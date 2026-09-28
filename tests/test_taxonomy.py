"""Tests for the NSE taxonomy mapping.

The mapping is what turns a real, published, human-curated label (NSE's `desc`) into something
the evaluation can score, so a silent error here does not degrade quality, it invalidates the
headline number. Two properties carry the weight and both are pinned here:

1. **Every class the real feed contains is handled explicitly.** A class that is neither mapped
   nor declared unresolved falls through to `UNRESOLVED`, which is the safe default -- but "safe
   default" is not "handled", and a mapping that silently stops covering a live class would show
   up as a falling measurable fraction rather than as an error. These tests compare against the
   class names actually present in `evals/datasets/nse_announcements_v1.report.json`, which was
   produced from a live fetch, and against a hardcoded copy of that list taken from the same
   artifact so the test does not merely re-read whatever the code currently does.

2. **`UNRESOLVED` is not `other`.** "This filing is real but its event type is not derivable"
   and "resolved, and genuinely none of the above" are different claims, and the ability to say
   "I cannot tell" is a first-class product claim. Collapsing them would make that unmeasurable.

No torch, no checkpoint, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from divya.data.nse_taxonomy import (
    DESC_TO_EVENT_TYPE,
    UNRESOLVED,
    UNRESOLVED_CLASSES,
    classify,
    is_measurable,
    taxonomy_report,
)

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "evals" / "datasets" / "nse_announcements_v1.jsonl"
REPORT = REPO / "evals" / "datasets" / "nse_announcements_v1.report.json"
EVAL_ARTIFACT = REPO / "evals" / "results" / "real_eval.json"

#: Every distinct NSE `desc` value observed in the live September-2026 fetch that produced
#: `nse_announcements_v1.report.json` (6,000 announcements, 82 distinct classes). NSE publishes
#: 104 distinct values across the full 14,802-record month; the remaining 22 are rarer than this
#: sample and are not enumerated anywhere in this repository, so the honest assertion is over
#: what was actually observed rather than over a number nobody can reconstruct.
OBSERVED_NSE_CLASSES: tuple[str, ...] = (
    'Acquisition',
    'Action(s) initiated or orders passed',
    'Action(s) taken or orders passed',
    'Addendum',
    'Address Change',
    'Adoption of new line(s) of business',
    'Agreements',
    'Allotment of Securities',
    'Amalgamation/Merger',
    'Amendment to AOA/MOA',
    'Analysts/Institutional Investor Meet/Con. Call Updates',
    'Appointment',
    'Awarding of order(s)/contract(s)',
    'Bagging/Receiving of orders/contracts',
    'Bonus',
    'Buyback',
    'Capacity addition',
    'Certificate under SEBI (Depositories and Participants) Regulations, 2018',
    'Cessation',
    'Change in Auditors',
    'Change in Company Secretary/Compliance Officer',
    'Change in Director(s)',
    'Change in Management',
    'Commencement of commercial production/operations',
    'Committee Meeting Updates',
    'Copy of Newspaper Publication',
    'Corporate Insolvency Resolution Process',
    'Corrigendum',
    'Credit Rating',
    'Credit Rating- New',
    'Credit Rating- Others',
    'Credit Rating- Revision',
    'Demerger',
    'Demise',
    'Disclosure of material issue',
    'Disclosure under SEBI Takeover Regulations',
    'Disruption of Operations',
    'Dividend',
    'ESOP/ESOS/ESPS',
    'Extension of Annual General Meeting',
    'General Updates',
    'Giving guarantees/indemnity/ becoming a surety for third party',
    'Granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals',
    'Increase in Authorised Capital',
    'Investor Presentation',
    'Issue of Securities',
    'Loss of Share Certificates',
    'Memorandum of Understanding/Agreements',
    'Monthly Business Updates',
    'Name Change',
    'Name and Symbol Change',
    'News Verification',
    'Options to purchase securities',
    'Other Restructuring',
    'Others',
    'Outcome of Board Meeting',
    'Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company',
    'Post Buyback Public Announcement',
    'Preferential issue',
    'Press Release',
    'Price movement',
    'Product launch',
    'Public Announcement - Buyback of Shares',
    'Qualified Institutional Placement',
    'Record Date',
    'Reply to Clarification- Financial results',
    'Rescission/termination(s)',
    'Resignation',
    'Resignation of Director/KMP/SMP',
    'Retirement',
    'Rights Issue',
    'Rumour Verification - Regulation 30(11)',
    'Sale or disposal',
    'Scheme of Arrangement',
    'Shareholders meeting',
    'Spurt in Volume',
    'Stock split',
    'Strikes/Lockouts/Disturbances',
    'Suspension of Trading',
    'Trading Plan under PIT',
    'Trading Window',
    'Updates',
)

#: Classes the taxonomy declares but that this sample never contained. Named separately so a
#: future run that does encounter one is visible rather than quietly folded in.
DECLARED_NOT_OBSERVED: tuple[str, ...] = (
    "Clarification",
    "Press Release (Revised)",
    "Structural Digital Database",
    "Arrangements for strategic, technical, manufacturing, or marketing tie up",
    "Change in Fiscal Year",
    "Clarification - Financial Results",
    "Closure of Buy Back",
    "Closure of operations",
    "Conversion",
    "Delay/default in the payment of fines/penalties/dues etc. to authority",
    "Diversification/Disinvestment",
    "Effect(s) on listed entity due to changed regulatory  framework applicable",
    "Effect(s) on listed entity due to changed regulatory framework applicable",
    "Fraud/Default/Arrest",
    "Integrated Filing- Financial",
    "Issue of Duplicate Share Certificate",
    "Monitoring Agency Report",
    "Postponement of commercial production/operations",
    "Public Announcement-Open Offer",
    "Reasons for Delayed/Non-submission of Financial Results",
    "Redemption",
    "Registrar & Share Transfer Agent Update",
    "Related Party Transactions",
    "Resignation of Statutory Auditor",
    "Revised Record date",
)


def _dataset_records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _dataset_descs() -> list[str]:
    return [str(r["nse_desc"]) for r in _dataset_records()]


def _report() -> dict[str, object]:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _feed_descs() -> list[str]:
    """The full 6,000-announcement population, reconstructed from the report's class counts.

    The shipped `.jsonl` is the *measurable* subset (`--measurable-only`), so it cannot be used
    to re-derive the report; the report's own per-class counts can, and doing so is a real check
    that the mapping still produces the published numbers rather than merely agreeing with a
    file that was written by the same code.
    """
    rep = _report()
    out: list[str] = []
    for name, n in {**rep["mapped_classes"], **rep["unmapped_classes"]}.items():
        out.extend([str(name)] * int(n))
    return out


# --- coverage of the real taxonomy -----------------------------------------


def test_the_hardcoded_class_list_is_the_one_the_live_fetch_contained():
    rep = _report()
    assert len(OBSERVED_NSE_CLASSES) == 82
    assert len(set(OBSERVED_NSE_CLASSES)) == 82
    assert set(OBSERVED_NSE_CLASSES) == set(rep["mapped_classes"]) | set(rep["unmapped_classes"])
    assert rep["total_announcements"] == 6000
    assert rep["kept_after_measurable_filter"] == len(_dataset_records()) == 1042
    assert rep["dropped_unresolved"] == 4958
    # The shipped dataset holds only the measurable tail, so its class set is a strict subset.
    assert set(_dataset_descs()) < set(OBSERVED_NSE_CLASSES)
    assert set(_dataset_descs()) == set(rep["mapped_classes"])


def test_every_real_class_is_explicitly_handled():
    """A class is handled if a human wrote it into one of the two tables.

    Not merely "classify() returned something": `classify` returns UNRESOLVED for a typo, and a
    typo would then be indistinguishable from a deliberate decision. Membership in a table is the
    assertion that a human looked at the class.
    """
    declared = set(DESC_TO_EVENT_TYPE) | set(UNRESOLVED_CLASSES)
    missing = [c for c in OBSERVED_NSE_CLASSES if c not in declared]
    assert missing == [], f"real NSE classes with no explicit handling: {missing}"
    assert not (set(DESC_TO_EVENT_TYPE) & set(UNRESOLVED_CLASSES)), (
        "a class cannot be both mapped and declared unresolved"
    )
    for extra in DECLARED_NOT_OBSERVED:
        assert extra in declared, f"{extra!r} is listed as declared but is in neither table"


def test_the_declared_taxonomy_has_no_duplicate_or_misspelled_keys():
    """Two spellings of one class is a real NSE distinction; a typo is a bug. Keep them apart."""
    # NSE genuinely publishes the framework class twice, with one and two spaces.
    assert (
        "Effect(s) on listed entity due to changed regulatory framework applicable"
        in DESC_TO_EVENT_TYPE
    )
    assert (
        "Effect(s) on listed entity due to changed regulatory  framework applicable"
        in DESC_TO_EVENT_TYPE
    )
    assert classify(
        "Effect(s) on listed entity due to changed regulatory framework applicable"
    ) == classify(
        "Effect(s) on listed entity due to changed regulatory  framework applicable"
    ) == "regulatory_action"


@pytest.mark.parametrize("desc", OBSERVED_NSE_CLASSES)
def test_no_real_class_silently_becomes_other(desc: str) -> None:
    """`other` is only ever the result of a deliberate row in the mapping table."""
    label = classify(desc)
    if desc in DESC_TO_EVENT_TYPE:
        assert label == DESC_TO_EVENT_TYPE[desc]
        if label == "other":
            assert desc in _DELIBERATE_OTHER
    else:
        assert label == UNRESOLVED


#: The classes deliberately parked in `other`: genuine corporate events the protocol has no
#: option for. A scope decision, recorded as one rather than hidden.
_DELIBERATE_OTHER = frozenset(
    k for k, v in DESC_TO_EVENT_TYPE.items() if v == "other"
)


# --- UNRESOLVED is not `other` ---------------------------------------------


def test_unresolved_is_distinct_from_other():
    assert UNRESOLVED == "unresolved"
    assert UNRESOLVED != "other"
    assert UNRESOLVED not in set(DESC_TO_EVENT_TYPE.values())
    assert classify("Trading Window") == UNRESOLVED
    assert classify("Others") == "other"
    assert is_measurable("Trading Window") is False
    assert is_measurable("Others") is True


@pytest.mark.parametrize(
    "unknown",
    [
        "",
        "   ",
        "A Class NSE Has Never Published",
        "appointment",              # case differs
        "appointment of director",  # a description, not a class name
        "Appointmentx",             # one character off a real class
        "Divdend",                  # a real class with a typo
    ],
)
def test_unknown_classes_return_unresolved_not_other(unknown: str) -> None:
    assert classify(unknown) == UNRESOLVED, f"{unknown!r} fell through to {classify(unknown)!r}"
    assert is_measurable(unknown) is False


def test_surrounding_whitespace_is_stripped_before_lookup():
    assert classify("  Appointment  ") == "leadership_change"
    assert classify(" Trading Window\n") == UNRESOLVED


def test_whitespace_is_stripped_but_the_class_is_not_guessed():
    assert classify("  Appointment  ") == "leadership_change"
    assert classify("APPOINTMENT") == UNRESOLVED
    assert classify("appointment") == UNRESOLVED


# --- taxonomy_report arithmetic --------------------------------------------


def test_taxonomy_report_reproduces_the_shipped_artifact():
    descs = _feed_descs()
    report = taxonomy_report(descs)
    shipped = _report()
    assert report["total_announcements"] == shipped["total_announcements"] == len(descs) == 6000
    assert report["distinct_classes"] == shipped["distinct_classes"] == 82
    assert report["classes_mapped"] == shipped["classes_mapped"] == 60
    assert report["measurable_announcements"] == shipped["measurable_announcements"] == 1042
    assert report["measurable_fraction"] == shipped["measurable_fraction"] == 0.1737
    assert report["by_event_type"] == shipped["by_event_type"]
    assert sum(report["by_event_type"].values()) == 1042
    assert report["mapped_classes"] == shipped["mapped_classes"]
    assert report["unmapped_classes"] == shipped["unmapped_classes"]


def test_taxonomy_report_arithmetic_on_a_hand_counted_input():
    report = taxonomy_report(["Dividend", "Dividend", "Appointment", "Trading Window", "Nonsense"])
    assert report["total_announcements"] == 5
    assert report["distinct_classes"] == 4
    assert report["classes_mapped"] == 2, "only Dividend and Appointment are measurable"
    assert report["measurable_announcements"] == 3
    # 3/5 = 0.6, and the value is rounded to 4 places by the function itself.
    assert report["measurable_fraction"] == 0.6
    assert report["by_event_type"] == {"capital_action": 2, "leadership_change": 1}
    assert report["mapped_classes"] == {"Dividend": 2, "Appointment": 1}
    assert report["unmapped_classes"] == {"Trading Window": 1, "Nonsense": 1}
    # Sorted by descending count, so the largest class is first and is the one a reader looks at.
    assert list(report["by_event_type"]) == ["capital_action", "leadership_change"]
    assert list(report["unmapped_classes"]) == ["Trading Window", "Nonsense"]


def test_taxonomy_report_on_an_empty_input_does_not_divide_by_zero():
    report = taxonomy_report([])
    assert report["total_announcements"] == 0
    assert report["measurable_fraction"] == 0.0
    assert report["by_event_type"] == {}
    assert report["classes_mapped"] == 0


def test_the_unmapped_population_is_the_dominant_one():
    """77% of the feed is pure process. A mapping that only counted the measurable tail would
    report a flattering number, so the size of the untouched population is itself a result."""
    report = taxonomy_report(_feed_descs())
    assert report["measurable_fraction"] < 0.25
    assert report["unmapped_classes"]["Trading Window"] == 1789
    assert report["unmapped_classes"]["Shareholders meeting"] == 1242


# --- against the shipped evaluation artifact -------------------------------


def test_every_dataset_label_is_what_classify_returns():
    """The dataset's `labels.event_type` is derived from the taxonomy; if they ever diverge, the
    evaluation is scoring against a label the product would not produce."""
    bad: list[tuple[str, str, str]] = []
    for rec in _dataset_records():
        assert classify(str(rec["nse_desc"])) != UNRESOLVED, (
            f"{rec['id']} is in the measurable-only dataset but its class is unresolved"
        )
        assert rec["is_measurable"] is True
        assert rec["label_source"] == "nse_desc_via_nse_taxonomy"
        if classify(str(rec["nse_desc"])) != rec["labels"]["event_type"]:
            bad.append((str(rec["id"]), str(rec["nse_desc"]), str(rec["labels"]["event_type"])))
    assert bad == [], f"dataset labels that disagree with the taxonomy: {bad[:5]}"


def test_the_headline_eval_number_is_pinned_to_the_artifact():
    """Arm A on the real NSE sample is the number the README quotes. Pin it.

    If the harness, the protocol or the dataset changes, this fails loudly rather than the README
    quietly becoming wrong.
    """
    report = json.loads(EVAL_ARTIFACT.read_text(encoding="utf-8"))
    assert report["config"]["system1_available"] is True
    assert report["config"]["provider"] == "ollama"
    a = report["results"]["A"]
    assert a["event_type"]["accuracy"] == 0.5583
    assert a["event_type"]["macro_f1"] == 0.4362
    assert a["calibration"]["ece_event_type"] == 0.0956
    assert a["calibration"]["aurc"] == 0.2399
    # The thesis under test: C is the control, D is the claim, and D is not better.
    assert report["results"]["C"]["event_type"]["accuracy"] == a["event_type"]["accuracy"]
    assert report["results"]["D"]["event_type"]["accuracy"] < a["event_type"]["accuracy"]
    assert report["results"]["B"]["event_type"]["accuracy"] == 0.0
    assert report["dataset"]["synthetic_text"] is False
    assert report["dataset"]["n_items"] == 120
