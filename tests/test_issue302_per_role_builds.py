"""RED->GREEN regressions for maintainer review 5482179642 P1-A on PR #305.

Per-role build identities: the collector path must bind the client to the
retained llama-server manifest/executable (libllama-full.a closure) and the
RPC participant to the retained ggml-rpc-server manifest/executable
(libggml-static.a closure), with distinct per-role runtime digests. All
remote content is SYNTHETIC except the two genuine retained #301 build
manifests, whose overlay/backend identities are consumed verbatim. The
executable-byte pin is rebound to synthetic binaries through the collector's
retained_builds seam exactly as production would pin the genuine bytes.
"""
import hashlib
import json
import unittest
from pathlib import Path

from inferswarm.operator import phased_observation as contract
from inferswarm.operator.config import parse_config
from inferswarm.operator.plan import build_plan
from inferswarm.operator.profiles import canonical, freeze
from inferswarm.operator.bindings import ProcessIdentity
from inferswarm.operator.native_observer.collector import (
    CollectorError, NativeObserverCollector, ProcIdentityReader,
    SSHCollectorTransport)

from tests.issue299_fixture import NOW, reseal_profiles, profile_digest
from tests.test_issue299_q8_plan import fully_bounded_mapping

ROUND2 = Path(__file__).resolve().parents[1] / 'tests/fixtures/issue299/round2-native'

LLAMA_MANIFEST = json.loads((ROUND2 / 'llama-server.build-manifest.json').read_text())
RPC_MANIFEST = json.loads((ROUND2 / 'ggml-rpc-server.build-manifest.json').read_text())

# Genuine retained per-role executable identities (#301, /2 manifests).
LLAMA_EXE_SHA = LLAMA_MANIFEST['executable_sha256']
RPC_EXE_SHA = RPC_MANIFEST['executable_sha256']

ROLE_PATHS = {
    'client': ('/opt/observer/llama-server.build-manifest.json', '/opt/observer/llama-server'),
    'remote': ('/opt/observer/ggml-rpc-server.build-manifest.json', '/opt/observer/ggml-rpc-server'),
}
ROLE_EXECUTABLES = {'client': b'synthetic-llama-server-binary',
                    'remote': b'synthetic-rpc-server-binary'}
SYNTHETIC_EXE_SHA = {role: hashlib.sha256(payload).hexdigest()
                     for role, payload in ROLE_EXECUTABLES.items()}


def per_role_observer_options():
    return dict(client_manifest_path=ROLE_PATHS['client'][0],
                client_executable_path=ROLE_PATHS['client'][1],
                remote_manifest_path=ROLE_PATHS['remote'][0],
                remote_executable_path=ROLE_PATHS['remote'][1])


def synthetic_retained_builds():
    """The genuine overlay/backend-closure pins rebound to synthetic bytes."""
    return {
        'client': {'executable_name': 'llama-server',
                   'executable_sha256': SYNTHETIC_EXE_SHA['client'],
                   'backend_libraries': (('libllama-full.a',
                     LLAMA_MANIFEST['backend_libraries'][0]['sha256']),)},
        'remote': {'executable_name': 'ggml-rpc-server',
                   'executable_sha256': SYNTHETIC_EXE_SHA['remote'],
                   'backend_libraries': (('libggml-static.a',
                     RPC_MANIFEST['backend_libraries'][0]['sha256']),)},
    }


def distinct_runtime_mapping():
    """Fully bounded one-gpu mapping whose participants carry the two genuine
    retained per-role runtime executable identities (SYNTHETIC plan plumbing;
    the genuine manifest byte joins happen in the collector tests below)."""
    raw = fully_bounded_mapping('one-gpu')
    raw['strategy_options']['observer'] = per_role_observer_options()
    # Distinct per-role runtime digests: the participants' runtime binaries
    # are the two genuinely different retained executables.
    digests = {'A': LLAMA_EXE_SHA, 'B': RPC_EXE_SHA}
    for participant in raw['participants']:
        participant['runtime_sha256'] = digests[participant['host_id']]
    # Every runtime capability of a host must match its participant binary.
    for runtime in raw['profiles']['snapshot']['runtime_capabilities']:
        participant = next(p for p in raw['participants']
                           if p['host_id'] == runtime['host_id'])
        runtime['binary_sha256'] = participant['runtime_sha256']
        for evidence in raw['profiles']['snapshot']['evidence']:
            if evidence['evidence_id'] == 'synthetic-' + runtime['runtime_id']:
                evidence['dependencies'][
                    'runtime:' + runtime['runtime_id'] + ':binary_sha256'] = participant['runtime_sha256']
    reseal_profiles(raw['profiles']['snapshot'])
    raw['profiles']['digest'] = profile_digest(raw['profiles']['snapshot'])
    return raw


