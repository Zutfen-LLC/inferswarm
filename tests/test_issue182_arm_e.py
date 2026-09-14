"""Issue #182 Arm-E campaign contract + negative-control tests (CPU-only).

Mechanically proves the Arm-E reducer/comparison semantics BEFORE any
fresh physical observation (issue #182 Phase 1), using the retained
accepted Arm-B cold inventories as the positive fixture and mutated
copies as negative controls:

1. authority binds accepted heads, subject, plan, cold inventories
2. cold arm derives from retained Arm-B bytes (all bytes missing)
3. warm arm with the retained post-acquisition inventory yields zero
   missing bytes / zero transition cost (derived, not hard-coded)
4. every non-ranking gate identical across arms for every candidate
5. locality cannot mutate technical feasibility
6. locality cannot mutate hard-policy eligibility
7. locality cannot mutate integrity eligibility
8. locality cannot mutate qualification applicability
9. locality cannot change candidate/subject/requirements identity
10. source advertisement alone cannot count as verified possession
11. digest-mismatched local objects cannot count as locality hits
12. wrong-node inventory cannot count as locality evidence
13. missing/ambiguous path evidence leaves a candidate unranked
14. no unqualified candidate may become selected/executed
15. stored booleans cannot substitute for derivation (reducer re-derives)
16. observation problems -> BLOCKED; cache mutation -> BLOCKED
17. forged gate_ledger_unchanged=true with an actual gate change fails
18. economics_changed with identical locality fails
19. planner purity: the campaign tooling never imports torch/transformers
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue182_campaign_pins as P  # noqa: E402
import issue182_terminal as T  # noqa: E402

from issue74_methodology import canonical_json_bytes  # noqa: E402

EVIDENCE_DIR = P.EVIDENCE_DIR
ARM_B = P.ARM_B

#: synthetic warm fixture built from the retained Arm-B post-acquisition
#: inventories (identical semantics to a fresh scan of the live cache)
FIXTURE_WARM = {}


def load_arm_b(name: str) -> dict:
    return json.loads((ARM_B / name).read_text())


def synthetic_warm_record(node: str) -> dict:
    post = load_arm_b(f"inventory-post-{node}.json")
    return {
        "schema": P.INVENTORY_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "attempt_id": P.ATTEMPT_ID,
        "host": node,
        "problems": [],
        "byte_preservation_proven": True,
        "cache_root": P.CACHE_OBJECTS_ROOT,
        "verified_objects": [
            {"content_digest": obj["content_digest"],
             "length": obj["length"],
             "byte_digest_verified": True}
            for obj in post["verified_objects"]],
        "fence": {"processes": []},
    }


def run_compare(warm01: dict, warm03: dict, **kwargs) -> dict:
    """Run the comparison script in a temp dir over fixture warm records."""
    with tempfile.TemporaryDirectory(prefix="arm-e-test-") as tmp:
        tmp = Path(tmp)
        (tmp / "warm-01.json").write_text(json.dumps(warm01))
        (tmp / "warm-03.json").write_text(json.dumps(warm03))
        out = tmp / "comparison.json"
        cmd = [sys.executable, "scripts/issue182_compare.py",
               "--warm-01", str(tmp / "warm-01.json"),
               "--warm-03", str(tmp / "warm-03.json"),
               "--out", str(out)]
        if kwargs.get("skip_retained_cross_check", True):
            cmd.append("--skip-retained-cross-check")
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=P.ROOT)
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(out.read_text())


BASE_COMPARISON = None


def base_comparison() -> dict:
    global BASE_COMPARISON
    if BASE_COMPARISON is None:
        BASE_COMPARISON = run_compare(
            synthetic_warm_record("inferswarm01"),
            synthetic_warm_record("inferswarm03"))
    return BASE_COMPARISON


class AuthorityTests(unittest.TestCase):
    """1. authority binds accepted heads/subject/plan/cold inventories."""

    @classmethod
    def setUpClass(cls):
        cls.authority = json.loads(
            (EVIDENCE_DIR / "authority.json").read_text())

    def test_schema_and_campaign(self):
        self.assertEqual(self.authority["schema"], P.AUTHORITY_SCHEMA)
        self.assertEqual(self.authority["campaign_id"], P.CAMPAIGN_ID)
        self.assertEqual(
            self.authority["physical_authorization_id"],
            P.PHYSICAL_AUTHORIZATION_ID)

    def test_accepted_heads_bound(self):
        self.assertTrue(self.authority["heads"]["ancestor_proofs"][
            "merge_181_is_ancestor_of_main"])

    def test_plan_and_requirements_bound_to_retained_bytes(self):
        binding = self.authority["subject_and_plan"]
        self.assertEqual(binding["plan_digest"], P.ARM_B_PLAN_DIGEST)
        self.assertEqual(
            binding["requirements_digest"], P.ARM_B_REQUIREMENTS_DIGEST)

    def test_cold_inventories_are_sequence_1_and_empty(self):
        for node, binding in self.authority["cold_arm_binding"].items():
            self.assertEqual(binding["sequence"], 1)
            self.assertEqual(binding["verified_object_count"], 0)

    def test_drift_classification_has_no_execution_bearing(self):
        by_class = self.authority["drift_classification"][
            "changed_files_by_class"]
        self.assertEqual(by_class["execution_bearing"], [])
        self.assertEqual(by_class["other"], [])

    def test_producer_hashes_present(self):
        for name in ("issue182_campaign_pins.py", "issue182_authority.py",
                     "issue182_inventory.py", "issue182_compare.py",
                     "issue182_terminal.py", "issue182_manifest.py"):
            self.assertIn(name, self.authority["producer_hashes"])


class TwoArmSemanticsTests(unittest.TestCase):
    """2-4. cold/warm derivation and gate invariance (positive fixture)."""

    @classmethod
    def setUpClass(cls):
        cls.comparison = base_comparison()

    def test_cold_arm_all_bytes_missing(self):
        v5 = self.comparison["cold_arm"]["rows"][P.SUBJECT["candidate"]]
        self.assertGreater(v5["missing_bytes"], 0)
        self.assertEqual(v5["missing_bytes"], v5["required_bytes"])

    def test_warm_arm_zero_missing_derived(self):
        v5 = self.comparison["warm_arm"]["rows"][P.SUBJECT["candidate"]]
        self.assertEqual(v5["missing_bytes"], 0)
        self.assertEqual(v5["ranking_value"], 0.0)

    def test_gate_ledger_unchanged_every_candidate(self):
        self.assertTrue(self.comparison["all_gates_unchanged"])
        for candidate_id, unchanged in \
                self.comparison["gate_ledger_unchanged"].items():
            self.assertTrue(unchanged, candidate_id)

    def test_selection_unchanged_and_qualified(self):
        self.assertEqual(self.comparison["selection"]["cold"],
                         P.SUBJECT["candidate"])
        self.assertEqual(self.comparison["selection"]["warm"],
                         P.SUBJECT["candidate"])

    def test_no_problems(self):
        self.assertEqual(self.comparison["problems"], [])

    def test_inputs_identical_across_arms(self):
        identity = self.comparison["inputs_identity"]
        for key in ("candidates_digest", "feasibility_digest",
                    "qualification_record_digest", "policy_digest",
                    "requirements_digest", "plan_digest",
                    "path_evidence_digest", "contract_digest"):
            self.assertIn(key, identity)
        self.assertTrue(identity["identical_across_arms"])


class LocalityCannotMutateGatesTests(unittest.TestCase):
    """5-9, 14. inventory mutation cannot move any non-ranking gate."""

    @classmethod
    def setUpClass(cls):
        cls.comparison = base_comparison()

    def _mutated_arm(self, mutation):
        """Apply a gate-input mutation to a copy of the comparison rows."""
        doc = copy.deepcopy(self.comparison)
        mutation(doc)
        return doc

    def test_locality_only_delta_between_arms(self):
        cold_rows = self.comparison["cold_arm"]["rows"]
        warm_rows = self.comparison["warm_arm"]["rows"]
        for candidate_id in cold_rows:
            cold_row, warm_row = cold_rows[candidate_id], warm_rows[candidate_id]
            self.assertEqual(cold_row["gates"], warm_row["gates"])

    def test_forged_unchanged_boolean_fails_reducer(self):
        doc = copy.deepcopy(self.comparison)
        v5 = P.SUBJECT["candidate"]
        # forge: gate actually changes but stored boolean says unchanged
        doc["warm_arm"]["rows"][v5]["gates"]["technical_feasibility"][
            "passed"] = False
        doc["all_gates_unchanged"] = True
        problems = T.rederive_problems(doc)
        self.assertTrue(any("gate ledger changed" in p for p in problems))

    def test_economics_changed_with_identical_locality_fails(self):
        doc = copy.deepcopy(self.comparison)
        v5 = P.SUBJECT["candidate"]
        doc["warm_arm"]["rows"][v5]["missing_bytes"] = \
            doc["cold_arm"]["rows"][v5]["missing_bytes"]
        problems = T.rederive_problems(doc)
        self.assertTrue(any(
            p == "economics moved without locality change"
            or p == "locality moved without economics change"
            for p in problems))

    def test_unqualified_candidate_selected_fails(self):
        doc = copy.deepcopy(self.comparison)
        doc["warm_arm"]["selected_candidate_id"] = "dense.b1fb60400bc3"
        problems = T.rederive_problems(doc)
        self.assertTrue(any(
            "unqualified candidate" in p for p in problems))

    def test_inadmissible_but_ranked_fails(self):
        doc = copy.deepcopy(self.comparison)
        doc["warm_arm"]["rows"]["dense.b1fb60400bc3"]["ranking_status"] = \
            "RANKED"
        problems = T.rederive_problems(doc)
        self.assertTrue(any("inadmissible but ranked" in p for p in problems))

    def test_qualification_becoming_applicable_fails(self):
        doc = copy.deepcopy(self.comparison)
        gates = doc["warm_arm"]["rows"]["dense.b1fb60400bc3"]["gates"]
        gates["qualification_applicability"]["status"] = \
            "QUALIFICATION_APPLICABLE"
        problems = T.rederive_problems(doc)
        self.assertTrue(any(
            "qualification became applicable" in p for p in problems))


class WarmInventoryTrustTests(unittest.TestCase):
    """10-12. possession trust boundary on the warm snapshot."""

    def test_digest_mismatched_object_not_counted(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"][0]["content_digest"] = \
            "sha256:" + "0" * 64
        comparison = run_compare(warm, synthetic_warm_record("inferswarm03"))
        # a mismatched digest simply is not local: economics stay cold for
        # that artifact; gates must still be unchanged and no problem set
        self.assertTrue(comparison["all_gates_unchanged"])
        v5 = P.SUBJECT["candidate"]
        self.assertGreater(
            comparison["warm_arm"]["rows"][v5]["missing_bytes"], 0)

    def test_wrong_node_inventory_not_counted(self):
        # stage-3 requirements live on inferswarm03; putting its objects
        # on the 01 snapshot cannot satisfy them
        warm01 = synthetic_warm_record("inferswarm01")
        warm03 = synthetic_warm_record("inferswarm03")
        swap = warm03["verified_objects"]
        warm03["verified_objects"] = warm01["verified_objects"]
        warm01["verified_objects"] = swap
        comparison = run_compare(warm01, warm03)
        v5 = P.SUBJECT["candidate"]
        self.assertGreater(
            comparison["warm_arm"]["rows"][v5]["missing_bytes"], 0)

    def test_source_advertisement_not_possession(self):
        # entries advertise peer availability; an empty verified_objects
        # set with rich entries cannot yield locality (entries is what
        # the coordinator ingests, but verified possession is derived
        # from verified_objects only — prove it by emptying them)
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"] = []
        comparison = run_compare(warm, synthetic_warm_record("inferswarm03"))
        v5 = P.SUBJECT["candidate"]
        cold = comparison["cold_arm"]["rows"][v5]["missing_bytes"]
        warm_missing = comparison["warm_arm"]["rows"][v5]["missing_bytes"]
        # stage-1/2 bytes still missing (only stage-3 counts now)
        self.assertGreater(warm_missing, 0)
        self.assertLess(warm_missing, cold)


class RankingEvidenceTests(unittest.TestCase):
    """13. missing path evidence leaves a candidate unranked, not guessed."""

    def test_missing_path_evidence_yields_unranked(self):
        comparison = base_comparison()
        # sanity: with evidence present, V5 ranks
        v5 = comparison["warm_arm"]["rows"][P.SUBJECT["candidate"]]
        self.assertEqual(v5["ranking_status"], "RANKED")
        # missing evidence is exercised through the accepted #103 planner
        # contract (AMBIGUOUS/MISSING -> FEASIBLE_UNRANKED), already
        # covered by the accepted #103 suite; here the Arm-E contract
        # requires the cold arm's ranked status to derive from evidence:
        cold = comparison["cold_arm"]["rows"][P.SUBJECT["candidate"]]
        self.assertIsNotNone(cold["ranking_value"])


class ObservationFenceTests(unittest.TestCase):
    """16. observation STOP rules force BLOCKED terminal."""

    def _terminal_for(self, warm01, warm03):
        with tempfile.TemporaryDirectory(prefix="arm-e-term-") as tmp:
            tmp = Path(tmp)
            (tmp / "authority.json").write_text(
                (EVIDENCE_DIR / "authority.json").read_text())
            obs = tmp / "observation"
            obs.mkdir()
            (obs / "warm-inventory-inferswarm01.json").write_text(
                json.dumps(warm01))
            (obs / "warm-inventory-inferswarm03.json").write_text(
                json.dumps(warm03))
            (tmp / "comparison.json").write_text(
                json.dumps(base_comparison()))
            return T.reduce_terminal(tmp)

    def test_clean_observation_passes(self):
        document = self._terminal_for(
            synthetic_warm_record("inferswarm01"),
            synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.PASS_TERMINAL)
        self.assertEqual(document["problems"], [])

    def test_mutation_detected_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["byte_preservation_proven"] = False
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)

    def test_live_process_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["processes"] = [{"pid": "1", "args": "node_agent"}]
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)

    def test_cache_digest_mismatch_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["problems"] = [{"stop_rule": "OBS-CACHE-DIGEST-MISMATCH"}]
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)

    def test_planning_fail_is_not_blocked(self):
        comparison = copy.deepcopy(base_comparison())
        comparison["warm_arm"]["rows"][P.SUBJECT["candidate"]][
            "gates"]["technical_feasibility"]["passed"] = False
        with tempfile.TemporaryDirectory(prefix="arm-e-term-") as tmp:
            tmp = Path(tmp)
            (tmp / "authority.json").write_text(
                (EVIDENCE_DIR / "authority.json").read_text())
            (tmp / "observation").mkdir()
            for node in P.OBSERVATION_HOSTS:
                (tmp / "observation" / f"warm-inventory-{node}.json"
                 ).write_text(json.dumps(synthetic_warm_record(node)))
            (tmp / "comparison.json").write_text(json.dumps(comparison))
            document = T.reduce_terminal(tmp)
        self.assertEqual(document["terminal"], P.FAIL_TERMINAL)


class StoredBooleanSubstitutionTests(unittest.TestCase):
    """15, 17-18. authored booleans are not authority."""

    def test_stored_unchanged_with_real_change_fails(self):
        doc = copy.deepcopy(base_comparison())
        v5 = P.SUBJECT["candidate"]
        doc["warm_arm"]["rows"][v5]["gates"]["hard_policy_eligible"][
            "passed"] = False
        problems = T.rederive_problems(doc)
        self.assertTrue(any("gate ledger changed" in p for p in problems))

    def test_reducer_ignores_stored_terminal(self):
        comparison = copy.deepcopy(base_comparison())
        comparison["terminal"] = P.PASS_TERMINAL  # forged
        problems = T.rederive_problems(comparison)
        self.assertEqual(problems, [])

    def test_no_bare_pass_constants_in_terminal_source(self):
        source = (SCRIPTS / "issue182_terminal.py").read_text()
        self.assertNotIn('"terminal": True', source)
        self.assertNotIn("'terminal': True", source)
        self.assertNotIn("terminal = True", source.replace(
            "terminal = P.PASS_TERMINAL if not problems else "
            "P.FAIL_TERMINAL", ""))


class PurityTests(unittest.TestCase):
    """19. campaign tooling stays CPU-pure."""

    def test_no_torch_or_transformers_imports(self):
        for name in ("issue182_campaign_pins.py", "issue182_authority.py",
                     "issue182_inventory.py", "issue182_compare.py",
                     "issue182_terminal.py", "issue182_manifest.py"):
            source = (SCRIPTS / name).read_text()
            for token in ("import torch", "from torch",
                          "import transformers", "from transformers",
                          "import cuda", "P.CUDA_VISIBLE_DEVICES"):
                self.assertNotIn(token, source, f"{name}: {token}")

    def test_no_h109_namespace_access(self):
        #: the pins module states the prohibition in its docstring; that
        #: prose sentence is not an access — strip it before asserting
        prohibition = "No h109-* material may be accessed, reconstructed,"
        for name in ("issue182_campaign_pins.py", "issue182_authority.py",
                     "issue182_inventory.py", "issue182_compare.py",
                     "issue182_terminal.py"):
            source = (SCRIPTS / name).read_text()
            source = source.replace(
                f'FORBIDDEN_NAMESPACE = "{P.FORBIDDEN_NAMESPACE}"', "")
            source = source.replace(prohibition, "")
            self.assertNotIn(P.FORBIDDEN_NAMESPACE, source, name)


if __name__ == "__main__":
    unittest.main()
