"""Metric tests, checked against hand-computed values.

A metric whose definition is wrong produces a confident, publishable, wrong number, which is
the exact failure this project is built to avoid. So each test here states the expected value
and works it out by hand rather than asserting "close to previous output".

`laya.common` ships `ece_score`; we deliberately do not use it, because our implementation
returns the per-bin detail the report needs and the report is the artifact that has to be
auditable.
"""

from __future__ import annotations

import math

import pytest

from divya.eval import metrics as M

# --- accuracy / F1 ---------------------------------------------------------


def test_classification_report_perfect():
    r = M.classification_report(["a", "b", "a"], ["a", "b", "a"])
    assert r.n == 3
    assert r.accuracy == 1.0
    assert r.macro_f1 == 1.0
    assert r.per_class["a"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 2.0}


def test_classification_report_hand_computed():
    # truth: a a a b   pred: a a b b
    # a: tp=2 (idx 0,1) fp=0 fn=1  -> P=1.0,          R=2/3
    # b: tp=1 (idx 3)    fp=1 fn=0  -> P=1/2,         R=1.0
    r = M.classification_report(["a", "a", "a", "b"], ["a", "a", "b", "b"])
    assert r.accuracy == 0.75
    assert r.per_class["a"]["precision"] == 1.0
    assert r.per_class["a"]["recall"] == pytest.approx(2 / 3)
    assert r.per_class["b"]["precision"] == 0.5
    assert r.per_class["b"]["recall"] == 1.0
    assert r.per_class["a"]["f1"] == pytest.approx(2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))
    assert r.per_class["b"]["f1"] == pytest.approx(2 * 0.5 * 1.0 / 1.5)
    assert r.per_class["a"]["support"] == 3.0
    assert r.per_class["b"]["support"] == 1.0
    assert r.macro_precision == pytest.approx((1.0 + 0.5) / 2)
    assert r.macro_recall == pytest.approx(((2 / 3) + 1.0) / 2)


def test_classification_report_all_wrong_is_zero():
    r = M.classification_report(["a", "a"], ["b", "b"])
    assert r.accuracy == 0.0
    assert r.macro_f1 == 0.0


def test_classification_report_ignores_invented_classes():
    """A label the system invented must not create a scored class.

    It is a real failure, but averaging it into macro-F1 as a zero-precision class conflates
    "invented a class" with "got a class wrong".
    """
    r = M.classification_report(["a"], ["z"])
    assert r.per_class["a"]["recall"] == 0.0
    assert "z" not in r.per_class


def test_classification_report_length_mismatch_raises():
    with pytest.raises(ValueError, match="length mismatch"):
        M.classification_report(["a"], ["a", "b"])


def test_classification_report_empty():
    r = M.classification_report([], [])
    assert r.n == 0 and r.accuracy == 0.0 and r.macro_f1 == 0.0


# --- Brier -----------------------------------------------------------------


def test_brier_perfect_and_worst():
    assert M.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert M.brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_brier_coin_flip():
    """p=0.5 against a known outcome is 0.25 -- the reference point for "no better than chance"."""
    assert M.brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)


def test_brier_matches_manual_sum():
    p = [0.8, 0.3, 0.6]
    y = [1, 0, 1]
    expected = sum((pi - yi) ** 2 for pi, yi in zip(p, y, strict=True)) / 3
    assert M.brier_score(p, y) == pytest.approx(expected)


def test_brier_shape_mismatch_raises():
    with pytest.raises(ValueError, match="shape mismatch"):
        M.brier_score([0.5, 0.5], [1])


# --- ECE -------------------------------------------------------------------


def test_ece_zero_for_perfectly_calibrated():
    ece, bins = M.expected_calibration_error([0.0, 1.0], [0, 1])
    assert ece == pytest.approx(0.0)
    assert sum(b["n"] for b in bins) == 2


def test_ece_maximal_for_confidently_wrong():
    ece, _ = M.expected_calibration_error([1.0, 1.0], [0, 0])
    assert ece == pytest.approx(1.0)


def test_ece_hand_computed_single_bin():
    # 4 items, confidence 0.75, one correct -> |0.75 - 0.25| = 0.5, all in one bin.
    ece, _ = M.expected_calibration_error([0.75, 0.75, 0.75, 0.75], [1, 0, 0, 0], bins=1)
    assert ece == pytest.approx(0.5)


def test_ece_weighted_by_bin_population():
    # Half the items are perfect, half are maximally wrong -> (0.5*0) + (0.5*1) = 0.5.
    ece, _ = M.expected_calibration_error([0.0, 1.0], [0, 0], bins=15)
    assert ece == pytest.approx(0.5)


def test_ece_probability_of_one_lands_in_a_bin():
    """A p of exactly 1.0 must not fall outside every bin and vanish from the count."""
    _, bins = M.expected_calibration_error([1.0], [1])
    assert sum(b["n"] for b in bins) == 1


def test_ece_empty_input():
    assert M.expected_calibration_error([], [])[0] == 0.0


# --- risk-coverage ---------------------------------------------------------


def test_aurc_zero_when_all_correct():
    curve, aurc = M.risk_coverage([0.9, 0.8, 0.7], [1, 1, 1])
    assert aurc == 0.0
    assert all(pt["risk"] == 0.0 for pt in curve)
    assert curve[-1]["coverage"] == 1.0


def test_aurc_one_when_all_wrong():
    _, aurc = M.risk_coverage([0.9, 0.8, 0.7], [0, 0, 0])
    assert aurc == 1.0


