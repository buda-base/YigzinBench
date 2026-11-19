# Serverless Submission, Approval and Deletion Flow for YigzinBench

*   **Author:** kaldan007
*   **Status:** Draft (revised after review)
*   **Date:** 2026-11-19
*   **Predecessor:** concepts brief, revision 3 (not committed; every rule this
    design keeps from it is stated here)

--------------------------------------------------------------------------------

## Overview

YigzinBench is a public leaderboard for the BDRC (Buddhist Digital Resource
Center) Tibetan OCR benchmark (472 pages). It has no server: a static GitHub
Pages site (`site/`) shows `leaderboard/leaderboard.json`, and GitHub Actions
workflows score, publish and re-score submissions. The folders under
`submissions/` are the source of truth; the board and the README table are
rebuilt from them.

The community is small and few submissions are expected. This design makes the
existing flow safe and simple for that scale, without adding a server, a login
system or a database:

1.  **Submitting.** Participants keep using the GitHub issue form. The bot now
    accepts the Hugging Face links people usually copy (`/blob/` pages,
    `?download=true`), and its error reply lists numbered fix steps.
2.  **Reviewing.** The bot scores the file, records its SHA-256 hash, and posts
    one reply, edited in place, with the CER (character error rate), coverage,
    the rank the entry would take, and how many pages match the ground truth
    exactly.
3.  **Deciding.** No maintainer touches a label. To publish, a maintainer clicks
    GitHub's **Close issue** button ("Close as completed"). To reject, they
    write the reason and choose **Close as not planned**. If publishing is
    refused or fails, the bot reopens the issue and says why, so an open issue
    always means "not on the board".
4.  **Removing.** A "Delete submission" workflow, run from the Actions tab,
    removes any entry (`issue-*` or `bdrc-*`) and adds its id to a removed list,
    so later BDRC imports do not bring it back.

The work ships in three stages, in order; each builds on the ones before it.
Work can stop after any stage.

| Stage | What ships | Goals |
| --- | --- | --- |
| 1 | Approval by closing, with the hash check; score marker; fallback score reply; link rewrites; `apply-and-push.sh` with deploy dispatch; re-score in its own concurrency group | 1, 2, 4, 7 |
| 2 | `_removed.json`, `tools/manage.py delete`, the "Delete submission" workflow | 3 |
| 3 | Rank and exact-match rows in the score reply; a "partial" tag on the board | 5, 6 |

## The Problem

Today there are 47 entries: 46 BDRC reference runs (`bdrc-*`) and one community
entry (`issue-3`). The flow has four problems.

**1. Approval depends on two labels and can fail without a reply.**

*   A maintainer approves by adding the `approved` label, but
    `publish-submission.yml` only runs if the `submission` label is also still
    on the issue. If it was removed, the job is skipped and nothing is posted.
    The README has to warn about this, and fixing a submission means removing
    and re-adding a label. This label handling is what makes the process hard
    to run.
*   If the person adding the label lacks write access, the permission step
    exits before the reply file exists. The reply step then finds no file and
    exits quietly. The issue gets no comment.
*   Approving three issues in a row can lose one. `publish-submission.yml` and
    `rescore-all.yml` share the concurrency group `publish`, and GitHub keeps
    only one pending run per group: a newer pending run cancels the older one
    before any of its jobs start, so it posts nothing.

**2. The approved file may not be the reviewed file.**

*   `tools/submission.py` downloads the CSV again at approval time
    (`run()`, lines 158-160). It does not compare it with the file that was
    scored.
*   Between scoring and approval, a submitter can edit the issue to point at a
    different file. A Hugging Face `/resolve/main/...` link can also start
    serving different bytes with no edit at all, because `tools/fetch.py`
    accepts any revision name, and gist links may leave out the revision.
*   The ground truth (`scorer/data/ground_truth.csv`) is public. An honest file
    at review time and a doctored file at approval time is the attack that
    maintainer approval is meant to stop. With one community entry, a single
    doctored file would be a large share of the community board.

**3. Removing an entry is manual and does not last.**

*   Removal today is a local `git rm`, a rebuild and a push. A maintainer
    without a local checkout cannot do it.
*   `tools/import_bdrc_runs.py` rewrites every `bdrc-*` folder it imports, so a
    deleted BDRC run comes back on the next import.
*   Of the bot workflows, only "Publish submission" and "Re-score all
    submissions" redeploy the site (through `workflow_run` in
    `deploy-pages.yml`). A push made by any other workflow with `GITHUB_TOKEN`
    starts no workflow, so a new removal workflow would leave the old board on
    the site.

**4. Submissions fail for avoidable reasons, and scores lack context.**

*   Common Hugging Face links (`/blob/` pages, `?download=true`) do not match
    the allow-list in `tools/fetch.py` and are rejected.
*   If scoring crashes outside the scorer's own checks (a `pip install`
    outage, a runner failure), the issue gets no reply at all.
