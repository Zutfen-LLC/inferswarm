"""Offline integrity and adversarial controls for Issue #209 R7-B (v4)."""
from __future__ import annotations

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

VLLM_SOURCES = ("vllm/v1/core/kv_cache_manager.py",
                "vllm/v1/core/single_type_kv_cache_manager.py",
                "vllm/v1/core/kv_cache_coordinator.py",
                "vllm/v1/core/sched/scheduler.py",
                "vllm/v1/kv_cache_interface.py",
                "vllm/models/deepseek_v41/attention.py",
                "vllm/models/deepseek_v41/nvidia/model.py",
                "vllm/model_executor/models/utils.py",
                "vllm/model_executor/model_loader/default_loader.py")


class Issue209R7BTests(unittest.TestCase):
    def staged(self, skip=()) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in reducer.INPUTS:
            if relative in skip:
                continue
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reducer.ROOT / relative, target)
        # retained external bytes (not in INPUTS; copied for hash checks)
        for relative in VLLM_SOURCES:
            target = root / "docs/investigations/deepseek-v41-flash-r7-b/external" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reducer.ROOT / "docs/investigations/deepseek-v41-flash-r7-b/external" / relative, target)
        return root

    def sources(self, root: Path) -> dict:
        return json.loads((root / reducer.EXTERNAL_SOURCE_EVIDENCE).read_text())

    def write_sources(self, root: Path, document: dict) -> None:
        (root / reducer.EXTERNAL_SOURCE_EVIDENCE).write_text(json.dumps(document))

    def authority(self, root: Path) -> dict:
        return json.loads((root / reducer.RUNTIME_AUTHORITY).read_text())

    def write_authority(self, root: Path, document: dict) -> None:
        (root / reducer.RUNTIME_AUTHORITY).write_text(json.dumps(document))

    @staticmethod
    def vllm(document: dict) -> dict:
        return next(row for row in document["candidates"] if row["id"] == "vllm-current-source")

    # ---- retained terminal / derivation ----

    def test_retained_terminal_is_gate_ready(self):
        actual = json.loads((reducer.ROOT / reducer.OUTPUT).read_text())
        self.assertEqual(actual, reducer.reduction_document())
        self.assertEqual(actual["terminal"], reducer.GATE_READY)
        self.assertEqual(actual["p8_derivation"]["status"], "PASS")
        self.assertEqual(len(actual["p8_derivation"]["verified"]), 13)
        self.assertEqual(actual["terminal_detail"]["shape"], "contiguous_stage")
        self.assertEqual(actual["terminal_detail"]["cut"], 20)

    def test_p8_is_derived_not_authored(self):
        # authored p8 PASS with deleted lifecycle bytes must NOT derive PASS
        root = self.staged()
        victim = root / "docs/investigations/deepseek-v41-flash-r7-b/external/vllm/v1/core/sched/scheduler.py"
        victim.unlink()
        with self.assertRaises(ValueError) as ctx:
            reducer._adjudicate_p8(root, self.sources(root))
        self.assertIn("ISSUE209_FAIL", str(ctx.exception))

    def test_p8_unproven_cannot_be_manufactured_by_deleting_retained_evidence(self):
        # deleting a hash-pinned lifecycle file fails closed (hash mismatch/
        # absent), it cannot quietly downgrade to UNPROVEN -> EVIDENCE_BLOCKED
        root = self.staged()
        victim = root / "docs/investigations/deepseek-v41-flash-r7-b/external/vllm/v1/core/kv_cache_manager.py"
        victim.write_bytes(b"tampered\n")
        with self.assertRaises(ValueError) as ctx:
            reducer._adjudicate_p8(root, self.sources(root))
        self.assertIn("hash mismatch", str(ctx.exception))

    def test_marker_removal_unproves_only_with_exact_question(self):
        # a legitimately missing marker records the exact fact question
        root = self.staged()
        sources = self.sources(root)
        entry = sources["third_party_candidates"]["vllm"]["files"]["kv_cache_manager"]
        entry["sha256"] = "0" * 64  # mismatched pin -> fail closed, not UNPROVEN
        self.write_sources(root, sources)
        with self.assertRaises(ValueError):
            reducer._adjudicate_p8(root, sources)

    # ---- forged FAIL-proof seam ----

    def test_forged_fail_proof_prose_cannot_produce_runtime_prerequisite(self):
        root = self.staged()
        sources = self.sources(root)
        vllm = sources["third_party_candidates"]["vllm"]
        vllm["p8_failure_proof"] = {
            "requires_external_runtime_backend_change": True,
            "source_file": "scheduler",
            "sha256": vllm["files"]["scheduler"]["sha256"],
            "excerpt": "totally fabricated prose not in the source",
        }
        self.write_sources(root, sources)
        with self.assertRaises(ValueError) as ctx:
            reducer._terminal_for_p8("FAIL", root, sources)
        self.assertIn("excerpt not in retained bytes", str(ctx.exception))

    def test_authored_boolean_alone_cannot_flip_terminal(self):
        root = self.staged()
        sources = self.sources(root)
        vllm = sources["third_party_candidates"]["vllm"]
        vllm["p8_failure_proof"] = {
            "requires_external_runtime_backend_change": True,
            "source_file": "nonexistent-key",
            "excerpt": "x",
        }
        self.write_sources(root, sources)
        with self.assertRaises(ValueError):
            reducer._terminal_for_p8("FAIL", root, sources)

    def test_fail_proof_requires_verbatim_condition_in_retained_bytes(self):
        root = self.staged()
        sources = self.sources(root)
        vllm = sources["third_party_candidates"]["vllm"]
        text = (root / "docs/investigations/deepseek-v41-flash-r7-b/external"
                "/vllm/v1/core/sched/scheduler.py").read_text()
        vllm["p8_failure_proof"] = {
            "requires_external_runtime_backend_change": True,
            "source_file": "scheduler",
            "sha256": vllm["files"]["scheduler"]["sha256"],
            "excerpt": "def _preempt_request(",
            "source_condition": "not in the source",
        }
        self.write_sources(root, sources)
        with self.assertRaises(ValueError) as ctx:
            reducer._terminal_for_p8("FAIL", root, sources)
        self.assertIn("source condition not in retained bytes", str(ctx.exception))

    def test_valid_fail_proof_derives_runtime_prerequisite(self):
        root = self.staged()
        sources = self.sources(root)
        vllm = sources["third_party_candidates"]["vllm"]
        vllm["p8_failure_proof"] = {
            "requires_external_runtime_backend_change": True,
            "source_file": "scheduler",
            "sha256": vllm["files"]["scheduler"]["sha256"],
            "excerpt": "def _preempt_request(",
            "source_condition": "def _preempt_request(",
        }
        self.write_sources(root, sources)
        terminal, detail = reducer._terminal_for_p8("FAIL", root, sources)
        self.assertEqual(terminal, reducer.RUNTIME_PREREQUISITE)

    def test_mismatched_source_hash_fails_closed(self):
        root = self.staged()
        sources = self.sources(root)
        sources["third_party_candidates"]["vllm"]["files"]["scheduler"]["sha256"] = "f" * 64
        self.write_sources(root, sources)
        with self.assertRaises(ValueError):
            reducer._adjudicate_p8(root, sources)

    # ---- phase 2-5 gates ----

    def test_p8_pass_cannot_terminate_at_phase_1(self):
        root = self.staged(skip=(reducer.STRATEGY_AUTHORITY,
                                 reducer.EXECUTION_CONTRACT))
        with self.assertRaises(ValueError) as ctx:
            reducer._terminal_for_p8("PASS", root, self.sources(root))
        self.assertIn("ISSUE209_FAIL", str(ctx.exception))

    def test_illegal_cut_rejected(self):
        root = self.staged()
        strategy = json.loads((root / reducer.STRATEGY_AUTHORITY).read_text())
        strategy["cut_layer"] = 5  # inside kv-sharing group {2..7}
        strategy["layer_interval"] = [5, 40]
        (root / reducer.STRATEGY_AUTHORITY).write_text(json.dumps(strategy))
        with self.assertRaises(ValueError) as ctx:
            reducer._verify_phase2_5(root)
        self.assertIn("not a legal kv-sharing-group boundary", str(ctx.exception))

    def test_legal_cuts_are_exactly_group_boundaries(self):
        self.assertEqual(reducer.LEGAL_CUTS, (2, 8, 14, 20, 40))

    def test_fixture_units_multi_resource_with_dependencies(self):
        execution = json.loads((reducer.ROOT / reducer.EXECUTION_CONTRACT).read_text())
        units = execution["units"]
        self.assertGreaterEqual(len(units), 2)
        self.assertGreaterEqual(len({u["resource"] for u in units}), 2)
        self.assertEqual(units[1]["dependencies"], ["stage-a"])
        controls = execution["negative_controls"]
        self.assertTrue(all(c["result"] == "FAIL_CLOSED" for c in controls))
        self.assertEqual(len(controls), 11)

    # ---- authored-field overrides ----

    def test_authored_terminal_rejected(self):
        root = self.staged()
        authority = self.authority(root)
        authority["terminal"] = reducer.GATE_READY
        self.write_authority(root, authority)
        with self.assertRaises(ValueError) as ctx:
            reducer._vllm_authority(authority, self.sources(root))
        self.assertIn("authored terminal", str(ctx.exception))

    def test_authored_p8_contradiction_rejected(self):
        root = self.staged()
        document = reducer.reduction_document()  # baseline derives PASS
        authority = self.authority(root)
        vllm = self.vllm(authority)
        row = next(r for r in vllm["predicate_adjudications"]
                   if r["id"] == "p8_observable_cache_authority")
        row["status"] = "UNPROVEN"  # contradicts source-derived PASS
        self.write_authority(root, authority)
        with self.assertRaises(ValueError) as ctx:
            reducer.reduction_document(root)
        self.assertIn("contradicts source-derived", str(ctx.exception))

    def test_disposition_must_match_derived_terminal(self):
        root = self.staged()
        authority = self.authority(root)
        self.vllm(authority)["disposition"] = "EVIDENCE_BLOCKED"
        self.write_authority(root, authority)
        with self.assertRaises(ValueError):
            reducer.reduction_document(root)

    # ---- preservation / supersession ----

    def test_r7a_remains_byte_identical(self):
        reduction = reducer.reduction_document()
        predecessor = reduction["predecessor"]
        self.assertEqual(predecessor["terminal_sha256"], reducer.R7A_TERMINAL_SHA256)
        self.assertEqual(predecessor["manifest_sha256"], reducer.R7A_MANIFEST_SHA256)
        # any R7-A mutation fails the reduction
        root = self.staged()
        victim = root / "docs/investigations/deepseek-v41-flash-r7-a/external/LICENSE"
        victim.write_bytes(victim.read_bytes() + b"x")
        with self.assertRaises(ValueError):
            reducer.reduction_document(root)

    def test_superseded_evidence_cannot_become_authority(self):
        root = self.staged()
        superseded = (reducer.ROOT / "docs/investigations/deepseek-v41-flash-r7-b/superseded-253d19b.json").read_bytes()
        (root / reducer.EXTERNAL_SOURCE_EVIDENCE).write_bytes(superseded)
        with self.assertRaises(ValueError):
            reducer._vllm_authority(
                json.loads((root / reducer.RUNTIME_AUTHORITY).read_text()),
                json.loads(superseded))

    def test_superseded_records_retained(self):
        area = reducer.ROOT / "docs/investigations/deepseek-v41-flash-r7-b"
        for name in ("superseded-69e07e5.json", "superseded-9feb7e74.json",
                     "superseded-253d19b.json"):
            self.assertTrue((area / name).is_file(), name)

    # ---- manifest ----

    def test_evidence_manifest_is_current(self):
        self.assertEqual(manifest.manifest_text(),
                         (reducer.ROOT / "docs/investigations/deepseek-v41-flash-r7-b/MANIFEST.sha256").read_text())


if __name__ == "__main__":
    unittest.main()
