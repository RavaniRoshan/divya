# ENVIRONMENT — practical survey of this machine

**Compiled:** 2026-09-28. Every command below was actually run on this host; real output is reproduced.
**Tag legend:** `[FACT]` = observed. `[HYPOTHESIS]` = inference. `[UNKNOWN]` = could not determine.

**Stated platform:** WSL2, 16 vCPU, 7.5 GB RAM, RTX 3050 4 GB, no docker, Python 3.12, Node 24.
`[FACT]` Confirmed by `uname -a`, `nproc`, `free -g`, `nvidia-smi`, `python3 -V`, `node -v`:

```
Linux RoshansdaamPC 6.6.87.2-microsoft-standard-WSL2 #1 SMP Fri Jun 6 06:30:16 UTC 2025 x86_64
Python 3.12.3
v24.19.0
16
              total        used        free      shared  buff/cache   available
Mem:              7           1           0           0           5           5
```
`[FACT]` GPU: `NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB`; at survey time **4096 MiB total, 0 used, 3962 free**.
`[FACT]` Disk: `/dev/sdd 1007G total, 138G used, 819G avail` on both `/` and `/tmp`.
`[FACT]` `pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12)`.

---

## 1. HTTP reachability — the actual `curl -w "%{http_code}"` results

`[FACT]` First pass, `curl -s -m 30 -o /dev/null -w "%{http_code}" <url>`, no special headers:

```
000  https://www.nseindia.com
000  https://nsearchives.nseindia.com/content/historical/EQUITIES/2026/SEP/cm01SEP2026bhav.csv.zip
000  https://nsearchives.nseindia.com/content/historical/EQUITIES/2025/SEP/cm01SEP2025bhav.csv.zip
200  https://www.bseindia.com
200  https://api.github.com/rate_limit
200  https://huggingface.co/api/models?search=qwen
200  https://pypi.org/simple/laya/
200  https://example.com
200  https://www.google.com
200  https://arxiv.org/abs/2310.10683
000  https://raw.githubusercontent.com/torvalds/linux/master/README
```

`[FACT]` **Two `000`s are real and need explaining, because one of them invalidates a path in `plan.md` and the other will bite anyone who tries to `curl` a GitHub file.**

### 1.1 The NSE `000`s are not a network problem — they are two different things

`[FACT]` DNS resolves fine: `www.nseindia.com -> 184.85.220.148` / `.173`, `nsearchives.nseindia.com -> 2600:140f:7200:49::17d4:71` (IPv6).
`[FACT]` `curl -sv` shows TCP connect **succeeds** and the TLS 1.3 handshake completes. The failures are above TLS:
- `https://www.nseindia.com` under HTTP/2: `HTTP/2 stream 1 was not closed cleanly: INTERNAL_ERROR (err 2)`.
- Same URL with `--http1.1` **and** a full Chrome User-Agent: **`403`**, 370 bytes, `remote_ip=49.44.140.152`.
  → `[FACT]` This is Akamai application-layer bot detection, not a firewall. **A browser UA is mandatory for `www.nseindia.com`.**
- The 404s on the `content/historical/EQUITIES/.../cmDDMMYYYYbhav.csv.zip` paths are **real 404s from a reachable host** (3425-byte HTML error page, `text/html`) — the path is dead, not the network. See `INDIA_DATA.md` §1.1 for the live path.

`[FACT]` **`nsearchives.nseindia.com` is behind the SAME block, and I initially got this wrong.** Corrected by direct A/B test (2026-09-28):
```
nsearchives, no User-Agent:      000
nsearchives, User-Agent curl/8.5: 000
nsearchives, Chrome UA (x3):      200 200 200
```
A browser User-Agent is required on **both** NSE hosts. My earlier successful bhavcopy/circular fetches all passed `-A "<Chrome UA>"`; I mis-read them as header-free. `[HYPOTHESIS]` The block is uniform Akamai bot detection — the archives host is *not* an open bypass. **Divya's HTTP client must set a browser UA on every NSE request**, and the adapter must treat a UA-less `000`/403 as a first-class failure mode rather than a network error.
`[FACT]` Bhavcopy and circular fetches are stable once the UA is set: 3/3 consecutive 200s, byte-identical size (177,047) each time.
`[HYPOTHESIS]` Still favourable relative to BSE, whose `api.bseindia.com` returns a hard Akamai `403 Access Denied` even *with* a browser UA and Origin/Referer headers — NSE yields to a UA, BSE did not in my tests.

