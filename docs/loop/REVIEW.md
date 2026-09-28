# REVIEW — independent final review

Reviewer did not build this repository. Everything below was produced by running the code in
this venv and recomputing from the raw artifact, not by reading and agreeing.

Environment used: `/home/shiva/projects/divya/.venv` (Python 3.12.3, torch 2.14.0+cpu,
laya 0.3.21), `PYTHONPATH=src`. Git tree clean at `2467914`.

---

## VERDICT

**SHIP WITH CAVEATS — but only after the four Severity-1 defects below are fixed.**

The engineering is genuinely good and the honesty about the negative result is real and
rare. The artifact is internally consistent: I recomputed every headline metric from
`per_item` and all of them match to the last decimal. Tests, lint and mypy are clean. The
product runs.

What blocks an unqualified ship is narrower and worse than "docs are stale": **the measurement
apparatus reports success on runs that failed, and three documents make claims about the
results that the results do not support.** Severity 1 is four specific items, each with a
one-line fix. None of them require re-running the 25-minute evaluation.

I would not ship before fixing those four, because two of them (defects 1 and 3) are false
statements about the headline experiment, and AGENTS.md rule 1 makes that the line the
project sets for itself.

---

## WHAT I VERIFIED AND HOW

### 1. Tests — `PYTHONPATH=src .venv/bin/python -m pytest tests/ -q`

**83 passed, 0 failed, 0 skipped, 0 warnings, in 0.49 s.**

Per file: `test_metrics.py`, `test_protocol.py` (24 tests), `test_runtime.py` (28 tests).

The metric tests are the best thing in the repo — every expected value is hand-computed in a
comment and re-derived in the assert (`tests/test_metrics.py:31` is a full worked
precision/recall/F1 derivation). That is exactly the discipline `EVALS.md` demands of results.

### 2. Lint and types

- `make lint` → `ruff check src tests evals research` → **All checks passed!**
- `make typecheck` → `mypy src/divya` → **Success: no issues found in 22 source files**

Both clean, exit 0.

### 3. The headline numbers — recomputed from `per_item`, not from `results`

I did not trust the `results` block. I re-derived it from the 120 `per_item` records plus
ground-truth labels from `evals/datasets/nse_announcements_v1.jsonl`, using the harness's own
definitions (`score_event_type`: probability of the **predicted** class, outcome = correct
indicator; `brier_score`, `expected_calibration_error`, `risk_coverage` from
`src/divya/eval/metrics.py`).

| Claim | Docs say | Recomputed | Artifact | Verdict |
|---|---|---|---|---|
| A accuracy | 0.558 | 0.5583 | 0.5583 | **confirmed** |
| C accuracy | 0.558 | 0.5583 | 0.5583 | **confirmed, identical to A** |
| D accuracy | 0.508 | 0.5083 | 0.5083 | **confirmed** |
| A/C/D ECE | 0.096 / 0.096 / 0.080 | 0.0956 / 0.0956 / 0.0800 | same | **confirmed** |
| A/C/D AURC | 0.240 / 0.240 / 0.260 | 0.2399 / 0.2399 / 0.2602 | same | **confirmed** |
| A/C/D p95 | 4.7 s / 19.0 s / 40.4 s | 4736.1 / 19002.7 / 40380.0 ms | same | **confirmed** |
| D abstains | 75.8% | 0.7583 | 0.7583 | **confirmed** |
| A macro-F1 | 0.436 | 0.4362 | 0.4362 | confirmed |
| D macro-F1 | 0.371 | 0.3710 | 0.3710 | confirmed |
| Prompt tokens A/B/C/D | 0 / 2214 / 1079 / 4941 | — | 0 / 2213.6 / 1078.9 / 4940.7 | confirmed (rounding) |
| Latency ratios C/A, D/A | 4.0×, 8.5× | 4.01×, 8.53× | — | confirmed |

**Every headline number in the brief is correct.** `EVALS.md:129-131` row 12/13/14 also match.
The `real_eval.log` progress output agrees. The numbers are not fabricated and the rounding is
honest.

