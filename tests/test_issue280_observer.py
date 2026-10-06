"""CPU recording fixtures exercise the Issue #280 collector, not proof dicts."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/issue280_observer.py"
INSTR = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"
FIXTURES = ROOT / "docs/investigations/vulkan-same-request-280/fixtures"


class CollectorRecordingTests(unittest.TestCase):
    def collect(self, case):
        self.assertTrue(SCRIPT.is_file(), "real Issue #280 collector is missing")
        spec = importlib.util.spec_from_file_location("issue280_observer", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "cpu-recording"
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(INSTR), str(FIXTURES / "recording.cpp"),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            raw = subprocess.run([str(binary), case], check=True,
                                 capture_output=True, text=True).stdout
            return module.collect(raw, module.fixture_contract()), raw

    def test_prefill_then_decode_eos_recording(self):
        result, raw = self.collect("positive")
        self.assertIn("I280 ", raw)
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["claim"], "CPU_RECORDING_REPLAY_ONLY")
        self.assertEqual(result["physical_runner"], "HELD_UNAVAILABLE")
        self.assertEqual(len(result["graphs"]), 3)
        self.assertEqual(result["sampled_tokens"], 3)
        self.assertEqual(result["non_eos_tokens"], 2)
        self.assertEqual(result["logical_boundary_bytes"], 96)
        self.assertEqual(result["host_leg_bytes"], 192)
        self.assertEqual(result["boundary_elapsed_ns"], 90)
        self.assertIsNone(result["pcie_wire_bytes"])

    def test_empty_submit_does_not_prove_compute(self):
        result, _ = self.collect("empty-submit")
        self.assertFalse(result["ok"])
        self.assertIn("graph 0: no completed nonempty compute on 0000:02:00.0", result["problems"])

    def test_missing_completion(self):
        result, _ = self.collect("missing-completion")
        self.assertFalse(result["ok"])
        self.assertIn("unfinished compute submissions", "\n".join(result["problems"]))

    def test_missing_host_leg(self):
        result, _ = self.collect("missing-host-leg")
        self.assertFalse(result["ok"])
        self.assertIn("host staging legs", "\n".join(result["problems"]))

    def test_request_mismatch(self):
        result, _ = self.collect("wrong-request")
        self.assertFalse(result["ok"])
        self.assertIn("request mismatch", "\n".join(result["problems"]))

    def test_output_length_mismatch(self):
        result, _ = self.collect("wrong-output")
        self.assertFalse(result["ok"])
        self.assertIn("response sampled count", "\n".join(result["problems"]))

    def test_boundary_byte_mismatch(self):
        result, _ = self.collect("wrong-bytes")
        self.assertFalse(result["ok"])
        self.assertIn("expected logical bytes", "\n".join(result["problems"]))

    def test_nested_leg_time_not_added_to_outer_elapsed(self):
        result, _ = self.collect("positive")
        self.assertEqual(result["boundary_elapsed_ns"], 90)

    def test_completion_cannot_precede_submit(self):
        result, _ = self.collect("early-completion")
        self.assertFalse(result["ok"])
        self.assertIn("completion has no pending submission", "\n".join(result["problems"]))

    def test_no_decode_for_first_sample_or_terminal_eos(self):
        result, _ = self.collect("eos-first")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(result["graphs"]), 1)
        self.assertEqual(result["sampled_tokens"], 1)
        self.assertEqual(result["non_eos_tokens"], 0)

    def test_source_shaped_staging_and_timeline_completion(self):
        result, _ = self.collect("native-path")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["logical_boundary_bytes"], 96)

    def test_timeline_completion_cannot_claim_unrecorded_value(self):
        result, _ = self.collect("timeline-stale")
        self.assertFalse(result["ok"])
        self.assertIn("timeline completion identity", "\n".join(result["problems"]))

    def test_source_log_cannot_be_promoted_to_physical_evidence(self):
        result, _ = self.collect("source-identity")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["claim"], "SOURCE_LOG_REPLAY_ONLY_NOT_PHYSICAL_PROOF")
        self.assertEqual(result["physical_runner"], "HELD_UNAVAILABLE")

    def test_non_eos_limit_uses_actual_sample_count(self):
        result, _ = self.collect("limit")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["non_eos_tokens"], 3)

    def test_schema_duplicate_fields_refused(self):
        result, raw = self.collect("positive")
        spec = importlib.util.spec_from_file_location("observer_duplicate", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        broken = raw.replace('"tokens":4', '"tokens":4,"tokens":4', 1)
        out = module.collect(broken, module.fixture_contract())
        self.assertFalse(out["ok"])
        self.assertIn("duplicate field", "\n".join(out["problems"]))

    def test_missing_preexecution_boundary_manifest(self):
        result, _ = self.collect("missing-manifest")
        self.assertFalse(result["ok"])
        self.assertIn("boundary manifest", "\n".join(result["problems"]))

    def test_prefill_microbatch_graphs_use_actual_token_count(self):
        result, _ = self.collect("microbatch")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(len(result["graphs"]), 4)
        self.assertEqual(result["sampled_tokens"], 3)
        self.assertEqual(result["logical_boundary_bytes"], 96)

    def test_abort_retains_pending_work_without_success(self):
        result, _ = self.collect("abort")
        self.assertFalse(result["ok"])
        self.assertTrue(result["graphs"])
        self.assertIn("unfinished compute submissions", result["problems"])
        self.assertEqual(result["sampled_tokens"], 0)

    def test_disabled_emitter_is_inert(self):
        _, raw = self.collect("disabled")
        self.assertEqual(raw, "")


if __name__ == "__main__":
    unittest.main()
