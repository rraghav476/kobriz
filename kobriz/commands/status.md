---
description: Show kobriz ADLC status — task assignments, active worktrees/branches, lifecycle states, pending merges, and config health.
---

Report the current state of the kobriz ADLC. Gather from **real sources** only:

1. Config health:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py config validate`
   (and `config show` for the redacted settings — never print raw secrets).
   **Always state, up front, which branch is the base/merge target** (`base_branch` from
   `config show` / `setup status`, default `main`) and that merged task work lands there —
   not on the user's currently checked-out branch. Make this prominent, not buried.
2. Tracked worktrees, branches, lifecycle states, and the actual git worktree list:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree list`
3. Shared-file conflict signals across active tasks:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree shared`
4. For each tracked task, merge-readiness:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py merge preflight <task_id> --json`
5. Provider-side status: in REST mode use `adlc.py tasks list` / `tasks get`; in MCP mode
   query the configured MCP task tools.

Present a concise table: task id, kind, owner agent, branch, local state, provider status,
ahead/behind, conflicts, pending merge. Call out blocked tasks, test failures, and any
retained failed worktrees. Do not change anything — this command is read-only.
