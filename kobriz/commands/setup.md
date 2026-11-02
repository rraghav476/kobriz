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
Ask the user (use a clear choice prompt): **MCP server** or **REST API**?

### Path A — MCP (ticket system exposes an MCP server)
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

### Path B — REST API
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
1. **List the available projects** via the provider — MCP mode: the provider's project tool
   (e.g. Jira `getVisibleJiraProjects`); REST mode: the provider's projects endpoint if it
   has one.
2. **Ask the user to pick one** (show key + name). If exactly one exists, confirm it rather
   than assuming silently.
3. Persist the choice as `ADLC_TASK_PROJECT` (e.g. a Jira project key like `SCRUM`):
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup save --scope project \
     --data '{"ADLC_TASK_PROJECT": "<project-key>"}'
   ```
From then on, all discovery is scoped to this project (e.g. Jira JQL `project = <key>`); never
pull tickets from projects the user did not select. `/kobriz:start` and `/kobriz:status` must
read `ADLC_TASK_PROJECT` and, if it is unset, ask the user to pick before discovering.

## Guardrails
- Never echo secret values back to the user or into task comments. The config file is
  owner-only (0600); remind the user it is git-ignored.
- Prefer `--scope project` (per-repo) unless the user wants global (`--scope user`).
- Stop and report clearly if a connection test fails — do not pretend it connected.
- Always surface the base/merge branch (`base_branch`) to the user during setup. Merged task
  work goes to that branch, not the user's current checkout — never leave this implicit.
