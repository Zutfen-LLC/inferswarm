"""Issue #154 adapter-bound physical proof tests (CPU-only)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_vulkan_adapter as adapter  # noqa: E402

STDERR = """using device VkSelector (test accelerator) (0000:02:00.0)
offloaded 37/37 layers to GPU
"""


class V1AAdapterTests(unittest.TestCase):
    def test_adapter_binds_observation_to_opaque_inputs(self):
        observation = adapter.parse_backend_observation(
            stderr=STDERR, selector="VkSelector", expected_bdf="02:00.0",
            compute_unit_id="cu-opaque", memory_resource_id="mr-opaque",
            execution_unit_id="unit-opaque", implementation_id="impl-opaque",
            evidence_id="evidence-opaque", runtime_identity={"binary": "digest"})
        record = adapter.capability_record(
            compute_unit_id="cu-opaque", memory_resource_id="mr-opaque",
            execution_unit_id="unit-opaque", implementation_id="impl-opaque",
            evidence_id="evidence-opaque", bdf="02:00.0",
            runtime_identity={"binary": "digest"}, observation=observation)
        self.assertEqual(record["physical_device_bdf"], "02:00.0")
        self.assertEqual(record["bound_compute_unit_id"], "cu-opaque")

    def test_adapter_rejects_partial_offload_fallback_and_wrong_identity(self):
        args = dict(selector="VkSelector", expected_bdf="02:00.0", compute_unit_id="cu",
                    memory_resource_id="mr", execution_unit_id="unit", implementation_id="impl",
                    evidence_id="evidence", runtime_identity={"binary": "digest"})
        for stderr in (STDERR.replace("37/37", "36/37"), STDERR + "falling back to CPU\n",
                       STDERR.replace("02:00.0", "03:00.0")):
            with self.subTest(stderr=stderr), self.assertRaises(adapter.AdapterError):
                adapter.parse_backend_observation(stderr=stderr, **args)


if __name__ == "__main__":
    unittest.main()
