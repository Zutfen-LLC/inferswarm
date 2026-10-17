"""Tokenized, exact-PID/start-time leases for processes created by one invocation.

Only the configured lifecycle directory is mutated. The on-host helper runs
locally for CPU fixtures and over SSH for ordinary operator execution.
"""
from __future__ import annotations
import json
import ctypes
import errno
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import time


_CHILDREN={}


def pidfd(pid):
    if hasattr(os,'pidfd_open'): return os.pidfd_open(pid)
    # Linux syscall fallback for Python builds lacking the os.pidfd_* wrappers.
    libc=ctypes.CDLL(None,use_errno=True)
    fd=libc.syscall(434,pid,0)
    if fd<0: raise OSError(ctypes.get_errno(),'pidfd_open failed')
    return fd


def pidfd_term(fd):
    if hasattr(signal,'pidfd_send_signal'): return signal.pidfd_send_signal(fd,signal.SIGTERM)
    libc=ctypes.CDLL(None,use_errno=True)
    rc=libc.syscall(424,fd,signal.SIGTERM,0,0)
    if rc<0: raise OSError(ctypes.get_errno(),'pidfd_send_signal failed')


def identity(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()
    except FileNotFoundError: return None
    if fields[0]=='Z': return None
    return fields[19]


def _owned_listening(pid, bind, port):
    """Inspect this process's LISTEN socket, without opening an RPC connection."""
    try:
        family=socket.AF_INET
        try: wanted=socket.inet_pton(family,bind)
        except OSError:
            family=socket.AF_INET6
            wanted=socket.inet_pton(family,bind)
        owned=set()
        for fd in (Path('/proc')/str(pid)/'fd').iterdir():
            try: target=os.readlink(fd)
            except FileNotFoundError: continue  # fd closed while inspecting
            if target.startswith('socket:[') and target.endswith(']'):
                owned.add(target[8:-1])
        table='tcp' if family==socket.AF_INET else 'tcp6'
        for line in (Path('/proc')/str(pid)/'net'/table).read_text().splitlines()[1:]:
            fields=line.split()
            address,hex_port=fields[1].split(':')
            if fields[3]!='0A' or int(hex_port,16)!=port or fields[9] not in owned:
                continue
            raw=bytes.fromhex(address)
            if family==socket.AF_INET:
                actual=raw[::-1]
            else:
                actual=b''.join(raw[i:i+4][::-1] for i in range(0,16,4))
            if actual==wanted or actual==bytes(len(wanted)):
                return True
    except FileNotFoundError:
        return False  # process/socket disappeared during inspection
    return False


def _onhost(p):
    root=Path(p['root']); marker=root/'active'; token=p['token']; action=p['action']
    if action=='admit':
        root.mkdir(parents=True,exist_ok=True)
        try: marker.mkdir()
        except FileExistsError as exc: raise ValueError('lease already exists; no prior run touched') from exc
        try:
            (marker/'token').write_text(token,encoding='ascii')
            (root/token).mkdir()
        except BaseException:
            # This invocation alone just created the empty marker.
            (marker/'token').unlink(missing_ok=True); marker.rmdir(); raise
        return {'lease':'admitted'}
    # Authorization precedes every record read and any signal/unlink.
    if (marker/'token').read_text(encoding='ascii')!=token: raise ValueError('lease token mismatch')
    if action=='port':
        with socket.socket() as s:
            try: s.bind((p['bind'],p['port']))
            except OSError as exc: raise ValueError(f'port occupied/unavailable: {p["bind"]}:{p["port"]}') from exc
        return {'port':'available'}
    if action=='write':
        # #314 demand-capture prompt staging: bounded exclusive-create inside
        # the OWNED invocation directory only; never an arbitrary path.
        import base64 as _b64
        target=Path(p['path'])
        root=Path(root)/token
        try: target.relative_to(root)
        except ValueError: raise ValueError('write must stay inside the owned invocation directory')
        data=_b64.b64decode(p['data'],validate=True)
        if len(data)>65536: raise ValueError('write exceeds the demand prompt bound')
        with target.open('xb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        return {'written':len(data)}
    if action=='spawn':
        name=p['name']
        if name not in ('client','rpc','rpc0','rpc1','demand'): raise ValueError('unsupported process name')
        record=marker/(name+'.json'); log=root/token/(name+'.log')
        if record.exists() or log.exists(): raise ValueError('process record/log already exists')
        env=os.environ.copy()
        if p.get('cache'): env['LLAMA_CACHE']=p['cache']
        env.pop('IS311_ASSIGNED',None)
        if p.get('assigned'): env['IS311_ASSIGNED']=p['assigned']
        if p.get('export'):
            # The observation overlay claims the directory itself via
            # O_CREAT|O_EXCL; the controller owns creating it fresh and
            # enabling the strictly observation-only emitter.
            export_root=Path(p['export']); export_root.mkdir(parents=True,exist_ok=False)
            env['IS301_EXPORT_DIR']=p['export']; env['IS301_OBSERVE']='1'
        supervision=p.get('supervision')
        if supervision is not None:
            expected={'unit','memory_max_bytes','memory_swap_max_bytes','runtime_max_seconds'}
            optional={'slice','cuda_visible_devices'}
            if (not isinstance(supervision,dict) or not expected<=set(supervision)
                    or set(supervision)-expected-optional):
                raise ValueError('supervision fields must be exact')
            unit=supervision['unit']
            if (not isinstance(unit,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.service',unit)
                    or any(type(supervision[k]) is not int or supervision[k]<0
                           for k in expected-{'unit'})
                    or supervision['memory_max_bytes']<1
                    or supervision['runtime_max_seconds']<1):
                raise ValueError('invalid systemd supervision envelope')
            log.touch(exist_ok=False)
            command=['sudo','-n','systemd-run','--quiet','--unit='+unit,
                '--uid='+str(os.getuid()),'--gid='+str(os.getgid()),
                '--property=TimeoutStopSec=10',
                '--property=Type=simple','--property=KillMode=control-group',
                '--property=MemoryMax='+str(supervision['memory_max_bytes']),
                '--property=MemorySwapMax='+str(supervision['memory_swap_max_bytes']),
                '--property=RuntimeMaxSec='+str(supervision['runtime_max_seconds']),
                '--property=StandardOutput=append:'+str(log),
                '--property=StandardError=append:'+str(log)]
            if 'slice' in supervision:
                if not re.fullmatch(r'[A-Za-z0-9_.-]+\.slice',supervision['slice']):
                    raise ValueError('invalid owned slice')
                command.append('--slice='+supervision['slice'])
            if 'cuda_visible_devices' in supervision:
                command.append('--setenv=CUDA_VISIBLE_DEVICES='+supervision['cuda_visible_devices'])
            for key in ('LLAMA_CACHE','IS311_ASSIGNED','IS301_EXPORT_DIR','IS301_OBSERVE'):
                if key in env: command.append('--setenv='+key+'='+env[key])
            command.extend(('--',*p['argv']))
            try:
                started=subprocess.run(command,capture_output=True,text=True,timeout=30)
                if started.returncode:
                    raise RuntimeError('systemd-run failed: '+started.stderr[-500:])
                pid=None; deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    shown=subprocess.run(['sudo','-n','systemctl','show',unit,
                        '--property=MainPID','--value'],capture_output=True,text=True,timeout=10)
                    if shown.returncode:
                        raise RuntimeError('systemctl show failed: '+shown.stderr[-500:])
                    value=shown.stdout.strip()
                    if value.isdecimal() and int(value)>0:
                        pid=int(value); break
                    time.sleep(.05)
                if pid is None: raise ValueError('systemd service did not publish MainPID')
                child=None
            except BaseException:
                subprocess.run(['sudo','-n','systemctl','stop',unit],
                               capture_output=True,text=True,timeout=30)
                raise

        else:
            with log.open('xb') as f:
                child=subprocess.Popen(p['argv'],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                                       close_fds=True,start_new_session=True,env=env)
        try:
            child_pid=pid if supervision is not None else child.pid
            start=identity(child_pid)
            if start is None: raise ValueError('child exited during launch')
            row={'pid':child_pid,'start':start,'token':token}
            if supervision is not None: row['supervision']=supervision
            with record.open('x',encoding='ascii') as f:
                json.dump(row,f); f.flush(); os.fsync(f.fileno())
        except BaseException:
            # Even failure to record cannot leave an intentionally untracked child.
            if supervision is not None:
                subprocess.run(['sudo','-n','systemctl','stop',unit],capture_output=True,
                               text=True,timeout=30)
            elif identity(child.pid) is not None:
                child.terminate()
                try: child.wait(timeout=2)
                except subprocess.TimeoutExpired: raise RuntimeError(f'unrecorded child may remain pid={child.pid}')
            raise
        if child is not None: _CHILDREN[child.pid]=child
        return row
    if action in ('alive','listening','log','inspect','stop','release'):
        if action=='log':
            if p['name'] not in ('client','rpc','rpc0','rpc1'): raise ValueError('unsupported log')
            return {'text':(root/token/(p['name']+'.log')).read_text(errors='replace')[-2000000:]}
        if action=='release':
            for rec in marker.glob('*.json'):
                row=json.loads(rec.read_text()); current=identity(row['pid'])
                child=_CHILDREN.get(row['pid'])
                if child is not None and current is None: child.poll(); _CHILDREN.pop(row['pid'],None)
                if row['token']!=token or current==row['start']: raise ValueError('owned process still alive or record mismatch')
            for rec in marker.glob('*.json'): rec.unlink()
            (marker/'token').unlink(); marker.rmdir()
            return {'lease':'released'}
        name=p['name']
        if name not in ('client','rpc','rpc0','rpc1'): raise ValueError('unsupported process name')
        row=json.loads((marker/(name+'.json')).read_text())
        if row['token']!=token or row['pid']!=p['pid'] or row['start']!=p['start']:
            raise ValueError('ownership record mismatch')
        if action=='inspect':
            if 'supervision' not in row: raise ValueError('process is not systemd-supervised')
            unit=row['supervision']['unit']
            fields=('MainPID','ActiveState','Result','MemoryCurrent','MemoryPeak',
                    'MemorySwapCurrent','MemoryMax','MemorySwapMax','RuntimeMaxUSec','KillMode','ControlGroup')
            shown=subprocess.run(['sudo','-n','systemctl','show',unit,
                *('--property='+field for field in fields)],capture_output=True,text=True,timeout=10)
            if shown.returncode:
                raise RuntimeError('systemctl inspect failed: '+shown.stderr[-500:])
            values={}
            for line in shown.stdout.splitlines():
                key,sep,value=line.partition('=')
                if sep and key in fields: values[key]=value
            if set(values)!=set(fields): raise ValueError('incomplete systemd supervision receipt')
            return {'unit':unit,'properties':values}
        current=identity(row['pid'])
        if action=='alive': return {'alive':current==row['start']}
        if action=='listening':
            listening=current==row['start'] and _owned_listening(row['pid'],p['bind'],p['port'])
            return {'listening':listening and identity(row['pid'])==row['start']}
        if 'supervision' in row:
            unit=row['supervision']['unit']
            fields=('ActiveState','Result','ExecMainCode','ExecMainStatus','MemoryPeak',
                    'MemorySwapCurrent','MemoryMax','MemorySwapMax')
            try:
                shown=subprocess.run(['sudo','-n','systemctl','show',unit,
                    *('--property='+field for field in fields)],capture_output=True,text=True,timeout=10)
                if shown.returncode:
                    raise RuntimeError('systemctl final receipt failed: '+shown.stderr[-500:])
                properties={}
                for line in shown.stdout.splitlines():
                    key,sep,value=line.partition('=')
                    if sep and key in fields: properties[key]=value
                if set(properties)!=set(fields): raise ValueError('incomplete final systemd receipt')
            finally:
                stopped=subprocess.run(['sudo','-n','systemctl','stop',unit],capture_output=True,
                                       text=True,timeout=30)
                if stopped.returncode:
                    raise RuntimeError('systemctl stop failed: '+stopped.stderr[-500:])
            return {'signal':'systemd-stop','unit':unit,'properties':properties}
        if current!=row['start']: return {'exit':'absent-or-recycled'}
        # pidfd pins the observed PID; recheck /proc identity after opening fd.
        fd=pidfd(row['pid'])
        try:
            if identity(row['pid'])!=row['start']: return {'exit':'absent-or-recycled'}
            pidfd_term(fd)
        except OSError as exc:
            if exc.errno==errno.ESRCH: return {'exit':'absent-or-recycled'}
            raise
        finally: os.close(fd)
        return {'signal':'TERM'}
    raise ValueError('unsupported lifecycle action')


class LocalTransport:
    def call(self,address,payload): return _onhost(payload)


class SSHTransport:
    """A non-interactive, argv-only SSH transport; no remote installation needed."""
    def call(self,address,payload):
        script=Path(__file__).read_text(encoding='utf-8')+'\ntry:\n print(json.dumps(_onhost(json.load(sys.stdin))))\nexcept Exception as exc:\n print(json.dumps({"error":str(exc)}))\n sys.exit(1)\n'
        proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',address,
                             'python3 -c '+shlex.quote(script)],input=json.dumps(payload),text=True,
                            capture_output=True,timeout=45)
        try: result=json.loads(proc.stdout)
        except ValueError as exc: raise RuntimeError(f'SSH lifecycle transport failed: {proc.stderr[-300:]}') from exc
        if proc.returncode or 'error' in result: raise RuntimeError(f'SSH lifecycle action failed: {result.get("error",proc.stderr[-300:])}')
        return result


class LeaseManager:
    def __init__(self,transport,token,stop_timeout=10):
        self.transport=transport; self.token=token; self.stop_timeout=stop_timeout; self.leases={}; self.owned={}

    def _call(self,address,action,**kwargs):
        return self.transport.call(address,{'action':action,'root':self.leases[address],
                                            'token':self.token,**kwargs})

    def acquire(self,address,root):
        if address in self.leases: raise ValueError('duplicate host lease')
        result=self.transport.call(address,{'action':'admit','root':root,'token':self.token})
        self.leases[address]=root; self.owned[address]={}
        return result

    def port(self,address,bind,port): return self._call(address,'port',bind=bind,port=port)
    def invocation_dir(self,address):
        return str(Path(self.leases[address])/self.token)

    def spawn(self,address,name,argv,cache=None,export=None,assigned=None):
        result=self._call(address,'spawn',name=name,argv=list(argv),cache=cache,export=export,assigned=assigned)
        self.owned[address][name]=result
        return result

    def alive(self,address,name):
        row=self.owned[address][name]
        return self._call(address,'alive',name=name,pid=row['pid'],start=row['start'])['alive']

    def listening(self,address,name,bind,port):
        row=self.owned[address][name]
        return self._call(address,'listening',name=name,pid=row['pid'],start=row['start'],
                          bind=bind,port=port)['listening']

    def log(self,address,name): return self._call(address,'log',name=name)['text']

    def inspect(self,address,name):
        row=self.owned[address][name]
        return self._call(address,'inspect',name=name,pid=row['pid'],start=row['start'])

    def cleanup(self):
        outcomes={}
        for address in list(self.leases)[::-1]:
            result={}; ok=True
            for name,row in list(self.owned[address].items())[::-1]:
                try:
                    result[name]=self._call(address,'stop',name=name,pid=row['pid'],start=row['start'])
                    deadline=time.monotonic()+self.stop_timeout
                    while self.alive(address,name) and time.monotonic()<deadline: time.sleep(.02)
                    if self.alive(address,name):
                        result[name]={'error':'owned process did not exit before timeout'}; ok=False
                except Exception as exc:
                    result[name]={'error':str(exc)}; ok=False
            if ok:
                try: result.update(self._call(address,'release'))
                except Exception as exc: result['lease']='retained-incomplete'; result['error']=str(exc)
                else:
                    del self.leases[address]; del self.owned[address]
            else: result['lease']='retained-incomplete'
            outcomes[address]=result
        return outcomes
