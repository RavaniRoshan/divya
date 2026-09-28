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
