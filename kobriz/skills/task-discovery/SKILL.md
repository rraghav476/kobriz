---
name: task-discovery
description: Discover and fetch tasks from the existing task management system (MCP server or REST API) for the kobriz ADLC. Use when the manager needs to list eligible tasks, read full task details/acceptance criteria, update task status, or post comments. Covers both MCP tool discovery and the REST CLI.
---

# Task Discovery

The existing task system is the **source of truth**. Never create a parallel task store.
The integration mode is set by `ADLC_TASK_SOURCE_TYPE` (`mcp` | `rest`).

**Scope discovery to the configured project.** A provider can host many projects/boards; the
selected one is `ADLC_TASK_PROJECT` (e.g. a Jira project key). Every discovery query MUST be
filtered to it (e.g. Jira JQL `project = <ADLC_TASK_PROJECT>`). If `ADLC_TASK_PROJECT` is unset,
stop and have the user pick one (list projects via the provider) before discovering — do not
pull from all projects.

## MCP mode (`ADLC_TASK_SOURCE_TYPE=mcp`)
**The main assistant (acting as manager) calls these tools directly** — MCP tools are not
available to subagents, so discovery and status-sync must happen in the main loop.
1. The configured server is named by `ADLC_MCP_SERVER`. **Discover** the tools it exposes;
   do not assume tool names. Look for tools that: list/search tasks, get task details,
   update status, and add comments/worklog.
2. Inspect each tool's input schema before calling it. Use only the configured, authorized
   server.
3. Map the provider's fields to the kobriz canonical set: `id, title, description, status,
   acceptance_criteria, dependencies, kind, labels`.
4. **Mirror the selected tasks into Claude Code's built-in Task tools**
   (`TaskCreate`/`TaskList`/`TaskUpdate`) and run the ADLC from that internal list — it is
   the execution-state source of truth. `adlc.py tasks ...` is intentionally **disabled** in
   MCP mode (it would duplicate MCP); do not use it for listing.

## REST mode (`ADLC_TASK_SOURCE_TYPE=rest`)
**First try the CLI.** It handles auth, headers, response-envelope unwrapping, field mapping
(`ADLC_TASK_FIELD_MAP_JSON`), and status mapping (`ADLC_TASK_STATUS_MAP_JSON`):

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py tasks list
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py tasks get <task_id>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py tasks status <task_id> <LIFECYCLE_STATE>
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py tasks comment <task_id> "<text>"
```

### The provider response can be in ANY shape — extract tasks yourself
The CLI's parser only unwraps a **single-level** envelope (`tasks`/`data`/`items`/`results`
as a top-level array) and verifies SSL via Python's CA store. Real providers vary: the task
array may be nested (e.g. `data.items`, `payload.results`, `result.records`), the id may be
under a non-standard key (`_id`, `cr_id`, `ticket_id`, `key`), and the host's TLS chain may
not validate under Python even when it's fine under `curl`. **Do not treat a CLI failure as
"no tasks."** When `adlc.py tasks list` errors (SSL `CERTIFICATE_VERIFY_FAILED`, "not a JSON
array or recognized envelope", or an empty list you don't believe), fall back to fetching the
endpoint directly and parsing it yourself:

1. Read the connection config (don't hardcode): base URL `ADLC_TASK_API_BASE_URL`, list path
   `ADLC_TASK_LIST_PATH`, and headers `ADLC_TASK_EXTRA_HEADERS_JSON` from
   `.kobriz/config.json` (or env). If the list path contains a `{usecase_slug}` / other
   placeholder, substitute the target value for this run.
2. `curl -s "<base_url><list_path>" -H "<Header>: <Value>" …` for each configured header.
   `curl` uses the system cert store, so it sidesteps the Python SSL issue.
3. **Find the task array wherever it lives** in the returned JSON — walk nested envelopes
   until you reach the list of task objects. Don't assume a key name.
4. Map each object to the canonical set (`id, title, description, status,
   acceptance_criteria, dependencies, kind, labels`) using `ADLC_TASK_FIELD_MAP_JSON` as a
   hint; for `id`, use whichever id-like field is actually populated (`_id`, `cr_id`, `id`,
   `key`…). Skip objects with no usable id and say so.
5. Never echo secret header values into output or task comments.

Use the same direct-`curl` fallback for `get`/`status`/`comment` when the CLI can't reach or
parse the provider.

## Eligibility & dependencies
- A task is eligible when its provider status maps to `READY` and all its declared
  dependencies are satisfied.
- Build a plan with `adlc.py plan` (REST) or the same logic in MCP mode: topological order,
  concurrency batches (`ADLC_MAX_CONCURRENCY`), cycles flagged, unknown deps blocked.

## Guardrails
- Never print raw secrets (the CLI redacts config; MCP auth is handled by the server).
- Validate configuration first: `adlc.py config validate`.
- If discovery/credentials are missing, report clear setup steps; for local testing use a
  mock REST provider (see `tests/`).
