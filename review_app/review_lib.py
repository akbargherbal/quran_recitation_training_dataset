"""Data loading + report building for the aqfilter listening-review app.

Standard library only. `app.py` adds the Flask layer on top.
"""

from __future__ import annotations

import atexit
import csv
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

# --------------------------------------------------------------------------- #
# Configuration constants (mirrors what the calibration step asks the user)
# --------------------------------------------------------------------------- #

GROUPS = ["above", "below", "random_rejects"]

GROUP_BLURB = {
    "above": {
        "title": "just ABOVE the ovrl_mos threshold",
        "hint": "If these sound BAD, the boundary is too LOOSE.",
    },
    "below": {
        "title": "just BELOW the ovrl_mos threshold",
        "hint": "If these sound clearly GOOD, the boundary is too STRICT.",
    },
    "random_rejects": {
        "title": "rejected by at least one check",
        "hint": "If these sound GOOD, a non-MOS gate (often bandwidth_hz) over-rejects.",
    },
}

METRIC_ORDER = [
    "ovrl_mos",
    "sig_mos",
    "bak_mos",
    "snr_est_db",
    "noise_floor_db",
    "bandwidth_hz",
]

METRIC_LABEL = {
    "ovrl_mos": "Overall MOS",
    "sig_mos": "Signal MOS",
    "bak_mos": "Background MOS",
    "p808_mos": "P808 MOS",
    "snr_est_db": "SNR (dB)",
    "noise_floor_db": "Noise floor (dB)",
    "bandwidth_hz": "Bandwidth (Hz)",
    "clipping_ratio": "Clipping",
    "duration_s": "Duration (s)",
}

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac")

VERDICTS = [
    {
        "value": "too_loose",
        "label": "Too loose",
        "hint": "Keeps clips that sound bad (above/ sounds bad).",
    },
    {
        "value": "about_right",
        "label": "About right",
        "hint": "above/ sounds bad and below/ sounds good.",
    },
    {
        "value": "too_strict",
        "label": "Too strict",
        "hint": "Rejects clips that sound clearly acceptable (below/ sounds good).",
    },
]

VERDICT_LABEL = {v["value"]: v["label"] for v in VERDICTS}

# The questions the report answers. Kept in one place so the UI and the exported
# report stay in sync.
QUESTIONS = {
    "reciter_verdict": {
        "prompt": "Overall, is this reciter's quality boundary too loose, about right, or too strict?",
        "options": VERDICTS,
        "required": True,
    },
    "metrics_suspect": {
        "prompt": "Which metric(s), if any, look like they over- or under-reject?",
        "options": [m for m in METRIC_ORDER] + ["none", "unsure"],
        "required": False,
    },
    "clip_verdict": {
        "prompt": "Does this clip sound acceptable?",
        "options": [
            {"value": "good", "label": "Sounds good"},
            {"value": "bad", "label": "Sounds bad"},
            {"value": "unsure", "label": "Unsure"},
        ],
    },
    "free_text": {
        "global": "Anything else I should know before I re-calibrate?",
        "reciter": "Notes for this reciter (optional)",
        "clip": "Note for this clip (optional)",
    },
}

# --------------------------------------------------------------------------- #
# review directory / zip resolution
# --------------------------------------------------------------------------- #

_EXTRACTED: list[str] = []


def _cleanup_extracted() -> None:
    for d in _EXTRACTED:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_extracted)


