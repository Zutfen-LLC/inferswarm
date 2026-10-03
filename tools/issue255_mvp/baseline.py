#!/usr/bin/env python3
"""One isolated #255 single-host CUDA comparison; no RPC, no old evidence writes."""
import argparse
import json
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path: sys.path.insert(0, str(REPO))
from tools.issue255_mvp import measure as m

ROOT = '/home/hermes/issue255-mvp/task3-baseline'
EVIDENCE = REPO / 'docs/implementation/two-host-mvp-255/evidence/task3-baseline'
HOST = m.CLIENT
PORT = 8344
TUNNEL_PORT = 18344

def server_command():
    return (f'{m.SERVER} -m {m.MODEL} --device CUDA0 -ngl 8 -cmoe '
            f'--host 127.0.0.1 --port {PORT} -c 1024 -np 1 --no-warmup -lv 5')

def acquire(state):
    marker = ROOT + '/task3-active'
    m.remote(HOST, f'mkdir -p {shlex.quote(ROOT)}; mkdir {shlex.quote(marker)} || '
                   '{ echo "active lease already exists" >&2; exit 73; }; '
                   f'printf "%s\\n" {shlex.quote(state["token"])} > {shlex.quote(marker + "/token")}')
    state['leased'] = True

def spawn(state, name, command, log):
    marker = ROOT + '/task3-active/token'
    pid = int(m.remote(HOST, f'test "$(cat {shlex.quote(marker)})" = {shlex.quote(state["token"])} || exit 73; '
                              f'nohup {command} >{shlex.quote(ROOT + "/" + log)} 2>&1 </dev/null & echo $!').strip())
    start = m.process_start(HOST, pid)
    # Register in memory immediately so a record-write failure still leaves an exact owner to stop.
    state['owned'][name] = (pid, start)
    script = ('import pathlib,sys; token,marker,path,value=sys.argv[1:]; '
              'assert pathlib.Path(marker).read_text().strip()==token; '
              'pathlib.Path(path).write_text(value+"\\n")')
    m.remote(HOST, f'python3 -c {shlex.quote(script)} {shlex.quote(state["token"])} '
                   f'{shlex.quote(marker)} {shlex.quote(ROOT + "/" + name)} {pid}:{start}')
    return pid

def stop_owned(state):
    """Only lease-bound exact PID/start pairs; never signal unrelated processes."""
    result = {}
    script = '''import os,pathlib,signal,sys
marker,token,path,pid_text,start_text=sys.argv[1:]
if pathlib.Path(marker).read_text().strip()!=token:
    print('lease mismatch'); sys.exit()
record=pathlib.Path(path)
if not record.exists() or record.read_text().strip()!=f'{pid_text}:{start_text}':
    print('record mismatch'); sys.exit()
pid=int(pid_text)
try: fd=os.pidfd_open(pid)
except ProcessLookupError:
    record.unlink(); print('already-exited'); sys.exit()
try:
    actual=pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[19]
    if actual!=start_text: print('start-time mismatch')
    else:
        try: signal.pidfd_send_signal(fd,signal.SIGTERM); print('signaled')
        except ProcessLookupError: print('already-exited')
        record.unlink()
finally: os.close(fd)
'''
    for name, (pid, start) in list(state.get('owned', {}).items())[::-1]:
        try:
            status = m.remote(HOST, f'python3 -c {shlex.quote(script)} '
                             f'{shlex.quote(ROOT + "/task3-active/token")} {shlex.quote(state["token"])} '
                             f'{shlex.quote(ROOT + "/" + name)} {pid} {start}').strip()
            result[name] = status
            if status in ('signaled', 'already-exited'): del state['owned'][name]
        except Exception as exc: result[name] = {'not_signaled': str(exc)}
    tunnel = state.pop('tunnel', None)
    if tunnel:
        tunnel.terminate()
        try: tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired: tunnel.kill(); tunnel.wait()
    if state.get('leased') and not state['owned']:
        release = ('import pathlib,sys; marker=pathlib.Path(sys.argv[1]); '
                   'assert (marker/"token").read_text().strip()==sys.argv[2]; '
                   '(marker/"token").unlink(); marker.rmdir(); print("released")')
        try:
            result['lease'] = m.remote(HOST, f'python3 -c {shlex.quote(release)} '
                                      f'{shlex.quote(ROOT + "/task3-active")} {shlex.quote(state["token"])}').strip()
            state['leased'] = False
        except Exception as exc: result['lease'] = {'not_released': str(exc)}
    return result

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')

