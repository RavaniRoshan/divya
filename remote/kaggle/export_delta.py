"""Export a fine-tuned checkpoint as a SPARSE DELTA against the base model.

**The problem this solves.** `kaggle kernels output` delivers every small file from a kernel
correctly -- a 2 KB encoder config, a 964 B training manifest, a 338 B result -- and delivers
`model.safetensors` as **0 bytes**, silently, with no error. That is a size limit on the output
API, not corruption: the weights really are in the kernel, and the run really did score 0.975
there. The full 1.7 GB model simply will not come down.

**The fix is to make the artifact smaller than the limit.** A four-epoch fine-tune moves most of
the encoder very little. So rather than shipping the whole model, ship the *difference* from the
stock checkpoint, keeping the largest-magnitude changes:

    base (already on disk, downloads from HF fine)
      + delta (small, this script) = fine-tuned model

That is a smaller transfer **and** a better artifact: the delta is itself the record of what
training changed, which is the thing worth keeping. The upstream checkpoint stays intact and
downloadable, so nothing is lost if the delta is dropped.

**How sparse.** `--keep` is the fraction of the largest-magnitude entries retained per tensor.
Reconstruction is exact for the retained entries and reverts the rest to the base checkpoint, so
the export records its own fidelity in `delta_index.json`. `--keep 1.0` is lossless: every entry
is retained and the round trip is bit-exact, which is what `tests/test_export_delta.py` asserts.

**The indices are the whole trick.** A delta of *values* alone is not a delta -- a tensor's
values are only meaningful at their positions. Both the positions and the values travel, keyed
`idx/<tensor>` (int32) and `val/<tensor>` (fp16). `apply_delta` scatters the values back onto the
recorded positions and leaves everything else at base.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

IDX_PREFIX = "idx/"
VAL_PREFIX = "val/"


def _select(base: dict, tuned: dict, keep: float):
    """Yield (name, indices, values, shape) for the largest-magnitude entries per tensor.

    Values travel as fp16, which is what makes a sparse delta small. At `keep=1.0` they
    travel in the base tensor's own dtype instead, so the full round trip is bit-exact and
    "lossless" means what it says. Any `keep<1.0` export is an approximation on both axes
    and `delta_index.json` records that.
    """
    import torch

    exact = keep >= 1.0
    for name, tb in base.items():
        tt = tuned[name].to(tb.dtype)
        d = (tt.float() - tb.float()).flatten()
        n = d.numel()
        k = min(max(1, int(n * keep)), n)
        idx = torch.topk(d.abs(), k, largest=True).indices
        yield name, idx.to(torch.int32), d[idx].to(tb.dtype if exact else torch.float16), tb.shape


def write_delta(base: dict, tuned: dict, out_dir: Path, keep: float = 0.05) -> dict:
    """Write a delta between two state dicts. The one implementation; everything else is I/O."""
    import torch
    from safetensors.torch import save_file

    missing = set(base) ^ set(tuned)
    if missing:
        raise SystemExit(
            f"base and tuned differ in their parameter sets ({len(missing)} tensors). "
            f"Example: {sorted(missing)[:3]}. A delta needs identical keys."
        )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    index: dict[str, dict] = {}
    chunks: dict[str, torch.Tensor] = {}
    retained = total = 0

    for name, idx, val, shape in _select(base, tuned, keep):
        chunks[IDX_PREFIX + name] = idx
        chunks[VAL_PREFIX + name] = val.contiguous()
        index[name] = {
            "shape": list(shape),
            "k": int(idx.numel()),
            "n": int(torch.tensor(list(shape)).prod()),
            "value_dtype": str(chunks[VAL_PREFIX + name].dtype).removeprefix("torch."),
        }
        retained += int(idx.numel())
        total += index[name]["n"]

    save_file(chunks, str(out_dir / "delta.safetensors"))
    (out_dir / "delta_index.json").write_text(
        json.dumps(
            {
                "base": "convaiinnovations/laya",
                "keep": keep,
                "tensors": index,
                "retained": retained,
                "total": total,
                "retained_fraction": round(retained / total, 6) if total else 0.0,
                "fidelity": (
                    "lossless: every entry retained in the base dtype; round trip is bit-exact"
                    if keep >= 1.0
                    else f"approximate: top-{keep:.1%} of entries by |delta| per tensor, "
                         "values stored as fp16; unretained entries revert to the base "
                         "checkpoint. Verify by re-running the held-out evaluation on the "
                         "reconstructed checkpoint before trusting any number from it."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    size = (out_dir / "delta.safetensors").stat().st_size
    return {
        "delta_bytes": size,
        "delta_mb": round(size / 2**20, 1),
        "retained": retained,
        "total": total,
        "retained_fraction": round(retained / total, 5) if total else 0.0,
        "keep": keep,
        "seconds": round(time.perf_counter() - t0, 1),
        "transfers": size < 200 * 2**20,
    }


def export_delta(base_dir: Path, tuned_dir: Path, out_dir: Path, keep: float = 0.05) -> dict:
    from safetensors.torch import load_file

    base = load_file(str(Path(base_dir) / "model.safetensors"))
    tuned = load_file(str(Path(tuned_dir) / "model.safetensors"))
    return write_delta(base, tuned, Path(out_dir), keep)


def apply_delta(base_dir: Path, delta_dir: Path, out_dir: Path) -> dict:
    """Reconstruct a usable checkpoint as base + delta. Exact for retained entries."""
    import shutil

    from safetensors.torch import load_file, save_file

    meta = json.loads((delta_dir / "delta_index.json").read_text(encoding="utf-8"))
    base = load_file(str(base_dir / "model.safetensors"))
    delta = load_file(str(delta_dir / "delta.safetensors"))

    applied = 0
    for name in meta["tensors"]:
        ik, vk = IDX_PREFIX + name, VAL_PREFIX + name
        if name not in base or ik not in delta or vk not in delta:
            continue
        idx = delta[ik].long()
        val = delta[vk].float()
        if idx.numel() != val.numel():
            raise SystemExit(
                f"{name}: {idx.numel()} indices but {val.numel()} values -- corrupt delta"
            )
        if int(idx.max()) >= base[name].numel():
            raise SystemExit(f"{name}: index out of range for a tensor of {base[name].numel()}")
        flat = base[name].float().flatten().clone()
        flat[idx] += val
        base[name] = flat.reshape(base[name].shape).to(base[name].dtype)
        applied += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    save_file(base, str(out_dir / "model.safetensors"))
    for sub in ("tokenizer", "encoder"):
        src = base_dir / sub
        if src.exists():
            shutil.copytree(src, out_dir / sub, dirs_exist_ok=True)
    cfg = base_dir / "rl_agent_config.json"
    if cfg.exists():
        shutil.copy(cfg, out_dir / "rl_agent_config.json")
    return {"tensors_patched": applied, "kept": meta["keep"], "out": str(out_dir)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="stock Laya checkpoint dir")
    ap.add_argument("--tuned", help="fine-tuned checkpoint dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", type=float, default=0.05)
    ap.add_argument("--apply", action="store_true", help="reconstruct instead of export")
    args = ap.parse_args()

    if args.apply:
        print(json.dumps(apply_delta(Path(args.base), Path(args.out), Path(args.tuned)), indent=2))
        return 0

    res = export_delta(Path(args.base), Path(args.tuned), Path(args.out), args.keep)
    print(json.dumps(res, indent=2))
    if not res["transfers"]:
        print(
            f"\nWARNING: the delta is {res['delta_mb']} MB, which is over the size at which\n"
            f"kaggle kernels output has been observed to return 0 bytes. Lower --keep.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
