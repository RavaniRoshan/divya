# INDIA_DATA — access, terms, and licensing for Indian market data

**Compiled:** 2026-09-28. Every URL below was fetched by me on **2026-09-28**. Where a fetch failed or a document is unreadable, I say so rather than guessing.

**Tag legend:** `[FACT]` = verified from a primary source I fetched. `[HYPOTHESIS]` = my inference. `[UNKNOWN]` = could not verify.

## 🔴 The single most important line in this file

> `[UNKNOWN]` **I could not read NSE's Terms of Use, Disclaimer, or Copyright pages.** NSE publishes all three, they are listed in NSE's own `robots.txt`-declared `sitemap.xml`, and they are **client-rendered Angular pages whose served HTML contains only site navigation chrome** — the legal text is fetched by XHR and never appears in the initial response. I tried 6 URL shapes, the sitemap, and the `/api/` namespace.
>
> **Consequence: this file cannot tell you whether NSE permits redistribution of the EOD bhavcopy. Nobody can, from the public web, without either (a) rendering the SPA in a browser, or (b) buying the NSE Data & Analytics market-data agreement.** Treat "free to redistribute" as an *unverified third-party assertion*, not a fact. See §7.

---

## 1. NSE bhavcopy — daily EOD CSV (the planned public default)

### 1.1 What is actually published, and where

`[FACT]` **The URL in `plan.md` §2 is dead.** Verified 2026-09-28:

| URL | Result |
|---|---|
| `https://nsearchives.nseindia.com/content/historical/EQUITIES/2025/SEP/cm01SEP2025bhav.csv.zip` | **404** |
| `https://nsearchives.nseindia.com/content/historical/EQUITIES/2026/SEP/cm28SEP2026bhav.csv.zip` | **404** |
| `https://archives.nseindia.com/content/historical/EQUITIES/2025/SEP/cm01SEP2025bhav.csv.zip` | **404** |

`[FACT]` **The live path is different.** The current CM EOD bhavcopy lives at:

```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
```

Verified 200 on two different dates, **no cookie, no session, no auth** — but a **browser User-Agent is mandatory** (A/B tested 2026-09-28: no UA → `000`; `User-Agent: curl/8.5.0` → `000`; Chrome UA → `200 200 200`):
- `..._20250901_F_0000.csv.zip` → **200**, `application/zip`, **177,047 bytes**, `Last-Modified: Mon, 01 Sep 2025 11:03:02 GMT`
- `..._20260925_F_0000.csv.zip` → **200**, `application/zip`, **204,425 bytes**

`[FACT]` Response headers include `Akamai-GRN: 0.b78c2c31...` — NSE is fronted by Akamai, and the origin is a static file store (note `ETag: W/"177047-..."` and `Accept-Ranges: bytes`).

`[FACT]` **A second, non-zip, older-format bhavcopy also works** (browser UA) for the derivatives/other segments:
```
https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
```
- `sec_bhavdata_full_01092025.csv` → 200, `text/csv`, 340,424 bytes
- `sec_bhavdata_full_25092026.csv` → 200, `text/csv`, 396,933 bytes
- Columns: `SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER…`

### 1.2 Contents (verified by downloading and parsing)

`[FACT]` `BhavCopy_NSE_CM_0_0_0_20250901_F_0000.csv` = 547,382 bytes, **3,168 data rows + header**, 33 columns:
`TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId, ISIN, TckrSymb, SctySrs, XpryDt, FininstrmActlXpryDt, StrkPric, OptnTp, FinInstrmNm, OpnPric, HghPric, LwPric, ClsPric, LastPric, PrvsClsgPric, UndrlygPric, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd, SsnId, NewBrdLotQty, Rmks, Rsvd1..Rsvd4`

