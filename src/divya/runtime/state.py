"""The shared state: the single object both systems read and write.

This is the whole contract between System-2 and System-1. There is no other channel: no prose
passed back and forth, no hidden conversation object, no "notes" string. If a fact influences
a decision, it is a field here; if it is not here, the trace cannot show it and the evaluation
cannot use it.

Three properties are load-bearing and each is enforced by construction rather than by
convention:

1. **System-1 output is immutable.** :class:`System1Record` stores the request, the raw
   response, and the parsed answer as separate fields, and exposes no mutation path. When
   System-2 disagrees with a System-1 answer, that disagreement is recorded *alongside* the
   answer (:class:`Disagreement`), never in place of it. An architecture whose value depends
   on the reasoning model's judgement must keep the judgement inspectable, or the evaluation
   is measuring an unfalsifiable thing.

2. **Every transition is reconstructable.** Each mutation appends a :class:`StateTransition`
   with a monotonic index. Replaying the transition log rebuilds the state exactly, so a bug
   reported weeks later can be diagnosed from the JSONL trace without the conversation that
   produced it.

3. **Termination is explicit and total.** A run ends in exactly one of four states. There is
   no path that returns without setting one, which is what makes "the loop hung" a
   distinguishable failure rather than a hang.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TerminationStatus(str, Enum):
    """Every run ends in exactly one of these. There is no 'still running' return value."""

    FINISHED = "finished"
    ABSTAINED = "abstained"
    MAX_TURNS = "max_turns"
    ERROR = "error"


class Observation(BaseModel):
    """One piece of the world the task is reasoning about.

    `content_hash` is over the exact text the System-1 engine saw. It exists so that a stale
    decision cannot be silently re-attributed to edited text: if the text changes, the hash
    changes, and a cache keyed on the decision alone becomes visibly wrong instead of quietly
    wrong.
    """

    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(default_factory=lambda: new_id("obs"))
    kind: str = "document"
    source_id: str
    source_url: str | None = None
    content: str
    retrieved_at: str = Field(default_factory=utc_now)
    published_at: str | None = None
    is_simulated: bool = False
    content_hash: str = ""

    def model_post_init(self, _context: Any) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:16]

    def age_seconds(self, now: datetime | None = None) -> float:
        try:
            ts = datetime.fromisoformat(self.retrieved_at)
        except ValueError:
            return 0.0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ((now or datetime.now(UTC)) - ts).total_seconds()


class System1Record(BaseModel):
    """One System-1 call: what was asked, what came back, verbatim.

    `raw_response` is the engine's own payload with no interpretation applied. `answers` is the
    parsed view of it. Both are kept because a parser bug and a model bug look identical in
    the parsed view and completely different in the raw one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(default_factory=lambda: new_id("s1"))
    turn_index: int
    decision_names: list[str]
    spec_name: str
    spec_version: int
    protocol_version: str
    state_digest: str = Field(default="", description="sha256 of the exact state text sent")
    request: dict[str, Any]
    raw_response: dict[str, Any]
    answers: dict[str, Any]
    checkpoint: str | None = None
    latency_ms: float = 0.0
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        return self.error is None

    def confidence(self, decision: str) -> float:
        """System-1's own confidence for one decision, or 0.0 if it did not report one.

        Zero rather than one when absent. A decision whose confidence cannot be read has not
        demonstrated it clears the bar; defaulting upward would convert an instrumentation
        gap into a false positive, which is the exact failure this system exists to avoid.
        """
        ans = self.answers.get(decision)
        if not isinstance(ans, dict):
            return 0.0
        for key in ("probability", "confidence", "score"):
            v = ans.get(key)
            if isinstance(v, int | float):
                return float(v)
        return 0.0

    def summary(self) -> dict[str, Any]:
        """Compact view for the trace, without dropping the raw payload's key names."""
        return {
            "record_id": self.record_id,
            "turn_index": self.turn_index,
            "spec": f"{self.spec_name}@{self.spec_version}",
            "decisions": self.decision_names,
            "checkpoint": self.checkpoint,
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
            "answers": self.answers,
        }


