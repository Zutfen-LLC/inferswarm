"""Issue #163 correction round 3: stale-inventory and raw-probe-provenance controls.

Production-path CPU controls for the corrected R3 contract. The R2
loader aged only the review event; these controls prove the loader now
fails closed on a STALE PHYSICAL INVENTORY even when the review is
fresh, on inventory-timestamp divergence between the authority and the
digest-verified artifacts, on malformed/naive/future/inverted
timestamps, on probe results that do not mechanically prove zero
generation from their raw bytes, and on tampered retained raw probe
bytes. Fixture device names/selectors are synthetic; no accepted
subject literal appears here beyond authority/evidence fixtures.
"""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v2a_authority as authority  # noqa: E402
import v2a_authority_v3 as authority_v3  # noqa: E402
import v2a_discovery_v3 as discovery_v3  # noqa: E402

REFERENCE = b"synthetic accepted reference bytes\n"
EXEC_SHA = "e" * 64

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

NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)
RAW_REL = "raw/discovery-r3"


def iso(dt: datetime) -> str:
    return dt.isoformat()


def raw_probe_bytes(selector: str, bdf: str, *, rate: str = "0.0") -> tuple[bytes, bytes]:
    """Synthetic raw probe stdout/stderr in the runtime's own grammar."""
    stderr = (f"0.00.801.708 I llama_prepare_model_devices: using device {selector} "
              f"(Synthetic Twin GPU) (0000:{bdf}) - 8100 MiB free\n").encode()
    stdout = b"[ Prompt: 217.6 t/s | Generation: " + rate.encode() + b" t/s ]\n"
    return stdout, stderr


def raw_rel_paths(selector: str) -> tuple[str, str]:
    label = selector.lower()
    return (f"{RAW_REL}/identity-probe-stdout-{label}.txt",
            f"{RAW_REL}/identity-probe-stderr-{label}.txt")


def injected_probe(selector: str, bdf: str, *, rate: str = "0.0",
                   with_raw_paths: bool = False) -> dict:
    """A CPU-injected probe result carrying its OWN synthetic raw bytes.

    build_bindings routes injected results through the SAME shared
    validate_probe() path as real executions, so an injected probe must
    carry raw bytes that mechanically prove everything it claims. When
    ``with_raw_paths`` is set the record also points at retained raw
    files (which the caller writes) so re-verification re-derives the
    proof from those bytes exactly like a production record.
    """
    stdout, stderr = raw_probe_bytes(selector, bdf, rate=rate)
    identity = f"using device {selector} (Synthetic Twin GPU) (0000:{bdf})"
    record = {
        "probe_kind": "NON_CORRECTNESS_BEARING_IDENTITY_PROBE",
        "authorization": "NON_AUTHORIZING",
        "nonclaims": [discovery_v3.NON_AUTHORIZING, discovery_v3.NON_CORRECTNESS_BEARING],
        "started_utc": iso(NOW),
        "argv": ["/synthetic/llama-cli", "-m", "/synthetic/model.gguf", "--device", selector,
                 "-ngl", "99", "-n", "0", "-p", "identity-probe", "--no-warmup", "-st", "-lv", "4"],
        "exit_code": 0,
        "selector": selector,
        "observed_pci_bdf": bdf,
        "identity_proof_line": identity,
        "generated_tokens": 0,
        "zero_generation_proof": [f"Generation: {rate} t/s"],
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        # raw byte payloads consumed (and stripped) by the shared validator
        "raw_stdout": stdout,
        "raw_stderr": stderr,
    }
    if with_raw_paths:
        rel_stdout, rel_stderr = raw_rel_paths(selector)
        record["raw_stdout_path"] = rel_stdout
        record["raw_stderr_path"] = rel_stderr
    return record


def retain_raw_files(root: Path, selector: str, bdf: str, *, rate: str = "0.0") -> None:
    """Write an injected probe's synthetic raw bytes where its paths point."""
    stdout, stderr = raw_probe_bytes(selector, bdf, rate=rate)
    rel_stdout, rel_stderr = raw_rel_paths(selector)
    (root / rel_stdout).write_bytes(stdout)
    (root / rel_stderr).write_bytes(stderr)


