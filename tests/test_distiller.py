import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from collector.hook_adapter import enqueue_hook_payload
from collector.service import collect
from distiller.scripts.prepare_distillation import (
    build_evidence_index,
    build_run_scaffold,
    load_bundle,
)


def _only_trajectory_id(root: Path) -> str:
    raw_dirs = sorted((root / "trajectories" / "raw").iterdir())
    assert len(raw_dirs) == 1
    return raw_dirs[0].name


class DistillerTest(unittest.TestCase):
    def test_build_run_scaffold_for_collected_trajectory(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(
                root,
                "tool_pre",
                {
                    "tool_name": "shell",
                    "tool_call_id": "call-1",
                    "session_id": "session-1",
                    "cwd": str(root),
                },
            )
            collect(root)
            trajectory_id = _only_trajectory_id(root)

            result = build_run_scaffold(root, trajectory_id)
            run_dir = Path(result["run_dir"])

            self.assertTrue((run_dir / "run_meta.json").exists())
            self.assertTrue((run_dir / "evidence_index.json").exists())
            self.assertTrue((run_dir / "distilled_experience.json").exists())
            self.assertTrue((run_dir / "distilled_experience.md").exists())
            self.assertEqual(result["evidence_index"]["trajectory_id"], trajectory_id)
            self.assertEqual(result["evidence_index"]["event_count"], 1)

            distilled = json.loads((run_dir / "distilled_experience.json").read_text(encoding="utf-8"))
            self.assertEqual(distilled["source_trajectory_id"], trajectory_id)
            self.assertEqual(distilled["reviewer_status"], "unreviewed")

    def test_evidence_index_rejects_incomplete_bundle(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_bundle(Path(tmp), "missing-trajectory")

    def test_build_evidence_index_contains_event_references(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            enqueue_hook_payload(
                root,
                "tool_pre",
                {
                    "tool_name": "shell",
                    "tool_call_id": "call-2",
                    "session_id": "session-2",
                    "cwd": str(root),
                },
            )
            collect(root)
            trajectory_id = _only_trajectory_id(root)

            bundle = load_bundle(root, trajectory_id)
            evidence = build_evidence_index(bundle)

            self.assertEqual(evidence["event_count"], 1)
            self.assertEqual(evidence["event_index"][0]["tool_name"], "shell")
            self.assertTrue(evidence["event_index"][0]["artifact_ids"])
            self.assertTrue(evidence["event_index"][0]["snapshot_ids"])


if __name__ == "__main__":
    unittest.main()
