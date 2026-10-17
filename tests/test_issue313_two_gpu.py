"""Focused #313 two-CUDA-device planning/lowering regressions.

All profiles and build identities here are synthetic.  They prove the fixed
operator contract and native argv only; they do not prove CUDA execution.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from inferswarm.operator import assigned_backing
from inferswarm.operator import lifecycle
from inferswarm.operator.config import parse_config
from inferswarm.operator.lifecycle import LeaseManager
from inferswarm.operator.plan import build_plan, revalidate_admission
from inferswarm.operator.phased_observation import reconcile_dynamic
from inferswarm.operator.profiles import thaw, sha256 as canonical_sha
from inferswarm.operator.profiles import freeze
from inferswarm.operator.bindings import ProcessIdentity
from inferswarm.operator.qwen_q8 import (NativeQ8Options, q8_llama_cpp_spec,
    q8_rpc_processes, validate_q8_ownership)
from inferswarm.operator.runtime import OperatorRunner
from inferswarm.operator.q8_experiment import (EXPERIMENTAL_OPT_IN,
    ExperimentalLeaseManager, SystemdCampaignGuard,
    validate_experimental_envelope)
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


def two_gpu_mapping(placement_variant=None):
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
    first,second=41,45
    if placement_variant is not None:
        raw['strategy_options']['placement_variant']=placement_variant
        first,second=40,44

    owners={'binding-A-cpu':[],'binding-B-gpu0':[],'binding-B-gpu1':[]}
    for tensor in metadata().tensors:
        layer=int(tensor.state_id.split('.')[1]) if tensor.state_id.startswith('blk.') else 48
        owner=('binding-A-cpu' if tensor.state_id in ('token_embd.weight','per_layer_token_embd.weight') or layer<first
               else 'binding-B-gpu0' if layer<second else 'binding-B-gpu1')
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
    def build(self,mutate=None,*,placement_variant=None,build_pair=None):
        raw,manifest=two_gpu_mapping(placement_variant)
        if build_pair is not None:
            raw['strategy_options']['build_pair']=build_pair
            for p in raw['participants']:
                backend='cpu' if p['role']=='client' else 'cuda'
                p['runtime_sha256']=assigned_backing.role_identity(p['role'],backend,
                    build_pair=build_pair).executable_sha256
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

    def test_existing_modes_keep_pre_variant_canonical_bytes(self):
        from tests.test_issue299_q8_plan import config
        # Recorded on untouched aa3e1717 with these deterministic fixtures.
        expected={
            'two-gpu':('bc6c773d803bcef2dbf26141539768432eaf0c1fde655ed412a80a4da325cb73',
                       '6209b19b7d1ea35084aafece2678345a4ce7a0c931d06fe2a71770fffdde8893',
                       '5c19b6891a0d6e07f2cf8f687caee6b0a3115dd7a8873b3e0040be758921f78f'),
            'one-gpu':('6c2a4f28196609bc40b1ec4cfbb76319180007047305a61b6fdb0fe964863715',
                       'b1427dcb547ffe2e052f91aa9b0cb6f1f1ea9ca89d42eb14bc9369c2c3d3777e',
                       'f803f5df62ab05c480ef5f4847214a7e04f4b33dd70f40871f488da0449ff01d'),
            'cpu-only':('6e8e64d6d8d2f6771bef7bb55ca00e6bcd68851d2d5efb6270b7e51224b03a1e',
                        'ded88dfa1cf96ecca2776fed703e89bd6f4a20f5a326932b46a760d419319ffb',
                        '8f65940e86352d4c6a6369b364e6ad9cf52d0359627adc7bc822ce4fa9147e93')}
        for selection,witness in expected.items():
            plan=self.build() if selection=='two-gpu' else build_plan(config(selection),now=NOW)
            with self.subTest(selection=selection):
                self.assertEqual((plan.digest,canonical_sha(asdict(plan.candidate)),
                                  canonical_sha(asdict(q8_llama_cpp_spec(plan)))),witness)

    def test_40_44_ownership_state_cuts_and_exact_weight_census(self):
        baseline=self.build(); plan=self.build(placement_variant='40-44'); c=plan.candidate
        for a in c.assignments:
            layer=int(a.state_id.split('.')[1]) if a.state_id.startswith('blk.') else 48
            expected=('binding-A-cpu' if a.state_id in ('token_embd.weight','per_layer_token_embd.weight') or layer<40
                      else 'binding-B-gpu0' if layer<44 else 'binding-B-gpu1')
            self.assertEqual(a.binding_id,expected,a.state_id)
        weights=lambda p,b: sum(a.encoded_bytes for a in p.candidate.assignments if a.binding_id==b)
        self.assertEqual(weights(plan,'binding-B-gpu0'),11035064960)
        self.assertEqual(weights(plan,'binding-B-gpu1'),11717499520)
        self.assertEqual(weights(plan,'binding-B-gpu0')+weights(plan,'binding-B-gpu1'),22752564480)
        states={s.state_id:s for s in c.required_state}
        for layer,bid in ((40,'binding-B-gpu0'),(44,'binding-B-gpu1')):
            rows=[states[f'cache_{name}_l{layer}'] for name in ('r','s')]
            self.assertEqual([r.lower_bound_bytes for r in rows],[122880,3145728])
            self.assertEqual({r.binding_id for r in rows},{bid})
            self.assertEqual(sum(a.encoded_bytes for a in c.assignments
                                 if a.state_id.startswith(f'blk.{layer}.')),2760141696)
        def known(p,bid):
            return sum(c.bytes for c in p.candidate.charges if c.phase=='serve' and c.bytes is not None
                       and c.allocation_id.startswith(('encoded-weights:'+bid+'/', 'state-lower-bound:'+bid+'/')))
        self.assertEqual(known(plan,'binding-B-gpu0'),known(baseline,'binding-B-gpu0'))
        self.assertEqual(known(plan,'binding-B-gpu1')-known(baseline,'binding-B-gpu1'),2763410304)
        self.assertEqual([b.before_layer for b in c.boundaries],[40,44])
        self.assertEqual(c.boundaries[1].route_hosts,('B','A','B'))
        self.assertEqual(c.boundaries[1].link_legs,('A-B','A-B'))
        for cuts in (baseline.candidate.boundaries,tuple(replace(b,before_layer=b.before_layer+1) for b in c.boundaries)):
            with self.assertRaisesRegex(ValueError,'boundary schema'):
                validate_q8_ownership(replace(c,boundaries=cuts),metadata())
        bad=replace(c,assignments=baseline.candidate.assignments)
        with self.assertRaisesRegex(ValueError,'whole-layer ownership'):
            validate_q8_ownership(bad,metadata())

    def test_40_44_native_float32_map_and_canonical_identity(self):
        pair=assigned_backing.OPTIMIZED_BUILD_PAIR
        plan=self.build(placement_variant='40-44',build_pair=pair); spec=q8_llama_cpp_spec(plan)
        self.assertEqual(spec.args[spec.args.index('--gpu-layers')+1],'9')
        self.assertEqual(spec.args[spec.args.index('--tensor-split')+1],'4,5')
        self.assertEqual(NativeQ8Options('two-gpu',gpu_layers=9).layer_device_indices(),
                         (None,)*40+(0,)*4+(1,)*5)  # Includes output slot 48.
        self.assertEqual(spec.device,'RPC0,RPC1')
        self.assertNotEqual(plan.digest,self.build(build_pair=pair).digest)
        self.assertEqual(thaw(plan.candidate.canonical_strategy_options)['placement_variant'],'40-44')
        self.assertEqual(plan.candidate.semantic_contract[0].placement_variant,'40-44')
        self.assertEqual(plan.candidate.source_contract[-1],NativeQ8Options('two-gpu',gpu_layers=9))
        self.assertNotIn('plan digest integrity mismatch',revalidate_admission(plan,now=NOW).deficits)
        self.assertNotIn('plan strategy options integrity mismatch',revalidate_admission(plan,now=NOW).deficits)
        changed=replace(plan,config=replace(plan.config,strategy_options=self.build().strategy_options))
        self.assertIn('plan strategy options integrity mismatch',revalidate_admission(changed,now=NOW).deficits)

    def test_40_44_static_context_retains_closed_variant_contract(self):
        from inferswarm.operator.phased_observation import derive_static_plan_context
        from inferswarm.operator.qwen_q8 import Q8VariantContract
        plan=self.build(placement_variant='40-44',build_pair=assigned_backing.OPTIMIZED_BUILD_PAIR)
        context=derive_static_plan_context(plan,metadata(),original_plan_digest=plan.digest)
        self.assertEqual(context.inventory.weights,plan.candidate.assignments)
        self.assertFalse(plan.admission.execution_ready)
        contract=plan.candidate.semantic_contract[0]
        @dataclass(frozen=True)
        class ExtraContract(Q8VariantContract):
            extra: int=0
        for bad in (replace(contract,placement_variant=('40-44',)),ExtraContract(**vars(contract))):
            candidate=replace(plan.candidate,semantic_contract=(bad,))
            with self.assertRaisesRegex(ValueError,'static context typed input'):
                derive_static_plan_context(replace(plan,candidate=candidate),metadata(),
                                           original_plan_digest=plan.digest)

    def test_40_44_cache_projection_and_guards_reuse_exact_ranges(self):
        def payload(variant,previous=None):
            raw,_=two_gpu_mapping(variant)
            if previous is not None:
                # Retain the authenticated old content/native keys across a bank
                # move; only the new layer gets new synthetic content identities.
                old={r['state_id']:r for r in previous['participants'][1]['cache_ranges']}
                next_key=max(int(r['cache_key'],16) for r in old.values())+1
                for row in raw['participants'][1]['cache_ranges']:
                    if row['state_id'] in old:
                        row['cache_key']=old[row['state_id']]['cache_key']
                    else:
                        row['cache_key']=format(next_key,'016x'); next_key+=1
            pair=assigned_backing.OPTIMIZED_BUILD_PAIR
            raw['strategy_options']['build_pair']=pair
            for p in raw['participants']:
                backend='cpu' if p['role']=='client' else 'cuda'
                p['runtime_sha256']=assigned_backing.role_identity(p['role'],backend,build_pair=pair).executable_sha256
            plan=build_plan(parse_config(rejoin_profiles(raw),now=NOW,profile_mode='replay'),now=NOW)
            return plan,q8_source_payload(plan)
        baseline,old=payload(None); plan,new=payload('40-44',old)
        self.assertEqual([p.runtime_sha256 for p in plan.participants],
                         [p.runtime_sha256 for p in baseline.participants])
        old_rows={r['state_id']:r for r in old['prepared_metadata']['tensors']}
        rows={r['state_id']:r for r in new['prepared_metadata']['tensors']}
        missing=set(rows)-set(old_rows)
        self.assertEqual(missing,{t.state_id for t in metadata().tensors if t.state_id.startswith('blk.40.')})
        self.assertEqual(sum(rows[n]['encoded_bytes'] for n in missing),2760141696)
        for name in old_rows:
            for field in ('member','absolute_offset','encoded_bytes','content_sha256','cache_key','ggml_type','shape'):
                self.assertEqual(rows[name][field],old_rows[name][field],(name,field))
            if name.startswith('blk.44.'):
                self.assertEqual((old_rows[name]['binding_id'],rows[name]['binding_id']),
                                 ('binding-B-gpu0','binding-B-gpu1'))
        guards={bid:source_verifier.assigned_guard_bytes(dict(new['prepared_metadata'],
            tensors=[r for r in rows.values() if r['binding_id']==bid])).decode().splitlines()
            for bid in ('binding-B-gpu0','binding-B-gpu1')}
        names={bid:{line.split()[0] for line in lines} for bid,lines in guards.items()}
        self.assertFalse(names['binding-B-gpu0'] & names['binding-B-gpu1'])
        self.assertEqual(set.union(*names.values()),set(rows))
        self.assertTrue(missing<=names['binding-B-gpu0'])
        self.assertTrue({n for n in rows if n.startswith('blk.44.') or n.startswith('output')}<=names['binding-B-gpu1'])

    def test_unsupported_variants_native_options_and_cache_coverage_refuse(self):
        with self.assertRaisesRegex(ValueError,'whole-layer ownership'):
            self.build(lambda raw: raw['strategy_options'].update(placement_variant='40-44'))
        for variant in ('41-45','39-43','40-45',None,False,9,[],{}):
            with self.subTest(variant=variant),self.assertRaisesRegex(ValueError,'unsupported Q8 placement variant'):
                self.build(lambda raw: raw['strategy_options'].update(placement_variant=variant))
        for selection in ('one-gpu','cpu-only'):
            raw=q8_mapping(selection); raw['strategy_options']['placement_variant']='40-44'
            with self.subTest(selection=selection),self.assertRaisesRegex(ValueError,'unsupported Q8 placement variant'):
                build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        for layers in (7,10,35,True,9.0):
            with self.subTest(layers=layers),self.assertRaisesRegex(ValueError,'fixed native options'):
                NativeQ8Options('two-gpu',gpu_layers=layers)
        for prefix in ('blk.40.','blk.44.'):
            def omit(raw):
                remote=raw['participants'][1]
                remote['cache_ranges']=[r for r in remote['cache_ranges'] if not r['state_id'].startswith(prefix)]
            with self.subTest(prefix=prefix),self.assertRaisesRegex(ValueError,'cache state coverage'):
                self.build(omit,placement_variant='40-44')
        plan=self.build(placement_variant='40-44')
        self.assertFalse(plan.admission.execution_ready)
        self.assertTrue(any(d.startswith('UNKNOWN allocation:') for d in plan.admission.deficits))
        with self.assertRaisesRegex(ValueError,'Q8 admission refused:'):
            OperatorRunner(None,None,None,None)._profiled_admission(plan)

    def test_worker_host_and_each_vram_are_independent_domains(self):
        plan=self.build(); charges=plan.candidate.charges
        self.assertEqual({c.allocation_id for c in charges if c.memory_id=='B-ram'
                          and c.allocation_id.startswith('remote-receive-staging')},
                         {'remote-receive-staging:rpc0/load','remote-receive-staging:rpc0/serve',
                          'remote-receive-staging:rpc1/load','remote-receive-staging:rpc1/serve'})
        self.assertTrue(all(c.bytes==1<<20 for c in charges if c.memory_id=='B-ram'
                            and c.allocation_id.startswith('remote-receive-staging')))
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

    def test_experimental_envelope_is_explicit_and_preserves_unknown_admission(self):
        plan=self.build(lambda raw: raw['strategy_options']['participant_backing'].update(
            limit_bytes=48<<30,min_free_bytes=64<<30,reserve_bytes=12<<30))
        envelope=dict(schema='q8-two-cuda-experiment/1',opt_in='not-authorized',
            config_sha256='1'*64,request_sha256='2'*64,
            limits=dict(total_seconds=10800,cleanup_reserve_seconds=1200,
                backing_ceiling_bytes=48<<30,min_free_disk_bytes=64<<30,
                application_payload_ceiling_bytes=24<<30,
                worker_memory_max_bytes=10<<30,worker_min_host_headroom_bytes=4<<30,
                coordinator_memory_max_bytes=110<<30,
                coordinator_min_host_headroom_bytes=8<<30,owned_swap_max_bytes=0,
                per_gpu_reserve_bytes=512<<20),
            gpu_bindings=[dict(selector='CUDA0',uuid='GPU-'+('a'*32)),
                          dict(selector='CUDA1',uuid='GPU-'+('b'*32))])
        with self.assertRaisesRegex(ValueError,'explicit experimental opt-in'):
            validate_experimental_envelope(plan,envelope,config_sha256='1'*64,
                                             request_sha256='2'*64)
        envelope['opt_in']=EXPERIMENTAL_OPT_IN
        with self.assertRaisesRegex(ValueError,'assigned backing budget'):
            validate_experimental_envelope(self.build(),envelope,
                config_sha256='1'*64,request_sha256='2'*64)
        validated=validate_experimental_envelope(plan,envelope,
            config_sha256='1'*64,request_sha256='2'*64)
        self.assertEqual(validated.normal_admission_status,plan.admission.status)
        self.assertFalse(validated.normal_execution_ready)
        self.assertGreater(len(validated.unknown_allocations),0)
        self.assertTrue(all(row.endswith(('/load','/serve','/cleanup','/verification'))
                            for row in validated.unknown_allocations))

    def test_experimental_supervision_caps_include_both_listeners(self):
        class Transport:
            def __init__(self): self.calls=[]
            def call(self,address,payload):
                self.calls.append((address,payload))
                if payload['action']=='admit': return {'lease':'admitted'}
                if payload['action']=='spawn':
                    return {'pid':100+len(self.calls),'start':'200','token':payload['token'],
                            'supervision':payload['supervision']}
                raise AssertionError(payload['action'])
        transport=Transport()
        manager=ExperimentalLeaseManager(transport,'campaign-token')
        manager.acquire('worker','/run/worker')
        manager.acquire('coordinator','/run/coordinator')
        manager.spawn('worker','rpc0',['rpc','--device','CUDA0'])
        manager.spawn('worker','rpc1',['rpc','--device','CUDA1'])
        manager.spawn('coordinator','client',['server'])
        spawns=[payload for _,payload in transport.calls if payload['action']=='spawn']
        self.assertEqual(sum(p['supervision']['memory_max_bytes'] for p in spawns
                             if p['name'].startswith('rpc')),10<<30)
        self.assertEqual(next(p for p in spawns if p['name']=='client')
                         ['supervision']['memory_max_bytes'],110<<30)
        self.assertTrue(all(p['supervision']['memory_swap_max_bytes']==0 for p in spawns))
        self.assertTrue(all(p['supervision']['runtime_max_seconds']==9600 for p in spawns))

    def test_experimental_preflight_refuses_identity_disk_source_and_gpu_mapping_drift(self):
        plan=self.build(lambda raw: raw['strategy_options']['participant_backing'].update(
            limit_bytes=48<<30,min_free_bytes=64<<30,reserve_bytes=12<<30))
        client=next(p for p in plan.participants if p.role=='client')
        remote=next(p for p in plan.participants if p.role=='remote')
        raw=dict(schema='q8-two-cuda-experiment/1',opt_in=EXPERIMENTAL_OPT_IN,
            config_sha256='1'*64,request_sha256='2'*64,
            limits=dict(total_seconds=10800,cleanup_reserve_seconds=1200,
                backing_ceiling_bytes=48<<30,min_free_disk_bytes=64<<30,
                application_payload_ceiling_bytes=24<<30,
                worker_memory_max_bytes=10<<30,worker_min_host_headroom_bytes=4<<30,
                coordinator_memory_max_bytes=110<<30,
                coordinator_min_host_headroom_bytes=8<<30,owned_swap_max_bytes=0,
                per_gpu_reserve_bytes=512<<20),
            gpu_bindings=[dict(selector='CUDA0',uuid='GPU-'+('a'*32)),
                          dict(selector='CUDA1',uuid='GPU-'+('b'*32))])
        envelope=validate_experimental_envelope(plan,raw,config_sha256='1'*64,
                                                 request_sha256='2'*64)
        class Commands:
            def __init__(self,mode='ok'): self.mode=mode
            def run(self,address,argv):
                if argv[0] in ('sudo','systemd-run','systemctl'): return ''
                if argv[0]=='sha256sum':
                    digest=(client.runtime_sha256 if address==client.execution_address
                            else remote.runtime_sha256)
                    return (('0'*64 if self.mode=='binary' else digest)+'  '+argv[-1]+'\n')
                if argv[0]=='grep': return 'MemAvailable: 134217728 kB\n'
                if argv[0]=='df':
                    return 'Avail\n'+str((1 if self.mode=='disk' else 70)<<30)+'\n'
                if argv[0]=='nvidia-smi' and argv[1].startswith('--query-gpu='):
                    first='GPU-'+('c' if self.mode=='gpu' else 'a')*32
                    return f'0, {first}, 2048, 10\n1, GPU-{"b"*32}, 2048, 10\n'
                if argv[0]=='nvidia-smi':
                    return f'101, GPU-{"b"*32}, 1024\n102, GPU-{"a"*32}, 1024\n'
                raise AssertionError(argv)
        from inferswarm.operator.qwen_q8 import q8_llama_cpp_spec
        for mode,reason in (('binary','runtime binary identity mismatch'),
                            ('disk','free-disk floor'),('gpu','selector/UUID mapping')):
            with self.subTest(mode=mode),self.assertRaisesRegex((ValueError,RuntimeError),reason):
                SystemdCampaignGuard(envelope,SimpleNamespace(),Commands(mode)).begin(
                    plan,q8_llama_cpp_spec(plan),client,remote)
        guard=SystemdCampaignGuard(envelope,SimpleNamespace(),Commands())
        guard.begin(plan,q8_llama_cpp_spec(plan),client,remote)
        with self.assertRaisesRegex(ValueError,'guards missing'):
            guard.sources_verified(plan,{remote.participant_id:{'assigned_guard_paths':{}}})
        with self.assertRaisesRegex(RuntimeError,'wrong GPU/listener'):
            guard._sample({'rpc0':{'pid':101},'rpc1':{'pid':102}})
        guard=SystemdCampaignGuard(envelope,SimpleNamespace(),Commands(),clock=lambda:0)
        guard.started=0
        with self.assertRaisesRegex(RuntimeError,'owned systemd job failed'):
            guard.after_cleanup({'worker':{'rpc0':{'properties':{
                'Result':'oom-kill','MemorySwapCurrent':'0'}},'lease':'released'}})

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

    def test_ordinary_live_admission_still_refuses_unknown_allocations(self):
        runner=OperatorRunner(None,None,None,None)
        with self.assertRaisesRegex(ValueError,'Q8 admission refused:'):
            runner._profiled_admission(self.build())

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
        self.check_diagnostic(self.build())

    def test_40_44_diagnostic_keeps_unaccepted_flags_and_observer_refusal(self):
        self.check_diagnostic(self.build(placement_variant='40-44'))

    def check_diagnostic(self,plan):
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
        class CampaignGuard:
            def __init__(self,fail=None): self.fail=fail
            def begin(self,*args): pass
            def checkpoint(self): pass
            def process_started(self,*args): pass
            def stop_monitor(self): pass
            def sources_verified(self,*args): pass
            def before_request(self,*args):
                if self.fail=='before': raise RuntimeError('material allocator refusal')
                return {'cgroups':'bounded'}
            def request_started(self): pass
            def request_timeout_seconds(self): return 900
            def after_request(self,*args):
                if self.fail=='monitor': raise RuntimeError('material monitor failure')
                return {'compute_attribution':'INCONCLUSIVE'}
            def after_cleanup(self,*args): pass
        def execute(*,fail_spawn=None,fail_request=False,fail_dynamic=False,campaign=None):
            transport=Transport(fail_spawn); manager=LeaseManager(
                transport,'issue313-diagnostic-'+str(fail_spawn)+str(fail_request)+str(fail_dynamic),
                stop_timeout=0)
            runner=OperatorRunner(Sources(),manager,HTTP(fail_request),lambda *args:(Tunnel(),8080),
                observation_mode='synthetic-test',clock=lambda:NOW,
                collector=Collector(transport,fail_dynamic))
            try:
                if campaign is None:
                    with patch.object(runner,'_profiled_admission',return_value=plan.admission):
                        outcome=runner.run(plan)
                else:
                    outcome=runner._execute_two_gpu_diagnostic(
                        plan,plan.admission,campaign_guard=campaign)
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
        experimental,exp_runner,exp_transport=execute(campaign=CampaignGuard())
        self.assertFalse(experimental['output_accepted'])
        self.assertFalse(experimental['physical_qualified'])
        self.assertEqual(experimental['campaign_observation']['after_request']
                         ['compute_attribution'],'INCONCLUSIVE')
        for phase in ('before','monitor'):
            outcome,guard_runner,guard_transport=execute(campaign=CampaignGuard(phase))
            if phase=='before': self.assertIsInstance(outcome,RuntimeError)
            else: self.assertEqual(outcome['status'],'EXECUTED-OBSERVATION-REFUSED')
            self.assertEqual(guard_transport.stopped,set(guard_transport.rows))
            self.assertTrue(all(row['lease']=='released'
                                for row in guard_runner.last_cleanup.values()))


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
        with patch.object(source_verifier,'_q8_native_repair_reserve',
                          wraps=source_verifier._q8_native_repair_reserve) as reserve:
            receipt=source_verifier.verify_q8_role(participant,selective)
        self.assertEqual(reserve.call_args.kwargs['simultaneous_bindings'],
                         ('B-gpu0','B-gpu1'))
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

    def test_dual_listener_repair_reserve_sums_each_bank_peak(self):
        mib=1<<20
        tensors=[dict(state_id='a',binding_id='B-gpu0'),
                 dict(state_id='b',binding_id='B-gpu0'),
                 dict(state_id='c',binding_id='B-gpu1')]
        descriptors={
            'a':dict(sha256='a'*64,length=11*mib),
            'b':dict(sha256='b'*64,length=13*mib),
            'c':dict(sha256='c'*64,length=17*mib),
        }
        overhead=16384*(len(descriptors)+1)
        single=source_verifier._q8_native_repair_reserve(tensors,descriptors)
        dual=source_verifier._q8_native_repair_reserve(
            tensors,descriptors,simultaneous_bindings=('B-gpu0','B-gpu1'))
        self.assertEqual(single,(11+13+17+17)*mib+overhead)
        self.assertEqual(dual,(11+13+17+13+17)*mib+overhead)


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

    def test_systemd_spawn_uses_exact_hard_limits_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            running={'value':True}; calls=[]
            def command(argv,**kwargs):
                calls.append(tuple(argv))
                if argv[:3]==['sudo','-n','systemd-run']:
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                if argv[:3]==['sudo','-n','systemctl'] and 'show' in argv:
                    if '--property=MainPID' in argv:
                        text='123\n'
                    else:
                        text=('ActiveState=active\nResult=success\nExecMainCode=0\n'
                              'ExecMainStatus=0\nMemoryPeak=1024\nMemorySwapCurrent=0\n'
                              f'MemoryMax={5<<30}\nMemorySwapMax=0\n')
                    return SimpleNamespace(returncode=0,stdout=text,stderr='')
                if argv[:4]==['sudo','-n','systemctl','stop']:
                    running['value']=False
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                raise AssertionError(argv)
            with patch.object(lifecycle.subprocess,'run',side_effect=command), \
                 patch.object(lifecycle,'identity',side_effect=lambda pid:'456' if running['value'] else None):
                manager=ExperimentalLeaseManager(lifecycle.LocalTransport(),'token',stop_timeout=0)
                manager.acquire('local',root)
                row=manager.spawn('local','rpc0',['/rpc','--device','CUDA0'])
                self.assertEqual(row['supervision']['memory_max_bytes'],5<<30)
                cleanup=manager.cleanup()
            launch=next(argv for argv in calls if argv[:3]==('sudo','-n','systemd-run'))
            self.assertIn('--property=MemoryMax='+str(5<<30),launch)
            self.assertIn('--property=MemorySwapMax=0',launch)
            self.assertIn('--property=RuntimeMaxSec=9600',launch)
            self.assertEqual(cleanup['local']['lease'],'released')

