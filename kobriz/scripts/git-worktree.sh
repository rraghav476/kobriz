#!/usr/bin/env bash
# kobriz ADLC — safe git worktree helper (standalone shell interface).
#
# This mirrors a subset of worktree.py for direct shell use and hooks. It is deliberately
# conservative: it validates inputs, never force-removes by default, never resets the
# user's checkout, and refuses obviously-unsafe paths. For full state tracking use
# `python3 adlc.py worktree ...`.
#
# Usage:
#   git-worktree.sh create <repo> <worktree_root> <branch> <base_commit>
#   git-worktree.sh list   <repo>
#   git-worktree.sh remove <repo> <path> [--force]
#   git-worktree.sh clean-check <repo>      # exit 0 if clean, 1 if dirty

set -euo pipefail

die() { printf 'kobriz: %s\n' "$1" >&2; exit 1; }

valid_branch() {
  case "$1" in
    *..*|*' '*|-*|'') return 1 ;;
    *) [[ "$1" =~ ^[A-Za-z0-9._/-]+$ ]] ;;
  esac
}

valid_path() {
  local p="$1"
  [[ -n "$p" && "$p" != "/" && "$p" != "$HOME" ]]
}

cmd="${1:-}"; shift || true

case "$cmd" in
  create)
    repo="${1:?repo required}"; root="${2:?worktree_root required}"
    branch="${3:?branch required}"; base="${4:?base_commit required}"
    [ -d "$repo/.git" ] || git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || die "not a git repo: $repo"
    valid_branch "$branch" || die "invalid branch name: $branch"
    valid_path "$root" || die "unsafe worktree root: $root"
    if git -C "$repo" show-ref --verify --quiet "refs/heads/$branch"; then
      die "branch already exists: $branch"
    fi
    mkdir -p "$root"
    # slug the branch leaf into a directory name
    dir="$root/$(printf '%s' "$branch" | tr '/:' '--')"
    [ -e "$dir" ] && die "worktree path exists: $dir"
    git -C "$repo" worktree add -b "$branch" "$dir" "$base"
    printf '%s\n' "$dir"
    ;;
  list)
    repo="${1:?repo required}"
    git -C "$repo" worktree list --porcelain
    ;;
  remove)
    repo="${1:?repo required}"; path="${2:?path required}"; force="${3:-}"
    valid_path "$path" || die "unsafe path: $path"
    [ -d "$path" ] || die "no such worktree: $path"
    if [ "$force" = "--force" ]; then
      git -C "$repo" worktree remove --force "$path"
    else
      # Refuse if dirty
      if [ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]; then
        die "worktree has uncommitted changes; pass --force to remove: $path"
      fi
      git -C "$repo" worktree remove "$path"
    fi
    ;;
  clean-check)
    repo="${1:?repo required}"
    if [ -n "$(git -C "$repo" status --porcelain)" ]; then
      exit 1
    fi
    exit 0
    ;;
  *)
    die "unknown command: ${cmd:-<none>} (use create|list|remove|clean-check)"
    ;;
esac
