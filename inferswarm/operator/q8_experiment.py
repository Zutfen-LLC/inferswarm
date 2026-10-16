"""Explicitly bounded, non-qualifying #313 two-CUDA experiment driver.

This module is deliberately separate from ordinary operator admission.  It
does not manufacture allocation bounds or capability evidence: it records the
ordinary blocked admission verbatim and permits only a separately authorized,
externally supervised diagnostic campaign.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import posixpath
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import threading
import time

from .config import parse_config_json
from .lifecycle import LeaseManager, SSHTransport
from .plan import build_plan
from .profiles import canonical, thaw


EXPERIMENTAL_OPT_IN = 'I_AUTHORIZE_ONE_UNQUALIFIED_Q8_TWO_CUDA_EXPERIMENT'

_LIMITS = {
    'total_seconds': 180 * 60,
    'cleanup_reserve_seconds': 20 * 60,
    'backing_ceiling_bytes': 48 << 30,
    'min_free_disk_bytes': 64 << 30,
    'application_payload_ceiling_bytes': 24 << 30,
    'worker_memory_max_bytes': 10 << 30,
    'worker_min_host_headroom_bytes': 4 << 30,
    'coordinator_memory_max_bytes': 110 << 30,
    'coordinator_min_host_headroom_bytes': 8 << 30,
    'owned_swap_max_bytes': 0,
    'per_gpu_reserve_bytes': 512 << 20,
}


@dataclass(frozen=True)
class ExperimentalEnvelope:
    config_sha256: str
    request_sha256: str
    gpu_bindings: tuple[tuple[str, str], ...]
    limits: tuple[tuple[str, int], ...]
    normal_admission_status: str
    normal_technical_feasibility: str
    normal_execution_ready: bool
    unknown_allocations: tuple[str, ...]


class ExperimentalLeaseManager(LeaseManager):
    """Issue-313-only systemd limits for every persistent owned process."""
    def configure(self,guard):
        self.guard=guard
        self.units={}
        self.slices={}
        self._lock=threading.RLock()
        self.cancelled=False
        self.helper_index=0
        self.helper_receipts=[]
        self.stopped_receipts={}
        self.spawn_receipts=[]

    def register(self,address,unit):
        # Register BEFORE dispatch so a failed/ambiguous SSH reply remains owned.
        with self._lock:
            self.guard.checkpoint()
            if self.cancelled: raise RuntimeError('experimental campaign already stopped')
            self.units.setdefault(address,[]).append(unit)

    def open_budget(self,part,memory):
        address=part.execution_address
        token=re.sub(r'[^A-Za-z0-9]', '', self.token)
        owned_slice='inferswarmq8'+token+'.slice'
        unit='inferswarm-q8-'+token+'-deadline.service'
        self.slices[address]=owned_slice
        self.register(address,unit)
        # A tiny owned sentinel keeps the slice available before any payload or
        # helper starts. Its timer is an independent backstop, not the monitor.
        self.guard.commands.run(address,['sudo','-n','systemd-run','--quiet',
            '--unit='+unit,'--slice='+owned_slice,
            '--property=RuntimeMaxSec='+str(self.guard.remaining()),
            '--property=TimeoutStopSec=10','--','/usr/bin/sleep',
            str(self.guard.remaining())])
        self.guard.commands.run(address,['sudo','-n','systemctl','set-property',
            '--runtime',owned_slice,'MemoryAccounting=yes','MemoryMax='+str(memory),
            'MemorySwapMax=0'])

    def run_helper(self,address,command,*,input=None,text=True,timeout=120,
                   capture_output=True):
        """Run source/collector helpers in the same host aggregate as payloads."""
        with self._lock:
            self.helper_index+=1
            unit='inferswarm-q8-'+self.token+'-helper'+str(self.helper_index)+'.service'
            self.register(address,unit)
        remote=['sudo','-n','systemd-run','--quiet','--wait','--pipe',
            '--unit='+unit,'--slice='+self.slices[address],
            '--property=KillMode=control-group','--property=TimeoutStopSec=10',
            '--property=MemorySwapMax=0',
            '--property=RuntimeMaxSec='+str(min(timeout,self.guard.remaining())),
            '--uid='+self.guard.uids[address], '--gid='+self.guard.gids[address],
            '--','/bin/sh','-c',command]
        # Source program and payload are unchanged; all compiler children inherit
        # the service cgroup. Successful synchronous completion is retained as a receipt.
        proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',
            address,shlex.join(remote)],input=input,text=text,
            capture_output=capture_output,timeout=min(timeout,self.guard.remaining())+15)
        with self._lock:
            self.helper_receipts.append(dict(address=address,unit=unit,returncode=proc.returncode))
            if proc.returncode==0: self.units[address].remove(unit)
        self.guard.checkpoint()
        return proc

    def _call(self,address,action,**kwargs):
        key=(address,kwargs.get('name'))
        if action=='stop' and key in getattr(self,'stopped_receipts',{}):
            return self.stopped_receipts[key]
        return super()._call(address,action,**kwargs)

    def stop_units(self):
        errors=[]
        with self._lock:
            self.cancelled=True
            owned=[(a,list(units)) for a,units in self.units.items()]
        for address,units in reversed(owned):
            for unit in reversed(units):
                try:
                    names=[name for name,row in list(self.owned.get(address,{}).items())
                           if row.get('supervision',{}).get('unit')==unit]
                    if names:
                        name=names[0]; row=self.owned[address][name]
                        self.stopped_receipts[(address,name)]=self._call(address,'stop',
                            name=name,pid=row['pid'],start=row['start'])
                    else:
                        # An acknowledged synchronous helper may already be
                        # inactive/GC'd; an ambiguous spawn remains registered.
                        state=self.guard.commands.run(address,['sudo','-n','systemctl','show',unit,
                            '--property=LoadState','--property=ActiveState'])
                        values=dict(line.split('=',1) for line in state.splitlines() if '=' in line)
                        if values.get('ActiveState')!='inactive':
                            self.guard.commands.run(address,
                                ['sudo','-n','systemctl','stop',unit],timeout=30)
                except Exception as exc: errors.append(str(exc))
        if errors: raise RuntimeError('owned systemd stop failed: '+'; '.join(errors))

    def cleanup(self):
        rows=super().cleanup()
        if not hasattr(self,'_lock'): return rows
        with self._lock:
            for address,host in rows.items():
                for row in host.values():
                    if isinstance(row,dict) and row.get('signal')=='systemd-stop':
                        unit=row['unit']
                        if unit in self.units.get(address,[]): self.units[address].remove(unit)
        return rows

    def cleanup_budgets(self):
        # Called even if a spawn/source call failed before a PID receipt arrived.
        errors=[]; receipts={}
        try: self.stop_units()
        except Exception as exc: errors.append(str(exc))
        for address,owned_slice in self.slices.items():
            try:
                self.guard.commands.run(address,['sudo','-n','systemctl','stop',owned_slice])
                state=self.guard.commands.run(address,['sudo','-n','systemctl','show',owned_slice,
                    '--property=ActiveState','--property=ControlGroup'])
                props=dict(line.split('=',1) for line in state.splitlines() if '=' in line)
                receipts[address]=props
                if props.get('ActiveState')!='inactive' or props.get('ControlGroup')!='':
                    raise RuntimeError('owned aggregate still populated after stop')
            except Exception as exc: errors.append(str(exc))
        # Stop above is idempotent; failed units stay loaded for receipts, then
        # reset only this invocation's explicitly registered units.
        for address,units in self.units.items():
            for unit in units:
                try: self.guard.commands.run(address,['sudo','-n','systemctl','reset-failed',unit])
                except Exception: pass  # metadata GC cannot replace verified cleanup
        if errors: raise RuntimeError('; '.join(errors))
        return receipts

    def spawn(self, address, name, argv, cache=None, export=None, assigned=None):
        if name in ('rpc0', 'rpc1'):
            memory = _LIMITS['worker_memory_max_bytes'] // 2
        elif name == 'client':
            memory = _LIMITS['coordinator_memory_max_bytes']
        else:
            raise ValueError('experimental campaign refuses ancillary persistent process: '+name)
        unit_token = re.sub(r'[^A-Za-z0-9_.-]', '-', self.token)
        supervision = {
            'unit': 'inferswarm-q8-313-'+unit_token+'-'+name+'.service',
            'memory_max_bytes': memory,
            'memory_swap_max_bytes': _LIMITS['owned_swap_max_bytes'],
            'runtime_max_seconds': (_LIMITS['total_seconds']
                                    - _LIMITS['cleanup_reserve_seconds']),
        }
        if hasattr(self,'guard'):
            self.register(address,supervision['unit'])
            supervision.update(slice=self.slices[address],
                runtime_max_seconds=self.guard.remaining(),
                cuda_visible_devices=(','.join(uuid for _,uuid in self.guard.envelope.gpu_bindings)
                                      if name.startswith('rpc') else ''))
        return self._spawn_supervised(address, name, argv, cache=cache,
            export=export, assigned=assigned, supervision=supervision)

    def _spawn_supervised(self, address, name, argv, *, cache, export, assigned,
                          supervision):
        result = self._call(address, 'spawn', name=name, argv=list(argv),
            cache=cache, export=export, assigned=assigned,
            supervision=supervision)
        self.owned[address][name] = result
        if hasattr(self,'spawn_receipts'):
            self.spawn_receipts.append(dict(address=address,name=name,argv=list(argv),**result))
        return result


def _duration_usec(value):
    # systemctl show renders USEC properties as human-readable durations.
    if value.isdecimal(): return int(value)
    units={'us':1,'ms':1000,'s':1000000,'min':60*1000000,'h':3600*1000000}
    tokens=re.findall(r'([0-9]+)(us|ms|min|h|s)',value)
    if not tokens or ''.join(n+u for n,u in tokens)!=value.replace(' ',''):
        raise ValueError('unverifiable systemd runtime deadline')
    return sum(int(n)*units[u] for n,u in tokens)


def _digest(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError(label + ' must be lowercase SHA-256')
    return value


def validate_experimental_envelope(plan, raw, *, config_sha256, request_sha256):
    """Validate the fixed experiment envelope without changing admission."""
    expected = {'schema', 'opt_in', 'config_sha256', 'request_sha256',
                'limits', 'gpu_bindings'}
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ValueError('experimental envelope fields must be exact')
    if raw['schema'] != 'q8-two-cuda-experiment/1':
        raise ValueError('unsupported experimental envelope schema')
    if raw['opt_in'] != EXPERIMENTAL_OPT_IN:
        raise ValueError('explicit experimental opt-in required')
    if plan.selection != 'two-gpu':
        raise ValueError('experimental driver requires the two-gpu plan')
    if not plan.admission.structural_admissible:
        raise ValueError('experimental driver requires a structurally admissible plan')
    if plan.admission.execution_ready or plan.admission.status == 'ADMITTED':
        raise ValueError('experimental driver is only for ordinarily blocked diagnostics')
    options=thaw(plan.strategy_options)
    backing=options.get('participant_backing')
    if (not isinstance(backing,dict)
            or backing.get('limit_bytes')!=_LIMITS['backing_ceiling_bytes']
            or backing.get('min_free_bytes',0)<_LIMITS['min_free_disk_bytes']
            or type(backing.get('reserve_bytes')) is not int
            or not 0<backing['reserve_bytes']<=_LIMITS['backing_ceiling_bytes']):
        raise ValueError('assigned backing budget must encode the frozen ceiling and free-disk floor')
    if _digest(raw['config_sha256'], 'config_sha256') != _digest(config_sha256, 'actual config SHA-256'):
        raise ValueError('experimental config identity mismatch')
    if _digest(raw['request_sha256'], 'request_sha256') != _digest(request_sha256, 'actual request SHA-256'):
        raise ValueError('experimental request identity mismatch')
    if (not isinstance(raw['limits'],dict) or raw['limits']!=_LIMITS
            or any(type(v) is not int for v in raw['limits'].values())):
        raise ValueError('experimental limits must equal the reviewed frozen envelope')
    bindings = raw['gpu_bindings']
    if not isinstance(bindings, list) or len(bindings) != 2:
        raise ValueError('exactly two GPU bindings required')
    parsed = []
    for index, row in enumerate(bindings):
        if not isinstance(row, dict) or set(row) != {'selector', 'uuid'}:
            raise ValueError('GPU binding fields must be exact')
        selector = row['selector']; uuid = row['uuid']
        if selector != 'CUDA' + str(index):
            raise ValueError('GPU bindings must preserve CUDA0,CUDA1 selector order')
        if not isinstance(uuid, str) or not re.fullmatch(r'GPU-[0-9A-Fa-f-]{32,36}', uuid):
            raise ValueError('GPU binding requires an observed NVIDIA UUID')
        parsed.append((selector, uuid))
    if parsed[0][1].lower() == parsed[1][1].lower():
        raise ValueError('GPU bindings require two distinct UUIDs')
    unknown = tuple(sorted(c.allocation_id for c in plan.candidate.charges
                           if c.bytes is None))
    if not unknown:
        raise ValueError('experimental driver cannot erase ordinary unknown allocations')
    payload = sum(a.encoded_bytes for a in plan.candidate.assignments
                  if a.binding_id in ('binding-B-gpu0', 'binding-B-gpu1'))
    if payload > _LIMITS['application_payload_ceiling_bytes']:
        raise ValueError('assigned application payload exceeds frozen ceiling')
    if payload > _LIMITS['backing_ceiling_bytes']:
        raise ValueError('assigned backing exceeds frozen ceiling')
    return ExperimentalEnvelope(raw['config_sha256'], raw['request_sha256'],
        tuple(parsed), tuple(sorted(_LIMITS.items())), plan.admission.status,
        plan.admission.technical_feasibility, plan.admission.execution_ready,
        unknown)


def _strict_json(path):
    def pairs(rows):
        result={}
        for key,value in rows:
            if key in result: raise ValueError('duplicate experimental envelope key: '+key)
            result[key]=value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError('non-finite experimental envelope value: '+value)))


class SSHCommandRunner:
    """Fixed-command, non-interactive read-only probes for the two named hosts."""
    def run(self,address,argv,*,timeout=30):
        proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',address,
            shlex.join(argv)],capture_output=True,text=True,timeout=timeout)
        if proc.returncode:
            raise RuntimeError('remote command failed on '+address+': '+proc.stderr[-500:])
        return proc.stdout


class SystemdCampaignGuard:
    """Fail-closed one-shot preflight and best-effort physical observation."""
    def __init__(self,envelope,leases,commands,*,clock=time.monotonic,pause=time.sleep):
        self.envelope=envelope; self.leases=leases; self.commands=commands
        self.clock=clock; self.pause=pause; self.started=None; self.execute_deadline=None
        self.client=None; self.remote=None; self.process_receipts=None
        self.rows={}; self.uids={}; self.gids={}
        self.request_attempts=0; self.verified_backing={}
        self.execution_result={}; self.raw_response=None
        self.last_aggregates={}; self.last_gpu_rows=[]; self.last_host_available={}
        self._stop=threading.Event(); self._thread=None; self._samples=[]; self._monitor_error=None
        if hasattr(leases,'configure'): leases.configure(self)

    def _run(self,part,argv): return self.commands.run(part.execution_address,argv)

    def remaining(self):
        self.checkpoint()
        remaining=int(self.execute_deadline-self.clock())
        if remaining<1: raise TimeoutError('campaign execution deadline reached')
        return remaining

    def checkpoint(self):
        if self._monitor_error is not None:
            raise RuntimeError('campaign monitor failed: '+str(self._monitor_error)) from self._monitor_error
        if self.execute_deadline is not None and self.clock()>=self.execute_deadline:
            raise TimeoutError('campaign execution deadline reached')

    def budget(self,address):
        owned_slice=self.leases.slices[address]
        raw=self.commands.run(address,['sudo','-n','systemctl','show',owned_slice,
            '--property=MemoryMax','--property=MemorySwapMax','--property=MemoryCurrent',
            '--property=MemorySwapCurrent','--property=ControlGroup'])
        props=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        self.last_aggregates[address]=props
        expected=(_LIMITS['worker_memory_max_bytes'] if address==self.remote.execution_address
                  else _LIMITS['coordinator_memory_max_bytes'])
        if (int(props['MemoryMax'])!=expected or int(props['MemorySwapMax'])!=0
                or int(props['MemorySwapCurrent'])!=0 or int(props['MemoryCurrent'])>expected):
            raise RuntimeError('aggregate cgroup limit/owned swap violation: '+address)
        group=props['ControlGroup']
        if not group.startswith('/') or '..' in Path(group).parts:
            raise ValueError('invalid aggregate ControlGroup')
        events=self.commands.run(address,['cat','/sys/fs/cgroup'+group+'/memory.events'])
        counters=dict(line.split() for line in events.splitlines())
        props['memory_events']=counters
        if any(int(counters[k]) for k in ('oom','oom_kill')):
            raise RuntimeError('owned aggregate allocator/OOM failure: '+address)
        props['memory_events']=counters  # max/reclaim alone is an observation
        return props

    @staticmethod
    def _available(text):
        rows=[line.split() for line in text.splitlines() if line.strip()]
        values={row[0].rstrip(':'):int(row[1])*1024 for row in rows
                if len(row)>=2 and row[1].isdigit()}
        if 'MemAvailable' not in values: raise ValueError('MemAvailable observation missing')
        return values['MemAvailable']

    def _gpu_rows(self):
        raw=self._run(self.remote,['nvidia-smi','--query-gpu=index,uuid,memory.free,utilization.gpu',
            '--format=csv,noheader,nounits'])
        rows=[]
        for line in raw.splitlines():
            fields=[item.strip() for item in line.split(',')]
            if len(fields)!=4 or not fields[0].isdigit() or not fields[2].isdigit() or not fields[3].isdigit():
                raise ValueError('unparseable nvidia-smi GPU observation')
            rows.append(dict(index=int(fields[0]),uuid=fields[1],
                free_bytes=int(fields[2])<<20,utilization=int(fields[3])))
        self.last_gpu_rows=rows
        wanted=dict(self.envelope.gpu_bindings)
        by_uuid={row['uuid']:row for row in rows}
        for selector in ('CUDA0','CUDA1'):
            if wanted[selector] not in by_uuid:
                raise ValueError('wrong GPU selector/UUID mapping for '+selector)
            if by_uuid[wanted[selector]]['free_bytes']<_LIMITS['per_gpu_reserve_bytes']:
                raise RuntimeError('per-GPU reserve breach: '+selector)
        return rows

    def _apps(self):
        raw=self._run(self.remote,['nvidia-smi','--query-compute-apps=pid,gpu_uuid,used_memory',
            '--format=csv,noheader,nounits'])
        rows=[]
        for line in raw.splitlines():
            if not line.strip(): continue
            fields=[item.strip() for item in line.split(',')]
            if len(fields)!=3 or not fields[0].isdigit() or not fields[2].isdigit():
                raise ValueError('unparseable nvidia-smi process observation')
            rows.append(dict(pid=int(fields[0]),uuid=fields[1],used_bytes=int(fields[2])<<20))
        return rows

    def _memory(self,part,minimum):
        available=self._available(self._run(part,['grep','-E','^MemAvailable:','/proc/meminfo']))
        self.last_host_available[part.host_id]=available
        if available<minimum: raise RuntimeError('host headroom breach: '+part.host_id)
        return available

    def begin(self,plan,spec,client,remote):
        self.started=self.clock(); self.execute_deadline=self.started+(
            _LIMITS['total_seconds']-_LIMITS['cleanup_reserve_seconds'])
        self.client=client; self.remote=remote
        from .qwen_q8 import q8_rpc_processes
        processes=q8_rpc_processes(plan)
        if [(p.native_selector,p.endpoint) for p in processes] != [
                ('CUDA0',thaw(plan.strategy_options)['rpc_endpoints'][0]),
                ('CUDA1',thaw(plan.strategy_options)['rpc_endpoints'][1])]:
            raise ValueError('native two-listener lowering drift')
        for part in (client,remote):
            self._run(part,['sudo','-n','true'])
            self._run(part,['systemd-run','--version'])
            self._run(part,['systemctl','--version'])
            observed=self._run(part,['sha256sum','--',part.runtime_executable]).split()[0]
            if observed!=part.runtime_sha256:
                raise ValueError('runtime binary identity mismatch: '+part.participant_id)
        self._memory(client,_LIMITS['coordinator_min_host_headroom_bytes'])
        self._memory(remote,_LIMITS['worker_min_host_headroom_bytes'])
        disk=self._run(remote,['df','-B1','--output=avail',remote.cache_path]).splitlines()
        values=[line.strip() for line in disk if line.strip().isdigit()]
        if len(values)!=1 or int(values[0])<_LIMITS['min_free_disk_bytes']:
            raise RuntimeError('assigned cache free-disk floor not met')
        self._gpu_rows()
        if hasattr(self.leases,'configure'):
            for part,cap in ((remote,_LIMITS['worker_memory_max_bytes']),
                             (client,_LIMITS['coordinator_memory_max_bytes'])):
                self.uids[part.execution_address]=self._run(part,['id','-u']).strip()
                self.gids[part.execution_address]=self._run(part,['id','-g']).strip()
                if not self.uids[part.execution_address].isdigit() or not self.gids[part.execution_address].isdigit():
                    raise ValueError('supervised service UID/GID missing')
                self.leases.open_budget(part,cap)
                self.budget(part.execution_address)
            self._thread=threading.Thread(target=self._monitor,daemon=True)
            self._thread.start()

    def sources_verified(self,plan,sources):
        self.verified_backing=sources
        receipt=sources.get(self.remote.participant_id)
        guards=receipt.get('assigned_guard_paths') if isinstance(receipt,dict) else None
        if not isinstance(guards,dict) or set(guards)!={'binding-B-gpu0','binding-B-gpu1'}:
            raise ValueError('immutable assigned preparation guards missing')
        if len(set(guards.values()))!=2:
            raise ValueError('assigned preparation guards must be disjoint')
        retained=receipt.get('retained_backing_bytes')
        reserve=receipt.get('native_repair_reserve_bytes')
        if (type(retained) is not int or type(reserve) is not int
                or retained<0 or reserve<0
                or retained+reserve>_LIMITS['backing_ceiling_bytes']):
            raise ValueError('verified assigned backing exceeds frozen ceiling')

    def _inspect(self,rows):
        receipts={}
        for name in rows:
            part=self.client if name=='client' else self.remote
            expected=(110<<30) if name=='client' else (5<<30)
            row=self.leases.inspect(part.execution_address,name)
            props=row['properties']; receipts[name]=row
            if props['ActiveState']!='active' or int(props['MainPID'])!=rows[name]['pid']:
                raise RuntimeError('systemd ownership mismatch: '+name)
            if int(props['MemoryMax'])!=expected or int(props['MemorySwapMax'])!=0:
                raise RuntimeError('systemd resource limit mismatch: '+name)
            if int(props['MemorySwapCurrent'])!=0 or int(props['MemoryCurrent'])>expected:
                raise RuntimeError('owned cgroup memory/swap violation: '+name)
            if props['KillMode']!='control-group' or not 0<_duration_usec(props['RuntimeMaxUSec'])<=9600*1000000:
                raise RuntimeError('systemd deadline/descendant supervision mismatch: '+name)
            expected_slice=self.leases.slices[part.execution_address]
            if expected_slice not in props['ControlGroup'].split('/'):
                raise RuntimeError('service outside owned aggregate: '+name)
        return receipts

    def _sample(self,rows):
        gpu=self._gpu_rows(); apps=self._apps()
        expected={rows[name]['pid']:dict(self.envelope.gpu_bindings)[selector]
                  for name,selector in (('rpc0','CUDA0'),('rpc1','CUDA1')) if name in rows}
        owned=[row for row in apps if row['pid'] in expected]
        observed={row['pid']:row['uuid'] for row in owned}
        wrong={row['pid']:(expected[row['pid']],row['uuid']) for row in owned
               if expected[row['pid']]!=row['uuid']}
        if wrong: raise RuntimeError('wrong GPU/listener PID mapping: '+repr(wrong))
        return dict(monotonic=self.clock(),gpu=gpu,owned_apps=observed,
                    attribution=('BOUND' if expected and set(observed)==set(expected) else 'INCONCLUSIVE'))

    def process_started(self,rows):
        self.rows=dict(rows)
        self.checkpoint()
        # Verify the parent slice, per-service cap, ownership and timer before
        # allowing any further launch or the frozen request.
        self._inspect(rows)

    def resource_sample(self,rows):
        sample=self._sample(dict(rows))
        sample['host_available']={
            self.remote.host_id:self._memory(self.remote,_LIMITS['worker_min_host_headroom_bytes']),
            self.client.host_id:self._memory(self.client,_LIMITS['coordinator_min_host_headroom_bytes'])}
        sample['aggregates']={a:self.budget(a) for a in self.leases.slices}
        for name in dict(rows):
            part=self.client if name=='client' else self.remote
            log=str(Path(self.leases.invocation_dir(part.execution_address))/(name+'.log'))
            text=self._run(part,['tail','-c','16384','--',log])
            if re.search(r'(?i)(out of memory|failed to allocate|bad_alloc|illegal memory access|device.*lost|CUDA error)',text):
                raise RuntimeError('owned allocator/device failure: '+name)
        self._inspect(dict(rows))
        return sample

    def _monitor(self):
        try:
            while not self._stop.wait(2):
                self.checkpoint()
                self._samples.append(self.resource_sample(dict(self.rows)))
        except BaseException as exc:
            self._monitor_error=exc
            # Sweep until the main path acknowledges STOP. This also catches a
            # previously dispatched helper whose systemd launch arrives late.
            while True:
                try: self.leases.stop_units()
                except Exception as stop_error:
                    self._monitor_error=RuntimeError(str(exc)+'; '+str(stop_error))
                if self._stop.wait(2): break

    def stop_monitor(self):
        self._stop.set()
        if self._thread is not None: self._thread.join(timeout=45)
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError('campaign monitor did not stop')

    def before_request(self,plan,rows,process_receipts,sources):
        if self.clock()>=self.execute_deadline: raise TimeoutError('campaign execution deadline reached')
        self.process_receipts=process_receipts
        receipt=dict(cgroups=self._inspect(rows),sample=self.resource_sample(rows))
        self.checkpoint()
        self._samples.append(receipt['sample'])
        return receipt

    def request_started(self):
        self.checkpoint()
        if self.request_attempts: raise RuntimeError('experimental request already attempted')
        self.request_attempts=1

    def request_timeout_seconds(self):
        remaining=int(self.execute_deadline-self.clock())
        if remaining<1: raise TimeoutError('campaign execution deadline reached')
        return min(900,remaining)

    def after_request(self,plan,rows,process_receipts,sources,response):
        self.checkpoint()
        self._samples.append(self.resource_sample(rows))
        cgroups=self._inspect(rows)
        return dict(cgroups=cgroups,samples=list(self._samples),
                    compute_attribution='INCONCLUSIVE',
                    sampling_limit='PID/UUID memory and device-wide utilization do not prove owned kernel execution; sampled reserve is not a hard GPU cap')

    def after_cleanup(self,cleanup):
        self.stop_monitor()
        if hasattr(self.leases,'cleanup_budgets'):
            self.final_aggregates=self.leases.cleanup_budgets()
        if any(row.get('lease')!='released' for row in cleanup.values()):
            raise RuntimeError('owned lease cleanup incomplete')
        for host in cleanup.values():
            for name,row in host.items():
                if name=='lease' or not isinstance(row,dict): continue
                props=row.get('properties')
                if props is None: raise RuntimeError('final systemd receipt missing: '+name)
                if props['Result'] not in ('success','signal'):
                    raise RuntimeError('owned systemd job failed: '+name+': '+props['Result'])
                if int(props['MemorySwapCurrent'])!=0:
                    raise RuntimeError('owned swap violation retained at cleanup: '+name)
        if self.started is not None and self.clock()>self.started+_LIMITS['total_seconds']:
            raise TimeoutError('campaign total deadline exceeded during cleanup')


from .runtime import SSHSourceTransport
from .native_observer.collector import SSHCollectorTransport


class SupervisedSourceTransport(SSHSourceTransport):
    def __init__(self,manager,*,digest_cache=None,force_fresh=False):
        self.manager=manager
        self.digest_cache=digest_cache
        self.force_fresh=force_fresh
        self.digest_cache_stats={}
        self.source_fingerprints={}
        self.coordinator=None
    def _call(self,part,program,payload):
        cached=False
        if payload and self.digest_cache and part.role=='client':
            value=json.loads(payload)
            if value.get('schema')=='q8-source-verification/1':
                value.update(schema='q8-source-verification/2',
                    digest_cache=dict(path=self.digest_cache,force_fresh=self.force_fresh))
                payload=json.dumps(value); cached=True
        proc=self.manager.run_helper(part.execution_address,
            'python3 -c '+shlex.quote(program),input=payload,timeout=1800)
        if cached and proc.returncode==0:
            value=json.loads(proc.stdout)
            self.digest_cache_stats=value['digest_cache']
            self.source_fingerprints=value['source_fingerprints']
            self.coordinator=part
            proc.stdout=json.dumps(value['receipt'])
        return proc

    def revalidate_source_identity(self):
        if not self.source_fingerprints: return
        from . import source
        program=Path(source.__file__).read_text().rsplit("if __name__=='__main__': main()",1)[0]
        program += "\nfor path, witness in json.loads(sys.stdin.read()).items():\n    if SourceDigestCache.fingerprint(path) != witness: raise ValueError('source changed during experiment')\n"
        proc=self.manager.run_helper(self.coordinator.execution_address,
            'python3 -c '+shlex.quote(program),input=json.dumps(self.source_fingerprints),timeout=30)
        if proc.returncode: raise RuntimeError('coordinator source identity changed during experiment: '+proc.stderr[-500:])


class SupervisedCollectorTransport(SSHCollectorTransport):
    def __init__(self,manager): self.manager=manager
    def run(self,address,command,**kwargs):
        return self.manager.run_helper(address,command,**kwargs)


class ExperimentalCampaignError(RuntimeError):
    """A nonzero campaign result with its partial evidence still available."""
    def __init__(self,campaign_receipt,cause):
        super().__init__(str(cause))
        self.campaign_receipt=campaign_receipt


def run_experimental_campaign(config_path,envelope_path,*,commands=None,transport=None,
                              runner_factory=None,evidence_root=None,
                              evidence_transport=None,source_digest_cache=None,force_fresh_source_hash=False):
    """Run exactly one unqualified request under the reviewed #313 envelope."""
    config_bytes=Path(config_path).read_bytes()
    plan=build_plan(parse_config_json(config_bytes.decode('utf-8'),base_dir=Path(config_path).parent))
    if force_fresh_source_hash and source_digest_cache is None:
        raise ValueError('force fresh source hash requires source digest cache')
    if source_digest_cache is not None:
        cache_path=Path(source_digest_cache)
        if not cache_path.is_absolute(): raise ValueError('absolute source digest cache path required')
        cache_path=Path(posixpath.normpath(str(cache_path)))
        for part in plan.participants:
            if cache_path.is_relative_to(Path(posixpath.normpath(part.lifecycle_dir))):
                raise ValueError('source digest cache must be outside lifecycle directories')
        source_digest_cache=str(cache_path)
    config_sha=hashlib.sha256(config_bytes).hexdigest()
    request_sha=hashlib.sha256(canonical(dict(plan.request))).hexdigest()
    envelope=validate_experimental_envelope(plan,_strict_json(envelope_path),
        config_sha256=config_sha,request_sha256=request_sha)
    # The controller-owned durable evidence destination is created fresh
    # BEFORE any launch, outside every remote lifecycle namespace, bound to
    # this invocation's token and both frozen hashes.  Refusal here is the
    # safe outcome: nothing has launched yet.
    token=secrets.token_hex(16)
    if evidence_root is None:
        evidence_root=str(Path.home()/'.local'/'share'/'inferswarm'
            /('q8-two-cuda-evidence-'+token))
    from .evidence_retention import DurableEvidenceStore
    evidence_store=DurableEvidenceStore.create(evidence_root,token,
        config_sha256=config_sha,request_sha256=request_sha)
    manager=ExperimentalLeaseManager(transport or SSHTransport(),token)
    guard=SystemdCampaignGuard(envelope,manager,commands or SSHCommandRunner())
    if runner_factory is None:
        from .runtime import JSONHTTP, OperatorRunner, ssh_tunnel
        from .native_observer.collector import NativeObserverCollector
        runner=OperatorRunner(SupervisedSourceTransport(manager,digest_cache=source_digest_cache,
            force_fresh=force_fresh_source_hash),manager,JSONHTTP(),ssh_tunnel,
            collector=NativeObserverCollector(transport=SupervisedCollectorTransport(manager),selective=True))
    else:
        runner=runner_factory(manager)
    # Experimental path only: the runner preserves raw evidence into the
    # controller-owned store on every exit path.
    runner.evidence=evidence_store
    runner.evidence_transport=(evidence_transport if evidence_transport is not None
                               else guard.commands)
    result={}; failure=None; interrupted=None
    try: result=runner._execute_two_gpu_diagnostic(plan,plan.admission,campaign_guard=guard)
    except (KeyboardInterrupt,SystemExit) as exc:
        # Catchable interruption: owned cleanup already ran inside the
        # driver's finally path.  Finalize the evidence manifest, then
        # re-raise the original interrupt unchanged -- retention failure
        # must never mask it, and no recovery is promised past this point.
        interrupted=exc
        result=dict(guard.execution_result or {})
        result.update(status='INTERRUPTED',error=str(exc) or 'interrupted',
                      error_type=type(exc).__name__,raw_response=guard.raw_response)
    except Exception as exc:
        failure=exc
        result=dict(guard.execution_result)
        result.update(status='STOPPED',error=str(exc),error_type=type(exc).__name__,
                      raw_response=guard.raw_response)
    # Finalize durable retention on EVERY catchable exit path (success,
    # campaign failure, raised error, KeyboardInterrupt/SystemExit) and
    # record its honest summary separately from execution/observation/
    # cleanup outcomes.  Never allowed to mask or replace the campaign's
    # own result or exception.  (No recovery from SIGKILL or power loss.)
    evidence_summary=evidence_store.finalize()
    result.update(evidence_retention=evidence_summary)
    if source_digest_cache is not None:
        result['source_digest_cache']=dict(getattr(runner.source,'digest_cache_stats',{}),
            path=source_digest_cache,force_fresh=force_fresh_source_hash)
    result.update(schema='q8-two-gpu-experimental-campaign/1',
        experimental_opt_in=True,output_accepted=False,physical_qualified=False,
        execution_authorized=False,experimental_execution_authorized=True,
        normal_admission_status=envelope.normal_admission_status,
        normal_technical_feasibility=envelope.normal_technical_feasibility,
        normal_execution_ready=envelope.normal_execution_ready,
        unknown_allocations=list(envelope.unknown_allocations),limits=dict(envelope.limits),
        request_sha256=envelope.request_sha256,config_sha256=envelope.config_sha256,
        frozen_request=dict(plan.request),gpu_bindings=dict(envelope.gpu_bindings),
        attempts=1,request_attempts=guard.request_attempts,restarts=0,
        helper_receipts=manager.helper_receipts,spawn_receipts=manager.spawn_receipts,
        verified_backing=guard.verified_backing,cleanup=runner.last_cleanup,
        final_aggregate_receipts=getattr(guard,'final_aggregates',{}))
    if interrupted is not None:
        result.update(samples=list(guard._samples),
            last_aggregate_observations=guard.last_aggregates,
            last_gpu_observations=guard.last_gpu_rows,
            last_host_available=guard.last_host_available,
            monitor_failure=str(guard._monitor_error) if guard._monitor_error is not None else None)
        raise interrupted
    if failure is not None:
        result.update(samples=list(guard._samples),
            last_aggregate_observations=guard.last_aggregates,
            last_gpu_observations=guard.last_gpu_rows,
            last_host_available=guard.last_host_available,
            monitor_failure=str(guard._monitor_error) if guard._monitor_error is not None else None)
        raise ExperimentalCampaignError(result,failure) from failure
    return result
