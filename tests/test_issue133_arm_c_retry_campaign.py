"""Issue #133 — physical Arm-C retry campaign authority tests (CPU-only).

Exercises scripts/issue133_arm_c_retry_campaign.py:

- the authority document satisfies the #129-frozen strict schema AND the
  exact issue #133 identity bindings;
- the comparator contract data matches the frozen #129 argument contract;
- attempt facts emitted against the authority record are classifiable by
  the #129 state machine, and authority drift fails closed;
- the STATIC execution-freeze record builder enforces the static
  deployment-identity contract on every driver before freezing, and a
  pre-run freeze can never masquerade as completed post-run verification;
- the mechanical freeze<->authority binding rejects any byte/identity
  mismatch;
- the accepted-history prelaunch gate requires the authority commit to be
  an ANCESTOR of refs/remotes/origin/main, proven in controlled temporary
  Git repositories (branch-only rejection, accepted-main success, missing
  remote ref, malformed commit).
"""
import copy
import json
import os
import shutil
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


def _git(root: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(root), *args], cwd=str(root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        check=check)


def _scratch_repo(tmp: str) -> Path:
    """A scratch repository carrying this checkout's authority bytes plus
    the retained evidence the loaders need (minimal copy)."""
    repo = Path(tmp) / "repo"
    repo.mkdir()
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    area = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
    shutil.copytree(area, repo / "docs/implementation"
                    "/r6-successor-dense-full-integration-117",
                    ignore=shutil.ignore_patterns("__pycache__"))
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Issue 133 Test")
    _git(repo, "config", "user.email", "issue133@example.invalid")
    # base history WITHOUT the authority path (so a side-branch authority
    # commit is the only commit carrying those bytes when tests want it)
    (repo / "README.marker").write_text("scratch fixture\n")
    _git(repo, "add", "README.marker")
    _git(repo, "commit", "-q", "-m", "scratch base")
    return repo


def _commit_marker(repo: Path, message: str) -> str:
    """An unrelated base commit that does NOT touch the authority path."""
    marker = repo / "README.marker"
    marker.write_text(f"scratch: {message}\n")
    _git(repo, "add", "README.marker")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit_authority(repo: Path, message: str) -> str:
    rel = camp.AUTHORITY_PATH.relative_to(ROOT)
    _git(repo, "add", str(rel))
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


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


class CampaignRetentionTests(unittest.TestCase):
    def test_current_campaign_has_zero_attempts_terminals_and_stops(self):
        proof = camp.verify_campaign_retention_legality()
        self.assertEqual(proof["campaign_id"], "armc-retry-afcdc4428f95d50c")
        self.assertEqual(proof["attempt_count"], 0)
        self.assertEqual(proof["terminal_count"], 0)
        self.assertEqual(proof["stop_count"], 0)
        self.assertTrue(proof["prior_stop_fields_all_null"])
        self.assertTrue(proof["same_campaign_rebinding_legal"])


class ExecutionFreezeTests(unittest.TestCase):
    def _driver(self, **overrides):
        driver = {
            "repository_sha": "a" * 40,
            "file_sha256": "b" * 64,
            "expected_path": "/srv/inferswarm/state/arm-c-retry/direct.py",
            "read_only": True,
        }
        driver.update(overrides)
        return driver

    def _dependencies(self):
        return {
            "runtime_session_allocator_source": {
                "repository_sha": "c" * 40,
                "file_sha256": "d" * 64,
                "expected_path": (
                    "/srv/inferswarm/state/arm-c-retry/scripts/r5b_epochs.py"),
                "read_only": True,
            }
        }

    def _record(self):
        return camp.build_execution_freeze_record(
            {"direct": self._driver()}, self._dependencies())

    def test_freeze_record_binds_all_issue133_identities(self):
        record = self._record()
        for field in ("frozen_producer", "checkpoint_sha256",
                      "candidate", "geometry", "execution_plan_digest",
                      "participant_identity", "fixture_digest"):
            self.assertEqual(record[field], camp.ISSUE133[field])
        self.assertEqual(record["schema"], camp.FREEZE_SCHEMA)
        self.assertEqual(
            record["authorized_realization_inputs"],
            camp.AUTHORIZED_REALIZATION_INPUTS)
        self.assertIn("runtime_session_allocator_source",
                      record["dependencies"])

    def test_control_mutable_driver_rejected_before_freeze(self):
        with self.assertRaisesRegex(ValueError, "static deployment-identity"):
            camp.build_execution_freeze_record(
                {"direct": self._driver(read_only=False)},
                self._dependencies())

    def test_control_observational_driver_field_rejected_before_freeze(self):
        with self.assertRaisesRegex(ValueError, "static deployment-identity"):
            camp.build_execution_freeze_record(
                {"direct": self._driver(pre_launch_verified=True)},
                self._dependencies())

    def test_freeze_record_contains_no_observational_claims(self):
        record = self._record()
        encoded = json.dumps(record)
        for field in camp.OBSERVATIONAL_DEPLOYMENT_FIELDS:
            self.assertNotIn(f'"{field}"', encoded)
        requirements = record["deployment_verification_requirements"]
        self.assertTrue(requirements["pre_launch_verification_required"])
        self.assertTrue(requirements["post_run_verification_required"])

    def test_control_all_observational_fields_rejected_from_static_freeze(self):
        record = self._record()
        values = {
            "pre_launch_verified": True,
            "post_run_verified": True,
            "post_run_file_sha256": "b" * 64,
        }
        for field, value in values.items():
            with self.subTest(field=field), self.assertRaisesRegex(
                    RuntimeError, "observational deployment fields"):
                driver = dict(record["drivers"]["direct"])
                driver[field] = value
                camp.verify_freeze_static_shape({
                    **record,
                    "drivers": {**record["drivers"], "direct": driver},
                })

    def test_control_old_v1_pre_authored_freeze_shape_rejected(self):
        # the corrected (#134 review finding 3) shape: the OLD v1 record
        # with pre-authored post_run fields must fail the static check
        record = self._record()
        legacy_driver = dict(record["drivers"]["direct"])
        legacy_driver["post_run_verified"] = True
        legacy_driver["post_run_file_sha256"] = legacy_driver["file_sha256"]
        legacy = dict(record)
        legacy["schema"] = "inferswarm.issue133.execution-freeze/1"
        legacy.pop("deployment_verification_requirements")
        legacy["drivers"] = {"direct": legacy_driver}
        with self.assertRaisesRegex(RuntimeError, "observational"):
            camp.verify_freeze_static_shape(legacy)

    def test_freeze_identity_is_canonical_sha256(self):
        record = self._record()
        identity = camp.execution_freeze_identity(record)
        self.assertEqual(len(identity), 64)
        recomputed = camp.execution_freeze_identity(
            json.loads(json.dumps(record)))
        self.assertEqual(identity, recomputed)


