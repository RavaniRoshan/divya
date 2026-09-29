# State of the Art — Indian corporate-announcement event classification

**Survey date:** 2026-09-29. Every figure below was fetched during this survey; the URL is given for each.
Anything not fetched is marked `[UNVERIFIED]`.

---

## THE HEADLINE ANSWER

**Your 0.43 macro-F1 is not a prompt problem and it is not below par — it is essentially exactly where
Laya's own published numbers say a zero-shot non-autoregressive encoder lands.** Laya's model card and
`BENCHMARKS.md` state that its base checkpoints score **0.361 accuracy on its own 2,000-decision
typed-decision benchmark — below the 0.461 majority-class baseline** — while the *fine-tuned*
checkpoint of the same architecture scores **0.766** on the same benchmark, and the author writes
plainly: *"Base checkpoints are near chance on typed-decisions zero-shot… Laya is a fast base to
specialise, not a zero-shot decision engine."* On a held-out **10-way** classification
(support triage) the base checkpoint scores **0.502**; on 4-way AG News it scores 0.950. Your 9-way
noisy-financial-text task sits squarely in the 6–20-option band where Laya is documented to degrade.
Meanwhile a **fine-tuned** transformer on comparable financial text reaches **m-F1 78.0 / µ-F1 82.1**
(FiNER-139) and a fine-tuned FinBERT/RoBERTa reaches **94.29% accuracy / 93.27% F1 on Indian financial
news** (SEntFiN 1.0). **The gap between your 0.43 and the ~0.80–0.94 band is almost entirely the
fine-tuning gap, not an architecture impossibility** — and Laya's own published recipe closes most of
it (0.362 → 0.766) on 2x free Kaggle T4 GPUs in 4 epochs. Separately: **there is no published
benchmark, dataset, or practitioner write-up anywhere that classifies NSE/BSE announcements into
event types with reported accuracy.** You are not behind a state of the art. There is no state of the
art.

---

## Published results table

