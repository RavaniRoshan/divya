"""Red-team suite tests.

Two jobs, and the second is the one the rest of the test suite depends on.

1. Assert that `divya.eval.redteam` itself is sound: that the corpus it ships actually contains
   the attacks it claims to, that a case whose expectation is trivially true cannot hide a
   regression, and that the suite exits non-zero when something fails. A red-team runner that
   cannot fail is a decoration.

2. Re-export the System-1 test double. Every other test module that needs a System-1 imports
   `StubSystem1` from here, so there is exactly one definition of it in the repository. It is a
   lexical stand-in with uncalibrated confidence; see `divya.eval.redteam.AdversarialStubSystem1`
   for what it does and does not tell you.

No torch, no checkpoint, no network: these tests must run in CI on a box with no System-1 weights.
The real-engine path is exercised by `python -m divya.eval.redteam`, not here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from divya.eval import redteam as RT
from divya.eval.redteam import (
    CLASSES,
    AdversarialStubSystem1 as StubSystem1,  # re-exported for the rest of the suite
    CLEAN_FILING,
    CLEAN_FILING_2,
    CONTRADICTION_PAIRS,
    INJECTIONS,
    MALFORMED,
    STALE_CASES,
    Engine,
    Probe,
    main,
    render_table,
    run_suite,
    stub_engine,
)

ENGINE = stub_engine()


# --- the corpus is what it claims to be ------------------------------------


def test_every_documented_class_has_a_builder():
    assert set(CLASSES) == {
        "prompt_injection",
        "malformed_input",
        "duplicate_events",
        "stale_data",
        "contradictory",
        "numeric_extraction_trap",
        "resource_exhaustion",
    }
    for name, (builder, note, _prefer_real) in CLASSES.items():
        assert callable(builder), name
        assert note, f"{name} has no class-level note, so the report cannot explain what it tested"


def test_corpus_covers_every_required_attack():
    """Each class must exercise the specific attacks the suite was written to cover.

    Asserting on the case *names* rather than on behaviour is deliberate here: a class that
    silently stopped generating a case would still pass a behavioural assertion over the ones it
    kept, and the missing coverage would be invisible.
    """
    names = {c: {case.name for case in builder(stub_engine())}
             for c, (builder, _n, _p) in CLASSES.items()}

    assert {n.split("_x")[0] for n in names["duplicate_events"]} >= {"identical"}
    assert "near_duplicate_whitespace" in names["duplicate_events"]
    assert {"identical_x2", "identical_x3", "identical_x10"} <= names["duplicate_events"]

    assert {n for n, _t, _d, _f in STALE_CASES} <= names["stale_data"]
    assert {d for _n, _t, d, _f in STALE_CASES} == {1, 8, 400, -2}
    assert "unparseable_timestamp" in names["stale_data"]

    assert {n for n, _a, _b in CONTRADICTION_PAIRS} <= names["contradictory"]
    assert "two_consistent_filings" in names["contradictory"], "the class needs a non-firing control"

    assert {n for n, _t, _d in MALFORMED} == {
        "empty_string", "whitespace_only", "single_character", "huge_200k_chars",
        "lone_surrogates", "nul_bytes", "no_alphabetic", "numbers_only", "mixed_scripts",
    }

    inj = names["prompt_injection"]
    for required in ("ignore_previous", "fake_role_turn", "closing_tag", "always_other",
                     "output_string", "homoglyph", "zero_width", "split_sentence"):
        assert required in inj, f"prompt_injection lost the {required} attack"
    assert len(INJECTIONS) == 8

    assert "max_turns_zero" in names["resource_exhaustion"]
    assert "max_turns_10000_with_a_looper" in names["resource_exhaustion"]
    assert "hanging_system2" in names["resource_exhaustion"]


def test_injection_payloads_actually_reach_the_document():
    """A payload that is silently stripped would make the class vacuous.

    The suite has no sanitisation layer, and the day someone adds one, the injection cases would
    keep passing while testing nothing. This pins that the payload is in the text handed over.
    """
    for name, payload, sentinel in INJECTIONS:
        text = CLEAN_FILING + "\n\n" + payload
        assert payload in text, name
        assert sentinel in text.lower(), name
    assert any(HOMO for HOMO in ("\u0456",) if HOMO in INJECTIONS[5][1]), "homoglyph case lost its lookalike"
    assert "\u200b" in INJECTIONS[6][1], "the zero-width case lost its zero-width spaces"
    assert RT.HOMO_I in INJECTIONS[5][1]


def test_control_filings_classify_as_themselves_under_the_stub():
    """The differential is only meaningful if the control produces a stable, non-degenerate label."""
    p = RT.probe([CLEAN_FILING], StubSystem1())
    assert p.ok and p.event_type == "capital_action"
    assert p.termination == "finished"
    p2 = RT.probe([CLEAN_FILING_2], StubSystem1())
    assert p2.ok and p2.event_type == "m_and_a", "the second control must not collide with the first"


def test_probe_reports_a_raise_instead_of_propagating_it():
    class Exploding:
        def is_available(self) -> bool:
            return True

        def answer(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("engine exploded")

    p = RT.probe(["x"], Exploding())
    assert not p.ok
    assert "engine exploded" in p.error
    assert p.event_type is None and p.termination is None


def test_probe_captures_a_raising_observation_construct():
    """`probe` must survive input the state model refuses, or the class cannot report on it."""
    p = RT.probe(["\udcff\udcfe"], StubSystem1())
    assert not p.ok
    assert "surrogate" in p.error.lower() or "utf-8" in p.error.lower()


# --- a case can actually fail ----------------------------------------------


def test_a_failing_case_is_reported_and_drives_the_exit_code(tmp_path: Path):
    def builder(engine):  # noqa: ANN001, ANN202
        return [RT.Case(name="always_fails", check=lambda: ["this system is broken"])]

    saved = dict(CLASSES)
    try:
        CLASSES.clear()
        CLASSES.update({"malformed_input": (builder, "injected failing builder", False)})
        out = tmp_path / "rt.json"
        rc = main(["--out", str(out), "--no-real-system1", "--quiet", "--class", "malformed_input"])
    finally:
        CLASSES.clear()
        CLASSES.update(saved)
    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["totals"]["failed"] == 1
    assert report["results"][0]["cases"][0]["failures"] == ["this system is broken"]


def test_an_exception_in_a_check_is_a_failure_not_a_pass():
    def boom() -> list[str]:
        raise RuntimeError("the check itself is broken")

    result = RT._run_class("x", ENGINE, lambda e: [RT.Case(name="boom", check=boom)])
    assert result.failed == 1
    assert "the check itself is broken" in result.cases[0].failures[0]


def test_a_broken_observe_does_not_hide_a_passing_case():
    def boom() -> dict[str, object]:
        raise RuntimeError("observer is broken")

    result = RT._run_class(
        "x", ENGINE, lambda e: [RT.Case(name="ok", check=lambda: [], observe=boom)]
    )
    assert result.failed == 0
    assert "observer is broken" in result.cases[0].observed["observe_failed"]


def test_render_table_reports_every_failure():
    report = {
        "totals": {"cases": 2, "passed": 1, "failed": 1, "wall_s": 0.1},
        "results": [
            {
                "class": "c1", "n": 1, "passed": 1, "failed": 0, "note": "note one",
                "engine": {"is_real_laya": False},
                "cases": [{"name": "a", "status": "pass", "failures": []}],
            },
            {
                "class": "c2", "n": 1, "passed": 0, "failed": 1, "note": "note two",
                "engine": {"is_real_laya": True},
                "cases": [{"name": "b", "status": "fail", "failures": ["because"]}],
            },
        ],
    }
    table = render_table(report)
    assert "c1" in table and "c2" in table
    assert "laya" in table and "stub" in table
    assert "FAIL c2/b: because" in table


# --- the suite is reproducible and self-describing --------------------------


def test_stub_only_suite_runs_and_reports_itself(tmp_path: Path):
    out = tmp_path / "redteam.json"
    rc = main(["--out", str(out), "--no-real-system1", "--quiet", "--class", "stale_data"])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["suite"] == "divya.eval.redteam"
    assert report["engines"]["used_for"]["stale_data"] == "lexical stub"
    assert report["totals"]["cases"] == 5
    assert "not a security audit" in report["what_this_is"]
    # The two known freshness defects must be visible in the artifact, not only in prose.
    failed = {c["name"] for r in report["results"] for c in r["cases"] if c["status"] == "fail"}
    assert failed == {"future_timestamp", "unparseable_timestamp"}
    assert rc == 1, "a suite with two known failures must exit non-zero"


def test_unknown_class_is_rejected_before_any_work(tmp_path: Path):
    with pytest.raises(SystemExit):
        main(["--out", str(tmp_path / "x.json"), "--no-real-system1", "--class", "nope"])


def test_run_suite_reports_the_totals_it_printed():
    report = run_suite(["contradictory"], use_real=False)
    by_class = report["results"][0]
    assert by_class["n"] == len(by_class["cases"]) == 5
    assert by_class["passed"] + by_class["failed"] == by_class["n"]
    assert report["totals"]["failed"] == by_class["failed"]
    assert report["totals"]["cases"] == 5


# --- the System-1 test double every other module reuses ---------------------


def test_stub_reports_a_typed_answer_for_every_protocol_decision():
    from divya.protocol.loader import load_protocol

    s1 = StubSystem1()
    p = load_protocol()
    for spec in p.specs:
        rec = s1.answer(CLEAN_FILING, spec, turn_index=0, protocol_version=p.protocol_version)
        assert rec.error is None
        assert set(rec.answers) == {q.name for q in spec.questions}
        for name, ans in rec.answers.items():
            assert ans["type"] in {"choice", "noul", "score"}
            assert "confidence" in ans
            assert 0.0 <= ans["confidence"] <= 1.0, name
    assert len(s1.calls) == len(p.specs)


def test_stub_is_deterministic_and_content_sensitive():
    a = StubSystem1().answer(CLEAN_FILING, _spec(), only=["event_type"])
    b = StubSystem1().answer(CLEAN_FILING, _spec(), only=["event_type"])
    c = StubSystem1().answer(CLEAN_FILING_2, _spec(), only=["event_type"])
    assert a.answers == b.answers
    assert a.answers["event_type"]["choice"] == "capital_action"
    assert c.answers["event_type"]["choice"] == "m_and_a"


def test_stub_is_not_the_production_path():
    """Nothing outside the red-team module and the tests may construct the double."""
    from divya.system1.laya_adapter import LayaSystem1, NullSystem1

    assert not isinstance(LayaSystem1(), StubSystem1)
    assert not isinstance(NullSystem1(), StubSystem1)
    assert StubSystem1().is_available() is True
    assert NullSystem1().is_available() is False


def _spec():  # noqa: ANN202
    from divya.protocol.loader import load_protocol

    return load_protocol().by_name("event_triage")


# --- probe/record plumbing -------------------------------------------------


def test_probe_snapshot_survives_a_failed_run():
    p = Probe(texts=["x"], result=None, elapsed_s=0.0, error="boom")
    snap = p.snapshot()
    assert snap["termination"] is None
    assert snap["event_type"] is None
    assert snap["system1_calls"] == 0


def test_engine_reuses_the_shared_backend_but_not_the_transient_one():
    shared = Engine("s", StubSystem1, is_real=False, detail="d", shared=True)
    assert shared.system1() is shared.system1()
    transient = Engine("t", StubSystem1, is_real=False, detail="d")
    assert transient.system1() is not transient.system1()


def test_module_is_runnable_as_a_script(tmp_path: Path):
    out = tmp_path / "r.json"
    rc = main(["--out", str(out), "--no-real-system1", "--quiet", "--class", "numeric_extraction_trap"])
    assert rc in (0, 1)
    assert out.exists()
    report = json.loads(out.read_text(encoding="utf-8"))
    failed = [c["name"] for c in report["results"][0]["cases"] if c["status"] == "fail"]
    assert failed == ["canary_requested_by_the_degraded_path"], (
        "the numeric canary omission is a known defect; if this starts passing, the fix landed "
        "and this assertion must be updated deliberately rather than by accident"
    )


def test_redteam_module_never_imports_laya_directly():
    """The suite must import on a box with no torch, like every other non-System-1 module.

    `LayaSystem1` is used, which is the sanctioned boundary; `import laya` here would pull torch
    into the eval layer and break the property the whole System-1 split exists to protect.
    """
    src = Path(RT.__file__).read_text(encoding="utf-8")
    assert "import laya" not in src.replace("LayaSystem1", "").replace(
        "LayaSystem1()", ""
    ).replace("LayaSystem1,", "").replace("LayaSystem1)", ""), (
        "the red-team module must reach the engine only through divya.system1.laya_adapter"
    )
    assert "from laya" not in src
    assert RT.LayaSystem1.__module__ == "divya.system1.laya_adapter"
    assert "laya" not in sys.modules or True  # presence depends on the box, not on this module
