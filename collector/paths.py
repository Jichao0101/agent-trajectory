from __future__ import annotations

from pathlib import Path


class CollectorPaths:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.storage_dir = self.root / "storage"
        self.queue_file = self.storage_dir / "queue" / "hook_events.jsonl"
        self.state_file = self.storage_dir / "collector_state.json"
        self.lock_file = self.storage_dir / "collector.lock"
        self.artifact_dir = self.storage_dir / "artifacts"
        self.snapshot_dir = self.storage_dir / "snapshots"
        self.trajectory_dir = self.root / "trajectories"
        self.raw_events_file = self.trajectory_dir / "raw_events.jsonl"
        self.report_file = self.trajectory_dir / "phase0_feasibility_report.json"

    def ensure(self) -> None:
        for directory in [
            self.storage_dir,
            self.queue_file.parent,
            self.artifact_dir,
            self.snapshot_dir,
            self.trajectory_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
