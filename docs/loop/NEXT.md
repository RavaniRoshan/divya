# NEXT

Exactly one item is `IN_PROGRESS`. Everything else is a queue, not a promise.

---

## `[x]` DONE — E-009: the A/B/C/D result, read and acted on

**Result: the thesis is rejected on this data.** A 0.558 · B 0.000 · C 0.558 · **D 0.508**.
A and C are identical to the decimal on all four quality and calibration metrics; D is worse
than C and abstains on 75.8% of events. H1 rejected, H2 rejected, H3 supported, H4 not supported.
Recorded in `STATUS.md`, `DECISIONS.md` D-012/D-013, `UNIFICATION_EXPERIMENTS.md` E-009, and the
README. The default runtime is now `--mode system1`; Levels 3 and 4 are declined and recorded as
declined. No re-run with a different seed, subset, or model was attempted.

---

## `[x]` DONE — remove `other`? NO: the significance test says the loop's failure is narrower than that

The `other`-attractor diagnosis is **confirmed and larger than first stated**: **three** classes
at zero accuracy (`capital_action`, `fundraise`, `regulatory_action`), with **36** errors landing
on `other` (not 27). But the attribution needed correcting too: the loop is not losing accuracy
*because* it abstains on those. Paired per item, **A is right and D is wrong on 6 items, D is
right and A is wrong on 0** — the loop never fixed an error and broke six correct ones, entirely
on items System-1 alone got right. So `other` is a System-1 protocol defect, not a loop
artefact, and it is the right next target.

## `[~]` IN_PROGRESS — re-run E-009 on full filing text

Every result so far was measured on one-line summaries. `evals/datasets/nse_announcements_filings_v1.jsonl`
carries the real filings (107/120 upgraded, 25.3x more text). Running the same arms on the same
labels with the real text is the experiment D-016 enabled.

**Why this is next.** The result is not a flat failure — it is a *localised* one, and the
localisation is diagnosable. Per class, arm A scores `credit_rating` F1 0.94 and
`leadership_change` F1 0.88, but `capital_action` (n=13) and `regulatory_action` (n=17) score
exactly **0.00**. The confusion matrix shows `other` acting as an attractor for uncertainty:
`capital_action` goes to `other`/`fundraise` 13 of 13, `regulatory_action` to
`other`/`capital_action` 16 of 17, and `other` itself has precision **0.294** in arm A (TP 15, FP 36) — it absorbs the
uncertainty from classes the head cannot resolve.

A catch-all option in a typed-decision head does not stay a catch-all; it becomes where
uncertainty goes. That is a protocol design defect, not a model defect, and it is fixable.

**Done when:** `event_type` drops `other` (protocol v3), unresolvable filings route to an
explicit `unresolved`/abstain path, and E-009 is re-run on the same 120 items with the same
pre-registered strata — reported whatever it shows, including if it does not help.

---

## Queue

- `[ ]` **PDF extraction.** `attchmntText` is a one-line summary (median 154 chars); the filing
  body is in the attached PDF. Unblocks the biggest data gap (B-004) and could change every
  conclusion, because a materiality judgement needs the figures a summary omits.
- `[ ]` **Temperature refit on a Divya dev set.** Laya's mid-confidence band is 20% accurate at
  63% stated confidence. A refit is the direct remedy and is the highest-value model work left.
- `[ ]` **ONNX measurement.** `laya[onnx]` is the one untested performance lever.
  `pip install 'laya[onnx]'` and re-run `bench_resources.py`.
- `[ ]` **Expert hand-labelling** for `is_material` / `materiality` / `direction` on a real
  sample, with recorded annotator confidence. Unblocks two of four decisions on real data (B-005).
- `[ ]` **Red-team suite as a named test module.** The degradation paths are implemented and
  individually tested; they are not yet collected into one adversarial run over a real corpus.
- `[ ]` **Clean-clone verification.** `git clone` to a fresh directory, `make setup && make check`,
  and record the actual output.
- `[ ]` **Level 3 (System-2 fine-tuning) and Level 4 (fusion).** Only if E-009 shows D > C.
  Otherwise these are explicitly declined, and declining them is the correct outcome.

## Standing rules for this queue

- A negative result is a valid, valuable outcome. **Record it; do not hide it and do not re-run
  until it goes our way.**
- Distinguishing H1 from H2 from H3 is the point. Reporting "the loop is fine" without naming
  which hypothesis survived is not a result.
- Every item ends with a command whose output was actually observed.
- Anything that needs a human — a licence, a secret, a destructive action — goes to
  `docs/loop/BLOCKERS.md` and into the final report. Never worked around silently.

---

## Gaps the independent review named that are not yet queued

Recorded so they are not lost, in severity order. `docs/loop/REVIEW.md` is the full review.

- **No test coverage for `eval/harness.py`, `data/nse_taxonomy.py`, `data/nse.py`, `cli.py`,
  `terminal/view.py`.** The module that produced the headline number and the module that
  produced every label have zero tests. The single largest gap, and the one that would have
  caught D1.
- **No significance test for the paired A-vs-D claim.** "H3 SUPPORTED" is currently an
  assertion over 6 net disagreements. A paired test (McNemar / exact binomial on the
  discordant pairs) is cheap and would either confirm it or show it is within noise on n=120.
  **Until that runs, the correct phrasing is "D measured worse; the gap is 6 items and has not
  been tested for significance."**
- **Arm C ran at `c_samples=1`,** so it is not yet a self-consistency arm — it is arm A plus a
  no-op reasoning call. That is consistent with the result (A == C exactly) but it means the
  "control for sample count" design in `EVALS.md` was specified and not exercised.
- **A dev/test split and a recorded seed are mandated in `EVALS.md` and not implemented.** The
  real dataset is a single unshuffled pool. For a comparison like this it did not change the
  result, but the discipline is stated and not enforced.
