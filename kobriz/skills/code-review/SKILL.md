---
name: code-review
description: Validate a completed ADLC task branch before integration — correctness vs acceptance criteria, coding-standard adherence, real test results, scope, and merge safety. Use before merging any task branch, or when running /kobriz:review.
allowed-tools: Bash(python3 *) Bash(git *)
---

# Code Review & Pre-Integration Validation

Gate every task branch before it enters the merge queue. Base conclusions on **real data**
(the diff, actual test output, git state) — never on an agent's prose claims alone.

## Checklist
1. **Acceptance criteria** — read the task's criteria; verify each against the real diff:
   `git -C <worktree_path> diff <base_commit>...<branch>`.
2. **Coding standards** — apply the backend-development or frontend-development skill as
   appropriate. Check layering/types/error handling, naming, docstrings/types, and that no
   unrelated files were changed.
3. **Tests actually passed** — confirm the developer ran the repo's real test commands and
   that they passed. If `ADLC_REQUIRE_TESTS=true`, no passing tests ⇒ not merge-ready.
4. **Security** — no hardcoded/logged secrets; inputs validated; authZ respected.
5. **Change impact** — run the change-impact-analysis skill
   (`adlc.py impact <task_id>`): review confirmed dependents, potential impact, and shared
   files touched by concurrent tasks.
6. **Merge safety (read-only)** —
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py merge preflight <task_id> --json`:
   check `can_merge`, `conflicting_files`, divergence (`ahead`/`behind`), and `blockers`.

## Verdict
Return `approve` or `needs_rework` with a specific, actionable issue list. Set the task
state accordingly (`REVIEW` → `READY_TO_MERGE` or `NEEDS_REWORK`).

## Merging
Do **not** merge from review by default. Only on explicit request, with `can_merge: true`
and tests passing:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py merge integrate <task_id> --confirm`.
Never force-push or bypass branch protection. On conflict, preserve the branch/worktree,
record conflicting files, and route back to the owning developer agent.
