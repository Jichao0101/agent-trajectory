from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def persist_payload_artifact(artifact_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = artifact_dir / f"{digest}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
    return {
        "artifact_id": digest,
        "kind": "hook_payload",
        "path": str(path),
        "sha256": digest,
    }
