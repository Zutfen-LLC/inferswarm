"""CPU-only tests for the Issue #35 role sweep module."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue35_role_sweep as sweep  # noqa: E402


GOOD_STDOUT = (
    "\n> PROMPT_TEXT\nthe visible continuation bytes\n\n"
    "[ Prompt: 100.0 t/s | Generation: 40.0 t/s ]\n\nExiting...\n"
)
GOOD_STDERR = "I load_tensors: offloaded 37/37 layers to GPU\n"


class ParseTests(unittest.TestCase):
    def test_parse_rates(self):
        rates = sweep.parse_rates(GOOD_STDOUT)
        self.assertEqual(rates["generation_tokens_per_s"], 40.0)
        self.assertEqual(rates["prompt_tokens_per_s"], 100.0)

    def test_parse_rates_missing_fails_closed(self):
        with self.assertRaises(sweep.SweepError):
            sweep.parse_rates("no summary at all\n")

    def test_parse_offload_complete(self):
        out = sweep.parse_offload(GOOD_STDERR)
        self.assertTrue(out["complete_offload"])
        self.assertEqual(out["layers_offloaded"], 37)

    def test_parse_offload_partial(self):
        out = sweep.parse_offload("offloaded 20/37 layers to GPU\n")
        self.assertFalse(out["complete_offload"])
        self.assertEqual(out["layers_total"], 37)

    def test_parse_offload_missing_fails_closed(self):
        with self.assertRaises(sweep.SweepError):
            sweep.parse_offload("nothing here")


class VisibleOutputTests(unittest.TestCase):
    def test_extracts_continuation(self):
        out = sweep.visible_output(GOOD_STDOUT.replace("PROMPT_TEXT", "hello"),
                                   "hello")
        self.assertEqual(out.strip(), "the visible continuation bytes")

    def test_prompt_echo_missing_fails_closed(self):
        with self.assertRaises(sweep.SweepError):
            sweep.visible_output("unrelated", "hello")


class ArgvBuilderTests(unittest.TestCase):
    SPEC = {
        "runtime_executable": "/bin/true",
        "model": "/models/m.gguf",
        "prompt": "prompt",
        "selector": "SEL0",
    }

    def test_single_subject_control(self):
        argv = sweep.build_argv(self.SPEC, {
            "role_kind": "single_subject_control", "tokens": 48})
        self.assertIn("SEL0", argv)
        self.assertNotIn("-sm", argv)

    def test_layer_split(self):
        argv = sweep.build_argv(self.SPEC, {
            "role_kind": "coarse_layer_split", "tokens": 48,
            "peer_selector": "SEL1", "layer_split": "99"})
        self.assertEqual(argv[argv.index("--device") + 1], "SEL0,SEL1")
        self.assertEqual(argv[argv.index("-sm") + 1], "layer")

    def test_capacity_model_override(self):
        argv = sweep.build_argv(self.SPEC, {
            "role_kind": "capacity_feasibility", "tokens": 48,
            "peer_selector": "SEL1", "tensor_split": "0.5,0.5",
            "model_override": "/models/big.gguf"})
        self.assertIn("/models/big.gguf", argv)
        self.assertNotIn("/models/m.gguf", argv)

    def test_unknown_role_kind_fails_closed(self):
        with self.assertRaises(sweep.SweepError):
            sweep.build_argv(self.SPEC, {"role_kind": "made_up"})


class ReduceRoleTests(unittest.TestCase):
    SPEC = {"prompt": "prompt", "selector": "SEL0"}

    def _attempt(self, gen=40.0, exit_code=0):
        return {
            "exit_code": exit_code, "wall_seconds": 1.0,
            "stdout": f"[ Prompt: 1 t/s | Generation: {gen} t/s ]\n",
            "stderr": GOOD_STDERR,
        }

    def test_reduce_clean(self):
        result = sweep.reduce_role(
            self.SPEC,
            {"role_id": "r", "role_kind": "single_subject_control"},
            [self._attempt(40.0), self._attempt(41.0)], None)
        self.assertEqual(result["clean_attempts"], 2)
        self.assertEqual(result["generation_tokens_per_s"]["median"], 40.5)

    def test_reduce_with_reference(self):
        reference = "\nexpected\n"
        attempts = [{
            "exit_code": 0, "wall_seconds": 1.0,
            "stdout": "> prompt\nexpected\n\n[ Prompt: 1 t/s | Generation: 1 t/s ]\n",
            "stderr": GOOD_STDERR,
        }]
        result = sweep.reduce_role(
            self.SPEC, {"role_id": "r", "role_kind": "single_subject_control"},
            attempts, reference)
        self.assertTrue(result["byte_exact_vs_reference"]["all_match"])

    def test_expected_failure_path(self):
        result = sweep.reduce_role(
            self.SPEC,
            {"role_id": "r", "role_kind": "communication_heavy_row_split",
             "expected_failure_mode": "load failure"},
            [self._attempt(exit_code=1)], None)
        self.assertEqual(result["outcome"], "EXPECTED_FAILURE")

    def test_unexpected_all_failed_raises(self):
        with self.assertRaises(sweep.SweepError):
            sweep.reduce_role(
                self.SPEC,
                {"role_id": "r", "role_kind": "single_subject_control"},
                [self._attempt(exit_code=1)], None)


class SourceAuditTests(unittest.TestCase):
    """No subject literal may appear in the reusable sweep module bytes.

    Audit labels derive from the frozen campaign documents (authority
    data), never hardcoded, so this test cannot flag its own prose.
    """

    def _module(self):
        return (ROOT / "scripts/issue35_role_sweep.py").read_text("utf-8")

    def test_no_subject_literals_in_sweep_module(self):
        freeze = ROOT / "docs/investigations/link-x1-envelope/SUBJECT-FREEZE.json"
        if not freeze.is_file():
            self.skipTest("subject freeze not yet frozen")
        module = self._module()
        subjects = json.loads(freeze.read_text("utf-8"))["subjects"]
        for facts in subjects.values():
            for key in ("selector", "pci_bdf"):
                self.assertNotIn(facts[key], module)
        for token in ("Radeon", "GeForce", "3060", "580"):
            self.assertNotIn(token, module)

    def test_no_width_or_vendor_policy_literals(self):
        # Issue non-goal: no PCIe-width or vendor special cases as policy.
        # The role kinds are communication-shape names, not width/vendor
        # branches; assert no width/vendor token appears.
        module = self._module()
        for token in (" x1", "x4", "x8", "x16", "AMD", "NVIDIA"):
            self.assertNotIn(token, module)


if __name__ == "__main__":
    unittest.main()
