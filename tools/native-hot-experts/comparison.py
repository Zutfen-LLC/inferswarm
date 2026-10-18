#!/usr/bin/env python3
"""Frozen #314 PREPARATION/ANALYSIS only. No inference, SSH or process launcher."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from inferswarm.operator.profiles import canonical
from inferswarm.operator.q8_session import response_metrics, validate_session

MODEL_SHA256 = 'a13849d1ad98cff76713f7cd0f650be1217402d79588327815025bd7d42b48d1'
NATIVE_SOURCE = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
BUILD_PAIR = 'hot-experts-candidate-cpu05-cuda03'
WARMUP = 'Complete the sequence with the next word only.\nred red red red'
ORIGINAL = 'Repeat the sequence, separated by spaces, without commentary.\nA B C D A B C D A B C D A B C D'
FACTUAL = 'Extract the city field. Reply with the city only.\nname=Mira; city=Lima; year=2024\ncity:'
TRANSFORM = "Apply Python's sorted() to [3, 1, 2]. Reply only with the JSON array.\nResult:"
DIGEST = re.compile('[0-9a-f]{64}')


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def frozen_session():
    return {'schema': 'q8-two-cuda-session/1', 'requests': [
        {'warmup': i == 0, 'body': {'prompt': prompt, 'n_predict': cap,
          'temperature': 0, 'seed': 42, 'stream': False, 'cache_prompt': False}}
        for i, (prompt, cap) in enumerate(zip(
            (WARMUP, ORIGINAL, FACTUAL, TRANSFORM, ORIGINAL), (8,32,32,32,32)))]}


def validate_frozen_session(session):
    plain = {k: v for k,v in session.items() if k != 'hot_experts'}
    validate_session(plain)
    if canonical(plain) != canonical(frozen_session()):
        raise ValueError('frozen request body/order/settings drift')
    if 'hot_experts' in session:
        hot = session['hot_experts']
        if (not isinstance(hot, dict) or set(hot) != {'enabled','prepared_path','prepared_sha256'}
                or type(hot['enabled']) is not bool
                or not isinstance(hot['prepared_path'], str)
                or not Path(hot['prepared_path']).is_absolute()
                or '..' in Path(hot['prepared_path']).parts
                or not isinstance(hot['prepared_sha256'], str)
                or not DIGEST.fullmatch(hot['prepared_sha256'])):
            raise ValueError('invalid hot_experts prepared-file binding')
    return session


def arm_sessions(prepared_path, prepared_sha256):
    sessions = {}
    for arm, enabled in (('A',False), ('B',True)):
        session = frozen_session()
        session['hot_experts'] = {'enabled': enabled, 'prepared_path': str(prepared_path),
                                  'prepared_sha256': prepared_sha256}
        validate_frozen_session(session)
        sessions[arm] = session
    return sessions


def validate_tokenizer_receipt(receipt, session):
    """Runner prerequisite: actual token IDs, not word counts or estimates.

    The producer must be the admitted model's tokenizer using the exact native
    input preprocessing. This validates retained bindings, not producer honesty.
    Call BEFORE inference for each arm's full frozen session; never tokenize by
    issuing a completion or silently substitute another tokenizer.
    """
    validate_frozen_session(session)
    if not isinstance(receipt, dict) or receipt.get('schema') != 'is314-tokenizer-receipt/1':
        raise ValueError('actual model tokenizer receipt required before inference')
    tokenizer = receipt.get('tokenizer', {})
    if (receipt.get('model_sha256') != MODEL_SHA256
            or receipt.get('session_sha256') != sha(canonical(session))
            or tokenizer.get('source_revision') != NATIVE_SOURCE
            or not isinstance(tokenizer.get('executable_sha256'), str)
            or not DIGEST.fullmatch(tokenizer['executable_sha256'])
            or tokenizer.get('actual_model_input') is not True
            or tokenizer.get('add_special') is not True
            or tokenizer.get('parse_special') is not True):
        raise ValueError('tokenizer model/session/source/settings binding mismatch')
    rows = receipt.get('requests')
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError('tokenizer must retain every actual request tokenization')
    counts = []
    for index, (row, request) in enumerate(zip(rows, session['requests']), 1):
        if (not isinstance(row, dict) or set(row) != {'index','body_sha256','token_ids'}
                or type(row['index']) is not int or row['index'] != index
                or row['body_sha256'] != sha(canonical(request['body']))):
            raise ValueError('tokenizer request body/index binding mismatch')
        ids = row['token_ids']
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 128
                or any(type(i) is not int or i < 0 for i in ids)):
            raise ValueError('actual tokenizer input must contain 1..128 model token IDs')
        counts.append(len(ids))
    return counts


def semantic_check(index, content):
    if type(index) is not int or not 1 <= index <= 5 or not isinstance(content, str):
        raise ValueError('semantic check requires frozen request index and text')
    if index == 1:
        # Original recipe only records warmup completion; no warmup acceptance.
        return {'pass': bool(content.strip()), 'scope': 'warmup completion only; not semantic acceptance'}
    if index in (2,5):
        words = content.split()
        ok = len(words) >= 4 and all(word == 'ABCD'[i % 4] for i,word in enumerate(words))
        return {'pass': ok, 'check': 'ABCD prefix and entire whitespace-token cycle',
                'checked_words': len(words)}
    if index == 3:
        return {'pass': content.strip() == 'Lima', 'check': 'entire trimmed answer equals Lima'}
    try:
        value = json.loads(content)
        ok = (isinstance(value, list) and value == [1,2,3]
              and all(type(item) is int for item in value))
    except (ValueError, TypeError):
        ok = False
    return {'pass': ok, 'check': 'entire response parses as integer JSON array [1,2,3]'}


def numerical_diagnostic(reference, candidate):
    """Fixed diagnostic metrics, deliberately NOT a fitted heterogeneous tolerance."""
    if (not reference or len(reference) != len(candidate)
            or any(type(v) not in (float,int) or not math.isfinite(v)
                   for v in (*reference,*candidate))):
        raise ValueError('numerical operands must be nonempty, finite and shape-aligned')
    delta = [abs(a-b) for a,b in zip(reference,candidate)]
    error = math.sqrt(math.fsum(d*d for d in delta))
    norm_a = math.sqrt(math.fsum(a*a for a in reference))
    norm_b = math.sqrt(math.fsum(b*b for b in candidate))
    return {'finite': True, 'max_abs': max(delta), 'rms': error/math.sqrt(len(delta)),
            'relative_l2': error/norm_a if norm_a else (0.0 if error == 0 else None),
            'cosine': math.fsum(a*b for a,b in zip(reference,candidate))/(norm_a*norm_b)
                      if norm_a and norm_b else None,
            'verdict': 'DIAGNOSTIC-NOT-QUALIFICATION',
            'tolerance': None, 'bitwise_equality_required': False}


def compare_numeric_captures(reference, candidate):
    """Read retained IS309 input/output ABI, not a new exporter or profiling run."""
    spec = importlib.util.spec_from_file_location('is314_capture_reader',
                 ROOT / 'tools/native-moe-overlap/compare.py')
    if spec is None or spec.loader is None:
        raise ValueError('retained numerical capture reader unavailable')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    a, b = reader.records(reference), reader.records(candidate)
    if len(a) != len(b):
        raise ValueError('numerical record count mismatch')
    rows = []
    for left, right in zip(a,b):
        if left[0] != right[0] or left[0][0] != 7:
            raise ValueError('numerical layer/shape/step mismatch')
        numerical_diagnostic(left[1], right[1])
        if left[1] != right[1]:
            raise ValueError('same-input numerical comparison requires identical actual inputs')
        rows.append({'shape_step': list(left[0]),
                     'output': numerical_diagnostic(left[2], right[2])})
    return {'schema': 'is314-numerical-diagnostic/1', 'records': rows,
            'reference_sha256': sha(Path(reference).read_bytes()),
            'candidate_sha256': sha(Path(candidate).read_bytes()),
            'verdict': 'DIAGNOSTIC-NOT-QUALIFICATION', 'output_accepted': False}


def validate_config_pair(a, b):
    """Compare frozen configs, allowing only fresh plan/lifecycle ownership names.

    This is content equivalence, not promotion of a candidate build identity.
    Actual config/metadata parsing, runtime review and envelope admission remain
    owned by the existing runner and fail closed if any receipt is absent.
    """
    normalized = []
    for config in (a,b):
        value = json.loads(canonical(config))
        options = value['strategy_options']
        work = value['workload']
        if (value.get('selection') != 'two-gpu' or options.get('build_pair') != BUILD_PAIR
                or 'placement_variant' in options or sha(canonical(value['model'])) != MODEL_SHA256
                or any(work.get(k) != v for k,v in
                       {'context':2048,'batch':128,'microbatch':32,'slots':1}.items())):
            raise ValueError('frozen model/candidate-pair/41-45/workload config drift')
        value.pop('plan_id',None)
        for part in value['participants']:
            part.pop('lifecycle_dir',None)
        normalized.append(value)
    if canonical(normalized[0]) != canonical(normalized[1]):
        raise ValueError('material arm config settings differ beyond plan/lifecycle names')
    return {'materially_equal':True,'normalized_sha256':sha(canonical(normalized[0])),
            'ignored_fields':['plan_id','participants[*].lifecycle_dir'],
            'candidate_identity_reviewed':False}


def prepare_plan(*, prepared_path=None, config_a=None, config_b=None):
    """Archive constraints without manufacturing future build or token identities."""
    session = json.loads((HERE / 'frozen-requests.json').read_bytes())
    validate_frozen_session(session)
    capture = json.loads((HERE / 'capture-provenance.json').read_bytes())
    plan = {'schema': 'is314-comparison-plan/1', 'stage': 'PREPARATION-ONLY',
        'execution_authorized': False, 'arm_order': ['A','B'], 'retries': 0,
        'max_loads_per_arm': 1, 'request_count_per_arm': 5,
        'build_pair': BUILD_PAIR, 'candidate_identity': 'PENDING-REAL05-BUILD-AND-REVIEW-PROMOTION',
        'tokenizer_status': 'PENDING-ACTUAL-MODEL-TOKENIZATION',
        'model_sha256': MODEL_SHA256, 'native_source': NATIVE_SOURCE,
        'budget': {'total_seconds': 10800, 'execution_stop_seconds': 9600,
                   'cleanup_seconds': 1200, 'one_shared_outer_clock': True,
                   'coordinator_memory_max_bytes': 118111600640,
                   'aggregate_worker_memory_max_bytes': 10737418240,
                   'owned_swap_max_bytes': 0, 'coordinator_mem_available_floor_bytes': 8589934592,
                   'worker_mem_available_floor_bytes': 4294967296,
                   'per_gpu_reserve_bytes': 536870912,
                   'relevant_volume_free_floor_bytes': 68719476736},
        'native_activation': {'environment': 'IS314_HOT_SPEC', 'A': 'unset',
                              'B': 'runner-staged authenticated native spec; existing RPC0 only'},
        'fixed_runtime': {'placement': '41/45', 'gpu_layers': 8, 'tensor_split': [4,4],
            'devices': ['RPC0','RPC1'], 'hot_layer': 7, 'expert_ids': [54,74,136,290,394],
            'context': 2048, 'batch': 128, 'microbatch': 32, 'parallel': 1,
            'cache_type_k': 'f16', 'cache_type_v': 'f16', 'kv_offload': True,
            'op_offload': False, 'flash_attention': 'off', 'kv_unified': False,
            'fit': 'off', 'lazy_mode': 'on', 'load_mode': 'none',
            'threads': 'same explicitly frozen native thread setting in both arms; do not use profiling 28 as ordinary 14'},
        'request_semantics': [semantic_check(i, '')['check'] if i > 1 else
                              'warmup completion only' for i in range(1,6)],
        'numerical_contract': {'metric': 'finite, max_abs, RMS, relative_L2, cosine on aligned same-input layer7 records',
            'tolerance': None, 'verdict': 'diagnostic only; no heterogeneous bitwise equality or numerical acceptance',
            'independent_reference': 'tools/moe-overlap/numerical-reference.md moe-operand-reference/2 only with all independently reconstructed operands/plane mass; otherwise NOT-EVALUATED'},
        'source_hashes': {}, 'historical_config_sha256': capture['members']['config.json']['sha256'],
        'sessions': {}, 'blockers': ['no hardware authority in this plan',
            'reviewed candidate identity receipt deliberately absent before real05 build and promotion',
            'actual model tokenizer receipts required by runner before every arm inference',
            'current config/envelope/source/backing/topology hashes and shared spanning enforcement required']}
    for path in (Path(__file__).resolve(), HERE/'provenance.py', HERE/'frozen-requests.json',
                 HERE/'capture-provenance.json', HERE/'comparison-recipe.md',
                 ROOT/'inferswarm/operator/q8_session.py', ROOT/'inferswarm/operator/q8_experiment.py',
                 ROOT/'inferswarm/operator/q8_demand.py', ROOT/'inferswarm/operator/runtime.py',
                 ROOT/'inferswarm/operator/hot_experts.py', ROOT/'inferswarm/operator/hot_experiment.py',
                 HERE/'example-manifest.json', ROOT/'tools/native-moe-overlap/hot-build-composed.py',
                 ROOT/'tools/native-moe-overlap/compare.py',
                 ROOT/'tools/moe-overlap/numerical-reference.md'):
        plan['source_hashes'][str(path.relative_to(ROOT))] = sha(path.read_bytes())
    if (config_a is None) != (config_b is None):
        raise ValueError('both arm config files are required together')
    plan['arm_configs'] = {}
    if config_a is not None and config_b is not None:
        paths = {'A':Path(config_a), 'B':Path(config_b)}
        blobs = {arm:path.read_bytes() for arm,path in paths.items()}
        plan['config_equivalence'] = validate_config_pair(json.loads(blobs['A']),json.loads(blobs['B']))
        plan['arm_configs'] = {arm:{'path':str(paths[arm].resolve()), 'sha256':sha(blob)}
                               for arm,blob in blobs.items()}
    else:
        plan['blockers'].append('current arm configs not yet frozen or compared')
    if prepared_path is not None:
        path = Path(prepared_path)
        if not path.is_absolute() or not path.is_file():
            raise ValueError('prepared path must name an existing absolute controller JSON file')
        # Runtime/preparation API owns prepared-artifact semantic validation.
        json.loads(path.read_bytes())
        for arm, arm_session in arm_sessions(path, sha(path.read_bytes())).items():
            plan['sessions'][arm] = {'body': arm_session, 'request_sha256': sha(canonical(arm_session))}
    else:
        plan['blockers'].append('no immutable prepared artifact supplied; arm sessions not yet bound')
    return plan


def analyze_arm(root):
    root = Path(root)
    path = root/'session-report.json'
    try:
        report = json.loads(path.read_bytes())
        session = validate_frozen_session(report['frozen_session'])
        if report['session_sha256'] != sha(canonical(session)):
            raise ValueError('retained full session digest mismatch')
        planned = session['requests']
        rows = report['requests']
        if len(rows) != 5 or set(p.name for p in root.glob('request-*-response.json')) != {
                f'request-{i:02d}-response.json' for i in range(1,6)}:
            raise ValueError('require exactly five retained request responses; no retry or extras')
        results = []
        for i, (row, frozen) in enumerate(zip(rows,planned),1):
            body = frozen['body']
            if (row.get('index') != i or row.get('warmup') is not frozen['warmup']
                    or canonical(row.get('body')) != canonical(body)
                    or row.get('request_sha256') != sha(canonical(body))
                    or row.get('status') != 'COMPLETED'):
                raise ValueError('retained request body/order/status drift')
            response_path = root/f'request-{i:02d}-response.json'
            raw = response_path.read_bytes()
            response = json.loads(raw)
            if (not isinstance(response.get('content'), str) or not response['content'].strip()
                    or response.get('stop') is not True or response.get('truncated') is True):
                raise ValueError('empty, malformed, incomplete or context-truncated response')
            metrics = response_metrics(response)
            for value in (response.get('tokens_predicted'), metrics.get('predicted_n')):
                if value is not None and (type(value) is not int or not 0 < value <= body['n_predict']):
                    raise ValueError('retained generated-token cap drift')
            settings = response.get('generation_settings', {})
            for key in ('n_predict','max_tokens'):
                if key in settings and settings[key] != body['n_predict']:
                    raise ValueError('retained generation settings drift')
            results.append({'index': i, 'warmup': frozen['warmup'],
                'body_sha256': sha(canonical(body)), 'response_sha256': sha(raw),
                'finish_reason': response.get('stop_type'), 'wall_seconds': row.get('wall_seconds'),
                'metrics': metrics, 'semantic': semantic_check(i,response['content']),
                'cache_n': metrics.get('cache_n')})
        outcomes = report.get('outcomes', {})
        return {'session_sha256': report['session_sha256'],
                'hot_experts': session.get('hot_experts'),
                'report_sha256': sha(path.read_bytes()), 'requests': results,
                'execution': outcomes.get('execution'), 'observer': outcomes.get('observer'),
                'cleanup': outcomes.get('cleanup'), 'setup': report.get('setup'),
                'samples': report.get('samples'), 'output_accepted': False, 'physical_qualified': False}
    except (OSError, KeyError, TypeError) as error:
        raise ValueError(f'incomplete/malformed retained arm: {error}') from error


def compare_arms(a_root, b_root):
    a, b = analyze_arm(a_root), analyze_arm(b_root)
    ah, bh = a['hot_experts'], b['hot_experts']
    if (not ah or not bh or ah['enabled'] is not False or bh['enabled'] is not True
            or {k:v for k,v in ah.items() if k != 'enabled'} !=
               {k:v for k,v in bh.items() if k != 'enabled'}):
        raise ValueError('A disabled then B enabled must bind the same prepared artifact')
    pairs = []
    for left,right in zip(a['requests'][1:], b['requests'][1:]):
        x,y = left['wall_seconds'],right['wall_seconds']
        ratio = y/x if (type(x) in (int,float) and type(y) in (int,float)
                       and math.isfinite(x) and math.isfinite(y) and x > 0 and y >= 0) else None
        pairs.append({'index':left['index'], 'wall_ratio_b_over_a':ratio,
                      'native_a': left['metrics'], 'native_b': right['metrics']})
    return {'schema':'is314-comparison-analysis/1','arms':{'A':a,'B':b},
            'paired_requests':pairs,
            'semantic_pass':all(row['semantic']['pass'] for arm in (a,b) for row in arm['requests']),
            'numerical':{'verdict':'NOT-CAPTURED'},
            'context_equivalence':'NOT-VERIFIED-BY-RESPONSE-ONLY-ANALYSIS; join frozen config/build/source/outer-guard receipts',
            'scope':'single A-then-B screening, no-gain is valid; not statistical speedup',
            'output_accepted':False,'physical_qualified':False}


def freeze_clock(path):
    import time
    record=dict(schema='is314-shared-clock/1',host=os.uname().nodename,
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        started_monotonic=time.monotonic(),total_seconds=10800,
        execution_stop_seconds=9600,cleanup_seconds=1200)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(canonical(record)+b'\n'); stream.flush(); os.fsync(stream.fileno())
    return record


def check_clock(path, *, now=None):
    import time
    record=json.loads(Path(path).read_bytes())
    if (record.get('schema')!='is314-shared-clock/1' or record.get('host')!=os.uname().nodename
            or record.get('boot_id')!=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            or [record.get(k) for k in ('total_seconds','execution_stop_seconds','cleanup_seconds')]
                !=[10800,9600,1200]):
        raise ValueError('shared clock host/boot/budget mismatch')
    started=record.get('started_monotonic')
    now=time.monotonic() if now is None else now
    if type(started) not in (int,float) or not math.isfinite(started) or not 0<=started<=now:
        raise ValueError('invalid shared outer start')
    if now>=started+9600:
        raise TimeoutError('shared 160-minute execution STOP reached; cleanup only')
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='archive private offline plan; never launch')
    prep.add_argument('--output',required=True,type=Path)
    prep.add_argument('--prepared',type=Path)
    prep.add_argument('--config-a',type=Path)
    prep.add_argument('--config-b',type=Path)
    admit = commands.add_parser('validate-tokenizer', help='refuse missing/oversized actual input tokens')
    admit.add_argument('--session',required=True,type=Path)
    admit.add_argument('--receipt',required=True,type=Path)
    analysis = commands.add_parser('compare',help='analyze two retained guarded-runner evidence roots')
    analysis.add_argument('--a',required=True,type=Path)
    analysis.add_argument('--b',required=True,type=Path)
    numerical = commands.add_parser('numerical',help='diagnose retained same-input layer7 binary captures')
    numerical.add_argument('--reference',required=True,type=Path)
    numerical.add_argument('--candidate',required=True,type=Path)
    gather=commands.add_parser('gather',help='hash exact encoded slices; no model load or inference')
    gather.add_argument('--manifest',required=True,type=Path)
    gather.add_argument('--manifest-sha256',required=True)
    gather.add_argument('--source',required=True,action='append',help='exact member basename=local path')
    gather.add_argument('--rpc-endpoint',required=True)
    gather.add_argument('--clock',required=True,type=Path)
    gather.add_argument('--output',required=True,type=Path)
    clock=commands.add_parser('clock',help='freeze/check one shared controller clock; never launch')
    clock.add_argument('--output',type=Path)
    clock.add_argument('--check',type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'gather':
            from inferswarm.operator.hot_experts import load_manifest,prepare
            check_clock(args.clock)
            if os.path.lexists(args.output):
                raise ValueError('prepared output already exists')
            paths={}
            for item in args.source:
                name,sep,path=item.partition('=')
                if not sep or not name or not path or name in paths:
                    raise ValueError('unique member=path sources required')
                paths[name]=path
            with args.manifest.open('rb') as stream:
                manifest=load_manifest(stream.read(1048577),expected_sha256=args.manifest_sha256)
            prepared=prepare(manifest,paths,rpc_backend='RPC['+args.rpc_endpoint+']',
                             checkpoint=lambda:check_clock(args.clock))
            check_clock(args.clock)
            fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(prepared.canonical_bytes);stream.flush();os.fsync(stream.fileno())
            result=dict(prepared_sha256=sha(prepared.canonical_bytes),report=prepared.report(),
                        execution_authorized=False)
        elif args.command == 'clock':
            if bool(args.output)==bool(args.check):
                raise ValueError('clock requires exactly one of --output or --check')
            result=freeze_clock(args.output) if args.output else check_clock(args.check)
        elif args.command == 'prepare':
            plan = prepare_plan(prepared_path=args.prepared,config_a=args.config_a,config_b=args.config_b)
            args.output.mkdir(mode=0o700, parents=False)
            files = {'plan.json':canonical(plan)+b'\n',
                     'frozen-requests.json':canonical(frozen_session())+b'\n'}
            for arm,item in plan['arm_configs'].items():
                blob = Path(item['path']).read_bytes()
                if sha(blob) != item['sha256']:
                    raise ValueError('arm config changed while archiving plan')
                files[f'config-{arm}.json'] = blob
            for arm, item in plan['sessions'].items():
                files[f'session-{arm}.json'] = canonical(item['body'])+b'\n'
            for name,blob in files.items():
                fd = os.open(args.output/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as output: output.write(blob)
            result = {'stage':plan['stage'],'execution_authorized':False,
                      'plan_sha256':sha(files['plan.json']),'blockers':plan['blockers']}
        elif args.command == 'validate-tokenizer':
            counts = validate_tokenizer_receipt(json.loads(args.receipt.read_bytes()),
                                                json.loads(args.session.read_bytes()))
            result = {'status':'TOKEN-BOUND-ONLY','actual_input_tokens':counts,
                      'execution_authorized':False,'receipt_sha256':sha(args.receipt.read_bytes())}
        elif args.command == 'numerical':
            result = compare_numeric_captures(args.reference,args.candidate)
        else:
            result = compare_arms(args.a,args.b)
        print(json.dumps(result,sort_keys=True,indent=2,allow_nan=False))
        return 1 if result.get('semantic_pass') is False else 0
    except (ValueError,OSError,KeyError,TypeError,TimeoutError) as error:
        parser.exit(1,f'comparison refused: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
