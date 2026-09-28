#!/usr/bin/env bash
# Guard against the failure that actually happened: two Laya processes at once on a 7.5 GiB
# box, which is how this session was killed once already.
#
# Laya's checkpoint is ~2.8 GB resident. Two of them plus the OS, Ollama and another agent
# session is an OOM, and the symptom is a vanished process with no traceback.
#
# Usage:
#   research/scripts/with_laya_guard.sh <command> [args...]
#
# Takes an exclusive lock for the duration. If a Laya process is already running, prints what is
# holding the lock and exits 75 (EX_TEMPFAIL) rather than starting a second one. Refusing is
# the whole point: the alternative is being OOM-killed mid-write and losing the run.

set -uo pipefail

LOCK="${DIVYA_LAYA_LOCK:-/tmp/divya-laya.lock}"
TIMEOUT="${DIVYA_LAYA_LOCK_TIMEOUT:-0}"   # seconds to wait for the lock; 0 = fail immediately
AVAIL_MIN_MB="${DIVYA_LAYA_MIN_AVAIL_MB:-2500}"

have() { command -v "$1" >/dev/null 2>&1; }

avail_mb() { awk '/MemAvailable/ {print int($2)}' /proc/meminfo 2>/dev/null || echo 0; }

running_laya() {
  pgrep -af 'divya.eval.harness|bench_laya|bench_resources|divya.cli decide|divya.cli serve' \
    2>/dev/null | grep -v "$$" || true
}

if have flock; then
  exec 9>"$LOCK"
  if ! flock -n -w "$TIMEOUT" 9; then
    echo "REFUSED: another Laya process holds $LOCK" >&2
    running_laya | sed 's/^/    /' >&2
    echo "Wait for it, or set DIVYA_LAYA_LOCK_TIMEOUT to wait." >&2
    exit 75
  fi
fi

avail=$(avail_mb)
if [ "$avail" -lt "$AVAIL_MIN_MB" ]; then
  echo "REFUSED: only ${avail} MiB available, need ${AVAIL_MIN_MB} MiB for the checkpoint." >&2
  echo "Free something first, or set DIVYA_LAYA_MIN_AVAIL_MB lower at your own risk." >&2
  exit 75
fi

# Torch is told to keep its thread pool bounded. A 421M model on 16 vCPUs will otherwise take
# every core and starve the Ollama server and anything else on the box, which looks like a
# hang even when it is only contention.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-8}"

echo "[guard] acquired; ${avail} MiB available, threads capped at ${OMP_NUM_THREADS}" >&2
exec "$@"
