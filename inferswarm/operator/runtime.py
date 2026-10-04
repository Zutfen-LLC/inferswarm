"""One fixed-plan ordinary generation with verified sources and bounded ownership."""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import time
import urllib.error
import urllib.request

from .config import load_config
from .lifecycle import LeaseManager,SSHTransport
from .plan import build_plan
from .strategy import llama_cpp_spec

ASSIGNMENT = re.compile(r'load_tensors: layer\s+(\d+) assigned to device (\S+), is_swa = [01]')


def observed_placement(log,plan):
    spec=llama_cpp_spec(plan)
    client=next(p for p in plan.participants if p.role=='client')
    remote=next(p for p in plan.participants if p.role=='remote')
    expected={}
    for span in spec.expected_placement:
        device='CPU' if span.first_layer==0 else (client.device if span.compute_id==client.compute_id else remote.device)
        for i in range(span.first_layer,span.last_layer+1): expected[i]=device
        if span.output: expected[plan.backend_options.hidden_layers]=device
    # Pinned loader sometimes emits a second fitting pass; the LAST complete
    # assignment is authoritative. Incomplete or contradictory final pass fails.
    blocks=[]; current={}
    for line in log.splitlines():
        m=ASSIGNMENT.search(line)
        if not m: continue
        i=int(m.group(1))
        if i==0 and current: blocks.append(current); current={}
        if i in current: raise ValueError(f'duplicate loader layer assignment: {i}')
        current[i]=m.group(2)
    if current: blocks.append(current)
    if not blocks or blocks[-1]!=expected:
        actual=blocks[-1] if blocks else {}
        differing=[i for i in expected if actual.get(i)!=expected[i]]
        raise ValueError(f'placement mismatch: missing/wrong loader layers {differing[:12]}')
    return {'layers':{str(k):v for k,v in sorted(blocks[-1].items())},
            'cpu_prefix':[0,40], 'local_gpu':[41,44], 'remote_gpu':[45,47],
            'output_layer':plan.backend_options.hidden_layers}


class SSHSourceTransport:
    def verify(self,part,plan,fnv_binary=None):
        from . import source
        program=Path(source.__file__).read_text(encoding='utf-8')
        payload={'participant':asdict(part),'model':asdict(plan.model),
                 'placement':[asdict(x) for x in plan.placement],
                 'backend':asdict(plan.backend_options),'fnv_binary':fnv_binary}
        remote_command='python3 -c '+shlex.quote(program)
        proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',part.execution_address,
                             remote_command],input=json.dumps(payload),capture_output=True,text=True,timeout=1800)
        try: result=json.loads(proc.stdout)
        except ValueError as exc: raise RuntimeError(f'{part.role} source verification failed: {proc.stderr[-500:]}') from exc
        if proc.returncode or 'error' in result: raise RuntimeError(f'{part.role} source verification failed: {result.get("error",proc.stderr[-500:])}')
        return result


class JSONHTTP:
    def _request(self,url,payload=None,timeout=2):
        data=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=timeout) as response:
            if response.status!=200: raise ValueError(f'HTTP status {response.status}')
            return json.load(response)
    def get(self,url,timeout): return self._request(url,timeout=timeout)
    def post(self,url,data,timeout): return self._request(url,data,timeout)


