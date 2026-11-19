"""Score or publish a leaderboard submission made through the GitHub issue form.

Run by the Actions workflows. The issue is read from environment variables
(never interpolated into a shell command), and the reply is written as markdown
to the --comment path for the workflow to post.

    python -m tools.submission score   --comment comment.md
    python -m tools.submission publish --comment comment.md

Environment: ISSUE_NUMBER, ISSUE_BODY, ISSUE_AUTHOR, ISSUE_CREATED_AT, ISSUE_URL.
Optional: BOT_COMMENTS_FILE (JSON list of {id, body, updated_at} bot comments),
GITHUB_OUTPUT.

`score` always exits 0 once a comment is written (errors are reported in the
comment). `publish` exits 0 when published or already published, 10 when
refused, and 1 on unexpected failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from scorer.score import CATEGORIES, SubmissionError, load_reference, score_bytes
from tools.build_leaderboard import OUTPUT, SUBMISSIONS, build
from tools.fetch import download, find_url

FIELDS = {
    "Model name": "model",
    "Team or organization": "team",
    "Training": "training",
    "Open weights": "open_weights",
    "Model or code link": "model_url",
    "Paper or report link": "paper_url",
    "Predictions CSV": "predictions",
    "Notes": "notes",
    "Rules": "rules",
}
REQUIRED = {"model": "Model name", "team": "Team or organization", "predictions": "Predictions CSV"}
HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
MARKER_RE = re.compile(
    r"^<!-- yigzinbench:score v=1 verdict=(ok|error) sha256=([0-9a-f]{64}|-) scored_at=(\S+) -->$"
)
D1_REFUSAL = (
    "The file at the link changed after it was scored, and the issue was not edited, "
    "so nothing scored the new file. Ask the submitter to link a pinned revision "
    "(a Hugging Face commit or a gist revision) and edit the issue; the bot will score it again."
)
FIX_STEPS = (
    "To fix it:\n"
    "1. Edit the first post of this issue.\n"
    "2. Replace the predictions file or link.\n"
    "3. Save. The bot will score it again and update this reply."
)
def parse_issue_form(body: str) -> dict[str, str]:
    """Split a rendered issue form ("### Label" + value blocks) into fields."""
    fields: dict[str, str] = {}
    key, lines = None, []

    def flush() -> None:
        if key:
            value = "\n".join(lines).strip()
            fields[key] = "" if value == "_No response_" else value

    for line in (body or "").splitlines():
        m = HEADING_RE.match(line)
        if m and m.group(1) in FIELDS:
            flush()
            key, lines = FIELDS[m.group(1)], []
        else:
            lines.append(line)
    flush()
    return fields


def clean_text(value: str, limit: int) -> str:
    return CONTROL_RE.sub(" ", " ".join((value or "").split()))[:limit].strip()


def clean_url(value: str) -> str:
    value = (value or "").strip()
    return value if re.fullmatch(r"https?://[^\s<>\"'`]{1,500}", value) else ""


def md(value: str) -> str:
    """Escape user text for a markdown table cell and stop it from @-mentioning anyone."""
    value = re.sub(r"([\\`*_{}\[\]<>|#])", r"\\\1", value)
    return value.replace("@", "&#64;")


def file_hash(raw: bytes) -> str:
    """Return the SHA-256 hex digest of raw CSV bytes."""
    return hashlib.sha256(raw).hexdigest()


def render_marker(verdict: str, sha256: str, scored_at: str) -> str:
    """Build the HTML comment that carries the score verdict and hash."""
    digest = sha256 if verdict == "ok" else "-"
    return f"<!-- yigzinbench:score v=1 verdict={verdict} sha256={digest} scored_at={scored_at} -->"


def latest_marker(comments: list[dict]) -> dict | None:
    """Return the latest bot score marker from first lines of bot comments."""
    best: dict | None = None
    for comment in comments:
        body = comment.get("body") or ""
        first = body.splitlines()[0] if body else ""
        m = MARKER_RE.match(first)
        if not m:
            continue
        updated = comment.get("updated_at") or ""
        if best is None or updated > best["updated_at"]:
            best = {
                "verdict": m.group(1),
                "sha256": m.group(2),
                "scored_at": m.group(3),
                "comment_id": comment.get("id"),
                "updated_at": updated,
            }
    return best


def load_bot_comments(env: dict[str, str]) -> list[dict]:
    path = env.get("BOT_COMMENTS_FILE", "")
    if not path:
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_github_output(**fields: object) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in fields.items():
            fh.write(f"{key}={'' if value is None else value}\n")


def collect(env: dict[str, str]) -> tuple[dict, str]:
    """Validate the form and return (metadata, predictions URL). Raises SubmissionError."""
    fields = parse_issue_form(env.get("ISSUE_BODY", ""))
    missing = [label for key, label in REQUIRED.items() if not fields.get(key)]
    if missing:
        raise SubmissionError("Required field(s) are empty: " + ", ".join(f"*{m}*" for m in missing) + ".")
    if "[x]" not in fields.get("rules", "").lower():
        raise SubmissionError("Please tick the checkbox under *Rules*.")
    url = find_url(fields["predictions"])
    meta = {
        "model": clean_text(fields["model"], 80),
        "team": clean_text(fields["team"], 80),
        "training": "fine-tuned" if fields.get("training", "").startswith("Fine-tuned") else "off-the-shelf",
        "open_weights": {"yes": True, "no": False}.get(fields.get("open_weights", "").strip().lower()),
        "model_url": clean_url(fields.get("model_url", "")),
        "paper_url": clean_url(fields.get("paper_url", "")),
        "notes": (fields.get("notes") or "")[:2000],
        "source": "community",
        "submitted_by": env.get("ISSUE_AUTHOR", ""),
        "submitted_at": env.get("ISSUE_CREATED_AT", ""),
        "issue_url": env.get("ISSUE_URL", ""),
        "predictions_url": url,
    }
    return meta, url


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def would_rank(mean_cer: float, submitted_at: str = "") -> tuple[int, int]:
    """Return (k, N) as on the board: ties broken by earlier submitted_at.

    Rank is computed against the current board before this entry is published,
    so N is len(entries) + 1.
    """
    entries: list[dict] = []
    if OUTPUT.exists():
        try:
            board = json.loads(OUTPUT.read_text(encoding="utf-8"))
            entries = list(board.get("entries") or [])
        except (json.JSONDecodeError, OSError):
            entries = []
    stamp = submitted_at or "~"
    ahead = sum(
        1
        for e in entries
        if (e["mean_cer"], e.get("submitted_at") or "~") < (mean_cer, stamp)
    )
    return ahead + 1, len(entries) + 1


def exact_zero_pages(result: dict) -> int:
    """Count pages with CER exactly 0 whose reference text is not empty."""
    gt, _, _ = load_reference()
    per_page = result.get("per_page") or {}
    return sum(1 for pid, ref in gt.items() if ref and per_page.get(pid) == 0.0)


def score_entry(env: dict[str, str]) -> tuple[dict, bytes, dict]:
    """Collect metadata, download predictions and score. Raises SubmissionError."""
    meta, url = collect(env)
    raw = download(url)
    result = score_bytes(raw)
    return meta, raw, result


def _drop_removed_record(entry_id: str) -> None:
    path = SUBMISSIONS / "_removed.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    removed = [r for r in data.get("removed", []) if r.get("id") != entry_id]
    if len(removed) == len(data.get("removed", [])):
        return
    data["removed"] = sorted(removed, key=lambda r: r["id"])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def store_entry(number: int, meta: dict, raw: bytes, result: dict) -> str:
    """Write submissions/issue-<n>/, rebuild the board, return the entry id."""
    entry_id = f"issue-{number}"
    out = SUBMISSIONS / entry_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.csv").write_bytes(raw)
    stored = dict(meta)
    stored["predictions_url"] = ""  # the copy in the repo is now the source of truth
    (out / "meta.json").write_text(json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _drop_removed_record(entry_id)
    build()
    return entry_id


def render_result(
    meta: dict,
    result: dict,
    *,
    published: bool = False,
    entry_id: str | None = None,
    sha256: str | None = None,
    scored_at: str | None = None,
) -> str:
    """Render the success reply, including rank and exact-match rows."""
    rank_k, rank_n = would_rank(result["mean_cer"], meta.get("submitted_at", ""))
    exact = exact_zero_pages(result)
    if published:
        header = f"### ✅ Published as `{entry_id}`" if entry_id else "### ✅ Published to the leaderboard"
    else:
        header = "### ✅ Ready for review"
    lines = [
        header,
        "",
        f"**{md(meta['model'])}** · {md(meta['team'])}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| **Mean CER** (ranking metric) | **{pct(result['mean_cer'])}** |",
        f"| Median CER | {pct(result['median_cer'])} |",
        f"| Pages with CER > 50% | {result['catastrophic_pct']:.2f}% |",
        f"| Pages covered | {result['coverage']} / {result['n']} |",
        f"| Would rank | #{rank_k} of {rank_n} |",
        f"| Pages with CER exactly 0 | {exact} |",
        "",
    ]
    for warning in result.get("warnings", []):
        lines.append(f"> ⚠️ {warning}")
    if result.get("warnings"):
        lines.append("")
    lines += ["<details><summary>Breakdown by page category</summary>", ""]
    for cat, label in CATEGORIES.items():
        lines += [f"**{label}**", "", "| | Pages | Mean CER |", "|---|---:|---:|"]
        for name, cell in result["breakdown"][cat].items():
            lines.append(f"| {md(name)} | {cell['n']} | {pct(cell['mean_cer'])} |")
        lines.append("")
    lines += ["</details>", ""]
    if sha256:
        lines.append(f"File SHA-256 (first 12): `{sha256[:12]}`")
    if scored_at:
        lines.append(f"Scored at: `{scored_at}`")
    if sha256 or scored_at:
        lines.append("")
    if not published:
        lines.append(
            "A maintainer will review this and publish it by closing the issue as completed. "
            "To fix something, edit the issue and it will be scored again."
        )
    lines.append(
        f"<sub>dataset `{result['dataset']}` @ `{result['dataset_revision'][:12]}` · "
        f"scorer v{result['scorer_version']}</sub>"
    )
    return "\n".join(lines) + "\n"


def render_error(message: str) -> str:
    """Render a scored-as-error reply with numbered fix steps."""
    return (
        "### ❌ Could not be scored\n\n"
        f"{md(message)}\n\n"
        f"{FIX_STEPS}\n"
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_score(comment_path: Path, env: dict[str, str]) -> int:
    """Score the issue and write a marked reply. Always exits 0 after writing."""
    marker = latest_marker(load_bot_comments(env))
    comment_id = marker["comment_id"] if marker else ""
    scored_at = _now()
    try:
        meta, raw, result = score_entry(env)
        digest = file_hash(raw)
        body = (
            render_marker("ok", digest, scored_at)
            + "\n"
            + render_result(meta, result, sha256=digest, scored_at=scored_at)
        )
        append_github_output(verdict="ok", sha256=digest, comment_id=comment_id)
    except SubmissionError as exc:
        body = render_marker("error", "-", scored_at) + "\n" + render_error(str(exc))
        append_github_output(verdict="error", sha256="-", comment_id=comment_id)
    comment_path.write_text(body, encoding="utf-8")
    return 0


def cmd_publish(comment_path: Path, env: dict[str, str]) -> int:
    """Publish a scored submission. Exit 0, 10 (refused) or 1 (error)."""
    number = int(env["ISSUE_NUMBER"])
    entry_id = f"issue-{number}"
    folder = SUBMISSIONS / entry_id

    if folder.is_dir() and (folder / "result.json").exists():
        comment_path.write_text(f"Already published as `{entry_id}`.\n", encoding="utf-8")
        return 0

    marker = latest_marker(load_bot_comments(env))
    if marker is None:
        comment_path.write_text(
            "Not scored yet. Wait for the bot's reply, then close the issue again.\n",
            encoding="utf-8",
        )
        return 10
    if marker["verdict"] != "ok":
        comment_path.write_text(
            "The file could not be scored; see the bot's reply.\n",
            encoding="utf-8",
        )
        return 10

    try:
        meta, raw, result = score_entry(env)
    except SubmissionError as exc:
        comment_path.write_text(render_error(str(exc)), encoding="utf-8")
        return 1

    digest = file_hash(raw)
    if digest != marker["sha256"]:
        comment_path.write_text(D1_REFUSAL + "\n", encoding="utf-8")
        return 10

    store_entry(number, meta, raw, result)
    comment_path.write_text(
        render_result(
            meta,
            result,
            published=True,
            entry_id=entry_id,
            sha256=digest,
            scored_at=marker["scored_at"],
        ),
        encoding="utf-8",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["score", "publish"])
    ap.add_argument("--comment", type=Path, required=True, help="where to write the markdown reply")
    args = ap.parse_args(argv)
    env = dict(os.environ)
    if args.command == "score":
        return cmd_score(args.comment, env)
    try:
        return cmd_publish(args.comment, env)
    except Exception as exc:  # unexpected failures become exit 1 for the workflow
        args.comment.write_text(f"Publishing failed: {exc}\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())
