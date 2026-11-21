"""The approval guard hook and the meeting-intake ledger."""

import json
import os
import subprocess
import sys

import pytest

from config import Config
from intake_store import IntakeStore, draft_key

GUARD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts",
                                     "guard-approval.py"))


def _guard(payload):
    return subprocess.run([sys.executable, GUARD], input=json.dumps(payload),
                          capture_output=True, text=True, env=dict(os.environ))


def _bash(cmd):
    return _guard({"tool_name": "Bash", "tool_input": {"command": cmd}})


@pytest.mark.parametrize("cmd", [
    "python3 /p/scripts/adlc.py plan approve plan-1 --hash abcdef123456 --by me",
    "python3 adlc.py   plan   approve x --hash y --by z",
    "python3 -c 'from plan_store import PlanStore; s.approve_session(\"p\",\"h\",\"me\")'",
    "python3 adlc.py setup save --data '{\"ADLC_REQUIRE_PLAN_APPROVAL\": false}'",
    "python3 adlc.py setup save --data '{\"ADLC_PLAN_APPROVAL\": \"session\"}'",
    "python3 adlc.py setup save --data '{\"ADLC_PLAN_APPROVED_STATUS\": \"to do\"}'",
    "cat > .kobriz/plans/plan-1.json <<EOF\n{}\nEOF",
    "sed -i '' 's/x/y/' .kobriz/config.json",
])
def test_guard_blocks_bash(gated_env, cmd):
    result = _bash(cmd)
    assert result.returncode == 2, cmd
    assert "kobriz: blocked" in result.stderr


@pytest.mark.parametrize("cmd", [
    "python3 adlc.py plan create --file /tmp/p.json",
    "python3 adlc.py plan show plan-1 --markdown",
    "python3 adlc.py plan record-provider-approval plan-1 --task 900 --status 'Plan Approved'",
    "python3 adlc.py setup save --data '{\"ADLC_PLAN_APPROVAL\": \"both\"}'",
    "git status",
])
def test_guard_allows_bash(gated_env, cmd):
    assert _bash(cmd).returncode == 0, cmd


def test_guard_allows_first_status_setup(base_env, monkeypatch):
    monkeypatch.delenv("ADLC_PLAN_APPROVED_STATUS", raising=False)
    cmd = "python3 adlc.py setup save --data '{\"ADLC_PLAN_APPROVED_STATUS\": \"plan approved\"}'"
    assert _bash(cmd).returncode == 0


def test_guard_blocks_edit_under_kobriz(gated_env):
    blocked = _guard({"tool_name": "Write",
                      "tool_input": {"file_path": "/repo/.kobriz/plans/plan-1.json"}})
    assert blocked.returncode == 2
    allowed = _guard({"tool_name": "Edit", "tool_input": {"file_path": "/repo/app/users.py"}})
    assert allowed.returncode == 0


def test_guard_blocks_setting_approval_status_via_mcp(gated_env):
    blocked = _guard({"tool_name": "mcp__claude_ai_ClickUp__clickup_update_task",
                      "tool_input": {"task_id": "900", "status": "plan approved"}})
    assert blocked.returncode == 2
    nested = _guard({"tool_name": "mcp__clickup__clickup_execute_operator",
                     "tool_input": {"operator": "task.update_many",
                                    "args": {"tasks": [{"id": "900", "status": " PLAN APPROVED "}]}}})
    assert nested.returncode == 2
    review = _guard({"tool_name": "mcp__clickup__clickup_update_task",
                     "tool_input": {"task_id": "900", "status": "plan review"}})
    assert review.returncode == 0
    other = _guard({"tool_name": "mcp__granola__get_meetings",
                    "tool_input": {"q": "plan approved"}})
    assert other.returncode == 0


