# scorer

## Overview

The Python scoring package for the BDRC Tibetan OCR benchmark. It checks a
submitted `id,transcription` predictions CSV against the vendored ground truth
in `data/` and reports per-page and aggregate character error rate (CER), with
breakdowns by page-metadata category. The CER logic in `cer.py` is BDRC's
reference implementation, copied unchanged. The submission and leaderboard
tools in [`../tools/`](../tools/README.md) call this package.

## Interface

### `cer.py`

- `cer(hyp_raw: str, ref_prepared: str) -> float`: normalizes and prepares the
  hypothesis, then returns `Levenshtein(hyp, ref) / len(ref)`, capped at 1.0.
- `prepare(text: str, is_hypothesis: bool = False) -> str`: runs
  `normalize_hypothesis` first for a hypothesis, then strips all whitespace,
  folds repeated tsheg and drops placeholder characters.
- `normalize_hypothesis(text: str) -> str`: replaces U+00A0 with a space, then
  applies botok `normalize_spaces(tibetan_specific=False)`,
  `normalize_unicode` and `normalize_graphical`, then strips `" \n\r"`.
- Constants: `CATASTROPHIC_THRESHOLD = 0.5`, `PLACEHOLDERS = frozenset("KOBIS")`.

### `score.py`

- Constants: `SCORER_VERSION = "1.0.0"`, `DATA_DIR` (`<package>/data`),
  `MAX_BYTES` (20 MiB), `UNKNOWN = "Unknown"`.
- `CATEGORIES`: ordered map of metadata column to label: `technology`,
  `script`, `script_4` (Script style), `legibility`, `rarity`, `period`.
- `class SubmissionError(Exception)`: a predictions file cannot be scored; the
  message is meant to be shown to the submitter.
- `load_reference() -> (ground_truth, pages, source)`: prepared ground truth by
  id, page metadata rows by id, and the `SOURCE.json` contents.
- `parse_predictions(raw: bytes) -> (preds, warnings)`: validates and parses
  the CSV.
- `score_predictions(preds: dict[str, str]) -> dict`: returns `mean_cer`,
  `median_cer`, `catastrophic_pct`, `coverage`, `n`,
  `breakdown{category: {value: {n, mean_cer}}}`, `per_page{id: cer}`,
  `dataset`, `dataset_revision`, `scorer_version`.
- `score_bytes(raw: bytes) -> dict`: `parse_predictions` then
  `score_predictions`, plus a `warnings` list; raises `SubmissionError`.
- `main(argv=None) -> int`: CLI entry point.

  ```bash
  python -m scorer.score predictions.csv [--json out.json]
  ```

### Other files

- `__init__.py` is empty; the package exports nothing at the top level.
- `requirements.txt` pins `botok==1.1.7` and `rapidfuzz==3.13.0`.
- `data/` holds `ground_truth.csv` (`id,transcription`), `pages.csv`
  (`id,technology,script,script_4,period,rarity,legibility`) and
  `SOURCE.json` (dataset name, revision, split). It is data only and has no
  contract file of its own.

## Invariants

- Only the hypothesis is normalized with botok; the reference is assumed to be
  pre-normalized and is only passed through `prepare`.
- `prepare` removes all whitespace, collapses two or more U+0F0B tsheg into
  one, then drops every character in `K O B I S`.
- An empty prepared reference gives CER 0.0 if the prepared hypothesis is also
  empty, otherwise 1.0. Per-page CER is capped at 1.0.
- The `cer.py` docstring requires bumping `SCORER_VERSION` and re-scoring every
  submission before the CER logic changes.
- Input files over `MAX_BYTES` raise `SubmissionError`.
- The file must decode as UTF-8 (a BOM is accepted); otherwise
  `SubmissionError` names the offending byte offset.
- The header must contain `id` and `transcription`, matched case-insensitively
  after stripping whitespace; other columns are ignored.
- Ids are stripped and rows with an empty id are skipped. A digit-only id
  missing from the ground truth is zero-padded to 4 characters when that form
  exists (`2` → `0002`), with a warning.
- Duplicate ids, unknown ids, malformed CSV and a file with no prediction rows
  each raise `SubmissionError` (lists show at most 10 ids).
- A missing transcription cell is scored as an empty string. A page without a
  prediction scores 1.0 and produces a warning; the mean and median always
  cover every ground-truth page.
- Rounding: per-page CER to 6 decimals; `mean_cer`, `median_cer` and breakdown
  `mean_cer` to 4; `catastrophic_pct` to 2. `catastrophic_pct` counts pages
  with CER strictly greater than `CATASTROPHIC_THRESHOLD`.
- In breakdowns an empty metadata value is grouped as `Unknown`, and values are
  sorted by name. Every ground-truth id must also appear in `pages.csv`, or
  `score_predictions` raises `KeyError`.
- `dataset` and `dataset_revision` in the result come from the `dataset` and
  `revision` keys of `data/SOURCE.json`.

## Side Effects

- `load_reference` reads `data/ground_truth.csv`, `data/pages.csv` and
  `data/SOURCE.json` once per process (`lru_cache(maxsize=1)`).
- Importing `score.py` calls `csv.field_size_limit(sys.maxsize)`, which changes
  process-global `csv` state.
- CLI: reads the predictions file; on `SubmissionError` prints `error: <msg>`
  to stderr and exits 1. On success prints `warning:` lines to stderr, the
  summary and category breakdowns to stdout, and exits 0.
- CLI with `--json PATH`: writes the full result, including per-page CER, as
  UTF-8 JSON (`indent=2`, trailing newline).
- No network calls.

## Verification

- Run: `python -m unittest discover -s tests -t .`
