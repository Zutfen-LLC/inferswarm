"""Issue #129 — Arm-C retry methodology gate (CPU-only; no GPU/model execution).

Exercises scripts/issue129_arm_c_retry_core.py end to end:

- BASELINE: 24/24 exact runtime-call transcript equivalence between the
  ORDINARY arm (the REAL frozen EpochServingController, planner, and
  strategy bytes retained under the accepted and additive frozen areas,
  fed by the ordinary Coordinator ingress/tokenizer seam) and the corrected
  DIRECT comparator (which allocates runtime session ids through the
  allocator mechanically extracted from the pinned r5b_epochs.py bytes),
  on the recording fake runtime;
- the ordinary Coordinator ingress/tokenizer seam renders the exact
  ordinary request bodies to exactly the frozen prompt-token fixture
  (24/24) through the MECHANICALLY EXTRACTED frozen functions;
- the tokenizer Source contract (non-Source pinned assets; zero
  forbidden-root opens during the observation window);
- the accepted #128 blocker evidence is preserved byte-exact from the
  accepted merge 718efbf…;
- frozen-byte pinning fails closed (including the inherited #128 pins);
- every mandatory negative control of issue #129 fails closed through
  the same real derivation;
- the attempt/STOP/physical-authorization state machine classifies attempts
  and preserves mandatory STOPs mechanically;
- the deployed-script identity contract rejects mutable/unpinned/changed
  scripts;
- stored ``equal`` flags or terminal strings never substitute for
  derivation.
"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue129_arm_c_retry_core as core  # noqa: E402

AREA = core.AREA
RETRY_EVIDENCE = AREA / "evidence" / "arm-c-retry"
ARM_C = AREA / "evidence" / "arm-c"


def _arms(**kwargs):
    return core.run_both_arms(ROOT, **kwargs)


def _attempt_facts(**overrides):
    campaign = overrides.get("campaign_id", "campaign-A")
    is_b = campaign == "campaign-B"
    facts = {
        "campaign_id": campaign,
        "physical_authorization_id": (
            "authorization-B" if is_b else "authorization-A"),
        "methodology_ready_identity": "a" * 40,
        "execution_freeze_identity": "b" * 64,
        "attempt_id": "a",
        "observed_at": (
            "2026-09-09T00:00:05Z" if is_b else
            "2026-09-09T00:00:01Z"),
        "campaign_lineage_root": "lineage-B" if is_b else "lineage-A",
        "physical_authorization_issued_at": (
            "2026-09-09T00:00:04Z" if is_b else
            "2026-09-09T00:00:00Z"),
        "prior_stopped_campaign_id": "campaign-A" if is_b else None,
        "prior_stop_attempt_id": "invalid-1" if is_b else None,
        "prior_stop_review_id": "maintainer-review-A" if is_b else None,
        "prior_stop_reviewed_at": (
            "2026-09-09T00:00:03Z" if is_b else None),
        "gpu_execution_occurred": False,
        "model_execution_occurred": False,
        "correctness_bearing_result_emitted": False,
        "result_reached_coordinator": False,
        "coordinator_commit_occurred": False,
        "frozen_identity_verified_pre_launch": True,
        "frozen_identity_verified_post_run": True,
        "methodology_gate_passed": True,
        "physical_retry_authorized": True,
        "terminal_observation": False,
        "diagnostic_only_disclosure": False,
        "stop_occurred": False,
    }
    facts.update(overrides)
    return facts


def _accepted_authority_records(attempts):
    """Build explicit synthetic accepted-authority records for tests."""
    records = {}
    for facts in attempts:
        campaign_id = facts["campaign_id"]
        records.setdefault(campaign_id, {
            field: facts[field] for field in core.CAMPAIGN_AUTHORITY_FIELDS})
    return records


def _reduce(attempts, *, accepted_authorities=None):
    """Reduce test facts against authority that is separate from them."""
    attempts = list(attempts)
    authorities = (accepted_authorities if accepted_authorities is not None
                   else _accepted_authority_records(attempts))
    return core._reduce_attempts_with_authority_records(
        attempts, accepted_campaign_authorities=authorities)


def _physical_authority_document(attempts):
    """Build a strict synthetic document for authority-parser tests."""
    return {
        "schema": core.PHYSICAL_AUTHORITY_SCHEMA,
        "acceptance": {
            "methodology_terminal": core.METHODOLOGY_READY,
            "methodology_accepted": True,
            "methodology_acceptance_reference": "review-accepted-129",
            "methodology_accepted_at": "2026-09-08T23:59:58Z",
        },
        "execution_authorization": {
            "physical_retry_authorized": True,
            "authorization_reference": "issue-117-physical-authorization",
            "authorized_at": "2026-09-08T23:59:59Z",
            "scope": "ISSUE117_ARM_C_RETRY",
        },
        "campaigns": _accepted_authority_records(attempts),
    }


def _init_scratch_authority_repo(root, document):
    """Commit canonical authority bytes and set the accepted main ref."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Issue 129 Test"],
        cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "issue129@example.invalid"],
        cwd=root, check=True)
    path = root / core.PHYSICAL_CAMPAIGN_AUTHORITY_PATH
    path.parent.mkdir(parents=True)
    raw = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    subprocess.run(["git", "add", str(path.relative_to(root))],
                   cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test: authority"],
                   cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        capture_output=True, text=True).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", commit],
        cwd=root, check=True)
    return commit, raw


def _scratch_mirror(tmp: str) -> Path:
    """A scratch mirror of scripts/ + the issue-117 area (for
    frozen-byte/pins mutation controls; carries no git history)."""
    import shutil
    mirror = Path(tmp) / "repo"
    mirror.mkdir()
    shutil.copytree(ROOT / "scripts", mirror / "scripts")
    area = mirror / AREA.relative_to(ROOT)
    shutil.copytree(AREA, area, ignore=shutil.ignore_patterns())
    return mirror


