from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .timeutil import utc_now_iso


def _git(cwd: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def capture_baseline_snapshot(snapshot_dir: Path, workspace: Path) -> dict[str, Any]:
    record = {
        "snapshot_layer": "session_baseline",
        "parent_snapshot_id": None,
        "captured_at": utc_now_iso(),
        "workspace": str(workspace.resolve()),
        "repo": _git(workspace, ["rev-parse", "--show-toplevel"]),
        "branch": _git(workspace, ["branch", "--show-current"]),
        "commit": _git(workspace, ["rev-parse", "HEAD"]),
        "dirty_state": _git(workspace, ["status", "--short"]),
        "permission_boundary": {
            "allowed_paths": os.environ.get("AGENT_TRAJECTORY_ALLOWED_PATHS", ""),
            "sandbox": os.environ.get("AGENT_TRAJECTORY_SANDBOX", ""),
        },
    }
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    snapshot_id = hashlib.sha256(encoded).hexdigest()
    path = snapshot_dir / f"{snapshot_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(encoded)
    return {
        "snapshot_id": snapshot_id,
        "snapshot_layer": "session_baseline",
        "path": str(path),
        "sha256": snapshot_id,
    }
