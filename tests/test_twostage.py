"""Two-stage reading tests.

The two-stage reader exists to keep the accuracy of full filing text without paying its
latency. The property worth testing is not "does it read the filing" but **"does it read the
filing only when it should"** — a reader that always escalates is correct and useless, and one
that never escalates is fast and wrong.

No Laya in this file. The engine is stubbed so the escalation *policy* can be tested at full
speed, which matters because a policy test that takes 40 s per case is a policy that stops
being tested.
"""

from __future__ import annotations

import pytest

from divya.data.store import EventRow
from divya.data.twostage import _confidence_of


def _row(seq="s1", summary="Short summary text.", pdf="https://x.invalid/a.pdf") -> EventRow:
    return EventRow(
        seq_id=seq, symbol="TEST", company="Test Ltd", industry="test",
        nse_desc="Acquisition", text=summary, pdf_url=pdf, announced_at="2026-09-28T10:00:00+00:00",
        retrieved_at="2026-09-28T10:00:00+00:00", has_xbrl=False, is_simulated=False,
        source_id="test:1", content_hash="deadbeef",
    )


class StubSystem1:
    """Returns a scripted confidence for the summary, a fixed one for the filing.

    `summary_conf` and `filing_conf` are separate so a test can assert that escalation
    *changed* the answer, not merely that it happened.
    """

    def __init__(self, summary_conf=0.9, filing_conf=0.95, gate=0.99):
        self.summary_conf = summary_conf
        self.filing_conf = filing_conf
        self.gate = gate
        self.calls: list[tuple[str, int]] = []

    def is_available(self) -> bool:
        return True

    def answer(self, state_text, spec, *, only=None, turn_index=0, protocol_version="", timeout_note=""):
        n = len(state_text)
        self.calls.append((state_text[:40], n))
        is_filing = n > 5000
        conf = self.filing_conf if is_filing else self.summary_conf
        det = self.gate if is_filing else min(self.summary_conf, self.gate)
        return _record(spec, conf, det, protocol_version, only)


def _record(spec, conf, determinable, protocol_version="", only=None):
    from divya.runtime.state import System1Record

    names = sorted(spec.to_laya(only=only)) if only else sorted(spec.to_laya())
    answers = {
        n: {"type": "noul", "noul": conf, "confidence": conf} for n in names
    }
    answers["event_type"] = {
        "type": "choice", "choice": "m_and_a",
        "probabilities": {"m_and_a": conf}, "confidence": conf,
    }
    answers["event_type_determinable"] = {
        "type": "noul", "noul": determinable, "confidence": determinable,
    }
    return System1Record(
        turn_index=0, decision_names=names, spec_name=spec.name, spec_version=spec.version,
        protocol_version=protocol_version, request={}, raw_response={"answers": answers},
        answers=answers, checkpoint="stub", latency_ms=1.0,
    )


# --- the escalation policy -------------------------------------------------


def test_confident_summary_is_not_escalated(monkeypatch):
    """The whole point. A confident first pass must not pay for the document."""
    import divya.data.twostage as ts

    stub = StubSystem1(summary_conf=0.9)
    monkeypatch.setattr(ts, "get_filing_text", lambda *a, **k: _fake_filing())
    monkeypatch.setattr(ts.TwoStageReader, "_fetch", lambda self, row: _LONG)

    r = ts.TwoStageReader(escalate_below=0.6, system1=stub)
    res = r.read(_row())

    assert res.expanded is False
    assert res.text_source == "summary"
    assert len(stub.calls) == 1, "a confident pass must be a single call"
    assert "not read" in res.reason


def test_low_confidence_summary_escalates_and_re_reads(monkeypatch):
    import divya.data.twostage as ts

    stub = StubSystem1(summary_conf=0.3, filing_conf=0.95)
    monkeypatch.setattr(ts, "get_filing_text", lambda *a, **k: _fake_filing())
    monkeypatch.setattr(ts.TwoStageReader, "_fetch", lambda self, row: _LONG)

    r = ts.TwoStageReader(escalate_below=0.6, system1=stub)
    res = r.read(_row())

    assert res.expanded is True
    assert res.text_source == "filing"
    assert len(stub.calls) == 2, "a low-confidence pass must re-read"
    assert res.first_confidence == pytest.approx(0.3)


