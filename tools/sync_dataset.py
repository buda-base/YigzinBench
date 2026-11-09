"""Refresh scorer/data/ from a revision of the Hugging Face dataset.

    pip install pyarrow
    python -m tools.sync_dataset                 # latest revision on the Hub
    python -m tools.sync_dataset --revision <sha>

Writes ground_truth.csv, pages.csv (page metadata) and SOURCE.json. Afterwards
run `python -m tools.build_leaderboard --rescore` and commit everything, so
every entry is scored against the same ground truth.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import urllib.request
from pathlib import Path

from scorer.score import DATA_DIR

DATASET = "BDRC/tibetan-ocr-benchmark"
PARQUET = "data/test-00000-of-00001.parquet"
META_COLUMNS = ["id", "technology", "script", "script_4", "period", "rarity", "legibility"]


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "YigzinBench-sync"})
    with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as fh:
        shutil.copyfileobj(resp, fh)


def main() -> int:
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--revision", help="dataset commit sha (default: latest)")
    args = ap.parse_args()

    revision = args.revision
    if not revision:
        with urllib.request.urlopen(f"https://huggingface.co/api/datasets/{DATASET}", timeout=60) as resp:
            revision = json.load(resp)["sha"]
    base = f"https://huggingface.co/datasets/{DATASET}/resolve/{revision}"

    with tempfile.TemporaryDirectory() as tmp:
        gt_path, parquet_path = Path(tmp) / "ground_truth.csv", Path(tmp) / "test.parquet"
        fetch(f"{base}/runs/ground_truth.csv", gt_path)
        fetch(f"{base}/{PARQUET}", parquet_path)

        rows = sorted(pq.read_table(parquet_path, columns=META_COLUMNS).to_pylist(), key=lambda r: r["id"])
        with gt_path.open(encoding="utf-8", newline="") as fh:
            gt_ids = {r["id"].strip() for r in csv.DictReader(fh)}
        if gt_ids != {r["id"] for r in rows}:
            raise SystemExit("ground_truth.csv and the parquet disagree on page ids; not updating.")

        shutil.copyfile(gt_path, DATA_DIR / "ground_truth.csv")
        with (DATA_DIR / "pages.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=META_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    source_path = DATA_DIR / "SOURCE.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["revision"] = revision
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"scorer/data updated to {DATASET}@{revision} ({len(rows)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
