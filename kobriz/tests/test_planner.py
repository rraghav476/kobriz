"""Dependency-aware planner tests."""

from planner import build_plan, classify, agent_for
from task_client import Task


def _t(tid, title="", desc="", deps=None, kind=None, labels=None):
    return Task(id=tid, title=title, description=desc, dependencies=deps or [],
                kind=kind, labels=labels or [])


def test_classify_backend():
    assert classify(_t("1", "Add user API endpoint", "server database model")) == "backend"


def test_classify_frontend():
    assert classify(_t("2", "Build dashboard component", "react page UI")) == "frontend"


def test_classify_coordinated():
    assert classify(_t("3", "API and dashboard", "backend endpoint plus react component")) == "coordinated"


def test_explicit_kind_wins():
    assert classify(_t("4", "anything", kind="frontend")) == "frontend"


def test_agent_mapping():
    assert agent_for("backend") == "backend-developer"
    assert agent_for("frontend") == "frontend-developer"
    assert agent_for("coordinated") == "manager"


def test_topological_batches_respect_deps():
    tasks = [_t("A"), _t("B", deps=["A"]), _t("C", deps=["A"]), _t("D", deps=["B", "C"])]
    plan = build_plan(tasks, max_concurrency=5)
    order = [tid for batch in plan.batches for tid in batch]
    assert order.index("A") < order.index("B")
    assert order.index("B") < order.index("D")
    assert order.index("C") < order.index("D")


def test_concurrency_bound():
    tasks = [_t(x) for x in ["A", "B", "C", "D", "E"]]  # all independent
    plan = build_plan(tasks, max_concurrency=2)
    assert all(len(b) <= 2 for b in plan.batches)
    assert sum(len(b) for b in plan.batches) == 5


def test_cycle_detection():
    tasks = [_t("A", deps=["B"]), _t("B", deps=["A"])]
    plan = build_plan(tasks, max_concurrency=2)
    assert plan.cycles  # A<->B cycle reported, not silently scheduled


def test_unknown_dependency_blocks():
    tasks = [_t("A", deps=["GHOST"])]
    plan = build_plan(tasks, max_concurrency=2)
    assert "GHOST" in plan.blocked.get("A", [])
