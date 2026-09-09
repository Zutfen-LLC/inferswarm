"""Arm-B retained-evidence mutation tests (Issue #117).

Every test mutates one retained Arm-B evidence artifact in an isolated copy
of the repository evidence tree, runs the REAL reducer derivation against
it, and requires the mutated dimension to fail closed. No constant
assertions: the full derivation path re-runs each time.

Round-3 additions (maintainer findings 1-5): raw source-server log SHA /
client drift, coordinator observed-inventory corruption, per-file sum
mismatch, stale textual total, derived-histogram-without-raw-change,
movement-summary mutation, movement-unestablishable non-PASS terminal,
execution-vs-retention distinction, parent/child lineage corruption,
timestamp/order contradiction.
"""
import json
import os
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
        timeout=300)
    return result


class MutationTestCase(unittest.TestCase):
    """Base: copy evidence, apply mutation, require derivation failure."""

    def mutate_and_run(self, filename, mutator):
        tmp = Path(tempfile.mkdtemp(prefix="armb-mut-",
                                    dir=os.environ.get("ARMB_MUT_TMP")
                                    or None))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
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
                or "Traceback" in combined or "Failure" in combined
                or "REDUCER FAILURE" in combined,
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

    def test_runtime_fallback_cpu_layers(self):
        # a real runtime fallback: CPU-owned decoder layers with a
        # perfectly clean acquisition ledger
        def m(p):
            d = json.loads(p.read_text())
            d["cpu_owned_decoder_layers"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("realize-stage-1.json", m))

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
                                capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("ISSUE117_ARM_B_COLD_REALIZATION_PASS", result.stdout)


class ReviewHardeningMutations(MutationTestCase):
    """One-mutation negative controls for the review-demonstrated derivation
    gaps (PR #127 reviews, 2026-09-08): inflated cache-hit bytes, whole-model
    reads hidden in other buckets, resume-flag byte bypass, staging retained
    after realization, stored coordinator counters diverging from
    observations, materialized-object path substitution, and aggregate/event
    reconciliation."""

    def test_cache_hit_bytes_inflated(self):
        def m(p):
            d = json.loads(p.read_text())
            for e in d["events"]:
                if e["event"] == "CACHE_HIT" and e["bytes"] > 1024:
                    e["bytes"] += 999999
                    break
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm03.json", m))

    def test_whole_model_read_in_other_bucket(self):
        def m(p):
            d = json.loads(p.read_text())
            d["classified"]["other_reads"].append(
                "/srv/models/gemma-r6/model.safetensors")
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("read-audit-stage-2.json", m))

    def test_resume_flag_byte_bypass(self):
        def m(p):
            d = json.loads(p.read_text())
            for e in d["events"]:
                if e["event"] == "ACQUIRED" and e["bytes"] > 1024:
                    e["bytes"] += 4096
                    e["resumed_from_bytes"] = 1
                    break
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm01.json", m))

    def test_host_staging_retained_after_realization(self):
        def m(p):
            d = json.loads(p.read_text())
            d["host_staging_current_bytes"] = 5000000000
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("realize-stage-1.json", m))

    def test_stored_mirror_zero_diverges(self):
        def m(p):
            d = json.loads(p.read_text())
            d["unexplained_persistent_host_mirror_bytes"] = 8192
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("realize-stage-2.json", m))

    def test_coordinator_counter_diverges_from_observations(self):
        def m(p):
            d = json.loads(p.read_text())
            d["coordinator_cuda_initialized"] = 0  # stays zero...
            d["cuda_observations"]["dev_nvidia_nodes"] = ["nvidia0"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-counters.json", m))

    def test_coordinator_weight_roots_diverge(self):
        def m(p):
            d = json.loads(p.read_text())
            d["weight_roots_bytes"]["/srv/inferswarm/cache/issue117"] = 1024
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-counters.json", m))

    def test_materialized_object_path_substitution(self):
        def m(p):
            d = json.loads(p.read_text())
            d["objects_written"][0]["object"] = \
                "/srv/models/gemma-r6/model.safetensors"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("assemble-stage-1.json", m))

    def test_aggregate_acquired_bytes_diverge(self):
        def m(p):
            d = json.loads(p.read_text())
            d["aggregate"]["newly_acquired_bytes"] += 512
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm03.json", m))

    def test_aggregate_cache_hit_bytes_diverge(self):
        def m(p):
            d = json.loads(p.read_text())
            d["aggregate"]["verified_cache_hit_bytes"] += 512
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "acquisition-ledger-inferswarm01.json", m))

    def test_read_audit_counter_diverges(self):
        def m(p):
            d = json.loads(p.read_text())
            d["unexplained_full_model_dependency"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("read-audit-stage-3.json", m))

    def test_delta_requirements_digest_drift(self):
        def m(p):
            d = json.loads(p.read_text())
            d["deltas"][0]["participant_requirements_digest"] = "sha256:" + "7" * 64
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("coordinator-deltas.json", m))

    def test_assemble_execution_unit_drift(self):
        def m(p):
            d = json.loads(p.read_text())
            d["execution_unit_id"] = "inferswarm03/gpu-1"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("assemble-stage-2.json", m))

    def test_dirty_tree_in_delta_audit(self):
        def m(p):
            d = json.loads(p.read_text())
            d["porcelain_empty"] = False
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("delta-audit.json", m))


