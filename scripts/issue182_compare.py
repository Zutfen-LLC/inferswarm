#!/usr/bin/env python3
"""Issue #182 — Arm-E two-arm planning comparison (CPU-only, stdlib).

Runs the ACCEPTED admission planner (issue117_planner.AdmissionPlanner
over the accepted #103/#101/#99 machinery) over exactly two inventory
arms whose ONLY difference is the verified node inventory:

  Arm E-A (cold): the retained accepted Arm-B sequence-1
      pre-realization inventory snapshots (empty verified-object sets),
      consumed byte-for-byte from the retained Arm-B evidence.

  Arm E-B (warm): the fresh read-only observation's verified object
      inventory, cross-bound to the accepted Arm-D cache identities and
      the retained Arm-B post-acquisition inventory.

Every other planning input — candidate set, feasibility/capacity facts,
hard policy, integrity, qualification record + policy, participant
requirements, path evidence, evidence contract, objective, tie-break —
is constructed ONCE and reused verbatim in both arms; the retained
comparison record proves that byte-identity mechanically.

Fail-closed: any identity drift, any unexplained difference, any
mutation during observation, or any gate movement stops with a
classified problem and no terminal is emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue182_campaign_pins as P  # noqa: E402

from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_artifact_core import digest_of_bytes, self_digest  # noqa: E402
from issue101_orchestration import (  # noqa: E402
    Coordinator, VerifiedInventory, _SNAPSHOT_ISSUER,
)
from issue117_planner import AdmissionPlanner  # noqa: E402
from issue103_planner import MIN_TRANSITION_COST  # noqa: E402
from issue117_accepted_subject import accepted_v5_qualification_record  # noqa: E402

EVIDENCE_117 = P.EVIDENCE_117
PREFLIGHT = EVIDENCE_117 / "physical-preflight.json"
ARM_B_POST_01 = P.ARM_B / "inventory-post-inferswarm01.json"
ARM_B_POST_03 = P.ARM_B / "inventory-post-inferswarm03.json"

NODE_SOURCES = [
    {"source_id": "inferswarm01",
     "endpoint": "file:///srv/inferswarm/cache/issue117"},
    {"source_id": "inferswarm03",
     "endpoint": "file:///srv/inferswarm/cache/issue117"},
]
ORIGIN_SOURCES = [dict(P.SOURCE_DESCRIPTOR)]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Retained-input loading and single construction (shared by both arms)
# ---------------------------------------------------------------------------

def load_candidates() -> list[dict]:
    document = json.loads(PREFLIGHT.read_text())
    candidates = document["candidate_set"]["candidates"]
    ids = [c["candidate_id"] for c in candidates]
    if sorted(ids) != sorted({
            "dense.3b8644d360a3", "dense.6171f32b4413", "dense.720a017663e4",
            "dense.97c6513e854b", "dense.9dd68b5adfa3", "dense.b1fb60400bc3",
            "dense.b3c4d8a8929e", "dense.e3a5ae183953", "dense.ede4c4376efe"}):
        raise SystemExit("ISSUE182_COMPARE_FAIL: candidate set drift")
    return candidates


def load_cu_roles() -> dict:
    document = json.loads(PREFLIGHT.read_text())
    return {cu["cu_id"]: cu["role"] for cu in document["compute_units"]}


def build_artifact_table(requirements: dict) -> dict:
    """Invert the retained V5 requirements into a (class, state) table.

    Every artifact record any legal dense candidate stage can require is
    present in the retained V5 participant requirements (the union of
    the three stages covers all 48 layers, the embedding, the final
    norm, the tied-head shared variants, and the metadata object).
    """
    table: dict[tuple[str, str], dict[str, dict]] = {}
    for participant in requirements["participants"]:
        for record in participant["required_artifacts"]:
            for state_id in record["satisfies_logical_state_ids"]:
                key = (record["requirement_class"], state_id)
                table.setdefault(key, {})
                table[key][record["artifact_id"]] = record
    return table


def make_resolver(table: dict):
    def resolver(requirement_class: str, state_id: str) -> list[dict]:
        entries = table.get((requirement_class, state_id))
        if entries is None:
            raise SystemExit(
                f"ISSUE182_COMPARE_FAIL: retained artifact table lacks "
                f"({requirement_class}, {state_id})")
        return [deepcopy(record) for _, record in sorted(entries.items())]
    return resolver


def build_plan(candidate: dict, requirements_model: dict,
               layer_count: int) -> dict:
    """Construct the execution plan for one candidate (retained format)."""
    stages = candidate["stage_structure"]
    units = [{"id": "metadata.config.json"},
             {"id": "state.embedding"},
             {"id": "state.final_norm"}]
    units += [{"id": f"state.layer.{i}"} for i in range(layer_count)]
    units += [{"id": "state.output_head"}]
    units.sort(key=lambda unit: unit["id"])
    participants = []
    for index, stage in enumerate(stages):
        assigned = [f"state.layer.{i}"
                    for i in range(stage["layer_start"], stage["layer_end"])]
        shared: list[str] = []
        metadata = ["metadata.config.json"]
        if index == 0:
            assigned.insert(0, "state.embedding")
        if index == len(stages) - 1:
            assigned.append("state.final_norm")
            if requirements_model["tie_word_embeddings"] and len(stages) > 1:
                shared = ["state.embedding", "state.output_head"]
        assigned.sort()
        participants.append({
            "execution_unit_id": stage["cu_id"],
            "node_id": stage["node"],
            "participant_id": f"{candidate['candidate_id']}.stage-{index + 1}",
            "required_state": {
                "assigned_logical_state": assigned,
                "declared_shared_state": shared,
                "required_metadata": metadata,
            },
        })
    plan = {
        "schema": "inferswarm.issue117.execution-plan/2",
        "candidate_id": candidate["candidate_id"],
        "epoch": 1,
        "logical_state_units": units,
        "model": deepcopy(requirements_model),
        "participants": participants,
    }
    plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
    return plan


def content_unique_weight(records: list[dict]) -> int:
    """Content-unique required bytes excluding metadata for one stage."""
    unique: dict[str, int] = {}
    for record in records:
        if record["requirement_class"] == "required_metadata":
            continue
        key = record["content_digest"]
        unique[key] = max(unique.get(key, 0), record["length"])
    return sum(unique.values())


def build_feasibility(candidates: list[dict], table: dict,
                      requirements_model: dict, layer_count: int,
                      gpu_total_bytes: dict, roles: dict) -> dict:
    """Derive the fixed feasibility input (technical + policy + integrity).

    Technical: stage weight bytes (content-unique, metadata excluded,
    derived from the retained artifact table) must fit the usable
    weight bytes of the stage's compute unit (observed GPU total minus
    the frozen reserve). Hard policy: every stage CU must be in a
    serving-eligible role (reference-reserved CUs are excluded).
    Integrity: eligibility is unconditional in this campaign (no
    integrity evidence exists against any candidate).
    """
    serving_eligible_roles = {"serving-candidate"}
    feasibility = {}
    for candidate in candidates:
        stage_weights = []
        usable = []
        fits = True
        for index, stage in enumerate(candidate["stage_structure"]):
            records = []
            assigned = [f"state.layer.{i}" for i in
                        range(stage["layer_start"], stage["layer_end"])]
            if index == 0:
                assigned.insert(0, "state.embedding")
            if index == len(candidate["stage_structure"]) - 1:
                assigned.append("state.final_norm")
                if (requirements_model["tie_word_embeddings"]
                        and len(candidate["stage_structure"]) > 1):
                    assigned_states_shared = ["state.embedding",
                                             "state.output_head"]
                else:
                    assigned_states_shared = []
            else:
                assigned_states_shared = []
            for state_id in assigned:
                for _, record in sorted(
                        table.get(("assigned_logical_state", state_id),
                                  {}).items()):
                    records.append(record)
            for state_id in assigned_states_shared:
                for _, record in sorted(
                        table.get(("declared_shared_state", state_id),
                                  {}).items()):
                    records.append(record)
            weight = content_unique_weight(records)
            stage_weights.append(weight)
            total = gpu_total_bytes.get(stage["cu_id"])
            if total is None:
                raise SystemExit(
                    f"ISSUE182_COMPARE_FAIL: no GPU total for "
                    f"{stage['cu_id']}")
            limit = total - P.CAPACITY_RESERVE_BYTES
            usable.append(limit)
            if weight > limit or limit <= 0:
                fits = False
        policy_ok = all(roles.get(stage["cu_id"]) in serving_eligible_roles
                        for stage in candidate["stage_structure"])
        feasibility[candidate["candidate_id"]] = {
            "technical_feasibility": bool(fits),
            "technical_feasibility_known": True,
            "hard_policy_eligible": bool(policy_ok),
            "integrity_eligible": True,
            "stage_weight_bytes": stage_weights,
            "usable_weight_bytes": usable,
            "accounting_source": "retained-arm-b-artifact-table-content-unique",
        }
    return feasibility


def build_path_evidence(requirements: dict, bandwidth: dict) -> list[dict]:
    """One frozen bandwidth record per required artifact of the V5 plan."""
    evidence = []
    for participant in requirements["participants"]:
        stage_number = participant["participant_id"].rsplit(".stage-", 1)[1]
        node_bw = bandwidth[participant["node_id"]]
        for record in participant["required_artifacts"]:
            document = {
                "schema": "issue103.path-evidence/1",
                "candidate_id":
                    f"{P.SUBJECT['candidate']}::stage-{stage_number}",
                "participant_id": participant["participant_id"],
                "node_id": participant["node_id"],
                "artifact_id": record["artifact_id"],
                "source": dict(P.SOURCE_DESCRIPTOR),
                "target_node_id": participant["node_id"],
                "target": {"execution_unit_id":
                           participant["execution_unit_id"]},
                "path_id": f"arm-e-source-path-{record['artifact_id'][7:19]}",
                "bandwidth_bytes_per_second": node_bw,
                "evidence_version":
                    P.PLANNING_EVIDENCE_CONTRACT["path"]["evidence_version"],
                "evidence_identity":
                    P.PLANNING_EVIDENCE_CONTRACT["path"]["evidence_identity"],
                "applicability_context":
                    P.PLANNING_EVIDENCE_CONTRACT["path"][
                        "applicability_context"],
                "requirement_identity": record["artifact_id"],
                "plan_digest": requirements["plan_digest"],
                "requirements_digest": requirements["requirements_digest"],
            }
            document["evidence_digest"] = self_digest(
                document, identity_field="evidence_digest")
            evidence.append(document)
    return evidence


def qualification_policy() -> dict:
    from issue117_subject_identity import MACHINERY_LOCAL_SUBJECT_KEYS
    return {
        "policy": "REQUIRE_ACCEPTED_EXECUTION_QUALIFICATION",
        "accepted_dispositions": ("V5_QUALIFICATION_PASS",),
        "accepted_adjudication_sha256": P.ACCEPTED_ADJUDICATION_SHA256,
        "machinery_local_subject_keys": MACHINERY_LOCAL_SUBJECT_KEYS,
        "required_for_admission": True,
    }


# ---------------------------------------------------------------------------
# Inventory arm construction
# ---------------------------------------------------------------------------

def cold_snapshot(node_id: str) -> dict:
    path = (P.ARM_B_COLD_INVENTORY_01 if node_id == "inferswarm01"
            else P.ARM_B_COLD_INVENTORY_03)
    document = json.loads(path.read_text())
    return {
        "node_id": document["node_id"],
        "sequence": document["sequence"],
        "source": document["source"],
        "verified_objects": [
            {"content_digest": obj["content_digest"],
             "length": obj["length"],
             "byte_digest_verified": bool(obj["byte_digest_verified"])}
            for obj in document["verified_objects"]],
        "entries": [],
    }


def warm_snapshot(record: dict) -> dict:
    """Normalize one fresh observation record into a snapshot document."""
    problems = record.get("problems") or []
    if problems:
        raise SystemExit(
            f"ISSUE182_COMPARE_FAIL: warm observation problems on "
            f"{record.get('host')}: {problems}")
    if not record.get("byte_preservation_proven"):
        raise SystemExit("ISSUE182_COMPARE_FAIL: byte preservation unproven")
    fence = record.get("fence") or {}
    if fence.get("processes"):
        raise SystemExit(
            "ISSUE182_COMPARE_FAIL: execution-bearing processes live")
    return {
        "node_id": record["host"],
        "sequence": 2,
        "source": {"source_id": record["host"],
                   "endpoint": f"file://{P.CACHE_ROOT}"},
        "verified_objects": [
            {"content_digest": obj["content_digest"],
             "length": obj["length"],
             "byte_digest_verified": bool(obj["byte_digest_verified"])}
            for obj in record["verified_objects"]],
        "entries": [],
    }


def check_warm_against_retained(warm: dict, node_id: str) -> None:
    """Cross-bound the fresh scan to the retained Arm-B post-acquisition
    inventory: every object the accepted campaign verified must still be
    present with identical (content_digest, length)."""
    path = ARM_B_POST_01 if node_id == "inferswarm01" else ARM_B_POST_03
    retained = json.loads(path.read_text())
    retained_set = {(obj["content_digest"], obj["length"])
                    for obj in retained["verified_objects"]}
    fresh_set = {(obj["content_digest"], obj["length"])
                 for obj in warm["verified_objects"]}
    missing = retained_set - fresh_set
    if missing:
        raise SystemExit(
            f"ISSUE182_COMPARE_FAIL: cache drift vs retained Arm-B post "
            f"inventory on {node_id}: {sorted(missing)[:3]}")


def run_arm(planner_inputs: dict, snapshots: list[dict]) -> dict:
    coordinator = Coordinator(node_sources=deepcopy(NODE_SOURCES),
                              origin_sources=deepcopy(ORIGIN_SOURCES))
    requirements = coordinator.freeze(
        planner_inputs["plan"], planner_inputs["resolver"])
    if canonical_json_bytes(requirements) != planner_inputs[
            "requirements_canonical"]:
        raise SystemExit(
            "ISSUE182_COMPARE_FAIL: coordinator freeze does not reproduce "
            "the retained Arm-B requirements byte-for-byte")
    for snapshot in snapshots:
        coordinator.ingest(VerifiedInventory(deepcopy(snapshot),
                                              _SNAPSHOT_ISSUER))
    planner = AdmissionPlanner(
        candidates=deepcopy(planner_inputs["candidates"]),
        feasibility=deepcopy(planner_inputs["feasibility"]),
        qualification_records=[deepcopy(
            planner_inputs["qualification_record"])],
        qualification_policy=deepcopy(planner_inputs["policy"]),
        requirements_by_candidate={
            P.SUBJECT["candidate"]: deepcopy(
                planner_inputs["requirements"])},
        path_evidence_by_candidate={
            P.SUBJECT["candidate"]: deepcopy(
                planner_inputs["path_evidence"])},
        evidence_contract=deepcopy(planner_inputs["contract"]),
        coordinators_by_candidate={
            P.SUBJECT["candidate"]: coordinator},
    )
    return planner.rank()


def summarize(decision: dict) -> dict:
    rows = {}
    for row in decision["candidates"]:
        rows[row["candidate_id"]] = {
            "admissible": row["admissible"],
            "admission_failures": row["admission_failures"],
            "gates": row["gates"],
            "ranking_status": row["ranking_status"],
            "ranking_reason": row["ranking_reason"],
            "ranking_value": row["ranking_value"],
            "missing_bytes": row["missing_bytes"],
            "required_bytes": row["required_bytes"],
        }
    return {
        "objective": decision["objective"],
        "selected_candidate_id": decision["selected_candidate_id"],
        "ranking_order": decision["ranking_order"],
        "rows": rows,
    }


def compare(cold: dict, warm: dict, inputs_identity: dict) -> dict:
    problems: list[str] = []
    if cold["objective"] != MIN_TRANSITION_COST or \
            warm["objective"] != MIN_TRANSITION_COST:
        problems.append("objective drift")
    ids = sorted(cold["rows"])
    if ids != sorted(warm["rows"]):
        problems.append("candidate set drift between arms")
    gate_unchanged = {}
    for candidate_id in ids:
        cold_row, warm_row = cold["rows"][candidate_id], warm["rows"][candidate_id]
        gate_unchanged[candidate_id] = cold_row["gates"] == warm_row["gates"]
        for gate in ("technical_feasibility", "hard_policy_eligible",
                     "integrity_eligible", "qualification_applicability"):
            cold_gate = cold_row["gates"][gate]
            warm_gate = warm_row["gates"][gate]
            cold_pass = cold_gate.get("passed", cold_gate.get("status"))
            warm_pass = warm_gate.get("passed", warm_gate.get("status"))
            if cold_pass is not None and warm_pass is not None:
                if not cold_pass and warm_pass:
                    problems.append(
                        f"{candidate_id}: gate {gate} failed-cold passes-warm")
        if cold_row["admissible"] != warm_row["admissible"]:
            problems.append(f"{candidate_id}: admissibility moved")
    if not all(gate_unchanged.values()):
        problems.append("gate ledger changed between arms")

    v5 = P.SUBJECT["candidate"]
    cold_row, warm_row = cold["rows"][v5], warm["rows"][v5]
    if not cold_row["admissible"]:
        problems.append("V5 candidate not admissible in cold arm")
    locality_changed = (cold_row["missing_bytes"] != warm_row["missing_bytes"])
    economics_changed = (cold_row["ranking_value"]
                         != warm_row["ranking_value"])
    if cold_row["missing_bytes"] < warm_row["missing_bytes"]:
        problems.append("warm arm missing bytes increased")
    if economics_changed and not locality_changed:
        problems.append("economics moved without locality change")
    if locality_changed and not economics_changed:
        problems.append("locality moved without economics change")
    if warm_row["ranking_status"] != "RANKED":
        problems.append("V5 candidate unranked in warm arm")
    selected_same = cold["selected_candidate_id"] == warm["selected_candidate_id"]
    if warm["selected_candidate_id"] != v5:
        problems.append("warm selection is not the admissible V5 candidate")
    for candidate_id in ids:
        row = warm["rows"][candidate_id]
        if not row["admissible"] and row["ranking_status"] == "RANKED":
            problems.append(f"{candidate_id}: inadmissible but ranked")
    return {
        "schema": P.COMPARISON_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "attempt_id": P.ATTEMPT_ID,
        "objective": MIN_TRANSITION_COST,
        "inputs_identity": inputs_identity,
        "gate_ledger_unchanged": gate_unchanged,
        "all_gates_unchanged": all(gate_unchanged.values()),
        "selection": {
            "cold": cold["selected_candidate_id"],
            "warm": warm["selected_candidate_id"],
            "unchanged": selected_same,
        },
        "v5": {
            "cold": {
                "missing_bytes": cold_row["missing_bytes"],
                "required_bytes": cold_row["required_bytes"],
                "estimated_transition_seconds": cold_row["ranking_value"],
                "ranking_status": cold_row["ranking_status"],
            },
            "warm": {
                "missing_bytes": warm_row["missing_bytes"],
                "required_bytes": warm_row["required_bytes"],
                "estimated_transition_seconds": warm_row["ranking_value"],
                "ranking_status": warm_row["ranking_status"],
            },
            "locality_changed": locality_changed,
            "economics_changed": economics_changed,
        },
        "per_candidate": {
            candidate_id: {"cold": cold["rows"][candidate_id],
                           "warm": warm["rows"][candidate_id]}
            for candidate_id in ids},
        "ranking_order": {"cold": cold["ranking_order"],
                          "warm": warm["ranking_order"]},
        "problems": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warm-01", type=Path, required=True)
    parser.add_argument("--warm-03", type=Path, required=True)
    parser.add_argument("--out", type=Path,
                        default=P.EVIDENCE_DIR / "comparison.json")
    parser.add_argument("--skip-retained-cross-check", action="store_true",
                        help="test fixture mode: synthetic warm snapshots")
    args = parser.parse_args()

    requirements = json.loads(P.ARM_B_REQUIREMENTS.read_text())
    plan = json.loads(P.ARM_B_PLAN.read_text())
    candidates = load_candidates()
    roles = load_cu_roles()
    table = build_artifact_table(requirements)
    resolver = make_resolver(table)

    # validate the plan builder + resolver reproduce the retained plan and
    # requirements byte-for-byte for the accepted V5 candidate
    v5_candidate = next(c for c in candidates
                        if c["candidate_id"] == P.SUBJECT["candidate"])
    rebuilt_plan = build_plan(v5_candidate, plan["model"], 48)
    if canonical_json_bytes(rebuilt_plan) != canonical_json_bytes(plan):
        raise SystemExit(
            "ISSUE182_COMPARE_FAIL: plan builder does not reproduce the "
            "retained Arm-B execution plan")

    authority = json.loads((P.EVIDENCE_DIR / "authority.json").read_text())
    bandwidth = {node: entry["bandwidth_bytes_per_second"]
                 for node, entry in
                 authority["path_bandwidth"]["per_node"].items()}
    gpu_totals = {}
    for cu_id, total in authority["capacity_method"][
            "pinned_gpu_total_bytes"].items():
        gpu_totals[cu_id] = total

    planner_inputs = {
        "candidates": candidates,
        "feasibility": build_feasibility(candidates, table, plan["model"],
                                         48, gpu_totals, roles),
        "qualification_record": accepted_v5_qualification_record(P.ROOT),
        "policy": qualification_policy(),
        "plan": plan,
        "resolver": resolver,
        "requirements": requirements,
        "requirements_canonical": canonical_json_bytes(requirements),
        "path_evidence": build_path_evidence(requirements, bandwidth),
        "contract": dict(P.PLANNING_EVIDENCE_CONTRACT),
    }
    inputs_identity = {
        "candidates_digest": digest_of_bytes(canonical_json_bytes(
            planner_inputs["candidates"])),
        "feasibility_digest": digest_of_bytes(canonical_json_bytes(
            planner_inputs["feasibility"])),
        "qualification_record_digest":
            planner_inputs["qualification_record"]["record_digest"],
        "policy_digest": digest_of_bytes(canonical_json_bytes(
            planner_inputs["policy"])),
        "requirements_digest": requirements["requirements_digest"],
        "plan_digest": plan["plan_digest"],
        "path_evidence_digest": digest_of_bytes(canonical_json_bytes(
            planner_inputs["path_evidence"])),
        "contract_digest": digest_of_bytes(canonical_json_bytes(
            planner_inputs["contract"])),
        "identical_across_arms": True,
        "note": ("every non-inventory planning input is constructed once "
                 "and deep-copied into both arms; the digests above pin "
                 "the exact bytes both arms consumed"),
    }

    cold_snapshots = [cold_snapshot("inferswarm01"),
                      cold_snapshot("inferswarm03")]
    warm_record_01 = json.loads(args.warm_01.read_text())
    warm_record_03 = json.loads(args.warm_03.read_text())
    warm_snapshots = [warm_snapshot(warm_record_01),
                      warm_snapshot(warm_record_03)]
    if not args.skip_retained_cross_check:
        check_warm_against_retained(warm_snapshots[0], "inferswarm01")
        check_warm_against_retained(warm_snapshots[1], "inferswarm03")

    cold_decision = summarize(run_arm(planner_inputs, cold_snapshots))
    warm_decision = summarize(run_arm(planner_inputs, warm_snapshots))
    document = compare(cold_decision, warm_decision, inputs_identity)
    document["cold_arm"] = cold_decision
    document["warm_arm"] = warm_decision
    write_json(args.out, document)
    print(json.dumps({
        "comparison": str(args.out),
        "problems": document["problems"],
        "all_gates_unchanged": document["all_gates_unchanged"],
        "v5": document["v5"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
