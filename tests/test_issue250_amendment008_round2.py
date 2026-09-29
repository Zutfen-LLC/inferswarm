#!/usr/bin/env python3
"""Issue #250 — METHODOLOGY-AMENDMENT-008 correction round 2 (RED first).

Adversarial regressions for the corrected Arm-A bridge law at reviewed
head 35f427bcc13e2ee56a2f566848018b6e3a08016d. Reviewed-head defects:

  D1  the launch gate opened the bridge for ANY historical-gate refusal
      whose message merely began with the historical reason prefix, and
      never revalidated an exact authenticated predecessor DECISION —
      absent, invalid, or wrong-state AMD V0 evidence could open Arm A
      whenever the bridge JSON and a presentable V0n tree existed;
  D2  the V0 half of the bridge was never revalidated from retained
      bytes (no frozen retained-population verifier, no three-unit
      repeat law, no accepted-contrast revalidation);
  D3  the V0n half used a bespoke weaker population checker instead of
      the frozen retained-population verifier + frozen reducer, so
      receipts with altered backend, identity, residency, dispatch or
      other frozen custody fields could open Arm A;
  D4  bridge-path provenance was never persisted in Arm-A receipts and
      the terminal reducer never consumed a verified bridge-path Arm-A
      population (the ARM_A_STOPS_LADDER branch was dead code).

Committed RED at the reviewed head: every [RED] test FAILS there and
must pass after the correction; [PIN] tests pin retained correct
behavior and pass at both heads.

Fixture law: the accepted 993280-byte rows cannot be synthesized on a
CPU host, so each test patches the frozen bridge row/freeze constants
to its synthetic population's REAL digests (the established
ACCEPTED_248_MANIFEST_SELF_DIGEST fixture precedent) and installs a
resigned bridge record naming them; every frozen verifier then runs
UNMODIFIED over real bytes, and any row/receipt mutation changes its
real digest and rejects. The accepted dispatch-authority payloads
reconstruct byte-exactly from the retained comment fields (no digest
patching): V0 99cb573c…, V0n 4aa0aa0b….

Cross-host evidence-path law (corrected): the accepted predecessor
roots (AMD V0 on inferswarm05, V0n on inferswarm01) are mounted
READ-ONLY under the campaign evidence root as predecessor-v0/ and
predecessor-v0n/ (self-contained copies of the append-only roots;
originals immutable); the bridge authenticates them through the frozen
retained-population verifiers. The fixture ALSO mirrors the V0n tree
at the evidence-root top level so the REVIEWED-head code path (the
bespoke checker reads <root>/d250-arm-v0n-nvidia) genuinely engages:
at the reviewed head the gate OPENS where it must not — that opening
is the defect under test.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import issue250_diagnostic as D0  # noqa: E402
import issue250_physical as P0  # noqa: E402
import issue250_terminal as T0  # noqa: E402
from test_issue248_diagnostic import census_observation  # noqa: E402

# ONE singleton set per process (same law as the amendment008 suite).
D = P0.D

V0N_HEAD = "aa059713d83204a4dd8be2ea903aa31bddfdf3b8"
V0_HEAD = "c5cc132762c51a3352014f36553eff6d0d26b112"

BRIDGE_REL = ("docs/investigations/"
              "qwen38-flash-next-r8-i3b-ref-runtime-boundary/"
              "arm-a-reachability-bridge.json")

V0N_RUNTIME = {"kernel": "6.12.105-deb13", "vulkan_instance": "1.4.309"}


def canonical_bridge_record() -> dict:
    return json.loads((REPO / BRIDGE_REL).read_bytes())


def resign(record: dict) -> dict:
    record = copy.deepcopy(record)
    record.pop("canonical_digest_sha256", None)
    record["canonical_digest_sha256"] = P0._v0_digest(record)
    return record


def accepted_v0_authority() -> dict:
    """The completed AMD V0 dispatch payload, byte-exact (99cb573c…)."""
    return {
        "comment_id": 5868617068,
        "issue_url": ("https://api.github.com/repos/Zutfen-LLC/"
                      "inferswarm/issues/251"),
        "author_association": "MEMBER",
        "created_at": "2026-09-28T11:05:20Z",
        "body": "\n".join([
            "R8I3B PHYSICAL DISPATCH #250",
            f"head={V0_HEAD}",
            "diagnostic-namespace=d250-arm-v0-amd",
            "arm=V0-amd-vulkan-concordance",
        ]),
        "head_sha": V0_HEAD,
        "namespace": "d250-arm-v0-amd",
        "arm": "V0-amd-vulkan-concordance",
        "open_pr": True,
        "issue_open": True,
    }


def accepted_v0n_authority() -> dict:
    """The completed V0n dispatch payload, byte-exact (4aa0aa0b…)."""
    return {
        "comment_id": 5880409202,
        "issue_url": ("https://api.github.com/repos/Zutfen-LLC/"
                      "inferswarm/issues/251"),
        "author_association": "MEMBER",
        "created_at": "2026-09-28T23:13:06Z",
        "body": "\n".join([
            "R8I3B PHYSICAL DISPATCH #250",
            f"head={V0N_HEAD}",
            "diagnostic-namespace=d250-arm-v0n-nvidia",
            "arm=V0n-nvidia-vulkan-current",
        ]) + "\n",
        "head_sha": V0N_HEAD,
        "namespace": "d250-arm-v0n-nvidia",
        "arm": "V0n-nvidia-vulkan-current",
        "open_pr": True,
        "issue_open": True,
    }


def row_with_sha(seed: bytes) -> bytes:
    return (hashlib.sha256(seed).digest() * (D.ROW_BYTES // 32 + 1)
            )[:D.ROW_BYTES]


def production_vram_evidence(uuid: str, bdf: str, before_mib: str,
                             after_mib: str) -> dict:
    return {
        "before": {"gpu_uuid": uuid, "bdf": bdf,
                   "population": [[uuid, bdf, before_mib]],
                   "selected_row": [uuid, bdf, before_mib]},
        "after": {"gpu_uuid": uuid, "bdf": bdf,
                  "population": [[uuid, bdf, after_mib]],
                  "selected_row": [uuid, bdf, after_mib]},
    }


def synthetic_subject_identity():
    return P0.v0n_identity_from_observation(
        census_observation("B"), runtime=V0N_RUNTIME)


def synthetic_nvidia_device(**overrides):
    device = {"index": 0, "vendor_id": "0x10de", "device_id": "0x2504",
              "name": "NVIDIA GeForce RTX 3060",
              "driver_id": "DRIVER_ID_NVIDIA_PROPRIETARY",
              "driver_info": "610.57.04", "driver_version": "610.57.4.0",
              "api_version": "1.4.341",
              "vulkan_indices": [0], "enumeration_sha256": "a" * 64,
              "icd_sha256": "b" * 64,
              "runtime_identity": {"kernel": "6.12.105-deb13",
                                   "vulkan_instance": "1.4.309",
                                   "devices": {}},
              "host": "inferswarm01"}
    device["subject_identity"] = synthetic_subject_identity()
    device["subject_identity_sha256"] = P0._v0n_identity_digest(
        device["subject_identity"])
    device.update(overrides)
    if "subject_identity" in overrides:
        device["subject_identity_sha256"] = P0._v0n_identity_digest(
            device["subject_identity"])
    return device


# ---------------------------------------------------------------------------
# Synthetic accepted predecessor evidence (production shapes; REAL
# digests; frozen verifiers run unmodified; bridge constants patched to
# the synthetic digests and restored on cleanup).
# ---------------------------------------------------------------------------


class PredecessorMounts:
    """Installs the accepted predecessor evidence under an evidence
    root:

      predecessor-v0/   — read-only mount of the accepted AMD V0 root
                          (three repeat-stable units + freeze + binding
                          + preflight, self-contained);
      predecessor-v0n/  — read-only mount of the accepted V0n root
                          (two mismatched units + freeze);
      <root>/d250-arm-v0n-nvidia + <root>/v0n-screen-freeze.json — a
                          TOP-LEVEL mirror of the V0n mount engaging the
                          REVIEWED-head bespoke checker (whose layout
                          expectation is the evidence-root top level).

    Bridge constants are patched to the synthetic population's real
    digests (restored on cleanup); `bridge_record()` returns a
    resigned canonical record naming them.
    """

    def __init__(self, test: unittest.TestCase, root: Path, *,
                 v0_units=3, v0n_units=2, mirror_v0n=True):
        self.root = Path(root)
        self.test = test
        self.mirror_v0n = mirror_v0n
        self.saved = {
            "stable": D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256,
            "rows": D.ARM_A_BRIDGE_V0N_ROW_SHA256,
            "freeze": D.ARM_A_BRIDGE_V0N_FREEZE_SHA256,
            "amd_current": D.V0N_AMD_CURRENT_ROW0_SHA256,
        }

        def restore():
            D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256 = self.saved["stable"]
            D.ARM_A_BRIDGE_V0N_ROW_SHA256 = self.saved["rows"]
            D.ARM_A_BRIDGE_V0N_FREEZE_SHA256 = self.saved["freeze"]
            D.V0N_AMD_CURRENT_ROW0_SHA256 = self.saved["amd_current"]
        test.addCleanup(restore)
        self._build_v0(v0_units)
        self._build_v0n(v0n_units)

    # ----- V0 (AMD) mount ---------------------------------------------

    def _build_v0(self, units):
        head = V0_HEAD
        authority = accepted_v0_authority()
        mount = self.root / "predecessor-v0"
        # Real binary/lib directory (the frozen binding validator checks
        # binary_lib_dir exists and is binary_path's parent).
        bin_dir = self.root / "v0-bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        binary_path = bin_dir / "llama-server"
        binary_path.write_bytes(b"fake-accepted-comparator")
        cards = {"0000:07:00.0": "card1", "0000:0b:00.0": "card2"}
        device_identity = {
            "vendor_id": "0x1002", "device_id": "0x6864",
            "name": "AMD Radeon Pro V340 (RADV VEGA10)",
            "driver_id": "DRIVER_ID_MESA_RADV",
            "driver_info": "Mesa 25.0.7-2+deb13u1",
            "driver_version": "25.0.7", "api_version": "1.4.305",
        }
        live = {"index": 0, "vendor_id": "0x1002", "device_id": "0x6864",
                "name": "AMD V340L synthetic", "vulkan_indices": [0, 1],
                "enumeration_sha256": "a" * 64, "icd_sha256": "b" * 64,
                "runtime_identity": {
                    "kernel": "6.12.107-deb13u3-x",
                    "vulkan_instance": "1.4.309",
                    "devices": {0: copy.deepcopy(device_identity),
                                1: copy.deepcopy(device_identity)}},
                "drm_cards": cards, "binary_lib_dir": str(bin_dir)}
        self.v0_binary = binary_path
        self.v0_lib_dir = str(bin_dir)
        binding = {"schema": P0.V0_BINDING_SCHEMA,
                   "expected_pr_head": head, "host": "inferswarm05",
                   "producer": P0.V0_BINDING_PRODUCER,
                   "source_pin": P0.V0_SOURCE_PIN,
                   "binary_sha256": P0.V0_COMPARATOR_SHA,
                   "binary_path": str(binary_path),
                   "icd": P0.V0_RADV_ICD, "cuda_visible_devices": "-1",
                   "binary_lib_dir": str(bin_dir),
                   "enumeration_sha256": live["enumeration_sha256"],
                   "icd_sha256": live["icd_sha256"],
                   "runtime_identity": json.loads(json.dumps(
                       live["runtime_identity"])),
                   "drm_cards": cards, "mapping": {}}
        for idx, selected in ((0, "0000:07:00.0"), (1, "0000:0b:00.0")):
            excluded = next(b for b in cards if b != selected)
            binding["mapping"][str(idx)] = {
                "selected_bdf": selected, "excluded_bdf": excluded,
                "selected_card": cards[selected],
                "excluded_card": cards[excluded],
                "vram_before": {selected: 0, excluded: 0},
                "vram_after": {selected: 512 * 1024 * 1024, excluded: 0}}
        probe_dir = mount / "v0-selector-preflight"
        probe_dir.mkdir(parents=True)
        binding["preflight_probe_sha256"] = {}
        binding["dispatch_sha256"] = D.authority_digest(authority)
        for idx in (0, 1):
            entry = binding["mapping"][str(idx)]
            probe = {"index": idx, "vram_before": entry["vram_before"],
                     "vram_after": entry["vram_after"],
                     "process_attribution": {
                         "server_exe_sha256": P0.V0_COMPARATOR_SHA,
                         "server_argv": P0.v0_server_argv(
                             self.v0_binary,
                             Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                         "server_env": {
                             "VK_ICD_FILENAMES": P0.V0_RADV_ICD,
                             "GGML_VK_VISIBLE_DEVICES": str(idx),
                             "CUDA_VISIBLE_DEVICES": "-1",
                             "LD_LIBRARY_PATH": self.v0_lib_dir}}}
            path = probe_dir / f"index-{idx}.json"
            path.write_text(json.dumps(probe))
            binding["preflight_probe_sha256"][str(idx)] = \
                D.file_sha256(path)
        binding["canonical_digest_sha256"] = P0._v0_digest(binding)
        (mount / "v0-selector-binding.json").write_text(json.dumps(binding))
        freeze_rule_index = min(
            (0, 1),
            key=lambda i: str(binding["mapping"][str(i)]["selected_bdf"]))
        freeze_entry = binding["mapping"][str(freeze_rule_index)]
        freeze = {
            "schema": P0.V0_FREEZE_SCHEMA, "producer": P0.V0_FREEZE_PRODUCER,
            "freeze_rule": P0.V0_FREEZE_RULE, "expected_pr_head": head,
            "v0_screen_vulkan_index": freeze_rule_index,
            "v0_screen_selected_bdf": freeze_entry["selected_bdf"],
            "v0_screen_excluded_bdf": freeze_entry["excluded_bdf"],
            "selected_card": freeze_entry["selected_card"],
            "excluded_card": freeze_entry["excluded_card"],
            "source_pin": P0.V0_SOURCE_PIN,
            "binary_sha256": P0.V0_COMPARATOR_SHA,
            "icd": P0.V0_RADV_ICD, "cuda_visible_devices": "-1",
            "selector_binding_digest": binding["canonical_digest_sha256"],
            "dispatch_sha256": D.authority_digest(authority),
            "namespace": D.V0_NAMESPACE, "arm": D.V0_ARM,
        }
        freeze["canonical_digest_sha256"] = P0._v0_freeze_digest(freeze)
        (mount / P0.V0_FREEZE_NAME).write_text(json.dumps(freeze))
        base = mount / D.V0_NAMESPACE
        base.mkdir(parents=True)
        self.v0_rows = []
        stable_row = row_with_sha(b"synthetic-v0-stable")
        for index, tag in enumerate(D.V0_UNIT_TAGS[:units], 1):
            unit = base / tag
            unit.mkdir()
            (unit / "obs.row0.f32").write_bytes(stable_row)
            digest = hashlib.sha256(stable_row).hexdigest()
            self.v0_rows.append(digest)
            receipt = {
                "schema": D.V0_SCHEMA, "tag": tag,
                "namespace": D.V0_NAMESPACE, "arm": D.V0_ARM,
                "head_sha": head,
                "evidence_generation": P0.EVIDENCE_GENERATION,
                "authority_sha256": D.authority_digest(authority),
                "placement_verified": True,
                "amd_device": live, "v0_selector_binding": binding,
                "selected_bdf": "0000:07:00.0",
                "excluded_bdf": "0000:0b:00.0",
                "vram_before": {"0000:07:00.0": 0, "0000:0b:00.0": 0},
                "vram_after": {"0000:07:00.0": 512 * 1024 * 1024,
                               "0000:0b:00.0": 0},
                "placement_source_law": {
                    "source_pin": P0.V0_SOURCE_PIN, "ngl": 1,
                    "embedding": "CPU", "output_projection": "Vulkan"},
                "decision0_row_sha256": digest,
                "row_bytes": D.ROW_BYTES, "case_id": D.CONTRAST_CASE,
                "ngl": 1, "backend": "Vulkan",
                "embedding_placement": "CPU",
                "output_projection_placement": "Vulkan",
                "model_dir": D.MODEL_DIR,
                "model_launch_member": str(
                    Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                "model_member_sha256": D.MODEL_MEMBER_SHA256[
                    D.MODEL_MEMBER_1],
                "prompt_sha256": D.sha256_bytes(json.dumps(
                    [1] * 3077, separators=(",", ":")).encode()),
                "prompt_token_ids": [1] * 3077,
                "prompt_text_sha256": "t" * 64, "prompt_len": 3077,
                "request_contract": D.REQUEST_CONTRACT,
                "request_contract_sha256": D.canonical_request_digest(
                    D.REQUEST_CONTRACT),
                "fresh_process": True, "server_pid": 51000 + index,
                "binary_sha256": P0.V0_COMPARATOR_SHA,
                "server_argv": P0.v0_server_argv(
                    self.v0_binary,
                    Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                "server_env": {"VK_ICD_FILENAMES": P0.V0_RADV_ICD,
                               "GGML_VK_VISIBLE_DEVICES": "0",
                               "CUDA_VISIBLE_DEVICES": "-1",
                               "LD_LIBRARY_PATH": self.v0_lib_dir},
            }
            receipt["process_attribution"] = {
                "server_exe_sha256": P0.V0_COMPARATOR_SHA,
                "server_pid": receipt["server_pid"],
                "server_argv": receipt["server_argv"],
                "server_env": receipt["server_env"]}
            (unit / "unit.json").write_text(json.dumps(receipt))
        self.v0_stable = self.v0_rows[0]
        D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256 = self.v0_stable
        # The V0n frozen reducer compares against the AMD current-
        # window stable row (same accepted population).
        D.V0N_AMD_CURRENT_ROW0_SHA256 = self.v0_stable

    # ----- V0n (NVIDIA) mount (+ reviewed-head top-level mirror) ------

    def _build_v0n(self, units):
        device = synthetic_nvidia_device()
        identity = synthetic_subject_identity()
        self.identity_digest = P0._v0n_identity_digest(identity)
        freeze = {
            "schema": P0.V0N_FREEZE_SCHEMA,
            "producer": P0.V0N_FREEZE_PRODUCER,
            "expected_pr_head": V0N_HEAD,
            "namespace": D.V0N_NAMESPACE, "arm": D.V0N_ARM,
            "identity_arm": P0.V0N_IDENTITY_ARM,
            "identity_authority": "scripts/issue248_identity.py",
            "subject_identity": identity,
            "subject_identity_sha256": self.identity_digest,
            "gpu_uuid": identity["gpu_uuid"], "bdf": identity["bdf"],
            "icd": P0.V0N_NVIDIA_ICD,
            "vulkan_selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                                "VK_ICD_FILENAMES": P0.V0N_NVIDIA_ICD},
            "cuda_law": {"CUDA_VISIBLE_DEVICES": "-1",
                         "link_family_cuda_exclusion": True},
            "source_pin": P0.V0N_SOURCE_PIN,
            "llama_source_pin": P0.V0N_SOURCE_PIN,
            "binary_sha256": P0.V0N_COMPARATOR_SHA,
            "comparator_sha256": P0.V0N_COMPARATOR_SHA,
            "observer_libraries": dict(P0.V0_OBSERVER_LIBS),
            "dispatch_sha256": D.authority_digest(accepted_v0n_authority()),
        }
        freeze["canonical_digest_sha256"] = P0._v0n_freeze_digest(freeze)
        self.freeze_digest = freeze["canonical_digest_sha256"]
        mount = self.root / "predecessor-v0n"
        mount.mkdir(parents=True)
        (mount / P0.V0N_FREEZE_NAME).write_text(json.dumps(freeze))
        base = mount / D.V0N_NAMESPACE
        base.mkdir()
        self.v0n_rows = []
        for i, tag in enumerate(D.V0N_UNIT_TAGS[:units]):
            unit = base / tag
            unit.mkdir()
            row = row_with_sha(f"synthetic-v0n-{i}".encode())
            (unit / "obs.row0.f32").write_bytes(row)
            digest = hashlib.sha256(row).hexdigest()
            self.v0n_rows.append(digest)
            (unit / "unit.json").write_text(json.dumps(
                self._v0n_receipt(tag, i, digest, identity, freeze,
                                  device)))
        D.ARM_A_BRIDGE_V0N_ROW_SHA256 = tuple(self.v0n_rows)
        D.ARM_A_BRIDGE_V0N_FREEZE_SHA256 = self.freeze_digest
        if self.mirror_v0n:
            # Top-level mirror engaging the REVIEWED-head checker.
            mirror = self.root / D.V0N_NAMESPACE
            if not mirror.exists():
                shutil.copytree(base, mirror)
            shutil.copy(mount / P0.V0N_FREEZE_NAME,
                        self.root / P0.V0N_FREEZE_NAME)

    def _v0n_receipt(self, tag, i, digest, identity, freeze, device):
        argv = P0.v0n_server_argv(
            self.v0_binary,
            Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)
        env = {"VK_ICD_FILENAMES": P0.V0N_NVIDIA_ICD,
               "GGML_VK_VISIBLE_DEVICES": "0",
               "CUDA_VISIBLE_DEVICES": "-1",
               "LD_LIBRARY_PATH": self.v0_lib_dir}
        return {
            "schema": D.V0N_SCHEMA, "tag": tag,
            "namespace": D.V0N_NAMESPACE, "arm": D.V0N_ARM,
            "head_sha": V0N_HEAD,
            "evidence_generation": P0.EVIDENCE_GENERATION,
            "decision0_row_sha256": digest,
            "row_bytes": D.ROW_BYTES,
            "authority_sha256": D.authority_digest(
                accepted_v0n_authority()),
            "v0n_freeze_digest": self.freeze_digest,
            "v0n_subject_identity": dict(identity),
            "v0n_subject_identity_sha256": self.identity_digest,
            "prelaunch_identity_sha256": self.identity_digest,
            "postexec_identity_sha256": self.identity_digest,
            "gpu_uuid": identity["gpu_uuid"], "bdf": identity["bdf"],
            "vulkan_selector": dict(freeze["vulkan_selector"]),
            "placement_verified": True,
            "vram_before": 0,
            "vram_after": 512 * 1024 * 1024,
            "vram_evidence": production_vram_evidence(
                identity["gpu_uuid"], identity["bdf"], "0", "512"),
            "nvidia_device": copy.deepcopy(device),
            "case_id": D.CONTRAST_CASE, "ngl": 1,
            "backend": "Vulkan", "cuda_participation": False,
            "embedding_placement": "CPU",
            "output_projection_placement": "Vulkan",
            "placement_source_law": {
                "source_pin": P0.V0N_SOURCE_PIN, "ngl": 1,
                "embedding": "CPU", "output_projection": "Vulkan"},
            "model_dir": D.MODEL_DIR,
            "model_launch_member": str(
                Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
            "model_member_sha256": D.MODEL_MEMBER_SHA256[
                D.MODEL_MEMBER_1],
            "prompt_sha256": D.sha256_bytes(json.dumps(
                [1] * 3077, separators=(",", ":")).encode()),
            "prompt_token_ids": [1] * 3077,
            "prompt_text_sha256": "t" * 64, "prompt_len": 3077,
            "request_contract": D.REQUEST_CONTRACT,
            "request_contract_sha256": D.canonical_request_digest(
                D.REQUEST_CONTRACT),
            "fresh_process": True, "server_pid": 1275670 + i,
            "binary_sha256": P0.V0N_COMPARATOR_SHA,
            "server_argv": argv, "server_env": env,
            "process_attribution": {
                "server_exe_sha256": P0.V0N_COMPARATOR_SHA,
                "server_pid": 1275670 + i, "server_argv": argv,
                "server_env": env},
        }

    # ----- bridge record consistent with the synthetic population ----

    def bridge_record(self) -> dict:
        record = copy.deepcopy(canonical_bridge_record())
        record["v0"]["stable_row_sha256"] = self.v0_stable
        record["v0n"]["row_sha256"] = list(self.v0n_rows)
        record["v0n"]["freeze_sha256"] = self.freeze_digest
        return resign(record)

    # ----- mutation helpers (mount + mirror stay consistent) ---------

    def mutate_v0n_receipt(self, tag_index, **mutations):
        for base in self.v0n_bases():
            path = base / D.V0N_UNIT_TAGS[tag_index] / "unit.json"
            doc = json.loads(path.read_bytes())
            doc.update(mutations)
            path.write_text(json.dumps(doc))

    def v0n_bases(self):
        bases = [self.root / "predecessor-v0n" / D.V0N_NAMESPACE]
        if (self.root / D.V0N_NAMESPACE).is_dir():
            bases.append(self.root / D.V0N_NAMESPACE)
        return bases


def write_bridge(root: Path, record: dict) -> None:
    (root / D.ARM_A_BRIDGE_NAME).write_text(json.dumps(record))


class BridgeGateTestCase(unittest.TestCase):
    """Common setUp: evidence root + predecessor mounts + bridge."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mounts = PredecessorMounts(self, self.root)
        write_bridge(self.root, self.mounts.bridge_record())

    def gate(self, arm="A-vulkan-necessity", head=V0N_HEAD):
        return P0._require_sequential_reachability(
            self.root, self.root, arm, head, {}, None,
            "https://api.github.com")


