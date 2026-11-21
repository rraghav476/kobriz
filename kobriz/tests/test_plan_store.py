"""Persisted plans and the approval gate on worktree creation and merge."""

import json
import os
import subprocess
import sys

import pytest

import gitutil
from config import Config
from merge import Integrator
from plan_store import (APPROVED, CHANGES_REQUESTED, PENDING, SUPERSEDED, PlanError,
                        PlanGateError, PlanStore, content_hash,
                        render_markdown)
from worktree import WorktreeManager

ADLC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "adlc.py"))


def _plan(task_ids=("101",), approval_task="900"):
    return {"title": "Users API", "approval_task_id": approval_task,
            "tasks": [{"id": t, "title": f"task {t}", "kind": "backend",
                       "agent": "backend-developer", "affected_files": ["app/users.py"]}
                      for t in task_ids],
            "batches": [list(task_ids)], "risks": ["touches users table"]}


def _post(store, record):
    return store.record_posted(record["plan_id"], "900", "plan review")


def _approve_both(store, record):
    short = record["content_hash"][:12]
    _post(store, record)
    store.approve_session(record["plan_id"], short, by="Reviewer")
    return store.record_provider_approval(record["plan_id"], "900", "plan approved",
                                          by="Reviewer", evidence="status set in tracker")


def test_create_is_pending_and_renders_markdown(gated_env):
    cfg = Config.load()
    store = PlanStore(cfg)
    rec = store.create(_plan(), by="manager")
    assert rec["state"] == PENDING
    assert os.path.isfile(os.path.join(store.dir, f"{rec['plan_id']}.json"))
    md = render_markdown(rec, cfg)
    assert rec["content_hash"][:12] in md and "Plan Approved" in md


