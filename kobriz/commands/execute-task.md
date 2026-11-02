---
description: Execute a single task end-to-end in an isolated worktree — fetch, classify, delegate to the right developer agent, validate, and report.
argument-hint: "<task_id>"
---

Execute one task through the kobriz ADLC. The task id is `$1` (in `$ARGUMENTS`).

Delegate to the **manager** agent (`@agent-kobriz:manager`) scoped to this single task.
The manager must:

0. Check setup (`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup status`); if
   `needs_setup` is true, run `/kobriz:setup` first.
1. Validate + test the connection (`adlc.py config validate` and `adlc.py config test`).
2. Fetch the task from the existing system (MCP tools, or `adlc.py tasks get $1` in REST
   mode) including full details and acceptance criteria.
3. Classify it (backend / frontend / coordinated) and pick the developer agent.
4. Create the worktree:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree create $1 <slug> --kind <kind> --agent <agent>`
   and set status to IN_PROGRESS in the provider.
5. Delegate to the developer agent with the full structured specification; require the
   structured completion report back.
6. Validate: verify acceptance criteria against the real diff, confirm tests actually
   passed, run `adlc.py impact $1`, then `adlc.py merge preflight $1`.
7. Report results. **Do not merge** unless the user asks and all configured checks pass
   (then `adlc.py merge integrate $1 --confirm`).
8. Sync status + summary back to the task system.

If `$1` is empty, ask the user for a task id.
