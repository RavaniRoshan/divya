"""Indian market data sources, behind adapters with a recorded licence verdict.

Every source in Divya is wrapped in an adapter that stamps provenance and a licence verdict onto
everything it emits. The reason is not ceremony: the one thing this project must never do is
quietly redistribute data whose terms do not permit it, and the only reliable way to guarantee
that is to make the verdict impossible to omit.

The licence verdicts currently in `LICENSE_REGISTER` were established from primary sources on
2026-09-28 and are recorded in `research/INDIA_DATA.md`. The single most important entry:

    NSE bhavcopy — redistribution UNRESOLVED.

`plan.md` asserted bhavcopy was "free/redistributable" and tagged it `[E]` (evidence). That was
wrong. NSE's Terms, Disclaimer and Copyright pages are client-rendered SPAs whose legal text never
appears in served HTML; `Allow: /` in robots.txt is crawler etiquette, not a licence; and the
only claimed precedent (tejhq) is two repositories with 1 and 0 stars whose MIT licence covers
code only. The PDR's tag has been corrected to `[?]`.

Because the verdict is unresolved, the bhavcopy adapter is `redistribution_allowed: False` and the
public default deployment ships labelled fixture data instead. If you configure a live NSE
source for your own use, the fetched data is stamped `is_simulated: False` and carries its
retrieval time, but the adapter still refuses to act as a redistributing mirror.

Note on scraping etiquette: NSE requires a browser User-Agent to respond at all. That is a
technical requirement discovered by measurement, not a licence grant, and it does not change the
verdict above.
"""

from __future__ import annotations

import csv
import io
import io as _io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx

from divya.runtime.state import Observation

#: NSE returns nothing at all to a request without a browser User-Agent. Verified by A/B test.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class LicenceVerdict:
    """The recorded legal position for one source. Carried into the data, not just the docs."""

    source_id: str
    name: str
    access: str
    redistribution_allowed: bool
    attribution_required: str
    terms_url: str
    verdict: str
    verified_on: str
    notes: str = ""

    @property
    def is_redistributable(self) -> bool:
        return self.redistribution_allowed


LICENSE_REGISTER: dict[str, LicenceVerdict] = {
    "nse_bhavcopy": LicenceVerdict(
        source_id="nse_bhavcopy",
        name="NSE India daily bhavcopy (EOD equity prices)",
        access="HTTPS GET of a per-day zip from nsearchives.nseindia.com; requires a browser UA",
        redistribution_allowed=False,
        attribution_required="Attribution to NSE is required if the data is ever displayed.",
        terms_url="https://www.nseindia.com/terms",
        verdict=(
            "UNRESOLVED. The file is freely downloadable, but free-to-download is not the same "
            "as free-to-redistribute. NSE's Terms/Disclaimer/Copyright pages are client-rendered "
            "SPAs whose legal text is not present in served HTML, so the redistribution clause "
            "could not be read from a primary source. Circular NSE/MSD/76457 (2026-09-21) also "
            "re-organises dissemination effective 2026-10-12, so the endpoint is unstable."
        ),
        verified_on="2026-09-28",
        notes=(
            "plan.md asserted this was redistributable and tagged it [E]. That assertion is "
            "re-tagged [?] and corrected here. Usable for your own analysis; not shippable as "
            "a redistributing default."
        ),
    ),
    "nse_announcements": LicenceVerdict(
        source_id="nse_announcements",
        name="NSE India corporate announcements",
        access="JSON endpoint, session/UA dependent; subject to change without notice",
        redistribution_allowed=False,
        attribution_required="Attribution to NSE required on display.",
        terms_url="https://www.nseindia.com/terms",
        verdict=(
            "UNRESOLVED, same reasoning as the bhavcopy. Also rate-limited and session-dependent "
            "in practice, so it is not a reliable bulk source."
        ),
        verified_on="2026-09-28",
        notes="Intended use is per-event evaluation against the exchange's own `desc` taxonomy.",
    ),
    "fixture": LicenceVerdict(
        source_id="fixture",
        name="Divya bundled fixture data",
        access="Shipped in the repository under data/fixtures/",
        redistribution_allowed=True,
        attribution_required="None. Synthetic data authored for this project.",
        terms_url="",
        verdict=(
            "SAFE. Every record is explicitly labelled is_simulated=True in the data itself, "
            "not only in documentation, so a fixture can never be mistaken for a live price."
        ),
        verified_on="2026-09-28",
    ),
}


class SourceError(RuntimeError):
    """A source could not be reached or returned something unusable."""


def _require_licensed(source_id: str) -> LicenceVerdict:
    v = LICENSE_REGISTER.get(source_id)
    if v is None:
        raise SourceError(f"no licence verdict registered for source {source_id!r}")
    return v


