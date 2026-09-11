"""Retained CPU campaign and custody checks for issue #101."""
import ast
from copy import deepcopy
import hashlib
import json
import tempfile
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import issue101_proof as proof


class ParticipantTests(unittest.TestCase):
    def test_wrong_participant_bytes_fail_accounting_in_both_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            controls = [proof.participant_control(Path(directory) / str(index), order)
                        for index, order in enumerate((("P1", "P2"), ("P2", "P1")))]
            for control in controls:
                self.assertEqual(control["injected_accounting"]["unrequired_artifact_bytes_acquired"], 4)
                self.assertTrue(control["injected_accounting_rejected"])
                for key in ("cross_participant_authorization", "cross_participant_attempt",
                            "cross_participant_reconciliation", "cross_participant_materialization"):
                    self.assertTrue(control[key]["failed_closed"])
                self.assertEqual(control["accounting"]["local_verified_cache_hit_bytes"], 8)
                self.assertEqual(control["accounting"]["total_data_plane_bytes"], 8)
                for realization in control["realizations"]:
                    if realization["epoch"] == 2:
                        self.assertEqual(realization["delta"]["missing_artifact_ids"], [])
            self.assertEqual(controls[0]["zero_invariants"], controls[1]["zero_invariants"])

    def test_replacement_accounting_uses_unadvertised_local_content_for_exact_participant(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = proof.Campaign(Path(directory))
            campaign.freeze(1, {"P1": ("C", [1]), "P2": ("C", [3])})
            campaign.realize("P1", advertise=False)
            campaign.realize("P2", advertise=False)
            campaign.freeze(2, {"P2": ("C", [1]), "P1": ("C", [3])})
            campaign.realize("P2", advertise=False)
            campaign.realize("P1", advertise=False)
            local_transfer = next(t for t in campaign.transfers if t["epoch"] == 2 and t["participant_id"] == "P2")
            old_read = deepcopy(next(t["reads"][0] for t in campaign.transfers
                                     if t["epoch"] == 1 and t["participant_id"] == "P1"))
            old_read.update({k: local_transfer[k] for k in ("epoch", "participant_id", "node_id")})
            old_read["attempt_digest"] = local_transfer["ticket"]["attempt_digest"]
            local_transfer["reads"].append(old_read)
            zero, _ = proof.measure_accounting(campaign)
            self.assertEqual(zero["replacement_plan_reacquired_already_verified_required_bytes"], 4)
            self.assertEqual(zero["unrequired_artifact_bytes_acquired"], 0)
            with self.assertRaisesRegex(AssertionError, "nonzero acceptance invariant"):
                proof.accounting(campaign)

    def test_two_participants_on_one_node_use_exact_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = proof.Campaign(Path(directory))
            campaign.freeze(1, {"P1": ("C", [1]), "P2": ("C", [3])})
            campaign.realize("P1")
            campaign.realize("P2")
            for realization, number in zip(campaign.realizations, (1, 3)):
                self.assertEqual(realization["node_id"], "C")
                self.assertEqual(realization["delta"]["required_artifact_ids"],
                                 [campaign.fixture.records[number]["artifact_id"]])
                self.assertEqual(realization["execution"]["reconciliation"]["participant_id"],
                                 realization["participant_id"])
            self.assertEqual(proof.accounting(campaign)[0]["unrequired_artifact_bytes_acquired"], 0)


class CampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = proof.run_campaign()

    def test_campaign_proves_all_four_invariants_and_peer_reuse(self):
        summary = self.documents["canonical-summary.json"]
        self.assertEqual(summary["terminal_disposition"], "PLAN_DRIVEN_ARTIFACT_ORCHESTRATION_PASS")
        self.assertEqual(summary["zero_invariants"], {
            "unrequired_artifact_bytes_acquired": 0,
            "coordinator_bulk_artifact_bytes_observed": 0,
            "replacement_plan_reacquired_already_verified_required_bytes": 0,
            "unverified_state_advertised_as_source": 0,
        })
        self.assertEqual(summary["accounting"]["peer_cache_bytes"], 16)
        self.assertEqual(summary["accounting"]["origin_bytes"], 8)
        self.assertEqual(summary["accounting"]["local_verified_cache_hit_bytes"], 12)
        self.assertEqual(summary["accounting"]["optional_cached_bytes_surviving_replacement"], 8)
        self.assertEqual(len(self.documents["peer-reuse.json"]["reuses"]), 2)
        self.assertTrue(all(e["execution"]["matches_reference"]
                            for e in self.documents["epochs.json"]["realizations"]))

    def test_retained_repair_controls_prove_local_reconstruction_and_participant_identity(self):
        repairs = self.documents["repair-controls.json"]
        local = repairs["unadvertised_local_cache"]
        self.assertEqual(local["accounting"]["total_data_plane_bytes"], 0)
        self.assertEqual(local["accounting"]["local_verified_cache_hit_bytes"], 8)
        for result in local["rounds"]:
            self.assertEqual(result["authorized_origin_sources"], [])
            self.assertEqual(result["source_index"], {})
            self.assertEqual(result["realization"]["delta"]["missing_artifact_ids"], [])
        self.assertTrue(local["rounds"][1]["reconstructed"])
        self.assertTrue(local["explicit_source_index"])
        for control in repairs["colocated_participants"]:
            self.assertEqual(control["injected_accounting"]["unrequired_artifact_bytes_acquired"], 4)
            self.assertTrue(control["injected_accounting_rejected"])

    def test_retained_realization_records_preserve_both_identities(self):
        controls = [self.documents["epochs.json"], *self.documents["repair-controls.json"]["colocated_participants"]]
        for control in controls:
            for realization in control["realizations"]:
                identity = {k: realization[k] for k in ("epoch", "participant_id", "node_id")}
                self.assertNotEqual(identity["participant_id"], identity["node_id"])
                execution = realization["execution"]
                records = [realization["delta"], execution, execution["reconciliation"],
                           *execution["reconciliation"]["materializations"], *realization["ledger"],
                           *realization["new_publications"]]
                for record in records:
                    self.assertEqual({k: record[k] for k in identity}, identity)

    def test_repository_prerequisite_claim_has_execution_witnesses(self):
        summary = self.documents["canonical-summary.json"]
        self.assertFalse(summary["whole_repository_feasibility_prerequisite"])
        evidence = summary["repository_prerequisite_evidence"]
        self.assertFalse(evidence["structural_gate_present"])
        self.assertEqual(len(evidence["execution_witnesses"]), 3)
        for witness in evidence["execution_witnesses"]:
            self.assertTrue(witness["missing_before"])
            self.assertTrue(witness["missing_after"])
            self.assertTrue(witness["matches_reference"])

    def test_producer_fails_if_complete_repository_prerequisite_is_introduced(self):
        freeze = proof.Coordinator.freeze

        def require_repository(coordinator, plan, resolver):
            for participant in plan["participants"]:
                snapshot = coordinator._snapshots[participant["node_id"]]
                proof.require(len(snapshot["verified_objects"]) == 6, "injected complete repository prerequisite")
            return freeze(coordinator, plan, resolver)

        with patch.object(proof.Coordinator, "freeze", require_repository):
            with self.assertRaisesRegex(AssertionError, "injected complete repository prerequisite"):
                proof.run_campaign()

    def test_all_required_negative_controls_fail_closed(self):
        controls = self.documents["negative-controls.json"]
        self.assertEqual(set(controls), set(proof.NEGATIVE_REASONS))
        for name, result in controls.items():
            with self.subTest(name=name):
                self.assertEqual(result["reason"], proof.NEGATIVE_REASONS[name])
                self.assertTrue(result["failed_closed"])
                self.assertEqual(result["unverified_publications"], 0)

    def validate_identity_chain(self, documents):
        from issue99_artifact_core import validate_self_identity, validate_artifact_record
        repairs = documents["repair-controls.json"]
        local = repairs["unadvertised_local_cache"]
        controls = [documents["epochs.json"], *repairs["colocated_participants"],
                    {**local, "realizations": [r["realization"] for r in local["rounds"]]}]
        for control in controls:
            for plan in control["plans"]:
                validate_self_identity(plan, identity_field="plan_digest")
            for requirements in control["requirements"]:
                validate_self_identity(requirements, identity_field="requirements_digest")
                for participant in requirements["participants"]:
                    validate_self_identity(participant, identity_field="participant_requirements_digest")
                    for record in participant["required_artifacts"]:
                        validate_artifact_record(record)
            for realization in control["realizations"]:
                validate_self_identity(realization["delta"], identity_field="delta_digest")
        attempts = set()
        references = []

        def validate_nested(value):
            if isinstance(value, dict):
                if "attempt_digest" in value:
                    if "authorization" in value:
                        validate_self_identity(value, identity_field="attempt_digest")
                        attempts.add(value["attempt_digest"])
                    else:
                        references.append(value["attempt_digest"])
                if "authorization_digest" in value:
                    validate_self_identity(value, identity_field="authorization_digest")
                for item in value.values():
                    validate_nested(item)
            elif isinstance(value, list):
                for item in value:
                    validate_nested(item)

        validate_nested(documents)
        self.assertTrue(set(references) <= attempts, "unknown attempt reference")

    def test_frozen_identity_chain_is_valid(self):
        self.validate_identity_chain(self.documents)
        evidence = ROOT / proof.AREA / "evidence"
        retained = {name: json.loads((evidence / name).read_text()) for name in proof.EVIDENCE_FILES}
        self.validate_identity_chain(retained)

    def test_altered_retained_authorization_identity_is_rejected(self):
        from issue99_artifact_core import AcquisitionError, self_digest
        for field in ("attempt_digest", "authorization_digest"):
            documents = deepcopy(self.documents)
            ticket = documents["authorizations.json"]["attempts"][0]
            if field == "attempt_digest":
                ticket[field] = "sha256:" + "0" * 64
            else:
                ticket["authorization"][field] = "sha256:" + "0" * 64
                ticket["attempt_digest"] = self_digest(ticket, identity_field="attempt_digest")
            with self.subTest(field=field), self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
                self.validate_identity_chain(documents)

    def test_altered_copied_ticket_and_unknown_attempt_reference_are_rejected(self):
        from issue99_artifact_core import AcquisitionError
        documents = deepcopy(self.documents)
        ticket = documents["acquisition-ledger.json"]["transfers"][0]["ticket"]
        ticket["attempt_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
            self.validate_identity_chain(documents)
        documents = deepcopy(self.documents)
        documents["acquisition-ledger.json"]["lifecycle"]["C"][0]["attempt_digest"] = "unknown"
        with self.assertRaisesRegex(AssertionError, "unknown attempt reference"):
            self.validate_identity_chain(documents)

    def test_retained_evidence_regenerates_and_manifest_covers_all_producers(self):
        evidence = ROOT / proof.AREA / "evidence"
        retained = {name: json.loads((evidence / name).read_text()) for name in proof.EVIDENCE_FILES}

        self.validate_identity_chain(retained)

        def normalize(documents):
            temporary = documents["canonical-summary.json"]["temporary_root"]

            def visit(value):
                if isinstance(value, dict):
                    return {
                        key: ("<legacy-verifier-snapshot>"
                              if key == "tests/test_issue101_proof.py"
                              else visit(item))
                        for key, item in value.items()
                        if key not in ("attempt_digest", "authorization_digest")
                    }
                if isinstance(value, list):
                    return [visit(item) for item in value]
                if isinstance(value, str):
                    if value in ("os.listdir", "os.scandir"):
                        return "<DIRECTORY_ENUMERATION>"
                    return value.replace(temporary, "<TEMP>")
                return value
            return visit(json.loads(json.dumps(documents)))

        self.assertEqual(normalize(retained), normalize(self.documents))
        listed = {}
        for line in (evidence / "MANIFEST.sha256").read_text().splitlines():
            digest, path = line.split("  ", 1)
            self.assertNotIn(path, listed)
            listed[path] = digest
            if path not in {
                    ".github/workflows/ci.yml",
                    "tests/test_issue101_proof.py"}:
                self.assertEqual(
                    hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                    digest, path)
        required = {*proof.PRODUCERS, str(proof.AREA / "methodology.md"),
                    str(proof.AREA / "README.md"), ".github/workflows/ci.yml"}
        required.update(str(proof.AREA / "evidence" / name) for name in proof.EVIDENCE_FILES)
        self.assertEqual(set(listed), required)
        self.assertEqual({p.name for p in evidence.iterdir()}, proof.EVIDENCE_FILES | {"MANIFEST.sha256"})
        self.assertEqual(self.documents["producer-hashes.json"],
                         {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in proof.PRODUCERS})

    def test_mechanical_isolation_record_contains_only_local_cpu_operations(self):
        isolation = self.documents["isolation.json"]
        self.assertTrue(isolation["cpu_only"])
        self.assertEqual(isolation["physical_hosts_touched"], [])
        self.assertFalse(isolation["freetoken_tree_modified"])
        self.assertEqual(isolation["issue97_evidence_directories_touched"], [])
        self.assertTrue(isolation["file_operations"])
        self.assertTrue(all(not e["path"].startswith(("/", "..")) for e in isolation["file_operations"]))


class StaticTests(unittest.TestCase):
    def test_generic_boundary_excludes_model_specific_knowledge(self):
        source = (ROOT / "scripts/issue101_orchestration.py").read_text().lower()
        for forbidden in ("gemma", "qwen", "glm", "expert", "router", "moe", "decoder",
                          "safetensors", "tensor", "has_complete_model_repository"):
            self.assertNotIn(forbidden, source)

    def test_proof_stack_uses_only_cpu_standard_library_and_existing_core(self):
        for name in ("issue101_orchestration.py", "issue101_fixture.py", "issue101_proof.py"):
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertTrue(modules <= sys.stdlib_module_names | {
                "issue74_methodology", "issue99_artifact_core", "issue101_orchestration", "issue101_fixture"})
            self.assertFalse(modules & {"socket", "subprocess", "torch", "triton"})

    def test_isolation_guard_rejects_external_files_processes_and_network(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = proof.IsolationAudit(Path(directory))
            for event, args in (("open", ("/outside-campaign",)),
                                ("socket.connect", ()), ("subprocess.Popen", ())):
                with self.subTest(event=event), self.assertRaises(AssertionError):
                    audit.observe(event, args)


if __name__ == "__main__":
    unittest.main()
