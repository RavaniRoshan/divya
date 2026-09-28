# Divya container image.
#
# UNVERIFIED-IN-THIS-ENV: the machine this project was built on has no docker binary, so this
# file has never been executed. It is authored to be correct and it is not claimed to work.
# The verified reproducible path is `make setup && make check`. See docs/loop/DECISIONS.md D-002.
#
# Sizing notes, from measurement on the 7.5 GiB target box:
#   laya (torch CPU)  ->  ~2.8 GB RSS once a checkpoint is resident
#   System-2 (3B)     ->  ~1.9 GB via Ollama
# Those two together leave very little headroom. The image therefore does NOT bundle a reasoning
# model: point DIVYA_S2_BASE_URL at an Ollama host, or run with DIVYA_S2_PROVIDER=heuristic.

FROM python:3.12-slim AS base

# curl is for the healthcheck; ca-certificates for TLS to the data sources and the model server.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DIVYA_S2_PROVIDER=ollama \
    DIVYA_S2_BASE_URL=http://host.docker.internal:11434

WORKDIR /app

# Dependencies first so the layer caches across source edits. torch is pinned to the CPU wheel:
# this image targets small CPU-only boxes, and a CUDA torch is ~2.5 GB of dead weight there.
COPY pyproject.toml README.md ./
COPY src/divya/__init__.py src/divya/
RUN pip install --no-cache-dir \
      torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -e '.[all]'

COPY src/ src/
COPY models/ models/
COPY evals/ evals/
COPY research/ research/
COPY tests/ tests/
COPY Makefile ./

# Run unprivileged. The container needs no write access outside its data volumes.
RUN useradd --create-home --uid 10001 divya \
 && mkdir -p /app/data/store /app/data/traces /app/evals/results \
 && chown -R divya:divya /app
USER divya

EXPOSE 8000

# Reports what works inside the container rather than assuming. Exits 0 if the core runtime
# imports; System-1 absence is reported but is not a container failure, because the runtime
# degrades to System-2 only and says so.
HEALTHCHECK --interval=30s --timeout=20s --start-period=90s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "-m", "divya.cli", "doctor"]