# ---------------------------------------------------------------------------
# D1 — exact authenticated predecessor decision (launch gate)
# ---------------------------------------------------------------------------


class ExactPredecessorDecisionTests(BridgeGateTestCase):

    def test_v0_evidence_absent_does_not_open_arm_a(self):
        # [RED] No AMD V0 predecessor evidence at all (mount removed;
        # the reviewed code never read it): the bridge JSON + a valid
        # V0n tree must NOT open Arm A.
        shutil.rmtree(self.root / "predecessor-v0")
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0_wrong_state_does_not_open_arm_a(self):
        # [RED] A V0 population whose frozen reducer decision is
        # CONCORDANCE_STOP (stable row matching a retained #248 NVIDIA
        # row) is not the accepted decision and must not open Arm A.
        saved = D.V0_NVIDIA_ROW0_SHA256
        D.V0_NVIDIA_ROW0_SHA256 = (self.mounts.v0_stable, saved[1])
        self.addCleanup(lambda: setattr(
            D, "V0_NVIDIA_ROW0_SHA256", saved))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0_variable_state_does_not_open_arm_a(self):
        # [RED] A V0 population with a mismatched first pair (reducer
        # decision AMD_VARIABLE, not the accepted stable stop) must not
        # open Arm A through the bridge.
        unit = (self.root / "predecessor-v0" / D.V0_NAMESPACE /
                D.V0_UNIT_TAGS[1])
        raw = (unit / "obs.row0.f32").read_bytes()
        (unit / "obs.row0.f32").write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0_two_unit_prefix_does_not_open_arm_a(self):
        # [RED] The accepted V0 result has THREE repeat-stable units; a
        # two-unit prefix is a different decision (third-required) and
        # must not open Arm A.
        shutil.rmtree(self.root / "predecessor-v0" / D.V0_NAMESPACE /
                      D.V0_UNIT_TAGS[2])
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0_receipt_authority_drift_does_not_open_arm_a(self):
        # [RED] V0 receipts must bind the accepted dispatch authority
        # (99cb573c…); drift must not open Arm A.
        path = (self.root / "predecessor-v0" / D.V0_NAMESPACE /
                D.V0_UNIT_TAGS[0] / "unit.json")
        doc = json.loads(path.read_bytes())
        doc["authority_sha256"] = "f" * 64
        path.write_text(json.dumps(doc))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0_row_drift_does_not_open_arm_a(self):
        # [RED] Altered V0 row bytes must not open Arm A.
        path = (self.root / "predecessor-v0" / D.V0_NAMESPACE /
                D.V0_UNIT_TAGS[2] / "obs.row0.f32")
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0n_evidence_absent_does_not_open_arm_a(self):
        # [PIN] No V0n predecessor evidence: rejected at both heads.
        shutil.rmtree(self.root / "predecessor-v0n")
        shutil.rmtree(self.root / D.V0N_NAMESPACE)
        (self.root / P0.V0N_FREEZE_NAME).unlink()
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_accepted_combination_opens_arm_a(self):
        # [PIN] The exact accepted combination — three repeat-stable
        # V0 units under the accepted dispatch, two mismatched novel
        # V0n units under the accepted dispatch, canonical bridge —
        # must open Arm A (pins the positive path against an
        # over-tight correction).
        self.gate()  # must not raise

    def test_bridge_never_opens_later_arms(self):
        # [PIN] Later arms keep the historical ladder verbatim.
        for arm in ("B-process-init", "C-cpu-threads",
                    "C1-reduced-parallelism", "C2-serial",
                    "D-context-transition"):
            with self.subTest(arm=arm):
                with self.assertRaises(P0.PhysicalDiagnosticError):
                    self.gate(arm=arm)


