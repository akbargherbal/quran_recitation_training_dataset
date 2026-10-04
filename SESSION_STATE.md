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

_As of **2026-10-04T10:22Z** (recompute with §4; do not trust this timestamp)._

| Stage | State |
|---|---|
| Dataset download | ✅ done, **13,501** MP3s, ~5.6 GB, at `data/quran_dataset_AHH_long_aya/` |
| Tool + tests | ✅ done, **28/28 tests pass** |
| Full `score` | ✅ done, **13,501 / 13,501** rows, all unique, **0 decode failures** |
| GCS checkpointing | ✅ complete (final snapshot rows=13501) |
| Code on GitHub | ✅ pushed (see §6) |
| `calibrate` / `plot` | ✅ first pass `k=0.25` → `thresholds_k0.25_all6.json`; **re-calibrated** (see below) |
| `review --zip` | ✅ done → `review.zip` (21.8 MiB, 45 clips) + `review2.zip` (verification round) |
| Listening-review app | ✅ `review_app/` (Flask UI) built + tested (**15 tests**); bundle `aqfilter_review_app.zip` on GCS |
| Listening verdict | ✅ returned: **too strict** for all three reciters |
| `filter` | ✅ done → `results/` (**9,492 kept / 4,009 rejected**) |
| Filtered dataset | ✅ `AHH_Quran_Long_Aya_Filtered_DATASET.zip` (3.69 GiB, 9,492 clips + `README.md` + `MANIFEST.csv`) on GCS (see §6) |

**Calibration (final):** the "too strict" verdict → `k=0.5`, **and** `bandwidth_hz`
+ `bak_mos` dropped via the new `calibrate --drop-metric` flag. Rationale:
`bandwidth_hz` is bimodal for Abdul (references are all high-mode, so the
threshold amputates the ~7 kHz mode the listener liked, and bad clips passed it
*more* than good ones — no `k` can fix that); `bak_mos` was mis-placed for Husary
(rejected 10/13 clips the listener called good). Hudhaify's good/bad labels were
not separable by any metric (~coin-flip), so its verdict was applied only as a
mild global loosen — don't over-trust that reciter's boundary.

**Pass rates:** Abdul_Basit_Murattal **53.0%** (2,399/4,525), Hudhaify **91.2%**
(4,143/4,542), Husary **66.5%** (2,950/4,434). On the 45 labeled clips, balanced
accuracy improved vs `k=0.25` (Abdul 0.55→0.70, Husary 0.65→0.85).

**STOP gate 2 passed.** A verification round `review2/` (+ `review2.zip`) was
generated against the new thresholds — optional re-listen before final delivery.

---

## 2. What the tool does

`aqfilter` (package in `aqfilter/`) has five subcommands:

```
aqfilter score     --data DIR --out scores.csv [--workers N] [--resume]
aqfilter calibrate --scores scores.csv --refs FILE_OR_DIR --out thresholds.json [--k 0.25] [--k-reciter NAME=VAL ...] [--drop-metric METRIC ...]
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

## 5. Background jobs (all completed)

Scoring finished at 10:10:37Z (`supervisor: complete`); the checkpoint loop
uploaded the final `rows=13501` snapshot and exited. All were launched detached
with `setsid`, so they survived SSH disconnects.

| Job | Script | Behavior |
|---|---|---|
| Scorer | `run_score_loop.sh` | looped `aqfilter score ... --resume` until all 13,501 rows existed; auto-restarted after a kill/crash |
| Checkpointer | `backup_to_gcs.sh` | uploaded a cleaned `scores.csv` snapshot every 10 min; exited on completion |

They are **not running now** (nothing left to score). To resume/restart, see §6.

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
| `review/review.zip` | listening material, **direct download** (also inside the work tarball); binary, intentionally not on GitHub | after `review` |
| `review/aqfilter_review_app.zip` | self-contained bundle (`review_app/` + `review/`) for the listening session | after building the app |

Refresh the full work snapshot (run after every completed stage):
```bash
cd /content/quran_recitations && ./backup_work_to_gcs.sh
```

### Filtered dataset deliverable

The final selection is packaged as a standalone, self-describing zip **next to the
source dataset** (outside the `aqfilter/` prefix):

```
gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/AHH_Quran_Long_Aya_Filtered_DATASET.zip
gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/AHH_Quran_Long_Aya_Filtered_DATASET.zip.sha256
```

- 9,492 kept MP3s (flat, original filenames) + `README.md` (method/spec) +
  `MANIFEST.csv` (metrics per file); **3.69 GiB**; SHA-256 in the `.sha256` object.
- Built from `results/keep_list.txt`; MP3s are byte-identical originals (selection,
  not re-encode).

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

### OpenCode session continuity (separate tool, separate store)

The agent session is also backed up with
[`vm-continuity`](https://github.com/akbargherbal/vm-continuity) (cloned at
`/content/vm-continuity`), independent of the aqfilter store:

- **Session:** `ses_efab17986ffeabT6Yhuerxczxe` — "Quran reciter finetuning implementation plan"
- **Store:** `gs://akbar-december-2024-backup/opencode_sessions/by_host/93aaaef1bef7/`
  (`opencode.db` + `sessions/<id>.json` + config). opencode's ~5.7 GB workspace
  `snapshot/` is intentionally **skipped** (`CONTINUITY_SIDE_MAX_MB`, default 200 MB).
