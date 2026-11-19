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

Top 10 of 47 models. [See the full leaderboard](https://buda-base.github.io/YigzinBench/), with breakdowns by script, technology and legibility.
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
4. **[Open a submission issue](https://github.com/buda-base/YigzinBench/issues/new?template=submission.yml)**: fill in the model name, team and links, and drag the CSV into the form (or paste a Hugging Face `/resolve/` or `/blob/` link, or a raw gist URL).
   Within a few minutes a bot replies with your CER, coverage, where the score would rank, and how many pages match exactly.
   Editing the issue re-scores it. A maintainer publishes it by closing the issue as completed.

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
issue form ──► score-submission.yml ──► bot reply with CER + hash marker   (anyone)
   │
   └─ Close as completed ──► publish-submission.yml                        (maintainers)
                              ├─ hash check against the score reply
                              ├─ submissions/issue-<n>/{predictions.csv,meta.json,result.json}
                              ├─ leaderboard/leaderboard.json
                              └─ apply-and-push.sh ──► deploy-pages.yml ──► GitHub Pages

Actions tab ──► delete-submission.yml ──► remove folder + _removed.json   (maintainers)
```

| Path | What it is |
|---|---|
| `scorer/` | Validation and CER scoring (`python -m scorer.score`), plus the vendored ground truth |
| `tools/submission.py` | Parses the issue form, scores or publishes, writes the marked reply |
| `tools/manage.py` | Deletes a published entry and records it in `_removed.json` |
| `tools/build_leaderboard.py` | Rebuilds `leaderboard.json` from `submissions/` (`--rescore` re-scores all) |
| `tools/import_bdrc_runs.py` | Seeds the board with BDRC's reference runs (skips ids in `_removed.json`) |
| `tools/sync_dataset.py` | Pulls a new dataset revision into `scorer/data/` |
| `submissions/` | One folder per leaderboard entry; this folder is the source of truth |
| `site/` | The static leaderboard page (vanilla HTML/CSS/JS) |
| `.github/` | The issue form, workflows, and `scripts/apply-and-push.sh` |

Prediction files are downloaded only from GitHub issue attachments, Hugging Face `/resolve/` or `/blob/` URLs, or raw gists, up to 20 MB.
Issue text reaches Python through environment variables and is never interpolated into a shell command.

## Maintainer guide

**One-time setup**

1. *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
2. *Settings → Actions → General → Workflow permissions:* allow **read and write**. The workflows request only what they need.
3. Create the submission label (the issue form adds it automatically):
   ```bash
   gh label create submission --color 0E8A16 --description "Leaderboard submission"
   ```
   The old `approved` label is unused; after deploying this flow, remove it with `gh label delete approved --yes`.
4. If `main` has branch protection, allow GitHub Actions to push to it, or publishing can't commit.

**Review queue:** `is:open label:submission`.

| Action | How |
|---|---|
| Publish | Read the bot reply (check it just before closing), then **Close issue** (completed). |
| Reject | Write the reason, then **Close as not planned**. The bot does nothing. |
| Retry after a refusal | The bot reopens the issue; fix what it asked for, then Close as completed again. |
| Delete a published entry | Actions → **Delete submission** with the entry id (`issue-<n>` or `bdrc-<run_id>`) and a reason. |
| Undo a delete (`issue-*`) | Reopen the issue and Close as completed (publishes again and drops the removed record). |
| Undo a delete (`bdrc-*`) | Restore the folder locally, remove its `_removed.json` record, rebuild, and push. |
| Update a published entry | Ask for a new submission issue; publish it, then delete the old entry. |

Only users with write access can publish; a submitter closing their own issue gets "Closed by the submitter; nothing was published."
Publishing re-downloads the file and refuses if its SHA-256 no longer matches the score reply (ask for a pinned Hugging Face commit or gist revision, then edit the issue).

**Failed score:** re-run the score job, or edit the issue. After a release, prefer editing so the new workflow file is used.

**A word on trust:** the ground truth is public, so a submission could be faked.
Maintainer review, backed by the hash check, is the safeguard: look for a model or code link and plausible per-category results.

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

## Subdirectories & System Boundaries

The folders with code each have a contract file listing their interface, invariants and side effects.

- `scorer/`: [scorer/README.md](scorer/README.md) - parses and validates a predictions CSV and computes CER against the vendored ground truth. No network access.
- `tools/`: [tools/README.md](tools/README.md) - the issue-form, download, leaderboard-build, BDRC-import and dataset-sync CLIs that the workflows call. Imports `scorer.score`.
- `site/`: [site/README.md](site/README.md) - the static page that renders `leaderboard.json`. It reads data only and never writes to the repo.
- `submissions/`, `leaderboard/`, `scorer/data/`: data only, written by `tools/` (see its contract).
- `tests/`: unit tests for the scorer.

## Global Invariants

- `submissions/<id>/` is the source of truth; `leaderboard/leaderboard.json` and the table above are derived from it by `python -m tools.build_leaderboard` and must not be edited by hand.
- `leaderboard.json` entries are sorted by ascending mean CER, ties to the earlier submission. The site takes the first entry as the best model.
- Changing the CER logic in `scorer/cer.py` requires bumping `SCORER_VERSION` in `scorer/score.py` and re-scoring every submission; entries scored on another scorer version or dataset revision are marked stale.
- Predictions are downloaded only from GitHub issue attachments, Hugging Face `/resolve/` or `/blob/` URLs or raw gists, up to 20 MiB (`tools/fetch.py`).
- `tools/build_leaderboard.py` rewrites only the text between the two leaderboard comment markers in this file; keep both markers.

## Global Side Effects

- Network: Hugging Face (dataset sync, BDRC run import, prediction downloads), GitHub and gist downloads, and Google Fonts on the site.
- Files: the tools write `submissions/`, `leaderboard/leaderboard.json`, this README's table and `scorer/data/`.
- Git commits, issue comments and Pages deploys are done by the workflows in `.github/workflows/`, not by the Python code.

## System Verification

- Run: `python -m unittest discover -s tests -t .`

## License

Benchmark data: CC0, by [BDRC](https://www.bdrc.io). No license has been chosen for the code in this repository yet.
