# Real Data Sources — Verification Report

**Date of verification: 2026-09-28.** All HTTP codes, byte counts and field names below were
obtained by actually fetching the endpoint from this machine on this date. Anything not fetched is
marked `[UNVERIFIED]`. Anything fetched and working is marked `[VERIFIED]`.

Universal curl prefix used throughout (NSE requires a browser User-Agent; without it NSE returns
nothing useful):

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
curl -s -m 30 -A "$UA" <url>
```

The User-Agent is a technical compatibility measure, not a licence grant. NSE/BSE terms are
unresolved (see §3) and are a **blocker for any product use**, not just for redistribution.

---

## 1. Master table

| source | endpoint | works today? (HTTP + evidence) | data shape / key fields | rate limits observed | licence / terms URL | redistribution OK? | cost | quality caveats |
|---|---|---|---|---|---|---|---|---|
| **NSE corporate announcements (JSON)** | `https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` | **YES — HTTP 200**, 10,458,349 B, 14,802 records for Sep-2026 `[VERIFIED]` | 19 fields. `symbol`, `sm_name`, `sm_isin`, `smIndustry`, `desc` (**pre-classified event type, 104 distinct values**), `an_dt` (timestamp), `attchmntText` (human summary), `attchmntFile` (PDF URL), `attFileSize`, `hasXbrl`, `exchdisstime`, `seq_id` | **No throttling observed** — 5 back-to-back calls all HTTP 200 (0.2–3.0 s). ~9 MB / 12.7 k records per month | NSE terms `[UNVERIFIED]` — must read before product use | **Unknown / assumed NO** — exchange data, no grant found | Free | **Best structured source found.** `desc` is a clean controlled vocabulary and maps directly onto System-1 typed decisions. Every record had `hasXbrl=true` and an attachment. |
| **NSE historical price series v3** | `https://www.nseindia.com/api/historical/cm/equity?symbol=RELIANCE&series=["EQ"]&from=...&to=...` | **NO — HTTP 503, 5/5 attempts** (with and without cookie jar, with `Referer`, with `csv=true`) `[VERIFIED FAILURE]` | n/a (Akamai/Apache "Service Unavailable" HTML, 542 B and 18,518 B) | n/a | n/a | n/a | n/a | **Server-side down or geo/IP-blocked.** Not a rate-limit problem — retries 5 s apart all failed identically. Same-day control endpoints (bhavcopy, announcements) were 200 at the time, so the failure is specific to this path. |
| **NSE bhavcopy EOD (zip)** | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` | **YES — HTTP 200** on 20260924 (203,837 B), 20260925 (204,425 B), 20260928 (206,229 B), 20260826 (203,590 B), 20250102 (171,515 B) `[VERIFIED]` | Valid zip → CSV. SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, PREV_CLOSE, TOTAL_TRADED_QUANTITY, TIMESTAMP | Not formally probed; 1 req/s acceptable in practice | NSE terms `[UNVERIFIED]` | **Unknown / assumed NO** | Free | 404 on 20260926/27 (Sat/Sun — correct) and on **20230102**, so this path is **not** a deep archive. ~3-year window at most. |
| **NSE all-indices quotes** | `https://www.nseindia.com/api/allIndices` | **YES — HTTP 200**, 114,022 B `[VERIFIED]` | `key`, `index`, `indexSymbol`, `last`, `variation`, `percentChange`, `open`, `high`… Live NIFTY 50 = 22,780.25 | Not probed | NSE terms `[UNVERIFIED]` | **Unknown / assumed NO** | Free | Live snapshot only, no history. |
| **NSE NIFTY 50 constituent list** | `https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv` | **YES — HTTP 200**, 3,352 B, 51 lines (header + 50) `[VERIFIED]` | `Company Name, Industry, Symbol, Series, ISIN Code` | Not probed | NSE terms `[UNVERIFIED]` | **Unknown / assumed NO** | Free | Stable, small, ideal for universe definition. Also 200 on `archives.nseindia.com` mirror. |
| **NSE announcements CSV (nsearchives)** | `https://nsearchives.nseindia.com/content/press/corp_anncmnts/<DATE>.csv` | **NO — HTTP 404** for `21-09-2026`, `21092026`, `2026-09-21` `[VERIFIED FAILURE]` | n/a | n/a | n/a | n/a | n/a | This legacy path is dead. Use the JSON API instead. |
| **BSE — bhavcopy / archives** | `https://archives.bseindia.com/...` | **NO — no DNS resolution** for `archives.bseindia.com`; curl exits 000 `[VERIFIED FAILURE]` | n/a | n/a | n/a | n/a | n/a | Host does not resolve from this network. |
| **BSE — api.bseindia.com** | `https://api.bseindia.com/BseIndiaAPI/api/...` | **NO — HTTP 403 "Access Denied"** on 5 distinct paths (StockReachGraph, AnnSubCategoryGetData, DefaultData, SensexData) with and without Origin/Referer `[VERIFIED FAILURE]` | n/a (Akamai block page, 410–426 B) | n/a | n/a | n/a | n/a | Akamai edge blocks this egress IP. `www.bseindia.com` HTML pages return 200 but the bhavcopy page is a 14,287 B JS shell with no data. **BSE is effectively unavailable.** |
| **yfinance (fallback)** | `yf.Ticker("RELIANCE.NS").history(...)` | **YES — real data returned** `[VERIFIED]`. RELIANCE.NS 1mo = 22 rows, TCS.NS 22, INFY.NS 22, `^NSEI` 21. `period="max"` = **7,717 rows back to 1996-01-01** | DataFrame OHLCV + Dividends. `RELIANCE.NS` last close 1197.60; `^NSEI` last 22,780.25 | None hit; 6 tickers + 1 max-history call all succeeded | Library **Apache-2.0**; underlying **Yahoo Finance ToS** `https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html` (fetched, 200) | **NO — ToS explicitly prohibits it.** See caveat | Free (unofficial) | **Licence is the problem, not the data.** Yahoo ToS §4 text fetched verbatim: *"access or collect data … from our Services using any automated means, devices, programs, algorithms or methodologies, including but not limited to robots, spiders, scrapers, data mining tools"*. Also *"personal, royalty-free, non-transferable"* software licence. Excellent for local dev; **not appropriate for a shipped product.** |
| **HF `Abhishek9045/nse-bhavcopy-data`** | `https://huggingface.co/datasets/Abhishek9045/nse-bhavcopy-data` | **YES — HTTP 200**, 82,770,335 B parquet downloaded and read `[VERIFIED]` | 3,923,492 rows × 7 cols: `Symbol, TradeDate, Open, High, Low, Close, Volume`. Range **2017-07-03 → 2026-08-05** | n/a | **No licence declared** | **NO — no licence = all rights reserved** | Free | **Data is REAL, confirmed by cross-check**: HF `RELIANCE` 2026-08-03 O/H/L/C/V = 1315.2/1319.0/1306.0/1319.0/7508023 — **byte-identical** to yfinance same day. Not synthetic. But data **stops 2026-08-05** (~2 months stale) and there is no licence. |
| **HF `Subham9126/bhavcopy`** | `https://huggingface.co/datasets/Subham9126/bhavcopy` | **YES — HTTP 200**, 862 zip files; fetched `data/2022/04-Apr/bhavcopy_01-Apr-2022.zip` (86,941 B), valid zip → real CSV `[VERIFIED]` | Full NSE bhavcopy schema: ISIN, SYMBOL, SCRIP CODE, SECURITY NAME, SERIES, OPEN/HIGH/LOW/CLOSING PRICE, LAST TRADED PRICE, PREVIOUS CLOSE PRICE, TRADED QUANTITY, TRADED VALUE, TRADE DATE, NUMBER OF TRADES, SCRIP TYPE, INSTRUMENT ID | n/a | **No licence declared** | **NO** | Free | Per-day zips mirroring real NSE files. lastModified 2026-03-30 → **stale by 6 months**. Still useful as a *verified-real offline regression corpus*. |
| **HF `AYUSHKHAIRE/indian-stocks-comprehensive-fundamentals-dataset`** | HF datasets API | **YES — HTTP 200**, 34,532 files, 4,913 downloads, lastModified 2026-09-27 `[VERIFIED]` (metadata fetched; payload not parsed) | Per-symbol weekly JSON news/fundamental records | n/a | **CC0-1.0** | **YES** | Free | **The only explicitly redistributable HF find (CC0).** Highest download count in the search. Payload content not validated — treat as `[UNVERIFIED]` on field semantics. |
| **HF `EduDevCommons/Indian_Stock_Market_Indices-SENSEX_NIFTY_etc`** | HF datasets API | **YES — HTTP 200**, 3 files, lastModified 2026-08-12 `[VERIFIED]` (metadata only) | `NIFTY, SENSEX, BANKNIFTY etc.zip` | n/a | **Apache-2.0** | **YES (with attribution)** | Free | Metadata only; payload not opened. |
| **HF `xxparthparekhxx/indian-stock-market-minute-data`** | HF datasets API | **YES — HTTP 200**, 1,335 downloads, 9 likes, lastModified 2026-01-25 `[VERIFIED]` (metadata only) | `day/` and `minute/` parquet shards | n/a | **MIT** | **YES** | Free | Most popular genuinely-licensed intraday find. Historical window unverified. |
| **SEBI circulars** | `https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListingAll=yes&cid=3` | **YES — HTTP 200**, 46,600 B, 26 table rows `[VERIFIED]` | Date, Type (Circulars/Master Circulars/Orders), Title. Latest: "Revision of Monthly Cumulative Report" 2026-05-19 | None hit | SEBI website ToS `[UNVERIFIED]` | Government publication, generally OK | Free | **Circulars only — NOT enforcement actions.** |
| **SEBI enforcement / orders** | `.../HomeAction.do?doListingAll=yes&cid=7` (Orders), `cid=14` | **HTTP 200 but unusable** `[VERIFIED — reachable, not viable]`. cid=7 = 3 rows back to 1995 (SAT appeals, stale). cid=14 = 3 rows from 2022 (prosecution/compounding lists) | No stable per-row PDF link pattern; no JSON | n/a | as above | as above | Free | **No structured enforcement feed exists.** `/enforcement-actions` = 404. `sebiweb/rss/rss.xml` = 404. Listings are JS-paginated and thin. Do not build on it. |
| **GDELT 2.0 Doc API** | `https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&format=json` | **NO — HTTP 429** on 3 attempts over ~90 s, including a 40 s backoff; both `artlist` and `timelinevol` modes `[VERIFIED FAILURE]` | n/a (429 rate-limit body, 444 B) | **IP-level rate limit, not per-request** — this box's egress IP is throttled | GDELT is genuinely free/open | Yes (open) | Free | GDELT itself is legitimately open, but **unreachable from this host**. Would need a different egress path or a self-hosted BigQuery/ngrams mirror. |
| **tejhq.com** | `https://tejhq.com/`, `https://www.tejhq.com/pricing/` | **NO — HTTP 000** (no connection) on both `[VERIFIED FAILURE]` | n/a | n/a | — | — | **Unknown — could not load the page** | Could not verify pricing. `tejhq.com` is a paid broker-API aggregator; treat as **not free**. |
| **Global Datafeeds (databulls.com)** | `https://databulls.com/` | **NO — HTTP 403** (5,658 B) `[VERIFIED FAILURE]` | n/a | n/a | — | — | — | Site blocks this IP. Bluntly: this is a **commercial** feed vendor, sold on subscription. Not a free tier. |
| **TrueData (truevalue.ml)** | `https://www.truevalue.ml/` | **NO — HTTP 000** (no connection) `[VERIFIED FAILURE]` | n/a | n/a | — | — | — | Could not verify. A known paid commercial feed. Not free. |
| **Upstox** | `https://upstox.com/developer/api-documentation/` **200**; `https://upstox.com/pricing/` **200** (352,371 B) | **YES — docs reachable** `[VERIFIED]` | Docs are a JS shell (14,790 B); pricing page is retail brokerage, not API terms | n/a | Upstox ToS `[UNVERIFIED]` | **No — broker data is personal-use-only** | Trading requires a **paid Upstox trading account**; API access is tied to that account | **Blunt: not free.** It is a *trading* API for your own account, not a market-data feed. Personal use only, no redistribution. |
| **Dhan** | `https://dhanhq.co/docs/v2/` **200** (28,904 B) | **YES — docs reachable** `[VERIFIED]` | Full API doc: Getting Started, Errors, Rate Limit, Authentication, Trading APIs, Super Orders | n/a | Dhan ToS `[UNVERIFIED]` | **No — personal use only** | Requires a **paid Dhan trading account** | **Blunt: not free.** Trading API for your own account, not a data feed. All pricing pages (`/pricing/`, `/pricing-calculator/`, `/faqs/`) returned 404 — **price `[UNVERIFIED]`**. |
| **Zerodha Kite Connect** | `https://kite.trade/docs/connect/v3/` **200**; `.../market-quotes/` **200** | **YES — docs reachable** `[VERIFIED]` | Docs cover Historical candle data, WebSocket streaming, Instruments, Portfolio | n/a | Kite ToS `[UNVERIFIED]` | **No — personal use only** | **Price `[UNVERIFIED]`** — every pricing path 404'd: `/connect/` 404, `/connect/pricing/` 404, `/connect/faq/` 404, `/connect/api/` 404, `/connect/introduction/` 404, `/pricing/` 404, `/docs/connect/v3/getting-started/` 404 | **Blunt: not free.** Kite Connect is a paid developer subscription on top of a Zerodha trading account. I could not verify the amount and will not guess. |

