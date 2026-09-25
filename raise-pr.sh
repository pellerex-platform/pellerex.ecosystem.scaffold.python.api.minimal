#!/bin/bash

# Pushes the CURRENT branch and raises a GitHub PR for it.
#
# Usage:
#   ./raise-pr.sh "Commit and PR title"
#   ./raise-pr.sh "Commit and PR title" "PR body text"
#   ./raise-pr.sh -d "Commit and PR title"
#
# -d / --dry-run prints every command it would run without executing anything.
#
# Behaviour:
#   - Uses the branch you are already on; refuses to run on master/main.
#   - Commits everything pending (git add -A) with the given title.
#   - Unlocks the SSH key once into the ssh-agent, so git never prompts for
#     the passphrase mid-push. The agent holds it in memory; the script never
#     stores it. (Run "ssh-add --apple-use-keychain" once manually if you want
#     macOS to remember it across reboots.)
#   - Pushes to the "gh" remote, falling back to "origin".
#   - Raises the PR with gh against the repo's default branch. With no body
#     given, gh fills the PR body from the commit message.

set -euo pipefail

DRY_RUN=false
if [ "${1:-}" = "-d" ] || [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    shift
fi

TITLE="${1:-}"
BODY="${2:-}"

if [ -z "$TITLE" ]; then
    echo "Usage: $0 [-d] \"Commit and PR title\" [\"PR body\"]"
    exit 1
fi

run() {
    echo "+ $*"
    if [ "$DRY_RUN" = false ]; then
        "$@"
    fi
}

# Make sure the SSH key git will actually use is unlocked in the agent before
# pushing, so the passphrase is asked at most once here and held in the
# agent's memory, never in this script. The key is resolved from the SSH
# config for the remote's host (a bare ssh-add would only load default-named
# keys, prompting for the wrong one when the host uses a specific
# IdentityFile).
ensure_ssh_key() {
    local host identity fingerprint status=0

    # git@github.com:Owner/repo.git -> github.com; an https remote needs no key.
    host=$(echo "$URL" | sed -E 's#^git@([^:]+):.*#\1#')
    if [ "$host" = "$URL" ]; then
        return 0
    fi

    ssh-add -l > /dev/null 2>&1 || status=$?
    if [ "$status" -eq 2 ]; then
        eval "$(ssh-agent -s)" > /dev/null
    fi

    identity=$(ssh -G "$host" | awk '/^identityfile /{print $2; exit}')
    identity="${identity/#\~/$HOME}"

    if [ -f "$identity" ]; then
        # Already unlocked? Compare fingerprints instead of prompting again.
        fingerprint=$(ssh-keygen -lf "$identity.pub" 2>/dev/null | awk '{print $2}')
        if [ -n "$fingerprint" ] && ssh-add -l 2>/dev/null | grep -q "$fingerprint"; then
            return 0
        fi
        echo "Unlocking $identity (asked once, kept by ssh-agent):"
        ssh-add "$identity"
    else
        echo "Unlocking default SSH key (asked once, kept by ssh-agent):"
        ssh-add
    fi
}

BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [ "$BRANCH" = "master" ] || [ "$BRANCH" = "main" ]; then
    echo "You are on $BRANCH. Switch to a feature branch first."
    exit 1
fi

REMOTE="gh"
if ! git config --get "remote.$REMOTE.url" > /dev/null; then
    REMOTE="origin"
fi

URL=$(git config --get "remote.$REMOTE.url")

# git@github.com:Owner/repo.git or https://github.com/Owner/repo -> Owner/repo
REPO=$(echo "$URL" | sed -E 's#^(git@github.com:|https://github.com/)##; s#\.git$##')

# Default branch: ask GitHub (authoritative; local remote-HEAD refs go stale),
# falling back to the local remote HEAD, then master, then main.
BASE=$(gh repo view "$REPO" --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || true)
if [ -z "$BASE" ]; then
    if BASE_REF=$(git symbolic-ref --quiet "refs/remotes/$REMOTE/HEAD"); then
        BASE="${BASE_REF##*/}"
    elif git show-ref --quiet --verify "refs/remotes/$REMOTE/master"; then
        BASE="master"
    else
        BASE="main"
    fi
fi

echo "Repo:   $REPO"
echo "Branch: $BRANCH"
echo "Base:   $BASE"
echo "Remote: $REMOTE"
echo ""

if [ -n "$(git status --porcelain)" ]; then
    run git add -A
    run git commit -m "$TITLE"
else
    echo "Nothing to commit; pushing existing commits."
fi

if [ "$DRY_RUN" = false ]; then
    ensure_ssh_key
fi

# A branch reused across sessions may already exist on the remote with
# commits we do not have locally; merge those in first or the push is
# rejected as a non fast-forward.
echo "+ git fetch $REMOTE $BRANCH (skipped when the branch is not on the remote yet)"
if [ "$DRY_RUN" = false ] && git fetch "$REMOTE" "$BRANCH" 2>/dev/null; then
    run git merge --no-edit FETCH_HEAD
fi

# The org rulesets require PR branches to be up to date with the base branch,
# so merge the base in before pushing. On a conflict the script stops here;
# resolve, commit, and run it again.
run git fetch "$REMOTE" "$BASE"
run git merge --no-edit "$REMOTE/$BASE"

run git push -u "$REMOTE" "$BRANCH"

if [ -n "$BODY" ]; then
    run gh pr create -R "$REPO" --base "$BASE" --head "$BRANCH" --title "$TITLE" --body "$BODY"
else
    run gh pr create -R "$REPO" --base "$BASE" --head "$BRANCH" --title "$TITLE" --fill
fi
