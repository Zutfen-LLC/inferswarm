"""#321: actual stock/composed build and assigned whole-bank graph seams."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT/'tools/moe-overlap/build.py'


class ComposedBuildTests(unittest.TestCase):
    def test_explicit_composed_build_has_separate_closure_and_provenance(self):
        binary = build_binary('--native-cache')
        self.assertEqual(binary.parent.name, 'build-cpu-native-cache')
        import json
        receipt = json.loads(binary.with_suffix('.build-manifest.json').read_text())
        self.assertEqual(receipt['role'], 'derived-moe-harness')
        self.assertEqual(receipt['rpc_closure'], 'native-cache-composed')
        self.assertEqual(receipt['executable_sha256'], __import__('hashlib').sha256(binary.read_bytes()).hexdigest())
        self.assertTrue(receipt['composition_sha256'])

    def test_stock_and_composed_objects_cannot_alias(self):
        composed = build_binary('--native-cache')
        stock = build_binary()
        self.assertNotEqual(stock.parent, composed.parent)
        # ggml.c bytes are identical in the two trees: flags/source closure,
        # rather than that single TU's digest, must distinguish these stamps.
        stamp='stamps/ggml__src__ggml.c.o.stamp'
        self.assertNotEqual((stock.parent/stamp).read_text(),(composed.parent/stamp).read_text())
        old=(composed.parent/stamp).stat().st_mtime_ns
        build_binary('--native-cache')
        self.assertEqual((composed.parent/stamp).stat().st_mtime_ns,old)
        import shutil
        rpc='ggml__src__ggml-rpc__ggml-rpc.cpp.o'
        target=composed.parent/rpc
        digest=__import__('hashlib').sha256(target.read_bytes()).hexdigest()
        shutil.copyfile(stock.parent/rpc,target)
        (composed.parent/'stamps'/(rpc+'.stamp')).write_text((stock.parent/'stamps'/(rpc+'.stamp')).read_text())
        build_binary('--native-cache')
        self.assertEqual(__import__('hashlib').sha256(target.read_bytes()).hexdigest(),digest)

    def test_composed_cuda_build_refuses(self):
        result=subprocess.run([sys.executable,str(BUILD),'--native-cache','--cuda'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CPU/RPC',result.stderr)



def build_binary(*options):
    cache = ROOT/'.cache/moe321'
    result = subprocess.run([sys.executable, str(BUILD), '--cache', str(cache),
                             '--jobs', '2', *options],
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise AssertionError(result.stderr[-4000:])
    return Path(next(line.split(' ', 1)[1] for line in result.stdout.splitlines()
                     if line.startswith('MOE_OVERLAP_BINARY ')))


def fixture(root):
    """Literal sparse Q8 blocks; no native quantizer or harness layout is used."""
    import hashlib
    import struct
    from inferswarm.operator.source import assigned_guard_bytes
    def text(s):
        b = s.encode(); return struct.pack('<Q', len(b)) + b
    tensors = {}
    for kind, k, rows in [('up', 2560, 640), ('gate', 2560, 640), ('down', 640, 2560)]:
        for shared in (False, True):
            count = 1 if shared else 12
            stride = rows * (k//32) * 34
            data = bytearray(stride * count)
            for eid in range(count):
                row = (31 if shared else eid) if kind == 'down' else 0
                col = 0 if shared or kind == 'down' else eid
                off = eid*stride + row*(k//32)*34 + (col//32)*34
                struct.pack_into('<e', data, off, 1/128)
                data[off+2+col%32] = 1 if shared or kind == 'down' else (eid+1 if kind == 'up' else 1+eid%3)
            name = f'blk.2.ffn_{kind}_{"shexp" if shared else "exps"}.weight'
            tensors[name] = (8, [k, rows] if shared else [k, rows, count], bytes(data))
    ranks = [4, 1, 11, 7, 0, 9, 3, 10, 2, 8, 5, 6]
    router = bytearray(2560*12*4)
    for eid, rank in enumerate(ranks):
        struct.pack_into('<f', router, eid*2560*4, rank/1270)
    tensors['blk.2.ffn_gate_inp.weight'] = (0, [2560,12], bytes(router))
    tensors['blk.2.ffn_gate_inp_shexp.weight'] = (0, [2560], bytes(2560*4))
    # Deliberately different file and in-memory ordering.
    order = sorted(tensors, reverse=True)
    header = b'GGUF'+struct.pack('<IQQ',3,len(order),1)
    header += text('general.architecture')+struct.pack('<I',8)+text('qwen4exp')
    offset = 0; rows = []
    for name in order:
        typ, shape, data = tensors[name]
        header += text(name)+struct.pack('<I',len(shape))+struct.pack('<'+'Q'*len(shape),*shape)+struct.pack('<IQ',typ,offset)
        offset += len(data)
        if '_exps.' in name:
            rows.append(dict(state_id=name,ggml_type=typ,shape=shape,encoded_bytes=len(data),
                             content_sha256=hashlib.sha256(data).hexdigest()))
    gguf = root/'block.gguf'
    with gguf.open('wb') as stream:
        stream.write(header+b'\0'*(-len(header)%32))
        for name in order: stream.write(tensors[name][2])
    guard = root/'assigned.txt'
    guard.write_bytes(assigned_guard_bytes({'tensors':sorted(rows,key=lambda r:r['state_id'])}))
    inputs=root/'inputs.f32'; inputs.write_bytes(struct.pack('<2560f',*([127.0]*2560)))
    return gguf, guard, inputs, tensors, ranks


class AssignedGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = build_binary('--native-cache')
        cls.temp = tempfile.TemporaryDirectory(prefix='moe321-graph-')
        cls.root=Path(cls.temp.name)
        cls.gguf, cls.guard, cls.inputs, cls.tensors, cls.ranks=fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_harness(self, *args):
        return subprocess.run([str(self.binary),'--gguf',str(self.gguf),'--layer','2',
            '--assigned-banks',str(self.guard),'--split','0','--secondary','rpc',
            '--rpc-endpoint','127.0.0.1:1','--threads','2','--warmup','0','--reps','1',
            '--inputs-file',str(self.inputs),*args],capture_output=True,text=True,timeout=60)

    def test_assignment_mismatch_refuses_before_connection(self):
        rows=self.guard.read_text().splitlines()
        variants=[rows[:-1],rows+rows[:1],rows+['extra 8 2560 640 12 1 20889600 '+'a'*64]]
        for field,value in ((0,'blk.2.up_slice'),(1,'0'),(2,'32'),(4,'11'),(6,'1'),(7,'0'*64)):
            fields=rows[0].split(); fields[field]=value
            variants.append([' '.join(fields),*rows[1:]])
        for number,rows in enumerate(variants):
            with self.subTest(case=number):
                bad=self.root/'bad.txt'; bad.write_text('\n'.join(rows)+'\n')
                result=self.run_harness('--assigned-banks',str(bad))
                self.assertNotEqual(result.returncode,0)
                self.assertIn('assigned whole-bank identity mismatch',result.stderr)

    def test_changed_source_bytes_refuse_before_connection(self):
        import shutil
        changed=self.root/'changed.gguf'; shutil.copyfile(self.gguf,changed)
        with changed.open('r+b') as stream:
            stream.seek(-1,2); stream.write(b'X')
        result=self.run_harness('--gguf',str(changed))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('assigned whole-bank identity mismatch',result.stderr)

    def test_incomplete_or_truncated_source_bank_refuses(self):
        import shutil
        import struct
        changed=self.root/'incomplete.gguf'
        shutil.copyfile(self.gguf,changed)
        with changed.open('r+b') as stream:
            header=stream.read(4096)
            name=b'blk.2.ffn_up_exps.weight'
            dimension=header.index(name)+len(name)+4+16
            stream.seek(dimension); stream.write(struct.pack('<Q',11))
        result=self.run_harness('--gguf',str(changed))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('gguf_init_from_file failed',result.stderr)
        shutil.copyfile(self.gguf,changed)
        with changed.open('r+b') as stream: stream.truncate(changed.stat().st_size-34)
        result=self.run_harness('--gguf',str(changed))
        self.assertNotEqual(result.returncode,0)
        self.assertRegex(result.stderr,'short read|gguf_init_from_file failed')

    def test_unsupported_assignment_configurations_refuse(self):
        for flags in (('--split','1'),('--secondary','cpu'),('--synthetic',)):
            with self.subTest(flags=flags):
                result=self.run_harness(*flags)
                self.assertEqual(result.returncode,2)
                self.assertIn('GGUF, RPC, split=0 complete banks',result.stderr)
        stock=build_binary()
        result=subprocess.run([str(stock),'--assigned-banks',str(self.guard),'--split','0'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('requires build.py --native-cache',result.stderr)

    def test_real_graph_cold_restart_cache_reuse_and_independent_mapping(self):
        import contextlib
        import hashlib
        import json
        import socket
        import time
        import numpy as np
        from tests.test_native_cache import Relay, child_limits, HEADER_SIZE
        worker = build_binary('--native-cache','--rpc-worker')
        stock = build_binary()
        cache=self.root/'rpc-cache'; cache.mkdir()
        @contextlib.contextmanager
        def serving():
            with socket.socket() as s:
                s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
            with tempfile.TemporaryFile(mode='w+') as log:
                proc=subprocess.Popen([str(worker),'--host','127.0.0.1','--port',str(port),
                    '--device','CPU','--threads','2','--cache-dir',str(cache)],
                    env=dict(os.environ,IS311_ASSIGNED=str(self.guard),GGML_NO_BACKTRACE='1'),
                    stdout=log,stderr=log,preexec_fn=child_limits)
                try:
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        if proc.poll() is not None:
                            log.seek(0); self.fail(log.read())
                        try:
                            with socket.create_connection(('127.0.0.1',port),timeout=.1): break
                        except OSError: time.sleep(.02)
                    else: self.fail('worker readiness deadline')
                    relay=Relay(port)
                    try: yield relay
                    finally: relay.close()
                finally:
                    proc.terminate()
                    try: proc.wait(5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait(5)
        runs=[]
        for label in ('cold','restart'):
            case=self.root/label
            with serving() as relay:
                if label == 'cold':
                    mismatch=subprocess.run([str(stock),'--gguf',str(self.gguf),
                        '--split','0','--secondary','rpc','--rpc-endpoint',f'127.0.0.1:{relay.port}',
                        '--threads','2','--warmup','0','--reps','1'],capture_output=True,text=True,timeout=30,
                        env=dict(os.environ,GGML_NO_BACKTRACE='1'),preexec_fn=child_limits)
                    self.assertNotEqual(mismatch.returncode,0)
                    self.assertIn('RPC server version mismatch: 7.0.0',mismatch.stderr)
                result=self.run_harness('--rpc-endpoint',f'127.0.0.1:{relay.port}',
                    '--self-check-negative','--dump-reference-case',str(case))
                self.assertEqual(result.returncode,0,result.stderr[-4000:])
            self.assertEqual(relay.errors,[])
            weights=[r for r in relay.requests if r.get('tensor') in self.tensors and '_exps.' in r['tensor']]
            sets=[r for r in weights if r['cmd']==6]
            hashes=[r for r in weights if r['cmd']==7]
            self.assertEqual(len(hashes),3)
            self.assertEqual(sum(r['size']-HEADER_SIZE for r in sets),0 if label=='restart' else 3*20889600)
            self.assertEqual(len(sets),0 if label=='restart' else 3)
            for row in weights:
                typ,shape,data=self.tensors[row['tensor']]
                self.assertEqual(row['offset'],0)
                self.assertEqual(row['type'],typ)
                self.assertEqual(row['shape'],shape+[1])
                self.assertEqual(row['sha256'],hashlib.sha256(data).hexdigest())
                self.assertEqual(row['length'],len(data))
                self.assertEqual((cache/row['key']).read_bytes(),data)
            report=json.loads((case/'run.json').read_text())
            self.assertTrue(report['negative_control']['comparator_rejected'])
            self.assertEqual(report['config']['upload_boundary'],'assigned-whole-model-banks')
            self.assertEqual(report['reps'][0]['k_cpu_real'],0)
            self.assertEqual(report['reps'][0]['k_sec_real'],10)
            schedule=subprocess.run([sys.executable,str(ROOT/'tools/moe-overlap/check_scheduling.py'),str(case)],capture_output=True,text=True)
            self.assertEqual(schedule.returncode,0,schedule.stdout+schedule.stderr)
            numerical=subprocess.run([sys.executable,str(ROOT/'tools/moe-overlap/check_reference.py'),str(case),'--gguf',str(self.gguf)],capture_output=True,text=True)
            self.assertNotEqual(numerical.returncode,0)
            self.assertEqual(report['config']['reference_secondary_mode'],'rpc-remote-unverified')
            self.assertIn('unsupported/mismatched backend reference mode',numerical.stdout)
            # Independent source bytes and expert-ID oracle. Expected IDs come
            # from literal router ranks, never the harness's partition/export.
            expected_ids=np.argsort(self.ranks)[::-1][:10]
            np.testing.assert_array_equal(np.fromfile(case/'rep-0-ids.i32',dtype='<i4'),expected_ids)
            spec=importlib.util.spec_from_file_location('operand_reference',ROOT/'tools/moe-overlap/operand_reference.py')
            oracle=importlib.util.module_from_spec(spec); spec.loader.exec_module(oracle)
            logits=np.asarray(sorted(self.ranks,reverse=True)[:10],dtype=np.float32)/10
            rw=np.exp(logits-np.max(logits)); rw/=rw.sum()
            def load(kind,eid):
                if kind=='shared_gate': return self.tensors['blk.2.ffn_gate_inp_shexp.weight'][2]
                suffix='shexp' if eid is None else 'exps'
                typ,shape,data=self.tensors[f'blk.2.ffn_{kind}_{suffix}.weight']
                stride=shape[0]*shape[1]//32*34
                return data if eid is None else data[eid*stride:(eid+1)*stride]
            expected,mass=oracle.block(np.full((1,2560),127,dtype=np.float32),expected_ids.reshape(1,10),rw.reshape(1,10),load,
                split=0,n_ff=640,cpu_mode=report['config']['reference_cpu_mode'],secondary_mode=report['config']['reference_cpu_mode'])
            actual=np.fromfile(case/'rep-0-serial.f32',dtype='<f4').reshape(1,2560)
            comparison=oracle.compare(actual,expected['sec']+expected['shared'],mass['sec']+mass['shared'])
            self.assertTrue(comparison['pass'],comparison)
            self.assertGreater(float(actual[0,31]),0)  # local shared branch
            self.assertEqual((case/'rep-0-serial.f32').read_bytes(),(case/'rep-0-overlap.f32').read_bytes())
            runs.append((case/'rep-0-serial.f32').read_bytes())
            if os.environ.get('MOE_NATIVE_CACHE_RESULTS'):
                import shutil
                destination=Path(os.environ['MOE_NATIVE_CACHE_RESULTS'])
                destination.mkdir(parents=True,exist_ok=True)
                shutil.copytree(case,destination/label)
                (destination/(label+'-wire.json')).write_text(json.dumps({
                    'requests':relay.requests,'server_response_wire_bytes':relay.received,
                    'unchanged_weight_set_payload':sum(r['size']-HEADER_SIZE for r in sets),
                    'scheduling':json.loads(schedule.stdout),'numerical':json.loads(numerical.stdout),
                    'independent_fixture_mapping':comparison},indent=2)+'\n')
                shutil.copyfile(self.binary.with_suffix('.build-manifest.json'),destination/'harness.build-manifest.json')
                shutil.copyfile(worker.with_suffix('.build-manifest.json'),destination/'worker.build-manifest.json')
                shutil.copyfile(self.guard,destination/'assigned.txt')
                shutil.copyfile(self.inputs,destination/'inputs.f32')
        self.assertEqual(*runs)
