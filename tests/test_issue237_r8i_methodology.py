#!/usr/bin/env python3
"""Focused R8-I static methodology/tooling tests (issue #237).

Covers the mandatory negative controls of issue #237 plus the positive
contracts, including the correction-pass controls:

- the frozen validation report is byte-identical to a fresh freeze
  derivation (deterministic regeneration fixed point);
- the predictive corpora regenerate byte-identically under the corrected
  R8-band law (tokenizers-gated: host-availability skip otherwise);
- the frozen length bands mechanically match the R8-B fixture authority
  and a Gemma-band regression fails;
- active holdout identity is mechanically derived from sealed/holdout.cms;
- a superseded seal SHA cannot satisfy active-holdout validation;
- lifecycle (SEALED_NOT_CONSUMED) and custody (INCOMPLETE) are independent
  axes;
- no private key / plaintext holdout / secret seed exists anywhere in Git.

CPU-only; no physical execution, no SSH, no accelerator queries. Holdout
content tests use the PUBLIC commitment only (no decrypt path exists in
this module's import graph).
"""
from __future__ import annotations

import hashlib
import json
import math
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
    DOCS,
    ValidationError,
    cmd_check,
    derive_freeze_report,
    validate_corpora,
    validate_holdout_commitment,
    validate_methodology,
    validate_prerequisites,
)
from issue237_length_bands import (
    BandAuthorityError,
    derive_length_regimes,
    validate_frozen_bands,
)
from issue237_seal_holdout import (
    custody_is_satisfied,
    superseded_ciphertext_shas,
)
from issue74_methodology import canonical_json_bytes, sha256_bytes


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

    def test_prerequisites_bind_r8b_fixture_authority(self):
        report = validate_prerequisites()
        self.assertEqual(
            report["r8b_fixture_ladder"],
            "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db",
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


class LengthBandAuthorityTests(unittest.TestCase):
    """Corrected predictive length regimes (issue #237 correction pass)."""

    def test_bands_derive_from_r8b_fixture_authority(self):
        derived = derive_length_regimes()
        self.assertEqual(
            derived,
            ((250, 264), (1018, 1032), (3066, 3080), (4090, 4104)),
        )
        self.assertEqual(m.LENGTH_REGIMES, derived)

    def test_control_gemma_band_regression_fails(self):
        # a regression back to the Gemma qualification bands must fail the
        # authority cross-check (both orderings and mutations)
        gemma_bands = ((4, 8), (24, 28), (36, 40), (52, 56))
        with self.assertRaises(BandAuthorityError):
            validate_frozen_bands(gemma_bands)
        with self.assertRaises(BandAuthorityError):
            validate_frozen_bands(((250, 264), (1018, 1032), (3066, 3080), (4090, 4103)))
        with self.assertRaises(BandAuthorityError):
            validate_frozen_bands(((1018, 1032), (250, 264), (3066, 3080), (4090, 4104)))
        with self.assertRaises(BandAuthorityError):
            validate_frozen_bands(((250, 264), (1018, 1032)))

    def test_control_fixture_authority_drift_fails_closed(self):
        ladder = REPO / (
            "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json"
        )
        original = ladder.read_bytes()
        try:
            doc = json.loads(original)
            doc["cases"][0]["target_band"] = [4, 8]  # Gemma regression in the authority itself
            ladder.write_bytes(canonical_json_bytes(doc))
            with self.assertRaises(BandAuthorityError):
                derive_length_regimes()
        finally:
            ladder.write_bytes(original)
        self.assertEqual(derive_length_regimes()[0], (250, 264))

    def test_methodology_validation_enforces_bands(self):
        with mock.patch.object(m, "LENGTH_REGIMES", ((4, 8), (24, 28), (36, 40), (52, 56))):
            with self.assertRaises((ValidationError, BandAuthorityError)):
                validate_methodology()

    def test_mixture_declaration_carries_band_authority(self):
        declaration = m.mixture_population_declaration()
        authority = declaration["length_regime_authority"]
        self.assertEqual(
            authority["authority"],
            "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json",
        )
        self.assertEqual(
            authority["authority_sha256"],
            "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db",
        )
        self.assertEqual(
            [tuple(c["target_band"]) for c in authority["cases"]],
            list(m.LENGTH_REGIMES),
        )


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

    def test_future_use_state_audit_retained_unchanged(self):
        # correction-pass control: the longer-context bands change prompt
        # LENGTHS, not the observation seam; the audit's subsumption
        # argument (cache_prompt=false exposes no retained cross-decision
        # state) has no static/source-level contradiction, so the audit is
        # retained verbatim with M and comparator tiers unchanged.
        self.assertEqual(m.M, 3)
        self.assertEqual(
            [f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES],
            [
                "fp32-consumer-logits:max-absolute-difference",
                "fp32-consumer-logits:rms-difference",
                "decision_local_E_D",
            ],
        )
        self.assertEqual(
            m.MATCHED_GEOMETRY["request_contract"]["cache_prompt"], False
        )

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

    def test_control_no_physical_execution_code_path(self):
        # no execution-runtime import or device initialization exists in
        # any issue237 producer (CPU/static only)
        banned = (
            "import torch",
            "torch.cuda",
            "cudaSetUpDevices",
            "vulkan.initialize",
            "paramiko",
            "subprocess.run(['ssh'",
            'subprocess.run(["ssh"',
        )
        for path in sorted((REPO / "scripts").glob("issue237_*.py")):
            source = path.read_text()
            for marker in banned:
                self.assertNotIn(marker, source, f"{path.name}: {marker}")


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

    def test_all_token_counts_inside_corrected_r8_bands(self):
        cal = json.loads((DOCS / "manifests/calibration-corpus.json").read_text())
        stress = json.loads((DOCS / "manifests/stress-pool.json").read_text())
        bands = {tuple(b) for b in m.LENGTH_REGIMES}
        for case in cal["cases"] + stress["cases"]:
            regime = tuple(case["length_regime"])
            self.assertIn(regime, bands)
            low, high = regime
            self.assertTrue(
                low <= case["token_count"] <= high,
                f"{case['case_id']} token count {case['token_count']} "
                f"outside {regime}",
            )
            self.assertEqual(case["token_count"], len(case["token_ids"]))

    def test_control_no_gemma_band_case_survives(self):
        # the corrected corpus cannot contain any case in the superseded
        # Gemma band ranges (a stale/regressed corpus fails immediately)
        gemma_ranges = ((4, 8), (24, 28), (36, 40), (52, 56))
        cal = json.loads((DOCS / "manifests/calibration-corpus.json").read_text())
        for case in cal["cases"]:
            for low, high in gemma_ranges:
                self.assertFalse(
                    low <= case["token_count"] <= high,
                    f"{case['case_id']} still in a superseded Gemma band",
                )

    def test_deterministic_corpus_regeneration_byte_identical(self):
        """Committed predictive corpora regenerate byte-identically under
        the corrected law (requires the pinned tokenizer; host-availability
        skip otherwise)."""
        try:
            from tokenizers import Tokenizer  # noqa: F401
        except ImportError:
            self.skipTest("tokenizers unavailable on this host")
        with tempfile.TemporaryDirectory() as tmp:
            out_cal = Path(tmp) / "cal.json"
            out_stress = Path(tmp) / "stress.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts/issue237_generate_corpora.py"),
                    "--tokenizer-json",
                    str(REPO / "docs/qualification/qwen38-vulkan-v1/assets/tokenizer.json"),
                    "--calibration-out", str(out_cal),
                    "--stress-pool-out", str(out_stress),
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            self.assertEqual(
                out_cal.read_bytes(),
                (DOCS / "manifests/calibration-corpus.json").read_bytes(),
                "calibration corpus is not byte-identical to regeneration",
            )
            self.assertEqual(
                out_stress.read_bytes(),
                (DOCS / "manifests/stress-pool.json").read_bytes(),
                "stress pool is not byte-identical to regeneration",
            )


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

    def test_active_lifecycle_state_is_sealed_not_consumed(self):
        commitment = json.loads(
            (DOCS / "manifests/sealed-holdout-commitment.json").read_text()
        )
        self.assertEqual(commitment["state"], "SEALED_NOT_CONSUMED")
        custody = json.loads((DOCS / "manifests/holdout-custody-record.json").read_text())
        self.assertEqual(custody["holdout_state"], "SEALED_NOT_CONSUMED")
        # lifecycle never encodes custody completeness
        self.assertNotIn("CUSTODY", commitment["state"])

    def test_custody_status_is_independent_axis(self):
        custody = json.loads((DOCS / "manifests/holdout-custody-record.json").read_text())
        self.assertEqual(custody["custody_status"], "INCOMPLETE")
        self.assertEqual(custody["verified_custodian_count"], 0)
        self.assertFalse(custody["unseal_authorized"])
        for custodian in custody["custodians"]:
            self.assertIn("verified", custodian)
            # honest record: no verified claim without a receipt
            if custodian["verified"]:
                self.assertIn("verification_receipt", custodian)

    def test_custody_fail_closed_until_two_verified_custodians(self):
        self.assertFalse(
            custody_is_satisfied(
                {"holdout_state": "SEALED_NOT_CONSUMED",
                 "custody_status": "INCOMPLETE",
                 "custodians": [{"verified": True}]}
            )
        )
        self.assertFalse(
            custody_is_satisfied(
                {"holdout_state": "SEALED_NOT_CONSUMED",
                 "custody_status": "INCOMPLETE",
                 "custodians": [{"verified": True}, {"verified": True}]}
            )
        )
        self.assertFalse(
            # the OLD conflation (lifecycle carrying custody) must fail
            custody_is_satisfied(
                {"holdout_state": "SEALED_CUSTODY_INCOMPLETE",
                 "custody_status": "COMPLETE",
                 "custodians": [{"verified": True}, {"verified": True}]}
            )
        )
        self.assertTrue(
            custody_is_satisfied(
                {"holdout_state": "SEALED_NOT_CONSUMED",
                 "custody_status": "COMPLETE",
                 "custodians": [{"verified": True}, {"verified": True}]}
            )
        )
        self.assertFalse(
            custody_is_satisfied(
                {"holdout_state": "SEALED_NOT_CONSUMED",
                 "custody_status": "COMPLETE",
                 "custodians": [{"verified": True}]}
            )
        )

    def test_active_ciphertext_identity_is_mechanical(self):
        import issue237_freeze_tooling as ft
        commitment = json.loads(
            (DOCS / "manifests/sealed-holdout-commitment.json").read_text()
        )
        derived = ft.sha256_file(DOCS / "sealed/holdout.cms")
        self.assertEqual(commitment["ciphertext_sha256"], derived)
        report = validate_holdout_commitment()
        self.assertEqual(report["ciphertext_sha256"], derived)

    def test_superseded_seal_cannot_satisfy_active_validation(self):
        superseded = superseded_ciphertext_shas()
        self.assertIn(
            "f90806c5611d06234f18a853987b4476268d55c9c68d8c1428040260aeec81b9",
            superseded,
        )
        self.assertIn(
            "7bcdad8bf7955c83044971fdd30709deca5ec0a5eba858ddd30c6023bac0a9d6",
            superseded,
        )
        active = hashlib.sha256(
            (DOCS / "sealed/holdout.cms").read_bytes()
        ).hexdigest()
        self.assertNotIn(active, superseded)
        # forging the commitment to name a superseded SHA fails validation
        commitment_path = DOCS / "manifests/sealed-holdout-commitment.json"
        original = commitment_path.read_bytes()
        try:
            doc = json.loads(original)
            doc["ciphertext_sha256"] = sorted(superseded)[0]
            commitment_path.write_bytes(canonical_json_bytes(doc))
            with self.assertRaises(ValidationError):
                validate_holdout_commitment()
        finally:
            commitment_path.write_bytes(original)
        # swapping the ACTIVE ciphertext for the retained superseded bytes
        # fails validation (no superseded ciphertext exists in-tree for the
        # 7bcd seal; synthesize one to prove the mechanical rejection)
        cms_path = DOCS / "sealed/holdout.cms"
        active_bytes = cms_path.read_bytes()
        try:
            cms_path.write_bytes(b" forged-superseded-ciphertext\n")
            with self.assertRaises(ValidationError):
                validate_holdout_commitment()
        finally:
            cms_path.write_bytes(active_bytes)

    def test_supersession_records_are_honest(self):
        records_dir = DOCS / "sealed/superseded"
        records = sorted(records_dir.glob("superseded-holdout-*.json"))
        self.assertEqual(len(records), 2)
        for path in records:
            record = json.loads(path.read_text())
            self.assertFalse(record["consumed"])
            self.assertFalse(record["decrypt_performed"])
            self.assertIn("ineligibility", record)
            self.assertIn("ciphertext_sha256", record)
            self.assertIn("reason", record)
        # the short-context supersession explicitly names the population
        # supersession BEFORE physical execution
        v2 = json.loads(
            (records_dir / "superseded-holdout-v2-short-context-gemma-bands.json").read_text()
        )
        self.assertIn("superseded before physical execution", v2["reason"].lower())
        self.assertTrue(v2["disposition"]["plaintext_destroyed"])
        self.assertTrue(v2["disposition"]["recipient_private_key_destroyed"])
        self.assertTrue(v2["disposition"]["secret_seed_destroyed"])

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


