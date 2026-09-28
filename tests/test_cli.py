"""Tests for the command line.

The CLI is the product's actual surface, and it is also the most likely place for the
documentation to drift away from the code. Two claims are pinned here:

* every command the README shows a reader actually parses against the real parser, extracted from
  the README itself rather than re-typed, so the two cannot diverge;
* the module docstring's list of subcommands matches the parser.

The second check currently fails the project's own documentation, not its code: `cli.py`'s
docstring advertises `divya eval` and `build_parser()` has no `eval` subcommand. The evaluation
harness is reachable as `python -m divya.eval.harness` but not as `divya eval`. That is pinned
below as a known gap rather than quietly ignored, because a documented command that does not
exist is exactly the kind of thing an independent reviewer should find.

Nothing here runs the decision loop against a real checkpoint: `cmd_decide` is only exercised on
its early-exit paths, which return before System-1 is touched. No network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

import divya.cli as cli
from divya.protocol.loader import ProtocolError, load_protocol

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"


# --- the parser ------------------------------------------------------------


def test_every_documented_command_builds_and_resolves_to_a_handler():
    parser = cli.build_parser()
    minimal = {
        "doctor": ["doctor"],
        "fetch": ["fetch", "nse-announcements"],
        "decide": ["decide", "--text", "x"],
        "show": ["show", "task_abc"],
        "protocol": ["protocol", "show"],
    }
    for cmd, argv in minimal.items():
        args = parser.parse_args(argv)
        assert callable(args.func), cmd
        assert args.command == cmd


def test_no_subcommand_is_a_usage_error_not_a_silent_no_op():
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([])
    assert exc.value.code == 2


def test_decide_requires_exactly_one_text_source():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["decide"])
    with pytest.raises(SystemExit):
        parser.parse_args(["decide", "--text", "x", "--file", "y"])
    assert parser.parse_args(["decide", "--text", "x"]).file is None
    assert parser.parse_args(["decide", "--file", "y"]).text is None


def test_decide_defaults_to_the_measured_architecture():
    """`system1` is the default because D-012 measured the loop worse; that must not drift."""
    args = cli.build_parser().parse_args(["decide", "--text", "x"])
    assert args.mode == "system1"
    assert args.max_turns == 4
    assert args.min_confidence == 0.55
    assert args.escalation_disabled if hasattr(args, "escalation_disabled") else True
    loop = cli.build_parser().parse_args(["decide", "--text", "x", "--mode", "loop"])
    assert loop.mode == "loop" and loop.no_escalation is False
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["decide", "--text", "x", "--mode", "bogus"])


def test_fetch_sources_and_protocol_subcommands_are_enumerated():
    parser = cli.build_parser()
    for source in ("nse-announcements", "nse-prices", "nifty50"):
        assert parser.parse_args(["fetch", source]).source == source
    for sub in ("show", "check", "diff"):
        assert parser.parse_args(["protocol", sub]).protocol_cmd == sub
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "bloomberg"])


# --- the README's own examples ---------------------------------------------


def _readme_commands() -> list[str]:
    """Every `divya ...` line in a fenced code block, with wrapped lines rejoined."""
    text = README.read_text(encoding="utf-8")
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    out: list[str] = []
    for block in blocks:
        pending: list[str] = []
        for raw in block.splitlines():
            line = raw.strip()
            if not pending and not line.startswith("divya ") and not line.startswith("$ divya "):
                continue
            if not pending and line.startswith("$ "):
                line = line[2:]
            pending.append(line)
            if "".join(pending).count('"') % 2 == 1:
                continue  # the example wraps across lines inside a quoted argument
            out.append(" ".join(pending))
            pending = []
    return out


def test_the_readme_contains_command_examples_to_check():
    commands = _readme_commands()
    assert len(commands) >= 6, f"README command extraction found only {commands}"
    # `divya doctor` is only ever shown as `make doctor` in the README, so it is not in the set
    # of literal CLI examples; the parser test above covers it directly.
    for sub in ("decide", "fetch", "protocol", "show"):
        assert any(c.startswith(f"divya {sub}") for c in commands), sub


@pytest.mark.parametrize("command", _readme_commands())
def test_every_readme_command_example_parses(command: str) -> None:
    import shlex

    # Strip a trailing shell comment. A README legitimately writes
    # `divya index --days 2 --limit 500  # what this does`, and shlex does not treat `#` as a
    # comment unless told to -- so without this the docs are untestable rather than wrong.
    argv = shlex.split(command, comments=True)
    assert argv[0] == "divya", command
    args = cli.build_parser().parse_args(argv[1:])
    assert callable(args.func), command


def test_the_readme_documents_no_command_the_parser_lacks():
    """The inverse direction: nothing in the README may reference a subcommand that is gone."""
    known = set(cli.build_parser()._subparsers._group_actions[0].choices)  # type: ignore[attr-defined]
    for command in _readme_commands():
        sub = command.split()[1]
        assert sub in known, f"README documents `divya {sub}` but the parser does not provide it"


def test_the_cli_docstring_lists_a_subcommand_the_parser_lacks():
    """Known gap, pinned.

    `cli.py`'s module docstring advertises `divya eval`. The A/B/C/D harness is a separate
    entry point (`python -m divya.eval.harness`) and was never wired into the CLI. A reader who
    follows the docstring gets an argparse error. Fix by adding the subcommand; this assertion
    then has to be updated deliberately.
    """
    doc = cli.__doc__ or ""
    advertised = re.findall(r"^\s{4}divya ([a-z-]+)", doc, re.MULTILINE)
    assert advertised, "the module docstring no longer documents any commands"
    known = set(cli.build_parser()._subparsers._group_actions[0].choices)  # type: ignore[attr-defined]
    missing = [a for a in advertised if a not in known]
    assert missing == ["eval"], f"the documented-vs-implemented gap changed: {missing}"


# --- failure paths ---------------------------------------------------------


def test_main_returns_non_zero_when_the_protocol_path_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DIVYA_PROTOCOL_PATH", str(tmp_path / "no-such-protocol.yaml"))
    assert cli.main(["protocol", "check"]) == 1
    assert cli.main(["protocol", "show"]) == 1
    assert cli.main(["decide", "--text", "Acme Industries declared a dividend."]) == 1


def test_main_returns_non_zero_when_the_protocol_is_malformed(monkeypatch, tmp_path):
    """A protocol that violates the calibration cap fails at load, and the CLI says so."""
    bad = tmp_path / "questions.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "protocol_version": "9.9.9",
                "specs": [
                    {
                        "name": "s",
                        "version": 1,
                        "questions": [
                            {
                                "name": "many",
                                "type": "choice",
                                "instructions": "pick",
                                "criteria": {f"opt{i}": f"option {i}" for i in range(11)},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProtocolError, match="uncalibrated"):
        load_protocol(bad)
    monkeypatch.setenv("DIVYA_PROTOCOL_PATH", str(bad))
    assert cli.main(["protocol", "check"]) == 1


def test_main_reports_a_non_protocol_yaml_file_as_an_error(monkeypatch, tmp_path):
    junk = tmp_path / "questions.yaml"
    junk.write_text("- just\n- a list\n", encoding="utf-8")
    monkeypatch.setenv("DIVYA_PROTOCOL_PATH", str(junk))
    assert cli.main(["protocol", "check"]) == 1


def test_decide_refuses_empty_input_before_doing_any_work(tmp_path, monkeypatch):
    monkeypatch.setenv("DIVYA_PROTOCOL_PATH", str(tmp_path / "missing.yaml"))
    assert cli.main(["decide", "--text", "   \n\t "]) == 2
    assert cli.main(["decide", "--text", ""]) == 2


def test_decide_reports_a_missing_input_file_rather_than_crashing(monkeypatch, tmp_path):
    monkeypatch.setenv("DIVYA_PROTOCOL_PATH", str(REPO / "models" / "questions.yaml"))
    with pytest.raises((FileNotFoundError, OSError)):
        cli.main(["decide", "--file", str(tmp_path / "missing.txt")])


def test_show_returns_one_for_a_trace_that_does_not_exist(tmp_path, capsys):
    assert cli.main(["show", "task_doesnotexist", "--path", str(tmp_path / "nope.json")]) == 1
    assert "no trace at" in capsys.readouterr().err


def test_show_prints_a_stored_run_and_its_trace(tmp_path, capsys):
    from divya.runtime.loop import LoopResult, read_trace, write_trace
    from divya.runtime.state import (
        SharedState,
        StateBuilder,
        System1Record,
        TerminationStatus,
    )

    state = SharedState(protocol_version="0.1.0", domain="d", objective="o")
    b = StateBuilder(state)
    b.record_system1(
        System1Record(
            turn_index=0,
            decision_names=["event_type"],
            spec_name="event_triage",
            spec_version=2,
            protocol_version="0.1.0",
            request={"state_chars": 12},
            raw_response={"answers": {"event_type": {"choice": "capital_action"}},
                          "routing": {"model": "english"}},
            answers={"event_type": {"type": "choice", "choice": "capital_action",
                                    "probabilities": {"capital_action": 0.82},
                                    "confidence": 0.82}},
            checkpoint="english",
        )
    )
    b.set_outcome("a dividend was declared", 0.71, uncertainty="none recorded")
    b.terminate(TerminationStatus.FINISHED, "System-2 concluded")
    path = write_trace(LoopResult(state=state, builder=b), tmp_path / "t.json")
    assert cli.main(["show", "t", "--path", str(path)]) == 0
    out = capsys.readouterr().out
    assert "termination=finished" in out
    assert "a dividend was declared" in out
    assert "terminate" in out and '"status": "finished"' in out
    assert "0 system1" in out, "every recorded System-1 call leaves a transition"

    assert cli.main(["show", "t", "--path", str(path), "--full"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full == read_trace(path), "--full must print the stored document verbatim"
    rec = full["state"]["system1_records"][0]
    assert rec["raw_response"]["routing"]["model"] == "english", (
        "AGENTS.md rule 4: the raw System-1 payload is stored alongside the parsed answer and "
        "`divya show --full` is the only command that reaches it"
    )
    assert rec["answers"]["event_type"]["choice"] == "capital_action"
    assert rec["checkpoint"] == "english"
    assert full["state"]["termination"] == "finished"


def test_version_is_reported():
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--version"])
    assert exc.value.code == 0


def test_doctor_reports_the_truth_when_nothing_is_reachable(monkeypatch, capsys):
    """`divya doctor` is the first thing a new user runs; it must not guess and must not crash.

    No System-1, no resident model, no network. Every one of those must produce a *statement*, not
    a traceback, because the whole point of the command is to answer "what works here?".
    """
    from divya.system2.provider import HeuristicProvider

    class NoLaya:
        def is_available(self) -> bool:
            return False

    def dead_get(*args: object, **kwargs: object) -> None:
        raise OSError("network is unreachable")

    monkeypatch.setattr(cli, "LayaSystem1", NoLaya)
    monkeypatch.setattr(cli, "build_provider", lambda: HeuristicProvider())
    monkeypatch.setattr("httpx.get", dead_get)
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "laya             NOT INSTALLED" in out
    assert "the runtime will degrade to system-2 only and say so" in out
    assert "ollama cli       not on PATH" in out
    assert "unreachable (OSError)" in out
    assert "NOT redistributable" in out
    assert "redistributable" in out, "the fixture source is redistributable and must say so"
    assert "NOT clearance to redistribute" in out
    # A heuristic provider is never a model, and doctor must not imply it is one.
    assert "is_model=False" in out
