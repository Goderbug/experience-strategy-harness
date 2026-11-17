"""Native-shaped hook subprocess tests; a trusted Codex/model run is not simulated."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]


class RoleHookTests(unittest.TestCase):
    def setUp(self):
        project = tempfile.TemporaryDirectory(prefix="role-codex-")
        self.addCleanup(project.cleanup)
        self.root = Path(project.name).resolve()
        (self.root / "view.txt").write_text("initial fixture")
        self.run_tool("scripts/harness.py", "init", "--root", str(self.root), "--project-id", "fixture",
                      "--goal", "Inspect a saved artifact", "--scope", "Synthetic trial", "--version", "v1")
        self.run_tool("scripts/runtime.py", "setup", "--root", str(self.root), "--watch", "view.txt")

    def run_tool(self, script, *args, data=None):
        proc = subprocess.run([sys.executable, str(REPO / script), *args], capture_output=True, text=True,
                              input=json.dumps(data) if data is not None else None, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def hook(self, name, **extra):
        event = dict(cwd=str(self.root), session_id="native-shaped", turn_id="t-1",
                     hook_event_name=name, **extra)
        return self.run_tool("adapters/codex/hook.py", data=event)

    def test_role_appears_after_explicit_open_and_revision_invalidates_context_key(self):
        self.hook("UserPromptSubmit")
        before = self.run_tool("scripts/runtime.py", "context", "--root", str(self.root))
        self.assertNotIn("roles", before)
        self.assertFalse((self.root / ".experience-strategy" / "engine.sqlite3").exists())
        case = self.run_tool("scripts/engine.py", "open", "--root", str(self.root), data=dict(
            case_id="case-visible", goal="Keep list controls discoverable", claim="Save is discoverable",
            claim_type="behavior", route="tradeoff", mode="fixture"))
        event = self.hook("PreToolUse", tool_use_id="a", tool_name="Read")
        self.assertIn("next: strategist", event["hookSpecificOutput"]["additionalContext"])
        self.assertIn("case-visible", event["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("hookSpecificOutput", self.hook("PostToolUse", tool_use_id="a", tool_name="Read"))
        self.run_tool("scripts/engine.py", "submit", "--root", str(self.root), data=dict(
            case_id="case-visible", binding=case["binding"], expected_revision=case["revision"],
            request_id="unique-1", role="strategist", output=dict(
                intent="Preserve reading focus while providing save.",
                options=["Expose save permanently", "Reveal on focus"],
                proposal="Reveal on focus", assumption="Readers will discover save on focus.",
                reopen_if="Readers who want to save cannot find the action.")))
        next_event = self.hook("PreToolUse", tool_use_id="b", tool_name="Read")
        self.assertIn("next: critic", next_event["hookSpecificOutput"]["additionalContext"])
        after = self.run_tool("scripts/runtime.py", "context", "--root", str(self.root))
        self.assertEqual(before["pending_ids"], after["pending_ids"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertNotEqual(before["context_key"], after["context_key"])

    def test_creation_handoff_identifies_execution_without_enabling_user_research(self):
        case = self.run_tool("scripts/engine.py", "open", "--root", str(self.root), data=dict(
            case_id="card", goal="Save from the list", claim="Place Save next to the card",
            claim_type="artifact", task_stage="create", mode="fixture"))
        context = self.hook("UserPromptSubmit")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("next: critic", context)
        self.run_tool("scripts/engine.py", "submit", "--root", str(self.root), data=dict(
            case_id="card", binding=case["binding"], expected_revision=case["revision"],
            request_id="choose", role="critic", output=dict(
                change="Make Save visible", tradeoff="One extra visible action",
                acceptance="Check its presence in the default state.")))
        context = self.hook("PreToolUse", tool_use_id="check", tool_name="Read")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("next: execution", context)
        self.assertIn('"user_evidence":"disabled"', context)
        self.assertIn('"user_outcome":"unverified"', context)

    def test_role_store_error_does_not_hide_normal_checkpoint_or_invent_stop(self):
        (self.root / ".experience-strategy" / "engine.sqlite3").write_bytes(b"invalid database")
        # No turn-start event and no watched change: a role-only failure must not create a stop.
        self.assertNotIn("decision", self.hook("Stop", stop_hook_active=False))
        result = self.hook("UserPromptSubmit")
        self.assertIn("Design role state unavailable", result["hookSpecificOutput"]["additionalContext"])
        self.assertIn("Outstanding reviews:", result["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
