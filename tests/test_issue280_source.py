"""Exact-source transform tests: pinned SOURCE ONLY, no binaries/models/devices."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/issue280_source.py"


class SourceTransformTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.is_file(), "exact-source transformer is missing")
        spec = importlib.util.spec_from_file_location("issue280_source", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_local_pinned_source_transform_is_additions_only(self):
        m = self.module()
        source = Path("/home/zutfen/llama.cpp-252")
        if not source.is_dir():
            self.skipTest("host-local pinned public source not present")
        originals = {p: (source / p).read_bytes() for p in m.SOURCE_HASHES}
        transformed, identity = m.transform(originals)
        self.assertEqual(identity["source_pin"], "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        self.assertEqual(identity["physical_runner"], "HELD_UNAVAILABLE")
        for path, original in originals.items():
            self.assertEqual(m.remove_insertions(path, transformed[path]), original)
            self.assertEqual((source / path).read_bytes(), original)
        self.assertIn("issue280::event", "\n".join(v.decode() for v in transformed.values()))

    def test_unpinned_source_refused_before_transform(self):
        m = self.module()
        with self.assertRaisesRegex(ValueError, "pinned source identity"):
            m.transform({p: b"not pinned source" for p in m.SOURCE_HASHES})

    def test_original_wait_and_transfer_calls_are_preserved(self):
        m = self.module()
        for operations in m.INSERTIONS.values():
            for anchor, extra, where in operations:
                self.assertIn(where, {"before", "after"})
                self.assertTrue(anchor)
                # New hooks may reference metadata, but cannot add synchronization,
                # transfers, dispatches, tensor gets/sets, or execution callbacks.
                for forbidden in ("waitForFences(", "getFenceStatus(", "waitSemaphores(",
                                  "ggml_backend_synchronize(", "ggml_vk_synchronize(",
                                  "ggml_backend_tensor_get(", "ggml_backend_tensor_set(",
                                  "ggml_backend_sched_set_eval_callback(", ".dispatch(",
                                  "memcpy(", "memset(", "queue.submit("):
                    self.assertNotIn(forbidden, extra)

    def test_full_transformed_git_tree_is_bound_to_pin(self):
        m = self.module()
        self.assertTrue(hasattr(m, "full_tree_identity"), "full transformed Git tree binding is missing")
        source = Path("/home/zutfen/llama.cpp-252")
        if not source.is_dir():
            self.skipTest("host-local pinned public source not present")
        originals = {p: (source / p).read_bytes() for p in m.SOURCE_HASHES}
        files, _ = m.transform(originals)
        identity = m.full_tree_identity(source, files)
        self.assertRegex(identity["full_transformed_git_tree"], r"^[0-9a-f]{40}$")
        self.assertRegex(identity["base_git_tree"], r"^[0-9a-f]{40}$")
        self.assertNotEqual(identity["full_transformed_git_tree"], identity["base_git_tree"])
        self.assertEqual(identity, m.full_tree_identity(source, files))

    def test_cpu_tests_are_registered_in_current_qualification_group(self):
        from scripts import plan_ci
        group = "r8i-qwen-qualification"
        modules = ("test_issue280_observer", "test_issue280_source")
        for module in modules:
            self.assertIn(module, plan_ci.GROUP_TEST_MODULES[group])
        paths = ("scripts/issue280_observer.py", "scripts/issue280_source.py",
                 "docs/investigations/vulkan-same-request-280/fixtures/recording.cpp",
                 "docs/investigations/vulkan-same-request-280/instrumentation/issue280_observer.h")
        for path in paths:
            planned = plan_ci.plan([path])
            self.assertFalse(planned["full_regression"], planned)
            self.assertIn(group, planned["groups"])

    def test_logging_sinks_are_translation_unit_local(self):
        header_dir = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            common = '#include <iostream>\n#define I280_LOG(s) (std::cout << LABEL << s << "\\n")\n#include "issue280_observer.h"\n'
            (td / "a.cpp").write_text('#define LABEL "A "\n' + common + 'void a() { I280_EVENT("test").emit(); }\n')
            (td / "b.cpp").write_text('#define LABEL "B "\n' + common + 'void b() { I280_EVENT("test").emit(); }\n')
            (td / "main.cpp").write_text('#include <cstdlib>\nvoid a(); void b(); int main(){setenv("ISSUE280_OBSERVE","1",1);a();b();}\n')
            binary = td / "two-sinks"
            subprocess.run(["c++", "-std=c++17", "-O0", "-I", str(header_dir),
                            str(td/"a.cpp"), str(td/"b.cpp"), str(td/"main.cpp"),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            raw = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
            self.assertEqual([line[:2] for line in raw.splitlines()], ["A ", "B "])


if __name__ == "__main__":
    unittest.main()


class SourceCorrectionTests(unittest.TestCase):
    def test_source_hooks_cover_collector_causality_and_inventory_shapes(self):
        m = SourceTransformTests().module()
        source = Path("/home/zutfen/llama.cpp-252")
        if not source.is_dir():
            self.skipTest("host-local pinned public source not present")
        originals = {path: (source / path).read_bytes() for path in m.SOURCE_HASHES}
        transformed, _ = m.transform(originals)
        self.assertIn("src/llama-model.cpp", m.SOURCE_HASHES)
        self.assertIn("src/llama-kv-cache.cpp", m.SOURCE_HASHES)
        server = transformed["tools/server/server-context.cpp"].decode()
        model = transformed["src/llama-model.cpp"].decode()
        kv = transformed["src/llama-kv-cache.cpp"].decode()
        self.assertIn('.json("token_ids", observed_tokens_json)', server)
        self.assertIn('.json("positions", observed_positions_json)', server)
        self.assertIn('.n("pos_present", observed_pos_present ? 1 : 0)', server)
        self.assertIn('.n("ordinal", ++observed_request_ordinal)', server)
        self.assertIn('.s("stop_reason", observed_stop_reason)', server)
        self.assertIn('.n("absolute_position", slot.prompt.tokens.pos_next())', server)
        self.assertIn('event("weight_inventory")', model)
        self.assertIn('event("kv_inventory")', kv)
        for path, original in originals.items():
            self.assertEqual(m.remove_insertions(path, transformed[path]), original)

    def test_emitter_json_field_preserves_array_type(self):
        header_dir = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "probe.cpp").write_text(
                '#include <iostream>\n'
                '#define I280_LOG(s) (std::cout << s << "\\n")\n'
                '#include "issue280_observer.h"\n'
                'int main() { setenv("ISSUE280_OBSERVE", "1", 1); '
                'I280_EVENT("batch_begin").json("token_ids", "[7,8]").emit(); }\n')
            binary = td / "json-field"
            subprocess.run(["c++", "-std=c++17", "-I", str(header_dir),
                            str(td / "probe.cpp"), "-o", str(binary)],
                           check=True, capture_output=True, text=True)
            raw = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
            self.assertIn('"token_ids":[7,8]', raw)
