# UNIFICATION_EXPERIMENTS.md

Every experiment run against the System-1/System-2 architecture, including the ones that did
not work. Each entry: HYPOTHESIS · METHOD · BASELINE · DATASET · METRICS · RESULT · FAILURE
ANALYSIS · DECISION.

**Environment for every measurement below**, stated once so it is not restated ad hoc:
WSL2, 16 vCPU AMD Ryzen 7 4800H, 7.5 GiB RAM, **no GPU used**, torch 2.14.0+cpu,
laya 0.3.21, `qwen2.5-coder:3b` via Ollama 0.31.1, Python 3.12.3. All dates 2026-09-28.

---

## E-001 — Does the premise hold? Is Laya a real, capable System-1 engine?

**HYPOTHESIS.** The PDR's central dependency — "Laya", an Apache-2.0 non-autoregressive System-1
engine with `choice`/`score`/`noul` primitives — exists as described.

**METHOD.** Primary sources only, not the PDR and not documentation: the PyPI JSON API, the
downloaded wheel's `METADATA`, and the installed Python source.

**RESULT.** Confirmed.
- `laya` 0.3.21, Apache-2.0, "Convai Innovations", 29 releases (0.1.6 → 0.3.21).
- `QTYPES = {"choice": 0, "score": 1, "noul": 2}` — `laya/common.py:17`.
- `_resolve_noul_labels` — `common.py:92`; `labels` rejected for non-noul — `common.py:110`.
- `Router.predict(state, questions, …)` — `router.py:712`; `state` accepts `str|dict|list`.
- `DEFAULT_MODELS` — `router.py:49`: `english`, `multilingual`, `typed-decisions`.

**DECISION.** Premise holds. The architecture rests on a real artifact with exactly the
documented interface. Proceed.

---

## E-002 — Is Laya fast enough, and is the PDR's latency claim true?

**HYPOTHESIS.** `plan.md`: 193–464 ms per question on CPU.

**METHOD.** `research/scripts/bench_laya.py`, 4 finance-shaped fixtures × 3 repeats, 4 questions
per call, all 14 protocol tier-1 questions. Warm p50 per fixture.

**BASELINE.** The PDR's stated range.

**RESULT.** **Falsified.** Warm p50 across fixtures: **4552 ms** for a 4-question call =
**1138 ms/question**. That is 2.4–5.9× slower than the PDR's optimistic bound. Peak RSS 2.75 GB.
Cold load 6.6 s (the 280 s first observed was mostly a one-time checkpoint *download*).
`event_type` was 4/4 correct on the four clean fixtures, with top probabilities 0.92–0.9999.

**FAILURE ANALYSIS.** The PDR's figures are from a T4. Even so, the gap is not a hardware
artefact: cost scales with the number of questions in one forward pass, not with a fixed
per-call overhead. "Fast" is relative to an LLM (System-2 at 0.56–0.91 s warm for the whole
turn), not sub-second per decision on commodity CPU.

**DECISION.** Keep Laya. Reframe the claim honestly: it is a *cheap* decision engine, not a
fast one. Record the measurement as the latency budget for everything downstream.

---

## E-003 — Is Laya's confidence usable for abstention on finance text?

**HYPOTHESIS.** Laya is trained with RL against strictly proper scoring rules, so its
probabilities should support a "I don't know" gate.

**METHOD.** Compute Brier, ECE (15 bins) and risk-coverage / AURC on real NSE announcements.
Stratified so the ambiguous subset cannot hide in a pooled average.

**DATASET.** 30 synthetic clean + 24 real NSE announcements (event_type only; NSE publishes no
other ground truth).

**RESULT.** **Largely no.**

| Population | Accuracy | Macro-F1 | ECE | AURC |
|---|---|---|---|---|
| Synthetic `clear` (n=30) | 0.733 | 0.724 | 0.216 | 0.117 |
| **Real NSE** (n=24) | **0.500** | 0.538 | **0.182** | 0.210 |

ECE bin detail on the real run is the informative part:

| Confidence bin | n | Stated | Actual | Gap |
|---|---|---|---|---|
| 0.60–0.67 | 5 | 0.627 | **0.200** | **0.427** |
| 0.73–0.80 | 2 | 0.752 | 0.500 | 0.253 |
| 0.80–0.87 | 3 | 0.836 | 1.000 | 0.164 |
| **0.93–1.00** | 7 | 0.995 | **1.000** | **0.005** |

**FAILURE ANALYSIS.** Two separate problems.

