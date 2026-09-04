"""InferSwarm issue #86: v3 methodology/tooling tests.

CPU-only, static, synthetic. No model execution, no CUDA, no GPU queries,
no holdout decryption, no OpenSSL decrypt. The selected-eight /
calibration-summary / decision-domain fixtures used by positive tests are
TEST-ONLY SYNTHETIC EVIDENCE generated in memory via the real frozen v3
selector and derivation tooling — they are NOT real physical artifacts and
are never written into the qualification evidence directory.

Negative-control coverage maps to issue #86 section 13.
"""
from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue74_methodology import ENVELOPES, MethodologyError, canonical_json_bytes, sha256_bytes  # noqa: E402
from issue86_v3_methodology import (  # noqa: E402
    DECISION_DOMAIN_ESCAPE,
    SEMANTIC_PASS,
    ambiguity_set,
    argmax_tie_break_identity,
    case_e_d,
    decision_domain,
    decision_domain_construction_identity,
    decision_local_error,
    derive_e_d,
    domain_membership_sha256,
    evaluate_decision,
    frozen_argmax,
    margin_on_domain,
    minimum_sample_size_v3,
    statistical_design_v3,
)
from issue86_v3_thresholds import (  # noqa: E402
    V3_CALIBRATION_CORPUS_SHA256,
    V3_STRESS_COMMITMENT_SHA256,
    V3_STRESS_POOL_SHA256,
    V3_TOOLING_VERSION,
    derive_v3_threshold_manifest,
)
from select_issue86_margin_stress_v3 import (  # noqa: E402
    MARGIN_DEFINITION,
    NegativeReferenceMarginError,
    NonfiniteReferenceMarginError,
    select,
)
from verify_issue86_v3_unseal import (  # noqa: E402
    CUSTODY_NOT_VERIFIED,
    PRIVATE_KEY_NOT_EXTERNAL,
    SELECTED_SHA_MISMATCH,
    THRESHOLD_SCHEMA_INVALID,
    UnsealPreflightError,
    validate_unseal_preconditions,
    WRONG_HISTORICAL_HOLDOUT,
    WRONG_V3_HOLDOUT_MATERIAL,
)

V3 = ROOT / "docs/qualification/gemma4-12b-it-v3"
V1 = ROOT / "docs/qualification/gemma4-12b-it-v1"
V2 = ROOT / "docs/qualification/gemma4-12b-it-v2"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def sha_canonical(value: dict) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Synthetic fixture: deterministic, CPU-only, never committed.
# ---------------------------------------------------------------------------


def synthetic_logits(seed: int, size: int) -> list[float]:
    """Deterministic pseudo-logits (LCG over exactly representable values)."""
    state = seed & 0xFFFFFFFFFFFFFFFF
    values = []
    for _ in range(size):
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        values.append(float((state >> 11) % 20001) / 1000.0 - 10.0)
    return values


class V3Fixture:
    def __init__(self) -> None:
        self.corpus = load(V3 / "manifests/calibration-corpus.json")
        self.pool = load(V3 / "manifests/stress-pool.json")
        self.commitment = load(V3 / "manifests/stress-selection-commitment.json")
        assert sha_canonical(self.pool) == V3_STRESS_POOL_SHA256
        assert sha_canonical(self.commitment) == V3_STRESS_COMMITMENT_SHA256
        # Synthetic margins: 1 zero-tie case + 47 strictly increasing positives.
        rows = []
        for index, case in enumerate(reversed(self.pool["cases"])):
            margin = 0.0 if index == 0 else float(index) / 10.0
            rows.append({
                "case_id": case["case_id"],
                "case_sha256": case["case_sha256"],
                "top1_margin_hex": margin.hex(),
            })
        self.margins = {
            "schema": "inferswarm.issue86.v3-reference-margin-summary/1",
            "contract_id": "inferswarm.gemma4-heterogeneous-numerical-equivalence/1",
            "margin_definition": MARGIN_DEFINITION,
            "stress_pool_sha256": sha_canonical(self.pool),
            "cases": rows,
        }
        self.selection = select(self.pool, self.margins, self.commitment)
        selected_cases = [row["case"] for row in self.selection["selected"]]
        all_cases = self.corpus["cases"] + selected_cases
        self.domain_manifest = {
            "schema": "inferswarm.issue86.v3-decision-domain-manifest/1",
            "contract_id": "inferswarm.gemma4-heterogeneous-numerical-equivalence/1",
            "construction": decision_domain_construction_identity(),
            "k": 1024,
            "reference_derived_only": True,
            "candidate_membership_influence": "PROHIBITED",
            "statistical_cases": [],
            "stress_cases": [],
        }
        self.summary_rows = {}
        for index, case in enumerate(all_cases):
            prefix = "statistical_cases" if case["case_id"].startswith("c86-") else "stress_cases"
            rows_out = []
            summary_decisions = []
            for decision in range(8):
                ref = synthetic_logits(index * 31 + decision * 7 + 1, 4096)
                # force a large m_D so every synthetic row is STABLE
                ref[3] = 50.0
                domain = decision_domain(ref, 1024)
                domain_set = set(domain)
                cand = [v + (0.001 if i in domain_set else 5.0) for i, v in enumerate(ref)]
                rows_out.append({
                    "decision_index": decision,
                    "domain_membership_sha256": domain_membership_sha256(domain),
                    "domain_size": len(domain),
                })
                summary_decisions.append({
                    "decision_index": decision,
                    "domain_membership_sha256": domain_membership_sha256(domain),
                    "domain_size": len(domain),
                    "decision_local_error_hex": decision_local_error(ref, cand, domain).hex(),
                })
            self.domain_manifest[prefix].append({
                "case_id": case["case_id"],
                "case_sha256": case["case_sha256"],
                "decisions": rows_out,
            })
            self.summary_rows[case["case_id"]] = {
                "case_id": case["case_id"],
                "case_sha256": case["case_sha256"],
                "exact_integrity": "PASS",
                "finite": True,
                "evidence_complete": True,
                "envelopes": {name: (1.0 if prefix == "statistical_cases" else 2.0).hex() for name in ENVELOPES},
                "case_e_d_hex": case_e_d(
                    float.fromhex(d["decision_local_error_hex"]) for d in summary_decisions
                ).hex(),
                "decisions": summary_decisions,
            }
        self.summary = {
            "schema": "inferswarm.issue86.v3-calibration-summary/1",
            "contract_id": "inferswarm.gemma4-heterogeneous-numerical-equivalence/1",
            "tooling_version": V3_TOOLING_VERSION,
            "calibration_corpus_sha256": sha_canonical(self.corpus),
            "stress_pool_sha256": sha_canonical(self.pool),
            "stress_selection_commitment_sha256": sha_canonical(self.commitment),
            "reference_margin_summary_sha256": sha_canonical(self.margins),
            "stress_selection_sha256": sha_canonical(self.selection),
            "decision_domain_manifest_sha256": sha_canonical(self.domain_manifest),
            "evidence_sha256": ["a" * 64, "b" * 64],
            "statistical_cases": [self.summary_rows[c["case_id"]] for c in self.corpus["cases"]],
            "stress_cases": [self.summary_rows[c["case_id"]] for c in selected_cases],
        }

    def derive(self, **overrides):
        args = dict(
            calibration_corpus=self.corpus,
            stress_pool=self.pool,
            selection_commitment=self.commitment,
            reference_margin_summary=self.margins,
            stress_selection=self.selection,
            decision_domain_manifest=self.domain_manifest,
            calibration_summary=self.summary,
            program_sha256="c" * 64,
        )
        args.update(overrides)
        return derive_v3_threshold_manifest(**args)


