"""Tests for the aqfilter listening-review app.

Run from the review_app directory:
    python -m unittest discover -s tests -v
"""

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
sys.path.insert(0, APP_DIR)

import app as app_module  # noqa: E402
import review_lib  # noqa: E402

REPO_REVIEW = os.path.join(os.path.dirname(APP_DIR), "review")

GROUPS = ["above", "below", "random_rejects"]
CSV_HEADER = [
    "group", "rank", "copied_name", "filename", "reciter", "ovrl_mos", "sig_mos",
    "bak_mos", "p808_mos", "snr_est_db", "noise_floor_db", "bandwidth_hz",
    "clipping_ratio", "duration_s", "fail_reason",
]
# Dummy but valid-enough MP3 payloads.
MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 200


def make_fixture(root):
    """Create a minimal review/ tree with 2 reciters x 3 groups x 2 clips."""
    reciters = ["Abdul_Basit_Murattal", "Hudhaify"]
    rows = []
    for ri, rec in enumerate(reciters):
        for group in GROUPS:
            for rank in (1, 2):
                copied = "%02d_ovrl2.%d0_%s_128kbps_00000%d.mp3" % (rank, ri + 2, rec, rank)
                fname = "%s_128kbps_00000%d.mp3" % (rec, rank)
                d = os.path.join(root, rec, group)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, copied), "wb") as fh:
                    fh.write(MP3)
                rows.append({
                    "group": group,
                    "rank": rank,
                    "copied_name": copied,
                    "filename": fname,
                    "reciter": rec,
                    "ovrl_mos": 2.4 + 0.01 * rank,
                    "sig_mos": 3.0,
                    "bak_mos": 2.5,
                    "p808_mos": 2.9,
                    "snr_est_db": 25.0,
                    "noise_floor_db": -45.0,
                    "bandwidth_hz": 7000.0 if group == "random_rejects" else 13000.0,
                    "clipping_ratio": 0.0,
                    "duration_s": 20.0,
                    "fail_reason": "bandwidth_hz<1.194e+04" if group == "random_rejects" else "",
                })
    csv_path = os.path.join(root, "review.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# fixture\n")
    return root


class FixtureMixin:
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqfilter_test_")
        self.review_root = os.path.join(self.tmp, "review")
        make_fixture(self.review_root)
        self.out_dir = os.path.join(self.tmp, "out")
        self.app = app_module.create_app(self.review_root, self.out_dir)
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestDataLoading(FixtureMixin, unittest.TestCase):
    def test_counts_and_metrics(self):
        data = review_lib.load_review(self.review_root)
        self.assertEqual(data.total, 12)
        self.assertTrue(data.has_metrics)
        self.assertEqual(sorted(r["name"] for r in data.reciters),
                         ["Abdul_Basit_Murattal", "Hudhaify"])
        # clips are keyed by their on-disk (copied) filename
        d = os.path.join(self.review_root, "Hudhaify", "random_rejects")
        fn = sorted(os.listdir(d))[0]
        clip = data.clip("Hudhaify", "random_rejects", fn)
        self.assertIsNotNone(clip)
        self.assertEqual(clip.rank, 1)
        self.assertIn("bandwidth_hz", clip.metrics)
        self.assertEqual(clip.fail_reason, ["bandwidth_hz<1.194e+04"])

    def test_config_shape(self):
        cfg = self.app.test_client().get("/api/config").get_json()
        self.assertEqual(cfg["total_clips"], 12)
        self.assertEqual(len(cfg["reciters"]), 2)
        self.assertIn("reciter_verdict", cfg["questions"])
        self.assertIn("audio_url", cfg["reciters"][0]["groups"]["above"][0])


class TestRouting(FixtureMixin, unittest.TestCase):
    def test_index(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"listening review", r.data)

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["total_clips"], 12)

    def test_audio_served(self):
        cfg = self.client.get("/api/config").get_json()
        url = cfg["reciters"][0]["groups"]["above"][0]["audio_url"]
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b"\xff\xfb") or b"\xff\xfb" in r.data[:8])
        self.assertEqual(r.mimetype, "audio/mpeg")

    def test_audio_unknown_404(self):
        r = self.client.get("/audio/Hudhaify/above/nope.mp3")
        self.assertEqual(r.status_code, 404)

    def test_audio_traversal_blocked(self):
        r = self.client.get("/audio/Hudhaify/above/..%2f..%2f..%2fapp.py")
        self.assertEqual(r.status_code, 404)
        r2 = self.client.get("/audio/Hudhaify/above/../../app.py")
        self.assertEqual(r2.status_code, 404)


