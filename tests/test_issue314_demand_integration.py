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
        self.log_tail = ''
        self.oom = 0

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
            return f'low 0\nhigh 0\nmax 0\noom {self.oom}\noom_kill 0\n'
        if head == 'python3':
            return json.dumps({p: 'raw' for p in argv[3:]})
        if head == 'tail':
            self.tail_calls.append((address, argv[-1]))
            return self.log_tail
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

    def test_exact_backend_change_reservation_is_not_an_allocator_stop(self):
        self.commands.log_tail = ('ggml_backend_sched_alloc_splits: failed to allocate graph, '
                                  'reserving (backend_ids_changed = 1)\n')
        _monitor_tick(self.guard)
        self.assertIsNone(self.guard._monitor_error)

    def test_terminal_and_combined_failures_still_stop(self):
        benign = ('ggml_backend_sched_alloc_splits: failed to allocate graph, '
                  'reserving (backend_ids_changed = 1)')
        for text in ('ggml_backend_sched_alloc_splits: failed to allocate graph\n',
                     benign + '\nggml_backend_sched_alloc_splits: failed to allocate graph\n',
                     benign + ' CUDA error: out of memory\n',
                     benign + ' failed to allocate buffer of size 4096\n',
                     'failed to allocate graph, reserving (backend_ids_changed = 0)\n',
                     'failed to allocate buffer, reserving\n'):
            with self.subTest(text=text):
                self.commands.log_tail = text
                with self.assertRaisesRegex(RuntimeError, 'allocator/device'):
                    _monitor_tick(self.guard)

    def test_benign_log_never_hides_cgroup_oom(self):
        self.commands.log_tail = 'failed to allocate graph, reserving (backend_ids_changed = 1)\n'
        self.commands.oom = 1
        with self.assertRaisesRegex(RuntimeError, 'allocator/OOM'):
            _monitor_tick(self.guard)

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

    def capture(self, *, result='success', refuse_export=False, fail_at=None,
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
        refuse = {'demand-export.json'} if refuse_export else set()
        if fail_at == 'before-spawn':
            refuse.add('demand-capture-started.json')
        store = _StubStore(refuse=refuse)
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
            if payload.get('name') == 'demand':
                if fail_at == 'spawn-reply' and payload['action'] == 'spawn':
                    raise RuntimeError('demand spawn reply lost')
                if fail_at == 'guard-stop' and payload['action'] == 'alive':
                    self.guard._monitor_error = RuntimeError('owned allocator/device failure: demand')
                    self.guard.checkpoint()
            if (completion_override is not None and payload['action'] == 'inspect'
                    and payload['name'] == 'demand'
                    and self.transport.state[(address, 'demand')].get('exited')):
                return completion_override(receipt)
            return receipt

        class FakeCollector:
            MANIFEST_MAX_BYTES = 1 << 20
            EXECUTABLE_MAX_BYTES = 300 << 20

            def read_json(self, address, path, *, max_bytes):
                if fail_at == 'identity':
                    raise ValueError('candidate manifest unavailable')
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

    def test_failed_capture_remains_enabled_with_attempt_and_terminal_cause(self):
        for stage, attempted in (('identity', False), ('before-spawn', False),
                                 ('spawn-reply', True), ('guard-stop', True)):
            with self.subTest(stage=stage):
                self.setUp()
                with self.assertRaises((RuntimeError, ValueError)) as caught:
                    self.capture(fail_at=stage)
                report = self.guard.report(dict(self.guard.execution_result), failure=caught.exception)
                record = report.get('demand_capture')
                self.assertIsNotNone(record)
                self.assertTrue(record['enabled'])
                self.assertEqual(record['attempted'], attempted)
                self.assertEqual(record['failure']['reason'], str(caught.exception))
                self.assertNotEqual(report['outcomes']['demand_capture'], 'disabled')
                self.assertNotIn('export_retained', record)
                if stage == 'guard-stop':
                    self.assertEqual(record['status'], 'GUARD-STOPPED')
                    self.assertEqual(report['outcomes']['demand_capture'], 'GUARD-STOPPED')
                    self.assertIn('spawn_receipt', record)

    def test_default_off_report_remains_disabled(self):
        report = self.guard.report({}, failure=RuntimeError('ordinary client failed'))
        self.assertEqual(report['outcomes']['demand_capture'], 'disabled')
        self.assertNotIn('demand_capture', report)

    def test_enabled_capture_stopped_before_entry_is_not_disabled(self):
        self.guard.demand_profile = self.profile
        error = RuntimeError('session client did not exit before demand capture')
        report = self.guard.report({}, failure=error)
        self.assertFalse(report['demand_capture']['attempted'])
        self.assertEqual(report['demand_capture']['failure']['reason'], str(error))
        self.assertEqual(report['outcomes']['demand_capture'], 'FAILED')

    def test_later_campaign_failure_preserves_a_retained_export(self):
        record, _ = self.capture()
        report = self.guard.report(dict(self.guard.execution_result),
                                   failure=RuntimeError('later observer failure'))
        self.assertEqual(report['outcomes']['demand_capture'], 'EXPORTED')
        self.assertEqual(report['demand_capture'], record)

    def test_nested_success_reaches_export_readback_and_retention(self):
        record, store = self.capture(result='success')
        self.assertEqual(store.attempts[0][-1], record['log_path'])
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
        self.attempts = []

    def register_attempt(self, *args, **kwargs):
        self.attempts.append(args)

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
        local_run = lifecycle.subprocess.run
        log_bytes = b'native demand log retained\n'
        events = []
        unit = 'inferswarm-q8-313-retained-demand.service'
        fields = dict(MainPID='123', ActiveState='active', SubState='running',
            LoadState='loaded', RemainAfterExit='yes', Result='success',
            ExecMainCode='0', ExecMainStatus='0', MemoryCurrent='1024', MemoryPeak='2048',
            MemorySwapCurrent='0', MemoryMax=str(_COORD_CAP), MemorySwapMax='0',
            RuntimeMaxUSec='60s', KillMode='control-group', ControlGroup='/coord.slice/'+unit)

        def command(argv, **kwargs):
            if argv[2] == 'systemd-run':
                log_path = next(a.split('append:', 1)[1] for a in argv
                                if a.startswith('--property=StandardOutput=append:'))
                state['log_path'] = log_path
                Path(log_path).write_bytes(log_bytes)
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
                if argv[0] == 'tail':
                    commands.tail_calls.append((address, argv[-1]))
                    return Path(argv[-1]).read_text() if Path(argv[-1]).is_file() else ''
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
            self.assertEqual(record['log_path'], state['log_path'])
            self.assertIn(('client-host', state['log_path']), commands.tail_calls)
            self.assertEqual(store._attempted['demand']['log_path'], state['log_path'])
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
            # The production collector reads the registered path through a
            # local stand-in for host transport; only staged temporary files
            # are inspected, with all service commands still faked.
            def retained_read(address, argv, **kwargs):
                return local_run(argv, capture_output=True, text=True, check=True, **kwargs).stdout
            store.collect_processes([], SimpleNamespace(run=retained_read))
            kept = [row for row in store._rows if row['kind'] == 'log']
            self.assertEqual(len(kept), 1, store._rows)
            self.assertEqual(kept[0]['status'], 'collected', kept)
            self.assertEqual((Path(td)/'evidence'/kept[0]['target']).read_bytes(), log_bytes)


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

    def _execute_capture(self, *, fail_at=None):
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
                if action == 'spawn' and payload['name'] == 'demand' and fail_at == 'spawn-reply':
                    raise RuntimeError('demand spawn reply lost')
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
        return result, fixture, evidence_root

    def test_capture_exception_is_durably_reported_as_attempted(self):
        result, fixture, evidence_root = self._execute_capture(fail_at='spawn-reply')
        self.assertIsInstance(result, self._driver.experiment.ExperimentalCampaignError)
        receipt = result.campaign_receipt
        capture = receipt['demand_capture']
        self.assertTrue(capture['enabled'])
        self.assertTrue(capture['attempted'])
        self.assertEqual(capture['status'], 'FAILED')
        self.assertIn('demand spawn reply lost', capture['failure']['reason'])
        self.assertEqual(receipt['outcomes']['demand_capture'], 'FAILED')
        self.assertFalse((evidence_root/'demand-export.json').exists())
        retained = json.loads((evidence_root/'session-report.json').read_text())
        self.assertEqual(retained['demand_capture'], capture)
        self.assertFalse(fixture.services)

    def test_demand_capture_completes_after_session_with_workers_kept(self):
        session = self.demand_session()
        result, fixture, evidence_root = self._execute_capture()
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


class HotExpertManifestTests(unittest.TestCase):
    """#314 immutable intent and authenticated encoded-slice preparation only."""

    def fixture(self, root, ids=(54, 74, 136, 290, 394)):
        # Small encoded Q8_0 banks, still 512 global expert IDs. No weights.
        payload = dict(schema='is314-hot-expert-manifest/1', status='INTENT',
            model=dict(repository='synthetic/local', revision='fixture-v1',
                       metadata_sha256=hashlib.sha256(b'metadata').hexdigest()),
            representation='Q8_0', native_source='b29c606e28a01b1bc8c1351026a0fa6e616bf6c4',
            provenance_bundle_sha256=hashlib.sha256(b'fixture provenance').hexdigest(),
            capture_provenance_sha256=None, layer=7, expert_ids=list(ids), sources=[])
        paths, banks = {}, {}
        for n, component in enumerate(('gate', 'up', 'down')):
            slices = [bytes(((i + n) % 256, i // 256)) * 34 for i in range(512)]
            bank = b''.join(slices)
            member = component + '.gguf'
            content = b'prefix!' + bank + b'!tail'
            path = root / member
            path.write_bytes(content)
            paths[member], banks[component] = path, slices
            payload['sources'].append(dict(component=component,
                name='blk.7.ffn_' + component + '_exps.weight', member=member,
                member_sha256=hashlib.sha256(content).hexdigest(),
                member_size_bytes=len(content), tensor_offset=7,
                shape=[32, 2, 512, 1], ggml_type=8,
                tensor_sha256=hashlib.sha256(bank).hexdigest()))
        return payload, paths, banks

    def module(self):
        from inferswarm.operator import hot_experts
        return hot_experts

    def frozen(self, payload):
        module = self.module()
        data = module.seal_manifest(payload)
        return module.load_manifest(data, expected_sha256=json.loads(data)['sha256'])

    def test_preparation_checks_shared_deadline_between_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            payload,paths,_=self.fixture(root)
            calls=[]
            def checkpoint():
                calls.append(1)
                if len(calls)==3:
                    raise TimeoutError('outer deadline')
            outputs={c:root/(c+'.compact') for c in ('gate','up','down')}
            with self.assertRaisesRegex(TimeoutError,'outer deadline'):
                self.module().prepare(self.frozen(payload),paths,rpc_backend='RPC[fixture:1]',
                    output_paths=outputs,checkpoint=checkpoint)
            self.assertEqual(len(calls),3)
            self.assertTrue(all(not p.exists() for p in outputs.values()))

    def test_gather_cli_freezes_actual_hashes_under_shared_clock(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); payload,paths,_=self.fixture(root)
            manifest=self.frozen(payload); manifest_path=root/'manifest.json'
            manifest_path.write_bytes(manifest.canonical_bytes)
            clock=root/'clock.json'; _load314_recipe().freeze_clock(clock)
            output=root/'prepared.json'
            argv=[sys.executable,str(ROOT/'tools/native-hot-experts/comparison.py'),'gather',
                '--manifest',str(manifest_path),'--manifest-sha256',manifest.sha256,
                '--rpc-endpoint','fixture:1','--clock',str(clock),'--output',str(output)]
            for name,path in paths.items():
                argv.extend(['--source',name+'='+str(path)])
            result=subprocess.run(argv,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            prepared=self.module().load_prepared(output.read_bytes(),
                expected_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(prepared.native_spec()['rpc_backend'],'RPC[fixture:1]')
            self.assertEqual(prepared.report()['global_to_local']['394'],4)
            previous=output.read_bytes()
            again=subprocess.run(argv,capture_output=True,text=True)
            self.assertNotEqual(again.returncode,0)
            self.assertEqual(output.read_bytes(),previous)

    def test_manifest_is_canonical_immutable_and_externally_pinned(self):
        import copy
        from dataclasses import FrozenInstanceError
        with tempfile.TemporaryDirectory() as td:
            payload, _, _ = self.fixture(Path(td))
            module = self.module()
            manifest = self.frozen(payload)
            expected = manifest.sha256
            payload['expert_ids'].reverse()
            self.assertEqual(manifest.expert_ids, (54, 74, 136, 290, 394))
            returned = manifest.payload(); returned['expert_ids'].reverse()
            self.assertEqual(manifest.expert_ids[-1], 394)
            with self.assertRaises((FrozenInstanceError, AttributeError)):
                manifest.sha256 = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'expected manifest'):
                module.load_manifest(module.seal_manifest(payload), expected_sha256=expected)
            with self.assertRaisesRegex(ValueError, 'canonical'):
                module.load_manifest(manifest.canonical_bytes + b'\n', expected_sha256=expected)
            altered = json.loads(manifest.canonical_bytes)
            altered['sources'][0]['shape'][0] = 64
            with self.assertRaisesRegex(ValueError, 'self digest'):
                module.load_manifest(json.dumps(altered, sort_keys=True,
                    separators=(',', ':')).encode(), expected_sha256=expected)
            for field in ('model', 'expert_ids', 'sources', 'provenance_bundle_sha256'):
                changed = copy.deepcopy(manifest.payload())
                changed[field] = ({'repository': 'other', **changed[field], 'revision': 'other'}
                    if field == 'model' else list(reversed(changed[field]))
                    if field in ('expert_ids', 'sources') else 'f' * 64)
                reason = 'sources must be ordered' if field == 'sources' else 'expected manifest'
                with self.assertRaisesRegex(ValueError, reason):
                    module.load_manifest(module.seal_manifest(changed), expected_sha256=expected)

    def test_duplicate_out_of_range_and_invalid_source_metadata_refuse(self):
        import copy
        with tempfile.TemporaryDirectory() as td:
            payload, _, _ = self.fixture(Path(td))
            for ids in ([54, 54], [-1], [512], [True], [], [1.0]):
                bad = copy.deepcopy(payload); bad['expert_ids'] = ids
                with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'expert'):
                    self.frozen(bad)
            for field, value, reason in (
                    ('shape', [33, 2, 512, 1], 'shape'),
                    ('shape', [32, 2, 512, 2], 'shape'),
                    ('ggml_type', 1, 'Q8_0'),
                    ('tensor_offset', -1, 'offset'),
                    ('member_sha256', 'X' * 64, 'SHA-256'),
                    ('name', 'blk.8.ffn_gate_exps.weight', 'name')):
                bad = copy.deepcopy(payload); bad['sources'][0][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                    self.frozen(bad)

    def test_exact_noncontiguous_gather_global_local_map_and_native_spec(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload, paths, banks = self.fixture(root)
            manifest = self.frozen(payload)
            outputs = {c: root / (c + '.compact') for c in banks}
            result = self.module().prepare(manifest, paths, rpc_backend='RPC0[fixture:1]',
                output_paths=outputs, max_staging_bytes=340)
            spec, report = result.native_spec(), result.report()
            self.assertEqual(spec['schema'], 'is314-hot-experts/1')
            self.assertEqual(spec['expert_ids'], [54, 74, 136, 290, 394])
            self.assertEqual(report['global_to_local']['394'], 4)
            self.assertEqual(report['total_compact_bytes'], 1020)
            self.assertLessEqual(report['peak_staging_bytes'], 340)
            lines = result.assigned_lines().decode().splitlines()
            self.assertEqual(len(lines), 3)
            for source, row, line in zip(payload['sources'], spec['tensors'], lines):
                component = source['component']
                want = b''.join(banks[component][i] for i in manifest.expert_ids)
                self.assertEqual(outputs[component].read_bytes(), want)
                self.assertEqual(row['compact_sha256'], hashlib.sha256(want).hexdigest())
                self.assertEqual(row['source_sha256'], source['tensor_sha256'])
                self.assertEqual(row['source_shape'], [32, 2, 512, 1])
                self.assertEqual(row['compact_shape'], [32, 2, 5, 1])
                self.assertEqual(row['expert_bytes'], 68)
                self.assertEqual(row['ranges'][-1], dict(expert_id=394,
                    source_offset=26792, destination_offset=272, length=68))
                self.assertEqual(line.split(), [row['compact_name'], '8', '32', '2',
                    '5', '1', '340', hashlib.sha256(want).hexdigest()])
                self.assertLessEqual(len(row['compact_name'].encode('ascii')), 63)
                self.assertNotEqual(row['compact_name'], row['source_name'])
            # Metadata-only preparation computes the very same derived hashes;
            # no persistent staging files are required by native context setup.
            hash_only = self.module().prepare(manifest, paths, rpc_backend='RPC0[fixture:1]',
                max_staging_bytes=68)
            self.assertEqual(hash_only.native_spec(), spec)
            self.assertEqual(hash_only.assigned_lines(), result.assigned_lines())

    def test_source_member_tensor_hash_and_bounds_authenticate_before_outputs(self):
        import copy
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload, paths, _ = self.fixture(root)
            module = self.module()
            outputs = {c: root / (c + '.compact') for c in ('gate', 'up', 'down')}
            manifest = self.frozen(payload)
            original = paths['down.gguf'].read_bytes()
            paths['down.gguf'].write_bytes(original[:-1] + b'X')
            with self.assertRaisesRegex(ValueError, 'member.*SHA-256'):
                module.prepare(manifest, paths, rpc_backend='RPC0[fixture:1]', output_paths=outputs)
            self.assertFalse(any(p.exists() for p in outputs.values()))
            paths['down.gguf'].write_bytes(original)
            bad = copy.deepcopy(payload); bad['sources'][2]['tensor_sha256'] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'tensor.*SHA-256'):
                module.prepare(self.frozen(bad), paths, rpc_backend='RPC0[fixture:1]', output_paths=outputs)
            self.assertFalse(any(p.exists() for p in outputs.values()))
            bad = copy.deepcopy(payload); bad['sources'][2]['tensor_offset'] = len(original)
            with self.assertRaisesRegex(ValueError, 'bounds'):
                self.frozen(bad)
            with self.assertRaisesRegex(ValueError, 'staging'):
                module.prepare(manifest, paths, rpc_backend='RPC0[fixture:1]', max_staging_bytes=67)

    def test_output_destinations_never_overwrite_prior_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload, paths, _ = self.fixture(root)
            manifest = self.frozen(payload)
            module = self.module()
            same = root / 'same'
            outputs = dict(gate=same, up=same, down=root/'down.compact')
            with self.assertRaisesRegex(ValueError, 'duplicate output'):
                module.prepare(manifest, paths, rpc_backend='RPC0[fixture:1]', output_paths=outputs)
            self.assertFalse(same.exists())
            outputs = {c: root/(c+'.compact') for c in ('gate', 'up', 'down')}
            outputs['down'].write_bytes(b'prior accepted bytes')
            with self.assertRaisesRegex(ValueError, 'output.*exists'):
                module.prepare(manifest, paths, rpc_backend='RPC0[fixture:1]', output_paths=outputs)
            self.assertEqual(outputs['down'].read_bytes(), b'prior accepted bytes')
            self.assertFalse(outputs['gate'].exists())
            outputs['down'].unlink()
            outputs['gate'].symlink_to(root/'absent')
            with self.assertRaisesRegex(ValueError, 'output.*exists'):
                module.prepare(manifest, paths, rpc_backend='RPC0[fixture:1]', output_paths=outputs)
            self.assertFalse((root/'absent').exists())

    def test_explicit_allhot_selection_is_not_limited_to_h5(self):
        with tempfile.TemporaryDirectory() as td:
            payload, paths, _ = self.fixture(Path(td), ids=(394, 74, 0, 1, 2, 3, 4, 5, 6, 511, 54))
            manifest = self.frozen(payload)
            result = self.module().prepare(manifest, paths, rpc_backend='RPC0[fixture:1]')
            self.assertEqual(result.native_spec()['expert_ids'], payload['expert_ids'])
            self.assertEqual(result.native_spec()['tensors'][0]['compact_shape'][2], 11)
            self.assertEqual(result.report()['global_to_local']['394'], 0)

    def test_actual_source_reads_are_bounded_and_no_retained_tensor_hash_is_invented(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            payload, paths, banks = self.fixture(Path(td))
            for source in payload['sources']:
                source['tensor_sha256'] = None
            module = self.module()
            manifest = self.frozen(payload)
            original = Path.open
            reads = []
            class Reader:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): return self.stream.__exit__(*args)
                def fileno(self): return self.stream.fileno()
                def seek(self, *args): return self.stream.seek(*args)
                def read(self, *args): raise AssertionError('unbounded read is prohibited')
                def readinto(self, view):
                    reads.append(len(view))
                    return self.stream.readinto(view)
            def open_tracked(path, *args, **kwargs):
                stream = original(path, *args, **kwargs)
                return Reader(stream) if args and args[0] == 'rb' else stream
            with patch.object(Path, 'open', open_tracked):
                result = module.prepare(manifest, paths, rpc_backend='RPC0[fixture:1]',
                                        max_staging_bytes=68)
            self.assertTrue(reads)
            self.assertEqual(max(reads), 68)
            self.assertEqual(result.report()['peak_staging_bytes'], 68)
            for record in result.source_records:
                bank = b''.join(banks[record['component']])
                self.assertEqual(record['tensor_sha256'], hashlib.sha256(bank).hexdigest())
            self.assertTrue(all(source['tensor_sha256'] is None for source in manifest.payload()['sources']))
            self.assertFalse(list(Path(td).glob('*.compact')))

    def test_exclusive_output_race_preserves_competitor_and_cleans_only_own_files(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload, paths, _ = self.fixture(root)
            manifest = self.frozen(payload)
            outputs = {c: root/(c+'.compact') for c in ('gate', 'up', 'down')}
            original = Path.open
            def race(path, *args, **kwargs):
                if path == outputs['up'] and args and args[0] == 'xb':
                    with original(path, 'wb') as stream: stream.write(b'competitor')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'open', race), self.assertRaisesRegex(ValueError, 'output.*exists'):
                self.module().prepare(manifest, paths, rpc_backend='RPC0[fixture:1]', output_paths=outputs)
            self.assertEqual(outputs['up'].read_bytes(), b'competitor')
            self.assertFalse(outputs['gate'].exists())
            self.assertFalse(outputs['down'].exists())

    def test_derived_guard_uses_actual_native_whole_tensor_upload_checks(self):
        # Coverage-only follow-up: assigned.h already refuses these cases; this
        # binds its real reader/checker to the newly emitted compact guard.
        import os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload, paths, _ = self.fixture(root)
            prepared = self.module().prepare(self.frozen(payload), paths, rpc_backend='RPC0[fixture:1]')
            guard = root/'assigned'; guard.write_bytes(prepared.assigned_guard)
            source = root/'guard.cpp'
            source.write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#define GGML_ASSERT(x) assert(x)
struct rpc_tensor { char name[64]; uint64_t view_src, view_offs; uint32_t type, ne[4]; };
struct rpc_msg_set_tensor_hash_req { rpc_tensor tensor; uint64_t offset, size; uint8_t sha256[32]; };
#include "assigned.h"
int main() {
  const auto & entry = *assigned_ranges().begin();
  rpc_msg_set_tensor_hash_req good{};
  std::strcpy(good.tensor.name, entry.first.c_str());
  good.tensor.type=entry.second.type; good.size=entry.second.length;
  for (int i=0;i<4;++i) good.tensor.ne[i]=entry.second.ne[i];
  for (int i=0;i<32;++i) good.sha256[i]=std::stoi(entry.second.sha.substr(2*i,2),nullptr,16);
  assert(assigned_upload(good));
  auto bad=good; bad.tensor.view_src=1; assert(!assigned_upload(bad));
  bad=good; bad.tensor.view_offs=1; assert(!assigned_upload(bad));
  bad=good; bad.offset=1; assert(!assigned_upload(bad));
  bad=good; --bad.size; assert(!assigned_upload(bad));
  bad=good; ++bad.tensor.ne[2]; assert(!assigned_upload(bad));
  bad=good; ++bad.tensor.type; assert(!assigned_upload(bad));
  bad=good; bad.sha256[0]^=1; assert(!assigned_upload(bad));
  bad=good; std::strcpy(bad.tensor.name,"blk.7.ffn_gate_exps.weight"); assert(!assigned_upload(bad));
}
''')
            binary = root/'guard-fixture'
            subprocess.run(['c++', '-std=c++17', '-O0', '-I', str(ROOT/'tools/native-cache'),
                            str(source), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True,
                           env=dict(os.environ, IS311_ASSIGNED=str(guard)))

    def test_prepared_reader_is_raw_digest_pinned_and_rederives_guard_spec(self):
        import copy
        with tempfile.TemporaryDirectory() as td:
            payload, paths, _ = self.fixture(Path(td))
            module = self.module()
            prepared = module.prepare(self.frozen(payload), paths, rpc_backend='RPC0[fixture:1]')
            raw = prepared.canonical_bytes
            loaded = module.load_prepared(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(loaded.native_spec_bytes, prepared.native_spec_bytes)
            self.assertEqual(loaded.assigned_guard, prepared.assigned_lines())
            self.assertEqual(loaded.source_records[0]['name'], payload['sources'][0]['name'])
            with self.assertRaisesRegex(ValueError, 'prepared.*SHA-256'):
                module.load_prepared(raw, expected_sha256='f'*64)
            for key, value in (('compact_shape', [32, 2, 4, 1]), ('expert_bytes', 1),
                               ('source_name', 'other'), ('compact_name', payload['sources'][0]['name'])):
                bad = json.loads(raw); bad['native_spec']['tensors'][0][key] = value
                sealed = json.dumps(bad, sort_keys=True, separators=(',', ':')).encode()
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'native spec'):
                    module.load_prepared(sealed, expected_sha256=hashlib.sha256(sealed).hexdigest())
            # Full/view/offset-zero semantics cannot be weakened via extra fields.
            bad = json.loads(raw); bad['native_spec']['tensors'][0]['view_src'] = 1
            sealed = json.dumps(bad, sort_keys=True, separators=(',', ':')).encode()
            with self.assertRaisesRegex(ValueError, 'native spec'):
                module.load_prepared(sealed, expected_sha256=hashlib.sha256(sealed).hexdigest())

    def test_prepared_source_crosscheck_joins_actual_cpu_receipt_and_model_metadata(self):
        import copy
        with tempfile.TemporaryDirectory() as td:
            payload, paths, _ = self.fixture(Path(td))
            module = self.module()
            prepared = module.prepare(self.frozen(payload), paths, rpc_backend='RPC0[fixture:1]')
            metadata = dict(source=dict(source_id=payload['model']['repository'],
                revision=payload['model']['revision'], representation='Q8_0'),
                metadata_digest=payload['model']['metadata_sha256'], tensors=[dict(
                    state_id=s['name'], member=s['member'], absolute_offset=s['tensor_offset'],
                    shape=s['shape'][:3], ggml_type=8, encoded_bytes=34816) for s in payload['sources']])
            receipt = dict(schema='q8-source-receipt/1', status='VERIFIED-not-consumed',
                role='client', backing='full-source', source_identity=metadata['source'],
                metadata_digest=metadata['metadata_digest'], verified_members=list(paths),
                member_identities=[[s['member'], s['member_sha256'], s['member_size_bytes']]
                                   for s in payload['sources']], range_identities=[dict(
                    state_id=s['name'], member=s['member'], offset=s['tensor_offset'],
                    length=34816, sha256=s['tensor_sha256']) for s in payload['sources']])
            module.validate_prepared_sources(prepared, metadata, receipt)
            for field, value in (('verified_members', []), ('metadata_digest', 'f'*64),
                                 ('source_identity', {}), ('backing', 'assigned-immutable-native-backing')):
                bad = copy.deepcopy(receipt); bad[field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'source receipt'):
                    module.validate_prepared_sources(prepared, metadata, bad)
            bad = copy.deepcopy(metadata); bad['tensors'][0]['shape'][0] = 64
            with self.assertRaisesRegex(ValueError, 'source metadata'):
                module.validate_prepared_sources(prepared, bad, receipt)
            bad = copy.deepcopy(receipt); bad['range_identities'][0]['sha256'] = 'f'*64
            with self.assertRaisesRegex(ValueError, 'source receipt'):
                module.validate_prepared_sources(prepared, metadata, bad)

    def test_example_intent_binds_checked_in_source_metadata_without_compact_hashes(self):
        module = self.module()
        data = (ROOT/'tools/native-hot-experts/example-manifest.json').read_bytes()
        manifest = module.load_manifest(data, expected_sha256=json.loads(data)['sha256'])
        payload = manifest.payload()
        metadata = json.loads((ROOT/'tests/fixtures/issue299/q8-metadata.json').read_text())
        self.assertEqual(payload['model']['repository'], metadata['source']['source_id'])
        self.assertEqual(payload['model']['revision'], metadata['source']['revision'])
        self.assertEqual(payload['model']['metadata_sha256'], metadata['metadata_digest'])
        self.assertEqual(payload['provenance_bundle_sha256'],
            '5d52bf5badee1cdbf450d9c5ba59a1089c85ac45f0c386574cf0a7500b3bf42f')
        self.assertEqual(manifest.expert_ids, (54, 74, 136, 290, 394))
        self.assertEqual(payload['status'], 'INTENT')
        capture = ROOT/'tools/native-hot-experts/capture-provenance.json'
        self.assertEqual(payload['capture_provenance_sha256'],
                         hashlib.sha256(capture.read_bytes()).hexdigest())
        for source in payload['sources']:
            tensor = next(t for t in metadata['tensors'] if t['state_id'] == source['name'])
            member = next(h for h in metadata['header_identities'] if h[0] == tensor['member'])
            self.assertEqual(source['member_sha256'], member[5])
            self.assertEqual(source['member_size_bytes'], member[4])
            self.assertEqual(source['tensor_offset'], tensor['absolute_offset'])
            self.assertEqual(source['shape'], tensor['shape'] + [1])
            self.assertIsNone(source['tensor_sha256'])
            self.assertNotIn('compact_sha256', source)
            self.assertEqual(module.encoded_expert_bytes(source['shape']), 1740800)
        self.assertEqual(module.compact_byte_counts(manifest),
            dict(gate=8704000, up=8704000, down=8704000, total=26112000))




# Portable recipe fixtures: these are synthetic shapes, never hardware evidence.
import copy
import math


def _canonical314(obj):
    return json.dumps(obj,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()


def _load314_recipe():
    import importlib.util
    spec=importlib.util.spec_from_file_location('is314_comparison_tests',ROOT/'tools/native-hot-experts/comparison.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config314_recipe():
    provenance=json.loads((ROOT/'tools/native-hot-experts/capture-provenance.json').read_bytes())
    return dict(selection='two-gpu',plan_id='synthetic-A',model=provenance['model'],
        participants=[dict(lifecycle_dir='/synthetic/A')],
        workload=dict(context=2048,batch=128,microbatch=32,slots=1),
        strategy_options=dict(build_pair='hot-experts-candidate-cpu05-cuda03',threads=14))


class FrozenHotComparisonTests(unittest.TestCase):
    def config(self):
        from inferswarm.operator.assigned_backing import HOT_BUILD_PAIR, role_identity
        from tests.test_issue311_cuda_backing import rejoin_profiles
        from tests.test_issue313_two_gpu import two_gpu_mapping
        raw, _ = two_gpu_mapping()
        raw['strategy_options']['build_pair'] = HOT_BUILD_PAIR
        for part in raw['participants']:
            backend = 'cpu' if part['role'] == 'client' else 'cuda'
            part['runtime_sha256'] = role_identity(part['role'], backend,
                build_pair=HOT_BUILD_PAIR).executable_sha256
        return rejoin_profiles(raw)

    def plan(self):
        from inferswarm.operator.config import parse_config
        from inferswarm.operator.plan import build_plan
        from tests.issue299_fixture import NOW
        config = parse_config(self.config(), now=NOW, profile_mode='replay')
        return build_plan(config, now=NOW)

    def test_real_campaign_refuses_model_drift_before_lease_or_helper(self):
        from unittest.mock import Mock, patch
        from inferswarm.operator import q8_experiment as experiment
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            fixtures=HotExpertManifestTests()
            payload,paths,_=fixtures.fixture(root)
            prepared=fixtures.module().prepare(fixtures.frozen(payload),paths,
                rpc_backend='RPC[synthetic-B.example:5000]')
            prepared_path=root/'prepared.json'
            prepared_path.write_bytes(prepared.canonical_bytes)
            prepared_sha=hashlib.sha256(prepared.canonical_bytes).hexdigest()
            raw=self.config()
            raw['model']['members'][0]['sha256']='0'*64
            config_path=root/'config.json'
            config_path.write_text(json.dumps(raw))
            commands=Mock(spec=['run'])
            commands.run.side_effect=AssertionError('external helper crossed preflight')
            transport=Mock(spec=['call'])
            transport.call.side_effect=AssertionError('lease or launch crossed preflight')
            runner_factory=Mock(side_effect=AssertionError('runner crossed preflight'))
            for arm,session in self.helper().arm_sessions(str(prepared_path),prepared_sha).items():
                with self.subTest(arm=arm):
                    session_path=root/('session-'+arm+'.json')
                    session_path.write_text(json.dumps(session))
                    evidence_root=root/('evidence-'+arm)
                    # Observe the real constructor; parsing/planning and all
                    # identity validators remain real, with external I/O faked.
                    with patch.object(experiment,'ExperimentalLeaseManager',
                            wraps=experiment.ExperimentalLeaseManager) as leases:
                        with self.assertRaisesRegex(ValueError,'backing source identity mismatch'):
                            experiment.run_experimental_campaign(config_path,root/'unused-envelope.json',
                                commands=commands,transport=transport,runner_factory=runner_factory,
                                evidence_root=str(evidence_root),session_path=session_path,
                                outer_start_monotonic=100)
                    leases.assert_not_called()
                    commands.run.assert_not_called()
                    transport.call.assert_not_called()
                    runner_factory.assert_not_called()
                    self.assertFalse(evidence_root.exists())

    def test_frozen_model_preflight_refuses_identity_drift_before_tokenizer_io(self):
        from dataclasses import replace
        from inferswarm.operator.hot_experiment import validate_frozen_model, tokenize_hot_session
        plan=self.plan()
        model=plan.model
        self.assertEqual(validate_frozen_model(plan),
            'a13849d1ad98cff76713f7cd0f650be1217402d79588327815025bd7d42b48d1')
        changed=[replace(model,source_id='other'),replace(model,revision='other'),
                 replace(model,representation='other')]
        name,sha,size=model.members[0]
        changed.extend(replace(model,members=(member,)+model.members[1:]) for member in (
            ('other.gguf',sha,size),(name,'0'*64,size),(name,sha,size+1)))
        calls=[]
        runner=SimpleNamespace(http=SimpleNamespace(post=lambda *a,**k:calls.append((a,k))))
        guard=SimpleNamespace(session=validate_session(self.session()))
        client=next(p for p in plan.participants if p.role=='client')
        for changed_model in changed:
            with self.subTest(model=changed_model):
                bad=replace(plan,model=changed_model)
                with self.assertRaisesRegex(ValueError,'frozen comparison model identity mismatch'):
                    validate_frozen_model(bad)
                with self.assertRaisesRegex(ValueError,'frozen comparison model identity mismatch'):
                    tokenize_hot_session(runner,guard,bad,'http://owned',client)
        self.assertEqual(calls,[])

    def test_real_runner_and_guard_tokenize_both_arms_before_request_boundary(self):
        from inferswarm.operator.runtime import OperatorRunner
        from inferswarm.operator.source import q8_source_payload
        helper=self.helper()
        plan=self.plan()
        source_model=q8_source_payload(plan)['model']
        self.assertTrue(all(type(row) is list for row in source_model['members']))
        self.assertEqual(hashlib.sha256(_canonical314(source_model)).hexdigest(),
            'bcf68992a91dbb0bed9d37414ceaee2813fbedea39990a2dba73bc066c9d41be')
        runtime_sha=next(p.runtime_sha256 for p in plan.participants if p.role=='client')
        for arm in ('A','B'):
            with self.subTest(arm=arm):
                guard,leases,rows=_make_guard_state(_ProbeCommands(),_FakeTransport())
                guard.session=validate_session(helper.arm_sessions('/synthetic/prepared.json','2'*64)[arm])
                guard.hot_request=SimpleNamespace(enabled=arm=='B')
                calls=[]; saved={}
                def post(url,body,timeout):
                    calls.append((url,body,timeout))
                    if url.endswith('/tokenize'):
                        return {'tokens':[1,2,3]}
                    return {'content':'fixture', 'stop':True, 'stop_type':'eos'}
                runner=OperatorRunner(None,leases,SimpleNamespace(post=post),None)
                runner.evidence=SimpleNamespace(save_session_json=lambda name,value:
                    saved.__setitem__(name,value) or True)
                result=runner._execute_diagnostic_session(plan,guard,'http://owned',rows,[],{},
                    SimpleNamespace(poll=lambda:None),SimpleNamespace(
                        execution_address='client-host',runtime_sha256=runtime_sha),None,[])
                self.assertEqual([row[0] for row in calls],
                    ['http://owned/tokenize']*5+['http://owned/completion']*5)
                self.assertTrue(all(type(row[2]) is int and 1<=row[2]<=900 for row in calls))
                self.assertEqual([row['status'] for row in guard.request_records],['COMPLETED']*5)
                receipt=saved['actual-tokenizer.json']
                self.assertEqual(receipt,result['actual_tokenizer'])
                self.assertEqual(receipt['model_sha256'],
                    'a13849d1ad98cff76713f7cd0f650be1217402d79588327815025bd7d42b48d1')
                self.assertEqual(receipt['tokenizer']['executable_sha256'],runtime_sha)
                self.assertEqual(helper.validate_tokenizer_receipt(receipt,guard.session.payload()),[3]*5)

    def test_guard_uses_owned_server_tokenizer_before_inference(self):
        from inferswarm.operator.hot_experiment import tokenize_hot_session
        from inferswarm.operator.q8_session import validate_session
        calls=[]
        def post(url,body,timeout):
            calls.append((url,body,timeout))
            return {'tokens':[1,2,3]}
        saved={}
        from inferswarm.operator.q8_session import SystemdSessionGuard
        guard=SystemdSessionGuard(None,SimpleNamespace(),None,
            session=validate_session(self.session()),clock=lambda:1000)
        guard.set_outer_start(100)
        runner=SimpleNamespace(http=SimpleNamespace(post=post),evidence=SimpleNamespace(
            save_session_json=lambda name,obj:saved.setdefault(name,obj)))
        plan=self.plan()
        client=next(p for p in plan.participants if p.role=='client')
        receipt=tokenize_hot_session(runner,guard,plan,'http://owned',client)
        self.assertEqual(len(calls),5)
        self.assertTrue(all(x[0]=='http://owned/tokenize' for x in calls))
        self.assertTrue(all(x[1]['add_special'] is True and x[1]['parse_special'] is True for x in calls))
        self.assertEqual(receipt['tokenizer']['executable_sha256'],client.runtime_sha256)
        self.assertIn('actual-tokenizer.json',saved)
        runner.http.post=lambda *args,**kwargs:{'tokens':list(range(129))}
        with self.assertRaisesRegex(ValueError,'128'):
            tokenize_hot_session(runner,guard,plan,'http://owned',client)

    def test_shared_clock_is_one_immutable_controller_boot_record(self):
        c=self.helper()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'clock.json'
            record=c.freeze_clock(path)
            self.assertEqual(c.check_clock(path)['started_monotonic'],record['started_monotonic'])
            with self.assertRaises(FileExistsError):
                c.freeze_clock(path)
            with self.assertRaisesRegex(TimeoutError,'160-minute'):
                c.check_clock(path,now=record['started_monotonic']+9600)
            data=json.loads(path.read_bytes());data['boot_id']='different'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'host/boot'):
                c.check_clock(path)

    def helper(self):
        return _load314_recipe()

    def session(self):
        return json.loads((ROOT / 'tools/native-hot-experts/frozen-requests.json').read_text())

    def receipt(self, counts=None):
        c = self.helper()
        session = self.session()
        return {'schema': 'is314-tokenizer-receipt/1', 'model_sha256': c.MODEL_SHA256,
                'session_sha256': hashlib.sha256(_canonical314(session)).hexdigest(),
                'tokenizer': {'source_revision': 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4',
                              'executable_sha256': '1' * 64, 'add_special': True,
                              'parse_special': True, 'actual_model_input': True},
                'requests': [{'index': i+1, 'body_sha256': hashlib.sha256(_canonical314(row['body'])).hexdigest(),
                              'token_ids': list(range(count))}
                             for i, (row, count) in enumerate(zip(session['requests'], counts or [14,28,24,22,28]))]}

    def test_frozen_exact_bodies_caps_and_repeat(self):
        c = self.helper()
        session = self.session()
        c.validate_frozen_session(session)
        provenance=json.loads((ROOT/'tools/native-hot-experts/capture-provenance.json').read_bytes())
        for request,row in zip(session['requests'][:2],provenance['request_binding']['requests']):
            self.assertEqual(hashlib.sha256(_canonical314(request['body'])).hexdigest(),row['body_sha256'])
        self.assertEqual(session['requests'][4],session['requests'][1])
        self.assertEqual([r['body']['n_predict'] for r in session['requests']], [8,32,32,32,32])
        self.assertNotIn('demand', session)

    def test_session_drift_refused(self):
        c = self.helper()
        for change in ('prompt','n_predict','seed'):
            session = self.session()
            body = session['requests'][2]['body']
            body[change] = 'changed' if change == 'prompt' else 33
            with self.assertRaises(ValueError):
                c.validate_frozen_session(session)

    def test_tokenizer_missing_refused(self):
        c = self.helper()
        with self.assertRaisesRegex(ValueError, 'actual.*tokeniz|tokenizer'):
            c.validate_tokenizer_receipt(None, self.session())

    def test_actual_bound_tokenizer_ids_accepted(self):
        c = self.helper()
        self.assertEqual(c.validate_tokenizer_receipt(self.receipt(), self.session()), [14,28,24,22,28])

    def test_tokenizer_oversize_fake_count_wrong_model_or_body_refused(self):
        c = self.helper()
        for mutation in ('oversize','fake-count','model','body','bool-id','negative-id','settings','missing-row'):
            rec = self.receipt()
            if mutation == 'oversize': rec['requests'][2]['token_ids'] = list(range(129))
            if mutation == 'fake-count': rec['requests'][2] = {'index': 3, 'count': 4}
            if mutation == 'model': rec['model_sha256'] = '0' * 64
            if mutation == 'body': rec['requests'][2]['body_sha256'] = '0' * 64
            if mutation == 'bool-id': rec['requests'][2]['token_ids'] = [True]
            if mutation == 'negative-id': rec['requests'][2]['token_ids'] = [-1]
            if mutation == 'settings': rec['tokenizer']['add_special'] = False
            if mutation == 'missing-row': rec['requests'].pop()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                c.validate_tokenizer_receipt(rec, self.session())

    def test_frozen_semantics_independent_of_cross_backend_bytes(self):
        c = self.helper()
        self.assertTrue(c.semantic_check(1, ' red red')['pass'])
        self.assertTrue(c.semantic_check(2, 'A B C D A B C D')['pass'])
        self.assertFalse(c.semantic_check(2, 'A B C D A D')['pass'])
        self.assertFalse(c.semantic_check(2, 'A B')['pass'])
        self.assertTrue(c.semantic_check(3, ' Lima\n')['pass'])
        self.assertFalse(c.semantic_check(3, 'The city is Lima')['pass'])
        self.assertTrue(c.semantic_check(4, '[1, 2, 3]')['pass'])
        self.assertFalse(c.semantic_check(4, '[true,2,3]')['pass'])
        self.assertFalse(c.semantic_check(4, '```json\n[1,2,3]\n```')['pass'])
        self.assertTrue(c.semantic_check(5, 'A B C D')['pass'])

    def test_numeric_diagnostics_no_bitwise_or_invented_tolerance(self):
        c = self.helper()
        d = c.numerical_diagnostic([1.,2.], [1.01,2.])
        self.assertTrue(d['finite'])
        self.assertAlmostEqual(d['max_abs'], .01)
        self.assertAlmostEqual(d['rms'], math.sqrt(.0001/2))
        self.assertEqual(d['verdict'], 'DIAGNOSTIC-NOT-QUALIFICATION')
        self.assertNotIn('pass', d)
        for a,b in (([],[]),([1.],[1.,2.]),([1.],[float('nan')])):
            with self.assertRaises(ValueError): c.numerical_diagnostic(a,b)

    def test_numeric_capture_cli_uses_actual_aligned_same_input_records(self):
        import struct
        c = self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.bin';b=Path(tmp)/'b.bin'
            header=struct.pack('<IIIIQ',0x39303349,7,2,1,1)
            a.write_bytes(header+struct.pack('<ffff',1.,2.,3.,4.))
            b.write_bytes(header+struct.pack('<ffff',1.,2.,3.01,4.))
            report=c.compare_numeric_captures(a,b)
            self.assertEqual(report['verdict'],'DIAGNOSTIC-NOT-QUALIFICATION')
            self.assertEqual(len(report['records']),1)
            b.write_bytes(header+struct.pack('<ffff',2.,2.,3.,4.))
            with self.assertRaisesRegex(ValueError,'input'):
                c.compare_numeric_captures(a,b)

    def test_config_pair_checks_material_equivalence_and_candidate_pair(self):
        c = self.helper()
        a = _config314_recipe()
        a['strategy_options']['build_pair'] = c.BUILD_PAIR
        b = copy.deepcopy(a)
        b['plan_id'] = 'synthetic-B'
        for part in b['participants']: part['lifecycle_dir'] += '-B'
        self.assertTrue(c.validate_config_pair(a,b)['materially_equal'])
        for mutation in ('build','threads','placement','model','batch'):
            changed = copy.deepcopy(b)
            if mutation=='build':changed['strategy_options']['build_pair']='optimized-cpu05-cuda03'
            if mutation=='threads':changed['strategy_options']['threads']=28
            if mutation=='placement':changed['strategy_options']['placement_variant']='40-44'
            if mutation=='model':changed['model']['revision']='wrong'
            if mutation=='batch':changed['workload']['batch']=64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                c.validate_config_pair(a,changed)
        bad=copy.deepcopy(a);bad['workload']['context']=4096
        with self.assertRaises(ValueError): c.validate_config_pair(bad,copy.deepcopy(bad))

    def test_prepare_cli_archives_exact_config_bytes_and_refuses_overwrite(self):
        import subprocess
        c = self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config=_config314_recipe()
            config['strategy_options']['build_pair']=c.BUILD_PAIR
            a=root/'a.json';b=root/'b.json';prepared=root/'prepared.json'
            a.write_text(json.dumps(config));b.write_text(json.dumps(config))
            prepared.write_text('{}')  # Plan writer hashes only; runner owns semantic admission.
            out=root/'plan'
            command=[sys.executable,str(ROOT/'tools/native-hot-experts/comparison.py'),'prepare',
                     '--output',str(out),'--prepared',str(prepared),'--config-a',str(a),'--config-b',str(b)]
            done=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(done.returncode,0,done.stderr)
            self.assertEqual((out/'config-A.json').read_bytes(),a.read_bytes())
            plan=json.loads((out/'plan.json').read_text())
            self.assertEqual(plan['arm_configs']['A']['sha256'],hashlib.sha256(a.read_bytes()).hexdigest())
            self.assertTrue(plan['config_equivalence']['materially_equal'])
            self.assertFalse(plan['execution_authorized'])
            session=json.loads((out/'session-A.json').read_text())
            self.assertEqual(plan['sessions']['A']['request_sha256'],hashlib.sha256(_canonical314(session)).hexdigest())
            before=(out/'plan.json').read_bytes()
            again=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(again.returncode,0)
            self.assertEqual((out/'plan.json').read_bytes(),before)

    def test_offline_plan_pending_tokenizer_never_authorizes_execution(self):
        c = self.helper()
        plan = c.prepare_plan()
        self.assertFalse(plan['execution_authorized'])
        self.assertEqual(plan['arm_order'], ['A','B'])
        self.assertEqual(plan['budget']['total_seconds'], 10800)
        self.assertEqual(plan['budget']['execution_stop_seconds'], 9600)
        self.assertEqual(plan['tokenizer_status'], 'PENDING-ACTUAL-MODEL-TOKENIZATION')
        self.assertEqual(plan['max_loads_per_arm'], 1)
        self.assertEqual(plan['retries'], 0)
        self.assertEqual(plan['native_activation']['environment'], 'IS314_HOT_SPEC')

    def test_arm_sessions_bind_enabled_switch_to_different_full_hashes(self):
        c = self.helper()
        sessions = c.arm_sessions('/synthetic/prepared.json', '2' * 64)
        a, b = sessions['A'], sessions['B']
        self.assertEqual(a['requests'], b['requests'])
        self.assertFalse(a['hot_experts']['enabled'])
        self.assertTrue(b['hot_experts']['enabled'])
        self.assertNotEqual(hashlib.sha256(_canonical314(a)).hexdigest(), hashlib.sha256(_canonical314(b)).hexdigest())
        for session in sessions.values(): c.validate_frozen_session(session)
        with self.assertRaises(ValueError): c.arm_sessions('relative.json', '2' * 64)

    def make_arm(self, root, c, *, bad=False, arm='A'):
        session=c.arm_sessions('/synthetic/prepared.json', '2' * 64)[arm]
        responses=['red red', 'A B C D A B C D', 'Lima', '[1,2,3]', 'A B C D']
        rows=[]
        for i,(request,text) in enumerate(zip(session['requests'],responses),1):
            body=request['body']
            response={'content': text, 'stop': True, 'stop_type': 'limit',
                      'truncated': False, 'tokens_predicted': 4,
                      'timings': {'predicted_n': 4, 'prompt_n': 28, 'cache_n': 0,
                                  'prompt_ms': 10., 'predicted_ms': 20.}}
            if bad and i==3: response['content']='wrong'
            (root/f'request-{i:02d}-response.json').write_text(json.dumps(response))
            rows.append({'index':i,'warmup':request['warmup'],'body':body,
                         'request_sha256':hashlib.sha256(_canonical314(body)).hexdigest(),
                         'status':'COMPLETED','wall_seconds':.1})
        report={'session_sha256':hashlib.sha256(_canonical314(session)).hexdigest(),
                'frozen_session':session,'requests':rows,'output_accepted':False,
                'physical_qualified':False,'setup':{},'samples':[],
                'outcomes':{'execution':'COMPLETED','observer':'REFUSED','cleanup':'COMPLETE'}}
        (root/'session-report.json').write_text(json.dumps(report))

    def test_compare_actual_retained_shapes_preserves_observer_refusal(self):
        c=self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'A';b=Path(tmp)/'B';a.mkdir();b.mkdir()
            self.make_arm(a,c);self.make_arm(b,c,arm='B')
            report=c.compare_arms(a,b)
            self.assertTrue(report['semantic_pass'])
            self.assertEqual(report['arms']['A']['observer'],'REFUSED')
            self.assertFalse(report['output_accepted'])
            self.assertFalse(report['physical_qualified'])
            self.assertEqual(report['numerical']['verdict'],'NOT-CAPTURED')
            self.assertEqual(len(report['paired_requests']),4)
            self.assertEqual(report['paired_requests'][0]['wall_ratio_b_over_a'],1.)

    def test_compare_semantic_failure_does_not_erase_other_results(self):
        c=self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'A';b=Path(tmp)/'B';a.mkdir();b.mkdir()
            self.make_arm(a,c);self.make_arm(b,c,bad=True,arm='B')
            report=c.compare_arms(a,b)
            self.assertFalse(report['semantic_pass'])
            self.assertEqual(len(report['paired_requests']),4)

    def test_compare_refuses_drifted_request_and_missing_response(self):
        c=self.helper()
        for mutation in ('drift','missing','extra','over-generation'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);self.make_arm(root,c)
                if mutation=='drift':
                    p=root/'session-report.json';o=json.loads(p.read_text())
                    o['requests'][2]['body']['n_predict']=33;p.write_text(json.dumps(o))
                if mutation=='missing':(root/'request-03-response.json').unlink()
                if mutation=='extra':(root/'request-06-response.json').write_text('{}')
                if mutation=='over-generation':
                    p=root/'request-03-response.json';o=json.loads(p.read_text())
                    o['tokens_predicted']=33;p.write_text(json.dumps(o))
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                    c.analyze_arm(root)


if __name__ == '__main__':
    unittest.main()
