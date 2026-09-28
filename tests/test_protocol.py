"""Protocol tests.

The protocol is the contract with System-1, and its rules are copied from Laya's source rather
than from its documentation. Each test here pins one rule that, if the file drifted, would
produce an error deep inside inference instead of at load time.

No torch, no checkpoint: this module must be importable on a box with no System-1 weights,
because that is what CI and the degradation tests rely on.
"""

from __future__ import annotations

import pytest
import yaml

from divya.protocol.loader import (
    MAX_CALIBRATED_CHOICE_OPTIONS,
    ProtocolError,
    change_log,
    check_migration,
    iter_questions,
    laya_option_bucket,
    load_protocol,
)
from divya.protocol.schema import DecisionSpec, DecisionType, Protocol, Question

MINIMAL = {
    "protocol_version": "0.1.0",
    "specs": [
        {
            "name": "s",
            "version": 1,
            "questions": [
                {
                    "name": "q",
                    "type": "noul",
                    "instructions": "Decide.",
                    "labels": {"false": "no", "true": "yes"},
                }
            ],
        }
    ],
}


def _write(tmp_path, doc) -> str:
    p = tmp_path / "questions.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return str(p)


# --- Laya contract rules ---------------------------------------------------


def test_noul_labels_must_cover_false_and_true_exactly():
    with pytest.raises(ValueError, match="exactly 'false' and 'true'"):
        Question(name="q", type="noul", instructions="i", labels={"no": "x", "yes": "y"})


def test_noul_labels_must_be_distinct():
    with pytest.raises(ValueError, match="distinct"):
        Question(name="q", type="noul", instructions="i", labels={"false": "same", "true": "same"})


def test_noul_labels_must_be_non_empty():
    with pytest.raises(ValueError, match="non-empty"):
        Question(name="q", type="noul", instructions="i", labels={"false": "  ", "true": "yes"})


def test_labels_rejected_on_choice():
    """Laya raises `labels is only supported for noul questions` (common.py:110)."""
    with pytest.raises(ValueError, match="only valid on noul"):
        Question(
            name="q",
            type="choice",
            instructions="i",
            criteria={"a": "first", "b": "second"},
            labels={"false": "no", "true": "yes"},
        )


def test_labels_rejected_on_score():
    with pytest.raises(ValueError, match="only valid on noul"):
        Question(name="q", type="score", instructions="i", criteria=["low", "high"],
                 labels={"false": "no", "true": "yes"})


def test_choice_requires_mapping_criteria():
    with pytest.raises(ValueError, match="non-empty mapping"):
        Question(name="q", type="choice", instructions="i", criteria=["a", "b"])


def test_score_requires_ordered_list_of_at_least_two():
    with pytest.raises(ValueError, match="at least 2 level descriptions"):
        Question(name="q", type="score", instructions="i", criteria=["only one"])


def test_unknown_type_is_rejected():
    """`choice`/`score`/`noul` are the whole vocabulary (common.py:17 QTYPES)."""
    with pytest.raises(ValueError):
        Question(name="q", type="rank", instructions="i", criteria=["a", "b"])


def test_name_must_be_snake_case():
    with pytest.raises(ValueError):
        Question(name="Event Type", type="noul", instructions="i")


# --- rendering -------------------------------------------------------------


def test_to_laya_drops_divya_metadata():
    """Only the four fields Laya understands may be sent.

    Audit metadata going to the engine would be a channel through which evaluation config could
    influence a decision, so the boundary is asserted rather than assumed.
    """
    q = Question(
        name="q", type="noul", instructions="Decide.", labels={"false": "no", "true": "yes"},
        purpose="why", known_failure_modes=["x"], downstream_consumers=["y"], tier=2,
    )
    payload = q.to_laya()
    assert set(payload) == {"type", "instructions", "labels"}
    assert payload["type"] == "noul"


def test_choice_to_laya_preserves_label_descriptions():
    q = Question(name="q", type="choice", instructions="i",
                 criteria={"earnings": "results", "merger": "M and A"})
    assert q.to_laya()["criteria"] == {"earnings": "results", "merger": "M and A"}
    assert q.option_count == 2


def test_spec_to_laya_can_select_a_subset():
    """Selective invocation: the runtime asks for named decisions, not the whole spec."""
    spec = DecisionSpec(
        name="s", version=1,
        questions=[
            Question(name="a", type="noul", instructions="i"),
            Question(name="b", type="noul", instructions="i"),
        ],
    )
    assert set(spec.to_laya(only=["b"])) == {"b"}


def test_spec_rejects_duplicate_question_names():
    with pytest.raises(ValueError, match="duplicate question names"):
        DecisionSpec(
            name="s", version=1,
            questions=[Question(name="a", type="noul", instructions="i")] * 2,
        )


# --- calibration buckets ---------------------------------------------------