def _looks_like_root(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    if os.path.isfile(os.path.join(path, "review.csv")):
        return True
    for entry in os.listdir(path):
        sub = os.path.join(path, entry)
        if os.path.isdir(sub) and any(
            os.path.isdir(os.path.join(sub, g)) for g in GROUPS
        ):
            return True
    return False


def _find_root(base: str) -> str:
    if _looks_like_root(base):
        return base
    # Common layout: <base>/review/
    cand = os.path.join(base, "review")
    if _looks_like_root(cand):
        return cand
    # Otherwise search a couple of levels deep.
    for dirpath, dirnames, filenames in os.walk(base):
        depth = dirpath[len(base):].count(os.sep)
        if _looks_like_root(dirpath):
            return dirpath
        if depth >= 2:
            dirnames[:] = []
    raise FileNotFoundError(
        f"Could not find a review folder (with review.csv or <reciter>/<group>/ "
        f"subdirs) under: {base}"
    )


def resolve_review_root(path: str) -> str:
    """Return the directory that holds the reciter folders.

    Accepts a directory *or* a `review.zip` (which is extracted to a temp dir).
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if os.path.isfile(path):
        if not zipfile.is_zipfile(path):
            raise ValueError(f"Not a zip file: {path}")
        tmp = tempfile.mkdtemp(prefix="aqfilter_review_")
        _EXTRACTED.append(tmp)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        return _find_root(tmp)
    return _find_root(path)


# --------------------------------------------------------------------------- #
# Clip model
# --------------------------------------------------------------------------- #


@dataclass
class Clip:
    reciter: str
    group: str
    filename: str
    copied_name: str
    rank: int
    metrics: dict = field(default_factory=dict)
    fail_reason: list = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.reciter}|{self.group}|{self.filename}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "reciter": self.reciter,
            "group": self.group,
            "filename": self.filename,
            "copied_name": self.copied_name,
            "rank": self.rank,
            "metrics": self.metrics,
            "fail_reason": self.fail_reason,
            "audio_url": "/audio/{}/{}/{}".format(
                quote(self.reciter, safe=""),
                quote(self.group, safe=""),
                quote(self.filename, safe=""),
            ),
        }


def _as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rank_from_name(filename: str) -> int:
    head = filename.split("_", 1)[0]
    return int(head) if head.isdigit() else 0


def _clip_from_row(reciter, group, filename, row):
    metrics: dict = {}
    fail_reason: list = []
    copied_name = filename
    rank = _rank_from_name(filename)

    if row:
        copied_name = row.get("copied_name") or filename
        try:
            rank = int(row.get("rank"))
        except (TypeError, ValueError):
            rank = _rank_from_name(filename)
        for key, value in row.items():
            if key in ("reciter", "group", "filename", "copied_name", "fail_reason", "rank"):
                continue
            num = _as_float(value)
            if num is not None:
                metrics[key] = num
        raw = (row.get("fail_reason") or "").strip()
        if raw:
            fail_reason = [p.strip() for p in raw.split(";") if p.strip()]

    return Clip(
        reciter=reciter,
        group=group,
        filename=filename,
        copied_name=copied_name,
        rank=rank,
        metrics=metrics,
        fail_reason=fail_reason,
    )


class ReviewRoot:
    def __init__(self, root, reciters, total, has_metrics):
        self.root = root
        self.reciters = reciters  # [{"name", "groups": {group: [Clip, ...]}}]
        self.total = total
        self.has_metrics = has_metrics
        self._by_id = {
            clip.id: clip
            for rec in reciters
            for clips in rec["groups"].values()
            for clip in clips
        }

    def clip(self, reciter, group, filename):
        if group not in GROUPS:
            return None
        return self._by_id.get(f"{reciter}|{group}|{filename}")

    def iter_clips(self):
        return self._by_id.values()

    def to_config(self) -> dict:
        reciters = []
        for rec in self.reciters:
            groups = {}
            for group in GROUPS:
                groups[group] = [c.to_dict() for c in rec["groups"].get(group, [])]
            reciters.append({"name": rec["name"], "groups": groups})
        return {
            "app": "aqfilter listening review",
            "root": self.root,
            "reciters": reciters,
            "groups": GROUPS,
            "group_blurb": GROUP_BLURB,
            "metric_order": METRIC_ORDER,
            "metric_label": METRIC_LABEL,
            "questions": QUESTIONS,
            "verdicts": VERDICTS,
            "total_clips": self.total,
            "has_metrics": self.has_metrics,
        }


def load_review(path: str) -> ReviewRoot:
    root = resolve_review_root(path)

    csv_rows = {}
    csv_path = os.path.join(root, "review.csv")
    if os.path.isfile(csv_path):
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                key = (
                    row.get("reciter", ""),
                    row.get("group", ""),
                    row.get("copied_name") or row.get("filename"),
                )
                csv_rows[key] = row

    reciter_names = sorted(
        entry
        for entry in os.listdir(root)
        if os.path.isdir(os.path.join(root, entry))
        and any(os.path.isdir(os.path.join(root, entry, g)) for g in GROUPS)
    )

    reciters = []
    total = 0
    has_metrics = False
    for name in reciter_names:
        groups = {}
        for group in GROUPS:
            gdir = os.path.join(root, name, group)
            clips = []
            if os.path.isdir(gdir):
                for fn in sorted(os.listdir(gdir)):
                    if not fn.lower().endswith(AUDIO_EXTS):
                        continue
                    row = csv_rows.get((name, group, fn))
                    clip = _clip_from_row(name, group, fn, row)
                    if clip.metrics:
                        has_metrics = True
                    clips.append(clip)
                clips.sort(key=lambda c: (c.rank, c.filename))
            groups[group] = clips
            total += len(clips)
        reciters.append({"name": name, "groups": groups})

    if total == 0:
        raise FileNotFoundError(f"No audio clips found under: {root}")
    return ReviewRoot(root, reciters, total, has_metrics)


# --------------------------------------------------------------------------- #
# Report building
# --------------------------------------------------------------------------- #


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_clip_counts():
    return {"good": 0, "bad": 0, "unsure": 0, "unrated": 0}


def build_report(data: ReviewRoot, answers: dict):
    """Return (report_dict, markdown_str)."""
    answers = answers or {}
    rec_answers = answers.get("reciters") or {}

    report = {
        "schema_version": 1,
        "kind": "aqfilter_review_report",
        "generated_at": _now(),
        "source_review_dir": data.root,
        "reviewer": (answers.get("reviewer") or "").strip(),
        "global_notes": (answers.get("global_notes") or "").strip(),
        "questions": QUESTIONS,
        "reciters": {},
    }

    total_rated = 0
    for rec in data.reciters:
        name = rec["name"]
        a = rec_answers.get(name) or {}
        clip_answers = a.get("clips") or {}
        counts = _empty_clip_counts()
        clip_rows = []
        for group in GROUPS:
            for clip in rec["groups"].get(group, []):
                ca = clip_answers.get(clip.id) or {}
                verdict = ca.get("verdict") or "unrated"
                if verdict not in counts:
                    verdict = "unrated"
                counts[verdict] += 1
                if verdict != "unrated":
                    total_rated += 1
                clip_rows.append(
                    {
                        "id": clip.id,
                        "group": group,
                        "rank": clip.rank,
                        "filename": clip.filename,
                        "verdict": verdict,
                        "note": (ca.get("note") or "").strip(),
                        "metrics": clip.metrics,
                        "fail_reason": clip.fail_reason,
                    }
                )

        verdict = a.get("verdict") or ""
        report["reciters"][name] = {
            "verdict": verdict,
            "verdict_label": VERDICT_LABEL.get(verdict, ""),
            "metrics_suspect": a.get("metrics_suspect") or [],
            "notes": (a.get("notes") or "").strip(),
            "clip_summary": counts,
            "clips": clip_rows,
            "completed": bool(verdict),
        }

    total_clips = sum(
        len(rec["groups"].get(g, [])) for rec in data.reciters for g in GROUPS
    )
    report["totals"] = {
        "reciters": len(report["reciters"]),
        "reciters_answered": sum(
            1 for r in report["reciters"].values() if r["completed"]
        ),
        "clips": total_clips,
        "clips_rated": total_rated,
        "complete": bool(report["reciters"])
        and all(r["completed"] for r in report["reciters"].values()),
    }

    return report, render_markdown(report)


def _fmt_metric(key, value):
    if value is None:
        return "—"
    if key == "bandwidth_hz":
        return f"{value / 1000:.1f} kHz" if value >= 1000 else f"{value:.0f} Hz"
    if key in ("ovrl_mos", "sig_mos", "bak_mos", "p808_mos"):
        return f"{value:.2f}"
    if key == "duration_s":
        return f"{value:.1f}s"
    return f"{value:.2f}"


def render_markdown(report: dict) -> str:
    lines = []
    lines.append("# aqfilter listening-review report")
    lines.append("")
    lines.append(f"- **generated:** {report['generated_at']}")
    if report.get("reviewer"):
        lines.append(f"- **reviewer:** {report['reviewer']}")
    tot = report["totals"]
    lines.append(
        f"- **progress:** {tot['reciters_answered']}/{tot['reciters']} reciters, "
        f"{tot['clips_rated']}/{tot['clips']} clips rated"
    )
    lines.append(f"- **complete:** {'yes' if tot['complete'] else 'no'}")
    lines.append("")

    lines.append("## Verdict summary (the answer I need)")
    lines.append("")
    lines.append("```")
    for name, r in report["reciters"].items():
        lines.append(f"{name}: {r['verdict_label'] or '(no verdict)'}")
    lines.append("```")
    lines.append("")

    lines.append("## Per-reciter detail")
    lines.append("")
    for name, r in report["reciters"].items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- **verdict:** {r['verdict_label'] or '(no verdict)'}")
        suspect = ", ".join(r["metrics_suspect"]) if r["metrics_suspect"] else "—"
        lines.append(f"- **metrics that look suspect:** {suspect}")
        lines.append(f"- **notes:** {r['notes'] or '—'}")
        cs = r["clip_summary"]
        lines.append(
            f"- **clip ratings:** good={cs['good']} bad={cs['bad']} "
            f"unsure={cs['unsure']} unrated={cs['unrated']}"
        )
        rated = [c for c in r["clips"] if c["verdict"] != "unrated"]
        if rated:
            lines.append("")
            lines.append("| group | rank | file | rating | note |")
            lines.append("|---|---|---|---|---|")
            for c in rated:
                note = c["note"].replace("|", "\\|")
                lines.append(
                    f"| {c['group']} | {c['rank']} | `{c['filename']}` | "
                    f"{c['verdict']} | {note or ''} |"
                )
        lines.append("")

    if report.get("global_notes"):
        lines.append("## Global notes")
        lines.append("")
        lines.append(report["global_notes"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
