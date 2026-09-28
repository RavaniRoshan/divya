# DECISIONS

Architecture-changing decisions only. Format: DATE / DECISION / CONTEXT / OPTIONS / EVIDENCE /
TRADE-OFFS / WHY / REVERSIBILITY / FOLLOW-UP.

---

## D-001 — 2026-09-28 — Verify the premise before writing product code

**DECISION.** The first substantive act of the project is primary-source verification of Laya
(PyPI API, wheel contents, source of `router.py`/`common.py`), not scaffolding or architecture.

**CONTEXT.** The PDR is a *hypothesis*, and its entire architecture rests on a specific external
model existing with specific capabilities. If "Laya" were not a real artifact, every subsequent
decision — protocol schema, adapter, eval design — would be building on sand.

**OPTIONS.**
1. Scaffold the project first, verify Laya later. *(Rejected: builds on an unverified premise.)*
2. Verify from the PDR's own citations. *(Rejected: the PDR is what is under test.)*
3. Verify from primary sources: the PyPI JSON API, the downloaded wheel's `METADATA`, and the
   actual Python source of the question-validation and routing code. *(Chosen.)*

**EVIDENCE.** `curl https://pypi.org/pypi/laya/json` → HTTP 200. Wheel downloaded (214 kB).
Source read directly: `QTYPES = {"choice": 0, "score": 1, "noul": 2}` at `laya/common.py:17`;
`DEFAULT_MODELS` at `laya/router.py:49`; `_resolve_noul_labels` at `laya/common.py:92`;
`Router.predict` at `laya/router.py:712`. Full table in `STATUS.md`.

**TRADE-OFFS.** Costs one iteration of apparent "progress". Buys certainty on the single fact the
whole project rests on, and produced the exact question schema needed to design the protocol.

**WHY.** The mission explicitly forbids treating the PDR as unquestionable, and explicitly
requires replacement of unsound requirements rather than forced implementation. Verification is
the only way to know which case applies.

**REVERSIBILITY.** Fully reversible; nothing was built.

**FOLLOW-UP.** Benchmark Laya on this CPU (Q1 in STATUS).

---

## D-002 — 2026-09-28 — Docker target is unreachable in this environment; ship venv + Makefile

**DECISION.** Reproducible setup is delivered as `make setup` / `make test` over a pinned Python
venv, not `docker compose up`. A `Dockerfile` + `docker-compose.yml` will still be authored and
kept correct, but will be **labelled unverified in this environment** rather than claimed as
working.

**CONTEXT.** The PDR's stated release target is `docker compose up`. This machine has no docker
binary at all.

