"""CPU-only regression for the isolated #255 single-host operator."""
import importlib.util
import json

from pathlib import Path
import subprocess
import sys
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
            self.assertIn(result['server.pid'], ({'signal': 'already-exited', 'exit': 'absent'},
                                                  'start-time mismatch'))
            if result['server.pid'] == 'start-time mismatch':
                self.assertTrue(marker.exists())
                self.assertEqual((Path(tmp) / 'server.pid').read_text(), '123:0\n')
            else:
                self.assertEqual(result['lease'], 'released')
                self.assertFalse(marker.exists())

    def test_shutdown_waits_for_signaled_process_to_exit_before_readback(self):
        b = operator()
        def stat(state): return '123 (llama-server) ' + ' '.join([state] + ['0']*18 + ['1'])
        replies = iter([stat('R'), stat('Z')])
        with mock.patch.object(b.m, 'remote', side_effect=lambda *a, **kw: next(replies)), \
             mock.patch.object(b.time, 'sleep') as sleep:
            self.assertTrue(b.wait_for_exit(123, 1, timeout=3))
        sleep.assert_called_once()

    def test_cleanup_keeps_both_records_and_lease_until_server_exits(self):
        self.assert_cleanup_timeout_then_release('server.pid')

    def test_cleanup_keeps_both_records_and_lease_until_sampler_exits(self):
        self.assert_cleanup_timeout_then_release('sampler.pid')

    def assert_cleanup_timeout_then_release(self, stubborn):
        b = operator()
        children = {}
        with tempfile.TemporaryDirectory() as tmp:
            b.ROOT = tmp
            lease = Path(tmp, 'task3-active')
            lease.mkdir()
            (lease / 'token').write_text('ours\n')
            for name in ('server.pid', 'sampler.pid'):
                code = ('import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                        'print("ready",flush=True); time.sleep(60)' if name == stubborn else
                        'import time; print("ready",flush=True); time.sleep(60)')
                child = subprocess.Popen([sys.executable, '-u', '-c', code], stdout=subprocess.PIPE, text=True)
                children[name] = child
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            owned = {name: (p.pid, int(Path(f'/proc/{p.pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]))
                     for name, p in children.items()}
            for name, (pid, start) in owned.items():
                (Path(tmp) / name).write_text(f'{pid}:{start}\n')
            state = {'token': 'ours', 'owned': owned.copy(), 'leased': True}
            tunnel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            state['tunnel'] = tunnel
            def local(host, cmd, **kw):
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if p.returncode: raise RuntimeError(p.stderr)
                return p.stdout
            try:
                with mock.patch.object(b.m, 'remote', side_effect=local), mock.patch.object(b.time, 'sleep'):
                    result = b.stop_owned(state)
                self.assertEqual(result['lease'], 'retained-incomplete')
                self.assertEqual(result[stubborn]['exit'], 'timeout')
                self.assertTrue(lease.exists())
                self.assertEqual(state['owned'], owned)
                self.assertTrue(state['leased'])
                for name, (pid, start) in owned.items():
                    self.assertEqual((Path(tmp) / name).read_text(), f'{pid}:{start}\n')
                self.assertIsNone(children[stubborn].poll())
                self.assertIsNotNone(tunnel.poll())
                with mock.patch.object(b.m, 'remote', side_effect=local):
                    with self.assertRaises(RuntimeError):
                        b.acquire({'token': 'next-invocation', 'owned': {}})
                for child in children.values():
                    if child.poll() is None: child.kill()
                    child.wait(timeout=5)
                with mock.patch.object(b.m, 'remote', side_effect=local):
                    result = b.stop_owned(state)
                self.assertEqual(result['lease'], 'released')
                self.assertFalse(lease.exists())
                self.assertFalse(state['owned'])
                for name in owned: self.assertFalse((Path(tmp) / name).exists())
            finally:
                if tunnel.poll() is None: tunnel.kill()
                tunnel.wait(timeout=5)
                for child in children.values():
                    if child.poll() is None: child.kill()
                    child.wait(timeout=5)
                    child.stdout.close()

    def test_cleanup_refuses_live_start_mismatch_without_signaling(self):
        b = operator()
        with tempfile.TemporaryDirectory() as tmp:
            b.ROOT = tmp
            marker = Path(tmp, 'task3-active')
            marker.mkdir()
            (marker / 'token').write_text('ours\n')
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
            try:
                start = int(Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]) + 1
                (Path(tmp) / 'server.pid').write_text(f'{child.pid}:{start}\n')
                state = {'token': 'ours', 'owned': {'server.pid': (child.pid, start)}, 'leased': True}
                def local(host, cmd, **kw):
                    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if p.returncode: raise RuntimeError(p.stderr)
                    return p.stdout
                with mock.patch.object(b.m, 'remote', side_effect=local):
                    result = b.stop_owned(state)
                self.assertEqual(result['server.pid'], 'start-time mismatch')
                self.assertIsNone(child.poll())
                self.assertTrue(marker.exists())
                self.assertEqual((Path(tmp) / 'server.pid').read_text(), f'{child.pid}:{start}\n')
            finally:
                child.kill()
                child.wait(timeout=5)

    def test_normal_cleanup_releases_only_after_two_term_exits(self):
        b = operator()
        with tempfile.TemporaryDirectory() as tmp:
            b.ROOT = tmp
            lease = Path(tmp, 'task3-active')
            lease.mkdir()
            (lease / 'token').write_text('ours\n')
            children = {}
            try:
                for name in ('server.pid', 'sampler.pid'):
                    p = subprocess.Popen([sys.executable, '-u', '-c',
                                          'import time; print("ready",flush=True); time.sleep(60)'],
                                         stdout=subprocess.PIPE, text=True)
                    children[name] = p
                    self.assertEqual(p.stdout.readline().strip(), 'ready')
                owned = {name: (p.pid, int(Path(f'/proc/{p.pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]))
                         for name, p in children.items()}
                for name, (pid, start) in owned.items():
                    (Path(tmp) / name).write_text(f'{pid}:{start}\n')
                state = {'token': 'ours', 'owned': owned.copy(), 'leased': True}
                def local(host, cmd, **kw):
                    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if p.returncode: raise RuntimeError(p.stderr)
                    return p.stdout
                with mock.patch.object(b.m, 'remote', side_effect=local):
                    result = b.stop_owned(state)
                self.assertEqual(result['lease'], 'released')
                self.assertEqual({name for name in owned if result[name]['exit'] in ('absent', 'zombie')}, set(owned))
                self.assertFalse(lease.exists())
                self.assertFalse(state['owned'])
                for name in owned: self.assertFalse((Path(tmp) / name).exists())
            finally:
                for child in children.values():
                    if child.poll() is None: child.kill()
                    child.wait(timeout=5)
                    child.stdout.close()

    def test_remote_cleanup_failure_still_reaps_tunnel_and_retains_lease(self):
        b = operator()
        tunnel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        state = {'token': 'ours', 'owned': {'server.pid': (123, 456)}, 'leased': True, 'tunnel': tunnel}
        try:
            with mock.patch.object(b.m, 'remote', side_effect=RuntimeError('offline failure')):
                result = b.stop_owned(state)
            self.assertEqual(result['lease'], 'retained-incomplete')
            self.assertEqual(state['owned'], {'server.pid': (123, 456)})
            self.assertTrue(state['leased'])
            self.assertIsNotNone(tunnel.poll())
        finally:
            if tunnel.poll() is None: tunnel.kill()
            tunnel.wait(timeout=5)

    def test_main_reports_incomplete_cleanup_without_shutdown_success(self):
        b = operator()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp, 'new-output')
            def fake_launch(state):
                state.update({'leased': True, 'owned_original_server': (123, 456)})
            with mock.patch.object(b, 'launch', side_effect=fake_launch), \
                 mock.patch.object(b, 'capture', return_value={'response': {
                     'response_id': 'offline', 'generated_tokens': 1, 'stop_reason': 'stop'}}), \
                 mock.patch.object(b, 'stop_owned', return_value={'lease': 'retained-incomplete'}), \
                 mock.patch.object(b, 'verify_shutdown') as verify, \
                 mock.patch.object(sys, 'argv', ['baseline.py', '--output', str(output)]):
                with self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
                    b.main()
            self.assertEqual(json.loads((output / 'cleanup.json').read_text())['lease'], 'retained-incomplete')
            verify.assert_not_called()

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
            data = (subprocess.check_output(['git', 'show', f'7026ca82cabe6fc16bc1d68c33d6d309a265150b:{row["path"]}'], cwd=root)
                    if row['path'] in ('tools/issue255_mvp/baseline.py', 'tests/test_issue255_baseline.py')
                    else (root / row['path']).read_bytes())
            self.assertEqual(len(data), row['bytes'], row['path'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'], row['path'])
        ancestor = manifest['ancestor']
        self.assertEqual(hashlib.sha256(subprocess.check_output(['git', 'show',
                         f'{ancestor["commit"]}:{ancestor["path"]}'], cwd=root)).hexdigest(),
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
