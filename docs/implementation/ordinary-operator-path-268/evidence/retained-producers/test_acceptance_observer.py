"""CPU-only contract tests for the external issue-268 acceptance observer."""
import importlib.util
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import time
from unittest.mock import patch

P = Path(__file__).with_name('acceptance-observer.py')


def module():
    spec = importlib.util.spec_from_file_location('acceptance_observer', P)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def actual_sample_probe(m, row, inventory, *, inventory_exit=0, after_start=None, gpu=0):
    """Execute the serialized on-host PROBE against CPU-only /proc and smi shims."""
    shim = '''
import json, pathlib, subprocess, sys
fixture_pid = int(sys.argv[1]); fixture_start = sys.argv[2]; fixture_after = sys.argv[3]
fixture_inventory = sys.argv[4]; fixture_inv_exit = int(sys.argv[5]); fixture_gpu = int(sys.argv[6])
reads = [0]
original_text = pathlib.Path.read_text
original_bytes = pathlib.Path.read_bytes
def read_text(path, *a, **kw):
    if str(path) == f'/proc/{fixture_pid}/stat':
        reads[0] += 1
        value = fixture_start if reads[0] == 1 else fixture_after
        if value == 'ABSENT': raise FileNotFoundError(str(path))
        return '1 (fixture) ' + ' '.join(['S'] + ['0'] * 18 + [value])
    return original_text(path, *a, **kw)
def read_bytes(path, *a, **kw):
    if str(path) == f'/proc/{fixture_pid}/environ': return b'CUDA_VISIBLE_DEVICES=GPU-bbb\\0'
    return original_bytes(path, *a, **kw)
def fake_run(command, **kw):
    if command[:2] == ['nvidia-smi', '--query-gpu=index,uuid,pci.bus_id']:
        return subprocess.CompletedProcess(command, fixture_inv_exit, stdout=fixture_inventory, stderr='inventory diagnostic')
    if command[:2] == ['nvidia-smi', 'pmon']:
        return subprocess.CompletedProcess(command, 0, stdout=f'{fixture_gpu} {fixture_pid} C 5 0 0 0 app\\n', stderr='')
    raise AssertionError(command)
pathlib.Path.read_text = read_text
pathlib.Path.read_bytes = read_bytes
subprocess.run = fake_run
exec(sys.argv[7])
'''
    proc = subprocess.run([sys.executable, '-c', shim, str(row['pid']), row['start'],
                           after_start if after_start is not None else row['start'],
                           inventory, str(inventory_exit), str(gpu), m.PROBE],
                          input=json.dumps({'action': 'sample', 'pid': row['pid'], 'start': row['start']}),
                          text=True, capture_output=True, timeout=5)
    if proc.returncode: raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


def sampled_receipt(m, remote, client):
    """Feed actual serialized probe responses through both roles and result()."""
    with tempfile.TemporaryDirectory() as td:
        config = {'participants': [{'role': role, 'execution_address': role, 'port': 55,
                   'cache_path': td, 'cache_ranges': [], 'device': 'CUDA0'}
                   for role in ('remote', 'client')],
                  'backend_options': {'rpc_physical_device': 'CUDA0'}}
        t = m.Telemetry(config, Path(td)); t.config_path = Path('fixture.json')
        rows = {'remote': {'pid': 22, 'start': '200', 'token': 't'},
                'client': {'pid': 11, 'start': '100', 'token': 't'}}
        t.roles.update(rows)
        probes = {'remote': remote, 'client': client}
        def read(host, payload, timeout=20):
            if payload['action'] != 'sample': raise AssertionError(payload)
            return {'local_before': {'mono_ns': 120}, 'local_after': {'mono_ns': 140},
                    'remote': probes[host]}
        with patch.object(m, 'remote_read', read):
            for role, row in rows.items():
                t.stop.set()
                with patch.object(t.stop, 'is_set', side_effect=[False, True]):
                    t.ready[role] = __import__('threading').Event()
                    t.sampler(role, row)
        t.windows = [{'start_mono_ns': 100, 'end_mono_ns': 200}]
        return t.result(0, '', '', {}, False)


