from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DISTILLER_VERSION = "semantic-distillation-skill-v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def git_value(root: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def bundle_paths(root: Path, trajectory_id: str) -> dict[str, Path]:
    bundle_dir = root / "trajectories" / "raw" / trajectory_id
    return {
        "bundle_dir": bundle_dir,
        "meta": bundle_dir / "trajectory_meta.json",
        "events": bundle_dir / "raw_events.jsonl",
        "artifact_index": bundle_dir / "artifact_index.json",
        "snapshot_refs": bundle_dir / "snapshot_refs.json",
    }


def load_bundle(root: Path, trajectory_id: str) -> dict[str, Any]:
    paths = bundle_paths(root, trajectory_id)
    missing = [name for name, path in paths.items() if name != "bundle_dir" and not path.exists()]
    if missing:
        raise FileNotFoundError(f"trajectory bundle is incomplete: {', '.join(missing)}")
    meta = read_json(paths["meta"])
    events = read_jsonl(paths["events"])
    artifacts = read_json(paths["artifact_index"])
    snapshots = read_json(paths["snapshot_refs"])
    return {
        "paths": {name: str(path) for name, path in paths.items()},
        "meta": meta,
        "events": events,
        "artifacts": artifacts,
        "snapshots": snapshots,
    }


def build_evidence_index(bundle: dict[str, Any]) -> dict[str, Any]:
    events = bundle["events"]
    indexed_events = []
    for event in events:
        ordering = event.get("ordering", {})
        indexed_events.append(
            {
                "event_id": event.get("event_id"),
                "trajectory_id": event.get("trajectory_id"),
                "sequence_no": ordering.get("monotonic_sequence"),
                "trajectory_sequence_no": ordering.get("trajectory_sequence_no"),
                "hook_phase": ordering.get("hook_phase"),
                "correlation_key": ordering.get("correlation_key"),
                "correlation_status": ordering.get("correlation_status"),
                "event_type": event.get("event_type"),
                "tool_name": event.get("tool_name"),
                "hook_name": event.get("observation", {}).get("hook_name"),
                "artifact_ids": [item.get("artifact_id") for item in event.get("artifact_refs", [])],
                "snapshot_ids": [item.get("snapshot_id") for item in event.get("snapshot_refs", [])],
                "raw_error": event.get("raw_error"),
            }
        )
    return {
        "trajectory_id": bundle["meta"].get("trajectory_id"),
        "event_count": len(events),
        "event_index": indexed_events,
        "artifact_count": len(bundle["artifacts"]),
        "snapshot_count": len(bundle["snapshots"]),
        "source_bundle": bundle["paths"],
    }


def build_run_scaffold(root: Path, trajectory_id: str) -> dict[str, Any]:
    bundle = load_bundle(root, trajectory_id)
    evidence_index = build_evidence_index(bundle)
    run_id = str(uuid.uuid4())
    run_dir = root / "trajectories" / "distilled" / trajectory_id / run_id
    outputs = {
        "run_meta": run_dir / "run_meta.json",
        "evidence_index": run_dir / "evidence_index.json",
        "distilled_json": run_dir / "distilled_experience.json",
        "distilled_markdown": run_dir / "distilled_experience.md",
    }
    run_meta = {
        "trajectory_id": trajectory_id,
        "distillation_run_id": run_id,
        "distiller_version": DISTILLER_VERSION,
        "source_trajectory_schema_version": bundle["meta"].get("trajectory_schema_version"),
        "created_at": utc_now_iso(),
        "agent_trajectory_repo_commit": git_value(root, ["rev-parse", "HEAD"]),
        "agent_trajectory_repo_dirty": git_value(root, ["status", "--short"]),
        "input_bundle": bundle["paths"],
        "output_files": {name: str(path) for name, path in outputs.items()},
    }
    distilled_json = {
        "distillation_run_id": run_id,
        "distiller_version": DISTILLER_VERSION,
        "source_trajectory_id": trajectory_id,
        "source_trajectory_schema_version": bundle["meta"].get("trajectory_schema_version"),
        "source_event_range": bundle["meta"].get("event_range", {}),
        "distilled_task": {
            "interpreted_intent": "",
            "constraints": [],
            "success_criteria": [],
        },
        "distilled_claims": [],
        "distilled_causal_links": [],
        "decision_points": [],
        "failure_tags": [],
        "uncertainty": [],
        "reviewer_status": "unreviewed",
    }
    distilled_md = f"""# 语义蒸馏 {run_id}

## 任务意图

## 关键事实

## 决策点

## 失败与不确定性

## 证据链

source_trajectory_id: `{trajectory_id}`
"""
    write_json(outputs["run_meta"], run_meta)
    write_json(outputs["evidence_index"], evidence_index)
    write_json(outputs["distilled_json"], distilled_json)
    outputs["distilled_markdown"].write_text(distilled_md, encoding="utf-8")
    return {
        "distillation_run_id": run_id,
        "run_dir": str(run_dir),
        "run_meta": run_meta,
        "evidence_index": evidence_index,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a semantic distillation run for one trajectory.")
    parser.add_argument("--root", default=".", help="agent-trajectory repository root")
    parser.add_argument("--trajectory-id", required=True)
    parser.add_argument("--write-run", action="store_true", help="write run scaffold under trajectories/distilled")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = build_run_scaffold(root, args.trajectory_id) if args.write_run else build_evidence_index(load_bundle(root, args.trajectory_id))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
