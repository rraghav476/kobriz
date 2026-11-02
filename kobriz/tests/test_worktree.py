"""Git worktree lifecycle tests against a temp repository."""

import os
import subprocess

import pytest

import gitutil
from config import Config
from worktree import WorktreeManager


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_create_worktree_and_branch(base_env):
    mgr = WorktreeManager(Config.load())
    rec = mgr.create("101", "user-api", kind="backend", owner_agent="backend-developer")
    assert os.path.isdir(rec.path)
    assert rec.branch.startswith("adlc/task-101")
    assert "backend" in rec.branch
    # branch exists in repo
    assert gitutil.branch_exists(mgr.repo, rec.branch)
    # tracked in state
    assert mgr.get("101").branch == rec.branch


def test_branch_naming_safe(base_env):
    mgr = WorktreeManager(Config.load())
    name = mgr.branch_name("101", "User API!!!", kind="backend")
    gitutil.validate_branch_name(name)  # must not raise
    assert " " not in name and "!" not in name


def test_duplicate_create_refused(base_env):
    mgr = WorktreeManager(Config.load())
    mgr.create("101", "user-api")
    with pytest.raises(gitutil.GitError):
        mgr.create("101", "user-api")


def test_isolation_two_worktrees(base_env):
    mgr = WorktreeManager(Config.load())
    r1 = mgr.create("101", "user-api")
    r2 = mgr.create("102", "dashboard")
    assert r1.path != r2.path
    assert r1.branch != r2.branch
    # editing in one worktree does not affect the other
    (open(os.path.join(r1.path, "app", "users.py"), "a")).write("\n# task101\n")
    with open(os.path.join(r2.path, "app", "users.py")) as fh:
        assert "task101" not in fh.read()


def test_changed_files_and_shared_detection(base_env):
    mgr = WorktreeManager(Config.load())
    r1 = mgr.create("101", "a")
    r2 = mgr.create("102", "b")
    # both modify the same file -> shared
    for r in (r1, r2):
        p = os.path.join(r.path, "app", "users.py")
        with open(p, "a") as fh:
            fh.write(f"\n# edit {r.task_id}\n")
        _git(r.path, "add", "-A")
        _git(r.path, "commit", "-m", f"edit {r.task_id}")
    assert "app/users.py" in mgr.changed_files("101")
    shared = mgr.detect_shared_files()
    assert "app/users.py" in shared
    assert set(shared["app/users.py"]) == {"101", "102"}


def test_failed_worktree_retained(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_KEEP_FAILED_WORKTREES", "true")
    mgr = WorktreeManager(Config.load())
    mgr.create("103", "auth")
    mgr.set_state("103", "FAILED", note="tests failed")
    with pytest.raises(gitutil.GitError):
        mgr.remove("103")           # retained for debugging
    assert mgr.get("103") is not None
    # force override works
    assert mgr.remove("103", force=True) is True
    assert mgr.get("103") is None


def test_remove_refuses_dirty_worktree(base_env):
    mgr = WorktreeManager(Config.load())
    rec = mgr.create("104", "x")
    with open(os.path.join(rec.path, "newfile.txt"), "w") as fh:
        fh.write("uncommitted")
    _git(rec.path, "add", "-A")
    with pytest.raises(gitutil.GitError):
        mgr.remove("104")           # uncommitted changes protected
    assert mgr.remove("104", force=True) is True


def test_main_checkout_untouched_when_dirty(base_env):
    """Creating a worktree must never clean the user's dirty main checkout."""
    mgr = WorktreeManager(Config.load())
    dirty = os.path.join(mgr.repo, "WIP.txt")
    with open(dirty, "w") as fh:
        fh.write("work in progress")
    assert not gitutil.is_clean(mgr.repo)
    mgr.create("105", "y")
    # the user's uncommitted file is still there
    assert os.path.exists(dirty)
    assert not gitutil.is_clean(mgr.repo)
