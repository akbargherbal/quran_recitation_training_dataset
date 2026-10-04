# AHH Quran Long Aya — Filtered Dataset

A quality-filtered subset of the **AHH Quran long-aya recitation** collection.
**9,492 of 13,501** MP3s were kept after reference-calibrated audio-quality
filtering with the [`aqfilter`](https://github.com/akbargherbal/quran_recitation_training_dataset)
tool.

- **Source:** `quran_dataset_AHH_long_aya` — 13,501 MP3s (~5.6 GB), 3 reciters.
- **Kept:** 9,492 MP3s (~70.3% of the source).
- **Produced:** 2026-10-04.
- **Code / full method:** <https://github.com/akbargherbal/quran_recitation_training_dataset>

## Contents

```
AHH_Quran_Long_Aya_Filtered_DATASET/
├── README.md       # this file
├── MANIFEST.csv    # every kept file, with its full metric values
└── *.mp3           # 9,492 kept clips (flat layout; filenames match the source)
```

`MANIFEST.csv` columns: `filename, path, reciter, kbps_label, surah, ayah,
decode_ok, error, duration_s, native_sr, actual_kbps, ovrl_mos, sig_mos, bak_mos,
p808_mos, noise_floor_db, speech_db, snr_est_db, silence_ratio, clipping_ratio,
bandwidth_hz`.

## Reciter breakdown

| Reciter | Source | Kept | Keep rate |
|---|---:|---:|---:|
| Abdul_Basit_Murattal | 4,525 | 2,399 | 53.0% |
| Hudhaify | 4,542 | 4,143 | 91.2% |
| Husary | 4,434 | 2,950 | 66.5% |
| **Total** | **13,501** | **9,492** | **70.3%** |

## How this dataset was produced

Reference-calibrated filtering: instead of fixing absolute quality thresholds,
each reciter's thresholds are anchored to a small set of **hand-picked reference
clips** (3 per reciter, 9 total) that represent the minimum acceptable quality.

For every metric, the threshold is:

```
higher-is-better metrics:  threshold = min(reference values) - max(floor, k * IQR)
lower-is-better metrics:   threshold = max(reference values) + max(floor, k * IQR)
```

where `IQR` is the inter-quartile range of that metric across the reciter's whole
corpus (a robust spread) and `k` is the single tunable margin factor.

1. **Score** all 13,501 MP3s (`aqfilter score`) → perceptual MOS (DNSMOS) +
   classical signal metrics for each file.
2. **Calibrate** per-reciter thresholds from the 9 references.
3. **Listening review:** 45 clips (15 per reciter: just-above threshold,
   just-below threshold, and random rejects) were rated by a human reviewer via a
   small Flask app. Verdict: the filter was **too strict** for all three reciters.
4. **Re-calibrate** with `k = 0.5` and two metrics dropped (see below).
5. **Filter** → keep files passing every gate.

### Final specification (used for this dataset)

**Global gates (all files):**

| Gate | Rule |
|---|---|
| `decode_ok` | must decode |
| `duration_s` | 3 – 150 s |
| `speech_db` | ≥ −45 dB |
| `clipping_ratio` | ≤ 0.001 |

**Per-reciter metric thresholds (a file is kept only if it passes all four):**

| Reciter | `ovrl_mos` ≥ | `sig_mos` ≥ | `snr_est_db` ≥ | `noise_floor_db` ≤ |
|---|---:|---:|---:|---:|
| Abdul_Basit_Murattal | 2.081 | 2.946 | 25.76 | −43.01 |
| Hudhaify | 2.142 | 3.208 | 17.76 | −30.63 |
| Husary | 2.357 | 3.119 | 31.08 | −44.11 |

- **k (margin factor):** `0.5` for all three reciters.
- **Metrics dropped from the filter:** `bandwidth_hz` and `bak_mos`.
  - `bandwidth_hz` is bimodal for Abdul_Basit_Murattal (≈7 kHz vs ≈13–15 kHz);
    the references all sit in the high mode, so the threshold amputated the whole
    ~7 kHz mode that listeners found acceptable — and bad clips passed it *more*
    often than good ones. No `k` corrects that.
  - `bak_mos` was mis-placed for Husary (its threshold rejected 10 of 13 clips the
    listener rated good); `snr_est_db` + `noise_floor_db` already capture
    background noise.
- **Reference clips (threshold anchors):**
  `Abdul_Basit_Murattal_192kbps_003180.mp3`,
  `Abdul_Basit_Murattal_192kbps_021023.mp3`,
  `Abdul_Basit_Murattal_192kbps_058013.mp3`,
  `Hudhaify_128kbps_026044.mp3`, `Hudhaify_128kbps_029055.mp3`,
  `Hudhaify_128kbps_030044.mp3`, `Husary_128kbps_008016.mp3`,
  `Husary_128kbps_026008.mp3`, `Husary_128kbps_035024.mp3`.

## Reproduce

```bash
git clone https://github.com/akbargherbal/quran_recitation_training_dataset
cd quran_recitation_training_dataset

# 1. Score the source MP3s (the only expensive step)
python3 -m aqfilter score --data data/quran_dataset_AHH_long_aya --out scores.csv

# 2. Re-derive the thresholds used here
python3 -m aqfilter calibrate --scores scores.csv --refs refs.txt \
    --out thresholds.json --k 0.5 --drop-metric bandwidth_hz,bak_mos

# 3. Apply them
python3 -m aqfilter filter --scores scores.csv --thresholds thresholds.json \
    --out-dir results/
```

See the repo's `SESSION_STATE.md`, `RUNBOOK.md`, and
`SPEC_audio_quality_filter.md` for full details and provenance.

## Notes

- MP3s are the original source files, unchanged and bit-identical (this dataset is
  a selection, not a re-encode). No source file was modified.
- This is a **quality** filter only; it does not deduplicate, align, or trim audio.
