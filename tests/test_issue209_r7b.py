"""Offline integrity and adversarial controls for Issue #209 R7-B."""
from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue209_r7b_manifest as manifest  # noqa: E402
import issue209_r7b_reducer as reducer  # noqa: E402


class Issue209R7BTests(unittest.TestCase):
    def staged(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in reducer.INPUTS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reducer.ROOT / relative, target)
        return root

    def authority(self, root: Path) -> dict:
        return json.loads((root / reducer.RUNTIME_AUTHORITY).read_text())

    def write_authority(self, root: Path, document: dict) -> None:
        (root / reducer.RUNTIME_AUTHORITY).write_text(json.dumps(document))

    @staticmethod
    def vllm(document: dict) -> dict:
        return next(row for row in document["candidates"] if row["id"] == "vllm-current-source")

    def test_retained_terminal_is_evidence_blocked(self):
        actual = json.loads((reducer.ROOT / reducer.OUTPUT).read_text())
        self.assertEqual(actual, reducer.reduction_document())
        self.assertEqual(actual["terminal"], reducer.EVIDENCE_BLOCKED)
        self.assertEqual(actual["blocking_seam"]["predicate"], "p8_observable_cache_authority")
        statuses = {row["id"]: row["status"]
                    for row in actual["runtime"]["predicate_adjudications"]}
        self.assertEqual(statuses, reducer.EXPECTED_STATUS)

    def test_loader_and_pp_source_facts_cannot_be_falsely_rejected(self):
        terminal = reducer.reduction_document()
        rows = {row["id"]: row for row in terminal["runtime"]["predicate_adjudications"]}
        for predicate in ("p4_native_official_sharded_safetensors",
                          "p5_no_mandatory_representation_conversion",
                          "p7_selective_materialization_control",
                          "p9_one_legal_multi_resource_shape"):
            self.assertEqual(rows[predicate]["status"], "PASS")
        self.assertIn("model.safetensors.index.json", rows["p4_native_official_sharded_safetensors"]["evidence"][0])
        source = json.loads((reducer.ROOT / reducer.EXTERNAL_SOURCE_EVIDENCE).read_text())
        utils = "\n".join(source["third_party_candidates"]["vllm"]["files"]["utils"]["excerpts"])
        model = "\n".join(source["third_party_candidates"]["vllm"]["files"]["model"]["excerpts"])
        self.assertIn("PPMissingLayer", utils)
        self.assertIn("IntermediateTensors", model)

    def test_source_bound_predicates_cannot_be_downgraded_by_authored_disposition(self):
        for predicate in ("p4_native_official_sharded_safetensors",
                          "p5_no_mandatory_representation_conversion",
                          "p7_selective_materialization_control",
                          "p9_one_legal_multi_resource_shape"):
            with self.subTest(predicate=predicate):
                root = self.staged()
                document = self.authority(root)
                row = next(row for row in self.vllm(document)["predicate_adjudications"]
                           if row["id"] == predicate)
                row["status"] = "FAIL"
                self.write_authority(root, document)
                with self.assertRaisesRegex(ValueError, "predicate disposition contradicts pinned source"):
                    reducer.reduction_document(root)

    def test_cache_pass_cannot_stop_at_phase_one_terminal(self):
        root = self.staged()
        document = self.authority(root)
        row = next(row for row in self.vllm(document)["predicate_adjudications"]
                   if row["id"] == "p8_observable_cache_authority")
        row["status"] = "PASS"
        self.write_authority(root, document)
        with self.assertRaisesRegex(ValueError, "p8 PASS requires Phase 2-5"):
            reducer.reduction_document(root)

    def test_unproven_cache_always_derives_evidence_blocked(self):
        root = self.staged()
        document = self.authority(root)
        row = next(row for row in self.vllm(document)["predicate_adjudications"]
                   if row["id"] == "p8_observable_cache_authority")
        row["evidence"] = ["request/session lifetime, invalidation, and reconstruction remain insufficient"]
        self.write_authority(root, document)
        self.assertEqual(reducer.reduction_document(root)["terminal"], reducer.EVIDENCE_BLOCKED)

    def test_p8_fail_requires_pinned_external_change_proof(self):
        root = self.staged()
        document = self.authority(root)
        row = next(row for row in self.vllm(document)["predicate_adjudications"]
                   if row["id"] == "p8_observable_cache_authority")
        row["status"] = "FAIL"
        row["evidence"] = ["pinned source proves the capability is absent"]
        self.vllm(document)["disposition"] = "REJECTED"
        self.write_authority(root, document)
        with self.assertRaisesRegex(ValueError, "lacks retained external runtime/backend-change proof"):
            reducer.reduction_document(root)
        sources = json.loads((root / reducer.EXTERNAL_SOURCE_EVIDENCE).read_text())
        attention = sources["third_party_candidates"]["vllm"]["files"]["attention"]
        sources["third_party_candidates"]["vllm"]["p8_failure_proof"] = {
            "source_file": "attention", "sha256": attention["sha256"],
            "excerpt": "concrete pinned absence requires external runtime/backend change",
            "requires_external_runtime_backend_change": True,
        }
        (root / reducer.EXTERNAL_SOURCE_EVIDENCE).write_text(json.dumps(sources))
        self.assertEqual(reducer.reduction_document(root)["terminal"], reducer.RUNTIME_PREREQUISITE)

    def test_authored_terminal_cannot_override_predicates(self):
        root = self.staged()
        document = self.authority(root)
        document["terminal"] = reducer.RUNTIME_PREREQUISITE
        self.write_authority(root, document)
        with self.assertRaisesRegex(ValueError, "authored terminal is not an input"):
            reducer.reduction_document(root)

    def test_cache_seam_must_name_lifetime_invalidation_and_reconstruction(self):
        root = self.staged()
        document = self.authority(root)
        row = next(row for row in self.vllm(document)["predicate_adjudications"]
                   if row["id"] == "p8_observable_cache_authority")
        row["evidence"] = ["attention ownership only"]
        self.write_authority(root, document)
        with self.assertRaisesRegex(ValueError, "cache lifecycle seam is not explicit"):
            reducer.reduction_document(root)

    def test_pinned_source_and_r7a_drift_fail_closed(self):
        root = self.staged()
        path = root / reducer.EXTERNAL_SOURCE_EVIDENCE
        document = json.loads(path.read_text())
        document["third_party_candidates"]["vllm"]["files"]["attention"]["sha256"] = "forged"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "pinned vLLM source drift"):
            reducer.reduction_document(root)
        root = self.staged()
        path = root / reducer.R7A_MANIFEST
        path.write_bytes(path.read_bytes() + b"forged")
        with self.assertRaisesRegex(ValueError, "R7-A manifest drift"):
            reducer.reduction_document(root)

    def test_static_reducer_does_not_import_runtime_or_execute_a_model(self):
        forbidden = {"torch", "transformers", "subprocess", "vllm"}
        tree = ast.parse((SCRIPTS / "issue209_r7b_reducer.py").read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports |= {alias.name.split(".")[0] for alias in node.names}
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertFalse(imports & forbidden)

    def test_evidence_manifest_is_current_and_repository_relative(self):
        actual = (manifest.ROOT / manifest.OUTPUT).read_text()
        self.assertEqual(actual, manifest.manifest_text())
        for line in actual.splitlines():
            _, separator, relative = line.partition("  ")
            self.assertEqual(separator, "  ")
            self.assertTrue((manifest.ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
