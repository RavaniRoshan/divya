"""The Divya terminal: a keyboard-first intelligence TUI.

This is the product surface the plan asked for — event stream, company state, event history,
decision state, confidence, evidence, a "why" view, freshness, and model/version information —
in one screen, driven from the keyboard.

**Why Textual and not the existing `rich` render.** `terminal/view.py` renders one decision well
and is the audit path: it produces a file you can diff, paste into an issue, and check. This
module is the working path. Both call the same `divya` modules, so there is no second
implementation of the product logic to drift.

Design rules, each aimed at a specific failure:

* **Freshness is in the header, always, and it goes red.** A market terminal that quietly shows
  a week-old filing as current is worse than one that shows nothing. There is no state in which
  the header does not say when the data was last retrieved.
* **Raw and interpreted are one keystroke apart.** Pressing `w` swaps the decision pane between
  what the engine returned and what the system concluded from it. The two must never be
  confusable, because the whole claim of this project is that they can be told apart.
* **The keyboard is the interface.** No action requires a mouse. `?` lists every binding.
* **Degradation is stated, not hidden.** With no Laya checkpoint, the decision pane says so and
  the reason appears in the status bar rather than the app refusing to start.
* **Abstention is presented as an answer.** A run that abstained renders as an abstention with
  its uncertainty, not as an error state.

Headless-testable: the whole app is exercisable via `App.run_test()` in the test suite, so the
UI is verified rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from divya.data.store import EventRow, Store
from divya.runtime.state import MAX_OBSERVATION_AGE_S

# Terminal-local thresholds, named so the "why" view can explain a decision.
STALE_AFTER_S = MAX_OBSERVATION_AGE_S


class DivyaApp(App):
    """The terminal."""

    CSS = """
    Screen { background: $surface; }
    #body { height: 1fr; }
    #stream-pane { width: 34%; border: round $primary; }
    #centre { width: 33%; }
    #decision-pane { width: 33%; border: round $accent; }
    #status { height: 3; border: round $warning; }
    .pane-title { text-style: bold; color: $text; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "Quit"),
        Binding("j,down", "cursor_down", "Down"),
        Binding("k,up", "cursor_up", "Up"),
        Binding("g,home", "cursor_top", "Top"),
        Binding("G,end", "cursor_bottom", "Bottom"),
        Binding("enter", "decide", "Decide selected"),
        Binding("w", "toggle_raw", "Raw / interpreted"),
        Binding("c", "focus_companies", "Companies"),
        Binding("e", "focus_stream", "Event stream"),
        Binding("d", "focus_decision", "Decision"),
        Binding("f", "toggle_filter", "Filter: measurable only"),
        Binding("r", "reload", "Reload from store"),
        Binding("?", "help", "Help"),
    ]

    show_raw = reactive(False)
    measurable_only = reactive(False)
    status_message = reactive("")

    def __init__(
        self,
        store: Store | None = None,
        provider_kind: str = "system1",
        system1_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__()
        self.store = store or Store()
        self.provider_kind = provider_kind
        #: Injectable so the decide path is testable without a 2.8 GB checkpoint. Left as None
        #: in production, where the real engine is resolved lazily on first use.
        self._system1_factory = system1_factory
        self.rows: list[EventRow] = []
        self.cursor = 0
        self.last_decision: dict[str, Any] | None = None
        self.last_run: Any = None

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield Vertical(
                Static("EVENT STREAM", classes="pane-title", id="stream-title"),
                DataTable(id="stream", cursor_type="row"),
                id="stream-pane",
            )
            with TabbedContent(id="centre"):
                with TabPane("Detail", id="tab-detail"):
                    yield Static("", id="detail")
                with TabPane("Company", id="tab-company"):
                    yield DataTable(id="companies")
                with TabPane("Why", id="tab-why"):
                    yield Static("", id="why")
            yield Vertical(
                Static("DECISION STATE", classes="pane-title", id="decision-title"),
                Static("", id="decision"),
                id="decision-pane",
            )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#stream", DataTable)
        t.add_columns("when", "symbol", "NSE class", "our label")
        self.query_one("#companies", DataTable).add_columns("symbol", "company", "n", "last")
        self.reload_data()
        self.refresh_all()

    # -- data --------------------------------------------------------------

    def reload_data(self) -> None:
        self.rows = self.store.stream(limit=400, measurable_only=self.measurable_only)
        self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
        t = self.query_one("#stream", DataTable)
        t.clear()
        for r in self.rows:
            t.add_row(
                _short_time(r.announced_at),
                r.symbol,
                r.nse_desc[:22],
                r.label_event_type,
                key=r.seq_id,
            )
        c = self.query_one("#companies", DataTable)
        c.clear()
        for comp in self.store.companies(limit=300):
            c.add_row(comp["symbol"], comp["company"][:28], str(comp["n_events"]),
                      _short_time(comp["last_announced"]))

    @property
    def selected(self) -> EventRow | None:
        if not self.rows:
            return None
        return self.rows[max(0, min(self.cursor, len(self.rows) - 1))]

    # -- actions -----------------------------------------------------------

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_cursor_top(self) -> None:
        self.cursor = 0
        self._sync_cursor()

    def action_cursor_bottom(self) -> None:
        self.cursor = max(0, len(self.rows) - 1)
        self._sync_cursor()

    def _move(self, delta: int) -> None:
        if not self.rows:
            return
        self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))
        self._sync_cursor()

    def _sync_cursor(self) -> None:
        t = self.query_one("#stream", DataTable)
        if 0 <= self.cursor < t.row_count:
            t.move_cursor(row=self.cursor)
            self.refresh_all()

    def action_focus_stream(self) -> None:
        self.query_one("#stream", DataTable).focus()

    def action_focus_companies(self) -> None:
        self.query_one("#companies", DataTable).focus()

    def action_focus_decision(self) -> None:
        self.query_one("#decision", Static).focus()

    def action_toggle_filter(self) -> None:
        self.measurable_only = not self.measurable_only
        self.status_message = (
            f"filter: {'measurable only' if self.measurable_only else 'all classes'}"
        )
        self.reload_data()
        self.refresh_all()

    def action_toggle_raw(self) -> None:
        self.show_raw = not self.show_raw
        self.status_message = "showing RAW System-1 output" if self.show_raw else "showing interpretation"
        self.refresh_all()

    def action_reload(self) -> None:
        self.reload_data()
        self.status_message = f"reloaded {len(self.rows)} events"
        self.refresh_all()

    def watch_status_message(self, _message: str) -> None:
        """Re-render when the status line changes.

        Without this, any action that only sets `status_message` updates the attribute and
        nothing on screen -- `?` looked like it did nothing at all. Found by a headless test
        that read the widget rather than the attribute.
        """
        # `self.is_running` rather than `is_mounted`: the watcher can fire while the app is
        # shutting down, and a render against a torn-down tree is worse than a skipped one.
        if self.is_running:
            self._render_status()

    def action_help(self) -> None:
        self.status_message = (
            "j/k move  enter decide  w raw/interp  c companies  e stream  d decision  "
            "f filter  r reload  q quit"
        )

    async def action_decide(self) -> None:
        """Run the selected event through the runtime and store the result.

        The default mode is System-1 alone because that is what the measurement supports
        (docs/loop/DECISIONS.md D-012). The loop is available via `--mode loop` on the CLI and
        is not what a single keystroke should trigger.
        """
        row = self.selected
        if row is None:
            self.status_message = "nothing selected"
            return
        self.status_message = f"deciding {row.symbol} ..."

        from divya.protocol.loader import load_protocol
        from divya.runtime.loop import DivyaRuntime, LoopConfig, write_trace
        from divya.system1.laya_adapter import LayaSystem1, NullSystem1
        from divya.system2.provider import build_provider

        if self._system1_factory is not None:
            s1 = self._system1_factory()
        else:
            s1 = LayaSystem1() if LayaSystem1().is_available() else NullSystem1()
        loop_mode = self.provider_kind == "loop"
        runtime = DivyaRuntime(
            protocol=load_protocol(),
            system2=build_provider() if loop_mode else None,
            system1=s1,
            config=LoopConfig(
                max_turns=4, min_confidence=0.55, allow_escalation=loop_mode,
                system1_only=not loop_mode,
            ),
        )
        # Awaited, not `asyncio.run`: the TUI already owns an event loop, and nesting a new
        # one raises. Textual awaits async action handlers, so the UI stays responsive.
        result = await runtime.run(
            domain="corporate_actions",
            objective="Classify this Indian corporate disclosure.",
            observations=[row.to_observation()],
        )
        trace = None
        try:
            trace = write_trace(result, f"data/traces/{result.state.task_id}.json")
        except Exception as exc:
            self.status_message = f"decided, but trace write failed: {exc}"

        self.last_run = result
        self.store.record_run(
            result, mode="loop" if loop_mode else "system1",
            trace_path=str(trace) if trace else None,
            symbol=row.symbol, seq_id=row.seq_id,
        )
        self.last_decision = self.store.decision_for_event(row.seq_id)
        term = result.state.termination.value if result.state.termination else "unknown"
        m = result.metrics()
        elapsed = m["system1_latency_ms"] + m["system2_latency_ms"]
        self.status_message = (
            f"{row.symbol}: {term} in {elapsed:.0f}ms "
            f"(s1 {m['system1_calls']} call / {m['system1_latency_ms']:.0f}ms)"
        )
        self.refresh_all()

    # -- rendering ---------------------------------------------------------

    def refresh_all(self) -> None:
        self._render_status()
        self._render_detail()
        self._render_decision()
        self._render_why()

    def _render_status(self) -> None:
        s = self.store.stats()
        last = self.store.last_retrieved()
        age_s = _age_seconds(last)
        freshness = (
            f"data age {_age(last)}"
            if age_s is not None and age_s < STALE_AFTER_S
            else (f"STALE — last fetch {last or 'never'}" if last else "NO DATA")
        )
        s1 = "laya:loaded" if _laya_available() else "laya:MISSING"
        model = _system2_name()
        self.query_one("#status", Static).update(
            f" events {s['events']}  symbols {s['symbols']}  measurable {s['measurable']}"
            f"  decisions {s['decisions']}  runs {s['runs']}"
            f"  |  {freshness}"
            f"  |  {s1}  system2:{model}  mode:{'loop' if self.provider_kind == 'loop' else 'system1'}"
            f"  filter:{'measurable' if self.measurable_only else 'all'}"
            f"  view:{'RAW' if self.show_raw else 'interpretation'}\n"
            f" {self.status_message}"
        )

    def _render_detail(self) -> None:
        row = self.selected
        if row is None:
            self.query_one("#detail", Static).update("no events in store — run `divya fetch`")
            return
        age = row.age_seconds()
        fresh = (
            "SIMULATED — not market data" if row.is_simulated
            else ("STALE" if age > STALE_AFTER_S else f"{int(age)}s since fetch")
        )
        body = "\n".join([
            f"  {row.company}  ({row.symbol})",
            f"  industry     {row.industry}",
            f"  announced    {row.announced_at}",
            f"  NSE class    {row.nse_desc}",
            f"  our label    {row.label_event_type}"
            + ("" if row.is_measurable else "   [unresolvable by class]"),
            f"  freshness    {fresh}",
            f"  XBRL         {row.has_xbrl}",
            f"  source       {row.source_id}",
            f"  pdf          {row.pdf_url or '-'}",
            "",
            "  " + " ".join(row.text.split())[:520],
        ])
        self.query_one("#detail", Static).update(body)

    def _render_decision(self) -> None:
        d = self.last_decision
        if not d:
            self.query_one("#decision", Static).update(
                "no decision yet\n\npress [enter] on a selected event"
            )
            return
        lines: list[str] = []
        for name, v in d.items():
            if self.show_raw:
                raw = v.get("raw", {})
                if raw.get("type") == "choice":
                    probs = sorted((raw.get("probabilities") or {}).items(), key=lambda kv: -kv[1])[:3]
                    lines.append(f"  {name}")
                    lines.append(f"    choice      {raw.get('choice')}")
                    lines.append(f"    confidence  {v['confidence']:.3f}")
                    lines.append("    top         " + "  ".join(f"{k[:12]} {p:.2f}" for k, p in probs))
                elif raw.get("type") == "noul":
                    lines.append(f"  {name}")
                    lines.append(f"    P(true)     {raw.get('noul')}")
                    lines.append(f"    confidence  {v['confidence']:.3f}")
                else:
                    lines.append(f"  {name}  score={raw.get('score')}  conf={v['confidence']:.3f}")
                lines.append(f"    [RAW System-1 · {v.get('spec')}]")
            else:
                lines.append(f"  {name:<24} {v['value']}   conf {v['confidence']:.3f}")
        if self.last_run is not None:
            st = self.last_run.state
            term = st.termination.value if st.termination else "?"
            lines += [
                "",
                f"  termination  {term}",
                f"  conclusion   {st.conclusion[:60]}",
                f"  uncertainty  {st.uncertainty[:60]}",
                f"  cost         s1={self.last_run.metrics()['system1_latency_ms']:.0f}ms"
                f" s2={self.last_run.metrics()['system2_latency_ms']:.0f}ms",
            ]
        head = "DECISION STATE — RAW System-1 output" if self.show_raw else "DECISION STATE — interpretation"
        self.query_one("#decision", Static).update(head + "\n\n" + "\n".join(lines))

    def _render_why(self) -> None:
        """The 'why' view: the evidence chain behind whatever is on screen."""
        row = self.selected
        if row is None:
            self.query_one("#why", Static).update("no event selected")
            return
        d = self.store.decision_for_event(row.seq_id)
        lines = [
            "WHY THIS DECISION",
            "",
            f"1. source        {row.source_id}",
            f"   url           {row.pdf_url or '-'}",
            f"   retrieved     {row.retrieved_at} ({_age(row.retrieved_at)})",
            f"   simulated     {row.is_simulated}",
            "",
            f"2. exchange said {row.nse_desc!r}",
            f"   mapped to     {row.label_event_type}"
            + ("" if row.is_measurable else "   (class does not determine an event)"),
            "",
        ]
        if d:
            lines.append("3. System-1 (Laya) returned, verbatim:")
            for name, v in d.items():
                raw = v.get("raw", {})
                if raw.get("type") == "choice":
                    probs = sorted((raw.get("probabilities") or {}).items(), key=lambda kv: -kv[1])
                    lines.append(f"     {name} = {raw.get('choice')}  (conf {v['confidence']:.3f})")
                    lines.append("       " + "  ".join(f"{k}:{p:.3f}" for k, p in probs[:4]))
                elif raw.get("type") == "noul":
                    lines.append(f"     {name}: P(true) = {raw.get('noul'):.4f}")
                else:
                    lines.append(f"     {name}: level {raw.get('score')}")
                lines.append(f"       protocol {v.get('spec')}  run {v.get('run_id')}")
            if self.last_run is not None:
                st = self.last_run.state
                lines += [
                    "",
                    "4. System-2 conclusion:",
                    f"     {st.conclusion or '(none)'}",
                    f"     uncertainty: {st.uncertainty}",
                    "",
                    "5. where the reasoning model DISAGREED with System-1:",
                ]
                if st.disagreements:
                    lines += [f"     {d_.decision}: {d_.note or d_.system2_view}" for d_ in st.disagreements]
                else:
                    lines.append("     nothing recorded — raw System-1 output is authoritative")
        else:
            lines += [
                "3. no decision has been made on this event yet.",
                "   press [enter] on it to run one.",
            ]
        self.query_one("#why", Static).update("\n".join(lines))

    # -- events ------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "stream":
            try:
                idx = event.cursor_row
            except Exception:
                return
            if 0 <= idx < len(self.rows):
                self.cursor = idx
                self.refresh_all()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "stream":
            await self.action_decide()


def _short_time(ts: str | None) -> str:
    if not ts:
        return "-"
    return ts[5:16].replace("T", " ")


def _age_seconds(ts: str | None) -> float | None:
    """Numeric age, for comparisons. `_age` is the display form and is never compared."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return (datetime.now(UTC) - t).total_seconds()


def _age(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    s = int((datetime.now(UTC) - t).total_seconds())
    if s < 3600:
        return f"{s}s ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _laya_available() -> bool:
    try:
        from divya.system1.laya_adapter import LayaSystem1

        return LayaSystem1().is_available()
    except Exception:
        return False


def _system2_name() -> str:
    if not _laya_available():
        return "n/a"
    try:
        from divya.system2.provider import build_provider

        info = build_provider().info
        return f"{info.name}:{info.model}" if info.is_model else f"{info.name}(not a model)"
    except Exception as exc:
        return f"unavailable({type(exc).__name__})"


def main(store_path: str | None = None, provider_kind: str = "system1") -> int:
    """Entry point for `divya terminal`."""
    store = Store(store_path) if store_path else Store()
    DivyaApp(store=store, provider_kind=provider_kind).run()
    return 0
