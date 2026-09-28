# Divya

An India-first market-intelligence terminal that pairs a **System-2 reasoning model** with
**Laya** — an Apache-2.0, non-autoregressive System-1 engine that returns typed decisions with
probabilities — over a shared-state recurrent loop.

**The central claim is a hypothesis under test, not a finding.** No published work measures
whether a recurrent System-2 ↔ System-1 loop beats a single-shot System-2 → System-1 tool call.
The one adjacent result found (ATLAS, arXiv 2510.15949) reports that reflection-based feedback
*fails* to provide systematic gains. This repository is built to be able to return that negative
result, and to report it honestly. See [Status](#status) for what has actually been measured.

---

## What it does

One typed System-1 pass, no reasoning model, full provenance on screen — this is the default
because the measurement says the reasoning layer does not earn its cost (see Status below):

```
$ divya decide --text "Sun Pharma Limited has informed the Exchange that the Board has declared
an interim dividend of Rs 12.50 per equity share for the quarter. The record date has been fixed
as 14 August 2025." --trace
```

```
[system-1] event_triage@2  decisions=['direction','event_type','is_material','materiality']
           checkpoint=english  14831ms
  event_type       {"type": "choice", "choice": "earnings_result", "confidence": 0.4319, ...}
  is_material      {"type": "noul", "noul": 0.5114, "confidence": 0.5114, ...}
  materiality      {"type": "score", "score": 1.9278, ...}
  direction        {"type": "noul", "noul": 0.2437, "confidence": 0.7563, ...}

[conclusion] event type: earnings_result; material: P=0.51; materiality level: 2
[cost] s1 calls=1 s2 calls=0 turns=0 s1=14832ms s2=0ms
```

Note that last result: a *dividend* announcement classified `earnings_result` at 0.43
confidence. That is the `other`-attractor failure described under Status, caught by the
product's own default path, not by a test.

The full recurrent architecture is still there, fully traced, under `--mode loop`:

```
$ divya decide --text "..." --mode loop --trace
│ 0  ollama:qwen2.5-coder:3b   call_system1 ['event_type','is_material']     8905ms │
│ 1  ollama:qwen2.5-coder:3b   call_system1 ['evidence_sufficiency', …]      1343ms │
│ 2  ollama:qwen2.5-coder:3b   call_system1 ['numeric_disclosure_present']    1172ms │
│ 3  ollama:qwen2.5-coder:3b   finish                                       1453ms │
```

**It is not the default because it measured worse** — 0.508 vs 0.558 accuracy at 8.5× the
latency. It is kept because it is the control that produced that result.

---

## Quick start

Requires Python ≥ 3.10. Tested on Python 3.12.

```bash
git clone <this repo> && cd divya
make setup          # venv + pinned dependencies
make test           # 378 tests
make lint           # ruff + mypy
make doctor         # what actually works in YOUR environment
```

`make doctor` is the first thing to run. It reports, without guessing: whether Laya is
installed, whether the reasoning-model server is reachable and which models are present, which
data sources respond, and the recorded licence verdict for each.

### Run it

```bash
# 1. See the live NSE feed and how it maps to the decision protocol
divya fetch nse-announcements --days 7 --limit 300

# 2. Decide a single event. Default mode is one typed System-1 pass (see the results above).
divya decide --text "..." --trace

#    Or run the full recurrent architecture, which measured worse but is fully traced:
divya decide --text "..." --mode loop --trace
#    --file reads the WHOLE file as one document. Point it at a single record, not at a
#    dataset -- feeding the 1,042-record dataset takes ~53 s and produces nonsense.
divya decide --file data/one_announcement.txt

# 3. Inspect any past run in full
divya show <task-id> --full

# 4. Inspect the versioned decision protocol
divya protocol show
divya protocol diff --other path/to/older/questions.yaml
```

### Models

One System-1 checkpoint and one System-2 model. That is the whole requirement:

```bash
ollama pull qwen2.5-coder:3b     # System-2 (~1.9 GB); the first `divya decide --mode loop` pulls it
# Laya's `english` checkpoint (~248 MB) downloads automatically on first System-1 use.
```

A 4B model was measured and **deleted**, not kept: 42–64 s warm against this 0.56–0.91 s, with
only 1.3–2.2 s of that being generation (memory thrash — see DECISIONS D-009/D-014). If
`DIVYA_S2_MODEL` names something that is not pulled, `divya doctor` says so rather than letting
it fail mysteriously.

### Data defaults

The shipped default is **fixture data**, and every fixture record is stamped `is_simulated=True`
**in the data itself**, not just in the documentation. It cannot be laundered into looking live.

Live NSE endpoints work and `divya fetch` uses them, but they are exchange-proprietary and **no
reuse grant was located**. That is fine for running this yourself; it is **not** clearance to
redistribute a build with the data baked in. The per-source verdict lives in
`src/divya/data/sources.py` and is printed by `divya doctor`. See
[docs/loop/BLOCKERS.md](docs/loop/BLOCKERS.md) B-002.

---

## The terminal

```bash
divya index --days 2 --limit 500     # ingest live NSE announcements into a local store
divya terminal                       # launch the TUI
```

Event stream · detail · company list · a "why" evidence chain · decision state · freshness ·
model versions, all keyboard-driven:

```
j k  move          enter  decide the selected event       w  raw System-1 output
                   / interpreted (never confusable)
c  companies       d  decision pane     e  event stream
f  measurable only r  reload            ?  bindings      q  quit
```

The status bar always carries data age, whether System-1 is loaded, and which model is running.
There is no state in which it omits them. `w` swaps the decision pane between the engine's raw
output and the system's reading of it — the two are one keystroke apart because the whole claim
of this project is that they can be told apart.

Press `enter` on a real filing and it decides for real:

```
│ [system-1] event_triage@2  checkpoint=english  14831ms
│   event_type      {"type": "choice", "choice": "earnings_result", "confidence": 0.4319}
│   is_material     {"type": "noul", "noul": 0.5114}
│ [conclusion] event type: earnings_result; material: P=0.51; materiality level: 2
```

Note that result: a *dividend* announcement classified `earnings_result`. That is the
`other`-attractor failure, caught by the product's own default path rather than by a test.

### Full filing text

```bash
divya filings --db data/store/divya.db --limit 100
```

NSE's API returns a one-line summary — median **154 characters** across a month of feed. The
filing is in the attached PDF. Pulling it gives **25× more text** (107 of 120 evaluation items
upgraded, 17k → 431k characters), and a materiality judgement needs figures that summaries
routinely omit. Filings that are scanned images with no text layer are detected, reported, and
fall back rather than being decided on as empty documents.

---

## Red team

```bash
.venv/bin/python -m divya.eval.redteam --out evals/results/redteam.json
```

43 cases across 7 classes — prompt injection, malformed input, duplicates, stale data,
contradictory evidence, numeric traps, resource exhaustion. It runs against the real runtime and,
for the injection class, the real Laya engine. It exits non-zero on any failure.

**It found a real hole.** An 87-character fake system turn flipped `event_type` from
`earnings_result` (0.973) to `other` (0.652) against the real engine. There was no sanitisation
layer at all. It also found 14 more defects — contradictory evidence silently concatenated, a
future timestamp reading as *fresh*, duplicates multiplying what the engine read, a raising
System-1 escaping the loop, and a timeout that was not the bound.

All 15 are fixed and the suite passes 43/43.

**This is not a security audit and no claim is made that the system is secure.** Laya is a 421M
encoder with no instruction hierarchy; it follows strong associative patterns. Sanitising raises
the cost of the attacks we have seen. It does not raise a wall. See
[docs/loop/BLOCKERS.md](docs/loop/BLOCKERS.md) B-006.

---

## Architecture

Full specification: **[docs/architecture/UNIFIED_MODEL.md](docs/architecture/UNIFIED_MODEL.md)**.

```
                      NSE announcements / bhavcopy / fixtures
                                    │
                                    ▼
                          SharedState  (schema-validated,
                          append-only transitions, provenance)
                                    ▲
                    ┌───────────────┴───────────────┐
                    │                               │
             System-2 turn                  System-1 record
        call_system1 | finish | abstain     frozen: request + raw + parsed
                    │                               │
                    └──────────────► Laya ◄────────┘
                       decision names        choice | score | noul
```

Three rules the code enforces rather than merely documents:

1. **System-1 output is immutable.** `System1Record` is a frozen model holding the request, the
   raw payload, and the parsed answers separately. If the reasoning model disagrees, the
   disagreement is a separate object. Overriding is not discouraged — it is unrepresentable.
2. **Termination is total.** Every run ends in exactly one of `finished` / `abstained` /
   `max_turns` / `error`. "It hung" is distinguishable from "it finished" after the fact.
3. **Degradation is visible.** If Laya is missing or the model is unreachable, the run continues
   or fails *by name*, and the trace says so. A rule-based fallback stamps `is_model=False` so
   its output can never be reported as model output.

### The decision protocol is versioned code, not prompt text

`models/questions.yaml`. A `choice` question's option set *is* the decision problem, so options
live in a versioned, reviewable file. `load_protocol` enforces Laya's actual constraints (read
from its source, not its docs) and refuses to load a protocol that would produce uncalibrated
confidence. See [§6 of the architecture doc](docs/architecture/UNIFIED_MODEL.md#6-the-calibration-bucket-constraint-measured-and-it-changed-the-protocol).

---

## Status — what has actually been measured

All numbers: WSL2, 16 vCPU AMD Ryzen 7 4800H, 7.5 GiB RAM, **no GPU**, torch 2.14.0+cpu,
laya 0.3.21. Full method, n, and baseline in [docs/loop/EVALS.md](docs/loop/EVALS.md).

| Measurement | Result |
|---|---|
| Laya latency, CPU, 4-question call | **4552 ms p50** (1138 ms/question) — 2.4–5.9× slower than the PDR's 193–464 ms claim |
| Laya peak RSS | 2.75 GB |
| Laya `event_type` on 4 clean finance fixtures | 4/4 correct |
| Laya on **real NSE announcements** (n=24) | **accuracy 0.500**, macro-F1 0.538, ECE 0.182, AURC 0.210 |
| Calibration on the mid-confidence band (n=5) | 20% accuracy against 63% stated confidence |
| Calibration at 0.93–1.0 (n=7) | 100% accuracy — well calibrated |
| Batching lever | **1.10× at best** — torch already saturates all 16 threads |
| System-2 warm latency | `qwen2.5-coder:3b` **0.56–0.91 s**; `qwen3:4b` **42–64 s** (memory thrash) |
| **A/B/C/D on real NSE data** (n=120) | see below — **the thesis was rejected** |
| Significance, A vs D | McNemar **p = 0.0312**, paired bootstrap 95% CI **[−0.0917, −0.0167]** — excludes zero |
| Discordant pairs | **only-A-correct 6, only-D-correct 0** — the loop fixed nothing and broke six |
| Dead classes | **three at F1 = 0.00**: capital_action, fundraise, regulatory_action |
| `other` absorbs | **36** misclassifications (precision 0.294) |
| PDF filing extraction | **25.3×** more text; 107/120 items upgraded |
| Red team | **43/43** pass, 15 defects found and fixed |
| Tests | **378** passing, ruff and mypy clean |

### The headline result: the thesis is rejected on this data

120 real NSE announcements, four arms paired in one process against one loaded checkpoint.

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | Prompt tok | Abstain |
|---|---|---|---|---|---|---|---|
| **A** System-1 alone | **0.558** | 0.436 | 0.096 | **0.240** | **4.7 s** | 0 | 0.0% |
| **B** System-2 alone † | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 2214 | 0.0% |
| **C** System-2 → System-1 | **0.558** | 0.436 | 0.096 | **0.240** | 19.0 s | 1079 | 0.0% |
| **D** recurrent loop | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | 4941 | **75.8%** |

† **Arm B is a failed arm, not a result.** It produced no answer on any of 120 items (all
terminated `error` with an empty answer set). Its 0.000 is a missing answer scored wrong, not a
measurement of System-2's ability. The harness now fails loudly in this case.

1. **A and C are identical to the decimal** on all four metrics. The reasoning layer contributes
   *zero* while costing 4× the latency.
2. **D is worse than C** — 0.508 vs 0.558 — at 8.5× the latency and 2.57 System-1 calls per
   event. **Why:** paired per item, A is right and D is wrong on **6** items, and D is right and
   A is wrong on **0**. The recurrent loop never fixed a single error and broke 6 correct
   answers by re-asking System-1 and getting different, worse results. D abstains on 75.8% of
   events, but abstention is *not* the cause of the loss — accuracy is scored on the immutable
   raw System-1 answer, and 38 of the 91 abstained items were scored correct.

H1 (loop helps) **rejected** · H2 (loop ≈ single-shot) **rejected** · H3 (loop hurts)
**supported** · H4 (calibration win) **not supported**. H3 is also what the external literature
predicts — ATLAS (arXiv 2510.15949) reports reflection-based feedback fails to give systematic
gains.

**So the default runtime is System-1 alone (`divya decide --mode system1`, the default).** The recurrent loop is retained, tested and traced
under `--mode loop` because it is the control that produced this result, but it is not the
product default. Levels 3 and 4 are declined and recorded as declined. See
[DECISIONS D-012/D-013](docs/loop/DECISIONS.md) and
[E-009](docs/research/UNIFICATION_EXPERIMENTS.md).

**The next experiment the result points at.** The failure is not uniform: `credit_rating` scores
F1 0.94 and `leadership_change` 0.88, but `capital_action` (n=13) and `regulatory_action` (n=17)
score exactly **0.00**. The confusion matrix shows `other` acting as an attractor for uncertainty —
`capital_action` goes to `other`/`fundraise` 13 of 13, and `other` itself has precision 0.29
while absorbing 27 misclassifications. Removing the `other` option is the clearest experiment
available.

**Two negative results that changed the design:**

- The shipped checkpoint's `choice:11+` calibration temperature is `0.1006` — it sharpens logits
  ~10× and turns a 0.24 probability into a published 0.99. Our 11-option `event_type` question
  landed in that bucket. The protocol was changed to 10 options and the loader now refuses to
  load a protocol in an uncalibrated bucket.
- **Synthetic evaluation data was flattering us.** On the synthetic clean stratum Laya scored
  0.733; on real NSE announcements it scores 0.500. The synthetic set is kept (it is
  deterministic and carries prompt-injection cases a live feed never will) but its numbers are
  never quoted without the real ones beside them.

---

## What this is not

- **Not a "unified model".** Two connected models are two models. Nothing here fuses them.
  Level-3 training and Level-4 fusion are deliberately not built, because the evaluation has not
  shown that Level 2 is worth keeping.
- **Not advice.** Divya produces labelled, auditable decision state. It does not predict prices
  and it does not recommend trades.
- **Not real-time.** EOD bhavcopy and the announcement feed. Every view carries an as-of time,
  and stale data is labelled stale.
- **Not licence-cleared for redistribution.** See [B-002](docs/loop/BLOCKERS.md).

---

## Repository map

```
src/divya/protocol/   versioned decision protocol; untrusted-text sanitiser
src/divya/system1/    the Laya adapter — the only module that imports laya
src/divya/system2/    System-2 provider interface (ollama / openai_compatible / heuristic)
src/divya/runtime/    shared state, the recurrent loop, tracing, termination
src/divya/data/       source adapters, NSE live sources, licence register, taxonomy, PDF
                       extraction, and the SQLite store
src/divya/eval/       A/B/C/D harness, metrics, paired significance, red-team suite
src/divya/terminal/   the TUI (app.py) and the single-decision audit view (view.py)
models/questions.yaml the decision protocol
docs/loop/            project state — the external memory
docs/architecture/    UNIFIED_MODEL.md
research/             primary-source research and benchmark scripts
evals/                dataset builders (synthetic + real) and results
tests/                378 tests
```

`AGENTS.md` is the operational contract for anyone working here, including the rules on claims,
provenance, and what counts as evidence.

---

## Licence

Apache-2.0. Laya is Apache-2.0 (Convai Innovations). Data sources carry their own terms; see
`src/divya/data/sources.py`.
