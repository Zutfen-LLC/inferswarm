"""Offline exercise of the opt-in CLI and real bounded campaign path."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from inferswarm.operator import __main__ as cli
from inferswarm.operator import q8_experiment as experiment
from inferswarm.operator.config import parse_config_json
from inferswarm.operator.plan import build_plan
from inferswarm.operator.profiles import canonical
from inferswarm.operator.runtime import OperatorRunner
from tests import test_issue313_two_gpu as topology
from tests.issue299_fixture import NOW
from tests.test_issue311_cuda_backing import rejoin_profiles, synthetic_table


class CampaignFixture:
    def __init__(self,mode='ok'):
        self.mode=mode; self.rows={}; self.stopped=set(); self.services=set()
        self.commands=[]; self.posts=[]; self.tunnel=None; self.rejected=False
        self.failure=threading.Event()

    def call(self,address,payload):
        action=payload['action']; name=payload.get('name'); key=(address,name)
        if action=='admit': return {'lease':'admitted'}
        if action=='port': return {'port':'available'}
        if action=='spawn':
            supervision=payload['supervision']; self.services.add((address,supervision['unit']))
            # Simulate remote success and lost reply: unit is still known to the manager.
            if name=='rpc1' and self.mode=='partial': raise RuntimeError('ambiguous rpc1 spawn')
            row=dict(pid=100+len(self.rows),start='200',token=payload['token'],supervision=supervision)
            self.rows[key]=row; return row
        if action=='alive': return {'alive':key not in self.stopped}
        if action=='listening': return {'listening':True}
        if action=='inspect':
            row=self.rows[key]; supervision=row['supervision']
            return dict(properties=dict(MainPID=str(row['pid']),ActiveState='active',Result='success',
                MemoryMax=str(supervision['memory_max_bytes']),MemorySwapMax='0',
                MemorySwapCurrent='0',MemoryCurrent='1024',KillMode='control-group',
                RuntimeMaxUSec='2h 39min 59s',ControlGroup='/'+supervision['slice']+'/'+supervision['unit']))
        if action=='stop':
            self.stopped.add(key); row=self.rows[key]
            self.services.discard((address,row['supervision']['unit']))
            return dict(signal='systemd-stop',unit=row['supervision']['unit'],
                properties=dict(Result='success',MemorySwapCurrent='0'))
        if action=='release': return {'lease':'released'}
        raise AssertionError(action)

    def run(self,address,argv,**kwargs):
        self.commands.append((address,tuple(argv)))
        if argv[0]=='id': return '1000\n'
        if argv[0]=='sha256sum':
            part=next(p for p in self.plan.participants if p.execution_address==address)
            return part.runtime_sha256+'  binary\n'
        if argv[0]=='grep':
            return 'MemAvailable: '+str((1 if self.mode=='headroom' else 128)<<20)+' kB\n'
        if argv[0]=='df': return 'Avail\n'+str(70<<30)+'\n'
        if argv[0]=='nvidia-smi':
            if '--query-gpu=' in argv[1]:
                return '0, GPU-'+('a'*32)+', 2048, 99\n1, GPU-'+('b'*32)+', 2048, 99\n'
            return '\n'.join(str(row['pid'])+', GPU-'+(('a' if name=='rpc0' else 'b')*32)+', 1024'
                for (_,name),row in self.rows.items() if name.startswith('rpc'))
        if argv[0]=='tail':
            if self.mode=='allocator' and self.posts: return 'CUDA error: out of memory'
            if self.mode=='monitor' and self.posts: raise RuntimeError('monitor transport failed')
            return ''
        if argv[0]=='cat': return 'low 0\nhigh 0\nmax 29\noom 0\noom_kill 0\n'
        if argv[:3]==['sudo','-n','systemd-run']:
            unit=next(a.split('=',1)[1] for a in argv if a.startswith('--unit='))
            self.services.add((address,unit)); return ''
        if argv[:4]==['sudo','-n','systemctl','stop']:
            unit=argv[4]; self.services.discard((address,unit))
            self.failure.set(); return ''
        if argv[:4]==['sudo','-n','systemctl','show']:
            if '--property=LoadState' in argv:
                unit=argv[4]
                return 'LoadState=loaded\nActiveState='+('active' if (address,unit) in self.services else 'inactive')+'\n'
            if '--property=ActiveState' in argv:
                return 'ActiveState=inactive\nControlGroup=\n'
            worker=address==self.remote.execution_address
            cap=(10 if worker else 110)<<30
            if self.mode=='aggregate': cap-=1
            return (f'MemoryMax={cap}\nMemorySwapMax=0\nMemoryCurrent=1024\n'
                    f'MemorySwapCurrent=0\nControlGroup=/{argv[4]}\n')
        if argv[0] in ('sudo','systemctl','systemd-run'): return ''
        raise AssertionError(argv)

    def verify(self,part,plan,fnv_binary=None):
        if self.mode=='source': raise RuntimeError('source identity refused')
        result={'assigned_guard_path':'/guard/all'}
        if part.role=='remote': result.update(assigned_guard_paths={
            'binding-B-gpu0':'/guard/gpu0','binding-B-gpu1':'/guard/gpu1'},
            retained_backing_bytes=19992422784,native_repair_reserve_bytes=21582430208)
        return result

    def read(self,part,pid,**kwargs): return SimpleNamespace(pid=pid,start='200')
    def collect_build(self,*args,**kwargs): pass
    def await_terminal_export(self,*args,**kwargs): pass
    def collect_dynamic(self,*args,**kwargs):
        return SimpleNamespace(observation=SimpleNamespace(sequence=({'event':'rpc_server_command'},),
            terminal_digest='a'*64,event_count=1))
    def get(self,*args,**kwargs): return {'status':'ok'}
    def post(self,url,payload,timeout):
        self.posts.append(payload)
        if self.mode=='request': raise RuntimeError('request failed')
        if self.mode=='timeout': raise TimeoutError('request deadline')
        if self.mode in ('allocator','monitor'):
            if not self.failure.wait(8): raise AssertionError('monitor did not stop live services')
        return dict(id='one',choices=[dict(message=dict(content='unqualified'),finish_reason='stop')],
                    usage=dict(completion_tokens=1))
    def tunnel_factory(self,*args):
        fixture=self
        class Tunnel:
            done=False
            def poll(self): return 0 if self.done else None
            def terminate(self): self.done=True
            def wait(self,timeout=None): return 0
        fixture.tunnel=Tunnel(); return fixture.tunnel,8080


class ExperimentalDriverTests(unittest.TestCase):
    def setUp(self):
        self.plan=topology.TwoGpuTopologyTests().build(lambda raw: raw['strategy_options']['participant_backing'].update(
            limit_bytes=48<<30,min_free_bytes=64<<30,reserve_bytes=12<<30))
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name); self.config=root/'config.json'; self.envelope=root/'envelope.json'
        raw,manifest=topology.two_gpu_mapping()
        raw['strategy_options']['participant_backing'].update(
            limit_bytes=48<<30,min_free_bytes=64<<30,reserve_bytes=12<<30)
        self.manifest=manifest
        self.config.write_text(json.dumps(rejoin_profiles(raw)))
        self.raw=dict(schema='q8-two-cuda-experiment/1',opt_in=experiment.EXPERIMENTAL_OPT_IN,
            config_sha256=hashlib.sha256(self.config.read_bytes()).hexdigest(),
            request_sha256=hashlib.sha256(canonical(dict(self.plan.request))).hexdigest(),
            limits=dict(experiment._LIMITS),gpu_bindings=[dict(selector='CUDA0',uuid='GPU-'+'a'*32),
                                                       dict(selector='CUDA1',uuid='GPU-'+'b'*32)])

    def execute(self,mode='ok',raw=None,cli_path=False):
        self.envelope.write_text(json.dumps(self.raw if raw is None else raw))
        fixture=CampaignFixture(mode); fixture.plan=self.plan
        fixture.remote=next(p for p in self.plan.participants if p.role=='remote')
        def runner(manager):
            fixture.identity_reader=fixture
            return OperatorRunner(fixture,manager,fixture,fixture.tunnel_factory,collector=fixture)
        # Only replay time and synthetic retained identities are injected. The
        # CLI reads real config bytes, parses/builds the plan and retains its
        # blocked ordinary admission; no admission or runner method is mocked.
        def parse_fixture(text,base_dir):
            return parse_config_json(text,base_dir=base_dir,now=NOW,profile_mode='replay')
        with patch.object(experiment,'parse_config_json',side_effect=parse_fixture), \
             patch.object(experiment,'build_plan',side_effect=lambda config:build_plan(config,now=NOW)), \
             patch.object(topology.assigned_backing,'identities',return_value=synthetic_table(self.manifest)):
            if cli_path:
                original=experiment.run_experimental_campaign
                def dispatch(config,envelope):
                    return original(config,envelope,commands=fixture,transport=fixture,runner_factory=runner)
                with patch.object(experiment,'run_experimental_campaign',side_effect=dispatch), \
                     contextlib.redirect_stdout(io.StringIO()) as output, \
                     contextlib.redirect_stderr(io.StringIO()):
                    code=cli.main(['experimental-q8-two-cuda','--config',str(self.config),
                                   '--envelope',str(self.envelope)])
                return code,json.loads(output.getvalue()) if output.getvalue() else None,fixture
            try:
                result=experiment.run_experimental_campaign(self.config,self.envelope,
                    commands=fixture,transport=fixture,runner_factory=runner)
            except Exception as exc: result=exc
        return result,fixture

    def test_cli_reaches_one_real_driver_request_with_unknown_bounds(self):
        code,result,fixture=self.execute(cli_path=True)
        self.assertEqual(code,0); self.assertEqual(len(fixture.posts),1)
        self.assertTrue(result['unknown_allocations']); self.assertFalse(result['normal_execution_ready'])
        self.assertFalse(result['output_accepted']); self.assertFalse(result['physical_qualified'])
        self.assertEqual(result['campaign_observation']['after_request']['compute_attribution'],'INCONCLUSIVE')
        self.assertEqual((result['attempts'],result['restarts']),(1,0))
        self.assertFalse(fixture.services); self.assertTrue(fixture.tunnel.done)
        self.assertEqual(len(fixture.rows),3)
        for (_,name),row in fixture.rows.items():
            expected='GPU-'+'a'*32+',GPU-'+'b'*32 if name.startswith('rpc') else ''
            self.assertEqual(row['supervision']['cuda_visible_devices'],expected)

    def test_refusal_and_failure_paths_clean_up_without_retry(self):
        for mode in ('aggregate','headroom','source','partial','request','timeout','allocator','monitor'):
            with self.subTest(mode=mode):
                result,fixture=self.execute(mode)
                self.assertIsInstance(result,Exception,str(result))
                self.assertRegex(str(result),{'aggregate':'aggregate cgroup','headroom':'headroom',
                    'source':'source identity','partial':'ambiguous rpc1','request':'request failed',
                    'timeout':'request deadline','allocator':'allocator/device','monitor':'monitor'}[mode])
                self.assertFalse(fixture.services)
                self.assertLessEqual(len(fixture.posts),1)
                self.assertEqual(fixture.stopped,set(fixture.rows))
                if fixture.tunnel is not None: self.assertTrue(fixture.tunnel.done)

    def test_missing_optin_or_changed_frozen_hash_refuses_before_operations(self):
        for key,value in (('opt_in',''),('config_sha256','0'*64),('request_sha256','0'*64)):
            raw=copy.deepcopy(self.raw); raw[key]=value
            with self.subTest(key=key):
                result,fixture=self.execute(raw=raw)
                self.assertIsInstance(result,ValueError)
                self.assertEqual(fixture.commands,[]); self.assertEqual(fixture.rows,{})

    def test_systemd_duration_parser_rejects_infinite_or_unverifiable_timer(self):
        self.assertEqual(experiment._duration_usec('2h 39min 59s'),9599*1000000)
        for text in ('infinity','0','invalid'):
            if text=='0': self.assertEqual(experiment._duration_usec(text),0)
            else:
                with self.assertRaises(ValueError): experiment._duration_usec(text)

class SupervisionPrimitiveTests(unittest.TestCase):
    def test_supervised_helper_uses_same_aggregate_and_preserves_exact_input(self):
        manager=experiment.ExperimentalLeaseManager(SimpleNamespace(),'helper-token')
        guard=SimpleNamespace(checkpoint=lambda:None,remaining=lambda:100,
            uids={'worker':'1000'},gids={'worker':'1000'})
        manager.configure(guard); manager.slices['worker']='owned.slice'
        with patch.object(experiment.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            result=manager.run_helper('worker','python3 -c exact-program',input='exact-payload',timeout=50)
        argv=run.call_args.args[0]; kwargs=run.call_args.kwargs
        self.assertIn('--slice=owned.slice',argv[-1]); self.assertIn('--wait --pipe',argv[-1])
        self.assertIn('--property=RuntimeMaxSec=50',argv[-1])
        self.assertIn('--uid=1000',argv[-1]); self.assertEqual(kwargs['input'],'exact-payload')
        self.assertEqual(result.returncode,0); self.assertEqual(manager.units['worker'],[])
        self.assertEqual(manager.helper_receipts[0]['returncode'],0)

    def test_pid_discovery_failure_stops_unrecorded_systemd_service(self):
        from inferswarm.operator import lifecycle
        calls=[]
        def command(argv,**kwargs):
            calls.append(argv)
            failed=argv[:4]==['sudo','-n','systemctl','show']
            return SimpleNamespace(returncode=1 if failed else 0,stdout='',stderr='show refused')
        with tempfile.TemporaryDirectory() as root, patch.object(lifecycle.subprocess,'run',side_effect=command):
            manager=experiment.ExperimentalLeaseManager(lifecycle.LocalTransport(),'rollback')
            manager.acquire('local',root)
            with self.assertRaisesRegex(RuntimeError,'show failed'):
                manager.spawn('local','rpc0',['/rpc','--device','CUDA0'])
            self.assertTrue(any(argv[:4]==['sudo','-n','systemctl','stop'] for argv in calls))
            self.assertEqual(manager.cleanup()['local']['lease'],'released')
