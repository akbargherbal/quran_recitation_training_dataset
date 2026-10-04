# aqfilter — Reference-Calibrated Audio Quality Filter

Filter a large corpus of Quran recitation MP3s down to clips of acceptable
recording quality. "Acceptable" is defined *relative to each reciter's*
hand-picked reference clips: a clip is kept when its quality metrics fall
approximately within the range spanned by that reciter's references.

This implements `SPEC_audio_quality_filter.md`.

---

## 1. Install

Linux (primary target):

```bash
python -m pip install -r requirements.txt
# or, to get the `aqfilter` console script:
python -m pip install -e .
```

If you don't install the package, run it as a module: `python -m aqfilter ...`.

Notes / other platforms:
- Requires Python 3.10+ (developed and tested on 3.13).
- `soundfile` needs libsndfile **>= 1.1** for MP3 support. Check with
  `python -c "import soundfile; print('MP3' in soundfile.available_formats())"`.
- `ffmpeg` is an optional fallback decoder; put it on `PATH` to use it.
- Windows: multiprocessing uses the `spawn` start method, so always launch via
  the `aqfilter` entry point / `python -m aqfilter` (never by importing and
  calling in a way that re-executes module top level). Ensure `ffmpeg` is on
  `PATH` if you need the fallback.
- Everything runs **headless**; `plot` forces the matplotlib `Agg` backend.

---

## 2. End-to-end workflow

```bash
# 0) Get the dataset locally (outside the tool), e.g. gcloud storage:
#    gcloud storage cp -r gs://.../quran_dataset_AHH_long_aya/ ./data

# 1) Score every file (the expensive step; run in the background, resumable)
nohup python -m aqfilter score --data data/ --out scores.csv \
      --workers 7 --log score.log &

# 2) Derive per-reciter thresholds from the reference clips
python -m aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json

# 3) Look at the distributions
python -m aqfilter plot --scores scores.csv --refs refs.txt --out plots/ \
      --thresholds thresholds.json

# 4) Build listening material and download review.zip
python -m aqfilter review --scores scores.csv --thresholds thresholds.json \
      --data data/ --out review/ --zip
#    -> listen, decide too loose / about right / too strict per reciter

# 5) Adjust --k (no rescoring), re-calibrate + re-review as needed, then filter
python -m aqfilter filter --scores scores.csv --thresholds thresholds.json --out-dir results/
```

`score` may take hours. Everything after it is fast (seconds) because it only
reads `scores.csv`. Keep `scores.csv` — re-thresholding is then free.

### CLI reference

```
aqfilter score     --data DIR --out scores.csv [--workers N] [--resume] [--log FILE] [--benchmark-n N]
aqfilter calibrate --scores scores.csv --refs FILE_OR_DIR --out thresholds.json [--k 0.25] [--k-reciter NAME=VAL ...]
aqfilter plot      --scores scores.csv --refs FILE_OR_DIR --out plots/ [--thresholds thresholds.json]
aqfilter review    --scores scores.csv --thresholds thresholds.json --data DIR --out review/ [--n 5] [--zip]
aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/ [--copy-to DIR]
```

`--refs` accepts a text file (one basename per line), a CSV with a `filename`
column, or a directory of reference MP3s (recursive; folder names irrelevant).

---

## 3. Metric definitions

Each file produces one row in `scores.csv` (all tables are CSV).

**Identity / bookkeeping**

| Column | Meaning |
|---|---|
| `filename` | basename, the join key everywhere |
| `path` | path relative to `--data` |
| `reciter` | parsed from filename; `UNKNOWN` if the name doesn't match the pattern |
| `kbps_label` | the `<kbps>` field of the filename (encoding label only) |
| `surah`, `ayah` | parsed chapter/verse numbers |
| `decode_ok` | whether the audio could be decoded |
| `error` | decode/metric error text, empty on success |
| `duration_s` | duration in seconds |
| `native_sr` | native sample rate (Hz) |
| `actual_kbps` | `filesize*8 / duration / 1000` (encoding only, not quality) |

Filename pattern: `<Reciter>_<kbps>kbps_<SSSAAA>.mp3`, e.g.
`Husary_128kbps_008016.mp3` → surah 8, ayah 16.

**Learned quality** (DNSMOS, via the `speechmos` package, run on 16 kHz audio)

| Column | Meaning |
|---|---|
| `ovrl_mos` | overall MOS (primary ranking metric) |
| `sig_mos` | speech signal MOS |
| `bak_mos` | background-noise MOS |
| `p808_mos` | P.808 MOS |

DNSMOS scores 9.01 s windows with a 1 s hop and averages. Clips shorter than
9.01 s are tiled/repeated to fill a window, so very short clips are noisier.

**Classical** (frame analysis on the 16 kHz signal unless noted)

