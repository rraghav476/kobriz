"""Tests for the persisted config-file layer and the setup flow."""

import json
import os
import stat

import pytest

import config as config_mod
from config import Config, save_config_file, load_config_file, find_config_file


@pytest.fixture
def clean_env(tmp_path, monkeypatch, temp_repo):
    """Strip ADLC_* env and point the config file at a temp location."""
    for k in list(os.environ):
        if k.startswith("ADLC_") or k == "CLAUDE_PROJECT_DIR":
            monkeypatch.delenv(k, raising=False)
    cfg_path = str(tmp_path / ".kobriz" / "config.json")
    monkeypatch.setenv("ADLC_CONFIG_FILE", cfg_path)
    monkeypatch.setenv("ADLC_REPOSITORY_ROOT", temp_repo)
    return cfg_path


def test_unconfigured_by_default(clean_env):
    cfg = Config.load()
    assert cfg.is_configured() is False
    assert cfg.source_type == "mcp"


def test_file_supplies_values(clean_env):
    save_config_file({
        "ADLC_TASK_SOURCE_TYPE": "rest",
        "ADLC_TASK_API_BASE_URL": "https://tasks.example.com",
        "ADLC_TASK_API_TOKEN": "filetoken",
    }, path=clean_env)
    cfg = Config.load()
    assert cfg.source_type == "rest"
    assert cfg.api_base_url == "https://tasks.example.com"
    assert cfg.is_configured() is True
    assert cfg.config_file == clean_env


def test_env_overrides_file(clean_env, monkeypatch):
    save_config_file({"ADLC_TASK_SOURCE_TYPE": "rest",
                      "ADLC_TASK_API_BASE_URL": "https://file.example.com",
                      "ADLC_TASK_API_TOKEN": "t"}, path=clean_env)
    monkeypatch.setenv("ADLC_TASK_API_BASE_URL", "https://env.example.com")
    cfg = Config.load()
    assert cfg.api_base_url == "https://env.example.com"   # env wins over file


def test_file_is_owner_only(clean_env):
    save_config_file({"ADLC_TASK_API_TOKEN": "secret"}, path=clean_env)
    mode = stat.S_IMODE(os.stat(clean_env).st_mode)
    assert mode == 0o600


def test_json_map_from_file(clean_env):
    save_config_file({
        "ADLC_TASK_SOURCE_TYPE": "rest",
        "ADLC_TASK_API_BASE_URL": "https://x.example.com",
        "ADLC_TASK_API_TOKEN": "t",
        "ADLC_TASK_FIELD_MAP_JSON": {"ticket_id": "id"},   # stored as object, read as map
    }, path=clean_env)
    cfg = Config.load()
    assert cfg.field_map == {"ticket_id": "id"}


def test_save_merges_existing(clean_env):
    save_config_file({"ADLC_BASE_BRANCH": "develop"}, path=clean_env)
    save_config_file({"ADLC_MAX_CONCURRENCY": "5"}, path=clean_env)
    with open(clean_env) as fh:
        data = json.load(fh)
    assert data["ADLC_BASE_BRANCH"] == "develop"        # preserved
    assert data["ADLC_MAX_CONCURRENCY"] == "5"          # added


def test_is_configured_mcp(clean_env):
    save_config_file({"ADLC_TASK_SOURCE_TYPE": "mcp", "ADLC_MCP_SERVER": "jira"}, path=clean_env)
    assert Config.load().is_configured() is True


def test_is_configured_rest_auth_none(clean_env):
    save_config_file({"ADLC_TASK_SOURCE_TYPE": "rest",
                      "ADLC_TASK_API_BASE_URL": "https://x.example.com",
                      "ADLC_TASK_AUTH_TYPE": "none"}, path=clean_env)
    assert Config.load().is_configured() is True   # no token needed when auth=none


def test_malformed_file_raises(clean_env):
    os.makedirs(os.path.dirname(clean_env), exist_ok=True)
    with open(clean_env, "w") as fh:
        fh.write("{not json")
    with pytest.raises(config_mod.ConfigError):
        Config.load()


def test_find_config_file(clean_env):
    assert find_config_file() is None
    save_config_file({"ADLC_BASE_BRANCH": "main"}, path=clean_env)
    assert find_config_file() == clean_env
