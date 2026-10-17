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
import threading
import time
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
                '"unsupported profiling option: "',
                # Operator-only flags never silently drop outside the block.
                '"option requires the operator parity block: "'):
            self.assertIn(fragment, source)
        # Unknown flags are refused, never silently stored.
        self.assertIn('const std::set<std::string> accepted', source)
        # The legacy path keeps main's optional --gpu-layers behavior.
        self.assertIn('params.n_gpu_layers = (int)number(args.at("--gpu-layers"), 512)', source)


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
        retained = {'status': 'FINISHED', 'export_status': 'retained'}
        self.assertEqual(real(guard, {'demand_capture': retained}), 'EXPORTED')
        # A captured export without retained bytes is NOT a complete export.
        self.assertEqual(real(guard, {'demand_capture': {'export_status': 'retained'}}),
                         'FAILED')
        self.assertEqual(real(guard, {'demand_capture': {'export_status': 'missing'}}),
                         'COLLECTION-MISSING')
        # A nonzero demand-client exit is an honest failure state.
        self.assertEqual(real(guard, {'demand_capture': {'export_status': 'client-exit'}}),
                         'COLLECTION-CLIENT_EXIT')
        self.assertEqual(real(guard, {'demand_capture': {}}), 'FAILED')

    def test_runner_reads_parsed_manifest_not_double_decoded(self):
        """The manifest admission path uses read_json's PARSED object."""
        source = (ROOT / 'inferswarm/operator/runtime.py').read_text()
        self.assertIn('manifest=transport.read_json(client.execution_address', source)
        self.assertNotIn('json.loads(transport.read_json', source)

    def test_runner_maps_file_type_from_authenticated_plan_metadata(self):
        source = (ROOT / 'inferswarm/operator/runtime.py').read_text()
        self.assertIn('file_type=_model_file_type(plan)', source)
        self.assertIn("key == 'general.file_type'", source)
        self.assertNotIn('file_type=15', source)

    def test_runner_observes_client_host_threads_not_controller_guess(self):
        source = (ROOT / 'inferswarm/operator/runtime.py').read_text()
        self.assertIn('threads=_client_host_threads(guard,client)', source)
        self.assertIn("'getconf', 'NPROCESSORS_ONLN'", source)
        self.assertNotIn('os.sysconf', source)

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
        # Every allowlist (spawn, log, alive/inspect/stop) accepts 'demand'
        # together: a name admitted at spawn but refused at alive/stop would
        # strand the process outside lease-managed cleanup.
        self.assertEqual(source.count("('client','rpc','rpc0','rpc1','demand')"), 3)
        self.assertNotIn("('client','rpc','rpc0','rpc1')", source)

    def test_lifecycle_demands_full_lifecycle_end_to_end(self):
        """Spawn/alive/stop/release all accept 'demand' on the real lifecycle."""
        import importlib.util as ilu
        import tempfile as tf
        import time as _time
        spec = ilu.spec_from_file_location('lc_demand', ROOT / 'inferswarm/operator/lifecycle.py')
        if spec is None or spec.loader is None:
            self.fail('cannot load lifecycle module')
        lc = ilu.module_from_spec(spec); spec.loader.exec_module(lc)
        with tf.TemporaryDirectory() as td:
            root = str(Path(td) / 'lease')

            class Local:
                def call(self, address, payload):
                    return lc._onhost(payload)

            t = Local()
            t.call('h', dict(action='admit', root=root, token='tok'))
            row = t.call('h', dict(action='spawn', root=root, token='tok',
                                   name='demand', argv=['/bin/sleep', '5']))
            try:
                self.assertTrue(t.call('h', dict(action='alive', root=root,
                    token='tok', name='demand', pid=row['pid'], start=row['start']))['alive'])
                log = t.call('h', dict(action='log', root=root, token='tok', name='demand'))
                self.assertIn('text', log)
            finally:
                stopped = t.call('h', dict(action='stop', root=root, token='tok',
                                           name='demand', pid=row['pid'], start=row['start']))
                self.assertIn('signal', stopped)
                deadline = _time.monotonic() + 5
                while _time.monotonic() < deadline and t.call('h', dict(
                        action='alive', root=root, token='tok', name='demand',
                        pid=row['pid'], start=row['start']))['alive']:
                    _time.sleep(0.05)
            self.assertFalse(t.call('h', dict(action='alive', root=root,
                token='tok', name='demand', pid=row['pid'], start=row['start']))['alive'])
            self.assertEqual(t.call('h', dict(action='release', root=root,
                                              token='tok'))['lease'], 'released')

    def test_capture_runs_after_session_requests_with_client_stopped(self):
        """The pinned RPC server serves one connection; the ordinary client
        must be stopped before the demand client can connect. The stop/retire
        runs as ONE synchronized guard transition BEFORE _run_demand_capture
        and after the request loop."""
        source = (ROOT / 'inferswarm/operator/runtime.py').read_text()
        self.assertIn('demand_pending', source)
        # The synchronized handoff precedes the capture and follows the
        # request loop's phase reset.
        self.assertLess(source.index("guard.phase='cleanup'; guard.phase_index=None"),
                        source.index('guard.retire_client_for_demand('))
        self.assertLess(source.index('guard.retire_client_for_demand('),
                        source.index('demand_record=self._run_demand_capture'))
        # The retired client leaves monitoring only through the guard's
        # locked transition (no unsynchronized del of guard-visible state).
        self.assertNotIn("del self.leases.owned[client.execution_address]['client']",
                         source)
        # The runner's local row removal follows the confirmed stop.
        self.assertLess(source.index('guard.retire_client_for_demand('),
                        source.index("del rows['client']"))

    def test_failed_export_retention_downgrades_status(self):
        """A refused save_session_json (returns False) is never 'retained'."""
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        with tempfile.TemporaryDirectory() as td:
            store = DurableEvidenceStore.create(Path(td) / 'e', 'tok',
                config_sha256=A64, request_sha256=C64,
                max_total_bytes=1)  # force budget refusal
            self.assertFalse(store.save_session_json('demand-export.json',
                                                     {'x': 'y' * 100}))
            summary = store.finalize()
            self.assertFalse(summary['complete'])


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


