from __future__ import annotations

import argparse
import json
import socket
import uuid
from pathlib import Path
from typing import Any

from .artifacts import persist_payload_artifact
from .constants import COLLECTOR_VERSION, TRAJECTORY_SCHEMA_VERSION
from .extract import (
    event_type,
    extract_correlation_key,
    extract_cwd,
    extract_error,
    extract_session_id,
    extract_tool_name,
    hook_phase,
)
from .jsonl import append_jsonl, read_jsonl
from .paths import CollectorPaths
from .snapshot import capture_baseline_snapshot
from .timeutil import utc_now_iso


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "last_queue_line": 0,
            "next_sequence_no": 1,
            "trajectory_id": str(uuid.uuid4()),
            "collector_instance_id": f"{socket.gethostname()}:{uuid.uuid4()}",
            "baseline_snapshot_ref": None,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _workspace(root: Path, payload: dict[str, Any]) -> Path:
    cwd = extract_cwd(payload)
    return Path(cwd).resolve() if cwd else root.resolve()


def _raw_event(
    paths: CollectorPaths,
    state: dict[str, Any],
    envelope: dict[str, Any],
    sequence_no: int,
) -> dict[str, Any]:
    payload = envelope.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"raw_payload": payload}

    hook_name = str(envelope.get("hook_name") or "unknown")
    artifact_ref = persist_payload_artifact(paths.artifact_dir, payload)
    baseline = state.get("baseline_snapshot_ref")
    if baseline is None:
        baseline = capture_baseline_snapshot(paths.snapshot_dir, _workspace(paths.root, payload))
        state["baseline_snapshot_ref"] = baseline

    phase = hook_phase(hook_name, payload)
    correlation_key = extract_correlation_key(payload)
    return {
        "event_id": str(uuid.uuid4()),
        "parent_event_id": None,
        "trajectory_id": state["trajectory_id"],
        "trajectory_schema_version": TRAJECTORY_SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "collector_instance_id": state["collector_instance_id"],
        "source": {
            "agent_surface": envelope.get("source", "unknown"),
            "hook_profile": hook_name,
            "workspace": str(_workspace(paths.root, payload)),
            "session_id": extract_session_id(payload),
        },
        "ordering": {
            "ordering_strategy": "collector_instance_monotonic_sequence",
            "monotonic_sequence": sequence_no,
            "wall_clock": payload.get("timestamp"),
            "ingest_clock": utc_now_iso(),
            "parent_event_index": None,
            "hook_phase": phase,
            "correlation_key": correlation_key,
            "correlation_status": "missing" if phase in {"pre", "post"} and not correlation_key else "present",
        },
        "actor": "agent",
        "event_type": event_type(hook_name, payload),
        "tool_name": extract_tool_name(payload),
        "observation": {
            "hook_name": hook_name,
            "payload_artifact_id": artifact_ref["artifact_id"],
        },
        "input_ref": artifact_ref if phase in {"pre", "single"} else None,
        "output_ref": artifact_ref if phase == "post" else None,
        "artifact_refs": [artifact_ref],
        "snapshot_refs": [baseline],
        "ordering_barrier": phase == "post",
        "raw_error": extract_error(payload),
        "queued_envelope_id": envelope.get("envelope_id"),
        "queued_received_at": envelope.get("received_at"),
    }


def collect(root: Path, limit: int | None = None) -> dict[str, Any]:
    paths = CollectorPaths(root)
    paths.ensure()
    state = _load_state(paths.state_file)
    processed = 0

    for line_no, envelope in read_jsonl(paths.queue_file) or []:
        if line_no <= int(state.get("last_queue_line", 0)):
            continue
        sequence_no = int(state["next_sequence_no"])
        event = _raw_event(paths, state, envelope, sequence_no)
        append_jsonl(paths.raw_events_file, event)
        state["last_queue_line"] = line_no
        state["next_sequence_no"] = sequence_no + 1
        processed += 1
        if limit is not None and processed >= limit:
            break

    _save_state(paths.state_file, state)
    return {
        "processed": processed,
        "raw_events_file": str(paths.raw_events_file),
        "last_queue_line": state["last_queue_line"],
        "next_sequence_no": state["next_sequence_no"],
        "trajectory_id": state["trajectory_id"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process queued hook events into raw trajectory events.")
    parser.add_argument("--root", default=".", help="agent-trajectory project root")
    parser.add_argument("--limit", type=int, help="maximum queued envelopes to process")
    args = parser.parse_args(argv)
    result = collect(Path(args.root), args.limit)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
