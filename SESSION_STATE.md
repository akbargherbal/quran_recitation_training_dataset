# SESSION STATE — start here (fresh-session handoff)

> **Purpose:** if you are an agent or human opening this repo in a **new session
> with no prior context**, read this file first. It records what has been done,
> where everything lives, how to check live status, and what remains.
>
> Keep this file updated as the pipeline advances.

**Project:** reference-calibrated audio quality filter for ~13,501 Quran
recitation MP3s. Full requirements are in
[`SPEC_audio_quality_filter.md`](SPEC_audio_quality_filter.md); design plan in
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md); ops/resume instructions in
[`RUNBOOK.md`](RUNBOOK.md).

---

## 1. Status snapshot

_As of **2026-10-04T07:32Z** (recompute with §4; do not trust this timestamp)._

| Stage | State |
|---|---|
| Dataset download | ✅ done, **13,501** MP3s, ~5.6 GB, at `data/quran_dataset_AHH_long_aya/` |
| Tool + tests | ✅ done, **12/12 tests pass** |
| Full `score` | ⏳ **in progress**, **6,372 / 13,501** rows (~47%), 0 decode failures |
| GCS checkpointing | ✅ running (every 10 min) |
| Code on GitHub | ✅ pushed (see §6) |
| `calibrate` / `plot` / `review` / `filter` | ⬜ not started (blocked on scoring) |

The next action when scoring finishes is **`calibrate` + `plot`, then STOP and
report to the user** (spec handoff step 3). See §7.

---

## 2. What the tool does

`aqfilter` (package in `aqfilter/`) has five subcommands:

```
aqfilter score     --data DIR --out scores.csv [--workers N] [--resume]
aqfilter calibrate --scores scores.csv --refs FILE_OR_DIR --out thresholds.json [--k 0.25] [--k-reciter NAME=VAL ...]
aqfilter plot      --scores scores.csv --refs FILE_OR_DIR --out plots/ [--thresholds thresholds.json]
aqfilter review    --scores scores.csv --thresholds thresholds.json --data DIR --out review/ [--n 5] [--zip]
aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/ [--copy-to DIR]
```

`score` is the only expensive step; everything else reads `scores.csv` and runs
in seconds. Metrics: DNSMOS (`ovrl_mos`, `sig_mos`, `bak_mos`, `p808_mos`) plus
classical (`noise_floor_db`, `speech_db`, `snr_est_db`, `silence_ratio`,
`clipping_ratio`, `bandwidth_hz`). Thresholds are calibrated per reciter from 9
reference clips (`refs.txt`). Definitions: [`README.md`](README.md).

---

## 3. Environment (verified)

- Linux VM, **8 vCPU**, ~50 GB RAM; Python **3.13.15**.
- libsndfile 1.2.2 with MP3 support; `ffmpeg` present (fallback decoder).
- `speechmos 0.0.1.1` + `onnxruntime 1.30.0` installed.
- `gcloud` authenticated as `ghurbal.akbar@gmail.com`; `gh` authenticated as
  `akbargherbal`.
- Working dir: `/content/quran_recitations`.

---

## 4. How to check live status

```bash
cd /content/quran_recitations

# progress (rows scored, duplicates, decode failures)
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("scores.csv")))
n, total = len(rows), 13501
print(f"{n}/{total} ({n/total*100:.1f}%)  unique={len({r['filename'] for r in rows})}"
      f"  decode_fail={sum(1 for r in rows if r['decode_ok']!='True')}")
PY

# are the jobs alive?
pgrep -af "aqfilter score"        | grep -v pgrep   # scorer (1 parent + 7 workers)
pgrep -af "run_score_loop.sh"     | grep -v pgrep   # restart supervisor
pgrep -af "backup_to_gcs.sh"      | grep -v pgrep   # checkpoint loop
tail -5 score.log backup.log
```

Note: the on-disk row count lags slightly because the writer flushes every 500
rows and the tqdm bar/vm buffer; the number above is good enough.

---

## 5. Background jobs currently running

All were launched detached with `setsid`, so they survive an SSH disconnect
while the VM stays up:

| Job | Script | Behavior |
|---|---|---|
| Scorer | `run_score_loop.sh` | loops `aqfilter score ... --resume` until all 13,501 rows exist; auto-restarts after a kill/crash |
| Checkpointer | `backup_to_gcs.sh` | every 10 min uploads a cleaned `scores.csv` snapshot; exits when complete |

To restart everything from scratch (e.g. after a VM reboot), see §6.

---

## 6. Backup & resume (GCS + GitHub)

### GCS locations
Bucket: `gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/`

| Path | Contents | Freshness |
|---|---|---|
| `checkpoints/scores.csv` | cleaned `scores.csv` (complete rows only) | every 10 min |
| `checkpoints/score.log` | running log | every 10 min |
| `checkpoints/status.txt` | `rows=<N> updated=<ts>` | every 10 min |
| `work/aqfilter_work_latest.tar.gz` | **all work**: code, tests, docs, ops scripts, logs, `scores.csv` | on demand |
| `work/aqfilter_work_<ts>.tar.gz` | timestamped history of the above | on demand |
| `work/scores.csv`, `work/status.txt` | clean scores + manifest | on demand |

Refresh the full work snapshot (run after every completed stage):
```bash
cd /content/quran_recitations && ./backup_work_to_gcs.sh
```

### GitHub (source code)
- Repo: https://github.com/akbargherbal/quran_recitation_training_dataset
- Commits: `e7cbe89` (package), `b488894` (ops scripts + runbook).
- Push new commits with `git push origin main`.

