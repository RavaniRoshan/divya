"""The `divya` command line.

The CLI is the product's actual surface, and it is built around one rule: **every command
either produces a decision with visible provenance, or says plainly why it could not.** There
is no command that returns a bare verdict.

Subcommands:

    divya fetch nse --days 30        pull live announcements into a local store
    divya decide <text|--file>       run one event through the loop and show the trace
    divya show <task-id>             inspect a stored run
    divya protocol show|diff         inspect the versioned decision protocol
    divya eval                       run the A/B/C/D harness
    divya doctor                     check the environment and say what works
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from rich.console import Console

from divya import __version__
from divya.data.nse import NseAnnouncements, NseBhavcopyLive, NseIndexConstituents
from divya.data.nse_taxonomy import classify, is_measurable
from divya.protocol.loader import ProtocolError, check_migration, load_protocol
from divya.runtime.loop import DivyaRuntime, LoopConfig, read_trace, write_trace
from divya.runtime.state import Observation
from divya.system1.laya_adapter import LayaSystem1
from divya.system2.provider import build_provider

STORE = Path("data/store")
TRACES = Path("data/traces")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _age_seconds(ts: str | None) -> float | None:
    """Numeric age in seconds, or None. The display form is never compared to a threshold."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return (datetime.now(UTC) - t).total_seconds()


