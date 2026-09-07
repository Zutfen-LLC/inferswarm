"""Focused tests for the issue #117 physical preflight validator."""
import json
import subprocess
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

FREETOKEN_ROOT = Path("/home/zutfen/code/FreeToken")

_FREETOKEN_WORKTREE: Path | None = None


def freetoken_producer_checkout() -> Path | None:
    """A clean, detached checkout of the frozen FreeToken producer.

    Uses a temporary ``git worktree`` so the user's FreeToken checkout is
    never mutated; the worktree is removed at process exit.
    """
    global _FREETOKEN_WORKTREE
    if not FREETOKEN_ROOT.is_dir():
        return None
    if _FREETOKEN_WORKTREE is None:
        import atexit
        worktree = Path(tempfile.mkdtemp(prefix="issue117-freetoken-wt-"))
        result = subprocess.run(
            ["git", "-C", str(FREETOKEN_ROOT), "worktree", "add", "--detach",
             str(worktree), applicability.FROZEN_INTEGRATION_PRODUCER],
            capture_output=True)
        if result.returncode != 0:
            return None
        _FREETOKEN_WORKTREE = worktree
        atexit.register(lambda: subprocess.run(
            ["git", "-C", str(FREETOKEN_ROOT), "worktree", "remove", "--force",
             str(worktree)], capture_output=True))
    return _FREETOKEN_WORKTREE


def canonical_candidate_set_document():
    """The candidate set produced by the actual canonical strategy machinery.

    This is the same machinery the physical execution path uses: the
    canonical authority-descriptor catalog, subject_from_catalog, and the
    strategy's legal candidate enumeration.
    """
    catalog = strategy.canonical_authority_catalog(inferswarm_root=ROOT)
    subject = strategy.subject_from_catalog(
        catalog, execution=strategy.MODEL_SUBJECT["execution"],
        backend=strategy.MODEL_SUBJECT["backend"])
    instance = strategy.GemmaDenseStrategy(catalog=catalog, subject=subject,
                                           source_manifest=None)
    candidates = []
    for candidate in instance.legal_candidates():
        candidates.append({
            "candidate_id": candidate["candidate_id"],
            "stage_count": candidate["stage_count"],
            "stage_structure": [dict(stage) for stage in candidate["stages"]],
            "qualification_subject": candidate["qualification_subject"],
            "qualification_subject_digest": candidate["qualification_subject_digest"],
        })
    return {"candidates": candidates,
            "candidate_set_digest": preflight.candidate_set_digest(candidates)}


def derived_applicability_entries(candidate_set):
    """Retained applicability records equal to the independently derived
    verdicts (the honest retained evidence for a valid preflight)."""
    derived = preflight.derive_candidate_applicability(candidate_set["candidates"])
    entries = []
    for candidate in candidate_set["candidates"]:
        candidate_id = candidate["candidate_id"]
        status = derived[candidate_id]["status"]
        entry = {"candidate_id": candidate_id, "applicability": status,
                 "reason": derived[candidate_id]["reason"]}
        entry["record_digest"] = self_digest(entry, identity_field="record_digest")
        entries.append(entry)
    return entries


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


def source_descriptors_document():
    descriptors = [
        {"source_id": "issue117-origin", "source_kind": "local_file",
         "endpoint": "file:///srv/models/gemma-r6",
         "possession_root": POSSESSION_FIXTURE_ROOT},
        {"source_id": "issue117-remote-mirror", "source_kind": "remote_object",
         "endpoint": "https://models.example.internal/gemma-r6"},
    ]
    return {"descriptors": descriptors,
            "descriptors_digest": preflight.source_descriptors_digest(descriptors)}


def source_possession_records():
    return [preflight.collect_source_possession_record(
        source_id="issue117-origin",
        root=Path(_ensure_possession_fixture()))]


POSSESSION_FIXTURE_ROOT = "/tmp/issue117-possession-fixture/gemma-r6"


def _ensure_possession_fixture():
    fixture = Path(POSSESSION_FIXTURE_ROOT)
    fixture.mkdir(parents=True, exist_ok=True)
    return fixture


def inferswarm_identity_record():
    """Mechanically collected from the ACTUAL test repository checkout."""
    return preflight.collect_repository_identity(ROOT, role="inferswarm")


