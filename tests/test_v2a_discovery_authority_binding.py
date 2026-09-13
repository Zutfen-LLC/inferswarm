"""Issue #163 correction round 2: discovery -> authority binding controls.

Production-path CPU controls for the reviewed-discovery contract: the
authority loader must reject every disconnected, stale, tampered, or
ambiguous discovery binding, and identical device names may be resolved
ONLY by the explicit zero-token identity proof, never by ordering.
Fixture device names/selectors are synthetic; no accepted subject
literal appears here beyond authority/evidence fixtures.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_authority as authority  # noqa: E402
import v2a_authority_v2 as authority_v2  # noqa: E402
import v2a_discovery_v2 as discovery_v2  # noqa: E402

REFERENCE = b"synthetic accepted reference bytes\n"

# Synthetic twin fixture: TWO loader devices with the IDENTICAL name.
TWIN_LISTING = """\
Available devices:
  Vulkan1: Synthetic Twin GPU (8192 MiB, 8100 MiB free)
  Vulkan5: Synthetic Twin GPU (8192 MiB, 8100 MiB free)
  Vulkan7: Synthetic Unique GPU (4096 MiB, 4000 MiB free)
"""
TWIN_LOADER = """\
Vulkan Instance Version:   1.4.309
Devices:
========
GPU0:
\tdeviceName         = Synthetic Twin GPU
\tvendorID           = 0x9999
\tdeviceID           = 0x0001
\tdriverName         = twin-driver
VkPhysicalDevicePCIBusInfoPropertiesEXT:
----------------------------------------
\tpciDomain   = 0
\tpciBus      = 2
\tpciDevice   = 0
\tpciFunction = 0
GPU1:
\tdeviceName         = Synthetic Twin GPU
\tvendorID           = 0x9999
\tdeviceID           = 0x0001
\tdriverName         = twin-driver
VkPhysicalDevicePCIBusInfoPropertiesEXT:
----------------------------------------
\tpciDomain   = 0
\tpciBus      = 3
\tpciDevice   = 0
\tpciFunction = 0
GPU2:
\tdeviceName         = Synthetic Unique GPU
\tvendorID           = 0x8888
\tdeviceID           = 0x0002
\tdriverName         = unique-driver
VkPhysicalDevicePCIBusInfoPropertiesEXT:
----------------------------------------
\tpciDomain   = 0
\tpciBus      = 16
\tpciDevice   = 0
\tpciFunction = 0
"""
TWIN_LSPCI = """\
02:00.0 VGA compatible controller: Synthetic Twin [9999:0001]
03:00.0 VGA compatible controller: Synthetic Twin [9999:0001]
10:00.0 VGA compatible controller: Synthetic Unique [8888:0002]
"""

EXEC_SHA = "e" * 64


def probe_result(selector: str, bdf: str) -> dict:
    return {
        "probe_kind": "NON_CORRECTNESS_BEARING_IDENTITY_PROBE",
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [discovery_v2.NON_AUTHORIZING, discovery_v2.NON_CORRECTNESS_BEARING],
        "started_utc": "2026-09-13T00:00:00+00:00",
        "argv": ["/synthetic/llama-cli", "-m", "/synthetic/model.gguf", "--device", selector,
                 "-ngl", "99", "-n", "0", "-p", "identity-probe", "--no-warmup", "-st", "-lv", "4"],
        "exit_code": 0,
        "selector": selector,
        "observed_pci_bdf": bdf,
        "identity_proof_line": f"using device {selector} (Synthetic Twin GPU) (0000:{bdf}) - 8100 MiB free",
        "generated_tokens": 0,
        "zero_generation_proof": ["Generation: 0.0 t/s"],
        "stderr_sha256": "1" * 64,
        "stdout_sha256": "2" * 64,
    }


class ReviewedDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp = Path(self._temp.name)
        self.inventory = discovery_v2.build_inventory(
            runtime_executable="/synthetic/llama-cli", listing_probe=TWIN_LISTING,
            loader_probe=TWIN_LOADER, lspci_text=TWIN_LSPCI, hostname="node-r2")
        self.inventory["runtime_executable_sha256"] = EXEC_SHA

    def tearDown(self):
        self._temp.cleanup()

    def _bindings(self, **overrides):
        probes = {("Vulkan1", "02:00.0"): probe_result("Vulkan1", "02:00.0"),
                  ("Vulkan5", "03:00.0"): probe_result("Vulkan5", "03:00.0")}

        def runner(argv):
            selector = argv[argv.index("--device") + 1]
            for (sel, bdf), probe in probes.items():
                if sel == selector:
                    mutation = overrides.get("mutate_bdf_of") or {}
                    if bdf in mutation:
                        probe = copy.deepcopy(probe)
                        probe["observed_pci_bdf"] = mutation[bdf]
                    return probe
            raise discovery_v2.DiscoveryError(f"no probe for {selector}")

        return discovery_v2.build_bindings(self.inventory, model="/synthetic/model.gguf",
                                           probe_runner=runner)

    def test_inventory_records_ambiguous_twins_and_is_non_authorizing(self):
        by_selector = {d["selector"]: d for d in self.inventory["devices"]}
        self.assertEqual(by_selector["Vulkan1"]["binding_status"], "AMBIGUOUS")
        self.assertEqual(by_selector["Vulkan5"]["binding_status"], "AMBIGUOUS")
        self.assertEqual(sorted(by_selector["Vulkan1"]["candidate_bdfs"]), ["02:00.0", "03:00.0"])
        self.assertEqual(by_selector["Vulkan7"]["binding_status"], "BOUND")
        self.assertEqual(self.inventory["authorization"], "NON_AUTHORIZING")

    def test_identical_names_resolve_only_via_identity_proof_never_ordering(self):
        bindings = self._bindings()
        by_selector = {b["selector"]: b for b in bindings["bindings"]}
        # Swapping WHICH twin holds which BDF must flip the binding: an
        # ordering assumption would bind both probes identically.
        self.assertEqual(by_selector["Vulkan1"]["pci_bdf"], "02:00.0")
        self.assertEqual(by_selector["Vulkan5"]["pci_bdf"], "03:00.0")
        flipped = discovery_v2.build_bindings(
            self.inventory, model="/synthetic/model.gguf",
            probe_runner=lambda argv: probe_result(
                argv[argv.index("--device") + 1],
                "03:00.0" if argv[argv.index("--device") + 1] == "Vulkan1" else "02:00.0"))
        flipped_by = {b["selector"]: b for b in flipped["bindings"]}
        self.assertEqual(flipped_by["Vulkan1"]["pci_bdf"], "03:00.0")
        self.assertEqual(flipped_by["Vulkan5"]["pci_bdf"], "02:00.0")

    def test_probe_evidence_is_digest_bound_and_zero_token(self):
        bindings = self._bindings()
        entry = {b["selector"]: b for b in bindings["bindings"]}["Vulkan1"]
        probe = entry["identity_probe"]
        self.assertEqual(entry["binding_proof_sha256"],
                         hashlib.sha256(discovery_v2.canonical(probe)).hexdigest())
        self.assertEqual(probe["generated_tokens"], 0)
        self.assertEqual(probe["exit_code"], 0)
        self.assertIn("--device", probe["argv"])
        self.assertIn("-n", probe["argv"])
        self.assertEqual(probe["argv"][probe["argv"].index("-n") + 1], "0")

    def test_probe_with_nonzero_generation_fails_closed(self):
        def runner(argv):
            result = probe_result(argv[argv.index("--device") + 1], "02:00.0")
            result["zero_generation_proof"] = ["Generation: 9.5 t/s"]
            return result
        with self.assertRaises(discovery_v2.DiscoveryError):
            discovery_v2.build_bindings(self.inventory, model="/m", probe_runner=runner)

    def test_probe_mismatch_fails_closed(self):
        def runner(argv):
            return probe_result("Vulkan5", "02:00.0")  # selected line names the other selector
        with self.assertRaises(discovery_v2.DiscoveryError):
            discovery_v2.build_bindings(self.inventory, model="/m", probe_runner=runner)

    def test_tampered_probe_digest_rejected_at_verify(self):
        bindings = self._bindings()
        entry = {b["selector"]: b for b in bindings["bindings"]}["Vulkan1"]
        entry["identity_probe"]["identity_proof_line"] = "using device Vulkan1 (forged)"
        with self.assertRaises(discovery_v2.DiscoveryError):
            discovery_v2.verify_binding_document(bindings, self.inventory,
                                                 selector="Vulkan1", bdf="02:00.0")

    def test_unresolved_selector_never_binds(self):
        with self.assertRaises(discovery_v2.DiscoveryError):
            discovery_v2.verify_binding_document(self._bindings(), self.inventory,
                                                 selector="Vulkan99", bdf="02:00.0")

    def test_bindings_carry_no_correctness_data(self):
        bindings = self._bindings()
        self.assertNotIn("correctness", bindings)
        self.assertNotIn("reference", bindings)
        for entry in bindings["bindings"]:
            self.assertNotIn("correctness", entry)
            if "identity_probe" in entry:
                self.assertNotIn("correctness", entry["identity_probe"])
                self.assertNotIn("reference", entry["identity_probe"])


class AuthorityBindingTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp = Path(self._temp.name)
        (self.temp / "reference.txt").write_bytes(REFERENCE)
        inventory = discovery_v2.build_inventory(
            runtime_executable="/synthetic/llama-cli", listing_probe=TWIN_LISTING,
            loader_probe=TWIN_LOADER, lspci_text=TWIN_LSPCI, hostname="node-r2")
        inventory["runtime_executable_sha256"] = EXEC_SHA
        self.inventory = inventory
        probe = probe_result("Vulkan1", "02:00.0")
        probe["authorization"] = "NON_AUTHORIZING"
        bound = copy.deepcopy(inventory["devices"][0])
        bound.update({"binding_status": "BOUND", "pci_bdf": "02:00.0",
                      "resolution_mechanism": "runtime identity probe",
                      "identity_probe": probe,
                      "binding_proof_sha256": hashlib.sha256(
                          discovery_v2.canonical(probe)).hexdigest()})
        self.bindings = {
            "schema": discovery_v2.SCHEMA_BINDINGS,
            "inventory_schema": inventory["schema"],
            "inventory_hostname": inventory["hostname"],
            "inventory_runtime_executable": inventory["runtime_executable"],
            "inventory_runtime_executable_sha256": EXEC_SHA,
            "inventory_measured_utc": inventory["measured_utc"],
            "reviewed_utc": datetime.now(timezone.utc).isoformat(),
            "bindings": [bound],
            "authorization": "NON_AUTHORIZING",
            "nonclaims": [discovery_v2.NON_AUTHORIZING],
        }
        (self.temp / "inventory.json").write_bytes(discovery_v2.canonical(self.inventory) + b"\n")
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")

    def tearDown(self):
        self._temp.cleanup()

    def authority(self) -> dict:
        return {
            "schema": authority_v2.SCHEMA,
            "frozen": {
                "hostname": "node-r2", "node_id": "node-r2", "compute_unit_id": "cu-r2",
                "memory_resource_id": "mr-r2", "memory_bytes": 8589934592,
                "physical_device_bdf": "02:00.0", "selector": "Vulkan1",
                "execution_unit_id": "unit-r2", "execution_contract_id": "contract-r2",
                "implementation_id": "impl-r2", "logical_state_id": "state-r2",
                "required_representation": "gguf-q4-k-m", "required_features": ["compute"],
                "required_memory_bytes": 3254091776, "required_headroom_bytes": 536870912,
                "required_integrity_status": "QUALIFIED",
                "correctness_policy": authority.ACCEPTED_COMPARATOR_POLICY,
                "objective": "MIN_OBJECTIVE_VALUE", "prompt": "prompt-r2",
                "runtime_source": "/src", "runtime_source_commit": "c" * 40,
                "executable": "/synthetic/llama-cli", "executable_sha256": EXEC_SHA,
                "model": "/model.gguf", "model_sha256": "b" * 64, "model_bytes": 123,
                "qualification_evidence_id": "v2a-r2-qualification-01",
                "canonical_execution_evidence_id": "v2a-r2-canonical-01",
                "runtime_identity": {"selector": "Vulkan1"},
            },
            "discovery_binding": {
                "inventory_path": "inventory.json",
                "inventory_sha256": hashlib.sha256(
                    (self.temp / "inventory.json").read_bytes()).hexdigest(),
                "bindings_path": "bindings.json",
                "bindings_sha256": hashlib.sha256(
                    (self.temp / "bindings.json").read_bytes()).hexdigest(),
                "reviewed_utc": self.bindings["reviewed_utc"],
                "discovery_hostname": "node-r2",
                "discovery_runtime_executable_sha256": EXEC_SHA,
                "selector": "Vulkan1", "pci_bdf": "02:00.0",
                "binding_status": "BOUND",
                "binding_proof_sha256": self.bindings["bindings"][0]["binding_proof_sha256"],
            },
            "correctness": {
                "comparator_policy": authority.ACCEPTED_COMPARATOR_POLICY,
                "comparator_identity": "scripts/v0c_correctness.py",
                "comparator_sha256": hashlib.sha256(
                    (ROOT / "scripts/v0c_correctness.py").read_bytes()).hexdigest(),
                "reference_sha256": hashlib.sha256(REFERENCE).hexdigest(),
                "reference_path": str(self.temp / "reference.txt"),
                "reference_provenance": "accepted pre-existing campaign evidence (fixture)",
                "no_recalibration": authority.NO_RECALIBRATION,
            },
            "evidence": {"evidence_namespace": "vulkan-v2-a",
                         "plan_evidence_id": "v2a-r2-plan-01",
                         "capability_evidence_id": "v2a-r2-capability-01"},
            "nonclaims": ["internal harness only"],
        }

    def load(self, document=None, **kwargs):
        kwargs.setdefault("reference_root", self.temp)
        kwargs.setdefault("discovery_root", self.temp)
        return authority_v2.load_authority(document if document is not None else self.authority(),
                                           **kwargs)

    def test_v2_authority_with_bound_discovery_loads(self):
        loaded = self.load()
        self.assertEqual(loaded["verified_binding"]["binding_status"], "BOUND")

    def test_v1_authority_no_longer_sufficient(self):
        document = self.authority()
        document["schema"] = authority.SCHEMA  # attempt-01 contract: no binding block
        with self.assertRaises(authority.AuthorityError):
            authority_v2.load_authority(document, reference_root=self.temp,
                                        discovery_root=self.temp)

    # Control 1: missing discovery snapshot.
    def test_missing_inventory_rejected(self):
        document = self.authority()
        (self.temp / "inventory.json").unlink()
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 2: wrong discovery digest.
    def test_wrong_inventory_digest_rejected(self):
        document = self.authority()
        document["discovery_binding"]["inventory_sha256"] = "0" * 64
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 3: authority selector absent from discovery.
    def test_selector_absent_from_discovery_rejected(self):
        document = self.authority()
        self.bindings["bindings"] = [dict(self.bindings["bindings"][0], selector="Vulkan5",
                                          pci_bdf="03:00.0")]
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 4: AMBIGUOUS selector rejected (caller cannot enrich by BDF).
    def test_ambiguous_selector_rejected(self):
        document = self.authority()
        row = self.bindings["bindings"][0]
        row.update({"binding_status": "AMBIGUOUS", "pci_bdf": None,
                    "candidate_bdfs": ["02:00.0", "03:00.0"]})
        row.pop("identity_probe", None)
        row.pop("binding_proof_sha256", None)
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        document["discovery_binding"]["binding_status"] = "BOUND"
        document["discovery_binding"]["binding_proof_sha256"] = ""
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 5: UNRESOLVED selector rejected.
    def test_unresolved_selector_rejected(self):
        document = self.authority()
        row = self.bindings["bindings"][0]
        row.update({"binding_status": "UNRESOLVED", "pci_bdf": None})
        row.pop("identity_probe", None)
        row.pop("binding_proof_sha256", None)
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        document["discovery_binding"]["binding_proof_sha256"] = ""
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 6: selector bound to a different BDF.
    def test_selector_bound_to_different_bdf_rejected(self):
        document = self.authority()
        document["frozen"]["physical_device_bdf"] = "03:00.0"
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 7: correct selector/BDF but wrong hostname.
    def test_wrong_hostname_rejected(self):
        document = self.authority()
        document["discovery_binding"]["discovery_hostname"] = "node-elsewhere"
        with self.assertRaises(authority.AuthorityError):
            self.load(document)
        document = self.authority()
        document["frozen"]["hostname"] = "node-elsewhere"
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 8: stale discovery rejected.
    def test_stale_discovery_rejected(self):
        document = self.authority()
        stale = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
        self.bindings["reviewed_utc"] = stale
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["reviewed_utc"] = stale
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 9: different runtime executable hash.
    def test_different_runtime_executable_hash_rejected(self):
        document = self.authority()
        document["discovery_binding"]["discovery_runtime_executable_sha256"] = "f" * 64
        with self.assertRaises(authority.AuthorityError):
            self.load(document)
        document = self.authority()
        document["frozen"]["executable_sha256"] = "f" * 64
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 10: tampered binding proof.
    def test_tampered_binding_proof_rejected(self):
        document = self.authority()
        self.bindings["bindings"][0]["identity_probe"]["identity_proof_line"] = "forged line"
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 11: duplicate selector binding rows.
    def test_duplicate_selector_binding_rejected(self):
        document = self.authority()
        self.bindings["bindings"].append(dict(self.bindings["bindings"][0]))
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 13: reviewed discovery can never authorize correctness.
    def test_discovery_artifact_with_correctness_block_rejected(self):
        document = self.authority()
        self.bindings["correctness"] = {"reference": "forged"}
        (self.temp / "bindings.json").write_bytes(discovery_v2.canonical(self.bindings) + b"\n")
        document["discovery_binding"]["bindings_sha256"] = hashlib.sha256(
            (self.temp / "bindings.json").read_bytes()).hexdigest()
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # Control 14: correctness-reference provenance still independently required.
    def test_correctness_provenance_still_required(self):
        document = self.authority()
        document["correctness"]["reference_provenance"] = "derived from discovery output"
        with self.assertRaises(authority.AuthorityError):
            self.load(document)


if __name__ == "__main__":
    unittest.main()
