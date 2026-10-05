"""CPU fixture/recording evidence for issue #275's first demonstration; never physical authority.

No hardware or network access is used.
"""
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
        return (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                C.RADV_ICD.encode() + b"\0")
    def read_used_vulkan_device(self, pid):
        self.calls.append(("used", pid))
        d = self.devices[0]
        return canonical({"backend": "vulkan", "icd": d["icd"], "vulkan_uuid": d["vulkan_uuid"],
                          "bdf": d["bdf"], "index": d["index"], "driver_id": "DRIVER_ID_MESA_RADV"})
    def read_residency(self, bdf):
        self.calls.append(("residency", bdf))
        return canonical({"bytes": self.residencies[bdf].pop(0)})


class FirstDemonstrationTests(unittest.TestCase):
    def _receipt(self):
        return {
            "process_attribution": {"server_pid":4321, "server_env": {
                "GGML_VK_VISIBLE_DEVICES":"0", "VK_ICD_FILENAMES":C.RADV_ICD}},
            "subject_identity":{"bdf":"0000:07:00.0"},
            "model_members":dict(C.MODEL_MEMBER_SHA256), "exe_sha256":C.COMPARATOR_SHA256,
        }

    def test_demo_first_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "capture"
            probes = FixtureExecutionHarness()
            receipt_raw = canonical(self._receipt())
            obs = K.capture_execution_273("case-256", "candidate", False,
                                          self._receipt(), probes, root)
            stem = root / "source/case-256/candidate"
            expected = {
                "boot_identity.start.bin":probes.boot,
                "start_ticks.start.bin":probes.ticks,
                "process_census.start.bin":canonical({"boot_id":"recorded-boot-id", "processes":[{"pid":4321,"start_ticks":987654,"boot_id":"recorded-boot-id"}]}),
                "process_cmdline.start.bin":probes.cmdline,
                "exe_identity.start.bin":probes.exe,
                "open_model_members.start.bin":probes.members,
                "device_census.start.bin":canonical(probes.devices),
            }
            for name, data in expected.items():
                with self.subTest(probe=name):
                    self.assertEqual((stem / "raw" / name).read_bytes(), data)
                    self.assertEqual(obs["probe_inventory"][f"raw/{name}"],
                                     {"sha256":hashlib.sha256(data).hexdigest(), "bytes":len(data)})
            for bdf, samples in probes.residencies.items():
                for phase in ("start", "peak", "end"):
                    name = f"residency.{phase}.{bdf}.bin"
                    # Fixture returns canonical JSON for each ordered sample.
                    value = {"start":0,"peak":6_300_000_000 if bdf == "0000:07:00.0" else 100,"end":0}[phase]
                    data = canonical({"bytes":value})
                    self.assertEqual((stem / "raw" / name).read_bytes(), data)
                    self.assertEqual(obs["probe_inventory"][f"raw/{name}"],
                                     {"sha256":hashlib.sha256(data).hexdigest(), "bytes":len(data)})
            retained_obs = json.loads((stem / "observation.json").read_bytes())
            self.assertEqual(retained_obs["schema"], "inferswarm.issue275.collector-observation/1")
            self.assertEqual(retained_obs, obs)
            self.assertEqual((stem / "receipt.json").read_bytes(), receipt_raw)

            missing_root = Path(td) / "missing-capture"
            missing = FixtureExecutionHarness()
            missing.boot = b""
            with self.assertRaisesRegex(K.CollectorMissing, "read_boot_identity returned missing/empty output"):
                K.capture_execution_273("case-256", "candidate", False,
                                        self._receipt(), missing, missing_root)
            self.assertFalse(missing_root.exists())


if __name__ == "__main__": unittest.main()
