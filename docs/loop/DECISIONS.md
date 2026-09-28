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

---

## D-012 — 2026-09-28 — The recurrent loop is not the product default; System-1 alone is

**DECISION.** The default runtime is **arm A: System-1 alone**. System-2 remains configurable
and fully implemented. The recurrent loop (arm D) is retained as a tested, traced, selectable
mode — it is the control that produced the result — but it is **not** the default and it is not
what the product recommends.

**CONTEXT.** E-009 measured all four arms on 120 real NSE announcements, paired, same process,
same checkpoint. Full table in `docs/research/UNIFICATION_EXPERIMENTS.md` §E-009.

**RESULT.**

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | Abstain |
|---|---|---|---|---|---|---|
| A S1 alone | 0.558 | 0.436 | 0.096 | 0.240 | **4.7 s** | 0.0% |
| B S2 alone | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 0.0% |
| C S2→S1 | **0.558** | 0.436 | 0.096 | 0.240 | 19.0 s | 0.0% |
| D recurrent | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | **75.8%** |

Two independent findings:
1. **A and C are identical to the decimal** — accuracy, macro-F1, ECE, AURC all equal. The
   reasoning layer contributes *zero* while costing 4.0× latency and 1079 prompt tokens per event.
2. **D is worse than C** (−0.050 accuracy, worse on `clear` and `noisy`, tied on `ambiguous`) at
   8.5× arm A's latency, 2.57 System-1 calls per event, and a 75.8% abstention rate that scores
   the abstained events wrong.

Hypothesis verdicts: **H1 rejected, H2 rejected, H3 supported, H4 not supported** (D's ECE is
marginally better but its AURC is worse; the ECE gain is an artifact of abstaining more, not of
better-ordered confidence). H3 is also what the external literature predicts — ATLAS
(arXiv 2510.15949) reports reflection-based feedback fails to give systematic gains.

**TRADE-OFFS.** This is the project declining its own thesis on its own evidence. The
sophisticated architecture is fully built, fully tested, and fully documented — and it is not
recommended, because the measurement says so. Shipping arm A as the default is the honest
choice even though it makes the product simpler than the PDR described.

**WHY.** The mission is explicit that a strong product with documented limitations beats a false
claim, and that complexity must produce measurable value. Here it demonstrably does not.

**REVERSIBILITY.** Fully reversible. The loop is a runtime flag (`--max-turns`, `allow_escalation`),
not a rewrite. If a stronger System-2 is later available, re-run E-009 and revisit.

**FOLLOW-UP EXPERIMENT (highest value in the project).** The failure is *not uniform*: two
classes score **F1 = 0.00** (`capital_action` n=13, `regulatory_action` n=17) while
`credit_rating` scores 0.94 and `leadership_change` 0.88. The confusion matrix shows `other`
acting as an attractor for uncertainty — `capital_action` goes to `other`/`fundraise` 13/13,
`regulatory_action` to `other`/`capital_action` 16/17, and `other` itself has precision 0.29
while absorbing 27 misclassifications. **Removing `other` from the option set** is the single
clearest experiment available and could change these numbers substantially.

---

## D-013 — 2026-09-28 — Levels 3 and 4 are declined

**DECISION.** System-2 fine-tuning for the Laya interface (Level 3) and any model fusion
(distillation, shared latents, joint optimisation — Level 4) are **not built**.

**CONTEXT.** The phased plan made Level 3 conditional on the P7 evaluation justifying it. E-009
does not justify it: the untrained reasoning layer contributes nothing, and the recurrent loop
it would be trained to drive is measurably *worse* than the single-shot path it would replace.

**EVIDENCE.** D-012. Training a specialised System-2 to operate better with a loop that
demonstrably degrades results would be optimising a premise the experiment just rejected.

**WHY.** "Do not introduce complexity because it sounds state-of-the-art. Complexity must produce
measurable value." There is no measured value to optimise here, and building Levels 3–4 would
have consumed the remaining effort while producing no evidence about the actual question.

**REVERSIBILITY.** Reversible in principle — the protocol, state, and provider interface are all
in place. Declining is the right call *now*, and the decision is recorded so it can be revisited
against evidence rather than inertia.