| # | Source | Dataset | Classes | Model | Size | Fine-tuned? | Score | URL |
|---|---|---|---|---|---|---|---|---|
| 1 | Laya model card + BENCHMARKS.md (Laya's own, primary source) | `LocalLLaMA/typed-decisions`, 2,000 decisions, 4 workflows | mixed choice/score/noul | `laya` (ModernBERT-large) | 421M | **No (zero-shot)** | **acc 0.361**, soft-acc 0.332, Brier 0.316 | https://huggingface.co/convaiinnovations/laya · https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md |
| 2 | same | same | same | `laya-multilingual` (mmBERT-base) | 322M | No | acc 0.352 | same |
| 3 | same | same | same | `laya-typed-decisions` | 421M | **Yes (4 epochs, 2xT4, LR enc 2.5e-5 / head 1e-4, eff. batch 64)** | **acc 0.766** | same + https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb |
| 3b | same (baselines on the same benchmark) | typed-decisions | — | majority-class / random / TypeSafe Jev 1.13.0 (closed API) | — | n/a | 0.461 / 0.318 / 0.727 | same |
| 4 | Laya BENCHMARKS.md "Themes" | Support triage, **held out**, 400 cases | **10-way** | `laya` | 421M | No | **acc 0.502** | https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md |
| 5 | same | Support triage, held out | 10-way | `laya-multilingual` / `laya-typed-decisions` | 322M/421M | No / Yes | 0.522 / 0.505 | same |
| 6 | same | Moderation (toxic-chat), held out | — | `laya` | 421M | No | acc 0.530, **macro-F1 0.400** — "barely above chance" | same |
| 7 | same | AG News | 4 | `laya` / typed-decisions | 421M | No / Yes | 0.950 / 0.953 | same |
| 8 | same | DAIR Emotion | 6 | `laya` / typed-decisions | 421M | No / Yes | 0.595 / 0.600 | same |
| 9 | same | Banking77 | **77** | `laya` / typed-decisions | 421M | No / Yes | **0.425 / 0.492** — "keep choice questions under ~20 options" | same |
| 10 | same | MASSIVE intent, 20 options, English only | 20 | `laya` | 421M | No | 0.783 | https://huggingface.co/convaiinnovations/laya |
| 11 | same | MASSIVE intent, 20 options, 51 languages | 20 | `laya` / `laya-multilingual` | 421M/322M | No | **macro-acc 0.2269 / 0.3661; macro-F1 0.2053 / —** | https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md |
| 12 | **Martins & Astudillo, "FiNER" (arXiv 2203.06482)** | **FiNER-139**, 1.1M sentences of SEC filings | **139 XBRL entity types** | `sec-bert-shape` (BERT, pre-trained on EDGAR) | ~110M | **Yes** | **µ-F1 82.1**, m-F1 78.0–80.4 | https://arxiv.org/abs/2203.06482 |
| 13 | same | FiNER-139 | 139 | BERT+CRF / BiLSTM(words) / spaCy | 110M | Yes / no | m-F1 75.2 / 73.8 / **37.6** | same |
| 14 | same | FiNER-139 | 139 | FinBERT (Araci et al.) | 110M | Yes | worse than plain BERT without numeric pseudo-tokens; 80.1 µ-F1 with | same |
| 15 | **Araci, "FinBERT" (arXiv 1908.10063)** | Financial PhraseBank | 3 (pos/neg/neu) | FinBERT (BERT-base) | ~110M | **Yes** | **acc 0.97 / F1 0.91** on the 100%-agreement subset | https://arxiv.org/abs/1908.10063 · https://huggingface.co/ProsusAI/finbert |
| 16 | **Seth & Patel, "SEntFiN 1.0" (arXiv 2305.12257)** — **Indian financial news** | SEntFiN 1.0, 10,753 headlines | entity×sentiment, 3 | RoBERTa / FinBERT | 125M | **Yes** | **acc 94.29%, F1 93.27%** | https://arxiv.org/abs/2305.12257 · https://github.com/pyRis/SEntFiN |
| 17 | "Learning to Aggregate Zero-Shot LLM Agents for Corporate Disclosure Classification" (arXiv 2603.20965) | 9,860 US corporate disclosures, Jan 2025–Mar 2026 | next-day return direction | 3 zero-shot LLM classifiers + logistic aggregator | LLM (closed) | aggregator Yes, classifiers No | balanced acc **0.566** (best single) → **0.606** (trained aggregator); both beat a FinBERT baseline and a zero-shot LLM judge | https://arxiv.org/abs/2603.20965 |

### Direct zero-shot vs fine-tuned comparison (the comparison you asked for)

| Architecture | Task | Zero-shot | Fine-tuned | Δ |
|---|---|---|---|---|
| Laya 421M (your model) | its own typed-decision benchmark | **0.361** (below 0.461 majority baseline) | **0.766** | **+0.405** |
| Laya 421M | NSE announcement event typing, 9-way, 154 chars | **your 0.43 macro-F1** | `[UNVERIFIED — nobody has published this]` | — |
| BERT ~110M | FiNER-139, 139 financial entity types | `[UNVERIFIED — no zero-shot baseline reported]` | **m-F1 78.0 / µ-F1 82.1** | — |
| FinBERT ~110M | SEntFiN 1.0, Indian financial headlines | `[UNVERIFIED]` | **F1 93.27** | — |

**Blunt reading:** every published *fine-tuned* model on financial text sits at 0.78–0.94. Every
published *zero-shot* small-encoder result on a ≥6-way typed-decision task sits at 0.36–0.50. Your
0.43 is in the zero-shot band, exactly where it should be. **Further question-set editing is
predicted by the evidence to be wasted effort.**

---

## Datasets available

| Name | Size | Labels | Licence | How to get it | Indian? | URL |
|---|---|---|---|---|---|---|
| **FiNER-139** | 1.1M sentences (900,384 train / 112,494 dev / 108,378 test), ~1.7 tokens/sentence, 44.7 tags/sentence | 139 XBRL entity types (subset of 6,008) | **CC-BY-SA-4.0** | `huggingface.co/datasets/nlpaueb/finer-139` (634 downloads, 28 likes) | No — US SEC EDGAR | https://huggingface.co/datasets/nlpaueb/finer-139 · https://arxiv.org/abs/2203.06482 |
| **SEntFiN 1.0** | 10,753 headlines; 2,847 multi-entity | entity×sentiment (pos/neg/neu) | MIT (repo) | `github.com/pyRis/SEntFiN` (10 stars) | **Yes — Indian financial news** | https://github.com/pyRis/SEntFiN · https://arxiv.org/abs/2305.12257 |
| **`LocalLLaMA/typed-decisions`** | 400 cases / 2,000 decisions (train + test) | choice / score / noul across 4 workflows | **Apache-2.0** | `huggingface.co/datasets/LocalLLaMA/typed-decisions` (16,449 downloads, 59 likes) | No | https://huggingface.co/datasets/LocalLLaMA/typed-decisions |
| **FinQA** | **8,281 QA pairs** (6,251 train / 883 val / 1,147 test — verified in the HF card) | open numerical QA over financial reports + gold reasoning programs | **no licence declared** on the `dreamerdeo/finqa` mirror (HF API `cardData`) | `huggingface.co/datasets/dreamerdeo/finqa` (5,137 dl, 28 likes) | No — US | https://arxiv.org/abs/2109.00122 · https://huggingface.co/datasets/dreamerdeo/finqa |
| **DocFinQA** | **7,437 questions**, avg context raised from <700 words (FinQA) to **123k words** | long-document financial QA | `[UNVERIFIED]` | arXiv | No — US | https://arxiv.org/abs/2401.06915 |
| **MultiHiertt** | multi-hierarchical-table financial QA | QA | `[UNVERIFIED]` | arXiv | No | https://arxiv.org/abs/2206.01347 |
| **`kdave/Indian_Financial_News`** ("IndiaFinanceSent Corpus") | 26,000 rows, 112 MB | sentiment (labels "gathered using the GPT add-on for Google Sheets" — i.e. **weak/auto labels**), T5 summaries | **no licence declared in cardData** | `huggingface.co/datasets/kdave/Indian_Financial_News` (126 dl, 15 likes) | **Yes** | https://huggingface.co/datasets/kdave/Indian_Financial_News |
| **`rafaytalha23/psx-announcements-data`** | 3,655 examples | ticker, title, date, pdf_url, extracted_text, sentiment_score, sentiment_impact, sentiment_signals | MIT | `huggingface.co/datasets/rafaytalha23/psx-announcements-data` (41 dl) | **No — Pakistan Stock Exchange** | https://huggingface.co/datasets/rafaytalha23/psx-announcements-data |
| `ZipLime/corporate-actions` | adjustment factors, dividends, PIT deltas | structured corporate-action records (not text classification) | Apache-2.0 | `huggingface.co/datasets/ZipLime/corporate-actions` (259 dl) | `[UNVERIFIED]` | https://huggingface.co/datasets/ZipLime/corporate-actions |

### Datasets that do NOT exist (verified negative)

- **No NSE/BSE announcement event-classification dataset on HuggingFace.** Searches
  `nse`, `bse`, `announcement`, `corp announcement`, `corporate action`, `filing classification`,
  `event extraction` all returned no Indian exchange announcement text-classification corpus.
  (Searches run against `https://huggingface.co/api/datasets?search=…`.)
- **No published benchmark for this exact task in OpenAlex.** A filtered OpenAlex query on
  `title_and_abstract.search:"corporate announcements India classification natural language"`
  returned **count: 0** (https://api.openalex.org/works).
- arXiv searches for `abs:"Indian" AND abs:"stock" AND abs:"event"`,
  `all:"NSE India" … AND abs:NLP`, and `abs:"corporate actions" AND abs:"text"` returned nothing on
  announcement event typing (http://export.arxiv.org/api/query).

**Consequence: you have no external labelled Indian event corpus to fine-tune or validate on. The only
path to a labelled set is to scrape NSE yourself and label it. That is cheap and you should do it.**

---

## Models available

| Model id | Size | Trained on | Licence | Indian-specific? | Usable? |
|---|---|---|---|---|---|
| `convaiinnovations/laya` | 421M, ModernBERT-large, 512 ctx | RLCD typed decisions; English | **Apache-2.0** | No | yes — what you have |
| `convaiinnovations/laya-multilingual` | 322M, mmBERT-base, 1k ctx (8k) | same, 100+ languages | Apache-2.0 | No | yes |
| `convaiinnovations/laya-typed-decisions` | 421M | fine-tuned on `LocalLLaMA/typed-decisions` | Apache-2.0 | No | yes — proves the fine-tune path |
| `ai4bharat/indic-bert` | ALBERT, 12 Indic langs + English | IndicCorp | **MIT** | Indic (not financial) | good base if text is non-English; your `attchmntText` is English, so probably not needed |
| `ProsusAI/finbert` | ~110M BERT | Financial PhraseBank, 3-class sentiment | **no licence declared in cardData metadata** (verified via HF API `cardData`) | No | sentiment only, not event typing; licence unresolved |
| `yiyanghkust/finbert-pretrain` | 110M | financial corpus continued pretraining | no licence declared in cardData | No | pretrain-only |
| `yiyanghkust/finbert-tone` | 110M | Financial PhraseBank sentiment | no licence declared in cardData | No | sentiment only |
| `StephanAkkerman/FinTwitBERT-sentiment` | 109,755,651 params | Twitter/StockTwits | **MIT** | No | sentiment only |
| **`Aadhil-rog/finbert-indian-sentiment-v2`** | BERT-base | **`kdave/Indian_Financial_News` (26k rows, GPT-labelled)** | **Apache-2.0** | **Yes** | 39 downloads, 0 likes, no eval reported. Sentiment, not events. Weak labels. |
| `alexcruse07/indian-equity-sentiment-model` | DistilBERT (67M base) | Indian equity sentiment | **Apache-2.0** | **Yes** | 46 downloads, 0 likes, no reported metrics, no declared training data. Sentiment only. |
| `techkiyan/indian-financial-news-ner-gliner-v1` | GLiNER medium | Indian financial news NER | **`other` (unspecified)** | **Yes** | token NER, not sentence event typing; unusable licence |
| `distilbert/distilbert-base-uncased` | 66,985,530 params | generic | **Apache-2.0** | No | sensible small fine-tuning baseline |
| `ProsusAI/finbert` / `yiyanghkust/finbert-esg` / `turing-usp/FinBertPTBR` | ~110M | various | mixed | No | sentiment/ESG; not event typing |

**Direct answer to "is there a model fine-tuned on Indian filings specifically?"**
**No.** The closest three are `Aadhil-rog/finbert-indian-sentiment-v2` (39 downloads, 0 likes, trained
on GPT-labelled Indian financial *news*, not filings, and it is a 3-class sentiment head),
`alexcruse07/indian-equity-sentiment-model` (46 downloads, 0 likes, no declared data, no metrics), and
`techkiyan/indian-financial-news-ner-gliner-v1` (3 downloads, unusable licence). None is an event
classifier, none reports a metric, none has meaningful adoption. **Licensing is fine** (Apache-2.0 /
MIT for the usable ones); the problem is that nothing exists to download.

---

## What practitioners actually ship

| System | URL | Stars | Licence | Pipeline | Reported accuracy/latency |
|---|---|---|---|---|---|
| **nifty-alpha-engine** | https://github.com/tarun-rai21/nifty-alpha-engine | **0** | MIT | Docker scheduled ingestion of NSE corporate announcements + business news → `data/raw/` → **"Event Normalization": text → `{stock, event_type, timestamp, sentiment}`** → PostgreSQL → feature engineering (event category, sentiment, novelty, frequency) → **scikit-learn / XGBoost** ranking with confidence → **rule-based deterministic explanations** → FastAPI + React → event-time backtesting | **None reported.** The extraction method for `event_type` is not documented anywhere in the README. No accuracy, no F1, no latency. 0 stars, last pushed 2026-07-10. |
| **Agentic-Market-Monitor** | https://github.com/indresh-singh/Agentic-Market-Monitor | 1 | none | LangGraph agents: Scraper (NSE) → **Classifier Agent** → Earnings Agent → Risk/Market-Reaction/Alert/Communication. Classifier = **`OPENAI_MODEL=gpt-4o-mini`** | None reported. |
| **FabTrader "Extracting Corporate Announcements From NSE Using Python"** (2025-03-18) | https://fabtrader.in/blog/extracting-corporate-announcements-from-nse-using-python | n/a | n/a | `NseUtility` + pandas DataFrame of `sm_name`, `attchmntText`, `desc`, `attchmntFile`, PDF URLs. "Once the data lands in a pandas DataFrame… **you can tag important event dates**". **No ML classifier at all.** | None |
| **nsepy** | https://github.com/swapniljariwala/nsepy | 808 | NOASSERTION | Data fetch only | n/a |
| **nsetools** | https://github.com/vsjha18/nsetools | 907 | MIT | Realtime NSE data only | n/a |
| **nsepython** | https://github.com/aeron7/nsepython | 368 | GPL-3.0 | Unofficial NSE API wrapper | n/a |
| **jugaad-data** | https://github.com/jugaad-py/jugaad-data | 582 | none | Live/historical Indian market data | n/a |
| **zerodha/kiteconnectjs** | https://github.com/zerodha/kiteconnectjs | 400 | MIT | Broker API client | n/a |
| **RelativelyBurberry/Indian-Stock-News-Sentiment-Analysis** | https://github.com/RelativelyBurberry/Indian-Stock-News-Sentiment-Analysis | 6 | MIT | "collecting Indian stock market news, mapping articles to NSE tickers, and performing **FinBERT-based sentiment analysis**" | None |
| **hanitha9/NSE_scraping** | https://github.com/hanitha9/NSE_scraping | 2 | none | NSE scraper + **OpenAI API** query handling | None |
| Zerodha / Groww / Trendlyne NLP stacks | — | — | — | **No open-source event-extraction pipeline found from any of them.** `[UNVERIFIED — not exhaustively searched; their pipelines are closed/proprietary]` | — |

**GitHub search for `"NSE announcement"`: 47 repositories total.** Every one is a scraper, dashboard
or alert app. Highest star count in the entire result set is **7**
(`hirawatt/BSE_NSE_Announcement`, MIT). **Not one ships an event classifier with reported accuracy.**

### What that table actually means

1. Nobody in the Indian ecosystem publishes a benchmark for this task, because the practical
   products (Zerodha, Groww, Trendlyne) don't classify event types from `attchmntText` at all — they
   surface the announcement as-is and let the human read it. The `desc` field NSE already ships is a
   **coarse exchange-assigned category**, which is very likely what a shipping product uses instead
   of inferring its own taxonomy.
2. The one open-source Indian event pipeline with a stated architecture (`nifty-alpha-engine`) uses
   **scikit-learn/XGBoost for ranking and rule-based deterministic text processing for
   normalisation** — no small LM, no prompt engineering.
3. The one open-source agentic Indian announcement system uses **an LLM (`gpt-4o-mini`)** as the
   classifier.
4. **No practitioner in this space reports a number.** You cannot benchmark yourself against a
   competitor, because there is no competitor figure to benchmark against.

---

## Has anyone used Laya (or a similar typed-decision model) on finance?

**Effectively no. One adjacent project exists, and it reports a negative result.**

GitHub repository search for `laya model finance` returns **total: 1**:

- **`siva-sub/mandate-1`** — https://github.com/siva-sub/mandate-1 (0 stars, **Apache-2.0**,
  pushed 2026-09-21). "SAFR-inspired agentic finance research… I tried custom Needle 3 and GLiNER 2.5
  fine-tunes, then Laya." It ships a **fine-tuned ("distilled") Laya checkpoint** at
  `huggingface.co/sivasub987/mandate-1-laya` on **synthetic AML/CFT data** and reports:

  | Evidence | Observation | What it does not establish |
  |---|---|---|
  | Distilled Laya, synthetic test | 84.2% accuracy; 68.3% complete-pair accuracy; **18.3% false-clear rate** | Readiness to authorise financial actions |
  | Distilled Laya, near-OOD | 91.7% accuracy; 83.3% pair accuracy; 16.7% false-clear rate | Robustness to arbitrary new institutions/workflows |

  The author writes: *"The compact student improved over the earlier template-trained checkpoint but
  still misses important contradictions. We publish that negative result rather than lower the safety
  bar to call it production-ready."* And critically: *"The Laya checkpoint is **shadow-only** and does
  not power the live reference harness."*

  **This is the closest prior art to your problem, and its shape is exactly yours: base/template-trained
  Laya underperformed, fine-tuning helped a lot (84.2%), and OOD performance was not trusted. The
  author shipped a DeepSeek LLM reference path alongside, not instead of, the small model.**

- GitHub issue search `repo:NandhaKishorM/laya finance OR financial` → **total: 0**. No finance
  request or report exists in the Laya issue tracker.
- The rest of the Laya ecosystem (236 repos matching `laya decision model`) is games, robot
  controllers, CLI safety gates, MCP servers, MLX/ONNX/Rust/Go runtimes
  (`mizorewww/laya-mlx` 6571★, `ollaya-dev/ollaya` 875★, `receptron/laya` 568★, `wfzyx/von` 753★).
  **No financial application.**

**Verdict: nobody has used Laya for financial event typing, and the one finance-adjacent user reached
the same place you did — fine-tune or use an LLM.**

---

## What people say about the honest ceiling of small models here

The most authoritative statement is Laya's own, since Laya is the model in question:

> **"Base checkpoints are near chance on typed-decisions zero-shot — 0.362 here and 0.352 for
> multilingual, against a 0.318 random and 0.461 majority-class baseline. The 0.766 belongs to the
> checkpoint fine-tuned on that benchmark's own training split. Laya is a fast base to specialise,
> not a zero-shot decision engine."**
> — https://huggingface.co/convaiinnovations/laya ("Honest Limits")

> **"The base checkpoints sit below the majority-class baseline here — the capability on this
> benchmark comes from fine-tuning."**
> — https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md

Four more documented ceilings from the same source, each of which explains one of your four failed
experiments:

1. **Label-space ceiling (explains failure 1 — contrast clauses).** *"banking77 is the one clear loss,
   and it is architectural: a choice question's options share a fixed `head_max_len` budget… Both
   checkpoints score **exactly 0.425**, which is what you would expect from a budget ceiling rather
   than a capability gap. **Keep choice questions under ~20 options.**"*
2. **Confidence is not usable for routing (explains failure 3 — gate never fired).**
   *"**Ships over-confident**… Do this on your own data before trusting the probabilities."* Raw ECE
   is 0.466 before temperature fitting, and even after fitting the model is confident-but-wrong:
   *"The English checkpoint collapses on non-Latin scripts (Khmer scores **0.000 accuracy at 0.952
   confidence**). Because the model stays confident while being wrong, **confidence gating cannot save
   you**."* Your gate reporting 0.50–0.64 with no confidence above 0.70 is the same pathology in milder
   form.
3. **`noul`/binary questions can answer from their own option labels, not the state (explains failure
   2 — the 20/24 gate).** *"`noul` can follow its option labels instead of the state, most strongly on
   this English checkpoint… returning a confident 'no' for clearly positive input ([#156]). Check
   `noul` answers on your own data. If they look stuck, ask the same question as a two-option
   `choice` with neutral keys and your yes/no wording as the descriptions."* Your 9-way classifier
   "cannot use" the gate in the same forward pass is exactly the documented architectural property:
   one forward pass, no composition, no conditioning of question B on the answer to question A.
4. **Ordinal `score` is the weakest primitive** (SST-5 0.372) — don't build the taxonomy on `score`
   questions.

Independent corroboration that "model scale alone" is not the lever, and that even zero-shot LLMs
are weak on this text: arXiv 2603.20965 found the **best single zero-shot LLM classifier on real
corporate disclosures scored only 0.566 balanced accuracy**, and the honest win came from
**supervised aggregation over model outputs (0.606)**, not from better zero-shot reasoning. Their
abstract's conclusion: *"the strongest gains come from supervised aggregation rather than from
zero-shot voting alone."*

---

## RECOMMENDATION FOR US

**(b) fine-tune the domain model — and change the unit of work from prompt engineering to data
engineering. Do not keep editing the question set. Do not abandon Laya for this domain yet. Do not
put an LLM on the critical path yet.**

Reasoning, grounded only in the fetched evidence:

**1. Your diagnosis is confirmed, and it is stronger than you think.** Laya's own model card reports
**0.361** zero-shot on its own typed-decision benchmark — *below* its majority-class baseline. Your
**0.43 macro-F1 on a 9-way held-out Indian financial task is above Laya's published zero-shot number.**
You are not underperforming Laya. You are performing as Laya documents it performs. Four rounds of
question-set editing were, in the published evidence, a search in a space where the answer is known to
be 0.36.

**2. The five-way choice set you listed is wrong, and this is a judgement call you can make now.**
- ~~(a) keep tuning the question set~~ — **no.** Laya's BENCHMARKS.md explains why your failures 1–4
  happened, item by item, before you tried: label budget ceiling, confidence that cannot gate,
  `noul` answering from its own labels, one-pass non-composition. You re-derived all four.
- ~~(d) abandon the typed-decision approach~~ — **no, not yet.** Laya's own fine-tuned checkpoint hits
  **0.766** on a 2,000-decision, 4-workflow benchmark, above the 0.735 teacher ceiling, using **4
  epochs on Kaggle's free 2× T4 GPUs** with a published notebook. The `siva-sub/mandate-1` finance
  project reached 84.2% on synthetic AML data with a fine-tuned Laya. The architecture is not the
  blocker. **Untrained use of it is.**
- ~~(c) LLM for extraction~~ — **not yet, but build the escape hatch.** No practitioner publishes an
  LLM classifier number for this exact task, and the one independent study of zero-shot LLMs on
  real disclosures (arXiv 2603.20965) got **0.566** balanced accuracy on the *easier* target of
  next-day return direction. LLM extraction is not free accuracy.

**3. The binding constraint is data, and it is a solvable, cheap problem.** There is no public
labelled NSE/BSE event corpus — verified across HuggingFace datasets search, arXiv, and a filtered
OpenAlex query returning **count: 0**. So the only way to get supervision is to label NSE
announcements yourself, and NSE publishes them for free. The fine-tune recipe that took Laya from
0.362 → 0.766 used **~1,600 training decisions** (2,000 minus the 400-case test split). You have 120
test examples today. **Target 3,000–5,000 labelled `attchmntText` → event-class examples within two
weeks** — with a deliberate, documented decision to keep your 120-example set as a pure held-out set
and a second disjoint slice as a dev set. Do not train on either.

**4. Do three cheap things before you train anything, in this order.**
   a. **Check whether NSE's own `desc` field is already a usable label.** If it is a coherent
   exchange-assigned category, a rules/lookup baseline against it may beat 0.43 for near-zero cost,
   and it becomes your floor. If it is too coarse, say so and discard it.
   b. **Establish the trivial baselines you are missing**: majority class, TF-IDF + logistic
   regression, and a fine-tuned `distilbert-base-uncased` (66.99M, Apache-2.0). If a 67M DistilBERT
   beats 421M Laya zero-shot on your own data — and FiNER's BiLSTM beat plain BERT — then you have
   proof that model size is not your lever and fine-tuning is.
   c. **Refit Laya's temperature on your data before trusting any confidence number.** Laya reports raw
   ECE 0.466 → 0.081 after one temperature per (question type, option count). Until you do this, every
   confidence-gated idea you try (including the failed hierarchical router) is being evaluated on
   numbers that are known to be badly miscalibrated.

**5. Architecture changes to make now, all cheap, all evidence-backed.**
   - **Drop the binary gate and the hierarchical router.** Both are documented dead ends for a
     one-pass encoder with unusable confidence. Do not spend a fifth iteration there.
   - **Keep the question count under ~20 options** (you have 9 — fine) and **raise
     `agent.cfg["head_max_len"]` from the 192 default** so each of your 9 class descriptions gets real
     token budget. Laya's Banking77 diagnosis is that 77 options get ~4 tokens each and stop being
     distinguishable; check whether 9 options are also being squeezed.
   - **Convert the binary gate to a two-option `choice` with neutral keys** (Laya issue #156's own
     workaround) — not to make routing work, but so the signal is at least not self-contaminated if
     you keep it as a diagnostic.
   - **Do not build the taxonomy on `score` questions** — documented weakest primitive (SST-5 0.372).

**6. Define the decision gate up front, per your own loop protocol.** Write into `docs/loop/` the
number at which you stop: if a fine-tuned Laya on ≥3,000 labelled examples does not reach **≥0.65
macro-F1 on the untouched 120-example held-out set**, the typed-decision approach is refuted for this
domain and you move to the LLM path. 0.65 is chosen because it is roughly the midpoint of
Laya's own published fine-tuned 0.766 and the ~0.50 ceiling it documents for zero-shot use, and
because it is well above the 0.50–0.60 that even *zero-shot frontier LLMs* achieved on real
disclosures (arXiv 2603.20965). Pre-committing the number is what stops the fifth and sixth
question-set edit from happening.

**7. Pre-build the LLM fallback in parallel, not instead.** `siva-sub/mandate-1` — the only
finance-adjacent Laya deployment anywhere — kept a small fine-tuned model *and* a DeepSeek reference
path, and shipped the small model shadow-only. The one Indian open-source agentic announcement
classifier (`Agentic-Market-Monitor`) uses `gpt-4o-mini`. Wire an LLM extraction path as a
shadow/comparison channel from day one, so you have a measured A/B on your own data when the gate
fires.

**One thing to be honest about in the write-up:** even after fine-tuning, the strongest published
number on comparable financial text is FiNER-139's **m-F1 78.0** — and that is a 139-class *token
tagging* task on 1.1M sentences of clean SEC prose. Your task is 9-way *sentence* classification on
154-character noisy headline fragments. Published Indian-financial text results of 0.93+ (SEntFiN) are
3-class sentiment with a strong, easily-separated label signal. **A 0.65–0.75 macro-F1 outcome on your
120-example set is a realistic target; 0.90 is not, and any doc or UI copy implying otherwise should
be corrected.**

---

## Search method / reproducibility

- arXiv API: `http://export.arxiv.org/api/query?search_query=…` (requires following the 301 to HTTPS).
  Queries run: `all:"financial event extraction"`, `abs:"XBRL"`, `ti:"FinQA" OR ti:"DocFinQA" OR
  ti:"FinTral" OR ti:"MultiHiertt"`, `abs:"Indian" AND abs:"stock" AND abs:"event"`,
  `all:"NSE India" … AND abs:NLP`, `abs:"corporate actions" AND abs:"text"`, `id_list=2305.12257`.
- HuggingFace API: `https://huggingface.co/api/models?search=…`, `/api/datasets?search=…`,
  `/api/models/{id}`, `/api/datasets/{id}`, `/api/models?author=convaiinnovations`.
- GitHub API: `https://api.github.com/search/repositories?q=…&sort=stars`,
  `https://api.github.com/search/issues?q=repo:NandhaKishorM/laya+finance…`.
- OpenAlex: `https://api.openalex.org/works?search=…` and
  `?filter=title_and_abstract.search:…`. (Rate-limits at ~2 req/s; 429s encountered and retried.)
- Direct fetches: `arxiv.org/abs/…`, `arxiv.org/pdf/…` (PDF text extracted with `pdfminer.six`),
  `huggingface.co/{models,datasets}/*/raw/main/README.md`,
  `raw.githubusercontent.com/…`, `fabtrader.in`, `github.com/siva-sub/mandate-1`.
- **Search engines were not usable**: `html.duckduckgo.com` and `lite.duckduckgo.com` returned HTTP
  202 challenge pages after ~8 queries; `www.mojeek.com` returned a 5,520-byte stub; `www.bing.com`
  returned unrelated cached results. All findings above therefore come from **structured APIs and
  primary source documents**, not from search-engine summaries. This biases the survey toward
  indexed/structured sources and may miss non-indexed blog posts.
- **`bhavya.ai` did not resolve** (`getaddrinfo ENOTFOUND bhavya.ai`, both via curl and the URL
  fetcher). Laya's `convaiinnovations` HF org is an India-based org and Bhavya.ai is widely described
  as its commercial terminal, but **I could not verify it, and it is excluded from all claims above.**
  `[UNVERIFIED]`
- Licences were read from the HuggingFace `cardData.license` field via the API, not from the model
  card prose. `ProsusAI/finbert`, `yiyanghkust/finbert-pretrain` and `yiyanghkust/finbert-tone`
  returned `license: None` — that is a *verified absence of a declared licence*, which has commercial
  consequences and should be checked against the repos before use.

### Working files

All raw fetches are in `/tmp/divya-research/`: `laya_card.md`, `laya_bench.md`, `nae.md`, `amm.md`,
`finner.pdf`/`finner.txt`, `finbert.pdf`/`finbert.txt`, `nb.ipynb`, and the search helpers
`ax.py` (arXiv), `oa.py` (OpenAlex), `gh.py` (GitHub), `bing.py`/`eng.py` (search engines, both
blocked).