def _available_ram_gib() -> float:
    """Available RAM in GiB, or -1.0 if it cannot be read.

    A doctor command that reports a number it invented is worse than one that admits it does
    not know: this box is RAM-constrained, so a wrong figure here would mislead exactly the
    person who needs it.
    """
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    except (OSError, ValueError, IndexError):
        pass
    return -1.0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report what actually works in this environment. Never guesses, never optimises."""

    print(f"divya {__version__}\n")

    print("system")
    print(f"  python           {sys.version.split()[0]}")
    print(f"  platform         {sys.platform}")
    print(f"  cpu cores        {os.cpu_count()}")
    print(f"  ram available    {_available_ram_gib():.1f} GiB")

    print("\nsystem-1 (laya)")
    s1 = LayaSystem1()
    if s1.is_available():
        print("  laya             importable")
        import laya

        print(f"  version          {laya.__version__}")
        try:
            import torch

            print(f"  torch            {torch.__version__}  cuda={torch.cuda.is_available()}")
        except Exception:
            print("  torch            not importable")
        print("  checkpoint       not loaded yet (loads on first decide; ~7 s, ~2.8 GB RSS)")
    else:
        print("  laya             NOT INSTALLED -- system-1 is unavailable")
        print("                    the runtime will degrade to system-2 only and say so")

    print("\nsystem-2 (reasoning model)")
    # Check for the ollama *binary*, not the Python package: this project talks to the HTTP
    # API and never imports the package, so an import-based check reports "not present" on a
    # machine where the CLI works fine.
    cli_path = shutil.which("ollama")
    print(f"  ollama cli       {cli_path}" if cli_path
          else "  ollama cli       not on PATH (the HTTP API may still be running)")
    provider = build_provider()
    print(f"  provider         {provider.info.name} model={provider.info.model} "
          f"is_model={provider.info.is_model}")
    if provider.info.name == "ollama":
        import httpx

        base = str(getattr(provider, "base_url", "http://localhost:11434"))
        try:
            r = httpx.get(f"{base}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            print(f"  server           reachable, {len(models)} model(s): {', '.join(models)}")
            if provider.info.model and provider.info.model not in models:
                print(f"  WARNING          {provider.info.model} is not pulled. "
                      f"`ollama pull {provider.info.model}`")
        except Exception as exc:
            print(f"  server           UNREACHABLE ({exc})")
            print("                    `ollama serve` to start it")

    print("\ndata sources")
    from divya.data.sources import LICENSE_REGISTER

    for vid, v in LICENSE_REGISTER.items():
        flag = "redistributable" if v.redistribution_allowed else "NOT redistributable"
        print(f"  {vid:<20} {flag}")

    print("\nnetwork")
    for name, url in [
        ("nse bhavcopy", "https://nsearchives.nseindia.com/"),
        ("nse announcements", "https://www.nseindia.com/"),
    ]:
        import httpx

        try:
            r = httpx.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            print(f"  {name:<18} HTTP {r.status_code}")
        except Exception as exc:
            print(f"  {name:<18} unreachable ({type(exc).__name__})")

    print("\ndata licensing note: live NSE endpoints are exchange-proprietary with no located")
    print("reuse grant. Fine for self-hosting; NOT clearance to redistribute. Fixtures are the")
    print("shipped default and are labelled SIMULATED in the data itself.")
    return 0


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=args.days)
    STORE.mkdir(parents=True, exist_ok=True)

    if args.source == "nse-announcements":
        ann_src = NseAnnouncements()
        try:
            anns, truncated = ann_src.fetch(start, end, limit=args.limit)
        except Exception as exc:
            print(f"fetch failed: {exc}", file=sys.stderr)
            return 1
        out = STORE / f"nse_announcements_{start:%Y%m%d}_{end:%Y%m%d}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for a in anns:
                fh.write(
                    json.dumps(
                        {
                            "seq_id": a.seq_id, "symbol": a.symbol, "company": a.company,
                            "industry": a.industry, "nse_desc": a.desc, "text": a.text,
                            "pdf_url": a.pdf_url, "announced_at": a.announced_at,
                            "has_xbrl": a.has_xbrl,
                            "label_event_type": classify(a.desc),
                            "label_is_measurable": is_measurable(a.desc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        measurable = sum(1 for a in anns if is_measurable(a.desc))
        print(f"wrote {len(anns)} announcements to {out}")
        print(f"  window            {start} .. {end}")
        print(f"  measurable        {measurable} ({measurable / max(len(anns), 1):.1%}) "
              f"map to a scorable event type")
        print(f"  unresolved        {len(anns) - measurable} are filing containers or routine "
              f"process (not model errors)")
        if truncated:
            print("  WARNING: response hit the record cap; narrow the window", file=sys.stderr)
        print("  licence           NOT redistributable. Self-host use only "
              "(see src/divya/data/sources.py).")
        if not args.no_render:
            from divya.terminal.view import render_event_stream

            rows = [
                json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()[:200]
            ]
            Console(width=args.width).print()
            render_event_stream(rows)
        return 0

    if args.source == "nse-prices":
        price_src = NseBhavcopyLive()
        day = date.fromisoformat(args.day) if args.day else date.today()
        try:
            rows = price_src.fetch_rows(day)
        except Exception:
            # Markets close at weekends and on holidays, so "yesterday" usually has no file.
            # Probing back is cheap and needs no holiday calendar to maintain.
            fallback = price_src.previous_trading_day(day)
            if fallback is None:
                print(f"no bhavcopy found for {day} or the previous 10 days", file=sys.stderr)
                return 1
            print(f"{day} has no file; using previous trading day {fallback}")
            day = fallback
            rows = price_src.fetch_rows(day)
        out = STORE / f"bhavcopy_{day:%Y%m%d}.csv"
        out.write_text(
            "\n".join(",".join(r.values()) for r in rows[:200]), encoding="utf-8"
        )
        print(f"wrote {min(len(rows), 200)} of {len(rows)} rows to {out}")
        print(f"  as-of             {day} (EOD). This is a historical snapshot, not a live feed.")
        print("  licence           NOT redistributable. Self-host use only.")
        return 0

    if args.source == "nifty50":
        try:
            rows = NseIndexConstituents().fetch()
        except Exception as exc:
            print(f"fetch failed: {exc}", file=sys.stderr)
            return 1
        out = STORE / "nifty50.csv"
        out.write_text("\n".join(",".join(r.values()) for r in rows), encoding="utf-8")
        print(f"wrote {len(rows)} constituents to {out}")
        return 0

    return 1


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the FastAPI backend that the Space UI frontend talks to.

    Binds to loopback by default. There is no authentication -- this is a self-hosted
    single-user service, and shipping an unauthenticated API on 0.0.0.0 would be a claim the
    code does not back.
    """
    import uvicorn

    if args.db:
        os.environ["DIVYA_DB"] = args.db
    print(f"divya api  http://{args.host}:{args.port}   db={args.db or os.environ.get('DIVYA_DB', 'data/store/divya.db')}")
    uvicorn.run("divya.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_terminal(args: argparse.Namespace) -> int:
    """Launch the TUI. Imported lazily so the CLI stays fast and headless-friendly."""
    from divya.terminal.app import main as terminal_main

    return terminal_main(store_path=args.db, provider_kind=args.mode)


def cmd_index(args: argparse.Namespace) -> int:
    from divya.data.store import Store, ingest_nse

    store = Store(args.db) if args.db else Store()
    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=args.days)
    try:
        summary = ingest_nse(store, str(start), str(end), limit=args.limit)
    except Exception as exc:
        print(f"index failed: {exc}", file=sys.stderr)
        return 1
    print(f"indexed {summary['fetched']} announcements from NSE "
          f"({start} .. {end}) into {store.path}")
    print(f"  new rows      {summary['inserted']}")
    print(f"  measurable    {summary['measurable']}  (map to a scorable event type)")
    if summary["truncated"]:
        print("  WARNING: response hit the record cap; narrow the window", file=sys.stderr)
    print(f"  store now     {store.stats()}")
    print(f"\n  open the terminal with:  divya terminal --db {store.path}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    """Two-stage read of one event, reporting exactly what it cost and why it stopped there."""
    from divya.data.store import Store
    from divya.data.twostage import TwoStageReader

    store = Store(args.db) if args.db else Store()
    row = store.get_event(args.seq_id) if args.seq_id else None
    if row is None and args.symbol:
        hist = store.history(args.symbol.upper(), limit=1)
        row = hist[0]["event"] if hist else None
    if row is None:
        where = args.seq_id or args.symbol
        print(f"no stored event for {where}. Run `divya index` first.", file=sys.stderr)
        return 1

    reader = TwoStageReader(escalate_below=args.escalate_below)
    res = reader.read(row, force_filing=args.force_filing)

    print(f"{row.symbol}  {row.company}   [{row.nse_desc}]")
    print(f"  source        {res.text_source}"
          f"{'  (filing read)' if res.expanded else '  (summary only)'}")
    print(f"  first pass    {'n/a' if res.first_confidence is None else f'{res.first_confidence:.3f}'}"
          f"   threshold {res.escalate_below:.2f}")
    print(f"  why           {res.reason}")
    print(f"  cost          summary {res.summary_ms:.0f}ms  filing {res.filing_ms:.0f}ms"
          f"  total {res.elapsed_ms:.0f}ms")
    for name, ans in res.answers.items():
        summary = json.dumps(ans, ensure_ascii=False)
        if len(summary) > 190:
            summary = summary[:190] + "..."
        print(f"    {name:<26} {summary}")
    return 0


def cmd_filings(args: argparse.Namespace) -> int:
    """Replace summary text with the full filing, where a text layer exists.

    Stored decisions are deliberately NOT recomputed. Silently changing the text a decision was
    made on would make that decision a lie; re-decide explicitly instead.
    """
    from divya.data.filings import enrich_store_with_filings
    from divya.data.store import Store

    store = Store(args.db) if args.db else Store()
    summary = enrich_store_with_filings(
        store, limit=args.limit, measurable_only=not args.all
    )
    print(f"filings: attempted {summary['attempted']}, upgraded {summary['upgraded']} "
          f"to full text, {summary['fell_back_to_summary']} kept the summary")
    if summary["upgraded"]:
        print(f"  expansion       {summary['summary_chars_total']} -> "
              f"{summary['text_chars_total']} chars "
              f"({summary['expansion']:.1f}x) across the upgraded set")
    print("  reason: many Indian filings are scanned images with no text layer; those need OCR "
          "and fall back rather than being decided on as empty documents")
    for ex in summary["examples"][: args.show]:
        print(f"\n  {ex['symbol']}  {ex['nse_desc'][:44]}")
        print(f"    {ex['summary_chars']} -> {ex['chars']} chars "
              f"({ex['expansion']:.1f}x, {ex.get('pages')} pages, "
              f"{ex['boilerplate_removed']} boilerplate chars removed) [{ex['source']}]")
        print(f"    {ex['excerpt'][:280]}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from divya.data.store import Store

    store = Store(args.db) if args.db else Store()
    s = store.stats()
    last = store.last_retrieved()
    age = _age_seconds(last)
    fresh = (
        f"{age:.0f}s ago" if age is not None and age < 7 * 86400
        else (f"STALE — {last}" if last else "NO DATA")
    )
    print(f"store   {store.path}")
    print(f"  events      {s['events']}   symbols {s['symbols']}   measurable {s['measurable']}")
    print(f"  simulated   {s['simulated']}")
    print(f"  decisions   {s['decisions']}   runs {s['runs']}")
    print(f"  last fetch  {fresh}")
    print(f"  laya        {'available' if LayaSystem1().is_available() else 'NOT INSTALLED'}")
    try:
        info = build_provider().info
        print(f"  system-2    {info.name}:{info.model} (is_model={info.is_model})")
    except Exception as exc:
        print(f"  system-2    unavailable ({type(exc).__name__})")
    from divya.protocol.loader import load_protocol

    p = load_protocol()
    print(f"  protocol    {p.protocol_version}  specs: {', '.join(p.names)}")
    return 0


def _resolve_text(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    return args.text or ""


def cmd_decide(args: argparse.Namespace) -> int:
    text = _resolve_text(args)
    if not text.strip():
        print("nothing to decide: pass text or --file", file=sys.stderr)
        return 2

    try:
        protocol = load_protocol()
    except ProtocolError as exc:
        print(f"protocol error: {exc}", file=sys.stderr)
        return 1

    # Default is `system1`, and that default is a measurement, not a simplification.
    # On 120 real NSE announcements the reasoning layer was identical in accuracy to a single
    # System-1 call (0.558, macro-F1 0.436, ECE 0.096, AURC 0.240 -- all four equal) at 4x the
    # p95 latency, and the recurrent loop was *worse* (0.508) at 8.5x. See
    # docs/loop/DECISIONS.md D-012 and docs/research/UNIFICATION_EXPERIMENTS.md E-009.
    # The loop stays available and fully traced under --mode loop.
    if args.mode == "system1":
        runtime = DivyaRuntime(protocol=protocol, system2=None,
                               config=LoopConfig(system1_only=True))
    else:
        runtime = DivyaRuntime(
            protocol=protocol,
            system2=build_provider(),
            config=LoopConfig(
                max_turns=args.max_turns,
                min_confidence=args.min_confidence,
                allow_escalation=not args.no_escalation,
            ),
        )
    obs = Observation(
        kind="document",
        source_id=args.source_id or "cli:stdin",
        source_url=args.source_url,
        content=text,
        retrieved_at=datetime_now(),
        # CLI input is real user input, not synthetic. It is not market data either, and the
        # record says which source it came from so it is never mistaken for a filing.
        is_simulated=False,
    )

    events: list[dict] = []
    result = asyncio.run(
        runtime.run(domain=args.domain, objective=args.objective, observations=[obs],
                    on_event=events.append)
    )

    print(f"\n{'=' * 72}")
    term = result.state.termination
    print(f"task {result.state.task_id}   termination: {term.value if term else 'UNSET (bug)'}")
    print(f"{'=' * 72}")

    for s2 in result.state.system2_records:
        print(f"\n[system-2] turn {s2.turn_index}  {s2.provider}:{s2.model}"
              f"  (is_model={s2.is_model})")
        print(f"  {s2.kind}"
              + (f"  decisions={s2.decisions}" if s2.decisions else "")
              + f"  {s2.latency_ms:.0f}ms")
        if s2.rationale:
            print(f"  rationale: {s2.rationale[:160]}")
        if s2.error:
            print(f"  ERROR: {s2.error}")

    for s1 in result.state.system1_records:
        print(f"\n[system-1] {s1.spec_name}@{s1.spec_version}  "
              f"decisions={s1.decision_names}  checkpoint={s1.checkpoint}  {s1.latency_ms:.0f}ms")
        if s1.error:
            print(f"  ERROR: {s1.error}")
        for name, ans in s1.answers.items():
            summary = {k: v for k, v in ans.items() if k != "probabilities"}
            if "probabilities" in ans:
                top = sorted(ans["probabilities"].items(), key=lambda kv: -kv[1])[:3]
                summary["top3"] = [f"{k}={v:.3f}" for k, v in top]
            print(f"  {name:<26} {json.dumps(summary, ensure_ascii=False)[:150]}")

    if result.state.conclusion:
        print(f"\n[conclusion] {result.state.conclusion}")
    print(f"[confidence] {result.state.confidence:.3f}   [uncertainty] {result.state.uncertainty}")

    m = result.metrics()
    print(f"\n[cost] s1 calls={m['system1_calls']} s2 calls={m['system2_calls']} "
          f"turns={m['turns']} s1={m['system1_latency_ms']:.0f}ms "
          f"s2={m['system2_latency_ms']:.0f}ms")
    if result.degraded:
        print(f"[degraded] {len(result.degraded)} issue(s):")
        for d in result.degraded:
            print(f"  - {d}")

    if not args.no_render:
        from divya.terminal.view import render

        console = Console(width=args.width)
        console.print()
        render(result, console)

    if args.trace:
        TRACES.mkdir(parents=True, exist_ok=True)
        p = write_trace(result, TRACES / f"{result.state.task_id}.json")
        print(f"[trace] {p}")
    return 0


def datetime_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# show / protocol
# ---------------------------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    p = Path(args.path) if args.path else TRACES / f"{args.task_id}.json"
    if not p.exists():
        print(f"no trace at {p}", file=sys.stderr)
        return 1
    d = read_trace(p)
    if args.full:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0
    s, m = d["state"], d["metrics"]
    print(f"task {s['task_id']}  termination={s['termination']}  {s['termination_reason']}")
    print(f"conclusion: {s['conclusion']}")
    print(f"confidence: {s['confidence']}  uncertainty: {s['uncertainty']}")
    print(f"cost: {json.dumps(m)}")
    print("\ntrace:")
    for t in s["trace"]:
        print(f"  {t['index']:>2} {t['kind']:<18} {json.dumps(t['detail'])[:110]}")
    return 0


def cmd_protocol(args: argparse.Namespace) -> int:
    try:
        p = load_protocol()
    except ProtocolError as exc:
        print(f"protocol error: {exc}", file=sys.stderr)
        return 1

    if args.protocol_cmd == "show":
        print(f"protocol {p.protocol_version}  specs: {', '.join(p.names)}\n")
        for s in p.specs:
            print(f"{s.name} v{s.version}   ({s.purpose.strip()[:70]}...)")
            for q in s.questions:
                opts = (
                    f"{len(q.criteria)} options" if q.criteria
                    else f"binary {q.labels}" if q.labels else "-"
                )
                print(f"    tier {q.tier}  {q.name:<28} {q.type.value:<7} {opts}")
        return 0

    if args.protocol_cmd == "diff":
        other = load_protocol(args.other)
        changes = check_migration(p, other)
        if not changes:
            print(f"no semantic differences with {args.other}")
            return 0
        print(f"{len(changes)} change(s):")
        for c in changes:
            print(f"  {c}")
        return 0

    if args.protocol_cmd == "check":
        print(f"protocol {p.protocol_version} OK: {len(p.names)} specs, "
              f"{sum(len(s.questions) for s in p.specs)} questions")
        return 0
    return 1


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="divya", description=__doc__.split("\n")[0])
    ap.add_argument("--version", action="version", version=f"divya {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check the environment and report what works").set_defaults(
        func=cmd_doctor
    )

    sv = sub.add_parser("serve", help="run the API that backs the web terminal")
    sv.add_argument("--host", default=os.environ.get("DIVYA_HOST", "127.0.0.1"))
    sv.add_argument("--port", type=int, default=int(os.environ.get("DIVYA_PORT", "8000")))
    sv.add_argument("--db", default=None)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=cmd_serve)

    t = sub.add_parser("terminal", help="launch the keyboard-first terminal (TUI)")
    t.add_argument("--db", default=None, help="sqlite path (default data/store/divya.db)")
    t.add_argument("--mode", choices=["system1", "loop"], default="system1",
                   help="which runtime a keystroke-triggered decision uses. system1 (default) "
                        "is what the measurement supports; see DECISIONS D-012.")
    t.set_defaults(func=cmd_terminal)

    ix = sub.add_parser("index", help="ingest NSE announcements into the local store")
    ix.add_argument("--start", default=None)
    ix.add_argument("--end", default=None)
    ix.add_argument("--days", type=int, default=7)
    ix.add_argument("--limit", type=int, default=5000)
    ix.add_argument("--db", default=None)
    ix.set_defaults(func=cmd_index)

    tr = sub.add_parser(
        "read",
        help="decide an event with two-stage reading: summary first, filing only if unsure",
    )
    tr.add_argument("--db", default=None)
    tr.add_argument("--symbol", required=True, help="a symbol present in the store")
    tr.add_argument("--seq-id", default=None, help="a specific event; overrides --symbol")
    tr.add_argument("--escalate-below", type=float, default=0.60)
    tr.add_argument(
        "--force-filing", action="store_true",
        help="skip the summary pass; the upper bound when latency does not matter",
    )
    tr.set_defaults(func=cmd_read)

    fl = sub.add_parser(
        "filings",
        help="upgrade stored events from announcement summaries to full filing text (PDF)",
    )
    fl.add_argument("--db", default=None)
    fl.add_argument("--limit", type=int, default=50)
    fl.add_argument("--all", action="store_true", help="include unmeasurable classes too")
    fl.add_argument("--show", type=int, default=1, help="print N extracted examples")
    fl.set_defaults(func=cmd_filings)

    st = sub.add_parser("status", help="store statistics, freshness, and versions")
    st.add_argument("--db", default=None)
    st.set_defaults(func=cmd_status)

    f = sub.add_parser("fetch", help="pull live data into a local store")
    f.add_argument("source", choices=["nse-announcements", "nse-prices", "nifty50"])
    f.add_argument("--start")
    f.add_argument("--end")
    f.add_argument("--day")
    f.add_argument("--days", type=int, default=30)
    f.add_argument("--limit", type=int, default=5000)
    f.add_argument("--no-render", action="store_true")
    f.add_argument("--width", type=int, default=100)
    f.set_defaults(func=cmd_fetch)

    d = sub.add_parser("decide", help="run one event through the System-1/System-2 loop")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--file")
    d.add_argument("--domain", default="corporate_actions")
    d.add_argument("--objective", default=(
        "Classify this Indian corporate disclosure: event type, materiality, and direction."))
    d.add_argument("--source-id")
    d.add_argument("--source-url")
    d.add_argument("--mode", choices=["system1", "loop"], default="system1",
                   help="system1 (default, per D-012) asks System-1 once and reads the typed "
                        "answers. loop runs the full System-2<->System-1 recurrent architecture, "
                        "which measured worse -- available for inspection, not recommended.")
    d.add_argument("--max-turns", type=int, default=4)
    d.add_argument("--min-confidence", type=float, default=0.55)
    d.add_argument("--no-escalation", action="store_true")
    d.add_argument("--trace", action="store_true", help="write a JSONL trace to data/traces/")
    d.add_argument("--no-render", action="store_true", help="skip the terminal view")
    d.add_argument("--width", type=int, default=100)
    d.set_defaults(func=cmd_decide)

    s = sub.add_parser("show", help="inspect a stored run")
    s.add_argument("task_id", nargs="?")
    s.add_argument("--path")
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=cmd_show)

    pr = sub.add_parser("protocol", help="inspect the versioned decision protocol")
    pr.add_argument("protocol_cmd", choices=["show", "check", "diff"])
    pr.add_argument("--other")
    pr.set_defaults(func=cmd_protocol)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
