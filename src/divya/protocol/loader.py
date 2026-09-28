"""Loading and migration of the decision protocol.

`models/questions.yaml` is the single source of truth for what System-1 is allowed to decide.
It is loaded, validated against the pydantic schema, and rendered into Laya's request format.

Migration is explicit rather than automatic. A spec's ``version`` is an integer and changing it
is the act of declaring "the decision problem changed". :func:`check_migration` compares two
loaded protocols and reports what moved, so a version bump cannot silently change the meaning
of a stored decision.

Nothing here imports torch or laya. The protocol must be loadable and testable on a machine
with no checkpoint installed -- that is what lets the runtime, the eval harness, and CI run
without the System-1 weights present.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import yaml

from divya.protocol.schema import DecisionSpec, Protocol, Question

DEFAULT_PROTOCOL_PATH = Path("models/questions.yaml")


class ProtocolError(ValueError):
    """Raised when a protocol file is unreadable, malformed, or internally inconsistent."""


def _repo_root() -> Path:
    """Walk up from this file to the directory containing ``models/``.

    Walking up rather than using a fixed depth keeps the loader working from a source checkout,
    an installed package, or an unusual cwd.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "models" / "questions.yaml").exists():
            return parent
    # Fall back to cwd so an explicit --protocol path still works from anywhere.
    return Path.cwd()


def default_protocol_path() -> Path:
    """Resolve the protocol path, honouring ``DIVYA_PROTOCOL_PATH``."""
    env = os.environ.get("DIVYA_PROTOCOL_PATH")
    return Path(env) if env else _repo_root() / DEFAULT_PROTOCOL_PATH


