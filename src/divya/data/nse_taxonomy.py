"""Mapping NSE's announcement taxonomy onto Divya's decision protocol.

NSE publishes a `desc` field on every corporate announcement — **104 distinct classes** in
September 2026, human-curated by the exchange. That is a real, published label, and it is a
far better evaluation target than anything we could annotate ourselves.

It is **not** the same taxonomy as ours, and pretending otherwise would be the easiest false
claim in this project to make:

* NSE classifies **what kind of filing this is**. "Trading Window", "Copy of Newspaper
  Publication" and "Press Release" are filing categories.
* Divya's `event_type` asks **what corporate event occurred**. "Outcome of Board Meeting" is a
  filing category; the event inside it might be results, a dividend, an acquisition or a
  resignation, and only the text says which.

**The real distribution is the first useful finding.** The six largest classes are pure process:

    Shareholders meeting                            2668
    Trading Window                                  1858
    General Updates                                 1752
    Analysts/Institutional Investor Meet            1700
    Copy of Newspaper Publication                   1415
    Updates                                         1035

That is 11,428 of 14,805 announcements — **77%** — carrying no corporate event at all. A system
that claimed to classify "corporate events" and silently dropped these would look far better
than it is; one that classified them would be confidently wrong. They are ingested, labelled
`unresolved`, and reported as their own population.

**What the agreement numbers mean.** For classes that map one-to-one, we are measuring
agreement with NSE's filing classification — a real, published, human-curated label. That is
meaningful and it is auditable. It is not the same as being right about the market, and no
report in this repository claims it is.

Every mapping below is explicit. There is no fuzzy matching and no learned mapping, because a
mapping that cannot be read cannot be disputed when a result is wrong. Built by reading all 104
published classes on 2026-09-28 and assigning each one explicitly.
"""

from __future__ import annotations

#: NSE `desc` -> Divya `event_type`. Covers every event-bearing class in the published
#: taxonomy. Classes absent from this table and from :data:`UNRESOLVED_CLASSES` fall through
#: to `unresolved` rather than being guessed at.
DESC_TO_EVENT_TYPE: dict[str, str] = {
    # --- results and clarifications ----------------------------------------
    # `Outcome of Board Meeting` is deliberately absent: at 456 records it is the largest
    # event-bearing class and its text does not always state the outcome, so it is a
    # container (see UNRESOLVED_CLASSES) rather than a guessable label.
    "Clarification - Financial Results": "earnings_result",
    "Reply to Clarification- Financial results": "earnings_result",
    "Integrated Filing- Financial": "earnings_result",
    "Reasons for Delayed/Non-submission of Financial Results": "earnings_result",

    # --- capital actions (board decisions changing capital per share) --------
    "ESOP/ESOS/ESPS": "capital_event",
    "Options to purchase securities": "capital_event",
    "Allotment of Securities": "capital_event",
    "Dividend": "capital_event",
    "Bonus": "capital_event",
    "Buyback": "capital_event",
    "Public Announcement - Buyback of Shares": "capital_event",
    "Post Buyback Public Announcement": "capital_event",
    "Closure of Buy Back": "capital_event",
    "Stock split": "capital_event",
    "Increase in Authorised Capital": "capital_event",
    "Conversion": "capital_event",
    "Redemption": "capital_event",

    # --- fundraising ---------------------------------------------------------
    "Issue of Securities": "capital_event",
    "Qualified Institutional Placement": "capital_event",
    "Preferential issue": "capital_event",
    "Rights Issue": "capital_event",
    "Public Announcement-Open Offer": "capital_event",

    # --- M&A ----------------------------------------------------------------
    "Acquisition": "capital_event",
    "Amalgamation/Merger": "capital_event",
    "Scheme of Arrangement": "capital_event",
    "Sale or disposal": "capital_event",
    "Demerger": "capital_event",
    "Memorandum of Understanding/Agreements": "capital_event",
    "Arrangements for strategic, technical, manufacturing, or marketing tie up": "capital_event",
    "Disclosure under SEBI Takeover Regulations": "capital_event",
    "Diversification/Disinvestment": "capital_event",
    "Adoption of new line(s) of business": "capital_event",

    # --- people and auditors -------------------------------------------------
    "Appointment": "leadership_change",
    "Resignation of Director/KMP/SMP": "leadership_change",
    "Change in Management": "leadership_change",
    "Resignation": "leadership_change",
    "Change in Director(s)": "leadership_change",
    "Cessation": "leadership_change",
    "Retirement": "leadership_change",
    "Change in Company Secretary/Compliance Officer": "leadership_change",
    "Demise": "leadership_change",
    "Resignation of Statutory Auditor": "auditor_change",
    "Change in Auditors": "auditor_change",

    # --- credit ---------------------------------------------------------------
    "Credit Rating": "credit_rating",
    "Credit Rating- Revision": "credit_rating",
    "Credit Rating- New": "credit_rating",
    "Credit Rating- Others": "credit_rating",

    # --- regulatory, legal, and enforcement ----------------------------------
    "Action(s) taken or orders passed": "regulatory_action",
    "Action(s) initiated or orders passed": "regulatory_action",
    "Corporate Insolvency Resolution Process": "regulatory_action",
    "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company": "regulatory_action",
    "Suspension of Trading": "regulatory_action",
    "Fraud/Default/Arrest": "regulatory_action",
    "Delay/default in the payment of fines/penalties/dues etc. to authority": "regulatory_action",
    "Granting/withdrawal/surrender/cancellation/suspension of key licenses/ regulatory approvals":
        "regulatory_action",
    "Effect(s) on listed entity due to changed regulatory framework applicable": "regulatory_action",
    # NSE publishes this class with a double space in the framework name; matched verbatim
    # because a normalised key would silently merge two classes the exchange keeps distinct.
    "Effect(s) on listed entity due to changed regulatory  framework applicable": "regulatory_action",
    "Other Restructuring": "capital_event",
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018": "regulatory_action",

    # --- operating events with no better home ---------------------------------
    # These are genuine corporate events. They are `other` because the protocol has no
    # option for them, which is a scope decision and is recorded as one rather than hidden
    # by inventing a tenth-and-a-half category.
    "Bagging/Receiving of orders/contracts": "other",
    "Awarding of order(s)/contract(s)": "other",
    "Commencement of commercial production/operations": "other",
    "Capacity addition": "other",
    "Product launch": "other",
    "Disruption of Operations": "other",
    "Postponement of commercial production/operations": "other",
    "Closure of operations": "other",
    "Strikes/Lockouts/Disturbances": "other",
    "Giving guarantees/indemnity/ becoming a surety for third party": "other",
    "Related Party Transactions": "other",
    "Rescission/termination(s)": "other",
    "Amendment to AOA/MOA": "other",
    "Agreements": "other",
    "Disclosure of material issue": "other",
    "Extension of Annual General Meeting": "other",
    "Revised Record date": "other",
    "Change in Fiscal Year": "other",
    "Loss of Share Certificates": "other",
    "Issue of Duplicate Share Certificate": "other",
    "Registrar & Share Transfer Agent Update": "other",
    "Monitoring Agency Report": "other",
    "Others": "other",
}

