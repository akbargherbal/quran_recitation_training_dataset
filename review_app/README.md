# aqfilter listening-review app

A tiny Flask app that turns the `review/` clips into a guided listening session
and exports the verdict I need to re-calibrate. No build step, no database.

## What it does

- Plays the 45 clips (`above/`, `below/`, `random_rejects/` for each reciter),
  showing each clip's metrics and the exact checks it failed.
- Asks, per clip, **does it sound good / bad / unsure**.
- Asks, per reciter, **too loose / about right / too strict**, which metric(s)
  look suspect, and free-text notes.
- Autosaves everything (browser + server) and exports a shareable
  **`review_report.json`** and **`review_report.md`** that you can send back.

## Quick start (self-contained bundle)

If you have `aqfilter_review_app.zip` (contains both `review/` and
`review_app/`):

```bash
unzip aqfilter_review_app.zip
cd aqfilter_review_app
python -m pip install flask
python review_app/app.py
```

Then open <http://127.0.0.1:5000>.

## Quick start (from this repo)

```bash
cd review_app
python -m pip install -r requirements.txt
python app.py --review-dir ../review        # or --review-dir ../review.zip
```

Useful options:

| Flag | Meaning |
|---|---|
| `--review-dir PATH` | `review/` folder **or** `review.zip` (auto-extracted) |
| `--output-dir DIR` | where answers/report are written (default `./review_report`) |
| `--host`, `--port` | bind address (default `127.0.0.1:5000`) |

The app auto-detects `./review`, `./review.zip`, `../review`, etc. if
`--review-dir` is omitted.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | play / pause the highlighted clip |
| `↑` / `↓` (or `←` / `→`) | move the highlight |
| `g` / `b` / `u` | mark highlighted clip good / bad / unsure |

## Where your answers go

Two copies are kept so nothing is lost:

- **Browser** — `localStorage` (survives a refresh / accidental tab close).
- **Server** — `<output-dir>/answers.json`, autosaved on every change.

When you click **Export report**, the server writes:

- `<output-dir>/review_report.json` — machine-readable, for me to re-calibrate.
- `<output-dir>/review_report.md` — human-readable summary, with a copy-paste
  verdict block at the top.

Both are also offered as downloads from the export dialog. Share **either** file
back with me — the JSON is preferred.

## Tests

```bash
cd review_app
python -m unittest discover -s tests -v
```

15 tests cover data parsing (folder + `review.csv` + zip), audio serving
(including range requests and path-traversal rejection), answer persistence,
and report/export generation. A test also validates the real 45-clip dataset
when `../review/` is present.
