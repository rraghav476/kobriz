# Kobriz — Agentic Development Life Cycle (ADLC) plugin for Claude Code

Kobriz orchestrates specialized coding agents to execute development tasks from **your
existing task management system**. It does **not** include a task tracker, dashboard, CRUD
API, or UI — it integrates with the system you already have (ClickUp, another MCP server, or
REST), can turn a **Granola meeting** into tasks there, builds a plan that **a human must
approve**, runs each task in an isolated **git worktree**, validates the work, merges it
through a controlled process, and syncs status back.

```
Granola meeting ──/kobriz:intake──▶ tracker tasks ──/kobriz:plan──▶ stored plan
      ──human approves (tracker status + session command)──▶ /kobriz:execute-plan ──▶ merged
```

> Built against the official Claude Code plugin format (manifest, agents, skills, commands,
> hooks, MCP). See **Limitations** for an honest note on parallel execution.

---

## What's in the box

```
kobriz/
├── .claude-plugin/plugin.json      # plugin manifest
├── agents/
│   ├── manager.md                  # orchestrator (discover → assign → review → merge → sync)
│   ├── backend-developer.md        # backend-only implementer
│   └── frontend-developer.md       # frontend-only implementer
├── commands/                       # /kobriz:setup | intake | plan | execute-plan | start
│                                   # | execute-task | status | review
├── skills/                         # task-discovery, clickup-provider, meeting-intake,
│   │                               # plan-approval, git-worktree-management,
│   │                               # backend/frontend-development, code-review,
│   │                               # change-impact-analysis, task-splitting,
│   └── …                           # phased-implementation
├── hooks/hooks.json                # SessionStart config check + PreToolUse git and approval guards
├── scripts/                        # the real executable layer (Python 3 stdlib + bash)
│   ├── adlc.py                     # unified CLI — the single integration entrypoint
│   ├── config.py task_client.py gitutil.py worktree.py impact.py merge.py planner.py
│   ├── plan_store.py intake_store.py
│   ├── git-worktree.sh check-config.sh guard-git.sh guard-approval.py
└── tests/                          # pytest suite (121 tests, temp git repos + mock REST)
```

The agents/skills/commands are prompt-level orchestration; **all real operations**
(task I/O, worktrees, impact, merge) are performed by the tested `scripts/` layer, driven
through `adlc.py`.

## Requirements
- Claude Code with plugin support.
- Python 3.8+ and `git` on PATH. **No third-party Python packages** (standard library only).
- `pytest` only to run the test suite.

## Install (local development)
```bash
claude --plugin-dir ./kobriz        # load locally
claude plugin validate ./kobriz     # validate manifest/structure
```
Then enable it and use the `/kobriz:*` commands.

## First run — attach your ticket system (required)
A fresh install has **no ticket system attached**, so run the setup wizard first:

```
/kobriz:setup
```

It asks whether your tracker is an **MCP server** or a **REST API**, collects the
connection details, **persists them** to a per-project config file
(`.kobriz/config.json`, written `0600`, git-ignored), and then **tests the connection** so
you immediately see success or the exact error. The other commands refuse to run until a
provider is attached and `config test` passes.

Config is resolved from three layers (highest first): **environment `ADLC_*`** →
**`.kobriz/config.json`** (project, then `~/.claude/kobriz/config.json`) → **defaults**. So
the wizard works with zero shell-profile editing, and CI can still override via env vars.
`.env.example` documents every key if you prefer to set them directly.

Useful checks anytime:
```
python3 kobriz/scripts/adlc.py setup status     # configured? what's missing?
python3 kobriz/scripts/adlc.py config validate  # static validation
python3 kobriz/scripts/adlc.py config test      # LIVE connection test to the provider
```

### Mode A — MCP (recommended if your tracker has an MCP server)
```
ADLC_TASK_SOURCE_TYPE=mcp
ADLC_MCP_SERVER=<your-configured-mcp-server-name>
```
The manager agent **discovers** the server's task tools and schemas at runtime (it does not
assume tool names) and uses them for list/details/status/comments. `adlc.py tasks …` is
intentionally disabled in MCP mode so the plugin never duplicates MCP.

### Mode B — REST
```
ADLC_TASK_SOURCE_TYPE=rest
ADLC_TASK_API_BASE_URL=https://your-task-service.example.com
ADLC_TASK_API_TOKEN=<secret>          # or ADLC_TASK_AUTH_TYPE=apikey / none
ADLC_TASK_LIST_PATH=/tasks
ADLC_TASK_DETAILS_PATH=/tasks/{task_id}
ADLC_TASK_STATUS_PATH=/tasks/{task_id}/status
# Map your schema -> canonical fields and your statuses -> kobriz lifecycle states:
ADLC_TASK_FIELD_MAP_JSON={"ticket_id":"id","summary":"title","blocked_by":"dependencies"}
ADLC_TASK_STATUS_MAP_JSON={"IN_PROGRESS":"in-dev","COMPLETED":"done"}
```

