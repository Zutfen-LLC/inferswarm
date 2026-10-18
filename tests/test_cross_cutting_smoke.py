"""Always-run three-test smoke: identity custody, operator data, numeric failure.

Tiny CPU fixtures only. This is cross-cutting smoke, not native qualification.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from issue99_artifact_core import AcquisitionError, self_digest, validate_self_identity
from issue74_methodology import MethodologyError, tensor_metrics
from inferswarm.operator.profiles import canonical, freeze, thaw


class CrossCuttingSmoke(unittest.TestCase):
    def test_artifact_custody_rejects_mutation(self):
        record = {'payload': 'fixture'}
        record['identity'] = self_digest(record, identity_field='identity')
        validate_self_identity(record, identity_field='identity')
        record['payload'] = 'changed'
        with self.assertRaises(AcquisitionError):
            validate_self_identity(record, identity_field='identity')

    def test_operator_data_freezes_and_round_trips(self):
        raw = {'participants': [{'host': 'synthetic', 'bytes': 16}]}
        frozen = freeze(raw)
        raw['participants'][0]['bytes'] = 32
        self.assertEqual(thaw(frozen)['participants'][0]['bytes'], 16)
        self.assertEqual(canonical(frozen), canonical(thaw(frozen)))

    def test_numeric_core_rejects_nonfinite_values(self):
        self.assertEqual(tensor_metrics([1., 2.], [1., 2.])['max-absolute-difference'], 0)
        with self.assertRaises(MethodologyError):
            tensor_metrics([1.], [float('nan')])