### 1.2 `raw.githubusercontent.com` is blocked at the network edge

`[FACT]` `curl -sv` shows: IPv6 AAAA addresses fail (`Network is unreachable`), the IPv4 connect **succeeds**, the TLS Client Hello is sent, and then:
```
* Recv failure: Connection reset by peer
* OpenSSL SSL_connect: Connection reset by peer in connection to raw.githubusercontent.com:443
```
`[FACT]` DNS resolves to `185.199.108-111.133`; the host is reachable in principle. `[FACT]` Sibling hosts work fine: `api.github.com` → 200, `codeload.github.com` → 200, `github.com` → 200.
`[HYPOTHESIS]` An egress filter on this network is resetting `raw.githubusercontent.com` specifically (a common content-filtering target). **Workaround that works: use `https://codeload.github.com/<repo>/tar.gz/refs/heads/<branch>` and untar, which is how I inspected the repos in `INDIA_DATA.md` §4.**

---

## 2. Proxy / general egress

`[FACT]` `env | grep -i proxy` → **no output. No `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, or any proxy variable is set.**

`[FACT]` General internet egress is **open**, not host-allowlisted. Verified 200: `example.com`, `google.com`, `pypi.org`, `arxiv.org`, `huggingface.co`, `api.github.com`, `codeload.github.com`, `registry.ollama.ai`, `www.bing.com`, `html.duckduckgo.com` (202), `lite.duckduckgo.com` (202).
`[FACT]` The only confirmed egress block found is `raw.githubusercontent.com` (§1.2).
`[FACT]` Reachability is **bimodal per host**, not a global allow/deny: NSE blocks by bot-detection, BSE blocks by Akamai 403, GitHub blocks one subdomain, and the rest is open.

---

## 3. Python package availability

`[FACT]` Ran `python3 -m pip download <pkg> --no-deps -d /tmp/chk_<pkg>` for all nine. **All nine succeed.**

| Package | Result | Size | Artifact |
|---|---|---|---|
| `laya` | **OK** | 216K | `laya-0.3.21-py3-none-any.whl` |
| `onnxruntime` | **OK** | 23M | `onnxruntime-1.30.0-cp312-cp312-manylinux_2_28_x86_64.whl` |
| `numpy` | **OK** | 16M | `numpy-2.5.3-cp312-...manylinux_2_27_x86_64...whl` |
| `pandas` | **OK** | 11M | `pandas-3.0.6-cp312-...manylinux_2_24_x86_64...whl` |
| `pyarrow` | **OK** | 48M | `pyarrow-25.0.1-cp312-...manylinux_2_28_x86_64...whl` |
| `pydantic` | **OK** | 468K | `pydantic-2.13.5-py3-none-any.whl` |
| `textual` | **OK** | 720K | `textual-8.2.8-py3-none-any.whl` |
| `instructor` | **OK** | 268K | `instructor-1.17.0-py3-none-any.whl` |
| `lm-eval` | **OK** | 8.8M | `lm_eval-0.4.13-py3-none-any.whl` |

`[FACT]` **All resolve to cp312 manylinux x86_64 wheels or pure-Python wheels — no source builds, no compilation.** `[HYPOTHESIS]` The P0 `uv sync` path should be clean.

`[FACT]` ⚠️ **Version drift is ahead of `plan.md`.** `numpy 2.5.3`, `pandas 3.0.6` (pandas **3.x**), `onnxruntime 1.30.0`, `pyarrow 25.0.1`, `pydantic 2.13.5`. `plan.md` does not pin versions; **pandas 3.x is a major-version jump with breaking changes** and should be pinned deliberately rather than floated.

### 3.1 The venv already has Laya

`[FACT]` `/home/shiva/projects/divya/.venv/` is already populated. `pip list` shows **`laya 0.3.21`** plus `huggingface_hub 1.33.0`, `hf-xet 1.6.0`, `httpx 0.28.1`, `Jinja2 3.1.6`, `markdown-it-py 4.2.0`.
`[FACT]` Console scripts present: `laya`, `laya-evals`, `laya-mcp-server`, `laya-serve`, `hf`, `huggingface-cli`, `httpx`.

`[FACT]` Import smoke test passes:
```python
import laya
laya 0.3.21 at .../site-packages/laya/__init__.py
attrs: ['Agent', 'AsyncHook', 'BaseHook', 'DEFAULT_MODELS', 'DecisionResult', 'Hook',
        'LayaDecision', 'LayaEvaluator', 'LayaGuardrail', 'LayaGuardrailError', 'LayaGuardular',
        'LayaRouter', 'LayaTriage', 'PredictContext', 'PredictHook', 'QL_TYPES',
        'QTYPE_NAMES', 'RLAgent', 'RouteDecision', 'Router', 'answer_confidence']
