"""#311 experimental llama.cpp participant adapter, offline and no worker spawn.

Successor backing contract for preparation only. The original Q8 runner remains
full-source-both-hosts/1. Coordinator GGUF scaffold, loader reads/hash work and
actual upload boundaries still need a separate runtime integration review.
Fail closed on runtime/assignment/metadata identity drift, wrong native keys or
content, and insufficient disk reserve; never launch a worker on refusal.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import tempfile

from issue99_artifact_core import (
    ARTIFACT_RECORD_SCHEMA, freeze_artifact_record, self_digest, validate_artifact_record,
)
from issue311_preparation import admit_disk, file_identity, fsync_directory, prepare_participant, verify_file
from inferswarm.operator.source import _q8_canonical, fnv, validate_q8_payload

SOURCE_CONTRACT = 'coordinator-full-source/participant-assigned-rpc-backing/1'
NATIVE_PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
PATCH = Path(__file__).resolve().parents[1]/'tools/native-cache/native.patch'
MAX_METADATA_BYTES = 1 << 20


def _runtime_contract(executable_sha256):
    return dict(native_commit=NATIVE_PIN, rpc_major=7,
                patch_sha256=hashlib.sha256(PATCH.read_bytes()).hexdigest(),
                executable_sha256=executable_sha256)


def runtime_identity(executable, expected_sha256):
    if file_identity(executable)[0] != 'sha256:' + expected_sha256:
        raise ValueError('patched runtime executable identity mismatch')
    return _runtime_contract(expected_sha256)


def native_repair_reserve(records_and_keys):
    """Bound retained repair duplication plus one active replacement file.

    First native rename can leave a damaged hardlinked object inode behind.
    Later repairs replace the independent RPC inode, so they do not accumulate
    further copies. Conservatively reserve one extra per unique eligible content
    even if its RPC view is already independent; actual existing copies are also
    charged by admit_disk. No historical content is deleted or credited away.
    """
    eligible = {}
    for record, _ in records_and_keys:
        validate_artifact_record(record)
        if record['length'] > 10 * 1024 * 1024:
            eligible[(record['content_digest'], record['length'])] = record['length']
    return sum(eligible.values()) + max(eligible.values(), default=0) + 16384 * (len(eligible) + 1)


def _check_native_reserve(records_and_keys, budget):
    required = native_repair_reserve(records_and_keys)
    if budget.reserve_bytes < required:
        raise ValueError('native durable repair and replacement temp reserve required')
    return required


def publish_rpc_views(cache, records_and_keys, *, budget, fnv_binary=None):
    """#200 verify/fsync/atomic publication, from verified assigned backing.

    Same-filesystem hardlink publication avoids another weight-sized disk copy.
    SHA/length remain authoritative. Existing wrong/colliding entries are refused
    and preserved; no automatic historical-content deletion. Tiny tensors retain
    backing but are not native hash-hit eligible at the unchanged >10 MiB gate.
    Even low-level composition must supply the configured repair-aware budget.
    """
    records_and_keys = list(records_and_keys)
    _check_native_reserve(records_and_keys, budget)
    admit_disk(cache.root, [r for r, _ in records_and_keys], cache, budget)
    rows = []; keys = {}
    for record, key in records_and_keys:
        validate_artifact_record(record)
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{16}', key):
            raise ValueError('invalid native lookup key')
        identity = (record['content_digest'], record['length'])
        if key in keys and keys[key] != identity: raise ValueError('native lookup collision')
        keys[key] = identity
        path = cache.verified_path(record)
        if fnv(path, fnv_binary) != key: raise ValueError('native lookup key/content mismatch')
        eligible = record['length'] > 10 * 1024 * 1024
        if eligible:
            directory = cache.root/'rpc'; directory.mkdir(exist_ok=True)
            target = directory/key
            if target.exists():
                verify_file(target, record)
            else:
                fd, temporary = tempfile.mkstemp(prefix='.prepare-', dir=directory)
                os.close(fd); Path(temporary).unlink()
                try:
                    os.link(path, temporary)
                    verify_file(temporary, record)
                    with open(temporary, 'rb') as stream: os.fsync(stream.fileno())
                    os.replace(temporary, target)
                    fsync_directory(directory)
                finally: Path(temporary).unlink(missing_ok=True)
            verify_file(target, record)
        rows.append(dict(artifact_id=record['artifact_id'], cache_key=key,
                         native_hash_hit_eligible=eligible, backing_path=str(path)))
    return rows


def project_q8_preparation(payload, *, epoch, runtime):
    """Project a controller-authenticated existing plan; NEVER read source weights.

    The #299 payload validator binds every range/type/shape/owner/revision to the
    metadata authority. Its SHA range descriptors must be independently supplied
    by the controller; a header alone cannot authenticate tensor contents.
    Worker shared metadata consists precisely of immutable native/runtime and
    assigned descriptor dependencies. No tokenizer, other tensors, raw GGUF
    headers or full-source paths are copied to the participant requirement.
    """
    payload = deepcopy(validate_q8_payload(payload))
    if not payload['rpc_cache']: raise ValueError('explicit enabled RPC cache required')
    if type(epoch) is not int or epoch < 0: raise ValueError('invalid preparation epoch')
    expected_runtime = _runtime_contract(runtime.get('executable_sha256'))
    if runtime != expected_runtime or not re.fullmatch('[0-9a-f]{64}', runtime['executable_sha256'] or ''):
        raise ValueError('patched runtime contract required')
    participant = next(p for p in payload['participants'] if p['role'] == 'remote')
    bids = {b['binding_id'] for b in participant['bindings']}
    assigned = sorted((a for a in payload['assignments'] if a['binding_id'] in bids), key=lambda a:a['state_id'])
    descriptors = {c['state_id']: c for c in participant['cache_ranges']}
    members = {m[0]: m for m in payload['model']['members']}
    model = dict(model_id=payload['model']['source_id'], revision=payload['model']['revision'],
                 representation=payload['model']['representation'])
    records = {}; native = []; tensor_dependencies = []
    for assignment in assigned:
        name = assignment['state_id']; c = descriptors[name]; member, digest, size = members[c['member']]
        record = dict(schema=ARTIFACT_RECORD_SCHEMA, kind='byte_range',
            content_digest='sha256:' + c['sha256'], length=c['length'], provenance=model,
            satisfies_logical_state_ids=[name], requirement_class='assigned_logical_state',
            origin=dict(source_object=member, source_object_digest='sha256:' + digest,
                        source_object_length=size, byte_start=c['offset'], byte_end=c['offset']+c['length']))
        record['artifact_id'] = self_digest(record, identity_field='artifact_id')
        records[name] = validate_artifact_record(record)
        native.append((record, c['cache_key']))
        tensor_dependencies.append(dict(assignment, artifact_id=record['artifact_id'],
                                        content_sha256=c['sha256'], cache_key=c['cache_key'], unit_id=c['unit_id']))
    metadata = dict(source_contract=SOURCE_CONTRACT, source_identity=model,
        participant_id=participant['participant_id'], node_id=participant['host_id'],
        metadata_authority_digest=payload['metadata']['metadata_digest'],
        runtime=runtime, tensors=tensor_dependencies)
    metadata_bytes = _q8_canonical(metadata) + b'\n'
    if len(metadata_bytes) > MAX_METADATA_BYTES: raise ValueError('assigned metadata budget exceeded')
    metadata_id = 'native-assigned-descriptors'
    metadata_name = 'assigned-metadata-' + hashlib.sha256(metadata_bytes).hexdigest() + '.json'
    records[metadata_id] = freeze_artifact_record(kind='whole_object', content=metadata_bytes,
        **model, satisfies_logical_state_ids=[metadata_id], requirement_class='required_metadata',
        origin=dict(source_object=metadata_name, source_object_digest='sha256:' + hashlib.sha256(metadata_bytes).hexdigest(),
                    source_object_length=len(metadata_bytes)))
    required = dict(assigned_logical_state=[a['state_id'] for a in assigned],
                    declared_shared_state=[], required_metadata=[metadata_id])
    plan = dict(epoch=epoch, model=model, source_contract=SOURCE_CONTRACT,
        originating_plan_digest=payload['plan_digest'],
        logical_state_units=[dict(id=name) for name in sorted(records)],
        participants=[dict(participant_id=participant['participant_id'], node_id=participant['host_id'],
                           execution_unit_id='native-rpc-participant', required_state=required)])
    plan['plan_digest'] = self_digest(plan, identity_field='plan_digest')
    def resolver(requirement_class, state_id):
        record = records[state_id]
        if record['requirement_class'] != requirement_class: raise ValueError('requirement class drift')
        return [deepcopy(record)]
    return dict(plan=plan, resolver=resolver, records=records, native_ranges=native,
                metadata_bytes=metadata_bytes, metadata_name=metadata_name, metadata=metadata)


class AssignedSource:
    """Direct source with one small exact generated metadata dependency."""
    def __init__(self, origin_source, projection):
        self.origin = origin_source; self.projection = projection
        self.source_id = origin_source.source_id
    def descriptor(self): return self.origin.descriptor()
    def read(self, origin, offset, length):
        if origin['source_object'] == self.projection['metadata_name']:
            return self.projection['metadata_bytes'][offset:offset+length]
        return self.origin.read(origin, offset, length)


def prepare_q8_participant(*, payload, epoch, executable, executable_sha256,
                           node, origin_source, budget, fnv_binary=None):
    """Bounded opt-in adapter, before an independently owned worker startup.

    No Q8 runner admission or runtime launch is implied. A trusted controller
    supplies the reviewed patched executable hash, not the old stock identity.
    """
    from issue101_orchestration import Coordinator
    runtime = runtime_identity(executable, executable_sha256)
    projection = project_q8_preparation(payload, epoch=epoch, runtime=runtime)
    if any(r['length'] > 1 << 20 for r, _ in projection['native_ranges']) and fnv_binary is None:
        raise ValueError('provisioned bounded native FNV helper required')
    required_reserve = _check_native_reserve(projection['native_ranges'], budget)
    if node.node_id != projection['metadata']['node_id']:
        raise ValueError('preparation Node identity mismatch')
    source = AssignedSource(origin_source, projection)
    coordinator = Coordinator(node_sources=[node.descriptor()], origin_sources=[source.descriptor()])
    requirements = coordinator.freeze(projection['plan'], projection['resolver'])
    result = prepare_participant(coordinator=coordinator, requirements=requirements,
        participant_id=projection['metadata']['participant_id'], node=node,
        sources={source.source_id: source}, budget=budget,
        publish_view=lambda cache: publish_rpc_views(cache, projection['native_ranges'], budget=budget, fnv_binary=fnv_binary))
    result.update(source_contract=SOURCE_CONTRACT, originating_plan_digest=payload['plan_digest'],
                  metadata_artifact_id=projection['records']['native-assigned-descriptors']['artifact_id'],
                  runtime=runtime, native_repair_reserve_bytes=required_reserve, q8_runner_integrated=False)
    return result
