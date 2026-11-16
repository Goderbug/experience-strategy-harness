"""Contract tests using separate CLI processes, as external host agents would."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "harness.py"


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.init_args = ["init", "--project-id", "sample", "--goal", "Resume interrupted reading",
                          "--scope", "Open, read, switch app, return", "--version", "v1"]
        self.call(*self.init_args)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *arguments, body=None, error=None):
        completed = subprocess.run([sys.executable, str(SCRIPT), *arguments, "--root", str(self.root)],
                                   input=json.dumps(body) if body is not None else None,
                                   text=True, capture_output=True)
        if error:
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            result = json.loads(completed.stderr)
            self.assertEqual(result["error"], error, result)
        else:
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result["ok"])
        return result

    def envelope(self, request_id="c1", revision=0, **updates):
        envelope = {"request_id": request_id, "expected_revision": revision, "node": "intake",
                    "project_version": "v1", "change": "Inspect interruption recovery", "depth": "focused",
                    "reason": "A relevant journey changed", "summary": "Recovery requires investigation",
                    "next_action": "Observe switching away and returning", "limitations": ["No user test"]}
        envelope.update(updates)
        return envelope

    def concern(self, **updates):
        concern = {"id": "reading-recovery", "kind": "issue", "goal_ids": ["goal-primary"],
                   "statement": "Returning may lose reading position", "basis": "hypothesis", "status": "open",
                   "evidence_ids": [], "strategy": "Inspect the interrupted reading path",
                   "alternatives": ["Keep location in panel", "Open a persistent window"],
                   "tradeoff": "Persistence can increase window complexity", "next_trigger": "Navigation changes",
                   "validation": {"status": "unverified", "evidence_ids": [], "version": "v1",
                                  "note": "No independent observation yet"}}
        concern.update(updates)
        return concern

    def evidence(self, kind="runtime-test", version="v1", eid="test-1"):
        return {"id": eid, "kind": kind, "source": "Local test run, interrupted reading, step 4",
                "summary": "This specified path restores the saved position", "version": version}

    def committed(self, envelope, error=None):
        return self.call("commit", "--input", "-", body=envelope, error=error)

    def state(self):
        return json.loads((self.root / ".experience-strategy" / "state.json").read_text())

    def resolved(self, **updates):
        return self.concern(status="resolved", evidence_ids=["test-1"],
                            resolution_reason="Saved position restored in the cited interruption path only",
                            validation={"status": "pass", "evidence_ids": ["test-1"],
                                        "version": "v1", "note": "Verified only this navigation path"}, **updates)

    def test_resolved_requires_scoped_resolution_reason(self):
        concern = self.resolved()
        del concern["resolution_reason"]
        self.committed(self.envelope(concerns=[concern], evidence=[self.evidence()]), error="invalid_input")
        self.assertEqual(self.state()["revision"], 0)

    def test_fresh_process_preserves_issue_and_awaiting_validation(self):
        self.committed(self.envelope(concerns=[self.concern()]))
        self.committed(self.envelope("c2", 1, node="after-change", project_version="v2",
                                    concerns=[self.concern(status="awaiting-validation")]))
        context = self.call("context")
        self.assertEqual(context["revision"], 2)
        self.assertEqual([item["id"] for item in context["concerns"]], ["reading-recovery"])
        self.assertEqual(context["concerns"][0]["status"], "awaiting-validation")
        self.assertEqual(context["latest_checkpoint"]["node"], "after-change")
        self.assertFalse(context["online"])
        self.assertFalse(context["capabilities"]["background_monitoring"])
        state = self.state()
        self.assertEqual(state["checkpoints"][1]["before"]["concerns"]["reading-recovery"]["status"], "open")
        self.call("validate")

    def test_failed_unverified_and_simulation_only_closure_rejected(self):
        for validation_status in ("fail", "unverified"):
            with self.subTest(validation_status=validation_status):
                concern = self.resolved()
                concern["validation"]["status"] = validation_status
                self.committed(self.envelope(concerns=[concern], evidence=[self.evidence()]), error="invalid_input")
        for kind in ("simulation", "document"):
            with self.subTest(kind=kind):
                self.committed(self.envelope(concerns=[self.resolved()], evidence=[self.evidence(kind)]), error="invalid_input")
        self.assertEqual(self.state()["revision"], 0)

    def test_verified_scope_closure_then_explicit_reopen(self):
        self.committed(self.envelope(concerns=[self.resolved()], evidence=[self.evidence()]))
        self.committed(self.envelope("c2", 1, project_version="v2", node="before-change"))
        # Version changes retain old scoped evidence without claiming current validation.
        context = self.call("context")
        self.assertEqual(context["concerns"][0]["status"], "resolved")
        self.assertEqual(context["concerns"][0]["validation"]["version"], "v1")
        self.committed(self.envelope("c3", 2, project_version="v2", concerns=[self.concern()]), error="invalid_input")
        reopened = self.concern(resolution_reason="New window architecture invalidates the old path test")
        self.committed(self.envelope("c3", 2, project_version="v2", concerns=[reopened]))
        self.assertEqual(self.state()["concerns"]["reading-recovery"]["status"], "open")
        self.assertIn("test-1", self.state()["evidence"])

    def test_closure_requires_version_matched_evidence_and_checkpoint(self):
        self.committed(self.envelope(concerns=[self.resolved()], evidence=[self.evidence(version="v0")]), error="invalid_input")
        self.committed(self.envelope(project_version="v2", concerns=[self.resolved()], evidence=[self.evidence()]), error="invalid_input")

    def test_idempotent_request_retains_exact_receipt_after_later_checkpoints(self):
        original = self.envelope(concerns=[self.concern()])
        receipt = self.committed(original)
        self.committed(self.envelope("c2", 1, node="resume"))
        self.assertEqual(receipt, self.committed(original))
        self.assertEqual(self.state()["revision"], 2)
        different = copy.deepcopy(original)
        different["summary"] = "Different meaning"
        self.committed(different, error="request_conflict")
        self.committed(self.envelope("c3", 0), error="stale_revision")

    def test_initialization_is_non_destructive_and_original_resume_still_works(self):
        self.committed(self.envelope(project_version="v2"))
        before = self.state()
        resumed = self.call(*self.init_args)
        self.assertFalse(resumed["created"])
        self.assertEqual(resumed["revision"], 1)
        changed = list(self.init_args)
        changed[changed.index("--goal") + 1] = "Unrelated goal"
        self.call(*changed, error="already_initialized")
        self.assertEqual(before, self.state())

    def test_evidence_and_decisions_are_immutable(self):
        decision = {"id": "d1", "concern_ids": ["reading-recovery"], "choice": "Observe first",
                    "reason": "Evidence is incomplete", "origin": "agent", "source": "Intake analysis", "version": "v1"}
        self.committed(self.envelope(concerns=[self.concern()], evidence=[self.evidence()], decisions=[decision]))
        changed_evidence = self.evidence()
        changed_evidence["summary"] = "Rewritten history"
        self.committed(self.envelope("c2", 1, evidence=[changed_evidence]), error="immutable_record")
        changed_decision = dict(decision, choice="Different decision")
        self.committed(self.envelope("c2", 1, decisions=[changed_decision]), error="immutable_record")
        self.committed(self.envelope("c2", 1, concerns=[self.concern(status="awaiting-validation")]))
        self.assertIn("d1", self.state()["decisions"])
        self.assertIn("test-1", self.state()["evidence"])

    def test_references_duplicate_ids_and_unknown_fields_rejected(self):
        self.committed(self.envelope(concerns=[self.concern(goal_ids=["missing"])]), error="invalid_input")
        self.committed(self.envelope(concerns=[self.concern(evidence_ids=["missing"])]), error="invalid_input")
        self.committed(self.envelope(concerns=[self.concern(), self.concern()]), error="invalid_input")
        self.committed(self.envelope(unrecognized="ignored?"), error="invalid_input")

    def test_deferral_and_dismissal_require_reason_and_are_not_success(self):
        for status in ("deferred", "dismissed"):
            self.committed(self.envelope(concerns=[self.concern(status=status)]), error="invalid_input")
        self.committed(self.envelope(concerns=[self.concern(status="dismissed", resolution_reason="Outside the agreed task")]))
        concern = self.call("context")["concerns"][0]
        self.assertEqual(concern["status"], "dismissed")
        self.assertEqual(concern["validation"]["status"], "unverified")

    def test_project_update_preserves_old_focus_and_goals(self):
        self.committed(self.envelope(project_update={"goal": "Quick triage", "scope": "Glance only", "mode": "prototype"}))
        state = self.state()
        self.assertEqual(state["project"]["goal"], "Quick triage")
        self.assertEqual(state["goals"]["goal-primary"]["statement"], "Resume interrupted reading")
        self.assertEqual(state["checkpoints"][0]["before"]["project"]["goal"], "Resume interrupted reading")

    def test_existing_lock_is_never_removed(self):
        lock = self.root / ".experience-strategy" / "write.lock"
        lock.write_text('{"pid": -1, "created_at": "old"}')
        response = self.committed(self.envelope(), error="locked")
        self.assertIn("confirm no writer", response["message"])
        self.assertTrue(lock.exists())
        self.assertEqual(self.state()["revision"], 0)

    def test_state_file_symlink_is_rejected(self):
        path = self.root / ".experience-strategy" / "state.json"
        target = self.root / "elsewhere.json"
        path.rename(target)
        path.symlink_to(target)
        before = target.read_bytes()
        self.call("context", error="unsafe_path")
        self.committed(self.envelope(), error="unsafe_path")
        self.assertEqual(before, target.read_bytes())

    def test_data_directory_symlink_is_rejected(self):
        path = self.root / ".experience-strategy"
        target = self.root / "elsewhere"
        path.rename(target)
        path.symlink_to(target, target_is_directory=True)
        self.call("validate", error="unsafe_path")
        self.call(*self.init_args, error="unsafe_path")

    def test_export_is_source_free_and_never_overwrites(self):
        self.committed(self.envelope(concerns=[self.concern()], evidence=[self.evidence()]))
        (self.root / "secret-reference.txt").write_text("Source content must stay local")
        output = Path(self.temp.name) / "return-package"
        receipt = self.call("export", "--output", str(output))
        self.assertFalse(receipt["source_materials_copied"])
        self.assertEqual(set(item.name for item in output.iterdir()), {"state.json", "checkpoints.jsonl", "RETURN-REPORT.md"})
        self.assertEqual(json.loads((output / "state.json").read_text()), self.state())
        self.assertEqual(len((output / "checkpoints.jsonl").read_text().splitlines()), 1)
        self.assertIn("not an evaluation or proof", (output / "RETURN-REPORT.md").read_text())
        before = {item.name: item.read_bytes() for item in output.iterdir()}
        self.call("export", "--output", str(output), error="output_exists")
        self.assertEqual(before, {item.name: item.read_bytes() for item in output.iterdir()})

    def test_corrupt_history_is_rejected_before_mutation(self):
        self.committed(self.envelope())
        state = self.state()
        state["checkpoints"][0]["input"]["summary"] = "Tampered checkpoint"
        path = self.root / ".experience-strategy" / "state.json"
        path.write_text(json.dumps(state))
        self.call("validate", error="invalid_state")
        self.committed(self.envelope("c2", 1), error="invalid_state")


if __name__ == "__main__":
    unittest.main()
