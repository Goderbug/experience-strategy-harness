import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine
import harness
import runtime
import status_model


class StatusProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / "project"
        self.root.mkdir()

    def project(self, verify=False):
        return status_model.build_snapshot([self.root], verify_files=verify)["projects"][0]

    def initialize(self):
        (self.root / "baseline.txt").write_text("original")
        harness.initialize(NS(root=self.root, project_id="reading", goal="Read",
                              scope="Test", mode="analysis-only", version="v1"))

    def configure(self):
        self.initialize()
        runtime.setup(NS(root=self.root, watch=["baseline.txt"], max_continuations=1))

    def open_case(self, cid, **changes):
        payload = dict(case_id=cid, claim="Check the card", goal="Read", claim_type="artifact", mode="fixture")
        payload.update(changes)
        with patch.object(runtime, "read_input", return_value=payload):
            return engine.open_case(NS(root=self.root))

    def submit(self, case, output):
        payload = dict(case_id=case["case_id"], binding=case["binding"], expected_revision=case["revision"],
                       request_id="r-" + str(case["revision"]), role=case["next_role"], output=output)
        with patch.object(runtime, "read_input", return_value=payload):
            return engine.advance(NS(root=self.root, command="submit"))

    def state_storage(self):
        return {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in (self.root / ".experience-strategy").iterdir()}

    def test_absent_and_strategy_only_are_readable_without_setup(self):
        result = self.project()
        self.assertEqual(result["status"], "not_initialized")
        self.assertIsNone(result["runtime"]["pending_count"])
        self.assertFalse((self.root / ".experience-strategy").exists())
        self.initialize()
        before = self.state_storage()
        result = self.project()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["runtime"], {"enabled": False, "pending_count": None, "latest_event": None})
        self.assertEqual(result["cases"], [])
        self.assertEqual(self.state_storage(), before)

    def test_live_creative_projection_does_not_acknowledge_or_change_versions(self):
        self.configure()
        case = self.open_case("card", task_stage="create", mode="live")
        case = self.submit(case, dict(change="Show Save", tradeoff="A busier row", acceptance="Save in initial view"))
        candidate = case["candidate_dir"] + "/card.html"
        (self.root / candidate).parent.mkdir(parents=True)
        (self.root / candidate).write_text("<button>Save</button>")
        case = self.submit(case, dict(change="Added a visible action", candidate_refs=[candidate], review_steps="Open it"))
        (self.root / "check.txt").write_text("Save is in HTML")
        self.submit(case, dict(outcome="ready", checks=[dict(check="Save exists", result="pass", observation="In markup")],
                               evidence_refs=["check.txt"], limitations="Markup only"))
        with patch.object(runtime, "read_input", return_value=dict(event="session-start", session_id="s",
                               turn_id="", event_id="e", host="codex")):
            runtime.event(NS(root=self.root))
        before = self.state_storage()
        a = self.project()
        self.assertEqual(a["runtime"]["pending_count"], 1)
        self.assertIsNotNone(a["runtime"]["latest_event"])
        c = a["cases"][0]
        self.assertEqual([c[key] for key in ("phase", "user_evidence", "user_outcome")],
                         ["candidate_ready", "disabled", "unverified"])
        self.assertEqual([s["status"] for s in c["steps"]], ["done"] * 3)
        self.assertEqual(c["history"][1]["refs"][0]["path"], candidate)
        self.assertIsNone(c["stale_snapshot"])
        self.assertIsNone(c["integrity"])
        (self.root / "baseline.txt").write_text("changed")
        (self.root / candidate).write_text("changed candidate")
        b = self.project(verify=True)["cases"][0]
        self.assertTrue(b["stale_snapshot"])
        self.assertEqual(b["integrity"], {"candidate": "changed", "check_record": "matches"})
        self.assertEqual(self.state_storage(), before)
        self.assertNotIn('"binding"', json.dumps(a))
        self.assertNotIn('"checkpoints"', json.dumps(a))

    def test_real_legacy_wait_surfaces_judge_and_trigger_without_fake_user_research(self):
        self.configure()
        c = self.open_case("earlier", claim_type="behavior", mode="live")
        c = self.submit(c, dict(intent="Preserve context", options=["A", "B"], proposal="Use A", assumption="Works",
                                reopen_if="Unexpected difficulty"))
        c = self.submit(c, dict(objection="Hidden control", consequence="Missed action", check="Observe", reason="Unknown"))
        c = self.submit(c, dict(method="artifact-check", provenance="artifact", finding="inconclusive",
                                observation="Control exists", scope="Markup", evidence_refs=["baseline.txt"], limitations="No task data"))
        self.submit(c, dict(outcome="defer", rationale="Requires observation", critic_response="Keep objection",
                            tradeoff="Visibility has a cost", next_trigger="A participant tries the task"))
        r = self.project()["cases"][0]
        self.assertEqual((r["stage"], r["phase"], r["user_outcome"]), ("legacy_review", "waiting_evidence", "unverified"))
        self.assertEqual(r["next_trigger"], "A participant tries the task")
        self.assertIsNone(r["next_role"])
        self.assertEqual([s["role"] for s in r["steps"]], ["strategist", "critic", "verifier", "judge"])

    def test_more_than_host_hint_limit_and_reattempted_steps(self):
        self.configure()
        count = engine.LIST_LIMIT + 2
        for i in range(count):
            self.open_case("case-" + str(i))
        self.assertEqual(len(self.project()["cases"]), count)
        # A retry resets the visualization's active iteration even with older measurement receipts.
        steps = status_model._steps(dict(route="creation", task_stage="create",
                                    history=[{"role": r} for r in ("critic", "execution", "measurement")]), "execution")
        self.assertEqual([s["status"] for s in steps], ["done", "current", "upcoming"])

    def test_bad_runtime_and_symlinks_are_reported_without_reading_through(self):
        self.configure()
        self.open_case("card")
        state = self.root / ".experience-strategy"
        runtime_file = state / runtime.DB_NAME
        runtime_file.write_bytes(b"corrupt")
        a = self.project()
        self.assertEqual(a["status"], "partial")
        self.assertIsNone(a["runtime"]["pending_count"])
        self.assertEqual(len(a["cases"]), 1)
        db = state / engine.DB
        other = self.root / "other.sqlite"
        db.rename(other)
        db.symlink_to(other)
        self.assertEqual(self.project()["cases"], [])
        self.assertIn("unsafe_path", self.project()["error"])
        state_json = state / "state.json"
        renamed = self.root / "outside-state.json"
        state_json.rename(renamed)
        state_json.symlink_to(renamed)
        self.assertEqual(self.project()["status"], "error")

    def test_same_named_projects_are_distinct_and_bad_project_is_isolated(self):
        a = self.root / "a" / "same"
        b = self.root / "b" / "same"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        (b / ".experience-strategy").write_text("invalid")
        projects = status_model.build_snapshot([a, b, a])["projects"]
        self.assertEqual([p["status"] for p in projects], ["not_initialized", "error"])
        self.assertNotEqual(projects[0]["id"], projects[1]["id"])


if __name__ == "__main__":
    unittest.main()
