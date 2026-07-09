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


class Phase0Tests(unittest.TestCase):
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

            events = [record for _, record in read_jsonl(root / "trajectories" / "raw_events.jsonl")]
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(event["trajectory_schema_version"], "raw-trajectory-v1")
            self.assertEqual(event["ordering"]["monotonic_sequence"], 1)
            self.assertEqual(event["ordering"]["correlation_status"], "present")
            self.assertEqual(event["event_type"], "act")
            self.assertEqual(event["tool_name"], "shell")
            self.assertEqual(len(event["artifact_refs"]), 1)
            self.assertEqual(len(event["snapshot_refs"]), 1)

            report = build_report(root)
            self.assertEqual(report["raw_collection_llm_call_count"], 0)
            self.assertFalse(report["tool_correlation"]["phase0_blocker"])
            self.assertTrue(report["acceptance_questions"]["collector_can_assign_partial_order_sequence"])

    def test_missing_correlation_is_reported_as_blocker(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_post", {"tool_name": "shell"})
            collect(root)
            report = build_report(root)
            self.assertTrue(report["tool_correlation"]["phase0_blocker"])
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
            self.assertTrue((root / "trajectories" / "phase0_feasibility_report.json").exists())

    def test_scheduler_respects_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})
            enqueue_hook_payload(root, "tool_post", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})

            first = run_once(root, limit=1)
            second = run_once(root, limit=1)

            self.assertEqual(first["processed"], 1)
            self.assertEqual(second["processed"], 1)
            events = [record for _, record in read_jsonl(root / "trajectories" / "raw_events.jsonl")]
            self.assertEqual(len(events), 2)

    def test_scheduler_skips_when_lock_is_held(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(root, "tool_pre", {"tool_name": "shell", "tool_call_id": "call-1", "cwd": str(root)})

            with collector_lock(CollectorPaths(root)) as acquired:
                self.assertTrue(acquired)
                result = run_once(root)

            self.assertTrue(result["locked"])
            self.assertEqual(result["processed"], 0)
            self.assertFalse((root / "trajectories" / "raw_events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
