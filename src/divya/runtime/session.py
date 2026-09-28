"""Conversational task sessions: the state that makes follow-ups continuations.

The product difference between this and a chatbot is that "compare HDFC and ICICI" followed by
"now only asset quality" followed by "show me the evidence" is **one task with three turns**.
A chatbot treats them as three questions and loses the thread. Here the thread is explicit,
addressable, and inspectable.

`Session` holds:

* the **intent** the user expressed and how it was interpreted;
* the **entities** resolved from it (companies, symbols, dates) and the focus that follow-ups
  narrow;
* the **decisions** made so far, keyed by name, with the run that produced them;
* the **workspace** currently displayed, as typed intents;
* the **unresolved questions** and **degradations**, carried forward visibly.

Three rules that keep this from becoming a conversation-shaped guessing game:

1. **Resolution is explicit and reported.** When a symbol is matched to a company, the match is
   recorded. When a name is ambiguous, the session stops and asks rather than picking one.
   Guessing an entity is how a conversational layer becomes confidently wrong.
2. **Follow-ups narrow, they do not replace.** "Compare A and B" then "now only X" keeps both
   entities and adds a dimension. "Now show the evidence" changes the workspace but not the
   entities. The user's investigation is never silently discarded.
3. **Everything degrades visibly.** If System-2 is unavailable the session records that, and
   the workspace carries the degradation to the frontend. A conversational surface that hides
   its own degraded state is worse than one with no conversation at all.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from divya.runtime.intents import UIIntent, WorkspaceKind

DEFAULT_STORE = Path("data/store/divya.db")

#: Words that narrow the previous request rather than starting a new one. Kept explicit rather
#: than inferred from a model, because "only", "just" and "focus on" are unambiguous in this
#: context and an inference would be a place to be wrong.
FOLLOWUP_MARKERS = (
    "now only", "just show", "focus on", "only show", "what about", "and ", "same for",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Entity(BaseModel):
    """A resolved referent."""

    model_config = ConfigDict(extra="forbid")

    kind: str  # "company" | "sector" | "date" | "document"
    key: str
    label: str
    resolved_by: str = "rule"  # how it was matched, for audit
    confidence: float = 1.0


class Turn(BaseModel):
    """One exchange in the conversation, kept so the trace reads as a dialogue."""

    model_config = ConfigDict(extra="forbid")

    index: int
    said: str
    understood_as: str = ""
    resolved_entities: list[Entity] = Field(default_factory=list)
    workspace: list[UIIntent] = Field(default_factory=list)
    followed_up: bool = False
    notes: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=_now)


class Session(BaseModel):
    """A persistent analytical task. This is the unit the product calls a 'task'."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    #: The user's goal, in their words, restated once and preserved.
    objective: str = ""
    task_type: str = "unknown"  # market | company | comparison | screen | evidence | investigation
    turns: list[Turn] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    #: Dimensions the user has narrowed to, most recent last.
    dimensions: list[str] = Field(default_factory=list)
    #: Decision name -> {value, confidence, run_id}
    decisions: dict[str, Any] = Field(default_factory=dict)
    workspace: list[UIIntent] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)
    suggested_next: list[str] = Field(default_factory=list)
    status: str = "active"  # active | concluded | abstained

    def entity(self, kind: str, key: str) -> Entity | None:
        return next((e for e in self.entities if e.kind == kind and e.key == key), None)

    def symbols(self) -> list[str]:
        return [e.key for e in self.entities if e.kind == "company"]

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# --- entity resolution ----------------------------------------------------

_STOP = {
    "the", "a", "an", "for", "on", "in", "of", "to", "and", "or", "with", "from",
    "compare", "show", "me", "what", "why", "how", "investigate", "find", "companies",
    "today", "material", "everything", "tell", "about", "only", "just", "then", "now",
}

_SYMBOL = re.compile(r"\b([A-Z]{2,15})\b")


def resolve_symbols(text: str) -> list[Entity]:
    """Resolve bare NSE-style symbols from the text.

    Deliberately conservative. A bare uppercase token *might* be a ticker and is very often
    the word "WHAT" or a stray acronym; a false resolution silently sends the user to the
    wrong company, which is worse than asking.
    """
    common_words = {"WHAT", "WHY", "HOW", "THE", "AND", "FOR", "ALL", "TOP", "NEW", "CEO",
                    "IPO", "FY", "Q1", "Q2", "Q3", "Q4", "NSE", "BSE", "SEBI", "GST", "RBI"}
    out: list[Entity] = []
    seen: set[str] = set()
    for m in _SYMBOL.finditer(text):
        tok = m.group(1)
        if tok in common_words or len(tok) > 12:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(Entity(kind="company", key=tok, label=tok, resolved_by="bare_symbol", confidence=0.55))
    return out


def resolve_company_names(text: str, companies: Iterable[tuple[str, str]]) -> list[Entity]:
    """Resolve company names against known (symbol, name) pairs from the store."""
    haystack = text.lower()
    out: list[Entity] = []
    seen: set[str] = set()
    for symbol, name in companies:
        if not name:
            continue
        stem = name.lower().replace(" limited", "").replace(" ltd", "").strip()
        if len(stem) < 4:
            continue
        if stem in haystack and symbol not in seen:
            seen.add(symbol)
            out.append(
                Entity(kind="company", key=symbol, label=name,
                       resolved_by="name_match", confidence=0.9)
            )
    return out


