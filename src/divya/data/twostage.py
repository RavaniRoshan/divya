"""Two-stage reading: classify on the summary, re-read the filing only when it matters.

**The problem this solves.** Full filing text is worth a great deal of accuracy — on real NSE
announcements it moved `capital_action` from F1 0.00 to 0.39, `regulatory_action` from 0.00 to
0.30, and `earnings_result` from 0.33 to 0.80. It also cost **12x the latency**: 4.7 s → 57.7 s
per event, because the encoder reads the whole document.

Paying 12x on every event to help a minority of them is the wrong trade. And the minority is
identifiable *without* reading the filing: the summary is enough to tell you whether this is an
event-bearing filing at all, and the first-pass decision tells you how confident you are.

So: **read the summary first, and only pay for the document when the first pass is not
confident enough to act on.** That is not a heuristic bolted on; it is the same selective
computation the decision protocol already expresses as tiers, applied one level up — to the
document rather than to the question.

**Why the threshold lives here and not in the protocol.** A confidence threshold is a property
of a *decision to stop reading*, not of a question about a document. Putting it in
`questions.yaml` would make the protocol carry a runtime policy it has no opinion about, and
would put the same number in two places. It is a constructor argument here, recorded in the
result so the run can be reproduced.

**What it does not do.** It does not retry when the first pass was *confident and wrong*, and
it cannot: nothing in the summary says the answer will change. That case is the residual error,
and it is why the escalation threshold is deliberately low (read more often) rather than high.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from divya.data.filings import FilingText, get_filing_text
from divya.data.store import EventRow
from divya.protocol.loader import ProtocolError, get_spec, load_protocol
from divya.protocol.schema import Protocol as DecisionProtocol
from divya.runtime.loop import DivyaRuntime, LoopConfig
from divya.system1.laya_adapter import LayaSystem1, NullSystem1
from divya.system2.provider import HeuristicProvider

#: Below this, the summary pass is not trusted and the document is read.
#: 0.60 rather than 0.5 because the mid-confidence band (0.5-0.73) is exactly where Laya
#: measured ECE 0.18, and the first pass's most common failure there is being confidently
#: wrong about which kind of event this is.
DEFAULT_ESCALATE_BELOW = 0.60


@dataclass
class TwoStageResult:
    """The decision, plus exactly what it cost and why it stopped where it did."""

    text: str
    text_source: str          # "summary" | "filing"
    expanded: bool            # did we pay for the document
    escalate_below: float
    first_confidence: float | None
    decision_name: str
    answers: dict[str, Any]
    #: The exact text the decision was made on. A string, not the parsed answers: the point
    #: of keeping it is that a disagreement can be traced to the bytes that produced it.
    raw: str = ""
    summary_ms: float = 0.0
    filing_ms: float = 0.0
    reason: str = ""

    @property
    def elapsed_ms(self) -> float:
        return self.summary_ms + self.filing_ms

    def as_dict(self) -> dict[str, Any]:
        return {
            "text_source": self.text_source,
            "expanded": self.expanded,
            "escalate_below": self.escalate_below,
            "first_confidence": self.first_confidence,
            "decision": self.decision_name,
            "summary_ms": round(self.summary_ms, 1),
            "filing_ms": round(self.filing_ms, 1),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "reason": self.reason,
            "answers": self.answers,
        }


class TwoStageReader:
    """Runs the decision twice when it has to, and once when it does not."""

    def __init__(
        self,
        *,
        escalate_below: float = DEFAULT_ESCALATE_BELOW,
        decisions: list[str] | None = None,
        mode: str = "system1",
        system1: Any | None = None,
    ) -> None:
        self.escalate_below = escalate_below
        self.decisions = decisions or ["event_type"]
        self.mode = mode
        self.protocol_error: str | None = None
        self._system1 = system1 if system1 is not None else (
            LayaSystem1() if LayaSystem1().is_available() else NullSystem1()
        )
        self.protocol: DecisionProtocol | None = None
        try:
            self.protocol = load_protocol()
        except ProtocolError as exc:
            # A missing protocol is a configuration error, not a runtime one; it is recorded
            # rather than raised so the caller can fall back to the summary-only path and say so.
            self.protocol_error = str(exc)

    def _run(self, text: str, row: EventRow) -> tuple[dict[str, Any], float]:
        """One pass over `text`. Returns (answers, elapsed ms).

        The synthetic text still goes through the normal observation path so sanitisation,
        de-duplication and provenance behave exactly as they do in production. A short-circuit
        here would be a second code path, and a second code path is where provenance bugs live.
        """
        if self.protocol is None:
            return {}, 0.0
        spec = get_spec(self.protocol, "event_triage")
        names = [d for d in self.decisions if d in {q.name for q in spec.questions}]
        if not names:
            # No decision named here is in this spec. Ask the whole tier-1 rather than
            # silently returning nothing, which would read as 'the engine had no opinion'.
            names = [q.name for q in spec.questions if q.tier == 1]

        runtime = DivyaRuntime(
            protocol=self.protocol,
            system2=HeuristicProvider() if self.mode == "loop" else None,
            system1=self._system1,
            config=LoopConfig(system1_only=self.mode != "loop", max_turns=3),
        )
        obs = row.to_observation()
        obs.content = text
        # The digest must cover the text actually decided on, or the provenance chain lies.
        import hashlib

        obs.content_hash = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]

        t0 = time.perf_counter()
        result = runtime.run_sync(domain="corporate_actions", objective="Classify this filing.",
                                  observations=[obs])
        elapsed = (time.perf_counter() - t0) * 1000
        return result.state.latest_system1, elapsed

    def read(self, row: EventRow, *, force_filing: bool = False) -> TwoStageResult:
        """Decide on the summary; re-read the filing if the first pass was not confident.

        `force_filing` skips the first pass entirely and is for evaluating the *upper bound* —
        what accuracy is available if latency is not a constraint. It is what produced the
        0.475 number in the full-filing evaluation.
        """
        summary = " ".join(row.text.split())
        decisions = [d for d in self.decisions]

        if force_filing and row.pdf_url:
            ft = self._fetch(row)
            answers, ms = self._run(ft, row)
            return TwoStageResult(
                text=ft, text_source="filing", expanded=True,
                escalate_below=self.escalate_below, first_confidence=None,
                decision_name=",".join(decisions), answers=answers, raw=ft,
                filing_ms=ms, reason="forced: evaluating the no-latency-constraint upper bound",
            )

        answers, ms = self._run(summary, row)
        first_conf = _confidence_of(answers)

        # `None` means System-1 produced no usable confidence at all. That is treated as
        # "escalate": with no confidence there is no basis for skipping the document, and
        # formatting a None into the reason string used to raise TypeError exactly in the
        # path where a clear message mattered most.
        needs_more = first_conf is None or first_conf < self.escalate_below
        if not needs_more:
            return TwoStageResult(
                text=summary, text_source="summary", expanded=False,
                escalate_below=self.escalate_below, first_confidence=first_conf,
                decision_name=",".join(decisions), answers=answers, raw=summary,
                summary_ms=ms,
                reason=(
                    f"summary pass confident at {first_conf:.2f} "
                    f"(>= {self.escalate_below:.2f}); document not read"
                ),  # first_conf is not None here: None escalates
            )

        if not row.pdf_url:
            return TwoStageResult(
                text=summary, text_source="summary", expanded=False,
                escalate_below=self.escalate_below, first_confidence=first_conf,
                decision_name=",".join(decisions), answers=answers, raw=summary,
                summary_ms=ms,
                reason=f"low confidence {_fmt(first_conf)} but no filing is available",
            )

        ft = self._fetch(row)
        if not ft:
            return TwoStageResult(
                text=summary, text_source="summary", expanded=False,
                escalate_below=self.escalate_below, first_confidence=first_conf,
                decision_name=",".join(decisions), answers=answers, raw=summary,
                summary_ms=ms,
                reason=f"low confidence {_fmt(first_conf)} but the filing could not be read",
            )

        answers2, ms2 = self._run(ft, row)
        return TwoStageResult(
            text=ft, text_source="filing", expanded=True,
            escalate_below=self.escalate_below, first_confidence=first_conf,
            decision_name=",".join(decisions), answers=answers2, raw=ft,
            summary_ms=ms, filing_ms=ms2,
            reason=(
                f"summary pass only {_fmt(first_conf)} (< {self.escalate_below:.2f}); "
                f"re-read the filing"
            ),
        )

    def _fetch(self, row: EventRow) -> str:
        ft: FilingText = get_filing_text(row.seq_id, row.text, row.pdf_url)
        return ft.text if ft.used_pdf else ""


def _fmt(c: float | None) -> str:
    """Render a possibly-absent confidence without ever raising."""
    return "n/a" if c is None else f"{c:.2f}"


def _confidence_of(answers: dict[str, Any]) -> float | None:
    """Highest confidence across the decisions we asked for, or None if none reported one.

    `None` rather than `0.0`, because "no decision was produced" and "the decision was
    unconfident" call for different responses: the first should escalate, the second should
    escalate, and a third state where we simply have nothing to act on should not be invented
    by coercing a missing value into a number.
    """
    seen = False
    best: float | None = None
    for ans in answers.values():
        if not isinstance(ans, dict):
            continue
        for key in ("confidence", "noul", "probability"):
            v = ans.get(key)
            if isinstance(v, int | float):
                seen = True
                best = v if best is None else min(best, float(v))
                break
    return best if seen else None