class ObserverTests(unittest.TestCase):
    def test_actual_probe_failed_inventory_cannot_authenticate_pmon_positive(self):
        m = module(); remote = {'pid': 22, 'start': '200'}; client = {'pid': 11, 'start': '100'}
        good = '0, GPU-bbb, 0000:01:00.0\n'
        report = sampled_receipt(m, actual_sample_probe(m, remote, good, inventory_exit=1),
                                    actual_sample_probe(m, client, good))
        self.assertEqual(report['request_windows'][0]['gpu_evidence']['status'], 'inconclusive')
        self.assertEqual(report['request_windows'][0]['gpu_evidence']['matched_samples_per_role']['remote'], 0)
        self.assertEqual(report['host_samples'][0]['gpu_inventory_raw'], good)
        self.assertEqual(report['host_samples'][0]['gpu_inventory_exit'], 1)
        self.assertTrue(report['telemetry_errors'])

    def test_actual_probe_partial_ambiguous_and_missing_authority_inventories(self):
        m = module(); remote = {'pid': 22, 'start': '200'}; client = {'pid': 11, 'start': '100'}
        good = actual_sample_probe(m, client, '0, GPU-bbb, 0000:01:00.0\n')
        invalid = (
            '',
            '0, GPU-bbb, 0000:01:00.0\nmalformed\n',
            '0, GPU-bbb, 0000:01:00.0\n1, GPU-bbb, 0000:02:00.0\n',
            '0, GPU-bbb, 0000:01:00.0\n0, GPU-ccc, 0000:02:00.0\n',
            '0, GPU-bbb, 0000:01:00.0\n1, GPU-ccc, 0000:01:00.0\n',
            ', GPU-bbb, 0000:01:00.0\n',
            '0, , 0000:01:00.0\n',
            '0, GPU-bbb, \n',
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                report = sampled_receipt(m, actual_sample_probe(m, remote, raw), good)
                self.assertEqual(report['request_windows'][0]['gpu_evidence']['status'], 'inconclusive')
                self.assertEqual(report['request_windows'][0]['gpu_evidence']['matched_samples_per_role']['remote'], 0)
                self.assertTrue(report['telemetry_errors'])

    def test_actual_probe_post_sample_pid_recycle_or_absence_rejects_sm_positive(self):
        m = module(); remote = {'pid': 22, 'start': '200'}; client = {'pid': 11, 'start': '100'}
        raw = '0, GPU-bbb, 0000:01:00.0\n'
        good = actual_sample_probe(m, client, raw)
        for after in ('201', 'ABSENT'):
            with self.subTest(after=after):
                probe = actual_sample_probe(m, remote, raw, after_start=after)
                self.assertIn('22 C 5', probe['pmon'])
                report = sampled_receipt(m, probe, good)
                self.assertEqual(report['request_windows'][0]['gpu_evidence']['status'], 'inconclusive')
                self.assertEqual(report['request_windows'][0]['gpu_evidence']['matched_samples_per_role']['remote'], 0)
                self.assertTrue(report['telemetry_errors'])
                self.assertEqual(probe['identity_before'], '200')
                self.assertEqual(probe['identity_after'], None if after == 'ABSENT' else after)
                self.assertEqual(report['host_samples'][0]['identity_after'], probe['identity_after'])

    def test_actual_probe_valid_single_gpu_uuid_remap_and_wrong_physical_gpu(self):
        m = module(); remote = {'pid': 22, 'start': '200'}; client = {'pid': 11, 'start': '100'}
        client_probe = actual_sample_probe(m, client, '0, GPU-bbb, 0000:01:00.0\n')
        remote_probe = actual_sample_probe(m, remote,
            '0, GPU-aaa, 0000:01:00.0\n7, GPU-bbb, 0000:07:00.0\n', gpu=7)
        for probe in (client_probe, remote_probe):
            self.assertEqual(probe['identity_before'], probe['identity_after'])
        positive = sampled_receipt(m, remote_probe, client_probe)
        self.assertEqual(positive['request_windows'][0]['gpu_evidence']['status'], 'positive-pid-sm-samples')
        self.assertEqual(positive['request_windows'][0]['gpu_evidence']['matched_samples_per_role'],
                         {'remote': 1, 'client': 1})
        self.assertFalse(positive['telemetry_errors'])
        wrong = actual_sample_probe(m, remote,
            '0, GPU-aaa, 0000:01:00.0\n7, GPU-bbb, 0000:07:00.0\n', gpu=0)
        self.assertEqual(sampled_receipt(m, wrong, client_probe)['request_windows'][0]['gpu_evidence']['status'],
                         'inconclusive')

    def test_pid_start_and_token_are_all_required(self):
        m = module()
        row = {'pid': 123, 'start': '999', 'token': 'unique'}
        self.assertTrue(m.owned_identity(row, {'pid': 123, 'start': '999', 'token': 'unique'}))
        for change in ({'pid': 124}, {'start': '1000'}, {'token': 'other'}):
            self.assertFalse(m.owned_identity(row, row | change))

    def test_request_window_requires_both_owned_pid_samples(self):
        m = module()
        roles = {'client': {'pid': 11, 'start': '100', 'token': 't'},
                 'rpc': {'pid': 22, 'start': '200', 'token': 't'}}
        window = {'start_mono_ns': 100, 'end_mono_ns': 200}
        samples = [
            {'role': 'client', 'pid': 11, 'start': '100', 'token': 't', 'before_mono_ns': 120,
             'after_mono_ns': 140, 'sm': 1, 'gpu_index': 0, 'identity_observed': '100', 'device_mapping': {'physical_index': 0}},
            {'role': 'rpc', 'pid': 22, 'start': '200', 'token': 't', 'before_mono_ns': 150,
             'after_mono_ns': 170, 'sm': 2, 'gpu_index': 0, 'identity_observed': '200', 'device_mapping': {'physical_index': 0}},
        ]
        for sample in samples:
            sample.update(identity_before=sample['start'], identity_after=sample['start'],
                          gpu_inventory_exit=0, inventory_authentic=True, probe_status=0)
        self.assertEqual(m.request_gpu_evidence(window, roles, samples)['status'], 'positive-pid-sm-samples')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:1])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'start': '201'}])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'before_mono_ns': 90}])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'sm': 0}])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'gpu_index': 7}])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'identity_observed': '201'}])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'identity_before': '201'}])['status'], 'inconclusive')
        self.assertEqual(m.request_gpu_evidence(window, roles, samples[:-1] +
                         [samples[-1] | {'identity_after': None}])['status'], 'inconclusive')

    def test_real_sampler_to_result_wiring_and_device_binding(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            config = {'participants': [{'role': role, 'execution_address': role, 'port': 55,
                       'cache_path': td, 'cache_ranges': [], 'device': 'CUDA0'} for role in ('remote', 'client')],
                      'backend_options': {'rpc_physical_device': 'CUDA0'}}
            t = m.Telemetry(config, Path(td)); t.config_path = Path('fixture.json')
            rows = {'remote': {'pid': 22, 'start': '200', 'token': 't'},
                    'client': {'pid': 11, 'start': '100', 'token': 't'}}
            t.roles.update(rows)
            def probe(host, payload, timeout=20):
                row = rows[host]
                return {'local_before': {'mono_ns': 120}, 'local_after': {'mono_ns': 140},
                        'remote': {'identity': row['start'], 'identity_before': row['start'],
                                   'identity_after': row['start'], 'pmon_exit': 0,
                                   'pmon': f"0 {row['pid']} C 5 0 0 0 app\n",
                                   'gpu_inventory_raw': '0, GPU-aaa, 0000:01:00.0\n',
                                   'gpu_inventory_exit': 0, 'cuda_environment': {}}}
            with patch.object(m, 'remote_read', probe):
                for role, row in rows.items():
                    t.stop.set() # one real sampler iteration, no thread/network
                    with patch.object(t.stop, 'is_set', side_effect=[False, True]):
                        t.ready[role] = __import__('threading').Event()
                        t.sampler(role, row)
            t.windows = [{'start_mono_ns': 100, 'end_mono_ns': 200}]
            result = t.result(0, '', '', {}, False)
            self.assertEqual(result['request_windows'][0]['gpu_evidence']['status'], 'positive-pid-sm-samples')
            self.assertEqual(result['request_windows'][0]['gpu_evidence']['matched_samples_per_role'], {'remote': 1, 'client': 1})
            self.assertEqual({s['gpu_index'] for s in t.samples if s['sm']}, {0})
            self.assertEqual({s['device_mapping']['method'] for s in t.samples if s['sm']}, {'single-inventory-gpu'})
            for s in t.samples:
                if s['role'] == 'remote' and s['sm']: s['gpu_index'] = 7
            self.assertEqual(m.request_gpu_evidence(t.windows[0], t.roles, t.samples)['status'], 'inconclusive')

    def test_cuda_mapping_requires_authenticated_physical_identity(self):
        m = module()
        inventory = [{'index': 0, 'uuid': 'GPU-aaa', 'pci_bus_id': '0000:01:00.0'},
                     {'index': 7, 'uuid': 'GPU-bbb', 'pci_bus_id': '0000:07:00.0'}]
        self.assertEqual(m.resolve_device('CUDA0', {'CUDA_VISIBLE_DEVICES': 'GPU-bbb'}, inventory)['physical_index'], 7)
        self.assertIsNone(m.resolve_device('CUDA0', {}, inventory)['physical_index'])
        self.assertIsNone(m.resolve_device('CUDA0', {'CUDA_VISIBLE_DEVICES': '7'}, inventory)['physical_index'])

    def test_collector_failure_cleanup_uses_exact_token_pid_start_and_reaps_local_child(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            cfg = {'participants': [{'role': 'remote', 'execution_address': 'fixture',
                    'port': 55, 'cache_path': td, 'cache_ranges': [], 'lifecycle_dir': td}]}
            t = m.Telemetry(cfg, Path(td)); row = {'pid': 42, 'start': '42', 'token': 'a'*32}
            t.roles['remote'] = row
            actions = []
            def probe(host, payload, timeout=20):
                actions.append(payload)
                if payload['action'] == 'trace-stop':
                    return {'remote': {'recorded': {'pid': 99, 'start': '500', 'token': 'a'*32}, 'identity': None, 'status': 'stopped'}}
                if payload['action'] == 'trace-read':
                    return {'remote': {'status': 'read', 'data_b64': base64.b64encode(b'fixture trace').decode(), 'eof': True}}
                if payload['action'] == 'readback': return {'remote': {'identity': None, 'listener': False}}
                if payload['action'] == 'log': return {'remote': {'data_b64': '', 'eof': True}}
                raise AssertionError(payload)
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            t.trace_local = child
            t.trace_record = {'pid': 99, 'start': '500', 'token': 'a'*32}
            t.trace_attempted = True
            with patch.object(m, 'remote_read', probe):
                t.finish()
            self.assertIsNotNone(child.poll())
            self.assertEqual(actions[0]['action'], 'trace-stop')
            self.assertEqual(actions[0]['record'], t.trace_record)
            self.assertEqual((Path(td)/'remote-cache-strace.log').read_bytes(), b'fixture trace')

    def test_recycled_or_foreign_collector_is_not_signalled(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); token = 'a'*32; (root/token).mkdir()
            # The on-host helper must check token and start before signaling.
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            try:
                import os
                stat = (Path('/proc')/str(child.pid)/'stat').read_text().rsplit(') ', 1)[1].split()
                start = stat[19]
                record = {'pid': child.pid, 'start': str(int(start)+1), 'token': token, 'pgid': child.pid}
                (root/token/'observer-cache-tracer.json').write_text(json.dumps(record))
                payload = {'action': 'trace-stop', 'root': str(root), 'token': token, 'record': record}
                process = subprocess.run([sys.executable, '-c', m.PROBE], input=json.dumps(payload), text=True, capture_output=True, timeout=5)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout)['status'], 'recycled-or-absent')
                self.assertIsNone(child.poll())
                payload['token'] = 'foreign'
                process = subprocess.run([sys.executable, '-c', m.PROBE], input=json.dumps(payload), text=True, capture_output=True, timeout=5)
                self.assertNotEqual(process.returncode, 0)
                self.assertIsNone(child.poll())
            finally:
                child.terminate(); child.wait(timeout=5)

    def test_trace_start_requires_product_lease_token_before_launch(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); token = 'a'*32; (root/token).mkdir()
            (root/'active').mkdir(); (root/'active'/'token').write_text('b'*32)
            row = {'action': 'trace-start', 'root': str(root), 'token': token,
                   'pid': __import__('os').getpid(),
                   'start': (Path('/proc')/str(__import__('os').getpid())/'stat').read_text().rsplit(') ',1)[1].split()[19]}
            result = subprocess.run([sys.executable, '-c', m.PROBE], input=json.dumps(row),
                                    text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('lease token', result.stderr)
            self.assertFalse((root/token/'observer-cache-tracer.json').exists())

    def test_failed_attach_checks_exact_command_before_client_and_cleans_collector(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            row = {'pid': 12, 'start': '12', 'token': 'a'*32}
            cfg = {'participants': [{'role': 'remote', 'execution_address': 'remote',
                    'port': 55, 'lifecycle_dir': td, 'cache_path': td, 'cache_ranges': []}]}
            t = m.Telemetry(cfg, Path(td)); t.roles['remote'] = row
            owned = {'pid': 99, 'start': '500', 'token': row['token']}
            actions = []
            def probe(host, payload, timeout=20):
                actions.append(payload['action'])
                if payload['action'] == 'readback': return {'remote': {'identity': row['start'], 'listener': False}}
                if payload['action'] == 'trace-check':
                    return {'remote': {'permission_exit': 0,
                                       'permission_command': ['sudo', '-n', '-l', '--', '/usr/bin/timeout', '-s', 'INT', '1200', '/usr/bin/strace', '-p', '12'],
                                       'collector_command': ['sudo', '-n', '/usr/bin/timeout', '-s', 'INT', '1200', '/usr/bin/strace', '-p', '12']}}
                if payload['action'] == 'trace-start': return {'remote': {'recorded': owned}}
                if payload['action'] == 'trace-read': raise RuntimeError('attachment failed')
                if payload['action'] == 'trace-stop': return {'remote': {'status': 'stopped', 'recorded': owned, 'members': []}}
                if payload['action'] == 'log': return {'remote': {'data_b64': '', 'eof': True}}
                raise AssertionError(payload)
            with patch.object(m, 'remote_read', probe):
                with self.assertRaisesRegex(RuntimeError, 'attachment failed'): t.attach_trace(row)
                t.finish()
            self.assertEqual(actions[:3], ['readback', 'trace-check', 'trace-start'])
            self.assertIn('trace-stop', actions)
            self.assertEqual(t.trace_cleanup['remote']['recorded'], owned)

    def test_mismatched_permission_command_never_starts_tracer_or_client(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            cfg = {'participants': [{'role': 'remote', 'execution_address': 'remote',
                    'port': 55, 'lifecycle_dir': td, 'cache_path': td, 'cache_ranges': []}]}
            t = m.Telemetry(cfg, Path(td)); row = {'pid': 12, 'start': '12', 'token': 'a'*32}
            actions = []
            def probe(host, payload, timeout=20):
                actions.append(payload['action'])
                if payload['action'] == 'readback': return {'remote': {'identity': '12'}}
                if payload['action'] == 'trace-check':
                    return {'remote': {'permission_exit': 0,
                        'permission_command': ['sudo', '-n', '-l', '--', '/usr/bin/strace'],
                        'collector_command': ['sudo', '-n', '/usr/bin/timeout', '-s', 'INT', '1200', '/usr/bin/strace']}}
                raise AssertionError('tracer started without exact command check')
            with patch.object(m, 'remote_read', probe):
                with self.assertRaisesRegex(RuntimeError, 'exact collector command'): t.attach_trace(row)
            self.assertEqual(actions, ['readback', 'trace-check'])

    def test_exited_collector_blocks_http_even_after_prior_attach(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            cfg = {'participants': [{'role': role, 'execution_address': role,
                    'port': 55, 'lifecycle_dir': td, 'cache_path': td, 'cache_ranges': []}
                    for role in ('remote', 'client')]}
            t = m.Telemetry(cfg, Path(td))
            t.roles['remote'] = {'pid': 12, 'start': '12', 'token': 'a'*32}
            t.trace_attempted = True; t.trace_record = {'pid': 99, 'start': '500', 'token': 'a'*32}
            for role in ('remote', 'client'):
                t.ready[role] = __import__('threading').Event(); t.ready[role].set()
            def probe(host, payload, timeout=20):
                if payload['action'] == 'trace-read': return {'remote': {'status': 'read', 'data_b64': '', 'eof': True}}
                if payload['action'] == 'trace-status': return {'remote': {'status': 'exited', 'recorded': t.trace_record}}
                raise AssertionError('HTTP preparation continued after collector exit')
            with patch.object(m, 'remote_read', probe):
                with self.assertRaisesRegex(RuntimeError, 'collector.*active'): t.before_request()

    def test_product_failure_still_stops_collector_and_unresolved_is_explicit(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            cfg = {'participants': [{'role': 'remote', 'execution_address': 'remote',
                    'port': 55, 'lifecycle_dir': td, 'cache_path': td, 'cache_ranges': []}]}
            t = m.Telemetry(cfg, Path(td)); t.config_path = Path('fixture.json')
            t.roles['remote'] = {'pid': 12, 'start': '12', 'token': 'a'*32}
            t.trace_attempted = True; t.trace_record = {'pid': 99, 'start': '500', 'token': 'a'*32}
            def probe(host, payload, timeout=20):
                if payload['action'] == 'trace-stop':
                    self.assertEqual(payload['record'], t.trace_record)
                    return {'remote': {'status': 'unresolved-collector', 'recorded': t.trace_record,
                                       'identity': '500', 'members': [{'pid': 99, 'start': '500'}]}}
                if payload['action'] == 'trace-read':
                    return {'remote': {'status': 'read', 'data_b64': '', 'eof': True}}
                if payload['action'] == 'readback': return {'remote': {'identity': '12', 'listener': True}}
                if payload['action'] == 'log': return {'remote': {'data_b64': '', 'eof': True}}
                raise AssertionError(payload)
            with patch.object(m, 'remote_read', probe):
                readback, clean = t.finish()
            receipt = t.result(1, '', 'product failure', readback, clean)
            self.assertEqual(receipt['collector_identity'], t.trace_record)
            self.assertFalse(clean)
            self.assertTrue(any('unresolved_collector' in e for e in receipt['telemetry_errors']))
            self.assertEqual(m.acceptance_readiness(receipt), 'unproven-cli-cleanup-or-telemetry')

    def test_lost_launch_ack_recovers_collector_identity_from_token_record(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            cfg = {'participants': [{'role': 'remote', 'execution_address': 'remote',
                    'port': 55, 'lifecycle_dir': td, 'cache_path': td, 'cache_ranges': []}]}
            t = m.Telemetry(cfg, Path(td)); t.config_path = Path('fixture.json')
            t.roles['remote'] = {'pid': 12, 'start': '12', 'token': 'a'*32}
            t.trace_attempted = True; recorded = {'pid': 99, 'start': '500', 'token': 'a'*32}
            def probe(host, payload, timeout=20):
                if payload['action'] == 'trace-stop':
                    self.assertIsNone(payload['record'])
                    return {'remote': {'status': 'unresolved-collector', 'recorded': recorded,
                                       'identity': '500', 'members': [{'pid': 99, 'start': '500'}]}}
                if payload['action'] == 'trace-read':
                    return {'remote': {'status': 'read', 'data_b64': '', 'eof': True}}
                if payload['action'] == 'readback': return {'remote': {'identity': '12', 'listener': True}}
                if payload['action'] == 'log': return {'remote': {'data_b64': '', 'eof': True}}
                raise AssertionError(payload)
            with patch.object(m, 'remote_read', probe):
                readback, clean = t.finish()
            receipt = t.result(1, '', 'lost launch acknowledgment', readback, clean)
            self.assertEqual(receipt['collector_identity'], recorded)
            self.assertTrue(any('unresolved_collector' in e for e in receipt['telemetry_errors']))

    def test_real_local_collector_session_stop_does_not_signal_foreign_child(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); token = 'a'*32; (root/token).mkdir()
            collector = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                         start_new_session=True, stderr=subprocess.DEVNULL)
            foreign = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                       start_new_session=True, stderr=subprocess.DEVNULL)
            try:
                stat = (Path('/proc')/str(collector.pid)/'stat').read_text().rsplit(') ',1)[1].split()
                record = {'pid': collector.pid, 'start': stat[19], 'token': token, 'pgid': collector.pid}
                (root/token/'observer-cache-tracer.json').write_text(json.dumps(record))
                p = subprocess.run([sys.executable, '-c', m.PROBE], input=json.dumps({
                    'action': 'trace-stop', 'root': str(root), 'token': token, 'record': record}),
                    text=True, capture_output=True, timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout)['status'], 'stopped')
                collector.wait(timeout=3)
                self.assertIsNone(foreign.poll())
            finally:
                if collector.poll() is None: collector.terminate()
                collector.wait(timeout=5)
                foreign.terminate(); foreign.wait(timeout=5)

    def test_product_failure_after_spawn_uses_real_cli_cleanup_and_collector_stop(self):
        m = module(); sys.path.insert(0, str(m.REPO))
        from inferswarm.operator import lifecycle, runtime
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parts = [{'role': role, 'execution_address': host, 'lifecycle_dir': str(root/host),
                      'port': 58911 if role == 'remote' else 58912, 'cache_path': td,
                      'cache_ranges': []} for role, host in [('remote', 'fixture-remote'), ('client', 'fixture-client')]]
            cfg = root/'config.json'; cfg.write_text(json.dumps({'participants': parts}))
            actions = []
            def local_call(self, host, payload): return lifecycle._onhost(payload)
            def probe(host, payload, timeout=20):
                actions.append(payload)
                if payload['action'] == 'trace-stop':
                    return {'remote': {'status': 'stopped', 'recorded': payload['record'], 'members': []}}
                if payload['action'] == 'trace-read':
                    return {'remote': {'status': 'read', 'data_b64': '', 'eof': True}}
                if payload['action'] == 'readback':
                    return {'remote': {'identity': lifecycle.identity(payload['pid']), 'listener': False}}
                if payload['action'] == 'log':
                    data = (Path(payload['root'])/payload['token']/(payload['name']+'.log')).read_bytes()[payload['offset']:]
                    return {'remote': {'data_b64': base64.b64encode(data).decode(), 'eof': True}}
                raise AssertionError(payload)
            def no_gpu(self, role, row): self.ready[role].set()
            def attach(self, row):
                self.trace_attempted = True
                self.trace_record = {'pid': 99, 'start': '500', 'token': row['token']}
            def failing_run_config(path):
                manager = lifecycle.LeaseManager(lifecycle.SSHTransport(), 'a'*32)
                for part in parts: manager.acquire(part['execution_address'], part['lifecycle_dir'])
                try:
                    for part, name in zip(parts, ('rpc', 'client')):
                        manager.spawn(part['execution_address'], name,
                                      [sys.executable, '-c', 'import time; time.sleep(30)'])
                    raise RuntimeError('fixture product failure after spawn')
                finally: manager.cleanup()
            with patch.object(lifecycle.SSHTransport, 'call', local_call), \
                 patch.object(runtime, 'run_config', failing_run_config), \
                 patch.object(m, 'remote_read', probe), \
                 patch.object(m.Telemetry, 'sampler', no_gpu), \
                 patch.object(m.Telemetry, 'attach_trace', attach):
                receipt = m.run_one(cfg, root, 1, {'fixture': 'CPU-ONLY'})
            self.assertEqual(receipt['cli_exit'], 1)
            self.assertIn('fixture product failure', receipt['cli_stderr'])
            self.assertTrue(receipt['cleanup_exact_absence'])
            self.assertEqual(receipt['collector_cleanup']['remote']['status'], 'stopped')
            self.assertEqual([a['action'] for a in actions].count('trace-stop'), 1)
            self.assertEqual(receipt['request_windows'], [])

    def test_cleanup_requires_release_and_exact_listener_absence(self):
        m = module()
        roles = {'inferswarm01': {'client': {'pid': 11, 'start': '100', 'token': 't'}},
                 'inferswarm04': {'rpc': {'pid': 22, 'start': '200', 'token': 't'}}}
        clean = {h: {'lease': 'released'} for h in roles}
        readback = {h: {name: {'identity': None, 'listener': False, 'recorded': row}
                        for name, row in names.items()} for h, names in roles.items()}
        self.assertTrue(m.cleanup_ok(clean, readback, roles))
        self.assertFalse(m.cleanup_ok(clean, readback | {'inferswarm04': {}}, roles))
        bad = {**readback, 'inferswarm04': {'rpc': {**readback['inferswarm04']['rpc'], 'listener': True}}}
        self.assertFalse(m.cleanup_ok(clean, bad, roles))
        self.assertFalse(m.cleanup_ok({'inferswarm01': clean['inferswarm01']}, readback, roles))

    def test_cache_open_only_exact_native_path_in_startup(self):
        m = module()
        keys = {'abc0123456789def'}
        path = '/home/hermes/cache/rpc/abc0123456789def'
        line = '23:45:00.123456 openat(AT_FDCWD, "'+path+'", O_RDONLY) = 9'
        self.assertTrue(m.cache_open(line, path.rsplit('/rpc/', 1)[0], keys))
        self.assertFalse(m.cache_open(line.replace(' = 9', ' = -1 ENOENT'), path.rsplit('/rpc/', 1)[0], keys))
        self.assertFalse(m.cache_open(line.replace('abc0123456789def', 'ffffffffffffffff'), path.rsplit('/rpc/', 1)[0], keys))
        self.assertFalse(m.cache_open('[pid 24] ' + line, path.rsplit('/rpc/', 1)[0], keys, pid=23))
        self.assertTrue(m.cache_open('[pid 23] ' + line, path.rsplit('/rpc/', 1)[0], keys, pid=23))

    def test_receipt_readiness_is_fail_closed_and_inconclusive_not_absent(self):
        m = module()
        import copy
        receipt = {'response_id': 'r1', 'text': 'A sentence.', 'finish_reason': 'stop',
                   'observed_placement': {'layers': {'1': 'CPU'}},
                   'verified_backing': {'remote': {
                       'backing': 'participant-local-cache-verified-not-yet-observed-consumed',
                       'eligible_cache_reads': 1}}, 'cleanup': {'one': {'lease': 'released'}}}
        report = {'cli_exit': 0, 'cleanup_exact_absence': True, 'telemetry_errors': [],
                  'request_windows': [{'response_id': 'r1', 'gpu_evidence': {
                      'status': 'positive-pid-sm-samples'}}], 'startup_cache_open_count': 1,
                  'cli_stdout': json.dumps(receipt)}
        self.assertEqual(m.acceptance_readiness(report), 'evidence-ready-for-human-review')
        low = copy.deepcopy(report)
        low['request_windows'][0]['gpu_evidence']['status'] = 'inconclusive'
        self.assertEqual(m.acceptance_readiness(low), 'inconclusive-pid-gpu-sampling')
        wrong = copy.deepcopy(report)
        wrong['cli_stdout'] = json.dumps(receipt | {'response_id': 'other'})
        self.assertEqual(m.acceptance_readiness(wrong), 'product-receipt-incomplete')

    def test_default_invocation_never_contacts_fleet(self):
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.run([sys.executable, str(P), '--out', td], text=True, capture_output=True, timeout=15)
            m = module()
            head = subprocess.check_output(['git', '-C', str(m.REPO), 'rev-parse', 'HEAD'], text=True).strip()
            dirty = subprocess.check_output(['git', '-C', str(m.REPO), 'status', '--porcelain'])
            if head == m.HEAD and not dirty:
                self.assertEqual(p.returncode, 0, p.stderr)
                manifest = json.loads((Path(td)/'dry-run.json').read_text())
                self.assertEqual(manifest['mode'], 'dry-run')
                self.assertFalse(manifest['fleet_contact'])
            else:
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertFalse((Path(td)/'dry-run.json').exists())
            self.assertFalse((Path(td)/'physical.json').exists())

    def test_execute_refuses_without_exact_head_before_fleet_access(self):
        with tempfile.TemporaryDirectory() as td:
            p = subprocess.run([sys.executable, str(P), '--out', td, '--execute',
                                '--approved-head', 'wrong'], text=True, capture_output=True, timeout=15)
            self.assertEqual(p.returncode, 2)
            self.assertIn('approved-head', p.stderr)
            self.assertFalse((Path(td)/'physical.json').exists())


    def test_config_rejects_placement_drift_but_allows_distinct_leases(self):
        m = module()
        with tempfile.TemporaryDirectory() as td:
            data = json.loads(m.DEFAULT_CONFIG.read_text())
            for p in data['participants']:
                p['lifecycle_dir'] = str(Path(td)/p['role'])
            config = Path(td)/'config.json'; config.write_text(json.dumps(data))
            self.assertTrue(m.accepted_config_shape(config))
            data['placement'][0]['last_layer'] = 39
            config.write_text(json.dumps(data))
            self.assertFalse(m.accepted_config_shape(config))

    def test_instrumented_cli_uses_real_entrypoint_and_local_child_ownership(self):
        m = module()
        sys.path.insert(0, str(m.REPO))
        from inferswarm.operator import lifecycle, runtime
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = {'participants': [
                {'role': role, 'execution_address': host, 'lifecycle_dir': str(root / host),
                 'port': 58901 if role == 'remote' else 58902,
                 'cache_path': str(root/'cache'), 'cache_ranges': []}
                for role, host in [('remote', 'fixture-remote'), ('client', 'fixture-client')]]}
            cfg = root/'config.json'; cfg.write_text(json.dumps(config))

            def local_call(self, host, payload):
                return lifecycle._onhost(payload)

            def probe(host, payload, timeout=20):
                r = {'clock_start': {'remote_wall_ns': 1, 'remote_mono_ns': 1},
                     'clock_end': {'remote_wall_ns': 2, 'remote_mono_ns': 2}}
                if payload['action'] == 'readback':
                    r.update(identity=lifecycle.identity(payload['pid']), listener=False)
                elif payload['action'] == 'log':
                    path = Path(payload['root'])/payload['token']/(payload['name']+'.log')
                    data = path.read_bytes()[payload['offset']:]
                    r.update(data_b64=base64.b64encode(data).decode(), eof=True)
                else: raise AssertionError('unexpected probe')
                return {'local_before': {'mono_ns': 1}, 'local_after': {'mono_ns': 2}, 'remote': r}

            def no_gpu(self, role, row):
                self.ready[role].set()

            class Trace:
                def poll(self): return None
                def wait(self, timeout): return 0

            def attach(self, row):
                self.trace = Trace()

            def fake_post(self, url, payload, timeout):
                return {'id': 'fixture-response'}

            def fake_run_config(path):
                manager = lifecycle.LeaseManager(lifecycle.SSHTransport(), 'fixture-token')
                for part in config['participants']:
                    manager.acquire(part['execution_address'], part['lifecycle_dir'])
                try:
                    for part, name in zip(config['participants'], ('rpc', 'client')):
                        manager.spawn(part['execution_address'], name,
                                      [sys.executable, '-c', 'import time; time.sleep(30)'])
                    response = runtime.JSONHTTP().post('http://fixture/v1/chat/completions',
                                                       {'messages': []}, timeout=5)
                    return {'response_id': response['id']}
                finally:
                    manager.cleanup()

            with patch.object(lifecycle.SSHTransport, 'call', local_call), \
                 patch.object(runtime.JSONHTTP, 'post', fake_post), \
                 patch.object(runtime, 'run_config', fake_run_config), \
                 patch.object(m, 'remote_read', probe), \
                 patch.object(m.Telemetry, 'sampler', no_gpu), \
                 patch.object(m.Telemetry, 'attach_trace', attach):
                result = m.run_one(cfg, root, 1, {'fixture': 'CPU-ONLY'})
            self.assertEqual(result['cli_exit'], 0, result['cli_stderr'])
            self.assertEqual(result['request_windows'][0]['response_id'], 'fixture-response')
            self.assertEqual(set(result['roles']), {'remote', 'client'})
            self.assertTrue(result['cleanup_exact_absence'], result['cleanup'])
            self.assertTrue((root/'invocation-01'/'receipt.json').exists())


if __name__ == '__main__': unittest.main()