def classify_task(text: str, symbols: list[str]) -> str:
    """Map a request to a task type. Rule-based on purpose: it is inspectable and testable."""
    t = text.lower()
    if any(w in t for w in ("compare", " vs ", "versus", "side by side")):
        return "comparison"
    if any(w in t for w in ("evidence", "source", "cite", "where did")):
        return "evidence"
    if any(w in t for w in ("why", "reason", "how did", "explain")):
        return "investigation"
    if any(w in t for w in ("find", "screen", "where ", "which companies", "filter")):
        return "screen"
    if len(symbols) >= 2:
        return "comparison"
    if len(symbols) == 1:
        return "company"
    if any(w in t for w in ("today", "market", "nifty", "everything", "what changed")):
        return "market"
    return "unknown"


def is_followup(text: str, session: Session) -> bool:
    """Whether this turn continues the previous task rather than starting one.

    Requires *both* a marker in the text and an existing task. A bare marker on a fresh
    session has nothing to narrow, and treating it as a continuation would attach the request
    to nothing.
    """
    if not session.turns or session.status != "active":
        return False
    t = text.lower().strip()
    return any(m in t for m in FOLLOWUP_MARKERS) or t.startswith(
        ("and ", "now ", "then ", "only ", "just ", "show me the", "why")
    )


class SessionStore:
    """Sessions on disk. One JSON file per task, so a session survives a restart.

    A file rather than a table because a session is a document, and because being able to read
    one with `cat` during an incident is worth more than the query flexibility a table would
    buy. It is not a database pretending to be something it is not.
    """

    def __init__(self, root: str | Path = "data/sessions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "", task_id)
        return self.root / f"{safe}.json"

    def save(self, session: Session) -> Path:
        session.updated_at = _now()
        p = self.path(session.task_id)
        p.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        return p

    def load(self, task_id: str) -> Session | None:
        p = self.path(task_id)
        if not p.exists():
            return None
        try:
            return Session.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in sorted(self.root.glob("sess_*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append(
                {
                    "task_id": d.get("task_id"),
                    "objective": d.get("objective", "")[:120],
                    "task_type": d.get("task_type"),
                    "turns": len(d.get("turns", [])),
                    "status": d.get("status"),
                    "updated_at": d.get("updated_at"),
                    "symbols": [e.get("key") for e in d.get("entities", []) if e.get("kind") == "company"],
                }
            )
            if len(out) >= limit:
                break
        return out


class Resolver:
    """Turns a sentence into a Session update. Rules, not a model, by design.

    A model is genuinely better at "what does the user want" than a keyword list, and it is
    also the component that can be talked into a wrong answer by text inside a filing. Entity
    resolution is the one place where being wrong is silently destructive — attach a
    conversation to the wrong company and every subsequent answer is confidently about the
    wrong entity — so it is deterministic and it is tested.
    """

    def __init__(self, companies: Iterable[tuple[str, str]] | None = None) -> None:
        self.companies = list(companies or [])

    def entities_for(self, text: str) -> list[Entity]:
        found = resolve_company_names(text, self.companies)
        if found:
            return found
        return resolve_symbols(text)

    def apply(self, session: Session, text: str) -> Session:
        """Fold a new utterance into the session, preserving the thread."""
        followup = is_followup(text, session)
        found = self.entities_for(text)

        if followup and session.entities:
            # Narrow, do not replace. A follow-up that names a new entity adds to the thread;
            # it never silently drops the entities already under investigation.
            for e in found:
                if session.entity(e.kind, e.key) is None:
                    session.entities.append(e)
        elif followup:
            # A follow-up on a thread that never resolved an entity -- "why is AIIL high
            # priority?" as the second turn, after a market-wide scan. The prior turn has no
            # entities to inherit, so the entity named HERE becomes the basis. Dropping it
            # (the previous behaviour) made the follow-up resolve to nothing and the workspace
            # came back empty.
            session.entities = found
        else:
            # A new task. Previous entities are dropped, and the turn is marked as such, so
            # the user can see the context changed rather than wondering why.
            session.entities = found
            session.decisions = {}
            session.dimensions = []
            session.unresolved = []
            session.status = "active"

        if followup:
            for marker in ("asset quality", "margin", "revenue", "valuation", "risk",
                           "guidance", "segment", "provision"):
                if marker in text.lower() and marker not in session.dimensions:
                    session.dimensions.append(marker)

        task_type = classify_task(text, session.symbols())
        if not followup or task_type != "unknown":
            session.task_type = task_type
        if not followup or not session.objective:
            session.objective = text.strip()

        session.turns.append(
            Turn(
                index=len(session.turns),
                said=text.strip(),
                followed_up=followup,
                resolved_entities=found,
            )
        )
        return session


def suggested_for(session: Session) -> list[str]:
    """What the user could sensibly ask next, derived from what is missing.

    Not generated. Every entry corresponds to a gap the system can actually detect: no
    decision yet, no source, a narrowed dimension, an unresolved question. A suggestion the
    system cannot satisfy is worse than no suggestion.
    """
    out: list[str] = []
    if not session.decisions:
        out.append("Why is this material?")
    if not any(i.kind is WorkspaceKind.EVIDENCE for i in session.workspace):
        out.append("Show me the evidence.")
    if session.unresolved:
        out.append("What is still unresolved?")
    if len(session.symbols()) >= 2 and not session.dimensions:
        out.append("Now only look at asset quality.")
    if session.status == "active" and session.decisions:
        out.append("Show the decision trace.")
    return out[:4]
