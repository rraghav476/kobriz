#!/usr/bin/env python3
"""kobriz ADLC — unified command-line entrypoint.

This is the single integration point the plugin's slash commands and hooks invoke.
It wires together config, the REST task client, worktree management, impact analysis,
dependency planning and controlled merging.

Usage:
    python3 adlc.py config validate
    python3 adlc.py config show
    python3 adlc.py tasks list
    python3 adlc.py tasks get <task_id>
    python3 adlc.py tasks status <task_id> <LIFECYCLE_STATE>
    python3 adlc.py tasks comment <task_id> <text...>
    python3 adlc.py plan [build]
    python3 adlc.py plan create [--file plan.json] [--by name]
    python3 adlc.py plan revise <plan_id> [--file plan.json] [--by name] [--note text]
    python3 adlc.py plan show <plan_id> [--markdown]
    python3 adlc.py plan list
    python3 adlc.py plan approve <plan_id> --hash <short_hash> --by <name>   # human only
    python3 adlc.py plan posted <plan_id> --task <id> --status <seen>         # after posting
    python3 adlc.py plan record-provider-approval <plan_id> --task <id> --status <seen>
    python3 adlc.py plan verify-provider <plan_id>                           # REST mode
    python3 adlc.py plan request-changes <plan_id> --note text [--by name]
    python3 adlc.py plan check <task_id>
    python3 adlc.py intake check <meeting_id> --title <action item>
    python3 adlc.py intake record <meeting_id> --title <action item> --task-id <id>
    python3 adlc.py intake show <meeting_id>
    python3 adlc.py worktree create <task_id> <slug> [--kind backend|frontend] [--agent name]
    python3 adlc.py worktree list
    python3 adlc.py worktree state <task_id> <STATE> [--note text]
    python3 adlc.py worktree remove <task_id> [--force]
    python3 adlc.py worktree shared
    python3 adlc.py impact <task_id> [--json]
    python3 adlc.py merge preflight <task_id> [--json]
    python3 adlc.py merge integrate <task_id> [--confirm]

Every command prints JSON (``--json`` where offered, else human text) and exits non-zero
on error. Secrets are never printed.

In MCP mode the ``tasks`` subcommands are intentionally delegated to Claude (which calls
the configured MCP tools); this CLI reports that clearly instead of duplicating MCP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Make sibling modules importable when invoked by absolute path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, ConfigError, atomic_write_json, redact_text  # noqa: E402
import gitutil  # noqa: E402
from plan_store import (PlanError, PlanGateError, PlanStore, gate_status,  # noqa: E402
                        render_markdown, SHORT_HASH_LEN)

# Exit codes: 1 error, 3 merge not done, 4 not configured, 5 connection failed,
# 6 approval required for a tracker write, 7 plan approval gate refused.
EXIT_PLAN_GATE = 7


def _die(msg: str, code: int = 1) -> "None":
    print(json.dumps({"ok": False, "error": msg}), file=sys.stderr)
    sys.exit(code)


def _ok(payload: dict) -> None:
    payload = {"ok": True, **payload}
    print(json.dumps(payload, indent=2, default=str))


def _require_rest(cfg: Config):
    if cfg.source_type != "rest":
        _die("This command manages tasks over REST. ADLC_TASK_SOURCE_TYPE is 'mcp' — "
             "task retrieval/updates run through the manager agent's MCP tools, not this CLI. "
             "Set ADLC_TASK_SOURCE_TYPE=rest to use the HTTP client.")
    from task_client import RestTaskClient
    return RestTaskClient(cfg)


# -- config ---------------------------------------------------------------------

def cmd_config_validate(cfg: Config, args) -> None:
    errors = cfg.validate()
    if errors:
        _die("Configuration invalid:\n  - " + "\n  - ".join(errors))
    _ok({"message": f"Configuration valid (mode={cfg.source_type})"})


def cmd_config_show(cfg: Config, args) -> None:
    _ok({"config": cfg.redacted(), "config_file": cfg.config_file})


def cmd_config_test(cfg: Config, args) -> None:
    """Actually attempt to reach the configured task provider and report the result."""
    if not cfg.is_configured():
        _die("No task provider is configured yet. Run /kobriz:setup (or "
             "`python3 adlc.py setup save ...`) to attach a ticket system.", code=4)
    if cfg.source_type == "rest":
        from task_client import RestTaskClient, TaskClientError
        try:
            client = RestTaskClient(cfg)
            tasks = client.list_tasks()
        except (ConfigError, TaskClientError) as exc:
            _die(f"REST connection FAILED: {exc}", code=5)
        _ok({"provider": "rest", "connected": True, "endpoint": cfg.api_base_url,
             "task_count": len(tasks),
             "message": f"Connected. Retrieved {len(tasks)} task(s) from {cfg.list_path}."})
    else:
        # The CLI cannot speak MCP; the manager agent verifies it via MCP tools.
        mcp_file = _find_mcp_json()
        declared = False
        if mcp_file:
            try:
                with open(mcp_file, "r", encoding="utf-8") as fh:
                    servers = json.load(fh).get("mcpServers", {})
                declared = cfg.mcp_server in servers
            except (json.JSONDecodeError, OSError):
                pass
        _ok({"provider": "mcp", "server": cfg.mcp_server,
             "mcp_json": mcp_file, "server_declared_in_mcp_json": declared,
             "message": "MCP mode: configuration present. Actual connectivity and tool "
                        "discovery are verified by the manager agent via MCP tools — run "
                        "/kobriz:status. " + ("" if declared else
                        "Note: the server is not declared in a .mcp.json yet; add it in "
                        "Claude Code's MCP settings or via `setup init-mcp`.")})


def _find_mcp_json() -> "str | None":
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    candidate = os.path.join(project_dir, ".mcp.json")
    return candidate if os.path.isfile(candidate) else None


# -- setup ----------------------------------------------------------------------

def cmd_setup_status(cfg: Config, args) -> None:
    """Report whether setup is complete and what (if anything) is missing."""
    missing = []
    if cfg.source_type == "rest":
        if not cfg.api_base_url:
            missing.append("ADLC_TASK_API_BASE_URL")
        if cfg.auth_type in ("bearer", "apikey") and not cfg.api_token:
            missing.append("ADLC_TASK_API_TOKEN")
    elif cfg.source_type == "mcp":
        if not cfg.mcp_server:
            missing.append("ADLC_MCP_SERVER")
    _ok({"configured": cfg.is_configured(), "source_type": cfg.source_type,
         "config_file": cfg.config_file, "missing": missing,
         "base_branch": cfg.base_branch, "repository_root": cfg.repository_root,
         "task_project": cfg.task_project, "provider": cfg.provider,
         "plan_approval": {"required": cfg.require_plan_approval, "mode": cfg.plan_approval,
                           "review_status": cfg.plan_review_status,
                           "approved_status": cfg.plan_approved_status},
         "needs_setup": not cfg.is_configured()})


def _load_json_object(raw: "str | None", label: str) -> dict:
    """Parse a JSON object from text (``None`` = read stdin); exit cleanly on bad input."""
    if raw is None:
        raw = sys.stdin.read()
    if not raw or not raw.strip():
        _die(f"{label} expects a JSON object (argument or stdin)")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _die(f"{label} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        _die(f"{label} must be a JSON object")
    return data


def _read_setup_payload(args) -> dict:
    data = _load_json_object(args.data or None, "setup payload")
    # Only accept known ADLC_* keys to avoid writing junk.
    allowed_prefix = "ADLC_"
    bad = [k for k in data if not str(k).startswith(allowed_prefix)]
    if bad:
        _die(f"setup payload contains non-ADLC keys: {bad}")
    return data


def cmd_setup_save(cfg: Config, args) -> None:
    """Persist collected settings to the config file, then validate + test connection."""
    from config import save_config_file, Config as C
    data = _read_setup_payload(args)
    path = save_config_file(data, scope=args.scope)
    # Reload so file values take effect, then validate.
    new_cfg = C.load()
    errors = new_cfg.validate()
    result = {"saved_to": path, "source_type": new_cfg.source_type,
              "configured": new_cfg.is_configured(), "validation_errors": errors}
    # Opportunistically test the REST connection so the user gets immediate feedback.
    if new_cfg.source_type == "rest" and new_cfg.is_configured():
        from task_client import RestTaskClient, TaskClientError
        try:
            tasks = RestTaskClient(new_cfg).list_tasks()
            result["connection_test"] = {"connected": True, "task_count": len(tasks)}
        except (ConfigError, TaskClientError) as exc:
            result["connection_test"] = {"connected": False, "error": str(exc)}
    _ok(result)


def cmd_setup_init_mcp(cfg: Config, args) -> None:
    """Write/merge an MCP server entry into project .mcp.json AND record it in config.

    Supports command servers (--command [+ --arg]) and HTTP/SSE servers (--url).
    """
    from config import save_config_file
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    mcp_path = os.path.join(project_dir, ".mcp.json")
    doc = {}
    if os.path.isfile(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (json.JSONDecodeError, OSError):
            doc = {}
    servers = doc.setdefault("mcpServers", {})

    def _parse_json_arr(raw, label):
        if not raw:
            return None
        try:
            val = json.loads(raw)
        except json.JSONDecodeError as exc:
            _die(f"{label} is not valid JSON: {exc}")
        if not isinstance(val, list):
            _die(f"{label} must be a JSON array")
        return [str(x) for x in val]

    def _parse_json_obj(raw, label):
        if not raw:
            return None
        try:
            val = json.loads(raw)
        except json.JSONDecodeError as exc:
            _die(f"{label} is not valid JSON: {exc}")
        if not isinstance(val, dict):
            _die(f"{label} must be a JSON object")
        return {str(k): str(v) for k, v in val.items()}

    if args.url:
        entry = {"type": "http", "url": args.url}
        headers = _parse_json_obj(args.headers_json, "--headers-json") or (
            dict(h.split("=", 1) for h in args.header if "=" in h) if args.header else None)
        if headers:
            entry["headers"] = headers
    elif args.command:
        # --args-json is preferred (safely carries values like "-y"); --arg is a convenience.
        server_args = _parse_json_arr(args.args_json, "--args-json")
        if server_args is None:
            server_args = args.arg or []
        entry = {"command": args.command, "args": server_args}
        env = _parse_json_obj(args.env_json, "--env-json") or (
            dict(e.split("=", 1) for e in args.env if "=" in e) if args.env else None)
        if env:
            entry["env"] = env
    else:
        _die("setup init-mcp needs either --url (HTTP/SSE server) or --command (stdio server)")

    servers[args.server] = entry
    atomic_write_json(mcp_path, doc)

    cfg_path = save_config_file(
        {"ADLC_TASK_SOURCE_TYPE": "mcp", "ADLC_MCP_SERVER": args.server}, scope=args.scope)
    _ok({"mcp_json": mcp_path, "server": args.server, "config_file": cfg_path,
         "message": "MCP server recorded. Restart Claude Code (or re-open the project) so it "
                    "connects the server, then run /kobriz:status to verify tool discovery."})


# -- tasks ----------------------------------------------------------------------

def cmd_tasks_list(cfg: Config, args) -> None:
    client = _require_rest(cfg)
    tasks = client.list_tasks()
    _ok({"count": len(tasks), "tasks": [t.to_dict() for t in tasks]})


def cmd_tasks_get(cfg: Config, args) -> None:
    client = _require_rest(cfg)
    _ok({"task": client.get_task(args.task_id).to_dict()})


def cmd_tasks_status(cfg: Config, args) -> None:
    from config import ALL_STATES
    if args.state not in ALL_STATES:
        _die(f"Unknown lifecycle state {args.state!r}. Valid: {', '.join(ALL_STATES)}")
    client = _require_rest(cfg)
    resp = client.update_status(args.task_id, args.state)
    _ok({"task_id": args.task_id, "logical_status": args.state,
         "provider_status": cfg.status_map.get(args.state, args.state), "response": resp})


def cmd_tasks_comment(cfg: Config, args) -> None:
    client = _require_rest(cfg)
    text = redact_text(" ".join(args.text), cfg)
    resp = client.add_comment(args.task_id, text)
    _ok({"task_id": args.task_id, "response": resp})


def cmd_tasks_create_subtask(cfg: Config, args) -> None:
    """Create a subtask of a parent story. Refuses to write without --confirm, which the
    manager passes ONLY after the user has approved the proposed breakdown."""
    if not args.confirm:
        _die("Refusing to create a subtask without approval. The task-splitting skill "
             "requires explicit user approval; re-run with --confirm once approved.", code=6)
    client = _require_rest(cfg)
    extra = {}
    if args.kind:
        extra["kind"] = args.kind
    subtask = client.create_subtask(args.parent_id, args.title,
                                    description=args.description or "", extra=extra)
    _ok({"parent_id": args.parent_id, "created_subtask": subtask.to_dict()})


# -- plan -----------------------------------------------------------------------

def cmd_plan(cfg: Config, args) -> None:
    from planner import build_plan
    if cfg.source_type != "rest":
        _die("`plan` needs task data. In MCP mode, the manager agent fetches tasks via MCP "
             "and builds the plan itself; run with ADLC_TASK_SOURCE_TYPE=rest to plan here.")
    client = _require_rest(cfg)
    tasks = client.list_tasks()
    plan = build_plan(tasks, cfg.max_concurrency)
    _ok({"task_count": len(tasks), "max_concurrency": cfg.max_concurrency,
         "plan": plan.to_dict()})


def _read_plan_file(path) -> dict:
    if not path:
        return _load_json_object(None, "plan")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _load_json_object(fh.read(), f"plan file {path}")
    except OSError as exc:
        _die(f"could not read plan file: {exc}")


def _plan_view(cfg: Config, record: dict, markdown: bool = False) -> dict:
    view = {"plan_id": record["plan_id"], "state": record["state"],
            "short_hash": record["content_hash"][:SHORT_HASH_LEN],
            "required_approvals": cfg.required_approvals(),
            "approvals": record["approvals"],
            "task_ids": [t["id"] for t in record["content"]["tasks"]],
            "approval_task_id": record["content"].get("approval_task_id")}
    if markdown:
        view["markdown"] = render_markdown(record, cfg)
    return view


def _ok_plan(cfg: Config, record: dict, markdown: bool = False, **extra) -> None:
    _ok({"plan": _plan_view(cfg, record, markdown), **extra})


def cmd_plan_create(cfg: Config, args) -> None:
    record = PlanStore(cfg).create(_read_plan_file(args.file), by=args.by or "")
    _ok_plan(cfg, record, markdown=True)


def cmd_plan_revise(cfg: Config, args) -> None:
    record = PlanStore(cfg).revise(args.plan_id, _read_plan_file(args.file),
                                   by=args.by or "", note=args.note or "")
    _ok_plan(cfg, record, markdown=True)


def cmd_plan_show(cfg: Config, args) -> None:
    record = PlanStore(cfg).get(args.plan_id)
    if args.markdown:
        print(render_markdown(record, cfg))
        return
    _ok_plan(cfg, record, markdown=True, history=record.get("history", []))


def cmd_plan_list(cfg: Config, args) -> None:
    _ok({"plans": [_plan_view(cfg, r) for r in PlanStore(cfg).all()]})


def cmd_plan_approve(cfg: Config, args) -> None:
    _ok_plan(cfg, PlanStore(cfg).approve_session(args.plan_id, args.hash, args.by))


def cmd_plan_record_provider(cfg: Config, args) -> None:
    _ok_plan(cfg, PlanStore(cfg).record_provider_approval(
        args.plan_id, args.task, args.status, by=args.by or "",
        evidence=args.evidence or "", source=args.source or ""))


def cmd_plan_verify_provider(cfg: Config, args) -> None:
    """REST mode: read the approval task's status straight from the tracker and record it."""
    client = _require_rest(cfg)
    store = PlanStore(cfg)
    task_id = str(store.get(args.plan_id)["content"].get("approval_task_id", ""))
    if not task_id:
        _die(f"{args.plan_id} has no approval_task_id")
    status = client.get_task(task_id).status
    _ok_plan(cfg, store.record_provider_approval(args.plan_id, task_id, str(status),
                                                 evidence="read via REST", source="rest"))


