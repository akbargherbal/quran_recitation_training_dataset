#!/usr/bin/env bash
# Periodically checkpoint the expensive scores.csv (and logs) to Google Cloud
# Storage so the run can be resumed after a VM disconnect/restart.
#
# GCS is deliberately kept OUT of the aqfilter tool (see SPEC 2): this is an
# ops/setup script. Safe to run repeatedly; uploads a cleaned snapshot.
#
# Usage:
#   ./backup_to_gcs.sh            # run the loop forever (until complete)
#   ONCE=1 ./backup_to_gcs.sh     # single snapshot + upload, then exit
#
# Env overrides:
#   SRC      local scores file           (default: scores.csv)
#   GCS_DEST destination prefix          (default below)
#   INTERVAL seconds between checkpoints (default: 600)
#   TOTAL    expected row count          (default: 13501)
set -u
cd "$(dirname "$0")"

SRC="${SRC:-scores.csv}"
GCS_DEST="${GCS_DEST:-gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/checkpoints}"
INTERVAL="${INTERVAL:-600}"
TOTAL="${TOTAL:-13501}"
LOG="${BACKUP_LOG:-backup.log}"

log() { echo "[$(date -u +%H:%M:%S)] $*" >> "$LOG"; }

# Write a clean, complete snapshot (drops any trailing partial/incomplete row)
# and print the row count on stdout.
snapshot() {
  python3 - "$SRC" "$1" <<'PY'
import csv, sys
src, dst = sys.argv[1], sys.argv[2]
header, rows = None, []
with open(src, newline="", encoding="utf-8") as fh:
    reader = csv.reader(fh)
    header = next(reader, None)
    if header:
        for rec in reader:
            if len(rec) == len(header):
                rows.append(rec)
with open(dst, "w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    if header:
        writer.writerow(header)
    writer.writerows(rows)
print(len(rows))
PY
}

checkpoint() {
  [ -f "$SRC" ] || { echo 0; return; }
  local tmp count
  tmp="$(mktemp /tmp/aqf_scores.XXXXXX.csv)"
  count="$(snapshot "$tmp")"
  if gcloud storage cp "$tmp" "$GCS_DEST/scores.csv" >/dev/null 2>&1; then
    log "uploaded scores.csv rows=$count"
  else
    log "UPLOAD FAILED rows=$count"
  fi
  printf 'rows=%s updated=%s\n' "$count" "$(date -u +%FT%TZ)" > /tmp/aqf_status.txt
  gcloud storage cp /tmp/aqf_status.txt "$GCS_DEST/status.txt" >/dev/null 2>&1 || true
  [ -f score.log ] && gcloud storage cp score.log "$GCS_DEST/score.log" >/dev/null 2>&1 || true
  rm -f "$tmp" /tmp/aqf_status.txt
  echo "$count"
}

log "checkpoint -> $GCS_DEST (interval ${INTERVAL}s)"
while true; do
  count="$(checkpoint | tail -1)"
  if [ "${ONCE:-0}" = "1" ]; then
    echo "checkpoint done: rows=$count -> $GCS_DEST/scores.csv"
    break
  fi
  if [ "${count:-0}" -ge "$TOTAL" ]; then
    log "reached $count/$TOTAL; final checkpoint done"
    break
  fi
  sleep "$INTERVAL"
done