class TestAnswers(FixtureMixin, unittest.TestCase):
    def test_roundtrip(self):
        cfg = self.client.get("/api/config").get_json()
        clip_id = cfg["reciters"][0]["groups"]["above"][0]["id"]
        payload = {
            "reviewer": "tester",
            "global_notes": "hi",
            "reciters": {
                "Abdul_Basit_Murattal": {
                    "verdict": "too_strict",
                    "metrics_suspect": ["bandwidth_hz"],
                    "notes": "bandwidth seems low",
                    "clips": {clip_id: {"verdict": "good", "note": "fine"}},
                }
            },
        }
        r = self.client.post("/api/answers", json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        # persisted to disk
        saved = json.load(open(os.path.join(self.out_dir, "answers.json")))
        self.assertEqual(saved["reviewer"], "tester")
        # reflected by config
        cfg2 = self.client.get("/api/config").get_json()
        self.assertEqual(cfg2["answers"]["reciters"]["Abdul_Basit_Murattal"]["verdict"],
                         "too_strict")

    def test_answers_rejects_non_object(self):
        r = self.client.post("/api/answers", data="[]", content_type="application/json")
        self.assertEqual(r.status_code, 400)


class TestExport(FixtureMixin, unittest.TestCase):
    def _payload(self):
        cfg = self.client.get("/api/config").get_json()
        cid = cfg["reciters"][0]["groups"]["above"][0]["id"]
        return {
            "reviewer": "tester",
            "global_notes": "all good",
            "reciters": {
                "Abdul_Basit_Murattal": {
                    "verdict": "about_right",
                    "metrics_suspect": ["none"],
                    "notes": "sounds right",
                    "clips": {cid: {"verdict": "good", "note": "clean"}},
                },
                "Hudhaify": {
                    "verdict": "too_loose",
                    "metrics_suspect": ["bak_mos"],
                    "notes": "",
                    "clips": {},
                },
            },
        }

    def test_export_writes_files_and_report(self):
        r = self.client.post("/api/export", json={"answers": self._payload()})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["totals"]["clips_rated"], 1)
        self.assertEqual(body["totals"]["reciters_answered"], 2)
        self.assertTrue(body["complete"])
        # files on disk
        self.assertTrue(os.path.isfile(os.path.join(self.out_dir, "review_report.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.out_dir, "review_report.md")))
        # report structure
        report = body["report"]
        self.assertEqual(report["kind"], "aqfilter_review_report")
        self.assertEqual(report["reciters"]["Abdul_Basit_Murattal"]["verdict_label"],
                         "About right")
        self.assertEqual(report["reciters"]["Hudhaify"]["verdict_label"], "Too loose")
        # markdown contains the copy-pasteable verdict summary
        md = body["markdown"]
        self.assertIn("Abdul_Basit_Murattal: About right", md)
        self.assertIn("Hudhaify: Too loose", md)
        self.assertIn("## Verdict summary", md)

    def test_download_endpoints(self):
        self.client.post("/api/export", json={"answers": self._payload()})
        md = self.client.get("/download/review_report.md")
        self.assertEqual(md.status_code, 200)
        self.assertIn(b"Verdict summary", md.data)
        js = self.client.get("/download/review_report.json")
        self.assertEqual(js.status_code, 200)
        self.assertEqual(js.get_json()["kind"], "aqfilter_review_report")

    def test_export_before_any_answers(self):
        # no answers saved yet -> should still produce a report, not crash
        r = self.client.post("/api/export", json={})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["complete"])


class TestZip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aqfilter_ziptest_")
        root = make_fixture(os.path.join(self.tmp, "review"))
        self.zip_path = os.path.join(self.tmp, "review.zip")
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    zf.write(full, os.path.relpath(full, self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_from_zip(self):
        data = review_lib.load_review(self.zip_path)
        self.assertEqual(data.total, 12)
        self.assertTrue(os.path.isdir(data.root))
        # audio files were extracted and are readable
        fn = sorted(os.listdir(os.path.join(data.root, "Hudhaify", "above")))[0]
        with open(os.path.join(data.root, "Hudhaify", "above", fn), "rb") as fh:
            self.assertTrue(fh.read(4))

    def test_app_from_zip(self):
        application = app_module.create_app(self.zip_path, os.path.join(self.tmp, "out"))
        client = application.test_client()
        self.assertEqual(client.get("/api/config").get_json()["total_clips"], 12)


@unittest.skipUnless(os.path.isdir(REPO_REVIEW), "repo review/ folder not present")
class TestRealReviewData(unittest.TestCase):
    def test_real_counts(self):
        data = review_lib.load_review(REPO_REVIEW)
        self.assertEqual(data.total, 45)
        names = [r["name"] for r in data.reciters]
        self.assertIn("Abdul_Basit_Murattal", names)
        self.assertIn("Hudhaify", names)
        self.assertIn("Husary", names)
        for rec in data.reciters:
            for group in GROUPS:
                self.assertEqual(len(rec["groups"][group]), 5,
                                 f"{rec['name']}/{group} should have 5 clips")
        # every clip has metrics + a fail_reason list
        any_clip = data.reciters[0]["groups"]["random_rejects"][0]
        self.assertTrue(any_clip.metrics)
        self.assertIsInstance(any_clip.fail_reason, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
