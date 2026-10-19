#!/usr/bin/env python3
"""Bounded matched layer-7 native benchmark. No SSH, model, install or GPU launch.

An external endpoint can be an explicitly authorized existing RPC-v7 worker.
--loopback starts only the candidate CPU fixture worker and always reaps it.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import socket
import struct
import subprocess
import tarfile
import time

HERE = Path(__file__).resolve().parent
ARCHIVE_SHA = 'a79e3c2f9ffa9e3ffe7ede4d94d63c43976ba817aa022cd95407c7466ce9276b'
HOT = {54, 74, 136, 290, 394}
CLIENT_MEMBER = 'evidence/arm-B/client/client.log'
PREPARED_MEMBER = 'coordinator/immutable-prepared.json'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1 << 20):
            h.update(data)
    return h.hexdigest()


def parse_routing(text):
    """Only IDs and F32 bits from the two frozen decode windows, not activations."""
    rows = {}
    pattern = re.compile(r'^IS314_STEP layer=7 phase=decode step=(\d+) hot=(\d+) cold=(\d+) .*?ids=([0-9,]+) weight_bits=([0-9a-f,]+)$')
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if not match:
            continue
        step, hot, cold = map(int, match.group(1, 2, 3))
        if not (8 <= step <= 38 or 84 <= step <= 114):
            continue
        ids = [int(v) for v in match[4].split(',')]
        bits = match[5].split(',')
        if (step in rows or len(ids) != 10 or len(set(ids)) != 10 or
                any(not 0 <= v < 512 for v in ids) or len(bits) != 10 or
                any(not re.fullmatch('[0-9a-f]{8}', b) for b in bits)):
            raise ValueError('invalid/duplicate captured routing row')
        weights = [struct.unpack('<f', bytes.fromhex(b)[::-1])[0] for b in bits]
        if ((hot, cold) != (5, 5) or len(set(ids) & HOT) != 5 or
                any(not math.isfinite(w) or w <= 0 for w in weights)):
            raise ValueError('captured routing partition/weight mismatch')
        rows[step] = dict(label=f'request{2 if step < 84 else 5}:step{step}',
                          ids=ids, weight_bits=bits)
    expected = set(range(8, 39)) | set(range(84, 115))
    if set(rows) != expected:
        raise ValueError('captured routing windows incomplete')
    return [rows[step] for step in sorted(rows)]


def extract_routing(archive, output):
    archive, output = Path(archive), Path(output)
    if digest(archive) != ARCHIVE_SHA:
        raise ValueError('captured routing archive SHA-256 mismatch')
    with tarfile.open(archive) as tar:
        log = tar.extractfile(CLIENT_MEMBER).read()
        metadata = tar.extractfile(PREPARED_MEMBER).read()
    body = dict(schema='h5-layer7-routing/1', scope='captured routing only; synthetic activations, not activation replay',
                archive_sha256=ARCHIVE_SHA, members={CLIENT_MEMBER: hashlib.sha256(log).hexdigest(),
                    PREPARED_MEMBER: hashlib.sha256(metadata).hexdigest()},
                rows=parse_routing(log.decode()))
    with output.open('x') as stream:
        json.dump(body, stream, sort_keys=True, indent=2); stream.write('\n')
    return body


def candidate(receipt_path):
    """Bind actual built bytes to the composed source/compiler/static link receipt."""
    receipt_path = Path(receipt_path).resolve()
    receipt = json.loads(receipt_path.read_text())
    binary = Path(receipt['build_directory'])
    source = binary.parent / ('llama.cpp-' + receipt['native_commit'])
    role = receipt['roles']['native-layer7-bench']
    executable = Path(role['executable'])
    observed = digest(executable)
    if observed != role['identity']['executable_sha256']:
        raise ValueError('candidate executable identity mismatch')
    for name, sha in receipt['source_inputs'].items():
        path = Path(name) if Path(name).is_absolute() else source / name
        if digest(path) != sha:
            raise ValueError('candidate source identity mismatch: ' + name)
    libraries = []
    for name, sha in receipt['backend_libraries']:
        path = binary / name
        if digest(path) != sha:
            raise ValueError('candidate library identity mismatch: ' + name)
        libraries.append(dict(path=str(path), sha256=sha))
    for compiler in receipt['compiler_versions'].values():
        if digest(compiler['path']) != compiler['sha256']:
            raise ValueError('candidate compiler identity mismatch')
    link = subprocess.run(['ldd', str(executable)], capture_output=True, text=True, check=True)
    dynamic = []
    for line in link.stdout.splitlines():
        for token in line.split():
            if token.startswith('/') and Path(token).is_file():
                dynamic.append(dict(path=token, sha256=digest(token)))
    return dict(executable=str(executable), executable_sha256=observed,
                receipt=str(receipt_path), receipt_sha256=digest(receipt_path),
                source_composite_sha256=receipt['composite_sha256'], source_input_count=len(receipt['source_inputs']),
                source_inputs=receipt['source_inputs'], compiler_versions=receipt['compiler_versions'],
                libraries=libraries, dynamic_libraries=dynamic, build_options=receipt['build_options'],
                native_commit=receipt['native_commit'], archive_sha256=receipt['archive_sha256'],
                rpc_protocol=receipt['rpc_protocol'], portable_fixture_build=receipt['portable_fixture_build'])


def comparison_contract(mode):
    if mode not in ('cpu-loopback', 'cpu-cuda'):
        raise ValueError('invalid comparison mode')
    return dict(id='legacy-cpu-unsplit/1', mode=mode, f32_round=2.0**-23,
                association_multiplier=8, cross_backend_headroom=2.0**-7,
                zero_plane_fallback=8*2.0**-23, plane_source='A weighted slots')


def validate_weights(native, setup):
    native = Path(native)
    if (digest(native/'weights.json') != setup['weights_sha256'] or
            digest(native/'spec.json') != setup['weight_spec_sha256']):
        raise ValueError('native weight manifest identity mismatch')
    inventory = json.loads((native/'weights.json').read_text())
    d, f, experts, slots = setup['dimensions']
    expected = {f'blk.7.ffn_{kind}_exps.weight': (8, [d,f,experts,1]) for kind in ('gate','up')}
    expected['blk.7.ffn_down_exps.weight'] = (8, [f,d,experts,1])
    expected.update({f'blk.7.ffn_{kind}_shexp.weight': (8, [d,f,1,1]) for kind in ('gate','up')})
    expected.update({'blk.7.ffn_down_shexp.weight': (8, [f,d,1,1]),
                     'blk.7.ffn_gate_inp_shexp.weight': (0, [d,1,1,1]),
                     'blk.7.ffn_gate_inp.weight': (0, [d,experts,1,1])})
    tensors = inventory['tensors']
    if (inventory['schema'] != 'h5-layer7-weights/1' or len(tensors) != len(expected) or
            {t['name'] for t in tensors} != set(expected)):
        raise ValueError('incomplete native weight inventory')
    by_name = {}
    for t in tensors:
        kind, shape = expected[t['name']]
        size = math.prod(shape)*4 if kind == 0 else math.prod(shape)//32*34
        if ((t['ggml_type'], t['shape'], t['byte_length']) != (kind, shape, size) or
                not re.fullmatch('[0-9a-f]{64}', t['sha256'])):
            raise ValueError('invalid native weight type/shape/bytes/digest')
        by_name[t['name']] = t
    spec = json.loads((native/'spec.json').read_text())
    for t in spec['tensors']:
        if t['source_sha256'] != by_name[t['source_name']]['sha256']:
            raise ValueError('native expert weight identity mismatch')


def validate_result(rows, pairs, warmup, comparison_mode='cpu-loopback', tokens_list=(1,), diagnostic_pair13=False):
    if not rows or rows[0].get('type') != 'setup' or rows[-1].get('type') != 'summary':
        raise ValueError('incomplete native result')
    if (rows[0].get('comparator') != comparison_contract(comparison_mode) or
            rows[0].get('comparison_mode') != comparison_mode):
        raise ValueError('native comparator/mode mismatch')
    observed_tokens = rows[0].get('tokens_list')
    if observed_tokens is not None and observed_tokens != list(tokens_list):
        raise ValueError('native token batch list mismatch')
    summary = rows[-1]
    if not summary.get('valid') or (not diagnostic_pair13 and not summary.get('timing_comparison_valid')):
        raise ValueError('native comparison invalid')
    records = [r for r in rows if r.get('type') in (('pair', 'diagnostic-prime') if diagnostic_pair13 else ('pair',))]
    expected = set()
    for tokens in tokens_list:
        suffix = ('',) if tokens == 1 else ('-varied-set', '-shared-set')
        for case in ('mixed', 'all-cold'):
            for tag in suffix:
                for warm, n in ((True, warmup), (False, pairs)):
                    for i in range(n):
                        expected.add((case + tag, tokens, warm, i))
    if diagnostic_pair13:
        expected = {(case, 1, warm, i) for case in ('mixed', 'all-cold')
                    for warm, count in ((True, 5), (False, 20)) for i in range(count)}
        expected |= {('mixed-varied-set', 2, warm, i)
                     for warm, count in ((True, 5), (False, 14)) for i in range(count)}
        sequence = [(case, 1, warm, i) for case in ('mixed', 'all-cold')
                    for warm, count in ((True, 5), (False, 20)) for i in range(count)]
        sequence += [('mixed-varied-set', 2, warm, i)
                     for warm, count in ((True, 5), (False, 14)) for i in range(count)]
        if ([(r['case'], r['tokens'], r['warmup'], r['pair']) for r in records] != sequence or
                any(r['type'] != 'diagnostic-prime' for r in records[:-1]) or
                records[-1]['type'] != 'pair' or
                any(r.get('performance_claim') is not False for r in records) or
                summary.get('timing_comparison_valid') is not False or
                summary.get('diagnostic_complete') is not True or
                summary.get('priming_pairs') != 68 or summary.get('target_pairs') != 1 or
                records[-1].get('capture', {}).get('status') != 'complete'):
            raise ValueError('diagnostic prefix/target/capture mismatch')
    if len(records) != len(expected) or {(r['case'], r.get('tokens', 1), r['warmup'], r['pair']) for r in records} != expected:
        raise ValueError('native paired count/coverage mismatch')
    measured_expected = 0 if diagnostic_pair13 else len(expected) - sum(1 for (_, _, warm, _) in expected if warm)
    if summary['measured_pairs'] != measured_expected:
        raise ValueError('native paired count/coverage mismatch')
    owners = {r['B']['owner'] for r in records}
    if len(owners) != 1 or not next(iter(owners)):
        raise ValueError('native graph owner not reused')
    for r in records:
        expected_order = 'AB' if r['pair'] % 2 == 0 else 'BA'
        tokens = r.get('tokens', 1)
        if tokens not in tokens_list:
            raise ValueError('native pair token width outside requested sweep')
        case = r['case']
        base, _, tag = case.partition('-')
        want_hot = 5 if base == 'mixed' else 0
        if (r['order'] != expected_order or
                any(r[arm]['input_sha256'] != r['input_sha256'] or
                    r[arm]['routing_sha256'] != r['routing_sha256'] or
                    r[arm]['order'] != expected_order.index(arm) for arm in ('A', 'B'))):
            raise ValueError('matched input/routing/order mismatch')
        if (not r['valid'] or not r['correctness']['pass'] or not r['correctness']['finite'] or
                not r['shared_nonzero'] or not r['experts_nonzero'] or
                (r['hot'], r['cold']) != (want_hot, 10 - want_hot)):
            raise ValueError('invalid native numerical/partition/shared/expert result')
        rows_ids = r['ids'] if tokens > 1 else [r['ids']]
        rows_bits = r['weight_bits'] if tokens > 1 else [r['weight_bits']]
        if len(rows_ids) != tokens or len(rows_bits) != tokens:
            raise ValueError('native per-token routing row count mismatch')
        if not isinstance(r.get('routing_labels'), list) or len(r['routing_labels']) != tokens:
            raise ValueError('native per-token routing labels missing')
        # every token carries ten in-range distinct IDs and finite positive weights;
        # the row hash is re-derived from the displayed rows so routing attribution
        # cannot drift from the recorded partition
        ids_packed = weights_packed = b''
        for token_ids, token_bits in zip(rows_ids, rows_bits):
            if (len(token_ids) != 10 or len(token_bits) != 10 or
                    any(type(v) is not int or not 0 <= v < 512 for v in token_ids) or
                    len(set(token_ids)) != 10 or
                    any(not re.fullmatch('[0-9a-f]{8}', b) for b in token_bits)):
                raise ValueError('native per-token routing row malformed')
            weights = [struct.unpack('<f', bytes.fromhex(b)[::-1])[0] for b in token_bits]
            if any(not math.isfinite(w) or w <= 0 for w in weights):
                raise ValueError('native per-token routing weights invalid')
            ids_packed += struct.pack('<10i', *token_ids)
            weights_packed += b''.join(bytes.fromhex(b)[::-1] for b in token_bits)
        if hashlib.sha256(ids_packed + weights_packed).hexdigest() != r['routing_sha256']:
            raise ValueError('native routing hash does not match displayed rows')
        if any(not isinstance(r['correctness'].get(key), (int, float)) or
               not math.isfinite(r['correctness'][key]) or r['correctness'][key] < 0
               for key in ('max_abs', 'max_ratio', 'rms', 'relative_l2')) or r['correctness']['max_ratio'] > 1:
            raise ValueError('invalid native comparator metrics')
        if any(not math.isfinite(r[arm]['total_layer_ms']) or r[arm]['total_layer_ms'] <= 0 for arm in ('A', 'B')):
            raise ValueError('invalid native layer time')
        if r['B'].get('tokens', 1) != tokens:
            raise ValueError('native B token count mismatch')
    return summary


PR346_RUN_SHA256 = '89c148c31c222580375ff768b35124be2cbbf267eb739000fd830b4c0a7e1331'


def retained_pair13(path):
    """Authenticate the original run before reading its target boundary hashes."""
    if digest(path) != PR346_RUN_SHA256:
        raise ValueError('PR346 retained run archive identity mismatch')
    targets = []
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.endswith('/stdout.jsonl'):
                if member.size > 16*1024*1024:
                    raise ValueError('retained stdout budget exceeded')
                for line in archive.extractfile(member).read().splitlines():
                    row = json.loads(line)
                    if (row.get('type') == 'pair' and row.get('case') == 'mixed-varied-set' and
                            row.get('tokens') == 2 and row.get('pair') == 13 and row.get('warmup') is False):
                        targets.append(row)
    if len(targets) != 1:
        raise ValueError('retained pair13 boundary missing/ambiguous')
    return targets[0]


def validate_capture(native):
    """Read the bounded raw capture. Check every tensor before offline analysis."""
    native = Path(native)
    root = native/'capture'
    manifest_path = root/'manifest.json'
    if manifest_path.stat().st_size > 65536:
        raise ValueError('capture metadata budget exceeded')
    manifest = json.loads(manifest_path.read_text())
    if manifest['schema'] != 'h5-layer7-capture/2' or manifest['byte_order'] != 'little':
        raise ValueError('capture schema/byte order mismatch')
    if manifest.get('B_weighted_source') != 'retained-branch-outputs/1':
        raise ValueError('capture weighted source mismatch')
    limit = manifest['payload_limit_bytes']
    if type(limit) is not int or not 1 <= limit <= 16*1024*1024:
        raise ValueError('capture payload limit invalid')
    total = 0
    for name, tensor in manifest['tensors'].items():
        if (not re.fullmatch(r'[AB]\.(?:hot\.|cold\.)?[a-z]+', name) or
                tensor['file'] != name + '.bin'):
            raise ValueError('capture tensor filename invalid')
        shape = tensor['shape']
        if len(shape) != 4 or any(type(n) is not int or n < 1 for n in shape):
            raise ValueError('capture tensor shape invalid')
        size = math.prod(shape)*4
        if tensor['type_name'] not in ('f32', 'i32') or tensor['byte_length'] != size:
            raise ValueError('capture tensor type/size mismatch')
        path = root/tensor['file']
        total += size
        if total > limit or path.stat().st_size != size or digest(path) != tensor['sha256']:
            raise ValueError('capture tensor budget/identity mismatch')
    if total != manifest['payload_bytes']:
        raise ValueError('capture payload size mismatch')
    for name in ('weights.json', 'spec.json', 'assigned.txt'):
        if digest(native/name) != manifest['identities'][name]:
            raise ValueError('capture weight identity mismatch')
    return manifest


def run(build_receipt, output, *, endpoint=None, loopback=False, small_test=False,
        pairs=20, warmup=5, timeout=300, threads=8, seed=314159, routing_archive=None, comparison_mode='cpu-loopback',
        tokens_list=(1,), failure_dump=False, diagnostic_pair13=False, dump_max_bytes=16*1024*1024, retained_run=None):
    if retained_run and (not diagnostic_pair13 or small_test):
        raise ValueError('retained run requires production-geometry pair13 diagnostic')
    if diagnostic_pair13:
        if (pairs, warmup, seed) != (20, 5, 314159) or routing_archive or tuple(tokens_list) not in ((1,), (1, 2, 4, 8, 16)):
            raise ValueError('pair13 diagnostic requires frozen seed/warmup/pairs/synthetic routing/width allocation')
        tokens_list = (1, 2, 4, 8, 16)
    if type(dump_max_bytes) is not int or not 1 <= dump_max_bytes <= 16*1024*1024:
        raise ValueError('capture payload budget invalid')
    tokens_list = tuple(sorted(set(int(t) for t in tokens_list)))
    if (not tokens_list or any(type(t) is not int or not 1 <= t <= 256 for t in tokens_list)):
        raise ValueError('token batch list invalid')
    if (bool(endpoint) == bool(loopback) or type(pairs) is not int or not 1 <= pairs <= 100 or
            type(warmup) is not int or not 0 <= warmup <= 20 or not 0 < timeout <= 600 or
            type(threads) is not int or not 1 <= threads <= 128 or type(seed) is not int or not 1 <= seed <= 2147483647):
        raise ValueError('endpoint/loopback or bounded benchmark budget invalid')
    if len(','.join(map(str, tokens_list))) > 63:
        raise ValueError('token list too long')
    contract = comparison_contract(comparison_mode)  # freeze before launching any work
    for key in ('IS309_MOE', 'IS309_CAPTURE', 'IS314_HOT_SPEC', 'IS311_ASSIGNED'):
        if key in os.environ:
            raise ValueError('refuse inherited ' + key)
    provenance = candidate(build_receipt)
    if provenance['portable_fixture_build'] and not small_test:
        raise ValueError('portable fixture build requires --small-test; no production timing')
    output = Path(output).resolve(); output.mkdir(exist_ok=False)
    receipt = dict(schema='h5-layer7-run/1', valid=False, timing_comparison_valid=False,
        runner_sha256=digest(__file__), comparator=contract, comparison_mode=comparison_mode,
        physical_gpu_evidence=False, candidate=provenance, timed_out=False,
        started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        host=dict(hostname=platform.node(), platform=platform.platform(), machine=platform.machine(),
            cpuinfo=Path('/proc/cpuinfo').read_text().split('\n\n')[0],
            meminfo=Path('/proc/meminfo').read_text()),
        scope='layer routing boundary only; synthetic weights+activations; not model/activation replay or qualification')
    worker = None
    try:
        if diagnostic_pair13:
            command = [provenance['executable'], '--endpoint', 'unused:1', '--work-dir', str(output/'unused-probe'),
                       '--control', 'fixture-probe']
            if small_test:
                command.append('--small-test')
            probe = subprocess.run(command, capture_output=True, text=True, check=True, timeout=5)
            fixture = json.loads(probe.stdout)
            receipt['selected_fixture'] = fixture
            receipt['retained_identity_check'] = 'unavailable; no retained archive supplied'
            if retained_run:
                old = retained_pair13(retained_run)
                for key in ('input_sha256', 'routing_sha256'):
                    if fixture[key] != old[key]:
                        raise ValueError('selected fixture differs from retained pair13: ' + key)
                if ([r['ids'] for r in fixture['rows']] != old['ids'] or
                        [r['weight_bits'] for r in fixture['rows']] != old['weight_bits']):
                    raise ValueError('selected routing differs from retained pair13')
                receipt['retained_identity_check'] = 'verified input/routing hashes and slot/weight bits'
                receipt['retained_run_sha256'] = PR346_RUN_SHA256
        if loopback:
            raw = json.loads(Path(build_receipt).read_text())
            role = raw['roles']['rpc-worker']; worker_path = role['executable']
            if digest(worker_path) != role['identity']['executable_sha256']:
                raise ValueError('loopback worker identity mismatch')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            endpoint = f'127.0.0.1:{port}'
            command = [worker_path, '--host', '127.0.0.1', '--port', str(port), '--device', 'CPU', '--threads', str(threads)]
            worker_log = (output/'worker.log').open('w')
            worker = subprocess.Popen(command, stdout=worker_log, stderr=subprocess.STDOUT)
            worker_log.close()
            receipt['worker'] = dict(command=command, executable_sha256=digest(worker_path), pid=worker.pid)
            deadline = time.monotonic() + min(10, timeout)
            while True:
                if worker.poll() is not None:
                    raise ValueError('loopback worker exited before readiness')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError('loopback worker readiness timeout')
                    time.sleep(.02)
        command = [provenance['executable'], '--endpoint', endpoint, '--work-dir', str(output/'native'),
                   '--pairs', str(pairs), '--warmup', str(warmup), '--threads', str(threads), '--seed', str(seed),
                   '--tokens', ','.join(map(str, tokens_list)),
                   '--comparison-mode', comparison_mode]
        if failure_dump:
            command.append('--failure-dump')
        if diagnostic_pair13:
            command.append('--diagnostic-pair13')
        if failure_dump or diagnostic_pair13:
            command.extend(['--dump-max-bytes', str(dump_max_bytes)])
        if small_test:
            command.append('--small-test')
        if routing_archive:
            body = extract_routing(routing_archive, output/'routing.json')
            receipt['captured_routing'] = {k: v for k, v in body.items() if k != 'rows'}
            receipt['captured_routing']['row_count'] = len(body['rows'])
            command.extend(['--routing', str(output/'routing.json')])
        receipt.update(command=command, endpoint=endpoint, timeout_seconds=timeout,
                       local_cpu_loopback=loopback, small_test=small_test, tokens_list=list(tokens_list))
        with (output/'stdout.jsonl').open('w') as stdout, (output/'stderr.log').open('w') as stderr:
            try:
                result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout)
                receipt['returncode'] = result.returncode
            except subprocess.TimeoutExpired:
                receipt['timed_out'] = True
                raise ValueError('native process deadline exceeded; killed and reaped')
        rows = [json.loads(line) for line in (output/'stdout.jsonl').read_text().splitlines()]
        if failure_dump or diagnostic_pair13:
            receipt['diagnostic_pair13'] = diagnostic_pair13
            receipt['capture_requested'] = True
            receipt['capture_rows'] = [r for r in rows if 'capture' in r]
            if (output/'native/capture/manifest.json').exists():
                receipt['capture'] = validate_capture(output/'native')
        if result.returncode:
            raise ValueError(f'native exit {result.returncode}; inspect retained stdout/stderr')
        summary = validate_result(rows, pairs, warmup, comparison_mode, tokens_list, diagnostic_pair13)
        validate_weights(output/'native', rows[0])
        receipt.update(valid=True, timing_comparison_valid=not diagnostic_pair13, summary=summary)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        receipt['error'] = str(error)
    finally:
        if worker:
            worker.terminate()
            try:
                worker.wait(timeout=2)
            except subprocess.TimeoutExpired:
                worker.kill(); worker.wait(timeout=2)
            receipt['worker']['returncode'] = worker.returncode
            receipt['worker']['reaped'] = worker.poll() is not None
        receipt['artifacts'] = {p.relative_to(output).as_posix(): digest(p)
                                for p in sorted(output.rglob('*')) if p.is_file()}
        (output/'run.json').write_text(json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False)+'\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--endpoint'); mode.add_argument('--loopback', action='store_true')
    parser.add_argument('--comparison-mode', choices=('cpu-loopback','cpu-cuda'), default='cpu-loopback')
    parser.add_argument('--small-test', action='store_true')
    parser.add_argument('--failure-dump', action='store_true', help='capture the first refused pair outside timing')
    parser.add_argument('--diagnostic-pair13', action='store_true', help='original prefix then only T=2 varied-set measured pair 13; no performance claim')
    parser.add_argument('--dump-max-bytes', type=int, default=16*1024*1024)
    parser.add_argument('--captured-routing', type=Path)
    parser.add_argument('--retained-run', type=Path, help='authenticate PR346 archive and check pair13 identities before worker launch')
    parser.add_argument('--pairs', type=int, default=20); parser.add_argument('--warmup', type=int, default=5)
    parser.add_argument('--timeout', type=float, default=300); parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--seed', type=int, default=314159)
    parser.add_argument('--tokens', default='1', help='comma-separated bounded batch widths, e.g. 1,2,4,8,16')
    args = parser.parse_args()
    try:
        result = run(args.build_receipt, args.output, endpoint=args.endpoint, loopback=args.loopback,
            small_test=args.small_test, pairs=args.pairs, warmup=args.warmup, timeout=args.timeout,
            threads=args.threads, seed=args.seed, routing_archive=args.captured_routing, comparison_mode=args.comparison_mode,
            tokens_list=tuple(int(v) for v in args.tokens.split(',')), failure_dump=args.failure_dump,
            diagnostic_pair13=args.diagnostic_pair13, dump_max_bytes=args.dump_max_bytes, retained_run=args.retained_run)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result = dict(valid=False, timing_comparison_valid=False, error=str(error))
    print(json.dumps({k: v for k, v in result.items() if k not in ('candidate', 'host')}, sort_keys=True, allow_nan=False))
    raise SystemExit(0 if result['valid'] else 2)
