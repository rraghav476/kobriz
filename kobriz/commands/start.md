---
description: Run the full kobriz ADLC pipeline — discover eligible tasks, plan dependencies/concurrency, create worktrees, delegate to developer agents, validate, and integrate.
argument-hint: "[optional filter, e.g. label=ready]"
---

Run the kobriz Agentic Development Life Cycle.

**YOU (the main assistant) act as the manager — do not delegate orchestration to a
`kobriz:manager` subagent.** Rationale: MCP provider tools (e.g. Jira) are only callable
from the main loop, not from subagents, so a manager subagent cannot discover tickets or
sync status. You orchestrate directly with your own native tools and **delegate only the
coding work** to developer sub-agents. Apply any filter in `$ARGUMENTS`.

0. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup status`. If `needs_setup` is
   true, run the `/kobriz:setup` wizard first and do not proceed until a ticket system is
   attached and a real provider call succeeds.
1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py config validate`. For MCP mode, prove
   connectivity with a real provider tool call (the CLI `config test` only confirms the
   server is declared); stop on error.
2. **Discover eligible tasks with your native tools, not the `adlc.py tasks` CLI** — scoped to
   the configured project `ADLC_TASK_PROJECT` (a provider can host many; if it is unset, list
   projects and have the user pick one before discovering):
   - MCP mode: call the provider's MCP tools directly, filtered to the project (e.g. Jira
     `searchJiraIssuesUsingJql` with `project = <ADLC_TASK_PROJECT>`, `getJiraIssue`).
   - REST mode: the `adlc.py tasks` CLI (or a direct `curl` fallback) is still fine.
   Then **mirror the selected tasks into Claude Code's built-in Task tools**
   (`TaskCreate`/`TaskList`/`TaskUpdate`) and drive ADLC progress from that internal list —
   this is the source of execution state, replacing kobriz's own task listing.
3. **Evaluate task-splitting FIRST — proactively, without being reminded.** For every
   discovered task, apply the `task-splitting` skill. If a task spans multiple layers
   (backend + frontend + DB), is really a multi-part "story", or is too large/risky for one
   clean worktree/PR, **propose an ordered subtask breakdown as part of the plan** and show
   it to the user. **Creating subtasks in the provider (e.g. Jira) ALWAYS requires explicit
   user approval first** — on approval, create them via the provider tools (e.g. Jira
   subtasks under the parent) and mirror them into the built-in Task list; if the user
   declines, proceed with the task as a single unit. Never create provider subtasks silently.
   Then build the execution plan: classify backend/frontend/coordinated, resolve dependencies,
   flag cycles/blocked tasks, and detect shared-file conflicts
   (`adlc.py worktree shared`). Tasks that touch overlapping files MUST be serialized.
4. **Display the proposed plan and ask for confirmation** before any consequential
   operation (worktree creation, delegation, merge) — unless the user asked for a
   non-interactive run.
5. **Per-task impact preview + approval gate (before any worktree/delegation).** For each
   ready task, scan the repo to determine the **affected** files (the ones the task will
   create/modify/delete) and the **impacted** files (files that depend on an affected file
   but won't be changed). Present them **git-log style with status dots** — 🔴 red =
   affected, 🟠 orange = impacted (see the `change-impact-analysis` skill for the exact
   format and how to derive dependents). **Show it and wait for the user's approval.** On
   approval, **post the same preview as a comment on the ticket** (MCP comment tool / Jira
   `addCommentToJiraIssue`, or `adlc.py tasks comment` in REST) and only then proceed. If the
   user declines, skip that task.
6. For each approved task: create an isolated worktree (`adlc.py worktree ...`), set the
   provider status to in-progress **yourself via the MCP/provider tools**, mark the matching
   built-in Task `in_progress`, and **delegate the implementation to the right developer
   sub-agent** (`kobriz:backend-developer` / `kobriz:frontend-developer`) with a full spec.
7. Review completed work, run post-hoc change-impact analysis and preflight, and integrate
   serially through the controlled merge (`adlc.py merge integrate`; no auto-merge unless
   `ADLC_AUTO_MERGE=true`).
8. Sync status + completion summaries back to the provider **yourself via the provider
   tools**, and update the built-in Task to `completed`. Report results.

Be explicit about execution mode: developer sub-agents run through the Task tool **one at a
time (sequentially)** — there is no true parallelism — so even independent tasks are
interleaved, not simultaneous. Never bypass review or force-push, and never alter the user's
dirty working tree to make a merge possible.
