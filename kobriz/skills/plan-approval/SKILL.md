---
name: plan-approval
description: Build a kobriz execution plan, store it, post it for review, and collect human approval before any worktree is created or branch merged. Use for /kobriz:plan, /kobriz:start, /kobriz:execute-plan and /kobriz:execute-task. Covers the plan JSON schema, the approval protocol, and what to do when a plan changes.
---

# Plan approval

No task runs without an **approved plan**. `adlc.py worktree create` and
`adlc.py merge integrate` refuse with exit code 7 unless the newest plan containing the task
is `APPROVED` for its current version. This is enforced in code; do not look for a way
around it.

Approvals required are set by `ADLC_PLAN_APPROVAL` (`setup status` → `plan_approval.mode`):

| Mode | Needs |
| --- | --- |
| `both` (default) | a session approval **and** a tracker approval |
| `session` | a session approval |
| `provider` | a tracker approval |

## 1. Build the plan JSON
After discovery, task-splitting and the per-task impact preview, write the plan as JSON:

```json
{
  "title": "Users API: export and filters",
  "summary": "One or two sentences on what this plan delivers.",
  "approval_task_id": "<tracker task where a human approves>",
  "tasks": [
    {"id": "86abc1", "title": "CSV export endpoint", "kind": "backend",
     "agent": "backend-developer", "depends_on": [],
     "split": "none | phases | subtasks: <ids>",
     "affected_files": ["app/users.py"], "impacted_files": ["app/routes.py"]}
  ],
  "batches": [["86abc1"], ["86abc2", "86abc3"]],
  "risks": ["Touches the users table"]
}
```

- `id` = the tracker's task id. Every task you will create a worktree for must be listed.
- `approval_task_id` is required when the mode includes `provider`. Use the parent story when
  all tasks share one. Otherwise ask the user which task to use, or whether to create a
  "Plan review: <title>" task in the configured list (creating it is a tracker write, so ask).
- `affected_files` / `impacted_files` come from the change-impact preview.

Save it with the Write tool to a temp path **outside** `.kobriz/` (e.g. the session
scratchpad), then:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py plan create --file <path> --by manager
```

The output has `plan_id`, `short_hash` and `markdown`. Creating a plan supersedes any open
plan that shares a task.

## 2. Ask for review
1. Show the user the `markdown` in full.
2. If the mode includes `provider`: post the same markdown as a comment on
   `approval_task_id`, move that task to `ADLC_PLAN_REVIEW_STATUS`, read the task back, and
   record what you read:
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py plan posted <plan_id> --task <approval_task_id> \
     --status "<status as read>" --evidence "<comment id>"
   ```
   This is required for every version: a tracker approval only counts if it was set after the
   current version was posted, so an approval left over from an earlier version or plan never
   carries over. Use the provider recipe (e.g. the `clickup-provider` skill). Comments are not
   idempotent: post once.
3. Tell the user exactly how to approve, using the values from the output:
   - tracker: set task `<approval_task_id>` to status `<ADLC_PLAN_APPROVED_STATUS>`;
   - session: type `! python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py plan approve <plan_id> --hash <short_hash> --by "<their name>"`
     (expand `${CLAUDE_PLUGIN_ROOT}` to the real path when you show it).
4. **Stop and wait.** You cannot approve for them. The guard hook blocks you from running
   `plan approve`, from setting the approval status in the tracker, and from editing
   `.kobriz/`. Never ask the user to disable the guard or the gate.

## 3. Record the tracker approval
When the user says they approved (or on `/kobriz:execute-plan`):
1. Read `approval_task_id` from the tracker with the provider's get-task tool. In REST mode
   use `adlc.py plan verify-provider <plan_id>` instead and skip step 2.
2. Pass the status you **actually read**, never one you were told:
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py plan record-provider-approval <plan_id> \
     --task <approval_task_id> --status "<status as read>" --by "<who changed it, if shown>" \
     --evidence "<tool name + when read>"
   ```
   It refuses if the status is not the configured approval status.
3. `adlc.py plan show <plan_id>` → `state` must be `APPROVED`. If a session approval is still
   missing, remind the user of the command and wait.

## 4. When the plan changes
Any change after approval (a new subtask, a dropped task, different files or order) needs a
new version: edit the JSON, run `adlc.py plan revise <plan_id> --file <path> --note "<why>"`,
and go back to step 2. Revising clears every approval.

If the user asks for changes, record it with
`adlc.py plan request-changes <plan_id> --note "<what they asked>"`, then revise.

## 5. Before every worktree and merge
Run `adlc.py plan check <task_id>`. Exit 7 means stop and tell the user why (the output has
`reason`). Do not create a new plan to get around a refusal without telling the user.