def freetoken_identity_record():
    """Mechanically collected FreeToken identity.

    Uses a clean detached checkout of the frozen producer when the FreeToken
    repository is available; otherwise builds the evidence-binding record
    shape (validated mechanically; the validator re-checks against the real
    repository whenever its path is supplied and present).
    """
    checkout = freetoken_producer_checkout()
    if checkout is not None:
        return preflight.collect_repository_identity(
            checkout, role="freetoken-integration-producer",
            integration_producer=applicability.FROZEN_INTEGRATION_PRODUCER)
    record = {
        "schema": preflight.REPOSITORY_IDENTITY_SCHEMA,
        "collector": preflight.REPOSITORY_IDENTITY_COLLECTOR,
        "role": "freetoken-integration-producer",
        "repo_root": "/srv/freetoken (fabric-resident checkout)",
        "head": applicability.FROZEN_INTEGRATION_PRODUCER,
        "branch": "integration/issue-117",
        "porcelain": "",
        "clean": True,
        "integration_producer": applicability.FROZEN_INTEGRATION_PRODUCER,
    }
    record["repository_identity_digest"] = self_digest(
        record, identity_field="repository_identity_digest")
    return record


COMMITTED_FIXTURE = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
                     / "evidence" / "integration-fixture.json")


def build_valid_preflight(temp: Path | None = None, **overrides) -> dict:
    temp = temp or Path(tempfile.mkdtemp(prefix="issue117-preflight-"))
    _ensure_possession_fixture()
    candidate_set = candidate_set_document_cache()
    fields = dict(
        inferswarm_identity=inferswarm_identity_record(),
        freetoken_identity=freetoken_identity_record(),
        v5_authority_sha256={**applicability.V5_AUTHORITY_FILES,
                             **applicability.ACCEPTED_PHYSICAL_IDENTITY_FILES},
        compute_units=physical_compute_units(),
        candidate_set=candidate_set,
        qualification_applicability=derived_applicability_entries(candidate_set),
        applicability_audit_digest=applicability.canonical_issue117_audit()["audit_digest"],
        applicability_audit_result=applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY,
        fixture_digest=json.loads(COMMITTED_FIXTURE.read_text())["fixture_digest"],
        source_descriptors=source_descriptors_document(),
        source_possession_records=source_possession_records(),
        cold_cache_proofs=collected_proofs(temp),
    )
    fields.update(overrides)
    return preflight.build_preflight(**fields)


_CANDIDATE_SET_CACHE = None


def candidate_set_document_cache():
    global _CANDIDATE_SET_CACHE
    if _CANDIDATE_SET_CACHE is None:
        _CANDIDATE_SET_CACHE = canonical_candidate_set_document()
    return _CANDIDATE_SET_CACHE


