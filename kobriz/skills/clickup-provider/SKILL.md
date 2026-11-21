---
name: clickup-provider
description: How kobriz talks to ClickUp through ClickUp's official MCP server — choosing the workspace and list, discovering tasks, reading list statuses, updating status, commenting, creating subtasks and dependencies. Use whenever ADLC_TASK_PROVIDER=clickup.
---

# ClickUp provider recipe

Applies when `ADLC_TASK_PROVIDER=clickup` and `ADLC_TASK_SOURCE_TYPE=mcp`. Only the main
assistant calls these tools; developer subagents never do.

**Tool names** below come from ClickUp's MCP tools reference (developer.clickup.com,
27 Oct 2026); create/get/update task, comments, filter and statuses were checked against the
live server (Nov 2026). Your client shows them with a
server prefix (e.g. `mcp__<server>__clickup_get_task`). Before first use in a session, list
the server's tools and read each input schema. If a name or parameter differs, use what the
server shows and tell the user so this skill can be corrected.

## Settings
| Key | Meaning |
| --- | --- |
| `ADLC_MCP_SERVER` | the ClickUp MCP server's name in Claude Code |
| `ADLC_TASK_PROJECT` | the ClickUp **List id** kobriz works from |
| `ADLC_TASK_WORKSPACE` | ClickUp workspace id; pass as `workspace_id` when the user has several |
| `ADLC_TASK_STATUS_MAP_JSON` | kobriz lifecycle state → the list's own status name |
| `ADLC_PLAN_REVIEW_STATUS` / `ADLC_PLAN_APPROVED_STATUS` | list statuses for plan review and approval |

Statuses belong to each List, so the status map is only valid for `ADLC_TASK_PROJECT`.

## Recipes
| Need | Tool | Notes |
| --- | --- | --- |
| Pick workspace, space, list | `clickup_get_workspace_hierarchy` | Show names and ids; the user picks one List |
| Read the list's statuses | `clickup_get_list`, or `clickup_execute_operator` with `list_status: list` | Use for the status map and to confirm the plan statuses exist; call `clickup_get_operators` before the first operator call |
| Discover tasks | `clickup_filter_tasks` | Filter to the configured list (and status when given); page through results |
| Keyword search | `clickup_search` | Only when the user searches by words |
| Task details | `clickup_get_task` | Description, status, parent, dependencies, custom fields |
| Change status | `clickup_update_task` | Use the mapped status name exactly as the list spells it |
| Comment | `clickup_create_task_comment` | Or `clickup_create_comment`; the docs call the first a legacy name |
| Read comments | `clickup_get_task_comments` | |
| Create a task | `clickup_create_task` | `name` + `list_id`; only after the user approves |
| Create a subtask | `clickup_create_task` with `parent` | The live schema (21 Nov 2026) describes `parent` as "Parent task ID to create as subtask" |
| Dependency | `clickup_add_task_dependency` | `depends_on` + type "waiting on" / "blocking" |

Map ClickUp fields to the kobriz canonical set: `id` = task id, `title` = name,
`description` = description (markdown), `status` = status name, `dependencies` = tasks this
one is waiting on, `labels` = tags, `kind` = a `kind` custom field or tag if the team uses
one, else classify.

## Rules
- **Never set `ADLC_PLAN_APPROVED_STATUS` yourself.** The guard hook blocks it; a human sets it.
- **Creates and comments are not idempotent.** A retried call makes a duplicate. On an error
  or timeout, read back first (`clickup_filter_tasks` by title in the list, or
  `clickup_get_task_comments`) and only retry if nothing was created.
- Tools act with the signed-in user's own ClickUp permissions.
- Rate limit: about 1,000 requests a minute per connection. On HTTP 429 or
  `RATE_LIMIT_EXCEEDED`, wait the `Retry-After` / `retryAfter` seconds.
- Avoid `clickup_delete_task`, `clickup_merge_tasks` and bulk operators unless the user asks
  for that exact action.
