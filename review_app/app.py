#!/usr/bin/env python3
"""aqfilter listening-review web app.

Serves the clips from a `review/` folder (or `review.zip`) and captures your
per-clip and per-reciter judgements, then exports a shareable report.

Usage:
    python app.py                      # auto-detects ./review or ./review.zip
    python app.py --review-dir review --port 5000
    python app.py --review-dir review.zip

Then open http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _default_review_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.environ.get("REVIEW_DIR"),
        os.path.join(os.getcwd(), "review"),
        os.path.join(os.getcwd(), "review.zip"),
        os.path.join(here, "review"),
        os.path.join(os.path.dirname(here), "review"),
        os.path.join(os.path.dirname(here), "review.zip"),
    ):
        if cand and os.path.exists(cand):
            return cand
    return os.path.join(os.getcwd(), "review")


def _write_text(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def create_app(review_path: str, output_dir: str | None = None):
    from review_lib import build_report, load_review  # local import after sys.path tweak

    data = load_review(review_path)

    output_dir = os.path.abspath(output_dir or os.path.join(os.getcwd(), "review_report"))
    os.makedirs(output_dir, exist_ok=True)
    answers_path = os.path.join(output_dir, "answers.json")
    report_json = os.path.join(output_dir, "review_report.json")
    report_md = os.path.join(output_dir, "review_report.md")

    app = Flask(__name__)
    app.config["REVIEW_DATA"] = data
    app.config["OUTPUT_DIR"] = output_dir

    def load_answers() -> dict:
        if os.path.isfile(answers_path):
            try:
                with open(answers_path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                pass
        return {"reviewer": "", "global_notes": "", "reciters": {}}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/config")
    def api_config():
        cfg = data.to_config()
        cfg["answers"] = load_answers()
        cfg["output_dir"] = output_dir
        cfg["answers_path"] = answers_path
        return jsonify(cfg)

    @app.get("/api/health")
    def api_health():
        return jsonify(
            {
                "ok": True,
                "root": data.root,
                "reciters": [r["name"] for r in data.reciters],
                "total_clips": data.total,
            }
        )

    @app.get("/audio/<reciter>/<group>/<path:filename>")
    def audio(reciter, group, filename):
        clip = data.clip(reciter, group, filename)
        if clip is None:
            abort(404)
        return send_from_directory(
            os.path.join(data.root, reciter, group),
            filename,
            mimetype="audio/mpeg",
            conditional=True,
        )

    @app.post("/api/answers")
    def api_save_answers():
        payload = request.get_json(force=True, silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "expected a JSON object"}), 400
        _write_text(answers_path, json.dumps(payload, indent=2, ensure_ascii=False))
        return jsonify({"ok": True, "answers_path": answers_path})

    @app.post("/api/export")
    def api_export():
        payload = request.get_json(force=True, silent=True)
        answers = None
        if isinstance(payload, dict):
            answers = payload.get("answers", payload if "reciters" in payload else None)
        if not answers:
            answers = load_answers()

        _write_text(answers_path, json.dumps(answers, indent=2, ensure_ascii=False))
        report, markdown = build_report(data, answers)
        _write_text(report_json, json.dumps(report, indent=2, ensure_ascii=False))
        _write_text(report_md, markdown)

        return jsonify(
            {
                "ok": True,
                "complete": report["totals"]["complete"],
                "totals": report["totals"],
                "report": report,
                "markdown": markdown,
                "downloads": {
                    "json": "/download/review_report.json",
                    "markdown": "/download/review_report.md",
                },
                "saved_to": {"json": report_json, "markdown": report_md},
            }
        )

    @app.get("/download/review_report.json")
    def download_json():
        if not os.path.isfile(report_json):
            abort(404)
        return send_file(
            report_json, as_attachment=True, download_name="review_report.json"
        )

    @app.get("/download/review_report.md")
    def download_md():
        if not os.path.isfile(report_md):
            abort(404)
        return send_file(
            report_md, as_attachment=True, download_name="review_report.md"
        )

    return app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="aqfilter listening-review web app")
    parser.add_argument(
        "--review-dir",
        default=None,
        help="Path to the unzipped review folder or review.zip "
        "(default: auto-detect ./review or ./review.zip)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to write answers.json + review_report.* (default: ./review_report)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    review_path = args.review_dir or _default_review_path()
    if not os.path.exists(review_path):
        print(f"error: review path not found: {review_path}", file=sys.stderr)
        return 2

    app = create_app(review_path, args.output_dir)
    print(f"Review data : {app.config['REVIEW_DATA'].root}")
    print(f"Output dir  : {app.config['OUTPUT_DIR']}")
    print(f"Open        : http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
