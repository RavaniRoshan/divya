"""The System-2 turn: the only thing the reasoning model is allowed to emit.

System-2 does not produce prose and does not produce the final decision. It produces a *turn*:
a typed instruction to the runtime about what to do next. Keeping this narrow is what makes the
loop auditable -- every sentence a user sees in a trace came from a field in this object, and
every decision in the shared state came from a turn that named it.

Three outcomes, no more:

* ``CALL_SYSTEM1`` -- ask System-1 for named decisions. The runtime executes them, writes the
  raw results to shared state, and calls back.
* ``FINISH``      -- the evidence is sufficient; state the conclusion and stop.
* ``ABSTAIN``     -- the evidence will not support a conclusion. This is a success, not a
  failure: a market terminal that abstains honestly is more useful than one that guesses.

An optional ``rationale`` is recorded for the trace. It is *not* a decision and is never read
back into the pipeline -- treating a model's self-explanation as evidence is how confident
nonsense gets into a system.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TurnKind(str, Enum):
    CALL_SYSTEM1 = "call_system1"
    FINISH = "finish"
    ABSTAIN = "abstain"


class System2Turn(BaseModel):
    """One step of System-2 output."""

    model_config = ConfigDict(extra="forbid")

    kind: TurnKind
    rationale: str = Field(
        default="",
        description="Human-readable reasoning note for the trace. Never used as evidence.",
    )

    # --- call_system1 -----------------------------------------------------
    decisions: list[str] = Field(
        default_factory=list,
        description="Decision names to request. Must exist in the protocol.",
    )

    # --- finish / abstain -------------------------------------------------
    conclusion: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def needs_system1(self) -> bool:
        return self.kind is TurnKind.CALL_SYSTEM1

    def summary(self) -> str:
        """One line for a trace log."""
        if self.kind is TurnKind.CALL_SYSTEM1:
            return f"call_system1({', '.join(self.decisions) or '<empty>'})"
        return f"{self.kind.value}(confidence={self.confidence:.2f})"


class System2Request(BaseModel):
    """What gets handed to the System-2 model.

    Serialized to JSON. The state is included structurally rather than flattened into prose
    because the shared state already has a schema, and inventing a second text format for it
    would create a translation layer that can lose information silently.
    """

    model_config = ConfigDict(extra="forbid")

    task: str
    protocol_version: str
    available_decisions: list[dict[str, Any]]
    state: dict[str, Any]
    turn_index: int
    max_turns: int
    min_confidence: float

    def to_prompt_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


#: JSON Schema handed to the model provider for constrained decoding. Ollama's `format`
#: field accepts a JSON Schema object, which makes the grammar the model's constraint rather
#: than a post-hoc parse of whatever it felt like emitting.
SYSTEM2_TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "enum": [k.value for k in TurnKind]},
        "rationale": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "conclusion": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}


SYSTEM2_INSTRUCTIONS = """\
You are the System-2 reasoning component of Divya, a market-intelligence terminal for Indian \
equities. You do not decide anything yourself. You direct a System-1 decision engine.

You will receive a JSON task, the decisions available, and the shared state so far. Reply \
with ONE JSON object and nothing else.

Choose exactly one `kind`:

- "call_system1": you need more evidence from System-1. List the decision names you need in
  `decisions`. Ask for the smallest number of decisions that would move you forward. Do not \
  request decisions whose answers you already have.
- "finish": the evidence is sufficient. Set `conclusion` to your conclusion in one or two
  sentences and `confidence` between 0 and 1.
- "abstain": the evidence will not support a reliable conclusion, or the document does not \
  concern a corporate event. Set `conclusion` to the reason and `confidence` to 0.

Rules:
- Never invent a decision name. Only use names from `available_decisions`.
- Never state a System-1 answer in your own words as if it were your judgement. If you
  disagree with a System-1 result, say so in `rationale` and lower your `confidence`; the
  raw System-1 output stays authoritative in the record.
- `rationale` is for a human reading the trace. Keep it under 40 words. It is not evidence.
- Be willing to abstain. An honest abstention is a correct outcome.
"""


def build_messages(request: System2Request) -> list[dict[str, str]]:
    """Assemble the chat messages for a System-2 call."""
    import json

    return [
        {"role": "system", "content": SYSTEM2_INSTRUCTIONS},
        {"role": "user", "content": json.dumps(request.to_prompt_payload(), ensure_ascii=False)},
    ]


LiteralKind = Literal["call_system1", "finish", "abstain"]
