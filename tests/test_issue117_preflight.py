"""Focused tests for the issue #117 physical preflight validator."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_applicability as applicability  # noqa: E402
import issue117_gemma_strategy as strategy  # noqa: E402
import issue117_preflight as preflight  # noqa: E402
from issue99_artifact_core import self_digest  # noqa: E402


def build_valid_preflight(**overrides) -> dict:
    nodes = [
        {"node": "inferswarm01", "gpu_uuid": "GPU-aaaa", "gpu_product": "NVIDIA GeForce RTX 3060",
         "compute_capability": "8.9", **MODEL_BACKEND},
        {"node": "inferswarm03", "gpu_uuid": "GPU-bbbb", "gpu_product": "NVIDIA GeForce RTX 3060",
         "compute_capability": "8.9", **MODEL_BACKEND},
        {"node": "inferswarm04", "gpu_uuid": "GPU-cccc", "gpu_product": "NVIDIA GeForce RTX 3090",
         "compute_capability": "8.9", **MODEL_BACKEND},
    ]
    candidates = [{
        "candidate_id": "dense.v5candidate0000",
        "stage_structure": [dict(stage) for stage in strategy.ACCEPTED_V5_GEOMETRY],
    }, {
        "candidate_id": "dense.othercandidate00",
        "stage_structure": [{"cu_id": "inferswarm04/gpu-0", "layer_start": 0,
                             "layer_end": 48}],
    }]
    applicability_entries = [
        {"candidate_id": "dense.v5candidate0000",
         "applicability": "QUALIFICATION_APPLICABLE"},
        {"candidate_id": "dense.othercandidate00",
         "applicability": "QUALIFICATION_NOT_APPLICABLE"},
    ]
    fields = dict(
        inferswarm_head="a" * 40,
        inferswarm_clean_worktree=True,
        freetoken_integration_producer="b" * 40,
        freetoken_clean_worktree=True,
        v5_authority_sha256=dict(applicability.V5_AUTHORITY_FILES),
        nodes=nodes,
        candidate_set={"candidates": candidates},
        qualification_applicability=applicability_entries,
        applicability_audit_digest=applicability.canonical_issue117_audit()["audit_digest"],
        applicability_audit_result=applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY,
        fixture_digest="sha256:" + "c" * 64,
        source_descriptors={"descriptors": [{"source_id": "origin-1"}],
                            "descriptors_digest": "sha256:" + "d" * 64},
        cold_cache_proofs=[
            {"participant_id": "p1", "cache_root": "/srv/inferswarm/cache/issue117",
             "materialized_root": "/srv/inferswarm/materialized/issue117",
             "cache_entry_count": 0, "cache_bytes": 0,
             "materialized_entry_count": 0, "materialized_bytes": 0,
             "no_symlink_alias": True, "source_possession_separate": True},
            {"participant_id": "p2", "cache_root": "/srv/inferswarm/cache/issue117",
             "materialized_root": "/srv/inferswarm/materialized/issue117",
             "cache_entry_count": 0, "cache_bytes": 0,
             "materialized_entry_count": 0, "materialized_bytes": 0,
             "no_symlink_alias": True, "source_possession_separate": True},
        ],
    )
    fields.update(overrides)
    return preflight.build_preflight(**fields)


MODEL_BACKEND = {key: strategy.MODEL_SUBJECT["backend"][key]
                 for key in preflight.REQUIRED_BACKEND_KEYS}


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.valid = build_valid_preflight()

    def test_valid_preflight_passes(self):
        self.assertEqual(preflight.validate_preflight(self.valid, repo_root=ROOT), [])

    def test_valid_preflight_is_deterministic(self):
        self.assertEqual(self.valid, build_valid_preflight())

    def test_missing_field_fails(self):
        broken = json.loads(json.dumps(self.valid))
        del broken["integration_fixture_digest"]
        # rebuild without the digest field: simulate by tampering post-hoc
        broken["preflight_digest"] = preflight._self_digest(broken)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("fixture" in failure for failure in failures))

    def test_sha_fields_must_be_real_shas(self):
        broken = build_valid_preflight(inferswarm_head="main")
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("inferswarm_head" in failure for failure in failures))

    def test_dirty_worktree_fails(self):
        broken = build_valid_preflight(inferswarm_clean_worktree=False)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("worktree" in failure for failure in failures))

    def test_drifted_authority_pin_fails(self):
        pins = dict(applicability.V5_AUTHORITY_FILES)
        relative = "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"
        pins[relative] = "0" * 64
        broken = build_valid_preflight(v5_authority_sha256=pins)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("authority" in failure for failure in failures))

    def test_backend_drift_fails(self):
        nodes = json.loads(json.dumps(build_valid_preflight()["nodes"]))
        nodes[0]["torch"] = "2.4.0"
        broken = build_valid_preflight(nodes=nodes)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("torch drift" in failure for failure in failures))

    def test_nonzero_coordinator_invariant_fails(self):
        broken = build_valid_preflight()
        broken["resource_identity"]["coordinator_model_weight_bytes_received"] = 1024
        broken["preflight_digest"] = preflight._self_digest(broken)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("coordinator_model_weight_bytes_received" in failure
                            for failure in failures))

    def test_missing_v5_geometry_in_candidate_set_fails(self):
        candidates = [{
            "candidate_id": "dense.othercandidate00",
            "stage_structure": [{"cu_id": "inferswarm04/gpu-0", "layer_start": 0,
                                 "layer_end": 48}],
        }]
        applicability_entries = [
            {"candidate_id": "dense.othercandidate00",
             "applicability": "QUALIFICATION_NOT_APPLICABLE"}]
        broken = build_valid_preflight(
            candidate_set={"candidates": candidates},
            qualification_applicability=applicability_entries)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("V5 geometry" in failure for failure in failures))

    def test_v5_candidate_must_resolve_applicable(self):
        candidates = [{
            "candidate_id": "dense.v5candidate0000",
            "stage_structure": [dict(stage) for stage in strategy.ACCEPTED_V5_GEOMETRY],
        }]
        applicability_entries = [
            {"candidate_id": "dense.v5candidate0000",
             "applicability": "QUALIFICATION_NOT_APPLICABLE"}]
        broken = build_valid_preflight(
            candidate_set={"candidates": candidates},
            qualification_applicability=applicability_entries)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("QUALIFICATION_APPLICABLE" in failure for failure in failures))

    def test_wrong_audit_result_fails(self):
        broken = build_valid_preflight(
            applicability_audit_result="R6_SUCCESSOR_REQUALIFICATION_REQUIRED")
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("audit" in failure for failure in failures))

    def test_fixture_digest_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture_path = Path(temp) / "fixture.json"
            fixture_document = {
                "schema": "inferswarm.issue117.integration-fixture/1",
                "fixture_digest": "sha256:" + "e" * 64,
            }
            fixture_path.write_text(json.dumps(fixture_document))
            failures = preflight.validate_preflight(
                self.valid, repo_root=ROOT, fixture_path=fixture_path)
            self.assertTrue(any("fixture digest mismatch" in failure
                                for failure in failures))
            good = build_valid_preflight(
                fixture_digest="sha256:" + "e" * 64)
            self.assertEqual(
                preflight.validate_preflight(good, repo_root=ROOT,
                                             fixture_path=fixture_path), [])

    def test_nonzero_cold_cache_fails(self):
        proofs = json.loads(json.dumps(build_valid_preflight()["cold_cache_proofs"]))
        proofs[0]["cache_bytes"] = 24_000_000_000
        broken = build_valid_preflight(cold_cache_proofs=proofs)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("cache_bytes" in failure for failure in failures))

    def test_symlink_alias_without_proof_fails(self):
        proofs = json.loads(json.dumps(build_valid_preflight()["cold_cache_proofs"]))
        proofs[1]["no_symlink_alias"] = False
        broken = build_valid_preflight(cold_cache_proofs=proofs)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("symlink" in failure for failure in failures))

    def test_require_raises_with_all_failures(self):
        broken = build_valid_preflight(inferswarm_clean_worktree=False,
                                       freetoken_clean_worktree=False)
        with self.assertRaises(preflight.PreflightBlocked) as context:
            preflight.require_preflight_valid(broken, repo_root=ROOT)
        self.assertIn("worktree", str(context.exception))


if __name__ == "__main__":
    unittest.main()