def test_escalation_changes_the_answer(monkeypatch):
    """Escalating must be able to change the conclusion, or it is pure cost."""
    import divya.data.twostage as ts

    stub = StubSystem1(summary_conf=0.2, filing_conf=0.95)
    monkeypatch.setattr(ts, "get_filing_text", lambda *a, **k: _fake_filing())
    monkeypatch.setattr(ts.TwoStageReader, "_fetch", lambda self, row: _LONG)

    res = ts.TwoStageReader(escalate_below=0.6, system1=stub).read(_row())
    assert res.answers["event_type"]["probabilities"]["m_and_a"] == pytest.approx(0.95)


def test_threshold_is_configurable(monkeypatch):
    import divya.data.twostage as ts

    monkeypatch.setattr(ts.TwoStageReader, "_fetch", lambda self, row: _LONG)

    loose = StubSystem1(summary_conf=0.7)
    r_loose = ts.TwoStageReader(escalate_below=0.6, system1=loose).read(_row())
    assert r_loose.expanded is False

    strict = StubSystem1(summary_conf=0.7)
    r_strict = ts.TwoStageReader(escalate_below=0.9, system1=strict).read(_row())
    assert r_strict.expanded is True


def test_no_pdf_and_low_confidence_stays_on_the_summary(monkeypatch):
    """No document to read is a reason to report the summary, not to hang or invent one."""
    import divya.data.twostage as ts

    stub = StubSystem1(summary_conf=0.1)
    r = ts.TwoStageReader(escalate_below=0.6, system1=stub)
    res = r.read(_row(pdf=None))

    assert res.expanded is False
    assert res.text_source == "summary"
    assert "no filing" in res.reason
    assert len(stub.calls) == 1


def test_unreadable_pdf_stays_on_the_summary(monkeypatch):
    import divya.data.twostage as ts

    monkeypatch.setattr(ts.TwoStageReader, "_fetch", lambda self, row: "")  # extraction failed
    stub = StubSystem1(summary_conf=0.1)
    res = ts.TwoStageReader(escalate_below=0.6, system1=stub).read(_row())

    assert res.expanded is False
    assert "could not be read" in res.reason


def test_force_filing_skips_the_first_pass(monkeypatch):
    """The upper bound: what is available when latency does not matter."""
    import divya.data.twostage as ts

    monkeypatch.setattr(ts, "get_filing_text", lambda *a, **k: _fake_filing())
    monkeypatch.setattr(ts.TwoStageReader, "_fetch", lambda self, row: _LONG)
    stub = StubSystem1(summary_conf=0.99, filing_conf=0.99)
    res = ts.TwoStageReader(system1=stub).read(_row(), force_filing=True)

    assert res.expanded is True
    assert len(stub.calls) == 1, "force_filing must not pay for the summary pass too"
    assert "upper bound" in res.reason


# --- the confidence helper -------------------------------------------------


def test_confidence_is_the_minimum_across_decisions():
    """Escalation should trigger on the *least* confident decision, not the most."""
    assert _confidence_of({"a": {"confidence": 0.9}, "b": {"confidence": 0.4}}) == pytest.approx(0.4)


def test_no_answers_is_none_not_zero():
    """`None` and `0.0` call for different responses; coercing one into the other is a bug
    that would silently disable escalation whenever a decision reported nothing."""
    assert _confidence_of({}) is None
    assert _confidence_of({"a": {}}) is None
    assert _confidence_of({"a": {"noul": 0.0}}) == pytest.approx(0.0)


def test_result_records_what_it_cost():
    import divya.data.twostage as ts

    stub = StubSystem1(summary_conf=0.99)
    res = ts.TwoStageReader(system1=stub).read(_row())
    d = res.as_dict()
    for k in ("text_source", "expanded", "escalate_below", "first_confidence", "summary_ms", "reason"):
        assert k in d, f"a run must be reproducible from its own record; {k} is missing"


_LONG = "F" * 9000


def _fake_filing():
    from divya.data.filings import FilingText

    return FilingText(
        text=_LONG, source="pdf", chars=len(_LONG), summary_chars=20,
        url="https://x.invalid/a.pdf", pages=2, reason="stub",
    )
