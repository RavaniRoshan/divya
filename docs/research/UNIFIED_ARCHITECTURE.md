# UNIFIED_ARCHITECTURE.md

_2026-09-28. The research question, the levels, what was actually built, and what the evidence
says about each one. This is the document to read if you want to know whether the architecture
is justified — as opposed to what it does._

---

## 1. The question

> Can a System-2 reasoning model and a fast System-1 decision engine be architected into a
> single inference architecture in which both continuously exchange structured state through a
> recurrent interaction protocol?

Note the second clause. A recurrent protocol is a *mechanism*. The question is whether it buys
anything, and it is entirely possible to build a beautiful recurrent protocol that is worse
than a single call. We built it. Then we measured it.

---

## 2. The five levels, and where each one stands

| level | definition | status | evidence |
|---|---|---|---|
| **L1** | System-2 → Laya, single shot | **built, measured** | arm C, n=120 |
| **L2** | System-2 ↔ shared state ↔ Laya, recurrent | **built, measured** | arm D, n=120 |
| **L3** | System-2 specialised around the Laya protocol | **not built — declined** | D-013 |
| **L4** | learned routing, distillation, joint optimisation | **not built — declined** | D-013 |
| **L5** | is it a materially new architecture? | **no** | two connected models are two models |

L3 and L4 are declined for a reason that is worth stating plainly: **there is nothing for them
to optimise.** An untrained reasoning layer contributes exactly zero accuracy over calling the
decision engine directly, and the recurrent loop they would be trained to drive is measurably
*worse* than the single-shot path. Training a specialised model to be better at a protocol that
degrades results would be optimising a premise this project's own data just rejected.

---

## 3. The measurement that decided it

120 real NSE announcements, four arms, paired, same process, same loaded checkpoint, strata
assigned before scoring.

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | S1 calls | Prompt tok | Abstain |
|---|---|---|---|---|---|---|---|---|
| **A** System-1 alone | **0.558** | 0.436 | 0.096 | **0.240** | **4.7 s** | 1.00 | 0 | 0.0% |
| **B** System-2 alone † | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 0.00 | 2214 | 0.0% |
| **C** System-2 → Laya | **0.558** | 0.436 | 0.096 | **0.240** | 19.0 s | 1.00 | 1079 | 0.0% |
| **D** recurrent | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | 2.57 | 4941 | **75.8%** |

† arm B is a **failed arm**: 0 of 120 items produced any answer. Its 0.000 is a missing answer
scored wrong, not a measurement of System-2's ability.

**Two results, and the second is the one that matters.**

1. **A and C are identical to the decimal** on accuracy, macro-F1, ECE *and* AURC. The reasoning
   layer contributed nothing at 4× the latency.
2. **D is worse than C.** Paired per item: **A right / D wrong on 6, D right / A wrong on 0.**
   The loop never once fixed an error the single-shot path made, and it broke six correct
   answers by re-asking System-1 and receiving different, worse results.

Significant: McNemar exact **p = 0.0312**; paired bootstrap 95% CI **[−0.0917, −0.0167]**,
excluding zero; P(Δ<0) = 0.9984.

---

## 4. Hypotheses, resolved

| # | hypothesis | verdict | why |
|---|---|---|---|
| **H1** | the recurrent loop improves decision quality | **REJECTED** | D 0.508 < C 0.558, and worse on `clear` and `noisy` |
| **H2** | the loop mainly adds latency | **REJECTED as stated** | it is worse, not merely slower. Latency is real but not the finding |
| **H3** | the loop is useful only for ambiguous tasks | **SUPPORTED, inverted** | on the ambiguous stratum all arms tie at 0.500. The loop is not useful there either — it is useless, and harmful elsewhere |
| **H4** | a specialised System-2 substantially improves Laya utilisation | **UNTESTED** | the only 4B model that fits the RAM budget takes 42–64 s/call. A 120-item run is not affordable. **This is the largest open escape hatch** |
| **H5** | deeper coupling beats a tool protocol | **NOT BUILT** | premature while the untrained loop subtracts value |
| **H6** | selective Laya invocation beats repeated invocation | **PARTLY** | the tier structure exists and is what makes arm C and arm D differ. But on the evidence, *not invoking* beats invoking better |

