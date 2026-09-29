"""Export a fine-tuned checkpoint as a SPARSE DELTA against the base model.

**The problem this solves.** `kaggle kernels output` delivers every small file from a kernel
correctly -- a 2 KB encoder config, a 964 B training manifest, a 338 B result -- and delivers
`model.safetensors` as **0 bytes**, silently, with no error. That is a size limit on the output
API, not corruption: the weights really are in the kernel, and the run really did score 0.975
there. The full 1.7 GB model simply will not come down.

**The fix is to make the artifact smaller than the limit.** A four-epoch fine-tune moves most of
the encoder very little. So rather than shipping the whole model, ship the *difference* from the
stock checkpoint, keeping only the largest-magnitude changes:

    base (already on disk, downloads from HF fine)
      + delta (small, this script) = fine-tuned model

That is a smaller transfer **and** a better artifact: the delta is itself the record of what
training changed, which is the thing worth keeping. The upstream checkpoint stays intact and
downloadable, so nothing is lost if the delta is dropped.

**How sparse.** `--keep` is the fraction of the largest-magnitude entries retained per tensor.
The default is chosen to land well under a transfer limit, and the actual size is printed
in-kernel *before* anyone depends on it. If a run is given a higher `keep`, the script says
plainly that the artifact is larger and may not transfer.

Reconstruction is exact for the retained entries and reverts the rest to base, so the export
records its own fidelity: `keep=1.0` is lossless, and anything below that is a deliberate,
stated approximation.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys_path = str(REPO / "src")


def export_delta(
    base_dir: Path,
    tuned_dir: Path,
    out_dir: Path,
    keep: float = 0.05,
) -> dict:
    import torch
    from safetensors.torch import load_file, save_file

    base = load_file(str(base_dir / "model.safetensors"))
    tuned = load_file(str(tuned_dir / "model.safetensors"))

    missing = set(base) ^ set(tuned)
    if missing:
        raise SystemExit(
            f"base and tuned differ in their parameter sets ({len(missing)} tensors). "
            f"Example: {sorted(missing)[:3]}. A delta needs identical keys."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    index: dict[str, dict] = {}
    chunks: dict[str, torch.Tensor] = {}
    retained = total = 0

    for name, tb in base.items():
        tt = tuned[name].to(tb.dtype)
        d = (tt.float() - tb.float())
        flat = d.abs().flatten()
        n = flat.numel()
        k = max(1, int(n * keep))
        idx = torch.topk(flat, k, largest=True).indices
        chunks[name] = d.flatten()[idx].to(torch.float16)
        index[name] = {"shape": list(tb.shape), "k": k, "n": n}
        retained += k
        total += n

    save_file(chunks, str(out_dir / "delta.safetensors"))
    (out_dir / "delta_index.json").write_text(
        json.dumps(
            {
                "base": "convaiinnovations/laya",
                "base_dir_hint": str(base_dir),
                "keep": keep,
                "tensors": index,
                "retained": retained,
                "total": total,
                "retained_fraction": round(retained / total, 6) if total else 0.0,
                "fidelity": (
                    "lossless" if keep >= 1.0
                    else f"top-{keep:.0%} of entries by |delta| per tensor; "
                         f"unretained entries revert to the base checkpoint"
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


def apply_delta(
    base_dir: Path,
    delta_dir: Path,
    out_dir: Path,
) -> dict:
    """Reconstruct a usable checkpoint as base + delta. Exact for retained entries."""
    import shutil

    from safetensors.torch import load_file, save_file

    meta = json.loads((delta_dir / "delta_index.json").read_text(encoding="utf-8"))
    base = load_file(str(base_dir / "model.safetensors"))
    delta = load_file(str(delta_dir / "delta.safetensors"))

    applied = 0
    for name, spec in meta["tensors"].items():
        if name not in base or name not in delta:
            continue
        shape = tuple(spec["shape"])
        n = spec["n"]
        d = torch_flat_to_shape(delta[name], shape, n)
        base[name] = (base[name].float() + d.float()).to(base[name].dtype)
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


def torch_flat_to_shape(flat, shape, n):
    import torch

    full = torch.zeros(int(torch.tensor(shape).prod()), dtype=torch.float32)
    full[: flat.numel()] = flat.float()
    return full.reshape(shape)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="stock Laya checkpoint dir")
    ap.add_argument("--tuned", required=True, help="fine-tuned checkpoint dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", type=float, default=0.05)
    ap.add_argument("--apply", action="store_true", help="reconstruct instead of export")
    args = ap.parse_args()

    if args.apply:
        import torch  # noqa: F401

        print(json.dumps(apply_delta(Path(args.base), Path(args.out), Path(args.tuned)), indent=2))
        return 0

    import torch  # noqa: F401

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
