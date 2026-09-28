"""Tests for the paired-significance analysis.

The point of these is that the significance result is a *test*, not a number typed into a
document. The fixtures below are constructed so each expected value can be worked out by hand,
and so that a change in the implementation produces a failure rather than a different-looking
table.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from divya.eval.significance import (
    agreement_matrix,
    mcnemar_exact,
    paired_bootstrap,
    paired_comparison,
    report,
)

RESULT = Path("evals/results/real_eval.json")
DATASET = Path("evals/datasets/nse_announcements_v1.jsonl")


def _write(
    tmp_path: Path, pairs: list[tuple[str, str, str]], arm_d: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """Write a minimal artifact + dataset.

    `pairs` is [(item_id, truth, predicted_for_arm_A), ...]. `arm_d` overrides arm D's prediction
    per item; without it D is identical to A, which is what the "identical arms" tests want.
    """
    res = {"per_item": {"A": [], "D": []}}
    dsl = []
    for iid, truth, pred in pairs:
        res["per_item"]["A"].append({"item_id": iid, "answers": {"event_type": {"choice": pred}}})
        d_pred = (arm_d or {}).get(iid, pred)
        res["per_item"]["D"].append({"item_id": iid, "answers": {"event_type": {"choice": d_pred}}})
        dsl.append({"id": iid, "labels": {"event_type": truth}})
    rp = tmp_path / "r.json"
    dp = tmp_path / "d.jsonl"
    rp.write_text(json.dumps(res), encoding="utf-8")
    dp.write_text("\n".join(json.dumps(d) for d in dsl) + "\n", encoding="utf-8")
    return rp, dp


# --- McNemar --------------------------------------------------------------


def test_mcnemar_all_one_way_is_significant():
    """6 discordant, all favouring A: two-sided exact p = 2 * (1/2)^6 = 0.03125."""
    r = mcnemar_exact(6, 0)
    # 2 * (1/2)^6 = 0.03125, reported rounded to 4 dp.
    assert r["p_value"] == pytest.approx(0.03125, abs=1e-4)
    assert r["n_discordant"] == 6


def test_mcnemar_symmetric_split_is_not_significant():
    """3-3: p = 1.0, because a coin landing 3-3 is entirely unremarkable."""
    r = mcnemar_exact(3, 3)
    assert r["p_value"] == pytest.approx(1.0)


def test_mcnemar_one_one_sided():
    """1-0 discordant: p = 1.0. One disagreement proves nothing, which is the whole point of
    running a test instead of quoting a count."""
    r = mcnemar_exact(1, 0)
    assert r["p_value"] == pytest.approx(1.0)


def test_mcnemar_no_discordant_pairs():
    r = mcnemar_exact(0, 0)
    assert r["p_value"] == 1.0
    assert r["n_discordant"] == 0


# --- paired comparison ----------------------------------------------------


def test_paired_comparison_hand_computed(tmp_path):
    # 10 items. 5 both correct, 1 both wrong, 3 only A correct, 1 only D correct.
    pairs = [(f"b{i}", "x", "x") for i in range(5)] + [(f"w{i}", "x", "y") for i in range(1)]
    # D gets the 3 "A only correct" items wrong, and fixes the 1 "both wrong" item.
    arm_d = {**{f"a{i}": "y" for i in range(3)}, "d0": "x"}
    pairs = pairs + [(f"a{i}", "x", "x") for i in range(3)] + [("d0", "x", "y")]
    rp, dp = _write(tmp_path, pairs, arm_d=arm_d)
    c = paired_comparison(rp, dp)
    assert c.n == 10
    assert c.both_correct == 5 and c.both_wrong == 1
    assert c.a_only_correct == 3 and c.b_only_correct == 1
    assert c.acc_a == pytest.approx(0.8)
    assert c.acc_b == pytest.approx(0.6)
    assert c.delta == pytest.approx(-0.2)
    assert c.discordant == 4


def test_paired_comparison_identical_arms_have_zero_delta(tmp_path):
    pairs = [(f"i{i}", "x", "x" if i % 2 else "y") for i in range(20)]
    rp, dp = _write(tmp_path, pairs)
    c = paired_comparison(rp, dp)
    assert c.delta == 0.0
    assert c.discordant == 0


def test_missing_prediction_counts_as_wrong(tmp_path):
    """An arm that abstains into a missing answer must not get credit."""
    pairs = [(f"i{i}", "x", "x") for i in range(3)] + [("m1", "x", None)]
    rp, dp = _write(tmp_path, pairs)
    c = paired_comparison(rp, dp)
    assert c.n == 4
    assert c.acc_a == pytest.approx(0.75)


# --- bootstrap ------------------------------------------------------------


def test_bootstrap_is_seeded_and_reproducible(tmp_path):
    pairs = [(f"i{i}", "x", "x" if i < 7 else "y") for i in range(20)]
    rp, dp = _write(tmp_path, pairs)
    c = paired_comparison(rp, dp)
    a = paired_bootstrap(c, rp, dp, iterations=500, seed=7)
    b = paired_bootstrap(c, rp, dp, iterations=500, seed=7)
    assert a == b, "a seeded bootstrap must reproduce exactly"


def test_bootstrap_identical_arms_include_zero(tmp_path):
    pairs = [(f"i{i}", "x", "x" if i % 2 else "y") for i in range(30)]
    rp, dp = _write(tmp_path, pairs)
    c = paired_comparison(rp, dp)
    b = paired_bootstrap(c, rp, dp, iterations=500)
    assert b["ci95"][0] == pytest.approx(0.0)
    assert b["ci95"][1] == pytest.approx(0.0)


def test_bootstrap_detects_a_onesided_regression(tmp_path):
    """D wrong on 8 items that A got right, and fixing none: the CI must exclude zero."""
    pairs = [(f"ok{i}", "x", "x") for i in range(60)] + [(f"r{i}", "x", "x") for i in range(8)]
    rp, dp = _write(tmp_path, pairs, arm_d={f"r{i}": "y" for i in range(8)})
    c = paired_comparison(rp, dp)
    b = paired_bootstrap(c, rp, dp, iterations=1000)
    assert b["ci95"][1] < 0
    assert b["excludes_zero"] is True


# --- agreement matrix -----------------------------------------------------


def test_agreement_matrix_finds_zero_accuracy_classes(tmp_path):
    pairs = (
        [("g1", "good", "good"), ("g2", "good", "good")]
        + [("d1", "dead", "other"), ("d2", "dead", "other")]
        + [("o1", "other", "other")]
    )
    rp, dp = _write(tmp_path, pairs)
    m = agreement_matrix(rp, dp, arm="A")
    assert m["good"]["accuracy"] == 1.0
    assert m["dead"]["accuracy"] == 0.0
    assert "dead" in m["_summary"]["classes_with_zero_accuracy"]
    assert m["_summary"]["other_absorbs"] == 2


# --- the real artifact ----------------------------------------------------


def test_real_artifact_comparison_matches_the_published_numbers():
    """The committed result must still say what the docs say it says.

    If a re-run changes the numbers, this fails and the documentation has to be updated rather
    than quietly going stale.
    """
    c = paired_comparison(RESULT, DATASET)
    assert c.n == 120
    assert c.acc_a == pytest.approx(0.5583, abs=1e-3)
    assert c.acc_b == pytest.approx(0.5083, abs=1e-3)
    assert c.a_only_correct == 6
    assert c.b_only_correct == 0


def test_real_result_is_significant_and_one_sided():
    m = mcnemar_exact(6, 0)
    assert m["p_value"] < 0.05
    c = paired_comparison(RESULT, DATASET)
    b = paired_bootstrap(c, RESULT, DATASET, iterations=2000)
    assert b["excludes_zero"] is True
    assert b["ci95"][1] < 0


def test_report_states_a_conclusion():
    text = report(RESULT, DATASET)
    assert "INTERPRETATION" in text
    assert "McNemar" in text
    assert "bootstrap 95% CI" in text
