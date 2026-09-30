"""Prospective per-arm mechanism-evidence contracts (CPU-only fixtures)."""
from __future__ import annotations
import unittest
from pathlib import Path

from tests.test_issue252_physical import FixtureMixin, A, C
import issue252_mechanism as M

ENUM_NV = "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: NV_coopmat2\n"
ENUM_NONE = "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: none\n"
ENUM_KHR = "ggml_vulkan: 0 = NVIDIA GeForce RTX 3060 (NVIDIA) | matrix cores: KHR_coopmat\n"
DEV_ALLOC = ("ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB device at 0x1."
             " Total device: 4.00 MiB, total host: 0 B\n")
HOST_ALLOC = ("ggml_vulkan memory: NVIDIA GeForce RTX 3060: +16.00 MiB host at 0x2."
              " Total device: 4.00 MiB, total host: 16.00 MiB\n")
STAGING = "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4096)\n"
ASYNC_OFF = "ggml_vulkan: WARNING: Async execution disabled on certain Intel devices.\n"


def write(root: Path, namespace: str, name: str, log: str) -> None:
    unit = root / namespace / name
    unit.mkdir(parents=True, exist_ok=True)
    (unit / "server.log").write_text(log, encoding="utf-8")


class MechanismTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()
        self.ns = A.ARMS["A4"]["namespace"]

    # --- A1 non-terminal-capable ------------------------------------------

    def test_a1_is_non_terminal_capable(self):
        status = M.mechanism_status(self.evidence, "A1", A.ARMS["A1"]["namespace"])
        self.assertFalse(status["capable"])
        self.assertIn("serialize", status["reason"])

    # --- A2 ----------------------------------------------------------------

    def test_a2_positive_khr_disabled(self):
        # Only a NON-KHR, NON-NV family (e.g. "none") proves the KHR gate was
        # both live and path-changing on this subject.
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_NONE)
        status = M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])
        self.assertTrue(status["capable"])

    def test_a2_dead_control_on_nv_subject(self):
        # This RTX 3060's accepted capability line shows NV_coopmat2, which
        # GGML_VK_DISABLE_COOPMAT does not gate: dead control, no mechanism.
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_NV)
        with self.assertRaisesRegex(M.MechanismInvalid, "dead control"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    def test_a2_khr_still_active_rejected(self):
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", ENUM_KHR)
        with self.assertRaisesRegex(M.MechanismInvalid, "KHR coopmat still active"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    def test_a2_missing_enumeration_rejected(self):
        write(self.evidence, A.ARMS["A2"]["namespace"], "u1", "no markers\n")
        with self.assertRaisesRegex(M.MechanismInvalid, "enumeration"):
            M.mechanism_status(self.evidence, "A2", A.ARMS["A2"]["namespace"])

    # --- A3 ----------------------------------------------------------------

    def test_a3_positive(self):
        write(self.evidence, A.ARMS["A3"]["namespace"], "u1", ASYNC_OFF + ENUM_NV)
        status = M.mechanism_status(self.evidence, "A3", A.ARMS["A3"]["namespace"])
        self.assertTrue(status["capable"])

    def test_a3_marker_missing_rejected(self):
        write(self.evidence, A.ARMS["A3"]["namespace"], "u1", ENUM_NV)
        with self.assertRaisesRegex(M.MechanismInvalid, "marker"):
            M.mechanism_status(self.evidence, "A3", A.ARMS["A3"]["namespace"])

    # --- A4 ----------------------------------------------------------------

    def test_a4_positive(self):
        write(self.evidence, self.ns, "u1", ENUM_NV + DEV_ALLOC + HOST_ALLOC)
        status = M.mechanism_status(self.evidence, "A4", self.ns)
        self.assertTrue(status["capable"])
        self.assertGreaterEqual(status["facts"]["allocations"]["host"], 1)
        self.assertGreaterEqual(status["facts"]["allocations"]["device"], 1)

    def test_a4_no_host_allocation_rejected(self):
        write(self.evidence, self.ns, "u1", ENUM_NV + DEV_ALLOC)
        with self.assertRaisesRegex(M.MechanismInvalid, "host-typed allocation"):
            M.mechanism_status(self.evidence, "A4", self.ns)

    def test_a4_no_device_allocation_rejected(self):
        write(self.evidence, self.ns, "u1", ENUM_NV + HOST_ALLOC)
        with self.assertRaisesRegex(M.MechanismInvalid, "device-typed"):
            M.mechanism_status(self.evidence, "A4", self.ns)

    def test_a4_malformed_allocation_line_ignored_not_crash(self):
        # A near-miss line (missing unit) must not count as an allocation.
        bad = "ggml_vulkan memory: gpu: +4 device at 0x1\n"
        write(self.evidence, self.ns, "u1", ENUM_NV + bad + DEV_ALLOC + HOST_ALLOC)
        status = M.mechanism_status(self.evidence, "A4", self.ns)
        self.assertTrue(status["capable"])

    # --- A5 ----------------------------------------------------------------

    def test_a5_positive(self):
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1",
              ENUM_NV + STAGING + DEV_ALLOC)
        status = M.mechanism_status(self.evidence, "A5", A.ARMS["A5"]["namespace"])
        self.assertTrue(status["capable"])
        self.assertEqual(status["facts"]["allocations"]["host"], 0)

    def test_a5_host_allocation_rejected(self):
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1",
              ENUM_NV + STAGING + DEV_ALLOC + HOST_ALLOC)
        with self.assertRaisesRegex(M.MechanismInvalid, "host-typed allocation"):
            M.mechanism_status(self.evidence, "A5", A.ARMS["A5"]["namespace"])

    def test_a5_staging_line_missing_rejected(self):
        write(self.evidence, A.ARMS["A5"]["namespace"], "u1", ENUM_NV + DEV_ALLOC)
        with self.assertRaisesRegex(M.MechanismInvalid, "sync-staging"):
            M.mechanism_status(self.evidence, "A5", A.ARMS["A5"]["namespace"])

    # --- generic mutation discipline ---------------------------------------

    def test_missing_namespace_rejected(self):
        with self.assertRaisesRegex(M.MechanismInvalid, "absent/unsafe"):
            M.mechanism_status(self.evidence, "A4", "d252-nonexistent")

    def test_unknown_arm_rejected(self):
        with self.assertRaisesRegex(M.MechanismInvalid, "no prospective"):
            M.mechanism_status(self.evidence, "A9", self.ns)

    def test_mechanism_separate_from_determinism(self):
        # Mechanism facts carry no determinism claim; a capable status is
        # independent of retained rows/counts.
        write(self.evidence, self.ns, "only-one-unit", ENUM_NV + DEV_ALLOC + HOST_ALLOC)
        status = M.mechanism_status(self.evidence, "A4", self.ns)
        self.assertTrue(status["capable"])
        self.assertNotIn("deterministic", str(status["facts"]).lower())


if __name__ == "__main__":
    unittest.main()
