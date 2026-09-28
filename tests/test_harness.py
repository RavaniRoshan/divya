"""Tests for the A/B/C/D evaluation harness.

The harness produced the headline number in the README, so an error in it does not merely
mis-report quality, it invalidates the claim the whole project is built to test. These tests
pin the three places a harness can lie:

* **scoring** — what a missing answer is worth, and what probability is read out of a payload;
* **aggregation** — arithmetic against a hand-built record set with a hand-computed answer;
* **arm dispatch** — that each arm runs the architecture it claims to run, and that an arm which
  answers nothing is reported as a *failed arm* rather than as a 0.000 accuracy.

The last point is the one that changed a real number. Arm B produced no answer on 120 of 120
items in `evals/results/real_eval.json`; without the `ARM_FAILED_NO_OUTPUT` flag its 0.000 reads
as "System-2 alone is useless" when it is actually a wiring failure.

No torch, no checkpoint, no network, no resident model: System-1 is the shared test double
re-exported from `tests/test_redteam.py` and System-2 is the shipped heuristic policy.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from divya.eval import harness as H
from divya.protocol.loader import load_protocol
from divya.system1.laya_adapter import NullSystem1
from test_redteam import StubSystem1

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "evals" / "datasets" / "nse_announcements_v1.jsonl"
EVAL_ARTIFACT = REPO / "evals" / "results" / "real_eval.json"
PROTOCOL = load_protocol()


# --- scoring ---------------------------------------------------------------


def test_score_event_type_reads_the_probability_of_the_chosen_option():
    ans = {"type": "choice", "choice": "capital_action",
           "probabilities": {"capital_action": 0.42, "other": 0.11}, "confidence": 0.9}
    assert H.score_event_type(ans) == ("capital_action", 0.42)


def test_score_event_type_falls_back_to_the_stated_confidence():
    ans = {"type": "choice", "choice": "other", "confidence": 0.31}
    assert H.score_event_type(ans) == ("other", 0.31)


def test_score_event_type_returns_none_for_every_shape_of_missing_answer():
    """A missing answer is wrong at zero confidence, never 'abstained'.

    Scoring it as abstention would reward a system that refuses to answer, which is not the
    question being measured; abstention is measured separately by risk-coverage.
    """
    for missing in (None, {}, {"type": "choice"}, {"choice": None}, {"probabilities": {}}):
        assert H.score_event_type(missing) == (None, 0.0)


def test_score_event_type_clamps_a_zero_probability_to_zero():
    assert H.score_event_type({"choice": "other", "probabilities": {"other": 0.0}}) == ("other", 0.0)
    assert H.score_event_type({"choice": "other", "probabilities": {"other": None}}) == ("other", 0.0)


def test_score_noul_thresholds_at_half():
    assert H.score_noul({"noul": 0.9}) == (1, 0.9)
    assert H.score_noul({"noul": 0.5}) == (1, 0.5)
    assert H.score_noul({"noul": 0.49}) == (0, 0.49)
    assert H.score_noul({"noul": 0.0}) == (0, 0.0)


def test_score_noul_accepts_the_probability_alias():
    assert H.score_noul({"probability": 0.77}) == (1, 0.77)
    assert H.score_noul({"noul": None, "probability": 0.2}) == (0, 0.2)


def test_score_noul_returns_none_when_nothing_was_answered():
    for missing in (None, {}, {"noul": None}, {"other": 1}):
        assert H.score_noul(missing) == (None, 0.0)


def test_score_score_returns_the_level_and_its_confidence():
    assert H.score_score({"score": 2.1995, "confidence": 0.61}) == (2.1995, 0.61)
    assert H.score_score({"score": 4}) == (4.0, 0.0)
    assert H.score_score({"score": 0, "confidence": None}) == (0.0, 0.0)


def test_score_score_returns_none_when_nothing_was_answered():
    for missing in (None, {}, {"score": None}, {"legend": []}):
        assert H.score_score(missing) == (None, 0.0)


# --- aggregation, against hand-computed values -----------------------------


#: A filing the System-1 test double classifies as `capital_action`, so the arm tests below
#: exercise a real answer rather than the double's "nothing matched" fallback.
DIVIDEND_FILING = (
    "Sun Pharma Limited has informed the Exchange that the Board of Directors has declared an "
    "interim dividend of Rs 12.50 per equity share for the quarter ended 30 June 2026."
)


def _item(id_: str, truth: str, stratum: str = "clear") -> H.Item:
    return H.Item(
        id=id_,
        stratum=stratum,
        content=DIVIDEND_FILING,
        labels={"event_type": truth},
        annotator_confidence=0.0,
    )


def _rec(
    id_: str,
    truth: str,
    p: float,
    stratum: str = "clear",
    *,
    wall_ms: float = 100.0,
    abstained: bool = False,
    s1_calls: int = 1,
    s2_calls: int = 0,
    s1_failures: int = 0,
    terminated_ok: bool = True,
    answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "item_id": id_,
        "answers": {
            "event_type": {
                "type": "choice",
                "choice": truth,
                "probabilities": {truth: p},
                "confidence": p,
            }
        },
        "abstained": abstained,
        "wall_ms": wall_ms,
        "system1_calls": s1_calls,
        "system2_calls": s2_calls,
        "system1_failures": s1_failures,
        "terminated_ok": terminated_ok,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "s1_ms": 90.0,
        "s2_ms": 0.0,
    }
    if answers is not None:
        body["answers"] = answers
    return body


#: Four records, worked out by hand:
#:   r1 right at 0.90   r2 right at 0.20   r3 wrong at 0.80   r4 silent (no answer at all)
#: accuracy           = 2/4 = 0.5
#: brier (multiclass) = mean((p - y)^2) = (0.01 + 0.64 + 0.64 + 0.0)/4 = 1.29/4 = 0.3225
#: ECE with 15 equal-width bins:
#:   bin [0.0,0.0667)  empty
#:   bin [0.0667,0.133) empty
#:   bin [0.2,0.2667)  n=1, conf 0.20, acc 1 -> |0.20-1| = 0.80, weight 1/4
#:   bin [0.8,0.8667)  n=1, conf 0.80, acc 0 -> |0.80-0| = 0.80, weight 1/4
#:   bin [0.9,0.9667)  n=1, conf 0.90, acc 1 -> |0.90-1| = 0.10, weight 1/4
#:   bin [0.0,0.0)     the silent record contributes p=0.0, y=0 -> conf 0, acc 0, gap 0
#:   ece = 0.25*(0.80+0.80+0.10+0) = 0.425
#: AURC: sort by confidence desc -> [0.9, 0.8, 0.2, 0.0]
#:   risks: 0/1=0, 1/2=0.5, 1/3=0.3333, 2/4=0.5 -> mean = 1.3333/4 = 0.3333
HAND_IDS = ("r1", "r2", "r3", "r4")
HAND_RECORDS = [
    _rec("r1", "capital_action", 0.90, wall_ms=100.0),
    _rec("r2", "capital_action", 0.20, wall_ms=200.0),
    _rec("r3", "leadership_change", 0.80, wall_ms=300.0, answers={
        "event_type": {"type": "choice", "choice": "other",
                       "probabilities": {"other": 0.80}, "confidence": 0.80}}),
    _rec("r4", "capital_action", 0.0, wall_ms=400.0, answers={}),
]
HAND_ITEMS = {i.id: i for i in (
    _item("r1", "capital_action"),
    _item("r2", "capital_action"),
    _item("r3", "capital_action"),
    _item("r4", "capital_action"),
)}


def test_aggregate_matches_the_hand_computed_values():
    out = H.aggregate(HAND_RECORDS, HAND_ITEMS)
    assert out["n_items"] == 4
    assert out["event_type"]["accuracy"] == 0.5
    assert out["calibration"]["brier_event_type"] == 0.3225
    assert out["calibration"]["ece_event_type"] == 0.425
    assert out["calibration"]["aurc"] == 0.3333
    # The silent record is scored as a wrong prediction under a reserved label, not skipped.
    # A label that only ever appears in `y_pred` contributes no class row, so the reader cannot
    # mistake "invented a class we never asked about" for "got a class wrong".
    assert "__none__" not in out["event_type"]["per_class"]
    assert out["event_type"]["per_class"]["capital_action"]["recall"] == 0.5
    assert out["event_type"]["per_class"]["capital_action"]["support"] == 4.0
    assert out["event_type"]["per_class"]["capital_action"]["precision"] == 1.0
    # mean wall_ms of 100/200/300/400 = 250.0
    assert out["cost"]["wall_ms_mean"] == 250.0
    assert out["reliability"]["terminated_ok_rate"] == 1.0
    assert out["reliability"]["abstention_rate"] == 0.0
    assert out["reliability"]["system1_failure_rate"] == 0.0


def test_an_arm_that_answers_nothing_scores_zero_accuracy_not_a_skip():
    """Refusing to answer cannot improve a calibration number by opting out of being scored."""
    silent = [_rec("r1", "capital_action", 0.0, answers={}),
              _rec("r2", "capital_action", 0.0, answers={})]
    items = {"r1": _item("r1", "capital_action"), "r2": _item("r2", "capital_action")}
    out = H.aggregate(silent, items)
    assert out["event_type"]["accuracy"] == 0.0
    assert out["calibration"]["brier_event_type"] == 0.0, (
        "with no answer the harness states p=0, which is a *lucky* Brier of 0.0; that is "
        "exactly why ARM_FAILED_NO_OUTPUT exists and why the flag must be read"
    )
    assert out["calibration"]["ece_event_type"] == 0.0


def test_aggregate_reports_absent_labels_as_not_evaluated():
    out = H.aggregate(HAND_RECORDS, HAND_ITEMS)
    assert out["is_material_noul"]["n_labeled"] == 0
    assert "not evaluated" in out["is_material_noul"]["status"]
    assert out["materiality_ordinal"]["n_labeled"] == 0
    assert "not evaluated" in out["materiality_ordinal"]["status"]


def test_aggregate_scores_the_ordinal_and_binary_decisions_when_labelled():
    items = {
        "r1": H.Item(id="r1", stratum="clear", content="t",
                     labels={"event_type": "capital_action", "is_material": True, "materiality": 2},
                     annotator_confidence=0.0),
        "r2": H.Item(id="r2", stratum="clear", content="t",
                     labels={"event_type": "capital_action", "is_material": False, "materiality": 0},
                     annotator_confidence=0.0),
    }
    records = [
        _rec("r1", "capital_action", 0.9, answers={
            "event_type": {"type": "choice", "choice": "capital_action",
                           "probabilities": {"capital_action": 0.9}, "confidence": 0.9},
            "is_material": {"type": "noul", "noul": 0.8, "confidence": 0.8},
            "materiality": {"type": "score", "score": 2.4, "confidence": 0.5},
        }),
        _rec("r2", "capital_action", 0.9, answers={
            "event_type": {"type": "choice", "choice": "capital_action",
                           "probabilities": {"capital_action": 0.9}, "confidence": 0.9},
            "is_material": {"type": "noul", "noul": 0.3, "confidence": 0.3},
            "materiality": {"type": "score", "score": 1.0, "confidence": 0.5},
        }),
    ]
    out = H.aggregate(records, items)
    assert out["is_material_noul"]["n_labeled"] == 2
    assert out["is_material_noul"]["accuracy_at_0.5"] == 1.0
    assert out["is_material_noul"]["brier"] == pytest.approx((0.04 + 0.09) / 2, abs=1e-4)
    assert out["materiality_ordinal"]["n_labeled"] == 2
    # 2.4 rounds to 2 (correct); 1.0 rounds to 1, which is within one of 0.
    assert out["materiality_ordinal"]["exact"] == 0.5
    assert out["materiality_ordinal"]["within_one"] == 1.0


def test_aggregate_stratum_splits_without_doubling_counting():
    records = [
        *HAND_RECORDS,
        _rec("r5", "capital_action", 0.95, "ambiguous"),
        _rec("r6", "other", 0.10, "ambiguous", answers={
            "event_type": {"type": "choice", "choice": "other",
                           "probabilities": {"other": 0.10}, "confidence": 0.10}}),
    ]
    items = dict(HAND_ITEMS)
    items["r5"] = _item("r5", "capital_action", "ambiguous")
    items["r6"] = _item("r6", "capital_action", "ambiguous")
    out = H.aggregate(records, items)
    assert set(out["by_stratum"]) == {"clear", "ambiguous"}
    assert out["by_stratum"]["clear"]["n"] == 4
    assert out["by_stratum"]["ambiguous"]["n"] == 2
    assert out["n_items"] == 6 == sum(s["n"] for s in out["by_stratum"].values())
    assert out["by_stratum"]["ambiguous"]["accuracy"] == 0.5
    # brier = mean((0.05)^2, 0.1^2) over the two ambiguous records
    assert out["by_stratum"]["ambiguous"]["brier"] == pytest.approx((0.0025 + 0.01) / 2, abs=1e-4)
    assert out["by_stratum"]["clear"]["accuracy"] == 0.5
    assert out["by_stratum"]["clear"]["wall_ms_mean"] == 250.0


def test_aggregate_stratum_is_the_pooled_row_of_that_stratum():
    records = HAND_RECORDS
    pooled = H.aggregate(records, HAND_ITEMS)
    sub = H.aggregate_stratum(records, HAND_ITEMS)
    assert sub["accuracy"] == pooled["event_type"]["accuracy"]
    assert sub["brier"] == pooled["calibration"]["brier_event_type"]
    assert sub["ece"] == pooled["calibration"]["ece_event_type"]
    assert sub["aurc"] == pooled["calibration"]["aurc"]
    assert sub["n"] == 4


def test_aggregate_on_an_empty_record_set_does_not_divide_by_zero():
    out = H.aggregate([], {})
    assert out["n_items"] == 0
    assert out["event_type"]["accuracy"] == 0.0
    assert out["calibration"]["brier_event_type"] == 0.0
    assert out["calibration"]["ece_event_type"] == 0.0
    assert out["calibration"]["aurc"] == 0.0
    assert out["cost"]["wall_ms_mean"] == 0.0
    assert out["by_stratum"] == {}
    assert out["reliability"]["terminated_ok_rate"] == 0.0


def test_unnecessary_system1_calls_are_counted():
    records = [
        _rec("r1", "capital_action", 0.9, s1_calls=1),
        _rec("r2", "capital_action", 0.9, s1_calls=3),
        _rec("r3", "capital_action", 0.9, s1_calls=0),
    ]
    items = {i: _item(i, "capital_action") for i in ("r1", "r2", "r3")}
    out = H.aggregate(records, items)
    assert out["cost"]["unnecessary_system1_calls"] == 2
    assert out["cost"]["system1_calls_mean"] == pytest.approx(1.333, abs=1e-3)


# --- item loading ----------------------------------------------------------


def test_load_items_reads_the_real_dataset_and_preserves_null_annotator_confidence():
    items = H.load_items(DATASET, limit=5)
    assert len(items) == 5
    assert all(i.is_synthetic_text is False for i in items), (
        "the real dataset must not claim to be synthetic text"
    )
    assert all(i.annotator_confidence == 0.0 for i in items), (
        "a null annotator_confidence must not be carried through as 1.0"
    )
    assert {i.stratum for i in items} <= {"clear", "ambiguous", "noisy"}
    assert all(i.labels["event_type"] for i in items)


def test_load_items_filters_by_stratum_and_limit():
    clear = H.load_items(DATASET, strata=["clear"])
    assert clear
    assert all(i.stratum == "clear" for i in clear)
    assert len(H.load_items(DATASET, strata=["clear"], limit=2)) == 2
    assert H.load_items(DATASET, strata=["does-not-exist"]) == []


def test_item_from_json_defaults_the_synthetic_flag_to_true():
    item = H.Item.from_json({"id": "x", "stratum": "clear", "content": "c",
                             "labels": {"event_type": "other"}, "annotator_confidence": 1.0})
    assert item.is_synthetic_text is True
    assert item.is_adversarial is False
    assert item.ambiguous_alternatives == []


# --- arm dispatch ----------------------------------------------------------


def _runner(arm: str, **kw: Any) -> H.ArmRunner:
    return H.ArmRunner(
        arm=arm,
        system1=StubSystem1(),
        system2_factory=lambda: H.HeuristicProvider(),
        protocol=PROTOCOL,
        **kw,
    )


def test_arm_dispatch_rejects_an_unknown_arm():
    with pytest.raises(ValueError, match="unknown arm"):
        asyncio.run(_runner("Z").run_item(_item("x", "capital_action")))


def test_dispatch_table_covers_exactly_the_four_arms():
    assert set(H.ARMS) == {"A", "B", "C", "D"}
    assert set(H._ARM_DISPATCH) == set(H.ARMS)
    for arm, fn in H._ARM_DISPATCH.items():
        assert fn.__name__ == f"_arm_{arm.lower()}", "an arm letter must not point at another arm"


def test_arm_a_calls_system1_once_and_no_reasoning_model():
    rec = asyncio.run(_runner("A").run_item(_item("x", "capital_action")))
    assert rec["system1_calls"] == 1
    assert rec["system2_calls"] == 0
    assert rec["termination"] == "single_shot"
    assert rec["answers"]["event_type"]["choice"] == "capital_action"
    assert rec["terminated_ok"] is True
    assert rec["abstained"] is False
    assert rec["item_id"] == "x" and rec["stratum"] == "clear"
    assert rec["wall_ms"] >= 0.0


def test_arm_b_never_calls_system1_and_carries_no_answers():
    rec = asyncio.run(_runner("B").run_item(_item("x", "capital_action")))
    assert rec["system1_calls"] == 0
    assert rec["system2_calls"] >= 1
    assert rec["answers"] == {}, "arm B is System-2 alone; it must not smuggle in a System-1 answer"
    # With System-1 absent and escalation disabled, the heuristic asks for nothing it is allowed
    # to ask for on turn 2 and the runtime reports a clean abstention -- not an error. The point
    # stands either way: arm B produced no answer, which is what ARM_FAILED_NO_OUTPUT records.
    assert rec["termination"] == "abstained"
    assert rec["abstained"] is True


def test_arm_c_makes_exactly_one_system1_call():
    rec = asyncio.run(_runner("C").run_item(_item("x", "capital_action")))
    assert rec["system1_calls"] == 1
    assert rec["c_samples"] == 1
    assert rec["system2_calls"] >= 1
    assert rec["answers"]["event_type"]["choice"] == "capital_action"
    assert rec["termination"] == "max_turns", "arm C is configured with max_turns=1 by design"


def test_arm_c_repeats_and_majority_votes():
    runner = _runner("C", c_samples=3)
    rec = asyncio.run(runner.run_item(_item("x", "capital_action")))
    assert rec["c_samples"] == 3
    assert rec["system1_calls"] == 3
    with pytest.raises(IndexError):
        runner._majority_vote([])


def test_majority_vote_records_a_tie_instead_of_pretending_it_is_a_consensus():
    runs = [
        _run_with(("earnings_result", 0.4), ("capital_action", 0.6)),
        _run_with(("capital_action", 0.4), ("earnings_result", 0.6)),
    ]
    merged = _runner("C")._majority_vote(runs)
    assert merged["vote_tie"] is True
    assert merged["answers"]["event_type"]["vote_counts"] == {"earnings_result": 1,
                                                              "capital_action": 1}
    # The docstring claims a tie "falls back to the first sample". It does not: `max` over the
    # tally returns whichever label the tally dict saw first, which is the order System-1
    # happened to emit. Pinned here as-is so the fix is deliberate. See docs/loop/REDTOOM.md.
    assert merged["answers"]["event_type"]["choice"] == "capital_action"


def test_majority_vote_picks_the_real_majority():
    runs = [
        _run_with(("earnings_result", 0.4)),
        _run_with(("earnings_result", 0.4)),
        _run_with(("capital_action", 0.6)),
    ]
    merged = _runner("C")._majority_vote(runs)
    assert merged["vote_tie"] is False
    assert merged["answers"]["event_type"]["choice"] == "earnings_result"


def test_majority_vote_of_one_run_is_the_run_itself():
    runs = [_run_with(("capital_action", 0.9))]
    merged = _runner("C")._majority_vote(runs)
    assert merged == {"answers": runs[0].state.latest_system1, "vote_tie": False}


def test_arm_d_can_escalate_beyond_tier_one():
    rec = asyncio.run(_runner("D", d_max_turns=4).run_item(_item("x", "capital_action")))
    assert "event_type" in rec["answers"]
    assert rec["system2_calls"] >= 1
    assert rec["terminated_ok"] is True
    assert rec["termination"] in {"finished", "abstained", "max_turns"}


def _run_with(*answers: tuple[str, float]) -> Any:
    from divya.runtime.loop import LoopResult
    from divya.runtime.state import SharedState, StateBuilder, System1Record

    state = SharedState(protocol_version=PROTOCOL.protocol_version, domain="t", objective="o")
    builder = StateBuilder(state)
    for i, (label, prob) in enumerate(answers):
        builder.record_system1(
            System1Record(
                turn_index=i,
                decision_names=["event_type"],
                spec_name="event_triage",
                spec_version=2,
                protocol_version=PROTOCOL.protocol_version,
                request={},
                raw_response={},
                answers={"event_type": {"type": "choice", "choice": label,
                                        "probabilities": {label: prob}, "confidence": prob}},
            )
        )
    return LoopResult(state=state, builder=builder)


# --- the failed-arm flag ----------------------------------------------------


def test_an_arm_that_answers_nothing_is_flagged_as_a_failed_arm(monkeypatch, tmp_path):
    """Arm B in the shipped run errored on 120/120 and produced no output.

    Without the flag its 0.000 is indistinguishable from "System-2 alone performs at chance".
    This drives the real `run_eval` with System-1 forced unavailable and asserts the flag.
    """
    class Unavailable:
        def is_available(self) -> bool:
            return False

    monkeypatch.setattr(H, "LayaSystem1", Unavailable)
    monkeypatch.setattr(
        H.ArmRunner, "__init__", _force_null_system1(H.ArmRunner.__init__), raising=True
    )

    out = tmp_path / "eval.json"
    args = _ns(dataset=str(DATASET), limit=2, strata=None, arms=["B"], provider="heuristic",
               model=None, base_url=None, min_confidence=0.55, max_turns=4, c_samples=1,
               progress_every=100, out=str(out))
    report = asyncio.run(H.run_eval(args))

    b = report["results"]["B"]
    assert b["event_type"]["accuracy"] == 0.0
    assert b["ARM_FAILED_NO_OUTPUT"] is True
    assert all(r["answers"] == {} for r in report["per_item"]["B"])
    assert json.loads(out.read_text(encoding="utf-8"))["results"]["B"]["ARM_FAILED_NO_OUTPUT"] is True
    assert report["config"]["system1_available"] is False


def test_an_arm_that_answers_is_not_flagged(monkeypatch, tmp_path):
    class Unavailable:
        def is_available(self) -> bool:
            return False

    monkeypatch.setattr(H, "LayaSystem1", Unavailable)
    monkeypatch.setattr(
        H.ArmRunner, "__init__", _force_stub_system1(H.ArmRunner.__init__), raising=True
    )
    out = tmp_path / "eval.json"
    args = _ns(dataset=str(DATASET), limit=2, strata=None, arms=["A"], provider="heuristic",
               model=None, base_url=None, min_confidence=0.55, max_turns=4, c_samples=1,
               progress_every=100, out=str(out))
    report = asyncio.run(H.run_eval(args))
    assert "ARM_FAILED_NO_OUTPUT" not in report["results"]["A"]
    assert report["results"]["A"]["event_type"]["accuracy"] > 0.0


def test_an_empty_dataset_stops_the_run(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    args = _ns(dataset=str(empty), limit=None, strata=None, arms=["A"], provider="heuristic",
               model=None, base_url=None, min_confidence=0.55, max_turns=4, c_samples=1,
               progress_every=1, out=str(tmp_path / "x.json"))
    with pytest.raises(SystemExit, match="no items loaded"):
        asyncio.run(H.run_eval(args))


# --- the shipped artifact --------------------------------------------------


def test_the_shipped_eval_artifact_is_consistent_with_its_own_records():
    """Recompute arm A's accuracy from the per-item records in the shipped artifact.

    The reported number and the records it came from must agree; a report that disagrees with
    its own evidence is worse than no report.
    """
    report = json.loads(EVAL_ARTIFACT.read_text(encoding="utf-8"))
    items = {i.id: i for i in H.load_items(DATASET, limit=120)}
    for arm in ("A", "C", "D"):
        recs = report["per_item"][arm]
        assert len(recs) == 120
        correct = 0
        for r in recs:
            pred, _p = H.score_event_type((r.get("answers") or {}).get("event_type"))
            correct += int(pred == str(items[r["item_id"]].labels["event_type"]))
        assert round(correct / len(recs), 4) == report["results"][arm]["event_type"]["accuracy"], arm


def test_the_shipped_arm_b_produced_no_answers_at_all():
    report = json.loads(EVAL_ARTIFACT.read_text(encoding="utf-8"))
    recs = report["per_item"]["B"]
    assert all((r.get("answers") or {}).get("event_type") is None for r in recs)
    assert report["results"]["B"]["event_type"]["accuracy"] == 0.0
    # The flag is absent from the shipped artifact because the artifact predates the fix that
    # added it. Asserting its absence pins the staleness rather than hiding it.
    assert "ARM_FAILED_NO_OUTPUT" not in report["results"]["B"]


def test_the_shipped_artifact_d_abstains_much_more_than_it_helps():
    report = json.loads(EVAL_ARTIFACT.read_text(encoding="utf-8"))
    assert report["results"]["D"]["reliability"]["abstention_rate"] == 0.7583
    assert report["results"]["D"]["reliability"]["max_turns_hit_rate"] == 0.2417
    assert report["results"]["D"]["reliability"]["terminated_ok_rate"] == 1.0
    assert report["results"]["A"]["reliability"]["abstention_rate"] == 0.0


# --- helpers ---------------------------------------------------------------


def _ns(**kw: Any) -> Any:
    import argparse

    base = {"dataset": str(DATASET), "limit": None, "strata": None, "arms": ["A"],
            "provider": "heuristic", "model": None, "base_url": None, "min_confidence": 0.55,
            "max_turns": 4, "c_samples": 1, "progress_every": 10, "out": "/tmp/x.json"}
    base.update(kw)
    return argparse.Namespace(**base)


def _force_null_system1(orig: Any) -> Any:
    def patched(self: Any, *a: Any, **kw: Any) -> None:
        orig(self, *a, **kw)
        self.system1 = NullSystem1()

    return patched


def _force_stub_system1(orig: Any) -> Any:
    def patched(self: Any, *a: Any, **kw: Any) -> None:
        orig(self, *a, **kw)
        self.system1 = StubSystem1()

    return patched
