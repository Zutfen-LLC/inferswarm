#!/usr/bin/env python3
"""Issue #95 v4 threshold derivation from complete calibration evidence only.

This CPU-only deriver consumes the frozen corpus and campaign evidence rather
than caller-supplied maxima.  It never executes a model, calibrates hardware,
or decrypts holdout material.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

from issue74_methodology import ENVELOPES, MethodologyError, canonical_json_bytes, sha256_bytes, sha256_file
from issue95_v4_contract import comparator_tier_contract
from issue95_v4_methodology import (
    CONTRACT_ID,
    MARGIN_DEFINITION,
    V4_CALIBRATION_SCHEMA,
    V4_SELECTED_EIGHT_SCHEMA,
    V4_STRESS_COMMITMENT_SCHEMA,
    V4_STRESS_POOL_SCHEMA,
    argmax_tie_break_identity,
    case_e_d,
    decision_domain_construction_identity,
    is_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "docs/qualification/gemma4-12b-it-v4/manifests"
V4_TOOLING_VERSION = "inferswarm.issue95.v4-threshold-tooling/1"
V4_CALIBRATION_CORPUS_SHA256 = "b14d0377bc0ddc0a585f4f216aee52e1ac2b2e1727b140f41d3b3054be40119e"
V4_STRESS_POOL_SHA256 = "22d71e2444bfdfc549c63a3f85cd91a0604d6afff6154f4197bc65091c8e5bd5"
V4_STRESS_COMMITMENT_SHA256 = "f9bad1f61098439e8d0a3b3c240d9ea73893618f49855065a690e5f7ef7928ef"
V4_HOLDOUT_COMMITMENT_SHA256 = "1326b368e8a206693243a6acbb5f53a921fb1113e769c6215cf9d762ed050924"
V4_HOLDOUT_CUSTODY_RECORD_SHA256 = "0c9746e7f2886877318281c81940d8f7235918b5f2e119ed589f314a58111f28"
V4_STATISTICAL_CASES = 1896
V4_SELECTED_STRESS_CASES = 8

_SUMMARY_FIELDS = {
    "schema", "contract_id", "tooling_version", "calibration_corpus_sha256",
    "stress_pool_sha256", "stress_selection_commitment_sha256",
    "reference_margin_summary_sha256", "stress_selection_sha256",
    "decision_domain_manifest_sha256", "evidence_sha256", "statistical_cases",
    "stress_cases",
}
_CASE_FIELDS = {
    "case_id", "case_sha256", "exact_integrity", "finite", "evidence_complete",
    "envelopes", "case_e_d_hex", "decisions",
}
_DECISION_FIELDS = {
    "decision_index", "domain_membership_sha256", "domain_size",
    "decision_local_error_hex",
}
_DOMAIN_DECISION_FIELDS = {"decision_index", "domain_membership_sha256", "domain_size"}


def _hash(document: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(document))


def _require_frozen(document: dict[str, Any], *, sha: str, schema: str, label: str) -> None:
    if not isinstance(document, dict) or document.get("schema") != schema:
        raise MethodologyError(f"v4 {label} schema mismatch")
    if document.get("contract_id") != CONTRACT_ID:
        raise MethodologyError(f"v4 {label} contract mismatch")
    if _hash(document) != sha:
        raise MethodologyError(f"v4 {label} hash mismatch")


def _identities(cases: Any, *, count: int, prefix: str, label: str) -> dict[str, str]:
    if not isinstance(cases, list) or len(cases) != count:
        raise MethodologyError(f"v4 {label} must contain exactly {count} cases")
    result: dict[str, str] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise MethodologyError(f"v4 {label} contains an invalid case")
        case_id, case_sha = case.get("case_id"), case.get("case_sha256")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in result:
            raise MethodologyError(f"v4 {label} contains an invalid or duplicate case ID")
        if not is_sha256(case_sha):
            raise MethodologyError(f"v4 {label} contains an invalid case identity")
        result[case_id] = case_sha
    return result


def _metric(value: Any, *, label: str) -> float:
    if not isinstance(value, str):
        raise MethodologyError(f"{label} must be hexadecimal float evidence")
    try:
        parsed = float.fromhex(value)
    except ValueError as exc:
        raise MethodologyError(f"{label} must be hexadecimal float evidence") from exc
    if not math.isfinite(parsed) or parsed < 0.0:
        raise MethodologyError(f"{label} must be finite and nonnegative")
    return parsed


def _validate_domain(
    domain: dict[str, Any], statistical_ids: dict[str, str], stress_ids: dict[str, str]
) -> dict[str, dict[int, dict[str, Any]]]:
    if not isinstance(domain, dict) or domain.get("schema") != "inferswarm.issue95.v4-decision-domain-manifest/1":
        raise MethodologyError("v4 decision-domain manifest schema mismatch")
    if domain.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v4 decision-domain manifest contract mismatch")
    if domain.get("construction") != decision_domain_construction_identity() or domain.get("k") != 1024:
        raise MethodologyError("v4 decision-domain manifest construction mismatch")
    if domain.get("reference_derived_only") is not True or domain.get("candidate_membership_influence") != "PROHIBITED":
        raise MethodologyError("v4 decision-domain manifest is not reference-only")
    indexed: dict[str, dict[int, dict[str, Any]]] = {}
    for arm, identities in (("statistical_cases", statistical_ids), ("stress_cases", stress_ids)):
        rows = domain.get(arm)
        if not isinstance(rows, list) or len(rows) != len(identities):
            raise MethodologyError(f"v4 domain {arm} count mismatch")
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"case_id", "case_sha256", "decisions"}:
                raise MethodologyError("v4 domain row fields mismatch")
            case_id = row.get("case_id")
            if case_id in seen or row.get("case_sha256") != identities.get(case_id):
                raise MethodologyError("v4 domain case identity mismatch")
            seen.add(case_id)
            decisions = row.get("decisions")
            if not isinstance(decisions, list) or len(decisions) != 8:
                raise MethodologyError("v4 domain requires exactly 8 decision rows")
            rows_by_index: dict[int, dict[str, Any]] = {}
            for decision in decisions:
                if not isinstance(decision, dict) or set(decision) != _DOMAIN_DECISION_FIELDS:
                    raise MethodologyError("v4 domain decision fields mismatch")
                index = decision.get("decision_index")
                if not isinstance(index, int) or index in rows_by_index or not 0 <= index <= 7:
                    raise MethodologyError("v4 domain decision index invalid")
                if not is_sha256(decision.get("domain_membership_sha256")) or not isinstance(decision.get("domain_size"), int) or decision["domain_size"] < 1:
                    raise MethodologyError("v4 domain decision evidence invalid")
                rows_by_index[index] = decision
            if set(rows_by_index) != set(range(8)):
                raise MethodologyError("v4 domain decision indices incomplete")
            indexed[case_id] = rows_by_index
        if seen != set(identities):
            raise MethodologyError("v4 domain case set mismatch")
    return indexed


def _validate_summary_arm(rows: Any, identities: dict[str, str], domains: dict[str, dict[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(identities):
        raise MethodologyError("v4 calibration arm case count mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _CASE_FIELDS:
            raise MethodologyError("v4 case summary fields mismatch")
        case_id = row.get("case_id")
        if case_id in seen or row.get("case_sha256") != identities.get(case_id):
            raise MethodologyError("v4 summary case identity mismatch")
        seen.add(case_id)
        if row.get("exact_integrity") != "PASS" or row.get("finite") is not True or row.get("evidence_complete") is not True:
            raise MethodologyError("v4 case evidence must be exact-integrity PASS, finite, and complete")
        envelopes = row.get("envelopes")
        if not isinstance(envelopes, dict) or set(envelopes) != set(ENVELOPES):
            raise MethodologyError("v4 case must contain all 15 numerical envelopes")
        for identity, value in envelopes.items():
            _metric(value, label=f"{case_id} {identity}")
        decisions = row.get("decisions")
        if not isinstance(decisions, list) or len(decisions) != 8:
            raise MethodologyError("v4 case must contain exactly 8 decision rows")
        errors: list[float] = []
        seen_decisions: set[int] = set()
        for decision in decisions:
            if not isinstance(decision, dict) or set(decision) != _DECISION_FIELDS:
                raise MethodologyError("v4 summary decision fields mismatch")
            index = decision.get("decision_index")
            if not isinstance(index, int) or index in seen_decisions or not 0 <= index <= 7:
                raise MethodologyError("v4 summary decision index invalid")
            seen_decisions.add(index)
            domain = domains.get(case_id, {}).get(index)
            if domain is None or decision.get("domain_membership_sha256") != domain["domain_membership_sha256"] or decision.get("domain_size") != domain["domain_size"]:
                raise MethodologyError("v4 summary decision domain identity mismatch")
            errors.append(_metric(decision.get("decision_local_error_hex"), label=f"{case_id} decision-local error"))
        if seen_decisions != set(range(8)):
            raise MethodologyError("v4 summary decision indices incomplete")
        if _metric(row.get("case_e_d_hex"), label=f"{case_id} case E_D") != case_e_d(errors):
            raise MethodologyError("v4 case E_D does not equal its eight-decision maximum")
    if seen != set(identities):
        raise MethodologyError("v4 calibration arm case set mismatch")
    return rows


def _limit(statistical: Iterable[float], stress: Iterable[float], *, telemetry: bool = False) -> dict[str, str]:
    statistical_max, stress_max = max(statistical), max(stress)
    result = {
        "statistical_max_hex": statistical_max.hex(), "stress_max_hex": stress_max.hex(),
        "limit_hex": max(statistical_max, stress_max).hex(),
        "rule": "max(statistical_max,stress_max)", "comparison": "observed<=limit",
    }
    if telemetry:
        result["qualification_semantics"] = "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE"
    return result


def _replay_selected_stress(pool: dict[str, Any], margins: dict[str, Any], commitment: dict[str, Any]) -> dict[str, Any]:
    """Replay the frozen v4 margin selector without importing its stale v1 ID."""
    required = {"schema", "contract_id", "margin_definition", "stress_pool_sha256", "cases"}
    if not isinstance(margins, dict) or set(margins) != required:
        raise MethodologyError("v4 reference-margin summary fields mismatch")
    if margins.get("schema") != "inferswarm.issue95.v4-reference-margin-summary/1" or margins.get("contract_id") != CONTRACT_ID or margins.get("margin_definition") != MARGIN_DEFINITION:
        raise MethodologyError("v4 reference-margin summary contract mismatch")
    pool_hash = _hash(pool)
    if margins.get("stress_pool_sha256") != pool_hash:
        raise MethodologyError("v4 reference-margin summary pool binding mismatch")
    pool_cases = {case["case_id"]: case for case in pool["cases"]}
    rows = margins.get("cases")
    if not isinstance(rows, list) or len(rows) != len(pool_cases):
        raise MethodologyError("v4 reference-margin summary case count mismatch")
    eligible: list[tuple[float, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"case_id", "case_sha256", "top1_margin_hex"}:
            raise MethodologyError("v4 reference-margin row fields mismatch")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id in seen or row.get("case_sha256") != pool_cases.get(case_id, {}).get("case_sha256"):
            raise MethodologyError("v4 reference-margin case identity mismatch")
        seen.add(case_id)
        margin = _metric(row.get("top1_margin_hex"), label="reference top-1 margin")
        eligible.append((margin, case_id))
    if seen != set(pool_cases) or len(eligible) < 8:
        raise MethodologyError("v4 reference-margin eligibility mismatch")
    eligible.sort(key=lambda item: (item[0], item[1]))
    selected = []
    for group, rows in (("four-smallest-including-zero", eligible[:4]), ("four-largest", eligible[-4:])):
        selected.extend({
            "selection_group": group, "case": pool_cases[case_id],
            "reference_top1_margin_hex": margin.hex(), "exact_zero_margin": margin == 0.0,
        } for margin, case_id in rows)
    return {
        "schema": V4_SELECTED_EIGHT_SCHEMA, "contract_id": CONTRACT_ID,
        "margin_definition": MARGIN_DEFINITION,
        "margin_definition_unchanged_from": "v1 pre-registered producer definition (FreeToken 29e04d0)",
        "stress_pool_sha256": pool_hash, "selection_commitment_sha256": _hash(commitment),
        "reference_margin_summary_sha256": _hash(margins),
        "selection_inputs": "MATCHED_REFERENCE_MARGINS_ONLY",
        "eligibility_rule": commitment["eligibility_rule"], "selection_rule": commitment["selection_rule"],
        "minimum_eligible_cases": commitment["minimum_eligible_cases"],
        "eligible_case_count": len(eligible), "ineligible_case_count": 0, "ineligible_cases": [],
        "selected_count": 8, "selected": selected,
        "state": "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE",
    }


def derive_v4_threshold_artifacts(*, calibration_corpus: dict[str, Any], stress_pool: dict[str, Any],
                                  selection_commitment: dict[str, Any], reference_margin_summary: dict[str, Any],
                                  selected_stress: dict[str, Any], decision_domain_manifest: dict[str, Any],
                                  calibration_summary: dict[str, Any], comparator_contract: dict[str, Any],
                                  holdout_commitment: dict[str, Any], holdout_custody_record: dict[str, Any],
                                  program_sha256: str) -> dict[str, Any]:
    """Fail-closed v4 derivation from frozen identities and complete evidence."""
    _require_frozen(calibration_corpus, sha=V4_CALIBRATION_CORPUS_SHA256, schema=V4_CALIBRATION_SCHEMA, label="calibration corpus")
    _require_frozen(stress_pool, sha=V4_STRESS_POOL_SHA256, schema=V4_STRESS_POOL_SCHEMA, label="stress pool")
    _require_frozen(selection_commitment, sha=V4_STRESS_COMMITMENT_SHA256, schema=V4_STRESS_COMMITMENT_SCHEMA, label="stress commitment")
    _require_frozen(holdout_commitment, sha=V4_HOLDOUT_COMMITMENT_SHA256, schema="inferswarm.issue95.v4-holdout-commitment/1", label="holdout commitment")
    _require_frozen(holdout_custody_record, sha=V4_HOLDOUT_CUSTODY_RECORD_SHA256, schema="inferswarm.issue95.v4-holdout-custody-record/1", label="holdout custody record")
    if holdout_commitment.get("state") != "SEALED_NOT_CONSUMED" or holdout_custody_record.get("holdout_state") != "SEALED_NOT_CONSUMED":
        raise MethodologyError("v4 holdout identity is not sealed and unconsumed")
    if not is_sha256(program_sha256):
        raise MethodologyError("v4 derivation program identity must be SHA-256")
    if canonical_json_bytes(comparator_contract) != canonical_json_bytes(comparator_tier_contract()):
        raise MethodologyError("v4 comparator tier contract mismatch")

    statistical_ids = _identities(calibration_corpus.get("cases"), count=V4_STATISTICAL_CASES, prefix="c95-", label="calibration corpus")
    pool_ids = _identities(stress_pool.get("cases"), count=48, prefix="p95-", label="stress pool")
    replayed = _replay_selected_stress(stress_pool, reference_margin_summary, selection_commitment)
    if canonical_json_bytes(selected_stress) != canonical_json_bytes(replayed):
        raise MethodologyError("SELECTED_EIGHT_NOT_SELECTOR_DERIVED")
    if selected_stress.get("schema") != V4_SELECTED_EIGHT_SCHEMA or selected_stress.get("selected_count") != V4_SELECTED_STRESS_CASES:
        raise MethodologyError("v4 selected stress must contain exactly eight cases")
    stress_ids = _identities([row.get("case") for row in selected_stress.get("selected", [])], count=V4_SELECTED_STRESS_CASES, prefix="p95-", label="selected stress")
    if not set(stress_ids).issubset(pool_ids):
        raise MethodologyError("v4 selected stress contains non-pool identity")

    domain_sha = _hash(decision_domain_manifest)
    domains = _validate_domain(decision_domain_manifest, statistical_ids, stress_ids)
    if not isinstance(calibration_summary, dict) or set(calibration_summary) != _SUMMARY_FIELDS:
        raise MethodologyError("v4 calibration summary fields mismatch")
    if calibration_summary.get("schema") != "inferswarm.issue95.v4-calibration-summary/1" or calibration_summary.get("contract_id") != CONTRACT_ID or calibration_summary.get("tooling_version") != V4_TOOLING_VERSION:
        raise MethodologyError("v4 calibration summary contract mismatch")
    expected_bindings = {
        "calibration_corpus_sha256": _hash(calibration_corpus), "stress_pool_sha256": _hash(stress_pool),
        "stress_selection_commitment_sha256": _hash(selection_commitment),
        "reference_margin_summary_sha256": _hash(reference_margin_summary),
        "stress_selection_sha256": _hash(selected_stress), "decision_domain_manifest_sha256": domain_sha,
    }
    if any(calibration_summary.get(key) != value for key, value in expected_bindings.items()):
        raise MethodologyError("v4 calibration summary evidence binding mismatch")
    hashes = calibration_summary.get("evidence_sha256")
    if not isinstance(hashes, list) or not hashes or len(set(hashes)) != len(hashes) or not all(is_sha256(value) for value in hashes):
        raise MethodologyError("v4 calibration evidence hashes invalid")
    statistical = _validate_summary_arm(calibration_summary.get("statistical_cases"), statistical_ids, domains)
    stress = _validate_summary_arm(calibration_summary.get("stress_cases"), stress_ids, domains)

    core_keys = {f"{row['family']}:{row['metric']}" for row in comparator_contract["core_numerical_pairs"]} | {"decision_local_E_D"}
    telemetry_keys = {f"{row['family']}:{row['metric']}" for row in comparator_contract["mandatory_telemetry_pairs"]}
    if len(core_keys) != 4 or len(telemetry_keys) != 12 or core_keys & telemetry_keys or core_keys | telemetry_keys != set(ENVELOPES) | {"decision_local_E_D"}:
        raise MethodologyError("v4 comparator contract does not preserve four-core/twelve-telemetry semantics")
    def values(key: str, rows: list[dict[str, Any]]) -> Iterable[float]:
        return (_metric(row["case_e_d_hex"], label="case E_D") if key == "decision_local_E_D" else _metric(row["envelopes"][key], label=key) for row in rows)
    core_limits = {key: _limit(values(key, statistical), values(key, stress)) for key in sorted(core_keys)}
    telemetry_bands = {key: _limit(values(key, statistical), values(key, stress), telemetry=True) for key in sorted(telemetry_keys)}
    provenance = {
        "calibration_corpus_sha256": _hash(calibration_corpus),
        "calibration_summary_sha256": _hash(calibration_summary),
        "calibration_evidence_sha256": sorted(hashes),
        "selected_stress_sha256": _hash(selected_stress),
        "decision_domain_manifest_sha256": domain_sha,
        "derivation_program_sha256": program_sha256,
        "holdout_commitment_sha256": _hash(holdout_commitment),
        "holdout_custody_record_sha256": _hash(holdout_custody_record),
        "argmax_tie_break": argmax_tie_break_identity(),
    }
    common = {"contract_id": CONTRACT_ID, "comparator_tier_contract_sha256": _hash(comparator_contract), "provenance": provenance, "holdout_state": "SEALED_NOT_CONSUMED", "manual_editing_or_rounding": "PROHIBITED"}
    return {
        "core_threshold_manifest": common | {"schema": "inferswarm.issue95.v4-core-threshold-manifest/1", "limits": core_limits},
        "telemetry_reference_bands": common | {"schema": "inferswarm.issue95.v4-telemetry-reference-bands/1", "bands": telemetry_bands, "finite_exceedance": "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE"},
    }


def main(argv: Sequence[str] | None = None) -> int:
    raise SystemExit("future physical calibration only; invoke derive_v4_threshold_artifacts from a validated campaign assembler")


if __name__ == "__main__":
    main()