1. **The mid-confidence band is unusable.** At 0.6–0.73 stated confidence, the engine is right
   20% of the time. A terminal gating on `min_confidence = 0.55` would be *most* confident
   exactly where it is most wrong. This is the failure the whole product exists to prevent.
2. **The high-confidence band is excellent.** At 0.93–1.0 it is 7/7 correct. Selective prediction
   *at a high threshold* is viable even though mid-range calibration is not.

**DECISION.** Do not trust the 0.5–0.8 band. A future `min_confidence` should sit above 0.9, and
that is an empirical finding rather than a default. A temperature refit on a Divya-specific dev
set is the obvious remedy and is untested — see E-006.

---

## E-004 — Synthetic evaluation data, or real?

**HYPOTHESIS.** A deterministic, stratified, adversarial synthetic set is sufficient to measure
System-1 quality.

**METHOD.** Identical harness, identical scoring, run on both populations.

**RESULT.** **No. Synthetic was flattering us by ~23 points.**

| Population | Laya `event_type` accuracy |
|---|---|
| Synthetic `clear` (n=30) | **0.733** |
| Real NSE announcements (n=24) | **0.500** |

**FAILURE ANALYSIS.** Authored text is drawn from templates the system then classifies. It
measures consistency with our own writing, not coverage of a real distribution. It also cannot
contain the 77% of a real feed that is process noise, which is the population that actually
determines whether a terminal is useful.

**DECISION.** Real NSE announcements become the primary evaluation set (D-010). Synthetic is
retained for determinism and for prompt-injection cases a live feed will never contain, and its
numbers are never quoted without the real ones beside them. This finding came from the user
challenging the approach, and the user was right.

---

## E-005 — What is actually in a real Indian announcement feed?

**HYPOTHESIS.** Corporate events are the common case in the feed.

**METHOD.** One month of live NSE announcements (14,805 records) classified by NSE's own `desc`.

**RESULT.** **The hypothesis is backwards.** The six largest classes are process:

| NSE class | n |
|---|---|
| Shareholders meeting | 2668 |
| Trading Window | 1858 |
| General Updates | 1752 |
| Analysts/Institutional Investor Meet | 1700 |
| Copy of Newspaper Publication | 1415 |
| Updates | 1035 |

**77% of the feed contains no corporate event.** The largest *event-bearing* class,
`Outcome of Board Meeting` (456), is a container: the text often does not state the outcome.

**FAILURE ANALYSIS.** The first taxonomy draft mapped `Trading Window` → `regulatory_action`,
which was wrong — a trading-window closure is routine SEBI PIT compliance, not a penalty or
sanction, and that mapping alone would have contaminated 47% of the evaluation population with a
false label. It was caught by reading the frequency table before trusting the mapping, not after.

**DECISION.** Process classes are ingested and labelled `unresolved`, never dropped and never
guessed. All 104 published classes are mapped explicitly; unmapped classes fall through to
`unresolved` rather than defaulting to `other`, so a class we have never seen cannot masquerade
as a resolved label. See D-010 and `src/divya/data/nse_taxonomy.py`.

---

## E-006 — Is the checkpoint's calibration trustworthy for a wide choice question?

**HYPOTHESIS.** Any `choice` question with up to ~20 options returns usable confidence.

**METHOD.** Read `rl_agent_config.json` from the shipped checkpoint and reproduce Laya's bucket
routing from `laya/common.py:499`.

**RESULT.** **No — and this silently invalidated our own measurements.** Laya fits temperature
per `(type, option-count)` bucket:

| Bucket | Temperature | Status |
|---|---|---|
| `choice:2` | 1.9064 | valid |
| `choice:3-5` | 1.7602 | valid |
| `choice:6-10` | 1.0 | valid |
| **`choice:11+`** | **0.1006** | **invalid** |
| `noul:2` | 1.9834 | valid |
| `score:3-5` | 1.2514 | valid |

A temperature below 1 *sharpens* logits. At 0.1006 that is ~10×. Laya's own source comment:
"a 0.24 top probability is published as 0.99, so a caller gating on confidence is told a coin
flip is a certainty." Laya refuses to apply it, clamps to 0.5, and warns that confidence from
that bucket is uncalibrated (`agent.py:485`).

**Our `event_type` question had 11 options and was in exactly that bucket.** Every calibration
number it produced was measuring a value the library had already disclaimed.

**FAILURE ANALYSIS.** The warning *is* emitted at load time — it was in the benchmark output
and was initially read as noise. It should have been treated as a hard finding on sight.

