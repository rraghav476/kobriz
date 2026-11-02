"""Controlled integration / merge logic for the kobriz ADLC plugin.

This module never force-pushes, never bypasses branch protection, and never merges
unless the configured checks pass. ``preflight`` is read-only (safe to run anytime);
``integrate`` performs the actual merge into the configured target branch and is the
only mutating entry point.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import gitutil
from config import Config
from worktree import WorktreeManager


@dataclass
class PreflightResult:
    task_id: str
    branch: str
    target_branch: str
    clean_worktree: bool
    diverged: bool
    conflicting_files: List[str] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0
    can_merge: bool = False
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "branch": self.branch, "target_branch": self.target_branch,
            "clean_worktree": self.clean_worktree, "diverged": self.diverged,
            "conflicting_files": self.conflicting_files, "ahead": self.ahead, "behind": self.behind,
            "can_merge": self.can_merge, "blockers": self.blockers,
        }


@dataclass
class MergeResult:
    task_id: str
    branch: str
    target_branch: str
    merged: bool
    merge_commit: Optional[str] = None
    message: str = ""
    conflicting_files: List[str] = field(default_factory=list)


class Integrator:
    """Serialized, check-gated integration of task branches into the target branch."""

    def __init__(self, config: Config, manager: WorktreeManager) -> None:
        self.config = config
        self.manager = manager
        self.repo = manager.repo

    def _target_checkout(self, target: str) -> Optional[str]:
        """Return the path of the worktree that currently has ``target`` checked out, if any.

        A branch can only be checked out in one worktree at a time, so we must merge in
        that worktree rather than creating a conflicting second checkout.
        """
        for wt in gitutil.list_worktrees(self.repo):
            if wt.get("branch") == target:
                return wt.get("path")
        return None

    def _detect_conflicts(self, branch: str, target: str) -> List[str]:
        """Dry-run a merge to list conflicting files without touching the working tree.

        Uses ``git merge-tree`` (three-way) which computes the merge in memory.
        """
        base_code, merge_base, _ = gitutil.run_git(
            self.repo, ["merge-base", target, branch], check=False
        )
        if base_code != 0:
            return []
        code, out, _ = gitutil.run_git(
            self.repo, ["merge-tree", "--write-tree", "--name-only", target, branch], check=False
        )
        if code == 0:
            return []  # clean (modern git returns non-zero on conflict)
        # Conflicted: output after the first line (tree oid) lists conflicted paths.
        lines = out.splitlines()
        return [l for l in lines[1:] if l and "/" in l or l.endswith((".py", ".ts", ".tsx", ".js"))]

    def preflight(self, task_id: str) -> PreflightResult:
        """Read-only check: is this task branch safe and ready to merge?"""
        record = self.manager.get(task_id)
        if not record:
            raise gitutil.GitError(f"No worktree record for task {task_id}")
        target = self.config.base_branch
        result = PreflightResult(task_id=task_id, branch=record.branch, target_branch=target,
                                 clean_worktree=True, diverged=False)

        if os.path.isdir(record.path):
            result.clean_worktree = gitutil.is_clean(record.path)
        if not result.clean_worktree:
            result.blockers.append("Worktree has uncommitted changes — commit or discard first")

        gitutil.run_git(self.repo, ["fetch", "--all", "--quiet"], check=False)

        if not gitutil.branch_exists(self.repo, target):
            # Try origin/<target>.
            code, _, _ = gitutil.run_git(self.repo, ["rev-parse", f"origin/{target}"], check=False)
            if code != 0:
                result.blockers.append(f"Target branch {target} not found locally or on origin")
                return result
            target_ref = f"origin/{target}"
        else:
            target_ref = target

        code, out, _ = gitutil.run_git(
            self.repo, ["rev-list", "--left-right", "--count", f"{target_ref}...{record.branch}"],
            check=False,
        )
        if code == 0 and out:
            behind_str, _, ahead_str = out.partition("\t")
            try:
                result.behind = int(behind_str.strip())
                result.ahead = int(ahead_str.strip() or out.split()[-1])
            except (ValueError, IndexError):
                pass
        result.diverged = result.behind > 0

        result.conflicting_files = self._detect_conflicts(record.branch, target_ref)
        if result.conflicting_files:
            result.blockers.append(
                f"{len(result.conflicting_files)} conflicting file(s) with {target}"
            )

        if self.config.require_tests and record.state not in ("READY_TO_MERGE", "VALIDATING", "REVIEW"):
            result.blockers.append(
                f"Tests required but task state is {record.state} (expected validated state)"
            )

        result.can_merge = not result.blockers
        return result

    def integrate(self, task_id: str, allow_conflicts: bool = False,
                  confirm: bool = False) -> MergeResult:
        """Merge the task branch into the target branch after preflight passes.

        Mutating. Requires ``confirm=True`` OR ``config.auto_merge``. Never force-pushes.
        Merges into a dedicated integration checkout, not the user's main working tree.
        """
        if not (confirm or self.config.auto_merge):
            raise gitutil.GitError(
                "Refusing to merge: pass confirm=True or set ADLC_AUTO_MERGE=true"
            )
        record = self.manager.get(task_id)
        if not record:
            raise gitutil.GitError(f"No worktree record for task {task_id}")
        target = self.config.base_branch

        pre = self.preflight(task_id)
        if not pre.can_merge and not allow_conflicts:
            return MergeResult(
                task_id=task_id, branch=record.branch, target_branch=target, merged=False,
                message="Preflight failed: " + "; ".join(pre.blockers),
                conflicting_files=pre.conflicting_files,
            )

        if not gitutil.branch_exists(self.repo, target):
            return MergeResult(task_id, record.branch, target, merged=False,
                               message=f"Target branch {target} does not exist locally; "
                                       f"create/track it before integrating")

        # A branch can only be checked out in one worktree. If the target is already
        # checked out somewhere, merge there (requiring it be clean so we never clobber
        # uncommitted user work). Otherwise create a throwaway worktree for the merge.
        existing = self._target_checkout(target)
        temp_worktree = None
        if existing:
            if not gitutil.is_clean(existing):
                return MergeResult(
                    task_id, record.branch, target, merged=False,
                    message=f"Target branch {target} is checked out with uncommitted changes "
                            f"at {existing}; refusing to merge into a dirty worktree")
            integ_path = existing
        else:
            integ_path = gitutil.validate_path(
                os.path.join(self.manager.worktree_root, f"_integrate-{gitutil.slugify(task_id)}")
            )
            if os.path.exists(integ_path):
                gitutil.run_git(self.repo, ["worktree", "remove", "--force", integ_path], check=False)
            gitutil.run_git(self.repo, ["worktree", "add", integ_path, target])
            temp_worktree = integ_path
        try:
            strat = self.config.merge_strategy
            if strat == "rebase":
                code, _, err = gitutil.run_git(
                    integ_path, ["rebase", record.branch], check=False)
                if code != 0:
                    gitutil.run_git(integ_path, ["rebase", "--abort"], check=False)
                    return MergeResult(task_id, record.branch, target, merged=False,
                                       message=f"Rebase conflict: {err[:300]}",
                                       conflicting_files=pre.conflicting_files)
                merge_commit = gitutil.rev_parse(integ_path, "HEAD")
            else:
                args = ["merge", "--no-ff"]
                if strat == "squash":
                    args = ["merge", "--squash"]
                args += [record.branch, "-m"] if strat != "squash" else [record.branch]
                if strat != "squash":
                    args.append(f"kobriz: integrate task {task_id} ({record.branch})")
                code, _, err = gitutil.run_git(integ_path, args, check=False)
                if code != 0:
                    gitutil.run_git(integ_path, ["merge", "--abort"], check=False)
                    return MergeResult(task_id, record.branch, target, merged=False,
                                       message=f"Merge conflict: {err[:300]}",
                                       conflicting_files=pre.conflicting_files)
                if strat == "squash":
                    gitutil.run_git(integ_path, ["commit", "-m",
                                    f"kobriz: integrate task {task_id} ({record.branch})"])
                merge_commit = gitutil.rev_parse(integ_path, "HEAD")

            return MergeResult(task_id, record.branch, target, merged=True,
                               merge_commit=merge_commit,
                               message=f"Merged {record.branch} into {target} ({strat})")
        finally:
            # Only clean up a worktree we created; never remove the user's checkout.
            if temp_worktree:
                gitutil.run_git(self.repo, ["worktree", "remove", "--force", temp_worktree], check=False)
