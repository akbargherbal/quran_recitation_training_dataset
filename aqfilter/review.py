"""``review`` subcommand: material for the human listening check."""

from __future__ import annotations

import json
import logging
import random
import shutil
from pathlib import Path

import pandas as pd

from aqfilter.config import REVIEW_SEED
from aqfilter.gates import evaluate_row
from aqfilter.tables import load_scores

log = logging.getLogger("aqfilter")

REVIEW_COLUMNS = [
    "group",
    "rank",
    "copied_name",
    "filename",
    "reciter",
    "ovrl_mos",
    "sig_mos",
    "bak_mos",
    "p808_mos",
    "snr_est_db",
    "noise_floor_db",
    "bandwidth_hz",
    "clipping_ratio",
    "duration_s",
    "fail_reason",
]

README_TEXT = """# Listening review

For each reciter this folder contains three groups:

- `above/` — clips whose `ovrl_mos` sits just **above** the reciter's threshold.
  The boundary is too **loose** if these sound bad.
- `below/` — clips just **below** the threshold. The boundary is too **strict**
  if these sound clearly acceptable.
- `random_rejects/` — a random sample of clips rejected by any check. Use these
  to catch rejections caused by something other than the MOS threshold.

Filenames are prefixed with their rank and `ovrl_mos`, e.g.
`03_ovrl3.41_Husary_128kbps_008016.mp3`, so ordering is visible in a file
browser. `review.csv` lists every copied clip with its metrics and the checks it
failed. Listen, then say per reciter whether the boundary is **too loose**,
**about right**, or **too strict**; `--k` is adjusted only after that.
"""


def _prefixed(rank: int, ovrl: float, filename: str) -> str:
    value = "NA" if pd.isna(ovrl) else f"{ovrl:.2f}"
    return f"{rank:02d}_ovrl{value}_{filename}"


def _copy_group(
    rows: pd.DataFrame,
    group: str,
    dest: Path,
    data_dir: Path,
    records: list[dict],
    reasons: dict[str, str],
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for rank, (_, row) in enumerate(rows.iterrows(), start=1):
        copied = _prefixed(rank, row["ovrl_mos"], row["filename"])
        src = data_dir / str(row["path"])
        if src.exists():
            shutil.copy2(src, dest / copied)
        else:
            log.warning("Source missing, cannot copy: %s", src)
        record = {col: row.get(col) for col in REVIEW_COLUMNS if col in row.index}
        record.update(
            {
                "group": group,
                "rank": rank,
                "copied_name": copied,
                "filename": row["filename"],
                "fail_reason": reasons.get(row["filename"], ""),
            }
        )
        records.append(record)


def run_review(
    scores: str | Path,
    thresholds_path: str | Path,
    data: str | Path,
    out: str | Path,
    n: int = 5,
    make_zip: bool = False,
) -> Path:
    df = load_scores(scores)
    thresholds = json.loads(Path(thresholds_path).read_text(encoding="utf-8"))
    data_dir = Path(data)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    reasons = {
        row["filename"]: ";".join(evaluate_row(row, thresholds))
        for _, row in df.iterrows()
    }

    all_records: list[dict] = []
    for reciter in sorted(thresholds.get("reciters", {})):
        info = thresholds["reciters"][reciter]
        metric = info["metrics"].get("ovrl_mos")
        if metric is None:
            log.warning("%s has no ovrl_mos threshold; skipping", reciter)
            continue
        thr = float(metric["threshold"])
        rec_df = df[(df["reciter"] == reciter) & df["decode_ok"] & df["ovrl_mos"].notna()]
        rec_df = rec_df.sort_values("ovrl_mos")

        above = rec_df[rec_df["ovrl_mos"] >= thr].head(n)
        below = rec_df[rec_df["ovrl_mos"] < thr].sort_values(
            "ovrl_mos", ascending=False
        ).head(n)

        reciter_dir = out / reciter
        _copy_group(above, "above", reciter_dir / "above", data_dir, all_records, reasons)
        _copy_group(below, "below", reciter_dir / "below", data_dir, all_records, reasons)

        rejected = df[
            (df["reciter"] == reciter)
            & (df["filename"].map(lambda f: bool(reasons.get(f))))
        ]
        rng = random.Random(REVIEW_SEED)
        sample_idx = list(rejected.index)
        rng.shuffle(sample_idx)
        sample = rejected.loc[sample_idx[:n]]
        _copy_group(
            sample, "random_rejects", reciter_dir / "random_rejects",
            data_dir, all_records, reasons,
        )

    review_csv = out / "review.csv"
    pd.DataFrame(all_records, columns=REVIEW_COLUMNS).to_csv(review_csv, index=False)
    (out / "README.md").write_text(README_TEXT, encoding="utf-8")

    zip_path = out.parent / f"{out.name}.zip"
    if make_zip:
        if zip_path.exists():
            zip_path.unlink()
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", out.parent, out.name)
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        log.info("Wrote %s (%.1f MiB)", zip_path, size_mb)
        print(f"review zip: {zip_path} ({size_mb:.1f} MiB)")

    log.info("Review material written to %s (%d clips)", out, len(all_records))
    return out
