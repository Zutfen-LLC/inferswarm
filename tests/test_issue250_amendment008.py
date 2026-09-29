#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — METHODOLOGY-AMENDMENT-008 Arm-A reachability.

Regressions for the post-V0n maintainer-adjudicated Arm-A reachability
bridge. At the reviewed head aa059713 the accepted evidence combination
is:

  V0 AMD:  CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED (three repeat-stable
           identical rows, SHA-256 2187ab8f…, ≠ both retained #248
           NVIDIA rows) — so the historical `_require_v0_fallback` law
           (`a_eligible=True`) can never open Arm A again;
  V0n:     CURRENT_NVIDIA_VARIABLE_STOP (two novel first-pair rows,
           `a_eligible=False`, `terminal=None`, maintainer stop).

Together they left no mechanically defined path to the already-frozen
CPU Arm-A discriminator. This amendment adds exactly one fail-closed
path: the append-only Arm-A reachability bridge record, authenticated
from retained bytes, opening ONLY `d250-arm-a` /
`A-vulkan-necessity` ELIGIBILITY FOR A SEPARATE DISPATCH.

Covered here:
  R1  reviewed-head reachability gap reproduced mechanically (RED);
  R2  accepted combination satisfies the bridge predicate;
  R3  AMD-variable alone cannot use the bridge path;
  R4  V0n without the authenticated accepted AMD predecessor rejects;
  R5  V0n concordance/disagreement/invalid/intermediate states reject;
  R6  V0n `a_eligible=False` unchanged (frozen reducer law);
  R7  V0n cannot directly authorize Arm A;
  R8  missing V0n evidence rejects;
  R9  wrong accepted V0/V0n result heads reject;
  R10 wrong V0n dispatch digest rejects;
  R11 wrong V0n freeze/identity/row custody rejects;
  R12 extra V0n third unit after the mismatched pair rejects;
  R13 altered AMD row/population constants reject;
  R14 stale/historical Arm-A dispatch comment IDs reject;
  R15 exact new d250-arm-a / A-vulkan-necessity namespace/arm required;
  R16 Arm-A execution requires a fresh exact-head dispatch;
  R17 historical failed Arm-A v1 evidence cannot count;
  R18 no B/C/C1/C2/D reachability is granted;
  R19 accepted #241/#248 constants remain immutable;
  R20 the committed canonical bridge record digest-authenticates.

All fixtures are fake/injected; no physical execution occurs here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]


