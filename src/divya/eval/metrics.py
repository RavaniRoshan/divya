"""Evaluation metrics.

Deliberately small and dependency-free (numpy only) so that a metric definition cannot drift
between the version used in a report and the version in the code. Every function here is
unit-tested against a hand-computed value; see ``tests/test_metrics.py``.

Three groups:

**Task quality.** Accuracy, per-class precision/recall/F1, macro-F1. Macro rather than micro
because the event-type distribution is skewed, and a micro number on a skewed distribution
mostly measures the majority class.

**Calibration.** Brier score and expected calibration error. These matter more than accuracy
for this system, because the terminal's central claim is that it knows when it does not know. A
model that is confidently wrong is worse here than a model that is often unsure, and accuracy
alone cannot tell those apart.

**Selective risk.** Risk-coverage curve and area under it. AURC answers the question an
operator actually asks: if the system abstains on its least-confident 30% of events, what error
rate remains on the rest? This is the metric that distinguishes "confidently wrong" from
"usefully cautious", and it is the one most likely to separate a recurrent loop from a
single-shot call.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np


@dataclass
class ClassificationReport:
    """Per-class and pooled quality for one arm on one dataset."""

    n: int
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    per_class: dict[str, dict[str, float]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "accuracy": round(self.accuracy, 4),
            "macro_precision": round(self.macro_precision, 4),
            "macro_recall": round(self.macro_recall, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {
                k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in sorted(self.per_class.items())
            },
        }


def classification_report(
    y_true: Sequence[str], y_pred: Sequence[str]
) -> ClassificationReport:
    """Accuracy plus per-class precision/recall/F1 and their macro averages.

    Classes present in ``y_true`` are the ones scored. A predicted label that never appears in
    the truth contributes no class row rather than a precision of zero, because "the system
    invented a class we never asked about" is a different failure from "the system got a class
    wrong", and averaging the two hides the first one.
    """
    if len(y_true) != len(y_pred):
        raise ValueError(f"length mismatch: {len(y_true)} true vs {len(y_pred)} pred")

    labels = sorted(set(y_true))
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    support: dict[str, int] = defaultdict(int)

    # `truth`/`pred`, not `t`/`p`: `p` is reused below for precision, and two meanings in
    # one function is how a precision figure silently becomes a string.
    for truth, pred in zip(y_true, y_pred, strict=True):
        support[truth] += 1
        if truth == pred:
            tp[truth] += 1
        else:
            fn[truth] += 1
            fp[pred] += 1

    correct = sum(tp.values())
    per_class: dict[str, dict[str, float]] = {}
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []

    for label in labels:
        p: float = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) else 0.0
        r: float = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) else 0.0
        f: float = 2 * p * r / (p + r) if (p + r) else 0.0
        per_class[label] = {
            "precision": p,
            "recall": r,
            "f1": f,
            "support": float(support[label]),
        }
        precisions.append(p)
        recalls.append(r)
        f1s.append(f)

    n = len(y_true)
    return ClassificationReport(
        n=n,
        accuracy=correct / n if n else 0.0,
        macro_precision=float(np.mean(precisions)) if precisions else 0.0,
        macro_recall=float(np.mean(recalls)) if recalls else 0.0,
        macro_f1=float(np.mean(f1s)) if f1s else 0.0,
        per_class=per_class,
    )


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error between stated probability and realised outcome.

    The multi-class form, using the probability assigned to the *correct* class. Range [0, 2].
    A model that always says 0.5 scores 0.25 on a balanced binary task, so 0.0 is perfection
    and anything at or above ~0.25 on a binary task is no better than a coin flip that claims
    to know it is a coin flip.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.shape != y.shape:
        raise ValueError(f"shape mismatch: {p.shape} vs {y.shape}")
    if p.size == 0:
        return 0.0
    return float(np.mean((p - y) ** 2))


def binary_brier(positives: Sequence[float], labels: Sequence[int]) -> float:
    """Brier for a single probability per item, regardless of class."""
    return brier_score(positives, labels)


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[int], bins: int = 15
) -> tuple[float, list[dict[str, Any]]]:
    """Expected calibration error with equal-width bins, plus the bin detail.

    Returns ``(ece, bins)`` so a report can show *where* the miscalibration is, not just how
    much of it there is. A bare ECE of 0.14 is not actionable; "everything above 0.8 is
    overconfident" is.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.shape != y.shape:
        raise ValueError(f"shape mismatch: {p.shape} vs {y.shape}")
    if p.size == 0:
        return 0.0, []

    edges = np.linspace(0.0, 1.0, bins + 1)
    total = p.size
    ece = 0.0
    detail: list[dict[str, Any]] = []

    for lo, hi in pairwise(edges):
        # Right-closed on the last bin so p == 1.0 lands in a bin rather than falling out.
        mask = (p >= lo) & (p <= hi) if hi >= 1.0 else (p >= lo) & (p < hi)
        count = int(mask.sum())
        if count == 0:
            detail.append({"bin": [round(float(lo), 3), round(float(hi), 3)], "n": 0})
            continue
        conf = float(p[mask].mean())
        acc = float(y[mask].mean())
        gap = abs(conf - acc)
        ece += (count / total) * gap
        detail.append(
            {
                "bin": [round(float(lo), 3), round(float(hi), 3)],
                "n": count,
                "mean_confidence": round(conf, 4),
                "empirical_accuracy": round(acc, 4),
                "gap": round(gap, 4),
            }
        )
    return float(ece), detail


