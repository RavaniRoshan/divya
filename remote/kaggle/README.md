# Remote training — Kaggle GPU T4 ×2

All heavy compute for Divya runs here, never on the development machine. See
`docs/loop/DECISIONS.md` D-027 (why a local fine-tune is not viable) and D-028 (what runs
where).

## Layout

| file | purpose |
|---|---|
| `finetune_corpus.jsonl` | 5,092 train + 1,272 dev, labelled from NSE's own `desc`. The 120 held-out ids are **excluded by id** |
| `nse_v5_eval_set.jsonl` | the 120 held-out. Evaluated **once**, at the end |
| `finetune_laya.py` | the RLCD trainer, adapted from Laya's own 2×T4 reference recipe |
| `divya-finetune.ipynb` | the kernel: setup → locate → baseline → train → held-out eval → export |
| `dataset-metadata.json` | for `kaggle datasets create` |

## Run it

```bash
cd kernel
kaggle kernels status ravaniroshan/divya-laya-finetune
kaggle kernels output  ravaniroshan/divya-laya-finetune   # pulls the log
```

The output notebook writes `HELD_OUT_RESULT.json` at the kernel root.

## What the run decides

`docs/loop/STOP_RULE.md`, pre-committed before any training:

> If a fine-tuned Laya does not reach **≥ 0.65 macro-F1 on the 120 held-out announcements**,
> the typed-decision approach is refuted for this domain.

Baselines to beat: zero-shot macro-F1 **0.147** on dev, accuracy **0.513**; and **0.433**
accuracy on the held-out 120 through the Router.

## The objective

RLCD (policy gradient against a proper scoring rule), reproduced from the reference rather than
substituted with cross-entropy — the calibrated probability is the product, and a softmax
trained with CE is not that. Temperature is fitted afterwards on a slice held out of training.

## What it is not

This bundle does not claim the reference recipe was reproduced exactly: single process with
gradient accumulation, not DDP. Effective batch 64 matches. If the run falls short, the honest
reading has to allow that it was not a faithful reproduction.