def test_option_bucket_reproduces_laya_routing():
    """Must match laya.common.temp_bucket exactly, or the guard below guards the wrong thing."""
    assert laya_option_bucket("choice", 2) == "choice:2"
    assert laya_option_bucket("choice", 3) == "choice:3-5"
    assert laya_option_bucket("choice", 5) == "choice:3-5"
    assert laya_option_bucket("choice", 6) == "choice:6-10"
    assert laya_option_bucket("choice", 10) == "choice:6-10"
    assert laya_option_bucket("choice", 11) == "choice:11+"
    assert laya_option_bucket("score", 4) == "score:3-5"
    assert laya_option_bucket("noul", 2) == "noul:2"


def test_eleven_option_choice_is_rejected_as_uncalibrated(tmp_path):
    """The shipped `choice:11+` temperature is 0.1006 and Laya disclaims its confidence.

    A protocol that lands there would report ECE computed from numbers the engine has already
    said not to trust, so this must fail at load time.
    """
    doc = {
        "protocol_version": "0.1.0",
        "specs": [
            {
                "name": "s", "version": 1,
                "questions": [
                    {
                        "name": "wide", "type": "choice", "instructions": "i",
                        "criteria": {f"opt{i}": f"desc {i}" for i in range(11)},
                    }
                ],
            }
        ],
    }
    with pytest.raises(ProtocolError, match="uncalibrated"):
        load_protocol(_write(tmp_path, doc))


def test_ten_option_choice_is_accepted(tmp_path):
    doc = {
        "protocol_version": "0.1.0",
        "specs": [
            {
                "name": "s", "version": 1,
                "questions": [
                    {
                        "name": "wide", "type": "choice", "instructions": "i",
                        "criteria": {f"opt{i}": f"desc {i}" for i in range(MAX_CALIBRATED_CHOICE_OPTIONS)},
                    }
                ],
            }
        ],
    }
    p = load_protocol(_write(tmp_path, doc))
    assert p.by_name("s").by_name("wide").option_count == 10


# --- loader errors ---------------------------------------------------------


def test_missing_file_names_the_env_var(tmp_path):
    with pytest.raises(ProtocolError, match="DIVYA_PROTOCOL_PATH"):
        load_protocol(tmp_path / "nope.yaml")


def test_duplicate_spec_names_rejected(tmp_path):
    doc = {**MINIMAL, "specs": MINIMAL["specs"] * 2}
    with pytest.raises(ProtocolError, match="duplicate spec names"):
        load_protocol(_write(tmp_path, doc))


def test_malformed_yaml_is_reported_not_raised_raw(tmp_path):
    p = tmp_path / "questions.yaml"
    p.write_text("protocol_version: '0.1.0'\nspecs:\n  - name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProtocolError, match="invalid YAML"):
        load_protocol(str(p))


# --- migration -------------------------------------------------------------


def test_change_log_reports_option_changes():
    old = DecisionSpec(
        name="s", version=1,
        questions=[Question(name="q", type="choice", instructions="i",
                           criteria={"a": "x", "b": "y"})],
    )
    new = DecisionSpec(
        name="s", version=2,
        questions=[Question(name="q", type="choice", instructions="i",
                           criteria={"a": "x", "b": "y", "c": "z"})],
    )
    changes = change_log(old, new)
    assert any("version 1 -> 2" in c for c in changes)
    assert any("options changed" in c for c in changes)


def test_migration_flags_removed_questions():
    old = Protocol(protocol_version="0.1.0", specs=[
        DecisionSpec(name="s", version=1, questions=[
            Question(name="gone", type="noul", instructions="i"),
        ]),
    ])
    new = Protocol(protocol_version="0.1.0", specs=[
        DecisionSpec(name="s", version=2, questions=[
            Question(name="stays", type="noul", instructions="i"),
        ]),
    ])
    changes = check_migration(old, new)
    assert any("removed question gone" in c for c in changes)
    assert any("added question stays" in c for c in changes)


# --- the shipped protocol --------------------------------------------------


def test_shipped_protocol_loads():
    p = load_protocol()
    assert p.protocol_version
    assert p.names == sorted(p.names, key=p.names.index)  # order preserved, not sorted
    assert set(p.names) >= {"event_triage", "event_evidence"}


def test_shipped_protocol_has_tiered_decisions():
    """Tier separation is what makes arm C and arm D different architectures."""
    p = load_protocol()
    tiers = {q.name: q.tier for _s, q in iter_questions(p)}
    assert tiers["event_type"] == 1
    assert tiers["evidence_sufficiency"] == 2
    assert any(t == 1 for t in tiers.values())
    assert any(t > 1 for t in tiers.values())


def test_shipped_protocol_is_calibrated_everywhere():
    p = load_protocol()
    for spec in p.specs:
        for q in spec.questions:
            if q.type is DecisionType.CHOICE:
                assert laya_option_bucket("choice", q.option_count) != "choice:11+"
