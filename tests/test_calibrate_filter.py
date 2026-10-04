"""Calibration and filtering invariants (acceptance #5, #6, #7)."""

import json
from pathlib import Path

import pandas as pd

from aqfilter.calibrate import run_calibrate
from aqfilter.config import SCORE_COLUMNS
from aqfilter.filtering import run_filter
from aqfilter.gates import evaluate_row

RECITERS = ["ReciterA", "ReciterB", "ReciterC"]


def _row(reciter: str, idx: int, ref: bool) -> dict:
    row = {col: "" for col in SCORE_COLUMNS}
    row.update(
        {
            "filename": f"{reciter}_128kbps_{idx:03d}{idx:03d}.mp3",
            "path": f"{reciter}_128kbps_{idx:03d}{idx:03d}.mp3",
            "reciter": reciter,
            "kbps_label": 128,
            "surah": idx,
            "ayah": idx,
            "decode_ok": True,
            "error": "",
            "duration_s": 30.0,
            "native_sr": 16000,
            "actual_kbps": 128.0,
            "p808_mos": 3.5,
            "speech_db": -12.0,
            "silence_ratio": 0.2,
            "clipping_ratio": 0.0,
        }
    )
    if ref:
        row.update(
            {
                "ovrl_mos": 3.5 - 0.1 * idx,
                "sig_mos": 3.6,
                "bak_mos": 3.5,
                "noise_floor_db": -55.0,
                "snr_est_db": 40.0,
                "bandwidth_hz": 7000.0,
            }
        )
    else:
        row.update(
            {
                "ovrl_mos": 2.0,
                "sig_mos": 2.0,
                "bak_mos": 2.0,
                "noise_floor_db": -40.0,
                "snr_est_db": 15.0,
                "bandwidth_hz": 3000.0,
            }
        )
    return row


def _make_scores(tmp_path: Path) -> tuple[Path, Path]:
    rows = []
    ref_names = []
    for reciter in RECITERS:
        for i in range(3):
            rows.append(_row(reciter, i + 1, ref=True))
            ref_names.append(rows[-1]["filename"])
        for i in range(2):
            rows.append(_row(reciter, 10 + i, ref=False))
    scores = tmp_path / "scores.csv"
    pd.DataFrame(rows, columns=SCORE_COLUMNS).to_csv(scores, index=False)
    refs = tmp_path / "refs.txt"
    refs.write_text("\n".join(ref_names) + "\n", encoding="utf-8")
    return scores, refs


def test_references_pass_own_thresholds_and_filter_invariants(tmp_path: Path):
    scores, refs = _make_scores(tmp_path)
    thresholds_path = tmp_path / "thresholds.json"
    run_calibrate(scores, refs, thresholds_path)
    thresholds = json.loads(thresholds_path.read_text())
    df = pd.read_csv(scores)

    # Acceptance #5: every reference passes its own reciter's thresholds.
    for name in refs.read_text().split():
        row = df[df["filename"] == name].iloc[0]
        assert evaluate_row(row, thresholds) == [], f"{name} failed: {evaluate_row(row, thresholds)}"

    # Acceptance #6: keep + reject == total; every reject has a reason.
    out = tmp_path / "results"
    run_filter(scores, thresholds_path, out)
    keep = pd.read_csv(out / "keep.csv")
    reject = pd.read_csv(out / "reject.csv")
    assert len(keep) + len(reject) == len(df)
    assert len(keep) == 9
    assert reject["fail_reason"].notna().all()
    assert (reject["fail_reason"].str.len() > 0).all()


def test_k_change_does_not_need_rescoring(tmp_path: Path):
    scores, refs = _make_scores(tmp_path)
    mtime = scores.stat().st_mtime_ns
    out1 = tmp_path / "t1.json"
    out2 = tmp_path / "t2.json"
    run_calibrate(scores, refs, out1, k=0.25)
    run_calibrate(scores, refs, out2, k=1.0)
    assert scores.stat().st_mtime_ns == mtime
    assert json.loads(out1.read_text()) != json.loads(out2.read_text())
