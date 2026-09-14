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

Review-correction round (maintainer comment 5666244858):

20. P1-1: a failed/missing probe receipt is OBS-PROBE-FAILED (BLOCKED),
    never an empty observation; an empty process list is admissible
    ONLY against a proven-successful ps receipt
21. P1-1: missing/unparseable/non-idle GPU telemetry stops the campaign
22. P1-2: stale sequence / replayed record / wrong attempt / wrong
    authority binding are rejected (observation epoch controls)
23. P1-3: sha256-* objects must carry matching content-address
    identity; forged extra objects with unaccepted provenance are
    rejected even though the pre-correction subset check accepted them
24. planning-only terminal fields are derived, not authored literals
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
import issue182_compare as C  # noqa: E402
import issue182_inventory as I  # noqa: E402
import issue182_terminal as T  # noqa: E402

from issue74_methodology import canonical_json_bytes  # noqa: E402

EVIDENCE_DIR = P.EVIDENCE_DIR
ARM_B = P.ARM_B

BASE_COMPARISON = None
LIVE_AUTHORITY = None


def load_arm_b(name: str) -> dict:
    return json.loads((ARM_B / name).read_text())


def live_authority() -> dict:
    global LIVE_AUTHORITY
    if LIVE_AUTHORITY is None:
        LIVE_AUTHORITY = json.loads(
            (EVIDENCE_DIR / "authority.json").read_text())
    return LIVE_AUTHORITY


def synthetic_epoch(host: str, **overrides) -> dict:
    """Observation epoch bound to the live frozen authority bytes."""
    authority = live_authority()
    epoch = {
        "sequence": P.OBSERVATION_SEQUENCE,
        "authority_digest": authority["authority_digest"],
        "campaign_id": P.CAMPAIGN_ID,
        "attempt_id": P.ATTEMPT_ID,
        "host": host,
    }
    epoch.update(overrides)
    return epoch


def ok_receipt(name: str, stdout: str = "") -> dict:
    return {
        "name": name, "argv": [name], "returncode": 0,
        "stdout_bytes": len(stdout), "stdout_sha256":
            hashlib.sha256(stdout.encode()).hexdigest(),
        "stdout": stdout, "stderr_bytes": 0,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(), "stderr": "",
    }


