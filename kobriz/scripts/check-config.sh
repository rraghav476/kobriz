#!/usr/bin/env bash
# kobriz ADLC — SessionStart config check (non-blocking, first-run aware).
#
# On a fresh install nothing is configured yet, so this nudges the user to run the setup
# wizard instead of showing a raw validation error. It NEVER blocks the session and NEVER
# prints secrets. Exit code is always 0.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "kobriz: python3 not found — the ADLC scripts require Python 3.8+." >&2
  exit 0
fi

status="$(python3 "$PLUGIN_ROOT/scripts/adlc.py" setup status 2>/dev/null)" || {
  echo "kobriz ADLC: not configured yet. Run /kobriz:setup to attach your ticket system (MCP or REST)."
  exit 0
}

if printf '%s' "$status" | grep -q '"needs_setup": true'; then
  echo "kobriz ADLC: no ticket system attached yet."
  echo "  → Run /kobriz:setup to connect an MCP server or REST task API (takes ~1 min)."
  exit 0
fi

# Configured — do a light validation pass for actionable issues.
out="$(python3 "$PLUGIN_ROOT/scripts/adlc.py" config validate 2>&1)" || {
  echo "kobriz ADLC: configuration needs attention."
  echo "$out" | sed 's/^/  /'
  echo "  Run /kobriz:setup to fix it."
  exit 0
}
echo "kobriz ADLC: configured and ready. Use /kobriz:status or /kobriz:start."
exit 0
