"""Frozen semantic task checker for the #280 mechanism experiment (issue #284).

The checker verifies model CONTENT, not output formatting: correct three-field
JSON wrapped in Markdown fences or brief introductory prose is accepted; wrong,
missing, ambiguous, or contradictory field values are rejected. Deterministic;
tolerance frozen before any rerun; never tuned from candidate observations.
"""
from pathlib import Path
import importlib.util
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/issue280_task_check.py"

# Frozen expected semantic values per prompt (#280 freeze task_rubric).
EXPECTED_P1 = {"service": "payments", "severity": "high", "status": "resolved"}
EXPECTED_P2 = {"service": "search", "severity": "low", "status": "open"}

# Verbatim retained physical responses (issue #280 resumed campaign,
# req-L1-cold.json / req-L5-cold.json) — diagnostic observations, reused here
# only as frozen checker fixtures.
RETAINED_P1_TEXT = (
    " Here is the JSON output based on the provided incident details:\n\n"
    "```json\n"
    "{\n  \"service\": \"payments\",\n  \"severity\": \"high\",\n  \"status\": \"resolved\"\n}\n"
    "```"
)
RETAINED_P2_WRONG_SERVICE_TEXT = (
    " Here is the incident information extracted as JSON:\n\n"
    "```json\n"
    "{\n  \"service\": \"service=search\",\n  \"severity\": \"low\",\n  \"status\": \"open\"\n}\n"
    "```"
)


class SemanticCheckerLoad(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.is_file(), "frozen semantic task checker is missing")
        spec = importlib.util.spec_from_file_location("issue280_task_check", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class SemanticPositiveTests(SemanticCheckerLoad):
    def test_pure_json_object_accepted(self):
        m = self.module()
        ok, reason = m.check("P1", '{"service":"payments","severity":"high","status":"resolved"}')
        self.assertTrue(ok, reason)

    def test_retained_p1_prose_and_fences_accepted(self):
        m = self.module()
        ok, reason = m.check("P1", RETAINED_P1_TEXT)
        self.assertTrue(ok, reason)

    def test_brief_intro_prose_then_bare_json_accepted(self):
        m = self.module()
        text = "Sure! Here is the result: {\"service\": \"search\", \"severity\": \"low\", \"status\": \"open\"}"
        ok, reason = m.check("P2", text)
        self.assertTrue(ok, reason)

    def test_expected_values_are_frozen_per_prompt(self):
        m = self.module()
        self.assertEqual(m.EXPECTED["P1"], EXPECTED_P1)
        self.assertEqual(m.EXPECTED["P2"], EXPECTED_P2)
        self.assertEqual(m.FIELDS, ("service", "severity", "status"))


class SemanticNegativeTests(SemanticCheckerLoad):
    def test_retained_p2_wrong_service_value_rejected(self):
        m = self.module()
        ok, reason = m.check("P2", RETAINED_P2_WRONG_SERVICE_TEXT)
        self.assertFalse(ok)
        self.assertIn("service", reason)
        self.assertIn("service=search", reason)

    def test_wrong_severity_value_rejected(self):
        m = self.module()
        ok, reason = m.check(
            "P1", '{"service":"payments","severity":"low","status":"resolved"}')
        self.assertFalse(ok)
        self.assertIn("severity", reason)

    def test_missing_field_rejected(self):
        m = self.module()
        ok, reason = m.check("P1", '{"service":"payments","severity":"high"}')
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_extra_keys_rejected_as_ambiguous(self):
        m = self.module()
        ok, reason = m.check(
            "P1",
            '{"service":"payments","severity":"high","status":"resolved","note":"x"}')
        self.assertFalse(ok)

    def test_no_json_at_all_rejected(self):
        m = self.module()
        ok, reason = m.check("P1", "The incident is about payments with high severity.")
        self.assertFalse(ok)

    def test_two_contradictory_json_objects_rejected(self):
        m = self.module()
        text = ('{"service":"payments","severity":"high","status":"resolved"} '
                'and {"service":"payments","severity":"low","status":"resolved"}')
        ok, reason = m.check("P1", text)
        self.assertFalse(ok)
        self.assertIn("ambiguous", reason.lower())

    def test_non_string_field_value_rejected(self):
        m = self.module()
        ok, reason = m.check(
            "P1", '{"service":"payments","severity":"high","status":2}')
        self.assertFalse(ok)

    def test_p1_expected_values_do_not_leak_into_p2(self):
        m = self.module()
        ok, reason = m.check("P2", '{"service":"payments","severity":"high","status":"resolved"}')
        self.assertFalse(ok)

    def test_unknown_prompt_rejected(self):
        m = self.module()
        with self.assertRaisesRegex(KeyError, "P3"):
            m.check("P3", "{}")


class DeterminismTests(SemanticCheckerLoad):
    def test_checker_is_deterministic_across_repeated_calls(self):
        m = self.module()
        for text in (RETAINED_P1_TEXT, RETAINED_P2_WRONG_SERVICE_TEXT, "garbage"):
            results = {m.check("P1" if text is RETAINED_P1_TEXT else "P2", text) for _ in range(3)}
            self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