@pytest.mark.parametrize("tool,blocked", [
    ("mcp__claude_ai_Granola__get_meetings", False),
    ("mcp__claude_ai_Granola__search_meetings", False),
    ("mcp__claude_ai_Granola__get_meeting_transcript", False),
    ("mcp__claude_ai_Granola__update_summary", True),
    ("mcp__granola__add_note_to_folder", True),
    ("mcp__granola__generate_summary", True),
    ("mcp__granola__sign_out", True),
])
def test_guard_keeps_granola_read_only(tool, blocked):
    result = _guard({"tool_name": tool, "tool_input": {}})
    assert (result.returncode == 2) is blocked


def test_guard_ignores_garbage():
    result = subprocess.run([sys.executable, GUARD], input="not json",
                            capture_output=True, text=True)
    assert result.returncode == 0


def test_draft_key_is_stable():
    assert draft_key("Add CSV export to Users page") == draft_key("  add csv export, to users PAGE!")
    assert draft_key("Add CSV export") != draft_key("Add PDF export")


def test_intake_dedupes(gated_env):
    store = IntakeStore(Config.load())
    assert store.check("meet-1", "Add CSV export") is None
    store.record("meet-1", "Add CSV export", "86abc", meeting_title="Weekly sync")
    assert store.check("meet-1", "add csv export")["task_id"] == "86abc"
    assert store.check("meet-2", "Add CSV export") is None
    store.record("meet-1", "Add CSV export", "86abc")
    with pytest.raises(ValueError):
        store.record("meet-1", "Add CSV export", "86xyz")
    raw = json.dumps(store.show("meet-1"))
    assert "Weekly sync" in raw


def test_draft_key_handles_non_ascii_titles():
    a, b = draft_key("डैशबोर्ड ठीक करें"), draft_key("लॉगिन बग")
    assert a != b
    assert draft_key("Café menu") != draft_key("Cafe menu")
    assert draft_key("Ｆｉｘ login") == draft_key("fix login")


@pytest.mark.parametrize("payload", [
    {"tool_name": "Write", "tool_input": {"file_path": os.path.expanduser("~/.claude/kobriz/config.json"),
                                          "content": "{}"}},
    {"tool_name": "Write", "tool_input": {"file_path": "/tmp/a.sh",
                                          "content": "python3 x/adlc.py plan approve P --hash abcdef12 --by x"}},
    {"tool_name": "Edit", "tool_input": {"file_path": "/repo/.env", "old_string": "a",
                                         "new_string": "ADLC_REQUIRE_PLAN_APPROVAL=false"}},
    {"tool_name": "MultiEdit", "tool_input": {"file_path": "/repo/run.py", "edits": [
        {"old_string": "a", "new_string": "os.environ['ADLC_PLAN_APPROVAL'] = 'session'"}]}},
    {"tool_name": "Bash", "tool_input": {"command": "export ADLC_CONFIG_FILE=/tmp/mine.json"}},
])
def test_guard_blocks_review_bypasses(gated_env, payload):
    assert _guard(payload).returncode == 2


@pytest.mark.parametrize("payload", [
    {"tool_name": "Write", "tool_input": {"file_path": "/repo/docs/approval.md",
                                          "content": "Run `adlc.py plan approve <id> ...` yourself."}},
    {"tool_name": "Bash", "tool_input": {"command": "grep ADLC_PLAN_APPROVED_STATUS .env.example"}},
    {"tool_name": "mcp__clickup__clickup_filter_tasks",
     "tool_input": {"list_ids": ["1"], "statuses": ["plan approved"]}},
    {"tool_name": "mcp__clickup__clickup_get_task", "tool_input": {"task_id": "plan approved"}},
])
def test_guard_allows_reads_and_docs(gated_env, payload):
    assert _guard(payload).returncode == 0


def test_guard_blocks_status_on_create(gated_env):
    payload = {"tool_name": "mcp__clickup__clickup_create_task",
               "tool_input": {"list_id": "1", "name": "x", "status": "Plan Approved"}}
    assert _guard(payload).returncode == 2
