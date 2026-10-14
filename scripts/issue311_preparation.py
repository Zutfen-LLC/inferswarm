"""Internal CPU/offline participant preparation successor to #99/#101.

Keep their authority, inventory, delta and interruption contracts; replace only
whole-object cache verification/finalization with bounded file operations. No
runtime spawn, scheduler, eviction, mutable-state recovery or network discovery.
One owned backing directory, one preparation writer, workers stopped during
preparation. Historical producers remain byte-identical.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from issue99_artifact_core import (
    AcquisitionError, CACHE_INVENTORY_SCHEMA, NodeArtifactCache, TransferInterrupted,
    fail, guard_full_object_acquisition, validate_artifact_record, validate_self_identity,
)
from issue101_orchestration import Node

CHUNK_BYTES = 1 << 20


def file_identity(path):
    """SHA-256 and length with at most 1 MiB application read scratch."""
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise fail('UNVERIFIED_SOURCE_READ_REFUSED', 'regular backing file required')
    digest = hashlib.sha256(); length = 0
    with path.open('rb') as stream:
        while block := stream.read(CHUNK_BYTES):
            digest.update(block); length += len(block)
            del block
    return 'sha256:' + digest.hexdigest(), length


def verify_file(path, record):
    if file_identity(path) != (record['content_digest'], record['length']):
        raise fail('CACHE_OBJECT_TAMPERED', record['content_digest'])
    return Path(path)


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


class StreamingArtifactCache(NodeArtifactCache):
    """Same durable #99 layout and recovery binding; no full-object reads."""

    def verified_path(self, record):
        validate_artifact_record(record)
        path = self.lookup(record['content_digest'])
        if path is None:
            raise fail('UNVERIFIED_SOURCE_READ_REFUSED', record['content_digest'])
        return verify_file(path, record)

    def has_verified(self, record):
        validate_artifact_record(record)
        if self.lookup(record['content_digest']) is None: return False
        self.verified_path(record)
        return True

    def open_verified(self, record):
        raise ValueError('use verified_path and bounded reads for streaming backing')

    def finish_partial(self, record):
        retained = self._require_matching_partial(record)
        if retained != record['length']:
            raise fail('INTEGRITY_DIGEST_MISMATCH', 'incomplete partial')
        part = self._part_path(record['artifact_id'])
        try: verify_file(part, record)
        except AcquisitionError as error:
            raise fail('INTEGRITY_DIGEST_MISMATCH', str(error)) from error
        with self._lock:
            target = self.root / 'objects' / record['content_digest'].replace(':', '-')
            if target.exists():
                verify_file(target, record)
            else:
                with part.open('rb') as stream: os.fsync(stream.fileno())
                os.replace(part, target)
                fsync_directory(target.parent)
            self._discard_partial_locked(record['artifact_id'])
        return verify_file(target, record)

    def _write_state_locked(self, record, retained):
        # State publication cannot turn an incomplete prefix into verified data.
        state = dict(artifact_id=record['artifact_id'], content_digest=record['content_digest'],
                     length=record['length'], retained_bytes=retained)
        target = self._state_path(record['artifact_id'])
        fd, name = tempfile.mkstemp(prefix='.state-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(state, stream, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(name, target)
            fsync_directory(target.parent)
        finally: Path(name).unlink(missing_ok=True)

    def resume_partial(self, record):
        state = self.partial_state(record['artifact_id'])
        if state is None: return 0
        if (not isinstance(state, dict)
                or set(state) != {'artifact_id', 'content_digest', 'length', 'retained_bytes'}
                or type(state['retained_bytes']) is not int
                or not 0 <= state['retained_bytes'] <= record['length']):
            self.discard_partial(record['artifact_id'])
            raise fail('PARTIAL_STATE_IDENTITY_MISMATCH', 'invalid retained extent')
        return super().resume_partial(record)

    def inventory(self):
        objects = []
        for path in sorted((self.root / 'objects').iterdir()):
            if not re.fullmatch('sha256-[0-9a-f]{64}', path.name): continue
            try: digest, length = file_identity(path)
            except (OSError, AcquisitionError): continue
            objects.append(dict(content_digest=path.name.replace('-', ':', 1), length=length,
                                byte_digest_verified=digest == path.name.replace('-', ':', 1)))
        # Unknown/stale sidecars cannot satisfy inventory. They still consume disk.
        return dict(schema=CACHE_INVENTORY_SCHEMA, cache_root=str(self.root),
                    verified_objects=objects, partial_transfers=[],
                    verified_bytes=sum(o['length'] for o in objects if o['byte_digest_verified']),
                    partial_bytes=sum(p.stat().st_size for p in (self.root/'partial').glob('*.part')))


class StreamingNode(Node):
    def source(self, record):
        node = self
        path = node.cache.verified_path(record)
        class Source:
            source_id = node.node_id
            def descriptor(self): return node.descriptor()
            def read(self, origin, offset, length):
                if origin != record['origin']: raise fail('PROVENANCE_IDENTITY_MISMATCH', 'peer origin')
                base = origin['byte_start'] if record['kind'] == 'byte_range' else 0
                start = offset - base
                if start < 0 or start + length > record['length']:
                    raise fail('SOURCE_OBJECT_UNAVAILABLE', 'peer extent')
                # One source verification per acquisition. The destination's
                # final SHA check also rejects any source drift during transfer.
                with path.open('rb') as stream:
                    stream.seek(start)
                    return stream.read(length)
        return Source()


@dataclass(frozen=True)
class DiskBudget:
    limit_bytes: int
    min_free_bytes: int
    # Reserve native replacement temp / filesystem and metadata overhead explicitly.
    reserve_bytes: int

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in
               (self.limit_bytes, self.min_free_bytes, self.reserve_bytes)):
            raise ValueError('invalid configured disk budget')