*   The board does not mark an entry that covers only some of the 472 pages. A
    missing page counts as CER 1.0 (BDRC's rule), so in the main table a
    partial file looks like a weak model. (The bot reply and the board's Pages
    column already show the count.)
*   The reply does not put a new score in context: where it would rank, and
    how many pages match the ground truth exactly, which is a sign of a copied
    ground truth.

## Goals

Each goal states how it will be checked.

1.  **The published file is the reviewed file.** Publishing happens only if the
    SHA-256 of the newly downloaded bytes equals the hash in the bot's score
    reply. Check: in a fork, a file whose bytes change at its link after
    scoring, with no issue edit, is refused when the issue is closed; the issue
    is reopened with a reply, and nothing is committed.
2.  **A maintainer publishes or rejects with GitHub's Close button and always
    sees the result.** Closing as completed publishes, or reopens the issue with
    the reason. Closing as not planned rejects. No label is added or removed by
    hand. Check: a test for each publish outcome in the Publish outcomes table,
    and a run of each in a fork.
3.  **Any entry can be deleted from the GitHub web UI, and stays deleted.**
    This covers `issue-*` and `bdrc-*` entries, through the "Delete submission"
    workflow. Check: in a fork, a deleted `bdrc-*` entry is still gone after
    `python -m tools.import_bdrc_runs`.
4.  **Every workflow commit redeploys the site.** Bot commits go through
    `apply-and-push.sh`, which starts `deploy-pages.yml` after a successful
    push. Check: no workflow runs `git push` except through the script, and a
    delete run in a fork updates the live page.
5.  **Partial entries are marked.** The board tags an entry whose coverage is
    below 472 pages. Check: with today's data the tag appears on exactly the
    entries whose `coverage < n` (21 of 47), and
    `python -m tools.build_leaderboard --rescore` changes no `mean_cer` value.
6.  **Maintainers see where a new score would land.** The score reply shows the
    rank it would take ("would rank #k of N") and the number of pages with CER
    exactly 0. Check: a test reply for a fixture result shows both rows with the
    expected numbers. There are no thresholds; the maintainer judges.
7.  **Fewer submissions fail for avoidable reasons.** `/blob/` and
    `?download=true` links are accepted, a scoring crash still gets a reply,
    and the error reply lists numbered fix steps. Check: unit tests for both
    link forms and for the fallback reply.
8.  **Stay serverless.** GitHub Pages plus GitHub Actions only. Check: no
    workflow uses a secret other than `GITHUB_TOKEN`, and `site/` makes no
    authenticated request (a search for `Authorization` and `token` in `site/`
    finds nothing).

## Non-Goals

*   **A hosted backend, login system or database.** Rejected because of
    hosting and upkeep cost.
*   **Creating the issue for the participant.** That needs a token on a server,
    the API cannot attach files, and the issue would be authored by a bot. The
    participant always clicks submit on GitHub with their own account.
*   **Submitting without a GitHub account.**
*   **A submission page on the site.** Deferred; see Future Improvements.
*   **Comment commands such as `/approve`.** Deferred; see Future Improvements
    and Alternative E.
*   **Any label step for maintainers.** The `approved` label is removed, and no
    status labels are added. The `submission` label stays, because the issue
    form adds it automatically and the workflows filter on it.
*   **An archive, hidden state or restore command.** Reject before
    publication, delete after. To undo a delete: for an `issue-*` entry, reopen
    the issue and close it as completed; for a `bdrc-*` entry, a maintainer with
    a local checkout restores the folder, removes its record, rebuilds and
    pushes.
*   **Participants deleting or withdrawing published entries.** They ask a
    maintainer in the issue. A submitter who closes their own open issue
    publishes nothing.
*   **Updating a published entry in place.** The submitter opens a new
    submission; the maintainer publishes it and deletes the old entry. The
    README maintainer guide says so.
*   **Changing BDRC's scoring rule** (missing page = CER 1.0) or rejecting files
    for low coverage.
*   **Judging submissions automatically.** The rank and exact-match rows are
    facts for the maintainer and never change the verdict.
*   **Proving a submission is honest.** With a public ground truth this cannot
    be done. Maintainer review, backed by the hash check, stays the safeguard.
*   **Removing a file from git history.** Deleting removes an entry from the
    board, not from the repository history or from old Pages builds. A legal
    takedown needs a history rewrite done by hand.

## Open Questions

None. The open questions about issue-form prefill limits belonged to the
submission page and move with it to Future Improvements.

## Critical User Journeys (CUJs)

### CUJ 1: A participant submits a file

*   **Given**: A participant has a predictions CSV, or a Hugging Face or gist
    link to one, and a GitHub account.
*   **When**: They open the issue form from the site's "Submit your model"
    button, fill it in, attach the CSV or paste the link, and submit.
*   **Then**: Within minutes, one bot reply appears. Its first line says the
    status ("Ready for review" or "Could not be scored"), followed by the CER,
    coverage, the rank the entry would take, the number of exact-match pages,
    the file's short hash and the time it was scored. A Hugging Face `/blob/`
    link or a link ending in `?download=true` works like a `/resolve/` link.

### CUJ 2: A participant fixes a failed file

*   **Given**: An open submission whose bot reply says the file could not be
    scored.
*   **When**: The participant edits the first post of the issue with a new file
    or link, following the numbered steps in the bot reply.
*   **Then**: The bot updates the same reply in place with the new result and
    the new hash.

### CUJ 3: A maintainer publishes a submission

*   **Given**: An open submission whose bot reply says "Ready for review".
*   **When**: The maintainer clicks **Close issue** (close as completed).
*   **Then**: The workflow downloads the file again, checks its hash against the
    score reply, writes `submissions/issue-<n>/`, rebuilds the board, commits,
    and replies "Published as `issue-<n>`". The site redeploys. If anything
    stops the publish (not scored yet, a file the bot could not score, a
    changed file, a failed push), the bot reopens the issue and replies with
    the reason. Nothing is reported as published unless it was pushed.

### CUJ 4: A maintainer rejects a submission

*   **Given**: An open submission.
*   **When**: The maintainer writes the reason in the comment box and chooses
    **Close with comment → Close as not planned**.
*   **Then**: The issue is closed with the reason. The bot does nothing.

### CUJ 5: A maintainer deletes a published entry

*   **Given**: A published entry, either `issue-<n>` or `bdrc-<run_id>`.
*   **When**: The maintainer runs the "Delete submission" workflow from the
    Actions tab with the entry id and a reason.
*   **Then**: The folder is removed, the id is added to
    `submissions/_removed.json` with the reason and issue number, the board is
    rebuilt and committed, and the site redeploys. The run summary names the
    deleted model. A later BDRC import does not bring the entry back.

## Technical Plan (Architecture)

### Shape of the system

Nothing new runs outside GitHub. The site stays static, all writes happen in
Actions with `GITHUB_TOKEN`, and the repository is the only state.

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

### Where state lives

Each state is read from one place. No labels are read.

| State | Read from |
| --- | --- |
| Not ready | Open issue; no bot score marker yet, or the marker has `verdict=error` |
| Ready for review | Open issue; the marker has `verdict=ok` |
| Published | Folder `submissions/issue-<n>/` exists |
| Closed, not on board | Issue closed, no folder (rejected, deleted, or closed by the submitter) |

Maintainers find the review queue with the issue filter
`is:open label:submission`.

**Trusting the score marker.** Only the score reply carries the marker, and the
marker is the exact first line of that reply. The workflow fetches only
comments whose author is `github-actions[bot]`. Python reads the first line of
each and accepts it only if the whole line matches `MARKER_RE`. A marker
anywhere else in a comment is ignored, so file content that the bot repeats in
an error message (header names, unknown ids) cannot plant one. If more than one
bot comment starts with a valid marker, the one with the latest `updated_at`
wins. `render_error` also escapes the scorer's message with `md()` (the existing
helper in `tools/submission.py` that escapes markdown and `@`-mentions).