class BaselineEquivalenceTests(unittest.TestCase):
    """The methodology gate passes on the corrected comparator only."""

    @classmethod
    def setUpClass(cls):
        cls.arms = _arms()
        cls.reduction = core.reduce_transcripts(
            cls.arms["ordinary"], cls.arms["direct"])

    def test_24_of_24_transcript_equivalence(self):
        self.assertEqual(self.reduction["equal_count"], 24)
        self.assertTrue(self.reduction["passed"])
        self.assertEqual(
            self.reduction["terminal"], core.METHODOLOGY_READY)

    def test_ordinary_arm_is_the_real_frozen_controller(self):
        ordinary = self.arms["ordinary"]
        self.assertEqual(
            ordinary["selection_authorization"]["mode"],
            "AUTOMATIC_PLANNER_SELECTION")
        self.assertEqual(
            ordinary["plan_digest_source"],
            "real freeze_execution_plan via frozen producer bytes")
        # per-case committed epoch/plan attribution exists (real controller)
        for case in ordinary["per_case"].values():
            self.assertEqual(len(case["committed_epoch_ids"]), 8)
            self.assertTrue(all(case["committed_epoch_ids"]))
            self.assertEqual(len(set(case["committed_plan_digests"])), 1)
            self.assertEqual(case["prompt_ids_source"],
                             "ordinary-ingress derivation")

    def test_every_case_is_eight_calls_max2_with_speculative_discard(self):
        for arm_name in ("ordinary", "direct"):
            for case in self.arms[arm_name]["per_case"].values():
                self.assertEqual(len(case["calls"]), 8)
                for call in case["calls"]:
                    self.assertEqual(call["max_new_tokens"], 2)
                    self.assertIsNotNone(
                        call["response_speculative_token_id"])
                # committed ids are exactly the step-0 responses
                self.assertEqual(
                    case["completed_token_ids"],
                    [c["response_commit_token_id"] for c in case["calls"]])

    def test_replay_prefix_grows_by_one_committed_token_per_call(self):
        fixture = {
            case["case_id"]: case
            for case in self.arms["fixture"]["cases"]}
        for arm_name in ("ordinary", "direct"):
            for case_id, case in self.arms[arm_name]["per_case"].items():
                base = fixture[case_id]["rendered_prompt_token_ids"]
                for index, call in enumerate(case["calls"]):
                    self.assertEqual(
                        call["prompt_token_ids"],
                        list(base) + [
                            c["response_commit_token_id"]
                            for c in case["calls"][:index]])

    def test_runtime_session_id_is_compared_and_equal(self):
        # Finding 2: the runtime session_id is a generate() keyword
        # value and is compared exactly per call, per case, all 8 calls
        for case_id in sorted(self.arms["ordinary"]["per_case"]):
            o = self.arms["ordinary"]["per_case"][case_id]
            d = self.arms["direct"]["per_case"][case_id]
            self.assertEqual(
                [c["runtime_session_id"] for c in o["calls"]],
                [c["runtime_session_id"] for c in d["calls"]],
                f"{case_id}: runtime session id sequences differ")
        self.assertIn("runtime_session_id",
                      self.reduction["compared_runtime_call_fields"])
        self.assertNotIn("runtime_session_id",
                         self.reduction["control_plane_only_fields"])

    def test_runtime_session_ids_follow_the_frozen_allocation(self):
        # logical_session_id * 1_000_000 + global call sequence, one
        # global sequence across all cases in ordinary order — exactly
        # what the frozen controller's own allocation produces
        for case_id in sorted(self.arms["ordinary"]["per_case"]):
            case = self.arms["ordinary"]["per_case"][case_id]
            logical = case["logical_session_id"]
            offset = (logical - 1) * 8
            self.assertEqual(
                [c["runtime_session_id"] for c in case["calls"]],
                [logical * 1_000_000 + offset + i + 1
                 for i in range(8)])

    def test_direct_allocation_is_derived_from_pinned_source(self):
        facts = self.arms["direct"]["runtime_session_allocation"]
        self.assertEqual(facts["multiplier"], 1_000_000)
        self.assertIn("verbatim AST extraction", facts["derivation"])
        digests = core.verify_frozen_bytes(ROOT)
        epochs_rel = ("docs/implementation/r6-successor-dense-full-"
                      "integration-117/evidence/arm-c/frozen-freetoken/"
                      "924cd22e/python/freetoken/research/r5b_epochs.py")
        self.assertEqual(facts["source_sha256"], digests[epochs_rel])

    def test_control_plane_only_fields_are_outside_model_inputs(self):
        reduction = self.reduction
        # the recorded generate argument set excludes every
        # control-plane-only field on both arms
        for arm_name in ("ordinary", "direct"):
            names = self.arms[arm_name]["generate_argument_names"]
            for field in reduction["control_plane_only_fields"]:
                self.assertNotIn(field, names)

    def test_top_level_methodology_run_passes(self):
        run = core.run_methodology(ROOT)
        self.assertEqual(run["terminal"], core.METHODOLOGY_READY)
        self.assertFalse(run["cpu_only"]["gpu_execution_occurred"])
        self.assertFalse(run["cpu_only"]["model_execution_occurred"])
        self.assertEqual(run["schema"],
                         "inferswarm.issue129.methodology-run/4")
        self.assertTrue(run["runtime_session_cross_check"]["ok"])
        self.assertTrue(run["attempt_state_machine_self_checks"]["ok"])


class OrdinaryIngressTests(unittest.TestCase):
    """Finding 3: the actual ordinary Coordinator ingress/tokenizer
    seam is exercised and equals the frozen prompt-token fixture."""

    @classmethod
    def setUpClass(cls):
        cls.ingress = core.run_ordinary_ingress_proof(ROOT)

    def test_renders_equal_frozen_fixture_24_of_24(self):
        self.assertEqual(self.ingress["case_count"], 24)
        self.assertEqual(self.ingress["equal_count"], 24)
        self.assertTrue(self.ingress["passed"])
        self.assertEqual(self.ingress["problems"], [])

    def test_request_bodies_equal_retained_accepted_records(self):
        # the body-reconstruction equality is part of the proof (any
        # drift surfaces as an ingress problem)
        self.assertTrue(self.ingress["passed"])

    def test_ingress_functions_are_extracted_from_pinned_bytes(self):
        citations = self.ingress["coordinator_ingress_citations"]
        for key in ("_render_and_tokenize", "_sampling_of"):
            self.assertIn(key, citations)
            self.assertIn("source_sha256", citations[key])
        for key in core.COORDINATOR_INGRESS_LINES:
            self.assertIn(key, citations)
            self.assertIn("line", citations[key])
        digests = core.verify_frozen_bytes(ROOT)
        coordinator_rel = ("docs/implementation/r6-successor-dense-full-"
                           "integration-117/evidence/arm-c/frozen-freetoken/"
                           "924cd22e/benchmarks/inferswarm_r6/coordinator.py")
        self.assertEqual(self.ingress["coordinator_source_sha256"],
                         digests[coordinator_rel])

    def test_frozen_session_allocation_matches_request_log_order(self):
        # len(request_log) + 1 in ascending ordinary order reproduces
        # the frozen session indices 1..24
        indices = [row["session_index"] for row in self.ingress["rows"]]
        self.assertEqual(indices, list(range(1, 25)))

    def test_template_contract_cross_derived_from_both_sides(self):
        template = core.derive_template_contract(ROOT)
        self.assertEqual(template["header_token_ids"],
                         list(core.CHAT_TEMPLATE_HEADER_TOKEN_IDS))
        self.assertEqual(template["footer_token_ids"],
                         list(core.CHAT_TEMPLATE_FOOTER_TOKEN_IDS))
        self.assertEqual(template["trailing_space_cases"],
                         ["c109-04-03-040"])

    def test_control_ordinary_rendering_mismatch_footer(self):
        run = core.run_methodology(
            ROOT,
            ingress_footer_mutator=lambda footer: footer[:-1] + [footer[-1] + 1])
        self.assertEqual(run["terminal"], core.METHODOLOGY_BLOCKED)
        self.assertFalse(run["ordinary_ingress"]["passed"])

    def test_control_ordinary_rendering_mismatch_content(self):
        run = core.run_methodology(
            ROOT,
            ingress_content_mutator=lambda case_id, ids: ids[:-1] + [ids[-1] + 1])
        self.assertEqual(run["terminal"], core.METHODOLOGY_BLOCKED)
        self.assertFalse(run["ordinary_ingress"]["passed"])

    def test_control_ordinary_request_body_drift(self):
        def mangle(case_id, body):
            body = dict(body)
            body["temperature"] = 0.5
            return body
        run = core.run_methodology(ROOT, ingress_body_mutator=mangle)
        self.assertEqual(run["terminal"], core.METHODOLOGY_BLOCKED)

    def test_control_unpinned_content_fails_closed(self):
        # the stand-in tokenizer must refuse text outside the accepted
        # encodings (a mutated prompt cannot silently re-render)
        template = core.derive_template_contract(ROOT)
        tokenizer = core.FrozenSourceTokenizerStandIn(template, {})
        composed = tokenizer.apply_chat_template(
            [{"role": "user", "content": "never seen text"}])
        with self.assertRaises(RuntimeError):
            tokenizer.encode(composed, add_special_tokens=False)
        with self.assertRaises(RuntimeError):
            tokenizer.encode("not the frozen composition",
                             add_special_tokens=False)


