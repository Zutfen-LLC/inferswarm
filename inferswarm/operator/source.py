"""Read-only on-host authentication of runtime, full GGUF members and assigned RPC cache.

This file is self-contained so the controller can send it to a participant via
`ssh python3 -c ...` without requiring an installed product package there.
"""
from __future__ import annotations
import hashlib
import json
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



def gguf_tensors(path):
    """Return tensor -> exact (absolute offset, size), never read tensor data."""
    with Path(path).open('rb') as f:
        def read(n):
            b=f.read(n)
            if len(b)!=n: raise ValueError('truncated GGUF metadata')
            return b
        def scalar(fmt): return struct.unpack('<'+fmt,read(struct.calcsize('<'+fmt)))[0]
        def text():
            n=scalar('Q')
            if n>1<<24: raise ValueError('oversized GGUF string')
            return read(n).decode('utf-8')
        def value(typ):
            if typ==8: return text()
            if typ==9:
                subtype,n=scalar('I'),scalar('Q')
                if n>1<<26: raise ValueError('oversized GGUF array')
                if subtype in SCALAR: read(struct.calcsize('<'+SCALAR[subtype])*n)
                elif subtype==8:
                    for _ in range(n): text()
                else: raise ValueError('unsupported GGUF array subtype')
                return None
            if typ not in SCALAR: raise ValueError('unsupported GGUF metadata type')
            return scalar(SCALAR[typ])
        if read(4)!=b'GGUF' or scalar('I')!=3: raise ValueError('expected GGUF v3')
        n_tensor,n_kv=scalar('Q'),scalar('Q')
        if max(n_tensor,n_kv)>1000000: raise ValueError('oversized GGUF index')
        alignment=32
        for _ in range(n_kv):
            key,typ=text(),scalar('I'); val=value(typ)
            if key=='general.alignment': alignment=val
        if type(alignment)is not int or not 1<=alignment<=4096: raise ValueError('invalid GGUF alignment')
        entries=[]
        for _ in range(n_tensor):
            name,nd=text(),scalar('I')
            if not 1<=nd<=4: raise ValueError('invalid GGUF tensor dimensions')
            elements=1
            for _ in range(nd): elements*=scalar('Q')
            typ,offset=scalar('I'),scalar('Q')
            if typ not in TYPES: raise ValueError(f'unsupported GGUF tensor type: {typ}')
            block,width=TYPES[typ]
            if elements%block: raise ValueError('unaligned GGUF tensor')
            entries.append((name,offset,elements//block*width))
        start=(f.tell()+alignment-1)//alignment*alignment
        limit=os.fstat(f.fileno()).st_size; result={}
        for name,offset,length in entries:
            absolute=start+offset
            if name in result or length<1 or absolute+length>limit: raise ValueError('duplicate or out-of-bounds GGUF tensor')
            result[name]=(absolute,length)
        return result


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
