"""#311 focused native cache regressions; small CPU tensors, loopback, no model/GPU.

The relay retains only descriptor-sized metadata and streams <=64 KiB payloads.
Verification GET traffic is accounted separately from weight acquisition.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import socket
import struct
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
        budget = DiskBudget(128<<20,0,(12<<20)+32768)
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
                publish_view=lambda backing:publish_rpc_views(backing,[(records[n],keys[n]) for n in labels],fnv_binary=str(helper)))
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
