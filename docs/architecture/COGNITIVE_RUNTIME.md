# COGNITIVE_RUNTIME.md — the recurrent System-1/System-2 loop, at implementation level

_2026-09-28. Companion to `UNIFIED_MODEL.md` (the design) and `THESIS.md` (what we believe and
what would disprove it). This document is about the machinery, the state, and the failure
modes._

---

## 1. The loop, concretely

```
        user intent
             │
             ▼
    ┌─────────────────────┐
    │      System-2       │  understands intent, decomposes, decides what is
    │  (Ollama 3B / rule) │  needed, interprets results, judges sufficiency
    └──────────┬──────────┘
               │ System2Turn: call_system1(decisions=[...]) | finish | abstain
               ▼
    ┌─────────────────────┐
    │    SharedState      │  observations, evidence, raw System-1 output,
    │   (pydantic)        │  hypotheses, contradictions, disagreements,
    └──────────┬──────────┘  confidence, termination, append-only trace
               │ System1Record (frozen: request + raw payload + parsed answers)
               ▼
    ┌─────────────────────┐
    │      System-1       │  choice | score | noul, one forward pass,
    │   (Laya 0.3.21)     │  calibrated probabilities, no prose, ever
    └──────────┬──────────┘
               │ raw payload, unaltered
               ▼
        back to SharedState → System-2 again, or terminate
```

Three turn kinds and no others: `call_system1`, `finish`, `abstain`. There is no free-text
channel out of the reasoning model, and `rationale` is written to the trace and never read back.

---

## 2. The state, and why it has two digests

`SharedState` (`src/divya/runtime/state.py`) is the only channel between the two systems.

| Group | Fields |
|---|---|
| Identity | `task_id`, `protocol_version`, `domain`, `objective`, `created_at` |
| World | `observations[]`, `evidence_refs[]` |
| Actions | `turn_index`, `questions_asked[]`, `requested_decisions[]`, `system1_records[]`, `system2_records[]` |
| Beliefs | `hypotheses[]`, `contradictions[]`, `disagreements[]`, `unresolved_questions[]` |
| Outcome | `confidence`, `uncertainty`, `conclusion`, `termination`, `termination_reason` |
| Audit | `trace[]`, `config`, `errors[]` |

### `content_hash` vs `dedup_key`

An `Observation` carries **two** digests, because provenance and deduplication want opposite
things and one hash cannot honestly be both:

- **`content_hash`** — SHA-256 over the **exact** bytes received, encoded with
  `surrogatepass`. This is the provenance chain: a trace must be able to prove what was actually
  decided on. It is never normalised.
- **`dedup_key`** — the same hash over whitespace- and case-normalised text. A feed that
  re-emits one filing with different line wrapping is still one filing, and an exact hash cannot
  see that.

Before the split, one hash had to be both. Normalising it broke the red-team's provenance
assertion; keeping it exact meant eight copies of a 370 kB document reached System-1 in full.
Two fields, two purposes, and the red team asserts both properties.

### Freshness is computed, never stored

A row written a week ago is stale now, and no column can change that. `is_fresh` is a property:
every observation must have a readable, non-future age inside the window. The red team found
three separate bugs in the previous version, all of which failed *toward* "fresh":

- an unparseable timestamp returned age `0.0`, i.e. "brand new";
- a future timestamp produced a negative age, which the check compared only against the ceiling;
- an empty state could be reported as fresh.

`Observation.age_seconds()` now returns `float | None`, and every caller was updated. The
frontend has a mirror of the same rule in `isStale()`, which also fails toward caution: anything
that is not an explicit recent timestamp is treated as not-fresh.

---

## 3. Immutability, and what disagreement costs

`System1Record` is a frozen pydantic model holding three separate things: the **request** sent,
the **raw payload** returned, and the **parsed answers**. System-2 may interpret, compare,
request another decision, or abstain. It may not modify the payload — and cannot, structurally.

Where System-2 disagrees, the disagreement is a **separate object** (`Disagreement`), so it is
countable. An architecture whose value depends on the reasoner's judgement has to make that
judgement inspectable, or the evaluation is measuring an unfalsifiable thing.

In the measured run, arm D recorded **0 disagreements** while being wrong on 6 events arm A got
right. It did not disagree; it re-asked System-1 and got a different, worse answer. That is a
worse failure than disagreement, and it is invisible without the raw payload being kept.

---

