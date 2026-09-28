# DIVYA — plan.md
> Master goal + long-horizon engineering loop. Source of truth for WHAT to build and IN WHAT ORDER.
> Repo state: GREENFIELD 2026-09-28 — `/home/shiva/projects/divya` empty, no git. This plan bootstraps from zero.
> Loop state lives in `docs/loop/*`. This file is the index; those files are the memory.

## 0. Progress marking system (mandatory)
Every task uses one prefix. No vague prose in status files.

- `[ ] TODO` — not started
- `[~] IN_PROGRESS` — exactly one per owner at a time
- `[x] DONE` — verified (evidence link + test/bench command required)
- `[!] BLOCKED` — needs external decision/secret/auth; must cite `docs/loop/BLOCKERS.md` ID
- `[?] HYPOTHESIS` — unverified claim, must not be treated as fact
- `[E] EVIDENCE` — primary-source verified fact

Update `docs/loop/STATUS.md` after every substantial iteration using template in §9.
Every architecture-changing decision → append to `docs/loop/DECISIONS.md` using template in §9.

## 1. Mission (compressed)
India-first AI-native market-intelligence terminal. System-2 LLM (reason/plan/orchestrate/abstain) + Laya System-1 (fast typed `choice`/`score`/`noul`) over shared-state recurrent loop. Levels: L1 tool-baseline → L2 synced shared-state → L3 Laya-aware System-2 → L4 justified deep coupling only. No "unified model" claim without evidence. Apache-2.0, self-hostable, `docker compose up` target, zero-cost MVP bias.

## 2. Baseline FACTS (2026-09-28 research)
- `[E] Laya 0.3.21, Apache-2.0, pip install laya, py>=3.10. Router().predict(state, questions). Docs: HF convaiinnovations/laya, GH NandhaKishorM/laya, nandhakishorm.github.io/laya.`
- `[E] Checkpoints: english 421M/512, multilingual 322M/1024 (8192 max), typed-decisions 421M/1024. Weights ~647-808MB each, 2.3GB all. T4 33ms/q, CPU 193-464ms.`
- `[E] Limits: base 0.362 typed-decisions zero-shot; fine-tuned 0.766; >20 options fails at default head budget; noul bias #156; act_probability broken #185; over-confident, needs temp refit.`
- `[E] Data: Bhavcopy EOD free/redistributable; intraday/real-time/display = licensed; broker APIs personal-use only. MVP = Bhavcopy + tejhq/indian-markets pattern, isolated adapters, freshness UI.`
- `[E] Empty workspace, no git, no PDR file in repo — PDR exists only in prompt. Treat as hypothesis.`

Research sources: HF `convaiinnovations/laya`, PyPI `laya 0.3.21`, GH `NandhaKishorM/laya` (~27k stars, 712 commits, Docker/compose+Nix, ONNX+laya-ts), Talker-Reasoner / LLM2 / ATLAS literature, NSE data-sharing policy + tejhq/indian-markets precedent.

## 3. Assumption table (seed for docs/loop/RESEARCH.md)
| Assumption | Evidence | Confidence | Impact if false | Validation experiment | Status |
|---|---|---|---|---|---|
| Laya CPU-usable for MVP loop | HF bench 193-464ms CPU, ONNX INT8 | Medium | Need GPU/serve split | `bench_laya_cpu.py` latency + accuracy smoke | `[ ] TODO` |
| Bhavcopy sufficient for first domain | NSE daily CSV; tej-bazaar MIT precedent | High | Pivot domain or license | Ingest 30d Bhavcopy → Parquet + freshness check | `[ ] TODO` |
| Recurrent S2↔S1 beats S2→S1 on ambiguous events | Talker-Reasoner/LLM2/ATLAS literature | Low | Stay at L1 | 200-event ambiguous subset A/B/C/D eval | `[?] HYPOTHESIS` |
| Zero-cost self-host viable | Laya self-host + HF cache + sqlite | Medium | Need paid inference | `docker compose up` on clean CPU box | `[ ] TODO` |
| Multilingual checkpoint covers Hindi/Hinglish filings | Router 45/51 langs >3x random | Medium | Pin english + custom fine-tune | Hindi headline choice/noul mini-bench | `[ ] TODO` |

## 4. Target architecture (to be formalized in docs/architecture/UNIFIED_MODEL.md)
`WORLD → System-2 (understand/decompose/plan/select/uncertainty) → decision_request → Laya (choice/score/noul) → structured result → Shared State (facts/evidence/hypotheses/decisions/confidence/history/disagreements, protocol vX) → System-2 loop or terminate+abstain.`
Rules: Laya never prose; S2 never silently overwrites raw Laya output; provenance + raw outputs inspectable; `min_confidence` abstention; max-iteration guard; full trace replay.

