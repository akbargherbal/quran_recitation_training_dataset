"""Smoke tests for scoring a real file and a broken file (acceptance #1, #2, #3)."""

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from aqfilter.config import SCORE_COLUMNS
from aqfilter.score import _score_one, run_score

SR = 16000


def _write_clip(path: Path) -> None:
    t = np.arange(SR) / SR
    rng = np.random.default_rng(0)
    tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    noise = rng.normal(0.0, 0.02, SR).astype(np.float32)
    # WAV payload under an .mp3 name: soundfile reads by content, and the name
    # matches the dataset pattern.
    sf.write(str(path), np.clip(tone + noise, -1, 1), SR, format="WAV")


def test_score_one_valid_and_broken(tmp_path: Path):
    good = tmp_path / "Abdul_Basit_Murattal_192kbps_001001.mp3"
    _write_clip(good)
    row = _score_one((str(good), str(tmp_path)))
    assert row["decode_ok"] is True
    assert row["reciter"] == "Abdul_Basit_Murattal"
    assert row["error"] == ""
    assert row["ovrl_mos"] != ""
    assert row["bandwidth_hz"] > 0

    bad = tmp_path / "Abdul_Basit_Murattal_192kbps_001002.mp3"
    bad.write_bytes(b"")
    bad_row = _score_one((str(bad), str(tmp_path)))
    assert bad_row["decode_ok"] is False
    assert bad_row["error"]


def test_score_resume_row_count(tmp_path: Path):
    for i in range(3):
        _write_clip(tmp_path / f"Husary_128kbps_{i + 1:03d}{i + 1:03d}.mp3")

    out = tmp_path / "scores.csv"
    # Simulate an interrupted run: pre-write a single completed row.
    first = tmp_path / "Husary_128kbps_001001.mp3"
    row = _score_one((str(first), str(tmp_path)))
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCORE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)

    run_score(data=tmp_path, out=out, workers=1, resume=True, benchmark_n=1)
    df = pd.read_csv(out)
    assert len(df) == 3
    assert df["filename"].nunique() == 3
