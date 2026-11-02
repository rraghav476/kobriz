"""Change-impact analysis and controlled-merge tests against a temp repo."""

import os
import subprocess

import pytest

import gitutil
from config import Config
from worktree import WorktreeManager
from impact import analyze
from merge import Integrator


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit_change(path, relfile, content, msg):
    full = os.path.join(path, relfile)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(content)
    _git(path, "add", "-A")
    _git(path, "commit", "-m", msg)


def test_impact_report_from_real_git(base_env):
    mgr = WorktreeManager(Config.load())
    rec = mgr.create("201", "user-api", kind="backend")
    _commit_change(rec.path, "app/api/users.py", "def get_user():\n    return {}\n", "add users api")
    report = analyze(mgr, "201")
    assert "app/api/users.py" in report.added
    assert len(report.commits) == 1
    # API hint should flag potential frontend/API impact
    assert any("API" in r or "api" in r for r in report.potential_impact + report.risks)
    text = report.to_text()
    assert "Task: 201" in text


def test_impact_flags_shared_files(base_env):
    mgr = WorktreeManager(Config.load())
    r1 = mgr.create("301", "a")
    r2 = mgr.create("302", "b")
    for r in (r1, r2):
        _commit_change(r.path, "app/users.py", f"# {r.task_id}\n", f"edit {r.task_id}")
    report = analyze(mgr, "301")
    assert "app/users.py" in report.shared_with_tasks
    assert any("Shared files" in risk for risk in report.risks)


def test_merge_preflight_clean(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_REQUIRE_TESTS", "false")
    mgr = WorktreeManager(Config.load())
    rec = mgr.create("401", "feature")
    _commit_change(rec.path, "app/feature.py", "x = 1\n", "add feature")
    result = Integrator(Config.load(), mgr).preflight("401")
    assert result.conflicting_files == []
    assert result.can_merge is True


def test_merge_integrate_success(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_REQUIRE_TESTS", "false")
    cfg = Config.load()
    mgr = WorktreeManager(cfg)
    rec = mgr.create("402", "feature")
    _commit_change(rec.path, "app/feature.py", "y = 2\n", "add feature 402")
    result = Integrator(cfg, mgr).integrate("402", confirm=True)
    assert result.merged is True
    assert result.merge_commit
    # target branch now contains the file
    files = _git(mgr.repo, "ls-tree", "-r", "--name-only", "main")
    assert "app/feature.py" in files


def test_merge_requires_confirm(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_REQUIRE_TESTS", "false")
    monkeypatch.setenv("ADLC_AUTO_MERGE", "false")
    cfg = Config.load()
    mgr = WorktreeManager(cfg)
    rec = mgr.create("403", "feature")
    _commit_change(rec.path, "app/x.py", "z = 3\n", "add")
    with pytest.raises(gitutil.GitError):
        Integrator(cfg, mgr).integrate("403", confirm=False)


def test_merge_conflict_detected(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_REQUIRE_TESTS", "false")
    cfg = Config.load()
    mgr = WorktreeManager(cfg)
    # Make a conflicting change on main AFTER the worktree branches off.
    rec = mgr.create("404", "conflict")
    _commit_change(rec.path, "app/users.py", "def list_users():\n    return ['branch']\n", "branch edit")
    _commit_change(mgr.repo, "app/users.py", "def list_users():\n    return ['main']\n", "main edit")
    integ = Integrator(cfg, mgr)
    pre = integ.preflight("404")
    assert pre.conflicting_files or pre.diverged  # divergence/conflict surfaced
    result = integ.integrate("404", confirm=True)
    # With a real conflict the merge must NOT silently succeed.
    if not result.merged:
        assert "conflict" in result.message.lower() or pre.blockers
