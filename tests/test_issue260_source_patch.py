"""Issue #260 source patch: offline grammar checks and optional pinned transform."""
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
PINNED = Path(os.environ.get('ISSUE260_PINNED_LLAMA', '/home/zutfen/llama.cpp-252'))
SCRIPT = REPO / 'scripts/issue260_source_patch.py'
AREA = REPO / 'docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism'
PATCH = AREA / 'patches/issue260-vulkan-instrumentation.patch'
IDENTITY = AREA / 'issue260-source-identity.json'
SOURCE_FILE = 'ggml/src/ggml-vulkan/ggml-vulkan.cpp'
PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'


def run_transform(src, dst):
    return subprocess.run([sys.executable, str(SCRIPT), '--source', str(src), '--output', str(dst)],
                          cwd=REPO, text=True, capture_output=True)


class SourcePatchTests(unittest.TestCase):
    def test_red_refuses_source_other_than_frozen_commit(self):
        with tempfile.TemporaryDirectory(prefix='i260-bad-') as tmp:
            result = run_transform(Path(tmp), Path(tmp) / 'out')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pinned', (result.stderr + result.stdout).lower())

    def test_patch_and_identity_are_frozen_without_pinned_checkout(self):
        self.assertTrue(PATCH.is_file(), 'source patch must be committed')
        identity = json.loads(IDENTITY.read_text(encoding='utf-8'))
        self.assertEqual(identity['predecessor_commit'], PIN)
        self.assertEqual(identity['predecessor_tree'], TREE)
        self.assertEqual(identity['patch_sha256'], hashlib.sha256(PATCH.read_bytes()).hexdigest())
        self.assertRegex(identity['instrumented_tree'], r'^[0-9a-f]{40}$')
        self.assertNotEqual(identity['instrumented_tree'], TREE)
        additions = '\n'.join(line[1:] for line in PATCH.read_text(encoding='utf-8').splitlines()
                              if line.startswith('+') and not line.startswith('+++'))
        for marker in ('ggml_vk_i260:v1|graph|id=%llu|phase=begin',
                       'ggml_vk_i260:v1|graph|id=%llu|phase=end|compute_submits=%llu',
                       'ggml_vk_i260:v1|submit|graph=%llu|id=%llu|phase=submit|path=serialized',
                       'ggml_vk_i260:v1|submit|graph=%llu|id=%llu|phase=submit|path=normal',
                       'ggml_vk_i260:v1|submit|graph=%llu|id=%llu|phase=wait|path=serialized|wait=success',
                       'ggml_vk_i260:v1|memory|role=backend|buffer=',
                       'ggml_vk_i260:v1|memory|role=backend|event=retire|buffer=',
                       'ggml_vk_i260:v1|tensor|name=output.weight|buffer=',
                       '|offset=%llu|bytes=%llu|allocation_size=%llu',
                       'ggml_vk_i260:v1|staging|owner=device|event=create|buffer=',
                       'ggml_vk_i260:v1|staging|owner=device|event=retire|buffer=',
                       'ggml_vk_i260:v1|staging|owner=context|event=create|buffer=',
                       'ggml_vk_i260:v1|staging|owner=context|event=retire|buffer='):
            self.assertIn(marker, additions)

    @unittest.skipUnless(PINNED.is_dir(), 'pinned llama.cpp checkout not locally available')
    def test_transform_is_deterministic_on_clean_pin(self):
        with tempfile.TemporaryDirectory(prefix='i260-transform-') as tmp:
            out_a, out_b = Path(tmp) / 'a', Path(tmp) / 'b'
            first = run_transform(PINNED, out_a)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_transform(PINNED, out_b)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((out_a / SOURCE_FILE).read_bytes(), (out_b / SOURCE_FILE).read_bytes())
            self.assertEqual(first.stdout, second.stdout)
            self.assertIn('instrumented_tree=' + json.loads(IDENTITY.read_text())['instrumented_tree'], first.stdout)

    @unittest.skipUnless(PINNED.is_dir(), 'pinned llama.cpp checkout not locally available')
    def test_modified_pin_is_rejected_before_transform(self):
        with tempfile.TemporaryDirectory(prefix='i260-modified-') as tmp:
            clone = Path(tmp) / 'source'
            subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(PINNED), str(clone)],
                           check=True, capture_output=True)
            subprocess.run(['git', '-C', str(clone), 'checkout', '--detach', PIN],
                           check=True, capture_output=True)
            target = clone / SOURCE_FILE
            target.write_bytes(target.read_bytes() + b'\n// modified\n')
            result = run_transform(clone, Path(tmp) / 'out')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('clean', (result.stderr + result.stdout).lower())


if __name__ == '__main__':
    unittest.main()
