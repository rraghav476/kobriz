---
name: backend-development
description: Backend engineering standards and procedure for the kobriz ADLC backend-developer agent. Use when implementing or reviewing backend tasks — REST APIs, services, business logic, data models/schemas, validation, auth, and their tests.
---

# Backend Development Standards

Apply these when implementing or reviewing backend work. Always **inspect the existing
repository first** and conform to its architecture and conventions rather than imposing new
ones.

## Architecture
- Respect the project's layering (e.g. MVC): keep routes/controllers, services/business
  logic, schemas, and data access separate. Reusable services, no duplicated logic.
- Design REST endpoints with consistent resource naming and correct HTTP methods/status
  codes. Consistent, meaningful error handling.

## Types & validation
- Match the project's typing discipline. For Python + Pydantic: explicit request/response
  models, field validation, and return annotations on public functions.
- Public modules, classes, and functions get docstrings; document non-obvious logic.

## Security
- Handle authN/authZ and sensitive data carefully. Never hardcode or log secrets. Validate
  and sanitize inputs.

## Testing & quality gates
- Add unit and integration tests for new/changed behavior.
- Run the **repo's own** formatter, linter, type checker, and tests — discover the commands
  from its manifest/CI config; do not invent tool names.
- **Report only real results.** A test is "passing" only if it actually ran and passed.

## Procedure
1. Analyze task + relevant code; restate acceptance criteria.
2. Plan; list affected APIs/models/services/tests.
3. Implement inside the assigned worktree only.
4. Verify behavior and edge cases; run tests and capture output.
5. Review the diff for scope; commit with a descriptive message.
6. Return the structured completion report (see the backend-developer agent).

If a change affects an API contract the frontend depends on, surface it to the manager
agent — do not silently change shared contracts.
