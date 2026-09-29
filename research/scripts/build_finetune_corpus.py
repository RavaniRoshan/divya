"""Build a labelled fine-tuning corpus from live NSE announcements.

The research in `docs/research/STATE_OF_THE_ART.md` named data as the binding constraint:
there is no public NSE/BSE announcement event-classification corpus anywhere, so one has to
be made. The label is NSE's own `desc`, mapped through the explicit table in
`src/divya/data/nse_taxonomy.py` — a human-curated publication rather than our annotation.

Splits are fixed here and never revisited:

    train / dev    scraped, labelled, and shuffled with a fixed seed
    held-out       the 120 announcements in evals/datasets/nse_v5_eval_set.jsonl, EXCLUDED
                   from this file's output entirely

The held-out set is excluded **by id, not by convention**. A leak would make the stop rule in
`docs/loop/STOP_RULE.md` meaningless, and a meaningless stop rule is worse than none.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from divya.data.nse import NseAnnouncements
from divya.data.nse_taxonomy import UNRESOLVED, classify

HELDOUT = Path("evals/datasets/nse_v5_eval_set.jsonl")


def month_window(end: date, months_back: int) -> tuple[date, date]:
    """The calendar month `months_back` months before `end`'s month."""
    y, m = end.year, end.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    start = date(y, m, 1)
    last_day = (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
    return start, min(last_day, end)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=5)
    ap.add_argument("--end", default="2026-09-28")
    ap.add_argument("--out", default="evals/datasets/finetune_corpus.jsonl")
    ap.add_argument("--dev-fraction", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=20260929)
    args = ap.parse_args()

    held: set[str] = set()
    if HELDOUT.exists():
        for line in HELDOUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                held.add(json.loads(line)["id"])
        print(f"excluding {len(held)} held-out ids from training")

    end = date.fromisoformat(args.end)
    src = NseAnnouncements()
    rows: list[dict] = []
    seen: set[str] = set()

    for back in range(args.months):
        start, stop = month_window(end, back)
        try:
            anns, truncated = src.fetch(start, stop, limit=6000)
        except Exception as exc:
            print(f"  {start}..{stop}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        added = 0
        for a in anns:
            if a.seq_id in seen or a.seq_id in held:
                continue
            label = classify(a.desc)
            if label == UNRESOLVED or not a.text or len(a.text) < 40:
                continue
            seen.add(a.seq_id)
            rows.append(
                {
                    "id": a.seq_id, "symbol": a.symbol, "industry": a.industry,
                    "nse_desc": a.desc, "label": label, "text": a.text,
                    "pdf_url": a.pdf_url, "announced_at": a.announced_at,
                }
            )
            added += 1
        note = " (TRUNCATED - raise --months-limit or narrow the window)" if truncated else ""
        print(f"  {start}..{stop}: {len(anns)} fetched, {added} usable{note}", flush=True)

    rng = random.Random(args.seed)
    rng.shuffle(rows)
    n_dev = int(len(rows) * args.dev_fraction)
    dev, train = rows[:n_dev], rows[n_dev:]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in train:
            fh.write(json.dumps({**r, "split": "train"}, ensure_ascii=False) + "\n")
        for r in dev:
            fh.write(json.dumps({**r, "split": "dev"}, ensure_ascii=False) + "\n")

    c = Counter(r["label"] for r in rows)
    print(f"\nwrote {len(train)} train + {len(dev)} dev to {out}")
    print(f"total {len(rows)} labelled examples over {args.months} month(s)")
    for k, v in c.most_common():
        print(f"  {k:<20} {v}")
    rare = sorted(k for k, v in c.items() if v < 30)
    if rare:
        print(f"\n  WARNING: classes with <30 examples (a fine-tune will not learn these): {rare}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
