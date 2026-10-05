"""RED-first desired-behavior regressions for issue #276 (CPU fixture-only).

These tests drive the PRODUCTION path: retained collector originals ->
staging -> byte-deriving reader -> admission. They are fixture-only (no
hardware, network, or physical authority) and were committed RED before
the implementation, per the research-gate procedure.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
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


_ROW_CACHE: dict[tuple[str, str], bytes] = {}


def fixture_row(arm: str, decision: str) -> bytes:
    """Deterministic fixture row bytes: full-vocabulary finite FP32, equal
    across primary/repeat of one arm (determinism), necessarily unequal
    across arms (cross-vendor)."""
    key = (arm, decision)
    if key in _ROW_CACHE:
        return _ROW_CACHE[key]
    seed = hashlib.sha256(f"issue276-fixture-row:{arm}:{decision}".encode()).digest()
    blocks = []
    counter = 0
    while len(blocks) * 32 < C.ROW_BYTES + 4:
        blocks.append(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    stream = b"".join(blocks)[:C.ROW_BYTES]
    n = C.ROW_BYTES // 4
    words = struct.unpack(f"<{n}I", stream)
    values = [math.ldexp(w % 1_000_000, -20) for w in words]
    row = struct.pack(f"<{n}f", *values)
    _ROW_CACHE[key] = row
    return row


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
            verdict = R.admit_staged_276(self.staged, custody_root=self.source,
                                         case="case-256", arm="candidate", repeat=repeat)
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
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
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
        self.assertTrue(R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)["admitted"])
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
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
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
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])

    def test_staged_row_byte_change_rejected(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        target = self.staged / "units/case-256/candidate/rows/3.f32"
        data = bytearray(target.read_bytes())
        data[5] ^= 0xFF
        target.write_bytes(bytes(data))
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
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
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
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
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="reference", repeat=False)
        self.assertFalse(verdict["admitted"])

    def test_observation_label_rewrite_rejected(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        obs_path = self.staged / "units/case-256/candidate/observation.json"
        obs = json.loads(obs_path.read_bytes())
        obs["observed_selection"]["icd"] = C.NVIDIA_ICD  # authored label flip
        obs_path.write_bytes(canonical(obs))
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])

    def test_cross_arm_substitution_rejected_both_directions(self):
        for claimed, actual in (("candidate", "reference"), ("reference", "candidate")):
            with self.subTest(claimed=claimed, actual=actual):
                base = Path(self.tmp.name) / f"sub-{claimed}-{actual}"
                builder = BundleBuilder(base / "capture")
                builder.capture(actual, False)
                R.stage_capture_276(base / "capture", base / "staged", "case-256", actual, False)
                # Claim the other arm's staged unit at admission time.
                verdict = R.admit_staged_276(base / "staged", custody_root=base / "capture",
                                             case="case-256", arm=claimed, repeat=False)
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
        self.assertTrue(R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")["admitted"])
        # Attack: re-bind the candidate unit to the reference run's receipt
        # digest (source reuse at the binding level). Admission must refuse.
        binding_path = self.staged / "units/case-256/candidate.json"
        binding = json.loads(binding_path.read_bytes())
        ref_binding = json.loads((self.staged / "units/case-256/reference.json").read_bytes())
        binding["files"]["receipt.json"] = ref_binding["files"]["receipt.json"]
        binding_path.write_bytes(json.dumps(binding, sort_keys=True, indent=2).encode())
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
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
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
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
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])

    def test_staged_extra_unbound_file_fails_closed(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        (self.staged / "units/case-256/candidate/raw/extra.bin").write_bytes(b"extra")
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
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
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])

    # -- negative: review round 1 gaps ---------------------------------------
    def test_receipt_pid_contradiction_rejected(self):
        """Receipt server_pid is a claim against the byte-derived census pid."""
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        receipt = json.loads((run / "receipt.json").read_bytes())
        receipt["process_attribution"]["server_pid"] = 777777
        (run / "receipt.json").write_bytes(canonical(receipt))
        with self.assertRaisesRegex(R.ReaderError, "server_pid"):
            self.stage("candidate", False)

    def test_observation_exe_path_contradiction_rejected(self):
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        obs = json.loads((run / "observation.json").read_bytes())
        obs["process"]["exe"]["path"] = "/srv/donor-executable"
        (run / "observation.json").write_bytes(canonical(obs))
        with self.assertRaisesRegex(R.ReaderError, "exe"):
            self.stage("candidate", False)

    def test_observation_cmdline_contradiction_rejected(self):
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        obs = json.loads((run / "observation.json").read_bytes())
        obs["process"]["cmdline"] = ["/srv/other", "--model", "/tmp/wrong.gguf"]
        (run / "observation.json").write_bytes(canonical(obs))
        with self.assertRaisesRegex(R.ReaderError, "cmdline"):
            self.stage("candidate", False)

    def test_missing_metadata_files_rejected_at_admission(self):
        """Deleting receipt/observation from a staged unit cannot bypass
        derivation by omitting the labels entirely."""
        for victim in ("receipt.json", "observation.json"):
            with self.subTest(victim=victim):
                base = self.base / f"meta-{victim}"
                builder = BundleBuilder(base / "capture")
                builder.capture("candidate", False)
                R.stage_capture_276(base / "capture", base / "staged", "case-256",
                                    "candidate", False)
                target = base / "staged/units/case-256/candidate" / victim
                target.unlink()
                self._repair_binding(tag="candidate", staged=base / "staged")
                verdict = R.admit_staged_276(base / "staged", custody_root=base / "capture",
                                             case="case-256", arm="candidate", repeat=False)
                self.assertFalse(verdict["admitted"])
                self.assertTrue(any("mandatory" in p for p in verdict["problems"]))

    def test_non_f32_row_content_rejected(self):
        """Rows must be full-vocabulary finite FP32, not arbitrary strings."""
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        target = self.staged / "units/case-256/candidate/rows/3.f32"
        target.write_bytes(b"candidate")
        self._repair_binding()
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("FP32" in p or "row" in p for p in verdict["problems"]))

    def test_binding_campaign_and_source_stem_validated(self):
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        binding_path = self.staged / "units/case-256/candidate.json"
        binding = json.loads(binding_path.read_bytes())
        binding["campaign"] = "attacker-campaign"
        binding_path.write_bytes(canonical(binding))
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("campaign" in p for p in verdict["problems"]))

    def test_unknown_arm_fails_closed(self):
        """Only the two frozen arms exist; any other label is refused."""
        self.builder.capture("candidate", False)
        with self.assertRaisesRegex(R.ReaderError, "unknown arm"):
            self.stage("attacker-arm", False)
        verdict = R.admit_staged_276(self.staged, custody_root=self.source, case="case-256", arm="attacker-arm", repeat=False)
        self.assertFalse(verdict["admitted"])

    def test_duplicate_json_keys_rejected(self):
        """Duplicate keys in any probe document fail closed, matching the
        collector's law (ambiguous identity cannot resolve last-wins)."""
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        raw = (run / "raw/used_vulkan_device.start.bin").read_bytes()
        # Insert a duplicate "backend" key before the canonical close.
        marker = b'\n  "backend": "vulkan"'
        assert marker in raw
        forged = raw.replace(marker, marker[:-len('"vulkan"')] + b'"cpu",\n  "backend": "vulkan"', 1)
        (run / "raw/used_vulkan_device.start.bin").write_bytes(forged)
        with self.assertRaisesRegex(R.ReaderError, "duplicate key"):
            self.stage("candidate", False)

    def test_census_boot_contradiction_rejected(self):
        """Top-level census boot_id must agree with the boot bytes, matching
        the collector's law."""
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        census = json.loads((run / "raw/process_census.start.bin").read_bytes())
        census["boot_id"] = "other-boot-id"
        (run / "raw/process_census.start.bin").write_bytes(canonical(census))
        with self.assertRaisesRegex(R.ReaderError, "census/boot"):
            self.stage("candidate", False)

    def test_repeat_impersonation_rejected(self):
        """One capture cannot serve as its own repeat: primary/repeat must
        differ in process incarnation and source receipt."""
        self.builder.capture("candidate", False)
        import shutil
        src = self.source / "source/case-256/candidate"
        dst = self.source / "source/case-256/candidate-repeat"
        shutil.copytree(src, dst)
        R.stage_capture_276(self.source, self.staged, "case-256", "candidate", False)
        R.stage_capture_276(self.source, self.staged, "case-256", "candidate", True)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("repeat" in p.lower() for p in verdict["problems"]))

    def test_unilateral_row_copy_rejected_on_aliasing(self):
        """A one-directional row copy across arms IS detectable and rejected
        (the bilateral-permutation history here must not be read as 'all
        row attacks pass'). With custody binding (round 3) the copy is
        caught by the original-to-staged comparison first; the cross-arm
        aliasing signature remains the catch for digest-only callers."""
        for arm in ("reference", "candidate"):
            self.builder.capture(arm, False)
            self.builder.capture(arm, True)
            self.stage(arm, False)
            self.stage(arm, True)
        target = self.staged / "units/case-256/reference/rows/0.f32"
        donor = (self.staged / "units/case-256/candidate/rows/0.f32").read_bytes()
        target.write_bytes(donor)
        self._repair_binding("reference")
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("aliasing" in p or "custody" in p or "original" in p
                            for p in verdict["problems"]))
        # Legacy form (no retained custody at hand): the aliasing law
        # itself still rejects the unilateral copy.
        verdict_legacy = R.admit_pair_276(self.staged, case="case-256")
        self.assertFalse(verdict_legacy["admitted"])
        self.assertTrue(any("aliasing" in p for p in verdict_legacy["problems"]))

    def test_documented_origin_boundary_fully_authored_bundle_admits(self):
        """DOCUMENTED LIMITATION (canary) — open origin observation, round 2.

        A COMPLETE self-consistent bundle authored without the collector
        (raw bytes + labels + probe inventory all written consistently)
        admits at the fixture level. Nothing in a CPU fixture can confer
        collector origin: the collector's probe surface is itself
        fixture-supplied, and the derivation law is public repository
        code, so a knowledgeable author can satisfy shape-consistency.
        Origin rests on the PHYSICAL campaign boundary (reviewed collector
        code reading a contemporaneous OS the executor does not control),
        exactly as the #276 acceptance states: hashes prove byte
        integrity within that boundary, not origin by themselves.
        This pin makes the limitation falsifiable: when the physical
        campaign adds capture-window row binding or another origin
        mechanism, this test must be inverted or deleted alongside the
        boundary documentation."""
        base = self.base / "canary-fab"
        capture = base / "capture"
        staged = base / "staged"
        # Hand-author all four runs WITHOUT invoking the collector.
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                tag = arm + ("-repeat" if repeat else "")
                run = capture / "source/case-256" / tag
                (run / "raw").mkdir(parents=True)
                harness = Harness(arm,
                                  (5000 if arm == "reference" else 6000) + (1 if repeat else 0),
                                  f"authored-{tag}",
                                  (700_000 if arm == "reference" else 800_000) + (1 if repeat else 0))
                # raw probe bytes, authored:
                (run / "raw/boot_identity.start.bin").write_bytes(harness.boot)
                (run / "raw/start_ticks.start.bin").write_bytes(harness.ticks)
                (run / "raw/process_census.start.bin").write_bytes(
                    canonical({"boot_id": harness.boot_id,
                               "processes": [{"pid": harness.pid, "start_ticks": harness._ticks,
                                              "boot_id": harness.boot_id}]}))
                (run / "raw/process_cmdline.start.bin").write_bytes(harness.cmdline)
                (run / "raw/exe_identity.start.bin").write_bytes(harness.exe)
                (run / "raw/open_model_members.start.bin").write_bytes(harness.members)
                (run / "raw/device_census.start.bin").write_bytes(canonical(harness.devices))
                (run / "raw/process_environ.start.bin").write_bytes(
                    f"GGML_VK_VISIBLE_DEVICES=0\0VK_ICD_FILENAMES={harness.env_icd}\0".encode())
                d0 = harness.devices[0]
                (run / "raw/used_vulkan_device.start.bin").write_bytes(canonical({
                    "backend": "vulkan", "icd": d0["icd"], "vulkan_uuid": d0["vulkan_uuid"],
                    "bdf": d0["bdf"], "index": d0["index"], "driver_id": harness.used_driver_id}))
                for bdf, samples in harness.residencies.items():
                    for phase, value in zip(("start", "peak", "end"), samples):
                        (run / f"raw/residency.{phase}.{bdf}.bin").write_bytes(
                            canonical({"bytes": value}))
                (run / "raw/boot_identity.end.bin").write_bytes(harness.boot)
                (run / "raw/start_ticks.end.bin").write_bytes(harness.ticks)
                # receipt + rows + collector-shaped observation, authored:
                (run / "receipt.json").write_bytes(canonical(harness.receipt()))
                rows = run / "rows"
                rows.mkdir()
                digests = {}
                for d in range(C.DECISIONS):
                    data = fixture_row(arm, str(d))
                    (rows / f"{d}.f32").write_bytes(data)
                    digests[f"rows/{d}.f32"] = hashlib.sha256(data).hexdigest()
                inventory = {}
                for p in sorted(run.rglob("*")):
                    if p.is_file() and p.parent.name == "raw":
                        rel = "raw/" + p.name
                        inventory[rel] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                          "bytes": p.stat().st_size}
                obs = {"schema": KC.SCHEMA, "captured_at": "2026-10-05T00:00:00+00:00",
                       "probe_inventory": inventory,
                       "process": {"pid": harness.pid, "boot_id": harness.boot_id,
                                   "start_ticks": harness._ticks,
                                   "cmdline": harness.cmdline.decode().rstrip("\0").split("\0"),
                                   "exe": {"path": "/srv/llama-server",
                                           "sha256": C.COMPARATOR_SHA256},
                                   "effective_model": f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}",
                                   "open_model_members": dict(C.MODEL_MEMBER_SHA256),
                                   "incarnation_close": {"boot_id": harness.boot_id,
                                                         "start_ticks": harness._ticks,
                                                         "bound_same_process": True,
                                                         "derived_from": ["raw/boot_identity.end.bin",
                                                                          "raw/start_ticks.end.bin"]}},
                       "devices": [dict(d, **{"selected": d is d0}) for d in harness.devices],
                       "residency": {bdf: dict(zip(("before", "peak", "after"), s))
                                     for bdf, s in harness.residencies.items()},
                       "observed_selection": {
                           "derived_from": ["raw/process_environ.start.bin",
                                            "raw/used_vulkan_device.start.bin",
                                            "raw/device_census.start.bin"],
                           "selector_env_key": "GGML_VK_VISIBLE_DEVICES", "selector": "0",
                           "icd_env_key": "VK_ICD_FILENAMES", "icd": harness.env_icd,
                           "backend": "vulkan", "used_vulkan_uuid": d0["vulkan_uuid"],
                           "used_bdf": d0["bdf"], "used_index": d0["index"],
                           "used_driver_id": harness.used_driver_id},
                       "receipt_claims_checked": []}
                if arm == "reference":
                    obs["reference_identity_expected"] = C.reference_identity()
                (run / "observation.json").write_bytes(canonical(obs))
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                R.stage_capture_276(capture, staged, "case-256", arm, repeat)
        verdict = R.admit_pair_276(staged, custody_root=capture, case="case-256")
        # The pinned documented limitation: this ADMITS at the fixture level.
        self.assertTrue(verdict["admitted"], verdict["problems"])

    def test_bilateral_staged_row_permutation_now_rejected_round3(self):
        """INVERTED round-3 canary (was: documented origin boundary).

        Round 2 pinned that ANY bilateral permutation of row bytes
        across arms survived the reader because rows had no upstream
        derivation source. Round 3 closes exactly that gap: admission
        binds every staged byte to its collector-owned retained original
        (plain byte equality against the custody root), so partial and
        complete bilateral swaps — with every attacker-writable staged
        digest repaired — fail closed. The detailed variants are pinned
        by the round-3 tests above; this canary keeps the inversion
        itself falsifiable at the original fixture shape."""
        for arm in ("reference", "candidate"):
            self.builder.capture(arm, False)
            self.builder.capture(arm, True)
            self.stage(arm, False)
            self.stage(arm, True)
        self.assertTrue(R.admit_pair_276(self.staged, custody_root=self.source,
                                         case="case-256")["admitted"])
        for tag_a, tag_b in (("reference", "candidate"),
                             ("reference-repeat", "candidate-repeat")):
            a = self.staged / f"units/case-256/{tag_a}/rows/3.f32"
            b = self.staged / f"units/case-256/{tag_b}/rows/3.f32"
            tmp = a.read_bytes()
            a.write_bytes(b.read_bytes())
            b.write_bytes(tmp)
        for tag in ("reference", "candidate", "reference-repeat", "candidate-repeat"):
            self._repair_binding(tag)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
        # The round-2 limitation is CLOSED: this must NOT admit.
        self.assertFalse(verdict["admitted"])


    def _repair_binding(self, tag="candidate", staged=None):
        """Recompute the binding digest map from the unit's CURRENT bytes
        (the attacker-consistent forgery primitive)."""
        import hashlib as _h
        staged_root = Path(staged) if staged is not None else self.staged
        binding_path = staged_root / f"units/case-256/{tag}.json"
        binding = json.loads(binding_path.read_bytes())
        unit = staged_root / "units/case-256" / tag
        binding["files"] = {p.relative_to(unit).as_posix(): _h.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(unit.rglob("*")) if p.is_file()}
        binding_path.write_bytes(canonical(binding))

    # -- round 3: realistic same-host/same-boot incarnations -----------------
    def _capture_at(self, case, arm, repeat, pid, ticks, boot):
        """Capture one genuine run through the production collector path
        with an explicit process incarnation (same boot for the whole case
        when the caller chooses: one host, one boot session)."""
        harness = Harness(arm, pid, boot, ticks)
        tag = arm + ("-repeat" if repeat else "")
        run_root = self.source / "source" / case / tag
        KC.capture_execution_273(case, arm, repeat, harness.receipt(), harness, self.source)
        write_rows(run_root, arm)
        return run_root

    def test_same_host_same_boot_primary_repeat_and_cross_arm_admit(self):
        """Round-3 RED target (maintainer directive, part 1).

        A REALISTIC single-host campaign: every unit of the case runs on
        ONE host inside ONE boot session, so all four captures share the
        boot id and differ ONLY by process incarnation (distinct PIDs and
        start ticks) and by distinct source captures. Distinctness must be
        judged on the incarnation (pid, boot, start ticks) as a whole — a
        shared boot id is not impersonation, it is the normal same-host
        shape. The fixture does NOT manufacture different boot ids per
        capture to satisfy the validator."""
        boot = "b-3f9c1d2e4a5b6c7d-single-host-boot"
        self._capture_at("case-boot", "reference", False, 8101, 1_200_000, boot)
        self._capture_at("case-boot", "reference", True, 8102, 1_240_000, boot)
        self._capture_at("case-boot", "candidate", False, 8144, 1_310_000, boot)
        self._capture_at("case-boot", "candidate", True, 8147, 1_355_000, boot)
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                R.stage_capture_276(self.source, self.staged, "case-boot", arm, repeat)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-boot")
        self.assertEqual(verdict["problems"], [])
        self.assertTrue(verdict["admitted"])

    def test_identical_incarnation_repeat_still_rejected_same_boot(self):
        """Guard: within the same-boot world, a repeat whose process
        incarnation is IDENTICAL to the primary's (same pid, boot, and
        start ticks — a second capture, not a second process) must still
        fail closed."""
        boot = "b-3f9c1d2e4a5b6c7d-single-host-boot"
        self._capture_at("case-boot", "candidate", False, 8201, 2_000_000, boot)
        self._capture_at("case-boot", "candidate", True, 8201, 2_000_000, boot)
        self._capture_at("case-boot", "reference", False, 8301, 2_100_000, boot)
        self._capture_at("case-boot", "reference", True, 8302, 2_140_000, boot)
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                R.stage_capture_276(self.source, self.staged, "case-boot", arm, repeat)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-boot")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("incarn" in p or "impersonat" in p for p in verdict["problems"]))

    def test_source_capture_reuse_still_rejected_same_boot(self):
        """Guard: within the same-boot world, copying the primary's source
        capture directory as the repeat's source must still fail closed."""
        boot = "b-3f9c1d2e4a5b6c7d-single-host-boot"
        import shutil
        self._capture_at("case-boot", "candidate", False, 8401, 3_000_000, boot)
        shutil.copytree(self.source / "source/case-boot/candidate",
                        self.source / "source/case-boot/candidate-repeat")
        self._capture_at("case-boot", "reference", False, 8501, 3_100_000, boot)
        self._capture_at("case-boot", "reference", True, 8502, 3_140_000, boot)
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                R.stage_capture_276(self.source, self.staged, "case-boot", arm, repeat)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-boot")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("incarnation" in p or "source" in p for p in verdict["problems"]))

    # -- round 3: original-to-staged byte binding -----------------------------
    def _stage_full_case(self, case="case-256"):
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                self.builder.capture(arm, repeat, case=case)
                R.stage_capture_276(self.source, self.staged, case, arm, repeat)

    def test_bilateral_staged_row_swap_partial_repaired_digests_rejected(self):
        """Round-3 RED target (maintainer directive, part 2).

        A PARTIAL bilateral swap of staged row bytes across arms — one
        decision swapped consistently in primary and repeat tiers — with
        every attacker-writable staged digest repaired (bindings
        recomputed over the swapped bytes). Per-arm determinism holds and
        no aliasing signature exists, yet admission must FAIL: each
        staged row no longer equals its collector-owned retained
        original."""
        self._stage_full_case()
        self.assertTrue(R.admit_pair_276(self.staged, custody_root=self.source,
                                         case="case-256")["admitted"])
        for tag_a, tag_b in (("reference", "candidate"),
                             ("reference-repeat", "candidate-repeat")):
            a = self.staged / f"units/case-256/{tag_a}/rows/3.f32"
            b = self.staged / f"units/case-256/{tag_b}/rows/3.f32"
            tmp = a.read_bytes()
            a.write_bytes(b.read_bytes())
            b.write_bytes(tmp)
        for tag in ("reference", "candidate", "reference-repeat", "candidate-repeat"):
            self._repair_binding(tag)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("custody" in p or "original" in p for p in verdict["problems"]))

    def test_bilateral_staged_row_swap_complete_repaired_digests_rejected(self):
        """The COMPLETE bilateral permutation — every decision's row bytes
        swapped across arms in both tiers, all staged digests repaired —
        must fail through the same original-to-staged binding."""
        self._stage_full_case()
        self.assertTrue(R.admit_pair_276(self.staged, custody_root=self.source,
                                         case="case-256")["admitted"])
        for d in range(C.DECISIONS):
            for tag_a, tag_b in (("reference", "candidate"),
                                 ("reference-repeat", "candidate-repeat")):
                a = self.staged / f"units/case-256/{tag_a}/rows/{d}.f32"
                b = self.staged / f"units/case-256/{tag_b}/rows/{d}.f32"
                tmp = a.read_bytes()
                a.write_bytes(b.read_bytes())
                b.write_bytes(tmp)
        for tag in ("reference", "candidate", "reference-repeat", "candidate-repeat"):
            self._repair_binding(tag)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("custody" in p or "original" in p for p in verdict["problems"]))

    def test_within_arm_decision_permutation_repaired_digests_rejected(self):
        """A decision-level permutation INSIDE one arm (decisions 1 and 4
        exchanged consistently in primary and repeat, so per-arm
        determinism still holds), staged digests repaired, must fail:
        each decision's row is bound to its own collector-owned
        original."""
        self._stage_full_case()
        self.assertTrue(R.admit_pair_276(self.staged, custody_root=self.source,
                                         case="case-256")["admitted"])
        for tag in ("reference", "reference-repeat", "candidate", "candidate-repeat"):
            one = self.staged / f"units/case-256/{tag}/rows/1.f32"
            four = self.staged / f"units/case-256/{tag}/rows/4.f32"
            tmp = one.read_bytes()
            one.write_bytes(four.read_bytes())
            four.write_bytes(tmp)
            self._repair_binding(tag)
        verdict = R.admit_pair_276(self.staged, custody_root=self.source, case="case-256")
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("custody" in p or "original" in p for p in verdict["problems"]))

    def test_missing_custody_originals_fail_closed(self):
        """Admission binds through the collector-owned retained originals:
        when the accepted source custody is missing, admission fails
        closed even though the staged unit is internally perfect."""
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        import shutil
        shutil.rmtree(self.source / "source/case-256/candidate")
        verdict = R.admit_staged_276(self.staged, custody_root=self.source,
                                     case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("custody" in p for p in verdict["problems"]))

    def test_retained_original_tamper_detected_by_admission(self):
        """The original-to-staged comparison is live in BOTH directions:
        mutating the retained original (staged unit untouched, binding
        still true) must fail admission — staged bytes no longer equal
        the collector-owned original."""
        self.builder.capture("candidate", False)
        self.stage("candidate", False)
        target = self.source / "source/case-256/candidate/rows/2.f32"
        data = bytearray(target.read_bytes())
        data[9] ^= 0x33
        target.write_bytes(bytes(data))
        verdict = R.admit_staged_276(self.staged, custody_root=self.source,
                                     case="case-256", arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])
        self.assertTrue(any("custody" in p or "original" in p for p in verdict["problems"]))

    def test_staging_rejects_source_missing_row_file(self):
        self.builder.capture("candidate", False)
        (self.source / "source/case-256/candidate/rows/3.f32").unlink()
        with self.assertRaisesRegex(R.ReaderError, "row"):
            self.stage("candidate", False)

    def test_fabricated_complete_bundle_via_collector_path_admits_only_through_collector(self):
        """Gap-1 boundary pin (fixture-only): bytes not emitted by the
        collector are refused at staging even when internally consistent,
        because staging authenticates the collector's own retained
        inventory (observation.json probe inventory, written only by the
        collector)."""
        # Authentic capture, then rebuild every file by hand next to it.
        self.builder.capture("candidate", False)
        run = self.source / "source/case-256/candidate"
        files = {p.relative_to(run).as_posix(): p.read_bytes()
                 for p in sorted(run.rglob("*")) if p.is_file()}
        fabricated_root = self.base / "fab-complete/capture"
        fab_run = fabricated_root / "source/case-256/candidate"
        fab_run.mkdir(parents=True)
        for rel, data in files.items():
            (fab_run / rel).parent.mkdir(parents=True, exist_ok=True)
            (fab_run / rel).write_bytes(data)
        # Byte-identical copy of a collector-produced bundle admits (it IS
        # collector-origin); the boundary is the collector, not the copy.
        R.stage_capture_276(fabricated_root, self.base / "fab-complete/staged",
                            "case-256", "candidate", False)
        verdict = R.admit_staged_276(self.base / "fab-complete/staged", custody_root=fabricated_root,
                                     case="case-256", arm="candidate", repeat=False)
        self.assertTrue(verdict["admitted"])
        # But a hand-EDITED inventory (the only non-self-authenticating
        # surface) is refused: its digest no longer matches observation.json.
        staged2 = self.base / "fab-complete/staged2"
        R.stage_capture_276(fabricated_root, staged2, "case-256", "candidate", False)
        obs_path = staged2 / "units/case-256/candidate/observation.json"
        obs = json.loads(obs_path.read_bytes())
        obs["probe_inventory"]["raw/extra-entry.bin"] = {
            "sha256": hashlib.sha256(b"x").hexdigest(), "bytes": 1}
        obs_path.write_bytes(canonical(obs))
        self._repair_root_binding(staged2, "candidate")
        verdict = R.admit_staged_276(staged2, custody_root=fabricated_root, case="case-256",
                                     arm="candidate", repeat=False)
        self.assertFalse(verdict["admitted"])

    def _repair_root_binding(self, staged_root, tag):
        import hashlib as _h
        binding_path = Path(staged_root) / f"units/case-256/{tag}.json"
        binding = json.loads(binding_path.read_bytes())
        unit = Path(staged_root) / "units/case-256" / tag
        binding["files"] = {p.relative_to(unit).as_posix(): _h.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(unit.rglob("*")) if p.is_file()}
        binding_path.write_bytes(canonical(binding))


if __name__ == "__main__":
    unittest.main()
