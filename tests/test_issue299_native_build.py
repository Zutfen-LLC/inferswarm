"""Offline bounded substrate controls; no native build in the normal suite."""
import ctypes
import fcntl
import hashlib
import importlib
import time
from unittest import mock
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

# These controls never require the installed native checkout or campaign budget.
SOURCE = Path('nonexistent-native-source')


class NativeBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.b = importlib.import_module('inferswarm.operator.native_observer.build')
        except ModuleNotFoundError:
            cls.b = None

    def setUp(self):
        self.assertIsNotNone(self.b, 'supervised native builder is not implemented')
        self.tmp = tempfile.TemporaryDirectory(prefix='native-build-q1q3-')
        self.addCleanup(self.tmp.cleanup)
        self.workspace_root = Path(self.tmp.name).resolve()
        self.workspace = self.b.Workspace(self.workspace_root)
        self.root = self.workspace_root / 'run'
        self.source = self.workspace_root / SOURCE

    def supervisor(self, root=None, **kwargs):
        return self.b.Supervisor(root or self.root, workspace=self.workspace, **kwargs)

    def assembled(self, dest, target='cpu-rpc'):
        # Identity/version values attributed to pinned ggml CMake definitions;
        # this pure command-assembly input is NOT native authentication/execution.
        return self.b.assemble_recipe(self.source, dest, {},
                                     [self.b.PIN, self.b.TREE], 'b29c606',
                                     target=target, workspace=self.workspace)

    def test_dry_recipe_has_no_output_effects(self):
        dest = self.root / 'not-created'
        r = self.assembled(dest)
        self.assertFalse(dest.exists())
        self.assertEqual(r['base_revision'], self.b.PIN)
        expected = {
            'ggml/src/' + name for name in (
                'ggml.c', 'ggml.cpp', 'ggml-alloc.c', 'ggml-backend.cpp',
                'ggml-backend-meta.cpp', 'ggml-opt.cpp', 'ggml-threading.cpp',
                'ggml-quants.c', 'gguf.cpp', 'ggml-backend-dl.cpp', 'ggml-backend-reg.cpp',
                'ggml-cpu/ggml-cpu.c', 'ggml-cpu/ggml-cpu.cpp', 'ggml-cpu/repack.cpp',
                'ggml-cpu/iqp.cpp', 'ggml-cpu/hbm.cpp', 'ggml-cpu/quants.c',
                'ggml-cpu/traits.cpp', 'ggml-cpu/amx/amx.cpp', 'ggml-cpu/amx/mmq.cpp',
                'ggml-cpu/binary-ops.cpp', 'ggml-cpu/unary-ops.cpp', 'ggml-cpu/vec.cpp',
                'ggml-cpu/ops.cpp', 'ggml-cpu/arch/x86/quants.c',
                'ggml-cpu/arch/x86/repack.cpp', 'ggml-rpc/ggml-rpc.cpp', 'ggml-rpc/transport.cpp')
        } | {'tools/rpc/rpc-server.cpp'}
        self.assertEqual(set(r['sources']), expected)
        self.assertEqual(len(r['sources']), len(expected))
        compiled = {Path(c[c.index('-c') + 1]) for c in r['commands'] if '-c' in c}
        self.assertEqual(compiled, {self.source / s for s in expected} | {self.b.FIXTURE})
        self.assertEqual(r['flags'], ['-O0', '-g0', '-pthread', '-D_GNU_SOURCE',
                                      '-D_XOPEN_SOURCE=600', '-DGGML_SCHED_MAX_COPIES=4',
                                      '-DGGML_USE_CPU', '-DGGML_USE_RPC'])
        include_flags = ['-I' + str(p) for p in (self.source / 'ggml/include',
                         self.source / 'ggml/src', self.source / 'ggml/src/ggml-cpu', dest)]
        for index, command in enumerate(r['commands'][:-2]):
            self.assertEqual([v for v in command if v.startswith('-I')], include_flags)
            self.assertIn('-MD', command)
            self.assertEqual(Path(command[command.index('-MF') + 1]),
                             dest / (f'{index:02d}.d' if index < 29 else 'fixture.d'))
        objects = [str(dest / f'{index:02d}.o') for index in range(29)]
        self.assertEqual(r['commands'][-2], ['/usr/bin/c++', *objects, '-pthread',
                                            '-ldl', '-lm', '-o', str(dest / 'ggml-rpc-server')])
        self.assertEqual(r['commands'][-1], ['/usr/bin/c++', *objects[:-1], str(dest / 'fixture.o'),
                             '-pthread', '-ldl', '-lm', '-o', str(dest / 'native-buffer-graph')])
        self.assertEqual(r['template_options']['GGML_VERSION'], '0.24.0')
        for command in r['commands']:
            self.assertTrue(Path(command[-1]).is_relative_to(dest))

    def test_fixture_uses_stock_api_and_preallocation_bound(self):
        self.assertTrue(self.b.FIXTURE.is_file(), 'stock native fixture is missing')
        text = self.b.FIXTURE.read_text()
        self.assertIn('ggml_backend_alloc_ctx_tensors_from_buft_size', text)
        self.assertIn('ggml_backend_rpc_init', text)
        self.assertIn('ggml_backend_graph_compute', text)
        self.assertLess(text.index('needed <= buffer_cap'), text.index('ggml_backend_alloc_ctx_tensors(ctx'))

    def test_unknown_target(self):
        with self.assertRaisesRegex(self.b.BuildError, 'target'):
            self.assembled(self.root, target='llama-server')

    def test_wrong_pin(self):
        with self.assertRaisesRegex(self.b.BuildError, 'identity'):
            self.b.validate_identity([self.b.PIN, self.b.TREE], pin='0' * 40)

    def test_changed_source(self):
        altered = self.workspace_root / 'changed.cpp'
        original = b'// tiny genuine blob verification control\n'
        altered.write_bytes(original)
        blob = hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()
        self.assertEqual(self.b.verify_blob(altered, blob)['sha256'], hashlib.sha256(original).hexdigest())
        altered.write_text('not the original bytes')
        with self.assertRaisesRegex(self.b.BuildError, 'changed'):
            self.b.verify_blob(altered, blob)

    def test_outputs_cannot_escape_scratch(self):
        with self.assertRaisesRegex(self.b.BuildError, 'scratch'):
            self.assembled(self.workspace_root.parent / 'escape')

    def test_malformed_or_expanded_bounds(self):
        for kwargs in ({'as_bytes': 0}, {'phase_seconds': 1801}, {'rss_bytes': 5 << 30},
                       {'fixture_seconds': float('nan')}, {'jobs': 2}, {'disk_floor': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.b.Limits(**kwargs)

    def test_concurrent_supervisor_rejected(self):
        with self.supervisor() as first:
            with self.assertRaisesRegex(self.b.BuildError, 'locked'):
                with self.supervisor(self.workspace_root / 'second'):
                    pass
            self.assertEqual(first.run([sys.executable, '-c', 'print("owned")'])['exit_code'], 0)

    def test_timeout_reaps_owned_descendant(self):
        pidfile = self.root / 'child.pid'
        code = ('import subprocess,time,pathlib; '
                'p=subprocess.Popen(["/usr/bin/sleep","20"]); '
                f'pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(20)')
        with self.supervisor() as s:
            with self.assertRaisesRegex(self.b.BuildError, 'wall'):
                s.run([sys.executable, '-c', code], seconds=.2)
        pid = int(pidfile.read_text())
        self.assertFalse(Path(f'/proc/{pid}').exists())
        rows = json.loads((self.root / 'execution.json').read_text())
        self.assertEqual(rows[-1]['reason'], 'wall')

    def test_stderr_and_nonzero_preserved(self):
        with self.supervisor() as s:
            with self.assertRaisesRegex(self.b.BuildError, 'exit 7'):
                s.run([sys.executable, '-c', 'import sys; print("failure",file=sys.stderr); sys.exit(7)'])
        self.assertIn('failure', (self.root / 'step-000.stderr').read_text())

    def test_exec_resource_limits(self):
        with self.supervisor() as s:
            s.run([sys.executable, '-c', 'import resource; print(resource.getrlimit(resource.RLIMIT_AS)); print(resource.getrlimit(resource.RLIMIT_CORE)); print(resource.getrlimit(resource.RLIMIT_FSIZE))'])
        output = (self.root / 'step-000.stdout').read_text()
        self.assertIn(str(3 << 30), output)
        self.assertIn(str(256 << 20), output)
        self.assertIn('(0, 0)', output)

    def test_disk_floor_refusal(self):
        with self.supervisor() as s:
            with self.assertRaisesRegex(self.b.BuildError, 'disk'):
                s.check_storage(free_bytes=1)

    def test_artifact_cap_refusal(self):
        with self.supervisor() as s:
            with self.assertRaisesRegex(self.b.BuildError, 'artifact'):
                s.check_storage(artifact_bytes=(4 << 30) + 1)

    def test_rss_limit_stops_real_child(self):
        with self.supervisor(limits=self.b.Limits(rss_bytes=1 << 20)) as s:
            with self.assertRaisesRegex(self.b.BuildError, 'RSS'):
                s.run([sys.executable, '-c', 'import time; a=bytearray(8<<20); time.sleep(2)'])

    def test_workspace_immutable_and_isolated(self):
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            self.workspace.root = self.workspace_root.parent
        with self.supervisor() as first:
            other = self.b.Workspace(self.workspace_root / 'other')
            with self.b.Supervisor(other.root / 'run', workspace=other) as second:
                second.run([sys.executable, '-c', 'print("independent")'])
            first.run([sys.executable, '-c', 'print("first")'])
        self.assertNotEqual(self.workspace.ledger, other.ledger)
        self.assertEqual(len(json.loads(self.workspace.ledger.read_text())['phases']), 1)

    def test_execute_refuses_test_workspace_before_authentication(self):
        with mock.patch.object(self.b, 'authenticate', side_effect=AssertionError('must not authenticate')):
            with self.assertRaisesRegex(self.b.BuildError, 'unauthorized native workspace'):
                self.b.execute(self.source, self.root, workspace=self.workspace)
        self.assertFalse(self.root.exists())

    def test_real_authentication_required_before_compile(self):
        # Test scope cannot confer native authority; use default campaign only
        # to reject source BEFORE entering/locking/charging it. No compile.
        with mock.patch.object(self.b, 'authenticate', side_effect=self.b.BuildError('native base identity mismatch')) as auth:
            with mock.patch.object(self.b, 'Supervisor', side_effect=AssertionError('must not enter')):
                with self.assertRaisesRegex(self.b.BuildError, 'native base identity mismatch'):
                    self.b.execute(self.source)
        auth.assert_called_once()

    def test_identity_tree_mismatch(self):
        with self.assertRaisesRegex(self.b.BuildError, 'identity'):
            self.b.validate_identity([self.b.PIN, '0' * 40])

    def dependency(self, text):
        dep = self.workspace_root / 'input.d'
        dep.write_text(text)
        return self.b.compiled_inputs([dep], self.workspace_root)

    @staticmethod
    def make_escape(path):
        return str(path).replace('\\', '\\\\').replace(' ', '\\ ').replace('#', '\\#').replace(':', '\\:')

    def test_dependency_spaces_continuations_exact_hashes(self):
        directory = self.workspace_root / 'output with spaces'
        directory.mkdir()
        paths = [directory / 'source with spaces.cpp', directory / 'header with spaces.h',
                 directory / 'header#colon:back\\slash.h']
        for index, path in enumerate(paths):
            path.write_text(str(index))
        deptext = self.make_escape(directory / 'object with spaces.o') + ': ' + self.make_escape(paths[0])
        deptext += ' \\\n  ' + ' '.join(self.make_escape(p) for p in paths[1:]) + '\n'
        actual = self.dependency(deptext)
        self.assertEqual(actual, {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_execute_dependency_integration_without_native_launch(self):
        # Exercise actual execute() dependency/provenance wiring only. All
        # compile/server calls are inert boundary stubs, NOT native proof.
        from contextlib import contextmanager
        self.source.mkdir()
        template = self.source / 'ggml/src/ggml-version.h.in'
        template.parent.mkdir(parents=True)
        template.write_text('@GGML_VERSION@ @GGML_BUILD_COMMIT@')
        header = self.source / 'tiny header.h'
        header.write_text('real tiny header bytes')
        output = self.root
        depfile = output / 'fixture.d'
        recipe = {'commands': [['not-executed-compiler', '-MF', str(depfile)]],
                  'inputs': {}, 'template_options': {'GGML_VERSION': '0.24.0',
                                                    'GGML_BUILD_COMMIT': 'b29c606'}}
        class InertNativeBoundary:
            limits = self.b.Limits()
            def __enter__(boundary):
                output.mkdir()
                return boundary
            def __exit__(boundary, *args):
                pass
            def run(boundary, command, seconds=None):
                if '-MF' in command:
                    depfile.write_text('fixture.o: ' + self.make_escape(header) + '\n')
            @contextmanager
            def server(boundary, command):
                yield object()
        with mock.patch.object(self.b, 'output_root', return_value=output), \
             mock.patch.object(self.b, 'recipe', return_value=recipe), \
             mock.patch.object(self.b, 'authenticate', return_value={}), \
             mock.patch.object(self.b, 'Supervisor', return_value=InertNativeBoundary()), \
             mock.patch.object(self.b, 'wait_listener'):
            self.b.execute(self.source, output)
        provenance = json.loads((output / 'provenance.json').read_text())
        self.assertEqual(provenance['compiled_inputs'],
                         {str(header): hashlib.sha256(header.read_bytes()).hexdigest()})

    def test_dependency_relative_duplicate_paths(self):
        path = self.workspace_root / 'small.h'
        path.write_text('header')
        self.assertEqual(self.dependency('obj.o: small.h ./small.h\n'),
                         {str(path): hashlib.sha256(path.read_bytes()).hexdigest()})

    def test_dependency_missing_file_refused(self):
        with self.assertRaisesRegex(self.b.BuildError, 'missing dependency'):
            self.dependency('obj.o: missing.h\n')

    def test_dependency_missing_depfile_refused(self):
        with self.assertRaisesRegex(self.b.BuildError, 'missing depfile'):
            self.b.compiled_inputs([self.workspace_root / 'missing.d'], self.workspace_root)

    def test_dependency_unsupported_syntax_refused(self):
        path = self.workspace_root / 'small.h'
        path.write_text('header')
        for text in ('no separator', 'obj.o: small.h\nother.o: small.h\n',
                     'obj.o: $(HEADERS)\n', 'obj.o: small.h # comment\n',
                     'obj.o:: small.h\n', 'obj.o: small.h\\', 'obj.o: small.h | other.h\n',
                     'obj.o: small.h\\q\n', 'obj.o: small.h\x00\n'):
            with self.subTest(text=text), self.assertRaisesRegex(self.b.BuildError, 'unsupported depfile'):
                self.dependency(text)

    def test_active_server_deadline_refuses_before_client_success(self):
        done = self.root / 'client-completed'
        with self.supervisor(limits=self.b.Limits(fixture_seconds=.1)) as s:
            with self.assertRaisesRegex(self.b.BuildError, 'server fixture wall deadline exceeded'):
                with s.server([sys.executable, '-c', 'import time; time.sleep(20)']):
                    s.run([sys.executable, '-c', 'import time,pathlib; time.sleep(.35); '
                           + f'pathlib.Path({str(done)!r}).write_text("completed")'], seconds=.5)
            self.assertFalse(done.exists(), 'client output accepted beyond server deadline')
            self.assertFalse(s.active)
        rows = json.loads((self.root / 'execution.json').read_text())
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['reason'], 'server fixture wall deadline exceeded')
            self.assertFalse(Path(f'/proc/{row["pid"]}').exists())

    def test_server_readiness_obeys_reduced_deadline(self):
        with self.supervisor(limits=self.b.Limits(fixture_seconds=.1)) as s:
            with self.assertRaisesRegex(self.b.BuildError, 'server fixture wall deadline exceeded'):
                with s.server([sys.executable, '-c', 'import time; time.sleep(20)']) as child:
                    self.b.wait_listener(s, child, 1)
        self.assertFalse(Path(f'/proc/{child.pid}').exists())

    def test_subreaper_restored_on_exit(self):
        libc = ctypes.CDLL(None, use_errno=True)
        value = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(value), 0, 0, 0), 0)
        before = value.value
        libc.prctl(36, 0, 0, 0, 0)
        try:
            with self.supervisor() as s:
                s.run([sys.executable, '-c', 'pass'])
            self.assertEqual(libc.prctl(37, ctypes.byref(value), 0, 0, 0), 0)
            self.assertEqual(value.value, 0)
        finally:
            libc.prctl(36, before, 0, 0, 0)

    def test_subreaper_restored_on_entry_refusal(self):
        libc = ctypes.CDLL(None, use_errno=True)
        value = ctypes.c_int()
        libc.prctl(37, ctypes.byref(value), 0, 0, 0)
        before = value.value
        libc.prctl(36, 0, 0, 0, 0)
        (self.workspace_root / 'tiny-input').write_text('storage refusal')
        try:
            with self.assertRaisesRegex(self.b.BuildError, 'artifact budget violated'):
                with self.supervisor(limits=self.b.Limits(artifact_bytes=1)):
                    self.fail('entry should refuse')
            libc.prctl(37, ctypes.byref(value), 0, 0, 0)
            self.assertEqual(value.value, 0)
        finally:
            libc.prctl(36, before, 0, 0, 0)

    def test_existing_log_symlink_does_not_clobber_evidence(self):
        sentinel = self.workspace_root / 'sibling-evidence'
        sentinel.write_text('preserved')
        with self.supervisor() as s:
            (self.root / 'step-000.stdout').symlink_to(sentinel)
            with self.assertRaisesRegex(self.b.BuildError, 'existing output'):
                s.run([sys.executable, '-c', 'print("replacement")'])
        self.assertEqual(sentinel.read_text(), 'preserved')

    def test_metadata_symlink_refused(self):
        sentinel = self.workspace_root / 'sibling-evidence'
        sentinel.write_text('preserved')
        link = self.workspace_root / 'metadata.json'
        link.symlink_to(sentinel)
        with self.assertRaisesRegex(self.b.BuildError, 'unsafe metadata'):
            self.b.dump(link, {'new': 'bytes'})
        self.assertEqual(sentinel.read_text(), 'preserved')

    def test_existing_run_directory_preserves_failed_evidence(self):
        self.root.mkdir()
        sentinel = self.root / 'execution.json'
        sentinel.write_text('prior failed evidence')
        with self.assertRaisesRegex(self.b.BuildError, 'existing output'):
            with self.supervisor():
                self.fail('must refuse reused run')
        self.assertEqual(sentinel.read_text(), 'prior failed evidence')

    def test_storage_admission_refusal_is_charged(self):
        # Existing workspace file ensures otherwise-valid reduced storage fails.
        (self.workspace_root / 'tiny-input').write_text('actual existing bytes')
        with self.assertRaisesRegex(self.b.BuildError, 'artifact budget violated'):
            with self.supervisor(limits=self.b.Limits(artifact_bytes=1)):
                self.fail('entry should refuse')
        ledger = json.loads(self.workspace.ledger.read_text())
        self.assertGreater(ledger['elapsed_seconds'], 0)
        self.assertEqual(ledger['phases'][-1]['reason'], 'artifact budget violated')
        self.assertEqual(ledger['phases'][-1]['status'], 'admission refused')
        with self.supervisor(self.workspace_root / 'next') as s:
            s.run([sys.executable, '-c', 'pass'])

    def test_malformed_ledger_preserved_with_refusal_receipt(self):
        self.workspace.ledger.write_text('not-json')
        with self.assertRaisesRegex(self.b.BuildError, 'malformed build ledger'):
            with self.supervisor():
                self.fail('entry should refuse')
        self.assertEqual(self.workspace.ledger.read_text(), 'not-json')
        receipts = list(self.workspace_root.glob('admission-refusal-*.json'))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text())
        self.assertIn('malformed build ledger', receipt['reason'])
        self.assertGreater(receipt['elapsed_seconds'], 0)
        with self.workspace.lock.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_exhausted_ledger_is_uncharged_no_output(self):
        data = {'elapsed_seconds': 5400, 'phases': []}
        self.workspace.ledger.write_text(json.dumps(data))
        before = self.workspace.ledger.read_bytes()
        with self.assertRaisesRegex(self.b.BuildError, 'cumulative wall budget exhausted'):
            with self.supervisor():
                self.fail('entry should refuse')
        self.assertEqual(self.workspace.ledger.read_bytes(), before)
        self.assertFalse(self.root.exists())
        self.assertFalse(list(self.workspace_root.glob('admission-refusal-*.json')))

    def fake_pin(self, root):
        """Create a tiny real Git pin and return (source, revision, tree)."""
        import subprocess
        source = root / 'pin'
        source.mkdir()
        (source / 'common').mkdir()
        (source / 'common/common.cpp').write_bytes(b'int pinned_source;\n')
        (source / 'common/common.h').write_bytes(b'#define PINNED 1\n')
        subprocess.run(['git', '-C', str(source), 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(source), 'config', 'user.name', 'Test'], check=True)
        subprocess.run(['git', '-C', str(source), 'add', 'common'], check=True)
        subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'pin'], check=True)
        revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
        return source, revision, tree

    def fake_overlay(self, source, revision, tree):
        import inferswarm.operator.native_observer.overlay as overlay
        previous = {name: getattr(overlay, name) for name in
                    ('PIN', 'TREE', 'TRANSFORMED', 'NEW_FILES', 'FIXTURES', 'OVERLAY_DIR')}
        self.addCleanup(lambda: [setattr(overlay, name, value) for name, value in previous.items()])
        overlay.PIN, overlay.TREE = revision, tree
        overlay.TRANSFORMED = ()
        overlay.NEW_FILES = ()
        overlay.FIXTURES = source.parent / 'fixtures'
        overlay.OVERLAY_DIR = overlay.FIXTURES / 'overlay'
        overlay.OVERLAY_DIR.mkdir(parents=True)
        (overlay.FIXTURES / 'native-observer-transformed.json').write_text(
            json.dumps({'base_revision': revision, 'base_tree': tree, 'files': [],
                        'patch_sha256': 'a' * 64, 'schema': 'native-observer-transformed/1'},
                       indent=2, sort_keys=True) + '\n')
        return overlay

    def test_dirty_untransformed_tu_is_refused(self):
        from inferswarm.operator.native_observer import overlay
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-red-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
                ov.verify_tree_inputs(derived, source)
                (derived / 'common/common.cpp').write_text('foreign compiled source\\n')
                with self.assertRaisesRegex(ov.OverlayError, 'common/common.cpp'):
                    ov.verify_tree_inputs(derived, source)

    def test_reused_overlay_tree_full_authentication(self):
        from inferswarm.operator.native_observer import full_build
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-red-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
            (derived / 'common/common.cpp').write_text('foreign compiled source\\n')
            with mock.patch.object(full_build, 'assemble', side_effect=AssertionError('command assembly must not run')) as assemble:
                with self.assertRaisesRegex(full_build.BuildError, 'common/common.cpp'):
                    full_build.verify_tree_inputs(derived, source)
                assemble.assert_not_called()

    def test_overlay_apply_materializes_from_git_not_worktree(self):
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-red-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            (source / 'common/common.cpp').write_text('dirty working tree bytes\\n')
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
            self.assertEqual((derived / 'common/common.cpp').read_bytes(), b'int pinned_source;\n')
            self.assertFalse((derived / '.git').exists())

    def test_provenance_fields_are_separate(self):
        from inferswarm.operator.native_observer import full_build
        body = full_build._provenance_body(
            revision='r', tree='t', retained_patch_sha256='p',
            transformed_manifest_sha256='m', transformed_sources=[{'path': 'x', 'sha256': 'a'}],
            untransformed_inputs={'y': 'b'}, generated_inputs={'build-info.cpp': 'c'},
            compiler_identity='compiler', link_inputs={'server': ['d']},
            executable_sha256={'server': 'e'}, overlay_root='tree')
        fields = ('pinned_base', 'retained_patch_sha256', 'transformed_manifest_sha256',
                  'transformed_sources', 'untransformed_input_count',
                  'untransformed_inputs_sha256', 'generated_inputs', 'compiler_identity',
                  'link_inputs', 'executable_sha256')
        for field in fields:
            self.assertIn(field, body)
        identities = [body['pinned_base']['revision'], body['retained_patch_sha256'],
                      body['transformed_manifest_sha256'], body['transformed_sources'][0]['sha256'],
                      body['generated_inputs'][0]['sha256'],
                      body['executable_sha256']['server']]
        self.assertEqual(len(set(identities)), len(identities))


    def test_added_executable_bit_is_refused(self):
        # QUALITY finding Q4: a pinned 100644 file flipped to 0755 must be
        # refused (mode is part of the authenticated input identity).
        from inferswarm.operator.native_observer import overlay
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-mode-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
                (derived / 'common/common.cpp').chmod(0o755)
                with self.assertRaisesRegex(ov.OverlayError, 'common/common.cpp'):
                    ov.verify_tree_inputs(derived, source)

    def test_regular_to_symlink_substitution_is_refused(self):
        # QUALITY finding Q4: replacing a pinned regular file with a symlink
        # (even one resolving to the pinned bytes) must be refused — symlinks
        # can be retargeted after verification and before the compiler reads.
        from inferswarm.operator.native_observer import overlay
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-sym-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
                pinned_bytes = (source / 'common/common.cpp').read_bytes()
                outside = root / 'outside.cpp'
                outside.write_bytes(pinned_bytes)
                (derived / 'common/common.cpp').unlink()
                (derived / 'common/common.cpp').symlink_to(outside)
                with self.assertRaisesRegex(ov.OverlayError, 'common/common.cpp'):
                    ov.verify_tree_inputs(derived, source)

    def test_dangling_or_foreign_entry_is_refused(self):
        # QUALITY finding Q4 (enumeration): an unaccounted filesystem entry
        # (here a dangling symlink) must be refused by the complete
        # expected/actual set comparison.
        from inferswarm.operator.native_observer import overlay
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-dangling-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
                (derived / 'common/dangling').symlink_to(root / 'does-not-exist')
                with self.assertRaisesRegex(ov.OverlayError, 'dangling'):
                    ov.verify_tree_inputs(derived, source)

    def test_compile_inputs_come_only_from_materialized_tree(self):
        from inferswarm.operator.native_observer import full_build as fb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            tree, out = root / 'tree', root / 'out'
            recipe = fb.assemble(Path('/nonexistent-tree'), out)
            forbidden = 'tests/fixtures/issue299/overlay'
            self.assertFalse(any(forbidden in part for cmd in recipe['commands'] for part in cmd))
            for cmd in recipe['commands']:
                if '-c' in cmd:
                    src = Path(cmd[cmd.index('-c') + 1]).resolve()
                    self.assertTrue(src.is_relative_to(Path('/nonexistent-tree').resolve()) or src.is_relative_to(out))
                for arg in cmd:
                    if arg.startswith('-I'):
                        inc = Path(arg[2:]).resolve()
                        self.assertTrue(inc.is_relative_to(Path('/nonexistent-tree').resolve()) or inc.is_relative_to(out))

    def test_worktree_only_dirty_sink_cannot_reach_compilation(self):
        # Review A: a dirty repo-worktree overlay file must be neither a
        # compile input (assemble uses only tree/out paths) nor able to pass
        # verification (materialized bytes are checked against the retained
        # manifest digests).
        from inferswarm.operator.native_observer import full_build as fb
        from inferswarm.operator.native_observer import overlay
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-sink-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            pinned_bytes = b'pinned sink bytes\n'
            (ov.OVERLAY_DIR / 'is301_sink.cpp').write_bytes(pinned_bytes)
            ov.NEW_FILES = ('is301_sink.cpp',)
            manifest = json.loads((ov.FIXTURES / 'native-observer-transformed.json').read_text())
            manifest['files'] = [{'path': 'is301_sink.cpp',
                                  'sha256': hashlib.sha256(pinned_bytes).hexdigest()}]
            (ov.FIXTURES / 'native-observer-transformed.json').write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + '\n')
            derived = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, derived)
                self.assertEqual((derived / 'is301_sink.cpp').read_bytes(), pinned_bytes)
                # Dirty the WORKTREE copy only, after materialization: the
                # materialized tree stays authenticated (verification passes)
                # and — decisively — the dirty bytes cannot reach compilation
                # because assemble() consumes only tree/out paths.
                (ov.OVERLAY_DIR / 'is301_sink.cpp').write_bytes(b'foreign worktree bytes\n')
                ov.verify_tree_inputs(derived, source)
                # Dirty TREE copies are still refused (authentication holds).
                (derived / 'is301_sink.cpp').write_bytes(b'foreign tree bytes\n')
                with self.assertRaisesRegex(ov.OverlayError, 'is301_sink.cpp'):
                    ov.verify_tree_inputs(derived, source)
            recipe = fb.assemble(derived, root / 'out')
            self.assertFalse(any(str(ov.OVERLAY_DIR) in part
                                 for cmd in recipe['commands'] for part in cmd))
            # The sink TU must compile from the authenticated TREE copy, not
            # from any repository overlay path (old code compiled
            # REPO/tests/fixtures/issue299/overlay/is301_sink.cpp).
            sink_cmd = next(cmd for cmd in recipe['commands']
                            if 'is301_sink.cpp' in ' '.join(cmd))
            self.assertEqual(str(derived / 'is301_sink.cpp'),
                             sink_cmd[sink_cmd.index('-c') + 1])

    def test_symlink_to_existing_directory_is_refused(self):
        from inferswarm.operator.native_observer import overlay
        scratch = Path('/home/zutfen/.hermes/cache/scratch')
        with tempfile.TemporaryDirectory(prefix='p1c-foreigndir-', dir=scratch) as tmp:
            root = Path(tmp)
            source, revision, tree = self.fake_pin(root)
            ov = self.fake_overlay(source, revision, tree)
            destination = root / 'derived'
            with mock.patch.object(ov, 'PIN', revision), mock.patch.object(ov, 'TREE', tree):
                ov.apply(source, destination)
                target = root / 'somedir'
                target.mkdir()
                (destination / 'common/foreigndir').symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(ov.OverlayError, 'foreigndir'):
                    ov.verify_tree_inputs(destination, source)

    def test_foreign_empty_directory_is_refused(self):
        source, revision, tree = self.fake_pin(self.workspace_root)
        ov = self.fake_overlay(source, revision, tree)
        derived = self.workspace_root / 'derived'
        with mock.patch.object(ov, 'Path', wraps=Path):
            # Materialize the tiny authenticated fixture without scratch policy.
            import shutil
            shutil.copytree(source / 'common', derived / 'common')
            shutil.copyfile(ov.FIXTURES / 'native-observer-transformed.json',
                            derived / 'native-observer-transformed.json')
            ov.verify_tree_inputs(derived, source)
            (derived / 'foreign-empty').mkdir()
            with self.assertRaisesRegex(ov.OverlayError, 'foreign-empty'):
                ov.verify_tree_inputs(derived, source)

    def test_symlink_overlay_root_is_refused_without_following(self):
        source, revision, tree = self.fake_pin(self.workspace_root)
        ov = self.fake_overlay(source, revision, tree)
        import shutil
        derived = self.workspace_root / 'derived'
        shutil.copytree(source / 'common', derived / 'common')
        shutil.copyfile(ov.FIXTURES / 'native-observer-transformed.json',
                        derived / 'native-observer-transformed.json')
        link = self.workspace_root / 'linked-root'
        for target in (derived, self.workspace_root / 'missing'):
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ov.OverlayError, 'root'):
                ov.verify_tree_inputs(link, source)
            link.unlink()

    def test_link_membership_keeps_actual_non_numeric_object_paths(self):
        from inferswarm.operator.native_observer import full_build as fb
        command = ['/usr/bin/c++', str(self.root / 'library-member.o'),
                   str(self.root / 'server-main.o'), '-pthread', '-o',
                   str(self.root / 'llama-server')]
        self.assertEqual(fb._link_membership({'commands': [command]}),
                         {'llama-server': command[1:3]})

    def test_archive_membership_separates_main_translation_units(self):
        from inferswarm.operator.native_observer import full_build as fb
        recipe = fb.assemble(self.source, self.root)
        archives = fb._archive_membership(recipe)
        compiled = {c[c.index('-o') + 1]: c[c.index('-c') + 1]
                    for c in recipe['commands'] if '-c' in c}
        self.assertEqual(set(archives), {'libggml-static.a', 'libllama-full.a'})
        for members in archives.values():
            self.assertTrue(members)
            self.assertFalse(any(Path(compiled[p]).name in
                ('main.cpp', 'rpc-server.cpp', 'native-buffer-graph-observed.cpp',
                 'native-fact-bounds.cpp', 'native-export-claim.cpp') for p in members))
        self.assertIn(str(self.source / 'is301_sink.cpp'),
                      [compiled[p] for p in archives['libggml-static.a']])

    def test_full_recipe_emits_system_inclusive_depfiles(self):
        from inferswarm.operator.native_observer import full_build as fb
        recipe = fb.assemble(self.source, self.root)
        for command in recipe['commands']:
            if '-c' in command:
                self.assertIn('-MD', command)
                self.assertEqual(command[command.index('-MF') + 1],
                                 str(Path(command[command.index('-o') + 1]).with_suffix('.d')))

    def test_full_dependency_verification_uses_precompile_freeze(self):
        from inferswarm.operator.native_observer import full_build as fb
        roots = {kind: self.workspace_root / kind for kind in ('tree', 'generated', 'system')}
        inventories = {}
        for kind, root in roots.items():
            root.mkdir()
            header = root / (kind + '.h')
            header.write_text(kind)
            inventories[kind] = {str(header): hashlib.sha256(header.read_bytes()).hexdigest()}
        paths = [next(iter(items)) for items in inventories.values()]
        dep = self.workspace_root / 'actual.d'
        dep.write_text('object.o: ' + ' '.join(self.make_escape(p) for p in paths) + '\n')
        actual = fb._verify_compiled_inputs([dep], self.workspace_root, inventories)
        self.assertEqual(actual, inventories)
        Path(paths[2]).write_text('changed since freeze')
        with self.assertRaisesRegex(self.b.BuildError, 'changed dependency'):
            fb._verify_compiled_inputs([dep], self.workspace_root, inventories)
        Path(paths[2]).unlink()
        with self.assertRaisesRegex(self.b.BuildError, 'missing dependency'):
            fb._verify_compiled_inputs([dep], self.workspace_root, inventories)
        foreign = self.workspace_root / 'foreign.h'
        foreign.write_text('not frozen')
        dep.write_text('object.o: ' + self.make_escape(foreign) + '\n')
        with self.assertRaisesRegex(self.b.BuildError, 'unknown dependency'):
            fb._verify_compiled_inputs([dep], self.workspace_root, inventories)
        with self.assertRaisesRegex(self.b.BuildError, 'missing depfile'):
            fb._verify_compiled_inputs([self.workspace_root / 'missing.d'], self.workspace_root, inventories)

    def test_full_recipe_refuses_foreign_include_search(self):
        from inferswarm.operator.native_observer import full_build as fb
        recipe = fb.assemble(self.source, self.root)
        fb._verify_include_paths(recipe, self.source, self.root)
        recipe['commands'][0].insert(1, '-I/foreign/mutable-include')
        with self.assertRaisesRegex(self.b.BuildError, 'foreign include'):
            fb._verify_include_paths(recipe, self.source, self.root)

    def test_system_headers_are_frozen_before_depfile_verification(self):
        from inferswarm.operator.native_observer import full_build as fb
        system = self.workspace_root / 'compiler-include'
        system.mkdir()
        header = system / 'system.h'
        header.write_text('frozen compiler header')
        listing = self.workspace_root / 'compiler.stderr'
        listing.write_text('#include <...> search starts here:\n ' + str(system) + '\nEnd of search list.\n')
        boundary = mock.Mock(root=self.workspace_root)
        boundary.run.return_value = {'stderr': str(listing)}
        frozen = fb._freeze_system_inputs(boundary)
        self.assertEqual(frozen, {str(header): hashlib.sha256(header.read_bytes()).hexdigest()})
        self.assertEqual(boundary.run.call_count, 2)
        for call in boundary.run.call_args_list:
            self.assertIn('-v', call.args[0])
            self.assertIn('/dev/null', call.args[0])
        header.write_text('changed after freeze')
        dep = self.workspace_root / 'header.d'
        dep.write_text('object.o: ' + str(header) + '\n')
        with self.assertRaisesRegex(self.b.BuildError, 'changed dependency'):
            fb._verify_compiled_inputs([dep], self.workspace_root, {'system': frozen})
        listing.write_text('no compiler search roots')
        with self.assertRaisesRegex(self.b.BuildError, 'missing compiler include'):
            fb._freeze_system_inputs(boundary)

    def test_compiler_binary_identity_is_frozen_and_rechecked(self):
        from inferswarm.operator.native_observer import full_build as fb
        program = self.workspace_root / 'synthetic-compiler-program'
        program.write_text('test boundary, never executed')
        listing = self.workspace_root / 'compiler.stdout'
        listing.write_text(str(program) + '\n')
        boundary = mock.Mock()
        boundary.run.return_value = {'stdout': str(listing)}
        identities = fb._compiler_binary_identities(boundary)
        self.assertEqual(identities[str(program)]['sha256'], hashlib.sha256(program.read_bytes()).hexdigest())
        fb._verify_compiler_binaries(identities)
        program.write_text('changed after compiler freeze')
        with self.assertRaisesRegex(self.b.BuildError, 'changed compiler binary'):
            fb._verify_compiler_binaries(identities)

    def _synthetic_sealed_capture(self, path, **updates):
        # Resealed retained envelope used only for Python verifier controls;
        # these synthetic bytes are NOT proof of a native run.
        from inferswarm.operator.profiles import canonical
        fixture = Path(__file__).parent / 'fixtures/issue299/native-captures/fact-bounds/clean.json'
        record = json.loads(fixture.read_bytes())
        record.update(updates)
        record['terminal_digest'] = hashlib.sha256(canonical({k: v for k, v in record.items()
                                                             if k != 'terminal_digest'})).hexdigest()
        path.write_text(json.dumps(record))
        return record

    def test_parent_fact_verifier_requires_preserved_scalar_and_valid_seal(self):
        from inferswarm.operator.native_observer import full_build as fb
        append = self.workspace_root / 'fact-bounds-capture.json'
        scalar = self.workspace_root / 'fact-scalar-overwrite.json'
        clean = self.workspace_root / 'fact-bounds-clean.json'
        self._synthetic_sealed_capture(append, dropped_events=1)
        record = self._synthetic_sealed_capture(scalar, dropped_events=1, overflow=True,
                                                facts={'overwrite-bound': 'small'})
        self._synthetic_sealed_capture(clean)
        fb._verify_fact_captures(self.workspace_root)
        self._synthetic_sealed_capture(scalar, dropped_events=1, overflow=True,
                                       facts={'overwrite-bound': 'corrupted'})
        with self.assertRaisesRegex(self.b.BuildError, 'corrupted prior value'):
            fb._verify_fact_captures(self.workspace_root)
        scalar.write_text(json.dumps(record).replace('"small"', 'small'))
        with self.assertRaises(json.JSONDecodeError):
            fb._verify_fact_captures(self.workspace_root)
        record['terminal_digest'] = 'f' * 64
        scalar.write_text(json.dumps(record))
        with self.assertRaisesRegex(self.b.BuildError, 'invalid native capture seal'):
            fb._verify_fact_captures(self.workspace_root)

    def test_parent_claim_verifier_binds_owner_to_capture(self):
        from inferswarm.operator.native_observer import full_build as fb
        capture = self.workspace_root / 'claim-race-123-0000.json'
        self._synthetic_sealed_capture(capture, facts={'process': {'pid': 123, 'start_ticks': 456}})
        claim = self.workspace_root / 'is301-claim'
        claim.write_text('123\n456\nclaim-race\n')
        fb._verify_claim_proof(self.workspace_root)
        claim.write_text('123\n457\nclaim-race\n')
        with self.assertRaisesRegex(self.b.BuildError, 'owner identity mismatch'):
            fb._verify_claim_proof(self.workspace_root)
        claim.write_text('123\n456\nclaim-race\n')
        (self.workspace_root / 'foreign.tmp').write_text('unexpected')
        with self.assertRaisesRegex(self.b.BuildError, 'unexpected files'):
            fb._verify_claim_proof(self.workspace_root)

    def test_execute_prepares_export_dirs_before_fixture_launch(self):
        self._synthetic_execute_control()

    def test_fresh_execute_archive_bytes_and_full_link_inputs_are_stable(self):
        # Isolate F from the independently tested C directory-order defect.
        self._synthetic_execute_control(archive_only=True)

    def test_execute_refuses_depfile_drift_before_linking(self):
        for failure in ('missing depfile', 'changed dependency', 'unknown dependency'):
            with self.subTest(failure=failure):
                self._synthetic_execute_control(dep_failure=failure)

    def _synthetic_execute_control(self, *, archive_only=False, dep_failure=None):
        # Review C: every export directory must exist before the fixture or
        # daemon that writes into it is launched; no duplicate non-idempotent
        # mkdir may remain. Proven with a fake supervisor that asserts, at the
        # moment each env-carrying command runs, that its export dir exists.
        import tempfile
        from unittest import mock
        from inferswarm.operator.native_observer import full_build as fb
        from inferswarm.operator.native_observer.build import Workspace
        scratch = self.workspace_root
        with tempfile.TemporaryDirectory(prefix='p1c-order-', dir=scratch) as tmp:
            root = Path(tmp)
            workspace = Workspace(root / 'campaign')
            output = root / 'campaign' / 'run1'

            class FakeChild:
                pid = 4242

            class FakeSupervisor:
                limits = type('L', (), {'fixture_seconds': 60})()
                launched = []
                archives = {}
                archive_calls = []
                link_commands = []

                def __init__(self, out, workspace=None):
                    Path(out).mkdir(parents=True, exist_ok=True)

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def run(self, command, seconds=None, env_extra=None):
                    # Materialize the command's declared output so downstream
                    # provenance digesting sees real files (no compile happens).
                    if '-o' in command:
                        Path(command[command.index('-o') + 1]).parent.mkdir(
                            parents=True, exist_ok=True)
                        Path(command[command.index('-o') + 1]).write_bytes(('SYNTHETIC:' + ' '.join(command)).encode())
                    if '-c' not in command and '-o' in command:
                        self.link_commands.append(command)
                    if '-MF' in command and dep_failure != 'missing depfile':
                        dependency = output / 'ui.h'
                        if dep_failure == 'changed dependency':
                            dependency.write_text('mutated after precompile freeze')
                        elif dep_failure == 'unknown dependency':
                            dependency = root / 'unknown.h'
                            dependency.write_text('not in any frozen inventory')
                        Path(command[command.index('-MF') + 1]).write_text(
                            'obj.o: ' + str(dependency) + '\n')
                    if command[:2] == ['/usr/bin/ar', 'rc']:
                        archive = Path(command[2])
                        self.archives[str(archive)] = [Path(p).name for p in command[3:]]
                        self.archive_calls.append(str(archive))
                        archive.write_bytes(b'SYNTHETIC-ARCHIVE:' + b''.join(Path(p).read_bytes() for p in command[3:]))
                    if command[:2] == ['/usr/bin/ar', 't']:
                        listing = output / ('listing-' + Path(command[2]).name)
                        listing.write_text('\n'.join(self.archives[command[2]]) + '\n')
                        return {'stdout': str(listing)}
                    if env_extra and 'IS301_EXPORT_DIR' in env_extra:
                        export_dir = Path(env_extra['IS301_EXPORT_DIR'])
                        if archive_only:
                            export_dir.mkdir(parents=True, exist_ok=True)
                        if not export_dir.is_dir():
                            raise AssertionError(
                                'export dir missing at launch: ' + str(export_dir))
                        FakeSupervisor.launched.append(Path(command[0]).name)
                    return {'command': list(map(str, command))}

                class _ServerCtx:
                    def __init__(self, sup, cmd, env_extra):
                        self.sup, self.cmd, self.env_extra = sup, cmd, env_extra
                        self.child = FakeChild()

                    def __enter__(self):
                        export_dir = Path(self.env_extra['IS301_EXPORT_DIR'])
                        if archive_only:
                            export_dir.mkdir(parents=True, exist_ok=True)
                        if not export_dir.is_dir():
                            raise AssertionError(
                                'export dir missing at daemon start: ' + str(export_dir))
                        FakeSupervisor.launched.append(Path(self.cmd[0]).name)
                        return self.child

                    def __exit__(self, *exc):
                        return False

                def server(self, command, env_extra=None):
                    return FakeSupervisor._ServerCtx(self, command, env_extra)

            def fake_render(tree, out):
                for name in ('build-info.cpp', 'ggml-version.h',
                             'llama-version.h', 'ui.cpp', 'ui.h'):
                    (Path(out) / name).write_bytes(b'generated\n')

            from inferswarm.operator.native_observer import build as build_module
            original_mkdir = Path.mkdir
            def controlled_mkdir(path, mode=0o777, parents=False, exist_ok=False):
                if archive_only and path.is_relative_to(output / 'exports'):
                    exist_ok = True
                return original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)
            with mock.patch.object(Path, 'mkdir', controlled_mkdir), \
                 mock.patch.object(fb, 'CAMPAIGN', workspace), \
                 mock.patch.object(fb, 'Supervisor', FakeSupervisor), \
                 mock.patch.object(fb, '_render_templates', fake_render), \
                 mock.patch.object(fb, '_toolchain_identity', return_value='synthetic-toolchain'), \
                 mock.patch.object(fb, '_freeze_system_inputs', return_value={}, create=True), \
                 mock.patch.object(fb, '_compiler_binary_identities', return_value={}, create=True), \
                 mock.patch.object(fb, '_verify_claim_proof', create=True), \
                 mock.patch.object(fb, '_verify_fact_captures', create=True), \
                 mock.patch.object(fb, 'verify_tree_inputs', return_value={}), \
                 mock.patch.object(fb.subprocess, 'run', side_effect=
                     lambda command, **kwargs: FakeSupervisor.run(FakeSupervisor, command)), \
                 mock.patch.object(fb, 'overlay_module') as fake_overlay_module, \
                 mock.patch.object(build_module, 'wait_listener'):
                fake_overlay_module.PIN = 'fake-pin'
                fake_overlay_module.TREE = 'fake-tree'
                fake_overlay_module.TRANSFORMED = ()
                fake_overlay_module.NEW_FILES = ()
                def fake_apply(source, tree):
                    Path(tree).mkdir(parents=True)
                    (Path(tree) / 'native-observer-transformed.json').write_text(json.dumps({
                        'patch_sha256': 'a' * 64, 'files': []}))
                fake_overlay_module.apply.side_effect = fake_apply
                if dep_failure:
                    with self.assertRaisesRegex(fb.BuildError, dep_failure):
                        fb.execute(source=root / 'fake-source', output=output,
                                   overlay_root=root / 'fake-tree', workspace=workspace)
                    self.assertEqual(FakeSupervisor.launched, [])
                    self.assertEqual(FakeSupervisor.link_commands, [])
                    return
                fb.execute(source=root / 'fake-source', output=output, overlay_root=root / 'fake-tree', workspace=workspace)
            for name in ('fixture-cpu', 'rpc-server', 'fixture-rpc'):
                self.assertTrue((output / 'exports' / name).is_dir(), name)
            self.assertIn('native-buffer-graph-observed', FakeSupervisor.launched)
            provenance = json.loads((output / 'provenance.json').read_text())
            recipe = json.loads((output / 'recipe.json').read_text())
            # Synthetic boundary artifacts exercise wiring, NEVER native evidence.
            self.assertEqual(len(FakeSupervisor.archive_calls), len(set(FakeSupervisor.archive_calls)))
            for exe, row in provenance['link_inputs'].items():
                command = next(c for c in recipe['commands']
                               if '-c' not in c and Path(c[c.index('-o') + 1]).name == exe)
                self.assertEqual(row['command'], command)
                self.assertEqual(row['objects'], [a for a in command if a.endswith('.o')])
                self.assertEqual(row['object_sha256'], [hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                                        for p in row['objects']])
                manifest = json.loads((output / (exe + '.build-manifest.json')).read_text())
                for library in manifest['backend_libraries']:
                    self.assertEqual(library['sha256'], hashlib.sha256((output / library['name']).read_bytes()).hexdigest())
            compiles = {c[c.index('-o') + 1]: c[c.index('-c') + 1] for c in recipe['commands'] if '-c' in c}
            server_sources = [compiles[o] for o in provenance['link_inputs']['llama-server']['objects']]
            self.assertIn(str(root / 'fake-tree' / 'tools/server/main.cpp'), server_sources)
            for members in FakeSupervisor.archives.values():
                for member in members:
                    self.assertNotIn(Path(compiles[str(output / member)]).name,
                                     ('main.cpp', 'rpc-server.cpp', 'native-buffer-graph-observed.cpp',
                                      'native-fact-bounds.cpp', 'native-export-claim.cpp'))
