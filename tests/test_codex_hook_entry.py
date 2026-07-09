from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from collector.codex_hook_entry import handle_hook
from collector.jsonl import read_jsonl


class CodexHookEntryTests(unittest.TestCase):
    def test_allowed_workspace_is_enqueued_and_passes_through(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "collector-root"
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            allowlist = Path(tmp) / "allowlist.json"
            allowlist.write_text(
                json.dumps({"allowed_workspaces": [str(workspace)]}),
                encoding="utf-8",
            )

            response = handle_hook(
                "PreToolUse",
                {"cwd": str(workspace), "tool_name": "Read", "tool_call_id": "call-1"},
                root,
                allowlist,
            )

            self.assertEqual(response, {})
            queued = [record for _, record in read_jsonl(root / "storage" / "queue" / "hook_events.jsonl")]
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["hook_name"], "PreToolUse")
            self.assertEqual(queued[0]["source"], "codex-global-hook")
            self.assertEqual(queued[0]["payload"]["agent_trajectory_capture_mode"], "global_passive_allowlist")

    def test_unlisted_workspace_is_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "collector-root"
            allowed = Path(tmp) / "allowed"
            other = Path(tmp) / "other"
            allowed.mkdir()
            other.mkdir()
            allowlist = Path(tmp) / "allowlist.json"
            allowlist.write_text(
                json.dumps({"allowed_workspaces": [str(allowed)]}),
                encoding="utf-8",
            )

            response = handle_hook("UserPromptSubmit", {"cwd": str(other)}, root, allowlist)

            self.assertEqual(response, {})
            self.assertFalse((root / "storage" / "queue" / "hook_events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