#: Filing containers and pure process. These are ingested and displayed, but their
#: `event_type` is not derivable from the class, so they carry :data:`UNRESOLVED` and are
#: reported as a separate population. Dropping them silently would inflate every accuracy
#: figure by removing exactly the population that dominates a real feed.
UNRESOLVED_CLASSES: frozenset[str] = frozenset({
    # The six largest classes in the feed: 77% of all announcements, no corporate event.
    "Shareholders meeting",
    "Trading Window",
    "General Updates",
    "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Copy of Newspaper Publication",
    "Updates",
    # Containers: an event happened, but which one is only in the text (often the PDF).
    "Outcome of Board Meeting",
    "Press Release",
    "Press Release (Revised)",
    "Committee Meeting Updates",
    "Monthly Business Updates",
    "Investor Presentation",
    "Record Date",
    # Corrections and verifications about other filings, not events themselves.
    "Corrigendum",
    "Addendum",
    "News Verification",
    "Rumour Verification - Regulation 30(11)",
    "Clarification",
    # Market movement notices: exchange commentary, not a company event.
    "Spurt in Volume",
    "Price movement",
    # Administrative housekeeping.
    "Address Change",
    "Name Change",
    "Name and Symbol Change",
    "Trading Plan under PIT",
    "Structural Digital Database",
})

#: The label for "this filing is real, but its event type is not resolvable from the class".
#: Kept distinct from `other`, which means "resolved, and genuinely none of the above".
#: Collapsing them would make it impossible to measure how often the system correctly says
#: "I cannot tell", which is a first-class claim for this product.
UNRESOLVED = "unresolved"


def classify(desc: str) -> str:
    """Map an NSE ``desc`` to a Divya ``event_type`` label for evaluation.

    Unknown classes return :data:`UNRESOLVED` rather than falling back to `other`. Guessing
    "other" for a class we have never seen would manufacture a label, and the failure would be
    indistinguishable from the model getting it right.
    """
    d = (desc or "").strip()
    if d in DESC_TO_EVENT_TYPE:
        return DESC_TO_EVENT_TYPE[d]
    return UNRESOLVED


def is_measurable(desc: str) -> bool:
    """True when :func:`classify` yields a label we can actually score against."""
    return classify(desc) != UNRESOLVED


def taxonomy_report(descs: list[str]) -> dict[str, object]:
    """Coverage of the NSE taxonomy against our protocol.

    Run this before trusting any agreement figure. If a class that matters is unmapped, the
    number is measuring the wrong population, and the report has to say so rather than let a
    reader assume the table was exhaustive.
    """
    from collections import Counter

    counts = Counter(descs)
    mapped = {d: n for d, n in counts.items() if is_measurable(d)}
    unmapped = {d: n for d, n in counts.items() if not is_measurable(d)}
    total = sum(counts.values())
    covered = sum(mapped.values())

    by_label: dict[str, int] = {}
    for d, n in mapped.items():
        by_label[DESC_TO_EVENT_TYPE[d]] = by_label.get(DESC_TO_EVENT_TYPE[d], 0) + n

    return {
        "total_announcements": total,
        "distinct_classes": len(counts),
        "classes_mapped": len(mapped),
        "measurable_announcements": covered,
        "measurable_fraction": round(covered / total, 4) if total else 0.0,
        "by_event_type": dict(sorted(by_label.items(), key=lambda kv: -kv[1])),
        "mapped_classes": dict(sorted(mapped.items(), key=lambda kv: -kv[1])),
        "unmapped_classes": dict(sorted(unmapped.items(), key=lambda kv: -kv[1])),
    }
