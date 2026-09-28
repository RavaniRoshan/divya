# STATUS

_Last updated: 2026-09-28, iteration 4._

## CURRENT OBJECTIVE

The plan is complete. The thesis is measured and **rejected on this data**; the product ships
with the evidence-appropriate default; the red team found a real prompt injection and all 15
defects are fixed; and the conversational Space UI surface is built and verified in a browser.

The full-filing-text re-run has landed and it **changed the picture materially** — see below. The
one clearly next experiment is now to diagnose the `m_and_a` regression before shipping protocol
v3, because it may be the `other` problem reappearing.

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

### `[RESULT]` Full filing text: three classes fixed, one broken, loop destroyed

Same 120 filings, same labels, same protocol v2. Only difference: 107 of 120 items carry the
real PDF text instead of a 154-character summary — **25.3× more text**.

| arm | accuracy | ECE | AURC | p95 |
|---|---|---|---|---|
| A System-1 alone | 0.558 → **0.475** | 0.096 → 0.141 | 0.240 → 0.356 | 4.7 s → **57.7 s** |
| C System-2 → System-1 | 0.558 → 0.475 | 0.096 → 0.141 | 0.240 → 0.356 | 19.0 s → 48.8 s |
| D recurrent | 0.508 → **0.142** | 0.080 → 0.058 | 0.260 → **0.649** | 40.4 s → **90.0 s** |

The aggregate says accuracy fell 8 points. Per class:

| class | n | F1 summary → filing | |
|---|---|---|---|
| earnings_result | 4 | 0.33 → **0.80** | fixed |
| capital_action | 13 | **0.00 → 0.39** | **fixed from zero** |
| regulatory_action | 17 | **0.00 → 0.30** | **fixed from zero** |
| m_and_a | 14 | 0.67 → **0.13** | **badly regressed** |
| leadership_change | 43 | 0.88 → 0.70 | regressed |
| credit_rating | 8 | 0.94 → 0.94 | unchanged |

**The three structurally broken classes now work**, two from exactly zero — because summaries
omitted the figures that identify the event, which is the mechanism `other` was exploiting. The
largest quality movement in the project. But `m_and_a` breaks: on real acquisition filings the
engine now has enough text to be confidently wrong where on summaries it fell through to the
right answer by accident.

**And the recurrent loop stops working entirely** — 0.142, AURC 0.649, p95 over 90 s. The
negative result on the loop is **not** an artefact of short documents; it is worse on real ones.

**The headline 0.558 therefore describes a system reading one-line summaries** and is not
quoted without this beside it. **Latency is now the binding constraint, not accuracy**: 12× for
one item. The obvious fix — classify on the summary, re-read the filing only for the ambiguous
minority — is **not built**. Neither run used protocol v3, which began after both launched.

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
- Does removing `other` (protocol v3) change the three zero-F1 classes? Untested — the v3
  change landed after both evaluations launched. **And note that full text already moved two of
  them off zero without v3**, which is evidence about the mechanism rather than the fix.
- **Why did `m_and_a` collapse 0.67 → 0.13 on real filings?** The most urgent open question. It
  is either a real limitation of the classification head on long M&A documents, or the same
  catch-all problem reappearing in a different place. The data does not distinguish them yet.
- Does the reasoning layer earn its cost on **workspace selection**? That is a different task
  from the one that failed, and it is untested.
- Would PDF parsing change the numbers? The re-run is in flight.

## NEXT HIGHEST-VALUE ACTION

1. **Diagnose the `m_and_a` regression** (0.67 → 0.13 on real filings). It gates protocol v3:
   if it is the catch-all problem again, v3 will not help and the design needs a different gate.
2. **Re-run E-009 on protocol v3** against the same 120 items, on the summary text so it is
   paired with row 12 and comparable in 25 minutes rather than 2 h 35 m.
3. **Build the two-stage read**: classify on the summary, re-read the filing only for the
   ambiguous minority. Full text is worth ~30 points of per-class F1 and costs 12× latency; this
   is the obvious way to keep one without paying the other.
4. On a machine with more RAM, test H5 before anything else.
