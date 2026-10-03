"""Offline contract checks for bounded issue 255 physical measurement."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'tools/issue255_mvp/measure.py'
spec = importlib.util.spec_from_file_location('issue255_measure', SOURCE)


def module():
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class MeasurementTests(unittest.TestCase):
    def test_real_offline_pid_start_mismatch_preserves_lease_and_record(self):
        m = module()
        with tempfile.TemporaryDirectory() as root:
            m.ROOT = root
            marker = Path(root, 'task2-active')
            marker.mkdir()
            (marker / 'token').write_text('owned-token\n')
            state = {'token': 'owned-token', 'hosts': {m.CLIENT: {}}}
            def local_python(host, command, **kwargs):
                self.assertEqual(host, m.CLIENT)
                proc = subprocess.run(command, shell=True, capture_output=True, text=True)
                if proc.returncode:
                    raise RuntimeError(proc.stderr)
                return proc.stdout
            with mock.patch.object(m, 'remote', side_effect=local_python):
                m.record_pid(state, m.CLIENT, 'client.pid', os.getpid(), 0)
                record = Path(root, 'client.pid').read_bytes()
                self.assertEqual(record, f'{os.getpid()}:0\n'.encode())
                result = m.stop_owned(state)
            self.assertEqual(result[f'{m.CLIENT}:client.pid'], 'start-time mismatch')
            self.assertEqual(Path(root, 'client.pid').read_bytes(), record)
            self.assertEqual((marker / 'token').read_text(), 'owned-token\n')

    def test_real_offline_owned_child_is_terminated_and_lease_released(self):
        m = module()
        with tempfile.TemporaryDirectory() as root:
            m.ROOT = root
            marker = Path(root, 'task2-active')
            marker.mkdir()
            (marker / 'token').write_text('owned-token\n')
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            try:
                state = {'token': 'owned-token', 'hosts': {m.CLIENT: {}}}
                def local_python(host, command, **kwargs):
                    proc = subprocess.run(command, shell=True, capture_output=True, text=True)
                    if proc.returncode:
                        raise RuntimeError(proc.stderr)
                    return proc.stdout
                with mock.patch.object(m, 'remote', side_effect=local_python):
                    m.record_pid(state, m.CLIENT, 'client.pid', child.pid)
                    result = m.stop_owned(state)
                self.assertEqual(result[f'{m.CLIENT}:client.pid'], 'signaled')
                self.assertEqual(result[f'{m.CLIENT}:lease'], 'released')
                self.assertIsNotNone(child.wait(timeout=5))
                self.assertFalse(marker.exists())
                self.assertFalse(Path(root, 'client.pid').exists())
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)

    def test_rejected_existing_marker_does_not_signal_or_remove_prior_ownership(self):
        m = module()
        records = {'01': {'token': 'first-run', 'pid': '101:111'},
                   '04': {'token': 'first-run', 'pid': '202:222'}}
        before = json.dumps(records, sort_keys=True)
        def occupied(host, command, **kwargs):
            if host == m.CLIENT and 'mkdir' in command:
                raise RuntimeError('active lease already exists')
            self.fail(f'unexpected remote operation on rejected admission: {command}')
        state = {'hosts': {}, 'token': 'second-run'}
        with mock.patch.object(m, 'remote', side_effect=occupied) as remote:
            with self.assertRaisesRegex(RuntimeError, 'active lease'):
                m.acquire_hosts(state)
            self.assertEqual(m.stop_owned(state), {})
        self.assertEqual(remote.call_count, 1)
        self.assertEqual(json.dumps(records, sort_keys=True), before)

    def test_main_rejected_lease_keeps_other_run_records_unchanged(self):
        m = module()
        with tempfile.TemporaryDirectory() as root:
            m.ROOT = root
            marker = Path(root, 'task2-active')
            marker.mkdir()
            (marker / 'token').write_text('prior-run\n')
            (Path(root) / 'client.pid').write_text('321:876\n')
            prior = {p.name: p.read_bytes() for p in marker.iterdir()}
            prior['client.pid'] = (Path(root) / 'client.pid').read_bytes()
            output = Path(root, 'new-output')
            commands = []
            def local_remote(host, command, **kwargs):
                commands.append(command)
                self.assertEqual(host, m.CLIENT)
                proc = subprocess.run(command, shell=True, capture_output=True, text=True)
                if proc.returncode:
                    raise RuntimeError(proc.stderr)
                return proc.stdout
            with mock.patch.object(m, 'remote', side_effect=local_remote), \
                 mock.patch.object(m, 'validate_source', return_value=[]), \
                 mock.patch.object(sys, 'argv', ['measure.py', '--output', str(output)]):
                with self.assertRaisesRegex(RuntimeError, 'active lease already exists'):
                    m.main()
            self.assertEqual(json.loads((output / 'cleanup.json').read_text()), {})
            self.assertEqual({p.name: p.read_bytes() for p in marker.iterdir()},
                             {'token': prior['token']})
            self.assertEqual((Path(root) / 'client.pid').read_bytes(), prior['client.pid'])
            self.assertEqual(len(commands), 1)

    def test_empty_acquired_state_never_reads_pid_files_or_signals(self):
        m = module()
        with mock.patch.object(m, 'remote') as remote:
            self.assertEqual(m.stop_owned({'hosts': {}}), {})
        remote.assert_not_called()

    def test_partial_host_acquisition_releases_only_its_token(self):
        m = module()
        calls = []
        def remote(host, command, **kwargs):
            calls.append((host, command))
            if host == m.REMOTE and 'mkdir' in command:
                raise RuntimeError('remote marker occupied')
            return 'released' if 'rmdir' in command else ''
        state = {'hosts': {}, 'token': 'partial-run'}
        with mock.patch.object(m, 'remote', side_effect=remote):
            with self.assertRaisesRegex(RuntimeError, 'remote marker occupied'):
                m.acquire_hosts(state)
            acquisition_calls = len(calls)
            m.stop_owned(state)
        self.assertTrue(any(host == m.CLIENT and 'partial-run' in cmd and 'rmdir' in cmd
                            for host, cmd in calls))
        self.assertFalse(any(host == m.REMOTE for host, cmd in calls[acquisition_calls:]))

    def test_recycled_pid_start_time_refuses_signal_and_preserves_record(self):
        m = module()
        state = {'token': 'our-run', 'hosts': {m.CLIENT: {'client.pid': (345, 100)}}}
        calls = []
        def remote(host, command, **kwargs):
            calls.append(command)
            if 'client.pid' in command and 'pidfd_open' in command:
                return 'start-time mismatch'
            return ''
        with mock.patch.object(m, 'remote', side_effect=remote):
            result = m.stop_owned(state)
        self.assertIn('start-time mismatch', str(result))
        self.assertTrue(any('pidfd_open' in cmd and '100' in cmd and '345' in cmd for cmd in calls))
        self.assertFalse(any('kill -TERM' in cmd for cmd in calls))

    def test_client_death_after_tunnel_creation_terminates_and_waits(self):
        m = module()
        state = {'hosts': {}, 'token': 'tunnel-run'}
        tunnel = mock.Mock()
        tunnel.poll.return_value = None
        def remote(host, command, **kwargs):
            if 'nohup ' in command: return '303\n' if host == m.REMOTE else '101\n'
            if 'rsplit' in command: return '100\n'
            if 'pgrep -P' in command: return '202\n'
            if '/proc/202/cmdline' in command: return 'ggml-rpc-server'
            if 'ss -ltn' in command: return ':50055'
            if 'pidfd_open' in command: return 'signaled'
            if '/proc/' in command and '/stat' in command: return '100\n'
            if 'kill -0' in command: return ''
            return ''
        with mock.patch.object(m, 'remote', side_effect=remote), \
             mock.patch.object(m.subprocess, 'run'), \
             mock.patch.object(m.time, 'sleep'), \
             mock.patch.object(m.subprocess, 'Popen', return_value=tunnel):
            with self.assertRaisesRegex(RuntimeError, 'client exited during startup'):
                m.launch(state)
            m.stop_owned(state)
        tunnel.terminate.assert_called_once_with()
        tunnel.wait.assert_called_once_with(timeout=5)

    def test_normal_owned_lifecycle_records_exact_start_and_stops_once(self):
        m = module()
        state = {'token': 'normal-run', 'hosts': {m.CLIENT: {'client.pid': (321, 876)}}}
        tunnel = mock.Mock()
        state['tunnel'] = tunnel
        commands = []
        def remote(host, command, **kwargs):
            commands.append(command)
            return 'signaled' if 'pidfd_open' in command else 'released'
        with mock.patch.object(m, 'remote', side_effect=remote):
            first = m.stop_owned(state)
            second = m.stop_owned(state)
        self.assertEqual(first[f'{m.CLIENT}:client.pid'], 'signaled')
        self.assertEqual(second, {})
        self.assertEqual(sum('pidfd_open' in c for c in commands), 1)
        self.assertTrue(any('321' in c and '876' in c for c in commands))
        tunnel.terminate.assert_called_once_with()
        tunnel.wait.assert_called_once_with(timeout=5)

    def test_stream_separates_reasoning_and_visible_content_and_uses_usage_tokens(self):
        m = module()
        chunks = [
            (1.0, {'id': 'r1', 'choices': [{'delta': {'role': 'assistant'}, 'finish_reason': None}]}),
            (2.0, {'id': 'r1', 'choices': [{'delta': {'reasoning_content': 'thinking'}, 'finish_reason': None}]}),
            (3.0, {'id': 'r1', 'choices': [{'delta': {'content': 'Local backups help.'}, 'finish_reason': None}]}),
            (4.0, {'id': 'r1', 'choices': [{'delta': {}, 'finish_reason': 'stop'}]}),
            (4.1, {'id': 'r1', 'choices': [], 'usage': {'completion_tokens': 9},
                   'timings': {'predicted_ms': 2200, 'predicted_per_second': 4.09}}),
        ]
        result = m.reduce_stream(chunks, 0.5)
        self.assertEqual(result['response_id'], 'r1')
        self.assertEqual(result['reasoning'], 'thinking')
        self.assertEqual(result['completion'], 'Local backups help.')
        self.assertEqual(result['first_token_ttft_seconds'], 1.5)
        self.assertEqual(result['first_visible_content_seconds'], 2.5)
        self.assertEqual(result['generated_tokens'], 9)
        self.assertEqual(result['stop_reason'], 'stop')
        self.assertAlmostEqual(result['decode_tokens_per_second'], 4.09)

    def test_stream_rejects_mixed_id_missing_usage_or_empty_content(self):
        m = module()
        with self.assertRaisesRegex(ValueError, 'identity'):
            m.reduce_stream([(1, {'id': 'a', 'choices': []}),
                             (2, {'id': 'b', 'choices': []})], 0)
        with self.assertRaisesRegex(ValueError, 'usage'):
            m.reduce_stream([(1, {'id': 'a', 'choices': [{'delta': {'content': 'x'},
                                                           'finish_reason': 'stop'}]})], 0)

    def test_socket_counter_parses_only_exact_pid_and_endpoint(self):
        m = module()
        raw = 'ESTAB 0 0 10.0.0.142:37540 10.0.0.204:50055 users:(("llama-server",pid=123,fd=34))\n\tbytes_sent:203 bytes_received:89\nESTAB 0 0 10.0.0.142:37541 10.0.0.204:50055 users:(("llama-server",pid=124,fd=36))\n\tbytes_sent:999 bytes_received:999\n'
        self.assertEqual(m.tcp_counters(raw, 123, '10.0.0.204:50055'),
                         {'bytes_sent': 203, 'bytes_received': 89, 'local': '10.0.0.142:37540'})
        with self.assertRaisesRegex(ValueError, 'socket'):
            m.tcp_counters(raw, 999, '10.0.0.204:50055')

    def test_snapshot_gpu_before_after_is_pid_bound(self):
        m = module()
        raw = '1791000000.0\n980, 1\n486981, 970\n123 (ggml-rpc-server) S 1\n10.0.0.204 via 10.0.0.1 dev eno1 src 10.0.0.204\n1791000000.2\n'
        self.assertEqual(m.snapshot_gpu(raw, 486981), {'used_mib': 980,
                         'util_percent': 1, 'process_mib': 970})
        self.assertIsNone(m.snapshot_gpu(raw, 777)['process_mib'])

    def test_retained_four_request_epochs_are_separate_and_participating(self):
        import json
        evidence = SOURCE.parents[2] / 'docs/implementation/two-host-mvp-255/evidence/task2'
        ids = set()
        for index in range(1, 5):
            path = evidence / f'request-{index:02d}'
            summary = json.loads((path / 'summary.json').read_text())
            stream = json.loads((path / 'stream.json').read_text())
            before = json.loads((path / 'before.json').read_text())
            after = json.loads((path / 'after.json').read_text())
            self.assertEqual(summary['index'], index)
            self.assertEqual(summary['response'], stream['result'])
            self.assertEqual(summary['response']['generated_tokens'], 53)
            self.assertEqual(summary['response']['stop_reason'], 'stop')
            self.assertEqual(stream['payload']['messages'][0]['content'],
                             'In one sentence, explain why local backups are useful.')
            self.assertTrue(all(after['health'].values()))
            self.assertEqual(summary['network_socket_delta']['local'],
                             before['client_tcp']['local'])
            self.assertGreater(summary['network_socket_delta']['bytes_sent'], 0)
            ids.add(summary['response']['response_id'])
            for host in ('01', '04'):
                gpu = summary['gpu'][host]
                self.assertGreater(gpu['matching_pid_nonzero_util_samples'], 0)
                self.assertGreater(gpu['process_present_samples'], 0)
                self.assertEqual(before['snapshots'][host]['pid'],
                                 after['snapshots'][host]['pid'])
        self.assertEqual(len(ids), 4)
        source = json.loads((evidence / 'startup-source.json').read_text())
        self.assertEqual(source['cache_hit_count'], 9)
        self.assertEqual(source['cache_hit_immutable_bytes'], 473497600)
        shutdown = json.loads((evidence / 'shutdown-verified.json').read_text())
        self.assertTrue(all(not h['process_alive'] and not h['port_listening']
                            for h in shutdown.values()))

    def test_gpu_window_requires_matching_pid_and_in_window_nonzero_util(self):
        m = module()
        rows = [{'epoch': 10., 'used_mib': 100, 'util_percent': 0, 'pids': [42]},
                {'epoch': 11., 'used_mib': 120, 'util_percent': 2, 'pids': [42]},
                {'epoch': 12., 'used_mib': 140, 'util_percent': 6, 'pids': [99]},
                {'epoch': 13., 'used_mib': 90, 'util_percent': 0, 'pids': [42]}]
        result = m.gpu_window(rows, 10.5, 12.5, 42)
        self.assertEqual(result['sample_count'], 2)
        self.assertEqual(result['process_present_samples'], 1)
        self.assertEqual(result['matching_pid_nonzero_util_samples'], 1)
        self.assertEqual(result['sampled_peak_used_mib'], 140)


if __name__ == '__main__':
    unittest.main()
