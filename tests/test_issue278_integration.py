"""Issue #278 RED regressions: integrated capture→reduction chain (CPU-only).

Drive the PRODUCTION integration entry point that composes the accepted
#275 collector, the #276 staging/reader/admission path, and the #277
reference-first orchestration into ONE exact-head demonstration, then
shows the #273 reducer still fails closed on the fixture record.

All evidence produced here is tooling/fixture validation. No physical
authority is claimed or mintable at any stage.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue270_authority as C
import issue273_reducer as R
from tests.test_issue276_byte_admission import BundleBuilder, fixture_row
import issue278_integration as I


class IntegrationChainTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.source = root / "capture"
        self.staged = root / "staged"
        self.builder = BundleBuilder(self.source)
        self.launches = []
        self.comparisons = []

    # -- fixture knobs ------------------------------------------------------
    def produce(self, drift=None, tamper_after=None):
        """Recording capture producer driving the REAL #275 collector."""
        state = {"calls": 0}

        def producer(case, arm, repeat):
            state["calls"] += 1
            run = self.builder.capture(arm, repeat, case=case)
            if drift == (case, arm, repeat):
                (run / "rows/3.f32").write_bytes(fixture_row(arm, "3")[::-1])
            if tamper_after is not None and state["calls"] == tamper_after[0]:
                rel, data = tamper_after[1], tamper_after[2]
                (self.source / rel).write_bytes(data)
            return run
        return producer

    def executor(self, case):
        self.launches.append(case)
        return {str(d): fixture_row("candidate", str(d)) for d in range(C.DECISIONS)}

    def compare(self, case, reference, candidate):
        self.comparisons.append(case)
        return {"fixture_comparison": case}

    def run_gate(self, **kwargs):
        return I.run_integration_278(self.source, self.staged,
                                     kwargs.pop("producer", self.produce()),
                                     self.executor, self.compare, **kwargs)

    # -- the integrated chain ------------------------------------------------
    def test_matching_fixture_completes_every_stage(self):
        record = self.run_gate()
        self.assertEqual(record["schema"], "inferswarm.issue278.integration/1")
        self.assertEqual(record["status"],
                         "integration complete (tooling/fixture validation only)")
        self.assertEqual(record["evidence_class"], "tooling/fixture validation")
        # capture -> originals -> staging -> admission -> determinism -> reduction
        self.assertEqual(tuple(record["stages"]),
                         ("capture", "originals", "staging", "admission",
                          "determinism", "reduction"))
        cases = tuple(C.FIXTURE_CASES)
        # Every unit admitted through the reader with custody binding.
        admission = record["stages"]["admission"]["units"]
        for case in cases:
            for arm in ("reference", "candidate"):
                for tag in (arm, arm + "-repeat"):
                    unit = admission[f"{case}/{tag}"]
                    self.assertTrue(unit["admitted"], unit.get("problems"))
                    self.assertEqual(unit["derived"]["backend"], "vulkan")
                    self.assertIn("used_bdf", unit["derived"])
        # Reference-first determinism preserved end to end.
        self.assertEqual(self.launches, list(cases))
        self.assertEqual(self.comparisons, list(cases))
        self.assertEqual(record["candidate_launches"], len(cases))
        # The fixture chain CANNOT mint physical terminal authority.
        reduction = record["stages"]["reduction"]
        self.assertEqual(reduction["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
        self.assertNotEqual(reduction["terminal"], R.TERMINAL_PASS_273)
        self.assertTrue(reduction["problems"])

    def test_stage_linkage_binds_retained_bytes_to_derived_results(self):
        record = self.run_gate()
        capture = record["stages"]["capture"]["units"]
        originals = record["stages"]["originals"]["units"]
        admission = record["stages"]["admission"]["units"]
        for key, unit in capture.items():
            self.assertIn(key, originals)
            self.assertGreater(unit["files"], 0)
            self.assertGreater(unit["bytes"], 0)
            self.assertEqual(unit["files"], originals[key]["files"])
            # Capture-time and originals-stage per-unit inventories must be
            # EQUAL, not merely present: the census is the drift detector.
            self.assertEqual(unit["inventory_sha256"],
                             originals[key]["inventory_sha256"])
            self.assertEqual(unit["bytes"], originals[key]["bytes"])
        for key, unit in admission.items():
            case, tag = key.split("/")
            self.assertEqual(unit["source_stem"], f"source/{case}/{tag}")

    def test_capture_outside_custody_fails_closed_before_staging(self):
        def producer(case, arm, repeat):
            tag = arm + ("-repeat" if repeat else "")
            self.builder.capture(arm, repeat, case=case)
            # Lie about where the capture landed: outside the custody root.
            return self.source / "source" / "case-9999" / tag
        record = I.run_integration_278(self.source, self.staged, producer,
                                       self.executor, self.compare)
        self.assertEqual(record["status"], "blocked")
        self.assertTrue(any("custody" in p for p in record["problems"]))
        self.assertEqual(tuple(record["stages"]), ("capture",))
        staged_entries = list(self.staged.rglob("*")) if self.staged.exists() else []
        self.assertEqual(staged_entries, [])
        self.assertEqual(self.launches, [])

    def test_custody_tamper_between_capture_and_staging_fails_closed(self):
        # Tamper a retained original of the FIRST unit while the LAST unit
        # is being captured: staging/admission must refuse the edited bytes.
        first = "source/case-256/reference/receipt.json"
        producer = self.produce(
            tamper_after=(12, first, b'{"forged": true}\n'))
        record = self.run_gate(producer=producer)
        self.assertEqual(record["status"], "blocked")
        self.assertTrue(any("integrity" in p or "custody" in p or "mismatch" in p
                            for p in record["problems"]))
        self.assertEqual(self.launches, [])

    def test_custody_row_drift_blocks_reference_first_zero_launches(self):
        producer = self.produce(drift=("case-3072", "reference", True))
        record = self.run_gate(producer=producer)
        self.assertEqual(record["status"], "blocked")
        orch = record["orchestration"]
        self.assertEqual(orch["terminal"], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273)
        self.assertEqual(record["candidate_launches"], 0)
        self.assertEqual(self.launches, [])
        self.assertEqual(self.comparisons, [])

    def test_reevaluation_rejects_staged_and_custody_tamper(self):
        record = self.run_gate()
        self.assertEqual(record["status"],
                         "integration complete (tooling/fixture validation only)")
        # Staged-side tamper after a completed integrated run.
        staged_row = self.staged / "units/case-1024/candidate/rows/7.f32"
        staged_row.write_bytes(fixture_row("candidate", "7")[::-1])
        reeval = I.evaluate_278(self.staged, self.source, self.executor, self.compare)
        self.assertEqual(reeval["status"], "blocked")
        self.assertEqual(reeval["orchestration"]["terminal"],
                         R.TERMINAL_RUNTIME_BLOCKED_273)
        # Restore the staged bytes so the custody-side probe is NOT
        # confounded by the staged-side corruption above.
        staged_row.write_bytes(fixture_row("candidate", "7"))
        reeval_clean = I.evaluate_278(self.staged, self.source, self.executor,
                                      self.compare)
        self.assertEqual(reeval_clean["status"],
                         "integration complete (tooling/fixture validation only)")
        # Custody-side tamper after a completed integrated run.
        (self.source / "source/case-256/reference/rows/0.f32").write_bytes(
            fixture_row("reference", "0")[::-1])
        reeval2 = I.evaluate_278(self.staged, self.source, self.executor, self.compare)
        self.assertEqual(reeval2["status"], "blocked")
        self.assertEqual(reeval2["orchestration"]["terminal"],
                         R.TERMINAL_RUNTIME_BLOCKED_273)

    def test_blocked_record_reports_observed_launches_and_evidence_label(self):
        # Executor records its invocation then raises: the blocked record
        # must report the launch that ACTUALLY happened, and every record
        # (blocked or not) carries the tooling/fixture evidence label.
        def raising_executor(case):
            self.launches.append(case)
            if case == C.FIXTURE_CASES[1]:
                raise RuntimeError("recording fake failed mid-campaign")
            return {}
        record = I.run_integration_278(self.source, self.staged,
                                       self.produce(), raising_executor,
                                       self.compare)
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["candidate_launches"], 1)
        self.assertEqual(self.launches, [C.FIXTURE_CASES[0]])
        self.assertEqual(record["evidence_class"], "tooling/fixture validation")
        # Same honesty on the reevaluation path: a staged-side tamper that
        # reaches execution reports the launches that occurred.
        self.launches.clear()
        ok = self.run_gate()
        self.assertEqual(ok["status"],
                         "integration complete (tooling/fixture validation only)")
        (self.staged / "units/case-1024/candidate/rows/7.f32").write_bytes(
            fixture_row("candidate", "7")[::-1])
        reeval = I.evaluate_278(self.staged, self.source, self.executor,
                                self.compare)
        self.assertEqual(reeval["status"], "blocked")
        self.assertEqual(reeval["candidate_launches"], len(self.launches))
        self.assertEqual(reeval["evidence_class"], "tooling/fixture validation")

    def test_executor_custody_tamper_blocks_at_final_verification(self):
        # The executor runs AFTER reference admission: custody mutated
        # there must invalidate the run at a final custody verification,
        # not survive to completion with a stale record.
        def tampering_executor(case):
            self.launches.append(case)
            if case == C.FIXTURE_CASES[0]:
                row = self.source / "source/case-256/reference/rows/0.f32"
                row.write_bytes(fixture_row("reference", "0")[::-1])
            return {}
        record = I.run_integration_278(self.source, self.staged,
                                       self.produce(), tampering_executor,
                                       self.compare)
        self.assertEqual(record["status"], "blocked")
        self.assertTrue(any("custody" in p for p in record["problems"]))
        self.assertEqual(record["candidate_launches"], 1)

    def test_comparison_callback_custody_tamper_blocks(self):
        # The LAST callback in the chain: custody mutated after all
        # admission must still invalidate the completed record.
        def tampering_compare(case, reference, candidate):
            self.comparisons.append(case)
            if case == C.FIXTURE_CASES[-1]:
                row = self.source / "source/case-3072/candidate/rows/2.f32"
                row.write_bytes(fixture_row("candidate", "2")[::-1])
            return {}
        record = I.run_integration_278(self.source, self.staged,
                                       self.produce(), self.executor,
                                       tampering_compare)
        self.assertEqual(record["status"], "blocked")
        self.assertTrue(any("custody" in p for p in record["problems"]))
        self.assertEqual(record["candidate_launches"], len(C.FIXTURE_CASES))

    def test_evaluate_278_asserts_reducer_fail_closed(self):
        from unittest.mock import patch
        self.fixture = None  # unused guard
        ok = self.run_gate()
        self.assertEqual(ok["status"],
                         "integration complete (tooling/fixture validation only)")
        forged_pass = {"terminal": R.TERMINAL_PASS_273, "problems": []}
        with patch.object(I.R, "derive_terminal_273", return_value=forged_pass):
            reeval = I.evaluate_278(self.staged, self.source, self.executor,
                                    self.compare)
        self.assertEqual(reeval["status"], "blocked")
        self.assertTrue(any("physical terminal authority" in p
                            for p in reeval["problems"]))

    def test_forged_verdicts_cannot_mint_physical_terminal(self):
        record = self.run_gate()
        cases = tuple(C.FIXTURE_CASES)
        forged_admissions = {case: {"admitted": True, "schema": "forged",
                                    "case_id": case} for case in cases}
        forged_determinism = {case: {"reference": True, "candidate": True}
                              for case in cases}
        for admissions, determinism in ((record, record),
                                        (forged_admissions, forged_determinism)):
            with self.subTest(forged=admissions is not record):
                terminal = R.derive_terminal_273(admissions, determinism)
                self.assertEqual(terminal["terminal"], R.TERMINAL_RUNTIME_BLOCKED_273)
                self.assertTrue(terminal["problems"])

    def test_signature_rejects_authored_verdict_parameters(self):
        import inspect
        params = inspect.signature(I.run_integration_278).parameters
        for forbidden in ("admitted", "deterministic", "verdict", "terminal"):
            self.assertNotIn(forbidden, params)

    def test_first_demonstration_matching_and_fail_closed(self):
        matching = self.run_gate()
        print("\n[issue278 first demonstration] matching fixture:")
        for name, stage in matching["stages"].items():
            print(f"  stage {name}: {I.compact_stage(stage)}")
        self.assertEqual(matching["status"],
                         "integration complete (tooling/fixture validation only)")
        self.launches.clear()
        self.comparisons.clear()
        with tempfile.TemporaryDirectory() as td:
            self.source = Path(td) / "capture"
            self.staged = Path(td) / "staged"
            self.builder = BundleBuilder(self.source)
            blocked = self.run_gate(
                producer=self.produce(drift=("case-3072", "reference", True)))
            print("[issue278 first demonstration] fail-closed fixture:")
            print(f"  status={blocked['status']} "
                  f"launches={blocked['candidate_launches']}")
            self.assertEqual(blocked["orchestration"]["terminal"],
                             R.TERMINAL_REFERENCE_NONDETERMINISTIC_273)
            self.assertEqual(blocked["candidate_launches"], 0)


if __name__ == "__main__":
    unittest.main()