# ---------------------------------------------------------------------------
# D2/D3 — frozen-verifier V0n custody (bridge record + valid V0 not enough)
# ---------------------------------------------------------------------------


class V0nFrozenCustodyTests(BridgeGateTestCase):
    """V0n receipts with altered backend, identity, residency, dispatch
    or other frozen custody fields must not open Arm A even with the
    bridge record and a fully valid V0 mount present."""

    def test_backend_drift_rejects(self):
        # [RED] The reviewed bespoke checker never read `backend`.
        self.mounts.mutate_v0n_receipt(0, backend="CUDA")
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_cuda_participation_drift_rejects(self):
        # [RED]
        self.mounts.mutate_v0n_receipt(0, cuda_participation=True)
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_identity_drift_rejects(self):
        # [RED] pre/post identity-digest drift was never checked.
        self.mounts.mutate_v0n_receipt(
            1, prelaunch_identity_sha256="e" * 64,
            postexec_identity_sha256="e" * 64)
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_subject_identity_drift_rejects(self):
        # [PIN] identity content drift (receipt vs freeze) rejected at
        # both heads (the reviewed checker did compare these).
        path = (self.root / "predecessor-v0n" / D.V0N_NAMESPACE /
                D.V0N_UNIT_TAGS[1] / "unit.json")
        doc = json.loads(path.read_bytes())
        doc["v0n_subject_identity"]["gpu_uuid"] = \
            "GPU-00000000-0000-0000-0000-000000000000"
        path.write_text(json.dumps(doc))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_residency_evidence_drift_rejects(self):
        # [RED] The reviewed checker never read vram_evidence.
        self.mounts.mutate_v0n_receipt(
            0, vram_evidence={"before": {"population": []},
                              "after": {"population": []}})
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_residency_delta_drift_rejects(self):
        # [RED]
        self.mounts.mutate_v0n_receipt(0, vram_after=1024)
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_dispatch_binding_drift_rejects(self):
        # [RED] receipt dispatch binding was never checked.
        self.mounts.mutate_v0n_receipt(0, authority_sha256="f" * 64)
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_server_env_drift_rejects(self):
        # [RED]
        for base in self.mounts.v0n_bases():
            path = base / D.V0N_UNIT_TAGS[0] / "unit.json"
            doc = json.loads(path.read_bytes())
            doc["server_env"]["CUDA_VISIBLE_DEVICES"] = "0"
            doc["process_attribution"]["server_env"] = doc["server_env"]
            path.write_text(json.dumps(doc))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_server_argv_drift_rejects(self):
        # [RED]
        for base in self.mounts.v0n_bases():
            path = base / D.V0N_UNIT_TAGS[0] / "unit.json"
            doc = json.loads(path.read_bytes())
            doc["server_argv"] = list(doc["server_argv"]) + ["--taint"]
            doc["process_attribution"]["server_argv"] = doc["server_argv"]
            path.write_text(json.dumps(doc))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_generation_drift_rejects(self):
        # [RED]
        self.mounts.mutate_v0n_receipt(
            0, evidence_generation="gen-1-v1-timeout-defect")
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_duplicate_pid_rejects(self):
        # [RED]
        self.mounts.mutate_v0n_receipt(1, server_pid=1275670)
        path = (self.root / "predecessor-v0n" / D.V0N_NAMESPACE /
                D.V0N_UNIT_TAGS[1] / "unit.json")
        doc = json.loads(path.read_bytes())
        doc["process_attribution"]["server_pid"] = 1275670
        path.write_text(json.dumps(doc))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_third_unit_present_rejects(self):
        # [PIN] rejected at both heads.
        for base in self.mounts.v0n_bases():
            extra = base / D.V0N_UNIT_TAGS[2]
            extra.mkdir(exist_ok=True)
            (extra / "unit.json").write_text("{}")
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_missing_receipt_rejects(self):
        # [PIN]
        for base in self.mounts.v0n_bases():
            (base / D.V0N_UNIT_TAGS[1] / "unit.json").unlink()
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_freeze_dispatch_binding_drift_rejects(self):
        # [PIN] a re-signed freeze naming another dispatch must reject.
        for freeze_path in (
                self.root / "predecessor-v0n" / P0.V0N_FREEZE_NAME,
                self.root / P0.V0N_FREEZE_NAME):
            doc = json.loads(freeze_path.read_bytes())
            doc["dispatch_sha256"] = "e" * 64
            doc["canonical_digest_sha256"] = P0._v0n_freeze_digest(doc)
            freeze_path.write_text(json.dumps(doc))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_row_drift_rejects(self):
        # [PIN] altered V0n row bytes must reject.
        for base in self.mounts.v0n_bases():
            path = base / D.V0N_UNIT_TAGS[0] / "obs.row0.f32"
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_uniform_v0n_pair_rejects(self):
        # [RED] an identical (never-varied) V0n first pair is not the
        # accepted VARIABLE_STOP decision: with the constants pinned to
        # the uniform pair the record binding still holds, and the
        # corrected law must reject it through the frozen reducer
        # (IDENTICAL_PAIR_THIRD_REQUIRED ≠ the accepted decision).
        first = (self.root / "predecessor-v0n" / D.V0N_NAMESPACE /
                 D.V0N_UNIT_TAGS[0] / "obs.row0.f32").read_bytes()
        uniform = hashlib.sha256(first).hexdigest()
        for base in self.mounts.v0n_bases():
            (base / D.V0N_UNIT_TAGS[1] / "obs.row0.f32").write_bytes(first)
            path = base / D.V0N_UNIT_TAGS[1] / "unit.json"
            doc = json.loads(path.read_bytes())
            doc["decision0_row_sha256"] = uniform
            path.write_text(json.dumps(doc))
        D.ARM_A_BRIDGE_V0N_ROW_SHA256 = (uniform, uniform)
        record = copy.deepcopy(canonical_bridge_record())
        record["v0n"]["row_sha256"] = [uniform, uniform]
        record["v0n"]["freeze_sha256"] = self.mounts.freeze_digest
        record["v0"]["stable_row_sha256"] = self.mounts.v0_stable
        write_bridge(self.root, resign(record))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_row_equals_retained_nvidia_rejects(self):
        # [RED] accepted contrast law: both V0n rows must be NOVEL
        # (differ from the AMD stable row AND both retained #248
        # rows); a row equal to a retained #248 row is not the
        # accepted population even though the pair still mismatches.
        saved = D.V0_NVIDIA_ROW0_SHA256
        D.V0_NVIDIA_ROW0_SHA256 = (self.mounts.v0n_rows[0], saved[1])
        self.addCleanup(lambda: setattr(
            D, "V0_NVIDIA_ROW0_SHA256", saved))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_row_equals_amd_stable_rejects(self):
        # [RED] a V0n row equal to the AMD stable row is not the
        # accepted novel population.
        saved = D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256
        D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256 = self.mounts.v0n_rows[0]
        self.addCleanup(lambda: setattr(
            D, "ARM_A_BRIDGE_V0_STABLE_ROW_SHA256", saved))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()


