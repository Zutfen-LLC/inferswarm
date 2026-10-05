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
            {"bdf":"0000:07:00.0", "index":"0", "vendor_id":"0x1002", "device_id":"0x6864",
             "vulkan_uuid":C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"], "icd":C.RADV_ICD,
             "name":"AMD Radeon Pro V340", "physical_type":"DISCRETE_GPU", "selected":True},
            {"bdf":"0000:0b:00.0", "index":"1", "vendor_id":"0x1002", "device_id":"0x6864",
             "vulkan_uuid":C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:0b:00.0"], "icd":C.RADV_ICD,
             "name":"AMD Radeon Pro V340", "physical_type":"DISCRETE_GPU", "selected":False},
        ]
        self.residencies = {"0000:07:00.0": [0, 6_300_000_000, 0],
                            "0000:0b:00.0": [0, 100, 0]}
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

    def run_capture(self, probes=None, case="case-256", receipt=None):
        probes = probes or FixtureExecutionHarness()
        return K.capture_execution_273(case, "candidate", False, receipt or self.receipt,
                                       probes, self.root)

    def test_positive_capture_retains_raw_bytes_and_derives_observations(self):
        p = FixtureExecutionHarness()
        receipt_raw = canonical(self.receipt)
        self.run_capture(p)
        stem = self.root / "source/case-256/candidate"
        raw = stem / "raw"
        expected = {"boot_identity.start.bin":p.boot, "start_ticks.start.bin":p.ticks,
                    "process_census.start.bin":p.read_process_census.__self__.read_process_census() if False else canonical({"boot_id":"recorded-boot-id", "processes":[{"pid":4321,"start_ticks":987654,"boot_id":"recorded-boot-id"}]}),
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
        self.assertNotIn("receipt_claims", obs["devices"] and obs)

    def test_executable_and_effective_model_mismatches_fail_closed(self):
        for kind in ("exe", "model"):
            with self.subTest(kind=kind):
                p = FixtureExecutionHarness()
                if kind == "exe": p.exe = f"/srv/other {('0'*64)}\n".encode()
                else: p.cmdline = b"/srv/llama-server\0--model\0/tmp/wrong.gguf\0"
                with self.assertRaises(K.CollectorError): self.run_capture(p)
                self.assertFalse(self.root.exists())

    def test_missing_probe_output_is_collector_missing(self):
        p = FixtureExecutionHarness(); p.boot = b""
        with self.assertRaises(K.CollectorMissing): self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_duplicate_bdf_uuid_or_index_rejected(self):
        for key in ("bdf", "vulkan_uuid", "index"):
            with self.subTest(key=key):
                p = FixtureExecutionHarness(); p.devices[1][key] = p.devices[0][key]
                with self.assertRaises(K.CollectorError): self.run_capture(p)
                self.assertFalse(self.root.exists())

    def test_excluded_device_residency_delta_at_noise_limit_rejected(self):
        p = FixtureExecutionHarness(); p.residencies["0000:0b:00.0"] = [0,C.EXCLUDED_NOISE_BYTES,0]
        with self.assertRaises(K.CollectorError): self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_receipt_bdf_claim_contradiction_names_field(self):
        bad = json.loads(canonical(self.receipt)); bad["subject_identity"]["bdf"] = "0000:0b:00.0"
        with self.assertRaisesRegex(K.CollectorError, "subject_identity.bdf"):
            self.run_capture(receipt=bad)

    def test_append_only_second_capture_refused(self):
        self.run_capture()
        with self.assertRaises(K.CollectorError): self.run_capture()

    def test_symlinked_or_traversal_destination_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            outside = Path(td) / "outside"; outside.mkdir()
            self.root.mkdir()
            (self.root / "source").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(K.CollectorError): self.run_capture()
        with self.assertRaises(K.CollectorError): self.run_capture(case="../escape")

    def test_receipt_claims_are_marked_checked_not_observations(self):
        self.run_capture()
        obs = json.loads((self.root/"source/case-256/candidate/observation.json").read_bytes())
        self.assertIsInstance(obs["receipt_claims_checked"], list)
        self.assertTrue(all(isinstance(x, str) for x in obs["receipt_claims_checked"]))
        self.assertNotIn("receipt", obs)


if __name__ == "__main__": unittest.main()
