"""Evidence-regeneration and static-discipline checks for issue #200 (R8-F)."""
import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue200_r8f_proof as proof
import issue200_r8f_terminal_reduction as reduction


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CommittedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = ROOT / proof.AREA / "evidence"
        self.retained = {name: json.loads((self.evidence / name).read_text())
                         for name in proof.EVIDENCE_FILES}
        self.retained["terminal-reduction.json"] = json.loads(
            (self.evidence / "terminal-reduction.json").read_text())

    def test_all_evidence_documents_present(self):
        for name in proof.EVIDENCE_FILES | {"terminal-reduction.json", "MANIFEST.sha256"}:
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

    def test_committed_terminal_is_runtime_prerequisite(self):
        self.assertEqual(self.retained["terminal-reduction.json"]["terminal"],
                         "R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE")
        self.assertTrue(self.retained["terminal-reduction.json"]["compact_source_policy_seam_pass"])
        self.assertFalse(self.retained["terminal-reduction.json"]["physical_phase5_ran"])

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
    def test_proof_stack_imports_only_stdlib_and_accepted_modules(self):
        allowed = set(sys.stdlib_module_names) | {
            "issue74_methodology", "issue99_artifact_core", "issue101_orchestration",
            "issue200_r8f_source_policy", "issue200_r8f_fixture", "issue200_r8f_proof",
            "issue200_r8f_terminal_reduction"}
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
        """The Phase 4 finding must be re-derivable from the committed R8-D v2
        launch-orchestration source; this test fails if that source ever
        changes to actually give an RPC backend a model path, which is
        exactly the signal that would flip R8-F's terminal."""
        finding = reduction.phase4_mechanical_finding()
        self.assertTrue(finding["client_process_receives_model_path_argument"])
        self.assertFalse(finding["rpc_backend_process_receives_model_path_argument"])
        self.assertFalse(
            finding["answer_1_can_remote_participant_materialize_from_own_local_backing_without_client_retransmission"])

    def test_terminal_reduction_never_claims_physical_arm_ran(self):
        document, _ = reduction.reduce_terminal()
        self.assertFalse(document["physical_phase5_ran"])
        self.assertNotIn("staged_bytes", document)
        self.assertNotIn("network_bytes", document)


if __name__ == "__main__":
    unittest.main()
