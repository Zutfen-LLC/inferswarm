"""Focused #313 two-CUDA-device planning/lowering regressions.

All profiles and build identities here are synthetic.  They prove the fixed
operator contract and native argv only; they do not prove CUDA execution.
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from inferswarm.operator import assigned_backing
from inferswarm.operator.config import parse_config
from inferswarm.operator.lifecycle import LeaseManager
from inferswarm.operator.plan import build_plan
from inferswarm.operator.phased_observation import reconcile_dynamic
from inferswarm.operator.profiles import thaw
from inferswarm.operator.profiles import freeze
from inferswarm.operator.bindings import ProcessIdentity
from inferswarm.operator.qwen_q8 import NativeQ8Options, q8_llama_cpp_spec, q8_rpc_processes
from inferswarm.operator.runtime import OperatorRunner
from inferswarm.operator import source as source_verifier
from inferswarm.operator.source import q8_source_payload
from tests.issue299_fixture import NOW, profile_digest, reseal_profiles, sha
from tests.test_issue299_q8_plan import metadata, q8_mapping
from tests.test_issue311_cuda_backing import (OBSERVER, rejoin_profiles,
    synthetic_cuda_manifest, synthetic_table)

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from issue99_artifact_core import AcquisitionError, LocalFileSource
from issue311_native_backing import prepare_q8_participant, project_q8_preparation, runtime_identity
from issue311_preparation import DiskBudget, StreamingArtifactCache, StreamingNode


def two_gpu_mapping():
    """Assigned-only dual-GPU config on one synthetic remote host."""
    raw=q8_mapping('one-gpu')
    raw['selection']='two-gpu'
    snapshot=raw['profiles']['snapshot']

    vram0=next(r for r in snapshot['memory_resources'] if r['memory_id']=='B-vram')
    vram1=copy.deepcopy(vram0)
    vram1.update(memory_id='B-vram1',physical_id='physical-B-vram1')
    vram1['evidence_id']='synthetic-B-vram1'
    snapshot['memory_resources'].append(vram1)

    gpu0=next(r for r in snapshot['compute_units'] if r['compute_id']=='B-gpu')
    gpu1=copy.deepcopy(gpu0)
    gpu1.update(compute_id='B-gpu1',physical_id='physical-B-gpu1',memory_ids=['B-vram1'])
    gpu1['evidence_id']='synthetic-B-gpu1'
    snapshot['compute_units'].append(gpu1)

    runtime0=next(r for r in snapshot['runtime_capabilities'] if r['runtime_id']=='runtime-B-gpu')
    runtime1=copy.deepcopy(runtime0)
    runtime1.update(runtime_id='runtime-B-gpu1',compute_id='B-gpu1')
    runtime1['evidence_id']='synthetic-runtime-B-gpu1'
    snapshot['runtime_capabilities'].append(runtime1)

    snapshot['compute_units']=[r for r in snapshot['compute_units'] if r['compute_id']!='B-cpu']
    snapshot['runtime_capabilities']=[r for r in snapshot['runtime_capabilities'] if r['runtime_id']!='runtime-B-cpu']
    snapshot['evidence']=[r for r in snapshot['evidence'] if r['evidence_id'] not in
        ('synthetic-B-cpu','synthetic-runtime-B-cpu')]

    evidence={r['evidence_id']:r for r in snapshot['evidence']}
    for source,row,eid in ((vram0,vram1,'synthetic-B-vram1'),
                           (gpu0,gpu1,'synthetic-B-gpu1'),
                           (runtime0,runtime1,'synthetic-runtime-B-gpu1')):
        original=evidence[source['evidence_id']]
        cloned=copy.deepcopy(original)
        cloned['evidence_id']=eid
        deps=dict(cloned['dependencies'])
        def renamed(value):
            return (value.replace('runtime-B-gpu','runtime-B-gpu1')
                    .replace('B-vram','B-vram1').replace('physical-B-gpu','physical-B-gpu1')
                    .replace('compute:B-gpu:','compute:B-gpu1:'))
        deps={renamed(k):renamed(v) if isinstance(v,str) else v for k,v in deps.items()}
        cloned['dependencies']=deps
        snapshot['evidence'].append(cloned)

    remote=raw['participants'][1]
    remote['rpc_endpoint']='synthetic-B.example:5000'
    gpu0_binding=next(b for b in remote['bindings'] if b['binding_id']=='binding-B-gpu')
    gpu0_binding.update(binding_id='binding-B-gpu0',native_selector='CUDA0',visible_selector='RPC0')
    gpu1_binding=copy.deepcopy(gpu0_binding)
    gpu1_binding.update(binding_id='binding-B-gpu1',compute_id='B-gpu1',memory_id='B-vram1',
        physical_id='physical-B-gpu1',native_selector='CUDA1',visible_selector='RPC1',
        runtime_id='runtime-B-gpu1',evidence_id='synthetic-B-gpu1')
    gpu1_binding['evidence_sha256']='0'*64
    remote['bindings']=[gpu0_binding,gpu1_binding]

    raw['strategy_options'].update(
        bindings=dict(loader='binding-A-cpu',remote_gpu0='binding-B-gpu0',remote_gpu1='binding-B-gpu1'),
        route='client-mediated',source_contract=assigned_backing.CONTRACT,rpc_cache='enabled',
        rpc_endpoints=['synthetic-B.example:5000','synthetic-B.example:5001'],worker_host_memory_id='B-ram',
        subject_memory_ids=['B-ram'],
        participant_backing=dict(epoch=1,memory_id='B-disk',limit_bytes=256<<30,
            min_free_bytes=1<<30,reserve_bytes=128<<30),observer=dict(OBSERVER))
    remote['backing']=[]
    remote['cache_ranges']=[]

    owners={'binding-A-cpu':[],'binding-B-gpu0':[],'binding-B-gpu1':[]}
    for tensor in metadata().tensors:
        layer=int(tensor.state_id.split('.')[1]) if tensor.state_id.startswith('blk.') else 48
        owner=('binding-A-cpu' if tensor.state_id in ('token_embd.weight','per_layer_token_embd.weight') or layer<41
               else 'binding-B-gpu0' if layer<45 else 'binding-B-gpu1')
        owners[owner].append(tensor)
    raw['placement']=[]
    for binding_id,tensors in owners.items():
        unit='fixed-'+binding_id
        raw['placement'].append(dict(unit_id=unit,binding_id=binding_id,
            state_ids=[t.state_id for t in tensors],state_ranges=[dict(state_id=t.state_id,
                member=t.member,offset=t.absolute_offset,length=t.encoded_bytes) for t in tensors]))
        if binding_id!='binding-A-cpu':
            for tensor in tensors:
                remote['cache_ranges'].append(dict(state_id=tensor.state_id,member=tensor.member,
                    offset=tensor.absolute_offset,length=tensor.encoded_bytes,
                    sha256=sha({'synthetic':tensor.state_id}),
                    cache_key=format(len(remote['cache_ranges'])+1,'016x'),
                    source_id=raw['model']['source_id'],revision=raw['model']['revision'],
                    representation='Q8_0',unit_id=unit))

    raw['policy']['memory_limits'].append(dict(memory_id='B-vram1',peak_bytes=12<<30,
        min_available_bytes=0,reserve_bytes=2<<30))
    reseal_profiles(snapshot)
    # Bind the newly cloned compute evidence after its payload has been sealed.
    gpu1_binding['evidence_sha256']=next(e['sha256'] for e in snapshot['evidence']
        if e['evidence_id']=='synthetic-B-gpu1')
    manifest=synthetic_cuda_manifest()
    raw['participants'][0]['runtime_sha256']=assigned_backing.role_identity('client').executable_sha256
    raw['participants'][1]['runtime_sha256']=manifest['executable_sha256']
    raw=rejoin_profiles(raw)
    return raw,manifest


class TwoGpuTopologyTests(unittest.TestCase):
    def build(self,mutate=None):
        raw,manifest=two_gpu_mapping()
        if mutate: mutate(raw)
        with patch.object(assigned_backing,'identities',return_value=synthetic_table(manifest)):
            return build_plan(parse_config(rejoin_profiles(raw),now=NOW,profile_mode='replay'),now=NOW)

    def test_exact_whole_layer_ownership_output_and_coordinator_route(self):
        plan=self.build(); candidate=plan.candidate
        expected={tensor.state_id:(tensor.member,tensor.absolute_offset,tensor.encoded_bytes)
                  for tensor in metadata().tensors}
        actual={assignment.state_id:(assignment.member,assignment.absolute_offset,assignment.encoded_bytes)
                for assignment in candidate.assignments}
        self.assertEqual(len(candidate.assignments),len(actual))
        self.assertEqual(actual,expected)
        by_layer={layer:{a.binding_id for a in candidate.assignments
            if a.state_id.startswith(f'blk.{layer}.')} for layer in range(48)}
        self.assertTrue(all(by_layer[n]=={'binding-A-cpu'} for n in range(41)))
        self.assertTrue(all(by_layer[n]=={'binding-B-gpu0'} for n in range(41,45)))
        self.assertTrue(all(by_layer[n]=={'binding-B-gpu1'} for n in range(45,48)))
        self.assertEqual({a.binding_id for a in candidate.assignments if a.state_id.startswith('output')},
                         {'binding-B-gpu1'})
        self.assertEqual([b.before_layer for b in candidate.boundaries],[41,45])
        self.assertEqual(candidate.boundaries[1].route_hosts,('B','A','B'))
        self.assertEqual(candidate.boundaries[1].link_legs,('A-B','A-B'))
        self.assertFalse(any(c.allocation_id.startswith('encoded-weights:binding-B-cpu')
                             for c in candidate.charges))

    def test_native_lowering_binds_both_devices_in_order(self):
        plan=self.build(); spec=q8_llama_cpp_spec(plan)
        self.assertEqual(spec.rpc_endpoint,'synthetic-B.example:5000,synthetic-B.example:5001')
        self.assertEqual(spec.device,'RPC0,RPC1')
        self.assertEqual(spec.rpc_args,())
        self.assertEqual([(p.name,p.endpoint,p.binding_id,p.native_selector) for p in q8_rpc_processes(plan)],
            [('rpc0','synthetic-B.example:5000','binding-B-gpu0','CUDA0'),
             ('rpc1','synthetic-B.example:5001','binding-B-gpu1','CUDA1')])
        self.assertEqual(spec.args[spec.args.index('--tensor-split')+1],'4,4')
        self.assertEqual(spec.args[spec.args.index('--gpu-layers')+1],'8')
        self.assertEqual(NativeQ8Options('two-gpu',gpu_layers=8).layer_device_indices(),
                         (None,)*41+(0,0,0,0,1,1,1,1))

    def test_worker_host_and_each_vram_are_independent_domains(self):
        plan=self.build(); charges=plan.candidate.charges
        self.assertTrue(any(c.memory_id=='B-ram' and c.allocation_id.startswith('remote-receive-staging') for c in charges))
        boundary=plan.candidate.boundaries[1]
        worker_payload=next(c for c in charges if c.allocation_id=='boundary-worker-rpc-payload/serve')
        self.assertEqual((worker_payload.memory_id,worker_payload.bytes),('B-ram',boundary.logical_bytes))
        self.assertTrue(any(c.memory_id=='B-ram' and c.allocation_id=='boundary-worker-rpc-overlap/serve'
                            and c.bytes is None for c in charges))
        self.assertEqual({c.allocation_id for c in charges if c.memory_id=='B-ram'
                          and c.allocation_id.startswith('worker-runtime-heap:')
                          and c.bytes is None},
                         {'worker-runtime-heap:rpc0/load','worker-runtime-heap:rpc0/serve',
                          'worker-runtime-heap:rpc0/cleanup','worker-runtime-heap:rpc1/load',
                          'worker-runtime-heap:rpc1/serve','worker-runtime-heap:rpc1/cleanup'})
        self.assertTrue(any(c.memory_id=='B-vram' and c.allocation_id.startswith('encoded-weights:binding-B-gpu0') for c in charges))
        self.assertTrue(any(c.memory_id=='B-vram1' and c.allocation_id.startswith('encoded-weights:binding-B-gpu1') for c in charges))
        for memory_id in ('B-vram','B-vram1'):
            def starve(raw,mid=memory_id):
                memory=next(m for m in raw['profiles']['snapshot']['memory_resources'] if m['memory_id']==mid)
                memory['total_bytes']=memory['available_bytes']=1
                next(r for r in raw['policy']['memory_limits'] if r['memory_id']==mid)['peak_bytes']=1
            refused=self.build(starve)
            self.assertIn('physical capacity deficit: '+memory_id,refused.admission.deficits)

    def test_endpoint_alias_and_server_local_routes_refuse(self):
        for mutate,reason in (
            (lambda r:r['strategy_options'].update(rpc_endpoints=['synthetic-B.example:5000']*2),'distinct RPC endpoint'),
            (lambda r:r['strategy_options'].update(rpc_endpoints=['synthetic-B.example:5001','synthetic-B.example:5000']),'primary RPC endpoint'),
            (lambda r:r['strategy_options'].update(rpc_endpoints=['synthetic-B.example:5000','other.example:5001']),'same owned worker host'),
            (lambda r:r['strategy_options'].update(rpc_endpoints=['synthetic-B.example:5000','synthetic-B.example:5000']),'distinct RPC endpoint'),
            (lambda r:r['strategy_options'].update(route='server-local'),'client-mediated copy route')):
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.build(mutate)

    def test_pinned_server_is_serial_so_one_listener_cannot_back_two_dispatchers(self):
        source=(ROOT/'tests/fixtures/issue299/overlay/ggml/src/ggml-rpc/ggml-rpc.cpp').read_text()
        accept=source.index('auto client_socket = server_socket->accept();')
        serve=source.index('rpc_serve_client(backends, cache_dir, client_socket);',accept)
        closed=source.index('Client connection closed',serve)
        self.assertGreater(serve,accept)
        self.assertGreater(closed,serve)
        self.assertEqual(source.count('server_socket->accept()'),1)

    def test_full_source_worker_contract_refuses(self):
        def full_source(raw):
            raw['strategy_options']['source_contract']='full-source-both-hosts/1'
            remote=raw['participants'][1]
            remote['backing']=[dict(memory_id='B-disk',member=row['name'],sha256=row['sha256'],
                size_bytes=row['size_bytes']) for row in raw['model']['members']]
            raw['strategy_options'].pop('participant_backing')
        with self.assertRaisesRegex(ValueError,'assigned-only worker backing'):
            self.build(full_source)

    def test_assigned_only_projection_covers_both_gpu_banks(self):
        plan=self.build(); payload=q8_source_payload(plan)
        remote=next(p for p in payload['participants'] if p['role']=='remote')
        self.assertEqual(remote['backing'],[])
        self.assertEqual({row['binding_id'] for row in remote['bindings']
                          if row['binding_id'].startswith('binding-B-gpu')},
                         {'binding-B-gpu0','binding-B-gpu1'})
        assigned={row['binding_id'] for row in payload['assignments']
                  if row['binding_id'].startswith('binding-B-')}
        self.assertEqual(assigned,{'binding-B-gpu0','binding-B-gpu1'})

    def test_retained_dynamic_observer_refuses_ambiguous_device_route(self):
        plan=self.build()
        with self.assertRaisesRegex(ValueError,'lack endpoint/device ordinal'):
            reconcile_dynamic(plan,None,None,(),mode='synthetic-test',clock=lambda:NOW)

    def test_two_gpu_cannot_fall_through_the_legacy_single_rpc_runner(self):
        runner=OperatorRunner(None,None,None,None)
        with self.assertRaisesRegex(ValueError,'requires the collected observer path'):
            runner.run(self.build())

    def test_each_rpc_spawn_receives_only_its_exact_bank_guard(self):
        plan=self.build(); remote=next(p for p in plan.participants if p.role=='remote')
        guards={'binding-B-gpu0':'/guard/gpu0','binding-B-gpu1':'/guard/gpu1'}
        runner=OperatorRunner(None,None,None,None)
        sources={remote.participant_id:{'assigned_guard_paths':guards}}
        self.assertEqual(runner._assigned_spawn(plan,remote,sources,binding_id='binding-B-gpu0'),
                         {'assigned':'/guard/gpu0'})
        self.assertEqual(runner._assigned_spawn(plan,remote,sources,binding_id='binding-B-gpu1'),
                         {'assigned':'/guard/gpu1'})
        with self.assertRaisesRegex(KeyError,'not-a-bank'):
            runner._assigned_spawn(plan,remote,sources,binding_id='not-a-bank')

    def test_diagnostic_runs_two_owned_processes_retains_output_and_cleans_up(self):
        plan=self.build()
        class Transport:
            def __init__(self,fail_spawn=None):
                self.rows={}; self.stopped=set(); self.argv={}; self.fail_spawn=fail_spawn
            def call(self,address,payload):
                action=payload['action']; name=payload.get('name')
                if action=='admit': return {'lease':'admitted'}
                if action=='port': return {'port':'available'}
                if action=='spawn':
                    if name==self.fail_spawn: raise RuntimeError('material '+name+' spawn failure')
                    row={'pid':100+len(self.rows),'start':str(200+len(self.rows)),
                         'token':payload['token']}
                    self.rows[(address,name)]=row; self.argv[(address,name)]=tuple(payload['argv'])
                    return row
                if action=='alive': return {'alive':(address,name) not in self.stopped}
                if action=='listening': return {'listening':(address,name) not in self.stopped}
                if action=='stop': self.stopped.add((address,name)); return {'signal':'TERM'}
                if action=='release': return {'lease':'released'}
                raise AssertionError(action)
        transport=Transport(); manager=LeaseManager(transport,'issue313-diagnostic',stop_timeout=0)
        class Sources:
            def verify(self,part,plan,fnv_binary=None):
                receipt={'assigned_guard_path':'/guard/all'}
                if part.role=='remote': receipt['assigned_guard_paths']={
                    'binding-B-gpu0':'/guard/gpu0','binding-B-gpu1':'/guard/gpu1'}
                return receipt
        class IdentityReader:
            def __init__(self,transport): self.transport=transport
            def read(self,part,pid,*,expected_executable,expected_sha256,expected_argv):
                row=self.transport.rows[(part.execution_address,part.participant_id.rsplit('-',1)[-1])]
                return ProcessIdentity(part.participant_id,part.host_id,part.boot_epoch,
                    part.topology_epoch,pid,row['start'],expected_executable,expected_sha256,
                    tuple(expected_argv),freeze(dict(native=[],visible=[],environment={})),part.rpc_endpoint)
        class Collector:
            def __init__(self,transport,fail_dynamic=False):
                self.identity_reader=IdentityReader(transport); self.fail_dynamic=fail_dynamic
            def collect_build(self,*args,**kwargs): return None
            def await_terminal_export(self,*args,**kwargs): return None
            def collect_dynamic(self,part,*args,**kwargs):
                if self.fail_dynamic and part.participant_id.endswith('rpc1'):
                    raise RuntimeError('material rpc1 terminal observation failure')
                observation=SimpleNamespace(sequence=({'event':'rpc_server_command'},),
                    terminal_digest='a'*64,event_count=1)
                return SimpleNamespace(observation=observation)
        class HTTP:
            def __init__(self,fail=False): self.fail=fail
            def get(self,*args,**kwargs): return {'status':'ok'}
            def post(self,*args,**kwargs):
                if self.fail: raise RuntimeError('material request failure')
                return {'id':'diag-1','choices':[{'message':{'content':'raw diagnostic'},
                    'finish_reason':'stop'}],'usage':{'completion_tokens':2}}
        class Tunnel:
            def __init__(self): self.done=False
            def poll(self): return 0 if self.done else None
            def terminate(self): self.done=True
            def wait(self,timeout=None): return 0
        def execute(*,fail_spawn=None,fail_request=False,fail_dynamic=False):
            transport=Transport(fail_spawn); manager=LeaseManager(
                transport,'issue313-diagnostic-'+str(fail_spawn)+str(fail_request)+str(fail_dynamic),
                stop_timeout=0)
            runner=OperatorRunner(Sources(),manager,HTTP(fail_request),lambda *args:(Tunnel(),8080),
                observation_mode='synthetic-test',clock=lambda:NOW,
                collector=Collector(transport,fail_dynamic))
            try:
                with patch.object(runner,'_profiled_admission',return_value=plan.admission):
                    outcome=runner.run(plan)
            except BaseException as exc: outcome=exc
            return outcome,runner,transport
        result,runner,transport=execute()
        self.assertEqual((result['status'],result['raw_output'],result['output_accepted']),
                         ('EXECUTED-OUTPUT-UNACCEPTED','raw diagnostic',False))
        self.assertEqual([p['name'] for p in result['rpc_processes']],['rpc0','rpc1'])
        self.assertEqual([p['name'] for p in result['listener_observations']],['rpc0','rpc1'])
        self.assertEqual(result['cleanup'][next(p.execution_address for p in plan.participants
            if p.role=='remote')]['lease'],'released')
        remote=next(p for p in plan.participants if p.role=='remote')
        self.assertIn('CUDA0',transport.argv[(remote.execution_address,'rpc0')])
        self.assertIn('CUDA1',transport.argv[(remote.execution_address,'rpc1')])
        for failure,reason in ((dict(fail_spawn='rpc1'),'material rpc1 spawn failure'),
                               (dict(fail_request=True),'material request failure')):
            outcome,failed_runner,failed_transport=execute(**failure)
            self.assertIsInstance(outcome,RuntimeError)
            self.assertEqual(str(outcome),reason)
            self.assertEqual(failed_transport.stopped,set(failed_transport.rows))
            self.assertTrue(all(row['lease']=='released'
                                for row in failed_runner.last_cleanup.values()))
        refused,failed_runner,failed_transport=execute(fail_dynamic=True)
        self.assertEqual(refused['status'],'EXECUTED-OBSERVATION-REFUSED')
        self.assertEqual(refused['observation_refusal'],
                         'material rpc1 terminal observation failure')
        self.assertEqual(failed_transport.stopped,set(failed_transport.rows))
        self.assertTrue(all(row['lease']=='released' for row in failed_runner.last_cleanup.values()))


class TwoBankPreparationCompositionTests(unittest.TestCase):
    """Tiny CPU bytes prove cache composition, never CUDA correctness."""
    def setUp(self):
        from tests.test_issue299_source import Q8Source
        self.fixture=Q8Source(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.cached(); self.payload=copy.deepcopy(self.fixture.payload)
        remote=self.payload['participants'][1]
        rename={'B-cpu':'B-gpu0','B-gpu':'B-gpu1'}
        for binding in remote['bindings']:
            old=binding['binding_id']; binding['binding_id']=rename[old]
            binding['memory_id']=rename[old]+'-mem'
            binding['native_selector']='CUDA0' if old=='B-cpu' else 'CUDA1'
            binding['visible_selector']='RPC0' if old=='B-cpu' else 'RPC1'
        for assignment in self.payload['assignments']:
            if assignment['binding_id'] in rename:
                assignment['binding_id']=rename[assignment['binding_id']]
                assignment['memory_id']=rename[assignment['memory_id'].removesuffix('-mem')]+'-mem'
        unit_rename={}
        for placement in self.payload['placement']:
            if placement['binding_id'] in rename:
                old=placement['unit_id']; placement['binding_id']=rename[placement['binding_id']]
                placement['unit_id']='unit-'+placement['binding_id']; unit_rename[old]=placement['unit_id']
        for row in remote['cache_ranges']:
            row['unit_id']=unit_rename[row['unit_id']]
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cache=Path(self.temp.name)/'worker'
        self.source=LocalFileSource(source_id='origin',root=self.fixture.root)
        self.budget=DiskBudget(1<<20,0,32768)

    def prepare(self,node):
        remote=self.payload['participants'][1]
        return prepare_q8_participant(payload=self.payload,epoch=1,
            executable=self.fixture.runtime,executable_sha256=remote['runtime_sha256'],
            node=node,origin_source=self.source,budget=self.budget)

    def test_both_assigned_banks_cold_restart_and_failed_change_cleanup(self):
        node=StreamingNode('B',StreamingArtifactCache(self.cache))
        remote=self.payload['participants'][1]
        projection=project_q8_preparation(self.payload,epoch=1,
            runtime=runtime_identity(self.fixture.runtime,remote['runtime_sha256']))
        banks={row['binding_id'] for row in projection['metadata']['tensors']}
        self.assertEqual(banks,{'B-gpu0','B-gpu1'})
        cold=self.prepare(node)
        self.assertGreater(cold['acquisition_bytes'],0)
        selective=copy.deepcopy(self.payload)
        selective['source_contract']=assigned_backing.CONTRACT
        participant=selective['participants'][1]
        participant['backing']=[]; participant['cache_path']=str(self.cache)
        assigned_backing.project_payload(selective,dict(epoch=1,memory_id='B-disk',**vars(self.budget)))
        receipt=source_verifier.verify_q8_role(participant,selective)
        guards=receipt['assigned_guard_paths']
        self.assertEqual(set(guards),{'B-gpu0','B-gpu1'})
        self.assertEqual(len(set(guards.values())),2)
        guarded={bid:{line.split('\t',1)[0] for line in Path(path).read_text().splitlines()}
                 for bid,path in guards.items()}
        self.assertTrue(all(guarded.values()))
        self.assertFalse(guarded['B-gpu0'] & guarded['B-gpu1'])
        self.source.access_log.clear()
        warm=self.prepare(StreamingNode('B',StreamingArtifactCache(self.cache)))
        self.assertEqual((warm['acquisition_bytes'],self.source.access_log),(0,[]))
        changed=copy.deepcopy(self.payload)
        row=changed['participants'][1]['cache_ranges'][0]
        row['sha256']='0'*64
        before=StreamingNode('B',StreamingArtifactCache(self.cache)).inventory()['verified_objects']
        with self.assertRaises(AcquisitionError):
            prepare_q8_participant(payload=changed,epoch=2,
                executable=self.fixture.runtime,
                executable_sha256=changed['participants'][1]['runtime_sha256'],
                node=StreamingNode('B',StreamingArtifactCache(self.cache)),
                origin_source=self.source,budget=self.budget)
        after=StreamingNode('B',StreamingArtifactCache(self.cache)).inventory()['verified_objects']
        before_digests={row['content_digest'] for row in before}
        after_digests={row['content_digest'] for row in after}
        self.assertTrue(before_digests<=after_digests)
        self.assertNotIn('sha256:'+'0'*64,after_digests)


class TwoListenerLifecycleTests(unittest.TestCase):
    """Controller proof only; the later native route diagnostic is still required."""
    def test_two_owned_listeners_are_simultaneous_and_cleaned_up(self):
        class Transport:
            def __init__(self): self.rows={}; self.stopped=set()
            def call(self,address,payload):
                action=payload['action']; name=payload.get('name')
                if action=='admit': return {'lease':'admitted'}
                if action=='port': return {'port':'available'}
                if action=='spawn':
                    row={'pid':100+len(self.rows),'start':str(200+len(self.rows)),
                         'token':payload['token']}
                    self.rows[name]=row; return row
                if action=='alive': return {'alive':name not in self.stopped}
                if action=='listening': return {'listening':name not in self.stopped}
                if action=='stop': self.stopped.add(name); return {'signal':'TERM'}
                if action=='release': return {'lease':'released'}
                raise AssertionError(action)
        with tempfile.TemporaryDirectory() as root:
            manager=LeaseManager(Transport(),'issue313-two-listener-test',stop_timeout=0)
            manager.acquire('local',root)
            ports=[5000,5001]
            try:
                for index,port in enumerate(ports):
                    manager.port('local','127.0.0.1',port)
                    manager.spawn('local','rpc'+str(index),['synthetic-rpc',str(port)])
                self.assertTrue(all(manager.listening('local','rpc'+str(index),'127.0.0.1',port)
                                    for index,port in enumerate(ports)))
                self.assertNotEqual(manager.owned['local']['rpc0']['pid'],manager.owned['local']['rpc1']['pid'])
            finally:
                cleanup=manager.cleanup()
            self.assertEqual(cleanup['local']['lease'],'released')
            self.assertEqual(set(cleanup['local']),{'rpc0','rpc1','lease'})

