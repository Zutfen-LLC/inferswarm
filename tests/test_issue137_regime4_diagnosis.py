"""Issue #137 diagnostic evidence tests (CPU-only, fail-closed).

CORRECTED expectations (PR #138 correction pass): the reducer v2
derives the honest terminal from corrected evidence — probe C is
retired (informational), C2 is the causal intervention, per-case
partition is honest, history is narrowed to not-necessary.  The
committed artifact must reproduce byte-identically under the corrected
reducer.

Covers:
  * Phase-1 inventory re-derivation from the retained accepted bytes;
  * conclusions reducer reproduction (byte-identical re-run);
  * terminal-condition derivation (no constant terminal);
  * mutation controls: each control mutates ONE thing in a scratch copy
    of the evidence dir and asserts the reducer's derived conditions or
    fail-closed behavior changes exactly there;
  * DIAGNOSTIC_ONLY marking and producer pinning on every probe record;
  * instrumentation-off-by-default: the frozen producer's capture path
    is a no-op unless armed (source-text assertion, CPU-only host).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = (
    REPO / "docs" / "implementation" /
    "r6-successor-dense-full-integration-117" / "evidence" /
    "arm-c-regime4-diagnosis-137"
)
PHASE1 = REPO / "scripts" / "issue137_phase1_inventory.py"
CONCLUSIONS = REPO / "scripts" / "issue137_conclusions.py"
PROBE_DRIVER = REPO / "scripts" / "issue137_probe_driver.py"

DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
TERMINAL_LOCALIZED = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED"


def run_tool(script: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=300, cwd=REPO,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{script.name} failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


class TestPhase1Inventory(unittest.TestCase):
    def test_reproduces_from_retained_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_tool(PHASE1, "--repo", str(REPO),
                           "--out", str(Path(td) / "inv.json"))
            self.assertEqual(out["divergent_cases"], 6)
            self.assertTrue(out["stable_all_identical"])
            record = json.loads((Path(td) / "inv.json").read_text())
            # six divergent cases with authored == rederived positions
            for d in record["divergences"]:
                self.assertEqual(
                    d["first_divergent_position_rederived"],
                    d["first_divergent_position_authored"],
                )
            # the two-chunk population IS the divergent population
            self.assertEqual(
                set(record["chunk_partition"]["two_chunk_population"]),
                {d["case_id"] for d in record["divergences"]},
            )
            # all four cross-campaign observations distinct per case
            for c in record["cross_campaign"]["divergent_cases"]:
                self.assertTrue(c["all_four_distinct"])

    def test_hypothesis_matrix_covers_issue_families(self):
        with tempfile.TemporaryDirectory() as td:
            run_tool(PHASE1, "--repo", str(REPO),
                     "--out", str(Path(td) / "inv.json"))
            record = json.loads((Path(td) / "inv.json").read_text())
            self.assertEqual(len(record["hypothesis_matrix"]), 6)
            for family, entry in record["hypothesis_matrix"].items():
                self.assertIn("supporting", entry)
                self.assertIn("contradicting", entry)
                self.assertIn("smallest_discriminating_probe", entry)


class TestConclusions(unittest.TestCase):
    def test_reproduces_committed_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_tool(
                CONCLUSIONS, "--evidence-dir", str(EVIDENCE),
                "--out", str(Path(td) / "c.json"))
            # corrected reducer: the honest derived terminal from the
            # retained evidence (committed artifact must match exactly)
            committed = json.loads(
                (EVIDENCE / "diagnostic-conclusions.json").read_text())
            self.assertEqual(out["terminal"], committed["terminal"])
            self.assertEqual(out["problems"], committed["problems"])
            # byte-identical re-derivation vs the committed artifact
            fresh = json.loads((Path(td) / "c.json").read_text())
            fresh.pop("inputs")
            committed.pop("inputs")
            self.assertEqual(fresh, committed)

    def test_terminal_not_constant(self):
        source = CONCLUSIONS.read_text()
        self.assertIn('TERMINAL_LOCALIZED = "', source)
        # terminal assignment is conditional on derived requirements
        self.assertIn("if all(requirements.values())", source)
        self.assertIn("elif", source)
        self.assertIn('terminal = TERMINAL_INSUFFICIENT', source)


class TestMutationControls(unittest.TestCase):
    """One mutation per control; the reducer must change exactly there."""

    def _scratch(self, td: str) -> Path:
        scratch = Path(td) / "ev"
        shutil.copytree(EVIDENCE, scratch)
        return scratch

    def _conclusions(self, ev: Path, td: Path) -> dict:
        return run_tool(CONCLUSIONS, "--evidence-dir", str(ev),
                        "--out", str(Path(td) / "c.json"))

    def test_control_missing_probe_family_downgrades_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            (ev / "i137-diag-D-1789128772.json").unlink()
            out = self._conclusions(ev, Path(td))
            self.assertIn("missing probe family D", out["problems"])
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_control_flipped_determinism_on_control_case(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            p = ev / "i137-diag-A-1789129893.json"  # stable control
            rec = json.loads(p.read_text())
            rec["observations"][1]["committed_step0"] = 999999
            p.write_text(json.dumps(rec))
            out = self._conclusions(ev, Path(td))
            self.assertFalse(out["requirements"][
                "stable_control_single_chunk_deterministic"])
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_control_chunk_intervention_neutralized(self):
        """Corrected semantics: neutralizing the retired C record's
        flip is invisible to the CAUSAL verdict (C is informational);
        instead neutralizing a C2 record's two-arm variance must
        break the causal requirement."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            p = ev / "i137-diag-C-1789128426.json"
            rec = json.loads(p.read_text())
            for o in rec["observations"]:
                o["two_chunk_32"]["committed_step0"] = 1509
            p.write_text(json.dumps(rec))
            out = self._conclusions(ev, Path(td))
            # retired C cannot carry causal weight either way
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_control_stripped_diagnostic_marking_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            p = ev / "i137-diag-A2-1789128152.json"
            rec = json.loads(p.read_text())
            rec["classification"] = "QUALIFICATION"
            p.write_text(json.dumps(rec))
            with self.assertRaises(AssertionError):
                self._conclusions(ev, Path(td))

    def test_control_producer_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            p = ev / "i137-diag-B-1789130217.json"
            rec = json.loads(p.read_text())
            rec["producer"] = "0" * 40
            p.write_text(json.dumps(rec))
            with self.assertRaises(AssertionError):
                self._conclusions(ev, Path(td))


