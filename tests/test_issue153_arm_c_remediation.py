"""Issue #153 remediation bundle regressions (CPU-only) — CORRECTED.

Validates the corrected remediation record (classification
BACKEND_REQUIRES_MULTI_CHUNK, terminal ISSUE117_ARM_C_REMEDIATION_BLOCKED)
against the FreeToken remediation producer bytes and the accepted #117
producer:

- the phase-0 inventory, producer delta, and boundary matrix re-derive
  byte-identically from the pinned commits (via the FreeToken repo at
  its configured path, read-only);
- the classification is branch B and the terminal is BLOCKED;
- the accepted #137 population facts are hash-pinned and derived (65-67
  failing rows, <=53 stable, chunk 64, two-chunk == divergent);
- the failing population answers record behavior_changed=False with the
  unchanged accepted partition;
- the producer delta binds exact file hashes, the unchanged frozen
  surface, the timing-unit restoration, and mechanically rejects
  out-of-scope runtime changes (unit drift, wire-service imports,
  case/regime nouns);
- the bundle manifest is complete and acyclic, and rejects mutated or
  undeclared evidence;
- the parent #117 evidence manifest remains closed to this bundle;
- accepted #133/#137 bundles are byte-untouched by this slice.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_proof  # noqa: E402
import issue153_manifest  # noqa: E402

REMEDICATION = (
    ROOT / "docs/implementation/r6-successor-dense-full-integration-117/"
    "remediation"
)
FREETOKEN = ROOT.parent / "FreeToken"
ACCEPTED_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
# corrected candidate head (the reviewed head 5e6bca58 is superseded)
REMEDIATION_COMMIT = "f6133b88d40e4d43d3ac82fa732f21e540b7273d"


def load(name: str) -> dict:
    return json.loads((REMEDICATION / name).read_text())


def freetoken_available() -> bool:
    return (FREETOKEN / ".git").exists()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(FREETOKEN), *args], text=True
    ).strip()


class Phase0InventoryTests(unittest.TestCase):
    def test_record_present_and_correctly_classified(self):
        record = load("evidence/phase0-inventory.json")
        self.assertEqual(
            record["schema"],
            "inferswarm.issue117.arm-c-remediation.phase0-inventory/2",
        )
        self.assertEqual(
            record["chunk_policy_owner"]["function"],
            "GemmaStageChainRuntime.generate",
        )
        self.assertEqual(
            record["chunk_policy_owner"]["module"],
            "benchmarks/inferswarm_r6/stage_chain.py",
        )
        # corrected classification: branch B, terminal BLOCKED
        branch = record["branch_classification"]
        self.assertEqual(branch["branch"], "BACKEND_REQUIRES_MULTI_CHUNK")
        self.assertFalse(branch["branch_a_available"])
        self.assertIn("WITHDRAWN", branch["branch_a_withdrawn_rationale"])
        self.assertEqual(
            branch["terminal"], "ISSUE117_ARM_C_REMEDIATION_BLOCKED"
        )
        self.assertFalse(branch["branch_b_option_1_available_cpu_only"])

    def test_accepted_137_population_facts_bound(self):
        record = load("evidence/phase0-inventory.json")
        population = record["accepted_137_population"]
        self.assertEqual(
            population["failing_population_rows"], [65, 66, 67]
        )
        self.assertEqual(population["divergent_prompt_lens"],
                         [65, 65, 66, 67, 67, 67])
        self.assertEqual(population["stable_max_prompt_len"], 53)
        self.assertEqual(population["prefill_chunk"], 64)
        self.assertTrue(population["two_chunk_equals_divergent_population"])
        # the population record is hash-pinned to the accepted #137 bytes
        pinned = population["pinned_record"]
        pinned_path = ROOT / pinned["path"]
        actual = hashlib.sha256(pinned_path.read_bytes()).hexdigest()
        self.assertEqual(actual, pinned["sha256"])

    def test_failing_population_single_call_disproven(self):
        record = load("evidence/phase0-inventory.json")
        legality = record["failing_population_single_call_legal"]
        self.assertEqual(legality["rows"], [65, 66, 67])
        self.assertFalse(legality["verdict"])
        self.assertIn("NOT per-call boundary authority",
                      legality["runtime_capacity_note"])

    def test_c2_control_is_control_only(self):
        record = load("evidence/phase0-inventory.json")
        control = record["one_call_53_rows_legal_control_only"]
        self.assertTrue(control["verdict"])
        self.assertIn("CONTROL", control["role"])
        self.assertIn("NOT", control["role"])

    def test_row_limit_inputs_record_accepted_literals(self):
        record = load("evidence/phase0-inventory.json")
        inputs = record["row_limit_inputs"]
        self.assertEqual(inputs["accepted_two_stage_chunk_literal"], 32)
        self.assertEqual(inputs["strategy_PREFILL_CHUNK"], 64)

    @unittest.skipUnless(freetoken_available(), "FreeToken checkout absent")
    def test_record_regenerates_byte_identically(self):
        import issue153_phase0_inventory

        rebuilt = issue153_phase0_inventory.build(FREETOKEN, REMEDIATION_COMMIT)
        rendered = json.dumps(rebuilt, indent=2, sort_keys=True) + "\n"
        self.assertEqual(
            rendered,
            (REMEDICATION / "evidence/phase0-inventory.json").read_text(),
        )

    @unittest.skipUnless(freetoken_available(), "FreeToken checkout absent")
    def test_accepted_producer_in_remediation_ancestry(self):
        result = subprocess.run(
            ["git", "-C", str(FREETOKEN), "merge-base", "--is-ancestor",
             ACCEPTED_PRODUCER, REMEDIATION_COMMIT],
        )
        self.assertEqual(result.returncode, 0)


class ProducerDeltaTests(unittest.TestCase):
    def test_record_binds_corrected_classification_and_hashes(self):
        record = load("evidence/producer-delta.json")
        self.assertEqual(record["classification"],
                         "BACKEND_REQUIRES_MULTI_CHUNK")
        self.assertEqual(record["terminal"],
                         "ISSUE117_ARM_C_REMEDIATION_BLOCKED")
        self.assertEqual(record["accepted_producer"], ACCEPTED_PRODUCER)
        self.assertEqual(record["remediation_producer"], REMEDIATION_COMMIT)
        self.assertEqual(
            record["starting_research_base"],
            "b05564a7f3f7ca1b141d54842357ff2624dc6a19",
        )
        changed = record["changed_runtime_files"]
        self.assertIn(
            "python/freetoken/research/prefill_partition.py", changed
        )
        self.assertIn("benchmarks/inferswarm_r6/stage_chain.py", changed)
        for entry in changed.values():
            self.assertRegex(entry["remediated_sha256"] or "", r"^[0-9a-f]{64}$")
        self.assertIn("no h109-* material was accessed",
                      " ".join(record["non_claims"]))
        # every changed runtime file passed the mechanical audit
        audit = record["changed_runtime_files_audit"]
        for rel in record["changed_runtime_files"]:
            if rel.startswith(("benchmarks/", "python/")):
                self.assertEqual(audit[rel], "clean")

    def test_failing_population_answers_record_no_behavior_change(self):
        record = load("evidence/producer-delta.json")
        answers = record["failing_population_remediation_answers"]
        self.assertEqual(sorted(answers), ["65", "66", "67"])
        for rows, answer in answers.items():
            n = int(rows)
            self.assertEqual(
                answer["accepted_execution_partition"], [[0, 64], [64, n - 64]]
            )
            self.assertEqual(
                answer["corrected_execution_partition"], [[0, 64], [64, n - 64]]
            )
            self.assertFalse(answer["behavior_changed"])

    def test_timing_unit_correction_recorded(self):
        record = load("evidence/producer-delta.json")
        self.assertIn("perf_counter_ns", record["timing_unit_correction"])
        self.assertIn("nanosecond", record["timing_unit_correction"])

    def test_behavioral_delta_is_honest_about_failing_path(self):
        record = load("evidence/producer-delta.json")
        self.assertIn("UNCHANGED", record["behavioral_delta"])
        self.assertIn("NOT remediated", record["behavioral_delta"])
        self.assertIn("MUST NOT be authorized",
                      record["applicability_caveat"])

    @unittest.skipUnless(freetoken_available(), "FreeToken checkout absent")
    def test_record_regenerates_byte_identically(self):
        import issue153_producer_delta

        rebuilt = issue153_producer_delta.build(FREETOKEN, REMEDIATION_COMMIT)
        rendered = json.dumps(rebuilt, indent=2, sort_keys=True) + "\n"
        self.assertEqual(
            rendered,
            (REMEDICATION / "evidence/producer-delta.json").read_text(),
        )

    @unittest.skipUnless(freetoken_available(), "FreeToken checkout absent")
    def test_delta_builder_rejects_out_of_scope_change(self):
        import issue153_producer_delta as pd

        for frozen in pd.MUST_BE_IDENTICAL:
            self.assertNotIn(frozen, pd.ALLOWED_CHANGED)

    @unittest.skipUnless(freetoken_available(), "FreeToken checkout absent")
    def test_delta_builder_rejects_unit_drift(self):
        """Negative control: a two_stage carrying bare perf_counter() is
        mechanically rejected by the changed-file audit (the reviewed
        head's defect class), via the audit function directly on
        mutated bytes of the real corrected file."""
        import issue153_producer_delta as pd
        import tempfile

        data = pd.blob_bytes(
            FREETOKEN, REMEDIATION_COMMIT,
            "benchmarks/inferswarm_r6/two_stage.py",
        )
        drifted = data.replace(
            b"t = time.perf_counter_ns()", b"t = time.perf_counter()"
        )
        self.assertNotEqual(drifted, data)  # mutation actually applied

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)

            original = pd.blob_bytes

            def fake_blob(_repo, commit, path):
                if path.endswith("two_stage.py"):
                    return drifted
                return original(FREETOKEN, commit, path)

            pd.blob_bytes = fake_blob
            try:
                with self.assertRaises(SystemExit) as caught:
                    pd.audit_changed_runtime_files(repo, REMEDIATION_COMMIT)
                self.assertIn("perf_counter", str(caught.exception))
            finally:
                pd.blob_bytes = original

    def test_runtime_capacity_256_recorded_separately(self):
        record = load("evidence/phase0-inventory.json")
        legality = record["failing_population_single_call_legal"]
        self.assertEqual(legality["runtime_capacity_tokens"], 256)


class BoundaryMatrixTests(unittest.TestCase):
    def test_failing_population_is_primary_and_unchanged(self):
        record = load("evidence/boundary-matrix.json")
        matrix = record["boundary_matrix"]
        self.assertEqual(matrix["admitted_capacity"], 64)
        # the EXACT accepted population, explicitly classified
        for n, expected in (
            (65, [[0, 64], [64, 1]]),
            (66, [[0, 64], [64, 2]]),
            (67, [[0, 64], [64, 3]]),
        ):
            self.assertEqual(
                matrix["accepted_failing_population"][str(n)], expected, n
            )
        # per-row answers: unchanged accepted partition, no behavior change
        for n in (65, 66, 67):
            answer = record["failing_population_answers"][str(n)]
            self.assertFalse(answer["behavior_changed"], n)
            self.assertFalse(answer["single_call_legal_under_frozen_contract"])
            self.assertEqual(
                answer["corrected_execution_partition"], [[0, 64], [64, n - 64]]
            )

    def test_legal_sizes_single_chunk_and_c2_control_retained(self):
        record = load("evidence/boundary-matrix.json")
        matrix = record["boundary_matrix"]
        for n in (1, 31, 32, 33, 53, 63, 64):
            self.assertEqual(
                matrix["legal_single_chunk"][str(n)], [[0, n]], n
            )
        self.assertEqual(matrix["over_limit"]["85"], [[0, 64], [64, 21]])
        control = matrix["historical_causal_control"]
        self.assertEqual(control["single_chunk_53"], [[0, 53]])
        self.assertTrue(control["multi_chunk_32_21_rejected"])
        self.assertIn("NOT", control["role"])  # control-only disclaimed

    def test_focused_suite_green_on_corrected_head(self):
        record = load("evidence/boundary-matrix.json")
        self.assertEqual(record["focused_suite"]["exit_code"], 0)
        self.assertIn("79 passed", record["focused_suite"]["summary"])
        self.assertEqual(record["remediation_producer"], REMEDIATION_COMMIT)

    def test_record_disclaims_gpu_and_remediation_claims(self):
        record = load("evidence/boundary-matrix.json")
        self.assertTrue(record["does_not_prove"].startswith("GPU numerical"))
        self.assertIn("BLOCKED", record["does_not_prove"])


class ManifestTests(unittest.TestCase):
    def copy_bundle(self, root: Path) -> None:
        relatives = {
            *(str(issue153_manifest.BUNDLE / name)
              for name in issue153_manifest.EVIDENCE_FILES),
            *issue153_manifest.PRODUCERS,
        }
        for relative in relatives:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        manifest = root / issue153_manifest.MANIFEST
        manifest.write_bytes(issue153_manifest.render(root))

    def test_manifest_is_current_and_acyclic(self):
        issue153_manifest.check(ROOT)
        entries = issue153_manifest.parse(
            (ROOT / issue153_manifest.MANIFEST).read_bytes()
        )
        self.assertNotIn(str(issue153_manifest.MANIFEST), entries)
        self.assertEqual(
            set(entries), set(issue153_manifest.expected_entries(ROOT))
        )

    def test_manifest_rejects_mutated_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_bundle(root)
            readme = root / issue153_manifest.BUNDLE / "README.md"
            readme.write_bytes(readme.read_bytes() + b"\nmutation\n")
            with self.assertRaisesRegex(
                issue153_manifest.ManifestError, "manifest drift"
            ):
                issue153_manifest.check(root)

    def test_manifest_rejects_undeclared_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_bundle(root)
            rogue = root / issue153_manifest.BUNDLE / "evidence" / "rogue.json"
            rogue.write_text("{}\n")
            with self.assertRaisesRegex(
                issue153_manifest.ManifestError, "inventory mismatch"
            ):
                issue153_manifest.check(root)


class PreservationTests(unittest.TestCase):
    def test_parent_117_manifest_closed_to_this_bundle(self):
        prefix = "remediation/"
        self.assertFalse(
            any(path.startswith(prefix)
                for path in issue117_proof.COMMITTED_EVIDENCE_FILES)
        )
        parent = ROOT / issue117_proof.AREA / "evidence" / "MANIFEST.sha256"
        self.assertFalse(any(
            line.split("  ", 1)[1].startswith(
                str(issue117_proof.AREA / "evidence" / prefix))
            for line in parent.read_text().splitlines()
        ))

    def test_accepted_bundles_byte_untouched_by_working_tree(self):
        status = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain",
             "--", "docs/implementation"],
            capture_output=True, text=True,
        ).stdout.strip()
        for line in status.splitlines():
            self.assertFalse(
                line.endswith(".json") and (
                    "arm-c-regime4-diagnosis-137" in line
                    or "arm-c-retry" in line or "arm-c/" in line
                ),
                f"accepted evidence modified: {line}",
            )

    def test_accepted_137_inventory_bytes_unchanged(self):
        """The hash-pinned #137 population record is byte-identical to
        its accepted manifest row (the correction binds to it read-only)."""
        pinned = load("evidence/phase0-inventory.json")[
            "accepted_137_population"
        ]["pinned_record"]
        actual = hashlib.sha256((ROOT / pinned["path"]).read_bytes()).hexdigest()
        self.assertEqual(actual, pinned["sha256"])
        self.assertEqual(
            pinned["sha256"],
            "369b2c81faf8ed1b2a68b1e1d039d6e6e7924d02254443c4707ad1b006ac7b3f",
        )

    def test_readme_states_terminal_and_non_claims(self):
        readme = (REMEDICATION / "README.md").read_text()
        self.assertIn("ISSUE117_ARM_C_REMEDIATION_BLOCKED", readme)
        self.assertIn("BACKEND_REQUIRES_MULTI_CHUNK", readme)
        self.assertIn("WITHDRAWN", readme)
        self.assertIn("MUST NOT be authorized", readme)
        self.assertIn("No GPU/model execution occurred", readme)


if __name__ == "__main__":
    unittest.main()