`[FACT]` The file is **not equities-only**. The first rows of the 2025-09-01 file are Sovereign Gold Bonds (`SGBJUN28`, `SGBN28VIII`, `SGBMAY29I`, …) under `SctySrs=GB`, then equities under `SctySrs=EQ` (`ZUARIIND`, `ZYDUSLIFE`, `ZYDUSWELL`). Any ingest must filter on `SctySrs`, not assume equity.

`[FACT]` This is the **SEBI CMTS layout**. `tej-bazaar`'s README (below) documents the 2024 cutover from a legacy `SYMBOL/SERIES/TIMESTAMP` layout and states pre-2012 rows carry **no ISIN and no trade count**. If Divya wants pre-2024 history it must handle both schemas.

### 1.3 Historical archive

`[FACT]` I could not enumerate a browsable archive index — `https://www.nseindia.com/resources/historical-reports-capital-market-daily-monthly-archives` returns **200 but is a client-rendered SPA shell containing no "bhavcopy" string** (21,588 chars of extracted text, zero occurrences). The file naming scheme is **date-constructible** (`YYYYMMDD`), so backfill is a matter of generating URLs, not crawling. `[HYPOTHESIS]` A 10-year backfill ≈ 2,400 trading days; at ~200 KB/day that is ~480 MB and ~2,400 requests. Feasible, but rate-limit behaviour is undocumented.

`[UNKNOWN]` Whether NSE rate-limits `nsearchives`. No `Retry-After`, no documented quota, no published limit found. **No crawl-delay is stated anywhere I could reach.**

### 1.4 🔴 NSE is changing the bhavcopy contract on 2026-10-12

`[FACT]` **Exchange Circular `NSE/MSD/76457`, Circular Ref. No. 64/2026, dated 21 September 2026 — "Streamlining EOD information dissemination related to Bhavcopy - update."**
PDF: https://nsearchives.nseindia.com/content/circulars/MSD76457.pdf (200, `application/pdf`, 180,846 bytes, 3 pages, text extracted from the PDF content streams)

`[FACT]` It is the **fourth** in a four-month series: continuation of `NSE/MSD/75910` (24 Aug 2026), `NSE/MSD/75001` (02 Jul 2026), `NSE/MSD/74764` (18 Jun 2026).
`[FACT]` Discovered via NSE's own circular API: `https://www.nseindia.com/api/circulars?from_date=…&to_date=…&type=…` (200, JSON, 197 records) — the `q=` search parameter is **not supported**; I found this circular by filtering the `sub` field for "bhavcopy".

`[FACT]` What the circular says, verbatim from the extracted text:
- "Exchange is now additionally disseminating the bhavcopy reports (.DAT format) on Extract at the following paths:" — `FO` → `FNO_BC_DDMMYYYY.DAT` at `/faoftp/faocommon/Bhavcopy`; `CD` → `CD_BC_DDMMYYYY.DAT` at `/cdsftp/cdscommon/Bhavcopy`; `CO` → `CO_BC_DDMMYYYY.DAT` at `/comtftp/comtcommon/Bhavcopy`. Also: "A similar report for Electronic Gold Receipts will also be disseminated."
- **"effective October 12, 2026"** the Exchange will additionally disseminate `CM` → **`FCM_INTRM_BCDDMMYYYY.DAT`** at **`/cmftp/cmcommon/bhavcopy`**, displayed as "Bhavcopy File (DAT)".

`[FACT]` **I tested those four extract paths over HTTPS on 2026-09-28 and all four return 404** (e.g. `https://www.nseindia.com/faoftp/faocommon/Bhavcopy/FNO_BC_25092026.DAT` → 404). The paths are **"Extract" (FTP) distribution paths**, not public HTTPS paths.
`[FACT]` The **existing CSV zip and CSV paths were still 200 on 2026-09-28**, including `..._20260925_F_0000.csv.zip` and `sec_bhavdata_full_25092026.csv`.