# ---------------------------------------------------------------------------
# Third review pass (#337): monitored handoff + lifecycle response shape.
# Drives the REAL guard/monitor methods and the REAL runner demand path with
# external host operations faked (no source-string-only assertions).
# ---------------------------------------------------------------------------

from inferswarm.operator.q8_experiment import _LIMITS as _Q8_LIMITS
from inferswarm.operator.q8_experiment import ExperimentalEnvelope

_COORD_CAP = _Q8_LIMITS['coordinator_memory_max_bytes']
_WORKER_SERVICE_CAP = _Q8_LIMITS['worker_memory_max_bytes'] // 2
_WORKER_AGGREGATE_CAP = _Q8_LIMITS['worker_memory_max_bytes']


def _guard_envelope():
    return ExperimentalEnvelope(
        config_sha256=A64, request_sha256=C64,
        gpu_bindings=(('CUDA0', 'GPU-' + 'a' * 32), ('CUDA1', 'GPU-' + 'b' * 32)),
        limits=tuple(sorted(_Q8_LIMITS.items())),
        normal_admission_status='BLOCKED-UNKNOWN-ALLOCATION',
        normal_technical_feasibility='FEASIBLE',
        normal_execution_ready=False,
        unknown_allocations=('u1',))


class _ProbeCommands:
    """Answers the guard's read-only host probes with valid in-bounds values.

    Aggregate slice caps follow SystemdCampaignGuard.budget's expectation
    (remote aggregate = full worker cap, client aggregate = coordinator cap);
    per-service caps come from the spawn supervision rows themselves.
    """

    def __init__(self):
        self.tail_calls = []

    def run(self, address, argv, **kwargs):
        head = argv[0]
        if head == 'sudo' and '--property=LoadState' in argv:
            return 'LoadState=loaded\nActiveState=inactive\n'
        if head in ('sudo', 'systemctl') and 'show' in argv:
            cap = (_COORD_CAP if address == 'client-host' else _WORKER_AGGREGATE_CAP)
            return ('MemoryMax={}\nMemorySwapMax=0\nMemoryCurrent=1024\n'
                    'MemorySwapCurrent=0\nControlGroup=/{}.slice\n').format(cap, address)
        if head in ('sudo', 'systemctl', 'systemd-run'):
            return ''
        if head == 'nvidia-smi':
            if '--query-gpu=' in argv[1]:
                return ('0, GPU-' + 'a' * 32 + ', 2048, 1\n'
                        '1, GPU-' + 'b' * 32 + ', 2048, 1\n')
            return ''
        if head == 'grep':
            return 'MemAvailable: 134217728 kB\n'
        if head == 'cat':
            return 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n'
        if head == 'python3':
            return json.dumps({p: 'raw' for p in argv[3:]})
        if head == 'tail':
            self.tail_calls.append((address, argv[-1]))
            return ''
        if head == 'getconf':
            return '8\n'
        raise AssertionError(argv)


class _FakeTransport:
    """LocalTransport-shaped lifecycle fake mirroring lifecycle._onhost's
    documented action shapes (inspect returns {'unit', 'properties': {...}})."""

    def __init__(self):
        self.state = {}            # (address, name) -> spawn row + alive/exited
        self.extra = {}            # (address, name) -> {'Result': ...} override
        self.pending_death = {}    # (address, name) -> systemd Result on 1st alive
        self.refuse_inspect_after_exit = set()
        self.stop_hook = None
        self.next_pid = 100

    def call(self, address, payload):
        action = payload['action']
        if action == 'admit':
            return {'lease': 'admitted'}
        if action == 'port':
            return {'port': 'available'}
        if action == 'write':
            data = __import__('base64').b64decode(payload['data'])
            return {'written': len(data)}
        if action == 'spawn':
            name = payload['name']
            self.next_pid += 1
            row = dict(pid=self.next_pid, start='200', token=payload['token'],
                       alive=True, exited=False,
                       supervision=payload['supervision'])
            self.state[(address, name)] = row
            return dict(pid=row['pid'], start=row['start'], token=row['token'],
                        supervision=payload['supervision'])
        name = payload.get('name')
        key = (address, name)
        if action == 'alive':
            row = self.state[key]
            if key in self.pending_death and not row.get('exited'):
                result = self.pending_death.pop(key)
                row['alive'] = False
                row['exited'] = True
                row['Result'] = result
            return {'alive': bool(row.get('alive'))}
        if action == 'inspect':
            row = self.state[key]
            # A completion-read refusal is scoped to AFTER the unit exited:
            # the process_started inspection of a live unit must still work.
            if (key in self.refuse_inspect_after_exit and row.get('exited')):
                raise RuntimeError('synthetic inspect refusal')
            supervision = row['supervision']
            props = dict(
                MainPID=('0' if row.get('exited') else str(row['pid'])),
                ActiveState=('failed' if row.get('exited') and row.get('Result') != 'success' else 'active'),
                SubState=('exited' if row.get('exited') and row.get('Result') == 'success'
                          else ('failed' if row.get('exited') else 'running')),
                LoadState='loaded', RemainAfterExit=('yes' if name == 'demand' else 'no'),
                ExecMainCode=('1' if row.get('exited') else '0'),
                ExecMainStatus=('2' if row.get('Result') == 'exit-code' else '0'),
                Result=self.extra.get(key, {}).get('Result',
                                                   row.get('Result', 'success')),
                MemoryCurrent='1024', MemoryPeak='2048',
                MemorySwapCurrent='0',
                MemoryMax=str(supervision['memory_max_bytes']),
                MemorySwapMax='0',
                RuntimeMaxUSec='2h 39min 59s', KillMode='control-group',
                ControlGroup='/' + supervision['slice'] + '/' + supervision['unit'])
            return dict(unit=supervision['unit'], properties=props)
        if action == 'stop':
            if self.stop_hook is not None:
                self.stop_hook(name)
            row = self.state[key]
            row['alive'] = False
            row['exited'] = True
            return dict(signal='systemd-stop', unit=row['supervision']['unit'],
                        properties=dict(Result='success', MemorySwapCurrent='0'))
        if action == 'release':
            return {'lease': 'released'}
        raise AssertionError(action)


