from __future__ import annotations

from typing import Any


_CORRELATION_KEYS = (
    "correlation_key",
    "correlation_id",
    "tool_call_id",
    "tool_use_id",
    "call_id",
    "invocation_id",
    "request_id",
    "id",
)

_TOOL_KEYS = ("tool_name", "tool", "name", "command")
_SESSION_KEYS = ("session_id", "conversation_id", "thread_id", "trace_id")
_CWD_KEYS = ("cwd", "workspace", "working_dir")
_ERROR_KEYS = ("error", "raw_error", "stderr", "exception")


def deep_find(payload: Any, keys: tuple[str, ...]) -> Any | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for value in payload.values():
            found = deep_find(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = deep_find(value, keys)
            if found not in (None, ""):
                return found
    return None


def extract_correlation_key(payload: dict[str, Any]) -> str | None:
    found = deep_find(payload, _CORRELATION_KEYS)
    return str(found) if found not in (None, "") else None


def extract_tool_name(payload: dict[str, Any]) -> str | None:
    found = deep_find(payload, _TOOL_KEYS)
    return str(found) if found not in (None, "") else None


def extract_session_id(payload: dict[str, Any]) -> str | None:
    found = deep_find(payload, _SESSION_KEYS)
    return str(found) if found not in (None, "") else None


def extract_cwd(payload: dict[str, Any]) -> str | None:
    found = deep_find(payload, _CWD_KEYS)
    return str(found) if found not in (None, "") else None


def extract_error(payload: dict[str, Any]) -> str | None:
    found = deep_find(payload, _ERROR_KEYS)
    return str(found) if found not in (None, "") else None


def hook_phase(hook_name: str, payload: dict[str, Any]) -> str:
    lowered = hook_name.lower()
    if any(token in lowered for token in ("pre", "before", "start")):
        return "pre"
    if any(token in lowered for token in ("post", "after", "finish", "complete", "result")):
        return "post"
    phase = deep_find(payload, ("phase", "hook_phase", "event_phase"))
    if isinstance(phase, str) and phase.lower() in {"pre", "post"}:
        return phase.lower()
    return "single"


def event_type(hook_name: str, payload: dict[str, Any]) -> str:
    lowered = hook_name.lower()
    if any(token in lowered for token in ("stop", "handoff", "submit")):
        return "handoff"
    if extract_error(payload) or any(token in lowered for token in ("error", "fail")):
        return "fail"
    if any(token in lowered for token in ("test", "verify", "lint", "check")):
        return "verify"
    if any(token in lowered for token in ("tool", "command", "edit", "write", "permission")):
        return "act"
    return "observe"