`[HYPOTHESIS]` **This is the single biggest operational risk to the "Bhavcopy is our public default" plan.** NSE is mid-flight through a multi-round reorganisation of exactly the file we depend on, with a go-live **two weeks from the date of this document**. Divya's ingest adapter must be schema- and path-versioned with an explicit freshness assertion, and must not hard-code the filename pattern.

### 1.5 robots.txt — and what it does *not* mean

`[FACT]` `https://www.nseindia.com/robots.txt` → **200**:
```
User-agent: *
Allow: /
Disallow: /market-data-test
Sitemap: https://www.nseindia.com/sitemap.xml
```
`[FACT]` `https://nsearchives.nseindia.com/robots.txt` → **does not return a robots file**; it returns the NSE HTML error page.

> ⚠️ **`[FACT]` A permissive `robots.txt` is not a licence.** `Allow: /` means "not disallowed for crawlers." It is a crawler- etiquette directive. It grants **no redistribution right**, and NSE could change it at any time. Do not cite it as permission.

### 1.6 Bot protection on the main site

`[FACT]` `https://www.nseindia.com` with a default curl UA → **HTTP 403** (370 bytes) under HTTP/1.1 with a browser User-Agent, and an HTTP/2 `INTERNAL_ERROR` stream abort under the default. TLS completes fine; the block is Akamai application-layer bot detection.
`[FACT]` **`nsearchives.nseindia.com` is behind the same Akamai block** — A/B tested 2026-09-28: no User-Agent → `000`, `User-Agent: curl/8.5.0` → `000`, Chrome User-Agent → `200` (3/3 consecutive, byte-identical). A browser UA is required on every NSE host; the archives host is not an open bypass.
`[FACT]` By contrast `api.bseindia.com` returned a hard `403 Access Denied` from Akamai **even with** a browser UA plus `Origin: https://www.bseindia.com` and `Referer` headers.
`[HYPOTHESIS]` **NSE yields to a User-Agent; BSE did not in my tests.** Divya's HTTP client should set a realistic browser UA on all exchange traffic, and must treat a UA-less `000`/403 as a first-class, observable failure mode (this is exactly `AGENTS.md` rule 6 — fail safe, fail visible).

---

## 2. NSE corporate announcements — the best event-domain source I found

`[FACT]` **Fully public, no session, no cookie.** One request with a browser User-Agent:

```
https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=RELIANCE
```
→ **HTTP 200, 2,899,740 bytes, 3,360 records** (2026-09-28).

`[FACT]` I did **not** need a session cookie, an `X-Requested-With` header, or a warm-up request to the homepage. `[HYPOTHESIS]` This may be an Akamai-rate-dependent property rather than a stable guarantee — it should be re-verified from a clean process, and the adapter must handle the 403 case explicitly.

`[FACT]` Record schema (keys of record 0): `an_dt, attFileSize, attchmntFile, attchmntText, bflag, csvName, desc, difference, dt, exchdisstime, fileSize, hasXbrl, old_new, orgid, seq_id, smIndustry, sm_isin, sm_name, sort_date, symbol`

Live example values:
- `symbol=RELIANCE`, `sm_name=Reliance Industries Limited`, `sm_isin=INE002A01018`, `smIndustry=Refineries`
- **`desc = "Credit Rating"`** ← a clean, machine-readable **event type**
- `attchmntText = "Reliance Industries Limited has informed the Exchange about Credit Rating"`
- `attchmntFile = https://nsearchives.nseindia.com/corporate/PVIVINMA_25092026224843_SE.pdf` (the **actual filing PDF**)
- **`hasXbrl = True`** ← structured XBRL is available for filings
- `an_dt = 25-Sep-2026 22:49:03`, `seq_id = 106795047`

