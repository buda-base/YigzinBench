"""Unit tests for delete and removed-id filtering."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.manage import ManageError, delete_entry, main as manage_main
from tools.submission import cmd_publish, file_hash, render_marker
from tests.helpers import temp_repo, write_bot_comments
from tests.test_submission import PRED_URL, env_for, gt_rows, issue_body, to_csv


class DeleteTest(unittest.TestCase):
    def test_refusals(self):
        with temp_repo() as ctx:
            with self.assertRaises(ManageError):
                delete_entry("bad id!", "reason")
            with self.assertRaises(ManageError):
                delete_entry("issue-99999", "reason")
            with self.assertRaises(ManageError):
                delete_entry("issue-3", "")
            with self.assertRaises(ManageError):
                delete_entry("issue-3", "x" * 501)

            delete_entry("issue-3", "duplicate")
            with self.assertRaises(ManageError):
                delete_entry("issue-3", "again")
            removed = json.loads((ctx["submissions"] / "_removed.json").read_text())
            self.assertEqual(removed["removed"][0]["id"], "issue-3")
            self.assertFalse((ctx["submissions"] / "issue-3").exists())

    def test_delete_cli_writes_model(self):
        with temp_repo() as ctx, tempfile.TemporaryDirectory() as td:
            gh_out = Path(td) / "out"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh_out)}):
                code = manage_main(["delete", "issue-3", "--reason", "cleanup"])
            self.assertEqual(code, 0)
            text = gh_out.read_text()
            self.assertIn("model=", text)
            self.assertFalse((ctx["submissions"] / "issue-3").exists())

            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh_out)}):
                code = manage_main(["delete", "issue-3", "--reason", "again"])
            self.assertEqual(code, 10)

    def test_publish_drops_removed_record(self):
        raw = to_csv(gt_rows())
        digest = file_hash(raw)
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            delete_entry("issue-3", "temporary")
            self.assertTrue(any(r["id"] == "issue-3" for r in json.loads(
                (ctx["submissions"] / "_removed.json").read_text()
            )["removed"]))

            comments = write_bot_comments(
                Path(td) / "bots.json",
                [{"id": 1, "body": render_marker("ok", digest, "t") + "\nok\n", "updated_at": "t"}],
            )
            comment = Path(td) / "c.md"
            code = cmd_publish(comment, env_for(issue_body(), number=3, comments_file=str(comments)))
            self.assertEqual(code, 0)
            removed = json.loads((ctx["submissions"] / "_removed.json").read_text())["removed"]
            self.assertFalse(any(r["id"] == "issue-3" for r in removed))
            self.assertTrue((ctx["submissions"] / "issue-3").exists())


class ImportRemovedTest(unittest.TestCase):
    def test_skips_removed_before_best_pick(self):
        # Two runs same (engine, model); remove the better one; next-best is imported.
        catalog = io.StringIO("run_id,run_type\n" "better,ots\n" "worse,ots\n")
        summary = io.StringIO(
            "run_id,engine,model,mean_cer\n"
            "better,Eng,Mod,0.10\n"
            "worse,Eng,Mod,0.20\n"
        )
        raw = to_csv(gt_rows())
        urls = {
            "https://huggingface.co/datasets/BDRC/tibetan-ocr-benchmark/resolve/rev/runs/catalog.csv":
                catalog.getvalue().encode(),
            "https://huggingface.co/datasets/BDRC/tibetan-ocr-benchmark/resolve/rev/runs/cer_summary.csv":
                summary.getvalue().encode(),
            "https://huggingface.co/datasets/BDRC/tibetan-ocr-benchmark/resolve/rev/runs/predictions/worse.csv":
                raw,
        }
        with temp_repo(urls) as ctx:
            (ctx["submissions"] / "_removed.json").write_text(
                json.dumps({"removed": [{"id": "bdrc-better", "reason": "x", "issue": None}]}, indent=2) + "\n",
                encoding="utf-8",
            )
            downloaded: list[str] = []

            def track(url: str) -> bytes:
                downloaded.append(url)
                if url not in urls:
                    raise AssertionError(url)
                return urls[url]

            with mock.patch("tools.import_bdrc_runs.download", side_effect=track), \
                    mock.patch("tools.import_bdrc_runs.load_reference", return_value=({}, {}, {
                        "dataset": "BDRC/tibetan-ocr-benchmark",
                        "revision": "rev",
                    })), \
                    mock.patch("tools.import_bdrc_runs.score_bytes", return_value={
                        "mean_cer": 0.2,
                        "median_cer": 0.2,
                        "catastrophic_pct": 0.0,
                        "coverage": 472,
                        "n": 472,
                        "breakdown": {},
                        "per_page": {},
                        "dataset": "BDRC/tibetan-ocr-benchmark",
                        "dataset_revision": "rev",
                        "scorer_version": "0",
                        "warnings": [],
                    }), \
                    mock.patch("tools.import_bdrc_runs.build", return_value={"entries": []}):
                from tools import import_bdrc_runs
                code = import_bdrc_runs.main()
            self.assertEqual(code, 0)
            self.assertTrue(any("predictions/worse.csv" in u for u in downloaded))
            self.assertFalse(any("predictions/better.csv" in u for u in downloaded))
            self.assertTrue((ctx["submissions"] / "bdrc-worse").exists())
            self.assertFalse((ctx["submissions"] / "bdrc-better").exists())


if __name__ == "__main__":
    unittest.main()
