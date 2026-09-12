"""Issue #142 V0-B bundle tests (CPU-only, fail-closed).

Covers:
  * every V0-B producer re-runs deterministically and reproduces the
    committed artifact byte-identically;
  * the comparability audit fails closed when a retained evidence byte
    is tampered with (manifest digest drift) — verified against the
    production audit on a mutated scratch copy of the repo tree;
  * the corrected Phase-1 repeatability taxonomy: a one-run, one-output
    pair is `insufficiently_observed`, never `stable`; a genuine 3-run
    identical pair is `stable`; a missing pair fails the reducer;
  * the CPU-supplemental proof: re-derived from RAW retained stderr per
    run (never trusted from a boolean), the retained
    `llama_prepare_model_devices: using device Vulkan0` line has an
    explicit disposition, and a run.json claiming proof while its
    stderr violates the rule is rejected by the production deriver;
  * the terminal's mechanical, fail-closed input validation: mutating
    or removing the S2 seam, marking classes_all_considered=false, or
    removing a required capability fact each prevents the unchanged
    PROCEED + S2 terminal — every mutation is executed through the
    production `v0b_terminal.py` on a scratch input tree;
  * evidence-manifest lifecycle: the V0-B manifest is current (all rows
    existing, digest-exact, no living-file rows), parent V0-A manifest
    untouched (additive bundle discipline);
  * the terminal carries no new numerical-equivalence threshold in its
    semantics (checked against its actual selection behavior, not by
    string existence alone).

The physical CPU-supplemental runs are only checked for internal
consistency and proof re-derivation; they are never re-executed.
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
CPU_DERIVE = REPO / "scripts" / "v0b_cpu_supplement_derive.py"
CPU_PROOF = REPO / "scripts" / "v0b_cpu_proof.py"

VALID_TERMINALS = {
    "V0B_PROCEED_TO_INTEGRATION_SPIKE",
    "V0B_COMPATIBILITY_TIER_ONLY",
    "V0B_DO_NOT_INTEGRATE_CURRENT_PATH",
    "V0B_EVIDENCE_INSUFFICIENT",
}

SPIKE = "V0B_PROCEED_TO_INTEGRATION_SPIKE"


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


def make_scratch_tree(td: Path) -> Path:
    """Copy the repo tree (minus .git) into td/scratch for mutation tests.

    Needed because the producers resolve the repo from their own path;
    the production scripts are copied into the scratch tree so the
    PRODUCTION reducer executes against mutated inputs.
    """
    scratch = td / "scratch"
    scratch.mkdir()
    for item in REPO.iterdir():
        if item.name in (".git", "__pycache__"):
            continue
        dest = scratch / item.name
        if item.is_dir():
            shutil.copytree(item, dest, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(item, dest)
    return scratch


class TestReductionsReproduce(unittest.TestCase):
    """Every producer re-runs to the committed bytes (idempotent)."""

    def _reproduces(self, script: Path, rel: Path):
        before = rel.read_bytes()
        proc = run_tool(script)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        after = rel.read_bytes()
        self.assertEqual(before, after)

    def test_comparability_matrix_reproduces(self):
        self._reproduces(AUDIT, V0B / "results" / "comparability-matrix.json")

    def test_correctness_stability_reproduces(self):
        self._reproduces(STABILITY, V0B / "results" / "correctness-stability.json")

    def test_economics_reproduces(self):
        self._reproduces(ECONOMICS, V0B / "results" / "economics.json")

    def test_capability_assessment_reproduces(self):
        self._reproduces(CAPS, V0B / "results" / "capability-assessment.json")

    def test_seam_comparison_reproduces(self):
        self._reproduces(SEAMS, V0B / "results" / "seam-comparison.json")

    def test_terminal_reproduces(self):
        self._reproduces(TERMINAL, V0B / "TERMINAL.json")

    def test_cpu_summary_reproduces(self):
        self._reproduces(CPU_DERIVE,
                         V0B / "results" / "cpu-supplemental" / "summary.json")


class TestRepeatabilityClassification(unittest.TestCase):
    """The corrected Phase-1 taxonomy, executed through the producer."""

    def _classify(self, mutated_summary: dict):
        """Run the PRODUCTION stability reducer against mutated V0-A input."""
        with tempfile.TemporaryDirectory() as td:
            scratch = make_scratch_tree(Path(td))
            src = V0A / "results-correction" / "correctness-summary.json"
            (scratch / "docs/investigations/vulkan-v0-a/results-correction"
             / "correctness-summary.json").write_text(json.dumps(mutated_summary))
            proc = subprocess.run(
                [sys.executable, str(scratch / "scripts/v0b_correctness_stability.py")],
                capture_output=True, text=True, timeout=600, cwd=scratch)
            out = (scratch / "docs/investigations/vulkan-v0-b/results"
                   / "correctness-stability.json")
            return proc, (json.loads(out.read_text()) if out.exists() else None)

    def test_one_run_one_output_is_insufficiently_observed(self):
        cors = json.loads((V0A / "results-correction" / "correctness-summary.json")
                          .read_text())
        proc, out = self._classify(cors)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        for name in ("AMD-B/03:00.0/Vulkan", "NV-A/04:00.0/Vulkan",
                     "NV-A/04:00.0/CUDA"):
            self.assertEqual(
                out["per_pair"][name]["backend_local_repeatability"],
                "insufficiently_observed",
                f"{name}: a one-run pair must never classify as stable")

    def test_repeated_identical_pair_is_stable(self):
        cors = json.loads((V0A / "results-correction" / "correctness-summary.json")
                          .read_text())
        proc, out = self._classify(cors)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        amd = out["per_pair"]["AMD-A/02:00.0/Vulkan"]
        self.assertEqual(amd["runs"], 3)
        self.assertEqual(amd["unique_visible_generations"], 1)
        self.assertEqual(amd["backend_local_repeatability"], "stable")

    def test_repeated_conflicting_pair_is_output_unstable(self):
        cors = json.loads((V0A / "results-correction" / "correctness-summary.json")
                          .read_text())
        gen = cors["pairs"]["AMD-A/02:00.0/Vulkan"]["canonical_generations"]
        cors["pairs"]["AMD-A/02:00.0/Vulkan"]["canonical_generations"] = [
            gen[0], gen[0] + " x", gen[0] + " y"]
        cors["pairs"]["AMD-A/02:00.0/Vulkan"]["unique_canonical_outputs"] = 3
        proc, out = self._classify(cors)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertEqual(
            out["per_pair"]["AMD-A/02:00.0/Vulkan"]["backend_local_repeatability"],
            "output_unstable")

    def test_missing_pair_fails_reducer_nonzero(self):
        cors = json.loads((V0A / "results-correction" / "correctness-summary.json")
                          .read_text())
        del cors["pairs"]["AMD-B/03:00.0/Vulkan"]
        proc, out = self._classify(cors)
        self.assertNotEqual(proc.returncode, 0,
                            "a missing correctness pair must fail the reducer")
        self.assertIn("AMD-B", proc.stdout + proc.stderr)

    def test_committed_artifact_agrees_with_itself(self):
        out = json.loads((V0B / "results" / "correctness-stability.json")
                         .read_text())
        summary = out["classification_summary"]
        for name, p in out["per_pair"].items():
            cls = p["backend_local_repeatability"]
            key = {"AMD-A/02:00.0/Vulkan": "amd_a_vulkan",
                   "AMD-B/03:00.0/Vulkan": "amd_b_vulkan",
                   "NV-A/04:00.0/Vulkan": "nvidia_vulkan",
                   "NV-A/04:00.0/CUDA": "nvidia_cuda"}[name]
            if cls == "insufficiently_observed":
                self.assertIn("insufficiently_observed", summary[key])
            elif cls == "stable":
                self.assertIn("stable", summary[key])


class TestTerminalFailClosed(unittest.TestCase):
    """Mutations must move the PRODUCTION terminal off PROCEED + S2."""

    def _run_terminal_on_scratch(self, scratch: Path):
        return subprocess.run(
            [sys.executable, str(scratch / "scripts/v0b_terminal.py")],
            capture_output=True, text=True, timeout=600, cwd=scratch)

    def _mutated_terminal(self, mutate):
        with tempfile.TemporaryDirectory() as td:
            scratch = make_scratch_tree(Path(td))
            mutate(scratch)
            proc = self._run_terminal_on_scratch(scratch)
            out = scratch / "docs/investigations/vulkan-v0-b/TERMINAL.json"
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            term = json.loads(out.read_text())
            return proc, term

    def _seams(self, scratch: Path) -> dict:
        return (scratch / "docs/investigations/vulkan-v0-b/results"
                / "seam-comparison.json")

    def test_baseline_is_spike_with_s2(self):
        term = json.loads((V0B / "TERMINAL.json").read_text())
        self.assertEqual(term["terminal"], SPIKE)
        self.assertEqual(term["recommended_v0c_seam"],
                         "S2-backend-adapter-participant")

    def test_removing_s2_seam_prevents_spike(self):
        def mutate(scratch):
            data = json.loads(self._seams(scratch).read_text())
            data["seams"] = [s for s in data["seams"]
                             if s["id"] != "S2-backend-adapter-participant"]
            self._seams(scratch).write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)
        self.assertIsNone(term["recommended_v0c_seam"])

    def test_mutating_s2_properties_prevents_spike(self):
        def mutate(scratch):
            data = json.loads(self._seams(scratch).read_text())
            for s in data["seams"]:
                if s["id"] == "S2-backend-adapter-participant":
                    s["planner_leak"] = "HIGH — vendor nouns leak into the planner"
                    s["coexistence"] = "unknown"
            self._seams(scratch).write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)
        self.assertIsNone(term["recommended_v0c_seam"])

    def test_s2_freezing_public_api_prevents_spike(self):
        def mutate(scratch):
            data = json.loads(self._seams(scratch).read_text())
            for s in data["seams"]:
                if s["id"] == "S2-backend-adapter-participant":
                    s["v0c_could_prove"] = (
                        "that a Vulkan-backed Compute Unit can join one Swarm "
                        "while freezing the public adapter API surface")
                    s["v0c_bounds"]["no_public_api_freeze"] = False
            self._seams(scratch).write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)

    def test_classes_not_all_considered_prevents_spike(self):
        def mutate(scratch):
            data = json.loads(self._seams(scratch).read_text())
            data["classes_all_considered"] = False
            self._seams(scratch).write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)
        self.assertIsNone(term["recommended_v0c_seam"])

    def test_removing_required_capability_fact_prevents_spike(self):
        def mutate(scratch):
            p = (scratch / "docs/investigations/vulkan-v0-b/results"
                 / "capability-assessment.json")
            data = json.loads(p.read_text())
            del (data["per_backend"]["amd_a_polaris_vulkan"]["findings"]
                 ["model_state_materialization_on_accelerator"])
            p.write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)
        self.assertIsNone(term["recommended_v0c_seam"])

    def test_missing_economics_cpu_arm_does_not_control_spike(self):
        def mutate(scratch):
            p = (scratch / "docs/investigations/vulkan-v0-b/results"
                 / "economics.json")
            data = json.loads(p.read_text())
            data["host_execution_comparison"] = None
            p.write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertEqual(term["terminal"], SPIKE)
        self.assertEqual(term["recommended_v0c_seam"],
                         "S2-backend-adapter-participant")

    def test_correctness_qualification_mutations_prevent_spike(self):
        """The terminal must validate the upstream qualification posture,
        not merely repeat non-claims in TERMINAL.json."""
        mutations = {
            "missing ADR-0010 mapping": lambda d: d.pop("adr_0010_mapping"),
            "new threshold": lambda d: d["adr_0010_mapping"].__setitem__(
                "new_threshold_created", True),
            "layer 2 upgraded": lambda d: d["adr_0010_mapping"].__setitem__(
                "layer_2_qualified_numerical_equivalence", "ESTABLISHED"),
            "layer 3 upgraded": lambda d: d["adr_0010_mapping"].__setitem__(
                "layer_3_strategy_declared_semantic_correctness", "ESTABLISHED"),
            "generated-output difference relabeled": lambda d: d["cross_backend"].__setitem__(
                "classification_per_issue_phase_1", "exact agreement"),
            "prospective requirements removed": lambda d: d.__setitem__(
                "a_future_qualification_campaign_would_need_to_freeze_prospectively", []),
        }
        for label, mutate_data in mutations.items():
            with self.subTest(label=label):
                def mutate(scratch):
                    p = (scratch / "docs/investigations/vulkan-v0-b/results"
                         / "correctness-stability.json")
                    data = json.loads(p.read_text())
                    mutate_data(data)
                    p.write_text(json.dumps(data))
                _, term = self._mutated_terminal(mutate)
                self.assertNotEqual(term["terminal"], SPIKE)
                self.assertIsNone(term["recommended_v0c_seam"])

    def test_s2_cuda_without_hip_prevents_spike(self):
        def mutate(scratch):
            data = json.loads(self._seams(scratch).read_text())
            for seam in data["seams"]:
                if seam["id"] == "S2-backend-adapter-participant":
                    seam["coexistence"] = "CUDA adapters are peers under one resource graph"
                    seam["v0c_bounds"]["coexisting_resources"] = ["CUDA"]
            self._seams(scratch).write_text(json.dumps(data))
        _, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)
        self.assertIsNone(term["recommended_v0c_seam"])

    def test_stability_contradiction_prevents_spike(self):
        def mutate(scratch):
            p = (scratch / "docs/investigations/vulkan-v0-b/results"
                 / "correctness-stability.json")
            data = json.loads(p.read_text())
            data["per_pair"]["AMD-B/03:00.0/Vulkan"][
                "backend_local_repeatability"] = "stable"  # 1 run!
            p.write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)

    def test_integrity_failure_prevents_spike(self):
        def mutate(scratch):
            p = (scratch / "docs/investigations/vulkan-v0-b/results"
                 / "correctness-stability.json")
            data = json.loads(p.read_text())
            data["per_pair"]["NV-A/04:00.0/CUDA"]["integrity"] = (
                "FAIL — fallback marker in retained stderr")
            p.write_text(json.dumps(data))
        proc, term = self._mutated_terminal(mutate)
        self.assertNotEqual(term["terminal"], SPIKE)


class TestTerminalSemantics(unittest.TestCase):
    """Exactly one V0-B terminal; scoped claims; threshold semantics."""

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

    def test_no_preregistration_claim_for_heuristics(self):
        """The false 'pre-registered usefulness bar' claim is gone and the
        non-preregistration of the descriptive heuristics is asserted."""
        blob = json.dumps(self.term).lower()
        # the false claim itself must not survive as an assertion anywhere
        # outside the withdrawn-claim mention in the descriptive note
        self.assertNotIn("pre-registered usefulness bar", blob.replace(
            "the prior '2x pre-registered usefulness bar' claim was false "
            "and is withdrawn", ""))
        self.assertNotIn("bar_declared", blob)
        self.assertIn(
            "no performance threshold used here was preregistered",
            blob)
        desc = self.term["decision_inputs"][
            "descriptive_similarity_summaries"]
        self.assertFalse(desc["authoritative"])
        self.assertIn("2.0",
                      json.dumps(desc["amd_vk_over_host_execution"][
                          "reference_heuristic_declared_nonauthoritative"]))

    def test_no_numerical_threshold_in_semantics(self):
        """The terminal's selection must not depend on any numeric gate:
        the only authoritative decision inputs are class-valued or
        proof-valued, and thresholds appear only inside clearly marked
        non-authoritative descriptive blocks."""
        d = self.term["decision_inputs"]
        self.assertTrue(d["backend_local_stability"]["authoritative"])
        self.assertFalse(d["cpu_arm_context"]["authoritative"])
        self.assertFalse(
            d["descriptive_similarity_summaries"]["authoritative"])
        # no numeric acceptance gates anywhere in the terminal
        for key in ("pp_clears_bar", "decode_clears_bar", "value"):
            self.assertNotIn(key, json.dumps(d["backend_local_stability"]))
        self.assertNotIn(
            "near_native_nv", d,
            "the nv near-native heuristic must not be a decision input")

    def test_seam_selected_iff_spike(self):
        if self.term["terminal"] == SPIKE:
            self.assertIsNotNone(self.term["recommended_v0c_seam"])
        else:
            self.assertIsNone(self.term["recommended_v0c_seam"])

    def test_cpu_arm_non_claims_present(self):
        blob = json.dumps(self.term)
        self.assertIn("does not claim 'no GPU participated'", blob)
        self.assertIn("overwritten and are NOT retained", blob)


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

    def test_economics_consumes_corrected_cpu_summary(self):
        econ = json.loads((V0B / "results" / "economics.json").read_text())
        summ = json.loads((V0B / "results" / "cpu-supplemental" / "summary.json")
                          .read_text())
        cpu = econ["host_execution_comparison"]["cpu_arm"]
        self.assertEqual([r["run_id"] for r in cpu["runs"]],
                         [r["run_id"] for r in summ["accepted_runs"]])
        self.assertEqual(cpu["pp512_median_tps"], summ["pp512_median_tps"])


class TestComparabilityAuditFailClosed(unittest.TestCase):
    """The audit refuses to emit when identity evidence breaks."""

    def test_audit_passes_on_current_tree(self):
        proc = run_tool(AUDIT)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

    def test_manifest_tampering_returns_nonzero(self):
        """Tampering with a retained evidence byte must change the byte,
        its manifest digest must then mismatch, and the PRODUCTION audit
        must return nonzero on the mutated tree."""
        with tempfile.TemporaryDirectory() as td:
            scratch = make_scratch_tree(Path(td))
            target = (scratch / "docs/investigations/vulkan-v0-a/results"
                      / "bench-nvidia-vk.csv")
            original = target.read_bytes()
            tampered = original.replace(b"avg_ts", b"avg_TX", 1)
            self.assertNotEqual(original, tampered)
            target.write_bytes(tampered)
            # digest of the retained byte really changed:
            rows = (scratch / "docs/investigations/vulkan-v0-a"
                    / "MANIFEST.sha256").read_text().splitlines()
            row = next(r for r in rows
                       if r.endswith("docs/investigations/vulkan-v0-a/results/bench-nvidia-vk.csv"))
            digest, _ = row.split("  ", 1)
            self.assertNotEqual(digest, sha256(target))
            proc = subprocess.run(
                [sys.executable, str(scratch / "scripts/v0b_comparability_audit.py")],
                capture_output=True, text=True, timeout=600, cwd=scratch)
            self.assertNotEqual(proc.returncode, 0,
                                "comparability audit must fail on tampered evidence")
            output = proc.stdout + proc.stderr
            self.assertTrue(
                "digest drift" in output or "avg_ts" in output,
                f"audit must fail on the tampered manifest/row, got: {output[-400:]}")

    def test_stale_audit_output_missing(self):
        # the audit writes inside its own repo root; a foreign cwd must not
        # leave output behind
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(AUDIT)],
                capture_output=True, text=True, timeout=600, cwd=Path(td),
                env={"PATH": "/usr/bin:/bin", "HOME": str(td)},
            )
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


class TestCpuProofContract(unittest.TestCase):
    """The corrected layers-executed-on-CPU proof contract."""

    CPU = V0B / "results" / "cpu-supplemental"

    def test_retained_runs_carry_identity(self):
        run_dirs = sorted(self.CPU.glob("v0b-cpu-*"))
        self.assertGreaterEqual(len(run_dirs), 3)
        for rd in run_dirs:
            rec = json.loads((rd / "run.json").read_text())
            self.assertIn("backend_selection_proven", rec)
            self.assertEqual(rec["methodology_freeze_authority"],
                             "docs/investigations/vulkan-v0-b/METHODOLOGY.md")
            self.assertEqual(rec["executable"]["sha256"],
                             "f78e6786c7fbdeff3f89c97c02df078cfbc297b886fd3f8010a639720b66914c")
            self.assertEqual(rec["model"]["sha256"],
                             "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94")

    def test_proof_rederives_from_raw_stderr_for_every_run(self):
        proc = run_tool(CPU_DERIVE)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        summ = json.loads((self.CPU / "summary.json").read_text())
        self.assertEqual(summ["n_accepted"], 3)
        self.assertEqual(len(summ["per_run_proof"]), 3)
        for rid, p in summ["per_run_proof"].items():
            self.assertTrue(p["proved"], f"{rid}: proof must re-derive")
            self.assertTrue(p["offload_zero_proven"], rid)
            self.assertTrue(p["layers_all_cpu"], rid)
            self.assertTrue(p["cpu_mapped_model_buffer"], rid)
            self.assertTrue(p["cpu_kv_buffer"], rid)
            self.assertTrue(p["cpu_output_buffer"], rid)
            self.assertTrue(p["matches_collected_verdict"], rid)
            # explicit disposition of the retained using-device-Vulkan0 line
            binds = p["gpu_device_binding_lines"]
            self.assertTrue(binds, f"{rid}: the Vulkan0 device line must be matched")
            for b in binds:
                self.assertEqual(b["disposition"],
                                 "icd_device_enumeration_context_not_prohibitive")
                self.assertEqual(b["device"], "Vulkan0")

    def test_retained_vulkan0_line_has_tested_disposition(self):
        """The exact retained banner must exist in the raw bytes AND be
        matched+dispositioned by the proof module."""
        stderr = (self.CPU / "v0b-cpu-01" / "stderr.txt").read_text()
        self.assertIn(
            "llama_prepare_model_devices: using device Vulkan0",
            stderr,
            "the retained ICD-enumeration line must stay in the evidence")
        sys.path.insert(0, str(REPO / "scripts"))
        import v0b_cpu_proof as cp
        proof = cp.proof_from_stderr(stderr)
        self.assertTrue(proof["proved"])
        self.assertTrue(any(
            b["line"].startswith(
                "llama_prepare_model_devices: using device Vulkan0")
            and b["disposition"] ==
            "icd_device_enumeration_context_not_prohibitive"
            for b in proof["gpu_device_binding_lines"]))

    def test_false_claim_does_not_make_proved_when_stderr_violates(self):
        """A run.json claiming backend_selection_proven=true over stderr
        that violates the rule must NOT survive the proof — the deriver
        re-derives from raw bytes and returns nonzero (never averages)."""
        with tempfile.TemporaryDirectory() as td:
            scratch = make_scratch_tree(Path(td))
            rd = (scratch / "docs/investigations/vulkan-v0-b/results"
                  / "cpu-supplemental/v0b-cpu-02")
            rec = json.loads((rd / "run.json").read_text())
            self.assertTrue(rec["backend_selection_proven"])
            stderr_path = rd / "stderr.txt"
            stderr = stderr_path.read_text()
            # remove the zero-offload line: execution proof broken
            broken = "\n".join(
                ln for ln in stderr.splitlines()
                if "offloaded 0/37 layers to GPU" not in ln) + "\n"
            self.assertNotIn("offloaded 0/37 layers to GPU", broken)
            stderr_path.write_text(broken)
            proc = subprocess.run(
                [sys.executable, str(scratch / "scripts/v0b_cpu_supplement_derive.py")],
                capture_output=True, text=True, timeout=600, cwd=scratch)
            self.assertNotEqual(
                proc.returncode, 0,
                "the boolean alone must not carry the proof")
            self.assertIn("v0b-cpu-02", proc.stdout)
            summ = json.loads((scratch / "docs/investigations/vulkan-v0-b"
                               / "results/cpu-supplemental/summary.json").read_text())
            self.assertNotIn("v0b-cpu-02",
                             [r["run_id"] for r in summ["accepted_runs"]])

    def test_economics_rechecks_raw_stderr_not_historical_boolean(self):
        """Production economics must fail before making an invalid CPU ratio."""
        with tempfile.TemporaryDirectory() as td:
            scratch = make_scratch_tree(Path(td))
            rd = (scratch / "docs/investigations/vulkan-v0-b/results"
                  / "cpu-supplemental/v0b-cpu-02")
            rec = json.loads((rd / "run.json").read_text())
            self.assertTrue(rec["backend_selection_proven"])
            stderr_path = rd / "stderr.txt"
            stderr_path.write_text("\n".join(
                ln for ln in stderr_path.read_text().splitlines()
                if "offloaded 0/37 layers to GPU" not in ln) + "\n")
            proc = subprocess.run(
                [sys.executable, str(scratch / "scripts/v0b_economics.py")],
                capture_output=True, text=True, timeout=600, cwd=scratch)
            self.assertNotEqual(proc.returncode, 0,
                                "economics must recheck raw stderr, not the boolean")
            self.assertIn("v0b-cpu-02", proc.stdout + proc.stderr)

    def test_cpu_arm_is_retrospective_descriptive_not_prospective_authority(self):
        summ = json.loads((self.CPU / "summary.json").read_text())
        governance = summ["governance"]
        self.assertEqual(governance["physical_factual_finding"],
                         "layers-executed-on-host-CPU")
        self.assertEqual(governance["final_proof_timing"], "retrospective_after_collection")
        self.assertFalse(governance["prospectively_frozen_decision_grade"])

    def test_mutated_stderr_contradicting_verdict_is_rejected(self):
        """Rewriting a layer assignment to a GPU breaks the proof even
        though the byte count barely changes."""
        with tempfile.TemporaryDirectory() as td:
            scratch = make_scratch_tree(Path(td))
            rd = (scratch / "docs/investigations/vulkan-v0-b/results"
                  / "cpu-supplemental/v0b-cpu-03")
            stderr_path = rd / "stderr.txt"
            stderr = stderr_path.read_text()
            self.assertIn("layer  36 assigned to device CPU", stderr)
            stderr_path.write_text(
                stderr.replace("layer  36 assigned to device CPU",
                               "layer  36 assigned to device Vulkan0", 1))
            proc = subprocess.run(
                [sys.executable, str(scratch / "scripts/v0b_cpu_supplement_derive.py")],
                capture_output=True, text=True, timeout=600, cwd=scratch)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("v0b-cpu-03", proc.stdout)

    def test_proof_module_unit_semantics(self):
        sys.path.insert(0, str(REPO / "scripts"))
        import v0b_cpu_proof as cp

        good = (
            "llama_prepare_model_devices: using device Vulkan0 (X) (0000:04:00.0)\n"
            + "".join(f"load_tensors: layer {i:3d} assigned to device CPU, is_swa = 0\n"
                      for i in range(37))
            + "load_tensors: offloaded 0/37 layers to GPU\n"
            "load_tensors:   CPU_Mapped model buffer size =   1834.82 MiB\n"
            "llama_kv_cache:        CPU KV buffer size =    18.00 MiB\n"
            "llama_context:        CPU  output buffer size =     0.58 MiB\n"
            "sched_reserve:    Vulkan0 compute buffer size =   565.81 MiB\n"
        )
        proof = cp.proof_from_stderr(good)
        self.assertTrue(proof["proved"])
        self.assertEqual(len(proof["gpu_device_binding_lines"]), 1)

        # one layer assigned to GPU -> broken
        proof = cp.proof_from_stderr(good.replace(
            "layer   5 assigned to device CPU",
            "layer   5 assigned to device Vulkan0"))
        self.assertFalse(proof["proved"])
        self.assertEqual(proof["layers_assigned_gpu"], [5])

        # offload line duplicated -> broken
        proof = cp.proof_from_stderr(good + "load_tensors: offloaded 0/37 layers to GPU\n")
        self.assertFalse(proof["proved"])
        self.assertEqual(proof["offload_lines_found"], 2)

        # nonzero offload (offloaded 12/37) -> broken
        proof = cp.proof_from_stderr(good.replace(
            "offloaded 0/37", "offloaded 12/37"))
        self.assertFalse(proof["proved"])

        # missing CPU KV buffer -> broken
        proof = cp.proof_from_stderr(good.replace("CPU KV buffer", "CUDA0 KV buffer"))
        self.assertFalse(proof["proved"])

        # a fully-offloaded run (37/37) must not prove CPU execution
        proof = cp.proof_from_stderr(good.replace(
            "offloaded 0/37 layers to GPU", "offloaded 37/37 layers to GPU"))
        self.assertFalse(proof["proved"])
        self.assertFalse(proof["offload_zero_proven"])


if __name__ == "__main__":
    unittest.main()
