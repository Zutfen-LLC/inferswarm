"""Focused tests for the issue #117 physical preflight validator."""
import json
import shutil
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

MODEL_BACKEND = {key: strategy.MODEL_SUBJECT["backend"][key]
                 for key in preflight.REQUIRED_BACKEND_KEYS}


def collected_proofs(temp: Path, *, participants=("stage-1", "stage-2", "stage-3")):
    """Mechanically collect cold-cache proofs against empty dedicated roots."""
    proofs = []
    for participant in participants:
        cache = temp / f"cache-{participant}"
        materialized = temp / f"materialized-{participant}"
        cache.mkdir(parents=True, exist_ok=True)
        materialized.mkdir(parents=True, exist_ok=True)
        proofs.append(preflight.collect_cold_cache_proof(
            participant_id=participant, cache_root=cache,
            materialized_root=materialized))
    return proofs


def physical_compute_units(**overrides_per_cu):
    """Per-CU records carrying the exact retained identities (fabric form)."""
    records = []
    for cu in applicability.ACCEPTED_COMPUTE_UNITS:
        record = {
            "cu_id": cu["cu_id"],
            "node": cu["node"],
            "gpu_index": cu["gpu_index"],
            "gpu_uuid": cu["gpu_uuid"],
            "gpu_product": cu["product"],
            "compute_capability": cu["compute_capability"],
            "role": next(snapshot["role"] for snapshot
                         in strategy.RESOURCE_SNAPSHOT["compute_units"]
                         if snapshot["cu_id"] == cu["cu_id"]),
            "runtime": dict(MODEL_BACKEND),
            "node_identity": {"node_id": cu["node"],
                              "node_fingerprint": "f" * 64},
        }
        record.update(overrides_per_cu.get(cu["cu_id"], {}))
        records.append(record)
    return records


def candidate_set_document():
    from issue74_methodology import canonical_json_bytes
    from issue99_artifact_core import digest_of_bytes
    candidates = [{
        "candidate_id": "dense.v5candidate0000",
        "stage_structure": [dict(stage) for stage in strategy.ACCEPTED_V5_GEOMETRY],
        "qualification_subject": {"opaque": "v5-subject"},
        "qualification_subject_digest": digest_of_bytes(
            canonical_json_bytes({"opaque": "v5-subject"})),
    }, {
        "candidate_id": "dense.othercandidate00",
        "stage_structure": [{"cu_id": "inferswarm04/gpu-0", "layer_start": 0,
                             "layer_end": 48}],
        "qualification_subject": {"opaque": "other-subject"},
        "qualification_subject_digest": digest_of_bytes(
            canonical_json_bytes({"opaque": "other-subject"})),
    }]
    return {"candidates": candidates,
            "candidate_set_digest": preflight.candidate_set_digest(candidates)}


def applicability_entries():
    entries = [
        {"candidate_id": "dense.v5candidate0000",
         "applicability": "QUALIFICATION_APPLICABLE"},
        {"candidate_id": "dense.othercandidate00",
         "applicability": "QUALIFICATION_NOT_APPLICABLE"},
    ]
    for entry in entries:
        entry["record_digest"] = self_digest(entry, identity_field="record_digest")
    return entries


COMMITTED_FIXTURE = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
                     / "evidence" / "integration-fixture.json")


