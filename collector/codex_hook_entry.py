from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from collector.extract import extract_cwd
    from collector.hook_adapter import enqueue_hook_payload
else:
    from .extract import extract_cwd
    from .hook_adapter import enqueue_hook_payload


DEFAULT_ROOT = Path("/home/jichao/agent-trajectory")
DEFAULT_ALLOWLIST = DEFAULT_ROOT / "collector" / "allowed_workspaces.json"
LOG_FILE = DEFAULT_ROOT / "storage" / "hook_errors.log"


def _response() -> dict[str, Any]:
    return {}


def _read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if isinstance(payload, dict):
        return payload
    return {"raw_payload": payload}


def _load_allowlist(path: Path) -> list[Path]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    workspaces = data.get("allowed_workspaces", [])
    if not isinstance(workspaces, list):
        return []
    return [Path(str(item)).expanduser().resolve() for item in workspaces]


def _payload_workspace(payload: dict[str, Any]) -> Path:
    cwd = extract_cwd(payload) or os.environ.get("PWD") or os.getcwd()
    return Path(cwd).expanduser().resolve()


def _is_allowed(workspace: Path, allowed_roots: list[Path]) -> bool:
    for root in allowed_roots:
        if workspace == root or root in workspace.parents:
            return True
    return False


def _enrich_payload(payload: dict[str, Any], hook_name: str, workspace: Path) -> dict[str, Any]:
    enriched = dict(payload)
    enriched.setdefault("cwd", str(workspace))
    enriched.setdefault("codex_hook_name", hook_name)
    enriched.setdefault("agent_trajectory_capture_mode", "global_passive_allowlist")
    return enriched


def _log_error(message: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(message)
            handle.write("\n")
    except OSError:
        pass


def handle_hook(
    hook_name: str,
    payload: dict[str, Any],
    root: Path = DEFAULT_ROOT,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
) -> dict[str, Any]:
    workspace = _payload_workspace(payload)
    allowed_roots = _load_allowlist(allowlist_path)
    if not _is_allowed(workspace, allowed_roots):
        return _response()

    enqueue_hook_payload(
        root=root,
        hook_name=hook_name,
        payload=_enrich_payload(payload, hook_name, workspace),
        source="codex-global-hook",
    )
    return _response()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Passive Codex hook entry for agent trajectory collection.")
    parser.add_argument("--hook-name", required=True)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST))
    args = parser.parse_args(argv)

    try:
        payload = _read_stdin_json()
        response = handle_hook(args.hook_name, payload, Path(args.root), Path(args.allowlist))
    except Exception:
        _log_error(traceback.format_exc())
        response = _response()

    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
