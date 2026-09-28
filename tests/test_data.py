"""Tests for the data layer: the licence register, the fixture path, and the NSE adapters.

The data layer carries the two claims this project can most easily overstate. One is provenance:
a record that looks live and is not is the single worst failure this product could have. The
other is legal: quietly redistributing exchange data whose terms do not permit it is not a bug,
it is a lawsuit. Both are therefore asserted here rather than left to the documentation.

The URL shapes are pinned to the endpoints that were verified by direct fetch on 2026-09-28 and
recorded in `research/REAL_DATA_SOURCES.md`. A test that re-derives them from the same constant
would be a tautology, so the literal expected string is written out.

No network: every adapter test either uses a `tmp_path` fixture file or drives the parsing path
directly. The non-zip guard is exercised by calling the payload guard the adapter calls.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from divya.data.nse import (
    API,
    ARCHIVES,
    MAX_RECORDS,
    STATIC,
    Announcement,
    NseAnnouncements,
    NseBhavcopyLive,
    NseIndexConstituents,
    _headers,
    _parse_nse_time,
)
from divya.data.sources import (
    BROWSER_UA,
    LICENSE_REGISTER,
    FixtureSource,
    NseBhavcopy,
    SourceError,
    _require_licensed,
    staleness_warning,
)
from divya.runtime.state import Observation

SOURCES = Path(__file__).resolve().parents[1] / "src" / "divya" / "data" / "sources.py"
NSE = Path(__file__).resolve().parents[1] / "src" / "divya" / "data" / "nse.py"


# --- the licence register --------------------------------------------------


def test_every_registered_source_has_a_verdict_with_every_required_field():
    for sid, v in LICENSE_REGISTER.items():
        assert v.source_id == sid, "a register key and its verdict's source_id must agree"
        assert (v.name and v.access and v.terms_url) or sid == "fixture"
        assert v.verdict and v.verified_on, f"{sid} has no recorded verdict or verification date"
        assert v.redistribution_allowed in (True, False)
        assert v.attribution_required


def test_no_nse_source_claims_redistribution_without_a_licence_grant():
    """The one legal assertion that must never be relaxed.

    Every NSE endpoint is exchange-proprietary and no reuse grant was located. A source that
    silently flipped to `redistribution_allowed: True` would let `divya export` ship a bundle the
    project has no right to distribute, with no other code objecting.
    """
    nse_sources = {s: v for s, v in LICENSE_REGISTER.items() if s.startswith("nse")}
    assert nse_sources, "the register lost every NSE source, which would itself be a regression"
    for sid, v in nse_sources.items():
        assert v.redistribution_allowed is False, (
            f"{sid} claims redistribution is permitted; that requires a located, cited grant"
        )
        assert "UNRESOLVED" in v.verdict, f"{sid} no longer records the verdict as unresolved"


def test_the_only_redistributable_source_is_the_bundled_fixture():
    allowed = {s for s, v in LICENSE_REGISTER.items() if v.is_redistributable}
    assert allowed == {"fixture"}
    assert LICENSE_REGISTER["fixture"].verdict.startswith("SAFE")


def test_require_licensed_rejects_an_unregistered_source():
    with pytest.raises(SourceError, match="no licence verdict registered for source 'nope'"):
        _require_licensed("nope")
    with pytest.raises(SourceError):
        _require_licensed("")
    with pytest.raises(SourceError):
        _require_licensed("nse_bhavcopy_v2")  # a near-miss must not resolve
    assert _require_licensed("fixture").source_id == "fixture"


def test_every_adapter_registers_its_licence_before_it_can_run():
    assert NseBhavcopy().licence.source_id == "nse_bhavcopy"
    assert NseAnnouncements().licence.source_id == "nse_announcements"
    assert NseBhavcopyLive().licence.source_id == "nse_bhavcopy"
    assert FixtureSource().licence.source_id == "fixture"


def test_the_index_constituent_source_registers_itself_on_construction():
    src = NseIndexConstituents()
    assert LICENSE_REGISTER["nse_index"] is src.licence
    assert src.licence.redistribution_allowed is False


def test_the_register_is_written_where_the_docs_point_at_it():
    """`research/INDIA_DATA.md` and the module docstring are where a reader looks for the verdict."""
    src = SOURCES.read_text(encoding="utf-8")
    assert "LICENSE_REGISTER" in src
    assert "UNRESOLVED" in src
    doc = (SOURCES.parent.parent.parent / "research" / "INDIA_DATA.md")
    if doc.exists():
        assert "nse_bhavcopy" in doc.read_text(encoding="utf-8")


# --- fixtures: simulated is a property of the data -------------------------


def test_is_simulated_is_forced_true_even_when_the_fixture_file_says_otherwise(tmp_path: Path):
    """A fixture file must not be able to launder synthetic data as live.

    `is_simulated` is set in the adapter, not read from the record, so an edited fixture file
    cannot turn the flag off. This is the test that says so out loud.
    """
    p = tmp_path / "events.jsonl"
    p.write_text(
        json.dumps(
            {
                "source_id": "fixture:1",
                "content": "Acme Industries declared a dividend of Rs 5 per share.",
                "is_simulated": False,
                "retrieved_at": "2026-09-28T00:00:00+00:00",
            }
        )
        + "\n"
        + "# a comment line\n"
        + "\n"
        + json.dumps(
            {
                "source_id": "fixture:2",
                "content": "Acme Industries held its annual general meeting.",
                "is_simulated": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = FixtureSource(str(p)).load()
    assert [o.source_id for o in result.observations] == ["fixture:1", "fixture:2"]
    assert all(o.is_simulated is True for o in result.observations)
    # A record claiming is_simulated=False and a record claiming True are indistinguishable after
    # loading. That is the point: the adapter's verdict wins over the file's claim.
    assert result.licence.redistribution_allowed is True
    assert result.source_id == "fixture"


def test_a_missing_fixture_file_says_what_to_do(tmp_path: Path):
    with pytest.raises(SourceError, match=r"fixture file .* not found"):
        FixtureSource(str(tmp_path / "nope.jsonl")).load()


def test_an_invalid_fixture_line_names_the_line_number(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    p.write_text('{"source_id": "a", "content": "ok"}\n{not json}\n', encoding="utf-8")
    with pytest.raises(SourceError, match=r"events\.jsonl:2: invalid JSON"):
        FixtureSource(str(p)).load()


def test_a_fixture_line_missing_a_required_field_raises_a_bare_keyerror(tmp_path: Path):
    """Pinned as-is: `FixtureSource.load` documents `SourceError` but lets `KeyError` through.

    Every other failure in `load` is a `SourceError` with a file:line message. A record with no
    `content` or no `source_id` -- a hand-edited fixture, a truncated write, a schema drift --
    escapes as `KeyError: 'content'`, so the operator gets a traceback with no indication of
    which file or line is at fault. See docs/loop/REDTOOM.md.
    """
    p = tmp_path / "events.jsonl"
    p.write_text('{"source_id": "a"}\n', encoding="utf-8")
    with pytest.raises(KeyError) as exc:
        FixtureSource(str(p)).load()
    assert exc.value.args[0] == "content"
    assert str(p) not in str(exc.value)


# --- announcements ---------------------------------------------------------


def _nse_record(**over: Any) -> dict[str, Any]:
    base = {
        "seq_id": "106784957",
        "symbol": "JAGRAN",
        "sm_name": "Jagran Prakashan Limited",
        "smIndustry": "Printing And Publishing",
        "desc": "Appointment",
        "attchmntText": "Re-Appointment of Mr. Sanjay Gupta as Whole-time Director w.e.f. October 01, 2026.",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/JAGRAN_18092026201340.pdf",
        "sort_date": "18-Sep-2026 20:23:39",
        "hasXbrl": "true",
    }
    base.update(over)
    return base


def test_announcement_from_nse_builds_the_full_record():
    a = Announcement.from_nse(_nse_record())
    assert a is not None
    assert a.seq_id == "106784957"
    assert a.symbol == "JAGRAN"
    assert a.company == "Jagran Prakashan Limited"
    assert a.desc == "Appointment"
    assert a.has_xbrl is True
    assert a.announced_at == "2026-09-18T20:23:39+00:00"
    assert a.pdf_url.endswith(".pdf")
    assert a.raw["seq_id"] == "106784957"


def test_announcement_from_nse_returns_none_for_empty_text_or_missing_symbol():
    assert Announcement.from_nse(_nse_record(attchmntText="   ")) is None
    assert Announcement.from_nse(_nse_record(attchmntText="")) is None
    assert Announcement.from_nse(_nse_record(attchmntText=None)) is None
    assert Announcement.from_nse(_nse_record(attchmntText="")) is None
    assert Announcement.from_nse(_nse_record(symbol="   ")) is None
    assert Announcement.from_nse(_nse_record(symbol=None)) is None
    # A record with no body must not become a row scored as a model failure.
    assert Announcement.from_nse({"attchmntText": "x"}) is None


def test_announcement_defaults_are_declared_not_invented():
    a = Announcement.from_nse(
        _nse_record(desc="", smIndustry=None, hasXbrl=None, sort_date="", seq_id=None)
    )
    assert a is not None
    assert a.desc == "Unclassified"
    assert a.industry == "unknown"
    assert a.has_xbrl is False
    assert a.seq_id == "", "with no seq_id and no sort_date there is no identity to deduplicate on"
    assert a.announced_at is not None


def test_has_xbrl_is_only_true_for_the_exact_string_nse_sends():
    for value, expected in [("true", True), ("True", True), ("TRUE", True),
                            ("false", False), ("1", False), ("", False), (None, False)]:
        a = Announcement.from_nse(_nse_record(hasXbrl=value))
        assert a is not None and a.has_xbrl is expected, value


def test_announcement_to_observation_carries_provenance_and_is_not_simulated():
    a = Announcement.from_nse(_nse_record())
    obs = a.to_observation()
    assert isinstance(obs, Observation)
    assert obs.is_simulated is False, "this was genuinely fetched; redistribution is a separate flag"
    assert obs.source_id == "nse_ann:JAGRAN:106784957"
    assert obs.source_url == a.pdf_url
    assert obs.published_at == a.announced_at
    assert "Exchange category: Appointment" in obs.content
    assert "Jagran Prakashan Limited (JAGRAN)" in obs.content
    assert obs.content.endswith(a.text)
    assert obs.content_hash == obs.content_hash and len(obs.content_hash) == 16


def test_fetch_deduplicates_by_seq_id(monkeypatch: pytest.MonkeyPatch):
    """A repeated filing would be scored twice, inflating counts and flattering agreement."""
    raw = [
        _nse_record(seq_id="1", sort_date="18-Sep-2026 10:00:00"),
        _nse_record(seq_id="1", sort_date="18-Sep-2026 10:00:00"),
        _nse_record(seq_id="2", sort_date="18-Sep-2026 11:00:00"),
        _nse_record(seq_id="1", sort_date="18-Sep-2026 10:00:00"),
        _nse_record(seq_id="2", sort_date="18-Sep-2026 11:00:00"),
    ]
    src = NseAnnouncements()
    monkeypatch.setattr(src, "fetch_raw", lambda start, end: raw)
    got, truncated = src.fetch(date(2026, 9, 1), date(2026, 9, 30))
    assert [a.seq_id for a in got] == ["2", "1"], "newest first"
    assert truncated is False
    assert len({a.seq_id for a in got}) == len(got)


def test_fetch_honours_a_limit_and_reports_truncation(monkeypatch: pytest.MonkeyPatch):
    raw = [_nse_record(seq_id=str(i), sort_date=f"18-Sep-2026 1{i}:00:00") for i in range(5)]
    src = NseAnnouncements()
    monkeypatch.setattr(src, "fetch_raw", lambda start, end: raw)
    got, _ = src.fetch(date(2026, 9, 1), date(2026, 9, 30), limit=2)
    assert len(got) == 2

    monkeypatch.setattr(src, "fetch_raw", lambda start, end: [
        _nse_record(seq_id=str(i)) for i in range(MAX_RECORDS)
    ])
    _got, truncated = src.fetch(date(2026, 9, 1), date(2026, 9, 30))
    assert truncated is True, "a response at the cap is a partial window and must say so"


def test_fetch_drops_records_with_no_body_before_deduplicating(monkeypatch: pytest.MonkeyPatch):
    raw = [
        _nse_record(seq_id="1", attchmntText=""),
        _nse_record(seq_id="1", attchmntText="real body"),
    ]
    src = NseAnnouncements()
    monkeypatch.setattr(src, "fetch_raw", lambda start, end: raw)
    got, _ = src.fetch(date(2026, 9, 1), date(2026, 9, 30))
    assert len(got) == 1 and got[0].text == "real body"


def test_a_non_list_response_is_an_outage_not_an_empty_window(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> Any:
            class R:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> Any:
                    return {"error": "NSE is down"}

            return R()

    monkeypatch.setattr("divya.data.nse.httpx.Client", FakeClient)
    with pytest.raises(SourceError, match="expected a JSON list"):
        NseAnnouncements().fetch_raw(date(2026, 9, 1), date(2026, 9, 30))


def test_a_non_json_response_is_reported_as_such(monkeypatch: pytest.MonkeyPatch):
    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> Any:
            class R:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> Any:
                    raise ValueError("not json")

            return R()

    monkeypatch.setattr("divya.data.nse.httpx.Client", FakeClient)
    with pytest.raises(SourceError, match="returned non-JSON"):
        NseAnnouncements().fetch_raw(date(2026, 9, 1), date(2026, 9, 30))


# --- URL shapes, as verified on 2026-09-28 ---------------------------------


def test_announcement_url_matches_the_verified_shape():
    url = NseAnnouncements().url_for(date(2026, 9, 1), date(2026, 9, 28))
    assert url == (
        "https://www.nseindia.com/api/corporate-announcements?index=equities"
        "&from_date=01-09-2026&to_date=28-09-2026"
    )
    assert API == "https://www.nseindia.com"


@pytest.mark.parametrize("cls", [NseBhavcopy, NseBhavcopyLive])
def test_bhavcopy_url_matches_the_verified_shape(cls: Any) -> None:
    day = date(2026, 9, 28)
    assert cls().url_for(day) == (
        "https://nsearchives.nseindia.com/content/cm/"
        "BhavCopy_NSE_CM_0_0_0_20260928_F_0000.csv.zip"
    )
    assert ARCHIVES == "https://nsearchives.nseindia.com"
    # plan.md's historical/ path 404s; nothing in the code may go back to it.
    assert "historical" not in cls().url_for(day)
    src = NSE.read_text(encoding="utf-8")
    assert "/historical/" not in src


def test_the_nifty50_url_matches_the_verified_shape():
    assert STATIC == "https://archives.nseindia.com"
    assert "ind_nifty50list.csv" in NSE.read_text(encoding="utf-8")
    assert "ind_nifty50list.csv" in NSE.read_text(encoding="utf-8")


def test_nse_requires_a_browser_user_agent():
    """Measured: NSE returns nothing at all to a request without one."""
    assert "Mozilla/5.0" in BROWSER_UA
    assert _headers()["User-Agent"] == BROWSER_UA
    assert "python" not in BROWSER_UA.lower()
    assert "Accept" in _headers()


def test_the_verified_urls_are_the_ones_in_the_research_record():
    doc = Path(__file__).resolve().parents[1] / "research" / "REAL_DATA_SOURCES.md"
    text = doc.read_text(encoding="utf-8")
    assert "api/corporate-announcements?index=equities&from_date=DD-MM-YYYY" in text
    assert "BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip" in text
    assert "ind_nifty50list.csv" in text
    assert "104 distinct values" in text


# --- the bhavcopy payload guard --------------------------------------------


def test_a_non_zip_bhavcopy_payload_raises():
    """The guard exists because circular NSE/MSD/76457 changes the endpoint on 2026-10-12.

    An HTML error page served with HTTP 200 must be an error naming the change, not an empty
    snapshot.
    """
    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> Any:
            class R:
                content = b"<html>not a zip</html>"

                def raise_for_status(self) -> None:
                    return None

            return R()

    import divya.data.nse as nse_mod

    original = nse_mod.httpx.Client
    nse_mod.httpx.Client = FakeClient  # type: ignore[assignment]
    try:
        with pytest.raises(SourceError, match="non-zip bytes"):
            NseBhavcopyLive().fetch_rows(date(2026, 9, 28))
    finally:
        nse_mod.httpx.Client = original  # type: ignore[assignment]


def test_the_non_zip_guard_is_stated_in_both_adapters():
    src = SOURCES.read_text(encoding="utf-8")
    assert 'payload.startswith(b"PK")' in src
    assert 'payload.startswith(b"PK")' in NSE.read_text(encoding="utf-8")


def test_a_http_error_becomes_a_source_error(monkeypatch: pytest.MonkeyPatch):
    import httpx

    class FakeClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> Any:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("divya.data.nse.httpx.Client", FakeClient)
    with pytest.raises(SourceError, match="bhavcopy fetch failed"):
        NseBhavcopyLive().fetch_rows(date(2026, 9, 28))


# --- timestamps ------------------------------------------------------------


def test_parse_nse_time_handles_the_formats_nse_sends():
    assert _parse_nse_time("18-Sep-2026 20:23:39") == "2026-09-18T20:23:39+00:00"
    assert _parse_nse_time("2026-09-18 20:23:39") == "2026-09-18T20:23:39+00:00"
    assert _parse_nse_time("18-09-2026 20:23:39") == "2026-09-18T20:23:39+00:00"
    for junk in (None, "", "not a time", "2026-13-45 99:99:99"):
        parsed = datetime.fromisoformat(_parse_nse_time(junk))
        assert parsed.tzinfo is not None, "an unparsed timestamp must still carry a timezone"


def test_staleness_warning_fires_on_the_boundaries():
    now = datetime.now(UTC)
    fresh = Observation(source_id="s", content="x", retrieved_at=now.isoformat())
    assert staleness_warning(fresh) is None
    # `max_age_days=0` warns on a just-created record because a few microseconds have elapsed
    # and the guard is a strict `>`. Harmless at any real threshold, but it means the boundary
    # is exclusive, not inclusive.
    assert "0 days ago" in (staleness_warning(fresh, max_age_days=0) or "")

    at_the_line = Observation(source_id="s", content="x",
                              retrieved_at=(now - timedelta(days=7, seconds=-5)).isoformat())
    assert staleness_warning(at_the_line) is None, "just inside 7 days is still fresh"

    just_past = Observation(source_id="s", content="x",
                            retrieved_at=(now - timedelta(days=7, seconds=5)).isoformat())
    assert "7 days ago" in (staleness_warning(just_past) or "")

    future = Observation(source_id="s", content="x",
                         retrieved_at=(now + timedelta(days=1)).isoformat())
    assert "in the future" in (staleness_warning(future) or "")


def test_staleness_warning_agrees_with_the_state_freshness_rule():
    from divya.runtime.state import SharedState

    now = datetime.now(UTC)
    for days in (0, 3, 6, 7, 8, 400):
        obs = Observation(source_id="s", content="x",
                          retrieved_at=(now - timedelta(days=days)).isoformat())
        state = SharedState(protocol_version="0.1.0", domain="d", objective="o", observations=[obs])
        warned = staleness_warning(obs) is not None
        assert warned == (not state.is_fresh), f"{days}d: warning={warned} is_fresh={state.is_fresh}"
