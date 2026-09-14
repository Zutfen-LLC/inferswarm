"""Issue #189 static R8-A authority and terminal-reduction tests."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue189_r8a_reducer as reducer  # noqa: E402


class Issue189R8ATests(unittest.TestCase):
    def test_retained_terminal_is_current(self):
        expected = reducer.reduction_document()
        actual = json.loads((reducer.ROOT / reducer.OUTPUT).read_text())
        self.assertEqual(actual, expected)

    def test_authorities_remain_separate(self):
        document = reducer.reduction_document()
        authority = document["source_authority"]
        self.assertNotEqual(authority["official_revision"],
                            authority["third_party_gguf_revision"])
        self.assertEqual(document["representation"]["complete_split_files"], 3)

    def test_terminal_fails_closed_without_complete_source_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / reducer.SOURCE
            source.parent.mkdir(parents=True)
            original = (reducer.ROOT / reducer.SOURCE).read_text()
            source.write_text(original.replace(reducer.GGUF_REVISION, "drift"))
            with self.assertRaisesRegex(ValueError, "source-authority fact missing"):
                reducer.reduction_document(root)

    def test_no_execution_authorization_is_smuggled_into_terminal(self):
        document = reducer.reduction_document()
        self.assertEqual(document["terminal"], "R8A_QWEN38_RUNTIME_PREREQUISITE")
        self.assertEqual(document["fleet_fit"]["correctness_qualified"],
                         "NOT_ESTABLISHED")
        self.assertTrue(any("not acceptance" in claim.lower()
                            for claim in document["non_claims"]))

    def test_reducer_never_imports_a_model_runtime(self):
        source = (SCRIPTS / "issue189_r8a_reducer.py").read_text()
        for forbidden in ("torch", "transformers", "llama_cpp", "subprocess"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
