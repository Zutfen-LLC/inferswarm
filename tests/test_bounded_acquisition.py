"""Local HTTP/offline count and recovery regressions; no hardware or models."""
from contextlib import contextmanager
from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tracemalloc
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from issue99_artifact_core import (
    AcquisitionError, LocalFileSource, TransferInterrupted, digest_of_bytes,
    freeze_artifact_record, self_digest,
)
from issue101_fixture import Fixture
from issue101_orchestration import Coordinator
from issue311_preparation import DiskBudget, StreamingArtifactCache, StreamingNode, prepare_participant
from bounded_acquisition import (
    AssignedHttpSource, AssignedRangeServer, BatchedArtifactCache, BoundedStreamingNode,
)

BUDGET = DiskBudget(128 << 20, 0, 32768)


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root/'source')
        self.record = self.make_record((2 << 20) + 17)
        self.origin = LocalFileSource(source_id='origin', root=self.fixture.root)

    def make_record(self, size):
        data = (bytes(range(256)) * ((size + 255)//256))[:size]
        full = b'prefix' + data + b'unassigned'
        (self.fixture.root/'large.bin').write_bytes(full)
        return freeze_artifact_record(kind='byte_range', content=data,
            **self.fixture.plan(1, {})['model'], satisfies_logical_state_ids=['coefficient.1'],
            requirement_class='assigned_logical_state', origin=dict(source_object='large.bin',
                source_object_digest=digest_of_bytes(full), source_object_length=len(full),
                byte_start=6, byte_end=6+size))

    def node(self, name='backing', *, legacy=False, **cache_options):
        cache = (StreamingArtifactCache(self.root/name) if legacy
                 else BatchedArtifactCache(self.root/name, **cache_options))
        return (StreamingNode if legacy else BoundedStreamingNode)('A', cache)

    def prepare(self, node, source=None, record=None, *, epoch=1):
        source = source or self.origin
        record = record or self.record
        coordinator = Coordinator(node_sources=[node.descriptor()], origin_sources=[source.descriptor()])
        required = coordinator.freeze(self.fixture.plan(epoch, {'P': ('A', [1])}), lambda cls,sid:[record])
        result = prepare_participant(coordinator=coordinator, requirements=required, participant_id='P',
            node=node, sources={'origin': source}, budget=BUDGET)
        self.assertEqual(coordinator.bytes_observed, 0)
        return result

    def test_legacy_and_opt_in_read_and_checkpoint_counts(self):
        counts = []
        for legacy in (True, False):
            node = self.node('legacy' if legacy else 'bounded', legacy=legacy)
            self.origin.access_log.clear()
            with patch.object(node.cache, '_write_state_locked', wraps=node.cache._write_state_locked) as states:
                result = self.prepare(node)
            counts.append((len(self.origin.access_log), states.call_count))
            self.assertEqual(result['acquisition_bytes'], self.record['length'])
            self.assertTrue(node.cache.has_verified(self.record))
            self.assertEqual(sum(r['length'] for r in self.origin.access_log), self.record['length'])
            self.assertTrue(all(6 <= r['offset'] < r['offset']+r['length'] <= self.record['origin']['byte_end']
                                for r in self.origin.access_log))
        self.assertEqual(counts, [(33, 34), (3, 2)])

    def test_batched_checkpoint_and_final_short_range(self):
        self.record = self.make_record((9 << 20) + 17)
        node = self.node()
        with patch.object(node.cache, '_write_state_locked', wraps=node.cache._write_state_locked) as states:
            self.prepare(node)
        self.assertEqual([call.args[1] for call in states.call_args_list], [0, 8 << 20, (9 << 20)+17])
        self.assertEqual(len(self.origin.access_log), 10)
        self.assertEqual(self.origin.access_log[-1]['length'], 17)

    def test_http_requests_connections_and_state_publications(self):
        counts = []
        for legacy in (True, False):
            server = AssignedRangeServer(self.fixture.root, [self.record])
            with serving(server), patch.object(server, 'get_request', wraps=server.get_request) as connections:
                with patch.object(server.RequestHandlerClass, 'do_GET', autospec=True,
                                  side_effect=server.RequestHandlerClass.do_GET) as requests:
                    port = server.server_address[1]
                    source = AssignedHttpSource(source_id='origin', endpoint=self.origin.descriptor()['endpoint'],
                                                port=port, records=[self.record])
                    self.addCleanup(source.close)
                    if legacy:
                        def fresh_read(origin, offset, length):
                            request = urllib.request.Request(f'http://127.0.0.1:{port}/large.bin', headers={
                                'Range': f'bytes={offset}-{offset+length-1}',
                                'If-Match': '"'+origin['source_object_digest']+'"'})
                            with urllib.request.urlopen(request, timeout=5) as response:
                                return response.read(length)
                        source.read = fresh_read
                    node = self.node('http-old' if legacy else 'http-new', legacy=legacy)
                    with source, patch.object(node.cache, '_write_state_locked', wraps=node.cache._write_state_locked) as states:
                        self.prepare(node, source)
                    counts.append((requests.call_count, connections.call_count, states.call_count))
        self.assertEqual(counts, [(33, 33, 34), (3, 1, 2)])

    def test_source_and_server_refuse_outside_exact_whitelist(self):
        with serving(AssignedRangeServer(self.fixture.root, [self.record])) as server:
            with AssignedHttpSource(source_id='origin', endpoint=self.origin.descriptor()['endpoint'],
                    port=server.server_address[1], records=[self.record]) as source:
                for offset, length in [(0, 1), (5, 2), (self.record['origin']['byte_end']-1, 2), (6, (1<<20)+1)]:
                    with self.assertRaisesRegex(AcquisitionError, 'SOURCE_UNAUTHORIZED'):
                        source.read(self.record['origin'], offset, length)
                changed = deepcopy(self.record['origin'])
                changed['source_object_digest'] = 'sha256:'+'0'*64
                with self.assertRaisesRegex(AcquisitionError, 'SOURCE_UNAUTHORIZED'):
                    source.read(changed, 6, 1)
                connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
                try:
                    for target, first, last, etag, expected in [
                        ('large.bin', 0, 6, self.record['origin']['source_object_digest'], 404),
                        ('large.bin', 6, (1<<20)+6, self.record['origin']['source_object_digest'], 404),
                        ('coefficients.bin', 0, 3, self.record['origin']['source_object_digest'], 404),
                        ('large.bin', 6, 9, 'sha256:'+'0'*64, 412),
                    ]:
                        connection.request('GET', '/'+target, headers={
                            'Range': f'bytes={first}-{last}', 'If-Match': '"'+etag+'"'})
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected)
                        response.read()
                finally:
                    connection.close()

    def fault_server(self, mode):
        data = (self.fixture.root/'large.bin').read_bytes()
        origin = self.record['origin']
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_args): pass
            def handle(self):
                try: super().handle()
                except (BrokenPipeError, ConnectionResetError): pass
            def do_GET(self):
                start, end = map(int, self.headers['Range'][6:].split('-'))
                body = data[start:end+1]
                self.send_response(200 if mode == 'status' else 206)
                self.send_header('Content-Length', str(len(body)+1 if mode == 'oversized' else len(body)))
                self.send_header('Content-Range', f"bytes {start+1 if mode == 'range' else start}-{end}/{len(data)}")
                self.send_header('ETag', '"'+('sha256:'+'0'*64 if mode == 'identity' else origin['source_object_digest'])+'"')
                self.end_headers()
                if mode == 'truncated':
                    self.wfile.write(body[:13])
                    self.wfile.flush()
                    self.close_connection = True
                else:
                    try:
                        self.wfile.write((b'X'+body[1:]) if mode == 'corrupt' else body)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError): pass
        return ThreadingHTTPServer(('127.0.0.1', 0), Handler)

    def test_wrong_range_oversized_identity_status_and_digest_never_publish(self):
        for mode in ('range', 'oversized', 'identity', 'status', 'corrupt'):
            with self.subTest(mode=mode), serving(self.fault_server(mode)) as server:
                node = self.node(mode)
                with AssignedHttpSource(source_id='origin', endpoint=self.origin.descriptor()['endpoint'],
                        port=server.server_address[1], records=[self.record], timeout=5) as source:
                    with self.assertRaises(AcquisitionError):
                        self.prepare(node, source)
                self.assertFalse(node.cache.has_verified(self.record))
                self.assertIsNone(node.cache.partial_state(self.record['artifact_id']))

    def test_truncated_response_checkpoints_prior_full_ranges_and_can_restart(self):
        node = self.node()
        with serving(self.fault_server('truncated')) as server:
            with AssignedHttpSource(source_id='origin', endpoint=self.origin.descriptor()['endpoint'],
                    port=server.server_address[1], records=[self.record], timeout=5) as source:
                result = self.prepare(node, source)
        self.assertEqual(result['status'], 'INTERRUPTED')
        self.assertEqual(result['results'][0]['retained_bytes'], 0)
        self.assertFalse(node.cache.has_verified(self.record))
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length'])

    def test_controlled_interruption_flushes_complete_ranges_and_partial(self):
        node = self.node()
        original = self.origin.read
        def interrupted(origin, offset, length):
            if offset > 6:
                raise TransferInterrupted('fixture', original(origin, offset, 13))
            return original(origin, offset, length)
        with patch.object(self.origin, 'read', side_effect=interrupted):
            result = self.prepare(node)
        retained = (1 << 20)+13
        self.assertEqual(result['results'][0]['retained_bytes'], retained)
        self.assertEqual(node.cache.partial_state(self.record['artifact_id'])['retained_bytes'], retained)
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length']-retained)

    def test_data_before_state_fsync_and_state_failure_reuses_only_old_checkpoint(self):
        node = self.node(checkpoint_bytes=1 << 20)
        calls = []
        original_state = node.cache._write_state_locked
        original_sync = os.fsync
        def sync(fd):
            calls.append(('fsync', os.readlink(f'/proc/self/fd/{fd}')))
            return original_sync(fd)
        def state(record, retained):
            calls.append(('state', retained))
            if retained == 2 << 20:
                raise OSError('checkpoint write interrupted')
            return original_state(record, retained)
        with patch('bounded_acquisition.os.fsync', side_effect=sync), patch.object(node.cache, '_write_state_locked', side_effect=state):
            with self.assertRaisesRegex(OSError, 'checkpoint write interrupted'):
                self.prepare(node)
        self.assertEqual(node.cache.partial_state(self.record['artifact_id'])['retained_bytes'], 1 << 20)
        self.assertEqual(node.cache._part_path(self.record['artifact_id']).stat().st_size, 2 << 20)
        for index, event in enumerate(calls):
            if event[0] == 'state' and event[1]:
                self.assertEqual(calls[index-1][0], 'fsync')
                self.assertTrue(calls[index-1][1].endswith('.part'))
        self.origin.access_log.clear()
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length']-(1<<20))
        self.assertEqual(self.origin.access_log[0]['offset'], 6+(1<<20))

    def test_state_atomic_replace_failure_preserves_previous_sidecar(self):
        node = self.node(checkpoint_bytes=1 << 20)
        original = os.replace
        def interrupted(src, dst):
            if Path(dst).suffix == '.state' and node.cache._part_path(self.record['artifact_id']).stat().st_size >= 2<<20:
                raise OSError('state replace interrupted')
            return original(src, dst)
        with patch('issue311_preparation.os.replace', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'state replace interrupted'):
                self.prepare(node)
        self.assertEqual(node.cache.partial_state(self.record['artifact_id'])['retained_bytes'], 1<<20)
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length']-(1<<20))

    def test_partial_data_write_and_final_publication_interruptions_restart(self):
        node = self.node()
        def interrupted(record, data):
            with node.cache._part_path(record['artifact_id']).open('ab') as stream:
                stream.write(data[:19])
            raise OSError('partial data write')
        with patch.object(node.cache, 'append_partial', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'partial data write'):
                self.prepare(node)
        self.assertEqual(node.cache.partial_state(self.record['artifact_id'])['retained_bytes'], 0)
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length'])
        node = self.node('publication')
        original = os.replace
        def interrupted_publish(src, dst):
            if Path(dst).parent.name == 'objects':
                raise OSError('publication interrupted')
            return original(src, dst)
        with patch('issue311_preparation.os.replace', side_effect=interrupted_publish):
            with self.assertRaisesRegex(OSError, 'publication interrupted'):
                self.prepare(node)
        self.assertFalse(node.cache.has_verified(self.record))
        self.origin.access_log.clear()
        self.assertEqual(self.prepare(self.node('publication'))['acquisition_bytes'], 0)
        self.assertEqual(self.origin.access_log, [])

    def test_identity_change_and_disconnect_after_a_complete_response(self):
        for mode in ('identity', 'truncated'):
            with self.subTest(mode=mode):
                server = self.fault_server(mode)
                original = server.RequestHandlerClass.do_GET
                # First request uses the correct paired helper; switch the
                # same connection to the fault response on the second request.
                good = AssignedRangeServer(self.fixture.root, [self.record])
                self.addCleanup(good.server_close)
                calls = []
                def read(handler):
                    calls.append(1)
                    if len(calls) == 1:
                        good.RequestHandlerClass.do_GET(handler)
                    else:
                        original(handler)
                with serving(server), patch.object(server.RequestHandlerClass, 'do_GET', read):
                    node = self.node(mode+'-later')
                    with AssignedHttpSource(source_id='origin', endpoint=self.origin.descriptor()['endpoint'],
                            port=server.server_address[1], records=[self.record], timeout=5) as source:
                        if mode == 'identity':
                            with self.assertRaises(AcquisitionError): self.prepare(node, source)
                            self.assertIsNone(node.cache.partial_state(self.record['artifact_id']))
                        else:
                            result = self.prepare(node, source)
                            self.assertEqual(result['results'][0]['retained_bytes'], 1<<20)
                            self.assertEqual(self.prepare(self.node(mode+'-later'))['acquisition_bytes'],
                                             self.record['length']-(1<<20))
                    self.assertEqual(len(calls), 2)

    def test_caps_are_explicit_bounded_and_four_mib_ranges_work(self):
        for value in (0, True, 65536, (4<<20)+1):
            with self.assertRaises(ValueError): BoundedStreamingNode('A', self.node().cache, range_bytes=value)
        for value in (0, True, (64<<20)+1):
            with self.assertRaises(ValueError): BatchedArtifactCache(self.root/'invalid', checkpoint_bytes=value)
        self.record = self.make_record((5<<20)+17)
        node = BoundedStreamingNode('A', self.node().cache, range_bytes=4<<20)
        self.prepare(node)
        self.assertEqual([r['length'] for r in self.origin.access_log], [4<<20, (1<<20)+17])

    def test_fresh_process_drops_uncheckpointed_tail_then_reuses_verified_cache(self):
        node = self.node(checkpoint_bytes=1 << 20)
        inputs = self.root/'inputs.json'
        inputs.write_text(json.dumps(self.record))
        code = '''
import json,os,sys
from pathlib import Path
from bounded_acquisition import BatchedArtifactCache
r=json.loads(Path(sys.argv[1]).read_text()); c=BatchedArtifactCache(sys.argv[2],checkpoint_bytes=1<<20)
c.begin_partial(r)
c.append_partial(r, bytes(range(256)) * 4096)
with c._part_path(r['artifact_id']).open('ab') as f: f.write(b'uncheckpointed tail'); f.flush()
os._exit(73)
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT/'scripts'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-c', code, str(inputs), str(node.cache.root)], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length']-(1<<20))
        self.origin.access_log.clear()
        (self.fixture.root/'large.bin').unlink()
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], 0)
        self.assertEqual(self.origin.access_log, [])

    def test_invalid_checkpoint_identity_extent_and_short_data_restart_safely(self):
        for mode in ('digest', 'artifact', 'length', 'bool', 'negative', 'beyond', 'truncated',
                     'invalid_json', 'missing', 'list'):
            with self.subTest(mode=mode):
                node = self.node(mode)
                node.cache.begin_partial(self.record)
                node.cache.append_partial(self.record, b'X'*(1<<20))
                node.cache.checkpoint_partial(self.record)
                path = node.cache._state_path(self.record['artifact_id'])
                state = json.loads(path.read_text())
                if mode == 'digest': state['content_digest'] = 'sha256:'+'0'*64
                elif mode == 'artifact': state['artifact_id'] = 'sha256:'+'0'*64
                elif mode == 'length': state['length'] += 1
                elif mode == 'bool': state['retained_bytes'] = True
                elif mode == 'negative': state['retained_bytes'] = -1
                elif mode == 'beyond': state['retained_bytes'] = self.record['length']+1
                elif mode == 'truncated': node.cache._part_path(self.record['artifact_id']).write_bytes(b'X')
                elif mode == 'missing': del state['retained_bytes']
                elif mode == 'list': state = ['invalid']
                path.write_text('{' if mode == 'invalid_json' else json.dumps(state))
                self.assertEqual(self.prepare(self.node(mode))['acquisition_bytes'], self.record['length'])

    def test_changed_record_does_not_reuse_old_artifact_and_corrupt_prefix_never_publishes(self):
        node = self.node()
        node.cache.begin_partial(self.record)
        node.cache.append_partial(self.record, b'X'*(1<<20))
        node.cache.checkpoint_partial(self.record)
        with self.assertRaisesRegex(AcquisitionError, 'INTEGRITY_DIGEST_MISMATCH'):
            self.prepare(self.node())
        self.assertFalse(node.cache.has_verified(self.record))
        self.assertEqual(self.prepare(self.node())['acquisition_bytes'], self.record['length'])
        changed = deepcopy(self.record)
        changed['provenance']['revision'] = 'new-revision'
        changed['artifact_id'] = self_digest(changed, identity_field='artifact_id')
        other = self.node('changed')
        other.cache.begin_partial(self.record)
        other.cache.append_partial(self.record, b'X'*(1<<20))
        other.cache.checkpoint_partial(self.record)
        self.assertEqual(other.cache.resume_partial(changed), 0)
        self.assertFalse(other.cache.has_verified(changed))

    def test_streaming_scratch_is_independent_of_object_and_checkpoint_size(self):
        self.record = self.make_record((9 << 20)+17)
        node = self.node(checkpoint_bytes=64<<20)
        tracemalloc.start()
        try:
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole-object read')):
                self.prepare(node)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 4 << 20, peak)

    def test_existing_q8_preparation_composes_with_paired_http_and_local_metadata(self):
        from tests.test_issue299_source import Q8Source
        from issue311_native_backing import prepare_q8_participant, project_q8_preparation, runtime_identity
        fixture = Q8Source()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.cached()
        projection = project_q8_preparation(fixture.payload, epoch=1,
            runtime=runtime_identity(fixture.runtime, fixture.remote['runtime_sha256']))
        records = [r for r, _ in projection['native_ranges']]
        cache = BatchedArtifactCache(self.root/'q8')
        node = BoundedStreamingNode('B', cache)
        with serving(AssignedRangeServer(fixture.root, records)) as server:
            with AssignedHttpSource(source_id='origin', endpoint=fixture.root.as_uri(),
                    port=server.server_address[1], records=records) as source:
                result = prepare_q8_participant(payload=fixture.payload, epoch=1, executable=fixture.runtime,
                    executable_sha256=fixture.remote['runtime_sha256'], node=node, origin_source=source,
                    budget=BUDGET)
        self.assertEqual(result['status'], 'VERIFIED_BACKING-not-consumed')
        self.assertTrue(all(cache.has_verified(r) for r in projection['records'].values()))
        self.assertFalse(result['q8_runner_integrated'])


if __name__ == '__main__':
    unittest.main()
