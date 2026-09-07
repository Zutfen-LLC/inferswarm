"""Focused tests for the issue #117 V5 qualification-applicability barrier."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

import issue117_applicability as applicability  # noqa: E402

FREETOKEN_ROOT = Path("/home/zutfen/code/FreeToken")


def authority_for(producer: str | None = None) -> dict:
    return {
        "integration_producer": producer or applicability.FROZEN_INTEGRATION_PRODUCER,
        "execution_authority": applicability.ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY,
    }


def poisoned_delta(**overrides) -> dict:
    """A self-consistent delta document derived from the frozen evidence."""
    delta = json.loads(json.dumps(
        applicability.load_producer_delta(ROOT)))
    delta.update(overrides)
    delta.pop("producer_delta_digest", None)
    delta["producer_delta_digest"] = applicability.self_digest(
        delta, identity_field="producer_delta_digest")
    return delta


class V5AuthorityIdentityTests(unittest.TestCase):
    def test_accepted_v5_files_are_byte_identical(self):
        record = applicability.verify_v5_authority(ROOT)
        self.assertEqual(record["verified_file_count"], len(applicability.V5_AUTHORITY_FILES))

    def test_physical_identity_files_are_byte_identical(self):
        record = applicability.verify_v5_authority(ROOT)
        self.assertEqual(record["verified_physical_identity_files"],
                         {name: applicability.sha256_file(ROOT / name)
                          for name in applicability.ACCEPTED_PHYSICAL_IDENTITY_FILES})

    def test_terminal_adjudication_constant_matches_pinned_file(self):
        self.assertEqual(
            applicability.V5_AUTHORITY_FILES[
                "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json"],
            applicability.ACCEPTED_TERMINAL_ADJUDICATION_SHA256)

    def test_drifted_authority_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            name = "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"
            target = root / name
            target.parent.mkdir(parents=True)
            target.write_bytes(b'{"tampered": true}')
            with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "drifted"):
                applicability.verify_v5_authority(root, files={
                    name: applicability.V5_AUTHORITY_FILES[name]})

    def test_missing_authority_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "missing"):
                applicability.verify_v5_authority(Path(temp))

    def test_drifted_physical_identity_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            name = "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"
            for relative in applicability.ACCEPTED_PHYSICAL_IDENTITY_FILES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            with open(root / name, "ab") as handle:
                handle.write(b' {"tampered": true}')
            with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "drifted"):
                applicability.verify_v5_authority(root, files={})


@unittest.skipUnless(FREETOKEN_ROOT.is_dir(),
                    "FreeToken repository not available on this machine")
class ProducerDeltaCollectorTests(unittest.TestCase):
    """The frozen evidence must reproduce from a mechanical collection."""

    def test_frozen_delta_reproduces_deterministically(self):
        frozen = applicability.load_producer_delta(ROOT)
        collected = applicability.collect_producer_delta(
            FREETOKEN_ROOT,
            integration_producer=applicability.FROZEN_INTEGRATION_PRODUCER)
        self.assertEqual(frozen, collected)

    def test_zone_covers_the_accepted_holdout_authority_added_files(self):
        # the only zone deltas are the accepted holdout admission wrappers,
        # and their collected digests equal the accepted authority's pins
        frozen = applicability.load_producer_delta(ROOT)
        authority = json.loads((ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110"
                                / "preflight/HOLDOUT-EXECUTION-AUTHORITY.json").read_text())
        pinned = authority["holdout_producer"]["added_files_sha256"]
        extra = {entry["path"]: entry["integration_sha256"]
                 for entry in frozen["zone_files"] if entry["delta"] == "EXTRA"}
        for path, digest in pinned.items():
            if path in extra:
                self.assertEqual(extra[path], "sha256:" + digest)
            else:
                self.assertIn(path, frozen["out_of_zone_changes"]["added"])

    def test_execution_math_surfaces_are_provably_unchanged(self):
        frozen = applicability.load_producer_delta(ROOT)
        for entry in frozen["zone_files"]:
            if any(surface not in applicability.ADMISSIBLE_CHANGE_SURFACES
                   for surface in entry["surfaces"]):
                self.assertEqual(entry["delta"], applicability.DELTA_IDENTICAL,
                                 entry["path"])


class ProducerDeltaValidationTests(unittest.TestCase):
    def test_valid_frozen_delta_loads(self):
        self.assertEqual(applicability.load_producer_delta(ROOT)["schema"],
                         "inferswarm.issue117.producer-delta/2")

    def test_wrong_producer_binding_is_refused(self):
        delta = poisoned_delta(integration_producer="b" * 40)
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "frozen.*integration producer"):
            applicability.validate_producer_delta(delta)

    def test_self_identity_mismatch_is_refused(self):
        delta = poisoned_delta()
        delta["producer_delta_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "self-identity"):
            applicability.validate_producer_delta(delta)

    def test_wrong_execution_authority_is_refused(self):
        delta = poisoned_delta(execution_authority="c" * 40)
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "authority"):
            applicability.validate_producer_delta(delta)

    def test_unbound_zone_files_are_refused(self):
        delta = poisoned_delta(unbound_zone_files=["python/freetoken/new_math.py"])
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "UNKNOWN"):
            applicability.validate_producer_delta(delta)


class DynamicImportClosureTests(unittest.TestCase):
    """Finding 5: dynamic import coverage is closed or fails closed."""

    def test_frozen_closure_resolves_every_dynamic_target(self):
        frozen = applicability.load_producer_delta(ROOT)
        for closure_name in ("authority_closure", "integration_closure"):
            closure = frozen[closure_name]
            self.assertEqual(closure["unresolved_dynamic_targets"], [])
            self.assertEqual(closure["unresolved_in_repository_imports"], [])
            self.assertTrue(closure["dynamic_import_targets"])
        zone = {entry["path"] for entry in frozen["zone_files"]}
        resolved = {entry["resolution"] for entry in
                    frozen["authority_closure"]["dynamic_import_targets"]
                    if entry["classification"] == "IN_REPOSITORY"}
        self.assertTrue(resolved <= zone, resolved - zone)

    def test_external_module_targets_carry_accepted_runtime_bindings(self):
        frozen = applicability.load_producer_delta(ROOT)
        bound = {entry["target"]: entry["binding"] for entry in
                 frozen["authority_closure"]["dynamic_import_targets"]
                 if entry["classification"] == "EXTERNAL_BOUND"}
        self.assertIn("torch", bound)
        self.assertIn("torch 2.11.0+cu130", bound["torch"])
        probes = {entry["target"] for entry in
                  frozen["authority_closure"]["dynamic_import_targets"]
                  if entry["classification"] == "EXTERNAL_PROBE"}
        self.assertLessEqual(
            probes, set(applicability.EXTERNAL_AVAILABILITY_PROBE_ALLOWLIST))

    def test_unresolved_dynamic_target_fails_closed(self):
        delta = poisoned_delta()
        closure = delta["authority_closure"]
        closure["dynamic_import_targets"][0]["classification"] = "UNRESOLVED"
        closure["unresolved_dynamic_targets"] = [
            closure["dynamic_import_targets"][0]]
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "unresolved dynamic execution targets"):
            applicability.validate_producer_delta(delta)

    def test_non_literal_dynamic_target_fails_closed(self):
        delta = poisoned_delta()
        closure = delta["authority_closure"]
        closure["dynamic_import_targets"].append({
            "file": "python/freetoken/models/loader.py", "target": None,
            "mechanism": "module_import", "classification": "UNRESOLVED",
            "resolution": None, "binding": "non-literal dynamic import target"})
        closure["unresolved_dynamic_targets"] = [closure["dynamic_import_targets"][-1]]
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "unresolved dynamic execution targets"):
            applicability.validate_producer_delta(delta)

    def test_unresolved_in_repository_module_import_fails_closed(self):
        delta = poisoned_delta()
        delta["authority_closure"]["unresolved_in_repository_imports"] = [
            "freetoken.models.unresolved_module"]
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "unresolved in-repository module"):
            applicability.validate_producer_delta(delta)

    def test_changed_dynamically_loaded_target_requires_requalification(self):
        # the compiled-extension build source of the pinned.py dynamic import
        # is a zone member; changing it is changed execution math
        delta = poisoned_delta()
        entry = next(entry for entry in delta["zone_files"]
                     if entry["path"] ==
                     "python/freetoken/kernel/csrc/pinned_tensor.cpp")
        self.assertEqual(entry["delta"], applicability.DELTA_IDENTICAL)
        entry["integration_sha256"] = "sha256:" + "d" * 64
        entry["delta"] = applicability.DELTA_CHANGED
        delta.pop("producer_delta_digest")
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(
                applicability.ApplicabilityBlocked,
                applicability.R6_SUCCESSOR_REQUALIFICATION_REQUIRED):
            applicability.build_audit_document(delta, authority=authority_for())

    def test_newly_introduced_dynamic_target_blocks_the_closure(self):
        # a producer that adds a dynamic import the execution authority does
        # not have has an unprovable zone: the closure sets differ
        delta = poisoned_delta()
        delta["integration_closure"]["dynamic_import_targets"] = \
            delta["integration_closure"]["dynamic_import_targets"] + [{
                "file": "python/freetoken/models/loader.py",
                "target": "freetoken.models.gemma4.dynamic_math",
                "mechanism": "module_import",
                "classification": "IN_REPOSITORY",
                "resolution": "python/freetoken/models/gemma4/dynamic_math.py",
                "binding": None}]
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "dynamic-import usage differs"):
            applicability.validate_producer_delta(delta)

    def test_symbol_imports_are_harmless_telemetry(self):
        # `from X import symbol` names must not appear as unresolved modules:
        # the collector distinguishes them mechanically
        frozen = applicability.load_producer_delta(ROOT)
        closure = frozen["authority_closure"]
        unresolved = set(closure["unresolved_in_repository_imports"])
        for symbol in closure["imported_symbols"]:
            name = symbol.rsplit(": ", 1)[-1]
            self.assertNotIn(name, unresolved)


class AuditDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = applicability.canonical_issue117_audit(ROOT)

    def test_covers_every_audited_surface_exactly_once(self):
        surfaces = [entry["surface"] for entry in self.audit["entries"]]
        self.assertEqual(sorted(surfaces), sorted(applicability.AUDITED_SURFACES))
        self.assertEqual(len(surfaces), len(set(surfaces)))

    def test_canonical_audit_is_control_artifact_materialization_only(self):
        self.assertEqual(
            applicability.validate_audit_document(self.audit),
            applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY)

    def test_audit_is_bound_to_one_exact_producer(self):
        self.assertEqual(self.audit["authority"]["integration_producer"],
                         applicability.FROZEN_INTEGRATION_PRODUCER)
        self.assertEqual(self.audit["producer_delta"]["integration_producer"],
                         applicability.FROZEN_INTEGRATION_PRODUCER)
        self.assertEqual(self.audit["authority"]["execution_authority"],
                         applicability.ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY)

    def test_audit_is_frozen_and_deterministic(self):
        again = applicability.canonical_issue117_audit(ROOT)
        self.assertEqual(self.audit, again)

    def test_missing_surface_fails_closed(self):
        document = json.loads(json.dumps(self.audit))
        document["entries"] = [entry for entry in document["entries"]
                               if entry["surface"] != "precision"]
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "missing"):
            applicability.evaluate_audit(document)

    def test_extra_surface_fails_closed(self):
        document = json.loads(json.dumps(self.audit))
        document["entries"].append({
            "surface": "not_a_real_surface",
            "classification": applicability.CONTROL_ONLY,
            "binding": "FREETOKEN_EXECUTION_ZONE",
            "bound_file_count": 0,
            "observed_delta": "IDENTICAL",
            "delta_summary": {"IDENTICAL": 0, "CHANGED": 0,
                              "MISSING": 0, "EXTRA": 0},
            "evidence_ref": "x",
        })
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "extra"):
            applicability.evaluate_audit(document)

    def test_duplicated_surface_fails_closed(self):
        document = json.loads(json.dumps(self.audit))
        document["entries"].append(dict(document["entries"][0]))
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "duplicated"):
            applicability.evaluate_audit(document)

    def test_changed_execution_math_requires_requalification(self):
        delta = poisoned_delta()
        entry = next(entry for entry in delta["zone_files"]
                     if "dense_stage_model_math" in entry["surfaces"])
        entry["integration_sha256"] = "sha256:" + "f" * 64
        entry["delta"] = applicability.DELTA_CHANGED
        delta.pop("producer_delta_digest")
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(
                applicability.ApplicabilityBlocked,
                applicability.R6_SUCCESSOR_REQUALIFICATION_REQUIRED):
            applicability.build_audit_document(delta, authority=authority_for())

    def test_missing_execution_math_requires_requalification(self):
        delta = poisoned_delta()
        entry = next(entry for entry in delta["zone_files"]
                     if "attention_implementation" in entry["surfaces"])
        entry["integration_sha256"] = None
        entry["delta"] = applicability.DELTA_MISSING
        delta.pop("producer_delta_digest")
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(
                applicability.ApplicabilityBlocked,
                applicability.R6_SUCCESSOR_REQUALIFICATION_REQUIRED):
            applicability.build_audit_document(delta, authority=authority_for())

    def test_extra_zone_file_on_math_surface_requires_requalification(self):
        delta = poisoned_delta()
        delta["zone_files"].append({
            "path": "python/freetoken/models/gemma4/new_math.py",
            "authority_sha256": None,
            "integration_sha256": "sha256:" + "e" * 64,
            "delta": applicability.DELTA_EXTRA,
            "surfaces": ["dense_stage_model_math"],
        })
        delta["unbound_zone_files"] = []
        delta.pop("producer_delta_digest")
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        with self.assertRaisesRegex(
                applicability.ApplicabilityBlocked,
                applicability.R6_SUCCESSOR_REQUALIFICATION_REQUIRED):
            applicability.build_audit_document(delta, authority=authority_for())

    def test_changed_admission_wrapper_remains_admissible(self):
        delta = poisoned_delta()
        entry = next(entry for entry in delta["zone_files"]
                     if entry["surfaces"] == ["decision_row_construction"])
        entry["integration_sha256"] = "sha256:" + "d" * 64
        entry["delta"] = applicability.DELTA_CHANGED
        delta.pop("producer_delta_digest")
        delta["producer_delta_digest"] = applicability.self_digest(
            delta, identity_field="producer_delta_digest")
        document = applicability.build_audit_document(delta, authority=authority_for())
        self.assertEqual(document["overall_result"],
                         applicability.DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY)
        surface = next(entry for entry in document["entries"]
                       if entry["surface"] == "decision_row_construction")
        self.assertEqual(surface["observed_delta"], "OBSERVED_CHANGES")

    def test_undefined_classification_rejected(self):
        document = json.loads(json.dumps(self.audit))
        for entry in document["entries"]:
            if entry["surface"] == "prefill":
                entry["classification"] = "MAGIC_ONLY"
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "unknown classification"):
            applicability.evaluate_audit(document)

    def test_observed_delta_must_match_recorded_summary(self):
        document = json.loads(json.dumps(self.audit))
        for entry in document["entries"]:
            if entry["surface"] == "prefill":
                entry["observed_delta"] = "OBSERVED_CHANGES"
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked,
                                    "not derived"):
            applicability.evaluate_audit(document)

    def test_wrong_producer_authority_rejected(self):
        document = json.loads(json.dumps(self.audit))
        document["authority"]["integration_producer"] = "b" * 40
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "producer"):
            applicability.evaluate_audit(document)

    def test_tampered_frozen_audit_rejected(self):
        tampered = json.loads(json.dumps(self.audit))
        tampered["entries"][0]["observed_delta"] = "OBSERVED_CHANGES"
        with self.assertRaises(applicability.ApplicabilityBlocked):
            applicability.validate_audit_document(tampered)

    def test_validate_rejects_document_that_is_not_the_frozen_audit(self):
        document = applicability.build_audit_document(
            poisoned_delta(), authority=authority_for())
        # self-consistent but not the frozen audit for the frozen delta
        with self.assertRaisesRegex(applicability.ApplicabilityBlocked, "frozen"):
            applicability.validate_audit_document(document)


if __name__ == "__main__":
    unittest.main()
