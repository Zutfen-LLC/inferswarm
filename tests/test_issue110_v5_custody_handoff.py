"""Issue #110 v5 custody handoff tests (CPU/static, non-decrypting)."""
import ast
import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CAMPAIGN = ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110/preflight"
V5 = ROOT / "docs/qualification/gemma4-12b-it-v5"

sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import MethodologyError, canonical_json_bytes, sha256_bytes, sha256_file  # noqa: E402
import issue110_v5_custody as custody  # noqa: E402
import build_issue110_v5_threshold_adapter as adapter_builder  # noqa: E402

ACCEPTED_MERGE = "bc6f0ec657d025702d5928771bf8f51aa563a8be"
BASELINE_CUSTODY_SHA = "6adaa4e5743cdee65f659806d81039dca499c7997cf0240ce92d48cfc2a23b46"
THRESHOLDS_TOOL_SHA = "41904b3297e06656bad8b0776f75ca42f7a05635b48fe3afe0b7330071bb0e25"
EFFECTIVE_CUSTODY_SHA = "5a1a8756a2330e7ef6658dd9114a599d165741fc7e951482a630811b755e8b6c"
ADAPTER_SHA = "99e449185c7fb96efa5a594dcfcfda01656b51d67e7136dcdb01b34d66887622"


def _completion() -> dict:
    return json.loads((CAMPAIGN / "holdout-custody-completion.json").read_text())


def _effective() -> dict:
    return json.loads((CAMPAIGN / "effective-holdout-custody-record.json").read_text())


class BaselinePreservation(unittest.TestCase):
    def test_accepted_baseline_identities_at_merge(self):
        """All brief-named baseline blobs hash to the expected values at the merge."""
        expected = {
            "docs/qualification/gemma4-12b-it-v5/manifests/holdout-custody-record.json": BASELINE_CUSTODY_SHA,
            "docs/qualification/gemma4-12b-it-v5/manifests/sealed-holdout-commitment.json": "b0dcff2a241b20cbd24f1b54f30e77a33512d8ceb12f79afc6c1761b2c994fd2",
            "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json": "b35f1915231d455cd964e9b645e58269ec63cdf483742907af39cc850f9fdb35",
            "docs/qualification/gemma4-12b-it-v5/manifests/stress-pool.json": "e54b10ae86a2bbdf805e54d6f3266785dd9805d05477978a18d5c1ad5bce0c9d",
            "docs/qualification/gemma4-12b-it-v5/manifests/stress-selection-commitment.json": "38a1da0c06f5ad6336507e107fb5deb1b278b44aed95ea78a41f647245018eac",
            "docs/qualification/gemma4-12b-it-v5/manifests/comparator-tier-contract.json": "ebba447573ea7af9faeab91e1036a780db453661fbc5eb067f6acfd78a1df5af",
            "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json": "8b840eed2b858623be6abd1bfbac1bc7f3bf3637ac7acfa383ce039137226aee",
            "docs/qualification/gemma4-12b-it-v5/manifests/statistical-derivation.json": "97fcb4c968e76d067f156d52c97124f1b52ae209ebc92d7f975c46df3e0720b5",
            "scripts/issue109_v5_thresholds.py": THRESHOLDS_TOOL_SHA,
        }
        for rel, sha in expected.items():
            self.assertEqual(sha256_file(ROOT / rel), sha, rel)

    def test_no_v5_directory_bytes_modified(self):
        """The whole accepted v5 directory tree equals the merge tree."""
        out = subprocess.run(["git", "diff", "--stat", ACCEPTED_MERGE, "--",
                              "docs/qualification/gemma4-12b-it-v5/"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "", out.stdout)

    def test_baseline_loader_rejects_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp) / "custody.json"
            bad.write_text('{"schema": "x"}')
            with self.assertRaisesRegex(MethodologyError, "baseline custody record hash mismatch"):
                custody.load_accepted_baseline(bad)


