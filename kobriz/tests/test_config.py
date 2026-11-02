"""Tests for configuration loading, validation and secret redaction."""

import json

import pytest

from config import Config, redact, redact_text


def test_rest_config_valid(base_env):
    cfg = Config.load()
    assert cfg.source_type == "rest"
    assert cfg.validate() == []


def test_rest_requires_base_url(monkeypatch, temp_repo):
    monkeypatch.setenv("ADLC_TASK_SOURCE_TYPE", "rest")
    monkeypatch.setenv("ADLC_REPOSITORY_ROOT", temp_repo)
    monkeypatch.delenv("ADLC_TASK_API_BASE_URL", raising=False)
    errors = Config.load().validate()
    assert any("API_BASE_URL" in e for e in errors)


def test_bearer_requires_token(monkeypatch, temp_repo):
    monkeypatch.setenv("ADLC_TASK_SOURCE_TYPE", "rest")
    monkeypatch.setenv("ADLC_TASK_API_BASE_URL", "https://x.example.com")
    monkeypatch.setenv("ADLC_REPOSITORY_ROOT", temp_repo)
    monkeypatch.delenv("ADLC_TASK_API_TOKEN", raising=False)
    errors = Config.load().validate()
    assert any("API_TOKEN" in e for e in errors)


def test_invalid_concurrency(monkeypatch, base_env):
    monkeypatch.setenv("ADLC_MAX_CONCURRENCY", "0")
    errors = Config.load().validate()
    assert any("CONCURRENCY" in e for e in errors)


def test_invalid_branch_name(monkeypatch, base_env):
    monkeypatch.setenv("ADLC_BASE_BRANCH", "bad branch name")
    errors = Config.load().validate()
    assert any("BASE_BRANCH" in e for e in errors)


def test_extra_headers_parse(monkeypatch, base_env):
    monkeypatch.setenv("ADLC_TASK_EXTRA_HEADERS_JSON", json.dumps({"X-Team": "core"}))
    cfg = Config.load()
    assert cfg.extra_headers == {"X-Team": "core"}


def test_extra_headers_invalid_json(monkeypatch, base_env):
    monkeypatch.setenv("ADLC_TASK_EXTRA_HEADERS_JSON", "{not json")
    with pytest.raises(Exception):
        Config.load()


def test_redaction_masks_secrets():
    data = {"api_token": "abc", "nested": {"password": "p", "name": "ok"}, "list": [{"secret": "s"}]}
    red = redact(data)
    assert red["api_token"] == "***REDACTED***"
    assert red["nested"]["password"] == "***REDACTED***"
    assert red["nested"]["name"] == "ok"
    assert red["list"][0]["secret"] == "***REDACTED***"


def test_redacted_config_hides_token(base_env):
    red = Config.load().redacted()
    assert red["api_token"] == "***REDACTED***"


def test_redact_text_scrubs_literal(base_env):
    cfg = Config.load()
    text = "the token is secret-token-123 do not leak"
    assert "secret-token-123" not in redact_text(text, cfg)
    assert "***REDACTED***" in redact_text(text, cfg)


def test_default_mode_is_mcp(monkeypatch, temp_repo):
    for k in list(__import__("os").environ):
        if k.startswith("ADLC_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ADLC_REPOSITORY_ROOT", temp_repo)
    cfg = Config.load()
    assert cfg.source_type == "mcp"
    assert cfg.auto_merge is False  # safe default
