"""Tests for the REST task client using an injected fake transport (no network)."""

import json

import pytest

from config import Config
from task_client import RestTaskClient, Task, TaskClientError


class FakeTransport:
    """Records requests and returns scripted (status, body) responses by (method, path)."""

    def __init__(self, routes):
        self.routes = routes          # {(method, path_suffix): (status, body_obj)}
        self.calls = []

    def __call__(self, request):
        method = request.get_method()
        path = request.full_url
        self.calls.append({"method": method, "url": path,
                           "headers": dict(request.header_items()),
                           "body": request.data.decode() if request.data else None})
        for (m, suffix), (status, body) in self.routes.items():
            if m == method and path.endswith(suffix):
                return status, json.dumps(body) if body is not None else ""
        return 404, json.dumps({"error": "not found"})


def _client(base_env, transport, **extra_env):
    import os
    for k, v in extra_env.items():
        os.environ[k] = v
    cfg = Config.load()
    return RestTaskClient(cfg, opener=transport), cfg


def test_list_tasks_plain_array(base_env):
    t = FakeTransport({("GET", "/tasks"): (200, [{"id": "1", "title": "A"}, {"id": "2", "title": "B"}])})
    client, _ = _client(base_env, t)
    tasks = client.list_tasks()
    assert [x.id for x in tasks] == ["1", "2"]
    assert tasks[0].title == "A"


def test_list_tasks_envelope(base_env):
    t = FakeTransport({("GET", "/tasks"): (200, {"tasks": [{"id": "9", "title": "Z"}]})})
    client, _ = _client(base_env, t)
    assert client.list_tasks()[0].id == "9"


def test_auth_header_bearer(base_env):
    t = FakeTransport({("GET", "/tasks"): (200, [])})
    client, _ = _client(base_env, t)
    client.list_tasks()
    assert t.calls[0]["headers"].get("Authorization") == "Bearer secret-token-123"


def test_field_mapping(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_TASK_FIELD_MAP_JSON",
                       json.dumps({"ticket_id": "id", "summary": "title", "deps": "dependencies"}))
    t = FakeTransport({("GET", "/tasks"):
                       (200, [{"ticket_id": "T-5", "summary": "Do thing", "deps": ["T-1", "T-2"]}])})
    client, _ = _client(base_env, t)
    task = client.list_tasks()[0]
    assert task.id == "T-5"
    assert task.title == "Do thing"
    assert task.dependencies == ["T-1", "T-2"]


def test_status_mapping(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_TASK_STATUS_MAP_JSON", json.dumps({"IN_PROGRESS": "in-dev"}))
    t = FakeTransport({("PATCH", "/tasks/T-5/status"): (200, {"ok": True})})
    client, _ = _client(base_env, t)
    client.update_status("T-5", "IN_PROGRESS")
    body = json.loads(t.calls[0]["body"])
    assert body["status"] == "in-dev"   # mapped to provider's value


def test_get_task_missing_id_errors(base_env):
    t = FakeTransport({("GET", "/tasks/x"): (200, {"title": "no id here"})})
    client, _ = _client(base_env, t)
    with pytest.raises(TaskClientError):
        client.get_task("x")


def test_comment_requires_config(base_env):
    t = FakeTransport({})
    client, _ = _client(base_env, t)
    with pytest.raises(TaskClientError):
        client.add_comment("1", "hello")


def test_comment_posts_when_configured(base_env, monkeypatch):
    monkeypatch.setenv("ADLC_TASK_COMMENT_PATH", "/tasks/{task_id}/comments")
    t = FakeTransport({("POST", "/tasks/1/comments"): (201, {"id": "c1"})})
    client, _ = _client(base_env, t)
    resp = client.add_comment("1", "done")
    assert resp == {"id": "c1"}


def test_http_error_raises(base_env):
    t = FakeTransport({("GET", "/tasks"): (500, {"error": "boom"})})
    client, _ = _client(base_env, t)
    with pytest.raises(TaskClientError):
        client.list_tasks()