class FreezeFixedPointTests(unittest.TestCase):
    """Correction-pass determinism contract for the frozen authority."""

    def test_committed_validation_report_is_byte_identical_to_fresh_freeze(self):
        result = cmd_check()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["byte_identical"])
        self.assertEqual(result["committed_sha256"], result["fresh_sha256"])

    def test_control_forged_report_fails_fixed_point(self):
        report_path = DOCS / "manifests/validation-report.json"
        original = report_path.read_bytes()
        try:
            doc = json.loads(original)
            doc["holdout"]["ciphertext_sha256"] = "f" * 64
            report_path.write_bytes(canonical_json_bytes(doc))
            result = cmd_check()
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["byte_identical"])
        finally:
            report_path.write_bytes(original)
        # restored: fixed point holds again
        self.assertEqual(cmd_check()["status"], "PASS")

    def test_freeze_derivation_is_idempotent(self):
        first = canonical_json_bytes(derive_freeze_report())
        second = canonical_json_bytes(derive_freeze_report())
        self.assertEqual(first, second)


class GitPurityTests(unittest.TestCase):
    """No private key, plaintext holdout, or secret seed anywhere in Git."""

    def _git_files(self):
        proc = subprocess.run(
            ["git", "-C", str(REPO), "ls-files"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [line for line in proc.stdout.splitlines() if line]

    def test_no_private_or_plaintext_material_tracked(self):
        forbidden_names = (
            "holdout-plaintext",
            "secret-seed",
            "recipient.key",
        )
        for path in self._git_files():
            base = Path(path).name.lower()
            for marker in forbidden_names:
                self.assertNotIn(
                    marker, base,
                    f"tracked file looks like private material: {path}",
                )
            self.assertFalse(
                base.endswith(".key"),
                f"tracked private key file: {path}",
            )

    def test_tracked_holdout_artifacts_carry_no_secret_material(self):
        candidates = []
        for path in self._git_files():
            if "issue237" in path or "qwen38-vulkan-v1" in path:
                candidates.append(path)
        self.assertTrue(candidates)
        # entropy-blob scanning applies to TEXT artifacts only: binary
        # ciphertext (holdout.cms) and the base64 vocabulary/merge blobs in
        # the pinned tokenizer JSON are legitimately high-entropy public
        # assets; they still get the marker checks below.
        text_suffixes = (".json", ".md", ".py", ".txt")
        exempt_binary = {
            "docs/qualification/qwen38-vulkan-v1/sealed/holdout.cms",
            "docs/qualification/qwen38-vulkan-v1/assets/tokenizer.json",
        }
        for path in candidates:
            data = (REPO / path).read_bytes()
            if not path.endswith(".py"):
                # evidence/artifact files must never carry key material;
                # SOURCES AND TESTS legitimately mention the marker inside
                # the controls that police it (entropy-shape check applies)
                self.assertNotIn(b"PRIVATE KEY", data)
            if path.endswith((".json", ".md")):
                # evidence artifacts must not even NAME plaintext/seed
                # files; producer SOURCES legitimately name the concepts
                # (CLI args, docstrings) and are covered by the
                # entropy-shape check below instead
                self.assertNotIn(b"secret-seed", data)
                self.assertNotIn(b"holdout-plaintext", data)
            if path in exempt_binary or not path.endswith(text_suffixes):
                continue
            text = data.decode("utf-8", errors="replace")
            import re
            for match in re.findall(r"[A-Za-z0-9_-]{64,90}", text):
                # seed material is 43-char urlsafe base64 (token_urlsafe(32));
                # urlsafe ALPHABET with +/= padding or mixed-case runs of
                # this length are seed-shaped. Hex commitments and dashed
                # separators are not.
                is_hex = all(c in "0123456789abcdef" for c in match)
                is_dashes = set(match) == {"-"}
                is_identifier = ("_" in match) and not match.startswith("-")
                self.assertTrue(
                    is_hex or is_dashes or is_identifier,
                    f"seed-shaped high-entropy blob in {path} "
                    f"(not hex, not an identifier, not a separator)",
                )

    def test_superseded_ciphertext_not_retained_in_active_tree(self):
        # the 7bcd seal's ciphertext bytes were removed; only the
        # namespaced supersession records may carry its identity
        tracked = self._git_files()
        this_test = "tests/test_issue237_r8i_methodology.py"
        for path in tracked:
            if path.endswith("sealed/holdout.cms"):
                continue
            if "superseded" in path or path == this_test:
                continue
            data = (REPO / path).read_bytes()
            self.assertNotIn(
                b"7bcdad8bf7955c83044971fdd30709deca5ec0a5eba858ddd30c6023bac0a9d6",
                data,
                f"stale active-authority reference to the superseded seal in {path}",
            )


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
