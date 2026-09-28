# AGENTS.md — Divya

Operational contract for any human or agent working in this repository.

## What this is

Divya is an India-first, self-hostable market-intelligence terminal for Indian equities.
Its core claim under test: a **System-2 reasoning model** and **Laya** (an Apache-2.0,
non-autoregressive System-1 typed-decision engine) operating over a **shared-state recurrent
loop** produce better decisions than either alone, or than a single-shot `S2 -> S1` tool call.

That claim is a **hypothesis under test**, not an established fact. Do not write code, docs,
commit messages, or UI copy that asserts it as true.

## Non-negotiable rules

1. **No fabricated claims.** Never write "state of the art", "production ready", "calibrated",
   "near zero cost", "real time", "faster", "better" without a measured number and a pointer to
   the artifact that produced it. Every performance number reported anywhere must carry:
   hardware, model id + version, dataset + n, metric, baseline, method.
2. **Never fabricate market data or citations.** Simulated data is labelled `SIMULATED` in the
   data itself, not just in the docs. A price view with no as-of timestamp is a bug.
3. **No hypothesis-as-fact.** Use the tags in `docs/loop/RESEARCH.md`: `[FACT]`, `[HYPOTHESIS]`,
   `[EXPERIMENT]`, `[RESULT]`, `[DECISION]`. Repetition does not promote a hypothesis to a fact.
4. **Raw System-1 output is immutable.** The System-2 layer may interpret, aggregate, compare,
   or abstain. It must never silently overwrite a raw Laya answer. Raw + interpreted are both
   stored and both are inspectable.
5. **Laya never generates prose.** It returns typed decisions only.
6. **Fail safe, fail visible.** Every external call (Laya, System-2, data source) has a
   defined degradation path and an observable signal. Degrading is allowed; degrading
   *silently* is not.
7. **Tests are evidence.** Never weaken, skip, or delete a test to make a build green. Never
   hard-code an output to pass a benchmark. A mock must never become the production path.
8. **No secrets in the repo.** No API keys, no tokens, no `.env` committed.

## Loop protocol

Work as: OBSERVE → UNDERSTAND → HYPOTHESIZE → PLAN → IMPLEMENT → RUN → VERIFY → CRITIQUE →
INTEGRATE → RECORD → select next highest-value action.

- After every substantial iteration, update `docs/loop/STATUS.md` using the template there.
  Observable facts only. "Made good progress" is not a status.
- Every architecture-changing decision gets an entry in `docs/loop/DECISIONS.md`.
- Blockers that need a human go in `docs/loop/BLOCKERS.md` with an ID, and are surfaced
  in the final report — never silently worked around.
- Before any context transition, persist state to `docs/loop/*`. The repository is the
  memory; conversation history is not.

## Layout

```
src/divya/protocol/   versioned decision protocol: schemas, questions.yaml loader
src/divya/system1/    Laya adapter (the only code allowed to import laya)
src/divya/system2/    System-2 provider abstraction (ollama / openai-compatible / heuristic)
src/divya/runtime/    shared state, recurrent loop, tracing, termination, abstention
src/divya/data/       source adapters, normalization, provenance, freshness, store
src/divya/eval/       A/B/C/D harness, metrics (accuracy, Brier, ECE), report builder
src/divya/terminal/   terminal UI
models/questions.yaml the decision protocol definition — versioned, migrated
docs/architecture/    UNIFIED_MODEL.md — spec at implementation level
docs/loop/            project state (the external memory)
docs/research/        experiment records
evals/                evaluation datasets + generated reports
```

## Build / test

```bash
uv sync                       # or: python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q           # tests
.venv/bin/ruff check .        # lint
.venv/bin/mypy src            # types
.venv/bin/divya --help        # CLI
```

Docker is not available in this environment; the reproducible path is the venv + Makefile
route. See README for the current verified setup command.

## Before you call anything done

Run the tests, run the eval, and read the actual output. "It compiles" is not a result.
