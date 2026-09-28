# STATUS

_Last updated: 2026-09-28, iteration 4._

## CURRENT OBJECTIVE

The plan is complete. The thesis is measured and **rejected on this data**; the product ships
with the evidence-appropriate default; the red team found a real prompt injection and all 15
defects are fixed; and the conversational Space UI surface is built and verified in a browser.

One experiment remains in flight: re-running the A/B/C/D evaluation on **full filing text**
rather than 154-character summaries. It does not change any decision; it quantifies the largest
caveat on the headline result.

## WHAT CHANGED

- **The conversational product surface.** Space UI frontend: command surface, dynamic
  workspaces, context rail, evidence rail. Verified in Chromium, 0 console errors, 7/7
  Playwright tests against the live stack.
- **Typed UI intents** so the language model selects a workspace but never renders one.
- **Persistent task sessions** so follow-ups continue an investigation instead of restarting it.
- **A FastAPI backend** (`divya serve`) with `/command`, `/workspace`, `/sessions`,
  `/stream`, `/company`, `/decisions`, `/health`.
- **The Space UI stack verified, not assumed** — 252-item registry, and **two upstream defects
  found and worked around** (D-019).
- The Textual TUI remains as the *audit* path: one decision, full provenance, reconstructable
  trace.

## EVIDENCE

### `[RESULT]` The thesis — recurrent System-1/System-2 loop beats single-shot — is REJECTED

120 real NSE announcements, four arms, paired, same process, same checkpoint.
Artifact: `evals/results/real_eval.json`.

| Arm | Accuracy | Macro-F1 | ECE | AURC | p95 | S1 calls | Prompt tok | Abstain |
|---|---|---|---|---|---|---|---|---|
| **A** System-1 alone | **0.558** | 0.436 | 0.096 | **0.240** | **4.7 s** | 1.00 | 0 | 0.0% |
| **B** System-2 alone † | 0.000 | 0.000 | 0.000 | 1.000 | 2.1 s | 0.00 | 2214 | 0.0% |
| **C** System-2 → System-1 | **0.558** | 0.436 | 0.096 | **0.240** | 19.0 s | 1.00 | 1079 | 0.0% |
| **D** recurrent loop | **0.508** | 0.371 | 0.080 | 0.260 | **40.4 s** | 2.57 | 4941 | **75.8%** |

† **arm B is a failed arm** — 0 of 120 items produced any answer. Its 0.000 is a missing answer
scored wrong, not a measurement of System-2's ability.

1. **A and C are identical to the decimal** on accuracy, macro-F1, ECE *and* AURC. The
   reasoning layer contributed exactly zero at 4× the p95 latency.
2. **D is worse than C.** Paired per item: **A right / D wrong on 6, D right / A wrong on 0.**
   The loop never fixed an error the single-shot path made, and it broke six correct answers.

Significant: **McNemar exact p = 0.0312**; paired bootstrap **95% CI [−0.0917, −0.0167]**,
excluding zero; P(Δ<0) = 0.9984.

**H1 rejected · H2 rejected · H3 supported · H4 not supported · H5 (specialised System-2)
untested — the only 4B model that fits the RAM budget takes 42–64 s/call.**

### `[RESULT]` The failure is localised, and that is the actionable finding

| class | n | F1 |
|---|---|---|
| credit_rating | 8 | 0.94 |
| leadership_change | 43 | 0.88 |
| m_and_a | 14 | 0.67 |
| other | 18 | 0.43 (precision **0.294**) |
| capital_action | 13 | **0.00** |
| fundraise | 5 | **0.00** |
| regulatory_action | 17 | **0.00** |

`other` is an attractor for uncertainty: `capital_action` goes to `other`/`fundraise` 13 of 13;
`regulatory_action` to `other`/`capital_action` 16 of 17. **A protocol design defect, not a
model defect** — remove the catch-all and let unresolvable filings abstain.

### `[RESULT]` A prompt injection worked against the real engine, and is fixed

An 87-character fake system turn flipped `event_type` from `earnings_result` (0.973) to `other`
(0.652) against **real Laya 0.3.21**. The red team (43 cases, 7 classes) found **15 defects**;
all 15 are fixed; the suite now passes **43/43** including **8/8 injection cases against the
real engine**. Mitigation, not a solution — B-006.

### `[RESULT]` Space UI, verified

252-item shadcn-compatible registry at `spaceui.one/r/{name}.json`. Installed: React 19.2.8,
Next 16.3.6, Tailwind v4, `@base-ui/react` ^1.8.0, `motion` 13.4.4. **No `spaceui` npm package
exists.** Two upstream defects: `lib-style.json` 500s every page on a clean install, and
`components-spaceui-data-grid` does not typecheck (tanstack v9 rewrite). Both worked around,
both recorded in code. See D-019.

### `[RESULT]` The full stack runs

Browser → Next.js → FastAPI → SQLite → System-1. A real NSE filing selected in the stream,
decided with the real engine in 11,093 ms, rendered with decision-ranked materiality,
provenance in the status bar. Screenshots in `frontend/screenshots/`.

## TESTS

| Suite | Count | Status |
|---|---|---|
| Python (`pytest`) | **388** | pass |
| `ruff check src tests evals research` | — | clean |
| `mypy src/divya` (32 files) | — | clean |
| `tsc --noEmit` | — | clean |
| `eslint src tests` | — | 0 errors, 11 warnings (registry code) |
| `pnpm build` (Next 16, Turbopack) | — | pass |
| Playwright (real stack) | **7** | pass |
| Red team (real engine + stub) | **43** | pass |

## BENCHMARKS

All in `research/results/`, `evals/results/`, and `docs/loop/EVALS.md` with hardware, model
version, n and baseline attached. The A/B/C/D re-run on full filing text is **in flight**.

## KNOWN FAILURES

All found, all fixed, all with a regression test: the prompt injection, contradictory
evidence silently concatenated, a future timestamp and an unparseable timestamp both reading as
*fresh*, duplicates multiplying what System-1 read, a raising System-1 escaping the loop,
`system2_timeout_s` not being the bound, the heuristic path never running the ingestion canary,
and lone surrogates crashing `Observation`.

## OPEN QUESTIONS

- **H5** — would a System-2 specialised for the protocol change the result? Untestable here.
- **Is the task wrong rather than the architecture?** Every measurement is on event
  classification, which System-1 already does adequately. A task needing genuine decomposition
  might behave differently. **The most likely way the negative result is wrong.**
- Does removing `other` from the option set change the three zero-F1 classes? Untested, and the
  cheapest high-value experiment available.
- Does the reasoning layer earn its cost on **workspace selection**? That is a different task
  from the one that failed, and it is untested.
- Would PDF parsing change the numbers? The re-run is in flight.

## NEXT HIGHEST-VALUE ACTION

1. Read `evals/results/real_eval_filings.json` when the run lands and report whether the
   headline numbers move.
2. **Remove `other` from `event_type` (protocol v3) and re-run E-009.** Three classes at F1 0.00
   because a catch-all option absorbed them; this is a protocol defect and the cheapest fix with
   the largest expected effect.
3. On a machine with more RAM, test H5 before anything else.