## 5. Phased build (each = verifiable goal)
- `[ ] TODO` P0 Forensics+bootstrap: git init, AGENTS.md, docs/loop/{GOAL,STATUS,DECISIONS,RESEARCH,EVALS,BLOCKERS,NEXT}.md, pyproject+uv, ruff+mypy+pytest, CI smoke. Verify: `pytest -q` green on empty suite + docs exist.
- `[ ] TODO` P1 Validate thesis: `research/scripts/bench_laya.py` (latency/accuracy/conf), assumption table filled, data-license register. Verify: recorded RESULTs, no hypothesis-as-fact.
- `[ ] TODO` P2 Unified arch spec: UNIFIED_MODEL.md (roles, state schema, request/response JSON schemas, termination, budgets, observability) + `models/questions.yaml` v0. Verify: schemas import-tested.
- `[ ] TODO` P3 L1 baseline: S2→Laya single-shot CLI `divya decide`. Metrics: latency/acc/calibration/tokens/calls/failures. Verify: baseline numbers committed.
- `[ ] TODO` P4 L2 loop: `divya/runtime/` shared-state + recurrent agent + trace JSONL + max-iter + abstain. Verify: multi-call trajectory replay test.
- `[ ] TODO` P5 Protocol versioning: questions.yaml migrations, per-decision eval set + failure modes. Verify: migration test.
- `[ ] TODO` P6 First domain: Bhavcopy EOD + corporate announcements/events → normalize → S2 task → Laya → persist (sqlite/parquet) → TUI. Scope: earnings/actions only. Verify: end-to-end on fixture + labeled freshness.
- `[ ] TODO` P7 Evals: A/B/C/D (Laya-alone/S2-alone/L1/L2), accuracy/prec/rec/F1/Brier/ECE/latency/tokens/abstention. Verify: `evals/report.md` with hw/model/n/dataset/method, no SOTA claims.
- `[ ] TODO` P8 Unification experiments (only if P7 justifies): routing/fine-tune/distillation. Each with HYPOTHESIS/METHOD/BASELINE/DATASET/METRICS/RESULT/FAILURE/DECISION in docs/research/UNIFICATION_EXPERIMENTS.md.
- `[ ] TODO` P9 Terminal: keyboard-first event stream, company state, confidence, evidence, why-view, freshness, versions. Verify: manual script + screenshots.
- `[ ] TODO` P10 Red-team: injection/malformed/dup/stale/Laya-down/LLM-down/state-corrupt. Safe degrade + abstain. Verify: adversarial test suite.
- `[ ] TODO` P11 Release: clean-machine `docker compose up`, seed, health, full tests+evals, README accurate. Verify: fresh-clone run log.

## 6. Repo layout to create (P0)
```
AGENTS.md  README.md  pyproject.toml  docker-compose.yml  Dockerfile
docs/{architecture/UNIFIED_MODEL.md, loop/{GOAL,STATUS,DECISIONS,RESEARCH,EVALS,BLOCKERS,NEXT}.md, research/UNIFICATION_EXPERIMENTS.md}
models/questions.yaml  src/divya/{runtime,protocol,laya_client,data,terminal,eval}/  tests/  evals/  research/scripts/
```

## 7. System-2 default (to confirm in build mode)
Local-first, zero-cost: Ollama/Qwen3 or equivalent instruction model via env-switchable provider interface (`DIVYA_S2_PROVIDER`), never hardcoded. No API key committed. Cloud LLM only as opt-in adapter.

## 8. Data boundary (enforced)
Adapter per source with `source/terms/redistribution/attribution/rate-limit/cache` manifest. Public default = Bhavcopy-derived only. Every price view shows as-of timestamp + source. Simulated = labeled SIMULATED, never as live.

## 9. Loop file templates
STATUS.md: CURRENT OBJECTIVE / WHAT CHANGED / EVIDENCE / TESTS / BENCHMARKS / KNOWN FAILURES / OPEN QUESTIONS / NEXT HIGHEST-VALUE ACTION.
DECISIONS.md: DATE / DECISION / CONTEXT / OPTIONS / EVIDENCE / TRADE-OFFS / WHY / REVERSIBILITY / FOLLOW-UP.

## 10. Definition of done (gate before final report)
Clone→run→reproduce→inspect-protocol→evaluate→use without author help. Product+evals+provenance+freshness+degrade+self-host+docs+no hidden blockers+no fabricated claims.

## 11. NEXT (immediate, in order)
1. `[ ] TODO` init git + scaffold §6 + loop files
2. `[ ] TODO` run Laya CPU smoke + Bhavcopy 30d ingest (smallest thesis-distinguishing experiments)
3. `[ ] TODO` write UNIFIED_MODEL.md v0 + questions.yaml v0
