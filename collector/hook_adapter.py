from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from .jsonl import append_jsonl
from .paths import CollectorPaths
from .timeutil import utc_now_iso


def enqueue_hook_payload(
    root: Path,
    hook_name: str,
    payload: dict[str, Any],
    source: str = "codex-hook",
) -> dict[str, Any]:
    paths = CollectorPaths(root)
    paths.ensure()
    envelope = {
        "envelope_id": str(uuid.uuid4()),
        "received_at": utc_now_iso(),
        "source": source,
        "hook_name": hook_name,
        "payload": payload,
    }
    append_jsonl(paths.queue_file, envelope)
    return {
        "queued": True,
        "envelope_id": envelope["envelope_id"],
        "queue_file": str(paths.queue_file),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lightweight hook adapter for Phase 0.")
    parser.add_argument("--root", default=".", help="agent-trajectory project root")
    parser.add_argument("--hook-name", required=True, help="hook/event name from the caller")
    parser.add_argument("--source", default="codex-hook", help="source surface name")
    parser.add_argument("--payload-file", help="read JSON payload from file instead of stdin")
    args = parser.parse_args(argv)

    raw = Path(args.payload_file).read_text(encoding="utf-8") if args.payload_file else sys.stdin.read()
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise SystemExit("hook payload must be a JSON object")
    result = enqueue_hook_payload(Path(args.root), args.hook_name, payload, args.source)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