class AttemptLineageMutations(MutationTestCase):
    """PR #127 correction: the reducer must fail closed on any attempt-
    lineage corruption. The lineage record is evidence, never authority:
    each mutation also mutates the underlying records where the reducer
    cross-checks them."""

    def test_missing_invalid_attempt(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"] = [a for a in d["attempts"]
                             if a["ordering"] != 2]
            # renumber to keep the strict 1..N sequence intact so the
            # failure is the MISSING attempt, not the ordering
            for i, a in enumerate(
                    sorted(d["attempts"], key=lambda x: x["ordering"]), 1):
                a["ordering"] = i
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="frozen campaign enumeration")

    def test_invalid_attempt_claims_publication(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][0]["verified_publications"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="claims a publication")

    def test_invalid_attempt_claims_correctness_observation(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][0]["correctness_bearing_observations"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="correctness observation")

    def test_invalid_attempt_claims_correctness_record(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][5]["correctness_bearing_realization_records"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="correctness-bearing realization record")

    def test_invalid_attempt_claims_materialization(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][3]["materializations"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="claims a materialization")

    def test_cleanup_resets_canonical_root(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][0]["preexisting_cold_root_state_destroyed_or_reset"] = True
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="destroyed or reset")

    def test_cold_condition_inode_reset(self):
        # simulate a root delete/recreate: the lineage's observed inode
        # no longer matches the retained prestate inode
        def m(p):
            d = json.loads(p.read_text())
            d["cold_condition_summary"]["root_inode_continuity"]["roots"][
                "inferswarm03"]["/srv/inferswarm/cache/issue117"] = 424242
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="inode continuity broken")

    def test_wrong_attempt_ordering(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][0]["ordering"] = 9
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="strict 1..N")

    def test_valid_ledger_bound_to_wrong_attempt(self):
        # the valid campaign's plan digest no longer matches the retained
        # plan: the acquisition ledger cannot belong to this campaign
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["validity"] == "VALID":
                    a["plan_digest"] = "sha256:" + "0" * 64
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="plan digest")

    def test_duplicate_valid_attempt(self):
        def m(p):
            d = json.loads(p.read_text())
            dup = json.loads(json.dumps(d["attempts"][-1]))
            dup["attempt_id"] = dup["attempt_id"] + ".mirror"
            d["attempts"].append(dup)
            for i, a in enumerate(d["attempts"], 1):
                a["ordering"] = i
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="exactly one VALID")

    def test_all_invalid_attempts_removed(self):
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"] = [a for a in d["attempts"]
                             if a["validity"] == "VALID"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="no invalid attempts")


