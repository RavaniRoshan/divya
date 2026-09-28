"""Is the A-vs-D difference real, or noise on n=120?

The review was right that "H3 SUPPORTED" was an assertion. Arm D scored 0.508 against arm A's
0.558 — six net items out of 120. Before that is reported as a finding it has to survive a
test, and the right test is the *paired* one: the two arms ran on the same events, so the
discordant pairs are all the evidence there is.

Everything here is computed from `evals/results/real_eval.json` and
`evals/datasets/nse_announcements_v1.jsonl`. Nothing is hardcoded from the reported numbers; if
the artifact changes, the conclusion changes with it.

Two tests, because they answer different questions:

* **McNemar's exact test** on the discordant pairs. This is the correct test for paired
  proportions and does not assume anything about the marginal accuracy. It answers: "given the
  items where A and D disagreed, is the split further from 50/50 than chance?"
* **A paired bootstrap over items.** Resamples *events* (the unit of independence — resampling
  decisions within an event would be wrong, since one event produces several) and reports the
  distribution of the accuracy difference. This is the one to quote, because it does not reduce
  to a single p-value and it shows the effect size directly.

Reported honestly: with 6 discordant pairs the test has almost no power, and a non-significant
result here means "this experiment could not detect the difference", not "there is no
difference". That distinction is the whole reason this module exists.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from math import comb
from pathlib import Path
from typing import Any

DEFAULT_RESULT = Path("evals/results/real_eval.json")
DEFAULT_DATASET = Path("evals/datasets/nse_announcements_v1.jsonl")


@dataclass
class PairedComparison:
    arm_a: str
    arm_b: str
    n: int
    both_correct: int
    both_wrong: int
    a_only_correct: int
    b_only_correct: int
    acc_a: float
    acc_b: float
    delta: float

    @property
    def discordant(self) -> int:
        return self.a_only_correct + self.b_only_correct

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm_a": self.arm_a, "arm_b": self.arm_b, "n": self.n,
            "acc_a": round(self.acc_a, 4), "acc_b": round(self.acc_b, 4),
            "delta": round(self.delta, 4),
            "both_correct": self.both_correct, "both_wrong": self.both_wrong,
            "a_only_correct": self.a_only_correct, "b_only_correct": self.b_only_correct,
            "discordant_pairs": self.discordant,
        }


def _predicted(records: list[dict[str, Any]]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for r in records:
        ans = ((r.get("answers") or {}).get("event_type") or {})
        out[r["item_id"]] = ans.get("choice")
    return out


def _truth(dataset: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["id"]] = d["labels"]["event_type"]
    return out


def paired_comparison(
    result_path: Path = DEFAULT_RESULT,
    dataset_path: Path = DEFAULT_DATASET,
    arm_a: str = "A",
    arm_b: str = "D",
) -> PairedComparison:
    data = json.loads(Path(result_path).read_text(encoding="utf-8"))
    truth = _truth(Path(dataset_path))
    pa = _predicted(data["per_item"][arm_a])
    pb = _predicted(data["per_item"][arm_b])

    ids = [i for i in truth if i in pa and i in pb]
    both_c = both_w = a_only = b_only = 0
    for i in ids:
        ac = pa[i] == truth[i]
        bc = pb[i] == truth[i]
        if ac and bc:
            both_c += 1
        elif not ac and not bc:
            both_w += 1
        elif ac:
            a_only += 1
        else:
            b_only += 1
    n = len(ids)
    acc_a = (both_c + a_only) / n if n else 0.0
    acc_b = (both_c + b_only) / n if n else 0.0
    return PairedComparison(
        arm_a=arm_a, arm_b=arm_b, n=n, both_correct=both_c, both_wrong=both_w,
        a_only_correct=a_only, b_only_correct=b_only, acc_a=acc_a, acc_b=acc_b,
        delta=acc_b - acc_a,
    )


def mcnemar_exact(a_only: int, b_only: int) -> dict[str, Any]:
    """Two-sided exact McNemar test on the discordant pairs.

    Exact rather than chi-square because the discordant count is tiny — a chi-square
    approximation here would be meaningless, and a normal approximation would report a p-value
    for six observations as though it were sixty.
    """
    n = a_only + b_only
    if n == 0:
        return {"p_value": 1.0, "n_discordant": 0, "note": "no discordant pairs; nothing to test"}
    k = min(a_only, b_only)
    # P(X <= k) * 2 under Binomial(n, 0.5), capped at 1.
    tail = sum(comb(n, i) for i in range(0, k + 1)) / (2**n)
    p = min(1.0, 2 * tail)
    return {
        "p_value": round(p, 4),
        "n_discordant": n,
        "a_only": a_only,
        "b_only": b_only,
        "note": (
            "exact two-sided McNemar. With very few discordant pairs this test has almost no "
            "power: a non-significant result means the experiment could not resolve the "
            "difference, not that no difference exists."
        ),
    }


def paired_bootstrap(
    cmp: PairedComparison,
    result_path: Path = DEFAULT_RESULT,
    dataset_path: Path = DEFAULT_DATASET,
    iterations: int = 10_000,
    seed: int = 20260928,
) -> dict[str, Any]:
    """Bootstrap the paired accuracy difference by resampling *events*.

    Events are the unit of independence: one event yields several decisions, so resampling
    within an event would understate the variance. Seeded, so the reported interval is
    reproducible rather than a number that changes on every run.
    """
    import random

    data = json.loads(Path(result_path).read_text(encoding="utf-8"))
    truth = _truth(Path(dataset_path))
    pa = _predicted(data["per_item"][cmp.arm_a])
    pb = _predicted(data["per_item"][cmp.arm_b])
    ids = [i for i in truth if i in pa and i in pb]
    ok_a = [1 if pa[i] == truth[i] else 0 for i in ids]
    ok_b = [1 if pb[i] == truth[i] else 0 for i in ids]

    rng = random.Random(seed)
    n = len(ids)
    deltas: list[float] = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        deltas.append(
            sum(ok_b[i] for i in idx) / n - sum(ok_a[i] for i in idx) / n
        )
    deltas.sort()
    lo = deltas[int(0.025 * iterations)]
    hi = deltas[int(0.975 * iterations) - 1]
    worse = sum(1 for d in deltas if d < 0) / iterations
    better = sum(1 for d in deltas if d > 0) / iterations
    return {
        "iterations": iterations,
        "seed": seed,
        "delta_mean": round(sum(deltas) / iterations, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "p_delta_worse": round(worse, 4),
        "p_delta_better": round(better, 4),
        "excludes_zero": bool(lo > 0 or hi < 0),
        "note": (
            "95% CI on the paired accuracy difference (arm_b - arm_a). If the interval spans "
            "zero, the arms are not distinguishable at this sample size."
        ),
    }


def agreement_matrix(result_path: Path = DEFAULT_RESULT, dataset_path: Path = DEFAULT_DATASET,
                     arm: str = "A") -> dict[str, Any]:
    """Where the misclassifications actually go, per class.

    Included because the pooled accuracy number hides a bimodal failure: two classes scoring
    F1 = 0.00 while two others score above 0.85. A single figure cannot express that, and the
    per-class table is what points at the `other` option acting as an attractor.
    """
    data = json.loads(Path(result_path).read_text(encoding="utf-8"))
    truth = _truth(Path(dataset_path))
    pred = _predicted(data["per_item"][arm])
    rows: dict[str, Counter] = {}
    for i, t in truth.items():
        if i not in pred:
            continue
        rows.setdefault(t, Counter())[pred[i] or "__none__"] += 1
    out: dict[str, Any] = {}
    for t, c in rows.items():
        correct = c.get(t, 0)
        total = sum(c.values())
        predicted_as_other = c.get("other", 0)
        out[t] = {
            "n": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else 0.0,
            "predicted_as_other": predicted_as_other,
            "distribution": dict(c.most_common()),
        }
    out["_summary"] = {
        "arm": arm,
        "classes_with_zero_accuracy": sorted(
            t for t, v in out.items() if t != "_summary" and v["accuracy"] == 0.0
        ),
        "other_absorbs": sum(
            v["predicted_as_other"] for t, v in out.items() if t != "_summary" and t != "other"
        ),
    }
    return out


def report(result_path: Path = DEFAULT_RESULT, dataset_path: Path = DEFAULT_DATASET) -> str:
    """Human-readable significance report."""
    c = paired_comparison(result_path, dataset_path)
    m = mcnemar_exact(c.a_only_correct, c.b_only_correct)
    b = paired_bootstrap(c, result_path, dataset_path)
    mat = agreement_matrix(result_path, dataset_path)

    lines = [
        "PAIRED SIGNIFICANCE — does the recurrent loop (D) differ from System-1 alone (A)?",
        "",
        f"  n                     {c.n} paired events",
        f"  accuracy A            {c.acc_a:.4f}",
        f"  accuracy D            {c.acc_b:.4f}",
        f"  difference (D - A)    {c.delta:+.4f}",
        "",
        "  Discordant pairs",
        f"    both correct        {c.both_correct}",
        f"    both wrong          {c.both_wrong}",
        f"    only A correct      {c.a_only_correct}",
        f"    only D correct      {c.b_only_correct}",
        "",
        f"  McNemar exact         p = {m['p_value']}  ({m['n_discordant']} discordant)",
        f"  bootstrap 95% CI      [{b['ci95'][0]:+.4f}, {b['ci95'][1]:+.4f}]",
        f"  P(delta < 0)          {b['p_delta_worse']}",
        f"  excludes zero         {b['excludes_zero']}",
        "",
        "  INTERPRETATION",
    ]
    if b["excludes_zero"] and b["ci95"][1] < 0:
        lines += [
            "    The recurrent loop is measurably WORSE than System-1 alone, and the",
            "    difference survives a paired bootstrap. H3 is supported on this data.",
        ]
    elif b["excludes_zero"] and b["ci95"][0] > 0:
        lines += ["    The recurrent loop is measurably BETTER. H1 is supported on this data."]
    else:
        lines += [
            "    NOT RESOLVED. The 95% interval spans zero, so this experiment cannot",
            "    distinguish the two arms. With only "
            f"{c.discordant} discordant pairs there is almost no power.",
            "    The honest statement is 'D measured worse; the gap is "
            f"{abs(c.a_only_correct - c.b_only_correct)} items and has not been shown to be",
            "    real' -- not 'D is worse'.",
        ]
    lines += [
        "",
        "  WHERE ARM A GETS IT WRONG",
        f"    classes at 0.000 accuracy   {mat['_summary']['classes_with_zero_accuracy']}",
        f"    errors landing on 'other'   {mat['_summary']['other_absorbs']}",
    ]
    return "\n".join(lines)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--result", default=str(DEFAULT_RESULT))
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--out", default="evals/results/significance.json")
    args = ap.parse_args()

    c = paired_comparison(Path(args.result), Path(args.dataset))
    payload = {
        "comparison": c.as_dict(),
        "mcnemar_exact": mcnemar_exact(c.a_only_correct, c.b_only_correct),
        "paired_bootstrap": paired_bootstrap(c, Path(args.result), Path(args.dataset)),
        "agreement_arm_a": agreement_matrix(Path(args.result), Path(args.dataset)),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(report(Path(args.result), Path(args.dataset)))
    print(f"\n[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
