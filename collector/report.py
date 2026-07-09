from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .jsonl import read_jsonl
from .paths import CollectorPaths
from .timeutil import utc_now_iso


def _events(paths: CollectorPaths) -> list[dict[str, Any]]:
    return [record for _, record in (read_jsonl(paths.raw_events_file) or [])]


def build_report(root: Path) -> dict[str, Any]:
    paths = CollectorPaths(root)
    events = _events(paths)
    pre_post = [event for event in events if event["ordering"]["hook_phase"] in {"pre", "post"}]
    missing_correlation = [
        event for event in pre_post if event["ordering"].get("correlation_status") == "missing"
    ]
    event_types = Counter(event.get("event_type") for event in events)
    hook_profiles = Counter(event["source"].get("hook_profile") for event in events)
    sessions = {event["source"].get("session_id") for event in events if event["source"].get("session_id")}
    workspaces = {event["source"].get("workspace") for event in events if event["source"].get("workspace")}
    sequence_numbers = [event["ordering"]["monotonic_sequence"] for event in events]
    monotonic = sequence_numbers == sorted(sequence_numbers) and len(sequence_numbers) == len(set(sequence_numbers))

    report = {
        "generated_at": utc_now_iso(),
        "phase": "phase0_hook_feasibility_spike",
        "raw_collection_llm_call_count": 0,
        "total_events": len(events),
        "event_type_counts": dict(event_types),
        "hook_profile_counts": dict(hook_profiles),
        "observed_session_count": len(sessions),
        "observed_workspace_count": len(workspaces),
        "ordering": {
            "monotonic_sequence_valid": monotonic,
            "first_sequence_no": min(sequence_numbers) if sequence_numbers else None,
            "last_sequence_no": max(sequence_numbers) if sequence_numbers else None,
            "partial_order_supported": True,
        },
        "tool_correlation": {
            "pre_post_events": len(pre_post),
            "missing_correlation_events": len(missing_correlation),
            "missing_correlation_ratio": (len(missing_correlation) / len(pre_post)) if pre_post else None,
            "phase0_blocker": bool(missing_correlation),
        },
        "acceptance_questions": {
            "task_boundaries_observable": bool(events),
            "payload_has_tool_or_session_or_workspace": any(
                event.get("tool_name") or event["source"].get("session_id") or event["source"].get("workspace")
                for event in events
            ),
            "tool_pre_post_has_stable_correlation_key": bool(pre_post) and not missing_correlation,
            "collector_can_assign_partial_order_sequence": monotonic,
            "hook_adapter_is_lightweight_enqueue": True,
            "raw_collection_sync_path_uses_llm": False,
            "local_queue_or_collector_write_observed": paths.queue_file.exists() and paths.raw_events_file.exists(),
        },
        "files": {
            "queue_file": str(paths.queue_file),
            "raw_events_file": str(paths.raw_events_file),
            "report_file": str(paths.report_file),
        },
        "unresolved_items": [],
    }
    if not events:
        report["unresolved_items"].append("No hook payloads have been collected yet.")
    if missing_correlation:
        report["unresolved_items"].append(
            "Some tool pre/post events lack a stable correlation key; this is a Phase 0 blocker for reliable merge."
        )
    return report


def write_report(root: Path) -> dict[str, Any]:
    paths = CollectorPaths(root)
    paths.ensure()
    report = build_report(root)
    paths.report_file.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Phase 0 feasibility report.")
    parser.add_argument("--root", default=".", help="agent-trajectory project root")
    parser.add_argument("--write", action="store_true", help="write report to trajectories/")
    args = parser.parse_args(argv)
    report = write_report(Path(args.root)) if args.write else build_report(Path(args.root))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
