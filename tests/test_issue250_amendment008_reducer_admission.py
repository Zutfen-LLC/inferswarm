#!/usr/bin/env python3
"""Issue #250 — METHODOLOGY-AMENDMENT-008 reducer-admission correction (RED).

Reviewed-head defect (defect report PR #251 comment 5897507995,
maintainer adjudication 5897538288): ``derive_terminal()`` calls
``derive_v0_state(...)`` BEFORE the Arm-A walk.  ``derive_v0_state``
requires (a) a TOP-LEVEL ``d250-arm-v0-amd/`` tree in the campaign
evidence root and (b) live ``d250-arm-v0-amd`` dispatch authority at the
CURRENT PR head.  A compliant AMENDMENT-008 round-2 bridge campaign has
NEITHER: accepted predecessor evidence exists only under the read-only
``predecessor-v0/`` + ``predecessor-v0n/`` mounts, and the completed V0
dispatch (comment 5868617068) is historical/stale (frozen in
``ARM_A_BRIDGE_STALE_DISPATCH_COMMENT_IDS``).  A fully compliant bridge
campaign therefore derived ``V0_INVALID_BLOCKED`` and returned BEFORE
the ``reachability_source == "arm-a-bridge"`` / ``ARM_A_STOPS_LADDER``
branch — production-unreachable for exactly the campaign shape the
amendment authorizes.

The existing ``TerminalBridgeStopTests`` fixtures hid the divergence by
supplying a synthetic TOP-LEVEL V0 population and a same-head V0
authority in the fixture's fetcher (both impossible in production).
The fixture here carries NONE of those: no top-level ``d250-arm-v0-amd/``,
no top-level V0n namespace, and a V0-namespace fetch that ALWAYS fails
(the only legal production answer for a completed predecessor).  Only
the required current-campaign material is present: committed bridge
record, ``predecessor-v0/`` + ``predecessor-v0n/`` mounts (synthetic
bytes under real-digest-pinned constants — the established fixture
precedent), a valid current-head ``d250-arm-a`` authority, and a
completed Arm-A population whose receipts persist
``reachability_source="arm-a-bridge"``.

Committed RED at reviewed head 0b6da00343f353932e80cf43f9e88d301d9a5ccd:
``derive_terminal`` blocks with ``V0_INVALID_BLOCKED`` before Arm A.
After the reducer correction the same fixture must reach Arm A and stop
with ``ARM_A_STOPS_LADDER`` — for the variable AND the deterministic
Arm-A result — without ever consulting a ``d250-arm-v0-amd`` dispatch.
"""
from __future__ import annotations

import json
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

# ONE singleton set per process (the amendment008/terminal suite law):
# the CampaignFixture patches module attributes (D.SERVER_BINARIES,
# D.MODEL_DIR) on ITS loaded singletons; derive() must run against the
# SAME module objects the fixture built its bytes under.
D = P0.D

from test_issue250_amendment008_round2 import (  # noqa: E402
    PredecessorMounts,
    write_bridge,
)
from test_issue250_terminal import CampaignFixture  # noqa: E402


def no_v0_dispatch_fetcher(fixture):
    """Production-shaped live-dispatch fetcher: every namespace resolves
    through the fixture's authority map EXCEPT ``d250-arm-v0-amd`` —
    the completed predecessor dispatch can never be served again at a
    new head (any current-head V0 fetch must fail, as the real GitHub
    timeline guarantees)."""
    inner = fixture.fetch_all()

    def fetch(repo_root, expected_head, ns, github_api=None):
        if ns == D.V0_NAMESPACE:
            raise D.DiagnosticError(
                "no live dispatch authority for namespace "
                f"{D.V0_NAMESPACE} (completed predecessor; stale "
                f"comment {D.ARM_A_BRIDGE_V0_DISPATCH_COMMENT_ID})")
        return inner(repo_root, expected_head, ns, github_api)
    return fetch


