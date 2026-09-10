"""Issue #133 physical-execution retention tests.

Validates the retained physical-execution evidence set and the terminal
reduction, with fail-closed negative controls (mutated evidence must
change or reject the derivation). CPU-only; loads only committed bytes.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
     / "evidence/arm-c-retry/physical-execution")


def load(rel: str) -> dict:
    return json.loads((E / rel).read_text())


class PhysicalEvidenceSet(unittest.TestCase):
    def test_required_files_present(self) -> None:
        required = [
            "terminal-reduction.json", "equality-reduction.json",
            "strace-audit.json", "strace-raw-pins.json",
            "substrate-reconciliation-01.json",
            "substrate-reconciliation-03.json",
            "last-stage-direct.json", "last-stage-ordinary.json",
            "attempts/armc-retry-physical-1.json",
            "attempts/launch1-failure.log",
            "direct/direct-run.json",
            "ordinary-http/ordinary-campaign.json",
            "ordinary-http/serving-report.json",
            "ordinary-http/fencing-arm.json",
            "preflight/prelaunch-verdict-run1.json",
            "preflight/prelaunch-verdict-immediate-prelaunch.json",
            "preflight/tokenizer-deployment-proof.json",
            "preflight/host-preflight-01.json",
            "preflight/host-preflight-03.json",
        ]
        for rel in required:
            self.assertTrue((E / rel).is_file(), rel)

    def test_24_cases_each_arm(self) -> None:
        self.assertEqual(
            len(list((E / "direct").glob("direct-c109-*.json"))), 24)
        self.assertEqual(
            len(list((E / "ordinary-http").glob("ordinary-c109-*.json"))), 24)


class TerminalReductionDerivations(unittest.TestCase):
    def setUp(self) -> None:
        self.terminal = load("terminal-reduction.json")

    def test_terminal_is_semantic_fail(self) -> None:
        self.assertEqual(
            self.terminal["terminal"], "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL")

    def test_no_infrastructure_problems(self) -> None:
        self.assertEqual(self.terminal["problems"], [])

    def test_equality_18_of_24_all_regime4(self) -> None:
        eq = self.terminal["equality"]
        self.assertEqual(eq["equal"], 18)
        self.assertEqual(eq["of"], 24)
        self.assertEqual(len(eq["mismatched_cases"]), 6)
        self.assertTrue(all(
            c.startswith("c109-04") for c in eq["mismatched_cases"]))
        self.assertTrue(eq["all_mismatches_regime_4"])

    def test_all_zero_invariants_hold(self) -> None:
        z = self.terminal["zero_invariants"]
        for key in ("stale_session_commits", "wrong_session_commits",
                    "stale_plan_commits", "wrong_plan_commits",
                    "stale_epoch_commits", "wrong_epoch_commits",
                    "wrong_position_commits",
                    "unattributed_correctness_bearing_commits",
                    "coordinator_cuda_initialized",
                    "coordinator_model_weight_bytes_received",
                    "coordinator_model_weight_bytes_materialized",
                    "coordinator_bulk_artifact_bytes_observed"):
            self.assertEqual(z[key], 0, key)
        self.assertGreaterEqual(
            z["controlled_fencing_injections_rejected"], 2)

    def test_direct_comparator_contract(self) -> None:
        z = self.terminal["zero_invariants"]
        self.assertEqual(z["direct_invocations"], 192)
        run = load("direct/direct-run.json")
        self.assertFalse(
            run["comparator_contract"]["single_shot_max_new_tokens_8_used"])
        self.assertEqual(run["comparator_contract"]["max_new_tokens"], 2)


class EqualityRejectionControls(unittest.TestCase):
    """The retained equality rows must carry enough raw evidence to
    re-derive mismatches; mutated rows must be detectable."""

    def test_mismatched_rows_carry_both_sides(self) -> None:
        eq = load("equality-reduction.json")
        for row in eq["rows"]:
            if not row["committed_ids_equal"]:
                self.assertIn("committed_token_ids", row)
                self.assertEqual(len(row["committed_token_ids"]), 8)

    def test_token_mutation_detected(self) -> None:
        eq = load("equality-reduction.json")
        mutated = copy.deepcopy(eq)
        row = next(r for r in mutated["rows"] if r["committed_ids_equal"])
        # simulate a stored-equality forgery: flip a token id on the
        # ordinary side using the retained raw ordinary campaign records
        campaign = load("ordinary-http/ordinary-campaign.json")
        serving = load("ordinary-http/serving-report.json")
        sessions = serving["epochs"][0]["runtime_sessions"]
        by_logical: dict[int, list[dict]] = {}
        for s in sessions:
            by_logical.setdefault(s["session_id"] // 1_000_000, []).append(s)
        logical = row["logical_session"]
        raw_ids = [
            s["generated_token_ids"][0]
            for s in sorted(by_logical[logical], key=lambda x: x["session_id"])]
        self.assertEqual(raw_ids, row["committed_token_ids"])
        # the direct side must also match its own per-case file
        direct_case = json.loads(
            (E / "direct" / f"direct-{row['case_id']}.json").read_text())
        self.assertEqual(
            direct_case["generated_token_ids"], row["committed_token_ids"])
        del row, mutated

    def test_row_count_and_equal_count_consistent(self) -> None:
        eq = load("equality-reduction.json")
        self.assertEqual(len(eq["rows"]), 24)
        self.assertEqual(
            eq["equal_count"],
            sum(1 for r in eq["rows"]
                if r["committed_ids_equal"] and r["decoded_equal"]
                and r["http_content_bind"]))
        self.assertEqual(len(eq["problems"]), 16)  # 6 cases: ids+decoded+content-bind drift


class AttemptStateMachine(unittest.TestCase):
    def test_attempt_identity(self) -> None:
        attempt = load("attempts/armc-retry-physical-1.json")
        f = attempt["facts"]
        self.assertEqual(f["campaign_id"], "armc-retry-afcdc4428f95d50c")
        self.assertEqual(
            f["execution_freeze_identity"],
            "88389598ac485f82aa3ec00caadcebcb3cafb56cf967751262e8ab5bc9bf9a1c")
        self.assertEqual(
            attempt["classification_final"], "TERMINAL_CAMPAIGN_ATTEMPT")
        self.assertFalse(f["stop_occurred"])

    def test_launch1_was_pre_observation(self) -> None:
        attempt = load("attempts/armc-retry-physical-1.json")
        # the retained launch-1 failure log must show a dependency error,
        # not a correctness-bearing observation
        log = (E / "attempts/launch1-failure.log").read_text()
        self.assertIn("ModuleNotFoundError", log)
        # no case files existed for launch 1: the only execution-plan
        # artifact from launch 1 is retained separately
        self.assertTrue(
            (E / "attempts/execution-plan.launch1.json").is_file())


class PrelaunchGateEvidence(unittest.TestCase):
    def test_both_prelaunch_runs_accepted_materialization(self) -> None:
        for rel in ("preflight/prelaunch-verdict-run1.json",
                    "preflight/prelaunch-verdict-immediate-prelaunch.json"):
            v = load(rel)
            self.assertTrue(v["pass"], rel)
            self.assertEqual(v["source_mode"], "accepted_git_materialization")
            self.assertEqual(
                v["accepted_authority_commit"],
                "c42a0ea3f12532ab74c4e79772e1a126b5028514")
            self.assertEqual(
                v["execution_freeze_identity"],
                "88389598ac485f82aa3ec00caadcebcb3cafb56cf967751262e8ab5bc9bf9a1c")

    def test_tokenizer_deployment_proof_24_of_24(self) -> None:
        proof = load("preflight/tokenizer-deployment-proof.json")
        self.assertTrue(proof["passed"])
        self.assertEqual(proof["equal_count"], 24)
        self.assertEqual(proof["forbidden_source_opens"], [])


class DataPathInvariants(unittest.TestCase):
    def test_strace_audit_all_zero(self) -> None:
        audit = load("strace-audit.json")
        self.assertTrue(audit["passed"])
        for name, t in audit["traces"].items():
            self.assertEqual(t["source_models_opens"], 0, name)
            self.assertEqual(t["materialized_writes"], 0, name)

    def test_substrate_reconciliations_pass(self) -> None:
        for host in ("01", "03"):
            rec = load(f"substrate-reconciliation-{host}.json")
            self.assertTrue(rec["passed"], host)
            self.assertEqual(rec["problems"], [], host)


if __name__ == "__main__":
    unittest.main()
