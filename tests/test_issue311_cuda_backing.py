"""Bounded CUDA selective-backing prerequisite regressions (#311/#313/#315).

Pure identity/admission coverage on synthetic fixtures: the reviewed CPU pair
stays exactly as accepted, the explicitly reviewed one-GPU pair becomes
expressible only through a reviewed CUDA worker identity, unqualified or
missing CUDA identities refuse, unsupported placement still refuses, and
candidate build receipts never masquerade as accepted identities. No CUDA
compilation, GPU access, model bytes or inference happens here.
"""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'scripts'))

from inferswarm.operator import assigned_backing
from inferswarm.operator.assigned_backing import (CONTRACT, CPU_BACKEND, CUDA_BACKEND,
    HISTORICAL_BUILD_PAIR, STEP_A_BUILD_PAIR, role_identity, role_key)
from inferswarm.operator.config import parse_config
from inferswarm.operator.phased_observation import parse_build_manifest
from inferswarm.operator.plan import build_plan
from tests.test_issue299_q8_plan import q8_mapping
from tests.issue299_fixture import NOW, reseal_profiles, profile_digest, sha

CUDA_RECIPE = ROOT/'tools/native-cache/operator-build-cuda.py'
CPU_RECIPE = ROOT/'tools/native-cache/operator-build.py'
IDENTITY_TABLE = ROOT/'tools/native-cache/operator-build-identities.json'

OBSERVER = dict(client_manifest_path='/reviewed/client.json', client_executable_path='/reviewed/llama-server',
    remote_manifest_path='/reviewed/remote.json', remote_executable_path='/reviewed/ggml-rpc-server')


def synthetic_cuda_manifest(executable='c'*64, libraries=(('ggml/src/ggml-cuda/libggml-cuda.a','1'*64),('ggml/src/libggml-base.a','2'*64))):
    """Clearly synthetic CUDA worker manifest body; never a reviewed build."""
    from inferswarm.operator.native_observer.producer import build_manifest_body
    return build_manifest_body(executable_sha256=executable, backend_libraries=libraries,
        patch_sha256='3'*64, transformed_manifest_sha256='4'*64,
        compiler='synthetic nvcc fixture', options=('-DCMAKE_BUILD_TYPE=Debug','-DGGML_RPC=ON','-DGGML_CUDA=ON'))