**What the hash covers.** The marker records `sha256` of the downloaded CSV
bytes. Metadata (model, team, links) is not hashed: it changes only through an
issue edit, every edit triggers a re-score, and the re-score replaces the
marker, so the accepted risk in Decision D1 already covers it.

### Scoring (`score-submission.yml`, `tools/submission.py`)

*   `score` computes the CSV hash and a verdict, `ok` or `error`. A download
    failure is an `error` like any other, but its message (from `download()` in
    `tools/fetch.py`) says that the file could not be fetched and may not be
    wrong: for 401 and 403, that the repository may be gated or private; for
    timeouts, connection errors, 429 and 5xx, that the problem is probably
    temporary and a maintainer can re-run the job.
*   The reply's first line is the marker. Next comes a status line ("Ready for
    review" or "Could not be scored"), then the existing result table with its
    coverage row, the first 12 hex characters of the CSV hash and the time it
    was last scored. Stage 3 adds the rank and exact-match rows.
*   The error reply ends with numbered fix steps: edit the first post of the
    issue, replace the file or link, save; the bot scores it again and updates
    the reply.
*   The workflow keeps one bot score reply per issue. `score` finds the earlier
    one with `latest_marker` and writes its id to `$GITHUB_OUTPUT`; the
    workflow edits that comment, or creates one if there is none.
