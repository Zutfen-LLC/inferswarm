"""Issue #143 backend-local adapter tests (CPU-only)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v0c_vulkan_adapter as adapter  # noqa: E402


STDERR = """
ggml_vulkan: 1 = AMD Radeon RX 580 Series (RADV POLARIS10) (0000:02:00.0)
llama_model_load: using device Vulkan1 (AMD Radeon RX 580 Series (RADV POLARIS10)) (0000:02:00.0) - 7900 MiB free
llama_model_load: offloaded 37/37 layers to GPU
"""


class V0CVulkanAdapterTests(unittest.TestCase):
    def test_observation_binds_selected_vulkan_device_and_offload(self):
        observed = adapter.parse_backend_observation(
            stderr=STDERR, selector="Vulkan1", expected_bdf="02:00.0"
        )
        self.assertEqual(observed["physical_device_bdf"], "02:00.0")
        self.assertEqual(observed["offloaded_layers"], [37, 37])
        self.assertTrue(observed["full_offload"])

    def test_wrong_device_or_partial_offload_fails_closed(self):
        with self.assertRaises(adapter.AdapterError):
            adapter.parse_backend_observation(
                stderr=STDERR, selector="Vulkan1", expected_bdf="04:00.0"
            )
        with self.assertRaises(adapter.AdapterError):
            adapter.parse_backend_observation(
                stderr=STDERR.replace("37/37", "36/37"),
                selector="Vulkan1", expected_bdf="02:00.0"
            )

    def test_capability_record_is_bound_to_compute_unit_not_vendor_subclass(self):
        record = adapter.capability_record(
            compute_unit_id="cu-amd-a", implementation_id="impl-portable-amd-a",
            evidence_id="evidence-amd-a", bdf="02:00.0", runtime_identity={"build": "x"}
        )
        self.assertEqual(record["bound_compute_unit_id"], "cu-amd-a")
        self.assertNotIn("vendor", record)
        self.assertNotIn("gpu_class", record)


if __name__ == "__main__":
    unittest.main()
