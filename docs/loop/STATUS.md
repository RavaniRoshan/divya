# STATUS

_Last updated: 2026-09-28, iteration 3._

## CURRENT OBJECTIVE

The A/B/C/D evaluation on real NSE data is running. Everything needed to interpret it exists:
the harness, the metrics, the real dataset, and the protocol. When it lands, the job is to read
it honestly — including if D does not beat C.

## WHAT CHANGED

- **Real data pipeline working end to end.** Live NSE corporate announcements, bhavcopy, and
  NIFTY 50 constituents all verified by direct fetch. 14,805 announcements for Sept 2026.
- **Real evaluation dataset built**: 1,042 event-bearing announcements, 664 symbols, 61
  industries, labelled by NSE's own `desc` taxonomy via an explicit 104-class mapping.
- **A calibration bug found and fixed** that was silently invalidating every confidence number.
- **Two measured performance findings that changed the design**: the 4B reasoning model is
  unusable on this hardware, and batching does not work here.
- **The product works end to end**: `divya doctor`, `divya fetch`, `divya decide` (with the full
  terminal view and a reconstructable JSON trace), `divya show`, `divya protocol`.
- 79 tests, ruff clean, mypy clean.
- Architecture spec (`docs/architecture/UNIFIED_MODEL.md`), README, Makefile, Dockerfile and
  compose written.

## EVIDENCE

### `[RESULT]` Synthetic data was flattering us — the user's challenge was correct

| Population | Laya `event_type` accuracy |
|---|---|
| Synthetic, `clear` stratum (n=30) | **0.733** |
| **Real NSE announcements** (n=24) | **0.500** |

Roughly 23 points of optimism, entirely from authored text. Every synthetic number in this
repository is now reported beside its real counterpart or not at all.

### `[RESULT]` Real NSE data is available and usable (verified 2026-09-28)

| Source | Status |
|---|---|
| `api/corporate-announcements?from_date&to_date` | **HTTP 200, 14,805 records for Sept 2026, no cookies** |
| `nsearchives…/content/cm/BhavCopy_….csv.zip` | **HTTP 200, 177,333 bytes, valid CSV** |
| `archives…/ind_nifty50list.csv` | **HTTP 200, 50 rows** |
| NSE historical price API | **503 on every path** — no free NSE time series |
| BSE (archives + API) | **unreachable** — no DNS / 403 |
| `yfinance` | real Indian prices (RELIANCE.NS to 1996) but Yahoo ToS bans automated collection |
| HuggingFace bhavcopy datasets | real but overwhelmingly unlicensed |

A browser User-Agent is mandatory on every NSE host — without one, nothing is returned at all.

### `[RESULT]` The real distribution is the finding

The six largest NSE classes are process, not corporate events:

    Shareholders meeting 2668 · Trading Window 1858 · General Updates 1752
    Analysts/Investor Meet 1700 · Copy of Newspaper 1415 · Updates 1035

**77% of a real Indian announcement feed contains no corporate event.** These are ingested and
labelled `unresolved`, never dropped and never guessed. `Outcome of Board Meeting` (456, the
largest event-bearing class) is also `unresolved` — the text often does not state the outcome.

### `[RESULT]` The checkpoint's `choice:11+` bucket is uncalibrated — and we were in it

`rl_agent_config.json` ships temperature **0.1006** for `choice:11+`, which *sharpens* logits
~10×. Laya clamps it to 0.5 and warns that confidence from that bucket is uncalibrated. Our
11-option `event_type` was in exactly that bucket. Fixed by merging `board_dividend` into
`capital_action` (v1 → v2, 10 options, valid `choice:6-10` bucket), plus a load-time guard so it
cannot recur. See D-008.

**After the fix, calibration is still poor on real data**: ECE 0.182, and in the 0.6–0.73
confidence band accuracy is **20% against 63% stated confidence** (n=5). At 0.93–1.0 it is well
calibrated (n=7, 100%). Moving out of the broken bucket removed a defect; it did not make Laya
calibrated on finance text.

### `[RESULT]` Laya on this CPU

| Metric | Value |
|---|---|
| Hardware | WSL2, 16 vCPU Ryzen 7 4800H, 7.5 GiB RAM, no GPU |
| Latency, 4-question call | **4552 ms p50** = 1138 ms/question |
| Peak RSS | 2.75 GB |
| Checkpoint load | 6.6 s (plus a one-time ~270 s download) |
| PDR's claim | 193–464 ms/question — **falsified, 2.4–5.9× optimistic** |

### `[RESULT]` System-2 model sizing, measured

| Model | Warm wall | Own eval time | Verdict |
|---|---|---|---|
| `qwen2.5-coder:3b` | 0.56–0.91 s | 0.32–0.36 s | default |
| `qwen3:4b` | 42–64 s | 1.3–2.2 s | memory thrash — unusable |

### `[RESULT]` Batching is not a lever here

`predict_batch` gives **1.10× at best** (batch 4). Torch already saturates all 16 threads on a
single item. Recorded as a negative result in D-011 so it is not re-attempted.

### `[RESULT]` The loop works end to end with a real model

A 3B model drove a genuine 4-turn loop: tier-1 decisions → evidence-quality escalation →
numeric-presence check → finish at 0.81 confidence. 3 System-1 calls, 4 System-2 calls,
14,227 ms System-1 + 12,872 ms System-2. Full trace reconstructable from `data/traces/`.

## TESTS

**79 passing.** `ruff check` clean, `mypy src/divya` clean. Coverage includes: every Laya
contract rule, the calibration-bucket guard, hand-computed metric values, termination totality
across six distinct paths, degradation for missing/broken/failing System-1 and System-2, trace
reconstructability, frozen-record immutability, and the freshness/provenance invariants.

## BENCHMARKS

All in `research/results/` and `docs/loop/EVALS.md`, each with hardware, model version, n, and
baseline. The A/B/C/D comparison is in progress.

## KNOWN FAILURES

- `FetchURL` tool fails on every host here; `curl` via Bash is the working path.
- Docker absent → `docker compose up` unverified; venv+Makefile is the verified path (D-002).
- NSE historical price API 503; BSE unreachable; yfinance ToS-restricted. Documented in
  `research/REAL_DATA_SOURCES.md`.
- **PDFs are not parsed.** `attchmntText` is a one-line summary (median 154 chars), not the
  filing body. This is the biggest data limitation in the current evaluation.
- Live NSE data is not cleared for redistribution (B-002).

## OPEN QUESTIONS

- **Q3 (the central one): is D > C?** The evaluation is running. Unanswered.
- Is Laya's miscalibration in the mid-confidence band fixable by a temperature refit on a
  Divya-specific dev set? Probably, and it is untested.
- Does the loop *help* on the ambiguous stratum specifically? The stratified split will show.
- Would PDF extraction change any conclusion? Unknown and plausibly yes.

## NEXT HIGHEST-VALUE ACTION

Read the completed A/B/C/D result and report it, whatever it says — including the specific case
where the recurrent loop costs latency and tokens and does not return quality.
