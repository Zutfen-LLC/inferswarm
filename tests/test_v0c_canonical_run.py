"""CPU-only contract tests for the V0-C two-stage runner and accounting."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v0c_canonical_run as runner  # noqa: E402


BASE = """
llama_prepare_model_devices: using device Vulkan1 (AMD) (0000:02:00.0) - 8186 MiB free
load_tensors: offloaded 37/37 layers to GPU
load_tensors:   CPU_Mapped model buffer size =   243.43 MiB
load_tensors:      Vulkan1 model buffer size =  1834.82 MiB
llama_context: Vulkan_Host  output buffer size =     0.58 MiB
llama_kv_cache:    Vulkan1 KV buffer size =  1152.00 MiB
sched_reserve:    Vulkan1 compute buffer size =   104.51 MiB
sched_reserve: Vulkan_Host compute buffer size =    40.02 MiB
common_memory_breakdown_print: | memory breakdown [MiB] | total free self model context compute unaccounted |
common_memory_breakdown_print: |   - Vulkan1 (AMD) | 8192 = 8186 + (3091 = 1834 + 1152 + 104) + -3086 |
slot operator(): id 0 | task 0 | cached n_tokens = 0, memory_seq_rm [0, end)
common_memory_breakdown_print: | memory breakdown [MiB] | total free self model context compute unaccounted |
common_memory_breakdown_print: |   - Vulkan1 (AMD) | 8192 = 5088 + (3091 = 1834 + 1152 + 104) + 12 |
common_memory_breakdown_print: |   - Host | 283 = 243 + 0 + 40 |
"""


class V0CCanonicalAccountingTests(unittest.TestCase):
    def test_parses_direct_accounting_and_retains_raw_lines(self):
        parsed = runner.parse_accounting(BASE)
        self.assertGreater(parsed["device_resident_model_bytes"], 0)
        self.assertGreater(parsed["device_context_bytes"], 0)
        self.assertGreater(parsed["device_compute_bytes"], 0)
        self.assertGreater(parsed["intentional_host_mapping_or_cache_bytes"], 0)
        self.assertEqual(parsed["unexplained_persistent_host_mirror_bytes"], 0)
        self.assertEqual(parsed["source_fetches_after_ready"], 0)
        self.assertEqual(parsed["unplanned_state_movements"], 0)
        self.assertTrue(parsed["raw_lines"]["ready_state"])
        self.assertEqual(len(parsed["raw_lines"]["device_memory_before_after"]), 2)

    def test_missing_required_accounting_line_fails_closed(self):
        with self.assertRaisesRegex(runner.AccountingError, "CPU_Mapped"):
            runner.parse_accounting(BASE.replace("load_tensors:   CPU_Mapped model buffer size =   243.43 MiB\n", ""))

    def test_contradictory_totals_fail_closed(self):
        bad = BASE.replace("|   - Host | 283 = 243 + 0 + 40 |", "|   - Host | 500 = 243 + 0 + 40 |")
        with self.assertRaisesRegex(runner.AccountingError, "host"):
            runner.parse_accounting(bad)

    def test_malformed_sizes_fail_closed(self):
        bad = BASE.replace("104.51 MiB", "not-a-size MiB")
        with self.assertRaisesRegex(runner.AccountingError, "compute"):
            runner.parse_accounting(bad)

    def test_unexplained_host_allocation_is_not_zeroed(self):
        bad = BASE.replace("|   - Host | 283 = 243 + 0 + 40 |", "|   - Host | 1940 = 1900 + 0 + 40 |")
        parsed = runner.parse_accounting(bad)
        self.assertGreater(parsed["unexplained_persistent_host_mirror_bytes"], 0)

    def test_missing_ready_state_accounting_fails_closed(self):
        with self.assertRaisesRegex(runner.AccountingError, "ready-state"):
            runner.parse_accounting(BASE.replace("slot operator(): id 0 | task 0 | cached n_tokens = 0, memory_seq_rm [0, end)\n", ""))

    def test_qualification_does_not_require_plan_and_canonical_does(self):
        qualification = {"schema": "inferswarm.v0c.qualification-observation/1"}
        runner.validate_stage_inputs("qualification", qualification, None)
        with self.assertRaisesRegex(RuntimeError, "plan"):
            runner.validate_stage_inputs("canonical", qualification, None)


if __name__ == "__main__":
    unittest.main()
