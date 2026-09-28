# UNIFIED_MODEL.md — the System-1 / System-2 architecture, at implementation level

Protocol version: `0.1.0` · Status: **specified and implemented; the thesis is under evaluation,
not established.** See `docs/loop/EVALS.md` for what has actually been measured.

---

## 0. What this document is and is not

It defines the architecture precisely enough to implement against and to audit. It does **not**
claim the architecture works. The central claim — that a recurrent System-2 ↔ System-1 loop
beats a single-shot System-2 → System-1 tool call — is a hypothesis under test, and the
research in `research/LITERATURE.md` found **no published measurement of that comparison in
either direction**, plus one adjacent result (ATLAS, arXiv 2510.15949) reporting that
reflection-based feedback fails to give systematic gains.

Where this document says "must", it means a test enforces it. Where it says "may", it means a
measured result does not yet exist.

---

## 1. The two roles

### System-1 — Laya (`src/divya/system1/laya_adapter.py`)

A non-autoregressive, Apache-2.0, 421M-parameter encoder that answers **typed questions in one
forward pass** and emits calibrated probabilities. It is the fast, narrow, reliable path.

| Property | Value | Source |
|---|---|---|
| Package / licence | `laya` 0.3.21, Apache-2.0 | PyPI JSON API, fetched 2026-09-28 |
| Question types | exactly `choice`, `score`, `noul` | `laya/common.py:17` `QTYPES` |
| Checkpoints | `english`, `multilingual`, `typed-decisions` | `laya/router.py:49` |
| Latency, this box | **1138 ms/question** (4552 ms for a 4-question call), 16 vCPU, CPU-only | `research/results/bench_laya.json` |
| Peak RSS | 2.75 GB | same |
| Cold load | 6.6 s (plus a one-time ~270 s checkpoint download) | `research/results/bench_resources.json` |

**Rules, enforced:**

1. **System-1 never generates prose.** It returns `choice` / `score` / `noul` and nothing else.
2. **System-1 never overwrites its own output.** `System1Record` is `frozen=True`; the raw
   payload, the parsed answers, and the exact request are three separate fields.
3. **System-1 is the only module permitted to `import laya`.** Enforced by convention and by
   keeping torch out of every other module's import path, so the protocol, runtime, eval, and
   CLI all run on a machine with no checkpoint.

### System-2 — the reasoning model (`src/divya/system2/`)

Plans, decomposes, maintains state, judges sufficiency, and abstains. It emits **one of three
typed turns and nothing else** (`System2Turn`):

- `call_system1(decisions=[...])` — ask for named decisions
- `finish(conclusion, confidence)`
- `abstain(conclusion, confidence)`

There is no fourth option and no free-text channel. This is what makes a trace readable: every
sentence a user sees came from a named field.

**Rules, enforced:**

1. **System-2 never states a System-1 answer as its own judgement.** If it disagrees, the
   disagreement is recorded in `Disagreement` and the raw System-1 value stays authoritative.
2. **`rationale` is written to the trace and never read back.** Treating a model's
   self-explanation as evidence is how confident nonsense enters a system.
3. **A provider is never hardcoded.** `System2Provider` has `ollama`, `openai_compatible`, and
   `heuristic` implementations. The `heuristic` provider stamps `is_model=False` on every
   record so its output can never be reported as model output.

---

## 2. The shared state

`SharedState` (`src/divya/runtime/state.py`) is the **only** channel between the two systems.
There is no hidden conversation object, no "notes" string, no implicit ordering.

| Group | Fields |
|---|---|
| Identity | `task_id`, `protocol_version`, `domain`, `objective`, `created_at` |
| World | `observations[]` (with `source_id`, `source_url`, `content_hash`, `retrieved_at`, `is_simulated`), `evidence_refs[]` |
| Actions | `turn_index`, `questions_asked[]`, `requested_decisions[]`, `system1_records[]`, `system2_records[]` |
| Beliefs | `hypotheses[]`, `contradictions[]`, `disagreements[]`, `unresolved_questions[]` |
| Outcome | `confidence`, `uncertainty`, `conclusion`, `termination`, `termination_reason` |
| Audit | `trace[]` (append-only transitions), `config`, `errors[]` |

Three properties are structural rather than aspirational:

- **Immutability of System-1 output.** `System1Record` is frozen; disagreement is a separate
  object, so overriding is not merely discouraged but unrepresentable.
- **Reconstructability.** Every mutation goes through `StateBuilder`, which appends an indexed
  `StateTransition`. Replaying the log rebuilds the state.
  `tests/test_runtime.py::test_every_record_leaves_a_transition` asserts that the number of
  `system1` transitions equals the number of records — an unaccounted-for record fails the build.
- **Termination is total.** Exactly one `TerminationStatus`, on every path. There is no code
  path that returns without setting one, so "it hung" is distinguishable from "it finished"
  after the fact.

### Provenance

Every `Observation` carries a `content_hash` over the exact text System-1 saw. It exists so a
stale decision cannot be silently re-attributed to edited text. `is_fresh` is a *computed*
property (no observation, or any older than 7 days → not fresh) rather than a field someone
remembers to update.

---

## 3. The decision protocol

`models/questions.yaml`, loaded by `src/divya/protocol/` into a pydantic schema.

A `choice` question's option set **is** the decision problem. Adding an option changes what is
being asked and makes answers recorded before and after non-comparable, which is why options
live in a versioned file rather than in prompt text.

**Two tiers**, which are the mechanism that makes arm C (single-shot) and arm D (recurrent)
different architectures rather than the same code with a different turn budget:

| Tier | Meaning | Arm C | Arm D |
|---|---|---|---|
| 1 | answerable from one pass | requested | requested |
| 2+ | only worth cost when tier-1 evidence is thin | never requested | requested selectively |

### Load-time validation

`load_protocol` refuses to load a file that violates any of these, each with a message naming
the offending question:

1. Only `choice` / `score` / `noul` exist. *(Laya's `QTYPES`, `common.py:17`)*
2. `choice` takes a `dict[label → description]`; `score` takes an ordered `list`.
   *(Laya's `render_options`, `common.py:106`)*
3. `labels` is rejected on non-`noul` questions. *(Laya raises this itself, `common.py:110`)*
4. `noul` labels map exactly `{"false","true"}` to distinct non-empty strings.
   *(Laya's `_resolve_noul_labels`, `common.py:92`)*
5. **No `choice` question may exceed 10 options.** This one is ours, and it is a measured
   constraint — see §6.

---

## 4. The loop

```
run(domain, objective, observations)
  │
  ├─► build SharedState, add observations
  │
  └─► for turn in 0..max_turns:
        │
        ├─ request = System2Request(available_decisions=eligible, state=model_view)
        ├─ turn = await system2.complete(request)            ← failure: retry, then heuristic, then ERROR
        ├─ record System2Record                               ← always, including failures
        │
        ├─ if FINISH   → set_outcome, terminate(FINISHED)
        ├─ if ABSTAIN  → set_outcome(conf=0), terminate(ABSTAINED)
        │
        └─ if CALL_SYSTEM1:
             ├─ drop names not in `eligible` (hallucination guard, logged to errors)
             ├─ empty result            → terminate(ABSTAINED)
             ├─ identical to a prior request:
             │     System-1 failing?    → terminate(ERROR)      ← the real cause
             │     otherwise            → terminate(MAX_TURNS)  ← the model is stuck
             ├─ group by owning spec, one System-1 call
             ├─ record System1Record     ← frozen; raw + parsed + request
             ├─ consecutive S1 failures ≥ 2 → terminate(ERROR)
             └─ advance turn
```

### Termination statuses

| Status | Meaning |
|---|---|
| `finished` | System-2 concluded |
| `abstained` | System-2 declined, or requested nothing it was allowed to ask for |
| `max_turns` | budget exhausted, or the model repeated an identical request |
| `error` | System-1 failed twice, or System-2 failed twice with no fallback available |

`error` vs `max_turns` is a distinction the tests forced: an early version reported
`max_turns` when System-1 was broken, which tells an operator to raise a budget when the real
fix is to restart the engine.

### Eligibility (`_eligible_decisions`)

A decision that has already been answered is **not eligible**. Re-asking costs a full forward
pass to learn something known, and repeated identical requests are the clearest signal of a
stuck model. With `allow_escalation=False` (arm C), only tier-1 is eligible.

### What the reasoning model sees

`_model_view` deliberately excludes raw System-1 payloads and the transition log. The model gets
answers, provenance, and what has already been asked — not the machinery. Sending the full
trace would blow the context budget and invite the model to reason about its own plumbing, which
is both expensive and a route for evaluation config to leak into decisions.
`tests/test_runtime.py::test_model_view_excludes_raw_payload_and_trace` asserts it.

---

## 5. Degradation

Every external dependency has a defined, **visible** failure mode.

| Failure | Behaviour | Signalled by |
|---|---|---|
| `laya` not installed | `NullSystem1`; loop continues on System-2 alone | `degraded[]` entry; every `System1Record.error` |
| System-1 raises / times out | record with `error`, retry once, then `terminate(ERROR)` | `degraded[]`, `termination=error` |
| System-1 returns a short answer | recorded as an error naming the missing decisions | `System1Record.error` |
| System-2 unreachable | retry, then fall back to `HeuristicProvider` | `degraded[]`; heuristic records carry `is_model=False` |
| System-2 unreachable, no fallback | `terminate(ERROR)` | `termination=error` |
| Model invents a decision name | dropped, logged to `state.errors` | `errors[]` |
| No System-1 confidence readable | reads as **0.0**, not 1.0 | — |

The last row matters more than it looks. Defaulting an unreadable confidence upward turns an
instrumentation gap into a false positive, which is the specific failure this system exists to
prevent.

---

## 6. The calibration-bucket constraint (measured, and it changed the protocol)

Laya fits a separate temperature per `(type, option-count)` bucket via `laya.common.temp_bucket`:

```
k ≤ 2 → "2"    k ≤ 5 → "3-5"    k ≤ 10 → "6-10"    else → "11+"
```

Read from the shipped checkpoint's `rl_agent_config.json` on 2026-09-28:

| Bucket | Temperature | Status |
|---|---|---|
| `choice:2` | 1.9064 | valid |
| `choice:3-5` | 1.7602 | valid |
| `choice:6-10` | 1.0 | valid |
| **`choice:11+`** | **0.1006** | **invalid — clamped to 0.5, confidence declared uncalibrated** |
| `noul:2` | 1.9834 | valid |
| `score:3-5` | 1.2514 | valid |

A temperature **below 1 sharpens** logits rather than softening them. At 0.1006 that is roughly
tenfold: a genuine 0.24 top probability is published as 0.99. Laya refuses to apply it, clamps
to 0.5, and warns that "confidence from the affected entries is uncalibrated" (`laya/agent.py:485`).

Divya's `event_type` had **11 options** and landed exactly in that bucket, so every calibration
number it produced was measuring a value the library had already disclaimed.

**Two changes followed.** `board_dividend` was merged into `capital_action`
(`event_triage` v1 → v2), moving the question to 10 options and the valid `choice:6-10` bucket.
And `load_protocol` now reproduces `temp_bucket` and **refuses to load** a protocol containing a
`choice` question in an uncalibrated bucket, so this cannot recur silently.
`tests/test_protocol.py::test_eleven_option_choice_is_rejected_as_uncalibrated` pins it.

**After the fix, calibration is still poor on real data** — see `docs/loop/STATUS.md`. Moving
out of the broken bucket removed a known defect; it did not make Laya calibrated on finance
text.

---

## 7. Observability

Every run writes a JSON document containing the full state, a metrics block, and a trace
digest. From it a human can reconstruct the entire trajectory: which decisions were requested,
in what order, what the engine returned verbatim, what the model did with it, and why it
stopped.

`LoopResult.metrics()` reports per run: turns, System-1 and System-2 call counts, failure
counts, latency split by system, prompt/completion tokens, repair count, max System-1
confidence, disagreement count, and the degradation list.

`divya show <task-id> --full` prints the raw document.

---

## 8. What is deliberately absent

- **Latency budgets as a design constraint.** Measured System-1 cost is 1138 ms/question on the
  target hardware. Any "interactive" claim would have to be measured, not assumed.
- **A "unified model" claim.** Two connected models are two models. Nothing in this architecture
  fuses them, and Level 4 (distillation, shared latents, joint optimisation) is not built because
  the evaluation has not yet shown that Level 2 is worth keeping.
- **Price prediction, sentiment scoring, or recommendations.** Out of scope. The product makes
  labelled, auditable decision state, not predictions.
- **Multi-tenancy or a hosted service.** This is a self-hosted research terminal.