---

## 2. Notable negative results

- **The NSE historical price API is down** (503 ×5). This was the planned replacement for
  `content/historical/EQUITIES/...`, which also 404s. **There is currently no free NSE API path to
  historical intraday/daily time series.** EOD bhavcopy + yfinance are the only working options.
- **BSE is entirely unavailable from this host** — archives host does not resolve, API host is
  403-blocked by Akamai. Do not plan around BSE data.
- **The NSE announcements `desc` field is the single most valuable discovery.** It is a
  pre-classified, 104-value event taxonomy that needs no NLP to consume. In the Sep-2026 sample
  (14,781 records): `Shareholders meeting` 2659, `Trading Window` 1854, `General Updates` 1749,
  `Outcome of Board Meeting` 455, `Record Date` 235, `Credit Rating` 210, `Change in Management` 160,
  `ESOP/ESOS/ESPS` 171, `Bagging/Receiving of orders/contracts` 116, `Acquisition` 83,
  `Disclosure under SEBI Takeover Regulations` 66, `Corporate Insolvency Resolution Process` 63.
  These are exactly the events a System-1 typed-decision engine should fire on.
- **Chunk the announcements API by month.** A 1-year window returned 113,970,379 B and was
  truncated/unparseable. A 1-month window returns ~9 MB and parses cleanly. Backfill was verified
  at least as far back as **Jan-2024** (12,743 records for Jan-2024 alone).
