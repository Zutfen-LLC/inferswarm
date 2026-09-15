"""Offline integrity and negative controls for Issue #187's static census."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue187_r7a_reducer as reducer  # noqa: E402


class Issue187R7ATests(unittest.TestCase):
    def staged(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for relative in (reducer.INVENTORY, reducer.CENSUS, reducer.STATE):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reducer.ROOT / relative, target)
        return root

    def test_retained_terminal_is_current(self):
        actual = json.loads((reducer.ROOT / reducer.OUTPUT).read_text())
        self.assertEqual(actual, reducer.reduction_document())

    def test_no_model_runtime_or_execution_imported_by_reducer(self):
        source = (SCRIPTS / "issue187_r7a_reducer.py").read_text()
        for forbidden in ("torch", "transformers", "subprocess", "cuda"):
            self.assertNotIn(forbidden, source.lower())

    def test_stale_revision_fails_closed(self):
        root = self.staged()
        path = root / reducer.STATE
        document = json.loads(path.read_text())
        document["revision"] = "stale"
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "stale external revision"):
            reducer.reduction_document(root)

    def test_duplicate_tensor_fails_closed(self):
        root = self.staged()
        path = root / reducer.CENSUS
        document = json.loads(path.read_text())
        document["tensors"][1]["name"] = document["tensors"][0]["name"]
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "tensor duplication"):
            reducer.reduction_document(root)

    def test_aggregate_vram_is_not_a_feasibility_claim(self):
        document = reducer.reduction_document()
        self.assertEqual(document["terminal"], reducer.TERMINAL)
        self.assertFalse(document["fleet_fit"]["official_checkpoint_fits_one_resource"])
        self.assertEqual(document["fleet_fit"]["capacity_feasible"], "NOT_ESTABLISHED")
        self.assertEqual(document["fleet_fit"]["correctness_qualified"], "NOT_ESTABLISHED")

    def test_terminal_names_the_bounded_substrate_contract(self):
        document = reducer.reduction_document()
        contract = document["substrate_prerequisite"]
        self.assertEqual(contract["model"]["revision"], reducer.REVISION)
        self.assertEqual(contract["model"]["scope"], "text-only")
        self.assertIn("official sharded safetensors", contract["representation"]["required"])
        self.assertEqual(document["decomposition"]["evidence_supported_candidates"],
                         ["contiguous_stage", "expert_local"])
        self.assertEqual(document["decomposition"]["hybrid_stage_expert"],
                         "RUNTIME_BACKEND_PREREQUISITE")
        self.assertIn("vision/aligner support", contract["not_required"])

    def test_manifest_rows_are_repository_relative(self):
        manifest = reducer.ROOT / reducer.AREA / "MANIFEST.sha256"
        for line in manifest.read_text().splitlines():
            _, separator, relative = line.partition("  ")
            self.assertEqual(separator, "  ")
            self.assertTrue((reducer.ROOT / relative).is_file(), relative)

    def test_expert_count_assumption_fails_closed(self):
        root = self.staged()
        path = root / reducer.STATE
        document = json.loads(path.read_text())
        document["config"]["n_activated_experts"] = 7
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "unsupported inference assumption"):
            reducer.reduction_document(root)


if __name__ == "__main__":
    unittest.main()
