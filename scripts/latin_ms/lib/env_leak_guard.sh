# shellcheck shell=bash
# Refuse to load a secrets file that git is tracking.
#
# Extracted from run_pipeline.sh so the test suite can exercise THE REAL GUARD.
# The previous test inlined its own copy of the logic, which meant it validated
# a duplicate and could not catch a regression in the shipped code -- and there
# was one to catch (see below).
#
# THIS GUARD MUST FAIL CLOSED. The original was:
#
#   if [[ -f "$ENV_FILE" ]] && git -C "$DIR" ls-files --error-unmatch "$ENV_FILE" ...
#
# which reads EVERY non-zero exit as "not tracked". Two real ways secrets slip:
#
#   1. git not runnable. On this Mac /usr/local/bin/git is a stale x86_64 binary
#      exiting 126 ("Bad CPU type in executable"). The guard read 126 exactly as
#      it reads "clean" and proceeded. It had been silently disabled.
#   2. Tracked but locally deleted. `[[ -f ]]` short-circuits, so a file present
#      in the index but absent from the worktree was never checked -- yet
#      committing still publishes it.
#
# Only exit 1 (git ran; path not in the index) counts as safe. Anything else
# means undeterminable, and undeterminable is not permission to load real keys.
env_leak_guard() {
    local env_file="$1"
    local dir="${2:-$(dirname "$env_file")}"

    local git_bin
    git_bin="$(command -v git || true)"
    if [[ -z "$git_bin" ]] || ! "$git_bin" --version >/dev/null 2>&1; then
        echo "ERROR: cannot run git (${git_bin:-not found}) -- unable to verify that" >&2
        echo "  $env_file" >&2
        echo "is untracked, so refusing to load secrets. Fix git and retry." >&2
        echo "  (a stale /usr/local/bin/git shadowing the system one causes this)" >&2
        return 1
    fi

    # Outside a repo there is nothing to leak into.
    "$git_bin" -C "$dir" rev-parse --git-dir >/dev/null 2>&1 || return 0

    "$git_bin" -C "$dir" ls-files --error-unmatch "$env_file" >/dev/null 2>&1
    local rc=$?
    if [[ "$rc" -eq 0 ]]; then
        echo "ERROR: $env_file is tracked by git -- remove it from the index first:" >&2
        echo "  git rm --cached $env_file" >&2
        return 1
    elif [[ "$rc" -ne 1 ]]; then
        echo "ERROR: git ls-files exited $rc -- could not determine whether" >&2
        echo "  $env_file" >&2
        echo "is tracked. Refusing to load secrets on an inconclusive check." >&2
        return 1
    fi
    return 0
}
