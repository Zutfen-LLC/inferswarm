#!/usr/bin/env python3
"""External #268 continuation; dry-run by default, at most requests 2 and 3.

No observer, product, first receipt or original STOP ledger is rewritten.
The live authority recheck and independent reviews are controller prerequisites.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PHYSICAL = ROOT / 'physical-478eb5ef'
CONFIG = ROOT / 'physical-operator-config.json'
OBSERVER = ROOT / 'acceptance-observer.py'
HEAD = '478eb5efc93476dc2be990ac738c7ddd40e11eab'
OBSERVER_SHA = '9a38a94ed9666615e37ebb46912b9bf558aba6e07e041d2466bd859ab6bfb72b'
OBSERVER_TEST_SHA = '83bf01989b8ee78a0cb7f8821c5052cadf5457484c7facf3ae36b7ad3251b551'
FIRST_HASHES = {
    'invocation-01/receipt.json': '3cf83336ef482f643aa7a5bb1a93c18b2bf8627624bee94af402ee81c7b1cad3',
    'invocation-01/remote-rpc.log': '8cc860ade606da920484c25a931dc8d607e15ca8cbce58b9bf2bf67ea07fbd3d',
    'invocation-01/remote-cache-strace.log': 'f013d36e07688e2378f7226684bb65165241e2425a54bbbc3580b6900d52ca0a',
    'invocation-01/client-client.log': '4ce6cd10657169f13c6c42a6b098898eee3d294c6b96cf590f1b471097bed18b',
    'physical.json': '40279d7c82322935e79c59481a692c1da7a32bf633cd46ab8cc86e5d3cbd06a5',
}
GRAPH = b'ggml_backend_cuda_graph_compute: CUDA graph warmup complete'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_observer():
    if digest(OBSERVER) != OBSERVER_SHA or digest(ROOT / 'test_acceptance_observer.py') != OBSERVER_TEST_SHA:
        raise ValueError('approved observer bytes changed')
    spec = importlib.util.spec_from_file_location('approved_acceptance_observer', OBSERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_hashes(observer, config_path):
    sources = {str(p.relative_to(observer.REPO)): digest(p)
               for p in sorted((observer.REPO / 'inferswarm/operator').glob('*.py'))}
    sources[str(config_path)] = digest(config_path)
    return sources


def check_log_snapshots(rows, raw):
    """Remote bytes must be a complete, contiguous reproduction of retained chunks."""
    if not rows or rows[0]['start_offset'] != 0 or rows[-1]['end_offset'] != len(raw):
        raise ValueError('remote log snapshot incomplete')
    last = 0
    for row in rows:
        start, end = row['start_offset'], row['end_offset']
        bounds = row['clock_bounds']
        if (start != last or end <= start or bounds['remote']['offset'] != start or
                base64.b64decode(bounds['remote']['data_b64'], validate=True) != raw[start:end] or
                not bounds['remote']['eof']):
            raise ValueError('remote log snapshot bytes/offsets differ')
        last = end


def authentic_raw_samples(observer, window, roles, samples, config):
    """Re-derive owned in-window raw pmon/inventory for either SM=0 or positive."""
    authenticated = []
    physical = config['backend_options']['rpc_physical_device']
    for sample in samples:
        role = sample.get('role')
        if role not in roles or type(sample.get('sm')) is not int or sample['sm'] < 0:
            continue
        owned = roles[role]
        if not observer.owned_identity(owned, sample):
            continue
        remote = sample.get('clock_bounds', {}).get('remote', {})
        line = sample.get('raw_pmon_line')
        fields = line.split() if isinstance(line, str) else []
        mapping = sample.get('device_mapping', {})
        try:
            inventory = observer.parse_gpu_inventory(sample['gpu_inventory_raw'])
        except (ValueError, TypeError, KeyError):
            continue
        device = 'CUDA0' if role == 'client' else physical
        if (len(fields) < 5 or not fields[0].isdigit() or not fields[1].isdigit() or
                not fields[3].isdigit() or int(fields[0]) != sample.get('gpu_index') or
                int(fields[1]) != owned['pid'] or int(fields[3]) != sample['sm'] or
                line not in remote.get('pmon', '').splitlines() or
                remote.get('pmon_exit') != 0 or remote.get('gpu_inventory_exit') != 0 or
                remote.get('identity_before') != owned['start'] or
                remote.get('identity') != owned['start'] or
                remote.get('identity_after') != owned['start'] or
                remote.get('gpu_inventory_raw') != sample['gpu_inventory_raw'] or
                sample.get('inventory_authentic') is not True or
                mapping.get('inventory') != inventory or
                mapping != observer.resolve_device(device, remote.get('cuda_environment', {}), inventory) or
                mapping.get('logical_device') != device or
                type(sample.get('gpu_index')) is not int or
                mapping.get('physical_index') != sample['gpu_index'] or
                sample.get('before_mono_ns') != sample.get('clock_bounds', {}).get('local_before', {}).get('mono_ns') or
                sample.get('after_mono_ns') != sample.get('clock_bounds', {}).get('local_after', {}).get('mono_ns') or
                sample.get('identity_before') != owned['start'] or
                sample.get('identity_after') != owned['start'] or
                sample.get('identity_observed') != owned['start'] or
                sample.get('probe_status') != 0 or sample.get('gpu_inventory_exit') != 0 or
                not (window['start_mono_ns'] <= sample.get('before_mono_ns', -1) <=
                     sample.get('after_mono_ns', 10**30) <= window['end_mono_ns'])):
            continue
        authenticated.append(sample)
    return authenticated


def check_request_log_clocks(before, after, window):
    """Bound the untimestamped delta by nearby, ordered request snapshots."""
    second = 1_000_000_000
    for row in (before, after):
        bounds = row['clock_bounds']
        start, end = bounds['local_before'], bounds['local_after']
        remote = bounds['remote']
        rstart, rend = remote['clock_start'], remote['clock_end']
        if (any(type(v) is not int or v <= 0 for v in (
                start['mono_ns'], end['mono_ns'], start['wall_ns'], end['wall_ns'],
                rstart['remote_mono_ns'], rend['remote_mono_ns'],
                rstart['remote_wall_ns'], rend['remote_wall_ns'])) or
                start['mono_ns'] > end['mono_ns'] or start['wall_ns'] > end['wall_ns'] or
                rstart['remote_mono_ns'] > rend['remote_mono_ns'] or
                not (start['wall_ns'] <= rstart['remote_wall_ns'] <=
                     rend['remote_wall_ns'] <= end['wall_ns'])):
            raise ValueError('request clock/snapshot bounds invalid')
    b = before['clock_bounds']['local_after']
    a0, a1 = after['clock_bounds']['local_before'], after['clock_bounds']['local_after']
    if (before['end_offset'] != after['start_offset'] or
            any(type(window[k]) is not int for k in
                ('start_mono_ns', 'end_mono_ns', 'start_wall_ns', 'end_wall_ns')) or
            not (window['start_mono_ns'] < window['end_mono_ns'] and
                 window['start_wall_ns'] < window['end_wall_ns']) or
            not (window['start_mono_ns'] - second <= b['mono_ns'] < window['start_mono_ns']) or
            not (window['start_wall_ns'] - second <= b['wall_ns'] < window['start_wall_ns']) or
            not (window['end_mono_ns'] <= a0['mono_ns'] <= window['end_mono_ns'] + second) or
            not (window['end_wall_ns'] <= a0['wall_ns'] <= window['end_wall_ns'] + second) or
            not (a0['mono_ns'] <= a1['mono_ns'] <= window['end_mono_ns'] + 2 * second) or
            not (a0['wall_ns'] <= a1['wall_ns'] <= window['end_wall_ns'] + 2 * second)):
        raise ValueError('request clock/snapshot bounds invalid')


def evaluate(report, remote_log, trace, config):
    """Pure per-request decision; an inconclusive pmon is never rewritten."""
    observer = approved_observer()
    original = observer.acceptance_readiness(report)
    result = {'observer_readiness': original, 'status': 'STOP-evidence-gap',
              'remote_gpu_evidence': 'unproven',
              'caveat': 'pmon is sampled, not kernel tracing; untimestamped log lines are bounded by snapshots; startup cache opens do not prove full byte reads'}
    try:
        if report['cli_exit'] != 0 or report['telemetry_errors'] or not report['cleanup_exact_absence']:
            raise ValueError('CLI/telemetry/cleanup failed')
        if len(report['request_windows']) != 1:
            raise ValueError('not exactly one request')
        win = report['request_windows'][0]
        if not win.get('response_id') or not (win['start_mono_ns'] < win['end_mono_ns']):
            raise ValueError('request identity/clock missing')
        roles = report['roles']
        if set(roles) != {'remote', 'client'} or roles['remote']['token'] != roles['client']['token']:
            raise ValueError('owned roles/token missing')
        if any(not all(role.get(k) for k in ('pid', 'start', 'token')) for role in roles.values()):
            raise ValueError('owned identity incomplete')
        parts = {p['role']: p for p in config['participants']}
        if set(parts) != set(roles): raise ValueError('participant roles differ')
        if report['operator_argv'] != ['python', '-m', 'inferswarm.operator', 'run', '--config', str(CONFIG)]:
            raise ValueError('not approved ordinary CLI/config')
        product = json.loads(report['cli_stdout'].strip())
        backing = product['verified_backing']['remote']
        if (report['cli_stderr'].strip() or product['response_id'] != win['response_id'] or
                not product['text'].strip() or product['finish_reason'] != 'stop' or
                not isinstance(product.get('tokens'), int) or product['tokens'] <= 0 or
                backing['backing'] != 'participant-local-cache-verified-not-yet-observed-consumed' or
                backing['eligible_cache_reads'] < 1 or
                not product['observed_placement']['layers'] or
                not all(v.get('lease') == 'released' for v in product['cleanup'].values())):
            raise ValueError('CLI product receipt incomplete')
        placement = product['observed_placement']
        expected = {}
        for item in config['placement']:
            part = next(p for p in parts.values() if p['compute_id'] == item['compute_id'])
            device = 'CPU' if item['unit_id'] == 'client-cpu-prefix' else ('RPC0' if part['role'] == 'remote' else 'CUDA0')
            expected.update({str(i): device for i in range(item['first_layer'], item['last_layer'] + 1)})
            if item['output']: expected[str(max(int(x) for x in expected) + 1)] = device
        if placement['layers'] != expected or 'CUDA0' not in expected.values() or 'RPC0' not in expected.values():
            raise ValueError('observed placement differs')
        for role, name in (('remote', 'rpc'), ('client', 'client')):
            part = parts[role]; owned = roles[role]; host = part['execution_address']
            row = report['cleanup_readback'][host][name]
            if (row['recorded'] != owned or row['identity'] is not None or row['listener'] is not False or
                    report['cleanup'][host]['lease'] != 'released'):
                raise ValueError('owned cleanup readback mismatch')
            spawns = [e for e in report['events'] if e['event'] == 'lifecycle-result' and
                      e.get('action') == 'spawn' and e.get('host') == host and e.get('name') == name and
                      e.get('result') == owned and e['clock']['mono_ns'] < win['start_mono_ns']]
            if len(spawns) != 1: raise ValueError('spawn identity not bound to request')
        collector = report['collector_cleanup']['remote']
        if (collector['status'] not in ('stopped', 'recycled-or-absent') or collector['members'] or
                collector['recorded'] != report['collector_identity'] or
                collector['recorded']['token'] != roles['remote']['token'] or
                collector.get('identity') is not None):
            raise ValueError('collector unresolved')
        keys = {c['cache_key'] for c in parts['remote']['cache_ranges']}
        opens = report['startup_cache_open_lines']
        if (not opens or len(opens) != report['startup_cache_open_count'] or
                not all(line.encode() in trace and observer.cache_open(line, parts['remote']['cache_path'],
                    keys, roles['remote']['pid']) for line in opens)):
            raise ValueError('authentic owned remote startup cache opens absent')
        trace_lines = trace.decode('utf-8', 'replace').splitlines(True)
        for line in opens:
            if line not in trace_lines: raise ValueError('startup trace line not byte-identical')
            timestamp = re.match(r'^\[pid\s+\d+\]\s+(\d+\.\d{6})\s+', line)
            if not timestamp:
                raise ValueError('startup trace clock missing')
            seconds, micros = timestamp.group(1).split('.')
            if int(seconds) * 1_000_000_000 + int(micros) * 1000 >= win['start_wall_ns']:
                raise ValueError('startup cache open is not strictly before request')
        rows = report['logs']['remote-rpc']
        check_log_snapshots(rows, remote_log)
        authenticated = authentic_raw_samples(observer, win, roles, report['host_samples'], config)
        positive = observer.request_gpu_evidence(win, roles, authenticated)
        if positive['status'] == 'positive-pid-sm-samples':
            result.update(status='evidence-ready-for-human-review',
                          remote_gpu_evidence='positive-owned-pid-sm-samples',
                          matched_samples_per_role=positive['matched_samples_per_role'])
            return result
        if original not in ('inconclusive-pid-gpu-sampling', 'evidence-ready-for-human-review'):
            raise ValueError('observer found another evidence gap')
        if positive['matched_samples_per_role']['client'] <= 0:
            raise ValueError('authenticated in-window client raw pmon sample absent')
        remote = [s for s in authenticated if s['role'] == 'remote']
        if not remote: raise ValueError('authenticated in-window remote role absent')
        before = [r for r in rows if r['phase'] == 'before-request']
        after = [r for r in rows if r['phase'] == 'after-request']
        if len(before) != 1 or len(after) != 1:
            raise ValueError('request clock/snapshot bounds invalid')
        check_request_log_clocks(before[0], after[0], win)
        delta = remote_log[after[0]['start_offset']:after[0]['end_offset']]
        if not any(line == GRAPH for line in delta.splitlines()):
            raise ValueError('no request-bound CUDA backend graph computation log')
        result.update(status='evidence-ready-for-human-review',
                      remote_gpu_evidence='owned-request-bound-cuda-graph-snapshot',
                      graph_line_count=sum(line == GRAPH for line in delta.splitlines()),
                      remote_snapshot_offsets=[after[0]['start_offset'], after[0]['end_offset']])
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError) as exc:
        result['reason'] = str(exc)
    return result


def verify_first(root):
    if not root.is_dir() or sorted(p.name for p in root.glob('invocation-*')) != ['invocation-01']:
        raise ValueError('request inventory is not exactly invocation-01')
    for name, expected in FIRST_HASHES.items():
        if digest(root / name) != expected: raise ValueError('first raw/ledger hash mismatch: ' + name)
    first = json.loads((root / 'physical.json').read_text())
    receipt = json.loads((root / 'invocation-01/receipt.json').read_text())
    item = first['invocations']
    if (first['product_head'] != HEAD or first['status'] != 'INCOMPLETE' or len(item) != 1 or
            item[0]['index'] != 1 or item[0]['readiness'] != 'inconclusive-pid-gpu-sampling' or
            item[0]['request_windows'] != receipt['request_windows'] or
            item[0]['cli_exit'] != receipt['cli_exit'] or
            receipt['request_windows'][0]['response_id'] !=
            'chatcmpl-GuBRCJgLyah2hQy0GRmHwfq8xwvpIe84'):
        raise ValueError('first ledger/receipt request identity inconsistent')
    return receipt


def reserve(root, ledger, metadata):
    if ledger.exists() or sorted(p.name for p in root.glob('invocation-*')) != ['invocation-01']:
        raise ValueError('continuation replay/partial/existing request: refuse')
    # O_EXCL is durable admission: never delete it after a failure or successful completion.
    try:
        fd = os.open(ledger, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError('continuation admission already consumed') from exc
    with os.fdopen(fd, 'w') as f:
        json.dump({'status': 'ADMITTED-NOT-STARTED', 'remaining_indices': [2, 3],
                   'attempted_indices': [], 'metadata': metadata}, f, indent=2, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    fd = os.open(ledger.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def update_ledger(path, record):
    temp = path.with_name(path.name + '.new')
    with temp.open('x') as f:
        json.dump(record, f, indent=2, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def verify_reviews(root):
    # Future independent approvals have fixed names; historical failures remain untouched.
    spec = json.loads((root / 'task4-continuation-spec-review-round4.json').read_text())
    quality = json.loads((root / 'task4-continuation-quality-review-round2.json').read_text())
    first_spec = json.loads((root / 'task4-invocation1-spec-adjudication.json').read_text())
    first_quality = json.loads((root / 'task4-invocation1-quality-adjudication.json').read_text())
    for record, verdict in ((spec, 'PASS'), (quality, 'APPROVED')):
        if (record['verdict'] != verdict or record['product_head'] != HEAD or
                record['wrapper_sha256'] != digest(Path(__file__)) or
                record['tests_sha256'] != digest(root / 'test_continue_ordinary_acceptance.py')):
            raise ValueError('independent continuation review mismatch')
    receipt = json.loads((PHYSICAL / 'invocation-01/receipt.json').read_text())
    response_id = receipt['request_windows'][0]['response_id']
    token = receipt['roles']['remote']['token']
    for name, record, hashes, head, reviewed_id, reviewed_token in (
            ('spec', first_spec, first_spec.get('independent_raw_sha256', {}),
             first_spec['authority']['product_head'], first_spec['request']['response_id'],
             first_spec['provenance']['invocation_token']),
            ('quality', first_quality, first_quality.get('independent_sha256', {}),
             first_quality['authority']['product_head_verified_clean'],
             first_quality['identity_and_request']['response_id'],
             first_quality['identity_and_request']['invocation_token'])):
        verdict = 'SUPPORTED_FIRST_REQUEST' if name == 'spec' else 'APPROVED_FIRST_REQUEST'
        if (record['verdict'] != verdict or head != HEAD or reviewed_id != response_id or
                reviewed_token != token or
                any(hashes.get('physical-478eb5ef/' + k) != v or
                    digest(PHYSICAL / k) != v for k, v in FIRST_HASHES.items())):
            raise ValueError('first request independent ' + name + ' approval mismatch')
    if (first_spec['provenance']['config_sha256'] != digest(CONFIG) or
            first_quality['independent_sha256'].get('physical-operator-config.json') != digest(CONFIG) or
            first_spec['provenance']['exact_clean_head_verified'] is not True):
        raise ValueError('first request source/config approval mismatch')


def run_remaining(root, ledger, config, sources, runner, evaluator, first_response_id, first_token):
    """A consumed admission runs only 2 then 3; any ambiguity burns the budget."""
    record = json.loads(ledger.read_text())
    if record['status'] != 'ADMITTED-NOT-STARTED' or record['attempted_indices']:
        raise ValueError('continuation admission already used')
    identities = {first_response_id}
    tokens = {first_token}
    for index in (2, 3):
        if sorted(p.name for p in root.glob('invocation-*')) != [f'invocation-{n:02d}' for n in range(1, index)]:
            raise ValueError('request inventory changed after admission')
        record['attempted_indices'].append(index)
        record['status'] = 'ATTEMPTED-STOP-UNTIL-EVALUATED'
        update_ledger(ledger, record)  # Write-ahead budget burn, including crashes/ambiguous outcomes.
        try:
            report = runner(config, root, index, sources)
            raw = root / f'invocation-{index:02d}'
            if report != json.loads((raw / 'receipt.json').read_text()):
                raise ValueError('retained report differs')
            if report['source_sha256'] != sources or len(report['request_windows']) != 1:
                raise ValueError('invocation source/count differs')
            response_id = report['request_windows'][0].get('response_id')
            token = report['roles']['remote']['token']
            if not response_id or response_id in identities or not token or token in tokens or report['roles']['client']['token'] != token:
                raise ValueError('duplicate or missing fresh response/lease identity')
            identities.add(response_id); tokens.add(token)
            result = evaluator(report, (raw / 'remote-rpc.log').read_bytes(),
                               (raw / 'remote-cache-strace.log').read_bytes(), json.loads(config.read_text()))
            record.setdefault('results', []).append({'index': index, 'response_id': response_id,
                'lease_token': token, 'receipt_sha256': digest(raw / 'receipt.json'), 'evaluation': result})
            if result['status'] != 'evidence-ready-for-human-review':
                record['status'] = 'STOP-EVIDENCE-GAP'
                update_ledger(ledger, record)
                return 1
            record['status'] = 'INCOMPLETE-HUMAN-REVIEW-REQUIRED'
            update_ledger(ledger, record)
        except BaseException as exc:
            record['status'] = 'STOP-AMBIGUOUS-ATTEMPT'
            record['error'] = repr(exc)
            update_ledger(ledger, record)
            raise
    return 0


def main(argv=None, runner=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-head')
    parser.add_argument('--out', type=Path, default=PHYSICAL)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'mode': 'dry-run', 'fleet_contact': False, 'would_request_indices': [2, 3],
                          'physical_pending': True, 'approval_required': True}, sort_keys=True))
        return 0
    if args.approved_head != HEAD or args.out.resolve() != PHYSICAL.resolve():
        raise ValueError('exact head and original physical root required')
    observer = approved_observer()
    first = verify_first(PHYSICAL)
    verify_reviews(ROOT)
    if digest(CONFIG) != '5cfe57c3cd4d311dec69c973bff83531140d280a3ab77ccad3e4e6195b28ad9f' or not observer.accepted_config_shape(CONFIG):
        raise ValueError('approved physical config changed')
    if subprocess.check_output(['git', '-C', str(observer.REPO), 'rev-parse', 'HEAD'], text=True).strip() != HEAD or subprocess.check_output(['git', '-C', str(observer.REPO), 'status', '--porcelain']):
        raise ValueError('product exact clean head required')
    authority = json.loads((ROOT / 'physical-preflight-authority.json').read_text())
    if (authority['run']['id'] != 37169789383 or authority['run']['head_sha'] != HEAD or
            authority['run']['conclusion'] != 'success' or authority['authorized_requests'] != 3 or
            authority['observer_sha256'] != OBSERVER_SHA or authority['tests_sha256'] != OBSERVER_TEST_SHA or
            authority['config_sha256'] != digest(CONFIG)):
        raise ValueError('retained authority/CI mismatch')
    sources = source_hashes(observer, CONFIG)
    if first['source_sha256'] != sources: raise ValueError('source identity differs from first request')
    # Live remote authority recheck is a controller prerequisite; retained snapshot is not live authority.
    metadata = {'product_head': HEAD, 'observer_sha256': OBSERVER_SHA,
                'observer_tests_sha256': OBSERVER_TEST_SHA, 'wrapper_sha256': digest(Path(__file__)),
                'wrapper_tests_sha256': digest(ROOT / 'test_continue_ordinary_acceptance.py'),
                'config_sha256': digest(CONFIG), 'source_sha256': sources,
                'first_sha256': FIRST_HASHES, 'ordinary_ci_run': 37169789383,
                'authorized_total_requests': 3}
    ledger = PHYSICAL / 'continuation-admission.json'
    reserve(PHYSICAL, ledger, metadata)
    if str(observer.REPO) not in sys.path: sys.path.insert(0, str(observer.REPO))
    status = run_remaining(PHYSICAL, ledger, CONFIG, sources, runner or observer.run_one,
                           evaluate, first['request_windows'][0]['response_id'], first['roles']['remote']['token'])
    if status: return status
    print('Two additional ordinary requests retained; independent human review and Final CPU remain pending')
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, FileNotFoundError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
