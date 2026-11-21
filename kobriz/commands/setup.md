---
description: First-run setup wizard — attach your existing ticket system (MCP server or REST API) to kobriz, persist the config, and test the connection.
argument-hint: "(no arguments)"
---

Run the kobriz onboarding wizard. **Always do this before any other kobriz command when the
plugin is not yet configured.** Walk the user through attaching their ticket system and do
not finish until a connection test succeeds (or the user explicitly defers).

## Step 1 — check current state
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup status
```
If `configured` is already true, offer to re-run anyway or just `config test`.

**Always tell the user, in plain words, which branch kobriz treats as the base/main branch**
(the `base_branch` field in the output; default `main`). State explicitly that all task work
is merged into THAT branch via isolated worktrees — NOT into whatever branch the user
currently has checked out, and that their current working tree is never touched. Confirm this
is the branch they want before proceeding; if not, set `ADLC_BASE_BRANCH` in Step 3.

## Step 2 — choose the integration
Ask the user (use a clear choice prompt): **ClickUp (MCP)**, **another MCP server** (e.g. Jira),
or **REST API**?

### Path A — ClickUp (official MCP server)
1. If a ClickUp MCP server is already connected in Claude Code (its tools are listed, e.g. a
   claude.ai ClickUp connector), use its server name. Otherwise register ClickUp's hosted
   server (URL per ClickUp's "Connect an AI assistant to ClickUp's MCP server" docs; their
   Claude Code instruction is `claude mcp add --transport http clickup https://mcp.clickup.com/mcp`):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup init-mcp --server clickup \
     --url https://mcp.clickup.com/mcp
   ```
   ClickUp's MCP uses a sign-in, not an API key: after restarting Claude Code the user
   authenticates with `/mcp`. Never ask for or store a ClickUp token.
2. Save the provider:
   `adlc.py setup save --scope project --data '{"ADLC_TASK_SOURCE_TYPE":"mcp","ADLC_MCP_SERVER":"<name>","ADLC_TASK_PROVIDER":"clickup"}'`
3. Continue with Step 4 (verify) and Step 4.5 (pick the List), then Step 4.6 (statuses).

### Path B — another MCP server (e.g. Jira)
Ask for:
- the MCP **server name** they want to use (how it should appear in Claude Code), and
- how to connect: a **command** (stdio, e.g. `npx -y some-mcp-server`) **or** a **URL**
  (HTTP/SSE), plus any env vars or headers (e.g. an API token header).

Then register it and record the mode (this writes/merges project `.mcp.json` and the kobriz
config file):
```
# stdio example (use --args-json so values like "-y" are passed safely):
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup init-mcp \
  --server <name> --command npx --args-json '["-y","<package>"]' --env-json '{"TOKEN":"<secret>"}'
# HTTP example:
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup init-mcp \
  --server <name> --url https://tickets.example.com/mcp --headers-json '{"Authorization":"Bearer <secret>"}'
```
Tell the user: **restart Claude Code / re-open the project** so it actually connects the MCP
server. After restart, verify with Step 4.
Also save `ADLC_TASK_PROVIDER` (`jira` for Atlassian, otherwise `generic`) with `setup save`.

### Path C — REST API
Collect: base URL, auth type (`bearer`/`apikey`/`none`) and token, and (if non-standard)
the list/details/status/comment paths, plus optional field and status maps for their schema.
Persist it (keys MUST be `ADLC_*`; secrets are written to a 0600 file, never printed):
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup save --scope project --data '{
  "ADLC_TASK_SOURCE_TYPE": "rest",
  "ADLC_TASK_API_BASE_URL": "https://your-task-service.example.com",
  "ADLC_TASK_AUTH_TYPE": "bearer",
  "ADLC_TASK_API_TOKEN": "<secret>",
  "ADLC_TASK_LIST_PATH": "/tasks",
  "ADLC_TASK_DETAILS_PATH": "/tasks/{task_id}",
  "ADLC_TASK_STATUS_PATH": "/tasks/{task_id}/status",
  "ADLC_TASK_FIELD_MAP_JSON": {"ticket_id":"id","summary":"title","blocked_by":"dependencies"},
  "ADLC_TASK_STATUS_MAP_JSON": {"IN_PROGRESS":"in-dev","COMPLETED":"done"}
}'
```
`setup save` reports validation errors and, for REST, immediately runs a live connection
test. If it fails, show the exact error and help the user fix the URL/auth/paths, then
re-save.