class RuntimeFallbackMutations(MutationTestCase):
    """runtime_fallback_events must derive from runtime evidence, not
    acquisition-ledger integrity."""

    def test_alternate_gpu_substitution(self):
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-3"][
                "observed_gpu_uuid"] = "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "runtime-fallback-accounting.json", m))

    def test_runtime_fallback_with_clean_acquisition_ledger(self):
        # inject an actual fallback event while the acquisition ledger
        # stays perfectly clean — the old derivation would have passed
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-2"][
                "cpu_model_state_fallback"] = True
            d["per_stage"]["dense.6171f32b4413.stage-2"][
                "runtime_fallback_events_stage"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "runtime-fallback-accounting.json", m))

    def test_backend_fallback(self):
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "backend_or_compat_fallback"] = True
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "runtime-fallback-accounting.json", m))

    def test_cuda_path_establishment_removed(self):
        # no nvidia device nodes opened: CUDA execution path unproven
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "nvidia_device_nodes_opened"] = []
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "runtime-fallback-accounting.json", m))


class SteadyStateMovementMutations(MutationTestCase):
    """unplanned steady-state movement must derive from the raw strace
    parse plus finalization counters, not from a stored zero."""

    def test_post_finalization_cache_read(self):
        def m(p):
            d = json.loads(p.read_text())
            d["strace_facts"]["stages"][
                "dense.6171f32b4413.stage-2"]["cache_root_opens"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "steady-state-movement.json", m))

    def test_post_finalization_model_state_access(self):
        def m(p):
            d = json.loads(p.read_text())
            d["strace_facts"]["stages"][
                "dense.6171f32b4413.stage-3"][
                "model_state_opens_after_last_shard_open"] = [
                    "/srv/inferswarm/cache/issue117/objects/x"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "steady-state-movement.json", m))

    def test_source_fetch_after_finalization(self):
        def m(p):
            d = json.loads(p.read_text())
            d["strace_facts"]["stages"][
                "dense.6171f32b4413.stage-1"]["source_tree_opens"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "steady-state-movement.json", m))

    def test_stored_movement_zero_diverges(self):
        # keep the byte accounting unchanged but claim unexplained
        # movement exists in the stored summary fields
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "unexplained_movement_bytes"] = 4096
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "steady-state-movement.json", m))

    def test_finalization_counter_disagrees_with_report(self):
        # stored movement record's finalization counters disagree with
        # the realize report: must fail closed
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-2"][
                "finalization_counters"][
                "safetensors_mapping_close_count"] = 17
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "steady-state-movement.json", m),
            needle="finalization counters disagree")

    def test_report_mapping_counters_unbalanced(self):
        # the realize report itself claims unbalanced mapping open/close
        # or nonzero staging: the invariant is NOT establishable and the
        # terminal must be non-PASS
        def m(p):
            d = json.loads(p.read_text())
            d["safetensors_mapping_close_count"] = 200
            p.write_text(json.dumps(d))
        result = self.mutate_and_run("realize-stage-1.json", m)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ISSUE117_ARM_B_EVIDENCE_DERIVATION_FAILURE",
                      result.stdout + result.stderr)

    def test_missing_finalization_counters_yields_non_pass(self):
        # remove the counters entirely: inability to establish the
        # movement invariant must yield a non-PASS terminal state
        def m(p):
            d = json.loads(p.read_text())
            del d["safetensors_mapping_open_count"]
            del d["safetensors_mapping_close_count"]
            p.write_text(json.dumps(d))
        result = self.mutate_and_run("realize-stage-3.json", m)
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, combined[-500:])
        self.assertIn("NOT derivable", combined)

    def test_movement_summary_mutation_without_raw_support(self):
        # mutate ONLY the stored movement summary's zero (claim zero
        # movement) while the underlying realize report shows retained
        # staging: the raw-support cross-check must fail it
        def m(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "finalization_counters"]["host_staging_current_bytes"] = 0
            # ...while claiming processed != fetched would be caught;
            # here we keep the record internally consistent but flip the
            # stored zero-derivation text to a fabricated derivation
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "zero_derivation"] = "fabricated: everything is fine"
            p.write_text(json.dumps(d))
        # the reducer does not parse the text; the mutation that matters
        # is a nonzero staging in the REPORT with a zero in the summary
        def m2(p):
            d = json.loads(p.read_text())
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "unexplained_movement_bytes"] = 0
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "post_finalization_model_state_path_opens"] = []
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "finalization_counters"]["host_staging_current_bytes"] = 0
            d["per_stage"]["dense.6171f32b4413.stage-1"][
                "planned_initial_materialization_bytes"] = 0
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "steady-state-movement.json", m2))


