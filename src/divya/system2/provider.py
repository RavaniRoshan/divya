"""System-2 provider interface.

System-2 is pluggable. Nothing in the runtime names a model; the runtime asks a provider for a
:class:`~divya.system2.turn.System2Turn` and does not know or care what produced it.

Three implementations ship:

* :class:`OllamaProvider` -- a local Ollama server. The default for self-hosting.
* :class:`OpenAICompatProvider` -- anything speaking the OpenAI chat-completions API
  (llama.cpp's ``--server``, vLLM, LM Studio, TGI).
* :class:`HeuristicProvider` -- no model at all. A deterministic rule-based policy.

The heuristic exists for two legitimate reasons and one illegitimate one. Legitimate: it lets
the runtime, protocol, and eval harness be tested in CI on a box with no LLM resident, and it
gives the system something to fall back to when the reasoning model is unreachable, which is
an explicit requirement. Illegitimate: pretending it is a model. It is therefore named
``heuristic``, it stamps ``is_model=False`` on every result, and the evaluation harness reports
its numbers in a block that cannot be confused with model output.

The interface is async because the runtime may want to issue several System-2 calls
concurrently against independent events, and because a slow local model must not block the
event loop. Callers that want sequential behaviour simply await.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from divya.system2.turn import (
    SYSTEM2_TURN_SCHEMA,
    System2Request,
    System2Turn,
    TurnKind,
    build_messages,
)

log = logging.getLogger(__name__)


class System2Error(RuntimeError):
    """System-2 could not produce a valid turn. Always recoverable by the runtime."""


@dataclass(frozen=True)
class ProviderInfo:
    """Identity of the provider behind a call, recorded in every trace.

    ``is_model=False`` is load-bearing. An evaluation result that does not say whether a number
    came from a model or from a rule is not a result.
    """

    name: str
    model: str | None
    is_model: bool


@dataclass
class System2Result:
    turn: System2Turn
    info: ProviderInfo
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_response: str = ""
    repaired: bool = False
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class System2Provider(Protocol):
    """What the runtime needs from a reasoning model."""

    info: ProviderInfo

    async def complete(self, request: System2Request, *, timeout: float) -> System2Result:
        """Produce one turn. Must raise :class:`System2Error` rather than returning junk."""
        ...


def _parse_turn(text: str) -> tuple[System2Turn, bool]:
    """Parse a model response into a turn.

    Returns ``(turn, repaired)``. Two repairs are attempted, in order, because a local model
    failing to produce one valid JSON object is common and is not a reason to lose the whole
    step:

    1. strip markdown fences and any prose around the JSON object;
    2. if the object parses but violates the schema, coerce it (``kind`` case, missing
       confidence defaulted to 0, unknown fields dropped).

    If both fail, :class:`System2Error` is raised -- the runtime then decides whether to retry,
    abstain, or fall back. It never guesses a turn.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()

    try:
        return System2Turn.model_validate_json(candidate), False
    except (ValidationError, ValueError):
        pass

    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise System2Error(f"no JSON object in System-2 response: {text[:200]!r}")
    try:
        raw = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise System2Error(f"System-2 response is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise System2Error(f"System-2 response is a {type(raw).__name__}, expected an object")

    coerced = dict(raw)
    kind = coerced.get("kind")
    if isinstance(kind, str):
        coerced["kind"] = kind.strip().lower().replace("-", "_")
    coerced.pop("additionalProperties", None)
    try:
        return System2Turn.model_validate(coerced), True
    except ValidationError as exc:
        raise System2Error(f"System-2 response failed schema validation: {exc}") from exc


class OllamaProvider:
    """Local Ollama server.

    Passes the turn schema to Ollama's ``format`` field so decoding is grammar-constrained.
    That matters more than it might seem: a 4B model asked for bare JSON will occasionally
    emit prose around it, and post-hoc repair of that is a source of silent corruption.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
        keep_alive: str = "5m",
        extra_options: dict[str, Any] | None = None,
    ) -> None:
        self.info = ProviderInfo(name="ollama", model=model, is_model=True)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive
        self.extra_options = extra_options or {}

    async def complete(self, request: System2Request, *, timeout: float | None = None) -> System2Result:
        import time

        payload: dict[str, Any] = {
            "model": self.info.model,
            "messages": build_messages(request),
            "stream": False,
            "format": SYSTEM2_TURN_SCHEMA,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0.0,
                "num_ctx": 8192,
                **self.extra_options,
            },
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise System2Error(f"ollama unreachable or errored: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000

        text = body.get("message", {}).get("content", "")
        turn, repaired = _parse_turn(text)
        return System2Result(
            turn=turn,
            info=self.info,
            latency_ms=latency_ms,
            prompt_tokens=int(body.get("prompt_eval_count", 0) or 0),
            completion_tokens=int(body.get("eval_count", 0) or 0),
            raw_response=text,
            repaired=repaired,
        )


class OpenAICompatProvider:
    """Any OpenAI chat-completions endpoint.

    Used when the local model is served by llama.cpp, vLLM, or similar instead of Ollama.
    Schema-constrained decoding is not available through the portable chat API, so this
    provider relies on :func:`_parse_turn` repair and reports ``repaired`` honestly in the trace
    -- a high repair rate on this provider is itself a finding about the model.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.info = ProviderInfo(name="openai_compatible", model=model, is_model=True)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.response_format = response_format
        self.extra_body = extra_body or {}

    async def complete(self, request: System2Request, *, timeout: float | None = None) -> System2Result:
        import time

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.info.model,
            "messages": build_messages(request),
            "temperature": 0.0,
            **self.extra_body,
        }
        if self.response_format:
            payload["response_format"] = self.response_format

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                resp = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise System2Error(f"openai-compatible endpoint unreachable: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000

        text = body["choices"][0]["message"]["content"]
        turn, repaired = _parse_turn(text)
        usage = body.get("usage", {}) or {}
        return System2Result(
            turn=turn,
            info=self.info,
            latency_ms=latency_ms,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw_response=text,
            repaired=repaired,
        )


class HeuristicProvider:
    """No model. A deterministic policy over the shared state.

    This is not a stand-in for System-2 and is never reported as one. It exists so the runtime
    has a defined behaviour when no reasoning model is available, and so tests can assert on
    loop mechanics without a 2 GB model in the way.

    The policy is intentionally simple and inspectable: request the tier-1 decisions, then
    finish if System-1's own confidence cleared the threshold, otherwise abstain. That is a
    reasonable if crude strategy, and measuring how far it gets from the real model is a
    legitimate ablation.
    """

    #: Decisions requested on the first turn, then the escalation set.
    PRIMARY: tuple[str, ...] = ("event_type", "is_material", "materiality", "direction")
    ESCALATION: tuple[str, ...] = ("evidence_sufficiency", "is_summary_only")

    def __init__(
        self,
        primary: tuple[str, ...] | None = None,
        escalation: tuple[str, ...] | None = None,
        min_confidence: float = 0.55,
    ) -> None:
        self.info = ProviderInfo(name="heuristic", model=None, is_model=False)
        self.primary = tuple(primary) if primary is not None else self.PRIMARY
        self.escalation = tuple(escalation) if escalation is not None else self.ESCALATION
        self.min_confidence = min_confidence

    async def complete(self, request: System2Request, *, timeout: float | None = None) -> System2Result:
        import time

        started = time.perf_counter()
        available = {d["name"] for d in request.available_decisions}
        state = request.state
        asked = set(state.get("requested_decisions", []))
        system1 = state.get("system1_results", {})

        if request.turn_index == 0:
            wanted = [d for d in self.primary if d in available and d not in asked]
            turn = System2Turn(
                kind=TurnKind.CALL_SYSTEM1,
                decisions=wanted,
                rationale="Initial pass: request tier-1 decisions for this event.",
            )
        elif self.escalation and not any(d in system1 for d in self.escalation):
            wanted = [d for d in self.escalation if d in available and d not in asked]
            turn = System2Turn(
                kind=TurnKind.CALL_SYSTEM1,
                decisions=wanted,
                rationale="Tier-1 complete; request evidence-quality decisions to test sufficiency.",
            )
        else:
            best = max(
                (_confidence_of(r) for r in system1.values()),
                default=0.0,
            )
            if best >= self.min_confidence:
                turn = System2Turn(
                    kind=TurnKind.FINISH,
                    conclusion=_conclusion_from(system1),
                    confidence=best,
                    rationale="System-1 confidence cleared the threshold.",
                )
            else:
                turn = System2Turn(
                    kind=TurnKind.ABSTAIN,
                    conclusion="No System-1 decision cleared the confidence threshold.",
                    confidence=0.0,
                    rationale="Max System-1 confidence was below the configured minimum.",
                )

        return System2Result(
            turn=turn,
            info=self.info,
            latency_ms=(time.perf_counter() - started) * 1000,
            raw_response="<heuristic: no model was called>",
        )


def _confidence_of(result: dict[str, Any]) -> float:
    """Pull a usable confidence out of a raw System-1 answer, defaulting to 0.

    Missing confidence must read as zero, not as one. A decision whose confidence we cannot
    read has not demonstrated that it clears the bar, and defaulting upward would turn an
    instrumentation gap into a false positive.
    """
    for key in ("probability", "confidence", "score"):
        v = result.get(key)
        if isinstance(v, int | float):
            return float(v)
    return 0.0


def _conclusion_from(system1: dict[str, Any]) -> str:
    parts: list[str] = []
    if choice := (system1.get("event_type") or {}).get("choice"):
        parts.append(f"event type: {choice}")
    if isinstance((mat := system1.get("is_material") or {}).get("probability"), int | float):
        parts.append(f"material: P={mat['probability']:.2f}")
    return "; ".join(parts) or "no System-1 decision available"


def build_provider(kind: str | None = None, **kwargs: Any) -> System2Provider:
    """Construct a provider from ``DIVYA_S2_PROVIDER``.

    Defaults to Ollama on localhost with ``qwen3:4b``, which is the configuration verified on
    this machine. The model name is a default, not a hardcoding: it is overridable by env var
    and the runtime never reads it directly.
    """
    import os

    kind = (kind or os.environ.get("DIVYA_S2_PROVIDER") or "ollama").strip().lower()
    # Default model is 3b, not 4b, and that is a measurement rather than a preference.
    # Warm end-to-end latency on the 16 vCPU / 7.5 GiB target box, with Laya resident
    # (2.8 GB RSS): qwen2.5-coder:3b 0.56-0.91 s, qwen3:4b 42-64 s. The 4B model's own
    # generation time is only 1.3-2.2 s; the rest is memory thrashing. At 4B the recurrent
    # loop is unusable, which would make any arm-D latency figure meaningless.
    match kind:
        case "ollama":
            return OllamaProvider(
                model=kwargs.get("model") or os.environ.get("DIVYA_S2_MODEL") or "qwen2.5-coder:3b",
                base_url=kwargs.get("base_url")
                or os.environ.get("DIVYA_S2_BASE_URL")
                or "http://localhost:11434",
            )
        case "openai_compatible" | "openai":
            base = kwargs.get("base_url") or os.environ.get("DIVYA_S2_BASE_URL")
            if not base:
                raise ValueError("openai_compatible provider requires DIVYA_S2_BASE_URL")
            return OpenAICompatProvider(
                model=kwargs.get("model") or os.environ.get("DIVYA_S2_MODEL") or "local",
                base_url=base,
                api_key=os.environ.get("DIVYA_S2_API_KEY"),
            )
        case "heuristic":
            return HeuristicProvider()
        case _:
            raise ValueError(f"unknown DIVYA_S2_PROVIDER {kind!r}; expected ollama, openai_compatible, or heuristic")
