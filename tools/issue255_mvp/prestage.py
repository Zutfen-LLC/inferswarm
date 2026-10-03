#!/usr/bin/env python3
"""Issue #255: stage selected whole GGUF tensors into the pinned RPC local cache.

Run on the participant against a release whose complete-member SHA-256 has
already been verified (discovery receipt).  No full-member rehash here.
The native FNV only names upstream cache files; SHA-256 authenticates bytes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

# Pinned llama.cpp b29c606 GGML_QUANT_SIZES (block elements, block bytes).
TYPES = {0:(1,4),1:(1,2),2:(32,18),3:(32,20),6:(32,22),7:(32,24),8:(32,34),9:(32,40),
         10:(256,84),11:(256,110),12:(256,144),13:(256,176),14:(256,210),15:(256,292),
         16:(256,66),17:(256,74),18:(256,98),19:(256,50),20:(32,18),21:(256,110),
         22:(256,82),23:(256,82),24:(1,1),25:(1,2),26:(1,4),27:(1,8),28:(1,8),
         29:(256,56),30:(1,2),34:(256,54),35:(256,66),39:(32,17),40:(64,36),
         41:(128,18),42:(64,18)}
SCALAR = {0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}


def read_gguf_tensors(path):
    """Parse v3 metadata only; return name -> (absolute offset, exact nbytes, type)."""
    with Path(path).open('rb') as f:
        def value(fmt):
            return struct.unpack('<'+fmt, f.read(struct.calcsize('<'+fmt)))[0]
        def text():
            n = value('Q')
            if n > 1 << 24:
                raise ValueError('oversized GGUF metadata string')
            return f.read(n).decode('utf-8')
        def skip(ty):
            if ty == 8:
                return text()
            if ty == 9:
                subtype, n = value('I'), value('Q')
                if n > 1 << 26:
                    raise ValueError('oversized GGUF metadata array')
                if subtype in SCALAR:
                    f.seek(struct.calcsize('<'+SCALAR[subtype])*n, 1)
                elif subtype == 8:
                    for _ in range(n): text()
                else:
                    raise ValueError('unsupported GGUF array subtype')
                return None
            if ty not in SCALAR:
                raise ValueError('unsupported GGUF value type')
            return value(SCALAR[ty])
        if f.read(4) != b'GGUF' or value('I') != 3:
            raise ValueError('expected GGUF v3')
        n_tensors, n_kv = value('Q'), value('Q')
        if n_tensors > 1000000 or n_kv > 1000000:
            raise ValueError('oversized GGUF index')
        alignment = 32
        for _ in range(n_kv):
            key, ty = text(), value('I')
            result = skip(ty)
            if key == 'general.alignment': alignment = result
        if not isinstance(alignment, int) or alignment < 1 or alignment > 4096:
            raise ValueError('invalid alignment')
        entries = []
        for _ in range(n_tensors):
            name, nd = text(), value('I')
            if not 1 <= nd <= 4:
                raise ValueError('invalid tensor dimensionality')
            dims = [value('Q') for _ in range(nd)]
            ty, offset = value('I'), value('Q')
            if ty not in TYPES:
                raise ValueError(f'unknown GGML type {ty} for {name}')
            block, size = TYPES[ty]
            elements = 1
            for d in dims: elements *= d
            if elements % block:
                raise ValueError('unaligned tensor blocks')
            entries.append((name, offset, elements // block * size, ty))
        data_start = (f.tell() + alignment - 1) // alignment * alignment
        total = Path(path).stat().st_size
        out = {}
        for name, offset, length, ty in entries:
            absolute = data_start + offset
            if name in out or absolute + length > total:
                raise ValueError('duplicate/out-of-bounds GGUF tensor')
            out[name] = (absolute, length, ty)
        return out


def compile_fnv(binary):
    source = Path(__file__).with_name('fnv64.c')
    subprocess.run(['cc','-O2','-std=c11','-o',str(binary),str(source)], check=True)


def fnv_file(binary, path):
    return subprocess.check_output([str(binary), str(path)], text=True).strip()


def stage(member, accepted_sha256, selected, cache, fnv_binary, *, verify_member=True):
    member, cache = Path(member), Path(cache)
    if verify_member:
        digest = hashlib.sha256()
        with member.open('rb') as f:
            for block in iter(lambda: f.read(8 << 20), b''): digest.update(block)
        if digest.hexdigest() != accepted_sha256:
            raise ValueError('member identity mismatch')
    entries = read_gguf_tensors(member)
    if len(selected) != len(set(selected)) or not selected or any(name not in entries for name in selected):
        raise ValueError('selected tensor inventory mismatch')
    rpc = cache / 'rpc'
    rpc.mkdir(parents=True, exist_ok=True)
    receipts = []
    published = {}
    with member.open('rb') as f:
        for name in selected:
            offset, length, ty = entries[name]
            temp = rpc / f'.stage-{len(receipts)}'
            if temp.exists(): raise ValueError(f'already staged temporary path {temp}')
            digest = hashlib.sha256()
            with temp.open('xb') as out:
                f.seek(offset)
                remaining = length
                while remaining:
                    block = f.read(min(8 << 20, remaining))
                    if not block: raise ValueError('short member range')
                    out.write(block)
                    digest.update(block)
                    remaining -= len(block)
                out.flush(); os.fsync(out.fileno())
            key = fnv_file(fnv_binary, temp)
            final = rpc / key
            if final.exists():
                temp.unlink()
                if published.get(key) != (length, digest.hexdigest()):
                    raise ValueError(f'already staged key {key}')
            else:
                temp.rename(final)
                published[key] = (length, digest.hexdigest())
            receipts.append({'member':member.name,'name':name,'offset':offset,'bytes':length,
                             'ggml_type':ty,'sha256':digest.hexdigest(),'fnv1a':key,'cache_path':str(final)})
    return receipts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--member', type=Path, required=True)
    p.add_argument('--member-sha256', required=True)
    p.add_argument('--names', type=Path, required=True, help='JSON array of selected names for THIS member')
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--fnv-binary', type=Path, required=True)
    p.add_argument('--previously-verified-member', action='store_true',
                   help='skip redundant full member hash; cite discovery receipt')
    a = p.parse_args()
    selected = json.loads(a.names.read_text())
    print(json.dumps(stage(a.member,a.member_sha256,selected,a.cache,a.fnv_binary,
                           verify_member=not a.previously_verified_member), indent=2))


if __name__ == '__main__': main()
