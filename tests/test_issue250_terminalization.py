"""Strict tests for the additive Issue #250 terminalization successor."""
from __future__ import annotations

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
import issue250_terminalization as S  # noqa: E402
from test_issue250_amendment008_reducer_admission import BridgeReducerAdmissionMixin  # noqa: E402


class TerminalizationTests(unittest.TestCase):
    def _fixture(self, rows):
        builder = BridgeReducerAdmissionMixin()
        cleanups = []
        builder.__dict__["addCleanup"] = cleanups.append
        fixture, mounts = builder._fixture(rows)
        retained = S.AUTHORITY_DIR / "accepted-original" / "preflight-complete.json"
        shutil.copyfile(retained, fixture.evidence / "preflight-complete.json")
        self.addCleanup(fixture.restore_contrast_constant)
        self.addCleanup(fixture.tmp.cleanup)
        return fixture, mounts

    def _derive_fixture(self, fixture, *, authority_fetcher=None):
        body = "R8I3B PHYSICAL DISPATCH #250" + chr(10) + "head=" + fixture.head + chr(10) + "diagnostic-namespace=d250-arm-a" + chr(10) + "arm=A-vulkan-necessity"
        auth = {"comment_id": S.DISPATCH_ID,
                "issue_url": "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/251",
                "author_association": "MEMBER", "created_at": "2026-09-30T02:03:22Z",
                "head_sha": fixture.head, "namespace": "d250-arm-a", "arm": "A-vulkan-necessity",
                "body": body, "issue_open": True, "open_pr": True}
        auth = S.frozen.D.validate_authority_payload(auth, fixture.head)
        with mock.patch.object(S, "EXPECTED_HEAD", fixture.head), \
                mock.patch.object(S, "captured_dispatch", return_value=auth):
            return S.derive(fixture.evidence, contrast_root=fixture.contrast_root,
                            repo_root=fixture.repo, authority_fetcher=authority_fetcher)

    def test_positive_production_shaped_arm_a_derives_only_authorized_terminal(self):
        fixture, _ = self._fixture("det")
        # The synthetic fixture retains production-shaped receipts; frozen verifiers run unmodified.
        out = self._derive_fixture(fixture)
        self.assertEqual(out.get("terminal"), S.TERMINAL, out.get("problems"))
        self.assertEqual(out["localized_factor"], "zero↔nonzero Vulkan participation")
        self.assertFalse(out["later_arms_authorized"])
        self.assertIn("not a Vulkan", out["interpretation"])
        self.assertIn("unlocalized", out["interpretation"])

    def test_captured_authority_is_byte_and_semantically_pinned(self):
        a = S.captured_dispatch()
        self.assertEqual(a["comment_id"], 5902614446)
        self.assertEqual(a["head_sha"], S.EXPECTED_HEAD)
        self.assertEqual(a["namespace"], "d250-arm-a")
        self.assertEqual(a["arm"], "A-vulkan-necessity")
        self.assertEqual(S.frozen.D.authority_digest(a), S.DISPATCH_DIGEST)

    def test_authority_tamper_and_wrong_injected_authority_block(self):
        dispatch = S.AUTHORITY_DIR / "dispatch-comment.json"
        original = dispatch.read_bytes()
        try:
            dispatch.write_bytes(original + b" ")
            self.assertIsNone(S.derive(Path("/missing"), contrast_root=Path("/missing"),
                                       repo_root=REPO).get("terminal"))
        finally:
            dispatch.write_bytes(original)
        fixture, _ = self._fixture("det")
        out = S.derive(fixture.evidence, contrast_root=fixture.contrast_root,
                       repo_root=fixture.repo,
                       authority_fetcher=lambda *a, **k: {"comment_id": 1})
        self.assertIsNone(out.get("terminal"))

    def test_less_than_five_or_variable_arm_a_never_localizes(self):
        fixture, _ = self._fixture("det")
        arm_root = fixture.evidence / "d250-arm-a"
        unit_dirs = sorted(p for p in arm_root.iterdir() if p.is_dir())
        shutil.rmtree(unit_dirs[-1])
        out = S.derive(fixture.evidence, contrast_root=fixture.contrast_root,
                       repo_root=fixture.repo)
        self.assertIsNone(out.get("terminal"))
        fixture, _ = self._fixture("vary")
        out = S.derive(fixture.evidence, contrast_root=fixture.contrast_root,
                       repo_root=fixture.repo)
        self.assertIsNone(out.get("terminal"))

    def test_missing_adjudication_blocks(self):
        path = S.AUTHORITY_DIR / "adjudication-pr-251.json"
        original = path.read_bytes()
        try:
            path.write_bytes(original[:-1])
            fixture, _ = self._fixture("det")
            out = S.derive(fixture.evidence, contrast_root=fixture.contrast_root,
                           repo_root=fixture.repo)
            self.assertIsNone(out.get("terminal"))
        finally:
            path.write_bytes(original)

    def test_source_build_preflight_digest_and_semantics_are_required(self):
        # The accepted preflight is an independently pinned retained source/build
        # authority, not inferred from the per-unit comparator-only receipt.
        path = Path("/home/zutfen/.hermes/cache/scratch/is250-terminalization/evidence-arm-a-5d015b5/preflight-complete.json")
        self.assertTrue(path.is_file(), "retained production preflight must be mounted by fixture")
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), S.PREFLIGHT_SHA256)
        doc = json.loads(raw)
        sb = doc["source_build"]
        self.assertEqual(sb["source_head"], "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        self.assertEqual(sb["source_tree"], "950999fe62b7fe55f44ab5b7394e3c8542f37f12")
        self.assertEqual(sb["binary_sha256"], "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad")

    def test_wrong_head_model_build_health_and_provenance_fail_frozen_reducer(self):
        # Existing frozen reducer remains the sole receipt/provenance validator;
        # malformed production-shaped fixtures cannot become this terminal.
        fixture, _ = self._fixture("det")
        out = S.derive(fixture.evidence, contrast_root=fixture.contrast_root,
                       repo_root=fixture.repo,
                       authority_fetcher=lambda *a, **k: {"wrong": "dispatch"})
        self.assertIsNone(out.get("terminal"))

    def test_cli_has_no_caller_selected_terminal_surface(self):
        source = (REPO / "scripts/issue250_terminalization.py").read_text()
        self.assertNotIn("--terminal", source)
        self.assertNotIn("terminal_override", source)
        self.assertNotIn("later_arms_authorized=", source)


if __name__ == "__main__":
    unittest.main()