- **HF has genuinely real Indian bhavcopy data**, proven by exact cross-check against yfinance
  rather than assumed. But most of it carries **no licence**, which means no redistribution and a
  real legal risk if shipped.

---

## 3. Licence position — the real blocker

Everything reachable on `nseindia.com` is **exchange proprietary data**. I found **no** public
grant permitting reuse, caching, or redistribution. The same applies to BSE. **This is a blocker
for a shipped product, not for local research.** It should be logged in `docs/loop/BLOCKERS.md`.

`yfinance` is the mirror image: technically perfect, but Yahoo's ToS (fetched and quoted above)
prohibits automated collection outright.

The two clean CC0/MIT/Apache-2.0 HF datasets are the only *licence-clean* data found, and they are
stale snapshots — not a live feed.

**Practical stance:** NSE announcements + bhavcopy are excellent for building and validating the
decision engine locally. Before any product launch, either (a) obtain a written data licence, or
(b) move the product to a data source with an explicit commercial licence (paid broker API), or
(c) position as a personal-use research tool only.

---

## 4. RECOMMENDED REAL-DATA DEPLOYMENT

Priority order. Prefer the three that definitely work.

### P0 — NSE corporate announcements (the decision substrate)

The single highest-value source. It carries pre-classified events; it is the raw material for
System-1 typed decisions, not just prices. No cookies, no warm-up, no session.

