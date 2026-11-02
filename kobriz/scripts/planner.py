"""Dependency-aware scheduling and task classification for the kobriz manager.

Given a set of tasks (from the provider), this produces:
  * a backend/frontend/shared/coordinated classification (heuristic, overridable),
  * a topological ordering that respects declared dependencies, and
  * concurrency batches bounded by ADLC_MAX_CONCURRENCY.

This is advisory input for the manager agent, which makes the final call and also
consults real shared-file analysis before treating tasks as independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from task_client import Task

_BACKEND_HINTS = ("backend", "api", "server", "endpoint", "database", "db", "model",
                  "service", "schema", "migration", "auth")
_FRONTEND_HINTS = ("frontend", "ui", "react", "component", "page", "css", "style",
                   "dashboard", "form", "view")


def classify(task: Task) -> str:
    """Classify a task as backend | frontend | shared | coordinated (heuristic)."""
    if task.kind in ("backend", "frontend", "shared", "coordinated"):
        return task.kind
    text = f"{task.title} {task.description} {' '.join(task.labels)}".lower()
    be = any(h in text for h in _BACKEND_HINTS)
    fe = any(h in text for h in _FRONTEND_HINTS)
    if be and fe:
        return "coordinated"
    if be:
        return "backend"
    if fe:
        return "frontend"
    return "shared"


def agent_for(kind: str) -> str:
    """Map a classification to the owning developer agent."""
    return {
        "backend": "backend-developer",
        "frontend": "frontend-developer",
        "coordinated": "manager",   # manager splits/coordinates; may spawn both
        "shared": "manager",
    }.get(kind, "manager")


@dataclass
class Plan:
    batches: List[List[str]] = field(default_factory=list)   # ordered concurrency waves
    classification: Dict[str, str] = field(default_factory=dict)
    assignment: Dict[str, str] = field(default_factory=dict)
    blocked: Dict[str, List[str]] = field(default_factory=dict)  # task -> unmet deps
    cycles: List[List[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "batches": self.batches, "classification": self.classification,
            "assignment": self.assignment, "blocked": self.blocked, "cycles": self.cycles,
        }


def build_plan(tasks: List[Task], max_concurrency: int = 3) -> Plan:
    """Build a dependency-respecting, concurrency-bounded execution plan."""
    plan = Plan()
    by_id = {t.id: t for t in tasks}
    for t in tasks:
        kind = classify(t)
        plan.classification[t.id] = kind
        plan.assignment[t.id] = agent_for(kind)

    # Only consider dependencies that refer to tasks in this working set.
    deps: Dict[str, set] = {}
    for t in tasks:
        known = {d for d in t.dependencies if d in by_id}
        unknown = [d for d in t.dependencies if d not in by_id]
        if unknown:
            plan.blocked[t.id] = unknown
        deps[t.id] = known

    # Kahn's algorithm for topological batching.
    remaining = set(by_id)
    resolved: set = set()
    while remaining:
        ready = sorted(tid for tid in remaining if deps[tid] <= resolved)
        if not ready:
            # Cycle: whatever's left depends on each other.
            plan.cycles.append(sorted(remaining))
            break
        # Split the ready set into waves no larger than max_concurrency.
        for i in range(0, len(ready), max(1, max_concurrency)):
            plan.batches.append(ready[i:i + max_concurrency])
        resolved |= set(ready)
        remaining -= set(ready)

    return plan