def distinct_role_plan():
    return build_plan(parse_config(distinct_runtime_mapping(), now=NOW,
                                   profile_mode='replay'), now=NOW)


class VirtualHostTree:
    def __init__(self):
        self.files = {}
        self.dirs = {}

    def put(self, address, path, payload):
        if isinstance(payload, (dict, list)):
            payload = canonical(payload)
        self.files.setdefault(address, {})[str(path)] = payload

    def put_dir(self, address, path, names):
        self.dirs.setdefault(address, {})[str(path)] = sorted(names)


class RecordingCollectorTransport(SSHCollectorTransport):
    def __init__(self, tree):
        self.tree = tree
        self.reads = []

    def read_bytes(self, address, path):
        self.reads.append((address, path))
        try:
            return self.tree.files[address][str(path)]
        except KeyError as exc:
            raise CollectorError(f'collector read failed ({address}:{path}): absent') from exc

    def read_json(self, address, path):
        return json.loads(self.read_bytes(address, path).decode('utf-8'))

    def list_dir(self, address, path):
        try:
            return list(self.tree.dirs[address][str(path)])
        except KeyError as exc:
            raise CollectorError(f'collector listing failed ({address}:{path}): absent') from exc


class RecordingIdentityReader(ProcIdentityReader):
    """Records genuinely distinct observed per-role executable identities."""

    def read(self, participant, pid, *, expected_executable, expected_sha256,
             expected_argv, visibility_environment=()):
        return ProcessIdentity(participant.participant_id, participant.host_id,
            participant.boot_epoch, participant.topology_epoch, pid,
            'start-%d' % pid, expected_executable, expected_sha256,
            tuple(expected_argv),
            freeze(dict(native=[], visible=[], environment={})),
            participant.rpc_endpoint)


def per_role_tree(plan):
    """Both hosts carry BOTH retained manifests and executables; role-correct
    selection is the collector's job, path identity alone is not trust.

    The manifest bodies keep the genuine retained overlay/backend-closure
    identities verbatim; only the executable-byte pin is rebound to the
    synthetic binaries (the collector's retained_builds seam pins the same
    synthetic digests, mirroring how production pins the genuine bytes)."""
    tree = VirtualHostTree()
    bodies = {
        'client': dict(LLAMA_MANIFEST, executable_sha256=SYNTHETIC_EXE_SHA['client']),
        'remote': dict(RPC_MANIFEST, executable_sha256=SYNTHETIC_EXE_SHA['remote']),
    }
    for participant in plan.participants:
        address = participant.execution_address
        tree.put(address, ROLE_PATHS['client'][0], bodies['client'])
        tree.put(address, ROLE_PATHS['remote'][0], bodies['remote'])
        tree.put(address, ROLE_PATHS['client'][1], ROLE_EXECUTABLES['client'])
        tree.put(address, ROLE_PATHS['remote'][1], ROLE_EXECUTABLES['remote'])
    return tree


def spawn_for(participant, token='inv-302'):
    pid = 101 if participant.role == 'client' else 202
    return contract.OwnedSpawnFacts(participant.participant_id, pid,
        'start-%d' % pid, token)


def collector_for(tree):
    return NativeObserverCollector(RecordingCollectorTransport(tree),
                                   RecordingIdentityReader(),
                                   retained_builds=synthetic_retained_builds())


def collect_both(plan, tree):
    collector = collector_for(tree)
    evidence = []
    for participant in plan.participants:
        manifest_path, executable_path = ROLE_PATHS[participant.role]
        evidence.append(collector.collect_static(participant,
            spawn_for(participant), manifest_path, executable_path,
            'a' * 64, expected_argv=(participant.runtime_executable, '--serve')))
    return evidence