def ssh_tunnel(address,remote_port):
    # Binding port 0 is not useful for OpenSSH -L; reserve an OS-selected local
    # loopback port, close before launching, then require SSH forward success.
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); local=sock.getsockname()[1]
    process=subprocess.Popen(['ssh','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
                              '-N','-L',f'127.0.0.1:{local}:127.0.0.1:{remote_port}',address],
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return process,local


class OperatorRunner:
    def __init__(self,source,leases,http,tunnel_factory,pause=time.sleep):
        self.source=source; self.leases=leases; self.http=http
        self.tunnel_factory=tunnel_factory; self.pause=pause; self.last_cleanup={}

    def run(self,plan):
        # Pure admission before any mutation; no inventory/hostname substitution.
        spec=llama_cpp_spec(plan)
        client=next(p for p in plan.participants if p.role=='client')
        remote=next(p for p in plan.participants if p.role=='remote')
        if not plan.backend_options.rpc_physical_device: raise ValueError('explicit rpc_physical_device required')
        if Path(client.source_path).name!=plan.model.members[0][0]: raise ValueError('client source_path must name first full GGUF member')
        if Path(remote.source_path).name!=plan.model.members[0][0]: raise ValueError('remote source_path must name first full GGUF member')
        host,sep,port=remote.rpc_endpoint.rpartition(':')
        if not sep or not host or not port.isdecimal() or int(port)!=remote.port: raise ValueError('RPC endpoint must exactly match configured port')
        if client.execution_address==remote.execution_address: raise ValueError('distinct explicit execution addresses required')
        if client.lifecycle_dir==remote.lifecycle_dir: raise ValueError('distinct lifecycle directories required')
        tunnel=None; error=None; result=None
        try:
            self.leases.acquire(remote.execution_address,remote.lifecycle_dir)
            self.leases.acquire(client.execution_address,client.lifecycle_dir)
            sources={p.role:self.source.verify(p,plan,
                     str(Path(self.leases.invocation_dir(p.execution_address))/'fnv-cache')
                     if p.role=='remote' else None) for p in (remote,client)}
            self.leases.port(remote.execution_address,host,remote.port)
            self.leases.port(client.execution_address,'127.0.0.1',client.port)
            self.leases.spawn(remote.execution_address,'rpc',
                              [remote.runtime_executable,'-H',host,'-p',str(remote.port),
                               '-d',plan.backend_options.rpc_physical_device,'-c'],cache=remote.cache_path)
            rpc_deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                self._live(client,remote,client_started=False)
                if self.leases.listening(remote.execution_address,'rpc',host,remote.port):
                    self._live(client,remote,client_started=False)
                    if time.monotonic()>rpc_deadline: raise TimeoutError('RPC owned listener startup timeout')
                    break
                self._live(client,remote,client_started=False)
                if time.monotonic()>rpc_deadline: raise TimeoutError('RPC owned listener startup timeout')
                self.pause(.5)
            self.leases.spawn(client.execution_address,'client',
                              [spec.executable,'-m',client.source_path,*spec.args,
                               '--host','127.0.0.1','--port',str(client.port)])
            # Register tunnel immediately before any health/probe can fail.
            opened=self.tunnel_factory(client.execution_address,client.port)
            tunnel,local_port=opened if isinstance(opened,tuple) else (opened,client.port)
            base=f'http://127.0.0.1:{local_port}'
            deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                self._live(client,remote)
                if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited during startup')
                try:
                    if self.http.get(base+'/health',timeout=2).get('status')=='ok': break
                except (OSError,ValueError,urllib.error.URLError): pass
                if time.monotonic()>deadline: raise TimeoutError('client startup health timeout')
                self.pause(.5)
            placement=observed_placement(self.leases.log(client.execution_address,'client'),plan)
            self._live(client,remote)
            request=dict(plan.request)
            response=self.http.post(base+'/v1/chat/completions',
                                    {'messages':[{'role':'user','content':request['prompt']}],
                                     'max_tokens':request['max_tokens'],'temperature':request['temperature'],
                                     'seed':request['seed'],'stream':False},timeout=900)
            self._live(client,remote)
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited during request')
            choice=response['choices'][0]; text=choice['message']['content']
            if not isinstance(text,str) or not text or not choice['finish_reason'] or not response['id']:
                raise ValueError('incomplete generation response')
            result={'response_id':response['id'],'text':text,'finish_reason':choice['finish_reason'],
                    'tokens':response['usage']['completion_tokens'],'plan_id':plan.plan_id,
                    'plan_digest':plan.digest,'verified_backing':sources,'observed_placement':placement}
        except BaseException as exc: error=exc
        finally:
            tunnel_error=None
            try:
                if tunnel is not None:
                    try:
                        if tunnel.poll() is None: tunnel.terminate()
                        try: tunnel.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            tunnel.kill(); tunnel.wait(timeout=5)
                    except BaseException as exc: tunnel_error=exc
            finally:
                self.last_cleanup=self.leases.cleanup()
            if tunnel_error is not None:
                error=RuntimeError(f'SSH tunnel cleanup failed: {tunnel_error}')
        if any(row.get('lease')!='released' for row in self.last_cleanup.values()):
            raise RuntimeError(f'incomplete owned cleanup: {self.last_cleanup}') from error
        if error: raise error
        result['cleanup']=self.last_cleanup
        return result

    def _live(self,client,remote,client_started=True):
        if not self.leases.alive(remote.execution_address,'rpc'): raise RuntimeError('remote participant lost')
        if client_started and not self.leases.alive(client.execution_address,'client'):
            raise RuntimeError('client participant lost')


def run_config(path):
    plan=build_plan(load_config(path))
    manager=LeaseManager(SSHTransport(),secrets.token_hex(16))
    runner=OperatorRunner(SSHSourceTransport(),manager,JSONHTTP(),ssh_tunnel)
    return runner.run(plan)