def cmd_plan_posted(cfg: Config, args) -> None:
    _ok_plan(cfg, PlanStore(cfg).record_posted(args.plan_id, args.task, args.status,
                                               evidence=args.evidence or ""))


def cmd_plan_request_changes(cfg: Config, args) -> None:
    _ok_plan(cfg, PlanStore(cfg).request_changes(args.plan_id, by=args.by or "",
                                                 note=args.note))


def cmd_plan_check(cfg: Config, args) -> None:
    result = gate_status(cfg, args.task_id)
    if not result["ok"]:
        print(json.dumps({"ok": False, "task_id": args.task_id, **result}, indent=2))
        sys.exit(EXIT_PLAN_GATE)
    _ok({"task_id": args.task_id, **result})


# -- intake ---------------------------------------------------------------------

def cmd_intake_check(cfg: Config, args) -> None:
    from intake_store import IntakeStore, draft_key
    entry = IntakeStore(cfg).check(args.meeting_id, args.title)
    _ok({"meeting_id": args.meeting_id, "key": draft_key(args.title),
         "already_created": bool(entry), "entry": entry})


def cmd_intake_record(cfg: Config, args) -> None:
    from intake_store import IntakeStore
    try:
        entry = IntakeStore(cfg).record(args.meeting_id, args.title, args.task_id,
                                        meeting_title=args.meeting_title or "")
    except ValueError as exc:
        _die(str(exc))
    _ok({"meeting_id": args.meeting_id, "entry": entry})


