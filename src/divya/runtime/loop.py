"""The recurrent System-2 <-> System-1 loop.

This is the Level-2 architecture: System-2 sees the shared state, decides what System-1 should
be asked, the answer is written back into the state, and System-2 sees the new state. The loop
ends when System-2 says to, or when a guard stops it.

Three things about it are deliberate and worth stating up front.

**The baseline is the same code path.** Level 1 (System-2 -> Laya, single shot) is this loop
with ``max_turns=1`` and a single-shot turn mode. That is not a convenience -- it is what makes
the Level-1-vs-Level-2 comparison an apples-to-apples measurement rather than a comparison of
two different programs that differ in more than the variable under test. Everything except the
turn budget is held constant.

**Termination is total.** Every exit sets exactly one :class:`TerminationStatus`. A run that
falls out of the loop without one is a bug, and ``tests/test_runtime_termination.py`` asserts
it. The guards are the guard: max turns, no new decisions requested, System-2 failing
repeatedly, and System-1 failing persistently each end the run in a *different, named* state,
so "it stopped" and "it gave up" and "it ran out of budget" are distinguishable after the fact.

**Degradation is a first-class path, not an exception path.** If System-1 is missing, the loop
continues with System-2 alone and marks the run degraded. If System-2 is missing, the loop
falls back to the heuristic policy and says so in the trace. Neither case silently produces a
confident-looking answer, because a terminal that degrades invisibly is worse than one that
is down.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import Protocol as TypingProtocol

from divya.protocol.loader import ProtocolError, get_spec, load_protocol
from divya.protocol.schema import Protocol as DecisionProtocol
from divya.runtime.state import (
    Observation,
    SharedState,
    StateBuilder,
    System1Record,
    System2Record,
    TerminationStatus,
)
from divya.system1.laya_adapter import LayaSystem1, NullSystem1
from divya.system2.provider import (
    HeuristicProvider,
    ProviderInfo,
    System2Error,
    System2Provider,
    build_provider,
)
from divya.system2.turn import System2Request, TurnKind

log = logging.getLogger(__name__)

#: Above this many consecutive System-2 failures the run is abandoned. Two is enough to
#: distinguish a transient hiccup from a model that cannot do the job; a third attempt just
#: burns wall-clock to reach the same conclusion.
MAX_CONSECUTIVE_SYSTEM2_FAILURES = 2

#: Above this many consecutive System-1 failures the loop stops escalating. Asking a broken
#: engine the same question five times is not persistence, it is a hang with extra steps.
MAX_CONSECUTIVE_SYSTEM1_FAILURES = 2


class System1(TypingProtocol):
    def is_available(self) -> bool: ...
    def answer(
        self,
        state_text: str,
        spec: Any,
        *,
        only: list[str] | None = None,
        turn_index: int = 0,
        protocol_version: str = "",
        timeout_note: str = "",
    ) -> System1Record: ...


@dataclass
class LoopConfig:
    """Everything that varies between evaluation arms, in one inspectable place."""

    max_turns: int = 4
    min_confidence: float = 0.55
    system2_timeout_s: float = 90.0
    system1_timeout_s: float = 120.0
    allow_escalation: bool = True
    #: Run exactly one System-1 pass over the tier-1 decisions and stop, with no reasoning model
    #: involved. This is the measured default (D-012): arm A scored identically to arm C on
    #: every quality and calibration metric at a quarter of the latency. It is a named mode
    #: rather than `max_turns=0`, because a zero turn budget means "do nothing", not "ask
    #: System-1 once", and conflating the two makes the config unreadable.
    system1_only: bool = False
    max_consecutive_system1_failures: int = MAX_CONSECUTIVE_SYSTEM1_FAILURES
    max_consecutive_system2_failures: int = MAX_CONSECUTIVE_SYSTEM2_FAILURES
    fallback_to_heuristic: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_turns": self.max_turns,
            "min_confidence": self.min_confidence,
            "system2_timeout_s": self.system2_timeout_s,
            "allow_escalation": self.allow_escalation,
            "system1_only": self.system1_only,
            "fallback_to_heuristic": self.fallback_to_heuristic,
        }


@dataclass
class LoopResult:
    state: SharedState
    builder: StateBuilder
    degraded: list[str] = field(default_factory=list)

    @property
    def terminated(self) -> bool:
        return self.state.termination is not None

    def to_json(self) -> str:
        return self.state.model_dump_json(indent=2)

    def metrics(self) -> dict[str, Any]:
        """Per-run cost and behaviour counters. The evaluation aggregates these across runs."""
        s2 = self.state.system2_records
        s1 = self.state.system1_records
        return {
            "task_id": self.state.task_id,
            "termination": self.state.termination.value if self.state.termination else None,
            "turns": self.state.turn_index,
            "system1_calls": len(s1),
            "system1_failures": sum(1 for r in s1 if r.error),
            "system2_calls": len(s2),
            "system2_failures": sum(1 for r in s2 if r.error),
            "system1_latency_ms": round(sum(r.latency_ms for r in s1), 1),
            "system2_latency_ms": round(sum(r.latency_ms for r in s2), 1),
            "prompt_tokens": sum(r.prompt_tokens for r in s2),
            "completion_tokens": sum(r.completion_tokens for r in s2),
            "repairs": sum(1 for r in s2 if r.repaired),
            "max_system1_confidence": round(self.state.max_confidence, 4),
            "disagreements": len(self.state.disagreements),
            "degraded": self.degraded,
        }


def _options_for(q: Any) -> list[str]:
    """The option labels for a question, in the order the engine will see them.

    Rendered here rather than inside the pydantic model because the model stores a
    ``dict | list | None`` union, and a menu built from a union is a menu that can raise at
    three different call sites depending on the question type.
    """
    if q.type.value == "choice":
        return sorted(q.criteria or {})
    if q.type.value == "score":
        return [str(c) for c in (q.criteria or [])]
    return sorted((q.labels or {"false": "", "true": ""}).values())


class DivyaRuntime:
    """Owns the loop. Construct with a protocol and providers; call :meth:`run`."""

    def __init__(
        self,
        protocol: DecisionProtocol | None = None,
        system2: System2Provider | None = None,
        system1: System1 | None = None,
        config: LoopConfig | None = None,
    ) -> None:
        self.protocol = protocol or load_protocol()
        self.config = config or LoopConfig()
        self._system2 = system2
        self._system1 = system1
        self.degraded: list[str] = []

    # -- lazily built so importing this module never loads a 300 MB engine --

    @property
    def system1(self) -> System1:
        if self._system1 is None:
            if LayaSystem1().is_available():
                self._system1 = LayaSystem1()
            else:
                self._system1 = NullSystem1()
                self.degraded.append("system1: laya not installed; running without System-1")
                log.warning(self.degraded[-1])
        return self._system1

    @property
    def system2(self) -> System2Provider:
        if self._system2 is None:
            self._system2 = build_provider()
        return self._system2

    # -- protocol helpers --------------------------------------------------

    def _available_decisions(self) -> list[dict[str, Any]]:
        """The decision menu handed to System-2, with tiers so it can escalate deliberately."""
        menu: list[dict[str, Any]] = []
        for spec in self.protocol.specs:
            for q in spec.questions:
                menu.append(
                    {
                        "name": q.name,
                        "type": q.type.value,
                        "tier": q.tier,
                        "spec": spec.name,
                        "purpose": q.purpose,
                        "options": _options_for(q),
                    }
                )
        return menu

    def _spec_for(self, decision_names: list[str]) -> tuple[Any, list[str]]:
        """Group requested decisions into the spec(s) that define them.

        Escalating into two specs costs two System-1 calls; batching them into one costs one.
        The first request of a run takes every spec that owns a requested decision, and
        escalations take only the spec that owns the newly-requested ones.
        """
        owners: dict[str, list[str]] = {}
        for spec in self.protocol.specs:
            for q in spec.questions:
                if q.name in decision_names:
                    owners.setdefault(spec.name, []).append(q.name)
        if not owners:
            raise ProtocolError(f"none of {decision_names} exist in the protocol")
        # Prefer a single spec covering the most requested decisions, to minimise engine calls.
        best = max(owners, key=lambda s: (len(owners[s]), s))
        return get_spec(self.protocol, best), owners[best]

    def _tier_of(self, name: str) -> int:
        for spec in self.protocol.specs:
            for q in spec.questions:
                if q.name == name:
                    return q.tier
        return 99

    # -- the loop ----------------------------------------------------------

    async def run(
        self,
        *,
        domain: str,
        objective: str,
        observations: list[Observation],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> LoopResult:
        state = SharedState(
            protocol_version=self.protocol.protocol_version,
            domain=domain,
            objective=objective,
            config=self.config.as_dict(),
        )
        b = StateBuilder(state)
        for obs in observations:
            b.add_observation(obs)

        emit = on_event or (lambda _e: None)

        if not self.system1.is_available():
            self.degraded.append("system1: engine unavailable at run start")

        if self.config.system1_only:
            return self._run_system1_only(state, b, emit)

        consecutive_s2_fail = 0
        consecutive_s1_fail = 0
        seen_request_sets: set[tuple[str, ...]] = set()
        last_s1_error: str = ""
        system2 = self.system2

        for _ in range(self.config.max_turns):
            turn = state.turn_index
            available = self._available_decisions()
            eligible = self._eligible_decisions(state)

            request = System2Request(
                task=objective,
                protocol_version=self.protocol.protocol_version,
                available_decisions=[d for d in available if d["name"] in eligible],
                state=self._model_view(state),
                turn_index=turn,
                max_turns=self.config.max_turns,
                min_confidence=self.config.min_confidence,
            )

            info: ProviderInfo = getattr(system2, "info", ProviderInfo("unknown", None, False))
            try:
                result = await asyncio.wait_for(
                    system2.complete(request, timeout=self.config.system2_timeout_s),
                    timeout=self.config.system2_timeout_s + 5,
                )
            except (System2Error, TimeoutError, OSError) as exc:
                consecutive_s2_fail += 1
                b.record_system2(
                    System2Record(
                        turn_index=turn,
                        provider=info.name,
                        model=info.model,
                        is_model=bool(getattr(info, "is_model", False)),
                        kind="error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                if consecutive_s2_fail >= self.config.max_consecutive_system2_failures:
                    if self.config.fallback_to_heuristic and not isinstance(
                        system2, HeuristicProvider
                    ):
                        self.degraded.append("system2: failed; falling back to heuristic policy")
                        log.warning(self.degraded[-1])
                        system2 = HeuristicProvider()
                        consecutive_s2_fail = 0
                        continue
                    b.terminate(
                        TerminationStatus.ERROR,
                        f"System-2 failed {consecutive_s2_fail} consecutive times: {exc}",
                    )
                    return LoopResult(state=state, builder=b, degraded=list(self.degraded))
                continue

            consecutive_s2_fail = 0
            b.record_system2(
                System2Record(
                    turn_index=turn,
                    provider=result.info.name,
                    model=result.info.model,
                    is_model=result.info.is_model,
                    kind=result.turn.kind.value,
                    decisions=result.turn.decisions,
                    conclusion=result.turn.conclusion,
                    confidence=result.turn.confidence,
                    rationale=result.turn.rationale,
                    latency_ms=result.latency_ms,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    repaired=result.repaired,
                    raw_response=result.raw_response,
                    error=result.error,
                )
            )
            emit({"type": "system2", "turn": turn, "action": result.turn.summary()})

            if result.turn.kind is TurnKind.FINISH:
                b.set_outcome(
                    result.turn.conclusion,
                    result.turn.confidence,
                    uncertainty=self._uncertainty(state),
                )
                b.terminate(TerminationStatus.FINISHED, "System-2 concluded")
                return LoopResult(state=state, builder=b, degraded=list(self.degraded))

            if result.turn.kind is TurnKind.ABSTAIN:
                b.set_outcome(
                    result.turn.conclusion or "System-2 abstained.",
                    0.0,
                    uncertainty=self._uncertainty(state),
                )
                b.terminate(TerminationStatus.ABSTAINED, "System-2 abstained")
                return LoopResult(state=state, builder=b, degraded=list(self.degraded))

            # --- call_system1 ---------------------------------------------
            wanted = [d for d in result.turn.decisions if d in eligible]
            unknown = [d for d in result.turn.decisions if d not in eligible]
            if unknown:
                # A hallucinated decision name is a protocol violation, not a retryable error.
                b.state.errors.append(
                    f"System-2 requested unavailable decisions {unknown}; ignored"
                )
            if not wanted:
                b.terminate(
                    TerminationStatus.ABSTAINED,
                    "System-2 asked for a System-1 call with no valid decisions",
                )
                return LoopResult(state=state, builder=b, degraded=list(self.degraded))

            key = tuple(sorted(wanted))
            if key in seen_request_sets:
                # Attribute the stop to the actual cause. If System-1 has been failing, the
                # repeated request is a consequence of a broken engine, not of a stuck
                # reasoning model, and reporting MAX_TURNS would tell an operator to raise a
                # budget when the real fix is to restart the engine.
                if consecutive_s1_fail > 0:
                    b.terminate(
                        TerminationStatus.ERROR,
                        f"System-1 failed {consecutive_s1_fail} consecutive times and the "
                        f"retry of {list(key)} hit the no-repeat guard: {last_s1_error}",
                    )
                else:
                    b.terminate(
                        TerminationStatus.MAX_TURNS,
                        f"System-2 repeated the identical request {list(key)}; refusing to loop",
                    )
                return LoopResult(state=state, builder=b, degraded=list(self.degraded))
            seen_request_sets.add(key)

            try:
                spec, only = self._spec_for(wanted)
            except ProtocolError as exc:
                b.terminate(TerminationStatus.ERROR, str(exc))
                return LoopResult(state=state, builder=b, degraded=list(self.degraded))

            try:
                rec = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.system1.answer,
                        state.observation_text(),
                        spec,
                        only=only,
                        turn_index=turn,
                        protocol_version=self.protocol.protocol_version,
                    ),
                    timeout=self.config.system1_timeout_s,
                )
            except (TimeoutError, OSError) as exc:
                rec = System1Record(
                    turn_index=turn,
                    decision_names=only,
                    spec_name=spec.name,
                    spec_version=spec.version,
                    protocol_version=self.protocol.protocol_version,
                    request={},
                    raw_response={},
                    answers={},
                    error=f"System-1 timed out after {self.config.system1_timeout_s}s: {exc}",
                )
            b.record_system1(rec)
            emit(
                {
                    "type": "system1",
                    "turn": turn,
                    "spec": f"{spec.name}@{spec.version}",
                    "decisions": only,
                    "checkpoint": rec.checkpoint,
                    "latency_ms": round(rec.latency_ms, 1),
                    "error": rec.error,
                    "answers": rec.answers,
                }
            )

            if rec.error:
                consecutive_s1_fail += 1
                last_s1_error = rec.error
                # Record the degradation on the *first* failure, not when the threshold is
                # reached. A run that retried once and then stopped still had a degraded
                # System-1, and a report that only shows degradation at the point of giving up
                # hides the single most diagnostic fact about the failure.
                self.degraded.append(f"system1: {rec.error}")
                if consecutive_s1_fail >= self.config.max_consecutive_system1_failures:
                    self.degraded.append(f"system1: repeated failure ({rec.error})")
                    b.terminate(
                        TerminationStatus.ERROR,
                        f"System-1 failed {consecutive_s1_fail} consecutive times: {rec.error}",
                    )
                    return LoopResult(state=state, builder=b, degraded=list(self.degraded))
            else:
                consecutive_s1_fail = 0

            b.advance()

        b.terminate(
            TerminationStatus.MAX_TURNS,
            f"Reached max_turns={self.config.max_turns} without a conclusion",
        )
        return LoopResult(state=state, builder=b, degraded=list(self.degraded))

    def _run_system1_only(
        self, state: SharedState, b: StateBuilder,
        emit: Callable[[dict[str, Any]], None],
    ) -> LoopResult:
        """One typed-decision pass, no reasoning model, no loop.

        The conclusion is the typed answers themselves plus the engine's own confidence, not a
        model-written sentence: on this task the engine's calibrated answer was strictly better
        than anything a 3B model added on top of it, and attributing the output to a reasoner
        that did not contribute would misdescribe where it came from.
        """
        spec = self.protocol.by_name("event_triage")
        tier1 = [q.name for q in spec.questions if q.tier == 1]
        try:
            rec = self.system1.answer(
                state.observation_text(), spec, only=tier1, turn_index=0,
                protocol_version=self.protocol.protocol_version,
            )
        except Exception as exc:
            b.terminate(TerminationStatus.ERROR, f"System-1 raised: {type(exc).__name__}: {exc}")
            return LoopResult(state=state, builder=b, degraded=list(self.degraded))
        b.record_system1(rec)
        emit({"type": "system1", "spec": f"{spec.name}@{spec.version}",
              "decisions": tier1, "checkpoint": rec.checkpoint,
              "latency_ms": round(rec.latency_ms, 1), "error": rec.error,
              "answers": rec.answers})
        if rec.error:
            b.terminate(TerminationStatus.ERROR, f"System-1 failed: {rec.error}")
            return LoopResult(state=state, builder=b, degraded=list(self.degraded))

        answers = rec.answers
        conf = max((rec.confidence(n) for n in answers), default=0.0)
        parts: list[str] = []
        if choice := (answers.get("event_type") or {}).get("choice"):
            parts.append(f"event type: {choice}")
        if isinstance((mat := answers.get("is_material") or {}).get("noul"), int | float):
            parts.append(f"material: P={mat['noul']:.2f}")
        if isinstance((lvl := answers.get("materiality") or {}).get("score"), int | float):
            parts.append(f"materiality level: {round(float(lvl['score']))}")
        b.set_outcome("; ".join(parts) or "no System-1 answer", conf, self._uncertainty(state))
        b.terminate(
            TerminationStatus.FINISHED,
            "System-1 only mode: one typed pass, no reasoning model (D-012)",
        )
        return LoopResult(state=state, builder=b, degraded=list(self.degraded))

    # -- helpers -----------------------------------------------------------

    def _eligible_decisions(self, state: SharedState) -> set[str]:
        """Which decisions System-2 is allowed to request this turn.

        A decision already answered is ineligible -- asking again costs a full forward pass to
        learn something we know, and repeated identical requests are the clearest signal of a
        model stuck in a loop. Escalation into higher tiers is allowed only while
        ``allow_escalation`` is on, which is what separates arm C from arm D.
        """
        all_decisions = {q.name for s in self.protocol.specs for q in s.questions}
        answered = set(state.latest_system1)
        eligible = all_decisions - answered
        if not self.config.allow_escalation:
            eligible &= {n for n in eligible if self._tier_of(n) == 1}
        return eligible

    def _model_view(self, state: SharedState) -> dict[str, Any]:
        """The slice of state the reasoning model sees.

        Deliberately excludes raw System-1 payloads and the transition trace. The model needs
        the answers, the provenance, and what has already been asked -- not the full machinery,
        which would blow the context budget and invite the model to reason about its own
        plumbing. The trace stays available to the human via the CLI and terminal.
        """
        observations = [
            {
                "observation_id": o.observation_id,
                "source_id": o.source_id,
                "source_url": o.source_url,
                "published_at": o.published_at,
                "retrieved_at": o.retrieved_at,
                "is_simulated": o.is_simulated,
                "excerpt": o.content[:1200],
            }
            for o in state.observations
        ]
        return {
            "domain": state.domain,
            "objective": state.objective,
            "turn": state.turn_index,
            "turns_remaining": self.config.max_turns - state.turn_index,
            "observations": observations,
            "system1_results": state.latest_system1,
            "requested_decisions": state.requested_decisions,
            "unresolved_questions": state.unresolved_questions,
            "disagreements": [
                {"decision": d.decision, "note": d.note} for d in state.disagreements
            ],
            "confidence_so_far": round(state.max_confidence, 4),
        }

    def _uncertainty(self, state: SharedState) -> str:
        reasons: list[str] = []
        if state.max_confidence < self.config.min_confidence:
            reasons.append(
                f"max System-1 confidence {state.max_confidence:.2f} is below the "
                f"{self.config.min_confidence:.2f} threshold"
            )
        failed = [r for r in state.system1_records if r.error]
        if failed:
            reasons.append(f"{len(failed)} System-1 call(s) returned an error")
        if any(not o.is_simulated for o in state.observations) and not state.is_fresh:
            reasons.append("one or more observations are older than the freshness window")
        if not reasons:
            return "none recorded"
        return "; ".join(reasons)


# -- trace persistence ----------------------------------------------------


def write_trace(result: LoopResult, path: str | Path) -> Path:
    """Write the full run to disk as one JSON document.

    The repository is the memory: a run that is not written down did not happen, and cannot be
    re-examined when someone asks six weeks later why the system abstained.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metrics": result.metrics(),
        "state": json.loads(result.state.model_dump_json()),
        "trace_digest": result.builder.trace_digest(),
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def read_trace(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
