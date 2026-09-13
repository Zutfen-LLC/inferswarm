"""InferSwarm #168 — Arm-C post-SWA requalification blocked record tests.

CPU-only, pure stdlib. Every fact asserted here is re-derived from
hash-pinned committed bytes (the census, the authority record, the
accepted fixture/corpus bytes), never from narrative. Negative controls
mutate copies of the real records and require the terminal reducer to
fail closed on exactly the mutated check.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / (
    "docs/implementation/r6-successor-arm-c-requal-blocked-168")
EVIDENCE = BUNDLE / "evidence"
CENSUS = EVIDENCE / "corpus-census.json"
AUTHORITY = EVIDENCE / "authority-record.json"
TERMINAL = EVIDENCE / "terminal-reduction.json"
CORPUS = ROOT / "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json"
FIXTURE = ROOT / (
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-retry/prompt-fixture.json")

SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_reducer():
    spec = importlib.util.spec_from_file_location(
        "issue168_terminal_reduction",
        SCRIPTS / "issue168_terminal_reduction.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REDUCER = load_reducer()

ACCEPTED_FIXTURE_DIGEST = (
    "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2")
ISSUE168_HEADS = {
    "inferswarm_main": "00140a14e3ecbbbd64fdaf1803fe3922e7f4a554",
    "freetoken_inferswarm_research":
        "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469",
    "freetoken_implementation_166":
        "64a37a1f1a2797a190610c5adcdcb4157bce63b9",
}
STAGE_RUNTIME_SHA_166 = (
    "afe9ceb09208174d0da2905d4097009460d05bbe5050b0d15eaa2baa4e40ac73")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _with_mutated_census(mutator, tmpdir: Path) -> Path:
    doc = json.loads(CENSUS.read_text())
    mutator(doc)
    out = tmpdir / "corpus-census.json"
    out.write_text(json.dumps(doc, sort_keys=True, indent=1))
    (tmpdir / "authority-record.json").write_text(AUTHORITY.read_text())
    return tmpdir


def _with_mutated_authority(mutator, tmpdir: Path) -> Path:
    doc = json.loads(AUTHORITY.read_text())
    mutator(doc)
    out = tmpdir / "authority-record.json"
    out.write_text(json.dumps(doc, sort_keys=True, indent=1))
    (tmpdir / "corpus-census.json").write_text(CENSUS.read_text())
    return tmpdir


class CensusCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(CENSUS.read_text())
        cls.corpus = json.loads(CORPUS.read_text())
        cls.fixture = json.loads(FIXTURE.read_text())

    def test_schema_and_salt(self):
        self.assertEqual(
            self.doc["schema"],
            "inferswarm.issue168.arm-c-requal-corpus-census/1")
        self.assertEqual(
            self.doc["salt"], "issue168-arm-c-post-swa-requal-v1")

    def test_corpus_pin(self):
        self.assertEqual(
            self.doc["corpus"]["file_sha256"],
            "sha256:" + _sha(CORPUS))
        self.assertEqual(self.doc["corpus"]["case_count"], 1416)
        self.assertEqual(self.doc["corpus"]["case_id_prefixes"], ["c109"])

    def test_regression_fixture_binding(self):
        binding = self.doc["regression_fixture"]
        self.assertEqual(
            binding["accepted_fixture_digest"], ACCEPTED_FIXTURE_DIGEST)
        self.assertEqual(binding["renders_reproduced"], 24)
        self.assertEqual(
            set(binding["case_ids"]),
            {c["case_id"] for c in self.fixture["cases"]})

    def test_pool_excludes_fixture_and_covers_corpus(self):
        fixture_ids = {c["case_id"] for c in self.fixture["cases"]}
        per_case_ids = [r["case_id"] for r in
                        self.doc["per_case_rendered_lengths"]]
        self.assertEqual(set(per_case_ids),
                         {c["case_id"] for c in self.corpus["cases"]})
        # no fixture case appears as an eligible member anywhere
        for reading in self.doc["eligibility_readings"].values():
            for members in reading["members"].values():
                for m in members:
                    self.assertNotIn(m["case_id"], fixture_ids)

    def test_max_rendered_len_bound(self):
        self.assertLessEqual(self.doc["max_rendered_len_corpus"], 69)
        # raw regimes cap at 56; wrapper adds at most 13
        raw_max = max(c["token_count"] for c in self.corpus["cases"])
        self.assertLessEqual(self.doc["max_rendered_len_corpus"],
                             raw_max + 13)

    def test_upper_buckets_empty_under_both_readings(self):
        for name, reading in self.doc["eligibility_readings"].items():
            counts = reading["eligible_counts"]
            self.assertEqual(counts["25-48"], 0, name)
            self.assertEqual(counts["49-64"], 0, name)
            self.assertIn("25-48", reading["insufficient_buckets"], name)
            self.assertIn("49-64", reading["insufficient_buckets"], name)

    def test_members_carry_selection_keys_sorted(self):
        for name, reading in self.doc["eligibility_readings"].items():
            for bucket, members in reading["members"].items():
                keys = [m["selection_key_sha256"] for m in members]
                self.assertEqual(keys, sorted(keys), f"{name}/{bucket}")
                self.assertEqual(
                    len(members), reading["eligible_counts"][bucket],
                    f"{name}/{bucket}")

    def test_non_claims_present(self):
        claims = " ".join(self.doc["non_claims"])
        self.assertIn("no model execution", claims)
        self.assertIn("no h109-*", claims)


class AuthorityCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(AUTHORITY.read_text())

    def test_campaign_ids_fresh_and_bound(self):
        self.assertEqual(
            self.doc["campaign_id"], "issue168-arm-c-post-swa-requal-v1")
        self.assertTrue(self.doc["physical_authorization_id"].startswith(
            "physical-authorization-issue168-"))

    def test_heads_are_issue_named_heads(self):
        heads = self.doc["starting_heads"]
        self.assertTrue(heads["verified"])
        self.assertEqual(
            heads["expected_inferswarm_main"],
            ISSUE168_HEADS["inferswarm_main"])
        self.assertEqual(
            heads["expected_freetoken_inferswarm_research"],
            ISSUE168_HEADS["freetoken_inferswarm_research"])
        self.assertTrue(all(
            heads["ancestor_proofs"].values()))

    def test_subject_matches_accepted_117(self):
        subject = self.doc["subject"]
        self.assertEqual(subject["model"], "google/gemma-4-12B-it")
        self.assertEqual(
            subject["revision"],
            "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7")
        self.assertEqual(
            subject["checkpoint_sha256"],
            "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d")
        self.assertEqual(subject["candidate"], "dense.6171f32b4413")
        self.assertIn("inferswarm01/gpu-0 [0,16)", subject["geometry"])
        self.assertEqual(subject["chunk_boundary_contract"],
                         "64 rows per prefill call")

    def test_166_delta_bounds_stage_runtime_change(self):
        audit = self.doc["execution_delta_audit"]
        self.assertEqual(
            audit["stage_runtime_sha256_at_166"], STAGE_RUNTIME_SHA_166)
        execution = audit["changed_files_by_class"]["execution_bearing"]
        self.assertIn(
            "benchmarks/inferswarm_r6/stage_runtime.py", execution)
        # the #166 step itself (64a37a1..6202eee) only touched
        # stage_runtime + its test
        self.assertEqual(
            audit["producer_lineage"][-2:],
            [ISSUE168_HEADS["freetoken_implementation_166"],
             ISSUE168_HEADS["freetoken_inferswarm_research"]])

    def test_no_execution_claim(self):
        state = self.doc["preflight_state"]
        self.assertEqual(state["phase_reached"], "phase-1-corpus-freeze")
        self.assertFalse(state["physical_execution_performed"])
        self.assertFalse(state["outputs_inspected"])
        self.assertFalse(state["h109_material_accessed"])
        self.assertIn("NOT answered", " ".join(self.doc["non_claims"]))


class TerminalCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(TERMINAL.read_text())

    def test_terminal_is_mandated_blocked(self):
        self.assertEqual(
            self.doc["verdict"],
            "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED")
        self.assertEqual(
            self.doc["classification_basis"],
            "corpus_insufficiency_pre_observation")

    def test_terminal_derives_not_authored(self):
        result = REDUCER.reduce_terminal(EVIDENCE)
        self.assertEqual(
            result["verdict"], self.doc["verdict"])
        self.assertEqual(result["detail"], self.doc["detail"])


class NegativeControls(unittest.TestCase):
    """Each control mutates ONE thing in a copy of the real evidence and
    requires the reducer to fail closed or change verdict."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmpdir = Path(self.tmp)

    def test_mutated_count_fails_closed(self):
        def mutate(doc):
            doc["eligibility_readings"]["prompt_two_chunk"][
                "eligible_counts"]["1-8"] = 999
        directory = _with_mutated_census(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("recomputation" in f for f in result["failures"]))

    def test_fake_eligible_member_rejected(self):
        def mutate(doc):
            members = doc["eligibility_readings"]["prompt_two_chunk"][
                "members"]["49-64"]
            members.append({
                "case_id": "c109-04-06-074",
                "rendered_len": 67, "effective_len": 67,
                "second_chunk_remainder": 3,
                "selection_key_sha256": "0" * 64,
                "rendered_prompt_token_ids": [2]})
        directory = _with_mutated_census(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("recomputation" in f or "counts" in f
                            for f in result["failures"]))

    def test_wrong_bucket_membership_rejected(self):
        def mutate(doc):
            members = doc["eligibility_readings"]["prompt_two_chunk"][
                "members"]["1-8"]
            members[0]["second_chunk_remainder"] = 30
        directory = _with_mutated_census(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("bucket membership" in f
                            for f in result["failures"]))

    def test_per_case_length_drift_rejected(self):
        def mutate(doc):
            # inflate one case's rendered length into an upper bucket
            for row in doc["per_case_rendered_lengths"]:
                if not row["in_regression_fixture"]:
                    row["rendered_len"] = 120
                    break
        directory = _with_mutated_census(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("recomputation" in f for f in result["failures"]))

    def test_sufficient_corpus_changes_verdict_not_passes(self):
        def mutate(doc):
            # hypothetically populate upper buckets consistently
            reading = doc["eligibility_readings"]["prompt_two_chunk"]
            pool_rows = [r for r in doc["per_case_rendered_lengths"]
                         if not r["in_regression_fixture"]]
            for bucket, count in (("25-48", 4), ("49-64", 4), ("9-24", 4)):
                rows = pool_rows[:count]
                for row in rows:
                    row["rendered_len"] = 64 + (
                        30 if bucket == "25-48" else
                        55 if bucket == "49-64" else 12)
                pool_rows = pool_rows[count:]
                reading["members"][bucket] = [
                    {"case_id": r["case_id"],
                     "rendered_len": r["rendered_len"],
                     "effective_len": r["rendered_len"],
                     "second_chunk_remainder": r["rendered_len"] - 64,
                     "selection_key_sha256": "0" * 64,
                     "rendered_prompt_token_ids": [2]}
                    for r in rows]
                reading["eligible_counts"][bucket] = count
            reading["insufficient_buckets"] = []
            doc["eligibility_readings"]["final_replay_crossing"][
                "insufficient_buckets"] = []
        directory = _with_mutated_census(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        # the mutated census is internally consistent for the strict
        # reading but the generous reading still recomputes empty upper
        # buckets -> fail closed OR sufficient -> no execution verdict
        self.assertIn(result["verdict"], (
            "REDUCTION_FAILED", "CORPUS_SUFFICIENT_CAMPAIGN_UNEXECUTED"))
        self.assertNotEqual(
            result["verdict"], "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED")

    def test_authority_claims_execution_rejected(self):
        def mutate(doc):
            doc["preflight_state"]["physical_execution_performed"] = True
        directory = _with_mutated_authority(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("physical execution" in f
                            for f in result["failures"]))

    def test_authority_h109_access_rejected(self):
        def mutate(doc):
            doc["preflight_state"]["h109_material_accessed"] = True
        directory = _with_mutated_authority(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("h109" in f for f in result["failures"]))

    def test_fixture_digest_drift_rejected(self):
        def mutate(doc):
            doc["regression_fixture"]["accepted_fixture_digest"] = (
                "sha256:" + "0" * 64)
        directory = _with_mutated_census(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("fixture digest" in f
                            for f in result["failures"]))

    def test_census_authority_binding_drift_rejected(self):
        def mutate(doc):
            doc["fresh_corpus_census"]["insufficient_buckets"] = {}
        directory = _with_mutated_authority(mutate, self.tmpdir)
        result = REDUCER.reduce_terminal(directory)
        self.assertEqual(result["verdict"], "REDUCTION_FAILED")
        self.assertTrue(any("insufficient-bucket drift" in f
                            for f in result["failures"]))


class PredecessorPreservation(unittest.TestCase):
    def test_accepted_166_bundle_bytes_unchanged(self):
        bundle_166 = ROOT / (
            "docs/implementation/r6-successor-arm-c-swa-remediation-166")
        manifest = {}
        for line in (
                bundle_166 / "evidence" / "MANIFEST.sha256").read_text(
                ).splitlines():
            if line.strip():
                digest, path = line.split(None, 1)
                manifest[path.strip()] = digest
        for path, digest in manifest.items():
            self.assertEqual(
                _sha(ROOT / path), digest,
                f"accepted #166 evidence byte drift: {path}")

    def test_accepted_133_fixture_bytes_unchanged(self):
        # the accepted fixture file hash is pinned by its own manifest
        # suite; assert it is still readable and structurally intact
        doc = json.loads(FIXTURE.read_text())
        self.assertEqual(doc["case_count"], 24)
        self.assertEqual(
            doc["authority"]["accepted_fixture_digest"],
            ACCEPTED_FIXTURE_DIGEST)


if __name__ == "__main__":
    unittest.main()
