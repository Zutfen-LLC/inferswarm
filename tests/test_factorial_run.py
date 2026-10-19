"""CPU-only supervisor lifecycle, fixed-grid and future launcher contract tests."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT/'tools/native-moe-overlap'
spec = importlib.util.spec_from_file_location('factorial_run',TOOLS/'factorial_run.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class FactorialSupervisor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def executable(self, name, body):
        path = self.root/name; path.write_text('#!'+sys.executable+'\n'+body); path.chmod(0o700)
        return str(path)

    def provenance(self, native_body):
        native = self.executable('native',native_body)
        worker = self.executable('worker','''import argparse,socket
p=argparse.ArgumentParser(); p.add_argument('--host'); p.add_argument('--port',type=int); p.add_argument('--device'); p.add_argument('--threads'); a=p.parse_args()
s=socket.socket(); s.bind((a.host,a.port)); s.listen()
while True:
 c,_=s.accept(); c.close()
''')
        return dict(portable_fixture_build=False,roles={
            'native-factorial-bench':dict(executable=native,executable_sha256=runner.digest(native)),
            'rpc-worker':dict(executable=worker,executable_sha256=runner.digest(worker))})

    def execute(self, body='print("{}")', **kwargs):
        provenance = self.provenance(body)
        with mock.patch.object(runner,'candidate',return_value=provenance), \
             mock.patch.object(runner,'validate_records',return_value=([{}]*16,[dict(warmup=False)]*4+[dict(warmup=True)]*2,'cpu-loopback')):
            return runner.run('unused',self.root/'result',loopback=True,small_test=True,quick=True,timeout=2,threads=1,**kwargs)

    def test_success_retains_receipt_and_reaps_worker(self):
        result = self.execute()
        self.assertTrue(result['execution_complete']); self.assertFalse(result['timing_comparison_valid'])
        self.assertTrue(result['offline_analysis_required']); self.assertTrue(result['native_reaped'])
        self.assertTrue(result['worker']['reaped']); self.assertFalse(Path('/proc',str(result['worker']['pid'])).exists())
        self.assertIn('--quick',result['command']); self.assertIn('--small-test',result['command'])
        self.assertEqual(result['command'][result['command'].index('--work-dir')+1],str(self.root/'result/native'))
        saved=json.loads((self.root/'result/run.json').read_text())
        self.assertEqual(saved['artifacts']['stdout.jsonl'],runner.digest(self.root/'result/stdout.jsonl'))

    def test_native_failure_is_terminal_and_worker_reaped(self):
        result=self.execute('raise SystemExit(9)')
        self.assertFalse(result['execution_complete']); self.assertIn('native exit 9',result['error'])
        self.assertTrue(result['worker']['reaped']); self.assertTrue(result['native_reaped'])

    def test_native_timeout_kills_reaps_and_retains_partial_output(self):
        provenance=self.provenance('import time\nprint("partial",flush=True)\ntime.sleep(30)')
        with mock.patch.object(runner,'candidate',return_value=provenance):
            result=runner.run('unused',self.root/'result',loopback=True,small_test=True,quick=True,timeout=.15,threads=1)
        self.assertFalse(result['execution_complete']); self.assertIn('deadline',result['error'])
        self.assertTrue(result['native_reaped']); self.assertTrue(result['worker']['reaped'])
        self.assertEqual((self.root/'result/stdout.jsonl').read_text().strip(),'partial')
        self.assertFalse(Path('/proc',str(result['native_pid'])).exists())

    def test_storage_overrun_stops_before_accepting_result(self):
        with mock.patch.object(runner,'EVIDENCE_CAP',8):
            result=self.execute('import time\nprint("x"*100,flush=True)\ntime.sleep(30)')
        self.assertFalse(result['execution_complete']); self.assertIn('evidence cap',result['error'])
        self.assertTrue(result['native_reaped']); self.assertTrue(result['worker']['reaped'])

    def test_supervisor_signal_reaps_both_owned_groups(self):
        result=self.execute('import os,signal,time\nos.kill(os.getppid(),signal.SIGTERM)\ntime.sleep(30)')
        self.assertFalse(result['execution_complete']); self.assertIn('received signal',result['error'])
        self.assertTrue(result['native_reaped']); self.assertTrue(result['worker']['reaped'])
        self.assertFalse(Path('/proc',str(result['native_pid'])).exists())

    def test_invalid_budget_mode_rejected_before_candidate_or_output(self):
        cases=[dict(threads=15),dict(timeout=301),dict(timeout=float('nan')),dict(quick=True),
               dict(loopback=True,comparison_mode='cpu-cuda'),dict(small_test=True,comparison_mode='cpu-cuda')]
        with mock.patch.object(runner,'candidate') as candidate:
            for case in cases:
                with self.subTest(case=case),self.assertRaises(ValueError):
                    opts=dict(endpoint='127.0.0.1:50060'); opts.update(case)
                    runner.run('unused',self.root/'result',**opts)
            candidate.assert_not_called()
        self.assertFalse((self.root/'result').exists())

    def test_refuses_inherited_transport_or_weight_overrides(self):
        for key in ('IS_FACTORIAL_TRANSPORT','IS314_HOT_SPEC','IS311_ASSIGNED'):
            with self.subTest(key=key),mock.patch.dict(os.environ,{key:'unsafe'}),self.assertRaises(ValueError):
                runner.run('unused',self.root/'result',endpoint='127.0.0.1:1')

    def test_existing_output_preserved(self):
        (self.root/'result').mkdir(); (self.root/'result/keep').write_text('old')
        with mock.patch.object(runner,'candidate',return_value=self.provenance('print("{}")')), \
             self.assertRaises(FileExistsError):
            runner.run('unused',self.root/'result',loopback=True)
        self.assertEqual((self.root/'result/keep').read_text(),'old')

    def test_candidate_rejects_wrong_pin_before_executable(self):
        path=self.root/'receipt.json'
        path.write_text(json.dumps(dict(schema='factorial-candidate-build/1',native_commit='wrong')))
        with self.assertRaisesRegex(ValueError,'native/archive/protocol'):
            runner.candidate(path)


class FutureLauncherContract(unittest.TestCase):
    def test_caps_ownership_and_no_checker_during_worker(self):
        text=(TOOLS/'factorial-cpu05.sh').read_text()
        subprocess.run(['bash','-n',str(TOOLS/'factorial-cpu05.sh')],check=True)
        self.assertIn('900 bash -c',text); self.assertIn('--threads 14 --timeout 300',text)
        self.assertEqual(text.count('-N -L '),1); self.assertNotIn(' -R ',text)
        self.assertIn('owned_worker_absent',text); self.assertIn('owned_listener_absent',text)
        self.assertIn('start_attempted=1',text); self.assertNotIn('factorial_check.py',text)
        self.assertLess(text.index('900 bash -c'),text.index('ssh -M -S'))

    def test_accepted_worker_and_ownership_protocol_unchanged(self):
        old=(TOOLS/'layer7_remote.py').read_text(); new=(TOOLS/'factorial_remote.py').read_text()
        for constant in ('WORKER =','WORKER_SHA =','GPU_UUID =','TOKEN_KEY ='):
            self.assertEqual(next(s for s in old.splitlines() if s.startswith(constant)),
                             next(s for s in new.splitlines() if s.startswith(constant)))
        for name in ('identity','tagged','members','owned_members','spawn_owned','terminate_owned','main'):
            import ast
            old_tree=ast.parse(old); new_tree=ast.parse(new)
            get=lambda tree:next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(get(old_tree)),ast.dump(get(new_tree)))
        self.assertIn("'360',WORKER",new); self.assertIn('MIN_FREE_MIB = 2048',new)


if __name__=='__main__': unittest.main()
