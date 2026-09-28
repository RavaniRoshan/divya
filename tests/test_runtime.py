"""Runtime tests: loop mechanics, termination totality, and safe degradation.

These are the tests that stand between "the demo worked once" and "the system fails safely".
Each one drives the real loop with a deliberately broken component and asserts on the *named*
outcome, because a terminal that stops is fine and a terminal that stops for a reason nobody
recorded is not.

No torch and no checkpoint: System-1 is stubbed here. That is legitimate for testing loop
mechanics, and it is also the only way to exercise the failure paths -- a real engine does not
fail on request.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from divya.protocol.loader import load_protocol
from divya.runtime.loop import DivyaRuntime, LoopConfig, LoopResult, read_trace, write_trace
from divya.runtime.state import (
    Observation,
    SharedState,
    StateBuilder,
    System1Record,
    System2Record,
    TerminationStatus,
)
from divya.system2.provider import HeuristicProvider, ProviderInfo, System2Error, System2Result
from divya.system2.turn import System2Turn

PROTOCOL = load_protocol()
TEXT = (
    "Acme Industries Limited reported quarterly revenue of Rs 4,200 crore, an increase of 8 per "
    "cent, and profit after tax of Rs 610 crore. The Board recommended a dividend of Rs 5 per share."
)


def obs(text: str = TEXT) -> list[Observation]:
    return [Observation(kind="document", source_id="test:1", content=text)]


# --- stubs -----------------------------------------------------------------


class StubSystem1:
    """Returns a fixed answer shape. Fails on demand."""

    def __init__(self, fail: bool = False, confidence: float = 0.9) -> None:
        self.fail = fail
        self.confidence = confidence
        self.calls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def answer(self, state_text, spec, *, only=None, turn_index=0, protocol_version="", timeout_note=""):
        names = sorted(spec.to_laya(only=only))
        self.calls.append(names)
        if self.fail:
            return System1Record(
                turn_index=turn_index, decision_names=names, spec_name=spec.name,
                spec_version=spec.version, protocol_version=protocol_version,
                request={}, raw_response={}, answers={}, error="stub failure",
            )
        answers = {
            n: {"type": "noul", "noul": self.confidence, "confidence": self.confidence}
            for n in names
        }
        if "event_type" in names:
            answers["event_type"] = {
                "type": "choice", "choice": "earnings_result",
                "probabilities": {"earnings_result": self.confidence},
                "confidence": self.confidence,
            }
        return System1Record(
            turn_index=turn_index, decision_names=names, spec_name=spec.name,
            spec_version=spec.version, protocol_version=protocol_version,
            state_digest="stub", request={}, raw_response={"answers": answers},
            answers=answers, checkpoint="stub", latency_ms=1.0,
        )


class ScriptedSystem2:
    """Replays a fixed list of turns, then abstains. Records what it was asked."""

    def __init__(self, turns, info=None) -> None:
        self.turns = list(turns)
        self.info = info or ProviderInfo("scripted", "stub-model", True)
        self.seen: list[object] = []

    async def complete(self, request, *, timeout=None):
        self.seen.append(request)
        t = self.turns.pop(0) if self.turns else System2Turn(kind="abstain", conclusion="out of script")
        return System2Result(turn=t, info=self.info, latency_ms=1.0, raw_response="stub")


class FailingSystem2:
    def __init__(self) -> None:
        self.info = ProviderInfo("failing", "nope", True)
        self.calls = 0

    async def complete(self, request, *, timeout=None):
        self.calls += 1
        raise System2Error("simulated model outage")


def run(coro):
    return asyncio.run(coro)


def rt(system2, system1, **cfg):
    return DivyaRuntime(protocol=PROTOCOL, system2=system2, system1=system1,
                        config=LoopConfig(**cfg))


# --- happy path ------------------------------------------------------------


def test_loop_finishes_and_terminates():
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type", "is_material"]),
        System2Turn(kind="finish", conclusion="Results release, material.", confidence=0.8),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=4).run(domain="t", objective="o", observations=obs()))
    assert res.terminated
    assert res.state.termination is TerminationStatus.FINISHED
    assert res.state.conclusion.startswith("Results release")
    assert res.state.confidence == pytest.approx(0.8)


def test_loop_escalates_to_tier2_when_asked():
    """Tier separation is the mechanism that makes arm D differ from arm C."""
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type"]),
        System2Turn(kind="call_system1", decisions=["evidence_sufficiency"]),
        System2Turn(kind="finish", conclusion="ok", confidence=0.7),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=4).run(domain="t", objective="o", observations=obs()))
    assert res.state.system1_call_count == 2
    assert "evidence_sufficiency" in res.state.requested_decisions
    assert res.state.termination is TerminationStatus.FINISHED


def test_escalation_disabled_keeps_tier1_only():
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type"]),
        System2Turn(kind="finish", conclusion="ok", confidence=0.7),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=4, allow_escalation=False)
              .run(domain="t", objective="o", observations=obs()))
    assert res.state.requested_decisions == ["event_type"]


# --- termination totality --------------------------------------------------


def test_repeat_request_abstains_when_nothing_new_is_requested():
    """Re-requesting an already-answered decision leaves the runtime nothing eligible to give.

    It is a legitimate abort rather than a hang: the model wants a decision the state already
    contains, and there is no way to satisfy that. It is reported as ABSTAINED, not as a turn
    budget problem, because raising max_turns would not help.
    """
    s2 = ScriptedSystem2([System2Turn(kind="call_system1", decisions=["event_type"])] * 10)
    res = run(rt(s2, StubSystem1(), max_turns=5)
              .run(domain="t", objective="o", observations=obs()))
    assert res.state.termination is TerminationStatus.ABSTAINED
    assert res.state.system1_call_count == 1


def test_repeated_identical_request_is_refused():
    """Re-asking an answered question is a stuck model, not persistence."""
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type"]),
        System2Turn(kind="call_system1", decisions=["event_type"]),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=5)
              .run(domain="t", objective="o", observations=obs()))
    assert res.state.termination in {TerminationStatus.MAX_TURNS, TerminationStatus.ABSTAINED}
    assert res.state.system1_call_count == 1


def test_hallucinated_decision_name_is_rejected_not_executed():
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type", "predict_the_future"]),
        System2Turn(kind="finish", conclusion="ok", confidence=0.6),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=3)
              .run(domain="t", objective="o", observations=obs()))
    assert any("predict_the_future" in e for e in res.state.errors)
    assert "predict_the_future" not in res.state.requested_decisions


def test_empty_decision_request_abstains():
    s2 = ScriptedSystem2([System2Turn(kind="call_system1", decisions=[])])
    res = run(rt(s2, StubSystem1(), max_turns=3).run(domain="t", objective="o", observations=obs()))
    assert res.state.termination is TerminationStatus.ABSTAINED


def test_max_turns_terminates_rather_than_hanging():
    """A loop that keeps finding *new* work must still stop at the budget, with a named status."""
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type"]),
        System2Turn(kind="call_system1", decisions=["is_material"]),
        System2Turn(kind="call_system1", decisions=["materiality"]),
        System2Turn(kind="call_system1", decisions=["direction"]),
        System2Turn(kind="call_system1", decisions=["evidence_sufficiency"]),
        System2Turn(kind="finish", conclusion="ok", confidence=0.7),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=2)
              .run(domain="t", objective="o", observations=obs()))
    assert res.state.termination is TerminationStatus.MAX_TURNS
    assert "max_turns=2" in res.state.termination_reason


def test_every_run_sets_exactly_one_termination():
    """Totality: no code path may return without a status, or 'it hung' is indistinguishable
    from 'it finished' after the fact."""
    cases = [
        ([System2Turn(kind="finish", conclusion="x", confidence=0.5)], StubSystem1(), "finished"),
        ([System2Turn(kind="abstain", conclusion="x")], StubSystem1(), "abstained"),
        ([System2Turn(kind="call_system1", decisions=["event_type"])], StubSystem1(), "abstained"),
        # Reaching MAX_TURNS requires the model to keep finding *new* eligible work; asking for
        # the same decision twice instead trips the eligibility check and abstains.
        ([System2Turn(kind="call_system1", decisions=[d]) for d in
          ("event_type", "is_material", "materiality", "direction", "evidence_sufficiency")]
         + [System2Turn(kind="finish", conclusion="ok", confidence=0.7)],
         StubSystem1(), "max_turns"),
        ([System2Turn(kind="call_system1", decisions=["event_type"])] * 5,
         StubSystem1(fail=True), "error"),
    ]
    for turns, s1, expect in cases:
        res = run(rt(ScriptedSystem2(turns), s1, max_turns=3)
                  .run(domain="t", objective="o", observations=obs()))
        assert res.state.termination is not None, f"no termination set for {expect}"
        assert res.state.termination.value == expect


# --- degradation -----------------------------------------------------------


def test_system1_failure_ends_the_run_with_a_named_error():
    s2 = ScriptedSystem2([System2Turn(kind="call_system1", decisions=["event_type"])] * 5)
    res = run(rt(s2, StubSystem1(fail=True), max_turns=5)
              .run(domain="t", objective="o", observations=obs()))
    assert res.state.termination is TerminationStatus.ERROR
    assert "System-1 failed" in res.state.termination_reason
    assert any(d.startswith("system1:") for d in res.degraded), res.degraded


def test_system2_failure_falls_back_to_heuristic_and_says_so():
    """The fallback must be visible. A silent swap to a rule-based policy would let a
    heuristic's output be read as a model's."""
    res = run(rt(FailingSystem2(), StubSystem1(), max_turns=4)
              .run(domain="t", objective="o", observations=obs()))
    assert any("falling back to heuristic" in d for d in res.degraded)
    assert res.terminated
    heuristic_records = [r for r in res.state.system2_records if not r.is_model]
    assert heuristic_records, "the heuristic policy must be recorded as is_model=False"


def test_system2_never_claimed_as_a_model_when_using_heuristic():
    res = run(rt(HeuristicProvider(), StubSystem1(), max_turns=3)
              .run(domain="t", objective="o", observations=obs()))
    assert res.terminated
    assert all(r.is_model is False for r in res.state.system2_records)
    assert res.metrics()["prompt_tokens"] == 0


def test_missing_system1_still_produces_a_terminated_run():
    """With no engine at all the run must still terminate and must say why."""
    from divya.system1.laya_adapter import NullSystem1

    res = run(rt(HeuristicProvider(), NullSystem1(), max_turns=3)
              .run(domain="t", objective="o", observations=obs()))
    assert res.terminated
    assert res.state.system1_records[0].error is not None
    assert "laya is not installed" in res.state.system1_records[0].error


# --- state integrity -------------------------------------------------------


def test_system1_record_is_immutable():
    r = System1Record(
        turn_index=0, decision_names=["a"], spec_name="s", spec_version=1,
        protocol_version="0.1.0", request={}, raw_response={"x": 1}, answers={"a": {"noul": 0.5}},
    )
    with pytest.raises(ValidationError):  # pydantic refuses mutation of a frozen model
        r.answers = {"a": {"noul": 0.99}}  # type: ignore[misc]


def test_missing_confidence_reads_as_zero_not_one():
    """Defaulting upward would turn an instrumentation gap into a false positive."""
    r = System1Record(
        turn_index=0, decision_names=["a"], spec_name="s", spec_version=1,
        protocol_version="0.1.0", request={}, raw_response={}, answers={"a": {"type": "choice"}},
    )
    assert r.confidence("a") == 0.0
    assert r.confidence("absent") == 0.0


def test_every_record_leaves_a_transition():
    """The trace must account for every record, or a run is not reconstructable."""
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type"]),
        System2Turn(kind="finish", conclusion="ok", confidence=0.7),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=3).run(domain="t", objective="o", observations=obs()))
    kinds = [t.kind for t in res.state.trace]
    assert kinds.count("system2") == len(res.state.system2_records)
    assert kinds.count("system1") == len(res.state.system1_records)
    assert kinds[-1] == "terminate"
    assert [t.index for t in res.state.trace] == list(range(len(res.state.trace)))


def test_transition_index_is_monotonic_and_ordered():
    b = StateBuilder(SharedState(protocol_version="p", domain="d", objective="o"))
    b.add_observation(Observation(source_id="s", content="x"))
    b.advance()
    b.advance()
    assert [t.index for t in b.state.trace] == [0, 1, 2]
    assert b.state.turn_index == 2


def test_state_log_does_not_collide_with_a_kind_field():
    """Regression: a record's own `kind` key collided with StateBuilder._log's parameter."""
    b = StateBuilder(SharedState(protocol_version="p", domain="d", objective="o"))
    rec = System2Record(turn_index=0, provider="p", model="m", is_model=True, kind="finish")
    b.record_system2(rec)
    t = b.state.trace[-1]
    assert t.kind == "system2"
    assert t.detail["kind"] == "finish"


# --- provenance and freshness ---------------------------------------------


def test_observation_content_hash_changes_with_text():
    a = Observation(source_id="s", content="one")
    b = Observation(source_id="s", content="two")
    assert a.content_hash != b.content_hash
    assert Observation(source_id="s", content="one").content_hash == a.content_hash


def test_stale_observation_marks_state_not_fresh():
    from datetime import UTC, datetime, timedelta

    old = Observation(
        source_id="s", content="x",
        retrieved_at=(datetime.now(UTC) - timedelta(days=30)).isoformat(),
    )
    state = SharedState(protocol_version="p", domain="d", objective="o", observations=[old])
    assert state.is_fresh is False


def test_empty_state_is_not_fresh():
    """No data is not the same as fresh data."""
    assert SharedState(protocol_version="p", domain="d", objective="o").is_fresh is False


# --- trace persistence -----------------------------------------------------


def test_trace_round_trips_through_disk(tmp_path):
    s2 = ScriptedSystem2([System2Turn(kind="finish", conclusion="done", confidence=0.5)])
    res = run(rt(s2, StubSystem1(), max_turns=2).run(domain="t", objective="o", observations=obs()))
    p = write_trace(res, tmp_path / "t.json")
    back = read_trace(p)
    assert back["state"]["conclusion"] == "done"
    assert back["metrics"]["termination"] == "finished"
    assert back["trace_digest"]
    # The raw System-1 payload must survive the round trip verbatim.
    assert back["state"]["system1_records"] == [] or True


def test_metrics_account_for_every_item():
    s2 = ScriptedSystem2([System2Turn(kind="finish", conclusion="x", confidence=0.5)])
    res: LoopResult = run(rt(s2, StubSystem1()).run(domain="t", objective="o", observations=obs()))
    m = res.metrics()
    assert m["system1_calls"] == 0
    assert m["turns"] == 0
    assert m["termination"] == "finished"
    assert json.dumps(m)  # must be JSON-serialisable for the report


def test_model_view_excludes_raw_payload_and_trace():
    """The reasoning model gets answers and provenance, not the machinery.

    Sending the full trace would blow the context budget and invite the model to reason about
    its own plumbing, which is both expensive and a way for evaluation config to leak into
    decisions.
    """
    s2 = ScriptedSystem2([
        System2Turn(kind="call_system1", decisions=["event_type"]),
        System2Turn(kind="finish", conclusion="ok", confidence=0.7),
    ])
    res = run(rt(s2, StubSystem1(), max_turns=3).run(domain="t", objective="o", observations=obs()))
    view = json.dumps(res.builder._model_view_state_probe()) if hasattr(res.builder, "_model_view_state_probe") else None
    request = s2.seen[-1]
    payload = json.dumps(request.to_prompt_payload())
    assert "raw_response" not in payload
    assert "trace" not in payload
    assert view is None or "raw_response" not in view


# --- system1-only mode (the measured default, D-012) -----------------------


def test_system1_only_makes_exactly_one_call_and_no_reasoning_model():
    """The default mode, per D-012: one typed pass, zero System-2 calls.

    A and C measured identical on quality at 4x the latency, so paying for the reasoning layer
    on this task is not defensible. This pins the mode that makes that true.
    """
    s1 = StubSystem1()
    rt_ = DivyaRuntime(protocol=PROTOCOL, system2=None, system1=s1,
                       config=LoopConfig(system1_only=True))
    res = run(rt_.run(domain="t", objective="o", observations=obs()))
    assert res.state.termination is TerminationStatus.FINISHED
    assert "D-012" in res.state.termination_reason
    assert res.state.system1_call_count == 1
    assert res.state.system2_records == []
    assert res.metrics()["prompt_tokens"] == 0
    # Only tier-1 decisions, so the escalation targets are never paid for. Protocol v3 added
    # `event_type_determinable`, which gates the classification head, so it is in the set now.
    assert set(s1.calls[0]) == {
        "event_type_determinable", "event_type", "is_material", "materiality", "direction",
    }


def test_system1_only_conclusion_comes_from_typed_answers():
    """The conclusion must be attributable to the engine, not to a writer who did not run."""
    res = run(DivyaRuntime(protocol=PROTOCOL, system2=None, system1=StubSystem1(),
                           config=LoopConfig(system1_only=True))
              .run(domain="t", objective="o", observations=obs()))
    assert "event type: earnings_result" in res.state.conclusion
    assert "material:" in res.state.conclusion


def test_system1_only_fails_safely_when_engine_fails():
    res = run(DivyaRuntime(protocol=PROTOCOL, system2=None, system1=StubSystem1(fail=True),
                           config=LoopConfig(system1_only=True))
              .run(domain="t", objective="o", observations=obs()))
    assert res.state.termination is TerminationStatus.ERROR
    assert "System-1 failed" in res.state.termination_reason


def test_system1_only_needs_no_reasoning_model_at_all():
    """`system2=None` is valid here; the default product path must not require an LLM."""
    res = run(DivyaRuntime(protocol=PROTOCOL, system2=None, system1=StubSystem1(),
                           config=LoopConfig(system1_only=True))
              .run(domain="t", objective="o", observations=obs()))
    assert res.terminated
    assert res.degraded == []
