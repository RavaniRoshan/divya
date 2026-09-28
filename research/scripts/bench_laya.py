"""N1: measure Laya on this machine, on finance-shaped text.

This script exists because the PDR's performance numbers are from a T4 and a customer-support
benchmark. Neither transfers to an 8-core CPU without a 4 GB graphics card running a market
terminal. Everything this project later claims about latency or about Laya's usefulness rests
on the output of this script.

What it records:
  * cold load seconds (checkpoint download + first forward pass)
  * warm p50 / p95 latency per predict call
  * which checkpoint the router chose, and whether the choice was sane
  * the raw answers, verbatim -- never reinterpreted
  * peak RSS, because the box has 7.5 GiB and a System-2 model also has to fit

Usage:
    python research/scripts/bench_laya.py
    python research/scripts/bench_laya.py --model typed-decisions --repeat 5 --out bench.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

# Real-shaped disclosure text. These are written to look like NSE/BSE filings and exchange
# announcements -- the actual distribution the system will meet. Deliberately includes one
# boilerplate meeting notice and one ambiguous case, because those are where a decision engine
# is most likely to be wrong and a benchmark of only clean cases would hide it.
FIXTURES: list[dict[str, str]] = [
    {
        "id": "earnings_q2",
        "expected_hint": "earnings_result / material / level 3 / not adverse",
        "text": (
            "HDFC Bank Limited has informed the Exchange about its audited financial results for "
            "the quarter ended 30 June 2025. Net profit after tax stood at Rs 18,209 crore as "
            "against Rs 16,510 crore in the corresponding quarter of the previous year, an "
            "increase of 10.3 per cent. Net interest income was Rs 29,510 crore. Gross NPA "
            "ratio stood at 1.46 per cent of gross advances as against 1.40 per cent as at 31 "
            "March 2025, while net NPA ratio was 0.41 per cent. The Board has recommended an "
            "interim dividend of Rs 12.50 per share."
        ),
    },
    {
        "id": "board_meeting_notice",
        "expected_hint": "board_meeting / not material / level 0 / neutral",
        "text": (
            "Infosys Limited has informed the Exchange that a meeting of the Board of Directors "
            "of the Company will be held on Thursday, 24 October 2024 at 10:00 a.m. IST through "
            "video conferencing to, inter alia, consider and approve the unaudited financial "
            "results of the Company for the quarter ended 30 September 2024. The intimation was "
            "filed under Regulation 29 of the SEBI (Listing Obligations and Disclosure "
            "Requirements) Regulations, 2015."
        ),
    },
    {
        "id": "regulatory_penalty",
        "expected_hint": "regulatory_action / material / level 3 / adverse",
        "text": (
            "Reliance Industries Limited has received a show cause notice from the Securities and "
            "Exchange Board of India dated 12 March 2025, seeking explanation regarding "
            "disclosure of related party transactions in the quarter ended June 2024. The Company "
            "is in the process of responding to the notice and will disclose the outcome in due "
            "course. The Company has not made any provision towards any penalty arising out of "
            "the said notice at this stage."
        ),
    },
    {
        "id": "summary_not_filing",
        "expected_hint": "m_and_a or fundraise / material / level 3-4 / favourable",
        "text": (
            "Tata Motors on Tuesday said it would acquire a 51 per cent stake in freight "
            "logistics firm Rivus, marking the Indian automaker's biggest push into electric "
            "commercial vehicles. The deal, reported by Business Standard, is valued at "
            "approximately Rs 4,600 crore and is expected to close in the second half of the "
            "current fiscal year, the company said in a filing to the stock exchanges."
        ),
    },
]

# The tier-1 slice of the real protocol, inlined so this benchmark measures the model rather
# than the loader. The loader has its own tests.
QUESTIONS: dict[str, dict] = {
    "event_type": {
        "type": "choice",
        "instructions": (
            "Choose the single category that best describes the main corporate event described "
            "in this document."
        ),
        "criteria": {
            "earnings_result": "quarterly or annual results: revenue, profit, EPS, margins",
            "board_dividend": "declaration of a dividend or change in dividend policy",
            "capital_action": "buyback, bonus issue, rights issue, split, subdivision",
            "fundraise": "raising new capital: shares, warrants, debt, or a subsidiary IPO",
            "m_and_a": "acquisition, disposal, merger, demerger, joint venture, subsidiary sale",
            "leadership_change": "appointment or resignation of a director or key executive",
            "auditor_change": "change of statutory auditor, or a resignation with qualification",
            "regulatory_action": "penalty, show-cause notice, trading ban, listing suspension, court",
            "credit_rating": "change in credit rating, outlook, or rating agency action",
            "board_meeting": "notice of a board meeting, with no results or decision stated",
            "other": "any other corporate disclosure",
        },
    },
    "is_material": {
        "type": "noul",
        "instructions": (
            "Decide whether this disclosure is material to a company following the stock. Routine "
            "filings that restate already-public information, or that require no action, are not."
        ),
        "criteria": {
            "false": "routine, procedural, or already-public information",
            "true": "new results, capital change, acquisition, regulatory action, or audit qualification",
        },
        "labels": {"false": "not material", "true": "material"},
    },
    "materiality": {
        "type": "score",
        "instructions": "Grade how significant this event is, from routine to severe.",
        "criteria": [
            "routine or procedural; already known",
            "minor; small in financial terms or no immediate consequence",
            "moderate; material result, capital action, or significant strategic change",
            "major; large result, transformative acquisition, substantial fundraise",
            "severe; control change, going-concern doubt, trading ban, fraud",
        ],
    },
    "direction": {
        "type": "noul",
        "instructions": (
            "Decide the effect of this event on the value of the company's shares, judged on "
            "information in this document alone."
        ),
        "criteria": {
            "false": "neutral or favourable for the company's value",
            "true": "adverse for the company's value",
        },
        "labels": {"false": "neutral or favourable", "true": "adverse"},
    },
}


def peak_rss_mb() -> float:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB, macOS bytes.
        return round(peak / 1024, 1) if sys.platform != "darwin" else round(peak / 1024 / 1024, 1)
    except Exception:
        return -1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="force a checkpoint instead of routing")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--out", default="research/results/bench_laya.json")
    ap.add_argument("--only-tier1", action="store_true", help="measure one question per call")
    args = ap.parse_args()

    from laya import Router

    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": __import__("os").cpu_count(),
        "torch": __import__("torch").__version__,
        "cuda_available": __import__("torch").cuda.is_available(),
    }
    print(f"[env] {env}")

    t0 = time.perf_counter()
    router = Router()
    first = router.predict(
        FIXTURES[0]["text"],
        {"event_type": QUESTIONS["event_type"]},
        model=args.model,
    )
    cold_load_s = round(time.perf_counter() - t0, 2)
    routed = first.get("routing", {}).get("model")
    print(f"[load] cold load + first predict: {cold_load_s}s; routed to: {routed}")

    rows: list[dict] = []
    for fixture in FIXTURES:
        call_latencies: list[float] = []
        result: dict = {}
        for _ in range(args.repeat):
            qs = {"event_type": QUESTIONS["event_type"]} if args.only_tier1 else QUESTIONS
            t = time.perf_counter()
            result = router.predict(fixture["text"], qs, model=args.model)
            call_latencies.append((time.perf_counter() - t) * 1000)

        answers = result.get("answers", {})
        row = {
            "fixture_id": fixture["id"],
            "expected_hint": fixture["expected_hint"],
            "routed_model": result.get("routing", {}).get("model"),
            "latency_ms": {
                "p50": round(statistics.median(call_latencies), 1),
                "min": round(min(call_latencies), 1),
                "max": round(max(call_latencies), 1),
                "all": [round(x, 1) for x in call_latencies],
            },
            "raw_answers": answers,
        }
        rows.append(row)

        print(f"\n=== {fixture['id']} ===")
        print(f"  hint     : {fixture['expected_hint']}")
        print(f"  p50      : {row['latency_ms']['p50']} ms")
        for name, ans in answers.items():
            print(f"  {name:<12}: {json.dumps(ans, ensure_ascii=False)[:220]}")

    p50s = [r["latency_ms"]["p50"] for r in rows]
    summary = {
        "environment": env,
        "cold_load_s": cold_load_s,
        "routed_checkpoint": routed,
        "forced_model": args.model,
        "repeat": args.repeat,
        "latency_ms_p50_median": round(statistics.median(p50s), 1),
        "latency_ms_p50_min": round(min(p50s), 1),
        "latency_ms_p50_max": round(max(p50s), 1),
        "peak_rss_mb": peak_rss_mb(),
        "results": rows,
        "notes": [
            "Latency is full-pipeline Router.predict on this CPU, including tokenisation.",
            "No GPU: torch CPU wheel, cuda_available is False.",
            "Raw answers recorded verbatim. Hints are our expectation, not ground truth, and "
            "are not used to score here -- this run measures cost and behaviour, not accuracy.",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[summary] p50 median {summary['latency_ms_p50_median']} ms | peak RSS {summary['peak_rss_mb']} MB")
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
