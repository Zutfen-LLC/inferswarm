#!/usr/bin/env python3
"""Offline checks and prespecified within-session contrasts for the 2x2 fixture."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics
import struct
import sys
import time

HERE = Path(__file__).resolve().parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


legacy = module('factorial_legacy_operand','layer7_operand_check.py')
stages = module('factorial_stage_contract','factorial_stages.py')
mmvq = module('factorial_mmvq','factorial_mmvq_check.py')
ARMS = ('cpu','current5','pipeline5','current10','pipeline10')
exact = legacy.exact


def validate_boundary(base, raw, d, slot_map, tokens):
    """Re-derive all consumed bytes, original slots and compact resident IDs."""
    hot, cold, resident = stages.placement(base)
    row = base['pair_record']
    shapes = {name:[d,tokens,1,1] for name in
        ('A.input','B.input','B.hot.input','A.output','B.output','A.shared','B.shared')}
    for arm in ('A','B'):
        shapes[arm+'.ids'] = [10,tokens,1,1]
        shapes[arm+'.weights'] = [1,10,tokens,1]
        shapes[arm+'.weighted'] = [d,10,tokens,1]
    for branch, count in (('hot',hot),('cold',cold)):
        if count:
            shapes['B.'+branch+'.ids'] = [count,tokens,1,1]
            shapes['B.'+branch+'.weights'] = [1,count,tokens,1]
    if set(raw) != set(shapes) or set(base['tensors']) != set(shapes):
        raise ValueError('base tensor coverage mismatch (zero-cold tensors must be absent)')
    for name, shape in shapes.items():
        meta = base['tensors'][name]; strides = [4]
        for dim in shape[:-1]: strides.append(strides[-1]*dim)
        integer = name.endswith('.ids')
        if (meta['shape'] != shape or meta['strides_bytes'] != strides or
                meta['ggml_type'] != (26 if integer else 0) or meta['type_name'] != ('i32' if integer else 'f32') or
                len(raw[name]) != math.prod(shape)*4):
            raise ValueError('base shape/type/stride mismatch: '+name)
        if not integer and not all(math.isfinite(v) for v in stages.floats(raw[name])):
            raise ValueError('nonfinite base tensor: '+name)
    if (base['B_weighted_source'] != 'retained-branch-outputs/1' or
            raw['A.input'] != raw['B.input'] or raw['A.input'] != raw['B.hot.input'] or
            raw['A.ids'] != raw['B.ids'] or raw['A.weights'] != raw['B.weights'] or
            stages.digest(raw['A.input']) != row['input_sha256'] or
            stages.digest(raw['A.ids']+raw['A.weights']) != row['routing_sha256']):
        raise ValueError('consumed boundary identity mismatch')
    ids = struct.unpack('<'+str(tokens*10)+'i',raw['A.ids'])
    bits = struct.unpack('<'+str(tokens*10)+'I',raw['A.weights'])
    row_ids = row['ids'] if tokens == 1 else [v for r in row['ids'] for v in r]
    row_bits = row['weight_bits'] if tokens == 1 else [v for r in row['weight_bits'] for v in r]
    if list(ids) != row_ids or [f'{v:08x}' for v in bits] != row_bits:
        raise ValueError('selected routing ID/weight bits mismatch')
    if any(not math.isfinite(w) or w <= 0 for w in stages.floats(raw['A.weights'])):
        raise ValueError('routing weights must be finite positive')
    expected = []
    for token in range(tokens):
        counts = dict(hot=0,cold=0); token_ids = ids[token*10:(token+1)*10]
        if len(set(token_ids)) != 10 or any(v not in stages.RESIDENT10 for v in token_ids):
            raise ValueError('invalid selected expert IDs')
        if sum(v in stages.HOT for v in token_ids) != 5:
            raise ValueError('fixture changed original five/five selection')
        for slot, expert in enumerate(token_ids):
            compact = resident.index(expert) if expert in resident else None
            branch = 'hot' if compact is not None else 'cold'; count = hot if branch == 'hot' else cold
            branch_slot = counts[branch]
            if branch_slot >= count:
                raise ValueError('selected expert outside frozen resident union/partition')
            expected.append(dict(token=token,original_slot=slot,global_expert=expert,
                branch=branch,branch_slot=branch_slot,compact_expert=compact))
            at = token*count+branch_slot
            actual_id = struct.unpack_from('<i',raw['B.'+branch+'.ids'],at*4)[0]
            actual_weight = struct.unpack_from('<I',raw['B.'+branch+'.weights'],at*4)[0]
            if actual_id != (compact if branch == 'hot' else expert) or actual_weight != bits[token*10+slot]:
                raise ValueError('branch routing ID/weight/slot mismatch')
            counts[branch] += 1
        if counts != dict(hot=hot,cold=cold):
            raise ValueError('selected partition count mismatch')
    if slot_map != expected or base['slot_map'] != expected:
        raise ValueError('slot mapping mismatch')
    for arm in ('A','B'):
        if stages.digest(raw[arm+'.output']) != row[arm]['output_sha256']:
            raise ValueError('selected output identity mismatch')


def replay_binding(directory, row, timed_records):
    if timed_records is None: return 'unknown'
    binding = stages.metadata(Path(directory).parent/'replay-binding.json')
    if (binding.get('schema') != 'h5-layer7-replay-binding/1' or
            binding.get('timed_graph_retention') is not False or
            binding.get('replay_after_all_timed_work') is not True or binding.get('outputs_equal') is not True):
        return 'mismatch'
    records = timed_records if isinstance(timed_records,list) else [json.loads(s) for s in Path(timed_records).read_text().splitlines()]
    target = binding.get('timed_record')
    return 'match' if target == row and sum(r == target for r in records) == 1 else 'mismatch'


def cpu_projection(model, bank, operands, observed, mapping, columns, rows, tokens, hot, down=False, arm='B'):
    """Same frozen CPU dot profile; selected and resident dimensions are distinct."""
    slots = 10 if arm == 'A' else hot
    if len(operands) != tokens*(slots if down else 1)*columns or len(observed) != tokens*slots*rows:
        raise ValueError('CPU selected projection dimensions mismatch')
    predicted, actual, controls = [], [], []
    quantized = {}; stride = columns//32*34
    for e in mapping:
        if e['branch'] != 'hot': continue
        t = e['token']; slot = e['original_slot'] if arm == 'A' else e['branch_slot']
        key = t*slots+slot if down else t
        if key not in quantized:
            values = operands[key*columns:(key+1)*columns]
            for at in range(0,columns,32):
                amax = max(map(abs,values[at:at+32]))
                if amax and not 2**-6 <= amax <= 1024:
                    return dict(status='unknown',reason='activation scale range outside CPU profile')
            quantized[key] = model.quantize(values)
        block = []
        for c in range(rows):
            at = (e['compact_expert']*rows+c)*stride
            block.append(model.dot(bank[at:at+stride],quantized[key]))
        predicted.extend(block); actual.extend(observed[(t*slots+slot)*rows:(t*slots+slot+1)*rows])
        controls.append(dict(token=t,expert=e['global_expert'],status='rejected' if any(v != 0 for v in block) else 'insensitive'))
    result = exact(predicted,actual)
    result.update(sensitive=all(c['status']=='rejected' for c in controls),zero_expert_controls=controls)
    return result


def selected_cpu_stages(a, b, mapping, width, tokens, hot):
    expected = []
    for token in range(tokens):
        for slot in range(hot):
            e = next(e for e in mapping if e['token']==token and e['branch']=='hot' and e['branch_slot']==slot)
            at = (token*10+e['original_slot'])*width
            expected.extend(a[at:at+width])
    result = exact(expected,b)
    result['sensitive'] = all(any(v != 0 for v in b[at:at+width]) for at in range(0,len(b),width))
    return result


def analyze(directory, helper, timed_records=None, bank_cache=None, expected_record=None, comparison_mode='cpu-cuda'):
    directory = Path(directory)
    m, base, banks = stages.load_capture(directory,bank_cache)
    if expected_record is not None and m['pair_record'] != expected_record:
        raise ValueError('pair-specific replay differs from expected timed record')
    hot, cold, resident = stages.placement(m); tokens = m['pair_record']['tokens']
    d = m['files']['gate.q8_0.bin']['shape'][0]; f = m['files']['A.gate.bin']['shape'][0]
    if not (32 <= d <= 2560 and d%32 == 0 and 32 <= f <= 640 and f%32 == 0):
        return dict(status='inconclusive',reason='unsupported stage dimensions',numerical_qualification=False)
    raw = {name:(directory.parent/'capture'/meta['file']).read_bytes() for name,meta in base['tensors'].items()}
    validate_boundary(base,raw,d,m['slot_map'],tokens)
    data = {arm+'.'+stage:stages.floats((directory/(arm+'.'+stage+'.bin')).read_bytes())
        for arm in ('A','B') for stage in stages.STAGES}
    if not all(math.isfinite(v) for values in data.values() for v in values):
        raise ValueError('nonfinite retained stage')
    model = legacy.arithmetic.Arithmetic(helper)
    environment = getattr(model.library,'l7_environment_ok',None)
    if environment is None or environment() != 1:
        return dict(status='inconclusive',reason='CPU emulator requires RN with FTZ/DAZ disabled',numerical_qualification=False)
    checks = {}
    for arm, count in (('A',10),('B',hot)):
        checks[arm+'.weighting'] = legacy.weighting_check(data[arm+'.down'],stages.floats(raw[arm+'.weights' if arm=='A' else 'B.hot.weights']),data[arm+'.weighted'],d)
        restored = stages.floats(raw[arm+'.weighted']); selected = []
        for token in range(tokens):
            for slot in range(count):
                e = next(e for e in m['slot_map'] if e['token']==token and
                    (e['original_slot']==slot if arm=='A' else e['branch']=='hot' and e['branch_slot']==slot))
                at = (token*10+e['original_slot'])*d
                selected.extend(restored[at:at+d])
        checks[arm+'.restored_planes'] = exact(data[arm+'.weighted'],selected)
        checks[arm+'.composition'] = legacy.composition_check(restored,stages.floats(raw[arm+'.shared']),stages.floats(raw[arm+'.output']),d,tokens)
    ac, bc = [], []
    for e in m['slot_map']:
        if e['branch'] == 'cold':
            at = (e['token']*10+e['original_slot'])*d
            ac.extend(stages.floats(raw['A.weighted'])[at:at+d]); bc.extend(stages.floats(raw['B.weighted'])[at:at+d])
    checks['B.cold_reference'] = exact(ac,bc) if cold else dict(status='not-applicable',reason='hot=10,cold=0; no cold tensors or work')
    checks['B.shared_reference'] = exact(stages.floats(raw['A.shared']),stages.floats(raw['B.shared']))
    for stage in ('gate','up'):
        checks['A.'+stage] = cpu_projection(model,banks[stage],stages.floats(raw['A.input']),data['A.'+stage],m['slot_map'],d,f,tokens,hot,arm='A')
    if comparison_mode == 'cpu-cuda':
        for stage in ('gate','up','down'):
            down = stage == 'down'
            checks['B.'+stage] = mmvq.projection(model,banks[stage],data['B.swiglu'] if down else stages.floats(raw['B.hot.input']),
                data['B.'+stage],m['slot_map'],f if down else d,d if down else f,tokens,down,hot,len(resident))
        checks['B.swiglu'] = mmvq.swiglu(data['B.gate'],data['B.up'],data['B.swiglu'],f,tokens,hot)
    elif comparison_mode == 'cpu-loopback':
        for stage in ('gate','up'):
            checks['B.'+stage] = cpu_projection(model,banks[stage],stages.floats(raw['B.hot.input']),
                data['B.'+stage],m['slot_map'],d,f,tokens,hot)
        # Local CPU regression mode compares the remaining executed branches
        # exactly with A. It introduces no new independent CPU SwiGLU/down
        # arithmetic profile and makes no hardware qualification claim.
        for stage,width in (('swiglu',f),('down',d)):
            checks['B.'+stage] = selected_cpu_stages(data['A.'+stage],data['B.'+stage],m['slot_map'],width,tokens,hot)
    else:
        raise ValueError('unsupported comparison mode')
    sensitive = all(checks['B.'+s].get('sensitive',False) for s in ('gate','up','swiglu','down'))
    sensitive &= all(c['status']=='rejected' for arm in ('A','B') for c in checks[arm+'.composition'].get('negative_controls',[]))
    mismatch = any(c['status']=='mismatch' for c in checks.values())
    complete = all(c['status']=='match' or (name=='B.cold_reference' and cold==0 and c['status']=='not-applicable') for name,c in checks.items())
    binding = replay_binding(directory,m['pair_record'],timed_records)
    matched = complete and sensitive and binding == 'match'
    return dict(schema='h5-layer7-factorial-check/1',status='mismatch' if mismatch or binding=='mismatch' else
        ('conditional-profile-match' if comparison_mode=='cpu-cuda' else 'cpu-loopback-match') if matched else 'inconclusive',
        comparison_mode=comparison_mode,profile=mmvq.PROFILE if comparison_mode=='cpu-cuda' else legacy.CPU,
        assumption=mmvq.ASSUMPTION if comparison_mode=='cpu-cuda' else 'same pinned CPU AVX2/FMA dot profile; local fixture validation only',
        tokens=tokens,hot_count=hot,cold_count=cold,resident_count=len(resident),selected_count=10,
        timed_binding=binding,sensitive=bool(sensitive),numerical_qualification=False,performance_claim=False,
        checks=checks,legacy_comparator=base['pair_record']['correctness'],
        stage_manifest_sha256=stages.digest((directory/'manifest.json').read_bytes()))



def validate_rpc(stats, arm, d, tokens):
    hot = 10 if arm.endswith('10') else 5
    if (stats.get('hot'),stats.get('cold'),stats.get('tokens')) != (hot,10-hot,tokens):
        raise ValueError('factorial measured placement counts mismatch')
    r = stats['rpc']
    if any(r.get(k) != v for k,v in dict(commands=5,set_commands=3,set_acks=3,graph_commands=1,get_commands=1,graph_recompute=1,failed=0,pipeline=int(arm.startswith('pipeline'))).items()):
        raise ValueError('factorial measured RPC command/admission/recompute mismatch')
    if not isinstance(r.get('graph_uid'),int) or r['graph_uid'] <= 0 or len(r.get('sets',[])) != 3:
        raise ValueError('factorial graph UID/SET instrumentation mismatch')
    def ordered(*values):
        if any(type(v) is not int or v <= 0 for v in values) or list(values) != sorted(values):
            raise ValueError('factorial client timestamp order mismatch')
    ordered(r['begin_ns'],r['group_enqueue_ns'],r['group_dequeue_ns'],r['group_end_ns'],r['graph_enqueue_ns'],r['graph_write_begin_ns'],r['graph_write_end_ns'],r['get_write_begin_ns'],r['get_write_end_ns'],r['get_first_byte_ns'],r['get_last_byte_ns'],r['end_ns'])
    ordered(r['graph_enqueue_ns'],r['get_enqueue_ns'],r['get_write_begin_ns'])
    payloads = [d*tokens*4,hot*tokens*4,hot*tokens*4]
    if r.get('tx_payload_bytes') != sum(payloads) or r.get('tx_wire_bytes',0) <= sum(payloads) or r.get('rx_wire_bytes',0) < 35+d*hot*tokens*4:
        raise ValueError('factorial RPC byte counters mismatch')
    for i,item in enumerate(r['sets']):
        ordered(r['begin_ns'],item['hash_begin_ns'],item['hash_end_ns'],item['enqueue_ns'],r['group_dequeue_ns'],item['write_begin_ns'],item['write_end_ns'],item['flush_ns'],item['ack_first_ns'],item['ack_end_ns'],r['group_end_ns'])
        if item['payload_bytes'] != payloads[i] or item['wire_bytes'] <= payloads[i]:
            raise ValueError('factorial SET payload/wire counter mismatch')
        if i:
            previous = r['sets'][i-1]
            ordered(previous['write_end_ns'],item['write_begin_ns'])
            ordered(previous['ack_end_ns'],item['ack_first_ns'])
            if not r['pipeline']:ordered(previous['ack_end_ns'],item['write_begin_ns'])


def validate_records(records, small_test_grid=False):
    """Validate blocks, contemporaneous CPU references and balanced comparisons."""
    pairs, warmups = (2,1) if small_test_grid else (20,5)
    if not records or records[0].get('type') != 'factorial-setup' or records[-1].get('type') != 'factorial-summary':
        raise ValueError('incomplete factorial result')
    mode = records[0].get('comparison_mode')
    if mode not in ('cpu-loopback','cpu-cuda') or (small_test_grid and mode != 'cpu-loopback'):
        raise ValueError('factorial mode/quick grid mismatch')
    setup, summary = records[0], records[-1]
    d,f,experts,selected = setup['dimensions']
    if (setup.get('schema') != 'h5-layer7-factorial/1' or setup.get('pairs') != pairs or setup.get('warmup') != warmups or
            setup.get('tokens_list') != [1,4] or setup.get('seed') != 314159 or setup.get('representation') != 'Q8_0' or
            setup.get('resident_union') != list(stages.RESIDENT10) or setup.get('selected_per_token') != 10 or
            setup.get('five_remote_resident_count') != 5 or setup.get('ten_remote_resident_count') != 26 or
            setup.get('ten_remote_payload_bytes') != 3*d*f//32*34*26 or (experts,selected) != (512,10) or
            (d,f) != ((32,32) if setup.get('small_test') else (2560,640)) or
            setup.get('performance_claim') is not False or (small_test_grid and setup.get('small_test') is not True) or (mode=='cpu-cuda' and setup.get('small_test') is True)):
        raise ValueError('factorial frozen setup/counts/geometry mismatch')
    if (summary.get('diagnostic_complete') is not True or summary.get('numerical_qualification') is not False or
            summary.get('performance_claim') is not False):
        raise ValueError('incomplete factorial summary')
    blocks = [r for r in records if r.get('type')=='factorial-block']
    rows = [r for r in records if r.get('type')=='factorial-pair']
    expected = {(t,w,i) for t in (1,4) for w,n in ((True,warmups),(False,pairs)) for i in range(n)}
    key = lambda r:(r['tokens'],r['warmup'],r['pair'])
    if len(blocks) != len(expected) or {key(r) for r in blocks} != expected:
        raise ValueError('factorial block count/coverage mismatch')
    pair_keys = [(key(r),r['factorial_arm']) for r in rows]
    wanted = {(k,a) for k in expected for a in ARMS[1:]}
    measured_wanted = {(k,a) for k in expected if not k[1] for a in ARMS[1:]}
    if len(pair_keys) != len(set(pair_keys)) or set(pair_keys) not in (wanted,measured_wanted):
        raise ValueError('factorial pair count/coverage mismatch')
    by_key = {key(r):r for r in blocks}
    for block in blocks:
        if (not isinstance(block['order'],list) or len(block['order']) != 5 or
                set(block['order']) != set(ARMS) or set(block['arms']) != set(ARMS)):
            raise ValueError('factorial block arm/order coverage mismatch')
        for name, stats in block['arms'].items():
            value = stats['total_layer_ms']
            if type(value) not in (float,int) or not math.isfinite(value) or value <= 0:
                raise ValueError('invalid factorial layer time')
            if stats.get('order') != block['order'].index(name):
                raise ValueError('factorial arm order position mismatch')
            if name == 'cpu':
                if stats.get('commands') != 0 or 'rpc' in stats:
                    raise ValueError('ordinary CPU arm contains RPC work')
            else:
                validate_rpc(stats,name,d,block['tokens'])
    for row in rows:
        block = by_key[key(row)]; arm = row['factorial_arm']
        if row['A'] != block['arms']['cpu'] or row['B'] != block['arms'][arm]:
            raise ValueError('factorial pair not bound to contemporaneous block arm')
        if row['case'] != ('mixed' if row['tokens']==1 else 'mixed-varied-set'):
            raise ValueError('factorial case outside frozen scope')
        expected_order = 'AB' if block['order'].index('cpu') < block['order'].index(arm) else 'BA'
        if (row['order'] != expected_order or not row['correctness']['finite'] or
                any(row[s]['input_sha256'] != row['input_sha256'] or row[s]['routing_sha256'] != row['routing_sha256'] for s in ('A','B'))):
            raise ValueError('factorial input/routing/finite/order mismatch')
        siblings = [r for r in rows if key(r)==key(row)]
        if any(r['input_sha256'] != row['input_sha256'] or r['routing_sha256'] != row['routing_sha256'] or
               r['ids'] != row['ids'] or r['weight_bits'] != row['weight_bits'] for r in siblings):
            raise ValueError('factorial factors changed fixture bytes/routing')
    measured = [r for r in rows if not r['warmup']]
    replays = [r for r in records if r.get('type')=='factorial-replay']
    replay_key = lambda r:(r['tokens'],r['case'],r['pair'],r['factorial_arm'])
    if ([replay_key(r) for r in replays] != [replay_key(r) for r in measured] or
            summary.get('replays') != len(measured) or not all(r.get('outputs_equal') is True for r in replays) or
            not replays or records.index(replays[0]) <= max(i for i,r in enumerate(records) if r.get('type')=='factorial-pair')):
        raise ValueError('incomplete, reordered or unbound factorial replay grid')
    if not small_test_grid:
        for tokens in (1,4):
            selected = [b for b in blocks if b['tokens']==tokens and not b['warmup']]
            for i,a in enumerate(ARMS):
                for b in ARMS[i+1:]:
                    if sum(r['order'].index(a)<r['order'].index(b) for r in selected) != 10:
                        raise ValueError('factorial pairwise order balance mismatch')
    return measured, blocks, mode


def performance(blocks, small_test_grid=False):
    """Resample complete fixture blocks; intervals describe this one session."""
    def distribution(values):
        ordered = sorted(values)
        return dict(count=len(values),median=statistics.median(values),minimum=ordered[0],maximum=ordered[-1],
                    p95=ordered[math.ceil(.95*len(values))-1])
    def interval(values, seed):
        rng = random.Random(seed); count = len(values)
        samples = sorted(statistics.median(values[rng.randrange(count)] for _ in values) for _ in range(10000))
        return [samples[249],samples[9749]]
    cases = {}
    for tokens in (1,4):
        rows = sorted((b for b in blocks if b['tokens']==tokens and not b['warmup']),key=lambda b:b['pair'])
        times = {a:[r['arms'][a]['total_layer_ms'] for r in rows] for a in ARMS}
        contrasts = {a+'_minus_cpu':[v-c for v,c in zip(times[a],times['cpu'])] for a in ARMS[1:]}
        contrasts.update(transport_at_five=[p-c for p,c in zip(times['pipeline5'],times['current5'])],
            transport_at_ten=[p-c for p,c in zip(times['pipeline10'],times['current10'])],
            placement_current=[t-f for t,f in zip(times['current10'],times['current5'])],
            placement_pipeline=[t-f for t,f in zip(times['pipeline10'],times['pipeline5'])],
            interaction=[(pt-ct)-(pf-cf) for pt,ct,pf,cf in zip(times['pipeline10'],times['current10'],times['pipeline5'],times['current5'])])
        contrasts['transport_average'] = [(a+b)/2 for a,b in zip(contrasts['transport_at_five'],contrasts['transport_at_ten'])]
        contrasts['placement_average'] = [(a+b)/2 for a,b in zip(contrasts['placement_current'],contrasts['placement_pipeline'])]
        contrast_reports = {name:dict(**distribution(values),median_paired_bootstrap_95_ms=interval(values,314159+tokens*100+i))
            for i,(name,values) in enumerate(contrasts.items())}
        screens = {}
        for a in ARMS[1:]:
            gain = statistics.median((c-v)/c for c,v in zip(times['cpu'],times[a]))
            upper = contrast_reports[a+'_minus_cpu']['median_paired_bootstrap_95_ms'][1]
            screens[a] = dict(median_paired_fraction_gain=gain,conservative_adoption_screen=not small_test_grid and gain>=.10 and upper<0,
                measured_direction='faster' if statistics.median(contrasts[a+'_minus_cpu'])<0 else 'slower-or-tied')
        cases['t'+str(tokens)] = dict(raw_total_layer_ms=times,latency_ms={a:distribution(v) for a,v in times.items()},
            paired_contrasts_ms=contrast_reports,per_width_adoption_screen=screens)
    return dict(scope='one contemporaneous warmed synthetic single-layer session; decode and batched widths assessed separately',
        timer='total_layer_ms wall time; overlapping client spans are not added',
        uncertainty='deterministic percentile bootstrap of paired fixture-block median contrasts; 10000 resamples, seeds 314159+100*t+contrast_index; order-statistic endpoints 249/9749 (zero based); within-session sampling only, not independent-session or hardware-population uncertainty',
        frozen_screen='per width: >=10% median paired gain over CPU and upper paired median-difference 95% interval <0; smaller gains are still reported',
        excludes=['warmup','setup','one immediate untimed prime per arm','replay','checking'],cases=cases)


def analyze_replays(benchmark, helper, small_test_grid=False):
    benchmark = Path(benchmark); stdout = benchmark/'stdout.jsonl'
    if stdout.stat().st_size > 64*1024*1024:
        raise ValueError('factorial stdout budget exceeded')
    records = [json.loads(line) for line in stdout.read_text().splitlines()]
    timed, blocks, mode = validate_records(records,small_test_grid)
    reports = []; cache = {}; started = time.monotonic()
    for row in timed:
        path = benchmark/'native/replays'/('t'+str(row['tokens'])+'-'+row['case']+'-p'+str(row['pair'])+'-'+row['factorial_arm'])/'stages'
        report = analyze(path,helper,records,cache,row,mode)
        report.update(case=row['case'],pair=row['pair'],factorial_arm=row['factorial_arm'])
        reports.append(report)
        print(json.dumps(dict(checked=len(reports),expected=len(timed),tokens=row['tokens'],arm=row['factorial_arm'],pair=row['pair'],status=report['status'],analysis_seconds=time.monotonic()-started)),file=sys.stderr,flush=True)
    good = 'conditional-profile-match' if mode=='cpu-cuda' else 'cpu-loopback-match'
    status = 'mismatch' if any(r['status']=='mismatch' for r in reports) else good if all(r['status']==good for r in reports) else 'inconclusive'
    result = dict(schema='h5-layer7-factorial-analysis/1',status=status,numerical_qualification=False,performance_claim=False,
        comparison_mode=mode,small_test_grid=small_test_grid,profiles=reports,measured_factorial_pairs=len(timed),
        measured_fixture_blocks=sum(not b['warmup'] for b in blocks),warmup_fixture_blocks=sum(b['warmup'] for b in blocks),
        analysis_seconds=time.monotonic()-started,unique_banks_read=len(cache),immutable_bank_bytes_cached=sum(len(value[1]) for value in cache.values()),
        checker_sha256=stages.digest(Path(__file__).read_bytes()),helper_sha256=stages.digest(Path(helper).read_bytes()),
        timed_records_sha256=stages.digest(stdout.read_bytes()),legacy_all_pass=all(r['correctness']['pass'] for r in timed),
        legacy_finite_disagreements=sum(not r['correctness']['pass'] and r['correctness']['finite'] for r in timed),
        scope='five/ten selected experts remote out of the same ten selected per token; 5/26 resident single-layer fixture experts, not full-capacity or full-model placement')
    if status==good:
        result['observational_performance'] = performance(blocks,small_test_grid)
        result['accuracy_assumption'] = reports[0]['assumption']
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replays',type=Path,required=True)
    parser.add_argument('--helper',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--small-test-grid',action='store_true',help='CPU-only 2 measured/1 warmup diagnostic grid; no adoption screen')
    args = parser.parse_args()
    result = analyze_replays(args.replays,args.helper,args.small_test_grid)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:result[k] for k in ('status','numerical_qualification','analysis_seconds')}))
    raise SystemExit(0 if result['status'] in ('conditional-profile-match','cpu-loopback-match') else 2 if result['status']=='mismatch' else 3)
