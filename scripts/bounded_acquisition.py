"""Opt-in bounded initial acquisition over an operator-owned loopback tunnel.

Successor composition of the unchanged #99/#101/#311 producers. One stopped
participant, one preparation writer, no discovery, retries or parallel fetches.
The paired HTTP helper serves only frozen assigned ranges/required metadata.
It is not a public server or a replacement for the native RPC transport.
"""
from __future__ import annotations

from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote

from issue99_artifact_core import (
    AcquisitionError, TransferInterrupted, acquire_artifact, fail,
    guard_full_object_acquisition, validate_artifact_record,
)
from issue311_preparation import StreamingArtifactCache, StreamingNode

RANGE_BYTES = 1 << 20
CHECKPOINT_BYTES = 8 << 20


def _range_cap(value):
    if type(value) is not int or not (1 << 20) <= value <= (4 << 20):
        raise ValueError('range cap must be between 1 and 4 MiB')
    return value


class BatchedArtifactCache(StreamingArtifactCache):
    """Keep the #311 layout; sidecar names only a data-fsynced prefix.

    Writes go straight to disk, not a checkpoint-sized RAM buffer. After a
    process/data/state-write interruption, resume truncates any uncheckpointed
    tail to that prefix. Final length and SHA verification remain mandatory.
    """

    def __init__(self, root, *, checkpoint_bytes=CHECKPOINT_BYTES):
        if type(checkpoint_bytes) is not int or not (1 << 20) <= checkpoint_bytes <= (64 << 20):
            raise ValueError('checkpoint interval must be between 1 and 64 MiB')
        super().__init__(root)
        self.checkpoint_bytes = checkpoint_bytes

    def partial_state(self, artifact_id):
        state = super().partial_state(artifact_id)
        # The inherited acquisition loop reads retained_bytes for diagnostics
        # before resume. Malformed JSON shapes must restart like unreadable JSON.
        if (not isinstance(state, dict)
                or set(state) != {'artifact_id', 'content_digest', 'length', 'retained_bytes'}
                or type(state['retained_bytes']) is not int):
            return None
        return state

    def _extent(self, record):
        retained = self._require_matching_partial(record)
        size = self._part_path(record['artifact_id']).stat().st_size
        if not retained <= size <= record['length']:
            raise fail('PARTIAL_STATE_IDENTITY_MISMATCH', 'partial extent')
        return retained, size

    def append_partial(self, record, data):
        with self._lock:
            retained, size = self._extent(record)
            if size + len(data) > record['length']:
                raise fail('SOURCE_OBJECT_UNAVAILABLE', 'oversized append')
            with self._part_path(record['artifact_id']).open('ab') as stream:
                stream.write(data)
                size += len(data)
                if size - retained >= self.checkpoint_bytes or size == record['length']:
                    stream.flush()
                    os.fsync(stream.fileno())
                    self._write_state_locked(record, size)
            return size

    def checkpoint_partial(self, record):
        with self._lock:
            retained, size = self._extent(record)
            if size != retained:
                with self._part_path(record['artifact_id']).open('rb') as stream:
                    os.fsync(stream.fileno())
                self._write_state_locked(record, size)
            return size

    def resume_partial(self, record):
        validate_artifact_record(record)
        state = self.partial_state(record['artifact_id'])
        if state is None:
            return 0
        try:
            if not 0 <= state['retained_bytes'] <= record['length']:
                raise fail('PARTIAL_STATE_IDENTITY_MISMATCH', 'invalid retained extent')
            with self._lock:
                retained, size = self._extent(record)
                if size != retained:
                    with self._part_path(record['artifact_id']).open('r+b') as stream:
                        stream.truncate(retained)
                        stream.flush()
                        os.fsync(stream.fileno())
            return retained
        except (AcquisitionError, FileNotFoundError) as error:
            self.discard_partial(record['artifact_id'])
            raise fail('PARTIAL_STATE_IDENTITY_MISMATCH', 'partial binding/extent') from error


class BoundedStreamingNode(StreamingNode):
    """#101 attempt/lifecycle contract with an explicit bounded read size."""

    def __init__(self, node_id, cache, *, range_bytes=RANGE_BYTES):
        if not isinstance(cache, BatchedArtifactCache):
            raise ValueError('batched streaming cache required')
        super().__init__(node_id, cache)
        self.range_bytes = _range_cap(range_bytes)
        if cache.checkpoint_bytes < self.range_bytes:
            raise ValueError('checkpoint interval must cover at least one range')

    def acquire(self, coordinator, ticket, source):
        # Retain Node.acquire's attempt validation, lifecycle and ledger binding;
        # the frozen predecessor has no per-node chunk-size hook.
        authority, record = coordinator.validate_attempt(ticket, self.node_id, source.descriptor())
        identity = dict(attempt_digest=ticket['attempt_digest'], artifact_id=record['artifact_id'],
                        participant_id=ticket['participant_id'], node_id=self.node_id,
                        epoch=ticket['epoch'], plan_digest=ticket['plan_digest'])
        start = len(self.ledger.events)
        try:
            if not self.cache.has_verified(record):
                for state in ('MISSING', 'AUTHORIZED', 'ACQUIRING'):
                    self.lifecycle.append(dict(identity, state=state))
            result = acquire_artifact(cache=self.cache, source=source, record=record,
                authorization=authority, participant_id=ticket['participant_id'],
                ledger=self.ledger, chunk_bytes=self.range_bytes)
            if result['status'] == 'INTERRUPTED':
                retained = self.cache.checkpoint_partial(record)
                result['retained_bytes'] = retained
                self.ledger.events[-1]['partial_staging_bytes'] = retained
        except AcquisitionError as error:
            self.failures.append(dict(identity, reason=str(error).split(':')[0]))
            raise
        finally:
            for event in self.ledger.events[start:]:
                event.update(identity)
        if result['status'] == 'INTERRUPTED':
            self.failures.append(dict(identity, reason='TRANSFER_INTERRUPTED'))
        else:
            self.lifecycle.append(dict(identity, state='VERIFIED_AVAILABLE'))
        return result