- **Keep current:** a detached watch loop runs `capture`+`ship` every 5 min.
  Health: `cd /content/vm-continuity && python3 continuity.py status`.
- **Restore on a fresh VM:** `python3 continuity.py pull` then
  `python3 continuity.py restore opencode -- --mode db` (or `--mode export`).
- **Note:** OpenCode v2.0.22 moved export under `session`; fixed + pushed upstream
  as commit `56eae4b` (probe-and-cache CLI spelling; skip oversized side dirs).

**Deliberately NOT backed up:** `data/` (5.6 GB, always re-downloadable — user's
explicit instruction). Never delete or modify the source MP3s.

---

## 7. What remains (ordered), with STOP gates

1. ✅ **Scoring done** — 13,501/13,501 rows, all unique, 0 decode failures.
2. ✅ `calibrate` → `thresholds.json`; ✅ `plot` → `plots/*.png` +
   `plots/summary.csv`; backup refreshed with `./backup_work_to_gcs.sh`.
3. ✅ STOP gate 1 passed: threshold table + plots reported to the user.
4. ✅ `review --zip` → `review.zip` (21.8 MiB, 45 clips); path/size given.
5. ✅ STOP gate 2 passed: the user reviewed via `review_app/` and returned
   `review_report.md` — verdict **too strict** for all three reciters.
6. ✅ Re-calibrated: `--k 0.5 --drop-metric bandwidth_hz,bak_mos` (see §1).
   `review2/` generated for optional verification. **No rescoring.**
7. ✅ `filter` → `results/{keep.csv,reject.csv,summary.md,keep_list.txt}`
   (9,492 kept / 4,009 rejected). Persist.
8. ⬜ Final delivery of all artifacts; keep `scores.csv` so future re-thresholding
   (e.g. reverting to `thresholds_k0.25_all6.json`) is free.

---

## 8. Key decisions, gotchas, fixed bugs

- **`--k` and the metric set are now settled** (after the listening review):
  `k=0.5`, metrics `ovrl_mos`/`sig_mos`/`snr_est_db`/`noise_floor_db`
  (`bandwidth_hz` + `bak_mos` dropped via `--drop-metric`). Change only with a new
  listening round. Thresholds anchor at the *worst* reference minus
  `max(floor, k*iqr)`.
- **`bandwidth_hz` is unreliable on bimodal reciters** (Abdul): the references all
  sit in the high mode, so the threshold deletes the low mode the listener liked;
  bad clips passed it *more* than good ones. Prefer `--drop-metric bandwidth_hz`
  over inflating `k` to compensate.
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
tests/                        # 28 tests (naming, metrics synthetic, calibrate/filter, cli smoke)
data/                         # 13,501 source MP3s (NOT backed up, re-downloadable)
refs/                         # 9 extracted reference MP3s
refs.txt                      # 9 reference basenames (threshold anchors)
scores.csv                    # THE expensive artifact (checkpointed to GCS)
thresholds.json               # generated by calibrate (may not exist yet)
plots/                        # generated by plot
review/ , review.zip          # generated by review (round 1, k=0.25)
review2/ , review2.zip        # generated by review (round 2, final thresholds)
review_app/                   # Flask UI to review clips + export the verdict report
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
python3 -m aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json --k 0.5 --drop-metric bandwidth_hz,bak_mos   # FINAL settings
python3 -m aqfilter plot      --scores scores.csv --refs refs.txt --out plots/ --thresholds thresholds.json
python3 -m aqfilter review    --scores scores.csv --thresholds thresholds.json --data data/ --out review2/ --zip
python3 -m aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/

# --- listening-review app (after review/) ---
cd review_app && python3 -m unittest discover -s tests -v   # 15 tests
python3 app.py --review-dir ../review                       # http://127.0.0.1:5000

# --- tests ---
python3 -m pytest -q

# --- push source ---
git add -A && git commit -m "..." && git push origin main
```
