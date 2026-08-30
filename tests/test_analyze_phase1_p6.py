import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analyze_phase1_p6 as analysis


class Phase1P6AnalysisTests(unittest.TestCase):
    def _row(self, session, arm, class_id, repetition, *, measured):
        return {
            "phase": "measured" if measured else "warmup",
            "measured": measured,
            "repetition": repetition,
            "failed": False,
            "session_number": session,
            "arm_id": arm,
            "class_id": class_id,
            "batch_size": 1,
            "ignore_eos": True,
            "completion_matches_request": True,
            "decode_tok_s": 10.0 + repetition,
            "ttft_ms": 100.0,
            "prefill": {"prefill_tok_s": 1000.0},
            "inter_token_ms_p50": 1.0,
            "inter_token_ms_p95": 2.0,
            "inter_token_ms_max": 3.0,
        }

    def _session(self, root, session=1):
        session_root = root / f"session-{session}"
        session_root.mkdir()
        summary = {
            "execution_status": "COMPLETE",
            "validity": "VALID",
            "campaign_identity": {"sha256": analysis.EXPECTED_IDENTITY},
            "campaign_invalidations": [],
            "canonical_blockers": [],
            "baseline_noise_floor_status": {"all_within_ceiling": True},
            "baseline_identity_gate": {"passed": True},
            "completion": {
                "expected_primary_generations": 96,
                "observed_generations": 144,
                "failed_generations": 0,
                "incomplete_blocks": [],
                "supplementary_condition": {
                    "required_supplementary_block_completed": True
                },
            },
            "artifact_sha256": {},
        }
        for arm in analysis.PRIMARY_ARMS + ("baseline_b1_kv_matched",):
            arm_root = session_root / arm
            arm_root.mkdir()
            for class_id in analysis.CLASSES:
                rows = [
                    self._row(session, arm, class_id, index, measured=False)
                    for index in range(2)
                ]
                rows += [
                    self._row(session, arm, class_id, index, measured=True)
                    for index in range(10)
                ]
                (arm_root / f"{class_id}.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows)
                )
        (session_root / "session-summary.json").write_text(json.dumps(summary))
        return session_root / "session-summary.json"

    def test_validate_session_accepts_complete_canonical_input(self):
        with tempfile.TemporaryDirectory() as directory:
            self._session(Path(directory))
            summary, repetitions = analysis.validate_session(
                Path(directory), 1, verify_hashes=True
            )
        self.assertEqual(summary["validity"], "VALID")
        self.assertEqual(len(repetitions["baseline_b1"]["W1"]), 10)

    def test_validate_session_rejects_incomplete_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._session(Path(directory))
            summary = json.loads(path.read_text())
            summary["execution_status"] = "INCOMPLETE"
            path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "not COMPLETE / VALID"):
                analysis.validate_session(Path(directory), 1, verify_hashes=False)

    def test_validate_session_rejects_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._session(Path(directory))
            summary = json.loads(path.read_text())
            summary["campaign_identity"]["sha256"] = "0" * 64
            path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                analysis.validate_session(Path(directory), 1, verify_hashes=False)

    def test_validate_session_rejects_baseline_cv_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._session(Path(directory))
            summary = json.loads(path.read_text())
            summary["baseline_noise_floor_status"]["all_within_ceiling"] = False
            path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "baseline CV"):
                analysis.validate_session(Path(directory), 1, verify_hashes=False)

    def test_validate_session_rejects_artifact_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._session(Path(directory))
            session_root = path.parent
            artifact = session_root / "indexed.json"
            artifact.write_text("preserved observation\n")
            summary = json.loads(path.read_text())
            summary["artifact_sha256"]["indexed.json"] = "0" * 64
            path.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                analysis.validate_session(Path(directory), 1, verify_hashes=True)

    def test_measured_repetitions_rejects_selective_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "W1.jsonl"
            rows = [self._row(1, "baseline_b1", "W1", i, measured=False) for i in range(2)]
            rows += [self._row(1, "baseline_b1", "W1", i, measured=True) for i in range(9)]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.assertRaisesRegex(ValueError, "10 measured"):
                analysis.measured_repetitions(path, 1, "baseline_b1", "W1")

    def test_bootstrap_is_fixed_unpaired_and_exactly_ten_thousand(self):
        repetitions = {}
        for arm, offset in (("baseline_b1", 0.0), ("candidate_v2", 2.0)):
            repetitions[arm] = {}
            for class_id in analysis.CLASSES:
                repetitions[arm][class_id] = [
                    self._row(1, arm, class_id, i, measured=True)
                    | {"decode_tok_s": 10.0 + offset + i}
                    for i in range(10)
                ]
        first = analysis.bootstrap_session(repetitions, seed=0, resamples=10_000)
        second = analysis.bootstrap_session(repetitions, seed=0, resamples=10_000)
        self.assertEqual(first, second)
        self.assertGreater(first["classes"]["W1"]["r_c"], 1.0)
        self.assertTrue(np.isfinite(first["r_agg_ci95"]).all())


if __name__ == "__main__":
    unittest.main()
