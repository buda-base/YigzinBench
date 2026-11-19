#!/usr/bin/env bash
# Run a mutating command against a fresh origin/main, commit, push, and deploy.
#
# Usage: bash .github/scripts/apply-and-push.sh <commit message> -- <command...>
#
# Command exit codes: 0 = done, 10 = refused on the fresh tree, other = error.
# Writes result=committed|refused|unchanged|push_failed|error to $GITHUB_OUTPUT.
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <commit message> -- <command...>" >&2
  exit 2
fi

MESSAGE=$1
shift
if [[ "$1" != "--" ]]; then
  echo "usage: $0 <commit message> -- <command...>" >&2
  exit 2
fi
shift

write_result() {
  local value=$1
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "result=${value}" >> "$GITHUB_OUTPUT"
  fi
  echo "apply-and-push: result=${value}" >&2
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

for attempt in 1 2 3 4 5; do
  echo "apply-and-push: attempt ${attempt}/5" >&2
  git fetch origin main
  git reset --hard origin/main
  # Drop derived trees so the command rebuilds them from the fresh checkout.
  git clean -fd -- submissions leaderboard >/dev/null 2>&1 || true

  set +e
  "$@"
  status=$?
  set -e

  if [[ $status -eq 10 ]]; then
    write_result refused
    exit 0
  fi
  if [[ $status -ne 0 ]]; then
    write_result error
    exit 1
  fi

  git add submissions leaderboard README.md
  if git diff --cached --quiet; then
    write_result unchanged
    exit 0
  fi

  git commit -m "$MESSAGE"
  set +e
  git push origin HEAD:main
  push_status=$?
  set -e
  if [[ $push_status -eq 0 ]]; then
    # Record committed before deploy dispatch so a dispatch failure cannot
    # reopen an issue whose entry is already on main (RFC open item 3).
    write_result committed
    if ! gh workflow run deploy-pages.yml --ref main; then
      echo "::warning::deploy-pages.yml dispatch failed; entry is on main, deploy manually if needed" >&2
    fi
    exit 0
  fi
  sleep $((2 + RANDOM % 4))
done

write_result push_failed
exit 1