class PerRoleBuildIdentityTests(unittest.TestCase):
    """P1-A — one shared observer identity cannot serve both roles."""

    @classmethod
    def setUpClass(cls):
        cls.plan = distinct_role_plan()

    def participant(self, role):
        return next(p for p in self.plan.participants if p.role == role)

    def test_participants_have_distinct_retained_runtime_identities(self):
        client = self.participant('client')
        remote = self.participant('remote')
        self.assertNotEqual(client.runtime_sha256, remote.runtime_sha256)
        self.assertEqual(client.runtime_sha256, LLAMA_EXE_SHA)
        self.assertEqual(remote.runtime_sha256, RPC_EXE_SHA)

    def test_collector_joins_genuine_distinct_role_manifests(self):
        tree = per_role_tree(self.plan)
        client = self.participant('client')
        remote = self.participant('remote')
        by_id = {e.participant_id: e for e in collect_both(self.plan, tree)}
        # The joined manifests are the genuine retained per-role bodies with
        # only the executable-byte pin rebound to the synthetic binaries.
        self.assertEqual(by_id[client.participant_id].build.manifest.executable_sha256,
                         SYNTHETIC_EXE_SHA['client'])
        self.assertEqual(by_id[remote.participant_id].build.manifest.executable_sha256,
                         SYNTHETIC_EXE_SHA['remote'])
        self.assertEqual(by_id[client.participant_id].build.manifest.backend_libraries,
                         (('libllama-full.a',
                           LLAMA_MANIFEST['backend_libraries'][0]['sha256']),))
        self.assertEqual(by_id[remote.participant_id].build.manifest.backend_libraries,
                         (('libggml-static.a',
                           RPC_MANIFEST['backend_libraries'][0]['sha256']),))
        self.assertNotEqual(by_id[client.participant_id].build.manifest.manifest_sha256,
                            by_id[remote.participant_id].build.manifest.manifest_sha256)

    def test_swapped_role_manifests_refuse(self):
        # The client joined to the retained RPC-server manifest/executable
        # must refuse: the role's backend closure does not match.
        tree = per_role_tree(self.plan)
        client = self.participant('client')
        collector = collector_for(tree)
        with self.assertRaisesRegex(CollectorError, 'for this role'):
            collector.collect_static(client, spawn_for(client),
                ROLE_PATHS['remote'][0], ROLE_PATHS['remote'][1],
                'a' * 64, expected_argv=(client.runtime_executable, '--serve'))

    def test_shared_observer_options_refuse_at_config_validation(self):
        # The shared manifest_path/executable_path shape from the reviewed
        # head is no longer an accepted observer configuration.
        raw = fully_bounded_mapping('one-gpu')
        raw['strategy_options']['observer'] = dict(
            manifest_path=ROLE_PATHS['client'][0],
            executable_path=ROLE_PATHS['client'][1])
        with self.assertRaisesRegex(ValueError, 'observer'):
            build_plan(parse_config(raw, now=NOW, profile_mode='replay'), now=NOW)

    def test_incomplete_role_coverage_refuses(self):
        raw = fully_bounded_mapping('one-gpu')
        raw['strategy_options']['observer'] = dict(
            client_manifest_path=ROLE_PATHS['client'][0],
            client_executable_path=ROLE_PATHS['client'][1])
        with self.assertRaisesRegex(ValueError, 'observer'):
            build_plan(parse_config(raw, now=NOW, profile_mode='replay'), now=NOW)

    def test_foreign_backend_closure_refuses(self):
        # The RPC role must close over libggml-static.a, not libllama-full.a.
        tree = per_role_tree(self.plan)
        remote = self.participant('remote')
        address = remote.execution_address
        body = dict(RPC_MANIFEST)
        body['backend_libraries'] = [dict(name='libllama-full.a',
            sha256=RPC_MANIFEST['backend_libraries'][0]['sha256'])]
        body['executable_sha256'] = SYNTHETIC_EXE_SHA['remote']
        tree.put(address, ROLE_PATHS['remote'][0], body)
        collector = collector_for(tree)
        with self.assertRaisesRegex(CollectorError, 'backend'):
            collector.collect_static(remote, spawn_for(remote),
                ROLE_PATHS['remote'][0], ROLE_PATHS['remote'][1],
                'a' * 64, expected_argv=(remote.runtime_executable, '--serve'))


if __name__ == '__main__':
    unittest.main()