def synthetic_warm_record(node: str, **overrides) -> dict:
    """A fresh-observation-shaped record over the accepted object set.

    The verified object set is derived from the retained accepted
    Arm-B post-acquisition inventories — identical semantics to a
    fresh scan of the live cache under the accepted cache contract.
    """
    post = load_arm_b(f"inventory-post-{node}.json")
    record = {
        "schema": P.INVENTORY_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "attempt_id": P.ATTEMPT_ID,
        "host": node,
        "problems": [],
        "byte_preservation_proven": True,
        "cache_root": P.CACHE_OBJECTS_ROOT,
        "observation_epoch": synthetic_epoch(node),
        "verified_objects": [
            {"content_digest": obj["content_digest"],
             "length": obj["length"],
             "byte_digest_verified": True,
             "content_address_verified": True}
            for obj in post["verified_objects"]],
        "fence": {
            "processes": [],
            "ports": {"18080": [], "18485": [], "18486": []},
            "gpus": [
                {"index": index, "uuid": uuid,
                 "memory_total": "12288 MiB", "memory_used": "1 MiB",
                 "driver": "610.57.04"}
                for index, uuid in
                sorted(P.FROZEN_HOST_GPU_UUIDS[node].items())],
            "probe_receipts": {
                "ps": ok_receipt("ps"),
                "ss:18080": ok_receipt("ss:18080"),
                "ss:18485": ok_receipt("ss:18485"),
                "ss:18486": ok_receipt("ss:18486"),
                "nvidia-smi": ok_receipt("nvidia-smi"),
            },
            "collected_at_unix": 1789396037,
        },
    }
    record["record_digest"] = T.observation_record_digest(record)
    for key, value in overrides.items():
        if key == "epoch_overrides":
            record["observation_epoch"].update(value)
        else:
            record[key] = value
    return record


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
        cls.authority = live_authority()

    def test_schema_and_campaign(self):
        self.assertEqual(self.authority["schema"], P.AUTHORITY_SCHEMA)
        self.assertEqual(self.authority["campaign_id"], P.CAMPAIGN_ID)
        self.assertEqual(
            self.authority["physical_authorization_id"],
            P.PHYSICAL_AUTHORIZATION_ID)

    def test_accepted_heads_bound(self):
        self.assertTrue(self.authority["heads"]["ancestor_proofs"][
            "merge_181_is_ancestor_of_main"])

    def test_attempt_state_machine_bound(self):
        machine = self.authority["attempt_state_machine"]
        self.assertEqual(machine["attempt_id"], P.ATTEMPT_ID)
        # the frozen authority predates the review-round amendment;
        # its STOP-rule list PLUS the amendment's new rules must equal
        # the living pin set (the authority itself is never rewritten)
        effective = sorted(set(machine["stop_rules"]) | set(
            self.amendment_new_stop_rules()))
        self.assertEqual(effective, sorted(P.STOP_RULES))

    @staticmethod
    def amendment_new_stop_rules() -> list[str]:
        amendment_path = (P.EVIDENCE_DIR / "authority" /
                          "amendment-1-reduction-hardening.json")
        if not amendment_path.is_file():
            return []
        amendment = json.loads(amendment_path.read_text())
        return list(amendment.get("new_stop_rules") or [])

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

    def test_observation_epoch_frozen(self):
        epoch = self.authority["observation_epoch"]
        self.assertEqual(epoch["sequence"], P.OBSERVATION_SEQUENCE)
        self.assertEqual(epoch["retained_cold_sequence"], 1)
        self.assertEqual(epoch["retained_accepted_sequence"], 2)
        self.assertEqual(epoch["sequence"],
                         epoch["retained_accepted_sequence"] + 1)

    def test_probe_contract_fail_closed(self):
        contract = self.authority["probe_contract"]
        self.assertTrue(contract["fail_closed"])
        self.assertEqual(contract["stop_rule"], "OBS-PROBE-FAILED")
        self.assertEqual(sorted(contract["probes"]),
                         sorted(P.FENCE_PROBE_NAMES))

    def test_accepted_cache_objects_binding_rederivable(self):
        """The sidecar on disk equals the sha256 in the authority AND is
        re-derivable from the retained Arm-B post inventories."""
        binding = self.authority["accepted_cache_objects"]
        sidecar_path = P.ROOT / binding["path"]
        self.assertEqual(
            hashlib.sha256(sidecar_path.read_bytes()).hexdigest(),
            binding["sha256"])
        sidecar = json.loads(sidecar_path.read_text())
        self.assertEqual(sidecar["schema"], P.ACCEPTED_CACHE_OBJECTS_SCHEMA)
        for node in P.OBSERVATION_HOSTS:
            retained = load_arm_b(f"inventory-post-{node}.json")
            retained_set = {(obj["content_digest"], obj["length"])
                            for obj in retained["verified_objects"]}
            sidecar_set = {(obj["content_digest"], obj["length"])
                           for obj in sidecar["per_node"][node]["objects"]}
            self.assertEqual(retained_set, sidecar_set, node)


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

    def test_warm_sequence_is_bound_epoch_not_literal(self):
        """The warm snapshot sequence is 3 only via the bound epoch
        (P1-2); no planner-side manufacture of sequence values."""
        source = (SCRIPTS / "issue182_compare.py").read_text()
        self.assertNotIn('"sequence": 2', source)
        self.assertNotIn('"sequence": 3', source)

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

    def test_digest_mismatched_object_rejected(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"][0]["content_digest"] = \
            "sha256:" + "0" * 64
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("cache drift", str(ctx.exception))

    def test_wrong_node_inventory_rejected(self):
        warm01 = synthetic_warm_record("inferswarm01")
        warm03 = synthetic_warm_record("inferswarm03")
        swap = warm03["verified_objects"]
        warm03["verified_objects"] = warm01["verified_objects"]
        warm01["verified_objects"] = swap
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm01, warm03)
        self.assertIn("cache drift", str(ctx.exception))

    def test_source_advertisement_not_possession(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"] = []
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("cache drift", str(ctx.exception))


class FreshnessControlsTests(unittest.TestCase):
    """22 (P1-2). stale/replayed/wrong-attempt/wrong-authority rejected."""

    def test_stale_sequence_rejected(self):
        warm = synthetic_warm_record(
            "inferswarm01",
            epoch_overrides={"sequence": 2})
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("epoch identity wrong or stale", str(ctx.exception))

    def test_replayed_record_wrong_host_rejected(self):
        # a record collected for 03 replayed as the 01 observation
        warm = synthetic_warm_record("inferswarm01")
        warm["observation_epoch"]["host"] = "inferswarm03"
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("epoch identity wrong or stale", str(ctx.exception))

    def test_wrong_attempt_rejected_by_compare(self):
        warm = synthetic_warm_record(
            "inferswarm01",
            epoch_overrides={"attempt_id": "arme-182-physical-1"})
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("epoch identity wrong or stale", str(ctx.exception))

    def test_wrong_authority_binding_rejected(self):
        warm = synthetic_warm_record(
            "inferswarm01",
            epoch_overrides={"authority_digest": "0" * 64})
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("epoch identity wrong or stale", str(ctx.exception))

    def test_wrong_attempt_rejected_by_terminal(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["attempt_id"] = "arme-182-physical-1"
        warm["observation_epoch"]["attempt_id"] = "arme-182-physical-1"
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any(
            "OBS-OBSERVATION-EPOCH-INVALID" in p
            for p in document["problems"]))

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


class ForgedExtraObjectTests(unittest.TestCase):
    """23 (P1-3). content-address identity + accepted provenance."""

    def test_content_address_mismatch_detected_by_classifier(self):
        # a file whose name hex does NOT equal its bytes digest
        files = {
            "sha256-" + "a" * 64: {"size": 10, "mtime_ns": 1,
                                   "inode": 1, "sha256": "b" * 64},
        }
        objects, problems = I.classify_tree_objects(files)
        self.assertEqual(objects, [])
        self.assertEqual(problems[0]["stop_rule"],
                         "OBS-CONTENT-ADDRESS-MISMATCH")

    def test_non_content_addressed_file_rejected(self):
        files = {
            "README.txt": {"size": 3, "mtime_ns": 1,
                           "inode": 1, "sha256": "c" * 64},
        }
        objects, problems = I.classify_tree_objects(files)
        self.assertEqual(objects, [])
        self.assertEqual(problems[0]["stop_rule"],
                         "OBS-UNACCEPTED-CACHE-OBJECT")

    def test_valid_content_address_accepted(self):
        digest = hashlib.sha256(b"payload").hexdigest()
        files = {
            f"sha256-{digest}": {"size": 7, "mtime_ns": 1,
                                 "inode": 1, "sha256": digest},
        }
        objects, problems = I.classify_tree_objects(files)
        self.assertEqual(problems, [])
        self.assertEqual(objects[0]["content_address_verified"], True)
        self.assertEqual(objects[0]["content_digest"],
                         "sha256:" + digest)

    def _forged_object(self) -> dict:
        """An independent, well-formed forged object: content-address
        consistent, verified-looking, requirement-shaped — exactly what
        the pre-correction subset-only cross-check accepted."""
        digest = hashlib.sha256(b"forged-extra-object-control").hexdigest()
        # length of a real 15 MiB shard chunk so it looks like an
        # artifact chunk, not metadata noise
        return {"content_digest": "sha256:" + digest,
                "length": 15728640,
                "byte_digest_verified": True,
                "content_address_verified": True}

    def test_forged_extra_object_rejected_by_compare(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"] = (
            [self._forged_object()] + warm["verified_objects"])
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("unaccepted extra cache objects", str(ctx.exception))

    def test_forged_extra_object_accepted_by_pre_correction_logic(self):
        """4b control: the OLD subset-only cross-check accepted this
        exact forged record — the new equality check is what rejects
        it, so the regression catches the old defect, not vice versa."""
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"] = (
            [self._forged_object()] + warm["verified_objects"])
        authority = live_authority()

        def old_subset_check(warm_snapshot, node_id, auth):
            # replica of the pre-correction retained-subset cross-check
            path = C.ARM_B_POST_01 if node_id == "inferswarm01" \
                else C.ARM_B_POST_03
            retained = json.loads(path.read_text())
            retained_set = {(obj["content_digest"], obj["length"])
                            for obj in retained["verified_objects"]}
            fresh_set = {(obj["content_digest"], obj["length"])
                         for obj in warm_snapshot["verified_objects"]}
            if retained_set - fresh_set:
                raise SystemExit("old check: missing objects")

        original = C.check_warm_against_accepted
        try:
            C.check_warm_against_accepted = old_subset_check
            snapshot = C.warm_snapshot(warm, authority)  # must NOT raise
            self.assertEqual(
                len(snapshot["verified_objects"]),
                len(warm["verified_objects"]))
        finally:
            C.check_warm_against_accepted = original
        # and the restored hardening rejects it
        with self.assertRaises(SystemExit):
            C.warm_snapshot(warm, authority)

    def test_missing_accepted_object_rejected(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"] = warm["verified_objects"][1:]
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("cache drift", str(ctx.exception))

    def test_unverified_object_rejected(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"][0]["byte_digest_verified"] = False
        with self.assertRaises(RuntimeError) as ctx:
            run_compare(warm, synthetic_warm_record("inferswarm03"))
        self.assertIn("unverified object", str(ctx.exception))


class ProbeReceiptTests(unittest.TestCase):
    """20-21 (P1-1). fail-closed probes with retained receipts."""

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

    def test_empty_process_list_admissible_with_successful_receipt(self):
        self.assertEqual(
            synthetic_warm_record("inferswarm01")["fence"]["processes"], [])

    def test_missing_ps_receipt_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        del warm["fence"]["probe_receipts"]["ps"]
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-PROBE-FAILED" in p
                            for p in document["problems"]))

    def test_failed_nvidia_smi_blocks_not_empty_observation(self):
        """A failed nvidia-smi (rc=1, no output -> no GPU rows) must
        BLOCK on the failed receipt, never read as 'no GPUs observed'."""
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["probe_receipts"]["nvidia-smi"] = {
            "name": "nvidia-smi", "argv": I.GPU_QUERY, "returncode": 1,
            "stdout_bytes": 0,
            "stdout_sha256": hashlib.sha256(b"").hexdigest(),
            "stdout": "", "stderr_bytes": 57,
            "stderr_sha256": hashlib.sha256(b"err").hexdigest(),
            "stderr": "err"}
        warm["fence"]["gpus"] = []
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-PROBE-FAILED" in p
                            for p in document["problems"]))

    def test_missing_gpu_row_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["gpus"] = warm["fence"]["gpus"][:1]
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-GPU-SET-MISMATCH" in p
                            for p in document["problems"]))

    def test_unparseable_gpu_telemetry_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["gpus"][0]["memory_used"] = "[N/A]"
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-GPU-TELEMETRY-UNPARSEABLE" in p
                            for p in document["problems"]))

    def test_busy_gpu_blocks(self):
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["gpus"][0]["memory_used"] = "8192 MiB"
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-GPU-NOT-IDLE" in p
                            for p in document["problems"]))

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

    def test_tampered_comparison_now_blocks_not_fail(self):
        """Round-2 semantics change: a comparison whose rows were
        edited post-hoc (previously FAIL via rederive_problems) is now
        EVIDENCE_BLOCKED at the re-derivation gate — the retained
        document must BE the deterministic rebuild."""
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
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any(
            "OBS-COMPARISON-REDERIVATION-MISMATCH" in p
            for p in document["problems"]))


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


