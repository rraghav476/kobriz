---
name: frontend-development
description: Frontend engineering standards and procedure for the kobriz ADLC frontend-developer agent. Use when implementing or reviewing frontend tasks — React components, hooks, pages, state, styling, API client integration, and their tests.
---

# Frontend Development Standards

Apply these when implementing or reviewing frontend work. Always **inspect the existing
frontend first** — stack, design system, conventions, and API client layer — and conform
to it.

## Components & hooks
- Use the project's stack (prefer React + TypeScript when already used). Follow its
  component/hook/file naming.
- Build small, reusable, focused components; extract custom hooks for reusable stateful
  logic. Avoid oversized components and duplication. Follow the Rules of Hooks.
- Reuse existing design-system components and styles; do not reinvent them.

## Types & data
- Explicit types for props, API responses, state, callbacks. Avoid unnecessary `any`.
- **Never invent backend response schemas.** Read the real API contract (types, client
  code, schema/OpenAPI). If it's missing or must change, report to the manager and wait.
- Handle API errors consistently; implement loading, empty, success, and failure states.

## Testing & quality gates
- Add component and integration tests.
- Run the repo's linter, type checker, and tests using its own commands. Report only real,
  observed results.

## Procedure
1. Inspect architecture and the relevant components/hooks/API clients; restate acceptance
   criteria.
2. Confirm the API contract exists; coordinate via the manager if backend work is needed.
3. Implement inside the assigned worktree only; keep changes scoped (no unrelated UI edits).
4. Verify interactions, types, and all UI states.
5. Run lint/type/test and capture output; review the diff; commit.
6. Return the structured completion report (see the frontend-developer agent).
