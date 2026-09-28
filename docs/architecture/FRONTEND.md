# FRONTEND.md — architecture of the Divya web surface

_2026-09-28. The web frontend is the product's primary surface. This document records what it
is, what it is built on, what it deliberately refuses to do, and which parts are verified._

---

## 1. What this frontend is

**A conversational control surface with a dynamic analytical workspace**, not a dashboard with
a chat box bolted on.

```
┌────────────────────────────────────────────────────────────────────────┐
│ COMMAND SURFACE — always visible, `/` focuses from anywhere            │
├──────────────┬─────────────────────────────────────┬───────────────────┤
│ CONTEXT RAIL │ WORKSPACE                           │ EVIDENCE RAIL     │
│              │                                     │                   │
│ active task  │ rendered from a typed UI intent     │ decisions made    │
│ entities     │ — the workspace *changes* with the  │ sources + URLs    │
│ narrowed to  │ conversation, it is not a page      │ freshness         │
│ recent tasks │ you navigate to                     │ unresolved        │
├──────────────┴─────────────────────────────────────┴───────────────────┤
│ STATUS — freshness · engine · model · degradation · degraded reason    │
└────────────────────────────────────────────────────────────────────────┘
```

That three-column shape is a terminal's information architecture, not a generic layout:
**left = what I am working on, centre = the answer, right = why I should believe it.**

The workspace is not navigated to. It is *constructed* from a typed intent the backend emits.
Asking a different question changes the centre panel; the rails persist.

---

## 2. Space UI — verified, not assumed

The brief requires Space UI as the foundation and forbids guessing. Everything below was
established by fetching the ecosystem's own sources on 2026-09-28, not by inference.

### What Space UI actually is

A **shadcn-compatible component registry** at `https://www.spaceui.one/r/{name}.json`, not an
npm package. `spaceui`, `@space-ui/react` and `@spaceui/react` all 404 on npm. The inventory
(252 items) was recovered by grepping the homepage's JS chunks, because the site publishes no
index endpoint — `/r/registry.json` returns a Next.js 404 page with HTTP 200.

| Group | Count | Examples |
|---|---|---|
| `primitives-*` | 60+ | button, card, table, tabs, sidebar, command, dialog, drawer, sheet, scroll-area, popover, tooltip, badge, input, textarea, select, combobox, kbd, meter, progress, skeleton, separator, toolbar, breadcrumb, pagination, alert, toast, accordion, autocomplete, checkbox, collapsible, field, form, frame, group, navigation-menu, number-field, otp-field, preview-card, radio-group, spinner, switch, toggle |
| `components-spaceui-*` | 60+ | data-grid, event-calendar, kanban, sortable, filters, resizable, status-badge, theme-toggle, morphing-command-bar, interactive-checklist, timeline |
| `hooks-*` | 50+ | `use-event-listener`, `use-debounce`, `use-pagination`, `use-sanitize-content`, `use-performance-mode`, … |
| `lib-*` | 6 | utils, **base-ui**, style, gpu-runtime, … |
| `block-*` | 6 | marketing blocks — **not used**; a terminal is not a landing page |

### Verified stack

| Package | Version | How verified |
|---|---|---|
| React | 19.2.8 | installed |
| Next.js | 16.3.6 (App Router, Turbopack) | installed |
| Tailwind CSS | 4.3.3, CSS-first config | installed |
| **`@base-ui/react`** | ^1.8.0 | installed — note it is **not** `@base-ui-components/react` |
| `motion` | 13.4.4 | installed |
| icons | Lucide (primitives), Tabler (components) | `components.json` `iconLibrary: lucide` |

Theming is `src/app/globals.css`, class-based `.dark` via `@custom-variant dark (&:is(.dark *))`,
with a squircle radius scale derived from `--radius`.

### Install commands (verified working)

```bash
pnpm dlx shadcn@latest init https://www.spaceui.one/r/lib-style.json -y
pnpm dlx shadcn@latest add @spaceui/primitives-table --yes --overwrite
```

**The namespace is doubled-prefix.** The item is `primitives-table`, so the command is
`@spaceui/primitives-table`. Space UI's own docs show `@spaceui/dialog`, which is wrong.

### Naming that differs from shadcn

`dropdown-menu` → **`primitives-menu`** · `sonner` → **`primitives-toast`** ·
`hover-card` → **`primitives-preview-card`** · **`chart` does not exist** at all (only
`--chart-1..5` colour tokens) · `timeline` exists as a component, not a primitive.

25 items are PRO-locked and were not used. `primitives-preview-link-card` depends on
`@space-ui-components/react`, which 404s on npm and cannot be installed.

---

## 3. Two upstream defects found, and what was done

Both are recorded in the code, not just here.

### D-1 — `lib-style.json` produces a 500 on first run

It emits `--ring: var(--ring)` inside `@theme inline`, which shadcn's base layer then
`@apply`s as `outline-ring/50`. Tailwind cannot resolve that class, so **every page 500s on a
clean install**. One-line fix, applied in `globals.css`:

```diff
-  --ring: var(--ring);
+  --color-ring: var(--ring);
```

Without this, nothing renders. Anyone installing Space UI hits it.

### D-2 — `components-spaceui-data-grid` does not typecheck as installed

It depends on `@tanstack/react-table`, and the registry resolves **v9**, which is a full
rewrite: `useTable` instead of `useReactTable`, feature-based `createColumnHelper`, and
`flexRender` instead of `columnDef.cell(context)`. The component is written against the v8 API
and produces 8 type errors on import.

**Decision: the event stream is built on Space UI's own `table` primitive instead.** The data
grid was removed rather than left in the tree, because shipping a component that does not
compile is worse than shipping one that does.