def _make_guard_state(commands, transport, *, with_client=True):
    """Real ExperimentalLeaseManager + SystemdSessionGuard over the fakes."""
    from inferswarm.operator.q8_experiment import ExperimentalLeaseManager
    from inferswarm.operator.q8_session import SystemdSessionGuard
    leases = ExperimentalLeaseManager(transport, 'monitor-token')
    for address in ('client-host', 'remote-host'):
        leases.leases[address] = '/tmp/lease-' + address
        leases.owned[address] = {}
    session = validate_session(session_raw())
    guard = SystemdSessionGuard(_guard_envelope(), leases, commands, session=session)
    # The focused tests wire the topology fields begin() derives and never
    # start the background monitor thread; ticks are driven explicitly.
    leases.slices = {'client-host': 'coord.slice', 'remote-host': 'work.slice'}
    guard.client = SimpleNamespace(execution_address='client-host',
                                   host_id='client-h')
    guard.remote = SimpleNamespace(execution_address='remote-host',
                                   host_id='remote-h')
    guard.uids = {a: '1000' for a in leases.leases}
    guard.gids = {a: '1000' for a in leases.leases}
    guard.execute_deadline = time.monotonic() + 3600
    guard.started = time.monotonic()
    rows = {}
    if with_client:
        rows['client'] = leases.spawn('client-host', 'client', ['/bin/true'])
    rows['rpc0'] = leases.spawn('remote-host', 'rpc0', ['/bin/true'])
    rows['rpc1'] = leases.spawn('remote-host', 'rpc1', ['/bin/true'])
    guard.process_started(rows)
    return guard, leases, rows


def _monitor_tick(guard):
    """One real monitor-loop iteration (the fixed body: tick under the lock)."""
    with guard._rows_lock:
        guard.checkpoint()
        sample = guard.resource_sample(dict(guard.rows))
    guard._samples.append(sample)
    return sample