Also confirmed from the artifact: `capital_action` → `other`/`fundraise` 13/13,
`regulatory_action` → `other`/`capital_action` 16/17, `other` precision 0.2941,
`credit_rating` F1 0.9412, `leadership_change` F1 0.8831.

### 4. Runtime

- `divya doctor` → exit 0. Correctly reports laya 0.3.21 importable, torch 2.14.0+cpu,
  `cuda=False`, checkpoint not loaded yet (~7 s, ~2.8 GB RSS), ollama reachable with
  `qwen2.5-coder:3b`, and the per-source licence verdicts.
- `divya protocol show` → exit 0. `event_triage v2`, 10 options on `event_type`,
  `evidence_sufficiency` tier 2. Consistent with the shipped `models/questions.yaml`.
- `divya decide --text "Infosys…quarter ended 30 September 2024." --width 100` → exit 0 in
  **16.7 s**. Default mode is genuinely System-1-only: `s1 calls=1 s2 calls=0 turns=0`,
  termination `finished` with reason "System-1 only mode: one typed pass, no reasoning model
  (D-012)". Classified `earnings_result` at 0.752 confidence. Does not hang, does not crash.

Note on that example: Laya put `earnings_result` 0.74 against `board_meeting` 0.25. A board
meeting notice *about* results is exactly the kind of item the NSE-desc taxonomy will score
`board_meeting`. This is a live illustration of the labelling ambiguity in B-004/EVALS.md:76,
and it would be a good addition to the docs.

---

## DEFECTS FOUND

### SEVERITY 1 — must fix before ship

#### D1. ~~`terminated_ok` is inverted~~ **FIXED** (see `docs/loop/STATUS.md` and the commit) — original finding retained below

> Original finding:

`src/divya/eval/harness.py:267`

```python
"terminated_ok": result.state.termination is not None,
```

This is "did the loop terminate at all", not "did it terminate successfully". An error
termination sets a status and so evaluates `True`. Contrast the sibling paths, which do it
correctly: `harness.py:249` uses `terminated_ok: False` on the exception path, and
`harness.py:214` uses `not rec.error` for arm A.

Evidence:

```
arm B: results.B.reliability.terminated_ok_rate == 1.0
       all 120 per_item records: termination == "error", answers == {}, conclusion == ""
```

Every single arm-B item errored and produced nothing, and the artifact reports
`terminated_ok_rate: 1.0`. The `reliability` block for all four arms
(`real_eval.json` → `results.*.reliability.terminated_ok_rate`) is therefore meaningless.
This is the headline experiment's only failure-visibility signal, and it is stuck on. It
directly violates AGENTS.md rule 6, "fail safe, fail visible".

#### D2. ~~Arm B's 0.000 is a broken arm~~ **FIXED** (harness now prints `ERROR: arm B produced NO event_type answer` and sets `ARM_FAILED_NO_OUTPUT`); documentation corrected below

> Original finding:

`README.md:151`, `docs/loop/STATUS.md:34`, `docs/loop/EVALS.md:129`, `docs/loop/NEXT.md:7`

All four report arm B as `accuracy 0.000 · macro-F1 0.000 · ECE 0.000 · AURC 1.000`. The
numbers are arithmetically correct — the harness scores a missing answer as wrong at zero
confidence (`harness.py:113-127`), which is the right choice. But nothing anywhere says arm B
**produced no output at all**:

```
arm B: 120/120 items -> answers == {}   (0 items with an event_type answer)
        ECE "0.000" is the degenerate 0-vs-0 case, not a calibration result
        AURC 1.000 is the constant-confidence case, not a risk-coverage finding
```

`grep -rn "no answers|did not answer|produced no"` across `README.md` and `docs/` returns
**nothing**. So a reader sees a clean results table row reading "System-2 alone: 0.000" and
reasonably concludes System-2 alone was measured and is useless. What actually happened is that
the System-2-only path emitted nothing parseable on 120 of 120 items. Those are different
findings: the first is a model result, the second is a wiring bug plus a blocked capability
(B-003, which still says structured-output quality is "not yet measured" — it has now been
measured, adversely).

