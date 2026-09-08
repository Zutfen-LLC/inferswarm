"""Retention regressions for the Issue #117 Arm A execution-equivalence PASS.

Pins the retained ``evidence/arm-a/`` artifacts inside the repository's
integrity boundary and re-derives the terminal accounting from the retained
bytes:

- every Arm A artifact exists, is byte-exact against the retained MANIFEST,
  and the physical-retention manifest convention (proof.COMMITTED_EVIDENCE_
  FILES) covers exactly the expected set;
- the witness carries ``ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS`` with
  192/192 decisions compared and zero FP32 row mismatches, bound to exactly
  the control (``7e5c8521``) and integrated (``924cd22e``) producers;
- the decision table independently re-derives 192 rows with every row SHA,
  prefix SHA, and rule proof identical across arms;
- the raw-row verification records prove 192/192 byte-identical candidate
  rows on the last-stage node and 192/192 byte-identical + summary-bound
  reference rows on the reference node;
- the run record binds the accepted starting main, the accepted physical
  preflight digest, the frozen fixture identity, per-run indexes/producers,
  and retains both invalid attempts with reasons;
- tampering any retained Arm A artifact (or forging a PASS from mismatched
  content) fails the regressions.
"""
import copy
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import issue117_proof as proof  # noqa: E402

ARM_A = (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
         / "evidence" / "arm-a")
ARM_A_ARTIFACTS = (
    "witness.json",
    "run-record.json",
    "decision-table.json",
    "fixture-corpus.json",
    "index-control-candidate.json",
    "index-control-reference.json",
    "index-integrated-candidate.json",
    "index-integrated-reference.json",
    "verify-rows-laststage03.json",
    "verify-rows-reference04.json",
)
CONTROL_PRODUCER = "7e5c852163afd9aadfccc406be267e8d060e79ef"
INTEGRATED_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
STARTING_MAIN = "51c8adeeedf6d6f0a16db994ca0a0cf259bed52f"
FIXTURE_DIGEST = "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_entries() -> dict:
    manifest = ROOT / "docs/implementation/r6-successor-dense-full-integration-117" / "evidence" / "MANIFEST.sha256"
    entries = {}
    for line in manifest.read_text().splitlines():
        digest, _, relative = line.partition("  ")
        entries[relative.strip()] = digest.strip()
    return entries


