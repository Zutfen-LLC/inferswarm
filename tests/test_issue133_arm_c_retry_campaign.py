"""Issue #133 — physical Arm-C retry campaign authority tests (CPU-only).

Exercises scripts/issue133_arm_c_retry_campaign.py:

- the authority document satisfies the #129-frozen strict schema AND the
  exact issue #133 identity bindings;
- the comparator contract data matches the frozen #129 argument contract;
- attempt facts emitted against the authority record are classifiable by
  the #129 state machine, and authority drift fails closed;
- the execution-freeze record builder enforces the deployment-identity
  contract on every driver before freezing;
- the authority-history gate fails closed until the document is committed
  to accepted history.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue133_arm_c_retry_campaign as camp  # noqa: E402
import issue129_arm_c_retry_core as core  # noqa: E402

AUTHORITY = camp.AUTHORITY_PATH


class AuthorityDocumentTests(unittest.TestCase):
    def test_document_satisfies_frozen_schema_and_issue_bindings(self):
        document = camp.load_authority_document()
        verdict = camp.validate_authority_bindings(document)
        self.assertTrue(verdict["bound"], verdict["problems"])
        self.assertEqual(len(verdict["campaign_ids"]), 1)

    def test_document_is_canonical_json(self):
        raw = AUTHORITY.read_bytes()
        document = json.loads(raw)
        self.assertEqual(
            raw, (json.dumps(document, indent=2, sort_keys=True) + "\n").encode())

    def test_methodology_head_is_the_accepted_808b77c(self):
        document = camp.load_authority_document()
        for record in document["campaigns"].values():
            self.assertEqual(
                record["methodology_ready_identity"],
                camp.ISSUE133["methodology_ready_head"])

    def test_authorization_follows_methodology_acceptance(self):
        document = camp.load_authority_document()
        self.assertTrue(document["execution_authorization"][
            "physical_retry_authorized"])
        # PR #132 merged 2026-09-09T20:00:50-04:00 == 2026-09-10T00:00:50Z
        self.assertEqual(
            document["acceptance"]["methodology_accepted_at"],
            "2026-09-10T00:00:50Z")

    def test_control_scope_drift_fails_closed(self):
        document = camp.load_authority_document()
        document["execution_authorization"]["scope"] = "ISSUE117_ARM_D"
        with self.assertRaisesRegex(RuntimeError, "scope"):
            core._parse_accepted_campaign_authority_document(document)

    def test_control_issue_reference_drift_fails_closed(self):
        document = camp.load_authority_document()
        verdict = camp.validate_authority_bindings(document)
        self.assertTrue(verdict["bound"])
        document["execution_authorization"][
            "authorization_reference"] = "https://github.com/Zutfen-LLC/inferswarm/issues/129"
        verdict = camp.validate_authority_bindings(document)
        self.assertFalse(verdict["bound"])
        self.assertTrue(any("issue #133" in p for p in verdict["problems"]))

    def test_control_placeholder_freeze_identity_fails_closed(self):
        document = camp.load_authority_document()
        for campaign_id in document["campaigns"]:
            document["campaigns"][campaign_id][
                "execution_freeze_identity"] = "0" * 64
        verdict = camp.validate_authority_bindings(document)
        self.assertFalse(verdict["bound"])

    def test_control_second_campaign_fails_closed(self):
        document = camp.load_authority_document()
        first = next(iter(document["campaigns"]))
        clone = copy.deepcopy(document["campaigns"][first])
        clone["physical_authorization_id"] = "phys-auth-clone"
        clone["campaign_lineage_root"] = "sha256:" + "c" * 64
        document["campaigns"]["armc-retry-clone"] = clone
        verdict = camp.validate_authority_bindings(document)
        self.assertFalse(verdict["bound"])


class ComparatorContractTests(unittest.TestCase):
    def test_contract_matches_frozen_129_argument_contract(self):
        self.assertEqual(
            tuple(camp.COMPARATOR_CONTRACT["generate_argument_names"]),
            tuple(core.GENERATE_ARGUMENT_NAMES))
        self.assertEqual(camp.COMPARATOR_CONTRACT["max_new_tokens"], 2)
        self.assertIn("forbidden", camp.COMPARATOR_CONTRACT["single_shot_forbidden"])
        self.assertIn("step zero", camp.COMPARATOR_CONTRACT["commit"])

    def test_tokenizer_pins_match_accepted_integrity_record(self):
        integrity = json.loads(
            (camp.RETRY_EVIDENCE / "integrity.json").read_text())
        self.assertEqual(
            camp.TOKENIZER_ASSET_PINS,
            integrity["tokenizer_asset_pins"])
        self.assertEqual(
            camp.TOKENIZER_SOFTWARE_IDENTITY,
            integrity["tokenizer_software_identity"]["packages"])


class AttemptFactsTests(unittest.TestCase):
    def _authority(self):
        return camp.load_authority_document()

    def test_fresh_campaign_facts_classify_pre_observation(self):
        facts = camp.emit_attempt_facts(
            campaign_id=next(iter(self._authority()["campaigns"])),
            attempt_id="armc-retry-infra-1",
            observed_at="2026-09-10T02:00:00Z",
            authority=self._authority(),
            gpu_execution_occurred=False,
            model_execution_occurred=False,
            correctness_bearing_result_emitted=False,
            result_reached_coordinator=False,
            coordinator_commit_occurred=False,
            frozen_identity_verified_pre_launch=True,
            frozen_identity_verified_post_run=True)
        self.assertEqual(
            core.classify_attempt(facts), "PRE_OBSERVATION_INFRASTRUCTURE")

    def test_control_emission_against_wrong_campaign_fails(self):
        authority = self._authority()
        with self.assertRaises(KeyError):
            camp.emit_attempt_facts(
                campaign_id="armc-retry-nonexistent",
                attempt_id="x",
                observed_at="2026-09-10T02:00:00Z",
                authority=authority,
                gpu_execution_occurred=False,
                model_execution_occurred=False,
                correctness_bearing_result_emitted=False,
                result_reached_coordinator=False,
                coordinator_commit_occurred=False,
                frozen_identity_verified_pre_launch=True,
                frozen_identity_verified_post_run=True)


class ExecutionFreezeTests(unittest.TestCase):
    def _driver(self, **overrides):
        driver = {
            "repository_sha": "a" * 40,
            "file_sha256": "b" * 64,
            "expected_path": "/srv/inferswarm/state/arm-c-retry/direct.py",
            "read_only": True,
            "pre_launch_verified": True,
            "post_run_verified": True,
            "post_run_file_sha256": "b" * 64,
        }
        driver.update(overrides)
        return driver

    def test_freeze_record_binds_all_issue133_identities(self):
        record = camp.build_execution_freeze_record(
            {"direct": self._driver()})
        for field in ("frozen_producer", "checkpoint_sha256",
                      "candidate", "geometry", "execution_plan_digest",
                      "participant_identity", "fixture_digest"):
            self.assertEqual(record[field], camp.ISSUE133[field])
        self.assertEqual(record["schema"],
                         "inferswarm.issue133.execution-freeze/1")

    def test_control_mutable_driver_rejected_before_freeze(self):
        with self.assertRaisesRegex(ValueError, "deployment-identity"):
            camp.build_execution_freeze_record(
                {"direct": self._driver(read_only=False)})

    def test_control_changed_after_freeze_driver_rejected(self):
        with self.assertRaisesRegex(ValueError, "deployment-identity"):
            camp.build_execution_freeze_record(
                {"direct": self._driver(
                    post_run_file_sha256="c" * 64)})

    def test_freeze_identity_is_canonical_sha256(self):
        record = camp.build_execution_freeze_record(
            {"direct": self._driver()})
        identity = camp.execution_freeze_identity(record)
        self.assertEqual(len(identity), 64)
        recomputed = camp.execution_freeze_identity(
            json.loads(json.dumps(record)))
        self.assertEqual(identity, recomputed)


class AuthorityHistoryGateTests(unittest.TestCase):
    def test_gate_fails_closed_until_committed_to_accepted_history(self):
        # In the pre-merge working tree the committed bytes (if any) do not
        # yet match; if they DO match (document already committed on this
        # branch) the gate must return a commit without error.
        try:
            commit = camp.accepted_authority_commit()
        except RuntimeError as error:
            self.assertIn("not yet committed", str(error))
            return
        self.assertEqual(len(commit), 40)


if __name__ == "__main__":
    unittest.main()
