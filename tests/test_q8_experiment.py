"""Offline exercise of the opt-in CLI and real bounded campaign path."""
import base64
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
        self.probe_timeouts=[]
        self.failure=threading.Event()
        # Synthetic remote evidence surfaces (#326 durable retention):
        # per-address filesystem of original export/claim/log bytes the
        # fixture serves to the read-only retention probes.
        self.files={}; self.exports={}; self.roots={}

    def call(self,address,payload):
        action=payload['action']; name=payload.get('name'); key=(address,name)
        if action=='admit':
            self.roots[address]=payload['root']; return {'lease':'admitted'}
        if action=='port': return {'port':'available'}
        if action=='spawn':
            supervision=payload['supervision']; self.services.add((address,supervision['unit']))
            # Simulate remote success and lost reply: unit is still known to the manager.
            if name=='rpc1' and self.mode=='partial': raise RuntimeError('ambiguous rpc1 spawn')
            row=dict(pid=100+len(self.rows),start='200',token=payload['token'],supervision=supervision)
            self.rows[key]=row
            if payload.get('export'):
                invocation=str(Path(self.roots[address])/payload['token'])
                self.exports.setdefault(address,{})[payload['export']]=self._synthetic_export(
                    address,name,payload['export'],invocation,row)
            return row
        if action=='alive': return {'alive':key not in self.stopped}
        if action=='listening': return {'listening':True}
        if action=='inspect':
            row=self.rows[key]; supervision=row['supervision']
            return dict(properties=dict(MainPID=str(row['pid']),ActiveState='active',Result='success',
                MemoryMax=str(supervision['memory_max_bytes']),MemorySwapMax='0',
                MemorySwapCurrent='0',MemoryCurrent='1024',KillMode='control-group',
                RuntimeMaxUSec='2h 39min 59s',ControlGroup='/'+supervision['slice']+'/'+supervision['unit']))
        if action=='stop':
            if self.mode=='cleanup' and name=='client' and not self.rejected:
                self.rejected=True
                raise RuntimeError('transient cleanup reply failed')
            self.stopped.add(key); row=self.rows[key]
            self.services.discard((address,row['supervision']['unit']))
            return dict(signal='systemd-stop',unit=row['supervision']['unit'],
                properties=dict(Result='success',MemorySwapCurrent='0'))
        if action=='release': return {'lease':'released'}
        raise AssertionError(action)

    def _synthetic_export(self,address,name,export_dir,invocation,row):
        """Create one process's remote export dir plus its invocation log."""
        label='ggml-rpc-server' if name.startswith('rpc') else 'llama-server'
        claim=(str(row['pid'])+'\n'+str(row['start'])+'\n'+label+'\n').encode('utf-8')
        envelope=(b'{"schema":"native-stream/1","participant_id":"'+label.encode()
                  +b'","dropped_events":0}')
        if self.mode=='evidence-malformed' and name=='rpc0':
            envelope=b'{"schema":"native-stream/1","dropped_events":'  # truncated original bytes
        files={str(Path(export_dir)/'is301-claim'):claim,
               str(Path(export_dir)/(label+'-'+str(row['pid'])+'-0000.json')):envelope,
               str(Path(invocation)/(name+'.log')):b'no owned allocator failure\n'}
        if self.mode=='evidence-symlink' and name=='rpc1':
            files[str(Path(export_dir)/'is301-claim')]=str(Path(invocation)/(name+'.log'))
        if self.mode=='evidence-oversize' and name=='rpc1':
            files[str(Path(export_dir)/(label+'-'+str(row['pid'])+'-0001.json'))]=b'x'*(9<<20)
        if self.mode=='big-log' and name=='rpc1':
            # Log larger than the 2 MB retention bound: the tail must be kept.
            files[str(Path(invocation)/(name+'.log'))]=(b'x'*(2_000_000)+b'TAIL-MARKER\n')
        self.files.setdefault(address,{}).update(files)
        return export_dir

    def _run_retention_probe(self,address,argv):
        """Answer read-only retention probes from the synthetic files."""
        import base64 as _b64, json as _json, os as _os
        program,path=argv[2],argv[3]
        tree=self.files.get(address,{})
        if 'os.listdir' in program:
            names=sorted(_os.path.basename(candidate) for candidate in tree
                         if _os.path.dirname(candidate)==path)
            if not names and not any(candidate.startswith(path+'/') for candidate in tree):
                return _json.dumps({'missing':True})
            out={}
            for file_name in names:
                full=str(_os.path.join(path,file_name))
                if isinstance(tree.get(full),str): out[file_name]={'type':'symlink'}
                else: out[file_name]={'type':'file','size':len(tree[full])}
            return _json.dumps(out)
        payload=tree[path]
        if isinstance(payload,str): raise RuntimeError('refusing to follow symlink: '+path)
        if 'os.lseek' in program:
            # Tail probe: original size line, then the LAST bound bytes.
            limit=int(argv[4])
            return (_json.dumps(len(payload))+'\n'
                    +_b64.b64encode(payload[-limit:] if limit else b'').decode('ascii'))
        return _b64.b64encode(payload[:int(argv[4])+1]).decode('ascii')

    def run(self,address,argv,**kwargs):
        self.commands.append((address,tuple(argv)))
        if argv[:2]==['python3','-c'] and len(argv)>3 and (
                'os.listdir' in argv[2] or 'base64' in argv[2]):
            self.probe_timeouts.append(kwargs.get('timeout'))
            if self.mode=='evidence-refused-rpc0' and 'os.listdir' in argv[2] \
                    and 'exports-rpc0' in argv[3]:
                # First-listener probe channel refuses; rpc1/client must survive.
                raise RuntimeError('rpc0 probe channel refused')
            return self._run_retention_probe(address,argv)
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
    def collect_dynamic(self,participant=None,spawn=None,*args,**kwargs):
        if self.mode=='dropped' and participant is not None \
                and participant.participant_id.endswith('-rpc1'):
            raise ValueError('observation dropped events refuse completeness')
        return SimpleNamespace(observation=SimpleNamespace(sequence=({'event':'rpc_server_command'},),
            terminal_digest='a'*64,event_count=1))
    def get(self,*args,**kwargs): return {'status':'ok'}
    def post(self,url,payload,timeout):
        self.posts.append(payload)
        if self.mode=='interrupt': raise KeyboardInterrupt
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
        evidence_root=Path(self.temp.name)/('evidence-'+mode)
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
                import uuid
                def dispatch(config,envelope,evidence_root=None):
                    return original(config,envelope,commands=fixture,transport=fixture,
                        runner_factory=runner,evidence_root=(evidence_root if evidence_root
                            is not None else str(Path(self.temp.name)/('evidence-'+uuid.uuid4().hex))),
                        evidence_transport=fixture)
                with patch.object(experiment,'run_experimental_campaign',side_effect=dispatch), \
                     contextlib.redirect_stdout(io.StringIO()) as output, \
                     contextlib.redirect_stderr(io.StringIO()) as error:
                    code=cli.main(['experimental-q8-two-cuda','--config',str(self.config),
                                   '--envelope',str(self.envelope)])
                return code,json.loads(output.getvalue() or error.getvalue()),fixture,evidence_root
            try:
                result=experiment.run_experimental_campaign(self.config,self.envelope,
                    commands=fixture,transport=fixture,runner_factory=runner,
                    evidence_root=str(evidence_root),evidence_transport=fixture)
            except Exception as exc: result=exc
        return result,fixture,evidence_root

    def test_cli_reaches_one_real_driver_request_with_unknown_bounds(self):
        code,result,fixture,_=self.execute(cli_path=True)
        self.assertEqual(code,0); self.assertEqual(len(fixture.posts),1)
        self.assertTrue(result['unknown_allocations']); self.assertFalse(result['normal_execution_ready'])
        self.assertFalse(result['output_accepted']); self.assertFalse(result['physical_qualified'])
        self.assertEqual(result['campaign_observation']['after_request']['compute_attribution'],'INCONCLUSIVE')
        self.assertEqual((result['attempts'],result['restarts']),(1,0))
        self.assertFalse(fixture.services); self.assertTrue(fixture.tunnel.done)
        failed_code,failed,failed_fixture,_=self.execute('timeout',cli_path=True)
        self.assertEqual(failed_code,1)
        self.assertEqual(failed['campaign']['request_attempts'],1)
        self.assertEqual(failed['campaign']['status'],'STOPPED')
        self.assertFalse(failed_fixture.services)
        self.assertEqual(len(fixture.rows),3)
        for (_,name),row in fixture.rows.items():
            expected='GPU-'+'a'*32+',GPU-'+'b'*32 if name.startswith('rpc') else ''
            self.assertEqual(row['supervision']['cuda_visible_devices'],expected)

    def test_refusal_and_failure_paths_clean_up_without_retry(self):
        for mode in ('aggregate','headroom','source','partial','request','timeout','allocator','monitor','cleanup'):
            with self.subTest(mode=mode):
                result,fixture,_=self.execute(mode)
                self.assertIsInstance(result,experiment.ExperimentalCampaignError,str(result))
                receipt=result.campaign_receipt
                self.assertEqual(receipt['status'],'STOPPED')
                self.assertEqual(receipt['config_sha256'],self.raw['config_sha256'])
                self.assertEqual(receipt['request_sha256'],self.raw['request_sha256'])
                self.assertEqual(receipt['request_attempts'],len(fixture.posts))
                self.assertTrue(receipt['unknown_allocations'])
                self.assertFalse(receipt['output_accepted'])
                self.assertIn('cleanup',receipt); self.assertIn('last_aggregate_observations',receipt)
                self.assertRegex(str(result),{'aggregate':'aggregate cgroup','headroom':'headroom',
                    'source':'source identity','partial':'ambiguous rpc1','request':'request failed',
                    'timeout':'request deadline','allocator':'allocator/device','monitor':'monitor',
                    'cleanup':'cleanup'}[mode])
                if mode=='cleanup':
                    self.assertEqual(receipt['raw_output'],'unqualified')
                    self.assertEqual(receipt['raw_response']['id'],'one')
                    self.assertEqual(receipt['response_id'],'one')
                    self.assertIn('campaign_observation',receipt)
                self.assertFalse(fixture.services)
                self.assertLessEqual(len(fixture.posts),1)
                self.assertEqual(fixture.stopped,set(fixture.rows))
                if fixture.tunnel is not None: self.assertTrue(fixture.tunnel.done)

    def test_missing_optin_or_changed_frozen_hash_refuses_before_operations(self):
        for key,value in (('opt_in',''),('config_sha256','0'*64),('request_sha256','0'*64)):
            raw=copy.deepcopy(self.raw); raw[key]=value
            with self.subTest(key=key):
                result,fixture,_=self.execute(raw=raw)
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


