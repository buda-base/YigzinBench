"""Seed the leaderboard with BDRC's public reference runs.

Downloads `runs/catalog.csv` and `runs/cer_summary.csv` from the dataset repo at
the revision in scorer/data/SOURCE.json, keeps the best run per (engine, model),
scores its predictions with our scorer, and checks the result matches BDRC's
published mean CER. Predictions are referenced by URL, not copied into this repo.

    python -m tools.import_bdrc_runs
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys

from scorer.score import load_reference, score_bytes
from tools.build_leaderboard import SUBMISSIONS, build
from tools.fetch import download

csv.field_size_limit(sys.maxsize)


def hf_url(revision: str, path: str) -> str:
    return f"https://huggingface.co/datasets/BDRC/tibetan-ocr-benchmark/resolve/{revision}/{path}"


def read_csv(url: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(download(url).decode("utf-8"), newline="")))


def run_date(run_id: str) -> str:
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})", run_id)
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}Z" if m else ""


def main() -> int:
    _, _, source = load_reference()
    rev = source["revision"]
    catalog = {r["run_id"]: r for r in read_csv(hf_url(rev, "runs/catalog.csv"))}
    summary = read_csv(hf_url(rev, "runs/cer_summary.csv"))

    best: dict[tuple[str, str], dict] = {}
    for row in summary:
        key = (row["engine"], row["model"])
        if key not in best or float(row["mean_cer"]) < float(best[key]["mean_cer"]):
            best[key] = row

    mismatches = 0
    for (engine, model), row in sorted(best.items(), key=lambda kv: float(kv[1]["mean_cer"])):
        run_id = row["run_id"]
        url = hf_url(rev, f"runs/predictions/{run_id}.csv")
        result = score_bytes(download(url))
        official = float(row["mean_cer"])
        ok = abs(result["mean_cer"] - official) < 1e-4
        mismatches += not ok
        print(f"{'ok ' if ok else 'MISMATCH'} {result['mean_cer']:.4f} vs {official:.4f}  {engine} / {model}")

        run_type = catalog.get(run_id, {}).get("run_type", "")
        meta = {
            "model": model,
            "team": engine,
            "training": {"ft": "fine-tuned", "ots": "off-the-shelf"}.get(run_type, ""),
            "open_weights": None,
            "model_url": "",
            "paper_url": "",
            "notes": f"BDRC reference run `{run_id}`.",
            "source": "bdrc-reference",
            "submitted_by": "BDRC",
            "submitted_at": run_date(run_id),
            "issue_url": "",
            "predictions_url": url,
        }
        folder = SUBMISSIONS / f"bdrc-{run_id}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    board = build()
    print(f"imported {len(best)} runs; leaderboard has {len(board['entries'])} entries; {mismatches} mismatches")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
