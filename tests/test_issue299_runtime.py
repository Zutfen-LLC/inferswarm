"""Production runner, recording boundaries; all evidence explicitly SYNTHETIC."""
import copy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch

from inferswarm.operator import bindings, source
from inferswarm.operator.config import parse_config
from inferswarm.operator.plan import build_plan, revalidate_admission
from inferswarm.operator.qwen_q8 import q8_candidates, bound_capability
from inferswarm.operator.lifecycle import LeaseManager
from inferswarm.operator.profiles import canonical, freeze, sha256, thaw
from inferswarm.operator.runtime import OperatorRunner, SSHSourceTransport, observed_placement
from inferswarm.operator.strategy import llama_cpp_spec
from tests.issue299_fixture import NOW, reseal_profiles, profile_digest
from tests.test_issue299_q8_plan import fully_bounded_mapping, metadata
from tests.test_issue299_bindings import (plan_fixture, envelope, source_receipt,
    owned_payload, seal, wire)
from tests import test_issue299_source as source_tests


def synthetic_mapping(cache=False):
    raw = fully_bounded_mapping()
    # These cache identities are fabricated test inputs, NOT public weight proof.
    if cache:
        raw['strategy_options']['rpc_cache'] = 'enabled'
        remote = raw['participants'][1]; identity = raw['model']
        remote['cache_ranges'] = [dict(state_id=r['state_id'], member=r['member'], offset=r['offset'],
            length=r['length'], sha256=sha256({'SYNTHETIC':r['state_id']}), cache_key=format(i+1,'016x'),
            source_id=identity['source_id'], revision=identity['revision'], representation=identity['representation'],
            unit_id=row['unit_id']) for row in raw['placement'] if row['binding_id']!='binding-A-cpu'
            for i,r in enumerate(row['state_ranges'])]
        # Keys need uniqueness across BOTH remote bindings.
        for i,r in enumerate(remote['cache_ranges']): r['cache_key']=format(i+1,'016x')
    from tests.test_issue299_bindings import CAPS, QUALIFICATION
    snapshot = raw['profiles']['snapshot']
    for r in snapshot['runtime_capabilities']: r['capabilities'].extend((*CAPS,QUALIFICATION))
    reseal_profiles(snapshot); raw['profiles']['digest']=profile_digest(snapshot)
    if cache:
        candidate, = q8_candidates(parse_config(raw,now=NOW,profile_mode='replay'),metadata())
        memories = {m['memory_id']:m for m in snapshot['memory_resources']}
        for charge in candidate.charges:
            if charge.bytes is not None: continue
            runtime = next(r for r in snapshot['runtime_capabilities'] if r['host_id']==memories[charge.memory_id]['host_id'])
            amount = 2**21  # Explicitly synthetic, same convention as prior fixtures.
            raw['strategy_options']['bounds'].append(dict(allocation_id=charge.allocation_id, bytes=amount, evidence_id=runtime['evidence_id']))
            runtime['capabilities'].append(bound_capability(charge,amount))
            evidence = next(e for e in snapshot['evidence'] if e['evidence_id']==runtime['evidence_id'])
            evidence['dependencies']['memory:'+charge.memory_id+':physical_id']=memories[charge.memory_id]['physical_id']
        reseal_profiles(snapshot); raw['profiles']['digest']=profile_digest(snapshot)
    return raw


class RecordingLifecycle:
    """Only transport is replaced; actual LeaseManager owns cleanup decisions."""
    def __init__(self, events):
        self.events = events
        self.active = {}; self.rows = {}; self.argv = {}; self.dead = set()
        self.foreign = {'untouched': 'foreign-pid-and-token'}
        self.fail = None; self.lost_reply = False; self.listen_after = 0; self.checks = 0
        self.loss = None; self.stop_failure = False

    def call(self, address, payload):
        action = payload['action']; name = payload.get('name')
        self.events.append((action, address, name))
        if self.fail == (action, address): raise ValueError('recorded '+action+' failure')
        if action == 'admit':
            if address in self.active: raise ValueError('lease already exists; foreign untouched')
            self.active[address] = payload['token']; self.rows[address] = {}
            return {'lease': 'admitted'}
        if self.active.get(address) != payload['token']: raise ValueError('lease token mismatch')
        if action == 'port': return {'port': 'available'}
        if action == 'spawn':
            row = dict(pid=202 if name == 'rpc' else 101, start=987654321 if name == 'rpc' else 'opaque-A', token=payload['token'])
            self.rows[address][name] = row; self.argv[address] = tuple(payload['argv'])
            if self.lost_reply: raise OSError('reply lost after spawn')
            return dict(row)
        if action == 'alive': return {'alive': (address, name) not in self.dead and self.loss != name}
        if action == 'listening':
            self.checks += 1
            return {'listening': self.checks > self.listen_after}
        if action == 'stop':
            if self.stop_failure: raise OSError('recorded owned stop failure')
            assert self.rows[address][name] == dict(pid=payload['pid'], start=payload['start'], token=payload['token'])
            self.dead.add((address, name)); return {'signal': 'TERM'}
        if action == 'release':
            if any((address, n) not in self.dead for n in self.rows[address]):
                raise ValueError('owned process still alive or record mismatch')
            del self.active[address]; return {'lease': 'released'}
        raise AssertionError('unexpected lifecycle action '+action)


