"""Evidence-regeneration and static-discipline checks for issue #200 (R8-F)."""
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue200_r8f_proof as proof
import issue200_r8f_rpc_cache_mechanism as cache_mechanism
import issue200_r8f_terminal_reduction as reduction


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_cache_finding(**overrides):
    finding = {
        "schema": "inferswarm.issue200.rpc-cache-mechanical-finding/1",
        "pinned_llama_cpp_commit": cache_mechanism.PINNED_LLAMA_CPP_COMMIT,
        "measured": {"cold_set_phase_bytes_sent": 12583546, "warm_restart_set_phase_bytes_sent": 321,
                     "prestaged_set_phase_bytes_sent": 321, "wrong_content_get_exit_code": 2,
                     "truncated_get_exit_code": 2},
        "cold_exceeded_hash_threshold": True,
        "durable_cache_reuse_suppresses_retransmission": True,
        "prestaged_verified_backing_consumed_without_prior_network_pass": True,
        "upstream_cache_is_fail_open_on_wrong_or_truncated_content": True,
        "case_classification": "C",
        "case_classification_meaning": "existing cache can consume pre-staged backing with a bounded external adapter, no llama.cpp modification",
        "legal_non_runtime_modifying_seam_exists": True,
        "requires_external_provenance_verification_before_cache_population": True,
        "non_claim_fnv1a_is_not_inferswarm_trust_authority": "test",
        "boundary_condition_not_proven": "test",
    }
    finding.update(overrides)
    return finding


def valid_physical_phase5_document(**overrides):
    doc = {
        "schema": reduction.PHYSICAL_PHASE5_SCHEMA,
        "participants": ["p1", "p2"],
        "accepted_release_hashes_matched": True,
        "provenance_verified": True,
        "identical_required_state_and_placement": True,
        "zero_reacquisition_bytes_measured": True,
        "network_bytes_remote_cold_arm": 12345,
        "network_bytes_local_verified_arm": 0,
        "network_bytes_local_verified_arm_repeat": 0,
    }
    doc.update(overrides)
    return doc


class CommittedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = ROOT / proof.AREA / "evidence"
        self.retained = {name: json.loads((self.evidence / name).read_text())
                         for name in proof.EVIDENCE_FILES}
        self.retained["terminal-reduction.json"] = json.loads(
            (self.evidence / "terminal-reduction.json").read_text())

    def test_all_evidence_documents_present(self):
        extra = {"terminal-reduction.json", "MANIFEST.sha256", "rpc-cache-mechanism.json",
                 "rpc-cache-experiment.json"}
        for name in proof.EVIDENCE_FILES | extra:
            self.assertTrue((self.evidence / name).is_file(), name)

    def test_manifest_covers_and_matches_every_retained_path(self):
        listed = {}
        for line in (self.evidence / "MANIFEST.sha256").read_text().splitlines():
            digest, path = line.split("  ", 1)
            self.assertNotIn(path, listed)
            listed[path] = digest
        for path, digest in listed.items():
            self.assertEqual(sha(ROOT / path), digest, path)
        for producer in proof.PRODUCERS:
            self.assertIn(producer, listed)
        self.assertIn(str(proof.AREA / "README.md"), listed)

    def test_terminal_reduction_regenerates_identically(self):
        document, _ = reduction.reduce_terminal()

        def normalize(value):
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items() if k != "temporary_root"}
            if isinstance(value, list):
                return [normalize(v) for v in value]
            return value

        self.assertEqual(normalize(document), normalize(self.retained["terminal-reduction.json"]))

    def test_committed_terminal_is_physical_verification_required_incomplete(self):
        document = self.retained["terminal-reduction.json"]
        self.assertEqual(document["terminal"], "R8F_PHYSICAL_VERIFICATION_REQUIRED_INCOMPLETE")
        self.assertTrue(document["compact_source_policy_seam_pass"])
        self.assertFalse(document["physical_phase5_ran"])
        self.assertTrue(document["cache_mechanism_finding"]["legal_non_runtime_modifying_seam_exists"])
        self.assertEqual(document["cache_mechanism_finding"]["case_classification"], "C")
        self.assertIsNotNone(document["physical_phase5_handoff"])

    def test_all_arms_and_negative_controls_recorded(self):
        arms = self.retained["arms.json"]
        for arm in ("L1", "L2", "R1", "LREQ", "RREQ", "policy_never_changes_required_state"):
            self.assertIn(arm, arms)
        controls = self.retained["negative-controls.json"]
        self.assertEqual(len(controls), 12, sorted(controls))


