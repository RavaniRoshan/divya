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

To be built. Requirements, not numbers:

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

## Current status

**No evaluation has been run.** No number in this repository is a measurement yet. Any number
appearing in a commit message, README, or UI before this file is populated is, by definition,
fabricated.