**FOLLOW-UP.** Revisit only if (a) a stronger System-2 becomes runnable on this hardware class,
or (b) the `other`-attractor fix materially changes the picture.

---

## D-014 — 2026-09-28 — One model per role; a superseded model gets deleted, not kept "just in case"

**DECISION.** Exactly one System-1 checkpoint and one System-2 model are kept. Any model that a
measurement has ruled out is deleted, and any package installed outside `pyproject.toml` and
imported by nothing is uninstalled.

**CONTEXT.** During the sizing experiment I pulled a second reasoning model to compare, plus a
research agent installed `yfinance`/`pyarrow` to test a data source. All of it stayed on disk
after the question it answered. That is ~2.7 GB of nothing.

**REMOVED.**
- `qwen3:4b` (2.5 GB) — D-009 measured it at 42–64 s warm against `qwen2.5-coder:3b`'s
  0.56–0.91 s, with only 1.3–2.2 s of that being generation. The rest was memory thrash. It is
  the *documented reason* the default is 3B; keeping it contradicts the project's own finding.
- `yfinance` + `pyarrow` + `curl_cffi` (~195 MB) — installed by a research probe to verify a
  data source. Not in `pyproject.toml`, imported by no product code. Removing them makes the
  working venv match what a clean clone produces, which is the point of having a lockfile story.

**KEPT.** `qwen2.5-coder:3b` (1.9 GB) — the default System-2. Laya `english` (248 MB) — the only
System-1 checkpoint ever fetched; Laya's router downloads on demand and only the english one was
ever requested, so `multilingual` and `typed-decisions` were never pulled.

**RULE going forward.** A model earns its place by being used. If an experiment needs a second
model, it is deleted when the experiment ends unless the result changed the default. Documented
here because "we might need it later" is how a research box quietly becomes 40 GB.

**REVERSIBILITY.** Fully reversible — `ollama pull qwen3:4b` restores it in minutes. Nothing in
the code references a model that is no longer present; `divya doctor` warns when the configured
model is not pulled, so a missing one is diagnosed rather than mysterious.

---

## D-015 — 2026-09-28 — The A-vs-D difference is significant, and the mechanism is narrow

**DECISION.** Record H3 as **supported on tested evidence** rather than asserted, and correct
the per-class failure count.

**CONTEXT.** The independent review was right that "H3 SUPPORTED" was an assertion over six net
items. Phase 7 requires a claim to be falsifiable, and an untested difference is not a finding.

**METHOD.** `src/divya/eval/significance.py`, computed from the raw artifact with nothing
hardcoded from the reported numbers. Two tests answering different questions: McNemar's **exact**
test on the discordant pairs (exact rather than chi-square, because with six discordant
observations a normal approximation would report a p-value as though it were sixty), and a
**seeded** paired bootstrap resampling *events* — one event yields several decisions, so
resampling within an event would understate the variance.

**RESULT.**

| Quantity | Value |
|---|---|
| n | 120 paired events |
| accuracy A / D | 0.5583 / 0.5083 |
| difference (D − A) | **−0.0500** |
| both correct / both wrong | 61 / 53 |
| **only A correct / only D correct** | **6 / 0** |
| McNemar exact | **p = 0.0312** |
| bootstrap 95% CI | **[−0.0917, −0.0167]**, excludes zero |
| P(Δ < 0) | 0.9984 |

**WHY IT IS SIGNIFICANT DESPITE ONLY SIX DISCORDANT PAIRS:** all six go the same way. A 6–0
split has probability (1/2)^6 = 0.0156 one-sided. The loop **never once fixed an error the
single-shot path made, and broke six correct answers**. That is a much sharper statement than
"D scored lower", and it is the honest description of what happened.

**A NUMBER THAT WAS WRONG.** The agreement matrix shows **three** classes at zero accuracy, not
two: `capital_action`, `fundraise` **and** `regulatory_action`. And **36** errors land on `other`,
not 27. The `other`-attractor diagnosis is unchanged in direction and larger than previously
stated.