class System2Record(BaseModel):
    """One System-2 call, with enough metadata to reproduce it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(default_factory=lambda: new_id("s2"))
    turn_index: int
    provider: str
    model: str | None
    is_model: bool
    kind: str
    decisions: list[str] = Field(default_factory=list)
    conclusion: str = ""
    confidence: float = 0.0
    rationale: str = ""
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    repaired: bool = False
    raw_response: str = ""
    error: str | None = None
    created_at: str = Field(default_factory=utc_now)

    def summary(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "turn_index": self.turn_index,
            "provider": f"{self.provider}:{self.model}",
            "is_model": self.is_model,
            "kind": self.kind,
            "decisions": self.decisions,
            "confidence": round(self.confidence, 4),
            "latency_ms": round(self.latency_ms, 1),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "repaired": self.repaired,
            "error": self.error,
        }


class Disagreement(BaseModel):
    """Recorded where System-2 and System-1 do not agree.

    Exists as a first-class object rather than a flag on the System-1 record so that
    disagreement is countable. If the reasoning model quietly overrides System-1 twenty times
    in a hundred events, that is a finding about the architecture, and it has to be measurable.
    """

    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: new_id("dis"))
    decision: str
    system1_value: Any
    system2_view: str
    resolution: Literal["system1_kept", "abstained", "escalated"] = "system1_kept"
    note: str = ""
    created_at: str = Field(default_factory=utc_now)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(default_factory=lambda: new_id("hyp"))
    statement: str
    status: Literal["open", "supported", "refuted", "abandoned"] = "open"
    support: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class Contradiction(BaseModel):
    """Two observations that cannot both be true, surfaced rather than silently resolved."""

    model_config = ConfigDict(extra="forbid")

    contradiction_id: str = Field(default_factory=lambda: new_id("con"))
    claim: str
    sources: list[str] = Field(default_factory=list)
    resolution: str = ""
    created_at: str = Field(default_factory=utc_now)


class StateTransition(BaseModel):
    """One append-only mutation. Replaying these in order rebuilds the state exactly."""

    model_config = ConfigDict(extra="forbid")

    index: int
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)
    at: str = Field(default_factory=utc_now)


class SharedState(BaseModel):
    """The whole task state. Append-only in the ways that matter; see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    # --- identity ---------------------------------------------------------
    task_id: str = Field(default_factory=lambda: new_id("task"))
    protocol_version: str
    domain: str
    objective: str
    created_at: str = Field(default_factory=utc_now)

    # --- the world --------------------------------------------------------
    observations: list[Observation] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    # --- what the systems have done --------------------------------------
    turn_index: int = 0
    questions_asked: list[str] = Field(default_factory=list)
    requested_decisions: list[str] = Field(default_factory=list)
    system1_records: list[System1Record] = Field(default_factory=list)
    system2_records: list[System2Record] = Field(default_factory=list)

    # --- what is believed -------------------------------------------------
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)

    # --- where it ended ---------------------------------------------------
    confidence: float = 0.0
    uncertainty: str = ""
    conclusion: str = ""
    termination: TerminationStatus | None = None
    termination_reason: str = ""
    trace: list[StateTransition] = Field(default_factory=list)

    # --- provenance of the run itself -------------------------------------
    config: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------
    @property
    def latest_system1(self) -> dict[str, dict[str, Any]]:
        """Most recent answer per decision name.

        Keyed by decision rather than by call, because the runtime reasons about decisions and
        the evaluation compares decisions. The full history stays in ``system1_records``.
        """
        out: dict[str, dict[str, Any]] = {}
        for rec in self.system1_records:
            for name, ans in rec.answers.items():
                out[name] = ans if isinstance(ans, dict) else {"value": ans}
        return out

    @property
    def max_confidence(self) -> float:
        confs = [
            r.confidence(name)
            for r in self.system1_records
            for name in r.answers
        ]
        return max(confs) if confs else 0.0

    @property
    def system1_call_count(self) -> int:
        return len(self.system1_records)

    def observation_text(self) -> str:
        """Exactly the text handed to System-1. Digestmed alongside it in the record."""
        return "\n\n".join(obs.content for obs in self.observations)

    def state_digest(self) -> str:
        return hashlib.sha256(self.observation_text().encode("utf-8")).hexdigest()[:16]

    @property
    def is_fresh(self) -> bool:
        """False if any observation is missing or implausibly old.

        A terminal that shows a stale price as current is worse than one that shows nothing,
        so freshness is a computed property of the state rather than a field someone remembers
        to update.
        """
        if not self.observations:
            return False
        return all(obs.age_seconds() < MAX_OBSERVATION_AGE_S for obs in self.observations)


