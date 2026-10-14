"""Ordinary startup's assigned backing admission; compact CPU/native loader only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from issue99_artifact_core import LocalFileSource
from issue311_preparation import DiskBudget, StreamingNode, StreamingArtifactCache, backing_usage
from issue311_native_backing import prepare_q8_participant
from inferswarm.operator import source
from inferswarm.operator.assigned_backing import CONTRACT, project_payload, role_identity
from inferswarm.operator.lifecycle import LeaseManager, LocalTransport
from inferswarm.operator.runtime import OperatorRunner
from inferswarm.operator.profiles import freeze
from inferswarm.operator.native_observer.collector import NativeObserverCollector, CollectorError
from tests import test_issue299_source as fixture
text=fixture.text; digest=fixture.digest
from tests.test_native_cache import Relay, child_limits


class LocalSources:
    def __init__(self,payload): self.payload=payload; self.receipts=[]
    def verify(self,part,plan,fnv_binary=None):
        if fnv_binary: source.compile_fnv(fnv_binary)
        selected=next(p for p in self.payload['participants'] if p['participant_id']==part.participant_id)
        if part.role=='remote':
            receipt=source.verify_assigned_envelope(source.assigned_verification_envelope(self.payload,selected,fnv_binary))
        else: receipt=source.verify_q8_role(selected,self.payload,fnv_binary)
        self.receipts.append(receipt)
        return receipt


class LocalCollector:
    def read_json(self,address,path,**kwargs): return json.loads(Path(path).read_text())
    def read_bytes(self,address,path,**kwargs): return Path(path).read_bytes()


class AssignedSourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.Q8Source(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.cached(); self.payload=self.fixture.payload
        self.node=StreamingNode('B',StreamingArtifactCache(self.fixture.root/'backing'))
        self.budget=DiskBudget(4<<20,0,32768)
        self.origin=LocalFileSource(source_id='origin',root=self.fixture.root)
        prepare_q8_participant(payload=self.payload,epoch=1,executable=self.fixture.runtime,
            executable_sha256=self.fixture.remote['runtime_sha256'],node=self.node,
            origin_source=self.origin,budget=self.budget)
        self.selective=copy.deepcopy(self.payload)
        self.selective['source_contract']=CONTRACT
        self.selective['participants'][1]['backing']=[]
        self.selective['participants'][1]['cache_path']=str(self.node.cache.root)
        project_payload(self.selective,dict(epoch=1,memory_id='B-disk',**vars(self.budget)))

    def test_assigned_verification_needs_no_worker_gguf_and_includes_small_objects(self):
        p=self.selective['participants'][1]; p['source_path']='/absent-worker/member-0.gguf'
        r=source.verify_q8_role(p,self.selective)
        self.assertEqual(r['verified_members'],[]); self.assertEqual(r['header_identities'],[])
        self.assertEqual(r['assigned_count'],4); self.assertEqual(r['eligible_cache_ranges'],0)
        self.assertEqual(len(list(self.node.cache.root.glob('assigned-*.txt'))),1)
        self.assertFalse(r['cache_consumed'])
        self.assertEqual(source.verify_q8_role(p,self.selective)['range_identities'],r['range_identities'])

    def test_worker_wire_contains_only_assigned_tensor_dependencies(self):
        p=self.selective['participants'][1]
        envelope=source.assigned_verification_envelope(self.selective,p,None)
        self.assertNotIn('token_embd.weight',json.dumps(envelope))
        self.assertNotIn('header_identities',json.dumps(envelope))
        r=source.verify_assigned_envelope(envelope)
        self.assertEqual(r['verified_members'],[])
        result=subprocess.run([sys.executable,'-c',Path(source.__file__).read_text()],input=json.dumps(envelope),capture_output=True,text=True,timeout=10,cwd=self.node.cache.root)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['range_identities'],r['range_identities'])

    def test_corrupt_metadata_backing_guard_budget_and_runtime_refuse(self):
        p=self.selective['participants'][1]
        for mutate,reason in [
            (lambda v:v['backing_budget'].update(reserve_bytes=0),'repair reserve'),
            (lambda v:v['backing_budget'].update(limit_bytes=1),'disk budget'),
            (lambda v:v['prepared_metadata']['runtime'].update(rpc_major=6),'runtime identity'),
            (lambda v:v['prepared_metadata']['tensors'][0].update(shape=[64]),'metadata object|tensor identity')]:
            v=copy.deepcopy(self.selective); mutate(v)
            with self.assertRaisesRegex(ValueError,reason): source.verify_q8_role(v['participants'][1],v)
        r=source.verify_q8_role(p,self.selective)
        guard=Path(r['assigned_guard_path']); guard.write_text('corrupt')
        with self.assertRaisesRegex(ValueError,'guard identity'): source.verify_q8_role(p,self.selective)
        guard.unlink()
        file=self.node.cache.root/'objects'/('sha256-'+p['cache_ranges'][0]['sha256'])
        file.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'backing identity'): source.verify_q8_role(p,self.selective)

    def test_coordinator_still_authenticates_complete_source(self):
        c=self.selective['participants'][0]
        r=source.verify_q8_role(c,self.selective)
        self.assertEqual(len(r['verified_members']),6)
        (self.fixture.root/'member-3.gguf').unlink()
        with self.assertRaises(OSError): source.verify_q8_role(c,self.selective)

    def test_finite_build_identity_refuses_foreign_and_swapped_executable(self):
        collector=NativeObserverCollector(transport=LocalCollector(),selective=True)
        with self.assertRaises((CollectorError,ValueError)):
            collector.collect_build(SimpleNamespace(role='remote',participant_id='B',execution_address='B',runtime_sha256='0'*64),
                ROOT/'tests/fixtures/issue299/round2-native/ggml-rpc-server.build-manifest.json',self.fixture.runtime)

    def test_normal_q8_plan_accepts_finite_cpu_contract_and_charges_backing(self):
        from tests.test_issue299_q8_plan import q8_mapping
        from tests.issue299_fixture import NOW, reseal_profiles, profile_digest, sha
        from inferswarm.operator.config import parse_config
        from inferswarm.operator.plan import build_plan
        raw=q8_mapping('cpu-only')
        options=raw['strategy_options']; options.update(source_contract=CONTRACT,rpc_cache='enabled',
            participant_backing=dict(epoch=1,memory_id='B-disk',limit_bytes=256<<30,min_free_bytes=1<<30,reserve_bytes=128<<30),
            observer=dict(client_manifest_path='/reviewed/client.json',client_executable_path='/reviewed/llama-server',remote_manifest_path='/reviewed/remote.json',remote_executable_path='/reviewed/ggml-rpc-server'))
        remote=raw['participants'][1]; remote['backing']=[]
        for row in raw['placement']:
            if row['binding_id']=='binding-A-cpu': continue
            for d in row['state_ranges']:
                remote['cache_ranges'].append(dict(**d,unit_id=row['unit_id'],sha256=sha({'synthetic':d['state_id']}),cache_key=format(len(remote['cache_ranges'])+1,'016x'),source_id=raw['model']['source_id'],revision=raw['model']['revision'],representation='Q8_0'))
        for p in raw['participants']: p['runtime_sha256']=role_identity(p['role']).executable_sha256
        snapshot=raw['profiles']['snapshot']
        for runtime in snapshot['runtime_capabilities']:
            p=next(p for p in raw['participants'] if p['host_id']==runtime['host_id'])
            runtime['binary_sha256']=p['runtime_sha256']
            e=next(e for e in snapshot['evidence'] if e['evidence_id']==runtime['evidence_id'])
            e['dependencies']['runtime:'+runtime['runtime_id']+':binary_sha256']=p['runtime_sha256']
        reseal_profiles(snapshot); raw['profiles']['digest']=profile_digest(snapshot)
        plan=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        payload=source.q8_source_payload(plan)
        self.assertEqual(payload['source_contract'],CONTRACT)
        self.assertEqual(payload['participants'][1]['backing'],[])
        charges={r.allocation_id:r for r in plan.candidate.charges}
        self.assertEqual(charges['remote-receive-staging/load'].bytes,1<<20)
        self.assertEqual(charges['remote-receive-staging/serve'].bytes,1<<20)
        self.assertEqual(charges['FNV-cache-message-staging/load'].bytes,352)
        for prefix,mid in (('', 'B-ram'),('coordinator-', 'A-ram')):
            for phase in ('load','serve','cleanup'):
                metadata=charges[prefix+'assigned-metadata-and-guard/'+phase]
                layout=charges[prefix+'assigned-descriptor-layout/'+phase]
                self.assertEqual((metadata.memory_id,metadata.bytes),(mid,2<<20))
                self.assertEqual((layout.memory_id,layout.bytes),(mid,None))
        self.assertEqual(charges['prepared-backing-budget/load'].bytes,256<<30)
        self.assertFalse(any(k.startswith('source-backing:B:') for k in charges))
        self.assertFalse(any(k.startswith('full-tensor-cache-hit-vector') for k in charges))
        self.assertFalse(plan.admission.execution_ready)
        raw['participants'][1]['runtime_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'binding runtime binary mismatch|unreviewed per-role runtime identity'):
            build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)



@unittest.skipUnless(os.environ.get('NATIVE_ASSIGNED_BUILD'),'retained explicit CPU operator build required')
class NativeAssignedStartupTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.Q8Source(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.build=Path(os.environ['NATIVE_ASSIGNED_BUILD'])
        self.bin=self.build/'build/bin'
        self.payload=self.fixture.payload
        # Genuine GGUF split fields/types consumed by the pinned loader; compact
        # synthetic F32 tensors exercise uploads without constructing a model.
        total=len(self.payload['metadata']['tensors'])
        for number,(name,_,_) in enumerate(self.payload['model']['members']):
            ts=[t for t in self.payload['metadata']['tensors'] if t['member']==name]
            pairs=[('general.architecture',8,'llama'),('split.no',2,number),
                   ('split.count',2,6),('split.tensors.count',5,total)]
            header=b'GGUF'+struct.pack('<IQQ',3,len(ts),len(pairs))
            for key,typ,value in pairs:
                header+=text(key)+struct.pack('<I',typ)+(text(value) if typ==8 else struct.pack('<H' if typ==2 else '<i',value))
            lengths=[34*20*20000 if t['state_id']=='blk.45.ffn_up_exps.weight' else 12<<20 for t in ts]
            shapes=[[640,20000] if t['state_id']=='blk.45.ffn_up_exps.weight' else [lengths[i]//4] for i,t in enumerate(ts)]
            for i,t in enumerate(ts):
                quant=t['state_id']=='blk.45.ffn_up_exps.weight'
                header+=text(t['state_id'])+struct.pack('<I',len(shapes[i]))+struct.pack('<'+'Q'*len(shapes[i]),*shapes[i])+struct.pack('<IQ',8 if quant else 0,sum(lengths[:i]))
            start=(len(header)+31)//32*32
            with (self.root/name).open('wb') as stream:
                stream.write(header+b'\0'*(start-len(header)))
                for i,t in enumerate(ts):
                    seed=hashlib.sha256(t['state_id'].encode()).digest()
                    block=(seed*2048)
                    for _ in range(lengths[i]//len(block)): stream.write(block)
                    stream.write(block[:lengths[i]%len(block)])
            size=(self.root/name).stat().st_size; full=source.sha(self.root/name)
            self.payload['model']['members'][number]=[name,full,size]
            self.payload['metadata']['header_identities'][number]=[name,0,len(header)-1,hashlib.sha256(header).hexdigest(),size,full]
            for i,t in enumerate(ts):
                quant=t['state_id']=='blk.45.ffn_up_exps.weight'
                t.update(ggml_type=8 if quant else 0,shape=shapes[i],relative_offset=sum(lengths[:i]),absolute_offset=start+sum(lengths[:i]),encoded_bytes=lengths[i])
                a=next(a for a in self.payload['assignments'] if a['state_id']==t['state_id'])
                a.update({k:t[k] for k in ('ggml_type','shape','absolute_offset','encoded_bytes')})
                for row in self.payload['placement']:
                    for span in row['state_ranges']:
                        if span[0]==t['state_id']: span[2:]=[t['absolute_offset'],t['encoded_bytes']]
        meta=self.payload['metadata']; meta['model_metadata']=[['general.architecture','llama']]
        meta['metadata_digest']=digest({k:v for k,v in meta.items() if k!='metadata_digest'})
        for p in self.payload['participants']:
            p['runtime_executable']=str(self.bin/('llama-server' if p['role']=='client' else 'ggml-rpc-server'))
            p['runtime_sha256']=source.sha(p['runtime_executable'])
            self.assertEqual(p['runtime_sha256'],role_identity(p['role']).executable_sha256)
            p['backing']=[dict(memory_id=p['host_id']+'-disk',member=n,sha256=h,size_bytes=s) for n,h,s in self.payload['model']['members']]
        self.payload['rpc_cache']=True
        self.payload['participants'][1]['bindings']=self.payload['participants'][1]['bindings'][:1]
        for a in self.payload['assignments']:
            if a['binding_id']=='B-gpu': a.update(binding_id='B-cpu',memory_id='B-cpu-mem')
        for row in self.payload['placement']:
            if row['binding_id']=='B-gpu': row['binding_id']='B-cpu'
        self.helper=self.root/'fnv'; source.compile_fnv(self.helper)
        self.node=StreamingNode('B',StreamingArtifactCache(self.root/'prepared'))
        self.budget=DiskBudget(192<<20,0,96<<20)
        self.origin=LocalFileSource(source_id='origin',root=self.root)
        self.results=[]

    def tearDown(self):
        if os.environ.get('NATIVE_ASSIGNED_RESULTS'):
            Path(os.environ['NATIVE_ASSIGNED_RESULTS']).write_text(json.dumps(self.results,indent=2)+'\n')

    def descriptors(self):
        p=self.payload['participants'][1]; p['cache_ranges']=[]
        for row in self.payload['placement']:
            if row['binding_id']!='B-cpu': continue
            for name,member,off,length in row['state_ranges']:
                temporary=self.root/'range'
                with (self.root/member).open('rb') as stream,temporary.open('wb') as out:
                    stream.seek(off)
                    for _ in range(length//65536): out.write(stream.read(65536))
                    out.write(stream.read(length%65536))
                p['cache_ranges'].append(dict(state_id=name,member=member,offset=off,length=length,sha256=source.sha(temporary),cache_key=source.fnv(temporary,str(self.helper)),source_id=p['source_id'],revision=p['source_revision'],representation=p['source_representation'],unit_id=row['unit_id']))
                temporary.unlink()

    def prepare(self,epoch):
        self.descriptors()
        p=self.payload['participants'][1]
        return prepare_q8_participant(payload=self.payload,epoch=epoch,executable=p['runtime_executable'],executable_sha256=p['runtime_sha256'],node=self.node,origin_source=self.origin,budget=self.budget,fnv_binary=str(self.helper))

    def startup_load(self,epoch,negative=None):
        payload=copy.deepcopy(self.payload); payload['source_contract']=CONTRACT
        payload['participants'][1].update(backing=[],cache_path=str(self.node.cache.root),source_path='/absent-worker/member-0.gguf')
        project_payload(payload,dict(epoch=epoch,memory_id='B-disk',**vars(self.budget)))
        parts=[]
        for p in payload['participants']:
            obj=SimpleNamespace(**p); obj.execution_address=p['host_id']; obj.lifecycle_dir=str(self.root/('lease-'+p['role']))
            parts.append(obj)
        client,remote=parts
        options=dict(source_contract=CONTRACT,rpc_cache='enabled',observer={})
        for p in parts:
            options['observer'][p.role+'_manifest_path']=str(self.build/(Path(p.runtime_executable).name+'.build-manifest.json'))
            options['observer'][p.role+'_executable_path']=p.runtime_executable
        plan=SimpleNamespace(strategy_options=freeze(options))
        leases=LeaseManager(LocalTransport(),os.urandom(16).hex())
        sources=LocalSources(payload)
        runner=OperatorRunner(sources,leases,None,None,collector=NativeObserverCollector(transport=LocalCollector(),selective=True))
        relay=None
        try:
            for p in (remote,client): leases.acquire(p.execution_address,p.lifecycle_dir)
            receipts=runner._verify_profiled_sources(plan,client,remote)
            with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            argv=[remote.runtime_executable,'--host','127.0.0.1','--port',str(port),'--cache','--device','CPU','--threads','2']
            runner._spawn_profiled_rpc(plan,remote,argv,receipts)
            deadline=time.monotonic()+5
            while not leases.listening('B','rpc','127.0.0.1',port):
                if not leases.alive('B','rpc') or time.monotonic()>deadline: self.fail(leases.log('B','rpc'))
                time.sleep(.02)
            relay=Relay(port)
            env=dict(os.environ,IS311_ASSIGNED=receipts['A']['assigned_guard_path'],GGML_NO_BACKTRACE='1')
            if negative: env['IS311_FIXTURE_'+negative]='1'
            command=[str(self.bin/'is311-loader'),f'127.0.0.1:{relay.port}',str(self.root/'member-0.gguf'),*[str(self.root/n) for n,_,_ in payload['model']['members']]]
            result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20,preexec_fn=child_limits)
            if negative:
                self.assertNotEqual(result.returncode,0)
                self.assertIn('unsupported immutable upload boundary/identity',result.stderr)
                self.results.append(dict(refused_native_upload=negative,ordinary_owned_worker=True))
                return
            self.assertEqual(result.returncode,0,result.stderr)
            expected=len(payload['prepared_metadata']['tensors'])
            requests=[r for r in relay.requests if r['cmd']==7]
            self.assertEqual(len(requests),expected)
            declared={t['state_id']:t for t in payload['prepared_metadata']['tensors']}
            self.assertEqual({r['tensor'] for r in requests},set(declared))
            for r in requests:
                t=declared[r['tensor']]
                self.assertEqual((r['offset'],r['length'],r['type'],r['shape'],r['sha256']),
                    (0,t['encoded_bytes'],t['ggml_type'],t['shape']+[1]*(4-len(t['shape'])),t['content_sha256']))
            self.assertEqual(sum(r['size']-352 for r in relay.requests if r['cmd']==6),0)
            self.assertEqual(len([line for line in result.stdout.splitlines() if '"readback":true' in line]),expected)
            self.assertEqual(receipts['B']['verified_members'],[])
            self.assertLessEqual(backing_usage(self.node.cache.root),self.budget.limit_bytes)
            record=dict(epoch=epoch,weight_set_bytes=0,assigned=expected,exact_readback=True,
                verification_get_bytes=sum(r.get('get_bytes',0) for r in relay.requests),
                control_request_bytes=sum(r['size']+9 for r in relay.requests),
                coordinator_full_source_bytes=sum(m[2] for m in payload['model']['members']))
            self.results.append(record)
            return record
        finally:
            if relay: relay.close()
            cleanup=leases.cleanup()
            self.assertTrue(all(row.get('lease')=='released' for row in cleanup.values()),cleanup)

    def test_owned_ordinary_startup_real_loader_cold_restart_and_delta(self):
        cold=self.prepare(1)
        self.assertEqual(sum(r['length'] for r in self.origin.access_log),(36<<20)+34*20*20000)
        self.assertGreater(cold['acquisition_bytes'],(36<<20)+34*20*20000)
        self.startup_load(1).update(preparation_acquired_bytes=cold['acquisition_bytes'],weight_acquisition_bytes=(36<<20)+34*20*20000)
        self.node=StreamingNode('B',StreamingArtifactCache(self.node.cache.root))
        self.origin.access_log.clear()
        warm=self.prepare(1); self.assertEqual(warm['acquisition_bytes'],0); self.assertEqual(self.origin.access_log,[])
        self.startup_load(1).update(preparation_acquired_bytes=warm['acquisition_bytes'],weight_acquisition_bytes=0)
        # Add one formerly coordinator-local immutable tensor. Existing backing
        # remains charged; only this new range is acquired for the replacement.
        name='per_layer_token_embd.weight'
        row=next(r for r in self.payload['placement'] if name in r['state_ids'])
        span=next(r for r in row['state_ranges'] if r[0]==name)
        row['state_ids'].remove(name); row['state_ranges'].remove(span)
        remote=next(r for r in self.payload['placement'] if r['binding_id']=='B-cpu')
        remote['state_ids'].append(name); remote['state_ranges'].append(span)
        a=next(a for a in self.payload['assignments'] if a['state_id']==name)
        a.update(binding_id='B-cpu',memory_id='B-cpu-mem')
        self.origin.access_log.clear()
        delta=self.prepare(2)
        self.assertEqual(sum(r['length'] for r in self.origin.access_log),12<<20)
        self.assertGreater(delta['acquisition_bytes'],12<<20)
        self.startup_load(2).update(preparation_acquired_bytes=delta['acquisition_bytes'],weight_acquisition_bytes=12<<20)
        self.startup_load(2,negative='PARTIAL')
        self.startup_load(2,negative='DUPLICATE')
