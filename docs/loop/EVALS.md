# EVALS

The evaluation register. **No number appears in this repo unless it appears here first, with
its conditions attached.**

## Reporting contract

Every reported number must carry, without exception:

| Field | Why |
|---|---|
| hardware | a latency number is meaningless without it |
| model id + version | models change under you |
| dataset + n | 50 hand-picked examples is not evidence |
| metric definition | precision over what, recall over what |
| baseline | a number with no baseline is not a result |
| method | how it was measured, and what was excluded |

## Required comparison

The thesis is **D > C**. Everything else is context. All four arms must be run on the *same*
examples, in the *same* session, with the *same* System-2 model, so the comparison is paired.

| Arm | Configuration | Role |
|---|---|---|
| **A** | Laya alone, no System-2 | Is the fast path sufficient? |
| **B** | System-2 alone, no Laya | Is the loop necessary, or is S2 enough? |
| **C** | System-2 → Laya, single shot | **Control condition.** The thing to beat. |
| **D** | System-2 ↔ shared state ↔ Laya, recurrent | The claim under test. |

## Metrics

**Quality** — task accuracy; macro precision / recall / F1 over event types; per-class breakdown.
A system that wins on average by memorising the majority class has not won.

**Calibration** — this is the metric that matters most for a terminal that must be able to
abstain. A decision engine that is confidently wrong is worse than one that abstains.

- Brier score
- Expected calibration error (ECE), 15 bins
- Reliability of the `noul` abstention signal specifically

**Cost** — wall-clock latency (p50/p95); Laya call count per event; *unnecessary* Laya calls
(decisions that did not change the outcome); System-2 token counts; number of loop iterations
before termination.

**Loop pathology** — premature termination (abstained while evidence was sufficient);
over-analysis (looped past the point of usefulness); duplicate identical decisions; non-termination
(must be zero by construction, and the guard must be tested).

**Robustness** — accuracy under missing evidence, contradictory evidence, noisy headlines,
duplicate events, and prompt-injection payloads embedded in event text.

## Datasets

Two, and they are not interchangeable.

### Primary: real NSE corporate announcements

`evals/datasets/nse_announcements_v1.jsonl` — **1,042 real announcements**, 664 symbols,
61 industries, 3 strata. Built by `evals/build_real_dataset.py` from the live NSE API.
Labels come from **NSE's own `desc` field**, mapped through the explicit 104-class table in
`src/divya/data/nse_taxonomy.py`.

- **Real:** the filing text, company, industry, timestamp, and PDF link are fetched from NSE.
  `is_synthetic_text: false` on every row.
- **Not ground truth:** agreement with NSE is agreement with the exchange's *filing*
  classification. It is a real, published, human-curated label, which is much better than our
  own annotation — and it is still a taxonomy, not the truth about the business.
- **Only `event_type` is scored.** NSE publishes no label for `is_material`, `materiality` or
  `direction`, and inventing one would reintroduce the synthetic-data problem that made the
  first results misleading. The harness reports the others as `"not evaluated"`.
- **The base rate is the finding.** 77% of a real feed is process, not corporate events. The
  dataset is filtered to event-bearing announcements, and the unfiltered base rate is recorded
  in `evals/datasets/nse_announcements_v1.report.json` so the filter is visible.
- **Known gap:** `attchmntText` is a one-line summary (median 154 chars), not the filing body.
  PDFs are not parsed. See BLOCKERS B-004.

### Secondary: synthetic, stratified, deterministic

`evals/datasets/event_triage_v1.jsonl` — 210 items from `evals/make_dataset.py`, seed 20260928.
Every row is stamped `is_synthetic_text: true`. Strata: `clear` 90, `ambiguous` 45, `noisy` 45,
`adversarial` 30 (prompt-injection payloads that a live feed will never contain). All 10
`event_type` classes covered, minimum class n=5, round-robin template assignment so no class is
starved.

