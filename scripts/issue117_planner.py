#!/usr/bin/env python3
"""Issue #117 generic admission planner (model-independent, CPU-only).

Owns the planner-side gates of the accepted "strategy constrains; planner
chooses" rule, extended with the #117 qualification-applicability barrier:

    strategy legal candidates
        -> technical feasibility (operator capacity model)
        -> hard operator policy
        -> integrity eligibility
        -> qualification/evidence applicability   (new; independent gate)
        -> candidate admission
        -> locality ranking per stage (accepted #103 semantics, reused)
        -> deterministic candidate selection + explanations

This module must not import the strategy module and must not contain any
model-family, product, layer-index, or accepted-campaign branch. Tests
enforce that statically. Ranking never overrides an exclusion: a candidate
that is technically feasible but ``QUALIFICATION_NOT_APPLICABLE`` stays
ineligible for the correctness-bearing arm no matter how cheap its
transition would be.

Also provides the compact result-fencing authority used to prove that
session/epoch/realization/plan/operation/position mismatches fail closed.

Pure stdlib.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from issue103_planner import (
    EXCLUDED,
    FEASIBLE_UNRANKED,
    MIN_TRANSITION_COST,
    RANKED,
    LocalityPlanner,
    account_transfer_events,
    purity_audit,
)
from issue99_artifact_core import (
    validate_self_identity,
)
from issue117_subject_identity import MACHINERY_LOCAL_SUBJECT_KEYS, subject_digest

QUALIFICATION_POLICY_STRICT = "REQUIRE_ACCEPTED_EXECUTION_QUALIFICATION"

QUALIFICATION_APPLICABLE = "QUALIFICATION_APPLICABLE"
QUALIFICATION_NOT_APPLICABLE = "QUALIFICATION_NOT_APPLICABLE"

REASON_MATCHED_ACCEPTED_RECORD = "MATCHED_ACCEPTED_QUALIFICATION_RECORD"
REASON_NO_ACCEPTED_EVIDENCE = "NO_ACCEPTED_QUALIFICATION_EVIDENCE"
REASON_SUBJECT_MISMATCH = "QUALIFICATION_SUBJECT_MISMATCH"
REASON_EVIDENCE_NOT_TERMINAL_PASS = "QUALIFICATION_EVIDENCE_NOT_TERMINAL_PASS"
REASON_MALFORMED_RECORD = "MALFORMED_QUALIFICATION_RECORD"
REASON_RECORD_NOT_BOUND_TO_ACCEPTED_AUTHORITY = "RECORD_NOT_BOUND_TO_ACCEPTED_AUTHORITY"

GATE_TECHNICAL = "technical_feasibility"
GATE_HARD_POLICY = "hard_policy_eligible"
GATE_INTEGRITY = "integrity_eligible"
GATE_QUALIFICATION = "qualification_applicability"


class PlannerError(RuntimeError):
    """Fail-closed planner misuse."""


# ---------------------------------------------------------------------------
# Qualification-applicability gate (generic, evidence-digest based)
# ---------------------------------------------------------------------------


def _validate_qualification_record(record: Mapping[str, Any], *,
                                   accepted_adjudication_sha256: str) -> tuple[dict[str, Any] | None, str | None]:
    """Validate one record against its own subject and the accepted authority.

    Returns ``(record, None)`` when the record is usable evidence, else
    ``(None, reason)``. A record is trusted only when it is self-consistent
    (its subject digest recomputes from its subject) AND its terminal
    adjudication identity equals the policy's accepted identity.
    """
    for field in ("schema", "qualification_record_id", "authority",
                  "qualification_subject", "qualification_subject_digest",
                  "record_digest"):
        if field not in record:
            return None, REASON_MALFORMED_RECORD
    try:
        validate_self_identity(dict(record), identity_field="record_digest")
    except Exception:
        return None, REASON_MALFORMED_RECORD
    authority = record["authority"]
    if not isinstance(authority, Mapping) or "terminal_disposition" not in authority:
        return None, REASON_MALFORMED_RECORD
    subject = record["qualification_subject"]
    if not isinstance(subject, Mapping):
        return None, REASON_MALFORMED_RECORD
    try:
        recomputed = subject_digest(subject)
    except Exception:
        return None, REASON_MALFORMED_RECORD
    if recomputed != record["qualification_subject_digest"]:
        return None, REASON_MALFORMED_RECORD
    if authority.get("terminal_adjudication_sha256") != accepted_adjudication_sha256:
        return None, REASON_RECORD_NOT_BOUND_TO_ACCEPTED_AUTHORITY
    return dict(record), None


def _candidate_subject_digest(candidate: Mapping[str, Any], *,
                              machinery_local_subject_keys: Sequence[str] = ()) -> str:
    """Recompute a candidate's qualification-subject digest from its subject.

    The caller-supplied ``qualification_subject_digest`` is never trusted:
    the digest used for qualification is always recomputed from the exact
    subject the candidate carries, over the shared execution-equality
    projection (``issue99_artifact_core.subject_digest``). Machinery-local
    subject keys declared by the policy (e.g. content bindings that are
    enforced by the strategy/catalog machinery rather than by the accepted
    evidence) must be present on the candidate subject and are projected out
    of the matched digest on BOTH sides.
    """
    subject = candidate.get("qualification_subject")
    if not isinstance(subject, Mapping):
        raise PlannerError(
            f"candidate {candidate.get('candidate_id')!r} carries no "
            "qualification subject; applicability cannot be derived")
    for key in machinery_local_subject_keys:
        if key not in subject:
            raise PlannerError(
                f"candidate {candidate.get('candidate_id')!r} subject is "
                f"missing the machinery-local identity field {key!r}; "
                "applicability cannot be derived")
    recomputed = subject_digest(
        subject, machinery_local_subject_keys=machinery_local_subject_keys)
    declared = candidate.get("qualification_subject_digest")
    if declared != recomputed:
        raise PlannerError(
            f"candidate {candidate.get('candidate_id')!r} declared subject "
            f"digest {declared!r} does not match its own subject "
            f"({recomputed!r})")
    return recomputed


def evaluate_qualification_applicability(
    candidate: Mapping[str, Any],
    qualification_records: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Mechanically derive whether a candidate may inherit accepted evidence.

    A candidate is applicable when its execution-equality subject digest —
    always recomputed from the candidate's own subject over the shared
    projection convention — equals the subject digest of an accepted
    terminal-pass record whose terminal adjudication identity is bound to
    the policy's accepted authority. Nothing about the candidate's content
    is interpreted here: the digest comparison is the whole gate, so any
    material change of execution-equality identity (geometry, device,
    backend, weights authority, representation) breaks applicability
    mechanically.
    """
    if policy["policy"] != QUALIFICATION_POLICY_STRICT:
        raise PlannerError(f"unsupported qualification policy {policy['policy']!r}")
    accepted_authority = policy.get("accepted_adjudication_sha256")
    if not (isinstance(accepted_authority, str) and accepted_authority.strip()):
        raise PlannerError(
            "qualification policy carries no accepted adjudication identity")
    machinery_local_subject_keys = tuple(
        policy.get("machinery_local_subject_keys", ()))
    unknown_local_keys = sorted(
        set(machinery_local_subject_keys) - set(MACHINERY_LOCAL_SUBJECT_KEYS))
    if unknown_local_keys:
        raise PlannerError(
            f"qualification policy declares unknown machinery-local subject "
            f"keys {unknown_local_keys}")
    candidate_digest = _candidate_subject_digest(
        candidate, machinery_local_subject_keys=machinery_local_subject_keys)
    valid_records = []
    malformed_record_ids = []
    unbound_record_ids = []
    for record in qualification_records:
        validated, reason = _validate_qualification_record(
            record, accepted_adjudication_sha256=accepted_authority)
        if validated is None:
            if reason == REASON_RECORD_NOT_BOUND_TO_ACCEPTED_AUTHORITY:
                unbound_record_ids.append(
                    str(record.get("qualification_record_id", "<unidentified>")))
            else:
                malformed_record_ids.append(
                    str(record.get("qualification_record_id", "<unidentified>")))
            continue
        valid_records.append(validated)
    accepted = set(policy.get("accepted_dispositions", ()))
    passing = [record for record in valid_records
               if record["authority"]["terminal_disposition"] in accepted]
    if not passing:
        reason = (REASON_EVIDENCE_NOT_TERMINAL_PASS if valid_records
                  else REASON_NO_ACCEPTED_EVIDENCE)
        return {"status": QUALIFICATION_NOT_APPLICABLE,
                "reason": reason, "matched_record_ids": [],
                "malformed_record_ids": sorted(malformed_record_ids),
                "unbound_record_ids": sorted(unbound_record_ids)}
    matched = [record for record in passing
               if record["qualification_subject_digest"] == candidate_digest]
    if not matched:
        return {"status": QUALIFICATION_NOT_APPLICABLE,
                "reason": REASON_SUBJECT_MISMATCH, "matched_record_ids": [],
                "malformed_record_ids": sorted(malformed_record_ids),
                "unbound_record_ids": sorted(unbound_record_ids)}
    return {
        "status": QUALIFICATION_APPLICABLE,
        "reason": REASON_MATCHED_ACCEPTED_RECORD,
        "matched_record_ids": sorted(
            record["qualification_record_id"] for record in matched),
        "malformed_record_ids": sorted(malformed_record_ids),
        "unbound_record_ids": sorted(unbound_record_ids),
    }


