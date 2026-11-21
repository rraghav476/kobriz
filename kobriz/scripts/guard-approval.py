#!/usr/bin/env python3
"""kobriz ADLC — PreToolUse guard that keeps plan approval in human hands.

Blocks (exit 2, reason on stderr) when the agent tries to:
  * run ``adlc.py plan approve`` — session approval must be typed by a human
    (``! python3 .../adlc.py plan approve ...`` or their own terminal);
  * weaken approval settings: turn ADLC_REQUIRE_PLAN_APPROVAL off, change
    ADLC_PLAN_APPROVAL away from ``both``, or change an already-configured
    ADLC_PLAN_APPROVED_STATUS;
  * touch kobriz plans or config directly — ``.kobriz/``, ``~/.claude/kobriz/`` or the file
    ADLC_CONFIG_FILE names — or point ADLC_CONFIG_FILE somewhere else;
  * write a script or config file (anything but prose docs, outside the plugin) containing
    any of the commands or settings above, to be run later;
  * set the plan-approval status through a tracker MCP tool (any argument equal to
    ADLC_PLAN_APPROVED_STATUS on a ClickUp / configured-provider tool that is not a read);
  * call a Granola tool that changes data — meeting intake is read-only.

This is a guardrail against an agent approving its own plan by accident or shortcut, not
a security boundary: a determined process on the same machine can bypass any local check.
Anything it cannot parse is allowed.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_APPROVE_RE = re.compile(r"adlc\.py['\"]?\s+plan\s+approve\b|approve_session\s*\(")
_DISABLE_RE = re.compile(r"ADLC_REQUIRE_PLAN_APPROVAL['\"\]]*\s*[:=]\s*['\"]?(false|0|no|off)\b",
                         re.I)
_MODE_RE = re.compile(r"ADLC_PLAN_APPROVAL['\"\]]*\s*[:=]\s*['\"]?(\w+)", re.I)
_STATUS_SET_RE = re.compile(r"ADLC_PLAN_APPROVED_STATUS['\"\]]*\s*[:=]")
_CONFIG_FILE_SET_RE = re.compile(r"ADLC_CONFIG_FILE['\"\]]*\s*[:=]")
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Prose files may mention these commands; anything else written to disk could be run later.
_DOC_EXTENSIONS = (".md", ".mdx", ".rst", ".txt")
# Tracker tools that only read; every other tool on a watched server is treated as a write.
_READ_TOOL_RE = re.compile(r"(^|_)(get|filter|search|list|read|query|find|resolve|fetch)(_|$)")
# Granola tools that change data, per Granola's MCP docs (Nov 2026); matched on the tool
# name's last segment so any server prefix works.
_GRANOLA_WRITE_RE = re.compile(
    r"(^|_)(create_|update_|add_|remove_|generate_|switch_workspace|sign_out|give_feedback)")


def _block(reason: str) -> None:
    print(f"kobriz: blocked — {reason}", file=sys.stderr)
    print("Plan approval must come from a human. Ask the user to do this step themselves.",
          file=sys.stderr)
    sys.exit(2)


def _config():
    try:
        from config import Config
        return Config.load()
    except Exception:  # noqa: BLE001 — unreadable config must not break the session
        return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def check_text(text: str, load_config) -> None:
    """Rules for anything that could run: a Bash command, or a script/config being written."""
    if _APPROVE_RE.search(text):
        _block("only a human may run `adlc.py plan approve`")
    if _DISABLE_RE.search(text):
        _block("only a human may turn off ADLC_REQUIRE_PLAN_APPROVAL")
    for mode in _MODE_RE.findall(text):
        if mode.lower() != "both":
            _block("only a human may change ADLC_PLAN_APPROVAL away from 'both'")
    if _STATUS_SET_RE.search(text):
        cfg = load_config()  # only this check needs config; skip the load on ordinary commands
        if cfg is not None and cfg.plan_approved_status:
            _block("only a human may change an already-configured ADLC_PLAN_APPROVED_STATUS")
    if _CONFIG_FILE_SET_RE.search(text):
        _block("only a human may point kobriz at a different config file (ADLC_CONFIG_FILE)")
    if ".kobriz/plans" in text or "kobriz/config.json" in text:
        _block("plans and kobriz config are changed only through adlc.py")


def _protected(path: str) -> bool:
    norm = path.replace("\\", "/")
    if "/.kobriz/" in norm or norm.startswith(".kobriz/") or "/.claude/kobriz/" in norm:
        return True
    explicit = os.environ.get("ADLC_CONFIG_FILE")
    return bool(explicit) and os.path.abspath(os.path.expanduser(explicit)) == os.path.abspath(path)


def check_edit(tool_input: dict, load_config) -> None:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if _protected(path):
        _block("kobriz config and plans are changed only through adlc.py")
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if path.lower().endswith(_DOC_EXTENSIONS) or (
            plugin_root and os.path.abspath(path).startswith(os.path.abspath(plugin_root))):
        return
    content = {k: v for k, v in tool_input.items() if k not in ("file_path", "notebook_path")}
    for text in _strings(content):
        check_text(text, load_config)


def check_granola(tool_name: str) -> None:
    name = tool_name.casefold()
    if "granola" not in name:
        return
    leaf = name.split("__")[-1]
    if _GRANOLA_WRITE_RE.search(leaf):
        _block(f"meeting intake is read-only; {leaf} would change Granola data")


def check_mcp(tool_name: str, tool_input: dict, load_config) -> None:
    check_granola(tool_name)
    cfg = load_config()  # the provider and server names to watch come from config
    if cfg is None or not cfg.plan_approved_status:
        return
    name = tool_name.casefold()
    watched = {"clickup"}
    if cfg.provider and cfg.provider != "generic":
        watched.add(cfg.provider.casefold())
    if cfg.mcp_server:
        watched.add(cfg.mcp_server.casefold())
    if not any(w in name for w in watched) or _READ_TOOL_RE.search(name.split("__")[-1]):
        return
    wanted = cfg.plan_approved_status.strip().casefold()
    if any(s.strip().casefold() == wanted for s in _strings(tool_input)):
        _block(f"only a human may set the plan-approval status "
               f"'{cfg.plan_approved_status}' in the tracker")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        sys.exit(0)
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        sys.exit(0)
    if tool == "Bash":
        check_text(str(tool_input.get("command", "")), _config)
    elif tool in _EDIT_TOOLS:
        check_edit(tool_input, _config)
    elif tool.startswith("mcp__"):
        check_mcp(tool, tool_input, _config)
    sys.exit(0)


if __name__ == "__main__":
    main()
