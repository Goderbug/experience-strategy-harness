"""Kernel integration tests: real files and SQLite, no model or product execution."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import engine
import harness
import runtime


class EngineTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.base = Path(td.name)
        self.root = self.project("root")

    def project(self, name):
        root = self.base / name
        (root / "src").mkdir(parents=True)
        (root / "src/header.txt").write_text("sample header")
        (root / "proof.txt").write_text("fixture: sample observation")
        harness.initialize(NS(root=str(root), project_id=name, goal="Read", scope="Header", mode="analysis-only", version="v1"))
        runtime.setup(NS(root=str(root), watch=["src/**"], max_continuations=1))
        return root

    def command(self, cmd, data, root=None):
        with patch.object(sys, "stdin", io.StringIO(json.dumps(data))):
            args = NS(root=str(root or self.root), command=cmd, input="-")
            return {"open":engine.open_case, "submit":engine.advance, "resume":engine.advance}[cmd](args)

    def opening(self, **changes):
        return dict({"case_id":"card", "goal":"Glance", "claim":"The header control is absent",
                     "claim_type":"artifact", "mode":"fixture"}, **changes)

    def advance(self, case, output=None, **changes):
        envelope = dict(case_id=case["case_id"], expected_revision=case["revision"], binding=case["binding"],
                        request_id="req-"+str(case["revision"]), role=case["next_role"], output=output)
        envelope.update(changes)
        return self.command("submit", envelope)

    def check_error(self, code, function, *args, **kwargs):
        with self.assertRaises(harness.HarnessError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def verifier(self, finding="supports", **changes):
        return dict({"method":"artifact-check", "provenance":"simulation", "finding":finding,
                     "observation":"Fixture supplies a captured observation.", "scope":"Header only",
                     "evidence_refs":["proof.txt"], "limitations":"Not a live user observation."}, **changes)

    def strategist(self):
        return dict(intent="Keep the header quiet", options=["retain","move"], proposal="retain", assumption="Header is quiet",
                    reopen_if="Control visible")

    def critic(self):
        return dict(objection="Control hidden", consequence="Missed affordance", check="inspect header",
                    reason="Artifact constrains the proposed layout")

    def judge(self, outcome):
        return dict(outcome=outcome, rationale="Only the header in the observed fixture",
                    critic_response="Limit to the checked header", tradeoff="Does not cover discovery",
                    next_trigger="New header or observation")

    def test_disabled_read_no_side_effect_and_uninitialized_refusal(self):
        empty = self.base / "not-initialized"
        empty.mkdir()
        self.assertFalse(engine.summary_if_enabled(empty)["enabled"])
        self.check_error("not_configured", self.command, "open", self.opening(), empty)
        self.assertEqual(list(empty.iterdir()), [])

    def test_standalone_cli_read_after_exit_and_explicit_flags(self):
        args = [sys.executable, str(SCRIPTS/"engine.py")]
        p = subprocess.run(args+["open","--root",str(self.root)],input=json.dumps(self.opening()),text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        c=json.loads(p.stdout)
        p = subprocess.run(args+["context","--root",str(self.root),"--case-id","card"],text=True,capture_output=True)
        self.assertEqual(json.loads(p.stdout)["binding"], c["binding"])
        p = subprocess.run(args+["submit","--root",str(self.root)],input="{}",text=True,capture_output=True)
        self.assertNotEqual(p.returncode,0)
        self.assertFalse(json.loads(p.stdout)["ok"])

    def test_green_direct_does_not_close_runtime_checkpoint(self):
        self.command("open", self.opening())
        again = self.command("open", self.opening())
        self.assertTrue(again["duplicate"])
        snap = again["snapshot"]
        state_before = (self.root/".experience-strategy/state.json").read_bytes()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(dict(host="codex",session_id="fixture",turn_id="1",
                event_id="u1",event="turn-start")))):
            r = runtime.event(NS(root=str(self.root), input="-"))
        result = self.advance(again, self.verifier())
        self.assertEqual(result["receipt"]["snapshot"], snap)
        self.assertEqual(result["phase"],"verified")
        self.assertEqual(len(result["history"][0]["evidence_files"][0]["sha256"]),64)
        r2 = runtime.context(NS(root=str(self.root)))
        self.assertEqual(r2["pending_ids"], r["pending_ids"])
        self.assertEqual((self.root/".experience-strategy/state.json").read_bytes(), state_before)
        self.assertTrue(self.advance(again,self.verifier())["duplicate"])
        self.check_error("request_conflict", self.advance, again,self.verifier(scope="different"))
        self.check_error("stale_revision", self.advance, again,self.verifier(),request_id="not-the-same-retry")

    def test_closed_role_and_same_case_id_in_another_root(self):
        a=self.command("open",self.opening())
        other=self.project("second")
        b=self.command("open",self.opening(),other)
        self.assertNotEqual(a["binding"], b["binding"])
        self.check_error("wrong_binding",self.command,"submit",dict(case_id="card",expected_revision=0,
                         request_id="r",binding=a["binding"],role="verifier",output=self.verifier()),other)
        self.check_error("wrong_role",self.advance,a,self.judge("keep"),role="judge")
        self.check_error("case_conflict",self.command,"open",self.opening(goal="different"))

    def test_validate_concern_identity_and_preserve_linked_strategy(self):
        self.check_error("unknown_concern", self.command,"open",self.opening(concern_id="other-root-id"))
        self.assertFalse((self.root/".experience-strategy/engine.sqlite3").exists())
        env={"request_id":"intake","expected_revision":0,"node":"intake","project_version":"v1",
             "change":"Record concern","depth":"focused","reason":"Local case","summary":"Observation needed",
             "next_action":"Verify in scope","limitations":["No observation"],"concerns":[{
             "id":"C","kind":"issue","goal_ids":["goal-primary"],"statement":"Header may be busy",
             "basis":"hypothesis","status":"awaiting-validation","evidence_ids":[],"strategy":"retain",
             "alternatives":["move"],"tradeoff":"content width","next_trigger":"new header",
             "validation":{"status":"unverified","evidence_ids":[],"version":"v1","note":"waiting"}}]}
        with patch.object(sys, "stdin", io.StringIO(json.dumps(env))):
            harness.commit(NS(root=str(self.root), input="-"))
        c=self.command("open",self.opening(concern_id="C"))
        basis=c["brief"]["basis"]["concern_context"]
        self.assertEqual(basis["tradeoff"],"content width")
        self.assertEqual(basis["goals"][0]["id"],"goal-primary")
        self.assertEqual(basis["validation"]["status"],"unverified")
        unrelated = {k:v for k,v in env.items() if k!="concerns"}
        unrelated.update(expected_revision=1,request_id="other")
        with patch.object(sys, "stdin", io.StringIO(json.dumps(unrelated))):
            harness.commit(NS(root=str(self.root),input="-"))
        self.assertFalse(engine.get_context(NS(root=str(self.root),case_id="card"))["stale_concern"])
        env.update(request_id="changed",expected_revision=2)
        env["concerns"][0]["strategy"]="Replace header"
        with patch.object(sys, "stdin", io.StringIO(json.dumps(env))):
            harness.commit(NS(root=str(self.root),input="-"))
        self.check_error("stale_concern",self.advance,c,self.verifier())
        self.assertTrue(engine.get_context(NS(root=str(self.root),case_id="card"))["stale_concern"])

    def test_stale_files_supersede_keeps_history_suppresses_routing(self):
        c=self.command("open",self.opening(signals=["tradeoff"]))
        c=self.advance(c,self.strategist())
        (self.root/"src/header.txt").write_text("changed")
        self.check_error("stale_snapshot",self.advance,c,self.critic())
        fresh=self.command("open",self.opening(case_id="new",supersedes="card"))
        self.assertEqual(fresh["supersedes"],"card")
        old=engine.get_context(NS(root=str(self.root),case_id="card"))
        self.assertEqual(old["phase"],"superseded")
        self.assertTrue(old["stale_snapshot"])
        self.assertEqual(old["history"][0]["role"],"strategist")
        self.assertIsNone(old["next_role"])
        self.assertEqual(engine.summary_if_enabled(self.root)["cases"][0]["case_id"],"new")

    def test_cannot_waive_or_silently_replace_evidence(self):
        c=self.command("open",self.opening(route="tradeoff"))
        c=self.advance(c,self.strategist())
        c=self.advance(c,self.critic())
        for ref in ("missing.txt", ".env.local"):
            self.check_error("unsafe_evidence",self.advance,c,self.verifier(evidence_refs=[ref]))
        (self.root/"link").symlink_to(self.base)
        self.check_error("unsafe_evidence",self.advance,c,self.verifier(evidence_refs=["link/root/proof.txt"]))
        c=self.advance(c,self.verifier())
        (self.root/"proof.txt").write_text("mutated evidence")
        self.check_error("stale_evidence",self.advance,c,self.judge("keep"))
        self.assertEqual(engine.get_context(NS(root=str(self.root),case_id="card"))["revision"],3)

    def test_defer_persists_resume_requires_new_observation_and_refutation_can_withdraw(self):
        c=self.command("open",self.opening(claim_type="behavior"))
        c=self.advance(c,self.strategist())
        c=self.advance(c,self.critic())
        unknown=self.verifier("inconclusive",provenance="simulation",method="artifact-check")
        c=self.advance(c,unknown)
        self.check_error("invalid_role_output",self.advance,c,self.judge("keep"))
        c=self.advance(c,self.judge("defer"))
        self.assertEqual(c["phase"],"waiting_evidence")
        payload=dict(case_id="card",binding=c["binding"],expected_revision=c["revision"],
                     request_id="resume-1",reason="A new controlled trace is available.")
        c=self.command("resume",payload)
        self.assertTrue(self.command("resume",payload)["duplicate"])
        self.assertEqual(c["next_role"],"verifier")
        v=self.verifier("refutes",method="human-task",task="Bookmark a story",
                        participant_scope="Scripted fixture; no human participants.")
        c=self.advance(c,v)
        c=self.advance(c,self.judge("withdraw"))
        self.assertEqual(c["phase"],"decided")
        summary = engine.summary_if_enabled(self.root)["cases"][0]
        self.assertEqual(summary["outcome"], "withdraw")
        self.assertEqual(summary["next_trigger"], "New header or observation")
        successor = self.command("open",self.opening(case_id="next",supersedes="card",claim_type="behavior"))
        prior = successor["brief"]["basis"]["predecessor_handoff"]
        self.assertTrue(prior["historical_only"])
        self.assertEqual(prior["last_judgment"]["outcome"],"withdraw")
        self.assertEqual(prior["proposal"]["assumption"],"Header is quiet")
        self.assertFalse(successor["history"])
        self.assertEqual([s["role"] for s in c["history"]],["strategist","critic","verifier","judge","resume","verifier","judge"])

    def test_empty_watch_and_invalid_successor_do_not_opt_in(self):
        self.check_error("unknown_case", self.command,"open", self.opening(supersedes="absent"))
        (self.root/"src/header.txt").unlink()
        self.check_error("empty_watch",self.command,"open", self.opening())
        self.assertFalse(engine.summary_if_enabled(self.root)["enabled"])

    def test_concurrent_creator_and_submitters_share_one_receipt(self):
        cmd = [sys.executable,str(SCRIPTS/"engine.py")]
        def op(action,payload):
            proc = subprocess.run(cmd+[action,"--root",str(self.root)],input=json.dumps(payload),
                                  capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            return json.loads(proc.stdout)
        with ThreadPoolExecutor(max_workers=4) as executor:
            opens = list(executor.map(lambda _: op("open",self.opening(signals=None)),range(4)))
            self.assertEqual(sum(not o["duplicate"] for o in opens),1)
            self.assertEqual(len(set(o["binding"] for o in opens)),1)
            body=dict(case_id="card",binding=opens[0]["binding"],expected_revision=0,
                      request_id="concurrent",role="verifier",output=self.verifier())
            submits = list(executor.map(lambda _:op("submit",body),range(4)))
        self.assertEqual(sum(not s["duplicate"] for s in submits),1)
        self.assertTrue(all(len(s["history"])==1 for s in submits))

    def test_database_copied_from_another_root_refused_on_context(self):
        self.command("open", self.opening())
        other=self.project("another")
        shutil.copyfile(self.root/".experience-strategy/engine.sqlite3",other/".experience-strategy/engine.sqlite3")
        self.check_error("wrong_root",engine.summary_if_enabled,other)


if __name__ == "__main__":
    unittest.main()
