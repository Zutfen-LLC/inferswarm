"""Focused ordinary CI reuse controls; all GitHub calls use the existing fake."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ci_unittest as outcomes
import ordinary_ci_reuse as ordinary
import issue213_gate_orchestration as gate
from tests.test_issue323_verified_ordinary_ci import world_for
from tests.test_issue291_final_validation_reuse import make_request

SHA = 'a' * 40
TREE = 'b' * 40
IDS = ['tests.test_example.Example.test_one', 'tests.test_example.Example.test_two']


def record(ids=IDS, skip=False):
    return {'schema': outcomes.SCHEMA, 'ok': True, 'run_id': '9001', 'attempt': '1',
            'job': 'example', 'checkout_sha': 'c' * 40, 'tree': TREE,
            'runtime': {'python': '3.12'}, 'started_unix': 1., 'ended_unix': 2.,
            'started_ids': list(ids), 'outcomes': [[i, 'skip' if skip else 'success',
                                                  'host resource absent' if skip else None]
                                                 for i in ids]}


class RecordValidation(unittest.TestCase):
    def validate(self, records):
        return ordinary.validate_records(records, expected=IDS,
                                          runtime={'python': '3.12'}, tree=TREE,
                                          run_id=9001, attempt=1)

    def test_real_workflow_population_matches_canonical_discovery(self):
        from collections import Counter
        import run_full_cpu_suite as runner
        expected = [i for ids in ordinary.schedule().values() for i in ids]
        discovered = runner.ids_for_units(runner.discover_units(ROOT, ROOT / 'tests'))
        self.assertTrue(all(i.startswith('tests.test_') for i in expected))
        self.assertTrue(all(i.startswith('test_') for i in discovered))
        self.assertEqual(Counter(map(ordinary.canonical_test_id, expected)),
                         Counter(discovered))

    def test_import_prefix_is_exact_and_does_not_merge_other_namespaces(self):
        for i in IDS:
            self.assertEqual(ordinary.canonical_test_id(i), i.removeprefix('tests.'))
        for bad in (IDS[0].removeprefix('tests.'), 'other.' + IDS[0], 'tests.' + IDS[0],
                    'test_other.Example.test_one.extra', 'Example.test_one'):
            with self.subTest(test_id=bad), self.assertRaises(ValueError):
                ordinary.canonical_test_id(bad)

    def test_normalization_preserves_duplicates_and_exact_skip_identity(self):
        r = record(skip=True)
        self.assertEqual(self.validate([r]), IDS)
        r['started_ids'].append(IDS[0])
        r['outcomes'].append([IDS[0], 'skip', 'absent'])
        with self.assertRaises(ValueError):
            self.validate([r])
        r = record()
        r['started_ids'][0] = IDS[0].removeprefix('tests.')
        r['outcomes'][0][0] = IDS[0].removeprefix('tests.')
        with self.assertRaises(ValueError):
            self.validate([r])
        r = record()
        r['outcomes'][0][0] = 'tests.test_other.Example.test_one'
        with self.assertRaises(ValueError):
            self.validate([r])

    def test_terminal_success_and_explicit_skip(self):
        self.assertEqual(self.validate([record()]), [])
        self.assertEqual(self.validate([record(skip=True)]), IDS)

    def test_missing_duplicate_and_failed_outcomes_rejected(self):
        for change in (lambda r: r['outcomes'].pop(),
                       lambda r: r['outcomes'].append(r['outcomes'][0]),
                       lambda r: r['started_ids'].pop(),
                       lambda r: r['started_ids'].append(IDS[0]),
                       lambda r: r.update(ok=False),
                       lambda r: r['outcomes'][0].__setitem__(1, 'failure'),
                       lambda r: r.update(runtime={'python': '3.13'}),
                       lambda r: r.update(tree='d' * 40),
                       lambda r: r.update(attempt='2')):
            r = record(); change(r)
            with self.subTest(record=r), self.assertRaises(ValueError):
                self.validate([r])

    def test_recorded_subtest_failure_cannot_be_reused(self):
        class Example(unittest.TestCase):
            def runTest(self):
                with self.subTest(value=1):
                    self.fail('deliberate')
        result = unittest.TextTestRunner(stream=io.StringIO(),
                                        resultclass=outcomes.OutcomeResult).run(
                                            unittest.TestSuite([Example()]))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.outcomes, [])

    def test_skip_confirmation_physically_checks_only_the_named_subset(self):
        with patch.dict(os.environ, GITHUB_RUN_ID='9001', GITHUB_RUN_ATTEMPT='1'):
            ordinary.confirm_skips(['tests.test_plan_ci.TestCLI.test_self_check_cli'])

    def test_skip_confirmation_failure_and_timeout_block(self):
        with patch('ordinary_ci_reuse.subprocess.run') as run:
            run.return_value.returncode = 1
            with self.assertRaises(ValueError):
                ordinary.confirm_skips(IDS)
            run.side_effect = subprocess.TimeoutExpired('unittest', 1800)
            with self.assertRaises(subprocess.TimeoutExpired):
                ordinary.confirm_skips(IDS)

    def test_real_cli_writes_outcomes_and_preserves_exit_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, CI_OUTCOMES_DIR=temporary)
            p = subprocess.run([sys.executable, '-m', 'scripts.ci_unittest',
                                'tests.test_plan_ci.TestCLI.test_self_check_cli', '-v'],
                               cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('test_self_check_cli (', p.stderr)
            files = list(Path(temporary).glob('*.json'))
            self.assertEqual(len(files), 1)
            r = json.loads(files[0].read_text())
            self.assertEqual(r['started_ids'], [
                'tests.test_plan_ci.TestCLI.test_self_check_cli'])
            self.assertTrue(r['ok'])
            p = subprocess.run([sys.executable, '-m', 'scripts.ci_unittest',
                                'tests.no_such_module'], cwd=ROOT, env=env,
                               capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)


class Authentication(unittest.TestCase):
    def setUp(self):
        self.api = world_for(SHA)
        self.request = make_request(SHA, count=2)
        for target, value in (
                ('ordinary_ci_reuse.schedule', {'example': IDS}),
                ('ordinary_ci_reuse.outcomes.runtime_identity', {'python': '3.12'}),
                ('ordinary_ci_reuse.outcomes.git_value', TREE),
                ('run_full_cpu_suite.discover_units', []),
                ('run_full_cpu_suite.ids_for_units', [i.removeprefix('tests.') for i in IDS])):
            self.addCleanup(patch.stopall)
            patch(target, return_value=value).start()
        self.records = [record()]
        self.art = {'id': 1, 'name': ordinary.PREFIX + 'example',
                    'expired': False, 'workflow_run': {
                        'id': 9001, 'head_sha': SHA, 'repository_id': 1,
                        'head_repository_id': 1}}
        self.repack()
        self.api.list_artifacts = lambda run_id: {
            'total_count': 1, 'artifacts': [copy.deepcopy(self.art)]}
        self.api.download_artifact = lambda art_id, bound: self.blob

    def repack(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            for n, r in enumerate(self.records):
                archive.writestr(f'{n}.json', json.dumps(r))
        self.blob = buf.getvalue()
        self.art.update(size_in_bytes=len(self.blob),
                        digest='sha256:' + hashlib.sha256(self.blob).hexdigest())

    def lookup(self, pr=7):
        return ordinary.lookup(self.api, request=self.request,
                               current_run_id=10000, pr_number=pr)

    def test_authenticated_same_tree_merge_checkout_is_eligible(self):
        decision = self.lookup()
        self.assertEqual(decision['action'], 'reuse', decision)
        self.assertEqual(decision['source']['tree'], TREE)
        self.assertEqual(decision['source_kind'], ordinary.MODE)

    def test_incompatible_incomplete_or_unassociated_ci_falls_back(self):
        for key, value in (('tree', 'd' * 40), ('runtime', {}),
                           ('started_ids', IDS[:1]), ('job', 'other'),
                           ('attempt', '2')):
            self.records = [record()]; self.records[0][key] = value; self.repack()
            self.assertEqual(self.lookup()['action'], 'run', key)
        self.records = [record()]; self.repack()
        self.assertEqual(self.lookup(pr=None)['action'], 'run')
        self.api.runs[0]['pull_requests'] = []
        self.assertEqual(self.lookup()['action'], 'run')

    def test_digest_expiry_and_api_failure_fall_back(self):
        original = copy.deepcopy(self.art)
        self.art['digest'] = 'sha256:' + '0' * 64
        self.assertEqual(self.lookup()['action'], 'run')
        self.art = dict(original, expired=True)
        self.assertEqual(self.lookup()['action'], 'run')
        self.art = original
        self.api.download_artifact = lambda *a: (_ for _ in ()).throw(TimeoutError())
        self.assertEqual(self.lookup()['action'], 'run')

    def compose(self, decision):
        return ordinary.compose(decision, api=self.api, request=self.request,
                                current_run_id=10000, attempt=1, pr_number=7,
                                dispatch_sha=SHA)

    def test_compose_reauthenticates_and_records_actual_schedule(self):
        decision = self.lookup()
        with patch.object(ordinary, 'confirm_skips') as confirm:
            envelope = self.compose(decision)
        confirm.assert_called_once_with([], ROOT)
        self.assertTrue(gate.validate_final_validation_receipt(envelope, SHA))
        self.assertEqual(envelope['suite_receipt']['suite']['suite_config'],
                         ordinary.suite_configuration())
        self.assertNotEqual(envelope['suite_receipt']['suite']['suite_config'],
                            self.request.suite['suite_config'])
        self.art['expired'] = True
        with self.assertRaises(ValueError):
            self.compose(decision)

    def test_handoff_allows_only_the_verified_alternate_schedule(self):
        import hosted_ci_verification as ci
        envelope = self.compose(self.lookup())
        def handoff():
            return gate.handoff_gate_status(
                self.request, None, None, True, envelope,
                ci_verifier=ci.HostedCiVerifier(self.api, ci.CANONICAL_REPOSITORY,
                                                pr_number=7))
        self.assertTrue(handoff()['handoff_complete'])
        envelope['suite_receipt']['suite']['suite_config']['plan_digest'] = '0' * 64
        with self.assertRaises(gate.GateOrderingError):
            handoff()

    def test_skip_confirmation_required_and_failure_blocks(self):
        self.records = [record(skip=True)]; self.repack()
        decision = self.lookup()
        with patch.object(ordinary, 'confirm_skips', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                self.compose(decision)
        with patch.object(ordinary, 'confirm_skips') as confirm:
            envelope = self.compose(decision)
        confirm.assert_called_once_with(IDS, ROOT)
        envelope['execution']['skips_confirmed'] = False
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_final_validation_receipt(envelope, SHA)

    def test_changed_pointer_attempt_and_run_cannot_compose(self):
        for key, value in (('tree', 'd' * 40), ('run_attempt', 2), ('run_id', 9002)):
            decision = self.lookup()
            decision['source'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compose(decision)


if __name__ == '__main__':
    unittest.main()