| Column | Definition |
|---|---|
| `noise_floor_db` | 10th percentile of frame RMS in dBFS (25 ms frames, 10 ms hop) |
| `speech_db` | 95th percentile of the same frame RMS values |
| `snr_est_db` | `speech_db - noise_floor_db` |
| `silence_ratio` | fraction of frames below `speech_db - 35 dB` |
| `clipping_ratio` | fraction of **native-rate** samples with `abs(x) >= 0.999` |
| `bandwidth_hz` | upper edge of the main spectral band: on the **native-rate** signal, the highest frequency of the contiguous band that stays within 60 dB of the Welch-PSD peak |

The heuristics constants (percentiles, −35 dB, −60 dB, frame sizes, etc.) are
module-level in `aqfilter/config.py` so they can be tuned.

---

## 4. How thresholds are computed

`calibrate` derives thresholds per reciter (see `thresholds.json`).

Metrics and directions:

| Metric | Direction | Margin floor |
|---|---|---|
| `ovrl_mos` | higher is better | 0.05 |
| `sig_mos` | higher | 0.05 |
| `bak_mos` | higher | 0.05 |
| `snr_est_db` | higher | 1.0 |
| `bandwidth_hz` | higher | 250 |
| `noise_floor_db` | **lower** is better | 1.0 |

For each metric and reciter:

1. `iqr` = interquartile range of that metric across **all decoded dataset
   files of that reciter**.
2. `margin = max(floor, k * iqr)`, with `k` default `0.25`.
3. Higher-is-better: `threshold = min(reference values) - margin`
   (`value >= threshold` passes).
4. Lower-is-better: `threshold = max(reference values) + margin`
   (`value <= threshold` passes).

Because the threshold is offset from the *worst* reference, every reference
passes its own reciter's thresholds by construction.

**Global hard gates** (reference-independent, stored under `"global"`): a file
must decode, have `3 <= duration_s <= 150`, `speech_db >= -45`, and
`clipping_ratio <= 0.001`. Every value is editable in `thresholds.json`.

---

## 5. Tuning `--k`

The references span excellent → just-acceptable quality; the thresholds are
anchored at the *worst* reference and widened by `margin`. `k` controls how far
below the worst reference a clip may fall and still be accepted.

- Smaller `k` → stricter (fewer files kept).
- Larger `k` → looser.
- Per reciter: `--k-reciter Hudhaify=0.35` (repeatable), overriding `--k` for
  that reciter only.

Use the `review` step (listen to clips just above/below each reciter's
threshold) to decide whether the boundary is too loose, about right, or too
strict, then re-run `calibrate` and `filter` — **no rescoring required**.

---

## 6. Review workflow

For each reciter, `review` copies:

- `above/` — the `--n` clips closest above the reciter's `ovrl_mos` threshold;
- `below/` — the `--n` closest below;
- `random_rejects/` — `--n` randomly rejected clips (fixed seed).

Filenames are prefixed with rank and MOS, e.g.
`03_ovrl3.41_Husary_128kbps_008016.mp3`. `review/review.csv` lists every copied
clip with metrics and the checks it failed; `review/README.md` explains the
layout. With `--zip`, `review.zip` contains only the selected clips plus the CSV
and README (about 45 files), easy to download for remote listening.

---

## 7. Outputs of `filter`

- `keep.csv` — all `scores.csv` columns for kept files.
- `reject.csv` — same plus `fail_reason`, a `;`-separated list of **every**
  failed check (e.g. `bak_mos<2.91;noise_floor_db>-48.2`).
- `summary.md` — per-reciter totals, top fail reasons, and the thresholds used.
- `keep_list.txt` — dataset-relative paths, one per line (usable with
  `rsync --files-from` or a `gcloud storage cp` loop).
- optional `--copy-to DIR` — copies kept files, preserving basenames.

A file is kept only if it passes every global gate and every per-reciter metric
threshold. Files with `reciter == "UNKNOWN"` are rejected as
`unknown_reciter`.

---

## 8. Known limitations

- **DNSMOS is trained on noisy conversational/English speech.** Melodic
  recitation with long elongations may be scored somewhat unfairly. This is why
  thresholds are relative to each reciter's references and why the by-ear
  review step is mandatory.
- `noise_floor_db` / `snr_est_db` assume the clip contains low-energy frames. A
  clip with continuous recitation and no pauses will overestimate the noise
  floor.
- `actual_kbps` and the `kbps` label describe MP3 encoding only — not quality.
- Quality is mostly a property of the source recording, so per-reciter
  distributions may be **multimodal** (several sessions per reciter). The tool
  does not cluster sessions automatically; `plot` exists to reveal this.
- Non-goals: training a classifier, speaker-embedding similarity, audio
  enhancement/denoising, and modifying or re-encoding source files.
- Optional future extension (only if review shows DNSMOS is insufficient):
  TorchAudio SQUIM (`STOI`, `PESQ`, `SI-SDR`) behind a `--squim` flag.