class FreshCampaignTests(unittest.TestCase):
    def test_campaign_regenerates_and_all_checks_pass(self):
        documents = proof.run_campaign()
        summary = documents["canonical-summary.json"]
        self.assertTrue(summary["all_arms_passed"])
        self.assertTrue(summary["all_negative_controls_failed_closed"])
        self.assertEqual(documents["isolation.json"]["network_operations"], [])
        self.assertEqual(documents["isolation.json"]["process_operations"], [])
        self.assertEqual(documents["isolation.json"]["outside_root_paths"], [])

    def test_campaign_is_deterministic_across_runs(self):
        first = proof.run_campaign()
        second = proof.run_campaign()

        def normalize(value):
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items() if k != "temporary_root"}
            if isinstance(value, list):
                return [normalize(v) for v in value]
            return value

        self.assertEqual(normalize(first), normalize(second))


class StaticDisciplineTests(unittest.TestCase):
    def test_upstream_source_identity_hashes_are_well_formed_sha256(self):
        """A truncated or malformed hash is never a valid sha256 digest; this
        network-free check catches transcription corruption in
        UPSTREAM_SOURCE_IDENTITY even though re-fetching the real upstream
        files to confirm the value itself is correct is out of scope for the
        standard CPU suite."""
        for path, entry in cache_mechanism.UPSTREAM_SOURCE_IDENTITY.items():
            digest = entry["sha256"]
            self.assertEqual(len(digest), 64, f"{path}: sha256 must be 64 hex chars, got {len(digest)}")
            self.assertRegex(digest, r"^[0-9a-f]{64}$", f"{path}: sha256 must be lowercase hex")

    def test_proof_stack_imports_only_stdlib_and_accepted_modules(self):
        allowed = set(sys.stdlib_module_names) | {
            "issue74_methodology", "issue99_artifact_core", "issue101_orchestration",
            "issue200_r8f_source_policy", "issue200_r8f_fixture", "issue200_r8f_proof",
            "issue200_r8f_terminal_reduction", "issue200_r8f_rpc_cache_mechanism"}
        for name in ("issue200_r8f_proof.py", "issue200_r8f_terminal_reduction.py"):
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertTrue(modules <= allowed, modules - allowed)
            self.assertFalse(modules & {"socket", "subprocess", "torch", "triton"})

    def test_phase4_finding_is_mechanically_derived_not_authored(self):
        """The Phase 4 launch-configuration finding must be re-derivable from
        the committed R8-D v2 launch-orchestration source; this test fails if
        that source ever changes to actually give an RPC backend a model path
        or a -c/--cache flag. This finding is intentionally narrow (see
        retraction_note): it no longer drives any answer about whether a
        participant-local-backing seam exists at all -- that is
        cache_mechanism_finding's job, tested separately below."""
        finding = reduction.phase4_mechanical_finding()
        self.assertTrue(finding["client_process_receives_model_path_argument"])
        self.assertFalse(finding["rpc_backend_process_receives_model_path_argument"])
        self.assertFalse(finding["rpc_backend_process_receives_cache_flag"])
        self.assertIn("retraction_note", finding)
        self.assertNotIn("answer_1_can_remote_participant_materialize_from_own_local_backing_without_client_retransmission",
                         finding)

    def test_cache_mechanism_finding_is_mechanically_derived_from_retained_experiment(self):
        """The corrected Phase 4 answer must be re-derivable from the
        retained, checked-in RPC cache experiment evidence (built and run
        against the actual pinned ggml-rpc-server binary); this is not an
        authored conclusion."""
        finding = reduction.cache_mechanism_finding()
        self.assertEqual(finding["case_classification"], "C")
        self.assertTrue(finding["legal_non_runtime_modifying_seam_exists"])
        self.assertTrue(finding["durable_cache_reuse_suppresses_retransmission"])
        self.assertTrue(finding["prestaged_verified_backing_consumed_without_prior_network_pass"])
        self.assertTrue(finding["upstream_cache_is_fail_open_on_wrong_or_truncated_content"])
        self.assertTrue(finding["requires_external_provenance_verification_before_cache_population"])
        # Re-derive independently from the raw retained numbers to prove this
        # isn't just trusting the stored finding's own booleans.
        evidence = ROOT / proof.AREA / "evidence"
        experiment = json.loads((evidence / "rpc-cache-experiment.json").read_text())
        phases = experiment["phases"]
        cold = phases["A_cold"]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]
        warm = phases["B_warm_restart"]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]
        prestaged = phases["C_prestaged"]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]
        self.assertGreater(cold, cache_mechanism.HASH_THRESHOLD_BYTES)
        self.assertLess(warm, cache_mechanism.SMALL_RESPONSE_THRESHOLD_BYTES)
        self.assertLess(prestaged, cache_mechanism.SMALL_RESPONSE_THRESHOLD_BYTES)
        self.assertEqual(phases["D_wrong_content"]["result"]["exit_code"], 2)
        self.assertEqual(phases["E_truncated"]["result"]["exit_code"], 2)

    def test_terminal_reduction_never_claims_physical_arm_ran(self):
        document, _ = reduction.reduce_terminal()
        self.assertFalse(document["physical_phase5_ran"])
        self.assertNotIn("staged_bytes", document)
        self.assertNotIn("network_bytes", document)


