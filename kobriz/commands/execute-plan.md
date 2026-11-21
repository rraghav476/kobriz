---
description: Execute an approved kobriz plan — record the tracker approval, then create worktrees, delegate to developer agents, validate, and integrate exactly the tasks the plan lists.
argument-hint: "<plan_id>"
---

Execute plan `$1` (in `$ARGUMENTS`). If it is empty, run `adlc.py plan list` and ask which
plan. **You (the main assistant) act as the manager**; only the coding is delegated.

1. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py plan show $1`. If `state` is not `APPROVED`
   and the mode includes `provider`, read the approval task's status from the tracker and
   record it (`plan-approval` skill, step 3). If it is still not `APPROVED`, tell the user what
   is missing and stop.
2. Execute only the tasks in the plan, in its `batches` order. For each task:
   1. `adlc.py plan check <task_id>` — exit 7 means stop and report the reason.
   2. `adlc.py worktree create <task_id> <slug> --kind <kind> --agent <agent>`.
   3. Set the tracker status to the mapped `IN_PROGRESS` yourself and mark the built-in Task
      `in_progress`.
   4. Delegate to `kobriz:backend-developer` / `kobriz:frontend-developer` with the full
      assignment spec (see the manager agent) and require the completion report.
3. If the work needs something the plan does not cover (a new task, a new subtask, a
   materially different set of files), **stop that task**, revise the plan
   (`plan-approval` skill, step 4) and wait for approval again.
4. Review, run `adlc.py impact` and `adlc.py merge preflight`, then integrate serially with
   `adlc.py merge integrate <task_id> --confirm` only when checks pass (no auto-merge unless
   `ADLC_AUTO_MERGE=true`). The merge is also gated on the approved plan.
5. Sync status and completion summaries to the tracker yourself; mark built-in Tasks
   `completed`. Report results per task, including anything stopped by the gate.

Developer sub-agents run one at a time unless background agents are available; say which.
Never bypass review, never force-push, never touch the user's dirty working tree.
