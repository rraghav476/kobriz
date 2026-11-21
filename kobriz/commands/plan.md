---
description: Build an execution plan for eligible tasks, store it, post it for review, and stop until a human approves it. Nothing is executed.
argument-hint: "[optional filter, e.g. status=ready or task ids]"
---

Plan a kobriz run. **You (the main assistant) act as the manager** and call the tracker's MCP
tools yourself. This command never creates worktrees, delegates coding, or merges.

0. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup status`. If `needs_setup` is true, run
   `/kobriz:setup` first. Note `provider`, `task_project` and `plan_approval`.
1. `adlc.py config validate`. In MCP mode prove connectivity with one real provider call.
2. **Discover** eligible tasks in the configured project only, applying `$ARGUMENTS` as a
   filter — follow the `task-discovery` skill and the provider recipe (`clickup-provider`
   for ClickUp). Mirror selected tasks into the built-in Task list.
3. **Split** where needed with the `task-splitting` skill. Proposed subtasks are part of the
   plan; creating them in the tracker still needs the user's explicit yes, and any created
   subtask goes into the plan JSON before it is stored.
4. **Classify and order**: backend / frontend / coordinated, dependencies, cycles, blocked
   tasks, and tasks that touch the same files (those run one after another).
5. **Impact preview** per task with the `change-impact-analysis` skill (affected and impacted
   files). This goes into the plan; it is approved with the plan, not separately.
6. **Store and request approval** with the `plan-approval` skill: write the plan JSON,
   `adlc.py plan create`, show the markdown, post it to the approval task when the mode
   includes `provider`, and tell the user exactly how to approve.
7. **Stop.** Report the plan id and what approval is still missing. Execution happens in
   `/kobriz:execute-plan <plan_id>` once the plan is `APPROVED`.