## 4. Termination is total, and computable

Exactly one `TerminationStatus` on every path: `finished`, `abstained`, `max_turns`, `error`.
`tests/test_runtime.py::test_every_run_sets_exactly_one_termination` drives six distinct paths
and asserts each lands on the right named status.

The guards, and what each one actually prevents:

| Guard | Prevents |
|---|---|
| `max_turns` | an unbounded loop |
| already-answered decisions are ineligible | re-asking to learn something known |
| identical request guard | a reasoning model stuck in a cycle |
| consecutive System-1 failures ≥ 2 | paying repeatedly for a broken engine |
| consecutive System-2 failures ≥ 2 | one flaky provider consuming the whole run |
| document length cap | a 3.5 MB document becoming a self-inflicted DoS |

`error` and `max_turns` are distinguished on purpose. An earlier version reported `max_turns`
when System-1 was actually broken, which tells an operator to raise a budget when the real fix
is to restart the engine. The independent review caught that, and the no-repeat guard now
attributes the stop to the cause.

`system2_timeout_s` is the real bound. It was not: a hardcoded `+ 5` meant a configured 0.05 s
waited 5.07 s.

---

## 5. Untrusted content

Document text is attacker-influenced. **A prompt injection succeeded against the real engine**
before this layer existed: 87 characters appended to a 220-character dividend filing flipped
`event_type` from `earnings_result` (0.973) to `other` (0.652).

`src/divya/protocol/sanitize.py` runs at the System-1 boundary — *not* at ingestion, so the
stored document stays exactly what the source published. It:

1. removes zero-width and bidi characters;
2. strips control markup (`</system>`, `<|im_start|>`, `[INST]`, ```` ```system ````);
3. defangs role-shaped JSON **keys**;
4. **redacts instruction-like text**, which is the part that actually works — defanging the
   JSON was not sufficient, because a 421M encoder follows an instruction whether or not it is
   well-formed JSON;
5. caps document length.

Post-fix, the red team passes **8/8 injection cases against the real Laya engine**.

This is mitigation, not a fix, and the module says so. A defence is only as good as the test
that tries to break it, which is why `python -m divya.eval.redteam` ships and is runnable.
B-006 records it as an accepted open risk.

---

## 6. Contradiction detection

`Contradiction` and `add_contradiction` existed from the first commit and **nothing called
them**. Two filings that could not both be true were concatenated into one blob and handed to
System-1 unmarked.

Detection is now wired into the loop and is deliberately **topic-scoped**: dividend,
acquisition, auditor, buyback, fundraise — each with language asserting it went one way and
language asserting the opposite. A flat positive/negative keyword split was tried first and
missed every real case, because filings say "declined to declare any dividend", not "no dividend".

Narrowness is the point. A company declaring a dividend in April and reporting results in July
is not a contradiction, and a detector that says it is gets switched off.

---

## 7. Sanity of the measurements themselves

Reported numbers are recomputed from raw artifacts, not from the harness's summary:

- `src/divya/eval/significance.py` re-derives accuracy from `per_item` plus the dataset labels
  and runs McNemar's exact test plus a seeded paired bootstrap resampling **events** (one event
  yields several decisions; resampling within an event understates variance).
- `docs/loop/REVIEW.md` recomputed every headline figure independently and found the harness
  itself was reporting success on failed runs (`terminated_ok` counted `error` as OK). Fixed, and
  regression-tested.

Two arm-level results needed correcting after review and are worth repeating because they are
the kind of error that survives into a paper:

- "arm D scores the abstained events wrong" was **false** — accuracy is computed on the raw
  System-1 answer, which exists even when the loop abstained, and 38 of 91 abstained items were
  correct. The real mechanism is that the loop fixed 0 errors and broke 6.
- The `other`-precision figure mixed arms: 0.294 is arm A's, 27 is arm D's false-positive
  count. Now stated per arm.

---

## 8. What the runtime does *not* do

- **It does not claim to be a unified model.** Two connected models are two models. Nothing
  here fuses them.
- **It does not run the recurrent loop by default.** Measured default is one typed System-1
  pass (`--mode system1`), because the loop measured worse (see `THESIS.md` §2). The loop is
  fully implemented, tested and traced; it is selectable because it is the control that
  produced the result, not because it is recommended.
- **It does not expose chain-of-thought.** `rationale` exists for a human reading a trace and
  is never fed back into the pipeline.
