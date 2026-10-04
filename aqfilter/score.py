"""``score`` subcommand: compute per-file metrics into a CSV."""

from __future__ import annotations

import csv
import logging
import multiprocessing as mp
import time
from pathlib import Path

from tqdm import tqdm

from aqfilter.audio_io import clamp, decode, resample_to_16k
from aqfilter.config import CHUNKSIZE, DEFAULT_BENCHMARK_N, FLUSH_EVERY, SCORE_COLUMNS
from aqfilter.dnsmos_wrap import run_dnsmos, worker_init
from aqfilter.metrics import bandwidth_hz, clipping_ratio, level_metrics
from aqfilter.naming import parse_or_unknown, report_parse, scan_mp3s

log = logging.getLogger("aqfilter")


def default_workers() -> int:
    return max(1, (mp.cpu_count() or 1) - 1)


def configure_logging(log_path: Path | None) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    log.addHandler(stream)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(fmt)
        log.addHandler(handler)


def read_done_filenames(out_path: Path) -> set[str]:
    done: set[str] = set()
    if not out_path.exists() or out_path.stat().st_size == 0:
        return done
    with out_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return done
        key = "filename" if "filename" in reader.fieldnames else reader.fieldnames[0]
        for row in reader:
            value = row.get(key)
            if value:
                done.add(value)
    return done


def _score_one(args: tuple[str, str]) -> dict:
    """Worker entry point. Never raises; returns a failure row instead."""
    path_str, data_root_str = args
    path = Path(path_str)
    data_root = Path(data_root_str)

    row: dict = {col: "" for col in SCORE_COLUMNS}
    row["filename"] = path.name
    try:
        row["path"] = str(path.relative_to(data_root))
    except ValueError:
        row["path"] = path.name

    parsed = parse_or_unknown(path.name)
    row["reciter"] = parsed["reciter"]
    row["kbps_label"] = parsed["kbps_label"]
    row["surah"] = parsed["surah"]
    row["ayah"] = parsed["ayah"]

    try:
        mono, sr = decode(path)
    except Exception as exc:  # noqa: BLE001 - record and move on
        row["decode_ok"] = False
        row["error"] = f"decode: {exc}"
        return row

    # Decode succeeded: from here a failure is a metric failure, not a decode one.
    row["decode_ok"] = True
    try:
        duration = mono.size / float(sr) if sr else 0.0
        row["duration_s"] = duration
        row["native_sr"] = sr
        if duration > 0:
            row["actual_kbps"] = path.stat().st_size * 8 / duration / 1000.0

        row["clipping_ratio"] = clipping_ratio(mono)
        row["bandwidth_hz"] = bandwidth_hz(mono, sr)

        x16 = resample_to_16k(mono, sr)
        row.update(level_metrics(x16))
        row.update(run_dnsmos(clamp(x16)))
    except Exception as exc:  # noqa: BLE001 - keep partial row
        row["error"] = f"metric: {exc}"
    return row


def _benchmark(paths: list[Path], data_root: str, workers: int, n: int) -> dict | None:
    sample = paths[:n]
    if not sample:
        return None
    args = [(str(p), data_root) for p in sample]
    arrivals: list[float] = []
    fails = 0
    with mp.Pool(processes=workers, initializer=worker_init) as pool:
        start = time.time()
        for row in pool.imap_unordered(_score_one, args, chunksize=CHUNKSIZE):
            arrivals.append(time.time())
            if row["decode_ok"] is False:
                fails += 1
    elapsed = time.time() - start
    if len(arrivals) > 1:
        per_file = (arrivals[-1] - arrivals[0]) / (len(arrivals) - 1)
    else:
        per_file = elapsed
    return {
        "n": len(sample),
        "elapsed": elapsed,
        "per_file": per_file,
        "fails": fails,
    }


def run_score(
    data: str | Path,
    out: str | Path,
    workers: int | None = None,
    resume: bool = False,
    log_path: str | Path | None = None,
    benchmark_n: int = DEFAULT_BENCHMARK_N,
) -> Path:
    workers = workers or default_workers()
    out = Path(out)
    data = Path(data)
    if log_path is None:
        log_path = out.with_suffix(out.suffix + ".log") if out.suffix else out.parent / "score.log"
    configure_logging(Path(log_path))

    files = scan_mp3s(data)
    report_parse(files)
    if not files:
        log.warning("No MP3 files found under %s", data)
        return out

    done = read_done_filenames(out) if resume else set()
    todo = [p for p in files if p.name not in done]
    log.info(
        "Files: %d total, %d already scored, %d to process (workers=%d)",
        len(files), len(done), len(todo), workers,
    )
    if not todo:
        log.info("Nothing to do.")
        return out

    # Quick benchmark to report an ETA before the long run.
    bench = _benchmark(todo, str(data), workers, max(1, benchmark_n))
    if bench:
        eta = bench["per_file"] * len(todo)
        log.info(
            "Benchmark: %d files in %.1fs (%.2fs/file excluding warmup), "
            "decode failures=%d",
            bench["n"], bench["elapsed"], bench["per_file"], bench["fails"],
        )
        log.info("ETA: ~%.1f min for %d files", eta / 60.0, len(todo))

    existing = out.exists() and out.stat().st_size > 0
    mode = "a" if resume else "w"
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    decode_fails = 0
    start = time.time()
    with out.open(mode, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCORE_COLUMNS, extrasaction="ignore")
        if not (resume and existing):
            writer.writeheader()
            fh.flush()
        args = ((str(p), str(data)) for p in todo)
        with mp.Pool(processes=workers, initializer=worker_init) as pool:
            for row in tqdm(
                pool.imap_unordered(_score_one, args, chunksize=CHUNKSIZE),
                total=len(todo),
                desc="score",
                unit="file",
            ):
                writer.writerow(row)
                count += 1
                if row["decode_ok"] is False:
                    decode_fails += 1
                if count % FLUSH_EVERY == 0:
                    fh.flush()
        fh.flush()

    wall = time.time() - start
    log.info(
        "Done: %d files in %.1fs (%.2fs/file), decode failures=%d -> %s",
        count, wall, wall / count if count else 0.0, decode_fails, out,
    )
    return out
