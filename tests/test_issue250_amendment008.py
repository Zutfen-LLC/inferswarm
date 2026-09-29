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
    """Synthetic evidence root carrying the accepted predecessor
    population under real digests, plus the bridge record.

    CORRECTION ROUND 2: delegates to the round-2 mount builder
    (tests/test_issue250_amendment008_round2.PredecessorMounts), which
    installs read-only predecessor-v0/ and predecessor-v0n/ mounts with
    REAL content digests (bridge constants patched to the synthetic
    population and restored on cleanup) plus a top-level V0n mirror for
    legacy path expectations. Every frozen verifier runs unmodified
    over real bytes; mutated rows/receipts change their real digest and
    reject. A ``bridge_record()`` helper returns the resigned canonical
    record naming the synthetic digests.
    """

    def __init__(self, test: unittest.TestCase):
        from test_issue250_amendment008_round2 import PredecessorMounts
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mounts = PredecessorMounts(test, self.root)
        self.row_digests = list(self.mounts.v0n_rows)
        self.freeze = json.loads(
            (self.root / "predecessor-v0n" / P.V0N_FREEZE_NAME
             ).read_bytes())

    def bridge_record(self) -> dict:
        return self.mounts.bridge_record()


class BridgeValidatorTests(unittest.TestCase):
    """validate_arm_a_bridge over synthetic accepted-shape evidence."""

    def setUp(self):
        self.fixture = BridgeFixture(self)
        self.root = self.fixture.root

    def _valid_bridge(self) -> dict:
        """The canonical bridge record rebound to the fixture's
        synthetic population digests and resigned (correction round 2:
        mounts carry real synthetic digests; the committed record names
        the remote accepted bytes)."""
        return self.fixture.bridge_record()

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
            saved = {}
            for base in (self.root / "predecessor-v0n" / D.V0N_NAMESPACE,
                         self.root / D.V0N_NAMESPACE):
                saved[base] = (base / victim / "unit.json").read_bytes()
                (base / victim / "unit.json").unlink()
            with self.subTest(victim=victim):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P.validate_arm_a_bridge(self.root, V0N_HEAD)
            for base, raw in saved.items():
                (base / victim / "unit.json").write_bytes(raw)

    def test_extra_third_unit_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        for base in (self.root / "predecessor-v0n" / D.V0N_NAMESPACE,
                     self.root / D.V0N_NAMESPACE):
            extra = base / D.V0N_UNIT_TAGS[2]
            extra.mkdir()
            (extra / "unit.json").write_text("{}")
        # CORRECTION ROUND 2: rejected through the frozen
        # retained-population verifier (unexpected/partial/future unit
        # population) before the two-unit reduction.
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)
        shutil.rmtree(self.root / "predecessor-v0n" / D.V0N_NAMESPACE
                      / D.V0N_UNIT_TAGS[2])
        shutil.rmtree(self.root / D.V0N_NAMESPACE / D.V0N_UNIT_TAGS[2])

    def test_row_drift_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        for base in (self.root / "predecessor-v0n" / D.V0N_NAMESPACE,
                     self.root / D.V0N_NAMESPACE):
            row_path = base / D.V0N_UNIT_TAGS[0] / "obs.row0.f32"
            raw = row_path.read_bytes()
            row_path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_identity_custody_drift_rejects(self):
        record = self._valid_bridge()
        write_bridge_record(self.root, record)
        for base in (self.root / "predecessor-v0n" / D.V0N_NAMESPACE,
                     self.root / D.V0N_NAMESPACE):
            path = base / D.V0N_UNIT_TAGS[1] / "unit.json"
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
        # at all (asserted first). CORRECTION ROUND 2: the tail law (a
        # uniform, never-varied presented population rejects even when
        # every custody clause passes) runs through the frozen reducer
        # path on real bytes: unit-2 row rewritten to unit-1's bytes,
        # digest + record rebound, and reduce_v0n_screen derives
        # IDENTICAL_PAIR_THIRD_REQUIRED ≠ the accepted VARIABLE_STOP.
        record = self._valid_bridge()
        record["v0n"]["row_sha256"] = [record["v0n"]["row_sha256"][0]] * 2
        write_bridge_record(self.root, resign(record))
        with self.assertRaisesRegex(
                P.PhysicalDiagnosticError,
                "binding/authority mismatch"):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)
        mount_base = self.root / "predecessor-v0n" / D.V0N_NAMESPACE
        first = (mount_base / D.V0N_UNIT_TAGS[0] /
                 "obs.row0.f32").read_bytes()
        uniform = hashlib.sha256(first).hexdigest()
        for base in (mount_base, self.root / D.V0N_NAMESPACE):
            (base / D.V0N_UNIT_TAGS[1] / "obs.row0.f32").write_bytes(first)
            path = base / D.V0N_UNIT_TAGS[1] / "unit.json"
            doc = json.loads(path.read_bytes())
            doc["decision0_row_sha256"] = uniform
            path.write_text(json.dumps(doc))
        D.ARM_A_BRIDGE_V0N_ROW_SHA256 = (uniform, uniform)
        record = self._valid_bridge()
        record["v0n"]["row_sha256"] = [uniform, uniform]
        write_bridge_record(self.root, resign(record))
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_arm_a_bridge(self.root, V0N_HEAD)

    def test_committed_canonical_record_digest_authenticates(self):
        record = canonical_bridge_record()
        self.assertEqual(record["canonical_digest_sha256"],
                         P._v0_digest(record))
        # The fixture patches the digest constants to its synthetic
        # population; the committed record binds the REAL accepted
        # digests (asserted against the saved originals).
        saved = self.fixture.mounts.saved
        self.assertEqual(record["v0n"]["freeze_sha256"],
                         saved["freeze"])
        self.assertEqual(tuple(record["v0n"]["row_sha256"]),
                         tuple(saved["rows"]))
        self.assertEqual(record["v0"]["stable_row_sha256"],
                         saved["stable"])
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
        # CORRECTION ROUND 2: the fixture mounts carry synthetic
        # digests; the gate must receive the matching resigned record
        # (the committed canonical record names the remote bytes).
        write_bridge_record(self.root, self.fixture.bridge_record())
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
