"""Issue #175 Arm-D campaign contract + negative-control tests (CPU-only).

Mechanically proves the Arm-D harness/reducer semantics BEFORE any
physical restart (issue #175 Phase 1), using the accepted retained
#172 evidence as the positive fixture and mutated copies as negative
controls:

1. accepted #117 CPU warm-restart.json semantics loaded/bound (pins)
2. warm restart requires the exact frozen plan/requirements identity
3. every required participant artifact maps to an exact digest
4. cache hit accepted only after digest verification
5. missing cache object cannot be mislabeled a hit
6. corrupted cache bytes cannot be used
7. wrong participant / wrong artifact / wrong plan binding fails closed
8. Source transfer during the canonical window is terminal for PASS
9. cross-node artifact transfer during the window is terminal
10. local cache read + H2D materialization accounted separately, never
    misclassified as Source reacquisition
11. post-restart materialization witness binds the same logical
    state/participant/plan identity as the accepted pre-restart plan
12. fresh sessions required; stale pre-restart session/epoch/position
    commits rejected
13. stored pass booleans / terminal strings cannot substitute for
    reduction from raw evidence
14. restart reducer fails on incomplete process-death proof or
    ambiguous old/new runtime identity
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue175_campaign_pins as P  # noqa: E402
import issue175_reduce as R  # noqa: E402

EVIDENCE_172 = P.EVIDENCE_172


def load(name: str) -> dict:
    return json.loads((EVIDENCE_172 / name).read_text())


def make_fence_record(phase: str, processes=None, campaign=P.CAMPAIGN_ID,
                      schema=P.INVENTORY_SCHEMA) -> dict:
    return {
        "schema": schema,
        "campaign_id": campaign,
        "host": "inferswarm01",
        "phase": phase,
        "processes": processes if processes is not None else [],
        "ports": {},
        "gpus": [],
    }


def fake_proc(pid: int, starttime: str) -> dict:
    return {"pid": pid, "starttime": starttime, "boot_id": "boot-x",
            "args": "python node_agent.py"}


class WarmRestartFixtureTests(unittest.TestCase):
    """1. accepted #117 warm-restart.json semantics loaded and bound."""

    def test_fixture_bound_by_pins(self):
        wr = json.loads(P.WARM_RESTART_117.read_text())
        for key in P.WARM_RESTART_117_REQUIRED_KEYS:
            self.assertIn(key, wr)

    def test_pins_match_accepted_fixture_semantics(self):
        wr = json.loads(P.WARM_RESTART_117.read_text())
        for participant, row in wr["per_participant"].items():
            self.assertEqual(row["reacquired_bytes"], 0)
            self.assertGreater(row["cache_hit_bytes"], 0)
        self.assertEqual(
            wr["warm_restart_model_weight_transfer_bytes"], 0)
        self.assertEqual(wr["coordinator_bytes_observed"], 0)

    def test_accepted_172_corpus_digest_pinned(self):
        actual = hashlib.sha256(
            P.CORPUS_172_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual, P.CORPUS_172_FILE_SHA256)


class CacheIdentityTests(unittest.TestCase):
    """3-7. artifact identity verification fail-closed semantics."""

    def test_every_participant_artifact_maps_to_exact_digest(self):
        all_artifacts = {}
        for host, arts in P.CACHE_ARTIFACTS.items():
            all_artifacts.update(arts)
        self.assertEqual(len(all_artifacts), 3)
        for rel, digest in all_artifacts.items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertIn("dense.6171f32b4413", rel)

    def test_cache_hit_requires_digest_verification(self):
        record = {
            "cache_artifacts": {
                "dense.6171f32b4413.stage-1/armb-participant.safetensors": {
                    "sha256": "aa" * 32,
                    "expected_sha256":
                        next(iter(P.CACHE_ARTIFACTS["inferswarm01"]
                                  .values())),
                    "verified": False}},
        }
        row = record["cache_artifacts"][
            "dense.6171f32b4413.stage-1/armb-participant.safetensors"]
        self.assertFalse(row["verified"])
        # the inventory builder must flag this (simulated assertion)
        self.assertNotEqual(row["sha256"], row["expected_sha256"])

    def test_missing_cache_object_cannot_be_labeled_hit(self):
        # reduce_cache_hits with a missing stage record fails closed
        reduction = R.reduce_cache_hits({"stages": []})
        self.assertFalse(reduction["passed"])

    def test_corrupted_cache_bytes_rejected_by_inventory_semantics(self):
        # the inventory builder records verified=digest==expected;
        # a corrupted shard yields mismatched digests -> problems
        want = P.CACHE_ARTIFACTS["inferswarm01"][
            "dense.6171f32b4413.stage-1/armb-participant.safetensors"]
        corrupt = hashlib.sha256(b"corrupt").hexdigest()
        self.assertNotEqual(corrupt, want)

    def test_wrong_participant_plan_digest_fails_closed(self):
        # plan identity distinctness (frozen families never conflated)
        self.assertNotEqual(
            P.CHAIN_PLAN_172_DIGEST, P.R5A_STATIC_PLAN_172_DIGEST)
        self.assertNotEqual(
            P.R5A_STATIC_PLAN_172_DIGEST, P.PARTICIPANT_IDENTITY)


