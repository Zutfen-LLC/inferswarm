"""Internal generic ranking seam for issue #103."""
from __future__ import annotations

import ast
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import fail, self_digest


MIN_TRANSITION_COST = "MIN_TRANSITION_COST"
WARM_DECODE_THROUGHPUT = "WARM_DECODE_THROUGHPUT"
RANKED = "RANKED"
FEASIBLE_UNRANKED = "FEASIBLE_UNRANKED"
EXCLUDED = "EXCLUDED"

def _descriptor_key(value: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(dict(value))


def _same_descriptor(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _descriptor_key(left) == _descriptor_key(right)


def _evidence_identity(document: Mapping[str, Any]) -> str:
    return self_digest(document, identity_field="evidence_digest")


def validate_path_evidence(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one frozen path-bandwidth record."""
    required = {
        "schema", "candidate_id", "participant_id", "node_id", "artifact_id",
        "source", "target_node_id", "target", "path_id", "bandwidth_bytes_per_second",
        "evidence_version", "evidence_identity", "applicability_context",
        "requirement_identity", "plan_digest", "requirements_digest", "evidence_digest",
    }
    if set(document) != required or document["schema"] != "issue103.path-evidence/1":
        raise ValueError("malformed path evidence")
    if document["evidence_digest"] != _evidence_identity(document):
        raise ValueError("path evidence identity mismatch")
    return dict(document)


def validate_execution_evidence(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one frozen execution-performance record."""
    required = {
        "schema", "candidate_id", "participant_id", "node_id", "score", "metric", "units",
        "evidence_version", "evidence_identity", "applicability_context", "plan_digest",
        "requirements_digest", "evidence_digest",
    }
    if set(document) != required or document["schema"] != "issue103.execution-evidence/1":
        raise ValueError("malformed execution evidence")
    if document["evidence_digest"] != _evidence_identity(document):
        raise ValueError("execution evidence identity mismatch")
    return dict(document)


class LocalityPlanner:
    """Rank legal candidates after exact requirement and source resolution."""

    def __init__(self, *, coordinator, requirements: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]],
                 path_evidence: Sequence[Mapping[str, Any]],
                 execution_evidence: Sequence[Mapping[str, Any]],
                 evidence_contract: Mapping[str, Any]):
        self.coordinator = coordinator
        self.requirements = deepcopy(requirements)
        self.candidates = [deepcopy(candidate) for candidate in candidates]
        self.path_evidence = [deepcopy(item) for item in path_evidence]
        self.execution_evidence = [deepcopy(item) for item in execution_evidence]
        self.evidence_contract = deepcopy(evidence_contract)

    def _candidate_requirements(self, participant_id: str) -> dict[str, Any]:
        matches = [p for p in self.requirements["participants"]
                   if p["participant_id"] == participant_id]
        if len(matches) != 1:
            raise fail("RECONCILIATION_MISMATCH", "candidate participant is not exact")
        return matches[0]

    def _path_for(self, *, candidate, record, ticket):
        matches = [item for item in self.path_evidence
                   if item.get("candidate_id") == candidate["candidate_id"]
                   and item.get("artifact_id") == record["artifact_id"]]
        if not matches:
            return None, "MISSING_PATH_BANDWIDTH_EVIDENCE"
        evidence = matches[0]
        try:
            validate_path_evidence(evidence)
        except ValueError:
            return None, "RANKING_INPUT_WITHOUT_FROZEN_PROVENANCE"
        contract = self.evidence_contract["path"]
        if (evidence["plan_digest"] != self.requirements["plan_digest"]
                or evidence["requirements_digest"] != self.requirements["requirements_digest"]
                or evidence["requirement_identity"] != record["artifact_id"]
                or evidence["evidence_version"] != contract["evidence_version"]
                or evidence["evidence_identity"] != contract["evidence_identity"]
                or evidence["applicability_context"] != contract["applicability_context"]):
            return None, "RANKING_INPUT_WITHOUT_FROZEN_PROVENANCE"
        if (evidence["participant_id"] != candidate["participant_id"]
                or evidence["node_id"] != candidate["node_id"]
                or evidence["target_node_id"] != candidate["node_id"]
                or not _same_descriptor(evidence["target"], candidate["target_descriptor"])):
            return None, "PATH_EVIDENCE_INAPPLICABLE"
        if not _same_descriptor(evidence["source"], ticket["source"]):
            raise fail("SOURCE_UNAUTHORIZED", "path evidence source is not authorized")
        bandwidth = evidence["bandwidth_bytes_per_second"]
        if not isinstance(bandwidth, (int, float)) or isinstance(bandwidth, bool):
            return None, "INVALID_PATH_BANDWIDTH_EVIDENCE"
        if not math.isfinite(float(bandwidth)) or float(bandwidth) <= 0.0:
            return None, "INVALID_PATH_BANDWIDTH_EVIDENCE"
        return evidence, None

    def _execution_for(self, candidate):
        matches = [item for item in self.execution_evidence
                   if item.get("candidate_id") == candidate["candidate_id"]]
        if len(matches) != 1:
            return None, "MISSING_EXECUTION_EVIDENCE"
        evidence = matches[0]
        try:
            validate_execution_evidence(evidence)
        except ValueError:
            return None, "RANKING_INPUT_WITHOUT_FROZEN_PROVENANCE"
        contract = self.evidence_contract["execution"]
        if (evidence["plan_digest"] != self.requirements["plan_digest"]
                or evidence["requirements_digest"] != self.requirements["requirements_digest"]
                or evidence["evidence_version"] != contract["evidence_version"]
                or evidence["evidence_identity"] != contract["evidence_identity"]
                or evidence["applicability_context"] != contract["applicability_context"]):
            return None, "RANKING_INPUT_WITHOUT_FROZEN_PROVENANCE"
        if (evidence["participant_id"] != candidate["participant_id"]
                or evidence["node_id"] != candidate["node_id"]):
            return None, "EXECUTION_EVIDENCE_INAPPLICABLE"
        score = evidence["score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(float(score)):
            return None, "INVALID_EXECUTION_EVIDENCE"
        return evidence, None

    def _row(self, candidate):
        feasibility = candidate["feasibility"]
        technical = all((feasibility["technical_feasibility"],
                         feasibility["hard_policy_eligible"],
                         feasibility["integrity_eligible"]))
        participant = self._candidate_requirements(candidate["participant_id"])
        delta = self.coordinator.delta(candidate["participant_id"])
        records = {record["artifact_id"]: record for record in participant["required_artifacts"]}
        local_ids = set(delta["local_artifact_ids"])
        missing_ids = set(delta["missing_artifact_ids"])
        selected_sources = {}
        path_ids = {}
        bandwidths = {}
        per_artifact = {}
        transfer_events = []
        reasons = []
        provenance_violations = 0
        for artifact_id in sorted(records):
            record = records[artifact_id]
            ticket = self.coordinator.authorize(delta, artifact_id)
            selected_sources[artifact_id] = deepcopy(ticket["source"])
            if artifact_id in local_ids:
                per_artifact[artifact_id] = 0.0
                continue
            if artifact_id not in missing_ids:
                raise fail("RECONCILIATION_MISMATCH", "delta does not cover exact requirement")
            evidence, reason = self._path_for(candidate=candidate, record=record, ticket=ticket)
            if evidence is None:
                reasons.append(reason)
                if reason == "RANKING_INPUT_WITHOUT_FROZEN_PROVENANCE":
                    provenance_violations += 1
                continue
            seconds = float(record["length"]) / float(evidence["bandwidth_bytes_per_second"])
            per_artifact[artifact_id] = seconds
            path_ids[artifact_id] = evidence["path_id"]
            bandwidths[artifact_id] = evidence["bandwidth_bytes_per_second"]
            transfer_events.append({"candidate_id": candidate["candidate_id"],
                                    "participant_id": candidate["participant_id"],
                                    "artifact_id": artifact_id, "bytes": record["length"],
                                    "source": deepcopy(ticket["source"])})
        priced_missing = [artifact_id for artifact_id in missing_ids if artifact_id in per_artifact]
        transition_seconds = math.fsum(per_artifact[artifact_id] for artifact_id in priced_missing)
        if len(priced_missing) != len(missing_ids):
            transition_seconds = None
        transition_reason = reasons[0] if reasons else None
        execution, execution_reason = self._execution_for(candidate)
        if not technical:
            status, reason, value = EXCLUDED, "TECHNICAL_OR_HARD_ELIGIBILITY_FAILED", None
        else:
            status, reason, value = RANKED, None, None
        return {
            "candidate_id": candidate["candidate_id"],
            "participant_id": candidate["participant_id"],
            "node_id": candidate["node_id"],
            "required_artifact_ids": sorted(records),
            "required_artifact_bytes": sum(r["length"] for r in records.values()),
            "required_artifact_bytes_by_id": {aid: records[aid]["length"] for aid in sorted(records)},
            "verified_local_required_artifact_ids": sorted(local_ids),
            "verified_local_required_bytes": sum(records[aid]["length"] for aid in local_ids),
            "missing_artifact_ids": sorted(missing_ids),
            "missing_artifact_bytes": sum(records[aid]["length"] for aid in missing_ids),
            "locality_evidence_status": "VERIFIED_INVENTORY",
            "source_authorization_status": "EXACT_AUTHORIZATION",
            "selected_source_descriptor_by_artifact": selected_sources,
            "path_evidence_identity_by_nonlocal_artifact": path_ids,
            "bandwidth_bytes_per_second_by_nonlocal_artifact": bandwidths,
            "estimated_transfer_seconds_by_artifact": per_artifact,
            "estimated_transition_seconds": transition_seconds,
            "transform_materialization_seconds": 0.0,
            "technical_feasibility": technical,
            "hard_policy_eligible": feasibility["hard_policy_eligible"],
            "integrity_eligible": feasibility["integrity_eligible"],
            "transition_ranking_status": RANKED if transition_seconds is not None else FEASIBLE_UNRANKED,
            "transition_ranking_reason": transition_reason or "COMPLETE_FROZEN_PATH_EVIDENCE",
            "execution_evidence": deepcopy(execution) if execution else None,
            "execution_evidence_reason": execution_reason,
            "execution_ranking_status": RANKED if execution else FEASIBLE_UNRANKED,
            "execution_ranking_reason": execution_reason or "COMPLETE_FROZEN_EXECUTION_EVIDENCE",
            "ranking_status": status,
            "ranking_reason": reason,
            "ranking_value": value,
            "transfer_events": transfer_events,
            "ranking_input_without_frozen_provenance": provenance_violations,
        }

    def rank(self, objective: str, *, candidate_order: Sequence[Mapping[str, Any]] | None = None):
        if objective not in (MIN_TRANSITION_COST, WARM_DECODE_THROUGHPUT):
            raise ValueError(f"unsupported objective: {objective}")
        candidates = list(candidate_order if candidate_order is not None else self.candidates)
        rows = []
        for candidate in candidates:
            row = self._row(candidate)
            if not row["technical_feasibility"]:
                row["ranking_status"] = EXCLUDED
                row["ranking_reason"] = "TECHNICAL_OR_HARD_ELIGIBILITY_FAILED"
            elif objective == MIN_TRANSITION_COST:
                if row["transition_ranking_status"] == RANKED:
                    row["ranking_status"] = RANKED
                    row["ranking_value"] = row["estimated_transition_seconds"]
                    row["ranking_reason"] = "MIN_TRANSITION_COST"
                else:
                    row["ranking_status"] = FEASIBLE_UNRANKED
                    row["ranking_reason"] = row["transition_ranking_reason"]
            elif row["execution_ranking_status"] == RANKED:
                row["ranking_status"] = RANKED
                row["ranking_value"] = row["execution_evidence"]["score"]
                row["ranking_reason"] = "WARM_DECODE_THROUGHPUT"
            else:
                row["ranking_status"] = FEASIBLE_UNRANKED
                row["ranking_reason"] = row["execution_ranking_reason"]
            row["ranking_objective"] = objective
            rows.append(row)
        rankable = [row for row in rows if row["ranking_status"] == RANKED]
        if objective == MIN_TRANSITION_COST:
            rankable.sort(key=lambda row: (row["ranking_value"], row["candidate_id"]))
        else:
            rankable.sort(key=lambda row: (-row["ranking_value"], row["candidate_id"]))
        unranked = sorted((row for row in rows if row["ranking_status"] != RANKED),
                          key=lambda row: row["candidate_id"])
        ordered = rankable + unranked
        return {
            "objective": objective,
            "selected_candidate_id": ordered[0]["candidate_id"] if rankable else None,
            "ranking_order": [row["candidate_id"] for row in ordered],
            "ranked_candidate_ids": [row["candidate_id"] for row in rankable],
            "costs": {row["candidate_id"]: row["estimated_transition_seconds"]
                      for row in rows},
            "scores": {row["candidate_id"]: row["execution_evidence"]["score"]
                       for row in rows if row["execution_evidence"] is not None},
            "candidates": sorted(rows, key=lambda row: row["candidate_id"]),
        }


def account_transfer_events(rows: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]):
    """Derive unexplained bytes from exact candidate/artifact accounting."""
    expected = {(row["candidate_id"], artifact_id): row["required_artifact_bytes_by_id"][artifact_id]
                for row in rows for artifact_id in row["missing_artifact_ids"]}
    unexplained = 0
    accepted = []
    for event in events:
        key = (event.get("candidate_id"), event.get("artifact_id"))
        if (key not in expected or event.get("bytes") != expected[key]
                or key in accepted):
            unexplained += int(event.get("bytes", 0))
        else:
            accepted.append(key)
    missing = set(expected) - set(accepted)
    missing_bytes = sum(expected[key] for key in missing)
    return {"expected_event_count": len(expected), "accepted_event_count": len(accepted),
            "missing_event_count": len(missing),
            "missing_event_bytes": missing_bytes,
            "unexplained_transition_bytes": unexplained + missing_bytes}


def purity_audit(path: Path, forbidden_tokens: Sequence[str]):
    """Return a static audit of forbidden domain-specific branches."""
    source = path.read_text()
    tree = ast.parse(source)
    names = {node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)}
    lower = source.lower()
    violations = sorted(token for token in forbidden_tokens if token in lower or token in names)
    return {"path": str(path), "forbidden_tokens": list(forbidden_tokens),
            "violations": violations, "planner_model_specific_branches": len(violations)}