def build_valid_preflight(temp: Path | None = None, **overrides) -> dict:
    temp = temp or Path(tempfile.mkdtemp(prefix="issue117-preflight-"))
    fields = dict(
        inferswarm_head="a" * 40,
        inferswarm_clean_worktree=True,
        freetoken_integration_producer=applicability.FROZEN_INTEGRATION_PRODUCER,
        freetoken_clean_worktree=True,
        v5_authority_sha256={**applicability.V5_AUTHORITY_FILES,
                             **applicability.ACCEPTED_PHYSICAL_IDENTITY_FILES},
        compute_units=physical_compute_units(),
        candidate_set=candidate_set_document(),
        qualification_applicability=applicability_entries(),
        applicability_audit_digest=applicability.canonical_issue117_audit()["audit_digest"],
        applicability_audit_result=applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY,
        fixture_digest=json.loads(COMMITTED_FIXTURE.read_text())["fixture_digest"],
        source_descriptors={
            "descriptors": [{"source_id": "origin-1",
                             "endpoint": "file:///srv/models/checkpoint"}],
            "descriptors_digest": preflight.source_descriptors_digest(
                [{"source_id": "origin-1",
                  "endpoint": "file:///srv/models/checkpoint"}])},
        cold_cache_proofs=collected_proofs(temp),
        source_possession_roots=["/srv/models/source-possession"],
    )
    fields.update(overrides)
    return preflight.build_preflight(**fields)


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-preflight-valid-")
        cls.valid = build_valid_preflight(Path(cls.temp.name))

    def test_valid_preflight_passes(self):
        self.assertEqual(preflight.validate_preflight(self.valid, repo_root=ROOT), [])

    def test_valid_preflight_is_deterministic(self):
        import re
        def normalize(value):
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()
                        if not key.endswith("_digest")}
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if isinstance(value, str):
                return re.sub(r"/tmp/[^/\"]+", "<temporary>", value)
            return value
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual(normalize(self.valid),
                             normalize(build_valid_preflight(Path(other))))

    def test_random_integration_producer_fails(self):
        # a syntactically valid but wrong producer SHA cannot inherit the
        # frozen applicability audit
        broken = build_valid_preflight(
            freetoken_integration_producer="b" * 40)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("exact producer" in failure for failure in failures))

    def test_missing_field_fails(self):
        broken = json.loads(json.dumps(self.valid))
        del broken["integration_fixture_digest"]
        broken["preflight_digest"] = preflight._self_digest(broken)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("fixture" in failure for failure in failures))

    def test_sha_fields_must_be_real_shas(self):
        broken = build_valid_preflight(self.valid and Path(self.temp.name),
                                       inferswarm_head="main")
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("inferswarm_head" in failure for failure in failures))

    def test_dirty_worktree_fails(self):
        broken = build_valid_preflight(inferswarm_clean_worktree=False)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("worktree" in failure for failure in failures))

    def test_drifted_authority_pin_fails(self):
        pins = {**applicability.V5_AUTHORITY_FILES,
                **applicability.ACCEPTED_PHYSICAL_IDENTITY_FILES}
        relative = "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"
        pins[relative] = "0" * 64
        broken = build_valid_preflight(v5_authority_sha256=pins)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("authority" in failure for failure in failures))

    def test_runtime_drift_fails(self):
        units = physical_compute_units()
        units[0]["runtime"] = {**MODEL_BACKEND, "torch": "2.4.0"}
        broken = build_valid_preflight(compute_units=units)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("torch drift" in failure for failure in failures))

    def test_nonzero_coordinator_observation_fails(self):
        # the coordinator counters are fabric-collected builder inputs, not
        # constants; a nonzero observation is recorded and then refused
        broken = build_valid_preflight(
            coordinator_model_weight_bytes_received=1024)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("coordinator_model_weight_bytes_received" in failure
                            for failure in failures))

    def test_unbound_node_identity_fails(self):
        units = physical_compute_units()
        units[0]["node_identity"] = {"node_id": units[0]["node"]}
        broken = build_valid_preflight(compute_units=units)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("node_fingerprint" in failure for failure in failures))

    def test_fixture_validation_is_mandatory(self):
        # even with no explicit fixture path the committed fixture is fully
        # validated: a record binding a bogus digest cannot pass
        broken = build_valid_preflight(fixture_digest="sha256:" + "c" * 64)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("fixture digest mismatch" in failure
                            for failure in failures))

    def test_missing_v5_geometry_in_candidate_set_fails(self):
        from issue74_methodology import canonical_json_bytes
        from issue99_artifact_core import digest_of_bytes
        subject = {"opaque": "other"}
        candidates = [{
            "candidate_id": "dense.othercandidate00",
            "stage_structure": [{"cu_id": "inferswarm04/gpu-0", "layer_start": 0,
                                 "layer_end": 48}],
            "qualification_subject": subject,
            "qualification_subject_digest": digest_of_bytes(canonical_json_bytes(subject)),
        }]
        entries = [{"candidate_id": "dense.othercandidate00",
                    "applicability": "QUALIFICATION_NOT_APPLICABLE",
                    "record_digest": self_digest(
                        {"candidate_id": "dense.othercandidate00",
                         "applicability": "QUALIFICATION_NOT_APPLICABLE"},
                        identity_field="record_digest")}]
        broken = build_valid_preflight(
            candidate_set={"candidates": candidates,
                           "candidate_set_digest": preflight.candidate_set_digest(candidates)},
            qualification_applicability=entries)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("V5 geometry" in failure for failure in failures))

    def test_v5_candidate_must_resolve_applicable(self):
        document = candidate_set_document()
        document["candidates"][0]["stage_structure"] = [
            dict(stage) for stage in strategy.ACCEPTED_V5_GEOMETRY]
        document["candidate_set_digest"] = preflight.candidate_set_digest(
            document["candidates"])
        entries = applicability_entries()
        entries[0] = {"candidate_id": "dense.v5candidate0000",
                      "applicability": "QUALIFICATION_NOT_APPLICABLE"}
        entries[0]["record_digest"] = self_digest(
            {k: v for k, v in entries[0].items() if k != "record_digest"},
            identity_field="record_digest")
        broken = build_valid_preflight(candidate_set=document,
                                       qualification_applicability=entries)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("QUALIFICATION_APPLICABLE" in failure for failure in failures))

    def test_tampered_applicability_record_is_not_digest_bound(self):
        entries = applicability_entries()
        entries[0]["applicability"] = "QUALIFICATION_NOT_APPLICABLE"
        broken = build_valid_preflight(qualification_applicability=entries)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("digest-bound" in failure for failure in failures))

    def test_lying_candidate_subject_digest_fails(self):
        document = candidate_set_document()
        document["candidates"][0]["qualification_subject_digest"] = "sha256:" + "9" * 64
        broken = build_valid_preflight(candidate_set=document)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("does not recompute" in failure for failure in failures))

    def test_wrong_audit_result_fails(self):
        broken = build_valid_preflight(
            applicability_audit_result="R6_SUCCESSOR_REQUALIFICATION_REQUIRED")
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("audit" in failure for failure in failures))

    def test_fixture_validation_is_full_not_digest_only(self):
        fixture_path = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
                        / "evidence" / "integration-fixture.json")
        document = json.loads(fixture_path.read_text())
        good = build_valid_preflight(fixture_digest=document["fixture_digest"])
        self.assertEqual(
            preflight.validate_preflight(good, repo_root=ROOT,
                                         fixture_path=fixture_path), [])
        tampered = json.loads(json.dumps(document))
        tampered["cases"][0]["case"]["prompt_text"] += " tampered"
        tampered_path = Path(self.temp.name) / "tampered-fixture.json"
        tampered_path.write_text(json.dumps(tampered))
        failures = preflight.validate_preflight(good, repo_root=ROOT,
                                                fixture_path=tampered_path)
        self.assertTrue(any("fixture validation failed" in failure
                            for failure in failures))

    def test_planted_cache_file_fails_cold_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            planted = root / "cache-stage-1" / "object.bin"
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_bytes(b"x" * 128)
            proofs = collected_proofs(root)
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = preflight.validate_preflight(broken, repo_root=ROOT)
            self.assertTrue(any("not empty" in failure for failure in failures))

    def test_collected_proof_rejects_boolean_shortcuts(self):
        legacy = [{"participant_id": "p1", "cache_root": "/srv/cache",
                   "materialized_root": "/srv/materialized",
                   "cache_entry_count": 0, "cache_bytes": 0,
                   "no_symlink_alias": True, "source_possession_separate": True}]
        broken = build_valid_preflight(cold_cache_proofs=legacy)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("mechanically collected" in failure for failure in failures))

    def test_symlink_in_collected_facts_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cache-stage-1").mkdir(parents=True, exist_ok=True)
            (root / "cache-stage-1" / "alias").symlink_to("/srv/models")
            proofs = collected_proofs(root)
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = preflight.validate_preflight(broken, repo_root=ROOT)
            self.assertTrue(any("symlink" in failure for failure in failures))

    def test_tampered_proof_digest_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            proofs = collected_proofs(Path(temp))
            proofs[0]["cache_facts"]["entry_count"] = 5
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = preflight.validate_preflight(broken, repo_root=ROOT)
            self.assertTrue(any(
                "entry_count" in failure or "self-identity" in failure
                for failure in failures))

    def test_source_possession_must_be_disjoint(self):
        with tempfile.TemporaryDirectory() as temp:
            proofs = collected_proofs(Path(temp))
            broken = build_valid_preflight(
                cold_cache_proofs=proofs,
                source_possession_roots=[str(Path(temp) / "cache-stage-1")])
            failures = preflight.validate_preflight(broken, repo_root=ROOT)
            self.assertTrue(any("not separate" in failure for failure in failures))

    def test_require_raises_with_all_failures(self):
        broken = build_valid_preflight(inferswarm_clean_worktree=False,
                                       freetoken_clean_worktree=False)
        with self.assertRaises(preflight.PreflightBlocked) as context:
            preflight.require_preflight_valid(broken, repo_root=ROOT)
        self.assertIn("worktree", str(context.exception))