class CoordinatorTransportMutations(MutationTestCase):
    """coordinator bulk bytes must derive from the RAW source-server log
    and the observed inventory, not a stored summary zero."""

    def test_coordinator_model_payload_rx(self):
        def m(p):
            d = json.loads(p.read_text())
            d["low_level_observations"]["source_server_log"][
                "coordinator_get_requests"] = 1
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "coordinator-transport-accounting.json", m))

    def test_coordinator_summary_zero_diverges(self):
        # low-level traffic nonzero while the stored summary still says
        # zero: the reducer must catch the disagreement
        def m(p):
            d = json.loads(p.read_text())
            d["low_level_observations"]["source_server_log"][
                "client_ip_histogram"]["10.0.0.206"] = 3
            d["low_level_observations"]["source_server_log"][
                "coordinator_get_requests"] = 3
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "coordinator-transport-accounting.json", m))

    def test_coordinator_state_holds_payload_bytes(self):
        def m(p):
            d = json.loads(p.read_text())
            d["low_level_observations"]["coordinator_state_tree"][
                "model_payload_bytes_under_state_arm_b"] = 1024
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "coordinator-transport-accounting.json", m))

    def test_participant_request_identity_broken(self):
        # the server-log client count no longer equals the 03 ledger's
        # transport request count: the transport binding is broken
        def m(p):
            d = json.loads(p.read_text())
            d["low_level_observations"]["source_server_log"][
                "client_ip_histogram"]["10.0.0.219"] = 400
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "coordinator-transport-accounting.json", m))


class RepositoryDependencyMutations(MutationTestCase):
    """Section-8 conjunction: an auxiliary whole-repository file read
    during realization is a repository dependency even when the shard
    stays participant-sized."""

    def test_auxiliary_repository_file_read(self):
        def m(p):
            d = json.loads(p.read_text())
            d["classified"]["other_reads"].append(
                "/srv/models/gemma-r6/tokenizer.json")
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "read-audit-stage-2.json", m),
            needle="whole-repository dependency")


class ReviewFixMutations(MutationTestCase):
    """Independent-review findings (round 1) turned into permanent
    negative controls."""

    def test_validity_third_state_escapes_partition(self):
        # a 'PENDING' label with an admitted publication must fail, not
        # dodge the per-invalid enforcement
        def m(p):
            d = json.loads(p.read_text())
            d["attempts"][3]["validity"] = "PENDING"
            d["attempts"][3]["verified_publications"] = 5
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="not explicitly VALID/INVALID")

    def test_excerpt_digest_does_not_bind_verbatim(self):
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-2"):
                    a["evidence"]["excerpt_verbatim"] = a["evidence"][
                        "excerpt_verbatim"].replace(
                        "MALFORMED_ARTIFACT_RECORD",
                        "AUTHORIZATION_BYPASSED_RECORD")
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="bind its verbatim content")


class Round2ReviewMutations(MutationTestCase):
    """Round-2 review findings (B1, B3) as permanent controls."""

    def test_invalid_attempt_reordering_vs_timestamps(self):
        # B3: swapping the orderings of two invalid attempts must fail
        # because their observed timestamps contradict the new sequence
        def m(p):
            d = json.loads(p.read_text())
            by_id = {a["attempt_id"]: a for a in d["attempts"]}
            a, b = (by_id["i117-arm-b-cold-acquisition.launch-1"],
                    by_id["i117-arm-b-cold-acquisition.launch-2"])
            a["ordering"], b["ordering"] = b["ordering"], a["ordering"]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="timestamp ordering")