# ---------------------------------------------------------------------------
# Accepted-authority reconstruction pins
# ---------------------------------------------------------------------------


class BridgeRecordBindingPins(unittest.TestCase):

    def test_committed_canonical_record_binds_real_accepted_digests(self):
        # [PIN] The committed record binds the REAL accepted digests
        # (constants unpatched here) and its canonical digest
        # authenticates.
        record = canonical_bridge_record()
        self.assertEqual(record["canonical_digest_sha256"],
                         P0._v0_digest(record))
        self.assertEqual(record["v0"]["stable_row_sha256"],
                         D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256)
        self.assertEqual(tuple(record["v0n"]["row_sha256"]),
                         D.ARM_A_BRIDGE_V0N_ROW_SHA256)
        self.assertEqual(record["v0n"]["freeze_sha256"],
                         D.ARM_A_BRIDGE_V0N_FREEZE_SHA256)

    def test_accepted_dispatch_payloads_reconstruct_byte_exactly(self):
        # [PIN] The accepted dispatch-authority digests reconstruct
        # byte-exactly from the retained comment fields — the basis of
        # the bridge's offline predecessor revalidation.
        self.assertEqual(
            D.authority_digest(accepted_v0_authority()),
            D.ARM_A_BRIDGE_V0_DISPATCH_DIGEST_SHA256)
        self.assertEqual(
            D.authority_digest(accepted_v0n_authority()),
            D.ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256)


