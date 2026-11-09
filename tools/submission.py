"""Score or publish a leaderboard submission made through the GitHub issue form.

Run by the Actions workflows. The issue is read from environment variables
(never interpolated into a shell command), and the reply is written as markdown
to the --comment path for the workflow to post.

    python -m tools.submission score   --comment comment.md
    python -m tools.submission publish --comment comment.md

Environment: ISSUE_NUMBER, ISSUE_BODY, ISSUE_AUTHOR, ISSUE_CREATED_AT, ISSUE_URL.

`score` always exits 0 once a comment is written (errors are reported in the
comment). `publish` exits 1 when the submission can't be published, so the
workflow stops before committing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from scorer.score import CATEGORIES, SubmissionError, score_bytes
from tools.build_leaderboard import SUBMISSIONS, build
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


def parse_issue_form(body: str) -> dict[str, str]:
    """Split a rendered issue form ("### Label" + value blocks) into fields."""
    fields: dict[str, str] = {}
    key, lines = None, []

    def flush():
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


def render_result(meta: dict, result: dict, published: bool) -> str:
    lines = [
        "### ✅ Published to the leaderboard" if published else "### 📊 Scoring result",
        "",
        f"**{md(meta['model'])}** · {md(meta['team'])}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| **Mean CER** (ranking metric) | **{pct(result['mean_cer'])}** |",
        f"| Median CER | {pct(result['median_cer'])} |",
        f"| Pages with CER > 50% | {result['catastrophic_pct']:.2f}% |",
        f"| Pages covered | {result['coverage']} / {result['n']} |",
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
    if not published:
        lines.append(
            "A maintainer will review this and add it to the leaderboard. "
            "To fix something, edit the issue and it will be scored again."
        )
    lines.append(
        f"<sub>dataset `{result['dataset']}` @ `{result['dataset_revision'][:12]}` · "
        f"scorer v{result['scorer_version']}</sub>"
    )
    return "\n".join(lines) + "\n"


def render_error(message: str) -> str:
    return (
        "### ❌ This submission could not be scored\n\n"
        f"{message}\n\n"
        "Edit the issue to fix it; it will be scored again automatically.\n"
    )


def run(command: str, comment_path: Path, env: dict[str, str]) -> int:
    try:
        meta, url = collect(env)
        raw = download(url)
        result = score_bytes(raw)
    except SubmissionError as exc:
        comment_path.write_text(render_error(str(exc)), encoding="utf-8")
        return 0 if command == "score" else 1

    if command == "publish":
        number = int(env["ISSUE_NUMBER"])
        out = SUBMISSIONS / f"issue-{number}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "predictions.csv").write_bytes(raw)
        meta["predictions_url"] = ""  # the copy in the repo is now the source of truth
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        build()

    comment_path.write_text(render_result(meta, result, published=command == "publish"), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["score", "publish"])
    ap.add_argument("--comment", type=Path, required=True, help="where to write the markdown reply")
    args = ap.parse_args(argv)
    return run(args.command, args.comment, dict(os.environ))


if __name__ == "__main__":
    sys.exit(main())
