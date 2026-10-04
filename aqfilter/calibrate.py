"""``calibrate`` subcommand: derive per-reciter thresholds from references."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from aqfilter.config import DEFAULT_K, GLOBAL_GATES, THRESHOLD_METRICS
from aqfilter.naming import parse_or_unknown, read_refs
from aqfilter.tables import load_scores

log = logging.getLogger("aqfilter")


def _resolve_refs(df: pd.DataFrame, refs_path: str | Path) -> dict[str, list[str]]:
    """Map reference basenames to their reciter and validate they exist."""
    names = read_refs(refs_path)
    known = set(df["filename"].astype(str))
    missing = [n for n in names if n not in known]
    if missing:
        raise SystemExit(
            "Reference file(s) not found in the scores table: "
            + ", ".join(missing)
        )
    by_reciter: dict[str, list[str]] = {}
    for name in names:
        reciter = parse_or_unknown(name)["reciter"]
        by_reciter.setdefault(reciter, []).append(name)
    return {r: sorted(v) for r, v in by_reciter.items()}


def _metric_pass(row: pd.Series, metric: str, direction: str, threshold: float) -> bool:
    value = row.get(metric)
    if pd.isna(value):
        return False
    return value >= threshold if direction == "higher" else value <= threshold


def _global_pass(row: pd.Series, gates: dict) -> bool:
    if gates.get("decode_ok", True) and not bool(row.get("decode_ok", False)):
        return False
    duration = row.get("duration_s")
    if pd.isna(duration) or not (gates["duration_s_min"] <= duration <= gates["duration_s_max"]):
        return False
    speech = row.get("speech_db")
    if pd.isna(speech) or speech < gates["speech_db_min"]:
        return False
    clip = row.get("clipping_ratio")
    if pd.isna(clip) or clip > gates["clipping_ratio_max"]:
        return False
    return True


def compute_thresholds(
    df: pd.DataFrame,
    refs_path: str | Path,
    k: float = DEFAULT_K,
    k_reciter: dict[str, float] | None = None,
    drop_metrics: set[str] | None = None,
) -> dict:
    k_reciter = k_reciter or {}
    drop = set(drop_metrics or ())
    refs_by_reciter = _resolve_refs(df, refs_path)

    reciters_out: dict[str, dict] = {}
    for reciter, ref_files in refs_by_reciter.items():
        ref_rows = df[df["filename"].isin(ref_files)]
        reciter_df = df[(df["reciter"] == reciter) & df["decode_ok"]]
        k_eff = float(k_reciter.get(reciter, k))
        metrics_out: dict[str, dict] = {}
        for metric, direction, floor in THRESHOLD_METRICS:
            if metric in drop:
                continue
            ref_values = [float(v) for v in ref_rows[metric].tolist() if pd.notna(v)]
            series = reciter_df[metric].dropna()
            if series.size >= 2:
                iqr = float(series.quantile(0.75) - series.quantile(0.25))
            else:
                iqr = 0.0
            margin = max(floor, k_eff * iqr)
            if direction == "higher":
                threshold = (min(ref_values) if ref_values else float("nan")) - margin
            else:
                threshold = (max(ref_values) if ref_values else float("nan")) + margin
            metrics_out[metric] = {
                "direction": direction,
                "threshold": threshold,
                "ref_values": ref_values,
                "iqr": iqr,
                "k": k_eff,
                "margin": margin,
            }
        reciters_out[reciter] = {
            "n_reference_files": len(ref_files),
            "reference_files": sorted(ref_files),
            "metrics": metrics_out,
        }

    return {
        "k_default": float(k),
        "k_effective": {
            r: float(k_reciter.get(r, k)) for r in reciters_out
        },
        "dropped_metrics": sorted(drop),
        "global": dict(GLOBAL_GATES),
        "reciters": reciters_out,
    }


def _print_report(df: pd.DataFrame, thresholds: dict) -> None:
    print("\n=== Per-reciter threshold report ===")
    for reciter, info in sorted(thresholds["reciters"].items()):
        reciter_df = df[(df["reciter"] == reciter) & df["decode_ok"]]
        print(f"\n{reciter}  (n={len(reciter_df)} decoded, "
              f"{info['n_reference_files']} references, k={thresholds['k_effective'][reciter]})")
        print(f"  {'metric':16} {'refs':>26} {'median':>9} {'thresh':>9} {'pass%':>7}")
        for metric, m in info["metrics"].items():
            series = reciter_df[metric].dropna()
            median = float(series.median()) if series.size else float("nan")
            direction = m["direction"]
            thr = m["threshold"]
            if series.size:
                passed = (
                    (series >= thr) if direction == "higher" else (series <= thr)
                )
                pass_frac = float(passed.mean())
            else:
                pass_frac = float("nan")
            refs = ", ".join(f"{v:.3g}" for v in m["ref_values"])
            print(f"  {metric:16} {refs:>26} {median:9.3g} {thr:9.3g} {pass_frac*100:6.1f}%")

        overall = _overall_pass(df, reciter, info["metrics"], thresholds["global"])
        if reciter_df.empty:
            overall_frac = float("nan")
        else:
            overall_frac = overall / len(reciter_df)
        print(f"  {'ALL CHECKS':16} {'':>26} {'':>9} {'':>9} {overall_frac*100:6.1f}%")


def _overall_pass(
    df: pd.DataFrame, reciter: str, metrics: dict, gates: dict
) -> int:
    reciter_df = df[(df["reciter"] == reciter) & df["decode_ok"]]
    count = 0
    for _, row in reciter_df.iterrows():
        if not _global_pass(row, gates):
            continue
        if all(
            _metric_pass(row, metric, m["direction"], m["threshold"])
            for metric, m in metrics.items()
        ):
            count += 1
    return count


def _emit_warnings(df: pd.DataFrame, thresholds: dict) -> None:
    for reciter, info in thresholds["reciters"].items():
        n = info["n_reference_files"]
        if n < 3:
            log.warning("%s: only %d reference(s) found (expected 3)", reciter, n)
        # References must pass their own thresholds by construction.
        for _, row in df[df["filename"].isin(info["reference_files"])].iterrows():
            failed = [
                metric
                for metric, m in info["metrics"].items()
                if not _metric_pass(row, metric, m["direction"], m["threshold"])
            ]
            if failed:
                log.warning(
                    "Reference %s fails its own thresholds: %s",
                    row["filename"], ", ".join(failed),
                )
        reciter_df = df[(df["reciter"] == reciter) & df["decode_ok"]]
        if reciter_df.empty:
            continue
        overall = _overall_pass(df, reciter, info["metrics"], thresholds["global"])
        frac = overall / len(reciter_df)
        if frac < 0.10:
            log.warning("%s: overall pass rate %.1f%% is below 10%%", reciter, frac * 100)
        elif frac > 0.95:
            log.warning("%s: overall pass rate %.1f%% is above 95%%", reciter, frac * 100)


def run_calibrate(
    scores: str | Path,
    refs: str | Path,
    out: str | Path,
    k: float = DEFAULT_K,
    k_reciter: dict[str, float] | None = None,
    drop_metrics: set[str] | None = None,
) -> dict:
    df = load_scores(scores)
    thresholds = compute_thresholds(
        df, refs, k=k, k_reciter=k_reciter, drop_metrics=drop_metrics
    )
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    _print_report(df, thresholds)
    _emit_warnings(df, thresholds)
    log.info("Wrote thresholds to %s", out)
    return thresholds
