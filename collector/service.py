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
            "collector_instance_id": f"{socket.gethostname()}:{uuid.uuid4()}",
            "active_trajectories": {},
            "trajectory_ids": [],
        }
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("active_trajectories", {})
    state.setdefault("trajectory_ids", [])
    return state


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _workspace(root: Path, payload: dict[str, Any]) -> Path:
    cwd = extract_cwd(payload)
    return Path(cwd).resolve() if cwd else root.resolve()


def _is_user_prompt(hook_name: str) -> bool:
    lowered = hook_name.lower().replace("_", "")
    return "userprompt" in lowered or "promptsubmit" in lowered


def _is_stop(hook_name: str) -> bool:
    return "stop" in hook_name.lower()


def _trajectory_key(session_id: str | None, workspace: Path) -> str:
    return f"{session_id or 'no-session'}|{workspace}"


def _trajectory_paths(paths: CollectorPaths, trajectory_id: str) -> dict[str, Path]:
    directory = paths.raw_trajectory_dir / trajectory_id
    return {
        "dir": directory,
        "meta": directory / "trajectory_meta.json",
        "events": directory / "raw_events.jsonl",
        "artifacts": directory / "artifact_index.json",
        "snapshots": directory / "snapshot_refs.json",
    }


def _write_json(path: Path, record: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_trajectory(
    paths: CollectorPaths,
    state: dict[str, Any],
    hook_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workspace = _workspace(paths.root, payload)
    session_id = extract_session_id(payload)
    key = _trajectory_key(session_id, workspace)
    active = state.setdefault("active_trajectories", {})
    current = active.get(key)
    needs_new = current is None or (current.get("state") == "closed" and _is_user_prompt(hook_name))
    if not needs_new:
        return current

    trajectory_id = str(uuid.uuid4())
    baseline = capture_baseline_snapshot(paths.snapshot_dir, workspace)
    now = utc_now_iso()
    record = {
        "trajectory_id": trajectory_id,
        "trajectory_schema_version": TRAJECTORY_SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "created_at": now,
        "closed_at": None,
        "state": "open",
        "event_count": 0,
        "segmentation": {
            "start_reason": "user_prompt" if _is_user_prompt(hook_name) else "first_event_for_session_workspace",
            "close_reason": None,
            "session_id": session_id,
            "workspace": str(workspace),
            "user_prompt_event_id": None,
            "stop_event_id": None,
            "idle_timeout_seconds": None,
        },
        "source": {
            "agent_surface": None,
            "hook_profile_set": [],
        },
        "quality": {
            "tier": "candidate",
            "domain_tags": [],
            "capture_reason": "allowed_workspace_hook_payload",
            "drop_reason": None,
        },
        "event_range": {
            "first_sequence_no": None,
            "last_sequence_no": None,
            "first_ingest_clock": None,
            "last_ingest_clock": None,
        },
        "artifacts": {
            "raw_events_file": str(_trajectory_paths(paths, trajectory_id)["events"]),
            "artifact_index": str(_trajectory_paths(paths, trajectory_id)["artifacts"]),
            "snapshot_refs": str(_trajectory_paths(paths, trajectory_id)["snapshots"]),
        },
        "baseline_snapshot_ref": baseline,
        "unresolved_items": [],
    }
    tpaths = _trajectory_paths(paths, trajectory_id)
    _write_json(tpaths["meta"], record)
    _write_json(tpaths["artifacts"], [])
    _write_json(tpaths["snapshots"], [baseline])
    current = {
        "trajectory_id": trajectory_id,
        "state": "open",
        "session_id": session_id,
        "workspace": str(workspace),
    }
    active[key] = current
    state.setdefault("trajectory_ids", []).append(trajectory_id)
    return current


def _update_trajectory_meta(
    paths: CollectorPaths,
    trajectory: dict[str, Any],
    envelope: dict[str, Any],
    event: dict[str, Any],
) -> None:
    trajectory_id = trajectory["trajectory_id"]
    tpaths = _trajectory_paths(paths, trajectory_id)
    meta = _load_json(tpaths["meta"], {})
    event_count = int(meta.get("event_count") or 0) + 1
    hooks = set(meta.get("source", {}).get("hook_profile_set", []))
    hooks.add(str(envelope.get("hook_name") or "unknown"))
    meta.setdefault("source", {})["hook_profile_set"] = sorted(hooks)
    meta["source"]["agent_surface"] = envelope.get("source", "unknown")
    meta["event_count"] = event_count
    event_range = meta.setdefault("event_range", {})
    sequence_no = event["ordering"]["monotonic_sequence"]
    ingest_clock = event["ordering"]["ingest_clock"]
    event_range["first_sequence_no"] = event_range.get("first_sequence_no") or sequence_no
    event_range["last_sequence_no"] = sequence_no
    event_range["first_ingest_clock"] = event_range.get("first_ingest_clock") or ingest_clock
    event_range["last_ingest_clock"] = ingest_clock
    segmentation = meta.setdefault("segmentation", {})
    if _is_user_prompt(str(envelope.get("hook_name") or "")) and not segmentation.get("user_prompt_event_id"):
        segmentation["user_prompt_event_id"] = event["event_id"]
    if _is_stop(str(envelope.get("hook_name") or "")):
        segmentation["stop_event_id"] = event["event_id"]
        segmentation["close_reason"] = "stop_hook"
        meta["state"] = "closed"
        meta["closed_at"] = ingest_clock
        trajectory["state"] = "closed"
    _write_json(tpaths["meta"], meta)

    artifacts = _load_json(tpaths["artifacts"], [])
    for artifact in event.get("artifact_refs", []):
        if artifact not in artifacts:
            artifacts.append(artifact)
    _write_json(tpaths["artifacts"], artifacts)

    snapshots = _load_json(tpaths["snapshots"], [])
    for snapshot in event.get("snapshot_refs", []):
        if snapshot not in snapshots:
            snapshots.append(snapshot)
    _write_json(tpaths["snapshots"], snapshots)


def _raw_event(
    paths: CollectorPaths,
    state: dict[str, Any],
    trajectory: dict[str, Any],
    envelope: dict[str, Any],
    sequence_no: int,
) -> dict[str, Any]:
    payload = envelope.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"raw_payload": payload}

    hook_name = str(envelope.get("hook_name") or "unknown")
    artifact_ref = persist_payload_artifact(paths.artifact_dir, payload)
    tpaths = _trajectory_paths(paths, trajectory["trajectory_id"])
    meta = _load_json(tpaths["meta"], {})
    baseline = meta.get("baseline_snapshot_ref")
    trajectory_sequence_no = int(meta.get("event_count") or 0) + 1

    phase = hook_phase(hook_name, payload)
    correlation_key = extract_correlation_key(payload)
    return {
        "event_id": str(uuid.uuid4()),
        "parent_event_id": None,
        "trajectory_id": trajectory["trajectory_id"],
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
            "trajectory_sequence_no": trajectory_sequence_no,
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
        payload = envelope.get("payload") if isinstance(envelope, dict) else {}
        if not isinstance(payload, dict):
            payload = {"raw_payload": payload}
        hook_name = str(envelope.get("hook_name") or "unknown")
        trajectory = _ensure_trajectory(paths, state, hook_name, payload)
        event = _raw_event(paths, state, trajectory, envelope, sequence_no)
        append_jsonl(_trajectory_paths(paths, trajectory["trajectory_id"])["events"], event)
        _update_trajectory_meta(paths, trajectory, envelope, event)
        state["last_queue_line"] = line_no
        state["next_sequence_no"] = sequence_no + 1
        processed += 1
        if limit is not None and processed >= limit:
            break

    _save_state(paths.state_file, state)
    return {
        "processed": processed,
        "raw_trajectory_dir": str(paths.raw_trajectory_dir),
        "last_queue_line": state["last_queue_line"],
        "next_sequence_no": state["next_sequence_no"],
        "trajectory_ids": sorted(set(state.get("trajectory_ids", []))),
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
