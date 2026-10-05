"""RED-first desired-behavior regressions for issue #276 (CPU fixture-only).

These tests drive the PRODUCTION path: retained collector originals ->
staging -> byte-deriving reader -> admission. They are fixture-only (no
hardware, network, or physical authority) and were committed RED before
the implementation, per the research-gate procedure.
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
import issue275_collector as KC
import issue276_reader as R


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode()


ROW_BYTES = 128


def fixture_row(arm: str, decision: str) -> bytes:
    """Deterministic fixture row bytes: equal across primary/repeat of one
    arm (determinism), necessarily unequal across arms (cross-vendor)."""
    seed = hashlib.sha256(f"issue276-fixture-row:{arm}:{decision}".encode()).digest()
    return seed * 2


def write_rows(run_root: Path, arm: str) -> dict[str, str]:
    digests = {}
    rows = run_root / "rows"
    rows.mkdir(parents=True, exist_ok=True)
    for d in range(C.DECISIONS):
        data = fixture_row(arm, str(d))
        (rows / f"{d}.f32").write_bytes(data)
        digests[str(d)] = hashlib.sha256(data).hexdigest()
    return digests


class Harness:
    """Configurable recording fake for the #275 collector probe surface."""

    def __init__(self, arm: str, pid: int, boot: str, ticks: int):
        self.arm = arm
        self.pid = pid
        self.boot_id = boot
        self._ticks = ticks
        self.cmdline = (b"/srv/llama-server\0--model\0" +
                        f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}".encode() + b"\0")
        self.exe = f"/srv/llama-server {C.COMPARATOR_SHA256}\n".encode()
        self.members = canonical(dict(C.MODEL_MEMBER_SHA256))
        if arm == "candidate":
            self.devices = [
                {"bdf": "0000:07:00.0", "index": 0, "vendor_id": "0x1002", "device_id": "0x6864",
                 "vulkan_uuid": C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:07:00.0"], "icd": C.RADV_ICD,
                 "name": "AMD Radeon Pro V340", "physical_type": "DISCRETE_GPU"},
                {"bdf": "0000:0b:00.0", "index": 1, "vendor_id": "0x1002", "device_id": "0x6864",
                 "vulkan_uuid": C.EXPECTED_VULKAN_DEVICE_UUIDS["0000:0b:00.0"], "icd": C.RADV_ICD,
                 "name": "AMD Radeon Pro V340", "physical_type": "DISCRETE_GPU"},
            ]
            self.env_icd = C.RADV_ICD
            self.used_driver_id = "DRIVER_ID_MESA_RADV"
        else:
            identity = C.reference_identity()
            self.devices = [
                {"bdf": identity["bdf"], "index": 0, "vendor_id": "0x10de",
                 "device_id": "0x" + identity["pci_id"].split(":")[-1],
                 "gpu_uuid": identity["gpu_uuid"], "vulkan_uuid": identity["vulkan_device_uuid"],
                 "icd": identity["icd"], "name": identity["vulkan_device_name"],
                 "physical_type": "DISCRETE_GPU"},
                {"bdf": "0000:0b:00.0", "index": 1, "vendor_id": "0x1002", "device_id": "0x67df",
                 "vulkan_uuid": "excluded-rx580-uuid", "icd": C.RADV_ICD,
                 "name": "AMD Radeon RX 580", "physical_type": "DISCRETE_GPU"},
            ]
            self.env_icd = identity["icd"]
            self.used_driver_id = KC.NVIDIA_VULKAN_DRIVER_ID
        selected_bdf = self.devices[0]["bdf"]
        excluded_bdf = self.devices[1]["bdf"]
        self.residencies = {selected_bdf: [0, 6_300_000_000, 0],
                            excluded_bdf: [0, 100, 0]}

    @property
    def ticks(self) -> bytes:
        return f"{self._ticks}\n".encode()

    @property
    def boot(self) -> bytes:
        return f"{self.boot_id}\n".encode()

    def receipt(self) -> dict:
        return {"process_attribution": {"server_pid": self.pid, "server_env": {
                    "GGML_VK_VISIBLE_DEVICES": "0", "VK_ICD_FILENAMES": self.env_icd}},
                "subject_identity": {"bdf": self.devices[0]["bdf"]},
                "model_members": dict(C.MODEL_MEMBER_SHA256),
                "exe_sha256": C.COMPARATOR_SHA256}

    # -- probe surface ------------------------------------------------------
    def read_boot_identity(self): return self.boot
    def read_start_ticks(self, pid): return self.ticks
    def read_process_census(self):
        return canonical({"boot_id": self.boot_id,
                          "processes": [{"pid": self.pid, "start_ticks": self._ticks,
                                         "boot_id": self.boot_id}]})
    def read_process_cmdline(self, pid): return self.cmdline
    def read_exe_identity(self, pid): return self.exe
    def read_open_model_members(self, pid): return self.members
    def read_device_census(self): return canonical(self.devices)
    def read_process_environ(self, pid):
        return (f"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES={self.env_icd}\0").encode()
    def read_used_vulkan_device(self, pid):
        d = self.devices[0]
        return canonical({"backend": "vulkan", "icd": d["icd"], "vulkan_uuid": d["vulkan_uuid"],
                          "bdf": d["bdf"], "index": d["index"], "driver_id": self.used_driver_id})
    def read_residency(self, bdf):
        return canonical({"bytes": self.residencies[bdf].pop(0)})