class TokenizerSourceContractTests(unittest.TestCase):
    """The tokenizer Source rule: pinned non-Source assets; no
    forbidden-root opens during the observation window."""

    def test_contract_record_derives_from_accepted_provenance(self):
        record = core.tokenizer_asset_contract_record(ROOT)
        verdict = core.verify_tokenizer_asset_contract(record)
        self.assertTrue(verdict["ok"])
        names = {asset["name"] for asset in record["assets"]}
        self.assertEqual(names, set(core.REQUIRED_TOKENIZER_ASSETS))
        for asset in record["assets"]:
            self.assertEqual(asset["sha256"],
                             core.REQUIRED_TOKENIZER_ASSETS[asset["name"]])

    def test_control_tokenizer_path_points_at_source(self):
        for field in ("tokenizer_path", "asset_dir"):
            record = core.tokenizer_asset_contract_record(ROOT)
            record[field] = "/srv/models/gemma-r6"
            verdict = core.verify_tokenizer_asset_contract(record)
            self.assertFalse(verdict["ok"])
            self.assertIn("forbidden Source root", verdict["reason"])

    def test_control_tokenizer_asset_digest_drift(self):
        record = core.tokenizer_asset_contract_record(ROOT)
        record["assets"] = [
            {**asset, "sha256": "0" * 64}
            if asset["name"] == "tokenizer.json" else asset
            for asset in record["assets"]]
        verdict = core.verify_tokenizer_asset_contract(record)
        self.assertFalse(verdict["ok"])
        self.assertIn("digest drift", verdict["reason"])

    def test_control_missing_required_asset(self):
        record = core.tokenizer_asset_contract_record(ROOT)
        record["assets"] = [
            asset for asset in record["assets"]
            if asset["name"] != "chat_template.jinja"]
        verdict = core.verify_tokenizer_asset_contract(record)
        self.assertFalse(verdict["ok"])
        self.assertIn("missing", verdict["reason"])

    def test_control_digests_not_verified_pre_window(self):
        record = core.tokenizer_asset_contract_record(ROOT)
        record["digests_verified_pre_window"] = False
        verdict = core.verify_tokenizer_asset_contract(record)
        self.assertFalse(verdict["ok"])

    def test_control_unlisted_asset_dir_entry(self):
        # review 1 P2: an unlisted extra file in the tokenizer asset
        # directory (one AutoTokenizer could consume) violates the
        # contract even when every pinned digest matches
        record = core.tokenizer_asset_contract_record(ROOT)
        record["asset_dir_extra_entries"] = ["special_tokens_map.json"]
        verdict = core.verify_tokenizer_asset_contract(record)
        self.assertFalse(verdict["ok"])
        self.assertIn("unlisted entries", verdict["reason"])

    def test_control_non_exhaustive_asset_dir_listing(self):
        record = core.tokenizer_asset_contract_record(ROOT)
        record["asset_dir_exhaustive"] = False
        verdict = core.verify_tokenizer_asset_contract(record)
        self.assertFalse(verdict["ok"])
        self.assertIn("not exhaustive", verdict["reason"])

    def test_contract_record_labels_future_retry_obligation(self):
        # review 1/2: the record is a frozen contract for the future
        # retry, not a performed verification
        record = core.tokenizer_asset_contract_record(ROOT)
        self.assertIn("future-retry-obligation", record["status"])

    def test_control_forbidden_source_open_during_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = core.run_methodology(ROOT, simulated_forbidden_root=tmp)
        self.assertEqual(run["terminal"], core.METHODOLOGY_BLOCKED)
        monitor = run["tokenizer_source_contract"]["observation_monitor"]
        self.assertEqual(monitor["observation_window_source_opens"], 1)
        self.assertFalse(monitor["observation_window_clean"])

    def test_observation_monitor_ignores_non_source_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "benign.txt"
            target.write_text("x")
            monitor = core.SourceAccessMonitor()
            with monitor:
                with target.open("rb"):
                    pass
            report = monitor.report()
        self.assertEqual(report["observation_window_source_opens"], 0)
        self.assertTrue(report["observation_window_clean"])

    def test_gate_requires_real_transformers(self):
        run = core.run_methodology(ROOT)
        self.assertEqual(run["terminal"], core.METHODOLOGY_READY)
        self.assertEqual(
            run["ordinary_ingress"]["tokenizer"]["software"]["packages"],
            core.REQUIRED_TOKENIZER_SOFTWARE)


