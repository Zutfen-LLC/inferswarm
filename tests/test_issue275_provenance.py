"""#275 provenance regressions and negative controls (CPU fixture only).

Selection provenance: actual selector/ICD/backend/used-device identity must
derive from collector-owned contemporaneous bytes (process environ +
used-Vulkan-device observation + device census), never from receipt
process_attribution.server_env claims, which are claim-only cross-checks.

Incarnation binding: boot identity + start ticks are re-observed after the
execution-owned observations; a changed process incarnation during the
capture window fails closed.

Reference/candidate identity proof: the RTX 3060/NVIDIA reference path, the
RX 580 excluded bystander, the selected V340/RADV die, and the excluded
second V340 die are mechanically distinguished in fixture coverage.

Never physical authority; no hardware, network, or holdout access.
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
    """Fixture exposing collector-owned selection/incarnation observation bytes."""

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


def candidate_receipt():
    return {
        "process_attribution": {"server_pid": 4321, "server_env": {
            "GGML_VK_VISIBLE_DEVICES": "0", "VK_ICD_FILENAMES": C.RADV_ICD}},
        "subject_identity": {"bdf": "0000:07:00.0"},
        "model_members": dict(C.MODEL_MEMBER_SHA256), "exe_sha256": C.COMPARATOR_SHA256,
    }


class CaptureTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "capture"
        self.receipt = candidate_receipt()

    def run_capture(self, probes=None, case="red-case", receipt=None, arm="candidate",
                    repeat=False):
        probes = probes or ObservedHarness()
        return K.capture_execution_273(case, arm, repeat, receipt or self.receipt,
                                       probes, self.root)

    def obs(self, case="red-case", arm="candidate"):
        return json.loads(
            (self.root / f"source/{case}/{arm}" / "observation.json").read_bytes())


class SelectionProvenanceRegressions(CaptureTestCase):
    def test_selection_derived_from_collector_owned_bytes_not_receipt(self):
        p = ObservedHarness()
        # Receipt carries NO selector/ICD claims at all: the capture still
        # succeeds because selection derives from observed bytes alone.
        claimless = json.loads(canonical(self.receipt))
        claimless["process_attribution"]["server_env"] = {}
        self.run_capture(p, receipt=claimless)
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

    def test_used_vulkan_uuid_absent_from_census_fails_closed(self):
        p = ObservedHarness()
        p.used = dict(p.used, vulkan_uuid="00000000-ffff-0000-0000-000000000000")
        with self.assertRaisesRegex(
                K.CollectorError, "absent/ambiguous in device census"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_used_vulkan_uuid_ambiguous_in_census_fails_closed(self):
        p = ObservedHarness()
        p.devices[1]["vulkan_uuid"] = p.used["vulkan_uuid"]
        # Either the census uniqueness guard or the used-UUID resolution must
        # fail closed; a duplicated used UUID is ambiguous evidence.
        with self.assertRaisesRegex(
                K.CollectorError,
                "absent/ambiguous in device census|duplicate/missing vulkan_uuid"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_malformed_used_device_bytes_fail_closed(self):
        p = ObservedHarness()
        p.used = {"backend": "vulkan"}  # missing icd/uuid/bdf/index
        with self.assertRaisesRegex(
                K.CollectorError, "used_vulkan_device missing/malformed"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_malformed_environ_bytes_fail_closed(self):
        p = ObservedHarness()
        p.environ = b"\xff\xfe not-utf8\x00"
        with self.assertRaisesRegex(K.CollectorError, "process environ"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_environ_without_selector_observation_fails_closed(self):
        p = ObservedHarness()
        p.environ = b"VK_ICD_FILENAMES=" + C.RADV_ICD.encode() + b"\0"
        with self.assertRaises(K.CollectorMissing):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_unsupported_observed_backend_fails_closed(self):
        p = ObservedHarness()
        p.used = dict(p.used, backend="cuda")
        with self.assertRaisesRegex(K.CollectorError, "unsupported observed backend"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_used_index_contradicts_census_fails_closed(self):
        p = ObservedHarness()
        p.used = dict(p.used, index=1)
        with self.assertRaisesRegex(
                K.CollectorError, "selector/used-device index disagreement"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_environ_icd_contradicts_used_device_icd_fails_closed(self):
        p = ObservedHarness()
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                     b"/usr/share/vulkan/icd.d/other.json\0")
        with self.assertRaisesRegex(
                K.CollectorError, "ICD disagrees between environ and used-device"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())


class IncarnationBindingRegressions(CaptureTestCase):
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

    def test_closing_identity_missing_fails_closed(self):
        class VanishedProcess(ObservedHarness):
            closing = False

            def read_residency(self, bdf):
                raw = ObservedHarness.read_residency(self, bdf)
                self.closing = True  # after last residency sample
                return raw

            def read_start_ticks(self, pid):
                if self.closing:
                    raise FileNotFoundError(pid)
                return ObservedHarness.read_start_ticks(self, pid)

        with self.assertRaises(K.CollectorMissing):
            self.run_capture(VanishedProcess())
        self.assertFalse(self.root.exists())


class ReferenceHostSelectionProof(CaptureTestCase):
    """inferswarm01: RTX 3060/NVIDIA selected; RX 580 positively excluded."""

    def reference_harness(self):
        identity = C.reference_identity()
        p = ObservedHarness()
        p.devices = [
            {"bdf": identity["bdf"], "index": 0, "vendor_id": "0x10de",
             "device_id": "0x" + identity["pci_id"].split(":")[-1],
             "gpu_uuid": identity["gpu_uuid"], "vulkan_uuid": identity["vulkan_device_uuid"],
             "icd": identity["icd"], "name": identity["vulkan_device_name"],
             "physical_type": "DISCRETE_GPU"},
            {"bdf": "0000:0b:00.0", "index": 1, "vendor_id": "0x1002", "device_id": "0x67df",
             "vulkan_uuid": "rx580-excluded-uuid", "icd": C.RADV_ICD,
             "name": "AMD Radeon RX 580", "physical_type": "DISCRETE_GPU"},
        ]
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                     identity["icd"].encode() + b"\0")
        p.used = {"backend": "vulkan", "icd": identity["icd"],
                  "vulkan_uuid": identity["vulkan_device_uuid"],
                  "bdf": identity["bdf"], "index": 0,
                  "driver_id": K.NVIDIA_VULKAN_DRIVER_ID}
        p.residencies = {identity["bdf"]: [0, 10, 0], "0000:0b:00.0": [0, 100, 0]}
        receipt = json.loads(canonical(self.receipt))
        receipt["process_attribution"]["server_env"]["VK_ICD_FILENAMES"] = identity["icd"]
        receipt["subject_identity"]["bdf"] = identity["bdf"]
        return p, identity, receipt

    def test_reference_proves_rtx3060_nvidia_path_and_rx580_exclusion(self):
        p, identity, receipt = self.reference_harness()
        self.run_capture(p, receipt=receipt, arm="reference", case="ref-case")
        obs = self.obs(case="ref-case", arm="reference")
        sel = obs["observed_selection"]
        self.assertEqual(sel["used_bdf"], identity["bdf"])
        self.assertEqual(sel["used_vulkan_uuid"], identity["vulkan_device_uuid"])
        self.assertEqual(sel["icd"], identity["icd"])  # NVIDIA ICD, not RADV
        self.assertEqual(sel["backend"], "vulkan")
        marked = [d for d in obs["devices"] if d["selected"]]
        self.assertEqual(marked[0]["vendor_id"], "0x10de")
        rx580 = [d for d in obs["devices"] if d["vendor_id"] == "0x1002"]
        self.assertEqual(rx580[0]["selected"], False)
        self.assertEqual(obs["residency"][rx580[0]["bdf"]]["peak"], 100)
        self.assertIn("reference_identity_expected", obs)

    def test_receipt_claims_reference_while_observed_backend_is_radv_fails_closed(self):
        # Observed bytes say the process used the RADV/RX 580 path while the
        # receipt claims the reference (NVIDIA) subject.
        p, identity, receipt = self.reference_harness()
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=1\0VK_ICD_FILENAMES=" +
                     C.RADV_ICD.encode() + b"\0")
        p.used = {"backend": "vulkan", "icd": C.RADV_ICD,
                  "vulkan_uuid": "rx580-excluded-uuid",
                  "bdf": "0000:0b:00.0", "index": 1, "driver_id": "DRIVER_ID_MESA_RADV"}
        p.residencies = {identity["bdf"]: [0, 0, 0], "0000:0b:00.0": [0, 6_300_000_000, 0]}
        with self.assertRaisesRegex(
                K.CollectorError,
                "reference observed PCI/UUID lineage mismatch|positive RX580 excluded census absent|contradicts observed"):
            self.run_capture(p, receipt=receipt, arm="reference", case="ref-case")
        self.assertFalse(self.root.exists())

    def test_receipt_claims_rtx3060_while_observed_used_device_is_rx580_candidate_arm(self):
        # Candidate arm: observed used device is the RTX 3060 (NVIDIA), not a
        # V340; the receipt's RTX 3060 labels cannot make it a valid candidate.
        p, identity, receipt = self.reference_harness()
        p.residencies = {identity["bdf"]: [0, 10, 0], "0000:0b:00.0": [0, 100, 0]}
        with self.assertRaisesRegex(
                K.CollectorError,
                "candidate observed vendor/device/ICD drift|frozen two-die BDF set"):
            self.run_capture(p, receipt=receipt, case="ref-cand-case")
        self.assertFalse(self.root.exists())


class CandidateHostSelectionProof(CaptureTestCase):
    """inferswarm05: exactly one V340 die selected via RADV; second die excluded."""

    def test_selected_and_second_die_mechanically_distinguished(self):
        p = ObservedHarness()
        self.run_capture(p, case="cand-case")
        obs = self.obs(case="cand-case")
        sel = obs["observed_selection"]
        self.assertEqual(sel["icd"], C.RADV_ICD)
        self.assertEqual(sel["backend"], "vulkan")
        self.assertEqual(sel["used_bdf"], "0000:07:00.0")
        self.assertEqual(sel["used_vulkan_uuid"],
                         C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"])
        second = [d for d in obs["devices"] if d["bdf"] == "0000:0b:00.0"][0]
        self.assertFalse(second["selected"])
        self.assertEqual(obs["residency"]["0000:0b:00.0"],
                         {"before": 0, "peak": 100, "after": 0})

    def test_receipt_claims_candidate_while_observed_backend_is_nvidia_fails_closed(self):
        identity = C.reference_identity()
        p = ObservedHarness()
        p.devices = [
            {"bdf": identity["bdf"], "index": 0, "vendor_id": "0x10de",
             "device_id": "0x" + identity["pci_id"].split(":")[-1],
             "gpu_uuid": identity["gpu_uuid"], "vulkan_uuid": identity["vulkan_device_uuid"],
             "icd": identity["icd"], "name": identity["vulkan_device_name"],
             "physical_type": "DISCRETE_GPU"},
        ]
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                     identity["icd"].encode() + b"\0")
        p.used = {"backend": "vulkan", "icd": identity["icd"],
                  "vulkan_uuid": identity["vulkan_device_uuid"],
                  "bdf": identity["bdf"], "index": 0,
                  "driver_id": K.NVIDIA_VULKAN_DRIVER_ID}
        p.residencies = {identity["bdf"]: [0, 10, 0]}
        bad = json.loads(canonical(self.receipt))
        bad["process_attribution"]["server_env"]["VK_ICD_FILENAMES"] = identity["icd"]
        bad["subject_identity"]["bdf"] = identity["bdf"]
        with self.assertRaisesRegex(
                K.CollectorError,
                "candidate observed vendor/device/ICD drift|frozen two-die BDF set"):
            self.run_capture(p, receipt=bad, case="cand-case")
        self.assertFalse(self.root.exists())


class ReviewRoundBlockingRegressions(CaptureTestCase):
    """Regressions for the independent-review blocking findings (round 4)."""

    def test_candidate_census_omitting_second_die_fails_closed(self):
        p = ObservedHarness()
        p.devices = [p.devices[0]]  # second V340 die omitted entirely
        p.residencies = {"0000:07:00.0": [0, 6_300_000_000, 0]}
        with self.assertRaisesRegex(
                K.CollectorError, "frozen two-die BDF set"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_candidate_census_extra_device_fails_closed(self):
        p = ObservedHarness()
        p.devices.append({"bdf": "0000:0f:00.0", "index": 2, "vendor_id": "0x1002",
                          "device_id": "0x6864", "vulkan_uuid": "extra-uuid",
                          "icd": C.RADV_ICD, "name": "AMD Radeon Pro V340",
                          "physical_type": "DISCRETE_GPU"})
        p.residencies["0000:0f:00.0"] = [0, 100, 0]
        with self.assertRaisesRegex(
                K.CollectorError, "frozen two-die BDF set"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_candidate_contradictory_driver_id_fails_closed(self):
        p = ObservedHarness()
        p.used = dict(p.used, driver_id="DRIVER_ID_NVIDIA_PROPRIETARY")
        with self.assertRaisesRegex(
                K.CollectorError, "Vulkan driver identity drift"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_candidate_missing_driver_id_fails_closed(self):
        p = ObservedHarness()
        p.used = {k: v for k, v in p.used.items() if k != "driver_id"}
        with self.assertRaisesRegex(
                K.CollectorError, "used_vulkan_device missing/malformed driver_id"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_reference_contradictory_driver_id_fails_closed(self):
        identity = C.reference_identity()
        p = ObservedHarness()
        p.devices = [
            {"bdf": identity["bdf"], "index": 0, "vendor_id": "0x10de",
             "device_id": "0x" + identity["pci_id"].split(":")[-1],
             "gpu_uuid": identity["gpu_uuid"], "vulkan_uuid": identity["vulkan_device_uuid"],
             "icd": identity["icd"], "name": identity["vulkan_device_name"],
             "physical_type": "DISCRETE_GPU"},
            {"bdf": "0000:0b:00.0", "index": 1, "vendor_id": "0x1002", "device_id": "0x67df",
             "vulkan_uuid": "rx580-excluded-uuid", "icd": C.RADV_ICD,
             "name": "AMD Radeon RX 580", "physical_type": "DISCRETE_GPU"},
        ]
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                     identity["icd"].encode() + b"\0")
        p.used = {"backend": "vulkan", "icd": identity["icd"],
                  "vulkan_uuid": identity["vulkan_device_uuid"],
                  "bdf": identity["bdf"], "index": 0,
                  "driver_id": "nvidia"}  # kernel-driver domain, NOT VkDriverId
        p.residencies = {identity["bdf"]: [0, 10, 0], "0000:0b:00.0": [0, 100, 0]}
        receipt = json.loads(canonical(self.receipt))
        receipt["process_attribution"]["server_env"]["VK_ICD_FILENAMES"] = identity["icd"]
        receipt["subject_identity"]["bdf"] = identity["bdf"]
        with self.assertRaisesRegex(
                K.CollectorError, "reference observed PCI/UUID lineage mismatch"):
            self.run_capture(p, receipt=receipt, arm="reference", case="ref-driver-case")
        self.assertFalse(self.root.exists())

    def test_duplicate_json_keys_in_used_device_fail_closed(self):
        p = ObservedHarness()
        raw = (b'{"backend": "vulkan", "icd": "' + C.RADV_ICD.encode() +
               b'", "vulkan_uuid": "' + C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"].encode() +
               b'", "vulkan_uuid": "conflicting-uuid", "bdf": "0000:07:00.0", "index": 0}')
        class DuplicateKeyUsed(ObservedHarness):
            def read_used_vulkan_device(self, pid):
                self.calls.append(("used", pid)); return raw
        with self.assertRaisesRegex(K.CollectorError, "used_vulkan_device malformed"):
            self.run_capture(DuplicateKeyUsed())
        self.assertFalse(self.root.exists())

    def test_whitespace_only_boot_identity_fails_closed(self):
        p = ObservedHarness()
        p.boot = b" \n"
        with self.assertRaisesRegex(K.CollectorError, "boot identity empty"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_negative_start_ticks_fails_closed(self):
        p = ObservedHarness()
        p.ticks = b"-1\n"
        with self.assertRaisesRegex(K.CollectorError, "start ticks negative"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_huge_selector_string_fails_closed_as_error(self):
        p = ObservedHarness()
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=" + b"9" * 5000 +
                     b"\0VK_ICD_FILENAMES=" + C.RADV_ICD.encode() + b"\0")
        with self.assertRaises(K.CollectorError):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_unimplemented_probe_method_is_collector_missing(self):
        class IncompleteHarness(ObservedHarness):
            def read_process_environ(self, pid):
                raise NotImplementedError
        with self.assertRaises(K.CollectorMissing):
            self.run_capture(IncompleteHarness())
        self.assertFalse(self.root.exists())

    def test_missing_probe_attribute_is_collector_missing(self):
        class NoEnvironHarness:
            # Exposes every probe surface EXCEPT read_process_environ.
            def __init__(self):
                self.inner = ObservedHarness()
            def __getattr__(self, name):
                if name == "read_process_environ":
                    raise AttributeError(name)
                return getattr(self.inner, name)
        with self.assertRaises(K.CollectorMissing):
            self.run_capture(NoEnvironHarness())
        self.assertFalse(self.root.exists())

    def test_residency_boolean_bytes_rejected(self):
        p = ObservedHarness()
        orig = ObservedHarness.read_residency
        state = {"n": 0}
        def read_residency(self, bdf):
            self.calls.append(("residency", bdf))
            state["n"] += 1
            if state["n"] == 2:  # peak sample of first device
                return canonical({"bytes": True})
            return orig(self, bdf)
        p.read_residency = lambda bdf: read_residency(p, bdf)
        with self.assertRaisesRegex(K.CollectorError, "counter malformed"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_residency_non_object_rejected(self):
        p = ObservedHarness()
        orig = ObservedHarness.read_residency
        state = {"n": 0}
        def read_residency(self, bdf):
            state["n"] += 1
            if state["n"] == 2:
                return b"[]"
            return orig(self, bdf)
        p.read_residency = lambda bdf: read_residency(p, bdf)
        with self.assertRaisesRegex(K.CollectorError, "counter malformed"):
            self.run_capture(p)
        self.assertFalse(self.root.exists())

    def test_reference_identity_is_labeled_expected_not_observed(self):
        self.run_capture(case="label-case", arm="candidate")
        obs = self.obs(case="label-case")
        self.assertNotIn("reference_identity", obs)
        # reference arm emits the frozen identity under an expected-label key
        identity = C.reference_identity()
        p = ObservedHarness()
        p.devices = [
            {"bdf": identity["bdf"], "index": 0, "vendor_id": "0x10de",
             "device_id": "0x" + identity["pci_id"].split(":")[-1],
             "gpu_uuid": identity["gpu_uuid"], "vulkan_uuid": identity["vulkan_device_uuid"],
             "icd": identity["icd"], "name": identity["vulkan_device_name"],
             "physical_type": "DISCRETE_GPU"},
            {"bdf": "0000:0b:00.0", "index": 1, "vendor_id": "0x1002", "device_id": "0x67df",
             "vulkan_uuid": "rx580-excluded-uuid", "icd": C.RADV_ICD,
             "name": "AMD Radeon RX 580", "physical_type": "DISCRETE_GPU"},
        ]
        p.environ = (b"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES=" +
                     identity["icd"].encode() + b"\0")
        p.used = {"backend": "vulkan", "icd": identity["icd"],
                  "vulkan_uuid": identity["vulkan_device_uuid"],
                  "bdf": identity["bdf"], "index": 0,
                  "driver_id": K.NVIDIA_VULKAN_DRIVER_ID}
        p.residencies = {identity["bdf"]: [0, 10, 0], "0000:0b:00.0": [0, 100, 0]}
        receipt = json.loads(canonical(self.receipt))
        receipt["process_attribution"]["server_env"]["VK_ICD_FILENAMES"] = identity["icd"]
        receipt["subject_identity"]["bdf"] = identity["bdf"]
        self.run_capture(p, receipt=receipt, arm="reference", case="label-ref-case")
        ref_obs = self.obs(case="label-ref-case", arm="reference")
        self.assertIn("reference_identity_expected", ref_obs)
        self.assertNotIn("reference_identity", ref_obs)


class AppendOnlyPreservation(CaptureTestCase):
    def test_append_only_and_non_destructive_behavior_remains_intact(self):
        self.run_capture(case="preserve-case")
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaises(K.CollectorError):
            self.run_capture(case="preserve-case")
        after = {p.relative_to(self.root): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
