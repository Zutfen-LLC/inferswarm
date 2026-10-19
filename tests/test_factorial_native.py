"""Actual CPU/RPC factorial graphs, immutable fixtures, and full replay checks."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/'tools/native-moe-overlap'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeFactorial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='factorial-native-')
        cls.root = Path(cls.temp.name)
        retained = os.environ.get('IS_FACTORIAL_BUILD')
        if retained:
            cls.binary = Path(retained)
        else:
            builder = load('factorial_native_builder', HERE/'factorial-build.py')
            pin = builder.base.base.pin.pin
            cache = Path(os.environ.get('MOE_OVERLAP_CACHE', cls.root/'pin'))
            cache.mkdir(parents=True, exist_ok=True)
            archive = Path(os.environ.get('MOE_OVERLAP_TARBALL', cache/'pin.tar.gz'))
            if not archive.is_file():
                pin.ensure_source(cache)
            cls.binary = Path(builder.build(archive, cls.root/'build')['build_directory'])
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        cls.log = (cls.root/'worker.log').open('w')
        cls.worker = subprocess.Popen([str(cls.binary/'bin/rpc-worker'), '--host','127.0.0.1',
            '--port',str(port),'--device','CPU','--threads','2'],stdout=cls.log,stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+5
            while True:
                try:
                    with socket.create_connection(('127.0.0.1',port),.1): break
                except OSError:
                    if cls.worker.poll() is not None or time.monotonic()>=deadline: raise
                    time.sleep(.02)
            cls.output = cls.root/'result'; cls.output.mkdir()
            with (cls.output/'stdout.jsonl').open('w') as out, (cls.output/'stderr.log').open('w') as err:
                result = subprocess.run([str(cls.binary/'bin/native-factorial-bench'),
                    '--endpoint',f'127.0.0.1:{port}','--work-dir',str(cls.output/'native'),
                    '--threads','2','--small-test','--quick'],stdout=out,stderr=err,timeout=30)
            if result.returncode:
                raise AssertionError((cls.output/'stderr.log').read_text()[-4000:])
        finally:
            cls.worker.terminate(); cls.worker.wait(timeout=5); cls.log.close()
        cls.records = [json.loads(line) for line in (cls.output/'stdout.jsonl').read_text().splitlines()]
        cls.checker = load('factorial_native_checker', HERE/'factorial_check.py')
        cls.helper = cls.root/'helper.so'
        subprocess.run(['c++','-O3','-std=c++17','-shared','-fPIC','-mf16c','-ffp-contract=off',
            str(HERE/'layer7_arithmetic.cpp'),'-o',str(cls.helper)],check=True,timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_four_cells_full_output_and_sensitive_controls(self):
        result = self.checker.analyze_replays(self.output,self.helper,small_test_grid=True)
        self.assertEqual(result['status'],'cpu-loopback-match')
        self.assertEqual(result['measured_factorial_pairs'],16)
        self.assertEqual(result['unique_banks_read'],6)
        self.assertTrue(all(r['timed_binding']=='match' and r['sensitive'] for r in result['profiles']))
        self.assertEqual({r['hot_count'] for r in result['profiles']},{5,10})
        self.assertFalse(result['numerical_qualification'])

    def test_fixture_routing_matches_retained_warmed_producer(self):
        # Retained 4a703fdc warmed stdout row identities; independent of geometry.
        expected = {
            (1,0):'0cdecdb5b1c3ba5a53338c73d84539660f0f3a60cc474a3b05161b441708ac55',
            (1,1):'fa3d285bd080461d296a73f9fee246b2840ae8fb24fa9c1df585e11dd0312fa4',
            (4,0):'35e471f8ceef3c4f0f117650a5828540a9389f4031dab670bcedd1238c296609',
            (4,1):'a9ce2c2657755f3c5534e01c3b954dd956495d5d8eef86179f69afaa945f547d'}
        rows = [r for r in self.records if r['type']=='factorial-pair']
        self.assertTrue(all(r['routing_sha256']==expected[r['tokens'],r['pair']] for r in rows))
        self.assertTrue(all(r['B']['rpc']['set_acks']==3 and r['B']['rpc']['graph_recompute']==1 for r in rows))

    def test_shared_banks_not_duplicated_into_replays(self):
        files = list((self.output/'native').rglob('*.q8_0.bin'))
        self.assertEqual(len(files),6)
        self.assertTrue(all('banks' in p.parts for p in files))
        for row in (r for r in self.records if r['type']=='factorial-pair' and not r['warmup'] and r['hot']==10):
            directory = self.output/'native/replays'/f"t{row['tokens']}-{row['case']}-p{row['pair']}-{row['factorial_arm']}"
            base = json.loads((directory/'capture/manifest.json').read_text())
            self.assertEqual(base['cold_count'],0)
            self.assertNotIn('B.cold.ids',base['tensors'])
            self.assertNotIn('B.cold.weights',base['tensors'])


if __name__ == '__main__':
    unittest.main()
