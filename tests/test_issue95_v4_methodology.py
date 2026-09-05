import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
import sys
sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import MethodologyError
from issue95_v4_contract import comparator_tier_contract, derive_separate_bands, predictive_design
from issue95_v4_methodology import derive_prediction_aligned_design


class Issue95V4MethodologyTests(unittest.TestCase):
    def test_prediction_theorem_is_derived_from_balanced_design(self):
        design = predictive_design()
        self.assertEqual((design['cases_per_cell'], design['statistical_cases']), (79, 1896))
        self.assertEqual(design['per_core_family_strict_exceedance_bound'], '1/80')
        self.assertEqual(design['familywise_bonferroni_bound'], '4/80')
        self.assertEqual(design['stress_cases_contribute_predictive_sample_size'], 0)
        self.assertGreaterEqual(design['zero_exceedance_probability_at_least'], 0.95)

    def test_accepted_classification_binds_exactly_four_core_and_twelve_telemetry(self):
        contract = comparator_tier_contract()
        self.assertEqual(len(contract['core_numerical_pairs']), 3)
        self.assertEqual(contract['semantic_core']['identity'], 'decision_local_E_D')
        self.assertEqual(len(contract['mandatory_telemetry_pairs']), 12)
        self.assertEqual(contract['classification_terminal_disposition'], 'NUMERICAL_CORE_TWO_TIER_DOCTRINE_ACCEPTED')

    def test_tier_drift_is_rejected(self):
        source = json.loads((ROOT / 'docs/qualification/post-v3-numerical-core-doctrine/first-contract-classification.json').read_text())
        source['families'][0]['tier'] = 'ACCEPTANCE_BEARING'
        with self.assertRaises(MethodologyError):
            comparator_tier_contract(source)

    def test_core_limits_and_telemetry_bands_stay_separate(self):
        contract = comparator_tier_contract()
        keys = [f"{x['family']}:{x['metric']}" for x in contract['core_numerical_pairs'] + contract['mandatory_telemetry_pairs']] + ['decision_local_E_D']
        result = derive_separate_bands({k: 1.0 for k in keys}, {k: 2.0 for k in keys}, contract)
        self.assertEqual(len(result['core_limits']), 4)
        self.assertEqual(len(result['telemetry_reference_bands']), 12)
        self.assertEqual(result['telemetry_exceedance_verdict'], 'TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE')

    def test_missing_or_promoted_telemetry_is_rejected(self):
        contract = comparator_tier_contract()
        keys = [f"{x['family']}:{x['metric']}" for x in contract['core_numerical_pairs'] + contract['mandatory_telemetry_pairs']] + ['decision_local_E_D']
        with self.assertRaises(MethodologyError):
            derive_separate_bands({k: 1.0 for k in keys[:-1]}, {k: 1.0 for k in keys[:-1]}, contract)

    def test_prediction_derivation_rejects_nearby_and_family_drift(self):
        frozen = derive_prediction_aligned_design()
        self.assertEqual((frozen['cases_per_cell'], frozen['statistical_cases']), (79, 1896))
        self.assertGreater(4 / (78 + 1), 0.05)
        self.assertEqual(derive_prediction_aligned_design(family_count=4)['cases_per_cell'], 79)
        self.assertNotEqual(derive_prediction_aligned_design(family_count=5)['cases_per_cell'], 79)
        self.assertEqual(frozen['stress_cases_contribute_predictive_sample_size'], 0)

    def test_split_schema_identity_exact_and_regenerates(self):
        from build_issue95_schemas import build
        schemas = build()
        schema_dir = ROOT / 'docs/qualification/gemma4-12b-it-v4/schemas'
        self.assertNotIn('threshold-manifest.schema.json', schemas)
        for name, doc in schemas.items():
            self.assertEqual((schema_dir / name).read_bytes(), __import__('issue74_methodology').canonical_json_bytes(doc))
        core = schemas['core-threshold-manifest.schema.json']['properties']['limits']
        self.assertEqual(set(core['required']), {'fp32-consumer-logits:max-absolute-difference', 'fp32-consumer-logits:rms-difference', 'fp32-consumer-logits:p99-absolute-error', 'decision_local_E_D'})
        telemetry = schemas['telemetry-reference-bands.schema.json']['properties']['bands']
        self.assertEqual(len(telemetry['required']), 12)
        self.assertFalse(set(core['required']) & set(telemetry['required']))
        for doc in (schemas['core-threshold-manifest.schema.json'], schemas['telemetry-reference-bands.schema.json']):
            self.assertIn('holdout_custody_record_sha256', doc['properties']['provenance']['required'])

    def test_v4_has_no_stale_population_coverage_contract(self):
        v4 = ROOT / 'docs/qualification/gemma4-12b-it-v4'
        sources = [(SCRIPTS / 'issue95_v4_methodology.py').read_text(), (SCRIPTS / 'build_issue95_schemas.py').read_text()]
        sources.extend(path.read_text() for path in v4.rglob('*') if path.is_file() and path.suffix in {'.json', '.md'})
        text = '\n'.join(sources).lower()
        for forbidden in ('population_content', 'minimum_sample_size_v4', 'statistical_design_v4', '99%-coverage', 'maximum-order-statistic tolerance', '16-family'):
            self.assertNotIn(forbidden, text)

    def test_unseal_rejects_substituted_custody_bytes_before_key_handling(self):
        from issue74_methodology import sha256_file
        from verify_issue95_v4_unseal import validate_unseal_preconditions
        custody = ROOT / 'docs/qualification/gemma4-12b-it-v4/manifests/holdout-custody-record.json'
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            threshold = temp / 'core.json'
            threshold.write_text(json.dumps({'schema': 'inferswarm.issue95.v4-core-threshold-manifest/1', 'holdout_state': 'SEALED_NOT_CONSUMED', 'provenance': {'holdout_custody_record_sha256': sha256_file(custody)}}))
            substitute = temp / 'custody.json'
            substitute.write_text(custody.read_text() + ' ')
            with self.assertRaisesRegex(MethodologyError, 'HOLDOUT_CUSTODY_RECORD_SHA_MISMATCH'):
                validate_unseal_preconditions(core_threshold_path=threshold, expected_core_threshold_sha256=sha256_file(threshold), ciphertext=ROOT / 'docs/qualification/gemma4-12b-it-v4/sealed/holdout.cms', certificate=ROOT / 'docs/qualification/gemma4-12b-it-v4/sealed/recipient-certificate.pem', custody_record_path=substitute, expected_custody_record_sha256=sha256_file(custody), private_key_path=Path('/nonexistent'))

    def test_unseal_negative_control_matrix_stops_before_decrypt(self):
        from issue74_methodology import sha256_file
        from verify_issue95_v4_unseal import validate_unseal_preconditions
        custody = ROOT / 'docs/qualification/gemma4-12b-it-v4/manifests/holdout-custody-record.json'
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            threshold = temp / 'core.json'
            threshold.write_text(json.dumps({'schema': 'inferswarm.issue95.v4-core-threshold-manifest/1', 'holdout_state': 'SEALED_NOT_CONSUMED', 'provenance': {'holdout_custody_record_sha256': sha256_file(custody)}}))
            kwargs = dict(core_threshold_path=threshold, expected_core_threshold_sha256=sha256_file(threshold), ciphertext=ROOT / 'docs/qualification/gemma4-12b-it-v4/sealed/holdout.cms', certificate=ROOT / 'docs/qualification/gemma4-12b-it-v4/sealed/recipient-certificate.pem', custody_record_path=custody, expected_custody_record_sha256=sha256_file(custody))
            with self.assertRaisesRegex(MethodologyError, 'PRIVATE_KEY_PATH_NOT_EXTERNAL_REGULAR_READABLE_FILE'):
                validate_unseal_preconditions(**kwargs, private_key_path=temp / 'missing.pem')
            wrong = temp / 'wrong.bin'; wrong.write_bytes(b'wrong')
            bad_material = kwargs | {'certificate': wrong}
            with self.assertRaisesRegex(MethodologyError, 'HOLDOUT_MATERIAL_MISMATCH'):
                validate_unseal_preconditions(**bad_material, private_key_path=temp / 'missing.pem')
            repo_key = ROOT / '.issue95-test-private-key'; repo_key.write_text('not a key')
            try:
                with self.assertRaisesRegex(MethodologyError, 'PRIVATE_KEY_PATH_NOT_EXTERNAL_TO_REPO'):
                    validate_unseal_preconditions(**kwargs, private_key_path=repo_key)
            finally:
                repo_key.unlink()

    def test_cpu_static_sources_do_not_import_runtime_stack(self):
        forbidden = {'torch', 'transformers', 'triton', 'cuda'}
        for name in ('issue95_v4_methodology.py', 'issue95_v4_contract.py', 'issue95_v4_thresholds.py', 'verify_issue95_v4_unseal.py'):
            tree = ast.parse((SCRIPTS / name).read_text())
            names = {node.names[0].name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
            names |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            self.assertFalse(names & forbidden, (name, names & forbidden))


if __name__ == '__main__':
    unittest.main()
