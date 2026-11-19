# RFC 0001: Serverless submission, approval, and deletion

*   **Author:** kaldan007
*   **Status:** Draft
*   **Date:** 2026-11-19
*   **Source:** [docs/designs/serverless_submission_flow.md](../designs/serverless_submission_flow.md)
*   **Supersedes:** `concepts_brief.md` revision 3, where the two disagree. The brief still describes a submission page, comment commands, and threshold hints. This RFC follows the revised design.

This RFC is the decision record. File-by-file steps stay in the source design. The implementation plan in that design is not ready to code until the items in [Open before implementation](#open-before-implementation) are written into it.

--------------------------------------------------------------------------------

## Summary

YigzinBench is a public leaderboard for the BDRC Tibetan OCR benchmark (472 pages). It has no server. A static GitHub Pages site (`site/`) shows `leaderboard/leaderboard.json`. GitHub Actions score, publish, and re-score submissions. Folders under `submissions/` are the source of truth. The board and the README table are rebuilt from those folders.

The community is small and few submissions are expected. This RFC keeps that shape and makes the existing flow safe to run:

1.  **Submitting.** Participants keep the GitHub issue form. The bot accepts the Hugging Face links people usually copy (`/blob/` pages and `?download=true`). An error reply lists numbered fix steps.
2.  **Reviewing.** The bot scores the file, records its SHA-256, and posts one reply. The reply is edited in place. It shows the character error rate (CER), coverage, the rank the entry would take, and how many pages match the ground truth exactly.
3.  **Deciding.** A maintainer does not touch a label. **Close issue** (close as completed) publishes. **Close as not planned**, with a written reason, rejects. If publishing is refused or fails, the bot reopens the issue and says why. An open issue means the entry is not on the board.
4.  **Removing.** A "Delete submission" workflow, run from the Actions tab, removes any entry (`issue-*` or `bdrc-*`) and records its id so a later BDRC import does not bring it back.

The work ships in three stages, in order. Each stage builds on the ones before it. Work can stop after any stage.

| Stage | What ships | Goals |
| --- | --- | --- |
| 1 | Approval by closing, with the hash check; score marker; fallback score reply; link rewrites; `apply-and-push.sh` with deploy dispatch; re-score in its own concurrency group | 1, 2, 4, 7 |
| 2 | `_removed.json`, `tools/manage.py delete`, the "Delete submission" workflow | 3 |
| 3 | Rank and exact-match rows in the score reply; a "partial" tag on the board | 5, 6 |

## Motivation

Today there are 47 entries: 46 BDRC reference runs (`bdrc-*`) and one community entry (`issue-3`). Four problems make the current flow hard to run and easy to get wrong.

**Approval depends on two labels and can fail without a reply.** A maintainer approves by adding `approved`, but `publish-submission.yml` runs only if `submission` is still on the issue. If that label was removed, the job is skipped and nothing is posted. If the person adding the label lacks write access, the permission step exits before a reply file exists, and the issue gets no comment. Approving three issues in a row can drop one: `publish-submission.yml` and `rescore-all.yml` share the concurrency group `publish`, and GitHub keeps only one pending run per group, so a newer pending run cancels the older one before any job starts.

**The approved file may not be the reviewed file.** `tools/submission.py` downloads the CSV again at approval time and does not compare it with the file that was scored. Between scoring and approval, a submitter can edit the issue to point at a different file. A Hugging Face `/resolve/main/...` link can also start serving different bytes with no edit, because `tools/fetch.py` accepts any revision name, and gist links may leave out the revision. The ground truth is public. An honest file at review time and a different file at approval time is the change maintainer approval is meant to stop. With one community entry, one swapped file would be a large share of the community board.

**Removing an entry is manual and does not last.** Removal today is a local `git rm`, a rebuild, and a push. A maintainer without a checkout cannot do it. `tools/import_bdrc_runs.py` rewrites every `bdrc-*` folder it imports, so a deleted BDRC run comes back on the next import. Of the bot workflows, only "Publish submission" and "Re-score all submissions" redeploy the site. A push made by any other workflow with `GITHUB_TOKEN` starts no workflow, so a new removal workflow would leave the old board on the site.

**Submissions fail for avoidable reasons, and scores lack context.** Common Hugging Face links (`/blob/` pages, `?download=true`) do not match the allow-list and are rejected. If scoring crashes outside the scorer's own checks, the issue gets no reply. The board does not mark an entry that covers only some of the 472 pages. A missing page counts as CER 1.0, so in the main table a partial file looks like a weak model. The reply does not say where a new score would rank, or how many pages match the ground truth exactly.

## Goals

Each goal states how it will be checked.

1.  **The published file is the reviewed file.** Publishing happens only if the SHA-256 of the newly downloaded bytes equals the hash in the bot's score reply. Check: in a fork, a file whose bytes change at its link after scoring, with no issue edit, is refused when the issue is closed; the issue is reopened with a reply, and nothing is committed.
2.  **A maintainer publishes or rejects with GitHub's Close button and always sees the result.** Closing as completed publishes, or reopens the issue with the reason. Closing as not planned rejects. No label is added or removed by hand. Check: a test for each publish outcome, and a run of each in a fork.
3.  **Any entry can be deleted from the GitHub web UI, and stays deleted.** This covers `issue-*` and `bdrc-*` entries, through the "Delete submission" workflow. Check: in a fork, a deleted `bdrc-*` entry is still gone after `python -m tools.import_bdrc_runs`.
4.  **Every workflow commit redeploys the site.** Bot commits go through `apply-and-push.sh`, which starts `deploy-pages.yml` after a successful push. Check: no workflow runs `git push` except through the script, and a delete run in a fork updates the live page.
5.  **Partial entries are marked.** The board tags an entry whose coverage is below 472 pages. Check: with today's data the tag appears on exactly the entries whose `coverage < n` (21 of 47), and `python -m tools.build_leaderboard --rescore` changes no `mean_cer` value.
6.  **Maintainers see where a new score would land.** The score reply shows the rank it would take ("would rank #k of N") and the number of pages with CER exactly 0. Check: a test reply for a fixture result shows both rows with the expected numbers. There are no thresholds. The maintainer judges.
7.  **Fewer submissions fail for avoidable reasons.** `/blob/` and `?download=true` links are accepted, a scoring crash still gets a reply, and the error reply lists numbered fix steps. Check: unit tests for both link forms and for the fallback reply.
8.  **Stay serverless.** GitHub Pages plus GitHub Actions only. Check: no workflow uses a secret other than `GITHUB_TOKEN`, and `site/` makes no authenticated request.

## Non-goals

*   A hosted backend, login system, or database.
*   Creating the issue for the participant. The participant always clicks submit on GitHub with their own account.
*   Submitting without a GitHub account.
*   A submission page on the site. Deferred; see Future work.
*   Comment commands such as `/approve`. Deferred; see Future work.
*   Any label step for maintainers. The `approved` label is removed. The `submission` label stays, because the issue form adds it and the workflows filter on it.
*   An archive, hidden state, or restore command. Reject before publication. Delete after. To undo a delete: for an `issue-*` entry, reopen the issue and close it as completed; for a `bdrc-*` entry, a maintainer with a local checkout restores the folder, removes its record, rebuilds, and pushes.
*   Participants deleting or withdrawing published entries. They ask a maintainer in the issue. A submitter who closes their own open issue publishes nothing.
*   Updating a published entry in place. The submitter opens a new submission. The maintainer publishes it and deletes the old entry.
*   Changing BDRC's scoring rule (missing page = CER 1.0) or rejecting files for low coverage.
*   Judging submissions automatically. The rank and exact-match rows are facts for the maintainer and never change the verdict.
*   Proving a submission is honest. With a public ground truth this cannot be done. Maintainer review, backed by the hash check, stays the safeguard.
*   Removing a file from git history. Deleting removes an entry from the board, not from repository history or from old Pages builds.

## Proposal

Nothing new runs outside GitHub. The site stays static. All writes happen in Actions with `GITHUB_TOKEN`. The repository is the only state.

```text
 PARTICIPANT                                     MAINTAINER
     |                                               |
     v                                               |
 GitHub issue form (label: submission, automatic)    |
     | issues: opened / edited                       |
     v                                               |
 score-submission.yml                                |
   python -m tools.submission score                  |
   -> one bot reply, edited in place;                |
      first line: <!-- yigzinbench:score ... -->     |
                                                     |
     issues: closed (completed)  <-------------------+ "Close issue"
     v                                               |
 publish-submission.yml                              | Actions tab: id, reason
   1. permission check on the closer                 +------------------+
   2. apply-and-push.sh -- tools.submission publish                     v
   3. reply; reopen the issue unless published          delete-submission.yml
     |                                                    apply-and-push.sh --
     |                                                    tools.manage delete
     |                                                          |
     +------------------ commit on main <-----------------------+
                              |
              apply-and-push.sh: gh workflow run
                              v
                      deploy-pages.yml
```

### Critical user journeys

**CUJ 1, a participant submits a file.** They open the issue form from the site's "Submit your model" button, attach a CSV or paste a Hugging Face or gist link, and submit. Within minutes, one bot reply appears. Its first line says "Ready for review" or "Could not be scored", followed by the CER, coverage, the rank the entry would take, the number of exact-match pages, the file's short hash, and the time it was scored. A `/blob/` link or a link ending in `?download=true` works like a `/resolve/` link.

**CUJ 2, a participant fixes a failed file.** The participant edits the first post of the issue with a new file or link, following the numbered steps in the bot reply. The bot updates the same reply in place with the new result and the new hash.

**CUJ 3, a maintainer publishes.** The maintainer clicks **Close issue** (close as completed) on an open submission whose reply says "Ready for review". The workflow downloads the file again, checks its hash against the score reply, writes `submissions/issue-<n>/`, rebuilds the board, commits, and replies "Published as `issue-<n>`". The site redeploys. If anything stops the publish, the bot reopens the issue and replies with the reason. Nothing is reported as published unless it was pushed.

**CUJ 4, a maintainer rejects.** The maintainer writes the reason and chooses **Close with comment → Close as not planned**. The issue stays closed. The bot does nothing.

**CUJ 5, a maintainer deletes a published entry.** They run "Delete submission" from the Actions tab with the entry id and a reason. The folder is removed, the id is added to `submissions/_removed.json`, the board is rebuilt and committed, and the site redeploys. A later BDRC import does not bring the entry back.

### Where state lives

Each state is read from one place. No labels are read as state.

| State | Read from |
| --- | --- |
| Not ready | Open issue; no bot score marker yet, or the marker has `verdict=error` |
| Ready for review | Open issue; the marker has `verdict=ok` |
| Published | Folder `submissions/issue-<n>/` exists |
| Closed, not on board | Issue closed, no folder (rejected, deleted, or closed by the submitter) |

Maintainers find the review queue with `is:open label:submission`.

## Detailed design

### Score marker

Only the score reply carries the marker, and the marker is the exact first line of that reply:

```text
<!-- yigzinbench:score v=1 verdict=(ok|error) sha256=([0-9a-f]{64}|-) scored_at=<time> -->
```

For `verdict=error` the hash is `-`. The workflow fetches only comments whose author is `github-actions[bot]`. Python accepts a comment only if the whole first line matches that pattern. A marker anywhere else in a comment is ignored, so file content that the bot repeats in an error message cannot plant one. If more than one bot comment starts with a valid marker, the one with the latest `updated_at` wins. Error text that comes from the scorer is escaped before it is placed in the reply.

The marker records the SHA-256 of the downloaded CSV bytes. Metadata (model, team, links) is not hashed. Metadata changes only through an issue edit, every edit triggers a re-score, and the re-score replaces the marker. The accepted risk in Decision D1 covers that.

`score` computes the hash and a verdict, `ok` or `error`. A download failure is an `error` like any other. Its message says the file could not be fetched and may not be wrong: for 401 and 403, that the repository may be gated or private; for timeouts, connection errors, 429, and 5xx, that the problem is probably temporary and a maintainer can re-run the job.

The reply keeps one bot score comment per issue. The workflow edits that comment, or creates one if there is none. The reply step runs even when scoring fails. If no reply file exists, it posts that scoring failed because of a problem on our side, with a link to the run. A maintainer can click "Re-run jobs", or anyone with access can edit the issue. "Re-run jobs" uses the workflow file of the original run, so after a release only an edit picks up the new code.

### Publishing

`publish-submission.yml` runs on `issues: closed`, and only when the issue has the `submission` label and `github.event.issue.state_reason` is `completed`. Every other close, including "not planned" and "duplicate", is skipped with no output.

The existing write-access check stays. It reads the collaborator permission, which reports `maintain` as `write`, and accepts `admin` and `write`. Someone without write access can close only their own issue. That case is the submitter withdrawing: the bot replies "Closed by the submitter; nothing was published." and stops.

For a maintainer, the workflow runs `python -m tools.submission publish` through `apply-and-push.sh`. On a fresh tree, `publish` reads the state, downloads the file, compares its hash with the score marker, writes `submissions/issue-<n>/`, and rebuilds the board.

| Case | `publish` exit | `result` | Reply | Issue ends |
| --- | --- | --- | --- | --- |
| Published | 0 | `committed` | "Published as `issue-<n>`" | closed |
| Already published (folder exists) | 0 | `unchanged` | "Already published as `issue-<n>`" | closed |
| No score marker yet | 10 | `refused` | "Not scored yet. Wait for the bot's reply, then close the issue again." | reopened |
| Verdict is `error` | 10 | `refused` | "The file could not be scored; see the bot's reply." | reopened |
| Hash mismatch | 10 | `refused` | The D1 refusal text | reopened |
| 5 failed pushes | (any) | `push_failed` | "Nothing was published: the push failed 5 times. Close the issue again to retry." | reopened |
| Any other failure | 1 | `error` | "Publishing failed; see <run link>." | reopened |

The reply and the reopen step run even when an earlier step fails. The reply file that `publish` writes is posted only for `committed`, `unchanged`, and `refused`, so a failed push is never reported as published.

`apply-and-push.sh` runs the change up to 5 times: fetch `origin/main`, reset hard to it, run the Python step again on the fresh tree, regenerate the board and the README table, commit, and push. Running the whole step again means derived files never conflict. A second close of a published issue finds the folder and changes nothing. After a successful push the script starts `deploy-pages.yml`. `rescore-all.yml` and `delete-submission.yml` use the same script. Workflows that call it need `contents: write` and `actions: write`.

#### Decision D1: publishing is bound to the latest score reply

Closing takes no argument. Publishing downloads the file again and compares its hash with the latest bot score marker. On a mismatch it refuses with: "The file at the link changed after it was scored, and the issue was not edited, so nothing scored the new file. Ask the submitter to link a pinned revision (a Hugging Face commit or a gist revision) and edit the issue; the bot will score it again."

This catches any change after the last scoring with no issue edit, such as a Hugging Face `main` link that now serves different bytes, or a gist without a pinned revision.

**Accepted risk.** The score reply is updated in place on every issue edit. If a submitter edits the issue after the maintainer reads the reply and before they close the issue, the new file is published without a fresh look. The maintainer's protection is to check the reply just before closing. GitHub shows an "edited" marker on the bot comment, and the reply prints the time it was last scored. A late swap is visible and is not blocked. This RFC accepts that at the current volume of one maintainer and a few submissions.

#### Decision D2: git is the only lock

`publish-submission.yml` and `delete-submission.yml` have no concurrency group. Every run starts. `apply-and-push.sh` resets to the latest `origin/main` before each attempt, and the Python step re-reads the state from that fresh tree, so the run that pushes second sees the first one's result.

A shared group is not used because it can cancel a pending run, which would close an issue with no reply. `rescore-all.yml` moves from the shared `publish` group to its own `rescore` group, so two re-scores never overlap. If a publish pushes while a re-score is running, the re-score's push is rejected and the whole re-score runs again on the fresh tree. That costs minutes per retry. Re-scores are rare and started by hand, so the cost is accepted. After 5 failed pushes the run stops, nothing is committed, the issue is reopened, and the reply says to close it again.

### Deletion

`submissions/_removed.json` holds `{"removed": [{"id", "reason", "issue"}]}`, sorted by id. The delete commit records the date, and its message names the person who ran the workflow. The board builder ignores the file, because it reads only folders.

`python -m tools.manage delete <id> --reason <text>` checks the id against `^(issue-\d+|bdrc-[\w.-]+)$`, checks that the folder exists and the id is not already removed, removes the folder, appends the record, and rebuilds the board. Exit 0 if deleted, 10 if refused, 1 on any other error.

`tools/import_bdrc_runs.py` drops removed runs before it picks the best run per (engine, model) and before any download, so the next-best run can take a removed run's place.

`delete-submission.yml` is a `workflow_dispatch` with inputs `id` and `reason`. Inputs reach the script through environment variables. Publishing an `issue-<n>` that has a removed record drops the record in the same commit, so reopening and closing a deleted issue publishes it again.

### Redeploying

`apply-and-push.sh` runs `gh workflow run deploy-pages.yml --ref main` after each successful push. Only runs that changed `main` deploy. `deploy-pages.yml` already accepts `workflow_dispatch`, checks out `main`, and uses the `pages` concurrency group, which keeps one pending deploy of the latest `main`. The `workflow_run` trigger is removed. Committing workflows need `actions: write`. Human pushes to `site/**` and `leaderboard/**` still deploy through the existing `push` trigger.

### Rank and the partial tag (Stage 3)

The score reply gains two rows: "Would rank #k of N", where k is one more than the number of board entries with a lower `mean_cer` and N is the number of entries plus one, and "Pages with CER exactly 0: m", counted from per-page results over pages whose reference text is not empty. An empty or missing `leaderboard.json` gives "Would rank #1 of 1". The scorer does not change.

The board shows a "partial (<coverage>/472)" tag, next to the existing "older version" tag, on entries whose coverage is below the page count. Today that is 21 of 47 entries.

The rank formula as written disagrees with how the board sorts ties, and a publish that rebuilds the board before rendering the reply would count the new entry twice. See [Open before implementation](#open-before-implementation).

## Alternatives considered

### Overall architecture

**A hosted web app with logins and a database.** Full control of the form and direct uploads. Rejected because of hosting and upkeep for one maintainer, and because the repository would stop being the only record.

**Create the issue automatically from the static site.** One click for the participant. Rejected because it needs a token on a server, the API cannot attach files, and the issue would be authored by a bot.

**Publish entries at once with a "pending review" tag.** Entries appear within minutes. Rejected because an unreviewed result would appear on the public board.

### Approving

**Keep label approval and fix its failures.** A smaller change. Rejected because maintainers would still add and remove labels, and a label cannot carry a reject reason. Closing the issue is one click GitHub users already know.

**Comment commands (`/approve`, `/reject`, `/delete`).** Explicit, and harder to trigger by accident than a Close click. Rejected because a parser, a workflow on every comment, and a state-by-command table are too much machinery for a few submissions a year. Kept as future work.

**Approval through a pull request.** The bot pushes a snapshot and opens a PR. Merging approves. This would bind the published file to the reviewed bytes by construction. Rejected because PRs opened with `GITHUB_TOKEN` do not trigger CI, a repository setting must allow Actions to open PRs, and the issue and the PR must stay in sync. The hash check leaves the gap accepted in D1. This alternative would close that gap.

**The maintainer quotes the short hash when approving.** Closes the gap between reading the reply and approving. Rejected because approval would no longer be one click, and a maintainer who copies the hash without reading gets no real protection.

**Refuse to publish after a recent re-score.** Catches most timed edits with no new step. Rejected because any fixed window is wrong both ways: a tab left open longer passes, and an honest quick approval after a fix is refused.

### Queueing runs

**One concurrency group per issue.** Runs on different issues are never dropped. Rejected because two quick events on the same issue can still cancel the earlier run before it replies.

**One shared `publish` group.** Runs never overlap. Rejected because pending runs can be cancelled, which is the silent failure this design exists to remove.

### Removing entries

**An archive state with a restore command.** Reversible from the GitHub UI. Rejected because deleting is rare, an `issue-*` entry can be restored by reopening and closing, and a `bdrc-*` restore by hand is acceptable at this volume.

**Participants withdraw their own published entries.** Rejected because it needs a second permission rule, and an entry could disappear after a dispute without a maintainer seeing it.

**Closing a reopened published issue updates the entry.** Rejected because a new submission plus deleting the old entry needs no extra state.

### Checking files

**A 90% minimum-coverage gate.** Keeps partial files off the board. Rejected because eight BDRC reference runs are below 425 of 472 pages, `--rescore` would stop, and the gate departs from BDRC's rule. Partial entries are tagged instead.

**Threshold-based review hints.** Flag a submission when its exact-zero share or similar signals pass a threshold. Rejected because the thresholds need calibration and drift as models improve, and at a few submissions a year the maintainer reads every reply. The rank and exact-match rows give the same information with nothing to tune.

### Submitting

**Build a submission page now.** A page checks the CSV in the browser and opens a prefilled issue form. Rejected for this RFC because the community is small, and the link rewrites and numbered fix steps remove the most common avoidable failures. Kept as future work.

## Security and operations

Issue text, ids, and reasons reach scripts only through environment variables, never through `${{ }}` inside `run:`. The `issues` workflows run from the default branch with a write token, on issues anyone can open. Only the first line of comments by `github-actions[bot]` is read for score markers. Publishing checks the closer's permission before any write. Entry ids from `workflow_dispatch` must match `^(issue-\d+|bdrc-[\w.-]+)$` and name an existing folder before any file is touched.

A publish run takes about one minute, mostly `pip install`. A re-score that loses a push race runs again in full.

Stages 1 to 3 are one pull request each, released in order. After Stage 1 is released, a maintainer edits the title of each open submission so it is scored again and gets a marker. An open issue without a marker cannot be published. After merging Stage 1, run `gh label delete approved --yes`.

Each stage is reverted with `git revert` of its merge commit. Reverting Stage 1 brings back label approval; the `approved` label must be re-created by hand. Reverting Stage 2's change to `tools/import_bdrc_runs.py` makes the next BDRC import bring back every deleted `bdrc-*` entry. Revert that change only together with a manual check of `submissions/_removed.json`.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| A maintainer closes as completed by habit, meaning to reject | An entry is published | The reply says so at once. Undo with the Delete workflow. |
| A file is swapped between review and closing | An unreviewed file is published | Hash check (Goal 1). The edit-window gap is accepted (D1). |
| A forged score marker | A bad file is published | Marker read only from the first line of bot comments. |
| Write token on events anyone can cause | Script injection | Event text only through `env`. |
| Hugging Face rate limits during a re-score retry | A re-score fails | Accepted. Re-scores are rare and started by hand. |
| A download fails during scoring | The submitter sees an error | The message says it is temporary. Re-run or edit the issue. |
| Git history grows by up to 20 MiB per entry | Slower clones | Accepted. See Future work. |

## Future work

*   **A submission page** that checks the CSV in the browser and opens a prefilled issue form. Pick it up if participants report trouble with the issue form, or if several first attempts cannot be scored. Check local files only. Compare only pass/fail and coverage with Python on shared fixtures. Generate the page's copy of the form from `submission.yml`. Measure the issue form's prefill limits first.
*   **Comment commands.** Pick them up if deleting from the issue, or explicit commands, become worth the machinery. Four states (not ready, ready, published, closed). A rules table for each command in each state. Every command, including reject, runs through `apply-and-push.sh`.
*   **Rebuild the board on any push to `submissions/**`, or build `leaderboard.json` at deploy time.** Deletion could then also be a folder delete in the GitHub web UI.
*   **Provenance badges** ("open weights + code", "self-reported"). Needs new fields in the issue form and site work.
*   **A soft size budget for stored CSVs.** A later option is to keep only `meta.json`, `result.json`, and the hash on `main`, and store CSV bytes on a separate data branch.

## Open before implementation

The decisions above are settled. The file-level plan in the source design still has gaps found by the implementation-readiness review on 2026-11-19 (`egm_review_round2/implementation_readiness_report.md`). An implementer who follows the plan as written will make these choices alone. They should be written into the design before Stage 1 starts.

1.  **Cancelled score runs.** `score-submission.yml` uses `cancel-in-progress: true`. A reply step that runs on cancellation can post "Scoring failed on our side" over a newer score, or overwrite the marker. The reply step needs a guard that skips cancelled jobs.
2.  **A crashed re-score leaves the old `ok` marker.** If scoring dies before it records the comment id, the fallback is a new comment with no marker. The previous `ok` marker stays in force. The plan should say whether the fallback edits the existing score comment.
3.  **Deploy dispatch after a successful push.** If `gh workflow run` fails, `result=committed` is never written, and the workflow can reopen an issue whose entry is already on `main`. Write `result=committed` immediately after the push, and treat a dispatch failure as a warning.
4.  **The published reply does not contain the entry id.** Today's `render_result(..., published=True)` does not print `issue-<n>`. The plan should say whether that function gains the id line or `publish` appends it.
5.  **Rank formula.** Publishing rebuilds the board before the reply, so "N + 1" counts the new entry twice. The board breaks ties by `(mean_cer, submitted_at)`. The plan's "strictly lower CER" formula ranks a tie ahead of existing entries. Show the rank rows on the pre-publish reply, and define the tie rule to match the board.
6.  **Delete refusal text never reaches the run summary.** `manage delete` writes the refusal only to stderr, and the script exits 0 on a refusal. The summary step cannot read that stderr. Write the message to `$GITHUB_OUTPUT` (or a file), and fail the run when `result` is `refused`. Use one CLI signature. The technical plan mentions `--actor`; the file plan uses `--reason` and an optional `--issue`. The commit message records who ran the workflow.
7.  **Tests cannot be written from the plan alone.** `temp_repo()` does not say how a test picks bytes per URL, which the hash-mismatch case needs. The BDRC import test needs fixture catalog rows, and no fixture files are listed. The script tests do not say how to make a push fail once and then five times, or which git identity to use. The fallback reply has no unit test. The private-gist end-to-end step does not produce the temporary-failure message the plan describes. 404 and other 4xx codes have no wording.
8.  **Stage 1 README describes Stage 2.** The Stage 1 maintainer guide tells the reader to delete and to undo by reopening, but reopening a published issue only gets "already published". Delete and undo belong in the Stage 2 guide, and "undo" means undoing a delete of an `issue-*` entry.

## Rollout check

*   Unit tests: `pip install -r scorer/requirements.txt`, then `python -m unittest discover -s tests -t .`.
*   After Stages 1 and 2, on a clean checkout, `python -m tools.build_leaderboard` changes nothing under `leaderboard/` on today's data.
*   After Stage 3, `python -m tools.build_leaderboard --rescore` changes no `mean_cer` value.
*   End to end, in a fork: a `/blob/` link scores; closing a ready issue publishes and updates the site; closing before a score reply reopens with "Not scored yet"; an unpinned gist whose bytes change is refused; a close as not planned does nothing; a deleted `bdrc-*` entry stays gone after import; the partial tag appears on the entries whose coverage is below the page count.
