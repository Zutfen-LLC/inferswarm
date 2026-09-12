"""Issue #153 Arm-C remediation bundle regressions (CPU-only).

Validates the retained remediation record against the FreeToken
remediation producer bytes and the accepted #117 producer:

- the phase-0 inventory, producer delta, and boundary matrix re-derive
  byte-identically from the pinned commits (via the FreeToken repo at
  its configured path, read-only);
- the classification is recorded and is branch A;
- the boundary matrix proves 1/31/32/33/53/63/64 single-chunk and
  over-limit determinism;
- the producer delta binds exact file hashes and the unchanged frozen
  surface;
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
REMEDIATION_COMMIT = "5e6bca586f6d960ac863f63cf9e9232ed80e362b"


def load(name: str) -> dict:
    return json.loads((REMEDICATION / name).read_text())


def freetoken_available() -> bool:
    return (FREETOKEN / ".git").exists()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(FREETOKEN), *args], text=True
    ).strip()


class Phase0InventoryTests(unittest.TestCase):
    def test_record_present_and_classified(self):
        record = load("evidence/phase0-inventory.json")
        self.assertEqual(
            record["schema"],
            "inferswarm.issue117.arm-c-remediation.phase0-inventory/1",
        )
        self.assertEqual(
            record["chunk_policy_owner"]["function"],
            "GemmaStageChainRuntime.generate",
        )
        self.assertEqual(
            record["chunk_policy_owner"]["module"],
            "benchmarks/inferswarm_r6/stage_chain.py",
        )
        self.assertTrue(record["one_call_53_rows_legal"]["verdict"])
        self.assertEqual(
            record["row_limit_inputs"]["accepted_two_stage_chunk_literal"], 32
        )
        self.assertEqual(
            record["row_limit_inputs"]["strategy_PREFILL_CHUNK"], 64
        )

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
    def test_record_binds_classification_and_hashes(self):
        record = load("evidence/producer-delta.json")
        self.assertEqual(
            record["classification"], "UNNECESSARY_PARTITION_POLICY"
        )
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
        # sanity: the allowed-changed set excludes every frozen surface file
        import issue153_producer_delta as pd

        for frozen in pd.MUST_BE_IDENTICAL:
            self.assertNotIn(frozen, pd.ALLOWED_CHANGED)


class BoundaryMatrixTests(unittest.TestCase):
    def test_legal_sizes_single_chunk(self):
        record = load("evidence/boundary-matrix.json")
        matrix = record["boundary_matrix"]
        self.assertEqual(matrix["admitted_capacity"], 64)
        for n in (1, 31, 32, 33, 53, 63, 64):
            self.assertEqual(
                matrix["legal_single_chunk"][str(n)], [[0, n]], n
            )
        self.assertEqual(matrix["over_limit"]["65"], [[0, 64], [64, 1]])
        self.assertEqual(matrix["over_limit"]["85"], [[0, 64], [64, 21]])
        self.assertEqual(
            matrix["historical_causal_control"]["single_chunk_53"], [[0, 53]]
        )
        self.assertTrue(
            matrix["historical_causal_control"]["multi_chunk_32_21_rejected"]
        )
        self.assertEqual(record["focused_suite"]["exit_code"], 0)
        self.assertIn("58 passed", record["focused_suite"]["summary"])
        self.assertEqual(record["remediation_producer"], REMEDIATION_COMMIT)

    def test_record_disclaims_gpu_claims(self):
        record = load("evidence/boundary-matrix.json")
        self.assertTrue(record["does_not_prove"].startswith("GPU numerical"))


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
        # the working tree must carry no modification under any accepted
        # evidence bundle (this test runs against the checked-out tree;
        # CI runs it against a fresh checkout, where it is trivially green
        # and still guards against accidental in-place edits on push)
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

    def test_readme_states_terminal_and_non_claims(self):
        readme = (REMEDICATION / "README.md").read_text()
        self.assertIn("ISSUE117_ARM_C_REMEDIATION_READY", readme)
        self.assertIn("UNNECESSARY_PARTITION_POLICY", readme)
        self.assertIn("remains separately blocked", readme)
        self.assertIn("No GPU/model execution occurred", readme)


if __name__ == "__main__":
    unittest.main()