class FreezeBindingTests(unittest.TestCase):
    """Mechanical binding of the retained execution-freeze bytes to the
    sole authorized campaign's execution_freeze_identity (review finding
    2), with the mandatory negative controls."""

    def _mutated_repo(self, mutator, *, commit_authority: bool = False):
        tmp = tempfile.mkdtemp(prefix="freeze-bind-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = _scratch_repo(tmp)
        if commit_authority:
            merged = _commit_authority(repo, "authority merged")
            _git(repo, "update-ref", "refs/remotes/origin/main", merged)
        freeze_path = repo / camp.EXECUTION_FREEZE_RECORD.relative_to(ROOT)
        mutator(freeze_path)
        return repo

    def test_retained_freeze_binds_to_authority_identity(self):
        verdict = camp.verify_execution_freeze_binding()
        self.assertTrue(verdict["bound"])
        self.assertEqual(
            verdict["authorized_execution_freeze_identity"],
            verdict["retained_bytes_sha256"])

    def test_control_single_freeze_byte_mutation_rejects(self):
        def mutate(path):
            raw = path.read_bytes()
            # flip one byte inside a sha256 value without touching the
            # authority document (which stays byte-identical)
            index = raw.index(b'"file_sha256": "')
            offset = index + len(b'"file_sha256": "') + 1
            mutated = bytearray(raw)
            original = mutated[offset]
            mutated[offset] = ord("0") if original != ord("0") else ord("1")
            path.write_bytes(bytes(mutated))
            self.assertNotEqual(raw, path.read_bytes())
        repo = self._mutated_repo(mutate)
        with self.assertRaisesRegex(RuntimeError, "binding mismatch"):
            camp.verify_execution_freeze_binding(repo_root=repo)

    def test_control_replaced_valid_looking_freeze_rejects(self):
        def mutate(path):
            record = json.loads(path.read_text())
            # another internally-valid record: different retained bytes,
            # same schema, authority unchanged
            record["case_count"] = 23
            path.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n")
        repo = self._mutated_repo(mutate)
        with self.assertRaisesRegex(RuntimeError, "binding mismatch"):
            camp.verify_execution_freeze_binding(repo_root=repo)

    def test_control_zero_authority_digest_rejects(self):
        document = camp.load_authority_document()
        campaign_id = next(iter(document["campaigns"]))
        document["campaigns"][campaign_id][
            "execution_freeze_identity"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "malformed or unbound"):
            camp.verify_execution_freeze_binding(document)

    def test_control_malformed_authority_digest_rejects(self):
        document = camp.load_authority_document()
        campaign_id = next(iter(document["campaigns"]))
        document["campaigns"][campaign_id][
            "execution_freeze_identity"] = "not-a-sha256"
        with self.assertRaisesRegex(RuntimeError, "malformed or unbound"):
            camp.verify_execution_freeze_binding(document)

    def test_control_non_canonical_freeze_bytes_reject(self):
        def mutate(path):
            record = json.loads(path.read_text())
            # same JSON value, non-canonical representation (no trailing
            # newline / different indent): identity is defined over the
            # canonical bytes, so this must fail closed even though the
            # parsed document is unchanged
            path.write_text(json.dumps(record, indent=4, sort_keys=True))
        repo = self._mutated_repo(mutate)
        with self.assertRaisesRegex(RuntimeError, "canonical"):
            camp.verify_execution_freeze_binding(repo_root=repo)

    def test_control_authored_digest_field_is_not_self_proof(self):
        def mutate(path):
            record = json.loads(path.read_text())
            # an authored digest field inside the freeze must never be
            # consulted as proof of its own identity: inject a WRONG
            # self-authored digest; binding still compares retained BYTES
            record["self_authored_digest"] = "0" * 64
            path.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n")
        repo = self._mutated_repo(mutate)
        with self.assertRaises(RuntimeError):
            camp.verify_execution_freeze_binding(repo_root=repo)

    def test_binding_is_executed_by_pre_execution_gate(self):
        # the Phase-B entry point runs the binding check; a mutated freeze
        # must reject the GATE, not merely a unit test (the fixture also
        # places the authority in accepted history so the failure is
        # attributable to the freeze binding itself)
        def mutate(path):
            raw = bytearray(path.read_bytes())
            raw[-10] = raw[-10] ^ 0x01
            path.write_bytes(bytes(raw))
        repo = self._mutated_repo(mutate, commit_authority=True)
        with self.assertRaisesRegex(RuntimeError, "freeze"):
            camp.verify_pre_execution_authority_gate(
                repo_root=repo, repo_path=repo)


class AcceptedHistoryGateTests(unittest.TestCase):
    """The pre-execution accepted-history gate (review finding 1),
    proven in controlled temporary Git repositories: the selected
    authority commit must be an ANCESTOR of refs/remotes/origin/main."""

    def _repo(self, tmp: str) -> Path:
        return _scratch_repo(tmp)

    def test_gate_fails_closed_when_authority_bytes_are_uncommitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            with self.assertRaisesRegex(RuntimeError, "no commit carries"):
                camp.accepted_authority_commit(repo_path=repo)

    def test_branch_only_authority_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            _commit_marker(repo, "unrelated base commit")
            # authority bytes land ONLY on a side branch; main stays behind
            _git(repo, "checkout", "-q", "-b", "pr-branch")
            branch_commit = _commit_authority(
                repo, "authority on the PR branch only")
            _git(repo, "checkout", "-q", "master")
            _git(repo, "update-ref", "refs/remotes/origin/main", "master")
            # sanity: the branch commit carries the authority bytes...
            # (authority BYTES for matching come from THIS repository's
            # retained evidence path, which the scratch branch committed
            # verbatim; only the git history lives in the scratch repo)
            self.assertEqual(
                camp.find_authority_commits(ROOT, repo), [branch_commit])
            # ...but the gate rejects it: not accepted history
            with self.assertRaisesRegex(
                    RuntimeError, "branch-only authority commit"):
                camp.accepted_authority_commit(repo_path=repo)

    def test_authority_commit_accepted_into_main_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            _commit_marker(repo, "unrelated base commit")
            merged = _commit_authority(repo, "authority merged into main")
            _git(repo, "update-ref", "refs/remotes/origin/main", merged)
            self.assertEqual(
                camp.accepted_authority_commit(repo_path=repo), merged)

    def test_missing_remote_ref_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            _commit_authority(repo, "authority committed")
            # deliberately NO refs/remotes/origin/main
            with self.assertRaisesRegex(RuntimeError, "missing"):
                camp.accepted_authority_commit(repo_path=repo)

    def test_matching_bytes_at_unaccepted_commit_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            # main carries an UNRELATED history; the authority bytes exist
            # only at a commit that is NOT an ancestor of origin/main
            _commit_marker(repo, "unrelated base")
            _git(repo, "update-ref", "refs/remotes/origin/main", "master")
            _git(repo, "checkout", "-q", "-b", "side")
            _commit_authority(repo, "authority bytes off-main")
            _git(repo, "checkout", "-q", "master")
            with self.assertRaisesRegex(RuntimeError, "not accepted into"):
                camp.accepted_authority_commit(repo_path=repo)

    def test_pre_execution_gate_requires_accepted_history_pre_merge(self):
        # in THIS working tree (pre-merge PR state) the gate must refuse
        # to authorize physical execution: the authority document exists
        # only on the unmerged PR branch
        with self.assertRaisesRegex(RuntimeError, "no commit carries|"
                                    "branch-only|not accepted into"):
            camp.verify_pre_execution_authority_gate()

    def test_pre_execution_gate_passes_in_accepted_history_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            merged = _commit_authority(repo, "authority merged into main")
            _git(repo, "update-ref", "refs/remotes/origin/main", merged)
            verdict = camp.verify_pre_execution_authority_gate(
                repo_root=repo, repo_path=repo)
            self.assertEqual(
                verdict["accepted_authority_commit"], merged)
            self.assertEqual(
                verdict["execution_freeze_binding"]["bound"], True)


if __name__ == "__main__":
    unittest.main()