def _origins(records):
    records = deepcopy(list(records))
    guard_full_object_acquisition(records)
    origins = []
    for record in records:
        validate_artifact_record(record)
        if record['kind'] not in ('byte_range', 'whole_object'):
            raise ValueError('only frozen ranges and required whole metadata are supported')
        origin = record['origin']
        name = origin['source_object']
        if not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('source object must be a basename')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', origin['source_object_digest']):
            raise ValueError('immutable SHA-256 source identity required')
        origins.append(origin)
    # One member cannot have conflicting immutable identities in one whitelist.
    identities = {}
    for origin in origins:
        identity = origin['source_object_digest'], origin['source_object_length']
        if identities.setdefault(origin['source_object'], identity) != identity:
            raise ValueError('conflicting source object identities')
    return origins


def _contains(origin, offset, length):
    start = origin.get('byte_start', 0)
    end = origin.get('byte_end', origin['source_object_length'])
    return start <= offset and offset + length <= end


class AssignedHttpSource:
    """One persistent HTTP/1.1 connection to the paired loopback range helper.

    ``endpoint`` is the existing #101 provisioned file:// source descriptor;
    ``port`` is its explicit operator-owned tunnel endpoint, never discovery.
    Responses must echo exact range, total length and immutable source ETag.
    """

    def __init__(self, *, source_id, endpoint, port, records, range_bytes=RANGE_BYTES, timeout=120):
        if not endpoint.startswith('file://'):
            raise ValueError('existing provisioned file source descriptor required')
        self.source_id = source_id
        self.endpoint = endpoint
        self.origins = _origins(records)
        self.range_bytes = _range_cap(range_bytes)
        self._connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)

    def descriptor(self):
        return dict(source_id=self.source_id, endpoint=self.endpoint)

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def read(self, origin, offset, length):
        if (type(offset) is not int or type(length) is not int or not 0 < length <= self.range_bytes
                or origin not in self.origins or not _contains(origin, offset, length)):
            raise fail('SOURCE_UNAUTHORIZED', 'outside exact assigned range')
        etag = '"' + origin['source_object_digest'] + '"'
        expected_range = f"bytes {offset}-{offset+length-1}/{origin['source_object_length']}"
        try:
            self._connection.request('GET', '/' + quote(origin['source_object'], safe=''),
                headers={'Range': f'bytes={offset}-{offset+length-1}', 'If-Match': etag})
            response = self._connection.getresponse()
            if (response.status != 206
                    or response.getheader('Content-Range') != expected_range
                    or response.getheader('ETag') != etag
                    or response.getheader('Content-Length') != str(length)
                    or response.getheader('Transfer-Encoding') is not None
                    or response.getheader('Content-Encoding') not in (None, 'identity')):
                raise fail('SOURCE_OBJECT_UNAVAILABLE', 'HTTP range/identity/framing mismatch')
            data = response.read(length)
            if len(data) != length:
                raise TransferInterrupted('truncated HTTP range')
            return data
        except (OSError, http.client.HTTPException) as error:
            self.close()
            # Drop the incomplete response; only fully received prior ranges
            # can enter a checkpoint. No automatic reconnect/retry loop.
            raise TransferInterrupted('HTTP connection interrupted') from error
        except (AcquisitionError, TransferInterrupted):
            self.close()
            raise


class AssignedRangeServer(ThreadingHTTPServer):
    """Paired owned helper: loopback only, exact whitelist, one bounded body.

    The operator provisions immutable member files and authenticated records.
    ETags echo that identity; destination final SHA remains the byte authority.
    Call serve_forever/shutdown using the ordinary HTTPServer lifecycle.
    """

    daemon_threads = True

    def __init__(self, root, records, *, port=0, range_bytes=RANGE_BYTES):
        root = Path(root).resolve()
        origins = _origins(records)
        cap = _range_cap(range_bytes)

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def do_GET(self):
                name = unquote(self.path.removeprefix('/'))
                match = re.fullmatch(r'bytes=(\d+)-(\d+)', self.headers.get('Range', ''))
                if match is None:
                    self.send_error(400, 'exact bounded Range required')
                    return
                offset, end = map(int, match.groups())
                length = end - offset + 1
                allowed = next((o for o in origins if o['source_object'] == name
                    and 0 < length <= cap and _contains(o, offset, length)), None)
                if allowed is None:
                    self.send_error(404, 'outside assigned whitelist/cap')
                    return
                etag = '"' + allowed['source_object_digest'] + '"'
                if self.headers.get('If-Match') != etag:
                    self.send_error(412, 'immutable source identity required')
                    return
                try:
                    path = (root/name).resolve()
                    if path.parent != root or not path.is_file():
                        raise OSError('member outside owned root')
                    with path.open('rb') as stream:
                        if os.fstat(stream.fileno()).st_size != allowed['source_object_length']:
                            raise OSError('member size changed')
                        stream.seek(offset)
                        data = stream.read(length)
                    if len(data) != length:
                        raise OSError('short member')
                except OSError:
                    self.send_error(404, 'immutable member unavailable')
                    return
                self.send_response(206)
                self.send_header('Content-Length', str(length))
                self.send_header('Content-Range', f"bytes {offset}-{end}/{allowed['source_object_length']}")
                self.send_header('ETag', etag)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        super().__init__(('127.0.0.1', port), Handler)
