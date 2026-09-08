"""Focused tests for the issue #117 generic admission planner."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_planner as planner  # noqa: E402
from issue103_planner import EXCLUDED, FEASIBLE_UNRANKED, RANKED, purity_audit  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_artifact_core import digest_of_bytes, self_digest  # noqa: E402

PLANNER_PATH = ROOT / "scripts" / "issue117_planner.py"

# forbidden model/campaign nouns, supplied by the caller so the planner
# module never needs to spell them
FORBIDDEN_TOKENS = (
    "gemma", "rtx", "3060", "3090", "bf16", "triton", "flashinfer", "cuda",
    "inferswarm00", "inferswarm01", "inferswarm03", "inferswarm04",
    "safetensors", "tokenizer", "checkpoint",
)

ACCEPTED_ADJUDICATION = "a" * 64


def make_record(record_id: str, subject_digest: str, *,
                subject: dict | None = None,
                disposition: str = "V5_QUALIFICATION_PASS",
                adjudication: str = ACCEPTED_ADJUDICATION) -> dict:
    subject = subject if subject is not None else {"opaque": record_id}
    record = {
        "schema": "inferswarm.issue117.qualification-record/2",
        "qualification_record_id": record_id,
        "scope": "test",
        "authority": {"terminal_disposition": disposition,
                      "terminal_adjudication_sha256": adjudication},
        "qualification_subject": subject,
    }
    # the record digest must recompute from the subject; a mismatched
    # caller-supplied digest produces a malformed record
    recomputed = digest_of_bytes(canonical_json_bytes(subject))
    record["qualification_subject_digest"] = (subject_digest
                                              if subject_digest is not None
                                              else recomputed)
    record["record_digest"] = self_digest(record, identity_field="record_digest")
    return record


def policy(**overrides) -> dict:
    base = {"policy": planner.QUALIFICATION_POLICY_STRICT,
            "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
            "accepted_adjudication_sha256": ACCEPTED_ADJUDICATION,
            "required_for_admission": True}
    base.update(overrides)
    return base


def make_requirements(spec: dict[str, list[tuple[str, int]]], plan_digest: str) -> dict:
    participants = []
    for participant_id, node_id, artifacts in spec["participants"]:
        participants.append({
            "plan_digest": plan_digest,
            "participant_id": participant_id,
            "node_id": node_id,
            "execution_unit_id": f"cu-for-{participant_id}",
            "required_logical_state": {"assigned": [], "declared_shared": [],
                                       "required_metadata": []},
            "required_artifacts": [
                {"artifact_id": artifact_id, "length": length}
                for artifact_id, length in artifacts
            ],
            "required_artifact_bytes": sum(length for _, length in artifacts),
        })
    document = {"schema": "inferswarm.issue99.participant-requirements/1",
                "plan_digest": plan_digest, "model": {"model_id": "m", "revision": "r",
                                                      "representation": "rep"},
                "participants": participants}
    document["requirements_digest"] = self_digest(document, identity_field="requirements_digest")
    return document


class StubCoordinator:
    """Delta/authorize over explicit verified-local inventory."""

    def __init__(self, requirements, local_by_participant, source=None):
        self.requirements = requirements
        self.local = local_by_participant
        self._source = source or {"kind": "authorized-source", "source_id": "origin-1"}

    def delta(self, participant_id):
        required_ids = set()
        for participant in self.requirements["participants"]:
            if participant["participant_id"] == participant_id:
                required_ids.update(record["artifact_id"]
                                    for record in participant["required_artifacts"])
        local_ids = sorted(required_ids & set(self.local.get(participant_id, ())))
        return {"participant_id": participant_id,
                "local_artifact_ids": local_ids,
                "missing_artifact_ids": sorted(required_ids - set(local_ids))}

    def authorize(self, delta, artifact_id):
        return {"participant_id": delta["participant_id"], "artifact_id": artifact_id,
                "source": dict(self._source)}


class World:
    """Minimal frozen world for planner-gate tests."""

    def __init__(self, planner_obj, requirements, coordinator):
        self.planner = planner_obj
        self.requirements = requirements
        self.coordinator = coordinator

    def __getattr__(self, name):
        return getattr(self.planner, name)

    def rank(self):
        return self.planner.rank()


def subject_for(name: str) -> dict:
    return {"model_id": "m", "revision": name, "checkpoint_sha256": name * 2,
            "representation": "rep", "execution": "exec", "backend": {"k": "v"},
            "layer_count": 48, "stage_structure": [{"cu_id": name}]}


def subject_digest(subject: dict) -> str:
    return digest_of_bytes(canonical_json_bytes(subject))


def build_world(*, local_for_v5=(), v5_subject="digest-v5", other_subject="digest-other",
                path_bandwidth=None) -> World:
    plan_digest = "plan-" + "0" * 60
    spec = {"participants": [
        ("cand-a.stage-1", "node-1", [("a1-w", 100), ("shared-emb", 50)]),
        ("cand-a.stage-2", "node-2", [("a2-w", 120)]),
        ("cand-b.stage-1", "node-1", [("b1-w", 400)]),
    ]}
    requirements = make_requirements(spec, plan_digest)
    coordinator = StubCoordinator(requirements, {
        "cand-a.stage-1": set(local_for_v5),
        "cand-a.stage-2": set(),
        "cand-b.stage-1": set(),
    })
    candidates = [
        {"candidate_id": "cand-a", "stage_count": 2,
         "qualification_subject": subject_for("v5"),
         "qualification_subject_digest": subject_digest(subject_for("v5"))},
        {"candidate_id": "cand-b", "stage_count": 1,
         "qualification_subject": subject_for("other"),
         "qualification_subject_digest": subject_digest(subject_for("other"))},
    ]
    feasibility = {
        "cand-a": {"technical_feasibility": True, "technical_feasibility_known": True,
                   "hard_policy_eligible": True, "integrity_eligible": True},
        "cand-b": {"technical_feasibility": True, "technical_feasibility_known": True,
                   "hard_policy_eligible": True, "integrity_eligible": True},
    }
    records = [make_record("rec-v5", subject_digest(subject_for("v5")),
                           subject=subject_for("v5"))]
    requirements_by_candidate = {
        "cand-a": slice_requirements(requirements, ("cand-a.stage-1", "cand-a.stage-2")),
        "cand-b": slice_requirements(requirements, ("cand-b.stage-1",)),
    }
    path_evidence_by_candidate = {"cand-a": [], "cand-b": []}
    if path_bandwidth:
        for candidate_id, sliced in requirements_by_candidate.items():
            stage_digest = sliced["requirements_digest"]
            path_evidence_by_candidate[candidate_id] = [
                make_path_evidence(
                    stage_candidate_id=f"{candidate_id}::stage-"
                                       f"{participant_id.rsplit('.stage-', 1)[1]}",
                    participant_id=participant_id,
                    node_id="node-1" if participant_id.endswith("stage-1") else "node-2",
                    artifact_id=artifact_id,
                    source=coordinator._source,
                    target={"execution_unit_id": f"cu-for-{participant_id}"},
                    plan_digest=plan_digest,
                    requirements_digest=stage_digest,
                    bandwidth=path_bandwidth)
                for participant in sliced["participants"]
                for participant_id in [participant["participant_id"]]
                for artifact_id in [record["artifact_id"]
                                    for record in participant["required_artifacts"]]
            ]
    planner_obj = planner.AdmissionPlanner(
        candidates=candidates, feasibility=feasibility,
        qualification_records=records, qualification_policy=policy(),
        requirements_by_candidate=requirements_by_candidate,
        path_evidence_by_candidate=path_evidence_by_candidate,
        evidence_contract=make_contract(),
        coordinators_by_candidate={"cand-a": coordinator, "cand-b": coordinator})
    return World(planner_obj, requirements, coordinator)



def slice_requirements(requirements, participant_ids):
    sliced = dict(requirements)
    sliced["participants"] = [
        participant for participant in requirements["participants"]
        if participant["participant_id"] in participant_ids]
    sliced["requirements_digest"] = self_digest(sliced, identity_field="requirements_digest")
    return sliced


def make_contract():
    return {"path": {"evidence_version": "issue117-evidence-v1",
                     "evidence_identity": "path-band-v1",
                     "applicability_context": {"fixture": "cpu-only"}}}



def make_path_evidence(*, stage_candidate_id, participant_id, node_id, artifact_id, source,
                       target, plan_digest, requirements_digest, bandwidth) -> dict:
    record = {
        "schema": "issue103.path-evidence/1",
        "candidate_id": stage_candidate_id,
        "participant_id": participant_id,
        "node_id": node_id,
        "artifact_id": artifact_id,
        "source": dict(source),
        "target_node_id": node_id,
        "target": dict(target),
        "path_id": f"path-{stage_candidate_id}-{artifact_id}",
        "bandwidth_bytes_per_second": bandwidth,
        "evidence_version": "issue117-evidence-v1",
        "evidence_identity": "path-band-v1",
        "applicability_context": {"fixture": "cpu-only"},
        "requirement_identity": artifact_id,
        "plan_digest": plan_digest,
        "requirements_digest": requirements_digest,
    }
    record["evidence_digest"] = self_digest(record, identity_field="evidence_digest")
    return record


class QualificationGateTests(unittest.TestCase):
    def v5_candidate(self) -> dict:
        return {"candidate_id": "cand",
                "qualification_subject": subject_for("v5"),
                "qualification_subject_digest": subject_digest(subject_for("v5"))}

    def v5_record(self, record_id="rec-v5", **kwargs) -> dict:
        return make_record(record_id, subject_digest(subject_for("v5")),
                           subject=subject_for("v5"), **kwargs)

    def test_matching_subject_is_applicable(self):
        result = planner.evaluate_qualification_applicability(
            self.v5_candidate(), [self.v5_record()], policy())
        self.assertEqual(result["status"], planner.QUALIFICATION_APPLICABLE)
        self.assertEqual(result["matched_record_ids"], ["rec-v5"])

    def test_materially_changed_subject_cannot_inherit(self):
        changed = {"candidate_id": "cand",
                   "qualification_subject": subject_for("CHANGED"),
                   "qualification_subject_digest": subject_digest(subject_for("CHANGED"))}
        result = planner.evaluate_qualification_applicability(
            changed, [self.v5_record()], policy())
        self.assertEqual(result["status"], planner.QUALIFICATION_NOT_APPLICABLE)
        self.assertEqual(result["reason"], planner.REASON_SUBJECT_MISMATCH)

    def test_no_accepted_evidence_is_not_applicable(self):
        result = planner.evaluate_qualification_applicability(
            self.v5_candidate(), [], policy())
        self.assertEqual(result["reason"], planner.REASON_NO_ACCEPTED_EVIDENCE)

    def test_non_terminal_disposition_is_not_evidence(self):
        result = planner.evaluate_qualification_applicability(
            self.v5_candidate(),
            [self.v5_record(disposition="SOMETHING_ELSE")], policy())
        self.assertEqual(result["reason"], planner.REASON_EVIDENCE_NOT_TERMINAL_PASS)

    def test_malformed_subject_digest_is_rejected_not_trusted(self):
        bad = self.v5_record()
        bad["qualification_subject_digest"] = "tampered"
        bad["record_digest"] = self_digest(bad, identity_field="record_digest")
        result = planner.evaluate_qualification_applicability(
            self.v5_candidate(), [bad], policy())
        self.assertEqual(result["reason"], planner.REASON_NO_ACCEPTED_EVIDENCE)
        self.assertEqual(result["malformed_record_ids"], ["rec-v5"])

    def test_record_bound_to_foreign_adjudication_is_rejected(self):
        foreign = self.v5_record(adjudication="b" * 64)
        result = planner.evaluate_qualification_applicability(
            self.v5_candidate(), [foreign], policy())
        self.assertEqual(result["status"], planner.QUALIFICATION_NOT_APPLICABLE)
        self.assertEqual(result["unbound_record_ids"], ["rec-v5"])

    def test_self_inconsistent_record_is_never_promoted(self):
        # a record whose subject digest does not recompute cannot be made
        # usable by ALSO tampering the adjudication identity or disposition
        bad = self.v5_record(disposition="OTHER")
        bad["qualification_subject_digest"] = "tampered"
        bad["record_digest"] = self_digest(bad, identity_field="record_digest")
        result = planner.evaluate_qualification_applicability(
            self.v5_candidate(), [bad], policy())
        self.assertEqual(result["status"], planner.QUALIFICATION_NOT_APPLICABLE)
        self.assertEqual(result["malformed_record_ids"], ["rec-v5"])

    def test_candidate_lying_subject_digest_is_hard_error(self):
        liar = {"candidate_id": "cand",
                "qualification_subject": subject_for("v5"),
                "qualification_subject_digest": subject_digest(subject_for("OTHER"))}
        with self.assertRaises(planner.PlannerError):
            planner.evaluate_qualification_applicability(liar, [self.v5_record()], policy())

    def test_candidate_without_subject_is_hard_error(self):
        with self.assertRaises(planner.PlannerError):
            planner.evaluate_qualification_applicability(
                {"candidate_id": "cand", "qualification_subject_digest": "x"},
                [self.v5_record()], policy())

    def test_missing_accepted_adjudication_in_policy_rejected(self):
        with self.assertRaises(planner.PlannerError):
            planner.evaluate_qualification_applicability(
                self.v5_candidate(), [self.v5_record()],
                policy(accepted_adjudication_sha256="  "))

    def test_unknown_policy_rejected(self):
        with self.assertRaises(planner.PlannerError):
            planner.evaluate_qualification_applicability(
                self.v5_candidate(), [], {"policy": "YOLO"})


class PlannerPurityTests(unittest.TestCase):
    def test_planner_module_has_no_model_specific_nouns(self):
        audit = planner.planner_purity_audit(PLANNER_PATH, FORBIDDEN_TOKENS)
        self.assertEqual(audit["violations"], [])
        self.assertEqual(audit["planner_model_specific_branches"], 0)

    def test_planner_does_not_import_the_strategy_module(self):
        source = PLANNER_PATH.read_text()
        self.assertNotIn("issue117_gemma_strategy", source)
        self.assertNotIn("issue117_applicability", source)
        module = sys.modules["issue117_planner"]
        for name in vars(module):
            self.assertFalse(name.startswith("issue117_gemma"), name)

    def test_purity_audit_detects_violations(self):
        audit = purity_audit(PLANNER_PATH, ("planner", "admissionplanner"))
        self.assertTrue(audit["violations"])


class AdmissionPlannerTests(unittest.TestCase):
    def build(self, **kwargs) -> World:
        return build_world(**kwargs)

    def test_qualified_candidate_selected_unqualified_excluded(self):
        decision = self.build(path_bandwidth=10).rank()
        self.assertEqual(decision["selected_candidate_id"], "cand-a")
        by_id = {row["candidate_id"]: row for row in decision["candidates"]}
        self.assertEqual(by_id["cand-b"]["ranking_status"], EXCLUDED)
        self.assertIn(planner.REASON_SUBJECT_MISMATCH,
                      by_id["cand-b"]["admission_failures"])
        self.assertEqual(by_id["cand-b"]["gates"]["qualification_applicability"]["status"],
                         planner.QUALIFICATION_NOT_APPLICABLE)
        self.assertTrue(by_id["cand-b"]["gates"]["technical_feasibility"]["passed"])

    def test_explanations_cover_selected_excluded(self):
        decision = self.build(path_bandwidth=10).rank()
        dispositions = {entry["candidate_id"]: entry["disposition"]
                        for entry in decision["explanations"]}
        self.assertEqual(dispositions["cand-a"], "SELECTED")
        self.assertEqual(dispositions["cand-b"], "EXCLUDED")

    def test_technical_infeasibility_excludes_despite_qualification(self):
        world = build_admission_with(
            feasibility_override={"cand-a": {"technical_feasibility": False,
                                             "technical_feasibility_known": True,
                                             "hard_policy_eligible": True,
                                             "integrity_eligible": True}})
        decision = world.rank()
        by_id = {row["candidate_id"]: row for row in decision["candidates"]}
        self.assertEqual(by_id["cand-a"]["ranking_status"], EXCLUDED)
        self.assertEqual(by_id["cand-a"]["admission_failures"], ["CAPACITY_INFEASIBLE"])
        self.assertEqual(
            by_id["cand-a"]["gates"]["qualification_applicability"]["status"],
            planner.QUALIFICATION_APPLICABLE)

    def test_hard_policy_exclusion_is_distinct_from_qualification(self):
        world = build_admission_with(
            feasibility_override={"cand-a": {"technical_feasibility": True,
                                             "technical_feasibility_known": True,
                                             "hard_policy_eligible": False,
                                             "integrity_eligible": True}})
        decision = world.rank()
        by_id = {row["candidate_id"]: row for row in decision["candidates"]}
        self.assertEqual(by_id["cand-a"]["admission_failures"], ["HARD_POLICY_EXCLUSION"])
        self.assertEqual(
            by_id["cand-a"]["gates"]["qualification_applicability"]["status"],
            planner.QUALIFICATION_APPLICABLE)

    def test_missing_path_evidence_yields_unranked_not_guessed(self):
        decision = self.build().rank()
        # admissible candidate without path evidence is admissible but unranked
        self.assertIsNone(decision["selected_candidate_id"])
        by_id = {row["candidate_id"]: row for row in decision["candidates"]}
        self.assertEqual(by_id["cand-a"]["ranking_status"], FEASIBLE_UNRANKED)
        self.assertIsNone(by_id["cand-a"]["estimated_transition_seconds"])

    def test_locality_cannot_override_qualification(self):
        # cand-b is fully locally possessed (zero-cost transition); it must
        # still be excluded by the qualification gate, never by economics
        world = build_world(path_bandwidth=10)
        world.coordinator.local["cand-b.stage-1"] = {"b1-w"}
        decision = world.rank()
        self.assertEqual(decision["selected_candidate_id"], "cand-a")
        by_id = {row["candidate_id"]: row for row in decision["candidates"]}
        self.assertEqual(by_id["cand-b"]["ranking_status"], EXCLUDED)

    def test_verified_local_inventory_reduces_missing_bytes(self):
        with_local = build_world(local_for_v5=("shared-emb", "a1-w"), path_bandwidth=10)
        without_local = build_world(path_bandwidth=10)
        decision_with = with_local.rank()
        decision_without = without_local.rank()
        row_with = {row["candidate_id"]: row for row in decision_with["candidates"]}["cand-a"]
        row_without = {row["candidate_id"]: row for row in decision_without["candidates"]}["cand-a"]
        self.assertLess(row_with["missing_bytes"], row_without["missing_bytes"])

    def test_transfer_accounting_derives_unexplained_zero(self):
        planner_obj = self.build(path_bandwidth=10)
        accounting = planner_obj.account_transfer_events()
        self.assertEqual(accounting["unexplained_transition_bytes"], 0)


def build_admission_with(*, feasibility_override) -> World:
    world = build_world(path_bandwidth=10)
    inner = world.planner
    feasibility = dict(inner.feasibility)
    feasibility.update(feasibility_override)
    planner_obj = planner.AdmissionPlanner(
        candidates=inner.candidates, feasibility=feasibility,
        qualification_records=inner.qualification_records,
        qualification_policy=inner.qualification_policy,
        requirements_by_candidate=inner.requirements_by_candidate,
        path_evidence_by_candidate=inner.path_evidence_by_candidate,
        evidence_contract=inner.evidence_contract,
        coordinators_by_candidate=inner._coordinators_by_candidate)
    return World(planner_obj, world.requirements, world.coordinator)


class ResultFenceTests(unittest.TestCase):
    def make_fence(self):
        return planner.ResultFence(
            contract_id="contract-1", session_id="session-1", epoch=3,
            realization_id="realization-1", plan_digest="plan-digest-1",
            operations=("prefill", "decode"))

    def base_result(self, operation="decode", position=0):
        return {"contract_id": "contract-1", "session_id": "session-1", "epoch": 3,
                "realization_id": "realization-1", "plan_digest": "plan-digest-1",
                "operation": operation, "position": position}

    def test_correct_sequence_commits(self):
        fence = self.make_fence()
        for position in range(3):
            receipt = fence.commit(self.base_result(position=position))
            self.assertTrue(receipt["committed"])
        summary = fence.summary()
        self.assertEqual(summary["committed_by_operation"]["decode"], 3)
        self.assertEqual(summary["stale_result_committed"], 0)
        self.assertEqual(summary["wrong_position_result_committed"], 0)
        self.assertEqual(summary["attempted_result_count"], 3)
        self.assertEqual(len(fence.committed_results), 3)

    def test_wrong_session_fails_closed(self):
        fence = self.make_fence()
        result = self.base_result()
        result["session_id"] = "session-2"
        with self.assertRaisesRegex(planner.PlannerError, "WRONG_SESSION"):
            fence.commit(result)
        self.assertEqual(fence.summary()["wrong_session_result_committed"], 0)
        self.assertEqual(fence.summary()["fence_rejections"], 1)
        # the full refused attempt is retained, not just a reason
        self.assertEqual(fence.rejections[0]["result"]["session_id"], "session-2")

    def test_stale_epoch_fails_closed(self):
        fence = self.make_fence()
        result = self.base_result()
        result["epoch"] = 2
        with self.assertRaisesRegex(planner.PlannerError, "WRONG_EPOCH"):
            fence.commit(result)

    def test_wrong_plan_fails_closed(self):
        fence = self.make_fence()
        result = self.base_result()
        result["plan_digest"] = "plan-digest-2"
        with self.assertRaisesRegex(planner.PlannerError, "WRONG_PLAN"):
            fence.commit(result)

    def test_wrong_realization_fails_closed(self):
        fence = self.make_fence()
        result = self.base_result()
        result["realization_id"] = "realization-2"
        with self.assertRaisesRegex(planner.PlannerError, "WRONG_REALIZATION"):
            fence.commit(result)

    def test_replayed_position_fails_closed(self):
        fence = self.make_fence()
        fence.commit(self.base_result(position=0))
        with self.assertRaisesRegex(planner.PlannerError, "WRONG_POSITION"):
            fence.commit(self.base_result(position=0))
        with self.assertRaisesRegex(planner.PlannerError, "WRONG_POSITION"):
            fence.commit(self.base_result(position=5))
        summary = fence.summary()
        self.assertEqual(summary["committed_by_operation"]["decode"], 1)
        self.assertEqual(summary["fence_rejections"], 2)

    def test_unknown_operation_fails_closed(self):
        fence = self.make_fence()
        with self.assertRaisesRegex(planner.PlannerError, "UNKNOWN_OPERATION"):
            fence.commit(self.base_result(operation="speculative"))

    def test_counters_are_derived_not_asserted(self):
        fence = self.make_fence()
        for position in range(4):
            fence.commit(self.base_result(position=position))
        # the ledger is the sole input to the counters: an admitted entry
        # that would violate the authority shows up as a nonzero counter
        fence.committed_results.append({**fence.committed_results[0],
                                        "session_id": "other-session"})
        summary = fence.summary()
        self.assertEqual(summary["wrong_session_result_committed"], 1)
        self.assertEqual(summary["wrong_session_result_committed"],
                         planner.derive_fence_counters(
                             fence.committed_results,
                             authority=fence.authority)["wrong_session_result_committed"])

    def test_stale_entry_derivation(self):
        fence = self.make_fence()
        fence.commit(self.base_result(position=0))
        fence.commit(self.base_result(position=1))
        ledger = list(fence.committed_results)
        ledger.insert(0, {**ledger[0], "position": 99})
        derived = planner.derive_fence_counters(ledger, authority=fence.authority)
        # the forged leading entry is out of sequence; the genuine entries
        # that follow revalidate in ledger order
        self.assertEqual(derived["wrong_position_result_committed"], 1)
        self.assertEqual(derived["stale_result_committed"], 0)
        self.assertNotIn("wrong_session_result_committed",
                         [name for name, value in derived.items() if value])

    def test_stale_ledger_entry_detection(self):
        fence = self.make_fence()
        fence.commit(self.base_result(position=0))
        fence.commit(self.base_result(position=1))
        ledger = list(fence.committed_results)
        # replaying position 0 after it was consumed is stale
        ledger.append(dict(ledger[0]))
        derived = planner.derive_fence_counters(ledger, authority=fence.authority)
        self.assertEqual(derived["stale_result_committed"], 1)

    def test_every_derived_counter_exists(self):
        fence = self.make_fence()
        for name in planner.FENCE_DERIVED_COUNTERS:
            self.assertIn(name, fence.summary())


if __name__ == "__main__":
    unittest.main()