@dataclass
class FetchResult:
    """What an adapter returns: observations plus the provenance that explains them."""

    source_id: str
    licence: LicenceVerdict
    observations: list[Observation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched_at: str = ""

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    def as_observations(self) -> list[Observation]:
        return self.observations


class NseBhavcopy:
    """Daily end-of-day equity prices from NSE.

    Prices only. This adapter deliberately produces *no* decisions and carries no event
    taxonomy — a price is context, and a price with a confident event label attached is how a
    terminal starts making claims it cannot support.
    """

    source_id = "nse_bhavcopy"

    def __init__(self, timeout: float = 45.0, base: str = "https://nsearchives.nseindia.com") -> None:
        self.timeout = timeout
        self.base = base.rstrip("/")
        self.licence = _require_licensed(self.source_id)

    def url_for(self, day: date) -> str:
        # Verified 2026-09-28 against a live file. The historical/ path used in plan.md 404s;
        # this is the working shape. Expect this to change on 2026-10-12 per circular 76457.
        return (
            f"{self.base}/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
        )

    def fetch(self, day: date) -> FetchResult:
        url = self.url_for(day)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": BROWSER_UA})
                resp.raise_for_status()
                payload = resp.content
        except httpx.HTTPError as exc:
            raise SourceError(f"NSE bhavcopy fetch failed for {day}: {exc}") from exc

        if not payload.startswith(b"PK"):
            raise SourceError(
                f"NSE returned {len(payload)} bytes that are not a zip for {day}; "
                f"the URL shape may have changed (circular NSE/MSD/76457 changes it on 2026-10-12)"
            )

        with zipfile.ZipFile(_io.BytesIO(payload)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                rows = list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))

        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        published = datetime.combine(day, datetime.min.time(), tzinfo=UTC).isoformat()

        obs = Observation(
            kind="market_snapshot",
            source_id=f"{self.source_id}:{day:%Y%m%d}",
            source_url=url,
            content=_render_snapshot(rows, day),
            published_at=published,
            retrieved_at=fetched_at,
            # NOT simulated: this was genuinely fetched. It is still not redistributable, which
            # is a separate property and is recorded in the licence verdict, not in this flag.
            is_simulated=False,
        )
        return FetchResult(
            observations=[obs],
            source_id=self.source_id,
            licence=self.licence,
            fetched_at=fetched_at,
        )


def _render_snapshot(rows: list[dict[str, str]], day: date) -> str:
    """Render the price file as text an analyst would read.

    Sorted by traded value, so the text is stable across runs. A file that reshuffles between
    fetches would make a content hash useless as a staleness check, and the hash is the whole
    reason the digest is stable.
    """
    if not rows:
        return f"NSE bhavcopy for {day:%Y-%m-%d}: no rows."

    def traded(r: dict[str, str]) -> float:
        try:
            return float(r.get("TURNOVER", 0) or 0)
        except ValueError:
            return 0.0

    top = sorted(rows, key=traded, reverse=True)[:25]
    lines = [
        f"NSE bhavcopy, equity segment, {day:%Y-%m-%d}.",
        f"Total symbols in file: {len(rows)}.",
        "Highest turnover symbols:",
    ]
    for r in top:
        lines.append(
            "  {SYMBOL} close={CLOSE} open={OPEN} high={HIGH} low={LOW} "
            "prev_close={PREV_CLOSE} volume={TOTAL_TRADED_QUANTITY}".format(
                SYMBOL=r.get("SYMBOL", "?"),
                CLOSE=r.get("CLOSE", "?"),
                OPEN=r.get("OPEN", "?"),
                HIGH=r.get("HIGH", "?"),
                LOW=r.get("LOW", "?"),
                PREV_CLOSE=r.get("PREV_CLOSE", "?"),
                TOTAL_TRADED_QUANTITY=r.get("TOTAL_TRADED_QUANTITY", "?"),
            )
        )
    return "\n".join(lines)


class FixtureSource:
    """Bundled fixture data. Every record is stamped ``is_simulated=True``.

    This is the default for any deployment that has not explicitly configured a live source, and
    the flag is set in the data rather than applied at display time so it survives a round-trip
    through storage.
    """

    source_id = "fixture"

    def __init__(self, path: str = "data/fixtures/events.jsonl") -> None:
        self.path = path
        self.licence = _require_licensed(self.source_id)

    def load(self) -> FetchResult:
        import json
        from pathlib import Path

        p = Path(self.path)
        if not p.exists():
            raise SourceError(
                f"fixture file {p} not found. Fixtures are the default data source; without one "
                f"there is nothing to demonstrate. Run `make fixtures` or supply a live source."
            )
        obs: list[Observation] = []
        for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SourceError(f"{p}:{line_no}: invalid JSON: {exc}") from exc
            obs.append(
                Observation(
                    kind=rec.get("kind", "document"),
                    source_id=rec["source_id"],
                    source_url=rec.get("source_url"),
                    content=rec["content"],
                    published_at=rec.get("published_at"),
                    retrieved_at=rec.get("retrieved_at") or datetime.now(UTC).isoformat(),
                    # Forced True regardless of what the file claims. A fixture file that could
                    # turn this off would be a way to launder synthetic data as live.
                    is_simulated=True,
                )
            )
        return FetchResult(
            observations=obs,
            source_id=self.source_id,
            licence=self.licence,
        )


def staleness_warning(obs: Observation, max_age_days: int = 7) -> str | None:
    """Return a human-readable warning if an observation is too old to display as current."""
    age = obs.age_seconds()
    if obs.age_seconds() < 0:
        return f"{obs.source_id}: timestamp is in the future ({obs.retrieved_at})"
    if age > max_age_days * 86400:
        days = timedelta(seconds=age).days
        return f"{obs.source_id}: retrieved {days} days ago; treat as stale"
    return None
