"""Read-only on-host authentication of runtime, full GGUF members and assigned RPC cache.

This file is self-contained so the controller can send it to a participant via
`ssh python3 -c ...` without requiring an installed product package there.
"""
from __future__ import annotations
from dataclasses import dataclass
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


def main():
    from types import SimpleNamespace
    def unpack(v):
        if isinstance(v,dict): return SimpleNamespace(**{k:unpack(x) for k,x in v.items()})
        if isinstance(v,list): return tuple(unpack(x) for x in v)
        return v
    payload=unpack(json.load(sys.stdin))
    if payload.fnv_binary is not None: compile_fnv(payload.fnv_binary)
    print(json.dumps(verify_role(payload.participant,payload.model,payload.placement,payload.backend,
                                 payload.fnv_binary)))

if __name__=='__main__': main()