def summary_rows(summary,root):
    manifest=json.loads((root/'MANIFEST.json').read_text()) \
        if (root/'MANIFEST.json').exists() else {'artifacts':[]}
    return manifest['artifacts']


class DurableEvidenceRetentionTests(unittest.TestCase):
    """IS326 follow-up: raw evidence must survive every campaign exit path."""

    def setUp(self):
        self.plan=topology.TwoGpuTopologyTests().build(lambda raw: raw['strategy_options']['participant_backing'].update(
            limit_bytes=48<<30,min_free_bytes=64<<30,reserve_bytes=12<<30))
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        raw,build_manifest=topology.two_gpu_mapping()
        raw['strategy_options']['participant_backing'].update(
            limit_bytes=48<<30,min_free_bytes=64<<30,reserve_bytes=12<<30)
        config=self.root/'config.json'; self.envelope=self.root/'envelope.json'
        self.config=config; self.build_manifest=build_manifest
        config.write_text(json.dumps(rejoin_profiles(raw)))
        self.seen_timeouts=[]
        self.raw=dict(schema='q8-two-cuda-experiment/1',opt_in=experiment.EXPERIMENTAL_OPT_IN,
            config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
            request_sha256=hashlib.sha256(canonical(dict(self.plan.request))).hexdigest(),
            limits=dict(experiment._LIMITS),gpu_bindings=[dict(selector='CUDA0',uuid='GPU-'+'a'*32),
                                                       dict(selector='CUDA1',uuid='GPU-'+'b'*32)])

    def execute(self,mode='ok',raw=None):
        self.envelope.write_text(json.dumps(self.raw if raw is None else raw))
        fixture=CampaignFixture(mode); fixture.plan=self.plan
        fixture.remote=next(p for p in self.plan.participants if p.role=='remote')
        evidence_root=self.root/('evidence-'+mode)
        def runner(manager):
            fixture.identity_reader=fixture
            return OperatorRunner(fixture,manager,fixture,fixture.tunnel_factory,collector=fixture)
        def parse_fixture(text,base_dir):
            return parse_config_json(text,base_dir=base_dir,now=NOW,profile_mode='replay')
        with patch.object(experiment,'parse_config_json',side_effect=parse_fixture), \
             patch.object(experiment,'build_plan',side_effect=lambda config:build_plan(config,now=NOW)), \
             patch.object(topology.assigned_backing,'identities',return_value=synthetic_table(self.build_manifest)):
            try:
                result=experiment.run_experimental_campaign(self.config,self.envelope,
                    commands=fixture,transport=fixture,runner_factory=runner,
                    evidence_root=str(evidence_root),evidence_transport=fixture)
            except KeyboardInterrupt as exc: result=exc
            except Exception as exc: result=exc
        return result,fixture,evidence_root

    def manifest(self,evidence_root):
        return json.loads((evidence_root/'MANIFEST.json').read_text())

    def _collected(self,evidence_root,process,kind,name=None):
        rows=[row for row in self.manifest(evidence_root)['artifacts']
              if row['process']==process and row['kind']==kind
              and (name is None or row['source_path'].endswith(name))]
        return rows

    def test_normal_completed_response_retains_all_raw_evidence(self):
        result,fixture,root=self.execute('ok')
        self.assertNotIsInstance(result,Exception,str(result))
        retention=result['evidence_retention']
        self.assertTrue(retention['complete'])
        self.assertEqual(retention['response_status'],'saved')
        self.assertEqual(sorted(retention['processes']),['client','rpc0','rpc1'])
        # Complete HTTP response persisted verbatim, not extracted text only.
        saved=json.loads((root/'http-response.json').read_text())
        self.assertEqual(saved['id'],'one')
        self.assertEqual(saved['usage'],dict(completion_tokens=1))
        self.assertEqual(saved['choices'][0]['finish_reason'],'stop')
        manifest=self.manifest(root)
        response_row=manifest['response']['row']
        raw=Path(root,'http-response.json').read_bytes()
        self.assertEqual(response_row['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(response_row['size'],len(raw))
        # Every owned process contributed claim + export envelope + log bytes.
        for process in ('rpc0','rpc1','client'):
            self.assertTrue((root/process/'is301-claim').is_file())
            self.assertTrue(any(row['kind']=='export' and row['status']=='collected'
                                for row in manifest['artifacts'] if row['process']==process))
            log_rows=[row for row in manifest['artifacts']
                      if row['process']==process and row['kind']=='log']
            self.assertTrue(log_rows and all(row['status']=='collected' for row in log_rows))
            for row in log_rows:
                digest=hashlib.sha256((root/row['target']).read_bytes()).hexdigest()
                self.assertEqual(row['sha256'],digest)
        self.assertEqual(manifest['process_identities']['rpc0']['pid'],
            fixture.rows[(fixture.remote.execution_address,'rpc0')]['pid'])
        # Qualification flags unchanged.
        self.assertFalse(result['output_accepted']); self.assertFalse(result['physical_qualified'])

    def test_dropped_event_refusal_retains_response_and_malformed_bytes(self):
        # The observation refuses with the exact IS326 dropped-events
        # wording on rpc1 while rpc0 wrote a malformed export: both raw
        # surfaces must be retained before parsing.
        result,fixture,root=self.execute('evidence-malformed')
        self.assertNotIsInstance(result,Exception,str(result))
        result_dropped,fixture_dropped,root_dropped=self.execute('dropped')
        self.assertNotIsInstance(result_dropped,Exception,str(result_dropped))
        self.assertEqual(result_dropped['status'],'EXECUTED-OBSERVATION-REFUSED')
        self.assertIn('dropped events',result_dropped['observation_refusal'])
        self.assertEqual(result_dropped['evidence_retention']['response_status'],'saved')
        manifest_dropped=self.manifest(root_dropped)
        self.assertTrue(manifest_dropped['complete'])
        self.assertEqual(json.loads((root_dropped/'http-response.json').read_text())['id'],'one')
        # Malformed rpc0 export: original truncated bytes retained verbatim.
        manifest=self.manifest(root)
        kept=[row for row in manifest['artifacts'] if row['status']=='collected'
              and row['kind']=='export' and row['process']=='rpc0'
              and (root/row['target']).read_bytes()==b'{"schema":"native-stream/1","dropped_events":']
        self.assertTrue(kept)
        # The refusal path retained the answer text and raw response too.
        self.assertEqual(result['raw_output'],'unqualified')
        self.assertEqual(json.loads((root/'http-response.json').read_text())['id'],'one')

    def test_first_listener_failure_preserves_second_listener_and_client(self):
        result,fixture,root=self.execute('evidence-refused-rpc0')
        self.assertNotIsInstance(result,Exception,str(result))
        manifest=self.manifest(root)
        rpc0_rows=[row for row in manifest['artifacts'] if row['process']=='rpc0']
        self.assertTrue(rpc0_rows)
        self.assertTrue(any(row['status']=='error' for row in rpc0_rows))
        self.assertFalse(manifest['complete'])
        for process in ('rpc1','client'):
            rows=[row for row in manifest['artifacts'] if row['process']==process]
            self.assertTrue(rows and all(row['status']=='collected' for row in rows))
            self.assertTrue((root/process/'is301-claim').is_file())
        self.assertEqual(json.loads((root/'http-response.json').read_text())['id'],'one')

    def test_load_and_request_failures_retain_partial_evidence(self):
        for mode in ('partial','request','timeout','monitor','allocator'):
            with self.subTest(mode=mode):
                result,fixture,root=self.execute(mode)
                self.assertIsInstance(result,experiment.ExperimentalCampaignError)
                receipt=result.campaign_receipt
                retention=receipt['evidence_retention']
                manifest=self.manifest(root)
                spawned=set(retention['processes'])
                # Whatever spawned left process identities in the manifest.
                for process in spawned:
                    self.assertIn(process,manifest['process_identities'])
                if mode=='request':
                    # No response existed; the store records not-received honestly.
                    self.assertEqual(retention['response_status'],'not-received')
                    self.assertFalse((root/'http-response.json').exists())
                if mode in ('monitor','allocator','timeout'):
                    # Monitor failure / allocator failure / request deadline:
                    # retention still ran and never displaced cleanup, which
                    # stopped every owned service before slices were torn down.
                    self.assertIn('cleanup',receipt)
                    self.assertFalse(fixture.services)
                    self.assertEqual(fixture.stopped,set(fixture.rows))
                    self.assertIsNotNone(retention)
                self.assertIn('cleanup',receipt)
                self.assertEqual(receipt['request_attempts'],len(fixture.posts))

    def test_cleanup_failure_after_completed_response_still_retains(self):
        result,fixture,root=self.execute('cleanup')
        self.assertIsInstance(result,experiment.ExperimentalCampaignError)
        receipt=result.campaign_receipt
        self.assertEqual(receipt['raw_response']['id'],'one')
        self.assertEqual(receipt['evidence_retention']['response_status'],'saved')
        saved=json.loads((root/'http-response.json').read_text())
        self.assertEqual(saved['choices'][0]['message']['content'],'unqualified')

    def test_missing_oversize_and_symlink_evidence_stay_honest(self):
        result,fixture,root=self.execute('evidence-symlink')
        self.assertNotIsInstance(result,Exception,str(result))
        manifest=self.manifest(root)
        symlink_rows=[row for row in manifest['artifacts']
                      if row['status']=='rejected-symlink']
        self.assertTrue(symlink_rows)
        self.assertFalse(manifest['complete'])
        self.assertFalse((root/'rpc1'/'is301-claim').exists())

        result,fixture,root=self.execute('evidence-oversize')
        self.assertNotIsInstance(result,Exception,str(result))
        manifest=self.manifest(root)
        oversize=[row for row in manifest['artifacts'] if row['status']=='oversize']
        self.assertTrue(oversize)
        self.assertFalse(manifest['complete'])
        # The oversize export was never materialized.
        for row in oversize:
            self.assertIsNone(row.get('target'))
            self.assertIsNone(row.get('sha256'))

    def test_store_records_disk_write_failure_honestly(self):
        import os as _os
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        root=self.root/'ev-readonly'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        # Kill write access after creation; every artifact copy must record
        # an error row and finalize must still return an honest summary.
        _os.chmod(root,0o500)
        class Runner:
            def run(self,address,argv,*,timeout=None):
                import base64
                return base64.b64encode(b'bytes').decode('ascii')
        entry=dict(name='rpc0',address='w',export_dir='/exports/rpc0',
                   log_path='/inv/rpc0.log',pid=1,start='1')
        store.collect_processes([entry],Runner())
        summary=store.finalize()
        self.assertFalse(summary['complete'])
        self.assertTrue(all(row['status']=='error'
                            for row in summary_rows(summary,root)))
        _os.chmod(root,0o700)

    def test_store_refuses_existing_destination_and_cross_invocation(self):
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        root=self.root/'ev-store'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        with self.assertRaisesRegex(ValueError,'already exists'):
            DurableEvidenceStore.create(root,'token2',
                config_sha256='a'*64,request_sha256='b'*64)
        store.save_response({'id':'x'})
        summary=store.finalize()
        self.assertTrue(summary['complete'])
        # A second invocation targeting the same root refuses and does not
        # touch the first invocation's artifacts.
        manifest_before=(root/'MANIFEST.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'already exists'):
            DurableEvidenceStore.create(root,'token3',
                config_sha256='c'*64,request_sha256='d'*64)
        self.assertEqual((root/'MANIFEST.json').read_bytes(),manifest_before)

    def test_store_directory_permissions_and_no_manifest_leak_of_content(self):
        import os as _os
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        root=self.root/'ev-perms'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        store.save_response({'secret-user-content':'answer text'})
        store.finalize()
        self.assertEqual(_os.stat(root).st_mode & 0o777,0o700)
        for name in ('identity.json','http-response.json','MANIFEST.json'):
            self.assertEqual(_os.stat(root/name).st_mode & 0o777,0o600)
        manifest=(root/'MANIFEST.json').read_text()
        self.assertNotIn('answer text',manifest)
        self.assertNotIn('secret-user-content',manifest)

    def test_collection_deadline_and_file_budget_bounds(self):
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        root=self.root/'ev-bounds'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64,
            max_collection_seconds=0, max_files_per_process=0)
        calls=[]
        class RefusingRunner:
            def run(self,address,argv,*,timeout=None):
                calls.append(argv)
                raise RuntimeError('probe channel refused')
        entry=dict(name='rpc0',address='w',export_dir='/exports',
                   log_path='/exports/../rpc0.log',pid=1,start='1')
        store.collect_processes([entry],RefusingRunner())
        summary=store.finalize()
        self.assertFalse(summary['complete'])
        rows=self.manifest(root)['artifacts']
        self.assertTrue(any(row['status'] in ('deadline','file-limit') for row in rows))
        # The refusing channel was still attempted (bounded attempt, honest error).
        self.assertTrue(calls or rows)

    def test_no_second_request_and_single_collection(self):
        result,fixture,root=self.execute('ok')
        self.assertEqual(len(fixture.posts),1)
        # Running the campaign again with a different evidence root works and
        # does not touch the first evidence directory.
        first=(root/'MANIFEST.json').read_bytes()
        result2,fixture2,root2=self.execute('dropped')
        self.assertEqual(len(fixture2.posts),1)
        self.assertEqual((root/'MANIFEST.json').read_bytes(),first)
        self.assertNotEqual(root,root2)

    def test_collection_waits_for_all_owned_stops_including_ambiguous_spawn(self):
        """Review follow-up: retention must not precede any owned stop.

        In the lost-spawn-reply path the acknowledged rpc0 is stopped by
        leases.cleanup(), but the ambiguous rpc1 unit and the deadline
        sentinels are stopped only by after_cleanup -> stop_units /
        cleanup_budgets. Collection runs strictly after all of them.
        """
        order=[]
        result,fixture,root=self.execute('partial')
        self.assertIsInstance(result,experiment.ExperimentalCampaignError)
        receipt=result.campaign_receipt
        self.assertEqual(receipt['evidence_retention']['response_status'],'not-received')
        # Nothing owned outlives the run: the acknowledged rpc0, the
        # ambiguous rpc1 unit and both deadline sentinels were all stopped
        # (sentinels/registered units via after_cleanup -> stop_units /
        # cleanup_budgets) before the campaign error surfaced.
        self.assertFalse(fixture.services)
        manifest=self.manifest(root)
        # rpc0 (acknowledged) identities retained with its real PID; rpc1
        # never had a receipt, but its attempted role/paths are registered
        # with an honestly unknown (null) PID/start -- never fabricated.
        self.assertIn('rpc0',manifest['process_identities'])
        self.assertEqual(manifest['process_identities']['rpc0']['pid'],
            fixture.rows[(fixture.remote.execution_address,'rpc0')]['pid'])
        self.assertIn('rpc1',manifest['process_identities'])
        self.assertIsNone(manifest['process_identities']['rpc1']['pid'])
        self.assertIsNone(manifest['process_identities']['rpc1']['start'])
        # rpc1's pre-registered paths were still attempted after every stop
        # (its export dir never existed -> honest missing rows), so it is
        # not 'omitted' -- but the unknown identity and missing rows keep
        # the manifest honestly incomplete.
        rpc1_rows=[row for row in manifest['artifacts'] if row['process']=='rpc1']
        self.assertTrue(rpc1_rows)
        self.assertTrue(all(row['status']!='collected' for row in rpc1_rows))
        self.assertFalse(manifest['complete'])
        self.assertEqual(receipt['evidence_retention']['complete'],False)
        # Ordering guard: collection must run only after every stop. The
        # fixture records service removal ('systemctl stop' commands) and
        # probe commands in one shared log; no retention probe may precede
        # the last owned stop.
        stop_indexes=[index for index,(address,argv) in enumerate(fixture.commands)
                      if list(argv[:4])==['sudo','-n','systemctl','stop']]
        probe_indexes=[index for index,(address,argv) in enumerate(fixture.commands)
                       if len(argv)>3 and argv[0]=='python3' and argv[1]=='-c'
                       and ('os.listdir' in argv[2] or 'base64' in argv[2])]
        self.assertTrue(stop_indexes and probe_indexes)
        self.assertGreater(min(probe_indexes),max(stop_indexes))

    def test_existing_but_empty_export_directory_is_not_complete(self):
        """Review follow-up: an empty export dir records an honest gap."""
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        root=self.root/'ev-empty'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        import base64 as _b64
        class Runner:
            def run(self,address,argv,*,timeout=None):
                if 'os.listdir' in argv[2]:
                    return '{}'
                return _b64.b64encode(b'log bytes').decode('ascii')
        store.collect_processes([dict(name='rpc0',address='w',
            export_dir='/exports/rpc0',log_path=None,
            pid=101,start='200')],Runner())
        summary=store.finalize()
        self.assertFalse(summary['complete'])
        rows=self.manifest(root)['artifacts']
        self.assertTrue(any(row['status']=='missing' and row['kind']=='export-dir'
                            and 'no claim or envelope' in str(row.get('error'))
                            for row in rows))

    def test_reads_refuse_replaced_or_symlinked_sources(self):
        """Review follow-up: O_NOFOLLOW + regular-file check on every read."""
        import os as _os
        from inferswarm.operator.evidence_retention import DurableEvidenceStore, READ_PROGRAM
        self.assertIn('O_NOFOLLOW',READ_PROGRAM)
        self.assertIn('S_ISREG',READ_PROGRAM)
        root=self.root/'ev-nofollow'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        real=self.root/'real-target'; real.write_bytes(b'secret referent')
        link=self.root/'log-link'; _os.symlink(real,link)
        import subprocess
        proc=subprocess.run(['python3','-c',READ_PROGRAM,str(link),'64'],
                            capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0)  # symlink refused, not followed
        self.assertEqual(proc.stdout,'')

    def test_lost_launch_reply_still_attempts_registered_paths(self):
        """Correction A: pre-dispatch registration of attempted processes.

        rpc1's spawn reply is lost: its role and artifact paths were
        registered BEFORE dispatch, so retention still attempts them after
        every owned stop, the PID/start identity stays honestly null, and
        the manifest cannot claim completeness.  rpc0's acknowledged
        identity keeps its real PID.
        """
        result,fixture,root=self.execute('partial')
        self.assertIsInstance(result,experiment.ExperimentalCampaignError)
        manifest=self.manifest(root)
        self.assertIn('rpc1',manifest['process_identities'])
        identity=manifest['process_identities']['rpc1']
        self.assertIsNone(identity['pid']); self.assertIsNone(identity['start'])
        rpc1_rows=[row for row in manifest['artifacts'] if row['process']=='rpc1']
        self.assertTrue(rpc1_rows)
        self.assertTrue(all(row['status']!='collected' for row in rpc1_rows))
        self.assertFalse(manifest['complete'])
        self.assertFalse(result.campaign_receipt['evidence_retention']['complete'])
        # Acknowledged rpc0 keeps its real identity.
        self.assertEqual(manifest['process_identities']['rpc0']['pid'],
            fixture.rows[(fixture.remote.execution_address,'rpc0')]['pid'])
        # Cleanup still ran for every acknowledged/ambiguous unit first.
        self.assertFalse(fixture.services)

    def test_omitted_attempt_never_yields_complete_manifest(self):
        """Correction A (store level): an attempted process that is never
        enumerated for collection keeps complete=false -- no falsely
        complete manifest, no fabricated identity."""
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        root=self.root/'ev-omitted'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        store.register_attempt('rpc1','w','/exports/rpc1','/inv/rpc1.log')
        # finalize() without any collect_processes(): the attempted launch
        # must surface as an omission, never as completeness.
        summary=store.finalize()
        self.assertFalse(summary['complete'])
        manifest=self.manifest(root)
        self.assertEqual(manifest['omitted_processes'],['rpc1'])
        self.assertIsNone(manifest['process_identities']['rpc1']['pid'])
        self.assertIsNone(manifest['process_identities']['rpc1']['start'])

    def test_keyboard_interrupt_finalizes_manifest_then_reraises(self):
        """Correction B: catchable interruption finalizes the manifest after
        cleanup and re-raises the original KeyboardInterrupt unchanged."""
        result,fixture,root=self.execute('interrupt')
        self.assertIsInstance(result,KeyboardInterrupt)
        # Owned cleanup still ran before the interrupt surfaced.
        self.assertFalse(fixture.services)
        self.assertEqual(fixture.stopped,set(fixture.rows))
        if fixture.tunnel is not None: self.assertTrue(fixture.tunnel.done)
        # The manifest was finalized despite the interrupt: honest partial
        # record -- no response was received, but every spawned process's
        # artifacts were still collected after owned cleanup.
        manifest=self.manifest(root)
        self.assertEqual(manifest['response']['status'],'not-received')
        self.assertFalse((root/'http-response.json').exists())
        self.assertIn('rpc0',manifest['process_identities'])
        rows=[row for row in manifest['artifacts'] if row['kind']=='log']
        self.assertTrue(rows and all(row['status']=='collected' for row in rows))

    def test_oversize_log_retains_last_bounded_bytes(self):
        """Correction C: logs over the 2 MB bound keep their tail with an
        explicit truncation record; export refusal behavior is unchanged."""
        result,fixture,root=self.execute('big-log')
        self.assertNotIsInstance(result,Exception,str(result))
        manifest=self.manifest(root)
        rpc1_log=[row for row in manifest['artifacts']
                  if row['process']=='rpc1' and row['kind']=='log']
        self.assertEqual(len(rpc1_log),1)
        row=rpc1_log[0]
        self.assertEqual(row['status'],'collected')
        self.assertTrue(row['truncated'])
        self.assertEqual(row['original_size'],2_000_000+len(b'TAIL-MARKER\n'))
        self.assertEqual(row['size'],2_000_000)
        self.assertEqual(row['retained_range'],
                         [len(b'TAIL-MARKER\n'),2_000_000+len(b'TAIL-MARKER\n')])
        kept=(root/row['target']).read_bytes()
        self.assertEqual(len(kept),2_000_000)
        self.assertTrue(kept.endswith(b'TAIL-MARKER\n'))
        self.assertEqual(row['sha256'],hashlib.sha256(kept).hexdigest())
        # Smaller logs are still copied whole (rpc0, client).
        for process in ('rpc0','client'):
            log=[r for r in manifest['artifacts']
                 if r['process']==process and r['kind']=='log']
            self.assertEqual(len(log),1)
            self.assertFalse(log[0]['truncated'])
            self.assertEqual(log[0]['original_size'],log[0]['size'])
        # Export oversize refusal is unchanged: oversize exports (not logs)
        # are still rejected whole.
        result2,_,root2=self.execute('evidence-oversize')
        manifest2=self.manifest(root2)
        oversize=[r for r in manifest2['artifacts'] if r['status']=='oversize']
        self.assertTrue(oversize)
        self.assertTrue(all(r['kind']!='log' for r in oversize))
        for r in oversize:
            self.assertIsNone(r.get('target')); self.assertIsNone(r.get('sha256'))

    def test_retention_uses_campaign_absolute_deadline_not_fresh_budget(self):
        """Correction D: collection clamps to the campaign's existing
        absolute deadline; no fresh 480 s window after budget expiry."""
        from inferswarm.operator.evidence_retention import (
            DurableEvidenceStore, MANIFEST_RESERVE_SECONDS)
        root=self.root/'ev-deadline'
        store=DurableEvidenceStore.create(root,'token1',
            config_sha256='a'*64,request_sha256='b'*64,
            max_collection_seconds=480)
        clock=[1000.0]
        # Campaign budget expires at 1010; binding happens AFTER expiry
        # (slow cleanup).  Collection must not grant a fresh 480 s window.
        clock[0]=1015.0
        store.begin_collection_budget(1010.0, clock=lambda: clock[0])
        store.collect_processes([dict(name='rpc0',address='w',
            export_dir='/exports/rpc0',log_path='/inv/rpc0.log',
            pid=1,start='1')], RefusingProbeRunner(self), clock=lambda: clock[0])
        summary=store.finalize()
        self.assertFalse(summary['complete'])
        rows=self.manifest(root)['artifacts']
        self.assertTrue(rows)
        # No probe was started at all: the budget was already expired, and
        # every row honestly reflects that (error/missing/deadline cascade).
        self.assertEqual(self.seen_timeouts,[])
        self.assertTrue(all(row['status']!='collected' for row in rows),
                        [row['status'] for row in rows])
        self.assertTrue(any(row['status']=='deadline' for row in rows))
        # A healthy remaining budget clamps probe timeouts to what is left.
        root2=self.root/'ev-clamp'
        store2=DurableEvidenceStore.create(root2,'token1',
            config_sha256='a'*64,request_sha256='b'*64)
        clock2=[2000.0]
        store2.begin_collection_budget(2000.0+MANIFEST_RESERVE_SECONDS+7,
                                       clock=lambda: clock2[0])
        store2.collect_processes([dict(name='rpc0',address='w',
            export_dir='/exports/rpc0',log_path='/inv/rpc0.log',
            pid=1,start='1')], RecordingProbeRunner(self), clock=lambda: clock2[0])
        self.assertTrue(self.seen_timeouts)
        self.assertTrue(all(t<=7 for t in self.seen_timeouts),self.seen_timeouts)


class RefusingProbeRunner:
    """Probe channel that records any attempted probe as a failure."""
    def __init__(self,test=None): self.calls=0; self.test=test
    def run(self,address,argv,*,timeout=None):
        self.calls+=1
        if self.test is not None: self.test.seen_timeouts.append(timeout)
        raise RuntimeError('probe channel refused')


class RecordingProbeRunner:
    """Serves probe requests while recording the clamped timeouts."""
    def __init__(self,test): self.test=test
    def run(self,address,argv,*,timeout=None):
        self.test.seen_timeouts.append(timeout)
        if 'os.listdir' in argv[2]: return json.dumps({'missing':True})
        return base64.b64encode(b'x').decode('ascii')