```python
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

def fetch_nse_announcements(from_date: str, to_date: str, index: str = "equities") -> list[dict]:
    """from_date/to_date are DD-MM-YYYY. Chunk to <= ~1 month; a 1-year window
    returns ~114 MB and truncates."""
    url = "https://www.nseindia.com/api/corporate-announcements"
    r = requests.get(
        url,
        params={"index": index, "from_date": from_date, "to_date": to_date},
        headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()

# ~9 MB, ~12.7k records, ~9 s
rows = fetch_nse_announcements("01-09-2026", "30-09-2026")

# Map NSE's own vocabulary onto the decision protocol. These are NSE's exact `desc` values.
EVENT_TYPES = {
    "Outcome of Board Meeting",
    "Record Date",
    "Credit Rating", "Credit Rating- Revision", "Credit Rating- New",
    "Acquisition", "Bagging/Receiving of orders/contracts",
    "Change in Management", "Resignation of Director/KMP/SMP",
    "Disclosure under SEBI Takeover Regulations",
    "Corporate Insolvency Resolution Process",
    "Disclosure of material issue",
    "ESOP/ESOS/ESPS", "Allotment of Securities",
    "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company",
    "Commencement of commercial production/operations",
    "Shareholders meeting",
}

for a in rows:
    if a["desc"] in EVENT_TYPES:
        emit_decision(
            symbol=a["symbol"],
            isin=a["sm_isin"],
            industry=a["smIndustry"],
            event_type=a["desc"],              # already classified — no NLP needed
            disclosed_at=a["an_dt"],          # as-of timestamp, mandatory
            summary=a["attchmntText"],
            source_url=a["attchmntFile"],     # always present in 14,781/14,781 sampled
            provenance="nse:corporate-announcements",
        )
```

