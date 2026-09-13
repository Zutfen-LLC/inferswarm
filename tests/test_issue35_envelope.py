"""CPU-only tests for the Issue #35 utility-envelope derivation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue35_envelope as envelope  # noqa: E402


def role(rate=None, complete=True, expected_failure=False):
    if expected_failure:
        return {"role_id": "r", "outcome": "EXPECTED_FAILURE"}
    return {
        "role_id": "r",
        "generation_tokens_per_s": {"median": rate},
        "offload": {"complete_offload": complete},
    }


def control(rate=40.0, complete=True):
    return {
        "role_id": "c",
        "generation_tokens_per_s": {"median": rate},
        "offload": {"complete_offload": complete},
    }


CAPACITY_BASIS = {
    "label": "CALCULATED",
    "capacity_positive": True,
    "control_pressure_facts": {
        "over_capacity": True,
        "over_capacity_devices": [{"device": "D0", "self_mib": 9021,
                                   "device_total_mib": 8192}],
        "fit_aborted": True,
        "fit_abort_reason": "n_gpu_layers already set by user",
        "projected_vs_free": [{"projected_mib": 32953,
                               "free_mib": 8186}],
        "context_reductions": [{"from": 131072, "to": 4096}],
    },
    "role_residency_facts": {
        "device_model_buffers_mib": {"D0": 3900.0, "D1": 4200.0},
        "model_buffer_placement_count": 2,
        "over_capacity": False,
        "over_capacity_devices": [],
    },
}


class ClassifyRoleTests(unittest.TestCase):
    def test_capacity_positive_throughput_negative(self):
        # capacity comes from measured memory-fit facts (capacity_basis),
        # never from the layer-count boolean alone
        result = envelope.classify_role(
            role(rate=10.0, complete=True), control(rate=40.0, complete=True),
            capacity_basis=CAPACITY_BASIS)
        self.assertEqual(
            result["classification"],
            "CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE")

    def test_capacity_positive_throughput_neutral(self):
        result = envelope.classify_role(
            role(rate=39.0, complete=True), control(rate=40.0, complete=True),
            capacity_basis=CAPACITY_BASIS)
        self.assertEqual(
            result["classification"],
            "CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL")

    def test_throughput_positive_with_capacity(self):
        result = envelope.classify_role(
            role(rate=50.0, complete=True), control(rate=40.0, complete=True),
            capacity_basis=CAPACITY_BASIS)
        self.assertEqual(result["classification"], "THROUGHPUT_POSITIVE")

    def test_throughput_positive_no_capacity(self):
        result = envelope.classify_role(
            role(rate=50.0, complete=True), control(rate=40.0, complete=True))
        self.assertEqual(result["classification"], "THROUGHPUT_POSITIVE")

    def test_not_useful_when_slower_no_capacity(self):
        result = envelope.classify_role(
            role(rate=20.0, complete=True), control(rate=40.0, complete=True))
        self.assertEqual(
            result["classification"], "NOT_USEFUL_FOR_TESTED_ROLE")

    def test_not_useful_when_neutral_no_capacity(self):
        result = envelope.classify_role(
            role(rate=40.0, complete=True), control(rate=40.0, complete=True))
        self.assertEqual(
            result["classification"], "NOT_USEFUL_FOR_TESTED_ROLE")

    def test_expected_failure_classifies_not_useful(self):
        result = envelope.classify_role(role(expected_failure=True), None)
        self.assertEqual(
            result["classification"], "NOT_USEFUL_FOR_TESTED_ROLE")

    def test_missing_control_insufficient(self):
        result = envelope.classify_role(role(rate=10.0), None)
        self.assertEqual(result["classification"], "EVIDENCE_INSUFFICIENT")

    def test_missing_throughput_reduction_insufficient(self):
        result = envelope.classify_role({"role_id": "r"}, control())
        self.assertEqual(result["classification"], "EVIDENCE_INSUFFICIENT")


class TransferCostTests(unittest.TestCase):
    TRANSPORT = {
        "sustained_transfers": {
            "h2d_4194304": {"gbps_median": 0.2},
            "d2h_4194304": {"gbps_median": 0.2},
        },
        "small_transfer_service": {"time_ms_median": 0.11},
    }

    def test_modeled_cost_uses_measured_rates(self):
        out = envelope.transfer_cost_per_token(self.TRANSPORT, 4096.0)
        self.assertEqual(out["label"], "CALCULATED")
        # 4096 bytes at 0.2 GB/s each way = 2 * 0.02048 ms
        self.assertAlmostEqual(out["modeled_link_ms_per_token"],
                               0.04096, places=6)

    def test_missing_measurements_fail_closed(self):
        with self.assertRaises(envelope.EnvelopeError):
            envelope.transfer_cost_per_token(
                {"sustained_transfers": {},
                 "small_transfer_service": {"time_ms_median": 0.1}}, 1.0)


class SourceAuditTests(unittest.TestCase):
    def test_no_width_vendor_policy_literals(self):
        module = (ROOT / "scripts/issue35_envelope.py").read_text("utf-8")
        for token in (" x1", "x4", "x8", "x16", "AMD", "NVIDIA",
                      "Radeon", "GeForce"):
            self.assertNotIn(token, module)


if __name__ == "__main__":
    unittest.main()
