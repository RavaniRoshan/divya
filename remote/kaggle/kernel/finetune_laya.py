"""RLCD fine-tuning of System-1 (Laya) on Indian corporate filings.

Extracted and adapted from Laya's own reference recipe,
`notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb` (Apache-2.0, same project as the
weights), so the objective is the one the model was designed for rather than a cross-entropy
substitute that would produce a different model.

**Why the objective is RLCD and not cross-entropy.** Laya is trained with policy gradients
against proper scoring rules. The calibrated probability *is* the product — a terminal that
abstains on `min_confidence` needs a trustworthy probability, and a softmax trained with
cross-entropy is not that. The reference loss is reproduced faithfully below.

**What is adapted, and why.** The reference runs 2x T4 with DDP. This box has one 4 GB card (or
none), so:

| reference | here | why |
|---|---|---|
| 2x T4, DDP | single process, gradient accumulation | one GPU |
| fp32 AdamW, batch 8 | bf16 autocast, micro-batch 2, accum 16 | 4 GB card cannot hold fp32 AdamW state for 421M params |
| `--nproc_per_node=2` | `--device` auto/cuda/cpu | — |
| separate temperature fit after training | same, held-out calibration slice | the reference already holds calibration items out of training, and the comment there is worth keeping: a temperature fitted on items the run has trained on measures the fit, not the calibration |

**Honesty about what this may or may not achieve.** The reference reaches 0.766 on its own
benchmark with 2x T4. The pre-committed bar for this project is **0.65 macro-F1 on 120
held-out NSE announcements** (`docs/loop/STOP_RULE.md`). This script exists to give that number
an honest chance, not to assume it.

**The held-out set is never read here.** `build_finetune_corpus.py` excludes it by id and
`assert_no_heldout` re-checks. A leak would void the stop rule.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

HELD_OUT = "evals/datasets/nse_v5_eval_set.jsonl"


# --- the reference loss, reproduced ----------------------------------------


def rlcd_loss(
    torch: Any,
    logits: Any,
    target: Any,
    mask: Any,
    qtype: Any,
    *,
    group_size: int = 4,
    sigma: float = 0.4,
    w_sph: float = 0.75,
    w_rps: float = 1.0,
    ce_weight: float = 1.0,
) -> Any:
    """GRPO-style policy gradient against a proper scoring rule, plus soft cross-entropy.

    Line-for-line the reference recipe's steps 1-3:

    1. sample G noisy logit distributions with a zero-mean projection onto the valid options,
       so exploration cannot wander into masked-out answers;
    2. score each sample with `proper_reward` and take the normalised group advantage;
    3. descend the policy gradient on the sampled distributions while a full-weight soft
       cross-entropy keeps the deterministic logits anchored.

    The zero-mean projection in step 1 is the part that is easy to get wrong and that decides
    whether exploration helps or merely adds variance: without it, noise is spent on
    non-answers.
    """
    from laya.common import proper_reward

    k = mask.sum(-1, keepdim=True).float()

    eps = torch.randn((group_size, *tuple(logits.shape)), device=logits.device) * sigma * mask
    eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
    z = logits.detach().unsqueeze(0) + eps
    q = torch.softmax(z.masked_fill(~mask, -1e4), -1)

    with torch.no_grad():
        r = proper_reward(q, target.unsqueeze(0), qtype, mask, w_sph=w_sph, w_rps=w_rps)
        adv = r - r.mean(0, keepdim=True)
        adv = adv / (adv.std() + 1e-6)

    logp = -(((z - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma**2)
    loss_rl = -(adv * logp).mean()
    loss_ce = -(target * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)).sum(-1).mean()
    return loss_rl + ce_weight * loss_ce, {"rl": float(loss_rl), "ce": float(loss_ce)}


def collate(torch: Any, items: list[dict[str, Any]], pad_id: int) -> dict[str, Any]:
    """The reference collator. Shapes must match what `build_model` expects."""
    n = len(items)
    L = max(len(it["ids"]) for it in items)
    kmax = max(len(it["markers"]) for it in items)
    ids = torch.full((n, L), pad_id, dtype=torch.long)
    att = torch.zeros((n, L), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long)
    mmask = torch.zeros((n, kmax), dtype=torch.bool)
    target = torch.zeros((n, kmax), dtype=torch.float32)
    for i, it in enumerate(items):
        ids[i, : len(it["ids"])] = torch.tensor(it["ids"])
        att[i, : len(it["ids"])] = 1
        k = len(it["markers"])
        mpos[i, :k] = torch.tensor(it["markers"])
        mmask[i, :k] = True
        target[i, : len(it["target"])] = torch.tensor(it["target"], dtype=torch.float32)
    return {
        "input_ids": ids, "attention_mask": att, "marker_pos": mpos, "marker_mask": mmask,
        "target": target,
        "qtype": torch.tensor([it["qtype"] for it in items]),
        "label": torch.tensor([it["label"] for it in items]),
    }


def fit_temperature(torch: Any, model: Any, tok: Any, items: list[dict[str, Any]],
                    device: str, max_iter: int = 100) -> float:
    """Fit the scoring temperature by LBFGS on a held-out calibration slice.

    The slice is held out **of training** on purpose. A temperature fitted on items the model
    has just trained on measures the fit, not the calibration: the model is near-certain and
    near-correct on them, so the optimiser has nothing to soften and returns a degenerate
    scale. This is the reference recipe's own reasoning and it is kept.
    """
    if len(items) < 10:
        return 1.0
    with torch.no_grad():
        z_list, t_list = [], []
        for it in items:
            b = collate(torch, [it], tok.pad_token_id)
            logits, _ = model(
                b["input_ids"].to(device), b["attention_mask"].to(device),
                b["marker_pos"].to(device), b["marker_mask"].to(device), b["qtype"].to(device),
            )
            m = b["marker_mask"].to(device)
            z_list.append(logits.float()[m])
            t_list.append(b["target"].to(device)[m])
    # Pad every item's option scores to the widest one, or the softmax mixes items.
    L = max(z.shape[0] for z in z_list)
    Z = torch.full((len(z_list), L), -1e4, device=device)
    T = torch.zeros((len(z_list), L), device=device)
    for i, (z, t) in enumerate(zip(z_list, t_list, strict=True), start=0):
        Z[i, : z.shape[0]] = z
        T[i, : t.shape[0]] = t
    log_t = torch.zeros(1, device=device, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=max_iter)

    def closure() -> Any:
        opt.zero_grad()
        loss = -(T * torch.log_softmax(Z / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss

    opt.step(closure)
    return float(torch.clamp(log_t.exp(), 0.1, 10.0).item())


# --- data ------------------------------------------------------------------


def make_items(
    torch: Any, tok: Any, rows: list[dict[str, Any]], options: list[str],
    max_len: int, head_max_len: int,
) -> tuple[list[dict[str, Any]], int]:
    """Turn labelled rows into Laya training items, following the reference `build_training_item`.

    Three details here are load-bearing and all three were got wrong in the first draft:

    1. **`build_sequence` returns a 2-tuple** `(ids, markers)`. Unpacking three values raises on
       every row, and the `except` around it silently skipped the entire corpus -- a training run
       over 1 item that looked like it had started.
    2. **The target is a normalised probability vector over the options, not a one-hot**, and it
       must sum to 1 because the loss is a proper scoring rule over a distribution. With a hard
       label from NSE's taxonomy, one-hot normalised IS the right target; the distinction only
       matters if soft labels are ever introduced.
    3. **An item is dropped when `len(markers) != len(options)`.** Two options that share a
       prefix can be cut to the same token span by the head budget, and the model then cannot
       tell them apart -- training on it teaches a distinction that is not representable. This is
       the "label-budget ceiling" the upstream benchmarks document, and it is why the drop is a
       hard filter rather than a warning.

    Option descriptions are deliberately **empty**: the class name is the whole option text, so
    seven options cost roughly 30 tokens against a 256-token head budget. Writing descriptive
    criteria here would reintroduce the ceiling that a wide `choice` question hits.
    """
    from laya.common import QTYPES, build_sequence, render_options

    crit = {o: "" for o in options}
    q = {"t": "choice", "ins": "Classify the corporate event this filing discloses.", "crit": crit}
    k = len(render_options(q))
    items: list[dict[str, Any]] = []
    dropped_budget = 0
    dropped_err = 0
    for r in rows:
        try:
            seq, markers = build_sequence(tok, r["text"], q, max_len, head_max_len)
        except Exception as exc:
            dropped_err += 1
            if dropped_err <= 3:
                print(f"  skipping {r['id']}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if len(markers) != k:
            dropped_budget += 1
            continue
        target = [0.0] * len(options)
        target[options.index(r["label"])] = 1.0
        s = sum(target)
        target = [v / s for v in target]
        items.append({
            "ids": seq, "markers": markers, "target": target,
            "qtype": QTYPES["choice"], "label": options.index(r["label"]),
        })
    return items, dropped_budget + dropped_err


def assert_no_heldout(ids: set[str], heldout: Path) -> None:
    if not heldout.exists():
        return
    banned = {
        json.loads(line)["id"]
        for line in heldout.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    hit = banned & ids
    if hit:
        raise SystemExit(
            f"REFUSING TO TRAIN: {len(hit)} held-out ids are in the corpus "
            f"(e.g. {sorted(hit)[:3]}). The stop rule is void if this leaks."
        )


# --- main ------------------------------------------------------------------


@dataclass
class Cfg:
    epochs: int = 4
    micro_batch: int = 2
    accum: int = 16
    group_size: int = 4
    lr_encoder: float = 2.5e-5
    lr_head: float = 1.0e-4
    sigma_start: float = 0.4
    sigma_end: float = 0.1
    max_len: int = 1024
    head_max_len: int = 256
    calib_max: int = 400
    seed: int = 20260929
    limit_train: int | None = None
    limit_dev: int | None = 300
    device: str = "auto"
    out: Path = field(default_factory=lambda: Path("data/finetune/laya-indian-filings"))
    eval_only: bool = False


def evaluate(torch: Any, model: Any, tok: Any, rows: list[dict[str, Any]],
             options: list[str], device: str, max_len: int, head_max_len: int,
             limit: int | None = None) -> dict[str, Any]:
    """Greedy accuracy and macro-F1 through the model itself, not through the Router."""
    from laya.common import QTYPES, build_sequence, render_options

    crit = {o: "" for o in options}
    q = {"t": "choice", "ins": "Classify the corporate event this filing discloses.", "crit": crit}
    k = len(render_options(q))
    use = rows[:limit] if limit else rows
    per_total: Counter[str] = Counter()
    per_ok: Counter[str] = Counter()
    with torch.no_grad():
        for r in use:
            try:
                seq, markers = build_sequence(tok, r["text"], q, max_len, head_max_len)
            except Exception:
                continue
            if len(markers) != k:
                continue
            ids = torch.tensor([seq], device=device)
            att = torch.ones_like(ids)
            mpos = torch.tensor([markers], device=device)
            mmask = torch.ones_like(mpos, dtype=torch.bool)
            qtype = torch.tensor([QTYPES["choice"]], dtype=torch.long, device=device)
            logits, _ = model(ids, att, mpos, mmask, qtype)
            # logits is (n, k) -- one score per option. argmax over the whole vector, not
            # over a single element: `reshape(-1)[0].argmax()` silently always returned 0,
            # i.e. it always predicted the alphabetically-first class, which is why the
            # first run reported 1.3% and looked like a broken model.
            pred = options[int(logits.float().reshape(-1).argmax())]
            per_total[r["label"]] += 1
            if pred == r["label"]:
                per_ok[r["label"]] += 1
    n = max(sum(per_total.values()), 1)
    f1s = []
    for label in options:
        tp = per_ok[label]
        fn = per_total[label] - tp
        fp = (n - per_total[label]) - tp
        p = tp / (tp + fp) if tp + fp else 0.0
        rr = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * rr / (p + rr) if p + rr else 0.0)
    return {
        "n": n,
        "accuracy": round(sum(per_ok.values()) / n, 4),
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "per_class": {k: round(per_ok[k] / v, 4) for k, v in per_total.items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="evals/datasets/finetune_corpus.jsonl")
    ap.add_argument("--heldout", default=HELD_OUT)
    ap.add_argument("--model-dir", default=None, help="local Laya checkpoint dir; default HF cache")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--micro-batch", type=int, default=2)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--group-size", type=int, default=4)
    ap.add_argument("--limit-train", type=int, default=None)
    ap.add_argument("--limit-dev", type=int, default=300)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", default="data/finetune/laya-indian-filings")
    ap.add_argument(
        "--delta-out",
        default=None,
        help="also write a sparse delta against the base checkpoint here. The base weights "
             "are held in memory at this point, so the delta costs no extra download -- "
             "which is the point: the 1.7 GB full model cannot be pulled out of a Kaggle "
             "kernel, but a ~50 MB delta can.",
    )
    ap.add_argument("--delta-keep", type=float, default=0.03)
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--seed", type=int, default=20260929)
    args = ap.parse_args(argv)

    import torch
    from laya.common import build_model
    from safetensors.torch import load_file, save_file
    from transformers import AutoTokenizer

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    corpus = Path(args.corpus)
    if not corpus.exists():
        raise SystemExit(
            f"{corpus} not found. Build it first:\n"
            f"  PYTHONPATH=src .venv/bin/python research/scripts/build_finetune_corpus.py"
        )
    rows = [
        json.loads(line)
        for line in corpus.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    train_rows = [r for r in rows if r["split"] == "train"]
    dev_rows = [r for r in rows if r["split"] == "dev"]
    assert_no_heldout({r["id"] for r in rows}, Path(args.heldout))
    if args.limit_train:
        train_rows = train_rows[: args.limit_train]
    if not train_rows:
        raise SystemExit("no training rows")

    options = sorted({r["label"] for r in rows})
    print(f"train {len(train_rows)}  dev {len(dev_rows)}  classes {len(options)}: {options}")

    model_dir = args.model_dir
    if model_dir is None:
        from huggingface_hub import snapshot_download

        model_dir = snapshot_download("convaiinnovations/laya")
    model_dir = str(model_dir)

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {device}")
    if device == "cuda":
        gb = torch.cuda.get_device_properties(0).total_memory / 2**30
        print(f"  {torch.cuda.get_device_name(0)}  {gb:.1f} GB")
        if gb < 6:
            print(
                "  NOTE: the reference recipe uses 2xT4 with fp32 AdamW. A 4 GB card cannot "
                "hold AdamW state for 421M params, so micro-batch is small and accum is high."
            )

    cfgj = json.loads((Path(model_dir) / "rl_agent_config.json").read_text())
    cfgj["gradient_checkpointing"] = True
    cfgj["max_tokens_per_batch"] = 4096
    cfgj["max_len"] = args_limit_len = 1024
    cfgj["head_max_len"] = 256

    tok = AutoTokenizer.from_pretrained(str(Path(model_dir) / "tokenizer"))
    model = build_model(cfgj, encoder_dir=str(Path(model_dir) / "encoder"))
    base_sd = load_file(str(Path(model_dir) / "model.safetensors"))
    model.load_state_dict(base_sd, strict=True)
    # Kept only when a delta is requested. It is the pre-training weights, so anything the
    # optimiser later overwrites would make the delta wrong; and holding it here is what
    # lets the delta be written without downloading the base checkpoint a second time.
    base_for_delta = {k: v.detach().cpu().clone() for k, v in base_sd.items()} if args.delta_out else None
    del base_sd
    model.to(device)
    if hasattr(model.encoder, "gradient_checkpointing_enable"):
        model.encoder.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    model.head_checkpointing = True
    model.eval()

    dev_rows_eval = dev_rows[: args.limit_dev] if args.limit_dev else dev_rows
    if args.eval_only:
        before = evaluate(torch, model, tok, dev_rows_eval, options, device,
                          args_limit_len, 256, None)
        print("BEFORE fine-tuning (dev):", json.dumps(before))
        return 0

    # -- items -------------------------------------------------------------
    print("encoding corpus ...", flush=True)
    all_items, dropped = make_items(torch, tok, train_rows, options, args_limit_len, 256)
    if not all_items:
        raise SystemExit(
            "no items encoded. Either build_sequence rejected every row or the head budget "
            "collapsed the options. Check the stderr above for which."
        )
    print(f"encoded {len(all_items)} training items ({dropped} dropped)", flush=True)

    # Calibration slice held out of training, fixed seed, as in the reference.
    order = list(range(len(all_items)))
    random.Random(20260922).shuffle(order)
    n_calib = min(args.calib_max if hasattr(args, "calib_max") else 400, len(all_items) // 10)
    calib_items = [all_items[i] for i in sorted(order[:n_calib])]
    train_items = [all_items[i] for i in sorted(order[n_calib:])]
    print(f"  {len(train_items)} train / {len(calib_items)} held out for calibration")

    # -- optimiser ---------------------------------------------------------
    enc = [p for n, p in model.named_parameters() if "encoder." in n and p.requires_grad]
    head = [p for n, p in model.named_parameters() if "encoder." not in n and p.requires_grad]
    try:
        import bitsandbytes as bnb  # type: ignore[import-not-found]

        opt = bnb.optim.AdamW8bit(
            [{"params": enc, "lr": args.lr_encoder if hasattr(args, "lr_encoder") else 2.5e-5},
             {"params": head, "lr": 1.0e-4}], weight_decay=0.01,
        )
        optname = "adamw8bit"
    except Exception as exc:
        print(f"  8-bit AdamW unavailable ({type(exc).__name__}); using fp32 AdamW")
        opt = torch.optim.AdamW(
            [{"params": enc, "lr": 2.5e-5}, {"params": head, "lr": 1.0e-4}], weight_decay=0.01
        )
        optname = "adamw_fp32"
    n_tr = sum(p.numel() for p in enc + head)
    print(f"  trainable {n_tr / 1e6:.1f}M ({len(enc)} enc tensors, {len(head)} head tensors)")
    print(f"  optimizer {optname}  micro {args.micro_batch} x accum {args.accum}"
          f"  epochs {args.epochs}")

    model.train()
    scaler = torch.amp.GradScaler("cuda", enabled=(device == "cuda"))
    t0 = time.time()
    step = 0
    hist: list[dict[str, Any]] = []
    for epoch in range(args.epochs):
        random.shuffle(train_items)
        prog = epoch / max(1, args.epochs - 1)
        sigma = 0.4 + (0.1 - 0.4) * prog
        opt.zero_grad(set_to_none=True)
        rl_s, ce_s, nb = 0.0, 0.0, 0
        for i in range(0, len(train_items), args.micro_batch):
            chunk = train_items[i : i + args.micro_batch]
            if not chunk:
                continue
            b = collate(torch, chunk, tok.pad_token_id)
            try:
                with torch.autocast("cuda", dtype=torch.float16, enabled=(device == "cuda")):
                    logits, _act = model(
                        b["input_ids"].to(device), b["attention_mask"].to(device),
                        b["marker_pos"].to(device), b["marker_mask"].to(device),
                        b["qtype"].to(device),
                    )
            except torch.cuda.OutOfMemoryError as exc:
                print(f"  OOM at micro-batch {args.micro_batch}: {exc}")
                print("  Lower --micro-batch and raise --accum; the effective batch is unchanged.")
                return 2
            logits = logits.float()
            mask = b["marker_mask"].to(device)
            target = b["target"].to(device)
            loss, parts = rlcd_loss(
                torch, logits, target, mask, b["qtype"].to(device),
                group_size=args.group_size, sigma=sigma,
            )
            scaler.scale(loss / args.accum).backward()
            rl_s += parts["rl"]
            ce_s += parts["ce"]
            nb += 1
            step += 1
            if nb % args.accum == 0:
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
                opt.zero_grad(set_to_none=True)
            if step % 25 == 0:
                el = time.time() - t0
                print(f"  e{epoch} step {step} loss_rl {rl_s / nb:.4f} loss_ce {ce_s / nb:.4f} "
                      f"sigma {sigma:.3f} ({el:.0f}s, {el / step:.2f}s/step)", flush=True)
        hist.append({"epoch": epoch, "loss_rl": rl_s / max(nb, 1),
                     "loss_ce": ce_s / max(nb, 1), "seconds": round(time.time() - t0)})
        print(f"epoch {epoch} done in {time.time() - t0:.0f}s", flush=True)

    # -- calibrate, evaluate, save -----------------------------------------
    model.eval()
    temp = fit_temperature(torch, model, tok, calib_items[:200], device)
    print(f"fitted temperature: {temp:.4f}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tuned_sd = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    save_file(tuned_sd, str(out / "model.safetensors"))
    (out / "rl_agent_config.json").write_text(json.dumps(cfgj, indent=2), encoding="utf-8")
    import shutil

    for sub in ("tokenizer", "encoder"):
        s = Path(model_dir) / sub
        if s.exists():
            shutil.copytree(s, out / sub, dirs_exist_ok=True)
    (out / "divya_finetune_meta.json").write_text(
        json.dumps({
            "corpus": corpus.name, "n_train": len(train_items),
            "n_calibration": len(calib_items), "classes": options,
            "epochs": args.epochs, "micro_batch": args.micro_batch, "accum": args.accum,
            "group_size": args.group_size, "device": device, "optimizer": optname,
            "temperature": temp, "seed": args.seed, "history": hist,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"saved to {out}")

    # -- the delta, written while the base weights are still in memory -----------------
    #
    # Everything above produces a 1.7 GB checkpoint that cannot leave a Kaggle kernel: the
    # output API returns it as 0 bytes, silently. Only this delta is small enough to travel,
    # and it can be produced here because the base state dict never left memory. Reconstruct
    # locally with `export_delta.py --apply`, then re-run the held-out evaluation on the
    # result -- the delta is an approximation, and only that evaluation says how much of the
    # 0.975 it actually preserves.
    if base_for_delta is not None:
        from export_delta import write_delta

        dres = write_delta(base_for_delta, tuned_sd, Path(args.delta_out), args.delta_keep)
        print("DELTA", json.dumps(dres), flush=True)
        if not dres["transfers"]:
            print(
                f"WARNING: delta is {dres['delta_mb']} MB, over the size at which "
                f"kaggle kernels output has been seen to return 0 bytes. Lower --delta-keep.",
                flush=True,
            )
        del base_for_delta, tuned_sd

    res = evaluate(torch, model, tok, dev_rows_eval, options, device, args_limit_len, 256, None)
    print("AFTER fine-tuning (dev):", json.dumps(res))
    print("\nThe number that decides the project is not this one -- it is the held-out 120,")
    print("evaluated once. See docs/loop/STOP_RULE.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