**Store `an_dt` on every record. A filing without an as-of timestamp is a bug (AGENTS.md rule 2).**
Keep `attchmntText` as the summary and `attchmntFile` as the citation; never overwrite the raw text.

### P1 — NSE bhavcopy EOD prices (the price substrate)

```python
import io, zipfile, datetime as dt
import pandas as pd

def fetch_nse_bhavcopy(day: dt.date) -> pd.DataFrame:
    """Returns None on non-trading days (weekends/holidays 404 — that is expected,
    not an error). Archive at this path reaches back ~3 years (20230102 was 404)."""
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    url = (f"https://nsearchives.nseindia.com/content/cm/"
           f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip")
    r = requests.get(url, headers={"User-Agent": ua}, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            return pd.read_csv(f)

# Run after 18:30 IST on trading days. ~200 KB zip, sub-second.
px = fetch_nse_bhavcopy(dt.date(2026, 9, 25))
# SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, PREV_CLOSE, TOTAL_TRADED_QUANTITY, TIMESTAMP
```

### P2 — NSE index + constituent universe

```python
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Live index levels — 114 KB, all indices
indices = requests.get("https://www.nseindia.com/api/allIndices",
                       headers={"User-Agent": UA}, timeout=30).json()["data"]
nifty50 = next(i for i in indices if i["index"] == "NIFTY 50")
# {'last': 22780.25, 'variation': -360.25, 'percentChange': -1.56, 'open': 23064.9, ...}

# Universe definition — 3.3 KB, 50 rows. Fetch once a week.
universe = pd.read_csv(
    "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    names=["company", "industry", "symbol", "series", "isin"],
    header=0,
)
# company, industry, symbol, series, isin
```

### P3 — yfinance: local development and backfill only, NOT production

```python
import yfinance as yf

RELIANCE = yf.Ticker("RELIANCE.NS").history(period="max")  # 7,717 rows, back to 1996-01-01
NIFTY    = yf.Ticker("^NSEI").history(period="1mo")       # 21 rows
```

Use it for backtesting, for validating that P1 parses correctly, and for filling gaps the bhavcopy
archive cannot reach (pre-2023). **Do not wire it into a shipped product path** — Yahoo's ToS bans
automated collection. Gate it behind a `DEV_ONLY` flag so it can never become the production path
by accident (AGENTS.md rule 7: a mock must never become the production path).

### Do NOT wire up

- **NSE historical v3 API** — 503, dead today. Re-check later; it is the natural fix if it returns.
- **BSE anything** — host does not resolve / 403-blocked. No plan should depend on it.
- **GDELT** — 429 from this IP. Genuinely open and worth retrying from different egress.
- **SEBI enforcement** — no structured feed exists. The circulars listing (cid=3) does work and is
  cheap to add if circulars are decision-relevant.
- **Upstox / Dhan / Kite Connect** — not free, personal-use-only, tied to a paid trading account,
  and not data feeds. Blunt answer: wrong tool for this product.

### The three-sentence version

Wire **NSE announcements (P0)** for decisions, **NSE bhavcopy (P1)** for prices, **NSE index +
constituents (P2)** for the universe. Use **yfinance (P3)** for backfill and tests only. That is a
genuinely real, currently-fetchable, all-free Indian market stack — and it needs exactly one
browser User-Agent, no cookies, and no session.

**But log the licence blocker before building further.** All NSE endpoints above are
exchange-proprietary with no located reuse grant. They are excellent for building and validating
the decision engine; they are not yet cleared for a shipped product.
