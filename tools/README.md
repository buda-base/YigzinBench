# tools

## Overview

The command-line layer around [`../scorer/`](../scorer/README.md). It parses
GitHub issue-form submissions, downloads prediction CSVs from allowed hosts
only, stores scored entries under `submissions/<id>/`, deletes entries,
imports BDRC's reference runs, syncs `scorer/data/` from the Hugging Face
dataset, and rebuilds `leaderboard/leaderboard.json` and the README top-10
table. The GitHub workflows in `.github/workflows/` are the main callers.
Committing workflows go through `.github/scripts/apply-and-push.sh`.

## Interface

### `submission.py`

- CLI: `python -m tools.submission {score|publish} --comment <path>`.
  `--comment` is required; the Markdown reply is written there.
- `score` exits 0 after writing a reply (errors go in the comment). Writes
  `verdict=`, `sha256=` and `comment_id=` to `$GITHUB_OUTPUT` when set.
- `publish` exits 0 when published or already published, 10 when refused
  (no marker, error verdict, hash mismatch), 1 on unexpected failure.
- Functions: `parse_issue_form`, `clean_text`, `clean_url`, `md`, `file_hash`,
  `render_marker`, `latest_marker`, `collect`, `score_entry`, `store_entry`,
  `pct`, `would_rank`, `exact_zero_pages`, `render_result`, `render_error`,
  `cmd_score`, `cmd_publish`, `main`.
- Score marker (exact first line of the bot reply):
  `<!-- yigzinbench:score v=1 verdict=(ok|error) sha256=([0-9a-f]{64}|-) scored_at=<time> -->`.
- `render_result` includes "Would rank #k of N" (ties by `(mean_cer,
  submitted_at)` like the board; N is board size + 1 before publish) and
  "Pages with CER exactly 0".
- Called by `score-submission.yml` and `publish-submission.yml`.

### `manage.py`

- CLI: `python -m tools.manage delete <id> --reason <text> [--issue <n>]`.
- Exit 0 if deleted, 10 if refused, 1 on unexpected error. Writes `model=`
  (and on refusal `result=refused` / `message=`) to `$GITHUB_OUTPUT`.
- `delete_entry(entry_id, reason, issue=None) -> str` raises `ManageError`
  for refusals. Ids must match `^(issue-\d+|bdrc-[\w.-]+)$`.

### `build_leaderboard.py`

- CLI: `python -m tools.build_leaderboard [--rescore]`.
- `removed_ids() -> set[str]` reads `submissions/_removed.json` (empty if
  missing). `build()` only reads folders, so it ignores that file.
- Called by `rescore-all.yml` through `apply-and-push.sh`.

### `fetch.py`

- No CLI. `rewrite_url`, `is_allowed`, `find_url`, `download`.
- `/blob/<rev>/...` becomes `/resolve/<rev>/...`; `download=true` is dropped
  from the query string. 401/403 mention gated or private repos; timeouts,
  connection errors, 429 and 5xx say the failure is probably temporary.

### `import_bdrc_runs.py`

- CLI: `python -m tools.import_bdrc_runs`.
- Drops rows whose `bdrc-<run_id>` is in `removed_ids()` before picking the
  best run per (engine, model) and before any download.

### `sync_dataset.py`

- CLI: `python -m tools.sync_dataset [--revision <sha>]`. Needs `pyarrow`.

### `.github/scripts/apply-and-push.sh`

- `bash .github/scripts/apply-and-push.sh <commit message> -- <command...>`.
- Command exit codes: 0 = done, 10 = refused, other = error.
- Up to 5 attempts: fetch/reset `origin/main`, run the command, commit,
  push. Writes `result=committed|refused|unchanged|push_failed|error` to
  `$GITHUB_OUTPUT`. After a successful push, writes `result=committed` then
  dispatches `deploy-pages.yml` (dispatch failure is a warning only).

## Invariants

- Each entry is a folder `submissions/<id>/` with `meta.json` and
  `result.json`, plus `predictions.csv` for issue submissions. Ids are
  `issue-<number>` for community entries and `bdrc-<run_id>` for BDRC runs.
- `submissions/_removed.json` is `{"removed": [{"id", "reason", "issue"}]}`,
  sorted by id. Publishing an `issue-<n>` that is listed there drops the
  record in the same commit.
- Ranking: entries sort ascending by `(mean_cer, submitted_at or "~")`.
- Downloads must match an allowed host after link rewriting, up to 20 MiB.
- Issue text reaches these modules only through environment variables.

## Side Effects

- `submission`: reads `ISSUE_*` and optional `BOT_COMMENTS_FILE`; downloads;
  always writes the comment file. `publish` writes `submissions/issue-<n>/`
  and calls `build()`.
- `manage delete`: removes a folder, appends `_removed.json`, calls `build()`.
- `build()`: writes `leaderboard/leaderboard.json` and the README table.
- `import_bdrc_runs`: may skip removed ids; writes `submissions/bdrc-*` and
  calls `build()`.
- Git commits and deploys are done by workflows via `apply-and-push.sh`.

## Verification

- Run: `python -m unittest discover -s tests -t .`
