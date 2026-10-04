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
# FINAL settings (from the listening review; rationale in SESSION_STATE.md §1):
python3 -m aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json \
    --k 0.5 --drop-metric bandwidth_hz,bak_mos
python3 -m aqfilter plot      --scores scores.csv --refs refs.txt --out plots/ --thresholds thresholds.json
# optional verification round against the new boundary:
python3 -m aqfilter review    --scores scores.csv --thresholds thresholds.json --data data/ --out review2/ --zip
python3 -m aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/

# `--drop-metric NAME` (repeatable or comma-separated) excludes a metric from every
# reciter's thresholds; recorded as `dropped_metrics` in thresholds.json.
# `--k-reciter NAME=VAL` (repeatable) overrides k per reciter.
# Round-1 calibration (k=0.25, all six metrics) is preserved at
# thresholds_k0.25_all6.json for quick A/B.
```

Checkpoint the later artifacts (`backup_work_to_gcs.sh` also uploads
`review.zip` to the direct-download path automatically):

```bash
cd /content/quran_recitations
./backup_work_to_gcs.sh          # tar of code/docs/logs + scores.csv + review.zip

# or copy individual artifacts to their canonical prefixes:
BASE=gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter
gcloud storage cp thresholds.json "$BASE/work/artifacts/"
gcloud storage cp -r plots        "$BASE/work/artifacts/"
gcloud storage cp review.zip      "$BASE/review/review.zip"   # direct download
gcloud storage cp -r results      "$BASE/work/artifacts/"
```

Canonical GCS prefixes:

| Prefix | Contents |
|---|---|
| `.../aqfilter/checkpoints/` | periodic `scores.csv` + `score.log` + `status.txt` |
| `.../aqfilter/work/` | code/docs/logs tarballs + clean `scores.csv` |
| `.../aqfilter/review/` | `review.zip` (listening material) + `aqfilter_review_app.zip` (app bundle) |

Binary/media artifacts (`review.zip`, the app bundle, MP3s) are **not** pushed to
GitHub — source only.

### 4.1 Listening-review app

`review_app/` is a small Flask UI for judging the clips and exporting the
verdict. The self-contained bundle (app + `review/`) is published to
`.../aqfilter/review/aqfilter_review_app.zip`:

```bash
gcloud storage cp gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/review/aqfilter_review_app.zip .
unzip aqfilter_review_app.zip && cd aqfilter_review_app
python -m pip install flask
python review_app/app.py            # http://127.0.0.1:5000
```

Click **Export report** when done: it writes `./review_report/review_report.json`
and `review_report.md` (the JSON is what the next calibration step consumes).
Run tests with `cd review_app && python -m unittest discover -s tests -v`.

## 5. Notes

- Never delete or modify the source MP3s under `data/`.
- `aqfilter` has no GCS integration by design; all cloud copying is in these
  ops scripts.
- `data/` is 5.6 GB and is not checkpointed — re-download it with
  `gcloud storage cp -r gs://.../quran_dataset_AHH_long_aya/ ./data/` if needed.
