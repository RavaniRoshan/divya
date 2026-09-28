"""Build a REAL evaluation dataset from live NSE corporate announcements.

This is the counterpart to `evals/make_dataset.py`, which builds synthetic text. The
synthetic set stays in the repository because it is deterministic, stratified by construction,
and contains the adversarial prompt-injection cases that a live feed will never contain. This
one is the set that shows whether any of it means anything.

**What this produces is real and what it is not:**

* Real: the filing text, the company, the industry, the timestamp, and the PDF link are all
  fetched from NSE. Nothing here is generated.
* Not ground truth: the label is **NSE's own `desc` field**, mapped onto our taxonomy by the
  explicit table in `nse_taxonomy.py`. Agreement with that is agreement with the exchange's
  filing classification. It is a real, published, human-curated label — which is much better
  than our own annotation — and it is still a taxonomy, not the truth about what happened to
  the business.
* Deliberately excluded: filing containers (`Outcome of Board Meeting`) and routine process
  (`Trading Window`, `Copy of Newspaper Publication`). Their `event_type` is not derivable
  from the class, so they are marked `unresolved` and reported as their own population
  instead of being dropped or guessed at.

Usage:
    python evals/build_real_dataset.py --out evals/datasets/nse_announcements_v1.jsonl
    python evals/build_real_dataset.py --start 2026-09-01 --end 2026-09-28 --limit 400
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from divya.data.nse import NseAnnouncements
from divya.data.nse_taxonomy import (
    UNRESOLVED,
    classify,
    is_measurable,
    taxonomy_report,
)


def stratum_for(a) -> str:
    """Assign a stratum from observable properties of the record, not from results.

    Strata are assigned before any model runs. Choosing them afterwards would make every
    hypothesis about the loop unfalsifiable.
    """
    if not is_measurable(a.desc):
        return "unmapped_class"
    text = a.text
    # NSE's `attchmntText` is a one-line summary, not the filing body -- in the September 2026
    # sample the median is 154 characters. Below 120 there is usually not enough text to
    # contain a stated figure or a counterparty, so that is the floor for a real decision.
    # Fixed here, in advance, from the observed distribution rather than tuned per result.
    if len(text) < 120:
        return "noisy"
    # A filing naming two or more event families is the ambiguous population. Counted from
    # literal markers in the exchange's own class plus the filing text, again before scoring.
    markers = (
        a.desc in {"Acquisition", "Stakes in JV / Subsidiary"}
        or "dividend" in text.lower()
        or "bonus" in text.lower()
        or "acquisition" in text.lower()
    )
    return "ambiguous" if markers else "clear"


def build(
    start: date, end: date, limit: int | None, seed: int = 20260928
) -> tuple[list[dict], dict]:
    src = NseAnnouncements()
    announcements, truncated = src.fetch(start, end, limit=limit)
    if not announcements:
        raise SystemExit(
            f"NSE returned no announcements for {start}..{end}. This is an outage or a changed "
            f"endpoint shape, not an empty market."
        )

    rng = random.Random(seed)
    items: list[dict] = []
    for a in announcements:
        label = classify(a.desc)
        items.append(
            {
                "id": f"nse_{a.seq_id or abs(hash(a.text)) % 10**10}",
                "stratum": stratum_for(a),
                "is_synthetic_text": False,
                "source": "nse_corporate_announcements",
                "symbol": a.symbol,
                "company": a.company,
                "industry": a.industry,
                "nse_desc": a.desc,
                "pdf_url": a.pdf_url,
                "has_xbrl": a.has_xbrl,
                "content": a.text,
                "labels": {"event_type": label},
                "label_source": "nse_desc_via_nse_taxonomy",
                "is_measurable": label != UNRESOLVED,
                # No annotator confidence: this is a published label, not an annotation. The
                # field is present and explicitly null so downstream code cannot invent one.
                "annotator_confidence": None,
                "announced_at": a.announced_at,
                "raw_nse": a.raw,
            }
        )

    rng.shuffle(items)
    report = taxonomy_report([a.desc for a in announcements])
    report["window"] = [str(start), str(end)]
    report["truncated"] = truncated
    report["fetched"] = len(announcements)
    report["strata"] = dict(Counter(i["stratum"] for i in items))
    return items, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="2026-09-28")
    ap.add_argument("--limit", type=int, default=1500,
                    help="cap on announcements fetched; keeps the dataset commit-sized")
    ap.add_argument("--measurable-only", action="store_true",
                    help="keep only announcements whose NSE class maps to a scorable label. "
                         "The base rate of the full feed is still reported, so the filter is "
                         "visible rather than hidden.")
    ap.add_argument("--out", default="evals/datasets/nse_announcements_v1.jsonl")
    ap.add_argument("--report", default="evals/datasets/nse_announcements_v1.report.json")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    items, report = build(start, end, args.limit)
    if args.measurable_only:
        kept = [i for i in items if i["is_measurable"]]
        report["kept_after_measurable_filter"] = len(kept)
        report["dropped_unresolved"] = len(items) - len(kept)
        items = kept

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {len(items)} real announcements to {out}")
    print(f"strata: {report['strata']}")
    print(
        f"measurable: {report['measurable_announcements']}/{report['total_announcements']} "
        f"({report['measurable_fraction']:.1%}) across {report['classes_mapped']}"
        f"/{report['distinct_classes']} NSE classes"
    )
    if report["truncated"]:
        print("WARNING: response hit the record cap; narrow the window to avoid silent truncation.")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
