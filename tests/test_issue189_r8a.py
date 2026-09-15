"""Issue #189 static R8-A authority and terminal-reduction tests.

Covers the three retained authorities (source findings, GGUF object census,
GGUF header/tensor census, hardware census), the terminal reduction, and
the negative/mutation controls required by the Issue #189 correction round
(maintainer review comment 5672736372).
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import issue189_r8a_reducer as reducer  # noqa: E402

ROOT = reducer.ROOT
AREA_PATH = ROOT / reducer.AREA


def staged_root(testcase: unittest.TestCase) -> Path:
    """Copy every authority into a temp root for mutation tests."""
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    for relative in (reducer.SOURCE, reducer.CENSUS, reducer.HEADER_CENSUS,
                     reducer.HARDWARE):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    raw = root / reducer.AREA / "raw-headers"
    raw.mkdir(parents=True, exist_ok=True)
    for entry in (AREA_PATH / "raw-headers").iterdir():
        (raw / entry.name).write_bytes(entry.read_bytes())
    return root


class Issue189R8ATests(unittest.TestCase):
    def test_retained_terminal_is_current(self):
        expected = reducer.reduction_document()
        actual = json.loads((ROOT / reducer.OUTPUT).read_text())
        self.assertEqual(actual, expected)

    def test_authorities_remain_separate(self):
        document = reducer.reduction_document()
        authority = document["source_authority"]
        self.assertNotEqual(authority["official_revision"],
                            authority["third_party_gguf_revision"])
        self.assertEqual(document["runtime_audit_revision"],
                         reducer.RUNTIME_AUDIT_REVISION)
        self.assertEqual(document["representation"]["complete_split_files"], 3)

    def test_terminal_fails_closed_without_complete_source_authority(self):
        root = staged_root(self)
        original = (ROOT / reducer.SOURCE).read_text()
        (root / reducer.SOURCE).write_text(
            original.replace(reducer.GGUF_REVISION, "drift"))
        with self.assertRaisesRegex(ValueError, "source-authority fact missing"):
            reducer.reduction_document(root)

    def test_reducer_requires_every_selected_split_object(self):
        root = staged_root(self)
        census_path = root / reducer.CENSUS
        census = json.loads(census_path.read_text())
        census["files"] = census["files"][1:]
        census_path.write_text(json.dumps(census))
        with self.assertRaisesRegex(ValueError, "incomplete GGUF object inventory"):
            reducer.reduction_document(root)

    def test_reducer_fails_closed_when_runtime_classification_or_mode_drifts(self):
        original = (ROOT / reducer.SOURCE).read_text()
        for expected in (reducer.RPC_CLASSIFICATION, *reducer.RPC_MODE_SOURCE_FACTS):
            with self.subTest(expected=expected):
                root = staged_root(self)
                (root / reducer.SOURCE).write_text(
                    original.replace(expected, "drift", 1))
                with self.assertRaisesRegex(ValueError, "source-authority fact missing"):
                    reducer.reduction_document(root)

    def test_no_execution_authorization_is_smuggled_into_terminal(self):
        document = reducer.reduction_document()
        self.assertEqual(document["terminal"], "R8A_QWEN38_RUNTIME_PREREQUISITE")
        self.assertEqual(document["fleet_fit"]["correctness_qualified"],
                         "NOT_ESTABLISHED")
        self.assertEqual(
            document["fleet_fit"]["r8_runtime_mode_qualified_capacity_bytes"], 0)
        self.assertTrue(any("not acceptance" in claim.lower()
                            for claim in document["non_claims"]))

    def test_reducer_never_imports_a_model_runtime(self):
        source = (SCRIPTS / "issue189_r8a_reducer.py").read_text()
        for forbidden in ("torch", "transformers", "llama_cpp", "subprocess"):
            self.assertNotIn(forbidden, source)

    def test_no_authored_fleet_constant_survives(self):
        source = (SCRIPTS / "issue189_r8a_reducer.py").read_text()
        self.assertNotIn("VERIFIED_NVIDIA_WEIGHT_BYTES", source)
        self.assertNotIn("72 * 1024**3", source)
        for constant in ("80 * 1024**3", "96 * 1024**3", "120 * 1024**3"):
            self.assertNotIn(constant, source)

    # ------------------------------------------------------------------
    # Hardware-census mutation controls
    # ------------------------------------------------------------------

    def _mutate_hardware(self, mutate):
        root = staged_root(self)
        path = root / reducer.HARDWARE
        document = json.loads(path.read_text())
        mutate(document)
        path.write_text(json.dumps(document, indent=1))
        return root

    def test_gpu_disappearing_from_inventory_fails_closed(self):
        def mutate(document):
            document["resources"] = [
                r for r in document["resources"]
                if r.get("bdf") != "0000:01:00.0" or r.get("host") != "inferswarm04"]
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "census totals disagree"):
            reducer.reduction_document(root)

    def test_vram_change_fails_closed(self):
        def mutate(document):
            for r in document["resources"]:
                if r.get("host") == "inferswarm04" and r.get("bdf") == "0000:01:00.0":
                    r["memory_bytes"] = 2 * 1024**3
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "census totals disagree"):
            reducer.reduction_document(root)

    def test_resource_incorrectly_marked_qualified_fails_closed(self):
        def mutate(document):
            document["resources"][0]["status"] = (
                "DEPLOYED_QUALIFIED_FOR_RELEVANT_BACKEND")
        root = self._mutate_hardware(mutate)
        # Status change alone does not alter derivation; the R8-qualified
        # subset must stay empty regardless of labels.
        document = reducer.reduction_document(root)
        self.assertEqual(
            document["fleet_fit"]["r8_runtime_mode_qualified_capacity_bytes"], 0)
        self.assertEqual(document["fleet_fit"]["correctness_qualified"],
                         "NOT_ESTABLISHED")

    def test_pending_device_counted_as_deployed_fails_closed(self):
        def mutate(document):
            for r in document["resources"]:
                if r.get("resource_id") == "pending-amd-radeon-pro-v340l":
                    r["memory_bytes"] = 2 * 8589934592
                    r["status"] = "DEPLOYED_AVAILABLE"
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(
                ValueError, "census totals disagree|pending hardware must be zero"):
            reducer.reduction_document(root)

    def test_pending_device_carrying_bytes_fails_closed(self):
        def mutate(document):
            for r in document["resources"]:
                if r.get("resource_id") == "pending-amd-radeon-pro-v340l":
                    r["memory_bytes"] = 17179869184  # stays PENDING
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "pending resource carries"):
            reducer.reduction_document(root)

    def test_v340l_flattened_to_single_16gib_space_fails_closed(self):
        def mutate(document):
            for r in document["resources"]:
                if r.get("resource_id") == "pending-amd-radeon-pro-v340l":
                    r["modeling_note"] = (
                        "single 16 GiB allocation across one device address space")
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "V340L not modeled"):
            reducer.reduction_document(root)

    def test_amd_resource_silent_omission_fails_closed(self):
        def mutate(document):
            # silent: rows vanish while the stored totals still claim AMD bytes
            document["resources"] = [
                r for r in document["resources"]
                if not str(r.get("vendor_device", "")).startswith("1002")]
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "census totals disagree"):
            reducer.reduction_document(root)

    def test_amd_consistent_forgery_boundary_is_pinned(self):
        # A fully consistent forgery (rows AND totals rewritten together) is
        # outside a self-contained reducer's boundary by construction; the
        # defense is that hardware-census.json is digest-pinned inside the
        # retained terminal record and covered by the bundle manifest.
        document = reducer.reduction_document()
        self.assertIn("hardware_census_sha256", document["source_authority"])
        self.assertEqual(
            document["source_authority"]["hardware_census_sha256"],
            reducer.sha256_file(ROOT / reducer.HARDWARE))

    def test_deployed_row_without_measured_memory_fails_closed(self):
        def mutate(document):
            document["resources"][0]["memory_source"] = None
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "lacks measured memory"):
            reducer.reduction_document(root)

    def test_hardcoded_fleet_total_fallback_fails_closed(self):
        def mutate(document):
            # rows unchanged; only the stored aggregate is forged
            document["totals"]["deployed_accelerator_bytes_total"] = (
                128849018880)
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "census totals disagree"):
            reducer.reduction_document(root)

    def test_unclassified_status_fails_closed(self):
        def mutate(document):
            document["resources"][0]["status"] = "PROBABLY_FINE"
        root = self._mutate_hardware(mutate)
        with self.assertRaisesRegex(ValueError, "unclassified resource status"):
            reducer.reduction_document(root)

    def test_valinor_excluded_but_disclosed(self):
        document = reducer.reduction_document()
        self.assertEqual(
            document["fleet_fit"]["valinor_gtx1060_bytes_excluded_from_execution_fleet"],
            3221225472)

    # ------------------------------------------------------------------
    # GGUF header-census mutation controls
    # ------------------------------------------------------------------

    def _mutate_headers(self, mutate):
        root = staged_root(self)
        path = root / reducer.HEADER_CENSUS
        document = json.loads(path.read_text())
        mutate(document)
        path.write_text(json.dumps(document, indent=1))
        return root

    def test_wrong_split_count_fails_closed(self):
        def mutate(document):
            document["files"][0]["metadata"]["split.count"] = 4
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "split order/count"):
            reducer.reduction_document(root)

    def test_split_order_mutation_fails_closed(self):
        def mutate(document):
            document["files"][1]["metadata"]["split.no"] = 2
            document["files"][2]["metadata"]["split.no"] = 1
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "split order/count"):
            reducer.reduction_document(root)

    def test_duplicate_tensor_identity_fails_closed(self):
        def mutate(document):
            tensors = document["files"][1]["tensors"]
            tensors[1] = dict(tensors[0])
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "duplicate tensor identity"):
            reducer.reduction_document(root)

    def test_missing_tensor_fails_closed(self):
        def mutate(document):
            document["files"][1]["tensors"] = document["files"][1]["tensors"][1:]
            document["files"][1]["tensor_count"] -= 1
            for f in document["files"]:
                f["metadata"]["split.tensors.count"] = 1223
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "carried tensor count"):
            reducer.reduction_document(root)

    def test_inconsistent_tensor_offset_fails_closed(self):
        def mutate(document):
            for t in document["files"][1]["tensors"]:
                if t["name"] == reducer.PLE_TABLE_TENSOR:
                    t["offset"] += 4096
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "PLE table byte extent drift"):
            reducer.reduction_document(root)

    def test_quantization_type_mutation_fails_closed(self):
        def mutate(document):
            for t in document["files"][1]["tensors"]:
                if t["name"] == reducer.PLE_TABLE_TENSOR:
                    t["ggml_type"] = 14
                    t["ggml_type_name"] = "GGML_TYPE_Q6_K"
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "shape/type drift"):
            reducer.reduction_document(root)

    def test_ngram_independent_addressability_authored_true_contradicting_metadata(self):
        def mutate(document):
            # forge the addressability claim while deleting the real tensor
            for f in document["files"]:
                f["tensors"] = [t for t in f["tensors"]
                                if t["name"] != reducer.PLE_TABLE_TENSOR]
            document["files"][0]["ngram_independently_addressable"] = True
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "PLE table tensor identity"):
            reducer.reduction_document(root)

    def test_retained_header_byte_drift_fails_closed(self):
        root = staged_root(self)
        target = (root / reducer.AREA / "raw-headers")
        victim = sorted(target.iterdir())[0]
        victim.write_bytes(victim.read_bytes() + b"\x00")
        with self.assertRaisesRegex(ValueError, "retained header bytes drift"):
            reducer.reduction_document(root)

    def test_body_download_claim_fails_closed(self):
        def mutate(document):
            document["body_download_bytes"] = 67564613632
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "header census claims body bytes"):
            reducer.reduction_document(root)

    def test_non_206_receipt_fails_closed(self):
        def mutate(document):
            document["files"][0]["receipts"][0]["http_status"] = 200
        root = self._mutate_headers(mutate)
        with self.assertRaisesRegex(ValueError, "non-206 range receipt"):
            reducer.reduction_document(root)

    def test_header_census_covers_required_facts(self):
        document = reducer.reduction_document()
        representation = document["representation"]
        self.assertEqual(representation["gguf_version"], 3)
        self.assertEqual(representation["architecture"], "qwen4exp")
        self.assertEqual(representation["tensor_total"], 1224)
        state = representation["ngram_ple_state"]
        self.assertEqual(state["identity_addressability"], "ESTABLISHED")
        self.assertEqual(state["table_bytes"], reducer.PLE_TABLE_BYTES)
        self.assertEqual(state["representation_separable_from_backbone"], "YES")
        self.assertTrue(state["placement_behavior_of_any_build"].startswith(
            "NOT_ESTABLISHED"))

    def test_malformed_gguf_header_receipt_fails_closed(self):
        # The census builder rejects bad magic at collection time; the
        # reducer binds the retained bytes by sha256, so a malformed header
        # cannot masquerade as the pinned one.
        root = staged_root(self)
        target = (root / reducer.AREA / "raw-headers")
        victim = sorted(target.iterdir())[0]
        data = bytearray(victim.read_bytes())
        data[0:4] = b"JUNK"
        victim.write_bytes(bytes(data))
        with self.assertRaisesRegex(ValueError, "retained header bytes drift"):
            reducer.reduction_document(root)

    def test_terminal_alternatives_are_rejected_with_reasons(self):
        document = reducer.reduction_document()
        derivation = document["terminal_derivation"]
        self.assertEqual(derivation["remaining_blocker"],
                         "runtime/backend qualification of one pinned llama.cpp "
                         "build for the exact proposed mode on this fleet")
        self.assertIn("R8A_QWEN38_REPRESENTATION_PREREQUISITE",
                      derivation["rejected_alternatives"])


if __name__ == "__main__":
    unittest.main()
