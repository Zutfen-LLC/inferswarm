from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import derive_phase1_placement as v1
import derive_phase1_placement_v2 as v2


class Phase1PlacementV2Tests(unittest.TestCase):
    def test_historical_v1_artifact_is_byte_identical(self) -> None:
        path = ROOT / "docs/investigations/data/phase1-qwen36-placement-v1.json"
        self.assertEqual(v1.sha256(path), v2.V1_ARTIFACT_SHA256)

    def test_checked_in_v2_artifact_and_checksum_are_self_consistent(self) -> None:
        data_dir = ROOT / "docs/investigations/data"
        artifact_path = data_dir / "phase1-qwen36-placement-v2.json"
        checksum_path = data_dir / "phase1-placement-v2.sha256.txt"
        expected_sha, expected_name = checksum_path.read_text(encoding="utf-8").split()
        self.assertEqual(expected_name, artifact_path.name)
        self.assertEqual(v1.sha256(artifact_path), expected_sha)

        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(artifact["policy_id"], v2.POLICY_ID)
        self.assertEqual(artifact["policy"]["selected_overlap_slots"], 528)
        self.assertEqual(artifact["policy"]["rank_window_start"], 3246)
        self.assertEqual(artifact["policy"]["rank_window_end_exclusive"], 8688)
        placement = artifact["placements"][v2.CANONICAL_PLACEMENT]
        self.assertEqual(placement["slot_count"], v2.REMOTE_SLOTS)
        self.assertTrue(
            all(
                row["minimum_repetition_coverage"] >= float(v2.PLACEMENT_FLOOR)
                for row in placement["coverage_evidence"]["per_class"].values()
            )
        )

    def test_canonical_source_hashes_are_all_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            for name in v1.EXPECTED_SHA256:
                (run_dir / name).write_text("fixture\n", encoding="utf-8")
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "headline": "VALID CANONICAL CAMPAIGN",
                        "execution_status": "COMPLETE",
                        "validity": "VALID",
                        "observations": {"expected": 288, "observed": 288},
                    }
                ),
                encoding="utf-8",
            )
            matching = lambda path: v1.EXPECTED_SHA256[path.name]
            with mock.patch.object(v1, "sha256", side_effect=matching):
                v2.check_source(run_dir)

            mismatching = dict(v1.EXPECTED_SHA256)
            mismatching["exact-routing.jsonl"] = "0" * 64
            with (
                mock.patch.object(
                    v1, "sha256", side_effect=lambda path: mismatching[path.name]
                ),
                self.assertRaisesRegex(ValueError, "source hash mismatch"),
            ):
                v2.check_source(run_dir)

            (run_dir / "cache-pressure.jsonl").unlink()
            with (
                mock.patch.object(v1, "sha256", side_effect=matching),
                self.assertRaisesRegex(ValueError, "missing canonical source artifact"),
            ):
                v2.check_source(run_dir)

    @staticmethod
    def _row(class_id: str, repetition: int) -> dict[str, object]:
        histogram = [[0] * v2.NUM_EXPERTS for _ in range(v2.NUM_LAYERS)]
        histogram[0][0] = 1
        return {
            "record_type": "measured_repetition",
            "class_id": class_id,
            "repetition": repetition,
            "measured": True,
            "trace_completeness": {"complete": True},
            "trace": {"truncated": False},
            "routing": {"histogram": histogram},
        }

    def _write_exact_routing(
        self,
        path: Path,
        *,
        omit: tuple[str, int] | None = None,
        mutate: tuple[str, int, str] | None = None,
    ) -> None:
        with path.open("w", encoding="utf-8") as output:
            for class_id in v2.REQUIRED_CLASSES:
                for repetition in range(v2.MEASURED_REPETITIONS_PER_CLASS):
                    if omit == (class_id, repetition):
                        continue
                    row = self._row(class_id, repetition)
                    if mutate == (class_id, repetition, "incomplete"):
                        row["trace_completeness"] = {"complete": False}
                    if mutate == (class_id, repetition, "truncated"):
                        row["trace"] = {"truncated": True}
                    output.write(json.dumps(row, separators=(",", ":")) + "\n")

    def test_requires_exactly_ten_complete_repetitions_per_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            path = run_dir / "exact-routing.jsonl"
            self._write_exact_routing(path)
            repetitions = v2.load_repetition_histograms(run_dir)
            self.assertEqual(
                {class_id: len(rows) for class_id, rows in repetitions.items()},
                {class_id: 10 for class_id in v2.REQUIRED_CLASSES},
            )

            self._write_exact_routing(path, omit=("W4", 9))
            with self.assertRaisesRegex(ValueError, "expected measured repetition ids"):
                v2.load_repetition_histograms(run_dir)

    def test_incomplete_or_truncated_routing_evidence_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            path = run_dir / "exact-routing.jsonl"
            self._write_exact_routing(path, mutate=("W2", 4, "incomplete"))
            with self.assertRaisesRegex(ValueError, "incomplete exact trace"):
                v2.load_repetition_histograms(run_dir)

            self._write_exact_routing(path, mutate=("W3", 7, "truncated"))
            with self.assertRaisesRegex(ValueError, "truncated exact trace"):
                v2.load_repetition_histograms(run_dir)

    def test_candidate_window_geometry_and_byte_arithmetic(self) -> None:
        ordered = list(range(v2.TOTAL_SLOTS))
        overlap = 123
        candidate = v2.candidate_window(ordered, overlap)
        v1_candidate = set(v2.candidate_window(ordered, 0))
        primary = set(ordered[: v2.GPU0_PRIMARY_PROXY_SLOTS])

        self.assertEqual(len(candidate), 5442)
        self.assertEqual(len(set(candidate)), 5442)
        self.assertEqual(candidate[0], v2.GPU0_PRIMARY_PROXY_SLOTS - overlap)
        self.assertEqual(
            candidate[-1] + 1,
            v2.GPU0_PRIMARY_PROXY_SLOTS - overlap + v2.REMOTE_SLOTS,
        )
        self.assertEqual(len(set(candidate) & primary), overlap)
        self.assertEqual(len(set(candidate) & v1_candidate), 5442 - overlap)
        self.assertEqual(v2.REMOTE_SLOTS * v2.BYTES_PER_SLOT, 9_662_902_272)
        self.assertLessEqual(v2.REMOTE_RESIDENT_BYTES, v2.REMOTE_BUDGET_BYTES)
        with self.assertRaisesRegex(ValueError, "outside valid range"):
            v2.candidate_window(ordered, -1)

    def test_aggregate_above_floor_does_not_hide_one_failed_repetition(self) -> None:
        repetitions: dict[str, list[dict[str, object]]] = {}
        for class_id in v2.REQUIRED_CLASSES:
            rows = []
            for repetition in range(10):
                selected = 1 if class_id == "W1" and repetition == 9 else 3
                counts = [0] * v2.TOTAL_SLOTS
                counts[0] = selected
                counts[10_000] = 10 - selected
                rows.append(
                    {
                        "repetition": repetition,
                        "counts": counts,
                        "total_routes": 10,
                    }
                )
            repetitions[class_id] = rows

        coverage = v2.repetition_coverage({0}, repetitions)
        aggregate_w1 = sum(row["selected_routes"] for row in coverage["W1"]) / sum(
            row["total_routes"] for row in coverage["W1"]
        )
        self.assertGreater(aggregate_w1, 0.20)
        self.assertLess(coverage["W1"][-1]["coverage"], 0.20)
        self.assertFalse(v2.all_repetitions_clear(coverage))

    def _minimum_overlap_fixture(
        self,
    ) -> tuple[list[int], dict[str, list[dict[str, object]]]]:
        ordered = list(range(v2.TOTAL_SLOTS))
        base_id = v2.GPU0_PRIMARY_PROXY_SLOTS
        second_admitted = v2.GPU0_PRIMARY_PROXY_SLOTS - 2
        repetitions: dict[str, list[dict[str, object]]] = {}
        for class_id in v2.REQUIRED_CLASSES:
            rows = []
            for repetition in range(10):
                counts = [0] * v2.TOTAL_SLOTS
                if class_id == "W1" and repetition == 0:
                    counts[base_id] = 1
                    counts[second_admitted] = 1
                    counts[10_000] = 8
                else:
                    counts[base_id] = 2
                    counts[10_000] = 8
                rows.append(
                    {
                        "repetition": repetition,
                        "counts": counts,
                        "total_routes": 10,
                    }
                )
            repetitions[class_id] = rows
        return ordered, repetitions

    def test_search_selects_smallest_qualifying_overlap(self) -> None:
        ordered, repetitions = self._minimum_overlap_fixture()
        overlap, coverage = v2.find_minimum_overlap(ordered, repetitions)
        self.assertEqual(overlap, 2)
        self.assertTrue(v2.all_repetitions_clear(coverage))
        prior = v2.repetition_coverage(
            set(v2.candidate_window(ordered, overlap - 1)), repetitions
        )
        self.assertFalse(v2.all_repetitions_clear(prior))

    def test_artifact_serialization_and_redundant_placement_are_deterministic(
        self,
    ) -> None:
        ordered, repetitions = self._minimum_overlap_fixture()
        counts_by_class, totals_by_class = v2.aggregate_repetitions(repetitions)
        overlap, coverage = v2.find_minimum_overlap(ordered, repetitions)
        artifact = v2.build_artifact(
            {"headline": "VALID CANONICAL CAMPAIGN"},
            ordered,
            overlap,
            coverage,
            counts_by_class,
            totals_by_class,
            {"policy_id": "phase1-qwen36-placement-v1"},
        )
        self.assertEqual(v2.artifact_bytes(artifact), v2.artifact_bytes(artifact))
        placement = artifact["placements"][v2.CANONICAL_PLACEMENT]
        flat_ids = placement["flat_ids_in_rank_order"]
        identities = placement["identities_in_rank_order"]
        self.assertEqual([row["flat_id"] for row in identities], flat_ids)
        self.assertTrue(
            all(
                row["flat_id"] == row["layer"] * v2.NUM_EXPERTS + row["expert_id"]
                for row in identities
            )
        )
        reconstructed = {
            layer_row["layer"] * v2.NUM_EXPERTS + expert_id
            for layer_row in placement["per_layer"]
            for expert_id in layer_row["expert_ids"]
        }
        self.assertEqual(reconstructed, set(flat_ids))
        self.assertEqual(len(flat_ids), 5442)
        digest_once = hashlib.sha256(v2.artifact_bytes(artifact)).hexdigest()
        digest_twice = hashlib.sha256(v2.artifact_bytes(artifact)).hexdigest()
        self.assertEqual(digest_once, digest_twice)


if __name__ == "__main__":
    unittest.main()
