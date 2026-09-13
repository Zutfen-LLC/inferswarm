"""CPU-only tests for the Issue #35 transport probe module."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue35_link_probe as probe  # noqa: E402


class LinkGenerationTests(unittest.TestCase):
    def test_known_labels(self):
        self.assertEqual(probe.link_generation("2.5 GT/s PCIe"), 1)
        self.assertEqual(probe.link_generation("5.0 GT/s PCIe"), 2)
        self.assertEqual(probe.link_generation("8.0 GT/s PCIe"), 3)
        self.assertEqual(probe.link_generation("16.0 GT/s PCIe"), 4)

    def test_unknown_label_fails_closed(self):
        with self.assertRaises(probe.ProbeError):
            probe.link_generation("42 GT/s magic")


class ParseProbeOutputTests(unittest.TestCase):
    def _stream(self):
        header = ('{"vk_device_index": 3, "device_name": "DEV X", '
                  '"name_match_rank": 0, "name_match_count": 1, '
                  '"api_version": "1.4.351"}')
        sustained = ('"sustained": [\n'
                     '  {"dir": "h2d", "bytes": 8, "rep": 0, "ms": 4.000000},\n'
                     '  {"dir": "d2h", "bytes": 8, "rep": 0, "ms": 4.000000}\n'
                     '],\n')
        latency = ('"latency": [\n'
                   '  {"bytes": 4096, "rep": 0, "ms": 0.100000}\n'
                   '],\n')
        bidir = ('"bidir": [\n'
                 '  {"bytes_each_direction": 16, "rep": 0, "ms": 8.000000}\n'
                 ']\n')
        return "\n".join([header, sustained, latency, bidir])

    def test_parse_roundtrip(self):
        parsed = probe.parse_probe_output(self._stream())
        self.assertEqual(parsed["identity"]["device_name"], "DEV X")
        self.assertEqual(len(parsed["sustained"]), 2)
        self.assertEqual(parsed["bidir"][0]["bytes_each_direction"], 16)

    def test_missing_header_fails_closed(self):
        with self.assertRaises(probe.ProbeError):
            probe.parse_probe_output('{"no": "identity"}')

    def test_zero_generation_rate_required(self):
        stderr = ("using device Vulkan9 (Some Device) (0000:0a:00.0)\n")
        stdout_ok = "[ Prompt: 1.0 t/s | Generation: 0.0 t/s ]"
        stdout_bad = "[ Prompt: 1.0 t/s | Generation: 12.5 t/s ]"
        result = probe.validate_identity_probe(
            stdout_ok, stderr, 0, "Vulkan9")
        self.assertEqual(result["pci_bdf"], "0a:00.0")
        self.assertEqual(result["tokens_generated"], 0)
        with self.assertRaises(probe.ProbeError):
            probe.validate_identity_probe(stdout_bad, stderr, 0, "Vulkan9")

    def test_identity_probe_requires_exactly_one_device_line(self):
        stdout = "[ Prompt: 1.0 t/s | Generation: 0.0 t/s ]"
        two = ("using device Vulkan1 (A) (0000:02:00.0)\n"
               "using device Vulkan3 (B) (0000:04:00.0)\n")
        with self.assertRaises(probe.ProbeError):
            probe.validate_identity_probe(stdout, two, 0, "Vulkan1")

    def test_identity_probe_selector_mismatch_fails(self):
        stdout = "[ Prompt: 1.0 t/s | Generation: 0.0 t/s ]"
        stderr = "using device Vulkan1 (A) (0000:02:00.0)\n"
        with self.assertRaises(probe.ProbeError):
            probe.validate_identity_probe(stdout, stderr, 0, "Vulkan3")


class ReduceRowsTests(unittest.TestCase):
    def test_reduce_distribution(self):
        # 100 MB in 0.1 s = 1.0 GB/s (realistic magnitudes)
        rows = [{"ms": 100.0, "bytes": 100_000_000},
                {"ms": 200.0, "bytes": 100_000_000},
                {"ms": 300.0, "bytes": 100_000_000}]
        out = probe.reduce_rows(rows)
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["time_ms_median"], 200.0)
        self.assertAlmostEqual(out["gbps_median"], 0.5, places=3)

    def test_mixed_sizes_fail_closed(self):
        rows = [{"ms": 1.0, "bytes": 100}, {"ms": 1.0, "bytes": 200}]
        with self.assertRaises(probe.ProbeError):
            probe.reduce_rows(rows)

    def test_invalid_rows_fail_closed(self):
        with self.assertRaises(probe.ProbeError):
            probe.reduce_rows([{"ms": 0, "bytes": 100}])
        with self.assertRaises(probe.ProbeError):
            probe.reduce_rows([])


class TwinBindingTests(unittest.TestCase):
    def _samples(self, subject_states, control_states):
        rows = []
        for i, (subj, ctrl) in enumerate(zip(subject_states, control_states)):
            rows.append({
                "phase": "idle:pre" if i == 0 else f"watch:{i}",
                "subject": subj,
                "control_03:00.0": ctrl,
            })
        return rows

    def _state(self, speed, width, max_speed="8.0 GT/s PCIe", max_width=16):
        return {"current_link_speed": speed, "current_link_width": width,
                "max_link_speed": max_speed, "max_link_width": max_width}

    def test_uptrain_binding_passes(self):
        idle = self._state("2.5 GT/s PCIe", "1")
        up = self._state("8.0 GT/s PCIe", "1")
        samples = self._samples(
            [idle, idle, up, idle],
            [idle, idle, idle, idle])
        result = probe.verify_twin_binding(samples, "02:00.0", ["03:00.0"])
        self.assertTrue(result["bound"])

    def test_control_also_active_fails_closed(self):
        idle = self._state("2.5 GT/s PCIe", "1")
        up = self._state("8.0 GT/s PCIe", "1")
        samples = self._samples(
            [idle, up, idle],
            [idle, up, idle])
        with self.assertRaises(probe.ProbeError):
            probe.verify_twin_binding(samples, "02:00.0", ["03:00.0"])

    def test_pegged_floor_binding_passes_with_idle_controls(self):
        floor = self._state("2.5 GT/s PCIe", "1")
        samples = self._samples([floor, floor, floor, floor],
                                [floor, floor, floor, floor])
        result = probe.verify_twin_binding(samples, "02:00.0", ["03:00.0"])
        self.assertTrue(result["bound"])

    def test_no_samples_fails_closed(self):
        with self.assertRaises(probe.ProbeError):
            probe.verify_twin_binding([], "02:00.0", ["03:00.0"])


class SourceAuditTests(unittest.TestCase):
    """No subject literal may appear in the reusable probe module bytes.

    Audit labels derive from authority data (the campaign subject freeze)
    rather than a hardcoded list, so this test cannot flag its own prose.
    """

    def test_no_subject_literals_in_module(self):
        freeze = ROOT / "docs/investigations/link-x1-envelope/SUBJECT-FREEZE.json"
        if not freeze.is_file():
            self.skipTest("subject freeze not yet frozen")
        subjects = json.loads(freeze.read_text(encoding="utf-8"))["subjects"]
        module_bytes = (ROOT / "scripts/issue35_link_probe.py").read_text(
            encoding="utf-8")
        for subject_id, facts in subjects.items():
            for key in ("selector", "pci_bdf"):
                self.assertNotIn(facts[key], module_bytes,
                                 f"subject literal {key}={facts[key]!r} "
                                 f"leaked into reusable probe logic")
            # the vendor-class and full device-name strings
            for token in ("Radeon", "GeForce", "3060", "580"):
                self.assertNotIn(token, module_bytes)


if __name__ == "__main__":
    unittest.main()
