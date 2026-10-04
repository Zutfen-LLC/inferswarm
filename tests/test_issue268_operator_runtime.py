"""CPU-only source, placement and ownership regressions for the ordinary path."""
import hashlib
import json
import os
from pathlib import Path
import signal
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from inferswarm.operator.config import parse_config
from inferswarm.operator.plan import build_plan
from inferswarm.operator.strategy import llama_cpp_spec
sys.path.insert(0, str(Path(__file__).parent))
from test_issue268_operator_plan import sample


def gguf(path, tensors):
    # Minimal GGUF v3: tensor name, one-dimensional F32, 32-byte data alignment.
    def string(s):
        b=s.encode(); return struct.pack('<Q', len(b))+b
    index=b''.join(string(name)+struct.pack('<IQIQ',1,len(data)//4,0,i*32)
                   for i,(name,data) in enumerate(tensors.items()))
    header=b'GGUF'+struct.pack('<IQQ',3,len(tensors),0)+index
    header+=b'\0'*((-len(header))%32)
    path.write_bytes(header+b''.join(data.ljust(32,b'\0') for data in tensors.values()))
    return {name:(len(header)+i*32,len(data)) for i,(name,data) in enumerate(tensors.items())}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.src=self.root/'model'; self.src.mkdir()
        self.member=self.src/'model.gguf'
        self.index=gguf(self.member, {'blk.45.attn.weight':b'a'*32,'output.weight':b'b'*32,
                                          'blk.45.ffn_exps.weight':b'c'*32})
        self.cache=self.root/'cache'; (self.cache/'rpc').mkdir(parents=True)
        self.bin=self.root/'binary'; self.bin.write_bytes(b'known runtime')
        self.config=sample(); m=self.config['model']; m['members']=[{'name':self.member.name,'sha256':hashlib.sha256(self.member.read_bytes()).hexdigest(),'size_bytes':self.member.stat().st_size}]
        self.config['participants'][1].update(source_path=str(self.member),runtime_executable=str(self.bin),runtime_sha256=hashlib.sha256(self.bin.read_bytes()).hexdigest(),cache_path=str(self.cache))
        self.config['participants'][0]['cache_ranges']=[]
        for p in self.config['placement'][:2]: p['state_ranges'][0]['member']=self.member.name
        self.config['placement'][0]['state_ranges'][0].update(offset=0,length=32)
        self.config['placement'][1]['state_ranges'][0].update(offset=32,length=32)
        self.config['placement'][2]['state_ids']=list(self.index)[:2]
        self.config['placement'][2]['state_ranges']=[dict(state_id=n,member=self.member.name,offset=self.index[n][0],length=self.index[n][1]) for n in list(self.index)[:2]]
        self.config['participants'][1]['cache_ranges']=[]
        for name in list(self.index)[:2]:
            offset,length=self.index[name]; content=self.member.read_bytes()[offset:offset+length]
            key=self.fnv(content); (self.cache/'rpc'/key).write_bytes(content)
            self.config['participants'][1]['cache_ranges'].append(dict(state_id=name,member=self.member.name,offset=offset,length=length,sha256=hashlib.sha256(content).hexdigest(),cache_key=key,source_id=m['source_id'],revision=m['revision'],representation=m['representation'],unit_id='unit-compute-y'))

    @staticmethod
    def fnv(content):
        h=0xcbf29ce484222325
        for b in content: h=((h^b)*0x100000001b3)&((1<<64)-1)
        return f'{h:016x}'

    def verify(self):
        from inferswarm.operator.source import verify_role
        p=build_plan(parse_config(self.config)); spec=llama_cpp_spec(p)
        return verify_role(next(x for x in p.participants if x.role=='remote'),p.model,p.placement,p.backend_options,fnv_binary=None)

    def test_verified_full_source_and_cache_metadata_and_bytes(self):
        receipt=self.verify()
        self.assertEqual(receipt['verified_members'],[self.member.name]); self.assertEqual(receipt['cache_ranges'],2)
        self.assertEqual(receipt['eligible_cache_reads'],0)

    def test_missing_or_wrong_full_member_and_runtime_rejected(self):
        for change in ('missing_member','wrong_member','wrong_runtime'):
            with self.subTest(change=change):
                if change=='missing_member': self.member.rename(self.root/'held')
                elif change=='wrong_member': self.member.write_bytes(self.member.read_bytes()+b'x')
                else: self.bin.write_bytes(b'altered')
                with self.assertRaisesRegex((ValueError,FileNotFoundError), 'member|runtime|model'):
                    self.verify()
                if change=='missing_member': (self.root/'held').rename(self.member)
                elif change=='wrong_member': self.member.write_bytes(self.member.read_bytes()[:-1])
                else: self.bin.write_bytes(b'known runtime')

    def test_descriptor_omission_or_self_consistent_misbind_rejected(self):
        self.config['participants'][1]['cache_ranges'].pop(); self.config['placement'][2]['state_ids'].pop(); self.config['placement'][2]['state_ranges'].pop()
        with self.assertRaisesRegex(ValueError,'source tensor inventory'): self.verify()
        self.setUp()
        record=self.config['participants'][1]['cache_ranges'][0]; placement=self.config['placement'][2]['state_ranges'][0]
        record['offset']+=4; record['length']-=4; placement['offset']+=4; placement['length']-=4
        with self.assertRaisesRegex(ValueError,'GGUF tensor range'): self.verify()

    def test_missing_wrong_or_misnamed_cache_rejected(self):
        for change in ('missing','wrong','key'):
            with self.subTest(change=change):
                key=self.config['participants'][1]['cache_ranges'][0]['cache_key']; path=self.cache/'rpc'/key
                data=path.read_bytes()
                if change=='missing': path.unlink()
                elif change=='wrong': path.write_bytes(b'0'*len(data))
                else: self.config['participants'][1]['cache_ranges'][0]['cache_key']='0'*16
                with self.assertRaisesRegex((ValueError,FileNotFoundError),'cache'): self.verify()
                path.write_bytes(data)
                self.config['participants'][1]['cache_ranges'][0]['cache_key']=key

    def test_native_cache_key_helper_compiles_in_invocation_dir(self):
        from inferswarm.operator.source import compile_fnv, verify_role
        helper=self.root/'invocation'/'fnv'; helper.parent.mkdir()
        compile_fnv(helper)
        p=build_plan(parse_config(self.config))
        rec=verify_role(next(x for x in p.participants if x.role=='remote'),p.model,p.placement,p.backend_options,fnv_binary=helper)
        self.assertEqual(rec['cache_ranges'],2)

    def test_cache_key_rejects_traversal(self):
        self.config['participants'][1]['cache_ranges'][0]['cache_key']='../foreign'
        with self.assertRaisesRegex(ValueError,'cache_key'): self.verify()

    def test_real_source_program_stdin_json_payload_and_negative(self):
        from inferswarm.operator import source
        plan=build_plan(parse_config(self.config))
        part=next(p for p in plan.participants if p.role=='remote')
        binary=self.root/'invocation'/'fnv-cache'; binary.parent.mkdir()
        payload=dict(participant=asdict(part),model=asdict(plan.model),
                     placement=[asdict(x) for x in plan.placement],
                     backend=asdict(plan.backend_options),fnv_binary=str(binary))
        def call(data):
            return subprocess.run([sys.executable,str(Path(source.__file__))],
                                  input=json.dumps(data),capture_output=True,text=True)
        proc=call(payload)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['cache_ranges'],2)
        self.assertTrue(binary.is_file())
        payload['fnv_binary']=None
        payload['participant']['cache_ranges'][0]['length']-=4
        proc=call(payload)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn('GGUF tensor range mismatch',proc.stderr)

    def test_source_helper_is_token_scoped_on_same_verified_config(self):
        from inferswarm.operator import source
        plan=build_plan(parse_config(self.config))
        part=next(p for p in plan.participants if p.role=='remote')
        payload=dict(participant=asdict(part),model=asdict(plan.model),
                     placement=[asdict(x) for x in plan.placement],backend=asdict(plan.backend_options))
        for token in ('first','second'):
            directory=self.root/'lease-root'/token; directory.mkdir(parents=True)
            payload['fnv_binary']=str(directory/'fnv-cache')
            proc=subprocess.run([sys.executable,str(Path(source.__file__))],
                                input=json.dumps(payload),capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['cache_ranges'],2)
            self.assertTrue((directory/'fnv-cache').is_file())

    def test_production_ssh_source_transport_executes_real_stdin_program_locally(self):
        from inferswarm.operator.runtime import SSHSourceTransport
        plan=build_plan(parse_config(self.config))
        part=next(p for p in plan.participants if p.role=='remote')
        directory=self.root/'invocation'; directory.mkdir()
        real_run=subprocess.run
        def offline_ssh(argv,**kwargs):
            self.assertEqual(argv[0],'ssh')
            command=shlex.split(argv[-1]); self.assertEqual(command[:2],['python3','-c'])
            return real_run([sys.executable,'-c',command[2]],**kwargs)
        with patch('inferswarm.operator.runtime.subprocess.run',side_effect=offline_ssh):
            receipt=SSHSourceTransport().verify(part,plan,str(directory/'fnv-cache'))
        self.assertEqual(receipt['cache_ranges'],2)
        self.assertTrue((directory/'fnv-cache').is_file())


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_foreign_lease_rejected_without_touching_state(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
        path=self.root/'host'; (path/'active').mkdir(parents=True); (path/'active'/'token').write_text('foreign')
        mgr=LeaseManager(LocalTransport(), 'ours')
        with self.assertRaisesRegex(ValueError,'lease'): mgr.acquire('host',str(path))
        self.assertEqual((path/'active'/'token').read_text(),'foreign')
        self.assertEqual(mgr.cleanup(),{})

    def test_real_owned_child_termination_releases_lease(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
        mgr=LeaseManager(LocalTransport(),'ours'); path=str(self.root/'host')
        mgr.acquire('host',path)
        result=mgr.spawn('host','client',[sys.executable,'-c','import time; time.sleep(30)'])
        self.assertTrue(mgr.alive('host','client'))
        self.assertIn('start',result)
        self.assertEqual(mgr.cleanup()['host']['lease'],'released')
        self.assertFalse((Path(path)/'active').exists())

    def test_listening_requires_exact_owned_socket_not_foreign_listener(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
        with socket.socket() as foreign:
            foreign.bind(('127.0.0.1', 0)); foreign.listen()
            port=foreign.getsockname()[1]
            mgr=LeaseManager(LocalTransport(),'owned-listener')
            mgr.acquire('host',str(self.root/'host'))
            try:
                mgr.spawn('host','rpc',[sys.executable,'-c','import time; time.sleep(30)'])
                self.assertFalse(mgr.listening('host','rpc','127.0.0.1',port))
                self.assertEqual(foreign.getsockname()[1],port)
            finally:
                self.assertEqual(mgr.cleanup()['host']['lease'],'released')

    def test_listening_detects_real_owned_tcp_socket_and_rejects_other_port(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
        mgr=LeaseManager(LocalTransport(),'owned-listener')
        mgr.acquire('host',str(self.root/'host'))
        try:
            mgr.spawn('host','rpc',[sys.executable,'-c',
                'import socket,time; s=socket.socket(); s.bind(("127.0.0.1",'+str(port)+')); s.listen(); print("ready",flush=True); time.sleep(30)'])
            for _ in range(200):
                if 'ready' in mgr.log('host','rpc'): break
                time.sleep(.01)
            else: self.fail('owned socket fixture did not bind')
            self.assertTrue(mgr.listening('host','rpc','127.0.0.1',port))
            self.assertFalse(mgr.listening('host','rpc','127.0.0.1',port+1))
            self.assertFalse(mgr.listening('host','rpc','127.0.0.2',port))
        finally:
            self.assertEqual(mgr.cleanup()['host']['lease'],'released')

    def test_production_ssh_listening_action_runs_offline_against_owned_child(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport, SSHTransport
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
        mgr=LeaseManager(LocalTransport(),'offline-ssh-listen')
        mgr.acquire('host',str(self.root/'host'))
        try:
            mgr.spawn('host','rpc',[sys.executable,'-c',
                'import socket,time; s=socket.socket(); s.bind(("127.0.0.1",'+str(port)+')); s.listen(); print("ready",flush=True); time.sleep(30)'])
            for _ in range(200):
                if 'ready' in mgr.log('host','rpc'): break
                time.sleep(.01)
            else: self.fail('owned socket fixture did not bind')
            real_run=subprocess.run
            def offline_ssh(argv,**kwargs):
                self.assertEqual(argv[0],'ssh')
                command=shlex.split(argv[-1]); self.assertEqual(command[:2],['python3','-c'])
                return real_run([sys.executable,'-c',command[2]],**kwargs)
            row=mgr.owned['host']['rpc']
            with patch('inferswarm.operator.lifecycle.subprocess.run',side_effect=offline_ssh):
                result=SSHTransport().call('host',dict(action='listening',root=str(self.root/'host'),
                     token=mgr.token,name='rpc',pid=row['pid'],start=row['start'],bind='127.0.0.1',port=port))
            self.assertTrue(result['listening'])
        finally:
            self.assertEqual(mgr.cleanup()['host']['lease'],'released')

    def test_term_ignoring_child_retains_lease(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
        mgr=LeaseManager(LocalTransport(),'ours',stop_timeout=.2); path=str(self.root/'host')
        mgr.acquire('host',path)
        row=mgr.spawn('host','rpc',[sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(30)'])
        for _ in range(100):
            if 'ready' in mgr.log('host','rpc'): break
            time.sleep(.01)
        self.assertIn('ready',mgr.log('host','rpc'))
        result=mgr.cleanup()
        self.assertEqual(result['host']['lease'],'retained-incomplete')
        self.assertEqual((Path(path)/'active'/'token').read_text(),'ours')
        os.kill(row['pid'],signal.SIGKILL)
        for _ in range(100):
            if not mgr.alive('host','rpc'): break
            time.sleep(.01)
        self.assertEqual(mgr.cleanup()['host']['lease'],'released')

    def test_pid_reuse_refuses_signal_and_partial_lease_releases(self):
        from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
        mgr=LeaseManager(LocalTransport(),'ours'); path=str(self.root/'host')
        mgr.acquire('host',path); self.assertEqual(mgr.cleanup()['host']['lease'],'released')
        mgr.token='another-invocation'; mgr.acquire('host',path)
        row=mgr.spawn('host','rpc',[sys.executable,'-c','import time; time.sleep(30)'])
        marker=Path(path)/'active'/'rpc.json'; record=json.loads(marker.read_text()); record['start']='0'; marker.write_text(json.dumps(record))
        result=mgr.cleanup()
        self.assertEqual(result['host']['lease'],'retained-incomplete')
        os.kill(row['pid'],0)
        os.kill(row['pid'],signal.SIGKILL)
        # Restore ownership only for test cleanup; previous refusal did not signal child.
        record['start']=row['start']; marker.write_text(json.dumps(record))
        for _ in range(100):
            if not mgr.alive('host','rpc'): break
            time.sleep(.01)
        self.assertEqual(mgr.cleanup()['host']['lease'],'released')


    def test_unknown_spawn_result_retains_live_record_until_exact_exit(self):
        from inferswarm.operator.lifecycle import LeaseManager,LocalTransport,_onhost
        class LostReply(LocalTransport):
            def call(self,address,payload):
                result=_onhost(payload)
                if payload['action']=='spawn': raise OSError('reply lost after spawn')
                return result
        mgr=LeaseManager(LostReply(),'ours',stop_timeout=.1)
        path=self.root/'host'; mgr.acquire('host',str(path))
        with self.assertRaisesRegex(OSError,'reply lost'):
            mgr.spawn('host','rpc',[sys.executable,'-c','import time; time.sleep(30)'])
        row=json.loads((path/'active'/'rpc.json').read_text())
        outcome=mgr.cleanup()['host']
        self.assertEqual(outcome['lease'],'retained-incomplete')
        self.assertTrue((path/'active'/'rpc.json').exists())
        os.kill(row['pid'],signal.SIGKILL)
        for _ in range(100):
            if not mgr.transport.call('host',{'action':'alive','root':str(path),'token':'ours',
                                               'name':'rpc','pid':row['pid'],'start':row['start']})['alive']: break
            time.sleep(.01)
        self.assertEqual(mgr.cleanup()['host']['lease'],'released')


class RunnerTests(SourceTests):
    """Run real plan/config + source verifier + leases; replace only transport/HTTP."""
    def setUp(self):
        super().setUp()
        self.config['participants'][0].update(source_path=str(self.member),runtime_executable=str(self.bin),runtime_sha256=hashlib.sha256(self.bin.read_bytes()).hexdigest(),cache_path=str(self.cache))
        self.config['backend_options']['rpc_physical_device']='CUDA0'
        self.config['participants'][1]['rpc_endpoint']='127.0.0.1:8081'
        self.config['participants'][0]['device']='CUDA0'; self.config['participants'][1]['device']='RPC0'
        for r in self.config['participants']:
            r['execution_address']=r['role']; r['lifecycle_dir']=str(self.root/r['role'])
        self.fixture=Path(__file__).resolve().parents[1]/'docs/implementation/two-host-mvp-255/evidence/task2/client.log'
        self.log_text='\n'.join(line for line in self.fixture.read_text().splitlines()[205:254] if 'assigned to device' in line)
        self.response_counter=0

    def runner(self, mismatch=False, lost=False, occupied=False, request_failure=False,
               rpc_ready_after=0, rpc_never_listens=False, rpc_lost_before_listen=False,
               use_helper=False):
        from inferswarm.operator.runtime import OperatorRunner
        from inferswarm.operator.source import compile_fnv, verify_role
        from inferswarm.operator.lifecycle import LeaseManager,LocalTransport
        parent=self
        class Source:
            def verify(self,part,plan,fnv_binary=None):
                if use_helper and part.role=='remote': compile_fnv(fnv_binary)
                return verify_role(part,plan.model,plan.placement,plan.backend_options,
                                   fnv_binary=fnv_binary if use_helper else None)
        class Managed(LeaseManager):
            def __init__(self):
                super().__init__(LocalTransport(),'operator-test',stop_timeout=.2)
                self.rpc_checks=0; self.client_spawned_at_rpc_check=None
            def spawn(self,address,name,argv,cache=None):
                if name=='client': self.client_spawned_at_rpc_check=self.rpc_checks
                row=super().spawn(address,name,[sys.executable,'-c','import time; time.sleep(30)'],cache)
                if lost and name=='client':
                    os.kill(self.owned['remote']['rpc']['pid'],signal.SIGTERM)
                    for _ in range(200):
                        if not self.alive('remote','rpc'): break
                        time.sleep(.01)
                    else: raise AssertionError('fixture remote child did not exit')
                return row
            def listening(self,address,name,bind,port):
                self.rpc_checks+=1
                if rpc_lost_before_listen and self.rpc_checks==1:
                    os.kill(self.owned['remote']['rpc']['pid'],signal.SIGTERM)
                    for _ in range(200):
                        if not self.alive('remote','rpc'): break
                        time.sleep(.01)
                    else: raise AssertionError('fixture remote child did not exit')
                return not rpc_never_listens and self.rpc_checks>rpc_ready_after
            def log(self,address,name):
                if name=='client':
                    return parent.log_text.replace('layer  45 assigned to device RPC0','layer  45 assigned to device CPU') if mismatch else parent.log_text
                return super().log(address,name)
            def port(self,address,bind,port):
                if occupied: raise ValueError('port occupied')
                return super().port(address,'127.0.0.1',0)
        class Tunnel:
            def __init__(self): self.stopped=False
            def poll(self): return None
            def terminate(self): self.stopped=True
            def wait(self,timeout=None): return 0
        class HTTP:
            def get(self,url,timeout): return {'status':'ok'}
            def post(self,url,data,timeout):
                if request_failure: raise ValueError('request failed')
                parent.response_counter+=1
                return {'id':f'reply-{parent.response_counter}','choices':[{'message':{'content':'Answer'},'finish_reason':'stop'}], 'usage':{'completion_tokens':1}}
        mgr=Managed(); tunnel=Tunnel()
        return OperatorRunner(Source(),mgr,HTTP(),lambda *args:tunnel,pause=lambda _:None),mgr,tunnel

    def test_one_request_verified_placement_and_bounded_cleanup(self):
        runner,mgr,tunnel=self.runner()
        result=runner.run(build_plan(parse_config(self.config)))
        self.assertEqual(result['response_id'],'reply-1')
        self.assertEqual(result['text'],'Answer')
        self.assertEqual(result['verified_backing']['remote']['cache_ranges'],2)
        self.assertEqual(len(result['observed_placement']['layers']),49)
        self.assertEqual(result['cleanup']['client']['lease'],'released')
        self.assertEqual(result['cleanup']['remote']['lease'],'released')
        self.assertTrue(tunnel.stopped)

    def test_mismatch_refused_and_tunnel_reaped(self):
        runner,mgr,tunnel=self.runner(mismatch=True)
        with self.assertRaisesRegex(ValueError,'placement mismatch'): runner.run(build_plan(parse_config(self.config)))
        self.assertTrue(tunnel.stopped); self.assertFalse(mgr.leases)

    def test_remote_loss_cannot_pass_health(self):
        runner,mgr,tunnel=self.runner(lost=True)
        with self.assertRaisesRegex(RuntimeError,'remote participant lost'):
            runner.run(build_plan(parse_config(self.config)))
        self.assertFalse(mgr.leases); self.assertTrue(tunnel.stopped)

    def test_request_failure_reaps_owned_processes_and_tunnel(self):
        runner,mgr,tunnel=self.runner(request_failure=True)
        with self.assertRaisesRegex(ValueError,'request failed'):
            runner.run(build_plan(parse_config(self.config)))
        self.assertFalse(mgr.leases); self.assertTrue(tunnel.stopped)

    def test_occupied_port_refuses_without_launch(self):
        runner,mgr,tunnel=self.runner(occupied=True)
        with self.assertRaisesRegex(ValueError,'port occupied'): runner.run(build_plan(parse_config(self.config)))
        self.assertFalse(mgr.leases)

    def test_repeat_same_config_distinct_invocation_tokens_durable_logs(self):
        plan=build_plan(parse_config(self.config))
        digests=[]; response_ids=[]; invocation_dirs=[]; helpers=[]
        for token in ('first-invocation','second-invocation'):
            runner,mgr,tunnel=self.runner(use_helper=True); mgr.token=token
            result=runner.run(plan)
            self.assertEqual(result['cleanup']['remote']['lease'],'released')
            digests.append(result['plan_digest'])
            response_ids.append(result['response_id'])
            helper=self.root/'remote'/token/'fnv-cache'
            self.assertTrue(helper.is_file())
            helpers.append(helper)
            for role in ('remote','client'):
                name='rpc.log' if role=='remote' else 'client.log'
                self.assertTrue((self.root/role/token/name).is_file())
                invocation_dirs.append(self.root/role/token)
        self.assertEqual(digests,[plan.digest,plan.digest])
        self.assertEqual(len(set(response_ids)),2)
        self.assertEqual(len(set(invocation_dirs)),4)
        self.assertEqual(len(set(helpers)),2)
        self.assertTrue(all(path.is_file() for path in helpers))
        self.assertTrue(all(path.is_dir() for path in invocation_dirs))

    def test_delayed_rpc_listen_blocks_client_launch_until_exact_ready(self):
        runner,mgr,tunnel=self.runner(rpc_ready_after=3)
        result=runner.run(build_plan(parse_config(self.config)))
        self.assertEqual(mgr.client_spawned_at_rpc_check,4)
        self.assertEqual(result['cleanup']['remote']['lease'],'released')

    def test_rpc_never_listens_times_out_before_client_launch_and_cleans_up(self):
        runner,mgr,tunnel=self.runner(rpc_never_listens=True)
        plan=build_plan(parse_config(self.config))
        plan=replace(plan,backend_options=replace(plan.backend_options,startup_timeout_seconds=1))
        runner.pause=lambda _:time.sleep(.02)
        with self.assertRaisesRegex(TimeoutError,'RPC.*listen.*timeout'):
            runner.run(plan)
        self.assertIsNone(mgr.client_spawned_at_rpc_check)
        self.assertFalse(mgr.leases); self.assertFalse(tunnel.stopped)

    def test_rpc_lost_before_listen_fails_without_client_launch(self):
        runner,mgr,tunnel=self.runner(rpc_lost_before_listen=True)
        with self.assertRaisesRegex(RuntimeError,'remote participant lost'):
            runner.run(build_plan(parse_config(self.config)))
        self.assertIsNone(mgr.client_spawned_at_rpc_check)
        self.assertFalse(mgr.leases)

    def test_startup_timeout_after_tunnel_reaps_every_owned_process(self):
        runner,mgr,tunnel=self.runner()
        runner.http.get=lambda url,timeout: {'status':'loading'}
        runner.pause=lambda _: time.sleep(.01)
        from types import SimpleNamespace
        from unittest.mock import Mock
        clock=SimpleNamespace(monotonic=Mock(side_effect=[0,0,0,100]),sleep=time.sleep)
        with patch('inferswarm.operator.runtime.time',clock):
            with self.assertRaisesRegex(TimeoutError,'startup health timeout'):
                runner.run(build_plan(parse_config(self.config)))
        self.assertFalse(mgr.leases); self.assertTrue(tunnel.stopped)

    def test_partial_acquire_lease_released_without_process(self):
        runner,mgr,tunnel=self.runner()
        (self.root/'client'/'active').mkdir(parents=True)
        (self.root/'client'/'active'/'token').write_text('foreign')
        with self.assertRaisesRegex(ValueError,'lease already exists'):
            runner.run(build_plan(parse_config(self.config)))
        self.assertFalse((self.root/'remote'/'active').exists())
        self.assertEqual((self.root/'client'/'active'/'token').read_text(),'foreign')

    def test_tunnel_termination_error_still_releases_leases(self):
        runner,mgr,tunnel=self.runner()
        def fail(): raise OSError('tunnel termination failed')
        tunnel.terminate=fail
        with self.assertRaisesRegex(RuntimeError,'SSH tunnel cleanup failed'):
            runner.run(build_plan(parse_config(self.config)))
        self.assertFalse(mgr.leases)

    def test_cli_fake_completion_from_config_parsing_through_runner(self):
        from inferswarm.operator.__main__ import main
        runner,mgr,tunnel=self.runner()
        path=self.root/'request.json'; path.write_text(json.dumps(self.config))
        out=io.StringIO()
        with patch('inferswarm.operator.runtime.OperatorRunner',return_value=runner),redirect_stdout(out):
            rc=main(['run','--config',str(path)])
        self.assertEqual(rc,0)
        self.assertEqual(json.loads(out.getvalue())['text'],'Answer')
        self.assertFalse(mgr.leases)


    def test_tunnel_exits_during_startup_with_bounded_cleanup(self):
        runner,mgr,tunnel=self.runner()
        tunnel.poll=lambda : 1
        with self.assertRaisesRegex(RuntimeError,'SSH tunnel exited during startup'):
            runner.run(build_plan(parse_config(self.config)))
        self.assertFalse(mgr.leases)

    def test_retained_cleanup_is_error_not_success(self):
        runner,mgr,tunnel=self.runner()
        original=mgr.cleanup
        def incomplete():
            result=original(); result['remote']['lease']='retained-incomplete'; return result
        mgr.cleanup=incomplete
        with self.assertRaisesRegex(RuntimeError,'incomplete owned cleanup'):
            runner.run(build_plan(parse_config(self.config)))


class CLITests(unittest.TestCase):
    def test_example_inventory_matches_retained_gguf_index_without_host_io(self):
        import re
        root=Path(__file__).resolve().parents[1]
        example=json.loads((root/'examples/ordinary-two-host.json').read_text())
        llama_cpp_spec(build_plan(parse_config(example)))
        remote=next(p for p in example['participants'] if p['role']=='remote')
        self.assertEqual(len(remote['cache_ranges']),71)
        index_path=Path('/home/zutfen/.cache/inferswarm-268/accepted-gguf-index.json')
        # #273 portability: on hosts where /home/zutfen is mode-0700 and
        # owned by another user, stat() raises EACCES for a path that is
        # not this test's subject — treat it exactly like an absent
        # retained index (offline cross-check only on retained-index
        # hosts), never as a suite error.
        try:
            retained = index_path.is_file()
        except OSError:
            retained = False
        if not retained: return
        index=json.loads(index_path.read_text())
        expected={name:(member,*tensor[:2]) for member,tensors in index.items()
                  for name,tensor in tensors.items() if
                  ((m:=re.match(r'blk\.(\d+)\.',name)) and 45<=int(m.group(1))<=47 and '_exps.' not in name)
                  or name.startswith(('output.','output_hc_'))}
        remote=next(p for p in example['participants'] if p['role']=='remote')
        actual={r['state_id']:(r['member'],r['offset'],r['length']) for r in remote['cache_ranges']}
        self.assertEqual(len(expected),71)
        self.assertEqual(actual,expected)
        self.assertEqual({r['state_id'] for p in example['placement'] if p['compute_id']==remote['compute_id']
                          for r in p['state_ranges']},set(expected))
        llama_cpp_spec(build_plan(parse_config(example)))

    def test_command_help_and_invalid_json_no_remote_work(self):
        result=subprocess.run([sys.executable,'-m','inferswarm.operator','--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('run',result.stdout)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'bad.json'; path.write_text('{not json}')
            result=subprocess.run([sys.executable,'-m','inferswarm.operator','run','--config',str(path)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('invalid config JSON',result.stderr)


if __name__=='__main__': unittest.main()
