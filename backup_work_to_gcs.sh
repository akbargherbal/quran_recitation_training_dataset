#!/usr/bin/env bash
# One-shot backup of ALL work done since the dataset download:
#   - code, tests, docs, ops scripts
#   - a clean snapshot of the expensive scores.csv
#   - logs and any generated artifacts (thresholds/plots/review/results)
#
# The ~5.6 GB source dataset is NOT included (always re-downloadable from GCS).
# Run this now, and again after calibrate/review/filter, to keep a resume point.
#
# Usage:
#   ./backup_work_to_gcs.sh
# Env:
#   GCS_DEST  destination prefix (default below)
set -u
cd "$(dirname "$0")"

GCS_DEST="${GCS_DEST:-gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter}"

WORK="$(mktemp -d /tmp/aqf_work.XXXXXX)"
STAGE="$WORK/stage"
mkdir -p "$STAGE"

# --- Clean snapshot of scores.csv (drops any trailing partial row) -----------
if [ -f scores.csv ]; then
  python3 - scores.csv "$STAGE/scores.csv" <<'PY'
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
print(f"scores.csv rows={len(rows)}", file=sys.stderr)
PY
fi

# --- Assemble the work tree (explicit list; excludes data/, refs/, caches) ---
ITEMS=(
  aqfilter tests pyproject.toml requirements.txt review_app
  README.md SPEC_audio_quality_filter.md IMPLEMENTATION_PLAN.md RUNBOOK.md
  SESSION_STATE.md RESTORE_NEXT_SESSION.md FILTERED_DATASET_README.md
  refs.txt run_score_loop.sh backup_to_gcs.sh backup_work_to_gcs.sh
  score.log backup.log download.log
  thresholds.json thresholds_k0.25_all6.json plots results review review.zip review2 review2.zip
)
for item in "${ITEMS[@]}"; do
  [ -e "$item" ] && cp -r "$item" "$STAGE/" 2>/dev/null
done

STAMP="$(date -u +%Y%m%d_%H%M%S)"
tar --exclude='*/__pycache__' --exclude='*.pyc' \
    -czf "$WORK/aqfilter_work_latest.tar.gz" -C "$STAGE" .
cp "$WORK/aqfilter_work_latest.tar.gz" "$WORK/aqfilter_work_${STAMP}.tar.gz"

if [ -f "$STAGE/scores.csv" ]; then
  ROWS="$(python3 -c "import csv; print(sum(1 for _ in csv.DictReader(open('$STAGE/scores.csv'))))")"
else
  ROWS=0
fi
{
  echo "updated=$(date -u +%FT%TZ)"
  echo "scores_rows=$ROWS"
  echo "archive=aqfilter_work_latest.tar.gz"
} > "$WORK/status.txt"

gcloud storage cp "$WORK/aqfilter_work_latest.tar.gz" "$GCS_DEST/work/aqfilter_work_latest.tar.gz"
gcloud storage cp "$WORK/aqfilter_work_${STAMP}.tar.gz" "$GCS_DEST/work/aqfilter_work_${STAMP}.tar.gz"
[ -f "$STAGE/scores.csv" ] && gcloud storage cp "$STAGE/scores.csv" "$GCS_DEST/work/scores.csv"
gcloud storage cp "$WORK/status.txt" "$GCS_DEST/work/status.txt"

# Listening material as a direct download (also inside the work tarball).
if [ -f review.zip ]; then
  gcloud storage cp review.zip "$GCS_DEST/review/review.zip"
  echo "uploaded $GCS_DEST/review/review.zip"
fi

# Verification-round listening material (new thresholds), direct download.
if [ -f review2.zip ]; then
  gcloud storage cp review2.zip "$GCS_DEST/review/review2.zip"
  echo "uploaded $GCS_DEST/review/review2.zip"
fi

# Self-contained review bundle (app + clips) as a direct download.
if [ -f aqfilter_review_app.zip ]; then
  gcloud storage cp aqfilter_review_app.zip "$GCS_DEST/review/aqfilter_review_app.zip"
  echo "uploaded $GCS_DEST/review/aqfilter_review_app.zip"
fi

echo "--- backup contents ---"
tar -tzf "$WORK/aqfilter_work_latest.tar.gz" | sed 's#^\./##' | grep -v '/$' | sort
echo "--- uploaded ---"
gcloud storage ls -l "$GCS_DEST/work/" 2>&1
rm -rf "$WORK"
