# NEXT

Exactly one item is `IN_PROGRESS`. Everything else is a queue, not a promise.

---

## `[~]` IN_PROGRESS — N1: First real Laya call on this CPU

**Why this is first.** Every latency budget, every cost estimate, and the feasibility of the
entire Level-1/Level-2 design depends on one unmeasured fact: what does Laya actually cost and
actually answer, on *this* machine, on *finance-shaped* text? The PDR's numbers are from a
T4 and a support-triage benchmark. Until this is measured, any architecture choice is a guess.

**Done when:**
- Laya is installed and a checkpoint is resident.
- `research/scripts/bench_laya.py` has run and written a result artifact.
- The result records: cold-load seconds, warm p50/p95 per `predict`, which checkpoint routed,
  and raw answers for a finance-shaped question set.
- The numbers are in `EVALS.md` and `RESEARCH.md`, tagged `[RESULT]`, with hardware stated.
- A5 (latency) and A6 (finance quality) move from `[HYPOTHESIS]` to measured-or-rejected.

**Explicit non-goal for this step:** do not build the runtime, the protocol, or the terminal yet.
Measuring first is the entire point.

---

## Queue (ordered; each is small enough to verify before moving on)

- `[ ]` **N2** First System-2 structured-output measurement. Does a 4B local model emit valid,
  schema-conforming S2 turns? Decides B-003. If not, add constrained decoding before any
  runtime work.
- `[ ]` **N3** Write `docs/architecture/UNIFIED_MODEL.md` at implementation level: roles, shared
  state schema, request/response JSON schemas, termination, budgets, observability. Written
  *after* N1/N2 so the latency and reliability budgets are real numbers, not guesses.
- `[ ]` **N4** `models/questions.yaml` v0 + JSON schemas, import-tested. Option sets are
  versioned artifacts because `choice` options *are* the decision problem (see RESEARCH A2).
- `[ ]` **N5** Level-1 baseline (`C` arm) end to end. Measure it before Level 2 exists, so the
  comparison is real and not retrofitted.
- `[ ]` **N6** Level-2 recurrent loop + shared state + JSONL traces + termination + abstention.
  Replay test proving a human can reconstruct the full trajectory.
- `[ ]` **N7** First real domain. Scope to earnings / corporate actions only.
- `[ ]` **N8** A/B/C/D evaluation harness. This is the deliverable that answers the thesis.
- `[ ]` **N9** Terminal UI.
- `[ ]` **N10** Red-team suite. Safe degradation is an acceptance criterion, not a nice-to-have.
- `[ ]` **N11** Release: clean-clone setup verified, README matches implementation.

## Standing rules for this queue

- Do not skip ahead to build something whose feasibility depends on an unmeasured value above it.
- A negative result on N1 or N8 is a valid, valuable outcome. **Record it; do not hide it and do
  not re-run until it goes our way.** Distinguishing H1 from H2 is the point of the exercise.
- Every item ends with a command whose output was actually observed.
