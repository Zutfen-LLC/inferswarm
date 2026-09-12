"""Issue #143 backend-local adapter tests (CPU-only)."""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
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
    def _validated_observation(self, **overrides):
        arguments = {
            "stderr": STDERR,
            "selector": "Vulkan1",
            "expected_bdf": "02:00.0",
            "compute_unit_id": "cu-amd-a",
            "memory_resource_id": "mr-amd-a-vram",
            "execution_unit_id": "unit-q4km-whole-model",
            "implementation_id": "impl-portable-amd-a",
            "evidence_id": "evidence-amd-a",
            "runtime_identity": {"binary_sha256": "build-x", "driver": "radv-x"},
        }
        arguments.update(overrides)
        return adapter.parse_backend_observation(**arguments)

    def _capability_record(self, observation, **overrides):
        arguments = {
            "compute_unit_id": "cu-amd-a",
            "memory_resource_id": "mr-amd-a-vram",
            "execution_unit_id": "unit-q4km-whole-model",
            "implementation_id": "impl-portable-amd-a",
            "evidence_id": "evidence-amd-a",
            "bdf": "02:00.0",
            "runtime_identity": {"binary_sha256": "build-x", "driver": "radv-x"},
            "observation": observation,
        }
        arguments.update(overrides)
        return adapter.capability_record(**arguments)

    def test_capability_requires_validated_observation_bound_to_all_identities(self):
        observed = self._validated_observation()
        record = self._capability_record(observed)
        self.assertEqual(record["bound_compute_unit_id"], "cu-amd-a")
        self.assertEqual(record["bound_memory_resource_id"], "mr-amd-a-vram")
        self.assertEqual(record["bound_execution_unit_id"], "unit-q4km-whole-model")
        self.assertEqual(record["observation_evidence_id"], "evidence-amd-a")

        with self.assertRaises(adapter.AdapterError):
            self._capability_record(None)
        for field, wrong in (
            ("compute_unit_id", "cu-other"),
            ("memory_resource_id", "mr-other"),
            ("execution_unit_id", "unit-other"),
            ("implementation_id", "impl-other"),
            ("evidence_id", "evidence-other"),
            ("runtime_identity", {"binary_sha256": "other", "driver": "radv-x"}),
            ("bdf", "04:00.0"),
        ):
            with self.subTest(field=field), self.assertRaises(adapter.AdapterError):
                self._capability_record(observed, **{field: wrong})

        # A copied object with changed facts no longer carries a valid proof seal.
        with self.assertRaises(adapter.AdapterError):
            self._capability_record(replace(observed, evidence_id="evidence-other"))
        mutated_runtime = self._validated_observation()
        mutated_runtime.runtime_identity["driver"] = "other-driver"
        with self.assertRaises(adapter.AdapterError):
            self._capability_record(mutated_runtime)

    def test_observation_rejects_contradiction_fallback_and_partial_offload(self):
        contradictory = STDERR + (
            "llama_model_load: using device Vulkan2 (other) (0000:04:00.0)\n"
        )
        for stderr in (
            contradictory,
            STDERR + "llama_model_load: falling back to CPU execution\n",
            STDERR.replace("37/37", "36/37"),
        ):
            with self.subTest(stderr=stderr), self.assertRaises(adapter.AdapterError):
                self._validated_observation(stderr=stderr)

    def test_observation_binds_selected_vulkan_device_and_offload(self):
        observed = self._validated_observation().facts()
        self.assertEqual(observed["physical_device_bdf"], "02:00.0")
        self.assertEqual(observed["offloaded_layers"], [37, 37])
        self.assertTrue(observed["full_offload"])

    def test_wrong_device_or_partial_offload_fails_closed(self):
        with self.assertRaises(adapter.AdapterError):
            self._validated_observation(expected_bdf="04:00.0")
        with self.assertRaises(adapter.AdapterError):
            self._validated_observation(stderr=STDERR.replace("37/37", "36/37"))

    def test_capability_record_is_bound_to_compute_unit_not_vendor_subclass(self):
        observation = self._validated_observation()
        record = self._capability_record(observation)
        self.assertEqual(record["bound_compute_unit_id"], "cu-amd-a")
        self.assertNotIn("vendor", record)
        self.assertNotIn("gpu_class", record)


if __name__ == "__main__":
    unittest.main()
