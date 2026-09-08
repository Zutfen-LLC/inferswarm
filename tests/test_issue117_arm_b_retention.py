"""Arm-B retained-evidence mutation tests (Issue #117).

Every test mutates one retained Arm-B evidence artifact in an isolated copy
of the repository evidence tree, runs the REAL reducer derivation against
it, and requires the mutated dimension to fail closed. No constant
assertions: the full derivation path re-runs each time.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REDUCER = ROOT / "scripts" / "issue117_arm_b_evidence.py"
ARM_B = (ROOT / "docs" / "implementation" /
         "r6-successor-dense-full-integration-117" / "evidence" / "arm-b")

PYTHON = sys.executable


def run_reducer(env_root: Path):
    """Run the reducer against an alternate repository root."""
    result = subprocess.run(
        [PYTHON, str(REDUCER)], capture_output=True, text=True,
        env={"ARM_B_EVIDENCE_ROOT": str(env_root / "arm-b"),
             "PINS_ROOT": str(env_root.parent),
             "PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        timeout=120)
    return result


class MutationTestCase(unittest.TestCase):
    """Base: copy evidence, apply mutation, require derivation failure."""

    def mutate_and_run(self, filename, mutator):
        tmp = Path(tempfile.mkdtemp(prefix="armb-mut-"))
        root = tmp / "evidence"
        root.mkdir()
        shutil.copytree(ARM_B, root / "arm-b")
        # the reducer also pins the preserved files one level up
        (root.parent).mkdir(parents=True, exist_ok=True)
        for pin in ("physical-preflight.json", "canonical-summary.json"):
            src = (ROOT / "docs" / "implementation" /
                   "r6-successor-dense-full-integration-117" / "evidence" / pin)
            shutil.copy(src, root.parent / pin)
        mutator(root / "arm-b" / filename)
        return run_reducer(root)

    def assertFails(self, result, needle=None):
        # fail-closed: nonzero exit, with either the explicit failure
        # classification or an unhandled derivation error (both refuse to
        # derive a PASS from mutated evidence)
        self.assertNotEqual(result.returncode, 0,
                            f"mutation not caught; output: {result.stdout[-800:]}")
        combined = result.stdout + result.stderr
        if needle is not None:
            self.assertIn(needle, combined)
        else:
            self.assertTrue(
                "ISSUE117_ARM_B_EVIDENCE_DERIVATION_FAILURE" in combined
                or "Traceback" in combined or "Failure" in combined,
                f"unexpected clean failure shape: {combined[-400:]}")


class ColdRootMutations(MutationTestCase):
    def test_cold_root_not_empty(self):
        def m(p):
            d = json.loads(p.read_text())
            d["roots"]["/srv/inferswarm/cache/issue117"]["entry_count"] = 1
            d["roots"]["/srv/inferswarm/cache/issue117"]["total_bytes"] = 1024
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "cold-root-prestate-inferswarm01.json", m))

    def test_cold_root_symlink(self):
        def m(p):
            d = json.loads(p.read_text())
            d["roots"]["/srv/inferswarm/materialized/issue117"]["is_symlink"] = True
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "cold-root-prestate-inferswarm03.json", m))

    def test_hardlink_alias(self):
        def m(p):
            d = json.loads(p.read_text())
            d["roots"]["/srv/inferswarm/cache/issue117"]["hardlink_entries"] = [
                {"path": "model.safetensors", "nlink": 2}]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "cold-root-prestate-inferswarm01.json", m))

    def test_bind_mount_same_device(self):
        def m(p):
            d = json.loads(p.read_text())
            g = d["gemma_r6_relationship"]
            for r in d["roots"].values():
                r["st_dev"] = g["gemma_root_st_dev"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "cold-root-prestate-inferswarm01.json", m))


class AcquisitionMutations(MutationTestCase):
    def test_unauthorized_source(self):
        def m(p):
            d = json.loads(p.read_text())
            for e in d["events"]:
                if e["event"] == "ACQUIRED":
                    e["source_id"] = "rogue-source"
                    break
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm03.json", m))

    def test_unassigned_artifact(self):
        def m(p):
            d = json.loads(p.read_text())
            for e in d["events"]:
                if e["event"] == "ACQUIRED":
                    e["artifact_id"] = "sha256:" + "0" * 64
                    break
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm01.json", m))

    def test_missing_participant_requirement(self):
        def m(p):
            d = json.loads(p.read_text())
            d["participants"] = d["participants"][:2]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("requirements.json", m))

    def test_extra_participant_artifact(self):
        def m(p):
            d = json.loads(p.read_text())
            fake = dict(d["participants"][0]["required_artifacts"][0])
            fake["artifact_id"] = "sha256:" + "1" * 64
            d["participants"][0]["required_artifacts"].append(fake)
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("requirements.json", m))

    def test_integrity_failure_present(self):
        def m(p):
            d = json.loads(p.read_text())
            d["aggregate"]["integrity_failures"] = [
                {"artifact_id": "sha256:x", "reason": "INTEGRITY_DIGEST_MISMATCH"}]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm01.json", m))

    def test_missing_verified_object(self):
        def m(p):
            d = json.loads(p.read_text())
            # drop one verified object that a required artifact needs
            d["verified_objects"] = d["verified_objects"][1:]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "inventory-post-inferswarm01.json", m))

    def test_unverified_object_treated_as_local(self):
        def m(p):
            d = json.loads(p.read_text())
            d["verified_objects"][0]["byte_digest_verified"] = False
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "inventory-post-inferswarm03.json", m))

    def test_byte_accounting_discrepancy(self):
        def m(p):
            d = json.loads(p.read_text())
            for e in d["events"]:
                if e["event"] == "ACQUIRED":
                    e["bytes"] = e["bytes"] + 4096
                    break
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm03.json", m))

    def test_missing_ledger_entry(self):
        def m(p):
            d = json.loads(p.read_text())
            acq = [i for i, e in enumerate(d["events"]) if e["event"] == "ACQUIRED"]
            del d["events"][acq[0]]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm03.json", m))


class CoordinatorMutations(MutationTestCase):
    def test_coordinator_model_payload_byte(self):
        def m(p):
            d = json.loads(p.read_text())
            d["coordinator_bulk_artifact_bytes_observed"] = 512
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-record.json", m))

    def test_coordinator_cuda_initialized(self):
        def m(p):
            d = json.loads(p.read_text())
            d["coordinator_cuda_initialized"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-counters.json", m))

    def test_coordinator_weight_bytes_materialized(self):
        def m(p):
            d = json.loads(p.read_text())
            d["coordinator_model_weight_bytes_materialized"] = 1024
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-counters.json", m))

    def test_plan_substitution(self):
        def m(p):
            d = json.loads(p.read_text())
            d["plan_digest"] = "sha256:" + "9" * 64
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-record.json", m))


class MaterializationMutations(MutationTestCase):
    def test_wrong_object_digest(self):
        def m(p):
            d = json.loads(p.read_text())
            d["tensor_bytes"] = d["tensor_bytes"] + 16
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("assemble-stage-2.json", m))

    def test_hidden_whole_model_read(self):
        def m(p):
            d = json.loads(p.read_text())
            d["unexplained_full_model_dependency"] = 1
            d["gemma_whole_model_weight_read_count"] = 1
            d["gemma_whole_model_weight_paths"] = [
                "/srv/models/gemma-r6/model.safetensors"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("read-audit-stage-3.json", m))

    def test_complete_repository_dependency(self):
        def m(p):
            d = json.loads(p.read_text())
            d["objects_written"][0]["bytes"] = 23_919_549_408 + 512
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("assemble-stage-1.json", m))

    def test_persistent_host_mirror(self):
        def m(p):
            d = json.loads(p.read_text())
            d["persistent_host_model_bytes"] = 4096
            d["host_resident_tensor_keys"] = ["model.language_model.norm.weight"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("realize-stage-1.json", m))

    def test_unplanned_post_materialization_movement(self):
        def m(p):
            d = json.loads(p.read_text())
            d["fetched_bytes"] = d["fetched_bytes"] + 2048
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("realize-stage-2.json", m))

    def test_runtime_fallback_event(self):
        def m(p):
            d = json.loads(p.read_text())
            d["aggregate"]["integrity_failures"] = [
                {"reason": "TRANSFER_INTERRUPTED"}]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm01.json", m))

    def test_wrong_gpu_binding(self):
        def m(p):
            d = json.loads(p.read_text())
            d["observed_gpu_uuid"] = "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("realize-stage-3.json", m))

    def test_checkpoint_authority_drift(self):
        def m(p):
            d = json.loads(p.read_text())
            d["model"]["checkpoint_authority_sha256"] = "0" * 64
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("execution-plan.json", m))

    def test_materialized_state_coverage_gap(self):
        def m(p):
            d = json.loads(p.read_text())
            d["materialized_logical_states"] = d[
                "materialized_logical_states"][:-1]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("assemble-stage-3.json", m))

    def test_delta_audit_material(self):
        def m(p):
            d = json.loads(p.read_text())
            d["delta_classification"] = "MATERIAL"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("delta-audit.json", m))

    def test_used_artifact_gap(self):
        def m(p):
            d = json.loads(p.read_text())
            d["used_artifact_ids"] = d["used_artifact_ids"][:-1]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("assemble-stage-1.json", m))


class Baseline(unittest.TestCase):
    def test_unmutated_pass(self):
        result = subprocess.run([PYTHON, str(REDUCER)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("ISSUE117_ARM_B_COLD_REALIZATION_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
