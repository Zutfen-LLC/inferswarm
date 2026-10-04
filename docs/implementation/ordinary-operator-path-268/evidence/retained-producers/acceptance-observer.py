#!/usr/bin/env python3
"""External, opt-in, instrumented ordinary operator CLI observer for issue 268.

DEFAULT DRY RUN DOES NOT CONTACT HOSTS. Execution requires a separate exact-head
approval and --execute. This is telemetry, not the product or a proof reducer.
One CLI invocation = one fresh request and independently owned lease/cleanup.
Positive PID SM samples are evidence; absent/low samples are INCONCLUSIVE.
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import runpy
import shlex
import subprocess
import sys
import threading
import time
import uuid

REPO = Path('/home/zutfen/code/is268-operator')
HEAD = '478eb5efc93476dc2be990ac738c7ddd40e11eab'
DEFAULT_CONFIG = REPO / 'examples/ordinary-two-host.json'
CLOCK = lambda: {'mono_ns': time.monotonic_ns(), 'wall_ns': time.time_ns()}


def owned_identity(expected, observed):
    return all(expected.get(k) == observed.get(k) and expected.get(k) is not None
               for k in ('pid', 'start', 'token'))


def request_gpu_evidence(window, roles, samples):
    hits = {}
    for role, owned in roles.items():
        hits[role] = [s for s in samples if s.get('role') == role and
                      owned_identity(owned, s) and isinstance(s.get('sm'), int) and
                      s['sm'] > 0 and s.get('identity_before') == owned['start'] and
                      s.get('identity_after') == owned['start'] and
                      s.get('identity_observed') == owned['start'] and
                      s.get('gpu_inventory_exit') == 0 and s.get('inventory_authentic') is True and
                      s.get('probe_status') == 0 and
                      isinstance(s.get('gpu_index'), int) and
                      s['gpu_index'] == s.get('device_mapping', {}).get('physical_index') and
                      window['start_mono_ns'] <= s.get('before_mono_ns', -1) and
                      s.get('after_mono_ns', 10**30) <= window['end_mono_ns']]
    return {'status': 'positive-pid-sm-samples' if len(hits) == 2 and all(hits.values())
            else 'inconclusive', 'matched_samples_per_role': {k: len(v) for k, v in hits.items()},
            'caveat': 'pmon is sampled, not per-kernel tracing; zero/missing samples do not prove absence'}


def parse_gpu_inventory(raw):
    """Reject any incomplete or ambiguous inventory rather than dropping rows."""
    inventory = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(',')]
        if (len(parts) != 3 or not parts[0].isdigit() or
            not parts[1].startswith('GPU-') or len(parts[1]) <= 4 or not parts[2]):
            raise ValueError('incomplete GPU inventory row')
        inventory.append({'index': int(parts[0]), 'uuid': parts[1], 'pci_bus_id': parts[2]})
    if (not inventory or any(len({row[key] for row in inventory}) != len(inventory)
                             for key in ('index', 'uuid', 'pci_bus_id'))):
        raise ValueError('empty or ambiguous GPU inventory')
    return inventory

def resolve_device(device, env, inventory):
    """Fail closed unless CUDA ordinal resolves to one inventoried physical GPU."""
    mapping = {'logical_device': device, 'visible': env.get('CUDA_VISIBLE_DEVICES'),
               'order': env.get('CUDA_DEVICE_ORDER'), 'inventory': inventory,
               'physical_index': None, 'method': 'unresolved'}
    match = re.fullmatch(r'CUDA(\d+)', device or '')
    if not match or not inventory or len({g['index'] for g in inventory}) != len(inventory):
        return mapping
    ordinal = int(match.group(1))
    visible = env.get('CUDA_VISIBLE_DEVICES')
    if visible:
        entries = [s.strip() for s in visible.split(',')]
        if ordinal >= len(entries): return mapping
        selection = entries[ordinal]
        # UUID/UUID-prefix is independent of CUDA's default enumeration order.
        matches = [g for g in inventory if g['uuid'] == selection or
                   (selection.startswith('GPU-') and g['uuid'].startswith(selection))]
        if len(matches) == 1:
            mapping.update(physical_index=matches[0]['index'], method='visible-uuid')
            return mapping
        if not selection.isdigit(): return mapping
        ordinal = int(selection)
    if len(inventory) == 1 and ordinal == 0:
        mapping.update(physical_index=inventory[0]['index'], method='single-inventory-gpu')
    elif env.get('CUDA_DEVICE_ORDER') == 'PCI_BUS_ID' and all(g.get('pci_bus_id') for g in inventory):
        ordered = sorted(inventory, key=lambda g: g['pci_bus_id'])
        if ordinal < len(ordered):
            mapping.update(physical_index=ordered[ordinal]['index'], method='pci-bus-order')
    return mapping


def cleanup_ok(cleanup, readback, roles):
    if set(cleanup) != set(roles) or set(readback) != set(roles):
        return False
    return all(cleanup[h].get('lease') == 'released' and
               all(readback[h].get(name, {}).get('recorded') == row and
                   readback[h][name].get('identity') is None and
                   readback[h][name].get('listener') is False
                   for name, row in names.items()) for h, names in roles.items())


def cache_open(line, cache_root, keys, pid=None):
    """strace successful O_RDONLY open on a configured native-key cache path."""
    prefixed = re.search(r'^\s*\[pid\s+(\d+)\]', line)
    if pid is not None and prefixed and int(prefixed.group(1)) != pid:
        return False
    path = re.escape(str(Path(cache_root) / 'rpc'))
    match = re.search(r'\bopenat2?\([^\n]*?"(' + path + r'/([0-9a-f]{16}))"[^\n]*?\)\s*=\s*(\d+)\b', line)
    return bool(match and match.group(2) in keys and 'O_RDONLY' in line)


# Probe reads are passive except opt-in tracer launch/stop under the current
# invocation's lease directory; neither product argv nor lifecycle is changed.
PROBE = r'''
import base64,json,pathlib,subprocess,time,os,re,signal,shutil
p=json.load(__import__('sys').stdin); a=p['action']; pid=p.get('pid')
def ident(pid):
 try:
  fields=(pathlib.Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()
  return None if fields[0]=='Z' else fields[19]
 except (FileNotFoundError,ProcessLookupError): return None
def listener(port):
 for table in ('tcp','tcp6'):
  try: lines=pathlib.Path('/proc/net',table).read_text().splitlines()[1:]
  except FileNotFoundError: continue
  for line in lines:
   fields=line.split(); h=fields[1].rsplit(':',1)[-1]
   if fields[3]=='0A' and int(h,16)==port: return True
 return False
def trace_paths():
 root=pathlib.Path(p['root'])/p['token']
 if not root.is_dir() or not re.fullmatch('[0-9a-f]{32}',p['token']):
  raise ValueError('collector token directory unavailable')
 return root/'observer-cache-tracer.json',root/'observer-cache-strace.log'
def trace_command():
 timeout=shutil.which('timeout'); tracer=shutil.which('strace')
 if not timeout or not tracer: raise ValueError('timeout/strace unavailable')
 return [timeout,'-s','INT','1200',tracer,'-f','-ttt','-e','trace=openat,openat2','-p',str(p['pid'])]
def exact_authorization(cmd):
 check=subprocess.run(['sudo','-n','-l','--',*cmd],capture_output=True,text=True,timeout=15)
 result.update(permission_command=['sudo','-n','-l','--',*cmd],permission_exit=check.returncode,permission_stderr=check.stderr[-500:])
 return check.returncode==0
def group_members(pgid):
 found=[]
 for entry in pathlib.Path('/proc').iterdir():
  if not entry.name.isdigit(): continue
  try:
   fields=(entry/'stat').read_text().rsplit(') ',1)[1].split()
   if fields[0]!='Z' and int(fields[2])==pgid: found.append({'pid':int(entry.name),'start':fields[19],'session':int(fields[3])})
  except (FileNotFoundError,ProcessLookupError,PermissionError): pass
 return found
start={'remote_wall_ns':time.time_ns(),'remote_mono_ns':time.monotonic_ns()}
result={'clock_start':start}
if a=='clock': pass
elif a=='readback':
 result.update(identity=ident(pid),listener=listener(p['port']))
elif a=='log':
 path=pathlib.Path(p['root'])/p['token']/(p['name']+'.log')
 with path.open('rb') as f:
  f.seek(p['offset']); data=f.read(4000000)
 result.update(offset=p['offset'], data_b64=base64.b64encode(data).decode(), eof=path.stat().st_size==p['offset']+len(data))
elif a=='sample':
 result['identity_before']=ident(pid)
 result['identity']=result['identity_before']
 if result['identity_before']==p['start']:
  envraw=(pathlib.Path('/proc')/str(pid)/'environ').read_bytes()
  env={k:v for k,v in (entry.decode('utf-8','replace').split('=',1) for entry in envraw.split(b'\0') if b'=' in entry) if k in ('CUDA_VISIBLE_DEVICES','CUDA_DEVICE_ORDER')}
  inv=subprocess.run(['nvidia-smi','--query-gpu=index,uuid,pci.bus_id','--format=csv,noheader'],capture_output=True,text=True,timeout=12)
  result.update(gpu_inventory_raw=inv.stdout,gpu_inventory_stderr=inv.stderr,gpu_inventory_exit=inv.returncode,cuda_environment=env)
  cmd=['nvidia-smi','pmon','-c','1','-s','um']
  run=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
  result.update(pmon=run.stdout, pmon_stderr=run.stderr, pmon_exit=run.returncode)
 else: result.update(pmon='',pmon_exit=None)
 result['identity_after']=ident(pid)
elif a=='trace-check':
 if ident(pid)!=p['start']: raise ValueError('RPC identity changed before tracer permission check')
 cmd=trace_command(); exact_authorization(cmd)
 result['collector_command']=['sudo','-n',*cmd]
elif a=='trace-start':
 if ident(pid)!=p['start']: raise ValueError('RPC identity changed before tracer launch')
 record,log=trace_paths()
 if (pathlib.Path(p['root'])/'active'/'token').read_text() != p['token']:
  raise ValueError('product lease token mismatch before tracer launch')
 if record.exists() or log.exists(): raise ValueError('collector record/log already exists')
 cmd=trace_command()
 if not exact_authorization(cmd): raise ValueError('exact sudo timeout/strace authorization unavailable')
 with log.open('xb') as output:
  child=subprocess.Popen(['sudo','-n',*cmd],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=output,start_new_session=True,close_fds=True)
 try:
  begin=ident(child.pid)
  if begin is None: raise ValueError('collector exited before ownership record')
  row={'pid':child.pid,'start':begin,'token':p['token'],'pgid':child.pid,'command':['sudo','-n',*cmd]}
  with record.open('x') as f: json.dump(row,f); f.flush(); os.fsync(f.fileno())
 except BaseException:
  if ident(child.pid) is not None:
   child.terminate(); child.wait(timeout=3)
  raise
 result.update(recorded=row,collector_command=row['command'])
elif a in ('trace-stop','trace-read','trace-status'):
 record,log=trace_paths()
 if not record.exists():
  result['status']='unresolved-no-record'
 else:
  row=json.loads(record.read_text())
  if row['token']!=p['token'] or (p.get('record') is not None and row!=p['record']):
   raise ValueError('collector ownership token/record mismatch')
  result['recorded']=row
  if a=='trace-status':
   current=ident(row['pid'])
   result.update(status='active' if current==row['start'] else 'exited',identity=current,members=group_members(row['pgid']))
  elif a=='trace-read':
   with log.open('rb') as f: f.seek(p.get('offset',0)); data=f.read(4000000)
   result.update(data_b64=base64.b64encode(data).decode(),eof=log.stat().st_size==p.get('offset',0)+len(data),status='read')
  else:
   current=ident(row['pid']); result['identity_before']=current
   if current!=row['start']:
    result.update(status='recycled-or-absent',identity=current,members=group_members(row['pgid']))
   else:
    # Pin the session leader, then recheck start/PGID before signaling its
    # isolated collector session. The traced RPC is never in this session.
    fd=os.pidfd_open(row['pid'])
    try:
     fields=(pathlib.Path('/proc')/str(row['pid'])/'stat').read_text().rsplit(') ',1)[1].split()
     if fields[19]!=row['start'] or int(fields[2])!=row['pgid'] or int(fields[3])!=row['pgid']:
      raise ValueError('collector identity/session changed before signal')
     members=group_members(row['pgid'])
     if any(member['session']!=row['pgid'] for member in members): raise ValueError('foreign process in collector group')
     os.killpg(row['pgid'],signal.SIGINT)
    finally: os.close(fd)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and group_members(row['pgid']): time.sleep(.05)
    remaining=group_members(row['pgid'])
    result.update(status='stopped' if not remaining else 'unresolved-collector',identity=ident(row['pid']),members=remaining)
else: raise ValueError('unsupported read-only probe')
result['clock_end']={'remote_wall_ns':time.time_ns(),'remote_mono_ns':time.monotonic_ns()}
print(json.dumps(result))
'''


def remote_read(host, payload, timeout=20):
    before = CLOCK()
    proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                           'python3 -c ' + shlex.quote(PROBE)], input=json.dumps(payload),
                          text=True, capture_output=True, timeout=timeout)
    after = CLOCK()
    if proc.returncode:
        raise RuntimeError(f'read-only host probe {host}/{payload["action"]}: {proc.stderr[-350:]}')
    return {'local_before': before, 'local_after': after, 'remote': json.loads(proc.stdout)}


class Telemetry:
    def __init__(self, config, directory):
        self.config = config
        self.directory = directory
        self.lock = threading.Lock()
        self.events = []
        self.samples = []
        self.roles = {}
        self.logs = {}
        self.log_offsets = {}
        self.threads = []
        self.stop = threading.Event()
        self.ready = {}
        self.trace = None
        self.trace_record = None
        self.trace_attempted = False
        self.trace_cleanup = None
        self.trace_lines = []
        self.startup_trace_end = 0
        self.trace_error = None
        self.windows = []
        self.cleanup = {}
        self.errors = []
        self.hosts = {p['role']: p for p in config['participants']}

    def event(self, event, **data):
        with self.lock: self.events.append({'event': event, 'clock': CLOCK(), **data})

    def sampler(self, role, row):
        host = self.hosts[role]['execution_address']
        while not self.stop.is_set():
            try:
                obs = remote_read(host, {'action': 'sample', 'pid': row['pid'], 'start': row['start']})
                r = obs['remote']
                raw_inventory = r.get('gpu_inventory_raw', '')
                inventory_error = None
                try:
                    if r.get('gpu_inventory_exit') != 0:
                        raise ValueError('GPU inventory command failed')
                    inventory = parse_gpu_inventory(raw_inventory)
                except ValueError as exc:
                    inventory = []
                    inventory_error = str(exc)
                device = (self.config['backend_options']['rpc_physical_device'] if role == 'remote'
                          else self.hosts[role]['device']) if 'backend_options' in self.config else 'CUDA0'
                mapping = resolve_device(device, r.get('cuda_environment', {}), inventory)
                authentic = inventory_error is None and mapping['physical_index'] is not None
                identity_ok = (r.get('identity_before') == row['start'] and
                               r.get('identity_after') == row['start'])
                status = r.get('pmon_exit')
                common = {'role': role, **row,
                    'before_mono_ns': obs['local_before']['mono_ns'],
                    'after_mono_ns': obs['local_after']['mono_ns'],
                    'clock_bounds': obs, 'identity_before': r.get('identity_before'),
                    'identity_after': r.get('identity_after'),
                    'identity_observed': r.get('identity_before'),
                    'probe_status': status, 'device_mapping': mapping,
                    'gpu_inventory_raw': raw_inventory,
                    'gpu_inventory_exit': r.get('gpu_inventory_exit'),
                    'gpu_inventory_stderr': r.get('gpu_inventory_stderr'),
                    'inventory_authentic': authentic, 'inventory_error': inventory_error}
                self.samples.append({**common, 'sm': None, 'raw_pmon': r.get('pmon', ''),
                                     'cuda_environment': r.get('cuda_environment')})
                if authentic and identity_ok and status == 0:
                    for line in r.get('pmon', '').splitlines():
                        fields = line.split()
                        if len(fields) < 5 or not fields[0].isdigit() or not fields[1].isdigit() or int(fields[1]) != row['pid']:
                            continue
                        # pmon: gpu, pid, type, sm, mem, enc, dec, command.
                        sm = int(fields[3]) if fields[3].isdigit() else None
                        self.samples.append({**common, 'sm': sm, 'gpu_index': int(fields[0]),
                                             'raw_pmon_line': line})
                if not authentic or not identity_ok or status != 0:
                    self.errors.append({'role': role, 'sampling': r,
                                        'inventory_error': inventory_error,
                                        'device_mapping': mapping})
                self.ready[role].set()
            except Exception as exc:
                self.errors.append({'role': role, 'sampler_error': str(exc)})
                self.ready[role].set()
            self.stop.wait(.1)

    def start_sampler(self, role, row):
        self.ready[role] = threading.Event()
        thread = threading.Thread(target=self.sampler, args=(role, row), daemon=True)
        self.threads.append(thread)
        thread.start()

    def snapshot_log(self, role, phase):
        host = self.hosts[role]['execution_address']
        name = 'rpc' if role == 'remote' else 'client'
        row = self.roles.get(role)
        if row is None: return
        key = role + '-' + name
        offset = self.log_offsets.get(key, 0)
        while True:
            obs = remote_read(host, {'action': 'log', 'root': self.hosts[role]['lifecycle_dir'],
                                   'token': row['token'], 'name': name, 'offset': offset})
            r = obs['remote']; data = base64.b64decode(r['data_b64'])
            with (self.directory / (key + '.log')).open('ab') as file: file.write(data)
            self.logs.setdefault(key, []).append({'phase': phase, 'start_offset': offset,
                'end_offset': offset + len(data), 'clock_bounds': obs})
            offset += len(data)
            self.log_offsets[key] = offset
            if r['eof'] or not data: break

    def read_trace(self):
        if not self.trace_attempted: return
        host = self.hosts['remote']['execution_address']
        row = self.roles['remote']
        # Binary chunks are stored byte-exactly; the offset never depends on
        # decoded UTF-8 line lengths (strace may output arbitrary filenames).
        offset = getattr(self, 'trace_offset', 0)
        while True:
            obs = remote_read(host, {'action': 'trace-read', 'root': self.hosts['remote']['lifecycle_dir'],
                                    'token': row['token'], 'record': self.trace_record, 'offset': offset})
            remote = obs['remote']
            if remote.get('status') != 'read':
                raise RuntimeError('collector trace record unavailable for readback: ' + remote['status'])
            data = base64.b64decode(remote['data_b64'])
            with (self.directory / 'remote-cache-strace.log').open('ab') as file: file.write(data)
            offset += len(data)
            self.trace_offset = offset
            self.trace_lines = (self.directory / 'remote-cache-strace.log').read_text(errors='replace').splitlines(True)
            if remote['eof'] or not data: break

    def attach_trace(self, row):
        host = self.hosts['remote']['execution_address']
        observed = remote_read(host, {'action': 'readback', 'pid': row['pid'],
                                     'port': self.hosts['remote']['port']})
        if observed['remote']['identity'] != row['start']:
            raise RuntimeError('remote RPC PID/start changed before trace attachment')
        payload = {'root': self.hosts['remote']['lifecycle_dir'], 'token': row['token'],
                   'pid': row['pid'], 'start': row['start']}
        check = remote_read(host, {'action': 'trace-check', **payload})
        self.event('trace-permission-check', host=host, check=check)
        auth = check['remote']
        permission = auth.get('permission_command', [])
        launch = auth.get('collector_command', [])
        if (auth['permission_exit'] != 0 or permission[:4] != ['sudo', '-n', '-l', '--'] or
            launch[:2] != ['sudo', '-n'] or permission[4:] != launch[2:]):
            raise RuntimeError('exact collector command sudo authorization unavailable; no request allowed')
        self.trace_attempted = True
        started = remote_read(host, {'action': 'trace-start', **payload})
        self.trace_record = started['remote']['recorded']
        self.event('trace-start', host=host, result=started)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.read_trace()
            if any('attached' in line for line in self.trace_lines): break
            time.sleep(.1)
        else: raise RuntimeError('exact remote RPC PID strace attachment unavailable; no request allowed')
        observed = remote_read(host, {'action': 'readback', 'pid': row['pid'],
                                     'port': self.hosts['remote']['port']})
        if observed['remote']['identity'] != row['start']:
            raise RuntimeError('remote RPC PID/start changed after trace attachment')
        self.event('trace-attached', role='remote', identity=row, collector=self.trace_record)

    def before_request(self):
        for role in ('remote', 'client'):
            if role not in self.ready or not self.ready[role].wait(20):
                raise RuntimeError('sampler not active before request: ' + role)
        if self.errors:
            raise RuntimeError('sampling/log probe failed before request; no request allowed')
        if not self.trace_attempted and (self.trace is None or self.trace.poll() is not None):
            raise RuntimeError('remote startup cache trace not active before request')
        if self.trace_attempted:
            self.read_trace()
            row = self.roles['remote']
            observed = remote_read(self.hosts['remote']['execution_address'], {
                'action': 'trace-status', 'root': self.hosts['remote']['lifecycle_dir'],
                'token': row['token'], 'record': self.trace_record})
            if (observed['remote'].get('status') != 'active' or
                observed['remote'].get('recorded') != self.trace_record):
                raise RuntimeError('owned collector not active before HTTP request')
        for role in ('remote', 'client'): self.snapshot_log(role, 'before-request')
        self.startup_trace_end = len(self.trace_lines)

    def finish(self):
        self.stop.set()
        if self.trace_attempted:
            row = self.roles['remote']; host = self.hosts['remote']['execution_address']
            try:
                stopped = remote_read(host, {'action': 'trace-stop',
                    'root': self.hosts['remote']['lifecycle_dir'], 'token': row['token'],
                    'record': self.trace_record})
                self.trace_cleanup = stopped
                r = stopped['remote']
                if self.trace_record is None and r.get('recorded') is not None:
                    # A lost trace-start SSH acknowledgment must not discard
                    # the on-host token record recovered during cleanup.
                    self.trace_record = r['recorded']
                if (r.get('status') not in ('stopped', 'recycled-or-absent') or
                    r.get('members') or (self.trace_record is not None and r.get('recorded') != self.trace_record)):
                    self.errors.append({'unresolved_collector': r})
            except Exception as exc:
                self.errors.append({'unresolved_collector': str(exc), 'recorded': self.trace_record})
            try: self.read_trace()
            except Exception as exc: self.errors.append({'trace_read_error': str(exc)})
        local = getattr(self, 'trace_local', None)
        if local is not None:
            if local.poll() is None: local.terminate()
            try: local.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.errors.append({'unresolved_local_collector': local.pid})
        if self.trace is not None:
            try: self.trace.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.errors.append({'unresolved_collector': 'legacy trace fixture did not exit'})
        for thread in self.threads:
            if thread is not threading.current_thread(): thread.join(timeout=15)
        for role in ('remote', 'client'):
            try: self.snapshot_log(role, 'after-cleanup')
            except Exception as exc: self.errors.append({'role': role, 'log_read_error': str(exc)})
        readback = {}
        for role, row in self.roles.items():
            part = self.hosts[role]; name = 'rpc' if role == 'remote' else 'client'
            try:
                obs = remote_read(part['execution_address'], {'action': 'readback',
                    'pid': row['pid'], 'port': part['port']})
                readback.setdefault(part['execution_address'], {})[name] = {
                    'recorded': row, 'identity': obs['remote']['identity'],
                    'listener': obs['remote']['listener'], 'clock_bounds': obs}
            except Exception as exc: self.errors.append({'role': role, 'readback_error': str(exc)})
        roles_by_host = {self.hosts[k]['execution_address']:
                         {'rpc' if k == 'remote' else 'client': v} for k, v in self.roles.items()}
        return readback, cleanup_ok(self.cleanup, readback, roles_by_host)

    def result(self, cli_status, stdout, stderr, readback, clean):
        keys = {c['cache_key'] for c in self.hosts['remote']['cache_ranges']}
        root = self.hosts['remote']['cache_path']
        # The trace is startup evidence only. Do not rebrand it as per-request
        # cache compute or claim actual bytes read from an open alone.
        remote_pid = self.roles.get('remote', {}).get('pid')
        opens = [line for line in self.trace_lines[:self.startup_trace_end]
                 if remote_pid is not None and cache_open(line, root, keys, remote_pid)]
        roles = dict(self.roles)
        for window in self.windows:
            if 'end_mono_ns' in window:
                window['gpu_evidence'] = request_gpu_evidence(window, roles, self.samples)
        return {'mode': 'instrumented-ordinary-cli', 'operator_argv':
                ['python', '-m', 'inferswarm.operator', 'run', '--config', str(self.config_path)],
                'cli_exit': cli_status, 'cli_stdout': stdout, 'cli_stderr': stderr,
                'roles': self.roles, 'events': self.events, 'host_samples': self.samples,
                'request_windows': self.windows, 'logs': self.logs, 'cleanup': self.cleanup,
                'cleanup_readback': readback, 'cleanup_exact_absence': clean,
                'startup_cache_open_count': len(opens), 'startup_cache_open_lines': opens,
                'cache_trace_raw': 'remote-cache-strace.log', 'collector_identity': self.trace_record,
                'collector_cleanup': self.trace_cleanup,
                'startup_cache_status': 'observed-open-not-read-proof' if opens else 'unobserved',
                'telemetry_errors': self.errors + ([self.trace_error] if self.trace_error else [])}


def run_one(config_path, out, index, source_hashes):
    from inferswarm.operator import lifecycle, runtime
    config = json.loads(config_path.read_text())
    directory = out / ('invocation-%02d' % index)
    directory.mkdir(mode=0o700)
    telemetry = Telemetry(config, directory)
    telemetry.config_path = config_path
    telemetry.event('start', observer_invocation=uuid.uuid4().hex)
    prior_call, prior_spawn, prior_cleanup, prior_post = (lifecycle.SSHTransport.call,
        lifecycle.LeaseManager.spawn, lifecycle.LeaseManager.cleanup, runtime.JSONHTTP.post)

    def observed_call(transport, host, payload):
        telemetry.event('lifecycle-call', host=host, action=payload.get('action'),
                        name=payload.get('name'), token=payload.get('token'))
        try:
            value = prior_call(transport, host, payload)
            telemetry.event('lifecycle-result', host=host, action=payload.get('action'),
                            name=payload.get('name'), result=value)
            if payload['action'] == 'release':
                telemetry.cleanup.setdefault(host, {}).update(value)
            elif payload['action'] == 'stop':
                telemetry.cleanup.setdefault(host, {})[payload['name']] = value
            return value
        except BaseException as exc:
            telemetry.event('lifecycle-error', host=host, action=payload.get('action'),
                            error=repr(exc))
            raise

    def observed_spawn(manager, host, name, argv, cache=None):
        # Instrument only AFTER product recorded its ownership row: an
        # attachment failure still passes through product-owned cleanup.
        row = prior_spawn(manager, host, name, argv, cache=cache)
        role = 'remote' if name == 'rpc' else 'client'
        if not owned_identity(row, manager.owned[host][name]):
            raise RuntimeError('spawn identity missing/mismatched in product ownership')
        telemetry.roles[role] = row
        telemetry.start_sampler(role, row)
        if role == 'remote': telemetry.attach_trace(row)
        return row

    def observed_cleanup(manager):
        telemetry.stop.set()
        for thread in telemetry.threads:
            if thread is not threading.current_thread() and thread is not getattr(telemetry, 'trace_thread', None):
                thread.join(timeout=15)
        return prior_cleanup(manager)

    def observed_post(http, url, payload, timeout):
        telemetry.before_request()
        window = {'start_mono_ns': time.monotonic_ns(), 'start_wall_ns': time.time_ns(),
                  'url': url, 'payload_sha256': hashlib.sha256(json.dumps(payload,
                            sort_keys=True).encode()).hexdigest()}
        telemetry.windows.append(window)
        try:
            response = prior_post(http, url, payload, timeout)
            window['response_id'] = response.get('id') if isinstance(response, dict) else None
            return response
        finally:
            window.update(end_mono_ns=time.monotonic_ns(), end_wall_ns=time.time_ns())
            for role in ('remote', 'client'):
                try: telemetry.snapshot_log(role, 'after-request')
                except Exception as exc: telemetry.errors.append({'log_read_error': str(exc)})

    lifecycle.SSHTransport.call = observed_call
    lifecycle.LeaseManager.spawn = observed_spawn
    lifecycle.LeaseManager.cleanup = observed_cleanup
    runtime.JSONHTTP.post = observed_post
    stdout, stderr = io.StringIO(), io.StringIO()
    original_argv = sys.argv[:]
    status = 1
    try:
        sys.argv = ['python -m inferswarm.operator', 'run', '--config', str(config_path)]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try: runpy.run_module('inferswarm.operator', run_name='__main__', alter_sys=False)
            except SystemExit as exc: status = exc.code if isinstance(exc.code, int) else 1
    except BaseException as exc:
        stderr.write(repr(exc) + '\n')
    finally:
        sys.argv = original_argv
        lifecycle.SSHTransport.call = prior_call
        lifecycle.LeaseManager.spawn = prior_spawn
        lifecycle.LeaseManager.cleanup = prior_cleanup
        runtime.JSONHTTP.post = prior_post
        readback, clean = telemetry.finish()
        report = telemetry.result(status, stdout.getvalue(), stderr.getvalue(), readback, clean)
        report['source_sha256'] = source_hashes
        (directory / 'receipt.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def acceptance_readiness(report):
    """Conservative evidence gate; inconclusive is not a product failure."""
    if report['cli_exit'] or not report['cleanup_exact_absence'] or report['telemetry_errors']:
        return 'unproven-cli-cleanup-or-telemetry'
    if len(report['request_windows']) != 1 or not report['request_windows'][0].get('response_id'):
        return 'unproven-request'
    if report['request_windows'][0]['gpu_evidence']['status'] != 'positive-pid-sm-samples':
        return 'inconclusive-pid-gpu-sampling'
    if not report['startup_cache_open_count']:
        return 'unobserved-startup-cache-open'
    try:
        product = json.loads(report['cli_stdout'].strip())
        remote = product['verified_backing']['remote']
        if (product['response_id'] != report['request_windows'][0]['response_id'] or
            not product['text'].strip() or not product['finish_reason'] or
            not product['observed_placement']['layers'] or
            remote['backing'] != 'participant-local-cache-verified-not-yet-observed-consumed' or
            remote['eligible_cache_reads'] < 1 or
            not all(v.get('lease') == 'released' for v in product['cleanup'].values())):
            return 'product-receipt-incomplete'
    except (KeyError, TypeError, ValueError, AttributeError):
        return 'product-receipt-incomplete'
    return 'evidence-ready-for-human-review'


def accepted_config_shape(path):
    """Only unique lease directories may differ from the pinned example."""
    actual = json.loads(path.read_text())
    expected = json.loads(DEFAULT_CONFIG.read_text())
    for config in (actual, expected):
        for part in config['participants']:
            part['lifecycle_dir'] = '<operator-selected-unique-lease>'
    return actual == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('/home/zutfen/.cache/inferswarm-268/observer-output'))
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--execute', action='store_true', help='opt-in physical execution, never used for CPU tests')
    parser.add_argument('--approved-head', help='required exact source SHA for physical execution')
    parser.add_argument('--requests', type=int, default=3, choices=(3,))
    args = parser.parse_args()
    config_path = args.config.resolve(strict=True)
    sources = {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((REPO / 'inferswarm/operator').glob('*.py'))}
    sources[str(config_path)] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    git = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    if git != HEAD: parser.error('exact product head changed; observer not authorized')
    if subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain']):
        parser.error('product tree dirty; observer not authorized')
    args.out.mkdir(parents=True, exist_ok=True)
    if not args.execute:
        (args.out / 'dry-run.json').write_text(json.dumps({'mode': 'dry-run',
            'product_head': git, 'source_sha256': sources, 'config': str(config_path),
            'would_invoke': ['python', '-m', 'inferswarm.operator', 'run', '--config', str(config_path)],
            'requests': args.requests, 'fleet_contact': False}, indent=2, sort_keys=True) + '\n')
        print('DRY RUN: no SSH, no HTTP, no physical request; explicit --execute required')
        return 0
    if args.approved_head != HEAD: parser.error('explicit --approved-head must equal pinned product head')
    if 'CHANGE-ME' in config_path.read_text(): parser.error('replace example lifecycle placeholders in external config before physical execution')
    if not accepted_config_shape(config_path):
        parser.error('config differs from accepted example beyond lifecycle_dir; no physical request allowed')
    if str(REPO) not in sys.path: sys.path.insert(0, str(REPO))
    reports = []
    for index in range(1, args.requests + 1):
        report = run_one(config_path, args.out, index, sources)
        readiness = acceptance_readiness(report)
        reports.append({'index': index, 'cli_exit': report['cli_exit'],
                        'cleanup_exact_absence': report['cleanup_exact_absence'],
                        'request_windows': report['request_windows'], 'readiness': readiness})
        (args.out / 'physical.json').write_text(json.dumps({'product_head': git,
            'status': 'INCOMPLETE', 'invocations': reports}, indent=2) + '\n')
        if readiness != 'evidence-ready-for-human-review':
            print('STOP: ' + readiness + '; inspect retained receipt', file=sys.stderr)
            return 1
    print('Three instrumented CLI invocations retained; human review of raw evidence still required')
    return 0


if __name__ == '__main__': raise SystemExit(main())
