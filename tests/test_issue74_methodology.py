from __future__ import annotations

import hashlib
import ast
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_issue74_corpora import (  # noqa: E402
    HISTORICAL_R6_TOKEN_IDS,
    TOKENIZER_SHA256,
    _raw_candidate,
    generate_public,
)
from issue74_methodology import (  # noqa: E402
    CONTENT_CLASSES,
    CONTRACT_ID,
    ENVELOPES,
    LENGTH_REGIMES,
    MethodologyError,
    canonical_json_bytes,
    conservative_case_family,
    derive_threshold_manifest,
    minimum_sample_size,
    nearest_rank_higher,
    tensor_metrics,
)
from select_issue74_margin_stress import select  # noqa: E402

BASE = ROOT / "docs/qualification/gemma4-12b-it-v1"
MANIFESTS = BASE / "manifests"


def load(name: str) -> dict:
    return json.loads((MANIFESTS / name).read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary_case(case_id: str, default: float = 1.0) -> dict:
    return {
        "case_id": case_id,
        "exact_integrity": "PASS",
        "semantic_output": "PASS",
        "finite": True,
        "evidence_complete": True,
        "envelopes": {name: float(default).hex() for name in ENVELOPES},
    }


class Issue74CorpusTests(unittest.TestCase):
    def test_calibration_has_24_cells_and_24_cases_per_cell(self):
        corpus = load("calibration-corpus.json")
        cells = Counter((row["content_class"], tuple(row["length_regime"])) for row in corpus["cases"])
        self.assertEqual(len(cells), 24)
        self.assertEqual(set(cells.values()), {24})
        self.assertEqual(len(corpus["cases"]), 24 * 24)
        for row in corpus["cases"]:
            low, high = row["length_regime"]
            self.assertLessEqual(low, row["token_count"])
            self.assertLessEqual(row["token_count"], high)

    def test_case_hashes_and_all_corpora_are_disjoint(self):
        calibration = load("calibration-corpus.json")
        stress = load("margin-stress-pool.json")
        holdout = load("sealed-holdout-commitment.json")
        groups = []
        for source in (calibration["cases"], stress["cases"], holdout["cells"]):
            prompt_hashes = {row["prompt_sha256"] for row in source}
            token_hashes = {row["token_ids_sha256"] for row in source}
            self.assertEqual(len(prompt_hashes), len(source))
            self.assertEqual(len(token_hashes), len(source))
            groups.append((prompt_hashes, token_hashes))
        for index, (prompts, tokens) in enumerate(groups):
            for other_prompts, other_tokens in groups[index + 1:]:
                self.assertFalse(prompts & other_prompts)
                self.assertFalse(tokens & other_tokens)
        self.assertNotIn(list(HISTORICAL_R6_TOKEN_IDS), [row["token_ids"] for row in calibration["cases"]])
        self.assertNotIn(list(HISTORICAL_R6_TOKEN_IDS), [row["token_ids"] for row in stress["cases"]])

    def test_frozen_public_case_content_hashes(self):
        for name in ("calibration-corpus.json", "margin-stress-pool.json"):
            artifact = load(name)
            for row in artifact["cases"]:
                identity = {key: row[key] for key in ("content_class", "length_regime", "prompt_text", "token_ids")}
                self.assertEqual(hashlib.sha256(row["prompt_text"].encode()).hexdigest(), row["prompt_sha256"])
                self.assertEqual(hashlib.sha256(canonical_json_bytes(row["token_ids"])).hexdigest(), row["token_ids_sha256"])
                self.assertEqual(hashlib.sha256(canonical_json_bytes(identity)).hexdigest(), row["case_sha256"])

    def test_generation_prng_is_deterministic(self):
        args = ("seed", "namespace", CONTENT_CLASSES[0], "cell", 9, 28, 0)
        self.assertEqual(_raw_candidate(*args), _raw_candidate(*args))

    @unittest.skipUnless(os.environ.get("ISSUE74_TOKENIZER_JSON"), "pinned tokenizer not provided")
    def test_public_artifacts_reproduce_byte_for_byte_with_pinned_tokenizer(self):
        from tokenizers import Tokenizer
        tokenizer_path = Path(os.environ["ISSUE74_TOKENIZER_JSON"])
        self.assertEqual(sha(tokenizer_path), TOKENIZER_SHA256)
        calibration, stress = generate_public(Tokenizer.from_file(str(tokenizer_path)))
        self.assertEqual(canonical_json_bytes(calibration), (MANIFESTS / "calibration-corpus.json").read_bytes())
        self.assertEqual(canonical_json_bytes(stress), (MANIFESTS / "margin-stress-pool.json").read_bytes())

    def test_holdout_is_one_case_per_cell_and_remains_sealed(self):
        commitment = load("sealed-holdout-commitment.json")
        cells = {(row["content_class"], tuple(row["length_regime"])) for row in commitment["cells"]}
        expected = {(name, bounds) for name in CONTENT_CLASSES for bounds in LENGTH_REGIMES}
        self.assertEqual(cells, expected)
        self.assertEqual(commitment["case_count"], 24)
        self.assertEqual(sha(BASE / "sealed/holdout.cms"), commitment["ciphertext_sha256"])
        self.assertFalse(any(path.name.endswith(".plaintext.json") for path in BASE.rglob("*")))


class Issue74ReducerTests(unittest.TestCase):
    def test_sample_size_is_568_and_selected_size_is_576(self):
        self.assertEqual(minimum_sample_size(), 568)
        alpha_i = 0.05 / 15
        self.assertLess(1.0 - 0.99 ** 567, 1.0 - alpha_i)
        self.assertGreaterEqual(1.0 - 0.99 ** 568, 1.0 - alpha_i)
        derivation = load("sample-size-derivation.json")
        self.assertEqual((derivation["minimum_n"], derivation["selected_n"]), (568, 576))

    def test_exactly_15_mandatory_envelopes(self):
        methodology = load("methodology.json")
        self.assertEqual(len(ENVELOPES), 15)
        self.assertEqual(methodology["mandatory_envelopes"], list(ENVELOPES))
        self.assertEqual(len(set(methodology["mandatory_envelopes"])), 15)

    def test_nearest_rank_higher_p99_is_deterministic_and_conservative(self):
        values = [float(value) for value in reversed(range(100))]
        self.assertEqual(nearest_rank_higher(values, 0.99), 98.0)
        self.assertEqual(nearest_rank_higher(list(reversed(values)), 0.99), 98.0)
        self.assertGreaterEqual(nearest_rank_higher([0.0, 1.0], 0.99), 1.0)

    def test_tensor_metrics_use_complete_domain_and_reject_nonfinite(self):
        result = tensor_metrics([0.0, 0.0, 0.0], [3.0, 4.0, 0.0])
        self.assertEqual(result["max-absolute-difference"], 4.0)
        self.assertAlmostEqual(result["rms-difference"], (25.0 / 3.0) ** 0.5)
        self.assertEqual(result["p99-absolute-error"], 4.0)
        with self.assertRaises(MethodologyError):
            tensor_metrics([0.0], [float("nan")])

    def test_case_family_reduction_takes_each_metric_maximum(self):
        result = conservative_case_family([
            {"max-absolute-difference": 3.0, "rms-difference": 1.0, "p99-absolute-error": 2.0},
            {"max-absolute-difference": 2.0, "rms-difference": 4.0, "p99-absolute-error": 1.0},
        ])
        self.assertEqual(result, {"max-absolute-difference": 3.0, "rms-difference": 4.0, "p99-absolute-error": 2.0})


class Issue74ThresholdTests(unittest.TestCase):
    def setUp(self):
        self.methodology = load("methodology.json")
        self.calibration = {
            "schema": "inferswarm.issue74.calibration-summary/1",
            "contract_id": CONTRACT_ID,
            "calibration_corpus_sha256": self.methodology["corpora"]["calibration_manifest_sha256"],
            "stress_selection_sha256": "c" * 64,
            "evidence_sha256": ["a" * 64],
            "statistical_cases": [summary_case(f"c74-test-{index:03d}", 1.0) for index in range(576)],
            "stress_cases": [summary_case(f"p74-test-{index:03d}", 2.0) for index in range(8)],
        }

    def test_threshold_is_maximum_of_statistical_and_stress(self):
        first, second = ENVELOPES[:2]
        self.calibration["statistical_cases"][11]["envelopes"][first] = (3.0).hex()
        self.calibration["stress_cases"][2]["envelopes"][second] = (4.0).hex()
        result = derive_threshold_manifest(self.methodology, self.calibration, program_sha256="b" * 64)
        self.assertEqual(result["limits"][first]["limit_hex"], (3.0).hex())
        self.assertEqual(result["limits"][second]["limit_hex"], (4.0).hex())
        self.assertTrue(all(row["rule"] == "max(statistical_max,stress_max)" for row in result["limits"].values()))

    def test_holdout_cannot_influence_threshold_derivation(self):
        for key, value in (("holdout_cases", []), ("unseal_key", "secret"), ("case_id", "h74-01")):
            poisoned = json.loads(json.dumps(self.calibration))
            poisoned[key] = value
            with self.assertRaisesRegex(MethodologyError, "holdout inputs are forbidden"):
                derive_threshold_manifest(self.methodology, poisoned, program_sha256="b" * 64)

    def test_missing_and_failed_evidence_fail_closed(self):
        missing = json.loads(json.dumps(self.calibration))
        missing["statistical_cases"].pop()
        with self.assertRaises(MethodologyError):
            derive_threshold_manifest(self.methodology, missing, program_sha256="b" * 64)
        failed = json.loads(json.dumps(self.calibration))
        failed["statistical_cases"][0]["exact_integrity"] = "FAIL"
        with self.assertRaises(MethodologyError):
            derive_threshold_manifest(self.methodology, failed, program_sha256="b" * 64)
        nonfinite = json.loads(json.dumps(self.calibration))
        nonfinite["stress_cases"][0]["envelopes"][ENVELOPES[0]] = "nan"
        with self.assertRaises(MethodologyError):
            derive_threshold_manifest(self.methodology, nonfinite, program_sha256="b" * 64)


class Issue74StressSelectionTests(unittest.TestCase):
    def test_selection_is_exact_deterministic_and_reference_only(self):
        pool = load("margin-stress-pool.json")
        pool_hash = hashlib.sha256(canonical_json_bytes(pool)).hexdigest()
        margins = {
            "schema": "inferswarm.issue74.reference-margin-summary/1",
            "contract_id": CONTRACT_ID,
            "stress_pool_sha256": pool_hash,
            "cases": [{"case_id": row["case_id"], "top1_margin_hex": float(index + 1).hex()}
                      for index, row in enumerate(reversed(pool["cases"]))],
        }
        first = select(pool, margins)
        second = select(pool, json.loads(json.dumps(margins)))
        self.assertEqual(first, second)
        self.assertEqual(first["selected_count"], 8)
        self.assertEqual(len(first["selected"]), 8)
        self.assertTrue(all("reference_top1_margin_hex" in row for row in first["selected"]))

    def test_nonpositive_reference_margin_is_rejected(self):
        pool = load("margin-stress-pool.json")
        margins = {
            "schema": "inferswarm.issue74.reference-margin-summary/1",
            "contract_id": CONTRACT_ID,
            "stress_pool_sha256": hashlib.sha256(canonical_json_bytes(pool)).hexdigest(),
            "cases": [{"case_id": row["case_id"], "top1_margin_hex": (1.0).hex()} for row in pool["cases"]],
        }
        margins["cases"][0]["top1_margin_hex"] = (0.0).hex()
        with self.assertRaises(ValueError):
            select(pool, margins)


class Issue74SafetyTests(unittest.TestCase):
    def test_methodology_tools_cannot_initialize_a_model_or_cuda(self):
        forbidden_modules = {"torch", "transformers", "freetoken", "triton"}
        for path in (ROOT / "scripts").glob("*issue74*.py"):
            tree = ast.parse(path.read_text())
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
            self.assertFalse(imports & forbidden_modules, f"{path} imports a forbidden execution runtime")
            self.assertNotIn("nvidia-smi", path.read_text().lower())

    def test_historical_r6_disposition_is_unchanged(self):
        methodology = load("methodology.json")
        self.assertEqual(methodology["historical_r6"], "R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL_UNTOUCHED")
        self.assertEqual(methodology["authorization"], "STOP_FOR_MAINTAINER_REVIEW_BEFORE_PHYSICAL_CALIBRATION")
        qualification = load("qualification-draft.json")
        self.assertEqual(qualification["state"], "NOT_QUALIFIED_METHODOLOGY_ONLY")
        self.assertEqual(qualification["planner_eligibility"], "EXCLUDED_PENDING_APPLICABLE_QUALIFICATION")
        self.assertIs(qualification["physical_execution_authorized"], False)

    def test_methodology_build_audit_records_no_physical_execution(self):
        audit = load("methodology-build-audit.json")
        for field in ("model_weights_read", "gemma_executed", "torch_imported", "cuda_initialized",
                      "gpu_queried", "triton_imported", "calibration_executed", "holdout_unsealed",
                      "historical_r6_evidence_modified", "physical_execution_authorized"):
            self.assertIs(audit[field], False, field)

    def test_sentinel_spans_all_content_and_length_classes(self):
        sentinel = load("sentinel-subset.json")
        self.assertEqual(len(sentinel["cases"]), 12)
        self.assertEqual({row["content_class"] for row in sentinel["cases"]}, set(CONTENT_CLASSES))
        self.assertEqual({tuple(row["length_regime"]) for row in sentinel["cases"]}, set(LENGTH_REGIMES))

    def test_required_schemas_exist_and_are_valid_json(self):
        expected = {"preflight.schema.json", "attempt-evidence.schema.json", "calibration-summary.schema.json", "threshold-manifest.schema.json"}
        found = {path.name for path in (BASE / "schemas").glob("*.json")}
        self.assertEqual(found, expected)
        for name in expected:
            schema = json.loads((BASE / "schemas" / name).read_text())
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_review_manifest_hashes_every_listed_artifact(self):
        entries = (BASE / "MANIFEST.sha256").read_text().splitlines()
        self.assertGreater(len(entries), 20)
        for entry in entries:
            expected, relative = entry.split("  ", 1)
            self.assertEqual(sha(ROOT / relative), expected, relative)


if __name__ == "__main__":
    unittest.main()