def risk_coverage(
    confidences: Sequence[float], correct: Sequence[int]
) -> tuple[list[dict[str, float]], float]:
    """Risk-coverage curve and its area (AURC).

    Sort by confidence descending, then walk down the coverage axis: at coverage 1.0 every item
    is answered and risk is the overall error rate; at low coverage only the most confident
    items are answered. AURC is the mean risk across that sweep.

    Lower is better. A system that abstains well has low risk at moderate coverage; a system
    that is confidently wrong has *higher* risk as coverage falls, because the items it drops
    first are the ones it was most sure about. That inversion is the signature this metric
    exists to detect, and it is invisible to accuracy.
    """
    c = np.asarray(confidences, dtype=float)
    k = np.asarray(correct, dtype=float)
    if c.shape != k.shape:
        raise ValueError(f"shape mismatch: {c.shape} vs {k.shape}")
    n = c.size
    if n == 0:
        return [], 0.0

    order = np.argsort(-c, kind="stable")
    k_sorted = k[order]
    errors_sorted = 1.0 - k_sorted
    cumulative_errors = np.cumsum(errors_sorted)

    curve: list[dict[str, float]] = []
    for i in range(1, n + 1):
        curve.append(
            {
                "coverage": round(i / n, 4),
                "risk": round(float(cumulative_errors[i - 1] / i), 4),
                "threshold": round(float(c[order][i - 1]), 4),
            }
        )
    aurc = float(np.mean([pt["risk"] for pt in curve]))
    return curve, aurc


def selective_accuracy_at(
    confidences: Sequence[float], correct: Sequence[int], coverage: float
) -> dict[str, Any]:
    """Accuracy and retained-set size if the least-confident (1-coverage) were abstained on."""
    c = np.asarray(confidences, dtype=float)
    k = np.asarray(correct, dtype=int)
    if c.size == 0:
        return {"coverage_target": coverage, "n_answered": 0, "accuracy": 0.0, "threshold": 1.0}
    order = np.argsort(-c, kind="stable")
    keep = max(1, round(coverage * c.size))
    kept = k[order][:keep]
    return {
        "coverage_target": coverage,
        "n_answered": int(keep),
        "accuracy": round(float(kept.mean()), 4),
        "threshold": round(float(c[order][keep - 1]), 4),
    }


def near_miss_rate(
    y_true: Sequence[int], y_pred_score: Sequence[float], tolerance: int = 1
) -> float:
    """Fraction of ordinal predictions within `tolerance` levels of the label.

    Ordinal decisions (materiality 0-4) are not binary correct/incorrect. Calling level 2 when
    the label is level 3 is a real error but a much smaller one than calling level 4, and
    pooling them understates how good a system is on the dimension that actually matters.
    """
    if len(y_true) != len(y_pred_score):
        raise ValueError(f"length mismatch: {len(y_true)} vs {len(y_pred_score)}")
    if not y_true:
        return 0.0
    hits = sum(1 for t, p in zip(y_true, y_pred_score, strict=True) if abs(int(t) - round(p)) <= tolerance)
    return hits / len(y_true)


def mean(values: Sequence[float]) -> float:
    v = [x for x in values if x is not None]
    return float(np.mean(v)) if v else 0.0


def p95(values: Sequence[float]) -> float:
    v = [x for x in values if x is not None]
    return float(np.percentile(v, 95)) if v else 0.0
