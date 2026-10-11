"""RED regressions for maintainer review 5482179642 P1-B/P1-C/P1-D on PR #305.

P1-B: static admission must reconcile the full calculated inventory (1,224
weights, 109 persistent-state expectations, two logical composites,
extents/allocations) against OBSERVED evidence, never calculated echoes;
missing observed evidence is a named fail-closed refusal identifying the
smallest missing observer capability.
P1-C: host/boot/listener/visibility identity must be independently observed
and joined against the frozen plan, never constructed from configuration.
P1-D: dynamic acceptance requires a proven request-identity join and
route-correct domain-boundary transfer evidence (B CPU -> A staging ->
B CUDA for one-gpu; a separate explicit CPU-only contract). Incidental CPU
fixture activity never satisfies the CUDA-route predicate.

All evidence is explicitly SYNTHETIC except the retained #301 captures.
"""
import hashlib
import json
import unittest
from pathlib import Path

from inferswarm.operator import phased_observation as contract
from inferswarm.operator.bindings import ProcessIdentity, TransportReply
from inferswarm.operator.profiles import canonical, freeze, sha256
from inferswarm.operator.qwen_q8 import q8_static_inventory

from tests.issue299_fixture import NOW
from tests.test_issue299_bindings import source_receipt
from tests.test_issue299_q8_plan import metadata
from tests.test_issue302_per_role_builds import (
    SYNTHETIC_EXE_SHA, distinct_role_plan)

ROUND2 = Path(__file__).resolve().parents[1] / 'tests/fixtures/issue299/round2-native'