`real_eval.log` prints `B: acc=0.000` with no warning, while the harness *does* warn loudly
when System-1 is missing (`harness.py:611`). The asymmetry is the bug: an arm returning zero
answers across an entire run should be loud.

#### D3. ~~"Scores the abstained events wrong" is false~~ **FIXED**; the corrected mechanism is sharper — original finding retained below

> Original finding:

`README.md:158`, `docs/loop/STATUS.md:47-48`

> "a 75.8% abstention rate that scores the abstained events wrong" (README)
> "It abstains on 75.8% of events and scores the abstained ones wrong, so the abstention costs
> accuracy rather than buying safety." (STATUS)

It does not. Arm D's accuracy is computed on the **raw System-1 answer**, which is present even
when the loop abstained (AGENTS.md rule 4 — raw output is immutable and separately scored).

```
D total    n=120  correct=61  accuracy=0.5083
D abstained n=91   correct=38   <- scored on a real raw answer, 38 of them correct
D answered  n=29   correct=23
D abstained items with no raw answer at all: 20
```

If abstained items were scored wrong, accuracy could not exceed 29/120 = 0.2417. The measured
0.5083 is above that ceiling, so the stated mechanism is disproven by the repo's own artifact.
The real explanation for D < A is that D's repeated System-1 calls returned *different, worse*
answers — 6 items where A was right and D wrong, 0 the other way.

This matters beyond wording: "abstention costs accuracy" is offered as part of the reasoning
for why H4 (calibration win) is not supported. That specific argument must be replaced.

#### D4. ~~The confusion matrix mixes arm A and arm D~~ **FIXED**; numbers now stated per arm — original finding retained below

> Original finding:

`README.md:175-176`, `docs/loop/STATUS.md:180-181`, `docs/loop/NEXT.md:26`

All three say `other` has "precision 0.29 while absorbing **27** of the misclassifications".
Precision 0.29 is **arm A's**. In arm A, `other` has TP=15, **FP=36**.

```
arm A: other TP=15 FP=36  precision=0.2941   <- the 0.29 quoted
arm C: other TP=15 FP=36  precision=0.2941
arm D: other TP=14 FP=27  precision=0.3415   <- 27 comes from here
```

27 is arm D's false-positive count, presented inside an arm-A analysis (STATUS.md:56 opens
"Per class" from the arm A table). No quantity in the arm-A analysis equals 27. Since this
number justifies the entire next experiment in `NEXT.md`, it needs to be 36, or the sentence
needs to say which arm it is quoting.

### SEVERITY 2 — fix before declaring complete

#### D5. "79 tests" is wrong and contradicts itself inside STATUS.md

`README.md:44` (`make test  # 79 tests`), `README.md:219` (`tests/  79 tests`),
`docs/loop/STATUS.md:22` ("79 tests, ruff clean, mypy clean") — actual count is **83**.
`docs/loop/STATUS.md:148` correctly says "**83 passing**". So STATUS.md contradicts itself,
and the README repeats the stale figure twice.

#### D6. STATUS.md still says the A/B/C/D comparison is in progress

`docs/loop/STATUS.md:156`: "The A/B/C/D comparison is in progress."

It is finished — E-009 is reported at STATUS.md:26-66 and `evals/results/real_eval.json`
exists and is populated (960 KB). Same section header (`## BENCHMARKS`).

#### D7. An open question was already answered 130 lines above it

`docs/loop/STATUS.md:173`: "Does the loop *help* on the ambiguous stratum specifically? The
stratified split will show."

The stratified split is already reported at STATUS.md:38-39: `ambiguous` (n=6) — A 0.500 /
C 0.500 / D 0.500. Tied. The question is answered; the answer is "no", and it is on n=6.

#### D8. `--mode system1_only` does not exist

`STATUS.md:62-63` names the mode `system1_only`, and D-012 is titled that way. The CLI accepts
`{system1, loop}`:

```
$ divya decide --text "x" --mode system1_only
divya decide: error: argument --mode: invalid choice: 'system1_only'
                (choose from 'system1', 'loop')
```

A user following the STATUS/DECISIONS wording hits an error. Either add the alias or make the
docs say `system1`.

#### D9. The README's `--file` example does not do what its comment says

`README.md:64`:

