"""``filter`` subcommand: apply thresholds and write keep/reject tables."""

from __future__ import annotations

import json
import logging
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd

from aqfilter.gates import evaluate_row
from aqfilter.tables import load_scores

log = logging.getLogger("aqfilter")


def _write_summary_md(
    summary_path: Path,
    df: pd.DataFrame,
    keep_mask: pd.Series,
    thresholds: dict,
    reasons_by_row: list[list[str]],
) -> None:
    lines = ["# Filter summary", ""]
    lines.append(f"Total files: **{len(df)}** — kept **{int(keep_mask.sum())}**, "
                 f"rejected **{int((~keep_mask).sum())}**.")
    lines.append("")
    lines.append("## Per-reciter counts")
    lines.append("")
    lines.append("| Reciter | Total | Kept | Rejected |")
    lines.append("|---|---:|---:|---:|")
    for reciter in sorted(df["reciter"].unique()):
        sub = df["reciter"] == reciter
        total = int(sub.sum())
        kept = int((sub & keep_mask).sum())
        lines.append(f"| {reciter} | {total} | {kept} | {total - kept} |")
    lines.append("")

    lines.append("## Top fail reasons per reciter")
    lines.append("")
    for reciter in sorted(df["reciter"].unique()):
        idx = df.index[df["reciter"] == reciter]
        counter: Counter[str] = Counter()
        for i in idx:
            counter.update(reasons_by_row[i])
        if not counter:
            continue
        lines.append(f"### {reciter}")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("|---|---:|")
        for reason, count in counter.most_common(10):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    lines.append("## Thresholds used")
    lines.append("")
    lines.append(f"- Global gates: `{json.dumps(thresholds.get('global', {}))}`")
    for reciter, info in sorted(thresholds.get("reciters", {}).items()):
        lines.append(f"- **{reciter}** (k={info.get('k')}):")
        for metric, m in info.get("metrics", {}).items():
            op = ">=" if m["direction"] == "higher" else "<="
            lines.append(f"    - `{metric} {op} {float(m['threshold']):.4g}`")
    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def run_filter(
    scores: str | Path,
    thresholds_path: str | Path,
    out_dir: str | Path,
    copy_to: str | Path | None = None,
) -> Path:
    df = load_scores(scores).reset_index(drop=True)
    thresholds = json.loads(Path(thresholds_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reasons_by_row: list[list[str]] = []
    for _, row in df.iterrows():
        reasons_by_row.append(evaluate_row(row, thresholds))

    df = df.copy()
    df["fail_reason"] = [";".join(r) for r in reasons_by_row]
    keep_mask = df["fail_reason"] == ""
    keep = df[keep_mask].drop(columns=["fail_reason"])
    reject = df[~keep_mask]
    if "fail_reason" in reject.columns:
        reject = reject[
            [c for c in keep.columns] + ["fail_reason"]
        ]

    # Invariant: keep + reject == total, every reject has a reason.
    assert len(keep) + len(reject) == len(df), "keep/reject row counts do not sum"
    assert reject["fail_reason"].str.len().gt(0).all(), "reject row without reason"

    keep.to_csv(out_dir / "keep.csv", index=False)
    reject.to_csv(out_dir / "reject.csv", index=False)
    (out_dir / "keep_list.txt").write_text(
        "\n".join(str(p) for p in keep["path"].tolist()) + ("\n" if len(keep) else ""),
        encoding="utf-8",
    )
    _write_summary_md(out_dir / "summary.md", df, keep_mask, thresholds, reasons_by_row)

    if copy_to is not None:
        copy_to = Path(copy_to)
        copy_to.mkdir(parents=True, exist_ok=True)
        for _, row in keep.iterrows():
            src = Path(scores).parent / str(row["path"])
            if src.exists():
                shutil.copy2(src, copy_to / Path(row["filename"]).name)
        log.info("Copied %d kept files to %s", len(keep), copy_to)

    log.info(
        "Filter: %d total, %d kept, %d rejected -> %s",
        len(df), len(keep), len(reject), out_dir,
    )
    return out_dir
