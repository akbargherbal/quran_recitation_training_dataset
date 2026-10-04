"""Shared pass/fail evaluation used by ``filter`` and ``review``."""

from __future__ import annotations

import pandas as pd


def global_gate_reasons(row: pd.Series, gates: dict) -> list[str]:
    reasons: list[str] = []
    if gates.get("decode_ok", True) and not bool(row.get("decode_ok", False)):
        reasons.append("decode_ok=false")

    duration = row.get("duration_s")
    if pd.isna(duration):
        reasons.append("duration_s=missing")
    else:
        if duration < gates["duration_s_min"]:
            reasons.append(f"duration_s<{gates['duration_s_min']:g}")
        elif duration > gates["duration_s_max"]:
            reasons.append(f"duration_s>{gates['duration_s_max']:g}")

    speech = row.get("speech_db")
    if pd.isna(speech):
        reasons.append("speech_db=missing")
    elif speech < gates["speech_db_min"]:
        reasons.append(f"speech_db<{gates['speech_db_min']:g}")

    clip = row.get("clipping_ratio")
    if pd.isna(clip):
        reasons.append("clipping_ratio=missing")
    elif clip > gates["clipping_ratio_max"]:
        reasons.append(f"clipping_ratio>{gates['clipping_ratio_max']:g}")

    return reasons


def metric_gate_reasons(row: pd.Series, metrics: dict) -> list[str]:
    reasons: list[str] = []
    for metric, m in metrics.items():
        value = row.get(metric)
        threshold = float(m["threshold"])
        direction = m["direction"]
        if pd.isna(value):
            reasons.append(f"{metric}=missing")
        elif direction == "higher":
            if value < threshold:
                reasons.append(f"{metric}<{threshold:.4g}")
        else:
            if value > threshold:
                reasons.append(f"{metric}>{threshold:.4g}")
    return reasons


def evaluate_row(row: pd.Series, thresholds: dict) -> list[str]:
    """Return every failed check for a row given the thresholds JSON."""
    reciter = row.get("reciter", "UNKNOWN")
    if reciter in (None, "", "UNKNOWN"):
        return ["unknown_reciter"]
    info = thresholds.get("reciters", {}).get(reciter)
    if info is None:
        return ["unknown_reciter"]

    reasons = global_gate_reasons(row, thresholds.get("global", {}))
    reasons.extend(metric_gate_reasons(row, info.get("metrics", {})))
    return reasons
