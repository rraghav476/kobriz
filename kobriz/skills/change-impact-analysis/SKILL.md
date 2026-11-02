---
name: change-impact-analysis
description: Produce a structured change-impact report for a completed ADLC task from real git data — changed files, commits, module dependents, shared-file conflicts, risks, and recommended validation. Use after a task is implemented and before/at merge, or when a task comment should carry an impact summary.
allowed-tools: Bash(python3 *) Bash(git *)
---

# Change Impact Analysis

A code-analysis and reporting capability — **not** a UI feature and **not** a separate
database. Every finding must come from actual repository data, and you must distinguish
**confirmed** dependencies from **potential** impact.

## Generate
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py impact <task_id>          # human-readable
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py impact <task_id> --json   # structured
```

## What it inspects (from git)
- Changed files by status: added / modified / deleted / renamed.
- Commits on the branch relative to its recorded base commit.
- **Confirmed dependents**: other tracked files that textually reference a changed module
  (via `git grep`) — likely, verify before relying on them.
- **Potential impact** (heuristic): API consumers, serialization/model consumers, etc.
- **Shared files** touched by other active tasks (a real parallel-conflict signal).
- Risks: schema/API compatibility, migrations, deletions causing dangling imports.
- Recommended validation steps.

## Report shape
```
Task: TASK-101
Branch: adlc/task-101-user-api
Base commit: <sha>
Direct changes: [added|modified|deleted|renamed] <files>
Confirmed dependents: <files referencing changed modules>
Potential impact: <heuristic consumers>
Shared files also touched by: <task ids>
Risks: <compatibility / migration / deletion>
Recommended validation: <tests to run>
```

## Pre-execution (predictive) preview — run BEFORE touching code
The `adlc.py impact` command above needs a committed branch diff, so it is post-hoc. For the
**pre-execution gate** (required by `/kobriz:start` before each task's worktree/delegation),
produce a *predictive* preview instead, from the implementation plan + repo:

1. **Affected files** = the files the task will create/modify/delete, taken from the plan
   (determined while scanning the repo for the task). Tag each with its intended git status
   letter: `A` added, `M` modified, `D` deleted, `R` renamed.
2. **Impacted files** = files that are NOT changed but depend on an affected file — find them
   from real repo data, e.g.:
   ```
   git grep -l -F -e "<affected-basename-without-ext>" -- 'src/**' | grep -v <affected files>
   ```
   (imports/references to the changed module). These are *potential* dependents — leads, not
   certainties; say so.

### Presentation — git-log style with status dots
Render it like a compact git log, one line per file, with a colored dot:
- 🔴 **red dot** = *affected* (a file this change will edit/add/delete)
- 🟠 **orange dot** = *impacted* (a file that depends on an affected file but isn't changed)

```
Impact preview — SCRUM-42: <summary>   (base: main @ <short-sha>)
🔴 M  src/auth/auth.service.ts
🔴 A  .env.example
🟠    src/auth/auth.module.ts        → imports auth.service
🟠    src/app.module.ts              → wires AuthModule
```

### Gate → comment → proceed
- **Show the preview and ask the user to approve** before creating the worktree or delegating.
- **On approval, post the same preview as a comment on the ticket** (MCP comment tool in MCP
  mode, e.g. Jira `addCommentToJiraIssue`; `adlc.py tasks comment` in REST mode), THEN proceed
  with worktree + delegation.
- If the user does not approve, do not proceed with that task.

## Publishing (post-implementation)
Attach the post-hoc report to the existing task system via its comment API when supported
(MCP comment tool in MCP mode, or `adlc.py tasks comment <id> "..."` in REST mode). Do not
create a separate impact store or dashboard. State uncertainty plainly — heuristic flags are
leads, not conclusions.