def seal(record):
    record = dict(record)
    record['terminal_digest'] = hashlib.sha256(json.dumps(
        {k: v for k, v in record.items() if k != 'terminal_digest'},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return record


def bound_manifest_for(plan, participant):
    from tests.test_issue302_per_role_builds import LLAMA_MANIFEST, RPC_MANIFEST
    body = dict(LLAMA_MANIFEST if participant.role == 'client' else RPC_MANIFEST)
    body['executable_sha256'] = participant.runtime_sha256
    return contract.parse_build_manifest(body)


def observed_inventory_for(plan, participant):
    """SYNTHETIC observed inventory for one participant's owned catalog.

    Labeled synthetic-contract evidence: each row mirrors what a capable
    pre-request static observer would report for this participant's owned
    slice of the frozen plan. It never becomes live capability evidence
    (receipts stay non-authorizing).
    """
    inv = q8_static_inventory(plan.config, metadata(), candidate=plan.candidate)
    ids = {b.binding_id for b in participant.bindings}
    memories = {b.memory_id for b in participant.bindings}
    states, extents = [], []
    for cache in inv.persistent_caches:
        if cache.state.binding_id not in ids:
            continue
        states.append(dict(state_id=cache.state.state_id,
                           binding_id=cache.state.binding_id,
                           memory_id=cache.state.memory_id,
                           native_name=cache.native_name,
                           ggml_type=cache.ggml_type,
                           native_dimensions=list(cache.native_dimensions),
                           observed_bytes=cache.state.lower_bound_bytes))
        extents.append(dict(state_id=cache.state.state_id,
                            base_buffer_bytes=cache.state.lower_bound_bytes,
                            layout_exact=True))
    composites = [dict(state_id=c.state.state_id, phase=c.phase, observed=True)
                  for c in inv.logical_composites]
    weights = [dict(state_id=a.state_id, binding_id=a.binding_id,
                    memory_id=a.memory_id, observed_bytes=a.encoded_bytes)
               for a in plan.candidate.assignments if a.binding_id in ids]
    return contract.ObservedInventoryEvidence(
        weights=tuple(freeze(row) for row in weights),
        persistent_states=tuple(freeze(row) for row in states),
        logical_composites=tuple(freeze(row) for row in composites),
        extents=tuple(freeze(row) for row in extents),
        allocations=tuple(freeze(dict(
            allocation_id=c.allocation_id, memory_id=c.memory_id,
            observed_bytes=c.bytes)) for c in inv.charges
            if c.bytes is not None and c.memory_id in memories),
        source='synthetic-contract')


def observed_host_facts_for(plan, participant):
    """SYNTHETIC independently-observed host facts for the frozen plan."""
    endpoint = participant.rpc_endpoint if participant.role == 'remote' \
        else '127.0.0.1:%d' % participant.port
    return contract.ObservedHostFacts(
        boot_epoch=participant.boot_epoch,
        topology_epoch=participant.topology_epoch,
        listening=(endpoint,),
        observer_environment=dict(IS301_OBSERVE='1',
                                  IS301_EXPORT_DIR='/synthetic/exports-x'),
        source='synthetic-contract')


def static_rows_for(plan, *, token='inv-302', inventory=True, host_facts=True,
                    start=None):
    rows = []
    for participant in plan.participants:
        pid = 101 if participant.role == 'client' else 202
        spawn = contract.OwnedSpawnFacts(participant.participant_id, pid,
                                         start or 'start-%d' % pid, token)
        identity = ProcessIdentity(participant.participant_id,
            participant.host_id, participant.boot_epoch, participant.topology_epoch,
            pid, spawn.start, participant.runtime_executable,
            participant.runtime_sha256,
            (participant.runtime_executable, '--serve'),
            freeze(dict(native=[], visible=[], environment={})),
            participant.rpc_endpoint)
        rows.append(contract.ParticipantStaticEvidence(
            participant.participant_id, identity, spawn,
            contract.DerivedBuildEvidence(bound_manifest_for(plan, participant),
                                          participant.runtime_sha256),
            sha256(source_receipt(plan, participant)),
            observed_inventory=observed_inventory_for(plan, participant) if inventory else None,
            observed_host_facts=observed_host_facts_for(plan, participant)
            if host_facts else None))
    return rows


def static_receipt_for(plan, rows, **kwargs):
    sources = {p.participant_id: source_receipt(plan, p) for p in plan.participants}
    return contract.reconcile_static(plan, rows, sources,
                                     mode='synthetic-test', clock=lambda: NOW, **kwargs)


def synthetic_dynamic_rows(plan, *, token='inv-302', route='one-gpu',
                           pids=None, start=None, nonce='nonce-302'):
    """SYNTHETIC labeled route evidence: nonce-correlated task and complete
    domain-boundary transfer legs for the requested route."""
    rows = []
    for participant in plan.participants:
        pid = (pids or {}).get(participant.role,
                               101 if participant.role == 'client' else 202)
        row_start = start or 'start-%d' % pid
        spawn = contract.OwnedSpawnFacts(participant.participant_id, pid,
                                         row_start, token)
        if participant.role == 'client':
            facts = dict(
                process=dict(pid=pid),
                allocations=[dict(buffer_bytes=96, backend='CPU')],
                tasks=[dict(task_id=1, response_id='unknown',
                            request_nonce=nonce)],
                responses=[dict(task_id=1, request_nonce=nonce)],
                graphs=[dict(graph_id=94176060335536, nodes=1, splits=1,
                             status=0, ubatch_lineage='ub-1')],
                ubatches=[dict(ubatch_id='ub-1', tokens=4,
                               task_id=1, request_nonce=nonce)],
                tokens=[dict(token_count=4, task_id=1,
                             request_nonce=nonce)],
                state_lineage=[dict(task_id=1, request_nonce=nonce,
                                    states_touched=109)],
                transfers=route_legs(route),
                output_custody=[dict(task_id=1, request_nonce=nonce,
                                     readback_bytes=64)],
                route_contract='synthetic/%s' % route)
            events = ['server_task_new_id', 'server_task_processed',
                      'server_response_send', 'tensor_set', 'tensor_get',
                      'sched_graph_compute']
        else:
            facts = dict(
                process=dict(pid=pid),
                allocations=[dict(buffer_bytes=96, backend='RPC0[host-b:5000]')],
                graphs=[dict(graph_id=94018699154864, nodes=1, splits=1,
                             status=0, ubatch_lineage='ub-1')],
                transfers=route_legs(route, remote=True),
                route_contract='synthetic/%s' % route)
            events = ['rpc_server_client', 'rpc_set_tensor', 'rpc_get_tensor',
                      'sched_graph_compute']
        record = dict(schema='inferswarm-native-observation/2', phase='dynamic',
            participant_id='llama-server' if participant.role == 'client'
            else 'ggml-rpc-server',
            plan_digest='0' * 64, invocation_token=token,
            stream_generation='exp-%d-0-966507438683494' % pid,
            sequence=[dict(sequence=i, event=name) for i, name in enumerate(events)],
            sequence_start=0, terminal_sequence=len(events),
            event_count=len(events), terminal_digest='', terminal=True,
            snapshot_fence=False, dropped_events=0, overflow=False,
            stream_kind='whole', facts=facts)
        observation = contract.parse_observation(
            TransportReply(0, json.dumps(seal(record)).encode()))
        rows.append(contract.ParticipantDynamicEvidence(
            participant.participant_id, observation, spawn, pid,
            row_start,
            'llama-server' if participant.role == 'client' else 'ggml-rpc-server'))
    return rows


def route_legs(route, *, remote=False):
    """Complete labeled boundary legs. one-gpu requires the full
    B CPU -> A staging -> B CUDA chain on both GET and SET families."""
    if route == 'cpu-only':
        return [dict(op='set', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                     source_domain='B/cpu', dest_domain='B/cpu',
                     boundary='cpu-only', completed=True),
                dict(op='get', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                     source_domain='B/cpu', dest_domain='B/cpu',
                     boundary='cpu-only', completed=True)]
    if remote:
        # RPC participant observes its side of each leg.
        return [dict(op='rpc_set', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                     source_domain='B/cpu', dest_domain='B/cuda',
                     boundary='b-cpu-to-b-cuda', completed=True),
                dict(op='rpc_get', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                     source_domain='B/cuda', dest_domain='B/cpu',
                     boundary='b-cuda-to-b-cpu', completed=True)]
    return [dict(op='set', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                 source_domain='B/cpu', dest_domain='A/staging',
                 boundary='b-cpu-to-a-staging', completed=True),
            dict(op='set', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                 source_domain='A/staging', dest_domain='B/cuda',
                 boundary='a-staging-to-b-cuda', completed=True),
            dict(op='get', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                 source_domain='B/cuda', dest_domain='A/staging',
                 boundary='b-cuda-to-a-staging', completed=True),
            dict(op='get', bytes=64, tensor='synthetic', shape=[4, 1, 1, 1],
                 source_domain='A/staging', dest_domain='A/cpu-output',
                 boundary='a-staging-to-output', completed=True)]


def request_for(token='inv-302', task_id='1', response_id='resp-1',
                nonce='nonce-302'):
    return contract.RequestIdentity(invocation_token=token, request_nonce=nonce,
                                    task_id=task_id, response_id=response_id)


class StaticInventoryJoinTests(unittest.TestCase):
    """P1-B: complete observed-inventory admission before POST."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def test_complete_observed_inventory_admits(self):
        receipt = static_receipt_for(self.plan, static_rows_for(self.plan))
        self.assertEqual(receipt.verdict, 'STATIC_ADMITTED')
        counts = dict(receipt.counts)
        self.assertEqual(counts['source-range-joined-weights'], 1224)
        self.assertEqual(counts['observed-persistent-states'], 109)
        self.assertEqual(counts['observed-logical-composites'], 2)

    def test_missing_observed_inventory_refuses_with_named_capability(self):
        rows = static_rows_for(self.plan, inventory=False)
        with self.assertRaisesRegex(ValueError, 'observed persistent-state inventory'):
            static_receipt_for(self.plan, rows)

    def test_incomplete_state_coverage_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[1]
        trimmed = victim.observed_inventory.persistent_states[:-1]
        object.__setattr__(victim.observed_inventory, 'persistent_states', trimmed)
        with self.assertRaisesRegex(ValueError, 'observed state coverage'):
            static_receipt_for(self.plan, rows)

    def test_missing_composite_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        object.__setattr__(victim.observed_inventory, 'logical_composites', ())
        with self.assertRaisesRegex(ValueError, 'observed composite'):
            static_receipt_for(self.plan, rows)

    def test_extent_mismatch_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        extents = list(victim.observed_inventory.extents)
        bad = dict(thaw(extents[0]))
        bad['base_buffer_bytes'] = bad['base_buffer_bytes'] + 1
        extents[0] = freeze(bad)
        object.__setattr__(victim.observed_inventory, 'extents', tuple(extents))
        with self.assertRaisesRegex(ValueError, 'extent'):
            static_receipt_for(self.plan, rows)

    def test_duplicated_extent_identity_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        extents = list(victim.observed_inventory.extents)
        extents.append(extents[0])
        object.__setattr__(victim.observed_inventory, 'extents', tuple(extents))
        with self.assertRaisesRegex(ValueError, 'extent identity'):
            static_receipt_for(self.plan, rows)

    def test_duplicated_allocation_identity_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        allocations = list(victim.observed_inventory.allocations)
        allocations.append(allocations[0])
        object.__setattr__(victim.observed_inventory, 'allocations',
                           tuple(allocations))
        with self.assertRaisesRegex(ValueError, 'allocation identity'):
            static_receipt_for(self.plan, rows)

    def test_allocation_headroom_mismatch_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        allocations = list(victim.observed_inventory.allocations)
        bad = dict(thaw(allocations[0]))
        bad['observed_bytes'] = bad['observed_bytes'] + 1
        allocations[0] = freeze(bad)
        object.__setattr__(victim.observed_inventory, 'allocations', tuple(allocations))
        with self.assertRaisesRegex(ValueError, 'allocation'):
            static_receipt_for(self.plan, rows)


class IndependentHostFactsTests(unittest.TestCase):
    """P1-C: independently observed host identity joins."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def test_missing_observed_host_facts_refuse(self):
        rows = static_rows_for(self.plan, host_facts=False)
        with self.assertRaisesRegex(ValueError, 'observed host'):
            static_receipt_for(self.plan, rows)

    def test_observed_boot_epoch_mismatch_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        bad = contract.ObservedHostFacts(boot_epoch='boot-FOREIGN',
            topology_epoch=victim.observed_host_facts.topology_epoch,
            listening=victim.observed_host_facts.listening,
            observer_environment=victim.observed_host_facts.observer_environment,
            source='synthetic-contract')
        object.__setattr__(victim, 'observed_host_facts', bad)
        with self.assertRaisesRegex(ValueError, 'boot epoch'):
            static_receipt_for(self.plan, rows)

    def test_listener_not_observed_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[1]
        bad = contract.ObservedHostFacts(boot_epoch=victim.observed_host_facts.boot_epoch,
            topology_epoch=victim.observed_host_facts.topology_epoch,
            listening=('127.0.0.1:9999',),
            observer_environment=victim.observed_host_facts.observer_environment,
            source='synthetic-contract')
        object.__setattr__(victim, 'observed_host_facts', bad)
        with self.assertRaisesRegex(ValueError, 'listener'):
            static_receipt_for(self.plan, rows)

    def test_missing_observer_environment_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        bad = contract.ObservedHostFacts(boot_epoch=victim.observed_host_facts.boot_epoch,
            topology_epoch=victim.observed_host_facts.topology_epoch,
            listening=victim.observed_host_facts.listening,
            observer_environment={},
            source='synthetic-contract')
        object.__setattr__(victim, 'observed_host_facts', bad)
        with self.assertRaisesRegex(ValueError, 'observer environment'):
            static_receipt_for(self.plan, rows)

    def test_physical_qualified_requires_observed_joins_not_mode_alone(self):
        # With complete observed joins the synthetic receipt still never
        # claims physical qualification; mode alone can never mint it.
        receipt = static_receipt_for(self.plan, static_rows_for(self.plan))
        self.assertFalse(receipt.physical_qualified)


class DynamicRouteContractTests(unittest.TestCase):
    """P1-D: request-correlated, route-correct dynamic acceptance."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def static_receipt(self, **kwargs):
        rows = static_rows_for(self.plan, **kwargs)
        return static_receipt_for(self.plan, rows)

    def test_complete_synthetic_route_contract_accepts(self):
        receipt = contract.reconcile_dynamic(self.plan, self.static_receipt(),
            synthetic_dynamic_rows(self.plan), request_for(),
            mode='synthetic-test', clock=lambda: NOW)
        self.assertEqual(receipt.verdict, 'DYNAMIC_ACCEPTED')

    def test_uncorrelated_task_refuses(self):
        # Genuine tiny-fixture shape: tasks without request correlation.
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['tasks'] = [dict(task_id=1, response_id='unknown')]
        facts['responses'] = [dict(task_id=1)]
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'request correlation'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_cpu_fixture_transfers_cannot_satisfy_cuda_route(self):
        # The reviewed head accepted one-gpu plans on incidental CPU fixture
        # transfers; domain-boundary legs are now mandatory.
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['transfers'] = [dict(op='set', bytes=16, tensor='tiny-a',
            shape=[4, 1, 1, 1], source_domain='A/cpu', dest_domain='A/cpu',
            boundary='fixture', completed=True),
            dict(op='get', bytes=16, tensor='tiny-a', shape=[4, 1, 1, 1],
            source_domain='A/cpu', dest_domain='A/cpu',
            boundary='fixture', completed=True)]
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'boundary|route'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_missing_staging_leg_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['transfers'] = [t for t in facts['transfers']
                              if t['boundary'] != 'b-cpu-to-a-staging']
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'b-cpu-to-a-staging'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_missing_cuda_leg_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['transfers'] = [t for t in facts['transfers']
                              if t['boundary'] != 'a-staging-to-b-cuda']
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'a-staging-to-b-cuda'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_incomplete_get_leg_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['transfers'] = [t for t in facts['transfers']
                              if t['boundary'] != 'b-cuda-to-a-staging']
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'b-cuda-to-a-staging'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_cpu_only_route_is_a_separate_contract(self):
        # A cpu-only plan accepts CPU-domain-boundary evidence that would
        # never satisfy the one-gpu CUDA route, and vice versa.
        from tests.test_issue302_per_role_builds import distinct_runtime_mapping
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.config import parse_config
        from tests.test_issue299_q8_plan import fully_bounded_mapping
        from tests.issue299_fixture import reseal_profiles, profile_digest
        raw = fully_bounded_mapping('cpu-only')
        raw['strategy_options']['observer'] = dict(
            client_manifest_path='/opt/observer/llama-server.build-manifest.json',
            client_executable_path='/opt/observer/llama-server',
            remote_manifest_path='/opt/observer/ggml-rpc-server.build-manifest.json',
            remote_executable_path='/opt/observer/ggml-rpc-server')
        from tests.test_issue302_per_role_builds import LLAMA_EXE_SHA, RPC_EXE_SHA
        digests = {'A': LLAMA_EXE_SHA, 'B': RPC_EXE_SHA}
        for participant in raw['participants']:
            participant['runtime_sha256'] = digests[participant['host_id']]
        for runtime in raw['profiles']['snapshot']['runtime_capabilities']:
            participant = next(p2 for p2 in raw['participants']
                               if p2['host_id'] == runtime['host_id'])
            runtime['binary_sha256'] = participant['runtime_sha256']
            for evidence in raw['profiles']['snapshot']['evidence']:
                if evidence['evidence_id'] == 'synthetic-' + runtime['runtime_id']:
                    evidence['dependencies'][
                        'runtime:' + runtime['runtime_id'] + ':binary_sha256'] = participant['runtime_sha256']
        reseal_profiles(raw['profiles']['snapshot'])
        raw['profiles']['digest'] = profile_digest(raw['profiles']['snapshot'])
        cpu_plan = build_plan(parse_config(raw, now=NOW, profile_mode='replay'), now=NOW)
        cpu_static = static_receipt_for(cpu_plan, static_rows_for(cpu_plan))
        receipt = contract.reconcile_dynamic(cpu_plan, cpu_static,
            synthetic_dynamic_rows(cpu_plan, route='cpu-only'), request_for(),
            mode='synthetic-test', clock=lambda: NOW)
        self.assertEqual(receipt.verdict, 'DYNAMIC_ACCEPTED')
        # The same CPU-only evidence on the one-gpu plan refuses.
        with self.assertRaisesRegex(ValueError, 'boundary|route'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(),
                synthetic_dynamic_rows(self.plan, route='cpu-only'), request_for(),
                mode='synthetic-test', clock=lambda: NOW)

    def test_unbound_output_custody_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['output_custody'] = [dict(task_id=2, request_nonce='nonce-302',
                                        readback_bytes=64)]
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'output custody'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_unknown_ubatch_lineage_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['graphs'] = [dict(g, ubatch_lineage='unknown')
                           for g in facts['graphs']]
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'ubatch'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)


def thaw(value):
    from inferswarm.operator.profiles import thaw as _thaw
    return _thaw(value)


def _mutate(observation, mutate, replacement=None):
    from dataclasses import fields as _fields
    record = {f.name: getattr(observation, f.name) for f in _fields(observation)}
    record['sequence'] = [dict(row) for row in observation.sequence]
    record['facts'] = json.loads(json.dumps(thaw(observation.facts)))
    if replacement is not None:
        record['facts'] = replacement
    mutate(record['facts'])
    return contract.parse_observation(TransportReply(0, json.dumps(seal(record)).encode()))


if __name__ == '__main__':
    unittest.main()
