"""Configuration loading, validation and secret redaction for the kobriz ADLC plugin.

Configuration is resolved from three layers, highest precedence first:

  1. Process environment  (``ADLC_*`` variables; also Claude Code plugin options
     surfaced as ``CLAUDE_PLUGIN_OPTION_*``)
  2. A persisted JSON config file written by ``/kobriz:setup``
     (project ``.kobriz/config.json`` or user ``~/.claude/kobriz/config.json``)
  3. Built-in defaults

This lets users configure the plugin once via the setup wizard without editing shell
profiles. Nothing here hard-codes credentials; secrets are only ever read from the
environment or the user's own 0600 config file, and are redacted before being logged.

This module is intentionally dependency-free (Python standard library only).
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# Keys whose values must never appear in logs, prompts or task comments.
_SECRET_KEY_PATTERN = re.compile(r"(token|secret|password|api[_-]?key|authorization|bearer)", re.I)

# Active config-file values for the current Config.load() pass (env still wins over these).
_ACTIVE_FILE_VALUES: Dict[str, str] = {}
_ACTIVE_FILE_PATH: Optional[str] = None

# Logical ADLC lifecycle states (mapped to the provider's own schema at the edge).
LIFECYCLE_STATES = [
    "READY", "ASSIGNED", "IN_PROGRESS", "REVIEW", "VALIDATING",
    "READY_TO_MERGE", "MERGING", "COMPLETED",
]
FAILURE_STATES = ["BLOCKED", "FAILED", "NEEDS_REWORK", "MERGE_CONFLICT", "CANCELLED"]
ALL_STATES = LIFECYCLE_STATES + FAILURE_STATES

_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class ConfigError(ValueError):
    """Raised when the plugin configuration is invalid or incomplete."""


def candidate_config_paths() -> List[str]:
    """Config-file locations in precedence order (first existing one is used)."""
    paths: List[str] = []
    explicit = os.environ.get("ADLC_CONFIG_FILE")
    if explicit:
        paths.append(os.path.expanduser(explicit))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    paths.append(os.path.join(project_dir, ".kobriz", "config.json"))
    paths.append(os.path.expanduser(os.path.join("~", ".claude", "kobriz", "config.json")))
    return paths


def find_config_file() -> Optional[str]:
    """Return the first existing config file, or None."""
    for p in candidate_config_paths():
        if p and os.path.isfile(p):
            return p
    return None


def default_config_path(scope: str = "project") -> str:
    """Where ``/kobriz:setup`` writes config. scope = 'project' | 'user'."""
    if scope == "user":
        return os.path.expanduser(os.path.join("~", ".claude", "kobriz", "config.json"))
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.join(project_dir, ".kobriz", "config.json")


def load_config_file() -> Tuple[Optional[str], Dict[str, str]]:
    """Load the active config file as a flat {ADLC_KEY: str} dict. Never raises on a
    missing file; raises ConfigError only on malformed JSON."""
    path = find_config_file()
    if not path:
        return None, {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object of ADLC_* keys")
    # Stringify scalars; serialize dict values (e.g. field maps) back to JSON strings so
    # the same _json_map parsing path handles file and env identically.
    flat: Dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(v, (dict, list)):
            flat[str(k)] = json.dumps(v)
        elif isinstance(v, bool):
            flat[str(k)] = "true" if v else "false"
        elif v is not None:
            flat[str(k)] = str(v)
    return path, flat


def save_config_file(values: Dict[str, Any], scope: str = "project",
                     path: Optional[str] = None) -> str:
    """Merge ``values`` into the config file and write it with 0600 perms. Returns path."""
    target = path or default_config_path(scope)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    existing: Dict[str, Any] = {}
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing.update({k: v for k, v in values.items() if v is not None})
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, sort_keys=True)
    os.replace(tmp, target)
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — secrets stay owner-only
    except OSError:
        pass
    return target


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Resolve a setting: environment first, then the active config file, then default."""
    val = os.environ.get(name)
    if val is None:
        val = _ACTIVE_FILE_VALUES.get(name)
    if val is None:
        return default
    val = val.strip()
    if val == "":
        return default
    return val


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:  # noqa: TRY003
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass
class Config:
    """Resolved, validated plugin configuration.

    Use :meth:`load` to build from the environment and :meth:`validate` to check it.
    """

    source_type: str = "mcp"                       # "mcp" | "rest"
    # --- REST provider settings ---
    api_base_url: Optional[str] = None
    list_path: str = "/tasks"
    details_path: str = "/tasks/{task_id}"
    status_path: str = "/tasks/{task_id}/status"
    comment_path: Optional[str] = None             # optional; absent => comments unsupported
    subtask_path: Optional[str] = None             # create endpoint; defaults to list_path
    subtask_method: str = "POST"
    parent_field: str = "parent_id"                # body field that links a subtask to its parent
    auth_type: str = "bearer"                      # "bearer" | "apikey" | "none"
    api_token: Optional[str] = None
    api_key_header: str = "X-API-Key"
    extra_headers: Dict[str, str] = field(default_factory=dict)
    list_method: str = "GET"
    status_method: str = "PATCH"
    # Response mapping: provider field -> canonical field.
    field_map: Dict[str, str] = field(default_factory=dict)
    status_map: Dict[str, str] = field(default_factory=dict)   # logical -> provider status
    # Which project/board within the ticket system to pull tickets from. A provider (Jira,
    # etc.) can host many projects; this scopes discovery to one. e.g. a Jira project key.
    task_project: Optional[str] = None
    # --- MCP provider settings ---
    mcp_server: Optional[str] = None               # expected MCP server name (for docs/validation)
    # --- Git / worktree settings ---
    repository_root: Optional[str] = None
    base_branch: str = "main"
    worktree_root: Optional[str] = None
    branch_prefix: str = "adlc"
    # --- Orchestration / merge policy ---
    max_concurrency: int = 3
    merge_strategy: str = "merge"                  # "merge" | "rebase" | "squash"
    require_tests: bool = True
    auto_merge: bool = False
    keep_failed_worktrees: bool = True
    auto_retries: int = 0
    # --- provenance (not a setting) ---
    config_file: Optional[str] = None              # path of the file that supplied values

    @classmethod
    def load(cls) -> "Config":
        """Build a Config from env + the persisted config file + defaults."""
        global _ACTIVE_FILE_VALUES, _ACTIVE_FILE_PATH
        _ACTIVE_FILE_PATH, _ACTIVE_FILE_VALUES = load_config_file()
        extra_headers: Dict[str, str] = {}
        raw_headers = _env("ADLC_TASK_EXTRA_HEADERS_JSON")
        if raw_headers:
            try:
                parsed = json.loads(raw_headers)
                if not isinstance(parsed, dict):
                    raise ConfigError("ADLC_TASK_EXTRA_HEADERS_JSON must be a JSON object")
                extra_headers = {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError as exc:
                raise ConfigError(f"ADLC_TASK_EXTRA_HEADERS_JSON is not valid JSON: {exc}") from exc

        def _json_map(var: str) -> Dict[str, str]:
            raw = _env(var)
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"{var} is not valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ConfigError(f"{var} must be a JSON object")
            return {str(k): str(v) for k, v in parsed.items()}

        return cls(
            source_type=(_env("ADLC_TASK_SOURCE_TYPE", "mcp") or "mcp").lower(),
            api_base_url=_env("ADLC_TASK_API_BASE_URL"),
            list_path=_env("ADLC_TASK_LIST_PATH", "/tasks") or "/tasks",
            details_path=_env("ADLC_TASK_DETAILS_PATH", "/tasks/{task_id}") or "/tasks/{task_id}",
            status_path=_env("ADLC_TASK_STATUS_PATH", "/tasks/{task_id}/status") or "/tasks/{task_id}/status",
            comment_path=_env("ADLC_TASK_COMMENT_PATH"),
            subtask_path=_env("ADLC_TASK_SUBTASK_PATH"),
            subtask_method=(_env("ADLC_TASK_SUBTASK_METHOD", "POST") or "POST").upper(),
            parent_field=_env("ADLC_TASK_PARENT_FIELD", "parent_id") or "parent_id",
            auth_type=(_env("ADLC_TASK_AUTH_TYPE", "bearer") or "bearer").lower(),
            api_token=_env("ADLC_TASK_API_TOKEN"),
            api_key_header=_env("ADLC_TASK_API_KEY_HEADER", "X-API-Key") or "X-API-Key",
            extra_headers=extra_headers,
            list_method=(_env("ADLC_TASK_LIST_METHOD", "GET") or "GET").upper(),
            status_method=(_env("ADLC_TASK_STATUS_METHOD", "PATCH") or "PATCH").upper(),
            field_map=_json_map("ADLC_TASK_FIELD_MAP_JSON"),
            status_map=_json_map("ADLC_TASK_STATUS_MAP_JSON"),
            task_project=_env("ADLC_TASK_PROJECT"),
            mcp_server=_env("ADLC_MCP_SERVER"),
            repository_root=_env("ADLC_REPOSITORY_ROOT") or os.getcwd(),
            base_branch=_env("ADLC_BASE_BRANCH", "main") or "main",
            worktree_root=_env("ADLC_WORKTREE_ROOT"),
            branch_prefix=_env("ADLC_BRANCH_PREFIX", "adlc") or "adlc",
            max_concurrency=_env_int("ADLC_MAX_CONCURRENCY", 3),
            merge_strategy=(_env("ADLC_MERGE_STRATEGY", "merge") or "merge").lower(),
            require_tests=_env_bool("ADLC_REQUIRE_TESTS", True),
            auto_merge=_env_bool("ADLC_AUTO_MERGE", False),
            keep_failed_worktrees=_env_bool("ADLC_KEEP_FAILED_WORKTREES", True),
            auto_retries=_env_int("ADLC_AUTO_RETRIES", 0),
            config_file=_ACTIVE_FILE_PATH,
        )

    def is_configured(self) -> bool:
        """True once a task provider has been set up enough to attempt a connection."""
        if self.source_type == "rest":
            return bool(self.api_base_url) and (
                self.auth_type == "none" or bool(self.api_token)
            )
        if self.source_type == "mcp":
            return bool(self.mcp_server)
        return False

    def validate(self) -> List[str]:
        """Return a list of human-readable validation errors (empty == valid)."""
        errors: List[str] = []

        if self.source_type not in ("mcp", "rest"):
            errors.append(
                f"ADLC_TASK_SOURCE_TYPE must be 'mcp' or 'rest', got {self.source_type!r}"
            )

        if self.source_type == "rest":
            if not self.api_base_url:
                errors.append("ADLC_TASK_API_BASE_URL is required when ADLC_TASK_SOURCE_TYPE=rest")
            elif not re.match(r"^https?://", self.api_base_url):
                errors.append("ADLC_TASK_API_BASE_URL must start with http:// or https://")
            if self.auth_type not in ("bearer", "apikey", "none"):
                errors.append("ADLC_TASK_AUTH_TYPE must be one of: bearer, apikey, none")
            if self.auth_type in ("bearer", "apikey") and not self.api_token:
                errors.append(
                    f"ADLC_TASK_API_TOKEN is required when ADLC_TASK_AUTH_TYPE={self.auth_type}"
                )
            if "{task_id}" not in self.details_path:
                errors.append("ADLC_TASK_DETAILS_PATH should contain the {task_id} placeholder")
            if "{task_id}" not in self.status_path:
                errors.append("ADLC_TASK_STATUS_PATH should contain the {task_id} placeholder")

        if self.source_type == "mcp" and not self.mcp_server:
            # Non-fatal: the manager agent can still discover tools, but warn.
            errors.append(
                "ADLC_MCP_SERVER is not set; configure the MCP server name so the manager "
                "can target the right provider (set ADLC_TASK_SOURCE_TYPE=rest to use REST instead)"
            )

        if not self.repository_root or not os.path.isdir(self.repository_root):
            errors.append(f"ADLC_REPOSITORY_ROOT is not a directory: {self.repository_root!r}")

        if not _BRANCH_NAME_RE.match(self.base_branch):
            errors.append(f"ADLC_BASE_BRANCH is not a valid branch name: {self.base_branch!r}")

        if not _BRANCH_NAME_RE.match(self.branch_prefix):
            errors.append(f"ADLC_BRANCH_PREFIX is not a valid branch segment: {self.branch_prefix!r}")

        if self.max_concurrency < 1:
            errors.append("ADLC_MAX_CONCURRENCY must be >= 1")

        if self.merge_strategy not in ("merge", "rebase", "squash"):
            errors.append("ADLC_MERGE_STRATEGY must be one of: merge, rebase, squash")

        if self.auto_retries < 0:
            errors.append("ADLC_AUTO_RETRIES must be >= 0")

        return errors

    def redacted(self) -> Dict[str, Any]:
        """Return the config as a dict with all secret-looking values masked."""
        return redact(asdict(self))


def redact(value: Any) -> Any:
    """Recursively mask secret-looking values in dicts/lists for safe logging."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if _SECRET_KEY_PATTERN.search(str(k)) and v not in (None, "", {}):
                out[k] = "***REDACTED***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def redact_text(text: str, config: "Config") -> str:
    """Scrub known secret literals out of a free-text blob before it leaves the host."""
    if not text:
        return text
    scrubbed = text
    secrets = [config.api_token]
    secrets += [v for v in config.extra_headers.values()]
    for secret in secrets:
        if secret and len(secret) >= 4:
            scrubbed = scrubbed.replace(secret, "***REDACTED***")
    return scrubbed
