# NEXT

Exactly one item is `IN_PROGRESS`. Everything else is a queue, not a promise.

---

## `[~]` IN_PROGRESS — E-009: read the completed A/B/C/D result

**Why this is the only thing that matters right now.** Everything else in the project is
either infrastructure for this measurement or already done. The thesis — that a recurrent
System-2 ↔ System-1 loop beats a single-shot System-2 → System-1 tool call — is unresolved, and
the run on 120 real NSE announcements is in flight.

**Done when:**
- `evals/results/real_eval.json` exists and every arm is populated.
- H1/H2/H3/H4 each get an explicit verdict, including "the data does not distinguish them".
- The result is written into `docs/loop/STATUS.md`, `docs/research/UNIFICATION_EXPERIMENTS.md`
  (E-009), and the final report — **whatever it says**.
- If D does not beat C, the product ships at Level 1 and Level 3/4 stay unbuilt, with that
  stated as the outcome rather than as a failure to hide.

**Explicit anti-goal:** do not re-run with a different seed, a different subset, or a different
model until it goes our way. One pre-registered run, reported as it came out.

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