**TRADE-OFFS.** n=120 with 6 discordant pairs is a small experiment. p = 0.0312 is not a
comfortable margin, and this says nothing about a stronger System-2 or a different protocol.
It says D was worse *here*.

**REVERSIBILITY.** Fully reproducible from the committed artifact; re-running it after a new
evaluation updates the conclusion automatically.

**FOLLOW-UP.** The bootstrap is the number to quote. If a future run produces a CI spanning
zero, the correct statement is "not resolved", and `report()` says exactly that.

---

## D-016 — 2026-09-28 — Full filing text from the PDF, not the one-line summary

**DECISION.** Decisions are made on text extracted from the announcement's attached PDF, with
the `attchmntText` summary as a labelled fallback.

**CONTEXT.** Blocked item B-004. NSE's API returns only a summary; the filing is in the PDF.

**EVIDENCE.** Measured on live filings, 2026-09-28: **105 → 3,770 characters (35.9×)** on one
event, 4.5×–33× across a sample. Median `attchmntText` across the September 2026 feed is
**154 characters**.

**WHY THIS IS THE LARGEST QUALITY LEVER AVAILABLE.** A materiality judgement needs figures —
amounts, percentages, share counts — and summaries routinely omit them. Every evaluation run
before this point measured the system on text that cannot support the decision it was being
asked to make. The reported 0.558 is a number about summaries.

**DESIGN.** Fetch PDF → extract with `pypdf` → strip the exchange address block → cache by the
exchange's own `seq_id`. Three failure modes handled explicitly rather than discovered later:
**no text layer** (many Indian filings are scanned images; treated as a failure, never as an
empty document, because "nothing to decide" reported as a finding is the worst outcome
available), **boilerplate** (removed as the most expensive and least informative text in the
document), and **fetch cost** (cached, so a filing is downloaded at most once).

**NOT DONE DELIBERATELY.** Stored decisions are not recomputed when a filing is upgraded.
Changing the text a decision was made on, after the fact, would make that decision a lie.
Re-decide explicitly.

**THREE BUGS FOUND BY TESTING THE STRIPPING RATHER THAN EYEBALLING IT.**
1. Patterns anchored on `"To,"` missed the header whenever the filing date sat between them,
   which is the normal layout. They now match the address landmarks directly.
2. The postcode pattern did not match `"Mumbai - 400 001"`, so BSE headers survived intact.
3. The over-strip guard was an absolute 200-character threshold and rejected valid short
   filings unmodified; changed to a 50% ratio it then rejected filings where the address
   genuinely is most of the text. Only catastrophic removal triggers it now.

**FOLLOW-UP.** Re-run E-009 on the enriched dataset and report whether 0.558 and the three
zero-F1 classes change. That is the experiment this enables.

---

## D-017 — 2026-09-28 — The terminal ships; the store is append-only and immutable

**DECISION.** Build the P9 terminal as a Textual TUI over a SQLite store, and keep
`terminal/view.py` as the separate audit path.

**CONTEXT.** Phase 9 asked for an event stream, company state, event history, decision state,
confidence, evidence, a "why" interface, freshness, model/version information and keyboard-first
interaction. What existed covered decision state for a single run and none of the rest.

**DESIGN.** `src/divya/data/store.py` persists events, runs, decisions and disagreements.
**Decisions are append-only and immutable**: a protocol change produces a new row with a new
version and both stay visible. Overwriting history would destroy the only thing that makes a
calibration claim checkable. **Freshness is a query, never a stored flag** — a row written a week
ago is stale now and no column can change that.

`src/divya/terminal/app.py` gives every pane a reason to exist: the status bar always carries
data age, the System-1 state and the model id, and `w` swaps the decision pane between raw
System-1 output and the system's interpretation. The two must never be confusable, because that
is this project's entire claim.

**WHY A TUI AND NOT JUST THE EXISTING RENDER.** `view.py` renders one decision and produces a
file you can diff and paste into an issue. That is the *audit* path and it is kept. A working
terminal needs a working terminal. Both call the same `divya` modules, so there is no second
implementation of the product logic to drift.

