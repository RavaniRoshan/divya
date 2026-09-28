"""Hierarchical routing tests.

Routing is the one place in this system where the runtime chooses *which questions the engine
is asked*, so it is the place where a bug could quietly become a decision the engine never
made. These tests pin the properties that prevent that:

1. **A confident "no event here" short-circuits, and `event_type` is never asked.**
2. **An unsure gate, or a "yes", falls through and the choice head decides.**
3. **Nothing is ever classified by the runtime itself** -- a resolved case records the gate's
   own answer, and says which gate produced it.

Note the polarity: routing short-circuits on **no**, not yes. 77% of a real Indian
announcement feed carries no corporate event, so that is the common case and the one worth
spending no forward pass on. "There is no event here" is also itself the answer, and it is
recorded as an absence rather than as a class, so nothing downstream can mistake one for the
other.

Stubbed, so the suite runs in well under a second. The real-engine cost of routing is measured
by the harness, not here.
"""

from __future__ import annotations

import pytest

from divya.protocol.routing import RoutedDecider, _confidence


class ScriptedSystem1:
    """Answers only for what was asked, at scripted confidence per decision.

    Answering un-asked questions would make every routing test pass regardless of routing,
    because the gate would appear to resolve things it was never told about.
    """

    def __init__(self, gate: float = 0.95, choice: str = "fundraise"):
        # `gate` IS the noul value. An earlier version took (probability, truth) and inverted
        # it, so "an unsure gate" silently became exactly-on-threshold and the fall-through
        # test was asserting the opposite of what it said.
        self.gate = gate
        self.choice = choice
        self.calls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def answer(self, state_text, spec, *, only=None, turn_index=0, protocol_version="", timeout_note=""):
        from divya.runtime.state import System1Record

        names = sorted(spec.to_laya(only=only))
        self.calls.append(names)
        answers: dict[str, object] = {}
        for n in names:
            if n == "event_type_determinable":
                v = self.gate
                answers[n] = {"type": "noul", "noul": v, "confidence": v}
            elif n == "event_type":
                answers[n] = {
                    "type": "choice", "choice": self.choice,
                    "probabilities": {self.choice: 0.9}, "confidence": 0.9,
                }
            else:
                answers[n] = {"type": "noul", "noul": 0.9, "confidence": 0.9}
        return System1Record(
            turn_index=turn_index, decision_names=names, spec_name=spec.name,
            spec_version=spec.version, protocol_version=protocol_version,
            state_digest="", request={}, raw_response={"answers": answers},
            answers=answers, checkpoint="stub", latency_ms=1.0,
        )


TEXT = "The Company approved the acquisition of 51 per cent of Target Limited for Rs 2,300 crore."


def _value(res):
    return res.answers["event_type"]["choice"]


# --- the resolution rule --------------------------------------------------


def test_confident_no_event_short_circuits_and_the_classification_is_skipped():
    """The whole point. A decisive "no event" must SAVE the question, not merely precede it."""
    stub = ScriptedSystem1(gate=0.20, choice="capital_event")  # gate says NOT determinable
    res = RoutedDecider(system1=stub, gate_confidence=0.70).decide(TEXT)

    assert _value(res) is None, "an unclassifiable document is not a class"
    assert res.resolved_by["event_type"] == "gate:event_type_determinable"
    # The choice head was never asked for event_type.
    assert all("event_type" not in c for c in stub.calls[1:]), stub.calls
    assert len(stub.calls) == 2, "gate stage, then whatever is left"


def test_a_yes_always_falls_through_to_the_choice_head():
    """A YES is not sufficient to name a class. Only a NO short-circuits."""
    stub = ScriptedSystem1(gate=0.95, choice="capital_event")
    res = RoutedDecider(system1=stub, gate_confidence=0.70).decide(TEXT)

    assert res.resolved_by == {}
    assert _value(res) == "capital_event"
    assert any("event_type" in c for c in stub.calls[1:])