# ---------------------------------------------------------------------------
# D4a — producer persists reachability provenance in Arm-A receipts
# ---------------------------------------------------------------------------


class ProducerProvenanceTests(unittest.TestCase):

    def test_bridge_path_receipt_carries_provenance(self):
        # [RED] A bridge-opened Arm-A unit receipt must persist
        # reachability_source="arm-a-bridge" (never written at the
        # reviewed head).
        from test_issue250_physical import (Env, fake_execute,
                                            fake_identity,
                                            fake_health_runner)
        real_source = P0.arm_a_reachability_source
        env = Env(self, "d250-arm-a", "A-vulkan-necessity")
        env.open_attestation()
        # Restore the REAL corrected Arm-A gate for the launch (Env
        # mocks it out; the bridge decides the path from the mounts).
        with mock.patch.object(P0, "arm_a_reachability_source", real_source):
            mounts = PredecessorMounts(self, env.evidence)
            write_bridge(env.evidence, mounts.bridge_record())
            tag = D.probe_list_for("A-vulkan-necessity")[0]["tag"]
            P0.run_diagnostic_unit(
                env.repo, env.evidence, "d250-arm-a",
                "A-vulkan-necessity", tag,
                binary=env.bin, binary_id="comparator",
                model_dir=env.model_dir, expected_head=env.head,
                model_attestation=env.attestation, execute=fake_execute,
                identity_observer=fake_identity,
                revalidate_authority=env.authority_fn(),
                health_runner=fake_health_runner)
        receipt = json.loads((env.evidence / "d250-arm-a" / tag /
                              "unit.json").read_bytes())
        self.assertEqual(receipt.get("reachability_source"),
                         "arm-a-bridge")

    def test_historical_path_receipt_carries_provenance(self):
        # [RED] A historically-opened Arm-A unit receipt must persist
        # reachability_source="historical-v0-amd-variable".
        from test_issue250_physical import Env
        env = Env(self, "d250-arm-a", "A-vulkan-necessity")
        env.open_attestation()
        env.populate_variable("d250-arm-a", "A-vulkan-necessity")
        tag = D.probe_list_for("A-vulkan-necessity")[0]["tag"]
        receipt = json.loads((env.evidence / "d250-arm-a" / tag /
                              "unit.json").read_bytes())
        self.assertEqual(receipt.get("reachability_source"),
                         "historical-v0-amd-variable")


