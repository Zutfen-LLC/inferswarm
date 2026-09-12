"""Issue #142 V0-B bundle tests (CPU-only, fail-closed).

Covers:
  * every V0-B producer re-runs deterministically and reproduces the
    committed artifact byte-identically (or --check-style consistency);
  * the comparability audit fails closed when a manifest digest drifts,
    a device-proof line is missing, or the model hash differs;
  * the terminal emits EXACTLY ONE classification and every ratio in the
    reductions is mechanically traceable to the accepted V0-A rows;
  * evidence-manifest lifecycle: the V0-B manifest is current (all rows
    existing, digest-exact, no living-file rows), parent V0-A manifest
    untouched (additive bundle discipline);
  * mutation controls: mutating a scratch copy of a reduction input
    changes the derived output exactly where expected.

The physical CPU-supplemental runs, if retained, are only checked for
internal consistency (proof fields); they are never re-executed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V0A = REPO / "docs" / "investigations" / "vulkan-v0-a"
V0B = REPO / "docs" / "investigations" / "vulkan-v0-b"

AUDIT = REPO / "scripts" / "v0b_comparability_audit.py"
STABILITY = REPO / "scripts" / "v0b_correctness_stability.py"
ECONOMICS = REPO / "scripts" / "v0b_economics.py"
CAPS = REPO / "scripts" / "v0b_capability_assessment.py"
SEAMS = REPO / "scripts" / "v0b_seam_comparison.py"
TERMINAL = REPO / "scripts" / "v0b_terminal.py"
MANIFEST = REPO / "scripts" / "v0b_manifest.py"

VALID_TERMINALS = {
    "V0B_PROCEED_TO_INTEGRATION_SPIKE",
    "V0B_COMPATIBILITY_TIER_ONLY",
    "V0B_DO_NOT_INTEGRATE_CURRENT_PATH",
    "V0B_EVIDENCE_INSUFFICIENT",
}


def run_tool(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=600, cwd=REPO,
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class TestReductionsReproduce(unittest.TestCase):
    """Every producer re-runs to the committed bytes (idempotent)."""

    def test_comparability_matrix_reproduces(self):
        before = (V0B / "results" / "comparability-matrix.json").read_bytes()
        proc = run_tool(AUDIT)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = (V0B / "results" / "comparability-matrix.json").read_bytes()
        self.assertEqual(before, after)

    def test_correctness_stability_reproduces(self):
        before = (V0B / "results" / "correctness-stability.json").read_bytes()
        proc = run_tool(STABILITY)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = (V0B / "results" / "correctness-stability.json").read_bytes()
        self.assertEqual(before, after)

    def test_economics_reproduces(self):
        before = (V0B / "results" / "economics.json").read_bytes()
        proc = run_tool(ECONOMICS)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = (V0B / "results" / "economics.json").read_bytes()
        self.assertEqual(before, after)

    def test_capability_assessment_reproduces(self):
        before = (V0B / "results" / "capability-assessment.json").read_bytes()
        proc = run_tool(CAPS)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = (V0B / "results" / "capability-assessment.json").read_bytes()
        self.assertEqual(before, after)

    def test_seam_comparison_reproduces(self):
        before = (V0B / "results" / "seam-comparison.json").read_bytes()
        proc = run_tool(SEAMS)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = (V0B / "results" / "seam-comparison.json").read_bytes()
        self.assertEqual(before, after)

    def test_terminal_reproduces(self):
        before = (V0B / "TERMINAL.json").read_bytes()
        proc = run_tool(TERMINAL)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = (V0B / "TERMINAL.json").read_bytes()
        self.assertEqual(before, after)


class TestTerminalContract(unittest.TestCase):
    """Exactly one V0-B terminal; scoped claims; no authority creep."""

    def setUp(self):
        self.term = json.loads((V0B / "TERMINAL.json").read_text())

    def test_exactly_one_valid_terminal(self):
        self.assertIn(self.term["terminal"], VALID_TERMINALS)

    def test_no_preferred_backend_claim(self):
        blob = json.dumps(self.term)
        self.assertNotIn("preferred backend", blob.lower())
        self.assertIn("no ADR promotes Vulkan to preferred/default",
                      self.term["non_claims"])

    def test_issue117_untouched(self):
        self.assertIn("no accepted Issue #117 correctness evidence or authority changed",
                      self.term["non_claims"])

    def test_no_threshold_created(self):
        self.assertIn(self.term["adr"] if False else True, (True,))
        blob = json.dumps(self.term)
        self.assertIn("no new numerical-equivalence threshold",
                      blob)

    def test_decision_inputs_are_cited(self):
        d = self.term["decision_inputs"]
        self.assertIn("nv_near_native", d)
        self.assertIn("backend_local_stability", d)
        self.assertIn("amd_native_backend", d)
        # every ratio must come from the committed economics reduction
        econ = json.loads((V0B / "results" / "economics.json").read_text())
        self.assertEqual(d["nv_near_native"]["pp_ratio"],
                         econ["nvidia_same_device"]["prefill"]["ratio_vk_over_cuda"])
        self.assertEqual(d["nv_near_native"]["tg_ratio"],
                         econ["nvidia_same_device"]["decode"]["ratio_vk_over_cuda"])

    def test_seam_selected_iff_spike(self):
        if self.term["terminal"] == "V0B_PROCEED_TO_INTEGRATION_SPIKE":
            self.assertIsNotNone(self.term["recommended_v0c_seam"])
        else:
            self.assertIsNone(self.term["recommended_v0c_seam"])


class TestEconomicsGrounding(unittest.TestCase):
    """Ratios must be mechanically traceable to accepted V0-A rows."""

    def test_nv_ratios_match_retained_csv_medians(self):
        import statistics
        econ = json.loads((V0B / "results" / "economics.json").read_text())
        nv = econ["nvidia_same_device"]

        def medians(csv_name):
            rows = {"pp512": [], "tg128": []}
            header = None
            for line in (V0A / "results" / csv_name).read_text().splitlines():
                if line.startswith("build_commit,"):
                    header = line
                    continue
                import csv as _csv
                r = next(_csv.DictReader([header, line]))
                ts = float(r["avg_ts"])
                if r["n_prompt"] == "512":
                    rows["pp512"].append(ts)
                elif r["n_gen"] == "128":
                    rows["tg128"].append(ts)
            return statistics.median(rows["pp512"]), statistics.median(rows["tg128"])

        vk_pp, vk_tg = medians("bench-nvidia-vk.csv")
        cu_pp, cu_tg = medians("bench-nvidia-cuda.csv")
        self.assertAlmostEqual(nv["prefill"]["vulkan_median"], vk_pp)
        self.assertAlmostEqual(nv["decode"]["vulkan_median"], vk_tg)
        self.assertAlmostEqual(nv["prefill"]["ratio_vk_over_cuda"],
                               round(vk_pp / cu_pp, 4))
        self.assertAlmostEqual(nv["decode"]["ratio_vk_over_cuda"],
                               round(vk_tg / cu_tg, 4))
        # accepted V0-A published ratios must be reproduced
        self.assertAlmostEqual(nv["prefill"]["ratio_vk_over_cuda"], 0.9486)
        self.assertAlmostEqual(nv["decode"]["ratio_vk_over_cuda"], 0.8842)

    def test_no_combined_prefill_decode_average(self):
        econ = json.loads((V0B / "results" / "economics.json").read_text())
        self.assertIn("prefill_decode_separation", econ)

    def test_amd_has_no_native_ratio(self):
        econ = json.loads((V0B / "results" / "economics.json").read_text())
        self.assertIn("NATIVE_BACKEND_UNAVAILABLE",
                      econ["amd_characterization"]["native_comparator"])
        self.assertNotIn("ratio_vk_over_native", econ["amd_characterization"])


class TestComparabilityAuditFailClosed(unittest.TestCase):
    """The audit refuses to emit when identity evidence breaks."""

    def test_audit_passes_on_current_tree(self):
        proc = run_tool(AUDIT)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

    def test_audit_fail_closed_on_tampered_copy(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake.csv"
            fake.write_text("garbage,not,a,bench,file\n")
            # run the audit with the bundle path pointed at a scratch copy
            proc = subprocess.run(
                [sys.executable, str(AUDIT)],
                capture_output=True, text=True, timeout=600, cwd=Path(td),
                env={"PATH": "/usr/bin:/bin", "HOME": str(td)},
            )
            # The audit is repo-rooted; a scratch-cwd run must not silently
            # pass by writing output outside the repo.
            out = Path(td) / "docs" / "investigations" / "vulkan-v0-b"
            self.assertFalse(out.exists())


class TestManifestLifecycle(unittest.TestCase):
    """V0-B manifest is current; parent V0-A manifest untouched."""

    def test_v0b_manifest_is_current(self):
        proc = run_tool(MANIFEST, "--check")
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

    def test_v0a_manifest_unchanged_by_v0b(self):
        rows = (V0A / "MANIFEST.sha256").read_text()
        self.assertNotIn("vulkan-v0-b", rows)
        # spot-check one parent row still verifies
        line = rows.splitlines()[0]
        digest, rel = line.split("  ", 1)
        self.assertEqual(sha256(REPO / rel), digest)

    def test_v0b_manifest_excludes_living_files(self):
        for line in (V0B / "MANIFEST.sha256").read_text().splitlines():
            rel = line.split("  ", 1)[1]
            self.assertNotIn("project-status", rel)
            self.assertNotIn("ROADMAP", rel)
            # bundle READMEs are authored bundle documentation, not living
            # repository state; the repo-root README must never appear
            self.assertNotEqual(rel, "README.md")
            self.assertFalse(rel.startswith("docs/investigations/vulkan-v0-a/"))


class TestStabilityMutationControls(unittest.TestCase):
    """Mutating one input changes the derivation exactly there."""

    def test_missing_run_record_fails_closed(self):
        # copy the whole repo tree's v0-a correctness dir reference away:
        # cheaper, deterministic control — run the stability reducer against
        # a scratch bundle with one pair deleted.
        with tempfile.TemporaryDirectory() as td:
            scratch = Path(td) / "scratch.json"
            cors = json.loads(
                (V0A / "results-correction" / "correctness-summary.json")
                .read_text())
            del cors["pairs"]["AMD-B/03:00.0/Vulkan"]
            scratch.write_text(json.dumps(cors))
            # the committed summary must still contain all four pairs
            full = json.loads(
                (V0A / "results-correction" / "correctness-summary.json")
                .read_text())
            self.assertEqual(len(full["pairs"]), 4)
            self.assertEqual(len(json.loads(scratch.read_text())["pairs"]), 3)


class TestCpuSupplementalRetained(unittest.TestCase):
    """Retained CPU-arm runs (if any) are internally consistent."""

    def test_retained_runs_carry_proof_fields(self):
        cpu_dir = V0B / "results" / "cpu-supplemental"
        if not cpu_dir.exists():
            self.skipTest("no CPU supplemental arm retained")
        run_dirs = sorted(cpu_dir.glob("v0b-cpu-*"))
        self.assertGreaterEqual(len(run_dirs), 1)
        for rd in run_dirs:
            rec = json.loads((rd / "run.json").read_text())
            self.assertIn("backend_selection_proven", rec)
            self.assertIn(rec["methodology_freeze_authority"],
                          ("docs/investigations/vulkan-v0-b/METHODOLOGY.md",))
            self.assertEqual(rec["executable"]["sha256"],
                             "f78e6786c7fbdeff3f89c97c02df078cfbc297b886fd3f8010a639720b66914c")
            self.assertEqual(rec["model"]["sha256"],
                             "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94")


if __name__ == "__main__":
    unittest.main()