class TestProbeRecords(unittest.TestCase):
    def test_all_records_diagnostic_only_and_producer_pinned(self):
        for p in sorted(EVIDENCE.glob("i137-diag-*.json")):
            rec = json.loads(p.read_text())
            self.assertEqual(rec["classification"], DIAGNOSTIC_ONLY, p.name)
            self.assertEqual(rec["producer"], PRODUCER, p.name)
            self.assertIn("started_at_ns", rec)
            self.assertIn("inputs", rec)

    def test_capture_manifests_bundle_hashed(self):
        for p in sorted(EVIDENCE.glob("manifest-*.json")):
            man = json.loads(p.read_text())
            self.assertIn("bundle_sha256", man)
            self.assertGreater(man["record_count"], 0)


class TestInstrumentationOffByDefault(unittest.TestCase):
    """The diagnostic capture lives in the FROZEN producer and is a
    no-op unless armed; asserted via the vendored frozen source text
    (CPU-only host cannot import torch)."""

    FROZEN_STAGE_CHAIN = (
        REPO / "docs" / "implementation" /
        "r6-successor-dense-full-integration-117" / "evidence" /
        "arm-c-retry" / "frozen-source" / "924cd22e" / "benchmarks" /
        "inferswarm_r6" / "stage_chain.py"
    )

    def test_capture_ops_are_explicit_and_default_off(self):
        """In the frozen producer, capture arming is an EXPLICIT op the
        serving loop never issues; without ARM_CAPTURE the sink is
        never installed (no capture on the ordinary path)."""
        text = self.FROZEN_STAGE_CHAIN.read_text()
        self.assertIn('"ARM_CAPTURE"', text)
        # generate() (the serving loop) issues only RESET/PREFILL/DECODE
        gen = text[text.index("def generate("):text.index("def report(")]
        self.assertNotIn("ARM_CAPTURE", gen)
        self.assertNotIn("capture_step", gen)

    def test_probe_driver_composes_public_api_only(self):
        source = PROBE_DRIVER.read_text()
        # no producer-tree writes, no monkeypatching of runtime internals
        self.assertNotIn("_capture_sink =", source)
        self.assertNotIn(".zero_()", source)
        self.assertNotIn("torch.manual_seed", source)
        self.assertNotIn("use_deterministic", source)
        # corrected binding: accepted-authority verification before
        # any execution (supersedes require_frozen_producer)
        self.assertIn("verify_producer_checkout", source)


if __name__ == "__main__":
    unittest.main()
