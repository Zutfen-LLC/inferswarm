"""Focused #313 two-CUDA-device planning/lowering regressions.

All profiles and build identities here are synthetic.  They prove the fixed
operator contract and native argv only; they do not prove CUDA execution.
"""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from inferswarm.operator import assigned_backing
from inferswarm.operator.config import parse_config
from inferswarm.operator.plan import build_plan
from inferswarm.operator.phased_observation import reconcile_dynamic
from inferswarm.operator.profiles import thaw
from inferswarm.operator.qwen_q8 import NativeQ8Options, q8_llama_cpp_spec
from inferswarm.operator.source import q8_source_payload
from tests.issue299_fixture import NOW, profile_digest, reseal_profiles, sha
from tests.test_issue299_q8_plan import metadata, q8_mapping
from tests.test_issue311_cuda_backing import (OBSERVER, rejoin_profiles,
    synthetic_cuda_manifest, synthetic_table)


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
        physical_id='physical-B-gpu1',native_selector='CUDA1',visible_selector='RPC3',
        runtime_id='runtime-B-gpu1',evidence_id='synthetic-B-gpu1')
    gpu1_binding['evidence_sha256']='0'*64
    remote['bindings']=[gpu0_binding,gpu1_binding]

    raw['strategy_options'].update(
        bindings=dict(loader='binding-A-cpu',remote_gpu0='binding-B-gpu0',remote_gpu1='binding-B-gpu1'),
        route='client-mediated',source_contract=assigned_backing.CONTRACT,rpc_cache='enabled',
        rpc_endpoints=['synthetic-B.example:5000','synthetic-B.example.:5000'],worker_host_memory_id='B-ram',
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
        self.assertEqual(spec.rpc_endpoint,'synthetic-B.example:5000,synthetic-B.example.:5000')
        self.assertEqual(spec.device,'RPC0,RPC3')
        self.assertEqual(spec.rpc_args,('--device','CUDA0,CUDA1'))
        self.assertEqual(spec.args[spec.args.index('--tensor-split')+1],'4,4')
        self.assertEqual(spec.args[spec.args.index('--gpu-layers')+1],'8')
        self.assertEqual(NativeQ8Options('two-gpu',gpu_layers=8).layer_device_indices(),
                         (None,)*41+(0,0,0,0,1,1,1,1))

    def test_worker_host_and_each_vram_are_independent_domains(self):
        plan=self.build(); charges=plan.candidate.charges
        self.assertTrue(any(c.memory_id=='B-ram' and c.allocation_id.startswith('remote-receive-staging') for c in charges))
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
            (lambda r:r['strategy_options'].update(rpc_endpoints=['synthetic-B.example.:5000','synthetic-B.example:5000']),'primary RPC endpoint'),
            (lambda r:r['strategy_options'].update(rpc_endpoints=['synthetic-B.example:5000','other.example.:5000']),'trailing-dot alias'),
            (lambda r:r['strategy_options'].update(route='server-local'),'client-mediated copy route')):
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.build(mutate)

    def test_assigned_only_projection_covers_both_gpu_banks(self):
        plan=self.build(); payload=q8_source_payload(plan)
        remote=next(p for p in payload['participants'] if p['role']=='remote')
        self.assertEqual(remote['backing'],[])
        self.assertEqual({row['binding_id'] for row in remote['bindings']},{'binding-B-gpu0','binding-B-gpu1'})
        assigned={row['binding_id'] for row in payload['assignments']
                  if row['binding_id'].startswith('binding-B-')}
        self.assertEqual(assigned,{'binding-B-gpu0','binding-B-gpu1'})

    def test_retained_dynamic_observer_refuses_ambiguous_device_route(self):
        plan=self.build()
        with self.assertRaisesRegex(ValueError,'lack endpoint/device ordinal'):
            reconcile_dynamic(plan,None,None,(),mode='synthetic-test',clock=lambda:NOW)