def cmd_intake_show(cfg: Config, args) -> None:
    from intake_store import IntakeStore
    _ok({"intake": IntakeStore(cfg).show(args.meeting_id)})


# -- worktree -------------------------------------------------------------------

def _manager(cfg: Config):
    from worktree import WorktreeManager
    return WorktreeManager(cfg)


def cmd_worktree_create(cfg: Config, args) -> None:
    mgr = _manager(cfg)
    rec = mgr.create(args.task_id, args.slug, kind=args.kind, owner_agent=args.agent)
    _ok({"worktree": rec.__dict__})


def cmd_worktree_list(cfg: Config, args) -> None:
    mgr = _manager(cfg)
    git_wts = gitutil.list_worktrees(mgr.repo)
    _ok({"tracked": [r.__dict__ for r in mgr.records()], "git_worktrees": git_wts})


def cmd_worktree_state(cfg: Config, args) -> None:
    from config import ALL_STATES
    if args.state not in ALL_STATES:
        _die(f"Unknown state {args.state!r}. Valid: {', '.join(ALL_STATES)}")
    mgr = _manager(cfg)
    rec = mgr.set_state(args.task_id, args.state, note=args.note or "")
    if not rec:
        _die(f"No worktree for task {args.task_id}")
    _ok({"worktree": rec.__dict__})