def _repo_worktree_is_clean() -> bool:
    result = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                            capture_output=True)
    return result.returncode == 0 and result.stdout.decode().strip() == ""


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-preflight-valid-")
        cls.valid = build_valid_preflight(Path(cls.temp.name))

    def test_valid_preflight_passes(self):
        if not _repo_worktree_is_clean():
            self.skipTest("test repository working tree is dirty")
        checkout = freetoken_producer_checkout()
        failures = preflight.validate_preflight(
            self.valid, repo_root=ROOT, freetoken_root=checkout)
        self.assertEqual(failures, [])

    def test_valid_preflight_binds_the_real_test_repository_head(self):
        observed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, check=True).stdout.decode().strip()
        self.assertEqual(
            self.valid["implementation"]["inferswarm_identity"]["head"],
            observed)

    def test_valid_preflight_derives_applicability_not_asserts_it(self):
        # the stored applicability records equal the independently derived
        # verdicts; flipping any of them breaks validation below
        statuses = {entry["candidate_id"]: entry["applicability"]
                    for entry in self.valid["qualification_applicability"]}
        derived = preflight.derive_candidate_applicability(
            self.valid["candidate_set"]["candidates"])
        self.assertEqual(statuses,
                         {cid: result["status"]
                          for cid, result in derived.items()})
        v5 = strategy.canonical_v5_candidate()["candidate_id"]
        self.assertEqual(statuses[v5], "QUALIFICATION_APPLICABLE")

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
        identity = freetoken_identity_record()
        identity["integration_producer"] = "b" * 40
        identity["repository_identity_digest"] = self_digest(
            identity, identity_field="repository_identity_digest")
        broken = build_valid_preflight(freetoken_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("exact producer" in failure for failure in failures))

    def test_missing_field_fails(self):
        broken = json.loads(json.dumps(self.valid))
        del broken["integration_fixture_digest"]
        broken["preflight_digest"] = preflight._self_digest(broken)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("fixture" in failure for failure in failures))

    def test_sha_fields_must_be_real_shas(self):
        identity = freetoken_identity_record()
        identity["head"] = "main"
        identity["repository_identity_digest"] = self_digest(
            identity, identity_field="repository_identity_digest")
        broken = build_valid_preflight(freetoken_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("not a git SHA" in failure for failure in failures))

    def test_dirty_worktree_evidence_fails(self):
        identity = inferswarm_identity_record()
        identity["porcelain"] = " M scripts/x.py\n"
        identity["clean"] = False
        identity["repository_identity_digest"] = self_digest(
            identity, identity_field="repository_identity_digest")
        broken = build_valid_preflight(inferswarm_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("worktree" in failure for failure in failures))

    def test_cleanliness_must_be_derived_from_porcelain(self):
        identity = freetoken_identity_record()
        identity["clean"] = False  # porcelain says clean, flag disagrees
        identity["repository_identity_digest"] = self_digest(
            identity, identity_field="repository_identity_digest")
        broken = build_valid_preflight(freetoken_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("not derived from" in failure for failure in failures))

    def test_edited_collector_record_fails(self):
        identity = inferswarm_identity_record()
        identity["head"] = "0" * 40  # edit without re-digesting
        broken = build_valid_preflight(inferswarm_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("edited" in failure for failure in failures))

    def test_head_that_merely_looks_valid_fails(self):
        # "a"*40 passes SHA syntax but does not equal the observed checkout
        identity = inferswarm_identity_record()
        identity["head"] = "a" * 40
        identity["repository_identity_digest"] = self_digest(
            identity, identity_field="repository_identity_digest")
        broken = build_valid_preflight(inferswarm_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("does not equal the observed checkout" in failure
                            for failure in failures))

    def test_freetoken_head_must_equal_bound_producer(self):
        identity = freetoken_identity_record()
        identity["head"] = "b" * 40
        identity["repository_identity_digest"] = self_digest(
            identity, identity_field="repository_identity_digest")
        broken = build_valid_preflight(freetoken_identity=identity)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any(
            "HEAD does not equal the producer bound" in failure
            for failure in failures))

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

    def test_drifted_checkpoint_authority_subject_fails(self):
        subject = dict(self.valid["model_subject"])
        subject["checkpoint_authority_sha256"] = "e" * 64
        broken = json.loads(json.dumps(self.valid))
        broken["model_subject"] = subject
        broken["preflight_digest"] = preflight._self_digest(broken)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("checkpoint_authority_sha256 drift" in failure
                            for failure in failures))


