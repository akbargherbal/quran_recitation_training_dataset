"""``plot`` subcommand: per-reciter histograms + summary table."""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from aqfilter.config import CLASSICAL_COLUMNS, DNSMOS_COLUMNS, PLOT_METRICS
from aqfilter.naming import read_refs, parse_or_unknown  # noqa: E402
from aqfilter.tables import load_scores  # noqa: E402

log = logging.getLogger("aqfilter")

SUMMARY_METRICS = DNSMOS_COLUMNS + CLASSICAL_COLUMNS


def _threshold_value(thresholds: dict | None, reciter: str, metric: str) -> float | None:
    if not thresholds:
        return None
    info = thresholds.get("reciters", {}).get(reciter)
    if not info:
        return None
    m = info.get("metrics", {}).get(metric)
    return None if m is None else float(m["threshold"])


def run_plot(
    scores: str | Path,
    refs: str | Path,
    out_dir: str | Path,
    thresholds_path: str | Path | None = None,
) -> Path:
    df = load_scores(scores)
    ref_names = set(read_refs(refs))
    thresholds = None
    if thresholds_path is not None:
        import json

        thresholds = json.loads(Path(thresholds_path).read_text(encoding="utf-8"))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Reference values per reciter (parsed from filename).
    ref_by_reciter: dict[str, list[str]] = {}
    for name in ref_names:
        ref_by_reciter.setdefault(parse_or_unknown(name)["reciter"], []).append(name)

    reciters = sorted(set(df["reciter"]) - {"UNKNOWN"})
    summary_rows = []
    for reciter in reciters:
        rec_df = df[(df["reciter"] == reciter) & df["decode_ok"]]
        if rec_df.empty:
            continue
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        fig.suptitle(f"{reciter} (n={len(rec_df)})")
        for ax, metric in zip(axes.ravel(), PLOT_METRICS):
            values = rec_df[metric].dropna()
            if not values.empty:
                ax.hist(values, bins=40, color="#4c72b0", alpha=0.8)
            for name in ref_by_reciter.get(reciter, []):
                rows = df[df["filename"] == name]
                if not rows.empty and pd.notna(rows.iloc[0][metric]):
                    ax.axvline(
                        rows.iloc[0][metric], color="green", ls="--", lw=1.2,
                        label="reference",
                    )
            thr = _threshold_value(thresholds, reciter, metric)
            if thr is not None:
                ax.axvline(thr, color="red", ls="-", lw=1.5, label="threshold")
            ax.set_title(metric)
            ax.set_ylabel("count")
            if ax.get_legend_handles_labels()[0]:
                ax.legend(fontsize=8)
        fig.tight_layout()
        png = out_dir / f"{reciter}.png"
        fig.savefig(png, dpi=120)
        plt.close(fig)
        log.info("Wrote %s", png)

        for metric in SUMMARY_METRICS:
            series = rec_df[metric].dropna()
            if series.empty:
                continue
            summary_rows.append(
                {
                    "reciter": reciter,
                    "metric": metric,
                    "median": float(series.median()),
                    "p10": float(series.quantile(0.10)),
                    "p90": float(series.quantile(0.90)),
                }
            )

    summary_path = out_dir / "summary.csv"
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    log.info("Wrote %s", summary_path)
    return out_dir