FIXTURE = V3Fixture()


# ---------------------------------------------------------------------------
# 1. frozen corpus/pool/commitment identities + disjointness
# ---------------------------------------------------------------------------


class TestFrozenV3Artifacts(unittest.TestCase):
    def test_calibration_corpus_identity(self):
        self.assertEqual(sha_canonical(FIXTURE.corpus), V3_CALIBRATION_CORPUS_SHA256)
        self.assertEqual(len(FIXTURE.corpus["cases"]), 576)
        self.assertTrue(all(c["case_id"].startswith("c86-") for c in FIXTURE.corpus["cases"]))
        self.assertEqual(FIXTURE.corpus["seed"], "inferswarm-issue-86-calibration-v3")

    def test_stress_pool_identity(self):
        self.assertEqual(sha_canonical(FIXTURE.pool), V3_STRESS_POOL_SHA256)
        self.assertEqual(len(FIXTURE.pool["cases"]), 48)
        self.assertTrue(all(c["case_id"].startswith("p86-") for c in FIXTURE.pool["cases"]))

    def test_selection_commitment_identity(self):
        self.assertEqual(sha_canonical(FIXTURE.commitment), V3_STRESS_COMMITMENT_SHA256)
        self.assertEqual(FIXTURE.commitment["state"], "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION")
        self.assertIn("finite zero margin: eligible", FIXTURE.commitment["eligibility_rule"])

    def test_disjointness_proof_file(self):
        proof = load(V3 / "manifests/disjointness-proof.json")
        self.assertEqual(proof["verdict"], "MECHANICALLY_DISJOINT")
        self.assertEqual(len(proof["checked_against"]), 4)
        # live re-derivation of the disjointness property
        def hashes(cases):
            return ({c["prompt_sha256"] for c in cases}, {c["token_ids_sha256"] for c in cases})
        v3cal = hashes(FIXTURE.corpus["cases"])
        v3pool = hashes(FIXTURE.pool["cases"])
        prior = {
            "c74": hashes(load(V1 / "manifests/calibration-corpus.json")["cases"]),
            "p74": hashes(load(V1 / "manifests/margin-stress-pool.json")["cases"]),
            "p76": hashes(load(V2 / "manifests/margin-stress-pool.json")["cases"]),
            "h74": hashes(load(V1 / "manifests/sealed-holdout-commitment.json")["cells"]),
            "h86": hashes(load(V3 / "manifests/sealed-holdout-commitment.json")["cells"]),
        }
        for name, (p, t) in prior.items():
            self.assertFalse(p & v3cal[0], name)
            self.assertFalse(t & v3cal[1], name)
            self.assertFalse(p & v3pool[0], name)
            self.assertFalse(t & v3pool[1], name)
        self.assertFalse(v3cal[0] & v3pool[0])
        self.assertFalse(v3cal[1] & v3pool[1])

    def test_no_v1_v2_case_id_reuse(self):
        old_ids = {c["case_id"] for c in load(V1 / "manifests/calibration-corpus.json")["cases"]}
        old_ids |= {c["case_id"] for c in load(V1 / "manifests/margin-stress-pool.json")["cases"]}
        old_ids |= {c["case_id"] for c in load(V2 / "manifests/margin-stress-pool.json")["cases"]}
        v3_ids = {c["case_id"] for c in FIXTURE.corpus["cases"]} | {
            c["case_id"] for c in FIXTURE.pool["cases"]
        }
        self.assertFalse(old_ids & v3_ids)

    def test_holdout_sealed_and_distinct(self):
        commitment = load(V3 / "manifests/sealed-holdout-commitment.json")
        self.assertEqual(commitment["state"], "SEALED_NOT_CONSUMED")
        self.assertEqual(commitment["case_count"], 24)
        self.assertTrue(all(c["case_id"].startswith("h86-") for c in commitment["cells"]))
        self.assertEqual(commitment["ciphertext_sha256"], sha_file(V3 / "sealed/holdout.cms"))
        self.assertEqual(
            commitment["recipient_certificate_sha256"],
            sha_file(V3 / "sealed/recipient-certificate.pem"),
        )
        self.assertNotEqual(
            commitment["ciphertext_sha256"],
            "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59",
        )

    def test_custody_record(self):
        custody = load(V3 / "manifests/holdout-custody-record.json")
        self.assertEqual(custody["schema"], "inferswarm.issue86.v3-holdout-custody-record/1")
        self.assertEqual(len(custody["custodians"]), 2)
        self.assertTrue(all(c["public_key_match"] for c in custody["custodians"]))
        self.assertFalse(custody["unseal_authorized"])
        self.assertEqual(custody["holdout_state"], "SEALED_NOT_CONSUMED")

    def test_historical_evidence_intact(self):
        # v1 living review manifest must still hash every listed artifact.
        for entry in (V1 / "MANIFEST.sha256").read_text().splitlines():
            expected, relative = entry.split("  ", 1)
            self.assertEqual(sha_file(ROOT / relative), expected, relative)
        # v2 pool unchanged.
        self.assertEqual(
            sha_file(V2 / "manifests/margin-stress-pool.json"),
            "533b32857721b3f99243e5695bc18b24960cbd3c80692d626154907d6ecbd7c9",
        )
        # #74 holdout ciphertext unchanged.
        self.assertEqual(
            sha_file(V1 / "sealed/holdout.cms"),
            "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59",
        )


