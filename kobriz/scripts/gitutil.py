"""Safe git helpers for the kobriz ADLC plugin.

All git invocations go through :func:`run_git`, which uses a list argv (never a shell
string) so task IDs, branch names and paths cannot inject shell commands. Paths and
branch names are validated before use.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import List, Optional, Tuple

_BRANCH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class GitError(RuntimeError):
    """Raised when a git command fails."""


def run_git(repo: str, args: List[str], check: bool = True) -> Tuple[int, str, str]:
    """Run ``git -C <repo> <args...>`` with no shell. Returns (code, stdout, stderr)."""
    if not isinstance(args, list):
        raise TypeError("git args must be a list (no shell string)")
    cmd = ["git", "-C", repo, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def repo_root(path: str) -> str:
    """Return the top-level directory of the git repo containing ``path``."""
    code, out, err = run_git(path, ["rev-parse", "--show-toplevel"], check=False)
    if code != 0:
        raise GitError(f"{path!r} is not inside a git repository: {err}")
    return out


def is_clean(repo: str) -> bool:
    """True if the working tree has no uncommitted changes (tracked or staged)."""
    _, out, _ = run_git(repo, ["status", "--porcelain"])
    return out == ""


def current_branch(repo: str) -> str:
    _, out, _ = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out


def rev_parse(repo: str, ref: str) -> str:
    _, out, _ = run_git(repo, ["rev-parse", ref])
    return out


def branch_exists(repo: str, branch: str) -> bool:
    code, _, _ = run_git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
    return code == 0


def validate_branch_name(name: str) -> None:
    """Reject branch names with unsafe characters."""
    if not name or len(name) > 240:
        raise GitError(f"Invalid branch name: {name!r}")
    for segment in name.split("/"):
        if not _BRANCH_SEGMENT_RE.match(segment):
            raise GitError(f"Invalid branch segment {segment!r} in {name!r}")


def slugify(text: str, max_len: int = 40) -> str:
    """Make a safe branch segment out of free text."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "task"


def list_worktrees(repo: str) -> List[dict]:
    """Return parsed ``git worktree list --porcelain`` entries."""
    _, out, _ = run_git(repo, ["worktree", "list", "--porcelain"])
    entries: List[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.strip() == "detached":
            cur["detached"] = True
    if cur:
        entries.append(cur)
    return entries


def validate_path(path: str) -> str:
    """Normalize and validate a filesystem path intended for a worktree."""
    norm = os.path.abspath(os.path.expanduser(path))
    if norm in ("/", os.path.expanduser("~")):
        raise GitError(f"Refusing to use unsafe worktree path: {norm}")
    return norm
