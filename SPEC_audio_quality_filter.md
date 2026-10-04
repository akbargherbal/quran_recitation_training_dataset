# Spec: Reference-Calibrated Audio Quality Filter

## 1. Goal

Filter ~13,000 MP3 speech clips (Quran recitation, 6 s to 2 min each) down to those of acceptable recording quality. "Acceptable" is defined by a small set of hand-picked reference clips per reciter: a clip is kept if its quality metrics fall approximately within the range of that reciter's references.

Deliverable: a Python CLI (`aqfilter.py` or a small package) with subcommands `score`, `calibrate`, `plot`, `review`, `filter`, plus a `README.md`.

## 2. Environment and constraints

- Python 3.10+. The agent runs the whole job on **its own machine** (likely a remote or sandboxed Linux box, not the user's PC). Target Linux first, but stay platform-neutral: use `pathlib`, guard multiprocessing with `if __name__ == "__main__"`, and do not assume the `fork` start method.
- Assume **headless**: no audio playback, no display. `matplotlib` must use the `Agg` backend.
- CPU-only must work. GPU is not required. Use all available cores by default (`--workers` default = `cpu_count() - 1`, minimum 1).
- Long job: scoring may take a long time. It must be runnable in the background (e.g. `nohup ... &`), write progress to a log file, and be resumable (see `--resume`).
- Keep dependencies small: `numpy`, `scipy`, `pandas`, `soundfile`, `librosa`, `speechmos`, `onnxruntime`, `matplotlib` (only for `plot`), `tqdm`. No parquet; use **CSV** for all tables.
- The tool itself works on **local files only**. It has no GCS integration. Getting the data onto the agent's machine is a separate setup step (section 3.0).
- All stages must be **re-runnable without recomputing scores**. Scoring is the expensive step; everything after it must be fast.

## 3. Inputs

### 3.0 Getting the data onto the agent's machine (setup, outside the tool)
The dataset lives at `gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/quran_dataset_AHH_long_aya/` (~13,000 MP3s). The agent should obtain it in one of these ways, in order of preference:
1. If the user has already placed it on the agent's machine, use that directory as `--data`.
2. If the agent has Google Cloud credentials: `gcloud storage cp -r gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/quran_dataset_AHH_long_aya/ ./data` (or `gsutil -m cp -r ...`).
3. Otherwise, **stop and ask the user** for a way to get the files (upload, signed URL, or credentials). Do not guess.

After download, verify and report: file count (expect ~13,000), total size, and that the `.mp3` count matches the listing. If the copy created a nested folder (e.g. `./data/quran_dataset_AHH_long_aya/`), point `--data` at the folder that actually contains the MP3s (the scanner is recursive, so either works).

### 3.1 Dataset
A directory of MP3s (searched recursively). Filename pattern:

```
<Reciter>_<kbps>kbps_<SSSAAA>.mp3
e.g. Abdul_Basit_Murattal_192kbps_001007.mp3  ->  reciter="Abdul_Basit_Murattal", kbps=192, surah=1, ayah=7
```

Regex: `^(?P<reciter>.+?)_(?P<kbps>\d+)kbps_(?P<surah>\d{3})(?P<ayah>\d{3})\.mp3$`

Files not matching the pattern must be reported (count + first 20 names) and given `reciter="UNKNOWN"`; they must not crash the run. Expected: exactly 3 distinct reciters (Abdul_Basit_Murattal, Hudhaify, Husary). Print the distinct reciter keys and file counts after parsing so typos are visible.

### 3.2 References
The user picked 9 references (3 per reciter). Because they are copies of files already in the dataset, the tool only needs their **basenames**, not the audio. `--refs` must accept either of:
- a **text/CSV file** with one basename per line (CSV: column `filename`), or
- a **directory** of reference MP3s (searched recursively; basenames are used).

The 9 references:
```
Abdul_Basit_Murattal_192kbps_003180.mp3
Abdul_Basit_Murattal_192kbps_021023.mp3
Abdul_Basit_Murattal_192kbps_058013.mp3
Hudhaify_128kbps_026044.mp3
Hudhaify_128kbps_029055.mp3
Hudhaify_128kbps_030044.mp3
Husary_128kbps_008016.mp3
Husary_128kbps_026008.mp3
Husary_128kbps_035024.mp3
```
(The user's original local layout was `Quran_MP3/AB`, `Quran_MP3/HUD`, `Quran_MP3/HUS` with these files. If the user also uploads that folder, it works as a directory `--refs`; folder names are irrelevant.)

```
Quran_MP3/
  AB/   Abdul_Basit_Murattal_192kbps_003180.mp3, ..._021023.mp3, ..._058013.mp3
  HUD/  Hudhaify_128kbps_026044.mp3, ..._029055.mp3, ..._030044.mp3
  HUS/  Husary_128kbps_008016.mp3, ..._026008.mp3, ..._035024.mp3
```

- Reference files are **matched to rows in the scores table by basename**, and the reciter is taken from the filename, not any folder.
- Each reference is also in the dataset, so it will already be in `scores.csv`. If a reference basename is not found in the scores table, fail with a clear error naming the file.
- If `--refs` is a directory, warn if a subfolder contains files from more than one reciter.
- The references span quality from excellent to just-acceptable. This is intentional: thresholds are derived from the worst reference.

## 4. CLI

```
aqfilter score     --data DIR --out scores.csv [--workers N] [--resume]
aqfilter calibrate --scores scores.csv --refs FILE_OR_DIR --out thresholds.json [--k 0.25] [--k-reciter NAME=VAL ...]
aqfilter plot      --scores scores.csv --refs FILE_OR_DIR --out plots/ [--thresholds thresholds.json]
aqfilter review    --scores scores.csv --thresholds thresholds.json --data DIR --out review/ [--n 5] [--zip]
aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/
```

## 5. `score`

Computes metrics for every MP3 and writes one row per file to `scores.csv`.

### 5.1 Decoding
- Decode with `soundfile` (libsndfile >= 1.1 supports MP3; verified `'MP3' in soundfile.available_formats()` with libsndfile 1.2.2). If that fails, fall back to an `ffmpeg` subprocess (if on PATH) decoding to float32 PCM. If both fail, record the row with `decode_ok=False` and the error string, and continue.
- Downmix to mono (mean of channels). Keep the **native-rate** signal for spectral metrics, and produce a **16 kHz** version (`scipy.signal.resample_poly`) for DNSMOS and frame-level metrics.
- Samples must be float32 in [-1, 1] (clamp after resampling; DNSMOS raises otherwise).

### 5.2 Metrics (columns in `scores.csv`)

Identity and bookkeeping:
`filename` (basename), `path` (relative to `--data`), `reciter`, `kbps_label`, `surah`, `ayah`, `decode_ok`, `error`, `duration_s`, `native_sr`, `actual_kbps` (= file size * 8 / duration / 1000).

Learned quality (DNSMOS via `speechmos`):
`ovrl_mos`, `sig_mos`, `bak_mos`, `p808_mos`.

Classical:

| Column | Definition |
|---|---|
| `noise_floor_db` | 10th percentile of frame RMS in dBFS (25 ms frames, 10 ms hop, on the 16 kHz signal; add epsilon before log). |
| `speech_db` | 95th percentile of the same frame RMS values in dBFS. |
| `snr_est_db` | `speech_db - noise_floor_db`. |
| `silence_ratio` | Fraction of frames below `speech_db - 35 dB`. |
| `clipping_ratio` | Fraction of samples (native-rate, pre-resample) with `abs(x) >= 0.999`. |
| `bandwidth_hz` | Highest frequency where the smoothed long-term average spectrum (Welch PSD on the **native-rate** signal, in dB, lightly smoothed) is within 60 dB of that spectrum's peak. Captures band-limited or upsampled old recordings. |

Document each definition in the README. These are heuristics; exact constants (percentiles, -35 dB, -60 dB) should be module-level constants so they can be tuned.

### 5.3 DNSMOS usage notes (verified from the installed `speechmos` source)
- Call `speechmos.dnsmos.run(audio_float32_16k, 16000)` with a **1-D numpy array**. It returns a dict with `ovrl_mos`, `sig_mos`, `bak_mos`, `p808_mos`. The `sr` argument must be exactly 16000, otherwise it raises.
- ONNX models ship inside the pip package; no download needed.
- Internally it scores 9.01 s windows with a 1 s hop and averages. Clips shorter than 9.01 s are tiled (repeated) to fill a window, so very short clips yield noisier scores. This is expected; do not "fix" it, but record `duration_s` so short clips can be examined.
- `speechmos` keeps its ONNX session in a **module-level global**, so each worker process loads it once. Do **not** pass a list of arrays to `run()` (that path uses a thread pool and `tqdm`); call it per clip inside a multiprocessing worker.
- Limit each worker's ONNX threads to 1 (set `OMP_NUM_THREADS=1` / ONNX session options if possible, or the env var before import) to avoid CPU oversubscription when `--workers` > 1.
- `speechmos` imports `librosa`, `requests`, and `tqdm`; include them in the requirements.

### 5.4 Execution
- `multiprocessing.Pool(--workers, default = cpu_count - 1)` with `imap_unordered` and chunksize ~8; `tqdm` progress bar.
- A worker must never raise; wrap each file in try/except and return a failure row.
- `--resume`: if `--out` exists, skip filenames already present and append new rows. Flush to disk periodically (e.g. every 500 files) so an interrupted run loses little.
- Also log to a file (`--log score.log`, default next to `--out`) so progress can be checked from a separate shell while the job runs in the background.
- Log the total wall time and per-file average at the end. Do a quick benchmark on the first 20 files and print an ETA.

## 6. `calibrate`

Derives per-reciter thresholds from the references and writes `thresholds.json`.

### 6.1 Metrics used for thresholds

| Metric | Direction | Floor on margin |
|---|---|---|
| `ovrl_mos` | higher is better | 0.05 |
| `sig_mos` | higher | 0.05 |
| `bak_mos` | higher | 0.05 |
| `snr_est_db` | higher | 1.0 |
| `bandwidth_hz` | higher | 250 |
| `noise_floor_db` | **lower** is better | 1.0 |

### 6.2 Algorithm (per reciter)
1. Take that reciter's reference rows (3 expected).
2. For each metric, compute `iqr` = interquartile range of that metric across **all dataset files of that reciter** where `decode_ok`.
3. `margin = max(floor, k * iqr)` with `k` default 0.25; `--k-reciter NAME=VAL` overrides `k` for one reciter.
4. Higher-is-better: `threshold = min(ref values) - margin`, rule is `value >= threshold`.
   Lower-is-better: `threshold = max(ref values) + margin`, rule is `value <= threshold`.
5. Store in JSON: for each reciter and metric, the `direction`, `threshold`, `ref_values`, `iqr`, `k`, `margin`. Also store `n_reference_files` and the reference filenames, for traceability.

### 6.3 Global hard gates (reference-independent, stored under `"global"`)
Applied to every file regardless of reciter. Defaults (all overridable in the JSON):
- `decode_ok == True`
- `duration_s` between 3 and 150
- `speech_db >= -45` (reject near-silent files)
- `clipping_ratio <= 0.001`

### 6.4 Output to console
Print a per-reciter table: for each metric, the 3 reference values, the dataset median, the threshold, and the fraction of that reciter's files that would pass **that single metric**. Also print the fraction passing everything. This lets the user sanity-check at a glance.

### 6.5 Warnings to emit
- Any reference that fails its own reciter's thresholds (should be impossible by construction; if it happens it indicates a bug).
- Any reciter where fewer than 3 references were found.
- Any reciter where the overall pass rate is below 10% or above 95% (the references may be mis-picked or the metric is not discriminating).

## 7. `plot`

Requires `matplotlib`. For each reciter, write one PNG with histograms of `ovrl_mos`, `bak_mos`, `noise_floor_db`, `bandwidth_hz` (2x2 grid), with the reference values drawn as vertical lines. If `--thresholds` is available, also draw the threshold. The purpose is to see whether each reciter's distribution is unimodal (one source recording), multimodal (several sources of differing quality), or whether the references sit in the bottom tail. Also write `plots/summary.csv` with per-reciter median, p10, p90 of each metric.

## 8. `review`

Produces material for the human listening check, which is how thresholds are validated.

For each reciter:
1. Rank files by `ovrl_mos`.
2. Copy `--n` (default 5) files **just above** and `--n` files **just below** that reciter's `ovrl_mos` threshold into `review/<reciter>/above/` and `review/<reciter>/below/`.
3. Also copy `--n` randomly chosen **rejected** files into `review/<reciter>/random_rejects/` (fixed seed).
4. Prefix copied filenames with their rank and `ovrl_mos` (e.g. `03_ovrl3.41_Husary_128kbps_008016.mp3`) so the ordering is visible in a file browser.
5. Write `review/<reciter>/review.csv` listing every copied file with its metrics and which gates it failed.

**The user will listen remotely, not on the agent's machine.** So `review` must make the material easy to download: with `--zip`, produce `review.zip` (the `review/` folder compressed; keep it small by copying only the selected clips, roughly 3 reciters x 3 groups x 5 clips = ~45 files). Also write a top-level `review/README.md` explaining the folder layout and what to listen for in each group. The agent should tell the user the zip's path/size when done and then **wait for the user's verdict** before changing `--k`; it must not pick the margin on its own.

Workflow the tool supports: the user listens, decides the boundary is too loose or too tight, re-runs `calibrate` with a different `--k` (globally or per reciter), re-runs `review`/`filter`. No re-scoring needed.

## 9. `filter`

For each file in `scores.csv`:
- Evaluate global gates, then the per-reciter metric thresholds for that file's reciter.
- Files with `reciter == "UNKNOWN"` are rejected with reason `unknown_reciter`.
- Write to `--out-dir`:
  - `keep.csv`: all columns from `scores.csv` for kept files.
  - `reject.csv`: same, plus `fail_reason`, a `;`-separated list of every failed check (e.g. `bak_mos<2.91;noise_floor_db>-48.2;clipping_ratio>0.001`), not just the first failure.
  - `summary.md`: per-reciter counts (total / kept / rejected), the top fail reasons per reciter, and the thresholds used. Written in Markdown.
  - `keep_list.txt`: relative paths, one per line, usable with `rsync --files-from` or a `gcloud storage cp` loop.
- A file is kept only if it passes **all** checks.
- Optional `--copy-to DIR` flag that copies kept files preserving filenames.

## 10. `README.md` (required, Markdown)

Must include: install instructions (Linux first; note any Windows differences), the end-to-end workflow below, definition of every metric column, how thresholds are computed, how to tune `--k`, and known limitations (section 12).

Workflow:
```
aqfilter score     --data data/ --out scores.csv
aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json
aqfilter plot      --scores scores.csv --refs refs.txt --out plots/ --thresholds thresholds.json
aqfilter review    --scores scores.csv --thresholds thresholds.json --data data/ --out review/ --zip
# listen, adjust --k, repeat calibrate + review
aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/
```

## 11. Acceptance criteria

The implementer must verify these before handing back:

1. `score` on a folder of ~20 real MP3s from the dataset runs end-to-end with `--workers 4` and produces a CSV with all columns in section 5.2 populated.
2. A corrupted or zero-byte MP3 produces a row with `decode_ok=False` instead of crashing the run.
3. `score --resume` after an interrupted run skips completed files and yields the same final row count as an uninterrupted run.
4. Synthetic sanity tests (generate audio with numpy): white noise added at decreasing SNR gives monotonically decreasing `snr_est_db` and `bak_mos`; a signal low-pass filtered at 4 kHz gives lower `bandwidth_hz` than the same signal unfiltered; a signal hard-clipped gives a higher `clipping_ratio`.
5. `calibrate`: every reference file passes its own reciter's thresholds.
6. `filter`: `keep.csv` + `reject.csv` row counts sum to `scores.csv` row count; every reject has a non-empty `fail_reason`.
7. Re-running `calibrate` / `filter` with a different `--k` does not trigger rescoring and takes seconds.
8. `review --zip` produces a `review.zip` containing only the selected clips plus the CSV/README files, small enough to download easily.
9. The tool runs headless (no display, no audio device) end to end, including `plot`.

## 12. Known limitations and non-goals

- DNSMOS is trained on noisy conversational/English speech. Melodic recitation with long elongations may be scored somewhat unfairly; that is why thresholds are **relative to each reciter's references**, not absolute, and why the by-ear review step is mandatory.
- `noise_floor_db` / `snr_est_db` assume the clip contains some low-energy frames. A clip with continuous recitation and no pauses will overestimate the noise floor.
- `actual_kbps` / the `kbps` label describe MP3 encoding only. They are not a quality measure.
- Quality is mostly a property of the source recording, so per-reciter distributions may be multimodal (several sessions per reciter). The tool does not try to cluster sessions automatically; `plot` exists to reveal this.
- Non-goals: training a classifier, speaker-embedding similarity matching (embeddings encode speaker and content, not quality), audio enhancement or denoising, and modifying or re-encoding source files.
- Optional extension, **only** if review shows DNSMOS is insufficient: add TorchAudio SQUIM (`SQUIM_OBJECTIVE`: STOI, PESQ, SI-SDR) as extra columns behind a `--squim` flag. This was not tested in the planning environment because the model download host was unreachable there.

## 13. Agent handoff protocol (what to report back, and when to stop)

1. After downloading the data: report file count, total size, distinct reciters and per-reciter counts.
2. Before scoring the full set: run on ~20 files, report the ETA and any decode failures.
3. After full scoring and `calibrate`: report the per-reciter threshold table (section 6.4) and the plots. **Stop and wait for the user.**
4. After `review --zip`: give the user the zip location and **stop and wait** for their listening verdict per reciter (too loose / about right / too strict). Only then adjust `--k`.
5. Final: deliver `keep.csv`, `reject.csv`, `keep_list.txt`, `summary.md`, `thresholds.json`, and `scores.csv` (the latter so any future re-thresholding is free).
6. Never delete or modify the downloaded source MP3s.
