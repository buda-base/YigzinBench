"""Maintainer helpers for published leaderboard entries.

    python -m tools.manage delete <id> --reason <text> [--issue <n>]

Exit 0 if deleted, 10 if refused, 1 on any other error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

from tools.build_leaderboard import SUBMISSIONS, build, removed_ids

ID_RE = re.compile(r"^(issue-\d+|bdrc-[\w.-]+)$")


class ManageError(Exception):
    """A refused delete; message is safe for the run summary."""


def delete_entry(entry_id: str, reason: str, issue: int | None = None) -> str:
    """Remove a submission folder, record it in _removed.json, rebuild the board.

    Returns the model name from meta.json.
    """
    if not ID_RE.fullmatch(entry_id):
        raise ManageError(
            f"Invalid id `{entry_id}`; expected `issue-<n>` or `bdrc-<run_id>`."
        )
    reason = (reason or "").strip()
    if not reason:
        raise ManageError("A non-empty reason is required.")
    if len(reason) > 500:
        raise ManageError("Reason must be at most 500 characters.")

    folder = SUBMISSIONS / entry_id
    if not folder.is_dir():
        raise ManageError(f"No folder `submissions/{entry_id}/` to delete.")
    if entry_id in removed_ids():
        raise ManageError(f"`{entry_id}` is already recorded as removed.")

    meta_path = folder / "meta.json"
    model = ""
    if meta_path.exists():
        model = json.loads(meta_path.read_text(encoding="utf-8")).get("model", "") or ""

    if issue is None:
        m = re.fullmatch(r"issue-(\d+)", entry_id)
        issue = int(m.group(1)) if m else None

    shutil.rmtree(folder)

    path = SUBMISSIONS / "_removed.json"
    data = {"removed": []}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("removed", [])
    data["removed"].append({"id": entry_id, "reason": reason, "issue": issue})
    data["removed"] = sorted(data["removed"], key=lambda r: r["id"])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build()
    return model


def _append_output(**fields: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in fields.items():
            fh.write(f"{key}={'' if value is None else value}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    delete = sub.add_parser("delete", help="remove a published entry")
    delete.add_argument("id", help="entry id (issue-<n> or bdrc-<run_id>)")
    delete.add_argument("--reason", required=True, help="why the entry is being removed")
    delete.add_argument("--issue", type=int, default=None, help="related issue number")
    args = ap.parse_args(argv)

    if args.command == "delete":
        try:
            model = delete_entry(args.id, args.reason, issue=args.issue)
        except ManageError as exc:
            print(str(exc), file=sys.stderr)
            _append_output(result="refused", message=str(exc), model="")
            return 10
        except Exception as exc:  # unexpected
            print(f"delete failed: {exc}", file=sys.stderr)
            _append_output(result="error", message=str(exc), model="")
            return 1
        _append_output(model=model)
        print(f"deleted {args.id} ({model})", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
