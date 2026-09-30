"""Offline source-bound Vulkan path reconstruction regression tests."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import issue252_vulkanpath as path


REPO = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("LLAMA_SRC", "/home/zutfen/llama.cpp-252"))


def pinned_source_available():
    try:
        if not SOURCE.is_dir():
            return False
        path.verify_source(SOURCE)
    except (ValueError, OSError):
        # Unavailable includes unreadable (e.g. permission-denied paths that
        # exist on a shared host): skip cleanly, exactly like absence.
        return False
    return True


class TestIdentity(unittest.TestCase):
    def test_wrong_head_and_tree_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "marker").write_text("fixture", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "marker"], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "fixture"], check=True)
            head, tree = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD", "HEAD^{tree}"], text=True).splitlines()
            with self.assertRaises(ValueError):
                path.verify_source(root)
            with self.assertRaises(ValueError):
                path.verify_source(root, expected_head=head, expected_tree="0" * 40)
            with self.assertRaises(ValueError):
                path.verify_source(root, expected_head="0" * 40, expected_tree=tree)
            self.assertEqual(path.verify_source(root, expected_head=head, expected_tree=tree), {"head": head, "tree": tree})
            (root / "marker").write_text("dirty fixture", encoding="utf-8")
            with self.assertRaises(ValueError):
                path.verify_source(root, expected_head=head, expected_tree=tree)


@unittest.skipUnless(pinned_source_available(), "pinned llama.cpp source unavailable or wrong pin")
class TestPinnedReconstruction(unittest.TestCase):
    def test_every_citation_really_anchors_its_claim(self):
        doc = path.derive(SOURCE, REPO)
        self.assertTrue(doc["path_trace"])
        self.assertTrue(all(item["files"] for item in doc["path_trace"]))
        self.assertEqual(path.verify_citations(doc, SOURCE), True)
        self.assertTrue(all(c["proven"] for c in doc["controls"]))
        self.assertTrue(all(c["source_basis"] for c in doc["nondeterminism_candidates"]))
        source_vars = set(path.enumerate_env_controls(SOURCE))
        self.assertEqual(source_vars, {c["name"] for c in doc["controls"] if c["kind"] == "env"})

    def test_derive_is_byte_identical_twice(self):
        a = path.encode(path.derive(SOURCE, REPO))
        b = path.encode(path.derive(SOURCE, REPO))
        self.assertEqual(a, b)
        artifact = REPO / path.OUTPUT_REL
        self.assertEqual(artifact.read_bytes(), a)

    def test_citation_line_tamper_fails(self):
        doc = copy.deepcopy(path.derive(SOURCE, REPO))
        doc["path_trace"][0]["files"][0]["lines"][0] = 1
        with self.assertRaises(ValueError):
            path.verify_citations(doc, SOURCE)

    def test_exact_output_dispatch_and_negative_cache_claims(self):
        doc = path.derive(SOURCE, REPO)
        topics = {x["topic"] for x in doc["path_trace"]}
        self.assertTrue({"output_projection", "shader_dispatch", "pipeline_cache", "buffer_initialization", "submission", "descriptor_reuse", "reduction_order"} <= topics)
        text = json.dumps(doc)
        self.assertIn("GGML_TYPE_IQ1_S", text)
        self.assertIn("VK_NULL_HANDLE", text)
        self.assertIn("GGML_VK_SERIALIZE_SUBMISSIONS", text)
        self.assertIn("ggml_vk_guess_split_k", text)
