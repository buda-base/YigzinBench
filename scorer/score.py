"""Validate a predictions CSV and score it against the benchmark ground truth.

Usage:
    python -m scorer.score predictions.csv              # print a summary
    python -m scorer.score predictions.csv --json out.json

The CSV must be UTF-8 with an `id,transcription` header and one row per page.
Pages left out count as CER 1.0, exactly as on BDRC's own leaderboard.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import sys
from functools import lru_cache
from pathlib import Path

from .cer import CATASTROPHIC_THRESHOLD, cer, prepare

SCORER_VERSION = "1.0.0"
DATA_DIR = Path(__file__).resolve().parent / "data"
MAX_BYTES = 20 * 1024 * 1024

# Page metadata columns shown as breakdowns on the leaderboard, in display order.
CATEGORIES = {
    "technology": "Technology",
    "script": "Script",
    "script_4": "Script style",
    "legibility": "Legibility",
    "rarity": "Rarity",
    "period": "Period",
}
UNKNOWN = "Unknown"

csv.field_size_limit(sys.maxsize)


class SubmissionError(Exception):
    """The predictions file can't be scored; the message is shown to the submitter."""


@lru_cache(maxsize=1)
def load_reference() -> tuple[dict[str, str], dict[str, dict[str, str]], dict]:
    """Return (prepared ground truth by id, page metadata by id, dataset source info)."""
    with (DATA_DIR / "ground_truth.csv").open(encoding="utf-8", newline="") as fh:
        gt = {row["id"].strip(): prepare(row["transcription"]) for row in csv.DictReader(fh)}
    with (DATA_DIR / "pages.csv").open(encoding="utf-8", newline="") as fh:
        pages = {row["id"].strip(): row for row in csv.DictReader(fh)}
    source = json.loads((DATA_DIR / "SOURCE.json").read_text(encoding="utf-8"))
    return gt, pages, source


def _preview(items: list[str], limit: int = 10) -> str:
    shown = ", ".join(f"`{i}`" for i in items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def parse_predictions(raw: bytes) -> tuple[dict[str, str], list[str]]:
    """Parse and validate a predictions CSV. Returns (predictions by id, warnings)."""
    gt, _, _ = load_reference()
    if len(raw) > MAX_BYTES:
        raise SubmissionError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubmissionError(f"The file is not valid UTF-8 (byte {exc.start}). Save it as UTF-8 CSV.") from None

    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = {(name or "").strip().lower(): name for name in (reader.fieldnames or [])}
    if "id" not in header or "transcription" not in header:
        found = ", ".join(f"`{n}`" for n in (reader.fieldnames or [])) or "nothing"
        raise SubmissionError(f"The header must contain `id` and `transcription` columns; found {found}.")
    id_col, text_col = header["id"], header["transcription"]

    preds: dict[str, str] = {}
    duplicates: list[str] = []
    unknown: list[str] = []
    padded = 0
    try:
        for row in reader:
            page_id = (row.get(id_col) or "").strip()
            if not page_id:
                continue
            # Spreadsheet apps turn "0002" into "2"; repair that rather than fail.
            if page_id not in gt and page_id.isdigit() and page_id.zfill(4) in gt:
                page_id = page_id.zfill(4)
                padded += 1
            if page_id not in gt:
                unknown.append(page_id)
            elif page_id in preds:
                duplicates.append(page_id)
            else:
                preds[page_id] = row.get(text_col) or ""
    except csv.Error as exc:
        raise SubmissionError(f"The CSV could not be parsed: {exc}.") from None

    if duplicates:
        raise SubmissionError(f"Some ids appear more than once: {_preview(sorted(set(duplicates)))}.")
    if unknown:
        raise SubmissionError(
            f"{len(unknown)} id(s) not in the benchmark: {_preview(unknown)}. "
            "Use the `id` column of the dataset unchanged."
        )
    if not preds:
        raise SubmissionError("The file has no prediction rows.")

    warnings = []
    if padded:
        warnings.append(f"{padded} ids had lost their leading zeros (e.g. `2` for `0002`) and were zero-padded.")
    missing = sorted(set(gt) - set(preds))
    if missing:
        warnings.append(f"{len(missing)} of {len(gt)} pages are missing and count as CER 1.0: {_preview(missing)}.")
    return preds, warnings


def score_predictions(preds: dict[str, str]) -> dict:
    """Score parsed predictions over every benchmark page."""
    gt, pages, source = load_reference()
    per_page = {pid: (round(cer(preds[pid], ref), 6) if pid in preds else 1.0) for pid, ref in gt.items()}
    values = list(per_page.values())

    breakdown: dict[str, dict[str, dict]] = {}
    for cat in CATEGORIES:
        groups: dict[str, list[float]] = {}
        for pid, value in per_page.items():
            groups.setdefault(pages[pid].get(cat) or UNKNOWN, []).append(value)
        breakdown[cat] = {
            name: {"n": len(vals), "mean_cer": round(statistics.mean(vals), 4)}
            for name, vals in sorted(groups.items())
        }

    return {
        "mean_cer": round(statistics.mean(values), 4),
        "median_cer": round(statistics.median(values), 4),
        "catastrophic_pct": round(100 * sum(v > CATASTROPHIC_THRESHOLD for v in values) / len(values), 2),
        "coverage": sum(pid in preds for pid in gt),
        "n": len(gt),
        "breakdown": breakdown,
        "per_page": per_page,
        "dataset": source["dataset"],
        "dataset_revision": source["revision"],
        "scorer_version": SCORER_VERSION,
    }


def score_bytes(raw: bytes) -> dict:
    """Parse, validate and score a predictions file. Raises SubmissionError."""
    preds, warnings = parse_predictions(raw)
    result = score_predictions(preds)
    result["warnings"] = warnings
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("predictions", type=Path, help="path to the id,transcription CSV")
    ap.add_argument("--json", type=Path, help="write the full result (incl. per-page CER) here")
    args = ap.parse_args(argv)

    try:
        result = score_bytes(args.predictions.read_bytes())
    except SubmissionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"mean CER      {result['mean_cer'] * 100:6.2f}%")
    print(f"median CER    {result['median_cer'] * 100:6.2f}%")
    print(f"pages > 50%   {result['catastrophic_pct']:6.2f}%")
    print(f"coverage      {result['coverage']}/{result['n']}")
    for cat, label in CATEGORIES.items():
        print(f"\n{label}")
        for name, cell in result["breakdown"][cat].items():
            print(f"  {name:<40}{cell['mean_cer'] * 100:6.2f}%  (n={cell['n']})")
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