class TerminalReductionFailClosedTests(unittest.TestCase):
    """Mutation/negative tests proving the terminal reducer fails closed:
    PASS requires validated physical evidence, PREREQUISITE requires the
    cache seam to be mechanically shown insufficient (never a default), and
    a missing cache-mechanism evaluation must surface loudly rather than
    silently resolving to a guess."""

    def test_legal_seam_plus_no_physical_evidence_cannot_pass(self):
        with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                               return_value=valid_cache_finding()):
            document, _ = reduction.reduce_terminal()
        self.assertNotEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertEqual(document["terminal"], reduction.TERMINAL_PHYSICAL_VERIFICATION_REQUIRED_INCOMPLETE)

    def test_missing_physical_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as td:
            missing_path = Path(td) / "physical-phase5.json"
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=missing_path)
        self.assertNotEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertFalse(document["physical_phase5_ran"])

    def test_invalid_or_mismatched_physical_evidence_cannot_pass(self):
        cases = [
            {},  # missing every required field
            valid_physical_phase5_document(schema="wrong-schema"),
            valid_physical_phase5_document(provenance_verified=False),
            valid_physical_phase5_document(zero_reacquisition_bytes_measured=False),
        ]
        for bad_doc in cases:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "physical-phase5.json"
                path.write_text(json.dumps(bad_doc))
                with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                       return_value=valid_cache_finding()):
                    document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
                self.assertNotEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS,
                                    bad_doc)
                self.assertFalse(document["physical_phase5_ran"], bad_doc)

    def test_valid_physical_evidence_enables_pass(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "physical-phase5.json"
            path.write_text(json.dumps(valid_physical_phase5_document()))
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
        self.assertEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertTrue(document["physical_phase5_ran"])

    def test_no_physical_evidence_and_no_legal_seam_is_runtime_prerequisite(self):
        with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                               return_value=valid_cache_finding(
                                   case_classification="D",
                                   legal_non_runtime_modifying_seam_exists=False,
                                   durable_cache_reuse_suppresses_retransmission=False,
                                   prestaged_verified_backing_consumed_without_prior_network_pass=False)):
            document, _ = reduction.reduce_terminal()
        self.assertEqual(document["terminal"], reduction.TERMINAL_RUNTIME_LOCAL_BACKING_PREREQUISITE)

    def test_runtime_prerequisite_never_emitted_when_cache_seam_not_evaluated(self):
        """If the cache-mechanism evidence cannot be evaluated at all (e.g. its
        retained experiment file is missing), the reducer must fail loudly
        rather than silently falling back to R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE
        -- that terminal may only be emitted once the seam has actually been
        mechanically evaluated and shown insufficient."""
        with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                               side_effect=AssertionError("evidence missing")):
            with self.assertRaises(AssertionError):
                reduction.reduce_terminal()


if __name__ == "__main__":
    unittest.main()