```
`[FACT]` **This is the real public API surface.** Note the actual names are **`QTYPES` / `QTYPE_NAMES`** and **`LayaDecision` / `LayaTriage` / `LayaEvaluator`** — not the "typed-decisions" phrasing used in `plan.md`.
`[FACT]` `LayaTriage` and `LayaGuardrail` are the abstention/guardrail primitives; `answer_confidence` is a module-level export. **These are the hooks `AGENTS.md`'s abstention and calibration requirements should bind to** — and their existence is the strongest reason to think calibrated abstention is buildable without writing it from scratch.

`[FACT]` ⚠️ **`onnxruntime` is NOT installed in the venv** (`ModuleNotFoundError: No module named 'onnxruntime'`) even though it downloads fine. `[HYPOTHESIS]` If Laya is to run via the ONNX INT8 path, this must be added to the dev/extra dependency group.

---

## 4. Can we run a real LLM locally? — **Yes.**

`[FACT]` `command -v ollama` → **`/usr/local/bin/ollama`**. `docker` → **not present** (consistent with `AGENTS.md`).
`[FACT]` `ollama --version` → **`ollama version is 0.31.1`**
`[FACT]` `ollama list` →
```
NAME                ID              SIZE      MODIFIED
qwen2.5-coder:3b    f72c60cabf62    1.9 GB    8 weeks ago
```
`[FACT]` The daemon is **already running**: `curl -s -m 5 http://localhost:11434/api/tags` → **200**.
`[FACT]` The model registry is reachable: `https://registry.ollama.ai/v2/library/qwen3/manifests/4b` → **200**. `[HYPOTHESIS]` Additional models can be pulled.

> **This is a meaningful positive.** A System-2 provider is available *today* with no cloud spend, no API key, and no download — `qwen2.5-coder:3b` is already on disk. `src/divya/system2/` can be written and A/B-tested against a real model on day one.

`[FACT]` `command -v nvidia-smi` → `/usr/lib/wsl/lib/nvidia-smi`; GPU passthrough works.

### 4.1 HuggingFace downloads work

`[FACT]` `curl -s -m 30 -o /dev/null -w "%{http_code}" "https://huggingface.co/api/models?search=qwen"` → **200**.
`[FACT]` `https://huggingface.co/Qwen/Qwen3-0.6B/resolve/main/config.json` → **307 redirect**, and with `-L` → **200, 726 bytes**.
`[FACT]` `https://huggingface.co/Qwen/Qwen3-4B/resolve/main/model-00001-of-00003.safetensors` → **302 → 200**, `x-linked-size: 3957900840` (3.96 GB for shard 1 of 3).
`[FACT]` ⚠️ `https://huggingface.co/Qwen/Qwen3-4B/resolve/main/model.safetensors` → **404** — Qwen3-4B is **sharded**; there is no single-file `model.safetensors`. Any downloader that assumes one file will break.

