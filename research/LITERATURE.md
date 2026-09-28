# LITERATURE — does recurrent S2↔S1 coupling show measured benefit?

**Compiled:** 2026-09-28. All URLs below were fetched by me on 2026-09-28 unless stated.
**Tag legend:** `[FACT]` = verified from a primary source I fetched. `[HYPOTHESIS]` = my inference. `[UNKNOWN]` = could not verify; **not** filled from memory.

**Headline conclusion up front:** the specific paper the project brief leans on — "Talker-Reasoner (Collins et al.), which measured X and had failure modes Y" — **does not check out**. The Talker-Reasoner work is by Christakopoulou et al., is a NeurIPS 2024 workshop **poster**, is a **position paper with no benchmark**, and I could not find the alleged failure-mode analysis. The single strongest *measured* System-1/System-2 result in this set (LLM2) is a **verifier/critic**, not a non-autoregressive System-1 and not a recurrent loop. Details below.

---

## 1. The Dyadic / Talker-Reasoner line

### 1.1 What actually exists

`[FACT]` **"Agents Thinking Fast and Slow: A Talker-Reasoner Architecture"**
- Authors: **Konstantina Christakopoulou, Shibl Mourad, Maja Mataric** — *not* Collins.
- arXiv: **2410.08328**, submitted **10 October 2024**. https://arxiv.org/abs/2410.08328
- Venue: **NeurIPS 2024 Workshop on Open-World Agents, POSTER** (OpenReview forum `xPhcP6rbI4`).
  https://api2.openreview.net/notes/search?term=Talker-Reasoner&limit=5
- Subjects: cs.AI, cs.CL, cs.LG.

`[FACT]` **Only v1 exists.** The arXiv submission-history block on https://arxiv.org/abs/2410.08328 lists exactly one entry: `[v1] Thu, 10 Oct 2024 19:31:35 UTC`. `https://arxiv.org/abs/2410.08328v2` returns **404**. There is no arXiv v2 and no `comments` field (no venue note) on the arXiv record.

`[FACT]` **The abstract reports no quantitative result and no failure analysis.** Verbatim from the arXiv abstract: the authors "describe the new Talker-Reasoner architecture and discuss its advantages, including modularity and decreased latency. We ground the discussion in the context of a sleep coaching agent, in order to demonstrate real-world relevance." There is no accuracy number, no latency number, no baseline, no ablation, no dataset.

`[FACT]` **Not in the ACL Anthology.** I grepped the full volume listings `2025.acl-long` (3,702,784 bytes) and `2025.findings-acl` (3,838,241 bytes) at https://aclanthology.org/volumes/2025.acl-long/ and https://aclanthology.org/volumes/2025.findings-acl/ — zero matches for "Talker-Reasoner". The only "Talker" hit in ACL 2025 is an unrelated speech-synthesis paper, *Chain-Talker* (https://aclanthology.org/2025.findings-acl.101/).

### 1.2 Where the brief's premises fail

| Brief's claim | Verdict | Evidence |
|---|---|---|
| "Collins et al." wrote the Talker-Reasoner work | **FALSE** | Authors are Christakopoulou, Mourad, Mataric (OpenReview + arXiv, above). |
| It has "the real paper title/venue/arxiv id" | **TRUE** | arXiv 2410.08328; NeurIPS 2024 OWA Workshop **poster**. |
| "the headline quantitative result" | **DOES NOT EXIST** | The abstract has zero numbers. `[UNKNOWN]` whether the poster PDF contains measurements — I did not retrieve the PDF. |
| Failure modes: "failure to maintain self-consistency, premature termination" | **UNVERIFIED** | Not in the arXiv abstract, not in the OpenReview abstract, not in the TLDR. `[UNKNOWN]` |
| A separate "dyadic" LLM-grounding paper by Collins | **NOT FOUND** | arXiv advanced search, `terms-0-field=author`=Collins AND `terms-1-field=all`=dyadic, CS-only, returns exactly **1** hit: arXiv 2109.00861 *"User, Robot, Deployer: A New Model for Measuring Trust in HRI"* (2021) — unrelated. `terms-1-term=heartex` returns **0**. |