class RealTokenizerProofTests(unittest.TestCase):
    """The real retained tokenizer is methodology authority."""

    def test_real_tokenizer_renders_24_of_24(self):
        proof = core.run_ordinary_ingress_proof(ROOT)
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["equal_count"], 24)
        self.assertFalse(proof["stand_in_authority"])
        self.assertEqual(
            proof["tokenizer"]["loader"],
            "AutoTokenizer.from_pretrained")
        self.assertTrue(proof["tokenizer"]["local_files_only"])
        self.assertFalse(proof["tokenizer"]["trust_remote_code"])

    def test_control_each_tokenizer_asset_byte_mutation(self):
        import shutil
        for name in sorted(core.REQUIRED_TOKENIZER_ASSETS):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                assets = Path(tmp) / "assets"
                shutil.copytree(core.TOKENIZER_ASSET_DIR, assets)
                target = assets / name
                target.write_bytes(target.read_bytes() + b"\n")
                with self.assertRaisesRegex(RuntimeError, "asset drift"):
                    core.verify_retained_tokenizer_assets(
                        ROOT, asset_dir=assets)

    def test_control_missing_tokenizer_asset(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            shutil.copytree(core.TOKENIZER_ASSET_DIR, assets)
            (assets / "chat_template.jinja").unlink()
            with self.assertRaisesRegex(RuntimeError, "not exhaustive"):
                core.verify_retained_tokenizer_assets(ROOT, asset_dir=assets)

    def test_control_unlisted_tokenizer_asset(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            assets = Path(tmp) / "assets"
            shutil.copytree(core.TOKENIZER_ASSET_DIR, assets)
            (assets / "special_tokens_map.json").write_text("{}\n")
            with self.assertRaisesRegex(RuntimeError, "not exhaustive"):
                core.verify_retained_tokenizer_assets(ROOT, asset_dir=assets)

    def test_control_tokenizer_package_version_drift(self):
        versions = dict(core.REQUIRED_TOKENIZER_SOFTWARE)
        versions["transformers"] = "5.17.1"
        with self.assertRaisesRegex(RuntimeError, "package/version drift"):
            core.verify_tokenizer_software_identity(
                ROOT, installed_versions=versions)

    def test_control_rendered_ids_differ_from_fixture(self):
        proof = core.run_ordinary_ingress_proof(
            ROOT,
            rendered_ids_mutator=lambda case_id, ids: ids[:-1])
        self.assertFalse(proof["passed"])
        self.assertEqual(proof["equal_count"], 0)

    def test_control_tokenizer_path_under_source_root(self):
        with self.assertRaisesRegex(RuntimeError, "forbidden"):
            core.verify_retained_tokenizer_assets(
                ROOT, asset_dir=Path("/srv/models/gemma-r6"))


class AcceptedBlockerPreservationTests(unittest.TestCase):
    """Finding 1: accepted #128 blocker evidence is byte-exact from the
    accepted merge; #129 authority is additive only."""

    MERGE = core.ACCEPTED_BLOCKER_MERGE

    def test_all_accepted_arm_c_paths_byte_exact(self):
        result = core.verify_accepted_blocker_preservation(ROOT)
        self.assertTrue(result["preserved"])
        self.assertEqual(result["accepted_blocker_merge"], self.MERGE)
        self.assertGreaterEqual(result["path_count"], 60)
        self.assertTrue(result["no_new_paths"])
        self.assertEqual(result["new_paths"], [])
        # the two previously-modified files are byte-exact again
        for name in ("pre-execution-authority-audit.json",
                     "blocker-reduction.json"):
            rel = str((ARM_C / name).relative_to(ROOT))
            self.assertIn(rel, result["digests"])

    def test_accepted_audit_head_is_never_advanced(self):
        audit = json.loads(
            (ARM_C / "pre-execution-authority-audit.json").read_text())
        self.assertEqual(audit["head_classified"],
                         "5a56eb5c5df6289d25b2ae8fcff0497deda881c6")
        self.assertNotIn("head_classified_note", audit)
        reduction = json.loads(
            (ARM_C / "blocker-reduction.json").read_text())
        self.assertEqual(reduction["head_audited"],
                         "5a56eb5c5df6289d25b2ae8fcff0497deda881c6")

    def test_control_drifted_accepted_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            import os
            repo = Path(tmp) / "repo"
            repo.mkdir()
            # minimal git repo: commit the arm-c evidence tree at one
            # commit, point the accepted-merge override at it, then
            # drift one file
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args],
                               check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.email", "t@example.com")
            git("config", "user.name", "t")
            area = repo / AREA.relative_to(ROOT)
            shutil.copytree(ARM_C, area)
            git("add", "-A")
            git("commit", "-qm", "accepted base")
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True).stdout.strip()
            target = area / "blocker-reduction.json"
            target.write_text(target.read_text() + "\n")
            env_updates = {"ARM_C_RETRY_ACCEPTED_MERGE": head,
                           "ARM_C_RETRY_REPO": str(repo)}
            old = {k: os.environ.get(k) for k in env_updates}
            os.environ.update(env_updates)
            try:
                with self.assertRaises(RuntimeError):
                    core.verify_accepted_blocker_preservation(repo)
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_control_new_path_in_accepted_namespace_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            mirror = _scratch_mirror(tmp)
            subprocess.run(["git", "-C", str(mirror), "init", "-q"],
                           check=True)
            subprocess.run(["git", "-C", str(mirror), "config",
                            "user.email", "t@example.com"], check=True)
            subprocess.run(["git", "-C", str(mirror), "config",
                            "user.name", "t"], check=True)
            subprocess.run(["git", "-C", str(mirror), "add", "-A"],
                           check=True)
            subprocess.run(["git", "-C", str(mirror), "commit", "-qm",
                            "accepted base"], check=True)
            head = subprocess.run(
                ["git", "-C", str(mirror), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True).stdout.strip()
            extra = (mirror / AREA.relative_to(ROOT) / "evidence" / "arm-c"
                     / "issue129-extra.txt")
            extra.write_text("not allowed\n")
            old_merge = os.environ.get("ARM_C_RETRY_ACCEPTED_MERGE")
            os.environ["ARM_C_RETRY_ACCEPTED_MERGE"] = head
            try:
                with self.assertRaisesRegex(RuntimeError,
                                            "introduced paths"):
                    core.verify_accepted_blocker_preservation(mirror)
            finally:
                if old_merge is None:
                    os.environ.pop("ARM_C_RETRY_ACCEPTED_MERGE", None)
                else:
                    os.environ["ARM_C_RETRY_ACCEPTED_MERGE"] = old_merge

    def test_blocker_reducer_historical_mode_available(self):
        # the accepted #128 reducer derives the blocker at the accepted
        # merge (historical-verification mode); the audited head stays
        # the accepted audit's own head_classified (never advanced)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "issue117_arm_c_blocker_reducer",
            ROOT / "scripts/issue117_arm_c_blocker_reducer.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.reduce_all(head=self.MERGE)
        self.assertEqual(result["terminal"], module.BLOCKED)
        retained = json.loads(
            (ARM_C / "blocker-reduction.json").read_text())
        self.assertEqual(result["head_audited"],
                         retained["head_audited"])
        self.assertEqual(result["authority"]["audited_head"],
                         retained["authority"]["audited_head"])


class MandatoryNegativeControlTests(unittest.TestCase):
    """Every issue-#129 mandatory negative control fails closed."""

    def _require_blocked(self, reduction):
        self.assertFalse(reduction["passed"],
                         "mutated control must not pass")
        self.assertEqual(reduction["terminal"], core.METHODOLOGY_BLOCKED)

    def test_control_direct_single_shot_max_new_tokens_8(self):
        arms = _arms(direct_variant="single_shot_8")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_wrong_replay_prefix(self):
        arms = _arms(direct_variant="wrong_replay_prefix")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_call_count_change(self):
        arms = _arms(direct_variant="call_count_skip")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_commit_speculative_second_token(self):
        arms = _arms(direct_variant="commit_speculative")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_runtime_session_allocation_only_change(self):
        # Finding 2 negative control: ONLY the runtime-session ID
        # allocation/sequence differs (shift by one); replay ids,
        # outputs, max tokens, and everything else stay identical
        arms = _arms(direct_session_sequence_start=1)
        ordinary = arms["ordinary"]["per_case"]
        direct = arms["direct"]["per_case"]
        for case_id in sorted(ordinary):
            self.assertNotEqual(
                [c["runtime_session_id"] for c in ordinary[case_id]["calls"]],
                [c["runtime_session_id"] for c in direct[case_id]["calls"]],
                f"{case_id}: control must change the session sequence")
            self.assertEqual(
                [c["prompt_token_ids"] for c in ordinary[case_id]["calls"]],
                [c["prompt_token_ids"] for c in direct[case_id]["calls"]],
                f"{case_id}: control must leave replay prefixes identical")
            self.assertEqual(
                [c["response_commit_token_id"]
                 for c in ordinary[case_id]["calls"]],
                [c["response_commit_token_id"]
                 for c in direct[case_id]["calls"]],
                f"{case_id}: control must leave outputs identical")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_sampling_inputs_differ(self):
        arms = _arms(direct_sampling={
            "temperature": 0.7, "top_k": -1, "top_p": 1.0})
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_prompt_token_ids_differ(self):
        def mangle(case_id, ids):
            return ids[:-1]
        arms = _arms(direct_prompt_mangle=mangle)
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_stopping_policy_differs(self):
        arms = _arms(direct_stopping={
            "kind": "eos_or_length", "committed_tokens": 8})
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_control_plane_field_leaks_into_model_inputs(self):
        arms = _arms(direct_variant="control_plane_field_leak")
        self._require_blocked(core.reduce_transcripts(
            arms["ordinary"], arms["direct"]))

    def test_control_mutable_deployment_identity_permitted(self):
        verdict = core.verify_deployment_identity({
            "repository_sha": "9" * 40,
            "file_sha256": "a" * 64,
            "expected_path": "/srv/inferswarm/run/driver.py",
            "read_only": False,  # mutable staged script
            "pre_launch_verified": True,
            "post_run_verified": True,
            "post_run_file_sha256": "a" * 64,
        })
        self.assertFalse(verdict["ok"])
        self.assertIn("mutable", verdict["reason"])

    def test_control_script_changed_after_freeze(self):
        verdict = core.verify_deployment_identity({
            "repository_sha": "9" * 40,
            "file_sha256": "a" * 64,
            "expected_path": "/srv/inferswarm/run/driver.py",
            "read_only": True,
            "pre_launch_verified": True,
            "post_run_verified": True,
            "post_run_file_sha256": "b" * 64,  # changed after freeze
        })
        self.assertFalse(verdict["ok"])
        self.assertIn("changed after freeze", verdict["reason"])

    def test_control_unpinned_deployment_identity(self):
        for missing in ("repository_sha", "file_sha256",
                        "pre_launch_verified", "post_run_verified"):
            record = self._valid_identity()
            record.pop(missing)
            verdict = core.verify_deployment_identity(record)
            self.assertFalse(verdict["ok"], missing)

    def test_control_missing_post_run_sha_fails_closed(self):
        # P1 hardening (review 1): the byte-level post-run check is
        # mandatory — no ok verdict on attestation alone
        record = self._valid_identity()
        record.pop("post_run_file_sha256")
        verdict = core.verify_deployment_identity(record)
        self.assertFalse(verdict["ok"])
        self.assertIn("post-run file sha256", verdict["reason"])

    @staticmethod
    def _valid_identity():
        return {
            "repository_sha": "9" * 40,
            "file_sha256": "a" * 64,
            "expected_path": "/srv/inferswarm/run/driver.py",
            "read_only": True,
            "pre_launch_verified": True,
            "post_run_verified": True,
            "post_run_file_sha256": "a" * 64,
        }

    def test_control_invalid_attempt_continues_without_stop(self):
        attempts = [
            self._facts(attempt_id="retry-1",
                        correctness_bearing_result_emitted=True,
                        frozen_identity_verified_pre_launch=False),
            self._facts(attempt_id="retry-2",
                        correctness_bearing_result_emitted=True),
        ]
        reduction = _reduce(attempts)
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][0]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertEqual(
            reduction["events"][0]["stop_rule_fired"],
            "invalid_correctness_bearing_observation")
        self.assertEqual(
            reduction["events"][1]["stop_rule_fired"],
            "invalid_correctness_bearing_observation")

    def test_control_stored_equal_substitutes_for_derivation(self):
        # the reducer must re-derive: feeding doctored documents whose
        # stored per-case 'equal' claims true while the transcripts differ
        # must still fail (the reducer never reads stored equality)
        arms = _arms(direct_variant="wrong_replay_prefix")
        doctored_direct = copy.deepcopy(arms["direct"])
        for case in doctored_direct["per_case"].values():
            case["equal"] = True  # stored lie
        doctored_direct["terminal"] = core.METHODOLOGY_READY  # stored lie
        reduction = core.reduce_transcripts(arms["ordinary"], doctored_direct)
        self.assertFalse(reduction["passed"])
        self.assertEqual(reduction["terminal"], core.METHODOLOGY_BLOCKED)

    @staticmethod
    def _facts(**overrides):
        return _attempt_facts(**overrides)


