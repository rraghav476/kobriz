# Kobriz — Agentic Development Life Cycle (ADLC) plugin for Claude Code

Kobriz orchestrates specialized coding agents to execute development tasks from **your
existing task management system**. It does **not** include a task tracker, dashboard, CRUD
API, or UI — it integrates with the system you already have (via MCP or REST), runs each
task in an isolated **git worktree**, validates the work, merges it through a controlled
process, and syncs status back.

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
├── commands/                       # /kobriz:start | execute-task | status | review
├── skills/                         # task-discovery, git-worktree-management,
│   │                               # backend/frontend-development, code-review,
│   │                               # change-impact-analysis, task-splitting,
│   └── …                           # phased-implementation
├── hooks/hooks.json                # SessionStart config check + PreToolUse git guard
├── scripts/                        # the real executable layer (Python 3 stdlib + bash)
│   ├── adlc.py                     # unified CLI — the single integration entrypoint
│   ├── config.py task_client.py gitutil.py worktree.py impact.py merge.py planner.py
│   ├── git-worktree.sh check-config.sh guard-git.sh
└── tests/                          # pytest suite (43 tests, temp git repos + mock REST)
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
| `/kobriz:setup` | **Run first.** Attach a ticket system (MCP or REST), persist config, test the connection. |
| `/kobriz:start [filter]` | Discover eligible tasks → plan deps/concurrency → confirm → worktrees → delegate → validate → integrate → sync. |
| `/kobriz:execute-task <id>` | Run a single task end-to-end in its own worktree. |
| `/kobriz:status` | Read-only: assignments, worktrees/branches, lifecycle + provider status, pending merges, conflicts. |
| `/kobriz:review <id>` | Review quality, tests, and change impact for a task branch; merge only if asked and all checks pass. |

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

## Testing
```bash
cd kobriz && python3 -m pytest tests/ -q      # 43 tests, no network, no real creds
```
Covers: config validation + secret redaction, REST task retrieval + MCP-vs-REST split,
auth/header injection, field/status mapping, worktree creation/isolation/branch mapping,
shared-file detection, failed-worktree retention, safe handling of uncommitted changes,
dependency-aware planning (topo/cycles/blocked), change-impact generation, merge preflight,
conflict detection, and successful integration. Git tests use throwaway temp repositories.

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
