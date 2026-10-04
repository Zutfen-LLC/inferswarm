"""Round-3 regressions for caller-controlled admission and terminal authority.

CPU-only tests. These target the remaining production trust boundaries, not
physical execution or sealed/holdout evidence.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import issue273_admission as A  # noqa: E402
import issue273_reducer as R  # noqa: E402
import test_issue273_admission as F  # noqa: E402
import issue273_evidence as E  # noqa: E402


class Round3TrustBoundaryTests(unittest.TestCase):
    def test_evidence_root_producer_is_available_and_requires_independent_anchor(self):
        self.assertTrue(callable(getattr(E, "produce_terminal_273", None)))
        with self.assertRaises(E.EvidenceError):
            E.produce_terminal_273(Path("/nonexistent"), expected_head="a" * 40)

    def _pair(self, mismatch_reference_repeat=False):
        ref = F.staged_receipt(
            F.GENUINE_NVIDIA_REF,
            F.make_process(A.expected_icd("reference"), 8, 61001,
                           "inferswarm01"), F._rows(b"r-primary"))
        cand = F.staged_receipt(
            F.CANDIDATE,
            F.make_process(A.expected_icd("candidate"), 7, 62001,
                           "inferswarm05"), F._rows(b"c-primary"))
        ref_rep = F.staged_receipt(
            F.GENUINE_NVIDIA_REF,
            F.make_process(A.expected_icd("reference"), 8, 61002,
                           "inferswarm01"),
            F._rows(b"r-mismatch" if mismatch_reference_repeat else b"r-primary"))
        cand_rep = F.staged_receipt(
            F.CANDIDATE,
            F.make_process(A.expected_icd("candidate"), 7, 62002,
                           "inferswarm05"), F._rows(b"c-primary"))
        rd, rr = F.source_digests_of(ref)
        cd, cr = F.source_digests_of(cand)
        return ref, cand, ref_rep, cand_rep, rd, rr, cd, cr

    def test_caller_determinism_boolean_cannot_admit_mismatched_repeat_bytes(self):
        ref, cand, ref_rep, cand_rep, rd, rr, cd, cr = self._pair(True)
        verdict = A.admit_pair(
            ref, F.as_source(ref), cand, F.as_source(cand), ref_rep, cand_rep,
            reference_deterministic=True, candidate_deterministic=True,
            reference_source_digest=rd, reference_source_row_digests=rr,
            candidate_source_digest=cd, candidate_source_row_digests=cr)
        self.assertFalse(verdict["admitted"],
                         "determinism must be derived from retained repeat bytes")

    def test_schema_shaped_admission_dict_cannot_mint_terminal_pass(self):
        cases = ("case-256", "case-1024", "case-3072")
        forged = {case: {"schema": A.SCHEMA, "case_id": case,
                         "admitted": True, "problems": []}
                  for case in cases}
        det = {case: {"reference": True, "candidate": True} for case in cases}
        result = R.derive_terminal_273(forged, det)
        self.assertNotEqual(result["terminal"], R.TERMINAL_PASS_273,
                            "caller-authored schema fields are not evidence")

    def test_caller_dispatch_claim_cannot_authenticate_maintainer_comment(self):
        doc = {"schema": R.DISPATCH_SCHEMA, "issue": 273,
               "dispatch_phrase": R.DISPATCH_PHRASE_273,
               "head_sha": "a" * 40, "namespace": R.NAMESPACE_273,
               "commenter_association": "OWNER", "comment_id": 1,
               "commenter": "attacker", "tooling_merged": True}
        with self.assertRaises(R.ReducerError):
            R.validate_dispatch_273(doc, "a" * 40)


if __name__ == "__main__":
    unittest.main()