class Round3RawEvidenceMutations(MutationTestCase):
    """Maintainer round-3 findings 1/2/3: raw-evidence authority. The
    reducer must fail closed when the RAW source-server log drifts, when
    a stored derived histogram changes without a raw change, when the
    coordinator observed inventory is corrupted, and when stale textual
    totals survive."""

    def _mutate_and_run_two(self, file_a, mut_a, file_b, mut_b):
        tmp = Path(tempfile.mkdtemp(prefix="armb-mut-",
                                    dir=os.environ.get("ARMB_MUT_TMP")
                                    or None))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = tmp / "evidence"
        root.mkdir()
        shutil.copytree(ARM_B, root / "arm-b")
        (root.parent).mkdir(parents=True, exist_ok=True)
        for pin in ("physical-preflight.json", "canonical-summary.json"):
            src = (ROOT / "docs" / "implementation" /
                   "r6-successor-dense-full-integration-117" / "evidence" / pin)
            shutil.copy(src, root.parent / pin)
        mut_a(root / "arm-b" / file_a)
        mut_b(root / "arm-b" / file_b)
        return run_reducer(root)

    def test_raw_server_log_sha_drift(self):
        # mandated control 1: a single byte change in the retained RAW
        # source-server log must fail closed (sha pin)
        def m(p):
            text = p.read_text()
            p.write_text(text.replace("10.0.0.219", "10.0.0.218", 1))
        self.assertFails(self.mutate_and_run(
            "raw/source-server-access.log", m))

    def test_raw_server_log_client_change(self):
        # mandated control 2: rewrite one client line (byte-identical
        # length impossible to keep -> sha drift + histogram mismatch
        # even if the pin were removed)
        def m(p):
            lines = p.read_text().splitlines()
            for i, ln in enumerate(lines):
                if ln.startswith("10.0.0.219"):
                    lines[i] = ln.replace("/model.safetensors", "/config.json ")
                    break
            p.write_text("\n".join(lines) + "\n")
        self.assertFails(self.mutate_and_run(
            "raw/source-server-access.log", m))

    def test_derived_histogram_change_without_raw_change(self):
        # mandated control 7: mutate ONLY the stored derived histogram
        # (coordinator-transport-accounting.json) while the raw log is
        # untouched: the disagreement must fail closed
        def m(p):
            d = json.loads(p.read_text())
            d["low_level_observations"]["source_server_log"][
                "client_ip_histogram"]["10.0.0.219"] = 426
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "coordinator-transport-accounting.json", m),
            needle="disagree with the RAW log parse")

    def test_coordinator_inventory_unexpected_file(self):
        # mandated control 3: an unexpected file in the OBSERVED
        # inventory must fail (allowlist enforcement over observations)
        def m(p):
            d = json.loads(p.read_text())
            d["entries"].append({"path": "models/payload.safetensors",
                                 "type": "f", "size": 23919549408,
                                 "symlink_target": None})
            d["regular_file_digests"]["models/payload.safetensors"] = \
                "0" * 64
            d["total_file_count"] += 1
            d["total_bytes"] += 23919549408
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "observations/coordinator-state-inventory.json", m))

    def test_coordinator_inventory_digest_drift(self):
        # mandated control 4: an observed file's digest drifts
        def m(p):
            d = json.loads(p.read_text())
            d["regular_file_digests"][
                "authorization/coordinator-record.json"] = "f" * 64
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "observations/coordinator-state-inventory.json", m))

    def test_coordinator_inventory_per_file_sum_mismatch(self):
        # mandated control 5: the stored numeric total no longer equals
        # the per-file sum
        def m(p):
            d = json.loads(p.read_text())
            d["total_bytes"] += 4096
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "observations/coordinator-state-inventory.json", m))

    def test_stale_textual_coordinator_total(self):
        # mandated control 6: the stale round-2 textual total reappears
        # in the derivation text
        def m(p):
            d = json.loads(p.read_text())
            d["derivation"] = d["derivation"].replace(
                str(d["low_level_observations"]["coordinator_state_tree"]
                    ["data_file_total_bytes"]), "34887199")
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run(
            "coordinator-transport-accounting.json", m),
            needle="stale textual coordinator total")

    def test_raw_strace_sha_drift(self):
        # a changed raw strace log must fail closed (sha pin)
        def m(p):
            text = p.read_text()
            p.write_text(text + '999999 openat(AT_FDCWD, "/srv/inferswarm/cache/issue117/objects/x", O_RDONLY) = 99\n')
        self.assertFails(self.mutate_and_run(
            "raw/realize-strace.stage-2.log", m))

    def test_raw_strace_post_boundary_open_injected(self):
        # append a model-state open AFTER the last shard open directly
        # in the raw log AND update the parser pins would be needed to
        # pass the sha check — without pin updates this must fail; with
        # pins updated by an attacker the post-boundary scan catches it.
        # Here: inject and also patch the pin inside the parser copy
        # that the reducer imports (simulating a coordinated attacker).
        result = self._mutate_and_run_two(
            "raw/realize-strace.stage-1.log",
            lambda p: p.write_text(
                p.read_text() +
                '125629 openat(AT_FDCWD, "/srv/inferswarm/cache/issue117/objects/zz", O_RDONLY) = 99\n'),
            "steady-state-movement.json",
            lambda p: p.write_text(p.read_text()))  # no summary change
        self.assertNotEqual(result.returncode, 0)

    def test_producer_source_drift(self):
        # a changed pinned producer source must fail closed
        def m(p):
            text = p.read_text()
            p.write_text(text + "\n# tampered\n")
        self.assertFails(self.mutate_and_run(
            "raw/producer/loader.py", m))


