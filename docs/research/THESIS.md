# THESIS.md — what exactly are we building, and what would disprove it?

_2026-09-28. This document exists because the honest answer to "is this architecture worth
building" was **no**, and the project only became worth continuing by measuring that.*

---

## 1. What exactly are we building?

Not a stock dashboard with AI. Not a chatbot for stocks. Not "an LLM that calls a tool."

**A conversational market-intelligence terminal whose control surface is natural language and
whose output surface is a dynamic analytical workspace.**

The user expresses analytical *intent*. The internal cognitive system decomposes it, decides
which typed decision operations are required, performs them through the fast decision engine,
assesses whether the evidence is sufficient, and constructs the appropriate workspace. The user
then continues the same investigation conversationally — the task state persists, so "show me
the evidence" is a continuation, not a new question.

From the user's side: **one analytical intelligence**. They never choose which model did what.

---

## 2. The System-1/System-2 thesis

> A specialised System-2 language model and a fast System-1 decision model can be architected
> into a single inference architecture in which both continuously exchange structured state
> through a recurrent interaction protocol.

**The specific claim, stated so it can fail:** *the recurrent loop produces better decisions than
a single-shot System-2 → System-1 tool call, at an acceptable cost.*

**The evidence says no.** On 120 real NSE announcements:

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | Abstain |
|---|---|---|---|---|---|---|
| **A** System-1 alone | **0.558** | 0.436 | 0.096 | **0.240** | **4.7 s** | 0.0% |
| **B** System-2 alone † | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 0.0% |
| **C** System-2 → System-1 | **0.558** | 0.436 | 0.096 | **0.240** | 19.0 s | 0.0% |
| **D** recurrent loop | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | **75.8%** |

† arm B is a **failed arm** — 0 of 120 items produced any answer.

Two results, and the second is the important one:

1. **A and C are identical to the decimal** on accuracy, macro-F1, ECE *and* AURC. The reasoning
   layer contributed *exactly zero* while costing 4× the p95 latency and 1079 prompt tokens.
2. **D is worse than C**, and the mechanism is specific: paired per item, **A is right and D is
   wrong on 6 items; D is right and A is wrong on 0.** The loop never once fixed an error the
   single-shot path made, and it converted six correct answers into wrong ones by re-asking
   System-1 and getting different, worse results.

That is significant, not noise: McNemar exact **p = 0.0312**, paired bootstrap 95% CI
**[−0.0917, −0.0167]**, P(Δ<0) = 0.9984. It is significant despite only six discordant pairs
because all six go the same way.

**H3 is supported. H1 (loop helps) and H2 (loop ≈ single-shot) are rejected.**

---

## 3. What is different from a normal AI agent?

A normal agent has a language model that calls tools and writes prose. Divya is different in
three specific, testable ways:

1. **The fast engine answers structured questions, not prompts.** System-1 returns typed
   `choice` / `score` / `noul` values with a full probability distribution. It cannot write
   prose. That constraint is what makes its output auditable.
2. **The reasoning model's prose is never load-bearing.** System-2 emits one of three typed
   turns — `call_system1`, `finish`, `abstain`. Its rationale is written to the trace and never
   read back. A model that cannot phrase an answer cannot smuggle one.
3. **The reasoning model cannot overwrite the fast engine.** `System1Record` is a frozen model
   holding request, raw payload and parsed answer as three separate fields. Disagreement is a
   *separate object*. Overriding is not discouraged — it is unrepresentable.

A normal agent fails open when it is unsure. Divya fails **closed**: `abstain` is a first-class
outcome and a terminal that shows "I cannot tell" is working correctly.

---

## 4. What is different from a normal financial dashboard?

A dashboard shows a fixed set of charts the designer chose. Divya **constructs** the workspace
from the task. The backend emits a typed UI intent (`SHOW_COMPANY`, `SHOW_COMPARISON`,
`SHOW_SCREEN`, `SHOW_DECISION_TRACE`, …) and the frontend renders the corresponding workspace
from structured state. The language model never emits HTML or code.

The practical consequence: "What changed across the Nifty 50 today?" produces a ranked event
table; "Why is HDFC highest priority?" transforms the *same task state* into a focused
investigation workspace. No navigation model was written for either.

**Every view carries its evidence.** Not a "see more" link — the source, the retrieval time, the
raw decision, the confidence, the model version, and the freshness, on screen with the
conclusion.

---

## 5. What is different from a normal chatbot?

A chatbot is a text box. Divya's conversation is the *control layer* of an analytical
instrument, and it has state.

- **The task persists.** "Compare HDFC and ICICI" → "now only asset quality" → "show me the
  evidence" is one task with three turns, not three questions.
