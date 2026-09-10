"""Issue #133 corrected freeze — mandatory regression closure tests.

The Phase-A suite missed Blocker A because the positive path MOCKED
``build_execution_plan()``. These tests close that gap:

- REAL-BUILDER CPU DRY RUN: execute the actual frozen producer
  planning/build path (no mocked build_execution_plan, no GPU, no model
  realization) from the exact corrected canonical environment and the
  exact authorized chain plan, and require the resulting
  ``inferswarm.r5a.static-execution-plan/1`` digest to equal the newly
  frozen r5a static-plan digest, with the expected Issue-133
  candidate/mapping semantics;

- WRONG-FAMILY NEGATIVE CONTROL: the accepted Arm-B participant-plan
  digest (``inferswarm.issue117.execution-plan/2``,
  sha256:8646e00c…) can NEVER satisfy the r5a static-plan authorization
  fence — not by digest equality, not by schema substitution;

- ENVIRONMENT CANONICALIZATION: the corrected canonical environment is
  the #129 derivation with exactly the three BDF corrections and no
  narrative provenance_note; BDF drift negative controls (stale #129
  literals, 12-char forms, swapped GPUs) fail closed;

- the deployed-state identity: the corrected canonical environment is
  byte-identical to the historical physically-deployed environment
  (98c04387…), independently validating that the deployed BDF truth was
  physical all along;

- the three plan identities remain distinct across the freeze.

CPU-only. No GPU, no model execution, no participant-state mutation.
"""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue129_arm_c_retry_core as core  # noqa: E402
import issue133_arm_c_retry_campaign as camp  # noqa: E402
import issue133_arm_c_retry_direct as drv  # noqa: E402
import issue133_canonical_environment as ice  # noqa: E402
import issue133_real_builder_dry_run as dry  # noqa: E402


class RealBuilderDryRunTests(unittest.TestCase):
    """The critical acceptance test: from the final correction bytes,
    before any GPU/model work, the actual unmocked direct builder
    produces exactly the same-family r5a static execution-plan digest
    the new freeze authorizes."""

    @classmethod
    def setUpClass(cls):
        result = dry.run_real_builder_dry_run()
        cls.plan = result["plan"]
        cls.environment = result["environment"]

    def test_built_plan_family_is_r5a_static(self):
        self.assertEqual(self.plan["schema"],
                         "inferswarm.r5a.static-execution-plan/1")

    def test_built_digest_equals_frozen_authority(self):
        self.assertEqual(self.plan["digest"],
                         camp.AUTHORIZED_R5A_STATIC_PLAN_DIGEST)
        self.assertEqual(self.plan["digest"],
                         drv.AUTHORIZED_R5A_STATIC_PLAN_DIGEST)

    def test_candidate_and_mapping_are_expected_issue133_values(self):
        self.assertEqual(self.plan["candidate_id"],
                         camp.ISSUE133_R5A_EXPECTED_CANDIDATE_ID)
        self.assertEqual(self.plan["mapping"],
                         camp.ISSUE133_R5A_EXPECTED_MAPPING)
        self.assertEqual(self.plan["mapping"], {
            "slot-stage-1": "gpu.node-a.0",
            "slot-stage-2": "gpu.node-a.1",
            "slot-stage-3": "gpu.node-b.0"})

    def test_full_dry_run_verdict_passes(self):
        verdict = dry.verify_dry_run(self.plan)
        self.assertEqual(verdict["digest"], verdict["frozen_digest"])

    def test_built_plan_passes_the_driver_fence(self):
        drv.verify_r5a_plan_authorization_fence(self.plan)

    def test_environment_is_the_corrected_canonical_one(self):
        self.assertEqual(
            ice.environment_canonical_sha256(self.environment),
            "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5"
            "edbf67")

    def test_deterministic_rebuild(self):
        second = dry.run_real_builder_dry_run()["plan"]
        self.assertEqual(second["digest"], self.plan["digest"])


