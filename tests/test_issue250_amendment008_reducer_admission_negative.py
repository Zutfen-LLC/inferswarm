#!/usr/bin/env python3
"""Issue #250 — reducer-admission negative regressions (AMENDMENT-008
reducer-admission correction).

Every test here mutates ONE element of the compliant bridge-shaped
campaign (the same production shape
``BridgeReducerAdmissionTests`` proves GREEN after the correction) and
requires ``derive_terminal`` to FAIL CLOSED before consuming any Arm-A
population:

  * bridge record absent  -> the unchanged historical top-level-V0
    path runs (it blocks on the missing V0 namespace for this
    bridge-shaped root — never on bridge admission);
  * bridge record present but tampered/malformed/invalid -> the bridge
    admission rejects; the reducer NEVER falls back to historical V0
    admission (which cannot exist on a compliant bridge root anyway);
  * predecessor mount missing/symlinked/row-tampered/authority-invalid
    -> ``revalidating_arm_a_predecessors`` fails; admission blocks.

A mixed-provenance or provenance-less Arm-A population must also never
reach ``ARM_A_STOPS_LADDER``, and a valid bridge admission must not
fetch B/C/C1/C2/D authority after the Arm-A stop.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import issue250_diagnostic as D0  # noqa: E402
import issue250_physical as P0  # noqa: E402
import issue250_terminal as T0  # noqa: E402

D = P0.D

from test_issue250_amendment008_reducer_admission import (  # noqa: E402
    BridgeReducerAdmissionMixin,
    no_v0_dispatch_fetcher,
)


class BridgeReducerNegativeTests(
        BridgeReducerAdmissionMixin, unittest.TestCase):
    """One mutation per control on the compliant GREEN fixture; every
    control must fail closed at admission (never ARM_A_STOPS_LADDER,
    never a terminal, never historical-path fallback)."""

    def _derive_mutated(self, arm_a_rows, mutate):
        fixture, mounts = self._fixture(arm_a_rows)
        mutate(fixture, mounts)
        return self._derive(fixture)

    @staticmethod
    def _assert_admission_blocked(test, out, expect_bridge_marker=True):
        test.assertIsNone(out["terminal"])
        test.assertEqual(out["blocked"], T0.BLOCKED)
        joined = "\n".join(out["problems"])
        test.assertFalse(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])
        if expect_bridge_marker:
            test.assertTrue(
                "bridge" in joined.lower(), out["problems"])
        v0 = out.get("v0") or {}
        if expect_bridge_marker:
            test.assertEqual(v0.get("admission"), "amendment-008-bridge")
        # fail closed: never AMD_VARIABLE-eligible from a broken bridge
        test.assertNotEqual(v0.get("state"), D.V0_STATE_AMD_VARIABLE)

    # 1. bridge record absent -> the UNCHANGED historical path runs and
    #    blocks on the missing top-level V0 namespace (the historical
    #    law, unmodified; NOT a bridge rejection).
    def test_bridge_record_absent_runs_historical_path(self):
        def mutate(fixture, mounts):
            (fixture.evidence / D.ARM_A_BRIDGE_NAME).unlink()
        out = self._derive_mutated("vary", mutate)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertTrue(any("V0 gate blocks A" in p for p in out["problems"]),
                        out["problems"])
        self.assertFalse(any("bridge" in p.lower() for p in out["problems"]),
                         out["problems"])
        v0 = out.get("v0") or {}
        self.assertEqual(v0.get("state"), D.V0_STATE_INVALID)
        self.assertIsNone(v0.get("admission"))

    # 2. bridge record tampered (canonical digest mismatch)
    def test_bridge_record_tampered_rejects(self):
        def mutate(fixture, mounts):
            path = fixture.evidence / D.ARM_A_BRIDGE_NAME
            record = json.loads(path.read_bytes())
            record["v0"]["units"] = 7  # claim drift, digest NOT recomputed
            path.write_text(json.dumps(record))
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 3/4. predecessor mounts missing (record still valid)
    def test_predecessor_v0_mount_absent_rejects(self):
        def mutate(fixture, mounts):
            import shutil
            shutil.rmtree(fixture.evidence / "predecessor-v0")
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    def test_predecessor_v0n_mount_absent_rejects(self):
        def mutate(fixture, mounts):
            import shutil
            shutil.rmtree(fixture.evidence / "predecessor-v0n")
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 5. symlinked predecessor mount
    def test_predecessor_v0_mount_symlink_rejects(self):
        def mutate(fixture, mounts):
            import shutil
            root = fixture.evidence
            real = root / "real-predecessor-v0"
            (root / "predecessor-v0").rename(real)
            (root / "predecessor-v0").symlink_to(real)
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 6. wrong V0 stable-row digest (row bytes mutated)
    def test_v0_stable_row_drift_rejects(self):
        def mutate(fixture, mounts):
            path = (fixture.evidence / "predecessor-v0" / D.V0_NAMESPACE /
                    D.V0_UNIT_TAGS[2] / "obs.row0.f32")
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 7. wrong V0n row digest
    def test_v0n_row_drift_rejects(self):
        def mutate(fixture, mounts):
            path = (fixture.evidence / "predecessor-v0n" / D.V0N_NAMESPACE /
                    D.V0N_UNIT_TAGS[1] / "obs.row0.f32")
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 8. wrong V0n freeze digest (record re-signed to stale freeze)
    def test_v0n_freeze_drift_rejects(self):
        def mutate(fixture, mounts):
            mount = fixture.evidence / "predecessor-v0n"
            freeze_path = mount / P0.V0N_FREEZE_NAME
            doc = json.loads(freeze_path.read_bytes())
            doc["dispatch_sha256"] = "e" * 64
            doc["canonical_digest_sha256"] = P0._v0n_freeze_digest(doc)
            freeze_path.write_text(json.dumps(doc))
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 9. invalid reconstructed predecessor dispatch authority
    def test_v0_receipt_authority_drift_rejects(self):
        def mutate(fixture, mounts):
            path = (fixture.evidence / "predecessor-v0" / D.V0_NAMESPACE /
                    D.V0_UNIT_TAGS[0] / "unit.json")
            doc = json.loads(path.read_bytes())
            doc["authority_sha256"] = "f" * 64
            path.write_text(json.dumps(doc))
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 10. invalid predecessor state (V0 population no longer the
    #     accepted repeat-stable stop)
    def test_v0_population_state_drift_rejects(self):
        def mutate(fixture, mounts):
            path = (fixture.evidence / "predecessor-v0" / D.V0_NAMESPACE /
                    D.V0_UNIT_TAGS[1] / "obs.row0.f32")
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)

    # 11. bridge artifacts present but invalid must NOT fall back into
    #     the historical V0 path (historical admission is impossible on
    #     a compliant root: no top-level V0 tree exists).
    def test_invalid_bridge_never_falls_back_to_historical(self):
        def mutate(fixture, mounts):
            path = fixture.evidence / D.ARM_A_BRIDGE_NAME
            path.write_text("{not json")
        out = self._derive_mutated("vary", mutate)
        self._assert_admission_blocked(self, out)
        # The failure names the bridge, not the historical gate.
        self.assertTrue(any("Arm-A bridge" in p for p in out["problems"]),
                        out["problems"])

    # 12. bridge population with mixed Arm-A reachability provenance
    def test_mixed_provenance_arm_a_population_rejects(self):
        def mutate(fixture, mounts):
            receipt_path = (fixture.evidence / "d250-arm-a" /
                            D.probe_list_for(
                                "A-vulkan-necessity")[0]["tag"] /
                            "unit.json")
            doc = json.loads(receipt_path.read_bytes())
            doc["reachability_source"] = "historical-v0-amd-variable"
            receipt_path.write_text(json.dumps(doc))
        out = self._derive_mutated("vary", mutate)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertFalse(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])
        self.assertTrue(any("reachability" in p.lower()
                            for p in out["problems"]), out["problems"])

    def test_homogeneous_historical_provenance_cannot_use_bridge_admission(self):
        def mutate(fixture, mounts):
            for unit in (fixture.evidence / "d250-arm-a").iterdir():
                path = unit / "unit.json"
                doc = json.loads(path.read_bytes())
                doc["reachability_source"] = "historical-v0-amd-variable"
                path.write_text(json.dumps(doc))
        out = self._derive_mutated("vary", mutate)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertFalse(any(T0.ARM_A_STOPS_LADDER in p
                             for p in out["problems"]), out["problems"])

    def test_dangling_bridge_record_never_falls_back_to_historical(self):
        def mutate(fixture, mounts):
            path = fixture.evidence / D.ARM_A_BRIDGE_NAME
            path.unlink()
            path.symlink_to(fixture.evidence / "missing-bridge-record")
        out = self._derive_mutated("vary", mutate)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertFalse(any(T0.ARM_A_STOPS_LADDER in p
                             for p in out["problems"]), out["problems"])
        self.assertTrue(any("bridge" in p.lower()
                            for p in out["problems"]), out["problems"])

    def test_dangling_top_level_v0_symlink_refused_at_bridge_launch_gate(self):
        fixture, _ = self._fixture("vary")
        path = fixture.evidence / D.V0_NAMESPACE
        path.symlink_to(fixture.evidence / "missing-v0")
        with self.assertRaises((P0.PhysicalDiagnosticError, ValueError)):
            P0.validate_arm_a_bridge(fixture.evidence, fixture.head)

    # 13. bridge population with missing reachability provenance
    def test_missing_provenance_arm_a_population_rejects(self):
        def mutate(fixture, mounts):
            receipt_path = (fixture.evidence / "d250-arm-a" /
                            D.probe_list_for(
                                "A-vulkan-necessity")[0]["tag"] /
                            "unit.json")
            doc = json.loads(receipt_path.read_bytes())
            del doc["reachability_source"]
            receipt_path.write_text(json.dumps(doc))
        out = self._derive_mutated("vary", mutate)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertFalse(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])

    # 14. a valid bridge admission must not fetch B (or any later-arm)
    #     authority after the Arm-A stop.
    def test_bridge_stop_fetches_no_later_arm_authority(self):
        fixture, _ = self._fixture("vary")
        calls = []
        inner = no_v0_dispatch_fetcher(fixture)

        def counting(repo_root, expected_head, ns, github_api=None):
            calls.append(ns)
            return inner(repo_root, expected_head, ns, github_api)

        kw = dict(
            evidence_root=fixture.evidence, expected_head=fixture.head,
            repo_root=fixture.repo,
            authority_fetcher=counting,
            contrast_root=fixture.contrast_root,
        )
        with mock.patch.object(T0, "verify_v0_historical_rows",
                               return_value=dict(fixture.v0_history)):
            out = T0.derive_terminal(**kw)
        self.assertTrue(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])
        for ns in ("d250-arm-b", "d250-arm-c", "d250-arm-c1",
                   D.C2_SERIAL_NAMESPACE, "d250-arm-d"):
            self.assertNotIn(ns, calls)

    # 15. deterministic bridge result ALSO stops (never LOCALIZED /
    #     UNRESOLVED) — already proven positive; pinned here against
    #     the negative matrix so a future edit cannot loosen it.
    def test_deterministic_bridge_result_stops_not_localized(self):
        fixture, _ = self._fixture("det")
        out = self._derive(fixture)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertTrue(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])


if __name__ == "__main__":
    unittest.main()