**VERIFIED END TO END.** A live NSE filing (AIIL, "Appointment") selected in the stream, decided
with the real engine in 11,093 ms, `event_type leadership_change` at P=0.99, four decisions
persisted, raw and interpreted views both rendered, then read back from the store.

**FOUR BUGS FOUND BY DRIVING IT RATHER THAN READING IT.** Duplicate widget ids; a `str`/`int`
comparison in the freshness path that silently aborted every key handler; `str.join` given
multiple arguments; and `asyncio.run()` nested inside Textual's own event loop. 20 headless
tests now cover mounting, navigation clamping, filtering, the raw/interpreted toggle, freshness
and simulation labelling, and the decide path.

**REVERSIBILITY.** The store is a single SQLite file; deleting it loses only derived state, and
re-fetching rebuilds it from the exchange.

---

## D-018 — 2026-09-28 — The red team is shipped as a test suite, not a report

**DECISION.** `python -m divya.eval.redteam` is a runnable suite that exits non-zero on any
failure, and `docs/loop/REDTOOM.md` is its written report.

**EVIDENCE.** 43 cases across 7 classes, run against the real runtime and — for the injection
class — the real Laya engine. **15 defects found. All 15 fixed. Suite now 43/43.**

**THE ONE THAT MATTERED.** A prompt injection worked. 87 characters appended to a 220-character
dividend filing flipped `event_type` from `earnings_result` (0.973) to `other` (0.652). There
was no sanitisation layer at all.

**WHAT WORKED AND WHAT DID NOT.** Defanging the injected JSON's *keys* did not stop it — a 421M
encoder follows an instruction whether or not it is well-formed JSON. What worked was
**redacting the instruction text itself**, plus stripping control markup and zero-width
characters. This is not a solved problem and `sanitize.py` says so: a defence is only as good as
the test that tries to break it, which is why the suite is committed and runnable rather than
described.

**THE OTHER 14, in one line each.** Contradictory observations were silently concatenated
(`Contradiction` existed from day one and nothing called it). Duplicates multiplied what System-1
read. A future timestamp and an unparseable timestamp both read as **fresh**. A raising System-1
escaped the loop, breaking the totality guarantee `UNIFIED_MODEL.md` claims. `system2_timeout_s`
was not the bound. The heuristic path never ran the ingestion canary. Lone surrogates crashed
`Observation`.

**THE TWO-DIGEST DECISION.** The state now carries `content_hash` over the **exact** bytes
(provenance — a trace must prove what was actually decided on) and `dedup_key` over the
whitespace-normalised form (cost — a feed that re-emits one filing with different wrapping is
still one filing). One hash cannot honestly be both, and the red team asserted both properties.

**FOUR TESTS ASSERTED THE OLD BROKEN BEHAVIOUR** and failed once fixed. All four are now
regression tests for the fix. One of them carried its own instruction to *"update this
deliberately rather than by accident"* when the fix landed.

**STATED PLAINLY: this is not a security audit, and no claim is made that the system is secure.**
It is a suite of 43 specific attacks, 7 of which ran against the real engine and one of which
found a real hole. An adaptive adversary who reads `sanitize.py` will find a gap.

---

## D-019 — 2026-09-28 — Space UI is the frontend foundation, and the data grid is deliberately not used

**DECISION.** Build the web frontend on Space UI. Build the event stream on Space UI's `table`
primitive rather than its composite `data-grid`. Remove `data-grid` from the tree.

**CONTEXT.** The brief requires Space UI as the foundation and forbids guessing the stack.

**STACK VERIFIED, NOT ASSUMED.** A research agent fetched spaceui.one's own JS chunks and
recovered the inventory. Space UI is a **shadcn-compatible registry at
`https://www.spaceui.one/r/{name}.json`** with **252 items** — 60+ primitives, 60+ composites,
50+ hooks, plus `lib-base-ui`. There is **no `spaceui` npm package**; `spaceui`,
`@space-ui/react` and `@spaceui/react` all 404. There is no index endpoint —
`/r/registry.json` returns a Next.js 404 page with HTTP 200.

