"""RED regressions for maintainer review 5482179642 P2 on PR #305.

Bounded collection and terminal evidence:
- SSH reads must enforce distinct per-artifact size bounds BEFORE
  materializing remote file contents (claims/manifests/envelopes/executables).
- Output acceptance requires a deterministic exact-owned terminal-export
  fence after owned teardown: missing, racing, duplicate, stale, malformed
  and overbound exports refuse.
All remote content is SYNTHETIC except the retained #301 manifests/captures.
"""
import hashlib
import json
import unittest
from pathlib import Path

from inferswarm.operator import phased_observation as contract
from inferswarm.operator.bindings import TransportReply
from inferswarm.operator.native_observer.collector import (
    CLAIM_NAME, CollectorError, NativeObserverCollector, NATIVE_LABELS,
    ProcIdentityReader, SSHCollectorTransport)

from tests.test_issue302_per_role_builds import (
    LLAMA_MANIFEST, RPC_MANIFEST, ROLE_PATHS, ROLE_EXECUTABLES,
    SYNTHETIC_EXE_SHA, VirtualHostTree, RecordingCollectorTransport,
    RecordingIdentityReader, collector_for, distinct_role_plan,
    synthetic_retained_builds)

ROUND2 = Path(__file__).resolve().parents[1] / 'tests/fixtures/issue299/round2-native'
from tests.test_issue302_collected_runner import export_name, genuine_dynamic


