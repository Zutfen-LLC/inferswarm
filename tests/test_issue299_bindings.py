"""Complete public descriptors, explicitly SYNTHETIC observer plumbing only."""
import copy
from dataclasses import asdict, replace, FrozenInstanceError
from datetime import timedelta
import importlib
import json
import unittest
from unittest.mock import patch

from inferswarm.operator.config import parse_config
from inferswarm.operator.plan import build_plan
from inferswarm.operator.profiles import (_dependency_context, canonical, freeze,
    sha256, thaw)
from tests.issue299_fixture import NOW, reseal_profiles, profile_digest
from tests.test_issue299_q8_plan import fully_bounded_mapping

CAPS = ('physical-bindings/1', 'complete-materialization/1', 'state-authority/1',
        'copy-route/1', 'process-identity/1')
PRODUCER = 'synthetic-independent-probe'
METHOD = 'native-context-inventory/1'
QUALIFICATION = 'owned-observer/1:' + PRODUCER + ':' + METHOD


def wire(value):
    return json.loads(canonical(thaw(asdict(value)) if hasattr(value, '__dataclass_fields__') else thaw(value)))


def plan_fixture(selection):
    raw = fully_bounded_mapping(selection)
    for r in raw['profiles']['snapshot']['runtime_capabilities']:
        r['capabilities'].extend((*CAPS, QUALIFICATION))
    reseal_profiles(raw['profiles']['snapshot'])
    raw['profiles']['digest'] = profile_digest(raw['profiles']['snapshot'])
    return build_plan(parse_config(raw, now=NOW, profile_mode='replay'), now=NOW)


def subject(plan):
    return dict(plan_digest=plan.digest, selection=plan.selection,
        profiles_digest=plan.profiles.digest, profiles_file_sha256=plan.profiles.sha256,
        metadata_digest=plan.metadata.digest, metadata_sha256=plan.metadata.sha256,
        model_digest=sha256(asdict(plan.model)), workload_digest=sha256(asdict(plan.workload)))


def dependencies(plan):
    return {**_dependency_context(plan.profiles.snapshot),
        **dict(plan.candidate.subject.dependencies), **{'subject:'+k:str(v) for k,v in subject(plan).items()}}


def seal(payload):
    payload['evidence']['record_digest'] = sha256({k:v for k,v in payload.items() if k != 'evidence'} | {
        'evidence': {k:v for k,v in payload['evidence'].items() if k != 'record_digest'}})
    return payload


def envelope(plan, participant):
    s = plan.profiles.snapshot
    host = next(r for r in s.hosts if r.host_id == participant.host_id)
    computes = {r.compute_id:r for r in s.compute_units}
    memories = {r.memory_id:r for r in s.memory_resources}
    runtimes = {r.runtime_id:r for r in s.runtime_capabilities}
    bindings = sorted(participant.bindings, key=lambda b:b.visible_selector)
    return seal(dict(schema='binding-preflight/1', participant_id=participant.participant_id,
        subject=subject(plan), host=wire(host), endpoint=participant.rpc_endpoint,
        visibility=dict(native=[b.native_selector for b in bindings], visible=[b.visible_selector for b in bindings], environment={}),
        capabilities=list(CAPS), bindings=[dict(binding=wire(b), compute=wire(computes[b.compute_id]),
            memory=wire(memories[b.memory_id]), runtime=wire(runtimes[b.runtime_id]), advertised_type='GPU') for b in bindings],
        evidence=dict(producer=PRODUCER, method=METHOD, provenance={'protocol':'independent capture/1', 'record_id':'synthetic-'+participant.participant_id},
            observed_at='2026-01-02T11:59:59Z', expires_at='2026-01-02T12:30:00Z', evidence_class='measured', source_scope='synthetic',
            dependencies=dependencies(plan), record_digest='0'*64)))


def identity(api, p):
    bindings = sorted(p.bindings, key=lambda b:b.visible_selector)
    return api.ProcessIdentity(p.participant_id, p.host_id, p.boot_epoch, p.topology_epoch,
        101 if p.role=='client' else 202, 'opaque-start-'+p.host_id, p.runtime_executable,
        p.runtime_sha256, (p.runtime_executable, '--device', ','.join(b.native_selector for b in bindings)),
        freeze(dict(native=[b.native_selector for b in bindings], visible=[b.visible_selector for b in bindings], environment={})),
        p.rpc_endpoint)


def source_receipt(plan, p):
    ids = {b.binding_id for b in p.bindings}
    rows = [dict(state_id=a.state_id, member=a.member, offset=a.absolute_offset,
        length=a.encoded_bytes, sha256=sha256({'SYNTHETIC':a.state_id}), binding_id=a.binding_id,
        memory_id=a.memory_id, authority=a.authority, cache_eligible=False, cache_key=None)
        for a in plan.candidate.assignments if a.binding_id in ids]
    # Only the source join fields are used by this seam. These are fabricated
    # test receipts, never outputs of a full public-weight verifier.
    return dict(schema='q8-source-receipt/1', participant_id=p.participant_id,
        status='VERIFIED-not-consumed', plan_digest=plan.digest, metadata_digest=plan.metadata.digest,
        source_identity={k:getattr(plan.model,k) for k in ('source_id','revision','representation')},
        member_identities=wire(plan.model)['members'], runtime_sha256=p.runtime_sha256, range_identities=rows,
        physical_observation=False, cache_consumed=False)