Confirmed and installed: **React 19.2.8 · Next.js 16.3.6 · Tailwind v4 (CSS-first) ·
`@base-ui/react` ^1.8.0 · `motion` 13.4.4**. Note it is `@base-ui/react`, **not**
`@base-ui-components/react`. Install is
`pnpm dlx shadcn@latest init https://www.spaceui.one/r/lib-style.json` then
`pnpm dlx shadcn@latest add @spaceui/primitives-table --yes --overwrite` — the namespace is
doubled-prefix, and Space UI's own docs showing `@spaceui/dialog` are wrong.

**TWO UPSTREAM DEFECTS FOUND, BOTH WORKED AROUND.**

1. `lib-style.json` emits `--ring: var(--ring)` inside `@theme inline`, which shadcn's base
   layer then `@apply`s as `outline-ring/50`. **Every page 500s on a clean install.** Fixed to
   `--color-ring: var(--ring)`. Anyone installing Space UI hits this.
2. `components-spaceui-data-grid` depends on `@tanstack/react-table` and the registry resolves
   **v9** — a full rewrite (`useTable`, feature-based `createColumnHelper`, `flexRender`). The
   component is written against v8 and produces 8 type errors on import.

**WHY THE DATA GRID IS NOT USED.** Writing a correct integration against a table API this
project has not verified would mean shipping code nobody could check. The event stream uses
Space UI's own `table` primitive — a verified component in the same design system — which gives
a sticky header, tabular numerals, dense rows and sort affordances. **Given up:** column resize,
column pinning, server pagination. **Kept:** everything a 200-row feed needs. The trade-off and
the condition under which it stops being right are written into the component's docstring, not
just here. The broken component was deleted rather than left in the tree.

**REVERSIBILITY.** Reversible. Swapping the table primitive for a working grid is a single
component's worth of work and no protocol change.

**FOLLOW-UP.** If a registry update fixes the v9 incompatibility, re-evaluate — a virtualised
grid matters at terminal row counts and not yet here.

---

## D-020 — 2026-09-28 — The language model emits typed UI intents and never renders

**DECISION.** System-2 may choose *which* workspace is appropriate. It may not choose what the
workspace looks like, and it emits no code. The intent enum is closed.

**CONTEXT.** The brief requires a conversational control surface and dynamic workspaces, and
warns against the model emitting arbitrary frontend code.

**DESIGN.** `src/divya/runtime/intents.py` defines a closed `WorkspaceKind` enum mapped from the
prescribed intents (`SHOW_COMPANY`, `SHOW_COMPARISON`, `SHOW_EVENT_STREAM`, `SHOW_SCREEN`,
`SHOW_FILING`, `SHOW_TIMELINE`, `SHOW_FINANCIALS`, `SHOW_DECISION_TRACE`, `SHOW_EVIDENCE`,
`SHOW_ALERTS`, plus investigation and event). `src/lib/divya-types.ts` mirrors it as a
TypeScript discriminated union, so the frontend **cannot render an intent outside the union** —
it is a type-system boundary, not a runtime lookup.

**WHY THIS IS A SECURITY BOUNDARY, NOT A STYLE CHOICE.** Document text is attacker-influenced,
and the red team already demonstrated a working prompt injection against the real engine. If
the model's output selected a component or a route, that text would be one prompt away from
choosing what the user sees. A closed enum makes the view layer unreachable from document
content.

**CONSEQUENCE FOR BUILDERS.** Each intent's payload is built by a human-written constructor
(`intents.company()`, `intents.comparison()`, …) that returns a typed `EMPTY` note rather than
an unrenderable empty workspace. An intent that cannot be filled is a result the frontend can
display, not a bug report.

**WHAT THE UI REFUSES TO DO**, each a deliberate and previously-wrong choice:
- undecided events sort **last**, not first — an unjudged event is not top priority;
- no number renders without its retrieval time — freshness travels with the data;
- the reasoning model's prose is never displayed as a confidence — confidence comes from the
  typed engine or not at all.

---

## D-021 — 2026-09-28 — Protocol v3: split determinability out of the classification head

**DECISION.** `event_triage` v2 → v3. `other` is **removed** from the `event_type` choice head
(10 options → 9), and a new tier-1 `noul` — `event_type_determinable` — gates it. A document
with no classifiable corporate event is answered by the gate, not by a catch-all class.