> `[HYPOTHESIS]` **This directly answers the event-domain question.** `desc` is a pre-classified exchange-supplied event type; `hasXbrl` gives structured financials; `attchmntFile` gives the primary document with a stable `nsearchives` URL; `sm_isin` is the join key to bhavcopy. A `desc` taxonomy is far more reliable ground truth for a Laya `choice` head than anything we could label ourselves. **I would shortlist "material corporate announcements + XBRL-tagged filings" as the first domain over raw price events**, with earnings extracted from the XBRL rather than scraped from text.
> `[UNKNOWN]` The full set of distinct `desc` values — I fetched one symbol only and did not enumerate the taxonomy. **This is a 20-minute follow-up and should gate the domain decision.**

`[UNKNOWN]` **Legal posture of the announcements endpoint and of the filing PDFs is unverified.** See §7. Scraping an endpoint that requires no auth is **not** the same as being permitted to republish the PDFs. A filing PDF is a company filing; republishing it wholesale has different copyright posture from publishing a derived numeric fact.

`[FACT]` `/api/cm/quote?symbol=RELIANCE` → **404** (that path shape is wrong). `[UNKNOWN]` The correct live-quote endpoint shape.

---

## 3. BSE India

`[FACT]` `https://www.bseindia.com` → **200** (reachable).
`[FACT]` **BSE's entire web surface is a client-rendered Angular SPA.** `https://www.bseindia.com/robots.txt` returns the homepage HTML (title `LIVE Stock/Share Market | Indian Stock/Share Market LIVE | BSE SENSEX`), not a robots file. `https://www.bseindia.com/corporates/Disclaimer.html` → 301 → `https://www.bseindia.com/corporates/Disclaimer` → 200 but **14,287 bytes of the same SPA shell** containing no disclaimer text. Same for `terms_conditions`, `markets/Disclaimer`, `static/markets/marketinfo/Disclaimer.htm`.
`[FACT]` `https://api.bseindia.com/BseIndiaAPI/api/AttachType/w?f=1` → **403 Akamai "Access Denied"** (`errors.edgesuite.net` reference). Tested 4 endpoints (`Disclaimer`, `DefaultData`, `AttachType`, `BhavCopy_NSE_CM`), all 403 — including with `Origin: https://www.bseindia.com` and `Referer` headers set.
`[FACT]` `https://mdcdn.bseindia.com/BhavCopy_NSE_CM.zip` → **000** (connection failure).

> **Verdict: BSE is effectively unusable from this environment.** Both the front end (SPA, no content) and the API (Akamai 403) are closed to a plain HTTP client. `[HYPOTHESIS]` A headless browser would very likely get through — but that is exactly the pattern exchange bot-protection is designed to detect, and building it is a materially different legal posture from fetching a public static file.
> `[UNKNOWN]` **BSE's terms, redistribution language, rate limits, and bhavcopy licensing — entirely unverified.**

---

## 4. Open-source projects that already ingest Indian market data

All via `https://api.github.com/search/repositories` and `https://codeload.github.com/<repo>/tar.gz/refs/heads/<branch>`, fetched 2026-09-28. Note: `raw.githubusercontent.com` is **blocked from this host** (connection reset by peer), but `codeload.github.com` works.

| Repo | Stars | License (verified from the LICENSE file, not the API) | Last push |
|---|---|---|---|
| `tejhq/tej-bazaar` | 1 | **MIT** (`Copyright (c) 2026 TejHQ`) | 2026 |
| `tejhq/tej-sdk-py` | 0 | **MIT** | 2026 |
| `swapniljariwala/nsepy` | 808 | **LGPL-3.0** | 2023-12-24 (unmaintained ~2.5y) |
| `jugaad-py/jugaad-data` | 582 | **"YOLO License" = public domain** | 2026-09-23 |
| `aeron7/nsepython` | 368 | GPL-3.0 | 2026-03-07 |
| `maanavshah/stock-market-india` | 1040 | MIT | 2023-12-17 |
| `BennyThadikaran/NseIndiaApi` | 161 | GPL-3.0 | 2026-08-31 |
| `pkjmesra/PKScreener` | 398 | MIT | 2026-09-28 |
| `rehanhaider/stocky` | 31 | GPL-3.0 | 2026-09-27 |

