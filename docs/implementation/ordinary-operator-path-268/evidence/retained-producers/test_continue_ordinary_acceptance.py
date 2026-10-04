"""CPU-only contract for the bounded external #268 continuation."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
TARGET = Path(os.environ.get('CONTINUATION_TEST_WRAPPER', ROOT / 'continue-ordinary-acceptance.py'))
SPEC = importlib.util.spec_from_file_location('continuation', TARGET)
continuation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(continuation)
PHYSICAL = ROOT / 'physical-478eb5ef'
if TARGET != ROOT / 'continue-ordinary-acceptance.py':
    # The archived wrapper has identical dependencies in the external fixture root.
    continuation.ROOT = ROOT
    continuation.PHYSICAL = PHYSICAL
    continuation.CONFIG = ROOT / 'physical-operator-config.json'
    continuation.OBSERVER = ROOT / 'acceptance-observer.py'


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads((PHYSICAL / 'invocation-01/receipt.json').read_text())
        cls.config = json.loads((ROOT / 'physical-operator-config.json').read_text())
        cls.log = (PHYSICAL / 'invocation-01/remote-rpc.log').read_bytes()
        cls.trace = (PHYSICAL / 'invocation-01/remote-cache-strace.log').read_bytes()

    def evaluate(self, change=None, log=None, trace=None, config=None):
        r = copy.deepcopy(self.receipt)
        if change: change(r)
        return continuation.evaluate(r, self.log if log is None else log,
                                     self.trace if trace is None else trace,
                                     self.config if config is None else config)

    def test_actual_first_receipt_supports_only_supplemental_request_bound_class(self):
        result = self.evaluate()
        self.assertEqual(result['status'], 'evidence-ready-for-human-review')
        self.assertEqual(result['observer_readiness'], 'inconclusive-pid-gpu-sampling')
        self.assertEqual(result['remote_gpu_evidence'], 'owned-request-bound-cuda-graph-snapshot')
        self.assertIn('not kernel', result['caveat'])

    def test_fallback_rejects_client_summary_without_authentic_raw_pmon_sample(self):
        def change(r):
            positives = [s for s in r['host_samples'] if s.get('role') == 'client' and
                         type(s.get('sm')) is int and s['sm'] > 0]
            self.assertTrue(positives)
            for sample in positives:
                sample['raw_pmon_line'] = '0 0 C 0 0'
                sample['clock_bounds']['remote']['pmon'] = '0 0 C 0 0'
        result = self.evaluate(change)
        self.assertEqual(result['status'], 'STOP-evidence-gap')
        self.assertEqual(result['reason'], 'authenticated in-window client raw pmon sample absent')
        self.assertEqual(result['remote_gpu_evidence'], 'unproven')

    def test_fallback_remote_sample_requires_authentic_raw_inventory_pmon_and_mapping(self):
        def corrupt_all_remote(r):
            for sample in r['host_samples']:
                if sample.get('role') == 'remote':
                    sample['gpu_inventory_raw'] = 'garbage'
                    sample['clock_bounds']['remote']['gpu_inventory_raw'] = 'garbage'
                    sample['raw_pmon_line'] = 'garbage'
                    sample['clock_bounds']['remote']['pmon'] = 'garbage'
                    sample['device_mapping']['inventory'] = []
        result = self.evaluate(corrupt_all_remote)
        self.assertEqual(result['status'], 'STOP-evidence-gap')
        self.assertEqual(result['remote_gpu_evidence'], 'unproven')
        for field, value in (('gpu_inventory_raw', 'garbage'),
                             ('identity_after', 'recycled-start'),
                             ('device_mapping', -1)):
            def change(r):
                for sample in r['host_samples']:
                    if sample.get('role') == 'remote':
                        if field == 'device_mapping':
                            sample[field]['physical_index'] = value
                        else: sample[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.evaluate(change)['status'], 'STOP-evidence-gap')

    def test_forged_positive_summary_does_not_claim_remote_positive_sm(self):
        result = self.evaluate(lambda r: r['request_windows'][0]['gpu_evidence'].update(status='positive-pid-sm-samples'))
        self.assertNotEqual(result['remote_gpu_evidence'], 'positive-owned-pid-sm-samples')

    def test_positive_summary_without_authentic_raw_pmon_does_not_pass(self):
        def change(r):
            remote = next(s for s in r['host_samples'] if s.get('role') == 'remote' and
                s.get('sm') == 0 and r['request_windows'][0]['start_mono_ns'] <= s['before_mono_ns'])
            remote['sm'] = 5  # the retained raw_pmon_line still says SM=0
            r['request_windows'][0]['gpu_evidence'].update(status='positive-pid-sm-samples')
        self.assertNotEqual(self.evaluate(change)['remote_gpu_evidence'], 'positive-owned-pid-sm-samples')

    def test_authenticated_two_role_positive_raw_samples_can_pass_positive_path(self):
        def change(r):
            remote = next(s for s in r['host_samples'] if s.get('role') == 'remote' and
                s.get('sm') == 0 and r['request_windows'][0]['start_mono_ns'] <= s['before_mono_ns'])
            old = remote['raw_pmon_line']
            new = old.replace(' C      0 ', ' C      5 ', 1)
            self.assertNotEqual(old, new)
            remote['raw_pmon_line'] = new
            remote['clock_bounds']['remote']['pmon'] = remote['clock_bounds']['remote']['pmon'].replace(old, new)
            remote['sm'] = 5
        result = self.evaluate(change)
        self.assertEqual(result['remote_gpu_evidence'], 'positive-owned-pid-sm-samples')
        self.assertGreater(result['matched_samples_per_role']['client'], 0)
        self.assertGreater(result['matched_samples_per_role']['remote'], 0)

    def test_positive_sample_must_bind_original_probe_clocks_and_device_mapping(self):
        def positive(r):
            remote = next(s for s in r['host_samples'] if s.get('role') == 'remote' and
                s.get('sm') == 0 and r['request_windows'][0]['start_mono_ns'] <= s['before_mono_ns'])
            old = remote['raw_pmon_line']; new = old.replace(' C      0 ', ' C      5 ', 1)
            remote['raw_pmon_line'] = new
            remote['clock_bounds']['remote']['pmon'] = remote['clock_bounds']['remote']['pmon'].replace(old, new)
            remote['sm'] = 5
            return remote
        for field in ('before_mono_ns', 'cuda_environment'):
            def change(r):
                remote = positive(r)
                if field == 'before_mono_ns':
                    remote['clock_bounds']['local_before']['mono_ns'] += 1
                else:
                    remote['clock_bounds']['remote']['cuda_environment'] = {'CUDA_VISIBLE_DEVICES': '999'}
            with self.subTest(field=field):
                self.assertNotEqual(self.evaluate(change)['remote_gpu_evidence'], 'positive-owned-pid-sm-samples')

    def test_delayed_after_request_snapshot_cannot_claim_request_bound_graph(self):
        def change(r):
            bounds = r['logs']['remote-rpc'][1]['clock_bounds']
            for side in ('local_before', 'local_after'):
                for key in ('mono_ns', 'wall_ns'):
                    bounds[side][key] += 600_000_000_000
        self.assertNotEqual(self.evaluate(change)['status'], 'evidence-ready-for-human-review')

    def test_reordered_or_invalid_snapshot_clocks_are_rejected(self):
        cases = (
            lambda r: r['logs']['remote-rpc'][1]['clock_bounds']['local_after'].update(wall_ns=float('nan')),
            lambda r: r['logs']['remote-rpc'][1]['clock_bounds']['local_after'].update(wall_ns=0),
            lambda r: r['logs']['remote-rpc'][0]['clock_bounds']['remote']['clock_end'].update(remote_mono_ns=0),
            lambda r: r['logs']['remote-rpc'][0]['clock_bounds']['local_before'].update(mono_ns=r['request_windows'][0]['start_mono_ns'] + 1),
        )
        for change in cases:
            with self.subTest(change=change):
                self.assertNotEqual(self.evaluate(change)['status'], 'evidence-ready-for-human-review')

    def test_incomplete_finish_is_not_a_coherent_ordinary_response(self):
        for finish in ('length', 'truncated'):
            with self.subTest(finish=finish):
                def change(r):
                    product = json.loads(r['cli_stdout']); product['finish_reason'] = finish
                    r['cli_stdout'] = json.dumps(product)
                self.assertNotEqual(self.evaluate(change)['status'], 'evidence-ready-for-human-review')

    def test_wrong_response_fails(self):
        self.assertNotEqual(self.evaluate(lambda r: r['request_windows'][0].update(response_id='wrong'))['status'], 'evidence-ready-for-human-review')

    def test_wrong_role_pid_start_fails(self):
        self.assertNotEqual(self.evaluate(lambda r: r['roles']['remote'].update(start='other'))['status'], 'evidence-ready-for-human-review')

    def test_graph_lines_only_in_startup_fails(self):
        def change(r):
            import base64
            row = r['logs']['remote-rpc'][1]
            row['clock_bounds']['remote']['data_b64'] = base64.b64encode(b'Client connection closed\n').decode()
            row['end_offset'] = row['start_offset'] + len(b'Client connection closed\n')
        self.assertNotEqual(self.evaluate(change)['status'], 'evidence-ready-for-human-review')

    def test_tampered_raw_log_and_snapshot_fails(self):
        self.assertNotEqual(self.evaluate(log=self.log.replace(b'warmup complete', b'warmup complete!', 1))['status'], 'evidence-ready-for-human-review')
        self.assertNotEqual(self.evaluate(lambda r: r['logs']['remote-rpc'][1]['clock_bounds']['remote'].update(data_b64='AA=='))['status'], 'evidence-ready-for-human-review')

    def test_wrong_clock_bounds_fails(self):
        self.assertNotEqual(self.evaluate(lambda r: r['logs']['remote-rpc'][0]['clock_bounds']['local_after'].update(mono_ns=10**30))['status'], 'evidence-ready-for-human-review')

    def test_startup_cache_open_cannot_be_after_request_wall(self):
        def change(r):
            r['request_windows'][0]['start_wall_ns'] = 1791081140000000000
        self.assertNotEqual(self.evaluate(change)['status'], 'evidence-ready-for-human-review')

    def test_failed_cli_cleanup_telemetry_each_fail(self):
        for change in (lambda r: r.update(cli_exit=1),
                       lambda r: r.update(cleanup_exact_absence=False),
                       lambda r: r['telemetry_errors'].append('unresolved')):
            with self.subTest(change=change):
                self.assertNotEqual(self.evaluate(change)['status'], 'evidence-ready-for-human-review')

    def test_foreign_config_fails(self):
        config = copy.deepcopy(self.config)
        config['participants'][1]['cache_path'] = '/foreign'
        self.assertNotEqual(self.evaluate(config=config)['status'], 'evidence-ready-for-human-review')

    def test_duplicate_request_count_fails(self):
        self.assertNotEqual(self.evaluate(lambda r: r['request_windows'].append(copy.deepcopy(r['request_windows'][0])))['status'], 'evidence-ready-for-human-review')


class AdmissionTests(unittest.TestCase):
    def test_admission_fsyncs_file_then_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'invocation-01').mkdir()
            ledger = root / 'continuation-admission.json'
            calls = []
            real_fsync = os.fsync
            def observe(fd):
                st = os.fstat(fd)
                calls.append('dir' if st.st_ino == root.stat().st_ino else 'file')
                real_fsync(fd)
            with mock.patch.object(continuation.os, 'fsync', side_effect=observe):
                continuation.reserve(root, ledger, {})
            self.assertEqual(calls, ['file', 'dir'])
            with self.assertRaises(ValueError): continuation.reserve(root, ledger, {})

    def test_admission_directory_fsync_failure_burns_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'invocation-01').mkdir()
            ledger = root / 'continuation-admission.json'
            real_fsync = os.fsync
            def fail_dir(fd):
                if os.fstat(fd).st_ino == root.stat().st_ino:
                    raise OSError('directory fsync failed')
                real_fsync(fd)
            with mock.patch.object(continuation.os, 'fsync', side_effect=fail_dir):
                with self.assertRaisesRegex(OSError, 'directory fsync failed'):
                    continuation.reserve(root, ledger, {})
            self.assertTrue(ledger.exists())
            with self.assertRaises(ValueError): continuation.reserve(root, ledger, {})

    def test_first_spec_must_exist_and_bind_actual_raw_before_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviews = {
                'task4-continuation-spec-review.json': {'verdict': 'FAIL'},
                'task4-continuation-quality-review.json': {'verdict': 'REQUEST_CHANGES'},
                'task4-continuation-spec-review-round4.json': {'verdict': 'PASS'},
                'task4-continuation-quality-review-round2.json': {'verdict': 'APPROVED'},
                'task4-invocation1-spec-adjudication.json': json.loads((ROOT / 'task4-invocation1-spec-adjudication.json').read_text()),
                'task4-invocation1-quality-adjudication.json': json.loads((ROOT / 'task4-invocation1-quality-adjudication.json').read_text()),
            }
            for record in ('task4-continuation-spec-review-round4.json', 'task4-continuation-quality-review-round2.json'):
                reviews[record].update(wrapper_sha256=continuation.digest(TARGET),
                    tests_sha256=continuation.digest(ROOT / 'test_continue_ordinary_acceptance.py'),
                    product_head=continuation.HEAD)
            (root / 'test_continue_ordinary_acceptance.py').write_bytes((ROOT / 'test_continue_ordinary_acceptance.py').read_bytes())
            def put():
                for name, value in reviews.items():
                    if value is not None: (root / name).write_text(json.dumps(value))
                    else: (root / name).unlink(missing_ok=True)
            put(); continuation.verify_reviews(root)
            original = copy.deepcopy(reviews['task4-invocation1-spec-adjudication.json'])
            for name, change in (
                    ('missing', lambda s: None), ('fail', lambda s: s.update(verdict='FAIL')),
                    ('hash', lambda s: s['independent_raw_sha256'].update({'physical-478eb5ef/invocation-01/receipt.json': '0'*64})),
                    ('response', lambda s: s['request'].update(response_id='foreign')),
                    ('head', lambda s: s['authority'].update(product_head='foreign'))):
                reviews['task4-invocation1-spec-adjudication.json'] = copy.deepcopy(original)
                change(reviews['task4-invocation1-spec-adjudication.json'])
                if name == 'missing':
                    reviews['task4-invocation1-spec-adjudication.json'] = None
                put()
                with self.subTest(name=name):
                    with self.assertRaises((FileNotFoundError, ValueError)):
                        continuation.verify_reviews(root)

    def test_only_current_exact_review_pair_admits_before_ledger_or_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviews = {
                'task4-continuation-spec-review.json': {'verdict': 'FAIL'},
                'task4-continuation-quality-review.json': {'verdict': 'REQUEST_CHANGES'},
                'task4-continuation-spec-review-round4.json': {'verdict': 'PASS'},
                'task4-continuation-quality-review-round2.json': {'verdict': 'APPROVED'},
            }
            current = ('task4-continuation-spec-review-round4.json',
                       'task4-continuation-quality-review-round2.json')
            for name in current:
                reviews[name].update(product_head=continuation.HEAD,
                    wrapper_sha256=continuation.digest(TARGET),
                    tests_sha256=continuation.digest(ROOT / 'test_continue_ordinary_acceptance.py'))
            for name in ('task4-invocation1-spec-adjudication.json', 'task4-invocation1-quality-adjudication.json'):
                reviews[name] = json.loads((ROOT / name).read_text())
            (root / 'test_continue_ordinary_acceptance.py').write_bytes((ROOT / 'test_continue_ordinary_acceptance.py').read_bytes())
            def check():
                for name, record in reviews.items():
                    target = root / name
                    if record is None: target.unlink(missing_ok=True)
                    else: target.write_text(json.dumps(record))
                continuation.verify_reviews(root)
                self.assertFalse((PHYSICAL / 'continuation-admission.json').exists())
            check()
            for name, field, bad in (
                    (current[0], 'verdict', 'FAIL'),
                    (current[1], 'verdict', 'REQUEST_CHANGES'),
                    *((name, 'product_head', 'foreign') for name in current),
                    *((name, 'wrapper_sha256', '0'*64) for name in current),
                    *((name, 'tests_sha256', '0'*64) for name in current)):
                old = reviews[name][field]
                reviews[name][field] = bad
                with self.subTest(name=name, field=field):
                    with self.assertRaises(ValueError): check()
                reviews[name][field] = old
            for name in current:
                saved = reviews[name]; reviews[name] = None
                with self.subTest(missing=name):
                    with self.assertRaises(FileNotFoundError): check()
                reviews[name] = saved
    def test_bounded_runner_only_two_fresh_fake_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'invocation-01').mkdir()
            (root / 'invocation-01/receipt.json').write_text('{}')
            (root / 'physical.json').write_text('{}')
            ledger = root / 'continuation-admission.json'
            continuation.reserve(root, ledger, {'first': 'hash'})
            first = json.loads((PHYSICAL / 'invocation-01/receipt.json').read_text())
            calls = []
            def runner(config, output, index, sources):
                calls.append(index)
                target = output / f'invocation-{index:02d}'
                target.mkdir()
                report = copy.deepcopy(first)
                report['source_sha256'] = sources
                report['request_windows'][0]['response_id'] = f'fresh-{index}'
                report['roles']['remote']['token'] = f'token-{index}'
                report['roles']['client']['token'] = f'token-{index}'
                (target / 'receipt.json').write_text(json.dumps(report))
                (target / 'remote-rpc.log').write_bytes(b'remote')
                (target / 'remote-cache-strace.log').write_bytes(b'trace')
                return report
            ready = lambda *args: {'status': 'evidence-ready-for-human-review'}
            self.assertEqual(continuation.run_remaining(root, ledger, ROOT / 'physical-operator-config.json',
                {'source': 'sha'}, runner, ready, 'first-id', 'first-token'), 0)
            self.assertEqual(calls, [2, 3])
            self.assertEqual(json.loads(ledger.read_text())['attempted_indices'], [2, 3])
            with self.assertRaises(ValueError):
                continuation.run_remaining(root, ledger, ROOT / 'physical-operator-config.json',
                    {'source': 'sha'}, runner, ready, 'first-id', 'first-token')
            self.assertEqual(calls, [2, 3])

    def test_bounded_runner_stops_after_evidence_gap_without_third_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'invocation-01').mkdir()
            (root / 'invocation-01/receipt.json').write_text('{}')
            (root / 'physical.json').write_text('{}')
            ledger = root / 'continuation-admission.json'
            continuation.reserve(root, ledger, {'first': 'hash'})
            calls = []
            first = json.loads((PHYSICAL / 'invocation-01/receipt.json').read_text())
            def fake_runner(config, output, index, sources):
                calls.append(index)
                target = output / f'invocation-{index:02d}'
                target.mkdir()
                report = copy.deepcopy(first)
                report['source_sha256'] = sources
                report['request_windows'][0]['response_id'] = 'different-id'
                (target / 'receipt.json').write_text(json.dumps(report))
                (target / 'remote-rpc.log').write_bytes(b'remote')
                (target / 'remote-cache-strace.log').write_bytes(b'trace')
                return report
            def stop(*args): return {'status': 'STOP-evidence-gap'}
            self.assertEqual(continuation.run_remaining(root, ledger, ROOT / 'physical-operator-config.json',
                {'source': 'sha'}, fake_runner, stop, 'first-id', 'first-token'), 1)
            self.assertEqual(calls, [2])
            self.assertEqual(json.loads(ledger.read_text())['attempted_indices'], [2])
            self.assertFalse((root / 'invocation-03').exists())

    def test_bounded_runner_never_reuses_response_or_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'invocation-01').mkdir()
            (root / 'invocation-01/receipt.json').write_text('{}')
            (root / 'physical.json').write_text('{}')
            ledger = root / 'continuation-admission.json'
            continuation.reserve(root, ledger, {'first': 'hash'})
            first = json.loads((PHYSICAL / 'invocation-01/receipt.json').read_text())
            calls = []
            def fake_runner(config, output, index, sources):
                calls.append(index)
                target = output / f'invocation-{index:02d}'
                target.mkdir()
                report = copy.deepcopy(first)
                report['source_sha256'] = sources
                report['request_windows'][0]['response_id'] = 'first-id'
                (target / 'receipt.json').write_text(json.dumps(report))
                (target / 'remote-rpc.log').write_bytes(b'remote')
                (target / 'remote-cache-strace.log').write_bytes(b'trace')
                return report
            with self.assertRaises(ValueError):
                continuation.run_remaining(root, ledger, ROOT / 'physical-operator-config.json',
                    {'source': 'sha'}, fake_runner, lambda *a: {'status': 'evidence-ready-for-human-review'},
                    'first-id', 'first-token')
            self.assertEqual(calls, [2])
            self.assertEqual(json.loads(ledger.read_text())['status'], 'STOP-AMBIGUOUS-ATTEMPT')

    def test_original_first_inventory_and_hash_replayed_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'invocation-01').mkdir()
            (root / 'invocation-01/receipt.json').write_text('{}')
            (root / 'physical.json').write_text('{}')
            ledger = root / 'continuation-admission.json'
            continuation.reserve(root, ledger, {'first': 'hash'})
            self.assertTrue(ledger.exists())
            with self.assertRaises(ValueError): continuation.reserve(root, ledger, {'first': 'hash'})
            (root / 'invocation-02').mkdir()
            with self.assertRaises(ValueError): continuation.reserve(root, root / 'new-admission.json', {'first': 'hash'})

    def test_default_cli_dry_run_never_invokes_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            def forbidden(*args): raise AssertionError('fleet contact')
            self.assertEqual(continuation.main(['--out', tmp], runner=forbidden), 0)
            self.assertFalse(list(Path(tmp).glob('invocation-*')))

    def test_execute_requires_independent_continuation_reviews_before_fleet(self):
        def forbidden(*args): raise AssertionError('fleet contact')
        with self.assertRaises(FileNotFoundError):
            continuation.main(['--execute', '--approved-head', continuation.HEAD], runner=forbidden)
        self.assertFalse((PHYSICAL / 'continuation-admission.json').exists())


if __name__ == '__main__': unittest.main()