def launch(state):
    acquire(state)
    subprocess.run(['scp', '-q', str(REPO / 'tools/issue255_mvp/sample_gpu.py'), f'{HOST}:{ROOT}/sample_gpu.py'], check=True)
    started = time.monotonic()
    pid = spawn(state, 'server.pid', server_command(), 'server.log')
    tunnel = subprocess.Popen(['ssh','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
                               '-N','-L', f'127.0.0.1:{TUNNEL_PORT}:127.0.0.1:{PORT}', HOST],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    state['tunnel'] = tunnel
    import requests
    for _ in range(240):
        if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited')
        if not m.remote(HOST, f'kill -0 {pid} 2>/dev/null && echo alive', check=False).strip():
            raise RuntimeError('server exited before health')
        try:
            response = requests.get(f'http://127.0.0.1:{TUNNEL_PORT}/health', timeout=1)
            if response.status_code == 200 and response.json().get('status') == 'ok': break
        except (requests.RequestException, ValueError): pass
        time.sleep(.5)
    else: raise RuntimeError('no healthy server within 120 seconds')
    state.update({'server_pid':pid, 'startup_load_seconds':time.monotonic()-started,
                  'argv_server':server_command(), 'ready_wall_epoch':time.time()})
    spawn(state, 'sampler.pid', f'python3 -u {ROOT}/sample_gpu.py {pid}', 'gpu-01.jsonl')
    return state

def capture(state):
    pid = state['server_pid']
    before = m.snapshot(HOST, pid)
    nic_before = m.interface_counters(HOST, '10.0.0.204')
    save(EVIDENCE / 'before.json', {'snapshot':before, 'interface':nic_before})
    stream = m.streaming_request()
    save(EVIDENCE / 'stream.json', {'payload':m.PAYLOAD, **stream})
    after = m.snapshot(HOST, pid)
    nic_after = m.interface_counters(HOST, '10.0.0.204')
    healthy = bool(m.remote(HOST, f'kill -0 {pid} 2>/dev/null && echo alive', check=False).strip())
    save(EVIDENCE / 'after.json', {'snapshot':after,'interface':nic_after,'server_alive':healthy})
    m.fetch(HOST, f'{ROOT}/gpu-01.jsonl', EVIDENCE / 'gpu-01.jsonl')
    m.fetch(HOST, f'{ROOT}/server.log', EVIDENCE / 'server.log')
    rows = [json.loads(line) for line in (EVIDENCE / 'gpu-01.jsonl').read_text().splitlines()]
    gpu = m.gpu_window(rows, before['clock_start_epoch'], after['clock_end_epoch'], pid)
    gpu['before'] = m.snapshot_gpu(before['raw'],pid)
    gpu['after'] = m.snapshot_gpu(after['raw'],pid)
    summary = {'response':stream['result'], 'startup_load_seconds':state['startup_load_seconds'],
               'elapsed_seconds':stream['elapsed_seconds'], 'process_health_after_request':healthy,
               'gpu':gpu, 'sample_window':[before['clock_start_epoch'],after['clock_end_epoch']],
               'network':{'client_participant_rpc_bytes':0,
                          'scope':'No RPC participant/socket in single-host topology; SSH tunnel HTTP traffic not measured.',
                          'whole_host_interface_delta':{key:nic_after[key]-nic_before[key] for key in ('rx_bytes','tx_bytes')},
                          'interface_scope':'Host LAN interface includes unrelated traffic; not a request-specific counter.'}}
    save(EVIDENCE / 'summary.json', summary)
    if not healthy or gpu['matching_pid_nonzero_util_samples'] == 0:
        raise RuntimeError('server unhealthy or no matching-PID CUDA activity in request window')
    return summary

def wait_for_exit(pid, start, timeout=10):
    for _ in range(timeout * 2):
        current = m.remote(HOST, f'cat /proc/{pid}/stat 2>/dev/null || true', check=False).strip()
        if not current: return True
        suffix = current.rsplit(') ', 1)[1].split()
        if suffix[19] != str(start) or suffix[0] == 'Z': return True
        time.sleep(.5)
    return False

def verify_shutdown(state):
    pid,start = state['owned_original_server']
    exited = wait_for_exit(pid,start)
    raw = m.remote(HOST, f'ps -p {pid} -o pid,stat,cmd; ss -ltn "( sport = :{PORT} )"; '
                         'nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits')
    alive = not exited
    result = {'raw':raw, 'owned_process_alive':alive, 'port_listening':f':{PORT}' in raw,
              'gpu_memory_after_release_mib':int(raw.splitlines()[-1].split(',')[0])}
    save(EVIDENCE / 'shutdown-verified.json',result)
    if alive or result['port_listening']: raise RuntimeError('baseline server not released')
    return result

def main():
    global EVIDENCE
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=EVIDENCE)
    args = p.parse_args()
    EVIDENCE = args.output
    if EVIDENCE.exists(): raise RuntimeError('baseline output already exists; use fresh path')
    EVIDENCE.mkdir(parents=True)
    m.ROOT, m.EVIDENCE, m.LOCAL_PORT = ROOT, EVIDENCE, TUNNEL_PORT
    state = {'token':secrets.token_hex(16), 'owned':{}}
    try:
        launch(state)
        state['owned_original_server'] = state['owned']['server.pid']
        save(EVIDENCE/'topology.json', {key:value for key,value in state.items() if key!='tunnel'})
        summary = capture(state)
        print(summary['response']['response_id'],summary['response']['generated_tokens'],summary['response']['stop_reason'],flush=True)
    except BaseException as exc:
        save(EVIDENCE/'run-error.json',{'type':type(exc).__name__,'error':str(exc)})
        raise
    finally:
        save(EVIDENCE/'cleanup.json',stop_owned(state))
        if 'owned_original_server' in state: verify_shutdown(state)

if __name__=='__main__': main()