class ComputeUnitIdentityTests(unittest.TestCase):
    """P0-5: the physical record binds each Compute Unit independently."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-preflight-cu-")
        cls.valid = build_valid_preflight(Path(cls.temp.name))

    def test_both_inferswarm01_gpus_are_bound_separately(self):
        cu_ids = [record["cu_id"] for record in self.valid["compute_units"]]
        self.assertIn("inferswarm01/gpu-0", cu_ids)
        self.assertIn("inferswarm01/gpu-1", cu_ids)
        uuids = {record["cu_id"]: record["gpu_uuid"]
                 for record in self.valid["compute_units"]}
        self.assertNotEqual(uuids["inferswarm01/gpu-0"], uuids["inferswarm01/gpu-1"])

    def test_wrong_uuid_fails(self):
        units = physical_compute_units()
        units[1]["gpu_uuid"] = "GPU-00000000-0000-0000-0000-000000000000"
        broken = build_valid_preflight(compute_units=units)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("inferswarm01/gpu-1" in failure and "gpu_uuid" in failure
                            for failure in failures))

    def test_fabricated_compute_capability_fails(self):
        # "8.9" is not the retained measured identity for a 3060/3090
        for fabricated in ("8.9", "9.0", "8.6 "):
            units = physical_compute_units()
            units[0]["compute_capability"] = fabricated.strip() + (
                "" if fabricated.endswith(" ") else "")
            units[0]["compute_capability"] = fabricated
            broken = build_valid_preflight(compute_units=units)
            failures = preflight.validate_preflight(broken, repo_root=ROOT)
            self.assertTrue(any("compute_capability" in failure for failure in failures),
                             fabricated)

    def test_wrong_product_fails(self):
        units = physical_compute_units()
        units[3]["gpu_product"] = "NVIDIA GeForce RTX 4090"
        broken = build_valid_preflight(compute_units=units)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("gpu_product" in failure for failure in failures))

    def test_one_record_per_node_is_not_enough(self):
        # dropping the second inferswarm01 GPU leaves a CU unbound
        units = [record for record in physical_compute_units()
                 if record["cu_id"] != "inferswarm01/gpu-1"]
        broken = build_valid_preflight(compute_units=units)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("exactly one Compute Unit record" in failure
                            for failure in failures))

    def test_accepted_units_match_the_pinned_evidence_files(self):
        # mechanical cross-check: the frozen per-CU identities are exactly
        # what the pinned retained evidence files record
        v2 = json.loads((ROOT / "docs/qualification/gemma4-12b-it-v2-campaign-81"
                         / "preflight-applicability.json").read_text())
        by_uuid = {}
        for node, node_record in v2["nodes"].items():
            for gpu in node_record.get("gpu", []):
                by_uuid[gpu["uuid"]] = (node, gpu)
        v4 = json.loads((ROOT / "docs/qualification/gemma4-12b-it-v4-campaign-97"
                         / "EXECUTION-AUTHORITY.json").read_text())
        v4_by_uuid = {entry["gpu_uuid"]: entry for entry in v4["topology"]["candidate"]}
        v4_by_uuid[v4["topology"]["reference"]["gpu_uuid"]] = v4["topology"]["reference"]
        for cu in applicability.ACCEPTED_COMPUTE_UNITS:
            node, gpu = by_uuid[cu["gpu_uuid"]]
            self.assertEqual(node, cu["node"])
            self.assertEqual(gpu["product"], cu["product"])
            self.assertEqual(gpu["compute_capability"], cu["compute_capability"])
            self.assertIn(cu["gpu_uuid"], v4_by_uuid)


if __name__ == "__main__":
    unittest.main()
