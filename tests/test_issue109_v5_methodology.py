import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
import sys
sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import MethodologyError, canonical_json_bytes
from issue109_v5_contract import comparator_tier_contract, derive_separate_bands, predictive_design
import issue109_v5_methodology as v5
from issue109_v5_methodology import (
    component_stream,
    derive_mixture_prediction_design,
    mixture_components,
    mixture_population_declaration,
    physical_subject_contract,
    target_length_stream,
)


class Issue109V5MethodologyTests(unittest.TestCase):
    def test_mixture_prediction_theorem_is_derived_from_declared_design(self):
        design = predictive_design()
        self.assertEqual((design['calibration_cases'], design['holdout_cases']), (1416, 24))
        self.assertEqual(design['mixture_components'], 24)
        self.assertEqual(design['assumption_profile'], 'MIXTURE_POPULATION_EXCHANGEABILITY')
        self.assertEqual(design['construction'], 'POOLED_ORDER_STATISTIC_PREDICTION')
        self.assertEqual(design['qualification_claim'], 'ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE')
        self.assertEqual(design['per_core_family_strict_exceedance_bound'], '24/1440')
        self.assertEqual(design['familywise_bonferroni_bound'], '72/1440')
        self.assertEqual(design['stress_cases_contribute_predictive_sample_size'], 0)
        self.assertGreaterEqual(design['zero_exceedance_probability_at_least'], 0.95)

    def test_mixture_design_rejects_a_budget_violating_family_count(self):
        with self.assertRaises(MethodologyError):
            derive_mixture_prediction_design(family_count=4)

    def test_mixture_design_rejects_invalid_inputs(self):
        for kwargs in (dict(calibration_cases=0), dict(holdout_cases=0),
                       dict(mixture_component_count=0), dict(family_count=0)):
            with self.assertRaises(MethodologyError):
                derive_mixture_prediction_design(**kwargs)

    def test_mixture_components_cover_every_content_class_and_length_regime(self):
        from issue74_methodology import CONTENT_CLASSES, LENGTH_REGIMES
        components = mixture_components()
        self.assertEqual(len(components), 24)
        self.assertEqual(len(set(components)), 24)
        self.assertEqual({c for c, _ in components}, set(CONTENT_CLASSES))
        self.assertEqual({r for _, r in components}, set(range(len(LENGTH_REGIMES))))

    def test_component_stream_is_deterministic_and_iid_seeded(self):
        first = list(component_stream('seed-a', 'calibration', 50))
        second = list(component_stream('seed-a', 'calibration', 50))
        self.assertEqual(first, second)
        different_seed = list(component_stream('seed-b', 'calibration', 50))
        self.assertNotEqual(first, different_seed)
        different_namespace = list(component_stream('seed-a', 'v5-sealed-holdout', 50))
        self.assertNotEqual(first, different_namespace)
        # Not every draw need be distinct (small-support cells legitimately
        # repeat under true IID sampling), but the draw *positions* must be.
        self.assertEqual([index for index, _ in first], list(range(50)))

    def test_component_stream_rejects_negative_count(self):
        with self.assertRaises(MethodologyError):
            list(component_stream('seed', 'calibration', -1))

    def test_target_lengths_are_case_local_uniform_draws(self):
        first = list(target_length_stream('seed-a', 'calibration', 2, 50))
        self.assertEqual(first, list(target_length_stream('seed-a', 'calibration', 2, 50)))
        self.assertNotEqual(first, list(target_length_stream('seed-b', 'calibration', 2, 50)))
        self.assertTrue(all(36 <= value <= 40 for value in first))

    def test_mixture_population_declaration_is_frozen_and_shared(self):
        declaration = mixture_population_declaration()
        self.assertEqual(declaration['schema'], 'inferswarm.issue109.v5-mixture-population/1')
        self.assertEqual(declaration['component_count'], 24)
        self.assertTrue(declaration['draws_are_iid'])
        self.assertTrue(declaration['calibration_and_holdout_share_generator'])
        self.assertEqual(len(declaration['components']), 24)
        # Deterministic: rebuilding produces byte-identical output.
        self.assertEqual(canonical_json_bytes(declaration), canonical_json_bytes(mixture_population_declaration()))

    def test_physical_subject_contract_preserves_v4_geometry_and_semantic_order(self):
        subject = physical_subject_contract()
        self.assertEqual(subject["checkpoint_sha256"], "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d")
        self.assertEqual(subject["decision_count"], 8)
        self.assertIn("DECISION_DOMAIN_ESCAPE", subject["reason_codes"])

    def test_accepted_classification_binds_exactly_three_core_and_thirteen_telemetry(self):
        contract = comparator_tier_contract()
        self.assertEqual(len(contract['core_numerical_pairs']), 2)
        self.assertEqual(contract['semantic_core']['identity'], 'decision_local_E_D')
        self.assertEqual(len(contract['mandatory_telemetry_pairs']), 13)
        self.assertEqual(contract['classification_terminal_disposition'], 'POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED')
        core_pairs = {(p['family'], p['metric']) for p in contract['core_numerical_pairs']}
        self.assertEqual(core_pairs, {
            ('fp32-consumer-logits', 'max-absolute-difference'),
            ('fp32-consumer-logits', 'rms-difference'),
        })
        telemetry_pairs = {(p['family'], p['metric']) for p in contract['mandatory_telemetry_pairs']}
        self.assertIn(('fp32-consumer-logits', 'p99-absolute-error'), telemetry_pairs)
        reducers = contract["consumer_logit_reducer_contract"]
        self.assertEqual(reducers["capture_position_rule"], "all 8 canonical-prefix decisions")
        self.assertEqual(reducers["vocabulary_scope"], "full vocabulary")

    def test_v3_tier_drift_is_rejected(self):
        source = json.loads((ROOT / 'docs/qualification/post-v3-numerical-core-doctrine/first-contract-classification.json').read_text())
        source['families'][0]['tier'] = 'ACCEPTANCE_BEARING'
        with self.assertRaises(MethodologyError):
            comparator_tier_contract(source)

    def test_v4_metric_classification_drift_is_rejected(self):
        source = json.loads((ROOT / 'docs/qualification/post-v4-statistical-metric-doctrine/metric-core-classification.json').read_text())
        for metric in source['metrics']:
            if metric['identity'] == 'fp32-consumer-logits:p99-absolute-error':
                metric['tier'] = 'ACCEPTANCE_BEARING'
        with self.assertRaises(MethodologyError):
            comparator_tier_contract(v4_metric_classification=source)

    def test_core_limits_and_telemetry_bands_stay_separate(self):
        contract = comparator_tier_contract()
        keys = [f"{x['family']}:{x['metric']}" for x in contract['core_numerical_pairs'] + contract['mandatory_telemetry_pairs']] + ['decision_local_E_D']
        result = derive_separate_bands({k: 1.0 for k in keys}, {k: 2.0 for k in keys}, contract)
        self.assertEqual(len(result['core_limits']), 3)
        self.assertEqual(len(result['telemetry_reference_bands']), 13)
        self.assertEqual(result['telemetry_exceedance_verdict'], 'TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE')

    def test_missing_or_promoted_telemetry_is_rejected(self):
        contract = comparator_tier_contract()
        keys = [f"{x['family']}:{x['metric']}" for x in contract['core_numerical_pairs'] + contract['mandatory_telemetry_pairs']] + ['decision_local_E_D']
        with self.assertRaises(MethodologyError):
            derive_separate_bands({k: 1.0 for k in keys[:-1]}, {k: 1.0 for k in keys[:-1]}, contract)

    def test_split_schema_identity_exact_and_regenerates(self):
        from build_issue109_schemas import build
        schemas = build()
        schema_dir = ROOT / 'docs/qualification/gemma4-12b-it-v5/schemas'
        for name, doc in schemas.items():
            self.assertEqual((schema_dir / name).read_bytes(), canonical_json_bytes(doc))
        core = schemas['core-threshold-manifest.schema.json']['properties']['limits']
        self.assertEqual(set(core['required']), {
            'fp32-consumer-logits:max-absolute-difference',
            'fp32-consumer-logits:rms-difference', 'decision_local_E_D',
        })
        telemetry = schemas['telemetry-reference-bands.schema.json']['properties']['bands']
        self.assertEqual(len(telemetry['required']), 13)
        self.assertFalse(set(core['required']) & set(telemetry['required']))
        for doc in (schemas['core-threshold-manifest.schema.json'], schemas['telemetry-reference-bands.schema.json']):
            self.assertIn('holdout_custody_record_sha256', doc['properties']['provenance']['required'])

    def test_committed_corpora_are_disjoint_and_unique(self):
        calibration = json.loads((ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json').read_text())
        stress = json.loads((ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests/stress-pool.json').read_text())
        self.assertEqual(len(calibration['cases']), 1416)
        self.assertEqual(len({c['case_id'] for c in calibration['cases']}), 1416)
        self.assertEqual(len({c['prompt_sha256'] for c in calibration['cases']}), 1416)
        self.assertEqual(len(stress['cases']), 48)
        self.assertEqual(len({c['case_id'] for c in stress['cases']}), 48)

    def test_committed_disjointness_proof_has_no_overlap(self):
        proof = json.loads((ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests/disjointness-proof.json').read_text())
        self.assertEqual(proof['verdict'], 'MECHANICALLY_DISJOINT')
        for row in proof['comparisons']:
            self.assertEqual(row['prompt_sha256_overlap'], 0)
            self.assertEqual(row['token_ids_sha256_overlap'], 0)

    def test_custody_record_is_honest_about_incomplete_custody(self):
        from commit_issue109_holdout import custody_is_satisfied
        custody = json.loads((ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests/holdout-custody-record.json').read_text())
        self.assertEqual(len(custody['custodians']), 1)
        self.assertEqual(custody['holdout_state'], 'SEALED_CUSTODY_INCOMPLETE')
        self.assertFalse(custody['unseal_authorized'])
        self.assertFalse(custody_is_satisfied(custody))

    def test_custody_helper_requires_two_distinct_verified_custodians(self):
        from commit_issue109_holdout import build_custody_record, custody_is_satisfied
        commitment = {'ciphertext_sha256': 'a' * 64, 'recipient_certificate_sha256': 'b' * 64}
        one = build_custody_record(commitment, [
            {'private_key_sha256': 'c' * 64, 'public_key_match': True, 'verified_date': '2026-01-01'},
        ])
        self.assertEqual(one['holdout_state'], 'SEALED_CUSTODY_INCOMPLETE')
        self.assertIn('outstanding_action', one)
        self.assertFalse(custody_is_satisfied(one))
        two = build_custody_record(commitment, [
            {'custodian_id': 'a', 'private_key_sha256': 'c' * 64, 'public_key_match': True, 'verified_date': '2026-01-01'},
            {'custodian_id': 'b', 'private_key_sha256': 'c' * 64, 'public_key_match': True, 'verified_date': '2026-01-01'},
        ])
        self.assertEqual(two['holdout_state'], 'SEALED_NOT_CONSUMED')
        self.assertNotIn('outstanding_action', two)
        self.assertTrue(custody_is_satisfied(two))

    def test_cpu_static_sources_do_not_import_runtime_stack(self):
        forbidden = {'torch', 'transformers', 'triton', 'cuda'}
        for name in ('issue109_v5_methodology.py', 'issue109_v5_contract.py',
                     'issue109_v5_thresholds.py', 'verify_issue109_v5_unseal.py',
                     'issue109_v5_methodology_freeze.py'):
            tree = ast.parse((SCRIPTS / name).read_text())
            names = {node.names[0].name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
            names |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            self.assertFalse(names & forbidden, (name, names & forbidden))

    def test_v5_reexports_the_unchanged_v4_semantic_gate(self):
        import issue95_v4_methodology as v4
        self.assertIs(v5.decision_domain, v4.decision_domain)
        self.assertIs(v5.frozen_argmax, v4.frozen_argmax)
        self.assertIs(v5.evaluate_decision, v4.evaluate_decision)
        self.assertEqual(v5.decision_domain_construction_identity(), 'reference-top-1024-with-cutoff-ties/1')
        self.assertEqual(v5.argmax_tie_break_identity(), 'ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima')
        self.assertEqual(v5.DECISION_LOCAL_BOUND_EXCEEDED, 'DECISION_LOCAL_BOUND_EXCEEDED')
        self.assertEqual(v5.DECISION_DOMAIN_ESCAPE, 'DECISION_DOMAIN_ESCAPE')
        self.assertEqual(v5.SEMANTIC_PASS, 'SEMANTIC_PASS')

    def test_unseal_rejects_substituted_custody_bytes_before_key_handling(self):
        from issue74_methodology import sha256_file
        from verify_issue109_v5_unseal import validate_unseal_preconditions
        custody = ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests/holdout-custody-record.json'
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            threshold = temp / 'core.json'
            threshold.write_text(json.dumps({'schema': 'inferswarm.issue109.v5-core-threshold-manifest/1', 'holdout_state': 'SEALED_NOT_CONSUMED', 'provenance': {'holdout_custody_record_sha256': sha256_file(custody)}}))
            substitute = temp / 'custody.json'
            substitute.write_text(custody.read_text() + ' ')
            with self.assertRaisesRegex(MethodologyError, 'HOLDOUT_CUSTODY_RECORD_SHA_MISMATCH'):
                validate_unseal_preconditions(core_threshold_path=threshold, expected_core_threshold_sha256=sha256_file(threshold), ciphertext=ROOT / 'docs/qualification/gemma4-12b-it-v5/sealed/holdout.cms', certificate=ROOT / 'docs/qualification/gemma4-12b-it-v5/sealed/recipient-certificate.pem', custody_record_path=substitute, expected_custody_record_sha256=sha256_file(custody), private_key_path=Path('/nonexistent'))

    def test_unseal_refuses_the_currently_incomplete_custody_record(self):
        """The real committed v5 custody record is intentionally incomplete
        (one custodian, holdout_state SEALED_CUSTODY_INCOMPLETE): the
        preflight must fail closed against it exactly as it stands today."""
        from issue74_methodology import sha256_file
        from verify_issue109_v5_unseal import validate_unseal_preconditions
        custody = ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests/holdout-custody-record.json'
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            threshold = temp / 'core.json'
            threshold.write_text(json.dumps({'schema': 'inferswarm.issue109.v5-core-threshold-manifest/1', 'holdout_state': 'SEALED_NOT_CONSUMED', 'provenance': {'holdout_custody_record_sha256': sha256_file(custody)}}))
            with self.assertRaisesRegex(MethodologyError, 'HOLDOUT_CUSTODY_NOT_VERIFIED'):
                validate_unseal_preconditions(
                    core_threshold_path=threshold, expected_core_threshold_sha256=sha256_file(threshold),
                    ciphertext=ROOT / 'docs/qualification/gemma4-12b-it-v5/sealed/holdout.cms',
                    certificate=ROOT / 'docs/qualification/gemma4-12b-it-v5/sealed/recipient-certificate.pem',
                    custody_record_path=custody, expected_custody_record_sha256=sha256_file(custody),
                    private_key_path=Path('/nonexistent'),
                )


if __name__ == '__main__':
    unittest.main()
