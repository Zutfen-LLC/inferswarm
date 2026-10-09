"""Authentic public metadata + SYNTHETIC resources; no physical proof."""
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path
import copy
import hashlib
import unittest
from unittest.mock import patch

from inferswarm.operator.config import parse_config
from inferswarm.operator.metadata import load_metadata_index
from tests.issue299_fixture import NOW, synthetic_config, reseal_profiles, profile_digest, sha

FIXTURE = Path(__file__).parent / 'fixtures/issue299/q8-metadata.json'
FILE_SHA = 'd4ff414c3d796abd6afb94329de633c39ad5ba4723fc17baa41bdc4c72dce485'
PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'


def metadata():
    return load_metadata_index(FIXTURE, expected_sha256=FILE_SHA)


def q8_mapping(selection='one-gpu', route='client-mediated'):
    """Otherwise valid /3 config with public descriptors, synthetic evidence."""
    m = metadata()
    raw = synthetic_config()
    raw['selection'] = selection
    raw['model'] = dict(source_id=m.source.source_id, revision=m.source.revision,
                        representation=m.source.representation,
                        members=[dict(name=n, sha256=h, size_bytes=s) for n,h,s in m.source.members])
    raw['metadata'] = dict(path=str(FIXTURE), sha256=FILE_SHA, digest=m.metadata_digest)
    raw['workload'] = dict(context=2048, slots=1, batch=128, microbatch=32,
        cache_settings=dict(k='f16', v='f16', recurrent_rows=1, rs_sequences=0, cache_streams=1,
                            attention_cells=2048, text_only=True, kv_offload=True))
    raw['strategy_options'] = dict(bindings=dict(loader='binding-A-cpu', remote_cpu='binding-B-cpu',
        **({'remote_gpu':'binding-B-gpu'} if selection=='one-gpu' else {})),
        route=route, source_contract='full-source-both-hosts/1', rpc_cache='disabled',
        host_mirrors=[], bounds=[], startup_timeout_seconds=120)
    p = raw['profiles']['snapshot']
    if selection == 'cpu-only':
        for group, field, missing in (('compute_units','compute_id','B-gpu'),
                ('memory_resources','memory_id','B-vram'),('runtime_capabilities','runtime_id','runtime-B-gpu')):
            p[group] = [r for r in p[group] if r[field] != missing]
        p['evidence'] = [e for e in p['evidence'] if e['evidence_id'] not in
                        ('synthetic-B-gpu','synthetic-B-vram','synthetic-runtime-B-gpu')]
        raw['participants'][1]['bindings'] = raw['participants'][1]['bindings'][:1]
    for r in p['memory_resources']:
        r['total_bytes'] = (128 if r['kind']=='ram' else 12 if r['kind']=='vram' else 1024) * 2**30
        r['available_bytes'] = r['total_bytes']
    for r in p['runtime_capabilities']:
        r['source_revision'] = PIN
        r['route'] = route
        e = next(e for e in p['evidence'] if e['evidence_id']==r['evidence_id'])
        e['dependencies'].update({'runtime:'+r['runtime_id']+':source_revision':PIN,
            'runtime:'+r['runtime_id']+':route':route, 'workload:digest':sha(raw['workload']),
            **{'model:'+k:raw['model'][k] for k in ('source_id','revision','representation')}})
    reseal_profiles(p)
    raw['profiles']['digest'] = profile_digest(p)
    raw['policy']['memory_limits'] = [dict(memory_id=r['memory_id'], peak_bytes=(100*2**30 if r['kind']=='ram' else r['total_bytes']),
        min_available_bytes=(16*2**30 if r['kind']=='ram' else 0), reserve_bytes=(2*2**30 if r['kind']=='vram' else 0)) for r in p['memory_resources']]
    for participant in raw['participants']:
        participant.update(source_id=m.source.source_id, source_revision=m.source.revision,
                           source_representation='Q8_0', source_path='/synthetic/model/'+m.source.members[0][0])
        participant['backing'] = [dict(memory_id=participant['host_id']+'-disk', member=n, sha256=h, size_bytes=s) for n,h,s in m.source.members]
        for binding in participant['bindings']:
            binding['visible_selector'] = ('CPU' if participant['role']=='client' else 'RPC0' if binding['compute_id']=='B-cpu' else 'RPC1')
    owners = {'binding-A-cpu':[], 'binding-B-cpu':[]}
    if selection == 'one-gpu': owners['binding-B-gpu'] = []
    for t in m.tensors:
        layer = int(t.state_id.split('.')[1]) if t.state_id.startswith('blk.') else None
        owner = ('binding-A-cpu' if layer is not None and layer<14 or t.state_id in ('token_embd.weight','per_layer_token_embd.weight') else
                 'binding-B-gpu' if selection=='one-gpu' and (layer is None or layer>=45) else 'binding-B-cpu')
        owners[owner].append(t)
    raw['placement'] = [dict(unit_id='fixed-'+bid, binding_id=bid, state_ids=[t.state_id for t in ts],
        state_ranges=[dict(state_id=t.state_id,member=t.member,offset=t.absolute_offset,length=t.encoded_bytes) for t in ts]) for bid,ts in owners.items()]
    return raw


