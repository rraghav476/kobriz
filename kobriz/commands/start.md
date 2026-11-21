---
description: Run the full kobriz ADLC — plan eligible tasks, get the plan approved by a human, then execute and integrate it.
argument-hint: "[optional filter, e.g. status=ready]"
---

Run the kobriz Agentic Development Life Cycle. **You (the main assistant) act as the
manager — do not delegate orchestration to a `kobriz:manager` subagent.** Tracker MCP tools
are called from the main loop; the plugin's developer agents have tool allowlists without
MCP, so delegate only the coding to them. Apply any filter in `$ARGUMENTS`.

This is `/kobriz:plan` followed by `/kobriz:execute-plan`, with a human approval in between:

1. **Plan** — do every step of `/kobriz:plan` (discovery scoped to the configured project,
   task splitting, classification, impact preview, store the plan, request approval).
2. **Wait for approval.** Tell the user what to do (from the `plan-approval` skill) and stop.
   Do not continue in the same turn. When the user says they approved, record the tracker
   approval and confirm `adlc.py plan show <plan_id>` reports `APPROVED`.
3. **Execute** — do every step of `/kobriz:execute-plan <plan_id>`.

Approval is enforced in code: `worktree create` and `merge integrate` exit with code 7 when
the plan is not approved. If that happens, report it; never work around it.

Be explicit about execution mode: developer sub-agents run one at a time unless background
agents are available. Never bypass review or force-push, and never alter the user's dirty
working tree to make a merge possible.