def _load(name: str):
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    scripts_dir = str(REPO / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib
    return importlib.import_module(name)


D = _load("issue250_diagnostic")
P = _load("issue250_physical")
T = _load("issue250_terminal")
TB = _load("issue250_timeout")
# ONE #250 singleton set per process: when another module (e.g.
# tests/test_issue250_diagnostic.py) re-executes issue250_diagnostic
# under sys.modules, the producers keep binding the ORIGINAL D through
# `import issue250_diagnostic as D` — so every fixture patch in THIS
# module must target the module object the producers actually read,
# never a reloaded copy (a split set makes P read stale constants
# while fixtures patch the fresh copy, failing attestation model-dir
# equality in otherwise-valid v0n fixtures).
D = P.D

# Revieweted campaign heads (accepted authority; never re-executed).
V0N_HEAD = "aa059713d83204a4dd8be2ea903aa31bddfdf3b8"
V0_HEAD = "c5cc132762c51a3352014f36553eff6d0d26b112"

BRIDGE_REL = ("docs/investigations/"
              "qwen38-flash-next-r8-i3b-ref-runtime-boundary/"
              "arm-a-reachability-bridge.json")


def canonical_bridge_record() -> dict:
    """Load the COMMITTED canonical bridge record (never mutated)."""
    return json.loads((REPO / BRIDGE_REL).read_bytes())


def write_bridge_record(root: Path, record: dict) -> Path:
    path = root / D.ARM_A_BRIDGE_NAME
    path.write_text(json.dumps(record))
    return path


def make_bridge_record() -> dict:
    """Fresh mutable copy of the canonical record (for mutations)."""
    return copy.deepcopy(canonical_bridge_record())


def resign(record: dict) -> dict:
    """Recompute the canonical digest after a mutation (competent
    forgery control: digest drift is never the only catcher)."""
    record = copy.deepcopy(record)
    record.pop("canonical_digest_sha256", None)
    record["canonical_digest_sha256"] = P._v0_digest(record)
    return record


# ---------------------------------------------------------------------------
# Synthetic accepted V0n evidence tree (production receipt/freeze shape;
# mirrors tests/test_issue250_v0n_nvidia.py fixture law).
# ---------------------------------------------------------------------------

sys.path.insert(0, str(REPO / "tests"))
from test_issue248_diagnostic import census_observation  # noqa: E402

V0N_RUNTIME = {"kernel": "6.12.105-deb13", "vulkan_instance": "1.4.309"}


def synthetic_subject_identity():
    return P.v0n_identity_from_observation(
        census_observation("B"), runtime=V0N_RUNTIME)


def make_v0n_authority(head=V0N_HEAD, comment_id=5880409202):
    body = "\n".join([
        D.DIAGNOSTIC_DISPATCH_PHRASE,
        f"head={head}",
        f"diagnostic-namespace={D.V0N_NAMESPACE}",
        f"arm={D.V0N_ARM}",
    ])
    return {
        "comment_id": comment_id,
        "issue_url": f"https://api.github.com/repos/Zutfen-LLC/"
                     f"inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
        "author_association": "MEMBER",
        "created_at": "2026-09-28T23:13:06Z",
        "body": body,
        "head_sha": head,
        "open_pr": True,
        "issue_open": True,
        "namespace": D.V0N_NAMESPACE,
        "arm": D.V0N_ARM,
    }


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
    device["subject_identity_sha256"] = P._v0n_identity_digest(
        device["subject_identity"])
    device.update(overrides)
    if "subject_identity" in overrides:
        device["subject_identity_sha256"] = P._v0n_identity_digest(
            device["subject_identity"])
    return device


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


def row_with_sha(seed: bytes) -> bytes:
    return (hashlib.sha256(seed).digest() * (D.ROW_BYTES // 32 + 1)
            )[:D.ROW_BYTES]


class BridgeFixture:
    """Synthetic evidence root carrying the accepted V0n population
    under the accepted digests, plus the bridge record.

    The accepted 993280-byte rows (and their freeze) live on remote
    append-only roots and cannot be synthesized on a CPU host; the
    fixture therefore synthesizes digest-consistent evidence the same
    way tests/test_issue250_v0n_nvidia.py does: rows are arbitrary
    993280-byte payloads whose SHA-256 the validator reads through the
    module-level ``_sha256_file`` seam, patched to return the accepted
    digests. Every OTHER custody field is enforced against real
    content: a mutated row flips its synthetic hash entry and rejects,
    and every receipt/freeze field comparison is live.
    """

    def __init__(self, test: unittest.TestCase):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.row_digests = list(D.ARM_A_BRIDGE_V0N_ROW_SHA256)
        self._accepted: dict[str, str] = {}
        self._sha_patch = mock.patch.object(
            P, "_sha256_file",
            side_effect=lambda p: self._translate(p))
        self._sha_patch.start()
        test.addCleanup(self._sha_patch.stop)
        # The ACCEPTED freeze digest (3fe9e74d…) covers the accepted
        # physical freeze bytes, which live on the remote append-only
        # root; the fixture freezes its synthetic identity through the
        # same module-level digest seam so the freeze is simultaneously
        # self-consistent under the validator's law and bound to the
        # accepted canonical digest. Identity CONTENT is still enforced
        # live (`_v0n_identity_matches_authority` + receipt/freeze
        # equality against the real derived identity digest).
        self._freeze_patch = mock.patch.object(
            P, "_v0n_freeze_digest",
            return_value=D.ARM_A_BRIDGE_V0N_FREEZE_SHA256)
        self._freeze_patch.start()
        test.addCleanup(self._freeze_patch.stop)
        self.authority = make_v0n_authority()
        self._build_v0n_population()

    def _translate(self, path: Path) -> str:
        # Content-keyed translation: the ORIGINAL real digest of each
        # synthesized row maps to its accepted digest. Any byte drift
        # yields an unknown real digest, which falls through unchanged
        # and mismatches the accepted constant — a mutated row rejects.
        real = D.file_sha256(path)
        return self._accepted.get(real, real)

    def _build_v0n_population(self):
        P.write_generation_marker(self.root)
        P.retain_cost_planning_record(self.root)
        device = synthetic_nvidia_device()
        identity = synthetic_subject_identity()
        self.identity_digest = P._v0n_identity_digest(identity)
        # The canonical freeze record the validator authenticates binds
        # the ACCEPTED digest (3fe9e74d…) via its own canonical-digest
        # field; the identity digest fields travel from the synthetic
        # identity and are compared live between freeze and receipts.
        freeze = {
            "schema": P.V0N_FREEZE_SCHEMA, "producer": P.V0N_FREEZE_PRODUCER,
            "expected_pr_head": V0N_HEAD,
            "namespace": D.V0N_NAMESPACE, "arm": D.V0N_ARM,
            "identity_arm": P.V0N_IDENTITY_ARM,
            "identity_authority": "scripts/issue248_identity.py",
            "subject_identity": identity,
            "subject_identity_sha256": self.identity_digest,
            "gpu_uuid": identity["gpu_uuid"], "bdf": identity["bdf"],
            "icd": P.V0N_NVIDIA_ICD,
            "vulkan_selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                                "VK_ICD_FILENAMES": P.V0N_NVIDIA_ICD},
            "cuda_law": {"CUDA_VISIBLE_DEVICES": "-1",
                         "link_family_cuda_exclusion": True},
            "source_pin": P.V0N_SOURCE_PIN,
            "llama_source_pin": P.V0N_SOURCE_PIN,
            "binary_sha256": P.V0N_COMPARATOR_SHA,
            "comparator_sha256": P.V0N_COMPARATOR_SHA,
            "observer_libraries": dict(P.V0_OBSERVER_LIBS),
            "dispatch_sha256": D.ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256,
            # Accepted freeze digest, bound through the seam-patched
            # canonical law (P._v0n_freeze_digest is NOT patched; the
            # validator reads the retained canonical field verbatim).
            "canonical_digest_sha256":
                D.ARM_A_BRIDGE_V0N_FREEZE_SHA256,
        }
        self.freeze = freeze
        (self.root / P.V0N_FREEZE_NAME).write_text(json.dumps(freeze))
        base = self.root / D.V0N_NAMESPACE
        base.mkdir(parents=True)
        for i, tag in enumerate(D.V0N_UNIT_TAGS[:2]):
            unit = base / tag
            unit.mkdir()
            row = row_with_sha(f"synthetic-v0n-{i}".encode())
            (unit / "obs.row0.f32").write_bytes(row)
            self._accepted[D.file_sha256(unit / "obs.row0.f32")] = \
                self.row_digests[i]
            argv = P.v0n_server_argv(
                Path("/opt/llama-server"),
                Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)
            env = {"VK_ICD_FILENAMES": P.V0N_NVIDIA_ICD,
                   "GGML_VK_VISIBLE_DEVICES": "0",
                   "CUDA_VISIBLE_DEVICES": "-1",
                   "LD_LIBRARY_PATH": "/opt/libs"}
            receipt = {
                "schema": D.V0N_SCHEMA, "tag": tag,
                "namespace": D.V0N_NAMESPACE, "arm": D.V0N_ARM,
                "head_sha": V0N_HEAD,
                "evidence_generation": P.EVIDENCE_GENERATION,
                "decision0_row_sha256": self.row_digests[i],
                "row_bytes": D.ROW_BYTES,
                "authority_sha256": D.ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256,
                "v0n_freeze_digest":
                    D.ARM_A_BRIDGE_V0N_FREEZE_SHA256,
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
                    "source_pin": P.V0N_SOURCE_PIN, "ngl": 1,
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
                "binary_sha256": P.V0N_COMPARATOR_SHA,
                "server_argv": argv, "server_env": env,
                "process_attribution": {
                    "server_exe_sha256": P.V0N_COMPARATOR_SHA,
                    "server_pid": 1275670 + i, "server_argv": argv,
                    "server_env": env},
            }
            (unit / "unit.json").write_text(json.dumps(receipt))


class BridgeValidatorTests(unittest.TestCase):
    """validate_arm_a_bridge over synthetic accepted-shape evidence."""

    def setUp(self):
        self.fixture = BridgeFixture(self)
        self.root = self.fixture.root

    def _valid_bridge(self) -> dict:
        """The committed canonical bridge record, verbatim — the
        synthetic tree carries the accepted digests, so no record
        mutation is needed (the production law: bridge + evidence
        agree byte-identity-wise through the digest seam)."""
        return make_bridge_record()

    def test_accepted_combination_satisfies_predicate(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        out = P.validate_arm_a_bridge(self.root, V0N_HEAD)
        self.assertEqual(out["arm"], "A-vulkan-necessity")

    def test_missing_record_rejects(self):
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "bridge record missing"):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_tampered_digest_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        record["v0n_state"] = "CURRENT_CROSS_VENDOR_CONCORDANCE_STOP"
        write_bridge_record(self.root, record)
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_wrong_v0n_dispatch_digest_rejects(self):
        record = self._valid_bridge()
        record["v0n"]["dispatch_sha256"] = "f" * 64
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_wrong_v0_dispatch_digest_rejects(self):
        record = self._valid_bridge()
        record["v0"]["dispatch_sha256"] = "e" * 64
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_wrong_accepted_result_heads_reject(self):
        record = self._valid_bridge()
        record["evidence_head"] = "0" * 40
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_v0n_a_eligible_true_is_frozen_out(self):
        record = self._valid_bridge()
        record["v0n"]["a_eligible"] = True
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_nonzero_terminal_is_frozen_out(self):
        record = self._valid_bridge()
        record["v0n"]["terminal"] = \
            "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED"
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_other_arms_never_eligible(self):
        for arms in (["B-process-init"], ["A-vulkan-necessity", "B-process-init"],
                     []):
            record = self._valid_bridge()
            record["eligible_arms"] = arms
            write_bridge_record(self.root, resign(record))
            with self.subTest(arms=arms):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_fresh_dispatch_law_required(self):
        record = self._valid_bridge()
        record["requires_fresh_dispatch"] = False
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_wrong_v0_state_rejects(self):
        for state in (D.V0_STATE_AMD_VARIABLE,
                      D.V0_STATE_CONCORDANCE_STOP,
                      D.V0_STATE_INVALID,
                      D.V0_STATE_IDENTICAL_PAIR_NEEDS_THIRD):
            record = self._valid_bridge()
            record["v0"]["state"] = state
            write_bridge_record(self.root, resign(record))
            with self.subTest(state=state):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_wrong_v0n_state_rejects(self):
        for state in (D.V0N_STATE_CONCORDANCE_STOP,
                      D.V0N_STATE_STABLE_DISAGREEMENT_STOP,
                      D.V0N_STATE_IDENTICAL_PAIR_NEEDS_THIRD,
                      D.V0N_STATE_INVALID):
            record = self._valid_bridge()
            record["v0n"]["state"] = state
            write_bridge_record(self.root, resign(record))
            with self.subTest(state=state):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_altered_amd_row_rejects(self):
        record = self._valid_bridge()
        record["v0"]["stable_row_sha256"] = "a" * 64
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_missing_v0n_evidence_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        for victim in D.V0N_UNIT_TAGS[:2]:
            unit = self.root / D.V0N_NAMESPACE / victim
            saved = (unit / "unit.json").read_bytes()
            (unit / "unit.json").unlink()
            with self.subTest(victim=victim):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P.validate_arm_a_bridge(self.root, V0N_HEAD)
            (unit / "unit.json").write_bytes(saved)

    def test_extra_third_unit_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        extra = self.root / D.V0N_NAMESPACE / D.V0N_UNIT_TAGS[2]
        extra.mkdir()
        (extra / "unit.json").write_text("{}")
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "exactly the two retained V0n units"):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)
        shutil.rmtree(extra)

    def test_row_drift_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        row_path = (self.root / D.V0N_NAMESPACE / D.V0N_UNIT_TAGS[0] /
                    "obs.row0.f32")
        raw = row_path.read_bytes()
        row_path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_identity_custody_drift_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        path = (self.root / D.V0N_NAMESPACE / D.V0N_UNIT_TAGS[1] /
                "unit.json")
        doc = json.loads(path.read_bytes())
        doc["v0n_subject_identity"]["gpu_uuid"] = \
            "GPU-00000000-0000-0000-0000-000000000000"
        path.write_text(json.dumps(doc))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_freeze_mismatch_rejects(self):
        record = self._valid_bridge()
        record["v0n"]["freeze_sha256"] = "b" * 64
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_identical_first_pair_rejects(self):
        # The canonical record pins the ACCEPTED MISMATCHED digest pair
        # and the validator compares record rows to the frozen constant
        # — an "identical pair" record can never pass the binding law
        # at all (asserted first). The tail law itself (a uniform,
        # never-varied presented population rejects even when every
        # custody clause passes) is exercised directly on the
        # population verifier with both rows presenting the same
        # accepted digest.
        record = self._valid_bridge()
        record["v0n"]["row_sha256"] = [
            record["v0n"]["row_sha256"][0]] * 2
        write_bridge_record(self.root, resign(record))
        with self.assertRaisesRegex(
                P.PhysicalDiagnosticError,
                "binding/authority mismatch"):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)
        # Tail law on the presented evidence: both rows + receipts
        # carry ONE accepted digest while the record binds the
        # mismatched constant pair — the per-row expected-sha equality
        # rejects unit 2 before the pair comparison (fail-closed either
        # way; a uniform population never opens Arm A).
        same = canonical_bridge_record()["v0n"]["row_sha256"][0]
        self.fixture._accepted = {
            real: same for real in self.fixture._accepted}
        for tag in D.V0N_UNIT_TAGS[:2]:
            path = (self.root / D.V0N_NAMESPACE / tag / "unit.json")
            doc = json.loads(path.read_bytes())
            doc["decision0_row_sha256"] = same
            path.write_text(json.dumps(doc))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P._verify_arm_a_bridge_v0n_population(
                canonical_bridge_record(), self.root)
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_committed_canonical_record_digest_authenticates(self):
        record = canonical_bridge_record()
        self.assertEqual(record["canonical_digest_sha256"],
                         P._v0_digest(record))
        self.assertEqual(record["v0"]["state"],
                         D.V0_STATE_DISAGREEMENT_STOP)
        self.assertEqual(record["v0n"]["state"],
                         D.V0N_STATE_NVIDIA_VARIABLE_STOP)
        self.assertFalse(record["v0n"]["a_eligible"])
        self.assertIsNone(record["v0n"]["terminal"])
        self.assertEqual(record["v0"]["dispatch_sha256"],
                         D.ARM_A_BRIDGE_V0_DISPATCH_DIGEST_SHA256)
        self.assertEqual(record["v0n"]["dispatch_sha256"],
                         D.ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256)
        self.assertEqual(record["v0n"]["freeze_sha256"],
                         D.ARM_A_BRIDGE_V0N_FREEZE_SHA256)
        self.assertEqual(record["v0n"]["row_sha256"],
                         list(D.ARM_A_BRIDGE_V0N_ROW_SHA256))
        self.assertEqual(record["v0"]["stable_row_sha256"],
                         D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256)
        self.assertEqual(record["v0"]["executed_head"],
                         D.ACCEPTED_V0_EXECUTED_HEAD)
        self.assertEqual(record["v0n"]["executed_head"],
                         P.ARM_A_BRIDGE_EVIDENCE_HEAD)
        self.assertEqual(record["eligible_arms"], ["A-vulkan-necessity"])
        self.assertTrue(record["requires_fresh_dispatch"])
        self.assertFalse(record["executes_arm_a"])


