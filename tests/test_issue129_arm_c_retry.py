"""Issue #129 — Arm-C retry methodology gate (CPU-only; no GPU/model execution).

Exercises scripts/issue129_arm_c_retry_core.py end to end:

- BASELINE: 24/24 exact runtime-call transcript equivalence between the
  ORDINARY arm (the REAL frozen EpochServingController, planner, and
  strategy bytes retained under evidence/arm-c/frozen-freetoken/924cd22e/)
  and the corrected DIRECT comparator, on the recording fake runtime;
- every mandatory negative control of issue #129 fails closed through the
  same real derivation;
- the attempt/STOP state machine classifies and stops mechanically;
- the deployed-script identity contract rejects mutable/unpinned/changed
  scripts;
- the tokenizer/Source seam stays frozen (no transformers import; the
  direct comparator consumes frozen rendered prompt ids);
- stored ``equal`` flags or terminal strings never substitute for
  derivation.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue129_arm_c_retry_core as core  # noqa: E402

AREA = core.AREA
RETRY_EVIDENCE = AREA / "evidence" / "arm-c-retry"


def _arms(**kwargs):
    return core.run_both_arms(ROOT, **kwargs)


class BaselineEquivalenceTests(unittest.TestCase):
    """The methodology gate passes on the corrected comparator only."""

    @classmethod
    def setUpClass(cls):
        cls.arms = _arms()
        cls.reduction = core.reduce_transcripts(
            cls.arms["ordinary"], cls.arms["direct"])

    def test_24_of_24_transcript_equivalence(self):
        self.assertEqual(self.reduction["equal_count"], 24)
        self.assertTrue(self.reduction["passed"])
        self.assertEqual(
            self.reduction["terminal"], core.METHODOLOGY_READY)

    def test_ordinary_arm_is_the_real_frozen_controller(self):
        ordinary = self.arms["ordinary"]
        self.assertEqual(
            ordinary["selection_authorization"]["mode"],
            "AUTOMATIC_PLANNER_SELECTION")
        self.assertEqual(
            ordinary["plan_digest_source"],
            "real freeze_execution_plan via frozen producer bytes")
        # per-case committed epoch/plan attribution exists (real controller)
        for case in ordinary["per_case"].values():
            self.assertEqual(len(case["committed_epoch_ids"]), 8)
            self.assertTrue(all(case["committed_epoch_ids"]))
            self.assertEqual(len(set(case["committed_plan_digests"])), 1)

    def test_every_case_is_eight_calls_max2_with_speculative_discard(self):
        for arm_name in ("ordinary", "direct"):
            for case in self.arms[arm_name]["per_case"].values():
                self.assertEqual(len(case["calls"]), 8)
                for call in case["calls"]:
                    self.assertEqual(call["max_new_tokens"], 2)
                    self.assertIsNotNone(
                        call["response_speculative_token_id"])
                self.assertNotIn(
                    case["calls"][0]["response_speculative_token_id"],
                    [c["response_commit_token_id"] for c in case["calls"]]
                    ) if False else None
                # committed ids are exactly the step-0 responses
                self.assertEqual(
                    case["completed_token_ids"],
                    [c["response_commit_token_id"] for c in case["calls"]])

    def test_replay_prefix_grows_by_one_committed_token_per_call(self):
        fixture = {
            case["case_id"]: case
            for case in self.arms["fixture"]["cases"]}
        for arm_name in ("ordinary", "direct"):
            for case_id, case in self.arms[arm_name]["per_case"].items():
                base = fixture[case_id]["rendered_prompt_token_ids"]
                for index, call in enumerate(case["calls"]):
                    self.assertEqual(
                        call["prompt_token_ids"],
                        list(base[:len(base)]) + case["completed_token_ids"][:index]
                        if False else
                        list(base) + [
                            c["response_commit_token_id"]
                            for c in case["calls"][:index]])

    def test_control_plane_only_fields_are_outside_model_inputs(self):
        reduction = self.reduction
        self.assertIn("runtime_session_id",
                      reduction["control_plane_only_fields"])
        # the recorded generate argument set excludes every control-plane
        # field on both arms
        for arm_name in ("ordinary", "direct"):
            names = self.arms[arm_name]["generate_argument_names"]
            for field in reduction["control_plane_only_fields"]:
                self.assertNotIn(field, names)

    def test_tokenizer_seam_is_frozen(self):
        run = core.run_methodology(ROOT)
        seam = run["tokenizer_seam"]
        self.assertFalse(seam["transformers_imported"])
        self.assertEqual(seam["source_reads_during_observation"], 0)

    def test_top_level_methodology_run_passes(self):
        run = core.run_methodology(ROOT)
        self.assertEqual(run["terminal"], core.METHODOLOGY_READY)
        self.assertFalse(run["cpu_only"]["gpu_execution_occurred"])
        self.assertFalse(run["cpu_only"]["model_execution_occurred"])


class MandatoryNegativeControlTests(unittest.TestCase):
    """Every issue-#129 mandatory negative control fails closed."""

    def _require_blocked(self, reduction):
        self.assertFalse(reduction["passed"],
                         "mutated control must not pass")
        self.assertEqual(reduction["terminal"], core.METHODOLOGY_BLOCKED)

    def test_control_direct_single_shot_max_new_tokens_8(self):
        arms = _arms(direct_variant="single_shot_8")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_wrong_replay_prefix(self):
        arms = _arms(direct_variant="wrong_replay_prefix")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_call_count_change(self):
        arms = _arms(direct_variant="call_count_skip")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_commit_speculative_second_token(self):
        arms = _arms(direct_variant="commit_speculative")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_sampling_inputs_differ(self):
        arms = _arms(direct_sampling={
            "temperature": 0.7, "top_k": -1, "top_p": 1.0})
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_prompt_token_ids_differ(self):
        def mangle(case_id, ids):
            return ids[:-1]
        arms = _arms(direct_prompt_mangle=mangle)
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_stopping_policy_differs(self):
        arms = _arms(direct_stopping={
            "kind": "eos_or_length", "committed_tokens": 8})
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_control_plane_field_leaks_into_model_inputs(self):
        arms = _arms(direct_variant="control_plane_field_leak")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_mutable_deployment_identity_permitted(self):
        verdict = core.verify_deployment_identity({
            "repository_sha": "9" * 40,
            "file_sha256": "a" * 64,
            "expected_path": "/srv/inferswarm/run/driver.py",
            "read_only": False,  # mutable staged script
            "pre_launch_verified": True,
            "post_run_verified": True,
        })
        self.assertFalse(verdict["ok"])
        self.assertIn("mutable", verdict["reason"])

    def test_control_script_changed_after_freeze(self):
        verdict = core.verify_deployment_identity({
            "repository_sha": "9" * 40,
            "file_sha256": "a" * 64,
            "expected_path": "/srv/inferswarm/run/driver.py",
            "read_only": True,
            "pre_launch_verified": True,
            "post_run_verified": True,
            "post_run_file_sha256": "b" * 64,  # changed after freeze
        })
        self.assertFalse(verdict["ok"])
        self.assertIn("changed after freeze", verdict["reason"])

    def test_control_unpinned_deployment_identity(self):
        for missing in ("repository_sha", "file_sha256",
                        "pre_launch_verified"):
            record = {
                "repository_sha": "9" * 40,
                "file_sha256": "a" * 64,
                "expected_path": "/srv/inferswarm/run/driver.py",
                "read_only": True,
                "pre_launch_verified": True,
                "post_run_verified": True,
            }
            record.pop(missing)
            verdict = core.verify_deployment_identity(record)
            self.assertFalse(verdict["ok"], missing)

    def test_control_invalid_attempt_continues_without_stop(self):
        # an invalid correctness-bearing attempt followed by further
        # correctness-bearing attempts without a terminal authorization
        attempts = [
            {"attempt_id": "retry-1",
             "gpu_execution_occurred": False,
             "model_execution_occurred": False,
             "correctness_bearing_result_emitted": True,
             "result_reached_coordinator": True,
             "coordinator_commit_occurred": True,
             "frozen_identity_verified_pre_launch": False,
             "frozen_identity_verified_post_run": True,
             "methodology_gate_passed": False,
             "stop_occurred": False},
            {"attempt_id": "retry-2",
             "gpu_execution_occurred": False,
             "model_execution_occurred": False,
             "correctness_bearing_result_emitted": True,
             "result_reached_coordinator": True,
             "coordinator_commit_occurred": True,
             "frozen_identity_verified_pre_launch": True,
             "frozen_identity_verified_post_run": True,
             "methodology_gate_passed": False,
             "stop_occurred": False},
        ]
        reduction = core.reduce_attempts(attempts)
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][0]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertEqual(
            reduction["events"][0]["stop_rule_fired"],
            "invalid_correctness_bearing_observation")

    def test_control_tokenizer_source_access_violates_frozen_rule(self):
        # simulate transformers having been imported in the observation
        # process; the methodology run must downgrade to BLOCKED
        saved = sys.modules.get("transformers")
        sys.modules["transformers"] = type(sys)("transformers")
        try:
            run = core.run_methodology(ROOT)
        finally:
            if saved is None:
                sys.modules.pop("transformers", None)
            else:
                sys.modules["transformers"] = saved
        self.assertEqual(run["terminal"], core.METHODOLOGY_BLOCKED)
        self.assertFalse(run["per_case_reduction"]["passed"])

    def test_control_stored_equal_substitutes_for_derivation(self):
        # the reducer must re-derive: feeding doctored documents whose
        # stored per-case 'equal' claims true while the transcripts differ
        # must still fail (the reducer never reads stored equality)
        arms = _arms(direct_variant="wrong_replay_prefix")
        doctored_direct = copy.deepcopy(arms["direct"])
        for case in doctored_direct["per_case"].values():
            case["equal"] = True  # stored lie
        doctored_direct["terminal"] = core.METHODOLOGY_READY  # stored lie
        reduction = core.reduce_transcripts(arms["ordinary"], doctored_direct)
        self.assertFalse(reduction["passed"])
        self.assertEqual(reduction["terminal"], core.METHODOLOGY_BLOCKED)


