"""Scoped merge gates: tiny Git histories and the existing read-only API fake."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import merge_validation as merge
import plan_ci
import hosted_ci_verification as ci
import issue213_gate_orchestration as gate
from tests.test_issue323_verified_ordinary_ci import world_for
from tests.test_issue291_final_validation_reuse import make_request


class Selection(unittest.TestCase):
    def test_ordinary_and_shared_operator_scope_is_concrete(self):
        for path, expected in (
            ('docs/README.md', ['repo-integrity']),
            ('inferswarm/operator/runtime.py', ['issue-99-103', 'repo-integrity']),
            ('inferswarm/operator/profiles.py', ['issue-99-103', 'repo-integrity']),
            ('tools/issue255_mvp/driver.py', ['issue-99-103', 'repo-integrity']),
        ):
            with self.subTest(path=path):
                plan = plan_ci.plan([path])
                self.assertFalse(plan['full_regression'])
                self.assertEqual(plan['groups'], expected)

    def test_native_dependency_policy_and_unknown_escalate_full(self):
        for path in ('inferswarm/operator/native_observer/full_build.py',
                     'tests/fixtures/issue299/native-observer-overlay.patch',
                     'tools/native-cache/server.cpp', 'tools/moe-overlap/build.py',
                     'scripts/issue264_source_patch.py', 'scripts/issue280_source.py',
                     'requirements-test.txt',
                     'docs/new-family/requirements.txt', 'pyproject.toml',
                     'scripts/merge_validation.py', 'scripts/run_full_cpu_suite.py',
                     'docs/campaign-gate-ordering.md', '.github/workflows/ci.yml',
                     'unclassified/new.py'):
            with self.subTest(path=path):
                plan = plan_ci.plan([path], mode='merge')
                self.assertTrue(plan['full_regression'])
                self.assertEqual(plan['groups'], sorted(plan_ci.GROUP_TEST_MODULES))

    def test_native_ci_selection_and_dependency_escalation_are_distinct(self):
        for path in ('inferswarm/operator/native_observer/full_build.py',
                     'tools/moe-overlap/build.py', 'scripts/issue280_source.py',
                     'docs/investigations/vulkan-same-request-280/fixtures/recording.cpp'):
            with self.subTest(path=path):
                self.assertFalse(plan_ci.plan([path], mode='pr')['full_regression'])
                self.assertTrue(plan_ci.plan([path], mode='merge')['full_regression'])
        for path in ('docs/new-family/requirements.txt', 'requirements-test.txt',
                     'scripts/merge_validation.py', 'unclassified/new.py'):
            for mode in ('pr', 'merge'):
                with self.subTest(path=path, mode=mode):
                    self.assertTrue(plan_ci.plan([path], mode=mode)['full_regression'])

    def test_real_selected_population_exactly_matches_modules_and_smoke(self):
        groups = ['issue-99-103', 'repo-integrity']
        names, ids = merge.selected_population(ROOT, groups)
        expected = sorted(i for group in groups for module in plan_ci.GROUP_TEST_MODULES[group]
                          for i in merge.parity.module_test_ids(module, ROOT))
        self.assertEqual(ids, expected)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len([i for i in ids if '.test_cross_cutting_smoke.' in i]), 3)
        self.assertEqual(set(names), {'Group issue-99-103', 'Group repo-integrity (always-on)'})
        self.assertFalse(any('.test_native_cache.' in i or '.test_issue278_integration.' in i
                             for i in ids))

    def test_weekly_and_manual_full_are_repository_workflows(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        self.assertEqual(triggers['schedule'], [{'cron': '23 4 * * 1'}])
        self.assertIn('workflow_dispatch', triggers)
        full = plan_ci.plan([], mode='full')
        self.assertEqual(full['groups'], sorted(plan_ci.GROUP_TEST_MODULES))


class Handoff(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='merge-scope-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.root / 'README.md').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        path = self.root / 'inferswarm/operator/runtime.py'
        path.parent.mkdir(parents=True)
        path.write_text('# fixture\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'change')
        self.sha = self.git('rev-parse', 'HEAD')
        self.head = make_request(self.sha)
        self.api = world_for(self.sha)
        self.api.pulls[7]['base']['sha'] = self.base
        self.verifier = ci.HostedCiVerifier(self.api, ci.CANONICAL_REPOSITORY, pr_number=7)
        self.ids = ['tests.test_tiny.Tiny.test_one']
        fake_population = patch.object(merge, 'selected_population', return_value=(
            ('Group issue-99-103', 'Group repo-integrity (always-on)'), self.ids))
        fake_population.start()
        self.addCleanup(fake_population.stop)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True).strip()

    def status(self, **kwargs):
        return merge.handoff_status(self.head, root=self.root, ci_verifier=self.verifier,
                                    finalizer_ok=kwargs.pop('finalizer_ok', True), **kwargs)

    def test_scoped_pass_is_not_full_qualification_and_executes_no_tests(self):
        with patch('subprocess.Popen', wraps=subprocess.Popen) as processes:
            result = self.status()
        self.assertTrue(result['handoff_complete'], result)
        self.assertEqual(result['required_test_ids'], self.ids)
        self.assertEqual(result['reused_groups'], ['issue-99-103', 'repo-integrity'])
        self.assertEqual(result['base_sha'], self.base)
        self.assertEqual(result['validation_scope'], 'scoped')
        self.assertFalse(result['full_suite_receipt_valid'])
        self.assertIsNone(result['full_suite_proof'])
        self.assertIn('r8i-qwen-qualification', result['uncovered_groups'])
        self.assertTrue(all(call.args[0][0] == 'git' for call in processes.call_args_list))
        with self.assertRaises(gate.GateOrderingError):
            gate.validate_final_validation_receipt(result, self.sha)

    def test_missing_skipped_or_failed_required_group_cannot_hide_behind_gate(self):
        for mode in ('missing', 'skipped', 'failure'):
            saved = copy.deepcopy(self.api.jobs)
            jobs = self.api.jobs[9001]
            target = next(j for j in jobs if j['name'] == 'Group issue-99-103')
            if mode == 'missing': jobs.remove(target)
            else: target['conclusion'] = mode
            result = self.status()
            self.assertFalse(result['handoff_complete'], result)
            self.assertEqual(result['reused_groups'], [])
            self.api.jobs = saved

    def test_missing_ci_wrong_head_and_finalizer_failure_block(self):
        self.assertFalse(self.status(finalizer_ok=False)['handoff_complete'])
        self.api.runs.clear()
        self.assertFalse(self.status()['handoff_complete'])
        self.api.pulls[7]['head']['sha'] = 'a' * 40
        with self.assertRaises(ValueError): self.status()

    def test_base_drift_and_dirty_checkout_block(self):
        def drift(n, pull):
            if n >= 4: pull['base']['sha'] = 'b' * 40
            return pull
        self.api.get_pull_mutator = drift
        with self.assertRaisesRegex(ValueError, 'base changed'): self.status()
        self.api.get_pull_mutator = None
        (self.root / 'README.md').write_text('dirty')
        with self.assertRaises(gate.GateOrderingError): self.status()

    def test_native_merge_requires_full_proof_even_when_ci_is_targeted(self):
        path = self.root / 'inferswarm/operator/native_control.cpp'
        path.write_text('// native fixture\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'native change')
        self.sha = self.git('rev-parse', 'HEAD')
        self.head = make_request(self.sha)
        self.api = world_for(self.sha)
        self.api.pulls[7]['base']['sha'] = self.base
        self.verifier = ci.HostedCiVerifier(self.api, ci.CANONICAL_REPOSITORY, pr_number=7)
        paths = merge._changed_paths(self.root, self.base, self.sha)
        self.assertFalse(plan_ci.plan(paths, mode='pr')['full_regression'])
        result = self.status()
        self.assertEqual(result['validation_scope'], 'full')
        self.assertTrue(result['full_qualification_required'])
        self.assertFalse(result['handoff_complete'])

    def test_policy_change_requires_existing_full_proof_and_preserves_contract(self):
        path = self.root / 'scripts/plan_ci.py'
        path.parent.mkdir()
        path.write_text('# policy\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'policy')
        self.sha = self.git('rev-parse', 'HEAD')
        self.head = make_request(self.sha)
        self.api = world_for(self.sha)
        self.api.pulls[7]['base']['sha'] = self.base
        self.verifier = ci.HostedCiVerifier(self.api, ci.CANONICAL_REPOSITORY, pr_number=7)
        result = self.status()
        self.assertEqual(result['validation_scope'], 'full')
        self.assertFalse(result['handoff_complete'])
        marker = {'handoff_complete': True}
        with patch.object(gate, 'handoff_gate_status', return_value=marker) as full:
            receipt = {'fixture': 'existing full receipt'}
            self.assertTrue(self.status(final_validation_receipt=receipt)['handoff_complete'])
            self.assertIs(full.call_args.args[4], receipt)

    def test_scoped_cli_uses_same_verifier_without_requiring_a_full_receipt(self):
        output = self.root.parent / (self.root.name + '-handoff.json')
        self.addCleanup(output.unlink, missing_ok=True)
        result = gate.main(['handoff', '--risk-based', '--root', str(self.root),
                            '--repo', ci.CANONICAL_REPOSITORY, '--pr', '7',
                            '--finalizer-ok', '--out', str(output)],
                           environ={'GITHUB_TOKEN': 'offline-fixture'},
                           api_factory=lambda *args: self.api,
                           request_factory=lambda root: self.head)
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.read_text())['validation_scope'], 'scoped')

    def test_direct_script_full_handoff_preserves_request_and_error_identity(self):
        # Exercise __main__, rather than importing gate.main: merge_validation
        # must use the same request/error classes as the executing CLI module.
        for rel in gate.ENV_AUTHORITY_FILES:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture authority\n')
        (self.root / 'tests').mkdir()
        (self.root / 'tests/test_entry_fixture.py').write_text(
            'import unittest\nclass Fixture(unittest.TestCase):\n'
            ' def test_never_executes(self): raise AssertionError("handoff ran tests")\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'full-risk fixture')
        sha = self.git('rev-parse', 'HEAD')
        request = gate.current_final_head_request(self.root)
        receipt = dict(schema=gate.RECEIPT_SCHEMA, **request.to_dict(),
                       result='PASS', count=request.suite['count'],
                       started_unix=1000.0, ended_unix=2000.0)
        with tempfile.TemporaryDirectory(prefix='merge-entry-') as temporary:
            output = Path(temporary) / 'handoff.json'
            proof = Path(temporary) / 'receipt.json'
            harness = '''
import runpy, sys
from pathlib import Path
sys.path[:0] = [sys.argv[1], str(Path(sys.argv[1]) / 'scripts')]
import hosted_ci_verification as ci
from tests.hosted_ci_fakes import authenticated_ci
api = authenticated_ci(sys.argv[2]).api
api.pulls[7]['base']['sha'] = sys.argv[3]
ci.default_api_factory = lambda *args: api
ci.resolve_token = lambda *args, **kwargs: 'offline-fixture'
script = str(Path(sys.argv[1]) / 'scripts/issue213_gate_orchestration.py')
sys.argv = [script] + sys.argv[4:]
runpy.run_path(script, run_name='__main__')
'''
            for mode, expected in (('complete', 0), ('missing', 1), ('malformed', 1)):
                with self.subTest(mode=mode):
                    payload = dict(receipt, schema='invalid') if mode == 'malformed' else receipt
                    proof.write_text(json.dumps(payload))
                    output.unlink(missing_ok=True)
                    arguments = ['handoff', '--risk-based', '--root', str(self.root),
                                 '--repo', ci.CANONICAL_REPOSITORY, '--pr', '7',
                                 '--finalizer-ok', '--out', str(output)]
                    if mode != 'missing':
                        arguments += ['--suite-receipt', str(proof)]
                    process = subprocess.run(
                        [sys.executable, '-B', '-c', harness, str(ROOT), sha,
                         self.base, *arguments], capture_output=True, text=True,
                        timeout=30)
                    self.assertEqual(process.returncode, expected,
                                     process.stdout + process.stderr)
                    self.assertNotIn('Traceback', process.stdout + process.stderr)
                    if mode == 'malformed':
                        self.assertIn('handoff: FAIL', process.stdout)
                        self.assertFalse(output.exists())
                    else:
                        result = json.loads(output.read_text())
                        self.assertEqual(result['validation_scope'], 'full')
                        self.assertEqual(result['handoff_complete'], mode == 'complete')
                        self.assertEqual(result['full_suite_receipt_valid'], mode == 'complete')

    def test_wrong_checked_out_head_and_missing_base_object_fail_closed(self):
        head = self.head
        self.head = make_request('a' * 40)
        with self.assertRaises(ValueError): self.status()
        self.head = head
        self.api.pulls[7]['base']['sha'] = 'c' * 40
        with self.assertRaises(subprocess.CalledProcessError): self.status()

    def test_rename_keeps_removed_native_and_added_prose_paths(self):
        native = self.root / 'native.cpp'
        native.write_text('// fixture\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'native base')
        base = self.git('rev-parse', 'HEAD')
        (self.root / 'docs').mkdir()
        self.git('mv', 'native.cpp', 'docs/story.md')
        self.git('commit', '-qm', 'rename')
        paths = merge._changed_paths(self.root, base, self.git('rev-parse', 'HEAD'))
        self.assertEqual(paths, ['docs/story.md', 'native.cpp'])
        self.assertTrue(plan_ci.plan(paths)['full_regression'])
