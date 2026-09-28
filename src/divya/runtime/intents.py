"""Typed UI intents: the boundary between the cognitive system and the frontend.

The System-2 layer decides *what analytical surface the user needs*. It does not decide what
the page looks like, and it never emits HTML, JSX, or code. It emits one of a fixed set of
typed intents, each carrying structured data that the frontend already knows how to render.

That boundary is the whole point. A language model that writes UI code is a liability: it
cannot be type-checked, it cannot be tested without rendering it, and every prompt becomes a
potential injection vector into the view layer. A closed enum of intents cannot be
misinterpreted, and every workspace it can produce was written and tested by a human.

**The enum is the product's information architecture.** Adding a value here is how the product
grows a new analytical surface; it is a deliberate, reviewable change, not something a model
discovers at runtime. That is intentional — see `docs/research/THESIS.md` §4.

An intent also carries *enough* to be worth rendering. `SHOW_COMPANY` with an empty payload is
not a workspace, it is a bug report. Every intent carries its own payload shape and the
constructors refuse to build an intent whose payload cannot render.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceKind(str, Enum):
    """The analytical surfaces the system can construct.

    Grouped by what the user is doing, not by what the backend happens to have: the names are
    the product's vocabulary, so they are written the way a user would say them.
    """

    #: A ranked view of everything that happened across the market or a universe.
    MARKET = "market"
    #: One company: its events, filings, decisions and fundamentals.
    COMPANY = "company"
    #: Two or more entities side by side on shared dimensions.
    COMPARISON = "comparison"
    #: A filtered universe from structured predicates.
    SCREEN = "screen"
    #: One event and every decision and source attached to it.
    EVENT = "event"
    #: The source filing with extracted context and the decisions made from it.
    DOCUMENT = "document"
    #: A persistent multi-step research task in progress.
    INVESTIGATION = "investigation"
    #: The structured record of what the cognitive loop did and why.
    DECISION_TRACE = "decision_trace"
    #: Sources, timestamps, confidence and provenance for a prior conclusion.
    EVIDENCE = "evidence"
    #: Standing alerts derived from prior decisions.
    ALERTS = "alerts"
    #: Nothing to show yet — an empty state that says why.
    EMPTY = "empty"


#: The intent names System-2 is allowed to emit, as the directive specifies them. Kept as a
#: module-level mapping so the backend, the API schema and the tests cannot drift.
UI_INTENTS: dict[str, WorkspaceKind] = {
    "SHOW_COMPANY": WorkspaceKind.COMPANY,
    "SHOW_COMPARISON": WorkspaceKind.COMPARISON,
    "SHOW_EVENT_STREAM": WorkspaceKind.MARKET,
    "SHOW_SCREEN": WorkspaceKind.SCREEN,
    "SHOW_FILING": WorkspaceKind.DOCUMENT,
    "SHOW_TIMELINE": WorkspaceKind.COMPANY,
    "SHOW_FINANCIALS": WorkspaceKind.COMPANY,
    "SHOW_DECISION_TRACE": WorkspaceKind.DECISION_TRACE,
    "SHOW_EVIDENCE": WorkspaceKind.EVIDENCE,
    "SHOW_ALERTS": WorkspaceKind.ALERTS,
    "SHOW_MARKET": WorkspaceKind.MARKET,
    "SHOW_INVESTIGATION": WorkspaceKind.INVESTIGATION,
    "SHOW_EVENT": WorkspaceKind.EVENT,
}


class UIIntent(BaseModel):
    """A single typed instruction to the frontend.

    `kind` selects the workspace component; `payload` is structured data for it; `reason` is
    one sentence a user can read to understand *why the surface changed*. A workspace that
    appears with no explanation reads as a glitch.
    """

    model_config = ConfigDict(extra="forbid")

    kind: WorkspaceKind
    title: str = ""
    reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Optional client-side routing target, so an analytical state is addressable and a
    #: workspace can be linked to or shared.
    route: str | None = None
    #: Set when the workspace is showing something incomplete, so the frontend can mark it
    #: partial rather than presenting a half-answer as a whole one.
    partial: bool = False
    #: Populated instead of `kind` when the system cannot construct a workspace. An intent
    #: that cannot be built is still an answer -- "I have no data for that" is a result.
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Workspace(BaseModel):
    """A sequence of intents plus the task context they belong to.

    More than one is legitimate: "why is HDFC highest priority?" after a market scan may
    legitimately want the event workspace *and* the evidence rail. The frontend renders them
    in order into the workspace region; the context rail is separate.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    intents: list[UIIntent] = Field(min_length=1)
    #: Follow-up suggestions the user can take in one keystroke. Derived from what the system
    #: knows is incomplete, not generated freehand.
    suggested_next: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)
    data_freshness: dict[str, str] = Field(default_factory=dict)

    @property
    def primary(self) -> UIIntent:
        return self.intents[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "intents": [i.as_dict() for i in self.intents],
            "suggested_next": self.suggested_next,
            "degraded": self.degraded,
            "data_freshness": self.data_freshness,
        }


# --- builders -------------------------------------------------------------
# Constructors rather than free-form dicts, so an unrenderable workspace cannot be produced by
# a caller. Each returns a `note` intent rather than raising: "I cannot show that" is a valid
# answer and the frontend has a state for it.


