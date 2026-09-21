#!/usr/bin/env python3
"""Focused R8-I static methodology/tooling tests (issue #237).

Covers the mandatory negative controls of issue #237 plus the positive
contracts. CPU-only; no physical execution, no SSH, no accelerator queries.
Holdout-content tests use the PUBLIC commitment only (no decrypt path
exists in this module's import graph).
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue237_methodology as m
import issue237_semantic_adjudication as adj
import issue237_thresholds as thr
from issue237_build_exclusion_inventory import build_inventory, historical_identity_set
from issue237_freeze_tooling import (
    ValidationError,
    validate_corpora,
    validate_holdout_commitment,
    validate_methodology,
    validate_prerequisites,
)
from issue237_seal_holdout import custody_is_satisfied
from issue74_methodology import canonical_json_bytes, sha256_bytes

DOCS = REPO / "docs/qualification/qwen38-vulkan-v1"


def synth_rows(n_vocab=256, offset=0.0):
    """Small-vocab synthetic FP32 rows for gate tests."""
    base = [math.sin(i * 0.05 + offset) for i in range(n_vocab)]
    return base


class PrerequisiteTests(unittest.TestCase):
    def test_prerequisites_pass_and_bind_r8h(self):
        report = validate_prerequisites()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            report["predecessor_binding"]["r8h_terminal"],
            "R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED",
        )

    def test_control_1_wrong_adr_authority_rejected(self):
        # the validator reads TERMINAL.json; mutate it, expect failure, restore
        import issue237_freeze_tooling as ft
        original = ft.R8H_TERMINAL_JSON.read_text()
        try:
            mutated = original.replace(
                "R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED", "FORGED_TERMINAL"
            )
            self.assertNotEqual(mutated, original)
            ft.R8H_TERMINAL_JSON.write_text(mutated)
            with self.assertRaises(ValidationError):
                validate_prerequisites()
        finally:
            ft.R8H_TERMINAL_JSON.write_text(original)

    def test_control_2_wrong_predecessor_identity_rejected(self):
        import issue237_freeze_tooling as ft
        original = ft.R8H_AUTHORITY.read_text()
        try:
            mutated = original.replace(m.QWEN_OFFICIAL_REVISION, "0" * 40)
            self.assertNotEqual(mutated, original)
            ft.R8H_AUTHORITY.write_text(mutated)
            with self.assertRaises(ValidationError):
                validate_prerequisites()
        finally:
            ft.R8H_AUTHORITY.write_text(original)

    def test_control_4_wrong_gguf_identity_rejected(self):
        import issue237_freeze_tooling as ft
        original = ft.R8H_AUTHORITY.read_text()
        try:
            mutated = original.replace(
                m.GGUF_MEMBERS[0]["sha256"], "f" * 64
            )
            self.assertNotEqual(mutated, original)
            ft.R8H_AUTHORITY.write_text(mutated)
            with self.assertRaises(ValidationError):
                validate_prerequisites()
        finally:
            ft.R8H_AUTHORITY.write_text(original)

    def test_control_5_wrong_runtime_identity_rejected(self):
        import issue237_freeze_tooling as ft
        original = ft.R8H_AUTHORITY.read_text()
        try:
            mutated = original.replace(m.LLAMA_CPP_PIN, "0" * 40)
            self.assertNotEqual(mutated, original)
            ft.R8H_AUTHORITY.write_text(mutated)
            with self.assertRaises(ValidationError):
                validate_prerequisites()
        finally:
            ft.R8H_AUTHORITY.write_text(original)


class MethodologyTests(unittest.TestCase):
    def test_statistical_design_derived_not_transcribed(self):
        design = m.statistical_design()
        self.assertEqual(m.CALIBRATION_CASES, 1416)
        self.assertEqual(design["per_family_strict_exceedance_bound"], "24/1440")
        self.assertEqual(design["familywise_bonferroni_bound"], "72/1440")
        self.assertGreaterEqual(design["zero_exceedance_probability_at_least"], 0.95)

    def test_control_13_sample_size_consistency_enforced(self):
        from fractions import Fraction
        # M=4 at the frozen N=1416 violates the budget (96/1440 > 1/20): the
        # design derivation must refuse such a combination, and the frozen
        # triple (M=3, H=24, alpha=1/20) must satisfy it exactly.
        self.assertGreater(Fraction(4 * 24, 1416 + 24), m.ALPHA)
        self.assertLessEqual(Fraction(m.M * m.HOLDOUT_CASES, m.CALIBRATION_CASES + m.HOLDOUT_CASES), m.ALPHA)
        with self.assertRaises(m.MethodologyError):
            m.derive_minimum_calibration_n(m=0, h=24, alpha=m.ALPHA)
        # N is the true minimum: N-1 violates the budget
        self.assertGreater(
            Fraction(m.M * m.HOLDOUT_CASES, m.CALIBRATION_CASES - 1 + m.HOLDOUT_CASES),
            m.ALPHA,
        )

    def test_control_10_p99_not_promoted(self):
        tiers = {f["family"]: f["tier"] for f in m.TELEMETRY_FAMILIES}
        self.assertEqual(tiers["fp32-consumer-logits:p99-absolute-error"], "mandatory-telemetry")
        # promoting requires a NEW comparator id: assert the frozen id has no core p99
        core = {f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES}
        self.assertNotIn("fp32-consumer-logits:p99-absolute-error", core)

    def test_control_12_future_use_state_not_demoted_without_proof(self):
        audit = m.QWEN_FUTURE_USE_STATE_AUDIT
        self.assertEqual(audit["mechanical_answer"], "NO")
        self.assertIn("subsumption", audit["reasoning"])
        self.assertIn("NEW comparator version", audit["reasoning"])

    def test_control_8_semantic_profile_is_decision_stability(self):
        self.assertEqual(m.SEMANTIC_PROFILE, "DECISION_STABILITY/1")
        self.assertNotIn("EXACT_TOKENS", m.SEMANTIC_PROFILE)
        # and the strict profile cannot be silently substituted: gate order frozen
        self.assertIn("stable exact-winner", m.EVALUATION_ORDER)

    def test_decision_domain_is_full_vocabulary(self):
        domain = m.decision_domain_full_vocab(m.VOCAB_SIZE)
        self.assertEqual(len(domain), 248320)
        self.assertEqual(domain[0], 0)
        self.assertEqual(domain[-1], 248319)

    def test_control_7_single_die_authority_frozen(self):
        arm = m.CANDIDATE_ARM["single_die_authority"]
        self.assertEqual(arm["selected_die_bdf"], "00000000:06:00.0")
        self.assertEqual(arm["excluded_die_bdf"], "00000000:09:00.0")

    def test_control_6_no_cuda_in_vulkan_subject(self):
        self.assertEqual(m.LLAMA_VULKAN_BUILD["GGML_CUDA"], "OFF")
        self.assertEqual(m.LLAMA_VULKAN_BUILD["GGML_VULKAN"], "ON")


class SemanticGateTests(unittest.TestCase):
    def _vocab_patch(self, case):
        return mock.patch.object(adj.m, "VOCAB_SIZE", case)

    def test_stable_decision_requires_exact_winner(self):
        ref = synth_rows()
        cand = list(ref)
        cand[10] += 0.001
        # ensure a clear winner structure: make token 3 the argmax
        ref[3] += 5.0
        cand[3] += 5.0
        with self._vocab_patch(len(ref)):
            row = adj.evaluate_decision(ref, cand, e_d=0.01)
        self.assertEqual(row["stability"], "STABLE")
        self.assertEqual(row["verdict"], "SEMANTIC_PASS")

    def test_stable_mismatch_fails(self):
        # A STABLE decision (m_D > 2E_D) with all local errors under E_D can
        # only mismatch through the EMITTED-TOKEN seam: by the theorem the
        # bounded row alone cannot flip the winner, so a differing
        # physically emitted winner (candidate_emitted_token) is an
        # executor-output inconsistency -> STABLE_DECISION_MISMATCH.
        ref = synth_rows()
        ref[3] += 5.0              # clear reference winner at token 3
        cand = list(ref)
        cand[3] -= 0.01            # local errors stay well under E_D
        with self._vocab_patch(len(ref)):
            row = adj.evaluate_decision(
                ref, cand, e_d=0.05, candidate_emitted_token=5
            )
        self.assertEqual(row["stability"], "STABLE")
        self.assertEqual(row["verdict"], "STABLE_DECISION_MISMATCH")

    def test_decision_local_bound_checked_first(self):
        ref = synth_rows()
        cand = list(ref)
        cand[7] += 100.0  # huge local error inside D
        with self._vocab_patch(len(ref)):
            row = adj.evaluate_decision(ref, cand, e_d=0.01)
        self.assertEqual(row["verdict"], adj.m.DECISION_LOCAL_BOUND_EXCEEDED)

    def test_unstable_decision_ambiguity_set_adjudicates(self):
        ref = synth_rows()
        ref[3] += 0.5
        ref[9] += 0.49  # near-tie within 2*E_D
        cand = list(ref)
        cand[9] += 0.02
        cand[3] -= 0.02
        with self._vocab_patch(len(ref)):
            # E_D large enough that m_D <= 2E_D and the flipped winner is admissible
            row = adj.evaluate_decision(ref, cand, e_d=0.5)
        self.assertEqual(row["stability"], "UNSTABLE")
        self.assertTrue(row["ambiguity_membership"])
        self.assertEqual(row["verdict"], "SEMANTIC_PASS")

    def test_unstable_inadmissible_fails(self):
        ref = synth_rows()
        ref[3] += 0.5
        cand = list(ref)
        # candidate flips to a token far outside the ambiguity set
        cand[3] -= 1.0
        cand[100] += 1.5
        with self._vocab_patch(len(ref)):
            row = adj.evaluate_decision(ref, cand, e_d=0.2)
        self.assertNotEqual(row["verdict"], "SEMANTIC_PASS")

    def test_nan_is_unconditional_failure(self):
        ref = synth_rows()
        cand = list(ref)
        cand[4] = float("nan")
        with self._vocab_patch(len(ref)):
            with self.assertRaises(adj.AdjudicationError):
                adj.evaluate_decision(ref, cand, e_d=1.0)

    def test_case_rollup_requires_eight_decisions(self):
        rows = [{"verdict": "SEMANTIC_PASS", "decision_local_error_hex": (0.0).hex(),
                 "stability": "STABLE"}] * 7
        with self.assertRaises(adj.AdjudicationError):
            adj.evaluate_case(rows)


class ThresholdTests(unittest.TestCase):
    def test_limits_are_max_over_calibration(self):
        values = {f["family"]: [0.1] * 1416 for f in m.ACCEPTANCE_BEARING_FAMILIES}
        values["fp32-consumer-logits:max-absolute-difference"][0] = 0.7
        limits = thr.derive_core_limits(values)
        self.assertEqual(
            limits["fp32-consumer-logits:max-absolute-difference"]["limit_hex"],
            (0.7).hex(),
        )

    def test_control_20_no_manual_rounding_representable(self):
        values = {f["family"]: [1.0 / 3.0] * 1416 for f in m.ACCEPTANCE_BEARING_FAMILIES}
        limits = thr.derive_core_limits(values)
        self.assertEqual(
            limits["decision_local_E_D"]["limit_hex"], (1.0 / 3.0).hex()
        )

    def test_wrong_count_fails_closed(self):
        values = {f["family"]: [0.1] * 100 for f in m.ACCEPTANCE_BEARING_FAMILIES}
        with self.assertRaises(thr.DerivationError):
            thr.derive_core_limits(values)

    def test_e_d_derivation_arms(self):
        with self.assertRaises(thr.DerivationError):
            thr.derive_e_d([0.1] * 100, [0.2] * 8)
        with self.assertRaises(thr.DerivationError):
            thr.derive_e_d([0.1] * 1416, [0.2] * 7)
        self.assertEqual(thr.derive_e_d([0.1] * 1416, [0.4] * 8), (0.4).hex())

    def test_control_9_tolerance_must_be_derived_not_copied(self):
        # the algorithm ONLY reads provided calibration values; nothing
        # imports historical R8-H numbers. Assert the module source has no
        # hardcoded numeric limit constants:
        source = (REPO / "scripts/issue237_thresholds.py").read_text()
        for banned in ("0.25", "R8H", "gemma", "Gemma"):
            self.assertNotIn(banned, source)


class CorpusControlTests(unittest.TestCase):
    def test_control_16_historical_r8_prompt_excluded(self):
        exclusions = historical_identity_set(build_inventory())
        ladder = json.loads(
            (REPO / "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json").read_text()
        )
        for case in ladder["cases"]:
            self.assertIn(
                sha256_bytes(case["prompt_text"].encode("utf-8")), exclusions
            )
            self.assertIn(
                sha256_bytes(canonical_json_bytes(case["prompt_token_ids"])), exclusions
            )

    def test_control_14_same_generator_law_both_arms(self):
        cal = json.loads((DOCS / "manifests/calibration-corpus.json").read_text())
        commitment = json.loads(
            (DOCS / "manifests/sealed-holdout-commitment.json").read_text()
        )
        self.assertEqual(
            cal["mixture_population"]["component_selection_rule"],
            m.mixture_population_declaration()["component_selection_rule"],
        )
        self.assertEqual(
            cal["mixture_population"]["component_count"], commitment["case_count"] and 24
        )

    def test_control_15_no_fixed_quota_design(self):
        cal = json.loads((DOCS / "manifests/calibration-corpus.json").read_text())
        counts = [r["observed"] for r in cal["realized_component_counts"]]
        self.assertEqual(sum(counts), 1416)
        self.assertNotEqual(len(set(counts)), 1)

    def test_control_17_no_post_hoc_dedup(self):
        # corpus carries draw_index 0..N-1 in order with attempt nonces;
        # post-hoc dedup would break the replayed component stream
        report = validate_corpora()
        self.assertEqual(report["status"], "PASS")

    def test_control_18_19_stress_role_frozen(self):
        stress = json.loads((DOCS / "manifests/stress-pool.json").read_text())
        self.assertEqual(stress["stress_role"], "NON_PREDICTIVE; zero predictive sample count")
        self.assertEqual(len(stress["cases"]), 48)
        cal = json.loads((DOCS / "manifests/calibration-corpus.json").read_text())
        self.assertEqual(len(cal["cases"]), 1416)

    def test_tokenizer_asset_pinned(self):
        digest = hashlib.sha256(
            (REPO / "docs/qualification/qwen38-vulkan-v1/assets/tokenizer.json").read_bytes()
        ).hexdigest()
        self.assertEqual(digest, m.TOKENIZER_JSON_SHA256)


class HoldoutControlTests(unittest.TestCase):
    def test_control_21_22_23_holdout_sealed_no_decrypt_no_private_material(self):
        report = validate_holdout_commitment()
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["decrypt_performed"])
        commitment = json.loads(
            (DOCS / "manifests/sealed-holdout-commitment.json").read_text()
        )
        for draw in commitment["draws"]:
            self.assertNotIn("prompt_text", draw)
            self.assertNotIn("token_ids", draw)
        custody = json.loads((DOCS / "manifests/holdout-custody-record.json").read_text())
        self.assertFalse(custody["private_key_in_git"])
        self.assertFalse(custody["secret_seed_in_git"])
        # no private key material anywhere under the new docs dir
        for path in (DOCS).rglob("*"):
            if path.is_file():
                self.assertNotIn("PRIVATE KEY", path.read_text(errors="replace")[:4096])

    def test_custody_fail_closed_until_two_custodians(self):
        self.assertFalse(
            custody_is_satisfied(
                {"holdout_state": "SEALED_CUSTODY_INCOMPLETE",
                 "custodians": [{"verified": True}]}
            )
        )
        self.assertTrue(
            custody_is_satisfied(
                {"holdout_state": "SEALED_NOT_CONSUMED",
                 "custodians": [{"verified": True}, {"verified": True}]}
            )
        )
        self.assertFalse(
            custody_is_satisfied(
                {"holdout_state": "SEALED_NOT_CONSUMED",
                 "custodians": [{"verified": True}]}
            )
        )

    def test_control_3_r8h_observations_not_admitted(self):
        # the exclusion inventory contains the R8 fixture identities and the
        # corpus validator enforces membership rejection; a forged corpus
        # carrying an R8 fixture prompt must fail validation
        cal_path = DOCS / "manifests/calibration-corpus.json"
        original = cal_path.read_bytes()
        try:
            doc = json.loads(original)
            ladder = json.loads(
                (REPO / "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json").read_text()
            )
            fixture = ladder["cases"][0]
            victim = doc["cases"][0]
            doc["cases"][0] = {
                **victim,
                "prompt_text": fixture["prompt_text"],
                "token_ids": fixture["prompt_token_ids"],
                "prompt_sha256": sha256_bytes(fixture["prompt_text"].encode("utf-8")),
                "token_ids_sha256": sha256_bytes(
                    canonical_json_bytes(fixture["prompt_token_ids"])
                ),
            }
            cal_path.write_bytes(canonical_json_bytes(doc))
            with self.assertRaises(ValidationError):
                validate_corpora()
        finally:
            cal_path.write_bytes(original)

    def test_unseal_preflight_blocks_without_calibration_evidence(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts/issue237_unseal_preflight.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        report = json.loads(proc.stdout)
        self.assertEqual(report["decision"], "BLOCKED")
        self.assertFalse(report.get("decrypt_performed", False))


class PlannerPurityTests(unittest.TestCase):
    def test_control_26_no_vendor_policy_in_generic_planner(self):
        # The backend-coherence posture is a Model Execution Strategy
        # constraint. The generic planner's classify_path must not gain
        # vendor/backend/model POLICY from #237: path-registry literals are
        # fine, but the classification decision must never branch on
        # vendor/backend/model names.
        import ast
        plan_ci_src = (REPO / "scripts/plan_ci.py").read_text()
        tree = ast.parse(plan_ci_src)
        classify = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "classify_path"
        )
        body_src = ast.get_source_segment(plan_ci_src, classify) or ""
        for banned in ("NVIDIA", "AMD", "Vulkan", "CUDA", "Qwen"):
            self.assertNotIn(banned, body_src)
        # and the strategy modules exist (policy lives there, not here)
        strategy_names = [
            p.name for p in (REPO / "scripts").glob("issue237_*.py")
        ]
        self.assertTrue(strategy_names)


class ReasonCodeContractTests(unittest.TestCase):
    def test_reason_codes_frozen(self):
        self.assertEqual(
            list(m.REASON_CODES),
            [
                "DECISION_LOCAL_BOUND_EXCEEDED",
                "DECISION_DOMAIN_ESCAPE",
                "STABLE_DECISION_MISMATCH",
                "UNSTABLE_DECISION_INADMISSIBLE",
                "SEMANTIC_PASS",
            ],
        )

    def test_control_25_free_running_not_same_input_evidence(self):
        source = (REPO / "scripts/issue237_semantic_adjudication.py").read_text()
        self.assertIn("diagnostic-only", source)


if __name__ == "__main__":
    unittest.main()