class WrongFamilyNegativeControlTests(unittest.TestCase):
    """The Arm-B participant-plan digest (issue117.execution-plan/2) is
    valid accepted authority but can never satisfy the r5a fence."""

    def test_arm_b_digest_rejected_as_r5a_fence_input(self):
        with self.assertRaises(SystemExit):
            drv.verify_r5a_plan_authorization_fence(
                {"schema": "inferswarm.issue117.execution-plan/2",
                 "digest": camp.ISSUE133["execution_plan_digest"]})

    def test_arm_b_digest_rejected_even_with_r5a_schema_claim(self):
        with self.assertRaises(SystemExit):
            drv.verify_r5a_plan_authorization_fence(
                {"schema": "inferswarm.r5a.static-execution-plan/1",
                 "digest": camp.ISSUE133["execution_plan_digest"]})

    def test_arm_b_identity_independently_verifies(self):
        # the Arm-B digest remains valid PRESERVED authority: recomputed
        # from the retained accepted Arm-B execution-plan document
        dry.verify_arm_b_participant_authority()

    def test_wrong_family_control_via_dry_run_module(self):
        plan = dry.run_real_builder_dry_run()["plan"]
        dry.verify_wrong_family_negative_control(plan)

    def test_three_plan_identities_are_pairwise_distinct(self):
        identities = {
            camp.ISSUE133["execution_plan_digest"],   # Arm-B participant
            camp.AUTHORIZED_REALIZATION_INPUTS["chain_plan"]["digest"],
            camp.AUTHORIZED_R5A_STATIC_PLAN_DIGEST,
            camp.ISSUE133["participant_identity"],
        }
        self.assertEqual(len(identities), 4)


class CorrectedEnvironmentTests(unittest.TestCase):
    def test_corrected_environment_derivation(self):
        environment = ice.issue133_physical_environment()
        self.assertEqual(
            environment["node_a"]["gpus"][0]["pci_bdf"], "00000000:02:00.0")
        self.assertEqual(
            environment["node_a"]["gpus"][1]["pci_bdf"], "00000000:03:00.0")
        self.assertEqual(
            environment["node_b"]["gpus"][0]["pci_bdf"], "00000000:01:00.0")
        self.assertNotIn("provenance_note", environment)

    def test_canonical_identity_matches_frozen_constant(self):
        self.assertEqual(
            ice.environment_canonical_sha256(
                ice.issue133_physical_environment()),
            camp.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256)
        self.assertEqual(
            camp.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256,
            drv.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256)

    def test_corrected_environment_equals_deployed_physical_truth(self):
        # byte-identical to the historical deployed environment on
        # inferswarm00 — independent validation that the deployed BDFs
        # were the physical truth the #129 reconstruction lacked
        environment = ice.issue133_physical_environment()
        expected = {
            "schema": "inferswarm.r6.environment-freeze/1",
            "implementation_commit": "924cd22ea081f6d4ed471016faf01d427"
                                     "fc5b0d2",
            "runtime_context": None,  # checked below via full equality
        }
        self.assertEqual(environment["schema"], expected["schema"])
        deployed = json.loads(json.dumps(environment))
        canonical = (json.dumps(deployed, indent=2, sort_keys=True)
                     + "\n").encode()
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5"
            "edbf67")

    def test_uuid_product_index_come_from_accepted_preflight(self):
        environment = ice.issue133_physical_environment()
        preflight = json.loads(
            (ROOT / "docs/implementation"
             / "r6-successor-dense-full-integration-117"
             / "evidence/physical-preflight.json").read_text())
        units = {u["cu_id"]: u for u in preflight["compute_units"]}
        pairs = [
            (environment["node_a"]["gpus"][0], "inferswarm01/gpu-0", 0),
            (environment["node_a"]["gpus"][1], "inferswarm01/gpu-1", 1),
            (environment["node_b"]["gpus"][0], "inferswarm03/gpu-0", 0),
        ]
        for gpu, cu_id, index in pairs:
            self.assertEqual(gpu["uuid"], units[cu_id]["gpu_uuid"])
            self.assertEqual(gpu["name"], units[cu_id]["gpu_product"])
            self.assertEqual(gpu["index"], index)

    def test_observation_record_is_retained_and_canonical(self):
        raw = (ROOT / "docs/implementation"
               / "r6-successor-dense-full-integration-117"
               / "evidence/arm-c-retry/gpu-identity-observation.json"
               ).read_bytes()
        document = json.loads(raw)
        canonical = (json.dumps(document, indent=2, sort_keys=True)
                     + "\n").encode()
        self.assertEqual(raw, canonical)
        self.assertEqual(
            document["schema"],
            "inferswarm.issue133.physical-gpu-identity-observation/1")
        # the extra idle inferswarm03 GPU is recorded as observed-but-
        # unused, NOT added to the environment
        extra = [g for g in document["hosts"]["inferswarm03"]["gpus"]
                 if not g.get("in_authorized_geometry")]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0]["gpu_uuid"],
                         "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0")
        self.assertNotIn(extra[0]["pci_bdf"],
                         [g["pci_bdf"] for g in
                          ice.issue133_physical_environment()["node_b"]
                          ["gpus"]])