*   The reply step runs with `if: always()`. If no reply file exists (scoring
    crashed outside the scorer's own checks), it posts "Scoring failed because
    of a problem on our side, not your file. A maintainer can re-run the job;
    editing the issue also scores it again." with a link to the run.
*   Recovery after a temporary failure: a maintainer clicks "Re-run jobs" on
    the failed run, or anyone with access edits the issue. "Re-run jobs" uses
    the workflow file of the original run, so after a release only an edit
    picks up the new code.

### Publishing (`publish-submission.yml`, `tools/submission.py`)

**Trigger.** `issues: closed`. The job runs only if the issue has the
`submission` label and `github.event.issue.state_reason` is `completed`. Every
other closed issue in the repository, and every issue closed as not planned or
as a duplicate, is skipped with no output.

**Permissions.** The existing write-access check stays: it reads the
collaborator `.permission` field, which reports the `maintain` role as `write`,
and accepts `admin` and `write`. Someone without write access can close only
their own issue, so that case is the submitter withdrawing: the bot replies
"Closed by the submitter; nothing was published." and stops.

**Publishing.** For a maintainer, the workflow runs
`python -m tools.submission publish` through `apply-and-push.sh`. On the fresh
tree, `publish` reads the state, downloads the file, compares its hash with the
score marker, writes `submissions/issue-<n>/` and rebuilds the board.

**Publish outcomes.** The reply and the issue's final state depend on the
script's `result` (defined in item 3):

| Case | `publish` exit | `result` | Reply | Issue ends |
| --- | --- | --- | --- | --- |
| Published | 0 | `committed` | "Published as `issue-<n>`", using `render_result(..., published=True)` | closed |
| Already published (folder exists) | 0 | `unchanged` | "Already published as `issue-<n>`" | closed |
| No score marker yet | 10 | `refused` | "Not scored yet. Wait for the bot's reply, then close the issue again." | reopened |
| Verdict is `error` | 10 | `refused` | "The file could not be scored; see the bot's reply." | reopened |
| Hash mismatch | 10 | `refused` | The D1 refusal text | reopened |
| 5 failed pushes | (any) | `push_failed` | "Nothing was published: the push failed 5 times. Close the issue again to retry." | reopened |
| Any other failure | 1 | `error` | "Publishing failed; see <run link>." | reopened |

The reply step and the reopen step run with `if: always()`, so a failure in an
earlier step still ends in a reply and an open issue. The reply file that
`publish` writes is posted only for `committed`, `unchanged` and `refused`, so
a failed push is never reported as published.

**Committing safely.** A shared script, `.github/scripts/apply-and-push.sh`,
runs the change in a loop, up to 5 times: fetch `origin/main`,
`git reset --hard origin/main`, run the Python step again on the fresh tree
(which re-checks the state, so a second close of a published issue finds the
folder and changes nothing), regenerate `leaderboard.json` and the README
table, commit, push. Running the whole step again, and not only rebasing,
means derived files never conflict. After a successful push the script starts
`deploy-pages.yml`. `rescore-all.yml` and `delete-submission.yml` use the same
script.

**Every run writes a summary.** Each publish run writes a
`$GITHUB_STEP_SUMMARY` with the closer, the case from the table above, and the
entry id.

#### Decision D1: what publishing is bound to

**Option A (chosen): bind to the latest score reply.** Closing takes no
argument. Publishing downloads the file again and compares its hash with the
latest bot score marker. On a mismatch it refuses with this reply: "The file at
the link changed after it was scored, and the issue was not edited, so nothing
scored the new file. Ask the submitter to link a pinned revision (a Hugging
Face commit or a gist revision) and edit the issue; the bot will score it
again."

*   **What this catches:** any change after the last scoring with no issue
    edit, such as a Hugging Face `main` link that now serves different bytes,
    or a gist without a pinned revision.
*   **Accepted risk:** the score reply is updated in place on every issue edit.
    If a submitter edits the issue after the maintainer reads the reply and
    before they close the issue, the new file is published without review.
    The maintainer's protection is to check the reply just before closing:
    GitHub shows an "edited" marker with an edit history on the bot comment,
    and the reply prints the time it was last scored. A late swap is visible
    but not blocked. This design accepts that at the current volume of one
    maintainer and a few submissions.

#### Decision D2: how publish and delete runs are queued

**Option C (chosen): no concurrency group on publish and delete runs; git is
the only lock.**

*   **Why a group is not used.** A shared group can cancel a pending run (see
    Problem 1), which would close an issue with no reply.
*   **Mechanism.** `publish-submission.yml` and `delete-submission.yml` have no
    `concurrency` block. Every run starts at once. `apply-and-push.sh` resets to
    the latest `origin/main` before each attempt, and the Python step re-reads
    the state from that fresh tree, so the run that pushes second sees the
    first one's result.
*   **Re-score moves to its own group.** `rescore-all.yml` moves from the shared
    `publish` group to `concurrency: group: rescore`, so two re-scores never
    overlap. If a publish pushes while a re-score is running, the re-score's
    push is rejected and the whole re-score runs again on the fresh tree. That
    costs minutes per retry, and is accepted because re-scores are rare and
    started by hand.
*   **Retry limit.** After 5 failed pushes the run stops, nothing is
    committed, the issue is reopened, and the reply says to close it again.

### Deletion (`tools/manage.py`, `delete-submission.yml`)

*   `submissions/_removed.json` holds `{"removed": [{"id", "reason",
    "issue"}]}`, sorted by id. The delete commit records the date, and its
    message names the person who ran the workflow.
    `build()` ignores the file, because it reads only folders.
*   `python -m tools.manage delete <id> --reason <text> --actor <login>`
    checks the id against `^(issue-\d+|bdrc-[\w.-]+)$`, checks that the folder
    exists and the id is not already removed, removes the folder, appends the
    record and calls `build()`.
*   `tools/import_bdrc_runs.py` drops removed runs before it picks the best run
    per (engine, model) and before any download, so the next-best run can take
    a removed run's place, and its "imported N runs" count stays right.
*   `delete-submission.yml` (`workflow_dispatch` with inputs `id` and `reason`)
    passes both through environment variables, uses `apply-and-push.sh`, and
    prints the deleted model's name in the step summary.
*   Publishing an `issue-<n>` that has a removed record drops the record in the
    same commit, so reopening and closing a deleted issue publishes it again.

### Redeploying (`deploy-pages.yml`)

`apply-and-push.sh` runs `gh workflow run deploy-pages.yml --ref main` after
each successful push. So only runs that changed `main` deploy, whatever later
steps do. `deploy-pages.yml` already accepts `workflow_dispatch`, checks out
`main`, and uses the `pages` concurrency group, which keeps one pending deploy
of the latest `main`. The `workflow_run` trigger is removed. The cost:
committing workflows need `actions: write`, and the deploy is started from a
script, not declared as a trigger; the header comment of `deploy-pages.yml`
says so. Human pushes to `site/**` and `leaderboard/**` still deploy through
the existing `push` trigger.

### Rank and exact matches (Stage 3)

*   `render_result` adds two rows: "Would rank #k of N", where k is one more
    than the number of board entries with a lower `mean_cer` and N is the
    number of entries plus one, and "Pages with CER exactly 0: m", counted from
    `per_page` over pages whose reference text is not empty. An empty or
    missing `leaderboard.json` gives "Would rank #1 of 1". `scorer/score.py`
    does not change.
*   The board shows a "partial (<coverage>/472)" tag, next to the existing
    "older version" tag, on entries whose `coverage` is below `n` (the page
    count, 472). Today that is 21 of 47 entries.

## Alternatives Considered

The alternatives are grouped by the question they answer. The author made
each decision below; each entry gives the reason.

### Overall architecture

#### Alternative A: A hosted web app with logins and a database

*   **Pros**: Full control of the submission form; real accounts; no GitHub
    knowledge needed; files could be uploaded directly.
*   **Cons**: Hosting cost and upkeep for one maintainer; a database and an
    auth system to secure; the repository would stop being the only record.
*   **Reason for Rejection**: Hosting and maintenance cost, and it gives up the
    serverless model.

#### Alternative B: Create the issue automatically from the static site

*   **Pros**: One click for the participant; no GitHub form to fill in.
*   **Cons**: Needs a token kept on a server or proxy; the GitHub API cannot
    attach files to issues; issues would be authored by a bot, losing the
    submitter's identity; the endpoint would need spam protection.
*   **Reason for Rejection**: It needs a server-side token, which breaks Goal
    8, and loses who submitted.

#### Alternative C: Publish entries at once with a "pending review" tag

*   **Pros**: Entries appear within minutes; less waiting on the maintainer.
*   **Cons**: An unreviewed, possibly faked result appears on the public board.
*   **Reason for Rejection**: It gives up the guarantee that nothing appears on
    the board unreviewed.

### Approving

#### Alternative D: Keep label approval and fix its failures

*   **Pros**: Small change: drop the `submission` clause, always reply, add the
    hash check.
*   **Cons**: Maintainers still add and remove labels, and retrying means
    removing and re-adding `approved`. Labels cannot carry a reason, so
    rejecting still needs another path.
*   **Reason for Rejection**: The label handling is the part that makes the
    process hard to run. Closing the issue is one click that every GitHub user
    already knows, and "Close as not planned" with a comment carries the reject
    reason.

#### Alternative E: Comment commands (`/approve`, `/reject <reason>`, `/delete <reason>`)

*   **Pros**: Explicit; a typed command is harder to trigger by accident than a
    Close click; deletion could start from the issue.
*   **Cons**: A parser, a workflow that runs on every comment, a permission
    check before each reply, a `/help` command, and a state × command rules
    table with its tests.
*   **Reason for Rejection**: Too much machinery for a few submissions a year.
    Kept as a Future Improvement.

#### Alternative F: Approval through a pull request

*   **Mechanism**: The bot pushes a snapshot of the CSV to a branch and opens a
    PR. Merging approves, closing rejects, reverting deletes.
*   **Pros**: Approval is tied to an exact commit, so the reviewed file is the
    published file by construction.
*   **Cons**: PRs opened with `GITHUB_TOKEN` do not trigger CI; a repository
    setting must allow Actions to open PRs; the issue and the PR must be kept
    in sync.
*   **Reason for Rejection**: Less machinery (no PRs opened by `GITHUB_TOKEN`,
    no repository setting, no issue/PR sync), at the cost of the gap accepted
    in D1. F closes that gap by construction; the hash check does not.

#### Alternative G: The maintainer quotes the short hash when approving (D1, Option B)

*   **Pros**: Closes the gap between reading the reply and approving, because
    the maintainer names the file they reviewed.
*   **Cons**: Needs a comment with the hash, so approval is no longer one click;
    a maintainer who copies without reading gets no real protection.
*   **Reason for Rejection**: One extra step on every approval, to close a gap
    that D1 accepts at current volume.

#### Alternative H: Refuse to publish after a recent re-score (D1, Option C)

*   **Pros**: No new step; catches most timed edits.
*   **Cons**: Any fixed window is wrong both ways: a tab left open longer
    passes, and an honest quick approval after a fix is refused.
*   **Reason for Rejection**: Any fixed window refuses honest quick approvals
    and passes slow late swaps.

### Queueing runs

#### Alternative I: One concurrency group per issue (D2, Option A)

*   **Pros**: Runs on different issues are never dropped; runs on one issue
    never overlap.
*   **Cons**: Two quick events on the same issue can still cancel the earlier
    run before it replies.
*   **Reason for Rejection**: Running every event and letting git order them
    drops nothing, and the state re-check already handles duplicates.

#### Alternative J: One shared `publish` group (D2, Option B)

*   **Pros**: Runs never overlap, so pushes almost never race.
*   **Cons**: Pending runs can be cancelled (see Problem 1).
*   **Reason for Rejection**: A lost run with no reply is the silent failure
    this design exists to remove.

### Removing entries

#### Alternative K: An archive (hidden) state with a restore command

*   **Pros**: Reversible from the GitHub UI for every entry.
*   **Cons**: A status field in every entry, a restore path, and a choice
    between hiding and showing on the site; more states to test.
*   **Reason for Rejection**: Deleting is rare, `issue-*` entries can already be
    restored by reopening and closing, and a `bdrc-*` restore by hand is
    acceptable at this volume.

#### Alternative L: Participants withdraw their own published entries

*   **Pros**: Submitters can remove their own entries without waiting.
*   **Cons**: A second permission rule (the issue author); entries could
    disappear after a dispute without a maintainer seeing it.
*   **Reason for Rejection**: Both costs above, for a request a maintainer can
    handle in the issue.

#### Alternative M: Closing a reopened published issue updates the entry

*   **Pros**: The entry keeps its id and issue.
*   **Cons**: Needs a "re-review" state, rules for reopening, and a way to
    replace a folder in place.
*   **Reason for Rejection**: A new submission plus deleting the old entry
    needs no extra state.

### Checking files

#### Alternative N: A 90% minimum-coverage gate

*   **Pros**: Keeps partial files off the board.
*   **Cons**: Eight BDRC reference runs are below 425 of 472 pages, and
    `--rescore` has no error handling, so the "Re-score all" workflow would
    stop and commit nothing. It also departs from BDRC's rule.
*   **Reason for Rejection**: Partial entries are tagged instead (Goal 5).

#### Alternative O: Threshold-based review hints

*   **Mechanism**: Flag a submission when its exact-zero share, Tibetan
    character share or reproduced placeholder letters pass a threshold.
*   **Pros**: Points a maintainer at likely fakes without reading numbers.
*   **Cons**: The thresholds need calibration against the 46 BDRC runs and
    drift as models improve (the current #1 already has 68 of 472 pages at CER
    0); the scorer's result schema grows.
*   **Reason for Rejection**: At a few submissions a year the maintainer reads
    every reply, and the rank and exact-match rows give the same information
    with nothing to tune.

### Submitting

#### Alternative P: Build a submission page now

*   **Mechanism**: A page on the site checks the CSV in the browser and opens a
    prefilled issue form.
*   **Pros**: Participants find bad files before the issue exists.
*   **Cons**: A JavaScript copy of the CSV rules with parity tests against
    Python, a generated copy of the form, prefill limits to measure, and
    changes to the site's link handling.
*   **Reason for Rejection (for now)**: The community is small, and the link
    rewrites and numbered fix steps remove the most common avoidable failures.
    Kept as a Future Improvement, with the evidence that would bring it back.

## Non-Functional Requirements

*   **Security.**
    *   The `issues` workflows run from the default branch with a write token,
        on issues anyone can open. Issue text, ids and reasons reach scripts
        only through environment variables, never through `${{ }}` inside
        `run:`.
    *   Only the first line of comments by `github-actions[bot]` is read for
        score markers, and submitter text in bot replies is escaped.
    *   Publishing checks the closer's `.permission` (admin or write) before
        any write to the repository.
    *   Entry ids from `workflow_dispatch` must match
        `^(issue-\d+|bdrc-[\w.-]+)$` and name an existing folder before any
        file is touched.
*   **Performance.** No critical latency. A publish run takes about one minute
    (an estimate), mostly `pip install`. A re-score that loses a push race runs
    again in full (Decision D2).
*   **Rollout.** Stages 1 to 3 are one pull request each, released in order.
    After Stage 1 is released, a maintainer edits the title of each open
    submission so it is scored again and gets a marker; an open issue without
    a marker cannot be published (closing it reopens it with "Not scored yet").
*   **Rollback.**
    *   Each stage is reverted with `git revert` of its merge commit.
    *   Reverting Stage 1 brings back label approval; the `approved` label must
        be re-created by hand.
    *   Reverting Stage 2's change to `tools/import_bdrc_runs.py` makes the
        next BDRC import bring back every deleted `bdrc-*` entry. Revert it
        only together with a manual check of `submissions/_removed.json`.
    *   A wrong delete is undone as described in Non-Goals.

## Risks & Mitigations

| Risk | Type | Impact | Mitigation |
| --- | --- | --- | --- |
| A maintainer closes as completed by habit, meaning to reject | Process | An entry is published | The reply says so at once; undo with the Delete workflow. Rejecting has its own option. |
| A file is swapped between review and closing | Security | An unreviewed file is published | Hash check (Goal 1); the edit-window gap is accepted (D1) |
| A forged score marker | Security | A bad file is published | Marker read only from the first line of bot comments (Trusting the score marker) |
| Write token on events anyone can cause | Security | Script injection | Event text only through `env` (Security) |
| Hugging Face rate limits during a re-score retry | Availability | A re-score fails | Accepted: re-scores are rare and started by hand (D2) |
| A download fails during scoring | Availability | The submitter sees an error | The message says it is temporary; re-run or edit the issue (Scoring) |
| Git history grows by up to 20 MiB per entry | Scale | Slower clones | Accepted; see Future Improvements |

## Future Improvements

*   **A submission page.** A page that checks the CSV in the browser and opens
    a prefilled issue form. Pick it up if participants report trouble with the
    issue form, or if several first attempts cannot be scored. The review of
    the earlier draft settled its shape: check local files only (links go
    straight to the issue form); compare only pass/fail and coverage with
    Python on shared fixtures generated by the Python parser; generate the
    page's copy of the form from `submission.yml`; read page ids from
    `scorer/data/pages.csv` with the standard library; and update
    `configureRepo()` in `site/app.js`, which rewrites every
    `[data-issue-link]` link at page load. Measure the issue form's prefill
    limits first.
*   **Comment commands** (Alternative E). Pick them up if deleting from the
    issue, or explicit commands, become worth the machinery. The review settled
    their shape: four states (not ready, ready, published, closed); a rules
    table for each command in each state; a job-level filter on comments
    starting with `/`, then the permission check, then a reply to every
    maintainer comment (help text for anything that is not a command); and
    every command, including reject, run through `apply-and-push.sh`.
*   **Rebuild the board on any push to `submissions/**`, or build
    `leaderboard.json` at deploy time.** Deletion could then also be done by
    deleting a folder in the GitHub web UI, and derived files would never be
    committed by hand. Not needed for any goal here.
*   **Provenance badges** ("open weights + code", "self-reported"). Needs new
    metadata fields in the issue form and site work.
*   **A soft size budget for stored CSVs.** Each published issue adds up to
    20 MiB to git history permanently. A later option is to keep only
    `meta.json`, `result.json` and the hash on `main`, and store CSV bytes on a
    separate data branch, so a takedown never rewrites `main`.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

Files are grouped by stage. Stages 1 to 3 are one pull request each, released
in order. Paths are relative to the repository root.

### Stage 1: Approval by closing, and safety fixes

#### 1. `tools/fetch.py` (Modify)

*   **Type / Scope**: Python module.
*   **Proposed Changes**:
    *   `find_url` rewrites each URL before `is_allowed`: a
        `https://huggingface.co/.../blob/<rev>/<path>` link becomes
        `.../resolve/<rev>/<path>`, and a `download=true` query parameter is
        dropped. The rewritten URL is the one returned and stored.
    *   `download()` keeps raising `SubmissionError`, with clearer messages:
        401 and 403 say the file may be in a gated or private repository;
        timeouts, connection errors, 429 and 5xx say the download failed,
        probably temporarily, that the file does not need changing, and that a
        maintainer can re-run the job.

#### 2. `tools/submission.py` (Modify)

*   **Type / Scope**: Python module.
*   **Proposed Changes**:
    *   `file_hash(raw: bytes) -> str`: SHA-256 hex.
    *   `MARKER_RE = re.compile(r"^<!-- yigzinbench:score v=1 verdict=(ok|error) sha256=([0-9a-f]{64}|-) scored_at=(\S+) -->$")`.
        `render_marker(verdict, sha256, scored_at) -> str` builds that line.
        For `error` the hash is `-`.
    *   `latest_marker(comments: list[dict]) -> dict | None`: takes
        `{id, body, updated_at}` records, checks only the first line of each
        body against `MARKER_RE`, and returns the verdict, hash, time and
        comment id from the comment with the latest `updated_at`.
    *   Split `run()` into `score_entry(env) -> (meta, raw, result)` (raises
        `SubmissionError`) and `store_entry(number, meta, raw, result) -> str`
        (writes `submissions/issue-<n>/`, calls `build()`, returns the id).
    *   `render_error` passes the message through `md()` and ends with the
        numbered fix steps from Scoring.
    *   The `score` subcommand writes the reply with the marker as its first
        line, then the status line, the result table, the short hash and the
        scored time. It reads `BOT_COMMENTS_FILE` and, if `GITHUB_OUTPUT` is
        set, appends `verdict=`, `sha256=` and `comment_id=` (empty if there
        is no earlier score reply). It still exits 0 after a
        `SubmissionError`.
    *   The `publish` subcommand reads `BOT_COMMENTS_FILE` and the `ISSUE_*`
        variables that `collect()` reads (`ISSUE_BODY`, `ISSUE_AUTHOR`,
        `ISSUE_CREATED_AT`, `ISSUE_URL`) plus `ISSUE_NUMBER`. In order:
        if the folder exists, write the "already published" reply and exit 0;
        if there is no marker, or the verdict is not `ok`, write the matching
        refusal and exit 10; otherwise run `score_entry`, and if
        `file_hash(raw)` differs from the marker's `sha256`, write the D1
        refusal and exit 10; otherwise run `store_entry` and write the
        published reply with `render_result(meta, result, published=True)`.
        Exit 0. Any other exception exits 1. The reply texts are those in the
        Publish outcomes table.

#### 3. `.github/scripts/apply-and-push.sh` (Create)

*   **Type / Scope**: Bash script used by every committing workflow.
*   **Proposed Changes**: Run as `bash .github/scripts/apply-and-push.sh
    <commit message> -- <command...>`. The command follows one exit-code
    contract: 0 = done (files may or may not have changed), 10 = refused on the
    fresh tree, anything else = error. Up to 5 attempts, each:
    1.  `git fetch origin main`, `git reset --hard origin/main`,
        `git clean -fd submissions leaderboard`.
    2.  Run the command. On 10: write `result=refused` to `$GITHUB_OUTPUT` and
        exit 0. On any code other than 0 or 10: write `result=error` and exit
        1.
    3.  `git add submissions leaderboard README.md`. If nothing is staged:
        write `result=unchanged` and exit 0.
    4.  Commit as `github-actions[bot]`, then `git push origin HEAD:main`. On
        success: run `gh workflow run deploy-pages.yml --ref main`, write
        `result=committed`, and exit 0. On any push failure: wait a random 2
        to 5 seconds and start the next attempt.

    After 5 failed pushes: write `result=push_failed` and exit 1. Workflows
    that call the script need `permissions: contents: write, actions: write`
    and `GH_TOKEN` set.

#### 4. `.github/workflows/score-submission.yml` (Modify)

*   **Type / Scope**: GitHub Actions workflow.
*   **Proposed Changes**:
    *   Before scoring, fetch bot comments once:
        `gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/issues/$ISSUE_NUMBER/comments" | jq '[.[][] | select(.user.login == "github-actions[bot]") | {id, body, updated_at}]' > "$RUNNER_TEMP/bot_comments.json"`,
        passed to `score` as `BOT_COMMENTS_FILE`.
    *   The score step gets `id: score`.
    *   The reply step runs with `if: always()`. If the reply file is missing,
        it writes the fallback text from Scoring with the run link. If
        `steps.score.outputs.comment_id` is set, it edits that comment with
        `gh api -X PATCH`; otherwise it creates a comment.
    *   Write `$GITHUB_STEP_SUMMARY` with the verdict and short hash.

#### 5. `.github/workflows/publish-submission.yml` (Modify)

*   **Type / Scope**: GitHub Actions workflow, `name: Publish submission`.
*   **Proposed Changes**:
    *   `on: issues: types: [closed]`.
    *   `permissions: contents: write, issues: write, actions: write`. Remove
        the `concurrency` block (Decision D2). Keep `timeout-minutes: 15`.
    *   Job `if:`: `github.event.issue.state_reason == 'completed' &&
        contains(github.event.issue.labels.*.name, 'submission')`.
    *   Steps, in order:
        1.  `perm`: the existing write-access check, changed to write
            `allowed=true|false` to `$GITHUB_OUTPUT` instead of failing.
        2.  If not allowed: reply "Closed by the submitter; nothing was
            published." Every later step except the summary has
            `if: steps.perm.outputs.allowed == 'true'` (combined with
            `always()` where noted).
        3.  `actions/checkout`, `actions/setup-python`,
            `pip install -r scorer/requirements.txt`.
        4.  Fetch bot comments (the command in item 4).
        5.  `apply` (id `apply`): `bash .github/scripts/apply-and-push.sh
            "Publish submission #<n> (closed by <login>)" -- python -m
            tools.submission publish
            --comment "$RUNNER_TEMP/reply.md"`, with the `ISSUE_*` variables
            and `BOT_COMMENTS_FILE` in `env`.
        6.  Reply, `if: always()`: post `reply.md` when `result` is
            `committed`, `unchanged` or `refused`; otherwise post the
            `push_failed` or failure text from the Publish outcomes table.
        7.  Reopen, `if: always()`: `gh issue reopen` unless `result` is
            `committed` or `unchanged`.
        8.  Summary, `if: always()`: the closer, the case and the entry id.
    *   Remove the old "Score and store", "Commit" and "Close issue" steps.

#### 6. `.github/workflows/rescore-all.yml` (Modify)

*   **Type / Scope**: GitHub Actions workflow.
*   **Proposed Changes**: Change `concurrency.group` from `publish` to
    `rescore`. Add `actions: write` to `permissions`. Replace the `--rescore`
    step and the "Commit" step with one step:
    `bash .github/scripts/apply-and-push.sh "Re-score all submissions" --
    python -m tools.build_leaderboard --rescore`. The script runs the re-score
    on each attempt.

#### 7. `.github/workflows/deploy-pages.yml` (Modify)

*   **Type / Scope**: GitHub Actions workflow.
*   **Proposed Changes**: Remove the `workflow_run` trigger and the build job's
    `if:` that checks its conclusion. Rewrite the header comment: bot commits
    start this workflow through `apply-and-push.sh` (`workflow_dispatch`),
    because pushes made with `GITHUB_TOKEN` start no workflow.

#### 8. `tests/helpers.py` (Create)

*   **Type / Scope**: Shared test helper.
*   **Proposed Changes**: `temp_repo()`, a context manager that copies
    `submissions/` to a temporary folder and patches
    `tools.build_leaderboard.SUBMISSIONS`, `.OUTPUT` and `.ROOT`, and each
    module's own `SUBMISSIONS` (`tools.submission`, and from Stage 2
    `tools.import_bdrc_runs` and `tools.manage`). It also patches
    `tools.submission.download` and `tools.import_bdrc_runs.download` to read
    local fixture bytes. No test writes the real `leaderboard/` or
    `README.md`, or uses the network.