class MonitoredDemandHandoffTests(unittest.TestCase):
    """Defect 1: monitored ownership through the client->demand handoff.

    The reviewed head stopped the ordinary client and deleted it from the
    runner rows and lease ownership, but CampaignGuard.rows kept the copy
    registered by process_started: the next monitor tick inspected the
    removed client, raised KeyError('client'), and called stop_units(),
    aborting demand capture. These drive the real guard + lease manager.
    """

    def setUp(self):
        self.commands = _ProbeCommands()
        self.transport = _FakeTransport()
        self.guard, self.leases, self.rows = _make_guard_state(
            self.commands, self.transport)

    def _register_demand(self):
        row = self.leases.spawn('client-host', 'demand', ['/bin/true'])
        rows = dict(self.guard.rows)
        rows['demand'] = row
        self.guard.process_started(rows)
        return row

    def test_monitor_advances_through_handoff_without_false_stop(self):
        """Ticks before the handoff, in the mid-state (client retired, demand
        not yet registered) and after registration: no KeyError, no false
        STOP, both workers supervised throughout, demand supervised after
        registration, and checkpoint() stays clean."""
        _monitor_tick(self.guard)
        self.assertEqual(set(self.guard.rows), {'client', 'rpc0', 'rpc1'})
        # The synchronized handoff: stop confirmed, then atomic retirement.
        self.guard.retire_client_for_demand('client-host', self.rows['client'])
        self.assertNotIn('client', self.guard.rows)
        self.assertNotIn('client', self.leases.owned['client-host'])
        # Mid-handoff tick (post-retirement, pre-registration) samples the
        # remaining supervised set without raising.
        _monitor_tick(self.guard)
        self.assertEqual(set(self.guard.rows), {'rpc0', 'rpc1'})
        # Demand registration: supervised from here on.
        self._register_demand()
        _monitor_tick(self.guard)
        self.assertEqual(set(self.guard.rows), {'rpc0', 'rpc1', 'demand'})
        self.assertIsNone(self.guard._monitor_error)
        self.guard.checkpoint()  # the campaign was NOT aborted

    def test_monitor_tick_cannot_observe_the_transition_mid_flight(self):
        """While the handoff critical section is in progress (client already
        stopped system-side, not yet retired), a concurrent monitor tick must
        block on the transition lock rather than observe the half-swapped
        state (a stopped-but-monitored client) and falsely stop the campaign."""
        stop_started = threading.Event()
        allow_removal = threading.Event()

        def hook(name):
            if name == 'client':
                stop_started.set()
                allow_removal.wait(10)

        self.transport.stop_hook = hook
        handoff = threading.Thread(
            target=self.guard.retire_client_for_demand,
            args=('client-host', self.rows['client']))
        handoff.start()
        self.assertTrue(stop_started.wait(10))
        tick_done = threading.Event()
        tick_errors = []

        def tick():
            try:
                _monitor_tick(self.guard)
            except BaseException as exc:
                tick_errors.append(exc)
            finally:
                tick_done.set()

        thread = threading.Thread(target=tick)
        thread.start()
        thread.join(1.0)
        self.assertFalse(tick_done.is_set(),
                         'monitor tick observed the half-swapped monitored set')
        allow_removal.set()
        handoff.join(10)
        thread.join(10)
        self.assertTrue(tick_done.is_set())
        self.assertEqual(tick_errors, [])
        self.assertNotIn('client', self.guard.rows)

    def test_demand_attributed_to_coordinator_host_and_cap(self):
        """The demand process is a COORDINATOR process: inspected on the
        client host under the coordinator aggregate/service cap, its log
        tailed on the client host; workers keep their worker caps."""
        self._register_demand()
        receipts = self.guard._inspect(dict(self.guard.rows))
        self.assertEqual(receipts['demand']['properties']['MemoryMax'],
                         str(_COORD_CAP))
        self.assertEqual(receipts['rpc0']['properties']['MemoryMax'],
                         str(_WORKER_SERVICE_CAP))
        self.assertEqual(receipts['rpc1']['properties']['MemoryMax'],
                         str(_WORKER_SERVICE_CAP))
        self.assertIn(('client-host', 'demand'), self.transport.state)
        self.assertNotIn(('remote-host', 'demand'), self.transport.state)
        _monitor_tick(self.guard)
        demand_log = str(Path('/tmp/lease-client-host/monitor-token') /
                         'demand.log')
        self.assertIn(('client-host', demand_log), self.commands.tail_calls)

    def test_genuine_demand_loss_stops_campaign_and_cleans_up_owned(self):
        """A demand unit dying abnormally while monitored is a real process
        loss: the monitor tick raises and the owned-unit sweep stops every
        still-owned process (client, both workers, demand)."""
        self.guard.phase = 'demand'
        self._register_demand()
        self.transport.state[('client-host', 'demand')]['alive'] = False
        self.transport.state[('client-host', 'demand')]['exited'] = True
        self.transport.state[('client-host', 'demand')]['Result'] = 'oom-kill'
        with self.assertRaisesRegex(RuntimeError, 'demand'):
            _monitor_tick(self.guard)
        self.leases.stop_units()
        stopped = {name for (_address, name), row in self.transport.state.items()
                   if row.get('exited')}
        self.assertEqual(stopped, {'client', 'rpc0', 'rpc1', 'demand'})

    def test_finished_demand_completion_is_classified_not_a_loss(self):
        """Between demand exit and monitored retirement a tick observes a
        terminal unit with an own-exit result: a classified completion, not a
        process loss; retirement keeps lease ownership for terminal cleanup."""
        self.guard.phase = 'demand'
        self._register_demand()
        self.transport.state[('client-host', 'demand')]['alive'] = False
        self.transport.state[('client-host', 'demand')]['exited'] = True
        self.transport.state[('client-host', 'demand')]['Result'] = 'success'
        _monitor_tick(self.guard)  # must not raise
        self.guard.retire_finished_demand('client-host')
        self.assertNotIn('demand', self.guard.rows)
        self.assertIn('demand', self.leases.owned['client-host'])
        _monitor_tick(self.guard)  # post-retirement tick stays clean

    def test_unloaded_wrong_unit_and_abnormal_completion_are_not_accepted(self):
        self.guard.phase = 'demand'
        self._register_demand()
        self.transport.state[('client-host', 'demand')].update(
            alive=False, exited=True, Result='success')
        original = self.transport.call
        from unittest.mock import patch
        for field, value in (('LoadState', 'not-found'), ('RemainAfterExit', 'no'),
                             ('ExecMainStatus', '2'), ('MainPID', '999'),
                             ('Result', 'timeout'), ('SubState', 'running'),
                             ('unit', 'unowned.service')):
            def inspect(address, payload):
                receipt = original(address, payload)
                if payload['action'] == 'inspect' and payload['name'] == 'demand':
                    if field == 'unit':
                        receipt['unit'] = value
                    else:
                        receipt['properties'][field] = value
                return receipt
            with self.subTest(field=field), patch.object(self.transport, 'call', side_effect=inspect):
                with self.assertRaises((RuntimeError, ValueError)):
                    _monitor_tick(self.guard)


