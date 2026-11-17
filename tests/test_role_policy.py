import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import role_policy as policy


def case(route="tradeoff", claim_type="behavior", mode="project"):
    return dict(route=route, claim_type=claim_type, mode=mode, history=[])


def record(c, role, out):
    policy.validate_output(c, role, out)
    c["history"].append({"role": role, "output": out})


STRATEGY = dict(intent="Preserve quiet scanning", options=["Hide tools until focus", "Show all controls"],
                proposal="Keep tools available on focus", assumption="The relevant action is discoverable",
                reopen_if="New readers need help to save.")
CRITIC = dict(objection="Keyboard users might miss the action", consequence="They cannot save from the list",
              check="Try the no-hints save task", reason="The proposal assumes focus reveals it in the user's path.")
HUMAN = dict(method="human-task", provenance="human", finding="supports", evidence_refs=["research/anon.md"],
             observation="The participant completed the task without a hint.", scope="This task and participant only",
             limitations="Cannot estimate retention", task="Save a story for later", participant_scope="One consenting first-time reader")
ARTIFACT = dict(method="artifact-check", provenance="artifact", finding="supports", evidence_refs=["after.png"],
                observation="Heart is absent from header", scope="Current 480px view", limitations="Other viewports not checked")
MISSING = dict(method="human-task", provenance="none", finding="unavailable", evidence_refs=[],
               observation="No session scheduled", scope="First use", limitations="No behavior evidence")
JUDGE = dict(outcome="keep", rationale="Observed task completed", critic_response="Focus path worked in this session",
             tradeoff="Prioritize quiet scanning; don't generalize", next_trigger="Reopen on an observed failure")


def after_critic(**kwargs):
    c = case(**kwargs)
    record(c, "strategist", copy.deepcopy(STRATEGY))
    record(c, "critic", copy.deepcopy(CRITIC))
    return c


