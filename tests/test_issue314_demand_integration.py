"""Issue #314 focused regressions: opt-in demand capture under the guarded 41/45 path.

Synthetic CPU coverage only: argument parity construction, option refusal,
default-off behavior, per-request binding, capacity/drop reporting through the
real #312 reducer fixtures, and the durable-export/interrupted-cleanup contract
of the session evidence flow. No native build, worker, model or GPU runs here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inferswarm.operator.q8_demand import (
    FIXED_OPTIONS, demand_client_argv, validate_demand)
from inferswarm.operator.q8_session import validate_session
from inferswarm.operator.q8_experiment import ExperimentalLeaseManager
from inferswarm.operator.lifecycle import LeaseManager

TOOL = ROOT / 'tools/native-moe-overlap'
A64, B64, C64 = 'a' * 64, 'b' * 64, 'c' * 64


def session_raw(demand=None, requests=None):
    body = {'schema': 'q8-two-cuda-session/1',
            'requests': requests if requests is not None else [
                {'warmup': True, 'body': {'prompt': 'warm', 'n_predict': 2,
                    'temperature': 0, 'seed': 1, 'stream': False, 'cache_prompt': False}},
                {'warmup': False, 'body': {'prompt': 'measure me', 'n_predict': 4,
                    'temperature': 0, 'seed': 1, 'stream': False, 'cache_prompt': False}}]}
    if demand is not None:
        body['demand'] = demand
    return body


def demand_block(**over):
    block = {'client_manifest_path': '/reviewed/native-demand.build-manifest.json',
             'client_executable_path': '/reviewed/native-demand',
             'client_sha256': B64, 'max_rows': 5000, 'model_sha256': A64,
             'native_build_sha256': C64, 'request_index': 2,
             'decode_steps': 8, 'prompt': 'measure me'}
    block.update(over)
    return block


class DemandValidationTests(unittest.TestCase):
    def validated(self, raw):
        session = validate_session(raw)
        return validate_demand(raw, session), session

    def test_default_off_is_inert(self):
        raw = session_raw()
        profile, session = self.validated(raw)
        self.assertIsNone(profile)
        # The frozen session digest is unchanged by the absence of the block.
        self.assertNotIn('demand', session.payload())

    def test_valid_block_binds_measured_request_and_prompt(self):
        profile, session = self.validated(session_raw(demand=demand_block()))
        self.assertEqual(profile.request_index, 2)
        self.assertEqual(profile.prompt, 'measure me')
        workload = profile.workload_sha256(session.digest)
        self.assertEqual(workload, hashlib.sha256(json.dumps(
            [session.digest, 2, profile.prompt_sha256],
            separators=(',', ':')).encode()).hexdigest())
        # Warmup/measured cannot mix: binding a warmup request refuses.
        with self.assertRaisesRegex(ValueError, 'warmup'):
            self.validated(session_raw(demand=demand_block(request_index=1, prompt='warm')))
        # The capture prompt must equal its measured request prompt.
        with self.assertRaisesRegex(ValueError, 'must equal'):
            self.validated(session_raw(demand=demand_block(prompt='different')))

    def test_unsupported_fields_digests_and_bounds_refuse(self):
        for mutate, pattern in (
                (dict(request_index=0), 'request_index'),
                (dict(max_rows=0), 'max_rows'),
                (dict(decode_steps=257), 'decode_steps'),
                (dict(client_sha256='Z' * 64), 'SHA-256'),
                (dict(model_sha256=''), 'SHA-256'),
                (dict(prompt=''), 'prompt'),
                (dict(client_manifest_path='relative/path'), 'absolute'),
                (dict(client_manifest_path='/a/../b'), 'absolute')):
            with self.subTest(mutate=mutate):
                with self.assertRaisesRegex(ValueError, pattern):
                    self.validated(session_raw(demand=demand_block(**mutate)))
        bad = demand_block(); bad['extra'] = 1
        with self.assertRaisesRegex(ValueError, 'exact'):
            self.validated(session_raw(demand=bad))

    def test_declared_digest_must_match_reviewed_manifest_when_supplied(self):
        raw = session_raw(demand=demand_block())
        session = validate_session(raw)
        body = {'executable_sha256': B64}
        self.assertIsNotNone(validate_demand(raw, session, client_manifest_body=body))
        with self.assertRaisesRegex(ValueError, 'reviewed manifest'):
            validate_demand(raw, session, client_manifest_body={'executable_sha256': 'd' * 64})


class DemandArgumentParityTests(unittest.TestCase):
    def argv(self):
        profile, session = None, None
        raw = session_raw(demand=demand_block())
        session = validate_session(raw)
        profile = validate_demand(raw, session)
        return demand_client_argv(profile,
            rpc_endpoints=['worker.example:5000', 'worker.example:5001'],
            model_path='/srv/models/q8/model.gguf', file_type=15,
            workload_sha256=C64, model_source='qwen3.8', model_revision='r1',
            representation='Q8_0', context=4096, batch=2048, microbatch=512,
            threads=8)

    def test_exact_41_45_argument_propagation(self):
        argv = self.argv()
        def value(flag):
            return argv[argv.index(flag) + 1]
        self.assertEqual(value('--rpc-endpoints'), 'worker.example:5000,worker.example:5001')
        self.assertEqual(value('--devices'), 'RPC0,RPC1')
        self.assertEqual(value('--gpu-layers'), '8')
        self.assertEqual(value('--tensor-split'), '4,4')
        self.assertEqual(value('--split-mode'), 'layer')
        self.assertEqual(value('--fit'), 'off')
        self.assertEqual(value('--lazy-mode'), 'on')
        self.assertEqual(value('--load-mode'), 'none')
        self.assertEqual(value('--kv-offload'), 'on')
        self.assertEqual(value('--no-op-offload'), 'on')
        self.assertEqual(value('--cache-type-k'), 'f16')
        self.assertEqual(value('--cache-type-v'), 'f16')
        self.assertEqual(value('--flash-attn'), 'off')
        self.assertEqual(value('--no-kv-unified'), 'on')
        self.assertEqual(value('--ctx-size'), '4096')
        self.assertEqual(value('--batch-size'), '2048')
        self.assertEqual(value('--ubatch-size'), '512')
        self.assertEqual(value('--parallel'), '1')
        self.assertEqual(value('--threads'), '8')
        self.assertEqual(value('--cohort'), 'profiling')
        self.assertEqual(argv.count('--model'), 1)
        # Parity constants mirror the accepted two-gpu lowering.
        self.assertEqual((FIXED_OPTIONS['gpu_layers'], FIXED_OPTIONS['tensor_split']),
                         (8, (4, 4)))

    def test_operator_mode_source_refuses_unsupported_native_options(self):
        """The composed client itself refuses non-41/45 operator settings."""
        source = (TOOL / 'demand_cli.cpp').read_text()
        for fragment in (
                '"--gpu-layers must be 8 for the 41/45 two-gpu lowering"',
                '"--tensor-split must be 4,4 for the 41/45 two-gpu lowering"',
                '"--devices must be RPC0,RPC1 in endpoint order"',
                '"unsupported profiling option: "'):
            self.assertIn(fragment, source)
        # Unknown flags are refused, never silently stored.
        self.assertIn('const std::set<std::string> accepted', source)


class DemandCLIOptionRefusalTests(unittest.TestCase):
    """Drive the real demand capture seam (not the CLI) for phase/position."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.tmp.name) / 'demand-fixture'
        subprocess.run(['c++', '-std=c++17', '-O0', '-I', str(TOOL),
                        str(TOOL / 'demand_fixture.cpp'),
                        str(TOOL / 'demand.cpp'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self, scenario):
        result = subprocess.run([str(self.binary), scenario],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def expected(self):
        return {'model_source': 'qwen3.8', 'model_revision': 'r38', 'model_sha256': A64,
                'representation': 'Q8', 'native_source': 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4',
                'native_build_sha256': B64, 'workload_sha256': C64}

    def test_per_request_phase_and_position_mapping_preserved(self):
        # Two-token prefill: early layers retain all prompt positions, the
        # final layer only the last output position, decode continues after.
        capture = self.fixture('prefill-last')
        early, final = capture['rows'][:2]
        self.assertEqual(early['token_positions'], [0, 1])
        self.assertEqual(final['token_positions'], [1])
        self.assertEqual([r['token_positions'] for r in capture['rows'][2:]], [[2], [2]])
        report = self.summary(capture)
        self.assertTrue(report['coverage']['complete'])
        self.assertEqual(report['coverage']['expected_token_rows'], 5)

    def test_capacity_and_drops_are_reported_not_hidden(self):
        capture = self.fixture('bounded')
        report = self.summary(capture)
        self.assertFalse(report['coverage']['complete'])
        self.assertEqual(report['coverage']['dropped_rows'], 2)
        self.assertEqual(report['coverage']['missing_layers'], [1])
        capture = self.fixture('byte-budget')
        report = self.summary(capture)
        self.assertFalse(report['coverage']['complete'])
        self.assertEqual(report['coverage']['retained_rows'] + report['coverage']['dropped_rows'],
                         report['coverage']['observed_rows'])

    def summary(self, capture):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'is314_summarize', TOOL / 'summarize_demand.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.summarize(capture, self.expected())


class DemandSessionFlowTests(unittest.TestCase):
    """Guarded-session integration contract with a fake transport."""

    def test_outcome_reporting_keeps_observer_and_demand_separate(self):
        from inferswarm.operator.q8_session import SystemdSessionGuard
        guard = SimpleNamespace()
        # Direct method binding on a minimally constructed guard instance.
        real = SystemdSessionGuard._demand_outcome
        self.assertEqual(real(guard, {}), 'disabled')
        self.assertEqual(real(guard, {'demand_capture': {'export_status': 'retained'}}), 'EXPORTED')
        self.assertEqual(real(guard, {'demand_capture': {'export_status': 'missing'}}),
                         'COLLECTION-MISSING')
        self.assertEqual(real(guard, {'demand_capture': {}}), 'NO-EXPORT')

    def test_demand_spawn_uses_coordinator_cap_and_owned_name(self):
        caps = {}

        class Transport:
            def call(self, address, payload):
                if payload['action'] == 'spawn':
                    caps[payload['name']] = payload.get('supervision', {})
                    return {'pid': 7, 'start': '123', 'token': payload['token']}
                if payload['action'] in ('stop', 'release'):
                    return {'lease': 'released', 'signal': 'TERM'}
                raise AssertionError(payload['action'])

        class Commands:
            def run(self, *args, **kwargs):
                return ''

        manager = ExperimentalLeaseManager(Transport(), 'tok')
        manager.leases['addr'] = '/tmp/lease-root'
        manager.owned['addr'] = {}
        manager.configure(SimpleNamespace(checkpoint=lambda: None, remaining=lambda: 600,
                                          envelope=SimpleNamespace(gpu_bindings=())))
        manager.slices['addr'] = 'owned.slice'
        manager.spawn('addr', 'demand', ['/bin/true'])
        self.assertIn('demand', caps)
        # Demand uses the coordinator aggregate cap, exactly like the client.
        manager.spawn('addr', 'client', ['/bin/true'])
        self.assertEqual(caps['demand']['memory_max_bytes'],
                         caps['client']['memory_max_bytes'])
        # Any other ancillary name is still refused.
        with self.assertRaisesRegex(ValueError, 'ancillary'):
            manager.spawn('addr', 'helper', ['/bin/true'])

    def test_lifecycle_admits_only_the_finite_process_names(self):
        source = (ROOT / 'inferswarm/operator/lifecycle.py').read_text()
        self.assertIn("('client','rpc','rpc0','rpc1','demand')", source)


class DemandExportDurabilityTests(unittest.TestCase):
    """Durable export through the real private evidence store."""

    def test_success_path_retains_export_and_manifest_digest(self):
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'evidence'
            store = DurableEvidenceStore.create(root, 'token-1',
                config_sha256=A64, request_sha256=C64)
            export = {'schema': 'native-demand/1', 'rows': [],
                      'observed_rows': 0, 'dropped_rows': 0, 'capacity_rows': 1}
            self.assertTrue(store.save_session_json('demand-export.json', export))
            summary = store.finalize()
            self.assertTrue(summary['complete'], summary)
            retained = json.loads((root / 'demand-export.json').read_text())
            self.assertEqual(retained, export)
            manifest = json.loads((root / 'MANIFEST.json').read_text())
            row = next(r for r in manifest['session_artifacts']
                       if r['target'] == 'demand-export.json')
            self.assertEqual(row['sha256'], hashlib.sha256(
                json.dumps(export, sort_keys=True, indent=1,
                           allow_nan=False).encode()).hexdigest())

    def test_interrupted_collection_keeps_partial_manifest_honest(self):
        """An interrupted demand capture never yields a complete ledger."""
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'evidence'
            store = DurableEvidenceStore.create(root, 'token-2',
                config_sha256=A64, request_sha256=C64)
            store.register_attempt('demand', 'host-a', '/exports/demand',
                                   '/logs/demand.log')
            # The process was registered but collection never ran (interrupt);
            # finalize must report the omission instead of claiming complete.
            store.register_process('demand', 'host-a', 42, '7')
            summary = store.finalize()
            self.assertFalse(summary['complete'], summary)
            manifest = json.loads((root / 'MANIFEST.json').read_text())
            self.assertIn('omitted_processes', json.dumps(manifest))


if __name__ == '__main__':
    unittest.main()
