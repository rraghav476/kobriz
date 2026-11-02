---
name: phased-implementation
description: Execute an approved ADLC task safely by breaking it into small ordered phases, gating each phase with real verification before the next starts. Use when a task is large, risky, or touches more than one layer — a database schema, money/financial figures, multi-tenant scoping, auth, or more than one file — and when a previously shipped fix turns out not to have worked. Applies inside the task's assigned git worktree.
---

## Phased Implementation

A large change shipped in one shot fails in one shot, and finding out which piece broke
means reasoning about all of it at once. A change shipped in small, ordered,
individually-verified phases fails, if it fails, at exactly the phase that has the bug —
with everything before it already proven working. Slower per-commit, faster overall.

In kobriz this happens **inside the task's assigned worktree**: each phase is one (or a few)
focused commits on the task's feature branch, gated before the next phase begins. The
controlled merge (`adlc.py merge preflight` / `integrate`) runs only after **all** phases
pass. A phase breakdown does **not** by itself create subtasks in the task system — see the
`task-splitting` skill for when/whether to do that, and its mandatory approval gate.

### 1. Break the change into ordered phases
Order by dependency, not convenience. Typical backend→frontend shape: new infrastructure
(tables, services) → data-model changes → business logic using the new data → read
paths/aggregations → frontend → end-to-end verification. Each phase small enough to
type-check and verify on its own before the next starts.

### 2. Gate every phase before moving on
After each phase:
- Type-check / compile-check immediately (the repo's real command). Don't accumulate across
  phases before checking.
- For anything touching real behavior (not a pure refactor), verify with a throwaway script
  or the repo's tests — not just "does it run," but does it produce the exact values the
  design called for, including the specific edge cases the design named.
- If a verification script itself is wrong (bad test data, stale assumption, typo) it can
  produce a false pass/fail. When something behaves unexpectedly, check whether the *test*
  is wrong before concluding the *code* is — and say which it turned out to be.
- Delete throwaway scripts/diagnostics as soon as their job is done — before the next phase,
  not "at the end." Commit each verified phase on the task branch so progress is recoverable.

### 3. Integrate only after all phases are green
Staging/deploy specifics depend on the repo. Within kobriz, a task is merge-ready only when
every phase's quality gate passed; record each phase's result in the completion report.
Before any production deploy the repo performs, record the currently-serving revision as the
rollback point **before** deploying, and after deploying confirm the serving revision
matches what you shipped — a successful deploy command is not proof the new code is serving.

### 4. When a shipped fix doesn't work, don't guess again
A second guess without new information is no more likely to be right than the first. Get a
way to see the real behavior — ask the user to test something specific and report back
exactly what happened, reproduce it yourself if viable, or compare against a known-working
state — before trying again. Two wrong guesses in a row is the signal to stop guessing.

### Output structure
Report against this shape both when proposing the breakdown and when reporting progress.

**Up front, before writing code:**
```
## Phases
1. [Name] — [what it covers] — [layer(s): backend / frontend / DB / config]
2. ...
## Verification plan per phase
[The specific happy-path and edge-case checks each phase's gate must prove]
```

**After each phase (or summarizing all):**
```
## Phase N: [name] — done / blocked
- Changed: [files, grouped by layer if it spans more than one]
- Quality gate: [type-check result] + [verification result — what was checked and what it
  showed, not just "passed"]
- Cleanup: [diagnostic scripts/jobs removed — confirm, don't assume]
## Coverage check
[One line per layer the change could plausibly touch — backend, frontend, DB/schema, seeded
data, config/deploy, docs — stating what changed there or that it was checked and didn't
need to.]
```
If a phase is still in progress, report what's done so far in this same shape, not free-form
prose — anyone scanning should be able to tell the state without re-reading everything.