class BridgeReducerAdmissionTests(unittest.TestCase):
    """A compliant bridge-shaped campaign root — NO top-level V0/V0n
    trees, NO same-head V0 authority — must reach the Arm-A walk in
    ``derive_terminal`` and stop at ``ARM_A_STOPS_LADDER``."""

    def _fixture(self, arm_a_rows):
        # CampaignFixture builds the synthetic V0 population at the
        # evidence-root TOP LEVEL (its legacy shape); a compliant
        # bridge campaign carries NONE of it, so it is removed.  The
        # v0-selector binding/freeze/preflight artifacts are V0's own
        # custody and go with it (the bridge revalidates the accepted
        # predecessor decision from the read-only mount instead).
        fixture = CampaignFixture(self, arm_a_rows=arm_a_rows)
        self.addCleanup(fixture.restore_contrast_constant)
        for name in (D.V0_NAMESPACE, "v0-selector-binding.json",
                     P0.V0_FREEZE_NAME, "v0-selector-preflight"):
            path = fixture.evidence / name
            if path.is_dir() and not path.is_symlink():
                import shutil
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        # Bridge-path predecessors + committed record at the campaign
        # root (no top-level V0n mirror: round-2 law forbids top-level
        # predecessor namespaces entirely).
        mounts = PredecessorMounts(self, fixture.evidence, mirror_v0n=False)
        write_bridge(fixture.evidence, mounts.bridge_record())
        # Rebuild the Arm-A population through the REAL producer under
        # the bridge path so receipts persist arm-a-bridge provenance.
        import shutil
        shutil.rmtree(fixture.evidence / "d250-arm-a")
        fixture._build_arm_a(arm_a_rows)
        return fixture, mounts

    def _derive(self, fixture):
        kw = dict(
            evidence_root=fixture.evidence, expected_head=fixture.head,
            repo_root=fixture.repo,
            authority_fetcher=no_v0_dispatch_fetcher(fixture),
            contrast_root=fixture.contrast_root,
        )
        with mock.patch.object(T0, "verify_v0_historical_rows",
                               return_value=dict(fixture.v0_history)):
            return T0.derive_terminal(**kw)

    def test_bridge_arm_a_variable_reaches_arm_a_stop(self):
        # [RED at 0b6da00] The reducer must NOT block at the V0 gate
        # (V0_INVALID_BLOCKED); it must reach the Arm-A walk and stop
        # the ladder with the frozen ARM_A_STOPS_LADDER reason.
        fixture, _ = self._fixture("vary")
        out = self._derive(fixture)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertTrue(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])
        v0 = out.get("v0") or {}
        self.assertEqual(v0.get("admission"), "amendment-008-bridge")
        self.assertEqual(v0.get("reachability_source"), "arm-a-bridge")
        arm_a = (out.get("arms") or {}).get("A-vulkan-necessity") or {}
        self.assertEqual(arm_a.get("reachability_source"), "arm-a-bridge")

    def test_bridge_arm_a_deterministic_reaches_arm_a_stop(self):
        # [RED at 0b6da00] Deterministic bridge Arm-A result: same
        # reach, same stop — no LOCALIZED, no UNRESOLVED, no B fetch.
        fixture, _ = self._fixture("det")
        out = self._derive(fixture)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T0.BLOCKED)
        self.assertTrue(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])
        arm_a = (out.get("arms") or {}).get("A-vulkan-necessity") or {}
        self.assertEqual(arm_a.get("reachability_source"), "arm-a-bridge")

    def test_bridge_admission_never_requests_same_head_v0_dispatch(self):
        # The bridge path must not consult d250-arm-v0-amd at the
        # current head — the fetcher above RAISES for that namespace,
        # so any live V0 authority request would surface as
        # V0_INVALID_BLOCKED, never ARM_A_STOPS_LADDER.
        fixture, _ = self._fixture("vary")
        calls = []

        inner = fixture.fetch_all()

        def counting_fetch(repo_root, expected_head, ns, github_api=None):
            calls.append(ns)
            if ns == D.V0_NAMESPACE:
                raise D.DiagnosticError(
                    "no live dispatch authority for namespace "
                    f"{D.V0_NAMESPACE}")
            return inner(repo_root, expected_head, ns, github_api)

        kw = dict(
            evidence_root=fixture.evidence, expected_head=fixture.head,
            repo_root=fixture.repo,
            authority_fetcher=counting_fetch,
            contrast_root=fixture.contrast_root,
        )
        with mock.patch.object(T0, "verify_v0_historical_rows",
                               return_value=dict(fixture.v0_history)):
            out = T0.derive_terminal(**kw)
        self.assertTrue(
            any(T0.ARM_A_STOPS_LADDER in p for p in out["problems"]),
            out["problems"])
        self.assertNotIn(D.V0_NAMESPACE, calls,
                         "bridge admission fetched same-head V0 authority")


if __name__ == "__main__":
    unittest.main()