def load_recipe(path):
    spec = importlib.util.spec_from_file_location('recipe_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_table(cuda_manifest=None):
    table = copy.deepcopy(assigned_backing.identities())
    if cuda_manifest is not None:
        table['roles']['remote-cuda'] = dict(identity=cuda_manifest)
    return table


def selective_mapping(selection, remote_sha, client_sha=None):
    """A /3 config wiring the selective contract with per-role runtime hashes."""
    raw = q8_mapping(selection)
    options = raw['strategy_options']
    options.update(source_contract=CONTRACT, rpc_cache='enabled',
        participant_backing=dict(epoch=1, memory_id='B-disk', limit_bytes=256<<30,
            min_free_bytes=1<<30, reserve_bytes=128<<30),
        observer=dict(OBSERVER))
    raw['participants'][1]['backing'] = []
    for row in raw['placement']:
        if row['binding_id'] == 'binding-A-cpu':
            continue
        for span in row['state_ranges']:
            raw['participants'][1]['cache_ranges'].append(dict(
                state_id=span['state_id'], member=span['member'], offset=span['offset'],
                length=span['length'], sha256=sha({'synthetic': span['state_id']}),
                cache_key=format(len(raw['participants'][1]['cache_ranges'])+1, '016x'),
                source_id=raw['model']['source_id'], revision=raw['model']['revision'],
                representation='Q8_0', unit_id=row['unit_id']))
    raw['participants'][0]['runtime_sha256'] = client_sha or role_identity('client').executable_sha256
    raw['participants'][1]['runtime_sha256'] = remote_sha
    return raw


def rejoin_profiles(raw):
    snapshot = raw['profiles']['snapshot']
    for runtime in snapshot['runtime_capabilities']:
        p = next(p for p in raw['participants'] if p['host_id'] == runtime['host_id'])
        runtime['binary_sha256'] = p['runtime_sha256']
        e = next(e for e in snapshot['evidence'] if e['evidence_id'] == runtime['evidence_id'])
        e['dependencies']['runtime:'+runtime['runtime_id']+':binary_sha256'] = p['runtime_sha256']
    reseal_profiles(snapshot)
    raw['profiles']['digest'] = profile_digest(snapshot)
    return raw


def step_a_bodies():
    return {role: json.loads((assigned_backing.STEP_A_MANIFESTS/name).read_text())
            for role,name in (('client','cpu05-llama-server.build-manifest.json'),
                              ('remote','cuda03-ggml-rpc-server.build-manifest.json'))}


def step_a_mapping():
    pair = assigned_backing.step_a_identities()
    raw = selective_mapping('one-gpu', pair['remote'].executable_sha256,
                            pair['client'].executable_sha256)
    raw['strategy_options']['build_pair'] = STEP_A_BUILD_PAIR
    return raw


class StepABuildPairTests(unittest.TestCase):
    """Exact uploaded descriptions; offline checks do not qualify hardware."""

    def build(self, raw):
        return build_plan(parse_config(rejoin_profiles(raw), now=NOW, profile_mode='replay'), now=NOW)

    def test_complete_uploaded_manifests_and_historical_bytes(self):
        pins = (('cpu05-llama-server.build-manifest.json',
                 'dffc6a2ce7028a973a41949aac094f39dbc8d7884abfca25ba3430d0d4a7a01c'),
                ('cuda03-ggml-rpc-server.build-manifest.json',
                 'e08ea250e56823072a5582a28e77edfe34774dafe0c3d8a0568f24274152f47d'))
        for name,digest in pins:
            self.assertEqual(hashlib.sha256((assigned_backing.STEP_A_MANIFESTS/name).read_bytes()).hexdigest(),digest)
        rows=(assigned_backing.STEP_A_MANIFESTS/'SHA256SUMS').read_text().splitlines()
        self.assertEqual({row.split()[1] for row in rows},{'README.md',*(name for name,_ in pins)})
        for row in rows:
            digest,name=row.split()
            self.assertEqual(hashlib.sha256((assigned_backing.STEP_A_MANIFESTS/name).read_bytes()).hexdigest(),digest)
        self.assertEqual(hashlib.sha256(IDENTITY_TABLE.read_bytes()).hexdigest(),
            '1e1c0d19788487a45a7c0183ae8dd1c7574fea697203237d05780caee022f5d8')
        pair = assigned_backing.step_a_identities()
        self.assertEqual(pair['client'].executable_sha256,
            '91f7ada4cb5d9805a292ec14b56518f80cb1b550834f30f225aeed676fcd518e')
        self.assertEqual(pair['remote'].executable_sha256,
            '46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73')
        for role,backend in (('client',CPU_BACKEND),('remote',CUDA_BACKEND)):
            self.assertEqual(role_identity(role,backend,build_pair=STEP_A_BUILD_PAIR),pair[role])
        self.assertEqual(role_identity('client'),role_identity('client',build_pair=HISTORICAL_BUILD_PAIR))
        self.assertEqual(role_identity('remote'),role_identity('remote',build_pair=HISTORICAL_BUILD_PAIR))

    def test_explicit_pair_admission_and_preparation_projection(self):
        from inferswarm.operator.source import q8_source_payload
        plan = self.build(step_a_mapping())
        self.assertEqual(dict(plan.strategy_options)['build_pair'],STEP_A_BUILD_PAIR)
        self.assertFalse(plan.admission.execution_ready)
        payload = q8_source_payload(plan)
        self.assertEqual(payload['prepared_metadata']['runtime']['executable_sha256'],
                         assigned_backing.step_a_identities()['remote'].executable_sha256)
        self.assertEqual(payload['participants'][1]['backing'],[])
        self.assertEqual(len(payload['participants'][0]['backing']),6)
        self.assertTrue(payload['prepared_metadata']['tensors'])

    def test_preparation_adapter_keeps_selected_worker_runtime_on_restart(self):
        from tests.test_issue299_source import Q8Source
        from issue99_artifact_core import LocalFileSource
        from issue311_native_backing import prepare_q8_participant
        from issue311_preparation import StreamingNode, StreamingArtifactCache, DiskBudget
        fixture=Q8Source(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.cached()
        bodies=step_a_bodies()
        # The archives contain no executable bytes: use the existing compact
        # source fixture's executable, never label it a physical Step A build.
        bodies['remote']['executable_sha256']=fixture.remote['runtime_sha256']
        pair={role:parse_build_manifest(body) for role,body in bodies.items()}
        node=StreamingNode('B',StreamingArtifactCache(fixture.root/'step-a-backing'))
        origin=LocalFileSource(source_id='origin',root=fixture.root)
        with patch.object(assigned_backing,'step_a_identities',return_value=pair):
            runtime=role_identity('remote',CUDA_BACKEND,build_pair=STEP_A_BUILD_PAIR)
            def prepare(node):
                return prepare_q8_participant(payload=fixture.payload,epoch=1,
                    executable=fixture.runtime,executable_sha256=runtime.executable_sha256,
                    node=node,origin_source=origin,budget=DiskBudget(4<<20,0,32768))
            cold=prepare(node)
            warm=prepare(StreamingNode('B',StreamingArtifactCache(node.cache.root)))
        self.assertGreater(cold['acquisition_bytes'],0)
        self.assertEqual(warm['acquisition_bytes'],0)
        self.assertEqual(cold['runtime']['executable_sha256'],runtime.executable_sha256)
        self.assertEqual(warm['runtime'],cold['runtime'])

    def test_unknown_selector_and_mixed_pairs_refuse(self):
        raw = step_a_mapping()
        raw['strategy_options']['build_pair']='unreviewed-pair'
        with self.assertRaisesRegex(ValueError,'unknown selective backing build pair'):
            self.build(raw)
        for role in ('client','remote'):
            raw = step_a_mapping()
            next(p for p in raw['participants'] if p['role']==role)['runtime_sha256']=role_identity(role).executable_sha256
            with self.subTest(role=role), self.assertRaisesRegex(ValueError,'unreviewed per-role runtime identity'):
                self.build(raw)
        raw = step_a_mapping()
        del raw['strategy_options']['build_pair']
        with self.assertRaisesRegex(ValueError,'unreviewed per-role runtime identity'):
            self.build(raw)

    def test_wrong_backend_incomplete_pair_and_required_options_refuse(self):
        pair = assigned_backing.step_a_identities()
        raw = selective_mapping('cpu-only',pair['remote'].executable_sha256,pair['client'].executable_sha256)
        raw['strategy_options']['build_pair']=STEP_A_BUILD_PAIR
        with self.assertRaisesRegex(ValueError,'wrong backend'):
            self.build(raw)
        raw=step_a_mapping()
        with tempfile.TemporaryDirectory() as td:
            # Even a client lookup must refuse the missing second participant.
            name='cpu05-llama-server.build-manifest.json'
            (Path(td)/name).write_bytes((assigned_backing.STEP_A_MANIFESTS/name).read_bytes())
            with patch.object(assigned_backing,'STEP_A_MANIFESTS',Path(td)):
                with self.assertRaisesRegex(ValueError,'incomplete Step A build pair'):
                    self.build(raw)
                with self.assertRaisesRegex(ValueError,'incomplete Step A build pair'):
                    role_identity('client',build_pair=STEP_A_BUILD_PAIR)
        for field,value in (('observer',None),('rpc_cache','disabled'),('route','server-local')):
            raw=step_a_mapping()
            if value is None: del raw['strategy_options'][field]
            else: raw['strategy_options'][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.build(raw)

    def test_collector_compares_every_identity_field_and_pair(self):
        from inferswarm.operator.native_observer.collector import NativeObserverCollector, CollectorError
        from tests.test_issue302_collected_runner import VirtualHostTree, RecordingCollectorTransport
        bodies=step_a_bodies()
        tree=VirtualHostTree()
        # Binary bytes are host-retained, so only the executable in this offline
        # fixture is synthetic; all other fields come from the exact manifests.
        for role in bodies:
            data=('synthetic Step A '+role).encode()
            bodies[role]['executable_sha256']=hashlib.sha256(data).hexdigest()
            tree.put(role,'/exe',data)
        expected={role:parse_build_manifest(body) for role,body in bodies.items()}
        collector=NativeObserverCollector(RecordingCollectorTransport(tree),selective=True)
        mutations={
            'schema':lambda b:b.update(schema='unknown/1'),
            'base_revision':lambda b:b.update(base_revision='a'*40),
            'base_tree':lambda b:b.update(base_tree='a'*40),
            'patch_sha256':lambda b:b.update(patch_sha256='a'*64),
            'transformed_manifest_sha256':lambda b:b.update(transformed_manifest_sha256='a'*64),
            'protocol':lambda b:b.update(protocol='other/2'),
            'compiler':lambda b:b.update(compiler='other compiler'),
            'build_options':lambda b:b['build_options'].append('-DGGML_NATIVE=ON'),
            'path_option':lambda b:b['build_options'].append('-DCMAKE_CUDA_COMPILER=/other/nvcc'),
            'executable_sha256':lambda b:b.update(executable_sha256='a'*64),
            'library_digest':lambda b:b['backend_libraries'][0].update(sha256='a'*64),
            'library_name':lambda b:b['backend_libraries'][0].update(name='other.a'),
            'library_closure':lambda b:b['backend_libraries'].pop(),
        }
        with patch.object(assigned_backing,'step_a_identities',return_value=expected):
            for role,backend in (('client',CPU_BACKEND),('remote',CUDA_BACKEND)):
                participant=SimpleNamespace(role=role,participant_id=role,execution_address=role,
                                            runtime_sha256=expected[role].executable_sha256)
                def collect(pair=STEP_A_BUILD_PAIR, selected_backend=backend):
                    return collector.collect_build(participant,'/manifest','/exe',backend=selected_backend,build_pair=pair)
                tree.put(role,'/manifest',bodies[role])
                self.assertEqual(collect().manifest,expected[role])
                for selector in (HISTORICAL_BUILD_PAIR,'unknown'):
                    with self.assertRaises((ValueError,CollectorError)): collect(selector)
                with self.assertRaises((ValueError,CollectorError)):
                    collect(selected_backend=CUDA_BACKEND if role=='client' else CPU_BACKEND)
                for name,mutate in mutations.items():
                    body=copy.deepcopy(bodies[role]); mutate(body); tree.put(role,'/manifest',body)
                    with self.subTest(role=role,field=name), self.assertRaises((ValueError,CollectorError)): collect()


class RoleIdentitySelectionTests(unittest.TestCase):
    """Synthetic identity-table selection, refusal and CPU-pair preservation."""

    def test_cpu_pair_keys_and_identities_unchanged(self):
        table = assigned_backing.identities()
        self.assertEqual(sorted(table['roles']), ['client', 'remote'])
        self.assertEqual(role_key('remote'), 'remote')
        self.assertEqual(role_key('client', CPU_BACKEND), 'client')
        self.assertEqual(role_identity('client').executable_sha256,
                         table['roles']['client']['identity']['executable_sha256'])
        self.assertEqual(role_identity('remote').executable_sha256,
                         table['roles']['remote']['identity']['executable_sha256'])
        # The accepted table carries no CUDA row and no CUDA backend option.
        self.assertNotIn('remote-cuda', table['roles'])
        self.assertNotIn('GGML_CUDA=ON', json.dumps(table))

    def test_cuda_identity_is_backend_qualified_and_refuses_when_absent(self):
        self.assertEqual(role_key('remote', CUDA_BACKEND), 'remote-cuda')
        with self.assertRaisesRegex(ValueError, 'no accepted cuda build'):
            role_identity('remote', CUDA_BACKEND)
        with self.assertRaisesRegex(ValueError, 'no supported native build backend'):
            role_identity('client', CUDA_BACKEND)
        with self.assertRaisesRegex(ValueError, 'unsupported native build backend'):
            role_identity('remote', 'vulkan')

    def test_reviewed_synthetic_cuda_identity_selects(self):
        manifest = synthetic_cuda_manifest()
        with patch.object(assigned_backing, 'identities', return_value=synthetic_table(manifest)):
            identity = role_identity('remote', CUDA_BACKEND)
        self.assertEqual(identity.executable_sha256, manifest['executable_sha256'])
        self.assertIn('-DGGML_CUDA=ON', identity.build_options)
        self.assertTrue(any('ggml-cuda' in name for name, _ in identity.backend_libraries))

    def test_cpu_row_is_not_reinterpreted_as_cuda_identity(self):
        table = assigned_backing.identities()
        cpu_row = table['roles']['remote']
        # The accepted CPU remote row placed under the CUDA key must refuse:
        # its options and library closure are CPU build facts.
        with patch.object(assigned_backing, 'identities',
                          return_value={**copy.deepcopy(table), 'roles': {**table['roles'], 'remote-cuda': cpu_row}}):
            with self.assertRaisesRegex(ValueError, 'is not a reviewed CUDA'):
                role_identity('remote', CUDA_BACKEND)

    def test_caller_supplied_hash_is_not_approval(self):
        # A caller cannot make an arbitrary executable accepted by passing its
        # hash: validation compares config hashes against the reviewed table,
        # and an unreviewed CUDA entry refuses regardless of caller input.
        manifest = synthetic_cuda_manifest(executable='e'*64)
        with patch.object(assigned_backing, 'identities', return_value=synthetic_table(None)):
            raw = selective_mapping('one-gpu', 'e'*64)
            with self.assertRaisesRegex(ValueError, 'unreviewed per-role runtime identity'):
                build_plan(parse_config(rejoin_profiles(raw), now=NOW, profile_mode='replay'), now=NOW)


class SelectiveAdmissionTests(unittest.TestCase):
    """Option validation and admission for the explicit one-GPU pair."""

    def build(self, raw):
        return build_plan(parse_config(rejoin_profiles(raw), now=NOW, profile_mode='replay'), now=NOW)

    def selective_contract_of(self, plan):
        return plan.candidate.semantic_contract[0].options if hasattr(
            plan.candidate.semantic_contract[0], 'options') else None

    def test_cpu_pair_regression_selective_startup_unchanged(self):
        # The merged #318 CPU contract keeps admitting exactly as before.
        raw = selective_mapping('cpu-only', role_identity('remote').executable_sha256)
        plan = self.build(raw)
        contract = plan.candidate.semantic_contract[0]
        self.assertEqual(contract.selection, 'cpu-only')
        self.assertFalse(plan.admission.execution_ready)
        options = {k: v for k, v in plan.candidate.canonical_strategy_options.items()} if isinstance(
            plan.candidate.canonical_strategy_options, dict) else dict(plan.candidate.canonical_strategy_options)
        self.assertEqual(options.get('source_contract'), CONTRACT)

    def test_one_gpu_selective_refuses_until_cuda_identity_reviewed(self):
        raw = selective_mapping('one-gpu', role_identity('remote').executable_sha256)
        with self.assertRaisesRegex(ValueError, 'unreviewed per-role runtime identity'):
            self.build(raw)

    def test_one_gpu_selective_builds_with_reviewed_synthetic_identity(self):
        manifest = synthetic_cuda_manifest()
        with patch.object(assigned_backing, 'identities', return_value=synthetic_table(manifest)):
            raw = selective_mapping('one-gpu', manifest['executable_sha256'])
            plan = self.build(raw)
        self.assertEqual(plan.selection, 'one-gpu')
        self.assertFalse(plan.admission.execution_ready)
        self.assertEqual(plan.candidate.semantic_contract[0].selection, 'one-gpu')

    def test_wrong_executable_or_library_closure_refuses(self):
        manifest = synthetic_cuda_manifest()
        wrong_executable = synthetic_cuda_manifest(executable='d'*64)
        with patch.object(assigned_backing, 'identities', return_value=synthetic_table(manifest)):
            with self.assertRaisesRegex(ValueError, 'unreviewed per-role runtime identity'):
                self.build(selective_mapping('one-gpu', wrong_executable['executable_sha256']))
        # A reviewed row whose declared closure is not a CUDA closure cannot
        # serve as the CUDA identity either (backend-qualified selection).
        cpu_libraries = (('ggml/src/libggml-base.a','2'*64),)
        cpu_closure_manifest = synthetic_cuda_manifest(libraries=cpu_libraries)
        with patch.object(assigned_backing, 'identities', return_value=synthetic_table(cpu_closure_manifest)):
            with self.assertRaisesRegex(ValueError, 'is not a reviewed CUDA'):
                role_identity('remote', CUDA_BACKEND)

    def test_one_gpu_server_local_placement_still_refused(self):
        manifest = synthetic_cuda_manifest()
        with patch.object(assigned_backing, 'identities', return_value=synthetic_table(manifest)):
            raw = selective_mapping('one-gpu', manifest['executable_sha256'])
            raw['strategy_options']['route'] = 'server-local'
            for runtime in raw['profiles']['snapshot']['runtime_capabilities']:
                runtime['route'] = 'server-local'
                e = next(e for e in raw['profiles']['snapshot']['evidence'] if e['evidence_id'] == runtime['evidence_id'])
                e['dependencies']['runtime:'+runtime['runtime_id']+':route'] = 'server-local'
            with self.assertRaisesRegex(ValueError, 'client-mediated copy route'):
                self.build(raw)

    def test_collector_binds_backend_identity(self):
        from inferswarm.operator.native_observer.collector import NativeObserverCollector, CollectorError

        class Local:
            def read_json(self, address, path, **kwargs): return json.loads(Path(path).read_text())
            def read_bytes(self, address, path, **kwargs): return Path(path).read_bytes()

        manifest = copy.deepcopy(synthetic_cuda_manifest())
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td)/'worker'
            executable.write_bytes(b'x'*(1 << 20))
            manifest['executable_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
            path = Path(td)/'manifest.json'
            path.write_text(json.dumps(manifest))
            participant = SimpleNamespace(role='remote', participant_id='B',
                execution_address='B', runtime_sha256=manifest['executable_sha256'])
            collector = NativeObserverCollector(transport=Local(), selective=True)
            with patch.object(assigned_backing, 'identities', return_value=synthetic_table(manifest)):
                evidence = collector.collect_build(participant, str(path), str(executable), backend=CUDA_BACKEND)
                self.assertEqual(evidence.executable_sha256, manifest['executable_sha256'])
                # The accepted CPU remote identity cannot answer a CUDA role.
                with self.assertRaises((CollectorError, ValueError)):
                    collector.collect_build(participant, str(path), str(executable), backend=CPU_BACKEND)
            # Without a reviewed CUDA row even the right bytes refuse.
            with patch.object(assigned_backing, 'identities', return_value=synthetic_table(None)):
                with self.assertRaises((CollectorError, ValueError)):
                    collector.collect_build(participant, str(path), str(executable), backend=CUDA_BACKEND)


class BuildReceiptSeparationTests(unittest.TestCase):
    """Candidate CUDA receipts and build configuration stay separate."""

    def test_cuda_recipe_writes_receipt_only(self):
        source = CUDA_RECIPE.read_text()
        self.assertIn('cuda-worker-receipt.json', source)
        self.assertIn('not an accepted runtime identity', source)
        # The recipe writes only inside its own owned output directory: the
        # identity table path never appears in code (docstrings excluded).
        code = source.split('"""')[2]
        self.assertNotIn('operator-build-identities', code)
        self.assertNotIn('IDENTITIES', code)
        table = json.loads(IDENTITY_TABLE.read_text())
        self.assertNotIn('remote-cuda', table['roles'])
        self.assertNotIn('GGML_CUDA=ON', json.dumps(table))
        # The accepted CPU recipe bytes are untouched: its patch_sha256 in the
        # accepted table covers native.patch + assigned.h + operator-build.py.
        blob = ((ROOT/'tools/native-cache/native.patch').read_bytes()
                + (ROOT/'tools/native-cache/assigned.h').read_bytes()
                + CPU_RECIPE.read_bytes())
        self.assertEqual(hashlib.sha256(blob).hexdigest(), table['patch_sha256'])

    def test_cpu_recipe_bytes_are_not_edited(self):
        # patch_sha256 of the accepted pair covers operator-build.py bytes;
        # confirm the file still hashes the same as the identity-embedded pin
        # implies by simply containing the exact historical option list.
        cpu = CPU_RECIPE.read_text()
        self.assertIn("'-DGGML_CUDA=OFF'", cpu)
        module = load_recipe(CPU_RECIPE)
        options = module.cpu_build_options(CPU_RECIPE) if hasattr(module, 'cpu_build_options') else None
        self.assertIsNone(options)

    def test_cuda_options_derive_from_cpu_recipe_and_pin_cmake(self):
        module = load_recipe(CUDA_RECIPE)
        base = module.cpu_build_options(CPU_RECIPE)
        self.assertIn('-DGGML_CUDA=OFF', base)  # extraction is faithful
        options = module.cuda_options(base, '86',
            '/synthetic/toolkit', ['-DCUDA_CUDA_LIBRARY=/synthetic/libcuda.so.1'])
        self.assertNotIn('-DGGML_CUDA=OFF', options)
        self.assertEqual(options.count('-DGGML_CUDA=ON'), 1)
        self.assertIn('-DCMAKE_CUDA_ARCHITECTURES=86', options)
        self.assertIn('-DCMAKE_CUDA_COMPILER=/synthetic/toolkit/bin/nvcc', options)
        self.assertIn('-DCUDA_CUDA_LIBRARY=/synthetic/libcuda.so.1', options)
        # CPU-only switches unrelated to the backend are preserved verbatim.
        for kept in ('-DGGML_RPC=ON', '-DGGML_VULKAN=OFF', '-DLLAMA_BUILD_TOOLS=ON'):
            self.assertIn(kept, options)

    def test_driver_resolution_reuses_shared_stub_refusing_probe(self):
        import ast as _ast
        source = CUDA_RECIPE.read_text()
        # Driver resolution delegates to the shared corrected probe instead
        # of duplicating stub logic.
        functions = [n for n in _ast.walk(_ast.parse(source))
                     if isinstance(n, _ast.FunctionDef) and n.name == 'driver_resolution']
        self.assertEqual(len(functions), 1)
        body = _ast.get_source_segment(source, functions[0])
        self.assertIsNotNone(body)
        self.assertIn('cuda_driver_flags', body)
        self.assertNotIn("'stubs'", body)
        module = load_recipe(CUDA_RECIPE)
        self.assertTrue(callable(module.driver_resolution))
        self.assertTrue(callable(module.cpu_build_options))
        # Stub refusal is inherited from the shared probe, verified directly.
        probe = load_recipe(ROOT/'tools/moe-overlap/build.py')
        with tempfile.TemporaryDirectory() as td:
            stub = Path(td)/'stubs'/'libcuda.so'
            stub.parent.mkdir(); stub.write_bytes(b'\x7fELF'+b'\0'*64)
            with patch.dict('os.environ', {'MOE_OVERLAP_CUDA_DRIVER': str(stub)}):
                with self.assertRaises(SystemExit):
                    probe.cuda_driver_flags('c++')


class SelectiveStaticCollectionTests(unittest.TestCase):
    def test_actual_runner_keeps_role_backend_through_static_collection(self):
        """Real runner + collector; only host reads/processes are synthetic.

        Build checks must finish for both roles before the real reconciler
        refuses the synthetic source receipt, with zero requests and cleanup.
        """
        from inferswarm.operator.bindings import ProcessIdentity
        from inferswarm.operator.native_observer.collector import NativeObserverCollector
        from inferswarm.operator.phased_observation import OwnedSpawnFacts
        from inferswarm.operator.profiles import freeze
        from inferswarm.operator.qwen_q8 import q8_candidates, bound_capability
        from tests.test_issue299_q8_plan import metadata
        from tests.test_issue302_collected_runner import (
            RecordingRunnerHarness, VirtualHostTree, RecordingCollectorTransport)
        from tests.test_issue302_per_role_builds import RecordingHostFactsReader

        table = synthetic_table()
        client_bytes = b'synthetic CPU coordinator'
        client_sha = hashlib.sha256(client_bytes).hexdigest()
        table['roles']['client']['identity']['executable_sha256'] = client_sha
        for selection,build_pair in (('cpu-only',HISTORICAL_BUILD_PAIR),
                                     ('one-gpu',HISTORICAL_BUILD_PAIR),
                                     ('one-gpu',STEP_A_BUILD_PAIR)):
            with self.subTest(selection=selection,build_pair=build_pair):
                remote_bytes = ('synthetic remote '+selection).encode()
                remote_sha = hashlib.sha256(remote_bytes).hexdigest()
                key = 'remote' if selection == 'cpu-only' else 'remote-cuda'
                if selection == 'one-gpu':
                    table['roles'][key] = dict(identity=synthetic_cuda_manifest(executable=remote_sha))
                else:
                    table['roles'][key]['identity']['executable_sha256'] = remote_sha
                bodies=step_a_bodies()
                bodies['client']['executable_sha256']=client_sha
                bodies['remote']['executable_sha256']=remote_sha
                step_a_pair={role:parse_build_manifest(body) for role,body in bodies.items()}
                with patch.object(assigned_backing, 'identities', return_value=table), patch.object(
                        assigned_backing,'step_a_identities',return_value=step_a_pair):
                    raw = selective_mapping(selection, remote_sha, client_sha)
                    if build_pair==STEP_A_BUILD_PAIR:
                        raw['strategy_options']['build_pair']=build_pair
                    candidate, = q8_candidates(parse_config(rejoin_profiles(raw), now=NOW,
                        profile_mode='replay'), metadata())
                    snapshot = raw['profiles']['snapshot']
                    runtimes = {r['runtime_id']: r for r in snapshot['runtime_capabilities']}
                    memories = {m['memory_id']: m for m in snapshot['memory_resources']}
                    for requirement in candidate.capability_requirements:
                        runtimes[requirement.runtime_id]['capabilities'].append(requirement.capability)
                    for charge in candidate.charges:
                        if charge.bytes is not None: continue
                        runtime = next(r for r in runtimes.values() if r['host_id']==memories[charge.memory_id]['host_id'])
                        amount = 2**21  # Synthetic witness only, never a hardware fit claim.
                        raw['strategy_options']['bounds'].append(dict(allocation_id=charge.allocation_id,
                            bytes=amount, evidence_id=runtime['evidence_id']))
                        runtime['capabilities'].append(bound_capability(charge, amount))
                        evidence = next(e for e in snapshot['evidence'] if e['evidence_id']==runtime['evidence_id'])
                        evidence['dependencies']['memory:'+charge.memory_id+':physical_id'] = memories[charge.memory_id]['physical_id']
                    plan = build_plan(parse_config(rejoin_profiles(raw), now=NOW, profile_mode='replay'), now=NOW)
                    harness = RecordingRunnerHarness(plan)
                    for receipt in harness.sources.values():
                        receipt['assigned_guard_path'] = '/synthetic/assigned-guard'
                    tree = VirtualHostTree()
                    for participant in plan.participants:
                        role = participant.role
                        tree.put(participant.execution_address, OBSERVER[role+'_manifest_path'],
                            bodies[role] if build_pair==STEP_A_BUILD_PAIR else
                            table['roles']['client' if role=='client' else key]['identity'])
                        tree.put(participant.execution_address, OBSERVER[role+'_executable_path'],
                            client_bytes if role=='client' else remote_bytes)

                    class IdentityReader:
                        def read(self, p, pid, *, expected_executable, expected_sha256, expected_argv):
                            row = harness.transport.rows[p.execution_address]['client' if p.role=='client' else 'rpc']
                            return ProcessIdentity(p.participant_id, p.host_id, p.boot_epoch, p.topology_epoch,
                                pid, str(row['start']), expected_executable, expected_sha256, tuple(expected_argv),
                                freeze(dict(native=[], visible=[], environment={})), p.rpc_endpoint)

                    collector = NativeObserverCollector(RecordingCollectorTransport(tree), IdentityReader(),
                        host_facts_reader=RecordingHostFactsReader(plan), selective=True)
                    runner = harness.runner(collector=collector)
                    with patch.object(collector,'collect_build',wraps=collector.collect_build) as builds:
                        with self.assertRaisesRegex(ValueError, 'selective participant provenance/verified-byte mismatch'):
                            runner.run(plan)
                    self.assertEqual([call.args[0].role for call in builds.call_args_list],
                                     ['remote','client','client','remote'])
                    self.assertTrue(all(call.kwargs.get('build_pair',HISTORICAL_BUILD_PAIR)==build_pair
                                        for call in builds.call_args_list))
                    self.assertEqual(harness.posts, 0)
                    self.assertTrue(all(row['lease']=='released' for row in runner.last_cleanup.values()))
                    # The public collector's omitted-backend default still
                    # qualifies a CPU role exactly as it did before this fix.
                    client = next(p for p in plan.participants if p.role=='client')
                    row = harness.transport.rows[client.execution_address]['client']
                    evidence = collector.collect_static(client, OwnedSpawnFacts(client.participant_id,
                        row['pid'], str(row['start']), harness.manager.token),
                        OBSERVER['client_manifest_path'], OBSERVER['client_executable_path'], '0'*64,
                        expected_argv=harness.transport.argv[client.execution_address],
                        **({'build_pair':build_pair} if build_pair==STEP_A_BUILD_PAIR else {}))
                    self.assertEqual(evidence.build.manifest, role_identity('client',build_pair=build_pair))


class DriverResolutionTests(unittest.TestCase):
    """Real CPU linker, synthetic ELF libraries; no driver/device/CUDA build."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.recipe = load_recipe(CUDA_RECIPE)
        self.probe = load_recipe(ROOT/'tools/moe-overlap/build.py')
        self.cxx = self.probe.pick_compiler('c++')
        self.driver = self.root/'libcuda.so.1'
        subprocess.run([self.cxx, '-shared', '-fPIC', '-x', 'c++', '-',
                        '-o', str(self.driver)],
                       input='extern "C" void cuMemCreate() {}\n',
                       text=True, check=True, timeout=30)
        (self.root/'libcuda.so').symlink_to(self.driver.name)

    def test_development_driver_success_binds_validated_filename(self):
        # Exercise both shared-probe success branches: an explicit linker
        # directory and the compiler's search path. Its legacy result remains
        # ['-lcuda']; the CMake adapter must retain the validated real filename.
        empty = self.root/'empty'; empty.mkdir()
        environment = dict(os.environ, LIBRARY_PATH=str(self.root))
        environment.pop('MOE_OVERLAP_CUDA_DRIVER', None)
        with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(io.StringIO()):
            for directory in (self.root, empty):
                with self.subTest(directory=directory), patch.object(
                        self.probe, 'CUDA_LIB_FLAGS', ['-L'+str(directory)]):
                    self.assertEqual(self.probe.cuda_driver_flags(self.cxx), ['-lcuda'])
                    record, options = self.recipe.driver_resolution(self.cxx, self.probe)
                    self.assertEqual(record['resolved_path'], str(self.driver))
                    self.assertEqual(record['resolved_sha256'], hashlib.sha256(self.driver.read_bytes()).hexdigest())
                    self.assertEqual(options, ['-DCUDA_CUDA_LIBRARY='+str(self.driver)])

    def test_explicit_runtime_driver_retains_resolved_path(self):
        with patch.dict(os.environ, {'MOE_OVERLAP_CUDA_DRIVER': str(self.root/'libcuda.so')}), contextlib.redirect_stdout(io.StringIO()):
            record, options = self.recipe.driver_resolution(self.cxx, self.probe)
        self.assertEqual(record['resolved_path'], str(self.driver))
        self.assertEqual(options, ['-DCUDA_CUDA_LIBRARY='+str(self.driver)])

    def test_invalid_driver_paths_still_refuse(self):
        stub = self.root/'stubs'/'libcuda.so'
        stub.parent.mkdir(); stub.write_bytes(self.driver.read_bytes())
        alias = self.root/'libcuda-stub-alias.so'; alias.symlink_to(stub)
        text = self.root/'not-elf.so'; text.write_text('not ELF')
        wrong = self.root/'wrong-symbol.so'
        subprocess.run([self.cxx, '-shared', '-fPIC', '-x', 'c++', '-', '-o', str(wrong)],
                       input='extern "C" void unrelated() {}\n', text=True, check=True, timeout=30)
        for driver, reason in ((stub, 'stub'), (alias, 'stub'), (text, 'ELF'),
                               (wrong, 'link probe failed'), (self.root/'missing.so', 'not a file')):
            with self.subTest(driver=driver), patch.dict(os.environ, {'MOE_OVERLAP_CUDA_DRIVER': str(driver)}):
                with self.assertRaisesRegex(SystemExit, reason):
                    self.recipe.driver_resolution(self.cxx, self.probe)




class OptimizedCpuPrerequisiteTests(unittest.TestCase):
    """Offline candidate recipe and finite reviewed-pair handoff; no native build."""

    def recipe(self):
        path = ROOT/'tools/native-cache/operator-build-cpu-optimized.py'
        self.assertTrue(path.is_file(), 'additive optimized CPU recipe missing')
        return load_recipe(path)

    def flags_fixture(self, binary, suffix=''):
        binary.mkdir(parents=True, exist_ok=True)
        m = self.recipe()
        options = m.optimized_options()
        cache = '\n'.join(o[2:].split('=', 1)[0]+':STRING='+o.split('=', 1)[1]
                          for o in options)
        (binary/'CMakeCache.txt').write_text(cache+'\nCMAKE_C_FLAGS:STRING=\nCMAKE_CXX_FLAGS:STRING=\n'
            'CMAKE_C_COMPILER:FILEPATH=/synthetic/cc\nCMAKE_CXX_COMPILER:FILEPATH=/synthetic/c++\n')
        rows = [dict(file='fixture.'+ext, directory=str(binary),
                     arguments=[compiler, '-O3', '-g0', *suffix.split(), '-c', 'fixture.'+ext])
                for ext,compiler in (('c','cc'),('cpp','c++'))]
        (binary/'compile_commands.json').write_text(json.dumps(rows))
        return rows

    def test_optimized_options_change_only_optimization_and_export_metadata(self):
        m = self.recipe()
        base = load_recipe(CUDA_RECIPE).cpu_build_options(CPU_RECIPE)
        expected = [o.replace('=-O0 -g0', '=-O3 -g0') for o in base]
        self.assertEqual(m.optimized_options(), expected+['-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'])
        self.assertEqual(m.cpu.compose.__code__.co_code, load_recipe(CPU_RECIPE).compose.__code__.co_code)
        self.assertEqual(m.cpu.PIN, 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4')

    def test_effective_flags_cannot_retain_o0_or_disable_assertions(self):
        m = self.recipe()
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td)/'build'
            self.flags_fixture(binary)
            report = m.inspect_effective_flags(binary)
            self.assertEqual(report['translation_units'], 2)
            for bad in ('-O0', '-O2', '-DNDEBUG', '-DNDEBUG=1', '-Wp,-DNDEBUG'):
                self.flags_fixture(binary, bad)
                with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'effective CPU flags'):
                    m.inspect_effective_flags(binary)
            self.flags_fixture(binary)
            (binary/'compile_commands.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'compile commands'):
                m.inspect_effective_flags(binary)

    def test_candidate_receipts_complete_separate_and_no_overwrite(self):
        m = self.recipe()
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)/'candidate'
            def compose(archive, out):
                out.mkdir(exist_ok=False)
                source = out/'source'; source.mkdir()
                return source, '4'*64
            def run(command, **kwargs):
                binary = output/'build'
                if '--build' not in command:
                    self.flags_fixture(binary)
                else:
                    (binary/'bin').mkdir()
                    for name in ('llama-server','ggml-rpc-server','is311-loader'):
                        (binary/'bin'/name).write_bytes(('synthetic '+name).encode())
                    for name in ('ggml/src/libggml-base.a','src/libllama.a'):
                        target = binary/name; target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(b'synthetic archive')
                return SimpleNamespace(returncode=0)
            before = {p:p.read_bytes() for p in [IDENTITY_TABLE, CPU_RECIPE,
                      *assigned_backing.STEP_A_MANIFESTS.glob('*')] if p.is_file()}
            with patch.object(m.cpu,'compose',side_effect=compose), \
                 patch.object(m.subprocess,'run',side_effect=run), \
                 patch.object(m.subprocess,'check_output',return_value='synthetic compiler\n') as versions:
                result = m.build('fixture.tar',output,'cmake')
                self.assertEqual(result['compiler_versions']['C']['path'], '/synthetic/cc')
                self.assertEqual(result['compiler_versions']['CXX']['path'], '/synthetic/c++')
                self.assertIn(unittest.mock.call(['/synthetic/c++','--version'],text=True),versions.call_args_list)
                self.assertIn('not an accepted runtime identity', result['note'])
                for role in ('client','remote'):
                    entry = result['roles'][role]
                    body = json.loads(Path(entry['manifest']).read_text())
                    identity = parse_build_manifest(body)
                    self.assertEqual(identity.executable_sha256, m.cpu.digest(entry['executable']))
                    self.assertEqual(identity.patch_sha256, assigned_backing.step_a_identities()['client'].patch_sha256)
                    self.assertTrue(identity.backend_libraries)
                    self.assertEqual(list(identity.build_options), m.optimized_options())
                self.assertEqual(result['effective_flags']['translation_units'], 2)
                self.assertEqual(result['loader_sha256'],m.cpu.digest(output/'build/bin/is311-loader'))
                with self.assertRaises(FileExistsError): m.build('fixture.tar',output,'cmake')
            for path,data in before.items(): self.assertEqual(path.read_bytes(),data)

    def test_bad_effective_flags_stop_before_build_or_manifest(self):
        m = self.recipe()
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)/'candidate'
            def compose(archive, out):
                out.mkdir(); source = out/'source'; source.mkdir()
                return source, '4'*64
            def configure(command, **kwargs):
                self.flags_fixture(output/'build','-O0')
            with patch.object(m.cpu,'compose',side_effect=compose), \
                 patch.object(m.subprocess,'run',side_effect=configure) as run:
                with self.assertRaisesRegex(ValueError,'effective CPU flags'):
                    m.build('synthetic.tar',output,'cmake')
                self.assertEqual(run.call_count,1)  # configure only; never native compilation
            self.assertFalse((output/'llama-server.build-manifest.json').exists())
            self.assertFalse((output/'optimized-cpu-receipt.json').exists())

    def test_unrecorded_optimized_pair_refuses_even_accepted_worker(self):
        selector = 'optimized-cpu05-cuda03'
        with self.assertRaisesRegex(ValueError, 'unreviewed optimized CPU'):
            role_identity('remote', CUDA_BACKEND, build_pair=selector)
        raw = step_a_mapping(); raw['strategy_options']['build_pair'] = selector
        with self.assertRaisesRegex(ValueError, 'unreviewed optimized CPU'):
            build_plan(parse_config(rejoin_profiles(raw),now=NOW,profile_mode='replay'),now=NOW)

    def test_explicit_reviewed_candidate_pair_and_mixed_identity_rejection(self):
        m = self.recipe()
        body = step_a_bodies()['client']
        body['build_options'] = m.optimized_options()
        body['executable_sha256'] = 'a'*64  # synthetic review fixture, never production authority
        selector = 'optimized-cpu05-cuda03'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'reviewed.json'; path.write_text(json.dumps(body))
            with patch.object(assigned_backing, 'OPTIMIZED_CPU_MANIFEST',path):
                self.assertEqual(role_identity('client',build_pair=selector),parse_build_manifest(body))
                self.assertEqual(role_identity('remote',CUDA_BACKEND,build_pair=selector),
                                 role_identity('remote',CUDA_BACKEND,build_pair=STEP_A_BUILD_PAIR))
                raw = step_a_mapping(); raw['strategy_options']['build_pair'] = selector
                raw['participants'][0]['runtime_sha256'] = body['executable_sha256']
                def plan(raw):
                    return build_plan(parse_config(rejoin_profiles(raw),now=NOW,profile_mode='replay'),now=NOW)
                self.assertEqual(dict(plan(copy.deepcopy(raw)).strategy_options)['build_pair'],selector)
                # Exercise the intended fixed two-GPU placement as well, without hardware.
                from tests.test_issue313_two_gpu import two_gpu_mapping
                from inferswarm.operator.source import q8_source_payload
                dual, _ = two_gpu_mapping()
                dual['strategy_options']['build_pair'] = selector
                dual['participants'][0]['runtime_sha256'] = body['executable_sha256']
                dual['participants'][1]['runtime_sha256'] = assigned_backing.step_a_identities()['remote'].executable_sha256
                dual_plan = plan(dual)
                self.assertEqual(dual_plan.selection,'two-gpu')
                self.assertFalse(dual_plan.admission.execution_ready)
                payload = q8_source_payload(dual_plan)
                self.assertEqual(payload['prepared_metadata']['runtime']['executable_sha256'],
                                 assigned_backing.step_a_identities()['remote'].executable_sha256)
                for role in ('client','remote'):
                    mixed = copy.deepcopy(raw)
                    mixed['participants'][0 if role=='client' else 1]['runtime_sha256'] = role_identity(role).executable_sha256
                    with self.subTest(role=role), self.assertRaisesRegex(ValueError,'unreviewed per-role runtime identity'):
                        plan(mixed)
                omitted = copy.deepcopy(raw); del omitted['strategy_options']['build_pair']
                with self.assertRaisesRegex(ValueError,'unreviewed per-role runtime identity'): plan(omitted)
                unknown = copy.deepcopy(raw); unknown['strategy_options']['build_pair']='unknown-optimized'
                with self.assertRaisesRegex(ValueError,'unknown selective backing build pair'): plan(unknown)
                for field,value in (('build_options',step_a_bodies()['client']['build_options']),
                                    ('patch_sha256','f'*64)):
                    bad = copy.deepcopy(body); bad[field]=value; path.write_text(json.dumps(bad))
                    with self.subTest(field=field), self.assertRaisesRegex(ValueError,'optimized CPU'):
                        role_identity('client',build_pair=selector)
                path.write_text(json.dumps(body))
                with self.assertRaisesRegex(ValueError,'wrong backend'):
                    role_identity('remote',CPU_BACKEND,build_pair=selector)


if __name__ == '__main__':
    unittest.main()