class DemandCompletionReadbackTests(unittest.TestCase):
    """Defect 2: the runner must read the actual lifecycle response shape.

    lifecycle.py's inspect action returns {'unit', 'properties': {...}} with
    Result NESTED under properties; the reviewed head read a top-level
    'Result', classifying every successful capture unknown-exit/FAILED and
    never reaching export readback. These drive the REAL
    OperatorRunner._run_demand_capture with external reads faked.
    """

    @classmethod
    def setUpClass(cls):
        from inferswarm.operator.assigned_backing import optimized_cpu_identities
        cls.executable = b'synthetic-demand-client-bytes'
        cls.executable_sha = hashlib.sha256(cls.executable).hexdigest()
        reviewed = optimized_cpu_identities()['client']
        cls.manifest = dict(
            schema='q8-native-build-manifest/2',
            base_revision=reviewed.base_revision, base_tree=reviewed.base_tree,
            patch_sha256=reviewed.patch_sha256,
            transformed_manifest_sha256='e' * 64,
            protocol=reviewed.protocol, compiler=reviewed.compiler,
            build_options=list(reviewed.build_options),
            executable_sha256=cls.executable_sha,
            backend_libraries=[dict(name=n, sha256=d)
                               for n, d in reviewed.backend_libraries])
        cls.export = json.dumps({'schema': 'native-demand/1', 'rows': [],
                                 'observed_rows': 0, 'dropped_rows': 0,
                                 'capacity_rows': 4}).encode()
        raw = session_raw(demand=demand_block(
            client_sha256=cls.executable_sha))
        cls.profile = validate_demand(raw, validate_session(session_raw()))

    def setUp(self):
        self.commands = _ProbeCommands()
        self.transport = _FakeTransport()
        self.guard, self.leases, self.rows = _make_guard_state(
            self.commands, self.transport, with_client=False)

    def capture(self, *, result='success', refuse_export=False,
                inspect_refuses=False, completion_override=None):
        from inferswarm.operator.runtime import OperatorRunner
        from unittest.mock import patch
        runner = OperatorRunner.__new__(OperatorRunner)
        runner.leases = self.leases
        runner.pause = lambda _seconds: None
        self.guard.demand_profile = self.profile
        self.guard.phase = 'demand'
        plan = SimpleNamespace(
            strategy_options=dict(
                rpc_endpoints=['w.example:5000', 'w.example:5001'],
                source_contract='full-source-both-hosts/1'),
            model=SimpleNamespace(source_id='qwen3.8', revision='r1',
                                  representation='Q8_0'),
            workload=SimpleNamespace(context=4096, batch=2048, microbatch=512))
        client = SimpleNamespace(execution_address='client-host',
                                 source_path='/srv/models/q8/model.gguf')
        remote = SimpleNamespace(execution_address='remote-host')
        store = _StubStore(refuse={'demand-export.json'} if refuse_export else set())
        if inspect_refuses:
            self.transport.refuse_inspect_after_exit = {('client-host', 'demand')}
        elif result is None:
            self.transport.extra[('client-host', 'demand')] = {'Result': None}
        else:
            self.transport.extra[('client-host', 'demand')] = {'Result': result}
        # The unit exits with `result` during the capture wait (first alive).
        self.transport.pending_death[('client-host', 'demand')] = (
            'success' if result is None else result)
        original_call = self.transport.call

        def call(address, payload):
            receipt = original_call(address, payload)
            if (completion_override is not None and payload['action'] == 'inspect'
                    and payload['name'] == 'demand'
                    and self.transport.state[(address, 'demand')].get('exited')):
                return completion_override(receipt)
            return receipt

        class FakeCollector:
            MANIFEST_MAX_BYTES = 1 << 20
            EXECUTABLE_MAX_BYTES = 300 << 20

            def read_json(self, address, path, *, max_bytes):
                return self.manifest

            def read_bytes(self, address, path, *, max_bytes):
                if 'demand-profile' in path:
                    return self.export
                return self.executable

        FakeCollector.manifest = self.manifest
        FakeCollector.export = self.export
        FakeCollector.executable = self.executable
        source_payload = {'metadata': {'model_metadata': [
            ['general.file_type', 7]]}}
        with patch('inferswarm.operator.native_observer.collector.'
                   'SSHCollectorTransport', FakeCollector), \
             patch('inferswarm.operator.source.q8_source_payload',
                   return_value=source_payload), \
             patch.object(self.transport, 'call', side_effect=call):
            record = OperatorRunner._run_demand_capture(
                runner, plan, self.guard, dict(self.rows), {}, client, remote,
                (), store)
        return record, store

    def test_nested_success_reaches_export_readback_and_retention(self):
        record, store = self.capture(result='success')
        self.assertEqual(record['unit_result'], 'success', record)
        self.assertEqual(record['export_status'], 'retained', record)
        self.assertEqual(record['status'], 'FINISHED', record)
        self.assertEqual(record['export_sha256'],
                         hashlib.sha256(self.export).hexdigest())
        self.assertTrue(record.get('export_retained'))
        self.assertEqual(store.saved, ['demand-capture-started.json',
                                       'demand-export.json',
                                       'demand-capture-finished.json'])
        # The finished demand leaves the monitored set; lease ownership is
        # retained so terminal cleanup still stops the unit.
        self.assertNotIn('demand', self.guard.rows)
        self.assertIn('demand', self.leases.owned['client-host'])

    def test_failed_exit_never_claims_success_or_reads_export(self):
        record, store = self.capture(result='exit-code')
        self.assertEqual(record['export_status'], 'client-exit', record)
        self.assertEqual(record['status'], 'FAILED', record)
        self.assertNotIn('demand-export.json', store.saved)
        self.assertNotIn('export_retained', record)

    def test_malformed_or_missing_completion_stays_unsuccessful(self):
        # Result missing/non-string inside properties.
        record, store = self.capture(result=None)
        self.assertEqual(record['export_status'], 'unknown-exit', record)
        self.assertEqual(record['status'], 'FAILED', record)
        self.assertNotIn('demand-export.json', store.saved)
        # The inspect channel itself failing stays unsuccessful too.
        record, store = self.capture(inspect_refuses=True)
        self.assertEqual(record['export_status'], 'unknown-exit', record)
        self.assertEqual(record['status'], 'FAILED', record)
        self.assertNotIn('demand-export.json', store.saved)

    def test_abnormal_unit_result_is_a_process_loss_stopping_the_campaign(self):
        for result in ('oom-kill', 'signal', 'timeout'):
            with self.subTest(result=result):
                self.setUp()
                with self.assertRaisesRegex(RuntimeError, 'process lost'):
                    self.capture(result=result)

    def test_unloaded_wrong_unit_and_malformed_completion_never_export(self):
        for override in (
                lambda row: dict(row, unit='unowned.service'),
                lambda row: dict(row, properties=dict(row['properties'], LoadState='not-found')),
                lambda row: dict(row, properties=dict(row['properties'], ExecMainStatus='2')),
                lambda row: dict(row, properties=[]),
                lambda row: {'unit': row['unit']},
                lambda row: None):
            self.setUp()
            record, store = self.capture(completion_override=override)
            self.assertEqual(record['export_status'], 'unknown-exit', record)
            self.assertEqual(record['status'], 'FAILED', record)
            self.assertNotIn('demand-export.json', store.saved)

    def test_retention_failure_after_successful_execution_is_never_retained(self):
        record, store = self.capture(result='success', refuse_export=True)
        self.assertEqual(record['export_status'], 'retention-failed', record)
        self.assertEqual(record['status'], 'FAILED', record)
        self.assertNotIn('export_retained', record)
        self.assertIn('demand-capture-started.json', store.saved)
        self.assertIn('demand-capture-finished.json', store.saved)


class _StubStore:
    def __init__(self, refuse=None):
        self.saved = []
        self.refuse = refuse or set()

    def register_attempt(self, *args, **kwargs):
        pass

    def register_process(self, *args, **kwargs):
        pass

    def save_session_json(self, name, value):
        if name in self.refuse:
            return False
        self.saved.append(name)
        return True


