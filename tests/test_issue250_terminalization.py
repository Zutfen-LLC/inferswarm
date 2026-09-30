"""Production-admission regressions for accepted Issue #250 terminalization.

Synthetic rows/build bytes use the repository's existing production-shaped
fixture builders. Only independently frozen DIGEST/identity constants are
rebound to the synthetic authorities; no reader/reducer is bypassed.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
import issue250_terminalization as S
from test_issue250_amendment008_reducer_admission import BridgeReducerAdmissionMixin


class TerminalizationTests(unittest.TestCase):
    def _fixture(self, rows="det"):
        # Pass the real TestCase so every model/digest patch has its cleanup.
        fixture, _ = BridgeReducerAdmissionMixin._fixture(self, rows)
        # This legacy fixture patch is unused by bridge admission. Remove it
        # explicitly: the successor must run every consumed frozen reader.
        fixture.v0_historical_patch.stop()
        authority = copy.deepcopy(fixture.fetch_all()(fixture.repo, fixture.head, "d250-arm-a", None))
        authdir = fixture.root / "terminalization-authority"
        authdir.mkdir()
        patches = {"AUTHORITY_DIR": authdir, "EXPECTED_HEAD": fixture.head,
                   "ORIGINAL_HEAD": fixture.head,
                   "DISPATCH_ID": authority["comment_id"],
                   "DISPATCH_DIGEST": S.frozen.D.authority_digest(authority),
                   "COMPARATOR_SHA256": S.frozen.D.SERVER_BINARIES["comparator"]}
        names = (("adjudication-pr-251.json", "PR_ADJUDICATION_SHA256"),
                 ("adjudication-issue-250.json", "ISSUE_ADJUDICATION_SHA256"))
        for name, pin in names:
            doc = json.loads((S.AUTHORITY_DIR / name).read_bytes())
            doc["body"] = doc["body"].replace(S.ORIGINAL_HEAD, fixture.head)
            raw = json.dumps(doc, sort_keys=True).encode()
            (authdir / name).write_bytes(raw)
            patches[pin] = hashlib.sha256(raw).hexdigest()
        comment = json.loads((S.AUTHORITY_DIR / "dispatch-comment.json").read_bytes())
        comment.update(id=authority["comment_id"], body=authority["body"],
                       created_at=authority["created_at"])
        raw = json.dumps(comment, sort_keys=True).encode()
        (authdir / "dispatch-comment.json").write_bytes(raw)
        patches["DISPATCH_SHA256"] = hashlib.sha256(raw).hexdigest()
        raw = json.dumps(authority, sort_keys=True).encode()
        (authdir / "dispatch-authority.json").write_bytes(raw)
        patches["AUTHORITY_SHA256"] = hashlib.sha256(raw).hexdigest()
        preflight = json.loads((S.AUTHORITY_DIR / "accepted-original/preflight-complete.json").read_bytes())
        preflight["head"] = fixture.head
        preflight["source_build"]["binary_sha256"] = patches["COMPARATOR_SHA256"]
        raw = json.dumps(preflight, sort_keys=True).encode()
        (fixture.evidence / "preflight-complete.json").write_bytes(raw)
        patches["PREFLIGHT_SHA256"] = hashlib.sha256(raw).hexdigest()
        for name, value in patches.items():
            self.enterContext(mock.patch.object(S, name, value))
        return fixture

    def _derive(self, f, **kwargs):
        return S.derive(f.evidence, contrast_root=f.contrast_root,
                        repo_root=f.repo, **kwargs)

    def _positive(self, f):
        out = self._derive(f)
        self.assertEqual(out.get("terminal"), S.TERMINAL, out.get("problems"))
        return out

    def _blocked(self, f, *, frozen_reason=None, **kwargs):
        out = self._derive(f, **kwargs)
        self.assertIsNone(out.get("terminal"))
        self.assertEqual(out["status"], "BLOCKED")
        if frozen_reason is not None:
            reasons = out.get("frozen_result", {}).get("problems", [])
            self.assertTrue(any(frozen_reason in p for p in reasons), reasons)
        return out

    def _unit(self, f, index=1):
        return f.evidence / "d250-arm-a" / f"case-3072-B-devnone-{index:03d}"

    def _mutate_receipt(self, f, change, index=1):
        p = self._unit(f, index) / "unit.json"
        doc = json.loads(p.read_bytes())
        change(doc)
        p.write_text(json.dumps(doc))

    def test_positive_production_shaped_arm_a_derives_only_authorized_terminal(self):
        out = self._positive(self._fixture())
        self.assertEqual(out["frozen_result"]["arms"]["A-vulkan-necessity"]["cpu_only_devnone"]["population"], "complete_deterministic")
        self.assertEqual(out["frozen_result"]["arms"]["A-vulkan-necessity"]["cpu_only_devnone"]["n"], 5)

    def test_terminal_records_exact_factor_without_root_cause(self):
        out = self._positive(self._fixture())
        self.assertEqual(out["localized_factor"], "zero↔nonzero Vulkan participation")
        self.assertIn("not a Vulkan, driver, device, kernel, vendor, or mechanism root-cause claim", out["interpretation"])
        self.assertIn("Implementation fix below this boundary remains unlocalized", out["interpretation"])
        self.assertFalse(out["later_arms_authorized"])

    def test_four_identical_cpu_repeats_cannot_localize(self):
        f = self._fixture()
        self._positive(f)
        shutil.rmtree(self._unit(f, 5))
        out = self._blocked(f)
        a = out["frozen_result"]["arms"]["A-vulkan-necessity"]
        self.assertEqual(a["cpu_only_devnone"]["n"], 4)
        self.assertEqual(a["cpu_only_devnone"]["population"], "incomplete")

    def test_cpu_only_mismatch_never_localizes(self):
        f = self._fixture("vary")
        out = self._blocked(f)
        a = out["frozen_result"]["arms"]["A-vulkan-necessity"]
        self.assertTrue(a["cpu_only_devnone"]["nondeterministic"])
        self.assertEqual(out["frozen_result"]["problems"], [S.frozen.ARM_A_STOPS_LADDER])

    def test_uniformly_wrong_provenance_rejects(self):
        f = self._fixture()
        self._positive(f)
        for i in range(1, 6):
            self._mutate_receipt(f, lambda r: r.update(reachability_source="historical-v0-amd-variable"), i)
        self._blocked(f, frozen_reason="provenance does not match")

    def test_mixed_provenance_rejects(self):
        f = self._fixture()
        self._positive(f)
        self._mutate_receipt(f, lambda r: r.update(reachability_source="historical-v0-amd-variable"))
        self._blocked(f)

    def test_missing_arm_a_receipt_rejects(self):
        f = self._fixture()
        self._positive(f)
        (self._unit(f) / "unit.json").unlink()
        self._blocked(f, frozen_reason="malformed retained unit")

    def test_tampered_arm_a_receipt_rejects(self):
        f = self._fixture()
        self._positive(f)
        self._mutate_receipt(f, lambda r: r.update(observer_rows=["0" * 64] * 8))
        self._blocked(f, frozen_reason="row")

    def test_wrong_execution_head_in_receipt_rejects(self):
        f = self._fixture()
        self._positive(f)
        self._mutate_receipt(f, lambda r: r["authority"].update(head_sha="0" * 40))
        self._blocked(f, frozen_reason="authority")

    def test_stale_execution_head_in_opening_attestation_rejects(self):
        f = self._fixture()
        self._positive(f)
        p = f.evidence / "model-attestation-open.json"
        d = json.loads(p.read_bytes())
        d["head_sha"] = "0" * 40
        p.write_text(json.dumps(d))
        self._blocked(f, frozen_reason="attestation")

    def test_wrong_dispatch_in_receipt_rejects(self):
        f = self._fixture()
        self._positive(f)
        self._mutate_receipt(f, lambda r: r["authority"].update(comment_id=999))
        self._blocked(f, frozen_reason="authority")

    def test_wrong_injected_dispatch_is_not_admitted(self):
        f = self._fixture()
        self._positive(f)
        out = self._blocked(f, authority_fetcher=lambda *a: {"comment_id": 999})
        self.assertIn("injected authority differs", str(out["frozen_result"]["problems"]))

    def test_missing_accepted_248_contrast_rejects(self):
        f = self._fixture()
        self._positive(f)
        shutil.rmtree(f.contrast_root)
        self._blocked(f, frozen_reason="contrast")

    def test_malformed_health_raw_custody_rejects(self):
        f = self._fixture()
        self._positive(f)
        p = self._unit(f) / "kernel-journal.raw"
        p.write_bytes(p.read_bytes() + b"tamper")
        self._blocked(f, frozen_reason="health")

    def test_malformed_model_custody_rejects(self):
        f = self._fixture()
        self._positive(f)
        self._mutate_receipt(f, lambda r: r.update(model_attestation_sha256="0" * 64))
        self._blocked(f, frozen_reason="attestation")

    def test_malformed_comparator_build_custody_rejects(self):
        f = self._fixture()
        self._positive(f)
        self._mutate_receipt(f, lambda r: r.update(binary_sha256="0" * 64))
        self._blocked(f, frozen_reason="binary")

    def test_malformed_source_preflight_rejects(self):
        f = self._fixture()
        self._positive(f)
        p = f.evidence / "preflight-complete.json"
        d = json.loads(p.read_bytes())
        d["source_build"]["source_head"] = "malformed"
        p.write_text(json.dumps(d))
        out = self._blocked(f)
        self.assertIn("source/build preflight digest mismatch", str(out["problems"]))

    def test_missing_source_preflight_rejects(self):
        f = self._fixture()
        self._positive(f)
        (f.evidence / "preflight-complete.json").unlink()
        self._blocked(f)

    def test_missing_adjudication_rejects(self):
        f = self._fixture()
        self._positive(f)
        (S.AUTHORITY_DIR / "adjudication-pr-251.json").unlink()
        self._blocked(f)

    def test_tampered_adjudication_rejects(self):
        f = self._fixture()
        self._positive(f)
        p = S.AUTHORITY_DIR / "adjudication-issue-250.json"
        p.write_bytes(p.read_bytes() + b" ")
        self._blocked(f)

    def test_tampered_captured_dispatch_rejects(self):
        f = self._fixture()
        self._positive(f)
        p = S.AUTHORITY_DIR / "dispatch-comment.json"
        p.write_bytes(p.read_bytes() + b" ")
        self._blocked(f)

    def test_no_later_arm_evidence_or_authority_needed(self):
        f = self._fixture()
        self.assertEqual([p.name for p in f.evidence.glob("d250-arm-*")], ["d250-arm-a"])
        calls = []
        def reader(root, head, namespace, github_api):
            calls.append(namespace)
            return S.captured_dispatch()
        self._positive(f)
        out = self._derive(f, authority_fetcher=reader)
        self.assertEqual(out["terminal"], S.TERMINAL)
        self.assertEqual(calls, ["d250-arm-a"])

    def test_historical_bridge_remains_at_original_fail_closed_stop(self):
        f = self._fixture()
        self._positive(f)
        old = S.frozen.derive_terminal(f.evidence, f.head, repo_root=f.repo,
                                      authority_fetcher=f.fetch_all(), contrast_root=f.contrast_root)
        self.assertIsNone(old["terminal"])
        self.assertEqual(old["problems"], [S.frozen.ARM_A_STOPS_LADDER])
        (f.evidence / S.frozen.D.ARM_A_BRIDGE_NAME).write_text("{}")
        self._blocked(f, frozen_reason="bridge admission rejected")

    def test_caller_cannot_select_terminal(self):
        self.assertNotIn("terminal", inspect.signature(S.derive).parameters)
        with self.assertRaises(TypeError):
            S.derive(Path("."), contrast_root=Path("."), repo_root=REPO, terminal=S.TERMINAL)
        result = subprocess.run([sys.executable, str(REPO / "scripts/issue250_terminalization.py"),
                                 ".", "--contrast-root", ".", "--terminal", S.TERMINAL], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"unrecognized arguments", result.stderr)

    def test_original_wrapper_identifier_value_anomaly_is_preserved(self):
        area = S.AUTHORITY_DIR / "accepted-original"
        failure = json.loads((area / "reducer-failure.json").read_bytes())
        summary = json.loads((area / "execution-summary.json").read_bytes())
        self.assertEqual(summary["failure"]["classification"], "REDUCTION_FAILURE")
        self.assertIn("['ARM_A_STOPS_LADDER']", failure["traceback"])
        self.assertNotEqual(S.frozen.ARM_A_STOPS_LADDER, "ARM_A_STOPS_LADDER")
        self.assertEqual(summary["reducer_result"]["problems"], [S.frozen.ARM_A_STOPS_LADDER])
        self.assertIsNone(summary["reducer_result"]["terminal"])

    def test_nonzero_arm_a_launch_is_rejected_by_frozen_reader(self):
        f = self._fixture()
        self._positive(f)
        def change(receipt):
            argv = receipt["server_argv"]
            argv[argv.index("-ngl") + 1] = "1"
        self._mutate_receipt(f, change)
        self._blocked(f, frozen_reason="argv")

    def test_arm_a_launch_without_dev_none_is_rejected(self):
        f = self._fixture()
        self._positive(f)
        def change(receipt):
            argv = receipt["server_argv"]
            i = argv.index("-dev")
            del argv[i:i + 2]
        self._mutate_receipt(f, change)
        self._blocked(f, frozen_reason="argv")

    def test_wrong_contrast_ngl_rejects_even_after_manifest_resigning(self):
        f = self._fixture()
        self._positive(f)
        tag = S.frozen.D.CONTRAST_UNITS[0]
        rel = S.frozen.D.CONTRAST_NAMESPACE + "/" + tag + "/unit.json"
        receipt = f.contrast_root / rel
        doc = json.loads(receipt.read_bytes())
        doc["ngl"] = 0
        receipt.write_text(json.dumps(doc))
        manifest = f.contrast_root / "SHA256SUMS"
        lines = manifest.read_text().splitlines()
        digest = hashlib.sha256(receipt.read_bytes()).hexdigest()
        manifest.write_text("\n".join(
            digest + "  " + rel if line.split(None, 1)[1].strip() == rel else line
            for line in lines) + "\n")
        # Rebind only the synthetic manifest's independent digest. The real
        # frozen ngl/case reader still runs and rejects the semantic forgery.
        with mock.patch.object(S.frozen.D, "ACCEPTED_248_MANIFEST_SELF_DIGEST",
                               hashlib.sha256(manifest.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(ValueError, "contrast unit binding mismatch"):
                S.frozen.verify_historical_contrast(f.contrast_root)
            self._blocked(f)

    def test_contradictory_adjudication_cannot_survive_byte_pin(self):
        f = self._fixture()
        self._positive(f)
        p = S.AUTHORITY_DIR / "adjudication-pr-251.json"
        doc = json.loads(p.read_bytes())
        doc["body"] += "\nContradiction: terminalization is not authorized."
        p.write_text(json.dumps(doc, sort_keys=True))
        out = self._blocked(f)
        self.assertIn("authority byte digest mismatch", str(out["problems"]))

    def test_real_captured_authority_is_byte_and_semantically_pinned(self):
        S.validate_adjudications()
        a = S.captured_dispatch()
        self.assertEqual(a["comment_id"], 5902614446)
        self.assertEqual(a["head_sha"], "5d015b5bc437bb82d5e966d0da8b90ff44b079a1")
        self.assertEqual(S.frozen.D.authority_digest(a), "70843356c497c3537eade2cec7767e56601954cc5fa083a3dce73d37aca5697b")
        source = S.verify_source_build(S.AUTHORITY_DIR / "accepted-original")
        self.assertEqual(source["source_head"], S.SOURCE_HEAD)


if __name__ == "__main__":
    unittest.main()