`[HYPOTHESIS]` The brief's "Collins et al." / "dyadic" / "failure modes" cluster is most likely a **conflation of several different papers** (there is a real "dyadic interaction" literature in computational linguistics — e.g. Pickering & Garrod 2013, *BBS*, https://doi.org/10.1017/S0140525X12001495 — but that is a human-language-production theory with no LLM System-1/System-2 architecture). **Do not cite "Collins et al." in Divya docs until someone produces a DOI or arXiv ID.**

### 1.3 Verdict on the dyadic framing
`[FACT]` The "two systems" framing in this line of work is **narrative, not measured**. It is an analogy borrowed from Kahneman used to name two modules and describe their qualitative division of labour. The one paper that is canonically attached to the name is a workshop poster arguing for the design.

---

## 2. LLM2 — the one real measured System-1/System-2 result

`[FACT]` **"LLM2: Let Large Language Models Harness System 2 Reasoning"**, arXiv **2412.20372**, submitted 28 February 2025. **Accepted to NAACL 2025 Main Conference** (per the arXiv `comments` field). https://arxiv.org/abs/2412.20372

Architecture, per abstract: an **LLM (System 1)** generates plausible candidates; a **process-based verifier (System 2)** gives process-level feedback to distinguish desirable from undesirable outputs. The verifier is trained with a **pairwise comparison loss** on synthetic process-supervision data from a "token quality exploration" strategy.

**Headline quantitative result** `[FACT]`, verbatim:
- GSM8K accuracy for **Llama3-1B: 50.3 → 57.8 (+7.5)**.
- Combined with self-consistency, **major@20: 56.2 → 70.2 (+14.0)**.

**Why this matters for Divya — and where it does not transfer:**
- `[FACT]` LLM2's System 1 is a standard **autoregressive** LLM. Its System 2 is a **trained verifier**, not a non-autoregressive typed-decision engine, and not a reasoner that plans over shared state.
- `[FACT]` The coupling is **one-directional and shallow**: the verifier scores candidates. There is **no recurrent loop** in which the verifier revises state and the generator re-plans. Divya's loop is a different (stronger) claim.
- `[HYPOTHESIS]` The transferable lesson is the **pairwise-comparison training signal over process steps**, not the System-1/System-2 naming. If Divya's Laya `choice` head is ever fine-tuned, LLM2 suggests preference-pair supervision is a working recipe for a 1B-class model.
- `[FACT]` The +14.0 gain is *with self-consistency* — i.e. the verifier composes with sampling, it does not replace it. Any Divya eval that compares against a single-shot S2→S1 call must also give the single-shot arm self-consistency, or the comparison is rigged.

---

## 3. Cascades / early-exit / FrugalGPT

`[FACT]` **FrugalGPT**, arXiv **2305.05176** (9 May 2023). https://arxiv.org/abs/2305.05176
Three strategy families: prompt adaptation, LLM approximation, LLM cascade. Headline, verbatim: FrugalGPT "can match the performance of the best individual LLM (e.g. GPT-4) with **up to 98% cost reduction** or **improve the accuracy over GPT-4 by 4%** with the same cost."
`[FACT]` The task domain is LLM **query routing / dataset annotation** (NLP datasets), not decision-making under ambiguity.

`[FACT]` **Conformal Cascade: Distribution-Free Accuracy Guarantees for Multi-Tier LLM Inference**, arXiv **2607.25018** (30 July 2026). https://arxiv.org/abs/2607.25018
- Key claim, verbatim: "**LLM confidence scores are miscalibrated**, the threshold must be tuned per model pair and per domain, and **no setting yields a formal bound on cascade accuracy**."
- Method: use **conformal prediction set size** as the deferral rule — accept when the calibrated set collapses to one answer, else defer. Gives a **distribution-free finite-sample** guarantee; per-tier union bound `1 − Kα` for any α.
- Scope: **18 multiple-choice benchmarks** (science, medicine, commonsense, exams), two-tier cascades, **four open-weight model families**.
- Result: "CC **strictly improves over the strongest calibration-tuned heuristic cascade on the majority of family–benchmark pairs**, with the **largest gains on reasoning-heavy benchmarks where majority vote is unreliable**."
- `[FACT]` Explicit limitations: "Extension to **open-ended generation** requires an answer-clustering step that we leave for future work." Requires no training, black-box API only.