### Full restore after a disconnect / VM loss
```bash
DEST=gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter
TMP=$(mktemp -d)
gcloud storage cp "$DEST/work/aqfilter_work_latest.tar.gz" "$TMP/"
tar -xzf "$TMP/aqfilter_work_latest.tar.gz" -C /content/quran_recitations   # restores code + scores.csv
# dataset is never checkpointed (re-downloadable):
gcloud storage cp -r gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/quran_dataset_AHH_long_aya/ ./data/
# resume scoring:
cd /content/quran_recitations
setsid bash run_score_loop.sh   >/dev/null 2>&1 < /dev/null &
setsid bash backup_to_gcs.sh    >/dev/null 2>&1 < /dev/null &
```

Scores-only fallback: `gcloud storage cp "$DEST/checkpoints/scores.csv" ./scores.csv`
then start the two jobs above.

**Deliberately NOT backed up:** `data/` (5.6 GB, always re-downloadable — user's
explicit instruction). Never delete or modify the source MP3s.

---

## 7. What remains (ordered), with STOP gates

1. **Wait for scoring to finish** (all 13,501 rows). Verify 0 unexpected decode
   failures and no duplicate filenames. Dedupe (`drop_duplicates("filename")`)
   only if duplicates appeared.
2. `calibrate` → `thresholds.json` + printed per-reciter table; `plot` → PNGs +
   `summary.csv`. Persist: `./backup_work_to_gcs.sh`.
3. 🛑 **STOP AND REPORT** the threshold table + plots to the user (spec handoff
   step 3). **Do not choose `--k` autonomously.**
4. `review --zip` → `review.zip` (~45 clips); give user path/size. Persist.
5. 🛑 **STOP AND WAIT for the user's listening verdict** per reciter
   (too loose / about right / too strict).
6. Adjust `--k` (globally or `--k-reciter NAME=VAL`) → re-run `calibrate`
   (and `review` if wanted). **No rescoring.** Persist.
7. `filter` → `results/{keep.csv,reject.csv,summary.md,keep_list.txt}` (+ optional
   `--copy-to`). Persist.
8. Final delivery of all artifacts; keep `scores.csv` so future re-thresholding
   is free.

---

## 8. Key decisions, gotchas, fixed bugs

- **`--k` is NOT chosen yet.** It is decided only after the user listens to
  `review.zip`. The references span excellent→acceptable, so thresholds anchor
  at the *worst* reference minus `max(floor, k*iqr)`.
- **Two intentional stop gates** (spec §13): after `calibrate`/`plot`, and after
  `review`. Respect them.
- **BUG fixed:** `bandwidth_hz` was inflated by `np.convolve(mode="same")`
  zero-padding at the spectrum edge, and `EPS=1e-10` masked the true spectral
  floor. Fixed with edge-padded smoothing, a dedicated `SPECTRAL_EPS=1e-20`, and
  a contiguous-band edge search. Regression test in
  `tests/test_metrics_synthetic.py`.
- **`speechmos` import gotcha:** must use `from speechmos import dnsmos as
  sm_dnsmos` (the submodule is not an attribute until imported).
- **ONNX threads:** each worker forces `intra/inter_op_num_threads=1` via an
  `onnxruntime.InferenceSession` monkeypatch in `aqfilter/dnsmos_wrap.py`
  (`worker_init`), preventing CPU oversubscription at `--workers 7`.
- **Empty audio guard:** `speechmos` infinitely appends on a zero-length array;
  `run_dnsmos` rejects empty input first.
- **Corrupt files** (e.g. zero-byte) produce a `decode_ok=False` row, never a
  crash (verified).
- **`--resume`** keys on the `filename` column; re-running never rescoring done
  files.
- Benchmark ETA from the first 20 files underestimates the full run (early files
  are short); real throughput is ~1.0–1.4 s/file with 7 workers.

---

## 9. File map (repo root)

```
aqfilter/                     # the tool (cli, score, calibrate, plotting, review, filtering, metrics, ...)
tests/                        # 12 tests (naming, metrics synthetic, calibrate/filter, cli smoke)
data/                         # 13,501 source MP3s (NOT backed up, re-downloadable)
refs/                         # 9 extracted reference MP3s
refs.txt                      # 9 reference basenames (threshold anchors)
scores.csv                    # THE expensive artifact (checkpointed to GCS)
thresholds.json               # generated by calibrate (may not exist yet)
plots/                        # generated by plot
review/ , review.zip          # generated by review
results/                      # generated by filter
run_score_loop.sh             # detached scoring supervisor
backup_to_gcs.sh              # periodic scores.csv checkpoint
backup_work_to_gcs.sh         # one-shot full work snapshot
RUNBOOK.md                    # ops/resume details
SESSION_STATE.md              # this file
SPEC_audio_quality_filter.md  # requirements
IMPLEMENTATION_PLAN.md        # design
README.md                     # tool docs, metric definitions
```

---

## 10. Command cheat sheet

```bash
# --- resume everything after a reconnect/reboot ---
cd /content/quran_recitations
gcloud storage cp gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/checkpoints/scores.csv ./scores.csv  # optional, if local stale/missing
setsid bash run_score_loop.sh >/dev/null 2>&1 < /dev/null &
setsid bash backup_to_gcs.sh  >/dev/null 2>&1 < /dev/null &

# --- checkpoint the full work now ---
./backup_work_to_gcs.sh

# --- post-scoring pipeline (fast) ---
python3 -m aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json
python3 -m aqfilter plot      --scores scores.csv --refs refs.txt --out plots/ --thresholds thresholds.json
python3 -m aqfilter review    --scores scores.csv --thresholds thresholds.json --data data/ --out review/ --zip
python3 -m aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/

# --- tests ---
python3 -m pytest -q

# --- push source ---
git add -A && git commit -m "..." && git push origin main
```
