# DATA_SOURCES.md

_Every source, how it is accessed, what it is worth, and what it may be used for. Verdict dates
are the dates the evidence was actually fetched._

## Licence position, stated once

**Live NSE endpoints are exchange-proprietary and no reuse grant was located.** That is fine for
running this software yourself and is **not** clearance to redistribute a build with the data
baked in. `src/divya/data/sources.py` holds the machine-readable verdict
(`LicenceVerdict.redistribution_allowed`), `divya doctor` prints it per source, and
`docs/loop/BLOCKERS.md` B-002 tracks it.

The shipped default is **fixture data**, and every fixture record is stamped `is_simulated=True`
**in the data itself** — not only in the documentation — so it cannot be laundered into looking
live by a code path that forgot to check.

## The register

| id | source | access | verified | redistribution |
|---|---|---|---|---|
| `nse_announcements` | NSE corporate announcements JSON | HTTPS, browser UA, **no cookies** | 2026-09-28 | **NO** — verdict UNRESOLVED |
| `nse_bhavcopy` | NSE daily EOD prices (zip) | HTTPS, browser UA | 2026-09-28 | **NO** — verdict UNRESOLVED |
| `nse_index` | NIFTY 50 constituents (CSV) | HTTPS, browser UA | 2026-09-28 | **NO** — verdict UNRESOLVED |
| `fixture` | Divya bundled fixtures | shipped in-repo | 2026-09-28 | **YES** (authored here) |

## What works, measured

### NSE corporate announcements — the primary source

```
https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
```

HTTP 200, **14,805 records for September 2026**, ~10 MB, **no session cookies required**. A
browser User-Agent is mandatory — a request without one returns nothing at all.

Fields: `seq_id`, `symbol`, `sm_name`, `smIndustry`, `sm_isin`, **`desc`**, `an_dt`, `sort_date`,
**`attchmntText`**, `attchmntFile` (PDF), `hasXbrl`, `orgid`.

`desc` is NSE's own human-curated event type — **104 distinct classes**. It is the evaluation
label, and mapping it to the protocol is explicit and auditable in
`src/divya/data/nse_taxonomy.py`.

**Chunk by month.** A one-year window returns ~114 MB and truncates.

### NSE bhavcopy — EOD prices

```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
```

HTTP 200, 177,333 bytes, valid CSV. **The URL in `plan.md` 404s** — it uses the retired
`content/historical/EQUITIES/...` path. Exchange circular **NSE/MSD/76457** (2026-09-21)
re-organises dissemination **effective 2026-10-12**, so this endpoint has a shelf life and the
adapter raises a specific error when the payload is not a zip.

### NIFTY 50 constituents

`https://archives.nseindia.com/content/indices/ind_nifty50list.csv` → HTTP 200, 50 rows.

## What does not work

Recorded because a plan that names only working sources reads as a plan that has been tested
when it has not.

| source | result | evidence |
|---|---|---|
| NSE historical price API (`/api/historical/cm/equity`) | **503 on every path** | 5 attempts, with and without cookies/`Referer`/`csv=true`; same-day bhavcopy and announcements returned 200, so it is path-specific |
| BSE archives (`archives.bseindia.com`) | **does not resolve** | curl 000 |
| BSE API (`api.bseindia.com`) | **403** Akamai "Access Denied" on 5 paths | |
| NSE `corp_anncmnts` CSV | **404** | superseded by the JSON API |
| `yfinance` | **works, but ToS-prohibited** | 7,717 rows for `RELIANCE.NS` back to 1996 — real data, but Yahoo's terms prohibit automated collection. Development/backfill only |
| HuggingFace bhavcopy datasets | **real but unlicensed** | `Abhishek9045/nse-bhavcopy-data` cross-checks exactly against yfinance — provably real — but declares no licence, which means all rights reserved |
| GDELT | **429** | 3 attempts over 90 s |
| tejhq, databulls, truevalue.ml | **unreachable** | curl 000 / 403 |

**There is currently no free path to an Indian historical price time series from the exchange.**
bhavcopy is per-day and must be collected day by day; yfinance is licence-restricted.

## The distribution that actually matters

The single most useful measurement in this project about the Indian market, from 14,805
September 2026 announcements:

| NSE class | n |
|---|---|
| Shareholders meeting | 2668 |
| Trading Window | 1858 |
| General Updates | 1752 |
| Analysts/Institutional Investor Meet | 1700 |
| Copy of Newspaper Publication | 1415 |
| Updates | 1035 |

**77% of a real Indian announcement feed contains no corporate event at all.** A system that
silently dropped these would look far better than it is; one that classified them would be
confidently wrong. They are ingested, labelled `unresolved`, and reported as their own
population. `Outcome of Board Meeting` (456, the largest event-bearing class) is also
`unresolved` — the text frequently does not state the outcome.

Event-bearing share: **18.7%** of the feed, 2,770 records.

## A mapping mistake worth recording

The first taxonomy draft mapped `Trading Window` → `regulatory_action`. **That was wrong.** A
trading-window closure is routine SEBI PIT compliance, not a penalty, sanction or suspension —
and it is the second-largest class in the feed. Left uncorrected it would have poisoned
**47% of the evaluation population** with a false label.

It was caught by reading the frequency table *before* trusting the mapping. Class counts are
the cheapest defence against a plausible-looking but wrong taxonomy.

## Filing text: summaries vs the real thing

`attchmntText` is a **one-line summary**; median **154 characters** across the feed. The filing
is in the attached PDF. `src/divya/data/filings.py` fetches and extracts it:

- **107 of 120** evaluation items upgraded; **25.3×** more text (17,015 → 431,266 characters).
- Exchange address boilerplate stripped — often a third of page one and the least informative.
- Filings that are **scanned images with no text layer** (13 of 120) are detected, reported, and
  fall back to the summary. Never decided on as an empty document. See B-007.

Every result reported before this was measured on summaries. A materiality judgement needs
figures, and summaries routinely omit them.

## Provenance carried on every record

| field | why |
|---|---|
| `source_id` | which adapter produced it, e.g. `nse_ann:RELIANCE:1234` |
| `source_url` / `attchmntFile` | the PDF a human can open |
| `announced_at` | when the exchange says it happened, not when we fetched it |
| `retrieved_at` | when we fetched it — the basis of every freshness claim |
| `is_simulated` | forced `True` for fixtures regardless of what the file says |
| `content_hash` | exact-byte digest; the provenance chain |
| `dedup_key` | normalised digest; duplicate detection |

Two digests because provenance and deduplication want opposite things — see
`COGNITIVE_RUNTIME.md` §2.

## What must not happen

- Do not redistribute restricted data. The verdict is `False` for every live source.
- Do not present simulated or stale data as live verified. `is_fresh` fails toward caution and
  the frontend renders the dot.
- Do not fabricate a price, a figure, or a citation. System-2 cannot invent one: any number in
  a workspace comes from a System-1 answer or a source document, and the trace says which.
- Do not default to a source whose licence was not read. That is why fixtures are the default
  and live NSE is opt-in.