`[FACT]` **Cluster, Route, Escalate: Cascaded Framework for Cost-Aware LLM Serving**, arXiv **2606.27457** (25 June 2026). https://arxiv.org/abs/2606.27457
Two-stage: cluster→cheapest capable model, then a quality-estimation cascade that escalates. Result, verbatim: "retains **97–99% of the strongest model's accuracy** while reducing Time Per Output Token (TPOT)". `[FACT]` Needs task-correctness labels; adapts to model-pool changes without reconfiguration.

**Read-across for Divya:** the cost side of the S1/S2 split is real and well-measured. Every cascade result I found measures **cost vs. accuracy on a single-shot decision** — i.e. "when to escalate." **None of them measures whether a recurrent re-plan loop beats a single-shot decision.** That is precisely the gap Divya must fill itself.

---

## 4. ATLAS — verified to exist, but it is *not* the paper the brief means

`[FACT]` **ATLAS does exist**, but as: **"ATLAS: Adaptive Trading with LLM AgentS Through Dynamic Prompt Optimization and Multi-Agent Coordination"**, arXiv **2510.15949**. Primary category **q-fin.TR (Trading and Market Microstructure)**. https://arxiv.org/abs/2510.15949

`[FACT]` It is a **trading-agent** paper, not a "System-1/System-2 for systematic decision making" paper. Core contribution is **Adaptive-OPRO**, which dynamically rewrites the agent's prompt using real-time stochastic reward feedback, so the agent can "incorporate feedback while trading."

`[FACT]` **The most decision-relevant sentence in the whole literature sweep is in this abstract**, verbatim:
> "Across regime-specific equity studies and multiple LLM families, Adaptive-OPRO **consistently outperforms fixed prompts**, while **reflection-based feedback fails to provide systematic gains**.**

`[HYPOTHESIS]` This is the single closest empirical warning to Divya's thesis. The closest thing anyone has built to "feed the model's own output back to it and let it improve" is Adaptive-OPRO (works, because it optimises the *prompt* against a measurable reward). The thing people actually build as "reflection" (re-prompt the model with its own reasoning) **failed to produce systematic gains** in that study. Divya's recurrent loop is a *typed-decision* variant of reflection. This does not refute Divya, but it means the burden of proof is entirely on Divya's own eval.

`[UNKNOWN]` A paper literally titled "ATLAS — adapting LLM for systematic decision making" — `[FACT]` **not found.** arXiv search for `ATLAS adapting large language model systematic decision making` returned exactly one hit, the q-fin.TR paper above. I did not find any ATLAS that matches the brief's description.

---

## 5. Calibrated abstention / selective prediction

`[FACT]` **Hierarchical Group-Conditional Conformal Risk Control (HG-CRC)**, arXiv **2607.24562** (27 July 2026). https://arxiv.org/abs/2607.24562
- Motivation, verbatim: marginal conformal risk control "does not imply per-group ones: a model can meet the population budget while systematically over-exposing subgroups to errors. Under mild shift in group composition, **standard CRC violates the budget in up to 47% of trials**."
- Result: HG-CRC reaches **0% empirical violation** and WGER=0 on ARC Challenge for Qwen3-4B and Llama-3.1-8B-Instruct. On MMLU-Pro "these models **abstain entirely**" (Gemma-3-4B and Llama degrade differently). Participation cost vs. global CRC: **22–37 points**.
- `[FACT]` Authors' own honesty: the 0% is an "empirical upper bound (true rate up to 0.6%), **not certified**."
- `[FACT]` Models evaluated are the *same class of small open-weight models Divya would run locally*: **Qwen3-4B, Llama-3.1-8B-Instruct, Gemma-3-4B**.

`[FACT]` **FinAbstain: Uncertainty-Calibrated Multimodal RAG for Selective Financial Forecasting**, arXiv **2607.24875** (27 July 2026). https://arxiv.org/abs/2607.24875
- Directly relevant domain. Point-in-time retriever admitting only information public at the forecast timestamp; five agents (fundamental, news, technical, risk, verification); aggregation over retrieval relevance, **evidence contradiction**, repeated-sample consistency, historical calibration stats; evaluates temperature scaling, isotonic regression, conformal prediction, and a hybrid score under a **common chronological protocol**.
- `[FACT]` **The authors explicitly refuse to report empirical numbers**: "To make the design auditable before a full data collection is complete, we report **explicitly labeled simulated results rather than empirical claims**."
- `[HYPOTHESIS]` This is the closest published template to Divya's actual problem, *and* it validates Divya's `AGENTS.md` rule 2 (label simulated data in the data, not just the docs).