**OPTIONS.**
1. Ship `docker compose up` as the primary documented path anyway. *(Rejected — that would be a
   fabricated verification claim. The mission's model-truthfulness rule forbids it.)*
2. Install docker. *(Rejected: requires privileges/daemon changes outside project scope, and
   WSL2 docker is a host-level change, not a project-level one.)*
3. Make venv+Makefile the verified primary path; author the compose files and mark them
   `UNVERIFIED-HERE` with the exact reason. *(Chosen.)*

**EVIDENCE.** `command -v docker` → not found. Logged in `STATUS.md` KNOWN FAILURES.

**TRADE-OFFS.** Less friction for a hypothetical future user with docker; more friction now.
Honest, and correct under the evidence rules.

**WHY.** "Clean-machine setup works" is an acceptance criterion. It can only be claimed for a path
that was actually executed here.

**REVERSIBILITY.** Fully reversible. If docker appears, add CI that runs the compose path and
flip the primary path.

**FOLLOW-UP.** Re-test on a docker-capable host and update README when available.

---

## D-003 — 2026-09-28 — System-2 is a provider interface, not a hardcoded model

**DECISION.** System-2 is defined by a `System2Provider` protocol with three implementations
selected by `DIVYA_S2_PROVIDER`: `ollama`, `openai_compatible`, and `heuristic`. No provider is
defaulted to a specific model in code.

**CONTEXT.** The loop must (a) run on a zero-API-key self-hosted box, (b) run in CI and in
`pytest` with no LLM resident, and (c) degrade visibly when the reasoning model is unavailable —
which is an explicit red-team requirement. A hardcoded model name fails all three.

**OPTIONS.**
1. Hardcode one local model. *(Rejected: fails CI and the degradation requirement.)*
2. Cloud API only. *(Rejected: violates the zero-cost, self-host, no-secret requirements.)*
3. Pluggable provider interface with an explicitly-labelled heuristic policy. *(Chosen.)*

**EVIDENCE.** Ollama 0.31.1 present, `localhost:11434` returns HTTP 200, `qwen2.5-coder:3b`
resident and answering. Confirms (a) is achievable here.

**TRADE-OFFS.** Three code paths to keep honest. The `heuristic` provider is the real risk: a
heuristic must never be mistaken for a model. Mitigation: it is named `heuristic` (not `mock`),
it emits a `provider_is_model: false` flag into every trace, and the eval harness reports its
results in a separate block from real-model results.

**WHY.** Testability and honest degradation are acceptance criteria; a pluggable interface is the
smallest thing that satisfies both.

**REVERSIBILITY.** Reversible — add providers, don't change the interface.

**FOLLOW-UP.** Measure whether the 4B model can emit reliable structured output, or whether
constrained decoding is required (Q2 in STATUS).

---

## D-004 — 2026-09-28 — Laya's published benchmark numbers are not finance numbers

**DECISION.** The PDR's "0.362 base / 0.766 fine-tuned" figures will **not** be used as
assumptions about Laya's behaviour on Indian market events. All Laya quality claims in this repo
will come from measurements on a Divya-built, finance-shaped dataset with n stated.

**CONTEXT.** Those numbers come from the upstream typed-decisions benchmark, which is
customer-support triage (department / urgency / churn-risk). Financial event text is a different
distribution. Treating them as a prior would be exactly the "hypothesis promoted to fact by
repetition" failure the AGENTS rules forbid.

**OPTIONS.**
1. Carry the numbers forward as an expected range. *(Rejected — distribution mismatch.)*
2. Discard them entirely. *(Rejected — they are real measurements, just of the wrong thing;
   discarding loses a useful reference point.)*
3. Cite them explicitly as *triage-domain* measurements, and measure the finance domain
   independently. *(Chosen.)*

**EVIDENCE.** Upstream README describes the benchmark as "2,000 decisions across four
workflows" in a customer-support framing (department / urgency / churn risk).

**TRADE-OFFS.** Requires building a Divya-specific eval set earlier in the schedule. That is
the correct cost — the eval set is needed for P7 regardless.

**WHY.** The mission forbids fabricated model-quality claims, and this is the most likely place
one would creep in.

**REVERSIBILITY.** Reversible once measured.

**FOLLOW-UP.** Build the finance decision set as part of the P3/P6 work.

---

## D-005 — 2026-09-28 — The literature does not support the architecture; we must measure it ourselves

**DECISION.** Divya will not cite any prior work as evidence that the recurrent System-2/System-1
loop improves decisions. The evaluation will be designed so that the thesis is genuinely
falsifiable, and the four competing hypotheses (H1 loop-wins, H2 null, H3 loop-hurts,
H4 calibration-not-accuracy) will be treated as live until the data says otherwise.

**CONTEXT.** Research (`research/LITERATURE.md`, 175 lines, primary sources) checked whether a
measured case for this architecture exists. It does not.

**EVIDENCE.** All verified by fetching the sources, 2026-09-28:
- The paper most often cited for this architecture — dyadic / Talker-Reasoner, arXiv
  **2410.08328** — is by **Christakopoulou, Mourad, Mataric**, *not* "Collins et al." as the PDR
  claims. It is a **NeurIPS 2024 workshop poster**, v1 only, and its abstract contains **no
  quantitative result at all**. The PDR's claimed failure modes (self-consistency loss, premature
  termination) could not be found in it.
- Every *measured* result found (LLM2, FrugalGPT, Conformal Cascade, Cluster-Route-Escalate) is a
  **single-shot** decision refined by routing or escalation. **No fetched paper measures
  recurrent re-planning over shared state against a single-shot tool call.** That is the exact
  comparison Divya needs, and it has no prior.
- The strongest adjacent evidence points the *wrong* way: **ATLAS, arXiv 2510.15949**, reports
  that **"reflection-based feedback fails to provide systematic gains"** while prompt
  optimisation did. This directly supports H3 (loop hurts) over H1 (loop helps).