class RetainedDemandLifecycleTests(unittest.TestCase):
    """Actual lifecycle launch, completion inspection and explicit cleanup.

    Only systemctl/systemd-run and /proc identity are faked; no service starts.
    The command's retention property controls whether successful exit keeps
    its receipt, rather than assuming inactive transient units stay loaded.
    """

    def test_retention_property_is_demand_only(self):
        from unittest.mock import patch
        from inferswarm.operator import lifecycle
        for name in ('client', 'rpc', 'rpc0', 'rpc1', 'demand'):
            calls = []
            def command(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0, stdout='123\n', stderr='')
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root, \
                 patch.object(lifecycle.subprocess, 'run', side_effect=command), \
                 patch.object(lifecycle, 'identity', return_value='start'):
                lifecycle._onhost(dict(action='admit', root=root, token='launch'))
                lifecycle._onhost(dict(action='spawn', root=root, token='launch',
                    name=name, argv=['/never-executed'], supervision=dict(
                        unit=name+'.service', memory_max_bytes=_COORD_CAP,
                        memory_swap_max_bytes=0, runtime_max_seconds=60)))
                argv = calls[0]
                self.assertEqual('--property=RemainAfterExit=yes' in argv, name == 'demand')
                for unchanged in ('--property=Type=simple', '--property=KillMode=control-group',
                                  '--property=MemorySwapMax=0', '--property=RuntimeMaxSec=60'):
                    self.assertIn(unchanged, argv)

    def test_unavailable_counter_never_hides_bad_receipts_or_nonzero_swap(self):
        from unittest.mock import patch
        guard, leases, _ = _make_guard_state(_ProbeCommands(), _FakeTransport(), with_client=False)
        row = leases.spawn('client-host', 'demand', ['/never-executed'])
        guard.demand_state = row
        receipt = dict(unit=row['supervision']['unit'], properties=dict(
            LoadState='loaded', ActiveState='active', SubState='exited', MainPID='0',
            RemainAfterExit='yes', Result='success', ExecMainCode='1', ExecMainStatus='0',
            MemoryMax=str(_COORD_CAP), MemorySwapMax='0',
            MemorySwapCurrent=str(2**64-1), ControlGroup=''))
        for field, value in (('unit','unowned.service'), ('LoadState','not-found'),
                             ('ExecMainStatus','2'), ('MemorySwapMax','1'),
                             ('MemorySwapCurrent','1'), ('MemorySwapCurrent','unknown')):
            bad = dict(receipt, properties=dict(receipt['properties']))
            if field == 'unit':
                bad['unit'] = value
            else:
                bad['properties'][field] = value
            cleanup = {'client-host': {'lease': 'released', 'demand': bad}}
            with self.subTest(field=field, value=value), \
                 patch.object(leases, 'cleanup_budgets', return_value={'client-host': {}}):
                with self.assertRaises((RuntimeError, ValueError)):
                    guard.after_cleanup(cleanup)

    def test_success_receipt_export_and_explicit_stop_release(self):
        from unittest.mock import patch
        from inferswarm.operator import lifecycle
        from inferswarm.operator.q8_session import SystemdSessionGuard
        from inferswarm.operator.runtime import OperatorRunner
        from inferswarm.operator.evidence_retention import DurableEvidenceStore
        DemandCompletionReadbackTests.setUpClass()
        fixture = DemandCompletionReadbackTests
        state = dict(exited=False, retained=False, loaded=False, identities=0)
        events = []
        unit = 'inferswarm-q8-313-retained-demand.service'
        fields = dict(MainPID='123', ActiveState='active', SubState='running',
            LoadState='loaded', RemainAfterExit='yes', Result='success',
            ExecMainCode='0', ExecMainStatus='0', MemoryCurrent='1024', MemoryPeak='2048',
            MemorySwapCurrent='0', MemoryMax=str(_COORD_CAP), MemorySwapMax='0',
            RuntimeMaxUSec='60s', KillMode='control-group', ControlGroup='/coord.slice/'+unit)

        def command(argv, **kwargs):
            if argv[2] == 'systemd-run':
                state['retained'] = '--property=RemainAfterExit=yes' in argv
                state['loaded'] = True
                events.append('spawn')
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            if argv[3] == 'stop':
                if not state['loaded']:
                    return SimpleNamespace(returncode=5, stdout='', stderr='Unit not loaded')
                events.append('stop')
                state['loaded'] = False
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            if '--value' in argv:
                return SimpleNamespace(returncode=0, stdout='123\n', stderr='')
            props = dict(fields)
            if state['exited']:
                # systemd prunes empty cgroups even for active/exited units;
                # retain the result, with unavailable live counters honest.
                props.update(MainPID='0', ActiveState='active', SubState='exited', ExecMainCode='1',
                    MemoryCurrent=str(2**64-1), MemorySwapCurrent=str(2**64-1), ControlGroup='')
            if not state['loaded']:
                props.update(LoadState='not-found', MainPID='0', ActiveState='inactive',
                             SubState='dead', RemainAfterExit='no', ExecMainCode='0')
            requested = [a.split('=', 1)[1] for a in argv if a.startswith('--property=')]
            return SimpleNamespace(returncode=0, stdout='\n'.join(k+'='+props[k] for k in requested), stderr='')

        def identity(pid):
            state['identities'] += 1
            if state['identities'] > 1 and not state['exited']:
                state.update(exited=True, loaded=state['retained'])
                events.append('self-exit')
            return None if state['exited'] else 'start'

        with tempfile.TemporaryDirectory() as td, \
             patch.object(lifecycle.subprocess, 'run', side_effect=command), \
             patch.object(lifecycle, 'identity', side_effect=identity):
            manager = ExperimentalLeaseManager(lifecycle.LocalTransport(), 'retained')
            manager.acquire('client-host', str(Path(td)/'lease'))
            manager.acquire('remote-host', str(Path(td)/'worker-lease'))
            commands = _ProbeCommands()
            probe = commands.run
            def run(address, argv, **kwargs):
                if ('--property=ActiveState' in argv and '--property=ControlGroup' in argv
                        and '--property=MemoryMax' not in argv):
                    return 'ActiveState=inactive\nControlGroup=\n'
                return probe(address, argv, **kwargs)
            commands.run = run
            guard = SystemdSessionGuard(_guard_envelope(), manager, commands,
                                       session=validate_session(session_raw()))
            manager.slices = {'client-host': 'coord.slice', 'remote-host': 'work.slice'}
            guard.client = SimpleNamespace(execution_address='client-host', host_id='client-h')
            guard.remote = SimpleNamespace(execution_address='remote-host', host_id='remote-h')
            guard.execute_deadline = time.monotonic()+60
            guard.demand_profile = fixture.profile
            store = DurableEvidenceStore.create(Path(td)/'evidence', 'retained',
                                                config_sha256=A64, request_sha256=C64)
            plan = SimpleNamespace(strategy_options=dict(rpc_endpoints=['w:5000','w:5001'],
                        source_contract='full-source-both-hosts/1'),
                model=SimpleNamespace(source_id='qwen3.8', revision='r1', representation='Q8_0'),
                workload=SimpleNamespace(context=4096, batch=2048, microbatch=512))
            client = SimpleNamespace(execution_address='client-host', source_path='/never-read')
            class Collector:
                MANIFEST_MAX_BYTES = 1 << 20
                EXECUTABLE_MAX_BYTES = 300 << 20
                def read_json(self, *args, **kwargs):
                    return fixture.manifest
                def read_bytes(self, address, path, **kwargs):
                    if 'demand-profile' in path:
                        _monitor_tick(guard)  # real active/exited completion before retirement
                        events.append('export')
                        return fixture.export
                    return fixture.executable
            runner = OperatorRunner(None, manager, None, None)
            with patch('inferswarm.operator.native_observer.collector.SSHCollectorTransport', Collector), \
                 patch('inferswarm.operator.runtime._model_file_type', return_value=7):
                record = runner._run_demand_capture(plan, guard, {}, {}, client, None, (), store)
            self.assertEqual(record['status'], 'FINISHED', record)
            self.assertTrue((Path(td)/'evidence/demand-export.json').is_file())
            self.assertEqual(record['supervision']['properties']['SubState'], 'exited')
            self.assertNotIn('demand', guard.rows)
            self.assertIn('demand', manager.owned['client-host'])
            cleanup = manager.cleanup()
            guard.after_cleanup(cleanup)
            self.assertEqual(cleanup['client-host']['lease'], 'released', cleanup)
            self.assertEqual(cleanup['client-host']['demand']['properties']['ExecMainStatus'], '0')
            self.assertEqual(cleanup['client-host']['demand']['properties']['MemorySwapCurrent'], str(2**64-1))
            self.assertEqual(cleanup['client-host']['demand']['memory_swap_current_status'], 'unavailable-after-exit')
            self.assertFalse((Path(td)/'lease/active').exists())
            self.assertEqual(events, ['spawn', 'self-exit', 'export', 'stop'])
            self.assertFalse(state['loaded'])