```bash
divya decide --file evals/datasets/nse_announcements_v1.jsonl   # (or pipe one record)
```

This runs, but `--file` reads the whole file as one document — so it feeds **1,042 JSON
records** to Laya as a single blob. Verified: 53.4 s System-1 latency (vs ~12 s for one
record) and a garbage `capital_action` at 0.09 confidence. The comment implies one record is
being decided. Either use a single-record file in the example or say plainly that this is a
whole-file smoke test.

#### D10. The README's opening example no longer describes the default

`README.md:17-33` shows `divya decide --text "..." --trace` producing a 4-turn System-2 trace
(`call_system1` … `call_system1` … `finish`). The default mode has been System-1-only since
D-012, so that command now emits `s1 calls=1 s2 calls=0 turns=0` and no `call_system1` lines.
The first thing a reader sees in the README is output the default mode cannot produce.

### SEVERITY 3 — evidence gaps and overstated framing

#### D11. No significance test anywhere; "H3 SUPPORTED" rests on 6 items

EVALS.md:19-22 demands a paired comparison and EVALS.md:16 demands a baseline. The comparison
is genuinely paired, but **no test is reported anywhere**. I ran the obvious one:

```
Paired A vs D on 120 items: A right/D wrong = 6,  A wrong/D right = 0
Exact McNemar two-sided p = 0.0312   (continuity-corrected z = 2.041)
```

So the direction of H3 is supported and the discordance is one-sided — but the entire result
is 6 items. "H3 (loop hurts) **SUPPORTED**" (README:161, STATUS.md:51) is stated with no
uncertainty attached and no test named. Given `NEXT.md`'s own rule that "every item ends with a
command whose output was actually observed", the p-value belongs in EVALS.md row 12 with the
n=6 discordance stated.

#### D12. "Well calibrated (n=7, 100%)" is not a calibration finding

`README.md:139`, `STATUS.md:114-115`. Seven items cannot establish calibration, and this sits
directly beside a system whose overall ECE is 0.182 and whose mid-band accuracy is 20% at 63%
stated confidence. Also note the 0.93–1.0 band is *exactly* the band the `choice:11+`
temperature of 0.1006 pushes mass into (`STATUS.md:105-111`) — a confidence of 0.99 is what
an over-sharpened distribution produces by construction, so 100% accuracy in that band is
weak evidence *for* calibration and it is being read as strong evidence. State n and drop
"well calibrated".

#### D13. Latency multiplier attributed to the wrong comparison

`README.md:157`: "**D is worse than C** — 0.508 vs 0.558 — at **8.5×** the latency."
D/C p95 = 40.380/19.003 = **2.12×**. The 8.5× is D vs **A** (40.380/4.7361 = 8.53×).
STATUS.md:47 gets this right ("8.5× arm A's latency"). README line 157 does not.

#### D14. `real_eval.json` mislabels the provenance of its own data

`evals/results/real_eval.json` → `dataset.note`:

> "Text is authored for this project, not scraped. Accuracy measures agreement with these
> labels, not correctness about the Indian market. See evals/make_dataset.py."

False for this run. `nse_announcements_v1.jsonl` has `is_synthetic_text: false` on every row
and the text is fetched from NSE. The note is a hardcoded string in
`src/divya/eval/harness.py` (~line 638) that does not vary by dataset, so the synthetic
dataset's caveat was carried into the real-data artifact. It errs in the safe direction, but a
provenance field in the primary artifact must be true.

#### D15. No dev/test split, no seed, and the "split" is a file prefix

`EVALS.md:103-108` mandates: "Fit/tune on the dev split only. Report on test, touched once per
configuration." There is no split anywhere. `load_items` (`harness.py:92-104`) is
`items[:limit]` — **the first 120 rows of a 1,042-row file**, deterministic, unshuffled, no
seed recorded in `config`. Two consequences: the subset is not a sample (it inherits whatever
ordering the builder emitted), and the protocol change v1→v2 plus the `min_confidence=0.55`
and `d_max_turns=4` choices were all made while looking at these 120 items, so "touched once"
is not true. Neither is fatal for a negative result, but EVALS.md should state the actual
protocol rather than an unimplemented one.