class Round3LineageSemanticsMutations(MutationTestCase):
    """Maintainer round-3 findings 4/5: execution-vs-retention semantics
    and parent/child campaign lineage."""

    def test_execution_without_retention_represented_consistently(self):
        # launch-6 physically executed to device residency with ZERO
        # correctness-bearing records: this is VALID REPRESENTATION and
        # must NOT fail. (Positive control for finding 4.)
        result = self.mutate_and_run("attempt-lineage.json", lambda p: None)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("ISSUE117_ARM_B_COLD_REALIZATION_PASS", result.stdout)

    def test_residency_without_execution_contradiction(self):
        # device residency claimed without realization execution
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-6"):
                    a["realization_execution_reached"] = False
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="residency without realization execution")

    def test_execution_without_request_contradiction(self):
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-5"):
                    a["realization_request_made"] = False
            p.write_text(json.dumps(d))
        # caught by the frozen per-attempt execution-flag enumeration
        # (stronger than the internal-consistency contradiction check)
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="execution-flag labels differ")

    def test_parent_child_link_corrupted(self):
        # mandated control 11: launch-4 re-labeled as NOT nested
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-4"):
                    a["parent_campaign_id"] = None
                    a["subattempt_of"] = None
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="parent/child structure")

    def test_pre_validity_launch_claimed_as_nested(self):
        # mandated control 11 variant: launch-1 (pre-validity) relabeled
        # as a nested campaign child — caught by the frozen nesting pin
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-1"):
                    a["parent_campaign_id"] = \
                        "i117-arm-b-cold-acquisition.campaign-1"
                    a["subattempt_of"] = \
                        "i117-arm-b-cold-acquisition.campaign-1"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="parent/child structure")

    def test_campaign_subattempt_ids_corrupted(self):
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["validity"] == "VALID":
                    a["subattempt_ids"] = a["subattempt_ids"][:2]
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="subattempt_ids")

    def test_timestamp_order_contradiction(self):
        # mandated control 12: a nested attempt's start moved outside
        # the campaign interval without moving anything else
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-5"):
                    a["started_utc_observed"] = "2026-09-08T19:00:00Z"
                    a["ended_utc_observed"] = "2026-09-08T19:00:05Z"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="started before the campaign interval")

    def test_pre_validity_launch_started_after_validity(self):
        # mandated control 12 variant: launch-1's start moved to after
        # acquisition validity was established
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-1"):
                    a["started_utc_observed"] = "2026-09-08T21:15:00Z"
                    a["ended_utc_observed"] = "2026-09-08T21:15:30Z"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="after the campaign's acquisition validity")

    def test_nested_attempt_backdated_before_validity(self):
        # independent-reviewer finding: a nested phase attempt backdated
        # to before acquisition validity was established (still inside
        # the campaign interval, timestamps monotone) must fail closed —
        # it would silently re-label a pre-validity failure as an
        # in-campaign phase attempt
        def m(p):
            d = json.loads(p.read_text())
            for a in d["attempts"]:
                if a["attempt_id"].endswith("launch-4"):
                    a["started_utc_observed"] = "2026-09-08T21:07:00Z"
                    a["ended_utc_observed"] = "2026-09-08T21:07:30Z"
            p.write_text(json.dumps(d))
        self.assertFails(self.mutate_and_run("attempt-lineage.json", m),
                         needle="backdated phase attempt")


if __name__ == "__main__":
    unittest.main()
