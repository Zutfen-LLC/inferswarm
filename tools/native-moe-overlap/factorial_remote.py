#!/usr/bin/env python3
"""Factorial CPU05 helper, sent on stdin over its existing SSH master.

No general observer: own one token-tagged process group and retain its exact
Linux /proc identity. No accepted executable or device identity is overridable.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

WORKER = '/home/hermes/is327-owned/ggml-rpc-server.cuda03'
WORKER_SHA = '46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73'
GPU_UUID = 'GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176'
CONTROL_ROOT = Path('/home/hermes/is327-owned')
TOKEN_KEY = 'H5_LAYER7_OWNER_TOKEN'
MIN_FREE_MIB = 2048  # Context + resident owners + arenas/staging, not bank size alone.


def identity(pid):
    try:
        proc = Path('/proc')/str(pid)
        fields = (proc/'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return dict(pid=int(pid), pgid=int(fields[2]), start_time=fields[19],
                    exe=os.readlink(proc/'exe'))
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def tagged(pid, token):
    try:
        return (TOKEN_KEY+'='+token).encode() in (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0')
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False


def members(pgid):
    return [item for p in Path('/proc').iterdir() if p.name.isdigit()
            if (item := identity(int(p.name))) and item['pgid'] == pgid]


def owned_members(pgid, token):
    rows = members(pgid)
    if any(not tagged(row['pid'], token) for row in rows):
        raise ValueError('group identity changed; refusing to signal unrelated processes')
    return rows


def spawn_owned(directory, token, command):
    """One fresh group; command/env are only factored for local process tests."""
    with (directory/'worker.log').open('xb') as log:
        child = subprocess.Popen(command, env=dict(os.environ, **{TOKEN_KEY: token}),
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    item = identity(child.pid)
    if item is None or item['pgid'] != child.pid:
        raise ValueError('owned group identity unavailable')
    record = dict(token=token, root=item)
    (directory/'identity.json').write_text(json.dumps(record, sort_keys=True)+'\n')
    return child, record


def terminate_owned(directory, token):
    record_path = directory/'identity.json'
    if not record_path.exists():
        # No launch is possible without holding the same startup/cleanup lock.
        # Refuse unknown if a token-tagged descendant nevertheless exists.
        if any(tagged(int(p.name), token) for p in Path('/proc').iterdir() if p.name.isdigit()):
            raise ValueError('token process exists without a recorded group; cleanup unknown')
        return dict(cleanup='verified', token=token, launched=False, owned_worker_absent=True, owned_listener_absent=True)
    record = json.loads(record_path.read_text())
    if record['token'] != token:
        raise ValueError('control token mismatch')
    root = record['root']; current = identity(root['pid'])
    if current is not None and current != root:
        raise ValueError('root PID identity changed; cleanup unknown')
    # Check all remaining descendants, including when timeout already exited.
    pgid = root['pgid']
    for sig, seconds in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        if not owned_members(pgid, token):
            break
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass  # final census below, never PID absence alone, proves cleanup
        deadline = time.monotonic()+seconds
        while owned_members(pgid, token) and time.monotonic() < deadline:
            time.sleep(.05)
    if owned_members(pgid, token):
        raise ValueError('owned process group remains after TERM/KILL bounds')
    # Listener check is ownership-specific: never kill a newly unrelated service.
    line = subprocess.check_output(['ss','-H','-lntp','sport = :50060'], text=True)
    listener_pids = [int(p) for p in re.findall(r'pid=(\d+)',line)]
    if any(tagged(pid, token) for pid in listener_pids):
        raise ValueError('owned listener remains')
    if line.strip() and not listener_pids:
        raise ValueError('listener ownership unavailable; cleanup unknown')
    return dict(cleanup='verified', token=token, root=root, owned_worker_absent=True,
                owned_listener_absent=True, unrelated_listener_preserved=bool(line.strip()))


def start(directory, token):
    # Identity and preflight are unchanged accepted facts, checked before launch.
    if hashlib.sha256(Path(WORKER).read_bytes()).hexdigest() != WORKER_SHA:
        raise ValueError('accepted worker hash mismatch')
    query = lambda field: subprocess.check_output(['nvidia-smi','-i','0',field,'--format=csv,noheader'], text=True).strip()
    if query('--query-gpu=uuid') != GPU_UUID or query('--query-compute-apps=pid'):
        raise ValueError('GPU UUID/idle preflight failed')
    free_mib = int(query('--query-gpu=memory.free').split()[0])
    if free_mib < MIN_FREE_MIB:
        raise ValueError('GPU free-memory preflight below 2048 MiB; no worker started')
    preflight = dict(
        gpu_uuid=GPU_UUID, free_mib=free_mib, minimum_free_mib=MIN_FREE_MIB,
        additional_allocation_envelope_mib=512,
        note='512 MiB is an estimate checked separately by native before/after setup; 2048 MiB reserves context and arena/staging headroom')
    (directory/'preflight.json').write_text(json.dumps(preflight,sort_keys=True)+'\n')
    print('H5_FACTORIAL_PREFLIGHT '+json.dumps(preflight,sort_keys=True),flush=True)
    if subprocess.check_output(['ss','-H','-lnt','sport = :50060'], text=True).strip():
        raise ValueError('remote port already occupied; preserved')
    print(query('--query-gpu=index,uuid,pci.bus_id,driver_version,memory.total,memory.free,temperature.gpu'), flush=True)
    os.environ['CUDA_VISIBLE_DEVICES'] = GPU_UUID
    # --foreground keeps worker in our newly created process group. The helper
    # is outside that group, so a separate cleanup request survives group TERM.
    child, record = spawn_owned(directory, token,
        ['timeout','--foreground','--signal=TERM','--kill-after=5','360',WORKER,
         '--host','127.0.0.1','--port','50060','--device','CUDA0'])
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise ValueError('owned worker exited before readiness')
        line = subprocess.check_output(['ss','-H','-lntp','sport = :50060'], text=True)
        pids = [int(p) for p in re.findall(r'pid=(\d+)',line)]
        if len(pids) == 1:
            worker = identity(pids[0])
            if (worker and worker['exe'] == os.path.realpath(WORKER) and
                    worker['pgid'] == record['root']['pgid'] and tagged(worker['pid'],token)):
                record['worker'] = worker
                (directory/'identity.json').write_text(json.dumps(record,sort_keys=True)+'\n')
                print('H5_LAYER7_WORKER_READY pid='+str(worker['pid']), flush=True)
                return child
        time.sleep(.05)
    raise ValueError('owned accepted listener readiness failed')


def main():
    action, token = sys.argv[1:]
    if action not in ('start','cleanup') or not re.fullmatch('[0-9a-f]{32}', token):
        raise ValueError('invalid bounded recipe action/token')
    directory = CONTROL_ROOT/('h5-layer7-'+token)
    # Cleanup can reserve an absent control directory when startup never ran.
    # Later start uses exist_ok=False and therefore cannot launch after cleanup.
    if action == 'start':
        directory.mkdir(mode=0o700, exist_ok=False)
    else:
        directory.mkdir(mode=0o700, exist_ok=True)
    with (directory/'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == 'cleanup':
            (directory/'terminal').touch()
            result = terminate_owned(directory, token)
            (directory/'cleanup.json').write_text(json.dumps(result,sort_keys=True)+'\n')
            print(json.dumps(result,sort_keys=True),flush=True)
            return
        if (directory/'terminal').exists():
            raise ValueError('cleanup already requested; refusing late launch')
        child = start(directory, token)
    # Keep the SSH invocation alive, but cleanup is an explicit second request.
    raise SystemExit(child.wait())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(cleanup='unknown', error=str(error))), flush=True)
        raise SystemExit(2)
