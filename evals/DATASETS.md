# Datasets

Two kinds. One is ours and ships; one is the exchange's and does not.

## 1. Shipped: the synthetic evaluation set

`evals/datasets/event_triage_v1.jsonl` — 210 items, authored for this project, freely
redistributable. Deterministic (seed 20260928), four strata (`clear` 90, `ambiguous` 45,
`noisy` 45, `adversarial` 30), all seven event classes covered.

Every row is stamped `is_synthetic_text: true` **in the data**, not only in the docs, so it
cannot be mistaken for market data by any code path that forgets to check.

```json
{
  "id": "clear_0000",
  "stratum": "clear",
  "is_synthetic_text": true,
  "sector": "banking",
  "company": "HDFC Bank",
  "content": "HDFC Bank Limited has informed the Exchange about its quarterly financial results...",
  "labels": { "event_type": "earnings_result", "is_material": true,
              "materiality": 3, "direction": "neutral_or_favourable" },
  "ambiguous_alternatives": [],
  "annotator_confidence": 0.95,
  "is_adversarial": false
}
```

Regenerate: `make fixtures` (`evals/make_dataset.py`).

## 2. Not shipped: real NSE announcements

Scraped from `www.nseindia.com/api/corporate-announcements`. **Exchange-proprietary, and no
reuse grant was located** — fine to fetch at runtime, not fine to redistribute
(`docs/loop/BLOCKERS.md` B-002). Not in version control; `.gitignore` prevents a re-add.

Rebuild locally — this is the better reproducibility story anyway, because a frozen copy
silently goes stale while the live feed does not:

```bash
divya index --days 5                                    # -> data/store/
PYTHONPATH=src .venv/bin/python \
  research/scripts/build_finetune_corpus.py --months 5 # -> evals/datasets/finetune_corpus.jsonl
```

### Schema

`evals/datasets/nse_announcements_v1.jsonl` — one announcement per row:

| field | meaning |
|---|---|
| `id` | NSE's own `seq_id`; the dedup and held-out-exclusion key |
| `symbol`, `company`, `industry` | as published |
| `nse_desc` | NSE's own filing class — **this is the label** |
| `content` | the filing text (summary, or full PDF text after `divya filings`) |
| `pdf_url` | the source document |
| `labels.event_type` | `nse_desc` mapped through `src/divya/data/nse_taxonomy.py` |
| `is_measurable` | false for the ~82% of the feed that is process, not events |

`evals/datasets/finetune_corpus.jsonl` — labelled, split into `train` / `dev`. **The 120 ids in
`nse_v5_eval_set.jsonl` are excluded from it by id**, which is what makes the stop rule in
`docs/loop/STOP_RULE.md` mean anything.

### Why the label is a taxonomy and not the truth

`nse_desc` is a real, published, human-curated filing classification — much better than
anything we could annotate, and the fine-tuned model reaching 0.975 against it is a real
result. It is still a statement about *how the exchange files a document*, not about what
happened to the business. Every report says so.

### What the mapping gets wrong

`Trading Window` was initially mapped to `regulatory_action`. A trading-window closure is routine
SEBI PIT compliance, not a penalty or sanction, and it is the **second-largest class in the
feed** — the error would have contaminated 47% of the evaluation population. Class-frequency
tables are the cheapest defence against a plausible-looking wrong taxonomy.
