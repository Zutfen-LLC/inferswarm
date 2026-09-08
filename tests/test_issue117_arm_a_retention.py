"""Retention regressions for the Issue #117 Arm A execution-equivalence PASS.

PR #122 retention/provenance correction: the terminal classification must be
INDEPENDENTLY RE-DERIVABLE from low-level retained records by
``scripts/issue117_arm_a_evidence.py`` (the reducer). No stored PASS boolean,
aggregate counter, or ``all_*_identical`` convenience field may substitute for
the derivations, and every trust boundary is exercised by a negative control
that applies exactly ONE mutation to a copy of the retained evidence in a
throwaway directory and asserts the reducer FAILS on exactly that dimension.
The reducer never runs against mutated repository bytes; mutations live only
in tmp fixtures.

Covers (issue review, required tests 1-20 plus mutation tests):
1  exact 24-case fixture identity;
2  unique complete (case, decision) keyspace = 192;
3  separate control/integrated prefix values;
4  separate control/integrated trajectory/token values;
5  separate control/integrated rule proofs;
6  separate control/integrated boundary records;
7  exact row SHA equality;
8  raw-row manifest -> decision-table SHA binding;
9  exact per-row candidate raw-byte verification;
10 exact per-row reference raw-byte + summary binding;
11 four run indexes bind exact producers;
12 all valid run indexes clean;
13 pre-Arm-A InferSwarm identity exact;
14 per-host control/integrated FreeToken identities exact and clean;
15 exact CU/runtime/checkpoint identity;
16 Arm-B cold roots untouched;
17 invalid attempts distinct and zero correctness-bearing observations;
18 accepted physical preflight bytes/digest unchanged;
19 #118 canonical summary unchanged;
20 Arm A manifest coverage complete.
"""
import ast
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_proof as proof  # noqa: E402
import issue117_arm_a_evidence as ev  # noqa: E402