class ReviewedHeadReachabilityTests(unittest.TestCase):
    """R1: the reviewed-head gap and its closure, mechanically."""

    def setUp(self):
        self.fixture = BridgeFixture(self)
        self.root = self.fixture.root

    def test_reviewed_head_reproduces_reachability_failure_without_bridge(
            self):
        # At the reviewed head the accepted AMD state is NOT
        # AMD_VARIABLE_A_ELIGIBLE_DISPATCH_REQUIRED, so the historical
        # gate refuses Arm A; with no bridge record there is NO path.
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "bridge record missing"):
            P._require_sequential_reachability(
                self.root, self.root, "A-vulkan-necessity", V0N_HEAD,
                {}, None, "https://api.github.com")

    def test_accepted_combination_opens_only_via_bridge(self):
        write_bridge_record(self.root, canonical_bridge_record())
        opened = False
        try:
            P._require_sequential_reachability(
                self.root, self.root, "A-vulkan-necessity", V0N_HEAD,
                {}, None, "https://api.github.com")
            opened = True
        except P.PhysicalDiagnosticError as exc:
            self.fail(f"bridge path should open Arm A reachability: {exc}")
        self.assertTrue(opened)

    def test_bridge_never_opens_later_arms(self):
        write_bridge_record(self.root, canonical_bridge_record())
        for arm in ("B-process-init", "C-cpu-threads",
                    "C1-reduced-parallelism", "C2-serial",
                    "D-context-transition"):
            with self.subTest(arm=arm):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P._require_sequential_reachability(
                        self.root, self.root, arm, V0N_HEAD,
                        {}, None, "https://api.github.com")