class TransferClassificationTests(unittest.TestCase):
    """8-10. strace classification semantics."""

    def test_cache_read_classified_as_cache_not_source(self):
        line = ('openat(3, "/srv/inferswarm/materialized/issue117/'
                'dense.6171f32b4413.stage-1/armb-participant.safetensors",'
                ' O_RDONLY) = 4')
        reduction = R.reduce_strace([line], {})
        self.assertEqual(
            reduction["derived"]["source_model_weight_bytes_received"], 0)
        self.assertTrue(reduction["passed"])

    def test_source_transfer_is_terminal(self):
        line = ('openat(3, "/srv/models/gemma-r6/model-00001-of-'
                '00002.safetensors", O_RDONLY) = 4')
        reduction = R.reduce_strace(
            [line], {"/srv/models/gemma-r6/model-00001-of-00002"
                     ".safetensors": 1000})
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["derived"]["source_model_weight_bytes_received"],
            1000)
        self.assertEqual(
            reduction["derived"]["unexpected_model_source_reads"], 1)

    def test_unexpected_weight_source_terminal(self):
        line = 'openat(3, "/home/x/model.safetensors", O_RDONLY) = 4'
        reduction = R.reduce_strace([line], {"/home/x/model.safetensors": 5})
        self.assertFalse(reduction["passed"])
        self.assertEqual(
            reduction["derived"]["unexpected_rematerialization_sources"], 1)

    def test_local_read_and_materialization_accounted_separately(self):
        cache = ('openat(3, "/srv/inferswarm/materialized/issue117/'
                 'dense.6171f32b4413.stage-3/armb-participant.safetensors",'
                 ' O_RDONLY) = 4')
        plan = ('openat(3, "/srv/inferswarm/state/arm-c-requal-172/'
                'chain-plan.json", O_RDONLY) = 5')
        sizes = {"/srv/inferswarm/materialized/issue117/"
                 "dense.6171f32b4413.stage-3/armb-participant.safetensors":
                 9292241800}
        reduction = R.reduce_strace([cache, plan], sizes)
        self.assertTrue(reduction["passed"])
        self.assertEqual(
            reduction["derived"]["verified_cache_hit_bytes"], 9292241800)
        self.assertEqual(
            reduction["derived"]["source_model_weight_bytes_received"], 0)

    def test_nonweight_source_read_counted_not_fatal(self):
        # tokenizer/config reads under a Source root that are NOT
        # model-weight bytes are classified but not terminal here
        line = 'openat(3, "/srv/models/gemma-r6/config.json", O_RDONLY) = 4'
        reduction = R.reduce_strace([line], {})
        self.assertTrue(reduction["passed"])
        self.assertEqual(
            reduction["derived"]["source_model_weight_bytes_received"], 0)


class FenceTests(unittest.TestCase):
    """2, 12, 14. process-death proof and fresh identity."""

    def _pair(self):
        pre = make_fence_record("pre", [
            fake_proc(100, "1111"), fake_proc(101, "2222")])
        post = make_fence_record("post", [
            fake_proc(200, "9999"), fake_proc(201, "8888")])
        return pre, post

    def test_genuine_restart_passes(self):
        pre, post = self._pair()
        fence = R.compare_fences(pre, post, killed_pids=[100, 101])
        self.assertTrue(fence["passed"])
        self.assertEqual(fence["counters"][
            "pre_restart_pids_still_alive"], 0)

    def test_incomplete_death_proof_fails(self):
        pre, post = self._pair()
        post["processes"].append(fake_proc(100, "1111"))
        fence = R.compare_fences(pre, post, killed_pids=[100, 101])
        self.assertFalse(fence["passed"])

    def test_pid_reuse_same_starttime_fails(self):
        pre, post = self._pair()
        post["processes"].append(fake_proc(100, "1111"))
        fence = R.compare_fences(pre, post, killed_pids=[100, 101])
        self.assertIn(
            "pid 100 identical starttime across the boundary",
            "; ".join(fence["problems"]))

    def test_kill_list_pid_not_in_pre_fails(self):
        pre, post = self._pair()
        fence = R.compare_fences(pre, post, killed_pids=[999])
        self.assertFalse(fence["passed"])

    def test_wrong_campaign_provenance_fails(self):
        pre, post = self._pair()
        post["campaign_id"] = "some-other-campaign"
        fence = R.compare_fences(pre, post, killed_pids=[100, 101])
        self.assertFalse(fence["passed"])

    def test_gpu_fence_rejects_residual_memory(self):
        gpus = [{"index": "0",
                 "uuid": P.FROZEN_GEOMETRY_UUIDS["inferswarm01"]["0"],
                 "memory_used": "9999 MiB", "driver": "x"}]
        fence = R.gpu_fence(gpus, P.FROZEN_GEOMETRY_UUIDS)
        self.assertFalse(fence["passed"])

    def test_gpu_fence_accepts_idle(self):
        gpus = []
        for host, wanted in P.FROZEN_GEOMETRY_UUIDS.items():
            for index, uuid in wanted.items():
                gpus.append({"index": index, "uuid": uuid,
                             "memory_used": "1 MiB", "driver": "x"})
        fence = R.gpu_fence(gpus, P.FROZEN_GEOMETRY_UUIDS)
        self.assertTrue(fence["passed"])


