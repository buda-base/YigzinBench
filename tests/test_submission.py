"""Unit tests for score markers, link rewrites, score and publish."""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scorer.score import SubmissionError, load_reference, score_bytes
from tools.fetch import find_url, rewrite_url
from tools.submission import (
    D1_REFUSAL,
    FIX_STEPS,
    cmd_publish,
    cmd_score,
    exact_zero_pages,
    file_hash,
    latest_marker,
    render_error,
    render_marker,
    render_result,
    would_rank,
)
from tests.helpers import temp_repo, write_bot_comments

PRED_URL = "https://github.com/user-attachments/files/12345/preds.csv"


def to_csv(rows, header=("id", "transcription")) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def gt_rows():
    with open("scorer/data/ground_truth.csv", encoding="utf-8", newline="") as fh:
        return [(r["id"], r["transcription"]) for r in csv.DictReader(fh)]


def issue_body(predictions: str = f"[preds.csv]({PRED_URL})") -> str:
    return f"""### Model name

test-model

### Team or organization

Test Lab

### Training

Fine-tuned or trained for Tibetan

### Open weights

Yes

### Model or code link

https://example.com/model

### Paper or report link

_No response_

### Predictions CSV

{predictions}

### Notes

_No response_

### Rules

- [X] These predictions were produced by the model named above, without using the benchmark's ground-truth transcriptions.
"""


def env_for(body: str, number: int = 99, comments_file: str = "") -> dict[str, str]:
    out = {
        "ISSUE_NUMBER": str(number),
        "ISSUE_BODY": body,
        "ISSUE_AUTHOR": "alice",
        "ISSUE_CREATED_AT": "2026-01-01T00:00:00Z",
        "ISSUE_URL": f"https://github.com/example/YigzinBench/issues/{number}",
    }
    if comments_file:
        out["BOT_COMMENTS_FILE"] = comments_file
    return out


class LinkRewriteTest(unittest.TestCase):
    def test_blob_and_download_true(self):
        blob = "https://huggingface.co/org/model/blob/main/preds.csv"
        rewritten = rewrite_url(blob)
        self.assertEqual(rewritten, "https://huggingface.co/org/model/resolve/main/preds.csv")
        self.assertEqual(find_url(f"see {blob}"), rewritten)

        with_qs = "https://huggingface.co/org/model/resolve/main/preds.csv?download=true"
        self.assertEqual(
            find_url(with_qs),
            "https://huggingface.co/org/model/resolve/main/preds.csv",
        )


class MarkerTest(unittest.TestCase):
    def test_round_trip_and_latest(self):
        line = render_marker("ok", "a" * 64, "2026-01-01T00:00:00Z")
        comments = [
            {"id": 1, "body": line + "\nold\n", "updated_at": "2026-01-01T00:00:00Z"},
            {
                "id": 2,
                "body": render_marker("error", "-", "2026-01-02T00:00:00Z") + "\nerr\n",
                "updated_at": "2026-01-02T00:00:00Z",
            },
            {"id": 3, "body": "not a marker\n" + line, "updated_at": "2026-01-03T00:00:00Z"},
        ]
        marker = latest_marker(comments)
        self.assertEqual(marker["comment_id"], 2)
        self.assertEqual(marker["verdict"], "error")

    def test_marker_in_error_body_not_trusted(self):
        planted = render_marker("ok", "b" * 64, "2026-01-01T00:00:00Z")
        reply = render_error(f"bad header: {planted}")
        # render_error alone has no first-line marker, so a planted marker in the
        # message body must not be read as verdict=ok.
        self.assertIsNone(latest_marker([{"id": 1, "body": reply, "updated_at": "t"}]))
        scored = render_marker("error", "-", "t") + "\n" + reply
        marker = latest_marker([{"id": 1, "body": scored, "updated_at": "t"}])
        self.assertEqual(marker["verdict"], "error")


