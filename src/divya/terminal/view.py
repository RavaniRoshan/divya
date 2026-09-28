"""The Divya terminal view.

Rendered with `rich` rather than a full TUI framework, for a reason that is about honesty
rather than preference: this must be inspectable in a non-interactive environment. The whole
value of the product is that a decision can be audited, and an audit view that only exists
inside a running full-screen application cannot be diffed, tested, or pasted into an issue.
So the same rendering path produces the interactive view and the `--render` dump that lands in
a file, and there is only one implementation to keep honest.

Design rules this view follows, each of which exists to stop a specific failure:

* **Confidence and its source are always on screen together.** A number without the evidence
  that produced it is a vibe, not a decision.
* **Raw System-1 output is never hidden behind the summary.** A user who wants to know why
  must not have to run a different command.
* **Uncertainty and degradation are shown, not omitted.** A run that fell back to a
  rule-based policy says so in the header.
* **Data freshness and simulation status are always visible.** A simulated price that looks
  like a live one is the worst failure this product could have.
* **Abstention is presented as a result, not an error.** "I cannot tell" is information.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from divya.data.nse_taxonomy import UNRESOLVED
from divya.runtime.loop import LoopResult
from divya.runtime.state import MAX_OBSERVATION_AGE_S, Observation, SharedState

SPARK = {0: "·", 1: "▁", 2: "▂", 3: "▃", 4: "▄", 5: "▅", 6: "▆", 7: "▇", 8: "█"}


def _confidence_bar(p: float, width: int = 20) -> Text:
    """A fixed-width confidence bar.

    Fixed width on purpose. A bar that scales to its own maximum makes 0.4 look certain
    whenever nothing bigger is on screen, which is precisely the illusion this product
    exists to remove.
    """
    p = max(0.0, min(1.0, p))
    filled = round(p * width)
    colour = "green" if p >= 0.75 else "yellow" if p >= 0.5 else "red"
    return Text("█" * filled + "░" * (width - filled), style=colour)


def _freshness(obs: Observation) -> Text:
    age = obs.age_seconds()
    if obs.is_simulated:
        return Text("SIMULATED — not market data", style="bold magenta")
    if age < 0:
        return Text(f"timestamp in the future ({obs.retrieved_at})", style="bold red")
    if age > MAX_OBSERVATION_AGE_S:
        return Text(f"STALE — retrieved {int(age // 86400)}d ago", style="bold red")
    if age > 3600:
        return Text(f"{int(age // 3600)}h old", style="yellow")
    return Text(f"fresh ({int(age)}s ago)", style="green")


def _header(state: SharedState, result: LoopResult | None) -> Panel:
    term = state.termination.value if state.termination else "running"
    style = {
        "finished": "green", "abstained": "yellow",
        "max_turns": "yellow", "error": "red",
    }.get(term, "white")

    left = Text()
    left.append("DIVYA", style="bold white on dark_blue")
    left.append(f"  {state.task_id}\n", style="dim")
    left.append("termination  ", style="dim")
    left.append(f"{term}", style=f"bold {style}")
    if state.termination_reason:
        left.append(f"  — {state.termination_reason}", style="dim")

    body = Group(left, Text())
    if result and result.degraded:
        warn = Text()
        warn.append("DEGRADED  ", style="bold red on yellow")
        warn.append(result.degraded[0], style="yellow")
        body = Group(left, warn)
    return Panel(body, border_style=style, padding=(0, 1))


def _observations(state: SharedState) -> Panel:
    t = Table(box=None, show_header=False, expand=True, pad_edge=False)
    t.add_column("", width=2)
    t.add_column("source", style="bold", no_wrap=True)
    t.add_column("kind", style="dim")
    t.add_column("freshness")
    t.add_column("excerpt", style="dim", overflow="ellipsis", max_width=44)

    for o in state.observations[:6]:
        t.add_row(
            "▸" if not o.is_simulated else "◇",
            o.source_id[:28],
            o.kind,
            _freshness(o),
            " ".join(o.content.split())[:44],
        )
    more = len(state.observations) - 6
    if more > 0:
        t.add_row("", f"… {more} more", "", "", "")
    return Panel(t, title="[bold]sources", border_style="dim")


def _system1(state: SharedState) -> Panel:
    """Every System-1 answer, with the raw probability distribution kept visible.

    Top-3 only, deliberately: the full 10-way distribution is in the trace, and a table that
    prints it inline is a table nobody reads. The top-3 plus the confidence bar is what
    actually distinguishes a confident answer from a lucky one.
    """
    t = Table(box=None, show_header=True, expand=True, header_style="bold dim", pad_edge=False)
    t.add_column("decision", no_wrap=True)
    t.add_column("answer", no_wrap=True)
    t.add_column("conf", no_wrap=True)
    t.add_column("", no_wrap=True, width=22)
    t.add_column("spec / call", style="dim", no_wrap=True)

    latest = state.latest_system1
    call_index = {n: i for i, r in enumerate(state.system1_records) for n in r.decision_names}

    for name, ans in latest.items():
        if ans.get("type") == "choice":
            value = str(ans.get("choice", "-"))
            conf = float(ans.get("confidence", 0.0) or 0.0)
            probs = ans.get("probabilities") or {}
            top = sorted(probs.items(), key=lambda kv: -kv[1])[:3]
            detail = "  ".join(f"{k[:12]} {v:.2f}" for k, v in top)
        elif ans.get("type") == "noul":
            v = float(ans.get("noul", 0.0) or 0.0)
            value = (ans.get("labels") or {}).get("true", "yes") if v >= 0.5 else (
                ans.get("labels") or {}).get("false", "no")
            conf = v
            detail = f"P(true)={v:.3f}"
        else:
            value = f"level {ans.get('score', '-')}"
            conf = float(ans.get("confidence", 0.0) or 0.0)
            detail = f"score={ans.get('score')}"
        t.add_row(name, value, f"{conf:.3f}", _confidence_bar(conf),
                  f"{call_index.get(name, 0)} · {detail[:40]}")

    if not latest:
        return Panel(Text("no System-1 answers were produced", style="dim red"),
                     title="[bold]system-1", border_style="red")
    return Panel(t, title="[bold]system-1 decisions", border_style="blue")


def _system2(state: SharedState) -> Panel:
    t = Table(box=None, expand=True, pad_edge=False)
    t.add_column("turn", width=4, style="dim")
    t.add_column("provider", no_wrap=True)
    t.add_column("action", no_wrap=True)
    t.add_column("ms", justify="right", style="dim")
    t.add_column("rationale", style="dim", overflow="ellipsis", max_width=40)

    for r in state.system2_records:
        action = r.kind + (f" {r.decisions}" if r.decisions else "")
        t.add_row(
            str(r.turn_index),
            f"{r.provider}:{r.model}" + ("" if r.is_model else "  [not a model]"),
            action[:34],
            f"{r.latency_ms:.0f}",
            r.rationale[:40],
        )
    if not state.system2_records:
        return Panel(Text("no System-2 calls were made", style="dim"), title="[bold]system-2")
    return Panel(t, title="[bold]system-2 trajectory", border_style="magenta")


def _verdict(state: SharedState) -> Panel:
    if state.termination and state.termination.value == "abstained":
        style, title = "yellow", "abstained"
        head = Text("The system declined to conclude.\n\n", style="bold yellow")
    elif state.termination and state.termination.value == "error":
        style, title = "red", "failed"
        head = Text("The run failed safely.\n\n", style="bold red")
    else:
        style, title = "green", "conclusion"
        head = Text("")

    body = Group(
        head,
        Text(state.conclusion or "(none recorded)", style="bold"),
        Text(),
        Text("confidence  ", style="dim"),
        _confidence_bar(state.confidence),
        Text(f"  {state.confidence:.3f}", style="bold"),
        Text("uncertainty  ", style="dim") ,
        Text(state.uncertainty or "none recorded", style="yellow" if state.uncertainty != "none recorded" else "dim"),
    )
    return Panel(body, title=f"[bold]{title}", border_style=style)


def _trace(state: SharedState) -> Panel:
    """The transition log, one transition per row.

    A table rather than flowed text: a wrapped paragraph of transitions cannot be scanned, and
    a trace that cannot be scanned is not an audit artefact.
    """
    t = Table(box=None, expand=True, pad_edge=False, show_header=True, header_style="bold dim")
    t.add_column("#", width=3, style="dim", justify="right")
    t.add_column("transition", no_wrap=True, style="bold cyan", width=17)
    t.add_column("detail", overflow="ellipsis", no_wrap=True)

    for tr in state.trace[-12:]:
        detail = tr.detail
        bits: list[str] = []
        for k in ("decisions", "spec", "checkpoint", "status", "reason", "confidence",
                  "termination", "source_id", "observation_id", "content_hash", "chars",
                  "prompt_tokens", "completion_tokens", "repaired", "error"):
            if k in detail and detail[k] not in (None, "", [], {}):
                bits.append(f"{k}={detail[k]}")
        t.add_row(str(tr.index), tr.kind, "  ".join(bits))

    if len(state.trace) > 12:
        t.caption = f"{len(state.trace) - 12} earlier transitions in the JSON trace"
        t.caption_style = "dim italic"
    return Panel(t, title="[bold]trace (fully reconstructable)", border_style="dim")


def render(result: LoopResult, console: Console | None = None) -> None:
    """Print the full terminal view for one run."""
    c = console or Console()
    state = result.state
    c.print(_header(state, result))
    c.print(_observations(state))
    c.print(_system2(state))
    c.print(_system1(state))
    c.print(_verdict(state))

    m = result.metrics()
    cost = Table.grid(padding=(0, 3))
    cost.add_column(style="dim")
    cost.add_column()
    cost.add_row("system-1 calls", str(m["system1_calls"]))
    cost.add_row("system-2 calls", str(m["system2_calls"]))
    cost.add_row("turns", str(m["turns"]))
    cost.add_row("system-1 latency", f"{m['system1_latency_ms']:.0f} ms")
    cost.add_row("system-2 latency", f"{m['system2_latency_ms']:.0f} ms")
    cost.add_row("prompt tokens", str(m["prompt_tokens"]))
    cost.add_row("disagreements", str(m["disagreements"]))
    c.print(Panel(cost, title="[bold]cost", border_style="dim"))

    c.print(_trace(state))
    c.print(
        Text(
            "Raw System-1 payloads, full transition log, and the exact request sent to each "
            "engine are in the JSON trace.  divya show <task-id> --full",
            style="dim italic",
        )
    )


def render_event_stream(items: list[dict[str, Any]], console: Console | None = None) -> None:
    """A stream view over fetched announcements, before any decision has been made."""
    c = console or Console()
    t = Table(box=None, expand=True, header_style="bold", pad_edge=False)
    t.add_column("when", style="dim", no_wrap=True)
    t.add_column("symbol", style="bold", no_wrap=True)
    t.add_column("nse class", style="cyan", no_wrap=True)
    t.add_column("→ our label", style="dim", no_wrap=True)
    t.add_column("text", overflow="ellipsis", max_width=52)

    for it in items[:60]:
        label = it.get("label_event_type", "")
        style = "dim yellow" if label == UNRESOLVED else "green"
        t.add_row(
            str(it.get("announced_at", ""))[:16],
            str(it.get("symbol", ""))[:10],
            str(it.get("nse_desc", ""))[:30],
            Text(label or "-", style=style),
            " ".join(str(it.get("text", "")).split())[:52],
        )
    c.print(
        Panel(
            t,
            title="[bold]NSE corporate announcements",
            subtitle=f"[dim]{len(items)} shown · yellow = no scorable event type",
            border_style="blue",
        )
    )
