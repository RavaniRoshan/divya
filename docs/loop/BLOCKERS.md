# BLOCKERS

Anything that genuinely requires a human decision, a missing secret, an authorization, or an
external dependency that cannot be worked around. **Nothing is a blocker until it is written here
and reported to the user.** Working around a blocker silently is worse than the blocker.

Format: `ID | what is blocked | why it is blocked | what I tried | what unblocks it | impact if never resolved`

---

## B-001 — OPEN (non-blocking) — Docker unavailable

| field | value |
|---|---|
| What is blocked | Verification of the PDR's `docker compose up` release target |
| Why | `command -v docker` → not found on this machine. No docker daemon, no docker CLI. |
| Tried | Verified absence directly; considered installing (requires host-level change outside project scope) |
| What unblocks it | A docker-capable host, or installing docker in WSL2 |
| Impact if never resolved | The PDR's stated release target is not met. The venv+Makefile path is verified instead. Recorded in D-002. Not a correctness risk to the product; it is a distribution-fidelity gap. |

**Workaround in force:** `make setup` / `make test` over a pinned venv is the primary verified
path. `Dockerfile` and `docker-compose.yml` are authored but labelled `UNVERIFIED-IN-THIS-ENV`
wherever they appear. Nothing claims a docker run was performed.

---

## B-002 — OPEN (non-blocking) — No redistributable live Indian market data confirmed

| field | value |
|---|---|
| What is blocked | A live-data first domain for Phase 6 |
| Why | NSE/BSE publish free EOD bhavcopy files, but redistribution terms for those files are not yet confirmed from a primary source |
| Tried | Research dispatched (`research/INDIA_DATA.md`, in progress) |
| What unblocks it | Confirmation of the terms on NSE's data-sharing / market-data agreement pages |
| Impact if never resolved | The product ships with explicitly labelled fixture data (`SIMULATED`) plus any adapter whose licence clears. This is a real reduction in product value and will be stated plainly in the final report, not glossed. |

**Interim stance:** the fixture path is the default. No source is assumed redistributable until
its terms are read. This is a deliberate conservatism, not an oversight.

---

## B-003 — OPEN (non-blocking) — System-2 model quality for structured output

| field | value |
|---|---|
| What is blocked | Whether Level 2 is buildable with a 4B local model, or needs constrained decoding |
| Why | Unknown until measured. A 4B model may not emit reliable JSON, in which case the S2 protocol needs a grammar constraint or a repair-and-verify step |
| Tried | Ollama 0.31.1 with a resident 3B model; structured-output quality not yet measured |
| What unblocks it | The first real System-2 structured-output measurement (next action) |
| Impact if never resolved | Would force constrained decoding into the design. Not fatal — the provider interface (D-003) already isolates this. |