class BundleBuilder:
    """Drives the production collector path and adds fixture run rows."""

    def __init__(self, root: Path):
        self.root = root  # capture root
        self.counter = 0

    def capture(self, arm: str, repeat: bool, case: str = "case-256", pid_base: int = 4321) -> Path:
        self.counter += 1
        harness = Harness(arm, pid_base + self.counter,
                          f"{arm}-boot-{self.counter}", 900_000 + self.counter)
        tag = arm + ("-repeat" if repeat else "")
        run_root = self.root / "source" / case / tag
        KC.capture_execution_273(case, arm, repeat, harness.receipt(), harness, self.root)
        write_rows(run_root, arm)
        return run_root


class ByteAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "capture"
        self.staged = self.base / "staged"
        self.builder = BundleBuilder(self.source)

    def stage(self, arm, repeat=False, case="case-256"):
        return R.stage_capture_276(self.source, self.staged, case, arm, repeat)

    # -- positives ----------------------------------------------------------
    def test_primary_and_repeat_candidate_bundle_admits_end_to_end(self):
        self.builder.capture("candidate", False)
        self.builder.capture("candidate", True)
        self.stage("candidate", False)
        self.stage("candidate", True)
        for repeat in (False, True):
            verdict = R.admit_staged_276(self.staged, "case-256", "candidate", repeat)
            self.assertEqual(verdict["problems"], [])
            self.assertTrue(verdict["admitted"])
            self.assertEqual(verdict["derived"]["icd"], C.RADV_ICD)
            self.assertEqual(verdict["derived"]["backend"], "vulkan")
            self.assertEqual(verdict["derived"]["used_bdf"], "0000:07:00.0")

    def test_full_pair_admits_with_anti_aliasing_law(self):
        for arm in ("reference", "candidate"):
            self.builder.capture(arm, False)
            self.builder.capture(arm, True)
            self.stage(arm, False)
            self.stage(arm, True)
        verdict = R.admit_pair_276(self.staged, "case-256")
        self.assertEqual(verdict["problems"], [])
        self.assertTrue(verdict["admitted"])

    def test_demo_first_demonstration_fixture_only(self):
        """Issue #276 first demonstration (fixture-only): admit one CPU-fixture
        bundle emitted through the #275 collector path, then show that a
        substituted counterpart is rejected by the same reader/admission
        entry point. The substitution rebuilds a SELF-CONSISTENT staged unit
        (binding digests recomputed over the substituted bytes) claiming the
        candidate tag while the bytes are a reference-arm capture."""
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        self.assertTrue(R.admit_staged_276(self.staged, "case-256", "candidate", False)["admitted"])
        # Build the substituted counterpart from a genuine reference capture.
        subst_base = self.base / "substitute"
        subst_builder = BundleBuilder(subst_base / "capture")
        subst_builder.capture("reference", False)
        R.stage_capture_276(subst_base / "capture", subst_base / "staged", "case-256", "reference", False)
        import shutil
        shutil.rmtree(self.staged / "units/case-256/candidate")
        (self.staged / "units/case-256/candidate.json").unlink()
        shutil.copytree(subst_base / "staged/units/case-256/reference",
                        self.staged / "units/case-256/candidate")
        binding = json.loads((subst_base / "staged/units/case-256/reference.json").read_bytes())
        binding["arm"] = "candidate"  # relabel the custody claim, keep digests true
        (self.staged / "units/case-256/candidate.json").write_bytes(
            json.dumps(binding, sort_keys=True, indent=2).encode())
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("candidate" in p for p in verdict["problems"]))

    # -- staging law --------------------------------------------------------
    def test_staging_refuses_incomplete_source_bundle(self):
        run = self.builder.capture("candidate", False)
        (run / "raw" / "used_vulkan_device.start.bin").unlink()
        with self.assertRaisesRegex(R.ReaderError, "incomplete|missing"):
            self.stage("candidate", False)

    def test_staging_is_append_only(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        with self.assertRaises(R.ReaderError):
            self.stage("candidate", False)

    def test_staging_copies_bytes_verbatim_and_binds_digests(self):
        run = self.builder.capture("candidate", False)
        self.stage("candidate", False)
        tag_dir = self.staged / "units/case-256/candidate"
        for rel in ("receipt.json", "observation.json"):
            self.assertEqual((tag_dir / rel).read_bytes(), (run / rel).read_bytes())
        for raw in (run / "raw").iterdir():
            self.assertEqual((tag_dir / "raw" / raw.name).read_bytes(), raw.read_bytes())
        binding = json.loads((self.staged / "units/case-256/candidate.json").read_bytes())
        self.assertEqual(binding["schema"], "inferswarm.issue276.staged-binding/1")
        recomputed = hashlib.sha256((tag_dir / "receipt.json").read_bytes()).hexdigest()
        self.assertEqual(binding["files"]["receipt.json"], recomputed)

    # -- negative: byte changes --------------------------------------------
    def test_staged_byte_change_rejected_any_file(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        target = self.staged / "units/case-256/candidate/raw/process_environ.start.bin"
        data = bytearray(target.read_bytes())
        data[0] ^= 0x01
        target.write_bytes(bytes(data))
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])

    def test_staged_row_byte_change_rejected(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        target = self.staged / "units/case-256/candidate/rows/3.f32"
        data = bytearray(target.read_bytes())
        data[5] ^= 0xFF
        target.write_bytes(bytes(data))
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])

    def test_forged_integrity_chain_still_fails_on_derivation(self):
        """Mutating a raw byte AND rewriting the binding digest AND the
        observation inventory (self-consistent integrity forgery) still fails:
        the mutated environ ICD contradicts the used-device observation."""
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        tag_dir = self.staged / "units/case-256/candidate"
        env_path = tag_dir / "raw/process_environ.start.bin"
        data = bytearray(env_path.read_bytes())
        data[data.index(b"VK_ICD_FILENAMES=") + len(b"VK_ICD_FILENAMES=")] = ord("X")
        env_path.write_bytes(bytes(data))
        digest = hashlib.sha256(bytes(data)).hexdigest()
        binding_path = self.staged / "units/case-256/candidate.json"
        binding = json.loads(binding_path.read_bytes())
        binding["files"]["raw/process_environ.start.bin"] = digest
        binding_path.write_bytes(canonical(binding))
        obs_path = tag_dir / "observation.json"
        obs = json.loads(obs_path.read_bytes())
        obs["probe_inventory"]["raw/process_environ.start.bin"] = {"sha256": digest, "bytes": len(data)}
        obs_path.write_bytes(canonical(obs))
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])

    # -- negative: relabeling / substitution --------------------------------
    def test_staged_relabeling_rejected(self):
        """Rewriting the staged binding's arm label cannot move admission:
        identity is re-derived from bytes and checked against the arm law."""
        self.builder.capture("reference", False)
        self.stage("reference", False)
        binding_path = self.staged / "units/case-256/reference.json"
        binding = json.loads(binding_path.read_bytes())
        binding["arm"] = "candidate"
        binding_path.write_bytes(canonical(binding))
        verdict = R.admit_staged_276(self.staged, "case-256", "reference", False)
        self.assertFalse(verdict["admitted"])

    def test_observation_label_rewrite_rejected(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        obs_path = self.staged / "units/case-256/candidate/observation.json"
        obs = json.loads(obs_path.read_bytes())
        obs["observed_selection"]["icd"] = C.NVIDIA_ICD  # authored label flip
        obs_path.write_bytes(canonical(obs))
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])

    def test_cross_arm_substitution_rejected_both_directions(self):
        for claimed, actual in (("candidate", "reference"), ("reference", "candidate")):
            with self.subTest(claimed=claimed, actual=actual):
                base = Path(self.tmp.name) / f"sub-{claimed}-{actual}"
                builder = BundleBuilder(base / "capture")
                builder.capture(actual, False)
                R.stage_capture_276(base / "capture", base / "staged", "case-256", actual, False)
                # Claim the other arm's staged unit at admission time.
                verdict = R.admit_staged_276(base / "staged", "case-256", claimed, False)
                self.assertFalse(verdict["admitted"])

    def test_source_run_reuse_across_arms_rejected(self):
        """The same source run staged for both arms is cross-arm aliasing.

        Staging a copied candidate capture under the reference tag is
        already refused by the arm law at staging time (fail closed,
        before any pair comparison) — pinned here. When both units were
        staged from their own genuine captures, sharing a source would
        additionally be caught by receipt-digest equality in
        admit_pair_276."""
        self.builder.capture("candidate", False)
        R.stage_capture_276(self.source, self.staged, "case-256", "candidate", False)
        # Re-stage the SAME source run under the reference tag.
        import shutil
        src = self.source / "source/case-256/candidate"
        dst = self.source / "source/case-256/reference"
        shutil.copytree(src, dst)
        with self.assertRaisesRegex(R.ReaderError, "reference law"):
            R.stage_capture_276(self.source, self.staged, "case-256", "reference", False)
        # Remove the copied run; capture genuine reference/repeat units.
        shutil.rmtree(dst)
        self.builder.capture("reference", False)
        self.builder.capture("reference", True)
        self.builder.capture("candidate", True)
        R.stage_capture_276(self.source, self.staged, "case-256", "reference", False)
        R.stage_capture_276(self.source, self.staged, "case-256", "reference", True)
        R.stage_capture_276(self.source, self.staged, "case-256", "candidate", True)
        # Genuine captures admit cleanly before the attack.
        self.assertTrue(R.admit_pair_276(self.staged, "case-256")["admitted"])
        # Attack: re-bind the candidate unit to the reference run's receipt
        # digest (source reuse at the binding level). Admission must refuse.
        binding_path = self.staged / "units/case-256/candidate.json"
        binding = json.loads(binding_path.read_bytes())
        ref_binding = json.loads((self.staged / "units/case-256/reference.json").read_bytes())
        binding["files"]["receipt.json"] = ref_binding["files"]["receipt.json"]
        binding_path.write_bytes(json.dumps(binding, sort_keys=True, indent=2).encode())
        verdict = R.admit_pair_276(self.staged, "case-256")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("integrity" in p or "reuse" in p or "same source" in p
                            for p in verdict["problems"]))

    def test_repeat_row_drift_rejected_as_nondeterminism(self):
        for arm in ("reference", "candidate"):
            self.builder.capture(arm, False)
            self.builder.capture(arm, True)
            self.stage(arm, False)
            self.stage(arm, True)
        target = self.staged / "units/case-256/candidate-repeat/rows/2.f32"
        data = bytearray(target.read_bytes())
        data[0] ^= 0x55
        target.write_bytes(bytes(data))
        verdict = R.admit_pair_276(self.staged, "case-256")
        self.assertFalse(verdict["admitted"])

    # -- negative: fabricated bundles ---------------------------------------
    def test_fabricated_self_consistent_labels_without_byte_basis_rejected(self):
        """A hand-authored receipt+observation pair that tells one consistent
        reference-arm story, with no accepted collector-retained raw basis,
        fails closed: the raw bytes derive a different identity."""
        fabricated = self.base / "fabricated"
        run = fabricated / "source/case-256/reference"
        run.mkdir(parents=True)
        identity = C.reference_identity()
        receipt = {"process_attribution": {"server_pid": 1, "server_env": {
            "GGML_VK_VISIBLE_DEVICES": "0", "VK_ICD_FILENAMES": identity["icd"]}},
            "subject_identity": {"bdf": identity["bdf"]},
            "model_members": dict(C.MODEL_MEMBER_SHA256), "exe_sha256": C.COMPARATOR_SHA256}
        obs = {"schema": "inferswarm.issue275.collector-observation/1",
               "observed_selection": {"icd": identity["icd"], "backend": "vulkan",
                                      "used_bdf": identity["bdf"]},
               "probe_inventory": {}}
        (run / "receipt.json").write_bytes(canonical(receipt))
        (run / "observation.json").write_bytes(canonical(obs))
        write_rows(run, "reference")
        with self.assertRaises(R.ReaderError):
            R.stage_capture_276(fabricated, self.base / "fab-staged", "case-256", "reference", False)

    def test_fabricated_labels_over_candidate_bytes_rejected(self):
        """Fabricated reference labels pasted over authentic candidate bytes:
        internally consistent at the JSON level, rejected by derivation."""
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        identity = C.reference_identity()
        receipt = json.loads((run / "receipt.json").read_bytes())
        receipt["process_attribution"]["server_env"]["VK_ICD_FILENAMES"] = identity["icd"]
        receipt["subject_identity"]["bdf"] = identity["bdf"]
        (run / "receipt.json").write_bytes(canonical(receipt))
        obs = json.loads((run / "observation.json").read_bytes())
        obs["observed_selection"]["icd"] = identity["icd"]
        obs["observed_selection"]["used_bdf"] = identity["bdf"]
        (run / "observation.json").write_bytes(canonical(obs))
        with self.assertRaises(R.ReaderError):
            self.stage("candidate", False)

    # -- negative: incomplete staged bundles --------------------------------
    def test_staged_bundle_missing_file_fails_closed(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        (self.staged / "units/case-256/candidate/raw/boot_identity.end.bin").unlink()
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])

    def test_staged_extra_unbound_file_fails_closed(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        (self.staged / "units/case-256/candidate/raw/extra.bin").write_bytes(b"extra")
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])

    # -- trust boundary law -------------------------------------------------
    def test_no_seal_authority_is_honored(self):
        """An invented seal/hash/manifest authority field on the binding is
        rejected: no seal assertion can substitute for collector-origin bytes."""
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        binding_path = self.staged / "units/case-256/candidate.json"
        binding = json.loads(binding_path.read_bytes())
        binding["CAPTURESEAL"] = hashlib.sha256(b"attacker-seal").hexdigest()
        binding_path.write_bytes(canonical(binding))
        verdict = R.admit_staged_276(self.staged, "case-256", "candidate", False)
        self.assertFalse(verdict["admitted"])


if __name__ == "__main__":
    unittest.main()
