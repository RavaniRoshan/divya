# GOAL

## Objective

Build Divya into a finished, working, tested, documented, reproducible product — and in
doing so, **determine whether the proposed unified System-1/System-2 architecture is
actually worth building**, rather than assuming it is.

## The thesis under test

A System-2 reasoning model (planning, decomposition, state, uncertainty, abstention) and
Laya (a fast, non-autoregressive, Apache-2.0 System-1 engine returning typed `choice` /
`score` / `noul` decisions with calibrated probabilities) coupled through a **shared-state
recurrent loop** will produce better decisions than:

- A. Laya alone
- B. System-2 alone
- C. System-2 → Laya, single shot (the Level-1 baseline / control condition)
- D. System-2 ↔ shared state ↔ Laya, recurrent (Level-2)

**D > C is the thing worth proving.** Everything else is scaffolding.

## Success conditions

1. Central premise (Laya) verified from primary sources, or refuted and replaced.
2. Working end-to-end product: event → S2 → S1 typed decision → shared state → persisted → terminal.
3. Level 1 and Level 2 both implemented, with traces that let a human reconstruct the
   entire decision trajectory.
4. Versioned decision protocol (`models/questions.yaml`) with import-tested JSON schemas.
5. Real evaluation over A/B/C/D, with calibration (Brier, ECE) and cost, n stated.
6. Tests green; lint + typecheck green.
7. Adversarial / degradation tests passing (Laya down, LLM down, malformed, injected,
   stale, duplicated, infinite-loop guard).
8. Data provenance, freshness, and a license register.
9. Clean-machine reproducible setup, verified from a fresh clone.
10. README and architecture docs that match the implementation.
11. No fabricated performance or model-quality claims. No hidden critical blockers.

## Explicitly NOT success conditions

- Code existing.
- Tests passing in isolation from the product.
- A demo working once.
- L1 + L2 + L3 + L4 all being "done". L3 (training) and L4 (fusion) are only justified
  if the P7 evaluation shows D > C. If it does not, **shipping the negative result is the
  correct outcome**, and the product is still complete.

## Anti-goals

- Chasing "unified model" language. Two connected models are two models. We will not call
  this a unified cognitive architecture unless a measurement earns it.
- Building the entire equity-research universe. One tight domain, done properly.
- Optimizing a benchmark until the benchmark is a lie.

## Non-goals (v1, stated so they are not mistaken for gaps)

- Intraday or real-time data. Licensed; out of scope for the free public default.
- Broker integration.
- Multi-tenant / hosted SaaS. This is a self-hosted research terminal.
- Financial advice. Divya produces labelled, auditable decision state, not recommendations.
