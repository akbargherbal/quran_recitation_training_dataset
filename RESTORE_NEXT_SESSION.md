# Restore next session — handoff

_Everything needed to recover this OpenCode session and resume the project after
the VM dies. Written 2026-10-04._

## TL;DR

- **Session:** `ses_efab17986ffeabT6Yhuerxczxe` — "Quran reciter finetuning implementation plan"
- **Session store:** `gs://akbar-december-2024-backup/opencode_sessions/by_host/93aaaef1bef7/`
- **Project repo:** https://github.com/akbargherbal/quran_recitation_training_dataset (branch `main`)
- **Project store:** `gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/`

## What is backed up

### 1. OpenCode session (this conversation)

Via [`vm-continuity`](https://github.com/akbargherbal/vm-continuity) — independent
of the project backup:

```
gs://akbar-december-2024-backup/opencode_sessions/by_host/93aaaef1bef7/
├── opencode.db                                   # consistent sqlite snapshot (~18 MB)
├── sessions/ses_efab17986ffeabT6Yhuerxczxe.json  # lossless, re-importable (~6 MB, 190 msgs)
├── config/opencode.json, opencode.jsonc
└── CAPTURE.json                                  # sessions exported 1/1, opencode v2.0.22
```

`CAPTURE.json` `sessions.exported` must be `1/1`. The ~5.7 GB workspace
`snapshot/` is intentionally **skipped** (`CONTINUITY_SIDE_MAX_MB`, default 200 MB).

### 2. Project work (`aqfilter`)

```
gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter/
├── checkpoints/scores.csv                 # THE expensive artifact (13,501 rows)
├── work/aqfilter_work_latest.tar.gz       # code/docs/logs + clean scores.csv + review_app/
├── work/scores.csv, work/status.txt
└── review/review.zip                      # listening material (45 clips, 21.8 MB)
    review/aqfilter_review_app.zip         # self-contained review web app + clips
```

The ~5.6 GB source MP3 dataset is **not** backed up (re-downloadable, below).

## Restore the session on a fresh VM

```bash
# 1. Get the tool and pull the store
git clone https://github.com/akbargherbal/vm-continuity ~/vm-continuity
cd ~/vm-continuity
python3 continuity.py pull                    # fetches by_host/93aaaef1bef7/ to /content/vm_state

# 2. Restore either the exact DB or a portable per-session import
python3 continuity.py restore opencode -- --mode db
#   OR, to import into a specific project dir (portable across OpenCode versions):
python3 continuity.py restore opencode -- --mode export --directory /content/quran_recitations

# 3. Reopen the session
opencode -s ses_efab17986ffeabT6Yhuerxczxe
```

Notes:
- `--mode db` restores the whole-store snapshot (backs up any existing db first).
- `--mode export` imports `/content/vm_state/opencode/sessions/*.json`; the session
  **id is preserved**, so `opencode -s <id>` works.
- Per the tool's own rule, a live import was **not** run (it would disturb the
  running session), so treat the cold-VM restore as the real proof.

## Resume the project

```bash
# code + docs + scores.csv
DEST=gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/aqfilter
TMP=$(mktemp -d)
gcloud storage cp "$DEST/work/aqfilter_work_latest.tar.gz" "$TMP/"
mkdir -p /content/quran_recitations
tar -xzf "$TMP/aqfilter_work_latest.tar.gz" -C /content/quran_recitations

# source dataset (never checkpointed)
gcloud storage cp -r gs://akbar-december-2024-backup/OSTRIS_Arabic_Suno_Finetuning/quran_dataset_AHH_long_aya/ /content/quran_recitations/data/
```

Then read **`/content/quran_recitations/SESSION_STATE.md`** — it is the cold-start
handoff for the pipeline (status, backups, remaining stages, STOP gates).

### Where the project is right now

Pipeline done: dataset download → `score` (13,501/13,501, 0 decode failures) →
`calibrate` → `plot` → `review --zip`.

**Current STOP gate (gate 2):** waiting on the user's per-reciter listening
verdict before choosing `--k`. The user reviews the clips with the Flask app
(`review_app/`, or the GCS bundle `review/aqfilter_review_app.zip`) and returns
`review_report.json` / `review_report.md`.

Then, with no rescoring:
```bash
python3 -m aqfilter calibrate --scores scores.csv --refs refs.txt --out thresholds.json [--k ...] [--k-reciter NAME=VAL ...]
python3 -m aqfilter review    --scores scores.csv --thresholds thresholds.json --data data/ --out review/ --zip
python3 -m aqfilter filter    --scores scores.csv --thresholds thresholds.json --out-dir results/
```

Deliverables: `results/{keep.csv, reject.csv, summary.md, keep_list.txt}` plus
`thresholds.json` and `scores.csv`.

## Keep the session backup current

A detached watch loop (capture+ship every 5 min) runs after restore:

```bash
cd ~/vm-continuity
setsid python3 continuity.py watch --interval-minutes 5 opencode \
  >/content/vm_state/continuity_watch.log 2>&1 < /dev/null &
python3 continuity.py status        # -> loop=running state=OK   (exit 0 = healthy)
pkill -f 'continuity.py watch'      # stop
```

## Fixes already pushed upstream (vm-continuity)

- **`56eae4b`** — OpenCode **v2.0.22** support: `export`/`import` moved under the
  `session` subcommand (`opencode session export <id>`, `... import <file>
  --directory <dir>`). The tool probes once and caches the spelling, with the v1
  top-level form as fallback. Without this, capture silently exported **0 sessions**
  (a 2 KB help-text file).
- **`56eae4b`** — skip side dirs (`data_dir()/snapshot`, `tool-output`) larger than
  `CONTINUITY_SIDE_MAX_MB` (default 200 MB) so a session backup doesn't ship the
  whole project. Tests: `tests/test_opencode_cli.py`; full suite **18 passed**.

## Git commits of note

| Repo | Commit | What |
|---|---|---|
| vm-continuity | `56eae4b` | v2.0.22 export/import + oversized-side-dir guard |
| quran_recitation_training_dataset | `14b4eb7` | document session continuity in `SESSION_STATE.md` |
| quran_recitation_training_dataset | `b2fbc3f` | Flask listening-review app + report export |
| quran_recitation_training_dataset | `95b59f5` | document `review.zip` GCS location |

## Key invariants

- Never delete or modify the source MP3s under `data/`.
- Capture must be consistent: snapshot live SQLite with `sqlite3.backup()`, never
  rsync a live DB.
- `db/opencode.db` is a fallback; the per-session JSON is the version-robust,
  re-importable record.