- Laya's own documented weaknesses compound the risk: upstream records it as over-confident,
  with a `noul` abstention bias (issue #156) and a broken `act_probability` (issue #185). A
  System-2 that re-plans on a miscalibrated System-1 signal can amplify System-1's errors.

**TRADE-OFFS.** This removes the "the literature backs us" fallback entirely, and makes a null or
negative result the single most likely outcome. That is the honest position and it is cheaper
now than after building an evaluation that cannot fail.

**WHY.** The mission forbids fabricated claims and requires contradicting evidence to be recorded
and the design updated. A negative result here is a valid, valuable deliverable.

**REVERSIBILITY.** N/A — this is a constraint on what we may claim, not a design choice.

**FOLLOW-UP — evaluation design now inherits four requirements from the research:**
1. **Control for sample count.** If arm D iterates, arm C must get self-consistency (n samples)
   or the comparison is confounded by how many times each arm sampled.
2. **Report ECE and risk–coverage, not accuracy alone.** A cascade that reports only accuracy
   is uninterpretable.
3. **Evaluate per stratum.** Divya's event strata (earnings / corporate actions / filings) are
   exactly the kind of group under which a single pooled number hides failure.
4. **Pre-register the ambiguity split.** If "ambiguous" is defined after seeing results, H1 is
   unfalsifiable. The split rule is fixed in `evals/` before the run.

---

## D-006 — 2026-09-28 — First domain: NSE corporate announcements + XBRL; bhavcopy for prices only

**DECISION.** The first real domain is **NSE corporate announcements**, with the EOD bhavcopy
used **only** for price context, never for the decision itself. The announcement's own `desc`
field is used as the label for System-1's `event_type` head.

**CONTEXT.** `research/INDIA_DATA.md` found the PDR's bhavcopy URL is dead and the redistribution
question is unresolved.

**EVIDENCE.** Verified by direct fetch on this machine, 2026-09-28:
- The PDR's `content/historical/EQUITIES/2026/SEP/cm01SEP2026bhav.csv.zip` path **404s**.
  The live path is `content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`, which returned
  **HTTP 200, 177,333 bytes**, a valid zip containing a 545 KB CSV.
- **Every NSE host requires a browser User-Agent.** A request with no UA returns no response;
  a Chrome UA returns 200. This is a real integration constraint, not a workaround.
- **Redistribution remains UNRESOLVED.** NSE's Terms/Disclaimer/Copyright pages are
  client-rendered SPAs whose legal text never appears in served HTML. `Allow: /` in robots.txt is
  crawler etiquette, not a licence. The PDR's `[E] Bhavcopy EOD free/redistributable` traces only
  to a tejhq README assertion, and that project is two repositories with 1 and 0 stars whose MIT
  licence covers code only. **Re-tagged from `[FACT]` to `[?]`.**
- **Contract instability.** Exchange circular **NSE/MSD/76457** (21 Sep 2026) re-organises
  bhavcopy dissemination **effective 12 Oct 2026** — the fourth such circular since June. Any
  hard-coded URL is a liability.
- Announcements carry a pre-classified `desc` and a `hasXbrl` flag, which is a far better
  training/eval target for a `choice` head than self-annotation.

**TRADE-OFFS.** Using the exchange's own `desc` as ground truth means we are measuring agreement
with NSE's taxonomy, not truth. That must be stated in every evaluation, because the taxonomy is
coarse and the eval cannot show the system is right — only that it is consistent and calibrated
against a published label.

**WHY.** It is the only source in reach that is both real and machine-readable today, and using
its own labels avoids inventing an unverifiable ground truth.

**REVERSIBILITY.** Fully reversible. All sources sit behind an adapter; the licence verdict lives
in a register, not in the ingestion code.

**FOLLOW-UP.** Build `src/divya/data/sources/nse.py` with UA handling, freshness stamping, and
explicit `SIMULATED` labelling for anything not fetched live. Re-verify the URL after 12 Oct 2026.

---

## D-007 — 2026-09-28 — Cap System-2 at ~4B parameters; Laya stays on CPU

**DECISION.** Default System-2 is `qwen3:4b` via Ollama on CPU. Laya runs on the CPU torch
wheel. No GPU path is assumed anywhere in the design or in any latency claim.

**CONTEXT.** The box has 7.5 GiB RAM and 4 GiB VRAM, and must hold an operating system, a Python
runtime, the Laya checkpoint, and the reasoning model simultaneously.

**EVIDENCE.** `research/ENVIRONMENT.md`; `nvidia-smi` shows 4 GiB VRAM; `free -h` shows 7.5 GiB
RAM; the installed torch is `2.14.0+cpu` with `cuda_available: False`. `qwen3:4b` is now pulled
and resident.

**TRADE-OFFS.** A 4B model is weak at multi-step reasoning and unreliable at JSON without a
grammar constraint — hence the schema-constrained `format` field in the Ollama provider. It also
means loop latency is dominated by generation, not by System-1, which will itself be an
interesting and reportable finding.

**WHY.** RAM, not VRAM, is the binding constraint, and a design that assumes more hardware than
the target box has is not a self-hosting design.

**REVERSIBILITY.** Reversible — the provider interface is swappable without touching the runtime.

**FOLLOW-UP.** Measure System-2 structured-output validity rate (blocker B-003).

---

## D-008 — 2026-09-28 — `event_type` reduced 11 → 10 options: the shipped checkpoint's `choice:11+` bucket is uncalibrated

**DECISION.** `event_triage` v1 → v2. `board_dividend` merged into `capital_action`, taking
`event_type` from 11 options to 10. `load_protocol` now refuses to load any protocol whose
`choice` question lands in a bucket the checkpoint's calibration does not cover.

**CONTEXT.** Laya fits a separate temperature per `(type, option-count)` bucket. Our 11-option
`event_type` question landed in the `choice:11+` bucket, and every calibration number it
produced was measuring a value the library had already disclaimed.

**EVIDENCE.** Read from the shipped checkpoint's `rl_agent_config.json`, 2026-09-28. Bucket rule
reproduced from `laya/common.py:499` `temp_bucket`: `k≤2→"2"`, `k≤5→"3-5"`, `k≤10→"6-10"`,
else `"11+"`.

| Bucket | Temperature | Status |
|---|---|---|
| `choice:2` | 1.9064 | valid |
| `choice:3-5` | 1.7602 | valid |
| `choice:6-10` | 1.0 | valid |
| **`choice:11+`** | **0.1006** | **invalid** — Laya clamps to 0.5 and warns "Treat confidence from the affected entries as uncalibrated" (`laya/agent.py:485`) |
| `noul:2` | 1.9834 | valid |
| `score:3-5` | 1.2514 | valid |

A temperature **below 1 sharpens** logits rather than softening them. At 0.1006 that is ~10×:
Laya's own comment states "a 0.24 top probability is published as 0.99, so a caller gating on
confidence is told a coin flip is a certainty."

**TRADE-OFFS.** We lost the ability to distinguish a dividend from a buyback, which is a real
taxonomy loss. In exchange, `event_type` confidence becomes a quantity we are entitled to
report. The alternative — keeping 11 options and quoting ECE — would have meant publishing
calibration numbers the upstream library explicitly says not to trust.

**WHY.** The whole product rests on being able to say "I don't know, and here is how sure I am."
A confidence the engine disclaims destroys that, silently.

**REVERSIBILITY.** Reversible but not free: it is a decision-problem change, so answers recorded
under v1 are not comparable to v2. `check_migration` reports the change explicitly.

**FOLLOW-UP.** Even in the valid bucket, measured ECE on real NSE data is **0.182**, and in the
0.6–0.73 confidence band accuracy is 20% against 63% stated confidence. Moving out of the
broken bucket removed a known defect; it did not make Laya calibrated on finance text. A
temperature refit on a Divya-specific dev set is the obvious next experiment.

---

## D-009 — 2026-09-28 — System-2 defaults to a 3B model, not 4B: 4B is 70–100× slower on the target box

**DECISION.** Default `DIVYA_S2_MODEL` is `qwen2.5-coder:3b`. `qwen3:4b` is supported but not
the default. No GPU path is assumed anywhere.

**CONTEXT.** The target box is 7.5 GiB RAM / 4 GiB VRAM / 16 vCPU, and must hold System-1
(2.8 GB RSS) and System-2 simultaneously.

**EVIDENCE.** Warm end-to-end `/api/chat` latency, schema-constrained, Laya resident:

| Model | Wall (3 calls) | Model's own `eval_duration` | Verdict |
|---|---|---|---|
| `qwen2.5-coder:3b` | 0.91 / 0.56 / 0.56 s | 0.32–0.36 s | usable |
| `qwen3:4b` | 50.1 / 42.4 / 63.5 s | 1.3–2.2 s | **memory thrash** |

The 4B model's *generation* is only 1.3–2.2 s. The other 40–60 s is paging. At that latency an
arm-D figure would be meaningless, because the loop's cost would be dominated by a model that
does not fit, not by the architecture under test.

**TRADE-OFFS.** `qwen2.5-coder:3b` is code-specialised, and the System-2 task is structured JSON
emission rather than coding. It does emit valid schema-constrained JSON, and it did drive a
correct 4-turn loop with sensible escalation in an end-to-end run — but "a coder model reasons
well about filings" is not a claim anyone should make on this evidence. `DIVYA_S2_MODEL` makes
this swappable without touching the runtime.

**WHY.** The architecture claim is about the *loop*, not the model. A model that does not fit in
the memory budget invalidates the measurement.

**REVERSIBILITY.** Fully reversible; the provider interface is the seam.

**FOLLOW-UP.** Re-measure on a larger box before claiming anything about 4B-class models.

---

## D-010 — 2026-09-28 — Real NSE announcements are the evaluation set; synthetic is kept only for adversarial cases

**DECISION.** The primary evaluation runs on **live NSE corporate announcements** labelled by
NSE's own `desc` taxonomy. The synthetic dataset is retained for determinism and for
prompt-injection cases, but its numbers are never quoted without the real ones beside them.

**CONTEXT.** The user was right to challenge the synthetic-only approach, and the data confirmed
it: Laya scores **0.733** on the synthetic clear stratum and **0.500** on real announcements.
The synthetic set was flattering us by roughly 23 points.

**EVIDENCE.** Verified by direct fetch 2026-09-28:
- `https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=…&to_date=…`
  → HTTP 200, **14,805 records for Sept 2026**, **no cookies needed**, browser UA required.
  Carries `desc` (104 human-curated classes), `attchmntText`, `attchmntFile`, `smIndustry`,
  `hasXbrl`, `sm_isin`.
- bhavcopy EOD zip → HTTP 200, 177,333 bytes, valid CSV.
- NIFTY 50 constituents → HTTP 200.
- **NSE historical price API → 503 on every path.** No free NSE time series.
- **BSE → entirely unreachable** (archives do not resolve; API 403).
- `yfinance` returns real Indian prices (RELIANCE.NS back to 1996) but Yahoo's ToS prohibits
  automated collection. Development and testing only.

**The distribution is itself the finding.** The six largest classes are process, not events:

    Shareholders meeting 2668 · Trading Window 1858 · General Updates 1752
    Analysts/Investor Meet 1700 · Copy of Newspaper 1415 · Updates 1035

**77% of a real Indian announcement feed contains no corporate event at all.** A system that
silently dropped them would look far better than it is; one that classified them would be
confidently wrong. They are ingested, labelled `unresolved`, and reported as their own
population. `Outcome of Board Meeting` (456, the largest event-bearing class) is also
`unresolved`, because the text often does not state the outcome.

**TRADE-OFFS.** Agreement with `desc` is agreement with the exchange's *filing* taxonomy, not
with the truth about the market. Every report says so. And `attchmntText` is a one-line summary
(median 154 characters), not the filing body — the full text is in a PDF, which this project
does not yet parse. That is a real limitation of the current evaluation.

**WHY.** The user is correct that a decision product must be trustworthy about real filings.
Measuring only on authored text measures our ability to predict our own templates.

**REVERSIBILITY.** Fully reversible. Both datasets are committed; the harness takes `--dataset`.

**FOLLOW-UP.** Parse the attached PDFs for full filing text. That is the single biggest data
improvement available and it is unblocked.

---

## D-011 — 2026-09-28 — Batching is not a performance lever on this hardware; record the negative result

**DECISION.** Do not build batched System-1 inference into the runtime. Keep single-event calls.

**CONTEXT.** `research/scripts/bench_resources.py` measured the free performance levers.

**EVIDENCE.** `Router.predict_batch` across batch sizes 1→12, on 16 vCPU with Laya resident:

| Batch | Total | Per item | Throughput |
|---|---|---|---|
| 1 | 1.943 s | 1.943 s | 0.51 items/s |
| 4 | 7.054 s | **1.764 s** | **0.57 items/s** |
| 12 | 22.217 s | 1.851 s | 0.54 items/s |

**Best case 1.10× at batch size 4.** The reason is that torch already saturates all 16 threads
on a single item, so there is no idle capacity for a batch to reclaim. Marginal cost per
question is ~0.8 s, so questions are cheap relative to re-encoding a document — which is why the
protocol puts a whole triage pass in one call.

**Corrected earlier claim.** The 280 s previously reported as "cold load" was mostly a one-time
checkpoint *download*. Load alone measured **6.6 s**. Both numbers are now reported separately
in `research/results/bench_resources.json`.

**UNMEASURED:** `onnxruntime` is not installed. Whether `laya[onnx]` export is faster on this
box is unknown and is the obvious next experiment if throughput becomes binding.

**WHY.** A negative result is worth more than a plausible-sounding optimisation. Recording "we
tried batching, it is 1.1×, here is why" stops the next engineer from spending a day on it.

**REVERSIBILITY.** Trivially reversible.

**FOLLOW-UP.** Install `laya[onnx]` and measure. If it does not help, throughput on this
hardware is what it is, and the honest answer is that the loop is not an interactive product.