class Harness:
    def __init__(self, plan, token='synthetic-invocation-1'):
        self.plan = plan; self.events = []; self.transport = RecordingLifecycle(self.events)
        self.manager = LeaseManager(self.transport, token, stop_timeout=0)
        self.sources = {p.participant_id: source_receipt(plan, p) for p in plan.participants}
        self.preflight_mutate = None; self.capture_mutate = None; self.identity_mutate = None
        self.capture_error = None; self.observe_status = 0; self.preflight_status = 0
        self.source_error = None; self.source_calls = []; self.reads = []
        self.stopped = False; self.tunnel_error = None; self.tunnel_status = None
        self.factory_error = None; self.request_error = None; self.posts = 0; self.health = 'ok'
        self.clock = lambda: NOW

    def verify(self, p, plan, fnv_binary=None):
        self.events.append(('source', p.role)); self.source_calls.append((p.participant_id, fnv_binary))
        if self.source_error: raise self.source_error
        return copy.deepcopy(self.sources[p.participant_id])

    def preflight(self, p, plan):
        self.events.append(('preflight', p.role))
        data = envelope(plan, p)
        if self.preflight_mutate: self.preflight_mutate(data)
        return bindings.TransportReply(self.preflight_status, canonical(seal(data)))

    def identity_reader(self, p, pid):
        self.reads.append(p.participant_id)
        row = self.transport.rows[p.execution_address]['client' if p.role == 'client' else 'rpc']
        out = bindings.ProcessIdentity(p.participant_id, p.host_id, p.boot_epoch, p.topology_epoch,
            pid, str(row['start']), p.runtime_executable, p.runtime_sha256,
            self.transport.argv[p.execution_address], freeze(envelope(self.plan, p)['visibility']), p.rpc_endpoint)
        return self.identity_mutate(out) if self.identity_mutate else out

    def observe(self, p, plan, **kwargs):
        self.events.append(('observe', p.role))
        if self.capture_error: raise self.capture_error
        data = owned_payload(bindings, plan, p, self.sources)
        # Adapt only synthetic wire identity to actual recording spawn/token/argv.
        row = self.transport.rows[p.execution_address]['client' if p.role == 'client' else 'rpc']
        data['process'].update(pid=row['pid'], start=str(row['start']), effective_argv=list(kwargs['owned_argv']))
        data['invocation_token'] = kwargs['invocation_token']
        for state in data['states']: state['authority_epoch'] = kwargs['invocation_token']
        for boundary in data['boundaries']:
            for leg in boundary['copies']: leg['invocation_token'] = kwargs['invocation_token']
        if self.capture_mutate: self.capture_mutate(data)
        return bindings.TransportReply(self.observe_status, canonical(seal(data)))

    def tunnel(self, *args):
        self.events.append(('tunnel',))
        if self.factory_error: raise self.factory_error
        return self, 18080

    def poll(self): return self.tunnel_status
    def terminate(self):
        self.stopped = True
        if self.tunnel_error: raise self.tunnel_error
    def wait(self, timeout=None): return 0
    def get(self, url, timeout):
        self.events.append(('health',)); return {'status': self.health}
    def post(self, url, data, timeout):
        self.posts += 1; self.events.append(('post',))
        if self.request_error: raise self.request_error
        return {'id': 'synthetic-reply', 'choices': [{'message': {'content': 'fixture'}, 'finish_reason': 'stop'}], 'usage': {'completion_tokens': 1}}

    def runner(self, **overrides):
        kwargs = dict(binding_transport=self, identity_reader=self.identity_reader,
            observation_mode='synthetic-test', clock=self.clock)
        kwargs.update(overrides)
        return OperatorRunner(self, self.manager, self, self.tunnel, pause=lambda _: None, **kwargs)