---

## 6. Fast non-autoregressive / small "System-1" decision heads (2025–2026)

`[FACT]` **I found no 2025–2026 arXiv work that evaluates a non-autoregressive "System-1 model" as a decision head coupled to an LLM System-2.** Searches run 2026-09-28, all via `https://arxiv.org/search/`:
- `non-autoregressive System 1 fast decision model LLM` → **0 results**
- `non-autoregressive text classification fast head` / `... parallel decoding efficient` → **0 results**
- `System 1 model fast intuitive decision making language model 2026` → **1 result**, arXiv 2606.28971 *"Self-Evolving Agentic Image Restoration via Deliberate Planning and Intuitive Execution"* — computer vision, not decision heads.

`[UNKNOWN]` This is a **negative result from metadata search, not from full-text search.** Caveat I verified: arXiv's `searchtype=all` searches **metadata (title/abstract/authors), not full text**. A 2026 paper could exist that uses "System 1" only in its body. My conclusion is bounded accordingly.

`[FACT]` What *is* abundant in 2025–2026 is the **non-autoregressive decoding** line (diffusion LMs, parallel decoding, remasking — e.g. arXiv 2509.20744, 2510.18165, 2510.00294, 2509.24435 *survey*), and the **routing/cascading** line (§3). `[HYPOTHESIS]` Neither line, as far as I can verify, produces a **typed, calibrated, abstaining decision** — which is precisely Laya's claimed niche. There is a real gap here, but an unclaimed gap is also a signal that nobody has shown it pays off.

---

## 7. ⚠️ COMPETING HYPOTHESES — the deliverable

**The question Divya must answer with its own experiment:**
> Does the recurrent S2↔S1 loop beat a single-shot S2→S1 tool call?

**The literature predicts essentially nothing here, and that is itself the finding.** Every measured result I found (§2, §3) is a *single-shot* decision with a *routing/escalation* refinement. **No fetched paper measures recurrent re-planning over shared state against a single-shot tool call.** Divya has no prior to lean on, in either direction.

### H1 — Loop wins (Divya's thesis)
The loop helps *only* on events where the first pass is genuinely ambiguous and the second pass has **new evidence** (a contradiction detected, a missing field found, a disconfirming price action). Prediction: the gain concentrates entirely in a small ambiguous subset; on unambiguous events the loop is pure overhead.

### H2 — Loop ≈ single-shot (the null)
The loop buys latency and token cost and returns ~nothing, because Laya's contribution is *speed on easy items*, which a single-shot call already gets. Prediction: quality-parity with L1, worse p95 latency, higher token spend.

### H3 — Loop actively hurts (the failure mode)
`[HYPOTHESIS]` Backed by the strongest adjacent datum found — ATLAS 2510.15949: **"reflection-based feedback fails to provide systematic gains"** (§4). Laya's own documented weaknesses compound this: the project brief records Laya as **over-confident**, with a **`noul` (abstain) bias (issue #156)** and a **broken `act_probability` (issue #185)**. If S2 re-plans on the basis of an over-confident, miscalibrated S1 signal, the loop will **amplify** S1's errors rather than correct them. Prediction: loop accuracy < single-shot accuracy on the ambiguous subset, with the abstention rate *falling* while error rate *rises*.

### H4 — The win is calibration, not accuracy
`[HYPOTHESIS]` The recurrent loop's real value may be **confidence estimation**, not decision quality. Conformal Cascade (2607.25018) shows confidence routing is where the measurable wins are, and that raw LLM confidence is unusable ("LLM confidence scores are miscalibrated"). A loop that re-asks on disagreement produces an **ensemble/disagreement signal** usable for conformal abstention — a win that shows up in ECE and risk–coverage, not accuracy.

### What measurement would distinguish them