- **The output is a workspace, not a paragraph.**
- **The model never invents a number or a citation.** If System-2 states a figure, that figure
  came from a System-1 answer or a source document, and the trace proves which.

---

## 6. What must be true for this to work?

Stated as falsifiable conditions, each with its current status.

| # | Condition | Status | Evidence |
|---|---|---|---|
| 1 | The fast engine is a real, capable, permissively-licensed artifact | **TRUE** | `laya` 0.3.21, Apache-2.0, verified from PyPI + source |
| 2 | It is fast enough to be worth calling repeatedly | **MARGINAL** | 1138 ms/question on CPU — cheap, but 4552 ms per 4-question call |
| 3 | Its confidence is calibrated enough to gate on | **FALSE** | ECE 0.182; 20% accuracy at 63% stated confidence |
| 4 | A reasoning layer adds value over calling the engine directly | **FALSE** | A and C identical to the decimal |
| 5 | A *recurrent* loop adds value over a single call | **FALSE** | D 0.508 vs C 0.558, p = 0.0312 |
| 6 | Real, redistributable Indian market data is obtainable | **PARTIAL** | Live NSE works; **redistribution is not cleared** |
| 7 | The decision protocol can be versioned and migrated safely | **TRUE** | v1→v2 migration, load-time validation, 5 checked invariants |
| 8 | The system fails safely under adversarial input | **TRUE, after fixes** | 43/43 red-team cases; one real prompt injection was found and closed |
| 9 | A conversational surface improves on a fixed pane UI | **UNTESTED** | This is the product bet of the current phase |

Four of nine are false. **That is the most important sentence in this document.** The project
continues because the false ones are *specific and fixable*, not because the architecture is
sound in general.

---

## 7. What must be measured?

Already measured, with hardware, model version, n and baseline attached to every number:
accuracy, macro-F1, per-class P/R/F1, Brier, ECE, risk-coverage/AURC, p50/p95 latency, token
usage, System-1 call count, unnecessary calls, abstention rate, premature termination,
over-analysis, paired significance, robustness to missing/contradictory/stale/duplicate/
injected/malformed input, and per-stratum accuracy.

Not yet measured: conversational-intent accuracy, workspace-selection accuracy, follow-up
context resolution, and whether the loop helps on a task where decomposition actually matters.

---

## 8. What could disprove the thesis?

Already disconfirmed, by our own data:

- ~~"The recurrent loop improves decision quality."~~ **Disconfirmed.** D < C, p = 0.0312.
- ~~"A reasoning layer adds value."~~ **Disconfirmed.** A ≡ C exactly.
- ~~"The fast engine's confidence is usable for abstention."~~ **Disconfirmed in the mid band.**
- ~~"PDR latency claims transfer."~~ **Disconfirmed** by 2.4–5.9×.

Still live, and any of these would still disprove the product:

- **H5** — a System-2 specialised for the decision protocol changes the picture. Untestable
  here: the only 4B model that fits the RAM budget is 42–64 s per call, so a 120-item run is not
  affordable. **This is the single largest untested escape hatch from the negative result.**
- **H6** — deeper coupling (learned routing, distillation) beats the tool protocol. Not built,
  and correctly so while the untrained version adds nothing.
- **The task is wrong, not the architecture.** Every measurement is on *event classification*,
  which System-1 already does adequately. A task needing genuine decomposition — "find companies
  where revenue is growing but margins are deteriorating" — might behave completely differently.
  **This is the most likely way the negative result is wrong, and it is a hypothesis, not a hope.**

---

## 9. What we are therefore building

Because four conditions came back false, the product is not the one the original PDR described:

- **The typed decision engine is the product's analytical core**, not a subordinate tool. It is
  fast, cheap, auditable and — at n=120 — the best-performing configuration measured.
- **The reasoning model is optional and off by default**, because it costs 4× latency for zero
  measured gain on this task. It remains selectable, fully traced, and is the substrate for the
  conversational surface — where its job is *intent understanding and workspace selection*, a
  different task from the one that failed.
- **The recurrent loop is retained as a mode, not a default**, because it is the control that
  produced the negative result and the user must be able to see it.
- **The remaining work is the conversational surface and dynamic workspaces**, because that is
  where the reasoning model plausibly earns its cost: interpreting intent, maintaining task
  state, and choosing what to show. That is a different question from "can it improve a
  classification?" and it has not been measured.
- **Two defects dominate accuracy** and are the highest-value engineering target: three classes
  at F1 = 0.00 (`capital_action`, `fundraise`, `regulatory_action`), with 36 misclassifications
  absorbed by the `other` option. `other` is acting as an attractor for uncertainty. This is a
  protocol defect, not a model defect.
