"""Rebuild leaderboard/leaderboard.json from submissions/*/{meta,result}.json.

    python -m tools.build_leaderboard             # rebuild from stored results
    python -m tools.build_leaderboard --rescore   # re-score every submission first

Re-score after updating scorer/data to a new dataset revision or changing the
scorer; entries scored against an older revision or scorer are marked `stale`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scorer.score import CATEGORIES, SCORER_VERSION, UNKNOWN, load_reference, score_bytes

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ROOT / "submissions"
OUTPUT = ROOT / "leaderboard" / "leaderboard.json"

META_KEYS = [
    "model", "team", "training", "open_weights", "model_url", "paper_url", "notes",
    "source", "submitted_by", "submitted_at", "issue_url", "predictions_url",
]
# Ordinal categories read best-first ("4 - Excellent" before "0 - Illegible").
DESCENDING_BY_NAME = {"legibility", "rarity"}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rescore(folder: Path) -> None:
    from tools.fetch import download

    meta = read_json(folder / "meta.json")
    local = folder / "predictions.csv"
    raw = local.read_bytes() if local.exists() else download(meta["predictions_url"])
    result = score_bytes(raw)
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def category_values() -> dict:
    _, pages, _ = load_reference()
    out = {}
    for cat, label in CATEGORIES.items():
        counts: dict[str, int] = {}
        for page in pages.values():
            name = page.get(cat) or UNKNOWN
            counts[name] = counts.get(name, 0) + 1
        if cat in DESCENDING_BY_NAME:
            order = sorted(counts, reverse=True)
        else:
            order = sorted(counts, key=lambda n: -counts[n])
        order = [n for n in order if n != UNKNOWN] + ([UNKNOWN] if UNKNOWN in counts else [])
        out[cat] = {"label": label, "values": [{"name": n, "n": counts[n]} for n in order]}
    return out


def build() -> dict:
    _, _, source = load_reference()
    entries = []
    for folder in sorted(p for p in SUBMISSIONS.glob("*") if p.is_dir()):
        if not (folder / "result.json").exists():
            continue
        meta, result = read_json(folder / "meta.json"), read_json(folder / "result.json")
        entries.append({
            "id": folder.name,
            **{k: meta.get(k, "") for k in META_KEYS},
            "mean_cer": result["mean_cer"],
            "median_cer": result["median_cer"],
            "catastrophic_pct": result["catastrophic_pct"],
            "coverage": result["coverage"],
            "n": result["n"],
            "breakdown": {cat: {k: v["mean_cer"] for k, v in cells.items()} for cat, cells in result["breakdown"].items()},
            "stale": result["dataset_revision"] != source["revision"] or result["scorer_version"] != SCORER_VERSION,
        })
    entries.sort(key=lambda e: (e["mean_cer"], e["submitted_at"] or "~"))

    board = {
        "dataset": source["dataset"],
        "dataset_revision": source["revision"],
        "scorer_version": SCORER_VERSION,
        "categories": category_values(),
        "entries": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(board, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return board


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rescore", action="store_true", help="re-score every submission before building")
    args = ap.parse_args(argv)
    if args.rescore:
        for folder in sorted(p for p in SUBMISSIONS.glob("*") if p.is_dir()):
            print(f"re-scoring {folder.name}", file=sys.stderr)
            rescore(folder)
    board = build()
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(board['entries'])} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
