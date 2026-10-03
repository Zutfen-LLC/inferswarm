"""Offline contract checks for bounded issue 255 physical measurement."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'tools/issue255_mvp/measure.py'
spec = importlib.util.spec_from_file_location('issue255_measure', SOURCE)


def module():
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class MeasurementTests(unittest.TestCase):
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
