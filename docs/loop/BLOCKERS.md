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

## B-002 — OPEN (non-blocking, but now the top real-world limitation) — Live NSE data is not cleared for redistribution

| field | value |
|---|---|
| What is blocked | Shipping a build with market data baked in, or redistributing a dataset |
| Why | Every NSE endpoint is exchange-proprietary and **no reuse grant was located**. NSE's Terms/Disclaimer/Copyright pages are client-rendered SPAs whose legal text never appears in served HTML; `Allow: /` in robots.txt is crawler etiquette, not a licence |
| Tried | 6 URL shapes plus the `/api/` namespace for the terms pages; fetched every reachable NSE endpoint; checked tejhq (2 repos, 1 and 0 stars, MIT covers code only) |
| What unblocks it | A written reuse grant from NSE, or a licensed aggregator |
| Impact if never resolved | **None for self-hosting — the data is fetched live and works.** Full impact only on redistribution |

**This is now a much smaller problem than it was.** The earlier version of this file said no
usable live data existed. That was wrong. As of 2026-09-28, verified by direct fetch:

- NSE corporate announcements JSON → **14,805 records/month, no cookies, browser UA only**
- NSE bhavcopy EOD zip, NIFTY 50 constituents → HTTP 200
- **The product runs on real data today.** `divya fetch nse-announcements` then `divya decide`.

The boundary is precisely: **fetching at runtime for your own use is fine; shipping the data is
not.** `LicenceVerdict.redistribution_allowed` is False for every live source, the shipped
default is fixture data stamped `is_simulated=True` in the data itself, and `divya doctor`
prints the verdict for each source. This is a distribution constraint, not a capability one.

**Other sources checked and rejected as product data:** NSE historical price API (503 on every
path — there is no free NSE time series); BSE (archives do not resolve, API 403); yfinance
(real Indian prices back to 1996, but Yahoo's ToS prohibits automated collection); HuggingFace
bhavcopy datasets (provably real — cross-checked against yfinance — but almost all unlicensed).
Full evidence in `research/REAL_DATA_SOURCES.md`.

---

## B-003 — OPEN (non-blocking) — System-2 model quality for structured output

| field | value |
|---|---|
| What is blocked | Whether Level 2 is buildable with a 4B local model, or needs constrained decoding |
| Why | Unknown until measured. A 4B model may not emit reliable JSON, in which case the S2 protocol needs a grammar constraint or a repair-and-verify step |
| Tried | Ollama 0.31.1 with a resident 3B model; structured-output quality not yet measured |
| What unblocks it | The first real System-2 structured-output measurement (next action) |
| Impact if never resolved | Would force constrained decoding into the design. Not fatal — the provider interface (D-003) already isolates this. |

---

## B-004 — **RESOLVED** — Filing PDFs are now parsed

| field | value |
|---|---|
| What was blocked | Evaluating on full filing text rather than one-line summaries |
| Why it was blocked | NSE's `attchmntText` is a summary; median **154 characters** across 14,805 announcements. The filing is in the attached PDF |
| What landed | `src/divya/data/filings.py` + `divya filings --db ...` + `research/scripts/enrich_dataset_with_filings.py` |
| Measured | **107 of 120** eval items upgraded; **25.3x** total expansion (17,015 → 431,266 chars) |
| Remaining gap | 13 of 120 have no usable text layer — scanned images needing OCR. They fall back to the summary and say so |

**Impact on prior results: every number reported before this was measured on summaries.** A
materiality judgement needs figures and summaries routinely omit them. The 0.558 figure is a
number about one-line summaries. The re-evaluation on full filing text is in flight.

---

## B-005 — OPEN (non-blocking) — No published ground truth for materiality or direction


| field | value |
|---|---|
| What is blocked | Scoring `is_material`, `materiality` and `direction` on real data |
| Why | The live NSE feed supplies `desc` → `event_type` and nothing else. There is no published label for materiality or direction, and inventing one by hand-labelling would reintroduce exactly the synthetic-data problem that made the first results misleading |
| Tried | Checked the announcement schema for any additional usable field; there is none |
| What unblocks it | Expert hand-labelling with recorded annotator confidence, or a licensed labelled dataset |
| Impact if never resolved | Only `event_type` is scored on real data. The harness reports the others as `"not evaluated"` rather than silently omitting them |

The synthetic dataset carries hand-authored labels for all four decisions, so the metrics code
is exercised — but those numbers are about authored text and are reported as such.

---

## B-006 — OPEN, accepted risk — Prompt injection is mitigated, not solved

| field | value |
|---|---|
| What is at risk | System-1 (Laya) reads untrusted document text with no instruction hierarchy |
| What was found | An 87-character fake system turn flipped `event_type` from `earnings_result` (0.973) to `other` (0.652) against the **real engine** |
| What landed | `src/divya/protocol/sanitize.py` strips control markup, defangs role-shaped JSON, removes zero-width/bidi characters, and redacts instruction-like text. Red-team suite now 43/43 including 8/8 injection cases against the real engine |
| Why it stays open | Laya is a 421M encoder with no concept of an instruction hierarchy. It follows strong associative patterns. Stripping known shapes raises the cost of the attacks we have seen; it does not raise a wall |
| What would actually close it | Constrained decoding over a grammar that cannot express instructions; or System-1 never reading raw text at all. Both are real work and neither is done |
| Accepted because | The alternative — doing nothing — is the state this was found in |

**This is not a security audit and no claim is made that the system is secure.** The committed
suite is 43 specific attacks; 7 ran against the real engine and one found a real hole. An
adaptive adversary who reads `sanitize.py` will find a gap. That is why the suite ships as a
runnable test rather than a document.

---

## B-007 — OPEN, accepted — Scanned filings need OCR

| field | value |
|---|---|
| What is at risk | 13 of 120 evaluation items had no text layer and fell back to the summary |
| Why | Many Indian filings are scanned images. `pypdf` returns nothing for them |
| What landed | Detected and reported as a **failure**, never as an empty document. An empty document would be decided on as "nothing to decide", which is the worst available outcome |
| What would close it | OCR (Tesseract or a cloud OCR service) for the ~11% of filings that are scans |
| Accepted because | The failure is visible and counted rather than silent. Deciding on a summary is worse than deciding on nothing visible |