def test_kobriz_dir_ignores_itself(gated_env):
    store = PlanStore(Config.load())
    store.create(_plan())
    status = subprocess.run(["git", "-C", gated_env, "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert ".kobriz" not in status


def test_invalid_plan_rejected(gated_env):
    store = PlanStore(Config.load())
    with pytest.raises(PlanError):
        store.create({"title": "x", "tasks": []})
    bad = _plan()
    del bad["approval_task_id"]
    with pytest.raises(PlanError):
        store.create(bad)
    dup = _plan(task_ids=("1", "1"))
    with pytest.raises(PlanError):
        store.create(dup)


def test_both_approvals_needed(gated_env):
    store = PlanStore(Config.load())
    rec = store.create(_plan())
    rec = store.approve_session(rec["plan_id"], rec["content_hash"][:12], by="Reviewer")
    assert rec["state"] == PENDING
    assert not store.check_task("101")["ok"]
    _post(store, rec)
    rec = store.record_provider_approval(rec["plan_id"], "900", "PLAN APPROVED", by="Reviewer")
    assert rec["state"] == APPROVED
    assert store.check_task("101")["ok"]


def test_session_approval_needs_matching_hash(gated_env):
    store = PlanStore(Config.load())
    rec = store.create(_plan())
    with pytest.raises(PlanError):
        store.approve_session(rec["plan_id"], "deadbeefdead", by="Reviewer")
    with pytest.raises(PlanError):
        store.approve_session(rec["plan_id"], rec["content_hash"][:4], by="Reviewer")
    with pytest.raises(PlanError):
        store.approve_session(rec["plan_id"], rec["content_hash"][:12], by=" ")


def test_provider_approval_checks_task_and_status(gated_env):
    store = PlanStore(Config.load())
    rec = store.create(_plan())
    _post(store, rec)
    with pytest.raises(PlanError):
        store.record_provider_approval(rec["plan_id"], "901", "plan approved")
    with pytest.raises(PlanError):
        store.record_provider_approval(rec["plan_id"], "900", "in progress")


def test_revision_voids_approval(gated_env):
    store = PlanStore(Config.load())
    rec = _approve_both(store, store.create(_plan()))
    assert rec["state"] == APPROVED
    changed = _plan()
    changed["risks"].append("new migration")
    rec = store.revise(rec["plan_id"], changed, note="added migration")
    assert rec["state"] == PENDING
    assert rec["approvals"] == {"session": None, "provider": None}
    assert not store.check_task("101")["ok"]


def test_out_of_band_edit_detected(gated_env):
    store = PlanStore(Config.load())
    rec = _approve_both(store, store.create(_plan()))
    path = os.path.join(store.dir, f"{rec['plan_id']}.json")
    data = json.load(open(path))
    data["content"]["tasks"].append({"id": "999", "title": "sneaked in"})
    json.dump(data, open(path, "w"))
    result = store.check_task("101")
    assert not result["ok"] and "hash mismatch" in result["reason"]


def test_request_changes_then_revise(gated_env):
    store = PlanStore(Config.load())
    rec = store.create(_plan())
    rec = store.request_changes(rec["plan_id"], by="Reviewer", note="split the migration")
    assert rec["state"] == CHANGES_REQUESTED
    with pytest.raises(PlanError):
        store.approve_session(rec["plan_id"], rec["content_hash"][:12], by="Reviewer")
    rec = store.revise(rec["plan_id"], _plan(task_ids=("101", "102")))
    assert rec["state"] == PENDING


def test_new_plan_supersedes_overlapping(gated_env):
    store = PlanStore(Config.load())
    old = _approve_both(store, store.create(_plan(task_ids=("101", "102"))))
    new = store.create(_plan(task_ids=("102", "103")))
    assert store.get(old["plan_id"])["state"] == SUPERSEDED
    assert store.find_for_task("102")["plan_id"] == new["plan_id"]
    # 101 was only in the superseded plan, so it is no longer covered.
    assert store.check_task("101")["plan_id"] is None


def test_session_only_mode(gated_env, monkeypatch):
    monkeypatch.setenv("ADLC_PLAN_APPROVAL", "session")
    store = PlanStore(Config.load())
    plan = _plan()
    del plan["approval_task_id"]
    rec = store.create(plan)
    rec = store.approve_session(rec["plan_id"], rec["content_hash"][:12], by="Reviewer")
    assert rec["state"] == APPROVED


def test_worktree_create_gated(gated_env):
    cfg = Config.load()
    mgr = WorktreeManager(cfg)
    with pytest.raises(PlanGateError):
        mgr.create("101", "user-api", kind="backend")
    store = PlanStore(cfg)
    _approve_both(store, store.create(_plan()))
    rec = mgr.create("101", "user-api", kind="backend")
    assert os.path.isdir(rec.path)
    with pytest.raises(PlanGateError):
        mgr.create("555", "not-in-plan")


def test_merge_gated_after_revision(gated_env):
    cfg = Config.load()
    store = PlanStore(cfg)
    rec = _approve_both(store, store.create(_plan()))
    mgr = WorktreeManager(cfg)
    wt = mgr.create("101", "user-api", kind="backend")
    with open(os.path.join(wt.path, "app", "users.py"), "a") as fh:
        fh.write("\n# change\n")
    subprocess.run(["git", "-C", wt.path, "commit", "-qam", "change"], check=True)
    mgr.set_state("101", "READY_TO_MERGE")
    changed = _plan()
    changed["title"] = "Users API v2"
    store.revise(rec["plan_id"], changed)
    with pytest.raises(PlanGateError):
        Integrator(cfg, mgr).integrate("101", confirm=True)


def test_gate_off_allows(base_env):
    mgr = WorktreeManager(Config.load())
    assert os.path.isdir(mgr.create("101", "user-api").path)


def test_config_requires_approved_status(gated_env, monkeypatch):
    monkeypatch.delenv("ADLC_PLAN_APPROVED_STATUS")
    assert any("ADLC_PLAN_APPROVED_STATUS" in e for e in Config.load().validate())
    monkeypatch.setenv("ADLC_PLAN_APPROVAL", "session")
    assert Config.load().validate() == []
    monkeypatch.setenv("ADLC_PLAN_APPROVAL", "anyone")
    assert any("ADLC_PLAN_APPROVAL" in e for e in Config.load().validate())


def test_cli_create_check_exit_codes(gated_env, tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(_plan()))
    env = dict(os.environ)
    out = subprocess.run([sys.executable, ADLC, "plan", "create", "--file", str(plan_file)],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    view = json.loads(out.stdout)["plan"]
    assert view["short_hash"] == content_hash(_plan())[:12]
    check = subprocess.run([sys.executable, ADLC, "plan", "check", "101"],
                           capture_output=True, text=True, env=env)
    assert check.returncode == 7
    wt = subprocess.run([sys.executable, ADLC, "worktree", "create", "101", "x"],
                        capture_output=True, text=True, env=env)
    assert wt.returncode == 7 and "Plan approval required" in wt.stderr
    ok = subprocess.run([sys.executable, ADLC, "plan", "approve", view["plan_id"],
                         "--hash", view["short_hash"], "--by", "Reviewer"],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr
    posted = subprocess.run([sys.executable, ADLC, "plan", "posted", view["plan_id"],
                             "--task", "900", "--status", "plan review"],
                            capture_output=True, text=True, env=env)
    assert posted.returncode == 0, posted.stderr
    prov = subprocess.run([sys.executable, ADLC, "plan", "record-provider-approval",
                           view["plan_id"], "--task", "900", "--status", "Plan Approved"],
                          capture_output=True, text=True, env=env)
    assert prov.returncode == 0, prov.stderr
    check = subprocess.run([sys.executable, ADLC, "plan", "check", "101"],
                           capture_output=True, text=True, env=env)
    assert check.returncode == 0
    legacy = subprocess.run([sys.executable, ADLC, "plan", "--help"],
                            capture_output=True, text=True, env=env)
    assert legacy.returncode == 0


def test_identical_plans_get_distinct_ids(gated_env):
    store = PlanStore(Config.load())
    first = store.create(_plan())
    second = store.create(_plan())
    assert first["plan_id"] != second["plan_id"]
    assert store.get(first["plan_id"])["state"] == SUPERSEDED
    assert store.get(second["plan_id"])["state"] == PENDING


def test_stale_tracker_approval_does_not_carry_over(gated_env):
    store = PlanStore(Config.load())
    rec = _approve_both(store, store.create(_plan()))
    changed = _plan()
    changed["title"] = "Users API v2"
    rec = store.revise(rec["plan_id"], changed)
    # The tracker task still says "plan approved" from v1; that must not approve v2.
    with pytest.raises(PlanError):
        store.record_provider_approval(rec["plan_id"], "900", "plan approved")
    with pytest.raises(PlanError):
        store.record_posted(rec["plan_id"], "900", "plan approved")
    _post(store, rec)
    rec = store.record_provider_approval(rec["plan_id"], "900", "plan approved")
    assert rec["approvals"]["provider"]["hash"] == rec["content_hash"]


def test_relaxed_mode_applies_to_pending_plan(gated_env, monkeypatch):
    store = PlanStore(Config.load())
    rec = store.create(_plan())
    store.approve_session(rec["plan_id"], rec["content_hash"][:12], by="Reviewer")
    assert not store.check_task("101")["ok"]
    monkeypatch.setenv("ADLC_PLAN_APPROVAL", "session")
    assert PlanStore(Config.load()).check_task("101")["ok"]


@pytest.mark.parametrize("value,gated", [("false", False), ("0", False), ("off", False),
                                         ("disabled", True), ("n", True), ("true", True)])
def test_gate_fails_closed(base_env, monkeypatch, value, gated):
    monkeypatch.setenv("ADLC_REQUIRE_PLAN_APPROVAL", value)
    assert Config.load().require_plan_approval is gated
