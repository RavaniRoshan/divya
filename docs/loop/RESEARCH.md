# RESEARCH

Evidence register. Every row is tagged. **A tag is a promise about how the row was obtained,
not a measure of how true it feels.**

- `[FACT]` verified from a primary source that was actually fetched
- `[HYPOTHESIS]` plausible, not verified
- `[EXPERIMENT]` currently running
- `[RESULT]` measured, with an artifact path
- `[DECISION]` chosen direction

---

## A. The Laya premise

### A1. Package existence and licence — `[FACT]`

`laya` 0.3.21 exists on PyPI, author "Convai Innovations", `License: Apache-2.0`,
`Requires-Python: >=3.10`, 29 releases from 0.1.6 → 0.3.21.

Primary sources fetched 2026-09-28:
- `https://pypi.org/pypi/laya/json` (HTTP 200)
- `pip download laya --no-deps` → `laya-0.3.21-py3-none-any.whl`, 214 kB
- wheel `METADATA`

Apache-2.0 is permissive and permits redistribution and commercial use with attribution and
preservation of the licence. This clears the PDR's licensing requirement for the model itself.

### A2. Typed decision schema — `[FACT]`

Read from source, not documentation. This is the exact contract the protocol must target.

| type | `criteria` shape | rendered to the model as |
|---|---|---|
| `choice` | `dict[label, description]` | `"<label>: <description>"` per option |
| `score` | `list[str]`, ordered | `"level <i>: <description>"` |
| `noul` | optional `dict` with `false` / `true` keys | `"<false_label>: …no, the statement does not hold"` / `"<true_label>: …yes, the statement holds"` |

- `labels` is **only** valid on `noul`, and must map exactly `{"false","true"}` to two distinct
  non-empty strings, else `ValueError`. *(A1 sources: `laya/common.py:92` `_resolve_noul_labels`,
  `laya/common.py:106` `render_options`.)*
- `choice` labels are stringified with `str(k)`, so int labels are safe. The **caller's original
  label is returned unchanged** in the answer. `(*source: `laya/common.py:106`.)*
- noul is *always* ordered `[false, true]` internally. Semantic order is fixed by the library.

**Design consequence:** the protocol's `choice` option set is what bounds Laya's decision
vocabulary. Adding an option changes the decision problem, so option sets are versioned
artifacts, not prompt text. This is the concrete justification for `questions.yaml`.

### A3. Invocation and result — `[FACT]`

```python
Router().predict(state, questions, model=None, task=None, lang=None,
                 max_len=None, head_max_len=None, min_confidence=None) -> dict
```

- `state: str | dict | list` — a structured state is first-class, not just prose. This matters:
  it means the shared-state protocol can be handed to Laya directly rather than flattened to text.
- Result carries `answers` (per-question result) and `routing` (which checkpoint was chosen, and
  why). `(*source: `laya/router.py:712`, `laya/router.py:49`.)*
- `min_confidence` is a first-class parameter. The abstention primitive already exists in the
  System-1 layer — the protocol should use it rather than reimplementing it.
- Also available: `predict_batch`, `predict_long`, `decide`/`decide_batch` (pydantic structured
  output, `laya[structured]`), `laya[serve]` FastAPI, `laya[mcp]`, ONNX runtime export.

### A4. Checkpoints — `[FACT]`

`DEFAULT_MODELS = {"english", "multilingual", "typed-decisions"}` (`laya/router.py:49`).
Standalone HF repos: `convaiinnovations/laya`, `convaiinnovations/laya-multilingual`,
`convaiinnovations/laya-typed-decisions` (`laya/router.py:56`).

`[UNKNOWN]` Exact parameter counts, weight sizes, and download size **on this machine** — not yet
measured. The PDR's "421M/512", "322M/1024", "~647–808MB each" figures come from the upstream
README and have not been independently confirmed.

### A5. Latency — `[HYPOTHESIS]`

PDR claims 33 ms/question on T4, 193–464 ms on CPU. **Not measured here.** This box is CPU-only
for Laya (torch CPU wheel). Must benchmark before any latency claim is made about Divya.

### A6. Quality on finance text — `[HYPOTHESIS]`

Upstream reports 0.362 base / 0.766 fine-tuned on a **customer-support triage** benchmark. See
D-004: these are *not* priors for financial text. Unmeasured.

---

## B. Architecture thesis

### B1. Competing hypotheses about D vs C — `[HYPOTHESIS]`

Held open deliberately. See `docs/research/LITERATURE.md` (research in progress) and
`docs/research/UNIFICATION_EXPERIMENTS.md`.

- **H1** The recurrent S2↔S1 loop improves decision quality on ambiguous events.
- **H2** The loop mostly adds latency for little quality gain.
- **H3** The loop helps only on the ambiguous subset and is a net loss on clear-cut events.
- **H4** Laya should be called selectively, not every iteration (fewer, better-targeted calls
  beat more calls).

**Note:** H3 and H4 together would imply the correct system is *adaptive* — decide per-event
whether to enter the loop at all. That is a more interesting and more defensible architecture
than "always loop", and it is reachable without any new model capability.

---

## C. Data

### C1. Indian market data licensing — `[EXPERIMENT]`

Research in progress, see `research/INDIA_DATA.md`. **No data source is assumed usable yet.**

Interim stance, safe by default:
- The public default deployment will ship with **explicitly labelled fixture data**, marked
  `SIMULATED` in the data, not in the docs.
- Any live source is isolated behind its own adapter with a recorded licence verdict.
- If redistribution rights are unclear, the adapter is quarantined and documented rather than
  shipped as default.
- No price or event view renders without an as-of timestamp and a source id.

---

## D. Environment

### D1. Machine capabilities — `[FACT]`

WSL2, 16 vCPU, 7.5 GiB RAM, 4 GiB VRAM (RTX 3050), 823 GiB free. No docker, no uv, no go.
Python 3.12.3. Ollama 0.31.1 with `qwen2.5-coder:3b` resident. Network egress open.

`[FACT]` `FetchURL` fails on every host in this environment; `curl` via Bash works. Research
instructions must say `curl`.

### D2. Constraint-driven architecture — `[DECISION]`

7.5 GiB RAM is the binding constraint. Laya (~0.7–2.3 GB of weights, depending on how many
checkpoints) plus a 4B reasoning model (~2.5 GB) plus OS and runtime is close to the limit. This
means:

- The System-2 model must be small and swappable.
- Only one Laya checkpoint should be resident by default.
- Concurrency must be bounded; a "load everything" architecture will OOM.
- Any Docker image must be sized for a small box, and that cannot be verified here (D-002).
