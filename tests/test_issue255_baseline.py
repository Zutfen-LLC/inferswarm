"""CPU-only regression for the isolated #255 single-host operator."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'tools/issue255_mvp/baseline.py'

def operator():
    spec = importlib.util.spec_from_file_location('issue255_baseline', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class BaselineTests(unittest.TestCase):
    def test_launch_is_single_host_cuda_and_exact_settings(self):
        b = operator()
        command = b.server_command()
        self.assertIn('-ngl 8 -cmoe', command)
        self.assertIn('-c 1024 -np 1 --no-warmup', command)
        self.assertNotIn('--rpc', command)
        self.assertNotIn('RPC0', command)
        self.assertEqual(b.m.PAYLOAD['temperature'], 0)
        self.assertEqual(b.m.PAYLOAD['seed'], 42)
        self.assertEqual(b.m.PAYLOAD['max_tokens'], 64)
        self.assertTrue(b.m.PAYLOAD['stream_options']['include_usage'])

    def test_existing_lease_refuses_launch_and_is_not_cleaned(self):
        b = operator()
        with tempfile.TemporaryDirectory() as tmp:
            b.ROOT = tmp
            marker = Path(tmp, 'task3-active')
            marker.mkdir()
            (marker / 'token').write_text('other\n')
            calls = []
            def local(host, cmd, **kw):
                calls.append(cmd)
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if p.returncode: raise RuntimeError(p.stderr)
                return p.stdout
            state = {'token': 'ours', 'owned': {}}
            with mock.patch.object(b.m, 'remote', side_effect=local):
                with self.assertRaises(RuntimeError): b.acquire(state)
                self.assertEqual(b.stop_owned(state), {})
            self.assertEqual((marker / 'token').read_text(), 'other\n')
            self.assertEqual(len(calls), 1)

    def test_cleanup_refuses_recycled_pid_and_preserves_lease(self):
        b = operator()
        with tempfile.TemporaryDirectory() as tmp:
            b.ROOT = tmp
            marker = Path(tmp, 'task3-active')
            marker.mkdir()
            (marker / 'token').write_text('ours\n')
            (Path(tmp) / 'server.pid').write_text('123:0\n')
            state = {'token': 'ours', 'owned': {'server.pid': (123, 0)}, 'leased': True}
            def local(host, cmd, **kw):
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if p.returncode: raise RuntimeError(p.stderr)
                return p.stdout
            with mock.patch.object(b.m, 'remote', side_effect=local):
                result = b.stop_owned(state)
            self.assertIn(result['server.pid'], ('already-exited', 'start-time mismatch'))
            if result['server.pid'] == 'start-time mismatch':
                self.assertTrue(marker.exists())
                self.assertEqual((Path(tmp) / 'server.pid').read_text(), '123:0\n')

    def test_shutdown_waits_for_signaled_process_to_exit_before_readback(self):
        b = operator()
        def stat(state): return '123 (llama-server) ' + ' '.join([state] + ['0']*18 + ['1'])
        replies = iter([stat('R'), stat('Z')])
        with mock.patch.object(b.m, 'remote', side_effect=lambda *a, **kw: next(replies)), \
             mock.patch.object(b.time, 'sleep') as sleep:
            self.assertTrue(b.wait_for_exit(123, 1, timeout=3))
        sleep.assert_called_once()

    def test_cpu_ci_planner_workflow_and_retention_register_every_issue255_module(self):
        import sys
        root = SOURCE.parents[2]
        sys.path.insert(0, str(root / 'scripts'))
        try:
            import plan_ci
            modules = ('test_issue255_mvp', 'test_issue255_measure', 'test_issue255_baseline')
            workflow = (root / '.github/workflows/ci.yml').read_text()
            audit = json.loads((root / 'docs/ci/test-retention-audit.json').read_text())['modules']
            group = plan_ci.GROUP_TEST_MODULES['issue-99-103']
            for module in modules:
                self.assertEqual(group.count(module), 1)
                self.assertEqual(workflow.count('tests.' + module + ' '), 1)
                self.assertEqual(audit[module]['group'], 'issue-99-103')
                self.assertEqual(audit[module]['disposition'], 'retain')
            for path in ('tools/issue255_mvp/baseline.py', 'tools/issue255_mvp/measure.py',
                         'docs/implementation/two-host-mvp-255/evidence/task3-baseline/summary.json'):
                self.assertIn('issue-99-103', plan_ci.classify_path(path)[0])
                self.assertTrue(plan_ci.classify_path(path)[1])
        finally:
            sys.path.remove(str(root / 'scripts'))

    def test_baseline_manifest_binds_raw_and_operator_sources(self):
        import hashlib
        root = SOURCE.parents[2]
        base = root / 'docs/implementation/two-host-mvp-255/evidence/task3-baseline'
        manifest = json.loads((base / 'MANIFEST.json').read_text())
        paths = {row['path'] for row in manifest['entries']}
        self.assertIn('tools/issue255_mvp/baseline.py', paths)
        self.assertIn('tests/test_issue255_baseline.py', paths)
        self.assertIn('docs/implementation/two-host-mvp-255/evidence/task3-baseline/stream.json', paths)
        self.assertIn('docs/implementation/two-host-mvp-255/evidence/task3-baseline/shutdown-verified.json', paths)
        self.assertEqual(len(paths), len(manifest['entries']))
        for row in manifest['entries']:
            data = (root / row['path']).read_bytes()
            self.assertEqual(len(data), row['bytes'], row['path'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'], row['path'])
        ancestor = manifest['ancestor']
        self.assertEqual(hashlib.sha256((root / ancestor['path']).read_bytes()).hexdigest(),
                         ancestor['sha256'])

    def test_retained_baseline_is_one_request_and_no_rpc(self):
        b = operator()
        root = SOURCE.parents[2] / 'docs/implementation/two-host-mvp-255/evidence/task3-baseline'
        if not (root / 'summary.json').exists(): self.skipTest('physical baseline not yet captured')
        s = json.loads((root / 'summary.json').read_text())
        stream = json.loads((root / 'stream.json').read_text())
        self.assertEqual(s['response'], stream['result'])
        self.assertEqual(stream['payload'], b.m.PAYLOAD)
        self.assertEqual(s['network']['client_participant_rpc_bytes'], 0)
        self.assertEqual(s['response']['stop_reason'], 'stop')
        self.assertGreater(s['gpu']['matching_pid_nonzero_util_samples'], 0)
        self.assertFalse(json.loads((root / 'shutdown-verified.json').read_text())['port_listening'])

if __name__ == '__main__': unittest.main()
