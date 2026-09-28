# Divya — reproducible setup and checks.
#
# venv + Makefile is the *verified* path in this environment. Docker is unavailable here, so
# Dockerfile/compose are authored but labelled UNVERIFIED-IN-THIS-ENV rather than claimed to
# work. See docs/loop/DECISIONS.md D-002.

PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
SRC := src

.DEFAULT_GOAL := help
.PHONY: help setup setup-full test lint typecheck check fixtures bench doctor decide \
        eval eval-real protocol clean docker-verify serve up frontend-install \
        frontend-build frontend-dev bench-resources

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install -q --upgrade pip

setup: $(BIN)/python  ## core install: enough to load the protocol, run the loop and the tests
	$(BIN)/python -m pip install -q -e '.[dev]'
	@echo "core installed. run 'make setup-full' for laya + rich + eval extras."

setup-full: $(BIN)/python  ## full install including System-1 (torch CPU + laya) — large download
	$(BIN)/python -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu
	$(BIN)/python -m pip install -q -e '.[all,dev]'
	@echo "full installed. run 'make doctor' to confirm."

test:  ## run the test suite
	PYTHONPATH=$(SRC) $(BIN)/python -m pytest tests/ -q

lint:  ## ruff
	$(BIN)/ruff check src tests evals research

typecheck:  ## mypy
	PYTHONPATH=$(SRC) $(BIN)/mypy src/divya

check: lint typecheck test  ## everything CI runs

fixtures:  ## regenerate the synthetic evaluation dataset (deterministic, seed 20260928)
	$(BIN)/python evals/make_dataset.py

protocol:  ## load and print the decision protocol
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.cli protocol show

doctor:  ## report what actually works in this environment
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.cli doctor

decide:  ## example single-event run with the full terminal view and trace
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.cli decide --trace --width 100 --text \
	  "Sun Pharma Limited has informed the Exchange about the change in its statutory auditors. \
M/s. Price Waterhouse & Co Chartered Accountants LLP have intimated their resignation from the \
office with effect from 30 November 2025, citing that they are not in a position to continue \
due to inadequacy of records relating to certain subsidiaries. The Company has initiated the \
process of appointing a new statutory auditor."

bench:  ## measure System-1 latency and quality on this machine
	PYTHONPATH=$(SRC) $(BIN)/python research/scripts/bench_laya.py --repeat 3

bench-resources:  ## measure the free performance levers (batching, persistence, ONNX)
	PYTHONPATH=$(SRC) $(BIN)/python research/scripts/bench_resources.py

eval:  ## A/B/C/D on the synthetic dataset (deterministic; no live data)
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.eval.harness \
	  --dataset evals/datasets/event_triage_v1.jsonl --arms A B C D --limit 60 \
	  --out evals/results/synthetic_eval.json

eval-real:  ## A/B/C/D on REAL NSE announcements. Rebuild the dataset first if it is missing.
	@test -f evals/datasets/nse_announcements_v1.jsonl || $(BIN)/python evals/build_real_dataset.py --measurable-only
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.eval.harness \
	  --dataset evals/datasets/nse_announcements_v1.jsonl --arms A B C D --limit 150 \
	  --out evals/results/real_eval.json

fetch:  ## pull 7 days of live NSE announcements into data/store
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.cli fetch nse-announcements --days 7 --limit 500

# --- web frontend (Space UI) ---------------------------------------------
frontend-install:  ## install frontend dependencies
	cd frontend && pnpm install

frontend-build:  ## typecheck + lint + production build
	cd frontend && pnpm exec tsc --noEmit && pnpm exec eslint src && pnpm build

frontend-dev:  ## run the Space UI dev server on :3000
	cd frontend && pnpm dev

serve:  ## run the API on 127.0.0.1:8000
	PYTHONPATH=$(SRC) $(BIN)/python -m divya.api

up:  ## api + frontend together (two terminals; the api is the source of truth)
	@echo "1) make serve    2) make frontend-dev    then open http://localhost:3000"

docker-verify:  ## run the compose path. Only meaningful where docker exists.
	@command -v docker >/dev/null 2>&1 || { \
	  echo "docker is not available in this environment."; \
	  echo "The venv path above is the VERIFIED reproducible path; the compose files are"; \
	  echo "authored but UNVERIFIED-HERE. See docs/loop/DECISIONS.md D-002."; exit 1; }
	docker compose up --build

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache **/__pycache__