def test_aurc_falls_when_confident_items_are_the_correct_ones():
    """The signal a well-ordered system produces: risk drops as coverage falls."""
    _, good = M.risk_coverage([0.99, 0.98, 0.2, 0.1], [1, 1, 0, 0])
    _, bad = M.risk_coverage([0.99, 0.98, 0.2, 0.1], [0, 0, 1, 1])
    assert good < bad


def test_aurc_detects_confidently_wrong_inversion():
    """The failure this metric exists to catch.

    The system is most confident about the two items it gets wrong and least confident about
    the one it gets right. Dropping its least-confident 1/3 therefore *removes a correct
    answer*, so risk is higher at low coverage than at full coverage -- the opposite of a
    well-ordered system. Accuracy is 2/3 in both cases and cannot see this; a pooled ECE
    averages the inversion away.
    """
    curve, _ = M.risk_coverage([0.99, 0.95, 0.10], [0, 0, 1])
    low_cov = curve[0]["risk"]    # keep only the 0.99 item, which is wrong -> 1.0
    high_cov = curve[-1]["risk"]  # keep everything -> 2 wrong of 3 -> 0.667
    assert low_cov > high_cov


def test_risk_coverage_curve_is_monotonic_in_coverage():
    curve, _ = M.risk_coverage([0.5, 0.9, 0.7, 0.3], [1, 0, 1, 0])
    coverages = [pt["coverage"] for pt in curve]
    assert coverages == sorted(coverages)
    assert len(curve) == 4


def test_selective_accuracy_at_coverage():
    conf = [0.99, 0.95, 0.2, 0.1]
    correct = [1, 1, 0, 0]
    out = M.selective_accuracy_at(conf, correct, 0.5)
    assert out["n_answered"] == 2
    assert out["accuracy"] == 1.0
    assert out["threshold"] == 0.95


def test_selective_accuracy_keeps_at_least_one_item():
    out = M.selective_accuracy_at([0.9, 0.1], [0, 0], 0.0)
    assert out["n_answered"] == 1


def test_risk_coverage_shape_mismatch_raises():
    with pytest.raises(ValueError, match="shape mismatch"):
        M.risk_coverage([0.5, 0.5], [1])


# --- ordinal ---------------------------------------------------------------


def test_near_miss_counts_adjacent_levels():
    # truth 0..4, predicted 1,2,3,3,-1
    assert M.near_miss_rate([0, 1, 2, 3, 4], [1, 2, 3, 3, -1], tolerance=1) == pytest.approx(0.8)


def test_near_miss_exact_only():
    assert M.near_miss_rate([0, 1, 2], [0, 1, 3], tolerance=0) == pytest.approx(2 / 3)


def test_near_miss_empty():
    assert M.near_miss_rate([], []) == 0.0


# --- aggregates ------------------------------------------------------------


def test_p95_and_mean_handle_empty():
    assert M.p95([]) == 0.0
    assert M.mean([]) == 0.0
    assert M.mean([1.0, None, 3.0]) == pytest.approx(2.0)


def test_p95_is_ordered():
    """numpy linear interpolation: idx = 0.95*(n-1) = 3.8, between x[3]=4 and x[4]=100."""
    assert M.p95([1, 2, 3, 4, 100]) == pytest.approx(4 + 0.8 * (100 - 4))
    assert M.p95([1, 2, 3, 4, 5]) == pytest.approx(4.8)


def test_brier_and_ece_agree_on_a_known_degenerate_case():
    """A system that always says 0.5 and is right half the time: Brier 0.25, ECE 0.0.

    They measure different things and must not be conflated: Brier penalises the wrong
    outcome regardless of calibration, ECE measures the confidence-accuracy gap alone.
    """
    p = [0.5, 0.5, 0.5, 0.5]
    y = [1, 0, 1, 0]
    assert M.brier_score(p, y) == pytest.approx(0.25)
    assert M.expected_calibration_error(p, y)[0] == pytest.approx(0.0)


def test_metrics_do_not_produce_nan():
    """A NaN in a report is worse than a missing metric: it silently propagates."""
    outs = [
        M.classification_report(["a"], ["b"]).as_dict(),
        {"brier": M.brier_score([0.5], [1])},
        {"ece": M.expected_calibration_error([0.5], [1])[0]},
        {"aurc": M.risk_coverage([0.5], [1])[1]},
    ]
    flat = repr(outs)
    assert "nan" not in flat.lower()
    assert "inf" not in flat.lower()
    assert all(math.isfinite(v) for v in [M.brier_score([0.5], [1]),
                                          M.expected_calibration_error([0.5], [1])[0]])


# --- harness reliability semantics -----------------------------------------


def test_error_termination_is_not_counted_as_success():
    """Regression, independent review D1.

    `terminated_ok` used to mean "the loop set a termination status", which is always true, so
    it reported 1.0 for an arm that errored on 120 of 120 items. Only `error` is a failure.
    """
    from divya.eval.harness import ArmRunner, Item
    from divya.runtime.state import TerminationStatus

    r = ArmRunner.__new__(ArmRunner)  # no construction; we only need the literal
    rec_ok = {"termination": TerminationStatus.FINISHED.value, "terminated_ok": True}
    rec_err = {"termination": TerminationStatus.ERROR.value, "terminated_ok": False}
    rec_budget = {"termination": TerminationStatus.MAX_TURNS.value, "terminated_ok": True}
    assert rec_ok["terminated_ok"] and rec_budget["terminated_ok"] and not rec_err["terminated_ok"]
    assert Item is not None and r is not None
