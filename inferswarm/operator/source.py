"""Read-only on-host authentication of runtime, full GGUF members and assigned RPC cache.

This file is self-contained so the controller can send it to a participant via
`ssh python3 -c ...` without requiring an installed product package there.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

# GGML quant block widths at the accepted runtime pin (GGUF v3).
TYPES = {0:(1,4),1:(1,2),2:(32,18),3:(32,20),6:(32,22),7:(32,24),8:(32,34),9:(32,40),
         10:(256,84),11:(256,110),12:(256,144),13:(256,176),14:(256,210),15:(256,292),
         16:(256,66),17:(256,74),18:(256,98),19:(256,50),20:(32,18),21:(256,110),
         22:(256,82),23:(256,82),24:(1,1),25:(1,2),26:(1,4),27:(1,8),28:(1,8),
         29:(256,56),30:(1,2),34:(256,54),35:(256,66),39:(32,17),40:(64,36),
         41:(128,18),42:(64,18)}
SCALAR = {0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
KEY = re.compile(r'[0-9a-f]{16}\Z')

FNV_C = r'''#include <stdint.h>
#include <stdio.h>
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 3;
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    unsigned char b[1048576]; size_t n;
    while ((n = fread(b,1,sizeof b,f)))
        for (size_t i=0;i<n;++i) h=(h^b[i])*UINT64_C(0x100000001b3);
    if (ferror(f)) return 4;
    fclose(f); printf("%016llx\n",(unsigned long long)h); return 0;
}'''


def compile_fnv(binary):
    """Create only the configured invocation-local helper, never a global binary."""
    binary=Path(binary)
    if binary.exists(): raise ValueError('native FNV artifact already exists')
    subprocess.run(['cc','-O2','-std=c11','-x','c','-o',str(binary),'-'],input=FNV_C,text=True,
                   capture_output=True,check=True,timeout=30)



MAX_HEADER_BYTES = 16 << 20
MAX_EXTENT_BYTES = (1 << 63) - 1


@dataclass(frozen=True)
class TensorRecord:
    """A descriptor, not verified tensor contents. Member is bound by the caller."""
    state_id: str
    member: str
    ggml_type: int
    shape: tuple[int, ...]
    relative_offset: int
    absolute_offset: int
    encoded_bytes: int


def _encoded_bytes(shape, typ):
    if typ not in TYPES: raise ValueError(f'unsupported GGUF tensor type: {typ}')
    if not 1 <= len(shape) <= 4: raise ValueError('invalid GGUF tensor dimensions')
    elements = 1
    for dimension in shape:
        if type(dimension) is not int or not 1 <= dimension <= MAX_EXTENT_BYTES // elements:
            raise ValueError('invalid GGUF shape')
        elements *= dimension
    block, width = TYPES[typ]
    if shape[0] % block: raise ValueError('block-incompatible GGUF shape')
    size = elements // block * width
    if not 1 <= size <= MAX_EXTENT_BYTES: raise ValueError('invalid GGUF encoded extent')
    return size


def _validate_extents(rows, object_bytes, start, alignment):
    """Allow only actual alignment padding, never infer sizes from next offsets."""
    if start > object_bytes: raise ValueError('out-of-bounds GGUF header')
    ordered = sorted(rows, key=lambda r: r.relative_offset)
    previous_end = start
    for row in ordered:
        if row.relative_offset % alignment: raise ValueError('unaligned GGUF offset')
        if row.absolute_offset != start + row.relative_offset:
            raise ValueError('GGUF absolute offset mismatch')
        end = row.absolute_offset + row.encoded_bytes
        if end > object_bytes: raise ValueError('out-of-bounds GGUF tensor')
        if row.absolute_offset < previous_end: raise ValueError('overlapping GGUF tensor')
        if row.absolute_offset != (previous_end + alignment - 1) // alignment * alignment:
            raise ValueError('GGUF extent mismatch')
        previous_end = end
    if object_bytes not in (previous_end, (previous_end + alignment - 1) // alignment * alignment):
        raise ValueError('GGUF extent mismatch')


def _read_gguf_index(stream, *, object_bytes):
    """Self-contained stream decoder shared by bounded headers and legacy files.

    Read only metadata/index bytes, not even header alignment or tensor prefixes.
    Tokenizer values are consumed but not retained. Counts, total reads, retained
    strings/arrays and shape arithmetic have independent finite bounds.
    """
    consumed = 0
    def read(n):
        nonlocal consumed
        if n < 0 or consumed + n > MAX_HEADER_BYTES: raise ValueError('oversized GGUF header')
        data = stream.read(n)
        consumed += len(data)
        if len(data) != n: raise ValueError('truncated GGUF metadata')
        return data
    def scalar(fmt):
        result = struct.unpack('<' + fmt, read(struct.calcsize('<' + fmt)))[0]
        if isinstance(result, float) and not math.isfinite(result): raise ValueError('nonfinite GGUF metadata')
        return result
    def text(*, retain=True, maximum=MAX_HEADER_BYTES):
        n = scalar('Q')
        if n > maximum: raise ValueError('oversized GGUF string')
        # Strings discarded from fixtures still undergo UTF-8 validation.
        try: value = read(n).decode('utf-8')
        except UnicodeDecodeError as exc: raise ValueError('invalid GGUF UTF-8') from exc
        return value if retain else None
    def value(typ, retain):
        if typ == 8: return text(retain=retain, maximum=65536 if retain else MAX_HEADER_BYTES)
        if typ == 9:
            subtype, n = scalar('I'), scalar('Q')
            if n > (4096 if retain else 1 << 20): raise ValueError('oversized GGUF array')
            if subtype not in SCALAR and subtype != 8: raise ValueError('unsupported GGUF array subtype')
            items = [] if retain else None
            for _ in range(n):
                item = text(retain=retain, maximum=65536 if retain else MAX_HEADER_BYTES) if subtype == 8 else scalar(SCALAR[subtype])
                if retain: items.append(item)
            return tuple(items) if retain else None
        if typ not in SCALAR: raise ValueError('unsupported GGUF metadata type')
        return scalar(SCALAR[typ])
    if read(4) != b'GGUF' or scalar('I') != 3: raise ValueError('expected GGUF v3')
    n_tensor, n_kv = scalar('Q'), scalar('Q')
    if n_tensor > 100000 or n_kv > 10000: raise ValueError('oversized GGUF index')
    metadata = {}; keys = set()
    for _ in range(n_kv):
        key, typ = text(maximum=4096), scalar('I')
        if not key or '\x00' in key: raise ValueError('invalid GGUF metadata key')
        if key in keys: raise ValueError('duplicate GGUF metadata')
        keys.add(key)
        retain = not key.startswith('tokenizer.')
        item = value(typ, retain)
        if retain: metadata[key] = item
    alignment = metadata.get('general.alignment', 32)
    if type(alignment) is not int or not 1 <= alignment <= 4096 or alignment & (alignment - 1):
        raise ValueError('invalid GGUF alignment')
    split = {'split.no', 'split.count', 'split.tensors.count'}
    if keys & split:
        if not split <= keys: raise ValueError('invalid GGUF split')
        number, count, total = (metadata[k] for k in ('split.no', 'split.count', 'split.tensors.count'))
        if any(type(v) is not int for v in (number, count, total)) or not 1 <= count <= 1024 or not 0 <= number < count or not n_tensor <= total <= 100000:
            raise ValueError('invalid GGUF split')
    entries = []; names = set()
    for _ in range(n_tensor):
        name, nd = text(maximum=4096), scalar('I')
        if not name or '\x00' in name: raise ValueError('invalid GGUF tensor name')
        if name in names: raise ValueError('duplicate GGUF tensor')
        names.add(name)
        if not 1 <= nd <= 4: raise ValueError('invalid GGUF tensor dimensions')
        shape = tuple(scalar('Q') for _ in range(nd))
        typ, offset = scalar('I'), scalar('Q')
        length = _encoded_bytes(shape, typ)
        entries.append((name, typ, shape, offset, length))
    start = (consumed + alignment - 1) // alignment * alignment
    rows = tuple(TensorRecord(name, '', typ, shape, offset, start + offset, length)
                 for name, typ, shape, offset, length in entries)
    _validate_extents(rows, object_bytes, start, alignment)
    return tuple(sorted(metadata.items())), rows, consumed


def parse_gguf_header(header: bytes, *, object_bytes: int, expected_header_sha256: str) -> tuple:
    """Return (immutable metadata pairs, TensorRecord tuple) from exact header bytes.

    Header SHA authentication is NOT full-object or tensor-range authentication.
    No package imports are needed when this file is sent as `python3 -c` source.
    """
    if type(object_bytes) is not int or not 1 <= object_bytes <= MAX_EXTENT_BYTES:
        raise ValueError('invalid object_bytes')
    if not isinstance(expected_header_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_header_sha256):
        raise ValueError('invalid header SHA-256')
    if type(header) is not bytes or len(header) > MAX_HEADER_BYTES: raise ValueError('oversized GGUF header')
    if hashlib.sha256(header).hexdigest() != expected_header_sha256: raise ValueError('header SHA-256 mismatch')
    metadata, rows, consumed = _read_gguf_index(io.BytesIO(header), object_bytes=object_bytes)
    if consumed != len(header): raise ValueError('unexpected bytes after GGUF header')
    return metadata, rows


def gguf_tensors(path):
    """Return tensor -> exact (absolute offset, size), never read tensor data."""
    with Path(path).open('rb') as stream:
        _, rows, _ = _read_gguf_index(stream, object_bytes=os.fstat(stream.fileno()).st_size)
    return {row.state_id: (row.absolute_offset, row.encoded_bytes) for row in rows}


def sha(path, offset=0, length=None):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        f.seek(offset)
        remaining=length
        while remaining is None or remaining:
            block=f.read(8<<20 if remaining is None else min(8<<20,remaining))
            if not block: break
            h.update(block)
            if remaining is not None: remaining-=len(block)
    if remaining: raise ValueError(f'short source range: {path}')
    return h.hexdigest()


def fnv(path, binary=None):
    if binary:
        return subprocess.check_output([str(binary),str(path)],text=True,timeout=300).strip()
    # Small local CPU fixtures only; product execution must provide the native helper.
    if Path(path).stat().st_size>1<<20: raise ValueError('native FNV helper required for large cache range')
    h=0xcbf29ce484222325
    with Path(path).open('rb') as f:
        for b in f.read(): h=((h^b)*0x100000001b3)&((1<<64)-1)
    return f'{h:016x}'


def _field(row,name): return row[name] if isinstance(row,dict) else getattr(row,name)


def verify_role(participant, model, placement, backend, fnv_binary=None):
    """Reject absent/altered bytes and self-consistent but incomplete descriptors.

    Source, executable and cache paths must be provisioned already; no stage or
    acquisition mutations occur here. The returned receipt says VERIFIED, never
    'consumed' (physical trace is needed to establish actual runtime cache reads).
    """
    role=_field(participant,'role'); root=Path(_field(participant,'source_path')).parent
    executable=Path(_field(participant,'runtime_executable'))
    if sha(executable)!=_field(participant,'runtime_sha256'): raise ValueError(f'{role}: runtime executable SHA-256 mismatch')
    tensors={}; members=[]
    for name,digest,size in _field(model,'members'):
        path=root/name
        if path.stat().st_size!=size or sha(path)!=digest: raise ValueError(f'{role}: model member identity mismatch: {name}')
        members.append(name)
        for state,(offset,length) in gguf_tensors(path).items():
            if state in tensors: raise ValueError(f'{role}: duplicate GGUF tensor name')
            tensors[state]=(name,offset,length)
    if role=='client':
        return {'role':role,'verified_members':members,'runtime_sha256':_field(participant,'runtime_sha256'),
                'backing':'full-source','cache_ranges':0,'eligible_cache_reads':0}
    assigned=[p for p in placement if _field(p,'compute_id')==_field(participant,'compute_id')]
    layers={i for p in assigned for i in range(_field(p,'first_layer'),_field(p,'last_layer')+1)}
    output=any(_field(p,'output') for p in assigned)
    def selected(name):
        m=re.match(r'blk\.(\d+)\.',name)
        if m: return int(m.group(1)) in layers and not (_field(backend,'cpu_experts') and '_exps.' in name)
        return output and (name.startswith('output.') or name.startswith('output_hc_'))
    required={name for name in tensors if selected(name)}
    descriptor={_field(c,'state_id'):c for c in _field(participant,'cache_ranges')}
    if len(descriptor)!=len(_field(participant,'cache_ranges')) or set(descriptor)!=required:
        raise ValueError(f'{role}: source tensor inventory mismatch: missing {sorted(required-set(descriptor))[:4]}, extra {sorted(set(descriptor)-required)[:4]}')
    selected_placement={state:(member,off,length) for p in assigned for state,member,off,length in _field(p,'state_ranges')}
    if set(selected_placement)!=required: raise ValueError(f'{role}: placement source tensor inventory mismatch')
    keys=set(); eligible=0
    for state,record in descriptor.items():
        member,off,length=tensors[state]
        if selected_placement[state]!=(member,off,length) or (_field(record,'member'),_field(record,'offset'),_field(record,'length'))!=(member,off,length):
            raise ValueError(f'{role}: GGUF tensor range mismatch: {state}')
        key=_field(record,'cache_key')
        if not isinstance(key,str) or not KEY.fullmatch(key) or key in keys: raise ValueError(f'{role}: invalid/duplicate cache key: {state}')
        keys.add(key)
        path=root/member; digest=sha(path,off,length)
        if digest!=_field(record,'sha256'): raise ValueError(f'{role}: source range digest mismatch: {state}')
        cached=Path(_field(participant,'cache_path'))/'rpc'/key
        if cached.stat().st_size!=length or sha(cached)!=digest: raise ValueError(f'{role}: cache identity mismatch: {state}')
        if fnv(cached,fnv_binary)!=key: raise ValueError(f'{role}: cache native lookup key mismatch: {state}')
        if length>10*1024*1024: eligible+=1
    return {'role':role,'verified_members':members,'runtime_sha256':_field(participant,'runtime_sha256'),
            'backing':'participant-local-cache-verified-not-yet-observed-consumed','cache_ranges':len(descriptor),
            'eligible_cache_reads':eligible}


# Versioned wire contract: source authentication only, not physical observation.
Q8_PLAN_FIELDS = ('schema', 'plan_digest', 'metadata', 'model', 'source_contract',
                  'rpc_cache', 'participants', 'assignments', 'placement')
Q8_PARTICIPANT_FIELDS = ('participant_id', 'role', 'host_id', 'source_path',
    'runtime_executable', 'runtime_sha256', 'source_id', 'source_revision',
    'source_representation', 'cache_path', 'bindings', 'backing', 'cache_ranges')
Q8_BINDING_FIELDS = ('binding_id', 'compute_id', 'memory_id', 'physical_id',
    'native_selector', 'visible_selector', 'runtime_id', 'evidence_id', 'evidence_sha256')
Q8_TENSOR_FIELDS = ('state_id', 'member', 'ggml_type', 'shape', 'relative_offset',
                    'absolute_offset', 'encoded_bytes')
Q8_ASSIGNMENT_FIELDS = ('state_id', 'member', 'ggml_type', 'shape', 'absolute_offset',
                        'encoded_bytes', 'binding_id', 'memory_id', 'authority')
Q8_CACHE_FIELDS = ('state_id', 'member', 'offset', 'length', 'sha256', 'cache_key',
                   'source_id', 'revision', 'representation', 'unit_id')
MAX_Q8_JSON_BYTES = 8 << 20


def _q8_canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def _q8_keys(value, expected, where):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(where + ' fields must be exactly ' + str(sorted(expected)))


def _q8_text(value, where):
    if not isinstance(value, str) or not value or value != value.strip() or '\x00' in value or len(value) > 65536:
        raise ValueError('invalid ' + where)
    return value


def _q8_int(value, where, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_EXTENT_BYTES:
        raise ValueError('invalid ' + where)
    return value


def _q8_digest(value, where):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid ' + where + ' SHA-256')
    return value


def _q8_array(value, where, maximum=100000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError('invalid ' + where + ' inventory')
    return value


def _q8_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _q8_json(data):
    def constant(_): raise ValueError('nonfinite JSON')
    def floating(text):
        result = float(text)
        if not math.isfinite(result): raise ValueError('nonfinite JSON')
        return result
    return json.loads(data, object_pairs_hook=_q8_pairs,
                      parse_constant=constant, parse_float=floating)


def _q8_project(row, fields):
    # Private copy: never mutate frozen configuration or caller dictionaries.
    def plain(value):
        if hasattr(value, '__dataclass_fields__'): return asdict(value)
        if isinstance(value, (tuple, list)): return [plain(v) for v in value]
        if isinstance(value, dict): return {k:plain(v) for k,v in value.items()}
        return value
    return json.loads(_q8_canonical({name: plain(_field(row, name)) for name in fields}))


def q8_source_payload(plan):
    """Project a validated /3 plan; read authenticated metadata, NEVER weights.

    Caller must separately revalidate plan/admission before transport/effects.
    plan_digest is the controller's immutable plan identity, not a new fit gate.
    """
    identity = _field(plan, 'metadata')
    with Path(_field(identity, 'path')).open('rb') as stream:
        data = stream.read((4 << 20) + 1)
    if len(data) > 4 << 20: raise ValueError('oversized metadata JSON')
    if hashlib.sha256(data).hexdigest() != _field(identity, 'sha256'):
        raise ValueError('metadata file SHA-256 mismatch')
    metadata = _q8_json(data)
    if metadata['metadata_digest'] != _field(identity, 'digest'):
        raise ValueError('metadata digest mismatch')
    options = dict(_field(plan, 'strategy_options'))
    mode = options['rpc_cache']
    if mode not in ('enabled', 'disabled'): raise ValueError('unsupported explicit RPC cache mode')
    payload = dict(schema='q8-source-plan/1', plan_digest=_field(plan, 'digest'),
        metadata=metadata, model=asdict(_field(plan, 'model')),
        source_contract=options['source_contract'], rpc_cache=mode == 'enabled',
        participants=[_q8_project(p, Q8_PARTICIPANT_FIELDS) for p in _field(plan, 'participants')],
        assignments=[asdict(a) for a in _field(_field(plan, 'candidate'), 'assignments')],
        placement=[asdict(p) for p in _field(plan, 'placement')])
    payload = json.loads(_q8_canonical(payload))
    validate_q8_payload(payload)
    return payload


def validate_q8_payload(payload):
    """Validate complete opaque ownership against authenticated metadata identity.

    Header digest authenticity is established against actual provisioned files in
    verify_q8_role. The trusted controller supplies the plan/metadata identities;
    resealing an invented digest is not independent public-source authentication.
    """
    _q8_keys(payload, Q8_PLAN_FIELDS, 'q8 source plan')
    if payload['schema'] != 'q8-source-plan/1': raise ValueError('unsupported Q8 source schema')
    _q8_digest(payload['plan_digest'], 'plan')
    if payload['source_contract'] != 'full-source-both-hosts/1':
        raise ValueError('unsupported full-source backing contract')
    if type(payload['rpc_cache']) is not bool: raise ValueError('explicit boolean RPC cache mode required')
    meta = payload['metadata']
    _q8_keys(meta, ('schema', 'source', 'header_identities', 'model_metadata', 'tensors', 'provenance', 'metadata_digest'), 'metadata')
    if meta['schema'] != 'gguf-metadata-index/1': raise ValueError('unsupported metadata schema')
    _q8_digest(meta['metadata_digest'], 'metadata')
    if hashlib.sha256(_q8_canonical({k:v for k,v in meta.items() if k != 'metadata_digest'})).hexdigest() != meta['metadata_digest']:
        raise ValueError('metadata digest mismatch')
    model = payload['model']
    _q8_keys(model, ('source_id', 'revision', 'representation', 'members'), 'model')
    _q8_keys(meta['source'], ('source_id', 'revision', 'representation'), 'metadata source')
    identity = {k: _q8_text(model[k], k) for k in ('source_id', 'revision', 'representation')}
    if meta['source'] != identity: raise ValueError('model/metadata source identity mismatch')
    members = {}
    for row in _q8_array(model['members'], 'model member', 1024):
        if not isinstance(row, list) or len(row) != 3: raise ValueError('invalid model member')
        name, h, size = row
        _q8_text(name, 'member'); _q8_digest(h, 'member'); _q8_int(size, 'member size', 1)
        if Path(name).name != name or name in ('.', '..') or name in members: raise ValueError('invalid/duplicate model member')
        members[name] = (h, size)
    if len(members) != 6: raise ValueError('model member inventory mismatch: all six members required')
    headers = {}
    for row in _q8_array(meta['header_identities'], 'header', 1024):
        if not isinstance(row, list) or len(row) != 6: raise ValueError('invalid header identity')
        name, start, end, h, size, full = row
        _q8_int(start, 'header start'); _q8_int(end, 'header end'); _q8_int(size, 'object bytes', 1)
        _q8_digest(h, 'header'); _q8_digest(full, 'member')
        if name not in members or name in headers or start != 0 or end >= MAX_HEADER_BYTES or end >= size or members[name] != (full, size):
            raise ValueError('header/member identity mismatch')
        headers[name] = row
    if set(headers) != set(members): raise ValueError('header/member inventory mismatch')
    pairs = {}; pairs_list = _q8_array(meta['model_metadata'], 'model metadata', 10000)
    for pair in pairs_list:
        if not isinstance(pair, list) or len(pair) != 2: raise ValueError('invalid model metadata pair')
        key, value = pair; _q8_text(key, 'metadata key')
        if key in pairs or key.startswith(('split.', 'tokenizer.')): raise ValueError('invalid/duplicate model metadata')
        pairs[key] = value
    tensors = {}; extents = set()
    for t in _q8_array(meta['tensors'], 'metadata tensor'):
        _q8_keys(t, Q8_TENSOR_FIELDS, 'metadata tensor')
        name = _q8_text(t['state_id'], 'state_id')
        for key in ('ggml_type', 'relative_offset', 'absolute_offset', 'encoded_bytes'): _q8_int(t[key], key)
        if not isinstance(t['shape'], list) or _encoded_bytes(t['shape'], t['ggml_type']) != t['encoded_bytes']:
            raise ValueError('metadata descriptor mismatch: ' + name)
        if name in tensors or t['member'] not in members: raise ValueError('metadata tensor inventory mismatch')
        extent = (t['member'], t['absolute_offset'], t['encoded_bytes'])
        if extent in extents: raise ValueError('duplicate metadata source extent')
        extents.add(extent); tensors[name] = t
    participants = _q8_array(payload['participants'], 'participant', 2)
    if len(participants) != 2 or {p.get('role') for p in participants if isinstance(p, dict)} != {'client', 'remote'}:
        raise ValueError('exactly one client and remote required')
    bindings = {}; participant_ids = set(); hosts = set()
    for p in participants:
        _q8_keys(p, Q8_PARTICIPANT_FIELDS, 'participant')
        for key in Q8_PARTICIPANT_FIELDS:
            if key not in ('bindings', 'backing', 'cache_ranges'): _q8_text(p[key], 'participant ' + key)
        _q8_digest(p['runtime_sha256'], 'runtime')
        for key in ('source_path', 'runtime_executable', 'cache_path'):
            if not Path(p[key]).is_absolute(): raise ValueError('participant path must be absolute')
        if p['participant_id'] in participant_ids or p['host_id'] in hosts: raise ValueError('duplicate participant identity')
        participant_ids.add(p['participant_id']); hosts.add(p['host_id'])
        if (p['source_id'], p['source_revision'], p['source_representation']) != tuple(identity[k] for k in ('source_id','revision','representation')):
            raise ValueError('participant source identity mismatch')
        if Path(p['source_path']).name not in members: raise ValueError('source path member mismatch')
        backing = []; memory_ids = set()
        for b in _q8_array(p['backing'], 'backing', 1024):
            _q8_keys(b, ('memory_id','member','sha256','size_bytes'), 'backing')
            _q8_text(b['memory_id'], 'backing memory'); _q8_digest(b['sha256'], 'backing'); _q8_int(b['size_bytes'], 'backing size', 1)
            backing.append([b['member'],b['sha256'],b['size_bytes']]); memory_ids.add(b['memory_id'])
        if sorted(backing) != sorted(model['members']): raise ValueError('full-source backing inventory mismatch')
        local_bindings = _q8_array(p['bindings'], 'binding', 1000)
        if not local_bindings: raise ValueError('missing participant bindings')
        for b in local_bindings:
            _q8_keys(b, Q8_BINDING_FIELDS, 'binding')
            for key in Q8_BINDING_FIELDS: _q8_text(b[key], 'binding ' + key)
            _q8_digest(b['evidence_sha256'], 'binding evidence')
            if b['binding_id'] in bindings: raise ValueError('duplicate binding identity')
            bindings[b['binding_id']] = b
        _q8_array(p['cache_ranges'], 'cache descriptor')
        if (not payload['rpc_cache'] or p['role'] == 'client') and p['cache_ranges']:
            raise ValueError('disabled RPC cache has descriptors' if not payload['rpc_cache'] else 'client cache ranges unsupported')
    assignments = {}; ownership = {}
    for a in _q8_array(payload['assignments'], 'assignment'):
        _q8_keys(a, Q8_ASSIGNMENT_FIELDS, 'assignment')
        name = _q8_text(a['state_id'], 'assignment state')
        if name in assignments or name not in tensors: raise ValueError('assignment inventory mismatch')
        assignments[name] = a
    if set(assignments) != set(tensors): raise ValueError('assignment inventory mismatch')
    units = set()
    for row in _q8_array(payload['placement'], 'placement'):
        _q8_keys(row, ('unit_id','binding_id','state_ids','state_ranges'), 'placement')
        unit = _q8_text(row['unit_id'], 'unit_id'); bid = row['binding_id']
        if unit in units or bid not in bindings: raise ValueError('placement unit/binding mismatch')
        units.add(unit)
        names = _q8_array(row['state_ids'], 'placement state'); ranges = _q8_array(row['state_ranges'], 'placement range')
        if len(names) != len(set(names)) or len(ranges) != len(names): raise ValueError('placement inventory mismatch')
        described = set()
        for r in ranges:
            if not isinstance(r, list) or len(r) != 4: raise ValueError('invalid placement range')
            name, member, off, size = r; _q8_int(off, 'placement offset'); _q8_int(size, 'placement length', 1)
            if name not in tensors or name in described or name in ownership: raise ValueError('placement inventory mismatch')
            t = tensors[name]
            if (member, off, size) != (t['member'], t['absolute_offset'], t['encoded_bytes']): raise ValueError('placement descriptor mismatch')
            described.add(name); ownership[name] = (unit, bid)
        if described != set(names): raise ValueError('placement inventory mismatch')
    if set(ownership) != set(tensors): raise ValueError('placement inventory mismatch')
    for name, a in assignments.items():
        t = tensors[name]
        for key in ('absolute_offset', 'encoded_bytes', 'ggml_type'): _q8_int(a[key], 'assignment ' + key)
        if any(_q8_canonical(a[key]) != _q8_canonical(t[key]) for key in ('member','absolute_offset','encoded_bytes','ggml_type','shape')):
            raise ValueError('assignment descriptor mismatch: ' + name)
        if a['authority'] != 'immutable-public-source/1': raise ValueError('assignment authority mismatch: ' + name)
        _, bid = ownership[name]
        if a['binding_id'] != bid or a['memory_id'] != bindings[bid]['memory_id']:
            raise ValueError('assignment ownership mismatch: ' + name)
    for p in participants:
        required = {name for name, a in assignments.items() if a['binding_id'] in {b['binding_id'] for b in p['bindings']}}
        if not payload['rpc_cache'] or p['role'] == 'client': continue
        descriptors = {}; keys = set()
        for c in p['cache_ranges']:
            _q8_keys(c, Q8_CACHE_FIELDS, 'cache descriptor')
            name = c['state_id']
            if name in descriptors or name not in required: raise ValueError('cache descriptor inventory mismatch')
            descriptors[name] = c
        if set(descriptors) != required: raise ValueError('cache descriptor inventory mismatch')
        for name, c in descriptors.items():
            if (c['source_id'],c['revision'],c['representation']) != tuple(identity[k] for k in ('source_id','revision','representation')):
                raise ValueError('cache source identity mismatch: ' + name)
            if c['unit_id'] != ownership[name][0]: raise ValueError('cache ownership mismatch: ' + name)
            t = tensors[name]
            _q8_int(c['offset'], 'cache offset'); _q8_int(c['length'], 'cache length', 1)
            if (c['member'],c['offset'],c['length']) != (t['member'],t['absolute_offset'],t['encoded_bytes']):
                raise ValueError('cache range mismatch: ' + name)
            _q8_digest(c['sha256'], 'cache range')
            key = c['cache_key']
            if not isinstance(key, str) or not KEY.fullmatch(key) or key in keys:
                raise ValueError('invalid/duplicate cache key: ' + name)
            keys.add(key)
    return payload


def _q8_cache_eligible(length):
    _q8_int(length, 'cache extent', 1)
    return length > 10 * 1024 * 1024


def verify_q8_role(participant, plan_payload, fnv_binary=None):
    """Read-only full-source + exact ranges on client and ALL remote bindings.

    No compile, provisioning or fit/physical/cache-consumption claim. In cached
    mode only an already provisioned helper (or tiny fixture fallback) is used.
    """
    payload = validate_q8_payload(json.loads(_q8_canonical(plan_payload)))
    if isinstance(participant, dict):
        _q8_keys(participant, Q8_PARTICIPANT_FIELDS, 'selected participant')
    p = _q8_project(participant, Q8_PARTICIPANT_FIELDS)
    selected = [r for r in payload['participants'] if r['participant_id'] == p['participant_id']]
    if len(selected) != 1 or p != selected[0]: raise ValueError('selected participant mismatch')
    role = p['role']; root = Path(p['source_path']).parent
    if payload['rpc_cache'] and role == 'remote' and fnv_binary is not None:
        _q8_text(fnv_binary, 'FNV helper path')
        if not Path(fnv_binary).is_absolute(): raise ValueError('FNV helper path must be absolute')
    if sha(p['runtime_executable']) != p['runtime_sha256']:
        raise ValueError(role + ': runtime executable SHA-256 mismatch')
    meta = payload['metadata']; headers = {r[0]:r for r in meta['header_identities']}
    expected = {t['state_id']:t for t in meta['tensors']}
    actual = {}; metadata = {}; members = []
    for name, full, size in payload['model']['members']:
        path = root / name
        if path.stat().st_size != size or sha(path) != full:
            raise ValueError(role + ': model member identity mismatch: ' + name)
        members.append(name); h = headers[name]
        with path.open('rb') as stream: header = stream.read(h[2] + 1)
        pairs, rows = parse_gguf_header(header, object_bytes=size, expected_header_sha256=h[3])
        for key, value in pairs:
            if key.startswith('split.'): continue
            if key in metadata and _q8_canonical(metadata[key]) != _q8_canonical(value):
                raise ValueError('model metadata mismatch')
            metadata[key] = value
        for row in rows:
            if row.state_id in actual: raise ValueError('duplicate actual GGUF tensor')
            t = asdict(row); t['member'] = name
            actual[row.state_id] = json.loads(_q8_canonical(t))
    if _q8_canonical(sorted(metadata.items())) != _q8_canonical(sorted(meta['model_metadata'])):
        raise ValueError('model metadata mismatch')
    if set(actual) != set(expected): raise ValueError('actual GGUF tensor inventory mismatch')
    for name in actual:
        if actual[name] != expected[name]: raise ValueError('metadata descriptor mismatch: ' + name)
    bids = {b['binding_id'] for b in p['bindings']}
    assigned = sorted((a for a in payload['assignments'] if a['binding_id'] in bids), key=lambda a:a['state_id'])
    descriptors = {c['state_id']:c for c in p['cache_ranges']}
    ranges = []; counts = {b:0 for b in sorted(bids)}; eligible = 0; checked = 0
    for a in assigned:
        # Offsets and lengths come from the actual authenticated GGUF parser,
        # NOT an echoed transport range. The exact join above is mandatory.
        t = actual[a['state_id']]; off, length = t['absolute_offset'], t['encoded_bytes']
        h = sha(root / t['member'], off, length)
        cache_eligible = _q8_cache_eligible(length)
        if cache_eligible: eligible += 1
        key = None
        if payload['rpc_cache'] and role == 'remote':
            c = descriptors[a['state_id']]; key = c['cache_key']
            if h != c['sha256']: raise ValueError('source range digest mismatch: ' + a['state_id'])
            cached = Path(p['cache_path']) / 'rpc' / key
            try:
                valid = cached.stat().st_size == length and sha(cached) == h
            except OSError:
                valid = False
            if not valid: raise ValueError('cache identity mismatch: ' + a['state_id'])
            if fnv(cached, fnv_binary) != key: raise ValueError('cache native lookup key mismatch: ' + a['state_id'])
            checked += 1
        counts[a['binding_id']] += 1
        ranges.append(dict(state_id=a['state_id'], member=t['member'], offset=off, length=length,
            sha256=h, binding_id=a['binding_id'], memory_id=a['memory_id'], authority=a['authority'],
            cache_eligible=cache_eligible, cache_key=key))
    return dict(schema='q8-source-receipt/1', role=role, participant_id=p['participant_id'],
        status='VERIFIED-not-consumed', plan_digest=payload['plan_digest'], metadata_digest=meta['metadata_digest'],
        source_contract=payload['source_contract'], rpc_cache=payload['rpc_cache'],
        source_identity=meta['source'], verified_members=members, member_identities=payload['model']['members'],
        header_identities=meta['header_identities'], runtime_sha256=p['runtime_sha256'],
        binding_expectations=p['bindings'], assigned_count=len(assigned), binding_counts=counts,
        range_identities=ranges, cache_ranges=checked, eligible_cache_ranges=eligible,
        eligible_cache_reads=eligible if payload['rpc_cache'] and role == 'remote' else 0,
        backing='full-source', physical_observation=False, cache_consumed=False)


def main():
    from types import SimpleNamespace
    def unpack(v):
        if isinstance(v,dict): return SimpleNamespace(**{k:unpack(x) for k,x in v.items()})
        if isinstance(v,list): return tuple(unpack(x) for x in v)
        return v
    data = sys.stdin.buffer.read(MAX_Q8_JSON_BYTES + 1)
    if len(data) > MAX_Q8_JSON_BYTES: raise ValueError('oversized Q8 verification JSON')
    raw = json.loads(data)
    # Keep legacy JSON value/duplicate semantics; strict decoding belongs only
    # to the explicitly versioned source protocol.
    if isinstance(raw, dict) and 'schema' in raw:
        raw = _q8_json(data)
    if isinstance(raw, dict) and raw.get('schema') == 'q8-source-verification/1':
        _q8_keys(raw, ('schema', 'participant', 'plan_payload', 'fnv_binary'), 'q8 verification envelope')
        try:
            print(json.dumps(verify_q8_role(raw['participant'], raw['plan_payload'], raw['fnv_binary']), allow_nan=False))
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            print(json.dumps({'schema':'q8-source-error/1', 'status':'ERROR', 'reason':str(exc)}))
            raise SystemExit(1)
        return
    if isinstance(raw, dict) and 'schema' in raw:
        raise ValueError('unsupported source verification schema')
    payload=unpack(raw)
    if payload.fnv_binary is not None: compile_fnv(payload.fnv_binary)
    print(json.dumps(verify_role(payload.participant,payload.model,payload.placement,payload.backend,
                                 payload.fnv_binary)))

if __name__=='__main__': main()