def backing_usage(root):
    """Count every retained file, including foreign/history/partials, once per inode.

    Charge max(logical length, allocated blocks): hardlinked RPC views do not
    duplicate weight charges, and sparse/rounded files do not evade admission.
    """
    seen = set(); total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(directory)/name; info = path.lstat()
            if stat.S_ISLNK(info.st_mode): raise ValueError('backing symlinks unsupported')
            identity = (info.st_dev, info.st_ino)
            if identity in seen: continue
            seen.add(identity)
            total += max(info.st_size, info.st_blocks * 512)
    return total


def admit_disk(root, records, cache, budget):
    unique = {r['content_digest']: r for r in records if not cache.has_verified(r)}
    # Conservative: do not credit partial prefixes; state/directory overhead and
    # future native repair temp must fit even while all historical files remain.
    missing = sum(r['length'] + 16384 for r in unique.values())
    used = backing_usage(root)
    if used + missing + budget.reserve_bytes > budget.limit_bytes:
        raise ValueError('configured backing disk budget exceeded')
    free = shutil.disk_usage(root).free
    if free < missing + budget.reserve_bytes + budget.min_free_bytes:
        raise ValueError('configured filesystem free headroom unavailable')
    return dict(retained_bytes=used, acquisition_upper_bytes=missing,
                reserve_bytes=budget.reserve_bytes, limit_bytes=budget.limit_bytes,
                min_free_bytes=budget.min_free_bytes)


@contextmanager
def preparation_lock(root):
    with (Path(root)/'.prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


class _ExactReads:
    def __init__(self, source): self.source = source
    @property
    def source_id(self): return self.source.source_id
    def descriptor(self): return self.source.descriptor()
    def read(self, origin, offset, length):
        try: data = self.source.read(origin, offset, length)
        except TransferInterrupted as error:
            if len(error.partial) > length: raise fail('SOURCE_OBJECT_UNAVAILABLE', 'oversized interruption')
            raise
        if len(data) != length:
            raise fail('SOURCE_OBJECT_UNAVAILABLE', 'short/oversized read')
        return data


def prepare_participant(*, coordinator, requirements, participant_id, node, sources, budget,
                        publish_view=None):
    """Prepare exactly the issued participant requirement; reconcile backing only.

    Sources are explicitly provisioned #101 descriptors. No discovery/fetch of
    unrelated model content. The caller supplies a StreamingNode and stops its
    owned runtime before entering this one-writer preparation transaction.
    """
    if not isinstance(node.cache, StreamingArtifactCache): raise ValueError('streaming cache required')
    validate_self_identity(requirements, identity_field='requirements_digest')
    selected = [p for p in requirements['participants'] if p['participant_id'] == participant_id]
    if len(selected) != 1: raise fail('RECONCILIATION_MISMATCH', 'participant selection')
    participant = selected[0]; records = participant['required_artifacts']
    guard_full_object_acquisition(records)
    with preparation_lock(node.cache.root):
        coordinator.ingest(node.inventory())
        delta = coordinator.delta(participant_id)
        if (delta['participant_requirements_digest'] != participant['participant_requirements_digest']
                or delta['node_id'] != node.node_id):
            raise fail('RECONCILIATION_MISMATCH', 'unissued requirements')
        admission = admit_disk(node.cache.root, records, node.cache, budget)
        start = len(node.ledger.events); results = []; materializations = []
        for record in records:
            ticket = coordinator.authorize(delta, record['artifact_id'])
            source = node.source(record) if ticket['mode'] == 'LOCAL_CACHE' else sources[ticket['source']['source_id']]
            result = node.acquire(coordinator, ticket, _ExactReads(source))
            results.append(result)
            if result['status'] == 'INTERRUPTED':
                return dict(status='INTERRUPTED', delta=delta, admission=admission, results=results)
            path = node.cache.verified_path(record)
            for state in record['satisfies_logical_state_ids']:
                materializations.append(dict(logical_state_id=state, participant_id=participant_id,
                    node_id=node.node_id, epoch=ticket['epoch'], verification='VERIFIED_CACHE_SOURCE',
                    expected_bytes=record['length'], observed_bytes=record['length'], backing_path=str(path)))
        view = publish_view(node.cache) if publish_view is not None else None
        # Recheck accounting before emitting success; no eviction/retry-until-pass.
        admit_disk(node.cache.root, records, node.cache, budget)
        reconciliation = coordinator.reconcile(participant_id,
            [r['artifact_id'] for r in records], materializations)
        events = node.ledger.events[start:]
        return dict(status='VERIFIED_BACKING-not-consumed', delta=delta, admission=admission,
            acquisition_bytes=sum(e['bytes'] for e in events if e['event'] == 'ACQUIRED'),
            reuse_bytes=sum(e['bytes'] for e in events if e['event'] == 'CACHE_HIT'),
            application_read_chunk_bytes=CHUNK_BYTES, results=results,
            reconciliation=reconciliation, backend_view=view,
            physical_observation=False, cache_consumed=False)
