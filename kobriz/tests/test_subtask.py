"""Tests for subtask creation (task splitting) via the REST client."""

import json

import pytest

from config import Config
from task_client import RestTaskClient, Task
from test_task_client import FakeTransport, _client


def test_create_subtask_body_and_parent(base_env):
    t = FakeTransport({("POST", "/tasks"): (201, {"id": "T-10", "title": "Child A"})})
    client, _ = _client(base_env, t)
    sub = client.create_subtask("T-1", "Child A", description="do A", extra={"kind": "backend"})
    assert isinstance(sub, Task) and sub.id == "T-10"
    body = json.loads(t.calls[0]["body"])
    assert body["title"] == "Child A"
    assert body["description"] == "do A"
    assert body["parent_id"] == "T-1"          # default parent field
    assert body["kind"] == "backend"


def test_create_subtask_custom_parent_field_and_path(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_TASK_SUBTASK_PATH", "/issues")
    monkeypatch.setenv("ADLC_TASK_PARENT_FIELD", "epic_id")
    t = FakeTransport({("POST", "/issues"): (201, {"id": "I-9", "title": "C"})})
    client, _ = _client(base_env, t)
    client.create_subtask("E-2", "C")
    assert t.calls[0]["url"].endswith("/issues")
    body = json.loads(t.calls[0]["body"])
    assert body["epic_id"] == "E-2"
    assert "parent_id" not in body


def test_create_subtask_respects_field_map(base_env, monkeypatch):
    # Provider calls title "summary"; the written body must use the provider's name.
    monkeypatch.setenv("ADLC_TASK_FIELD_MAP_JSON", json.dumps({"summary": "title"}))
    t = FakeTransport({("POST", "/tasks"): (201, {"id": "T-11", "summary": "Mapped"})})
    client, _ = _client(base_env, t)
    sub = client.create_subtask("T-1", "Mapped")
    body = json.loads(t.calls[0]["body"])
    assert body["summary"] == "Mapped"         # canonical 'title' -> provider 'summary'
    assert sub.title == "Mapped"               # response mapped back


def test_create_subtask_handles_bare_response(base_env):
    # Provider returns no recognizable id; client still returns a Task, not a crash.
    t = FakeTransport({("POST", "/tasks"): (201, {"ok": True})})
    client, _ = _client(base_env, t)
    sub = client.create_subtask("T-1", "X")
    assert sub.title == "X"
    assert "T-1" in sub.id