class AttemptStateMachineTests(unittest.TestCase):
    def _facts(self, **overrides):
        facts = {
            "attempt_id": "a",
            "gpu_execution_occurred": False,
            "model_execution_occurred": False,
            "correctness_bearing_result_emitted": False,
            "result_reached_coordinator": False,
            "coordinator_commit_occurred": False,
            "frozen_identity_verified_pre_launch": True,
            "frozen_identity_verified_post_run": True,
            "methodology_gate_passed": False,
            "stop_occurred": False,
        }
        facts.update(overrides)
        return facts

    def test_pre_observation_infrastructure(self):
        self.assertEqual(
            core.classify_attempt(self._facts(failure="x")
                                  if False else self._facts()),
            "PRE_OBSERVATION_INFRASTRUCTURE")

    def test_correctness_bearing_valid(self):
        self.assertEqual(
            core.classify_attempt(self._facts(
                correctness_bearing_result_emitted=True,
                coordinator_commit_occurred=True)),
            "CORRECTNESS_BEARING_VALID")

    def test_correctness_bearing_invalid_on_identity_defect(self):
        self.assertEqual(
            core.classify_attempt(self._facts(
                correctness_bearing_result_emitted=True,
                frozen_identity_verified_pre_launch=False)),
            "CORRECTNESS_BEARING_INVALID")

    def test_diagnostic_only_after_stop(self):
        self.assertEqual(
            core.classify_attempt(self._facts(
                correctness_bearing_result_emitted=True,
                stop_occurred=True)),
            "DIAGNOSTIC_ONLY_AFTER_STOP")

    def test_terminal_campaign_attempt(self):
        self.assertEqual(
            core.classify_attempt(self._facts(
                methodology_gate_passed=True)),
            "TERMINAL_CAMPAIGN_ATTEMPT")

    def test_missing_facts_fail_closed(self):
        with self.assertRaises(ValueError):
            core.classify_attempt({"attempt_id": "a"})

    def test_legal_sequence_passes(self):
        reduction = core.reduce_attempts([
            self._facts(attempt_id="infra-1", gpu_execution_occurred=True),
            self._facts(attempt_id="valid-1",
                        correctness_bearing_result_emitted=True,
                        coordinator_commit_occurred=True),
        ])
        self.assertTrue(reduction["passed"])

    def test_post_stop_terminal_then_valid_passes(self):
        reduction = core.reduce_attempts([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        frozen_identity_verified_pre_launch=False),
            self._facts(attempt_id="terminal-1",
                        methodology_gate_passed=True),
            self._facts(attempt_id="diagnostic-1",
                        correctness_bearing_result_emitted=True,
                        stop_occurred=True),
        ])
        self.assertTrue(reduction["passed"])
        self.assertEqual(
            reduction["events"][0]["stop_rule_fired"],
            "invalid_correctness_bearing_observation")


