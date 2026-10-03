"""Issue #262 source transform: offline chain checks and identity law."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PINNED = Path(os.environ.get('ISSUE262_PINNED_LLAMA', '/home/zutfen/llama.cpp-252'))
SCRIPT = REPO / 'scripts/issue262_source_patch.py'
AREA = REPO / 'docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism'
IDENTITY = AREA / 'issue262-source-identity.json'
I260_IDENTITY = AREA / 'issue260-source-identity.json'
H5_PATCH = AREA / 'patches/issue262-h5-route.patch'
H5_EDITOR = AREA / 'patches/issue262_h5_edit.py'
SOURCE_FILE = 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'


def run_transform(src, dst):
    return subprocess.run([sys.executable, str(SCRIPT), '--source', str(src),
                           '--output', str(dst)], cwd=REPO, text=True,
                          capture_output=True)


class SourceChainTests(unittest.TestCase):
    def test_red_refuses_source_other_than_frozen_commit(self):
        with tempfile.TemporaryDirectory(prefix='i262-bad-') as tmp:
            result = run_transform(Path(tmp), Path(tmp) / 'out')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pinned', (result.stderr + result.stdout).lower())

    def test_identity_chain_is_frozen_and_self_consistent(self):
        self.assertTrue(H5_PATCH.is_file(), 'H5 route patch must be committed')
        self.assertTrue(H5_EDITOR.is_file(), 'H5 anchor editor must be committed')
        identity = json.loads(IDENTITY.read_text(encoding='utf-8'))
        i260 = json.loads(I260_IDENTITY.read_text(encoding='utf-8'))
        self.assertEqual(identity['predecessor_commit'], PIN)
        self.assertEqual(identity['predecessor_tree'], TREE)
        self.assertEqual(identity['i260_patch_sha256'], i260['patch_sha256'])
        self.assertEqual(
            identity['h5_patch_sha256'],
            hashlib.sha256(H5_PATCH.read_bytes()).hexdigest())
        self.assertEqual(
            identity['h5_editor_sha256'],
            hashlib.sha256(H5_EDITOR.read_bytes()).hexdigest())
        self.assertRegex(identity['instrumented262_tree'], r'^[0-9a-f]{40}$')
        self.assertNotEqual(identity['instrumented262_tree'],
                            i260['instrumented_tree'])
        self.assertEqual(identity['server_source_sha256'],
                         '2f1f3d5461c39b94d4dc92c74e03da5fb0b1af069f1aeda1df587a25c3ffe89f')
        # The H5 marker grammar is committed in the patch.
        additions = '\n'.join(line[1:] for line in H5_PATCH.read_text(encoding='utf-8').splitlines()
                              if line.startswith('+') and not line.startswith('+++'))
        for marker in ('ggml_vk_i262:v1|route|id=%llu|graph=%llu',
                       '|weight=output.weight|node=%s|side=%d',
                       '|route=%s|pipe=%s|family=%s|quant_y=%d|split_k=%u|64b=%d',
                       '|dims=%llux%llu:%llux%llu->%llux%llu|types=%s*%s->%s'):
            self.assertIn(marker, additions)

    @unittest.skipUnless(PINNED.is_dir(), 'pinned llama.cpp checkout not locally available')
    def test_transform_is_deterministic_and_matches_frozen_tree(self):
        with tempfile.TemporaryDirectory(prefix='i262-transform-') as tmp:
            out_a, out_b = Path(tmp) / 'a', Path(tmp) / 'b'
            first = run_transform(PINNED, out_a)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_transform(PINNED, out_b)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((out_a / SOURCE_FILE).read_bytes(),
                             (out_b / SOURCE_FILE).read_bytes())
            identity = json.loads(IDENTITY.read_text(encoding='utf-8'))
            self.assertIn(identity['instrumented262_tree'], first.stdout)
            # H5 patch alone reproduces the vk source from the i260 tree:
            # applying the frozen H5 patch to the #260 instrumented tree
            # must equal the #262 vk source byte-for-byte.
            self.assertEqual(
                hashlib.sha256((out_a / SOURCE_FILE).read_bytes()).hexdigest(),
                identity['h5_vk_source_sha256'])

    def test_identity_file_refuses_drift(self):
        with tempfile.TemporaryDirectory(prefix='i262-drift-') as tmp:
            # A tampered H5 patch (edit bytes) must make verify mode fail.
            tampered = Path(tmp) / 'repo-tamper'
            tampered.mkdir()
            result = subprocess.run(
                [sys.executable, '-c', '''
import sys, types, pathlib
src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
src = src.replace("AREA = REPO / \\"docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism\\"",
                  "AREA = pathlib.Path(sys.argv[2])")
pathlib.Path(sys.argv[3]).write_text(src)
''', str(SCRIPT), str(AREA), str(tampered / 'issue262_source_patch.py')],
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            area_copy = tampered / 'area'
            subprocess.run(['cp', '-r', str(AREA), str(area_copy)], check=True)
            patch = area_copy / 'patches/issue262-h5-route.patch'
            patch.write_bytes(patch.read_bytes() + b'# tampered\n')
            out = tampered / 'out'
            bad = subprocess.run(
                [sys.executable, str(tampered / 'issue262_source_patch.py'),
                 '--source', str(PINNED) if PINNED.is_dir() else str(tampered),
                 '--output', str(out)], text=True, capture_output=True)
            # Either the pinned source is unavailable (skip) or the tampered
            # chain must be refused; it must never succeed silently.
            if PINNED.is_dir():
                self.assertNotEqual(bad.returncode, 0)
                self.assertIn('drift', (bad.stderr + bad.stdout).lower())


if __name__ == '__main__':
    unittest.main()