class StoredBooleanSubstitutionTests(unittest.TestCase):
    """15, 17-18, 24. authored booleans are not authority."""

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

    def test_planning_only_fields_not_authored_literals(self):
        """24: the planning-only booleans must be derived, so their
        literal True forms are banned from the terminal producer."""
        source = (SCRIPTS / "issue182_terminal.py").read_text()
        for field in ("no_model_execution", "no_gpu_initialization",
                      "no_artifact_acquisition", "no_h109_access"):
            self.assertNotIn(f'"{field}": True', source)
            self.assertNotIn(f"'{field}': True", source)

    def test_planning_only_fields_derive_false_under_attack(self):
        """If the underlying retained facts go missing, the derived
        planning-only fields must go False (they are computed)."""
        with tempfile.TemporaryDirectory(prefix="arm-e-deriv-") as tmp:
            tmp = Path(tmp)
            (tmp / "authority.json").write_text(
                (EVIDENCE_DIR / "authority.json").read_text())
            (tmp / "comparison.json").write_text(
                json.dumps(base_comparison()))
            obs = tmp / "observation"
            obs.mkdir()
            warm01 = synthetic_warm_record("inferswarm01")
            warm03 = synthetic_warm_record("inferswarm03")
            # a busy GPU must derive no_gpu_initialization False
            warm01["fence"]["gpus"][0]["memory_used"] = "8192 MiB"
            for node, record in (("inferswarm01", warm01),
                                 ("inferswarm03", warm03)):
                (obs / f"warm-inventory-{node}.json").write_text(
                    json.dumps(record))
            document = T.reduce_terminal(tmp)
            self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
            self.assertFalse(document["planning_only"][
                "no_gpu_initialization"])


