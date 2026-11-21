---
description: Turn one Granola meeting into tracker tasks — read the meeting (read-only), draft engineering tasks from its action items, get your approval per task, create only the approved ones, never duplicate.
argument-hint: "[meeting id or search words]"
---

Run meeting intake for one meeting (`$ARGUMENTS` may name it). **You (the main assistant)
do this directly** — MCP tools are called from the main loop, not from subagents.

1. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py setup status`. If `needs_setup` is true, run
   `/kobriz:setup` first. Intake creates tasks in the configured tracker list
   (`task_project`); if it is unset, have the user pick one first.
2. Confirm a Granola MCP server is connected (its tools are listed). If not, tell the user to
   connect Granola (claude.ai connector or `https://mcp.granola.ai/mcp`, OAuth sign-in) and
   stop.
3. Follow the `meeting-intake` skill end to end, using the tracker's provider recipe
   (`clickup-provider` when `provider` is `clickup`).

Never create a task the user did not approve, never write to Granola, and never paste raw
transcript text into the tracker.