class CompletionRecordValidation(unittest.TestCase):
    def test_committed_completion_record_validates(self):
        custody.validate_completion_record(_completion())

    def test_committed_completion_record_matches_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads((CAMPAIGN / "schemas/v5-custody-completion-record.schema.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(_completion())

    def test_effective_record_is_deterministic_construction(self):
        rebuilt = custody.build_effective_custody_record(_completion())
        self.assertEqual(canonical_json_bytes(rebuilt), canonical_json_bytes(_effective()))

    def test_effective_record_hash_is_frozen(self):
        self.assertEqual(custody.effective_custody_record_sha256(_effective()), EFFECTIVE_CUSTODY_SHA)
        # file bytes == canonical bytes (unseal verifier hashes file bytes)
        self.assertEqual(sha256_file(CAMPAIGN / "effective-holdout-custody-record.json"), EFFECTIVE_CUSTODY_SHA)

    def test_effective_record_satisfies_frozen_custody_semantics(self):
        from commit_issue109_holdout import custody_is_satisfied
        record = _effective()
        self.assertTrue(custody_is_satisfied(record))
        self.assertEqual(record["holdout_state"], "SEALED_NOT_CONSUMED")
        self.assertIs(record["unseal_authorized"], False)
        self.assertEqual({c["host"] for c in record["custodians"]}, {"inferswarm01", "hermes"})

    def test_effective_record_fits_frozen_109_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads((V5 / "schemas/holdout-custody-record.schema.json").read_text())
        jsonschema.Draft202012Validator(schema).validate(_effective())


class NegativeControls(unittest.TestCase):
    def _mut(self, fn):
        record = _completion()
        fn(record)
        with self.assertRaises(MethodologyError):
            custody.validate_completion_record(record)

    def test_reject_baseline_sha_drift(self):
        self._mut(lambda r: r.update(accepted_baseline_custody_record_sha256="0" * 64))

    def test_reject_wrong_holdout_commitment(self):
        self._mut(lambda r: r.update(accepted_holdout_commitment_sha256="0" * 64))

    def test_reject_same_host_twice(self):
        self._mut(lambda r: r["custodians"][1].update(host="inferswarm01"))

    def test_reject_same_location_twice(self):
        self._mut(lambda r: r["custodians"][1].update(location=r["custodians"][0]["location"]))

    def test_reject_noncanonical_host_alias(self):
        self._mut(lambda r: r["custodians"][0].update(host="orchestrator"))

    def test_reject_placeholder_host(self):
        self._mut(lambda r: r["custodians"][0].update(host="host-a"))

    def test_reject_uppercase_host(self):
        self._mut(lambda r: r["custodians"][0].update(host="Hermes"))

    def test_reject_network_backed_hermes_storage(self):
        self._mut(lambda r: r["custodians"][1].update(backing_storage={"kind": "local", "filesystem": "nfs", "device": "/dev/fake"}))

    def test_reject_mismatched_key_sha(self):
        self._mut(lambda r: r["custodians"][1].update(private_key_sha256="0" * 64))

    def test_reject_mismatched_seed_sha(self):
        self._mut(lambda r: r["custodians"][0].update(normalized_secret_seed_sha256="0" * 64))

    def test_rereject_mismatched_public_der(self):
        self._mut(lambda r: r["custodians"][1].update(public_key_der_sha256="0" * 64))

    def test_reject_mismatched_ciphertext(self):
        self._mut(lambda r: r["accepted_identities"].update(holdout_ciphertext_sha256="0" * 64))

    def test_reject_mismatched_certificate(self):
        self._mut(lambda r: r["accepted_identities"].update(recipient_certificate_sha256="0" * 64))

    def test_reject_three_custodians(self):
        third = copy.deepcopy(_completion()["custodians"][0])
        third.update(custodian_id="x", host="inferswarm02", location="/x")
        def add(r):
            r["custodians"].append(third)
        self._mut(add)

    def test_reject_decrypt_claim(self):
        self._mut(lambda r: r.update(decrypt_performed=True))

    def test_reject_unseal_authorized_effective(self):
        record = _effective()
        record["unseal_authorized"] = True
        from verify_issue109_v5_unseal import validate_unseal_preconditions
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "effective.json"
            path.write_bytes(canonical_json_bytes(record))
            threshold = Path(temp) / "core.json"
            threshold.write_text(json.dumps({
                "schema": "inferswarm.issue109.v5-core-threshold-manifest/1",
                "holdout_state": "SEALED_NOT_CONSUMED",
                "provenance": {"holdout_custody_record_sha256": sha256_file(path)},
            }))
            with self.assertRaisesRegex(MethodologyError, "HOLDOUT_CUSTODY_NOT_VERIFIED"):
                validate_unseal_preconditions(
                    core_threshold_path=threshold,
                    expected_core_threshold_sha256=sha256_file(threshold),
                    ciphertext=V5 / "sealed/holdout.cms",
                    certificate=V5 / "sealed/recipient-certificate.pem",
                    custody_record_path=path,
                    expected_custody_record_sha256=sha256_file(path),
                    private_key_path=Path("/nonexistent"),
                )

    def test_reject_private_material_in_repository_claim(self):
        self._mut(lambda r: r.update(private_material_in_repository=True))


class ThresholdAdapter(unittest.TestCase):
    def test_adapter_sha_is_frozen(self):
        self.assertEqual(sha256_file(SCRIPTS / "issue110_v5_thresholds.py"), ADAPTER_SHA)

    def test_adapter_differs_from_109_in_exactly_one_line(self):
        src = (SCRIPTS / "issue109_v5_thresholds.py").read_text().splitlines()
        dst = (SCRIPTS / "issue110_v5_thresholds.py").read_text().splitlines()
        self.assertEqual(len(src), len(dst))
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(src, dst)) if a != b]
        self.assertEqual(len(diff), 1, diff)
        i, a, b = diff[0]
        self.assertIn("V5_HOLDOUT_CUSTODY_RECORD_SHA256", a)
        self.assertIn("V5_HOLDOUT_CUSTODY_RECORD_SHA256", b)
        self.assertIn(BASELINE_CUSTODY_SHA, a)
        self.assertIn(EFFECTIVE_CUSTODY_SHA, b)

    def test_adapter_builder_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "adapter.py"
            sha1 = adapter_builder.write_adapter(out)
            sha2 = adapter_builder.write_adapter(out)
            self.assertEqual(sha1, sha2)
            self.assertEqual(sha1, ADAPTER_SHA)

    def test_adapter_builder_rejects_source_drift(self):
        original = adapter_builder.SOURCE.read_text()
        drifted = original.replace("V5_CALIBRATION_CASES", "V5_CALIBRATION_CASES_X")
        adapter_builder.SOURCE.write_text(drifted)
        try:
            with self.assertRaisesRegex(MethodologyError, "hash drift"):
                adapter_builder.build_adapter_source(EFFECTIVE_CUSTODY_SHA)
        finally:
            adapter_builder.SOURCE.write_text(original)
        self.assertEqual(sha256_file(adapter_builder.SOURCE), THRESHOLDS_TOOL_SHA)

    def test_adapter_builder_rejects_multi_substitution_source(self):
        original = adapter_builder.SOURCE.read_text()
        drifted = original + '\nV5_HOLDOUT_CUSTODY_RECORD_SHA256 = "' + "0" * 64 + '"\n'
        with self.assertRaisesRegex(MethodologyError, "exactly one custody-record hash constant"):
            adapter_builder.build_adapter_source(EFFECTIVE_CUSTODY_SHA, source=drifted)
        self.assertEqual(sha256_file(adapter_builder.SOURCE), THRESHOLDS_TOOL_SHA)

    def test_adapter_statistical_constants_unchanged(self):
        """N/H/M/alpha, corpus, pool, commitment, and tooling constants are identical."""
        import issue109_v5_thresholds as v109
        import issue110_v5_thresholds as v110
        for constant in ("V5_CALIBRATION_CORPUS_SHA256", "V5_STRESS_POOL_SHA256", "V5_STRESS_COMMITMENT_SHA256",
                         "V5_HOLDOUT_COMMITMENT_SHA256", "V5_TOOLING_VERSION"):
            self.assertEqual(getattr(v109, constant), getattr(v110, constant), constant)
        self.assertEqual(v109.derive_v5_threshold_artifacts.__code__.co_code, v110.derive_v5_threshold_artifacts.__code__.co_code)

    def test_adapter_only_custody_hash_differs(self):
        """Every function's bytecode and every non-custody module constant are identical."""
        import types
        import issue109_v5_thresholds as v109
        import issue110_v5_thresholds as v110
        self.assertEqual(v109.V5_HOLDOUT_CUSTODY_RECORD_SHA256, BASELINE_CUSTODY_SHA)
        self.assertEqual(v110.V5_HOLDOUT_CUSTODY_RECORD_SHA256, EFFECTIVE_CUSTODY_SHA)
        skip = {"V5_HOLDOUT_CUSTODY_RECORD_SHA256"}
        names = set(dir(v109)) & set(dir(v110))
        for name in names:
            if name.startswith("_") or name in skip or name in ("V5", "ROOT"):
                continue
            a, b = getattr(v109, name), getattr(v110, name)
            if isinstance(a, types.FunctionType) and isinstance(b, types.FunctionType):
                self.assertEqual(a.__code__.co_code, b.__code__.co_code, name)
            elif isinstance(a, (str, int, float, tuple)) and not callable(a):
                self.assertEqual(a, b, name)