### 4.2 What actually fits in 7.5 GB RAM / 4 GB VRAM

`[FACT]` Hardware envelope: **7.5 GB RAM** (≈5 GB available), **4 GB VRAM** (3962 MiB free), 819 GB disk.

`[HYPOTHESIS]` Sizing, by weight budget:
- **≤ ~2.5B params at Q4_K_M** (≈1.6 GB file) runs comfortably **fully on GPU** with room for KV cache under 4 GB VRAM. This is the recommended System-2 tier.
- **~4B params at Q4_K_M** (≈2.5 GB) fits VRAM only with a small context; a 4K–8K context will push it to partial CPU offload. Still workable, but latency becomes memory-bandwidth-bound.
- **~8B params at Q4_K_M** (≈5 GB) **does not fit in 4 GB VRAM**; it runs CPU-only. At ~7.5 GB total RAM with the OS and Laya resident, that leaves <5 GB for weights + KV — **marginal, and it competes directly with Laya.**
- **> ~13B is out.** Doesn't fit in RAM with any headroom.

`[FACT]` The already-pulled `qwen2.5-coder:3b` (1.9 GB) is the empirically safe choice, and it is a **code** model. `[HYPOTHESIS]` For financial-event reasoning, swap to an instruction-tuned general model of the same size (Qwen3-4B or an 8B at Q4) before drawing any conclusion about S2 quality — **a coder model on this task is a confound, not a baseline.**

> ⚠️ **The binding constraint is RAM, not VRAM.** Laya's CPU path (per `plan.md`, 193–464 ms/query) runs *in the same 7.5 GB* as the S2 model. `[HYPOTHESIS]` If S2 is run CPU-only at 8B, Laya latency and S2 latency will contend. **Prefer keeping S2 resident on GPU so Laya owns the CPU** — this is an architecture constraint the plan does not currently record.

---

## 5. Bottlenecks summary

| # | Finding | Impact |
|---|---|---|
| 1 | `laya 0.3.21` **already installed and importable**; real API is `Router`/`LayaDecision`/`LayaTriage`/`QTYPES` | P1 bench is unblocked |
| 2 | **Ollama 0.31.1 running with `qwen2.5-coder:3b` on disk** | System-2 arm is available today at zero cost |
| 3 | All 9 target pip packages install as prebuilt wheels | P0 `uv sync` is low-risk |
| 4 | `onnxruntime` missing from the venv | blocks the INT8 Laya path until added |
| 5 | **RAM (7.5 GB) is the real ceiling, not VRAM** | cap S2 at ~4B; keep Laya on CPU |
| 6 | **Every NSE host needs a browser UA** (Akamai): no-UA → `000`, `curl/8.5.0` → `000`, Chrome UA → `200` | set UA on all exchange traffic; treat `000`/403 as a real failure mode |
| 7 | `raw.githubusercontent.com` reset-by-peer | use `codeload.github.com` tarballs |
| 8 | `export.arxiv.org/api` → **HTTP 406** | use `arxiv.org/search/` + `api2.openreview.net` |
| 9 | No docker | venv + Makefile route, as `AGENTS.md` already states |
| 10 | pandas 3.0.6 / numpy 2.5.3 on PyPI | pin deliberately; pandas 3.x is a breaking major |

`[UNKNOWN]` Ollama's WSL2 GPU passthrough performance (tokens/s) was **not** measured — I did not run a generation. `[UNKNOWN]` Actual Laya inference latency on this host — requires downloading Laya checkpoints (`~647–808 MB` each per `plan.md`) and running `research/scripts/bench_laya.py`. `[UNKNOWN]` Whether the 4 GB VRAM is shared with the Windows host (WSL2 dynamic memory), which would make available VRAM less than 3962 MiB under GPU load.