def config(selection='one-gpu', route='client-mediated'):
    return parse_config(q8_mapping(selection,route), now=NOW, profile_mode='replay')


def fully_bounded_mapping(selection='one-gpu',route='client-mediated'):
    """Fabricated SYNTHETIC budget/capability witnesses for plumbing only."""
    from inferswarm.operator.qwen_q8 import q8_candidates, bound_capability
    raw=q8_mapping(selection,route)
    c=parse_config(raw,now=NOW,profile_mode='replay')
    candidate=q8_candidates(c,metadata())[0]
    p=raw['profiles']['snapshot']
    runtimes={r['runtime_id']:r for r in p['runtime_capabilities']}
    for requirement in candidate.capability_requirements:
        runtimes[requirement.runtime_id]['capabilities'].append(requirement.capability)
    memories={r['memory_id']:r for r in p['memory_resources']}
    for charge in candidate.charges:
        if charge.bytes is not None: continue
        host=memories[charge.memory_id]['host_id']
        runtime=next(r for r in p['runtime_capabilities'] if r['host_id']==host)
        amount=2**21  # Illustrative bound, NOT a measured target allocation.
        raw['strategy_options']['bounds'].append(dict(allocation_id=charge.allocation_id,bytes=amount,evidence_id=runtime['evidence_id']))
        runtime['capabilities'].append(bound_capability(charge,amount))
        evidence=next(e for e in p['evidence'] if e['evidence_id']==runtime['evidence_id'])
        evidence['dependencies']['memory:'+charge.memory_id+':physical_id']=memories[charge.memory_id]['physical_id']
    reseal_profiles(p); raw['profiles']['digest']=profile_digest(p)
    return raw