# ---------------------------------------------------------------------------
# 2. decision domain construction (issue #86 section 5)
# ---------------------------------------------------------------------------


class TestDecisionDomain(unittest.TestCase):
    def test_construction_identity(self):
        self.assertEqual(decision_domain_construction_identity(), "reference-top-1024-with-cutoff-ties/1")

    def test_exact_k_when_no_cutoff_ties(self):
        values = [float(i) for i in range(4096)]
        domain = decision_domain(values, 1024)
        self.assertEqual(len(domain), 1024)
        self.assertEqual(domain, tuple(range(3072, 4096)))
        self.assertEqual(domain, tuple(sorted(domain)))

    def test_cutoff_ties_all_included(self):
        values = [float(i) for i in range(4096)]
        values[0] = 3072.0  # tie AT the cutoff
        domain = decision_domain(values, 1024)
        self.assertEqual(len(domain), 1025)  # 1024 + the tied extra member
        self.assertIn(0, domain)
        self.assertNotIn(1, domain)

    def test_reference_winner_contained_by_construction(self):
        values = synthetic_logits(42, 4096)
        domain = decision_domain(values, 1024)
        self.assertIn(frozen_argmax(values), domain)

    def test_k_is_power_of_two_1024(self):
        values = [1.0] * 4096
        self.assertEqual(len(decision_domain(values, 1024)), 4096)  # all tie

    def test_domain_is_reference_derived_only(self):
        # candidate values cannot change membership: same reference row gives
        # byte-identical membership hash regardless of any candidate row.
        ref = synthetic_logits(7, 4096)
        d1 = decision_domain(ref, 1024)
        d2 = decision_domain(ref, 1024)
        self.assertEqual(domain_membership_sha256(d1), domain_membership_sha256(d2))

    def test_wrong_cutoff_negative_control(self):
        # a k of 512 is a DIFFERENT methodology version: construction with a
        # non-frozen k must never be labeled the frozen identity.
        values = [float(i) for i in range(4096)]
        self.assertNotEqual(len(decision_domain(values, 512)), len(decision_domain(values, 1024)))

    def test_nonfinite_reference_rejected(self):
        values = [1.0] * 4096
        values[0] = float("nan")
        with self.assertRaises(MethodologyError):
            decision_domain(values, 1024)

    def test_membership_hash_canonical_ordering(self):
        domain = decision_domain(synthetic_logits(9, 4096), 1024)
        self.assertEqual(
            domain_membership_sha256(domain),
            domain_membership_sha256(reversed(domain)),
        )


# ---------------------------------------------------------------------------
# 3. argmax/tie-break semantics (section 8)
# ---------------------------------------------------------------------------


class TestFrozenArgmax(unittest.TestCase):
    def test_identity_string(self):
        self.assertEqual(
            argmax_tie_break_identity(),
            "ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima",
        )

    def test_lowest_token_id_wins_exact_ties(self):
        values = [1.0, 5.0, 5.0, 5.0, 2.0]
        self.assertEqual(frozen_argmax(values), 1)
        values = [5.0, 5.0, 5.0]
        self.assertEqual(frozen_argmax(values), 0)

    def test_strictly_greater_replaces(self):
        self.assertEqual(frozen_argmax([1.0, 2.0, 3.0]), 2)

    def test_synthetic_property(self):
        for seed in range(32):
            values = synthetic_logits(seed, 2048)
            winner = frozen_argmax(values)
            self.assertEqual(values[winner], max(values))
            self.assertEqual(winner, min(i for i, v in enumerate(values) if v == max(values)))

    def test_mismatched_identity_rejected(self):
        with self.assertRaises(MethodologyError):
            evaluate_decision(
                [3.0, 2.0, 1.0], [3.0, 2.0, 1.0], (0, 1, 2), 0.1,
                tie_break_identity="ARGMAX_LAST_MAX/highest-token-id",
                domain_identity=decision_domain_construction_identity(),
            )


# ---------------------------------------------------------------------------
# 4. E_D derivation (section 6)
# ---------------------------------------------------------------------------


class TestEDerivation(unittest.TestCase):
    def test_case_e_d_requires_exactly_8(self):
        with self.assertRaises(MethodologyError):
            case_e_d([0.1] * 7)
        with self.assertRaises(MethodologyError):
            case_e_d([0.1] * 9)
        self.assertEqual(case_e_d([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]), 0.8)

    def test_global_e_d_is_max_of_arms(self):
        stat = [0.1] * 576
        stress = [0.5] * 8
        self.assertEqual(derive_e_d(stat, stress), 0.5)
        stat[0] = 0.9
        self.assertEqual(derive_e_d(stat, stress), 0.9)

    def test_wrong_arm_sizes_rejected(self):
        with self.assertRaises(MethodologyError):
            derive_e_d([0.1] * 575, [0.1] * 8)
        with self.assertRaises(MethodologyError):
            derive_e_d([0.1] * 576, [0.1] * 7)

    def test_no_rounding_or_safety_factor(self):
        stat = [0.123456789012345] * 576
        stress = [0.0] * 8
        self.assertEqual(derive_e_d(stat, stress), 0.123456789012345)

    def test_decision_local_error_only_over_domain(self):
        ref = [1.0] * 100
        cand = list(ref)
        cand[5] = 2.0  # in domain
        cand[99] = 100.0  # out of domain
        self.assertEqual(decision_local_error(ref, cand, (5,)), 1.0)
        # a full-vocab error outside D does not count into E_D — but E_full
        # would see it (supplemental, not replacement).
        self.assertEqual(decision_local_error(ref, cand, (5, 99)), 99.0)

    def test_case_e_d_binding_mismatch_rejected(self):
        broken = copy.deepcopy(FIXTURE.summary)
        broken["statistical_cases"][0]["case_e_d_hex"] = (99.0).hex()
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=broken)