**DECISION.** `event_triage` v1 → v2, merging `board_dividend` into `capital_action` to reach 10
options and the valid `choice:6-10` bucket. `load_protocol` now reproduces `temp_bucket` and
**refuses to load** a protocol with a `choice` question in an uncalibrated bucket. See D-008.

**AFTER THE FIX:** ECE on real data is still 0.182, and the 0.6–0.73 band is still 20% accurate
at 63% stated confidence. Removing a known defect did not make Laya calibrated on finance text.
**This experiment is not closed** — a temperature refit on a Divya dev set is the open follow-up.

---

## E-007 — Which reasoning model can actually run the loop?

**HYPOTHESIS.** A 4B instruction model is the right System-2 for a 7.5 GiB CPU-only box.

**METHOD.** Warm `/api/chat` latency, schema-constrained, 3 back-to-back calls per model, with
Laya resident (2.8 GB).

**RESULT.** **No.**

| Model | Warm wall | Model's own `eval_duration` |
|---|---|---|
| `qwen2.5-coder:3b` | 0.91 / 0.56 / 0.56 s | 0.32–0.36 s |
| `qwen3:4b` | 50.1 / 42.4 / 63.5 s | 1.3–2.2 s |

**FAILURE ANALYSIS.** The 4B model generates in 1.3–2.2 s and spends the other 40–60 s paging.
It does not fit alongside Laya. At that latency an arm-D number would measure memory behaviour,
not the loop.

**DECISION.** Default to 3B (D-009). `qwen3:4b` remains selectable. **Caveat stated plainly:**
`qwen2.5-coder:3b` is code-specialised and the System-2 task is structured JSON emission, not
coding. It emits valid schema-constrained JSON and did drive a correct 4-turn loop, but "a coder
model reasons well about filings" is not a claim this evidence supports.

---

## E-008 — Is batching a free performance win?

**HYPOTHESIS.** `predict_batch` amortises cost across an event stream.

**METHOD.** Batch sizes 1→12, 2 repeats, 12 finance-shaped states.

**RESULT.** **No. 1.10× at best** (batch 4, 1.764 s/item vs 1.943 s/item single).

| Batch | Total | Per item |
|---|---|---|
| 1 | 1.943 s | 1.943 s |
| 4 | 7.054 s | **1.764 s** |
| 12 | 22.217 s | 1.851 s |

Marginal cost per additional question is ~0.8 s, so questions are cheap relative to re-encoding
a document.

**FAILURE ANALYSIS.** Torch already saturates all 16 threads on a single item, so there is no
idle capacity for a batch to reclaim. On a machine with fewer cores the answer could differ.

**DECISION.** Do not build batched inference into the runtime. Record the negative result so it
is not rediscovered as a promising-sounding idea. See D-011. **ONNX remains unmeasured** —
`onnxruntime` is not installed, and it is the one lever still worth trying.

---

## E-009 — Does the recurrent loop beat a single-shot tool call? *(the actual thesis)*

**STATUS: RUNNING.** Results in `evals/results/real_eval.json`; read and reported in
`docs/loop/STATUS.md` and the final report.

**HYPOTHESES held open** (from `research/LITERATURE.md` §7):

- **H1** the loop helps, concentrated on genuinely ambiguous events.
- **H2** the loop buys latency and tokens for nothing.
- **H3** the loop *hurts*, amplifying Laya's miscalibration. Currently the best-supported
  alternative: ATLAS (arXiv 2510.15949) reports that reflection-based feedback fails to give
  systematic gains, and E-003 shows Laya is miscalibrated exactly in the mid-confidence band
  where a reasoning model would most rely on it.
- **H4** the win, if any, is calibration rather than accuracy.

**METHOD.** Four arms on the same 120 real NSE announcements, same process, same loaded
checkpoint, paired: **A** System-1 alone · **B** System-2 alone · **C** System-2 → System-1
single shot (the control) · **D** System-2 ↔ shared state ↔ System-1 recurrent.

Metrics: accuracy, macro-F1, Brier, ECE, AURC, per-stratum accuracy, wall p50/p95, System-1 call
count, unnecessary System-1 calls, prompt/completion tokens, termination and abstention rates.
Strata are assigned **before** scoring, by the dataset builder, so H1 cannot be made
unfalsifiable by choosing the split after seeing results.

**Known limitation of this experiment, stated in advance:** NSE publishes no ground truth for
`is_material`, `materiality` or `direction`, so only `event_type` is scored on real data. The
other two are reported as `"not evaluated"` rather than quietly dropped or scored against the
model's own output.
