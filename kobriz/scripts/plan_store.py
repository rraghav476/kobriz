"""Persisted execution plans and the human-approval gate for the kobriz ADLC plugin.

A plan is stored as JSON under ``<repo>/.kobriz/plans/`` with a content hash. A plan runs
only after every approval required by ``ADLC_PLAN_APPROVAL`` has been recorded against
its *current* hash:

  * ``session``  — a human runs ``adlc.py plan approve <id> --hash <short>`` themselves
                   (the guard-approval hook blocks the agent from running it).
  * ``provider`` — a human sets ``ADLC_PLAN_APPROVED_STATUS`` on the plan's approval task
                   in the tracker; the agent reads it back and records it here (the hook
                   blocks the agent from setting that status itself).

Revising a plan changes its hash and clears approvals. ``require_approved`` is the gate
called before a worktree is created or a branch is merged.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import gitutil
from config import APPROVALS_BY_MODE, Config, atomic_write_json, kobriz_dir, now_iso

PENDING = "PENDING_APPROVAL"
APPROVED = "APPROVED"
CHANGES_REQUESTED = "CHANGES_REQUESTED"
SUPERSEDED = "SUPERSEDED"

SHORT_HASH_LEN = 12


class PlanError(RuntimeError):
    """Invalid plan content or an illegal state transition."""


class PlanGateError(RuntimeError):
    """Raised when an action needs an approved plan and none covers the task."""


def _empty_approvals() -> Dict[str, None]:
    return dict.fromkeys(APPROVALS_BY_MODE["both"])


def content_hash(content: Dict[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_content(content: Any, needs_approval_task: bool) -> List[str]:
    errors: List[str] = []
    if not isinstance(content, dict):
        return ["plan must be a JSON object"]
    if not str(content.get("title", "")).strip():
        errors.append("plan.title is required")
    tasks = content.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("plan.tasks must be a non-empty list")
        return errors
    ids: List[str] = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            errors.append(f"plan.tasks[{i}] must be an object")
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not tid.strip():
            errors.append(f"plan.tasks[{i}].id must be a non-empty string")
            continue
        if not str(t.get("title", "")).strip():
            errors.append(f"plan.tasks[{i}].title is required")
        ids.append(tid)
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        errors.append(f"duplicate task ids: {dupes}")
    batches = content.get("batches")
    if batches is not None:
        if not isinstance(batches, list) or not all(isinstance(b, list) for b in batches):
            errors.append("plan.batches must be a list of lists of task ids")
        else:
            unknown = sorted({x for b in batches for x in b if x not in ids})
            if unknown:
                errors.append(f"plan.batches reference unknown task ids: {unknown}")
    if needs_approval_task and not str(content.get("approval_task_id", "")).strip():
        errors.append("plan.approval_task_id is required: the tracker task where a human "
                      "sets the approval status")
    return errors


class PlanStore:
    def __init__(self, config: Config, repo: Optional[str] = None) -> None:
        self.config = config
        self.dir = os.path.join(kobriz_dir(config, repo), "plans")
        os.makedirs(self.dir, exist_ok=True)

    # -- persistence --------------------------------------------------------------

    def _path(self, plan_id: str) -> str:
        if gitutil.slugify(plan_id, 80) != plan_id:
            raise PlanError(f"invalid plan id {plan_id!r}")
        return os.path.join(self.dir, f"{plan_id}.json")

    def _save(self, record: Dict[str, Any]) -> None:
        atomic_write_json(self._path(record["plan_id"]), record)

    def get(self, plan_id: str) -> Dict[str, Any]:
        path = self._path(plan_id)
        if not os.path.isfile(path):
            raise PlanError(f"no plan {plan_id!r}")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def all(self) -> List[Dict[str, Any]]:
        out = []
        for name in sorted(os.listdir(self.dir)):
            if name.endswith(".json"):
                with open(os.path.join(self.dir, name), "r", encoding="utf-8") as fh:
                    out.append(json.load(fh))
        return sorted(out, key=lambda r: r["created_at"])

    # -- transitions ----------------------------------------------------------------

    def _needs_provider(self) -> bool:
        return "provider" in self.config.required_approvals()

    def _check_content(self, content: Any) -> None:
        errors = validate_content(content, self._needs_provider())
        if errors:
            raise PlanError("invalid plan:\n  - " + "\n  - ".join(errors))

    def _event(self, record: Dict[str, Any], event: str, by: str = "", note: str = "") -> None:
        record.setdefault("history", []).append(
            {"at": now_iso(), "event": event, "by": by, "note": note,
             "hash": record["content_hash"][:SHORT_HASH_LEN]})
        record["updated_at"] = now_iso()

    def create(self, content: Dict[str, Any], by: str = "") -> Dict[str, Any]:
        """Store a new plan as PENDING_APPROVAL; supersede open plans sharing any task."""
        self._check_content(content)
        digest = content_hash(content)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        plan_id, n = f"plan-{stamp}-{digest[:6]}", 1
        while os.path.exists(self._path(plan_id)):
            n += 1
            plan_id = f"plan-{stamp}-{digest[:6]}-{n}"
        task_ids = {t["id"] for t in content["tasks"]}
        for other in self.all():
            if other["state"] != SUPERSEDED and task_ids & set(_task_ids(other)):
                other["state"] = SUPERSEDED
                self._event(other, "superseded", by, f"by {plan_id}")
                self._save(other)
        record = {"plan_id": plan_id, "state": PENDING, "content": content,
                  "content_hash": digest, "created_at": now_iso(), "updated_at": now_iso(),
                  "approvals": _empty_approvals(), "history": []}
        self._event(record, "created", by)
        self._save(record)
        return record

    def revise(self, plan_id: str, content: Dict[str, Any], by: str = "",
               note: str = "") -> Dict[str, Any]:
        """Replace the content; every earlier approval is void and the plan needs review again."""
        record = self.get(plan_id)
        if record["state"] == SUPERSEDED:
            raise PlanError(f"{plan_id} is superseded; create a new plan instead")
        self._check_content(content)
        record["content"] = content
        record["content_hash"] = content_hash(content)
        record["approvals"] = _empty_approvals()
        record.pop("posted", None)
        record["state"] = PENDING
        self._event(record, "revised", by, note)
        self._save(record)
        return record

    def request_changes(self, plan_id: str, by: str = "", note: str = "") -> Dict[str, Any]:
        record = self.get(plan_id)
        if record["state"] == SUPERSEDED:
            raise PlanError(f"{plan_id} is superseded")
        record["state"] = CHANGES_REQUESTED
        record["approvals"] = _empty_approvals()
        self._event(record, "changes_requested", by, note)
        self._save(record)
        return record

    def _approvable(self, plan_id: str) -> Dict[str, Any]:
        record = self.get(plan_id)
        if record["state"] not in (PENDING, APPROVED):
            raise PlanError(f"{plan_id} is {record['state']}; only a plan pending approval "
                            f"can be approved (revise it first if changes were requested)")
        if content_hash(record["content"]) != record["content_hash"]:
            raise PlanError(f"{plan_id} was edited outside kobriz (hash mismatch); revise it")
        return record

    def _settle(self, record: Dict[str, Any]) -> None:
        if all(_approval_valid(record, kind) for kind in self.config.required_approvals()):
            if record["state"] != APPROVED:
                record["state"] = APPROVED
                self._event(record, "approved")

    def approve_session(self, plan_id: str, short_hash: str, by: str) -> Dict[str, Any]:
        """Human approval of the exact version they reviewed (identified by its short hash)."""
        if not by.strip():
            raise PlanError("--by is required: the name of the person approving")
        record = self._approvable(plan_id)
        if not short_hash or not record["content_hash"].startswith(short_hash.lower()) \
                or len(short_hash) < 8:
            raise PlanError("hash does not match the current plan version; show the plan again "
                            "and approve the hash it prints")
        record["approvals"]["session"] = {"by": by, "at": now_iso(), "hash": record["content_hash"]}
        self._event(record, "session_approval", by)
        self._settle(record)
        self._save(record)
        return record

    def record_posted(self, plan_id: str, task_id: str, status_seen: str,
                      evidence: str = "") -> Dict[str, Any]:
        """Record that this version was posted to the approval task and the task was read back
        in a status other than the approval status. A tracker approval only counts after this,
        so an approval left over from an earlier version (or an earlier plan on the same task)
        can never carry over."""
        record = self._approvable(plan_id)
        self._check_approval_task(record, task_id)
        if status_seen.strip().casefold() == self._approved_status():
            raise PlanError(f"task {task_id} is still in the approval status "
                            f"{self.config.plan_approved_status!r}; move it to the review status "
                            f"before posting this version")
        record["posted"] = {"at": now_iso(), "hash": record["content_hash"],
                            "task_id": str(task_id), "status_seen": status_seen,
                            "evidence": evidence}
        self._event(record, "posted_for_review", note=f"{task_id}: {status_seen}")
        self._save(record)
        return record

    def _approved_status(self) -> str:
        wanted = (self.config.plan_approved_status or "").strip().casefold()
        if not wanted:
            raise PlanError("ADLC_PLAN_APPROVED_STATUS is not configured")
        return wanted

    @staticmethod
    def _check_approval_task(record: Dict[str, Any], task_id: str) -> None:
        expected = str(record["content"].get("approval_task_id", ""))
        if str(task_id) != expected:
            raise PlanError(f"approval must come from the plan's approval task "
                            f"{expected!r}, not {task_id!r}")

    def record_provider_approval(self, plan_id: str, task_id: str, status_seen: str,
                                 by: str = "", evidence: str = "",
                                 source: str = "") -> Dict[str, Any]:
        """Record that the approval status was read back from the tracker's approval task."""
        record = self._approvable(plan_id)
        self._check_approval_task(record, task_id)
        posted = record.get("posted") or {}
        if posted.get("hash") != record["content_hash"]:
            raise PlanError(f"{plan_id} has not been posted for review in its current version; "
                            f"post it, move the task to the review status, and record that "
                            f"with `adlc.py plan posted` before reading the approval")
        if status_seen.strip().casefold() != self._approved_status():
            raise PlanError(f"task {task_id} status is {status_seen!r}, not the approval "
                            f"status {self.config.plan_approved_status!r}; not approved yet")
        record["approvals"]["provider"] = {
            "by": by, "at": now_iso(), "hash": record["content_hash"], "task_id": str(task_id),
            "status_seen": status_seen, "evidence": evidence,
            "source": source or self.config.provider}
        self._event(record, "provider_approval", by, evidence)
        self._settle(record)
        self._save(record)
        return record

    # -- the gate -------------------------------------------------------------------

    def find_for_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Newest non-superseded plan that includes ``task_id``."""
        matches = [r for r in self.all()
                   if r["state"] != SUPERSEDED and str(task_id) in _task_ids(r)]
        return matches[-1] if matches else None

    def check_task(self, task_id: str) -> Dict[str, Any]:
        """Return {"ok": bool, "plan_id", "reason"} for whether ``task_id`` may run."""
        record = self.find_for_task(task_id)
        if not record:
            return {"ok": False, "plan_id": None,
                    "reason": f"no plan includes task {task_id}; create one with "
                              f"`adlc.py plan create` and get it approved"}
        pid = record["plan_id"]
        if content_hash(record["content"]) != record["content_hash"]:
            return {"ok": False, "plan_id": pid,
                    "reason": f"{pid} was edited outside kobriz (hash mismatch)"}
        if record["state"] not in (PENDING, APPROVED):
            return {"ok": False, "plan_id": pid,
                    "reason": f"{pid} is {record['state']}, not APPROVED"}
        # Judged against the current mode, not the state stored when approvals were recorded.
        missing = [k for k in self.config.required_approvals()
                   if not _approval_valid(record, k)]
        if missing:
            return {"ok": False, "plan_id": pid,
                    "reason": f"{pid} lacks {', '.join(missing)} approval for its current version"}
        return {"ok": True, "plan_id": pid, "reason": "approved"}


def gate_status(config: Config, task_id: str, repo: Optional[str] = None) -> Dict[str, Any]:
    """The single answer to "may this task run?", including when the gate is switched off."""
    if not config.require_plan_approval:
        return {"ok": True, "plan_id": None, "reason": "plan approval is disabled"}
    return PlanStore(config, repo).check_task(task_id)


def require_approved(config: Config, task_id: str, repo: Optional[str] = None) -> Optional[str]:
    """Raise PlanGateError unless an approved plan covers ``task_id``. Returns the plan id."""
    result = gate_status(config, task_id, repo)
    if not result["ok"]:
        raise PlanGateError(f"Plan approval required: {result['reason']}")
    return result["plan_id"]


def _task_ids(record: Dict[str, Any]) -> List[str]:
    return [str(t.get("id")) for t in record.get("content", {}).get("tasks", [])]


def _approval_valid(record: Dict[str, Any], kind: str) -> bool:
    entry = record.get("approvals", {}).get(kind)
    return bool(entry) and entry.get("hash") == record["content_hash"]


def render_markdown(record: Dict[str, Any], config: Config) -> str:
    """Human-readable plan, used for the review comment and the session prompt."""
    c = record["content"]
    short = record["content_hash"][:SHORT_HASH_LEN]
    lines = [f"# {c.get('title', record['plan_id'])}", "",
             f"Plan `{record['plan_id']}` · version `{short}` · state **{record['state']}**", ""]
    if c.get("summary"):
        lines += [str(c["summary"]), ""]
    lines += ["## Tasks", "", "| Task | Title | Kind | Agent | Depends on |",
              "| --- | --- | --- | --- | --- |"]
    for t in c.get("tasks", []):
        deps = ", ".join(map(str, t.get("depends_on") or [])) or "none"
        lines.append(f"| {t.get('id')} | {t.get('title', '')} | {t.get('kind', '')} | "
                     f"{t.get('agent', '')} | {deps} |")
    if c.get("batches"):
        lines += ["", "## Order", ""]
        lines += [f"{i}. {', '.join(map(str, b))}" for i, b in enumerate(c["batches"], 1)]
    for t in c.get("tasks", []):
        affected = t.get("affected_files") or []
        impacted = t.get("impacted_files") or []
        if affected or impacted or t.get("split"):
            lines += ["", f"### {t.get('id')}: {t.get('title', '')}"]
            if t.get("split"):
                lines.append(f"- Split: {t['split']}")
            lines += [f"- Changes: `{f}`" for f in affected]
            lines += [f"- Depends on the change: `{f}`" for f in impacted]
    if c.get("risks"):
        lines += ["", "## Risks", ""] + [f"- {r}" for r in c["risks"]]
    needs = config.required_approvals()
    lines += ["", "## How to approve", ""]
    if "provider" in needs:
        lines.append(f"- In the tracker: set task `{c.get('approval_task_id', '?')}` to status "
                     f"`{config.plan_approved_status or '?'}`.")
    if "session" in needs:
        lines.append(f"- In Claude Code, type: `! python3 <plugin>/scripts/adlc.py plan approve "
                     f"{record['plan_id']} --hash {short} --by \"<your name>\"`")
    lines.append("- Any change to the plan creates a new version that must be approved again.")
    return "\n".join(lines) + "\n"