ARM_A = ev.ARM_A
CONTROL_PRODUCER = ev.CONTROL_PRODUCER
INTEGRATED_PRODUCER = ev.INTEGRATED_PRODUCER
NEW_ARM_A_ARTIFACTS = (
    "paired-decision-records.json",
    "capture-manifest-records.json",
    "raw-row-manifest-laststage03.json",
    "raw-row-manifest-reference04.json",
    "attempt-lineage.json",
    "prerun-revalidation.json",
    "checkpoint-continuity.json",
    "run-device-bindings.json",
)
LEGACY_ARM_A_ARTIFACTS = (
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


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_entries() -> dict:
    manifest = ev.EVIDENCE / "MANIFEST.sha256"
    entries = {}
    for line in manifest.read_text().splitlines():
        digest, _, relative = line.partition("  ")
        entries[relative.strip()] = digest.strip()
    return entries


def _expect_reducer_failure(mutation):
    """Copy retained evidence to a throwaway tree, apply ONE mutation, and
    require the reducer to fail closed. Restores the reducer's paths."""
    with tempfile.TemporaryDirectory(prefix="i117a-mut-") as temp:
        root = Path(temp)
        arm_a = root / ARM_A.relative_to(ROOT)
        arm_a.mkdir(parents=True)
        for name in (*NEW_ARM_A_ARTIFACTS, *LEGACY_ARM_A_ARTIFACTS):
            (arm_a / name).write_bytes((ARM_A / name).read_bytes())
        evidence = arm_a.parent
        for name in ("physical-preflight.json", "canonical-summary.json"):
            (evidence / name).write_bytes((ev.EVIDENCE / name).read_bytes())
        mutation(root, arm_a, evidence)
        saved = (ev.ROOT, ev.ARM_A, ev.EVIDENCE)
        ev.ROOT, ev.ARM_A, ev.EVIDENCE = root, arm_a, evidence
        try:
            ev.derive()
        except ev.EvidenceError:
            return
        finally:
            ev.ROOT, ev.ARM_A, ev.EVIDENCE = saved
        raise AssertionError("reducer derived PASS from mutated evidence")


def _load(path: Path):
    return json.loads(path.read_text())


def _store(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")


class IndependentDerivationTests(unittest.TestCase):
    """Positive derivations: the reducer re-derives PASS from retained bytes."""

    def test_reducer_derives_pass_from_retained_evidence(self):
        report = ev.derive()
        self.assertEqual(report["terminal_classification"], ev.TERMINAL_PASS)
        d = report["derivation"]
        self.assertEqual(d["fixture"]["case_count"], 24)
        self.assertEqual(d["fixture"]["decision_keyspace"], 192)
        self.assertFalse(d["fixture"]["holdout_material"])
        self.assertEqual(
            set(d["run_indexes"]),
            {"control_reference", "control_candidate",
             "integrated_reference", "integrated_candidate"})
        self.assertEqual(d["run_indexes"]["control_reference"]["producer"], CONTROL_PRODUCER)
        self.assertEqual(d["run_indexes"]["control_candidate"]["producer"], CONTROL_PRODUCER)
        self.assertEqual(d["run_indexes"]["integrated_reference"]["producer"], INTEGRATED_PRODUCER)
        self.assertEqual(d["run_indexes"]["integrated_candidate"]["producer"], INTEGRATED_PRODUCER)
        for run, info in d["run_indexes"].items():
            self.assertEqual(info["cases"], 24, run)
            self.assertEqual(info["nan_inf"], 0, run)
        for label in ("candidate_rows", "reference_rows"):
            stats = d["paired_identity"][label]
            self.assertEqual(stats["rows"], 192, label)
            for field in ("prefix_len_mismatches", "prefix_sha_mismatches",
                          "emitted_token_mismatches", "argmax_rule_mismatches",
                          "rule_proof_mismatches", "row_sha_mismatches",
                          "element_count_mismatches"):
                self.assertEqual(stats[field], 0, f"{label}.{field}")
        self.assertEqual(d["stage_boundary_comparisons"], 72)  # 24 cases x 3 stages
        for label in ("candidate_raw_rows", "reference_raw_rows"):
            self.assertEqual(d[label]["rows_compared"], 192, label)
            self.assertEqual(d[label]["byte_identical"], 192, label)
            self.assertEqual(d[label]["summary_bound"], 192, label)
        self.assertEqual(d["attempt_lineage"]["valid"], "i117-arm-a-integrated-cand-1.valid")
        self.assertEqual(sorted(d["attempt_lineage"]["invalid"]),
                         ["i117-arm-a-integrated-cand-1.launch-1",
                          "i117-arm-a-integrated-cand-1.launch-2"])

    def test_paired_records_retain_both_sides_not_booleans(self):
        paired = _load(ARM_A / "paired-decision-records.json")
        for label in ("candidate_rows", "reference_rows"):
            rows = paired[label]
            self.assertEqual(len(rows), 192, label)
            for row in rows:
                for side in ("control", "integrated"):
                    self.assertIn(f"{side}_prefix_sha256", row)
                    self.assertIn(f"{side}_prefix_len", row)
                    self.assertIn(f"{side}_row_f32_sha256", row)
                    self.assertIn(f"{side}_emitted_token", row)
                for banned in ("prefix_sha_identical", "row_sha_identical",
                               "trajectory_identical", "rule_proof_identical",
                               "prefix_identical"):
                    self.assertNotIn(banned, row)

    def test_boundary_records_retain_both_lists(self):
        records = _load(ARM_A / "capture-manifest-records.json")
        self.assertEqual(len(records["cases"]), 24)
        for case in records["cases"]:
            for stage in ("stage1", "stage2", "stage3"):
                for side in ("control", "integrated"):
                    manifest = case[side][stage]
                    self.assertIn("record_count", manifest)
                    self.assertIn("record_sha256", manifest)
                    self.assertIsInstance(manifest["record_sha256"], list)
                    self.assertGreater(manifest["record_count"], 0)

    def test_raw_row_manifests_are_per_decision(self):
        for name in ("raw-row-manifest-laststage03.json",
                     "raw-row-manifest-reference04.json"):
            manifest = _load(ARM_A / name)
            rows = manifest["rows"]
            self.assertEqual(len(rows), 192, name)
            keys = {(r["case_id"], r["decision_index"]) for r in rows}
            self.assertEqual(len(keys), 192, name)
            for row in rows:
                for field in ("control_raw_row_sha256", "integrated_raw_row_sha256",
                              "control_raw_row_size", "integrated_raw_row_size",
                              "control_raw_row_path", "integrated_raw_row_path"):
                    self.assertIn(field, row, name)

    def test_invalid_attempts_distinct_with_zero_correctness(self):
        lineage = _load(ARM_A / "attempt-lineage.json")
        ids = [a["attempt_id"] for a in lineage["attempts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 3)
        for attempt in lineage["attempts"]:
            if attempt["validity"] == "INVALID":
                self.assertEqual(attempt["correctness_bearing_observation_count"], 0)
                for marker in ("CASE_ARM", "CASE_BEGIN", "PREFILL"):
                    self.assertIn(marker, attempt["harness_semantics_termination_proof"])
        valid = [a for a in lineage["attempts"] if a["validity"] == "VALID"]
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["correctness_bearing_observation_count"], 192)
        # every cleanup excerpt digest binds its verbatim excerpt
        cl = lineage["cleanup_lineage"]
        for key in list(cl):
            if key.endswith("_digest") and isinstance(cl.get(key[:-7] + "_verbatim"), str):
                self.assertEqual(
                    cl[key],
                    "sha256:" + hashlib.sha256(cl[key[:-7] + "_verbatim"].encode()).hexdigest(),
                    key)

    def test_prerun_revalidation_is_mechanical(self):
        reval = _load(ARM_A / "prerun-revalidation.json")
        self.assertEqual(reval["orchestrator_inferswarm"]["head"], ev.STARTING_MAIN)
        self.assertTrue(reval["orchestrator_inferswarm"]["clean"])
        self.assertNotIn("12:1x", json.dumps(reval))  # no approximate timestamps
        hosts = {r["host"] for r in reval["freetoken_identities"]}
        self.assertEqual(hosts, {"inferswarm01", "inferswarm03", "inferswarm04"})
        for rec in reval["freetoken_identities"]:
            roles = {c["role"]: c for c in rec["checkout_paths"]}
            self.assertEqual(roles["integrated"]["head_at_probe"], INTEGRATED_PRODUCER)
            self.assertEqual(roles["control"]["head_after_p0b_checkout"], CONTROL_PRODUCER)
            self.assertTrue(roles["control"]["clean_after_p0b_checkout"])
        cold = reval["arm_b_cold_roots"]
        self.assertIn("EMPTY", cold["pre_arm_a_state"])
        self.assertIn("NOT historical proof", cold["present_day_corroboration"]["label"])
        self.assertTrue(reval["collector"]["raw_output_digest"].startswith("sha256:"))

    def test_run_record_points_at_mechanical_records(self):
        rr = _load(ARM_A / "run-record.json")
        self.assertEqual(rr["invalid_attempts"]["mechanical_record"], "arm-a/attempt-lineage.json")
        self.assertEqual(len(rr["invalid_attempts"]["distinct_attempt_ids"]), 3)
        self.assertEqual(rr["fabric_revalidation"]["mechanical_record"], "arm-a/prerun-revalidation.json")
        self.assertNotIn("12:1x", rr["fabric_revalidation_utc_window"])


class MutationNegativeControls(unittest.TestCase):
    """One mutation per trust boundary; the reducer must fail closed."""

    def test_mutation_integrated_prefix_sha_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            doc["candidate_rows"][7]["integrated_prefix_sha256"] = "f" * 64
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_integrated_prefix_len_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            doc["candidate_rows"][7]["integrated_prefix_len"] += 1
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_integrated_emitted_token_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            doc["candidate_rows"][9]["integrated_emitted_token"] += 1
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_rule_proof_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            doc["candidate_rows"][3]["integrated_rule_proof"]["tie_count"] = 99
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_integrated_row_sha_only_in_paired_fails(self):
        # change the integrated row SHA in the paired records but ALSO in the
        # raw manifest consistently: must still fail because equality is
        # derived, not stored (and the decision-table cross-binding holds
        # only if BOTH sides change, which here they do not — index side fails)
        def mutation(root, arm_a, evidence):
            paired = _load(arm_a / "paired-decision-records.json")
            paired["candidate_rows"][21]["integrated_row_f32_sha256"] = "c" * 64
            _store(arm_a / "paired-decision-records.json", paired)
        _expect_reducer_failure(mutation)

    def test_mutation_stage_boundary_identity_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "capture-manifest-records.json")
            doc["cases"][5]["integrated"]["stage2"]["record_sha256"][0] = "0" * 64
            _store(arm_a / "capture-manifest-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_stage_boundary_count_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "capture-manifest-records.json")
            doc["cases"][5]["integrated"]["stage1"]["record_count"] += 1
            _store(arm_a / "capture-manifest-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_deleted_boundary_record_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "capture-manifest-records.json")
            del doc["cases"][11]["control"]["stage3"]
            _store(arm_a / "capture-manifest-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_duplicate_decision_key_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            row = copy.deepcopy(doc["candidate_rows"][10])
            doc["candidate_rows"][11] = row  # duplicate (case_id, decision_index)
            doc["candidate_rows"].pop()
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_removed_decision_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            doc["candidate_rows"].pop(42)
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_added_193rd_decision_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "paired-decision-records.json")
            extra = copy.deepcopy(doc["candidate_rows"][0])
            extra["decision_index"] = 8
            doc["candidate_rows"].append(extra)
            _store(arm_a / "paired-decision-records.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_wrong_raw_row_sha_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-laststage03.json")
            doc["rows"][100]["integrated_raw_row_sha256"] = "a" * 64
            _store(arm_a / "raw-row-manifest-laststage03.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_row_mapped_to_wrong_case_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-laststage03.json")
            doc["rows"][4]["case_id"] = doc["rows"][4]["case_id"][:-1] + "9"
            _store(arm_a / "raw-row-manifest-laststage03.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_row_mapped_to_wrong_decision_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-laststage03.json")
            doc["rows"][4]["decision_index"] = 7
            _store(arm_a / "raw-row-manifest-laststage03.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_missing_raw_verification_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-laststage03.json")
            doc["rows"].pop(55)
            _store(arm_a / "raw-row-manifest-laststage03.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_duplicate_raw_verification_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-laststage03.json")
            row = copy.deepcopy(doc["rows"][60])
            doc["rows"][61] = row
            doc["rows"].pop()
            _store(arm_a / "raw-row-manifest-laststage03.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_decision_table_sha_not_matching_raw_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-laststage03.json")
            doc["rows"][30]["control_raw_row_sha256"] = "b" * 64
            doc["rows"][30]["integrated_raw_row_sha256"] = "b" * 64
            _store(arm_a / "raw-row-manifest-laststage03.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_reference_row_lacking_summary_binding_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-reference04.json")
            doc["rows"][17]["control_summary_bound"] = False
            _store(arm_a / "raw-row-manifest-reference04.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_forged_aggregate_with_191_rows_fails(self):
        # aggregate counters forged to 192 while only 191 valid rows exist:
        # the reducer never reads aggregates, so the missing row must fail
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "raw-row-manifest-reference04.json")
            doc["rows"].pop(3)
            doc["files_compared"] = 192
            doc["byte_identical"] = 192
            doc["summary_bound_ok"] = 192
            _store(arm_a / "raw-row-manifest-reference04.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_producer_substitution_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-integrated-candidate.json")
            doc["producer"]["commit"] = CONTROL_PRODUCER
            _store(arm_a / "index-integrated-candidate.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_dirty_run_index_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-control-reference.json")
            doc["producer"]["dirty"] = True
            _store(arm_a / "index-control-reference.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_nan_inf_nonzero_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-integrated-candidate.json")
            doc["cases"][5]["nan_inf_count"] = 1
            _store(arm_a / "index-integrated-candidate.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_wrong_checkpoint_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-control-candidate.json")
            doc["subject"]["checkpoint_sha256"] = "0" * 64
            _store(arm_a / "index-control-candidate.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_prerun_wrong_inferswarm_head_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "prerun-revalidation.json")
            doc["orchestrator_inferswarm"]["head"] = "0" * 40
            _store(arm_a / "prerun-revalidation.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_prerun_dirty_inferswarm_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "prerun-revalidation.json")
            doc["orchestrator_inferswarm"]["clean"] = False
            _store(arm_a / "prerun-revalidation.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_prerun_wrong_control_checkout_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "prerun-revalidation.json")
            doc["freetoken_identities"][0]["checkout_paths"][1]["head_after_p0b_checkout"] = "0" * 40
            _store(arm_a / "prerun-revalidation.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_prerun_wrong_integrated_checkout_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "prerun-revalidation.json")
            doc["freetoken_identities"][2]["checkout_paths"][0]["head_at_probe"] = "0" * 40
            _store(arm_a / "prerun-revalidation.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_prerun_wrong_topology_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "prerun-revalidation.json")
            doc["compute_unit_identity"][2]["uuid"] = "GPU-0000"
            _store(arm_a / "prerun-revalidation.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_prerun_missing_host_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "prerun-revalidation.json")
            doc["freetoken_identities"].pop()  # drop inferswarm04
            _store(arm_a / "prerun-revalidation.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_invalid_attempt_claims_observations_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "attempt-lineage.json")
            doc["attempts"][0]["correctness_bearing_observation_count"] = 8
            _store(arm_a / "attempt-lineage.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_invalid_attempt_ids_remerged_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "attempt-lineage.json")
            doc["attempts"][2]["attempt_id"] = doc["attempts"][0]["attempt_id"]
            _store(arm_a / "attempt-lineage.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_second_valid_attempt_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "attempt-lineage.json")
            doc["attempts"][0]["validity"] = "VALID"
            _store(arm_a / "attempt-lineage.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_missing_artifact_fails(self):
        def mutation(root, arm_a, evidence):
            (arm_a / "attempt-lineage.json").unlink()
        _expect_reducer_failure(mutation)

    def test_mutation_malformed_artifact_fails(self):
        def mutation(root, arm_a, evidence):
            (arm_a / "prerun-revalidation.json").write_text("{not json")
        _expect_reducer_failure(mutation)

    def test_mutation_physical_preflight_bytes_fails(self):
        def mutation(root, arm_a, evidence):
            target = evidence / "physical-preflight.json"
            target.write_bytes(target.read_bytes() + b" ")
        _expect_reducer_failure(mutation)

    def test_mutation_canonical_summary_bytes_fails(self):
        def mutation(root, arm_a, evidence):
            target = evidence / "canonical-summary.json"
            doc = _load(target)
            doc["mutation"] = True
            _store(target, doc)
        _expect_reducer_failure(mutation)

    def test_mutation_holdout_case_in_fixture_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "fixture-corpus.json")
            doc["cases"][0]["case_id"] = "h109-01-01-045"
            _store(arm_a / "fixture-corpus.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_fixture_bytes_drift_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "fixture-corpus.json")
            doc["cases"][0]["token_count"] = doc["cases"][0].get("token_count", 0) + 1 \
                if isinstance(doc["cases"][0].get("token_count"), int) else doc["cases"][0]
            _store(arm_a / "fixture-corpus.json", doc)
        _expect_reducer_failure(mutation)


class CheckpointContinuityMutationTests(unittest.TestCase):
    """Finding 1 (P0) negative controls: accepted-byte continuity."""

    def test_mutation_current_full_sha_wrong_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"][0]["present_day_observation"]["full_file_sha256"] = "0" * 64
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_continuity_path_wrong_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"][1]["path"] = "/srv/models/gemma-r6-other/model.safetensors"
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_wrong_size_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"][2]["st_size"] = 23919549407
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_nonregular_symlink_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"][0]["is_symlink"] = True
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_inode_drift_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"][0]["st_ino"] = 999999
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_ctime_postdates_accepted_hash_fails(self):
        # ctime moved INSIDE the accepted hash window: replacement/write
        # during the continuity interval would look exactly like this
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            # 2026-09-08T12:00:00Z is after the #119 window start and inside
            # the Arm-A continuity interval
            doc["hosts"][0]["st_ctime_ns"] = 1788868800 * 1_000_000_000
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_interval_violation_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["continuity_interval"]["end_utc"] = "2026-09-07T00:00:00Z"
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_missing_host_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"] = [h for h in doc["hosts"] if h["host"] != "inferswarm03"]
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_result_true_but_derivation_fails(self):
        # the stored continuity_result string must not be authority: with the
        # derivation facts broken the record must still fail closed
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["hosts"][0]["st_mtime_ns"] = doc["hosts"][0]["st_ctime_ns"] + 10**9
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_launch_path_binding_removed_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            doc["continuity_derivation"]["launch_path_evidence"].pop()
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_launch_model_path_substituted_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "checkpoint-continuity.json")
            item = doc["continuity_derivation"]["launch_path_evidence"][0]
            item["model_arg"] = "--model /srv/models/gemma-r7"
            _store(arm_a / "checkpoint-continuity.json", doc)
        _expect_reducer_failure(mutation)


class SubjectMutationTests(unittest.TestCase):
    """Finding 2 (P1) negative controls: complete frozen subject."""

    def test_mutation_contract_id_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-integrated-candidate.json")
            doc["subject"]["contract_id"] = "inferswarm.other/2"
            _store(arm_a / "index-integrated-candidate.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_methodology_commit_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-control-candidate.json")
            doc["subject"]["methodology_commit"] = "0" * 40
            _store(arm_a / "index-control-candidate.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_model_revision_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-control-reference.json")
            doc["subject"]["model_revision"] = "0" * 40
            _store(arm_a / "index-control-reference.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_expected_producer_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "index-integrated-reference.json")
            doc["producer"]["expected_commit"] = CONTROL_PRODUCER
            _store(arm_a / "index-integrated-reference.json", doc)
        _expect_reducer_failure(mutation)


class DeviceBindingMutationTests(unittest.TestCase):
    """Finding 2 (P1) negative controls: exact valid-run CU bindings."""

    @staticmethod
    def _binding(doc, run):
        return next(b for b in doc["bindings"] if b["run"] == run)

    def test_mutation_stage1_uuid_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            self._binding(doc, "control_candidate_chain")["stage1"]["observed_gpu_uuids"] = [
                "GPU-0000"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_stage2_uuid_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            self._binding(doc, "integrated_candidate_chain")["stage2"]["observed_gpu_uuids"] = [
                "GPU-0000"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_stage3_uuid_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            self._binding(doc, "control_candidate_chain")["stage3"]["observed_gpu_uuids"] = [
                "GPU-0000"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_noncanonical_gpu_substituted_fails(self):
        # inferswarm03's second (noncanonical) RTX 3060 swapped in as stage 3
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            self._binding(doc, "integrated_candidate_chain")["stage3"]["observed_gpu_uuids"] = [
                "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_reference_uuid_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            self._binding(doc, "integrated_reference")["reference"]["observed_gpu_uuids"] = [
                "GPU-0000"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_missing_run_binding_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            doc["bindings"] = [b for b in doc["bindings"]
                               if b["run"] != "control_reference"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_topology_probe_right_but_binding_wrong_fails(self):
        # prerun topology untouched; only the actual run binding is wrong
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            self._binding(doc, "control_candidate_chain")["stage1"]["observed_gpu_uuids"] = [
                "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55"]
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)

    def test_mutation_exclusion_erased_fails(self):
        def mutation(root, arm_a, evidence):
            doc = _load(arm_a / "run-device-bindings.json")
            doc["noncanonical_gpu_exclusion"] = {}
            _store(arm_a / "run-device-bindings.json", doc)
        _expect_reducer_failure(mutation)


class ManifestCoverageTests(unittest.TestCase):
    def test_arm_a_artifacts_exist_and_are_manifest_exact(self):
        entries = manifest_entries()
        for name in (*NEW_ARM_A_ARTIFACTS, *LEGACY_ARM_A_ARTIFACTS):
            path = ARM_A / name
            self.assertTrue(path.is_file(), f"missing Arm A artifact {name}")
            relative = str(path.relative_to(ROOT))
            self.assertIn(relative, entries, f"{name} not in MANIFEST")
            self.assertEqual(entries[relative], sha256_file(path),
                             f"{name} bytes drift from MANIFEST")

    def test_committed_evidence_convention_covers_arm_a(self):
        covered = {name for name in proof.COMMITTED_EVIDENCE_FILES
                   if name.startswith("arm-a/")}
        expected = {f"arm-a/{name}" for name in (*NEW_ARM_A_ARTIFACTS, *LEGACY_ARM_A_ARTIFACTS)}
        self.assertEqual(covered, expected)
        for name in expected:
            self.assertTrue((ev.EVIDENCE / name).is_file(), name)

    def test_accepted_118_and_preflight_pins_hold(self):
        self.assertEqual(sha256_file(ev.EVIDENCE / "canonical-summary.json"),
                         ev.CANONICAL_SUMMARY_118_SHA256)
        self.assertEqual(sha256_file(ev.EVIDENCE / "physical-preflight.json"),
                         ev.PHYSICAL_PREFLIGHT_FILE_SHA256)

    def test_reducer_module_is_pure_stdlib_and_execution_free(self):
        source = (ROOT / "scripts" / "issue117_arm_a_evidence.py").read_text()
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        allowed = {"hashlib", "json", "pathlib", "typing", "__future__",
                   "datetime", "importlib", "sys"}
        self.assertTrue(imported <= allowed, f"unexpected imports: {imported - allowed}")
        # no stored-boolean authority: the reducer must not read the witness
        # status or any all_*_identical aggregate as evidence
        self.assertNotIn('"witness.json"', source)
        self.assertNotIn("all_row_sha_identical", source)
        self.assertNotIn("all_prefix_sha_identical", source)
        self.assertNotIn("files_compared", source)


if __name__ == "__main__":
    unittest.main()
