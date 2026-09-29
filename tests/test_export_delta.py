"""Round-trip proof for the sparse delta transport.

The delta exists to move weights out of Kaggle. If reconstruction is wrong, the model that
arrives locally is not the model that was trained, and every downstream number is fiction.
The failure is silent -- `apply_delta` still returns a valid safetensors file, it just is
not the right one -- so it needs an explicit test rather than a smoke check.

`tests/test_export_delta.py` is the cheap guard: a full `keep=1.0` round trip on a random
model must be bit-exact. If that holds, reconstruction of the retained entries is proven
correct, and a sparse `keep<1.0` delta differs from the base only in which entries travel.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
from safetensors.torch import load_file, save_file  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[1] / "research" / "scripts" / "export_delta.py"
_spec = importlib.util.spec_from_file_location("export_delta", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
apply_delta = _mod.apply_delta
export_delta = _mod.export_delta

SD = 7


def _make_model(d: object, *, bias: bool = True):
    torch.manual_seed(SD)
    sd = {"w": torch.randn(64, 32), "embed": torch.randn(128, 16)}
    if bias:
        sd["b"] = torch.randn(64)
    save_file(sd, str(d / "model.safetensors"))
    return sd


def _tuned_from(base):
    torch.manual_seed(SD + 1)
    return {k: (v + 0.25 * torch.randn_like(v.float())).to(v.dtype) for k, v in base.items()}


def test_full_round_trip_is_bit_exact(tmp_path):
    """keep=1.0 retains every entry, so base + delta must equal the fine-tuned model exactly.

    This is the assertion that the ORIGINAL exporter failed: it shipped values without their
    positions, and reconstruction was wrong while still looking like a valid checkpoint.
    """
    base_d, tuned_d, delta_d, out_d = (tmp_path / n for n in ("base", "tuned", "delta", "out"))
    for d in (base_d, tuned_d, delta_d, out_d):
        d.mkdir()

    base = _make_model(base_d)
    tuned = _tuned_from(base)
    save_file(tuned, str(tuned_d / "model.safetensors"))

    res = export_delta(base_d, tuned_d, delta_d, keep=1.0)
    assert res["keep"] == 1.0
    assert res["retained"] == res["total"]
    assert json.loads((delta_d / "delta_index.json").read_text())["fidelity"].startswith("lossless")

    apply_delta(base_d, delta_d, out_d)
    got = load_file(str(out_d / "model.safetensors"))
    assert set(got) == set(tuned)
    for k in tuned:
        assert torch.equal(got[k], tuned[k]), f"{k} did not survive the round trip"


def test_sparse_delta_keeps_large_entries_and_reverts_the_rest(tmp_path):
    """A sparse delta must be the base checkpoint plus exactly the retained large updates."""
    base_d, tuned_d, delta_d, out_d = (tmp_path / n for n in ("base", "tuned", "delta", "out"))
    for d in (base_d, tuned_d, delta_d, out_d):
        d.mkdir()

    base = _make_model(base_d)
    tuned = _tuned_from(base)
    save_file(tuned, str(tuned_d / "model.safetensors"))

    keep = 0.1
    export_delta(base_d, tuned_d, delta_d, keep=keep)
    apply_delta(base_d, delta_d, out_d)
    got = load_file(str(out_d / "model.safetensors"))

    index = json.loads((delta_d / "delta_index.json").read_text())
    for name, spec in index["tensors"].items():
        assert spec["k"] == max(1, int(spec["n"] * keep))
        # every retained entry carries its true fine-tuned value
        target = tuned[name].float().flatten()
        flat = got[name].float().flatten()
        baseflat = base[name].float().flatten()
        retained = (flat - baseflat).abs() > 0
        assert int(retained.sum()) == spec["k"]
        assert torch.allclose(flat[retained], target[retained], atol=1e-2)


def test_corrupt_delta_is_rejected_not_silently_applied(tmp_path):
    """A delta whose indices and values disagree must fail loudly."""
    from safetensors.torch import save_file as _save

    base_d, tuned_d, delta_d, out_d = (tmp_path / n for n in ("base", "tuned", "delta", "out"))
    for d in (base_d, tuned_d, delta_d, out_d):
        d.mkdir()

    base = _make_model(base_d)
    save_file(_tuned_from(base), str(tuned_d / "model.safetensors"))
    export_delta(base_d, tuned_d, delta_d, keep=0.1)

    delta = load_file(str(delta_d / "delta.safetensors"))
    key = next(k for k in delta if k.startswith("val/"))
    delta[key] = delta[key][:1]  # one value short of the indices
    _save(delta, str(delta_d / "delta.safetensors"))

    with pytest.raises(SystemExit, match="corrupt delta"):
        apply_delta(base_d, delta_d, out_d)


def test_mismatched_tensor_sets_are_refused(tmp_path):
    """A delta is only meaningful against an identical parameter set."""
    base_d, tuned_d, delta_d = (tmp_path / n for n in ("base", "tuned", "delta"))
    for d in (base_d, tuned_d, delta_d):
        d.mkdir()

    base = _make_model(base_d)
    save_file({k: v for k, v in _tuned_from(base).items() if k != "b"},
              str(tuned_d / "model.safetensors"))

    with pytest.raises(SystemExit, match="differ in their parameter sets"):
        export_delta(base_d, tuned_d, delta_d, keep=0.1)