def load_protocol(path: str | Path | None = None) -> Protocol:
    """Read and validate the decision protocol.

    Raises :class:`ProtocolError` on anything malformed, with the offending location named, so a
    bad edit fails with a message a human can act on rather than a stack trace inside Laya.
    """
    p = Path(path) if path is not None else default_protocol_path()
    if not p.exists():
        raise ProtocolError(
            f"decision protocol not found at {p}. Set DIVYA_PROTOCOL_PATH or create models/questions.yaml."
        )
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProtocolError(f"{p}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProtocolError(f"{p}: top level must be a mapping, got {type(raw).__name__}")
    if "protocol_version" not in raw:
        raise ProtocolError(f"{p}: missing 'protocol_version'")
    if "specs" not in raw:
        raise ProtocolError(f"{p}: missing 'specs'")

    try:
        protocol = Protocol.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError and anything it wraps
        raise ProtocolError(f"{p}: {exc}") from exc

    _check_cross_spec_constraints(protocol, p)
    _check_calibration_buckets(protocol, p)
    return protocol


def _check_cross_spec_constraints(protocol: Protocol, source: Path) -> None:
    """Checks that span specs and that a per-question validator cannot see.

    The option-count bound is here because it is a property of the *engine*, not of a single
    question: Laya's published material reports degradation when a choice question carries many
    options at the default head budget. We cap it at load time so a runaway option set is caught
    before it reaches inference, and so the cap is visible in one place.
    """
    names = protocol.names
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ProtocolError(f"{source}: duplicate spec names: {sorted(dupes)}")

    for spec in protocol.specs:
        for q in spec.questions:
            if q.type.value == "choice" and q.option_count > MAX_CHOICE_OPTIONS:
                raise ProtocolError(
                    f"{source}: spec {spec.name!r} question {q.name!r} has {q.option_count} options, "
                    f"above the protocol cap of {MAX_CHOICE_OPTIONS}. Laya's default head budget "
                    f"degrades past this; split the question or raise the cap deliberately."
                )


MAX_CHOICE_OPTIONS = 20

#: Laya fits a separate calibration temperature per (question type, option-count) bucket, and
#: the mapping is fixed in `laya.common.temp_bucket`:
#:
#:     k <= 2 -> "2"   k <= 5 -> "3-5"   k <= 10 -> "6-10"   else -> "11+"
#:
#: Measured from the shipped `convaiinnovations/laya` checkpoint's `rl_agent_config.json` on
#: 2026-09-28, only the `choice:11+` bucket is unfit: its temperature is 0.1006, which
#: *sharpens* logits roughly tenfold, so a genuine 0.24 top probability is published as 0.99.
#: Laya refuses to apply it, clamps to 0.5, and warns that "confidence from the affected
#: entries is uncalibrated" (`laya/agent.py:485`). Every other bucket is valid:
#: choice:2 = 1.9064, choice:3-5 = 1.7602, choice:6-10 = 1.0, noul:2 = 1.9834, score:3-5 = 1.2514.
#:
#: So a `choice` question with more than ten options produces confidences the engine itself
#: disclaims. Reporting an ECE computed from those numbers would be reporting a number the
#: library has already told us not to trust, so this is a load-time error rather than a warning.
#: The fix is fewer options, not a different threshold.
UNCALIBRATED_CHOICE_BUCKETS: set[str] = {"choice:11+"}
MAX_CALIBRATED_CHOICE_OPTIONS = 10


def laya_option_bucket(qtype: str, k: int) -> str:
    """Reproduce ``laya.common.temp_bucket`` so the protocol can check its own calibratability."""
    size = "2" if k <= 2 else "3-5" if k <= 5 else "6-10" if k <= 10 else "11+"
    return f"{qtype}:{size}"


def _check_calibration_buckets(protocol: Protocol, source: Path) -> None:
    """Fail at load time if any question lands in a bucket the engine disclaims.

    A protocol that produces disclaimed confidence is not a working protocol. Catching it here
    turns a subtle, downstream, hard-to-attribute measurement error into a one-line error
    pointing at the question that caused it.
    """
    offenders: list[str] = []
    for spec in protocol.specs:
        for q in spec.questions:
            if q.type.value != "choice":
                continue
            bucket = laya_option_bucket("choice", q.option_count)
            if bucket in UNCALIBRATED_CHOICE_BUCKETS:
                offenders.append(
                    f"spec {spec.name!r} question {q.name!r} has {q.option_count} options, which "
                    f"lands in the {bucket} bucket where the shipped checkpoint's calibration "
                    f"temperature is invalid. Laya clamps it and states the resulting confidence "
                    f"is uncalibrated. Reduce to {MAX_CALIBRATED_CHOICE_OPTIONS} options or fewer."
                )
    if offenders:
        raise ProtocolError(f"{source}: uncalibrated decision questions:\n  - " + "\n  - ".join(offenders))


def iter_questions(protocol: Protocol) -> Iterator[tuple[DecisionSpec, Question]]:
    for spec in protocol.specs:
        for q in spec.questions:
            yield spec, q


def get_spec(protocol: Protocol, name: str) -> DecisionSpec:
    try:
        return protocol.by_name(name)
    except KeyError as exc:
        available = ", ".join(protocol.names)
        raise ProtocolError(f"unknown decision spec {name!r}. Available: {available}") from exc


def change_log(old: DecisionSpec, new: DecisionSpec) -> list[str]:
    """Human-readable diff between two versions of one spec.

    Used by the migration check and by ``divya protocol diff`` so a version bump has a
    reviewable description rather than being a bare integer change in a diff.
    """
    changes: list[str] = []
    if old.version != new.version:
        changes.append(f"version {old.version} -> {new.version}")
    if old.purpose != new.purpose:
        changes.append("purpose changed")
    if old.checkpoint != new.checkpoint:
        changes.append(f"checkpoint {old.checkpoint} -> {new.checkpoint}")
    if old.max_len != new.max_len:
        changes.append(f"max_len {old.max_len} -> {new.max_len}")

    old_qs, new_qs = {q.name: q for q in old.questions}, {q.name: q for q in new.questions}
    for name in sorted(set(old_qs) - set(new_qs)):
        changes.append(f"removed question {name}")
    for name in sorted(set(new_qs) - set(old_qs)):
        changes.append(f"added question {name}")
    for name in sorted(set(old_qs) & set(new_qs)):
        o, n = old_qs[name], new_qs[name]
        if o.type != n.type:
            changes.append(f"{name}: type {o.type.value} -> {n.type.value}")
        if o.instructions != n.instructions:
            changes.append(f"{name}: instructions changed")
        if o.criteria != n.criteria:
            changes.append(f"{name}: options changed")
        if o.labels != n.labels:
            changes.append(f"{name}: labels changed")
    return changes


def check_migration(old: Protocol, new: Protocol) -> list[str]:
    """Report every semantic change between two protocol versions.

    A change to a question's *options* is a change to the decision problem: answers recorded
    under the old option set are not comparable to answers under the new one. This function
    makes that visible so stored decisions can be migrated or re-scored deliberately instead
    of being compared across a silent semantic change.
    """
    changes: list[str] = []
    if old.protocol_version != new.protocol_version:
        changes.append(f"protocol_version {old.protocol_version} -> {new.protocol_version}")

    old_specs, new_specs = {s.name: s for s in old.specs}, {s.name: s for s in new.specs}
    for name in sorted(set(old_specs) - set(new_specs)):
        changes.append(f"removed spec {name}")
    for name in sorted(set(new_specs) - set(old_specs)):
        changes.append(f"added spec {name} v{new_specs[name].version}")
    for name in sorted(set(old_specs) & set(new_specs)):
        changes.extend(f"{name}: {c}" for c in change_log(old_specs[name], new_specs[name]))
    return changes
