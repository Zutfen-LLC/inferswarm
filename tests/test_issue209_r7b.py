"""Offline integrity and negative controls for Issue #209's substrate audit."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue209_r7b_reducer as reducer  # noqa: E402
import issue209_r7b_manifest as manifest  # noqa: E402


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

    def test_retained_terminal_is_current(self):
        actual = json.loads((reducer.ROOT / reducer.OUTPUT).read_text())
        self.assertEqual(actual, reducer.reduction_document())

    def test_official_runtime_conversion_disqualifies_native_subject_claim(self):
        document = reducer.reduction_document()
        candidate = document["candidate_dispositions"][0]
        self.assertEqual(candidate["id"], "official-reference-runtime")
        self.assertEqual(candidate["disposition"], "REJECTED")
        self.assertIn("p4_native_official_sharded_safetensors",
                      candidate["failed_predicates"])
        self.assertEqual(document["terminal"], reducer.TERMINAL)

    def test_source_revision_drift_fails_closed(self):
        root = self.staged()
        path = root / reducer.RUNTIME_AUTHORITY
        document = json.loads(path.read_text())
        document["candidates"][0]["revision"] = "drifted"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "runtime revision drift"):
            reducer.reduction_document(root)

    def test_loader_that_accepts_official_shards_cannot_be_falsely_rejected(self):
        root = self.staged()
        path = root / reducer.RUNTIME_AUTHORITY
        document = json.loads(path.read_text())
        candidate = document["candidates"][0]
        candidate["loader_contract"] = "official-sharded-safetensors-index"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "candidate disposition contradicts loader contract"):
            reducer.reduction_document(root)

    def test_wrong_predecessor_terminal_fails_closed(self):
        root = self.staged()
        path = root / reducer.R7A_TERMINAL
        document = json.loads(path.read_text())
        document["terminal"] = "forged"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "R7-A terminal drift"):
            reducer.reduction_document(root)

    def test_nonsemantic_predecessor_terminal_edit_fails_closed(self):
        root = self.staged()
        path = root / reducer.R7A_TERMINAL
        document = json.loads(path.read_text())
        document["non_claims"].append("forged extra claim")
        path.write_text(json.dumps(document, sort_keys=True))
        with self.assertRaisesRegex(ValueError, "R7-A terminal content drift"):
            reducer.reduction_document(root)

    def test_predecessor_manifest_and_source_drift_fail_closed(self):
        for relative, expected in (
            (reducer.R7A_MANIFEST, "R7-A manifest drift"),
            (next(iter(reducer.R7A_RETAINED_FILES)), "R7-A retained source drift"),
        ):
            with self.subTest(relative=relative):
                root = self.staged()
                path = root / relative
                path.write_bytes(path.read_bytes() + b"forged")
                with self.assertRaisesRegex(ValueError, expected):
                    reducer.reduction_document(root)

    def test_external_source_evidence_drift_fails_closed(self):
        root = self.staged()
        path = root / reducer.EXTERNAL_SOURCE_EVIDENCE
        document = json.loads(path.read_text())
        document["third_party_candidates"]["vllm"]["revision"] = "forged"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "candidate source revision drift"):
            reducer.reduction_document(root)

    def test_pinned_candidate_authority_drift_fails_closed(self):
        root = self.staged()
        path = root / reducer.RUNTIME_AUTHORITY
        document = json.loads(path.read_text())
        document["candidates"][1]["revision"] = "forged"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "candidate authority inventory drift"):
            reducer.reduction_document(root)

    def test_no_model_runtime_or_execution_is_imported(self):
        source = (SCRIPTS / "issue209_r7b_reducer.py").read_text().lower()
        for forbidden in ("import torch", "import transformers", "import subprocess", "cuda"):
            self.assertNotIn(forbidden, source)

    def test_evidence_manifest_is_current_and_repository_relative(self):
        actual = (manifest.ROOT / manifest.OUTPUT).read_text()
        self.assertEqual(actual, manifest.manifest_text())
        for line in actual.splitlines():
            _, separator, relative = line.partition("  ")
            self.assertEqual(separator, "  ")
            self.assertTrue((manifest.ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