def seal(record):
    record = dict(record)
    record['terminal_digest'] = hashlib.sha256(json.dumps(
        {k: v for k, v in record.items() if k != 'terminal_digest'},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return record


class BoundedReadTests(unittest.TestCase):
    """P2: distinct limits per artifact family, enforced before parsing."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def participant(self, role):
        return next(p for p in self.plan.participants if p.role == role)

    def test_transport_read_bytes_requires_explicit_bound(self):
        transport = SSHCollectorTransport()
        # The bound is a required keyword-only argument: a read without it
        # cannot even be invoked, and an invalid bound refuses.
        with self.assertRaises(TypeError):
            transport.read_bytes('unused', '/opt/observer/llama-server')
        with self.assertRaisesRegex(ValueError, 'bound'):
            transport.read_bytes('unused', '/opt/observer/llama-server', max_bytes=0)
        with self.assertRaisesRegex(ValueError, 'bound'):
            transport.read_bytes('unused', '/opt/observer/llama-server', max_bytes=None)

    def test_overbound_envelope_refuses_before_parsing(self):
        # A >8 MiB dynamic envelope must refuse at the transport bound,
        # before any parse_observation materialization.
        tree = VirtualHostTree()
        p = self.participant('client')
        address = p.execution_address
        export = '/synthetic/exports-client'
        huge = seal(dict(json.loads((ROUND2 / 'cpu-dynamic.json').read_text()),
                         participant_id='llama-server', invocation_token='inv-302',
                         plan_digest='0' * 64,
                         stream_generation='exp-4242-0-966507438683494',
                         facts=dict(json.loads((ROUND2 / 'cpu-dynamic.json').read_text())['facts'],
                                    padding='x' * (9 << 20))))
        tree.put(address, export + '/' + export_name('llama-server', 4242), huge)
        tree.put_dir(address, export, [CLAIM_NAME, export_name('llama-server', 4242)])
        tree.put(address, export + '/' + CLAIM_NAME,
                 '4242\nstart-4242\nllama-server\n'.encode())
        collector = collector_for(tree)
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'exceeds|bound|oversized'):
            collector.collect_dynamic(p, spawn, export, self.plan.digest, 'inv-302',
                                      NATIVE_LABELS['client'])

    def test_overbound_executable_refuses(self):
        tree = VirtualHostTree()
        p = self.participant('client')
        address = p.execution_address
        body = dict(LLAMA_MANIFEST, executable_sha256=hashlib.sha256(b'x' * ((300 << 20) + 1)).hexdigest())
        tree.put(address, ROLE_PATHS['client'][0], body)
        tree.put(address, ROLE_PATHS['client'][1],
                 b'x' * (SSHCollectorTransport.EXECUTABLE_MAX_BYTES + 1))
        collector = NativeObserverCollector(RecordingCollectorTransport(tree),
                                            RecordingIdentityReader(),
                                            retained_builds={
            'client': {'executable_name': 'llama-server',
                       'executable_sha256': body['executable_sha256'],
                       'backend_libraries': (('libllama-full.a',
                         LLAMA_MANIFEST['backend_libraries'][0]['sha256']),)},
            'remote': {'executable_name': 'ggml-rpc-server',
                       'executable_sha256': SYNTHETIC_EXE_SHA['remote'],
                       'backend_libraries': (('libggml-static.a',
                         RPC_MANIFEST['backend_libraries'][0]['sha256']),)}})
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'exceeds|bound'):
            collector.collect_static(p, spawn, ROLE_PATHS['client'][0],
                                     ROLE_PATHS['client'][1], 'a' * 64,
                                     expected_argv=(p.runtime_executable, '--serve'))

    def test_overbound_claim_refuses(self):
        tree = VirtualHostTree()
        p = self.participant('client')
        address = p.execution_address
        export = '/synthetic/exports-client'
        tree.put(address, export + '/' + CLAIM_NAME,
                 (b'4242\nstart-4242\nllama-server\n' + b'x' * (1 << 20)))
        tree.put_dir(address, export, [CLAIM_NAME])
        collector = collector_for(tree)
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'exceeds|bound|malformed'):
            collector.collect_dynamic(p, spawn, export, self.plan.digest, 'inv-302',
                                      NATIVE_LABELS['client'])

    def test_distinct_limits_are_applied_per_family(self):
        # The production transport program carries per-family caps; the
        # collector passes each family's bound explicitly.
        from inferswarm.operator.native_observer import collector as module
        self.assertLess(module.CLAIM_MAX_BYTES, module.MANIFEST_MAX_BYTES)
        self.assertLess(module.MANIFEST_MAX_BYTES, module.ENVELOPE_MAX_BYTES)
        self.assertLess(module.ENVELOPE_MAX_BYTES, module.EXECUTABLE_MAX_BYTES)


class TerminalExportFenceTests(unittest.TestCase):
    """P2: deterministic exact-owned terminal-export completion fence."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def participant(self, role):
        return next(p for p in self.plan.participants if p.role == role)

    def tree_with_terminal_export(self, p, pid=4242, start='start-4242'):
        tree = VirtualHostTree()
        export = '/synthetic/exports-client'
        record = genuine_dynamic('cpu-dynamic.json', 'llama-server', 'inv-302', pid)
        tree.put(p.execution_address, export + '/' + CLAIM_NAME,
                 f'{pid}\n{start}\nllama-server\n'.encode())
        tree.put(p.execution_address, export + '/' + export_name('llama-server', pid), record)
        tree.put_dir(p.execution_address, export,
                     [CLAIM_NAME, export_name('llama-server', pid)])
        return tree, export

    def test_fence_waits_for_late_export(self):
        # The export lands a few polls after teardown (producer writes at
        # termination); the fence must wait bounded time, not refuse or
        # accept early.
        p = self.participant('client')
        tree, export = self.tree_with_terminal_export(p)
        transport = RecordingCollectorTransport(tree)
        listing = transport.list_dir
        state = {'calls': 0}

        def slow_list_dir(address, path):
            state['calls'] += 1
            if state['calls'] < 3:
                return []
            return listing(address, path)
        transport.list_dir = slow_list_dir
        collector = NativeObserverCollector(transport, RecordingIdentityReader(),
                                            retained_builds=synthetic_retained_builds())
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        collector.await_terminal_export(p, spawn, export, NATIVE_LABELS['client'],
                                        timeout=5.0, pause=0.01)
        self.assertGreaterEqual(state['calls'], 3)

    def test_fence_missing_export_refuses(self):
        p = self.participant('client')
        tree = VirtualHostTree()
        export = '/synthetic/exports-client'
        tree.put_dir(p.execution_address, export, [])
        collector = NativeObserverCollector(RecordingCollectorTransport(tree),
                                            RecordingIdentityReader(),
                                            retained_builds=synthetic_retained_builds())
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'terminal export'):
            collector.await_terminal_export(p, spawn, export, NATIVE_LABELS['client'],
                                            timeout=0.05, pause=0.01)

    def test_fence_foreign_pid_export_refuses(self):
        # A stale export from a different (recycled) pid must not satisfy
        # the fence for this owned spawn.
        p = self.participant('client')
        tree, export = self.tree_with_terminal_export(p, pid=99999)
        collector = NativeObserverCollector(RecordingCollectorTransport(tree),
                                            RecordingIdentityReader(),
                                            retained_builds=synthetic_retained_builds())
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'terminal export'):
            collector.await_terminal_export(p, spawn, export, NATIVE_LABELS['client'],
                                            timeout=0.05, pause=0.01)

    def test_fence_malformed_export_names_refuse(self):
        p = self.participant('client')
        tree = VirtualHostTree()
        export = '/synthetic/exports-client'
        tree.put(p.execution_address, export + '/' + CLAIM_NAME,
                 '4242\nstart-4242\nllama-server\n'.encode())
        tree.put_dir(p.execution_address, export, [CLAIM_NAME, 'garbage-name.json'])
        collector = NativeObserverCollector(RecordingCollectorTransport(tree),
                                            RecordingIdentityReader(),
                                            retained_builds=synthetic_retained_builds())
        spawn = contract.OwnedSpawnFacts(p.participant_id, 4242, 'start-4242', 'inv-302')
        with self.assertRaisesRegex(CollectorError, 'terminal export'):
            collector.await_terminal_export(p, spawn, export, NATIVE_LABELS['client'],
                                            timeout=0.05, pause=0.01)


if __name__ == '__main__':
    unittest.main()