#### 9. `tests/test_submission.py` (Create)

*   **Type / Scope**: Unit tests, using `temp_repo()`.
*   **Proposed Changes**:
    *   `find_url`: a `/blob/` link and a `?download=true` link are accepted
        and become the `/resolve/` URL.
    *   Marker round trip; `latest_marker` picks the latest `updated_at`; a
        marker that is not on the first line is ignored; a CSV whose header is
        a full marker line produces an error reply that `latest_marker` does
        not read as `verdict=ok`.
    *   `score` writes the marker as the first line and the `verdict=`,
        `sha256=` and `comment_id=` lines to a temporary `$GITHUB_OUTPUT`; a
        download failure gives `verdict=error` with the temporary-failure
        message; the error reply ends with the numbered steps.
    *   `publish`, one test per row of the Publish outcomes table that
        `publish` decides (published, already published, no marker, verdict
        `error`, hash mismatch), checking the exit code, the reply, and
        whether anything was written to `submissions/`.

#### 10. `tests/test_apply_and_push.py` (Create)

*   **Type / Scope**: Script tests.
*   **Proposed Changes**: Run the script against a local bare repository used
    as `origin`, with `gh` replaced by a stub on `PATH` that records its
    arguments. Cases: a clean push gives `committed` and one deploy dispatch;
    exit 10 gives `refused` and no commit; nothing staged gives `unchanged`;
    a push rejected once (another clone pushes first) succeeds on attempt 2;
    5 rejections give `push_failed` and exit 1.