class AttemptStateMachineTests(unittest.TestCase):
    def _facts(self, **overrides):
        return _attempt_facts(**overrides)

    def test_pre_observation_infrastructure(self):
        self.assertEqual(
            core.classify_attempt(self._facts()),
            "PRE_OBSERVATION_INFRASTRUCTURE")

    def test_correctness_bearing_valid(self):
        self.assertEqual(
            core.classify_attempt(self._facts(
                correctness_bearing_result_emitted=True,
                coordinator_commit_occurred=True)),
            "CORRECTNESS_BEARING_VALID")

    def test_control_cb_while_methodology_readiness_false(self):
        classification = core.classify_attempt(self._facts(
            correctness_bearing_result_emitted=True,
            methodology_gate_passed=False))
        self.assertEqual(classification, "CORRECTNESS_BEARING_INVALID")
        reduction = _reduce([self._facts(
            attempt_id="no-readiness",
            correctness_bearing_result_emitted=True,
            methodology_gate_passed=False)])
        self.assertFalse(reduction["passed"])
        self.assertEqual(reduction["events"][0]["stop_rule_fired"],
                         "invalid_correctness_bearing_observation")
        self.assertIn("methodology readiness",
                      reduction["mandatory_stop_events"][0])

    def test_control_cb_while_physical_authorization_false(self):
        classification = core.classify_attempt(self._facts(
            correctness_bearing_result_emitted=True,
            physical_retry_authorized=False))
        self.assertEqual(classification, "CORRECTNESS_BEARING_INVALID")
        reduction = _reduce([self._facts(
            attempt_id="no-authorization",
            correctness_bearing_result_emitted=True,
            physical_retry_authorized=False)])
        self.assertFalse(reduction["passed"])
        self.assertIn("physical retry not authorized",
                      reduction["mandatory_stop_events"][0])

    def test_control_same_campaign_terminal_cannot_clear_stop(
            self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(attempt_id="terminal-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        self.assertEqual(
            reduction["events"][1]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertFalse(reduction["events"][1]["authoritative"])
        self.assertFalse(reduction["passed"])
        self.assertTrue(reduction["final_state"]["stop_fired"])
        self.assertFalse(reduction["final_state"]["terminal_seen"])

    def test_control_post_stop_diagnostic_remains_non_authoritative(self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(attempt_id="diagnostic-1",
                        correctness_bearing_result_emitted=True,
                        diagnostic_only_disclosure=True,
                        physical_retry_authorized=False),
        ])
        self.assertEqual(
            reduction["events"][1]["classification"],
            "DIAGNOSTIC_ONLY_AFTER_STOP")
        self.assertFalse(reduction["events"][1]["authoritative"])
        # the diagnostic cleared neither the STOP nor the terminal
        # requirement; the campaign remains stopped (not passed)
        self.assertTrue(reduction["final_state"]["stop_fired"])
        self.assertFalse(reduction["final_state"]["terminal_seen"])
        self.assertFalse(reduction["passed"])
        self.assertEqual(reduction["problems"], [])

    def test_control_non_cb_marker_cannot_clear_stop(self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(attempt_id="marker-1",
                        terminal_observation=True),
        ])
        self.assertEqual(
            reduction["events"][1]["classification"],
            "TERMINAL_MARKER_NON_CORRECTNESS_BEARING")
        self.assertEqual(
            reduction["events"][1]["stop_rule_fired"],
            "non_correctness_bearing_terminal_cannot_clear_stop")
        self.assertFalse(reduction["passed"])
        self.assertTrue(reduction["final_state"]["stop_fired"])

    def test_control_continuation_after_stop_without_authorized_terminal(
            self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(attempt_id="continuation-1",
                        correctness_bearing_result_emitted=True),
        ])
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][1]["stop_rule_fired"],
            "invalid_correctness_bearing_observation")

    def test_terminal_without_prior_stop_passes(self):
        reduction = _reduce([
            self._facts(attempt_id="terminal-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        self.assertTrue(reduction["passed"])

    def test_authored_stop_label_cannot_launder_continuation(self):
        # an authored stop_occurred disclosure with no genuine STOP in
        # the reducer's own history is an ordinary correctness-bearing
        # attempt (here: valid and authorized, but not terminal)
        reduction = _reduce([
            self._facts(attempt_id="claimed-stop",
                        correctness_bearing_result_emitted=True,
                        stop_occurred=True),
        ])
        self.assertEqual(reduction["events"][0]["classification"],
                         "CORRECTNESS_BEARING_VALID")
        self.assertFalse(reduction["passed"])

    def test_unauthorized_terminal_claim_is_invalid(self):
        # a terminal attempt claiming correctness-bearing output
        # without authorization stays INVALID (fires the STOP)
        reduction = _reduce([
            self._facts(attempt_id="terminal-unauthorized",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True,
                        physical_retry_authorized=False),
        ])
        self.assertEqual(
            reduction["events"][0]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertFalse(reduction["passed"])

    def test_missing_facts_fail_closed(self):
        with self.assertRaises(ValueError):
            core.classify_attempt({"attempt_id": "a"})

    def test_legal_sequence_passes(self):
        reduction = _reduce([
            self._facts(attempt_id="infra-1", gpu_execution_occurred=True),
            self._facts(attempt_id="valid-1",
                        correctness_bearing_result_emitted=True,
                        coordinator_commit_occurred=True,
                        terminal_observation=True),
        ])
        self.assertTrue(reduction["passed"])

    def test_methodology_gate_passed_is_load_bearing(self):
        # the field gates correctness-bearing validity directly (it is
        # not inert): with readiness false even a fully-authorized,
        # identity-clean attempt is INVALID
        self.assertEqual(
            core.classify_attempt(self._facts(
                correctness_bearing_result_emitted=True,
                methodology_gate_passed=False)),
            "CORRECTNESS_BEARING_INVALID")

    def test_self_checks_pass(self):
        result = core.run_attempt_state_self_checks()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["rows"]), 13)

    def test_control_boolean_only_authorization_change_is_rejected(self):
        attempts = [
            self._facts(attempt_id="infra-not-authorized",
                        physical_retry_authorized=False),
            self._facts(attempt_id="terminal-boolean-flip",
                        observed_at="2026-09-09T00:00:02Z",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True,
                        physical_retry_authorized=True),
        ]
        reduction = _reduce(attempts)
        self.assertFalse(reduction["passed"])
        self.assertFalse(reduction["events"][1]["authoritative"])
        self.assertTrue(any(
            "accepted field physical_retry_authorized" in problem
            or "changed authority field physical_retry_authorized" in problem
            for problem in reduction["problems"]))

    def test_control_campaign_requires_authoritative_terminal(self):
        infrastructure = _reduce([
            self._facts(attempt_id="infra-only")])
        nonterminal = _reduce([
            self._facts(attempt_id="valid-nonterminal",
                        correctness_bearing_result_emitted=True)])
        self.assertFalse(infrastructure["passed"])
        self.assertFalse(nonterminal["passed"])
        self.assertFalse(
            infrastructure["campaigns"]["campaign-A"]
            ["terminal_authoritative"])
        self.assertFalse(
            nonterminal["campaigns"]["campaign-A"]
            ["terminal_authoritative"])

    def test_control_intermediate_campaign_cannot_bypass_stop_review(self):
        attempts = [
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(campaign_id="campaign-B", attempt_id="b-infra"),
            self._facts(
                campaign_id="campaign-C", attempt_id="c-terminal",
                observed_at="2026-09-09T00:00:06Z",
                physical_authorization_id="authorization-C",
                campaign_lineage_root="lineage-C",
                physical_authorization_issued_at="2026-09-09T00:00:00Z",
                prior_stopped_campaign_id=None,
                prior_stop_attempt_id=None,
                prior_stop_review_id=None,
                prior_stop_reviewed_at=None,
                correctness_bearing_result_emitted=True,
                terminal_observation=True),
        ]
        reduction = _reduce(attempts)
        self.assertFalse(reduction["passed"])
        self.assertTrue(any(
            "intermediate campaign cannot bypass" in problem
            for problem in reduction["problems"]))

    def test_control_diagnostic_disclosure_is_never_verdict_authority(self):
        reduction = _reduce([
            self._facts(attempt_id="diagnostic-terminal",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True,
                        diagnostic_only_disclosure=True),
        ])
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][0]["classification"], "DIAGNOSTIC_ONLY")
        self.assertFalse(reduction["events"][0]["authoritative"])
        self.assertFalse(reduction["final_state"]["terminal_seen"])

    def test_control_diagnostic_cannot_hide_methodology_failure(self):
        reduction = _reduce([
            self._facts(attempt_id="diagnostic-no-methodology",
                        correctness_bearing_result_emitted=True,
                        diagnostic_only_disclosure=True,
                        methodology_gate_passed=False),
            self._facts(attempt_id="terminal-after-laundering",
                        observed_at="2026-09-09T00:00:02Z",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][0]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertTrue(reduction["campaigns"]["campaign-A"]["blocked"])

    def test_control_diagnostic_cannot_hide_deployment_failure(self):
        reduction = _reduce([
            self._facts(attempt_id="diagnostic-bad-deployment",
                        correctness_bearing_result_emitted=True,
                        diagnostic_only_disclosure=True,
                        frozen_identity_verified_pre_launch=False),
            self._facts(attempt_id="terminal-after-laundering",
                        observed_at="2026-09-09T00:00:02Z",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][0]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertTrue(reduction["campaigns"]["campaign-A"]["blocked"])

    def test_control_attempt_identity_must_match_accepted_authority(self):
        accepted_attempt = self._facts(
            attempt_id="accepted-terminal",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)
        hostile_attempt = dict(accepted_attempt)
        hostile_attempt["methodology_ready_identity"] = "0" * 40
        reduction = _reduce(
            [hostile_attempt],
            accepted_authorities=
                _accepted_authority_records([accepted_attempt]))
        self.assertFalse(reduction["passed"])
        self.assertFalse(reduction["events"][0]["authoritative"])
        self.assertTrue(reduction["campaigns"]["campaign-A"]["blocked"])
        self.assertTrue(any(
            "accepted field methodology_ready_identity" in problem
            for problem in reduction["problems"]))

    def test_control_missing_accepted_authority_fails_closed(self):
        reduction = _reduce([
            self._facts(attempt_id="terminal-without-authority",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ], accepted_authorities={})
        self.assertFalse(reduction["passed"])
        self.assertFalse(reduction["events"][0]["authoritative"])
        self.assertTrue(any(
            "no accepted campaign authority record" in problem
            for problem in reduction["problems"]))

    def test_control_attempt_facts_cannot_supply_public_authority(self):
        attempts = [self._facts(
            attempt_id="self-authorized-terminal",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)]
        with self.assertRaises(TypeError):
            core.reduce_attempts(
                attempts,
                accepted_campaign_authorities=
                    _accepted_authority_records(attempts))

    def test_public_reducer_fails_closed_without_accepted_authority_file(self):
        attempts = [self._facts(
            attempt_id="terminal-without-recorded-authority",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)]
        with self.assertRaises(RuntimeError):
            core.reduce_attempts(
                attempts,
                accepted_authority_commit=core.ACCEPTED_BLOCKER_MERGE,
                repo_root=ROOT)

    def test_strict_physical_authority_document_binds_campaign(self):
        attempts = [self._facts(
            attempt_id="synthetic-terminal",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)]
        records = core._parse_accepted_campaign_authority_document(
            _physical_authority_document(attempts))
        self.assertEqual(records, _accepted_authority_records(attempts))

    def test_control_merge_does_not_imply_execution_authorization(self):
        attempts = [self._facts(
            attempt_id="synthetic-terminal",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)]
        document = _physical_authority_document(attempts)
        document["execution_authorization"][
            "physical_retry_authorized"] = False
        with self.assertRaisesRegex(RuntimeError, "not authorized"):
            core._parse_accepted_campaign_authority_document(document)

    def test_public_reducer_loads_authority_from_accepted_git_bytes(self):
        attempts = [self._facts(
            attempt_id="accepted-terminal",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commit, raw = _init_scratch_authority_repo(
                root, _physical_authority_document(attempts))
            reduction = core.reduce_attempts(
                attempts, accepted_authority_commit=commit, repo_root=root)
            blob_oid = subprocess.run(
                ["git", "rev-parse",
                 f"{commit}:{core.PHYSICAL_CAMPAIGN_AUTHORITY_PATH}"],
                cwd=root, check=True, capture_output=True,
                text=True).stdout.strip()
        self.assertTrue(reduction["passed"])
        self.assertEqual(
            reduction["accepted_authority_source"]["commit"], commit)
        self.assertEqual(
            reduction["accepted_authority_source"]["sha256"],
            core.sha256_bytes(raw))
        self.assertEqual(
            reduction["accepted_authority_source"]["git_blob_oid"], blob_oid)

    def test_control_public_reducer_rejects_nonaccepted_commit(self):
        attempts = [self._facts(
            attempt_id="unaccepted-terminal",
            correctness_bearing_result_emitted=True,
            terminal_observation=True)]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _ = _init_scratch_authority_repo(
                root, _physical_authority_document(attempts))
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m",
                 "test: unaccepted descendant"], cwd=root, check=True)
            unaccepted_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True).stdout.strip()
            with self.assertRaisesRegex(RuntimeError, "not on"):
                core.reduce_attempts(
                    attempts, accepted_authority_commit=unaccepted_commit,
                    repo_root=root)

    def test_control_stop_review_watermark_survives_terminal_campaign(self):
        attempts = [
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(campaign_id="campaign-B", attempt_id="b-terminal",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
            self._facts(
                campaign_id="campaign-C", attempt_id="c-terminal",
                observed_at="2026-09-09T00:00:06Z",
                physical_authorization_id="authorization-C",
                campaign_lineage_root="lineage-C",
                physical_authorization_issued_at="2026-09-09T00:00:00Z",
                prior_stopped_campaign_id="campaign-A",
                prior_stop_attempt_id="invalid-1",
                prior_stop_review_id="maintainer-review-A",
                prior_stop_reviewed_at="2026-09-09T00:00:03Z",
                correctness_bearing_result_emitted=True,
                terminal_observation=True),
        ]
        reduction = _reduce(attempts)
        self.assertFalse(reduction["passed"])
        self.assertTrue(any(
            "not issued after the prior STOP and review" in problem
            for problem in reduction["problems"]))

    def test_control_post_terminal_undisclosed_continuation(self):
        # review 1 P1: a correctness-bearing attempt after the
        # campaign's terminal observation, WITHOUT a diagnostic
        # disclosure, must fail closed (never silently auto-labeled
        # diagnostic)
        reduction = _reduce([
            self._facts(attempt_id="terminal-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
            self._facts(attempt_id="undisclosed-continuation",
                        correctness_bearing_result_emitted=True),
            self._facts(attempt_id="undisclosed-continuation-2",
                        correctness_bearing_result_emitted=True),
        ])
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["events"][1]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertEqual(
            reduction["events"][2]["classification"],
            "CORRECTNESS_BEARING_INVALID")
        self.assertIn("post-terminal continuation",
                      reduction["mandatory_stop_events"][0])

    def test_post_terminal_disclosed_diagnostic_is_powerless(self):
        reduction = _reduce([
            self._facts(attempt_id="terminal-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
            self._facts(attempt_id="disclosed-diagnostic",
                        correctness_bearing_result_emitted=True,
                        diagnostic_only_disclosure=True),
        ])
        self.assertEqual(
            reduction["events"][1]["classification"],
            "DIAGNOSTIC_ONLY_AFTER_STOP")
        self.assertFalse(reduction["events"][1]["authoritative"])
        self.assertTrue(reduction["passed"])

    def test_control_terminal_clears_no_fired_stop(self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(attempt_id="invalid-2",
                        correctness_bearing_result_emitted=True,
                        methodology_gate_passed=False),
            self._facts(attempt_id="terminal-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        self.assertFalse(reduction["passed"])
        self.assertTrue(reduction["final_state"]["stop_fired"])
        self.assertEqual(len(reduction["unresolved_mandatory_stops"]), 3)
        self.assertTrue(all("cleared by" not in event
                            for event in reduction["mandatory_stop_events"]))

    def test_continuation_event_firing_a_rule_is_non_authoritative(self):
        # review 1 P2: an event that fires a continuation stop rule is
        # recorded non-authoritative whatever its class label
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(attempt_id="continuation-1",
                        correctness_bearing_result_emitted=True),
        ])
        self.assertEqual(reduction["events"][1]["classification"],
                         "CORRECTNESS_BEARING_INVALID")
        self.assertFalse(reduction["events"][1]["authoritative"])

    def test_control_authorization_id_change_without_campaign_change(self):
        reduction = _reduce([
            self._facts(attempt_id="a-1"),
            self._facts(attempt_id="a-2",
                        physical_authorization_id="authorization-other",
                        observed_at="2026-09-09T00:00:02Z"),
        ])
        self.assertFalse(reduction["passed"])
        self.assertTrue(any("changed authority field" in problem
                            for problem in reduction["problems"]))
        self.assertFalse(reduction["events"][1]["authoritative"])

    def test_control_reused_authorization_for_new_campaign(self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(campaign_id="campaign-B", attempt_id="b-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True,
                        physical_authorization_id="authorization-A"),
        ])
        self.assertFalse(reduction["passed"])
        self.assertTrue(any("reuses physical authorization" in problem
                            for problem in reduction["problems"]))
        self.assertFalse(reduction["events"][1]["authoritative"])

    def test_control_new_campaign_authorization_predates_review(self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(campaign_id="campaign-B", attempt_id="b-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True,
                        physical_authorization_issued_at=
                        "2026-09-09T00:00:02Z"),
        ])
        self.assertFalse(reduction["passed"])
        self.assertTrue(any("not issued after" in problem
                            for problem in reduction["problems"]))

    def test_fresh_post_review_campaign_is_independent(self):
        reduction = _reduce([
            self._facts(attempt_id="invalid-1",
                        correctness_bearing_result_emitted=True,
                        physical_retry_authorized=False),
            self._facts(campaign_id="campaign-B", attempt_id="b-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        self.assertTrue(reduction["passed"])
        self.assertTrue(reduction["campaigns"]["campaign-A"]["blocked"])
        self.assertFalse(
            reduction["campaigns"]["campaign-A"]["terminal_seen"])
        self.assertTrue(reduction["campaigns"]["campaign-B"]["passed"])
        self.assertTrue(reduction["campaigns"]["campaign-B"]["terminal_seen"])

    def test_all_attempts_carry_campaign_authority_identities(self):
        reduction = _reduce([
            self._facts(attempt_id="terminal-1",
                        correctness_bearing_result_emitted=True,
                        terminal_observation=True),
        ])
        event = reduction["events"][0]
        for field in ("campaign_id", "physical_authorization_id",
                      "methodology_ready_identity",
                      "execution_freeze_identity", "attempt_id"):
            self.assertTrue(event[field])


class FrozenPinTests(unittest.TestCase):
    """Finding 4: frozen-byte pinning fails closed, inherited #128 pins
    included."""

    def test_every_frozen_control_plane_byte_matches_its_pin(self):
        digests = core.verify_frozen_bytes(ROOT)
        self.assertEqual(
            len(digests), len(core.FROZEN_CONTROL_PLANE_FILES))
        # the inherited files are covered by the accepted #128 pins too
        pins = core.load_inherited_pins(ROOT)
        for rel, digest in digests.items():
            if rel in pins:
                self.assertEqual(pins[rel], digest)

    def test_mutated_frozen_byte_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            target = (mirror / AREA.relative_to(ROOT) / "evidence"
                      / "arm-c-retry" / "frozen-source" / "924cd22e"
                      / "python" / "freetoken" / "research"
                      / "r3_planner.py")
            original = target.read_bytes()
            target.write_bytes(original + b"\n# mutation\n")
            with self.assertRaises(RuntimeError):
                core.verify_frozen_bytes(mirror)

    def test_mutated_r5b_epochs_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            target = (mirror / AREA.relative_to(ROOT) / "evidence"
                      / "arm-c" / "frozen-freetoken" / "924cd22e"
                      / "python" / "freetoken" / "research"
                      / "r5b_epochs.py")
            original = target.read_bytes()
            target.write_bytes(original + b"\n# mutation\n")
            with self.assertRaises(RuntimeError):
                core.verify_frozen_bytes(mirror)

    def test_mutated_xc_strategy_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            target = (mirror / AREA.relative_to(ROOT) / "evidence"
                      / "arm-c" / "frozen-freetoken" / "924cd22e"
                      / "benchmarks" / "inferswarm_r6"
                      / "xc_strategy.py")
            original = target.read_bytes()
            target.write_bytes(original + b"\n# mutation\n")
            with self.assertRaises(RuntimeError):
                core.verify_frozen_bytes(mirror)

    def test_missing_frozen_byte_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            target = (mirror / AREA.relative_to(ROOT) / "evidence"
                      / "arm-c" / "frozen-freetoken" / "924cd22e"
                      / "python" / "freetoken" / "research"
                      / "r5b_epochs.py")
            target.unlink()
            with self.assertRaises(FileNotFoundError):
                core.verify_frozen_bytes(mirror)

    def test_control_missing_pins_module_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            (mirror / "scripts" / "issue117_arm_c_frozen_pins.py").unlink()
            with self.assertRaises(FileNotFoundError):
                core.verify_frozen_bytes(mirror)

    def test_control_broken_pins_module_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            (mirror / "scripts" / "issue117_arm_c_frozen_pins.py").write_text(
                "def broken(:\n")
            with self.assertRaises(SyntaxError):
                core.verify_frozen_bytes(mirror)

    def test_control_missing_inherited_pin_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            pins_path = mirror / "scripts" / "issue117_arm_c_frozen_pins.py"
            pins = core.load_inherited_pins(ROOT)
            epochs_rel = ("docs/implementation/r6-successor-dense-full-"
                          "integration-117/evidence/arm-c/frozen-freetoken/"
                          "924cd22e/python/freetoken/research/r5b_epochs.py")
            # rewrite the pins module WITHOUT the inherited r5b_epochs
            # key (the delegated pin vanishes; verification must fail
            # closed rather than silently skip the file)
            reduced = {k: v for k, v in pins.items() if k != epochs_rel}
            pins_path.write_text(
                "FROZEN_SHA256 = " + json.dumps(reduced, indent=2) + "\n")
            with self.assertRaises(RuntimeError):
                core.verify_frozen_bytes(mirror)

    def test_control_malformed_inherited_pin_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            pins_path = mirror / "scripts" / "issue117_arm_c_frozen_pins.py"
            source = pins_path.read_text()
            # replace one hex half of the xc_strategy pin with 'z's
            mutated = source.replace(
                "8d33b4b297a20511448ab78909d2f528",
                "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz", 1)
            self.assertNotEqual(mutated, source)
            pins_path.write_text(mutated)
            with self.assertRaises(RuntimeError):
                core.verify_frozen_bytes(mirror)


class RuntimeSessionAllocatorTests(unittest.TestCase):
    def test_allocator_extraction_facts(self):
        allocator = core.extract_runtime_session_allocator(ROOT)
        self.assertEqual(allocator.facts["multiplier"], 1_000_000)
        self.assertEqual(
            allocator.allocate(1), 1_000_001)
        self.assertEqual(allocator.allocate(1), 1_000_002)
        self.assertEqual(allocator.allocate(7), 7_000_003)

    def test_control_drifted_epochs_source_fails_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            target = (mirror / AREA.relative_to(ROOT) / "evidence"
                      / "arm-c" / "frozen-freetoken" / "924cd22e"
                      / "python" / "freetoken" / "research"
                      / "r5b_epochs.py")
            original = target.read_bytes()
            target.write_bytes(original + b"\n# mutation\n")
            with self.assertRaises(RuntimeError):
                core.extract_runtime_session_allocator(mirror)


class PromptFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = core.derive_prompt_fixture(ROOT)

    def test_exactly_24_accepted_cases_with_digest(self):
        self.assertEqual(self.fixture["case_count"], 24)
        self.assertEqual(
            self.fixture["authority"]["accepted_fixture_digest"],
            core.FIXTURE_DIGEST_24)
        case_ids = {case["case_id"] for case in self.fixture["cases"]}
        self.assertTrue(all(cid.startswith("c109-") for cid in case_ids))
        self.assertFalse(any(cid.startswith("h109-")
                             for cid in case_ids))

    def test_derivation_fails_closed_on_render_equality_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            mirror = _scratch_mirror(tmp)
            report_path = (mirror / AREA.relative_to(ROOT) / "evidence"
                           / "arm-c" / "coordinator-report.json")
            report = json.loads(report_path.read_text())
            report["coordinator_scope"]["requests"][0][
                "prompt_token_ids"][0] += 1
            report_path.write_text(json.dumps(report))
            with self.assertRaises(RuntimeError):
                core.derive_prompt_fixture(mirror)

    def test_retained_fixture_json_matches_derivation(self):
        path = RETRY_EVIDENCE / "prompt-fixture.json"
        self.assertTrue(path.is_file(), "prompt-fixture.json not retained")
        retained = json.loads(path.read_text())
        self.assertEqual(
            retained["fixture_digest"], self.fixture["fixture_digest"])


class RetainedEvidenceTests(unittest.TestCase):
    def test_methodology_run_json_is_retained_and_current(self):
        path = RETRY_EVIDENCE / "methodology-run.json"
        self.assertTrue(path.is_file(), "methodology-run.json not retained")
        document = json.loads(path.read_text())
        self.assertEqual(document["schema"],
                         "inferswarm.issue129.methodology-run/4")
        self.assertEqual(document["terminal"], core.METHODOLOGY_READY)
        fresh = core.run_methodology(ROOT)
        self.assertEqual(document["terminal"], fresh["terminal"])
        self.assertEqual(document["fixture"]["fixture_digest"],
                         fresh["fixture"]["fixture_digest"])
        self.assertEqual(document["per_case_reduction"]["equal_count"], 24)
        self.assertEqual(document["ordinary_ingress"]["equal_count"], 24)
        self.assertTrue(
            document["accepted_blocker_preservation"]["preserved"])

    def test_authority_and_integrity_records_retained(self):
        authority = json.loads(
            (RETRY_EVIDENCE / "authority.json").read_text())
        self.assertEqual(
            authority["schema"],
            "inferswarm.issue129.arm-c-retry-authority/3")
        self.assertTrue(
            authority["accepted_blocker_preservation"]["preserved"])
        integrity = json.loads(
            (RETRY_EVIDENCE / "integrity.json").read_text())
        self.assertEqual(
            integrity["schema"],
            "inferswarm.issue129.arm-c-retry-integrity/2")
        self.assertIn("runtime_session_allocation", integrity)
        self.assertIn("content_encodings_pin", integrity)
        self.assertEqual(integrity["real_tokenizer_proof"]["equal_count"], 24)
        self.assertTrue(integrity["real_tokenizer_proof"]["passed"])


if __name__ == "__main__":
    unittest.main()
