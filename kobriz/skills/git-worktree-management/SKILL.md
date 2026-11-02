---
name: git-worktree-management
description: Create, track, and tear down isolated git worktrees for parallel ADLC tasks. Use whenever a task needs its own branch/worktree, when detecting shared-file conflicts across concurrent tasks, or when cleaning up after integration. Enforces safety rules (no touching the user's dirty checkout, no force by default, failed-worktree retention).
allowed-tools: Bash(python3 *) Bash(git *)
---

# Git Worktree Management

Every independently-executable task runs in its **own worktree + feature branch**. Git is
the source of truth for code. Use the CLI (it tracks state, validates paths/branch names,
and records base commits); drop to raw `git`/`scripts/git-worktree.sh` only for inspection.

## Workflow (per independent task)
```
# create: branch adlc/task-<id>-<kind>-<slug> from the base revision
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree create <id> <slug> --kind <kind> --agent <name>

python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree state  <id> IN_PROGRESS
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree list          # tracked + git worktrees
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree shared        # files touched by >1 task
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree remove <id>   # after successful integration
```

Layout example:
```
<repo>-kobriz-worktrees/
  task-101/   -> adlc/task-101-backend-user-api
  task-102/   -> adlc/task-102-frontend-dashboard
  task-103/   -> adlc/task-103-auth-validation
```
The root is `ADLC_WORKTREE_ROOT` (defaults to a sibling of the repo, outside the main tree).

## Safety rules (enforced by the scripts — do not bypass)
- **Never** run two agents against the same worktree concurrently; one owner per worktree.
- **Never** assume tasks are independent just because they have different IDs — check
  `worktree shared` and known dependencies before concurrent scheduling.
- **Never** reset/clean the user's main checkout. Worktree creation operates in a separate
  directory and leaves uncommitted main-checkout changes intact.
- **Never** force-remove by default. Removing a dirty worktree, or a failed one while
  `ADLC_KEEP_FAILED_WORKTREES=true`, is refused without `--force`.
- Failed worktrees (state FAILED/NEEDS_REWORK/MERGE_CONFLICT/BLOCKED) are **preserved for
  debugging**.
- Each record stores: task id, branch, worktree path, base commit, owner agent, state.

The `scripts/git-worktree.sh` helper offers `create|list|remove|clean-check` for shell use
with the same guards (valid branch/path checks, no force by default).
