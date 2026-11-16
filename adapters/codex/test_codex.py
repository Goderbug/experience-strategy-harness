"""Codex adapter contract tests; fixtures are not native-model execution."""

import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location("codex_" + name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load("hook")
installer = load("install")


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="experience-codex-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.payload = {"cwd": str(self.root), "session_id": "session-one", "turn_id": "turn-one"}

    def enable(self):
        directory = self.root / ".experience-strategy"
        directory.mkdir()
        (directory / "runtime.sqlite3").touch()

    def fixture(self, native, **values):
        return dict(self.payload, hook_event_name=native, **values)

    def test_no_opt_in_means_no_runtime_call(self):
        def unexpected(*args):
            self.fail("Runtime must not be invoked without explicit project opt-in")
        self.assertEqual(hook.dispatch(self.fixture("Stop"), unexpected), {})

    def test_existing_v01_state_does_not_opt_in(self):
        directory = self.root / ".experience-strategy"
        directory.mkdir()
        (directory / "state.json").write_text("{}")
        self.assertIsNone(hook.project_root(str(self.root)))

    def test_ancestor_root_and_symlink_rejection(self):
        self.enable()
        nested = self.root / "src" / "nested"
        nested.mkdir(parents=True)
        self.assertEqual(hook.project_root(str(nested)), self.root)
        database = self.root / ".experience-strategy" / "runtime.sqlite3"
        database.unlink()
        database.symlink_to(self.root / "missing.sqlite3")
        with self.assertRaisesRegex(ValueError, "regular file"):
            hook.project_root(str(nested))

    def test_context_events_return_native_json(self):
        self.enable()
        for native in hook.CONTEXT_EVENTS:
            with self.subTest(native=native):
                captured = []
                def runner(root, event):
                    captured.append((root, event))
                    return {"ok": True, "enabled": True, "context": "Review pending change.", "block_stop": True}
                output = hook.dispatch(self.fixture(native, tool_use_id="tool-a", tool_name="apply_patch"), runner)
                self.assertEqual(output, {"hookSpecificOutput": {"hookEventName": native, "additionalContext": "Review pending change."}})
                self.assertEqual(captured[0][1]["event"], hook.EVENTS[native])

    def test_stop_bounded_by_native_continuation_flag(self):
        self.enable()
        runner = lambda root, event: {"ok": True, "enabled": True, "context": "Perform the pending focused review.", "block_stop": True}
        first = hook.dispatch(self.fixture("Stop", stop_hook_active=False), runner)
        self.assertEqual(first["decision"], "block")
        self.assertEqual(hook.dispatch(self.fixture("Stop", stop_hook_active=True), runner), {})

    def test_interrupt_and_end_never_continue(self):
        self.enable()
        runner = lambda root, event: {"ok": True, "enabled": True, "context": "pending", "block_stop": True}
        for native in ["Interrupt", "SessionEnd"]:
            self.assertEqual(hook.dispatch(self.fixture(native), runner), {})

    def test_normalization_omits_user_text_and_tool_arguments(self):
        event = hook.normalize(self.fixture("PreToolUse", tool_use_id="tool-1", tool_name="Bash", prompt="private", tool_input={"command": "private"}, transcript_path="private"))
        self.assertNotIn("private", json.dumps(event))
        self.assertEqual(event["tool_name"], "Bash")

    def test_retry_identity_and_repeated_lifecycle_identity(self):
        payload = self.fixture("PostToolUse", tool_use_id="tool-1")
        self.assertEqual(hook.normalize(payload), hook.normalize(payload))
        first = hook.normalize(self.fixture("PreToolUse", tool_use_id="tool-1"))
        self.assertNotEqual(first["event_id"], hook.normalize(payload)["event_id"])
        resumed = self.fixture("SessionStart", source="resume")
        self.assertNotEqual(hook.normalize(resumed)["event_id"], hook.normalize(resumed)["event_id"])

    def test_failed_hook_returns_warning_without_block(self):
        completed = subprocess.run([sys.executable, str(HERE / "hook.py")], input="not-json", text=True, capture_output=True, check=True)
        output = json.loads(completed.stdout)
        self.assertIn("unverified", output["systemMessage"])
        self.assertNotIn("decision", output)

    def test_unknown_event_is_no_op(self):
        self.assertEqual(hook.dispatch(self.fixture("FutureHook")), {})


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="experience-install-'$() ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_install_preserves_other_handlers_and_is_idempotent(self):
        directory = self.root / ".codex"
        directory.mkdir()
        target = directory / "hooks.json"
        original = {"description": "existing policy", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}], "matcher": ""}]}}
        target.write_text(json.dumps(original), encoding="utf-8")
        result = installer.install(self.root)
        self.assertTrue(result["changed"])
        first = target.read_text()
        self.assertFalse(installer.install(self.root)["changed"])
        self.assertEqual(target.read_text(), first)
        data = json.loads(first)
        self.assertEqual(data["description"], "existing policy")
        self.assertEqual(data["hooks"]["Stop"][0], original["hooks"]["Stop"][0])
        for event in data["hooks"].values():
            for group in event:
                for handler in group["hooks"]:
                    if installer.owned(handler):
                        argv = shlex.split(handler["command"])
                        self.assertEqual(Path(argv[1]), HERE / "hook.py")
        installer.install(self.root, uninstall=True)
        self.assertEqual(json.loads(target.read_text()), original)

    def test_uninstall_does_not_create_config(self):
        self.assertFalse(installer.install(self.root, uninstall=True)["changed"])
        self.assertFalse((self.root / ".codex").exists())

    def test_refuses_directory_and_file_symlinks(self):
        other = self.root / "other"
        other.mkdir()
        config = self.root / ".codex"
        config.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            installer.install(self.root)
        config.unlink()
        config.mkdir()
        (config / "hooks.json").symlink_to(other / "outside.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            installer.install(self.root)

    def test_invalid_existing_config_remains_unchanged(self):
        config = self.root / ".codex"
        config.mkdir()
        target = config / "hooks.json"
        target.write_text('{"hooks":{"Stop":"broken"}}')
        original = target.read_bytes()
        with self.assertRaises(ValueError):
            installer.install(self.root)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((config / "experience-strategy-install.lock").exists())

    def test_install_lock_prevents_overwrite(self):
        config = self.root / ".codex"
        config.mkdir()
        lock = config / "experience-strategy-install.lock"
        lock.write_text("other process")
        with self.assertRaisesRegex(ValueError, "Another installer"):
            installer.install(self.root)
        self.assertEqual(lock.read_text(), "other process")

    def test_shell_quote_handles_unusual_checkout_path(self):
        original_root = installer.REPO_ROOT
        with tempfile.TemporaryDirectory(prefix="experience-repo-'$() ") as tmp:
            fake = Path(tmp)
            (fake / "hooks").mkdir()
            (fake / "hooks" / "hooks.json").write_text((original_root / "hooks" / "hooks.json").read_text())
            installer.REPO_ROOT = fake
            try:
                installer.install(self.root)
                data = json.loads((self.root / ".codex" / "hooks.json").read_text())
                command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
                self.assertEqual(shlex.split(command)[1], str(fake / "adapters" / "codex" / "hook.py"))
            finally:
                installer.REPO_ROOT = original_root

    def test_plugin_manifest_and_event_coverage(self):
        manifest = json.loads((HERE.parents[1] / "plugin.json").read_text())
        self.assertEqual(manifest["extensions"]["com.openai"]["hooks"], "./hooks/hooks.json")
        config = json.loads((HERE.parents[1] / "hooks" / "hooks.json").read_text())
        self.assertEqual(set(config["hooks"]), set(hook.EVENTS))
        for event in ["Interrupt", "SessionEnd"]:
            self.assertLessEqual(config["hooks"][event][0]["hooks"][0]["timeout"], 3)


class CoreIntegrationTests(unittest.TestCase):
    """Real subprocess adapter -> runtime -> SQLite/state, native-shaped inputs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="experience-codex-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = HERE.parents[1]
        (self.root / "src").mkdir()
        self.artifact = self.root / "src" / "view.txt"
        self.artifact.write_text("initial fixture artifact", encoding="utf-8")
        self.run_script("scripts/harness.py", ["init", "--root", str(self.root), "--project-id", "adapter-test", "--goal", "Complete a test journey", "--scope", "Fixture only", "--version", "initial"])
        self.run_script("scripts/runtime.py", ["setup", "--root", str(self.root), "--watch", "src/**"])

    def run_script(self, relative, arguments=(), payload=None):
        completed = subprocess.run([sys.executable, str(self.repo / relative)] + list(arguments),
                                   input=None if payload is None else json.dumps(payload),
                                   text=True, capture_output=True, timeout=12)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def event(self, native, session="native-session", turn="native-turn", **values):
        payload = {"cwd": str(self.root / "src"), "session_id": session, "turn_id": turn,
                   "hook_event_name": native, **values}
        result = self.run_script("adapters/codex/hook.py", payload=payload)
        self.assertNotIn("could not run", result.get("systemMessage", ""))
        return result

    def context(self):
        return self.run_script("scripts/runtime.py", ["context", "--root", str(self.root)])

    def checkpoint(self):
        payload = self.context()["checkpoint_template"]
        payload["checkpoint"].update({
            "change": "Exercise the native-shaped adapter fixture",
            "reason": "Verify execution plumbing with a controlled local artifact",
            "summary": "Engineering fixture only; no real user behavior was observed.",
            "next_action": "Run a human-supervised host/model experiment separately.",
            "limitations": ["Synthetic lifecycle input; not a native Codex model execution or UX validation."],
        })
        return self.run_script("scripts/runtime.py", ["checkpoint", "--root", str(self.root)], payload)

    def test_full_adapter_core_change_checkpoint_and_stop(self):
        start = self.event("SessionStart", turn="", source="startup")
        self.assertEqual(start["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("SKILL.md", start["hookSpecificOutput"]["additionalContext"])
        self.event("UserPromptSubmit", prompt="Synthetic test task")
        self.assertEqual(self.context()["pending_count"], 2)
        self.assertFalse(self.checkpoint()["review_required"])
        before = self.event("PreToolUse", tool_name="apply_patch", tool_use_id="edit-1", tool_input={"command": "synthetic"})
        self.assertIn("No runtime review is pending", before["hookSpecificOutput"]["additionalContext"])
        self.artifact.write_text("changed fixture artifact", encoding="utf-8")
        self.event("PostToolUse", tool_name="apply_patch", tool_use_id="edit-1", tool_response="synthetic")
        changed = self.context()
        self.assertEqual(changed["required_node"], "after-change")
        self.event("PostToolUse", tool_name="apply_patch", tool_use_id="edit-1", tool_response="synthetic")
        self.assertEqual(self.context()["pending_ids"], changed["pending_ids"])
        self.assertEqual(self.event("Stop", stop_hook_active=False)["decision"], "block")
        self.assertNotIn("decision", self.event("Stop", stop_hook_active=False))
        self.assertFalse(self.checkpoint()["review_required"])
        self.assertNotIn("decision", self.event("Stop", stop_hook_active=True))
        self.assertEqual(self.context()["revision"], 2)

    def test_interrupt_and_new_session_preserve_pending_work(self):
        self.event("SessionStart", turn="", source="startup")
        self.event("UserPromptSubmit", prompt="Synthetic task to interrupt")
        pending = set(self.context()["pending_ids"])
        self.assertNotIn("decision", self.event("Interrupt"))
        self.assertNotIn("decision", self.event("Stop", stop_hook_active=False))
        self.event("SessionEnd", turn="", reason="other")
        self.event("SessionStart", session="next-session", turn="", source="resume")
        resumed = self.context()
        self.assertTrue(pending.issubset(set(resumed["pending_ids"])))
        self.assertEqual(resumed["revision"], 0)


if __name__ == "__main__":
    unittest.main()