# ---------------------------------------------------------------------------
# D4b — terminal reducer consumes a verified bridge-path Arm-A population
# ---------------------------------------------------------------------------


class TerminalBridgeStopTests(unittest.TestCase):
    """A completed bridge-path Arm-A population (variable or
    deterministic) must reach the intended post-A review decision and
    must NOT advance to Arm B."""

    def _fixture(self, arm_a_rows):
        from test_issue250_terminal import CampaignFixture
        fixture = CampaignFixture(self, arm_a_rows=arm_a_rows)
        self.addCleanup(fixture.restore_contrast_constant)
        # Re-present the campaign's own V0 population as the accepted
        # DISAGREEMENT_STOP: three identical NOVEL rows under the
        # campaign's V0 authority — the frozen reducer derives the
        # state from the bytes through the real validators.
        base = fixture.evidence / D.V0_NAMESPACE
        stable = (base / D.V0_UNIT_TAGS[0] / "obs.row0.f32").read_bytes()
        digest = hashlib.sha256(stable).hexdigest()
        for tag in D.V0_UNIT_TAGS[:2]:
            (base / tag / "obs.row0.f32").write_bytes(stable)
            path = base / tag / "unit.json"
            doc = json.loads(path.read_bytes())
            doc["decision0_row_sha256"] = digest
            path.write_text(json.dumps(doc))
        # Third unit: full copy of the second under the third tag with
        # a distinct PID (fresh-process attribution law).
        third = base / D.V0_UNIT_TAGS[2]
        shutil.copytree(base / D.V0_UNIT_TAGS[1], third)
        path = third / "unit.json"
        doc = json.loads(path.read_bytes())
        doc["tag"] = D.V0_UNIT_TAGS[2]
        doc["server_pid"] = 40003
        doc["process_attribution"]["server_pid"] = 40003
        path.write_text(json.dumps(doc))
        # Bridge-path predecessors + record at the campaign root (no
        # reviewed-head mirror: the terminal consumes the mounts).
        mounts = PredecessorMounts(self, fixture.evidence, mirror_v0n=False)
        write_bridge(fixture.evidence, mounts.bridge_record())
        # Rebuild the Arm-A population through the REAL producer under
        # the bridge path, so receipts persist arm-a-bridge provenance.
        shutil.rmtree(fixture.evidence / "d250-arm-a")
        fixture._build_arm_a(arm_a_rows)
        return fixture

    def test_bridge_path_arm_a_variable_stops_before_b(self):
        # [RED] At the reviewed head the terminal derivation blocks at
        # the V0 gate (the bridge never reaches the Arm-A walk), so the
        # frozen ARM_A_STOPS_LADDER reason is never surfaced.
        fixture = self._fixture("vary")
        self.addCleanup(fixture.restore_contrast_constant)
        out = fixture.derive()
        self.assertIsNone(out["terminal"])
        self.assertTrue(out["blocked"])
        self.assertTrue(any("METHODOLOGY-AMENDMENT-008" in p
                            for p in out["problems"]), out["problems"])

    def test_bridge_path_arm_a_deterministic_stops_before_b(self):
        # [RED] Deterministic Arm-A result: same stop law.
        fixture = self._fixture("det")
        self.addCleanup(fixture.restore_contrast_constant)
        out = fixture.derive()
        self.assertIsNone(out["terminal"])
        self.assertTrue(out["blocked"])
        self.assertTrue(any("METHODOLOGY-AMENDMENT-008" in p
                            for p in out["problems"]), out["problems"])


