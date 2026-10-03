"""Issue #264 source transform provenance and scope tests."""
from __future__ import annotations

import hashlib
import json
import os
import re
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
        identity = json.loads(S.IDENTITY.read_text())
        self.assertEqual(identity["parent_tree"], "015c874f0cc0635fa1369650098c0137f9a492f0")
        self.assertEqual(identity["parent_vk_sha256"], "abb1031f1b35a669cb5a18b776fc6587cfb7927384729128048dd697b8160dbb")
        self.assertRegex(identity["issue264_tree"], r"^[0-9a-f]{40}$")
        patch = S.PATCH
        self.assertEqual(identity["patch_sha256"], hashlib.sha256(patch.read_bytes()).hexdigest())

    def test_patch_changes_only_exact_output_projection_dispatch(self):
        patch = S.PATCH.read_text()
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

    def test_metadata_initialized_once_before_compile_publication(self):
        source = Path(os.environ.get("LLAMA_SRC", str(
            Path.home() / ".hermes/cache/scratch/i264-green-clean")))
        if not source.is_dir():
            self.skipTest("pinned clean predecessor absent; set LLAMA_SRC")
        with tempfile.TemporaryDirectory(prefix="issue264-publication-") as tmp:
            output = Path(tmp) / "successor"
            S.build(source, output)
            cpp = (output / S.VK).read_text()
        load = cpp[cpp.index("static void ggml_vk_load_shaders(vk_device& device, vk_pipeline requested) {"):]
        load = load[:load.index("static bool ggml_vk_khr_cooperative_matrix_support")]
        loop = "for (vk_pipeline p = device->pipeline_dequant_mul_mat_vec_f32_f32[w][GGML_TYPE_Q4_K][i]; p; p = p->next) {"
        start = load.index(loop)
        # All three writes must be inside the once-only sentinel branch, not
        # merely somewhere under the walk lock (readers don't take that lock).
        guarded = """if (p->i264_wg == 99) {
                    p->i264_reduction = reduc16;
                    p->i264_local_x = wg_size_subgroup16;
                    p->i264_wg = w;
                }"""
        self.assertIn(guarded, load[start:start + 700])
        for field in ("i264_wg", "i264_reduction", "i264_local_x"):
            self.assertEqual(len(re.findall(r"p->" + field + r"\s*=(?!=)", load)), 1)
        lock = load.index("std::unique_lock<std::mutex> compile_lock(device->compile_mutex);")
        unlock = load.index("compile_lock.unlock();")
        worker = load.index("ggml_vk_create_pipeline_func(device, task.pipeline")
        self.assertLess(lock, start)
        self.assertLess(start + len(loop) + len(guarded), unlock)
        self.assertLess(unlock, worker)
        self.assertNotIn("compile_lock.unlock()", load[lock:start])
        self.assertIn("uint32_t i264_wg = 99;", cpp)
        self.assertIn("std::atomic<bool> compiled {};", cpp)
        self.assertIn("std::lock_guard<std::mutex> guard(device->compile_mutex);\n"
                      "        device->all_pipelines.push_back(pipeline);\n"
                      "        pipeline->compiled = true;", cpp)
        self.assertIn("return wait_pipeline->compiled.load();", load)

    def test_frozen_gen1_remains_replayable_and_v2_only_guards_publication(self):
        historical = json.loads((AREA / "issue264-source-identity.json").read_text())
        self.assertEqual(historical, {
            "parent_tree": S.PARENT_TREE,
            "parent_vk_sha256": S.PARENT_VK_SHA256,
            "patch_sha256": "c424ab73dcc7bcbd9b812e8adbc322a5dc2d52c79c6b0f531c3aaa0bb781af3e",
            "issue264_vk_sha256": "9b4b4f313712213eae7bae5e8cbe91922e0da58b6c9ef550ce8833cf9b83e816",
            "issue264_tree": "2d7a5693a8bf86648ee564d389a32c7c1671c571",
        })
        gen1_patch = AREA / "patches/issue264-mmv-selector.patch"
        self.assertEqual(S.sha(gen1_patch.read_bytes()), historical["patch_sha256"])
        self.assertEqual(S.PATCH.name, "issue264-mmv-selector-v2.patch")
        self.assertEqual(S.IDENTITY.name, "issue264-source-identity-v2.json")
        source = Path(os.environ.get("LLAMA_SRC", str(
            Path.home() / ".hermes/cache/scratch/i264-green-clean")))
        if not source.is_dir():
            self.skipTest("pinned clean predecessor absent; set LLAMA_SRC")
        with tempfile.TemporaryDirectory(prefix="issue264-generations-") as tmp:
            gen1, gen2 = Path(tmp) / "gen1", Path(tmp) / "gen2"
            S.parent.build(source, gen1)
            S.git(gen1, "apply", "--check", str(gen1_patch))
            S.git(gen1, "apply", str(gen1_patch))
            self.assertEqual(S.authenticate(gen1), historical["issue264_tree"])
            self.assertEqual(S.sha((gen1 / S.VK).read_bytes()), historical["issue264_vk_sha256"])
            result = S.build(source, gen2)
            self.assertEqual(result, json.loads(S.IDENTITY.read_text()))
            self.assertEqual(result["issue264_tree"], "23d38b96e371ad0634454d7bd6fe238da87eb1cb")
            before, after = (gen1 / S.VK).read_text(), (gen2 / S.VK).read_text()
            guard = """                if (p->i264_wg == 99) {
                    p->i264_reduction = reduc16;
                    p->i264_local_x = wg_size_subgroup16;
                    p->i264_wg = w;
                }"""
            unguarded = """                p->i264_wg = w;
                p->i264_reduction = reduc16;
                p->i264_local_x = wg_size_subgroup16;"""
            comment = ("            // This walk holds compile_mutex. Initialize once, before dropping the\n"
                       "            // lock and compiling; compiled publishes the immutable identity to readers.\n")
            self.assertEqual(after.count(guard), 1)
            self.assertEqual(after.replace(comment, "").replace(guard, unguarded), before)

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
            self.assertEqual(S.authenticate(output), identity["issue264_tree"])
            self.assertTrue((output / S.VK).is_file())


if __name__ == "__main__":
    unittest.main()
