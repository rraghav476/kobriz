"""Shared pytest fixtures for the kobriz test suite.

Git integration tests run against a throwaway local repository created in a temp dir.
No production credentials, network access, or the user's real repo are ever touched.
"""

import os
import subprocess
import sys

import pytest

# Make the plugin's scripts importable.
SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, SCRIPTS)


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


@pytest.fixture
def temp_repo(tmp_path):
    """A fresh git repo with an initial commit on branch ``main``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    r = str(repo)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test User")
    _git(r, "checkout", "-q", "-b", "main")
    (repo / "README.md").write_text("# test repo\n")
    (repo / "app").mkdir()
    (repo / "app" / "users.py").write_text("def list_users():\n    return []\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "initial")
    return r


@pytest.fixture
def base_env(temp_repo, tmp_path, monkeypatch):
    """Environment configured for the temp repo in REST mode (no real network)."""
    # Isolate config-file discovery so tests never read a developer's real ~/.claude config.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj_isolated"))
    monkeypatch.setenv("ADLC_CONFIG_FILE", str(tmp_path / "no_such_config.json"))
    monkeypatch.setenv("ADLC_TASK_SOURCE_TYPE", "rest")
    monkeypatch.setenv("ADLC_TASK_API_BASE_URL", "https://tasks.example.com")
    monkeypatch.setenv("ADLC_TASK_API_TOKEN", "secret-token-123")
    monkeypatch.setenv("ADLC_REPOSITORY_ROOT", temp_repo)
    monkeypatch.setenv("ADLC_BASE_BRANCH", "main")
    monkeypatch.setenv("ADLC_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    monkeypatch.setenv("ADLC_MAX_CONCURRENCY", "2")
    return temp_repo
