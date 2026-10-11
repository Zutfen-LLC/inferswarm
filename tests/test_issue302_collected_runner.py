"""Issue #302 collected /2 integration; all evidence explicitly SYNTHETIC
except the genuine retained native captures and build manifests, which are
replayed through recording SSH transports. No native build, no model, no
inference, no physical execution.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from inferswarm.operator import phased_observation as contract
from inferswarm.operator.phased_observation import ParticipantDynamicEvidence
from inferswarm.operator.bindings import ProcessIdentity, TransportReply
from inferswarm.operator.native_observer.collector import (
    CollectorError, NativeObserverCollector, NATIVE_LABELS, ProcIdentityReader,
    SSHCollectorTransport)
from inferswarm.operator.plan import build_plan
from inferswarm.operator.profiles import canonical, freeze, sha256, thaw
from inferswarm.operator.runtime import OperatorRunner, SSHSourceTransport
from inferswarm.operator.lifecycle import LeaseManager
from tests.issue299_fixture import NOW
from tests.test_issue299_bindings import plan_fixture, source_receipt
from tests.test_issue299_q8_plan import fully_bounded_mapping
from tests.test_issue299_runtime import Harness, RecordingLifecycle

ROUND2 = Path(__file__).resolve().parents[1] / 'tests/fixtures/issue299/round2-native'
CAPTURES = Path(__file__).resolve().parents[1] / 'tests/fixtures/issue299/native-captures'


def collected_plan(selection='one-gpu'):
    raw = fully_bounded_mapping(selection)
    raw['strategy_options']['observer'] = dict(
        manifest_path='/opt/observer/llama-server.build-manifest.json',
        executable_path='/opt/observer/llama-server')
    return build_plan(plan_parse(raw), now=NOW)


def plan_bound_manifest(plan):
    """Genuine #301 manifest body rebound to the synthetic plan runtime.

    The production law binds manifest.executable_sha256 to the participant's
    runtime binary; the synthetic plan's runtime digest is fabricated, so the
    genuine body is re-sealed against it for reconciler tests only. The
    collector tests below keep the genuine manifest and authenticate actual
    bytes.
    """
    body = build_manifest_body()
    client = next(p for p in plan.participants if p.role == 'client')
    remote = next(p for p in plan.participants if p.role == 'remote')
    assert client.runtime_sha256 == remote.runtime_sha256
    body['executable_sha256'] = client.runtime_sha256
    return contract.parse_build_manifest(body)


def plan_parse(raw):
    from inferswarm.operator.config import parse_config
    return parse_config(raw, now=NOW, profile_mode='replay')


class VirtualHostTree:
    """A fake per-address filesystem served to the collector over SSH."""

    def __init__(self):
        self.files = {}   # address -> {path: bytes}
        self.dirs = {}    # address -> {path: [names]}

    def put(self, address, path, payload):
        if isinstance(payload, (dict, list)):
            payload = canonical(payload)
        self.files.setdefault(address, {})[str(path)] = payload

    def put_dir(self, address, path, names):
        self.dirs.setdefault(address, {})[str(path)] = sorted(names)


class RecordingCollectorTransport(SSHCollectorTransport):
    def __init__(self, tree: VirtualHostTree, failures=None):
        self.tree = tree
        self.failures = failures or {}
        self.reads = []

    def read_bytes(self, address, path):
        self.reads.append((address, path))
        if (address, path) in self.failures:
            raise self.failures[(address, path)]
        try:
            return self.tree.files[address][str(path)]
        except KeyError as exc:
            raise CollectorError(f'collector read failed ({address}:{path}): absent') from exc

    def read_json(self, address, path):
        raw = self.read_bytes(address, path)
        return json.loads(raw.decode('utf-8'))

    def list_dir(self, address, path):
        try:
            return list(self.tree.dirs[address][str(path)])
        except KeyError as exc:
            raise CollectorError(f'collector listing failed ({address}:{path}): absent') from exc


def build_manifest_body(name='llama-server.build-manifest'):
    return json.loads((ROUND2 / f'{name}.json').read_text())


def genuine_dynamic(name, participant, token, pid):
    """Re-seal a genuine retained capture against the test identity."""
    record = json.loads((ROUND2 / name).read_text())
    record['participant_id'] = participant
    record['invocation_token'] = token
    record['plan_digest'] = '0' * 64
    record['terminal_digest'] = hashlib.sha256(canonical(
        {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
    return record


class StaticReconciliationTests(unittest.TestCase):
    """Genuine build manifests joined to synthetic plans; SYNTHETIC plans."""

    @classmethod
    def setUpClass(cls):
        cls.plan = collected_plan('one-gpu')
        cls.manifest = plan_bound_manifest(cls.plan)

    def participant(self, role):
        return next(p for p in self.plan.participants if p.role == role)

    def spawn(self, participant, token='inv-302'):
        return contract.OwnedSpawnFacts(participant.participant_id, 4242, 'start-4242', token)

    def identity(self, participant, spawn, argv=None):
        argv = argv or (participant.runtime_executable, '--serve')
        return ProcessIdentity(participant.participant_id, participant.host_id,
            participant.boot_epoch, participant.topology_epoch, spawn.pid, spawn.start,
            participant.runtime_executable, participant.runtime_sha256, argv,
            freeze(dict(native=[], visible=[], environment={})), participant.rpc_endpoint)

    def build_evidence(self, participant):
        return contract.DerivedBuildEvidence(self.manifest, self.manifest.executable_sha256)

    def static_snapshot(self, participant, token='inv-302'):
        record = json.loads((ROUND2 / 'cpu-static.json').read_text())
        record['participant_id'] = 'observer-static-' + participant.participant_id
        record['invocation_token'] = token
        record['plan_digest'] = '0' * 64
        record['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
        return contract.parse_observation(TransportReply(0, json.dumps(record).encode()))

    def evidence_rows(self, token='inv-302'):
        rows = []
        for role in ('client', 'remote'):
            p = self.participant(role)
            spawn = self.spawn(p, token)
            rows.append(contract.ParticipantStaticEvidence(
                p.participant_id, self.identity(p, spawn), spawn, self.build_evidence(p),
                sha256(self.source_receipts()[p.participant_id]),
                self.static_snapshot(p, token)))
        return rows

    def source_receipts(self):
        return {p.participant_id: source_receipt(self.plan, p) for p in self.plan.participants}

    def test_complete_static_path_admits_with_genuine_manifest(self):
        receipt = contract.reconcile_static(self.plan, self.evidence_rows(),
                                            self.source_receipts(),
                                            mode='synthetic-test', clock=lambda: NOW)
        self.assertEqual(receipt.verdict, 'STATIC_ADMITTED')
        self.assertEqual(receipt.plan_digest, self.plan.digest)
        self.assertEqual(dict(receipt.counts)['weights'], 1224)
        self.assertFalse(receipt.execution_authorized)

    def test_missing_source_range_refuses_before_admission(self):
        sources = self.source_receipts()
        victim = next(p for p in self.plan.participants if p.role == 'remote')
        receipt = sources[victim.participant_id]
        receipt['range_identities'].pop()
        # The controller-collected digest still describes the complete receipt,
        # so the tampered ranges fail the digest join first.
        rows = self.evidence_rows()
        with self.assertRaisesRegex(ValueError, 'source receipt digest mismatch'):
            contract.reconcile_static(self.plan, rows, sources,
                                      mode='synthetic-test', clock=lambda: NOW)
        # With a correctly recomputed digest, the coverage mismatch refuses.
        sources[victim.participant_id] = dict(receipt)
        rows = self.evidence_rows()
        for row in rows:
            if row.participant_id == victim.participant_id:
                object.__setattr__(row, 'source_receipt_digest', sha256(receipt))
        with self.assertRaisesRegex(ValueError, 'source range coverage mismatch'):
            contract.reconcile_static(self.plan, rows, sources,
                                      mode='synthetic-test', clock=lambda: NOW)

    def test_forged_identity_pid_refuses(self):
        rows = self.evidence_rows()
        victim = self.participant('remote')
        for row in rows:
            if row.participant_id == victim.participant_id:
                object.__setattr__(row, 'identity', replace_pid(row.identity, row.spawn.pid + 1))
        with self.assertRaisesRegex(ValueError, 'owned identity pid/start mismatch'):
            contract.reconcile_static(self.plan, rows, self.source_receipts(),
                                      mode='synthetic-test', clock=lambda: NOW)

    def test_stale_build_refuses(self):
        rows = self.evidence_rows()
        wrong = contract.DerivedBuildEvidence(
            self.manifest, 'f' * 64) if False else None
        from dataclasses import replace as _replace
        stale = _replace(self.manifest, manifest_sha256='0' * 64) if False else None
        # A mismatched executable digest cannot even construct evidence.
        with self.assertRaisesRegex(ValueError, 'derived build executable bytes mismatch'):
            contract.DerivedBuildEvidence(self.manifest, 'f' * 64)

    def test_coverage_gap_refuses(self):
        rows = self.evidence_rows()[:-1]
        with self.assertRaisesRegex(ValueError, 'participant coverage mismatch'):
            contract.reconcile_static(self.plan, rows, self.source_receipts(),
                                      mode='synthetic-test', clock=lambda: NOW)


def replace_pid(identity, pid):
    from dataclasses import replace
    return replace(identity, pid=pid)


class DynamicReconciliationTests(unittest.TestCase):
    """Genuine retained dynamic captures joined to a synthetic request."""

    @classmethod
    def setUpClass(cls):
        cls.plan = collected_plan('one-gpu')
        cls.manifest = plan_bound_manifest(cls.plan)

    def participant(self, role):
        return next(p for p in self.plan.participants if p.role == role)

    def spawn(self, participant, token='inv-302'):
        return contract.OwnedSpawnFacts(participant.participant_id, 4242, 'start-4242', token)

    def static_snapshot(self, participant, token='inv-302'):
        record = json.loads((ROUND2 / 'cpu-static.json').read_text())
        record['participant_id'] = 'observer-static-' + participant.participant_id
        record['invocation_token'] = token
        record['plan_digest'] = '0' * 64
        record['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
        return contract.parse_observation(TransportReply(0, json.dumps(record).encode()))

    def static_receipt(self, token='inv-302'):
        rows = []
        for role in ('client', 'remote'):
            p = self.participant(role)
            spawn = self.spawn(p, token)
            identity = ProcessIdentity(p.participant_id, p.host_id, p.boot_epoch,
                p.topology_epoch, spawn.pid, spawn.start, p.runtime_executable,
                p.runtime_sha256, (p.runtime_executable, '--serve'),
                freeze(dict(native=[], visible=[], environment={})), p.rpc_endpoint)
            snapshot = self.static_snapshot(p, token)
            rows.append(contract.ParticipantStaticEvidence(p.participant_id, identity,
                spawn, contract.DerivedBuildEvidence(self.manifest, self.manifest.executable_sha256),
                sha256(source_receipt(self.plan, p)), snapshot))
        sources = {p.participant_id: source_receipt(self.plan, p) for p in self.plan.participants}
        return contract.reconcile_static(self.plan, rows, sources,
                                         mode='synthetic-test', clock=lambda: NOW)

    def dynamic_rows(self, token='inv-302', pid=4242, start='start-4242'):
        rows = []
        client = self.participant('client')
        remote = self.participant('remote')
        pairs = ((client, 'cpu-dynamic.json', 'llama-server'),
                 (remote, 'rpc-dynamic.json', 'ggml-rpc-server'))
        for p, name, native in pairs:
            record = genuine_dynamic(name, native, token, pid)
            if p.role == 'client':
                # The genuine tiny-fixture captures predate server task
                # instrumentation; splice the genuine native task/response/
                # lifecycle fact shapes and re-seal before parsing.
                record['facts']['tasks'] = [dict(task_id=1, response_id='unknown')]
                record['facts']['responses'] = [dict(task_id=1)]
                lifecycle = ('server_task_new_id', 'server_task_processed',
                             'server_response_send')
                record['sequence'] = ([dict(sequence=i, event=name)
                                       for i, name in enumerate(lifecycle)]
                    + [dict(sequence=i + len(lifecycle), event=row['event'])
                       for i, row in enumerate(record['sequence'])])
                record['event_count'] = len(record['sequence'])
                record['terminal_sequence'] = record['event_count']
                record['terminal_digest'] = hashlib.sha256(canonical(
                    {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
            observation = contract.parse_observation(
                TransportReply(0, json.dumps(record).encode()))
            rows.append(contract.ParticipantDynamicEvidence(
                p.participant_id, observation, self.spawn(p, token), pid, start, native))
        return rows

    def request(self, token='inv-302', task_id=None, response_id='resp-1'):
        return contract.RequestIdentity(invocation_token=token, request_nonce='nonce-302',
                                        task_id=task_id, response_id=response_id)

    def test_complete_dynamic_path_accepts_with_genuine_captures(self):
        receipt = contract.reconcile_dynamic(self.plan, self.static_receipt(),
            self.dynamic_rows(), self.request(), mode='synthetic-test', clock=lambda: NOW)
        self.assertEqual(receipt.verdict, 'DYNAMIC_ACCEPTED')
        self.assertFalse(receipt.execution_authorized)
        self.assertGreater(dict(receipt.counts)['transfers'], 0)

    def test_wrong_token_refuses(self):
        with self.assertRaisesRegex(ValueError, 'invocation token mismatch'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(),
                self.dynamic_rows(), self.request(token='other'),
                mode='synthetic-test', clock=lambda: NOW)

    def test_claim_pid_mismatch_refuses_at_construction(self):
        rows = self.dynamic_rows()
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, 'export claim does not match owned spawn'):
            contract.ParticipantDynamicEvidence(rows[0].participant_id, rows[0].observation,
                rows[0].spawn, rows[0].claim_pid + 1, rows[0].claim_start,
                rows[0].native_participant)

    def test_dropped_stream_refuses_at_parse(self):
        rows = self.dynamic_rows()
        record = genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242)
        record['dropped_events'] = 1
        record['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
        with self.assertRaisesRegex(ValueError, 'dropped events refuse completeness'):
            contract.parse_observation(TransportReply(0, json.dumps(record).encode()))

    def test_truncated_stream_refuses_at_parse(self):
        # A gap inside the declared interval: honest re-seal, dishonest rows.
        record = genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242)
        gap = record['sequence'].pop(3)
        record['event_count'] = len(record['sequence'])
        record['terminal_sequence'] = record['event_count']
        record['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
        with self.assertRaisesRegex(ValueError, 'contiguous declared interval'):
            contract.parse_observation(TransportReply(0, json.dumps(record).encode()))

    def test_missing_get_leg_refuses(self):
        rows = self.dynamic_rows()
        client = rows[0]
        mutated = _mutate_observation(client.observation,
            lambda facts: facts.update(transfers=[r for r in facts['transfers']
                                                  if r['op'] not in ('get', 'rpc_get')]))
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, 'output custody readback missing on loader'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(),
                (replace(client, observation=mutated), rows[1]), self.request(),
                mode='synthetic-test', clock=lambda: NOW)

    def test_missing_task_facts_refuse(self):
        rows = self.dynamic_rows()
        mutated = _mutate_observation(rows[0].observation,
            lambda facts: facts.pop('tasks') if 'tasks' in facts else None)
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, 'request task facts missing'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(),
                (replace(rows[0], observation=mutated), rows[1]), self.request(),
                mode='synthetic-test', clock=lambda: NOW)

    def test_unobserved_graph_generation_refuses(self):
        rows = self.dynamic_rows()
        request = contract.RequestIdentity(invocation_token='inv-302', request_nonce='nonce-302',
                                           response_id='resp-1', graph_generations=(7,))
        with self.assertRaisesRegex(ValueError, 'graph generation not observed'):
            contract.reconcile_dynamic(self.plan, self.static_receipt(), rows, request,
                                       mode='synthetic-test', clock=lambda: NOW)


def _continuity_rows(plan):
    """Static receipt with spawn pid 4242; dynamic rows claim spawn pid 5555."""
    from inferswarm.operator.phased_observation import OwnedSpawnFacts
    manifest = plan_bound_manifest(plan)
    rows = []
    spawns = {}
    for role, name, native in (('client', 'cpu-dynamic.json', 'llama-server'),
                               ('remote', 'rpc-dynamic.json', 'ggml-rpc-server')):
        p = next(p for p in plan.participants if p.role == role)
        spawn = OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        spawns[p.participant_id] = spawn
        record = genuine_dynamic(name, native, 'inv-302', 4242)
        if role == 'client':
            record['facts']['tasks'] = [dict(task_id=1, response_id='unknown')]
            record['facts']['responses'] = [dict(task_id=1)]
            lifecycle = ('server_task_new_id', 'server_task_processed', 'server_response_send')
            record['sequence'] = ([dict(sequence=i, event=n) for i, n in enumerate(lifecycle)]
                + [dict(sequence=i + len(lifecycle), event=r['event'])
                   for i, r in enumerate(record['sequence'])])
            record['event_count'] = len(record['sequence'])
            record['terminal_sequence'] = record['event_count']
            record['terminal_digest'] = hashlib.sha256(canonical(
                {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
        observation = contract.parse_observation(TransportReply(0, json.dumps(record).encode()))
        rows.append(ParticipantDynamicEvidence(p.participant_id, observation, spawn,
                                               4242, 'start-4242', native))
    # A foreign dynamic spawn (pid 5555) breaking continuity with the static
    # receipt's spawn facts.
    wrong_client = rows[0]
    wrong = ParticipantDynamicEvidence(wrong_client.participant_id, wrong_client.observation,
        OwnedSpawnFacts(wrong_client.participant_id, 5555, 'start-5555', 'inv-302'),
        5555, 'start-5555', wrong_client.native_participant)
    static = _static_receipt_for(plan, manifest, spawns)
    return static, (wrong, rows[1])


def _static_receipt_for(plan, manifest, spawns):
    static_rows = []
    for p in plan.participants:
        spawn = spawns[p.participant_id]
        identity = ProcessIdentity(p.participant_id, p.host_id, p.boot_epoch,
            p.topology_epoch, spawn.pid, spawn.start, p.runtime_executable,
            p.runtime_sha256, (p.runtime_executable, '--serve'),
            freeze(dict(native=[], visible=[], environment={})), p.rpc_endpoint)
        snapshot = json.loads((ROUND2 / 'cpu-static.json').read_text())
        snapshot['participant_id'] = 'observer-static-' + p.participant_id
        snapshot['invocation_token'] = 'inv-302'
        snapshot['plan_digest'] = '0' * 64
        snapshot['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in snapshot.items() if k != 'terminal_digest'})).hexdigest()
        observation = contract.parse_observation(TransportReply(0, json.dumps(snapshot).encode()))
        static_rows.append(contract.ParticipantStaticEvidence(p.participant_id, identity,
            spawn, contract.DerivedBuildEvidence(manifest, manifest.executable_sha256),
            sha256(source_receipt(plan, p)), observation))
    sources = {p.participant_id: source_receipt(plan, p) for p in plan.participants}
    return contract.reconcile_static(plan, static_rows, sources,
                                     mode='synthetic-test', clock=lambda: NOW)


def _mutate_observation(observation, mutate):
    """Re-seal a parsed observation with mutated facts; honest tampering."""
    from dataclasses import fields as _fields
    record = {f.name: getattr(observation, f.name) for f in _fields(observation)}
    record['sequence'] = [dict(row) for row in observation.sequence]
    record['facts'] = json.loads(json.dumps(thaw(observation.facts)))
    mutate(record['facts'])
    record['terminal_digest'] = hashlib.sha256(canonical(
        {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
    return contract.parse_observation(TransportReply(0, json.dumps(record).encode()))


class RecordingIdentityReader(ProcIdentityReader):
    """Recording /proc identity seam; independently returns observed facts."""

    def __init__(self, observations=None, failures=None):
        self.observations = observations or {}
        self.failures = failures or {}

    def read(self, participant, pid, *, expected_executable, expected_sha256,
             expected_argv, visibility_environment=()):
        key = (participant.participant_id, pid)
        if key in self.failures:
            raise self.failures[key]
        observed = self.observations.get(key)
        if observed is None:
            observed = dict(exe=expected_executable, argv=list(expected_argv),
                            sha256=expected_sha256, start='start-%d' % pid,
                            environ={})
        # Faithful to the production reader: independent observations are
        # compared against the frozen expectations, mismatches refuse.
        if observed['exe'] != expected_executable:
            raise CollectorError(f'identity executable mismatch ({participant.participant_id})')
        if tuple(observed['argv']) != tuple(expected_argv):
            raise CollectorError(f'identity argv mismatch ({participant.participant_id})')
        if observed['sha256'] != expected_sha256:
            raise CollectorError(f'identity executable bytes mismatch ({participant.participant_id})')
        return ProcessIdentity(participant.participant_id, participant.host_id,
            participant.boot_epoch, participant.topology_epoch, pid,
            observed['start'], observed['exe'], observed['sha256'],
            tuple(observed['argv']), freeze(dict(native=[], visible=[],
            environment={k: v for k, v in observed['environ'].items()
                         if k in ('IS301_EXPORT_DIR', 'IS301_OBSERVE')})),
            participant.rpc_endpoint)


class CollectorTests(unittest.TestCase):
    """The real collector against a recording virtual-host tree."""

    @classmethod
    def setUpClass(cls):
        cls.plan = collected_plan('one-gpu')
        cls.manifest_body = build_manifest_body()
        cls.executable = (ROUND2 / 'native-export-claim.build-manifest.json').read_bytes()

    def participant(self, role):
        return next(p for p in self.plan.participants if p.role == role)

    def tree_with_build(self, manifest=None, executable=None, with_static=True):
        tree = VirtualHostTree()
        body = self.manifest_body if manifest is None else manifest
        body = dict(body)
        if executable is None:
            executable = b'synthetic-observer-binary'
        body['executable_sha256'] = hashlib.sha256(executable).hexdigest()
        from inferswarm.operator.phased_observation import parse_build_manifest
        manifest = parse_build_manifest(body)
        addr = self.participant('client').execution_address
        tree.put(addr, '/opt/observer/llama-server.build-manifest.json', body)
        tree.put(addr, '/opt/observer/llama-server', executable)
        if with_static:
            export = '/synthetic/exports-client'
            snapshot = json.loads((ROUND2 / 'cpu-static.json').read_text())
            snapshot['participant_id'] = 'observer-static-x'
            snapshot['invocation_token'] = 'inv-302'
            snapshot['plan_digest'] = '0' * 64
            snapshot['terminal_digest'] = hashlib.sha256(canonical(
                {k: v for k, v in snapshot.items() if k != 'terminal_digest'})).hexdigest()
            tree.put(addr, export + '/observer-0000.json', snapshot)
            tree.put_dir(addr, export, ['observer-0000.json'])
        return tree, manifest

    def test_collect_static_authenticates_bytes(self):
        tree, manifest = self.tree_with_build()
        transport = RecordingCollectorTransport(tree)
        collector = NativeObserverCollector(transport, RecordingIdentityReader())
        p = self.participant('client')
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        evidence = collector.collect_static(p, spawn,
            '/opt/observer/llama-server.build-manifest.json', '/opt/observer/llama-server',
            'a' * 64, expected_argv=(p.runtime_executable, '--serve'),
            export_dir='/synthetic/exports-client')
        self.assertEqual(evidence.build.manifest.manifest_sha256, manifest.manifest_sha256)
        self.assertIsNotNone(evidence.identity)

    def test_identity_reader_mismatch_refuses_instead_of_echoing(self):
        tree, _ = self.tree_with_build()
        p = self.participant('client')
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        # An independent observation reporting a foreign image must refuse,
        # never fall back to the configured executable digest.
        reader = RecordingIdentityReader(observations={
            (p.participant_id, 4242): dict(exe='/bin/false', argv=['/bin/false'],
                sha256='f' * 64, start='start-4242', environ={})})
        collector = NativeObserverCollector(RecordingCollectorTransport(tree), reader)
        with self.assertRaisesRegex(CollectorError, 'identity executable mismatch'):
            collector.collect_static(p, spawn,
                '/opt/observer/llama-server.build-manifest.json', '/opt/observer/llama-server',
                'a' * 64, expected_argv=(p.runtime_executable, '--serve'),
                export_dir='/synthetic/exports-client')

    def test_tampered_executable_refuses(self):
        tree, manifest = self.tree_with_build()
        addr = self.participant('client').execution_address
        tree.files[addr]['/opt/observer/llama-server'] = b'tampered'
        collector = NativeObserverCollector(RecordingCollectorTransport(tree),
                                            RecordingIdentityReader())
        p = self.participant('client')
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'executable bytes do not match manifest'):
            collector.collect_static(p, spawn,
                '/opt/observer/llama-server.build-manifest.json', '/opt/observer/llama-server',
                'a' * 64, expected_argv=(p.runtime_executable, '--serve'))

    def test_claim_owner_mismatch_refuses(self):
        tree, _ = self.tree_with_build()
        p = self.participant('client')
        export = '/synthetic/lease/token/exports-client'
        tree.put(p.execution_address, export + '/is301-claim',
                 '4242\nstart-4242\nllama-server\n'.encode())
        envelope = genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242)
        tree.put(p.execution_address, export + '/llama-server-0000.json', envelope)
        tree.put_dir(p.execution_address, export, ['is301-claim', 'llama-server-0000.json'])
        collector = NativeObserverCollector(RecordingCollectorTransport(tree))
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        evidence = collector.collect_dynamic(p, spawn, export, self.plan.digest, 'inv-302',
                                              NATIVE_LABELS['client'])
        self.assertEqual(evidence.native_participant, 'llama-server')
        # Wrong pid in claim refuses.
        tree.put(p.execution_address, export + '/is301-claim',
                 '9999\nstart-4242\nllama-server\n'.encode())
        with self.assertRaisesRegex(CollectorError, 'claim owner mismatch'):
            collector.collect_dynamic(p, spawn, export, self.plan.digest, 'inv-302',
                                      NATIVE_LABELS['client'])

    def test_two_envelopes_refuse(self):
        tree, _ = self.tree_with_build()
        p = self.participant('client')
        export = '/synthetic/lease/token/exports-client'
        tree.put(p.execution_address, export + '/is301-claim',
                 '4242\nstart-4242\nllama-server\n'.encode())
        tree.put(p.execution_address, export + '/llama-server-0000.json',
                 genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242))
        tree.put(p.execution_address, export + '/llama-server-0001.json',
                 genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242))
        tree.put_dir(p.execution_address, export, ['is301-claim', 'llama-server-0000.json',
                                                   'llama-server-0001.json'])
        collector = NativeObserverCollector(RecordingCollectorTransport(tree))
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'exactly one dynamic envelope'):
            collector.collect_dynamic(p, spawn, export, self.plan.digest, 'inv-302',
                                      NATIVE_LABELS['client'])

    def test_foreign_nonzero_plan_digest_refuses(self):
        tree, _ = self.tree_with_build()
        p = self.participant('client')
        export = '/synthetic/lease/token/exports-client'
        tree.put(p.execution_address, export + '/is301-claim',
                 '4242\nstart-4242\nllama-server\n'.encode())
        tree.put(p.execution_address, export + '/llama-server-0000.json',
                 genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242))
        tree.put_dir(p.execution_address, export, ['is301-claim', 'llama-server-0000.json'])
        collector = NativeObserverCollector(RecordingCollectorTransport(tree))
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        # The genuine envelope carries the zero placeholder: a controller
        # presenting a nonzero plan digest must still refuse because the
        # envelope cannot be bound to it.
        envelope = genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', 4242)
        envelope['plan_digest'] = 'c' * 64
        envelope['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in envelope.items() if k != 'terminal_digest'})).hexdigest()
        tree.put(p.execution_address, export + '/llama-server-0000.json', envelope)
        with self.assertRaisesRegex(CollectorError, 'plan digest mismatch'):
            collector.collect_dynamic(p, spawn, export, self.plan.digest, 'inv-302',
                                      NATIVE_LABELS['client'])


class CollectedRunnerTests(unittest.TestCase):
    """The actual runner through the collected /2 path with recording seams.

    Only the collector/identity seams are recording doubles; the runner,
    lease manager, reconcilers and receipt construction are the real ones.
    """

    @classmethod
    def setUpClass(cls):
        cls.plan = collected_plan('one-gpu')

    def test_one_post_static_before_dynamic_after_and_owned_cleanup(self):
        h = RecordingRunnerHarness(self.plan)
        h.collect_dynamic_marker = []
        original = h.collect_dynamic
        def collect_dynamic(*args, **kwargs):
            h.collect_dynamic_marker.append(h.posts)
            return original(*args, **kwargs)
        h.collect_dynamic = collect_dynamic
        result = h.runner().run(self.plan)
        self.assertEqual(h.posts, 1)
        # Both participants collected after the single POST.
        self.assertEqual(h.collect_dynamic_marker, [1, 1])
        self.assertEqual(result['static_receipt']['verdict'], 'STATIC_ADMITTED')
        self.assertEqual(result['dynamic_receipt']['verdict'], 'DYNAMIC_ACCEPTED')
        self.assertIs(result['execution_authorized'], False)
        self.assertTrue(all(row['lease'] == 'released' for row in result['cleanup'].values()))

    def test_static_refusal_means_zero_posts(self):
        h = RecordingRunnerHarness(self.plan)
        h.static_error = ValueError('static reconciliation: derived build executable identity mismatch')
        runner = h.runner()
        with self.assertRaisesRegex(ValueError, 'derived build executable identity mismatch'):
            runner.run(self.plan)
        self.assertEqual(h.posts, 0)
        self.assertTrue(all(row['lease'] == 'released' for row in runner.last_cleanup.values()))

    def test_dynamic_refusal_reports_executed_but_rejected(self):
        h = RecordingRunnerHarness(self.plan)
        h.dynamic_error = ValueError('dynamic reconciliation: request task facts missing')
        with self.assertRaisesRegex(ValueError, 'request task facts missing'):
            h.runner().run(self.plan)
        self.assertEqual(h.posts, 1)

    def test_profile_expiry_during_dynamic_collection_refuses_output(self):
        from datetime import timedelta
        h = RecordingRunnerHarness(self.plan)
        runner = h.runner()
        def collect_dynamic(p, spawn, export_dir, plan_digest, token, native_label):
            # Profiles expire while the controller blocks collecting evidence.
            runner.clock = lambda: NOW + timedelta(days=1)
            return h._dynamic(p, spawn, native_label)
        h.collect_dynamic = collect_dynamic
        with self.assertRaisesRegex(ValueError, 'expired|stale'):
            runner.run(self.plan)
        self.assertEqual(h.posts, 1)

    def test_foreign_claim_spawn_continuity_refuses(self):
        static, rows = _continuity_rows(self.plan)
        request = contract.RequestIdentity(invocation_token='inv-302', request_nonce='n',
                                           response_id='resp-1')
        with self.assertRaisesRegex(ValueError,
                                    'spawn continuity with static admission mismatch'):
            contract.reconcile_dynamic(self.plan, static, rows, request,
                                       mode='synthetic-test', clock=lambda: NOW)

    def test_resealed_foreign_manifest_refuses_in_collector(self):
        # A self-consistent but foreign overlay identity must refuse: the
        # derived build must descend from the retained authenticated #301
        # producer artifacts.
        tree = VirtualHostTree()
        body = dict(build_manifest_body())
        body['patch_sha256'] = 'e' * 64
        body['executable_sha256'] = hashlib.sha256(b'x').hexdigest()
        p = next(p for p in self.plan.participants if p.role == 'client')
        tree.put(p.execution_address, '/opt/observer/llama-server.build-manifest.json', body)
        tree.put(p.execution_address, '/opt/observer/llama-server', b'x')
        collector = NativeObserverCollector(RecordingCollectorTransport(tree),
                                            RecordingIdentityReader())
        with self.assertRaisesRegex(CollectorError, 'patch identity is not the retained'):
            collector.collect_build(p, '/opt/observer/llama-server.build-manifest.json',
                                    '/opt/observer/llama-server')


class RecordingRunnerHarness:
    """Actual OperatorRunner over the recording lifecycle with a recording
    collector; source receipts come from the synthetic fixture builder."""

    def __init__(self, plan, token='inv-302-runner'):
        from tests.test_issue299_bindings import source_receipt as _sr
        self.plan = plan
        self.events = []
        self.transport = RecordingLifecycle(self.events)
        from inferswarm.operator.lifecycle import LeaseManager
        self.manager = LeaseManager(self.transport, token, stop_timeout=0)
        self.sources = {p.participant_id: _sr(plan, p) for p in plan.participants}
        self.static_error = None
        self.dynamic_error = None
        self.posts = 0
        self.static_before_post = None
        self.dynamic_after_post = None
        self.clock = lambda: NOW

    def verify(self, p, plan, fnv_binary=None):
        import copy as _copy
        return _copy.deepcopy(self.sources[p.participant_id])

    def collect_static(self, p, spawn, manifest_path, executable_path, digest, *,
                       expected_argv, export_dir=None):
        if self.static_error: raise self.static_error
        return self._evidence(p, spawn, expected_argv)

    def collect_dynamic(self, p, spawn, export_dir, plan_digest, token, native_label):
        if self.dynamic_error:
            self.dynamic_error_runtime = self.dynamic_error
            raise self.dynamic_error
        return self._dynamic(p, spawn, native_label)

    def _evidence(self, p, spawn, expected_argv=None):
        manifest = plan_bound_manifest(self.plan)
        identity = ProcessIdentity(p.participant_id, p.host_id, p.boot_epoch,
            p.topology_epoch, spawn.pid, spawn.start, p.runtime_executable,
            p.runtime_sha256, tuple(expected_argv) if expected_argv else (p.runtime_executable, '--serve'),
            freeze(dict(native=[], visible=[], environment={})), p.rpc_endpoint)
        snapshot = json.loads((ROUND2 / 'cpu-static.json').read_text())
        snapshot['participant_id'] = 'observer-static-' + p.participant_id
        snapshot['invocation_token'] = spawn.invocation_token
        snapshot['plan_digest'] = '0' * 64
        snapshot['terminal_digest'] = hashlib.sha256(canonical(
            {k: v for k, v in snapshot.items() if k != 'terminal_digest'})).hexdigest()
        observation = contract.parse_observation(TransportReply(0, json.dumps(snapshot).encode()))
        return contract.ParticipantStaticEvidence(p.participant_id, identity, spawn,
            contract.DerivedBuildEvidence(manifest, manifest.executable_sha256),
            sha256(self.sources[p.participant_id]), observation)

    def _dynamic(self, p, spawn, native_label):
        name = 'cpu-dynamic.json' if p.role == 'client' else 'rpc-dynamic.json'
        record = genuine_dynamic(name, native_label, spawn.invocation_token, spawn.pid)
        if p.role == 'client':
            record['facts']['tasks'] = [dict(task_id=1, response_id='unknown')]
            record['facts']['responses'] = [dict(task_id=1)]
            lifecycle = ('server_task_new_id', 'server_task_processed', 'server_response_send')
            record['sequence'] = ([dict(sequence=i, event=name_) for i, name_ in enumerate(lifecycle)]
                + [dict(sequence=i + len(lifecycle), event=row['event'])
                   for i, row in enumerate(record['sequence'])])
            record['event_count'] = len(record['sequence'])
            record['terminal_sequence'] = record['event_count']
            record['terminal_digest'] = hashlib.sha256(canonical(
                {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
        observation = contract.parse_observation(TransportReply(0, json.dumps(record).encode()))
        return contract.ParticipantDynamicEvidence(p.participant_id, observation, spawn,
            spawn.pid, spawn.start, native_label)

    def tunnel(self, *args):
        return self, 18080

    def poll(self): return None
    def terminate(self): pass
    def wait(self, timeout=None): return 0

    def get(self, url, timeout):
        return {'status': 'ok'}

    def post(self, url, data, timeout):
        self.posts += 1
        self.static_before_post = self.static_before_post is not None or True
        return {'id': 'reply-302', 'choices': [{'message': {'content': 'fixture'}, 'finish_reason': 'stop'}],
                'usage': {'completion_tokens': 1}}

    def runner_ref(self):
        return self._runner

    def runner(self, **overrides):
        from inferswarm.operator.phased_observation import reconcile_static, reconcile_dynamic
        kwargs = dict(collector=self, static_reconciler=reconcile_static,
                      dynamic_reconciler=reconcile_dynamic,
                      observation_mode='synthetic-test', clock=self.clock)
        kwargs.update(overrides)
        self._runner = OperatorRunner(self, self.manager, self, self.tunnel,
                                      pause=lambda _: None, **kwargs)
        return self._runner


if __name__ == '__main__':
    unittest.main()
