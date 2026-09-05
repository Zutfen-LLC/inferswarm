import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
EVIDENCE = ROOT / 'docs/implementation/plan-driven-artifact-acquisition-99/evidence'
sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import sha256_file  # noqa: E402

import issue99_proof as proof  # noqa: E402
from issue99_artifact_core import self_digest  # noqa: E402


def strip_volatile(value):
    """Remove timing/path fields that legitimately vary between runs.

    ``endpoint`` varies because the authorized loopback test source binds an
    ephemeral port; ``authorization_digest`` covers that endpoint, so it is
    volatile for the same reason. Everything else must be identical.
    """
    if isinstance(value, dict):
        return {
            key: strip_volatile(item)
            for key, item in value.items()
            if key not in ("wall_time_seconds", "timings_seconds", "fixture_paths",
                           "cache_root", "endpoint", "authorization_digest", "detail")
        }
    if isinstance(value, list):
        return [strip_volatile(item) for item in value]
    return value


class FreshCampaignTests(unittest.TestCase):
    """Re-run the canonical campaign and prove its passing shape."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue99-proof-test-")
        cls.out = Path(cls.temp.name) / "evidence"
        cls.summary = proof.run_campaign(cls.out)
        cls.documents = {
            path.name: json.loads(path.read_text())
            for path in cls.out.glob("*.json")
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_terminal_disposition_is_pass_with_zero_invariants(self):
        self.assertEqual(self.summary["terminal_disposition"],
                         "PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS")
        zero = self.summary["zero_invariants"]
        self.assertEqual(zero["unrelated_model_bytes_acquired_for_realization"], 0)
        self.assertEqual(zero["unexplained_full_model_dependency"], 0)
        for arm, status in self.summary["arms"].items():
            self.assertTrue(status in (True, "PASS"), (arm, status))

    def test_canonical_participant_began_without_local_repository(self):
        canonical = self.summary["canonical_participant"]
        self.assertEqual(canonical["participant_id"], "exec.a")
        self.assertTrue(canonical["begins_without_complete_local_model_repository"])
        self.assertEqual(canonical["initial_verified_cache_bytes"], 0)
        arm = self.summary["accounting"]["canonical_arm_only"]
        self.assertEqual(arm["newly_acquired_bytes"], canonical["required_artifact_bytes"])
        self.assertEqual(arm["verified_cache_hit_bytes"], 0)
        self.assertEqual(arm["restart_arm"]["newly_acquired_bytes"], 0)
        self.assertEqual(arm["restart_arm"]["verified_cache_hit_bytes"],
                         canonical["required_artifact_bytes"])
        second = arm["second_participant"]
        self.assertGreater(second["newly_acquired_bytes"], 0)
        self.assertGreater(second["verified_cache_hit_bytes"], 0)

    def test_every_required_negative_control_failed_closed(self):
        controls = self.documents["negative-controls.json"]["controls"]
        expected = {
            "corrupt_transfer_data": "INTEGRITY_DIGEST_MISMATCH",
            "wrong_provenance_identity": "PROVENANCE_IDENTITY_MISMATCH",
            "missing_required_artifact": "SOURCE_OBJECT_UNAVAILABLE",
            "unauthorized_source": "SOURCE_UNAUTHORIZED",
            "foreign_partial_state_discarded": "PARTIAL_STATE_IDENTITY_MISMATCH",
            "unverified_object_read_refused": "UNVERIFIED_SOURCE_READ_REFUSED",
            "wrong_digest_publication_refused": "INTEGRITY_DIGEST_MISMATCH",
            "incomplete_lsu_coverage": "REQUIRED_STATE_COVERAGE_INCOMPLETE",
            "whole_model_injection": "UNDECLARED_REQUIREMENT_ARTIFACT",
            "unplanned_staging_fetch": "STAGING_UNPLANNED_KEY",
            "no_complete_repository_feasibility_assumption": "STRUCTURAL_ABSENCE",
        }
        self.assertEqual(set(controls), set(expected))
        for name, reason in expected.items():
            control = controls[name]
            self.assertEqual(control["outcome"], "FAIL_CLOSED_EXPECTED", name)
            self.assertEqual(control["observed_reason"], reason, name)
        self.assertTrue(self.documents["negative-controls.json"]["all_fail_closed"])

    def test_interrupted_transfer_resumed_from_bound_prefix(self):
        evidence = self.documents["interrupted-transfer.json"]
        self.assertEqual(evidence["retained_partial_bytes"], 6000)
        self.assertEqual(evidence["resume_transferred_bytes"],
                         evidence["artifact_length"] - 6000)
        self.assertTrue(evidence["resumed_from_bound_prefix"])
        self.assertTrue(evidence["post_resume_execution_matches_oracle"])
        self.assertEqual(evidence["reconciliation"], "PLANNED_AND_REALIZED")
        aggregate = self.documents["acquisition-ledger.json"]["aggregate"]
        self.assertEqual(aggregate["resume_reused_prefix_bytes"], 6000)
        self.assertEqual(aggregate["retry_resume_transfer_bytes"], 10384)

    def test_coordinator_never_holds_bulk_bytes_and_one_source_served_all(self):
        self.assertEqual(self.summary["coordinator"]["bytes_observed"], 0)
        self.assertFalse(self.summary["coordinator"]["bulk_bytes_transit_required"])
        by_source = self.documents["acquisition-ledger.json"]["aggregate"][
            "acquired_bytes_by_source"]
        self.assertEqual(set(by_source), {"operator-http-local"})

    def test_unrelated_upstream_objects_never_requested(self):
        accounting = self.summary["accounting"]
        self.assertEqual(accounting["unrelated_upstream_objects_requested"], [])
        ranges = accounting["upstream_shard_range_requests"]
        required_shards = ("model-00001-of-00002.safetensors",
                           "model-00002-of-00002.safetensors")
        # Required shards were only ever accessed via explicit Range requests;
        # unrelated upstream objects were never requested at all.
        for shard in required_shards:
            self.assertGreater(len(ranges[shard]), 0, shard)
            for request in ranges[shard]:
                self.assertTrue(request["range_header"].startswith("bytes="),
                                (shard, request))
        for shard in ("vision-adapter.safetensors", "mtp-head.safetensors"):
            self.assertEqual(ranges[shard], [])

    def test_deterministic_frozen_identities(self):
        with tempfile.TemporaryDirectory() as rerun:
            second = proof.run_campaign(Path(rerun) / "evidence")
        self.assertEqual(second["plan_digest"], self.summary["plan_digest"])
        self.assertEqual(second["requirements_digest"],
                         self.summary["requirements_digest"])
        self.assertEqual(second["provenance"]["fixture_catalog_digest"],
                         self.summary["provenance"]["fixture_catalog_digest"])
        self.assertEqual(second["provenance"]["oracle_workload_digest"],
                         self.summary["provenance"]["oracle_workload_digest"])
        self.assertEqual(second["model_identity"], self.summary["model_identity"])
        self.assertEqual(strip_volatile(second), strip_volatile(self.summary))

    def test_frozen_documents_regenerate_byte_identically(self):
        with tempfile.TemporaryDirectory() as rerun:
            out = Path(rerun) / "evidence"
            proof.run_campaign(out)
            for name in ("source-catalog.json", "frozen-plan.json",
                         "participant-requirements.json"):
                self.assertEqual(
                    (self.out / name).read_bytes(), (out / name).read_bytes(), name)


class CommittedEvidenceTests(unittest.TestCase):
    """Verify the retained committed proof area end to end."""

    def test_all_evidence_documents_present(self):
        for name in proof.EVIDENCE_FILES:
            self.assertTrue((EVIDENCE / name).is_file(), name)
        self.assertTrue((EVIDENCE / "MANIFEST.sha256").is_file())

    def test_manifest_covers_and_matches_every_retained_path(self):
        lines = (EVIDENCE / "MANIFEST.sha256").read_text().splitlines()
        self.assertGreater(len(lines), len(proof.EVIDENCE_FILES))
        listed = set()
        for line in lines:
            digest, _, rel = line.partition("  ")
            path = ROOT / rel
            self.assertTrue(path.is_file(), rel)
            self.assertEqual(sha256_file(path), digest, rel)
            listed.add(rel)
        for name in proof.EVIDENCE_FILES:
            self.assertIn(f"docs/implementation/plan-driven-artifact-acquisition-99/"
                          f"evidence/{name}", listed)
        for required in ("scripts/issue99_artifact_core.py",
                         "scripts/issue99_mini_model.py",
                         "scripts/issue99_proof.py",
                         "tests/test_issue99_artifact_core.py",
                         "tests/test_issue99_proof.py"):
            self.assertIn(required, listed)
        methodology = ROOT / ("docs/implementation/plan-driven-artifact-acquisition-99/"
                              "methodology.md")
        if methodology.is_file():
            self.assertIn("docs/implementation/plan-driven-artifact-acquisition-99/"
                          "methodology.md", listed)

    def test_committed_summary_records_passing_terminal_disposition(self):
        summary = json.loads((EVIDENCE / "canonical-summary.json").read_text())
        self.assertEqual(summary["terminal_disposition"],
                         "PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS")
        self.assertEqual(summary["zero_invariants"], {
            "unrelated_model_bytes_acquired_for_realization": 0,
            "unexplained_full_model_dependency": 0,
        })
        self.assertTrue(all(status in (True, "PASS")
                            for status in summary["arms"].values()))
        self.assertEqual(summary["coordinator"]["bytes_observed"], 0)
        self.assertTrue(summary["issue97_isolation"]["cpu_only"])
        self.assertFalse(summary["issue97_isolation"]["freetoken_tree_modified"])
        self.assertTrue(summary["non_claims"])

    def test_committed_producer_shas_match_live_scripts(self):
        summary = json.loads((EVIDENCE / "canonical-summary.json").read_text())
        producers = summary["provenance"]["producer_programs"]
        self.assertEqual(set(producers), {
            "issue99_artifact_core.py", "issue99_mini_model.py", "issue99_proof.py"})
        for name, digest in producers.items():
            self.assertEqual(digest, sha256_file(SCRIPTS / name), name)

    def test_committed_frozen_documents_match_a_fresh_campaign(self):
        with tempfile.TemporaryDirectory() as rerun:
            out = Path(rerun) / "evidence"
            proof.run_campaign(out)
            for name in ("source-catalog.json", "frozen-plan.json",
                         "participant-requirements.json"):
                self.assertEqual((EVIDENCE / name).read_bytes(),
                                 (out / name).read_bytes(), name)
            committed = json.loads((EVIDENCE / "canonical-summary.json").read_text())
            fresh = json.loads((out / "canonical-summary.json").read_text())
            self.assertEqual(strip_volatile(fresh), strip_volatile(committed))

    def test_requirement_manifest_is_self_consistent(self):
        requirements = json.loads((EVIDENCE / "participant-requirements.json").read_text())
        self.assertEqual(requirements["requirements_digest"],
                         self_digest(requirements))
        for participant in requirements["participants"]:
            self.assertEqual(participant["participant_requirements_digest"],
                             self_digest(participant))
            declared = (participant["required_logical_state"]["assigned"]
                        + participant["required_logical_state"]["declared_shared"]
                        + participant["required_logical_state"]["required_metadata"])
            covered = sorted({state for record in participant["required_artifacts"]
                              for state in record["satisfies_logical_state_ids"]})
            self.assertEqual(covered, sorted(declared), participant["participant_id"])
            self.assertEqual(participant["required_artifact_bytes"],
                             sum(r["length"] for r in participant["required_artifacts"]))

    def test_manifest_detects_tampering(self):
        summary_path = EVIDENCE / "canonical-summary.json"
        manifest_digest = None
        for line in (EVIDENCE / "MANIFEST.sha256").read_text().splitlines():
            digest, _, rel = line.partition("  ")
            if rel.endswith("evidence/canonical-summary.json"):
                manifest_digest = digest
        self.assertIsNotNone(manifest_digest)
        with tempfile.TemporaryDirectory() as temp:
            tampered = Path(temp) / "canonical-summary.json"
            raw = bytearray(summary_path.read_bytes())
            raw[-3] ^= 0x01
            tampered.write_bytes(bytes(raw))
            self.assertNotEqual(sha256_file(tampered), manifest_digest)
            self.assertEqual(sha256_file(summary_path), manifest_digest)


class StaticDisciplineTests(unittest.TestCase):
    def test_proof_stack_imports_stdlib_only(self):
        forbidden = {'torch', 'transformers', 'triton', 'cuda', 'safetensors', 'numpy'}
        for name in ('issue99_artifact_core.py', 'issue99_mini_model.py',
                     'issue99_proof.py'):
            tree = ast.parse((SCRIPTS / name).read_text())
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split('.')[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split('.')[0])
            self.assertFalse(modules & forbidden, (name, modules & forbidden))

    def test_model_nouns_stay_out_of_the_generic_core(self):
        core_text = (SCRIPTS / 'issue99_artifact_core.py').read_text().lower()
        for forbidden in ('safetensors', 'qwen', 'gemma', 'huggingface',
                          'has_complete_model_repository'):
            self.assertNotIn(forbidden, core_text)

    def test_strategy_boundary_holds_model_specific_knowledge(self):
        mini_text = (SCRIPTS / 'issue99_mini_model.py').read_text()
        for model_noun in ('embed_tokens', 'lm_head', 'rope.freqs', 'safetensors',
                           'attn_in.weight'):
            self.assertIn(model_noun, mini_text)
        core_text = (SCRIPTS / 'issue99_artifact_core.py').read_text()
        for model_noun in ('embed_tokens', 'lm_head', 'attn_in', 'layers.'):
            self.assertNotIn(model_noun, core_text)


if __name__ == "__main__":
    unittest.main()
