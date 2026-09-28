# DATA_PIPELINE.md

_Source → raw → normalised → stored → decided → served. Every stage records what it did, and
every stage can fail without taking the next one down with it._

---

## 1. The shape

```
  NSE announcements JSON ─┐
  NSE bhavcopy zip       ─┼─► adapter ─► normalise ─► SQLite store ─► workspace
  NIFTY 50 CSV           ─┘                 │              │              │
  bundled fixtures      ───────────────────┘              │              │
                                                        │              │
                                          provenance + freshness      │
                                          on every record            │
                                                                    │
  filing PDF ─► pypdf ─► strip boilerplate ─► full text ─────────────┘
                                                                    │
                                                       System-1 typed decision
                                                                    │
                                              raw payload stored, never rewritten
```

The store is the boundary. Everything upstream is replaceable — a different exchange, a licensed
vendor, a CSV on disk — because nothing downstream reads a source directly.

---

## 2. Adapters

Each adapter in `src/divya/data/` owns exactly one source and produces records carrying
provenance. An adapter that cannot satisfy its own contract raises rather than degrading into
partial data.

| adapter | source | output |
|---|---|---|
| `nse.NseAnnouncements` | corporate announcements JSON | `Announcement` with `to_observation()` |
| `nse.NseBhavcopyLive` | daily EOD zip | rows + `previous_trading_day()` probe |
| `nse.NseIndexConstituents` | NIFTY 50 CSV | rows |
| `filings.get_filing_text` | attached PDF | `FilingText` with source and expansion recorded |
| `sources.FixtureSource` | in-repo JSONL | observations, `is_simulated` forced `True` |
| `store.Store` | SQLite | events, runs, decisions, disagreements |

### Every adapter carries its licence verdict

`LicenceVerdict` is a field on the adapter, not a line in a doc. `redistribution_allowed` is
`False` for every live source, and `divya doctor` prints it. A future contributor cannot add a
source without making a statement about its rights, because the constructor requires one.

---

## 3. Three things that are easy to get wrong, and how they are handled

### Provenance is stored, not reconstructed

Every event row carries `source_id`, `source_url`, `announced_at`, `retrieved_at`,
`is_simulated`, `content_hash` and `dedup_key`. `announced_at` and `retrieved_at` are different
facts: the exchange says when it happened, we say when we fetched it. Collapsing them is how a
terminal ends up presenting a cached page as live.

### Freshness is computed, never stored

No `is_fresh` column exists, because a stored flag is wrong the moment it is written. Freshness
is a function of `retrieved_at` against a window, evaluated in three places — the state, the
terminal view, and the API — and all three fail toward "not fresh". A future timestamp, an
unreadable timestamp and an empty state are all treated as not-fresh; the red team found the
first two reading as *fresh* and both are fixed.

### De-duplication happens before the engine, not after

`SharedState.unique_observations()` collapses on `dedup_key` before text reaches System-1. The
red team showed eight copies of a 370 kB document reaching the engine in full. A market terminal
ingesting a window will see the same filing twice; paying twice is a cost bug and weighting
toward whichever copy arrived last is a correctness bug.

---

## 4. Normalisation, and where judgement enters

NSE supplies a `desc` — a human-curated filing classification. It is mapped to the protocol's
`event_type` by an **explicit 107-entry table** in `nse_taxonomy.py`, with every unmapped class
falling through to `unresolved`.

Three rules, each earned:

1. **Unmapped means `unresolved`, never `other`.** Defaulting to `other` would manufacture a
   label, and the failure would be indistinguishable from the model being right.
2. **`unresolved` is not `other`.** `other` means "resolved, and genuinely none of the above".
   Collapsing them makes it impossible to measure how often the system correctly says "I cannot
   tell", which is a first-class claim for this product.
3. **Container classes are unresolved.** `Outcome of Board Meeting` is 456 records — the largest
   event-bearing class — and the text frequently does not state the outcome. Guessing would be
   inventing a label.

**The mistake this table was corrected for:** the first draft mapped `Trading Window` →
`regulatory_action`. A trading-window closure is routine SEBI PIT compliance, not a sanction, and
it is the second-largest class in the feed. Left uncorrected it would have put a false label on
**47% of the evaluation population**. It was caught by reading the frequency table before
trusting the mapping.

---

## 5. Filing text: the one real enrichment

`attchmntText` is a one-line summary — median **154 characters**. A materiality judgement needs
figures, and summaries routinely omit them.

`filings.get_filing_text()` fetches the attached PDF, extracts with `pypdf`, strips the exchange
address block, and caches by the exchange's own `seq_id`. Measured: **107 of 120** evaluation
items upgraded, **25.3×** more text.

Three failure modes, handled explicitly:

| mode | handling | why |
|---|---|---|
| no text layer (scanned image) | fall back to the summary, record the reason | an empty document would be decided on as "nothing to decide" — the worst available outcome |
| boilerplate | stripped | a third of page one, invariant, and the most expensive text in the document |
| fetch cost | cached by `seq_id` | PDFs run to megabytes and a filing is fetched at most once |

**Stored decisions are not recomputed when a filing is upgraded.** Changing the text a decision
was made on, after the fact, would make that decision a lie.

---

## 6. Failure handling

| stage | failure | behaviour |
|---|---|---|
| fetch | host unreachable, non-JSON, HTML error page with HTTP 200 | `SourceError` with the status; the CLI reports and exits non-zero; the store is untouched |
| bhavcopy | payload is not a zip | specific error naming the URL shape and circular NSE/MSD/76457, because the endpoint genuinely changes |
| holidays | requested day has no file | probes back up to 10 days; reports which day it used |
| dedup | `seq_id` missing | falls back to the URL, then to a content hash |
| PDF | unreachable, oversized, not a PDF, no text layer | summary fallback with the reason recorded on the row |
| store | write failure | transaction rolls back; the CLI exits non-zero |
| System-1 | missing or raising | `NullSystem1` / caught, `error` termination, visible degradation |
| backend | unreachable | frontend shows the reason and the previous workspace is kept |

Ingestion is **idempotent**: re-fetching a window inserts only new `seq_id`s, so running it
twice is safe and a partially-completed run can simply be repeated.

---

## 7. What is deliberately not built

- **No BSE adapter.** Unreachable from this host — archives do not resolve, API returns 403. It
  would be an adapter written against documentation rather than against a working endpoint.
- **No historical price series adapter.** NSE's returns 503 on every path and yfinance is
  licence-restricted. bhavcopy is per-day and must be collected day by day. **There is currently
  no free exchange-sourced Indian time series**, and the architecture does not pretend otherwise.
- **No vendor adapter.** A licensed feed would slot in behind the same interface, but building a
  speculative adapter for a service we cannot test is not useful.
- **No entity resolution across sources.** Symbols are NSE's own; there is no ISIN-to-symbol
  crosswalk, because there is no second source to reconcile against.
