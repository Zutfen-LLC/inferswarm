"""Issue #277 RED regressions: CPU-only retained bytes and recording callbacks.

Drive the production orchestration entry point, not a test-only reducer. The
#276 builder emits independent collector captures for each arm and repeat;
no callback return value is evidence of admission or determinism.
"""
from __future__ import annotations

import inspect
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue270_authority as C
import issue273_reducer as R
import issue276_reader as B
from tests.test_issue276_byte_admission import BundleBuilder, fixture_row
import issue277_orchestrator as O


class ReferenceFirstTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source = root / "capture"
        self.staged = root / "staged"
        self.builder = BundleBuilder(self.source)
        self.launches = []
        self.comparisons = []

    def case(self, case, *, drift=None, missing=None, substitute_repeat=False):
        """Four distinct captures with complete, non-aliasing legal rows.

        Change row bytes in collector custody BEFORE staging so a drift is a
        validly admitted unit, not a staged byte-integrity failure.
        """
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                if substitute_repeat and arm == "reference" and repeat:
                    src = self.source / "source" / case / "reference"
                    dst = self.source / "source" / case / "reference-repeat"
                    shutil.copytree(src, dst)
                else:
                    run = self.builder.capture(arm, repeat, case=case)
                    if drift == (arm, repeat):
                        (run / "rows/3.f32").write_bytes(fixture_row(arm, "3")[::-1])
                if missing != (arm, repeat):
                    B.stage_capture_276(self.source, self.staged, case, arm, repeat)

    def fixture(self, **overrides):
        for case in C.FIXTURE_CASES:
            self.case(case, **overrides.get(case, {}))

    def executor(self, case):
        self.launches.append(case)
        # CPU-only recording fake. Returned bytes are not authority; the
        # orchestrator must read admitted staged/custody bytes instead.
        return {str(d): fixture_row("candidate", str(d)) for d in range(C.DECISIONS)}

    def compare(self, case, reference, candidate):
        self.comparisons.append(case)
        return {"fixture_comparison": case}

    def run_gate(self):
        return O.orchestrate_277(self.staged, self.source, self.executor, self.compare)

    def test_matching_reference_fixture_reaches_candidate_gate(self):
        self.fixture()
        record = self.run_gate()
        self.assertEqual(record["schema"], "inferswarm.issue277.reference-first/1")
        self.assertEqual(record["status"], "candidate gate reached")
        self.assertIsNone(record["terminal"])
        self.assertEqual(self.launches, list(C.FIXTURE_CASES))
        self.assertEqual(self.comparisons, list(C.FIXTURE_CASES))
        self.assertEqual(record["candidate_launches"], len(C.FIXTURE_CASES))
        for case in C.FIXTURE_CASES:
            for arm in ("reference", "candidate"):
                item = record["cases"][case][arm]
                self.assertTrue(item["deterministic"])
                self.assertEqual(set(item["primary_row_sha256"]),
                                 {str(d) for d in range(C.DECISIONS)})
                self.assertEqual(item["primary_row_sha256"], item["repeat_row_sha256"])

    def test_case3072_reference_mismatch_zero_candidate_launches(self):
        self.fixture(**{"case-3072": {"drift": ("reference", True)}})
        # Distinct validly admitted captures and derived row-digest mismatch.
        for repeat in (False, True):
            self.assertTrue(B.admit_staged_276(self.staged, "case-3072", "reference", repeat,
                                               custody_root=self.source)["admitted"])
        record = self.run_gate()
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["terminal"], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273)
        self.assertFalse(record["cases"]["case-3072"]["reference"]["deterministic"])
        self.assertEqual(record["candidate_launches"], 0)
        self.assertEqual(self.launches, [])
        self.assertEqual(self.comparisons, [])

    def test_missing_reference_evidence_fails_closed_distinct_from_mismatch(self):
        self.fixture(**{"case-3072": {"missing": ("reference", True)}})
        record = self.run_gate()
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("reference" in p and "missing" in p for p in record["problems"]))
        self.assertNotEqual(record["terminal"], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273)
        self.assertEqual(record["candidate_launches"], 0)
        self.assertEqual(self.launches, [])
        self.assertEqual(self.comparisons, [])

    def test_candidate_nondeterminism_blocks_pair_comparison(self):
        self.fixture(**{"case-1024": {"drift": ("candidate", True)}})
        record = self.run_gate()
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("candidate" in p and "mismatch" in p for p in record["problems"]))
        self.assertFalse(record["cases"]["case-1024"]["candidate"]["deterministic"])
        self.assertEqual(self.comparisons, [])
        self.assertEqual(self.launches, list(C.FIXTURE_CASES))

    def test_forged_determinism_boolean_cannot_bypass(self):
        self.fixture(**{"case-3072": {"missing": ("reference", True)}})
        self.assertNotIn("reference_deterministic", inspect.signature(O.orchestrate_277).parameters)
        with self.assertRaises(TypeError):
            O.orchestrate_277(self.staged, self.source, self.executor,
                              reference_deterministic=True)
        # Attack the PAIR verdict dictionary in memory. A forged claim of
        # admission/determinism cannot substitute for a missing repeat byte
        # set; the real per-unit byte reader must still be invoked.
        forged = {"admitted": True, "problems": [],
                  "units": {k: True for k in ("reference", "reference+repeat",
                                                   "candidate", "candidate+repeat")}}
        with patch.object(O, "admit_pair_276", return_value=forged):
            record = self.run_gate()
        self.assertEqual(record["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertEqual(record["candidate_launches"], 0)
        self.assertEqual(self.launches, [])

    def test_repeat_substitution_rejected(self):
        self.fixture(**{"case-3072": {"substitute_repeat": True}})
        record = self.run_gate()
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("repeat" in p.lower() and ("incarnation" in p or "source" in p)
                            for p in record["problems"]))
        self.assertEqual(self.launches, [])

    def test_missing_rows_rejected(self):
        self.fixture()
        (self.staged / "units/case-3072/reference-repeat/rows/7.f32").unlink()
        record = self.run_gate()
        self.assertEqual(record["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertTrue(any("rows/7.f32" in p or "row decision set incomplete" in p
                            for p in record["problems"]))
        self.assertEqual(self.launches, [])

    def test_reordered_execution_still_reference_first(self):
        self.fixture(**{"case-3072": {"drift": ("reference", True)}})
        # Reorder the earlier cases but leave the mismatch LAST: a flawed
        # per-case reference->candidate loop would launch twice before it.
        reordered = (C.FIXTURE_CASES[1], C.FIXTURE_CASES[0], C.FIXTURE_CASES[2])
        with patch.object(C, "FIXTURE_CASES", reordered):
            record = self.run_gate()
        self.assertEqual(record["terminal"], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273)
        self.assertEqual(record["candidate_launches"], 0)
        self.assertEqual(self.launches, [])
        self.assertEqual(self.comparisons, [])

    def test_first_demonstration_matching_and_mismatch_fixtures(self):
        self.fixture()
        matching = self.run_gate()
        self.assertEqual(matching["status"], "candidate gate reached")
        self.assertEqual(self.launches, list(C.FIXTURE_CASES))
        self.launches.clear()
        self.comparisons.clear()
        # Build a fresh fixture root; changing the collector-owned repeat
        # before staging creates a valid mismatch without repairing digests.
        with tempfile.TemporaryDirectory() as td:
            self.source = Path(td) / "capture"
            self.staged = Path(td) / "staged"
            self.builder = BundleBuilder(self.source)
            self.fixture(**{"case-3072": {"drift": ("reference", True)}})
            mismatch = self.run_gate()
            self.assertEqual(mismatch["terminal"], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273)
            self.assertEqual(mismatch["candidate_launches"], 0)
            self.assertEqual(self.launches, [])
            self.assertEqual(self.comparisons, [])


if __name__ == "__main__":
    unittest.main()
