"""Issue #154 adapter-bound physical proof tests (CPU-only)."""
from __future__ import annotations

from dataclasses import replace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_vulkan_adapter as adapter  # noqa: E402

STDERR = """using device VkSelector (test accelerator) (0000:02:00.0)
offloaded 12/12 layers to GPU
"""

IDENTITY = {
    "node_id": "node-opaque",
    "compute_unit_id": "cu-opaque",
    "memory_resource_id": "mr-opaque",
    "execution_unit_id": "unit-opaque",
    "execution_contract_id": "contract-opaque",
    "implementation_id": "impl-opaque",
    "evidence_id": "qualification-opaque",
    "runtime_identity": {"binary": "digest"},
}


def observation(stderr: str = STDERR, **overrides):
    values = {**IDENTITY, **overrides}
    return adapter.parse_backend_observation(
        stderr=stderr, selector="VkSelector", expected_bdf="02:00.0", **values)


class V1AAdapterTests(unittest.TestCase):
    def test_adapter_accepts_generic_complete_twelve_layer_observation(self):
        sealed = observation()
        self.assertEqual(sealed.offloaded_layers, (12, 12))
        self.assertEqual(sealed.execution_contract_id, "contract-opaque")
        record = adapter.capability_record(bdf="02:00.0", observation=sealed, **IDENTITY)
        self.assertEqual(record["bound_node_id"], "node-opaque")
        self.assertEqual(record["execution_contract_id"], "contract-opaque")
        self.assertEqual(record["physical_device_bdf"], "02:00.0")

    def test_adapter_rejects_partial_offload_fallback_and_wrong_identity(self):
        for stderr in (STDERR.replace("12/12", "11/12"), STDERR + "falling back to CPU\n",
                       STDERR.replace("02:00.0", "03:00.0")):
            with self.subTest(stderr=stderr), self.assertRaises(adapter.AdapterError):
                observation(stderr)

    def test_observation_requires_a_nonempty_execution_contract(self):
        with self.assertRaises(adapter.AdapterError):
            observation(execution_contract_id="")

    def test_capability_record_rejects_wrong_node_contract_and_tampered_observation(self):
        sealed = observation()
        with self.assertRaises(adapter.AdapterError):
            adapter.capability_record(bdf="02:00.0", observation=sealed,
                                      **{**IDENTITY, "node_id": "node-other"})
        # Correct resource identities but the wrong expected contract fail closed.
        with self.assertRaises(adapter.AdapterError):
            adapter.capability_record(bdf="02:00.0", observation=sealed,
                                      **{**IDENTITY, "execution_contract_id": "contract-other"})
        with self.assertRaises(adapter.AdapterError):
            adapter.capability_record(bdf="02:00.0",
                                      observation=replace(sealed, node_id="node-other"), **IDENTITY)
        # A sealed contract-A observation whose sealed contract is altered no
        # longer validates (proof digest covers the contract).
        with self.assertRaises(adapter.AdapterError):
            adapter.capability_record(
                bdf="02:00.0",
                observation=replace(sealed, execution_contract_id="contract-other"), **IDENTITY)

    def test_canonical_proof_binds_every_runtime_and_plan_identity(self):
        sealed = observation()
        proof = adapter.seal_canonical_execution_proof(
            observation=sealed, plan_digest="plan-a", candidate_id="candidate-a",
            execution_contract_id="contract-opaque", execution_evidence_id="canonical-a",
            stdout=b"runtime output", stderr=STDERR, exit_code=0)
        self.assertEqual(proof.node_id, "node-opaque")
        self.assertEqual(proof.plan_digest, "plan-a")
        self.assertEqual(proof.execution_contract_id, "contract-opaque")
        for field, value in (("node_id", "node-other"), ("compute_unit_id", "cu-other"),
                             ("memory_resource_id", "mr-other"), ("execution_unit_id", "unit-other"),
                             ("execution_contract_id", "contract-other"),
                             ("implementation_id", "impl-other"), ("plan_digest", "plan-other"),
                             ("candidate_id", "candidate-other")):
            with self.subTest(field=field), self.assertRaises(adapter.AdapterError):
                adapter.validate_canonical_execution_proof(replace(proof, **{field: value}))

    def test_canonical_proof_rejects_noncanonical_exit_or_observation_mismatch(self):
        sealed = observation()
        for kwargs in ({"exit_code": 1}, {"stderr": STDERR + "fallback\n"},
                       {"execution_contract_id": "contract-other"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(adapter.AdapterError):
                adapter.seal_canonical_execution_proof(
                    observation=kwargs.pop("observation", sealed), plan_digest="plan-a",
                    candidate_id="candidate-a",
                    execution_contract_id=kwargs.pop("execution_contract_id", "contract-opaque"),
                    execution_evidence_id="canonical-a", stdout=b"runtime output",
                    stderr=kwargs.pop("stderr", STDERR), exit_code=kwargs.pop("exit_code", 0))


if __name__ == "__main__":
    unittest.main()
