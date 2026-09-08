"""Focused tests: accepted V5 qualification-subject recovery (issue #117).

Proves:
- the accepted subject is reconstructed field-by-field from byte-pinned
  historical evidence, with the accepted terminal adjudication identity;
- the reconstruction is independent of current candidate machinery (strong
  independence test: materially altering the candidate-construction helper
  in test scope leaves the accepted subject and digest unchanged, while
  altering an accepted historical source invalidates it);
- the canonical V5 candidate becomes QUALIFICATION_APPLICABLE through
  ordinary subject equality against the recovered subject — not candidate
  ID, geometry name, or hard-coded selection;
- every materially different legal candidate stays QUALIFICATION_NOT_APPLICABLE;
- all mandatory negative controls fail closed.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_accepted_subject as accepted_subject  # noqa: E402
import issue117_applicability as applicability  # noqa: E402
import issue117_gemma_strategy as strategy  # noqa: E402
import issue117_planner as planner  # noqa: E402
import issue117_preflight as preflight  # noqa: E402
from issue117_subject_identity import (  # noqa: E402
    execution_equality_subject, subject_digest)

ADJUDICATION = applicability.ACCEPTED_TERMINAL_ADJUDICATION_SHA256


def copy_evidence_root(temp: Path) -> Path:
    """Copy every pinned evidence file into a throwaway root."""
    for relative in accepted_subject.ACCEPTED_SUBJECT_EVIDENCE_FILES:
        target = temp / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return temp


class ReconstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = accepted_subject.accepted_v5_qualification_record(ROOT)
        cls.subject = cls.record["qualification_subject"]

    def test_terminal_authority_is_bound(self):
        self.assertEqual(self.record["authority"]["terminal_disposition"],
                         "V5_QUALIFICATION_PASS")
        self.assertEqual(
            self.record["authority"]["terminal_adjudication_sha256"],
            ADJUDICATION)

    def test_subject_fields(self):
        self.assertEqual(self.subject["model_id"], "google/gemma-4-12B-it")
        self.assertEqual(
            self.subject["revision"], "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7")
        self.assertEqual(
            self.subject["checkpoint_authority_sha256"],
            "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d")
        self.assertEqual(self.subject["representation"], "checkpoint-safetensors")
        self.assertEqual(
            self.subject["execution"],
            "native BF16 text execution; Triton attention; one <=64-row replay chunk")
        self.assertEqual(self.subject["backend"], {
            "torch": "2.11.0+cu130", "cuda_runtime": "13.0",
            "nvidia_driver": "610.57.04", "triton": "3.6.0",
            "flashinfer": "0.6.17"})
        self.assertEqual(self.subject["layer_count"], 48)
        self.assertEqual(self.subject["stage_structure"], [
            {"cu_id": "inferswarm01/gpu-0", "node": "inferswarm01",
             "layer_start": 0, "layer_end": 16},
            {"cu_id": "inferswarm01/gpu-1", "node": "inferswarm01",
             "layer_start": 16, "layer_end": 32},
            {"cu_id": "inferswarm03/gpu-0", "node": "inferswarm03",
             "layer_start": 32, "layer_end": 48}])
        self.assertNotIn("catalog_content_digest", self.subject)
        self.assertEqual(self.record["qualification_subject_digest"],
                         subject_digest(self.subject))

    def test_projection_matches_the_shared_convention(self):
        # the accepted subject's execution-equality projection contains
        # exactly the acceptance-bearing fields, with machinery-local keys
        # (catalog content identity) absent
        projection = execution_equality_subject(self.subject)
        self.assertEqual(sorted(projection), sorted([
            "model_id", "revision", "checkpoint_authority_sha256",
            "representation", "execution", "backend", "layer_count",
            "stage_structure"]))

    def test_retained_record_file_agrees_with_the_derivation(self):
        retained = json.loads(
            (ROOT / accepted_subject.ACCEPTED_SUBJECT_RECORD_RELATIVE_PATH)
            .read_text())
        self.assertEqual(retained["classification"],
                         "V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED")
        self.assertEqual(
            retained["qualification_subject_digest"],
            self.record["qualification_subject_digest"])
        self.assertEqual(retained["unavailable_fields"], [])
        # every projected field has provenance recorded
        for field in execution_equality_subject(self.subject):
            if field == "backend":
                for key in self.subject["backend"]:
                    self.assertIn("backend." + key,
                                  retained["field_provenance"])
            else:
                self.assertIn(field, retained["field_provenance"], field)
        self.assertEqual(
            retained["terminal_adjudication"]["adjudication_sha256"], ADJUDICATION)

    def test_loader_rejects_a_tampered_retained_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = copy_evidence_root(Path(temp))
            retained = root / accepted_subject.ACCEPTED_SUBJECT_RECORD_RELATIVE_PATH
            retained.parent.mkdir(parents=True, exist_ok=True)
            document = accepted_subject.build_subject_record_document(root)
            subject = dict(document["qualification_subject"])
            subject["layer_count"] = 47  # tamper: materially different subject
            document["qualification_subject"] = subject
            document["qualification_subject_digest"] = subject_digest(subject)
            from issue99_artifact_core import self_digest
            document["record_digest"] = self_digest(
                document, identity_field="record_digest")
            retained.write_bytes(json.dumps(document, sort_keys=True,
                                            separators=(",", ":")).encode())
            with self.assertRaises(accepted_subject.SubjectReconstructionError):
                accepted_subject.load_accepted_v5_qualification_record(root)

    def test_loader_rejects_duplicate_conflicting_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = copy_evidence_root(Path(temp))
            evidence = root / "docs/implementation" / \
                "r6-successor-dense-full-integration-117" / "evidence"
            evidence.mkdir(parents=True, exist_ok=True)
            foreign = {
                "schema": accepted_subject.QUALIFICATION_RECORD_SCHEMA,
                "qualification_record_id": "conflicting/1",
                "qualification_subject": {"model_id": "foreign/model"},
                "qualification_subject_digest": "sha256:" + "3" * 64,
            }
            (evidence / "accepted-v5-qualification-subject-copy.json") \
                .write_text(json.dumps(foreign))
            with self.assertRaisesRegex(
                    accepted_subject.SubjectReconstructionError,
                    "duplicate/conflicting"):
                accepted_subject.load_accepted_v5_qualification_record(root)


class IndependenceTests(unittest.TestCase):
    """The strong independence test and structural purity proofs."""

    def test_reconstruction_module_imports_no_candidate_machinery(self):
        import ast
        source = (ROOT / "scripts" / "issue117_accepted_subject.py").read_text()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        banned = {"issue117_gemma_strategy", "issue117_planner",
                  "issue117_preflight", "issue117_proof",
                  "issue117_integration_fixture"}
        self.assertEqual(imported & banned, set(),
                         f"reconstruction imports candidate machinery: "
                         f"{imported & banned}")

    def test_candidate_construction_mutation_leaves_subject_unchanged(self):
        """STRONG INDEPENDENCE TEST (mandatory).

        Materially alter the current candidate-construction helper in test
        scope while holding historical evidence constant: the reconstructed
        accepted V5 subject and its digest must remain unchanged.
        """
        baseline = accepted_subject.accepted_v5_qualification_record(ROOT)
        baseline_digest = baseline["qualification_subject_digest"]

        # materially mutate the candidate-construction machinery in test scope
        original_geometry = strategy.ACCEPTED_V5_GEOMETRY
        original_model_subject = dict(strategy.MODEL_SUBJECT)
        original_layer_count = strategy.LAYER_COUNT
        original_balanced = strategy._balanced_stage_sizes
        try:
            strategy.ACCEPTED_V5_GEOMETRY = (
                {"cu_id": "inferswarm03/gpu-0", "layer_start": 0,
                 "layer_end": 24},
                {"cu_id": "inferswarm01/gpu-0", "layer_start": 24,
                 "layer_end": 48})
            strategy.MODEL_SUBJECT = {
                **strategy.MODEL_SUBJECT,
                "execution": "mutated execution semantics",
                "backend": {**strategy.MODEL_SUBJECT["backend"],
                            "torch": "9.9.9+cu999"},
            }
            strategy.LAYER_COUNT = 24
            strategy._balanced_stage_sizes = (
                lambda layers, stages: [1] * stages)
            # the reconstruction must ignore all of it
            mutated = accepted_subject.accepted_v5_qualification_record(ROOT)
            self.assertEqual(mutated["qualification_subject_digest"],
                             baseline_digest)
            self.assertEqual(
                mutated["qualification_subject"]["layer_count"], 48)
            self.assertEqual(
                mutated["qualification_subject"]["execution"],
                baseline["qualification_subject"]["execution"])
            self.assertEqual(
                mutated["qualification_subject"]["backend"]["torch"],
                "2.11.0+cu130")
            # and the canonical candidate machinery itself is materially
            # changed by the mutation (the control is non-vacuous)
            with self.assertRaises(strategy.StrategyError):
                strategy.canonical_v5_candidate()
        finally:
            strategy.ACCEPTED_V5_GEOMETRY = original_geometry
            strategy.MODEL_SUBJECT = original_model_subject
            strategy.LAYER_COUNT = original_layer_count
            strategy._balanced_stage_sizes = original_balanced
        # restored
        after = accepted_subject.accepted_v5_qualification_record(ROOT)
        self.assertEqual(after["qualification_subject_digest"], baseline_digest)

    def _tamper(self, relative: str, mutate):
        with tempfile.TemporaryDirectory() as temp:
            root = copy_evidence_root(Path(temp))
            path = root / relative
            mutate(path)
            accepted_subject.accepted_v5_qualification_record(root)

    def test_altering_accepted_historical_source_invalidates_subject(self):
        """Converse of the strong independence test (mandatory)."""
        cases = [
            ("docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json",
             "checkpoint authority mismatch"),
            ("docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json",
             "stage participant substitution"),
            ("docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json",
             "backend/runtime drift"),
            ("docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json",
             "terminal disposition drift"),
        ]
        for relative, label in cases:
            with self.subTest(case=label):
                def mutate(path, _relative=relative):
                    data = json.loads(path.read_text())
                    if "physical-subject" in _relative:
                        data["checkpoint_sha256"] = "7" * 64  # authority mismatch
                    elif "EXECUTION-AUTHORITY" in _relative:
                        data["topology"]["candidate"][0]["gpu_uuid"] = \
                            "GPU-substituted-0000"
                    elif "preflight-applicability" in _relative:
                        data["nodes"]["inferswarm01"]["stack"]["torch"] = \
                            "9.9.9+cu999"  # backend drift
                    else:
                        data["terminal"] = "V5_QUALIFICATION_FAIL"
                    path.write_text(json.dumps(data))
                with tempfile.TemporaryDirectory() as temp:
                    root = copy_evidence_root(Path(temp))
                    mutate(root / relative)
                    with self.assertRaises(
                            accepted_subject.SubjectReconstructionError):
                        accepted_subject.accepted_v5_qualification_record(root)

    def test_byte_drift_of_any_pinned_source_fails_closed(self):
        # control 11: accepted evidence source hash drift
        with tempfile.TemporaryDirectory() as temp:
            root = copy_evidence_root(Path(temp))
            # single-byte drift that keeps valid JSON
            path = root / ("docs/qualification/gemma4-12b-it-v5-campaign-110"
                           "/b/holdout-adjudication.json")
            data = json.loads(path.read_text())
            data["case_count"] = 25
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(
                    accepted_subject.SubjectReconstructionError, "drifted"):
                accepted_subject.accepted_v5_qualification_record(root)

    def test_missing_accepted_subject_source_blocks_applicability(self):
        # control 16: missing evidence source -> NOT_APPLICABLE everywhere
        with tempfile.TemporaryDirectory() as temp:
            root = copy_evidence_root(Path(temp))
            (root / "docs/qualification/gemma4-12b-it-v5/manifests"
             / "physical-subject.json").unlink()
            with self.assertRaises(accepted_subject.SubjectReconstructionError):
                accepted_subject.accepted_v5_qualification_record(root)
            from issue117_gemma_strategy import (
                QualificationAuthorityUnavailable,
                retained_v5_qualification_authority,
            )
            with self.assertRaises(QualificationAuthorityUnavailable):
                retained_v5_qualification_authority(root)
            from issue117_gemma_strategy import canonical_authority_catalog
            canonical = strategy.canonical_v5_candidate()
            derived = preflight.derive_candidate_applicability(
                [canonical], inferswarm_root=root)
            self.assertEqual(derived[canonical["candidate_id"]]["status"],
                             "QUALIFICATION_NOT_APPLICABLE")


class ApplicabilityTests(unittest.TestCase):
    """The canonical V5 candidate and every other legal candidate."""

    @classmethod
    def setUpClass(cls):
        cls.record = accepted_subject.accepted_v5_qualification_record(ROOT)
        cls.accepted_digest = cls.record["qualification_subject_digest"]

    def test_canonical_v5_candidate_is_applicable_by_subject_equality(self):
        canonical = strategy.canonical_v5_candidate(inferswarm_root=ROOT)
        self.assertEqual(canonical["qualification_subject_digest"],
                         self.accepted_digest)
        derived = preflight.derive_candidate_applicability([canonical])
        result = derived[canonical["candidate_id"]]
        self.assertEqual(result["status"], "QUALIFICATION_APPLICABLE")
        self.assertEqual(result["reason"],
                         planner.REASON_MATCHED_ACCEPTED_RECORD)
        self.assertEqual(result["matched_record_ids"],
                         [accepted_subject.ACCEPTED_RECORD_ID])

    def test_applicability_is_not_candidate_id_or_geometry_name(self):
        # a candidate with an arbitrary ID but the accepted execution
        # equality subject is applicable; the same ID with a foreign subject
        # is not: the digest comparison is the whole gate
        canonical = strategy.canonical_v5_candidate(inferswarm_root=ROOT)
        renamed = json.loads(json.dumps(canonical))
        renamed["candidate_id"] = "dense.aaaa00000000"
        derived = preflight.derive_candidate_applicability([renamed])
        self.assertEqual(derived[renamed["candidate_id"]]["status"],
                         "QUALIFICATION_APPLICABLE")
        foreign = json.loads(json.dumps(canonical))
        foreign["candidate_id"] = "dense.6171f32b4413"
        foreign["qualification_subject"] = {
            **foreign["qualification_subject"], "layer_count": 47}
        foreign["qualification_subject_digest"] = subject_digest(
            foreign["qualification_subject"])
        derived = preflight.derive_candidate_applicability([foreign])
        self.assertEqual(derived[foreign["candidate_id"]]["status"],
                         "QUALIFICATION_NOT_APPLICABLE")
        self.assertEqual(derived[foreign["candidate_id"]]["reason"],
                         planner.REASON_SUBJECT_MISMATCH)

    def test_every_other_legal_candidate_is_not_applicable(self):
        catalog = strategy.canonical_authority_catalog(inferswarm_root=ROOT)
        subject = strategy.subject_from_catalog(
            catalog, execution=strategy.MODEL_SUBJECT["execution"],
            backend=strategy.MODEL_SUBJECT["backend"])
        instance = strategy.GemmaDenseStrategy(
            catalog=catalog, subject=subject, source_manifest=None)
        candidates = instance.legal_candidates()
        self.assertGreater(len(candidates), 1)
        derived = preflight.derive_candidate_applicability(candidates)
        for candidate in candidates:
            status = derived[candidate["candidate_id"]]["status"]
            if candidate["qualification_subject_digest"] == self.accepted_digest:
                self.assertEqual(status, "QUALIFICATION_APPLICABLE",
                                 candidate["candidate_id"])
            else:
                self.assertEqual(status, "QUALIFICATION_NOT_APPLICABLE",
                                 candidate["candidate_id"])

    def test_checkpoint_authority_binding(self):
        # control 1: a checkpoint authority mismatch breaks equality
        canonical = strategy.canonical_v5_candidate(inferswarm_root=ROOT)
        wrong = json.loads(json.dumps(canonical))
        wrong["qualification_subject"]["checkpoint_authority_sha256"] = "5" * 64
        wrong["qualification_subject_digest"] = subject_digest(
            wrong["qualification_subject"])
        derived = preflight.derive_candidate_applicability([wrong])
        self.assertEqual(derived[wrong["candidate_id"]]["status"],
                         "QUALIFICATION_NOT_APPLICABLE")

    def test_every_single_field_drift_breaks_applicability(self):
        # controls 1-10: each acceptance-bearing field, mutated one at a
        # time, must break execution equality
        canonical = strategy.canonical_v5_candidate(inferswarm_root=ROOT)
        base = canonical["qualification_subject"]
        mutations = {
            "checkpoint authority mismatch":
                {"checkpoint_authority_sha256": "5" * 64},
            "revision mismatch": {"revision": "0" * 40},
            "representation mismatch": {"representation": "checkpoint-gguf"},
            "stage boundary change": {"stage_structure": [
                {**stage, "layer_end": stage["layer_end"] - 1,
                 "layer_start": max(stage["layer_start"],
                                    stage["layer_end"] - 17)}
                if index == 0 else stage
                for index, stage in enumerate(base["stage_structure"])]},
            "stage participant/device substitution": {"stage_structure": [
                {**stage, "cu_id": "inferswarm03/gpu-1",
                 "node": "inferswarm03"}
                if index == 1 else stage
                for index, stage in enumerate(base["stage_structure"])]},
            "gpu uuid substitution (via cu_id)": {"stage_structure": [
                {**stage, "cu_id": "inferswarm01/gpu-1"}
                if index == 0 else stage
                for index, stage in enumerate(base["stage_structure"])]},
            "backend/runtime version drift": {"backend": {
                **base["backend"], "triton": "3.7.0"}},
            "execution-mode/replay semantic drift": {"execution":
                "native BF16 text execution; Triton attention; one <=128-row "
                "replay chunk"},
            "precision drift": {"execution":
                "native FP16 text execution; Triton attention; one <=64-row "
                "replay chunk"},
            "attention/backend mode drift": {"execution":
                "native BF16 text execution; FlashInfer attention; one "
                "<=64-row replay chunk"},
        }
        for label, patch in mutations.items():
            with self.subTest(case=label):
                subject = {**base, **patch}
                digest = subject_digest(subject)
                self.assertNotEqual(digest, self.accepted_digest, label)
                candidate = {**canonical,
                             "qualification_subject": subject,
                             "qualification_subject_digest": digest}
                derived = preflight.derive_candidate_applicability([candidate])
                self.assertEqual(derived[candidate["candidate_id"]]["status"],
                                 "QUALIFICATION_NOT_APPLICABLE", label)

    def test_candidate_cannot_self_author_an_accepted_record(self):
        # control 15: a record the candidate constructs for itself, even
        # digest-bound and bound to the accepted adjudication identity, is
        # not retained evidence: the loader only accepts the derivation
        canonical = strategy.canonical_v5_candidate(inferswarm_root=ROOT)
        self_authored = strategy.build_qualification_record(
            qualification_record_id="self-authored/1",
            terminal_disposition="V5_QUALIFICATION_PASS",
            terminal_adjudication_sha256=ADJUDICATION,
            qualification_subject=dict(canonical["qualification_subject"]))
        # the generic evaluator alone would match it -- so the barrier must
        # come from WHERE the record comes from: the preflight derivation
        # ignores caller records entirely and loads only the evidence-derived
        # accepted record, whose identity is fixed
        derived = preflight.derive_candidate_applicability([canonical])
        self.assertEqual(
            derived[canonical["candidate_id"]]["matched_record_ids"],
            [accepted_subject.ACCEPTED_RECORD_ID])
        self.assertNotIn("self-authored/1",
                         derived[canonical["candidate_id"]]["matched_record_ids"])

    def test_synthetic_fixture_candidate_cannot_inherit_physical_qualification(self):
        # control 14: a full synthetic-fixture candidate carries a
        # fixture-scoped subject and never equals the accepted subject
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "fixture-repository"
            config, objects = strategy.build_synthetic_gemma_repository(repo)
            catalog = strategy.catalog_from_repository(
                repo, config=config, inferswarm_root=ROOT)
            subject = strategy.subject_from_catalog(
                catalog, execution=strategy.SYNTHETIC_SUBJECT_EXECUTION,
                backend=strategy.SYNTHETIC_SUBJECT_BACKEND)
            manifest = strategy.build_source_manifest(
                catalog, source_bytes=lambda name: objects[name])
            instance = strategy.GemmaDenseStrategy(
                catalog=catalog, subject=subject, source_manifest=manifest)
            candidates = instance.legal_candidates()
            derived = preflight.derive_candidate_applicability(candidates)
            for candidate in candidates:
                self.assertEqual(
                    derived[candidate["candidate_id"]]["status"],
                    "QUALIFICATION_NOT_APPLICABLE", candidate["candidate_id"])


class StrategyLoaderTests(unittest.TestCase):
    def test_strategy_loader_returns_the_evidence_record(self):
        record = strategy.retained_v5_qualification_authority(ROOT)
        self.assertEqual(record["qualification_record_id"],
                         accepted_subject.ACCEPTED_RECORD_ID)

    def test_strategy_loader_fails_closed_on_drifted_evidence(self):
        # control 12: accepted subject record/evidence tampering
        with tempfile.TemporaryDirectory() as temp:
            root = copy_evidence_root(Path(temp))
            path = root / ("docs/qualification/gemma4-12b-it-v2-campaign-81"
                           "/preflight-applicability.json")
            data = json.loads(path.read_text())
            data["nodes"]["inferswarm03"]["stack"]["flashinfer"] = "0.6.18"
            path.write_text(json.dumps(data))
            from issue117_gemma_strategy import QualificationAuthorityUnavailable
            with self.assertRaises(QualificationAuthorityUnavailable):
                strategy.retained_v5_qualification_authority(root)


if __name__ == "__main__":
    unittest.main()
