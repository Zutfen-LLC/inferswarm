"""Issue #264 source transform provenance and scope tests."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AREA = REPO / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism"
sys.path.insert(0, str(REPO / "scripts"))
import issue264_source_patch as S


class SourceTransformTests(unittest.TestCase):
    def test_identity_authenticates_complete_issue262_parent(self):
        identity = json.loads((AREA / "issue264-source-identity.json").read_text())
        self.assertEqual(identity["parent_tree"], "015c874f0cc0635fa1369650098c0137f9a492f0")
        self.assertEqual(identity["parent_vk_sha256"], "abb1031f1b35a669cb5a18b776fc6587cfb7927384729128048dd697b8160dbb")
        self.assertRegex(identity["issue264_tree"], r"^[0-9a-f]{40}$")
        patch = AREA / "patches/issue264-mmv-selector.patch"
        self.assertEqual(identity["patch_sha256"], hashlib.sha256(patch.read_bytes()).hexdigest())

    def test_patch_changes_only_exact_output_projection_dispatch(self):
        patch = (AREA / "patches/issue264-mmv-selector.patch").read_text()
        self.assertIn("GGML_VK_I264_MMV", patch)
        self.assertIn("output.weight", patch)
        self.assertIn("ggml_vk_i262", patch)
        self.assertIn("subgroup", patch)
        self.assertIn("hybrid", patch)
        self.assertIn("i264_local_x", patch)  # actual local-size specialization, not a claimed flag
        self.assertIn("dst->ne[2] == 1 && dst->ne[3] == 1", patch)
        self.assertTrue(S.I262_TREE == "015c874f0cc0635fa1369650098c0137f9a492f0")

    def test_transform_requires_new_output_and_exact_authenticated_parent(self):
        self.assertTrue(callable(S.build))
        self.assertEqual(S.PARENT_VK_SHA256,
                         "abb1031f1b35a669cb5a18b776fc6587cfb7927384729128048dd697b8160dbb")
        self.assertEqual(S.PARENT_TREE, "015c874f0cc0635fa1369650098c0137f9a492f0")

    def test_replay_clean_predecessor_reproduces_complete_frozen_tree(self):
        # A hosted runner without the pinned upstream checkout skips cleanly;
        # local audits can supply LLAMA_SRC explicitly.
        source = Path(os.environ.get("LLAMA_SRC", str(
            Path.home() / ".hermes/cache/scratch/i264-green-clean")))
        if not source.is_dir():
            self.skipTest("pinned clean predecessor absent; set LLAMA_SRC")
        identity = json.loads(S.IDENTITY.read_text())
        with tempfile.TemporaryDirectory(prefix="issue264-replay-") as tmp:
            output = Path(tmp) / "successor"
            self.assertEqual(S.build(source, output), identity)
            self.assertEqual(S.authenticate(output), "2d7a5693a8bf86648ee564d389a32c7c1671c571")
            self.assertTrue((output / S.VK).is_file())


if __name__ == "__main__":
    unittest.main()