class BdfDriftNegativeTests(unittest.TestCase):
    """Any BDF drift from the observed physical truth must change the
    environment identity (fail the driver fence) and must never
    reproduce the frozen r5a digest."""

    def _with_bdfs(self, a0, a1, b0):
        environment = ice.issue133_physical_environment()
        environment["node_a"]["gpus"][0]["pci_bdf"] = a0
        environment["node_a"]["gpus"][1]["pci_bdf"] = a1
        environment["node_b"]["gpus"][0]["pci_bdf"] = b0
        return environment

    def test_control_stale_129_literals_rejected_by_fence(self):
        stale = self._with_bdfs("0000:01:00.0", "0000:02:00.0",
                                "0000:01:00.0")
        with self.assertRaises(SystemExit):
            drv.verify_environment_authorization(stale)

    def test_control_stale_129_literals_change_identity(self):
        stale = self._with_bdfs("0000:01:00.0", "0000:02:00.0",
                                "0000:01:00.0")
        self.assertNotEqual(
            ice.environment_canonical_sha256(stale),
            camp.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256)

    def test_control_12char_bdf_form_rejected_by_shape(self):
        short = self._with_bdfs("0000:02:00.0", "00000000:03:00.0",
                                "00000000:01:00.0")
        with self.assertRaises(RuntimeError):
            ice.validate_environment_shape(short)

    def test_control_swapped_gpu_bdfs_change_identity(self):
        swapped = self._with_bdfs("00000000:03:00.0", "00000000:02:00.0",
                                  "00000000:01:00.0")
        self.assertNotEqual(
            ice.environment_canonical_sha256(swapped),
            camp.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256)

    def test_control_bdf_mutation_changes_built_plan_digest(self):
        # a mutated-BDF environment really built through the REAL
        # producer path yields a DIFFERENT r5a digest — the fence would
        # fail closed on a physical launch
        mutated = self._with_bdfs("0000:01:00.0", "0000:02:00.0",
                                  "0000:01:00.0")
        plan = drv.build_execution_plan_from_environment(mutated)
        self.assertNotEqual(plan["digest"],
                            camp.AUTHORIZED_R5A_STATIC_PLAN_DIGEST)
        with self.assertRaises(SystemExit):
            drv.verify_r5a_plan_authorization_fence(plan)

    def test_control_extra_gpu_in_geometry_rejected_by_shape(self):
        expanded = ice.issue133_physical_environment()
        expanded["node_b"]["gpus"].append(
            copy.deepcopy(expanded["node_b"]["gpus"][0]))
        with self.assertRaises(RuntimeError):
            ice.validate_environment_shape(expanded)

    def test_control_provenance_note_rejected_as_authorization_input(self):
        env = ice.issue133_physical_environment()
        env["provenance_note"] = "narrative-only field"
        with self.assertRaises(RuntimeError):
            ice.validate_environment_shape(env)


class DryRunGateCliTests(unittest.TestCase):
    def test_dry_run_script_main_passes(self):
        import subprocess
        completed = subprocess.run(
            [sys.executable,
             str(ROOT / "scripts/issue133_real_builder_dry_run.py")],
            capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        verdict = json.loads(completed.stdout)
        self.assertEqual(verdict["gate"],
                         "ISSUE133_REAL_BUILDER_CPU_DRY_RUN_BOUND")


if __name__ == "__main__":
    unittest.main()
