#!/usr/bin/env python3
"""Strict bounded factorial captures with shared, once-read immutable banks."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import struct

STAGES = ('gate', 'up', 'swiglu', 'down', 'weighted')
HOT = (54, 74, 136, 290, 394)
RESIDENT10 = tuple(range(21)) + HOT
LIMIT = 32*1024*1024
BASE_LIMIT = 16*1024*1024
IDENTITIES = ('weights.json', 'spec.json', 'assigned.txt')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def floats(data):
    if len(data) % 4:
        raise ValueError('incomplete F32 bytes')
    return struct.unpack('<'+'f'*(len(data)//4), data)


def metadata(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError('metadata budget exceeded: '+str(path))
    return json.loads(path.read_text())


def placement(m):
    hot, cold = m.get('hot_count'), m.get('cold_count')
    if type(hot) is not int or type(cold) is not int or (hot, cold) not in ((5,5), (10,0)):
        raise ValueError('explicit factorial placement counts required')
    resident = HOT if hot == 5 else RESIDENT10
    if m.get('resident_expert_order') != list(resident):
        raise ValueError('frozen resident expert union/order mismatch')
    return hot, cold, resident


def checked_bytes(path, meta):
    if path.stat().st_size != meta['byte_length']:
        raise ValueError('payload size mismatch: '+str(path))
    data = path.read_bytes()
    if digest(data) != meta['sha256']:
        raise ValueError('payload identity mismatch: '+str(path))
    return data


def load_capture(directory, bank_cache=None):
    """Hash per-replay payloads; hash/read each external physical bank once.

    The cache is private to one analyzer invocation. Entries bind resolved path,
    digest and stat identity, so repeated pairs do not re-read 129 MiB of banks.
    It assumes immutable files during this offline analysis and rejects drift.
    """
    directory = Path(directory)
    bank_cache = {} if bank_cache is None else bank_cache
    m = metadata(directory/'manifest.json')
    hot, cold, resident = placement(m)
    if (m.get('schema') != 'h5-layer7-factorial-stages/1' or
            m.get('byte_order') != 'little' or m.get('performance_claim') is not False or
            m.get('payload_limit_bytes') != LIMIT):
        raise ValueError('factorial stage schema/contract mismatch')
    base_path = directory.parent/'capture/manifest.json'
    base_bytes = base_path.read_bytes()
    if len(base_bytes) > 65536 or digest(base_bytes) != m['capture_manifest_sha256']:
        raise ValueError('base capture identity/budget mismatch')
    base = json.loads(base_bytes)
    if (base.get('schema') != 'h5-layer7-capture/2' or base.get('byte_order') != 'little' or
            placement(base) != (hot,cold,resident)):
        raise ValueError('base capture placement/schema mismatch')
    row = m['pair_record']; tokens = row['tokens']
    if (tokens not in (1,4) or row['case'] != ('mixed' if tokens == 1 else 'mixed-varied-set') or
            row.get('type') != 'factorial-pair' or row.get('warmup') is not False or
            row.get('factorial_arm') not in ('pipeline'+str(hot),'reduced'+str(hot)) or
            row != base['pair_record'] or m['slot_map'] != base['slot_map'] or
            m['input_sha256'] != row['input_sha256'] or m['routing_sha256'] != row['routing_sha256']):
        raise ValueError('factorial selected pair mismatch')
    expected_files = {arm+'.'+stage+'.bin' for arm in ('A','B') for stage in STAGES}
    expected_files |= {stage+'.q8_0.bin' for stage in ('gate','up','down')}
    if set(m['files']) != expected_files:
        raise ValueError('stage file coverage mismatch')
    d = base['tensors']['A.input']['shape'][0]
    f = m['files']['A.gate.bin']['shape'][0]
    total = 0
    for arm, count in (('A',10),('B',hot)):
        for stage in STAGES:
            name = arm+'.'+stage+'.bin'; meta = m['files'][name]
            width = f if stage in ('gate','up','swiglu') else d
            size = width*count*tokens*4
            if (meta['shape'] != [width,count,tokens,1] or
                    meta['strides_bytes'] != [4,width*4,width*count*4,width*count*tokens*4] or
                    meta['ggml_type'] != 0 or meta['type_name'] != 'f32' or
                    not meta['flags'] & 2 or meta['byte_length'] != size or
                    meta.get('file',name) != name):
                raise ValueError('retained stage dimensions/strides/flags mismatch')
            total += size
            if total > LIMIT:
                raise ValueError('stage payload budget exceeded')
            checked_bytes(directory/name, meta)
    if total != m['payload_bytes']:
        raise ValueError('stage payload size mismatch (external banks excluded)')
    base_total = 0
    if type(base.get('payload_limit_bytes')) is not int or not 1 <= base['payload_limit_bytes'] <= BASE_LIMIT:
        raise ValueError('base payload limit invalid')
    for name, meta in base['tensors'].items():
        if meta['file'] != name+'.bin':
            raise ValueError('base tensor path mismatch')
        base_total += meta['byte_length']
        if base_total > base['payload_limit_bytes']:
            raise ValueError('base payload budget exceeded')
        checked_bytes(directory.parent/'capture'/meta['file'], meta)
    if base_total != base['payload_bytes'] or set(base['identities']) != set(IDENTITIES):
        raise ValueError('base payload/identity coverage mismatch')
    for name in IDENTITIES:
        if digest((directory.parent/name).read_bytes()) != base['identities'][name]:
            raise ValueError('base source identity mismatch: '+name)
    prefix = '../../../banks/p'+str(hot)+'/'
    if m.get('bank_manifest') != prefix+'manifest.json':
        raise ValueError('bank manifest path outside frozen shared bank')
    bank_path = directory/m['bank_manifest']
    bank_text = bank_path.read_bytes()
    if len(bank_text) > 65536 or digest(bank_text) != m.get('bank_manifest_sha256'):
        raise ValueError('bank manifest identity/budget mismatch')
    bank_manifest = json.loads(bank_text)
    if (bank_manifest.get('schema') != 'h5-layer7-factorial-banks/1' or
            bank_manifest.get('byte_order') != 'little' or
            placement(bank_manifest) != (hot,cold,resident) or
            bank_manifest.get('identities') != base['identities'] or
            set(bank_manifest.get('files',{})) != {s+'.q8_0.bin' for s in ('gate','up','down')}):
        raise ValueError('shared bank manifest contract mismatch')
    for name in IDENTITIES:
        if digest((bank_path.parent/name).read_bytes()) != base['identities'][name]:
            raise ValueError('shared bank source identity mismatch: '+name)
    inventory = {t['name']:t for t in metadata(directory.parent/'weights.json')['tensors']}
    spec = metadata(directory.parent/'spec.json')
    if spec['layer'] != 7 or spec['expert_ids'] != list(resident):
        raise ValueError('bank layer/resident identity mismatch')
    if len(spec['tensors']) != 3:
        raise ValueError('bank source tensor coverage mismatch')
    banks = {}
    for stage in ('gate','up','down'):
        name = stage+'.q8_0.bin'; meta = m['files'][name]
        shared = bank_manifest['files'][name]
        if (meta.get('file') != prefix+name or shared.get('file',name) != name or
                {k:v for k,v in meta.items() if k != 'file'} != {k:v for k,v in shared.items() if k != 'file'}):
            raise ValueError('stage/shared bank metadata mismatch')
        columns, rows = (f,d) if stage == 'down' else (d,f)
        stride = columns//32*34
        source_name = 'blk.7.ffn_'+stage+'_exps.weight'
        matches = [t for t in spec['tensors'] if t['source_name'] == source_name]
        if len(matches) != 1:
            raise ValueError('bank selected source coverage mismatch')
        source = matches[0]
        if (columns % 32 or meta['shape'] != [columns,rows,len(resident),1] or
                meta['strides_bytes'] != [34,stride,stride*rows,stride*rows*len(resident)] or
                meta['byte_length'] != stride*rows*len(resident) or
                meta['ggml_type'] != 8 or meta['type_name'] != 'q8_0' or
                meta['source_tensor'] != source_name or meta['source_sha256'] != inventory[source_name]['sha256'] or
                source['source_sha256'] != meta['source_sha256'] or
                source['compact_sha256'] != meta['sha256'] or meta['B_actual_sha256'] != meta['sha256'] or
                [r['expert_id'] for r in source['ranges']] != list(resident)):
            raise ValueError('bank source/layout/encoded identity mismatch')
        path = (directory/meta['file']).resolve()
        stat = path.stat()
        identity = (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        key = (str(path),meta['sha256'])
        if key in bank_cache:
            previous, bank = bank_cache[key]
            if previous != identity:
                raise ValueError('immutable bank changed during analysis')
        else:
            bank = checked_bytes(path,meta)
            if not all(math.isfinite(struct.unpack_from('<e',bank,at)[0]) for at in range(0,len(bank),34)):
                raise ValueError('nonfinite bank scale')
            bank_cache[key] = (identity,bank)
        banks[stage] = bank
    return m, base, banks