class Q8Runner(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.plans = {s: plan_fixture(s) for s in ('one-gpu', 'cpu-only')}

    def harness(self, selection='one-gpu'): return Harness(self.plans[selection])

    def assert_released(self, h):
        self.assertFalse(h.manager.leases)
        self.assertFalse(h.transport.active)
        self.assertEqual(h.transport.foreign, {'untouched': 'foreign-pid-and-token'})

    def test_real_runner_both_variants_exact_flags_complete_inventory_one_post(self):
        for selection in self.plans:
            with self.subTest(selection=selection):
                h = self.harness(selection); before = copy.deepcopy(h.plan)
                h.transport.listen_after = 2
                result = h.runner().run(h.plan)
                spec = llama_cpp_spec(h.plan)
                client, remote = sorted(h.plan.participants, key=lambda p: p.role)
                expected_remote = (remote.runtime_executable, *spec.rpc_args, '--host', remote.rpc_endpoint.rpartition(':')[0], '--port', str(remote.port))
                self.assertEqual(h.transport.argv[remote.execution_address], expected_remote)
                self.assertEqual(h.transport.argv[client.execution_address], (spec.executable, *spec.args, '--host', '127.0.0.1', '--port', str(client.port)))
                self.assertNotIn('-cmoe', h.transport.argv[client.execution_address])
                self.assertEqual(h.transport.argv[client.execution_address].count('--model'), 1)
                self.assertEqual(len(h.source_calls), 2); self.assertTrue(all(path is None for _, path in h.source_calls))
                self.assertEqual(sum(e[0]=='admit' for e in h.events), 2)
                self.assertEqual(sum(e[0]=='spawn' and e[2]=='rpc' for e in h.events), 1)
                client_spawn = next(i for i,e in enumerate(h.events) if e[0]=='spawn' and e[2]=='client')
                self.assertEqual(sum(e[0]=='listening' for e in h.events[:client_spawn]), 3)
                self.assertEqual(h.posts, 1); self.assertTrue(h.stopped); self.assert_released(h)
                material = result['observed_materialization']
                self.assertEqual((material['tensor_count'], material['state_count']), (1224, 111))
                self.assertEqual(set(result['verified_backing']), set(h.sources))
                self.assertEqual(len(result['observed_bindings']), 2)
                self.assertEqual(len(result['binding_preflight']), 2)
                self.assertEqual(result['observation_mode'], 'synthetic-test')
                for flag in ('execution_authorized','physical_qualified','execution_ready'): self.assertIs(result[flag], False)
                self.assertEqual(result['admission']['status'], 'ADMITTED')
                self.assertEqual(h.plan, before)
                material['observed']['source_receipts'].clear()
                self.assertEqual(len(h.sources), 2)

    def test_enabled_cache_repeat_plan_fresh_tokens_directories_and_exact_cache_flag(self):
        plan = build_plan(parse_config(synthetic_mapping(cache=True),now=NOW,profile_mode='replay'),now=NOW)
        self.assertEqual(plan.admission.status,'ADMITTED',plan.admission.deficits)
        helpers=[]; directories=[]
        for token in ('synthetic-fresh-one','synthetic-fresh-two'):
            h = Harness(plan,token); result = h.runner().run(plan)
            self.assertEqual(result['plan_digest'],plan.digest); self.assertEqual(h.posts,1)
            remote = next(p for p in plan.participants if p.role=='remote')
            self.assertEqual(h.transport.argv[remote.execution_address][-1],'--cache')
            self.assertEqual(sum(e[0]=='spawn' and e[2]=='rpc' for e in h.events),1)
            helpers.append(next(path for pid,path in h.source_calls if pid==remote.participant_id))
            self.assertTrue(all(path is None for pid,path in h.source_calls if pid!=remote.participant_id))
            directories.extend(str(Path(p.lifecycle_dir)/token) for p in plan.participants)
            self.assert_released(h)
        self.assertEqual(len(set(helpers)),2); self.assertEqual(len(set(directories)),4)
        self.assertTrue(all(Path(path).name=='fnv-cache' for path in helpers))

    def test_blocked_unknown_budget_and_coherent_options_mutation_no_effects(self):
        raw = synthetic_mapping(); raw['strategy_options']['bounds'].pop()
        plan = build_plan(parse_config(raw,now=NOW,profile_mode='replay'),now=NOW)
        self.assertEqual(plan.admission.status,'BLOCKED')
        h = Harness(plan)
        with self.assertRaisesRegex(ValueError,'UNKNOWN allocation'): h.runner().run(plan)
        self.assertFalse(h.events)
        plan=self.plans['one-gpu']; options=thaw(plan.strategy_options)
        options['startup_timeout_seconds'] += 1
        changed=replace(plan,strategy_options=freeze(options),config=replace(plan.config,strategy_options=freeze(options)))
        h=Harness(changed)
        with self.assertRaisesRegex(ValueError,'strategy options integrity'): h.runner().run(changed)
        self.assertFalse(h.events)

    def test_fresh_admission_again_after_capture_before_post(self):
        h=self.harness(); original=bindings.reconcile_materialization
        def reconcile(*args,**kwargs):
            receipt=original(*args,**kwargs); h.clock=lambda:NOW+timedelta(days=1)
            return receipt
        runner=h.runner()
        # A mutable clock callable is a test seam, never a live API.
        runner.clock=lambda:h.clock()
        with patch.object(bindings,'reconcile_materialization',side_effect=reconcile):
            with self.assertRaisesRegex(ValueError,'expired|stale'): runner.run(h.plan)
        self.assertEqual(h.posts,0); self.assert_released(h)

    def test_live_revalidation_calls_without_retained_clock_and_cannot_replay(self):
        h=self.harness()
        with patch('inferswarm.operator.runtime.revalidate_admission',wraps=revalidate_admission) as checked:
            with self.assertRaisesRegex(ValueError,'non-live|synthetic|expired|stale'):
                h.runner(observation_mode='live',clock=None).run(h.plan)
        checked.assert_called_once_with(h.plan); self.assertFalse(h.events)

    def test_synthetic_scope_clock_and_missing_reader_do_not_acquire(self):
        cases=[({'clock':None},'synthetic test clock'),({'clock':lambda:NOW.replace(tzinfo=None)},'timezone-aware UTC'),
            ({'observation_mode':'replay'},'unsupported observation mode'),({'identity_reader':None},'independent identity reader')]
        for kwargs,reason in cases:
            h=self.harness()
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason):h.runner(**kwargs).run(h.plan)
            self.assertFalse(h.events)
        h=self.harness(); snapshot=h.plan.profiles.snapshot
        h.plan=replace(h.plan,profiles=replace(h.plan.profiles,snapshot=replace(snapshot,
            evidence=tuple(replace(e,source_scope='live') for e in snapshot.evidence))))
        with self.assertRaisesRegex(ValueError,'synthetic test profile scope'):h.runner().run(h.plan)
        self.assertFalse(h.events)

    def test_late_ple_output_and_expert_omissions_and_owned_failed_status(self):
        for name in ('per_layer_token_embd.weight','blk.1.ple_value.weight','blk.45.ffn_up_exps.weight','output_hc_up.weight'):
            h=self.harness()
            h.capture_mutate=lambda x:x.update(tensors=[r for r in x['tensors'] if r['contract']['state_id']!=name])
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'tensor coverage'):h.runner().run(h.plan)
            self.assertEqual(h.posts,0);self.assert_released(h)
        h=self.harness();h.observe_status=9
        with self.assertRaisesRegex(ValueError,'observer transport exit 9'):h.runner().run(h.plan)
        self.assertEqual(len(h.reads),3);self.assertEqual(h.posts,0);self.assert_released(h)

    def test_owned_identity_drift_before_capture_and_raise_with_after_drift_context(self):
        h=self.harness()
        h.identity_mutate=lambda i:replace(i,start='recycled') if len(h.reads)==2 else i
        with self.assertRaisesRegex(ValueError,'identity before capture'):h.runner().run(h.plan)
        self.assertFalse(any(e[0]=='observe' for e in h.events));self.assert_released(h)
        h=self.harness();error=OSError('original capture error')
        def observe(*args,**kwargs):
            h.identity_mutate=lambda i:replace(i,start='recycled')
            raise error
        h.observe=observe
        with self.assertRaisesRegex(ValueError,'identity after capture') as caught:h.runner().run(h.plan)
        self.assertIs(caught.exception.__context__,error);self.assertEqual(len(h.reads),3);self.assert_released(h)

    def test_health_timeout_before_capture_and_post(self):
        h=self.harness();h.health='loading';ticks=iter([0,0,0,10000])
        with patch('inferswarm.operator.runtime.time.monotonic',side_effect=lambda:next(ticks,10000)):
            with self.assertRaisesRegex(TimeoutError,'client startup health timeout'):h.runner().run(h.plan)
        self.assertFalse(h.reads);self.assertEqual(h.posts,0);self.assertTrue(h.stopped);self.assert_released(h)

    def test_tunnel_or_participant_loss_after_response_is_not_success(self):
        for kind in ('tunnel','participant'):
            h=self.harness();original=h.post
            def post(*args,**kwargs):
                result=original(*args,**kwargs)
                if kind=='tunnel':h.tunnel_status=1
                else:h.transport.loss='rpc'
                return result
            h.post=post
            with self.subTest(kind=kind),self.assertRaisesRegex(RuntimeError,'SSH tunnel exited during request|remote participant lost'):h.runner().run(h.plan)
            self.assertEqual(h.posts,1);self.assert_released(h)

    def test_tunnel_cleanup_or_incomplete_owned_cleanup_after_success_not_success(self):
        for kind in ('tunnel','lease'):
            h=self.harness()
            if kind=='tunnel':h.tunnel_error=OSError('termination failed')
            else:h.transport.stop_failure=True
            with self.subTest(kind=kind),self.assertRaisesRegex(RuntimeError,'cleanup'):h.runner().run(h.plan)
            self.assertEqual(h.posts,1)
            if kind=='tunnel':self.assert_released(h)
            else:self.assertTrue(h.manager.leases)

    def test_default_absent_observer_or_reader_before_effects(self):
        for kwargs, reason in [({}, 'UNKNOWN/unsupported'), ({'binding_transport': object()}, 'independent identity reader')]:
            h = self.harness()
            runner = OperatorRunner(h, h.manager, h, h.tunnel, **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, reason): runner.run(h.plan)
            self.assertEqual(h.events, [])

    def test_live_clock_injection_and_replay_scope_before_effects(self):
        for kwargs, reason in [({'observation_mode':'live','clock':lambda:NOW}, 'live clock'),
                ({'observation_mode':'live','clock':None}, 'non-live|synthetic|replay|expired|stale')]:
            h = self.harness()
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason): h.runner(**kwargs).run(h.plan)
            self.assertFalse(h.events)

    def test_fresh_admission_rejects_digest_options_and_expiration_before_effects(self):
        mutations = [replace(self.plans['one-gpu'], digest='0'*64),
            replace(self.plans['one-gpu'], strategy_options=freeze({'other':'options'}))]
        for plan in mutations:
            h = Harness(plan)
            with self.assertRaisesRegex(ValueError, 'integrity'): h.runner().run(plan)
            self.assertFalse(h.events)
        h = self.harness(); h.clock = lambda: NOW+timedelta(days=1)
        with self.assertRaisesRegex(ValueError, 'expired|stale'): h.runner().run(h.plan)
        self.assertFalse(h.events)

    def test_preflight_specific_mutations_zero_lifecycle_effects(self):
        cases = [('ordered binding translation', lambda x:x['bindings'].reverse()),
            ('physical binding identity', lambda x:x['bindings'][-1]['compute'].update(physical_id='other-UUID')),
            ('physical memory ownership', lambda x:x['bindings'][0]['memory'].update(kind='vram')),
            ('configured visibility', lambda x:x['visibility']['native'].reverse()),
            ('host epoch', lambda x:x['host'].update(boot_epoch='other')),
            ('runtime identity', lambda x:x['bindings'][0]['runtime'].update(build_id='other')),
            ('observer dependency', lambda x:x['evidence']['dependencies'].update({'other':'probe'})),
            ('expired observer', lambda x:x['evidence'].update(expires_at='2026-01-02T12:00:00Z'))]
        for reason, mutate in cases:
            with self.subTest(reason=reason):
                h = self.harness()
                h.preflight_mutate = lambda x: mutate(x) if x['participant_id']==h.plan.participants[1].participant_id else None
                with self.assertRaisesRegex(ValueError, reason): h.runner().run(h.plan)
                self.assertTrue(all(e[0]=='preflight' for e in h.events)); self.assertEqual(h.posts, 0)
        h = self.harness(); h.preflight_status = 7
        with self.assertRaisesRegex(ValueError, 'observer transport exit 7'): h.runner().run(h.plan)
        self.assertTrue(all(e[0]=='preflight' for e in h.events))

    def test_materialization_tensor_state_route_and_source_join_refuse_before_post(self):
        cases = [('tensor coverage', lambda x:x['tensors'].pop()),
            ('state coverage', lambda x:x['states'].pop()),
            ('state authority', lambda x:x['states'][0].update(authority_owner='wrong')),
            ('boundary route', lambda x:x['boundaries'][0].update(route='server-local')),
            ('source receipt identity digest', lambda x:x.update(source_receipt_digest='0'*64))]
        for reason, mutate in cases:
            with self.subTest(reason=reason):
                h = self.harness()
                h.capture_mutate = lambda x: mutate(x) if x['participant_id']==h.plan.participants[1].participant_id else None
                with self.assertRaisesRegex(ValueError, reason): h.runner().run(h.plan)
                self.assertEqual(h.posts, 0); self.assertTrue(h.stopped); self.assert_released(h)

    def test_layer_logs_cannot_issue_q8_receipt(self):
        with self.assertRaisesRegex(ValueError, 'complete typed observations|legacy-only'):
            observed_placement('load_tensors: layer 0 assigned to device CPU, is_swa = 0', self.plans['one-gpu'])

    def test_identity_actual_spawn_start_argv_visibility_and_frozen_fields(self):
        for field, value in [('start','recycled'),('effective_argv',('hidden-override',)),
                ('visibility',freeze({'native':[], 'visible':[], 'environment':{}})),
                ('host_id','other-host'),('binary_sha256','0'*64),('endpoint','other:1')]:
            with self.subTest(field=field):
                h = self.harness(); h.identity_mutate = lambda i: replace(i, **{field:value})
                with self.assertRaisesRegex(ValueError, 'owned process|visibility'): h.runner().run(h.plan)
                self.assertEqual(h.posts, 0); self.assert_released(h)

    def test_capture_drift_and_raised_capture_still_read_after(self):
        h = self.harness(); h.capture_mutate = lambda _: setattr(h, 'identity_mutate', lambda i:replace(i,start='recycled'))
        with self.assertRaisesRegex(ValueError, 'identity after capture'): h.runner().run(h.plan)
        self.assertEqual(len(h.reads), 3); self.assertEqual(h.posts, 0); self.assert_released(h)
        h = self.harness(); error = OSError('capture failed'); h.capture_error = error
        with self.assertRaises(OSError) as caught: h.runner().run(h.plan)
        self.assertIs(caught.exception, error); self.assertEqual(len(h.reads), 3); self.assert_released(h)

    def test_source_failure_prevents_spawn_and_post(self):
        h = self.harness(); h.source_error = ValueError('source range identity mismatch')
        with self.assertRaisesRegex(ValueError, 'source range identity'): h.runner().run(h.plan)
        self.assertFalse(any(e[0]=='spawn' for e in h.events)); self.assertEqual(h.posts,0); self.assert_released(h)

    def test_loss_start_request_and_tunnel_failures_owned_cleanup(self):
        for kind, reason in [('rpc','remote participant lost'),('client','client participant lost'),
                ('spawn','recorded spawn failure'),('request','request failed'),
                ('factory','tunnel opening failed'),('tunnel','SSH tunnel exited')]:
            with self.subTest(kind=kind):
                h = self.harness()
                if kind in ('rpc','client'): h.transport.loss = kind
                if kind == 'spawn': h.transport.fail = ('spawn',h.plan.participants[1].execution_address)
                if kind == 'request': h.request_error = ValueError(reason)
                if kind == 'factory': h.factory_error = OSError(reason)
                if kind == 'tunnel': h.tunnel_status = 1
                with self.assertRaisesRegex((RuntimeError,ValueError,OSError), reason): h.runner().run(h.plan)
                self.assert_released(h)
                self.assertEqual(h.posts, 1 if kind=='request' else 0)

    def test_listener_foreign_timeout_no_client_spawn(self):
        h = self.harness(); h.transport.listen_after = 100
        ticks = iter([0,10000])
        with patch('inferswarm.operator.runtime.time.monotonic',side_effect=lambda:next(ticks,10000)):
            with self.assertRaisesRegex(TimeoutError, 'RPC owned listener startup timeout'): h.runner().run(h.plan)
        self.assertFalse(any(e[0]=='spawn' and e[2]=='client' for e in h.events)); self.assert_released(h)

    def test_partial_acquire_foreign_preserved_and_lost_spawn_reply_retained(self):
        h = self.harness(); client = h.plan.participants[0]
        h.transport.active[client.execution_address] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'lease already exists'): h.runner().run(h.plan)
        self.assertEqual(h.transport.active,{client.execution_address:'foreign'}); self.assertFalse(h.manager.leases)
        h = self.harness(); h.transport.lost_reply = True; runner = h.runner()
        with self.assertRaisesRegex(OSError, 'reply lost after spawn') as caught: runner.run(h.plan)
        self.assertIn('incomplete owned cleanup',str(caught.exception.__cause__))
        remote = next(p for p in h.plan.participants if p.role=='remote')
        self.assertEqual(runner.last_cleanup[remote.execution_address]['lease'],'retained-incomplete')
        self.assertIn('owned process still alive',runner.last_cleanup[remote.execution_address]['error'])
        self.assertTrue(h.transport.active); self.assertEqual(h.posts,0)
        self.assertEqual(h.transport.foreign,{'untouched':'foreign-pid-and-token'})

    def test_material_error_preserved_with_tunnel_or_lease_cleanup_context(self):
        for failure in ('tunnel','lease'):
            h = self.harness(); h.capture_error = ValueError('material source identity error')
            if failure=='tunnel': h.tunnel_error = OSError('termination failed')
            else: h.transport.stop_failure = True
            runner = h.runner()
            with self.assertRaisesRegex(ValueError,'material source identity error') as caught: runner.run(h.plan)
            self.assertIn('cleanup',str(caught.exception.__cause__))
            self.assertEqual(h.posts,0)
            if failure=='tunnel': self.assert_released(h)
            else: self.assertTrue(h.manager.leases)


