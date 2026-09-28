"""The A/B/C/D evaluation harness.

This is the experiment the whole project exists to run. It executes four configurations on the
same items, in the same process, against the same loaded System-1 checkpoint, and reports
quality, calibration, and cost **per stratum**.

| Arm | Configuration | What it tests |
|---|---|---|
| A | System-1 alone | Is the fast path sufficient on its own? |
| B | System-2 alone | Does the reasoning model need System-1 at all? |
| C | System-2 -> System-1, single shot | The control. The thing to beat. |
| D | System-2 <-> state <-> System-1, recurrent | The claim under test. |

Four properties of the design exist specifically to stop the harness flattering the thesis:

1. **Paired.** Every arm sees byte-identical text. Differences are attributable to the
   architecture, not to sampling.

2. **Stratified, never pooled-only.** The dataset is split into `clear`, `ambiguous`, `noisy`
   and `adversarial`. A pooled average over all four can be won by handling `clear` perfectly
   while failing `ambiguous` completely, which is exactly the failure mode Laya showed on the
   results-plus-dividend case. Strata are reported side by side and the headline comparison
   is the ambiguous stratum.

3. **The ambiguity split is pre-registered.** Strata are assigned when the dataset is built,
   by a seeded generator, before any model runs. Choosing them after seeing results would make
   H1 unfalsifiable.

4. **Sample count is controlled.** If arm D is allowed to iterate and arm C is allowed one shot,
   any difference could be a difference in how many times each arm sampled. Arm C supports
   ``--c-samples`` self-consistency repeats, and the report prints both arms' effective sample
   counts.

Cost is a first-class output. An architecture that wins on accuracy by 2 points while doubling
p95 latency and quadrupling tokens is not obviously better, and the report must make that
trade visible rather than letting the reader assume it away.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from divya.eval import metrics as M
from divya.protocol.loader import load_protocol
from divya.runtime.loop import DivyaRuntime, LoopConfig, LoopResult
from divya.runtime.state import Observation, TerminationStatus
from divya.system1.laya_adapter import LayaSystem1, NullSystem1
from divya.system2.provider import HeuristicProvider, System2Provider

ARMS = ("A", "B", "C", "D")


@dataclass
class Item:
    id: str
    stratum: str
    content: str
    labels: dict[str, Any]
    annotator_confidence: float
    ambiguous_alternatives: list[str] = field(default_factory=list)
    is_adversarial: bool = False
    is_synthetic_text: bool = True

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Item:
        # Real NSE records carry `annotator_confidence: null` because the label is a published
        # exchange classification, not an annotation. There is no honest confidence to report
        # for it, so None is carried through rather than defaulted to 1.0, which would let a
        # label with no stated provenance look as reliable as a hand-checked one.
        conf = d.get("annotator_confidence")
        return cls(
            id=d["id"],
            stratum=d["stratum"],
            content=d["content"],
            labels=d["labels"],
            annotator_confidence=float(conf) if conf is not None else 0.0,
            ambiguous_alternatives=d.get("ambiguous_alternatives", []) or [],
            is_adversarial=bool(d.get("is_adversarial", False)),
            is_synthetic_text=bool(d.get("is_synthetic_text", True)),
        )


def load_items(path: str | Path, limit: int | None = None, strata: list[str] | None = None) -> list[Item]:
    items: list[Item] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        if strata and d["stratum"] not in strata:
            continue
        items.append(Item.from_json(d))
    if limit:
        items = items[:limit]
    return items


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_event_type(answer: dict[str, Any] | None) -> tuple[str | None, float]:
    """Extract the chosen label and the probability the engine put on it.

    Returns ``(None, 0.0)`` when the engine did not answer, which counts as wrong with zero
    confidence. Scoring a missing answer as "abstained" rather than "wrong" would quietly
    reward a system that refuses to answer, which is not what we are measuring here -- the
    abstention question is answered separately by risk-coverage.
    """
    if not answer:
        return None, 0.0
    choice = answer.get("choice")
    probs = answer.get("probabilities") or {}
    if choice is None:
        return None, 0.0
    p = probs.get(choice, answer.get("confidence", 0.0))
    return str(choice), float(p or 0.0)


def score_noul(answer: dict[str, Any] | None) -> tuple[int | None, float]:
    """Binary noul: returns ``(0|1, probability)``."""
    if not answer:
        return None, 0.0
    v = answer.get("noul")
    if v is None:
        v = answer.get("probability")
    if v is None:
        return None, 0.0
    v = float(v)
    return (1 if v >= 0.5 else 0), v


def score_score(answer: dict[str, Any] | None) -> tuple[float | None, float]:
    """Ordinal score: returns ``(level, confidence)``."""
    if not answer:
        return None, 0.0
    s = answer.get("score")
    if s is None:
        return None, 0.0
    return float(s), float(answer.get("confidence", 0.0) or 0.0)


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------


class ArmRunner:
    """Runs one arm over a list of items and returns per-item records."""

    def __init__(
        self,
        arm: str,
        system1: Any,
        system2_factory: Callable[[], System2Provider],
        protocol: Any,
        min_confidence: float = 0.55,
        d_max_turns: int = 4,
        c_samples: int = 1,
    ) -> None:
        self.arm = arm
        self.system1 = system1
        self.system2_factory = system2_factory
        self.protocol = protocol
        self.min_confidence = min_confidence
        self.d_max_turns = d_max_turns
        self.c_samples = c_samples

    def _observations(self, item: Item) -> list[Observation]:
        return [
            Observation(
                kind="document",
                source_id=f"eval:{item.id}",
                content=item.content,
                is_simulated=item.is_synthetic_text,
            )
        ]

    async def run_item(self, item: Item) -> dict[str, Any]:
        t0 = time.perf_counter()

        if self.arm not in ARMS:
            raise ValueError(f"unknown arm {self.arm!r}; expected one of {ARMS}")
        rec = await _ARM_DISPATCH[self.arm](self, item)

        rec["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        rec["item_id"] = item.id
        rec["stratum"] = item.stratum
        rec["annotator_confidence"] = item.annotator_confidence
        rec["is_synthetic_text"] = item.is_synthetic_text
        return rec

    # -- A: System-1 alone, no reasoning model -----------------------------
    async def _arm_a(self, item: Item) -> dict[str, Any]:
        spec = self.protocol.by_name("event_triage")
        rec = self.system1.answer(item.content, spec, turn_index=0, protocol_version=self.protocol.protocol_version)
        return {
            "answers": rec.answers,
            "system1_calls": 1,
            "system1_failures": 1 if rec.error else 0,
            "system2_calls": 0,
            "system2_failures": 0,
            "termination": "single_shot",
            "terminated_ok": not rec.error,
            "conclusion": "",
            "abstained": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "s1_ms": round(rec.latency_ms, 1),
            "s2_ms": 0.0,
        }

    # -- B: System-2 alone, no System-1 ------------------------------------
    async def _arm_b(self, item: Item) -> dict[str, Any]:
        provider = self.system2_factory()
        rt = DivyaRuntime(
            protocol=self.protocol,
            system2=provider,
            system1=NullSystem1(),
            config=LoopConfig(max_turns=2, min_confidence=self.min_confidence, allow_escalation=False),
        )
        try:
            result = await rt.run(
                domain="eval",
                objective=(
                    "Classify this Indian corporate disclosure. Report the event type, whether it "
                    "is material, its materiality level and its direction."
                ),
                observations=self._observations(item),
            )
        except Exception as exc:
            return {
                "answers": {},
                "system1_calls": 0,
                "system1_failures": 0,
                "system2_calls": 1,
                "system2_failures": 1,
                "termination": "error",
                "terminated_ok": False,
                "conclusion": f"error: {exc}",
                "abstained": True,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "s1_ms": 0.0,
                "s2_ms": 0.0,
            }

        s2 = result.state.system2_records
        return {
            "answers": {},
            "conclusion": result.state.conclusion,
            "system1_calls": 0,
            "system1_failures": 0,
            "system2_calls": len(s2),
            "system2_failures": sum(1 for r in s2 if r.error),
            "termination": result.state.termination.value if result.state.termination else None,
            # "Terminated without an error", NOT "set a status at all". `error` is a failure
            # and must not count as success -- the old check did, and reported 1.0 for an arm
            # that errored on 120 of 120 items. `max_turns` is NOT a failure either: arm C is
            # configured with max_turns=1, so exhausting its budget after its single System-1
            # call is its designed path, and scoring that as a failure would be wrong in the
            # other direction. See docs/loop/REVIEW.md D1.
            "terminated_ok": result.state.termination is not None
            and result.state.termination is not TerminationStatus.ERROR,
            "abstained": result.state.termination is not None
            and result.state.termination.value == "abstained",
            "prompt_tokens": sum(r.prompt_tokens for r in s2),
            "completion_tokens": sum(r.completion_tokens for r in s2),
            "s1_ms": 0.0,
            "s2_ms": round(sum(r.latency_ms for r in s2), 1),
        }

    # -- C: single-shot System-2 -> System-1 (the control) -----------------
    async def _arm_c(self, item: Item) -> dict[str, Any]:
        """One System-2 turn that requests the tier-1 decisions, then stop.

        ``max_turns=1`` means the loop can execute exactly one System-1 call and cannot see the
        result before deciding what to do -- which is exactly the single-shot semantics. The
        final answer is read from the System-1 record, not from System-2's prose, because
        System-2 is not allowed to restate a System-1 answer and have it count.

        ``c_samples`` repeats the call and takes a majority vote, so a loop-vs-single-shot
        comparison is not secretly a one-sample-vs-many-sample comparison.
        """
        provider = self.system2_factory()
        runs: list[LoopResult] = []
        for _ in range(max(1, self.c_samples)):
            rt = DivyaRuntime(
                protocol=self.protocol,
                system2=provider,
                system1=self.system1,
                config=LoopConfig(
                    max_turns=1,
                    min_confidence=self.min_confidence,
                    allow_escalation=False,
                    fallback_to_heuristic=False,
                ),
            )
            result = await rt.run(
                domain="eval",
                objective=(
                    "Classify this Indian corporate disclosure. Request the decisions you need."
                ),
                observations=self._observations(item),
            )
            runs.append(result)

        merged = self._majority_vote(runs)
        s1_recs = [r for run in runs for r in run.state.system1_records]
        s2_recs = [r for run in runs for r in run.state.system2_records]
        return {
            "answers": merged["answers"],
            "conclusion": runs[-1].state.conclusion,
            "system1_calls": sum(1 for r in s1_recs if not r.error),
            "system1_failures": sum(1 for r in s1_recs if r.error),
            "system2_calls": len(s2_recs),
            "system2_failures": sum(1 for r in s2_recs if r.error),
            "termination": runs[-1].state.termination.value if runs[-1].state.termination else None,
            "terminated_ok": True,
            "abstained": False,
            "prompt_tokens": sum(r.prompt_tokens for r in s2_recs),
            "completion_tokens": sum(r.completion_tokens for r in s2_recs),
            "s1_ms": round(sum(r.latency_ms for r in s1_recs), 1),
            "s2_ms": round(sum(r.latency_ms for r in s2_recs), 1),
            "c_samples": self.c_samples,
        }

    def _majority_vote(self, runs: list[LoopResult]) -> dict[str, Any]:
        """Majority-vote answers across repeated System-1 calls, keeping the first run's raw.

        Ties fall back to the first sample, and the choice is recorded in ``vote_tie`` so a
        report can say how often the vote was meaningless rather than presenting a coin flip
        as a consensus.
        """
        if len(runs) == 1:
            return {"answers": runs[0].state.latest_system1, "vote_tie": False}

        tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for run in runs:
            for name, ans in run.state.latest_system1.items():
                key = ans.get("choice")
                if key is not None:
                    tally[name][str(key)] += 1

        merged = dict(runs[0].state.latest_system1)
        tie = False
        for name, votes in tally.items():
            top = max(votes.items(), key=lambda kv: kv[1])
            tie = tie or (top[1] * 2 <= sum(votes.values()))
            if name in merged:
                merged[name] = {**merged[name], "choice": top[0], "vote_counts": dict(votes)}
        return {"answers": merged, "vote_tie": tie}

    # -- D: the recurrent loop ---------------------------------------------
    async def _arm_d(self, item: Item) -> dict[str, Any]:
        provider = self.system2_factory()
        rt = DivyaRuntime(
            protocol=self.protocol,
            system2=provider,
            system1=self.system1,
            config=LoopConfig(
                max_turns=self.d_max_turns,
                min_confidence=self.min_confidence,
                allow_escalation=True,
            ),
        )
        result = await rt.run(
            domain="eval",
            objective=(
                "Classify this Indian corporate disclosure. Request more decisions if the "
                "evidence is insufficient; otherwise conclude or abstain."
            ),
            observations=self._observations(item),
        )
        s1 = result.state.system1_records
        s2 = result.state.system2_records
        return {
            "answers": result.state.latest_system1,
            "conclusion": result.state.conclusion,
            "system1_calls": sum(1 for r in s1 if not r.error),
            "system1_failures": sum(1 for r in s1 if r.error),
            "system2_calls": len(s2),
            "system2_failures": sum(1 for r in s2 if r.error),
            "termination": result.state.termination.value if result.state.termination else None,
            # "Terminated without an error", NOT "set a status at all". `error` is a failure
            # and must not count as success -- the old check did, and reported 1.0 for an arm
            # that errored on 120 of 120 items. `max_turns` is NOT a failure either: arm C is
            # configured with max_turns=1, so exhausting its budget after its single System-1
            # call is its designed path, and scoring that as a failure would be wrong in the
            # other direction. See docs/loop/REVIEW.md D1.
            "terminated_ok": result.state.termination is not None
            and result.state.termination is not TerminationStatus.ERROR,
            "abstained": result.state.termination is not None
            and result.state.termination.value == "abstained",
            "prompt_tokens": sum(r.prompt_tokens for r in s2),
            "completion_tokens": sum(r.completion_tokens for r in s2),
            "s1_ms": round(sum(r.latency_ms for r in s1), 1),
            "s2_ms": round(sum(r.latency_ms for r in s2), 1),
            "turns": result.state.turn_index,
        }


#: arm letter -> the method that runs it. A table rather than an if-chain so that adding an
#: arm cannot silently fall through to another arm's result.
_ARM_DISPATCH: dict[str, Callable[[ArmRunner, Item], Any]] = {
    "A": ArmRunner._arm_a,
    "B": ArmRunner._arm_b,
    "C": ArmRunner._arm_c,
    "D": ArmRunner._arm_d,
}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(records: list[dict[str, Any]], items_by_id: dict[str, Item]) -> dict[str, Any]:
    """Quality, calibration and cost, pooled and per stratum."""
    y_true: list[str] = []
    y_pred: list[str] = []
    probs: list[float] = []
    correct: list[int] = []

    mat_true: list[int] = []
    mat_pred: list[float] = []

    matl_true: list[int] = []
    matl_pred: list[float] = []
    matl_conf: list[float] = []
    matl_correct: list[int] = []

    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for r in records:
        item = items_by_id[r["item_id"]]
        by_stratum[item.stratum].append(r)
        answers = r.get("answers") or {}

        pred, p = score_event_type(answers.get("event_type"))
        truth = str(item.labels["event_type"])
        # An arm that returned no answer is scored wrong at zero confidence, so it cannot
        # silently improve a calibration metric by opting out of being scored.
        y_true.append(truth)
        y_pred.append(pred if pred is not None else "__none__")
        probs.append(p)
        correct.append(1 if pred == truth else 0)

        # Only score a decision when the dataset actually carries a label for it. The live NSE
        # feed supplies `desc` -> `event_type` and nothing else; there is no published ground
        # truth for is_material, materiality or direction. Inventing one, or scoring the model
        # against its own output, would be circular. The report names which metrics ran.
        if "is_material" in item.labels:
            want = 1 if item.labels["is_material"] else 0
            n_pred, n_p = score_noul(answers.get("is_material"))
            matl_true.append(want)
            matl_pred.append(n_p)
            matl_conf.append(n_p)
            matl_correct.append(1 if n_pred == want else 0)

        if "materiality" in item.labels:
            s_pred, _s_conf = score_score(answers.get("materiality"))
            if s_pred is not None:
                mat_pred.append(s_pred)
                mat_true.append(int(item.labels["materiality"]))

    ece, ece_bins = M.expected_calibration_error(probs, correct)
    curve, aurc = M.risk_coverage(probs, correct)

    latencies = [float(r.get("wall_ms", 0.0)) for r in records]
    s1_costs = [float(r.get("s1_ms", 0.0)) for r in records]

    out: dict[str, Any] = {
        "n_items": len(records),
        "event_type": M.classification_report(y_true, y_pred).as_dict(),
        "calibration": {
            "brier_event_type": round(M.brier_score(probs, correct), 4),
            "ece_event_type": round(ece, 4),
            "ece_bins": ece_bins,
            "aurc": round(aurc, 4),
            "risk_coverage": curve[:: max(1, len(curve) // 20)],
        },
        "is_material_noul": (
            {
                "n_labeled": len(matl_true),
                "brier": round(M.binary_brier(matl_pred, matl_true), 4),
                "ece": round(M.expected_calibration_error(matl_conf, matl_correct)[0], 4),
                "accuracy_at_0.5": round(sum(matl_correct) / len(matl_correct), 4),
            }
            if matl_true
            else {"n_labeled": 0, "status": "not evaluated: dataset has no is_material ground truth"}
        ),
        "materiality_ordinal": (
            {
                "n_labeled": len(mat_true),
                "exact": round(
                    sum(1 for t, p in zip(mat_true, mat_pred, strict=True) if round(p) == t)
                    / len(mat_true), 4
                ),
                "within_one": round(M.near_miss_rate(mat_true, mat_pred, 1), 4),
            }
            if mat_true
            else {"n_labeled": 0, "status": "not evaluated: dataset has no materiality ground truth"}
        ),
        "cost": {
            "wall_ms_mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
            "wall_ms_p95": round(M.p95(latencies), 1),
            "system1_ms_mean": round(statistics.fmean(s1_costs), 1) if s1_costs else 0.0,
            "system1_calls_mean": round(
                statistics.fmean([float(r.get("system1_calls", 0)) for r in records]), 3
            ) if records else 0.0,
            "system2_calls_mean": round(
                statistics.fmean([float(r.get("system2_calls", 0)) for r in records]), 3
            ) if records else 0.0,
            "prompt_tokens_mean": round(
                statistics.fmean([float(r.get("prompt_tokens", 0)) for r in records]), 1
            ) if records else 0.0,
            "completion_tokens_mean": round(
                statistics.fmean([float(r.get("completion_tokens", 0)) for r in records]), 1
            ) if records else 0.0,
            "unnecessary_system1_calls": int(
                sum(max(0, int(r.get("system1_calls", 0)) - 1) for r in records)
            ),
        },
        "reliability": {
            "terminated_ok_rate": round(
                sum(1 for r in records if r.get("terminated_ok")) / len(records), 4
            ) if records else 0.0,
            "abstention_rate": round(
                sum(1 for r in records if r.get("abstained")) / len(records), 4
            ) if records else 0.0,
            "system1_failure_rate": round(
                sum(1 for r in records if int(r.get("system1_failures", 0)) > 0) / len(records), 4
            ) if records else 0.0,
            "max_turns_hit_rate": round(
                sum(1 for r in records if r.get("termination") == "max_turns") / len(records), 4
            ) if records else 0.0,
        },
        "by_stratum": {},
    }

    for stratum, recs in sorted(by_stratum.items()):
        sub = aggregate_stratum(recs, items_by_id)
        out["by_stratum"][stratum] = sub

    return out


def aggregate_stratum(records: list[dict[str, Any]], items_by_id: dict[str, Item]) -> dict[str, Any]:
    y_true, y_pred, probs, correct = [], [], [], []
    for r in records:
        item = items_by_id[r["item_id"]]
        pred, p = score_event_type((r.get("answers") or {}).get("event_type"))
        y_true.append(str(item.labels["event_type"]))
        y_pred.append(pred if pred is not None else "__none__")
        probs.append(p)
        correct.append(1 if pred == str(item.labels["event_type"]) else 0)
    rep = M.classification_report(y_true, y_pred)
    ece, _ = M.expected_calibration_error(probs, correct)
    _, aurc = M.risk_coverage(probs, correct)
    return {
        "n": len(records),
        "accuracy": round(rep.accuracy, 4),
        "macro_f1": round(rep.macro_f1, 4),
        "brier": round(M.brier_score(probs, correct), 4),
        "ece": round(ece, 4),
        "aurc": round(aurc, 4),
        "abstention_rate": round(
            sum(1 for r in records if r.get("abstained")) / len(records), 4
        ) if records else 0.0,
        "wall_ms_mean": round(
            statistics.fmean([float(r.get("wall_ms", 0)) for r in records]), 1
        ) if records else 0.0,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_system2_factory(
    provider_name: str, model: str | None, base_url: str | None
) -> Callable[[], System2Provider]:
    """Construct System-2 providers lazily, once per run rather than once per item.

    Constructing an OllamaProvider is cheap, but constructing a *model* is not, and rebuilding
    per item would put cold-start cost into every latency number.
    """
    kind = provider_name.strip().lower()
    if kind == "heuristic":
        return lambda: HeuristicProvider()
    if kind == "ollama":
        from divya.system2.provider import OllamaProvider

        return lambda: OllamaProvider(model=model or "qwen2.5-coder:3b", base_url=base_url or "http://localhost:11434")
    if kind in {"openai_compatible", "openai"}:
        from divya.system2.provider import OpenAICompatProvider

        if not base_url:
            raise SystemExit("--base-url is required for the openai_compatible provider")
        return lambda: OpenAICompatProvider(model=model or "local", base_url=base_url)
    raise SystemExit(f"unknown provider {provider_name!r}")


async def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    protocol = load_protocol()
    items = load_items(args.dataset, limit=args.limit, strata=args.strata)
    if not items:
        raise SystemExit(f"no items loaded from {args.dataset}")
    items_by_id = {i.id: i for i in items}

    system1 = LayaSystem1() if LayaSystem1().is_available() else NullSystem1()
    if isinstance(system1, NullSystem1):
        print("WARNING: System-1 unavailable; arms A/C/D will produce no answers.", file=__import__("sys").stderr)

    factory = build_system2_factory(args.provider, args.model, args.base_url)

    all_records: dict[str, list[dict[str, Any]]] = {}
    for arm in args.arms:
        print(f"[arm {arm}] running {len(items)} items ...", flush=True)
        runner = ArmRunner(
            arm=arm,
            system1=system1,
            system2_factory=factory,
            protocol=protocol,
            min_confidence=args.min_confidence,
            d_max_turns=args.max_turns,
            c_samples=args.c_samples,
        )
        recs: list[dict[str, Any]] = []
        t0 = time.perf_counter()
        for i, item in enumerate(items, 1):
            rec = await runner.run_item(item)
            recs.append(rec)
            if i % args.progress_every == 0 or i == len(items):
                el = time.perf_counter() - t0
                print(f"  {arm}: {i}/{len(items)} ({el:.0f}s)", flush=True)
        all_records[arm] = recs

    report: dict[str, Any] = {
        "dataset": {
            "path": args.dataset,
            "n_items": len(items),
            "strata": {s: sum(1 for i in items if i.stratum == s) for s in sorted({i.stratum for i in items})},
            "synthetic_text": all(i.is_synthetic_text for i in items),
            "note": (
                "Text is authored for this project, not scraped. Accuracy measures agreement "
                "with these labels, not correctness about the Indian market. See "
                "evals/make_dataset.py."
            ),
        },
        "config": {
            "arms": args.arms,
            "provider": args.provider,
            "model": args.model,
            "min_confidence": args.min_confidence,
            "d_max_turns": args.max_turns,
            "c_samples": args.c_samples,
            "system1_available": not isinstance(system1, NullSystem1),
        },
        "results": {},
        "per_item": {arm: all_records[arm] for arm in args.arms},
    }
    for arm, recs in all_records.items():
        report["results"][arm] = aggregate(recs, items_by_id)
        # An arm that answered nothing at all has not scored 0.000 -- it has failed, and the
        # two are indistinguishable in the results table without this. Arm B in the real run
        # errored on 120 of 120 and produced no output; reading its 0.000 as "System-2 alone
        # is useless" would be reading a wiring failure as a model result.
        answered = sum(
            1
            for r in recs
            if ((r.get("answers") or {}).get("event_type") or {}).get("choice")
        )
        if recs and answered == 0:
            print(
                f"ERROR: arm {arm} produced NO event_type answer on any of {len(recs)} items. "
                f"Terminations: "
                f"{sorted(str(r.get('termination')) for r in recs)}. Its 0.000 accuracy is a "
                f"FAILED ARM, not a measurement of the architecture.",
                file=sys.stderr,
                flush=True,
            )
            report["results"][arm]["ARM_FAILED_NO_OUTPUT"] = True
        r = report["results"][arm]
        print(
            f"[arm {arm}] acc={r['event_type']['accuracy']:.3f} "
            f"macroF1={r['event_type']['macro_f1']:.3f} "
            f"ECE={r['calibration']['ece_event_type']:.3f} "
            f"AURC={r['calibration']['aurc']:.3f} "
            f"p95={r['cost']['wall_ms_p95']:.0f}ms",
            flush=True,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[written] {out}")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Divya A/B/C/D evaluation harness")
    ap.add_argument("--dataset", default="evals/datasets/event_triage_v1.jsonl")
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument("--provider", default="ollama",
                    help="ollama | openai_compatible | heuristic")
    ap.add_argument("--model", default="qwen2.5-coder:3b")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--strata", nargs="*", default=None)
    ap.add_argument("--min-confidence", type=float, default=0.55)
    ap.add_argument("--max-turns", type=int, default=4)
    ap.add_argument("--c-samples", type=int, default=1,
                    help="self-consistency repeats for arm C; controls for sample count")
    ap.add_argument("--progress-every", type=int, default=10)
    ap.add_argument("--out", default="evals/results/eval.json")
    args = ap.parse_args(argv)
    asyncio.run(run_eval(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
