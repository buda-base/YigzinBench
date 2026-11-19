"""Shared test helpers for tools/submission and tools/manage."""
from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REAL_SUBMISSIONS = ROOT / "submissions"


@contextmanager
def temp_repo(fixture_bytes: dict[str, bytes] | None = None):
    """Copy submissions/ into a temp dir and patch module paths + downloads.

    ``fixture_bytes`` maps a predictions URL (or any download URL) to raw bytes.
    Downloads for unknown URLs raise ``AssertionError`` so tests stay offline.
    """
    fixture_bytes = dict(fixture_bytes or {})

    def fake_download(url: str) -> bytes:
        if url not in fixture_bytes:
            raise AssertionError(f"unexpected download: {url}")
        return fixture_bytes[url]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        submissions = tmp_path / "submissions"
        shutil.copytree(REAL_SUBMISSIONS, submissions)
        output = tmp_path / "leaderboard" / "leaderboard.json"
        readme = tmp_path / "README.md"
        readme.write_text(
            "<!-- leaderboard:start -->\n<!-- leaderboard:end -->\n",
            encoding="utf-8",
        )

        with ExitStack() as stack:
            for target, value in (
                ("tools.build_leaderboard.SUBMISSIONS", submissions),
                ("tools.build_leaderboard.OUTPUT", output),
                ("tools.build_leaderboard.ROOT", tmp_path),
                ("tools.submission.SUBMISSIONS", submissions),
                ("tools.submission.OUTPUT", output),
                ("tools.manage.SUBMISSIONS", submissions),
                ("tools.import_bdrc_runs.SUBMISSIONS", submissions),
            ):
                stack.enter_context(mock.patch(target, value))
            stack.enter_context(mock.patch("tools.submission.download", side_effect=fake_download))
            stack.enter_context(mock.patch("tools.import_bdrc_runs.download", side_effect=fake_download))
            stack.enter_context(mock.patch("tools.fetch.download", side_effect=fake_download))
            yield {
                "root": tmp_path,
                "submissions": submissions,
                "output": output,
                "readme": readme,
                "fixture_bytes": fixture_bytes,
            }


def write_bot_comments(path: Path, comments: list[dict]) -> Path:
    """Write a BOT_COMMENTS_FILE JSON list and return the path."""
    path.write_text(json.dumps(comments), encoding="utf-8")
    return path
