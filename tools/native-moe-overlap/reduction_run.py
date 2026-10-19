#!/usr/bin/env python3
"""Bounded factorial supervisor. External endpoint or owned local CPU fixture only.

No SSH/model access; arithmetic analysis is a separate command after cleanup.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import time

HERE = Path(__file__).resolve().parent
EVIDENCE_CAP = 8 * 1024**3
NATIVE_PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
ARCHIVE_SHA = '03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024*1024): h.update(data)
    return h.hexdigest()


def candidate(path):
    """Authenticate actual binaries, composed source, libraries and compilers."""
    path = Path(path).resolve(); raw = json.loads(path.read_text())
    if (raw['schema'] != 'factorial-candidate-build/1' or raw['native_commit'] != NATIVE_PIN or
            raw['archive_sha256'] != ARCHIVE_SHA or raw['rpc_protocol']['major'] != 7):
        raise ValueError('factorial build schema/native/archive/protocol mismatch')
    binary = Path(raw['build_directory']); source = binary.parent/('llama.cpp-'+NATIVE_PIN)
    for name in ('native-factorial-bench','rpc-worker','factorial-rpc-fixture'):
        role = raw['roles'][name]
        if digest(role['executable']) != role['executable_sha256']:
            raise ValueError('candidate executable identity mismatch: '+name)
    for name, sha in raw['source_inputs'].items():
        if digest(Path(name) if Path(name).is_absolute() else source/name) != sha:
            raise ValueError('candidate source identity mismatch: '+name)
    composite = hashlib.sha256(json.dumps(raw['source_inputs'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if composite != raw['composite_sha256']:
        raise ValueError('candidate composite identity mismatch')
    for name, sha in raw['backend_libraries']:
        if digest(binary/name) != sha: raise ValueError('candidate backend identity mismatch: '+name)
    for compiler in raw['compiler_versions'].values():
        if digest(compiler['path']) != compiler['sha256']:
            raise ValueError('candidate compiler identity mismatch')
    executable = raw['roles']['native-factorial-bench']['executable']
    link = subprocess.run(['ldd',executable],capture_output=True,text=True,check=True,timeout=10)
    dynamic = []
    for line in link.stdout.splitlines():
        for token in line.split():
            if token.startswith('/') and Path(token).is_file():
                dynamic.append(dict(path=token,sha256=digest(token)))
    return dict(receipt=str(path),receipt_sha256=digest(path),**raw,dynamic_libraries=dynamic)


def size_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file())


def stop(child):
    """Terminate and reap our process group; never match another process by name."""
    if child is None: return
    if child.poll() is None:
        try: os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        try: child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=2)
    else: child.wait()


def supervise(child, output, timeout, worker=None):
    """Watch native wall deadline and retained bytes while the process is alive."""
    deadline = time.monotonic()+timeout
    while child.poll() is None:
        if time.monotonic() >= deadline:
            raise ValueError('native process deadline exceeded; group terminated and reaped')
        if worker is not None and worker.poll() is not None:
            raise ValueError('owned loopback worker exited during native run')
        if size_bytes(output) > EVIDENCE_CAP:
            raise ValueError('8 GiB evidence cap exceeded; group terminated and reaped')
        time.sleep(min(.25,max(0,deadline-time.monotonic())))
    if size_bytes(output) > EVIDENCE_CAP: raise ValueError('8 GiB evidence cap exceeded')
    return child.returncode


def validate_records(records, quick):
    spec = importlib.util.spec_from_file_location('factorial_validation',HERE/'reduction_check.py')
    checker = importlib.util.module_from_spec(spec); spec.loader.exec_module(checker)
    return checker.validate_records(records,small_test_grid=quick)


def run(build_receipt, output, *, endpoint=None, loopback=False, threads=14,
        timeout=300, comparison_mode='cpu-loopback', small_test=False, quick=False):
    if (bool(endpoint)==bool(loopback) or type(threads) is not int or not 1<=threads<=14 or
            type(timeout) not in (int,float) or not 0<timeout<=300 or
            comparison_mode not in ('cpu-cuda','cpu-loopback') or
            (quick and (not small_test or comparison_mode!='cpu-loopback')) or
            (loopback and comparison_mode!='cpu-loopback') or
            (small_test and comparison_mode!='cpu-loopback')):
        raise ValueError('invalid frozen factorial mode/thread/deadline/quick grid')
    for key in ('IS309_MOE','IS309_CAPTURE','IS314_HOT_SPEC','IS311_ASSIGNED','IS_FACTORIAL_TRANSPORT','IS_REDUCED_OUTPUT'):
        if key in os.environ: raise ValueError('refuse inherited '+key)
    provenance = candidate(build_receipt)
    if provenance['portable_fixture_build'] and not small_test:
        raise ValueError('portable fixture build requires small-test; no production timings')
    output = Path(output).resolve(); output.mkdir(exist_ok=False)
    receipt = dict(schema='h5-layer7-factorial-run/1',valid=False,execution_complete=False,
        timing_comparison_valid=False,numerical_qualification=False,physical_gpu_evidence=False,
        offline_analysis_required=True,candidate=provenance,comparison_mode=comparison_mode,
        small_test=small_test,small_test_grid=quick,threads=threads,timeout_seconds=timeout,
        evidence_cap_bytes=EVIDENCE_CAP,runner_sha256=digest(__file__),
        started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        host=dict(hostname=platform.node(),platform=platform.platform(),machine=platform.machine()),
        scope='same ten selected experts/token; five or ten remote; 5/26 resident experts in one synthetic layer; not full-capacity placement')
    native = worker = None
    old_handlers = {}
    def interrupted(signum, frame): raise InterruptedError('supervisor received signal '+str(signum))
    for signum in (signal.SIGTERM,signal.SIGINT):
        old_handlers[signum] = signal.signal(signum,interrupted)
    try:
        if loopback:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
            endpoint = '127.0.0.1:'+str(port)
            worker_path = provenance['roles']['rpc-worker']['executable']
            command = [worker_path,'--host','127.0.0.1','--port',str(port),'--device','CPU','--threads',str(threads)]
            with (output/'worker.log').open('xb') as log:
                worker = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            receipt['worker'] = dict(command=command,pid=worker.pid,executable_sha256=digest(worker_path))
            deadline = time.monotonic()+min(10,timeout)
            while True:
                if worker.poll() is not None: raise ValueError('loopback worker exited before readiness')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1): break
                except OSError:
                    if time.monotonic()>=deadline: raise ValueError('loopback readiness deadline exceeded')
                    time.sleep(.02)
        command = [provenance['roles']['native-factorial-bench']['executable'],'--endpoint',endpoint,
                   '--work-dir',str(output/'native'),'--threads',str(threads),'--comparison-mode',comparison_mode]
        if small_test: command.append('--small-test')
        if quick: command.append('--quick')
        receipt.update(command=command,endpoint=endpoint,local_cpu_loopback=loopback)
        started = time.monotonic()
        with (output/'stdout.jsonl').open('xb') as stdout, (output/'stderr.log').open('xb') as stderr:
            native = subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True)
            receipt['native_pid'] = native.pid
            receipt['returncode'] = supervise(native,output,timeout,worker)
        receipt['native_wall_seconds'] = time.monotonic()-started
        if receipt['returncode']: raise ValueError('native exit '+str(receipt['returncode'])+'; retained stdout/stderr')
        records = [json.loads(line) for line in (output/'stdout.jsonl').read_text().splitlines()]
        timed, blocks, mode = validate_records(records,quick)
        if mode != comparison_mode: raise ValueError('native comparison mode mismatch')
        receipt.update(valid=True,execution_complete=True,measured_factorial_pairs=len(timed),
            measured_fixture_blocks=sum(not row['warmup'] for row in blocks),
            warmup_fixture_blocks=sum(row['warmup'] for row in blocks),
            checker_sha256=digest(HERE/'reduction_check.py'),
            note='structural execution only; offline full replay/check/cleanup required before conditional performance observation')
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        receipt['error'] = str(error)
    finally:
        stop(native)
        if native is not None: receipt.update(native_reaped=native.poll() is not None,native_returncode=native.returncode)
        stop(worker)
        if worker is not None: receipt['worker'].update(reaped=worker.poll() is not None,returncode=worker.returncode)
        for signum, handler in old_handlers.items(): signal.signal(signum,handler)
        receipt['evidence_bytes'] = size_bytes(output)
        receipt['artifacts'] = {p.relative_to(output).as_posix():digest(p) for p in sorted(output.rglob('*')) if p.is_file()}
        with (output/'run.json').open('x') as stream:
            json.dump(receipt,stream,sort_keys=True,indent=2,allow_nan=False); stream.write('\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument('--endpoint'); where.add_argument('--loopback',action='store_true')
    parser.add_argument('--threads',type=int,default=14)
    parser.add_argument('--timeout',type=float,default=300)
    parser.add_argument('--comparison-mode',choices=('cpu-cuda','cpu-loopback'),default='cpu-loopback')
    parser.add_argument('--small-test',action='store_true')
    parser.add_argument('--quick',action='store_true',help='local small geometry only: one warmup/two measured blocks per width')
    args = parser.parse_args()
    try: result = run(**vars(args))
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        result = dict(valid=False,execution_complete=False,error=str(error))
    print(json.dumps({k:v for k,v in result.items() if k not in ('candidate','host','artifacts')},sort_keys=True,allow_nan=False))
    return 0 if result['execution_complete'] else 2


if __name__=='__main__': raise SystemExit(main())
