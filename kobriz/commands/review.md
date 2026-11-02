---
description: Review a task branch or diff — code quality, tests, and change impact. Reports issues and required fixes; does not merge unless explicitly requested and all checks pass.
argument-hint: "<task_id>"
---

Review the work for task `$1` (in `$ARGUMENTS`) before integration.

Use the **code-review** and **change-impact-analysis** skills. Steps:

1. Resolve the branch/worktree:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py worktree list` (find task `$1`).
2. Read the full diff against the base:
   `git -C <worktree_path> diff <base_commit>...<branch>`.
3. Assess: correctness vs. acceptance criteria, adherence to the developer agent's coding
   standards (backend or frontend), test presence and whether tests **actually passed**
   (check real output, not claims), error handling, and scope (no unrelated changes).
4. Change impact:
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py impact $1` (derived from real git data —
   distinguish confirmed dependents from potential impact).
5. Merge safety (read-only):
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py merge preflight $1 --json`.
6. Produce a verdict: `approve` / `needs_rework` with a specific, actionable issue list.

**Do not merge automatically.** Only if the user explicitly asks AND preflight shows
`can_merge: true` AND required tests passed, run:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py merge integrate $1 --confirm`.

If `$1` is empty, ask the user for a task id (or a specific diff/branch to review).
