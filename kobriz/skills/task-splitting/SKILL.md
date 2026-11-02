---
name: task-splitting
description: Decide whether an ADLC task or story is too large/risky to execute as one unit and, if so, propose an ordered breakdown. Use when a fetched task is really a multi-part "story", spans multiple layers (backend+frontend+DB), or is too big for one clean worktree/PR. CRITICAL — creating subtasks in the task system ALWAYS requires explicit user approval first.
---

## Task Splitting

Some task-system items are a single unit of work; others are **stories** that bundle several
deliverables. Executing a story as one worktree produces a huge, hard-to-review change that
fails all at once. Splitting it into ordered pieces makes each reviewable and individually
verifiable. This skill decides *whether* to split and *how to propose* it — and enforces the
rule that **no subtask is ever created in the task system without the user's explicit
approval.**

### 1. Decide whether a split is warranted
Lean toward splitting when the item:
- reads as a **story / epic** (multiple user-facing outcomes, "and" in the title, a checklist
  of deliverables), or
- spans **more than one layer** (backend + frontend, or touches DB schema + API + UI), or
- touches **high-risk surfaces** — database schema, money/financial figures, multi-tenant
  scoping, auth — alongside other work, or
- is simply **too large for one clean worktree/PR** to review safely.

Lean toward *not* splitting a focused, single-layer, small task — splitting it just adds
overhead. State your reasoning either way.

### 2. Choose the form of the split
Two distinct mechanisms — pick deliberately:

- **Phases (no task-system writes).** Keep it as one task, and use the
  `phased-implementation` skill to execute it as ordered, individually-gated phases on one
  worktree/branch. This changes nothing in the external task system. **Default to this** when
  the pieces are not independently shippable or the provider shouldn't be cluttered with
  children. No approval needed — it's just how you implement the one approved task.

- **Subtasks (writes to the task system).** Create real child items under the parent story in
  the user's existing tracker, each becoming its own kobriz task (own worktree/branch). Use
  this when the pieces are independently assignable/trackable and the team wants them visible
  in the tracker. **This writes to the provider and therefore REQUIRES explicit user
  approval — always, every time.**

### 3. Propose the breakdown (no writes yet)
Present the plan and ask. Never create anything in this step.
```
## Proposed split for <PARENT_ID>: <title>
Recommendation: [phases only | create N subtasks]  — because <reason>

Pieces (ordered by dependency):
1. <name> — <layer(s)> — <acceptance criteria> — depends on: <none|#>
2. ...

If subtasks: I will create them under <PARENT_ID> in <provider>. Approve? (yes/no)
```

### 4. The approval gate (non-negotiable)
- **Ask for explicit approval before creating ANY subtask.** A plan is not approval. "Yes,
  go ahead" (or equivalent) for *this specific breakdown* is required. If the user approves
  only some pieces, create only those.
- Do not treat a general "run the pipeline" instruction, a prior approval for a different
  story, or silence as approval. When in doubt, ask again.
- Phases (Section 2, first option) do **not** need this gate — they create nothing external.

### 5. Create subtasks — only after approval
REST mode (the `--confirm` flag is refused unless set, and you set it only post-approval):
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/adlc.py tasks create-subtask <PARENT_ID> \
  --title "<child title>" --description "<criteria>" --kind <backend|frontend> --confirm
```
MCP mode: use the provider's own "create issue / create subtask" MCP tool (discover it; set
the parent link per its schema). Same approval gate applies — do not call the create tool
until the user has approved.

Requires provider support: a subtask/create endpoint (`ADLC_TASK_SUBTASK_PATH`, default =
the list endpoint) and a parent-link field (`ADLC_TASK_PARENT_FIELD`, default `parent_id`).
If the provider cannot create children, fall back to **phases** and say so — do not invent an
endpoint.

### 6. After creating subtasks
- Report each created child id and link back to the parent.
- Feed the new subtasks into the normal plan (`adlc.py plan` / dependency scheduling) and
  execute each in its own worktree. Execute each child with `phased-implementation` if it is
  itself large.
- Keep the parent story updated (status/comment) as children complete, using the provider's
  supported fields only.
