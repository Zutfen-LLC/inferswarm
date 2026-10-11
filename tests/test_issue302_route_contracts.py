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
    offsets = {}
    charges = {c.allocation_id: c for c in inv.charges}
    for cache in inv.persistent_caches:
        if cache.state.binding_id not in ids:
            continue
        allocation = 'state-lower-bound:' + cache.state.binding_id + '/serve'
        offset = offsets.get(allocation, 0)
        offsets[allocation] = offset + cache.state.lower_bound_bytes
        states.append(dict(state_id=cache.state.state_id,
                           binding_id=cache.state.binding_id,
                           memory_id=cache.state.memory_id,
                           native_name=cache.native_name,
                           ggml_type=cache.ggml_type,
                           native_dimensions=list(cache.native_dimensions),
                           observed_bytes=cache.state.lower_bound_bytes))
        extents.append(dict(state_id=cache.state.state_id,
                            allocation_id=allocation, offset=offset,
                            length=cache.state.lower_bound_bytes,
                            base_buffer_bytes=charges[allocation].bytes,
                            layout_exact=True))
    composites = [dict(state_id=c.state.state_id, phase=c.phase, observed=True,
                       binding_id=c.state.binding_id, memory_id=c.state.memory_id,
                       allocation_id=c.state.state_id + '/serve', offset=0,
                       observed_bytes=charges[c.state.state_id + '/serve'].bytes)
                  for c in inv.logical_composites if c.state.binding_id in ids]
    weights = [dict(state_id=a.state_id, binding_id=a.binding_id,
                    memory_id=a.memory_id, observed_bytes=a.encoded_bytes)
               for a in plan.candidate.assignments if a.binding_id in ids]
    memories = {m.memory_id: m for m in plan.profiles.snapshot.memory_resources
                if m.host_id == participant.host_id}
    return contract.ObservedInventoryEvidence(
        weights=tuple(freeze(row) for row in weights),
        persistent_states=tuple(freeze(row) for row in states),
        logical_composites=tuple(freeze(row) for row in composites),
        extents=tuple(freeze(row) for row in extents),
        allocations=tuple(freeze(dict(
            allocation_id=c.allocation_id, memory_id=c.memory_id,
            physical_domain=memories[c.memory_id].physical_id,
            physical_allocation_id=c.memory_id + ':' + c.allocation_id.rsplit('/', 1)[0],
            phase=c.phase, role=c.role, padding_bytes=0,
            total_bytes=memories[c.memory_id].total_bytes,
            available_bytes=memories[c.memory_id].available_bytes,
            observed_bytes=c.bytes)) for c in inv.charges
            if c.memory_id in memories),
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


def observed_visibility(participant):
    """OBSERVED effective selectors a capable observer reports for the
    frozen plan (mirrors the /1 binding-preflight visibility contract)."""
    bindings = sorted(participant.bindings, key=lambda b: b.visible_selector)
    return freeze(dict(native=[b.native_selector for b in bindings],
                       visible=[b.visible_selector for b in bindings],
                       environment={}))


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
            observed_visibility(participant),
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
                           pids=None, start=None, nonce='nonce-302', response_id='resp-1'):
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
                transfers=[dict(t, task_id=1, request_nonce=nonce)
                           for t in route_legs(route)],
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
                transfers=[dict(t, task_id=1, request_nonce=nonce)
                           for t in route_legs(route, remote=True)],
                route_contract='synthetic/%s' % route)
            events = ['rpc_server_client', 'rpc_set_tensor', 'rpc_get_tensor',
                      'sched_graph_compute']
        # Full SYNTHETIC producer-correlation catalog. These are test values,
        # never additions to the accepted #301 producer or retained captures.
        for graph in facts['graphs']:
            graph.update(task_id=1, request_nonce=nonce, generation=1,
                         ubatch_generation=1)
        facts['ubatches'] = [dict(ubatch_id='ub-1', generation=1,
            graph_generation=1, index=0, tokens=4, task_id=1, request_nonce=nonce)]
        facts['tokens'] = [dict(token_count=4, ubatch_id='ub-1', ubatch_generation=1,
            graph_generation=1, task_id=1, request_nonce=nonce)]
        owned = {b.binding_id for b in participant.bindings}
        facts['state_lineage'] = [dict(state_id=s.state_id, binding_id=s.binding_id,
            authority_epoch=1, ubatch_id='ub-1', ubatch_generation=1,
            graph_generation=1, task_id=1, request_nonce=nonce)
            for s in plan.candidate.required_state if s.binding_id in owned]
        for index, transfer in enumerate(facts['transfers']):
            is_get = transfer['op'] in ('get', 'rpc_get')
            transfer.update(graph_generation=1, ubatch_id='ub-1', ubatch_generation=1,
                tensor_generation=1, tensor_capacity_bytes=transfer['bytes'],
                depends_on_route='copy-in-1' if is_get else None,
                route_id='copy-out-1' if is_get else 'copy-in-1',
                transfer_id=participant.role + '-transfer-' + str(index),
                range_offset=0, range_bytes=transfer['bytes'],
                strides=[4, 16, 16, 16], leg_index=(index % 2 if participant.role == 'client' and route != 'cpu-only' else 0))
        if participant.role == 'client':
            facts['responses'][0]['response_id'] = response_id
            final = facts['transfers'][-1]
            facts['output_custody'][0].update(response_id=response_id,
                graph_generation=1, ubatch_id='ub-1', ubatch_generation=1,
                transfer_id=final['transfer_id'], tensor=final['tensor'],
                range_offset=final['range_offset'], range_bytes=final['range_bytes'],
                tensor_generation=final['tensor_generation'],
                shape=final['shape'], strides=final['strides'], output_domain=final['dest_domain'])
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
        # Above-bound padding is legal; this control targets below-bound bytes.
        bad['observed_bytes'] = bad['observed_bytes'] - 1
        allocations[0] = freeze(bad)
        object.__setattr__(victim.observed_inventory, 'allocations', tuple(allocations))
        with self.assertRaisesRegex(ValueError, 'allocation'):
            static_receipt_for(self.plan, rows)


    def test_unobserved_visibility_refuses_with_named_capability(self):
        # Empty visibility (what the production /proc reader reports today)
        # must refuse static admission naming the missing observer
        # capability — never silently accept the configured selectors.
        rows = static_rows_for(self.plan)
        victim = rows[0]
        from dataclasses import replace as _replace
        blank = _replace(victim.identity,
                         visibility=freeze(dict(native=[], visible=[],
                                                environment={})))
        object.__setattr__(victim, 'identity', blank)
        with self.assertRaisesRegex(ValueError,
                                    'effective device visibility not independently '
                                    'observed.*native/visible selector observation'):
            static_receipt_for(self.plan, rows)

    def test_mismatched_visibility_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        from dataclasses import replace as _replace
        foreign = _replace(victim.identity,
                           visibility=freeze(dict(native=['CUDA9'],
                                                  visible=['RPC9'],
                                                  environment={})))
        object.__setattr__(victim, 'identity', foreign)
        with self.assertRaisesRegex(ValueError,
                                    'effective device visibility not independently '
                                    'observed'):
            static_receipt_for(self.plan, rows)

    def test_unexpected_observed_extent_refuses(self):
        # Surplus extent evidence is a contradiction, not harmless.
        rows = static_rows_for(self.plan)
        victim = rows[0]
        extents = list(victim.observed_inventory.extents)
        foreign = dict(thaw(extents[0]))
        foreign['state_id'] = foreign['state_id'] + '-phantom'
        extents.append(freeze(foreign))
        object.__setattr__(victim.observed_inventory, 'extents', tuple(extents))
        with self.assertRaisesRegex(ValueError, 'extent coverage'):
            static_receipt_for(self.plan, rows)

    def test_unexpected_observed_allocation_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        allocations = list(victim.observed_inventory.allocations)
        foreign = dict(thaw(allocations[0]))
        foreign['allocation_id'] = foreign['allocation_id'] + '-phantom'
        allocations.append(freeze(foreign))
        object.__setattr__(victim.observed_inventory, 'allocations',
                           tuple(allocations))
        with self.assertRaisesRegex(ValueError, 'allocation coverage'):
            static_receipt_for(self.plan, rows)

    def test_missing_observed_weight_refuses(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        weights = list(victim.observed_inventory.weights)
        object.__setattr__(victim.observed_inventory, 'weights', weights[:-1])
        with self.assertRaisesRegex(ValueError, 'observed weight coverage'):
            static_receipt_for(self.plan, rows)

    def test_wrong_observed_weight_bytes_refuse(self):
        rows = static_rows_for(self.plan)
        victim = rows[0]
        weights = list(victim.observed_inventory.weights)
        bad = dict(thaw(weights[0]))
        bad['observed_bytes'] = bad['observed_bytes'] + 1
        weights[0] = freeze(bad)
        object.__setattr__(victim.observed_inventory, 'weights', tuple(weights))
        with self.assertRaisesRegex(ValueError, 'observed weight identity'):
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

    def test_transfer_with_foreign_request_correlation_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        facts['transfers'] = [dict(t, task_id=999, request_nonce='foreign')
                              for t in facts['transfers']]
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError, 'transfer.*request|foreign'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

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
        with self.assertRaisesRegex(ValueError, 'boundary|route|transfer request'):
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
        with self.assertRaisesRegex(ValueError, 'boundary|route|transfer request'):
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


    def test_boundary_label_with_wrong_op_cannot_satisfy_route(self):
        # The SET-direction staging leg relabeled onto a GET op must not
        # satisfy the boundary: label alone is not a domain/op join.
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        mutated_transfers = []
        for t in facts['transfers']:
            t = dict(t)
            if t['boundary'] == 'b-cpu-to-a-staging':
                t['op'] = 'get'
            mutated_transfers.append(t)
        facts['transfers'] = mutated_transfers
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError,
                                    'b-cpu-to-a-staging'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_boundary_label_with_wrong_domains_cannot_satisfy_route(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        mutated_transfers = []
        for t in facts['transfers']:
            t = dict(t)
            if t['boundary'] == 'a-staging-to-b-cuda':
                t['dest_domain'] = 'A/cpu'
            mutated_transfers.append(t)
        facts['transfers'] = mutated_transfers
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError,
                                    'a-staging-to-b-cuda'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_foreign_completed_boundary_label_refuses(self):
        rows = synthetic_dynamic_rows(self.plan)
        facts = dict(thaw(rows[0].observation.facts))
        extra = dict(facts['transfers'][0], boundary='cuda-direct-magic',
                     tensor='phantom')
        facts['transfers'] = list(facts['transfers']) + [extra]
        mutated = _mutate(rows[0].observation, lambda f: None, replacement=facts)
        from dataclasses import replace
        rows = (replace(rows[0], observation=mutated), rows[1])
        with self.assertRaisesRegex(ValueError,
                                    'foreign boundary label'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows,
                request_for(), mode='synthetic-test', clock=lambda: NOW)

    def test_cpu_only_route_requires_both_completed_legs(self):
        from tests.test_issue299_q8_plan import fully_bounded_mapping
        from tests.issue299_fixture import reseal_profiles, profile_digest
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.config import parse_config
        from tests.test_issue302_per_role_builds import LLAMA_EXE_SHA, RPC_EXE_SHA
        raw = fully_bounded_mapping('cpu-only')
        raw['strategy_options']['observer'] = dict(
            client_manifest_path='/opt/observer/llama-server.build-manifest.json',
            client_executable_path='/opt/observer/llama-server',
            remote_manifest_path='/opt/observer/ggml-rpc-server.build-manifest.json',
            remote_executable_path='/opt/observer/ggml-rpc-server')
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
        # Strip every GET leg: cpu-only must refuse, not accept the SET remnant.
        rows = synthetic_dynamic_rows(cpu_plan, route='cpu-only')
        stripped = []
        for row in rows:
            facts = dict(thaw(row.observation.facts))
            facts['transfers'] = [t for t in facts['transfers']
                                  if t['op'] not in ('get', 'rpc_get')]
            stripped.append(_mutate(row.observation, lambda f: None,
                                    replacement=facts))
        from dataclasses import replace
        rows = tuple(replace(row, observation=mutated)
                     for row, mutated in zip(rows, stripped))
        with self.assertRaisesRegex(ValueError, 'GET leg missing'):
            contract.reconcile_dynamic(cpu_plan, cpu_static, rows,
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


def capture_for(plan, row):
    from datetime import timedelta
    return dict(observed_at=NOW.isoformat(), expires_at=(NOW + timedelta(minutes=5)).isoformat(),
                capture_id='synthetic-capture-' + row.participant_id,
                producer='synthetic-contract', plan_digest=plan.digest,
                invocation_token=row.spawn.invocation_token, pid=row.spawn.pid, start=row.spawn.start,
                build_digest=row.build.manifest.manifest_sha256,
                source_digest=row.source_receipt_digest)


class ExactStaticReceiptTests(unittest.TestCase):
    """5483410569: complete receipt binding, immutable facts, live refusal."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def test_inventory_and_host_fact_changes_change_receipt_digest(self):
        from dataclasses import replace
        baseline = static_receipt_for(self.plan, static_rows_for(self.plan))
        for family in ('inventory', 'host'):
            rows = static_rows_for(self.plan)
            row = rows[0]
            if family == 'inventory':
                inv = row.observed_inventory
                weights = list(inv.weights)
                weights[0] = freeze(dict(thaw(weights[0]), capture_note='changed'))
                rows[0] = replace(row, observed_inventory=replace(inv, weights=tuple(weights)))
            else:
                host = row.observed_host_facts
                env = dict(thaw(host.observer_environment), CAPTURE_NOTE='changed')
                rows[0] = replace(row, observed_host_facts=replace(host, observer_environment=env))
            with self.subTest(family=family):
                self.assertNotEqual(baseline.observation_digest,
                                    static_receipt_for(self.plan, rows).observation_digest)

    def test_host_environment_is_detached_and_immutable(self):
        env = dict(IS301_OBSERVE='1', IS301_EXPORT_DIR='/synthetic/export')
        host = contract.ObservedHostFacts('boot', 'topology', ('endpoint',), env,
                                           'synthetic-contract')
        env['IS301_OBSERVE'] = '0'
        self.assertEqual(thaw(host.observer_environment)['IS301_OBSERVE'], '1')
        self.assertNotIsInstance(host.observer_environment, dict)

    def test_live_refuses_synthetic_unknown_and_missing_capture_provenance(self):
        from dataclasses import replace
        # Clock patched at its real-time seam, not injected through live API.
        from unittest.mock import patch
        sources = {p.participant_id: source_receipt(self.plan, p) for p in self.plan.participants}
        for source in ('synthetic-contract', 'observed/unknown', 'unrecognized', 'native-observer/2'):
            rows = static_rows_for(self.plan)
            rows = [replace(r, observed_inventory=replace(r.observed_inventory, source=source),
                               observed_host_facts=replace(r.observed_host_facts, source=source))
                    for r in rows]
            with self.subTest(source=source), patch.object(contract, '_static_observed_joins',
                    return_value=q8_static_inventory(self.plan.config, metadata(), candidate=self.plan.candidate)):
                with self.assertRaisesRegex(ValueError, 'provenance|capture'):
                    contract.reconcile_static(self.plan, rows, sources, mode='live')

    def test_capture_freshness_and_process_build_source_binding_refuse(self):
        rows = static_rows_for(self.plan)
        for field, value in (('observed_at', '2020-01-01T00:00:00Z'),
                             ('expires_at', '2020-01-02T00:00:00Z'),
                             ('pid', 999), ('start', 'foreign'),
                             ('plan_digest', 'f' * 64), ('invocation_token', 'foreign'),
                             ('build_digest', 'f' * 64), ('source_digest', 'f' * 64)):
            rows = static_rows_for(self.plan)
            for r in rows:
                capture = capture_for(self.plan, r)
                if r == rows[0]:
                    capture[field] = value
                object.__setattr__(r, 'capture', freeze(capture))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'capture'):
                static_receipt_for(self.plan, rows)

    def test_dynamic_live_mode_alone_never_qualifies_physical_q8(self):
        receipt = contract.reconcile_dynamic(self.plan,
            static_receipt_for(self.plan, static_rows_for(self.plan)),
            synthetic_dynamic_rows(self.plan), request_for(), mode='live')
        self.assertFalse(receipt.physical_qualified)


class ExactAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def mutate(self, rows, family, fn):
        from dataclasses import replace
        inv = rows[0].observed_inventory
        records = [thaw(r) for r in getattr(inv, family)]
        fn(records)
        rows[0] = replace(rows[0], observed_inventory=replace(inv,
            **{family: tuple(freeze(r) for r in records)}))

    def test_composites_are_owned_once_not_replicated_per_participant(self):
        from dataclasses import replace
        inv = q8_static_inventory(self.plan.config, metadata(), candidate=self.plan.candidate)
        rows = static_rows_for(self.plan)
        for n, (row, p) in enumerate(zip(rows, self.plan.participants)):
            names = {c.state.state_id for c in inv.logical_composites
                     if c.state.binding_id in {b.binding_id for b in p.bindings}}
            rows[n] = replace(row, observed_inventory=replace(row.observed_inventory,
                logical_composites=tuple(r for r in row.observed_inventory.logical_composites
                                        if thaw(r)['state_id'] in names)))
        self.assertEqual(static_receipt_for(self.plan, rows).verdict, 'STATIC_ADMITTED')

    def test_padded_native_extent_and_actual_allocation_admit(self):
        rows = static_rows_for(self.plan)
        self.mutate(rows, 'allocations', lambda a: a[0].update(observed_bytes=a[0]['observed_bytes'] + 64))
        # Native padding is actual bytes, not an equality to a calculated lower bound.
        self.assertEqual(static_receipt_for(self.plan, rows).verdict, 'STATIC_ADMITTED')

    def test_padded_state_extent_closes_against_actual_base(self):
        rows = static_rows_for(self.plan)
        target = thaw(rows[0].observed_inventory.extents[-1])
        allocation = target['allocation_id']
        self.mutate(rows, 'persistent_states', lambda a: a[-1].update(observed_bytes=a[-1]['observed_bytes'] + 64))
        self.mutate(rows, 'extents', lambda a: [r.update(base_buffer_bytes=r['base_buffer_bytes'] + 64,
            **({'length': r['length'] + 64} if r['state_id'] == target['state_id'] else {}))
            for r in a if r['allocation_id'] == allocation])
        self.mutate(rows, 'allocations', lambda a: [r.update(observed_bytes=r['observed_bytes'] + 64)
            for r in a if r['allocation_id'] == allocation])
        self.assertEqual(static_receipt_for(self.plan, rows).verdict, 'STATIC_ADMITTED')

    def test_unaccounted_extent_and_hidden_mirror_refuse(self):
        for family, mutate, reason in (
            ('extents', lambda a: a[0].update(allocation_id='unaccounted'), 'unaccounted'),
            ('allocations', lambda a: a[1].update(physical_allocation_id=a[0]['physical_allocation_id'],
                                                phase=a[0]['phase']), 'phase/role|mirror'),
            ('allocations', lambda a: a[0].update(observed_bytes=None), 'allocation'),
        ):
            rows = static_rows_for(self.plan)
            self.mutate(rows, family, mutate)
            with self.subTest(family=family), self.assertRaisesRegex(ValueError, reason):
                static_receipt_for(self.plan, rows)

    def test_foreign_physical_domain_refuses_even_with_matching_logical_memory(self):
        rows = static_rows_for(self.plan)
        self.mutate(rows, 'allocations', lambda a: a[0].update(physical_domain='foreign'))
        with self.assertRaisesRegex(ValueError, 'physical domain'):
            static_receipt_for(self.plan, rows)

    def test_extent_outside_base_refuses(self):
        rows = static_rows_for(self.plan)
        self.mutate(rows, 'extents', lambda a: a[0].update(offset=a[0]['base_buffer_bytes']))
        with self.assertRaisesRegex(ValueError, 'extent.*range|extent.*outside'):
            static_receipt_for(self.plan, rows)

    def test_extent_overlap_refuses(self):
        rows = static_rows_for(self.plan)
        self.mutate(rows, 'extents', lambda a: a[1].update(offset=0, allocation_id=a[0].get('allocation_id')))
        with self.assertRaisesRegex(ValueError, 'extent.*overlap'):
            static_receipt_for(self.plan, rows)

    def test_actual_policy_capacity_and_available_headroom_refuse(self):
        for field, value, reason in (('observed_bytes', 1 << 50, 'actual.*policy|actual.*capacity'),
                                     ('available_bytes', 0, 'actual.*headroom'),
                                     ('total_bytes', 1, 'actual.*capacity')):
            rows = static_rows_for(self.plan)
            self.mutate(rows, 'allocations', lambda a: [r.update(**{field: value})
                for r in a if r['memory_id'] == 'A-ram' and r.get('role') != 'virtual'])
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                static_receipt_for(self.plan, rows)


class ExactDynamicCorrelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()
        cls.static = static_receipt_for(cls.plan, static_rows_for(cls.plan))

    def reject_mutation(self, mutate, reason, participant=0):
        from dataclasses import replace
        rows = synthetic_dynamic_rows(self.plan)
        rows[participant] = replace(rows[participant], observation=_mutate(rows[participant].observation, mutate))
        with self.assertRaisesRegex(ValueError, reason):
            contract.reconcile_dynamic(self.plan, self.static, rows, request_for(),
                                       mode='synthetic-test', clock=lambda: NOW)

    def test_foreign_and_missing_graph_task_nonce_refuse_on_every_participant(self):
        for participant in (0, 1):
            for field, value in (('task_id', 999), ('request_nonce', 'foreign'), ('task_id', None)):
                with self.subTest(participant=participant, field=field):
                    self.reject_mutation(lambda f: f['graphs'][0].update(**{field: value}),
                                         'graph.*task/nonce', participant)

    def test_missing_explicit_graph_generation_refuses(self):
        self.reject_mutation(lambda f: f['graphs'][0].pop('generation', None), 'graph.*generation')

    def test_foreign_ubatch_generation_and_lineage_refuse(self):
        for field, value in (('ubatch_lineage', 'foreign'), ('ubatch_generation', 999)):
            with self.subTest(field=field):
                self.reject_mutation(lambda f: f['graphs'][0].update(**{field: value}), 'graph.*ubatch')

    def test_transfer_tensor_range_and_generation_are_not_labels(self):
        for field, value in (('tensor', 'foreign'), ('range_offset', 999),
                             ('graph_generation', 999), ('ubatch_generation', 999),
                             ('strides', [1, 2]), ('range_bytes', 1)):
            with self.subTest(field=field):
                self.reject_mutation(lambda f: f['transfers'][1].update(**{field: value}),
                                     'transfer.*join|route.*join|transfer.*lineage|transfer.*range')

    def test_reversed_material_legs_refuse(self):
        self.reject_mutation(lambda f: f['transfers'].reverse(), 'route.*order')

    def test_output_custody_response_tensor_range_readback_join_refuse(self):
        for field, value in (('response_id', 'foreign'), ('tensor', 'foreign'),
                             ('range_offset', 999), ('graph_generation', 999),
                             ('readback_bytes', 1), ('transfer_id', 'foreign')):
            with self.subTest(field=field):
                self.reject_mutation(lambda f: f['output_custody'][0].update(**{field: value}),
                                     'output custody.*join|output custody.*binding')

    def test_remote_domain_and_cross_route_order_refuse(self):
        with self.subTest(case='remote-domain'):
            self.reject_mutation(lambda f: f['transfers'][0].update(source_domain='A/cpu'),
                                 'route.*domain', participant=1)
        with self.subTest(case='return-before-send'):
            self.reject_mutation(lambda f: f.update(transfers=f['transfers'][2:] + f['transfers'][:2]),
                                 'route.*order')

    def test_transfer_native_range_capacity_and_tensor_generation_missing_refuse(self):
        for field in ('tensor_capacity_bytes', 'tensor_generation'):
            with self.subTest(field=field):
                self.reject_mutation(lambda f: f['transfers'][0].pop(field, None),
                                     'transfer.*range|transfer.*generation')

    def test_dynamic_digest_binds_static_receipt_and_request_identity(self):
        from dataclasses import replace
        rows = synthetic_dynamic_rows(self.plan)
        first = contract.reconcile_dynamic(self.plan, self.static, rows, request_for(),
                                            mode='synthetic-test', clock=lambda: NOW)
        second = contract.reconcile_dynamic(self.plan,
            replace(self.static, observation_digest='e' * 64), rows, request_for(),
            mode='synthetic-test', clock=lambda: NOW)
        self.assertNotEqual(first.observation_digest, second.observation_digest)

    def test_state_lineage_requires_named_authority_catalog_not_count(self):
        self.reject_mutation(lambda f: f['state_lineage'].clear(), 'state lineage')
        self.reject_mutation(lambda f: f['state_lineage'][0].update(state_id='foreign'),
                             'state lineage.*coverage|state lineage.*identity')


if __name__ == '__main__':
    unittest.main()