class ScopeAndPurity(unittest.TestCase):
    @staticmethod
    def _code_only(path: Path) -> str:
        """Source text with docstrings stripped (prose may legitimately mention scope)."""
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body[0] = ast.Pass()
        return ast.unparse(tree)

    def test_no_runtime_stack_imports(self):
        forbidden = {"torch", "transformers", "triton", "cuda", "paramiko", "fabric"}
        for name in ("issue110_v5_custody.py", "build_issue110_v5_threshold_adapter.py", "issue110_v5_thresholds.py"):
            tree = ast.parse((SCRIPTS / name).read_text())
            names = {node.names[0].name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
            names |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            self.assertFalse(names & forbidden, (name, names & forbidden))

    def test_no_decrypt_calls_in_110_sources(self):
        for name in ("issue110_v5_custody.py", "build_issue110_v5_threshold_adapter.py", "issue110_v5_thresholds.py"):
            code = self._code_only(SCRIPTS / name)
            self.assertNotIn("openssl", code, name)
            self.assertNotRegex(code, r"\bcms\b", name)
            self.assertNotRegex(code, r"decrypt\w*\s*\(", name)

    def test_no_ssh_or_subprocess_in_110_custody_sources(self):
        for name in ("issue110_v5_custody.py", "build_issue110_v5_threshold_adapter.py"):
            code = self._code_only(SCRIPTS / name)
            self.assertNotRegex(code, r"\bssh\b", name)
            self.assertNotIn("subprocess", code, name)

    def test_no_private_material_in_git(self):
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        for rel in out:
            self.assertFalse(rel.endswith(("recipient-key.pem", "secret-seed.txt")), rel)
            if rel.endswith(".pem"):
                content = (ROOT / rel).read_bytes()
                self.assertNotIn(b"PRIVATE KEY", content, rel)

    def test_campaign_scope_documentation(self):
        doc = (CAMPAIGN.parent / "README.md").read_text()
        self.assertIn("SECOND_INDEPENDENT_CUSTODY_VERIFIED", doc)
        self.assertIn("PRE_EXECUTION_CUSTODY_HANDOFF_TOOLING_REPAIR", doc)
        self.assertNotIn("orchestrator", doc)


class UnsealVerifierReuse(unittest.TestCase):
    def test_unseal_verifier_accepts_effective_record_and_stops_before_decrypt(self):
        """Synthetic e2e: #110 effective custody record + synthetic key/cert/threshold.

        Uses the real validate_unseal_preconditions from the accepted #109
        verifier with the effective custody record and a synthetic RSA keypair
        whose key hash is embedded in the record — proving the verifier
        accepts a completed custody record and stops at
        PRECONDITIONS_PASS_STOP_BEFORE_DECRYPT without any real private
        material.
        """
        from verify_issue109_v5_unseal import validate_unseal_preconditions
        import verify_issue109_v5_unseal as unseal
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            key = temp / "k.pem"
            subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True)
            cert = temp / "c.pem"
            subprocess.run(["openssl", "req", "-new", "-x509", "-key", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=test"], check=True, capture_output=True)
            ciphertext = temp / "holdout.cms"
            ciphertext.write_bytes(b"synthetic-ciphertext")
            # Synthetic commitment so the PASS path can be exercised without any
            # real private material; the real code path is untouched.
            synthetic_v5 = temp / "v5"
            (synthetic_v5 / "manifests").mkdir(parents=True)
            commitment = {
                "ciphertext_sha256": sha256_bytes(b"synthetic-ciphertext"),
                "recipient_certificate_sha256": sha256_file(cert),
            }
            (synthetic_v5 / "manifests/sealed-holdout-commitment.json").write_text(json.dumps(commitment))
            record = copy.deepcopy(_effective())
            record["custodians"][0]["private_key_sha256"] = sha256_file(key)
            record["holdout_ciphertext_sha256"] = commitment["ciphertext_sha256"]
            record["recipient_certificate_sha256"] = commitment["recipient_certificate_sha256"]
            pub_pem = subprocess.run(["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"], check=True, capture_output=True).stdout
            pub_der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pub_pem, check=True, capture_output=True).stdout
            record["recipient_public_key_der_sha256"] = sha256_bytes(pub_der)
            record_path = temp / "effective.json"
            record_path.write_bytes(canonical_json_bytes(record))
            threshold = temp / "core.json"
            threshold.write_text(json.dumps({
                "schema": "inferswarm.issue109.v5-core-threshold-manifest/1",
                "holdout_state": "SEALED_NOT_CONSUMED",
                "provenance": {"holdout_custody_record_sha256": sha256_file(record_path)},
            }))
            with patch.object(unseal, "V5", synthetic_v5):
                result = unseal.validate_unseal_preconditions(
                core_threshold_path=threshold,
                expected_core_threshold_sha256=sha256_file(threshold),
                ciphertext=ciphertext,
                certificate=cert,
                custody_record_path=record_path,
                expected_custody_record_sha256=sha256_file(record_path),
                private_key_path=key,
            )
            self.assertEqual(result["verdict"], "PRECONDITIONS_PASS_STOP_BEFORE_DECRYPT")
            self.assertEqual(result["custody_record_sha256"], sha256_file(record_path))

    def test_unseal_verifier_still_rejects_incomplete_baseline(self):
        from verify_issue109_v5_unseal import validate_unseal_preconditions
        custody_path = V5 / "manifests/holdout-custody-record.json"
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            threshold = temp / "core.json"
            threshold.write_text(json.dumps({
                "schema": "inferswarm.issue109.v5-core-threshold-manifest/1",
                "holdout_state": "SEALED_NOT_CONSUMED",
                "provenance": {"holdout_custody_record_sha256": sha256_file(custody_path)},
            }))
            with self.assertRaisesRegex(MethodologyError, "HOLDOUT_CUSTODY_NOT_VERIFIED"):
                validate_unseal_preconditions(
                    core_threshold_path=threshold,
                    expected_core_threshold_sha256=sha256_file(threshold),
                    ciphertext=V5 / "sealed/holdout.cms",
                    certificate=V5 / "sealed/recipient-certificate.pem",
                    custody_record_path=custody_path,
                    expected_custody_record_sha256=sha256_file(custody_path),
                    private_key_path=Path("/nonexistent"),
                )


if __name__ == "__main__":
    unittest.main()
