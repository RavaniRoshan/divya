# STOP RULE — pre-committed, before the next experiment

_Written 2026-09-29, before any fine-tuning, specifically so that a fifth round of question-set
editing cannot be rationalised after the fact._

## The situation

The System-1 decision engine sits at **0.43 macro-F1** on 120 real NSE announcements. Four
attempts to raise it by editing the question set have failed (D-024 → D-026). An independent
literature survey (`docs/research/STATE_OF_THE_ART.md`) found the reason:

- **Laya's own published zero-shot accuracy is 0.361** on its 2,000-decision typed-decision
  benchmark — *below its own majority-class baseline of 0.461*. Our 0.43 is **above** the
  author's own zero-shot number for a different task.
- The author writes: *"Laya is a fast base to specialise, not a zero-shot decision engine."*
- **Laya's own BENCHMARKS.md predicts all four of our failures in advance**: a label-budget
  ceiling on wide `choice` questions, confidence that stays high while the model is wrong
  (so confidence gating cannot save you), `noul` answering from its own option labels, and
  one-forward-pass non-composition. We re-derived every one of them independently.
- **Fine-tuning the same 421M architecture reaches 0.766** on that benchmark, using 4 epochs
  on free Kaggle 2×T4 GPUs, with a published notebook.
- **There is no public NSE/BSE announcement event-classification benchmark, dataset or
  practitioner write-up anywhere.** Verified across HuggingFace datasets, arXiv, and a
  filtered OpenAlex query returning `count: 0`. **There is no state of the art to be behind**,
  and equally no published number to benchmark ourselves against.
- Fine-tuned transformers reach **0.78 m-F1** on FiNER-139 and **0.93 F1** on SEntFiN — but
  both are easier tasks than 9-way event typing, and the realistic target here is
  **0.65–0.75, not 0.90**.

## The rule

> **If a fine-tuned Laya does not reach ≥ 0.65 macro-F1 on the 120 held-out announcements
> that have never been used for training, tuning, or threshold selection, the typed-decision
> approach is refuted for this domain.** We stop editing question sets, stop tuning thresholds
> against the held-out set, and move extraction to an LLM path with the typed engine demoted to
> a shadow/fast-path role.

## Conditions that make this a real commitment

1. **The 120 are frozen.** `evals/datasets/nse_v5_eval_set.jsonl`. No training, no prompt
   iteration against them, no threshold chosen by looking at them. If a threshold has to be
   picked, it is picked on a separate dev split.
2. **A dev split exists and is separate.** Training data is scraped and labelled from NSE's
   own `desc` taxonomy; a disjoint dev split is used for every choice; the 120 are touched
   exactly once, at the end.
3. **The rule is evaluated once.** Not "run it, see 0.61, tweak, run again". Tweak, then the
   held-out set is spent and the result stands.
4. **0.65 is a floor, not a target.** Beating it does not make the architecture vindicated; the
   loop result (D-012/D-026) stands independently. Passing it only establishes that the
   *engine* is capable on this domain, which is a different and narrower claim.

## What is explicitly still open

The **loop** question is settled separately and is not reopened by this rule: on real filings
the recurrent System-2/System-1 loop was measurably **worse** than a single System-1 pass
(p = 0.0312, six discordant pairs all favouring the single pass) before the taxonomy merge, and
after the merge it is indistinguishable from it. **Fine-tuning System-1 does not make System-2
useful.** The one Laya+finance project found anywhere keeps Laya in a shadow role for exactly
this reason.

## If the rule fires

The product does not become "an LLM with a prompt". It keeps:
- the versioned decision protocol and its load-time validation,
- the immutable raw-decision record and the full trace,
- the provenance, freshness and licence discipline,
- the terminal and its evidence surface.

What it loses is the claim that the typed engine is the analytical core. That claim is
currently **not supported by evidence**, and this document is the commitment to find out
whether it can be, rather than assuming it.