class RolePolicyTests(unittest.TestCase):
    def test_route_chooses_smallest_sufficient_review(self):
        self.assertEqual(policy.choose_route("artifact"), "direct")
        self.assertEqual(policy.choose_route("artifact", requested="tradeoff"), "tradeoff")
        self.assertEqual(policy.choose_route("behavior"), "tradeoff")
        for signal in ["tradeoff", "counterevidence", "high-rework"]:
            self.assertEqual(policy.choose_route("artifact", [signal]), "tradeoff")
            with self.assertRaises(ValueError):
                policy.choose_route("artifact", [signal], "direct")
        for args in [("behavior", [], "direct"), ("other", None, None),
                     ("artifact", "tradeoff", None), ("artifact", ["not-real"], None),
                     ("artifact", ["tradeoff", "tradeoff"], None)]:
            with self.assertRaises(ValueError):
                policy.choose_route(*args)

    def test_explicit_task_stages_route_by_intent(self):
        for kind in ("artifact", "behavior"):
            self.assertEqual(policy.choose_route(kind, ["tradeoff"], task_stage="create"), "creation")
        self.assertEqual(policy.choose_route("artifact", ["tradeoff"], task_stage="artifact_check"), "direct")
        self.assertEqual(policy.choose_route("behavior", task_stage="user_validation"), "tradeoff")
        for stage, kind, route in [("artifact_check", "behavior", None), ("user_validation", "artifact", None),
                                   ("create", "behavior", "tradeoff"), ("unknown", "artifact", None)]:
            with self.assertRaises(ValueError):
                policy.choose_route(kind, requested=route, task_stage=stage)

    def test_creation_has_its_own_critic_and_resumes_rework_at_execution(self):
        c = dict(case("creation"), task_stage="create")
        self.assertEqual(policy.role_brief(c)["contract"], policy.role_card("critic", "create"))
        self.assertNotEqual(policy.role_card("critic", "create"), policy.role_card("critic"))
        record(c, "critic", {"change": "Show star", "tradeoff": "More chrome", "acceptance": "Click toggles star"})
        with self.assertRaises(ValueError):
            record(c, "execution", {"work_item": "Implement later"})
        made = dict(change="Added button", candidate_refs=["candidates/abc/v1.html"], review_steps="Click it")
        record(c, "execution", made)
        check = dict(outcome="rework", checks=[dict(check="click", result="fail", observation="No change")],
                     evidence_refs=["evidence/log.txt"], limitations="No human participants")
        with self.assertRaises(ValueError):
            record(c, "measurement", dict(check, outcome="ready"))
        record(c, "measurement", check)
        record(c, "execution", dict(made, candidate_refs=["candidates/abc/v2.html"]))
        check["checks"] = [dict(check="click", result="pass", observation="aria-pressed changed")]
        record(c, "measurement", dict(check, outcome="ready"))
        self.assertEqual(policy.phase(c), "candidate_ready")
        self.assertIsNone(policy.next_role(c))

    def test_only_explicit_validation_activates_user_evidence(self):
        c = case()
        c["task_stage"] = "user_validation"
        record(c, "strategist", STRATEGY)
        record(c, "critic", CRITIC)
        self.assertEqual(policy.next_role(c), "user_evidence")
        with self.assertRaises(ValueError):
            record(c, "user_evidence", ARTIFACT)
        record(c, "user_evidence", MISSING)
        record(c, "judge", dict(JUDGE, outcome="defer"))
        c["history"].append({"role": "resume", "output": {"reason": "One authorized task observation"}})
        self.assertEqual(policy.next_role(c), "user_evidence")
        record(c, "user_evidence", HUMAN)
        record(c, "judge", JUDGE)
        self.assertEqual(policy.phase(c), "decided")

    def test_direct_assertion_does_not_run_critics_or_decide_a_design(self):
        for finding, status in [("supports", "verified"), ("refutes", "needs_owner"),
                                ("inconclusive", "waiting_evidence")]:
            c = case("direct", "artifact")
            self.assertEqual(policy.next_role(c), "verifier")
            record(c, "verifier", dict(ARTIFACT, finding=finding))
            self.assertEqual(policy.phase(c), status)
            self.assertIsNone(policy.next_role(c))
            self.assertIsNone(policy.role_brief(c)["template"])

    def test_role_order_and_no_material_objection(self):
        c = case()
        with self.assertRaises(ValueError):
            record(c, "judge", JUDGE)
        record(c, "strategist", STRATEGY)
        with self.assertRaises(ValueError):
            record(c, "critic", dict(CRITIC, objection=None))
        record(c, "critic", dict(CRITIC, objection=None, consequence=None,
                                 reason="No material counterexample beyond planned checks."))
        self.assertEqual(policy.next_role(c), "verifier")

    def test_keep_revise_or_withdraw_based_on_scoped_observations(self):
        for finding, outcome in [("supports", "keep"), ("refutes", "revise"), ("refutes", "withdraw")]:
            c = after_critic()
            record(c, "verifier", dict(HUMAN, finding=finding))
            if finding == "refutes":
                with self.assertRaises(ValueError):
                    record(c, "judge", JUDGE)
            record(c, "judge", dict(JUDGE, outcome=outcome))
            self.assertEqual(policy.phase(c), "decided")

    def test_screenshot_cannot_attest_first_time_discoverability(self):
        c = after_critic()
        with self.assertRaises(ValueError):
            record(c, "verifier", ARTIFACT)
        record(c, "verifier", dict(ARTIFACT, finding="inconclusive"))
        self.assertEqual(policy.role_brief(c)["values"]["outcome"], ["defer", "escalate"])
        for outcome in ("keep", "withdraw", "revise"):
            with self.assertRaises(ValueError):
                record(c, "judge", dict(JUDGE, outcome=outcome))
        record(c, "judge", dict(JUDGE, outcome="defer"))
        self.assertEqual(policy.phase(c), "waiting_evidence")
        self.assertIsNone(policy.next_role(c))
        c["history"].append({"role": "resume", "output": {"reason": "New consented session"}})
        self.assertEqual(policy.next_role(c), "verifier")
        record(c, "verifier", HUMAN)
        record(c, "judge", JUDGE)
        self.assertEqual(policy.phase(c), "decided")

    def test_missing_evidence_and_handoff_to_owner(self):
        c = after_critic()
        record(c, "verifier", MISSING)
        record(c, "judge", dict(JUDGE, outcome="escalate"))
        self.assertEqual(policy.phase(c), "needs_owner")

    def test_synthetic_observation_never_completes_real_case(self):
        v = dict(HUMAN, provenance="simulation")
        with self.assertRaises(ValueError):
            record(after_critic(), "verifier", v)
        c = after_critic(mode="fixture")
        record(c, "verifier", v)
        self.assertIn("模拟", policy.role_brief(c)["instructions"])

    def test_requires_scope_and_task_on_conclusive_human_observation(self):
        for field in ("scope", "task", "participant_scope", "limitations"):
            v = dict(HUMAN)
            v.pop(field)
            with self.assertRaises(ValueError):
                record(after_critic(), "verifier", v)

    def test_ref_requires_safe_local_path_and_declared_source(self):
        for refs in [[], ["https://x.local/note"], ["/other/file"], ["sub/../doc"], ["x", "x"], ["a\\b"], ["C:/x"]]:
            with self.assertRaises(ValueError):
                record(after_critic(), "verifier", dict(HUMAN, evidence_refs=refs))
        with self.assertRaises(ValueError):
            record(after_critic(), "verifier", dict(MISSING, evidence_refs=["note"]))

    def test_briefs_are_isolated_templates_not_acceptances(self):
        c = case()
        brief = policy.role_brief(c)
        with self.assertRaises(ValueError):
            record(c, "strategist", brief["template"])
        brief["contract"]["authority"] = "I can deploy"
        self.assertNotIn("deploy", policy.role_brief(c)["contract"]["authority"])
        with self.assertRaises(ValueError):
            record(c, "strategist", dict(STRATEGY, judgement="approved"))
        with self.assertRaises(ValueError):
            record(c, "strategist", dict(STRATEGY, options=["Keep", " KEEP "]))


if __name__ == "__main__":
    unittest.main()