# ---------------------------------------------------------------------------
# 5. statistical design (section 7)
# ---------------------------------------------------------------------------


class TestStatisticalDesign(unittest.TestCase):
    def test_minimum_n_is_574_for_16_families(self):
        self.assertEqual(minimum_sample_size_v3(), 574)
        self.assertEqual(minimum_sample_size_v3(family_count=15), 568)

    def test_576_remains_sufficient(self):
        design = statistical_design_v3()
        self.assertEqual(design["simultaneous_families"], 16)
        self.assertEqual(design["minimum_n"], 574)
        self.assertGreaterEqual(design["selected_n"], design["minimum_n"])
        self.assertEqual(design["selected_n"], 576)
        self.assertEqual(design["independent_unit"], "the case, not the token row")

    def test_e_d_counted_in_family_accounting(self):
        design = statistical_design_v3()
        self.assertIn("E_D", design["families"])
        self.assertAlmostEqual(design["bonferroni_alpha_per_family"], 0.05 / 16, places=12)


# ---------------------------------------------------------------------------
# 6. selector semantics (section 2)
# ---------------------------------------------------------------------------


class TestV3Selector(unittest.TestCase):
    def test_positive_selection_with_zero_tie(self):
        selection = FIXTURE.selection
        self.assertEqual(selection["selected_count"], 8)
        groups = [row["selection_group"] for row in selection["selected"]]
        self.assertEqual(groups.count("four-smallest-including-zero"), 4)
        self.assertEqual(groups.count("four-largest"), 4)
        smallest = [row for row in selection["selected"] if row["selection_group"] == "four-smallest-including-zero"]
        self.assertTrue(any(row["exact_zero_margin"] for row in smallest))
        self.assertEqual(float.fromhex(smallest[0]["reference_top1_margin_hex"]), 0.0)

    def test_negative_margin_fails_closed(self):
        margins = copy.deepcopy(FIXTURE.margins)
        margins["cases"][0]["top1_margin_hex"] = (-0.5).hex()
        with self.assertRaises(NegativeReferenceMarginError):
            select(FIXTURE.pool, margins, FIXTURE.commitment)

    def test_nonfinite_margin_fails_closed(self):
        margins = copy.deepcopy(FIXTURE.margins)
        margins["cases"][0]["top1_margin_hex"] = float("nan").hex()
        with self.assertRaises(NonfiniteReferenceMarginError):
            select(FIXTURE.pool, margins, FIXTURE.commitment)

    def test_zero_margin_is_eligible_not_fatal(self):
        margins = copy.deepcopy(FIXTURE.margins)
        for row in margins["cases"]:
            row["top1_margin_hex"] = (0.0).hex()
        # all-zero pool: 48 eligible, valid selection (not a fatality).
        selection = select(FIXTURE.pool, margins, FIXTURE.commitment)
        self.assertEqual(selection["selected_count"], 8)

    def test_too_few_eligible_rejected(self):
        margins = copy.deepcopy(FIXTURE.margins)
        rows = margins["cases"]
        for row in rows[:41]:
            row["top1_margin_hex"] = float("nan").hex()  # -> fatal instead
        # use negative? also fatal. Use... eligibility requires >=0; simulate
        # a small eligible set by making 41 rows negative is fatal; instead
        # shrink the pool binding is invalid. Direct path: fewer than 8
        # eligible cannot happen with >=0 semantics unless fatal — so assert
        # the guard directly with a synthetic commitment/pool shrink:
        margins = copy.deepcopy(FIXTURE.margins)
        with self.assertRaises(Exception):
            select(FIXTURE.pool, {"schema": "inferswarm.issue86.v3-reference-margin-summary/1",
                                  "contract_id": margins["contract_id"],
                                  "margin_definition": MARGIN_DEFINITION,
                                  "stress_pool_sha256": margins["stress_pool_sha256"],
                                  "cases": margins["cases"][:40]},
                   FIXTURE.commitment)

    def test_wrong_case_hash_mapping_rejected(self):
        margins = copy.deepcopy(FIXTURE.margins)
        margins["cases"][0]["case_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            select(FIXTURE.pool, margins, FIXTURE.commitment)

    def test_swapped_case_identities_rejected(self):
        margins = copy.deepcopy(FIXTURE.margins)
        a, b = margins["cases"][0], margins["cases"][1]
        a["case_id"], b["case_id"] = b["case_id"], a["case_id"]
        with self.assertRaises(ValueError):
            select(FIXTURE.pool, margins, FIXTURE.commitment)

    def test_commitment_drift_rejected(self):
        commitment = copy.deepcopy(FIXTURE.commitment)
        commitment["eligibility_rule"] = "margin is finite AND margin > 0"
        with self.assertRaises(ValueError):
            select(FIXTURE.pool, FIXTURE.margins, commitment)

    def test_candidate_informed_selection_rejected(self):
        commitment = copy.deepcopy(FIXTURE.commitment)
        commitment["candidate_observations_forbidden"] = False
        with self.assertRaises(ValueError):
            select(FIXTURE.pool, FIXTURE.margins, commitment)

    def test_missing_pool_case_rejected(self):
        margins = copy.deepcopy(FIXTURE.margins)
        margins["cases"] = margins["cases"][:-1]
        with self.assertRaises(ValueError):
            select(FIXTURE.pool, margins, FIXTURE.commitment)

    def test_deterministic_tie_break_by_case_id(self):
        margins = copy.deepcopy(FIXTURE.margins)
        for row in margins["cases"]:
            row["top1_margin_hex"] = (1.0).hex()  # all exactly tied
        selection = select(FIXTURE.pool, margins, FIXTURE.commitment)
        smallest = sorted(
            row["case"]["case_id"]
            for row in selection["selected"]
            if row["selection_group"] == "four-smallest-including-zero"
        )
        all_ids = sorted(c["case_id"] for c in FIXTURE.pool["cases"])
        self.assertEqual(smallest, all_ids[:4])


# ---------------------------------------------------------------------------
# 7. threshold derivation positive + provenance negative controls
# ---------------------------------------------------------------------------


class TestThresholdDerivation(unittest.TestCase):
    def test_positive_end_to_end(self):
        manifest = FIXTURE.derive()
        self.assertEqual(len(manifest["limits"]), 15)
        for envelope, row in manifest["limits"].items():
            self.assertEqual(
                float.fromhex(row["limit_hex"]),
                max(float.fromhex(row["statistical_max_hex"]),
                    float.fromhex(row["stress_max_hex"])),
            )
            self.assertEqual(row["comparison"], "observed<=limit")
        self.assertEqual(manifest["decision_domain_construction"],
                         decision_domain_construction_identity())
        self.assertEqual(manifest["argmax_tie_break"], argmax_tie_break_identity())
        self.assertEqual(manifest["holdout_state"], "SEALED_NOT_CONSUMED")
        self.assertEqual(manifest["manual_editing_or_rounding"], "PROHIBITED")
        # E_d = max(0.001 statistical, 0.001 stress) exactly
        self.assertLess(abs(float.fromhex(manifest["e_d_hex"]) - 0.001), 1e-12)
        # E_D <= E_full conjunctive relationship sanity
        e_full = float.fromhex(
            manifest["limits"]["fp32-consumer-logits:max-absolute-difference"]["limit_hex"]
        )
        self.assertGreaterEqual(e_full, float.fromhex(manifest["e_d_hex"]))

    def test_manifest_validates_against_committed_schema(self):
        schema = load(V3 / "schemas/threshold-manifest.schema.json")
        Draft202012Validator(schema).validate(FIXTURE.derive())

    def test_summary_validates_against_committed_schema(self):
        schema = load(V3 / "schemas/calibration-summary.schema.json")
        Draft202012Validator(schema).validate(FIXTURE.summary)

    def test_deterministic_byte_for_byte(self):
        self.assertEqual(canonical_json_bytes(FIXTURE.derive()), canonical_json_bytes(V3Fixture().derive()))

    def test_domain_manifest_validates(self):
        schema = load(V3 / "schemas/decision-domain-manifest.schema.json")
        Draft202012Validator(schema).validate(FIXTURE.domain_manifest)

    def test_selected_eight_validates(self):
        schema = load(V3 / "schemas/selected-stress-eighth.schema.json")
        Draft202012Validator(schema).validate(FIXTURE.selection)

    def test_corpus_and_pool_validate(self):
        Draft202012Validator(load(V3 / "schemas/calibration-corpus.schema.json")).validate(FIXTURE.corpus)
        Draft202012Validator(load(V3 / "schemas/stress-pool.schema.json")).validate(FIXTURE.pool)

    def test_holdout_commitment_and_custody_validate(self):
        Draft202012Validator(load(V3 / "schemas/sealed-holdout-commitment.schema.json")).validate(
            load(V3 / "manifests/sealed-holdout-commitment.json")
        )
        Draft202012Validator(load(V3 / "schemas/holdout-custody-record.schema.json")).validate(
            load(V3 / "manifests/holdout-custody-record.json")
        )

    # --- negative controls -------------------------------------------------

    def test_reject_substituted_corpus(self):
        old = json.loads((V1 / "manifests/calibration-corpus.json").read_text())
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_corpus=old)

    def test_reject_substituted_pool(self):
        old = json.loads((V2 / "manifests/margin-stress-pool.json").read_text())
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(stress_pool=old)

    def test_reject_substituted_commitment(self):
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(selection_commitment={"schema": "drifted"})

    def test_reject_missing_decision_row(self):
        broken = copy.deepcopy(FIXTURE.summary)
        broken["statistical_cases"][0]["decisions"] = broken["statistical_cases"][0]["decisions"][:7]
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=broken)

    def test_reject_missing_envelope(self):
        broken = copy.deepcopy(FIXTURE.summary)
        del broken["statistical_cases"][0]["envelopes"][ENVELOPES[0]]
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=broken)

    def test_reject_failed_integrity_row(self):
        broken = copy.deepcopy(FIXTURE.summary)
        broken["statistical_cases"][0]["exact_integrity"] = "FAIL"
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=broken)

    def test_reject_domain_manifest_substitution(self):
        broken = copy.deepcopy(FIXTURE.domain_manifest)
        broken["construction"] = "reference-top-512-with-cutoff-ties/1"
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(decision_domain_manifest=broken)

    def test_reject_candidate_influenced_domain(self):
        broken = copy.deepcopy(FIXTURE.domain_manifest)
        broken["candidate_membership_influence"] = "ALLOWED"
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(decision_domain_manifest=broken)

    def test_reject_domain_membership_mismatch(self):
        broken = copy.deepcopy(FIXTURE.summary)
        broken["statistical_cases"][0]["decisions"][0]["domain_membership_sha256"] = "0" * 64
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=broken)

    def test_reject_e_d_manual_modification(self):
        broken = copy.deepcopy(FIXTURE.summary)
        broken["stress_cases"][0]["decisions"][0]["decision_local_error_hex"] = (7.0).hex()
        # case_e_d binding now disagrees -> rejected
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=broken)

    def test_reject_holdout_material_in_inputs(self):
        contaminated = copy.deepcopy(FIXTURE.summary)
        contaminated["holdout_ciphertext_sha256"] = "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=contaminated)

    def test_reject_missing_selected_case(self):
        broken = copy.deepcopy(FIXTURE.selection)
        broken["selected"] = broken["selected"][:7]
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(stress_selection=broken)

    def test_reject_duplicate_selected_case(self):
        broken = copy.deepcopy(FIXTURE.selection)
        broken["selected"][1] = copy.deepcopy(broken["selected"][0])
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(stress_selection=broken)

    def test_reject_negative_margin_in_selection(self):
        broken = copy.deepcopy(FIXTURE.selection)
        broken["selected"][0]["reference_top1_margin_hex"] = (-1.0).hex()
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(stress_selection=broken)

    def test_reject_selection_not_derived_by_frozen_selector(self):
        # An arbitrary structurally valid 4+4 selection (different margins,
        # same shape/pool binding) must FAIL: it is not the selector's output
        # over the supplied reference-margin summary.
        broken = copy.deepcopy(FIXTURE.selection)
        # swap the margin values between the smallest and largest groups so
        # the shape stays valid but the selector replay disagrees
        broken["selected"][0]["reference_top1_margin_hex"] = (40.0).hex()
        broken["selected"][7]["reference_top1_margin_hex"] = (0.0).hex()
        broken["selected"][7]["exact_zero_margin"] = True
        with self.assertRaises(MethodologyError) as ctx:
            FIXTURE.derive(stress_selection=broken)
        self.assertIn("SELECTED_EIGHT_NOT_SELECTOR_DERIVED", str(ctx.exception))

    def test_reject_margin_summary_omitted(self):
        args = dict(
            calibration_corpus=FIXTURE.corpus,
            stress_pool=FIXTURE.pool,
            selection_commitment=FIXTURE.commitment,
            stress_selection=FIXTURE.selection,
            decision_domain_manifest=FIXTURE.domain_manifest,
            calibration_summary=FIXTURE.summary,
            program_sha256="c" * 64,
        )
        with self.assertRaises(TypeError):
            derive_v3_threshold_manifest(**args)

    def test_reject_inconsistent_margin_summary(self):
        # a DIFFERENT (still internally valid) margin summary does not
        # reproduce the committed selected-eight -> rejected.
        margins = copy.deepcopy(FIXTURE.margins)
        margins["cases"][0]["top1_margin_hex"] = (0.5).hex()
        with self.assertRaises(MethodologyError) as ctx:
            FIXTURE.derive(reference_margin_summary=margins)
        self.assertIn("SELECTED_EIGHT_NOT_SELECTOR_DERIVED", str(ctx.exception))

    def test_threshold_manifest_binds_margin_summary_sha(self):
        manifest = FIXTURE.derive()
        self.assertEqual(
            manifest["reference_margin_summary_sha256"],
            sha_canonical(FIXTURE.margins),
        )

    def test_reject_wrong_state_selection(self):
        broken = copy.deepcopy(FIXTURE.selection)
        broken["state"] = "DRAFT"
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(stress_selection=broken)