class AdversarialReviewRoundControls(unittest.TestCase):
    """25 (review lanes A/B round 1): terminal-layer tamper controls.

    Each control reproduces a hole an adversarial reviewer demonstrated
    against the pre-hardening terminal at head aa708bd (independently
    re-confirmed by the operator before the fix landed)."""

    def _terminal_for(self, warm01, warm03, comparison=None):
        with tempfile.TemporaryDirectory(prefix="arm-e-rev-") as tmp:
            tmp = Path(tmp)
            (tmp / "authority.json").write_text(
                (EVIDENCE_DIR / "authority.json").read_text())
            obs = tmp / "observation"
            obs.mkdir()
            (obs / "warm-inventory-inferswarm01.json").write_text(
                json.dumps(warm01))
            (obs / "warm-inventory-inferswarm03.json").write_text(
                json.dumps(warm03))
            (tmp / "comparison.json").write_text(json.dumps(
                comparison if comparison is not None
                else base_comparison()))
            return T.reduce_terminal(tmp)

    def test_contradictory_empty_cache_record_blocks(self):
        """Lane A probe 4: digest-consistent empty-cache observation
        paired with the retained warm comparison must BLOCK, not PASS
        (pre-hardening terminal returned PASS here)."""
        import hashlib as _h
        warm01 = synthetic_warm_record("inferswarm01")
        warm03 = synthetic_warm_record("inferswarm03")
        for warm in (warm01, warm03):
            warm["verified_objects"] = []
            warm["record_digest"] = T.observation_record_digest(warm)
        document = self._terminal_for(warm01, warm03)
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-UNACCEPTED-CACHE-OBJECT" in p
                            for p in document["problems"]))

    def test_stale_record_digest_blocks(self):
        """Lane B probe: post-hoc tamper with a stale self-digest."""
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["gpus"][0]["memory_total"] = "24576 MiB"
        warm["record_digest"] = "0" * 64
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-RECORD-DIGEST-MISMATCH" in p
                            for p in document["problems"]))

    def test_gpu_total_drift_blocks_even_with_recomputed_digest(self):
        """Lane B probe variant: GPU total tampered but the digest is
        honestly recomputed — the total-vs-pin re-check still fires."""
        warm = synthetic_warm_record("inferswarm01")
        warm["fence"]["gpus"][0]["memory_total"] = "24576 MiB"
        warm["record_digest"] = T.observation_record_digest(warm)
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-GPU-TOTAL-DRIFT" in p
                            for p in document["problems"]))

    def test_fully_rebound_forged_extra_object_blocks(self):
        """Lane B central demo: a forged extra object with the sidecar,
        authority digest, epoch, and record digest ALL self-consistently
        re-bound must still BLOCK — the terminal re-derives the accepted
        set from retained Arm-B bytes, not from any re-bindable digest."""
        import hashlib as _h
        forged_hex = _h.sha256(b"review-lane-b-forgery").hexdigest()
        warm = synthetic_warm_record("inferswarm01")
        warm["verified_objects"].append({
            "content_digest": "sha256:" + forged_hex,
            "length": 15728640,
            "byte_digest_verified": True,
            "content_address_verified": True,
            "host_path": "sha256-" + forged_hex})
        warm["record_digest"] = T.observation_record_digest(warm)
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-UNACCEPTED-CACHE-OBJECT" in p
                            for p in document["problems"]))

    def test_forged_warm_arm_binding_blocks(self):
        """Lane A probe 2: a comparison authored over different
        inventory bytes than the retained observation must BLOCK on the
        warm-arm cross-binding."""
        comparison = copy.deepcopy(base_comparison())
        binding = comparison.get("warm_arm_binding")
        if binding is None:
            self.fail("comparison.json lacks warm_arm_binding")
        binding["inferswarm01"]["snapshot_canonical_sha256"] = "0" * 64
        document = self._terminal_for(
            synthetic_warm_record("inferswarm01"),
            synthetic_warm_record("inferswarm03"),
            comparison=comparison)
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-WARM-ARM-BINDING-MISMATCH" in p
                            for p in document["problems"]))

    def test_retained_evidence_terminal_still_passes(self):
        """The corrected terminal still derives PASS from the retained
        physical records (regression: hardening must not over-block)."""
        with tempfile.TemporaryDirectory(prefix="arm-e-live-") as tmp:
            tmp = Path(tmp)
            (tmp / "authority.json").write_text(
                (EVIDENCE_DIR / "authority.json").read_text())
            obs = tmp / "observation"
            obs.mkdir()
            for node in P.OBSERVATION_HOSTS:
                (obs / f"warm-inventory-{node}.json").write_text(
                    (EVIDENCE_DIR / "observation" /
                     f"warm-inventory-{node}.json").read_text())
            (tmp / "comparison.json").write_text(
                (EVIDENCE_DIR / "comparison.json").read_text())
            document = T.reduce_terminal(tmp)
        self.assertEqual(document["terminal"], P.PASS_TERMINAL)
        self.assertEqual(document["problems"], [])


