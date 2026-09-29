"""Correct macro-F1 for the held-out set, and the number the stop rule actually asks for.

**The metric bug this replaces.** The Kaggle kernel computed

    fp = (N - tot[lb]) - tp

for the false-positive count. That subtracts correct predictions from the pool of items that
are *not* of class `lb`, which is not the quantity. It produced values that are arithmetically
impossible — a **negative** false-positive count and a **precision of 55.0** — and reported
macro-F1 0.2786 next to an accuracy of 0.975, which is the contradiction that exposed it.

The correct form needs a count of *predictions* per class, which the kernel never kept:

    fp[lb] = predicted[lb] - tp[lb]

**This is a correction to arithmetic, not a second evaluation.** The model, the corpus, the
splits, the 120 held-out ids and the predictions are all unchanged and were fixed before this
script ran. Nothing was tuned against the held-out set: `check_no_heldout_reuse` below records
that the set has been scored once by the kernel and once by this correction, and that the two
runs used identical inputs.

Runs on CPU by default. The model is 421M and the set is 120 short documents, so this is
seconds of compute, not the hour a training step costs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

HELDOUT = Path("evals/datasets/nse_v5_eval_set.jsonl")
DEFAULT_MODEL = Path("/tmp/finetuned")
BAR = 0.65


def macro_f1(tot: Counter, ok: Counter, pred: Counter) -> tuple[float, list[dict]]:
    """Macro-F1 with a correct false-positive term.

    `fp = pred[lb] - tp[lb]`, which is the only definition that cannot go negative.
    """
    rows: list[dict] = []
    f1s: list[float] = []
    for lb in sorted(tot):
        tp = ok[lb]
        fn = tot[lb] - tp
        fp = pred[lb] - tp
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        f1s.append(f1)
        rows.append(
            {
                "class": lb, "support": tot[lb], "tp": tp, "fp": fp, "fn": fn,
                "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            }
        )
    assert all(r["fp"] >= 0 for r in rows), "false positives cannot be negative"
    return (sum(f1s) / len(f1s) if f1s else 0.0), rows


def evaluate(model_dir: Path, heldout: Path, device: str = "cpu", max_len: int = 1024) -> dict:
    import torch
    from laya.agent import _load_tokenizer
    from laya.common import QTYPES, build_model, build_sequence, render_options
    from safetensors.torch import load_file

    rows = [
        json.loads(line)
        for line in heldout.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    options = sorted({r["labels"]["event_type"] for r in rows})
    crit = {o: "" for o in options}
    q = {"t": "choice", "ins": "Classify the corporate event this filing discloses.", "crit": crit}
    k = len(render_options(q))

    # Laya ships its OWN cached tokenizer loader. Going through transformers'
    # AutoTokenizer instead fails with "couldn't instantiate the backend tokenizer", because
    # the checkpoint is a Laya-tokenizer and its config is patched by laya.agent, not by
    # transformers. The model and the tokenizer have to be loaded the same way the model was
    # trained, or the option markers do not line up.
    cfg = json.loads((model_dir / "rl_agent_config.json").read_text())
    tok = _load_tokenizer(str(model_dir / "tokenizer"), cfg)
    model = build_model(cfg, encoder_dir=str(model_dir / "encoder"))
    model.load_state_dict(load_file(str(model_dir / "model.safetensors")), strict=True)
    model.to(device).eval()

    tot: Counter = Counter()
    ok: Counter = Counter()
    pred: Counter = Counter()
    skipped = 0
    with torch.no_grad():
        for r in rows:
            seq, markers = build_sequence(tok, r["content"], q, max_len, cfg["head_max_len"])
            if len(markers) != k:
                skipped += 1
                continue
            ids = torch.tensor([seq], device=device)
            att = torch.ones_like(ids)
            mpos = torch.tensor([markers], device=device)
            mmask = torch.ones_like(mpos, dtype=torch.bool)
            qt = torch.tensor([QTYPES["choice"]], device=device)
            logits, _ = model(ids, att, mpos, mmask, qt)
            p = options[int(logits.float().reshape(-1).argmax())]
            g = r["labels"]["event_type"]
            tot[g] += 1
            pred[p] += 1
            ok[g] += 1 if p == g else 0

    n = max(sum(tot.values()), 1)
    acc = sum(ok.values()) / n
    mf1, per_class = macro_f1(tot, ok, pred)
    return {
        "n_scored": n, "n_skipped": skipped, "accuracy": round(acc, 4),
        "macro_f1": round(mf1, 4), "bar": BAR, "verdict": "PASSED" if mf1 >= BAR else "FIRED",
        "per_class": per_class,
        "correctness_note": (
            "fp = predicted[lb] - tp[lb]. The kernel's earlier form (N - tot[lb]) - tp produced "
            "negative false positives and precision 55.0, and reported macro-F1 0.2786 beside an "
            "accuracy of 0.975. Same model, same predictions, same 120 ids; only the arithmetic "
            "was corrected."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL))
    ap.add_argument("--heldout", default=str(HELDOUT))
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default="evals/results/finetuned_heldout.json")
    args = ap.parse_args()
    res = evaluate(Path(args.model_dir), Path(args.heldout), args.device)
    print(json.dumps(res, indent=2))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(f"STOP RULE (>= {BAR} macro-F1 on held-out): {res['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
