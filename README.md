# YigzinBench

A public leaderboard for the [BDRC Tibetan OCR benchmark](https://huggingface.co/datasets/BDRC/tibetan-ocr-benchmark).
Anyone can download the 472 test pages, run their own OCR model, and submit the output.
GitHub Actions scores the submission, and the leaderboard is a static GitHub Pages site.
There is no server to run.

**[See the leaderboard](https://buda-base.github.io/YigzinBench/)** or **[submit your model](https://github.com/buda-base/YigzinBench/issues/new?template=submission.yml)**.

## Leaderboard

<!-- leaderboard:start -->
| # | Model | Team | Error rate |
|---:|---|---|---:|
| 1 | Yigdzin-v1 | BDRC OCR | 3.2% |
| 2 | bdrc-mitra-ocr-qwen35-0.8b | MITRA-BDRC | 7.3% |
| 3 | builtin/stable | google_vision | 22.2% |
| 4 | builtin/weekly | google_vision | 24.7% |
| 5 | PechaBridgeOCR_v1 | DONUT | 28.0% |
| 6 | PechaBridgeOCR_v2 | DONUT | 33.7% |
| 7 | PaddleOCR-VL-1.6-0.9B | PaddleOCR-VL | 37.4% |
| 8 | gemini-3-pro-preview | Gemini | 39.4% |
| 9 | gemini-3.1-pro-preview | Gemini | 40.3% |
| 10 | PaddleOCR-VL-1.5-0.9B | PaddleOCR-VL | 41.2% |

Top 10 of 46 models. [See the full leaderboard](https://buda-base.github.io/YigzinBench/), with breakdowns by script, technology and legibility.
<!-- leaderboard:end -->

## Submitting a model

1. **Download the pages.**
   ```python
   from datasets import load_dataset
   ds = load_dataset("BDRC/tibetan-ocr-benchmark", split="test")  # 472 pages: id, image, metadata
   ```
2. **Write one CSV**: UTF-8, header `id,transcription`, one row per page, with `id` exactly as in the dataset (`0002`, not `2`).
3. **Check your score locally** (optional, same code the leaderboard runs):
   ```bash
   pip install -r scorer/requirements.txt
   python -m scorer.score predictions.csv
   ```
4. **[Open a submission issue](https://github.com/buda-base/YigzinBench/issues/new?template=submission.yml)**: fill in the model name, team and links, and drag the CSV into the form.
   Within a few minutes a bot replies with your CER and a per-category breakdown.
   Editing the issue re-scores it. A maintainer then approves it and it appears on the leaderboard.

## How scoring works

The scorer in [`scorer/cer.py`](scorer/cer.py) is BDRC's reference implementation (`runs/compute_cer.py` in the dataset repo), copied unchanged:

- the prediction is normalized with [botok](https://github.com/OpenPecha/Botok) (the ground truth is pre-normalized);
- all whitespace is removed, repeated tsheg (`U+0F0B`) fold to one, and the placeholders `K O B I S` are dropped;
- per page, `CER = Levenshtein(hyp, ref) / len(ref)`, capped at 1.0;
- the ranking metric is the plain mean over all 472 pages, and a missing page counts as 1.0.

It reproduces BDRC's published `cer_summary.csv` exactly for all 46 reference models.
The ground truth and page metadata are vendored in [`scorer/data/`](scorer/data), pinned to the dataset revision in `SOURCE.json`.

## How it works

```
issue form ──► score-submission.yml ──► bot comment with CER          (anyone)
   │
   └─ label "approved" ──► publish-submission.yml                     (maintainers)
                              ├─ submissions/issue-<n>/{predictions.csv,meta.json,result.json}
                              ├─ leaderboard/leaderboard.json
                              └─ commit ──► deploy-pages.yml ──► GitHub Pages
```

| Path | What it is |
|---|---|
| `scorer/` | Validation and CER scoring (`python -m scorer.score`), plus the vendored ground truth |
| `tools/submission.py` | Parses the issue form, downloads the CSV, scores it, and writes the reply |
| `tools/build_leaderboard.py` | Rebuilds `leaderboard.json` from `submissions/` (`--rescore` re-scores all) |
| `tools/import_bdrc_runs.py` | Seeds the board with BDRC's reference runs (best run per model, linked from Hugging Face) |
| `tools/sync_dataset.py` | Pulls a new dataset revision into `scorer/data/` |
| `submissions/` | One folder per leaderboard entry; this folder is the source of truth |
| `site/` | The static leaderboard page (vanilla HTML/CSS/JS) |
| `.github/` | The issue form and the workflows |

Prediction files are downloaded only from GitHub issue attachments, Hugging Face `/resolve/` URLs, or raw gists, up to 20 MB.
Issue text reaches Python through environment variables and is never interpolated into a shell command.

## Maintainer guide

**One-time setup**

1. *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
2. *Settings → Actions → General → Workflow permissions:* allow **read and write**. The workflows request only what they need.
3. Create the two labels:
   ```bash
   gh label create submission --color 0E8A16 --description "Leaderboard submission"
   gh label create approved --color FBCA04 --description "Publish to the leaderboard"
   ```
4. If `main` has branch protection, allow GitHub Actions to push to it, or publishing can't commit.

**Approving a submission:** read the bot's score, check the model link and notes, then add the `approved` label.
Only users with write access can approve; the workflow checks this.
The entry is re-scored, committed under `submissions/issue-<n>/`, and the issue is closed.

**Fixing a submission:** ask the submitter to edit the issue, then remove and re-add the `approved` label.
The entry is re-scored and its folder overwritten.

**Removing a submission:** each entry is one folder under `submissions/`: community entries are `issue-<number>`, BDRC reference runs are `bdrc-<run_id>`.
To find a folder by model name:
```bash
grep -l '"model": "Yigdzin-v1"' submissions/*/meta.json
```
Then delete it, rebuild `leaderboard/leaderboard.json` and the README table, and push to `main`. The site redeploys automatically.
```bash
pip install -r scorer/requirements.txt   # once
git rm -r submissions/issue-12
python -m tools.build_leaderboard
git commit -am "Remove submission #12" && git push
```
Leave a comment on the original issue so the submitter knows why the entry is gone.

**A word on trust:** the ground truth is public, so a submission could be faked.
Approval is the safeguard: look for a model or code link and plausible per-category results.

**When BDRC updates the dataset:**
```bash
pip install -r scorer/requirements.txt pyarrow
python -m tools.sync_dataset            # pulls the latest revision into scorer/data/
python -m unittest discover -s tests -t .
git commit -am "Update ground truth to <rev>" && git push
```
Then run the **Re-score all submissions** workflow from the Actions tab.
Until you do, entries scored on the old revision are tagged "older version" on the site.

**Previewing the site locally:**
```bash
mkdir -p _site && cp -r site/. _site/ && cp leaderboard/leaderboard.json _site/ && python -m http.server -d _site 8000
```

## License

Benchmark data: CC0, by [BDRC](https://www.bdrc.io). No license has been chosen for the code in this repository yet.