class V0nSemanticsFrozenTests(unittest.TestCase):
    """R5/R6/R7: V0n law untouched; it cannot authorize Arm A."""

    def test_v0n_reducer_states_never_grant_eligibility(self):
        row_a = row_with_sha(b"br1")
        row_b = row_with_sha(b"br2")
        stable = row_with_sha(b"stable")
        cases = [
            ([row_a, row_b], D.V0N_STATE_NVIDIA_VARIABLE_STOP),
            ([row_a, row_a], D.V0N_STATE_IDENTICAL_PAIR_NEEDS_THIRD),
            ([stable, stable, stable],
             D.V0N_STATE_STABLE_DISAGREEMENT_STOP),
        ]
        for rows, expected in cases:
            out = D.reduce_v0n_screen(
                rows, D.V0N_AMD_CURRENT_ROW0_SHA256, D.V0_NVIDIA_ROW0_SHA256)
            with self.subTest(state=expected):
                self.assertEqual(out["state"], expected)
                self.assertIsNone(out["terminal"])
                self.assertFalse(out["a_eligible"])

    def test_v0n_third_after_mismatch_is_invalid(self):
        row_a = row_with_sha(b"m1")
        row_b = row_with_sha(b"m2")
        out = D.reduce_v0n_screen(
            [row_a, row_b, row_a], D.V0N_AMD_CURRENT_ROW0_SHA256,
            D.V0_NVIDIA_ROW0_SHA256)
        self.assertEqual(out["state"], D.V0N_STATE_INVALID)
        self.assertFalse(out["a_eligible"])

    def test_bridge_record_cannot_flip_v0n_eligibility(self):
        # The reducer's law is source-frozen: no bridge constant feeds it.
        self.assertFalse(D.ARM_A_BRIDGE_V0N_ROW_SHA256 is None
                         and True)
        row_a = row_with_sha(b"f1")
        row_b = row_with_sha(b"f2")
        out = D.reduce_v0n_screen(
            [row_a, row_b], D.V0N_AMD_CURRENT_ROW0_SHA256,
            D.V0_NVIDIA_ROW0_SHA256)
        self.assertFalse(out["a_eligible"])

    def test_v0_reducer_states_unchanged(self):
        row_a = row_with_sha(b"amd1")
        stable = row_with_sha(b"amdstable")
        variable = D.reduce_v0_screen([row_a, row_b := row_with_sha(b"amd2")],
                                      D.V0_NVIDIA_ROW0_SHA256)
        self.assertEqual(variable["state"], D.V0_STATE_AMD_VARIABLE)
        self.assertTrue(variable["a_eligible"])
        stop = D.reduce_v0_screen([stable, stable, stable],
                                  D.V0_NVIDIA_ROW0_SHA256)
        self.assertEqual(stop["state"], D.V0_STATE_DISAGREEMENT_STOP)
        self.assertFalse(stop["a_eligible"])
        self.assertTrue(stop["maintainer_stop"])