**CONTEXT.** The E-009 agreement matrix localised the failure rather than spreading it evenly:

| class | n | P | R | F1 |
|---|---|---|---|---|
| credit_rating | 8 | 0.89 | 1.00 | 0.94 |
| leadership_change | 43 | 1.00 | 0.79 | 0.88 |
| m_and_a | 14 | 1.00 | 0.50 | 0.67 |
| **other** | 18 | **0.294** | 0.83 | 0.43 |
| capital_action | 13 | 0.00 | 0.00 | **0.00** |
| fundraise | 5 | 0.00 | 0.00 | **0.00** |
| regulatory_action | 17 | 0.00 | 0.00 | **0.00** |

**Three** classes at exactly zero, and the confusion matrix shows why. `capital_action` goes to
`other`/`fundraise` **13 of 13**; `regulatory_action` to `other`/`capital_action` **16 of 17**.
`other` itself has precision **0.294** (TP 15, FP 36) — it is not a class the engine uses, it is
**where uncertainty goes**.

**WHY A GATE RATHER THAN JUST DELETING `other`.** Deleting the option without a gate would force
the engine to pick the least-wrong class when the honest answer is "I cannot tell" — replacing
a visible uncertainty with a confident error. The gate makes "not determinable" a first-class
answer produced by its own decision. The cost is stated in the protocol: the classification head
can no longer be right by elimination, only by evidence.

**SECONDARY BENEFIT, VERIFIED.** Nine options lands in Laya's `choice:6-10` bucket, whose fitted
temperature is **1.0** — valid. v2's ten options were also in that bucket, so this change is
about semantics rather than calibration, but it keeps a margin below the invalid `choice:11+`
boundary instead of sitting one option from it.

**THIS IS A HYPOTHESIS, NOT A RESULT.** The matrix above motivates it; only a re-run of E-009
on v3 shows whether it works. The expected effect is that `capital_action` and
`regulatory_action` stop collapsing into `other` — and the risk is that forcing a choice makes
them wrong *somewhere else* instead, which the same re-run will show.

**ALREADY FOUND BY MAKING THE CHANGE.** The red-team stub hardcoded a fallback answer of
`"other"`, which no longer exists. It raised `KeyError`, produced no answer at all, and the
suite reported the symptom as *a missing answer* rather than *a broken stub*. Fixed: the stub
now derives its winner from the options the protocol actually defines and treats "no trigger
matched" as a normal outcome. Suite back to 43/43.

**REVERSIBILITY.** Reversible — v2 is in git history and `check_migration` reports the change.
Decisions recorded under v2 carry `spec=event_triage@2` and are distinguishable.

**FOLLOW-UP.** Re-run E-009 on v3 against the same 120 items and the same labels. The
comparison is paired, so any movement is attributable to the protocol change and nothing else.

---

## D-022 — 2026-09-28 — Full filing text fixes the broken classes and breaks one; the loop collapses

**DECISION.** Report the result in full, including the per-class detail, and do not ship a
single headline number for it.

**RESULT.** The identical A/B/C/D run on the same 120 filings, same labels, same protocol
(v2), with the *only* difference being that 107 of 120 items now carry the real PDF text
instead of a one-line summary — **25.3× more text**.

| arm | accuracy (summary → filing) | Δ | ECE | AURC | p95 latency |
|---|---|---|---|---|---|
| A System-1 alone | 0.558 → **0.475** | **−0.083** | 0.096 → 0.141 | 0.240 → 0.356 | 4.7 s → **57.7 s** |
| C System-2 → System-1 | 0.558 → 0.475 | −0.083 | 0.096 → 0.141 | 0.240 → 0.356 | 19.0 s → 48.8 s |
| D recurrent | 0.508 → **0.142** | **−0.367** | 0.080 → 0.058 | 0.260 → **0.649** | 40.4 s → **90.0 s** |

**The aggregate says accuracy fell 8 points. The per-class table says something else entirely:**