# ---------------------------------------------------------------------------
# D5 — mutation matrix: every corrected boundary rejects a forged record
# ---------------------------------------------------------------------------


class BridgeMutationTests(BridgeGateTestCase):
    """Each mutation of the ACCEPTED bridge record binding must reject
    (record claims are never authority — the mounts decide)."""

    def _mutated_gate(self, *path):
        # path = zero or more "v0"/"v0n" node names, final element a
        # (key, value) tuple
        record = self.mounts.bridge_record()
        node = record
        for name in path[:-1]:
            node = node[name]
        node[path[-1][0]] = path[-1][1]
        write_bridge(self.root, resign(record))
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_v0_state_claim_drift_rejects(self):
        # [MUT] record claims CONCORDANCE_STOP for V0
        self._mutated_gate("v0", ("state", D.V0_STATE_CONCORDANCE_STOP))

    def test_v0_units_claim_drift_rejects(self):
        self._mutated_gate("v0", ("units", 2))

    def test_v0_dispatch_claim_drift_rejects(self):
        self._mutated_gate("v0", ("dispatch_sha256", "f" * 64))

    def test_v0n_state_claim_drift_rejects(self):
        self._mutated_gate("v0n", ("state", D.V0N_STATE_CONCORDANCE_STOP))

    def test_v0n_units_claim_drift_rejects(self):
        self._mutated_gate("v0n", ("units", 3))

    def test_v0n_freeze_claim_drift_rejects(self):
        self._mutated_gate("v0n", ("freeze_sha256", "f" * 64))

    def test_eligible_arms_widening_rejects(self):
        # [MUT] granting later arms through the record is forbidden
        self._mutated_gate(
            ("eligible_arms",
             ["A-vulkan-necessity", "B-process-init"]))

    def test_executes_arm_a_claim_drift_rejects(self):
        self._mutated_gate(("executes_arm_a", True))

    def test_schema_drift_rejects(self):
        self._mutated_gate(("schema", "forged/1"))

    def test_producer_drift_rejects(self):
        self._mutated_gate(("recorded_by", "attacker"))

    def test_evidence_head_drift_rejects(self):
        self._mutated_gate(("evidence_head", "a" * 40))

    def test_maintainer_adjudication_unset_rejects(self):
        self._mutated_gate(("maintainer_adjudicated", False))

    def test_undigested_record_rejects(self):
        record = self.mounts.bridge_record()
        record["v0"]["units"] = 2
        write_bridge(self.root, record)  # canonical digest NOT recomputed
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_symlinked_bridge_record_rejects(self):
        record = self.mounts.bridge_record()
        (self.root / D.ARM_A_BRIDGE_NAME).unlink()
        (self.root / "real.json").write_text(json.dumps(record))
        (self.root / D.ARM_A_BRIDGE_NAME).symlink_to(
            self.root / "real.json")
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_missing_bridge_record_rejects(self):
        (self.root / D.ARM_A_BRIDGE_NAME).unlink()
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_symlinked_v0_mount_rejects(self):
        real = self.root / "real-v0"
        (self.root / "predecessor-v0").rename(real)
        (self.root / "predecessor-v0").symlink_to(real)
        with self.assertRaises(P0.PhysicalDiagnosticError):
            self.gate()

    def test_mixed_path_arm_a_population_rejects_at_terminal(self):
        # [MUT] a population mixing historical and bridge provenance
        # fails the terminal population check.
        from test_issue250_terminal import CampaignFixture
        fixture = CampaignFixture(self, arm_a_rows="det")
        self.addCleanup(fixture.restore_contrast_constant)
        receipt_path = (fixture.evidence / "d250-arm-a" /
                        D.probe_list_for("A-vulkan-necessity")[0]["tag"] /
                        "unit.json")
        doc = json.loads(receipt_path.read_bytes())
        doc["reachability_source"] = "arm-a-bridge"
        receipt_path.write_text(json.dumps(doc))
        out = fixture.derive()
        self.assertTrue(out["blocked"])


if __name__ == "__main__":
    unittest.main()