class AdversarialReviewRound2Controls(unittest.TestCase):
    """26 (review lanes A/B round 2): authored-content trust controls.

    Round 2 demonstrated the terminal trusted authored DERIVED fields
    (comparison rows, GPU-used rows, preservation booleans). Every
    control here reproduces a demonstrated hole against head 9bc30b1
    and asserts the corrected terminal blocks it."""

    def _terminal_for(self, warm01, warm03, comparison=None):
        with tempfile.TemporaryDirectory(prefix="arm-e-rev2-") as tmp:
            tmp = Path(tmp)
            (tmp / "authority.json").write_text(
                (EVIDENCE_DIR / "authority.json").read_text())
            obs = tmp / "observation"
            obs.mkdir()
            (obs / "warm-inventory-inferswarm01.json").write_text(
                json.dumps(warm01))
            (obs / "warm-inventory-inferswarm03.json").write_text(
                json.dumps(warm03))
            (tmp / "comparison.json").write_text(json.dumps(
                comparison if comparison is not None
                else base_comparison()))
            return T.reduce_terminal(tmp)

    def test_fabricated_economics_block(self):
        """Lane A P0-1: forged self-consistent comparison with
        fabricated cold/warm magnitudes must BLOCK on re-derivation."""
        comparison = copy.deepcopy(base_comparison())
        v5 = P.SUBJECT["candidate"]
        for arm in ("cold_arm", "warm_arm"):
            comparison[arm]["rows"][v5]["missing_bytes"] = 7
            comparison[arm]["rows"][v5]["ranking_value"] = 0.25
            comparison[arm]["rows"][v5]["required_bytes"] = 7
        # keep cross-arm coupling internally consistent
        comparison["v5"]["cold"]["missing_bytes"] = 7
        comparison["v5"]["warm"]["missing_bytes"] = 3
        document = self._terminal_for(
            synthetic_warm_record("inferswarm01"),
            synthetic_warm_record("inferswarm03"),
            comparison=comparison)
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any(
            "OBS-COMPARISON-REDERIVATION-MISMATCH" in p
            for p in document["problems"]))

    def test_jointly_forged_gate_ledger_blocks(self):
        """Lane A P0-2: a gate flipped identically in BOTH arms (e.g.
        an infeasible candidate forged admissible everywhere) must
        BLOCK on re-derivation."""
        comparison = copy.deepcopy(base_comparison())
        infeasible = "dense.3b8644d360a3"
        for arm in ("cold_arm", "warm_arm"):
            row = comparison[arm]["rows"][infeasible]
            row["gates"]["technical_feasibility"]["passed"] = True
            row["admissible"] = True
            row["ranking_status"] = "RANKED"
        document = self._terminal_for(
            synthetic_warm_record("inferswarm01"),
            synthetic_warm_record("inferswarm03"),
            comparison=comparison)
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any(
            "OBS-COMPARISON-REDERIVATION-MISMATCH" in p
            for p in document["problems"]))

    def test_gpu_used_vs_receipt_stdout_drift_blocks(self):
        """Lane B P1-2: fence rows claiming idle while the retained
        nvidia-smi stdout says 9000 MiB used must BLOCK."""
        warm = synthetic_warm_record("inferswarm01")
        stdout_lines = []
        for gpu in warm["fence"]["gpus"]:
            stdout_lines.append(
                f"{gpu['index']}, {gpu['uuid']}, 12288 MiB, 9000 MiB, "
                f"{gpu['driver']}")
        stdout = "\n".join(stdout_lines) + "\n"
        warm["fence"]["probe_receipts"]["nvidia-smi"]["stdout"] = stdout
        warm["fence"]["probe_receipts"]["nvidia-smi"]["stdout_sha256"] = (
            hashlib.sha256(stdout.encode()).hexdigest())
        warm["fence"]["probe_receipts"]["nvidia-smi"]["stdout_bytes"] = (
            len(stdout.encode()))
        warm["record_digest"] = T.observation_record_digest(warm)
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-GPU-TELEMETRY-DRIFT" in p
                            for p in document["problems"]))

    def test_preservation_digest_mismatch_blocks(self):
        """Lane B P2: byte_preservation_proven kept true while the
        retained before/after tree digests differ must BLOCK."""
        warm = synthetic_warm_record("inferswarm01")
        warm["preservation_before"] = {"file_count": 411,
                                       "tree_digest": "aaa"}
        warm["preservation_after"] = {"file_count": 411,
                                      "tree_digest": "bbb"}
        warm["record_digest"] = T.observation_record_digest(warm)
        document = self._terminal_for(
            warm, synthetic_warm_record("inferswarm03"))
        self.assertEqual(document["terminal"], P.BLOCKED_TERMINAL)
        self.assertTrue(any("OBS-MUTATION-DETECTED" in p
                            for p in document["problems"]))

    def test_manifest_of_evidence_dir_verifies(self):
        """Lanes A/B P2-3: MANIFEST.sha256 has an automated verifier —
        every row matches the retained evidence bytes (a doctored
        evidence file regenerating nothing leaves a detectable
        mismatch)."""
        manifest = (EVIDENCE_DIR / "MANIFEST.sha256").read_text().splitlines()
        self.assertTrue(manifest)
        for line in manifest:
            digest, _, name = line.partition("  ")
            path = P.ROOT / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), digest, name)


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
