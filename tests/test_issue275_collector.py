"""CPU-only tests for collector-owned execution observations (no hardware authority)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue270_authority as C
import issue275_collector as K


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode()


class FixtureExecutionHarness:
    """Recording fake: exposes fixed raw contemporaneous probe bytes."""
    def __init__(self):
        self.pid = 4321
        self.boot = b"recorded-boot-id\n"
        self.ticks = b"987654\n"
        self.cmdline = (b"/srv/llama-server\0--model\0" +
                        f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}".encode() + b"\0")
        self.exe = f"/srv/llama-server {C.COMPARATOR_SHA256}\n".encode()
        self.members = canonical({name: digest for name, digest in C.MODEL_MEMBER_SHA256.items()})
        self.devices = [
            {"bdf":"0000:07:00.0", "index":0, "vendor_id":"0x1002", "device_id":"0x6864",
             "vulkan_uuid":C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"], "icd":C.RADV_ICD,
             "name":"AMD Radeon Pro V340", "physical_type":"DISCRETE_GPU", "selected":True},
            {"bdf":"0000:0b:00.0", "index":1, "vendor_id":"0x1002", "device_id":"0x6864",
             "vulkan_uuid":C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:0b:00.0"], "icd":C.RADV_ICD,
             "name":"AMD Radeon Pro V340", "physical_type":"DISCRETE_GPU", "selected":False},
        ]
        self.residencies = {"0000:07:00.0": [0, 6_300_000_000, 0],
                            "0000:0b:00.0": [0, 100, 0]}
        self.env_selector = "0"
        self.env_icd = C.RADV_ICD
        self.used_driver_id = "DRIVER_ID_MESA_RADV"
        self.calls = []

    def read_boot_identity(self): self.calls.append("boot"); return self.boot
    def read_start_ticks(self, pid): self.calls.append(("ticks", pid)); return self.ticks
    def read_process_census(self):
        self.calls.append("census")
        return canonical({"boot_id": self.boot.decode().strip(), "processes": [{"pid": self.pid, "start_ticks": int(self.ticks), "boot_id": self.boot.decode().strip()}]})
    def read_process_cmdline(self, pid): self.calls.append(("cmdline", pid)); return self.cmdline
    def read_exe_identity(self, pid): self.calls.append(("exe", pid)); return self.exe
    def read_open_model_members(self, pid): self.calls.append(("members", pid)); return self.members
    def read_device_census(self): self.calls.append("devices"); return canonical(self.devices)
    def read_process_environ(self, pid):
        self.calls.append(("environ", pid))
        return (f"GGML_VK_VISIBLE_DEVICES={self.env_selector}\0"
                f"VK_ICD_FILENAMES={self.env_icd}\0").encode()
    def read_used_vulkan_device(self, pid):
        self.calls.append(("used", pid))
        d = self.devices[int(self.env_selector)]
        return canonical({"backend": "vulkan", "icd": d.get("icd"), "vulkan_uuid": d.get("vulkan_uuid"),
                          "bdf": d.get("bdf"), "index": d.get("index"), "driver_id": self.used_driver_id})
    def read_residency(self, bdf):
        self.calls.append(("residency", bdf))
        return canonical({"bytes": self.residencies[bdf].pop(0)})


def digest(data):
    return hashlib.sha256(data).hexdigest()


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "capture"
        self.receipt = {
            "process_attribution": {"server_pid":4321, "server_env": {
                "GGML_VK_VISIBLE_DEVICES":"0", "VK_ICD_FILENAMES":C.RADV_ICD}},
            "subject_identity":{"bdf":"0000:07:00.0"},
            "model_members":dict(C.MODEL_MEMBER_SHA256), "exe_sha256":C.COMPARATOR_SHA256,
        }

    def run_capture(self, probes=None, case="case-256", receipt=None, arm="candidate"):
        probes = probes or FixtureExecutionHarness()
        return K.capture_execution_273(case, arm, False, receipt or self.receipt,
                                       probes, self.root)

    def test_nested_receipt_objects_are_guarded(self):
        for path, reason in (("process_attribution", "process_attribution"), ("server_env", "process_attribution.server_env"), ("subject_identity", "subject_identity")):
            bad = json.loads(canonical(self.receipt))
            if path == "server_env": bad["process_attribution"][path] = None
            else: bad[path] = None
            with self.subTest(path=path), self.assertRaisesRegex(K.CollectorError, reason): self.run_capture(receipt=bad)

    def test_traversal_bdf_rejected_during_census_validation(self):
        p = FixtureExecutionHarness(); p.devices[0]["bdf"] = "../../etc"
        with self.assertRaisesRegex(K.CollectorError, "census entry malformed bdf"): self.run_capture(p)

    def test_non_string_selector_rejected_without_coercion(self):
        bad = json.loads(canonical(self.receipt)); bad["process_attribution"]["server_env"]["GGML_VK_VISIBLE_DEVICES"] = 0
        with self.assertRaisesRegex(K.CollectorError, "GGML_VK_VISIBLE_DEVICES"): self.run_capture(receipt=bad)

    def test_reference_capture_derives_identity_and_retains_bytes(self):
        p = FixtureExecutionHarness(); identity = C.reference_identity(); d = p.devices[0]
        d.update({"bdf":identity["bdf"], "vendor_id":"0x10de", "device_id":"0x"+identity["pci_id"].split(":")[-1], "gpu_uuid":identity["gpu_uuid"], "vulkan_uuid":identity["vulkan_device_uuid"], "icd":identity["icd"], "name":identity["vulkan_device_name"]})
        p.devices[1].update({"vendor_id":"0x1002", "device_id":"0x67df", "name":"AMD RX 580", "icd":C.RADV_ICD})
        p.residencies={d["bdf"]:[0,10,0], p.devices[1]["bdf"]:[0,100,0]}
        p.env_icd = identity["icd"]; p.used_driver_id = K.NVIDIA_VULKAN_DRIVER_ID
        rec=json.loads(canonical(self.receipt)); rec["process_attribution"]["server_env"]["VK_ICD_FILENAMES"]=identity["icd"]; rec["subject_identity"]["bdf"]=identity["bdf"]
        self.run_capture(p, receipt=rec, arm="reference")
        stem=self.root/"source/case-256/reference"
        self.assertEqual((stem/"raw/device_census.start.bin").read_bytes(), canonical(p.devices))
        obs=json.loads((stem/"observation.json").read_bytes())
        self.assertEqual(obs["reference_identity_expected"], identity)
        self.assertFalse(obs["devices"][1]["selected"])

    def test_repeat_capture_uses_repeat_stem(self):
        K.capture_execution_273("case-256", "candidate", True, self.receipt, FixtureExecutionHarness(), self.root)
        self.assertTrue((self.root/"source/case-256/candidate-repeat/observation.json").is_file())

    def test_partial_write_cleanup_allows_retry(self):
        p = FixtureExecutionHarness(); original = K.os.fdopen; calls = [0]
        class BrokenStream:
            def __init__(self, wrapped): self.wrapped = wrapped
            def __enter__(self): return self
            def __exit__(self, *args): self.wrapped.close()
            def write(self, data): self.wrapped.write(data[:1]); raise OSError("injected write failure")
        def injected(fd, *args, **kwargs):
            calls[0] += 1
            return BrokenStream(original(fd, *args, **kwargs)) if calls[0] == 1 else original(fd, *args, **kwargs)
        K.os.fdopen = injected
        try:
            with self.assertRaisesRegex(K.CollectorError, "cannot write destination"): self.run_capture(p)
        finally: K.os.fdopen = original
        self.assertFalse(any(path.is_file() for path in self.root.rglob("*")))
        self.run_capture(FixtureExecutionHarness())

    def test_positive_capture_retains_raw_bytes_and_derives_observations(self):
        p = FixtureExecutionHarness()
        receipt_raw = canonical(self.receipt)
        self.run_capture(p)
        stem = self.root / "source/case-256/candidate"
        raw = stem / "raw"
        expected = {"boot_identity.start.bin":p.boot, "start_ticks.start.bin":p.ticks,
                    "process_census.start.bin":canonical({"boot_id":"recorded-boot-id", "processes":[{"pid":4321,"start_ticks":987654,"boot_id":"recorded-boot-id"}]}),
                    "process_cmdline.start.bin":p.cmdline, "exe_identity.start.bin":p.exe,
                    "open_model_members.start.bin":p.members, "device_census.start.bin":canonical(p.devices)}
        # Three original samples per device; fake values are supplied in order.
        for name, data in expected.items(): self.assertEqual((raw/name).read_bytes(), data)
        self.assertEqual((stem/"receipt.json").read_bytes(), receipt_raw)
        obs = json.loads((stem/"observation.json").read_bytes())
        self.assertEqual(obs["schema"], "inferswarm.issue275.collector-observation/1")
        self.assertEqual(obs["process"]["pid"], 4321)
        self.assertEqual(obs["process"]["boot_id"], "recorded-boot-id")
        self.assertEqual(obs["process"]["start_ticks"], 987654)
        self.assertEqual(obs["devices"], p.devices)
        self.assertEqual(obs["residency"]["0000:07:00.0"], {"before":0,"peak":6_300_000_000,"after":0})
        for rel, data in expected.items():
            self.assertEqual(obs["probe_inventory"][f"raw/{rel}"], {"sha256":digest(data),"bytes":len(data)})
        self.assertIn("subject_identity.bdf", obs["receipt_claims_checked"])
        self.assertNotIn("receipt_claims", obs)

    def test_executable_and_effective_model_mismatches_fail_closed(self):
        for kind in ("exe", "model"):
            with self.subTest(kind=kind):
                p = FixtureExecutionHarness()
                if kind == "exe": p.exe = f"/srv/other {('0'*64)}\n".encode()
                else: p.cmdline = b"/srv/llama-server\0--model\0/tmp/wrong.gguf\0"
                with self.assertRaisesRegex(K.CollectorError, "comparator sha" if kind == "exe" else "effective --model"):
                    self.run_capture(p)
                self.assertFalse(self.root.exists())

    def test_missing_probe_output_is_collector_missing(self):
        p = FixtureExecutionHarness(); p.boot = b""
        with self.assertRaises(K.CollectorMissing): self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_duplicate_bdf_uuid_or_index_rejected(self):
        for key in ("bdf", "vulkan_uuid", "index"):
            with self.subTest(key=key):
                p = FixtureExecutionHarness(); p.devices[1][key] = p.devices[0][key]
                with self.assertRaisesRegex(K.CollectorError, "duplicate/missing"):
                    self.run_capture(p)
                self.assertFalse(self.root.exists())

    def test_excluded_device_residency_delta_at_noise_limit_rejected(self):
        p = FixtureExecutionHarness(); p.residencies["0000:0b:00.0"] = [0,C.EXCLUDED_NOISE_BYTES,0]
        with self.assertRaisesRegex(K.CollectorError, "exceeds noise bound"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_receipt_bdf_claim_contradiction_names_field(self):
        bad = json.loads(canonical(self.receipt)); bad["subject_identity"]["bdf"] = "0000:0b:00.0"
        with self.assertRaisesRegex(K.CollectorError, "subject_identity.bdf"):
            self.run_capture(receipt=bad)

    def test_append_only_second_capture_refused(self):
        self.run_capture()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaises(K.CollectorError):
            self.run_capture()
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_symlinked_or_traversal_destination_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            outside = Path(td) / "outside"; outside.mkdir()
            self.root.mkdir()
            (self.root / "source").symlink_to(outside, target_is_directory=True)
            before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(K.CollectorError, "unsafe destination directory"):
            self.run_capture()
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        with self.assertRaises(K.CollectorError): self.run_capture(case="../escape")

    def test_candidate_unfrozen_vulkan_uuid_fails_closed(self):
        p = FixtureExecutionHarness()
        p.devices[0]["vulkan_uuid"] = "unfrozen-vulkan-uuid"
        with self.assertRaisesRegex(K.CollectorError, "candidate observed Vulkan UUID drift"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_candidate_wrong_vendor_id_fails_closed(self):
        p = FixtureExecutionHarness()
        p.devices[0]["vendor_id"] = "0x1234"
        with self.assertRaisesRegex(K.CollectorError, "candidate observed vendor/device/ICD drift"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_reference_excluded_non_rx580_fails_closed(self):
        p = FixtureExecutionHarness()
        identity = C.reference_identity()
        p.devices[0].update({
            "bdf": identity["bdf"], "index": 0, "vendor_id": "0x10de",
            "device_id": "0x" + identity["pci_id"].split(":")[-1],
            "vulkan_uuid": identity["vulkan_device_uuid"], "gpu_uuid": identity["gpu_uuid"],
            "icd": identity["icd"], "name": identity["vulkan_device_name"],
        })
        p.devices[1].update({"bdf":"0000:0b:00.0", "index":1, "vendor_id":"0x1002",
                             "device_id":"0x1234", "vulkan_uuid":"excluded-device-uuid",
                             "icd":C.RADV_ICD, "name":"Other AMD GPU"})
        p.residencies = {"00000000:03:00.0":[0,6_300_000_000,0], "0000:0b:00.0":[0,100,0]}
        p.env_icd = identity["icd"]; p.used_driver_id = K.NVIDIA_VULKAN_DRIVER_ID
        receipt = json.loads(canonical(self.receipt))
        receipt["process_attribution"]["server_env"] = {
            "GGML_VK_VISIBLE_DEVICES":"0", "VK_ICD_FILENAMES":identity["icd"]}
        receipt["subject_identity"]["bdf"] = identity["bdf"]
        with self.assertRaisesRegex(K.CollectorError, "positive RX580 excluded census absent"):
            self.run_capture(p, receipt=receipt, arm="reference")
        self.assertFalse(self.root.exists())

    def test_census_entry_missing_required_icd_fails_closed(self):
        p = FixtureExecutionHarness()
        p.devices[0].pop("icd")
        with self.assertRaisesRegex(K.CollectorError, "census entry missing/malformed icd"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_receipt_claims_are_marked_checked_not_observations(self):
        self.run_capture()
        obs = json.loads((self.root/"source/case-256/candidate/observation.json").read_bytes())
        self.assertIsInstance(obs["receipt_claims_checked"], list)
        self.assertTrue(all(isinstance(x, str) for x in obs["receipt_claims_checked"]))
        self.assertNotIn("receipt", obs)


if __name__ == "__main__": unittest.main()
