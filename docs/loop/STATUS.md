# STATUS

_Last updated: 2026-09-28, iteration 3._

## CURRENT OBJECTIVE

The thesis is measured and **rejected on this data**. The remaining work is the highest-value
experiment the result points at: the `other` option is acting as an attractor for uncertainty,
and two classes score F1 = 0.00 because of it.

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
- 84 tests, ruff clean, mypy clean.
- Architecture spec (`docs/architecture/UNIFIED_MODEL.md`), README, Makefile, Dockerfile and
  compose written.

## `[RESULT]` E-009 — THE ANSWER. The recurrent loop is worse, and the reasoning layer adds nothing

120 real NSE announcements. All four arms, paired, same process, same loaded checkpoint.
`qwen2.5-coder:3b`, min_confidence 0.55, max_turns 4. Artifact: `evals/results/real_eval.json`.

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | S1 calls | S2 calls | Prompt tok | Abstain |
|---|---|---|---|---|---|---|---|---|---|
| **A** S1 alone | **0.558** | 0.436 | 0.096 | **0.240** | **4.7 s** | 1.00 | 0.00 | 0 | 0.0% |
| **B** S2 alone † | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 0.00 | 2.00 | 2214 | 0.0% |
| **C** S2→S1 single shot | **0.558** | 0.436 | 0.096 | **0.240** | 19.0 s | 1.00 | 1.00 | 1079 | 0.0% |
| **D** S2↔state↔S1 recurrent | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | 2.57 | 3.33 | 4941 | **75.8%** |

Per stratum: `clear` (n=50) A 0.500 / C 0.500 / **D 0.420** · `noisy` (n=64) A 0.609 / C 0.609 /
**D 0.578** · `ambiguous` (n=6) all 0.500.

**Two independent negative results:**

1. **A and C are identical to the decimal** — accuracy, macro-F1, ECE and AURC all equal. The
   reasoning layer contributes *zero* to the decision while costing 4.0× p95 latency and 1079
   prompt tokens per event.
2. **D is worse than C** — 0.508 vs 0.558, worse on every stratum except `ambiguous` (tied), at
   8.5× arm A's latency and 2.57 System-1 calls per event.

   **Why it is worse (corrected after independent review).** An earlier draft of this file said
   arm D "scores the abstained events wrong". That was false and the artifact disproves it:
   accuracy is computed on the immutable raw System-1 answer, which is present even when the
   loop abstained, and 38 of the 91 abstained items were scored **correct**. (If abstained items
   were all scored wrong, accuracy could not exceed 29/120 = 0.242; the measured 0.508 is well
   above that ceiling.)

   The actual mechanism is sharper than the abstention story: paired per item, **A is right and
   D is wrong on 6 items; D is right and A is wrong on 0.** The recurrent loop never fixed a
   single error the single-shot path made, and it converted 6 correct answers into wrong ones by
   re-asking System-1 and receiving different, worse answers. That is H3 in its most direct form.

**Hypothesis verdicts:** H1 (loop helps) **REJECTED** · H2 (loop ≈ single-shot) **REJECTED** ·
H3 (loop hurts) **SUPPORTED** · H4 (calibration win) **NOT SUPPORTED** — D's ECE is marginally
better (0.080 vs 0.096) but its AURC is worse (0.260 vs 0.240), and the ECE gain is an artifact
of abstaining more rather than of better-ordered confidence. H3 is also what the external
literature predicts (ATLAS 2510.15949).

**The failure is not uniform, and that is the actionable part.** Per class: `credit_rating`
F1 0.94, `leadership_change` F1 0.88, `m_and_a` 0.67, `other` 0.43, `capital_action` **0.00**
(n=13), `regulatory_action` **0.00** (n=17). The confusion matrix shows `other` acting as an
attractor for uncertainty: in **arm A** `capital_action` goes to `other`/`fundraise` 13/13 and
`regulatory_action` to `other`/`capital_action` 16/17.

`other` precision is **0.294 in arms A and C** (TP 15, FP 36) and **0.342 in arm D** (TP 14,
FP 27). Both are bad; they are different numbers and are not interchangeable.

**DECISION (D-012, D-013):** the default runtime is **arm A, System-1 alone**, in a named
`--mode system1`. The recurrent loop is retained, tested and traced as the control that made
this result possible, but it is not the product default. **Levels 3 and 4 are declined** — there
is no measured value for a specialised System-2 to optimise when the untrained one contributes
nothing and the loop it would drive is worse.

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

**83 passing.** `ruff check` clean, `mypy src/divya` clean. Coverage includes: every Laya
contract rule, the calibration-bucket guard, hand-computed metric values, termination totality
across six distinct paths, degradation for missing/broken/failing System-1 and System-2, trace
reconstructability, frozen-record immutability, and the freshness/provenance invariants.

## BENCHMARKS

All in `research/results/` and `docs/loop/EVALS.md`, each with hardware, model version, n, and
baseline. The A/B/C/D comparison is complete; see the table above and `evals/results/real_eval.json`.

## KNOWN FAILURES

- `FetchURL` tool fails on every host here; `curl` via Bash is the working path.
- Docker absent → `docker compose up` unverified; venv+Makefile is the verified path (D-002).
- NSE historical price API 503; BSE unreachable; yfinance ToS-restricted. Documented in
  `research/REAL_DATA_SOURCES.md`.
- **PDFs are not parsed.** `attchmntText` is a one-line summary (median 154 chars), not the
  filing body. This is the biggest data limitation in the current evaluation.
- Live NSE data is not cleared for redistribution (B-002).

## OPEN QUESTIONS

- ~~Q3 (the central one): is D > C?~~ **Answered: no.** D 0.508 vs C 0.558, and A == C exactly.
- Is Laya's miscalibration in the mid-confidence band fixable by a temperature refit on a
  Divya-specific dev set? Probably, and it is untested.
- ~~Does the loop help on the ambiguous stratum?~~ **Answered: no, and weakly.** A 0.500 / C 0.500 / D 0.500 — all three tied. n=6 is too small to distinguish anything, so this is a null result, not evidence of equivalence.
- Would PDF extraction change any conclusion? Unknown and plausibly yes.

## NEXT HIGHEST-VALUE ACTION

**Remove `other` from the `event_type` option set and re-run E-009.** The confusion matrix shows
`other` acting as an attractor for uncertainty: `capital_action` (n=13) and `regulatory_action`
(n=17) both score F1 = 0.00 because their filings are absorbed by `other` (precision 0.29), and
that option has precision 0.294 in arm A (TP 15, FP 36). This is a protocol defect rather than
a model defect, it is the single clearest experiment the evaluation produced, and it could
change the headline numbers substantially.