def test_gate_threshold_is_configurable():
    """A gate below threshold must not short-circuit, however sure its polarity is."""
    strict = RoutedDecider(system1=ScriptedSystem1(gate=0.20), gate_confidence=0.90).decide(TEXT)
    assert strict.resolved_by == {}

    loose = RoutedDecider(system1=ScriptedSystem1(gate=0.20), gate_confidence=0.70).decide(TEXT)
    assert loose.resolved_by != {}


def test_a_gate_answering_nothing_does_not_resolve():
    """No answer is not a confident answer. Defaulting it to one would decide silently."""
    stub = ScriptedSystem1()
    stub.answer = lambda *a, **k: _record_with({})  # type: ignore[method-assign]
    res = RoutedDecider(system1=stub).decide(TEXT)
    assert res.resolved_by == {}


# --- integrity ------------------------------------------------------------


def test_every_asked_decision_survives_into_the_result():
    """A stage that dropped answers would look like a tighter pipeline, not a bug."""
    stub = ScriptedSystem1(gate=0.95)
    res = RoutedDecider(system1=stub).decide(TEXT)
    asked = {n for c in stub.calls for n in c}
    assert asked <= set(res.answers), f"dropped: {asked - set(res.answers)}"


def test_the_route_is_recorded_and_reproducible():
    stub = ScriptedSystem1(gate=0.95)
    res = RoutedDecider(system1=stub, gate_confidence=0.70).decide(TEXT)
    d = res.as_dict()
    for k in ("route_taken", "resolved_by", "stages", "total_ms", "degraded"):
        assert k in d
    assert d["route_taken"][0].startswith("gate:")
    assert len(d["stages"]) == 2
    # Each stage records what it asked, so a run can be reconstructed from its own output.
    for st in d["stages"]:
        assert "decisions" in st and "ms" in st


def test_a_routed_answer_records_which_question_produced_it():
    """A reader must be able to tell a gate decision from a classifier decision."""
    res = RoutedDecider(system1=ScriptedSystem1(gate=0.20)).decide(TEXT)
    assert res.answers["event_type"]["resolved_by"] == "gate:event_type_determinable"


def test_routing_never_invents_a_decision_the_engine_did_not_make():
    """The routed value is the engine's gate output, not a runtime inference.

    The route maps a gate's own answer onto a class name. It must not be able to produce a
    class the engine never mentioned, which is what would make this an 'agent' rather than a
    protocol.
    """
    res = RoutedDecider(system1=ScriptedSystem1(gate=0.20)).decide(TEXT)
    gate = res.answers["event_type_determinable"]
    assert gate["noul"] < 0.5, "the gate must actually have said no"
    # The runtime recorded an ABSENCE, not a class. Anything downstream that reads
    # `choice` must be able to see the difference.
    assert res.answers["event_type"]["choice"] is None
    assert res.answers["event_type"]["probabilities"] == {}


def test_degrades_rather_than_raising_when_the_engine_is_missing():
    from divya.system1.laya_adapter import NullSystem1

    res = RoutedDecider(system1=NullSystem1()).decide(TEXT)
    assert res.answers == {}
    assert res.degraded
    assert res.route_taken == []


# --- the confidence helper ------------------------------------------------


def test_confidence_reads_the_first_numeric_field():
    assert _confidence({"g": {"noul": 0.8}}, "g") == pytest.approx(0.8)
    assert _confidence({"g": {"confidence": 0.3}}, "g") == pytest.approx(0.3)
    assert _confidence({}, "g") is None
    assert _confidence({"g": {"noul": None}}, "g") is None


def _record_with(answers):
    from divya.runtime.state import System1Record

    return System1Record(
        turn_index=0, decision_names=list(answers), spec_name="event_triage",
        spec_version=4, protocol_version="0.1.0", state_digest="", request={},
        raw_response={}, answers=answers, checkpoint="stub", latency_ms=1.0,
    )
