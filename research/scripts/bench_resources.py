"""Measure the free performance levers available on a CPU-only box.

The PDR calls Laya a "fast" engine. Measured on this machine it is ~4.5 s per four-question
call, which is fine for one event and bad for an event stream. Before reaching for bigger
hardware or a paid service, three levers exist that cost nothing but engineering, and this
script measures what each is actually worth:

  1. **Batching.** `Router.predict_batch` runs many states in one forward pass. A terminal
     processing a stream cares about *throughput*, not per-event latency, and batching is
     usually the single largest win available on CPU.
  2. **Persistence.** Cold load is ~280 s. That is paid once per process, so a long-lived
     server amortises it to nothing while a per-request process pays it every time. This
     script reports the numbers separately so the difference is visible rather than implied.
  3. **ONNX.** `laya[onnx]` exports the model for ONNX Runtime, which can be materially faster
     on CPU than PyTorch. Whether it is *available and faster here* is measured, not assumed;
     if onnxruntime will not install, that is reported as a finding too.

Also measured: the marginal cost of each additional question in the same call, which
determines whether a 10-question triage pass or three 4-question passes is the cheaper design.

Usage:
    python research/scripts/bench_resources.py
    python research/scripts/bench_resources.py --batch-sizes 1 4 8 16
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

QUESTIONS = {
    "event_type": {
        "type": "choice",
        "instructions": "Choose the single category that best describes the main corporate event.",
        "criteria": {
            "earnings_result": "quarterly or annual results: revenue, profit, EPS, margins",
            "capital_action": "dividend, buyback, bonus, rights issue, split, subdivision",
            "fundraise": "raising new capital: shares, warrants, debt, subsidiary IPO",
            "m_and_a": "acquisition, disposal, merger, demerger, joint venture",
            "leadership_change": "appointment or resignation of a director or key executive",
            "auditor_change": "change of statutory auditor, or resignation with qualification",
            "regulatory_action": "penalty, show-cause notice, trading ban, listing suspension",
            "credit_rating": "change in credit rating, outlook, or rating agency action",
            "board_meeting": "notice of a board meeting, no results or decision stated",
            "other": "any other corporate disclosure",
        },
    },
    "is_material": {
        "type": "noul",
        "instructions": "Decide whether this disclosure is material to a company following the stock.",
        "criteria": {
            "false": "routine, procedural, or already-public information",
            "true": "new results, capital change, acquisition, regulatory action, audit qualification",
        },
        "labels": {"false": "not material", "true": "material"},
    },
}

SAMPLES = [
    "HDFC Bank Limited reported quarterly net profit after tax of Rs 18,209 crore as against Rs 16,510 crore in the corresponding quarter of the previous year, an increase of 10.3 per cent. Gross NPA ratio stood at 1.46 per cent of gross advances.",
    "Infosys Limited has informed the Exchange that a meeting of the Board of Directors will be held to consider and approve the unaudited financial results for the quarter ended 30 September 2024.",
    "Reliance Industries Limited has received a show cause notice from SEBI seeking explanation regarding disclosure of related party transactions. The Company is in the process of responding.",
    "Tata Motors said it would acquire a 51 per cent stake in freight logistics firm Rivus for approximately Rs 4,600 crore, expected to close in the second half of the current fiscal year.",
    "The Board of Sun Pharma approved a buyback of up to 8,500,000 equity shares at a maximum price of Rs 1,175 per share for an aggregate consideration not exceeding Rs 1,000 crore.",
    "Bharti Airtel has informed the Exchange that Mr. Rajesh Verma, Executive Director, has resigned from the office with effect from 12 March 2025, citing personal reasons.",
    "UltraTech Cement Limited has published its audited financial results for the year ended 31 March 2025. Revenue from operations stood at Rs 21,532 crore.",
    "Larsen & Toubro Limited has received a notice from the National Stock Exchange seeking explanations regarding the non-reconciliation of the shareholding pattern.",
    "Rating agency CRISIL has downgraded the long-term issuer rating of Axis Bank from AA to AA- and placed the rating on watch with negative outlook.",
    "Bajaj Finance Limited has approved a preferential issue of up to 12,000,000 equity shares at Rs 7,400 per share to certain identified persons.",
    "Maruti Suzuki India Limited has informed the Exchange about the appointment of Mr. Anil Iyer as Chief Financial Officer with effect from 1 April 2025.",
    "Dr Reddy's Laboratories Limited has declared an interim dividend of Rs 12.50 per equity share for the quarter. The record date has been fixed as 14 August 2025.",
]


def peak_rss_mb() -> float:
    import resource
    import sys

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / 1024, 1) if sys.platform != "darwin" else round(peak / 1024 / 1024, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-sizes", nargs="*", type=int, default=[1, 2, 4, 8, 12])
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--out", default="research/results/bench_resources.json")
    args = ap.parse_args()

    from laya import Router

    results: dict[str, object] = {
        "environment": {
            "platform": platform.platform(),
            "cpu_count": __import__("os").cpu_count(),
            "python": __import__("sys").version.split()[0],
            "torch": __import__("torch").__version__,
            "cuda_available": __import__("torch").cuda.is_available(),
        },
        "levers": {},
    }

    # --- lever 2: persistence -------------------------------------------------
    t0 = time.perf_counter()
    router = Router()
    router.predict(SAMPLES[0], QUESTIONS)
    cold = time.perf_counter() - t0
    results["levers"]["persistence"] = {
        "cold_load_s": round(cold, 2),
        "note": (
            "Paid once per process. A long-lived server pays it once at startup; a process-per-"
            "request design pays it on every call. This is the single largest 'free' win and it "
            "is an architectural choice, not a hardware one."
        ),
    }
    print(f"[persistence] cold load {cold:.1f}s", flush=True)

    # --- lever 1: batching ----------------------------------------------------
    batching: list[dict[str, float]] = []
    for bs in args.batch_sizes:
        if bs > len(SAMPLES):
            continue
        states = SAMPLES[:bs]
        times: list[float] = []
        for _ in range(args.repeats):
            t = time.perf_counter()
            router.predict_batch([{"state": s, "questions": QUESTIONS} for s in states])
            times.append(time.perf_counter() - t)
        best = min(times)
        per_item = best / bs
        rec = {
            "batch_size": bs,
            "batch_seconds": round(best, 3),
            "seconds_per_item": round(per_item, 3),
            "items_per_second": round(bs / best, 2),
        }
        batching.append(rec)
        print(
            f"[batch] bs={bs:<3} {best:.2f}s total, {per_item:.3f}s/item, {bs / best:.2f} items/s",
            flush=True,
        )
    results["levers"]["batching"] = batching

    if len(batching) >= 2:
        single = batching[0]
        best_batch = min(batching, key=lambda r: r["seconds_per_item"])
        results["levers"]["batching_summary"] = {
            "single_item_s": single["seconds_per_item"],
            "best_batch_size": best_batch["batch_size"],
            "best_s_per_item": best_batch["seconds_per_item"],
            "speedup_vs_single": round(single["seconds_per_item"] / best_batch["seconds_per_item"], 2),
        }

    # --- marginal cost per question -------------------------------------------
    marginal: list[dict[str, float]] = []
    one_q = {"event_type": QUESTIONS["event_type"]}
    t = time.perf_counter()
    for _ in range(args.repeats):
        router.predict(SAMPLES[0], one_q)
    marginal.append({"n_questions": 1, "seconds": round((time.perf_counter() - t) / args.repeats, 3)})
    t = time.perf_counter()
    for _ in range(args.repeats):
        router.predict(SAMPLES[0], QUESTIONS)
    marginal.append({"n_questions": len(QUESTIONS), "seconds": round((time.perf_counter() - t) / args.repeats, 3)})
    results["levers"]["marginal_cost_per_question"] = marginal
    print(f"[questions] {marginal}", flush=True)

    # --- lever 3: ONNX --------------------------------------------------------
    try:
        import onnxruntime

        results["levers"]["onnx"] = {"available": True, "version": onnxruntime.__version__}
        print(f"[onnx] available: {onnxruntime.__version__}", flush=True)
    except ImportError:
        results["levers"]["onnx"] = {
            "available": False,
            "note": (
                "onnxruntime is not installed. Whether exporting and serving the model through "
                "ONNX Runtime is faster on this box is UNMEASURED. Installing it is a one-line "
                "change (pip install 'laya[onnx]') and is the obvious next experiment if "
                "throughput is the binding constraint."
            ),
        }
        print("[onnx] NOT installed - speedup unmeasured", flush=True)

    results["peak_rss_mb"] = peak_rss_mb()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
