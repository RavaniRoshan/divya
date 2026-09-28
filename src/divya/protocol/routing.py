"""Hierarchical decision routing: ask a cheap gate, then ask only what the gate leaves open.

**Why this exists, and why it is not a design flourish.** The measurement that produced it is
in `DECISIONS.md` D-024 and D-025:

* Writing an explicit contrast clause into the class descriptions did **nothing** — `m_and_a`
  stayed at 0.13 and `capital_action` regressed. A 421M encoder does not read a contrast clause.
* Adding a binary gate, `transfers_a_business`, **worked as a discriminator**: 20 of 24 correct
  on exactly the distinction the 9-way head could not make. But the choice head in the *same
  forward pass* ignored it completely.

That is a property of the architecture, not of the prompt. A non-autoregressive encoder makes
one pass over the whole question set and has no mechanism for "given that this transfers a
business, the answer cannot be `capital_action`". The gate is a correct discriminator sitting
next to a classifier that cannot hear it.

So the constraint has to live in the **protocol routing** — in which questions are asked at
all — rather than in the wording. That is the cheapest possible form of the "learned routing"
the research plan lists under Level 4, and it uses the engine's own answer with no training.

**What routing buys and what it costs.**

| | value |
|---|---|
| buys | a decision the flat question set provably cannot make (0.07 → 0.35 on `m_and_a` from the gate alone) |
| costs | a second forward pass when the gate does not resolve the case |
| costs | a protocol that is no longer a flat list of questions, so the harness and the terminal must understand stages |

The second cost is real and is why routing is opt-in per spec rather than universal. A spec
that routes reports which stage produced each answer, so the cost of a routed run is never
invisible.

**The rule this module will not break.** A routed answer is still the engine's answer, stored
in the same frozen `System1Record` shape, with the gate's output kept alongside it. Routing
changes *which questions are asked*, never *what the answers mean*. Anything else would be the
runtime inventing a decision, which is the one thing this architecture exists to prevent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from divya.protocol.loader import get_spec, load_protocol
from divya.protocol.schema import DecisionSpec
from divya.protocol.schema import Protocol as DecisionProtocol
from divya.runtime.loop import DivyaRuntime, LoopConfig
from divya.runtime.state import SharedState, System1Record
from divya.system1.laya_adapter import LayaSystem1, NullSystem1
from divya.system2.provider import HeuristicProvider

#: Gate -> the class it resolves to outright, and the classes left to a choice head.
#: A gate resolves a case only when it is decisive; anything it leaves open goes to `choice`.
DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    "transfers_a_business": {
        "spec": "event_triage",
        "when": True,
        "resolve_to": "m_and_a",
        "otherwise": {
            "choice_over": ["capital_action", "fundraise", "board_meeting", "other"],
        },
    },
}


@dataclass
class StageResult:
    """One forward pass: the questions asked and what came back."""

    name: str
    decisions: list[str]
    answers: dict[str, Any]
    record: System1Record | None
    ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name, "decisions": self.decisions, "ms": round(self.ms, 1),
            "answers": self.answers,
        }


@dataclass
class RoutedResult:
    """The whole routed decision, with the path that produced it."""

    answers: dict[str, Any]
    stages: list[StageResult] = field(default_factory=list)
    route_taken: list[str] = field(default_factory=list)
    resolved_by: dict[str, str] = field(default_factory=dict)
    total_ms: float = 0.0
    degraded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "answers": self.answers,
            "route_taken": self.route_taken,
            "resolved_by": self.resolved_by,
            "stages": [s.as_dict() for s in self.stages],
            "total_ms": round(self.total_ms, 1),
            "degraded": self.degraded,
        }


def _confidence(answers: dict[str, Any], name: str) -> float | None:
    a = answers.get(name)
    if not isinstance(a, dict):
        return None
    for k in ("noul", "confidence", "probability"):
        v = a.get(k)
        if isinstance(v, int | float):
            return float(v)
    return None


class RoutedDecider:
    """Runs a spec in stages, resolving what a gate resolves and asking about the rest."""

    def __init__(
        self,
        system1: Any | None = None,
        routes: dict[str, dict[str, Any]] | None = None,
        gate_confidence: float = 0.70,
        mode: str = "system1",
    ) -> None:
        self.system1 = system1 if system1 is not None else (
            LayaSystem1() if LayaSystem1().is_available() else NullSystem1()
        )
        self.routes = routes if routes is not None else dict(DEFAULT_ROUTES)
        # A gate must be confident to resolve a case. 0.70 sits above the 0.5-0.73 band where
        # Laya measured ECE 0.18, so a borderline gate escalates to the choice head rather
        # than silently deciding.
        self.gate_confidence = gate_confidence
        self.mode = mode
        self.protocol: DecisionProtocol | None = None
        try:
            self.protocol = load_protocol()
        except Exception:
            self.protocol = None

    def _ask(
        self,
        spec: DecisionSpec,
        names: list[str],
        state: SharedState,
    ) -> tuple[dict[str, Any], System1Record | None, float]:
        t0 = time.perf_counter()
        runtime = DivyaRuntime(
            protocol=self.protocol,
            system2=HeuristicProvider() if self.mode == "loop" else None,
            system1=self.system1,
            config=LoopConfig(system1_only=self.mode != "loop", max_turns=3),
        )
        obs = state.observation_text()
        import hashlib

        digest = hashlib.sha256(obs.encode("utf-8", "surrogatepass")).hexdigest()[:16]
        rec = self.system1.answer(
            obs, spec, only=names, turn_index=len(state.system1_records),
            protocol_version=self.protocol.protocol_version if self.protocol else "",
        )
        # A System1Record built outside the runtime does not know the state digest, and
        # provenance that is silently blank is worse than no provenance.
        if getattr(rec, "state_digest", "") != digest:
            rec = rec.model_copy(update={"state_digest": digest})
        return dict(rec.answers), rec, (time.perf_counter() - t0) * 1000

    def decide(self, text: str, *, extra: list[str] | None = None) -> RoutedResult:
        """Route the decision. Returns every stage, so the path is inspectable."""
        from divya.runtime.state import Observation, SharedState

        state = SharedState(
            protocol_version=self.protocol.protocol_version if self.protocol else "0",
            domain="corporate_actions",
            objective="Classify this filing.",
            observations=[Observation(kind="document", source_id="routed:1", content=text)],
        )
        out = RoutedResult(answers={})

        if self.protocol is None:
            out.degraded.append("protocol unavailable; nothing could be routed")
            return out
        if not self.system1.is_available():
            out.degraded.append("system1 unavailable; nothing could be routed")
            return out

        spec = get_spec(self.protocol, "event_triage")
        tail = list(extra or [])

        # Stage 1: the gate. Also the ordinary tier-1 decisions that every route needs.
        gate_name = next(iter(self.routes), None)
        stage1_names = [n for n in ([gate_name] if gate_name else []) + tail]
        if not stage1_names:
            stage1_names = tail
        answers, rec, ms = self._ask(spec, stage1_names, state)
        if rec is not None:
            state.system1_records.append(rec)
        out.stages.append(StageResult("gate", stage1_names, answers, rec, ms))
        out.answers.update(answers)
        out.total_ms += ms
        out.route_taken.append(f"gate:{','.join(stage1_names)}")

        # Resolve from the gate when it is decisive.
        # A confident gate resolves the case. A low-confidence one does not, because the
        # 0.5-0.73 band is exactly where Laya measured ECE 0.18 and a borderline gate must not
        # silently decide.
        resolved_value: str | None = None
        if gate_name and gate_name in answers:
            p = _confidence(answers, gate_name)
            if p is not None and p >= self.gate_confidence:
                resolved_value = self.routes.get(gate_name, {}).get("resolve_to")
        if resolved_value is not None and "event_type" not in out.answers:
            # The gate answered a question ABOUT the event, and a confident gate answers the
            # classification too. The engine's own answer is recorded verbatim, and the fact
            # that a gate resolved it rather than the choice head is recorded alongside --
            # because a reader must be able to tell which question produced the label.
            out.answers["event_type"] = {
                "type": "choice", "choice": resolved_value,
                "confidence": _confidence(answers, gate_name or ""), "probabilities": {},
                "resolved_by": f"gate:{gate_name}",
            }
            out.resolved_by["event_type"] = f"gate:{gate_name}"

        # Stage 2: whatever the gate did not resolve.
        remaining = [
            q.name
            for q in spec.questions
            if q.tier == 1 and q.name not in out.answers and q.name not in stage1_names
        ]
        if remaining:
            answers2, rec2, ms2 = self._ask(spec, remaining, state)
            if rec2 is not None:
                state.system1_records.append(rec2)
            out.stages.append(StageResult("remaining", remaining, answers2, rec2, ms2))
            out.answers.update(answers2)
            out.total_ms += ms2
            out.route_taken.append(f"remaining:{','.join(remaining)}")

        return out