class Q8SSHSource(unittest.TestCase):
    def fixture(self):
        fixture = source_tests.Q8Source(methodName='test_full_source_and_ranges_on_both_roles_without_cache_effects')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        return fixture

    def test_authentic_frozen_q8_serialization_and_nonzero_success_reply(self):
        plan = plan_fixture('one-gpu'); p = plan.participants[1]
        expected = source.q8_source_payload(plan)
        calls = []
        def record(argv, **kwargs):
            calls.append((argv,kwargs)); return subprocess.CompletedProcess(argv,0,json.dumps(source_receipt(plan,p)),'')
        with patch('inferswarm.operator.runtime.subprocess.run',side_effect=record):
            SSHSourceTransport().verify(p,plan)
        data = json.loads(calls[0][1]['input'])
        self.assertEqual(data['schema'],'q8-source-verification/1'); self.assertEqual(data['plan_payload'],expected)
        self.assertEqual(calls[0][1]['timeout'],1800); self.assertIsInstance(data['plan_payload']['metadata']['provenance'],dict)
        with patch('inferswarm.operator.runtime.subprocess.run',return_value=subprocess.CompletedProcess([],9,json.dumps(source_receipt(plan,p)),'transport failed')):
            with self.assertRaisesRegex(RuntimeError,'source verification failed.*transport failed|source transport exit 9'):
                SSHSourceTransport().verify(p,plan)

    def test_unchanged_real_source_program_both_roles_and_error_reason_offline(self):
        f = self.fixture(); plan = plan_fixture('one-gpu'); real_run = subprocess.run
        def offline(argv, **kwargs):
            command = shlex.split(argv[-1]); self.assertEqual(command[:2],['python3','-c'])
            self.assertEqual(command[2],Path(source.__file__).read_text())
            return real_run([sys.executable,'-c',command[2]],**kwargs)
        with patch.object(source,'q8_source_payload',return_value=f.payload), patch('inferswarm.operator.runtime.subprocess.run',side_effect=offline):
            for p in plan.participants:
                selected = f.payload['participants'][0 if p.role=='client' else 1]
                # Actual transport picks selected participant from the versioned source projection.
                receipt = SSHSourceTransport().verify(replace(p,participant_id=selected['participant_id']),plan)
                self.assertEqual(receipt['status'],'VERIFIED-not-consumed'); self.assertFalse(receipt['cache_consumed'])
            f.runtime.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'runtime executable SHA-256 mismatch'):
                SSHSourceTransport().verify(replace(plan.participants[1],participant_id='B'),plan)

    def test_disabled_cache_and_enabled_client_never_provision_helper(self):
        f=self.fixture(); plan=plan_fixture('one-gpu'); real_run=subprocess.run;calls=[]
        def offline(argv,**kwargs):
            command=shlex.split(argv[-1]);calls.append((command,json.loads(kwargs['input'])))
            self.assertEqual(command[2],Path(source.__file__).read_text())
            return real_run([sys.executable,'-c',command[2]],**kwargs)
        with patch.object(source,'q8_source_payload',return_value=f.payload),patch('inferswarm.operator.runtime.subprocess.run',side_effect=offline):
            SSHSourceTransport().verify(replace(plan.participants[1],participant_id='B'),plan,'/foreign/fnv-cache')
            f.cached()
            SSHSourceTransport().verify(replace(plan.participants[0],participant_id='A'),plan,'/foreign/fnv-cache')
        self.assertEqual(len(calls),2);self.assertTrue(all(data['fnv_binary'] is None for _,data in calls))

    def test_helper_setup_and_zero_exit_source_errors_surface_reason(self):
        f=self.fixture();f.cached();plan=plan_fixture('one-gpu')
        p=replace(plan.participants[1],participant_id='B',lifecycle_dir=str(f.root/'lease'))
        helper=str(f.root/'lease'/'token'/'fnv-cache')
        with patch.object(source,'q8_source_payload',return_value=f.payload),patch('inferswarm.operator.runtime.subprocess.run',return_value=subprocess.CompletedProcess([],4,'','compile unavailable')) as call:
            with self.assertRaisesRegex(RuntimeError,'helper setup failed.*compile unavailable'):SSHSourceTransport().verify(p,plan,helper)
        self.assertEqual(call.call_count,1)
        plan=plan_fixture('one-gpu')
        with patch('inferswarm.operator.runtime.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps({'schema':'q8-source-error/1','status':'ERROR','reason':'range identity failed'}),'')):
            with self.assertRaisesRegex(RuntimeError,'range identity failed'):SSHSourceTransport().verify(plan.participants[1],plan)

    def test_legacy_source_shape_and_nonzero_status_remain_unchanged(self):
        from tests.test_issue268_operator_plan import sample
        plan=build_plan(parse_config(sample()));part=plan.participants[1];calls=[]
        def record(argv,**kwargs):
            calls.append(kwargs);return subprocess.CompletedProcess(argv,0,'{"role":"remote"}','')
        with patch('inferswarm.operator.runtime.subprocess.run',side_effect=record):
            self.assertEqual(SSHSourceTransport().verify(part,plan,'/legacy/helper'),{'role':'remote'})
        payload=json.loads(calls[0]['input'])
        self.assertEqual(set(payload),{'participant','model','placement','backend','fnv_binary'})
        self.assertEqual(payload['fnv_binary'],'/legacy/helper');self.assertEqual(calls[0]['timeout'],1800)
        with patch('inferswarm.operator.runtime.subprocess.run',return_value=subprocess.CompletedProcess([],1,'{"role":"remote"}','legacy transport failed')):
            with self.assertRaisesRegex(RuntimeError,'source verification failed.*legacy transport failed'):SSHSourceTransport().verify(part,plan)

    def test_enabled_helper_invocation_owned_only_and_standalone_unchanged(self):
        f = self.fixture(); f.cached(); plan = plan_fixture('one-gpu')
        p = replace(plan.participants[1], participant_id='B', lifecycle_dir=str(f.root/'lease'))
        real_run = subprocess.run; calls = []; helpers = []
        def offline(argv, **kwargs):
            calls.append((argv,kwargs)); command = shlex.split(argv[-1])
            return real_run([sys.executable,'-c',command[2]],**kwargs)
        with patch.object(source,'q8_source_payload',return_value=f.payload), patch('inferswarm.operator.runtime.subprocess.run',side_effect=offline):
            for token in ('synthetic-token-one','synthetic-token-two'):
                helper = f.root/'lease'/token/'fnv-cache'; helper.parent.mkdir(parents=True)
                receipt = SSHSourceTransport().verify(p,plan,str(helper))
                self.assertTrue(helper.is_file()); self.assertEqual(receipt['cache_ranges'],4)
                helpers.append(helper)
                self.assertEqual(shlex.split(calls[-1][0][-1])[2],Path(source.__file__).read_text())
        self.assertEqual(len(set(helpers)),2); self.assertTrue(all(helper.is_file() for helper in helpers))
        self.assertEqual(len(calls),4)
        with patch.object(source,'q8_source_payload',return_value=f.payload), patch('inferswarm.operator.runtime.subprocess.run',side_effect=AssertionError('no effects')):
            with self.assertRaisesRegex(ValueError,'invocation-owned'): SSHSourceTransport().verify(p,plan,str(f.root/'cache/fnv-cache'))


if __name__ == '__main__': unittest.main()