class Q8Contracts(unittest.TestCase):
    def api(self):
        from inferswarm.operator import qwen_q8
        return qwen_q8

    def test_exact_public_ownership_both_explicit_choices(self):
        q = self.api()
        for selection, expected in [('one-gpu',[(361,93736272512),(783,85520377984),(80,8957357824)]),
                                     ('cpu-only',[(361,93736272512),(863,94477735808)])]:
            with self.subTest(selection=selection):
                c = q.q8_candidates(config(selection),metadata())
                self.assertEqual(len(c),1)
                self.assertEqual(c[0].candidate_id,selection)
                q.validate_q8_ownership(c[0],metadata())
                grouped = {}
                for row in c[0].assignments: grouped.setdefault(row.binding_id,[]).append(row)
                self.assertEqual(sorted((len(v),sum(a.encoded_bytes for a in v)) for v in grouped.values()),sorted(expected))
                self.assertEqual(len(c[0].assignments),1224)
                self.assertEqual(len([a for a in c[0].assignments if '_exps.weight' in a.state_id]),144)
                for layer in (17,35):
                    rows=[a for a in c[0].assignments if a.state_id.startswith(f'blk.{layer}.')]
                    self.assertEqual(len({a.member for a in rows}),2)
                    self.assertEqual({a.binding_id for a in rows},{'binding-B-cpu'})

    def test_state_lower_bounds_and_real_hyperconnection_dependencies(self):
        q=self.api(); c=q.q8_candidates(config(),metadata())[0]
        states={s.state_id:s for s in c.required_state}
        for layer in range(48):
            names=(['cache_k','cache_v','cache_idx_k'] if layer%4==3 else ['cache_r','cache_s'])
            for name in names:
                s=states[f'{name}_l{layer}']
                self.assertEqual(s.binding_id,'binding-A-cpu' if layer<14 else 'binding-B-cpu' if layer<45 else 'binding-B-gpu')
                self.assertEqual(s.authority,'native-single-sequence/1')
                self.assertFalse(s.reconstructible)
        self.assertEqual(states['cache_r_l0'].lower_bound_bytes,122880)
        self.assertEqual(states['cache_s_l0'].lower_bound_bytes,3145728)
        self.assertEqual(states['cache_ple_r_l1'].lower_bound_bytes,368640)
        self.assertEqual(states['cache_k_l3'].lower_bound_bytes,2048*1024)
        self.assertEqual(states['cache_idx_k_l3'].lower_bound_bytes,2048*256)
        self.assertIn('client-control',states)
        self.assertIsNone(states['client-control'].lower_bound_bytes)
        self.assertEqual([b.before_layer for b in c.boundaries],[14,45])
        for b in c.boundaries:
            self.assertEqual(b.shape,(2560,4,32))
            self.assertEqual(b.logical_bytes,40960*32)
            self.assertIsNone(b.wire_bytes)
            self.assertIn('qsa-maps-bias',b.dependencies)
            self.assertIn('positions',b.dependencies)
            self.assertEqual(b.representation,'f32-completed-hc-residual/1')
        self.assertEqual(c.boundaries[1].route_hosts,('B','A','B'))
        self.assertEqual(len(c.boundaries[1].link_legs),2)

    def test_metadata_semantic_mutations_reach_named_predicates(self):
        q=self.api(); m=metadata(); c=config()
        mutations=[]
        bank=next(t for t in m.tensors if t.state_id=='blk.17.ffn_gate_exps.weight')
        mutations.append(('expert coverage',replace(m,tensors=tuple(t for t in m.tensors if t!=bank))))
        mutations.append(('expert shape',replace(m,tensors=tuple(replace(t,shape=(2560,640,511)) if t==bank else t for t in m.tensors))))
        mutations.append(('expert coverage',replace(m,tensors=m.tensors+(replace(bank,state_id='blk.17.ffn_extra_exps.weight'),))))
        for name,predicate in [('per_layer_token_embd.weight','PLE/input coverage'),('token_embd.weight','PLE/input coverage'),('output_hc_norm.weight','output coverage'),('blk.1.ple_conv1d.weight','PLE support coverage')]:
            mutations.append((predicate,replace(m,tensors=tuple(t for t in m.tensors if t.state_id!=name))))
        mutations.append(('encoded extent',replace(m,tensors=tuple(replace(t,encoded_bytes=t.encoded_bytes-32) if t==bank else t for t in m.tensors))))
        a=next(t for t in m.tensors if t.state_id=='blk.17.ffn_up_exps.weight')
        mutations.append(('metadata descriptor authentication',replace(m,tensors=tuple(replace(t,member=a.member,absolute_offset=a.absolute_offset,relative_offset=a.relative_offset) if t==bank else replace(t,member=bank.member,absolute_offset=bank.absolute_offset,relative_offset=bank.relative_offset) if t==a else t for t in m.tensors))))
        for reason, changed in mutations:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError,reason): q.q8_candidates(c,changed)

    def test_ownership_mutations_no_side_effects(self):
        q=self.api(); m=metadata(); candidate=q.q8_candidates(config(),m)[0]
        target=next(a for a in candidate.assignments if a.state_id=='blk.17.ffn_gate_exps.weight')
        output=next(a for a in candidate.assignments if a.state_id=='output.weight')
        changes=[('ownership coverage',replace(candidate,assignments=candidate.assignments[:-1])),
            ('duplicate ownership',replace(candidate,assignments=candidate.assignments+(target,))),
            ('whole-layer ownership',replace(candidate,assignments=tuple(replace(a,binding_id='binding-B-gpu') if a==target else a for a in candidate.assignments))),
            ('output owner',replace(candidate,assignments=tuple(replace(a,binding_id='binding-B-cpu') if a==output else a for a in candidate.assignments))),
            ('source range',replace(candidate,assignments=tuple(replace(a,absolute_offset=a.absolute_offset+32) if a==target else a for a in candidate.assignments))),
            ('required local state',replace(candidate,required_state=candidate.required_state[:-1])),
            ('boundary schema',replace(candidate,boundaries=(replace(candidate.boundaries[0],shape=(2560,32)),)+candidate.boundaries[1:]))]
        original=copy.deepcopy(candidate)
        for reason, changed in changes:
            with self.subTest(reason=reason), patch('subprocess.run',side_effect=AssertionError('no process access')):
                with self.assertRaisesRegex(ValueError,reason): q.validate_q8_ownership(changed,m)
                self.assertEqual(candidate,original)

    def test_real_config_placement_omissions_ranges_and_wrong_final_owner(self):
        from inferswarm.operator.plan import build_plan
        raw=q8_mapping()
        changed=copy.deepcopy(raw); row=changed['placement'][1]
        name=row['state_ids'][0]; row['state_ids'].remove(name); row['state_ranges']=[r for r in row['state_ranges'] if r['state_id']!=name]
        with self.assertRaisesRegex(ValueError,'ownership coverage'): build_plan(parse_config(changed,now=NOW,profile_mode='replay'),now=NOW)
        changed=copy.deepcopy(raw); changed['placement'][2]['state_ranges'][0]['offset']+=32
        with self.assertRaisesRegex(ValueError,'source range'): build_plan(parse_config(changed,now=NOW,profile_mode='replay'),now=NOW)
        changed=copy.deepcopy(raw); output=next(r for r in changed['placement'][2]['state_ranges'] if r['state_id']=='output.weight')
        changed['placement'][2]['state_ranges'].remove(output); changed['placement'][2]['state_ids'].remove(output['state_id'])
        changed['placement'][1]['state_ranges'].append(output); changed['placement'][1]['state_ids'].append(output['state_id'])
        with self.assertRaisesRegex(ValueError,'output owner'): build_plan(parse_config(changed,now=NOW,profile_mode='replay'),now=NOW)

    def test_profiled_build_digest_immutable_unordered_and_fresh(self):
        from inferswarm.operator.plan import build_plan, revalidate_admission
        c=config(); p=build_plan(c,now=NOW)
        self.assertEqual(p.selection,'one-gpu')
        self.assertEqual(p.admission.status,'BLOCKED')
        self.assertTrue(p.admission.structural_admissible)
        self.assertFalse(p.admission.execution_ready)
        self.assertTrue(any('UNKNOWN' in r for r in p.admission.deficits))
        self.assertEqual(p.digest,build_plan(c,now=NOW+timedelta(minutes=1)).digest)
        self.assertTrue(any('expired evidence' in r for r in revalidate_admission(p,now=NOW+timedelta(hours=2)).deficits))
        self.assertTrue(any('non-live evidence' in r for r in revalidate_admission(p).deficits))
        raw=q8_mapping(); raw['participants'].reverse(); raw['placement'].reverse(); raw['model']['members'].reverse()
        for row in raw['placement']: row['state_ids'].reverse(); row['state_ranges'].reverse()
        raw['strategy_options']['bounds'].reverse()
        self.assertEqual(p.digest,build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW).digest)
        with self.assertRaises(FrozenInstanceError): p.selection='cpu-only'
        with self.assertRaises(TypeError): p.candidate.assignments[0].shape[0]=1
        changed=replace(c,request=tuple((k,'different' if k=='prompt' else v) for k,v in c.request))
        self.assertNotEqual(p.digest,build_plan(changed,now=NOW).digest)
        self.assertNotEqual(p.digest,build_plan(config('cpu-only'),now=NOW).digest)

    def test_no_fallback_and_server_local_is_source_unsupported(self):
        from inferswarm.operator.plan import build_plan
        for route in ('server-local','client-mediated'):
            p=build_plan(config(route=route),now=NOW)
            self.assertEqual(p.selection,'one-gpu')
            self.assertEqual(p.candidate.candidate_id,'one-gpu')
            self.assertEqual(p.admission.status,'BLOCKED')
            if route=='server-local': self.assertTrue(any('UNSUPPORTED_PLACEMENT' in r for r in p.admission.deficits))
        p=build_plan(config('cpu-only'),now=NOW)
        self.assertFalse(any(c.memory_id=='B-vram' for c in p.candidate.charges))
        self.assertEqual(p.selection,'cpu-only')

    def test_strict_options_workload_and_source_backing(self):
        q=self.api()
        for change,reason in [('unknown','strategy options'),('workload','state/workload'),('backing','full-source backing'),('runtime','runtime source pin'),('mirror','host mirror')]:
            c=config()
            from inferswarm.operator.profiles import freeze, thaw
            if change=='unknown': c=replace(c,strategy_options=freeze({**thaw(c.strategy_options),'guess_flag':True}))
            if change=='workload': c=replace(c,workload=replace(c.workload,slots=2))
            if change=='backing': c=replace(c,participants=tuple(replace(p,backing=p.backing[:-1]) if p.role=='remote' else p for p in c.participants))
            if change=='runtime': c=replace(c,profiles=replace(c.profiles,snapshot=replace(c.profiles.snapshot,runtime_capabilities=tuple(replace(r,source_revision='other') for r in c.profiles.snapshot.runtime_capabilities))))
            if change=='mirror': c=replace(c,strategy_options=freeze({**thaw(c.strategy_options),'host_mirrors':[{'bytes':1}]}))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,reason): q.q8_candidates(c,metadata())

    def test_bound_cannot_zero_source_lower_bound_or_claim_unscoped_evidence(self):
        q=self.api(); from inferswarm.operator.profiles import freeze, thaw
        c=config(); original=q.q8_candidates(c,metadata())[0]
        for aid,value,reason in [('full-tensor-loader/load',0,'source-derived lower bound'),
                                ('workspace:binding-B-gpu/serve',1,'bound evidence scope'),
                                ('invented-allocation/serve',1,'unknown budget allocation')]:
            options=thaw(c.strategy_options)
            options['bounds']=[dict(allocation_id=aid,bytes=value,evidence_id='synthetic-runtime-B-gpu')]
            with self.subTest(aid=aid),self.assertRaisesRegex(ValueError,reason):
                q.q8_candidates(replace(c,strategy_options=freeze(options)),metadata())
        self.assertEqual(original,q.q8_candidates(c,metadata())[0])

    def test_cache_enabled_requires_exact_authentic_descriptors(self):
        q=self.api(); from inferswarm.operator.profiles import freeze, thaw
        c=config(); options=thaw(c.strategy_options); options['rpc_cache']='enabled'
        with self.assertRaisesRegex(ValueError,'cache state coverage'):
            q.q8_candidates(replace(c,strategy_options=freeze(options)),metadata())

    def test_every_boundary_contract_field_is_validated(self):
        q=self.api(); c=q.q8_candidates(config(),metadata())[0]; b=c.boundaries[1]
        for field,value in [('strides',(4,10240,40960+4)),('route_hosts',('B','B')),
                            ('link_legs',()),('state_dependencies',()),('ordering','arbitrary'),
                            ('alias_rule','independent-narrow-hidden'),('source_citation','invented')]:
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'boundary schema'):
                q.validate_q8_ownership(replace(c,boundaries=(c.boundaries[0],replace(b,**{field:value}))),metadata())

    def test_missing_required_charge_and_unknown_state_bound_are_explicit(self):
        q=self.api(); from inferswarm.operator.plan import admit_candidate
        c=config(); candidate=q.q8_candidates(c,metadata())[0]
        aid='PLE-active-backed-residence/serve'
        receipt=admit_candidate(replace(candidate,charges=tuple(x for x in candidate.charges if x.allocation_id!=aid)),c.profiles.snapshot,c.policy,now=NOW)
        self.assertTrue(any('missing required allocation' in d and aid in d for d in receipt.deficits))
        for label in ('backend-allocation-repacking','state-allocator-overhead','workspace','graph','PLE-active-backed-residence','source-page-residence','verification-read-buffer','boundary-wire','boundary-bounce-overlap'):
            self.assertTrue(any(label in d and 'UNKNOWN allocation' in d for d in admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW).deficits),label)
        for p in c.participants:
            backing=[x for x in candidate.charges if x.phase=='serve' and x.allocation_id.startswith('source-backing:'+p.participant_id)]
            self.assertEqual(sum(x.bytes for x in backing),188225033248)
            self.assertTrue(all(x.role=='backing' and x.memory_id.endswith('disk') for x in backing))

    def test_digest_context_batch_backing_role_evidence_identity_and_order(self):
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.profiles import freeze, thaw
        c=config(); p=build_plan(c,now=NOW)
        for w in (replace(c.workload,batch=64),replace(c.workload,microbatch=16),
                  replace(c.workload,context=4096,cache_settings=freeze({**thaw(c.workload.cache_settings),'attention_cells':4096}))):
            with self.subTest(w=w): self.assertNotEqual(p.digest,build_plan(replace(c,workload=w),now=NOW).digest)
        raw=q8_mapping(); profile=raw['profiles']['snapshot']
        profile['evidence'][0]['provenance']['producer']='different synthetic authority'
        reseal_profiles(profile); raw['profiles']['digest']=profile_digest(profile)
        self.assertNotEqual(p.digest,build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW).digest)
        raw=q8_mapping(); profile=raw['profiles']['snapshot']
        row=next(r for r in profile['compute_units'] if r['compute_id']=='B-gpu'); row['physical_id']='replacement-physical-gpu'
        for e in profile['evidence']:
            if 'compute:B-gpu:physical_id' in e['dependencies']: e['dependencies']['compute:B-gpu:physical_id']=row['physical_id']
        raw['participants'][1]['bindings'][1]['physical_id']=row['physical_id']
        reseal_profiles(profile); raw['profiles']['digest']=profile_digest(profile)
        raw['participants'][1]['bindings'][1]['evidence_sha256']=next(e for e in profile['evidence'] if e['evidence_id']=='synthetic-B-gpu')['sha256']
        self.assertNotEqual(p.digest,build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW).digest)

    def test_fully_bounded_config_is_admitted_only_for_synthetic_replay(self):
        from inferswarm.operator.plan import build_plan,revalidate_admission
        for selection in ('one-gpu','cpu-only'):
            raw=fully_bounded_mapping(selection)
            p=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
            self.assertEqual(p.admission.status,'ADMITTED',p.admission.deficits)
            self.assertEqual(p.admission.technical_feasibility,'FEASIBLE')
            self.assertFalse(p.admission.execution_ready)
            self.assertFalse(any(r.unknown_allocations for r in p.admission.peaks))
            self.assertEqual(revalidate_admission(p).status,'BLOCKED')
            raw['strategy_options']['bounds'].reverse()
            self.assertEqual(p.digest,build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW).digest)
            if selection=='one-gpu':
                unsupported_raw=fully_bounded_mapping(selection,'server-local')
                blocked=build_plan(parse_config(unsupported_raw,now=NOW,profile_mode='replay'),now=NOW)
                self.assertTrue(any('UNSUPPORTED_PLACEMENT' in r for r in blocked.admission.deficits))

    def test_proven_host_mirrors_are_distinct_and_digest_bearing(self):
        q=self.api(); from inferswarm.operator.plan import ResourceCharge,build_plan
        raw=fully_bounded_mapping(); baseline=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        runtime=next(r for r in raw['profiles']['snapshot']['runtime_capabilities'] if r['runtime_id']=='runtime-B-cpu')
        raw['strategy_options']['host_mirrors']=[dict(allocation_id='explicit-copy-1',memory_id='B-ram',bytes=2**20,evidence_id=runtime['evidence_id'])]
        for phase in ('load','serve','cleanup'):
            charge=ResourceCharge('host-mirror:explicit-copy-1/'+phase,'B-ram','optional',2**20,phase,runtime['evidence_id'])
            runtime['capabilities'].append(q.bound_capability(charge,2**20))
        reseal_profiles(raw['profiles']['snapshot']); raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
        p=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertNotEqual(p.digest,baseline.digest)
        self.assertEqual(next(r for r in p.admission.peaks if r.memory_id=='B-ram').peak_bytes-next(r for r in baseline.admission.peaks if r.memory_id=='B-ram').peak_bytes,2**20)
        self.assertTrue(all(c.role=='optional' for c in p.candidate.charges if c.allocation_id.startswith('host-mirror:')))
        raw['strategy_options']['host_mirrors'].append(dict(allocation_id='explicit-copy-2',memory_id='B-ram',bytes=2**20,evidence_id=runtime['evidence_id']))
        for phase in ('load','serve','cleanup'):
            charge=ResourceCharge('host-mirror:explicit-copy-2/'+phase,'B-ram','optional',2**20,phase,runtime['evidence_id'])
            runtime['capabilities'].append(q.bound_capability(charge,2**20))
        reseal_profiles(raw['profiles']['snapshot']); raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
        p2=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertEqual(next(r for r in p2.admission.peaks if r.memory_id=='B-ram').peak_bytes-next(r for r in p.admission.peaks if r.memory_id=='B-ram').peak_bytes,2**20)

    def test_typed_native_options_model_slot_and_output_slot(self):
        q=self.api()
        self.assertTrue(hasattr(q,'NativeQ8Options'),'missing typed native options')
        opt=q.NativeQ8Options('one-gpu')
        self.assertEqual(opt.gpu_layers,35)
        self.assertEqual(opt.layer_device_indices(),(None,)*14+(0,)*31+(1,)*4)
        self.assertEqual(q.NativeQ8Options('cpu-only').layer_device_indices(),(None,)*14+(0,)*35)
        with self.assertRaisesRegex(ValueError,'fixed native options'): q.NativeQ8Options('one-gpu',gpu_layers=34)
        with self.assertRaisesRegex(ValueError,'fixed native options'): q.NativeQ8Options('fallback')
        for args in (dict(flash_attention='auto'),dict(kv_unified=True),dict(gpu_layers=True),dict(kv_offload=1)):
            with self.subTest(args=args),self.assertRaisesRegex(ValueError,'fixed native options'): q.NativeQ8Options('one-gpu',**args)

    def test_synthetic_positive_cannot_hide_unknown_capacity_budget_failure(self):
        from inferswarm.operator.plan import build_plan
        raw=fully_bounded_mapping(); raw['policy']['memory_limits'][0]['peak_bytes']=1
        p=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertTrue(any('policy peak' in r for r in p.admission.deficits))
        self.assertEqual(p.selection,'one-gpu')
        self.assertEqual(len(p.candidate.assignments),1224)
        raw=fully_bounded_mapping(); raw['strategy_options']['bounds'].pop()
        p=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertTrue(any('UNKNOWN allocation' in r for r in p.admission.deficits))
        self.assertEqual(p.selection,'one-gpu')

    def test_route_profile_context_not_silently_relabelled(self):
        q=self.api(); c=config()
        snapshot=replace(c.profiles.snapshot,runtime_capabilities=tuple(replace(r,route='server-local') for r in c.profiles.snapshot.runtime_capabilities))
        with self.assertRaisesRegex(ValueError,'runtime route context'):
            q.q8_candidates(replace(c,profiles=replace(c.profiles,snapshot=snapshot)),metadata())

    def test_native_environment_cache_shape_is_explicit(self):
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.strategy import llama_cpp_spec
        q=self.api(); p=build_plan(config(),now=NOW); s=llama_cpp_spec(p)
        self.assertIn('--flash-attn',s.args)
        self.assertEqual(s.args[s.args.index('--flash-attn')+1],'off')
        self.assertIn('--no-kv-unified',s.args)
        self.assertTrue(any(r.capability=='qsa-top-k-qualified:2048' for r in p.candidate.capability_requirements))
        self.assertTrue(any(r.capability=='unmodified-source-tree:'+q.RUNTIME_TREE for r in p.candidate.capability_requirements))

    def test_generic_builder_does_not_interpret_q8_option_keys(self):
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.profiles import freeze
        from inferswarm.operator import plan
        c=config(); candidate=self.api().q8_candidates(c,metadata())[0]
        opaque=replace(c,strategy_options=freeze({'uninterpreted':{'object':[]}}))
        with patch('inferswarm.operator.strategy.candidates_for',return_value=(candidate,)):
            p=build_plan(opaque,now=NOW)
        self.assertEqual(p.candidate,candidate)

    def test_modified_candidate_cannot_reuse_original_plan_digest(self):
        from inferswarm.operator.plan import build_plan,revalidate_admission
        raw=fully_bounded_mapping(); p=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        charge=p.candidate.charges[0]
        changed=replace(p,candidate=replace(p.candidate,charges=(replace(charge,role='optional'),)+p.candidate.charges[1:]))
        receipt=revalidate_admission(changed,now=NOW)
        self.assertEqual(receipt.status,'BLOCKED')
        self.assertTrue(any('plan digest integrity' in r for r in receipt.deficits))
        changed=replace(p,selection='cpu-only')
        self.assertTrue(any('plan field integrity' in r for r in revalidate_admission(changed,now=NOW).deficits))

    def test_coherent_config_options_cannot_reuse_stale_candidate_digest(self):
        from inferswarm.operator.plan import build_plan, revalidate_admission
        from inferswarm.operator.strategy import llama_cpp_spec
        raw=fully_bounded_mapping(); original_raw=copy.deepcopy(raw)
        original=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertEqual(revalidate_admission(original,now=NOW).status,'ADMITTED')
        self.assertFalse(original.admission.execution_ready)
        self.assertEqual(llama_cpp_spec(original).startup_timeout_seconds,120)
        raw['strategy_options']['startup_timeout_seconds']=3600
        updated=parse_config(raw,now=NOW,profile_mode='replay')
        fresh=build_plan(updated,now=NOW)
        self.assertEqual(revalidate_admission(fresh,now=NOW).status,'ADMITTED')
        self.assertNotEqual(original.digest,fresh.digest)
        self.assertEqual(llama_cpp_spec(fresh).startup_timeout_seconds,3600)
        stale=replace(original,config=updated,strategy_options=updated.strategy_options)
        self.assertIs(stale.candidate,original.candidate)
        self.assertEqual(stale.digest,original.digest)
        with patch('inferswarm.operator.strategy.llama_cpp_spec',wraps=llama_cpp_spec) as consume, \
             patch('subprocess.run',side_effect=AssertionError('no process access')), \
             patch('socket.socket.connect',side_effect=AssertionError('no socket access')):
            receipt=revalidate_admission(stale,now=NOW)
            if receipt.status=='ADMITTED': consume(stale)
            self.assertEqual(receipt.deficits,('plan strategy options integrity mismatch',))
            self.assertEqual(receipt.status,'BLOCKED')
            self.assertFalse(receipt.execution_ready)
            consume.assert_not_called()
        self.assertEqual(original.config,parse_config(original_raw,now=NOW,profile_mode='replay'))
        self.assertEqual(raw['strategy_options']['startup_timeout_seconds'],3600)

    def test_substituted_canonical_options_cannot_self_seal_against_actual_config(self):
        from dataclasses import asdict
        from inferswarm.operator.plan import build_plan, revalidate_admission
        from inferswarm.operator.profiles import freeze, thaw, sha256
        original=build_plan(parse_config(fully_bounded_mapping(),now=NOW,profile_mode='replay'),now=NOW)
        options=thaw(original.candidate.canonical_strategy_options)
        options['startup_timeout_seconds']=3600
        candidate=replace(original.candidate,canonical_strategy_options=freeze(options))
        # Seal the substituted candidate using the pre-correction payload law.
        payload=asdict(original.config); payload['metadata'].pop('path')
        payload['strategy_options']=candidate.canonical_strategy_options
        payload['candidate']=asdict(candidate)
        forged=replace(original,candidate=candidate,digest=sha256(payload))
        self.assertNotEqual(forged.digest,original.digest)
        receipt=revalidate_admission(forged,now=NOW)
        self.assertEqual(receipt.deficits,('plan strategy options integrity mismatch',))
        self.assertEqual(receipt.status,'BLOCKED')
        self.assertFalse(receipt.execution_ready)

    def test_options_integrity_preserves_strategy_array_object_and_inventory_normalization(self):
        from inferswarm.operator.plan import ResourceCharge, build_plan, revalidate_admission
        from inferswarm.operator.profiles import thaw
        q=self.api(); raw=fully_bounded_mapping()
        runtime=next(r for r in raw['profiles']['snapshot']['runtime_capabilities'] if r['runtime_id']=='runtime-B-cpu')
        raw['strategy_options']['host_mirrors']=[dict(allocation_id=aid,memory_id='B-ram',bytes=2**20,evidence_id=runtime['evidence_id']) for aid in ('mirror-b','mirror-a')]
        for mirror in raw['strategy_options']['host_mirrors']:
            for phase in ('load','serve','cleanup'):
                charge=ResourceCharge('host-mirror:'+mirror['allocation_id']+'/'+phase,'B-ram','optional',mirror['bytes'],phase,mirror['evidence_id'])
                runtime['capabilities'].append(q.bound_capability(charge,mirror['bytes']))
        reseal_profiles(raw['profiles']['snapshot']); raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
        original_raw=copy.deepcopy(raw)
        original=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertEqual(revalidate_admission(original,now=NOW).status,'ADMITTED')
        raw['strategy_options']['bounds'].reverse(); raw['strategy_options']['host_mirrors'].reverse()
        def reverse_objects(value):
            if isinstance(value,dict): return {k:reverse_objects(v) for k,v in reversed(tuple(value.items()))}
            if isinstance(value,list): return [reverse_objects(v) for v in value]
            return value
        updated=parse_config(reverse_objects(raw),now=NOW,profile_mode='replay')
        fresh=build_plan(updated,now=NOW)
        self.assertEqual(original.digest,fresh.digest)
        self.assertEqual(original.candidate.canonical_strategy_options,fresh.candidate.canonical_strategy_options)
        equivalent=replace(original,config=updated,strategy_options=updated.strategy_options)
        self.assertEqual(revalidate_admission(equivalent,now=NOW).status,'ADMITTED')
        self.assertIsInstance(thaw(equivalent.strategy_options)['bindings'],dict)
        self.assertIsInstance(thaw(equivalent.strategy_options)['bounds'],list)
        self.assertEqual(original.config,parse_config(original_raw,now=NOW,profile_mode='replay'))
        empty=build_plan(config(),now=NOW)
        self.assertEqual(thaw(empty.candidate.canonical_strategy_options)['bounds'],[])
        self.assertEqual(thaw(empty.candidate.canonical_strategy_options)['host_mirrors'],[])
        for field in ('bounds','host_mirrors'):
            invalid=q8_mapping(); invalid['strategy_options'][field]={}
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,field+' must be array'):
                build_plan(parse_config(invalid,now=NOW,profile_mode='replay'),now=NOW)

    def test_generic_options_binding_rederives_opaque_strategy_payload(self):
        from inferswarm.operator.plan import build_plan, revalidate_admission
        from inferswarm.operator.profiles import freeze
        c=parse_config(fully_bounded_mapping(),now=NOW,profile_mode='replay')
        candidate=self.api().q8_candidates(c,metadata())[0]
        opaque=replace(c,strategy_options=freeze({'uninterpreted':{'object':{},'array':[]}}))
        def derive(config, index):
            return (replace(candidate,canonical_strategy_options=config.strategy_options),)
        with patch('inferswarm.operator.strategy.candidates_for',side_effect=derive):
            original=build_plan(opaque,now=NOW)
            self.assertEqual(revalidate_admission(original,now=NOW).status,'ADMITTED')
            changed=replace(opaque,strategy_options=freeze({'uninterpreted':{'object':{},'array':[1]}}))
            fresh=build_plan(changed,now=NOW)
            self.assertNotEqual(original.digest,fresh.digest)
            stale=replace(original,config=changed,strategy_options=changed.strategy_options)
            self.assertEqual(revalidate_admission(stale,now=NOW).deficits,('plan strategy options integrity mismatch',))

    def test_bound_token_alone_does_not_bind_physical_memory(self):
        raw=fully_bounded_mapping()
        evidence=next(e for e in raw['profiles']['snapshot']['evidence'] if e['evidence_id']=='synthetic-runtime-B-cpu')
        evidence['dependencies'].pop('memory:B-ram:physical_id',None)
        reseal_profiles(raw['profiles']['snapshot']); raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
        c=parse_config(raw,now=NOW,profile_mode='replay')
        with self.assertRaisesRegex(ValueError,'bound physical memory scope'):
            self.api().q8_candidates(c,metadata())

    def test_native_typed_lowering_never_legacy_cmoe(self):
        q=self.api(); from inferswarm.operator.plan import build_plan
        from inferswarm.operator.strategy import llama_cpp_spec
        for selection,split,devices,native in [('one-gpu','31,4','RPC0,RPC1','CPU,CUDA0'),('cpu-only','1','RPC0','CPU')]:
            p=build_plan(config(selection),now=NOW); s=llama_cpp_spec(p)
            self.assertEqual(s.args[s.args.index('--tensor-split')+1],split)
            self.assertEqual(s.args[s.args.index('--gpu-layers')+1],'35')
            self.assertEqual(s.device,devices)
            self.assertEqual(s.rpc_args,('--device',native))
            self.assertNotIn('-cmoe',s.args)
            self.assertIn('--kv-offload',s.args)
            self.assertEqual(s.args[s.args.index('--lazy-mode')+1],'on')
            self.assertFalse(s.executable_ready)
            self.assertEqual(s.expected_assignments,p.candidate.assignments)


if __name__=='__main__': unittest.main()