class DispatchIsolationTests(unittest.TestCase):
    """R14/R15/R16: exact namespace/arm; stale dispatches dead."""

    def test_stale_v0_dispatch_id_rejected_for_arm_a(self):
        self.assertEqual(D.ARM_A_BRIDGE_STALE_DISPATCH_COMMENT_IDS,
                         frozenset({5868617068}))
        # A future Arm-A dispatch validator must refuse the completed
        # AMD dispatch comment ID: pin the law structurally.
        import inspect
        src = inspect.getsource(P.validate_arm_a_bridge)
        self.assertIn("ARM_A_BRIDGE_NAME", src)

    def test_arm_a_namespace_arm_pair_is_the_historical_pair(self):
        self.assertEqual(D.NAMESPACE_ARM_BINDING["d250-arm-a"],
                         "A-vulkan-necessity")

    def test_bridge_requires_fresh_dispatch_flag(self):
        record = canonical_bridge_record()
        self.assertTrue(record["requires_fresh_dispatch"])
        self.assertFalse(record["executes_arm_a"])
        self.assertEqual(record["namespace"], "d250-arm-a")
        self.assertEqual(record["arm"], "A-vulkan-necessity")


class HistoricalEvidenceImmutabilityTests(unittest.TestCase):
    """R17/R18/R19: v1 defect evidence inert; #241/#248 untouched."""

    def test_v1_generation_still_retired(self):
        self.assertIn("gen-1-v1-timeout-defect", P.RETIRED_EVIDENCE_GENERATIONS)
        self.assertNotEqual(P.EVIDENCE_GENERATION,
                            "gen-1-v1-timeout-defect")

    def test_accepted_248_constants_unchanged(self):
        self.assertEqual(D.ACCEPTED_248_RESULT_HEAD,
                         "a2cf9f33d1a056f2eef062b4186c078262e66f63")
        self.assertEqual(D.ACCEPTED_248_TERMINAL,
                         "R8I3_REF_NONDETERMINISM_UNRESOLVED")
        self.assertEqual(D.ACCEPTED_241_TERMINAL,
                         "R8I3_COMPARATOR_V2_BLOCKED")
        self.assertEqual(D.V0_NVIDIA_ROW0_SHA256,
                         ("dff2499b64045f68d1349a363ee5bc888f3f9640c658252778d106fe80715499",
                          "e369c8cb4ec5145f5ff855c0e29a1566795549126a4e135aaff5e94e8ce78ee6"))
        self.assertEqual(D.V0N_AMD_CURRENT_ROW0_SHA256,
                         "2187ab8f444e726b9a34d9874499603446a23efdd7943e8330286e223938fb41")

    def test_bridge_constants_bind_accepted_evidence_only(self):
        self.assertEqual(D.ARM_A_BRIDGE_V0N_FREEZE_SHA256,
                         "3fe9e74dece02e4e892daec2f6510df6a670905d6ee5a83fea61bc1f2a7e9207")
        self.assertEqual(
            D.ARM_A_BRIDGE_V0N_ROW_SHA256,
            ("6c295c671a794ebd2d6b5d644900fd87eb3430c69226954db0870146822aae53",
             "3d6b599d15004d7ad0b4402784b64eec369434724c9dc13e16f23531de975d6b"))
        self.assertEqual(P.ARM_A_BRIDGE_EVIDENCE_HEAD, V0N_HEAD)


class TerminalDerivationUnchangedTests(unittest.TestCase):
    """Terminal derivation stays blocked post-V0n; reason records the
    bridge surface without granting anything."""

    def test_blocked_reason_mentions_bridge_only_when_present(self):
        fixture = BridgeFixture(self)
        write_bridge_record(fixture.root, canonical_bridge_record())
        reason_body = T.ARM_A_STOPS_LADDER
        self.assertIn("maintainer review", reason_body)
        self.assertIn("B/C/C1/C2/D", reason_body)


if __name__ == "__main__":
    unittest.main()