#### 11. `README.md`, `tools/README.md` (Modify)

*   **Type / Scope**: Documentation.
*   **Proposed Changes**:
    *   Rewrite the README maintainer guide around a table: publish = Close
        issue; reject = write the reason, then Close as not planned; retry
        after a refusal = Close issue again; delete = the Actions workflow
        (Stage 2); undo = reopen and close. Add "check the score reply just
        before closing" (the D1 risk), how to find the review queue, how to
        handle an update (publish the new issue, delete the old entry), and how
        to recover a failed score (re-run, or edit the issue).
    *   Remove the `approved` label from the setup steps, the process diagram
        and the note from commit `f7341f4` about needing both labels.
    *   Document in `tools/README.md` the marker, `score_entry`/`store_entry`,
        the `publish` exit codes, the link rewrites and `apply-and-push.sh`.

#### 12. Manual release steps

*   **Type / Scope**: One-off steps, not a file.
*   **Proposed Changes**:
    *   After merging, run `gh label delete approved --yes`.
    *   Edit the title of each open issue with the `submission` label, so it
        is scored again and gets a marker.

### Stage 2: Deletion

#### 13. `tools/build_leaderboard.py` (Modify)

*   **Type / Scope**: Python module.
*   **Proposed Changes**: `removed_ids() -> set[str]` reads
    `SUBMISSIONS / "_removed.json"`, building the path when called; a missing
    file means an empty set. `build()` and `--rescore` do not change.