def cmd_worktree_remove(cfg: Config, args) -> None:
    mgr = _manager(cfg)
    removed = mgr.remove(args.task_id, force=args.force)
    _ok({"removed": removed, "task_id": args.task_id})


def cmd_worktree_shared(cfg: Config, args) -> None:
    mgr = _manager(cfg)
    _ok({"shared_files": mgr.detect_shared_files()})


# -- impact ---------------------------------------------------------------------

def cmd_impact(cfg: Config, args) -> None:
    from impact import analyze
    mgr = _manager(cfg)
    report = analyze(mgr, args.task_id)
    if args.json:
        _ok({"impact": report.to_dict()})
    else:
        print(report.to_text())


# -- merge ----------------------------------------------------------------------

def cmd_merge_preflight(cfg: Config, args) -> None:
    from merge import Integrator
    mgr = _manager(cfg)
    result = Integrator(cfg, mgr).preflight(args.task_id)
    _ok({"preflight": result.to_dict()})


def cmd_merge_integrate(cfg: Config, args) -> None:
    from merge import Integrator
    mgr = _manager(cfg)
    result = Integrator(cfg, mgr).integrate(args.task_id, confirm=args.confirm)
    payload = {"task_id": result.task_id, "branch": result.branch,
               "target_branch": result.target_branch, "merged": result.merged,
               "merge_commit": result.merge_commit, "message": result.message,
               "conflicting_files": result.conflicting_files}
    if not result.merged:
        print(json.dumps({"ok": False, **payload}, indent=2))
        sys.exit(3)
    _ok(payload)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adlc", description="kobriz ADLC orchestration CLI")
    sub = p.add_subparsers(dest="group", required=True)

    cfg_p = sub.add_parser("config").add_subparsers(dest="cmd", required=True)
    cfg_p.add_parser("validate").set_defaults(func=cmd_config_validate)
    cfg_p.add_parser("show").set_defaults(func=cmd_config_show)
    cfg_p.add_parser("test").set_defaults(func=cmd_config_test)

    setup_p = sub.add_parser("setup").add_subparsers(dest="cmd", required=True)
    setup_p.add_parser("status").set_defaults(func=cmd_setup_status)
    ss = setup_p.add_parser("save")
    ss.add_argument("--data", help="JSON object of ADLC_* keys (else read from stdin)")
    ss.add_argument("--scope", choices=["project", "user"], default="project")
    ss.set_defaults(func=cmd_setup_save)
    sm = setup_p.add_parser("init-mcp")
    sm.add_argument("--server", required=True, help="MCP server name")
    sm.add_argument("--command", help="stdio server command (e.g. npx)")
    sm.add_argument("--arg", action="append", help="arg for --command (repeatable)")
    sm.add_argument("--args-json", dest="args_json",
                    help='JSON array of args, preferred for values like "-y" '
                         '(e.g. \'["-y","@acme/jira-mcp"]\')')
    sm.add_argument("--env", action="append", help="K=V env for --command (repeatable)")
    sm.add_argument("--env-json", dest="env_json", help="JSON object of env vars")
    sm.add_argument("--url", help="HTTP/SSE server URL (instead of --command)")
    sm.add_argument("--header", action="append", help="K=V header for --url (repeatable)")
    sm.add_argument("--headers-json", dest="headers_json", help="JSON object of headers")
    sm.add_argument("--scope", choices=["project", "user"], default="project")
    sm.set_defaults(func=cmd_setup_init_mcp)

    tasks_p = sub.add_parser("tasks").add_subparsers(dest="cmd", required=True)
    tasks_p.add_parser("list").set_defaults(func=cmd_tasks_list)
    g = tasks_p.add_parser("get"); g.add_argument("task_id"); g.set_defaults(func=cmd_tasks_get)
    s = tasks_p.add_parser("status"); s.add_argument("task_id"); s.add_argument("state")
    s.set_defaults(func=cmd_tasks_status)
    c = tasks_p.add_parser("comment"); c.add_argument("task_id"); c.add_argument("text", nargs="+")
    c.set_defaults(func=cmd_tasks_comment)
    cs = tasks_p.add_parser("create-subtask")
    cs.add_argument("parent_id")
    cs.add_argument("--title", required=True)
    cs.add_argument("--description")
    cs.add_argument("--kind", choices=["backend", "frontend", "shared", "coordinated"])
    cs.add_argument("--confirm", action="store_true", help="required; only after user approval")
    cs.set_defaults(func=cmd_tasks_create_subtask)

    plan_parser = sub.add_parser("plan")
    plan_parser.set_defaults(func=cmd_plan)
    pl = plan_parser.add_subparsers(dest="cmd")

    def plan_cmd(name, func, *, plan_id=True, by=False, **kw):
        sp = pl.add_parser(name, **kw)
        if plan_id:
            sp.add_argument("plan_id")
        if by:
            sp.add_argument("--by")
        sp.set_defaults(func=func)
        return sp

    pl.add_parser("build").set_defaults(func=cmd_plan)
    plan_cmd("create", cmd_plan_create, plan_id=False, by=True).add_argument("--file")
    revise = plan_cmd("revise", cmd_plan_revise, by=True)
    revise.add_argument("--file")
    revise.add_argument("--note")
    plan_cmd("show", cmd_plan_show).add_argument("--markdown", action="store_true")
    plan_cmd("list", cmd_plan_list, plan_id=False)
    approve = plan_cmd("approve", cmd_plan_approve,
                       help="human only: approve the version with this hash")
    approve.add_argument("--hash", required=True)
    approve.add_argument("--by", required=True)
    provider = plan_cmd("record-provider-approval", cmd_plan_record_provider, by=True)
    provider.add_argument("--task", required=True)
    provider.add_argument("--status", required=True)
    provider.add_argument("--evidence")
    provider.add_argument("--source")
    posted = plan_cmd("posted", cmd_plan_posted)
    posted.add_argument("--task", required=True)
    posted.add_argument("--status", required=True)
    posted.add_argument("--evidence")
    plan_cmd("verify-provider", cmd_plan_verify_provider)
    plan_cmd("request-changes", cmd_plan_request_changes,
             by=True).add_argument("--note", required=True)
    plan_cmd("check", cmd_plan_check, plan_id=False).add_argument("task_id")

    it = sub.add_parser("intake").add_subparsers(dest="cmd", required=True)
    ic = it.add_parser("check")
    ic.add_argument("meeting_id")
    ic.add_argument("--title", required=True)
    ic.set_defaults(func=cmd_intake_check)
    ir = it.add_parser("record")
    ir.add_argument("meeting_id")
    ir.add_argument("--title", required=True)
    ir.add_argument("--task-id", required=True)
    ir.add_argument("--meeting-title")
    ir.set_defaults(func=cmd_intake_record)
    ish = it.add_parser("show")
    ish.add_argument("meeting_id")
    ish.set_defaults(func=cmd_intake_show)

    wt = sub.add_parser("worktree").add_subparsers(dest="cmd", required=True)
    wc = wt.add_parser("create"); wc.add_argument("task_id"); wc.add_argument("slug")
    wc.add_argument("--kind", choices=["backend", "frontend", "shared", "coordinated"])
    wc.add_argument("--agent"); wc.set_defaults(func=cmd_worktree_create)
    wt.add_parser("list").set_defaults(func=cmd_worktree_list)
    ws = wt.add_parser("state"); ws.add_argument("task_id"); ws.add_argument("state")
    ws.add_argument("--note"); ws.set_defaults(func=cmd_worktree_state)
    wr = wt.add_parser("remove"); wr.add_argument("task_id")
    wr.add_argument("--force", action="store_true"); wr.set_defaults(func=cmd_worktree_remove)
    wt.add_parser("shared").set_defaults(func=cmd_worktree_shared)

    ip = sub.add_parser("impact"); ip.add_argument("task_id")
    ip.add_argument("--json", action="store_true"); ip.set_defaults(func=cmd_impact)

    mg = sub.add_parser("merge").add_subparsers(dest="cmd", required=True)
    mp = mg.add_parser("preflight"); mp.add_argument("task_id")
    mp.add_argument("--json", action="store_true"); mp.set_defaults(func=cmd_merge_preflight)
    mi = mg.add_parser("integrate"); mi.add_argument("task_id")
    mi.add_argument("--confirm", action="store_true"); mi.set_defaults(func=cmd_merge_integrate)

    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    try:
        cfg = Config.load()
    except ConfigError as exc:
        _die(f"Configuration error: {exc}")
    try:
        args.func(cfg, args)
    except PlanGateError as exc:
        _die(str(exc), code=EXIT_PLAN_GATE)
    except (ConfigError, gitutil.GitError, PlanError) as exc:
        _die(str(exc))
    except Exception as exc:  # noqa: BLE001 — surface a clean error, never a stack-trace secret leak
        _die(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
