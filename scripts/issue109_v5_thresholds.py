#!/usr/bin/env python3
"""Issue #109 v5 threshold derivation from complete calibration evidence only.

This CPU-only deriver consumes the frozen corpus and campaign evidence rather
than caller-supplied maxima. It never executes a model, calibrates hardware,
or decrypts holdout material. Ready for the physical execution gate (issue
#110) to invoke once real calibration/stress evidence exists; it cannot
itself produce evidence.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from issue74_methodology import ENVELOPES, MethodologyError, canonical_json_bytes, sha256_bytes, sha256_file
from issue109_v5_contract import comparator_tier_contract
from commit_issue109_holdout import custody_is_satisfied
from issue109_v5_methodology import (
    CONTRACT_ID,
    MARGIN_DEFINITION,
    V5_CALIBRATION_CASES,
    V5_CALIBRATION_SCHEMA,
    V5_SELECTED_EIGHT_SCHEMA,
    V5_SELECTED_STRESS_CASES,
    V5_STRESS_COMMITMENT_SCHEMA,
    V5_STRESS_POOL_CASES,
    V5_STRESS_POOL_SCHEMA,
    argmax_tie_break_identity,
    case_e_d,
    decision_domain_construction_identity,
    is_sha256,
    mixture_components,
)

ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / "docs/qualification/gemma4-12b-it-v5/manifests"
V5_TOOLING_VERSION = "inferswarm.issue109.v5-threshold-tooling/1"
V5_CALIBRATION_CORPUS_SHA256 = "b35f1915231d455cd964e9b645e58269ec63cdf483742907af39cc850f9fdb35"
V5_STRESS_POOL_SHA256 = "e54b10ae86a2bbdf805e54d6f3266785dd9805d05477978a18d5c1ad5bce0c9d"
V5_STRESS_COMMITMENT_SHA256 = "38a1da0c06f5ad6336507e107fb5deb1b278b44aed95ea78a41f647245018eac"
V5_HOLDOUT_COMMITMENT_SHA256 = "b0dcff2a241b20cbd24f1b54f30e77a33512d8ceb12f79afc6c1761b2c994fd2"
V5_HOLDOUT_CUSTODY_RECORD_SHA256 = "6adaa4e5743cdee65f659806d81039dca499c7997cf0240ce92d48cfc2a23b46"

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
    "decision_local_error_hex", "consumer_logit_reducers",
}
_DOMAIN_DECISION_FIELDS = {"decision_index", "domain_membership_sha256", "domain_size"}
_CONSUMER_REDUCERS = (
    "fp32-consumer-logits:max-absolute-difference",
    "fp32-consumer-logits:rms-difference",
    "fp32-consumer-logits:p99-absolute-error",
)


def _hash(document: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(document))


def _require_frozen(document: dict[str, Any], *, sha: str, schema: str, label: str) -> None:
    if not isinstance(document, dict) or document.get("schema") != schema:
        raise MethodologyError(f"v5 {label} schema mismatch")
    if document.get("contract_id") != CONTRACT_ID:
        raise MethodologyError(f"v5 {label} contract mismatch")
    if _hash(document) != sha:
        raise MethodologyError(f"v5 {label} hash mismatch")


def _identities(cases: Any, *, count: int, prefix: str, label: str) -> dict[str, str]:
    if not isinstance(cases, list) or len(cases) != count:
        raise MethodologyError(f"v5 {label} must contain exactly {count} cases")
    result: dict[str, str] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise MethodologyError(f"v5 {label} contains an invalid case")
        case_id, case_sha = case.get("case_id"), case.get("case_sha256")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in result:
            raise MethodologyError(f"v5 {label} contains an invalid or duplicate case ID")
        if not is_sha256(case_sha):
            raise MethodologyError(f"v5 {label} contains an invalid case identity")
        result[case_id] = case_sha
    return result


def _mixture_membership(cases: Any, *, label: str) -> None:
    """Verify every case's component is a member of the frozen mixture universe.

    Unlike v1/v3/v4's fixed balanced design, v5 calibration cases are IID
    mixture draws: cell counts are not fixed and must not be checked for
    balance, only for membership in the declared 24-component population.
    """
    valid = mixture_components()
    valid_pairs = {(content_class, regime_index) for content_class, regime_index in valid}
    from issue74_methodology import CONTENT_CLASSES, LENGTH_REGIMES

    for case in cases:
        content_class = case.get("content_class")
        regime = tuple(case.get("length_regime", []))
        try:
            regime_index = LENGTH_REGIMES.index(regime)
        except ValueError as exc:
            raise MethodologyError(f"v5 {label} case has an unrecognized length regime") from exc
        if content_class not in CONTENT_CLASSES or (content_class, regime_index) not in valid_pairs:
            raise MethodologyError(f"v5 {label} case is not a member of the frozen mixture population")


def _balanced_cells(cases: Any, *, per_cell: int, expected_cells: int, label: str) -> None:
    cells: dict[tuple[str, str], int] = {}
    for case in cases:
        parts = case.get("case_id", "").split("-") if isinstance(case, dict) else []
        if len(parts) != 4:
            raise MethodologyError(f"v5 {label} case ID does not encode a frozen cell")
        cell = (parts[1], parts[2])
        cells[cell] = cells.get(cell, 0) + 1
    if len(cells) != expected_cells or set(cells.values()) != {per_cell}:
        raise MethodologyError(f"v5 {label} cells must be exactly {expected_cells} x {per_cell}")


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
    if not isinstance(domain, dict) or domain.get("schema") != "inferswarm.issue109.v5-decision-domain-manifest/1":
        raise MethodologyError("v5 decision-domain manifest schema mismatch")
    if domain.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v5 decision-domain manifest contract mismatch")
    if domain.get("construction") != decision_domain_construction_identity() or domain.get("k") != 1024:
        raise MethodologyError("v5 decision-domain manifest construction mismatch")
    if domain.get("reference_derived_only") is not True or domain.get("candidate_membership_influence") != "PROHIBITED":
        raise MethodologyError("v5 decision-domain manifest is not reference-only")
    indexed: dict[str, dict[int, dict[str, Any]]] = {}
    for arm, identities in (("statistical_cases", statistical_ids), ("stress_cases", stress_ids)):
        rows = domain.get(arm)
        if not isinstance(rows, list) or len(rows) != len(identities):
            raise MethodologyError(f"v5 domain {arm} count mismatch")
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"case_id", "case_sha256", "decisions"}:
                raise MethodologyError("v5 domain row fields mismatch")
            case_id = row.get("case_id")
            if case_id in seen or row.get("case_sha256") != identities.get(case_id):
                raise MethodologyError("v5 domain case identity mismatch")
            seen.add(case_id)
            decisions = row.get("decisions")
            if not isinstance(decisions, list) or len(decisions) != 8:
                raise MethodologyError("v5 domain requires exactly 8 decision rows")
            rows_by_index: dict[int, dict[str, Any]] = {}
            for decision in decisions:
                if not isinstance(decision, dict) or set(decision) != _DOMAIN_DECISION_FIELDS:
                    raise MethodologyError("v5 domain decision fields mismatch")
                index = decision.get("decision_index")
                if not isinstance(index, int) or index in rows_by_index or not 0 <= index <= 7:
                    raise MethodologyError("v5 domain decision index invalid")
                if not is_sha256(decision.get("domain_membership_sha256")) or not isinstance(decision.get("domain_size"), int) or decision["domain_size"] < 1:
                    raise MethodologyError("v5 domain decision evidence invalid")
                rows_by_index[index] = decision
            if set(rows_by_index) != set(range(8)):
                raise MethodologyError("v5 domain decision indices incomplete")
            indexed[case_id] = rows_by_index
        if seen != set(identities):
            raise MethodologyError("v5 domain case set mismatch")
    return indexed


def _validate_summary_arm(rows: Any, identities: dict[str, str], domains: dict[str, dict[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(identities):
        raise MethodologyError("v5 calibration arm case count mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _CASE_FIELDS:
            raise MethodologyError("v5 case summary fields mismatch")
        case_id = row.get("case_id")
        if case_id in seen or row.get("case_sha256") != identities.get(case_id):
            raise MethodologyError("v5 summary case identity mismatch")
        seen.add(case_id)
        if row.get("exact_integrity") != "PASS" or row.get("finite") is not True or row.get("evidence_complete") is not True:
            raise MethodologyError("v5 case evidence must be exact-integrity PASS, finite, and complete")
        envelopes = row.get("envelopes")
        if not isinstance(envelopes, dict) or set(envelopes) != set(ENVELOPES):
            raise MethodologyError("v5 case must contain all 15 numerical envelopes")
        for identity, value in envelopes.items():
            _metric(value, label=f"{case_id} {identity}")
        decisions = row.get("decisions")
        if not isinstance(decisions, list) or len(decisions) != 8:
            raise MethodologyError("v5 case must contain exactly 8 decision rows")
        errors: list[float] = []
        consumer_values = {identity: [] for identity in _CONSUMER_REDUCERS}
        seen_decisions: set[int] = set()
        for decision in decisions:
            if not isinstance(decision, dict) or set(decision) != _DECISION_FIELDS:
                raise MethodologyError("v5 summary decision fields mismatch")
            index = decision.get("decision_index")
            if not isinstance(index, int) or index in seen_decisions or not 0 <= index <= 7:
                raise MethodologyError("v5 summary decision index invalid")
            seen_decisions.add(index)
            domain = domains.get(case_id, {}).get(index)
            if domain is None or decision.get("domain_membership_sha256") != domain["domain_membership_sha256"] or decision.get("domain_size") != domain["domain_size"]:
                raise MethodologyError("v5 summary decision domain identity mismatch")
            errors.append(_metric(decision.get("decision_local_error_hex"), label=f"{case_id} decision-local error"))
            reducers = decision.get("consumer_logit_reducers")
            if not isinstance(reducers, dict) or set(reducers) != set(_CONSUMER_REDUCERS):
                raise MethodologyError("v5 summary decision must contain three full-vocabulary consumer reducers")
            for identity in _CONSUMER_REDUCERS:
                consumer_values[identity].append(_metric(
                    reducers[identity], label=f"{case_id} decision {index} {identity}"
                ))
        if seen_decisions != set(range(8)):
            raise MethodologyError("v5 summary decision indices incomplete")
        if _metric(row.get("case_e_d_hex"), label=f"{case_id} case E_D") != case_e_d(errors):
            raise MethodologyError("v5 case E_D does not equal its eight-decision maximum")
        for identity, values in consumer_values.items():
            if _metric(envelopes[identity], label=f"{case_id} case {identity}") != max(values):
                raise MethodologyError(
                    "v5 case consumer-logit scalar does not equal its eight-decision maximum"
                )
    if seen != set(identities):
        raise MethodologyError("v5 calibration arm case set mismatch")
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


def derive_v5_threshold_artifacts(*, calibration_corpus: dict[str, Any], stress_pool: dict[str, Any],
                                  selection_commitment: dict[str, Any], reference_margin_summary: dict[str, Any],
                                  selected_stress: dict[str, Any], decision_domain_manifest: dict[str, Any],
                                  calibration_summary: dict[str, Any], comparator_contract: dict[str, Any],
                                  holdout_commitment: dict[str, Any], holdout_custody_record: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed v5 derivation from frozen identities and complete evidence."""
    _require_frozen(calibration_corpus, sha=V5_CALIBRATION_CORPUS_SHA256, schema=V5_CALIBRATION_SCHEMA, label="calibration corpus")
    _require_frozen(stress_pool, sha=V5_STRESS_POOL_SHA256, schema=V5_STRESS_POOL_SCHEMA, label="stress pool")
    _require_frozen(selection_commitment, sha=V5_STRESS_COMMITMENT_SHA256, schema=V5_STRESS_COMMITMENT_SCHEMA, label="stress commitment")
    _require_frozen(holdout_commitment, sha=V5_HOLDOUT_COMMITMENT_SHA256, schema="inferswarm.issue109.v5-holdout-commitment/1", label="holdout commitment")
    _require_frozen(holdout_custody_record, sha=V5_HOLDOUT_CUSTODY_RECORD_SHA256, schema="inferswarm.issue109.v5-holdout-custody-record/1", label="holdout custody record")
    if holdout_commitment.get("state") != "SEALED_NOT_CONSUMED":
        raise MethodologyError("v5 holdout is not sealed and unconsumed")
    if not custody_is_satisfied(holdout_custody_record):
        raise MethodologyError(
            "v5 holdout custody is not complete (>=2 verified independent "
            "custodians required); physical execution must not proceed"
        )
    program_sha256 = sha256_file(Path(__file__).resolve())
    if not is_sha256(program_sha256):
        raise MethodologyError("v5 derivation program identity must be SHA-256")
    if canonical_json_bytes(comparator_contract) != canonical_json_bytes(comparator_tier_contract()):
        raise MethodologyError("v5 comparator tier contract mismatch")

    statistical_ids = _identities(calibration_corpus.get("cases"), count=V5_CALIBRATION_CASES, prefix="c109-", label="calibration corpus")
    _mixture_membership(calibration_corpus["cases"], label="calibration corpus")
    pool_ids = _identities(stress_pool.get("cases"), count=V5_STRESS_POOL_CASES, prefix="p109-", label="stress pool")
    _balanced_cells(stress_pool["cases"], per_cell=2, expected_cells=24, label="stress pool")
    from select_issue109_margin_stress_v5 import select as replay_select

    replayed = replay_select(stress_pool, reference_margin_summary, selection_commitment)
    if canonical_json_bytes(selected_stress) != canonical_json_bytes(replayed):
        raise MethodologyError("SELECTED_EIGHT_NOT_SELECTOR_DERIVED")
    if selected_stress.get("schema") != V5_SELECTED_EIGHT_SCHEMA or selected_stress.get("selected_count") != V5_SELECTED_STRESS_CASES:
        raise MethodologyError("v5 selected stress must contain exactly eight cases")
    stress_ids = _identities([row.get("case") for row in selected_stress.get("selected", [])], count=V5_SELECTED_STRESS_CASES, prefix="p109-", label="selected stress")
    if not set(stress_ids).issubset(pool_ids):
        raise MethodologyError("v5 selected stress contains non-pool identity")

    domain_sha = _hash(decision_domain_manifest)
    domains = _validate_domain(decision_domain_manifest, statistical_ids, stress_ids)
    if not isinstance(calibration_summary, dict) or set(calibration_summary) != _SUMMARY_FIELDS:
        raise MethodologyError("v5 calibration summary fields mismatch")
    if calibration_summary.get("schema") != "inferswarm.issue109.v5-calibration-summary/1" or calibration_summary.get("contract_id") != CONTRACT_ID or calibration_summary.get("tooling_version") != V5_TOOLING_VERSION:
        raise MethodologyError("v5 calibration summary contract mismatch")
    expected_bindings = {
        "calibration_corpus_sha256": _hash(calibration_corpus), "stress_pool_sha256": _hash(stress_pool),
        "stress_selection_commitment_sha256": _hash(selection_commitment),
        "reference_margin_summary_sha256": _hash(reference_margin_summary),
        "stress_selection_sha256": _hash(selected_stress), "decision_domain_manifest_sha256": domain_sha,
    }
    if any(calibration_summary.get(key) != value for key, value in expected_bindings.items()):
        raise MethodologyError("v5 calibration summary evidence binding mismatch")
    hashes = calibration_summary.get("evidence_sha256")
    if not isinstance(hashes, list) or not hashes or len(set(hashes)) != len(hashes) or not all(is_sha256(value) for value in hashes):
        raise MethodologyError("v5 calibration evidence hashes invalid")
    statistical = _validate_summary_arm(calibration_summary.get("statistical_cases"), statistical_ids, domains)
    stress = _validate_summary_arm(calibration_summary.get("stress_cases"), stress_ids, domains)

    core_keys = {f"{row['family']}:{row['metric']}" for row in comparator_contract["core_numerical_pairs"]} | {"decision_local_E_D"}
    telemetry_keys = {f"{row['family']}:{row['metric']}" for row in comparator_contract["mandatory_telemetry_pairs"]}
    if len(core_keys) != 3 or len(telemetry_keys) != 13 or core_keys & telemetry_keys or core_keys | telemetry_keys != set(ENVELOPES) | {"decision_local_E_D"}:
        raise MethodologyError("v5 comparator contract does not preserve three-core/thirteen-telemetry semantics")

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
        "core_threshold_manifest": common | {"schema": "inferswarm.issue109.v5-core-threshold-manifest/1", "limits": core_limits},
        "telemetry_reference_bands": common | {"schema": "inferswarm.issue109.v5-telemetry-reference-bands/1", "bands": telemetry_bands, "finite_exceedance": "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE"},
    }


def main() -> None:
    raise SystemExit("future physical calibration only; invoke derive_v5_threshold_artifacts from a validated campaign assembler")


if __name__ == "__main__":
    main()
