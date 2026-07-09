from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from collector.hook_adapter import enqueue_hook_payload
from collector.jsonl import read_jsonl
from collector.report import build_report
from collector.paths import CollectorPaths
from collector.scheduler import collector_lock, run_once
from collector.service import collect


def _raw_event_files(root: Path) -> list[Path]:
    return sorted((root / "trajectories" / "raw").glob("*/raw_events.jsonl"))


def _all_events(root: Path) -> list[dict]:
    events = []
    for raw_file in _raw_event_files(root):
        events.extend(record for _, record in read_jsonl(raw_file))
    return events


class CollectorTests(unittest.TestCase):
    def test_enqueue_collect_report_with_correlation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "tool_name": "shell",
                "tool_call_id": "call-1",
                "session_id": "session-1",
                "cwd": str(root),
            }
            queued = enqueue_hook_payload(root, "tool_pre", payload)
            self.assertTrue(queued["queued"])

            result = collect(root)
            self.assertEqual(result["processed"], 1)

            self.assertFalse((root / "trajectories" / "raw_events.jsonl").exists())
            raw_files = _raw_event_files(root)
            self.assertEqual(len(raw_files), 1)
            events = _all_events(root)
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["trajectory_schema_version"], "raw-trajectory-v1")
            self.assertEqual(event["ordering"]["monotonic_sequence"], 1)
            self.assertEqual(event["ordering"]["trajectory_sequence_no"], 1)
            self.assertEqual(event["ordering"]["correlation_status"], "present")
            self.assertEqual(event["event_type"], "act")
            self.assertEqual(event["tool_name"], "shell")
            self.assertEqual(len(event["artifact_refs"]), 1)
            self.assertEqual(len(event["snapshot_refs"]), 1)

            meta = json.loads((raw_files[0].parent / "trajectory_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["trajectory_id"], event["trajectory_id"])
            self.assertEqual(meta["event_count"], 1)
            self.assertEqual(meta["segmentation"]["session_id"], "session-1")
            self.assertEqual(meta["quality"]["tier"], "candidate")

            report = build_report(root)
            self.assertEqual(report["raw_collection_llm_call_count"], 0)
            self.assertFalse(report["tool_correlation"]["collector_blocker"])
            self.assertTrue(report["acceptance_questions"]["collector_can_assign_partial_order_sequence"])

    def test_missing_correlation_is_reported_as_blocker(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_post", {"tool_name": "shell"})
            collect(root)
            report = build_report(root)
            self.assertTrue(report["tool_correlation"]["collector_blocker"])
            self.assertEqual(report["tool_correlation"]["missing_correlation_events"], 1)

    def test_cli_outputs_are_json_serializable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "user_prompt", {"prompt": "do work", "cwd": str(root)})
            result = collect(root)
            json.dumps(result)
            json.dumps(build_report(root))

    def test_scheduler_runs_collector_and_writes_report(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})

            result = run_once(root, write_feasibility_report=True)

            self.assertFalse(result["locked"])
            self.assertEqual(result["processed"], 1)
            self.assertTrue(result["report_written"])
            self.assertTrue((root / "trajectories" / "collection_report.json").exists())

    def test_scheduler_respects_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})
            enqueue_hook_payload(root, "tool_post", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})

            first = run_once(root, limit=1)
            second = run_once(root, limit=1)

            self.assertEqual(first["processed"], 1)
            self.assertEqual(second["processed"], 1)
            events = _all_events(root)
            self.assertEqual(len(events), 2)
            self.assertEqual(len(_raw_event_files(root)), 1)

    def test_scheduler_skips_when_lock_is_held(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})

            with collector_lock(CollectorPaths(root)) as acquired:
                self.assertTrue(acquired)
                result = run_once(root)

            self.assertTrue(result["locked"])
            self.assertEqual(result["processed"], 0)
            self.assertEqual(_raw_event_files(root), [])

    def test_different_sessions_create_separate_trajectory_bundles(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "session_id": "a", "cwd": str(root)})
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-2", "session_id": "b", "cwd": str(root)})

            result = collect(root)

            self.assertEqual(result["processed"], 2)
            self.assertEqual(len(result["trajectory_ids"]), 2)
            self.assertEqual(len(_raw_event_files(root)), 2)

    def test_different_workspaces_create_separate_trajectory_bundles(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_a = root / "a"
            workspace_b = root / "b"
            workspace_a.mkdir()
            workspace_b.mkdir()
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "session_id": "session", "cwd": str(workspace_a)})
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-2", "session_id": "session", "cwd": str(workspace_b)})

            result = collect(root)

            self.assertEqual(result["processed"], 2)
            self.assertEqual(len(result["trajectory_ids"]), 2)
            self.assertEqual(len(_raw_event_files(root)), 2)

    def test_stop_then_new_user_prompt_creates_new_trajectory_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {"session_id": "session", "cwd": str(root)}
            enqueue_hook_payload(root, "UserPromptSubmit", {**payload, "prompt": "first"})
            enqueue_hook_payload(root, "Stop", payload)
            enqueue_hook_payload(root, "UserPromptSubmit", {**payload, "prompt": "second"})

            result = collect(root)

            self.assertEqual(result["processed"], 3)
            self.assertEqual(len(result["trajectory_ids"]), 2)
            raw_files = _raw_event_files(root)
            self.assertEqual(len(raw_files), 2)
            metas = [json.loads((raw_file.parent / "trajectory_meta.json").read_text(encoding="utf-8")) for raw_file in raw_files]
            self.assertEqual(sorted(meta["event_count"] for meta in metas), [1, 2])
            self.assertEqual(sorted(meta["state"] for meta in metas), ["closed", "open"])


if __name__ == "__main__":
    unittest.main()
