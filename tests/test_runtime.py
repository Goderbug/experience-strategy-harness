"""Execution-layer invariants. These tests do not measure design quality."""

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import harness
import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "view.txt").write_text("Initial visible experience", encoding="utf-8")
        self.args = SimpleNamespace(root=str(self.root))
        harness.initialize(SimpleNamespace(root=str(self.root), project_id="test", goal="Complete the primary journey", scope="The editor", mode="prototype", version="initial"))
        runtime.setup(SimpleNamespace(root=str(self.root), watch=["src/**"], max_continuations=1))
        self.serial = 0

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, function, payload):
        self.serial += 1
        path = self.root / ("input-" + str(self.serial) + ".json")
        path.write_text(json.dumps(payload), encoding="utf-8")
        return function(SimpleNamespace(root=str(self.root), input=str(path)))

    def event(self, kind, session="session", turn="turn", identifier=None, **extra):
        self.serial += 1
        return self.call(runtime.event, {"host": "codex", "session_id": session, "turn_id": turn,
                                        "event_id": identifier or "event-" + str(self.serial), "event": kind, **extra})

    def review(self, context=None, **updates):
        context = context or runtime.context(self.args)
        payload = copy.deepcopy(context["checkpoint_template"])
        payload["checkpoint"].update({"change": "Review the selected journey", "reason": "Changed visible behavior",
                                       "summary": "Observed the current flow; the proposed change needs runtime validation.",
                                       "next_action": "Validate the changed journey with real interaction evidence.",
                                       "limitations": ["This fixture is an engineering test, not product evidence."]})
        payload["checkpoint"].update(updates)
        return payload

    def test_disabled_without_setup_and_no_implicit_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(root=directory)
            self.assertFalse(runtime.context(args)["enabled"])
            path = Path(directory) / "event.json"
            path.write_text(json.dumps({"host": "deepseek", "session_id": "s", "turn_id": "t", "event_id": "e", "event": "stop"}))
            self.assertFalse(runtime.event(SimpleNamespace(root=directory, input=str(path)))["enabled"])
            self.assertFalse((Path(directory) / ".experience-strategy").exists())

    def test_full_lifecycle_change_review_and_resume(self):
        start = self.event("session-start", turn="")
        self.assertEqual(start["required_node"], "resume")
        before = self.event("turn-start")
        self.assertEqual(before["pending_count"], 2)
        initial = self.call(runtime.checkpoint, self.review(before))
        self.assertFalse(initial["review_required"])
        (self.root / "src" / "view.txt").write_text("Changed visible experience")
        after = self.event("tool-result", tool_name="apply_patch")
        self.assertEqual(after["required_node"], "after-change")
        self.assertTrue(self.event("stop")["block_stop"])
        accepted = self.call(runtime.checkpoint, self.review(after))
        self.assertEqual(accepted["revision"], 2)
        self.assertFalse(self.event("stop", continuation=True)["block_stop"])
        resumed = self.event("session-start", session="new-session", turn="")
        self.assertEqual(resumed["revision"], 2)
        self.assertEqual(resumed["required_node"], "resume")

    def test_read_tools_and_duplicate_events_do_not_create_work(self):
        first = self.event("turn-start", identifier="same")
        duplicate = self.event("turn-start", identifier="same")
        self.assertTrue(duplicate["duplicate_event"])
        self.assertEqual(first["pending_ids"], duplicate["pending_ids"])
        self.call(runtime.checkpoint, self.review(first))
        self.assertFalse(self.event("before-tool", tool_name="read_file")["review_required"])
        self.assertFalse(self.event("tool-result", tool_name="read_file")["review_required"])
        with self.assertRaisesRegex(harness.HarnessError, "different body"):
            self.event("stop", identifier="same")

    def test_repeated_tool_context_is_suppressed_until_review_basis_changes(self):
        start = self.event("turn-start")
        self.assertTrue(start["context"])
        before = self.event("before-tool", tool_name="read_file")
        self.assertEqual(before["context"], "")
        self.assertEqual(before["context_key"], start["context_key"])
        unchanged = self.event("tool-result", tool_name="read_file")
        self.assertEqual(unchanged["context"], "")
        (self.root / "src" / "view.txt").write_text("Changed visual behavior")
        changed = self.event("tool-result", tool_name="apply_patch")
        self.assertTrue(changed["context"])
        self.assertNotEqual(changed["context_key"], start["context_key"])
        self.assertEqual(self.event("before-tool")["context"], "")
        self.assertTrue(self.event("stop")["context"])
        self.assertTrue(runtime.context(self.args)["context"])
        self.assertTrue(self.event("turn-start", turn="second")["context"])

    def test_stop_cap_duplicate_stop_and_interruption(self):
        self.event("turn-start")
        self.assertTrue(self.event("stop", identifier="stop-1")["block_stop"])
        duplicate = self.event("stop", identifier="stop-1")
        self.assertFalse(duplicate["block_stop"])
        self.assertTrue(duplicate["review_required"])
        exhausted = self.event("stop", identifier="stop-2")
        self.assertFalse(exhausted["block_stop"])
        self.assertIn("budget exhausted", exhausted["warning"])
        self.event("turn-start", turn="other")
        self.event("interrupt", turn="other")
        stopped = self.event("stop", turn="other")
        self.assertFalse(stopped["block_stop"])
        self.assertIn("interrupted", stopped["warning"])
        self.assertTrue(stopped["review_required"])

    def test_interrupt_and_session_end_never_hash_or_replay_strategy(self):
        first = self.event("turn-start")
        with patch.object(runtime, "snapshot", side_effect=AssertionError("must not hash")), patch.object(harness, "load", side_effect=AssertionError("must not replay history")):
            interrupted = self.event("interrupt")
            ended = self.event("session-end", turn="")
        self.assertEqual(interrupted["pending_ids"], first["pending_ids"])
        self.assertEqual(ended["pending_ids"], first["pending_ids"])
        self.assertEqual(interrupted["context"], "")
        self.assertTrue(ended["revision_cached"])
        self.assertFalse(self.event("stop")["block_stop"])

    def test_interrupt_lock_contention_returns_promptly_without_losing_pending(self):
        self.event("turn-start")
        database = sqlite3.connect(str(self.root / ".experience-strategy" / runtime.DB_NAME))
        database.execute("BEGIN IMMEDIATE")
        payload = {"host": "codex", "session_id": "s", "turn_id": "t", "event_id": "e", "event": "interrupt"}
        started = time.monotonic()
        try:
            process = subprocess.run([sys.executable, str(SCRIPTS / "runtime.py"), "event", "--root", str(self.root)], input=json.dumps(payload), text=True, capture_output=True, timeout=2)
        finally:
            database.rollback()
            database.close()
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(process.returncode, 1)
        self.assertFalse(json.loads(process.stdout)["ok"])
        self.assertTrue(runtime.context(self.args)["review_required"])

    def test_continuation_flag_cannot_request_another_turn(self):
        self.event("turn-start")
        result = self.event("stop", continuation=True)
        self.assertFalse(result["block_stop"])
        self.assertTrue(result["review_required"])
        self.assertIn("already a continuation", result["warning"])

    def test_snapshot_change_rejects_stale_review_and_detects_add_delete(self):
        context = self.event("turn-start")
        payload = self.review(context)
        (self.root / "src" / "new.txt").write_text("new")
        with self.assertRaisesRegex(harness.HarnessError, "changed since review"):
            self.call(runtime.checkpoint, payload)
        changed = runtime.context(self.args)
        self.assertNotEqual(changed["snapshot"], context["snapshot"])
        self.assertEqual(changed["required_node"], "after-change")
        (self.root / "src" / "new.txt").unlink()
        deleted = self.event("tool-result")
        self.assertEqual(deleted["snapshot"], context["snapshot"])
        self.assertEqual(deleted["pending_count"], 3)

    def test_old_receipt_cannot_clear_new_work(self):
        first = self.event("turn-start")
        payload = self.review(first)
        self.call(runtime.checkpoint, payload)
        newer = self.event("turn-start", turn="new")
        retried = self.call(runtime.checkpoint, payload)
        self.assertTrue(retried["duplicate_checkpoint"])
        self.assertEqual(retried["pending_ids"], newer["pending_ids"])
        forged = copy.deepcopy(payload)
        forged["pending_ids"] = newer["pending_ids"]
        with self.assertRaisesRegex(harness.HarnessError, "different runtime"):
            self.call(runtime.checkpoint, forged)

    def test_old_direct_commit_cannot_be_wrapped_as_runtime_completion(self):
        context = self.event("turn-start")
        payload = self.review(context)
        runtime.commit_checkpoint(self.root, payload["checkpoint"])
        with self.assertRaisesRegex(harness.HarnessError, "old receipt"):
            self.call(runtime.checkpoint, payload)
        self.assertTrue(runtime.context(self.args)["review_required"])

    def test_crash_after_strategy_commit_can_retry_without_double_commit(self):
        context = self.event("turn-start")
        payload = self.review(context)
        original = runtime.commit_checkpoint

        def crashed(root, checkpoint):
            original(root, checkpoint)
            raise SystemExit("simulated process failure after strategy commit")

        with patch.object(runtime, "commit_checkpoint", side_effect=crashed):
            with self.assertRaises(SystemExit):
                self.call(runtime.checkpoint, payload)
        self.assertEqual(harness.context(self.args)["revision"], 1)
        self.assertTrue(runtime.context(self.args)["review_required"])
        recovered = self.call(runtime.checkpoint, payload)
        self.assertFalse(recovered["review_required"])
        self.assertEqual(recovered["revision"], 1)
        self.assertEqual(recovered["receipt"]["request_id"], payload["checkpoint"]["request_id"])

    def test_change_during_commit_leaves_review_unacknowledged(self):
        context = self.event("turn-start")
        payload = self.review(context)
        original = runtime.commit_checkpoint

        def mutate(root, checkpoint):
            receipt = original(root, checkpoint)
            (self.root / "src" / "view.txt").write_text("Changed during review commit")
            return receipt

        with patch.object(runtime, "commit_checkpoint", side_effect=mutate):
            with self.assertRaisesRegex(harness.HarnessError, "during checkpoint commit"):
                self.call(runtime.checkpoint, payload)
        context = runtime.context(self.args)
        self.assertEqual(context["revision"], 1)
        self.assertTrue(context["review_required"])
        self.assertEqual(context["required_node"], "after-change")

    def test_concurrent_duplicate_processes_and_changed_events(self):
        payload = {"host": "codex", "session_id": "shared", "turn_id": "t", "event_id": "same", "event": "turn-start"}

        def run(_):
            process = subprocess.run([sys.executable, str(SCRIPTS / "runtime.py"), "event", "--root", str(self.root)], input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            return json.loads(process.stdout)

        with ThreadPoolExecutor(max_workers=6) as pool:
            outputs = list(pool.map(run, range(6)))
        self.assertEqual(sum(not item["duplicate_event"] for item in outputs), 1)
        self.assertEqual(runtime.context(self.args)["pending_count"], 1)
        (self.root / "src" / "view.txt").write_text("one shared change")
        payload.update(event="tool-result", event_id="changed")
        with ThreadPoolExecutor(max_workers=6) as pool:
            outputs = list(pool.map(run, range(6)))
        self.assertEqual(runtime.context(self.args)["pending_count"], 2)

    def test_database_transaction_recovers_after_process_exit(self):
        db = self.root / ".experience-strategy" / runtime.DB_NAME
        code = "import sqlite3,os,sys; c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE'); c.execute(\"UPDATE meta SET value='999' WHERE key='change_serial'\"); os._exit(23)"
        process = subprocess.run([sys.executable, "-c", code, str(db)])
        self.assertEqual(process.returncode, 23)
        self.assertTrue(self.event("turn-start")["review_required"])
        database = sqlite3.connect(str(db))
        try:
            self.assertEqual(database.execute("SELECT value FROM meta WHERE key='change_serial'").fetchone()[0], "0")
        finally:
            database.close()

    def test_symlink_and_traversal_scope_rejected(self):
        with self.assertRaises(harness.HarnessError):
            runtime.pattern_regex("../outside/**")
        with self.assertRaises(harness.HarnessError):
            runtime.pattern_regex(".env")
        (self.root / "src" / "linked.txt").symlink_to(self.root / "input.json")
        with self.assertRaisesRegex(harness.HarnessError, "not a regular file"):
            runtime.context(self.args)
        (self.root / "src" / "linked.txt").unlink()
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "src" / "linked-directory").symlink_to(outside)
            with self.assertRaisesRegex(harness.HarnessError, "symlink"):
                runtime.context(self.args)

    def test_excluded_secrets_and_nested_globs(self):
        baseline = runtime.context(self.args)["snapshot"]
        (self.root / "src" / ".env.local").write_text("SECRET=not-persisted")
        (self.root / "src" / "private.key").write_text("sensitive")
        self.assertEqual(runtime.context(self.args)["snapshot"], baseline)
        self.assertTrue(runtime.pattern_regex("src/**/*.tsx").fullmatch("src/a.tsx"))
        self.assertTrue(runtime.pattern_regex("src/**/*.tsx").fullmatch("src/sub/a.tsx"))

    def test_setup_cannot_overwrite_and_scope_is_bounded(self):
        same = runtime.setup(SimpleNamespace(root=str(self.root), watch=["src/**"], max_continuations=1))
        self.assertFalse(same["created"])
        with self.assertRaisesRegex(harness.HarnessError, "already configured"):
            runtime.setup(SimpleNamespace(root=str(self.root), watch=["other/**"], max_continuations=1))
        with patch.object(runtime, "MAX_FILES", 0):
            with self.assertRaises(harness.HarnessError):
                runtime.context(self.args)

    def test_runtime_state_never_contains_prompt_or_tool_output(self):
        payload = {"host": "codex", "session_id": "s", "turn_id": "t", "event_id": "e", "event": "tool-result", "prompt": "private user prompt"}
        with self.assertRaisesRegex(harness.HarnessError, "unknown fields"):
            self.call(runtime.event, payload)
        self.event("turn-start")
        output = runtime.context(self.args)
        self.assertIn("runtime.py checkpoint", output["context"])
        self.assertIn("does not grant or replace tool permissions", output["context"])
        self.assertLess(len(output["context"]), 12000)
        self.assertNotIn("private user prompt", (self.root / ".experience-strategy" / runtime.DB_NAME).read_bytes().decode("utf-8", errors="ignore"))

    def test_node_and_version_must_match_pending_review(self):
        context = self.event("turn-start")
        payload = self.review(context, node="feedback")
        with self.assertRaisesRegex(harness.HarnessError, "node must match"):
            self.call(runtime.checkpoint, payload)
        payload = self.review(context)
        payload["checkpoint"]["project_version"] = "unrelated"
        with self.assertRaisesRegex(harness.HarnessError, "must equal"):
            self.call(runtime.checkpoint, payload)

    def test_cli_errors_are_json_and_nonzero(self):
        process = subprocess.run([sys.executable, str(SCRIPTS / "runtime.py"), "event", "--root", str(self.root)], input="not json", text=True, capture_output=True)
        self.assertEqual(process.returncode, 1)
        self.assertFalse(json.loads(process.stdout)["ok"])
        self.assertEqual(process.stderr, "")
        invalid_args = subprocess.run([sys.executable, str(SCRIPTS / "runtime.py"), "event"], text=True, capture_output=True)
        self.assertEqual(invalid_args.returncode, 1)
        self.assertEqual(json.loads(invalid_args.stdout)["error"], "invalid_arguments")


if __name__ == "__main__":
    unittest.main()
