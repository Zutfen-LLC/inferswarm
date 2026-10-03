#!/usr/bin/env python3
"""Bounded #255 operator: one pinned CUDA/RPC topology, four serial measured chats.

Only touches /home/hermes/issue255-mvp/task2 on the selected participants.
Requires existing verified SSD model and independently staged/authenticated cache.
Run from controller; never kills by process name and always retains partial evidence.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time

CLIENT = 'hermes@inferswarm01'
REMOTE = 'hermes@inferswarm04'
ROOT = '/home/hermes/issue255-mvp/task2'
REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / 'docs/implementation/two-host-mvp-255/evidence/task2'
PROMPT = 'In one sentence, explain why local backups are useful.'
MODEL = '/srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf'
RPC = '/home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server'
SERVER = '/home/hermes/llama.cpp/build-v041/bin/llama-server'
CACHE = '/home/hermes/issue255-mvp-retry/cache-layer'
ENDPOINT = '10.0.0.204:50055'
LOCAL_PORT = 18343
PAYLOAD = {'messages': [{'role': 'user', 'content': PROMPT}], 'temperature': 0,
           'seed': 42, 'max_tokens': 64, 'stream': True,
           'stream_options': {'include_usage': True}}


def remote(host, command, timeout=60, *, check=True):
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', host,
                        'bash -lc ' + shlex.quote(command)], capture_output=True,
                       text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'{host} exit={p.returncode} command={command!r}: {p.stderr[-1500:]}')
    return p.stdout


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, sort_keys=True) + '\n'
    if (EVIDENCE / 'MANIFEST.json').exists():
        if not path.exists() or path.read_text() != data:
            raise RuntimeError(f'sealed evidence differs; create a successor bundle, not {path}')
        return
    path.write_text(data)


def tcp_counters(raw, pid, endpoint=ENDPOINT):
    for line, *rest in (block.splitlines() for block in raw.split('ESTAB ')[1:]):
        header = 'ESTAB ' + line
        if f'pid={pid},' not in header or endpoint not in header:
            continue
        fields = header.split()
        if len(fields) < 5 or fields[4] != endpoint:
            continue
        detail = ' '.join(rest)
        sent, received = re.search(r'\bbytes_sent:(\d+)\b', detail), re.search(r'\bbytes_received:(\d+)\b', detail)
        if sent and received:
            return {'bytes_sent': int(sent.group(1)), 'bytes_received': int(received.group(1)),
                    'local': fields[3]}
    raise ValueError(f'no matching TCP socket/counters for pid={pid} endpoint={endpoint}')


def reduce_stream(chunks, start_monotonic):
    identity = None
    reasoning, content, finish, usage, timings = [], [], None, None, None
    first_token, first_content = None, None
    for at, chunk in chunks:
        if identity is not None and chunk.get('id') != identity:
            raise ValueError('stream identity changed')
        identity = chunk.get('id')
        if not identity:
            raise ValueError('missing stream identity')
        for choice in chunk.get('choices', []):
            delta = choice.get('delta') or {}
            if delta.get('reasoning_content'):
                reasoning.append(delta['reasoning_content'])
                if first_token is None: first_token = at - start_monotonic
            if delta.get('content'):
                content.append(delta['content'])
                if first_token is None: first_token = at - start_monotonic
                if first_content is None: first_content = at - start_monotonic
            finish = choice.get('finish_reason') or finish
        usage = chunk.get('usage') or usage
        timings = chunk.get('timings') or timings
    if not usage or 'completion_tokens' not in usage:
        raise ValueError('missing usage completion tokens')
    if not ''.join(content).strip() or not finish or first_token is None:
        raise ValueError('empty visible completion, finish reason or first token')
    if not timings or 'predicted_per_second' not in timings:
        raise ValueError('missing server decode timings')
    return {'response_id': identity, 'reasoning': ''.join(reasoning), 'completion': ''.join(content),
            'stop_reason': finish, 'generated_tokens': usage['completion_tokens'],
            'usage': usage, 'timings': timings,
            'first_token_ttft_seconds': first_token,
            'first_visible_content_seconds': first_content,
            'decode_tokens_per_second': timings['predicted_per_second']}


def gpu_window(rows, start, end, pid):
    selected = [r for r in rows if start <= r['epoch'] <= end and 'used_mib' in r]
    present = [r for r in selected if pid in r['pids']]
    process_memory = [int(str(r.get('process_memory', {}).get(str(pid), r.get('process_memory', {}).get(pid, ''))).split()[0])
                      for r in present if str(r.get('process_memory', {}).get(str(pid), r.get('process_memory', {}).get(pid, ''))).split() and
                      str(r.get('process_memory', {}).get(str(pid), r.get('process_memory', {}).get(pid, ''))).split()[0].isdigit()]
    return {'sample_count': len(selected), 'process_present_samples': len(present),
            'matching_pid_nonzero_util_samples': sum(r['util_percent'] > 0 for r in present),
            'sampled_peak_used_mib': max((r['used_mib'] for r in selected), default=None),
            'sampled_peak_util_percent': max((r['util_percent'] for r in selected), default=None),
            'sampled_peak_process_mib': max(process_memory, default=None),
            'sampling_scope': 'nvidia-smi device-wide utilization and memory; simultaneous matching compute PID occupancy. Not per-kernel attribution or absolute peak.'}


def snapshot_gpu(raw, pid):
    lines = raw.splitlines()
    used, util = [int(x.strip()) for x in lines[1].split(',')]
    process_mib = None
    for line in lines[2:]:
        match = re.fullmatch(r'(\d+),\s*(\d+)(?:\s+MiB)?', line.strip())
        if match and int(match.group(1)) == pid:
            process_mib = int(match.group(2))
            break
    return {'used_mib': used, 'util_percent': util, 'process_mib': process_mib}


def add_gpu_endpoints(summary, evidence=None):
    path = (evidence or EVIDENCE) / f"request-{summary['index']:02d}"
    before = json.loads((path / 'before.json').read_text())
    after = json.loads((path / 'after.json').read_text())
    for host in ('01', '04'):
        pid = before['snapshots'][host]['pid']
        assert after['snapshots'][host]['pid'] == pid
        summary['gpu'][host]['before'] = snapshot_gpu(before['snapshots'][host]['raw'], pid)
        summary['gpu'][host]['after'] = snapshot_gpu(after['snapshots'][host]['raw'], pid)
    save(path / 'summary.json', summary)
    return summary


def acquire_hosts(state):
    """An atomic mkdir lease per host; an existing run is never ours to clean."""
    marker = shlex.quote(ROOT + '/task2-active')
    token = shlex.quote(state['token'])
    for host in (CLIENT, REMOTE):
        remote(host, f'mkdir -p {shlex.quote(ROOT)}; '
                     f'mkdir {marker} || {{ echo "active lease already exists" >&2; exit 73; }}; '
                     f'printf "%s\\n" {token} > {marker}/token || '
                     f'{{ rmdir {marker}; exit 1; }}')
        state['hosts'][host] = {}


def process_start(host, pid):
    script = ('import pathlib,sys; p=pathlib.Path("/proc")/sys.argv[1]/"stat"; '
              'print(p.read_text().rsplit(") ",1)[1].split()[19])')
    return int(remote(host, f'python3 -c {shlex.quote(script)} {pid}').strip())


def record_pid(state, host, filename, pid, start=None):
    start = process_start(host, pid) if start is None else start
    marker = ROOT + '/task2-active/token'
    script = ('import pathlib,sys; token,path,record=sys.argv[1:]; '
              f'assert pathlib.Path({marker!r}).read_text().strip()==token, "lease changed"; '
              'pathlib.Path(path).write_text(record+"\\n")')
    remote(host, f'python3 -c {shlex.quote(script)} {shlex.quote(state["token"])} '
                 f'{shlex.quote(ROOT + "/" + filename)} {pid}:{start}')
    state['hosts'][host][filename] = (pid, start)
    return pid


def spawn_owned(state, host, filename, command, log):
    marker = shlex.quote(ROOT + '/task2-active/token')
    token = shlex.quote(state['token'])
    raw = remote(host, f'test "$(cat {marker})" = {token} || exit 73; '
                       f'nohup {command} >{ROOT}/{log} 2>&1 </dev/null & pid=$!; '
                       'printf "%s\\n" "$pid"')
    return record_pid(state, host, filename, int(raw.strip()))


def snapshot(host, pid, *, client=False):
    # Remote clock bounds bracket SS/GPU/process observations on that host.
    cmd = (f'date +%s.%N; nvidia-smi --query-gpu=memory.used,utilization.gpu '
           f'--format=csv,noheader,nounits; '
           f'nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits; '
           f'cat /proc/{pid}/stat 2>/dev/null; '
           f'ip route get {"10.0.0.204" if client else "10.0.0.142"}; '
           f'ss -tinp; date +%s.%N')
    raw = remote(host, cmd)
    lines = raw.splitlines()
    return {'clock_start_epoch': float(lines[0]), 'clock_end_epoch': float(lines[-1]),
            'raw': raw, 'pid': pid}


def interface_counters(host, peer):
    script = (f'i=$(ip route get {peer} | sed -n "s/.* dev \\([^ ]*\\).*/\\1/p" | '
              'cut -d " " -f1); '
              'test -n "$i" || exit 1; '
              'printf "iface=%s\\n" "$i"; '
              'for key in rx_bytes tx_bytes; do printf "%s=" "$key"; '
              'cat "/sys/class/net/$i/statistics/$key"; done')
    raw = remote(host, script)
    return {k: int(v) if k != 'iface' else v for k, v in
            (line.split('=', 1) for line in raw.splitlines())}


def log_size(host, name):
    return int(remote(host, f'wc -c < {ROOT}/{name}').strip())


def log_slice(host, name, before, after):
    # Bounded, request-specific suffix; raw launch log remains separate.
    if after < before: raise ValueError('log truncation')
    return remote(host, f'python3 -c {shlex.quote("import sys; f=open(sys.argv[1],\"rb\"); f.seek(int(sys.argv[2])); sys.stdout.buffer.write(f.read(int(sys.argv[3])))")} {ROOT}/{name} {before} {after-before}', timeout=30)


def health(client_pid, rpc_pid, tracer_pid):
    return {'client': bool(remote(CLIENT, f'kill -0 {client_pid} 2>/dev/null && echo alive', check=False).strip()),
            'rpc': bool(remote(REMOTE, f'kill -0 {rpc_pid} 2>/dev/null && echo alive', check=False).strip()),
            'tracer': bool(remote(REMOTE, f'kill -0 {tracer_pid} 2>/dev/null && echo alive', check=False).strip())}


def streaming_request():
    import requests
    start_wall, start_mono = time.time(), time.monotonic()
    with requests.post(f'http://127.0.0.1:{LOCAL_PORT}/v1/chat/completions',
                       json=PAYLOAD, stream=True, timeout=(10, 180)) as response:
        response.raise_for_status()
        events = []
        for line in response.iter_lines():
            if not line or not line.startswith(b'data: '): continue
            body = line[6:]
            if body == b'[DONE]': break
            at_wall, at_mono = time.time(), time.monotonic()
            events.append({'wall_epoch': at_wall, 'monotonic': at_mono,
                           'chunk': json.loads(body)})
    finish_wall, finish_mono = time.time(), time.monotonic()
    result = reduce_stream([(event['monotonic'], event['chunk']) for event in events], start_mono)
    return {'start_wall_epoch': start_wall, 'finish_wall_epoch': finish_wall,
            'start_monotonic': start_mono, 'finish_monotonic': finish_mono,
            'elapsed_seconds': finish_mono - start_mono, 'events': events, 'result': result}


def launch(state):
    acquire_hosts(state)
    # Sampling script is an operator-owned copy; no preexisting namespace is changed.
    for host in (CLIENT, REMOTE):
        subprocess.run(['scp', '-q', str(REPO / 'tools/issue255_mvp/sample_gpu.py'),
                        f'{host}:{ROOT}/sample_gpu.py'], check=True)
    rpc_command = (f'env LLAMA_CACHE={CACHE} /usr/bin/strace -f -ttt -e trace=openat '
                   f'-s 200 -o {ROOT}/rpc-cache-open.strace {RPC} '
                   '-H 10.0.0.204 -p 50055 -d CUDA0 -c')
    tracer = spawn_owned(state, REMOTE, 'tracer.pid', rpc_command, 'rpc.log')
    rpc_pid = None
    for _ in range(60):
        child = remote(REMOTE, f'pgrep -P {tracer} || true').strip().splitlines()
        if child:
            candidate = int(child[0])
            cmdline = remote(REMOTE, f'tr "\\0" " " </proc/{candidate}/cmdline', check=False)
            if 'ggml-rpc-server' in cmdline:
                rpc_pid = candidate
                record_pid(state, REMOTE, 'rpc.pid', rpc_pid)
                break
        time.sleep(.25)
    if rpc_pid is None: raise RuntimeError('no owned RPC child')
    for _ in range(60):
        if ':50055' in remote(REMOTE, 'ss -ltn', check=False): break
        time.sleep(.25)
    else: raise RuntimeError('owned RPC never listened')
    argv = (f'{SERVER} -m {MODEL} --rpc {ENDPOINT} --device CUDA0,RPC0 '
            '--split-mode layer --tensor-split 1,1 -ngl 8 -cmoe '
            '--host 127.0.0.1 --port 8343 -c 1024 -np 1 --no-warmup -lv 5')
    started = time.monotonic()
    client_pid = spawn_owned(state, CLIENT, 'client.pid', argv, 'client.log')
    tunnel = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                               '-N', '-L', f'127.0.0.1:{LOCAL_PORT}:127.0.0.1:8343', CLIENT],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    state['tunnel'] = tunnel  # Register before any health/JSON/timeout failure.
    import requests
    for _ in range(240):
        if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited')
        if not health(client_pid, rpc_pid, tracer)['client']:
            raise RuntimeError('client exited during startup')
        try:
            response = requests.get(f'http://127.0.0.1:{LOCAL_PORT}/health', timeout=1)
            if response.status_code == 200 and response.json().get('status') == 'ok': break
        except (requests.RequestException, ValueError): pass
        time.sleep(.5)
    else: raise RuntimeError('no healthy client within 120 seconds')
    loaded = time.monotonic()
    for host, pid, tag in ((CLIENT, client_pid, '01'), (REMOTE, rpc_pid, '04')):
        spawn_owned(state, host, 'sampler.pid',
                    f'python3 -u {ROOT}/sample_gpu.py {pid}', f'gpu-{tag}.jsonl')
    state.update({'client_pid': client_pid, 'rpc_pid': rpc_pid, 'tracer_pid': tracer,
                  'startup_load_seconds': loaded-started,
                  'argv_client': argv, 'argv_remote': rpc_command,
                  'ready_wall_epoch': time.time()})
    return state


def collect_request(index, state):
    cp, rp, tp = state['client_pid'], state['rpc_pid'], state['tracer_pid']
    path = EVIDENCE / f'request-{index:02d}'
    path.mkdir(parents=True, exist_ok=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        before_snap = list(pool.map(lambda pair: snapshot(*pair), [(CLIENT, cp), (REMOTE, rp)]))
        before_iface = list(pool.map(lambda pair: interface_counters(*pair),
                                     [(CLIENT, '10.0.0.204'), (REMOTE, '10.0.0.142')]))
        before_logs = (log_size(CLIENT, 'client.log'), log_size(REMOTE, 'rpc.log'))
    try:
        before_tcp = tcp_counters(before_snap[0]['raw'], cp)
    except ValueError:
        # Snapshots retain raw counters; missing socket must fail honestly.
        save(path / 'failure.json', {'stage': 'before_tcp', 'before_snapshots': before_snap})
        raise
    save(path / 'before.json', {'snapshots': dict(zip(('01','04'), before_snap)),
                                'interfaces': dict(zip(('01','04'), before_iface)),
                                'client_tcp': before_tcp, 'log_offsets': before_logs})
    streamed = streaming_request()
    save(path / 'stream.json', {'payload': PAYLOAD, **streamed})
    with ThreadPoolExecutor(max_workers=2) as pool:
        after_snap = list(pool.map(lambda pair: snapshot(*pair), [(CLIENT, cp), (REMOTE, rp)]))
        after_iface = list(pool.map(lambda pair: interface_counters(*pair),
                                    [(CLIENT, '10.0.0.204'), (REMOTE, '10.0.0.142')]))
        after_logs = (log_size(CLIENT, 'client.log'), log_size(REMOTE, 'rpc.log'))
    after_tcp = tcp_counters(after_snap[0]['raw'], cp)
    same_socket = before_tcp['local'] == after_tcp['local']
    if not same_socket: raise RuntimeError('RPC socket changed during request')
    for name, host, start, end in (('client', CLIENT, before_logs[0], after_logs[0]),
                                    ('rpc', REMOTE, before_logs[1], after_logs[1])):
        (path / f'{name}-request.log').write_text(log_slice(host, f'{name}.log' if name=='client' else 'rpc.log', start, end))
    healthy = health(cp, rp, tp)
    save(path / 'after.json', {'snapshots': dict(zip(('01','04'), after_snap)),
                               'interfaces': dict(zip(('01','04'), after_iface)),
                               'client_tcp': after_tcp, 'log_offsets': after_logs,
                               'health': healthy})
    network = {k: after_tcp[k]-before_tcp[k] for k in ('bytes_sent','bytes_received')}
    network['scope'] = 'Owned client↔RPC socket cumulative TCP bytes, whole before/after request window; includes dynamic traffic and protocol, not pure immutable bytes.'
    network['local'] = before_tcp['local']
    interface = {host: {key: after_iface[i][key]-before_iface[i][key] for key in ('rx_bytes','tx_bytes')}
                 for i, host in enumerate(('01','04'))}
    for host in ('01','04'): interface[host]['scope'] = 'Whole-interface counters; includes unrelated LAN traffic.'
    summary = {'index': index, 'response': streamed['result'], 'request_start_wall_epoch': streamed['start_wall_epoch'],
               'request_end_wall_epoch': streamed['finish_wall_epoch'],
               'elapsed_seconds': streamed['elapsed_seconds'], 'network_socket_delta': network,
               'interface_deltas': interface, 'process_health_after_request': healthy,
               'sample_windows': {host: {'start_epoch': before_snap[i]['clock_start_epoch'],
                                         'end_epoch': after_snap[i]['clock_end_epoch']}
                                  for i,host in enumerate(('01','04'))},
               'gpu': None, 'startup_load_seconds': state['startup_load_seconds'] if index==1 else 0,
               'startup_scope': 'One model launch precedes four serial requests; repeats reuse resident topology.'}
    save(path / 'summary.json', summary)
    if not all(healthy.values()): raise RuntimeError(f'participant lost after request {index}: {healthy}')
    return summary


def fetch(host, source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['scp', '-q', f'{host}:{source}', str(target)], check=True)


def finalize_samples(summaries, state):
    for host, tag, pid in ((CLIENT, '01', state['client_pid']),
                           (REMOTE, '04', state['rpc_pid'])):
        target = EVIDENCE / f'gpu-{tag}.jsonl'
        fetch(host, f'{ROOT}/gpu-{tag}.jsonl', target)
        rows = [json.loads(line) for line in target.read_text().splitlines()]
        for summary in summaries:
            window = summary['sample_windows'][tag]
            summary['gpu'] = summary['gpu'] or {}
            summary['gpu'][tag] = gpu_window(rows, window['start_epoch'], window['end_epoch'], pid)
            save(EVIDENCE / f"request-{summary['index']:02d}/summary.json", summary)
    return [add_gpu_endpoints(summary) for summary in summaries]


def stop_owned(state):
    # Every signal is guarded remotely by the lease, on-disk record, pidfd and
    # /proc start-time; never discover ownership from fixed shared PID files.
    result = {}
    script = '''import os, pathlib, signal, sys
token, marker, path, pid_text, start_text = sys.argv[1:]
lease, record = pathlib.Path(marker), pathlib.Path(path)
if lease.read_text().strip() != token:
    print('lease mismatch')
    sys.exit(0)
if record.read_text().strip() != f'{pid_text}:{start_text}':
    print('record mismatch')
    sys.exit(0)
pid = int(pid_text)
try:
    fd = os.pidfd_open(pid)
except ProcessLookupError:
    record.unlink()
    print('already-exited')
    sys.exit(0)
try:
    actual = pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19]
    if actual != start_text:
        print('start-time mismatch')
    else:
        try:
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            record.unlink()
            print('signaled')
        except ProcessLookupError:
            record.unlink()
            print('already-exited')
finally:
    os.close(fd)
'''
    for host, filename in ((CLIENT, 'sampler.pid'), (REMOTE, 'sampler.pid'),
                           (CLIENT, 'client.pid'), (REMOTE, 'rpc.pid'),
                           (REMOTE, 'tracer.pid')):
        owned = state.get('hosts', {}).get(host, {})
        if filename not in owned:
            continue
        pid, start = owned[filename]
        try:
            status = remote(host, f'python3 -c {shlex.quote(script)} '
                            f'{shlex.quote(state["token"])} '
                            f'{shlex.quote(ROOT + "/task2-active/token")} '
                            f'{shlex.quote(ROOT + "/" + filename)} {pid} {start}').strip()
            result[f'{host}:{filename}'] = status
            if status in ('signaled', 'already-exited'):
                del owned[filename]
        except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            result[f'{host}:{filename}'] = {'not_signaled': str(exc)}
    tunnel = state.pop('tunnel', None)
    if tunnel is not None:
        try: tunnel.terminate()
        except ProcessLookupError: pass
        try: tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait()
    for host, owned in list(state.get('hosts', {}).items()):
        if owned:  # Failed identity check: preserve lease and records for review.
            continue
        marker = ROOT + '/task2-active'
        release = ('import pathlib,sys; path=pathlib.Path(sys.argv[1]); '
                   'token=sys.argv[2]; '
                   'assert (path/"token").read_text().strip()==token, "lease changed"; '
                   '(path/"token").unlink(); path.rmdir(); print("released")')
        try:
            result[f'{host}:lease'] = remote(host, f'python3 -c {shlex.quote(release)} '
                                             f'{shlex.quote(marker)} {shlex.quote(state["token"])}').strip()
            del state['hosts'][host]
        except (RuntimeError, subprocess.SubprocessError) as exc:
            result[f'{host}:lease'] = {'not_released': str(exc)}
    return result


def validate_source():
    # Bind live participant cache file digest to Task-1 selected inventory.
    parent_evidence = REPO / 'docs/implementation/two-host-mvp-255/evidence'
    staging = parent_evidence / '04/staging-layer2.json'
    staging3 = parent_evidence / '04/staging-layer3.json'
    entries = json.loads(staging.read_text()) + json.loads(staging3.read_text())
    hits = [row for row in entries if row['bytes'] > 10*1024*1024]
    if len(hits) != 9 or sum(row['bytes'] for row in hits) != 473497600:
        raise ValueError('unexpected pinned cache source inventory')
    checks = []
    for row in hits:
        line = remote(REMOTE, 'sha256sum ' + shlex.quote(row['cache_path']), timeout=120)
        digest = line.split()[0]
        checks.append({'name': row['name'], 'cache_path': row['cache_path'],
                       'bytes': row['bytes'], 'sha256': digest,
                       'matches_staged_source': digest == row['sha256']})
    if not all(row['matches_staged_source'] for row in checks):
        raise RuntimeError('remote cache identity mismatch')
    save(EVIDENCE / 'cache-identity.json', checks)
    return checks


def audit_existing():
    """Read-only post-run reduction; never relaunch or replace measured events."""
    summaries = []
    for index in range(1, 5):
        path = EVIDENCE / f'request-{index:02d}'
        summary = json.loads((path / 'summary.json').read_text())
        stream = json.loads((path / 'stream.json').read_text())
        if summary['index'] != index or summary['response'] != stream['result']:
            raise ValueError('request summary/stream identity mismatch')
        if stream['payload'] != PAYLOAD or not all(summary['process_health_after_request'].values()):
            raise ValueError('request settings or process health mismatch')
        summaries.append(add_gpu_endpoints(summary))
    ids = [s['response']['response_id'] for s in summaries]
    if len(set(ids)) != 4:
        raise ValueError('not four distinct response identities')
    before = json.loads((EVIDENCE / 'request-01/before.json').read_text())
    source_path = EVIDENCE / 'startup-source.json'
    source = json.loads(source_path.read_text())
    source['client_rpc_tcp_bytes_sent_at_first_request_before'] = before['client_tcp']['bytes_sent']
    source['client_rpc_tcp_bytes_received_at_first_request_before'] = before['client_tcp']['bytes_received']
    source['startup_network_scope'] = ('Cumulative owned TCP socket bytes at first request-before snapshot; '
        'socket created during startup/load, includes all protocol/model traffic before first request, '
        'not an exact immutable-payload counter.')
    save(source_path, source)
    topo = json.loads((EVIDENCE / 'topology.json').read_text())
    shutdown = {}
    for host, tag, pid, port in ((CLIENT, '01', topo['client_pid'], 8343),
                                  (REMOTE, '04', topo['rpc_pid'], 50055)):
        raw = remote(host, f'ps -p {pid} -o pid,stat,cmd; '
                           f'ss -ltn "( sport = :{port} )"; '
                           'nvidia-smi --query-gpu=memory.used,utilization.gpu '
                           '--format=csv,noheader,nounits')
        shutdown[tag] = {'raw': raw, 'process_alive': bool(remote(host,
                              f'kill -0 {pid} 2>/dev/null && echo alive', check=False).strip()),
                         'port_listening': f':{port}' in raw,
                         'gpu_memory_after_release_mib': int(raw.splitlines()[-1].split(',')[0])}
    save(EVIDENCE / 'shutdown-verified.json', shutdown)
    if any(v['process_alive'] or v['port_listening'] for v in shutdown.values()):
        raise RuntimeError('owned topology not fully shut down')
    return summaries


def main():
    global EVIDENCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=EVIDENCE)
    parser.add_argument('--audit-existing', action='store_true',
                        help='read-only audit/reduction of four retained measured requests')
    args = parser.parse_args()
    EVIDENCE = args.output
    if args.audit_existing:
        audit_existing()
        return
    if (EVIDENCE / 'MANIFEST.json').exists():
        raise RuntimeError('sealed evidence directory; use a fresh output directory for a new run')
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    state, summaries = {'token': secrets.token_hex(16), 'hosts': {}}, []
    try:
        checks = validate_source()
        launch(state)
        save(EVIDENCE / 'topology.json', {k:v for k,v in state.items() if k!='tunnel'})
        for i in range(1,5):
            summaries.append(collect_request(i, state))
            print(f"request-{i:02d}: {summaries[-1]['response']['response_id']} "
                  f"{summaries[-1]['response']['generated_tokens']} tokens "
                  f"{summaries[-1]['response']['stop_reason']}", flush=True)
        finalize_samples(summaries, state)
        fetch(REMOTE, f'{ROOT}/rpc-cache-open.strace', EVIDENCE / 'rpc-cache-open.strace')
        fetch(REMOTE, f'{ROOT}/rpc.log', EVIDENCE / 'rpc.log')
        fetch(CLIENT, f'{ROOT}/client.log', EVIDENCE / 'client.log')
        cache_trace = (EVIDENCE / 'rpc-cache-open.strace').read_text(errors='replace')
        hits = {row['cache_path']: cache_trace.count('"'+row['cache_path']+'", O_RDONLY') for row in checks}
        save(EVIDENCE / 'startup-source.json', {'cache_hits_by_path': hits,
             'cache_hit_count': sum(hits.values()), 'cache_hit_immutable_bytes': sum(
                 row['bytes'] for row in checks if hits[row['cache_path']] > 0),
             'below_upstream_hash_threshold_tensors': 62,
             'below_upstream_hash_threshold_immutable_bytes_calculated': 85129984,
             'immutable_bytes_sent_counter': None,
             'explanation': 'RPC caches only payloads above 10 MiB. Nine traced O_RDONLY file opens prove startup local backing; 62 smaller tensors (85,129,984 B) are sent normally during load. No dedicated immutable-byte wire counter; figure for small tensors is calculated and TCP startup delta includes overhead.'})
        if set(hits.values()) != {1}: raise RuntimeError(f'unexpected cache source hits {hits}')
        if any(s['gpu'][h]['matching_pid_nonzero_util_samples'] == 0 for s in summaries for h in ('01','04')):
            raise RuntimeError('no matching-PID nonzero GPU sample for at least one request')
        save(EVIDENCE / 'run-summary.json', {'status': 'FOUR_MEASURED_REQUESTS',
             'launch': {k:v for k,v in state.items() if k!='tunnel'},
             'request_ids': [s['response']['response_id'] for s in summaries],
             'repeats_success': len(summaries)-1})
    except BaseException as exc:
        save(EVIDENCE / 'run-error.json', {'type':type(exc).__name__, 'error': str(exc),
             'completed_request_ids':[s['response']['response_id'] for s in summaries]})
        raise
    finally:
        save(EVIDENCE / 'cleanup.json', stop_owned(state))


if __name__ == '__main__': main()