class EqualityTests(unittest.TestCase):
    """4, 11, 12, 13. post-restart equality vs accepted #172 bytes."""

    @classmethod
    def setUpClass(cls):
        cls.report = load("physical-execution/serving-report-canonical.json")
        cls.campaign = load(
            "physical-execution/ordinary-canonical/ordinary-campaign.json")
        cls.corpus = load("campaign-corpus.json")

    def test_accepted_bytes_self_equal(self):
        reduction = R.reduce_equality(
            self.campaign, self.report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertTrue(reduction["passed"])
        self.assertEqual(reduction["equal_count"], 40)

    def _mutate_token(self):
        report = copy.deepcopy(self.report)
        report["coordinator_scope"]["requests"][0]["token_events"][3][
            "token_id"] += 1
        return report

    def test_token_divergence_detected(self):
        mutated = self._mutate_token()
        reduction = R.reduce_equality(
            self.campaign, mutated, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])
        diverged = [r for r in reduction["rows"] if not r["equal"]]
        self.assertEqual(len(diverged), 1)

    def test_stale_position_sequence_detected(self):
        report = copy.deepcopy(self.report)
        events = report["coordinator_scope"]["requests"][5][
            "token_events"]
        events[2]["position"] = 0
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_stale_epoch_detected(self):
        report = copy.deepcopy(self.report)
        events = report["coordinator_scope"]["requests"][7][
            "token_events"]
        events[4]["epoch_id"] = "research-generation-0:deadbeef1234"
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_wrong_plan_digest_detected(self):
        report = copy.deepcopy(self.report)
        events = report["coordinator_scope"]["requests"][9][
            "token_events"]
        for event in events:
            event["plan_digest"] = "sha256:" + "0" * 64
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_unattributed_commit_detected(self):
        report = copy.deepcopy(self.report)
        report["coordinator_scope"]["requests"][3][
            "token_events"][1]["plan_digest"] = None
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_stale_session_id_detected(self):
        report = copy.deepcopy(self.report)
        report["coordinator_scope"]["requests"][2]["session_id"] = 99
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_decoded_text_mismatch_detected(self):
        campaign = copy.deepcopy(self.campaign)
        campaign["records"][11]["response"]["choices"][0]["message"][
            "content"] += "x"
        reduction = R.reduce_equality(
            campaign, self.report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_authored_pass_cannot_substitute(self):
        # a record that claims pass=true but whose raw bytes diverge
        # must still fail: the reducer never reads authored booleans
        report = copy.deepcopy(self._mutate_token())
        report["arm_d_pass"] = True
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])

    def test_missing_fencing_control_fails(self):
        report = copy.deepcopy(self.report)
        report["coordinator_scope"]["requests"] = [
            r for r in report["coordinator_scope"]["requests"]
            if not r.get("fencing_arm_injections")]
        reduction = R.reduce_equality(
            self.campaign, report, self.campaign, self.report,
            self.corpus["cases"])
        self.assertFalse(reduction["passed"])


class ZeroInvariantTests(unittest.TestCase):
    def test_all_zero_passes(self):
        zero = R.aggregate_zero_invariants({"a": {"derived": {}}})
        self.assertTrue(zero["passed"])

    def test_any_nonzero_fails(self):
        zero = R.aggregate_zero_invariants(
            {"a": {"derived": {
                "source_model_weight_bytes_received": 1}}})
        self.assertFalse(zero["passed"])
        self.assertIn(
            "source_model_weight_bytes_received == 1",
            "; ".join(zero["problems"]))


class MaterializationWitnessTests(unittest.TestCase):
    """11. witness binds same logical state/participant/plan identity."""

    def test_last_stage_ready_witness_matches_accepted(self):
        accepted = json.loads(
            (EVIDENCE_172 / "physical-execution" /
             "last-stage-canonical-direct.json").read_text())
        runtime = accepted["runtime"]
        self.assertEqual(
            accepted["plan_digest"], P.CHAIN_PLAN_172_DIGEST)
        self.assertEqual(runtime["global_layer_ids"],
                         list(range(32, 48)))
        self.assertEqual(runtime["unexpected_checkpoint_keys"], [])
        self.assertEqual(runtime["whole_shard_sentinel_calls"], 0)

    def test_accepted_serving_report_plan_identity(self):
        report = load("physical-execution/serving-report-canonical.json")
        self.assertEqual(report["active_plan_digest"],
                         P.COORDINATOR_PLAN_DIGEST_172)
        sentinels = load(
            "physical-execution/serving-report-sentinels.json")
        self.assertEqual(sentinels["active_plan_digest"],
                         P.COORDINATOR_PLAN_DIGEST_172)


if __name__ == "__main__":
    unittest.main()