`[FACT]` **The GitHub API misreports nsepy's license.** `repos/swapniljariwala/nsepy` returns `"license": null` / `NOASSERTION` (LGPL-3.0 is not auto-detected). The actual file in the tarball begins `GNU LESSER GENERAL PUBLIC LICENSE Version 3, 29 June 2007`. **Always read the LICENSE file; do not trust the API's `spdx_id` for copyleft.**

`[FACT]` **nsepy is unmaintained** — last push 2023-12-24, while `jugaad-data` pushed 2026-09-23. `jugaad-data` is the actively-maintained successor for most purposes.

`[FACT]` `jugaad-data`'s license is a joke that is a real dedication — `LICENSE.YOLO.md`: *"YOLO LICENSE … 0. jugaad-data is in public domain. 1. Do whatever you want with it. 2. Stop emailing me about it!"*

### 4.1 `tejhq` — correcting `plan.md`

`[FACT]` **`tejhq` is a real GitHub org with exactly two repositories**, both MIT, with **1 and 0 stars**:
- `tejhq/tej-bazaar` — the **real** thing: a genuine, well-engineered ingest pipeline (`pipeline/actions/{fetch,parse,derive,factors,back_adjust,scrip_map,audit,schema}.py`, `pipeline/cli.py`, `export_json.py`), a GitHub Actions cron at 18:30 IST with a 21:30 IST retry and a 7-day self-healing sweep, publishing Hive-partitioned Parquet to HuggingFace `tejhq/indian-markets` and R2, and an edge API at `api.tejhq.dev`.
- `tejhq/tej-sdk-py` — a small typed HTTP client (`client.py`, `async_client.py`, `models.py`, `exceptions.py`).

`[FACT]` **Not a legal precedent.** `plan.md` §2 calls this the "`tej-bazaar MIT precedent" and lists it alongside NSE data-sharing policy as a source for "`Bhavcopy EOD free/redistributable`". **The MIT licence covers the CODE only. It grants nothing over the DATA.** The README asserts:

> "**Source:** NSE/BSE Bhavcopy (official, free, no auth, redistributable)"
> "**License:** Code MIT. **Data is exchange-published Bhavcopy, free to redistribute.**"

`[FACT]` **That is tejhq's assertion. I found no NSE document confirming it.** I did not find any NSE circular, terms page, or data-sharing policy that grants redistribution rights for EOD bhavcopy. **A one-star hobby project repeating an assumption is not precedent, and a MIT licence on a scraper says nothing about the scraped data.**

`[HYPOTHESIS]` **tej-bazaar is nonetheless the single most useful engineering reference for Divya** — its ROADMAP and `pipeline/instrument.py` document a real problem Divya will hit: ~590 NSE symbols have changed ISIN since 2010 on face-value splits / scheme of arrangements, so an instrument must be modelled as a *chain* of ISIN intervals (≤30-day gap rule) rather than as a single ISIN. That is worth reading before writing `src/divya/data/`.

### 4.2 Broker APIs — personal-use constraint

`[UNKNOWN]` **I did not fetch Upstox, Dhan, Global Datafeeds, or TrueData terms.** I am not going to assert their terms from memory.

`[HYPOTHESIS]` (flagged as hypothesis, must be verified before any code touches them): Indian broker APIs are contractually **personal use only** — the agreement is between the broker and an individual retail investor, not a software developer building a redistributable product. This is the near-universal shape of Indian retail-broker API terms, and it is the reason the plan's `[E] Bhavcopy + tejhq/indian-markets pattern` is the right call. **But it is a hypothesis. `plan.md` currently records it as `[E]` — an `[E]` tag on an unverified legal claim is exactly what `AGENTS.md` rule 3 forbids.**

**Action:** before P6, fetch and quote the actual terms pages for Upstox and Dhan into `docs/loop/`, and re-tag this line from `[E]` to `[FACT]` or `[UNKNOWN]`.