class QualificationDerivationTests(unittest.TestCase):
    """Finding 2: applicability is derived from evidence, never trusted."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-preflight-qual-")
        cls.valid = build_valid_preflight(Path(cls.temp.name))

    def valid_with(self, candidate_set, applicability_entries):
        return build_valid_preflight(
            Path(self.temp.name), candidate_set=candidate_set,
            qualification_applicability=applicability_entries)

    def entry(self, candidate_id, status):
        entry = {"candidate_id": candidate_id, "applicability": status}
        entry["record_digest"] = self_digest(entry, identity_field="record_digest")
        return entry

    def foreign_subject_candidate(self, candidate_id="dense.foreignsubject00"):
        from issue74_methodology import canonical_json_bytes
        from issue99_artifact_core import digest_of_bytes, subject_digest
        subject = {
            "model_id": strategy.MODEL_SUBJECT["model_id"],
            "revision": strategy.MODEL_SUBJECT["revision"],
            "checkpoint_authority_sha256":
                strategy.MODEL_SUBJECT["checkpoint_authority_sha256"],
            "catalog_content_digest": "sha256:" + "9" * 64,
            "representation": strategy.MODEL_SUBJECT["representation"],
            "execution": strategy.MODEL_SUBJECT["execution"],
            "backend": dict(strategy.MODEL_SUBJECT["backend"]),
            "layer_count": 48,
            "stage_structure": [dict(stage) for stage
                                in strategy.ACCEPTED_V5_GEOMETRY],
        }
        return {"candidate_id": candidate_id,
                "stage_count": 3,
                "stage_structure": [dict(stage) for stage
                                    in strategy.ACCEPTED_V5_GEOMETRY],
                "qualification_subject": subject,
                "qualification_subject_digest": subject_digest(subject)}

    def test_v5_geometry_with_foreign_subject_and_forged_applicable_fails(self):
        # correct V5 geometry, foreign subject, forged APPLICABLE record:
        # the derivation yields NOT_APPLICABLE (subject mismatch) and the
        # mismatch with the retained record is refused
        foreign = self.foreign_subject_candidate()
        candidate_set = {
            "candidates": self.valid["candidate_set"]["candidates"] + [foreign],
            "candidate_set_digest": preflight.candidate_set_digest(
                self.valid["candidate_set"]["candidates"] + [foreign])}
        entries = derived_applicability_entries(candidate_set)
        forged = self.entry(foreign["candidate_id"], "QUALIFICATION_APPLICABLE")
        broken = self.valid_with(
            candidate_set,
            [entry for entry in entries
             if entry["candidate_id"] != foreign["candidate_id"]] + [forged])
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any(
            "does not equal the independently derived verdict" in failure
            for failure in failures), failures)

    def test_tampered_subject_digest_breaks_validation(self):
        candidate_set = json.loads(json.dumps(
            candidate_set_document_cache()))
        v5_id = strategy.canonical_v5_candidate()["candidate_id"]
        for candidate in candidate_set["candidates"]:
            if candidate["candidate_id"] == v5_id:
                candidate["qualification_subject_digest"] = "sha256:" + "8" * 64
        candidate_set["candidate_set_digest"] = preflight.candidate_set_digest(
            candidate_set["candidates"])
        entries = derived_applicability_entries(candidate_set)
        broken = self.valid_with(candidate_set, entries)
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("does not recompute" in failure
                            for failure in failures))

    def test_foreign_terminal_adjudication_yields_not_applicable(self):
        # a qualification record bound to a FOREIGN adjudication identity is
        # not accepted evidence: the evaluator refuses it as unbound, so a
        # candidate can only become applicable through the accepted record
        from issue117_gemma_strategy import build_qualification_record
        from issue117_planner import (
            QUALIFICATION_POLICY_STRICT,
            evaluate_qualification_applicability,
        )
        from issue99_artifact_core import MACHINERY_LOCAL_SUBJECT_KEYS
        canonical = strategy.canonical_v5_candidate()
        foreign_record = build_qualification_record(
            qualification_record_id="foreign/1",
            terminal_disposition="V5_QUALIFICATION_PASS",
            terminal_adjudication_sha256="7" * 64,
            qualification_subject=dict(canonical["qualification_subject"]),
            scope="test")
        policy = {
            "policy": QUALIFICATION_POLICY_STRICT,
            "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
            "accepted_adjudication_sha256":
                strategy.accepted_v5_qualification_record()
                ["authority"]["terminal_adjudication_sha256"],
            "machinery_local_subject_keys": MACHINERY_LOCAL_SUBJECT_KEYS,
            "required_for_admission": True,
        }
        result = evaluate_qualification_applicability(
            canonical, [foreign_record], policy)
        self.assertEqual(result["status"], "QUALIFICATION_NOT_APPLICABLE")
        self.assertEqual(result["unbound_record_ids"], ["foreign/1"])
        # and the preflight derivation hardwires the accepted record, so a
        # foreign record can never enter it at all
        derived = preflight.derive_candidate_applicability([canonical])
        self.assertEqual(derived[canonical["candidate_id"]]["status"],
                         "QUALIFICATION_APPLICABLE")

    def test_self_consistent_fabricated_record_cannot_make_candidate_applicable(self):
        # a stored applicability record claiming APPLICABLE for a candidate
        # whose derived verdict is NOT_APPLICABLE is refused even when the
        # record itself is digest-bound and internally consistent
        other = self.foreign_subject_candidate("dense.fabricated00")
        candidate_set = {
            "candidates": self.valid["candidate_set"]["candidates"] + [other],
            "candidate_set_digest": preflight.candidate_set_digest(
                self.valid["candidate_set"]["candidates"] + [other])}
        entries = derived_applicability_entries(candidate_set)
        fabricated = {"candidate_id": other["candidate_id"],
                      "applicability": "QUALIFICATION_APPLICABLE",
                      "authority": {"terminal_disposition": "V5_QUALIFICATION_PASS",
                                    "terminal_adjudication_sha256": "7" * 64},
                      "qualification_subject_digest": "sha256:" + "6" * 64}
        fabricated["record_digest"] = self_digest(
            fabricated, identity_field="record_digest")
        broken = self.valid_with(
            candidate_set,
            [entry for entry in entries
             if entry["candidate_id"] != other["candidate_id"]] + [fabricated])
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any(
            "does not equal the independently derived verdict" in failure
            for failure in failures))

    def test_duplicated_conflicting_applicability_records_fail(self):
        candidate_set = candidate_set_document_cache()
        entries = derived_applicability_entries(candidate_set)
        v5_id = strategy.canonical_v5_candidate()["candidate_id"]
        conflicting = self.entry(v5_id, "QUALIFICATION_NOT_APPLICABLE")
        broken = build_valid_preflight(
            Path(self.temp.name), candidate_set=candidate_set,
            qualification_applicability=entries + [conflicting])
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("duplicated/conflicting" in failure
                            for failure in failures))

    def test_missing_applicability_evidence_fails(self):
        broken = build_valid_preflight(
            Path(self.temp.name),
            qualification_applicability=[])
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("no qualification-applicability record" in failure
                            for failure in failures))

    def test_missing_v5_geometry_in_candidate_set_fails(self):
        candidate_set = candidate_set_document_cache()
        v5_id = strategy.canonical_v5_candidate()["candidate_id"]
        candidates = [candidate for candidate in candidate_set["candidates"]
                      if candidate["candidate_id"] != v5_id]
        reduced = {"candidates": candidates,
                   "candidate_set_digest": preflight.candidate_set_digest(candidates)}
        broken = build_valid_preflight(
            Path(self.temp.name), candidate_set=reduced,
            qualification_applicability=derived_applicability_entries(reduced))
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("V5 geometry" in failure for failure in failures))


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


class SourcePossessionTests(unittest.TestCase):
    """Finding 4: source-possession separation is mandatory, not vacuous."""

    def collected_proofs_with_roots(self, roots):
        proofs = []
        for index, root in enumerate(roots):
            proofs.append(preflight.collect_cold_cache_proof(
                participant_id=f"stage-{index + 1}", cache_root=root,
                materialized_root=root / "materialized"))
        return proofs

    def test_empty_possession_with_file_source_fails(self):
        broken = build_valid_preflight(source_possession_records=[])
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("no source-possession evidence" in failure
                            for failure in failures))

    def test_local_source_without_possession_record_fails(self):
        descriptors = source_descriptors_document()
        descriptors["descriptors"] = [descriptors["descriptors"][0]]
        descriptors["descriptors_digest"] = preflight.source_descriptors_digest(
            descriptors["descriptors"])
        broken = build_valid_preflight(
            source_descriptors=descriptors,
            source_possession_records=[])
        failures = preflight.validate_preflight(broken, repo_root=ROOT)
        self.assertTrue(any("carries no source-possession record" in failure
                            for failure in failures))

    def possession_valid_preflight(self, possession_root, cache_roots):
        """Build a preflight whose local source and cache roots are the given
        paths (all under one temporary directory)."""
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            source = temp_root / possession_root
            source.mkdir(parents=True, exist_ok=True)
            proofs = self.collected_proofs_with_roots(
                [temp_root / cache for cache in cache_roots])
            descriptors = {"descriptors": [
                {"source_id": "issue117-origin", "source_kind": "local_file",
                 "endpoint": f"file://{source}"}],
                "descriptors_digest": None}
            descriptors["descriptors_digest"] = preflight.source_descriptors_digest(
                descriptors["descriptors"])
            possession = [preflight.collect_source_possession_record(
                source_id="issue117-origin", root=source)]
            return build_valid_preflight(
                Path(temp),
                source_descriptors=descriptors,
                source_possession_records=possession,
                cold_cache_proofs=proofs)

    def _failures_for(self, document):
        return preflight.validate_preflight(document, repo_root=ROOT)

    def test_source_root_equal_to_cache_root_fails(self):
        document = self.possession_valid_preflight(
            "models/source", ["models/source", "cache-2", "cache-3"])
        failures = self._failures_for(document)
        self.assertTrue(any("is not separate from" in failure
                            for failure in failures))

    def test_source_parent_of_cache_root_fails(self):
        document = self.possession_valid_preflight(
            "models/source", ["models/source/cache-1", "cache-2", "cache-3"])
        failures = self._failures_for(document)
        self.assertTrue(any("is not separate from" in failure
                            for failure in failures))

    def test_cache_parent_of_source_root_fails(self):
        document = self.possession_valid_preflight(
            "models/cache-1/source", ["models/cache-1", "cache-2", "cache-3"])
        failures = self._failures_for(document)
        self.assertTrue(any("is not separate from" in failure
                            for failure in failures))

    def test_symlink_aliased_source_root_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            real = temp_root / "elsewhere" / "checkpoint"
            real.mkdir(parents=True)
            alias = temp_root / "models" / "source"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(real)
            proofs = self.collected_proofs_with_roots(
                [temp_root / "cache-1", temp_root / "cache-2",
                 temp_root / "cache-3"])
            descriptors = {"descriptors": [
                {"source_id": "issue117-origin", "source_kind": "local_file",
                 "endpoint": f"file://{alias}"}],
                "descriptors_digest": None}
            descriptors["descriptors_digest"] = preflight.source_descriptors_digest(
                descriptors["descriptors"])
            possession = [preflight.collect_source_possession_record(
                source_id="issue117-origin", root=alias)]
            document = build_valid_preflight(
                Path(temp), source_descriptors=descriptors,
                source_possession_records=possession,
                cold_cache_proofs=proofs)
            failures = self._failures_for(document)
            self.assertTrue(any("root itself is a symlink" in failure
                                for failure in failures), failures)

    def test_edited_possession_record_fails(self):
        records = source_possession_records()
        records[0]["facts"]["root_exists"] = False
        broken = build_valid_preflight(source_possession_records=records)
        failures = self._failures_for(broken)
        self.assertTrue(any("edited" in failure for failure in failures))

    def test_remote_source_kinds_require_explicit_identity(self):
        descriptors = source_descriptors_document()
        descriptors["descriptors"][1] = {
            "source_id": "issue117-remote-mirror",
            "endpoint": "https://models.example.internal/gemma-r6"}
        descriptors["descriptors_digest"] = preflight.source_descriptors_digest(
            descriptors["descriptors"])
        broken = build_valid_preflight(source_descriptors=descriptors)
        failures = self._failures_for(broken)
        self.assertTrue(any("no explicit source-kind identity" in failure
                            for failure in failures))

    def test_possession_record_from_foreign_directory_fails(self):
        # the possession record must be collected from exactly the Source's
        # authorized possession root, not any disjoint directory
        records = source_possession_records()
        foreign = preflight.collect_source_possession_record(
            source_id="issue117-origin", root=Path(tempfile.gettempdir()))
        self.assertNotEqual(foreign["facts"]["root"],
                            records[0]["facts"]["root"])
        broken = build_valid_preflight(source_possession_records=[foreign])
        failures = self._failures_for(broken)
        self.assertTrue(any("not the Source's authorized possession root" in failure
                            for failure in failures))

    def test_planted_cache_file_fails_cold_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            planted = root / "cache-stage-1" / "object.bin"
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_bytes(b"x" * 128)
            proofs = collected_proofs(root)
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = self._failures_for(broken)
            self.assertTrue(any("not empty" in failure for failure in failures))

    def test_symlink_in_cold_root_facts_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cache-stage-1").mkdir(parents=True, exist_ok=True)
            (root / "cache-stage-1" / "alias").symlink_to("/srv/models")
            proofs = collected_proofs(root)
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = self._failures_for(broken)
            self.assertTrue(any("symlink" in failure for failure in failures))

    def test_hardlink_alias_in_cold_root_facts_fails(self):
        # a hardlinked object inside a cold root is an aliasing channel into
        # source possession and must fail the collected facts
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_file = root / "source-object.bin"
            source_file.write_bytes(b"x" * 128)
            cache = root / "cache-stage-1"
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "aliased.bin").hardlink_to(source_file)
            proofs = collected_proofs(root)
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = self._failures_for(broken)
            self.assertTrue(any("hardlink" in failure for failure in failures),
                            failures)

    def test_tampered_proof_digest_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            proofs = collected_proofs(Path(temp))
            proofs[0]["cache_facts"]["entry_count"] = 5
            broken = build_valid_preflight(cold_cache_proofs=proofs)
            failures = self._failures_for(broken)
            self.assertTrue(any(
                "entry_count" in failure or "self-identity" in failure
                for failure in failures))

    def test_collected_proof_rejects_boolean_shortcuts(self):
        legacy = [{"participant_id": "p1", "cache_root": "/srv/cache",
                   "materialized_root": "/srv/materialized",
                   "cache_entry_count": 0, "cache_bytes": 0,
                   "no_symlink_alias": True, "source_possession_separate": True}]
        broken = build_valid_preflight(cold_cache_proofs=legacy)
        failures = self._failures_for(broken)
        self.assertTrue(any("mechanically collected" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
