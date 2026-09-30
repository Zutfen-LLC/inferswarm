"""Fail-closed offline controls for Issue #252 Phase 0."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue252_constants as C
import issue252_phase0 as P


class Phase0Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.area_rel = C.TERMINALIZATION_REL
        src = REPO / self.area_rel
        shutil.copytree(src, self.root / self.area_rel)
        self.area_patch = mock.patch.object(C, "TERMINALIZATION_REL", self.area_rel)
        self.area_patch.start()
        self.addCleanup(self.area_patch.stop)
        self.readme_rel = self.area_rel + "/README.md"

    def _copy_manifest_rows(self):
        area = self.root / self.area_rel
        for line in (area / "MANIFEST.sha256").read_text().splitlines():
            _, rel = line.split("  ", 1)
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dst)

    LLAMA = Path(os.environ.get("LLAMA_SRC", "/home/zutfen/llama.cpp-252"))

    def _llama_available(self) -> bool:
        return self.LLAMA.is_dir()

    def _assert_real_reconcile(self):
        if not self._llama_available():
            self.skipTest("pinned llama.cpp source unavailable (LLAMA_SRC)")
        result = P.derive_reconciliation(REPO, self.LLAMA,
                                         expected_base=C.EXPECTED_BASE_HEAD)
        self.assertEqual(result["status"], "RECONCILED")
        self.assertFalse(result["physical_execution"])
        return result

    def test_positive_real_repository_and_llama_pin(self):
        result = self._assert_real_reconcile()
        self.assertEqual(result["predecessor"]["terminal"], C.PREDECESSOR_TERMINAL)
        self.assertEqual(result["accepted_248_contrast_authority"]["manifest_self_digest"], C.ACCEPTED_248_MANIFEST_SELF_DIGEST)
        self.assertEqual(result["llama_cpp_pin"]["head"], C.LLAMA_PIN)

    def test_tampered_manifest_row_has_specific_error(self):
        self._copy_manifest_rows()
        path = self.root / (self.area_rel + "/MANIFEST.sha256")
        path.write_text(path.read_text().replace("1dc32c4", "0dc32c4", 1))
        with self.assertRaisesRegex(P.ReconciliationError, "manifest digest mismatch"):
            P._parse_manifest(self.root, path)

    def test_tampered_terminal_json_caught_by_manifest(self):
        # A mutated TERMINAL.json on disk must be caught by the terminalization
        # MANIFEST digest check (fail-closed) regardless of which semantic
        # field changed.
        self._copy_manifest_rows()
        import json
        area = self.root / self.area_rel
        d = json.loads((area / "TERMINAL.json").read_bytes())
        d["terminal"] = "WRONG"
        (area / "TERMINAL.json").write_text(json.dumps(d))
        with self.assertRaisesRegex(P.ReconciliationError, "manifest digest mismatch"):
            P.verify_terminalization(self.root)

    def test_wrong_terminal_name_has_specific_error(self):
        import json
        area = self.root / self.area_rel
        d = json.loads((area / "TERMINAL.json").read_bytes())
        d["terminal"] = "WRONG"
        (area / "TERMINAL.json").write_text(json.dumps(d))
        with mock.patch.object(P, "_parse_manifest",
                               lambda root, manifest: [{"path": "stub", "sha256": "0" * 64}]):
            with self.assertRaisesRegex(P.ReconciliationError, "terminal name mismatch"):
                P.verify_terminalization(self.root)

    def test_wrong_source_pin_has_specific_error(self):
        import json
        area = self.root / self.area_rel
        d = json.loads((area / "TERMINAL.json").read_bytes())
        d["source_build"]["source_head"] = "0" * 40
        (area / "TERMINAL.json").write_text(json.dumps(d))
        with mock.patch.object(P, "_parse_manifest",
                               lambda root, manifest: [{"path": "stub", "sha256": "0" * 64}]):
            with self.assertRaisesRegex(P.ReconciliationError, "llama.cpp pin"):
                P.verify_terminalization(self.root)

    def test_wrong_execution_head_has_specific_error(self):
        import json
        area = self.root / self.area_rel
        da = area / "dispatch-authority.json"
        d = json.loads(da.read_bytes())
        d["head_sha"] = "0" * 40
        da.write_text(json.dumps(d))
        with mock.patch.object(P, "_parse_manifest",
                               lambda root, manifest: [{"path": "stub", "sha256": "0" * 64}]):
            with self.assertRaisesRegex(P.ReconciliationError, "accepted predecessor execution head"):
                P.verify_terminalization(self.root)

    def test_tampered_dispatch_body_has_specific_error(self):
        import json
        area = self.root / self.area_rel
        da = area / "dispatch-authority.json"
        d = json.loads(da.read_bytes())
        d["body"] = "R8I3B PHYSICAL DISPATCH #250\nhead=" + "0" * 40
        da.write_text(json.dumps(d))
        with mock.patch.object(P, "_parse_manifest",
                               lambda root, manifest: [{"path": "stub", "sha256": "0" * 64}]):
            with self.assertRaisesRegex(P.ReconciliationError, "head binding missing"):
                P.verify_terminalization(self.root)

    def test_missing_artifact_has_specific_error(self):
        path = self.root / (self.area_rel + "/TERMINAL.json")
        with self.assertRaisesRegex(P.ReconciliationError, "manifest artifact missing"):
            P._parse_manifest(self.root, self.root / (self.area_rel + "/MANIFEST.sha256"))

    def test_tampered_digest_occurrence_has_specific_error(self):
        with mock.patch.object(C, "REFERENCE_PATHS", (self.readme_rel,)):
            data = (REPO / self.readme_rel).read_bytes().replace(C.ACCEPTED_248_MANIFEST_SELF_DIGEST.encode(), b"f" * 64)
            with mock.patch.object(P, "_show", return_value=data):
                with self.assertRaisesRegex(P.ReconciliationError, "manifest digest constant occurrence missing"):
                    P.verify_contrast_authority(REPO)

    def test_wrong_repository_base_fails_closed(self):
        # A base that is not a valid ancestor of HEAD must fail closed (the
        # exact message shape depends on git object validity; both paths raise
        # ReconciliationError before any authentication proceeds).
        with self.assertRaises(P.ReconciliationError):
            P.derive_reconciliation(REPO, self.LLAMA, expected_base="0" * 40)


if __name__ == "__main__":
    unittest.main()
