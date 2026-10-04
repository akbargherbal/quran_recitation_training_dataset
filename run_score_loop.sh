#!/usr/bin/env bash
# Supervisor for the full scoring run.
# Re-runs `score --resume` until every MP3 has a row, so an external kill only
# costs the last in-flight batch. Safe to run repeatedly.
set -u
cd "$(dirname "$0")"

DATA="${DATA:-data}"
OUT="${OUT:-scores.csv}"
WORKERS="${WORKERS:-7}"
LOG="${LOG:-score.log}"
STDOUT_LOG="${STDOUT_LOG:-score.stdout.log}"

total=$(find "$DATA" -name '*.mp3' | wc -l)
echo "[$(date -u +%H:%M:%S)] supervisor start: $total mp3s, workers=$WORKERS" >> "$STDOUT_LOG"

while true; do
  PYTHONUNBUFFERED=1 python3 -m aqfilter score \
    --data "$DATA" --out "$OUT" --workers "$WORKERS" --resume --log "$LOG" \
    >> "$STDOUT_LOG" 2>&1
  rc=$?
  done_count=$(python3 - "$OUT" <<'PY'
import csv, sys
try:
    with open(sys.argv[1], newline="", encoding="utf-8") as fh:
        print(sum(1 for _ in csv.DictReader(fh)))
except Exception:
    print(0)
PY
)
  echo "[$(date -u +%H:%M:%S)] score exited rc=$rc; rows=$done_count/$total" >> "$STDOUT_LOG"
  if [ "$done_count" -ge "$total" ]; then
    echo "[$(date -u +%H:%M:%S)] supervisor: complete" >> "$STDOUT_LOG"
    break
  fi
  sleep 5
done