## Step 3 — also capture git/merge policy (optional, sensible defaults otherwise)
Offer to set `ADLC_REPOSITORY_ROOT`, `ADLC_BASE_BRANCH`, `ADLC_WORKTREE_ROOT`,
`ADLC_MAX_CONCURRENCY`, `ADLC_MERGE_STRATEGY`. Save them the same way via `setup save`.
Keep `ADLC_AUTO_MERGE` false unless the user explicitly opts in.

**Re-confirm the base branch here.** After saving, re-run `setup status` and show the user the
resolved `base_branch` one more time as the merge target, so there is no surprise later about
where merged work lands.

## Step 4 — verify the connection
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py config test
```
- REST: must report `connected: true` and a task count.
- MCP: confirm the server is declared; then actually list tasks through the MCP tools to
  prove connectivity (the manager agent can do this). Do not claim success until a real
  call returns.

## Step 4.5 — choose the project/board (a provider can host many)
A ticket system usually contains **multiple projects/boards**; kobriz must know which one to
pull tickets from. After connectivity is proven:
1. **List the available projects** via the provider — MCP mode: the provider recipe
   (ClickUp `clickup_get_workspace_hierarchy`, Jira `getVisibleJiraProjects`); REST mode: the
   provider's projects endpoint if it has one. For ClickUp, the user picks one **List**; if
   they belong to several workspaces also save `ADLC_TASK_WORKSPACE`.
2. **Ask the user to pick one** (show key + name). If exactly one exists, confirm it rather
   than assuming silently.
3. Persist the choice as `ADLC_TASK_PROJECT` (a ClickUp List id, a Jira project key like
   `SCRUM`, …):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup save --scope project \
     --data '{"ADLC_TASK_PROJECT": "<project-key>"}'
   ```
From then on, all discovery is scoped to this project; never pull tickets from projects the
user did not select.

## Step 4.6 — statuses and plan approval
Every plan must be approved by a human before kobriz runs it (`plan-approval` skill).
1. Read the project's statuses (ClickUp: `clickup_get_list`). Build
   `ADLC_TASK_STATUS_MAP_JSON` with the user: each kobriz state the team uses
   (`READY`, `IN_PROGRESS`, `REVIEW`, `COMPLETED`, …) → the status name exactly as the
   tracker spells it.
2. Pick the two plan statuses: `ADLC_PLAN_REVIEW_STATUS` (plan posted, awaiting review) and
   `ADLC_PLAN_APPROVED_STATUS` (only a human sets it). If the list has no suitable statuses,
   ask the user to add them in the tracker (for example "plan review" and "plan approved");
   do not create statuses yourself.
3. Save them, plus `"ADLC_PLAN_APPROVAL": "both"`, with `setup save`. Explain the two
   approvals: a status change in the tracker and a command the user types with `!`. If they
   want only one of the two, they must set `ADLC_PLAN_APPROVAL` themselves (`session` or
   `provider`) with `! python3 ... setup save ...` — the guard hook stops you from weakening
   approval settings, and from changing the approval status once it is set. `/kobriz:start` and `/kobriz:status` must
read `ADLC_TASK_PROJECT` and, if it is unset, ask the user to pick before discovering.

## Guardrails
- Never echo secret values back to the user or into task comments. The config file is
  owner-only (0600); remind the user it is git-ignored.
- Prefer `--scope project` (per-repo) unless the user wants global (`--scope user`).
- Stop and report clearly if a connection test fails — do not pretend it connected.
- Always surface the base/merge branch (`base_branch`) to the user during setup. Merged task
  work goes to that branch, not the user's current checkout — never leave this implicit.