class DemandEndToEndCampaignTests(unittest.TestCase):
    """Full run_experimental_campaign with an opt-in demand block: the real
    monitor thread, guard, runner handoff, capture and durable retention on
    faked hosts (adapted from tests.test_q8_experiment.CampaignFixture)."""

    def setUp(self):
        from tests import test_q8_experiment as driver
        from tests import test_issue313_two_gpu as topology
        from tests.test_issue311_cuda_backing import rejoin_profiles, synthetic_table
        self._driver = driver
        plan_builder = topology.TwoGpuTopologyTests()
        self.plan = plan_builder.build(lambda raw: raw['strategy_options']
                                       ['participant_backing'].update(
                                           limit_bytes=48 << 30,
                                           min_free_bytes=64 << 30,
                                           reserve_bytes=12 << 30))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / 'config.json'
        self.envelope = root / 'envelope.json'
        raw, manifest = topology.two_gpu_mapping()
        raw['strategy_options']['participant_backing'].update(
            limit_bytes=48 << 30, min_free_bytes=64 << 30, reserve_bytes=12 << 30)
        self.config.write_text(json.dumps(rejoin_profiles(raw)))
        self._manifest = manifest
        self._topology = topology
        self._synthetic_table = synthetic_table
        from inferswarm.operator.assigned_backing import optimized_cpu_identities
        self.executable = b'end-to-end-demand-client-bytes'
        self.executable_sha = hashlib.sha256(self.executable).hexdigest()
        reviewed = optimized_cpu_identities()['client']
        self.manifest = dict(
            schema='q8-native-build-manifest/2',
            base_revision=reviewed.base_revision, base_tree=reviewed.base_tree,
            patch_sha256=reviewed.patch_sha256,
            transformed_manifest_sha256='f' * 64,
            protocol=reviewed.protocol, compiler=reviewed.compiler,
            build_options=list(reviewed.build_options),
            executable_sha256=self.executable_sha,
            backend_libraries=[dict(name=n, sha256=d)
                               for n, d in reviewed.backend_libraries])
        self.export = json.dumps({'schema': 'native-demand/1', 'rows': [],
                                  'observed_rows': 0, 'dropped_rows': 0,
                                  'capacity_rows': 4}).encode()

    def demand_session(self):
        from tests.test_issue314_demand_integration import session_raw
        raw = session_raw()
        raw['requests'][1]['body']['prompt'] = 'measure me'
        raw['demand'] = demand_block(client_sha256=self.executable_sha,
                                     prompt='measure me')
        return raw

    def test_demand_capture_completes_after_session_with_workers_kept(self):
        import copy as _copy
        import contextlib as _contextlib
        import io as _io
        from unittest.mock import patch
        from inferswarm.operator.config import parse_config_json
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.profiles import canonical
        from inferswarm.operator.runtime import OperatorRunner
        from tests.issue299_fixture import NOW

        session = self.demand_session()
        session_path = Path(self.temp.name) / 'session.json'
        session_path.write_text(json.dumps(session))
        envelope = dict(schema='q8-two-cuda-experiment/1',
                        opt_in=self._driver.experiment.EXPERIMENTAL_OPT_IN,
                        config_sha256=hashlib.sha256(
                            self.config.read_bytes()).hexdigest(),
                        request_sha256=hashlib.sha256(
                            canonical(session)).hexdigest(),
                        limits=dict(self._driver.experiment._LIMITS),
                        gpu_bindings=[dict(selector='CUDA0', uuid='GPU-' + 'a' * 32),
                                      dict(selector='CUDA1', uuid='GPU-' + 'b' * 32)])
        self.envelope.write_text(json.dumps(envelope))

        class DemandFixture(self._driver.CampaignFixture):
            """CampaignFixture + the demand lifecycle/collector surfaces."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.events = []

            def call(self2, address, payload):
                action = payload['action']
                if action == 'write':
                    data = __import__('base64').b64decode(payload['data'])
                    return {'written': len(data)}
                if action == 'spawn':
                    self2.events.append(('spawn', payload['name']))
                if action == 'stop':
                    self2.events.append(('stop', payload['name']))
                if action == 'alive' and payload.get('name') == 'demand':
                    # The capture client exits promptly after connecting.
                    self2.demand_exited = True
                    return {'alive': False}
                receipt = super().call(address, payload)
                if action == 'inspect' and payload.get('name') == 'demand':
                    row = self2.rows[(address, 'demand')]
                    exited = getattr(self2, 'demand_exited', False)
                    receipt['unit'] = row['supervision']['unit']
                    receipt['properties'].update(LoadState='loaded', RemainAfterExit='yes',
                        SubState='exited' if exited else 'running',
                        MainPID='0' if exited else str(row['pid']),
                        ExecMainCode='1' if exited else '0', ExecMainStatus='0')
                return receipt

            def run(self2, address, argv, **kwargs):
                if argv[0] == 'getconf':
                    return '8\n'
                return super().run(address, argv, **kwargs)

        fixture = DemandFixture('ok')
        fixture.plan = self.plan
        fixture.remote = next(p for p in self.plan.participants
                              if p.role == 'remote')
        evidence_root = Path(self.temp.name) / 'evidence-demand'

        class FakeCollector:
            MANIFEST_MAX_BYTES = 1 << 20
            EXECUTABLE_MAX_BYTES = 300 << 20

            def read_json(self, address, path, *, max_bytes):
                return self.manifest

            def read_bytes(self, address, path, *, max_bytes):
                if 'demand-profile' in path:
                    return self.export
                return self.executable

        FakeCollector.manifest = self.manifest
        FakeCollector.export = self.export
        FakeCollector.executable = self.executable

        def runner_factory(manager):
            fixture.identity_reader = fixture
            return OperatorRunner(fixture, manager, fixture,
                                  fixture.tunnel_factory, collector=fixture)

        def parse_fixture(text, base_dir):
            return parse_config_json(text, base_dir=base_dir, now=NOW,
                                     profile_mode='replay')

        experiment = self._driver.experiment
        with patch.object(experiment, 'parse_config_json',
                          side_effect=parse_fixture), \
             patch.object(experiment, 'build_plan',
                          side_effect=lambda config: build_plan(config, now=NOW)), \
             patch.object(self._topology.assigned_backing, 'identities',
                          return_value=self._synthetic_table(self._manifest)), \
             patch('inferswarm.operator.native_observer.collector.'
                   'SSHCollectorTransport', FakeCollector):
            try:
                result = experiment.run_experimental_campaign(
                    self.config, self.envelope, commands=fixture,
                    transport=fixture, runner_factory=runner_factory,
                    evidence_root=str(evidence_root),
                    evidence_transport=fixture, session_path=session_path)
            except BaseException as exc:
                result = exc
        self.assertIsInstance(result, dict, str(result)[:2000])
        capture = result.get('demand_capture')
        self.assertIsNotNone(capture, str(result)[:2000])
        self.assertEqual(capture['status'], 'FINISHED', str(capture)[:2000])
        self.assertEqual(capture['export_status'], 'retained')
        self.assertEqual(capture['unit_result'], 'success')
        self.assertEqual(result['outcomes']['demand_capture'], 'EXPORTED')
        self.assertEqual(result['outcomes']['cleanup'], 'COMPLETE')
        # The capture ran AFTER the frozen session's requests and after the
        # ordinary client stopped; the workers stayed up for cache reuse.
        self.assertEqual(len(fixture.posts), len(session['requests']))
        spawned = {name for (_addr, name) in fixture.rows}
        self.assertEqual(spawned, {'rpc0', 'rpc1', 'client', 'demand'})
        # Event order: the ordinary client's stop precedes the demand spawn,
        # and NO worker was stopped before the demand client spawned (the
        # workers stay up to serve the assigned-cache reuse); both are only
        # stopped by terminal cleanup afterwards.
        demand_spawn = fixture.events.index(('spawn', 'demand'))
        client_stop = fixture.events.index(('stop', 'client'))
        self.assertLess(client_stop, demand_spawn)
        pre_capture_stops = {name for kind, name in fixture.events[:demand_spawn]
                             if kind == 'stop'}
        self.assertEqual(pre_capture_stops, {'client'})
        post = [name for kind, name in fixture.events[demand_spawn:]
                if kind == 'stop']
        self.assertIn('demand', post)
        # Durable retention on the controller side.
        export = json.loads((evidence_root / 'demand-export.json').read_text())
        self.assertEqual(export['schema'], 'native-demand/1')
        finished = json.loads((evidence_root /
                               'demand-capture-finished.json').read_text())
        self.assertEqual(finished['status'], 'FINISHED')


if __name__ == '__main__':
    unittest.main()
