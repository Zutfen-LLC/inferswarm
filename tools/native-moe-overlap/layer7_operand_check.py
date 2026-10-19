#!/usr/bin/env python3
"""Offline, partial operand checks. Never qualifies a CPU/CUDA benchmark pair."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import time
import statistics

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('l7_operand_arithmetic', HERE/'layer7_arithmetic.py')
arithmetic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arithmetic)
stages = arithmetic.stages
CPU = 'b29c606e-q8_0-avx2-fma/1'


class UnsupportedProfile(ValueError):
    pass


def normal(value):
    if value != 0 and abs(value) < 2**-126:
        raise UnsupportedProfile('F32 subnormal arithmetic/FTZ contract unavailable')
    return value


def f32(value):
    """RN binary32 operation result, rejecting overflow and nonfinite values."""
    value = struct.unpack('<f', struct.pack('<f', value))[0]
    if not math.isfinite(value):
        raise ValueError('nonfinite arithmetic')
    return value


def exact(expected, observed):
    if not expected or len(expected) != len(observed):
        raise ValueError('nonempty matching shapes required')
    if not all(math.isfinite(v) for v in (*expected, *observed)):
        raise ValueError('nonfinite operand/result')
    errors = [i for i, (a, b) in enumerate(zip(expected, observed))
              if struct.pack('<f', a) != struct.pack('<f', b)]
    return dict(status='mismatch' if errors else 'match', coordinates=len(expected),
                mismatches=len(errors), first_mismatch=errors[0] if errors else None,
                max_abs=max(abs(a-b) for a, b in zip(expected, observed)))


def compose(weighted, shared, d, tokens=2, omit=None):
    """Pinned graph: left fold slots 0..9 with F32 adds, then shared add."""
    if (not 1 <= d <= 2560 or tokens not in (1, 2, 4, 8) or len(weighted) != tokens*10*d or
            len(shared) != tokens*d or
            not all(math.isfinite(v) for v in (*weighted, *shared))):
        raise ValueError('finite bounded composition shapes required')
    if omit is not None and omit not in range(11):
        raise ValueError('omission must be slot 0..9 or shared=10')
    for v in (*weighted, *shared):
        normal(v)
    result = []
    for token in range(tokens):
        for c in range(d):
            total = 0. if omit == 0 else weighted[token*10*d+c]
            for slot in range(1, 10):
                v = 0. if omit == slot else weighted[(token*10+slot)*d+c]
                total = normal(f32(total+v))
            result.append(normal(f32(total+(0. if omit == 10 else shared[token*d+c]))))
    return result


def composition_check(weighted, shared, output, d, tokens=2):
    try:
        reference = compose(weighted, shared, d, tokens=tokens)
    except UnsupportedProfile as error:
        return dict(status='unknown', reason=str(error))
    result = exact(reference, output)
    controls = []
    for token in range(tokens):
        original = reference[token*d:(token+1)*d]
        token_planes = weighted[token*10*d:(token+1)*10*d]
        token_shared = shared[token*d:(token+1)*d]
        for slot in range(11):
            try:
                changed = compose(token_planes, token_shared, d, tokens=1, omit=slot)
            except UnsupportedProfile:
                controls.append(dict(token=token, omitted='shared' if slot == 10 else slot,
                                     status='unknown-subnormal-control'))
                continue
            mass = (shared[token*d:(token+1)*d] if slot == 10 else
                    weighted[(token*10+slot)*d:(token*10+slot+1)*d])
            detected = exact(original, changed)['status'] == 'mismatch'
            controls.append(dict(token=token, omitted='shared' if slot == 10 else slot,
                status=('insensitive-zero-mass' if all(v == 0 for v in mass) else
                        'rejected' if detected else 'insensitive-rounding')))
        if tokens == 1:
            continue
        other_token = (token+1)%tokens
        other = output[other_token*d:(other_token+1)*d]
        controls.append(dict(token=token, omitted='stale-other-token-output',
            status='rejected' if exact(original, other)['status'] == 'mismatch'
                   else 'insensitive-identical-output'))
    result['negative_controls'] = controls
    return result


def weighting_check(down, weights, observed, d):
    if len(down) != len(observed) or len(down) != len(weights)*d:
        raise ValueError('weighting shape mismatch')
    if not all(math.isfinite(v) for v in (*down, *weights, *observed)):
        raise ValueError('nonfinite weighting')
    try:
        for v in (*down, *weights):
            normal(v)
        predicted = [normal(f32(v*weights[i//d])) for i, v in enumerate(down)]
    except UnsupportedProfile as error:
        return dict(status='unknown', reason=str(error))
    return exact(predicted, observed)


def validate_boundary(base, raw, d, slot_map, tokens=2):
    """Cross-check bytes against the selected pair, never trust a boolean flag."""
    row = base['pair_record']
    shapes = {name: [d, tokens, 1, 1] for name in
              ('A.input', 'B.input', 'B.hot.input', 'A.output', 'B.output', 'A.shared', 'B.shared')}
    for arm in ('A', 'B'):
        shapes[arm+'.ids'] = [10, tokens, 1, 1]
        shapes[arm+'.weights'] = [1, 10, tokens, 1]
        shapes[arm+'.weighted'] = [d, 10, tokens, 1]
    for branch in ('hot', 'cold'):
        shapes['B.'+branch+'.ids'] = [5, tokens, 1, 1]
        shapes['B.'+branch+'.weights'] = [1, 5, tokens, 1]
    if set(raw) != set(shapes) or set(base['tensors']) != set(shapes):
        raise ValueError('base tensor coverage mismatch')
    for name, shape in shapes.items():
        meta = base['tensors'][name]
        strides = [4]
        for dim in shape[:-1]:
            strides.append(strides[-1]*dim)
        integer = name.endswith('.ids')
        if (meta['shape'] != shape or meta['strides_bytes'] != strides or
                meta['ggml_type'] != (26 if integer else 0) or
                meta['type_name'] != ('i32' if integer else 'f32') or
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
    ids = struct.unpack('<'+str(tokens*10)+'i', raw['A.ids'])
    weights = struct.unpack('<'+str(tokens*10)+'I', raw['A.weights'])
    row_ids = row['ids'] if tokens == 1 else [i for r in row['ids'] for i in r]
    row_weights = row['weight_bits'] if tokens == 1 else [i for r in row['weight_bits'] for i in r]
    if (list(ids) != row_ids or
            [f'{v:08x}' for v in weights] != row_weights):
        raise ValueError('selected routing ID/weight bits mismatch')
    expected = []
    for token in range(tokens):
        counts = dict(hot=0, cold=0)
        token_ids = ids[token*10:(token+1)*10]
        if len(set(token_ids)) != 10 or any(not 0 <= i < 512 for i in token_ids):
            raise ValueError('invalid expert IDs')
        for slot, expert in enumerate(token_ids):
            compact = stages.HOT.index(expert) if expert in stages.HOT else None
            branch = 'hot' if compact is not None else 'cold'
            branch_slot = counts[branch]
            expected.append(dict(token=token, original_slot=slot, global_expert=expert,
                                 branch=branch, branch_slot=branch_slot, compact_expert=compact))
            counts[branch] += 1
            at = token*5+branch_slot
            if branch_slot >= 5:
                raise ValueError('unsupported expert partition')
            actual_id = struct.unpack_from('<i', raw['B.'+branch+'.ids'], at*4)[0]
            actual_weight = struct.unpack_from('<I', raw['B.'+branch+'.weights'], at*4)[0]
            if actual_id != (compact if branch == 'hot' else expert) or actual_weight != weights[token*10+slot]:
                raise ValueError('branch routing ID/weight/slot mismatch')
        if counts != dict(hot=5, cold=5):
            raise ValueError('unsupported expert partition')
    if slot_map != expected or base['slot_map'] != expected:
        raise ValueError('slot mapping mismatch')
    for arm in ('A', 'B'):
        if stages.digest(raw[arm+'.output']) != row[arm]['output_sha256']:
            raise ValueError('selected output identity mismatch')


def cpu_projection(helper, bank, inputs, observed, slot_map, d, f, profile=CPU):
    if profile != CPU:
        return dict(status='unknown', reason='unsupported arithmetic profile')
    environment = getattr(helper.library, 'l7_environment_ok', None)
    if environment is None or environment() != 1:
        return dict(status='unknown', reason='emulator needs RN rounding with FTZ/DAZ disabled')
    if not (32 <= d <= 2560 and d % 32 == 0 and 1 <= f <= 640):
        return dict(status='unknown', reason='unsupported projection dimensions')
    if len(inputs) != 2*d or len(observed) != 20*f or len(bank) != 5*f*(d//32*34):
        raise ValueError('projection shape mismatch')
    if not all(math.isfinite(v) for v in (*inputs, *observed)):
        raise ValueError('nonfinite projection')
    for offset in range(0, len(bank), 34):
        scale = struct.unpack_from('<e', bank, offset)[0]
        if not math.isfinite(scale):
            raise ValueError('nonfinite Q8 scale')
    quantized = []
    for token in range(2):
        values = inputs[token*d:(token+1)*d]
        for block in range(d//32):
            amax = max(abs(v) for v in values[block*32:(block+1)*32])
            if amax != 0 and not 2**-6 <= amax <= 1024:
                return dict(status='unknown', reason='activation scale range outside profile')
        quantized.append(helper.quantize(values))
    predictions, actual = [], []
    stride = d//32*34
    for entry in slot_map:
        if entry['branch'] != 'hot':
            continue
        token, compact, slot = entry['token'], entry['compact_expert'], entry['original_slot']
        for coordinate in range(f):
            at = (compact*f+coordinate)*stride
            predictions.append(helper.dot(bank[at:at+stride], quantized[token]))
            actual.append(observed[(token*10+slot)*f+coordinate])
    return exact(predictions, actual)


def replay_binding(directory, row, timed_records):
    if timed_records is None:
        return 'unknown'
    binding = json.loads((directory.parent/'replay-binding.json').read_text())
    if (binding.get('schema') != 'h5-layer7-replay-binding/1' or
            binding.get('timed_graph_retention') is not False or
            binding.get('replay_after_all_timed_work') is not True):
        return 'mismatch'
    records = timed_records if isinstance(timed_records, list) else [
        json.loads(line) for line in Path(timed_records).read_text().splitlines()]
    target = binding['timed_record']
    if binding.get('outputs_equal') is not True or sum(record == target for record in records) != 1:
        return 'mismatch'
    for key in ('case','tokens','pair','warmup','order','input_sha256','routing_sha256','ids','weight_bits'):
        if target[key] != row[key]: return 'mismatch'
    return 'match' if all(target[arm]['output_sha256'] == row[arm]['output_sha256']
                          for arm in ('A','B')) else 'mismatch'


def analyze_replays(benchmark, helper):
    benchmark = Path(benchmark)
    records = [json.loads(line) for line in (benchmark/'stdout.jsonl').read_text().splitlines()]
    timed = [r for r in records if r.get('type') == 'pair' and not r['warmup']]
    widths = records[0]['tokens_list']
    warmed = records[0].get('warmed_operand_sweep', False)
    module_spec = importlib.util.spec_from_file_location('l7_bench_contract', HERE/'layer7_bench.py')
    contract = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(contract)
    contract.validate_result(records, 20 if warmed else 1, 5 if warmed else 0,
        records[0]['comparison_mode'], widths, operand_replay=True)
    reports = []
    bank_cache = {}
    started = time.monotonic()
    for row in timed:
        path = benchmark/'native/replays'/('t'+str(row['tokens'])+'-'+row['case']+
            ('-p'+str(row['pair']) if warmed else ''))/'stages'
        report = analyze(path, helper, True, records, bank_cache, row)
        report.update(case=row['case'], pair=row['pair'])
        reports.append(report)
        print(json.dumps(dict(checked=len(reports), expected=len(timed), tokens=row['tokens'],
            case=row['case'], pair=row['pair'], status=report['status'],
            analysis_seconds=time.monotonic()-started)), file=sys.stderr, flush=True)
    matched = all(r['status'] == 'conditional-profile-match' for r in reports)
    result = dict(schema='h5-layer7-conditional-replays/1', numerical_qualification=False,
        performance_claim=False, status='conditional-profile-match' if all(
            r['status'] == 'conditional-profile-match' for r in reports) else 'inconclusive',
        profiles=reports, legacy_all_pass=all(r['correctness']['pass'] for r in records if r.get('type') == 'pair'),
        measured_pairs=len(timed), warmup_pairs=sum(r.get('type') == 'pair' and r['warmup'] for r in records),
        analysis_seconds=time.monotonic()-started, checker_sha256=stages.digest(Path(__file__).read_bytes()),
        helper_sha256=stages.digest(Path(helper).read_bytes()),
        timed_records_sha256=stages.digest((benchmark/'stdout.jsonl').read_bytes()))
    if warmed and matched:
        result['conditional_performance'] = performance(timed)
        result['accuracy_assumption'] = reports[0]['assumption']
    return result


def performance(timed):
    """Measured paired wall times only, after the caller validates every replay."""
    def distribution(values):
        ordered = sorted(values)
        return dict(count=len(values), median=statistics.median(values), minimum=ordered[0],
                    maximum=ordered[-1], p95=ordered[math.ceil(.95*len(values))-1])
    cases = {}
    for key in sorted({(r['tokens'],r['case']) for r in timed}):
        t, case = key
        rows = [r for r in timed if (r['tokens'],r['case']) == key]
        a = [r['A']['total_layer_ms'] for r in rows]
        b = [r['B']['total_layer_ms'] for r in rows]
        cases[case+'@t'+str(t)] = dict(A_ms=distribution(a), B_ms=distribution(b),
            B_minus_A_ms=distribution([y-x for x,y in zip(a,b)]),
            A_ms_per_token=distribution([x/t for x in a]), B_ms_per_token=distribution([x/t for x in b]),
            A_tokens_per_s=distribution([1000*t/x for x in a]), B_tokens_per_s=distribution([1000*t/x for x in b]),
            B_faster_count=sum(y<x for x,y in zip(a,b)), AB_count=sum(r['order']=='AB' for r in rows),
            BA_count=sum(r['order']=='BA' for r in rows))
    return dict(scope='experimental timings conditional on the assumed vendor accuracy profile; no numerical qualification',
                excludes=['warmup','setup','replay','checking'], timer='total_layer_ms wall time; no sum of overlapping stages', cases=cases)


def analyze(directory, helper, conditional=False, timed_records=None, bank_cache=None, expected_record=None):
    directory = Path(directory)
    if (directory/'manifest.json').stat().st_size > 65536:
        raise ValueError('stage metadata budget exceeded')
    preliminary = json.loads((directory/'manifest.json').read_text())
    tokens = preliminary['pair_record']['tokens']
    if tokens not in ((1, 2, 4, 8) if conditional else (2,)):
        return dict(schema='h5-layer7-operand-check/1', status='unknown',
                    reason='only retained T=2 stage layout is supported', end_to_end='unknown')
    m = stages.load_capture(directory, allow_operand_replay=conditional)
    if expected_record is not None and m['pair_record'] != expected_record:
        raise ValueError('pair-specific replay does not match the expected timed record')
    base = json.loads((directory.parent/'capture/manifest.json').read_text())
    d = m['files']['gate.q8_0.bin']['shape'][0]
    f = m['files']['A.gate.bin']['shape'][0]
    if not (32 <= d <= 2560 and d % 32 == 0 and 32 <= f <= 640 and f % 32 == 0):
        return dict(schema='h5-layer7-operand-check/1', status='unknown',
                    reason='unsupported stage dimensions', end_to_end='unknown')
    raw = {name: (directory.parent/'capture'/meta['file']).read_bytes()
           for name, meta in base['tensors'].items()}
    validate_boundary(base, raw, d, m['slot_map'], tokens)
    spec = json.loads((directory.parent/'spec.json').read_text())
    if spec['layer'] != 7 or spec['expert_ids'] != list(stages.HOT):
        raise ValueError('bank layer/expert identity mismatch')
    checks = {}
    model = arithmetic.Arithmetic(helper)
    environment = getattr(model.library, 'l7_environment_ok', None)
    if environment is None or environment() != 1:
        return dict(schema='h5-layer7-operand-check/1', status='unknown', end_to_end='unknown',
                    reason='emulator needs RN rounding with FTZ/DAZ disabled')
    for stage in ('gate', 'up', 'down'):
        meta = m['files'][stage+'.q8_0.bin']
        source = next(t for t in spec['tensors'] if t['source_name'] == meta['source_tensor'])
        if (meta['source_tensor'] != 'blk.7.ffn_'+stage+'_exps.weight' or
                source['compact_sha256'] != meta['sha256'] or
                source['source_sha256'] != meta['source_sha256'] or
                [r['expert_id'] for r in source['ranges']] != list(stages.HOT)):
            raise ValueError('selected bank identity/order mismatch')
    data = {name: stages.floats((directory/name).read_bytes())
            for name in m['files'] if '.q8_0.' not in name}
    if not all(math.isfinite(v) for values in data.values() for v in values):
        raise ValueError('nonfinite stage')
    # load_capture hashes every physical file first. Reuse immutable bytes and
    # finite-scale validation only under that verified content identity.
    bank_cache = {} if bank_cache is None else bank_cache
    banks = {}
    for stage in ('gate', 'up', 'down'):
        identity = m['files'][stage+'.q8_0.bin']['sha256']
        if identity not in bank_cache:
            bank = (directory/(stage+'.q8_0.bin')).read_bytes()
            if not all(math.isfinite(struct.unpack_from('<e', bank, at)[0])
                       for at in range(0, len(bank), 34)):
                raise ValueError('nonfinite bank scale')
            bank_cache[identity] = bank
        bank = banks[stage] = bank_cache[identity]
        if stage != 'down' and tokens == 2:
            checks['A.'+stage] = cpu_projection(model, bank, stages.floats(raw['A.input']),
                data['A.'+stage+'.bin'], m['slot_map'], d, f)
    for arm, slots in (('A', 10), ('B', 5)):
        down = data[arm+'.down.bin']
        weighted = data[arm+'.weighted.bin']
        weights = stages.floats(raw[arm+'.weights' if arm == 'A' else 'B.hot.weights'])
        checks[arm+'.weighting'] = weighting_check(down, weights, weighted, d)
        restored = stages.floats(raw[arm+'.weighted'])
        selected = []
        for token in range(tokens):
            for slot in range(slots):
                entry = next(e for e in m['slot_map'] if e['token'] == token and
                             (e['original_slot'] == slot if arm == 'A' else
                              e['branch'] == 'hot' and e['branch_slot'] == slot))
                at = (token*10+entry['original_slot'])*d
                selected.extend(restored[at:at+d])
        checks[arm+'.restored_planes'] = exact(weighted, selected)
        checks[arm+'.composition'] = composition_check(restored, stages.floats(raw[arm+'.shared']),
                                                       stages.floats(raw[arm+'.output']), d, tokens)
    if conditional:
        module_spec = importlib.util.spec_from_file_location('l7_conditional_mmvq', HERE/'layer7_mmvq_check.py')
        mmvq = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(mmvq)
        for stage in ('gate', 'up', 'down'):
            down = stage == 'down'
            operands = data['B.swiglu.bin'] if down else stages.floats(raw['B.hot.input'])
            checks['B.'+stage] = mmvq.projection(model, banks[stage],
                operands, data['B.'+stage+'.bin'], m['slot_map'], f if down else d,
                d if down else f, tokens, down)
        checks['B.swiglu'] = mmvq.swiglu(data['B.gate.bin'], data['B.up.bin'], data['B.swiglu.bin'], f, tokens)
        av, bv = stages.floats(raw['A.weighted']), stages.floats(raw['B.weighted'])
        ac, bc = [], []
        for e in m['slot_map']:
            if e['branch'] == 'cold':
                at = (e['token']*10+e['original_slot'])*d
                ac.extend(av[at:at+d]); bc.extend(bv[at:at+d])
        checks['B.cold_reference'] = exact(ac, bc)
        checks['B.shared_reference'] = exact(stages.floats(raw['A.shared']), stages.floats(raw['B.shared']))
        sensitive = all(checks['B.'+name].get('sensitive', False) for name in ('gate','up','swiglu','down'))
        sensitive &= all(c['status'] == 'rejected' for arm in ('A','B')
            for c in checks[arm+'.composition'].get('negative_controls', []))
        mismatch = any(c['status'] == 'mismatch' for c in checks.values())
        complete = all(c['status'] == 'match' for c in checks.values())
        binding = replay_binding(directory, m['pair_record'], timed_records)
        return dict(schema='h5-layer7-conditional-check/1', profile=mmvq.PROFILE, assumption=mmvq.ASSUMPTION,
            tokens=tokens, status='mismatch' if mismatch or binding == 'mismatch' else
            'conditional-profile-match' if complete and sensitive and binding == 'match' else 'inconclusive',
            conditional_arithmetic='match' if complete and sensitive else 'mismatch' if mismatch else 'inconclusive',
            timed_binding=binding, sensitive=sensitive, numerical_qualification=False, performance_claim=False,
            checks=checks, legacy_comparator=base['pair_record']['correctness'],
            stage_manifest_sha256=stages.digest((directory/'manifest.json').read_bytes()))
    mismatch = any(c['status'] == 'mismatch' for c in checks.values())
    return dict(schema='h5-layer7-operand-check/1', status='mismatch' if mismatch else 'unknown',
        end_to_end='unknown', numerical_qualification=False, performance_claim=False,
        profile=CPU, checks=checks, selected_pair=m['pair_record'],
        stage_manifest_sha256=stages.digest((directory/'manifest.json').read_bytes()),
        helper_sha256=stages.digest(Path(helper).read_bytes()),
        checker_sha256=stages.digest(Path(__file__).read_bytes()),
        legacy_comparator=base['pair_record']['correctness'],
        unknown=['executed CUDA activation bytes and accepted-worker compiler/instruction contract',
                 'SwiGLU, down projections, cold and shared arithmetic independently from original operands',
                 'same-request device execution attribution; complete coherent stale captures are not detected'],
        control_scope='output omissions relative to retained planes/shared, not independent proof those planes are correct')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--capture', type=Path)
    source.add_argument('--replays', type=Path, help='completed operand-replay benchmark directory')
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--conditional-mmvq', action='store_true')
    parser.add_argument('--timed-records', type=Path, help='retained benchmark stdout.jsonl, required for timed binding')
    args = parser.parse_args()
    result = analyze_replays(args.replays, args.helper) if args.replays else analyze(
        args.capture, args.helper, args.conditional_mmvq, args.timed_records)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: result[k] for k in ('status', 'numerical_qualification') if k in result}))
    # Unknown must never be consumed as successful acceptance by a shell wrapper.
    raise SystemExit(0 if result['status'] == 'conditional-profile-match' else 2 if result['status'] == 'mismatch' else 3)
