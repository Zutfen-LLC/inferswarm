"""Offline #301 authorization: embedded history, no real ledger/source access."""
import base64
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest import mock
import zlib

from inferswarm.operator.native_observer import build as b


class Issue301BudgetAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(b, 'Issue301Authorization'),
                        'explicit issue301 cumulative authorization is absent')
        self.auth = b.Issue301Authorization()
        self.workspace = b.Workspace(b.SCRATCH)
        self.original = json.loads(HISTORICAL_LEDGER)

    def raw(self, ledger):
        return (json.dumps(ledger, indent=2, sort_keys=True) + '\n').encode()

    def continued(self, seconds=100):
        ledger = json.loads(HISTORICAL_LEDGER)
        ledger['elapsed_seconds'] += seconds
        ledger['phases'].append({'root': str(b.SCRATCH / 'synthetic-run'),
            'elapsed_seconds': seconds, 'peak_sampled_rss_bytes': 0,
            'reason': 'completed', 'status': 'finished'})
        return ledger

    def supervisor(self, authorization=True, limits=None):
        return b.Supervisor(b.SCRATCH / 'synthetic-run', limits,
            workspace=self.workspace,
            authorization=self.auth if authorization else None)

    def test_authorization_is_explicit_immutable_and_exact(self):
        record = asdict(self.auth)
        self.assertEqual((record['issue'], record['original_seconds'],
                          record['extra_seconds'], record['ceiling_seconds']),
                         (301, 5400, 1200, 6600))
        self.assertEqual(record['original_phase_count'], 94)
        self.assertEqual(record['start_consumption_seconds'], 5328.017504271702)
        self.assertEqual(record['original_ledger_sha256'],
                         hashlib.sha256(HISTORICAL_LEDGER).hexdigest())
        with self.assertRaises(FrozenInstanceError):
            self.auth.ceiling_seconds = 7000
        with self.assertRaises(TypeError):
            b.Issue301Authorization(ceiling_seconds=7000)

    def test_default_and_limits_cannot_inject_extension(self):
        self.assertEqual(b.Limits().cumulative_seconds, 5400)
        self.assertEqual(self.supervisor(False).cumulative_seconds, 5400)
        with self.assertRaises(ValueError):
            b.Limits(cumulative_seconds=6600)

    def test_exact_historical_ledger_is_accepted(self):
        self.assertEqual(self.auth.validate(self.workspace, HISTORICAL_LEDGER), self.original)

    def test_original_raw_digest_is_required(self):
        with self.assertRaises(b.BuildError):
            self.auth.validate(self.workspace, json.dumps(self.original).encode())

    def test_wrong_workspace_is_rejected(self):
        with self.assertRaises(b.BuildError):
            self.auth.validate(b.Workspace('/synthetic/wrong-campaign'), HISTORICAL_LEDGER)

    def test_replacement_ledger_is_rejected(self):
        with self.assertRaises(b.BuildError):
            self.auth.validate(self.workspace, self.raw({'elapsed_seconds': 0, 'phases': []}))

    def test_truncated_history_is_rejected(self):
        self.original['phases'].pop()
        self.original['elapsed_seconds'] = sum(p['elapsed_seconds'] for p in self.original['phases'])
        with self.assertRaises(b.BuildError):
            self.auth.validate(self.workspace, self.raw(self.original))

    def test_changed_original_phase_is_rejected_after_append(self):
        ledger = self.continued()
        ledger['phases'][0]['reason'] = 'substituted'
        with self.assertRaises(b.BuildError):
            self.auth.validate(self.workspace, self.raw(ledger))

    def test_reordered_original_phases_are_rejected(self):
        ledger = self.continued()
        ledger['phases'][0], ledger['phases'][1] = ledger['phases'][1], ledger['phases'][0]
        with self.assertRaises(b.BuildError):
            self.auth.validate(self.workspace, self.raw(ledger))

    def test_elapsed_sum_mismatch_is_rejected(self):
        ledger = self.continued()
        ledger['elapsed_seconds'] += 1
        with self.assertRaises(b.BuildError):
            self.auth.validate(self.workspace, self.raw(ledger))

    def test_numeric_fields_are_validated(self):
        for field, values in [('elapsed_seconds', [True, -1, '100', float('nan'), float('inf')]),
                              ('peak_sampled_rss_bytes', [True, -1, '0', 0.5])]:
            for value in values:
                with self.subTest(field=field, value=value):
                    ledger = self.continued()
                    ledger['phases'][-1][field] = value
                    with self.assertRaises(b.BuildError):
                        self.auth.validate(self.workspace, self.raw(ledger))
        for value in [True, -1, '5428', float('nan'), float('inf')]:
            ledger = self.continued()
            ledger['elapsed_seconds'] = value
            with self.subTest(total=value), self.assertRaises(b.BuildError):
                self.auth.validate(self.workspace, self.raw(ledger))

    def test_malformed_or_missing_input_is_rejected(self):
        for raw in [None, b'', b'null', b'[]', b'{}', b'{"phases": null}']:
            with self.subTest(raw=raw), self.assertRaises(b.BuildError):
                self.auth.validate(self.workspace, raw)

    def test_continuation_retains_entire_original_prefix(self):
        ledger = self.continued()
        self.assertEqual(self.auth.validate(self.workspace, self.raw(ledger)), ledger)
        self.assertEqual(ledger['phases'][:94], self.original['phases'])

    def test_missing_ledger_is_not_initialized_under_extension(self):
        supervisor = self.supervisor()
        with (mock.patch.object(b, '_read_bounded', side_effect=b.BuildError('missing ledger')),
              mock.patch.object(b, 'dump') as dump):
            with self.assertRaises(b.BuildError):
                supervisor._load_ledger()
        self.assertIsNone(supervisor.ledger)
        self.assertEqual(supervisor.cumulative_seconds, 5400)
        dump.assert_not_called()

    def test_loading_explicit_authorization_applies_exact_ceiling(self):
        supervisor = self.supervisor()
        with (mock.patch.object(b, '_read_bounded', return_value=self.raw(self.continued())),
              mock.patch.object(b, 'dump') as dump):
            supervisor._load_ledger()
        self.assertEqual(supervisor.cumulative_seconds, 6600)
        self.assertEqual(supervisor.limits.cumulative_seconds, 5400)
        self.assertEqual(supervisor.ledger['phases'][:94], self.original['phases'])
        dump.assert_not_called()

    def test_check_enforces_extended_bound_not_default(self):
        supervisor = self.supervisor()
        with mock.patch.object(b, '_read_bounded', return_value=self.raw(self.continued())):
            supervisor._load_ledger()
        supervisor.start = 0
        with (mock.patch.object(b.time, 'monotonic', return_value=1170),
              mock.patch.object(b, 'group_rss', return_value=0),
              mock.patch.object(supervisor, 'check_storage')):
            supervisor.check()  # 6598.0175 total, above unchanged 5400 default
        with mock.patch.object(b.time, 'monotonic', return_value=1172):
            with self.assertRaisesRegex(b.BuildError, 'wall budget exceeded'):
                supervisor.check()

    def test_extended_check_preserves_phase_bound(self):
        supervisor = self.supervisor(limits=b.Limits(phase_seconds=10))
        with mock.patch.object(b, '_read_bounded', return_value=HISTORICAL_LEDGER):
            supervisor._load_ledger()
        supervisor.start = 0
        with mock.patch.object(b.time, 'monotonic', return_value=11):
            with self.assertRaisesRegex(b.BuildError, 'wall budget exceeded'):
                supervisor.check()

    def test_tighter_cumulative_limit_cannot_be_overridden(self):
        with self.assertRaises((ValueError, b.BuildError)):
            self.supervisor(limits=b.Limits(cumulative_seconds=100))

    def admission_mocks(self, raw):
        """Exercise real admission without locks, ledger/output writes or prctl."""
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(Path, 'mkdir'))
        stack.enter_context(mock.patch.object(Path, 'exists', return_value=True))
        stack.enter_context(mock.patch.object(Path, 'read_text', return_value='synthetic meminfo'))
        stack.enter_context(mock.patch.object(b.os, 'open', return_value=99))
        stack.enter_context(mock.patch.object(b.os, 'fdopen', return_value=io.StringIO()))
        stack.enter_context(mock.patch.object(b.fcntl, 'flock'))
        stack.enter_context(mock.patch.object(b.ctypes, 'CDLL',
            return_value=mock.Mock(prctl=mock.Mock(return_value=0))))
        stack.enter_context(mock.patch.object(b.time, 'monotonic', return_value=0))
        stack.enter_context(mock.patch.object(b.shutil, 'disk_usage', return_value=(1, 0, 1)))
        stack.enter_context(mock.patch.object(b.Supervisor, 'check_storage'))
        stack.enter_context(mock.patch.object(b, '_read_bounded', return_value=raw))
        return stack.enter_context(mock.patch.object(b, 'dump'))

    def test_envelope_records_authorization_and_unchanged_limits(self):
        dump = self.admission_mocks(self.raw(self.continued()))
        supervisor = self.supervisor()
        with supervisor:
            envelope = next(call.args[1] for call in dump.call_args_list
                            if call.args[0].name == 'envelope.json')
            self.assertEqual(envelope['authorization'], asdict(self.auth))
            self.assertEqual(envelope['effective_cumulative_seconds'], 6600)
            self.assertEqual(envelope['limits'], asdict(b.Limits()))
        charged = next(call.args[1] for call in dump.call_args_list
                       if call.args[0].name == 'ledger.json')
        self.assertEqual(charged['phases'][:94], self.original['phases'])
        self.assertEqual(len(charged['phases']), 96)

    def test_admission_at_exact_approved_ceiling_is_refused_without_charge(self):
        ledger = self.continued(self.auth.ceiling_seconds - self.auth.start_consumption_seconds)
        self.assertEqual(ledger['elapsed_seconds'], 6600)
        dump = self.admission_mocks(self.raw(ledger))
        with self.assertRaisesRegex(b.BuildError, 'cumulative wall budget exhausted'):
            self.supervisor().__enter__()
        dump.assert_not_called()

    def test_default_admission_has_no_6600_authority(self):
        dump = self.admission_mocks(self.raw(self.continued()))
        with self.assertRaisesRegex(b.BuildError, 'cumulative wall budget exhausted'):
            self.supervisor(False).__enter__()
        dump.assert_not_called()

    def test_charge_preserves_history_and_uses_existing_append_accounting(self):
        supervisor = self.supervisor()
        with mock.patch.object(b, '_read_bounded', return_value=HISTORICAL_LEDGER):
            supervisor._load_ledger()
        supervisor.start = 0
        with (mock.patch.object(b.time, 'monotonic', return_value=1),
              mock.patch.object(b, 'dump') as dump):
            supervisor._charge('synthetic phase', 'finished')
        self.assertEqual(supervisor.ledger['phases'][:94], self.original['phases'])
        self.assertEqual(len(supervisor.ledger['phases']), 95)
        self.auth.validate(self.workspace, self.raw(supervisor.ledger))
        dump.assert_called_once_with(self.workspace.ledger, supervisor.ledger)

    def test_failed_reload_drops_stale_ledger_authority(self):
        supervisor = self.supervisor()
        with mock.patch.object(b, '_read_bounded', return_value=HISTORICAL_LEDGER):
            supervisor._load_ledger()
        with mock.patch.object(b, '_read_bounded', return_value=b'{}'):
            with self.assertRaises(b.BuildError):
                supervisor._load_ledger()
        self.assertIsNone(supervisor.ledger)
        self.assertEqual(supervisor.cumulative_seconds, 5400)

    def test_check_at_exact_approved_ceiling_then_above(self):
        supervisor = self.supervisor()
        with mock.patch.object(b, '_read_bounded', return_value=HISTORICAL_LEDGER):
            supervisor._load_ledger()
        supervisor.start = 0
        remaining = 6600 - self.original['elapsed_seconds']
        with (mock.patch.object(b.time, 'monotonic', return_value=remaining),
              mock.patch.object(b, 'group_rss', return_value=0),
              mock.patch.object(supervisor, 'check_storage')):
            supervisor.check()
        with mock.patch.object(b.time, 'monotonic', return_value=remaining + .001):
            with self.assertRaises(b.BuildError):
                supervisor.check()

    def test_arbitrary_authorization_object_is_rejected(self):
        with self.assertRaises((ValueError, b.BuildError)):
            b.Supervisor(b.SCRATCH / 'synthetic-run', authorization=object())


# Frozen original 94-phase bytes (zlib/base64), SHA256
# ca237e383609bef6c62414ef7c132e2d5716eb13a016e84960e67b0a326a5c04.
# Compression only keeps this source fixture readable; no filesystem access.
HISTORICAL_LEDGER = zlib.decompress(base64.b64decode(
    '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'
))

if __name__ == '__main__':
    unittest.main()
