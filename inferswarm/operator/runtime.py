"""One fixed-plan ordinary generation with verified sources and bounded ownership."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
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
from .native_observer.collector import NATIVE_LABELS
from .plan import ProfiledOperatorPlan, build_plan, revalidate_admission
from .profiles import canonical, freeze, thaw
from . import bindings
from .strategy import llama_cpp_spec

ASSIGNMENT = re.compile(r'load_tensors: layer\s+(\d+) assigned to device (\S+), is_swa = [01]')


def observed_placement(log,plan):
    if isinstance(plan,ProfiledOperatorPlan):
        raise ValueError('legacy-only layer logs; Q8 requires complete typed observations')
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
        if isinstance(plan,ProfiledOperatorPlan):
            if plan.strategy_id!='qwen38-q8-fixed/1': raise ValueError('unsupported profiled source strategy')
            projected=source.q8_source_payload(plan)
            selected=next(p for p in projected['participants'] if p['participant_id']==part.participant_id)
            helper=None
            if projected['rpc_cache'] and part.role=='remote':
                if fnv_binary is None: raise ValueError('invocation-owned FNV helper required for enabled RPC cache')
                path=Path(fnv_binary)
                root=Path(part.lifecycle_dir)
                if (not path.is_absolute() or path.name!='fnv-cache' or path.parent.parent!=root
                        or path.parent.name in ('active','.','..') or '..' in path.parts):
                    raise ValueError('invocation-owned FNV helper path required')
                helper=str(path)
                # Only provisioning is runtime-owned. The unchanged standalone
                # Q8 verifier remains read-only and is invoked separately below.
                setup=program.rsplit("if __name__=='__main__': main()",1)[0]+'\ncompile_fnv('+repr(helper)+')\n'
                proc=self._call(part,setup,'')
                if proc.returncode:
                    raise RuntimeError(f'{part.role} source helper setup failed: {proc.stderr[-500:]}')
            payload=dict(schema='q8-source-verification/1',participant=selected,
                         plan_payload=projected,fnv_binary=helper)
            proc=self._call(part,program,canonical(payload).decode('utf-8'))
            try: result=json.loads(proc.stdout)
            except ValueError as exc:
                raise RuntimeError(f'{part.role} source verification failed: {proc.stderr[-500:]}') from exc
            if proc.returncode or not isinstance(result,dict) or result.get('status')!='VERIFIED-not-consumed':
                reason=result.get('reason',proc.stderr[-500:]) if isinstance(result,dict) else 'invalid Q8 source reply'
                raise RuntimeError(f'{part.role} source verification failed (source transport exit {proc.returncode}): {reason}')
            return result
        payload={'participant':asdict(part),'model':asdict(plan.model),
                 'placement':[asdict(x) for x in plan.placement],
                 'backend':asdict(plan.backend_options),'fnv_binary':fnv_binary}
        proc=self._call(part,program,json.dumps(payload))
        try: result=json.loads(proc.stdout)
        except ValueError as exc: raise RuntimeError(f'{part.role} source verification failed: {proc.stderr[-500:]}') from exc
        if proc.returncode or 'error' in result: raise RuntimeError(f'{part.role} source verification failed: {result.get("error",proc.stderr[-500:])}')
        return result

    def _call(self,part,program,payload):
        remote_command='python3 -c '+shlex.quote(program)
        return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',part.execution_address,
                               remote_command],input=payload,capture_output=True,text=True,timeout=1800)


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
    def __init__(self,source,leases,http,tunnel_factory,pause=time.sleep,*,
                 binding_transport=None,identity_reader=None,observation_mode='live',clock=None,
                 collector=None,static_reconciler=None,dynamic_reconciler=None):
        self.source=source; self.leases=leases; self.http=http
        self.tunnel_factory=tunnel_factory; self.pause=pause; self.last_cleanup={}
        # Internal synthetic plumbing only: run_config/CLI never exposes this.
        self.binding_transport=binding_transport; self.identity_reader=identity_reader
        self.observation_mode=observation_mode; self.clock=clock
        # #302 real collector path: production wiring supplies these through
        # run_config; tests inject recording doubles.
        self.collector=collector
        self.static_reconciler=static_reconciler
        self.dynamic_reconciler=dynamic_reconciler

    def run(self,plan):
        if isinstance(plan,ProfiledOperatorPlan): return self._run_profiled(plan)
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

    def _profiled_admission(self,plan):
        if self.observation_mode=='live':
            if self.clock is not None: raise ValueError('live clock injection is prohibited')
            # Explicitly do NOT pass the retained replay clock/profile_mode.
            admission=revalidate_admission(plan)
        elif self.observation_mode=='synthetic-test':
            if not callable(self.clock): raise ValueError('synthetic test clock must be explicitly injected')
            now=self.clock()
            if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset()!=timezone.utc.utcoffset(now):
                raise ValueError('observation clock must be timezone-aware UTC')
            if any(e.source_scope!='synthetic' for e in plan.profiles.snapshot.evidence):
                raise ValueError('synthetic test profile scope must be explicit')
            admission=revalidate_admission(plan,now=now)
        else: raise ValueError('unsupported observation mode')
        if (admission.status!='ADMITTED' or not admission.structural_admissible
                or admission.technical_feasibility!='FEASIBLE' or not admission.policy_eligible
                or (self.observation_mode=='live' and not admission.execution_ready)):
            raise ValueError('Q8 admission refused: '+('; '.join(admission.deficits) or admission.status))
        return admission

    def _owned_identity(self,part,row,argv,preflight):
        # The actual spawn receipt (or manager's owned row) supplies PID/start.
        if not isinstance(row,dict) or row.get('token')!=self.leases.token:
            raise ValueError('owned process spawn receipt/token mismatch')
        start=row.get('start')
        if type(start) is int and start>=0: start=str(start)
        if type(start) is not str or not start: raise ValueError('owned process opaque spawn start required')
        captured=self.identity_reader(part,row.get('pid'))
        expected=bindings.ProcessIdentity(part.participant_id,part.host_id,part.boot_epoch,
            part.topology_epoch,row.get('pid'),start,part.runtime_executable,part.runtime_sha256,
            argv,freeze(thaw(preflight.observed)['visibility']),part.rpc_endpoint)
        if not isinstance(captured,bindings.ProcessIdentity) or captured!=expected:
            raise ValueError('owned process actual spawn/frozen identity/visibility mismatch')
        return captured

    def _run_profiled(self,plan):
        if plan.strategy_id!='qwen38-q8-fixed/1': raise ValueError('unsupported profiled runtime strategy')
        if self.collector is not None:
            return self._run_profiled_collected(plan)
        if self.binding_transport is None or type(self.binding_transport) is bindings.BindingTransport:
            raise ValueError(bindings.UNSUPPORTED_OBSERVER)
        if not callable(self.identity_reader): raise ValueError('independent identity reader required; no host-query default')
        admission=self._profiled_admission(plan)
        mode=dict(mode=self.observation_mode,clock=self.clock)
        preflights=bindings.preflight_bindings(plan,transport=self.binding_transport,**mode)
        byid={r.participant_id:r for r in preflights}
        spec=llama_cpp_spec(plan)
        client=next(p for p in plan.participants if p.role=='client')
        remote=next(p for p in plan.participants if p.role=='remote')
        for part in (client,remote):
            if Path(part.source_path).name!=plan.model.members[0][0]:
                raise ValueError(part.role+' source_path must name first full GGUF member')
        host,sep,port=remote.rpc_endpoint.rpartition(':')
        if not sep or not host or not port.isdecimal() or int(port)!=remote.port:
            raise ValueError('RPC endpoint must exactly match configured port')
        if client.execution_address==remote.execution_address: raise ValueError('distinct explicit execution addresses required')
        if client.lifecycle_dir==remote.lifecycle_dir: raise ValueError('distinct lifecycle directories required')
        cache_enabled=thaw(plan.strategy_options)['rpc_cache']=='enabled'
        remote_argv=(remote.runtime_executable,*spec.rpc_args,'--host',host,'--port',str(remote.port),
                     *(('--cache',) if cache_enabled else ()))
        client_argv=(spec.executable,*spec.args,'--host','127.0.0.1','--port',str(client.port))
        tunnel=None; error=None; result=None; cleanup_error=None
        try:
            self.leases.acquire(remote.execution_address,remote.lifecycle_dir)
            self.leases.acquire(client.execution_address,client.lifecycle_dir)
            sources={p.participant_id:self.source.verify(p,plan,
                str(Path(self.leases.invocation_dir(p.execution_address))/'fnv-cache')
                if p.role=='remote' and cache_enabled else None) for p in (remote,client)}
            self.leases.port(remote.execution_address,host,remote.port)
            self.leases.port(client.execution_address,'127.0.0.1',client.port)
            rows={remote.participant_id:self.leases.spawn(remote.execution_address,'rpc',list(remote_argv),
                cache=remote.cache_path if cache_enabled else None)}
            rpc_deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                self._live(client,remote,client_started=False)
                ready=self.leases.listening(remote.execution_address,'rpc',host,remote.port)
                self._live(client,remote,client_started=False)
                if time.monotonic()>rpc_deadline: raise TimeoutError('RPC owned listener startup timeout')
                if ready: break
                self.pause(.5)
            rows[client.participant_id]=self.leases.spawn(client.execution_address,'client',list(client_argv))
            # Own the opened tunnel before any health/identity/capture can fail.
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
            observations=[]
            for p in plan.participants:
                name='client' if p.role=='client' else 'rpc'
                argv=client_argv if p.role=='client' else remote_argv
                row=rows[p.participant_id]
                manager_row=self.leases.owned.get(p.execution_address,{}).get(name)
                if row is None: row=manager_row
                elif manager_row is not None and row!=manager_row:
                    raise ValueError('owned process spawn receipt/manager mismatch')
                owned=self._owned_identity(p,row,argv,byid[p.participant_id])
                observations.append(bindings.gather_owned_observation(p,plan,
                    transport=self.binding_transport,owned=owned,owned_argv=argv,
                    invocation_token=self.leases.token,identity_reader=self.identity_reader,**mode))
            actual_bindings=bindings.reconcile_bindings(plan,observations,**mode)
            material=bindings.reconcile_materialization(plan,observations,source_receipts=sources,**mode)
            self._live(client,remote)
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited before request')
            request=dict(plan.request)
            # Recheck plan and retained capture freshness after blocking liveness;
            # no external transport/identity work may intervene before the POST.
            admission=self._profiled_admission(plan)
            actual_bindings=bindings.reconcile_bindings(plan,observations,**mode)
            response=self.http.post(base+'/v1/chat/completions',
                {'messages':[{'role':'user','content':request['prompt']}],
                 'max_tokens':request['max_tokens'],'temperature':request['temperature'],
                 'seed':request['seed'],'stream':False},timeout=900)
            self._live(client,remote)
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited during request')
            choice=response['choices'][0]; text=choice['message']['content']
            if not isinstance(text,str) or not text or not choice['finish_reason'] or not response['id']:
                raise ValueError('incomplete generation response')
            def detached(value): return json.loads(canonical(thaw(asdict(value))))
            result=dict(response_id=response['id'],text=text,finish_reason=choice['finish_reason'],
                tokens=response['usage']['completion_tokens'],plan_id=plan.plan_id,plan_digest=plan.digest,
                selection=plan.selection,admission=detached(admission),verified_backing=sources,
                binding_preflight=[detached(r) for r in preflights],
                observed_bindings=[detached(r) for r in actual_bindings],
                observed_materialization=detached(material),observation_mode=self.observation_mode,
                execution_ready=self.observation_mode=='live' and admission.execution_ready,
                physical_qualified=material.physical_qualified,execution_authorized=False,
                evidence_labels=list(material.evidence_classes),
                nonclaims=['source authentication is not cache consumption or physical placement',
                           'synthetic observations do not qualify physical execution',
                           'no kernel, numerical, memory-fit or performance qualification'])
        except BaseException as exc: error=exc
        finally:
            try:
                if tunnel is not None:
                    if tunnel.poll() is None: tunnel.terminate()
                    try: tunnel.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        tunnel.kill(); tunnel.wait(timeout=5)
            except BaseException as exc:
                cleanup_error=RuntimeError(f'SSH tunnel cleanup failed: {exc}')
                cleanup_error.__cause__=exc
            finally:
                try: self.last_cleanup=self.leases.cleanup()
                except BaseException as exc:
                    failure=RuntimeError(f'incomplete owned cleanup: {exc}')
                    failure.__cause__=cleanup_error or exc; cleanup_error=failure
            if any(row.get('lease')!='released' for row in self.last_cleanup.values()):
                failure=RuntimeError(f'incomplete owned cleanup: {self.last_cleanup}')
                failure.__cause__=cleanup_error; cleanup_error=failure
        if error is not None:
            if cleanup_error is not None: raise error from cleanup_error
            raise error
        if cleanup_error is not None: raise cleanup_error
        result['cleanup']=self.last_cleanup
        return result

    def _run_profiled_collected(self,plan):
        """#302 production path: real collector, phased /2 reconciliation.

        Complete static admission runs over independently collected evidence
        after both owned processes are healthy and before the sole POST; the
        same-request dynamic reconciliation runs after the POST and gates
        output acceptance. A dynamic refusal means execution occurred but the
        output is rejected, which is reported truthfully.
        """
        from .phased_observation import (OwnedSpawnFacts, RequestIdentity,
            reconcile_static, reconcile_dynamic)
        from .profiles import sha256 as _sha256
        admission=self._profiled_admission(plan)
        mode=dict(mode=self.observation_mode,clock=self.clock)
        spec=llama_cpp_spec(plan)
        client=next(p for p in plan.participants if p.role=='client')
        remote=next(p for p in plan.participants if p.role=='remote')
        for part in (client,remote):
            if Path(part.source_path).name!=plan.model.members[0][0]:
                raise ValueError(part.role+' source_path must name first full GGUF member')
        host,sep,port=remote.rpc_endpoint.rpartition(':')
        if not sep or not host or not port.isdecimal() or int(port)!=remote.port:
            raise ValueError('RPC endpoint must exactly match configured port')
        if client.execution_address==remote.execution_address: raise ValueError('distinct explicit execution addresses required')
        if client.lifecycle_dir==remote.lifecycle_dir: raise ValueError('distinct lifecycle directories required')
        cache_enabled=thaw(plan.strategy_options)['rpc_cache']=='enabled'
        options=thaw(plan.strategy_options)
        observer_options=options.get('observer')
        if not isinstance(observer_options,dict):
            raise ValueError('observer deployment options required for the collected /2 path')
        for field in ('manifest_path','executable_path'):
            if not isinstance(observer_options.get(field),str) or not observer_options[field]:
                raise ValueError('observer deployment option '+field+' required')
        remote_argv=(remote.runtime_executable,*spec.rpc_args,'--host',host,'--port',str(remote.port),
                     *(('--cache',) if cache_enabled else ()))
        client_argv=(spec.executable,*spec.args,'--host','127.0.0.1','--port',str(client.port))
        tunnel=None; error=None; result=None; cleanup_error=None
        try:
            self.leases.acquire(remote.execution_address,remote.lifecycle_dir)
            self.leases.acquire(client.execution_address,client.lifecycle_dir)
            sources={p.participant_id:self.source.verify(p,plan,
                str(Path(self.leases.invocation_dir(p.execution_address))/'fnv-cache')
                if p.role=='remote' and cache_enabled else None) for p in (remote,client)}
            self.leases.port(remote.execution_address,host,remote.port)
            self.leases.port(client.execution_address,'127.0.0.1',client.port)
            invocation=self.leases.token
            export_dirs={
                remote.participant_id:str(Path(self.leases.invocation_dir(remote.execution_address))/'exports-rpc'),
                client.participant_id:str(Path(self.leases.invocation_dir(client.execution_address))/'exports-client')}
            rows={remote.participant_id:self.leases.spawn(remote.execution_address,'rpc',list(remote_argv),
                cache=remote.cache_path if cache_enabled else None,export=export_dirs[remote.participant_id])}
            rpc_deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                self._live(client,remote,client_started=False)
                ready=self.leases.listening(remote.execution_address,'rpc',host,remote.port)
                self._live(client,remote,client_started=False)
                if time.monotonic()>rpc_deadline: raise TimeoutError('RPC owned listener startup timeout')
                if ready: break
                self.pause(.5)
            rows[client.participant_id]=self.leases.spawn(client.execution_address,'client',list(client_argv),
                export=export_dirs[client.participant_id])
            # Own the opened tunnel before any health/identity/capture can fail.
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
            # Complete static admission before the sole POST: independently
            # collected identity/build/source joins for every participant.
            static_evidence=[]
            for p in plan.participants:
                row=rows[p.participant_id]
                start=row.get('start')
                if type(start) is int and start>=0: start=str(start)
                spawn=OwnedSpawnFacts(p.participant_id,row['pid'],start,invocation)
                argv=client_argv if p.role=='client' else remote_argv
                evidence=self.collector.collect_static(p,spawn,
                    observer_options['manifest_path'],observer_options['executable_path'],
                    _sha256(sources[p.participant_id]),expected_argv=argv)
                static_evidence.append(evidence)
            static_receipt=self.static_reconciler(plan,static_evidence,sources,**mode)
            self._live(client,remote)
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited before request')
            request=dict(plan.request)
            request_nonce=secrets.token_hex(16)
            request_identity=RequestIdentity(invocation_token=invocation,request_nonce=request_nonce)
            # Recheck plan freshness after blocking liveness/tunnel work,
            # immediately before the sole POST; no transport work intervenes.
            admission=self._profiled_admission(plan)
            response=self.http.post(base+'/v1/chat/completions',
                {'messages':[{'role':'user','content':request['prompt']}],
                 'max_tokens':request['max_tokens'],'temperature':request['temperature'],
                 'seed':request['seed'],'stream':False},timeout=900)
            self._live(client,remote)
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited during request')
            choice=response['choices'][0]; text=choice['message']['content']
            if not isinstance(text,str) or not text or not choice['finish_reason'] or not response['id']:
                raise ValueError('incomplete generation response')
            # The response arrived; from here a failure means the request
            # executed but its output is REJECTED, which is raised truthfully.
            result_choice=choice; result_text=text; result_response=response
            # Same-request dynamic acceptance: the retained overlay exports
            # its terminal envelope at owned-process termination, so the
            # controller tears down the tunnel and owned processes first,
            # then collects and reconciles before accepting output.
            if tunnel.poll() is None: tunnel.terminate()
            try: tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill(); tunnel.wait(timeout=5)
            owned_cleanup=self.leases.cleanup()
            self.last_cleanup=owned_cleanup
            if any(row.get('lease')!='released' for row in owned_cleanup.values()):
                raise RuntimeError(f'incomplete owned cleanup: {owned_cleanup}')
            dynamic_evidence=[]
            for p in plan.participants:
                row=rows[p.participant_id]
                start=row.get('start')
                if type(start) is int and start>=0: start=str(start)
                spawn=OwnedSpawnFacts(p.participant_id,row['pid'],start,invocation)
                dynamic_evidence.append(self.collector.collect_dynamic(p,spawn,
                    export_dirs[p.participant_id],plan.digest,invocation,
                    NATIVE_LABELS['client' if p.role=='client' else 'remote']))
            # Bind the request identity to OBSERVED native facts: the task id
            # and graph generations come from the collected evidence, never
            # from the controller's guesses. The HTTP response id binds the
            # output; the native task id binds the request.
            client_evidence=next(e for e in dynamic_evidence
                if e.participant_id==client.participant_id)
            facts=thaw(client_evidence.observation.facts)
            native_tasks=facts.get('tasks') or []
            if len(native_tasks)!=1:
                raise ValueError('dynamic reconciliation: request task binding ambiguous: '
                                 'expected exactly one observed native task for this request')
            request_identity=RequestIdentity(invocation_token=invocation,
                request_nonce=request_nonce,
                task_id=str(native_tasks[0]['task_id']),
                response_id=str(result_response['id']))
            dynamic_receipt=self.dynamic_reconciler(plan,static_receipt,dynamic_evidence,
                request_identity,**mode)
            # Recheck evidence freshness after blocking collection work.
            admission=self._profiled_admission(plan)
            def detached(value): return json.loads(canonical(thaw(asdict(value))))
            response=result_response; choice=result_choice; text=result_text
            result=dict(response_id=response['id'],text=text,finish_reason=choice['finish_reason'],
                tokens=response['usage']['completion_tokens'],plan_id=plan.plan_id,plan_digest=plan.digest,
                selection=plan.selection,admission=detached(admission),verified_backing=sources,
                static_receipt=detached(static_receipt),dynamic_receipt=detached(dynamic_receipt),
                observation_mode=self.observation_mode,
                execution_ready=self.observation_mode=='live' and admission.execution_ready,
                physical_qualified=static_receipt.physical_qualified,
                execution_authorized=False,
                nonclaims=['source authentication is not cache consumption or physical placement',
                           'dynamic acceptance is not execution authorization; output accepted, execution already occurred',
                           'synthetic full-Q8 scenarios remain synthetic; no live capability evidence'])
        except BaseException as exc: error=exc
        finally:
            try:
                if tunnel is not None:
                    if tunnel.poll() is None: tunnel.terminate()
                    try: tunnel.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        tunnel.kill(); tunnel.wait(timeout=5)
            except BaseException as exc:
                cleanup_error=RuntimeError(f'SSH tunnel cleanup failed: {exc}')
                cleanup_error.__cause__=exc
            finally:
                try:
                    # A completed mid-run cleanup released every lease; the
                    # idempotent second pass returns {} and must NOT erase the
                    # authoritative receipt.
                    repeat=self.leases.cleanup()
                    if repeat:
                        self.last_cleanup=repeat
                except BaseException as exc:
                    failure=RuntimeError(f'incomplete owned cleanup: {exc}')
                    failure.__cause__=cleanup_error or exc; cleanup_error=failure
            if any(row.get('lease')!='released' for row in self.last_cleanup.values()):
                failure=RuntimeError(f'incomplete owned cleanup: {self.last_cleanup}')
                failure.__cause__=cleanup_error; cleanup_error=failure
        if error is not None:
            if cleanup_error is not None: raise error from cleanup_error
            raise error
        if cleanup_error is not None: raise cleanup_error
        result['cleanup']=self.last_cleanup
        return result

    def _live(self,client,remote,client_started=True):
        if not self.leases.alive(remote.execution_address,'rpc'): raise RuntimeError('remote participant lost')
        if client_started and not self.leases.alive(client.execution_address,'client'):
            raise RuntimeError('client participant lost')


def run_config(path):
    plan=build_plan(load_config(path))
    manager=LeaseManager(SSHTransport(),secrets.token_hex(16))
    observer=None
    if isinstance(plan,ProfiledOperatorPlan):
        options=thaw(plan.strategy_options)
        observer=options.get('observer') if isinstance(options,dict) else None
    if observer:
        # #302 production collected /2 path: real SSH collector, independent
        # /proc identity reader and phased reconciliation through ordinary
        # run_config. Legacy /1 observer wiring stays unchanged.
        from .native_observer.collector import NativeObserverCollector
        from .phased_observation import reconcile_static, reconcile_dynamic
        runner=OperatorRunner(SSHSourceTransport(),manager,JSONHTTP(),ssh_tunnel,
            collector=NativeObserverCollector(),static_reconciler=reconcile_static,
            dynamic_reconciler=reconcile_dynamic)
    else:
        runner=OperatorRunner(SSHSourceTransport(),manager,JSONHTTP(),ssh_tunnel)
    return runner.run(plan)
