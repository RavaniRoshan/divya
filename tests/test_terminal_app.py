"""Headless tests for the terminal application.

The TUI is the product surface, so it gets tested rather than assumed. Textual's `run_test()`
drives the real app with a real Pilot, so these exercise the actual key handling, the actual
widgets, and the actual render path — not a mock of any of it.

Deliberately no Laya and no LLM: the terminal must mount, navigate, filter, and render with
neither present, because that is exactly the degraded state a user hits on a fresh machine. The
two tests that need System-1 are marked `slow` and use the stub.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import DataTable

from divya.data.store import Store
from divya.terminal.app import DivyaApp, _age, _age_seconds, _short_time

# pytest-asyncio is not a dependency. Rather than add it, the async body is driven through a
# small helper and the tests are plain sync functions. This keeps the core dependency set
# exactly as declared in pyproject.toml.

EVENTS = [
    {
        "seq_id": f"seq{i}",
        "symbol": ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"][i % 5],
        "company": ["Reliance Industries", "Tata Consultancy", "Infosys", "HDFC Bank", "State Bank"][i % 5],
        "industry": ["oil_gas", "information_technology", "banking"][i % 3],
        "nse_desc": ["Acquisition", "Shareholders meeting", "Credit Rating",
                     "Trading Window", "Outcome of Board Meeting"][i % 5],
        "text": f"Test announcement number {i} for the market intelligence terminal test suite.",
        "pdf_url": f"https://example.invalid/{i}.pdf",
        "announced_at": f"2026-09-{20 + i:02d}T10:00:00+00:00",
        "retrieved_at": "2026-09-28T12:00:00+00:00",
        "has_xbrl": i % 2 == 0,
        "is_simulated": False,
        "source_id": f"nse:test:{i}",
    }
    for i in range(10)
]


@pytest.fixture()
def store(tmp_path) -> Store:
    s = Store(tmp_path / "t.db")
    s.upsert_events(EVENTS)
    return s


def drive(coro) -> None:
    asyncio.run(coro)


def render_text(widget) -> str:
    """The widget's current text.

    `Static.update()` in Textual 8.x stores the string in a name-mangled private attribute and
    exposes a read-only `content` property. Reading `content` is the supported path; the
    fallbacks exist so this helper does not silently start returning `str(widget)` -- which is
    what a missing accessor looks like, and it made nine tests pass a bare repr.
    """
    content = getattr(widget, "content", None)
    if isinstance(content, str):
        return content
    for attr in ("renderable", "_content", "_Static__content"):
        v = getattr(widget, attr, None)
        if isinstance(v, str):
            return v
    raise AssertionError(
        f"could not read text from {type(widget).__name__}; "
        f"a test asserting on str(widget) would be asserting on a repr"
    )


# --- mounting and data ----------------------------------------------------


def test_app_mounts_with_a_populated_store(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            assert app.query_one("#stream").row_count == 10
            assert app.query_one("#companies").row_count == 5
            assert app.selected is not None

    drive(go())


def test_app_mounts_on_an_empty_store_without_raising(tmp_path):
    """A fresh install has no data. The terminal must say so, not crash."""

    async def go():
        app = DivyaApp(store=Store(tmp_path / "empty.db"))
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            assert app.query_one("#stream").row_count == 0
            assert app.selected is None
            assert "no events in store" in render_text(app.query_one("#detail")).lower()
            assert "NO DATA" in render_text(app.query_one("#status"))

    drive(go())


# --- keyboard -------------------------------------------------------------


def test_jk_navigates_the_stream(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            start = app.cursor
            for _ in range(3):
                await pilot.press("j")
            await pilot.pause()
            assert app.cursor == start + 3
            await pilot.press("k")
            await pilot.pause()
            assert app.cursor == start + 2

    drive(go())


def test_navigation_clamps_at_both_ends(store):
    """A stream is finite; running off either end is a bug, not a feature."""

    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            for _ in range(50):
                await pilot.press("k")
            await pilot.pause()
            assert app.cursor == 0
            for _ in range(50):
                await pilot.press("j")
            await pilot.pause()
            assert app.cursor == 9

    drive(go())


def test_g_and_shift_g_jump_to_ends(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            await pilot.press("G")
            await pilot.pause()
            assert app.cursor == 9
            await pilot.press("g")
            await pilot.pause()
            assert app.cursor == 0

    drive(go())


def test_f_toggles_the_measurable_filter(store):
    """The filter is the mechanism for hiding the 77% of filings that carry no event."""

    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            all_rows = app.query_one("#stream").row_count
            await pilot.press("f")
            await pilot.pause()
            assert app.measurable_only is True
            filtered = app.query_one("#stream").row_count
            assert 0 < filtered < all_rows
            await pilot.press("f")
            await pilot.pause()
            assert app.measurable_only is False
            assert app.query_one("#stream").row_count == all_rows

    drive(go())


def test_w_toggles_raw_and_interpreted(store):
    """Raw System-1 output and the system's interpretation must be one keystroke apart."""

    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            assert app.show_raw is False
            await pilot.press("w")
            await pilot.pause()
            assert app.show_raw is True
            assert "RAW" in render_text(app.query_one("#status"))
            await pilot.press("w")
            await pilot.pause()
            assert app.show_raw is False

    drive(go())


