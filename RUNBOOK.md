# Runbook — long scoring run on a VM

Scoring is the only expensive step. It is resumable and periodically
checkpointed to Google Cloud Storage, so a VM disconnect or restart costs at
most a few minutes of work.

## 1. Checkpoints

`backup_to_gcs.sh` uploads a cleaned snapshot of `scores.csv` every 10 minutes
(and on completion) to:

```
gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/checkpoints/
├── scores.csv     # cleaned, complete-rows-only snapshot (resume from this)
├── score.log      # running log
└── status.txt     # "rows=<N> updated=<timestamp>"
```

The snapshot drops any trailing partial line, so it is always a valid CSV.

One-shot upload (after later stages too):

```bash
ONCE=1 ./backup_to_gcs.sh
```

Change the destination or interval:

```bash
GCS_DEST=gs://my-bucket/prefix INTERVAL=300 ./backup_to_gcs.sh
```

## 2. Restore / resume after a disconnect

### Option A — full restore (code + docs + scores.csv), one command

```bash
DEST=gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter
TMP=$(mktemp -d)
gcloud storage cp "$DEST/work/aqfilter_work_latest.tar.gz" "$TMP/"
tar -xzf "$TMP/aqfilter_work_latest.tar.gz" -C /content/quran_recitations
# re-download the source dataset (it is never checkpointed), then resume:
gcloud storage cp -r gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/quran_dataset_AHH_long_aya/ ./data/
setsid bash run_score_loop.sh >/dev/null 2>&1 < /dev/null &
```

### Option B — scores only (freshest checkpoint)

```bash
gcloud storage cp \
  gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/checkpoints/scores.csv \
  ./scores.csv
setsid bash run_score_loop.sh >/dev/null 2>&1 < /dev/null &
```

Verify before resuming (unique filenames, no duplicates):

```bash
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("scores.csv")))
print("rows:", len(rows), "unique:", len({r["filename"] for r in rows}))
PY
```

`run_score_loop.sh` loops `score --resume` until every MP3 has a row, so even an
external kill only loses the last in-flight batch.

### Manual full work backup

```bash
./backup_work_to_gcs.sh      # tar of code/docs/logs + clean scores.csv -> $DEST/work/
```

## 3. Status

```bash
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("scores.csv")))
n, total = len(rows), 13501
print(f"{n}/{total} ({n/total*100:.1f}%)  decode_failures={sum(1 for r in rows if r['decode_ok']!='True')}")
PY
pgrep -af "aqfilter score" | grep -v pgrep
pgrep -af "backup_to_gcs.sh" | grep -v pgrep
```

## 4. After scoring (fast, no rescoring)

```bash
python3 -m aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json
python3 -m aqfilter plot      --scores scores.csv --refs refs.txt --out plots/ --thresholds thresholds.json
python3 -m aqfilter review    --scores scores.csv --thresholds thresholds.json --data data/ --out review/ --zip
# listen to review.zip, then adjust --k if needed and re-run calibrate/review
python3 -m aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/
```

Checkpoint the later artifacts too:

```bash
DEST=gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/artifacts
gcloud storage cp thresholds.json "$DEST/"
gcloud storage cp -r plots "$DEST/"
gcloud storage cp review.zip "$DEST/"
gcloud storage cp -r results "$DEST/"
```

## 5. Notes

- Never delete or modify the source MP3s under `data/`.
- `aqfilter` has no GCS integration by design; all cloud copying is in these
  ops scripts.
- `data/` is 5.6 GB and is not checkpointed — re-download it with
  `gcloud storage cp -r gs://.../quran_dataset_AHH_long_aya/ ./data/` if needed.
