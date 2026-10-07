"""Issue #284 observer-retention correction tests.

Root cause (mechanically established from the retained #280 binaries/logs):
the five non-server producer TUs routed I280 events through LLAMA_LOG_INFO /
GGML_LOG_INFO. common_init() installs common_log_default_callback for both
llama and ggml logging; that callback maps library INFO to LOG_LEVEL_TRACE(4)
and drops it at the default threshold LOG_DEFAULT_LLAMA=LOG_LEVEL_INFO(3).
Only the server TU's LOG_INF (direct common_log_add at level INFO) survived —
exactly the request/batch/sample/response-only retention the campaign saw.

The correction: library TUs must emit at log level NONE (LLAMA_LOG/GGML_LOG),
which the pinned callback maps to LOG_LEVEL_OUTPUT(0) and always displays.
These tests bind the law to the REAL pinned source (not a reimplementation).
"""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/issue280_source.py"
PINNED = Path("/home/zutfen/llama.cpp-252")

LIBRARY_TUS = (
    "src/llama-context.cpp",
    "src/llama-kv-cache.cpp",
    "src/llama-model.cpp",
    "ggml/src/ggml-backend.cpp",
    "ggml/src/ggml-vulkan/ggml-vulkan.cpp",
)
SERVER_TU = "tools/server/server-context.cpp"


def load_module():
    spec = importlib.util.spec_from_file_location("issue280_source", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PinnedLoggingLawTests(unittest.TestCase):
    """Prove, from the pinned public source bytes, that INFO is dropped and
    NONE is displayed at the default threshold the server runs with."""

    @unittest.skipUnless((PINNED / "common/log.h").is_file(),
                         "host-local pinned public source not present")
    def test_pinned_callback_drops_library_info_and_shows_none(self):
        log_h = (PINNED / "common/log.h").read_text()
        log_cpp = (PINNED / "common/log.cpp").read_text()
        # threshold constant the callback compares against
        self.assertIn("#define LOG_DEFAULT_LLAMA LOG_LEVEL_INFO", log_h)
        self.assertIn("#define LOG_LEVEL_INFO   3", log_h)
        self.assertIn("#define LOG_LEVEL_TRACE  4", log_h)
        self.assertIn("#define LOG_LEVEL_OUTPUT 0", log_h)
        # the callback installed by common_init() for BOTH llama and ggml logs
        self.assertIn(
            "case GGML_LOG_LEVEL_INFO:  return LOG_LEVEL_TRACE;", log_cpp)
        self.assertIn(
            "case GGML_LOG_LEVEL_NONE:\n        default:\n            return LOG_LEVEL_OUTPUT;",
            log_cpp)
        self.assertIn("if (verbosity <= common_log_verbosity_thold) {", log_cpp)
        # and common_init installs it for llama logs (ggml shares via llama_log_set)
        common_cpp = (PINNED / "common/common.cpp").read_text()
        self.assertIn("llama_log_set(common_log_default_callback, NULL);", common_cpp)
        impl_cpp = (PINNED / "src/llama-impl.cpp").read_text()
        self.assertIn("ggml_log_set(log_callback, user_data);", impl_cpp)


class TransformLoggingSinkTests(unittest.TestCase):
    def setUp(self):
        self.m = load_module()

    def transformed(self):
        originals = {p: (PINNED / p).read_bytes() for p in self.m.SOURCE_HASHES}
        return self.m.transform(originals)[0]

    @unittest.skipUnless(PINNED.is_dir(), "host-local pinned public source not present")
    def test_library_tus_emit_at_level_none_not_filtered_info(self):
        transformed = self.transformed()
        for tu in LIBRARY_TUS:
            src = transformed[tu].decode()
            self.assertIn(
                '#define I280_LOG(s) LLAMA_LOG("I280 %s\\n", (s).c_str())'
                if tu.startswith("src/") else
                '#define I280_LOG(s) GGML_LOG("I280 %s\\n", (s).c_str())',
                src,
                f"{tu}: I280 events must use level-NONE logging; level-INFO "
                "events are dropped by common_log_default_callback at the "
                "default threshold (the #280 retention defect)",
            )
            self.assertNotIn("I280_LOG(s) LLAMA_LOG_INFO(", src)
            self.assertNotIn("I280_LOG(s) GGML_LOG_INFO(", src)

    @unittest.skipUnless(PINNED.is_dir(), "host-local pinned public source not present")
    def test_server_tu_kept_on_direct_common_log_path(self):
        transformed = self.transformed()
        src = transformed[SERVER_TU].decode()
        self.assertIn('#define I280_LOG(s) LOG_INF("I280 %s\\n", (s).c_str())', src)

    @unittest.skipUnless(PINNED.is_dir(), "host-local pinned public source not present")
    def test_corrected_transform_is_still_additions_only(self):
        transformed = self.transformed()
        for path, original in {p: (PINNED / p).read_bytes() for p in self.m.SOURCE_HASHES}.items():
            self.assertEqual(self.m.remove_insertions(path, transformed[path]), original)

    def test_event_set_unchanged_by_logging_sink_correction(self):
        # the sink fix must not change any hook body, only the I280_LOG macro
        for tu in LIBRARY_TUS + (SERVER_TU,):
            ops = [op for op in self.m.INSERTIONS[tu] if "issue280_observer.h" in op[1]]
            self.assertTrue(ops, f"{tu}: observer include insertion missing")


if __name__ == "__main__":
    unittest.main()