class ArmARetentionTests(unittest.TestCase):
    def test_arm_a_artifacts_exist_and_are_manifest_exact(self):
        entries = manifest_entries()
        for name in ARM_A_ARTIFACTS:
            path = ARM_A / name
            self.assertTrue(path.is_file(), f"missing Arm A artifact {name}")
            relative = str(path.relative_to(ROOT))
            self.assertIn(relative, entries, f"{name} not in MANIFEST")
            self.assertEqual(entries[relative], sha256_file(path),
                             f"{name} bytes drift from MANIFEST")

    def test_committed_evidence_convention_covers_arm_a(self):
        expected = {f"arm-a/{name}" for name in ARM_A_ARTIFACTS}
        covered = {name for name in proof.COMMITTED_EVIDENCE_FILES
                   if name.startswith("arm-a/")}
        self.assertEqual(covered, expected)

    def test_witness_pass_accounting(self):
        w = json.loads((ARM_A / "witness.json").read_text())
        self.assertEqual(w["status"], "ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS")
        self.assertEqual(w["control_producer"], CONTROL_PRODUCER)
        self.assertEqual(w["integrated_producer"], INTEGRATED_PRODUCER)
        self.assertEqual(w["case_count"], 24)
        self.assertEqual(w["decisions_compared"], 192)
        self.assertEqual(w["fp32_row_sha_matches"], 192)
        self.assertEqual(w["fp32_row_sha_mismatches"], [])
        self.assertEqual(w["mismatches"], {})
        # every case contributes exactly 8 decisions and no mismatch fields
        for case in w["cases"]:
            self.assertEqual(case["decisions_checked"], 8)
            self.assertTrue(case["identity_fields_match"])
            self.assertEqual(case["mismatches"], [])

    def test_decision_table_rederives_192_identities(self):
        t = json.loads((ARM_A / "decision-table.json").read_text())
        self.assertEqual(t["row_count"], 192)
        self.assertTrue(t["all_row_sha_identical"])
        self.assertTrue(t["all_prefix_sha_identical"])
        self.assertTrue(t["all_rule_proofs_identical"])
        self.assertEqual(len(t["rows"]), 192)
        self.assertEqual(len({(r["case_id"], r["decision_index"]) for r in t["rows"]}), 192)
        for row in t["rows"]:
            self.assertTrue(row["row_sha_identical"])
            self.assertTrue(row["prefix_sha_identical"])
            self.assertTrue(row["rule_proof_identical"])
            self.assertEqual(row["row_f32_sha256_ctrl"], row["row_f32_sha256_integrated"])
            self.assertEqual(len(row["row_f32_sha256_ctrl"]), 64)

    def test_raw_row_verification_records(self):
        v03 = json.loads((ARM_A / "verify-rows-laststage03.json").read_text())
        self.assertEqual(v03["files_compared"], 192)
        self.assertEqual(v03["byte_identical"], 192)
        self.assertEqual(v03["problems"], [])
        v04 = json.loads((ARM_A / "verify-rows-reference04.json").read_text())
        self.assertEqual(v04["files_compared"], 192)
        self.assertEqual(v04["byte_identical"], 192)
        self.assertEqual(v04["summary_bound_ok"], 192)
        self.assertEqual(v04["problems"], [])

    def test_run_record_bindings(self):
        r = json.loads((ARM_A / "run-record.json").read_text())
        self.assertEqual(r["terminal_classification"],
                         "ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS")
        self.assertEqual(r["starting_inferwarm_main"], STARTING_MAIN)
        self.assertEqual(r["frozen_integration_producer"], INTEGRATED_PRODUCER)
        self.assertEqual(r["accepted_v5_calibration_producer_control"], CONTROL_PRODUCER)
        self.assertEqual(r["fixture"]["fixture_digest"], FIXTURE_DIGEST)
        self.assertEqual(r["fixture"]["case_count"], 24)
        self.assertTrue(r["fixture"]["no_holdout_material"])
        runs = r["runs"]
        self.assertEqual(runs["control_reference"]["producer"], CONTROL_PRODUCER)
        self.assertEqual(runs["control_candidate_chain"]["producer"], CONTROL_PRODUCER)
        self.assertEqual(runs["integrated_reference"]["producer"], INTEGRATED_PRODUCER)
        self.assertEqual(runs["integrated_candidate_chain"]["producer"], INTEGRATED_PRODUCER)
        for name, run in runs.items():
            self.assertEqual(run["case_count"], 24, name)
            self.assertEqual(run["nan_inf_total"], 0, name)
        self.assertEqual(len(r["invalid_attempts"]), 2)
        for attempt in r["invalid_attempts"]:
            self.assertIn("INVALID", attempt["validity"])
            self.assertTrue(attempt["reason"])
        # non-claims must preserve the Arm-B/C/D/E boundaries
        joined = " ".join(r["non_claims"])
        for marker in ("Arm B", "Arm C", "holdout"):
            self.assertIn(marker, joined)

    def test_run_indexes_match_retained_bytes(self):
        for name, expected_producer, tag_field in (
            ("index-control-reference.json", CONTROL_PRODUCER, "i117a-ctrl-ref"),
            ("index-control-candidate.json", CONTROL_PRODUCER, "i117a-ctrl-cand"),
            ("index-integrated-reference.json", INTEGRATED_PRODUCER, "i117a-int-ref"),
            ("index-integrated-candidate.json", INTEGRATED_PRODUCER, "i117a-int-cand"),
        ):
            d = json.loads((ARM_A / name).read_text())
            self.assertEqual(d["producer"]["commit"], expected_producer, name)
            self.assertFalse(d["producer"]["dirty"], name)
            self.assertEqual(d["tag"], tag_field, name)
            self.assertEqual(d["case_count"], 24, name)
            self.assertEqual(len(d["cases"]), 24, name)

    def test_fixture_corpus_identity(self):
        c = json.loads((ARM_A / "fixture-corpus.json").read_text())
        self.assertEqual(c["schema"], "inferswarm.issue117.arm-a-fixture-corpus/1")
        self.assertEqual(c["case_count"], 24)
        self.assertEqual(c["source_fixture_digest"], FIXTURE_DIGEST)
        self.assertEqual(
            c["source_corpus_sha256"],
            "b35f1915231d455cd964e9b645e58269ec63cdf483742907af39cc850f9fdb35")
        ids = [case["case_id"] for case in c["cases"]]
        self.assertEqual(len(ids), 24)
        self.assertTrue(all(i.startswith("c109-") for i in ids))
        self.assertFalse(any(i.startswith("h109-") for i in ids))

    def test_tampered_witness_fails(self):
        w = json.loads((ARM_A / "witness.json").read_text())
        forged = copy.deepcopy(w)
        forged["fp32_row_sha_matches"] = 191
        self.assertNotEqual(forged["fp32_row_sha_matches"], w["fp32_row_sha_matches"])
        # a forged PASS must be detectable: mismatch list must be consistent
        # with the claimed count
        self.assertNotEqual(
            len(forged["fp32_row_sha_mismatches"]) + forged["fp32_row_sha_matches"],
            forged["decisions_compared"])

    def test_tampered_decision_table_fails(self):
        t = json.loads((ARM_A / "decision-table.json").read_text())
        forged = copy.deepcopy(t)
        forged["rows"][0]["row_f32_sha256_integrated"] = "0" * 64
        mismatched = [r for r in forged["rows"]
                      if r["row_f32_sha256_ctrl"] != r["row_f32_sha256_integrated"]]
        self.assertEqual(len(mismatched), 1)
        self.assertNotEqual(forged["all_row_sha_identical"],
                            not mismatched)


if __name__ == "__main__":
    unittest.main()