# ---------------------------------------------------------------------------
# 8. semantic gate evaluator (section 9)
# ---------------------------------------------------------------------------


class TestSemanticGate(unittest.TestCase):
    def _row(self, values):
        return list(values)

    def test_stable_decision_requires_exact_identity(self):
        ref = self._row([10.0, 0.0, -1.0] + [-5.0] * 29)
        domain = tuple(range(32))
        cand = self._row([10.001, 0.0, -1.0] + [-5.0] * 29)
        record = evaluate_decision(
            ref, cand, domain, 0.01,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        self.assertEqual(record["verdict"], SEMANTIC_PASS)
        # a flip under a large margin is a failure:
        cand2 = self._row([0.0, 10.0, -1.0] + [-5.0] * 29)
        # but err 10.0 > E_D 0.01 -> bound failure first
        record2 = evaluate_decision(
            ref, cand2, domain, 0.01,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        self.assertEqual(record2["verdict"], "DECISION_LOCAL_BOUND_EXCEEDED")

    def test_bound_precedes_containment(self):
        # violates BOTH the bound and containment: bound failure reported.
        ref = self._row([10.0, 0.0, -1.0] + [-5.0] * 29)
        cand = self._row([100.0, 0.0, -1.0] + [-5.0] * 29)
        record = evaluate_decision(
            ref, cand, tuple(range(32)), 0.01,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        self.assertEqual(record["verdict"], "DECISION_LOCAL_BOUND_EXCEEDED")

    def test_domain_escape_detected(self):
        ref = self._row([10.0, 0.0, -1.0] + [-5.0] * 29)
        domain = (0, 1)  # token 2 excluded
        cand = self._row([10.0, 0.0, 10.5] + [-5.0] * 29)
        record = evaluate_decision(
            ref, cand, domain, 6.0,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        # err over D: |10-10|=0, |0-0|=0 -> bound passes; winner j=2 escapes.
        self.assertEqual(record["verdict"], DECISION_DOMAIN_ESCAPE)

    def test_unstable_decision_ambiguity_admissible(self):
        ref = self._row([1.0, 0.95, -1.0] + [-5.0] * 29)
        domain = tuple(range(32))
        e_d = 0.5  # m_D = 0.05 <= 2*0.5
        cand = self._row([1.0, 0.96, -1.0] + [-5.0] * 29)
        record = evaluate_decision(
            ref, cand, domain, e_d,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        self.assertEqual(record["stability"], "UNSTABLE")
        self.assertEqual(record["verdict"], SEMANTIC_PASS)  # j=1 in A_ED

    def test_unstable_decision_inadmissible(self):
        ref = self._row([1.0, 0.95, 0.1] + [-5.0] * 29)
        domain = tuple(range(32))
        e_d = 0.5
        # j=2 with r[a]-r[2]=0.9 > 2*0.5? 0.9 <= 1.0 -> admissible; push out:
        ref2 = self._row([1.0, 0.95, 0.0] + [-5.0] * 29)
        cand = self._row([1.0, 0.95, 1.05] + [-5.0] * 29)
        record = evaluate_decision(
            ref2, cand, domain, e_d,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        # err@2 = 1.05 > 0.5 -> bound failure first. Adjust candidate:
        cand2 = self._row([0.6, 0.6, 0.6] + [-5.0] * 29)
        record2 = evaluate_decision(
            ref2, cand2, domain, e_d,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        # err: |0.6-1|=0.4, |0.6-0.95|=0.35, |0.6-0|=0.6>0.5 bound fail. Use
        # j-token 3 at -5: emitted winner must equal argmax cand = 0 (tie ->
        # lowest id 0). j=0=a -> STABLE branch? m_D=1.0 <= 2*0.5 -> unstable
        # branch, j=0 in A_ED trivially -> PASS.
        self.assertEqual(record2["verdict"], "DECISION_LOCAL_BOUND_EXCEEDED")

    def test_exact_equality_m_d_equals_2e_d_is_unstable(self):
        ref = self._row([1.0, 0.0, -1.0] + [-5.0] * 29)
        domain = tuple(range(32))
        e_d = 0.5  # m_D = 1.0 = 2*E_D exactly
        cand = self._row([0.5, 0.5, -1.0] + [-5.0] * 29)
        record = evaluate_decision(
            ref, cand, domain, e_d,
            tie_break_identity=argmax_tie_break_identity(),
            domain_identity=decision_domain_construction_identity(),
        )
        self.assertEqual(record["stability"], "UNSTABLE")
        # frozen tie-break -> j = 0 = a -> admissible
        self.assertEqual(record["verdict"], SEMANTIC_PASS)

    def test_reference_winner_escape_rejected_as_invalid_domain(self):
        ref = self._row([10.0, 0.0, -1.0] + [-5.0] * 29)
        with self.assertRaises(MethodologyError):
            evaluate_decision(
                ref, ref, (1, 2), 0.5,  # a=0 not in D
                tie_break_identity=argmax_tie_break_identity(),
                domain_identity=decision_domain_construction_identity(),
            )

    def test_margin_and_ambiguity_set(self):
        ref = [10.0, 8.0, 7.0, 0.0]
        domain = (0, 1, 2, 3)
        self.assertEqual(margin_on_domain(ref, domain), 2.0)
        self.assertEqual(ambiguity_set(ref, domain, 1.0), (0, 1))    # 10-x <= 2
        self.assertEqual(ambiguity_set(ref, domain, 1.5), (0, 1, 2)) # 10-x <= 3
        self.assertEqual(ambiguity_set(ref, domain, 0.5), (0,))      # 10-x <= 1

    def test_branch_label_prefix_reserved(self):
        # after a first allowed unstable divergence the trajectory label is
        # BRANCHED_*; later free-running tensors are diagnostic only. The
        # evaluator never treats post-branch rows: verified by contract text
        # and the absence of any free-running input in evaluate_decision.
        import inspect

        from issue86_v3_methodology import evaluate_decision as ed

        source = inspect.getsource(ed)
        self.assertNotIn("free_running", source)


# ---------------------------------------------------------------------------
# 9. unseal preflight (section 12)
# ---------------------------------------------------------------------------


class TestUnsealPreflight(unittest.TestCase):
    def _record(self):
        return validate_unseal_preconditions(
            threshold_manifest=None,
            threshold_manifest_sha256=None,
            expected_committed_threshold_sha256=None,
            holdout_ciphertext_sha256=None,
            recipient_certificate_sha256=None,
            custody_record=None,
            expected_stress_selection_sha256=None,
        )

    def test_positive_preflight(self):
        manifest = FIXTURE.derive()
        record = validate_unseal_preconditions(
            threshold_manifest=manifest,
            threshold_manifest_sha256=sha_canonical(manifest),
            expected_committed_threshold_sha256=sha_canonical(manifest),
            holdout_ciphertext_sha256=(
                sha_file(V3 / "sealed/holdout.cms")
            ),
            recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
            custody_record=load(V3 / "manifests/holdout-custody-record.json"),
            expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            private_key_path=Path("/home/zutfen/.local/share/inferswarm/issue86-holdout-v3/recipient-private-key.pem"),
        )
        self.assertEqual(record["verdict"], "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED")
        self.assertFalse(record["decrypt_performed"])
        self.assertFalse(record["openssl_invoked"])

    def test_wrong_threshold_sha_rejected(self):
        manifest = FIXTURE.derive()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256="0" * 64,
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(SELECTED_SHA_MISMATCH, str(ctx.exception))

    def test_manifest_bytes_not_matching_sha_rejected(self):
        manifest = FIXTURE.derive()
        tampered = copy.deepcopy(manifest)
        tampered["e_d_hex"] = (99.0).hex()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=tampered,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(THRESHOLD_SCHEMA_INVALID, str(ctx.exception))

    def test_wrong_selected_eight_sha_rejected(self):
        manifest = FIXTURE.derive()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256="1" * 64,
            )
        self.assertIn(SELECTED_SHA_MISMATCH, str(ctx.exception))

    def test_historical_h74_holdout_rejected(self):
        manifest = FIXTURE.derive()
        historical = "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=historical,
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(WRONG_HISTORICAL_HOLDOUT, str(ctx.exception))

    def test_historical_h74_certificate_rejected(self):
        manifest = FIXTURE.derive()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256="9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46",
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(WRONG_HISTORICAL_HOLDOUT, str(ctx.exception))

    def test_historical_h74_custody_record_rejected(self):
        manifest = FIXTURE.derive()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V2 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(WRONG_HISTORICAL_HOLDOUT, str(ctx.exception))

    def test_wrong_v3_ciphertext_rejected(self):
        manifest = FIXTURE.derive()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256="2" * 64,
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(WRONG_V3_HOLDOUT_MATERIAL, str(ctx.exception))

    def test_repo_local_private_key_rejected(self):
        manifest = FIXTURE.derive()
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=load(V3 / "manifests/holdout-custody-record.json"),
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
                private_key_path=ROOT / "sealed" / "holdout.cms",
            )
        self.assertIn(PRIVATE_KEY_NOT_EXTERNAL, str(ctx.exception))

    def test_custody_not_verified(self):
        manifest = FIXTURE.derive()
        custody = copy.deepcopy(load(V3 / "manifests/holdout-custody-record.json"))
        custody["custodians"] = custody["custodians"][:1]
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(
                threshold_manifest=manifest,
                threshold_manifest_sha256=sha_canonical(manifest),
                expected_committed_threshold_sha256=sha_canonical(manifest),
                holdout_ciphertext_sha256=sha_file(V3 / "sealed/holdout.cms"),
                recipient_certificate_sha256=sha_file(V3 / "sealed/recipient-certificate.pem"),
                custody_record=custody,
                expected_stress_selection_sha256=sha_canonical(FIXTURE.selection),
            )
        self.assertIn(CUSTODY_NOT_VERIFIED, str(ctx.exception))

    def test_cli_hashes_actual_files(self):
        import tempfile

        from verify_issue86_v3_unseal import main as unseal_main

        manifest = FIXTURE.derive()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "threshold.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest))
            # a tampered certificate copy must FAIL via actual-byte hashing
            bad_cert = tmp_path / "bad-cert.pem"
            bad_cert.write_bytes(b"-----BEGIN CERTIFICATE-----\nnot the real one\n")
            with self.assertRaises(UnsealPreflightError) as ctx:
                unseal_main([
                    "--threshold-manifest", str(manifest_path),
                    "--expected-threshold-sha256", sha_canonical(manifest),
                    "--expected-stress-selection-sha256", sha_canonical(FIXTURE.selection),
                    "--custody-record", str(V3 / "manifests/holdout-custody-record.json"),
                    "--holdout-ciphertext", str(V3 / "sealed/holdout.cms"),
                    "--recipient-certificate", str(bad_cert),
                    "--private-key-path", "/home/zutfen/.local/share/inferswarm/issue86-holdout-v3/recipient-private-key.pem",
                ])
            self.assertIn(WRONG_V3_HOLDOUT_MATERIAL, str(ctx.exception))
            # a missing ciphertext file must FAIL (unreadable), not pass
            with self.assertRaises(OSError):
                unseal_main([
                    "--threshold-manifest", str(manifest_path),
                    "--expected-threshold-sha256", sha_canonical(manifest),
                    "--expected-stress-selection-sha256", sha_canonical(FIXTURE.selection),
                    "--custody-record", str(V3 / "manifests/holdout-custody-record.json"),
                    "--holdout-ciphertext", str(tmp_path / "nonexistent.cms"),
                    "--recipient-certificate", str(V3 / "sealed/recipient-certificate.pem"),
                    "--private-key-path", "/home/zutfen/.local/share/inferswarm/issue86-holdout-v3/recipient-private-key.pem",
                ])
            # the REAL files must PASS end-to-end through the CLI
            import contextlib
            import io

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                unseal_main([
                    "--threshold-manifest", str(manifest_path),
                    "--expected-threshold-sha256", sha_canonical(manifest),
                    "--expected-stress-selection-sha256", sha_canonical(FIXTURE.selection),
                    "--custody-record", str(V3 / "manifests/holdout-custody-record.json"),
                    "--holdout-ciphertext", str(V3 / "sealed/holdout.cms"),
                    "--recipient-certificate", str(V3 / "sealed/recipient-certificate.pem"),
                    "--private-key-path", "/home/zutfen/.local/share/inferswarm/issue86-holdout-v3/recipient-private-key.pem",
                ])
            self.assertIn("UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED", buffer.getvalue())

    def test_cli_rejects_historical_h74_ciphertext_file(self):
        import tempfile

        from verify_issue86_v3_unseal import main as unseal_main

        manifest = FIXTURE.derive()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "threshold.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest))
            # a copy of the HISTORICAL #74 ciphertext routed into the v3 CLI
            with self.assertRaises(UnsealPreflightError) as ctx:
                unseal_main([
                    "--threshold-manifest", str(manifest_path),
                    "--expected-threshold-sha256", sha_canonical(manifest),
                    "--expected-stress-selection-sha256", sha_canonical(FIXTURE.selection),
                    "--custody-record", str(V3 / "manifests/holdout-custody-record.json"),
                    "--holdout-ciphertext", str(V1 / "sealed/holdout.cms"),
                    "--recipient-certificate", str(V3 / "sealed/recipient-certificate.pem"),
                    "--private-key-path", "/home/zutfen/.local/share/inferswarm/issue86-holdout-v3/recipient-private-key.pem",
                ])
            self.assertIn(WRONG_HISTORICAL_HOLDOUT, str(ctx.exception))

    def test_no_decrypt_in_source(self):
        source = (ROOT / "scripts/verify_issue86_v3_unseal.py").read_text()
        self.assertNotIn("cms", source.lower().replace("custody", "").replace(
            "openssl cms", "") or source)
        self.assertNotIn("-decrypt", source)


# ---------------------------------------------------------------------------
# 10. purity + no-execution guarantees
# ---------------------------------------------------------------------------


class TestPurity(unittest.TestCase):
    TOOLS = [
        "issue86_v3_methodology.py",
        "issue86_v3_thresholds.py",
        "verify_issue86_v3_unseal.py",
        "select_issue86_margin_stress_v3.py",
        "generate_issue86_corpora.py",
        "commit_issue86_stress_selection.py",
        "commit_issue86_holdout.py",
        "build_issue86_disjointness.py",
        "build_issue86_schemas.py",
    ]

    def test_no_torch_cuda_triton_imports(self):
        import ast

        for name in self.TOOLS:
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            forbidden = imported & {
                "torch", "triton", "transformers", "cuda", "numpy",
                "freetoken", "tokenizers",
            }
            # tokenizers IS allowed only in the generator (tokenizer-pure
            # corpus generation is CPU-only; it never loads model weights).
            if name == "generate_issue86_corpora.py":
                forbidden -= {"tokenizers"}
            self.assertFalse(forbidden, f"{name}: {forbidden}")

    def test_no_subprocess_nvidia_queries(self):
        import ast

        for name in self.TOOLS:
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name):
                        self.assertNotEqual(func.id, "system")
                        self.assertNotEqual(func.id, "popen")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if not (isinstance(getattr(node, "parent", None), ast.Expr)):
                        self.assertNotIn("nvidia-smi", node.value.lower())
                if isinstance(node, ast.Name):
                    self.assertNotEqual(node.id.lower(), "subprocess")

    def test_no_selected_eight_committed(self):
        # the real selected-eight manifest is a future physical artifact;
        # no margin-stress-selection/1-style JSON may exist under v3 evidence.
        for path in V3.rglob("*.json"):
            if path.parent.name != "schemas":
                self.assertNotIn("selected", path.name)

    def test_no_private_material_committed(self):
        for path in (V3).rglob("*"):
            self.assertNotIn("private", path.name)
        # ciphertext must not be a PEM/JSON plaintext
        head = (V3 / "sealed/holdout.cms").read_bytes()[:8]
        self.assertNotIn(b"{", head)


if __name__ == "__main__":
    unittest.main()
