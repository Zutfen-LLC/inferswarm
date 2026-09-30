import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import issue252_arms as arms


class Issue252ArmsTests(unittest.TestCase):
    def test_real_arms_validate(self):
        self.assertEqual([], arms.validate_arms())

    def test_missing_provenance_fails(self):
        changed = {key: dict(value) for key, value in arms.ARMS.items()}
        changed["A1"]["control"] = dict(changed["A1"]["control"])
        changed["A1"]["control"].pop("provenance")
        self.assertTrue(any("missing control provenance" in p for p in arms.validate_arms(changed)))

    def test_duplicate_namespace_fails(self):
        changed = {key: dict(value) for key, value in arms.ARMS.items()}
        changed["A2"]["namespace"] = changed["A1"]["namespace"]
        self.assertTrue(any("duplicate namespace" in p for p in arms.validate_arms(changed)))

    def test_unknown_control_fails(self):
        changed = {key: dict(value) for key, value in arms.ARMS.items()}
        changed["A1"]["control"] = dict(changed["A1"]["control"], name="GGML_VK_NOT_A_REAL_CONTROL")
        self.assertTrue(any("control name absent" in p for p in arms.validate_arms(changed)))

    def test_invalid_unit_count_fails(self):
        changed = {key: dict(value) for key, value in arms.ARMS.items()}
        changed["A1"]["units"] = {"variable_stop": 4, "min": 2}
        self.assertTrue(any("unit counts violate REPEAT_LAW" in p for p in arms.validate_arms(changed)))

    def test_matrix_generation_is_byte_deterministic(self):
        first, second = arms.matrix_bytes(), arms.matrix_bytes()
        self.assertEqual(first, second)
        self.assertEqual(0, arms.main() or 0)
        self.assertEqual(first, arms.MATRIX_PATH.read_bytes())
        arms.MATRIX_PATH.unlink()
        arms.main()
        self.assertEqual(first, arms.MATRIX_PATH.read_bytes())


if __name__ == "__main__":
    unittest.main()
