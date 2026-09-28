"""Live NSE sources: corporate announcements, EOD bhavcopy, and the index constituent list.

Everything here was verified by direct fetch from this machine on 2026-09-28. The evidence,
including what failed, is in `research/REAL_DATA_SOURCES.md`.

**What works, and needs no cookies or session:**

    https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
    https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
    https://archives.nseindia.com/content/indices/ind_nifty50list.csv

The announcements endpoint is the important one. A single month-long window returns ~14,800
records carrying `attchmntText` (the filing itself), `desc` (NSE's own pre-classified event
type, 104 distinct values), `smIndustry`, `hasXbrl` and a PDF link. That `desc` field is a
published, human-curated label, which makes it a far better evaluation target than anything we
could annotate ourselves -- with the caveat, stated everywhere it is used, that agreeing with
NSE's taxonomy is not the same as being right.

**What does not work, so nothing is built on it:** the NSE historical price API returns 503 on
every path tried, and the entire BSE estate is unreachable from this host (archives do not
resolve; the API returns 403). Historical price series come from a separate adapter, and BSE
is not planned around.

**Licence position.** Every endpoint here is exchange-proprietary and no reuse grant was
located. That is fine for running this software yourself and is *not* clearance to ship it
with the data baked in. `LicenceVerdict.redistribution_allowed` is False for all of them and
`divya export` will refuse to emit a redistributable bundle from a live-sourced state. See
`docs/loop/BLOCKERS.md` B-002.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from divya.data.sources import (
    BROWSER_UA,
    LICENSE_REGISTER,
    LicenceVerdict,
    SourceError,
    _require_licensed,
)
from divya.runtime.state import Observation

API = "https://www.nseindia.com"
ARCHIVES = "https://nsearchives.nseindia.com"
STATIC = "https://archives.nseindia.com"

#: How many announcements to take at most from one window. A full year returns ~114 MB and
#: truncates, so the fetch is chunked by month by the caller rather than by guessing here.
MAX_RECORDS = 20_000


def _headers() -> dict[str, str]:
    # No browser UA => no response at all. Measured, not assumed.
    return {"User-Agent": BROWSER_UA, "Accept": "application/json,text/plain,*/*"}


@dataclass
class Announcement:
    """One corporate announcement, in the shape the rest of Divya consumes."""

    seq_id: str
    symbol: str
    company: str
    industry: str
    desc: str
    text: str
    pdf_url: str | None
    announced_at: str
    has_xbrl: bool
    raw: dict[str, Any]

    @classmethod
    def from_nse(cls, r: dict[str, Any]) -> Announcement | None:
        text = (r.get("attchmntText") or "").strip()
        symbol = (r.get("symbol") or "").strip()
        if not text or not symbol:
            # Without text or an identity there is nothing to decide about, and a record with
            # an empty body would be scored as a model failure rather than a data gap.
            return None
        return cls(
            seq_id=str(r.get("seq_id") or r.get("sort_date") or ""),
            symbol=symbol,
            company=(r.get("sm_name") or symbol).strip(),
            industry=(r.get("smIndustry") or "unknown").strip(),
            desc=(r.get("desc") or "Unclassified").strip(),
            text=text,
            pdf_url=r.get("attchmntFile"),
            announced_at=_parse_nse_time(r.get("sort_date") or r.get("an_dt")),
            has_xbrl=str(r.get("hasXbrl", "")).lower() == "true",
            raw=r,
        )

    def to_observation(self) -> Observation:
        header = (
            f"NSE corporate announcement.\n"
            f"Company: {self.company} ({self.symbol})\n"
            f"Industry: {self.industry}\n"
            f"Exchange category: {self.desc}\n"
            f"Announced: {self.announced_at}\n"
            f"Source document: {self.pdf_url}\n"
            f"---\n"
        )
        return Observation(
            kind="corporate_announcement",
            source_id=f"nse_ann:{self.symbol}:{self.seq_id}",
            source_url=self.pdf_url,
            content=header + self.text,
            published_at=self.announced_at,
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
            # Genuinely fetched, not simulated. Whether it may be *redistributed* is a
            # separate question answered in the licence register, not by this flag.
            is_simulated=False,
        )


def _parse_nse_time(value: str | None) -> str:
    if not value:
        return datetime.now(UTC).isoformat(timespec="seconds")
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC).isoformat()
        except ValueError:
            continue
    return datetime.now(UTC).isoformat(timespec="seconds")


class NseAnnouncements:
    """Corporate announcements from the NSE JSON API.

    Fetch a window in chunks. A month is ~14.8k records and ~10 MB, which is comfortable; a
    year is ~114 MB and truncates, so the window is the caller's to choose and the chunking is
    the caller's responsibility. This class reports honestly rather than silently returning a
    partial window: ``truncated`` is set when the response hit the cap.
    """

    source_id = "nse_announcements"

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout
        self.licence: LicenceVerdict = _require_licensed(self.source_id)

    def url_for(self, start: date, end: date) -> str:
        return (
            f"{API}/api/corporate-announcements?index=equities"
            f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"
        )

    def fetch_raw(self, start: date, end: date) -> list[dict[str, Any]]:
        url = self.url_for(start, end)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=_headers())
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise SourceError(f"NSE announcements fetch failed for {start}..{end}: {exc}") from exc
        except ValueError as exc:
            raise SourceError(f"NSE announcements returned non-JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise SourceError(
                f"expected a JSON list, got {type(payload).__name__}. NSE sometimes answers "
                f"an error page with HTTP 200; treat this as an outage, not an empty window."
            )
        return payload

    def fetch(
        self, start: date, end: date, limit: int | None = None
    ) -> tuple[list[Announcement], bool]:
        """Return ``(announcements, truncated)``.

        Sorted newest-first and de-duplicated by ``seq_id``: the API can repeat a record
        across a window boundary, and a duplicated filing would be scored twice -- inflating
        every count and making two arms look more alike than they are for free.
        """
        raw = self.fetch_raw(start, end)
        truncated = len(raw) >= MAX_RECORDS

        seen: set[str] = set()
        out: list[Announcement] = []
        for r in raw:
            a = Announcement.from_nse(r)
            if a is None:
                continue
            if a.seq_id in seen:
                continue
            seen.add(a.seq_id)
            out.append(a)
            if limit and len(out) >= limit:
                break
        out.sort(key=lambda a: a.announced_at, reverse=True)
        return out, truncated


class NseIndexConstituents:
    """The NIFTY 50 constituent list. Useful as a default liquid universe."""

    source_id = "nse_index"

    def __init__(self, timeout: float = 45.0) -> None:
        self.timeout = timeout
        self.licence = LicenceVerdict(
            source_id=self.source_id,
            name="NSE index constituent list (NIFTY 50)",
            access="Static CSV over HTTPS",
            redistribution_allowed=False,
            attribution_required="Attribution to NSE required.",
            terms_url="https://www.nseindia.com/terms",
            verdict="UNRESOLVED, same reasoning as every other NSE endpoint.",
            verified_on="2026-09-28",
        )
        LICENSE_REGISTER[self.source_id] = self.licence

    def fetch(self) -> list[dict[str, str]]:
        url = f"{STATIC}/content/indices/ind_nifty50list.csv"
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=_headers())
                resp.raise_for_status()
                text = resp.content.decode("utf-8-sig", errors="replace")
        except httpx.HTTPError as exc:
            raise SourceError(f"NIFTY 50 list fetch failed: {exc}") from exc
        return list(csv.DictReader(io.StringIO(text)))


class NseBhavcopyLive:
    """Daily EOD prices. The archive URL shape is unstable -- re-verify after 2026-10-12.

    Kept separate from :class:`divya.data.sources.NseBhavcopy` only in name; the behaviour is
    the same, and the older class is retained because the synthetic-fixture path and the
    licence register already reference it.
    """

    source_id = "nse_bhavcopy"

    def __init__(self, timeout: float = 45.0) -> None:
        self.timeout = timeout
        self.licence = _require_licensed(self.source_id)

    def url_for(self, day: date) -> str:
        return f"{ARCHIVES}/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"

    def fetch_rows(self, day: date) -> list[dict[str, str]]:
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(self.url_for(day), headers=_headers())
                resp.raise_for_status()
                payload = resp.content
        except httpx.HTTPError as exc:
            raise SourceError(f"bhavcopy fetch failed for {day}: {exc}") from exc
        if not payload.startswith(b"PK"):
            raise SourceError(
                f"bhavcopy for {day} returned {len(payload)} non-zip bytes; the URL shape has "
                f"probably changed (circular NSE/MSD/76457 re-organises it on 2026-10-12)"
            )
        with zipfile.ZipFile(io.BytesIO(payload)) as zf, zf.open(zf.namelist()[0]) as fh:
            return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))

    def previous_trading_day(self, day: date, lookback: int = 10) -> date | None:
        """Walk back to the most recent day that actually has a file.

        Indian markets close on weekends and on a published holiday list, so "yesterday" is
        usually not a trading day. A hardcoded holiday calendar would be wrong twice a year;
        probing is cheap and stays correct without maintenance.
        """
        for i in range(1, lookback + 1):
            from datetime import timedelta

            cand = day - timedelta(days=i)
            if cand.weekday() >= 5:
                continue
            try:
                if self.fetch_rows(cand):
                    return cand
            except SourceError:
                continue
        return None
