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

```
$ divya decide --text "HDFC Bank Limited has informed the Exchange about its quarterly
financial results. Net profit after tax stood at Rs 18,209 crore as against Rs 16,510 crore
in the corresponding quarter of the previous year, an increase of 10.3 per cent. The Board
has recommended an interim dividend of Rs 12.50 per share." --trace
```

The reasoning model asks for the tier-1 decisions, escalates to the evidence-quality
decisions, requests a numeric-presence check, and concludes — or abstains. Every step is in
the output and in a JSON trace:

```
│ 0  ollama:qwen2.5-coder:3b   call_system1 ['event_type','is_material']     8905ms │
│ 1  ollama:qwen2.5-coder:3b   call_system1 ['evidence_sufficiency', …]      1343ms │
│ 2  ollama:qwen2.5-coder:3b   call_system1 ['numeric_disclosure_present']    1172ms │
│ 3  ollama:qwen2.5-coder:3b   finish                                       1453ms │
```

---

## Quick start

Requires Python ≥ 3.10. Tested on Python 3.12.

```bash
git clone <this repo> && cd divya
make setup          # venv + pinned dependencies
make test           # 79 tests
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
divya decide --file evals/datasets/nse_announcements_v1.jsonl   # (or pipe one record)

# 3. Inspect any past run in full
divya show <task-id> --full

# 4. Inspect the versioned decision protocol
divya protocol show
divya protocol diff --other path/to/older/questions.yaml
```

### Data defaults

The shipped default is **fixture data**, and every fixture record is stamped `is_simulated=True`
**in the data itself**, not just in the documentation. It cannot be laundered into looking live.

Live NSE endpoints work and `divya fetch` uses them, but they are exchange-proprietary and **no
reuse grant was located**. That is fine for running this yourself; it is **not** clearance to
redistribute a build with the data baked in. The per-source verdict lives in
`src/divya/data/sources.py` and is printed by `divya doctor`. See
[docs/loop/BLOCKERS.md](docs/loop/BLOCKERS.md) B-002.

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

### The headline result: the thesis is rejected on this data

120 real NSE announcements, four arms paired in one process against one loaded checkpoint.

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | Prompt tok | Abstain |
|---|---|---|---|---|---|---|---|
| **A** System-1 alone | **0.558** | 0.436 | 0.096 | **0.240** | **4.7 s** | 0 | 0.0% |
| **B** System-2 alone | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 2214 | 0.0% |
| **C** System-2 → System-1 | **0.558** | 0.436 | 0.096 | **0.240** | 19.0 s | 1079 | 0.0% |
| **D** recurrent loop | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | 4941 | **75.8%** |

1. **A and C are identical to the decimal** on all four metrics. The reasoning layer contributes
   *zero* while costing 4× the latency.
2. **D is worse than C** — 0.508 vs 0.558 — at 8.5× the latency, 2.57 System-1 calls per event,
   and a 75.8% abstention rate that scores the abstained events wrong.

H1 (loop helps) **rejected** · H2 (loop ≈ single-shot) **rejected** · H3 (loop hurts)
**supported** · H4 (calibration win) **not supported**. H3 is also what the external literature
predicts — ATLAS (arXiv 2510.15949) reports reflection-based feedback fails to give systematic
gains.

**So the default runtime is `system1_only`.** The recurrent loop is retained, tested and traced
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
src/divya/protocol/   versioned decision protocol: schema, loader, migration checks
src/divya/system1/    the Laya adapter — the only module that imports laya
src/divya/system2/    System-2 provider interface (ollama / openai_compatible / heuristic)
src/divya/runtime/    shared state, the recurrent loop, tracing, termination
src/divya/data/       source adapters, NSE live sources, licence register, taxonomy mapping
src/divya/eval/       A/B/C/D harness and metrics (accuracy, Brier, ECE, risk-coverage)
src/divya/terminal/   the terminal view
models/questions.yaml the decision protocol
docs/loop/            project state — the external memory
docs/architecture/    UNIFIED_MODEL.md
research/             primary-source research and benchmark scripts
evals/                dataset builders (synthetic + real) and results
tests/                79 tests
```

`AGENTS.md` is the operational contract for anyone working here, including the rules on claims,
provenance, and what counts as evidence.

---

## Licence

Apache-2.0. Laya is Apache-2.0 (Convai Innovations). Data sources carry their own terms; see
`src/divya/data/sources.py`.
