"""Upgrade an evaluation dataset from announcement summaries to full filing text.

The eval set was built from NSE's `attchmntText` — a one-line summary whose median in the
September 2026 feed is 154 characters. The filing itself is in the attached PDF. This script
swaps one for the other, so the same A/B/C/D comparison can be re-run on the text a real
deployment would actually see.

Labels are carried over **unchanged**. They came from NSE's own `desc` field, not from the
document text, so re-extracting the text cannot silently move the goalposts — which is the
failure mode that makes "we improved because we changed the data" unfalsifiable. Every row
records where its text came from, so a report can state how many items were decided on a short
summary rather than quietly pooling two input distributions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from divya.data.filings import get_filing_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="evals/datasets/nse_announcements_v1.jsonl")
    ap.add_argument("--out", default="evals/datasets/nse_announcements_filings_v1.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    rows = [
        json.loads(line)
        for line in Path(args.inp).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        rows = rows[: args.limit]

    out: list[dict] = []
    used_pdf = 0
    reasons: Counter[str] = Counter()
    for i, r in enumerate(rows, 1):
        ft = get_filing_text(r["id"], r["content"], r.get("pdf_url"), cache=True, max_chars=12_000)
        if ft.used_pdf:
            used_pdf += 1
        else:
            reasons[ft.reason.split(":")[0].strip() or "unknown"] += 1
        row = dict(r)
        row["content"] = ft.text
        row["text_source"] = ft.source
        row["summary_chars"] = ft.summary_chars
        row["filing_chars"] = ft.chars
        row["expansion"] = round(ft.expansion, 2)
        row["filing_fallback_reason"] = ft.reason
        row["label_source"] = "nse_desc_via_nse_taxonomy (unchanged; only the text was re-extracted)"
        out.append(row)
        if i % 20 == 0:
            print(f"  {i}/{len(rows)} ...", flush=True)

    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8"
    )

    before = sum(r["summary_chars"] for r in out)
    after = sum(r["filing_chars"] for r in out)
    print(f"wrote {len(out)} items to {p}")
    print(f"  upgraded to PDF text   {used_pdf}/{len(out)}")
    print(f"  kept the summary       {len(out) - used_pdf}")
    print(f"  total chars            {before} -> {after} ({after / max(before, 1):.1f}x)")
    for reason, n in reasons.most_common(6):
        print(f"    fallback: {n:4d}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
