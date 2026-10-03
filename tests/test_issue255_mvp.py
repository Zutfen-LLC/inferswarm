"""Offline regression checks for the Issue #255 physical staging operator."""
import hashlib
import importlib.util
import io
import json
from datetime import datetime, timedelta
import pathlib
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/issue255_mvp/prestage.py'
spec = importlib.util.spec_from_file_location('issue255_prestage', SCRIPT)


def fixture():
    def s(text):
        b = text.encode()
        return struct.pack('<Q', len(b)) + b
    # v3, one tensor, one metadata entry (alignment 32); data at aligned offset.
    header = b'GGUF' + struct.pack('<IQQ', 3, 1, 1)
    header += s('general.alignment') + struct.pack('<II', 4, 32)
    header += s('blk.24.attn_gate.weight') + struct.pack('<IQQIQ', 2, 32, 32, 0, 0)
    header += b'\0' * (-len(header) % 32)
    return header + bytes(range(256)) * 16, len(header)


class PrestageTests(unittest.TestCase):
    def module(self):
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_gguf_metadata_offsets_are_absolute_and_range_checked(self):
        m = self.module()
        blob, start = fixture()
        with tempfile.TemporaryDirectory() as directory:
            p = pathlib.Path(directory) / 'part.gguf'
            p.write_bytes(blob)
            entries = m.read_gguf_tensors(p)
            self.assertEqual(entries['blk.24.attn_gate.weight'], (start, 4096, 0))

    def test_native_fnv_matches_pinned_rpc_cache_key(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'sample'
            path.write_bytes(b'hello')
            binary = pathlib.Path(directory) / 'fnv'
            m.compile_fnv(binary)
            self.assertEqual(m.fnv_file(binary, path), 'a430d84680aabd0b')

    def test_stage_rejects_non_matching_member_and_existing_key(self):
        m = self.module()
        blob, _ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            member = root / 'part.gguf'
            member.write_bytes(blob)
            fnv = root / 'fnv'
            m.compile_fnv(fnv)
            cache = root / 'cache'
            with self.assertRaisesRegex(ValueError, 'identity'):
                m.stage(member, '0'*64, ['blk.24.attn_gate.weight'], cache, fnv)
            receipt = m.stage(member, hashlib.sha256(blob).hexdigest(), ['blk.24.attn_gate.weight'], cache, fnv)
            self.assertEqual(len(receipt), 1)
            self.assertEqual(receipt[0]['sha256'], hashlib.sha256(blob[-4096:]).hexdigest())
            with self.assertRaisesRegex(ValueError, 'already'):
                m.stage(member, hashlib.sha256(blob).hexdigest(), ['blk.24.attn_gate.weight'], cache, fnv)

    def test_identical_tensors_share_cache_key_with_distinct_inventory_rows(self):
        m = self.module()
        def s(x):
            b = x.encode()
            return struct.pack('<Q', len(b)) + b
        h = b'GGUF' + struct.pack('<IQQ', 3, 2, 1)
        h += s('general.alignment') + struct.pack('<II', 4, 32)
        for name, offset in [('blk.45.ssm_a', 0), ('blk.46.ssm_a', 32)]:
            h += s(name) + struct.pack('<IQIQ', 1, 8, 24, offset)
        h += b'\0' * (-len(h) % 32)
        blob = h + b'abcdefgh' + bytes(24) + b'abcdefgh'
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            member = root / 'part.gguf'
            member.write_bytes(blob)
            fnv = root / 'fnv'
            m.compile_fnv(fnv)
            result = m.stage(member, hashlib.sha256(blob).hexdigest(),
                             ['blk.45.ssm_a', 'blk.46.ssm_a'], root / 'cache', fnv)
            self.assertEqual(result[0]['fnv1a'], result[1]['fnv1a'])
            self.assertEqual(len(list((root / 'cache' / 'rpc').iterdir())), 1)


class StartupEvidenceAttributionTests(unittest.TestCase):
    """Lock each Task-1 summary claim to its own immutable request epoch."""

    def test_first_and_captured_requests_do_not_exchange_evidence(self):
        root = ROOT / 'docs/implementation/two-host-mvp-255/evidence'
        summary = json.loads((root / 'startup-observation.json').read_text())
        first, captured = summary['requests']['first'], summary['requests']['captured']
        raw_first = json.loads((root / '01/generation.json').read_text())
        raw_captured = json.loads((root / '01/generation-capture.json').read_text())

        for record, response, response_path, server_log in (
            (first, raw_first, '01/generation.json', '01/server-layer.log'),
            (captured, raw_captured, '01/generation-capture.json', '01/server-capture.log'),
        ):
            self.assertEqual(record['response_id'], response['id'])
            self.assertEqual(record['response_created_epoch_seconds'], response['created'])
            self.assertEqual(record['response_path'], response_path)
            self.assertEqual(record['server_log'], server_log)
            self.assertEqual(record['prompt_eval_ms'], response['timings']['prompt_ms'])
            self.assertEqual(record['generation_ms'], response['timings']['predicted_ms'])
            self.assertEqual(record['generation_tokens_per_second'],
                             response['timings']['predicted_per_second'])
            self.assertEqual(record['completion'], response['choices'][0]['message']['content'])
            self.assertEqual(record['stop_reason'], response['choices'][0]['finish_reason'])
            self.assertEqual(record['generated_tokens'], response['usage']['completion_tokens'])
            log = (root / server_log).read_text()
            self.assertIn(f"prompt eval time =    {record['prompt_eval_ms']:.2f} ms", log)
            self.assertIn(f"eval time =   {record['generation_ms']:.2f} ms", log)
        self.assertNotEqual(first['response_id'], captured['response_id'])
        self.assertLess(first['response_created_epoch_seconds'],
                        captured['response_created_epoch_seconds'])

        # The CSVs end before the second response even begins. Validate that
        # both hosts have nonzero samples during the first request's window.
        first_window = first['estimated_request_window_local_EDT']
        start = datetime.fromisoformat(first_window['start'])
        end = datetime.fromisoformat(first_window['end_exclusive'])
        self.assertEqual(start.utcoffset(), timedelta(hours=-4))
        response_second = datetime.fromtimestamp(raw_first['created'], start.tzinfo)
        self.assertEqual(end, response_second + timedelta(seconds=1))
        estimated_start = response_second - timedelta(milliseconds=
            raw_first['timings']['prompt_ms'] + raw_first['timings']['predicted_ms'])
        self.assertEqual(start, estimated_start)
        capture_start = datetime.fromisoformat(
            captured['estimated_request_window_local_EDT']['start'])
        self.assertEqual(capture_start, datetime.fromtimestamp(raw_captured['created'],
            start.tzinfo) - timedelta(milliseconds=raw_captured['timings']['prompt_ms']
                                                 + raw_captured['timings']['predicted_ms']))
        for host, path in (('01', '01/gpu01.csv'), ('04', '04/gpu04.csv')):
            self.assertEqual(first['gpu_samples'][host]['path'], path)
            rows = []
            for line in (root / path).read_text().splitlines():
                timestamp, memory, utilization = line.split(', ')
                at = datetime.strptime(timestamp, '%Y/%m/%d %H:%M:%S.%f').replace(
                    tzinfo=start.tzinfo)
                if start <= at < end:
                    rows.append((at, int(memory.removesuffix(' MiB')),
                                 int(utilization.removesuffix(' %'))))
            self.assertEqual(first['gpu_samples'][host]['request_window_sample_count'], len(rows))
            self.assertEqual(first['gpu_samples'][host]['request_window_nonzero_util_count'],
                             sum(util > 0 for _, _, util in rows))
            self.assertGreater(sum(util > 0 for _, _, util in rows), 0)
            self.assertLess(datetime.fromisoformat(first['gpu_samples'][host]['csv_end_local_EDT']),
                            datetime.fromtimestamp(raw_captured['created'], start.tzinfo))
        self.assertIsNone(captured['gpu_samples'])
        self.assertEqual(captured['gpu_samples_reason'], 'not captured in this request epoch')

        self.assertIsNone(first['request_network'])
        self.assertEqual(captured['request_network']['before_path'], '01/rpc-tcp-before.txt')
        self.assertEqual(captured['request_network']['after_path'], '01/rpc-tcp-after.txt')
        self.assertEqual(captured['request_network']['client_tcp_bytes_sent_delta'], 55896537)
        self.assertEqual(summary['captured_launch_local_backing']['trace'],
                         '04/rpc-cache-open.strace')
        self.assertNotIn('local_backing', first)
        self.assertNotIn('request', summary)
        self.assertNotIn('execution', summary)


if __name__ == '__main__':
    unittest.main()