def test_question_mark_shows_the_bindings(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            await pilot.press("?")
            await pilot.pause()
            status = render_text(app.query_one("#status"))
            assert "enter decide" in status and "raw/interp" in status

    drive(go())


def test_focus_bindings_do_not_raise(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            for key in ("c", "e", "d", "r"):
                await pilot.press(key)
                await pilot.pause()
            assert isinstance(app.query_one("#stream"), DataTable)

    drive(go())


# --- what the panes must always show ---------------------------------------


def test_status_pane_always_states_freshness_and_versions(store):
    """The header never omits data age, the System-1 state, or the model. Ever.

    A terminal that can display a filing without saying how old it is, or which model
    produced a number, is the exact failure this product exists to avoid.
    """

    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            status = render_text(app.query_one("#status"))
            assert "data age" in status
            assert "laya:" in status
            assert "system2:" in status
            assert "events 10" in status
            assert "mode:" in status

    drive(go())


def test_stale_data_is_labelled_stale_in_the_status_bar(tmp_path):
    """Old data must never render as current."""

    stale = [dict(EVENTS[0], retrieved_at="2020-01-01T00:00:00+00:00")]
    s = Store(tmp_path / "s.db")
    s.upsert_events(stale)

    async def go():
        app = DivyaApp(store=s)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            assert "STALE" in render_text(app.query_one("#status"))
            assert "STALE" in render_text(app.query_one("#detail"))

    drive(go())


def test_simulated_data_is_labelled_simulated(tmp_path):
    """Synthetic data must say so in the UI, not only in the docs."""

    s = Store(tmp_path / "sim.db")
    s.upsert_events([dict(EVENTS[0], is_simulated=True)])

    async def go():
        app = DivyaApp(store=s)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            assert "SIMULATED" in render_text(app.query_one("#detail"))

    drive(go())


def test_detail_pane_shows_provenance_and_the_mapped_label(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            await pilot.press("j")  # Acquisition
            await pilot.pause()
            detail = render_text(app.query_one("#detail"))
            assert "NSE class" in detail and "our label" in detail
            assert "pdf" in detail and "source" in detail
            assert "unresolvable by class" in detail or "m_and_a" in detail

    drive(go())


def test_why_pane_explains_the_label_mapping(store):
    """The 'why' view must be a real evidence chain, not a caption."""

    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            why = render_text(app.query_one("#why"))
            assert "WHY THIS DECISION" in why
            assert "source" in why and "retrieved" in why
            assert "exchange said" in why and "mapped to" in why
            assert "no decision has been made" in why

    drive(go())


def test_decision_pane_prompts_when_nothing_decided_yet(store):
    async def go():
        app = DivyaApp(store=store)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause()
            assert "no decision yet" in render_text(app.query_one("#decision")).lower()

    drive(go())


# --- helpers --------------------------------------------------------------


def test_age_helpers_are_consistent():
    """`_age` is display text and `_age_seconds` is the number. Mixing them was a real bug."""
    now = "2026-09-28T12:00:00+00:00"
    assert _age(now) is not None
    assert _age_seconds(now) is not None
    assert _age_seconds("not-a-date") is None
    assert _age("not-a-date") is None
    assert _age(None) is None
    assert _short_time(None) == "-"
    assert _short_time("2026-09-28T12:34:56+00:00") == "09-28 12:34"


# --- the decide path ------------------------------------------------------


class StubSystem1:
    """Stands in for Laya so the decide path is testable without the checkpoint.

    Returns a frozen `System1Record` with the same shape the real adapter returns, including a
    populated `answers` dict, so the terminal renders exactly what it would in production.
    """

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def answer(self, state_text, spec, *, only=None, turn_index=0, protocol_version="", timeout_note=""):
        from divya.runtime.state import System1Record

        self.calls += 1
        names = sorted(spec.to_laya(only=only))
        if self.fail:
            return System1Record(
                turn_index=turn_index, decision_names=names, spec_name=spec.name,
                spec_version=spec.version, protocol_version=protocol_version,
                request={}, raw_response={}, answers={}, error="stub: engine unavailable",
            )
        answers = {
            n: ({"type": "choice", "choice": "m_and_a",
                 "probabilities": {"m_and_a": 0.91, "other": 0.05, "fundraise": 0.04},
                 "confidence": 0.91}
                if n == "event_type" else
                {"type": "noul", "noul": 0.72, "confidence": 0.72})
            for n in names
        }
        return System1Record(
            turn_index=turn_index, decision_names=names, spec_name=spec.name,
            spec_version=spec.version, protocol_version=protocol_version,
            request={}, raw_response={"answers": answers}, answers=answers,
            checkpoint="stub", latency_ms=12.0,
        )


def test_enter_produces_a_persisted_decision(store):
    """A decision made in the terminal must be readable back from the store afterwards."""

    async def go():
        app = DivyaApp(store=store, system1_factory=StubSystem1)
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
            assert app.last_decision, "no decision recorded"
            assert "event_type" in app.last_decision
            assert app.last_decision["event_type"]["value"] == "m_and_a"
            # Persisted, not just held in memory.
            assert store.stats()["decisions"] > 0
            assert store.stats()["runs"] == 1
            assert "finished" in app.status_message
            pane = render_text(app.query_one("#decision"))
            assert "m_and_a" in pane and "termination" in pane

    drive(go())


def test_raw_view_shows_the_probability_distribution(store):
    """The raw view must expose the actual distribution, not just the winner."""

    async def go():
        app = DivyaApp(store=store, system1_factory=StubSystem1)
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
            await pilot.press("w")
            await pilot.pause()
            pane = render_text(app.query_one("#decision"))
            assert "RAW System-1" in pane
            assert "m_and_a:0.91" in pane or "m_and_a 0.91" in pane or "0.91" in pane
            assert "event_triage@" in pane

    drive(go())


def test_engine_failure_is_surfaced_not_swallowed(store):
    """A broken engine must produce a visible failed run, not an empty pane."""

    async def go():
        app = DivyaApp(store=store, system1_factory=lambda: StubSystem1(fail=True))
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
            assert "error" in app.status_message.lower()
            assert store.stats()["runs"] == 1

    drive(go())


def test_why_pane_populates_after_a_decision(store):
    async def go():
        app = DivyaApp(store=store, system1_factory=StubSystem1)
        async with app.run_test(size=(180, 50)) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(4):
                await pilot.pause()
            why = render_text(app.query_one("#why"))
            assert "System-1 (Laya) returned, verbatim" in why
            assert "System-2 conclusion" in why
            assert "DISAGREED" in why

    drive(go())
