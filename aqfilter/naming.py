"""Filename parsing, dataset scanning, and reference-list reading."""

from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from pathlib import Path

log = logging.getLogger("aqfilter")

# <Reciter>_<kbps>kbps_<SSS><AAA>.mp3
FILENAME_RE = re.compile(
    r"^(?P<reciter>.+?)_(?P<kbps>\d+)kbps_(?P<surah>\d{3})(?P<ayah>\d{3})\.mp3$"
)


def parse_name(name: str) -> dict | None:
    """Parse a dataset basename. Returns None if it does not match the pattern."""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    return {
        "reciter": m.group("reciter"),
        "kbps_label": int(m.group("kbps")),
        "surah": int(m.group("surah")),
        "ayah": int(m.group("ayah")),
    }


def parse_or_unknown(name: str) -> dict:
    """Like :func:`parse_name` but returns an UNKNOWN record on mismatch."""
    parsed = parse_name(name)
    if parsed is None:
        return {"reciter": "UNKNOWN", "kbps_label": None, "surah": None, "ayah": None}
    return parsed


def scan_mp3s(data_dir: str | Path) -> list[Path]:
    """Recursively find ``*.mp3`` files, sorted for deterministic ordering."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise NotADirectoryError(f"--data is not a directory: {data_dir}")
    return sorted(p for p in data_dir.rglob("*.mp3") if p.is_file())


def report_parse(files: list[Path]) -> None:
    """Print distinct reciter keys + counts and report non-matching filenames."""
    from collections import Counter

    counts: "Counter[str]" = Counter()
    bad: list[str] = []
    for p in files:
        parsed = parse_name(p.name)
        if parsed is None:
            bad.append(p.name)
            counts["UNKNOWN"] += 1
        else:
            counts[parsed["reciter"]] += 1

    log.info("Parsed %d files; distinct reciters:", len(files))
    for reciter, n in sorted(counts.items()):
        log.info("  %-35s %d", reciter, n)

    if bad:
        log.warning("Non-matching filenames: %d", len(bad))
        for name in bad[:20]:
            log.warning("  %s", name)


def _basename(value: str) -> str:
    return value.strip().replace("\\", "/").split("/")[-1]


def read_refs(refs: str | Path) -> list[str]:
    """Read reference basenames from a directory or a text/CSV file.

    Directory: recursive ``*.mp3`` basenames (folder names irrelevant). Warns if
    any single subfolder mixes files from more than one reciter.

    File: ``.csv`` uses the ``filename`` column (falls back to the first column);
    otherwise one basename per line. Blank lines and ``#`` comments are ignored.
    """
    refs = Path(refs)
    if not refs.exists():
        raise FileNotFoundError(f"--refs does not exist: {refs}")

    if refs.is_dir():
        by_dir: dict[Path, list[str]] = defaultdict(list)
        for p in sorted(refs.rglob("*.mp3")):
            if p.is_file():
                by_dir[p.parent].append(p.name)
        for parent, names in by_dir.items():
            reciters = {
                parsed["reciter"]
                for n in names
                if (parsed := parse_name(n)) is not None
            }
            if len(reciters) > 1:
                log.warning(
                    "Reference folder %s mixes reciters: %s",
                    parent,
                    ", ".join(sorted(reciters)),
                )
        names = [n for group in by_dir.values() for n in group]
        if not names:
            raise ValueError(f"No *.mp3 files found under --refs directory: {refs}")
        return sorted(set(names))

    # A file: .csv or plain text.
    names: list[str] = []
    if refs.suffix.lower() == ".csv":
        with refs.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            field = None
            if reader.fieldnames:
                field = "filename" if "filename" in reader.fieldnames else reader.fieldnames[0]
            for row in reader:
                if field is not None and row.get(field):
                    names.append(_basename(row[field]))
    else:
        for line in refs.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            names.append(_basename(line))
    if not names:
        raise ValueError(f"No reference filenames found in {refs}")
    return sorted(set(names))