#### 14. `tools/import_bdrc_runs.py` (Modify)

*   **Type / Scope**: Python module.
*   **Proposed Changes**: Drop rows whose `bdrc-<run_id>` is in
    `removed_ids()` before the loop that picks the best run per (engine,
    model), and print `skipped (removed): <id>` to stderr for each. A removed
    run is never downloaded, the next-best run can take its place, and the
    "imported N runs" count covers only imported runs.

#### 15. `submissions/_removed.json` (Create)

*   **Type / Scope**: Data.
*   **Proposed Changes**: `{"removed": []}`. Each record will be
    `{"id", "reason", "issue" (number or null)}`, kept sorted by id, written
    with `indent=2` and a trailing newline.

#### 16. `tools/manage.py` (Create)

*   **Type / Scope**: Python CLI.
*   **Proposed Changes**:
    *   `ID_RE = re.compile(r"^(issue-\d+|bdrc-[\w.-]+)$")`.
    *   `class ManageError(Exception)`: a refusal, with a message for the run
        summary.
    *   `delete_entry(entry_id, reason, issue=None) -> str`: validates the id
        and a non-empty reason of at most 500 characters, checks that the
        folder exists and the id is not removed, removes the folder with
        `shutil.rmtree`, appends the record, calls `build()`, and returns the
        model name. Raises `ManageError` for each refusal.
    *   CLI: `python -m tools.manage delete <id> --reason <text> [--issue <n>]`.
        Exit 0 if deleted, 10 if refused, 1 on any other error. Writes
        `model=` to `$GITHUB_OUTPUT`, and the refusal message to stderr.

