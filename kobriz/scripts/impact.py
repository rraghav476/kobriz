"""Change-impact analysis for the kobriz ADLC plugin.

Produces a structured report derived ONLY from real git data for a task branch:
changed files (by status), commits, module/import dependents, and heuristic risk flags.
It clearly separates *confirmed* changes from *potential* impact, and never invents
dependencies it cannot observe.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List

import gitutil
from worktree import WorktreeManager

# File-type heuristics used to classify risk and suggest validation (not authoritative).
_API_HINTS = ("api/", "routes/", "controllers/", "endpoints/", "urls.py", "router")
_SCHEMA_HINTS = ("schema", "model", "serializer", "dto", "types")
_MIGRATION_HINTS = ("migration", "migrations/")


@dataclass
class ImpactReport:
    task_id: str
    branch: str
    base_commit: str
    commits: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    renamed: List[str] = field(default_factory=list)
    confirmed_dependents: List[str] = field(default_factory=list)
    potential_impact: List[str] = field(default_factory=list)
    shared_with_tasks: Dict[str, List[str]] = field(default_factory=dict)
    risks: List[str] = field(default_factory=list)
    recommended_validation: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        lines = [
            f"Task: {self.task_id}",
            f"Branch: {self.branch}",
            f"Base commit: {self.base_commit[:12]}",
            f"Commits: {len(self.commits)}",
            "",
            "Direct changes:",
        ]
        for label, items in (("added", self.added), ("modified", self.modified),
                             ("deleted", self.deleted), ("renamed", self.renamed)):
            for f in items:
                lines.append(f"  [{label}] {f}")
        if not (self.added or self.modified or self.deleted or self.renamed):
            lines.append("  (none detected)")
        lines += ["", "Confirmed dependents (import references in repo):"]
        lines += [f"  - {d}" for d in self.confirmed_dependents] or ["  (none found)"]
        lines += ["", "Potential impact (heuristic, verify manually):"]
        lines += [f"  - {d}" for d in self.potential_impact] or ["  (none flagged)"]
        if self.shared_with_tasks:
            lines += ["", "Shared files also touched by other active tasks:"]
            for f, ids in self.shared_with_tasks.items():
                lines.append(f"  - {f}: {', '.join(ids)}")
        lines += ["", "Risks:"]
        lines += [f"  - {r}" for r in self.risks] or ["  (none flagged)"]
        lines += ["", "Recommended validation:"]
        lines += [f"  - {v}" for v in self.recommended_validation] or ["  (standard test suite)"]
        return "\n".join(lines)


def _grep_importers(repo: str, basename_no_ext: str) -> List[str]:
    """Find files in the repo that reference a changed module by basename.

    Uses ``git grep`` so it only searches tracked files and cannot run arbitrary shell.
    Returns a bounded, de-duplicated list. These are *confirmed textual references*, which
    we treat as likely-but-not-certain dependents.
    """
    if len(basename_no_ext) < 3:
        return []
    code, out, _ = gitutil.run_git(
        repo, ["grep", "-l", "-I", "--", basename_no_ext], check=False
    )
    if code != 0:
        return []
    return sorted({line for line in out.splitlines() if line})[:50]


def analyze(manager: WorktreeManager, task_id: str) -> ImpactReport:
    """Build an ImpactReport for a task branch using real git history and tree data."""
    record = manager.get(task_id)
    if not record:
        raise gitutil.GitError(f"No worktree record for task {task_id}")
    repo = manager.repo
    rng = f"{record.base_commit}...{record.branch}"

    report = ImpactReport(task_id=task_id, branch=record.branch, base_commit=record.base_commit)

    _, log_out, _ = gitutil.run_git(repo, ["log", "--format=%H %s", rng], check=False)
    report.commits = [l for l in log_out.splitlines() if l]

    _, name_status, _ = gitutil.run_git(repo, ["diff", "--name-status", rng], check=False)
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        path = parts[-1]
        if code.startswith("A"):
            report.added.append(path)
        elif code.startswith("M"):
            report.modified.append(path)
        elif code.startswith("D"):
            report.deleted.append(path)
        elif code.startswith("R"):
            report.renamed.append(f"{parts[1]} -> {parts[-1]}")

    changed = report.added + report.modified + [r.split(" -> ")[-1] for r in report.renamed]

    # Confirmed dependents: other tracked files that import a changed module by basename.
    dependents: set = set()
    for path in changed:
        base = os.path.splitext(os.path.basename(path))[0]
        for importer in _grep_importers(repo, base):
            if importer not in changed:
                dependents.add(importer)
    report.confirmed_dependents = sorted(dependents)[:50]

    # Potential impact + risks: heuristic classification of what the change touches.
    low = [c.lower() for c in changed]
    if any(any(h in c for h in _API_HINTS) for c in low):
        report.potential_impact.append("API consumers (frontend clients, integration tests)")
        report.risks.append("API surface changed — response/request schema compatibility")
        report.recommended_validation.append("API integration tests")
        report.recommended_validation.append("Frontend contract tests")
    if any(any(h in c for h in _SCHEMA_HINTS) for c in low):
        report.potential_impact.append("Serialization / data model consumers")
        report.risks.append("Schema/model changed — backward compatibility of persisted data")
    if any(any(h in c for h in _MIGRATION_HINTS) for c in low):
        report.risks.append("Database migration present — verify up/down and data safety")
        report.recommended_validation.append("Migration test against a copy of the schema")
    if report.deleted:
        report.risks.append(f"{len(report.deleted)} file(s) deleted — check for dangling imports")

    # Shared files across concurrent tasks (real parallel-conflict signal).
    shared = manager.detect_shared_files()
    report.shared_with_tasks = {f: ids for f, ids in shared.items() if task_id in ids}
    if report.shared_with_tasks:
        report.risks.append("Shared files touched by concurrent tasks — merge conflict likely")

    if not report.recommended_validation:
        report.recommended_validation.append("Run the task's unit tests and the standard suite")

    return report