| # | Measurement | H1 predicts | H2 predicts | H3 predicts | H4 predicts |
|---|---|---|---|---|---|
| 1 | Accuracy: L2 loop vs L1 single-shot, **split by ambiguity stratum** | big gain on ambiguous, ~0 on clear | ~0 everywhere | negative on ambiguous | ~0 on accuracy, both arms |
| 2 | **Disagreement-triggered subset only** (S2 changed its mind after an S1 call) | this subset carries the whole gain | indistinguishable from random | worse than the no-disagreement subset | — |
| 3 | Brier + ECE on S1 confidence | loop slightly worse (extra noise) | ~same | **materially worse** | **materially better** |
| 4 | Risk–coverage / AURC at the abstention threshold | ~same coverage, better error | ~same | abstains *less* and errs *more* | best error at matched coverage |
| 5 | p95 latency + total tokens | clearly worse | worse | worse | worse |
| 6 | **Laya-alone and S2-alone arms** (the A/B/C arms in `plan.md` P7) | S2-alone ≈ L1; S1-alone well below; gain only when both present | S2-alone ≥ loop | S1-alone poisons the loop | — |
| 7 | Max-iteration / non-convergence rate | low | n/a | **high** — the loop spins | low |

### Design requirements I would insist on (from §2, §5, §7)
1. `[FACT]` **The L1 single-shot arm must get self-consistency** if the L2 arm is allowed to iterate. LLM2's headline gain (+14.0) is *with* self-consistency; without controlling for it, any loop-vs-single-shot result is confounded by sample count.
2. `[FACT]` **Report ECE and risk–coverage, not just accuracy.** Per 2607.25018 and 2607.24562, a cascade/abstention system that reports only accuracy is uninterpretable.
3. `[FACT]` **Evaluate per-group.** 2607.24562 shows standard CRC violates its budget in up to 47% of trials under mild group-composition shift. Divya's event strata (earnings / actions / filings) are exactly such groups.
4. `[HYPOTHESIS]` **Pre-register the ambiguity split.** If the ambiguous subset is defined after seeing results, H1 is unfalsifiable.
5. `[FACT]` **Do not claim convergence from a position paper.** Talker-Reasoner (2410.08328) is the citation most people will reach for to justify this architecture, and it contains no measurement at all. Citing it as support for a *measured benefit* is a citation error.

---

## 8. Open questions I could not close

- `[UNKNOWN]` Whether the Talker-Reasoner poster PDF (OpenReview `xPhcP6rbI4`) contains any experiment. I read the abstract + TLDR only. **Worth 10 minutes to open** https://openreview.net/forum?id=xPhcP6rbI4 before finalising the literature claim.
- `[UNKNOWN]` Whether a "Collins et al." dyadic LLM-grounding paper exists outside arXiv CS. DBLP was Anubis-bot-walled, Semantic Scholar was hard rate-limited (HTTP 429 from a shared IP), ACL Anthology search is Google-CSE-driven and JS-only, and Bing returns JS-rendered results. **These three bibliographic sources are the gap.**
- `[UNKNOWN]` Full text of the 2026 cascade/conformal papers. All numbers above are from abstracts, which for these papers are unusually quantitative — but I have not read the experimental sections, sample sizes, or confidence intervals.
- `[UNKNOWN]` Laya's own measured characteristics. Nothing in this sweep independently verifies the brief's Laya numbers (33 ms/q T4, 193–464 ms CPU, 0.362 base / 0.766 fine-tuned accuracy). Those remain `[?]` pending `research/scripts/bench_laya.py`.

## 9. Tooling notes for whoever refreshes this file
- `https://export.arxiv.org/api/query` returns **HTTP 406** from this host. Use `https://arxiv.org/search/?query=...&searchtype=all` (works) or `https://arxiv.org/abs/<id>`.
- arXiv `searchtype=all` is **metadata-only**, not full text. Author-filtered queries need `https://arxiv.org/search/advanced` with `terms-0-field=author`.
- dblp.org is behind Anubis ("Making sure you're not a bot!"); api.semanticscholar.org returns 429 on unauthenticated shared IPs; aclanthology.org search is JS-rendered. **OpenReview's api2 and the ACL Anthology volume pages are the reliable bibliographic routes.**