#### 17. `tools/submission.py` (Modify)

*   **Type / Scope**: Python module.
*   **Proposed Changes**: `store_entry` removes a `_removed.json` record with
    the same id, so reopening and closing a deleted issue publishes it again.

#### 18. `.github/workflows/delete-submission.yml` (Create)

*   **Type / Scope**: GitHub Actions workflow, `name: Delete submission`.
*   **Proposed Changes**:
    *   `workflow_dispatch` inputs: `id` (string, required) and `reason`
        (string, required).
    *   `permissions: contents: write, actions: write`. No `concurrency` block
        (Decision D2). `timeout-minutes: 15`.
    *   Steps: checkout, Python setup and `pip install -r
        scorer/requirements.txt`, then `bash .github/scripts/apply-and-push.sh
        "Delete $ENTRY_ID (requested by $GITHUB_ACTOR)" -- python -m
        tools.manage delete "$ENTRY_ID"
        --reason "$REASON"`, with the issue number taken from an `issue-<n>`
        id. Inputs go in through `env`.
    *   Summary, `if: always()`: the id, the model name, the reason, and the
        `result`. A `refused` result fails the run with the refusal message,
        so the Actions tab shows it.

#### 19. `tests/test_manage.py` (Create)

*   **Type / Scope**: Unit tests, using `temp_repo()`.
*   **Proposed Changes**:
    *   An invalid id, a missing folder, an already-removed id, an empty
        reason and a reason over 500 characters each exit 10 before anything
        is written.
    *   A good delete removes the folder, adds a sorted record and writes
        `model=`.
    *   `import_bdrc_runs` never downloads a removed run, and picks the
        next-best run for its (engine, model).
    *   Publishing a removed `issue-<n>` drops its record.

#### 20. `README.md`, `tools/README.md` (Modify)

*   **Type / Scope**: Documentation.
*   **Proposed Changes**: Document deleting an entry, and undoing a delete for
    both kinds of entry, in the README maintainer guide. Document
    `_removed.json`, `removed_ids()`, `tools/manage.py` and the import rule in
    `tools/README.md`. Add the Stage 2 rollback warning about
    `import_bdrc_runs.py` to the maintainer guide.

### Stage 3: Rank and exact matches

#### 21. `tools/submission.py` (Modify)

*   **Type / Scope**: Python module.
*   **Proposed Changes**: `render_result` adds the two rows described in "Rank
    and exact matches". It reads the board from
    `tools.build_leaderboard.OUTPUT` and the reference text from
    `load_reference()`, which the scoring run has already loaded.

#### 22. `site/app.js` (Modify)

*   **Type / Scope**: Site JavaScript.
*   **Proposed Changes**: In `modelCell`, add a `tag` span with the text
    `partial (${e.coverage}/472)` when `e.coverage < e.n`, next to the
    existing "older version" tag.

#### 23. `tests/test_submission.py` (Modify)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**: Rank against an empty board, a board of one, and a
    tie; the exact-match count ignores pages whose reference is empty and
    pages that are missing.

#### 24. `site/README.md`, `tools/README.md` (Modify)

*   **Type / Scope**: Documentation.
*   **Proposed Changes**: Document the partial tag in `site/README.md`, and the
    two reply rows in `tools/README.md`.

### Verification Plan

*   **Build**: the deploy job copies `site/` to `_site/` and writes
    `config.json`; there is no other build step. Run the same commands from
    `deploy-pages.yml` locally to preview.
*   **Unit tests**: `pip install -r scorer/requirements.txt`, then
    `python -m unittest discover -s tests -t .`.
*   **Regression**: after Stages 1 and 2, on a clean checkout of the merged
    branch, `python -m tools.build_leaderboard && git diff --exit-code
    leaderboard` shows no change on today's data. After Stage 3,
    `python -m tools.build_leaderboard --rescore && git diff
    leaderboard/leaderboard.json | grep mean_cer` prints nothing.
*   **Static analysis**: none configured in the repository today; not added by
    this design.
*   **End to end, in a fork, per stage**:
    *   Stage 1:
        *   Submit with a `/blob/` link and see it scored.
        *   Submit a CSV whose header is a marker line and see an error reply.
        *   Close a ready issue and see it published, the issue stay closed,
            and the site update.
        *   Close it again after reopening and see "already published".
        *   Close an issue before its score reply and see it reopened with
            "Not scored yet".
        *   Link an unpinned gist, change the gist without editing the issue,
            close the issue, and see the D1 refusal and the issue reopened.
        *   Close your own submission from an account without write access and
            see the "Closed by the submitter" reply.
        *   Close an issue as not planned and see no bot action.
        *   Break a download (a private gist) and see the temporary-failure
            message.
    *   Stage 2: delete a `bdrc-*` entry from the Actions tab, see the site
        update, run `python -m tools.import_bdrc_runs`, and see it stay
        deleted. Delete an `issue-*` entry, then reopen and close its issue,
        and see it published again.
    *   Stage 3: open a submission and see the rank and exact-match rows; see
        the partial tag on 21 entries.