def empty(note: str, *, reason: str = "") -> UIIntent:
    return UIIntent(kind=WorkspaceKind.EMPTY, title="Nothing to show", reason=reason, note=note)


def market(
    events: list[dict[str, Any]],
    *,
    title: str = "Market",
    as_of: str = "",
    universe: str = "",
) -> UIIntent:
    if not events:
        return empty("No events in the current window.", reason="no events matched")
    return UIIntent(
        kind=WorkspaceKind.MARKET,
        title=title,
        reason=f"{len(events)} event(s)" + (f" across {universe}" if universe else ""),
        payload={"events": events, "as_of": as_of, "universe": universe},
        route="/market",
        partial=not as_of,
    )


def company(
    symbol: str,
    name: str,
    history: list[dict[str, Any]],
    *,
    decision: dict[str, Any] | None = None,
    as_of: str = "",
) -> UIIntent:
    if not history:
        return empty(
            f"No stored filings for {name or symbol}.", reason="symbol has no events in the store"
        )
    return UIIntent(
        kind=WorkspaceKind.COMPANY,
        title=f"{name} ({symbol})",
        reason=f"{len(history)} stored filing(s)",
        payload={
            "symbol": symbol, "company": name, "history": history,
            "decision": decision or {}, "as_of": as_of,
        },
        route=f"/company/{symbol}",
    )


def comparison(
    entities: list[dict[str, Any]],
    dimensions: list[str],
    *,
    title: str = "",
    as_of: str = "",
) -> UIIntent:
    if len(entities) < 2:
        return empty("Comparison needs at least two entities.", reason="only one entity resolved")
    return UIIntent(
        kind=WorkspaceKind.COMPARISON,
        title=title or f"{' vs '.join(e.get('symbol', '?') for e in entities)}",
        reason=f"{len(entities)} entities on {len(dimensions)} dimension(s)",
        payload={"entities": entities, "dimensions": dimensions, "as_of": as_of},
        route="/compare",
    )


def screen(
    rows: list[dict[str, Any]],
    predicate: str,
    *,
    title: str = "",
) -> UIIntent:
    return UIIntent(
        kind=WorkspaceKind.SCREEN,
        title=title or "Screen",
        reason=f"{len(rows)} match: {predicate}",
        payload={"rows": rows, "predicate": predicate},
        route="/screen",
        partial=not rows,
    )


def event(
    event_row: dict[str, Any],
    decision: dict[str, Any] | None,
    *,
    title: str = "",
) -> UIIntent:
    return UIIntent(
        kind=WorkspaceKind.EVENT,
        title=title or f"{event_row.get('symbol', '?')} event",
        reason="event, its decision, and its source",
        payload={"event": event_row, "decision": decision or {}},
        route=f"/event/{event_row.get('seq_id', '')}",
    )


def document(
    filing: dict[str, Any],
    *,
    decisions: list[dict[str, Any]] | None = None,
) -> UIIntent:
    return UIIntent(
        kind=WorkspaceKind.DOCUMENT,
        title=f"Filing — {filing.get('symbol', '?')}",
        reason="source text with the decisions made from it",
        payload={"filing": filing, "decisions": decisions or []},
        route=f"/document/{filing.get('seq_id', '')}",
    )


def decision_trace(trace: dict[str, Any], *, title: str = "Decision trace") -> UIIntent:
    return UIIntent(
        kind=WorkspaceKind.DECISION_TRACE,
        title=title,
        reason="what was asked, what was returned, and why the loop continued or stopped",
        payload={"trace": trace},
        route="/trace",
    )


def evidence(
    sources: list[dict[str, Any]],
    *,
    claim: str = "",
    title: str = "Evidence",
) -> UIIntent:
    if not sources:
        return empty("No source documents for this claim.", reason="no provenance recorded")
    return UIIntent(
        kind=WorkspaceKind.EVIDENCE,
        title=title,
        reason=f"{len(sources)} source(s)" + (f" for: {claim[:60]}" if claim else ""),
        payload={"sources": sources, "claim": claim},
        route="/evidence",
    )


def investigation(
    task_id: str,
    steps: list[dict[str, Any]],
    *,
    status: str = "in_progress",
) -> UIIntent:
    return UIIntent(
        kind=WorkspaceKind.INVESTIGATION,
        title=f"Investigation {task_id}",
        reason=status,
        payload={"steps": steps, "status": status},
        route="/investigate",
        partial=status == "in_progress",
    )


def alerts(rows: list[dict[str, Any]]) -> UIIntent:
    return UIIntent(
        kind=WorkspaceKind.ALERTS,
        title="Alerts",
        reason=f"{len(rows)} standing alert(s)",
        payload={"alerts": rows},
        route="/alerts",
        partial=not rows,
    )


#: Workspace kinds that require a live store to render. The frontend uses this to decide
#: whether to show a "no data connected" state rather than an empty table.
DATA_BACKED: frozenset[WorkspaceKind] = frozenset({
    WorkspaceKind.MARKET, WorkspaceKind.COMPANY, WorkspaceKind.COMPARISON,
    WorkspaceKind.SCREEN, WorkspaceKind.EVENT, WorkspaceKind.DOCUMENT,
    WorkspaceKind.INVESTIGATION,
})


IntentSource = Literal["system2", "heuristic", "rule", "fallback"]