def owned_payload(api, plan, p, sources):
    out = envelope(plan, p)
    out['schema'] = 'owned-observation/1'
    out['invocation_token'] = 'synthetic-invocation-token'
    out['process'] = wire(identity(api, p))
    out['context'] = wire(plan.workload)
    out['source_receipt_digest'] = sha256(sources[p.participant_id])
    ids = {b.binding_id for b in p.bindings}
    out['tensors'] = []
    out['states'] = []
    out['buffers'] = []
    for field, records in [('tensors',plan.candidate.assignments), ('states',plan.candidate.required_state)]:
        for a in records:
            if a.binding_id not in ids: continue
            bid = field+':'+a.state_id
            amount = a.encoded_bytes if field=='tensors' else (a.lower_bound_bytes or 1)
            observation = dict(contract=wire(a), materialization_id=bid, buffer_id=bid,
                buffer_offset=0, allocated_bytes=amount, resident_bytes=amount,
                residence='resident', native_buffer_type='synthetic-native',
                source_sha256=sha256({'SYNTHETIC':a.state_id}) if field=='tensors' else None)
            if field=='states':
                observation.update(authority_owner=a.binding_id,authority_epoch='synthetic-invocation-token',
                    lineage_id='synthetic-lineage:'+a.state_id, dependencies_observed=list(a.dependencies),
                    actual_representation=a.representation)
            out[field].append(observation)
            out['buffers'].append(dict(buffer_id=bid, binding_id=a.binding_id, memory_id=a.memory_id,
                allocated_bytes=amount, resident_bytes=amount, residence='resident', native_buffer_type='synthetic-native'))
    out['auxiliary'] = [dict(allocation_id=c.allocation_id, memory_id=c.memory_id, role=c.role,
        phase=c.phase, actual_bytes=c.bytes or 1, resident_bytes=0 if c.role in ('backing','virtual','reserve') else (c.bytes or 1),
        residence=c.role if c.role in ('backing','virtual','reserve') else 'resident')
        for c in plan.candidate.charges if c.phase=='serve' and next(m.host_id for m in plan.profiles.snapshot.memory_resources if m.memory_id==c.memory_id)==p.host_id]
    allbindings={b.binding_id:b for q in plan.participants for b in q.bindings}
    links={r.link_id:r for r in plan.profiles.snapshot.links}
    out['boundaries']=[]
    for b in plan.candidate.boundaries:
        if b.producer_binding not in ids: continue
        copies=[]
        for i,lid in enumerate(b.link_legs):
            link=links[lid]
            source_memory=(allbindings[b.producer_binding].memory_id if i==0 else
                next(m.memory_id for m in plan.profiles.snapshot.memory_resources if m.host_id==b.route_hosts[i] and m.kind=='ram'))
            target_memory=(allbindings[b.consumer_binding].memory_id if i==len(b.link_legs)-1 else
                next(m.memory_id for m in plan.profiles.snapshot.memory_resources if m.host_id==b.route_hosts[i+1] and m.kind=='ram'))
            copies.append(dict(sequence=i,source_materialization_id='synthetic-copy:'+b.semantic_id+':'+str(i),
                target_materialization_id='synthetic-copy:'+b.semantic_id+':'+str(i+1),
                source_host=b.route_hosts[i],target_host=b.route_hosts[i+1],
                source_memory_id=source_memory,target_memory_id=target_memory,link_id=lid,path=link.path,protocol=link.protocol,
                wire_bytes=17,staging_bytes=17,completed=True,invocation_token='synthetic-invocation-token',
                shape=list(b.shape),strides=list(b.strides),representation=b.representation,
                alias_base_id='synthetic-activation:'+b.semantic_id,view_offset=0,base_extent_bytes=b.logical_bytes,
                ordering=b.ordering,dependencies_observed=list(b.dependencies),state_dependencies_observed=list(b.state_dependencies)))
        out['boundaries'].append(dict(contract=wire(b),route=next(r.route for r in plan.profiles.snapshot.runtime_capabilities if r.runtime_id==p.bindings[0].runtime_id),
            copy_method='native-copy-trace/1',copy_provenance={'producer':PRODUCER,'protocol':'actual successful copies'},
            wire_bytes=sum(c['wire_bytes'] for c in copies),staging_bytes=sum(c['staging_bytes'] for c in copies),completed=True,copies=copies))
    return seal(out)


class FakeTransport:
    def __init__(self, api, payload, callback=None, exit_code=0):
        self.api, self.payload, self.callback, self.exit_code = api, payload, callback, exit_code
        self.calls = []

    def preflight(self, participant, plan):
        self.calls.append('preflight')
        return self.api.TransportReply(self.exit_code, canonical(self.payload))

    def observe(self, participant, plan, **kwargs):
        self.calls.append(('observe',kwargs))
        if self.callback: self.callback()
        return self.api.TransportReply(self.exit_code, canonical(self.payload))


class BindingContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans = {s:plan_fixture(s) for s in ('one-gpu','cpu-only')}

    def api(self):
        try: return importlib.import_module('inferswarm.operator.bindings')
        except ModuleNotFoundError: self.fail('strict owned binding contracts are absent')

    def preflight(self, payload=None, plan=None, p=None, **kwargs):
        api=self.api(); plan=plan or self.plans['one-gpu']; p=p or plan.participants[1]
        payload=payload or envelope(plan,p)
        return api.validate_preflight(p,plan,api.TransportReply(0,canonical(payload)),
            mode='synthetic-test',clock=lambda:NOW,**kwargs)

    def capture(self, plan, p, payload, reader=None, callback=None, exit_code=0, **kwargs):
        api=self.api(); owned=identity(api,p)
        return api.gather_owned_observation(p,plan,transport=FakeTransport(api,payload,callback,exit_code),
            owned=owned,owned_argv=owned.effective_argv,invocation_token='synthetic-invocation-token',
            identity_reader=reader or (lambda participant,pid:owned),mode='synthetic-test',clock=lambda:NOW,**kwargs)

    def complete(self, selection='one-gpu', mutate=None):
        api=self.api(); plan=self.plans[selection]
        sources={p.participant_id:source_receipt(plan,p) for p in plan.participants}
        payloads=[owned_payload(api,plan,p,sources) for p in plan.participants]
        if mutate: mutate(payloads,sources)
        observations=[self.capture(plan,p,seal(data)) for p,data in zip(plan.participants,payloads)]
        return api.reconcile_materialization(plan,observations,source_receipts=sources,
            mode='synthetic-test',clock=lambda:NOW)

    def test_cpu_advertised_gpu_and_ordered_same_endpoint_are_independent(self):
        receipt=self.preflight()
        self.assertFalse(receipt.physical_qualified)
        self.assertFalse(receipt.execution_authorized)
        self.assertEqual([r['binding']['native_selector'] for r in thaw(receipt.observed)['bindings']],['CPU','CUDA0'])
        self.assertEqual([r['binding']['visible_selector'] for r in thaw(receipt.observed)['bindings']],['RPC0','RPC1'])
        with self.assertRaises(FrozenInstanceError): receipt.physical_qualified=True
        with self.assertRaises(TypeError): receipt.observed[0]=()

    def test_explicit_cpu_only_complete_no_gpu_or_fallback(self):
        r=self.complete('cpu-only')
        self.assertEqual(r.tensor_count,1224)
        self.assertEqual(r.state_count,111)
        self.assertEqual(r.binding_counts,(('binding-A-cpu',361),('binding-B-cpu',863)))
        self.assertEqual(self.plans['cpu-only'].selection,'cpu-only')

    def test_complete_authentic_1224_111_with_private_deterministic_receipt(self):
        before=copy.deepcopy(self.plans['one-gpu'])
        r=self.complete()
        self.assertEqual((r.tensor_count,r.state_count,r.boundary_count),(1224,111,2))
        self.assertEqual(r.binding_counts,(('binding-A-cpu',361),('binding-B-cpu',783),('binding-B-gpu',80)))
        self.assertFalse(r.physical_qualified); self.assertFalse(r.execution_authorized)
        self.assertEqual(r.evidence_classes,(('measured','synthetic'),))
        self.assertEqual(before,self.plans['one-gpu'])
        def reorder(payloads,sources):
            for payload in payloads:
                for key in ('tensors','states','buffers','auxiliary','boundaries'): payload[key].reverse()
            for source in sources.values(): source['range_identities'].reverse()
            for payload in payloads: payload['source_receipt_digest']=sha256(sources[payload['participant_id']])
        self.assertEqual(r.observed_digest,self.complete(mutate=reorder).observed_digest)

    def test_binding_mutations_specific_first_predicates(self):
        baseline=envelope(self.plans['one-gpu'],self.plans['one-gpu'].participants[1])
        cases=[('ordered binding translation',lambda x:x['bindings'].reverse()),
            ('physical binding identity',lambda x:x['bindings'][1]['compute'].update(physical_id='other-UUID')),
            ('physical binding identity',lambda x:x['bindings'][0]['compute'].update(physical_id='')),
            ('physical memory ownership',lambda x:x['bindings'][0]['memory'].update(kind='vram')),
            ('configured visibility',lambda x:x['visibility']['native'].reverse()),
            ('runtime identity',lambda x:x['bindings'][1]['runtime'].update(build_id='stale')),
            ('host epoch',lambda x:x['host'].update(boot_epoch='old')),
            ('binding coverage',lambda x:x['bindings'].pop()),
            ('binding coverage',lambda x:x['bindings'].append(copy.deepcopy(x['bindings'][0])))]
        for reason,change in cases:
            with self.subTest(reason=reason):
                data=copy.deepcopy(baseline); change(data); seal(data); original=copy.deepcopy(data)
                with self.assertRaisesRegex(ValueError,reason): self.preflight(data)
                self.assertEqual(original,data)

    def test_provenance_scope_clock_freshness_dependencies_and_caps(self):
        p=self.plans['one-gpu']; baseline=envelope(p,p.participants[1])
        cases=[('independent observer method',lambda x:x['evidence'].update(method='expected-config-echo/1')),
            ('observer capability',lambda x:x['capabilities'].pop()),
            ('observer evidence class',lambda x:x['evidence'].update(evidence_class='estimated')),
            ('expired observer evidence',lambda x:x['evidence'].update(expires_at='2026-01-02T12:00:00Z')),
            ('stale observer evidence',lambda x:x['evidence'].update(observed_at='2026-01-01T12:00:00Z')),
            ('observer dependency',lambda x:x['evidence']['dependencies'].update({'link:A-B:path':'other-path'})),
            ('observer subject',lambda x:x['subject'].update(workload_digest='a'*64))]
        for reason,change in cases:
            with self.subTest(reason=reason):
                data=copy.deepcopy(baseline); change(data); seal(data)
                with self.assertRaisesRegex(ValueError,reason): self.preflight(data)
        data=copy.deepcopy(baseline); data['host']['physical_id']='other'; # deliberately leave seal stale
        with self.assertRaisesRegex(ValueError,'observer record digest'): self.preflight(data)
        api=self.api()
        for kwargs,reason in [({},'non-live'),({'clock':lambda:NOW},'live clock'),
                ({'mode':'synthetic-test'},'synthetic test clock'),({'mode':'replay','clock':lambda:NOW},'observation mode')]:
            with self.subTest(kwargs=kwargs),self.assertRaisesRegex(ValueError,reason):
                api.validate_preflight(p.participants[1],p,api.TransportReply(0,canonical(baseline)),**kwargs)
        unqualified=replace(p,profiles=replace(p.profiles,snapshot=replace(p.profiles.snapshot,
            runtime_capabilities=tuple(replace(r,capabilities=tuple(c for c in r.capabilities if c!=QUALIFICATION)) for r in p.profiles.snapshot.runtime_capabilities))))
        # Profile integrity refuses this before any observer can claim support.
        with self.assertRaisesRegex(ValueError,'evidence payload mismatch'): self.preflight(plan=unqualified)

    def test_preflight_has_no_pid_grammar_and_transport_failure_never_parses(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        data=envelope(plan,p); data['process']={'pid':202}; seal(data)
        with self.assertRaisesRegex(ValueError,'preflight fields'): self.preflight(data)
        with self.assertRaisesRegex(ValueError,'observer transport exit 7'):
            api.validate_preflight(p,plan,api.TransportReply(7,b'{parseable but not considered'),mode='synthetic-test',clock=lambda:NOW)

    def test_default_unsupported_before_any_effect_or_identity_reader(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        with patch('subprocess.run',side_effect=AssertionError('launch')),patch('socket.socket',side_effect=AssertionError('socket')):
            for call in (lambda:api.BindingTransport().preflight(p,plan),
                    lambda:api.BindingTransport().observe(p,plan,owned_pid=202,start='start',invocation_token='token',owned_argv=('runtime',)),
                    lambda:api.preflight_bindings(plan),
                    lambda:api.gather_owned_observation(p,plan,owned=identity(api,p),owned_argv=('runtime',),invocation_token='token',identity_reader=lambda *x:self.fail('identity read'))):
                with self.subTest(call=call),self.assertRaisesRegex(ValueError,'UNKNOWN/unsupported owned materialization observer'): call()

    def test_owned_capture_before_after_and_mid_capture_identity_changes(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        sources={q.participant_id:source_receipt(plan,q) for q in plan.participants}
        data=owned_payload(api,plan,p,sources); owned=identity(api,p)
        for field,value in [('start','recycled'),('binary_sha256','a'*64),('effective_argv',('override',)),
                            ('visibility',freeze({'other':'mask'})),('pid',303)]:
            for when in ('before','during'):
                with self.subTest(field=field,when=when):
                    current=[replace(owned,**{field:value}) if when=='before' else owned]
                    with self.assertRaisesRegex(ValueError,'owned process identity '+('before' if when=='before' else 'after')):
                        self.capture(plan,p,data,reader=lambda *x:current[0],callback=lambda:current.__setitem__(0,replace(owned,**{field:value})))
        with self.assertRaisesRegex(ValueError,'owned argv'):
            api.gather_owned_observation(p,plan,transport=FakeTransport(api,data),owned=owned,owned_argv=('hidden-override',),
                invocation_token='synthetic-invocation-token',identity_reader=lambda *x:owned,mode='synthetic-test',clock=lambda:NOW)
        with self.assertRaisesRegex(ValueError,'observer transport exit 9'): self.capture(plan,p,data,exit_code=9)

    def test_owned_envelope_cannot_echo_other_invocation_or_process(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        sources={q.participant_id:source_receipt(plan,q) for q in plan.participants}
        baseline=owned_payload(api,plan,p,sources)
        for reason,change in [('invocation token',lambda x:x.update(invocation_token='different')),
                ('owned observation process',lambda x:x['process'].update(start='other')),
                ('owned observation process',lambda x:x['process'].update(binary_sha256='a'*64)),
                ('observer context',lambda x:x['context'].update(context=4096)),
                ('configured visibility',lambda x:x['visibility']['visible'].reverse())]:
            with self.subTest(reason=reason):
                data=copy.deepcopy(baseline); change(data); seal(data)
                with self.assertRaisesRegex(ValueError,reason): self.capture(plan,p,data)

    def test_complete_tensor_omission_duplicate_extra_and_all_placement_classes(self):
        cases=[('tensor coverage',lambda xs:xs[0]['tensors'].pop()),
            ('duplicate tensor',lambda xs:xs[1]['tensors'].append(copy.deepcopy(xs[1]['tensors'][0]))),
            ('tensor coverage',lambda xs:xs[1]['tensors'].append(dict(xs[1]['tensors'][0],contract={**xs[1]['tensors'][0]['contract'],'state_id':'invented'})))]
        for name in ('per_layer_token_embd.weight','token_embd.weight','blk.1.ple_value.weight',
                     'blk.17.ffn_gate_exps.weight','blk.45.ffn_up_exps.weight','output.weight','output_hc_down.weight','output_hc_norm.weight','output_hc_up.weight'):
            cases.append(('tensor ownership',lambda xs,n=name:next(r for x in xs for r in x['tensors'] if r['contract']['state_id']==n)['contract'].update(binding_id='wrong-owner')))
        for reason,change in cases:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.complete(mutate=lambda xs,s:change(xs))

    def test_exact_tensor_descriptor_authority_and_actual_materialization(self):
        cases=[('tensor descriptor',lambda r:r['contract'].update(absolute_offset=r['contract']['absolute_offset']+32)),
            ('tensor descriptor',lambda r:r['contract'].update(ggml_type=True)),
            ('tensor descriptor',lambda r:r['contract'].update(shape=[1])),
            ('tensor authority',lambda r:r['contract'].update(authority='echo')),
            ('tensor memory',lambda r:r['contract'].update(memory_id='B-vram')),
            ('materialization bytes',lambda r:r.update(allocated_bytes=None)),
            ('materialization residence',lambda r:r.update(resident_bytes=None)),
            ('materialization residence',lambda r:r.update(residence='unknown')),
            ('source range identity',lambda r:r.update(source_sha256='b'*64))]
        for reason,change in cases:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason):
                self.complete(mutate=lambda xs,s:change(xs[0]['tensors'][0]))

    def test_state_inventory_owner_representation_bound_authority_dependencies(self):
        cases=[('state coverage',lambda xs:xs[0]['states'].pop()),
            ('duplicate state',lambda xs:xs[1]['states'].append(copy.deepcopy(xs[1]['states'][0]))),
            ('state coverage',lambda xs:xs[1]['states'][0]['contract'].update(state_id='extra')),
            ('state ownership',lambda xs:xs[1]['states'][0]['contract'].update(binding_id='binding-A-cpu')),
            ('state representation',lambda xs:xs[1]['states'][0]['contract'].update(representation='wrong')),
            ('state lower bound',lambda xs:xs[1]['states'][0].update(allocated_bytes=0)),
            ('state authority',lambda xs:xs[1]['states'][0]['contract'].update(authority='new-lineage')),
            ('state dependencies',lambda xs:xs[1]['states'][0]['contract'].update(dependencies=[]))]
        for reason,change in cases:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.complete(mutate=lambda xs,s:change(xs))

    def test_buffer_and_auxiliary_complete_inventory_and_unknown_not_zero(self):
        cases=[('buffer coverage',lambda xs:xs[0]['buffers'].pop()),
            ('duplicate buffer',lambda xs:xs[0]['buffers'].append(copy.deepcopy(xs[0]['buffers'][0]))),
            ('buffer coverage',lambda xs:xs[0]['buffers'].append(dict(xs[0]['buffers'][0],buffer_id='hidden-mirror'))),
            ('buffer physical ownership',lambda xs:xs[1]['buffers'][0].update(memory_id='A-ram')),
            ('buffer extent',lambda xs:xs[1]['buffers'][0].update(allocated_bytes=1)),
            ('auxiliary coverage',lambda xs:xs[0]['auxiliary'].pop()),
            ('auxiliary observation',lambda xs:xs[0]['auxiliary'][0].update(actual_bytes=None))]
        for reason,change in cases:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.complete(mutate=lambda xs,s:change(xs))

    def test_boundary_route_legs_alias_ordering_dependencies_and_wire_staging(self):
        cases=[('boundary coverage',lambda xs:xs[1]['boundaries'].clear()),
            ('duplicate boundary',lambda xs:xs[1]['boundaries'].append(copy.deepcopy(xs[1]['boundaries'][0]))),
            ('boundary contract',lambda xs:xs[1]['boundaries'][0]['contract'].update(route_hosts=['B','B'])),
            ('boundary contract',lambda xs:xs[1]['boundaries'][0]['contract'].update(link_legs=[])),
            ('boundary contract',lambda xs:xs[1]['boundaries'][0]['contract'].update(alias_rule='unknown')),
            ('boundary contract',lambda xs:xs[1]['boundaries'][0]['contract'].update(ordering='arbitrary')),
            ('boundary contract',lambda xs:xs[1]['boundaries'][0]['contract'].update(state_dependencies=[])),
            ('boundary route',lambda xs:xs[1]['boundaries'][0].update(route='server-local')),
            ('boundary wire observation',lambda xs:xs[1]['boundaries'][0].update(wire_bytes=None)),
            ('boundary wire observation',lambda xs:xs[1]['boundaries'][0].update(wire_bytes=0)),
            ('boundary staging observation',lambda xs:xs[1]['boundaries'][0].update(staging_bytes=None)),
            ('boundary completion',lambda xs:xs[1]['boundaries'][0].update(completed=False)),
            ('boundary copy provenance',lambda xs:xs[1]['boundaries'][0].update(copy_method='layer-log'))]
        for reason,change in cases:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.complete(mutate=lambda xs,s:change(xs))

    def test_source_receipt_identity_and_global_participant_coverage(self):
        with self.assertRaisesRegex(ValueError,'source receipt identity'):
            self.complete(mutate=lambda xs,s:s[xs[1]['participant_id']].update(runtime_sha256='a'*64))
        api=self.api(); p=self.plans['one-gpu']
        with self.assertRaisesRegex(ValueError,'owned participant coverage'):
            api.reconcile_materialization(p,[],source_receipts={},mode='synthetic-test',clock=lambda:NOW)

    def test_actual_slice4a_receipt_joins_without_schema_reinterpretation(self):
        from types import SimpleNamespace
        from inferswarm.operator.config import ModelIdentity
        from inferswarm.operator.qwen_q8 import WeightAssignment
        from tests.test_issue299_source import Q8Source
        api=self.api(); fixture=Q8Source(); fixture.setUp()
        try:
            model=fixture.payload['model']
            plan=SimpleNamespace(digest=fixture.payload['plan_digest'],
                metadata=SimpleNamespace(digest=fixture.payload['metadata']['metadata_digest']),
                model=ModelIdentity(model['source_id'],model['revision'],model['representation'],tuple(tuple(m) for m in model['members'])),
                candidate=SimpleNamespace(assignments=tuple(WeightAssignment(**{**a,'shape':tuple(a['shape'])}) for a in fixture.payload['assignments'])))
            sources={}; rows=[]
            for p in fixture.payload['participants']:
                receipt=fixture.verify(p); sources[p['participant_id']]=receipt
                rows.append((SimpleNamespace(participant_id=p['participant_id'],runtime_sha256=p['runtime_sha256'],
                    bindings=tuple(SimpleNamespace(binding_id=b['binding_id']) for b in p['bindings'])),
                    {'source_receipt_digest':sha256(receipt)}))
            before=copy.deepcopy(sources)
            try: result,normalized=api._source_ranges(plan,rows,sources)
            except ValueError as exc: self.fail('actual Slice4A receipt was refused: '+str(exc))
            self.assertEqual(len(result),len(plan.candidate.assignments))
            self.assertEqual(sources,before)
            self.assertEqual(set(normalized),set(sources))
        finally: fixture.doCleanups()

    def test_expected_contract_is_not_actual_state_authority_observation(self):
        api=self.api(); plan=self.plans['one-gpu']
        sources={p.participant_id:source_receipt(plan,p) for p in plan.participants}
        rows=[(p,owned_payload(api,plan,p,sources)) for p in plan.participants]
        # This is otherwise-valid historical observer data, with only the
        # desired contract and no captured authority/lineage/dependency facts.
        for _,data in rows:
            for r in data['states']:
                for key in ('authority_owner','authority_epoch','lineage_id','dependencies_observed','actual_representation'):
                    r.pop(key,None)
        with self.assertRaisesRegex(ValueError,'actual state authority observation'):
            api._materials(plan,rows,'states',plan.candidate.required_state,{})

    def test_expected_boundary_contract_is_not_actual_copy_leg_observation(self):
        api=self.api(); plan=self.plans['one-gpu']
        sources={p.participant_id:source_receipt(plan,p) for p in plan.participants}
        rows=[(p,owned_payload(api,plan,p,sources)) for p in plan.participants]
        for _,data in rows:
            for r in data['boundaries']: r.pop('copies',None)
        with self.assertRaisesRegex(ValueError,'actual boundary copy observation'):
            api._boundaries(plan,rows)

    def test_explicit_default_transport_refuses_before_identity_capture(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        with self.assertRaisesRegex(ValueError,'UNKNOWN/unsupported owned materialization observer'):
            api.gather_owned_observation(p,plan,transport=api.BindingTransport(),owned=identity(api,p),
                owned_argv=identity(api,p).effective_argv,invocation_token='token',
                identity_reader=lambda *x:self.fail('default transport performed process observation'))

    def test_actual_state_and_copy_facts_match_not_only_expected_contract(self):
        cases=[('state authority observation',lambda xs:xs[1]['states'][0].update(authority_owner='binding-A-cpu')),
            ('state authority observation',lambda xs:xs[1]['states'][0].update(authority_epoch='old-invocation')),
            ('state authority observation',lambda xs:xs[1]['states'][0].update(lineage_id='')),
            ('state dependencies observation',lambda xs:xs[1]['states'][0].update(dependencies_observed=[])),
            ('state representation observation',lambda xs:xs[1]['states'][0].update(actual_representation='unknown')),
            ('actual boundary copy coverage',lambda xs:xs[1]['boundaries'][0]['copies'].pop()),
            ('actual boundary copy route',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(target_host='B')),
            ('actual boundary copy link',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(path='other-path')),
            ('actual boundary copy memory',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(target_memory_id='B-vram')),
            ('actual boundary copy ordering',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(sequence=1)),
            ('actual boundary copy ordering',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(invocation_token='other')),
            ('actual boundary copy dependency',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(dependencies_observed=[])),
            ('actual boundary copy alias',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(base_extent_bytes=1)),
            ('actual boundary copy completion',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(completed=False)),
            ('actual boundary copy bytes',lambda xs:xs[1]['boundaries'][0]['copies'][0].update(wire_bytes=None))]
        for reason,change in cases:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason): self.complete(mutate=lambda xs,s:change(xs))

    def test_process_visibility_private_copy_not_only_frozen_outer_tuple(self):
        from inferswarm.operator.profiles import FrozenMapping
        api=self.api(); plan=self.plans['one-gpu']; owned=identity(api,plan.participants[1])
        native=['CPU','CUDA0']; visible=['RPC0','RPC1']; environment={'MASK':'original'}
        deceptive=FrozenMapping((('native',native),('visible',visible),('environment',environment)))
        actual=replace(owned,visibility=deceptive)
        native.reverse(); visible.clear(); environment['MASK']='changed'
        self.assertEqual(thaw(actual.visibility),{'native':['CPU','CUDA0'],'visible':['RPC0','RPC1'],'environment':{'MASK':'original'}})

    def test_missing_baseline_qualified_observer_not_self_certified_by_payload(self):
        raw=fully_bounded_mapping()
        for r in raw['profiles']['snapshot']['runtime_capabilities']: r['capabilities'].extend(CAPS)
        reseal_profiles(raw['profiles']['snapshot']);raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
        p=build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        with self.assertRaisesRegex(ValueError,'observer capability not qualified'): self.preflight(plan=p)

    def test_public_preflight_and_binding_reconciliation_share_owned_seam(self):
        api=self.api(); plan=self.plans['one-gpu']
        class MultiTransport:
            def preflight(self,p,plan): return api.TransportReply(0,canonical(envelope(plan,p)))
        before=copy.deepcopy(plan)
        receipts=api.preflight_bindings(plan,transport=MultiTransport(),mode='synthetic-test',clock=lambda:NOW)
        self.assertEqual(len(receipts),2)
        sources={p.participant_id:source_receipt(plan,p) for p in plan.participants}
        observations=[self.capture(plan,p,owned_payload(api,plan,p,sources)) for p in plan.participants]
        bindings=api.reconcile_bindings(plan,observations,mode='synthetic-test',clock=lambda:NOW)
        self.assertEqual(len(bindings),2)
        for r in bindings: self.assertFalse(r.physical_qualified); self.assertFalse(r.execution_authorized)
        detached=thaw(bindings[0].observed);detached['bindings'].clear()
        self.assertTrue(thaw(bindings[0].observed)['bindings'])
        self.assertEqual(before,plan)
        with self.assertRaisesRegex(ValueError,'owned participant coverage'):
            api.reconcile_bindings(plan,[observations[0],observations[0]],mode='synthetic-test',clock=lambda:NOW)
        with self.assertRaisesRegex(ValueError,'owned observation mode mismatch'):
            api.reconcile_bindings(plan,observations)
        with self.assertRaisesRegex(ValueError,'process pid'):
            replace(identity(api,plan.participants[0]),pid=True)

    def test_lazy_backed_observation_reports_zero_residence_not_zero_extent(self):
        def lazy(xs,sources):
            tensor=next(r for x in xs for r in x['tensors'] if r['contract']['state_id']=='per_layer_token_embd.weight')
            tensor.update(residence='lazy-backed',resident_bytes=0)
            buffer=next(r for x in xs for r in x['buffers'] if r['buffer_id']==tensor['buffer_id'])
            buffer.update(residence='lazy-backed',resident_bytes=0)
        receipt=self.complete(mutate=lazy)
        rows=thaw(receipt.observed)['observations']
        tensor=next(r for x in rows for r in x['tensors'] if r['contract']['state_id']=='per_layer_token_embd.weight')
        self.assertEqual(tensor['resident_bytes'],0)
        self.assertEqual(tensor['allocated_bytes'],54400261120)
        self.assertFalse(receipt.physical_qualified)

    def shared_inventory(self, fields=('tensors','tensors')):
        api=self.api(); plan=self.plans['one-gpu']
        sources={p.participant_id:source_receipt(plan,p) for p in plan.participants}
        payloads=[owned_payload(api,plan,p,sources) for p in plan.participants]
        local=payloads[0]
        first=next(r for r in local[fields[0]] if r['contract']['state_id']=='blk.0.attn_gate.weight')
        second=(next(r for r in local['tensors'] if r['contract']['state_id']=='blk.0.attn_qkv.weight')
            if fields[1]=='tensors' else next(r for r in local['states']
                if r['contract']['binding_id']==first['contract']['binding_id']))
        old_ids={first['buffer_id'],second['buffer_id']}
        total=first['allocated_bytes']+second['allocated_bytes']
        for row,offset in ((first,0),(second,first['allocated_bytes'])):
            row.update(buffer_id='shared-native-base',buffer_offset=offset,
                residence='lazy-backed',resident_bytes=row['allocated_bytes'])
        local['buffers']=[b for b in local['buffers'] if b['buffer_id'] not in old_ids]
        base=dict(buffer_id='shared-native-base',binding_id=first['contract']['binding_id'],
            memory_id=first['contract']['memory_id'],allocated_bytes=total,resident_bytes=total,
            residence='lazy-backed',native_buffer_type=first['native_buffer_type'])
        local['buffers'].append(base)
        return plan,sources,payloads,(first,second),base

    def reconcile_inventory(self, plan, sources, payloads):
        api=self.api()
        for payload in payloads: seal(payload)
        before=copy.deepcopy((plan,sources,payloads))
        try:
            observations=[self.capture(plan,p,data) for p,data in zip(plan.participants,payloads)]
            frozen_before=copy.deepcopy(observations)
            try:
                return api.reconcile_materialization(plan,observations,source_receipts=sources,
                    mode='synthetic-test',clock=lambda:NOW)
            finally: self.assertEqual(frozen_before,observations)
        finally: self.assertEqual(before,(plan,sources,payloads))

    def test_shared_disjoint_view_residence_sum_cannot_exceed_base(self):
        api=self.api(); plan,sources,payloads,views,base=self.shared_inventory()
        self.assertEqual([r['contract']['state_id'] for r in views],
            ['blk.0.attn_gate.weight','blk.0.attn_qkv.weight'])
        self.assertEqual([r['buffer_offset'] for r in views],[0,16711680])
        self.assertEqual([r['resident_bytes'] for r in views],[16711680,27852800])
        self.assertEqual((base['allocated_bytes'],base['resident_bytes']),(44564480,44564480))
        receipt=self.reconcile_inventory(plan,sources,payloads)
        self.assertEqual((receipt.tensor_count,receipt.state_count,receipt.buffer_count,
            receipt.auxiliary_count,receipt.boundary_count),(1224,111,1334,43,2))
        original=copy.deepcopy(payloads)
        # Only one semantic field differs from the accepted complete capture.
        base['resident_bytes']=27852800
        seal(payloads[0])
        expected=copy.deepcopy(original)
        next(b for b in expected[0]['buffers'] if b['buffer_id']=='shared-native-base')['resident_bytes']=27852800
        seal(expected[0]); self.assertEqual(expected,payloads)
        with patch.object(api,'MaterializationReceipt',side_effect=AssertionError('contradiction reached receipt construction')):
            with self.assertRaisesRegex(ValueError,'^buffer residence sum exceeds base residence$'):
                self.reconcile_inventory(plan,sources,payloads)

    def test_shared_base_allows_padding_zero_and_partial_residence(self):
        for name,view_resident,padding,base_extra in (
                ('exact-sum',None,0,0),('resident-padding',None,4096,4096),
                ('zero',(0,0),0,0),('partial',(1024,2048),0,0),
                ('unreferenced-resident',(1024,2048),0,4096)):
            with self.subTest(name=name):
                plan,sources,payloads,views,base=self.shared_inventory()
                if view_resident is not None:
                    for row,resident in zip(views,view_resident): row['resident_bytes']=resident
                base['allocated_bytes']+=padding
                base['resident_bytes']=sum(r['resident_bytes'] for r in views)+base_extra
                receipt=self.reconcile_inventory(plan,sources,payloads)
                observed=next(b for x in thaw(receipt.observed)['observations'] for b in x['buffers']
                    if b['buffer_id']=='shared-native-base')
                self.assertEqual(observed,base)
                self.assertEqual((receipt.tensor_count,receipt.state_count,receipt.buffer_count),(1224,111,1334))
                self.assertFalse(receipt.physical_qualified); self.assertFalse(receipt.execution_authorized)

    def test_shared_tensor_state_residence_sum_uses_all_referenced_views(self):
        plan,sources,payloads,views,base=self.shared_inventory(fields=('tensors','states'))
        self.reconcile_inventory(plan,sources,payloads)
        base['resident_bytes']=max(r['resident_bytes'] for r in views)
        with self.assertRaisesRegex(ValueError,'^buffer residence sum exceeds base residence$'):
            self.reconcile_inventory(plan,sources,payloads)

    def test_shared_buffer_existing_specific_guards_precede_sum_check(self):
        cases=(('buffer overlapping materializations',lambda v,b:v[1].update(buffer_offset=0)),
            ('buffer extent mismatch',lambda v,b:v[1].update(buffer_offset=v[1]['buffer_offset']+1)),
            ('buffer physical ownership mismatch',lambda v,b:b.update(memory_id='B-ram')),
            ('buffer residence mismatch',lambda v,b:b.update(resident_bytes=1)))
        for reason,change in cases:
            with self.subTest(reason=reason):
                plan,sources,payloads,views,base=self.shared_inventory(); change(views,base)
                with self.assertRaisesRegex(ValueError,'^'+reason+'$'):
                    self.reconcile_inventory(plan,sources,payloads)

    def failed_capture(self, after='stable', error_type=OSError):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        sources={q.participant_id:source_receipt(plan,q) for q in plan.participants}
        payload=owned_payload(api,plan,p,sources); owned=identity(api,p)
        before=copy.deepcopy((plan,sources,payload,owned))
        current=[owned]; reads=[]; capture_error=error_type('capture connection lost')
        after_error=OSError('after identity read unavailable')
        def reader(participant,pid):
            reads.append((participant,pid,current[0]))
            if len(reads)==2 and after=='reader-failure': raise after_error
            return current[0]
        def lose_capture():
            if after=='drift': current[0]=replace(owned,start='recycled-during-failed-capture')
            raise capture_error
        transport=FakeTransport(api,payload,callback=lose_capture)
        expected_type=ValueError if after=='drift' else (OSError if after=='reader-failure' else error_type)
        reason=('owned process identity after capture mismatch' if after=='drift' else
            ('after identity read unavailable' if after=='reader-failure' else 'capture connection lost'))
        with patch.object(api,'_decode',side_effect=AssertionError('failed capture was decoded')):
            try:
                api.gather_owned_observation(p,plan,transport=transport,owned=owned,
                    owned_argv=owned.effective_argv,invocation_token='synthetic-invocation-token',
                    identity_reader=reader,mode='synthetic-test',clock=lambda:NOW)
            except BaseException as exc: caught=exc
            else: self.fail('raised capture yielded a usable observation')
        self.assertIsInstance(caught,expected_type)
        self.assertEqual(str(caught),reason)
        self.assertEqual(len(reads),2)
        self.assertEqual(len(transport.calls),1)
        self.assertEqual([(q,pid) for q,pid,_ in reads],[(p,owned.pid),(p,owned.pid)])
        self.assertEqual(before,(plan,sources,payload,owned))
        if after=='stable': self.assertIs(caught,capture_error)
        else:
            self.assertIs(caught.__context__,capture_error)
            if after=='reader-failure': self.assertIs(caught,after_error)

    def test_raised_capture_start_drift_rechecks_identity_and_chains_failure(self):
        self.failed_capture(after='drift')

    def test_raised_capture_stable_identity_propagates_same_exception(self):
        for error_type in (OSError,KeyboardInterrupt):
            with self.subTest(error_type=error_type): self.failed_capture(error_type=error_type)

    def test_raised_capture_after_reader_failure_preserves_capture_exception(self):
        self.failed_capture(after='reader-failure')

    def test_capture_refused_before_observe_has_no_after_identity_read(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]; owned=identity(api,p)
        for refusal in ('unsupported','before-mismatch','before-reader-failure'):
            with self.subTest(refusal=refusal):
                reads=[]; transport=FakeTransport(api,{})
                def reader(*args):
                    reads.append(args)
                    if refusal=='before-reader-failure': raise OSError('before identity unavailable')
                    return replace(owned,start='recycled-before-capture')
                reason={'unsupported':'UNKNOWN/unsupported owned materialization observer',
                    'before-mismatch':'owned process identity before capture mismatch',
                    'before-reader-failure':'before identity unavailable'}[refusal]
                with self.assertRaisesRegex(OSError if refusal=='before-reader-failure' else ValueError,reason):
                    api.gather_owned_observation(p,plan,transport=None if refusal=='unsupported' else transport,
                        owned=owned,owned_argv=owned.effective_argv,invocation_token='synthetic-invocation-token',
                        identity_reader=reader,mode='synthetic-test',clock=lambda:NOW)
                self.assertEqual(len(reads),0 if refusal=='unsupported' else 1)
                self.assertEqual(transport.calls,[])

    def test_returned_failure_rechecks_once_before_transport_decode(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]; owned=identity(api,p)
        for drift in (False,True):
            with self.subTest(drift=drift):
                reads=[]; current=[owned]
                def reader(*args): reads.append(args); return current[0]
                transport=FakeTransport(api,{'parseable':'unusable'},exit_code=9,
                    callback=lambda:current.__setitem__(0,replace(owned,start='recycled') if drift else owned))
                reason='owned process identity after capture mismatch' if drift else 'observer transport exit 9'
                with patch.object(api,'_decode',wraps=api._decode) as decode:
                    with self.assertRaisesRegex(ValueError,'^'+reason+'$'):
                        api.gather_owned_observation(p,plan,transport=transport,owned=owned,
                            owned_argv=owned.effective_argv,invocation_token='synthetic-invocation-token',
                            identity_reader=reader,mode='synthetic-test',clock=lambda:NOW)
                    self.assertEqual(decode.call_count,0 if drift else 1)
                self.assertEqual((len(reads),len(transport.calls)),(2,1))

    def test_copy_producer_and_two_leg_materialization_continuity_are_actual(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        sources={q.participant_id:source_receipt(plan,q) for q in plan.participants}
        baseline=owned_payload(api,plan,p,sources)['boundaries'][0]
        changed=copy.deepcopy(baseline);changed['copy_provenance']['producer']='config-echo'
        with self.subTest(check='producer'),self.assertRaisesRegex(ValueError,'boundary copy provenance'):
            api._boundaries(plan,[(plan.participants[0],owned_payload(api,plan,plan.participants[0],sources)),
                (p,{**owned_payload(api,plan,p,sources),'boundaries':[changed]})])
        # Missing continuity facts must not be supplied by the expected contract.
        for c in baseline['copies']:
            c.pop('source_materialization_id',None);c.pop('target_materialization_id',None)
        with self.subTest(check='continuity'),self.assertRaisesRegex(ValueError,'actual boundary copy continuity'):
            api._copy_legs(plan,baseline,baseline['contract'],'synthetic-invocation-token')

    def test_strict_wire_duplicate_nonfinite_unknown_key_and_payload_bound(self):
        api=self.api(); plan=self.plans['one-gpu']; p=plan.participants[1]
        baseline=envelope(plan,p); encoded=canonical(baseline)
        values=[('duplicate observation key',encoded.replace(b'"schema":',b'"schema":"binding-preflight/1","schema":',1)),
            ('nonfinite observation number',encoded.replace(b'"advertised_type":"GPU"',b'"advertised_type":NaN',1)),
            ('oversized observation payload',b' '*(api.MAX_OBSERVATION_BYTES+1))]
        for reason,payload in values:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason):
                api.validate_preflight(p,plan,api.TransportReply(0,payload),mode='synthetic-test',clock=lambda:NOW)
        baseline['unknown']=True;seal(baseline)
        with self.assertRaisesRegex(ValueError,'preflight fields'): self.preflight(baseline)


    def copy_inventory(self):
        api=self.api(); plan=self.plans['one-gpu']
        sources={p.participant_id:source_receipt(plan,p) for p in plan.participants}
        payloads=[owned_payload(api,plan,p,sources) for p in plan.participants]
        return plan,sources,payloads

    def test_copy_materialization_id_cannot_change_physical_memory_across_chain(self):
        api=self.api(); plan,sources,payloads=self.copy_inventory()
        legs=payloads[1]['boundaries'][0]['copies']
        self.assertEqual(payloads[1]['boundaries'][0]['contract']['semantic_id'],'completed-layer-44/45')
        self.assertEqual([(r['source_host'],r['source_memory_id'],r['target_host'],r['target_memory_id'])
            for r in legs],[('B','B-ram','A','A-ram'),('A','A-ram','B','B-vram')])
        self.assertEqual(legs[0]['target_materialization_id'],legs[1]['source_materialization_id'])
        with patch('subprocess.run',side_effect=AssertionError('launch')),patch('socket.socket',side_effect=AssertionError('socket')):
            receipt=self.reconcile_inventory(plan,sources,payloads)
            self.assertEqual((receipt.tensor_count,receipt.state_count,receipt.buffer_count,
                receipt.auxiliary_count,receipt.boundary_count),(1224,111,1335,43,2))
            self.assertFalse(receipt.physical_qualified); self.assertFalse(receipt.execution_authorized)
            self.assertEqual(receipt.evidence_classes,(('measured','synthetic'),))
            detached=thaw(receipt.observed); detached['observations'].clear()
            self.assertEqual(len(thaw(receipt.observed)['observations']),2)
            original=copy.deepcopy(payloads)
            # Exactly the reproduced nonadjacent identity mutation plus its seal.
            legs[1]['target_materialization_id']=legs[0]['source_materialization_id']
            seal(payloads[1])
            expected=copy.deepcopy(original)
            expected[1]['boundaries'][0]['copies'][1]['target_materialization_id']=legs[0]['source_materialization_id']
            seal(expected[1]); self.assertEqual(expected,payloads)
            with patch.object(api,'MaterializationReceipt',side_effect=AssertionError('contradiction reached receipt construction')):
                with self.assertRaisesRegex(ValueError,'^actual boundary copy materialization physical identity/ownership mismatch$'):
                    self.reconcile_inventory(plan,sources,payloads)

    def test_copy_materialization_identity_consistent_global_reuse_is_accepted(self):
        for witness in ('copy','tensor','state'):
            with self.subTest(witness=witness):
                plan,sources,payloads=self.copy_inventory()
                if witness=='copy':
                    identity_id=payloads[0]['boundaries'][0]['copies'][0]['target_materialization_id']
                else:
                    identity_id=next(r['materialization_id'] for r in payloads[1][witness+'s']
                        if r['contract']['memory_id']=='B-ram')
                payloads[1]['boundaries'][0]['copies'][0]['source_materialization_id']=identity_id
                receipt=self.reconcile_inventory(plan,sources,payloads)
                self.assertEqual((receipt.tensor_count,receipt.state_count,receipt.buffer_count,
                    receipt.auxiliary_count,receipt.boundary_count),(1224,111,1335,43,2))
                self.assertFalse(receipt.physical_qualified); self.assertFalse(receipt.execution_authorized)

    def test_copy_materialization_identity_matches_global_observed_physical_witness(self):
        api=self.api()
        # The inventories already enforce global materialization ID uniqueness.
        # Reuse is legal; only a contradictory physical resource is refused.
        for witness in ('copy','tensor','state'):
            with self.subTest(witness=witness):
                plan,sources,payloads=self.copy_inventory()
                self.reconcile_inventory(plan,sources,payloads)
                if witness=='copy':
                    identity_id=payloads[0]['boundaries'][0]['copies'][0]['target_materialization_id']
                else:
                    identity_id=next(r['materialization_id'] for r in payloads[1][witness+'s']
                        if r['contract']['memory_id']=='B-ram')
                # This final endpoint is B VRAM, never the B RAM witness above.
                payloads[1]['boundaries'][0]['copies'][1]['target_materialization_id']=identity_id
                with patch.object(api,'MaterializationReceipt',side_effect=AssertionError('conflict reached receipt construction')):
                    with self.assertRaisesRegex(ValueError,'^actual boundary copy materialization physical identity/ownership mismatch$'):
                        self.reconcile_inventory(plan,sources,payloads)

    def test_copy_identity_existing_continuity_and_memory_guards_remain_first(self):
        cases=(('actual boundary copy continuity aliases different physical endpoints',
                lambda c:c[0].update(target_materialization_id=c[0]['source_materialization_id'])),
            ('actual boundary copy continuity between staged legs mismatch',
                lambda c:c[1].update(source_materialization_id=c[0]['source_materialization_id'])),
            ('actual boundary copy continuity between staged legs mismatch',
                lambda c:c[1].update(source_memory_id='B-ram')),
            ('actual boundary copy memory ownership mismatch',
                lambda c:c[1].update(target_memory_id='B-ram')))
        api=self.api()
        for reason,change in cases:
            with self.subTest(reason=reason):
                plan,sources,payloads=self.copy_inventory(); change(payloads[1]['boundaries'][0]['copies'])
                with patch.object(api,'MaterializationReceipt',side_effect=AssertionError('invalid copy reached receipt')):
                    with self.assertRaisesRegex(ValueError,'^'+reason+'$'):
                        self.reconcile_inventory(plan,sources,payloads)

    def test_copy_identity_strict_text_types_are_preserved(self):
        api=self.api()
        for value in (None,True,1,1.0,[],{},''):
            with self.subTest(value=value):
                plan,sources,payloads=self.copy_inventory()
                payloads[1]['boundaries'][0]['copies'][1]['target_materialization_id']=value
                with patch.object(api,'MaterializationReceipt',side_effect=AssertionError('invalid identity reached receipt')):
                    with self.assertRaisesRegex(ValueError,'actual boundary copy continuity'):
                        self.reconcile_inventory(plan,sources,payloads)


if __name__=='__main__': unittest.main()