class R3DiscoveryTests(unittest.TestCase):
    """Discovery-layer controls: timestamps, chronology, raw-byte binding."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp = Path(self._temp.name)
        (self.temp / RAW_REL).mkdir(parents=True)

    def tearDown(self):
        self._temp.cleanup()

    def _inventory(self, **kwargs):
        params = dict(runtime_executable="/synthetic/llama-cli", listing_probe=TWIN_LISTING,
                      loader_probe=TWIN_LOADER, lspci_text=TWIN_LSPCI, hostname="node-r3",
                      measured_utc=iso(NOW))
        params.update(kwargs)
        inventory = discovery_v3.build_inventory(**params)
        inventory["runtime_executable_sha256"] = EXEC_SHA
        return inventory

    def _bindings(self, inventory=None, **kwargs):
        inventory = inventory if inventory is not None else self._inventory()
        probes = {("Vulkan1", "02:00.0"): injected_probe("Vulkan1", "02:00.0", with_raw_paths=True),
                  ("Vulkan5", "03:00.0"): injected_probe("Vulkan5", "03:00.0", with_raw_paths=True)}
        for (sel, bdf) in probes:
            retain_raw_files(self.temp, sel, bdf)

        def runner(argv):
            selector = argv[argv.index("--device") + 1]
            for (sel, bdf), probe in probes.items():
                if sel == selector:
                    return copy.deepcopy(probe)
            raise discovery_v3.DiscoveryError(f"no probe for {selector}")

        params = dict(model="/synthetic/model.gguf", probe_runner=runner,
                      raw_root=self.temp, raw_rel_dir=RAW_REL,
                      reviewed_utc=iso(NOW + timedelta(minutes=10)))
        params.update(kwargs)
        return discovery_v3.build_bindings(inventory, **params)

    # --- timestamp parsing: fail-closed on malformed/naive/missing ---

    def test_malformed_inventory_measured_utc_rejected_at_build(self):
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._inventory(measured_utc="not-a-timestamp")

    def test_naive_inventory_measured_utc_rejected_at_build(self):
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._inventory(measured_utc="2026-09-13T12:00:00")  # no timezone

    def test_malformed_reviewed_utc_rejected_at_bindings_build(self):
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._bindings(reviewed_utc="2026-13-45T99:00:00+00:00")

    def test_naive_reviewed_utc_rejected_at_bindings_build(self):
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._bindings(reviewed_utc="2026-09-13T12:10:00")

    # --- chronology: inventory measured <= reviewed, fail-closed ---

    def test_inverted_inventory_review_chronology_rejected_at_build(self):
        # review BEFORE the physical measurement is impossible chronology
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._bindings(reviewed_utc=iso(NOW - timedelta(hours=1)))

    def test_bindings_inventory_measured_utc_must_equal_inventory_artifact(self):
        inventory = self._inventory()
        bindings = self._bindings(inventory)
        self.assertEqual(bindings["inventory_measured_utc"], inventory["measured_utc"])
        tampered = copy.deepcopy(bindings)
        tampered["inventory_measured_utc"] = iso(NOW - timedelta(days=365))
        with self.assertRaises(discovery_v3.DiscoveryError):
            discovery_v3.verify_binding_document(
                tampered, inventory, selector="Vulkan1", bdf="02:00.0", raw_root=self.temp)

    # --- raw-byte provenance: retained paths, digests, tamper ---

    def test_bindings_retain_explicit_raw_probe_paths_and_reverify(self):
        inventory = self._inventory()
        bindings = self._bindings(inventory)
        entry = {b["selector"]: b for b in bindings["bindings"]}["Vulkan1"]
        probe = entry["identity_probe"]
        self.assertEqual(probe["raw_stdout_path"], f"{RAW_REL}/identity-probe-stdout-vulkan1.txt")
        self.assertEqual(probe["raw_stderr_path"], f"{RAW_REL}/identity-probe-stderr-vulkan1.txt")
        # clean re-verification passes through the shared raw-byte path
        verified = discovery_v3.verify_binding_document(
            bindings, inventory, selector="Vulkan1", bdf="02:00.0", raw_root=self.temp)
        self.assertEqual(verified["binding_status"], "BOUND")

    def test_tampered_retained_raw_stdout_fails_reverification(self):
        inventory = self._inventory()
        bindings = self._bindings(inventory)
        # tamper with the retained raw stdout while the structured record
        # (and its digest fields) stay unchanged
        path = self.temp / raw_rel_paths("Vulkan1")[0]
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaises(discovery_v3.DiscoveryError):
            discovery_v3.verify_binding_document(
                bindings, inventory, selector="Vulkan1", bdf="02:00.0", raw_root=self.temp)

    def test_tampered_retained_raw_stderr_fails_reverification(self):
        inventory = self._inventory()
        bindings = self._bindings(inventory)
        path = self.temp / raw_rel_paths("Vulkan1")[1]
        path.write_bytes(path.read_bytes().replace(b"02:00.0", b"03:00.0"))
        with self.assertRaises(discovery_v3.DiscoveryError):
            discovery_v3.verify_binding_document(
                bindings, inventory, selector="Vulkan1", bdf="02:00.0", raw_root=self.temp)

    def test_missing_retained_raw_probe_bytes_fail_reverification(self):
        inventory = self._inventory()
        bindings = self._bindings(inventory)
        (self.temp / raw_rel_paths("Vulkan1")[0]).unlink()
        with self.assertRaises(discovery_v3.DiscoveryError):
            discovery_v3.verify_binding_document(
                bindings, inventory, selector="Vulkan1", bdf="02:00.0", raw_root=self.temp)


class R3ZeroGenerationTests(unittest.TestCase):
    """The repaired zero-generation false-positive control.

    The R2 control could pass because its injected runner bound BOTH
    twins to the same BDF, triggering duplicate-BDF rejection
    independently of the generation evidence. These controls isolate
    generation EXACTLY: the fixture binds the twins to DISTINCT BDFs and
    is clean on every other axis, so only the generation evidence can
    cause a failure.
    """

    def _inventory(self):
        inventory = discovery_v3.build_inventory(
            runtime_executable="/synthetic/llama-cli", listing_probe=TWIN_LISTING,
            loader_probe=TWIN_LOADER, lspci_text=TWIN_LSPCI, hostname="node-r3",
            measured_utc=iso(NOW))
        inventory["runtime_executable_sha256"] = EXEC_SHA
        return inventory

    def _build(self, vulkan1_probe, vulkan5_probe):
        probes = {("Vulkan1", "02:00.0"): vulkan1_probe, ("Vulkan5", "03:00.0"): vulkan5_probe}

        def runner(argv):
            selector = argv[argv.index("--device") + 1]
            for (sel, bdf), probe in probes.items():
                if sel == selector:
                    return copy.deepcopy(probe)
            raise discovery_v3.DiscoveryError(f"no probe for {selector}")

        return discovery_v3.build_bindings(
            self._inventory(), model="/synthetic/model.gguf", probe_runner=runner,
            reviewed_utc=iso(NOW + timedelta(minutes=10)))

    def test_valid_zero_generation_probes_bind_both_twins_to_distinct_bdfs(self):
        # the clean baseline: distinct BDFs, valid zero-generation raw bytes
        bindings = self._build(injected_probe("Vulkan1", "02:00.0"),
                               injected_probe("Vulkan5", "03:00.0"))
        by = {b["selector"]: b for b in bindings["bindings"]}
        self.assertEqual(by["Vulkan1"]["pci_bdf"], "02:00.0")
        self.assertEqual(by["Vulkan5"]["pci_bdf"], "03:00.0")

    def test_nonzero_generation_evidence_fails_despite_distinct_bdfs(self):
        # ONLY the generation evidence changes: Vulkan5's raw stdout now
        # carries a nonzero generation rate (as if tokens had been
        # generated) while its structured fields still CLAIM zero. The
        # shared raw-byte validation path must reject; no duplicate BDF
        # or other unrelated condition exists in this fixture.
        with self.assertRaises(discovery_v3.DiscoveryError) as ctx:
            self._build(injected_probe("Vulkan1", "02:00.0"),
                        injected_probe("Vulkan5", "03:00.0", rate="9.5"))
        self.assertIn("zero", str(ctx.exception))

    def test_structured_zero_claim_diverging_from_raw_rates_fails(self):
        # raw bytes prove nonzero generation but the structured record
        # declares 0.0: the derivation mismatch must fail.
        probe = injected_probe("Vulkan5", "03:00.0", rate="9.5")
        probe["zero_generation_proof"] = ["Generation: 0.0 t/s"]
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._build(injected_probe("Vulkan1", "02:00.0"), probe)

    def test_absent_generation_rate_in_raw_stdout_fails(self):
        # stdout with NO generation line cannot prove zero generation
        stdout = b"[ Prompt: 217.6 t/s ]\n"
        probe = injected_probe("Vulkan5", "03:00.0")
        probe["raw_stdout"] = stdout
        probe["stdout_sha256"] = hashlib.sha256(stdout).hexdigest()
        probe["zero_generation_proof"] = []
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._build(injected_probe("Vulkan1", "02:00.0"), probe)

    def test_self_reported_digest_without_matching_raw_bytes_fails(self):
        # structured digests that match NONE of the held raw bytes fail
        probe = injected_probe("Vulkan5", "03:00.0")
        probe["stdout_sha256"] = "0" * 64
        with self.assertRaises(discovery_v3.DiscoveryError):
            self._build(injected_probe("Vulkan1", "02:00.0"), probe)


class R3AuthorityTests(unittest.TestCase):
    """Loader controls: stale inventory, chronology, divergence, tamper."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp = Path(self._temp.name)
        (self.temp / "reference.txt").write_bytes(REFERENCE)
        (self.temp / RAW_REL).mkdir(parents=True)
        self.anchor = NOW + timedelta(hours=1)
        self._build_artifacts(measured=NOW, reviewed=NOW + timedelta(minutes=10))

    def tearDown(self):
        self._temp.cleanup()

    def _build_artifacts(self, *, measured: datetime, reviewed: datetime):
        inventory = discovery_v3.build_inventory(
            runtime_executable="/synthetic/llama-cli", listing_probe=TWIN_LISTING,
            loader_probe=TWIN_LOADER, lspci_text=TWIN_LSPCI, hostname="node-r3",
            measured_utc=iso(measured))
        inventory["runtime_executable_sha256"] = EXEC_SHA
        probe = injected_probe("Vulkan1", "02:00.0", with_raw_paths=True)
        retain_raw_files(self.temp, "Vulkan1", "02:00.0")
        record = {k: v for k, v in probe.items()
                  if k not in ("raw_stdout", "raw_stderr")}
        bound = copy.deepcopy(inventory["devices"][0])
        bound.update({"binding_status": "BOUND", "pci_bdf": "02:00.0",
                      "resolution_mechanism": "runtime identity probe",
                      "identity_probe": record,
                      "binding_proof_sha256": hashlib.sha256(
                          discovery_v3.canonical(record)).hexdigest()})
        bindings = {
            "schema": discovery_v3.SCHEMA_BINDINGS,
            "inventory_schema": inventory["schema"],
            "inventory_hostname": inventory["hostname"],
            "inventory_runtime_executable": inventory["runtime_executable"],
            "inventory_runtime_executable_sha256": EXEC_SHA,
            "inventory_measured_utc": inventory["measured_utc"],
            "reviewed_utc": iso(reviewed),
            "bindings": [bound],
            "authorization": "NON_AUTHORIZING",
            "nonclaims": [discovery_v3.NON_AUTHORIZING],
        }
        (self.temp / "inventory.json").write_bytes(discovery_v3.canonical(inventory) + b"\n")
        (self.temp / "bindings.json").write_bytes(discovery_v3.canonical(bindings) + b"\n")
        self.inventory, self.bindings = inventory, bindings

    def authority(self) -> dict:
        return {
            "schema": authority_v3.SCHEMA,
            "frozen": {
                "hostname": "node-r3", "node_id": "node-r3", "compute_unit_id": "cu-r3",
                "memory_resource_id": "mr-r3", "memory_bytes": 8589934592,
                "physical_device_bdf": "02:00.0", "selector": "Vulkan1",
                "execution_unit_id": "unit-r3", "execution_contract_id": "contract-r3",
                "implementation_id": "impl-r3", "logical_state_id": "state-r3",
                "required_representation": "gguf-q4-k-m", "required_features": ["compute"],
                "required_memory_bytes": 3254091776, "required_headroom_bytes": 536870912,
                "required_integrity_status": "QUALIFIED",
                "correctness_policy": authority.ACCEPTED_COMPARATOR_POLICY,
                "objective": "MIN_OBJECTIVE_VALUE", "prompt": "prompt-r3",
                "runtime_source": "/src", "runtime_source_commit": "c" * 40,
                "executable": "/synthetic/llama-cli", "executable_sha256": EXEC_SHA,
                "model": "/model.gguf", "model_sha256": "b" * 64, "model_bytes": 123,
                "qualification_evidence_id": "v2a-r3-qualification-01",
                "canonical_execution_evidence_id": "v2a-r3-canonical-01",
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
                "inventory_measured_utc": self.inventory["measured_utc"],
                "discovery_hostname": "node-r3",
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
                         "plan_evidence_id": "v2a-r3-plan-01",
                         "capability_evidence_id": "v2a-r3-capability-01"},
            "nonclaims": ["internal harness only"],
        }

    def load(self, document=None, **kwargs):
        kwargs.setdefault("reference_root", self.temp)
        kwargs.setdefault("discovery_root", self.temp)
        kwargs.setdefault("raw_root", self.temp)
        kwargs.setdefault("frozen_at", iso(self.anchor))
        return authority_v3.load_authority(document if document is not None else self.authority(),
                                           **kwargs)

    def _rewrite(self, artifact: dict, name: str) -> dict:
        (self.temp / name).write_bytes(discovery_v3.canonical(artifact) + b"\n")
        document = self.authority()
        key = "inventory" if name.startswith("inventory") else "bindings"
        document["discovery_binding"][f"{key}_sha256"] = hashlib.sha256(
            (self.temp / name).read_bytes()).hexdigest()
        return document

    def test_v3_authority_with_fresh_inventory_loads(self):
        loaded = self.load()
        self.assertEqual(loaded["verified_binding"]["binding_status"], "BOUND")

    def test_r2_schema_authority_no_longer_accepted_for_campaigns(self):
        document = self.authority()
        document["schema"] = "inferswarm.v2a.campaign-authority/2"
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # --- THE stale-inventory control: fresh review, stale measurement ---

    def test_stale_inventory_with_fresh_review_rejected(self):
        # inventory measured 100h before the anchor (>72h), but reviewed
        # only 1h before the anchor (fresh): MUST fail closed.
        self._build_artifacts(measured=self.anchor - timedelta(hours=100),
                              reviewed=self.anchor - timedelta(hours=1))
        with self.assertRaises(authority.AuthorityError) as ctx:
            self.load()
        self.assertIn("INVENTORY is stale", str(ctx.exception))

    def test_inventory_just_inside_age_limit_loads(self):
        # measured exactly 71h before the anchor, reviewed 1h before:
        # inside the 72h inventory limit; loads.
        self._build_artifacts(measured=self.anchor - timedelta(hours=71),
                              reviewed=self.anchor - timedelta(hours=1))
        loaded = self.load()
        self.assertEqual(loaded["verified_binding"]["binding_status"], "BOUND")

    def test_binding_inventory_measured_utc_divergence_rejected(self):
        # the authority declares a DIFFERENT measured_utc than the
        # digest-verified inventory carries
        document = self.authority()
        document["discovery_binding"]["inventory_measured_utc"] = iso(NOW - timedelta(days=30))
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    def test_bindings_artifact_inventory_measured_divergence_rejected(self):
        # the BINDINGS artifact's copied measured_utc diverges from the
        # digest-verified inventory's measured_utc
        bindings = copy.deepcopy(self.bindings)
        bindings["inventory_measured_utc"] = iso(NOW - timedelta(days=30))
        with self.assertRaises(authority.AuthorityError):
            self.load(self._rewrite(bindings, "bindings.json"))

    # --- timestamp parsing/chronology controls at the loader ---

    def test_malformed_inventory_measured_utc_rejected_at_load(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["measured_utc"] = "13/09/2026"
        with self.assertRaises(authority.AuthorityError):
            self.load(self._rewrite(inventory, "inventory.json"))

    def test_naive_inventory_measured_utc_rejected_at_load(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["measured_utc"] = "2026-09-13T12:00:00"
        with self.assertRaises(authority.AuthorityError):
            self.load(self._rewrite(inventory, "inventory.json"))

    def test_missing_inventory_measured_utc_rejected_at_load(self):
        inventory = copy.deepcopy(self.inventory)
        inventory.pop("measured_utc")
        with self.assertRaises(authority.AuthorityError):
            self.load(self._rewrite(inventory, "inventory.json"))

    def test_future_inventory_measurement_rejected(self):
        # reviewed after an inventory measured after the anchor:
        # impossible chronology regardless of ages
        self._build_artifacts(measured=self.anchor + timedelta(hours=1),
                              reviewed=self.anchor + timedelta(hours=2))
        with self.assertRaises(authority.AuthorityError):
            self.load()

    def test_inverted_review_before_measurement_rejected_at_load(self):
        # reviewed BEFORE the inventory was measured: impossible chronology
        self._build_artifacts(measured=NOW, reviewed=NOW - timedelta(hours=1))
        with self.assertRaises(authority.AuthorityError):
            self.load()

    def test_future_reviewed_utc_rejected(self):
        bindings = copy.deepcopy(self.bindings)
        bindings["reviewed_utc"] = iso(self.anchor + timedelta(hours=24))
        document = self._rewrite(bindings, "bindings.json")
        document["discovery_binding"]["reviewed_utc"] = bindings["reviewed_utc"]
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    def test_naive_reviewed_utc_rejected_at_load(self):
        bindings = copy.deepcopy(self.bindings)
        bindings["reviewed_utc"] = "2026-09-13T12:10:00"
        document = self._rewrite(bindings, "bindings.json")
        document["discovery_binding"]["reviewed_utc"] = bindings["reviewed_utc"]
        with self.assertRaises(authority.AuthorityError):
            self.load(document)

    # --- stale REVIEW stays independently rejected (not conflated) ---

    def test_stale_review_with_fresh_inventory_also_rejected(self):
        # measured fresh but reviewed 100h before the anchor: the review
        # event is stale; rejected independently of inventory staleness.
        self._build_artifacts(measured=self.anchor - timedelta(hours=101),
                              reviewed=self.anchor - timedelta(hours=100))
        with self.assertRaises(authority.AuthorityError):
            self.load()

    # --- raw-proof provenance through the loader ---

    def test_tampered_retained_raw_stdout_rejected_at_load(self):
        path = self.temp / raw_rel_paths("Vulkan1")[0]
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaises(authority.AuthorityError):
            self.load()

    def test_tampered_retained_raw_stderr_rejected_at_load(self):
        path = self.temp / raw_rel_paths("Vulkan1")[1]
        path.write_bytes(path.read_bytes().replace(b"02:00.0", b"03:00.0"))
        with self.assertRaises(authority.AuthorityError):
            self.load()

    def test_missing_retained_raw_probe_bytes_rejected_at_load(self):
        (self.temp / raw_rel_paths("Vulkan1")[0]).unlink()
        with self.assertRaises(authority.AuthorityError):
            self.load()


if __name__ == "__main__":
    unittest.main()