### Git / merge policy (both modes)
```
ADLC_REPOSITORY_ROOT=.         ADLC_BASE_BRANCH=main      ADLC_WORKTREE_ROOT=
ADLC_MAX_CONCURRENCY=3         ADLC_MERGE_STRATEGY=merge  ADLC_REQUIRE_TESTS=true
ADLC_AUTO_MERGE=false          ADLC_KEEP_FAILED_WORKTREES=true
```
`ADLC_AUTO_MERGE` stays **false** until you explicitly enable it. See `.env.example` for the
full, documented contract.

## Commands
| Command | What it does |
|---|---|
| `/kobriz:setup` | **Run first.** Attach a ticket system (ClickUp, other MCP, or REST), pick the list/project, map statuses, set the plan-approval statuses, test the connection. |
| `/kobriz:intake [meeting]` | Read one Granola meeting (read-only), draft tasks from its action items, create the ones you approve, never twice. |
| `/kobriz:plan [filter]` | Discover → split → classify/order → impact preview → store the plan → post it for review → stop. |
| `/kobriz:execute-plan <plan_id>` | Record the tracker approval, then worktrees → delegate → validate → integrate → sync, for exactly the planned tasks. |
| `/kobriz:start [filter]` | `/kobriz:plan`, wait for approval, then `/kobriz:execute-plan`. |
| `/kobriz:execute-task <id>` | Run a single task end-to-end in its own worktree (needs an approved plan that includes it). |
| `/kobriz:status` | Read-only: assignments, worktrees/branches, lifecycle + provider status, pending merges, conflicts. |
| `/kobriz:review <id>` | Review quality, tests, and change impact for a task branch; merge only if asked and all checks pass. |

## Plan approval
Every run starts from a stored plan (`.kobriz/plans/<plan_id>.json` in the target repo,
git-ignored; `adlc.py plan show <id> --markdown` renders it). `worktree create` and `merge integrate` **refuse with exit 7**
unless the newest plan containing the task is `APPROVED` for its current content hash.

| `ADLC_PLAN_APPROVAL` | A plan is approved when |
| --- | --- |
| `both` (default) | a human sets `ADLC_PLAN_APPROVED_STATUS` on the plan's approval task in the tracker **and** types `! python3 …/adlc.py plan approve <plan_id> --hash <short_hash> --by "<name>"` |
| `session` | only the typed command |
| `provider` | only the tracker status |

- **States:** `PENDING_APPROVAL → APPROVED`, or `CHANGES_REQUESTED`; a newer plan covering the
  same task makes the old one `SUPERSEDED`. Revising a plan clears every approval.
- **Approving the exact version:** the session approval must quote the plan's hash, and the
  gate recomputes the hash, so an edited plan file is refused.
- **Keeping it human:** the `guard-approval.py` hook blocks the agent from running
  `plan approve`, setting the approval status through a tracker MCP tool, editing anything
  under `.kobriz/`, and weakening the approval settings.
- **Limits, stated honestly:** this stops an agent approving its own plan by accident or as a
  shortcut; it is not a security boundary against a process on your machine set on bypassing
  it. In MCP mode the tracker approval is read by the agent and recorded with
  `plan record-provider-approval`, which only accepts the configured status, from the plan's
  own approval task, after this version was posted for review (`plan posted`); in REST mode
  `plan verify-provider` reads it directly. The CLI cannot call MCP, so in MCP mode it relies
  on the status the agent reports: `provider`-only mode is therefore agent-attested, and the
  default `both` keeps a step only a human performs.
- `ADLC_REQUIRE_PLAN_APPROVAL` fails closed: only `false`, `0`, `no` or `off` switch the gate
  off.
- `ADLC_REQUIRE_PLAN_APPROVAL=false` turns the gate off. Only a human should set it.
- The guard also scans scripts and config files the agent writes (not prose docs, not the
  plugin itself) for these commands and settings, and protects `~/.claude/kobriz/` and the
  file `ADLC_CONFIG_FILE` names.

## Meeting intake (Granola)
`/kobriz:intake` reads one meeting through a connected Granola MCP server (the claude.ai
connector or `https://mcp.granola.ai/mcp`, OAuth sign-in per user), drafts engineering tasks
from its notes, and creates only the drafts you approve in the configured list.
- Read-only: the guard hook blocks Granola tools that create, update, move, regenerate or
  sign out.
- Meeting text is treated as data, never as instructions; transcripts are never pasted into
  the tracker.
- `adlc.py intake check|record|show` keeps a per-meeting ledger of created task ids, so a
  re-run never creates a duplicate (tracker creates are not idempotent). Matching is by
  normalized title (case, punctuation and width ignored), so a reworded title counts as new.
- Granola has no structured action-item field; items are extracted by the model and each
  draft says what it is based on. Free Granola plans see the last 30 days; transcripts need a
  paid plan.

