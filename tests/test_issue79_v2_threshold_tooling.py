"""Issue #79: versioned v2 threshold/calibration/unseal tooling tests.

CPU-only, static, synthetic. No model execution, no CUDA, no GPU queries,
no holdout decryption. The selected-eight manifest used by the positive
fixture is TEST-ONLY SYNTHETIC EVIDENCE generated in memory from
deterministic synthetic reference margins via the accepted real v2 selector
— it is NOT a real future physical artifact and is never written into the
qualification evidence directory.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue74_methodology import CONTRACT_ID, ENVELOPES  # noqa: E402
from issue79_v2_thresholds import (  # noqa: E402
    CALIBRATION_CORPUS_SHA256,
    V2_COMMITMENT_SHA256,
    V2_POOL_SHA256,
    V2_SELECTION_STATE,
    MethodologyError,
    canonical_json_bytes,
    derive_v2_threshold_manifest,
    sha256_bytes,
)
from select_issue76_margin_stress_v2 import MARGIN_DEFINITION, select  # noqa: E402
from verify_issue79_v2_unseal import (  # noqa: E402
    CUSTODY_NOT_VERIFIED,
    EXPECTED_RECIPIENT_CERTIFICATE_SHA256,
    HOLDOUT_CIPHERTEXT_SHA256,
    PRIVATE_KEY_NOT_EXTERNAL,
    REPO_ROOT,
    SELECTED_SHA_MISMATCH,
    THRESHOLD_SCHEMA_INVALID,
    UnsealPreflightError,
    load_threshold_schema,
    main as unseal_main,
    validate_unseal_preconditions,
)

V1 = ROOT / "docs/qualification/gemma4-12b-it-v1"
V2 = ROOT / "docs/qualification/gemma4-12b-it-v2"
CUSTODY_RECORD_PATH = V2 / "manifests/holdout-custody-record.json"
THRESHOLD_SCHEMA_PATH = V2 / "schemas/threshold-manifest.schema.json"
# External accepted key locations (never read; externality proof only).
EXTERNAL_KEY_ORCHESTRATOR = (
    "/home/zutfen/.local/share/inferswarm/issue74-holdout-v1/recipient-private-key.pem"
)
EXTERNAL_KEY_INFERSWARM00 = (
    "/srv/inferswarm/state/issue74-holdout-custody/recipient-private-key.pem"
)

# Frozen identity constants (issue #79 text; also asserted against files).
FROZEN_CORPUS_SHA = "e147ce0a672fe7f8616f9e000fea770bfeab6e0a1aca637ffe6bc07cd64c3175"
FROZEN_POOL_SHA = "533b32857721b3f99243e5695bc18b24960cbd3c80692d626154907d6ecbd7c9"
FROZEN_SELECTOR_SHA = "e32e8672671c3b3ec6b47e3b119c66fd54e2c5a62ba72fb2ec2288764508beab"
FROZEN_COMMITMENT_SHA = "04421a6f19f6338a340dfea296214509eae3adc5ca32067dfd76880ab1cacba0"
FROZEN_HOLDOUT_SHA = "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"
FROZEN_CERT_SHA = "9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46"
ACCEPTED_V2_BASE_SHA = "8905566031e0296694b3f1288d0f9d1ae15f8134"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def sha_canonical(value: dict) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary_case(case: dict, default: float) -> dict:
    return {
        "case_id": case["case_id"],
        "case_sha256": case["case_sha256"],
        "exact_integrity": "PASS",
        "semantic_output": "PASS",
        "finite": True,
        "evidence_complete": True,
        "envelopes": {name: float(default).hex() for name in ENVELOPES},
    }


class V2Fixture:
    """Deterministic synthetic end-to-end fixture (TEST-ONLY SYNTHETIC
    EVIDENCE — never committed to the qualification evidence directory)."""

    def __init__(self) -> None:
        self.corpus = load(V1 / "manifests/calibration-corpus.json")
        self.pool = load(V2 / "manifests/margin-stress-pool.json")
        self.commitment = load(V2 / "manifests/margin-stress-selection-commitment.json")
        # Synthetic deterministic reference margins: strictly increasing by
        # reversed case index — deterministic, finite, positive, physical-free.
        self.margins = {
            "schema": "inferswarm.issue76.reference-margin-summary/2",
            "contract_id": CONTRACT_ID,
            "margin_definition": MARGIN_DEFINITION,
            "stress_pool_sha256": sha_canonical(self.pool),
            "cases": [
                {
                    "case_id": case["case_id"],
                    "case_sha256": case["case_sha256"],
                    "top1_margin_hex": float(1 + index / 10).hex(),
                    "steps_nonpositive": 0,
                }
                for index, case in enumerate(reversed(self.pool["cases"]))
            ],
        }
        # Selector-generated synthetic selected-eight manifest.
        self.stress_selection = select(self.pool, self.margins, self.commitment)
        selected_cases = [row["case"] for row in self.stress_selection["selected"]]
        self.summary = {
            "schema": "inferswarm.issue79.v2-calibration-summary/1",
            "contract_id": CONTRACT_ID,
            "tooling_or_methodology_version": (
                "inferswarm.issue79.v2-threshold-tooling/1 "
                "(methodology v2 accepted at inferswarm@"
                + ACCEPTED_V2_BASE_SHA + ")"
            ),
            "calibration_corpus_sha256": sha_canonical(self.corpus),
            "stress_pool_sha256": sha_canonical(self.pool),
            "stress_selection_commitment_sha256": sha_canonical(self.commitment),
            "stress_selection_sha256": sha_canonical(self.stress_selection),
            "evidence_sha256": ["e" * 64, "f" * 64],
            "statistical_cases": [summary_case(case, 1.0) for case in self.corpus["cases"]],
            "stress_cases": [summary_case(case, 2.0) for case in selected_cases],
        }

    def derive(self, **overrides):
        args = dict(
            calibration_corpus=self.corpus,
            stress_pool=self.pool,
            selection_commitment=self.commitment,
            stress_selection=self.stress_selection,
            calibration_summary=self.summary,
            program_sha256="a" * 64,
        )
        args.update(overrides)
        return derive_v2_threshold_manifest(**args)


FIXTURE = V2Fixture()


class TestFrozenInputsUnchanged(unittest.TestCase):
    def test_calibration_corpus_sha_unchanged(self):
        self.assertEqual(sha_file(V1 / "manifests/calibration-corpus.json"), FROZEN_CORPUS_SHA)
        corpus = FIXTURE.corpus
        self.assertEqual(len(corpus["cases"]), 576)
        self.assertTrue(all(c["case_id"].startswith("c74-") for c in corpus["cases"]))

    def test_v2_stress_pool_sha_unchanged(self):
        self.assertEqual(sha_file(V2 / "manifests/margin-stress-pool.json"), FROZEN_POOL_SHA)

    def test_v2_selector_sha_unchanged(self):
        self.assertEqual(sha_file(ROOT / "scripts/select_issue76_margin_stress_v2.py"), FROZEN_SELECTOR_SHA)

    def test_v2_selection_commitment_sha_unchanged(self):
        self.assertEqual(
            sha_file(V2 / "manifests/margin-stress-selection-commitment.json"),
            FROZEN_COMMITMENT_SHA,
        )

    def test_holdout_ciphertext_and_certificate_sha_unchanged(self):
        self.assertEqual(sha_file(V1 / "sealed/holdout.cms"), FROZEN_HOLDOUT_SHA)
        self.assertEqual(sha_file(V1 / "sealed/recipient-certificate.pem"), FROZEN_CERT_SHA)

    def test_v1_review_manifest_hashes_every_listed_artifact(self):
        entries = (V1 / "MANIFEST.sha256").read_text().splitlines()
        self.assertGreater(len(entries), 20)
        for entry in entries:
            expected, relative = entry.split("  ", 1)
            self.assertEqual(sha_file(ROOT / relative), expected, relative)

    def test_v1_tooling_files_byte_identical_to_frozen_manifest(self):
        # The living v1 MANIFEST.sha256 pins the v1 derivation tool, selector,
        # seal script and tests; equality above proves byte-identity.
        manifest = dict(
            line.split("  ", 1)[::-1]
            for line in (V1 / "MANIFEST.sha256").read_text().splitlines()
        )
        for name in (
            "scripts/issue74_methodology.py",
            "scripts/select_issue74_margin_stress.py",
            "scripts/seal_issue74_holdout.py",
            "docs/qualification/gemma4-12b-it-v1/schemas/calibration-summary.schema.json",
            "docs/qualification/gemma4-12b-it-v1/schemas/threshold-manifest.schema.json",
        ):
            self.assertIn(name, manifest)
            self.assertEqual(sha_file(ROOT / name), manifest[name], name)


class TestV2Schemas(unittest.TestCase):
    def setUp(self):
        self.calibration_schema = load(V2 / "schemas/calibration-summary.schema.json")
        self.threshold_schema = load(V2 / "schemas/threshold-manifest.schema.json")

    def test_calibration_schema_is_versioned_v2_and_requires_provenance(self):
        self.assertEqual(
            self.calibration_schema["properties"]["schema"]["const"],
            "inferswarm.issue79.v2-calibration-summary/1",
        )
        for field in (
            "schema", "contract_id", "calibration_corpus_sha256", "stress_pool_sha256",
            "stress_selection_commitment_sha256", "stress_selection_sha256",
            "evidence_sha256", "statistical_cases", "stress_cases",
        ):
            self.assertIn(field, self.calibration_schema["required"])
        self.assertIs(self.calibration_schema["additionalProperties"], False)
        lowered = json.dumps(self.calibration_schema).lower()
        self.assertNotIn("holdout", lowered)
        self.assertNotIn("unseal", lowered)

    def test_threshold_schema_requires_all_commitment_fields(self):
        for field in (
            "schema", "contract_id", "tooling_or_methodology_version",
            "calibration_corpus_sha256", "calibration_summary_sha256",
            "calibration_evidence_sha256", "stress_pool_sha256",
            "stress_selection_commitment_sha256", "stress_selection_sha256",
            "derivation_program_sha256", "metric_reducer", "limits",
            "holdout_state", "manual_editing_or_rounding",
        ):
            self.assertIn(field, self.threshold_schema["required"])
        self.assertIs(self.threshold_schema["additionalProperties"], False)
        names = self.threshold_schema["properties"]["limits"]["propertyNames"]["enum"]
        self.assertEqual(len(names), 15)
        self.assertEqual(set(names), set(ENVELOPES))

    def test_synthetic_calibration_summary_validates(self):
        Draft202012Validator(self.calibration_schema).validate(FIXTURE.summary)

    def test_synthetic_threshold_manifest_validates(self):
        manifest = FIXTURE.derive()
        Draft202012Validator(self.threshold_schema).validate(manifest)


class TestPositiveSyntheticEndToEnd(unittest.TestCase):
    """Clearly synthetic CPU-only end-to-end proof."""

    def test_1_selected_eight_manifest_validates(self):
        selection = FIXTURE.stress_selection
        self.assertEqual(selection["schema"], "inferswarm.issue76.margin-stress-selection/2")
        self.assertEqual(selection["state"], V2_SELECTION_STATE)
        self.assertEqual(len(selection["selected"]), 8)
        pool_ids = {c["case_id"] for c in FIXTURE.pool["cases"]}
        for row in selection["selected"]:
            self.assertIn(row["case"]["case_id"], pool_ids)
            self.assertTrue(row["case"]["case_id"].startswith("p76-"))
        groups = [row["selection_group"] for row in selection["selected"]]
        self.assertEqual(groups.count("four-smallest-positive"), 4)
        self.assertEqual(groups.count("four-largest-positive"), 4)

    def test_2_calibration_summary_validates(self):
        schema = load(V2 / "schemas/calibration-summary.schema.json")
        Draft202012Validator(schema).validate(FIXTURE.summary)

    def test_3_threshold_derivation_succeeds(self):
        manifest = FIXTURE.derive()
        self.assertEqual(len(manifest["limits"]), 15)
        for row in manifest["limits"].values():
            self.assertEqual(row["rule"], "max(statistical_max,stress_max)")
            self.assertEqual(row["comparison"], "observed<=limit")
            self.assertEqual(
                row["limit_hex"],
                max(float.fromhex(row["statistical_max_hex"]),
                    float.fromhex(row["stress_max_hex"])).hex(),
            )

    def test_4_threshold_manifest_validates(self):
        schema = load(V2 / "schemas/threshold-manifest.schema.json")
        Draft202012Validator(schema).validate(FIXTURE.derive())

    def test_5_output_is_deterministic_byte_for_byte(self):
        first = canonical_json_bytes(FIXTURE.derive())
        second = canonical_json_bytes(V2Fixture().derive())
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_bytes(first)
            (Path(tmp) / "b.json").write_bytes(second)
            self.assertEqual(sha_file(Path(tmp) / "a.json"), sha_file(Path(tmp) / "b.json"))

    def test_6_unseal_preflight_succeeds_without_decrypt(self):
        manifest = FIXTURE.derive()
        record = validate_unseal_preconditions(
            threshold_manifest=manifest,
            threshold_manifest_sha256=sha_canonical(manifest),
            expected_committed_threshold_sha256=sha_canonical(manifest),
            holdout_ciphertext_sha256=HOLDOUT_CIPHERTEXT_SHA256,
            recipient_certificate_sha256=EXPECTED_RECIPIENT_CERTIFICATE_SHA256,
            custody_record=load(V2 / "manifests/holdout-custody-record.json"),
            expected_stress_selection_sha256=sha_canonical(FIXTURE.stress_selection),
        )
        self.assertEqual(record["verdict"], "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED")
        self.assertFalse(record["decrypt_performed"])
        self.assertFalse(record["openssl_invoked"])

    def test_threshold_math_is_unchanged_from_v1_semantics(self):
        # statistical arm dominates at 1.0 defaults, stress at 2.0 -> limit 2.0
        manifest = FIXTURE.derive()
        for envelope in ENVELOPES:
            row = manifest["limits"][envelope]
            self.assertEqual(float.fromhex(row["statistical_max_hex"]), 1.0)
            self.assertEqual(float.fromhex(row["stress_max_hex"]), 2.0)
            self.assertEqual(float.fromhex(row["limit_hex"]), 2.0)
        # flip one statistical value above the stress max
        mutated = copy.deepcopy(FIXTURE.summary)
        mutated["statistical_cases"][3]["envelopes"][ENVELOPES[7]] = (5.5).hex()
        manifest2 = derive_v2_threshold_manifest(
            calibration_corpus=FIXTURE.corpus,
            stress_pool=FIXTURE.pool,
            selection_commitment=FIXTURE.commitment,
            stress_selection=FIXTURE.stress_selection,
            calibration_summary=mutated,
            program_sha256="a" * 64,
        )
        self.assertEqual(float.fromhex(manifest2["limits"][ENVELOPES[7]]["limit_hex"]), 5.5)
        self.assertEqual(manifest2["metric_reducer"],
                         "host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1")


class TestStatisticalCorpusNegativeControls(unittest.TestCase):
    def assert_rejects(self, **overrides):
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(**overrides)

    def test_wrong_calibration_corpus_sha(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"][0]["prompt_text"] += " tampered"
        self.assert_rejects(calibration_corpus=corpus)

    def test_unknown_c74_case_id(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"][0]["case_id"] = "c74-unknown-case"
        self.assert_rejects(calibration_corpus=corpus)

    def test_correct_id_wrong_hash(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"][0]["case_sha256"] = "0" * 64
        self.assert_rejects(calibration_corpus=corpus)

    def test_duplicate_case(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"][1] = copy.deepcopy(corpus["cases"][0])
        self.assert_rejects(calibration_corpus=corpus)

    def test_substituted_case(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"][0], corpus["cases"][1] = (
            copy.deepcopy(corpus["cases"][1]), copy.deepcopy(corpus["cases"][0])
        )
        # swapping whole rows keeps the multiset; substitute identity only:
        corpus["cases"][2]["case_sha256"] = corpus["cases"][3]["case_sha256"]
        self.assert_rejects(calibration_corpus=corpus)

    def test_575_cases(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"].pop()
        self.assert_rejects(calibration_corpus=corpus)

    def test_577_cases(self):
        corpus = copy.deepcopy(FIXTURE.corpus)
        corpus["cases"].append(copy.deepcopy(corpus["cases"][0]))
        corpus["cases"][-1]["case_id"] = "c74-extra"
        self.assert_rejects(calibration_corpus=corpus)

    def test_summary_row_unknown_id_and_wrong_hash(self):
        bad_id = copy.deepcopy(FIXTURE.summary)
        bad_id["statistical_cases"][9]["case_id"] = "c74-not-in-corpus"
        self.assert_rejects(calibration_summary=bad_id)
        bad_hash = copy.deepcopy(FIXTURE.summary)
        bad_hash["statistical_cases"][9]["case_sha256"] = "1" * 64
        self.assert_rejects(calibration_summary=bad_hash)


class TestStressProvenanceNegativeControls(unittest.TestCase):
    def assert_rejects(self, **overrides):
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(**overrides)

    def test_v1_p74_stress_row(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["stress_cases"][0]["case_id"] = "p74-01-01-01"
        self.assert_rejects(calibration_summary=summary)

    def test_arbitrary_non_selected_p76_stress_row(self):
        summary = copy.deepcopy(FIXTURE.summary)
        selected_ids = {row["case"]["case_id"] for row in FIXTURE.stress_selection["selected"]}
        outsider = next(c for c in FIXTURE.pool["cases"] if c["case_id"] not in selected_ids)
        summary["stress_cases"][0] = summary_case(outsider, 2.0)
        self.assert_rejects(calibration_summary=summary)

    def test_correct_selected_id_wrong_hash(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["stress_cases"][0]["case_sha256"] = "2" * 64
        self.assert_rejects(calibration_summary=summary)

    def test_wrong_stress_pool_sha(self):
        pool = copy.deepcopy(FIXTURE.pool)
        pool["cases"][0]["prompt_text"] += " drift"
        self.assert_rejects(stress_pool=pool)

    def test_wrong_selection_commitment_sha(self):
        commitment = copy.deepcopy(FIXTURE.commitment)
        commitment["eligibility_rule"] = "margin > 0.5"
        self.assert_rejects(selection_commitment=commitment)

    def test_wrong_selected_manifest_sha_in_summary(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["stress_selection_sha256"] = "3" * 64
        self.assert_rejects(calibration_summary=summary)

    def test_selected_manifest_using_v1_schema(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["schema"] = "inferswarm.issue74.margin-stress-selection/1"
        self.assert_rejects(stress_selection=selection)

    def test_selected_manifest_wrong_state(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["state"] = "DRAFT"
        self.assert_rejects(stress_selection=selection)

    def test_selected_manifest_wrong_selection_inputs(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["selection_inputs"] = "CANDIDATE_MARGINS_INCLUDED"
        self.assert_rejects(stress_selection=selection)

    def test_selected_manifest_containing_non_pool_case(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        impostor = copy.deepcopy(FIXTURE.pool["cases"][0])
        impostor["prompt_text"] += " not in pool"
        selection["selected"][0]["case"] = impostor
        self.assert_rejects(stress_selection=selection)

    def test_duplicate_selected_case(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["selected"][1]["case"] = copy.deepcopy(selection["selected"][0]["case"])
        self.assert_rejects(stress_selection=selection)

    def test_fewer_than_eight_selected(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["selected"] = selection["selected"][:7]
        selection["selected_count"] = 7
        self.assert_rejects(stress_selection=selection)

    def test_more_than_eight_selected(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selected_ids = {row["case"]["case_id"] for row in selection["selected"]}
        outsider = next(c for c in FIXTURE.pool["cases"] if c["case_id"] not in selected_ids)
        selection["selected"].append({
            "selection_group": "four-largest-positive",
            "case": outsider,
            "reference_top1_margin_hex": (9.9).hex(),
        })
        selection["selected_count"] = 9
        self.assert_rejects(stress_selection=selection)

    def test_selected_manifest_margin_definition_drift(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["margin_definition"] = "max over 8 greedy steps of fp32(top1-top2)"
        self.assert_rejects(stress_selection=selection)

    def test_bad_grouping_shape(self):
        selection = copy.deepcopy(FIXTURE.stress_selection)
        selection["selected"][0]["selection_group"] = "four-largest-positive"
        self.assert_rejects(stress_selection=selection)


class TestCorrectnessGateNegativeControls(unittest.TestCase):
    def assert_rejects(self, summary):
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(calibration_summary=summary)

    def test_exact_integrity_fail(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["statistical_cases"][0]["exact_integrity"] = "FAIL"
        self.assert_rejects(summary)

    def test_semantic_output_fail(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["stress_cases"][0]["semantic_output"] = "FAIL"
        self.assert_rejects(summary)

    def test_finite_false(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["statistical_cases"][5]["finite"] = False
        self.assert_rejects(summary)

    def test_nonfinite_metric_hex(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["statistical_cases"][5]["envelopes"][ENVELOPES[0]] = float("inf").hex()
        self.assert_rejects(summary)

    def test_evidence_complete_false(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["stress_cases"][2]["evidence_complete"] = False
        self.assert_rejects(summary)

    def test_missing_one_envelope(self):
        summary = copy.deepcopy(FIXTURE.summary)
        del summary["statistical_cases"][0]["envelopes"][ENVELOPES[0]]
        self.assert_rejects(summary)

    def test_extra_envelope(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["statistical_cases"][0]["envelopes"]["bogus-family:bogus-metric"] = (1.0).hex()
        self.assert_rejects(summary)

    def test_duplicate_evidence_sha(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["evidence_sha256"] = ["e" * 64, "e" * 64]
        self.assert_rejects(summary)

    def test_invalid_evidence_sha(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["evidence_sha256"] = ["not-a-hash"]
        self.assert_rejects(summary)

    def test_wrong_row_count(self):
        summary = copy.deepcopy(FIXTURE.summary)
        summary["statistical_cases"].pop()
        self.assert_rejects(summary)
        summary = copy.deepcopy(FIXTURE.summary)
        summary["stress_cases"].pop()
        self.assert_rejects(summary)


class TestHoldoutPoisoningNegativeControls(unittest.TestCase):
    POISONS = [
        ("h74- id", "case_id", "h74-01"),
        ("holdout_cases", "holdout_cases", []),
        ("holdout_values", "holdout_values", [1.0]),
        ("holdout_plaintext", "holdout_plaintext", "secret"),
        ("unseal_key", "unseal_key", "secret"),
        ("nested unseal field", "metadata", {"unseal_instruction": "run openssl"}),
    ]

    def test_poisoned_summary_rejected(self):
        for label, key, value in self.POISONS:
            with self.subTest(label):
                summary = copy.deepcopy(FIXTURE.summary)
                summary[key] = value
                with self.assertRaises(MethodologyError):
                    FIXTURE.derive(calibration_summary=summary)

    def test_poisoned_selected_manifest_rejected(self):
        for label, key, value in self.POISONS[:5]:
            with self.subTest(label):
                selection = copy.deepcopy(FIXTURE.stress_selection)
                selection[key] = value
                with self.assertRaises(MethodologyError):
                    FIXTURE.derive(stress_selection=selection)

    def test_poisoned_pool_rejected(self):
        pool = copy.deepcopy(FIXTURE.pool)
        pool["holdout_notes"] = "h74 leakage"
        with self.assertRaises(MethodologyError):
            FIXTURE.derive(stress_pool=pool)


class TestUnsealPreflightNegativeControls(unittest.TestCase):
    def setUp(self):
        self.manifest = FIXTURE.derive()
        self.manifest_sha = sha_canonical(self.manifest)
        self.selection_sha = sha_canonical(FIXTURE.stress_selection)
        self.custody = load(CUSTODY_RECORD_PATH)
        self.ok = dict(
            threshold_manifest=self.manifest,
            threshold_manifest_sha256=self.manifest_sha,
            expected_committed_threshold_sha256=self.manifest_sha,
            expected_stress_selection_sha256=self.selection_sha,
            holdout_ciphertext_sha256=HOLDOUT_CIPHERTEXT_SHA256,
            recipient_certificate_sha256=EXPECTED_RECIPIENT_CERTIFICATE_SHA256,
            custody_record=self.custody,
        )

    def assert_preflight_fails(self, code=None, **overrides):
        args = dict(self.ok)
        args.update(overrides)
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(**args)
        if code is not None:
            self.assertIn(code, str(ctx.exception))

    def self_consistent(self, manifest):
        """Re-bind the threshold SHAs so ONLY the manifest mutation itself
        can cause the failure (proves the check is not SHA-reliance)."""
        manifest_sha = sha_canonical(manifest)
        return dict(
            self.ok,
            threshold_manifest=manifest,
            threshold_manifest_sha256=manifest_sha,
            expected_committed_threshold_sha256=manifest_sha,
        )

    # --- threshold provenance (retained controls) ---------------------------

    def test_wrong_threshold_file_sha(self):
        self.assert_preflight_fails(expected_committed_threshold_sha256="9" * 64)

    def test_wrong_threshold_schema(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["schema"] = "inferswarm.issue74.threshold-manifest/1"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_tooling_version(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["tooling_or_methodology_version"] = "some-other-version"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_holdout_state(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["holdout_state"] = "CONSUMED"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_calibration_corpus_sha(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["calibration_corpus_sha256"] = "8" * 64
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_stress_pool_sha(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["stress_pool_sha256"] = "7" * 64
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_selection_commitment_sha(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["stress_selection_commitment_sha256"] = "6" * 64
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_ciphertext_sha(self):
        self.assert_preflight_fails(holdout_ciphertext_sha256="4" * 64)

    def test_wrong_recipient_certificate_sha(self):
        self.assert_preflight_fails(recipient_certificate_sha256="3" * 64)

    # --- BLOCKER 1: external selected-eight SHA binding ---------------------

    def test_expected_selected_sha_is_a_mandatory_keyword(self):
        args = dict(self.ok)
        del args["expected_stress_selection_sha256"]
        with self.assertRaises(TypeError):
            validate_unseal_preconditions(**args)

    def test_malformed_expected_selected_sha_fails(self):
        self.assert_preflight_fails(
            code=SELECTED_SHA_MISMATCH, expected_stress_selection_sha256="not-a-sha"
        )

    def test_wrong_expected_selected_sha_fails(self):
        self.assert_preflight_fails(
            code=SELECTED_SHA_MISMATCH, expected_stress_selection_sha256="0" * 64
        )

    def test_manifest_field_selected_sha_alone_is_insufficient(self):
        # Manifest field is syntactically valid but no external binding is
        # possible without the mandatory expected SHA (TypeError above); here
        # a WRONG external expected SHA must fail even though everything else
        # is self-consistent.
        self.assert_preflight_fails(
            code=SELECTED_SHA_MISMATCH, expected_stress_selection_sha256="1" * 64
        )

    def test_self_consistent_selected_sha_mutation_still_fails(self):
        # Mutate the manifest's own selected-eight SHA and re-bind the
        # threshold file SHAs so the manifest is fully self-consistent; the
        # EXTERNAL expected SHA remains the real one, so the preflight must
        # still refuse.
        manifest = copy.deepcopy(self.manifest)
        manifest["stress_selection_sha256"] = "5" * 64
        with self.assertRaises(UnsealPreflightError) as ctx:
            validate_unseal_preconditions(**self.self_consistent(manifest))
        self.assertIn(SELECTED_SHA_MISMATCH, str(ctx.exception))

    def test_matching_external_selected_sha_passes(self):
        record = validate_unseal_preconditions(
            **self.ok, private_key_path=EXTERNAL_KEY_ORCHESTRATOR
        )
        self.assertEqual(
            record["verdict"], "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED"
        )

    # --- BLOCKER 2: real JSON Schema validation inside the preflight --------

    def test_missing_one_limit_fails(self):
        manifest = copy.deepcopy(self.manifest)
        del manifest["limits"][ENVELOPES[0]]
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_sixteenth_extra_envelope_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["limits"]["bogus-family:bogus-metric"] = copy.deepcopy(
            manifest["limits"][ENVELOPES[0]]
        )
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_malformed_limit_hex_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["limits"][ENVELOPES[0]]["limit_hex"] = "2.5"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_rule_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["limits"][ENVELOPES[0]]["rule"] = "max(statistical_max,stress_max)+0.001"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_wrong_comparison_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["limits"][ENVELOPES[0]]["comparison"] = "observed<limit+1"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_missing_manual_editing_field_fails(self):
        manifest = copy.deepcopy(self.manifest)
        del manifest["manual_editing_or_rounding"]
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_extra_unexpected_top_level_property_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["unexpected_extra"] = "x"
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_duplicate_calibration_evidence_sha_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["calibration_evidence_sha256"] = ["e" * 64, "e" * 64]
        with self.assertRaises(UnsealPreflightError):
            validate_unseal_preconditions(**self.self_consistent(manifest))

    def test_committed_threshold_schema_is_bound_to_canonical_path(self):
        from verify_issue79_v2_unseal import THRESHOLD_SCHEMA_PATH as verifier_path
        self.assertEqual(verifier_path, THRESHOLD_SCHEMA_PATH)
        schema = load_threshold_schema()
        self.assertEqual(
            schema["$id"], "https://inferswarm.dev/schema/issue79/v2-threshold-manifest-1.json"
        )
        self.assertEqual(
            schema["properties"]["schema"]["const"],
            "inferswarm.issue79.v2-threshold-manifest/1",
        )

    # --- BLOCKER 3: custody fails closed -------------------------------------

    def assert_custody_fails(self, **overrides):
        self.assert_preflight_fails(code=CUSTODY_NOT_VERIFIED, **overrides)

    def test_custody_record_absent_fails(self):
        self.assert_custody_fails(custody_record=None)

    def test_custody_state_none_without_record_fails(self):
        self.assert_custody_fails(custody_record=None, custody_state=None)

    def test_custody_record_empty_fails(self):
        self.assert_custody_fails(custody_record={})

    def test_custody_unknown_verdict_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["custody_verdict"] = "SOME_NEW_STATE"
        self.assert_custody_fails(custody_record=custody)

    def test_custody_blocked_verdict_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["custody_verdict"] = "HOLDOUT_CUSTODY_BLOCKED"
        self.assert_custody_fails(custody_record=custody)

    def test_custody_blocked_state_flag_fails(self):
        self.assert_custody_fails(custody_state="HOLDOUT_CUSTODY_BLOCKED")

    def test_custody_wrong_schema_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["schema"] = "someone.elses.custody-record/9"
        self.assert_custody_fails(custody_record=custody)

    def test_custody_wrong_holdout_state_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["holdout_state"] = "SEALED_NOT_CONSUMED"
        self.assert_custody_fails(custody_record=custody)

    def test_custody_wrong_ciphertext_sha_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["holdout_ciphertext_sha256"] = "2" * 64
        self.assert_custody_fails(custody_record=custody)

    def test_custody_wrong_certificate_sha_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["recipient_certificate_sha256"] = "a" * 64
        self.assert_custody_fails(custody_record=custody)

    def test_custody_wrong_public_key_der_sha_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["recipient_public_key_der_sha256"] = "b" * 64
        self.assert_custody_fails(custody_record=custody)

    def test_custody_missing_custodians_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["custodians"] = []
        self.assert_custody_fails(custody_record=custody)

    def test_custody_single_unverified_custodian_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["custodians"] = [
            {"custodian_id": "only-one", "public_key_match": False}
        ]
        self.assert_custody_fails(custody_record=custody)

    def test_custody_one_public_key_match_false_fails(self):
        custody = copy.deepcopy(self.custody)
        custody["custodians"][1]["public_key_match"] = False
        self.assert_custody_fails(custody_record=custody)

    def test_real_committed_custody_record_is_found_verified(self):
        self.assertEqual(self.custody["custody_verdict"], "FOUND_VERIFIED")

    # --- BLOCKER 4: private-key externality always proven --------------------

    def assert_key_fails(self, **overrides):
        self.assert_preflight_fails(code=PRIVATE_KEY_NOT_EXTERNAL, **overrides)

    def test_repo_local_absolute_key_fails(self):
        self.assert_key_fails(private_key_path=str(ROOT / "keys/recipient-private-key.pem"))

    def test_repo_local_relative_key_fails(self):
        previous = Path.cwd()
        os.chdir(ROOT)
        try:
            self.assert_key_fails(private_key_path="keys/recipient-private-key.pem")
        finally:
            os.chdir(previous)

    def test_symlink_outside_repo_resolving_inside_repo_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "external-alias.pem"
            os.symlink(ROOT / "scripts/verify_issue79_v2_unseal.py", link)
            self.assert_key_fails(private_key_path=str(link))

    def test_key_inside_repo_with_repo_root_omitted_fails(self):
        # The failure mode being excluded: repo-local key + repo_root omitted
        # must NOT pass — REPO_ROOT defaults deterministically.
        self.assert_key_fails(
            private_key_path=str(ROOT / "k.pem"), repo_root=None
        )

    def test_committed_certificate_material_fails(self):
        self.assert_key_fails(private_key_path=str(V1 / "sealed/recipient-certificate.pem"))

    def test_external_orchestrator_key_path_accepted(self):
        record = validate_unseal_preconditions(
            **self.ok, private_key_path=EXTERNAL_KEY_ORCHESTRATOR
        )
        self.assertEqual(
            record["verdict"], "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED"
        )

    def test_external_inferswarm00_key_path_accepted(self):
        record = validate_unseal_preconditions(
            **self.ok, private_key_path=EXTERNAL_KEY_INFERSWARM00
        )
        self.assertEqual(
            record["verdict"], "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED"
        )


class TestOperatorCliContract(unittest.TestCase):
    """The operator CLI itself must be the fail-closed barrier."""

    def setUp(self):
        self.manifest = FIXTURE.derive()
        self.manifest_sha = sha_canonical(self.manifest)
        self.selection_sha = sha_canonical(FIXTURE.stress_selection)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.manifest_path = self.base / "threshold-manifest.json"
        self.manifest_path.write_bytes(canonical_json_bytes(self.manifest))
        # Byte-identical copies of the committed holdout/certificate material
        # (SHA must match the frozen values; contents are public non-secret).
        self.holdout_path = self.base / "holdout.cms"
        self.holdout_path.write_bytes((V1 / "sealed/holdout.cms").read_bytes())
        self.cert_path = self.base / "recipient-certificate.pem"
        self.cert_path.write_bytes((V1 / "sealed/recipient-certificate.pem").read_bytes())
        self.custody_path = self.base / "holdout-custody-record.json"
        self.custody_path.write_bytes(CUSTODY_RECORD_PATH.read_bytes())
        self.out_path = self.base / "unseal-preflight.json"

    def tearDown(self):
        self.tmp.cleanup()

    def argv(self, **overrides):
        args = dict(
            threshold_manifest=str(self.manifest_path),
            expected_threshold_sha256=self.manifest_sha,
            expected_stress_selection_sha256=self.selection_sha,
            holdout_ciphertext=str(self.holdout_path),
            recipient_certificate=str(self.cert_path),
            custody_record=str(self.custody_path),
            private_key_path=EXTERNAL_KEY_ORCHESTRATOR,
            out=str(self.out_path),
        )
        args.update(overrides)
        argv = []
        for key, value in args.items():
            argv.extend([f"--{key.replace('_', '-')}", str(value)])
        return argv

    def test_cli_requires_every_external_argument(self):
        required = [
            "threshold_manifest", "expected_threshold_sha256",
            "expected_stress_selection_sha256", "holdout_ciphertext",
            "recipient_certificate", "custody_record", "private_key_path", "out",
        ]
        for omitted in required:
            with self.subTest(omitted):
                args = dict(
                    threshold_manifest=str(self.manifest_path),
                    expected_threshold_sha256=self.manifest_sha,
                    expected_stress_selection_sha256=self.selection_sha,
                    holdout_ciphertext=str(self.holdout_path),
                    recipient_certificate=str(self.cert_path),
                    custody_record=str(self.custody_path),
                    private_key_path=EXTERNAL_KEY_ORCHESTRATOR,
                    out=str(self.out_path),
                )
                del args[omitted]
                argv = []
                for key, value in args.items():
                    argv.extend([f"--{key.replace('_', '-')}", str(value)])
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        unseal_main(argv)
                self.assertEqual(ctx.exception.code, 2)

    def test_cli_positive_end_to_end_external_binding(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = unseal_main(self.argv())
        self.assertEqual(code, 0)
        record = json.loads(self.out_path.read_text())
        self.assertEqual(
            record["verdict"], "UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED"
        )
        self.assertFalse(record["decrypt_performed"])
        self.assertFalse(record["openssl_invoked"])
        self.assertEqual(record["stress_selection_sha256"], self.selection_sha)
        self.assertIn("UNSEAL_PRECONDITIONS_PASS_DECRYPT_NOT_PERFORMED", stdout.getvalue())

    def test_cli_rejects_repo_local_private_key(self):
        with self.assertRaises(SystemExit) as ctx:
            unseal_main(self.argv(private_key_path=str(ROOT / "keys/key.pem")))
        self.assertIn("UNSEAL_PRECONDITIONS_FAIL", str(ctx.exception.code))
        self.assertIn(PRIVATE_KEY_NOT_EXTERNAL, str(ctx.exception.code))
        self.assertFalse(self.out_path.exists())

    def test_cli_rejects_wrong_expected_selected_sha(self):
        with self.assertRaises(SystemExit) as ctx:
            unseal_main(self.argv(expected_stress_selection_sha256="0" * 64))
        self.assertIn(SELECTED_SHA_MISMATCH, str(ctx.exception.code))
        self.assertFalse(self.out_path.exists())

    def test_cli_rejects_malformed_threshold_structure(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["unexpected_extra"] = "x"
        path = self.base / "malformed-threshold.json"
        path.write_bytes(canonical_json_bytes(manifest))
        with self.assertRaises(SystemExit) as ctx:
            unseal_main(
                self.argv(
                    threshold_manifest=str(path),
                    expected_threshold_sha256=sha_file(path),
                )
            )
        self.assertIn(THRESHOLD_SCHEMA_INVALID, str(ctx.exception.code))
        self.assertFalse(self.out_path.exists())

    def test_cli_rejects_absent_custody_record_content(self):
        empty = self.base / "empty-custody.json"
        empty.write_text("null")
        with self.assertRaises(SystemExit) as ctx:
            unseal_main(self.argv(custody_record=str(empty)))
        self.assertIn(CUSTODY_NOT_VERIFIED, str(ctx.exception.code))
        self.assertFalse(self.out_path.exists())


class TestToolingPurity(unittest.TestCase):
    FORBIDDEN_MODULES = {"torch", "transformers", "freetoken", "triton"}

    def test_issue79_tools_cannot_import_execution_runtimes(self):
        for name in ("issue79_v2_thresholds.py", "verify_issue79_v2_unseal.py"):
            path = ROOT / "scripts" / name
            tree = ast.parse(path.read_text())
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
            self.assertFalse(imports & self.FORBIDDEN_MODULES, f"{path} imports a forbidden runtime")
            self.assertNotIn("nvidia-smi", path.read_text().lower())
            self.assertNotIn("cuda", path.read_text().lower())
            self.assertNotIn("subprocess", path.read_text())

    def test_v2_tooling_declares_test_only_synthetic_evidence(self):
        text = (ROOT / "tests/test_issue79_v2_threshold_tooling.py").read_text()
        self.assertIn("TEST-ONLY SYNTHETIC EVIDENCE", text)

    def test_no_selected_eight_manifest_committed_to_evidence_directory(self):
        for path in V2.rglob("*.json"):
            data = json.loads(path.read_text())
            if isinstance(data, dict) and data.get("schema") == "inferswarm.issue76.margin-stress-selection/2":
                self.fail(f"real-or-fake selected-eight manifest committed at {path}")


if __name__ == "__main__":
    unittest.main()
