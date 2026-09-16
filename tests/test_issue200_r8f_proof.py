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
import issue200_r8f_physical as physical


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


def _receipt(root, name, document):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, sort_keys=True).encode()
    path.write_bytes(payload)
    return {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}


def valid_physical_phase5_document(root, **overrides):
    authority = physical.accepted_model_authority()
    node_id = "inferswarm03"
    binary = physical.accepted_rpc_binary_authority()[node_id]
    payload_bytes = b"r8-f-observed-payload"
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    payload_path = "raw/payload.bin"
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / payload_path).write_bytes(payload_bytes)
    payload = {"offset": 0, "length": len(payload_bytes), "sha256": payload_sha,
               "fnv1a_cache_key": physical.fnv1a64(payload_bytes)}

    def arm(name, policy, source, immutable_bytes):
        network = _receipt(root, f"raw/{name}.network.json", {
            "schema": "inferswarm.issue200.network-receipt/1", "arm": name,
            "source_attribution": source,
            "events": [{"classification": "immutable_model_payload", "bytes": immutable_bytes},
                       {"classification": "rpc_control_or_hash_probe", "bytes": 17}],
        })
        runtime = _receipt(root, f"raw/{name}.runtime.json", {"arm": name, "schema": "raw-runtime/1",
                   "participants": [node_id], "required_state_identity": "sha256:state",
                   "participant_requirements_identity": "sha256:requirements",
                   "placement_identity": "sha256:placement", "materialization_identity": "sha256:materialization",
                   "initialization_wall_time_ms": 1.0, "set_tensor_payloads": [payload]})
        reads = _receipt(root, f"raw/{name}.reads.json", {"arm": name, "schema": "raw-reads/1",
                   "source_attribution": source})
        result = {"source_policy": policy, "source_attribution": source,
                  "participants": [node_id], "required_state_identity": "sha256:state",
                  "participant_requirements_identity": "sha256:requirements",
                  "placement_identity": "sha256:placement",
                  "materialization_identity": "sha256:materialization",
                  "initialization_wall_time_ms": 1.0, "network_receipt": network,
                  "runtime_receipt": runtime, "local_read_receipt": reads,
                  "set_tensor_payloads": [payload]}
        if name != "cold_remote":
            cache_dir = f"/private/{name}"
            initialized = _receipt(root, f"raw/{name}.cache-init.json", {
                "schema": "inferswarm.issue200.cache-initialization-receipt/1", "arm": name,
                "cache_dir": cache_dir, "entries_before": [],
            })
            result["private_cache_dir"] = cache_dir
            result["cache_initialization_receipt"] = initialized
            staging = _receipt(root, f"raw/{name}.staging.json", {
                "schema": "inferswarm.issue200.cache-staging-receipt/1", "arm": name,
                "atomic_publish": True, "cache_sha256": payload_sha, "payload_path": payload_path,
            })
            result["cache_staging"] = [{
                "accepted_artifact_range": {"member": authority["members"][0]["file"], "offset": 0,
                                            "length": len(payload_bytes), "sha256": payload_sha},
                "set_tensor_payload": payload,
                "staged_cache": {"path": f"{cache_dir}/{payload['fnv1a_cache_key']}",
                                 "sha256_before": payload_sha, "sha256_after": payload_sha,
                                 "length_before": len(payload_bytes), "length_after": len(payload_bytes),
                                 "receipt": staging},
            }]
        return result

    doc = {
        "schema": reduction.PHYSICAL_PHASE5_SCHEMA,
        "accepted_model_members": authority["members"], "accepted_total_bytes": authority["total_bytes"],
        "runtime": {"llama_cpp_commit": physical.PINNED_LLAMA_CPP_COMMIT,
                    "source_files": cache_mechanism.UPSTREAM_SOURCE_IDENTITY,
                    "binaries": [{"node_id": node_id, "binary": "ggml-rpc-server", "sha256": binary}]},
        "participants": [{"node_id": node_id, "rpc_endpoint": "100.77.187.38:50052",
                          "rpc_command": "ggml-rpc-server -H 0.0.0.0 -p 50052 -c /private/cache"}],
        "frozen": {"required_state_identity": "sha256:state",
                   "participant_requirements_identity": "sha256:requirements",
                   "placement_identity": "sha256:placement",
                   "materialization_identity": "sha256:materialization"},
        "arms": {
            "cold_remote": arm("cold_remote", "PREFER_REMOTE_AUTHORIZED", "REMOTE_AUTHORIZED", len(payload_bytes)),
            "local_verified": arm("local_verified", "REQUIRE_LOCAL_VERIFIED", "LOCAL_VERIFIED", 0),
            "repeat_local_verified": arm("repeat_local_verified", "REQUIRE_LOCAL_VERIFIED", "LOCAL_VERIFIED", 0),
        },
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

    def test_committed_campaign_is_explicitly_nonterminal_pending_phase5(self):
        document = self.retained["terminal-reduction.json"]
        self.assertIsNone(document["terminal"])
        self.assertEqual(document["status"], "PHASE5_REQUIRED")
        self.assertTrue(document["incomplete"])
        self.assertTrue(document["compact_source_policy_seam_pass"])
        self.assertFalse(document["physical_phase5_ran"])
        self.assertTrue(document["cache_mechanism_finding"]["legal_non_runtime_modifying_seam_exists"])
        self.assertEqual(document["cache_mechanism_finding"]["case_classification"], "C")
        self.assertIsNotNone(document["physical_phase5_handoff"])

    def test_all_arms_and_negative_controls_recorded(self):
        arms = self.retained["arms.json"]
        for arm in ("L1", "L2", "R1", "LREQ", "RREQ"):
            self.assertIn(arm, arms)
        invariance = self.retained["materialization-invariance.json"]
        self.assertEqual(invariance["local_verified"]["materialization_identity"],
                         invariance["remote_authorized"]["materialization_identity"])
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
            "issue200_r8f_terminal_reduction", "issue200_r8f_rpc_cache_mechanism",
            "issue200_r8f_physical"}
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
    """PASS is derived from raw receipts; it is never an authored boolean."""

    def test_legal_seam_plus_no_physical_evidence_cannot_pass(self):
        with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                               return_value=valid_cache_finding()):
            document, _ = reduction.reduce_terminal()
        self.assertNotEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertIsNone(document["terminal"])
        self.assertEqual(document["status"], "PHASE5_REQUIRED")

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
            {"schema": "wrong-schema"},
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
            path.write_text(json.dumps(valid_physical_phase5_document(Path(td))))
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
        self.assertEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertTrue(document["physical_phase5_ran"])

    def _rejects_pass_after_mutation(self, mutate):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            doc = valid_physical_phase5_document(root)
            mutate(doc, root)
            path = root / "physical-phase5.json"
            path.write_text(json.dumps(doc))
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                result, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
            self.assertNotEqual(result["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
            self.assertFalse(result["physical_phase5_ran"])

    def test_required_physical_mutations_reject_pass(self):
        mutations = [
            lambda d, r: d["arms"]["local_verified"]["network_receipt"].update(
                _receipt(r, "raw/local_verified.network.json", {"schema": "inferswarm.issue200.network-receipt/1",
                 "arm": "local_verified", "source_attribution": "LOCAL_VERIFIED",
                 "events": [{"classification": "immutable_model_payload", "bytes": 1}]})),
            lambda d, r: d["arms"]["repeat_local_verified"]["network_receipt"].update(
                _receipt(r, "raw/repeat_local_verified.network.json", {"schema": "inferswarm.issue200.network-receipt/1",
                 "arm": "repeat_local_verified", "source_attribution": "LOCAL_VERIFIED",
                 "events": [{"classification": "immutable_model_payload", "bytes": 1}]})),
            lambda d, r: d["arms"]["local_verified"].__setitem__("placement_identity", "sha256:drift"),
            lambda d, r: d["arms"]["local_verified"].__setitem__("required_state_identity", "sha256:drift"),
            lambda d, r: d["arms"]["local_verified"].__setitem__("materialization_identity", "sha256:drift"),
            lambda d, r: d["accepted_model_members"].pop(),
            lambda d, r: d["accepted_model_members"][0].__setitem__("sha256", "0" * 64),
            lambda d, r: d["accepted_model_members"][0].__setitem__("bytes", 1),
            lambda d, r: d["participants"].clear(),
            lambda d, r: d["arms"]["local_verified"]["runtime_receipt"].update(
                _receipt(r, "raw/local_verified.runtime.json", {"arm": "local_verified",
                 "schema": "raw-runtime/1", "participants": []})),
            lambda d, r: d["arms"]["local_verified"].pop("source_attribution"),
            lambda d, r: d["arms"]["repeat_local_verified"].__setitem__(
                "private_cache_dir", d["arms"]["local_verified"]["private_cache_dir"]),
            lambda d, r: d["arms"]["local_verified"]["cache_staging"][0]["staged_cache"].__setitem__("sha256_after", "0" * 64),
            lambda d, r: d["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]["receipt"].__setitem__("path", "raw/missing.json"),
            lambda d, r: d["arms"]["local_verified"]["network_receipt"].__setitem__("path", "raw/missing.json"),
            lambda d, r: d.__setitem__("zero_reacquisition_bytes_measured", True),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self._rejects_pass_after_mutation(mutation)

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