# ---------------------------------------------------------------------------
# Admission planner
# ---------------------------------------------------------------------------


class AdmissionPlanner:
    """Gate legal candidates, then rank admissible ones by locality economics.

    ``candidates`` come from the strategy boundary and carry opaque
    ``qualification_subject_digest`` values. Each candidate has its own frozen
    plan, participant requirements, and path evidence; locality ranking
    reuses the accepted issue #103 planner per candidate stage.
    """

    def __init__(self, *, candidates: Sequence[Mapping[str, Any]],
                 feasibility: Mapping[str, Mapping[str, Any]],
                 qualification_records: Sequence[Mapping[str, Any]],
                 qualification_policy: Mapping[str, Any],
                 requirements_by_candidate: Mapping[str, Mapping[str, Any]],
                 path_evidence_by_candidate: Mapping[str, Sequence[Mapping[str, Any]]],
                 evidence_contract: Mapping[str, Any] | None = None,
                 coordinators_by_candidate: Mapping[str, Any] | None = None):
        self.candidates = [deepcopy(candidate) for candidate in candidates]
        self.feasibility = feasibility
        self.qualification_records = qualification_records
        self.qualification_policy = qualification_policy
        self.requirements_by_candidate = requirements_by_candidate
        self.path_evidence_by_candidate = path_evidence_by_candidate
        self.evidence_contract = evidence_contract or {}
        self._coordinators_by_candidate = coordinators_by_candidate or {}
        self._locality: dict[str, LocalityPlanner] = {}

    def coordinator_for(self, candidate_id: str) -> Any:
        coordinator = self._coordinators_by_candidate.get(candidate_id)
        if coordinator is None:
            raise PlannerError(f"no coordinator bound for candidate {candidate_id}")
        return coordinator

    def _stage_entries(self, candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
        requirements = self.requirements_by_candidate[candidate["candidate_id"]]
        feasibility = self.feasibility[candidate["candidate_id"]]
        stage_feasibility = {
            "technical_feasibility": bool(feasibility["technical_feasibility"]),
            "hard_policy_eligible": bool(feasibility["hard_policy_eligible"]),
            "integrity_eligible": bool(feasibility["integrity_eligible"]),
        }
        entries = []
        for index in range(candidate["stage_count"]):
            participant_id = f"{candidate['candidate_id']}.stage-{index + 1}"
            matches = [p for p in requirements["participants"]
                       if p["participant_id"] == participant_id]
            if len(matches) != 1:
                raise PlannerError(
                    f"no frozen requirements for stage participant {participant_id}")
            participant = matches[0]
            entries.append({
                "candidate_id": f"{candidate['candidate_id']}::stage-{index + 1}",
                "participant_id": participant_id,
                "node_id": participant["node_id"],
                "target_descriptor": {"execution_unit_id": participant["execution_unit_id"]},
                "feasibility": dict(stage_feasibility),
            })
        return entries

    def _locality_planner(self, candidate: Mapping[str, Any]) -> LocalityPlanner:
        candidate_id = candidate["candidate_id"]
        if candidate_id not in self._locality:
            self._locality[candidate_id] = LocalityPlanner(
                coordinator=self.coordinator_for(candidate_id),
                requirements=self.requirements_by_candidate[candidate_id],
                candidates=self._stage_entries(candidate),
                path_evidence=self.path_evidence_by_candidate.get(candidate_id, []),
                execution_evidence=[],
                evidence_contract=self.evidence_contract,
            )
        return self._locality[candidate_id]

    def gate_ledger(self) -> dict[str, dict[str, Any]]:
        """Every gate outcome for every candidate, with no silent exclusion."""
        ledger = {}
        for candidate in self.candidates:
            feasibility = self.feasibility[candidate["candidate_id"]]
            known = feasibility.get("technical_feasibility_known", True)
            gates = {
                GATE_TECHNICAL: {
                    "passed": bool(feasibility["technical_feasibility"]),
                    "known": bool(known),
                    "reason": None if feasibility["technical_feasibility"]
                    else ("TECHNICAL_FEASIBILITY_UNKNOWN" if not known
                          else "CAPACITY_INFEASIBLE"),
                },
                GATE_HARD_POLICY: {
                    "passed": bool(feasibility["hard_policy_eligible"]),
                    "reason": None if feasibility["hard_policy_eligible"]
                    else "HARD_POLICY_EXCLUSION",
                },
                GATE_INTEGRITY: {
                    "passed": bool(feasibility["integrity_eligible"]),
                    "reason": None if feasibility["integrity_eligible"]
                    else "INTEGRITY_EXCLUSION",
                },
                GATE_QUALIFICATION: evaluate_qualification_applicability(
                    candidate, self.qualification_records, self.qualification_policy),
            }
            qualification_required = bool(
                self.qualification_policy.get("required_for_admission", True))
            gates[GATE_QUALIFICATION]["required"] = qualification_required
            admission_failures = []
            if not gates[GATE_TECHNICAL]["passed"]:
                admission_failures.append(gates[GATE_TECHNICAL]["reason"])
            if not gates[GATE_HARD_POLICY]["passed"]:
                admission_failures.append(gates[GATE_HARD_POLICY]["reason"])
            if not gates[GATE_INTEGRITY]["passed"]:
                admission_failures.append(gates[GATE_INTEGRITY]["reason"])
            if (qualification_required
                    and gates[GATE_QUALIFICATION]["status"] != QUALIFICATION_APPLICABLE):
                admission_failures.append(gates[GATE_QUALIFICATION]["reason"])
            ledger[candidate["candidate_id"]] = {
                "candidate_id": candidate["candidate_id"],
                "gates": gates,
                "admissible": not admission_failures,
                "admission_failures": admission_failures,
            }
        return ledger

    def rank(self) -> dict[str, Any]:
        """Admit, rank, select; retain selected/lower-ranked/excluded reasons."""
        ledger = self.gate_ledger()
        candidate_rows = []
        for candidate in self.candidates:
            entry = ledger[candidate["candidate_id"]]
            row = {
                "candidate_id": candidate["candidate_id"],
                "admissible": entry["admissible"],
                "admission_failures": entry["admission_failures"],
                "gates": entry["gates"],
                "stage_count": candidate["stage_count"],
                "estimated_transition_seconds": None,
                "missing_bytes": 0,
                "required_bytes": 0,
                "transfer_events": [],
                "ranking_status": EXCLUDED if not entry["admissible"] else FEASIBLE_UNRANKED,
                "ranking_reason": (entry["admission_failures"][0]
                                   if entry["admission_failures"] else "NOT_EVALUATED"),
                "ranking_value": None,
            }
            if entry["admissible"]:
                stage_decision = self._locality_planner(candidate).rank(MIN_TRANSITION_COST)
                rows = []
                complete = True
                for stage_row in stage_decision["candidates"]:
                    rows.append(stage_row)
                    if stage_row["transition_ranking_status"] != RANKED:
                        complete = False
                row["required_artifact_bytes_by_id"] = {
                    artifact_id: byte_count
                    for row_i in rows
                    for artifact_id, byte_count in
                    row_i["required_artifact_bytes_by_id"].items()}
                row["missing_artifact_ids"] = sorted(
                    {artifact_id for row_i in rows for artifact_id in row_i["missing_artifact_ids"]})
                row["selected_source_descriptor_by_artifact"] = {
                    artifact_id: descriptor
                    for row_i in rows
                    for artifact_id, descriptor in
                    row_i["selected_source_descriptor_by_artifact"].items()}
                row["required_bytes"] = sum(row_i["required_artifact_bytes"] for row_i in rows)
                row["missing_bytes"] = sum(row_i["missing_artifact_bytes"] for row_i in rows)
                row["transfer_events"] = [
                    event for row_i in rows for event in row_i["transfer_events"]]
                if complete:
                    seconds = sum(
                        stage_row["estimated_transition_seconds"]
                        for stage_row in rows)
                    row["estimated_transition_seconds"] = seconds
                    row["ranking_status"] = RANKED
                    row["ranking_reason"] = "MIN_TRANSITION_COST"
                    row["ranking_value"] = seconds
                else:
                    row["ranking_status"] = FEASIBLE_UNRANKED
                    row["ranking_reason"] = next(
                        (stage_row["transition_ranking_reason"] for stage_row in rows
                         if stage_row["transition_ranking_status"] != RANKED),
                        "INCOMPLETE_STAGE_EVIDENCE")
            candidate_rows.append(row)

        rankable = sorted(
            (row for row in candidate_rows if row["ranking_status"] == RANKED),
            key=lambda row: (row["ranking_value"], row["candidate_id"]))
        unranked = sorted(
            (row for row in candidate_rows if row["ranking_status"] != RANKED),
            key=lambda row: row["candidate_id"])
        ordered_ids = ([row["candidate_id"] for row in rankable]
                       + [row["candidate_id"] for row in unranked])
        selected = rankable[0]["candidate_id"] if rankable else None
        explanations = []
        for row in candidate_rows:
            if row["candidate_id"] == selected:
                disposition = "SELECTED"
            elif row["ranking_status"] == RANKED:
                disposition = "LOWER_RANKED"
            elif row["ranking_status"] == EXCLUDED:
                disposition = "EXCLUDED"
            else:
                disposition = "ADMISSIBLE_UNRANKED"
            explanations.append({
                "candidate_id": row["candidate_id"],
                "disposition": disposition,
                "ranking_status": row["ranking_status"],
                "reason": row["ranking_reason"] or row["ranking_status"],
            })
        return {
            "objective": MIN_TRANSITION_COST,
            "selected_candidate_id": selected,
            "ranking_order": ordered_ids,
            "ranked_candidate_ids": [row["candidate_id"] for row in rankable],
            "candidates": sorted(candidate_rows, key=lambda row: row["candidate_id"]),
            "explanations": explanations,
        }

    def _stage_rows(self, candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
        decision = self._locality_planner(candidate).rank(MIN_TRANSITION_COST)
        return list(decision["candidates"])

    def account_transfer_events(self) -> dict[str, Any]:
        """Derive unexplained transition bytes from exact identity (via #103).

        Accounting stays at the stage level and covers admissible candidates
        only: excluded candidates can never legitimately transfer bytes.
        Every expected event is bound by (stage candidate, participant,
        artifact, bytes, authorized source).
        """
        decision = self.rank()
        admissible_ids = {row["candidate_id"] for row in decision["candidates"]
                          if row["admissible"]}
        stage_rows = []
        for candidate in self.candidates:
            if candidate["candidate_id"] not in admissible_ids:
                continue
            stage_rows.extend(self._stage_rows(candidate))
        events = [dict(event)
                  for row in decision["candidates"]
                  for event in row["transfer_events"]]
        return account_transfer_events(stage_rows, events)


def guard_participant_exact(requirements: Mapping[str, Any], *,
                            total_model_weight_bytes: int) -> None:
    """Structural control-plane guard against whole-model requirement injection.

    No participant may require the complete immutable model weight state;
    each participant's assigned weight bytes must be a proper subset. This is
    a necessary structural condition, independent of any strategy semantics.
    """
    for participant in requirements["participants"]:
        weight = sum(record["length"] for record in participant["required_artifacts"]
                     if record["kind"] == "byte_range")
        if total_model_weight_bytes <= 0 or weight >= total_model_weight_bytes:
            raise PlannerError(
                f"REQUIRES_COMPLETE_MODEL_REPOSITORY: "
                f"{participant['participant_id']} requires {weight} of "
                f"{total_model_weight_bytes} weight bytes")


def planner_purity_audit(path, forbidden_tokens) -> dict[str, Any]:
    """Static audit that the planner module carries no model-specific nouns.

    The forbidden-token list is supplied by the caller (proof/tests), so this
    module never needs to spell the nouns it forbids.
    """
    return purity_audit(path, forbidden_tokens)


# ---------------------------------------------------------------------------
# Result fencing (session / epoch / realization / plan / operation / position)
# ---------------------------------------------------------------------------

#: Derived counter names for invalid results found in the committed ledger.
FENCE_DERIVED_COUNTERS = (
    "stale_result_committed",
    "wrong_session_result_committed",
    "wrong_epoch_result_committed",
    "wrong_realization_result_committed",
    "wrong_plan_result_committed",
    "wrong_contract_result_committed",
    "wrong_position_result_committed",
    "malformed_position_result_committed",
)


def derive_fence_counters(committed_results: Sequence[Mapping[str, Any]], *,
                          authority: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the invalid-commit counters from the committed-result ledger.

    Every admitted result is retained with its full identity. The counters
    are computed by re-inspecting that ledger against the fencing authority
    and the per-operation position sequence — they are never constants. If
    an invalid result were ever admitted (or the ledger were poisoned), the
    corresponding counter would become nonzero here.
    """
    counters = {name: 0 for name in FENCE_DERIVED_COUNTERS}
    pointers: dict[str, int] = {}
    committed_by_operation: dict[str, int] = {}
    for entry in committed_results:
        operation = entry.get("operation")
        invalid: list[str] = []
        if not isinstance(operation, str) or not operation:
            counters["malformed_position_result_committed"] += 1
            continue
        if entry.get("session_id") != authority.get("session_id"):
            invalid.append("wrong_session_result_committed")
        if entry.get("epoch") != authority.get("epoch"):
            invalid.append("wrong_epoch_result_committed")
        if entry.get("realization_id") != authority.get("realization_id"):
            invalid.append("wrong_realization_result_committed")
        if entry.get("plan_digest") != authority.get("plan_digest"):
            invalid.append("wrong_plan_result_committed")
        if entry.get("contract_id") != authority.get("contract_id"):
            invalid.append("wrong_contract_result_committed")
        position = entry.get("position")
        if not isinstance(position, int) or isinstance(position, bool):
            invalid.append("malformed_position_result_committed")
        else:
            expected = pointers.get(operation, 0)
            if position < expected:
                invalid.append("stale_result_committed")
            elif position != expected:
                invalid.append("wrong_position_result_committed")
        if invalid:
            for name in invalid:
                counters[name] += 1
        else:
            pointers[operation] = position + 1
            committed_by_operation[operation] = pointers[operation]
    return {
        "committed_by_operation": {
            operation: committed_by_operation.get(operation, 0)
            for operation in sorted(committed_by_operation)},
        **counters,
    }


class ResultFence:
    """Fail-closed result attribution for the ordinary serving path.

    Every committed result must carry the exact session, epoch, realization,
    plan digest, operation, and the next expected commit position for that
    operation. Any mismatch is refused and counted; nothing stale can ever be
    attributed to the current authority. Every attempted result — committed
    or rejected — is retained, and the zero-invariant counters are derived
    from the committed-result ledger, never asserted.
    """

    def __init__(self, *, contract_id: str, session_id: str, epoch: int,
                 realization_id: str, plan_digest: str,
                 operations: Sequence[str]):
        self.authority = {
            "contract_id": contract_id,
            "session_id": session_id,
            "epoch": int(epoch),
            "realization_id": realization_id,
            "plan_digest": plan_digest,
        }
        self._operations = {operation: {"next_position": 0}
                            for operation in operations}
        self.committed_results: list[dict[str, Any]] = []
        self.rejections: list[dict[str, Any]] = []

    def commit(self, result: Mapping[str, Any]) -> dict[str, Any]:
        """Attribute one result; raise and record on any fence mismatch."""
        operation = result.get("operation")
        if not isinstance(operation, str):
            return self._reject(result, "UNKNOWN_OPERATION")
        state = self._operations.get(operation)
        if state is None:
            return self._reject(result, "UNKNOWN_OPERATION")
        expected = self.authority
        if result.get("session_id") != expected["session_id"]:
            return self._reject(result, "WRONG_SESSION")
        if result.get("epoch") != expected["epoch"]:
            return self._reject(result, "WRONG_EPOCH")
        if result.get("realization_id") != expected["realization_id"]:
            return self._reject(result, "WRONG_REALIZATION")
        if result.get("plan_digest") != expected["plan_digest"]:
            return self._reject(result, "WRONG_PLAN")
        if result.get("contract_id") != expected["contract_id"]:
            return self._reject(result, "WRONG_CONTRACT")
        position = result.get("position")
        if not isinstance(position, int) or isinstance(position, bool):
            return self._reject(result, "MALFORMED_POSITION")
        if position != state["next_position"]:
            return self._reject(result, "WRONG_POSITION")
        self.committed_results.append({
            "contract_id": result.get("contract_id"),
            "session_id": result.get("session_id"),
            "epoch": result.get("epoch"),
            "realization_id": result.get("realization_id"),
            "plan_digest": result.get("plan_digest"),
            "operation": operation,
            "position": position,
            "request_identity": result.get("request_identity"),
            "expected_position": state["next_position"],
        })
        state["next_position"] += 1
        return {"committed": True, "operation": operation, "position": position,
                "authority": dict(expected)}

    def _reject(self, result: Mapping[str, Any], reason: str) -> dict[str, Any]:
        self.rejections.append({
            "reason": reason,
            "result": {
                "contract_id": result.get("contract_id"),
                "session_id": result.get("session_id"),
                "epoch": result.get("epoch"),
                "realization_id": result.get("realization_id"),
                "plan_digest": result.get("plan_digest"),
                "operation": result.get("operation"),
                "position": result.get("position"),
                "request_identity": result.get("request_identity"),
            },
        })
        raise PlannerError(f"{reason}: fenced result rejected")

    def summary(self) -> dict[str, Any]:
        """Zero-invariant counters derived from the retained result records."""
        derived = derive_fence_counters(self.committed_results,
                                        authority=self.authority)
        return {
            "authority": dict(self.authority),
            "attempted_result_count":
                len(self.committed_results) + len(self.rejections),
            **derived,
            "fence_rejections": len(self.rejections),
            "rejection_reasons": sorted({entry["reason"] for entry in self.rejections}),
        }