#### D16. Arm C is not an independent condition at `c_samples=1`

`real_eval.json` `config.c_samples == 1`. Against arm A, arm C produced an **identical choice,
identical probability vector, and identical confidence on 120/120 items** — while making 120
extra System-2 calls, hitting `max_turns_hit_rate: 1.0`, and costing 4.01× p95. So "A and C
are identical to the decimal" (README:155) is true but the framing as two arms invites
reading it as two independent confirmations. The correct statement is the stronger one:
*one extra System-2 call per event changed nothing at all.*

#### D17. Zero tests for the modules that produce every number in the repo

Tests import only `divya.eval` (metrics), `divya.protocol.*`, `divya.runtime.*`,
`divya.system1.laya_adapter`, `divya.system2.*`. Untested:

- `src/divya/eval/harness.py` — **702 lines, the module that computed the entire headline
  result.** `grep -rn "harness" tests/` returns nothing. D1 lives here.
- `src/divya/data/nse_taxonomy.py` — the 104-class map that produced **every label** in the
  evaluation. A mapping bug here silently moves accuracy with no test failing.
- `src/divya/data/nse.py`, `src/divya/data/sources.py`, `src/divya/cli.py`,
  `src/divya/terminal/view.py`.

#### D18. A README number is not in the register it is required to be in

`README.md:136`: "Laya `event_type` on 4 clean finance fixtures | **4/4 correct**".
`EVALS.md:3-4`: "**No number appears in this repo unless it appears here first, with its
conditions attached.**" There is no such row in EVALS.md, and `research/results/` has no
artifact for it. (The adjacent latency and RSS figures *are* registered and *do* match
`bench_laya.json`: 4552.5 ms p50, 2746.2 MB.)

#### D19. One near-tautological test

`tests/test_metrics.py:174` `test_risk_coverage_curve_is_monotonic_in_coverage` asserts
`coverages == sorted(coverages)`. Coverage values are `i/n` for `i` in `1..n`
(`metrics.py:214-221`), so they are monotonic by construction for **any** input; the assert
cannot fail. The `len(curve) == 4` on the next line carries the whole test. Not harmful — it
just should not be counted as coverage of the property. The rest of `test_metrics.py` is
genuinely strong; this is the only one I could not make fail-or-pass meaningfully.

---

## OVERSTATED CLAIMS

**Does anything claim the architecture works when the measurement says it does not?**
Mostly no, and this is the project's real strength. README:7-11 states the thesis is a
hypothesis under test; README:144-169 reports the rejection; the default was switched to
System-1-only on the evidence; D-012/D-013 decline Levels 3-4 with reasoning
(`DECISIONS.md:480-489`). No document claims the loop wins. **I could not find the failure
mode the brief asked about**, and `NEXT.md`'s standing rules ("do not re-run until it goes our
way") are the right posture.

Where it does slip is narrower:

1. **Arm B (D2)** — the one arm that would make "System-2 alone is useless" look like a
   finding rather than a wiring failure.
2. **The mechanism offered for why the loop hurts (D3)** — a false causal claim, in the
   direction of making the negative result *less* favourable to the product than it is.
3. **The `other`-attractor diagnosis (D4)** — the entire next experiment rests on a number
   taken from the wrong arm. The conclusion probably survives (36 is a larger attractor than
   27), but the stated evidence is wrong.

**Numbers quoted with no artifact:** D18 (`4/4` fixtures). `EVALS.md:125` cites
"`research/results/`" with no filename for row 8 (the n=24 real-NSE result) — there is no such
file in that directory. The n=120, n=30, latency, RSS, and temperature numbers all trace to
real artifacts.

**Licence position:** appropriately hedged everywhere I checked. `README.md:200` "Not
licence-cleared for redistribution"; `B-002` is careful — "no reuse grant *was located*",
"`Allow: /` in robots.txt is crawler etiquette, not a licence", and it correctly separates
"fine for self-hosting" from "not clearance to ship". `sources.py` verdicts print via
`doctor`. `README.md:229-230` correctly notes data sources carry their own terms. **No
overstatement found** — this is better handled than most projects manage.

