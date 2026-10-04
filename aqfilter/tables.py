"""Shared loading helpers for the scores table."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from aqfilter.config import CLASSICAL_COLUMNS, DNSMOS_COLUMNS

NUMERIC_COLUMNS = [
    "kbps_label",
    "surah",
    "ayah",
    "duration_s",
    "native_sr",
    "actual_kbps",
    *DNSMOS_COLUMNS,
    *CLASSICAL_COLUMNS,
]

STRING_COLUMNS = ["filename", "path", "reciter", "error"]


def load_scores(path: str | Path) -> pd.DataFrame:
    """Load scores.csv with numeric columns coerced and booleans parsed."""
    df = pd.read_csv(path)
    for col in STRING_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype("string").fillna("")
    if "decode_ok" in df.columns:
        df["decode_ok"] = (
            df["decode_ok"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
        )
    else:
        df["decode_ok"] = False
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["reciter"] = df["reciter"].replace("", "UNKNOWN")
    return df