#: An observation older than this is surfaced as stale in the UI. Deliberately generous --
#: corporate filings do not move per second, and the point is to catch a dead ingestion job,
#: not to nag.
MAX_OBSERVATION_AGE_S = 7 * 24 * 3600


class StateBuilder:
    """The only sanctioned way to mutate a :class:`SharedState`.

    Every method records a transition. Mutating the state directly is not prevented at the type
    level -- pydantic models are mutable by default and forbidding that would be more ceremony
    than the bug it prevents is worth -- but it leaves no transition, and the trace check in
    ``tests/test_runtime_trace.py`` fails when a run produced transitions that do not account
    for the records present. The invariant is tested, not merely documented.
    """

    def __init__(self, state: SharedState) -> None:
        self.state = state

    def _log(self, kind: str, /, **detail: Any) -> StateTransition:
        # `kind` is positional-only so a record's own ``kind`` field can be splatted in
        # without colliding with this parameter.
        t = StateTransition(index=len(self.state.trace), kind=kind, detail=detail)
        self.state.trace.append(t)
        return t

    def add_observation(self, obs: Observation) -> Observation:
        self.state.observations.append(obs)
        self._log(
            "add_observation",
            observation_id=obs.observation_id,
            source_id=obs.source_id,
            content_hash=obs.content_hash,
            is_simulated=obs.is_simulated,
            chars=len(obs.content),
        )
        return obs

    def record_system1(self, rec: System1Record) -> System1Record:
        self.state.system1_records.append(rec)
        self.state.requested_decisions.extend(
            d for d in rec.decision_names if d not in self.state.requested_decisions
        )
        for d in rec.decision_names:
            if d not in self.state.questions_asked:
                self.state.questions_asked.append(d)
        if rec.error:
            self.state.errors.append(f"system1 {rec.record_id}: {rec.error}")
        self._log("system1", **rec.summary())
        return rec

    def record_system2(self, rec: System2Record) -> System2Record:
        self.state.system2_records.append(rec)
        if rec.error:
            self.state.errors.append(f"system2 {rec.record_id}: {rec.error}")
        self._log("system2", **rec.summary())
        return rec

    def record_disagreement(self, dis: Disagreement) -> Disagreement:
        self.state.disagreements.append(dis)
        self._log("disagreement", decision=dis.decision, resolution=dis.resolution)
        return dis

    def add_contradiction(self, con: Contradiction) -> Contradiction:
        self.state.contradictions.append(con)
        self._log("contradiction", claim=con.claim[:120])
        return con

    def set_unresolved(self, questions: list[str]) -> None:
        self.state.unresolved_questions = questions
        self._log("unresolved", count=len(questions))

    def advance(self) -> int:
        self.state.turn_index += 1
        self._log("advance_turn", turn_index=self.state.turn_index)
        return self.state.turn_index

    def terminate(self, status: TerminationStatus, reason: str = "") -> None:
        self.state.termination = status
        self.state.termination_reason = reason
        self._log("terminate", status=status.value, reason=reason)

    def set_outcome(self, conclusion: str, confidence: float, uncertainty: str = "") -> None:
        self.state.conclusion = conclusion
        self.state.confidence = max(0.0, min(1.0, confidence))
        self.state.uncertainty = uncertainty
        self._log("outcome", confidence=round(self.state.confidence, 4), conclusion=conclusion[:200])

    def to_json(self) -> str:
        return self.state.model_dump_json(indent=2, exclude_none=False)

    def trace_digest(self) -> str:
        return hashlib.sha256(
            json.dumps([t.model_dump() for t in self.state.trace], sort_keys=True).encode()
        ).hexdigest()[:16]