**"calibrated" / "fast" / "production ready" / "real-time":**
- *calibrated* — D12 ("well calibrated, n=7") and EVALS.md:138 "the protocol loader now
  refuses to load one" (that one is accurate). `metrics.py:14` says "calibrated" in a comment
  about a confidence convention; fine.
- *fast* — never used bare. Latency is always attached to hardware and a baseline (e.g.
  `README.md:134`), which is what AGENTS.md rule 1 requires. The p50 4552 ms is reported
  honestly, including the unflattering 8.6 s max in `bench_laya.json`.
- *production ready* — **not used anywhere.** Correct: `B-001` marks Docker
  `UNVERIFIED-IN-THIS-ENV`.
- *real-time* — `README.md:198` explicitly says "**Not real-time.** EOD bhavcopy". Good.
- *fail safe / fail visible* — this is where D1 lands: the one mechanism that would make a
  failed run visible is reporting success.

---

## MISSING WORK

Against the project's own definition-of-done:

1. **Tests for `eval/harness.py`, `data/nse_taxonomy.py`, `data/nse.py`, `cli.py`,
   `terminal/view.py` (D17).** The module that produced the headline number and the module
   that produced every label have zero coverage. This is the single largest gap.
2. **A significance test for the paired A-vs-D claim (D11).** `EVALS.md` defines the metric
   set but no inferential statistic; "H3 SUPPORTED" is currently an assertion.
3. **Arm C needs `c_samples > 1` before it can be called a self-consistency arm (D16).** At
   `c_samples=1` it is a duplicate of A plus a no-op call.
4. **`is_material`, `materiality`, `direction` remain unscored on real data (B-005).** The
   harness honestly reports `"not evaluated"` rather than omitting them, which is the right
   behaviour — but **three of the four decisions in the protocol have never been evaluated on
   real data.** `NEXT.md` queues the hand-labelling. Given the README calls Divya a
   "market-intelligence terminal", this is the widest functional hole.
5. **PDF extraction (B-004).** Median input is a 154-character one-liner. The largest single
   quality lever, and unblocked.
6. **Dev/test split and a recorded seed (D15).** EVALS.md mandates it; nothing implements it.
7. **Arm B needs diagnosis, not a results row (D2).** Either fix the System-2-only path or
   report it as a broken arm.

`NEXT.md`'s queue is honest and correctly prioritised, and D-009's refusal to re-run until
results improve is the right instinct. The gaps above are mostly *recorded*; my complaint is
that D2, D3, D4 and D18 are not, and each is a claim rather than a gap.

---

## WHAT I COULD NOT VERIFY

- **Docker / `docker compose up`** — `docker` not present. `B-001` already marks this
  `UNVERIFIED-IN-THIS-ENV`; I am not contradicting it, only confirming it remains unverified.
- **Reproducibility of `real_eval.json`.** Re-running the full A/B/C/D takes ~25 minutes of
  ollama + Laya time. I verified internal consistency of the artifact against `per_item`
  (complete) but not that a fresh run reproduces these numbers. `NEXT.md` also records that no
  re-run with a different seed/subset/model was attempted — a real reproducibility gap.
- **The n=24 real-NSE arm-A result** (`README.md:137`, `EVALS.md:125`) — no artifact in
  `research/results/`. Unverifiable, and `EVALS.md:125` does not name a file.
- **"4/4 correct on clean finance fixtures"** (`README.md:136`) — no artifact.
- **The n=30 synthetic 0.733** — I did not re-run it. `armA_v2_calibrated.json` exists and is
  97 KB; I did not recompute it.
- **Live NSE claims of 2026-09-28**: STATUS.md:85 records bhavcopy HTTP 200, but
  `divya doctor` returns **HTTP 404** for bhavcopy today. Announcements return 200. This is
  most likely a date/EOD-publication artefact rather than a false record, but the "verified"
  table does not currently reproduce.
- **`data/traces/`** contains exactly 1 trace file; STATUS.md:144's claim that the 4-turn loop
  is "reconstructable from `data/traces/`" rests on that single file. I confirmed it exists and
  is well-formed but did not replay it.