**It exists to expose failure modes and control for sample count. It is not evidence of
quality.** Measured: Laya scores **0.733** on its `clear` stratum against **0.500** on real
announcements. Both numbers are always reported together.

### Requirements the datasets are built to satisfy

- Must expose false positives, false negatives, genuine ambiguity, and contradictory evidence.
  A set of clean examples only measures the easy case and will make D and C look identical.
- Must span multiple sectors and multiple event types.
- Must include a deliberate **adversarial** slice (injection strings, malformed dates, duplicate
  events) separate from the accuracy slice, reported separately.
- Every item carries provenance: source document, retrieval timestamp, and label rationale.
- Hand-labelled items must record **who labelled them and how confident that label is**. A label
  with no annotator confidence is a hidden ground-truth error rate.
- If a row is synthetic, the row itself says so, and results are reported split real/synthetic.

## Split discipline

- Fit/tune on the **dev** split only. Report on **test**, touched once per configuration.
- If Laya is fine-tuned (L3), the fine-tune data and the eval set must be disjoint by construction,
  and the split must be by *company*, not by *event*, or the same filing leaks across splits.
- Report n on every table. A 12-item table and a 400-item table are not comparable.

## Measured so far

Every number below was produced by a command in this repository. Environment: WSL2, 16 vCPU
Ryzen 7 4800H, 7.5 GiB RAM, **no GPU**, torch 2.14.0+cpu, laya 0.3.21, `qwen2.5-coder:3b`,
Python 3.12.3, 2026-09-28.

| # | Measurement | n | Result | Source |
|---|---|---|---|---|
| 1 | Laya latency, 4-question call | 4 fixtures × 3 | 4552 ms p50 (1138 ms/question) | `research/results/bench_laya.json` |
| 2 | Laya peak RSS | — | 2746 MB | same |
| 3 | Checkpoint load (excl. download) | — | 6.6 s | `research/results/bench_resources.json` |
| 4 | Batching speedup | 12 states | **1.10×** at batch 4 | same |
| 5 | System-2 warm latency, 3B | 3 calls | 0.56–0.91 s | D-009 |
| 6 | System-2 warm latency, 4B | 3 calls | 42–64 s (1.3–2.2 s of it generation) | D-009 |
| 7 | Laya `event_type`, synthetic clear | 30 | acc 0.733, macro-F1 0.724, ECE 0.216, AURC 0.117 | `research/results/armA_v2_calibrated.json` |
| 8 | **Laya `event_type`, real NSE** | 24 | **acc 0.500, macro-F1 0.538, ECE 0.182, AURC 0.210** | `research/results/` |
| 9 | Calibration, mid band (0.60–0.67) | 5 | 0.200 accuracy at 0.627 stated confidence | same |
| 10 | Calibration, high band (0.93–1.00) | 7 | 1.000 accuracy at 0.995 stated confidence | same |
| 11 | Checkpoint `choice:11+` temperature | — | **0.1006 — invalid, confidence uncalibrated** | `rl_agent_config.json` |
| 12 | **A/B/C/D on real NSE** | 120 | **A 0.558 · B 0.000 · C 0.558 · D 0.508**; D abstains 75.8% | `evals/results/real_eval.json` |
| 13 | D vs C, p95 latency | 120 | 40.4 s vs 19.0 s; arm A 4.7 s | same |
| 14 | Per-class F1 (arm A) | 120 | credit_rating 0.94, leadership_change 0.88, m_and_a 0.67, other 0.43, **capital_action 0.00, regulatory_action 0.00** | same |

**Interpretation constraints, binding on every report:**

- Row 8 is agreement with NSE's taxonomy, not correctness about the market.
- Rows 7 and 8 must never appear without each other.
- Row 11 means any confidence from a >10-option `choice` question is unusable. The protocol
  loader now refuses to load one.
- No row in this table supports the claim that the recurrent loop is better. That claim is
  either supported by row 12 or it is not supported at all.
