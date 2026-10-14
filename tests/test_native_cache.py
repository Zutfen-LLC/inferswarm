"""#311 focused native cache regressions; small CPU tensors, loopback, no model/GPU.

The relay retains only descriptor-sized metadata and streams <=64 KiB payloads.
Verification GET traffic is accounted separately from weight acquisition.
"""
from __future__ import annotations

import contextlib
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import socket
import struct
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER_SIZE = 352  # packed tensor(296), offset, FNV, expected length, SHA-256


def child_limits():
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def read_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise EOFError
        result.extend(part)
    return bytes(result)


class Relay:
    def __init__(self, worker_port, interrupt=False):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        self.listener.settimeout(.1)
        self.worker_port, self.interrupt = worker_port, interrupt
        self.requests, self.sockets, self.errors = [], [], []
        self.received = 0
        self.stopping = threading.Event()
        self.partial = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def reverse(self, server, client):
        try:
            while not self.stopping.is_set():
                data = server.recv(65536)
                if not data:
                    break
                self.received += len(data)
                client.sendall(data)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)

    def serve(self):
        while not self.stopping.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            server = socket.create_connection(('127.0.0.1', self.worker_port), timeout=3)
            server.settimeout(None)
            self.sockets.extend([client, server])
            reverse = threading.Thread(target=self.reverse, args=(server, client), daemon=True)
            reverse.start()
            try:
                while not self.stopping.is_set():
                    header = read_exact(client, 9)
                    cmd, size = struct.unpack('<BQ', header)
                    if size > 40 << 20:
                        raise ValueError('fixture frame budget exceeded')
                    row = {'cmd': cmd, 'size': size}
                    self.requests.append(row)
                    server.sendall(header)
                    left, prefix = size, bytearray()
                    while left:
                        data = client.recv(min(left, 65536))
                        if not data:
                            raise EOFError
                        prefix.extend(data[:max(0, HEADER_SIZE - len(prefix))])
                        server.sendall(data)
                        left -= len(data)
                        if cmd == 6 and self.interrupt and size - left >= 2 << 20:
                            self.partial.set()
                            self.stopping.wait(10)
                            raise EOFError
                    if cmd in (6, 7):
                        row['key'] = f'{struct.unpack_from("<Q", prefix, 304)[0]:016x}'
                        row['sha256'] = prefix[320:352].hex()
                        row['tensor'] = prefix[228:292].split(b'\0',1)[0].decode('ascii')
                        row['type'] = struct.unpack_from('<I',prefix,8)[0]
                        row['shape'] = list(struct.unpack_from('<IIII',prefix,20))
                        row['offset'] = struct.unpack_from('<Q',prefix,296)[0]
                        row['length'] = struct.unpack_from('<Q',prefix,312)[0]
                    if cmd == 8:
                        row['get_bytes'] = struct.unpack_from('<Q', prefix, 304)[0]
            except (OSError, EOFError):
                pass
            except Exception as exc:
                self.errors.append(repr(exc))
            finally:
                for sock in (client, server):
                    with contextlib.suppress(OSError):
                        sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                reverse.join(3)

    def close(self):
        self.stopping.set()
        self.listener.close()
        for sock in self.sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        self.thread.join(4)
        if self.thread.is_alive():
            raise AssertionError('relay cleanup deadline exceeded')


class NativeCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='native-cache-311-')
        cls.root = Path(cls.directory.name)
        build_path = os.environ.get('NATIVE_CACHE_BUILD')
        if not build_path:
            spec = importlib.util.spec_from_file_location('cache_build', ROOT / 'tools/native-cache/build.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            result = module.build(os.environ.get('NATIVE_CACHE_SOURCE'), cls.root / 'compiled',
                                  os.environ.get('NATIVE_CACHE_CMAKE', 'cmake'))
            cls.bin = {k: v['path'] for k, v in result['binaries'].items()}
        else:
            cls.bin = {k: str(Path(build_path) / 'bin' / k) for k in ('driver', 'ggml-rpc-server')}
        cls.fixtures = {}
        for label, size, seed in [('A', 12 << 20, 19), ('B', 12 << 20, 67),
                                  ('C', 12 << 20, 101), ('D', 36 << 20, 149),
                                  ('Q', 34 * 512 * 724, 33)]:
            file = cls.root / (label + '.bin')
            block = bytes((i * 17 + i // 256 + seed) % 256 for i in range(65536))
            with file.open('wb') as stream:
                for _ in range(size // len(block)):
                    stream.write(block)
                stream.write(block[:size % len(block)])
            cls.fixtures[label] = file
        cls.records = []

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('NATIVE_CACHE_RESULTS'):
            Path(os.environ['NATIVE_CACHE_RESULTS']).write_text(json.dumps(cls.records, indent=2) + '\n')
        cls.directory.cleanup()

    @contextlib.contextmanager
    def worker(self, cache):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryFile(mode='w+') as log:
            env = dict(os.environ, LLAMA_CACHE=str(cache), GGML_RPC_DEBUG='1', GGML_NO_BACKTRACE='1')
            process = subprocess.Popen([self.bin['ggml-rpc-server'], '-H', '127.0.0.1', '-p', str(port),
                                        '-c', '-d', 'CPU', '-t', '2'], env=env,
                                       stdout=log, stderr=log, preexec_fn=child_limits)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        self.fail('worker exited: ' + log.read())
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.1):
                            break
                    except OSError:
                        time.sleep(.02)
                else:
                    self.fail('worker readiness deadline exceeded')
                yield process, port
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)

    def case(self, worker, label, expected_payload, mode='setget', control=''):
        process, port = worker
        relay = Relay(port)
        try:
            result = subprocess.run([self.bin['driver'], f'127.0.0.1:{relay.port}',
                                     str(self.fixtures[label]), mode, control],
                                    capture_output=True, text=True, timeout=20, preexec_fn=child_limits)
        finally:
            relay.close()
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        if mode == 'setget':
            self.assertIn('byte-identical to fixture: yes', result.stderr)
        self.assertFalse(relay.errors, relay.errors)
        expected_digest = hashlib.sha256(self.fixtures[label].read_bytes()).hexdigest()
        for row in relay.requests:
            if row['cmd'] in (6, 7):
                self.assertEqual(row['sha256'], expected_digest)
        weight = sum(r['size'] - HEADER_SIZE for r in relay.requests if r['cmd'] == 6)
        self.assertEqual(weight, expected_payload, relay.requests)
        sent = sum(9 + r['size'] for r in relay.requests)
        verification = sum(r.get('get_bytes', 0) for r in relay.requests)
        status = Path(f'/proc/{process.pid}/status').read_text()
        hwm = int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmHWM:')))
        record = {'case': label + '/' + mode + '/' + control, 'weight_payload': weight,
                  'setup_control_sent': sent - weight, 'verification_get_payload': verification,
                  'setup_control_received': relay.received - verification, 'worker_hwm_kib': hwm,
                  'exact_readback': mode == 'setget',
                  'coordinator_source_read_bytes': self.fixtures[label].stat().st_size}
        self.records.append(record)
        return next((r['key'] for r in relay.requests if r['cmd'] == 7), None), hwm

    def test_cold_reconnect_restart_delta_and_corruption_at_use(self):
        cache = self.root / 'main-cache'
        size = self.fixtures['A'].stat().st_size
        with self.worker(cache) as worker:
            key, _ = self.case(worker, 'A', size)
            self.case(worker, 'B', size)
            self.case(worker, 'A', 0)
            self.case(worker, 'B', 0)
            target = cache / 'rpc' / key
            # Damage after startup; a preparation-only gate cannot catch this.
            with target.open('r+b') as stream:
                original = stream.read(1)
                stream.seek(0)
                stream.write(bytes([original[0] ^ 255]))
            self.case(worker, 'A', size)
            self.assertEqual(target.read_bytes(), self.fixtures['A'].read_bytes())
            with target.open('r+b') as stream:
                stream.truncate(size // 2)
            self.case(worker, 'A', size)
            self.assertEqual(target.stat().st_size, size)
            # Same-size payload from another revision/representation cannot hit.
            target.write_bytes(self.fixtures['B'].read_bytes())
            self.case(worker, 'A', size)
        with self.worker(cache) as worker:
            self.case(worker, 'A', 0)
            self.case(worker, 'B', 0)
            self.case(worker, 'B', 0)
            self.case(worker, 'C', size)
        self.assertEqual(len(list((cache / 'rpc').glob('[0-9a-f]' * 16))), 3)

    def test_quantized_offset_and_async_native_semantics(self):
        cache = self.root / 'semantics-cache'
        with self.worker(cache) as worker:
            size = self.fixtures['Q'].stat().st_size
            self.case(worker, 'Q', size, control='q8')
            self.case(worker, 'Q', 0, control='q8')
            size = self.fixtures['A'].stat().st_size
            self.case(worker, 'A', size, control='offset')
            self.case(worker, 'A', 0, control='offset')
            self.case(worker, 'B', size, control='async')
            self.case(worker, 'B', 0, control='async')

    def test_selective_preparation_native_consumption_restart_and_delta(self):
        # Composition proof: #101-authorized range acquisition -> bounded #99
        # backing -> atomic #200-compatible RPC view -> real protocol-v7 hit.
        sys.path.insert(0, str(ROOT/'scripts'))
        from issue99_artifact_core import LocalFileSource, freeze_artifact_record, self_digest
        from issue101_orchestration import Coordinator
        from issue311_preparation import DiskBudget, StreamingArtifactCache, StreamingNode, prepare_participant
        from issue311_native_backing import publish_rpc_views
        from inferswarm.operator.source import compile_fnv, fnv
        helper = self.root/'preparation-fnv'; compile_fnv(helper)
        origin = self.root/'assigned-origin'; origin.mkdir()
        records = {}; keys = {}
        model = dict(model_id='synthetic/native', revision='fixture-v1', representation='Q8_0')
        for label in ('A','B','C','Q'):
            # Header/padding stands outside the assigned payload. Mandatory
            # acquisition of that remainder would be visible in the source log.
            data = self.fixtures[label].read_bytes()
            (origin/(label+'.bin')).write_bytes(data+b'UNRELATED')
            records[label] = freeze_artifact_record(kind='byte_range',content=data,**model,
                satisfies_logical_state_ids=[label],requirement_class='assigned_logical_state',
                origin=dict(source_object=label+'.bin',source_object_digest='sha256:'+hashlib.sha256(data+b'UNRELATED').hexdigest(),
                            source_object_length=len(data)+9,byte_start=0,byte_end=len(data)))
            keys[label] = fnv(self.fixtures[label],str(helper))
        # This is deliberately never an assigned or acquired artifact.
        (origin/'unassigned.bin').write_bytes(b'NOT NEEDED')
        source = LocalFileSource(source_id='origin',root=origin)
        cache = self.root/'selective-cache'
        budget = DiskBudget(128<<20,0,64<<20)
        def preparation(labels,epoch):
            node=StreamingNode('worker',StreamingArtifactCache(cache))
            controller=Coordinator(node_sources=[node.descriptor()],origin_sources=[source.descriptor()])
            plan=dict(epoch=epoch,model=model,logical_state_units=[dict(id=n) for n in records],
                participants=[dict(participant_id='P',node_id='worker',execution_unit_id='native-fixture',
                    required_state=dict(assigned_logical_state=labels,declared_shared_state=[],required_metadata=[]))])
            plan['plan_digest']=self_digest(plan,identity_field='plan_digest')
            required=controller.freeze(plan,lambda cls,sid:[records[sid]])
            return prepare_participant(coordinator=controller,requirements=required,participant_id='P',
                node=node,sources={'origin':source},budget=budget,
                publish_view=lambda backing:publish_rpc_views(backing,[(records[n],keys[n]) for n in labels],budget=budget,fnv_binary=str(helper)))
        cold=preparation(['A','B'],1)
        self.assertEqual(cold['acquisition_bytes'],24<<20)
        self.assertEqual({r['source_object'] for r in source.access_log},{'A.bin','B.bin'})
        self.assertLessEqual(max(r['length'] for r in source.access_log),65536)
        # Both cold-prepared payloads are already native hits on first startup.
        with self.worker(cache) as worker:
            self.case(worker,'A',0); self.case(worker,'B',0)
        before=len(source.access_log)
        warm=preparation(['A','B'],1)
        self.assertEqual(warm['acquisition_bytes'],0)
        self.assertEqual(len(source.access_log),before)
        with self.worker(cache) as worker: self.case(worker,'A',0)
        delta=preparation(['B','C','Q'],2)
        self.assertEqual(delta['acquisition_bytes'],(12<<20)+self.fixtures['Q'].stat().st_size)
        self.assertEqual({r['source_object'] for r in source.access_log[before:]},{'C.bin','Q.bin'})
        with self.worker(cache) as worker:
            self.case(worker,'B',0); self.case(worker,'C',0); self.case(worker,'Q',0,control='q8')
        # Immutable backing and the native view share disk bytes, but have no
        # permanent Python host mirror. Old A remains optional and budgeted.
        target=cache/'rpc'/keys['A']
        self.assertTrue(target.exists())
        backing=cache/'objects'/records['A']['content_digest'].replace(':','-')
        self.assertEqual(target.stat().st_ino,backing.stat().st_ino)
        self.records.append(dict(case='selective-preparation',cold_acquisition_bytes=cold['acquisition_bytes'],
            warm_acquisition_bytes=warm['acquisition_bytes'],delta_acquisition_bytes=delta['acquisition_bytes'],
            unrelated_acquisition_bytes=0,source_max_read_bytes=max(r['length'] for r in source.access_log),
            native_first_load_weight_payload=0,worker_restarted=True,exact_readback=True))

    def test_declared_repairs_fit_durable_duplicates_and_peak_stage(self):
        sys.path.insert(0, str(ROOT/'scripts'))
        from issue99_artifact_core import LocalFileSource
        from issue311_preparation import DiskBudget, StreamingArtifactCache, StreamingNode, backing_usage
        from issue311_native_backing import prepare_q8_participant
        from inferswarm.operator import source as q8_source
        from tests import test_issue299_source as q8_fixture
        fixture = q8_fixture.Q8Source(); fixture.setUp()
        self.addCleanup(fixture.doCleanups); fixture.cached()
        payload = fixture.payload
        helper = self.root/'repair-fnv'; q8_source.compile_fnv(helper)
        keys = {}
        # Two actual parsed synthetic GGUF members now contain the assigned
        # 12 MiB native I8 fixtures. Other members/metadata remain small.
        for label, name in [('A','blk.17.ffn_gate_exps.weight'),('B','blk.45.ffn_up_exps.weight')]:
            row = next(t for t in payload['metadata']['tensors'] if t['state_id']==name)
            member = row['member']; number = int(member.split('-')[1].split('.')[0])
            pairs = [('general.architecture','synthetic'),('split.no',number),
                     ('split.count',6),('split.tensors.count',len(payload['assignments']))]
            header = b'GGUF'+struct.pack('<IQQ',3,1,len(pairs))
            for key,value in pairs:
                header += q8_fixture.text(key)+struct.pack('<I',8 if isinstance(value,str) else 4)
                header += q8_fixture.text(value) if isinstance(value,str) else struct.pack('<I',value)
            data = self.fixtures[label].read_bytes()
            header += q8_fixture.text(name)+struct.pack('<IQIQ',1,len(data),24,0)
            full = header+b'\0'*(-len(header)%32)+data
            (fixture.root/member).write_bytes(full)
            full_sha = hashlib.sha256(full).hexdigest(); header_sha = hashlib.sha256(header).hexdigest()
            _,parsed = q8_source.parse_gguf_header(header,object_bytes=len(full),expected_header_sha256=header_sha)
            row.update(asdict(parsed[0]),member=member)
            # JSON wire descriptors use lists, independently of parser tuples.
            row['shape'] = list(row['shape'])
            for inventory in payload['model']['members']:
                if inventory[0]==member: inventory[:]=[member,full_sha,len(full)]
            for inventory in payload['metadata']['header_identities']:
                if inventory[0]==member: inventory[:]=[member,0,len(header)-1,header_sha,len(full),full_sha]
            for participant in payload['participants']:
                for backing in participant['backing']:
                    if backing['member']==member: backing.update(sha256=full_sha,size_bytes=len(full))
            assignment = next(a for a in payload['assignments'] if a['state_id']==name)
            assignment.update({k:row[k] for k in ('ggml_type','shape','absolute_offset','encoded_bytes')})
            for placement in payload['placement']:
                for span in placement['state_ranges']:
                    if span[0]==name: span[2:]=[row['absolute_offset'],len(data)]
            descriptor = next(c for c in fixture.remote['cache_ranges'] if c['state_id']==name)
            keys[label] = q8_source.fnv(self.fixtures[label],str(helper))
            descriptor.update(offset=row['absolute_offset'],length=len(data),
                              sha256=hashlib.sha256(data).hexdigest(),cache_key=keys[label])
        metadata = payload['metadata']
        metadata['metadata_digest'] = hashlib.sha256(q8_source._q8_canonical(
            {k:v for k,v in metadata.items() if k!='metadata_digest'})).hexdigest()
        executable = self.bin['ggml-rpc-server']; executable_sha = q8_source.sha(executable)
        origin = LocalFileSource(source_id='origin',root=fixture.root)
        def prepare(cache,budget):
            return prepare_q8_participant(payload=payload,epoch=1,executable=executable,
                executable_sha256=executable_sha,node=StreamingNode('B',StreamingArtifactCache(cache)),
                origin_source=origin,budget=budget,fnv_binary=str(helper))
        def repairs(cache,budget,rounds):
            usage = []
            with self.worker(cache) as worker:
                for round_number in range(rounds):
                    for label in ('A','B'):
                        target = cache/'rpc'/keys[label]
                        with target.open('r+b') as stream:
                            first=stream.read(1); stream.seek(0); stream.write(bytes([first[0]^255]))
                        self.case(worker,label,12<<20)
                        retained = backing_usage(cache)
                        usage.append(retained)
                        self.records.append(dict(case='declared-repair-budget',round=round_number,
                            label=label,retained_bytes=retained,limit_bytes=budget.limit_bytes,
                            exact_readback=True))
                        self.assertLessEqual(retained,budget.limit_bytes,
                            'declared native repairs exceeded admitted disk ceiling')
            return usage
        # RED on 52f95384: admission succeeds, both repairs read back exactly,
        # then ~48 MiB remains under a ~36 MiB admitted ceiling.
        tight = DiskBudget((36<<20)+(256<<10),0,(12<<20)+16384)
        tight_cache=self.root/'repair-tight'
        try: prepare(tight_cache,tight)
        except ValueError as error:
            self.assertRegex(str(error),'native.*reserve|disk budget')
            self.assertEqual(origin.access_log,[])
        else:
            repairs(tight_cache,tight,1)
            self.fail('unsafe repair reserve was admitted')
        admitted = DiskBudget(64<<20,0,(36<<20)+(256<<10))
        cache=self.root/'repair-admitted'; prepare(cache,admitted)
        usage=repairs(cache,admitted,3)
        self.assertGreater(usage[1],48<<20)
        self.assertEqual(usage[1:], [usage[1]]*5)  # later RPC inodes have no retained alias
        self.assertLessEqual(max(usage)+(12<<20)+16384,admitted.limit_bytes)
        # Already independent object/RPC copies are charged, not mistaken for
        # hardlink deduplication. Warm admission refuses a tight total and never
        # deletes the copies; a sufficient budget reuses them without a read.
        duplicate_cache=self.root/'repair-existing-duplicates'; prepare(duplicate_cache,admitted)
        for label in ('A','B'):
            target=duplicate_cache/'rpc'/keys[label]
            copied=duplicate_cache/('.copy-'+label)
            shutil.copyfile(target,copied); os.replace(copied,target)
        retained=backing_usage(duplicate_cache); origin.access_log.clear()
        with self.assertRaisesRegex(ValueError,'disk budget'): prepare(duplicate_cache,admitted)
        self.assertEqual(backing_usage(duplicate_cache),retained)
        self.assertEqual(origin.access_log,[])
        larger=DiskBudget(88<<20,0,admitted.reserve_bytes)
        self.assertEqual(prepare(duplicate_cache,larger)['acquisition_bytes'],0)
        self.assertEqual(origin.access_log,[])
        duplicate_usage=repairs(duplicate_cache,larger,2)
        self.assertEqual(duplicate_usage,[retained]*4)
        self.assertLessEqual(retained+(12<<20)+16384,larger.limit_bytes)

    def test_interrupted_publication_preserves_final_and_recovers(self):
        cache = self.root / 'interrupted-cache'
        with self.worker(cache) as worker:
            key, _ = self.case(worker, 'A', 12 << 20)
            previous = (cache / 'rpc' / key).read_bytes()
            process, port = worker
            relay = Relay(port, interrupt=True)
            client = subprocess.Popen([self.bin['driver'], f'127.0.0.1:{relay.port}',
                                       str(self.fixtures['C']), 'setget'], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, env=dict(os.environ, GGML_NO_BACKTRACE='1'),
                                      preexec_fn=child_limits)
            try:
                self.assertTrue(relay.partial.wait(10), 'did not reach partial native publication')
                process.terminate()  # actual worker restart in the middle of cold publication
                process.wait(5)
                relay.close()
                client.wait(5)
                self.assertNotEqual(client.returncode, 0)
            finally:
                relay.close()
                if client.poll() is None:
                    client.kill()
                    client.wait(5)
            self.assertEqual((cache / 'rpc' / key).read_bytes(), previous)
            self.assertTrue(list((cache / 'rpc').glob('.rpc-stage-*')))
            self.assertEqual(len(list((cache / 'rpc').glob('[0-9a-f]' * 16))), 1)
        with self.worker(cache) as worker:
            self.case(worker, 'A', 0)
            self.case(worker, 'C', 12 << 20)
            self.case(worker, 'C', 0)

    def test_bounded_staging_cold_and_warm(self):
        cache = self.root / 'bounded-cache'
        for payload in (36 << 20, 0):
            with self.worker(cache) as worker:
                _, hwm = self.case(worker, 'D', payload, mode='set')
                # CPU destination is 36 MiB. Allow baseline/allocator noise, but
                # reject the demonstrated extra full-object vector (~76.5 MiB).
                self.assertLess(hwm * 1024, (36 + 12) << 20)
