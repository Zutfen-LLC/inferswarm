"""Issue #110 terminal-report decimal-derivation regression (CPU-only).

The exact hexadecimal values in
docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json
are authoritative. This suite proves every decimal conversion and headroom
percentage DISPLAYED in b/TERMINAL-REPORT.md is derived correctly from those
exact hex strings via standard hex-float conversion (float.fromhex), so a
hand-transcription error in human-readable prose cannot recur silently.

Background: the original terminal report mistranscribed the decimals
(e.g. 0x1.d2p+4 written as 14.625 instead of 29.125). The pass verdicts were
unaffected (they derive from the hex comparison), but the prose was wrong.
This test fails if the report and the authoritative hex ever diverge again.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B_DIR = ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110/b"
ADJ = B_DIR / "holdout-adjudication.json"
REPORT = B_DIR / "TERMINAL-REPORT.md"


class TestTerminalReportDecimals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adj = json.loads(ADJ.read_text())
        cls.report = REPORT.read_text()
        # The authoritative core table of the report (the FIRST such table;
        # the correction blockquote quotes old values deliberately and the
        # historical values are named there as "not X", so we only bind the
        # table rows).
        cls.rows = {}
        for line in cls.report.splitlines():
            m = re.match(
                r"^\|\s*([A-Za-z0-9:._-]+)\s*\|"  # family
                r"\s*(0x[0-9a-fp.+-]+)\s*\(([0-9.]+)\)\s*\|"   # observed hex (dec)
                r"\s*(0x[0-9a-fp.+-]+)\s*\(([0-9.]+)\)\s*\|"    # limit hex (dec)
                r"\s*([0-9.]+)%\s*\|\s*(PASS|FAIL)\s*\|\s*$",
                line,
            )
            if m:
                cls.rows[m.group(1)] = m.groups()

    def test_core_table_present(self):
        self.assertEqual(
            set(self.rows),
            {
                "fp32-consumer-logits:max-absolute-difference",
                "fp32-consumer-logits:rms-difference",
                "decision_local_E_D",
            },
            "terminal report must display exactly the three core families",
        )

    def test_report_hex_matches_authoritative_adjudication(self):
        fam_map = {
            "fp32-consumer-logits:max-absolute-difference":
                "fp32-consumer-logits:max-absolute-difference",
            "fp32-consumer-logits:rms-difference":
                "fp32-consumer-logits:rms-difference",
            "decision_local_E_D": "decision_local_E_D",
        }
        for fam, groups in self.rows.items():
            with self.subTest(family=fam):
                key = fam_map[fam]
                self.assertEqual(
                    float.fromhex(groups[1]),
                    float.fromhex(self.adj["core_observed_maxima"][key]),
                    f"{fam}: report observed hex != adjudication hex")
                self.assertEqual(
                    float.fromhex(groups[3]),
                    float.fromhex(self.adj["core_limits"][key]),
                    f"{fam}: report limit hex != frozen limit hex")

    def test_displayed_decimals_derive_from_hex(self):
        for fam, groups in self.rows.items():
            with self.subTest(family=fam):
                obs_hex, obs_dec = groups[1], groups[2]
                lim_hex, lim_dec = groups[3], groups[4]
                self.assertEqual(
                    float(obs_dec), float.fromhex(obs_hex),
                    f"{fam}: observed decimal {obs_dec} != float.fromhex({obs_hex})")
                self.assertEqual(
                    float(lim_dec), float.fromhex(lim_hex),
                    f"{fam}: limit decimal {lim_dec} != float.fromhex({lim_hex})")

    def test_displayed_headroom_derives_from_hex(self):
        for fam, groups in self.rows.items():
            with self.subTest(family=fam):
                obs = float.fromhex(groups[1])
                lim = float.fromhex(groups[3])
                headroom = (lim - obs) / lim
                shown = float(groups[5])
                self.assertAlmostEqual(
                    shown, round(headroom * 100, 2), places=6,
                    msg=f"{fam}: shown headroom {shown}% != derived "
                        f"{headroom * 100:.2f}%")

    def test_specific_corrected_values(self):
        """Pin the exact values the maintainer correction established."""
        self.assertEqual(float.fromhex("0x1.b48p+3"), 13.640625)
        self.assertEqual(float.fromhex("0x1.d2p+4"), 29.125)
        self.assertEqual(
            float.fromhex("0x1.44dcfa4242a7ap+1"), 2.537993700364777)
        self.assertEqual(
            float.fromhex("0x1.7790ef6766a33p+3"), 11.736442281680047)
        self.assertEqual(float.fromhex("0x1.49p+3"), 10.28125)
        self.assertAlmostEqual(
            (float.fromhex("0x1.d2p+4") - float.fromhex("0x1.b48p+3"))
            / float.fromhex("0x1.d2p+4") * 100, 53.17, places=2)
        self.assertAlmostEqual(
            (float.fromhex("0x1.7790ef6766a33p+3")
             - float.fromhex("0x1.44dcfa4242a7ap+1"))
            / float.fromhex("0x1.7790ef6766a33p+3") * 100, 78.38, places=2)
        self.assertAlmostEqual(
            (float.fromhex("0x1.d2p+4") - float.fromhex("0x1.49p+3"))
            / float.fromhex("0x1.d2p+4") * 100, 64.70, places=2)

    def test_adjudication_artifact_unchanged_identity(self):
        """The authoritative artifact identity is the campaign-terminal one."""
        import hashlib
        self.assertEqual(
            hashlib.sha256(ADJ.read_bytes()).hexdigest(),
            "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70")


if __name__ == "__main__":
    unittest.main()