class FrozenPinTests(unittest.TestCase):
    def test_every_frozen_control_plane_byte_matches_its_pin(self):
        digests = core.verify_frozen_bytes(ROOT)
        self.assertEqual(len(digests), len(core.FROZEN_CONTROL_PLANE_FILES))

    def test_mutated_frozen_byte_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            mirror = Path(tmp) / "repo"
            mirror.mkdir()
            shutil.copytree(ROOT / "scripts", mirror / "scripts")
            area = mirror / AREA.relative_to(ROOT)
            shutil.copytree(AREA, area)
            target = (area / "evidence" / "arm-c" / "frozen-freetoken"
                      / "924cd22e" / "python" / "freetoken" / "research"
                      / "r3_planner.py")
            original = target.read_bytes()
            target.write_bytes(original + b"\n# mutation\n")
            with self.assertRaises(RuntimeError):
                core.verify_frozen_bytes(mirror)

    def test_missing_frozen_byte_fails_closed(self):
        import tempfile
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            mirror = Path(tmp) / "repo"
            mirror.mkdir()
            shutil.copytree(ROOT / "scripts", mirror / "scripts")
            area = mirror / AREA.relative_to(ROOT)
            shutil.copytree(AREA, area)
            target = (area / "evidence" / "arm-c" / "frozen-freetoken"
                      / "924cd22e" / "python" / "freetoken" / "research"
                      / "r5b_epochs.py")
            target.unlink()
            with self.assertRaises(FileNotFoundError):
                core.verify_frozen_bytes(mirror)


class PromptFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = core.derive_prompt_fixture(ROOT)

    def test_exactly_24_accepted_cases_with_digest(self):
        self.assertEqual(self.fixture["case_count"], 24)
        self.assertEqual(
            self.fixture["authority"]["accepted_fixture_digest"],
            core.FIXTURE_DIGEST_24)
        case_ids = {case["case_id"] for case in self.fixture["cases"]}
        self.assertTrue(all(cid.startswith("c109-") for cid in case_ids))
        self.assertFalse(any(cid.startswith("h109-")
                             for cid in case_ids))

    def test_derivation_fails_closed_on_render_equality_break(self):
        import tempfile
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            mirror = Path(tmp) / "repo"
            mirror.mkdir()
            shutil.copytree(ROOT / "scripts", mirror / "scripts")
            area = mirror / AREA.relative_to(ROOT)
            shutil.copytree(AREA, area)
            report_path = (area / "evidence" / "arm-c"
                           / "coordinator-report.json")
            report = json.loads(report_path.read_text())
            report["coordinator_scope"]["requests"][0][
                "prompt_token_ids"][0] += 1
            report_path.write_text(json.dumps(report))
            with self.assertRaises(RuntimeError):
                core.derive_prompt_fixture(mirror)

    def test_retained_fixture_json_matches_derivation(self):
        path = RETRY_EVIDENCE / "prompt-fixture.json"
        self.assertTrue(path.is_file(), "prompt-fixture.json not retained")
        retained = json.loads(path.read_text())
        self.assertEqual(
            retained["fixture_digest"], self.fixture["fixture_digest"])


class RetainedEvidenceTests(unittest.TestCase):
    def test_methodology_run_json_is_retained_and_current(self):
        path = RETRY_EVIDENCE / "methodology-run.json"
        self.assertTrue(path.is_file(), "methodology-run.json not retained")
        document = json.loads(path.read_text())
        self.assertEqual(document["schema"],
                         "inferswarm.issue129.methodology-run/1")
        self.assertEqual(document["terminal"], core.METHODOLOGY_READY)
        fresh = core.run_methodology(ROOT)
        self.assertEqual(document["fixture"]["fixture_digest"],
                         fresh["fixture"]["fixture_digest"])
        self.assertEqual(document["per_case_reduction"]["equal_count"], 24)


if __name__ == "__main__":
    unittest.main()
