"""One fixed-plan ordinary generation with verified sources and bounded ownership."""
from __future__ import annotations
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
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


def _model_file_type(plan):
    """general.file_type from the plan's authenticated model metadata."""
    from .source import q8_source_payload
    payload = q8_source_payload(plan)
    rows = payload.get('metadata', {}).get('model_metadata')
    if isinstance(rows, list):
        for key, value in rows:
            if key == 'general.file_type':
                return value
    raise ValueError('plan model metadata lacks general.file_type')


def _client_host_threads(guard, client):
    """Mirror the pinned server's -t default ON THE CLIENT HOST: observe the
    client's own online CPU count through the guard's read-only channel
    (postprocess_cpu_params -> common_cpu_get_num_math -> sysconf), never the
    controller's."""
    try:
        raw = guard.commands.run(client.execution_address,
            ['getconf', 'NPROCESSORS_ONLN'])
        return int(raw.strip())
    except Exception:
        raise ValueError('client host thread count unobservable; refusing '
                         'to guess a thread setting')


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
            if projected['source_contract']==source.SELECTIVE_CONTRACT and part.role=='remote':
                payload=source.assigned_verification_envelope(projected,selected,helper)
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
        # #313 durable evidence retention read transport (experimental path
        # only); None on ordinary paths.
        self.evidence_transport=None
        # #302 real collector path: production wiring supplies these through
        # run_config; tests inject recording doubles.
        self.collector=collector
        self.static_reconciler=static_reconciler
        self.dynamic_reconciler=dynamic_reconciler
        # Offline synthetic-correlation seam only: tests may pin the request
        # nonce so labeled synthetic evidence can carry the same correlation
        # key; production leaves this None and generates a fresh secret.
        self.request_nonce=None
        # #313 durable evidence retention (experimental path only): set by
        # the experimental driver before execution; None on every ordinary
        # path, which stays byte-for-byte unchanged in behavior.
        self.evidence=None

    def _verify_profiled_sources(self,plan,client,remote):
        """Ordinary owned startup's sole backing admission, before RPC spawn."""
        options=thaw(plan.strategy_options)
        cache=options['rpc_cache']=='enabled'
        sources={p.participant_id:self.source.verify(p,plan,
            str(Path(self.leases.invocation_dir(p.execution_address))/'fnv-cache')
            if p.role=='remote' and cache else None) for p in (remote,client)}
        from .assigned_backing import CONTRACT
        from .qwen_q8 import q8_participant_build_backend
        if options['source_contract']==CONTRACT:
            if self.collector is None: raise ValueError('selective backing requires per-role native build collector')
            observer=options['observer']
            # The remote role's build backend follows the plan's explicit
            # selection; the client/loader role stays on the reviewed CPU build.
            for p in (remote,client):
                if 'assigned_guard_path' not in sources[p.participant_id]: raise ValueError('selective backing upload guard missing')
                self.collector.collect_build(p,observer[p.role+'_manifest_path'],
                    observer[p.role+'_executable_path'],backend=q8_participant_build_backend(plan,p),
                    **({'build_pair':options['build_pair']} if 'build_pair' in options else {}))
        return sources

    def _spawn_profiled_rpc(self,plan,remote,argv,sources,export=None,*,name='rpc',binding_id=None):
        options=thaw(plan.strategy_options)
        return self.leases.spawn(remote.execution_address,name,list(argv),
            cache=remote.cache_path if options['rpc_cache']=='enabled' else None,
            **({'export':export} if export else {}),**self._assigned_spawn(plan,remote,sources,binding_id=binding_id))

    def _assigned_spawn(self,plan,part,sources,*,binding_id=None):
        from .assigned_backing import CONTRACT
        if thaw(plan.strategy_options)['source_contract']==CONTRACT:
            receipt=sources[part.participant_id]
            if binding_id is not None:
                guards=receipt.get('assigned_guard_paths')
                if not isinstance(guards,dict) or set(guards)!={
                        thaw(plan.strategy_options)['bindings']['remote_gpu0'],
                        thaw(plan.strategy_options)['bindings']['remote_gpu1']}:
                    raise ValueError('two-gpu requires exact per-binding assigned guards')
                return dict(assigned=guards[binding_id])
            return dict(assigned=receipt['assigned_guard_path'])
        return {}

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
        if plan.selection=='two-gpu':
            raise ValueError('two-gpu diagnostic requires the collected observer path')
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
            if (part.role=='client' or thaw(plan.strategy_options)['source_contract']=='full-source-both-hosts/1') and Path(part.source_path).name!=plan.model.members[0][0]:
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
            sources=self._verify_profiled_sources(plan,client,remote)
            self.leases.port(remote.execution_address,host,remote.port)
            self.leases.port(client.execution_address,'127.0.0.1',client.port)
            rows={remote.participant_id:self._spawn_profiled_rpc(plan,remote,remote_argv,sources)}
            rpc_deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                self._live(client,remote,client_started=False)
                ready=self.leases.listening(remote.execution_address,'rpc',host,remote.port)
                self._live(client,remote,client_started=False)
                if time.monotonic()>rpc_deadline: raise TimeoutError('RPC owned listener startup timeout')
                if ready: break
                self.pause(.5)
            rows[client.participant_id]=self.leases.spawn(client.execution_address,'client',list(client_argv),**self._assigned_spawn(plan,client,sources))
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

    def _run_two_gpu_diagnostic(self,plan):
        """Run the bounded two-listener diagnostic without accepting output.

        Pinned RPC v7 serves one connection at a time, so the two CUDA banks
        use two owned server processes/listeners.  This path retains the raw
        response and exact process/export receipts for review, but deliberately
        does not call the ordinary /2 dynamic reconciler or qualify the output.
        """
        admission=self._profiled_admission(plan)
        return self._execute_two_gpu_diagnostic(plan,admission)

    def _execute_two_gpu_diagnostic(self,plan,admission,*,campaign_guard=None):
        """Execute after either ordinary admission or an explicit experiment guard.

        The experimental caller supplies the unchanged blocked admission and a
        guard that independently enforces its one-shot external envelope.
        """
        from .phased_observation import OwnedSpawnFacts
        spec=llama_cpp_spec(plan)
        from .qwen_q8 import q8_rpc_processes
        rpc_processes=q8_rpc_processes(plan)
        if len(rpc_processes)!=2:
            raise ValueError('two-gpu diagnostic requires exactly two RPC processes')
        client=next(p for p in plan.participants if p.role=='client')
        remote=next(p for p in plan.participants if p.role=='remote')
        if client.execution_address==remote.execution_address:
            raise ValueError('distinct explicit execution addresses required')
        options=thaw(plan.strategy_options)
        if options['source_contract']!='coordinator-full-source/participant-assigned-rpc-backing/1':
            raise ValueError('two-gpu diagnostic requires assigned-only worker backing')
        cache_enabled=options['rpc_cache']=='enabled'
        processes=[]
        for process in rpc_processes:
            host,sep,port=process.endpoint.rpartition(':')
            if not sep or not host or not port.isdecimal():
                raise ValueError('two-gpu diagnostic RPC endpoint must be host:port')
            argv=(remote.runtime_executable,'--device',process.native_selector,
                  '--host',host,'--port',port,*(('--cache',) if cache_enabled else ()))
            processes.append((process,host,int(port),argv))
        client_argv=(spec.executable,*spec.args,'--host','127.0.0.1','--port',str(client.port))
        tunnel=None; error=None; result=None; cleanup_error=None
        rows={}; identities={}; export_dirs={}
        evidence_store=self.evidence
        evidence_entries=[]
        try:
            if campaign_guard is not None:
                campaign_guard.begin(plan,spec,client,remote)
            self.leases.acquire(remote.execution_address,remote.lifecycle_dir)
            self.leases.acquire(client.execution_address,client.lifecycle_dir)
            sources=self._verify_profiled_sources(plan,client,remote)
            if campaign_guard is not None:
                campaign_guard.sources_verified(plan,sources)
            hot_spec_path=None
            if getattr(campaign_guard,'hot_request',None) is not None:
                from .hot_experiment import stage_hot_experts
                hot_spec_path,campaign_guard.hot_record=stage_hot_experts(
                    self,campaign_guard,plan,sources,client,remote)
                campaign_guard.phase='load'
            guards=sources[remote.participant_id].get('assigned_guard_paths')
            wanted={p.binding_id for p,_,_,_ in processes}
            if not isinstance(guards,dict) or set(guards)!=wanted or len(set(guards.values()))!=2:
                raise ValueError('two-gpu diagnostic requires two distinct per-binding assigned guards')
            for process,host,port,argv in processes:
                self.leases.port(remote.execution_address,host,port)
                export=str(Path(self.leases.invocation_dir(remote.execution_address))/('exports-'+process.name))
                export_dirs[process.name]=export
                log_path=str(Path(self.leases.invocation_dir(
                    remote.execution_address))/(process.name+'.log'))
                # Register the attempted role + artifact paths BEFORE the
                # launch is dispatched: if the process starts but its spawn
                # reply is lost, cleanup still stops the leases and
                # retention still attempts these known paths; the PID/start
                # identity stays honestly unknown (None), never fabricated.
                if evidence_store is not None:
                    evidence_store.register_attempt(process.name,
                        remote.execution_address,export,log_path)
                rows[process.name]=self._spawn_profiled_rpc(plan,remote,argv,sources,export,
                    name=process.name,binding_id=process.binding_id)
                if evidence_store is not None:
                    evidence_store.register_process(process.name,remote.execution_address,
                        rows[process.name]['pid'],str(rows[process.name]['start']))
                    evidence_entries.append(dict(name=process.name,
                        address=remote.execution_address,export_dir=export,
                        log_path=log_path,
                        pid=rows[process.name]['pid'],
                        start=str(rows[process.name]['start'])))
                if campaign_guard is not None: campaign_guard.process_started(rows)
            self.leases.port(client.execution_address,'127.0.0.1',client.port)
            deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                if campaign_guard is not None: campaign_guard.checkpoint()
                ready=True
                for process,host,port,_ in processes:
                    if not self.leases.alive(remote.execution_address,process.name):
                        raise RuntimeError('two-gpu RPC process lost: '+process.name)
                    ready = self.leases.listening(remote.execution_address,process.name,host,port) and ready
                if ready: break
                if time.monotonic()>deadline:
                    raise TimeoutError('two-gpu owned RPC listeners startup timeout')
                self.pause(.5)
            # Independently bind each listener PID/start/executable/argv before
            # the client can connect.  The physical_id is the freshly admitted
            # profile identity; later hardware evidence must join it to UUID.
            remote_bindings={b.binding_id:b for b in remote.bindings}
            process_receipts=[]
            for process,host,port,argv in processes:
                row=rows[process.name]
                start=str(row['start'])
                proxy=replace(remote,participant_id=remote.participant_id+'-'+process.name,
                              rpc_endpoint=process.endpoint,port=port)
                identity=self.collector.identity_reader.read(proxy,row['pid'],
                    expected_executable=remote.runtime_executable,
                    expected_sha256=remote.runtime_sha256,expected_argv=argv)
                if identity.pid!=row['pid'] or identity.start!=start:
                    raise ValueError('two-gpu owned RPC identity mismatch: '+process.name)
                identities[process.name]=(proxy,identity)
                binding=remote_bindings[process.binding_id]
                process_receipts.append(dict(name=process.name,endpoint=process.endpoint,
                    binding_id=process.binding_id,native_selector=process.native_selector,
                    physical_id=binding.physical_id,pid=row['pid'],start=start,
                    executable_sha256=remote.runtime_sha256,assigned_guard=guards[process.binding_id]))
            client_export=str(Path(self.leases.invocation_dir(client.execution_address))/'exports-client')
            export_dirs['client']=client_export
            client_log=str(Path(self.leases.invocation_dir(
                client.execution_address))/'client.log')
            # Same pre-dispatch registration for the client launch.
            if evidence_store is not None:
                evidence_store.register_attempt('client',
                    client.execution_address,client_export,client_log)
            rows['client']=self.leases.spawn(client.execution_address,'client',list(client_argv),
                export=client_export,**self._assigned_spawn(plan,client,sources),
                **({'hot_spec':hot_spec_path} if hot_spec_path is not None else {}))
            if evidence_store is not None:
                evidence_store.register_process('client',client.execution_address,
                    rows['client']['pid'],str(rows['client']['start']))
                evidence_entries.append(dict(name='client',
                    address=client.execution_address,export_dir=client_export,
                    log_path=client_log,
                    pid=rows['client']['pid'],
                    start=str(rows['client']['start'])))
            if campaign_guard is not None: campaign_guard.process_started(rows)
            opened=self.tunnel_factory(client.execution_address,client.port)
            tunnel,local_port=opened if isinstance(opened,tuple) else (opened,client.port)
            base=f'http://127.0.0.1:{local_port}'
            deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                if campaign_guard is not None: campaign_guard.checkpoint()
                for process,_,_,_ in processes:
                    if not self.leases.alive(remote.execution_address,process.name):
                        raise RuntimeError('two-gpu RPC process lost: '+process.name)
                if not self.leases.alive(client.execution_address,'client'):
                    raise RuntimeError('client participant lost')
                if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited during startup')
                try:
                    if self.http.get(base+'/health',timeout=2).get('status')=='ok': break
                except (OSError,ValueError,urllib.error.URLError): pass
                if time.monotonic()>deadline: raise TimeoutError('client startup health timeout')
                self.pause(.5)
            if campaign_guard is not None and hasattr(campaign_guard,'session'):
                result=self._execute_diagnostic_session(plan,campaign_guard,base,
                    rows,process_receipts,sources,tunnel,client,remote,processes)
            else:
                campaign_before=None
                if campaign_guard is not None:
                    campaign_before=campaign_guard.before_request(plan,rows,process_receipts,sources)
                request=dict(plan.request)
                if campaign_guard is not None: campaign_guard.request_started()
                response=self.http.post(base+'/v1/chat/completions',
                    {'messages':[{'role':'user','content':request['prompt']}],
                     'max_tokens':request['max_tokens'],'temperature':request['temperature'],
                     'seed':request['seed'],'stream':False},
                    timeout=(campaign_guard.request_timeout_seconds() if campaign_guard is not None else 900))
                if campaign_guard is not None:
                    campaign_guard.raw_response=response
                if evidence_store is not None:
                    # Preserve the complete response JSON immediately after
                    # receipt, before checkpoint/validation/observation can
                    # fail; never allowed to disturb execution or cleanup.
                    try: evidence_store.save_response(response)
                    except BaseException: pass
                if campaign_guard is not None:
                    campaign_guard.checkpoint()
                revalidate=getattr(self.source,'revalidate_source_identity',None)
                if revalidate is not None: revalidate()
                choice=response['choices'][0]; output=choice['message']['content']
                if not isinstance(output,str) or not output or not choice['finish_reason'] or not response['id']:
                    raise ValueError('incomplete diagnostic generation response')
                result=dict(schema='q8-two-gpu-diagnostic/1',status='EXECUTED-OUTPUT-UNACCEPTED',
                    plan_id=plan.plan_id,plan_digest=plan.digest,selection=plan.selection,
                    response_id=response['id'],raw_output=output,
                    raw_output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                    finish_reason=choice['finish_reason'],tokens=response['usage']['completion_tokens'],
                    rpc_processes=process_receipts,verified_backing=sources,
                    output_accepted=False,physical_qualified=False,execution_authorized=False,
                    nonclaims=['diagnostic response is retained but not accepted by the ordinary /2 observer',
                               'endpoint/PID/device-selector binding is not GPU residency or UUID execution proof',
                               'full coordinator working-set fit remains unqualified'])
                if campaign_guard is not None:
                    campaign_guard.execution_result=result
                    try:
                        result['campaign_observation']={
                            'before_request':campaign_before,
                            'after_request':campaign_guard.after_request(
                                plan,rows,process_receipts,sources,response)}
                    except BaseException as exc:
                        result['status']='EXECUTED-OBSERVATION-REFUSED'
                        result['observation_refusal']=str(exc)
        except BaseException as exc: error=exc
        finally:
            if campaign_guard is not None:
                try: campaign_guard.stop_monitor()
                except BaseException as exc: cleanup_error=exc
            try:
                if tunnel is not None:
                    if tunnel.poll() is None: tunnel.terminate()
                    try: tunnel.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        tunnel.kill(); tunnel.wait(timeout=5)
            except BaseException as exc:
                cleanup_error=RuntimeError(f'SSH tunnel cleanup failed: {exc}')
            finally:
                try: self.last_cleanup=self.leases.cleanup()
                except BaseException as exc:
                    cleanup_error=RuntimeError(f'incomplete owned cleanup: {exc}')
        if error is None:
            try:
                evidence=[]
                for process,_,_,_ in processes:
                    proxy,_=identities[process.name]; row=rows[process.name]
                    spawn=OwnedSpawnFacts(proxy.participant_id,row['pid'],str(row['start']),self.leases.token)
                    self.collector.await_terminal_export(proxy,spawn,export_dirs[process.name],NATIVE_LABELS['remote'])
                    item=self.collector.collect_dynamic(proxy,spawn,export_dirs[process.name],
                        plan.digest,self.leases.token,NATIVE_LABELS['remote'])
                    events=[thaw(event)['event'] for event in item.observation.sequence]
                    if 'rpc_server_command' not in events:
                        raise ValueError('two-gpu diagnostic listener served no observed RPC command: '+process.name)
                    evidence.append(dict(name=process.name,terminal_digest=item.observation.terminal_digest,
                                         event_count=item.observation.event_count,
                                         rpc_commands=events.count('rpc_server_command')))
                result['listener_observations']=evidence
            except BaseException as exc:
                # Execution already happened.  Retain the raw response and
                # report the observation refusal without converting it into
                # accepted output or discarding the bounded diagnostic.
                if (campaign_guard is not None and hasattr(campaign_guard,'session')
                        and isinstance(exc,(KeyboardInterrupt,SystemExit,TimeoutError))):
                    # Preserve terminal observer interrupts/deadlines, but run
                    # aggregate cleanup and retention below before re-raising.
                    error=exc
                else:
                    result['status']='EXECUTED-OBSERVATION-REFUSED'
                    result['observation_refusal']=str(exc)
        if any(row.get('lease')!='released' for row in self.last_cleanup.values()):
            cleanup_error=RuntimeError(f'incomplete owned cleanup: {self.last_cleanup}')
        if campaign_guard is not None:
            try: campaign_guard.after_cleanup(self.last_cleanup)
            except BaseException as exc:
                cleanup_error=RuntimeError(f'experimental supervision cleanup failed: {exc}')
        if campaign_guard is not None and hasattr(campaign_guard,'session'):
            campaign_guard.cleanup_error=None if cleanup_error is None else str(cleanup_error)
        # Retention is strictly LAST: acknowledged processes, ambiguous
        # spawns (stopped by after_cleanup -> stop_units), leases, the SSH
        # tunnel and aggregate slices are all stopped before any evidence
        # byte is collected, so slow or failed retention can never defer an
        # owned stop.  Best-effort and bounded; an honest partial record is
        # recorded and never masks the campaign's own result or error.
        if evidence_store is not None:
            try:
                # Bind retention to the campaign's EXISTING absolute
                # deadline: probes clamp to the remaining budget (minus a
                # manifest reserve) and stop once it expires -- retention
                # never grants itself a fresh window after the campaign
                # budget is gone.  Owned-process shutdown has already run.
                if (campaign_guard is not None
                        and campaign_guard.execute_deadline is not None):
                    evidence_store.begin_collection_budget(
                        campaign_guard.execute_deadline)
                evidence_store.collect_processes(evidence_entries,
                    self.evidence_transport)
            except BaseException as exc:
                evidence_store._event('collect-wrapper-failed',exc)
        if error is not None:
            if cleanup_error is not None: raise error from cleanup_error
            raise error
        if cleanup_error is not None: raise cleanup_error
        result['cleanup']=self.last_cleanup
        return result

    def _execute_diagnostic_session(self,plan,guard,base,rows,process_receipts,
                                    sources,tunnel,client,remote,processes):
        """Reuse the already loaded owned server, with no hidden POST or retry."""
        from .q8_session import ENDPOINT, response_metrics
        store=self.evidence
        guard.setup['load_ended_monotonic']=guard.clock()
        demand_pending=getattr(guard,'demand_profile',None) is not None
        result=dict(status='EXECUTED-OUTPUT-UNACCEPTED',plan_id=plan.plan_id,
            plan_digest=plan.digest,selection=plan.selection,rpc_processes=process_receipts,
            verified_backing=sources,requests=guard.request_records,
            output_accepted=False,physical_qualified=False,execution_authorized=False,
            nonclaims=['diagnostic responses are not accepted by the ordinary /2 observer',
                'PID/UUID residency, graph submission and utilization are not kernel execution proof',
                'nonstreaming wall time is not TTFT; correctness is not evaluated'])
        guard.execution_result=result
        if getattr(guard,'hot_request',None) is not None:
            from .hot_experiment import tokenize_hot_session
            result['actual_tokenizer']=tokenize_hot_session(self,guard,plan,base,client)
        for index,request in enumerate(guard.session.payload()['requests'],1):
            guard.phase='request'; guard.phase_index=index
            body=request['body']
            record=dict(index=index,warmup=request['warmup'],measured=not request['warmup'],
                request_sha256=hashlib.sha256(canonical(body)).hexdigest(),body=body,
                endpoint=ENDPOINT,status='NOT-STARTED',started_monotonic=None,
                ended_monotonic=None,started_at=None,ended_at=None,finish_reason=None,
                metrics=None,correctness='NOT-EVALUATED',
                prompt_cache=dict(cache_prompt=body['cache_prompt'],reported_tokens_cached=None,
                    reported_reused_prompt_tokens=None,
                    interpretation='reuse permitted' if body['cache_prompt'] else 'uncached prefill requested',
                    uncertainty='timings.cache_n reports reused prefill; tokens_cached alone is not reuse proof; absent cache_n means unknown'))
            # Pre-request safety checks are not observer completeness checks.
            # Any failure here stops the sequence without consuming another POST.
            guard.before_request(plan,rows,process_receipts,sources)
            for process,_,_,_ in processes:
                if not self.leases.alive(remote.execution_address,process.name):
                    raise RuntimeError('two-gpu RPC process lost: '+process.name)
            if not self.leases.alive(client.execution_address,'client'):
                raise RuntimeError('client participant lost')
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited before request')
            revalidate=getattr(self.source,'revalidate_source_identity',None)
            if revalidate is not None: revalidate()
            guard.checkpoint()
            record.update(status='STARTED',started_monotonic=guard.clock(),
                          started_at=datetime.now(timezone.utc).isoformat())
            guard.request_records.append(record)
            prefix=f'request-{index:02d}'
            try:
                if store is None or not store.save_session_json(prefix+'-started.json',record):
                    raise RuntimeError('session request metadata retention failed')
                timeout=guard.request_timeout_seconds()
                guard.request_started()
                # Decode anew so a transport cannot mutate the frozen record.
                payload=guard.session.payload()['requests'][index-1]['body']
                record['http_started_monotonic']=guard.clock()
                record['http_started_at']=datetime.now(timezone.utc).isoformat()
                response=self.http.post(base+ENDPOINT,payload,timeout=timeout)
                record.update(ended_monotonic=guard.clock(),
                              ended_at=datetime.now(timezone.utc).isoformat(),status='RECEIVED')
                guard.raw_response=response
                # FIRST operation on the received value is durable retention.
                # No validation, observer or liveness call may precede this.
                if not store.save_session_json(prefix+'-response.json',response):
                    raise RuntimeError('complete session response retention failed')
                record['wall_seconds']=record['ended_monotonic']-record['http_started_monotonic']
                if not store.save_session_json(prefix+'-received.json',record):
                    raise RuntimeError('session receipt metadata retention failed')
                if not isinstance(response,dict):
                    raise ValueError('incomplete native diagnostic generation response')
                record['metrics']=response_metrics(response)
                record['prompt_cache']['reported_tokens_cached']=response.get('tokens_cached')
                record['prompt_cache']['reported_reused_prompt_tokens']=record['metrics']['cache_n']
                record['finish_reason']=response.get('stop_type')
                output=response.get('content')
                if (not isinstance(output,str) or not output or response.get('stop') is not True
                        or not record['finish_reason'] or response.get('error')):
                    raise ValueError('incomplete native diagnostic generation response')
                record.update(status='COMPLETED',raw_output_sha256=hashlib.sha256(output.encode()).hexdigest())
                # Completion is an HTTP fact, independent of later safety,
                # observer completeness or correctness acceptance.
                guard.checkpoint()
                for process,_,_,_ in processes:
                    if not self.leases.alive(remote.execution_address,process.name):
                        raise RuntimeError('two-gpu RPC process lost: '+process.name)
                if not self.leases.alive(client.execution_address,'client'):
                    raise RuntimeError('client participant lost')
                if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited during request')
                if revalidate is not None: revalidate()
                # This hook checks cgroup/OOM/allocator/host/GPU safety, not
                # terminal native event completeness: failures MUST stop.
                guard.after_request(plan,rows,process_receipts,sources,response)
            except BaseException as exc:
                if record['status']!='COMPLETED':
                    record['status']='INTERRUPTED' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'FAILED'
                record['failure']=dict(type=type(exc).__name__,reason=str(exc))
                raise
            finally:
                if record['ended_monotonic'] is None:
                    record.update(ended_monotonic=guard.clock(),
                                  ended_at=datetime.now(timezone.utc).isoformat())
                if store is not None:
                    saved=store.save_session_json(prefix+'-final.json',record)
                    # Do not replace an in-flight execution error/interrupt.
                    if not saved and 'failure' not in record:
                        raise RuntimeError('session final request metadata retention failed')
        guard.phase='cleanup'; guard.phase_index=None
        if demand_pending:
            # The pinned RPC server serves ONE connection synchronously
            # (ggml-rpc.cpp accept loop). While the ordinary session client
            # is loaded it owns the workers' connections, so a second client
            # would block forever at device registration. Run the capture
            # only AFTER the frozen session's requests, with the ordinary
            # client stopped first; the workers stay up and their validated
            # assigned cache then serves the demand client's load (the
            # existing #311 restart-reuse path, zero re-transfer).
            # The handoff runs as ONE locked transition on the campaign
            # guard: the ordinary client leaves monitoring and lease
            # ownership only after its stop is confirmed, so a concurrent
            # monitor tick can never inspect the removed client (KeyError)
            # or an unsupervised worker.
            guard.retire_client_for_demand(client.execution_address,rows['client'])
            del rows['client']  # runner-local bookkeeping; guard owns the rest
            if tunnel is not None and tunnel.poll() is None:
                tunnel.terminate()
            demand_record=self._run_demand_capture(plan,guard,rows,sources,
                client,remote,processes,store)
            if demand_record is not None:
                result['demand_capture']=demand_record
        return result

    def _run_demand_capture(self,plan,guard,rows,sources,client,remote,processes,store):
        """#314 opt-in native demand capture beside the loaded guarded session.

        Reuses this invocation's owned workers (already listening), assigned
        backing, supervision aggregates and the campaign deadline. The demand
        client is a SEPARATELY reviewed CPU successor identity: its digest must
        equal its reviewed successor manifest, never a caller-provided bypass.
        The capture prompt equals its frozen measured request prompt, so warmup
        and measured requests cannot mix.
        """
        from .q8_demand import demand_client_argv
        profile=guard.demand_profile
        # Keep this same record through admission, dispatch and readback.
        # The outer campaign retains execution_result even when any step
        # raises; report() then attaches the real terminal cause.
        record=dict(enabled=True,attempted=False,status='NOT-STARTED',
                    bound_request=profile.request_index)
        guard.execution_result['demand_capture']=record
        options=thaw(plan.strategy_options)
        # Identity admission: read the reviewed successor manifest through the
        # same collector transport used for the observer builds; it returns the
        # PARSED object. The executable bytes are then read and hashed.
        from .native_observer.collector import SSHCollectorTransport
        transport=SSHCollectorTransport()
        try:
            manifest=transport.read_json(client.execution_address,
                profile.client_manifest_path,
                max_bytes=SSHCollectorTransport.MANIFEST_MAX_BYTES)
        except Exception as exc:
            raise ValueError('demand client manifest unreadable: '+str(exc)) from exc
        if not isinstance(manifest,dict):
            raise ValueError('demand client manifest is not a JSON object')
        from .phased_observation import parse_build_manifest
        identity=parse_build_manifest(manifest)
        if identity.executable_sha256!=profile.client_sha256:
            raise ValueError('demand client digest does not match its manifest')
        # RPC v7 + optimized-CPU option parity with the reviewed client rows.
        from .assigned_backing import optimized_cpu_identities
        reviewed=optimized_cpu_identities()['client']
        if (tuple(identity.build_options)!=tuple(reviewed.build_options)
                or identity.patch_sha256!=reviewed.patch_sha256
                or identity.base_revision!=reviewed.base_revision):
            raise ValueError('demand client is not the reviewed optimized CPU successor shape')
        executable=transport.read_bytes(client.execution_address,
            profile.client_executable_path,
            max_bytes=SSHCollectorTransport.EXECUTABLE_MAX_BYTES)
        if hashlib.sha256(executable).hexdigest()!=profile.client_sha256:
            raise ValueError('demand client executable bytes do not match its digest')
        # The measured request's prompt IS the capture prompt (validated at
        # session load); stage it on the CLIENT host inside the owned
        # invocation directory through the same channel that spawns there.
        invocation=self.leases.invocation_dir(client.execution_address)
        prompt_remote=str(Path(invocation)/'demand-prompt.txt')
        output_remote=str(Path(invocation)/'demand-profile.json')
        log_remote=str(Path(invocation)/'demand.log')
        # Fresh-path enforcement happens on the client host at spawn time
        # (the lifecycle transport refuses an existing record/log), and the
        # CLI itself opens its output with O_CREAT|O_EXCL ("wx").
        prompt_bytes=profile.prompt.encode('utf-8')
        program=('import sys\n'
                 'data=sys.stdin.buffer.read()\n'
                 'open(sys.argv[1],"xb").write(data)\n')
        proc=self.leases.transport.call(client.execution_address,
            dict(action='write',root=self.leases.leases[client.execution_address],
                 token=self.leases.token,path=prompt_remote,
                 data=__import__('base64').b64encode(prompt_bytes).decode('ascii')))
        if not isinstance(proc,dict) or proc.get('written')!=len(prompt_bytes):
            raise ValueError('demand capture prompt staging failed on the client host')
        workload=profile.workload_sha256(guard.session.digest)
        file_type=_model_file_type(plan)
        argv=list(demand_client_argv(profile,
            rpc_endpoints=options['rpc_endpoints'],
            model_path=client.source_path,
            file_type=file_type,
            workload_sha256=workload,
            model_source=plan.model.source_id, model_revision=plan.model.revision,
            representation=plan.model.representation,
            context=plan.workload.context, batch=plan.workload.batch,
            microbatch=plan.workload.microbatch,
            threads=_client_host_threads(guard,client)))
        argv[argv.index('__demand_profile__')]=output_remote
        argv[argv.index('__demand_prompt__')]=prompt_remote
        record.update(status='STARTED',
            client_sha256=profile.client_sha256,
            manifest_sha256=identity.transformed_manifest_sha256,
            workload_sha256=workload,prompt_sha256=profile.prompt_sha256,
            file_type=file_type,argv=argv,started_monotonic=guard.clock(),
            started_at=datetime.now(timezone.utc).isoformat(),
            output_path=output_remote,log_path=log_remote)
        if store is not None:
            # Register the attempted role/artifact paths BEFORE dispatch, so a
            # lost spawn reply still gets retention attempted on known paths.
            store.register_attempt('demand',client.execution_address,
                invocation,log_remote)
            if not store.save_session_json('demand-capture-started.json',record):
                raise RuntimeError('demand capture metadata retention failed')
        guard.phase='demand'
        # The client connects to the already-listening owned workers; reuse the
        # same owned supervision/cleanup by running through the lease manager.
        spawn_options=self._assigned_spawn(plan,client,sources)
        record['attempted']=True
        rows['demand']=self.leases.spawn(client.execution_address,'demand',argv,
            **spawn_options)
        record['spawn_receipt']=dict(rows['demand'])
        if store is not None:
            store.register_process('demand',client.execution_address,
                rows['demand']['pid'],str(rows['demand']['start']))
        # Register the demand process with the campaign guard UNDER THE SAME
        # LOCK the monitor ticks under: from here on it is supervised like
        # every owned process (identity, coordinator cap, slice, deadline),
        # inspected on the CLIENT host as a coordinator process.
        guard.process_started(rows)
        # Bounded synchronous wait inside the campaign deadline; the supervised
        # unit carries the same RuntimeMaxSec backstop.
        deadline=guard.execute_deadline
        while True:
            guard.checkpoint()
            if not self.leases.alive(client.execution_address,'demand'):
                break
            if deadline is not None and time.monotonic()>=deadline:
                raise TimeoutError('demand capture exceeded the campaign deadline')
            self.pause(.5)
        # The supervised unit's own result decides success; the export is only
        # read afterwards. A nonzero unit result is a failed capture, never a
        # silently complete profile.
        try:
            exit_row=self.leases.inspect(client.execution_address,'demand')
        except Exception as exc:
            exit_row={'inspect_error':str(exc)}
        # The lifecycle 'inspect' action returns the systemd receipt NESTED:
        # {'unit': ..., 'properties': {...,'Result': ...}}. Reading a
        # top-level 'Result' would classify every successful capture as
        # unknown-exit/FAILED and never read the export back. Failed,
        # missing or malformed completion information stays unsuccessful.
        # Demand's RemainAfterExit unit must still be loaded and match the
        # owned spawn; default properties of an absent unit prove nothing.
        from .q8_experiment import _demand_completion_result
        unit_result=_demand_completion_result(exit_row,rows['demand'])
        record.update(ended_monotonic=guard.clock(),
            ended_at=datetime.now(timezone.utc).isoformat(),
            supervision=exit_row,unit_result=unit_result)
        if unit_result not in (None,'success','exit-code'):
            # A signal/oom/timeout/core-dump result is a genuine process
            # LOSS, not an own-exit failure: retain the honest receipt, then
            # stop the campaign (owned cleanup then stops every still-owned
            # process) instead of recording a mere failed capture.
            record.update(export_status='process-lost',status='FAILED')
            if store is not None and not store.save_session_json(
                    'demand-capture-finished.json',record):
                record['finished_record_retained']=False
            raise RuntimeError('demand capture process lost: systemd unit '
                'result '+unit_result)
        export_bytes=None
        if unit_result=='success':
            try:
                export_bytes=transport.read_bytes(client.execution_address,
                    output_remote,
                    max_bytes=16*1024*1024+1)
            except Exception as exc:
                record['export_status']='missing'
                record['export_error']=str(exc)
        elif unit_result is not None:
            record['export_status']='client-exit'
        else:
            record['export_status']='unknown-exit'
        if export_bytes is not None:
            if len(export_bytes)>16*1024*1024:
                record['export_status']='oversize'
            else:
                record['export_status']='retained'
                record['export_size']=len(export_bytes)
                record['export_sha256']=hashlib.sha256(export_bytes).hexdigest()
                if store is not None:
                    # Structural export only: selected expert IDs by layer/phase;
                    # the #312 emitter never writes prompts or token text.
                    # save_session_json returns False (never raises) on
                    # failure; a refused write must downgrade the status
                    # instead of labelling an unretained export 'retained'.
                    try:
                        saved=store.save_session_json('demand-export.json',
                            json.loads(export_bytes))
                    except Exception as exc:
                        saved=False
                        record['retention_error']=str(exc)
                    if not saved:
                        record['export_status']='retention-failed'
                    else:
                        record['export_retained']=True
        record['status']=('FINISHED' if record.get('export_status')=='retained'
                          else 'FAILED')
        if store is not None and not store.save_session_json(
                'demand-capture-finished.json',record):
            record['finished_record_retained']=False
        # The exited demand unit now leaves the MONITORED set (its outcome is
        # durably recorded); lease ownership is retained so terminal cleanup
        # still stops the unit and retains its final systemd receipt.
        guard.retire_finished_demand(client.execution_address)
        guard.phase='cleanup'; guard.phase_index=None
        return record

    def _run_profiled_collected(self,plan):
        """#302 production path: real collector, phased /2 reconciliation.

        Complete static admission runs over independently collected evidence
        after both owned processes are healthy and before the sole POST; the
        same-request dynamic reconciliation runs after the POST and gates
        output acceptance. A dynamic refusal means execution occurred but the
        output is rejected, which is reported truthfully.
        """
        if plan.selection=='two-gpu':
            return self._run_two_gpu_diagnostic(plan)
        from .phased_observation import (OwnedSpawnFacts, RequestIdentity,
            reconcile_static, reconcile_dynamic)
        from .profiles import sha256 as _sha256
        admission=self._profiled_admission(plan)
        mode=dict(mode=self.observation_mode,clock=self.clock)
        spec=llama_cpp_spec(plan)
        client=next(p for p in plan.participants if p.role=='client')
        remote=next(p for p in plan.participants if p.role=='remote')
        for part in (client,remote):
            if (part.role=='client' or thaw(plan.strategy_options)['source_contract']=='full-source-both-hosts/1') and Path(part.source_path).name!=plan.model.members[0][0]:
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
        # Per-role derived-build deployment identities: the client runs the
        # retained llama-server build and the RPC participant runs the
        # retained ggml-rpc-server build; a shared identity cannot express
        # both and must refuse here before any spawn.
        _ROLE_FIELDS=('client_manifest_path','client_executable_path',
                      'remote_manifest_path','remote_executable_path')
        if set(observer_options)!=set(_ROLE_FIELDS):
            raise ValueError('observer deployment options: exact per-role '
                             'manifest/executable deployment paths required')
        for field in _ROLE_FIELDS:
            if not isinstance(observer_options.get(field),str) or not observer_options[field]:
                raise ValueError('observer deployment option '+field+' required')
        role_paths={'client':(observer_options['client_manifest_path'],
                              observer_options['client_executable_path']),
                    'remote':(observer_options['remote_manifest_path'],
                              observer_options['remote_executable_path'])}
        remote_argv=(remote.runtime_executable,*spec.rpc_args,'--host',host,'--port',str(remote.port),
                     *(('--cache',) if cache_enabled else ()))
        client_argv=(spec.executable,*spec.args,'--host','127.0.0.1','--port',str(client.port))
        tunnel=None; error=None; result=None; cleanup_error=None
        try:
            self.leases.acquire(remote.execution_address,remote.lifecycle_dir)
            self.leases.acquire(client.execution_address,client.lifecycle_dir)
            sources=self._verify_profiled_sources(plan,client,remote)
            self.leases.port(remote.execution_address,host,remote.port)
            self.leases.port(client.execution_address,'127.0.0.1',client.port)
            invocation=self.leases.token
            export_dirs={
                remote.participant_id:str(Path(self.leases.invocation_dir(remote.execution_address))/'exports-rpc'),
                client.participant_id:str(Path(self.leases.invocation_dir(client.execution_address))/'exports-client')}
            rows={remote.participant_id:self._spawn_profiled_rpc(plan,remote,remote_argv,sources,export_dirs[remote.participant_id])}
            rpc_deadline=time.monotonic()+spec.startup_timeout_seconds
            while True:
                self._live(client,remote,client_started=False)
                ready=self.leases.listening(remote.execution_address,'rpc',host,remote.port)
                self._live(client,remote,client_started=False)
                if time.monotonic()>rpc_deadline: raise TimeoutError('RPC owned listener startup timeout')
                if ready: break
                self.pause(.5)
            rows[client.participant_id]=self.leases.spawn(client.execution_address,'client',list(client_argv),
                export=export_dirs[client.participant_id],**self._assigned_spawn(plan,client,sources))
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
                manifest_path,executable_path=role_paths[p.role]
                # Owned-listener endpoints RE-VERIFIED through the trusted
                # lifecycle seam immediately before collection: the remote
                # RPC listener is confirmed by a fresh owned-listener check
                # on the remote host; the client listener is confirmed by
                # the tunnel-mediated /health probe completed above. These
                # are independent remote observations, not configuration
                # echoes.
                if p.role=='remote':
                    if not self.leases.listening(p.execution_address,'rpc',
                                                 host,remote.port):
                        raise RuntimeError('owned RPC listener not independently '
                                           'observed at static admission')
                    owned_endpoints=(f'{host}:{remote.port}',)
                else:
                    owned_endpoints=(f'127.0.0.1:{p.port}',)
                # Repeat the source precheck's role/backend join at static
                # collection; the coordinator remains CPU for either plan.
                from .assigned_backing import CONTRACT
                from .qwen_q8 import q8_participant_build_backend
                build_kwargs = ({'backend': q8_participant_build_backend(plan,p)}
                    if options['source_contract']==CONTRACT else {})
                if options['source_contract']==CONTRACT and 'build_pair' in options:
                    build_kwargs['build_pair']=options['build_pair']
                evidence=self.collector.collect_static(p,spawn,
                    manifest_path,executable_path,
                    _sha256(sources[p.participant_id]),expected_argv=argv,
                    listener_endpoints=owned_endpoints,**build_kwargs)
                static_evidence.append(evidence)
            static_receipt=self.static_reconciler(plan,static_evidence,sources,**mode)
            self._live(client,remote)
            if tunnel.poll() is not None: raise RuntimeError('SSH tunnel exited before request')
            request=dict(plan.request)
            request_nonce=self.request_nonce or secrets.token_hex(16)
            request_identity=RequestIdentity(invocation_token=invocation,request_nonce=request_nonce)
            # Recheck plan freshness after blocking liveness/tunnel work,
            # immediately before the sole POST; no transport work intervenes.
            admission=self._profiled_admission(plan)
            fresh_static=reconcile_static(plan,static_evidence,sources,
                mode=self.observation_mode,clock=self.clock)
            if fresh_static != static_receipt:
                raise ValueError('static evidence changed after admission receipt')
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
            # then waits for the exact-owned terminal export fence before
            # collecting and reconciling; only then is output accepted.
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
                label=NATIVE_LABELS['client' if p.role=='client' else 'remote']
                # Deterministic terminal-export fence: the producer writes
                # the envelope at termination, which may complete after the
                # owned process exit is observed; wait bounded before
                # collecting, refuse on missing/foreign exports.
                self.collector.await_terminal_export(p,spawn,
                    export_dirs[p.participant_id],label)
                dynamic_evidence.append(self.collector.collect_dynamic(p,spawn,
                    export_dirs[p.participant_id],plan.digest,invocation,label))
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
            fresh_static=reconcile_static(plan,static_evidence,sources,
                mode=self.observation_mode,clock=self.clock)
            if fresh_static != static_receipt:
                raise ValueError('static evidence changed during dynamic collection')
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
        if options['source_contract']=='coordinator-full-source/participant-assigned-rpc-backing/1':
            collector=NativeObserverCollector(selective=True)
        else:
            collector=NativeObserverCollector()
        runner=OperatorRunner(SSHSourceTransport(),manager,JSONHTTP(),ssh_tunnel,
            collector=collector,static_reconciler=reconcile_static,
            dynamic_reconciler=reconcile_dynamic)
    else:
        runner=OperatorRunner(SSHSourceTransport(),manager,JSONHTTP(),ssh_tunnel)
    return runner.run(plan)