## ClickUp
Set `ADLC_TASK_PROVIDER=clickup` (the setup wizard does this). Kobriz works from one ClickUp
**List** (`ADLC_TASK_PROJECT`), whose statuses drive `ADLC_TASK_STATUS_MAP_JSON` and the two
plan statuses. The `clickup-provider` skill maps each need to a ClickUp MCP tool. Connect it with
`claude mcp add --transport http clickup https://mcp.clickup.com/mcp`, then `/mcp` to sign in
(per ClickUp's developer docs). Tool names
come from ClickUp's docs and must be checked against a live server; in particular, whether
`clickup_create_task` with `parent` creates a subtask is not yet confirmed.

## Task splitting & phased implementation
Large items are handled two ways (manager decides via the `task-splitting` skill):

- **Phases** — one approved task executed as small, individually-verified phases on its own
  worktree (`phased-implementation` skill). Creates nothing in the task system; no approval
  needed — it's just how a big task is implemented safely.
- **Subtasks** — real child items created under a parent **story** in your existing tracker,
  each becoming its own kobriz task. This writes to the provider, so it **always requires
  your explicit approval first**. The manager proposes an ordered breakdown and asks; only on
  an explicit "yes" does it create them:
  ```
  adlc.py tasks create-subtask <parent_id> --title "..." --kind backend --confirm
  ```
  The `--confirm` flag is refused unless set (exit 6), and the manager sets it only after you
  approve. Needs provider support: `ADLC_TASK_SUBTASK_PATH` (defaults to the list endpoint)
  and `ADLC_TASK_PARENT_FIELD` (default `parent_id`). No endpoint → it falls back to phases.

## Lifecycle
`READY → ASSIGNED → IN_PROGRESS → REVIEW → VALIDATING → READY_TO_MERGE → MERGING → COMPLETED`
plus `BLOCKED | FAILED | NEEDS_REWORK | MERGE_CONFLICT | CANCELLED`. These are **logical**
states; they're mapped to your provider's own status values via `ADLC_TASK_STATUS_MAP_JSON`.
Kobriz never overwrites fields/statuses the provider doesn't support, and if a status sync
fails it **preserves the development results** and reports the sync error (it does not
re-run the implementation).

## The CLI (what the agents actually call)
```bash
adlc.py setup status                                     # configured? what's missing?
adlc.py setup save --data '{...ADLC_* keys...}'          # persist config (0600 file)
adlc.py setup init-mcp --server <name> --command npx --args-json '[...]'   # attach MCP server
adlc.py config validate | show | test                   # test = LIVE provider connection
adlc.py tasks list | get <id> | status <id> <STATE> | comment <id> "<text>"   # REST mode
adlc.py plan                                                                   # REST mode
adlc.py worktree create <id> <slug> [--kind backend|frontend] [--agent name]
adlc.py worktree list | shared | state <id> <STATE> | remove <id> [--force]
adlc.py impact <id> [--json]
adlc.py merge preflight <id> [--json]
adlc.py merge integrate <id> [--confirm]
```
All output is JSON (or `--json`), non-zero exit on error, secrets never printed.

## Safety guarantees (enforced in code, covered by tests)
- Never resets/cleans the user's main checkout or overwrites uncommitted changes — all work
  happens in **separate worktrees**.
- One owner agent per worktree; never two agents on the same worktree.
- Detects shared-file edits across concurrent tasks (`worktree shared`) so different task
  IDs are not mistaken for independence.
- No force-push, no branch-protection bypass, no auto-merge unless explicitly enabled.
- Failed worktrees are retained for debugging (`ADLC_KEEP_FAILED_WORKTREES`).
- Merge is check-gated: preflight detects divergence/conflicts before any mutation; conflicts
  preserve the branch and route back to the developer agent.
- Secrets read only from env and redacted in all output; git commands use list-argv
  subprocess calls (no shell injection); paths and branch names validated.
- A `PreToolUse` hook blocks `git push --force`, `git reset --hard`, and `git clean -f`
  (force-with-lease is allowed).
- No worktree or merge without a human-approved plan (see **Plan approval**).

## Testing
```bash
cd kobriz && python3 -m pytest tests/ -q      # 121 tests, no network, no real creds
```
Covers: config validation + secret redaction, REST task retrieval + MCP-vs-REST split,
auth/header injection, field/status mapping, worktree creation/isolation/branch mapping,
shared-file detection, failed-worktree retention, safe handling of uncommitted changes,
dependency-aware planning (topo/cycles/blocked), change-impact generation, merge preflight,
conflict detection, successful integration, the plan store and approval gate (hash binding,
revision, supersession, both/session modes, CLI exit codes), the approval guard hook, and
the intake ledger. Git tests use throwaway temp repositories. The MCP-driven steps (ClickUp,
Granola, reading the approval status) are prompt-level and are verified by a manual run
against a test list and meeting, not by pytest.

## Limitations (stated honestly)
- **Parallel execution.** Subagents invoked with the `Task` tool run **sequentially** within
  a session. The manager runs each concurrency batch sequentially by default and reports it
  as such. True background parallelism is only used when your Claude Code environment
  provides background/parallel agents; otherwise kobriz uses the best supported sequential
  pattern — it does not pretend async execution exists when it doesn't.
- **MCP task operations** are performed by the manager agent via discovered MCP tools, not by
  the Python CLI (by design — the CLI would duplicate MCP). The REST client is fully
  scripted and tested.
- Change-impact "confirmed dependents" are textual (`git grep`) references — treat them as
  strong leads, and "potential impact" as heuristics to verify, not guarantees.
