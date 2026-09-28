# STATUS

_Last updated: 2026-09-28, iteration 2._

## CURRENT OBJECTIVE

Build the A/B/C/D evaluation harness and a real evaluation dataset, so the thesis (D > C) can be
falsified rather than asserted. The runtime, protocol, and System-1 adapter work; the
measurement apparatus is the gap.

## WHAT CHANGED

- **N1 complete: Laya measured on this CPU.** See BENCHMARKS.
- **N2 partially complete: the full loop runs end-to-end with a real Laya checkpoint** and a
  real JSONL trace, including escalation from tier 1 to tier 2.
- Primary-source research completed (`research/LITERATURE.md`, `INDIA_DATA.md`, `ENVIRONMENT.md`,
  578 lines). **It contradicts the PDR in four places** — see below.
- Decision protocol v0 written (`models/questions.yaml`: 2 specs, 7 questions, 2 tiers).
- Shared state, StateBuilder, System-2 provider interface, System-1 adapter, and the recurrent
  loop implemented and exercised.
- NSE bhavcopy adapter written and **verified against a live fetch** (HTTP 200, 177,333 bytes).

## EVIDENCE

### `[RESULT]` N1 — Laya on this machine, finance-shaped text

Artifact: `research/results/bench_laya.json`. Script: `research/scripts/bench_laya.py`.

| Metric | Value |
|---|---|
| Hardware | WSL2, 16 vCPU AMD Ryzen 7 4800H, 7.5 GiB RAM, **no GPU used** |
| Software | Python 3.12.3, torch 2.14.0+cpu, laya 0.3.21, `cuda_available: False` |
| Checkpoint routed to | `english` (all fixtures are English) |
| Cold load (download + first predict) | **280.03 s** |
| Warm p50 latency, 4 questions, 3 repeats | **4552.5 ms** median across fixtures |
| Per-fixture p50 | earnings 5806 · board_meeting 4930 · regulatory 4175 · summary 3951 ms |
| Peak RSS | **2746.2 MB** |
| `event_type` correctness | **4 / 4** on the four clean fixtures |
| `event_type` top probability | 0.9999, ~1.0, 0.9996, 0.9239 |

**This falsifies the PDR's latency claim.** `plan.md` states 193–464 ms per question on CPU.
Measured: 4552 ms for four questions ≈ **1138 ms per question**, 2.4× to 5.9× slower than the
optimistic end of the PDR's range. Cost scales with the number of questions in one forward pass,
not with a fixed per-call overhead — so the "fast typed decision engine" framing needs qualifying:
it is fast relative to an LLM, not sub-second per decision on commodity CPU.

### `[RESULT]` The interesting failure is ambiguity, not competence

All four clean fixtures classify correctly with high confidence. But in the end-to-end smoke
run, this text:

> "Reliance Industries reported Q2 FY25 net profit of Rs 30,783 crore, up 12.5% YoY. The Board
> declared an interim dividend of Rs 6 per share."

was classified **`board_dividend` (0.9237)** over `earnings_result` (0.0762). The text leads
with profit; the subject of the filing is the results. This is the failure mode predicted in
`models/questions.yaml` under `event_type.known_failure_modes`, and it was found by running the
system rather than by reasoning about it.

**This is the most valuable result so far.** Two answers are defensible here and the system picks
the wrong one *confidently*. It is exactly the population on which a recurrent loop either helps
(H1), does nothing (H2), or compounds the error (H3). The evaluation must include this stratum
and must not let the 4/4 clean score stand in for overall quality.

### `[RESULT]` Loop mechanics verified with a real checkpoint

Artifact: `research/results/smoke_trace.json`. Termination `finished`, 2 turns, 2 System-1
calls, 3 System-2 calls. Escalation from `event_triage` (tier 1) to `event_evidence` (tier 2)
happened as designed. First System-1 call 105.9 s (includes checkpoint load), second 2.8 s warm.

### `[FACT]` Laya is real — verified from primary source, not from the PDR

Package `laya` 0.3.21, Apache-2.0, author "Convai Innovations"; 29 releases 0.1.6 → 0.3.21.
Verified via PyPI JSON API and by reading the installed source, not documentation:

- `QTYPES = {"choice": 0, "score": 1, "noul": 2}` — `laya/common.py:17`
- `_resolve_noul_labels` — `laya/common.py:92`; noul `labels` must map exactly `{"false","true"}`
- `render_options` — `laya/common.py:106`; `labels` is **rejected** for non-noul questions
- `Router.predict(state, questions, …)` — `laya/router.py:712`; `state` accepts `str|dict|list`
- `DEFAULT_MODELS` — `laya/router.py:49`

The PDR's core premise survives verification.

### `[DECISION]` Research contradicts the PDR — D-005, D-006, D-007

1. **"Talker-Reasoner / Collins et al."** is wrong on both counts. It is arXiv 2410.08328 by
   Christakopoulou, Mourad and Mataric — a NeurIPS 2024 *workshop poster* whose abstract contains
   no numbers. The PDR's claimed failure modes are not in it.
2. **No paper measures recurrent re-planning against a single-shot tool call.** Divya has no
   prior in either direction.
3. **The nearest evidence points against the thesis.** ATLAS (arXiv 2510.15949) reports that
   "reflection-based feedback fails to provide systematic gains". This is the strongest support
   for H3 (loop hurts) over H1, and is why the evaluation is built to be able to return a
   negative result.
4. **The bhavcopy URL in `plan.md` 404s**, redistribution rights are unresolved, and NSE changes
   the dissemination format on 2026-10-12. Redistribution re-tagged from `[E]` to `[?]`.

## TESTS

- No pytest suite yet. Loop verified by direct execution, not by tests. **This is a real gap**
  and is fixed immediately after the harness.

## BENCHMARKS

See `[RESULT]` N1 above and `docs/loop/EVALS.md`. All numbers carry hardware, software version, n,
and baseline. The A/B/C/D comparison has **not** been run.

## KNOWN FAILURES

- `FetchURL` tool: fails on every host here. Use `curl` via Bash.
- Docker absent: `docker compose up` unachievable (D-002).
- No pytest suite.
- Laya is over-confident on the ambiguous results+dividend case and emitted no low-confidence
  signal that would have triggered abstention.

## OPEN QUESTIONS

- Q1. ~~What is Laya's latency on this CPU?~~ **Answered: 1138 ms/question warm, RSS 2.7 GB.**
- Q2. Can the 4B model emit valid structured turns, and at what rate? Partially answered —
  schema-constrained decoding via Ollama's `format` field is wired; validity rate unmeasured.
- Q3. Is D > C? **Still open, and now the entire point.** Requires the evaluation.
- Q4. Real Indian market data? Partially answered: the endpoint works, the licence does not
  clear, so fixtures remain the default (D-006).

## NEXT HIGHEST-VALUE ACTION

Build the evaluation harness and dataset: an A/B/C/D runner that executes all four arms on the
same examples and computes accuracy, Brier, ECE and risk–coverage **per stratum**, so the
ambiguous subset cannot hide inside a pooled average.