| class | n | F1 summary → filing | |
|---|---|---|---|
| earnings_result | 4 | 0.33 → **0.80** | fixed |
| capital_action | 13 | **0.00 → 0.39** | **fixed from zero** |
| regulatory_action | 17 | **0.00 → 0.30** | **fixed from zero** |
| m_and_a | 14 | 0.67 → **0.13** | **badly regressed** |
| leadership_change | 43 | 0.88 → 0.70 | regressed |
| credit_rating | 8 | 0.94 → 0.94 | unchanged |

**The three classes that were structurally broken now work.** Two of them went from *exactly
zero* to a usable score, because the summary omitted the figures and the subject that identify
the event — which is exactly the mechanism `other` was exploiting. That is the single largest
quality movement in the whole project.

**One class broke badly**: `m_and_a` 0.67 → 0.13. On real acquisition filings the engine now
has enough text to be confidently wrong, where on summaries it was falling through to the
correct answer by accident. A 14-item class moving 0.67 → 0.13 costs more aggregate accuracy
than three classes moving off zero gains.

**AND THE LOOP STOPS WORKING AT ALL.** Arm D falls to **0.142** with AURC 0.649 on real
documents, against 0.508 on summaries. The recurrent loop was already the worst arm; with
25× more text per document it becomes unusable, and its p95 crosses 90 seconds. **The negative
result on the loop is not an artefact of short documents — it is worse on real ones.**

**CONSEQUENCES, STATED PLAINLY.**

1. The headline 0.558 in `STATUS.md` and the README **describes a system reading one-line
   summaries.** That number should not be quoted without this beside it. It has been added to
   `EVALS.md` and flagged in both.
2. **Latency is the binding constraint, not accuracy.** 4.7 s → 57.7 s for one item is the price
   of the full text, and it is 12×. Anything interactive needs a length budget or a two-stage
   read (classify on the summary, then re-read the filing for the ambiguous minority) — the
   second is the obvious next experiment and is *not* built.
3. **The `m_and_a` regression must be diagnosed before v3 ships.** It may be a real limitation,
   or it may be the same catch-all problem reappearing. Both are consistent with the data.
4. Neither this nor the previous run used **protocol v3**, because the run began before the
   change. D-021 is still unvalidated.

**COST OF KNOWING.** This run took **2 h 35 m** on 16 vCPU against summaries' ~25 m. The
information is worth it and it is not cheap; any further full-text run should be a subset.

---

## D-023 — 2026-09-28 — One Laya process at a time, enforced

**DECISION.** `research/scripts/with_laya_guard.sh` takes an exclusive lock before any command
that loads the checkpoint, refuses to start a second one, and caps torch to 8 threads.

**CONTEXT.** This session was killed once by an OOM, and the cause was mine: a background
evaluation holding one Laya process (2.8 GB resident) while I started several more Laya
processes to test things alongside it, on a 7.5 GiB box that is also running another agent
session. The failure mode is nasty — the process vanishes mid-run with no traceback, and two
hours of evaluation disappear with it.

**WHAT THE GUARD DOES.**

1. **Exclusive lock.** `flock` on `/tmp/divya-laya.lock` for the command's lifetime. A second
   Laya process is **refused** (exit 75) rather than started. Refusing is the point: the
   alternative is being OOM-killed and losing the run.
2. **A memory floor.** Refuses to start if `MemAvailable` is under 2500 MiB, so the checkpoint
   cannot be loaded into a box that cannot hold it.
3. **Bounded threads.** `OMP_NUM_THREADS=8` rather than 16. A 421M model on 16 vCPUs otherwise
   takes every core and starves the Ollama server, which presents as a hang even when it is only
   contention. This is a distinct failure from the OOM and the guard prevents both.

**THE RULE FOR WORKING, NOT JUST THE TOOL.** While an evaluation is running, do **non-Laya**
work — tests, documentation, code review, analysis. Do not start a second Laya process "just to
check something", because that is exactly what killed this session. The two are not independent:
a 2.5-hour evaluation is not worth restarting because a one-line check was convenient.

**WHY A SCRIPT AND NOT A DISCIPLINE.** The discipline was already stated and was already
violated, twice, by the same agent that wrote it down. A rule that is not enforced by the
environment is a note, and this one had to become a gate.
