#!/usr/bin/env python3
"""Bounded offline comparison of executed layer-7 stages; no runtime or network.

Decimal dot products are mathematical dequantized references. They do not model
CPU/CUDA activation quantization, fused kernels, accumulation or rounding.
"""
from __future__ import annotations
import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import struct

STAGES = ('gate', 'up', 'swiglu', 'down', 'weighted')
HOT = (54, 74, 136, 290, 394)
LIMIT = 32*1024*1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def floats(data):
    return struct.unpack('<'+'f'*(len(data)//4), data)


def load_capture(directory, allow_operand_replay=False):
    """Validate identities/layouts before using executed stage bytes."""
    directory = Path(directory)
    path = directory/'manifest.json'
    if path.stat().st_size > 65536:
        raise ValueError('stage metadata budget exceeded')
    m = json.loads(path.read_text())
    replay = allow_operand_replay and m.get('schema') == 'h5-layer7-stages/2'
    if (m.get('schema') != ('h5-layer7-stages/2' if replay else 'h5-layer7-stages/1') or m.get('byte_order') != 'little' or
            m.get('compact_expert_order') != list(HOT) or m.get('performance_claim') is not False or
            m.get('payload_limit_bytes') != LIMIT):
        raise ValueError('stage schema/contract mismatch')
    base_path = directory.parent/'capture/manifest.json'
    base_bytes = base_path.read_bytes()
    if digest(base_bytes) != m['capture_manifest_sha256']:
        raise ValueError('stage base capture identity mismatch')
    base = json.loads(base_bytes)
    if base.get('schema') != 'h5-layer7-capture/2':
        raise ValueError('stages require corrected base capture')
    row = m['pair_record']
    tokens = row['tokens']
    if (tokens not in ((1,2,4,8) if replay else (2,)) or
            row['case'] not in (('mixed','mixed-varied-set','mixed-shared-set') if replay else ('mixed-varied-set',)) or
            row['warmup'] != base['pair_record']['warmup'] or m['slot_map'] != base['slot_map'] or
            m['input_sha256'] != base['pair_record']['input_sha256'] or
            m['routing_sha256'] != base['pair_record']['routing_sha256'] or
            row['pair'] != base['pair_record']['pair']):
        raise ValueError('stage selected pair mismatch')
    files = {arm+'.'+stage+'.bin' for arm in ('A','B') for stage in STAGES}
    files |= {name+'.q8_0.bin' for name in ('gate','up','down')}
    if set(m['files']) != files:
        raise ValueError('stage file coverage mismatch')
    total = 0
    for name, meta in m['files'].items():
        shape = meta['shape']
        if len(shape) != 4 or any(type(v) is not int or v < 1 for v in shape):
            raise ValueError('stage shape invalid')
        size = math.prod(shape)*4 if name.endswith('.bin') and '.q8_0.' not in name else math.prod(shape)//32*34
        total += size
        path = directory/name
        if (total > LIMIT or path.stat().st_size != size or meta['byte_length'] != size or
                digest(path.read_bytes()) != meta['sha256']):
            raise ValueError('stage size/identity/budget mismatch: '+name)
        if '.q8_0.' in name:
            if (meta['ggml_type'] != 8 or meta['type_name'] != 'q8_0' or shape[0]%32 or
                    shape[2:] != [5,1] or meta['B_actual_sha256'] != meta['sha256']):
                raise ValueError('stage Q8_0 identity mismatch')
        elif (meta['ggml_type'] != 0 or meta['type_name'] != 'f32' or
              shape[1:] != [10 if name.startswith('A.') else 5,tokens,1]):
            raise ValueError('stage F32 layout mismatch')
    if total != m['payload_bytes']:
        raise ValueError('stage payload size mismatch')
    for name, meta in base['tensors'].items():
        path = directory.parent/'capture'/meta['file']
        if path.stat().st_size != meta['byte_length'] or digest(path.read_bytes()) != meta['sha256']:
            raise ValueError('base tensor identity mismatch: '+name)
    for name, sha in base['identities'].items():
        if digest((directory.parent/name).read_bytes()) != sha:
            raise ValueError('base bank identity mismatch')
    inventory = {t['name']:t for t in json.loads((directory.parent/'weights.json').read_text())['tensors']}
    d = base['tensors']['A.input']['shape'][0]
    f = m['files']['A.gate.bin']['shape'][0]
    for stage in STAGES:
        width = f if stage in ('gate','up','swiglu') else d
        for arm, count in (('A',10), ('B',5)):
            meta = m['files'][arm+'.'+stage+'.bin']
            if (meta['shape'] != [width,count,tokens,1] or
                    meta['strides_bytes'] != [4,width*4,width*count*4,width*count*tokens*4] or
                    not meta['flags'] & 2):
                raise ValueError('retained stage dimensions/strides/flags mismatch')
    for bank in ('gate','up','down'):
        meta = m['files'][bank+'.q8_0.bin']
        columns, rows = (f,d) if bank=='down' else (d,f)
        stride = columns//32*34
        if (meta['shape'] != [columns,rows,5,1] or
                meta['strides_bytes'] != [34,stride,stride*rows,stride*rows*5] or
                meta['source_sha256'] != inventory[meta['source_tensor']]['sha256']):
            raise ValueError('stage bank source/layout mismatch')
    return m


def baseline_comparison(base, baseline):
    """Use final outputs and boundary hashes only, including old schema-1 runs."""
    path = Path(baseline)/'native/capture'
    old = json.loads((path/'manifest.json').read_text())
    old_row, row = old['pair_record'], base['pair_record']
    result = {}
    for key in ('case','tokens','pair','warmup','input_sha256','routing_sha256'):
        if row[key] != old_row[key]:
            raise ValueError('baseline selected boundary differs: '+key)
    for arm in ('A','B'):
        observed = (path/(arm+'.output.bin')).read_bytes()
        if digest(observed) != old_row[arm]['output_sha256']:
            raise ValueError('baseline output identity mismatch')
        result[arm+'_output_equal'] = row[arm]['output_sha256'] == digest(observed)
    result['final_hashes_equal'] = all(result.values())
    result['interpretation'] = ('instrumented final outputs reproduce the supplied uninstrumented outputs; stages are still from retained execution'
        if result['final_hashes_equal'] else 'instrumentation changes final numerical behavior; do not attribute these stages to the original failure')
    return result


def mathematical_dot(directory, manifest, stage, token, slot, coordinate, side, base_data):
    """One selected Q8_0-row dot at 100 decimal digits; not a backend emulator."""
    bank_name = stage+'.q8_0.bin'
    meta = manifest['files'][bank_name]
    ne0, ne1, _, _ = meta['shape']
    entry = next(e for e in manifest['slot_map'] if e['token']==token and e['branch']=='hot' and e['branch_slot']==slot)
    compact = HOT.index(entry['global_expert'])
    bank = (directory/bank_name).read_bytes()
    row_start = (compact*ne1+coordinate)*(ne0//32*34)
    if stage in ('gate','up'):
        operand = base_data['A.input' if side=='A' else 'B.hot.input'][token*ne0:(token+1)*ne0]
    else:
        swiglu = floats((directory/(side+'.swiglu.bin')).read_bytes())
        original_slot = entry['original_slot'] if side=='A' else slot
        slots = 10 if side=='A' else 5
        start = (token*slots+original_slot)*ne0
        operand = swiglu[start:start+ne0]
    with localcontext() as context:
        context.prec = 100
        total = Decimal(0)
        for block in range(ne0//32):
            offset = row_start+block*34
            scale = Decimal.from_float(struct.unpack_from('<e',bank,offset)[0])
            qs = struct.unpack_from('<32b',bank,offset+2)
            for j, q in enumerate(qs):
                total += scale*Decimal(q)*Decimal.from_float(operand[block*32+j])
    return dict(decimal=str(total), value=float(total), operand_sha256=digest(struct.pack('<'+'f'*ne0,*operand)))


def analyze(directory, baseline=None, reference=False):
    directory = Path(directory)
    m = load_capture(directory)
    base = json.loads((directory.parent/'capture/manifest.json').read_text())
    base_data = {name:floats((directory.parent/'capture'/meta['file']).read_bytes())
                 for name,meta in base['tensors'].items() if meta['type_name']=='f32'}
    result = dict(schema='h5-layer7-stage-analysis/1', performance_claim=False,
                  execution=m['execution'], perturbation=m['perturbation'], stages={},
                  selected_pair={k:m['pair_record'][k] for k in ('case','tokens','pair','warmup','order')},
                  baseline=baseline_comparison(base,baseline) if baseline else {'status':'not supplied; original-output equivalence unverified'})
    for stage in STAGES:
        a = floats((directory/('A.'+stage+'.bin')).read_bytes())
        b = floats((directory/('B.'+stage+'.bin')).read_bytes())
        width = m['files']['A.'+stage+'.bin']['shape'][0]
        if m['files']['B.'+stage+'.bin']['shape'][0] != width:
            raise ValueError('paired stage widths differ')
        tokens = []
        for token in range(2):
            profiles = []
            for entry in m['slot_map']:
                if entry['token'] != token or entry['branch'] != 'hot':
                    continue
                slot, branch = entry['original_slot'], entry['branch_slot']
                av = a[(token*10+slot)*width:(token*10+slot+1)*width]
                bv = b[(token*5+branch)*width:(token*5+branch+1)*width]
                if not all(math.isfinite(v) for v in (*av,*bv)):
                    raise ValueError('nonfinite executed stage')
                differences = [y-x for x,y in zip(av,bv)]
                squared = sum(d*d for d in differences)
                at = max(range(width),key=lambda c:abs(differences[c]))
                profiles.append(dict(token=token, original_slot=slot, branch_slot=branch,
                    global_expert=entry['global_expert'], exact_coordinates=sum(d==0 for d in differences),
                    max_abs=abs(differences[at]), rms=math.sqrt(squared/width),
                    relative_l2=math.sqrt(squared/max(sum(x*x for x in av),1e-300)),
                    coordinate=at,A=av[at],B=bv[at]))
            worst = max(profiles,key=lambda p:p['max_abs'])
            record = dict(token=token, exact=all(p['exact_coordinates']==width for p in profiles),
                          worst=worst,experts=profiles)
            if reference and stage in ('gate','up','down'):
                refs = {side:mathematical_dot(directory,m,stage,token,worst['branch_slot'],worst['coordinate'],side,base_data) for side in ('A','B')}
                refs['A']['backend_minus_reference'] = worst['A']-refs['A']['value']
                refs['B']['backend_minus_reference'] = worst['B']-refs['B']['value']
                record['mathematical_dequantized_reference'] = refs
            tokens.append(record)
        result['stages'][stage] = tokens
    result['first_differing_boundaries'] = {}
    for token in range(2):
        projections = [s for s in ('gate','up') if not result['stages'][s][token]['exact']]
        d = len(base_data['A.input'])//2
        input_equal = base_data['A.input'][token*d:(token+1)*d] == base_data['B.hot.input'][token*d:(token+1)*d]
        first = (['input'] if not input_equal else projections) or next(([s] for s in ('swiglu','down','weighted') if not result['stages'][s][token]['exact']),[])
        result['first_differing_boundaries'][str(token)] = first
    result['reference_scope'] = '100-digit Decimal Q8_0 dequantized row dots; actual backend activation quantization, fused arithmetic and rounding are not modeled'
    result['causality_limit'] = 'first differing executed boundary is not a specific kernel-stage cause; gate/up are parallel inputs; retention can inhibit fusion'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True,help='native/stages directory')
    parser.add_argument('--baseline',type=Path,help='existing uninstrumented benchmark directory')
    parser.add_argument('--reference',action='store_true',help='six selected individual-row Decimal comparisons')
    parser.add_argument('--output',type=Path,required=True,help='fresh JSON result')
    args = parser.parse_args()
    result = analyze(args.capture,args.baseline,args.reference)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'output':str(args.output),'baseline':result['baseline'],'first_differing_boundaries':result['first_differing_boundaries']},sort_keys=True))
