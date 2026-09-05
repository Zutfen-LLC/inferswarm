import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
import sys
sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import MethodologyError
from issue95_v4_contract import comparator_tier_contract, derive_separate_bands, predictive_design


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

    def test_cpu_static_sources_do_not_import_runtime_stack(self):
        forbidden = {'torch', 'transformers', 'triton', 'cuda', 'subprocess'}
        for name in ('issue95_v4_methodology.py', 'issue95_v4_contract.py', 'issue95_v4_thresholds.py', 'verify_issue95_v4_unseal.py'):
            tree = ast.parse((SCRIPTS / name).read_text())
            names = {node.names[0].name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)}
            names |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            self.assertFalse(names & forbidden, (name, names & forbidden))


if __name__ == '__main__':
    unittest.main()
