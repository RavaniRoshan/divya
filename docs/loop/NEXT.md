# NEXT

Exactly one item is `IN_PROGRESS`. Everything else is a queue, not a promise.

---

## `[x]` DONE — E-009: the A/B/C/D result, read and acted on

**Result: the thesis is rejected on this data.** A 0.558 · B 0.000 · C 0.558 · **D 0.508**.
A and C are identical to the decimal on all four quality and calibration metrics; D is worse
than C and abstains on 75.8% of events. H1 rejected, H2 rejected, H3 supported, H4 not supported.
Recorded in `STATUS.md`, `DECISIONS.md` D-012/D-013, `UNIFICATION_EXPERIMENTS.md` E-009, and the
README. The default runtime is now `system1_only`; Levels 3 and 4 are declined and recorded as
declined. No re-run with a different seed, subset, or model was attempted.

---

## `[~]` IN_PROGRESS — remove `other` from `event_type` and re-run E-009

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