What this gives up: column resize, column pinning, and server-side pagination. What it keeps:
a sticky header, tabular numerals, dense rows, sort affordances — everything a 200-row event
feed actually needs. If the feed grows to terminal row counts, the grid is the right answer and
the v9 integration is the work to budget. The trade-off is written into the component's
docstring so the next engineer does not rediscover it.

---

## 4. What the language model may and may not do

**It may not render.** System-2 emits one of a closed enum of typed UI intents:

```
SHOW_COMPANY   SHOW_COMPARISON  SHOW_EVENT_STREAM  SHOW_SCREEN
SHOW_FILING    SHOW_TIMELINE    SHOW_FINANCIALS    SHOW_DECISION_TRACE
SHOW_EVIDENCE  SHOW_ALERTS       SHOW_MARKET  SHOW_INVESTIGATION  SHOW_EVENT
```

Each maps to a `WorkspaceKind` in `src/divya/runtime/intents.py` and a React component in
`src/components/divya/workspaces/`. The mapping is mirrored in TypeScript at
`src/lib/divya-types.ts`, and the frontend **cannot render an intent outside the union** — it is
a discriminated union in the type system, not a string that gets looked up at runtime.

This is a security boundary, not a style preference. Text inside a filing is attacker-
influenced. If the model's output selected a component or a route, that text would be one
prompt away from choosing what the user sees. A closed enum makes the view layer
unreachable from document content.

The model may still decide *which* workspace is appropriate. It may not decide what it looks
like, and it emits no code.

---

## 5. Three things this UI refuses to do

Each of these was a deliberate choice, and each was previously wrong.

**1. Undecided events sort last.** The MATERIAL column sorts by System-1's
`is_material` probability. Events with no decision carry a `undecided` badge and rank *after*
decided ones. An event the system has not judged is not top priority, and putting it at the
top would be the single most misleading thing this view could do.

**2. No number renders without its retrieval time.** Freshness is passed into every
data-bearing workspace and rendered in its own footer *and* in the status bar, with a
green/red dot driven by `isStale()`. A market terminal that shows a price without showing its
age is the core failure mode of the category.

**3. The language model's prose is never shown as a confidence.** Confidence comes from the
typed engine's probability, and the tooltip says the number is raw System-1 output with its
protocol version. The reasoning model has a `rationale` field, and it is written to the trace
and **never read back** — see `docs/architecture/COGNITIVE_RUNTIME.md` §3.

---

## 6. Motion and accessibility

Space UI's reduced-motion handling is **not automatic**. The tree is wrapped in
`<MotionConfig reducedMotion="user">` in `app/layout.tsx`, and `globals.css` carries a
`prefers-reduced-motion` block. For a terminal this is a correctness requirement, not polish: a
grid that animates while someone is reading numbers in it is the opposite of a precision
instrument.

Motion is otherwise used sparingly — hover and focus transitions, and nothing that delays a
read. A market workspace should appear when the data arrives.

Also: `tabular-nums` is set globally (a column of prices that jitters as digits change width is
unreadable), focus rings are explicit and high-contrast, and the command input carries an
`aria-label` so the Playwright tests and screen readers find the same element.

---

## 7. Verification performed

| Check | Result |
|---|---|
| `pnpm build` (Next 16.3.6, Turbopack) | **passes** |
| `tsc --noEmit` | **clean** |
| `eslint src` | **0 errors**, 11 warnings (unused destructured props in registry code) |
| Real browser (Playwright/Chromium) | **0 console errors** |
| Idle → market workspace | 17 rows, headers `SYM / COMPANY / OUR LABEL / NSE CLASS / MATERIAL ▾ / SYSTEM-1 / ANNOUNCED / SRC` |
| Follow-up | workspace switched to investigation, `AIIL` preserved, `continuing` badge shown |
| Screenshots | `frontend/screenshots/01-idle.png`, `02-market-workspace.png`, `03-followup-investigation.png` |

Screenshots were produced against a live stack — Next.js on :3000, the FastAPI backend on
:8000, a real SQLite store with 600 NSE announcements, and System-1 loaded.

Two failures during that verification were **not** code defects: stale `next-server` processes
from a restart were holding port 3000 and serving chunks from a superseded build. The fix was
process hygiene, and it is recorded here because the symptom (a 500 on one chunk, a
server-rendered page that never hydrates) looks exactly like a frontend bug.

---

## 8. How to run it

```bash
# 1. backend
divya index --days 2 --limit 500        # ingest live NSE announcements
divya serve                             # FastAPI on 127.0.0.1:8000

# 2. frontend
cd frontend && pnpm install && pnpm dev  # http://localhost:3000
```

`NEXT_PUBLIC_DIVYA_API` points at a different backend if needed. The frontend degrades visibly
when the backend is unreachable — the status bar says so rather than rendering an empty shell.

---

## 9. What is not built

Honest inventory, because a frontend claim that overstates itself is the failure mode this
document exists to prevent.

- **Not implemented:** comparison against last quarter, charting, watchlists, saved
  investigations as first-class objects, alerts that fire, natural-language *filtering* of a
  result set (the screen workspace takes a predicate but does not compile it), URL-addressable
  analytical state beyond per-intent routes.
- **The reasoning model is not yet driving workspace selection.** The backend currently
  classifies intent with rules (`runtime/session.py`) and System-2 is available but unused for
  this step. This is deliberate: entity resolution is deterministic by design, and the
  measured result on the analogous task was that an untrained reasoning layer adds nothing
  (see `docs/research/THESIS.md` §2). Whether it helps *workspace selection* is **untested**,
  and that is the single most interesting open question in the product.
- **No auth, no multi-tenancy.** The backend binds to loopback with no authentication, by
  design: it is a self-hosted single-user service, and pretending otherwise would be a claim
  the code does not back.
