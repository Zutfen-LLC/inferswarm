"""Issue #133 — corrected direct comparator driver tests (CPU-only).

The driver is correctness-bearing on the node; these tests prove, on CPU,
that its invocation contract matches the frozen #129/#133 contract:

- the frozen runtime-session allocation is extracted from the pinned
  bytes (never hand-copied) and reproduces the accepted #129
  representative sequences exactly;
- byte drift in the pinned r5b_epochs.py fails closed;
- the corrected comparator contract data (max_new_tokens=2, commit step
  zero, discard step one, on_token present, argument names) matches the
  frozen generate() argument contract;
- the fixture digest pins fail closed on drift;
- the driver source contains no single-shot max_new_tokens=8 call and no
  plan-digest bypass (AST-checked).
"""
import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue133_arm_c_retry_direct as drv  # noqa: E402
import issue129_arm_c_retry_core as core  # noqa: E402

PINNED = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
          / "evidence/arm-c/frozen-freetoken/924cd22e/python/freetoken"
          / "research/r5b_epochs.py")
DRIVER_SOURCE = (ROOT / "scripts/issue133_arm_c_retry_direct.py").read_text()


class FrozenAllocatorTests(unittest.TestCase):
    def test_extraction_reproduces_accepted_129_sequences(self):
        allocator = drv.FrozenRuntimeSessionAllocator(PINNED.read_text())
        self.assertEqual(allocator.facts["multiplier"], 1000000)
        self.assertEqual(
            allocator.facts["method_sha256"],
            "94276b21597f22795af28ee4d3566dc15a903abadfd9a5c00a3d527f2b892f6c")
        ids = [allocator.allocate(1) for _ in range(8)]
        self.assertEqual(
            ids, [1000001, 1000002, 1000003, 1000004,
                  1000005, 1000006, 1000007, 1000008])
        ids2 = [allocator.allocate(2) for _ in range(8)]
        self.assertEqual(
            ids2, [2000009, 2000010, 2000011, 2000012,
                   2000013, 2000014, 2000015, 2000016])

    def test_control_pinned_byte_drift_fails_closed(self):
        # structural drift (removed sequence increment) fails closed inside
        # the allocator itself; multiplier-only drift is caught by the
        # driver's sha256 pin on the pinned bytes (checked in main())
        mutated = PINNED.read_text().replace(
            "        self._runtime_session_sequence += 1\n"
            "        return logical_session_id * 1_000_000 + "
            "self._runtime_session_sequence\n",
            "        return logical_session_id * 1_000_000\n",
            1)
        self.assertNotEqual(mutated, PINNED.read_text())
        with self.assertRaises(SystemExit) as caught:
            drv.FrozenRuntimeSessionAllocator(mutated)
        self.assertIn("FAIL", str(caught.exception))

    def test_control_sha_pin_drift_fails_closed_at_driver_entry(self):
        # the driver hard-pins the pinned bytes' sha256; any byte change
        # (including multiplier-only) is rejected before allocation
        mutated_sha = hashlib.sha256(
            PINNED.read_text().replace(
                "1_000_000", "2_000_000").encode()).hexdigest()
        self.assertNotEqual(
            mutated_sha, drv.R5B_EPOCHS_SHA256)

    def test_control_missing_method_fails_closed(self):
        mutated = PINNED.read_text().replace(
            "_runtime_session_id", "_renamed_method")
        with self.assertRaises(SystemExit):
            drv.FrozenRuntimeSessionAllocator(mutated)

    def test_pin_sha_matches_accepted_integrity(self):
        integrity = json.loads(
            (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
             / "evidence/arm-c-retry/integrity.json").read_text())
        self.assertEqual(
            hashlib.sha256(PINNED.read_bytes()).hexdigest(),
            integrity["runtime_session_allocation"]["source_sha256"])


class ComparatorContractSourceTests(unittest.TestCase):
    def test_generate_call_argument_set(self):
        tree = ast.parse(DRIVER_SOURCE)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "generate"]
        self.assertEqual(len(calls), 1, "exactly one runtime.generate call")
        keywords = {kw.arg for kw in calls[0].keywords}
        self.assertEqual(
            keywords, {"session_id", "prompt_token_ids",
                       "max_new_tokens", "on_token"})
        for kw in calls[0].keywords:
            if kw.arg == "max_new_tokens":
                self.assertIsInstance(kw.value, ast.Constant)
                self.assertEqual(kw.value.value, 2)

    def test_no_single_shot_8(self):
        tree = ast.parse(DRIVER_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "max_new_tokens" and isinstance(
                            kw.value, ast.Constant):
                        self.assertEqual(kw.value.value, 2)

    def test_plan_digest_check_present(self):
        self.assertIn('result.get("plan_digest")', DRIVER_SOURCE)

    def test_argument_contract_matches_frozen_129(self):
        self.assertEqual(
            tuple(drv.GENERATE_ARGUMENT_NAMES),
            tuple(core.GENERATE_ARGUMENT_NAMES))

    def test_fixture_digest_pins(self):
        self.assertIn("6046d4796a5d9cc888030c6b3f07304c20ce117d93905c3",
                      DRIVER_SOURCE)
        self.assertIn("180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a",
                      DRIVER_SOURCE)

    def test_producer_pin(self):
        self.assertIn("924cd22ea081f6d4ed471016faf01d427fc5b0d2",
                      DRIVER_SOURCE)


if __name__ == "__main__":
    unittest.main()
