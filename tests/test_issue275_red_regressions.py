"""RED-first regressions for the reviewed #275 collector provenance defect.

Desired behavior under #275 (all CPU-fixture; never physical authority):

(a) the selected device/backend must be derived from collector-owned
    contemporaneous observation bytes (process environ + used-device
    observation + device census), never from receipt
    process_attribution.server_env selector/ICD claims;
(b) flipping receipt selector/ICD values must fail closed as a claim
    contradiction, not move the selection;
(c) a capture lacking independent observed backend/device-selection
    evidence must be rejected (CollectorMissing) even when the receipt
    supplies selector/ICD values;
(d) a process incarnation changing between the initial identity capture
    and the closing observation must be detected and fail closed.

At reviewed head 246063afaa5f5aea470673e982df6a7b26b2ceef these tests are
RED (the defect is present). They must be GREEN after the fix.
"""
from __future__ import annotations

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


class ObservedHarness:
    """Fixture with collector-owned selection/incarnation observation bytes."""

    def __init__(self):
        self.pid = 4321
        self.boot = b"recorded-boot-id\n"
        self.ticks = b"987654\n"
        self.cmdline = (b"/srv/llama-server\0--model\0" +
                        f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}".encode() + b"\0")
        self.exe = f"/srv/llama-server {C.COMPARATOR_SHA256}\n".encode()
        self.members = canonical({n: d for n, d in C.MODEL_MEMBER_SHA256.items()})
        self.devices = [
            {"bdf": "0000:07:00.0", "index": 0, "vendor_id": "0x1002", "device_id": "0x6864",
             "vulkan_uuid": C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"], "icd": C.RADV_ICD,
             "name": "AMD Radeon Pro V340", "physical_type": "DISCRETE_GPU"},
            {"bdf": "0000:0b:00.0", "index": 1, "vendor_id": "0x1002", "device_id": "0x6864",
             "vulkan_uuid": C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:0b:00.0"], "icd": C.RADV_ICD,
             "name": "AMD Radeon Pro V340", "physical_type": "DISCRETE_GPU"},
        ]
        self.environ = (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                        C.RADV_ICD.encode() + b"\0")
        self.used = {"backend": "vulkan", "icd": C.RADV_ICD,
                     "vulkan_uuid": C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"],
                     "bdf": "0000:07:00.0", "index": 0,
                     "driver_id": "DRIVER_ID_MESA_RADV"}
        self.residencies = {"0000:07:00.0": [0, 6_300_000_000, 0],
                            "0000:0b:00.0": [0, 100, 0]}
        self.calls = []

    def read_boot_identity(self):
        self.calls.append("boot"); return self.boot

    def read_start_ticks(self, pid):
        self.calls.append(("ticks", pid)); return self.ticks

    def read_process_census(self):
        self.calls.append("census")
        return canonical({"boot_id": self.boot.decode().strip(),
                          "processes": [{"pid": self.pid, "start_ticks": int(self.ticks),
                                         "boot_id": self.boot.decode().strip()}]})

    def read_process_cmdline(self, pid):
        self.calls.append(("cmdline", pid)); return self.cmdline

    def read_exe_identity(self, pid):
        self.calls.append(("exe", pid)); return self.exe

    def read_open_model_members(self, pid):
        self.calls.append(("members", pid)); return self.members

    def read_device_census(self):
        self.calls.append("devices"); return canonical(self.devices)

    def read_process_environ(self, pid):
        self.calls.append(("environ", pid)); return self.environ

    def read_used_vulkan_device(self, pid):
        self.calls.append(("used", pid)); return canonical(self.used)

    def read_residency(self, bdf):
        self.calls.append(("residency", bdf))
        return canonical({"bytes": self.residencies[bdf].pop(0)})


class SelectionProvenanceRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "capture"
        self.receipt = {
            "process_attribution": {"server_pid": 4321, "server_env": {
                "GGML_VK_VISIBLE_DEVICES": "0", "VK_ICD_FILENAMES": C.RADV_ICD}},
            "subject_identity": {"bdf": "0000:07:00.0"},
            "model_members": dict(C.MODEL_MEMBER_SHA256), "exe_sha256": C.COMPARATOR_SHA256,
        }

    def run_capture(self, probes=None, case="red-case", receipt=None, arm="candidate"):
        probes = probes or ObservedHarness()
        return K.capture_execution_273(case, arm, False, receipt or self.receipt,
                                       probes, self.root)

    def obs(self, case="red-case", arm="candidate"):
        return json.loads(
            (self.root / f"source/{case}/{arm}" / "observation.json").read_bytes())

    def test_selection_derived_from_collector_owned_bytes_not_receipt(self):
        p = ObservedHarness()
        # Receipt tries to author the OTHER die; observed bytes say 07:00.0.
        bad = json.loads(canonical(self.receipt))
        bad["process_attribution"]["server_env"]["GGML_VK_VISIBLE_DEVICES"] = "1"
        bad["subject_identity"]["bdf"] = "0000:0b:00.0"
        p.residencies = {"0000:07:00.0": [0, 6_300_000_000, 0],
                         "0000:0b:00.0": [0, 100, 0]}
        self.run_capture(p, receipt=bad)
        obs = self.obs()
        sel = [d for d in obs["devices"] if d["selected"]]
        self.assertEqual(sel[0]["bdf"], "0000:07:00.0")
        self.assertEqual(obs["observed_selection"]["used_bdf"], "0000:07:00.0")
        self.assertEqual(obs["observed_selection"]["icd"], C.RADV_ICD)
        self.assertEqual(obs["observed_selection"]["selector"], "0")
        self.assertIn("raw/process_environ.start.bin",
                      obs["observed_selection"]["derived_from"])
        self.assertIn("raw/used_vulkan_device.start.bin",
                      obs["observed_selection"]["derived_from"])

    def test_receipt_selector_disagreement_fails_closed(self):
        bad = json.loads(canonical(self.receipt))
        bad["process_attribution"]["server_env"]["GGML_VK_VISIBLE_DEVICES"] = "1"
        with self.assertRaisesRegex(
                K.CollectorError,
                "GGML_VK_VISIBLE_DEVICES contradicts observed selector"):
            self.run_capture(receipt=bad)
        self.assertFalse(self.root.exists())

    def test_receipt_icd_disagreement_fails_closed(self):
        bad = json.loads(canonical(self.receipt))
        bad["process_attribution"]["server_env"]["VK_ICD_FILENAMES"] = "/other/icd.json"
        with self.assertRaisesRegex(
                K.CollectorError, "VK_ICD_FILENAMES contradicts observed ICD"):
            self.run_capture(receipt=bad)
        self.assertFalse(self.root.exists())

    def test_missing_independent_selection_observation_rejected(self):
        class NoSelectionObservation(ObservedHarness):
            def read_process_environ(self, pid):
                raise FileNotFoundError(pid)

        with self.assertRaises(K.CollectorMissing):
            self.run_capture(NoSelectionObservation())
        self.assertFalse(self.root.exists())

    def test_receipt_only_data_cannot_restore_missing_observation(self):
        class EmptyUsedObservation(ObservedHarness):
            def read_used_vulkan_device(self, pid):
                return b""

        # The receipt carries full selector/ICD claims, yet the capture must
        # fail closed: claims are not observations.
        with self.assertRaises(K.CollectorMissing):
            self.run_capture(EmptyUsedObservation())
        self.assertFalse(self.root.exists())


class IncarnationBindingRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "capture"
        self.receipt = {
            "process_attribution": {"server_pid": 4321, "server_env": {
                "GGML_VK_VISIBLE_DEVICES": "0", "VK_ICD_FILENAMES": C.RADV_ICD}},
            "subject_identity": {"bdf": "0000:07:00.0"},
            "model_members": dict(C.MODEL_MEMBER_SHA256), "exe_sha256": C.COMPARATOR_SHA256,
        }

    def run_capture(self, probes, case="red-case"):
        return K.capture_execution_273(case, "candidate", False, self.receipt,
                                       probes, self.root)

    def test_start_ticks_change_during_capture_detected(self):
        class ReplacedHarness(ObservedHarness):
            def read_residency(self, bdf):
                # PID reused by a new incarnation after identity capture.
                self.ticks = b"111111\n"
                return ObservedHarness.read_residency(self, bdf)

        with self.assertRaisesRegex(K.CollectorError, "incarnation changed"):
            self.run_capture(ReplacedHarness())
        self.assertFalse(self.root.exists())

    def test_boot_identity_change_during_capture_detected(self):
        class RebootedHarness(ObservedHarness):
            def read_residency(self, bdf):
                self.boot = b"other-boot-id\n"
                return ObservedHarness.read_residency(self, bdf)

        with self.assertRaisesRegex(K.CollectorError, "incarnation changed"):
            self.run_capture(RebootedHarness())
        self.assertFalse(self.root.exists())

    def test_closing_identity_bytes_retained_and_bound(self):
        p = ObservedHarness()
        self.run_capture(p)
        stem = self.root / "source/red-case/candidate"
        self.assertEqual((stem / "raw/boot_identity.end.bin").read_bytes(), p.boot)
        self.assertEqual((stem / "raw/start_ticks.end.bin").read_bytes(), p.ticks)
        obs = json.loads((stem / "observation.json").read_bytes())
        close = obs["process"]["incarnation_close"]
        self.assertEqual(close["boot_id"], "recorded-boot-id")
        self.assertEqual(close["start_ticks"], 987654)
        self.assertTrue(close["bound_same_process"])


if __name__ == "__main__":
    unittest.main()
