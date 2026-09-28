"""Decision protocol schema.

A *decision definition* is a versioned, reviewable artifact describing one System-1 decision:
its name, why it exists, what it may choose between, what evidence it needs, and how confident
it is expected to be.

These are not prompts. They are the contract between the System-2 layer, the System-1 engine,
and anyone auditing a decision months later. The option set of a `choice` decision *is* the
decision problem -- adding an option changes what the engine is being asked -- so it lives in a
versioned file rather than in prompt text or Python string literals.

Laya's own constraints (verified from `laya/common.py` in the 0.3.21 wheel) are encoded here so
an invalid definition fails at load time rather than at inference time:

  * only `choice`, `score`, `noul` exist -- `DecisionType` will not accept anything else;
  * `choice` takes a mapping of label -> description;
  * `score` takes an ordered sequence of level descriptions;
  * `noul` is binary and, if `labels` is given, must map exactly {"false", "true"} to two
    distinct non-empty strings.

The last one is the easiest to get wrong by hand, so it is validated here even though Laya
validates it again on its side.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROTOCOL_VERSION = "0.1.0"


class DecisionType(str, Enum):
    """The three primitives System-1 can answer. Mirrors ``laya.common.QTYPES``."""

    CHOICE = "choice"
    SCORE = "score"
    NOUL = "noul"


class Question(BaseModel):
    """A single decision, in Laya's wire format plus the metadata Divya needs.

    The `type`/`instructions`/`criteria` triple is exactly what ``Router.predict`` consumes.
    Everything else is Divya's own audit and evaluation metadata and is ignored by Laya.

    `tier` encodes *when* the System-2 layer is allowed to ask for this question. Tier 1
    decisions are the ones a single-shot pass should be able to answer, so they are the only
    ones a System-2 -> Laya baseline (arm C) requests. Higher tiers exist to be requested
    selectively when tier-1 output says the evidence is thin. This is the mechanism that makes
    "call System-1 more" and "call System-1 more *usefully*" distinguishable, and it is the
    concrete form hypothesis H4 takes in the evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    type: DecisionType
    instructions: str = Field(min_length=1)
    criteria: dict[str, str] | list[str] | None = None
    labels: dict[str, str] | None = None
    tier: int = Field(default=1, ge=1)
    purpose: str = ""
    required_evidence: list[str] = Field(default_factory=list)
    calibration_expectation: str = ""
    known_failure_modes: list[str] = Field(default_factory=list)
    downstream_consumers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_type_shape(self) -> Question:
        if self.type is DecisionType.CHOICE:
            if not isinstance(self.criteria, dict) or not self.criteria:
                raise ValueError(
                    f"choice {self.name!r} needs a non-empty mapping of label -> description"
                )
            if self.labels is not None:
                raise ValueError(f"'labels' is only valid on noul questions (got {self.name!r})")
        elif self.type is DecisionType.SCORE:
            if not isinstance(self.criteria, list) or len(self.criteria) < 2:
                raise ValueError(
                    f"score {self.name!r} needs an ordered list of at least 2 level descriptions"
                )
            if self.labels is not None:
                raise ValueError(f"'labels' is only valid on noul questions (got {self.name!r})")
        else:  # noul
            if self.labels is not None:
                if set(self.labels) != {"false", "true"}:
                    raise ValueError(
                        f"noul {self.name!r} labels must map exactly 'false' and 'true'"
                    )
                values = [self.labels["false"].strip(), self.labels["true"].strip()]
                if not all(values):
                    raise ValueError(f"noul {self.name!r} labels must be non-empty")
                if values[0] == values[1]:
                    raise ValueError(f"noul {self.name!r} labels must be distinct")
            if self.criteria is not None and not isinstance(self.criteria, dict):
                raise ValueError(f"noul {self.name!r} criteria must be a mapping when present")
        return self

    def to_laya(self) -> dict[str, object]:
        """Render this definition into the dict shape ``Router.predict`` expects.

        Only ``type``, ``instructions``, ``criteria`` and ``labels`` are passed through. The
        Divya-only fields are deliberately dropped so the engine cannot be influenced by audit
        metadata, and so the request logged is byte-identical to the request sent.
        """
        payload: dict[str, object] = {
            "type": self.type.value,
            "instructions": self.instructions,
        }
        if self.criteria is not None:
            payload["criteria"] = self.criteria
        if self.labels is not None:
            payload["labels"] = self.labels
        return payload

    @property
    def option_count(self) -> int:
        if self.type is DecisionType.CHOICE:
            return len(self.criteria or {})
        if self.type is DecisionType.SCORE:
            return len(self.criteria or [])
        return 2


class DecisionSpec(BaseModel):
    """A named, versioned group of questions evaluated together as one System-1 call."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    purpose: str = ""
    version: int = Field(ge=1)
    checkpoint: str | None = None
    max_len: int | None = None
    evaluation_dataset: str | None = None
    questions: list[Question] = Field(min_length=1)

    @field_validator("questions")
    @classmethod
    def _unique_names(cls, qs: list[Question]) -> list[Question]:
        names = [q.name for q in qs]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate question names: {sorted(dupes)}")
        return qs

    def by_name(self, name: str) -> Question:
        for q in self.questions:
            if q.name == name:
                return q
        raise KeyError(f"{self.name} has no question {name!r}")

    def to_laya(self, only: list[str] | None = None) -> dict[str, object]:
        """Build the ``questions`` argument for ``Router.predict``.

        ``only`` restricts the call to a named subset. This is the mechanism behind selective
        System-1 invocation -- arm D of the evaluation can ask for one question rather than the
        whole set, and the trace records exactly which subset was requested.
        """
        selected = self.questions if only is None else [self.by_name(n) for n in only]
        return {q.name: q.to_laya() for q in selected}


class Protocol(BaseModel):
    """The whole decision protocol: a set of specs pinned to a protocol version."""

    model_config = ConfigDict(extra="forbid")

    protocol_version: str
    specs: list[DecisionSpec] = Field(min_length=1)

    def by_name(self, name: str) -> DecisionSpec:
        for s in self.specs:
            if s.name == name:
                return s
        raise KeyError(f"no decision spec named {name!r}")

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.specs]
