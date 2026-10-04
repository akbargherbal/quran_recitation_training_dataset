"""Command-line interface for aqfilter."""

from __future__ import annotations

import argparse
import logging
import sys

from aqfilter import __version__
from aqfilter.config import DEFAULT_BENCHMARK_N, DEFAULT_K


def _parse_k_reciter(values: list[str] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in values or []:
        if "=" not in item:
            raise argparse.ArgumentTypeError(
                f"--k-reciter expects NAME=VAL, got {item!r}"
            )
        name, val = item.split("=", 1)
        out[name.strip()] = float(val)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aqfilter",
        description="Reference-calibrated audio quality filter for MP3 recitation clips.",
    )
    parser.add_argument("--version", action="version", version=f"aqfilter {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="compute metrics for every MP3")
    p_score.add_argument("--data", required=True, help="dataset directory (recursive)")
    p_score.add_argument("--out", required=True, help="output scores CSV")
    p_score.add_argument("--workers", type=int, default=None,
                         help="worker processes (default: cpu_count-1)")
    p_score.add_argument("--resume", action="store_true",
                         help="skip filenames already present in --out")
    p_score.add_argument("--log", default=None, help="log file (default: next to --out)")
    p_score.add_argument("--benchmark-n", type=int, default=DEFAULT_BENCHMARK_N,
                         help="files used for the pre-run ETA benchmark")

    p_cal = sub.add_parser("calibrate", help="derive thresholds from references")
    p_cal.add_argument("--scores", required=True)
    p_cal.add_argument("--refs", required=True, help="reference file (txt/csv) or directory")
    p_cal.add_argument("--out", required=True, help="output thresholds JSON")
    p_cal.add_argument("--k", type=float, default=DEFAULT_K, help="margin factor (default 0.25)")
    p_cal.add_argument("--k-reciter", action="append", default=None, metavar="NAME=VAL",
                       help="per-reciter k override (repeatable)")

    p_plot = sub.add_parser("plot", help="per-reciter histograms + summary")
    p_plot.add_argument("--scores", required=True)
    p_plot.add_argument("--refs", required=True)
    p_plot.add_argument("--out", required=True, help="output plot directory")
    p_plot.add_argument("--thresholds", default=None)

    p_rev = sub.add_parser("review", help="material for the listening check")
    p_rev.add_argument("--scores", required=True)
    p_rev.add_argument("--thresholds", required=True)
    p_rev.add_argument("--data", required=True)
    p_rev.add_argument("--out", required=True)
    p_rev.add_argument("--n", type=int, default=5)
    p_rev.add_argument("--zip", action="store_true", help="also produce review.zip")

    p_fil = sub.add_parser("filter", help="apply thresholds and write keep/reject")
    p_fil.add_argument("--scores", required=True)
    p_fil.add_argument("--thresholds", required=True)
    p_fil.add_argument("--out-dir", required=True)
    p_fil.add_argument("--copy-to", default=None, help="optional dir for kept files")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "score":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )

    if args.command == "score":
        from aqfilter.score import run_score

        run_score(
            data=args.data,
            out=args.out,
            workers=args.workers,
            resume=args.resume,
            log_path=args.log,
            benchmark_n=args.benchmark_n,
        )
    elif args.command == "calibrate":
        from aqfilter.calibrate import run_calibrate

        run_calibrate(
            scores=args.scores,
            refs=args.refs,
            out=args.out,
            k=args.k,
            k_reciter=_parse_k_reciter(args.k_reciter),
        )
    elif args.command == "plot":
        from aqfilter.plotting import run_plot

        run_plot(
            scores=args.scores,
            refs=args.refs,
            out_dir=args.out,
            thresholds_path=args.thresholds,
        )
    elif args.command == "review":
        from aqfilter.review import run_review

        run_review(
            scores=args.scores,
            thresholds_path=args.thresholds,
            data=args.data,
            out=args.out,
            n=args.n,
            make_zip=args.zip,
        )
    elif args.command == "filter":
        from aqfilter.filtering import run_filter

        run_filter(
            scores=args.scores,
            thresholds_path=args.thresholds,
            out_dir=args.out_dir,
            copy_to=args.copy_to,
        )
    else:  # pragma: no cover - argparse enforces the choices
        parser.error(f"unknown command {args.command!r}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