H3 is worth reading twice. The interesting version of the hypothesis was "the loop helps when
the case is ambiguous". The data says the loop does not help even there — it ties. So the
problem is not that the loop is aimed at the wrong population; the loop has no positive case at
all on this task.

The external literature agrees and was checked first. **ATLAS (arXiv 2510.15949)** reports that
reflection-based feedback fails to provide systematic gains. The paper most often cited for
this architecture — dyadic / Talker-Reasoner, arXiv 2410.08328 — is by Christakopoulou, Mourad
and Mataric, a NeurIPS 2024 *workshop poster* with no numbers in its abstract, and the
attribution to "Collins et al." in the original PDR is simply wrong.

---

## 5. Where the accuracy actually goes

The failure is not uniform, and the localisation is more useful than the headline.

| class | n | P | R | F1 |
|---|---|---|---|---|
| credit_rating | 8 | 0.89 | 1.00 | **0.94** |
| leadership_change | 43 | 1.00 | 0.79 | **0.88** |
| m_and_a | 14 | 1.00 | 0.50 | 0.67 |
| other | 18 | **0.29** | 0.83 | 0.43 |
| capital_action | 13 | 0.00 | 0.00 | **0.00** |
| **fundraise** | 5 | 0.00 | 0.00 | **0.00** |
| **regulatory_action** | 17 | 0.00 | 0.00 | **0.00** |

**Three** classes at exactly zero, and `other` at precision 0.294 (TP 15, FP 36) — it is an
attractor for uncertainty. `capital_action` goes to `other`/`fundraise` 13 of 13;
`regulatory_action` to `other`/`capital_action` 16 of 17.

This is a **protocol design defect, not a model defect**. A catch-all option in a typed-decision
head does not stay a catch-all; it becomes where uncertainty goes. Removing `other` from the
option set and letting unresolvable filings abstain is the clearest next experiment, and it
could change the numbers more than any architecture change available.

---

## 6. The honest caveat on all of it

**Every measurement is on event classification, which System-1 already does adequately.**

That is the most likely way this negative result is wrong. A task requiring genuine
decomposition — "find companies where revenue is growing but margins are deteriorating", across
many companies and many filings — might behave completely differently, and the reasoning model
might earn its cost there. This is a **hypothesis, not a hope**, and it is the first thing worth
testing with a bigger memory budget.

Two further limits:

- **Labels are NSE's `desc` taxonomy, not truth.** Agreement with the exchange's filing
  classification is meaningful and auditable. It is not correctness about the business.
- **107 of 120 items were 154-character summaries** when this was measured. Full filing text
  gives 25.3× more text and the re-evaluation on it is in flight. Every number above describes
  the system reading one-line summaries.

---

## 7. What the architecture *is*, then

Given the evidence, the honest description of the system:

> **A fast typed-decision engine over a versioned decision protocol, with an optional
> reasoning layer for intent understanding and workspace selection, and a transcript that makes
> every conclusion inspectable back to a source and a raw engine output.**

That is a real and useful thing. It is not a unified cognitive architecture, and the project
does not claim it is. What the project *does* claim is:

- the protocol is versioned, migration-checked, and refuses to load a definition that would
  produce confidence the engine itself disclaims;
- raw System-1 output is immutable and a reasoning model cannot overwrite it;
- every run ends in exactly one named state, and the totality of that is tested;
- the adversarial suite found a real prompt injection against the real engine, and it is fixed,
  8/8 against the real engine now;
- the headline number was recomputed by an independent reviewer who did not build it, found
  four defects in the reporting and two in the code, and all are fixed.

The most useful thing this project produced is not the terminal. It is a set of measurements
showing that an attractive architecture, built carefully and measured honestly, **did not beat
the obvious alternative** — and a list of exactly which measurements say so.
