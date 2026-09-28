"""Tests for the terminal view.

The view is the audit surface: it is what a human reads to decide whether to trust a decision.
Four of its stated design rules are therefore pinned as tests, because each of them exists to
stop a specific failure that a rendering change could silently reintroduce:

* it must render at all, on a run built from a stub, on a narrow console, with no answers;
* a simulated observation must say SIMULATED, and a stale one must say STALE;
* an abstention must read as an abstention, not as an error;
* a degraded run must say it is degraded.

These are the rules from the module docstring, checked against actual output rather than
against the code that produced it. No torch, no checkpoint, no network.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console

from divya.data.nse_taxonomy import UNRESOLVED
from divya.runtime.loop import DivyaRuntime, LoopConfig, LoopResult
from divya.runtime.state import Observation, SharedState, StateBuilder, TerminationStatus
from divya.system2.provider import HeuristicProvider
from divya.terminal import view
from test_redteam import StubSystem1

FILING = (
    "Sun Pharma Limited has informed the Exchange that the Board of Directors has declared an "
    "interim dividend of Rs 12.50 per equity share for the quarter ended 30 June 2026."
)


def _console(width: int = 120) -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=width, no_color=True, legacy_windows=False), buf


def _obs(**kw) -> Observation:
    base = {"kind": "document", "source_id": "test:1", "content": FILING}
    base.update(kw)
    return Observation(**base)


def _result(
    *,
    observations: list[Observation] | None = None,
    system1: bool = True,
    mode: str = "system1",
    config: LoopConfig | None = None,
) -> LoopResult:
    """Build a real `LoopResult` by driving the real loop with the shared System-1 double."""
    import asyncio

    runtime = DivyaRuntime(
        system2=HeuristicProvider(),
        system1=StubSystem1() if system1 else None,
        config=config or LoopConfig(system1_only=(mode == "system1"), max_turns=3),
    )
    return asyncio.run(
        runtime.run(
            domain="test",
            objective="Classify this Indian corporate disclosure.",
            observations=observations if observations is not None else [_obs()],
        )
    )


def _render(result: LoopResult, width: int = 120) -> str:
    console, buf = _console(width)
    view.render(result, console)
    return buf.getvalue()


# --- it renders ------------------------------------------------------------


def test_render_does_not_raise_on_a_stub_backed_run():
    out = _render(_result())
    assert "DIVYA" in out
    assert "system-1 decisions" in out
    assert "trace (fully reconstructable)" in out
    assert "cost" in out


def test_render_shows_the_typed_answer_and_its_confidence():
    out = _render(_result())
    assert "event_type" in out
    assert "capital_action" in out
    # Confidence and its source are on screen together, per the module's first design rule.
    assert "conf" in out
    assert "0." in out


def test_render_survives_a_run_with_no_system1_answers_at_all():
    import asyncio

    from divya.system1.laya_adapter import NullSystem1

    runtime = DivyaRuntime(system2=HeuristicProvider(), system1=NullSystem1(),
                           config=LoopConfig(system1_only=True))
    result = asyncio.run(runtime.run(domain="t", objective="o", observations=[_obs()]))
    out = _render(result)
    assert "no System-1 answers were produced" in out
    assert result.degraded, "an unavailable engine must be reported as a degradation"


def test_render_survives_a_narrow_console_and_a_long_document():
    long_text = FILING * 400
    out = _render(_result(observations=[_obs(content=long_text)]), width=40)
    assert "DIVYA" in out
    assert "more" in out or "…" in out or "..." in out


def test_render_survives_many_observations():
    obs = [_obs(source_id=f"test:{i}", content=f"{FILING} (variant {i})") for i in range(9)]
    out = _render(_result(observations=obs))
    assert "3 more" in out, "the sources table truncates rather than growing without bound"


def test_render_reports_degradation_in_the_header():
    import asyncio

    from divya.system1.laya_adapter import NullSystem1

    runtime = DivyaRuntime(system2=HeuristicProvider(), system1=NullSystem1(),
                           config=LoopConfig(system1_only=True))
    result = asyncio.run(runtime.run(domain="t", objective="o", observations=[_obs()]))
    out = _render(result)
    assert "DEGRADED" in out
    assert any("system1" in d for d in result.degraded), result.degraded


# --- provenance labels -----------------------------------------------------


def test_a_simulated_observation_is_labelled_simulated():
    out = _render(_result(observations=[_obs(is_simulated=True)]))
    assert "SIMULATED" in out
    assert "not market data" in out
    assert "◇" in out, "a simulated source uses the hollow marker"


def test_a_live_fresh_observation_is_labelled_fresh():
    out = _render(_result())
    assert "fresh (" in out
    assert "▸" in out


def test_a_stale_observation_is_labelled_stale_with_its_age():
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    out = _render(_result(observations=[_obs(retrieved_at=old, is_simulated=False)]))
    assert "STALE" in out
    assert "400d ago" in out


def test_a_future_timestamp_is_never_called_fresh():
    """A clock skewed into the future must not read as current.

    This test originally asserted the opposite — its name said "even though the state calls it
    fresh" and its body asserted `is_fresh is True`, "the defect this test documents". The
    red-team suite found that a future timestamp passed the freshness check, and the check has
    since been fixed. It is now a regression test for that fix. See docs/loop/REDTOOM.md.
    """
    ahead = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    obs = _obs(retrieved_at=ahead, is_simulated=False)
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o", observations=[obs])
    assert state.is_fresh is False, "a future timestamp must never be fresh"
    assert obs.age_seconds() is not None and obs.age_seconds() < 0

    out = _render(_result(observations=[obs]))
    assert "timestamp in the future" in out


def test_an_unreadable_timestamp_is_never_called_fresh():
    """Unknown age must not be presented as new. A parse failure returned 0.0, i.e. 'now'."""
    obs = _obs(retrieved_at="not-a-timestamp", is_simulated=False)
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o", observations=[obs])
    assert obs.age_seconds() is None
    assert state.is_fresh is False


def test_a_simulated_observation_is_not_also_labelled_by_age():
    """A simulated price is labelled by what it is, not by how old it is."""
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    out = _render(_result(observations=[_obs(retrieved_at=old, is_simulated=True)]))
    assert "SIMULATED" in out
    assert "STALE" not in out


def test_a_recent_observation_is_labelled_in_hours():
    hours = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    out = _render(_result(observations=[_obs(retrieved_at=hours, is_simulated=False)]))
    assert "5h old" in out


# --- abstention is a result, not an error ----------------------------------


def _abstained_result() -> LoopResult:
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o",
                        observations=[_obs()])
    b = StateBuilder(state)
    b.add_observation(_obs())
    b.set_outcome("No System-1 decision cleared the confidence threshold.", 0.0,
                  uncertainty="max System-1 confidence was below the configured minimum")
    b.terminate(TerminationStatus.ABSTAINED, "System-2 abstained")
    return LoopResult(state=state, builder=b, degraded=[])


def test_an_abstained_run_renders_as_abstained_not_as_an_error():
    out = _render(_abstained_result())
    assert "abstained" in out
    assert "The system declined to conclude." in out
    assert "failed" not in out
    assert "The run failed safely." not in out


def test_an_errored_run_renders_as_failed():
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o")
    b = StateBuilder(state)
    b.set_outcome("System-1 failed: laya is not installed", 0.0, uncertainty="1 System-1 call errored")
    b.terminate(TerminationStatus.ERROR, "System-1 failed twice")
    out = _render(LoopResult(state=state, builder=b))
    assert "failed" in out
    assert "The run failed safely." in out
    assert "abstained" not in out


def test_an_unterminated_state_does_not_crash_the_header():
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o")
    out = _render(LoopResult(state=state, builder=StateBuilder(state)))
    assert "running" in out


def test_a_low_confidence_conclusion_shows_the_uncertainty():
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o")
    b = StateBuilder(state)
    b.set_outcome("event type: other", 0.21,
                  uncertainty="max System-1 confidence 0.21 is below the 0.55 threshold")
    b.terminate(TerminationStatus.FINISHED, "System-2 concluded")
    out = _render(LoopResult(state=state, builder=b))
    assert "0.210" in out
    assert "below the 0.55 threshold" in out


def test_a_run_with_no_conclusion_says_so():
    state = SharedState(protocol_version="0.1.0", domain="t", objective="o")
    b = StateBuilder(state)
    b.terminate(TerminationStatus.MAX_TURNS, "Reached max_turns=4")
    out = _render(LoopResult(state=state, builder=b))
    assert "(none recorded)" in out
    assert "max_turns" in out


# --- the event stream ------------------------------------------------------


def test_render_event_stream_marks_unresolved_classes_distinctly():
    items = [
        {"announced_at": "2026-09-18T20:23:39+00:00", "symbol": "JAGRAN", "nse_desc": "Appointment",
         "label_event_type": "leadership_change", "text": FILING},
        {"announced_at": "2026-09-18T09:00:00+00:00", "symbol": "SKIL", "nse_desc": "Trading Window",
         "label_event_type": UNRESOLVED, "text": "the trading window for the quarter is closed"},
    ]
    console, buf = _console()
    view.render_event_stream(items, console)
    out = buf.getvalue()
    assert "leadership_change" in out
    assert UNRESOLVED in out
    assert "yellow = no scorable event type" in out
    assert "2 shown" in out


def test_render_event_stream_handles_an_empty_and_a_missing_label():
    console, buf = _console()
    view.render_event_stream([], console)
    assert "0 shown" in buf.getvalue()

    console, buf = _console()
    view.render_event_stream([{"symbol": "X", "nse_desc": "Unknown"}], console)
    assert "-" in buf.getvalue()


# --- helpers ---------------------------------------------------------------


def test_confidence_bar_is_fixed_width_and_colour_graded():
    for p in (0.0, 0.24, 0.5, 0.75, 1.0, -1.0, 5.0):
        bar = view._confidence_bar(p)
        assert len(bar.plain) == 20, p
    assert view._confidence_bar(0.9).style == "green"
    assert view._confidence_bar(0.6).style == "yellow"
    assert view._confidence_bar(0.1).style == "red"


def test_a_lower_confidence_does_not_look_certain_next_to_a_lower_one():
    """The bar is absolute, not relative: 0.4 next to 0.1 must still look like 0.4."""
    assert view._confidence_bar(0.4).plain == "\u2588" * 8 + "\u2591" * 12
    assert view._confidence_bar(0.1).plain == "\u2588" * 2 + "\u2591" * 18


@pytest.mark.parametrize("text", ["", " ", "x" * 5000, "\u20b9\u091f\u091f", "\n\n\n"])
def test_render_survives_odd_observation_content(text: str) -> None:
    out = _render(_result(observations=[_obs(content=text)]))
    assert "DIVYA" in out
