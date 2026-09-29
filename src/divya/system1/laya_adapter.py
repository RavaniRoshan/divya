"""The System-1 adapter: the only place in Divya that imports ``laya``.

Two reasons this boundary exists. First, ``import laya`` pulls in torch and transformers, which
is several hundred megabytes and seconds of startup -- the protocol, runtime, and evaluation
harness must be importable and testable on a machine with no checkpoint. Second, and more
importantly, the adapter is where "raw engine output" is defined. Everything downstream treats
this module's return value as authoritative and uninterpreted; if interpretation were allowed to
leak in here, the immutability guarantee in ``runtime.state`` would be decorative.

The adapter is also the single failure boundary for System-1. Timeouts, missing checkpoints,
malformed responses, and engine errors are all normalised into :class:`System1Error` so the
runtime has exactly one thing to catch and one degradation path to implement.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from divya.protocol.schema import DecisionSpec
from divya.runtime.state import System1Record

log = logging.getLogger(__name__)


class System1Error(RuntimeError):
    """System-1 could not be reached or did not return a usable answer."""


class System1Unavailable(System1Error):
    """System-1 is not installed or no checkpoint is resident.

    Distinguished from a generic error because this is the case where the runtime's documented
    degradation path applies: continue with System-2 alone and mark the run as degraded, rather
    than failing the task.
    """


@dataclass(frozen=True)
class System1Answer:
    """One engine response, with the raw payload kept intact."""

    answers: dict[str, Any]
    raw: dict[str, Any]
    checkpoint: str | None
    latency_ms: float

    def confidence(self, decision: str) -> float:
        ans = self.answers.get(decision)
        if not isinstance(ans, dict):
            return 0.0
        for key in ("probability", "confidence", "score"):
            v = ans.get(key)
            if isinstance(v, int | float):
                return float(v)
        return 0.0


#: The fine-tuned System-1, when it is present.
#:
#: This is the default, and it is a different model from the one Laya ships. Fine-tuned on 4,692
#: real NSE announcements labelled with the exchange's own `desc` taxonomy, it scores **0.975
#: accuracy on 120 held-out announcements** against **0.433 zero-shot** (DECISIONS D-029). The
#: base checkpoint is kept as an explicit fallback, never as a silent default, because "the
#: engine is 54 points worse than it could be" is not something to discover at runtime.
DEFAULT_FINETUNED = Path("data/finetune/laya-indian-filings")


def resolve_checkpoint() -> str | None:
    """Path to the fine-tuned checkpoint, or None if it has not been trained yet.

    A complete checkpoint is one with weights, a config, a tokenizer AND an encoder -- all four,
    because loading a partial one fails deep inside the model rather than at the boundary.
    """
    if not DEFAULT_FINETUNED.is_dir():
        return None
    needed = ("model.safetensors", "rl_agent_config.json", "tokenizer", "encoder")
    if not all((DEFAULT_FINETUNED / n).exists() for n in needed):
        return None
    if (DEFAULT_FINETUNED / "model.safetensors").stat().st_size == 0:
        return None  # a truncated download is worse than no download
    return str(DEFAULT_FINETUNED)


class LayaSystem1:
    """Thin, synchronous adapter over ``laya.Router``.

    Constructing this class does not load anything; the engine loads on first ``answer`` call
    and is cached, because checkpoint load is the single most expensive thing this system does.

    Defaults to the **fine-tuned** checkpoint when one has been trained, and to Laya's base
    checkpoint otherwise. Which one is in use is reported by ``divya status`` and recorded on
    every decision, because a 0.975 engine and a 0.433 engine must never be indistinguishable.
    """

    def __init__(
        self,
        model: str | None = None,
        max_len: int | None = None,
        min_confidence: float | None = None,
        allow_download: bool = True,
    ) -> None:
        self.model = model or resolve_checkpoint()
        self.is_finetuned = self.model is not None
        self.max_len = max_len
        self.min_confidence = min_confidence
        self.allow_download = allow_download
        self._router: Any = None
        self._loaded_at: float | None = None

    # -- lifecycle ---------------------------------------------------------

    def is_available(self) -> bool:
        """True if the engine can be imported. Does not load a checkpoint."""
        try:
            import laya  # noqa: F401
        except Exception:
            return False
        return True

    def describe(self) -> dict[str, Any]:
        """Which engine this is, and what it scores.

        Recorded on every run, because the fine-tuned and base checkpoints differ by 54 points
        of accuracy (DECISIONS D-029) and a reader of a trace has to be able to tell them apart.
        """
        return {
            "engine": "laya",
            "checkpoint": self.model or "convaiinnovations/laya (base, zero-shot)",
            "finetuned": self.is_finetuned,
            "note": (
                "fine-tuned on 4,692 NSE announcements; 0.975 accuracy on 120 held-out"
                if self.is_finetuned
                else "BASE zero-shot checkpoint: 0.433 accuracy on the same 120. Fine-tuning "
                     "is available and changes this by 54 points (docs/loop/DECISIONS.md D-029)."
            ),
        }

    def load(self) -> Any:
        if self._router is not None:
            return self._router
        try:
            from laya import Router
        except Exception as exc:
            raise System1Unavailable(f"laya is not importable: {exc}") from exc
        try:
            self._router = Router()
            self._loaded_at = time.perf_counter()
        except Exception as exc:
            raise System1Unavailable(f"could not initialise laya Router: {exc}") from exc
        return self._router

    @property
    def load_seconds(self) -> float | None:
        return None if self._loaded_at is None else round(self._loaded_at, 3)

    # -- inference ---------------------------------------------------------

    def answer(
        self,
        state_text: str,
        spec: DecisionSpec,
        *,
        only: list[str] | None = None,
        turn_index: int = 0,
        protocol_version: str = "",
        timeout_note: str = "",
    ) -> System1Record:
        """Run one System-1 call and return a complete, immutable record.

        Every failure path returns a record with ``error`` set rather than raising, because a
        failed decision is something the terminal must display, not something to lose. The
        caller decides whether to retry, degrade, or abstain; this layer only reports.
        """
        questions = spec.to_laya(only=only)
        digest = hashlib.sha256(state_text.encode("utf-8")).hexdigest()[:16]
        names = sorted(questions)
        request_record = {
            "spec": spec.name,
            "spec_version": spec.version,
            "questions": questions,
            "state_digest": digest,
            "state_chars": len(state_text),
        }

        started = time.perf_counter()
        try:
            router = self.load()
        except System1Unavailable as exc:
            return System1Record(
                turn_index=turn_index,
                decision_names=names,
                spec_name=spec.name,
                spec_version=spec.version,
                protocol_version=protocol_version,
                state_digest=digest,
                request=request_record,
                raw_response={},
                answers={},
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )

        kwargs: dict[str, Any] = {}
        if self.model:
            kwargs["model"] = self.model
        elif spec.checkpoint:
            kwargs["model"] = spec.checkpoint
        if self.max_len or spec.max_len:
            kwargs["max_len"] = self.max_len or spec.max_len
        if self.min_confidence is not None:
            kwargs["min_confidence"] = self.min_confidence

        try:
            raw = router.predict(state_text, questions, **kwargs)
        except Exception as exc:
            log.warning("system1 predict failed: %s", exc)
            return System1Record(
                turn_index=turn_index,
                decision_names=names,
                spec_name=spec.name,
                spec_version=spec.version,
                protocol_version=protocol_version,
                state_digest=digest,
                request=request_record,
                raw_response={},
                answers={},
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = (time.perf_counter() - started) * 1000
        answers = raw.get("answers") or {}
        checkpoint = (raw.get("routing") or {}).get("model")

        # The engine returned, but did it answer everything we asked? A silently short answer
        # is the failure mode most likely to be mistaken for a real "no" downstream.
        missing = [n for n in names if n not in answers]
        error = f"missing answers for {missing}" if missing else (timeout_note or None)

        return System1Record(
            turn_index=turn_index,
            decision_names=names,
            spec_name=spec.name,
            spec_version=spec.version,
            protocol_version=protocol_version,
            state_digest=digest,
            request=request_record,
            raw_response=raw,
            answers=answers,
            checkpoint=checkpoint,
            latency_ms=latency_ms,
            error=error,
        )


class NullSystem1:
    """Stand-in used when no engine is available.

    Not a mock: this is the documented degradation path. It returns records that carry a
    ``degraded`` error string naming the real cause, so the difference between "System-1 said
    no" and "System-1 was not there" is always visible in the trace and in the terminal.
    """

    reason = "System-1 unavailable: laya is not installed in this environment"

    def is_available(self) -> bool:
        return False

    def load_seconds(self) -> None:
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "engine": "unavailable",
            "checkpoint": None,
            "finetuned": False,
            "note": "laya is not installed; no typed decisions can be produced",
        }

    def answer(
        self,
        state_text: str,
        spec: DecisionSpec,
        *,
        only: list[str] | None = None,
        turn_index: int = 0,
        protocol_version: str = "",
        timeout_note: str = "",
    ) -> System1Record:
        import hashlib

        questions = spec.to_laya(only=only)
        return System1Record(
            turn_index=turn_index,
            decision_names=sorted(questions),
            spec_name=spec.name,
            spec_version=spec.version,
            protocol_version=protocol_version,
            state_digest=hashlib.sha256(state_text.encode("utf-8")).hexdigest()[:16],
            request={"spec": spec.name, "spec_version": spec.version, "questions": questions},
            raw_response={},
            answers={},
            latency_ms=0.0,
            error=self.reason,
        )