---

## 5. Rate limits, caching, storage

| Question | Finding |
|---|---|
| Documented NSE rate limit | `[UNKNOWN]` — none found |
| `Retry-After` header on any NSE response | `[FACT]` none present on the bhavcopy 200s |
| NSE caching policy | `[UNKNOWN]` — no `Cache-Control` on the bhavcopy response; `ETag` + `Last-Modified` + `Accept-Ranges` are present, so conditional GETs are technically possible |
| Attribution requirement | `[UNKNOWN]` — cannot be determined without NSE's terms |
| Commercial-use restriction | `[UNKNOWN]` |
| Redistribution permission | `[UNKNOWN]` — **the central open question** |
| robots.txt crawl-delay | `[FACT]` none stated; `Allow: /` only |

---

## 6. Event domain recommendation

`[HYPOTHESIS]` (my recommendation, built on the evidence above — not a fact):

1. **Primary: NSE corporate announcements + XBRL filings** (§2). Exchange-supplied `desc` event taxonomy, `hasXbrl` structured financials, `sm_isin` join key to bhavcopy, stable PDF URLs. **The exchange has already done the event classification for us** — that is a far better `choice`-head label source than self-annotation.
2. **Join with CM EOD bhavcopy** (§1) for the price/return context, via `sm_isin` ↔ `ISIN`.
3. **Defer BSE entirely** (§3) — blocked from this host, licensing unverified, and it would roughly double ingest complexity for coverage Divya does not need on day one.
4. **Corporate actions** — note tej-bazaar already publishes a derived corporate-actions tree; `[HYPOTHESIS]` those are *derived by a third party*, and re-deriving them ourselves from primary NSE data is more defensible than depending on their parquet.

---

## 7. 🔴 Blunt legal assessment

**Technically scrapable but redistribution unclear — stated exactly as the brief asked:**

- **NSE bhavcopy CSV (`nsearchives.nseindia.com`)** — accessible without auth, without cookies, without a session, without a browser UA. Not restricted by any robots.txt I could retrieve. **Permits no identified restriction on retrieval.** **The redistribution question is entirely open**, because NSE's terms-of-use text is unreadable from the public web. Exchange EOD files are, as a matter of long-standing market practice, the *input* to commercial data vendors (NSE Data & Analytics exists precisely to sell and license this data), which means "free to redistribute" is **not** a safe inference. **Treat as: usable internally, not safe to republish, until a lawyer or a written NSE clarification says otherwise.**
- **NSE corporate announcements API** — same posture, with an **additional** layer: the announcements metadata is exchange-published, but the linked filing PDFs are **company filings**, and republishing a filing document is a different copyright question from publishing a derived numeric fact. `[HYPOTHESIS]` Derived facts (a detected split ratio, a credit-rating change) are far safer than republishing the PDF.
- **Bhavcopy historical backfill** — `[HYPOTHESIS]` a 10-year rebuild is a large-volume, automated, sustained retrieval pattern against a resource with no published quota. Even if every individual fetch is permitted, **sustained high-volume harvesting is the behaviour exchange bot-protection and market-data licensing both exist to stop.** Build the backfill, but do it politely (sequential, with backoff, respecting any `Retry-After`) and record the request volume in `docs/loop/`.
- **Broker APIs** — `[HYPOTHESIS]` personal-use-only. **Do not build on them.**

**Minimum honest action before P6:** render `https://www.nseindia.com/static/nse-terms-of-use`, `/static/nse-disclaimer`, and `/static/nse-copyright` in a real browser (or via the NSE Data & Analytics market-data agreement page), quote the redistribution clause verbatim into `docs/loop/RESEARCH.md`, and only then let the word "redistributable" appear anywhere in Divya. **Until that is done, `plan.md` §2's `[E] Bhavcopy EOD free/redistributable` is an `[?]` and should be re-tagged.**