class ScorePublishTest(unittest.TestCase):
    def test_score_writes_marker_and_outputs(self):
        raw = to_csv(gt_rows())
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            out = Path(td)
            comment = out / "comment.md"
            gh_out = out / "github_output"
            comments = write_bot_comments(
                out / "bots.json",
                [{
                    "id": 42,
                    "body": render_marker("error", "-", "2025-01-01T00:00:00Z") + "\nold\n",
                    "updated_at": "2025-01-01T00:00:00Z",
                }],
            )
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh_out)}):
                code = cmd_score(comment, env_for(issue_body(), comments_file=str(comments)))
            self.assertEqual(code, 0)
            text = comment.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<!-- yigzinbench:score v=1 verdict=ok"))
            self.assertIn("Ready for review", text)
            self.assertIn(FIX_STEPS.split("\n")[0], render_error("x"))
            outputs = dict(line.split("=", 1) for line in gh_out.read_text().splitlines() if "=" in line)
            self.assertEqual(outputs["verdict"], "ok")
            self.assertEqual(outputs["sha256"], file_hash(raw))
            self.assertEqual(outputs["comment_id"], "42")

    def test_score_download_failure(self):
        from tools.fetch import _download_error
        import urllib.error

        msg = str(_download_error(urllib.error.HTTPError("u", 403, "no", hdrs=None, fp=None)))
        self.assertIn("gated or private", msg)

        with temp_repo() as ctx, tempfile.TemporaryDirectory() as td:
            comment = Path(td) / "comment.md"

            def boom(url: str) -> bytes:
                raise SubmissionError(
                    "Could not download the predictions file (connection failed or timed out). "
                    "This is probably temporary and your file does not need changing; "
                    "a maintainer can re-run the job, or you can edit the issue to try again."
                )

            with mock.patch("tools.submission.download", side_effect=boom):
                code = cmd_score(comment, env_for(issue_body()))
            self.assertEqual(code, 0)
            text = comment.read_text(encoding="utf-8")
            self.assertIn("verdict=error", text.splitlines()[0])
            self.assertIn("temporary", text)
            self.assertIn("1. Edit the first post", text)

    def test_publish_outcomes(self):
        raw = to_csv(gt_rows())
        digest = file_hash(raw)
        marker_line = render_marker("ok", digest, "2026-01-01T00:00:00Z")

        # Already published
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            comment = Path(td) / "c.md"
            # issue-3 already exists in the copied tree
            code = cmd_publish(comment, env_for(issue_body(), number=3))
            self.assertEqual(code, 0)
            self.assertIn("Already published as `issue-3`", comment.read_text())

        # No marker
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            comment = Path(td) / "c.md"
            comments = write_bot_comments(Path(td) / "bots.json", [])
            code = cmd_publish(comment, env_for(issue_body(), number=99, comments_file=str(comments)))
            self.assertEqual(code, 10)
            self.assertIn("Not scored yet", comment.read_text())
            self.assertFalse((ctx["submissions"] / "issue-99").exists())

        # Verdict error
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            comment = Path(td) / "c.md"
            comments = write_bot_comments(
                Path(td) / "bots.json",
                [{"id": 1, "body": render_marker("error", "-", "t") + "\nx\n", "updated_at": "t"}],
            )
            code = cmd_publish(comment, env_for(issue_body(), number=99, comments_file=str(comments)))
            self.assertEqual(code, 10)
            self.assertIn("could not be scored", comment.read_text())

        # Hash mismatch
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            comment = Path(td) / "c.md"
            comments = write_bot_comments(
                Path(td) / "bots.json",
                [{"id": 1, "body": render_marker("ok", "c" * 64, "t") + "\nok\n", "updated_at": "t"}],
            )
            code = cmd_publish(comment, env_for(issue_body(), number=99, comments_file=str(comments)))
            self.assertEqual(code, 10)
            self.assertIn(D1_REFUSAL.split(".")[0], comment.read_text())
            self.assertFalse((ctx["submissions"] / "issue-99").exists())

        # Published
        with temp_repo({PRED_URL: raw}) as ctx, tempfile.TemporaryDirectory() as td:
            comment = Path(td) / "c.md"
            comments = write_bot_comments(
                Path(td) / "bots.json",
                [{"id": 1, "body": marker_line + "\nok\n", "updated_at": "t"}],
            )
            code = cmd_publish(comment, env_for(issue_body(), number=99, comments_file=str(comments)))
            self.assertEqual(code, 0)
            self.assertTrue((ctx["submissions"] / "issue-99" / "predictions.csv").exists())
            self.assertIn("Published as `issue-99`", comment.read_text())


class RankExactTest(unittest.TestCase):
    def test_rank_empty_board_and_ties(self):
        with temp_repo() as ctx:
            # No leaderboard.json yet
            self.assertEqual(would_rank(0.5), (1, 1))
            board = {
                "entries": [
                    {"mean_cer": 0.1, "submitted_at": "2026-01-01T00:00:00Z"},
                    {"mean_cer": 0.2, "submitted_at": "2026-01-02T00:00:00Z"},
                ]
            }
            ctx["output"].parent.mkdir(parents=True, exist_ok=True)
            ctx["output"].write_text(json.dumps(board), encoding="utf-8")
            self.assertEqual(would_rank(0.15, "2026-01-03T00:00:00Z"), (2, 3))
            # Same CER, later stamp ranks after the earlier one
            self.assertEqual(would_rank(0.1, "2026-01-02T00:00:00Z"), (2, 3))
            self.assertEqual(would_rank(0.1, "2025-01-01T00:00:00Z"), (1, 3))

    def test_exact_zero_ignores_empty_ref_and_missing(self):
        rows = gt_rows()
        gt, _, _ = load_reference()
        nonempty = {pid for pid, ref in gt.items() if ref}
        # Perfect on first page only; rest missing -> CER 1.0, not exact zero
        raw = to_csv(rows[:1])
        result = score_bytes(raw)
        exact = exact_zero_pages(result)
        first_id = rows[0][0]
        self.assertEqual(exact, 1 if first_id in nonempty else 0)
        self.assertLess(exact, len(nonempty))

        perfect = score_bytes(to_csv(rows))
        # Only nonempty references with CER exactly 0 are counted.
        self.assertEqual(
            exact_zero_pages(perfect),
            sum(1 for pid in nonempty if perfect["per_page"].get(pid) == 0.0),
        )
        self.assertGreater(exact_zero_pages(perfect), 0)
        # A page with empty reference text is never counted, even if CER is 0.
        empty_ids = [pid for pid, ref in gt.items() if not ref]
        if empty_ids:
            self.assertEqual(
                exact_zero_pages({**perfect, "per_page": {**perfect["per_page"], empty_ids[0]: 0.0}}),
                exact_zero_pages(perfect),
            )

    def test_render_includes_rank_rows(self):
        rows = gt_rows()
        result = score_bytes(to_csv(rows))
        with temp_repo():
            text = render_result(
                {"model": "m", "team": "t", "submitted_at": "2026-01-01T00:00:00Z"},
                result,
                sha256="a" * 64,
                scored_at="2026-01-01T00:00:00Z",
            )
            self.assertIn("Would rank", text)
            self.assertIn("Pages with CER exactly 0", text)


if __name__ == "__main__":
    unittest.main()
