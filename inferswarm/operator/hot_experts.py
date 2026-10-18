"""Experimental #314 immutable intent and bounded, exact Q8_0 slice gather.

No selection, dequantization, model loading, placement, or ordinary ownership
changes occur here. INTENT binds source object identity and ordered IDs; only
prepare() authenticates bytes and supplies actual compact SHA-256 identities.
Freeze manifest.sha256 out of band. The self digest is canonical payload JSON
excluding the sha256 field, NOT a checksum supplied by the manifest itself.
Prepared files instead use SHA-256 of their complete raw canonical JSON bytes.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

_COMPONENTS = ('gate', 'up', 'down')
_MAX_JSON = 1 << 20
_MAX_STAGING = 8704000
_NATIVE_SOURCE = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _digest(value, label):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError(label + ' must be a lowercase SHA-256')
    return value


def _integer(value, label, minimum=0, maximum=(1 << 63) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(label + ' is out of bounds')
    return value


def _fields(value, keys, label):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError(label + ' must have exact fields')


def _text(value, label, maximum=1024):
    if type(value) is not str or not value or len(value) > maximum or '\x00' in value:
        raise ValueError(label + ' must be bounded nonempty text')
    return value


def _decode(data):
    if type(data) is not bytes or not data or len(data) > _MAX_JSON:
        raise ValueError('canonical JSON must be bounded bytes')
    try:
        value = json.loads(data)
        if _canonical(value) != data:
            raise ValueError('canonical JSON bytes required')
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('canonical JSON bytes required') from exc


def encoded_expert_bytes(shape):
    """Whole Q8_0 rows: one 34-byte block for each 32 encoded values."""
    if type(shape) is not list or len(shape) != 4:
        raise ValueError('source shape must have four dimensions')
    for value in shape:
        _integer(value, 'source shape dimension', 1, (1 << 31) - 1)
    if shape[0] % 32 or shape[3] != 1:
        raise ValueError('source shape requires whole Q8_0 rows and singleton fourth dimension')
    result = shape[0] // 32 * 34 * shape[1]
    _integer(result * shape[2], 'source shape encoded length', 1)
    return result


def _validate_payload(payload):
    _fields(payload, 'schema status model representation native_source provenance_bundle_sha256 '
            'capture_provenance_sha256 layer expert_ids sources', 'manifest')
    if payload['schema'] != 'is314-hot-expert-manifest/1' or payload['status'] != 'INTENT':
        raise ValueError('immutable INTENT manifest schema required')
    if payload['representation'] != 'Q8_0' or payload['native_source'] != _NATIVE_SOURCE:
        raise ValueError('Q8_0 and pinned native source required')
    _fields(payload['model'], 'repository revision metadata_sha256', 'model')
    _text(payload['model']['repository'], 'model repository')
    _text(payload['model']['revision'], 'model revision')
    _digest(payload['model']['metadata_sha256'], 'model metadata digest')
    _digest(payload['provenance_bundle_sha256'], 'provenance bundle digest')
    if payload['capture_provenance_sha256'] is not None:
        _digest(payload['capture_provenance_sha256'], 'capture provenance digest')
    _integer(payload['layer'], 'layer', 0, 511)
    ids = payload['expert_ids']
    if type(ids) is not list or not 1 <= len(ids) <= 512:
        raise ValueError('explicit nonempty ordered expert IDs required')
    for expert in ids:
        _integer(expert, 'expert ID', 0, 511)
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate expert ID')
    sources = payload['sources']
    if type(sources) is not list or len(sources) != 3:
        raise ValueError('exact gate/up/down source list required')
    members = {}
    for component, source in zip(_COMPONENTS, sources):
        _fields(source, 'component name member member_sha256 member_size_bytes tensor_offset '
                'shape ggml_type tensor_sha256', 'source')
        if source['component'] != component:
            raise ValueError('sources must be ordered gate/up/down')
        if source['name'] != f"blk.{payload['layer']}.ffn_{component}_exps.weight":
            raise ValueError('source name does not match layer/component')
        if type(source['ggml_type']) is not int or source['ggml_type'] != 8:
            raise ValueError('source must be Q8_0 type 8')
        _text(source['member'], 'member name', 255)
        if Path(source['member']).name != source['member'] or source['member'] in ('.', '..'):
            raise ValueError('member name must be a single basename')
        _digest(source['member_sha256'], 'member SHA-256')
        _integer(source['member_size_bytes'], 'member size', 1)
        _integer(source['tensor_offset'], 'tensor offset')
        size = encoded_expert_bytes(source['shape']) * source['shape'][2]
        if any(expert >= source['shape'][2] for expert in ids):
            raise ValueError('expert ID outside source shape')
        if source['tensor_offset'] + size > source['member_size_bytes']:
            raise ValueError('source tensor bounds exceed member')
        if source['tensor_sha256'] is not None:
            _digest(source['tensor_sha256'], 'tensor SHA-256')
        identity = (source['member_sha256'], source['member_size_bytes'])
        if source['member'] in members and members[source['member']] != identity:
            raise ValueError('conflicting source member identities')
        members[source['member']] = identity


def seal_manifest(payload):
    """Seal explicit intent. This is not acceptance; retain the digest externally."""
    payload = json.loads(_canonical(payload))
    _validate_payload(payload)
    return _canonical(dict(payload, sha256=hashlib.sha256(_canonical(payload)).hexdigest()))


@dataclass(frozen=True)
class HotExpertManifest:
    canonical_bytes: bytes
    sha256: str

    @property
    def expert_ids(self):
        return tuple(self.payload()['expert_ids'])

    def payload(self):
        result = json.loads(self.canonical_bytes)
        del result['sha256']
        return result


def load_manifest(data, *, expected_sha256):
    _digest(expected_sha256, 'expected manifest digest')
    value = _decode(data)
    if type(value) is not dict or 'sha256' not in value:
        raise ValueError('manifest self digest required')
    claimed = value.pop('sha256')
    _digest(claimed, 'manifest self digest')
    actual = hashlib.sha256(_canonical(value)).hexdigest()
    if actual != claimed:
        raise ValueError('manifest self digest mismatch')
    if actual != expected_sha256:
        raise ValueError('expected manifest digest mismatch')
    _validate_payload(value)
    return HotExpertManifest(data, actual)


def _checked_manifest(manifest):
    if not isinstance(manifest, HotExpertManifest):
        raise ValueError('validated immutable manifest required')
    return load_manifest(manifest.canonical_bytes, expected_sha256=manifest.sha256)


def compact_byte_counts(manifest):
    payload = _checked_manifest(manifest).payload()
    result = {s['component']: encoded_expert_bytes(s['shape']) * len(payload['expert_ids'])
              for s in payload['sources']}
    return dict(result, total=sum(result.values()))


def _backend(backend):
    _text(backend, 'RPC backend', 255)
    if not backend.startswith('RPC') or any(c.isspace() for c in backend):
        raise ValueError('exact RPC backend name required')
    return backend


def _native_spec(manifest, backend, hashes):
    _backend(backend)
    payload = manifest.payload()
    tensors = []
    for source in payload['sources']:
        component = source['component']
        source_sha, compact_sha = hashes[component]
        _digest(source_sha, 'derived source SHA-256')
        _digest(compact_sha, 'derived compact SHA-256')
        if source['tensor_sha256'] is not None and source_sha != source['tensor_sha256']:
            raise ValueError('source tensor SHA-256 mismatch')
        size = encoded_expert_bytes(source['shape'])
        shape = source['shape'][:2] + [len(payload['expert_ids']), 1]
        tensors.append(dict(source_name=source['name'],
            compact_name=f'is314.{manifest.sha256[:16]}.{component}', ggml_type=8,
            source_shape=source['shape'], compact_shape=shape, source_sha256=source_sha,
            compact_sha256=compact_sha, expert_bytes=size,
            ranges=[dict(expert_id=expert, source_offset=expert * size,
                destination_offset=local * size, length=size)
                for local, expert in enumerate(payload['expert_ids'])]))
    return dict(schema='is314-hot-experts/1', layer=payload['layer'],
                rpc_backend=backend, expert_ids=payload['expert_ids'], tensors=tensors)


def _guard(spec):
    return ''.join(' '.join(map(str, [t['compact_name'], t['ggml_type'],
        *t['compact_shape'], t['expert_bytes'] * len(spec['expert_ids']),
        t['compact_sha256']])) + '\n' for t in spec['tensors']).encode('ascii')


@dataclass(frozen=True)
class PreparedHotExperts:
    canonical_bytes: bytes

    def native_spec(self):
        return json.loads(self.canonical_bytes)['native_spec']

    @property
    def native_spec_bytes(self):
        return _canonical(self.native_spec())

    def assigned_lines(self):
        return _guard(self.native_spec())

    @property
    def assigned_guard(self):
        return self.assigned_lines()

    @property
    def source_records(self):
        body = json.loads(self.canonical_bytes)
        sources = body['manifest']['sources']
        for source, tensor in zip(sources, body['native_spec']['tensors']):
            source['tensor_sha256'] = tensor['source_sha256']
        return tuple(sources)

    def report(self):
        return json.loads(self.canonical_bytes)['report']


def _report(manifest, peak, limit):
    sizes = compact_byte_counts(manifest)
    return dict(manifest_sha256=manifest.sha256,
        global_to_local={str(expert): local for local, expert in enumerate(manifest.expert_ids)},
        compact_bytes={c: sizes[c] for c in _COMPONENTS}, total_compact_bytes=sizes['total'],
        peak_staging_bytes=peak, max_staging_bytes=limit,
        original_cpu_banks_retained=True, quantization_conversion=False)


def load_prepared(data, *, expected_sha256):
    """Validate raw-file pin, immutable intent, and exact native/guard lowering.

    The digest authenticates the controller's reviewed prepared artifact. It
    does not substitute for validate_prepared_sources against the runner's
    independently verified full CPU source receipt and model metadata.
    """
    _digest(expected_sha256, 'expected prepared SHA-256')
    if type(data) is not bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('prepared file SHA-256 mismatch')
    body = _decode(data)
    _fields(body, 'schema manifest native_spec report', 'prepared')
    if body['schema'] != 'is314-prepared-hot-experts/1':
        raise ValueError('prepared schema mismatch')
    value = body['manifest']
    if type(value) is not dict:
        raise ValueError('prepared immutable manifest missing')
    manifest = load_manifest(_canonical(value), expected_sha256=value.get('sha256'))
    spec = body['native_spec']
    try:
        hashes = {component: (tensor['source_sha256'], tensor['compact_sha256'])
                  for component, tensor in zip(_COMPONENTS, spec['tensors'])}
        expected = _native_spec(manifest, spec['rpc_backend'], hashes)
        if _canonical(expected) != _canonical(spec):
            raise ValueError('prepared native spec mismatch')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('prepared native spec malformed') from exc
    report = body['report']
    if type(report) is not dict:
        raise ValueError('prepared report required')
    limit = _integer(report.get('max_staging_bytes'), 'staging limit', 1, _MAX_STAGING)
    peak = _integer(report.get('peak_staging_bytes'), 'staging peak', 1, limit)
    if report != _report(manifest, peak, limit):
        raise ValueError('prepared report mismatch')
    return PreparedHotExperts(data)


def _span_hash(stream, offset, length, buffer, checkpoint=None):
    stream.seek(offset)
    remaining, digest = length, hashlib.sha256()
    view = memoryview(buffer)
    while remaining:
        if checkpoint is not None:
            checkpoint()
        count = stream.readinto(view[:min(remaining, len(buffer))])
        if not count:
            raise ValueError('source span truncated')
        digest.update(view[:count])
        remaining -= count
    return digest.hexdigest()


def _stat_identity(stream):
    value = os.fstat(stream.fileno())
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def prepare(manifest, source_paths, *, rpc_backend, output_paths=None,
            max_staging_bytes=_MAX_STAGING, checkpoint=None):
    """Authenticate source members, then gather full encoded slices in ID order.

    At most one reusable slice-sized (capped at 1 MiB) bytearray is resident.
    Hash-only preparation needs no persistent staging; native context setup
    gathers the same slices from retained CPU tensors once. Optional outputs
    are new complete tensors, never source views or overwrites. A failed call
    removes only files exclusively created by that invocation.
    """
    if checkpoint is not None:
        checkpoint()
    manifest = _checked_manifest(manifest)
    payload = manifest.payload()
    sources = payload['sources']
    _integer(max_staging_bytes, 'staging limit', 1, _MAX_STAGING)
    largest = max(encoded_expert_bytes(s['shape']) for s in sources)
    if max_staging_bytes < largest:
        raise ValueError('staging limit must hold one complete expert slice')
    # Validate backend before opening any files.
    _backend(rpc_backend)
    required = {s['member'] for s in sources}
    if type(source_paths) is not dict or set(source_paths) != required:
        raise ValueError('exact source member paths required')
    destinations = {}
    if output_paths is not None:
        if type(output_paths) is not dict or set(output_paths) != set(_COMPONENTS):
            raise ValueError('exact gate/up/down output paths required')
        destinations = {c: Path(output_paths[c]) for c in _COMPONENTS}
        resolved = [p.resolve() for p in destinations.values()]
        if len(set(resolved)) != len(resolved):
            raise ValueError('duplicate output destinations')
        if set(resolved) & {Path(p).resolve() for p in source_paths.values()}:
            raise ValueError('output aliases source member')
        for path in destinations.values():
            if os.path.lexists(path):
                raise ValueError('output destination exists: ' + str(path))
    size = min(max_staging_bytes, largest, 1 << 20)
    buffer = bytearray(size)
    created = []
    try:
        with ExitStack() as stack:
            streams = {name: stack.enter_context(Path(source_paths[name]).open('rb', buffering=0))
                       for name in required}
            identities = {name: _stat_identity(stream) for name, stream in streams.items()}
            members = {s['member']: s for s in sources}
            for name, stream in streams.items():
                source = members[name]
                if (identities[name][2] != source['member_size_bytes'] or
                        _span_hash(stream, 0, source['member_size_bytes'], buffer, checkpoint) != source['member_sha256']):
                    raise ValueError('source member SHA-256/size mismatch: ' + name)
            hashes = {}
            # Finish every authentication check before publishing any output.
            for source in sources:
                length = encoded_expert_bytes(source['shape']) * source['shape'][2]
                actual = _span_hash(streams[source['member']], source['tensor_offset'], length, buffer, checkpoint)
                if source['tensor_sha256'] is not None and actual != source['tensor_sha256']:
                    raise ValueError('source tensor SHA-256 mismatch: ' + source['name'])
                hashes[source['component']] = [actual, None]
            outputs = {}
            for component, path in destinations.items():
                try:
                    output = path.open('xb', buffering=0)
                except FileExistsError as exc:
                    raise ValueError('output destination exists: ' + str(path)) from exc
                created.append(path)
                outputs[component] = stack.enter_context(output)
            for source in sources:
                component = source['component']
                stream = streams[source['member']]
                expert_bytes = encoded_expert_bytes(source['shape'])
                digest = hashlib.sha256()
                view = memoryview(buffer)
                for expert in payload['expert_ids']:
                    stream.seek(source['tensor_offset'] + expert * expert_bytes)
                    remaining = expert_bytes
                    while remaining:
                        if checkpoint is not None:
                            checkpoint()
                        count = stream.readinto(view[:min(remaining, size)])
                        if not count:
                            raise ValueError('source expert slice truncated')
                        digest.update(view[:count])
                        if component in outputs:
                            chunk = view[:count]
                            while chunk:
                                written = outputs[component].write(chunk)
                                if not written:
                                    raise OSError('short compact output write')
                                chunk = chunk[written:]
                        remaining -= count
                hashes[component][1] = digest.hexdigest()
            for name, stream in streams.items():
                if _stat_identity(stream) != identities[name]:
                    raise ValueError('source member changed during preparation')
        spec = _native_spec(manifest, rpc_backend, hashes)
        data = _canonical(dict(schema='is314-prepared-hot-experts/1',
            manifest=json.loads(manifest.canonical_bytes), native_spec=spec,
            report=_report(manifest, size, max_staging_bytes)))
        return load_prepared(data, expected_sha256=hashlib.sha256(data).hexdigest())
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def validate_prepared_sources(prepared, metadata, source_receipt):
    """Join reviewed gather to already verified CPU source; never verifies a host."""
    prepared = load_prepared(prepared.canonical_bytes,
        expected_sha256=hashlib.sha256(prepared.canonical_bytes).hexdigest())
    payload = json.loads(prepared.canonical_bytes)['manifest']
    model = payload['model']
    identity = dict(source_id=model['repository'], revision=model['revision'], representation='Q8_0')
    if (metadata.get('source') != identity or metadata.get('metadata_digest') != model['metadata_sha256']):
        raise ValueError('source metadata model identity mismatch')
    receipt = source_receipt
    if (receipt.get('schema') != 'q8-source-receipt/1' or receipt.get('status') != 'VERIFIED-not-consumed'
            or receipt.get('role') != 'client' or receipt.get('backing') != 'full-source'
            or receipt.get('source_identity') != identity
            or receipt.get('metadata_digest') != model['metadata_sha256']):
        raise ValueError('source receipt must authenticate actual full CPU source')
    tensors = {t['state_id']: t for t in metadata.get('tensors', [])}
    ranges = {t['state_id']: t for t in receipt.get('range_identities', [])}
    members = {m[0]: (m[1], m[2]) for m in receipt.get('member_identities', [])}
    for source in prepared.source_records:
        length = encoded_expert_bytes(source['shape']) * source['shape'][2]
        tensor = tensors.get(source['name'], {})
        if (tensor.get('shape') != source['shape'][:3] or tensor.get('ggml_type') != 8
                or tensor.get('member') != source['member']
                or tensor.get('absolute_offset') != source['tensor_offset']
                or tensor.get('encoded_bytes') != length):
            raise ValueError('source metadata tensor descriptor mismatch')
        if (source['member'] not in receipt.get('verified_members', []) or
                members.get(source['member']) != (source['member_sha256'], source['member_size_bytes'])):
            raise ValueError('source receipt member identity mismatch')
        row = ranges.get(source['name'], {})
        if (row.get('member') != source['member'] or row.get('offset') != source['tensor_offset']
                or row.get('length') != length or row.get('sha256') != source['tensor_sha256']):
            raise ValueError('source receipt tensor range SHA-256 mismatch')
