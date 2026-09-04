#!/usr/bin/env python3
"""InferSwarm issue #86: v3 threshold derivation (CPU-only, fail-closed).

Derives the v3 threshold manifest from calibration-only summaries:

- the 15 numerical envelope limits with UNCHANGED v1 semantics
  (max(statistical_max, stress_max), observed <= limit, host-float64 exact
  hexadecimal serialization);
- the supplemental decision-local bound E_D = max(statistical_E_D,
  stress_E_D) with no rounding or safety factor;
- the frozen semantic provenance: decision-domain construction identity,
  reference decision-domain manifest SHA, argmax/tie-break identity,
  corpus/pool/commitment/selection/evidence SHAs, SEALED_NOT_CONSUMED.

Fail-closed contract (issue #86 section 12): rejects any calibration row
that lacks exact integrity, finite/evidence-complete state, all 15
numerical envelopes, all 8 canonical-prefix semantic decision rows, exact
domain membership binding, or exact case identity. Rejects any holdout
material in the inputs.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from issue74_methodology import (
    CONTRACT_ID,
    ENVELOPES,
    MethodologyError,
    _parse_metric,
    _walk_forbidden_holdout,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from issue86_v3_methodology import (
    argmax_tie_break_identity,
    case_e_d,
    decision_domain_construction_identity,
    derive_e_d,
    e_d_reducer_identity,
    is_sha256,
)

# --- frozen v3 artifact identities (committed by issue #86) ---------------

V3_TOOLING_VERSION = "inferswarm.issue86.v3-threshold-tooling/1"
V3_CALIBRATION_CORPUS_SHA256 = (
    "09731f1b2e66a6892b886c01bd2ec058be147b73885213844f2863caa10b41b6"
)
V3_CALIBRATION_CASE_IDS_SHA256 = (
    "4975e0bba93c39a7e1eb9eac79435675da26ce5f29f25936997e4c79be6faa5f"
)
V3_CALIBRATION_CASE_IDENTITIES_SHA256 = (
    "71299a2b827c102667457fb076acece563e3e0150f330962b0f694c6682f2191"
)
V3_STRESS_POOL_SHA256 = (
    "4e4735c19f10bdcff4bf4173d9e96d2330df5c98de40f2701e1e3c309d29f015"
)
V3_STRESS_COMMITMENT_SHA256 = (
    "4ec7233c0344ff98e9c914606904e6ccb74b29e5d001ffe20579d051fce74740"
)
V3_HOLDOUT_CIPHERTEXT_SHA256 = (
    "7dc3af038ac1e6a71bfb4b7088a1a43f4366dfe991e212c3cbd2794e58e4dac8"
)
V3_HOLDOUT_CERTIFICATE_SHA256 = (
    "680a01b722b28e6e147ace0bb6ade3f3dfc1915afdda480498f97de3042d1542"
)
V3_HOLDOUT_COMMITMENT_SHA256_PLACEHOLDER = None  # bound via decision at runtime

V3_STATISTICAL_CASES = 576
V3_SELECTED_STRESS_CASES = 8
METRIC_REDUCER = "host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1"

HISTORICAL_H74_CIPHERTEXT_SHA256 = (
    "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"
)

_CALIBRATION_SUMMARY_FIELDS = {
    "schema", "contract_id", "tooling_version", "calibration_corpus_sha256",
    "stress_pool_sha256", "stress_selection_commitment_sha256",
    "stress_selection_sha256", "decision_domain_manifest_sha256",
    "evidence_sha256", "statistical_cases", "stress_cases",
}
_SUMMARY_CASE_FIELDS = {
    "case_id", "case_sha256", "exact_integrity", "finite",
    "evidence_complete", "envelopes", "case_e_d_hex", "decisions",
}
_DECISION_FIELDS = {
    "decision_index", "domain_membership_sha256", "domain_size",
    "decision_local_error_hex",
}


def _identity_rows(cases: Any, *, expected_count: int, prefix: str) -> dict[str, str]:
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise MethodologyError(f"identity source must contain exactly {expected_count} cases")
    identities: dict[str, str] = {}
    for case in cases:
        if not isinstance(case, dict):
            raise MethodologyError("identity source contains an invalid case")
        case_id = case.get("case_id")
        case_sha256 = case.get("case_sha256")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in identities:
            raise MethodologyError(f"invalid or duplicate {prefix} identity source case ID")
        if not is_sha256(case_sha256):
            raise MethodologyError(f"{case_id} has an invalid frozen case hash")
        identities[case_id] = str(case_sha256)
    return identities


def _validate_summary_arm(
    rows: Any,
    expected_identities: dict[str, str],
    expected_count: int,
    prefix: str,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise MethodologyError(f"{prefix} arm must contain exactly {expected_count} cases")
    case_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _SUMMARY_CASE_FIELDS:
            raise MethodologyError(f"{prefix} case summary fields do not match the v3 schema")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith(prefix) or case_id in case_ids:
            raise MethodologyError(f"invalid or duplicate {prefix} case ID")
        case_ids.add(case_id)
        if row.get("case_sha256") != expected_identities.get(case_id):
            raise MethodologyError(f"{case_id} does not match the frozen case identity")
        if row.get("exact_integrity") != "PASS":
            raise MethodologyError(f"{case_id} does not pass the exact-integrity gate")
        if row.get("finite") is not True or row.get("evidence_complete") is not True:
            raise MethodologyError(f"{case_id} has incomplete or non-finite evidence")
        envelopes = row.get("envelopes")
        if not isinstance(envelopes, dict) or set(envelopes) != set(ENVELOPES):
            raise MethodologyError(f"{case_id} must contain all 15 numerical envelopes")
        for value in envelopes.values():
            _parse_metric(value)
        decisions = row.get("decisions")
        if not isinstance(decisions, list) or len(decisions) != 8:
            raise MethodologyError(f"{case_id} must contain exactly 8 canonical-prefix decision rows")
        seen_indices: set[int] = set()
        for decision in decisions:
            if not isinstance(decision, dict) or set(decision) != _DECISION_FIELDS:
                raise MethodologyError(f"{case_id} decision row fields do not match the v3 schema")
            index = decision.get("decision_index")
            if not isinstance(index, int) or index in seen_indices or not 0 <= index <= 7:
                raise MethodologyError(f"{case_id} decision index is invalid or duplicated")
            seen_indices.add(index)
            if not is_sha256(decision.get("domain_membership_sha256")):
                raise MethodologyError(f"{case_id} decision lacks exact domain membership hash")
            size = decision.get("domain_size")
            if not isinstance(size, int) or size < 1:
                raise MethodologyError(f"{case_id} decision has an invalid domain size")
            _parse_metric(decision.get("decision_local_error_hex"))
        if seen_indices != set(range(8)):
            raise MethodologyError(f"{case_id} is missing one of the 8 semantic decision rows")
        # case_E_D must equal the max of its own decision rows (exact binding).
        stated = _parse_metric(row.get("case_e_d_hex"))
        derived = case_e_d(
            float.fromhex(d["decision_local_error_hex"]) for d in decisions
        )
        if stated != derived:
            raise MethodologyError(f"{case_id} case_e_d does not equal the max over its 8 decisions")
    if case_ids != set(expected_identities):
        raise MethodologyError(f"{prefix} case IDs do not match the exact frozen case set")
    return rows


def derive_v3_threshold_manifest(
    *,
    calibration_corpus: dict[str, Any],
    stress_pool: dict[str, Any],
    selection_commitment: dict[str, Any],
    stress_selection: dict[str, Any],
    decision_domain_manifest: dict[str, Any],
    calibration_summary: dict[str, Any],
    program_sha256: str,
) -> dict[str, Any]:
    """Derive 15 numerical limits + E_D from calibration-only summaries."""
    forbidden = _walk_forbidden_holdout({
        "calibration_summary": calibration_summary,
        "stress_selection": stress_selection,
        "decision_domain_manifest": decision_domain_manifest,
    })
    if forbidden:
        raise MethodologyError("holdout inputs are forbidden: " + ", ".join(forbidden[:4]))

    # --- bind the exact frozen corpora ------------------------------------
    if calibration_corpus.get("schema") != "inferswarm.issue86.v3-calibration-corpus/1":
        raise MethodologyError("v3 calibration corpus schema mismatch")
    if calibration_corpus.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v3 calibration corpus contract mismatch")
    corpus_sha = sha256_bytes(canonical_json_bytes(calibration_corpus))
    if corpus_sha != V3_CALIBRATION_CORPUS_SHA256:
        raise MethodologyError(
            "v3 calibration corpus hash mismatch — reuse/substitution of a "
            "non-frozen corpus is rejected"
        )
    calibration_identities = _identity_rows(
        calibration_corpus.get("cases"), expected_count=V3_STATISTICAL_CASES, prefix="c86-"
    )
    identity_rows = [
        {"case_id": case_id, "case_sha256": case_sha}
        for case_id, case_sha in sorted(calibration_identities.items())
    ]
    if sha256_bytes(canonical_json_bytes(identity_rows)) != (
        V3_CALIBRATION_CASE_IDENTITIES_SHA256
    ):
        raise MethodologyError("v3 calibration case identity commitment mismatch")

    if stress_pool.get("schema") != "inferswarm.issue86.v3-stress-pool/1":
        raise MethodologyError("v3 stress pool schema mismatch")
    pool_sha = sha256_bytes(canonical_json_bytes(stress_pool))
    if pool_sha != V3_STRESS_POOL_SHA256:
        raise MethodologyError("v3 stress pool hash mismatch")

    commitment_sha = sha256_bytes(canonical_json_bytes(selection_commitment))
    if commitment_sha != V3_STRESS_COMMITMENT_SHA256:
        raise MethodologyError("v3 stress selection commitment hash mismatch")

    # --- validate the future selected-eight manifest -----------------------
    from select_issue86_margin_stress_v3 import (
        NegativeReferenceMarginError,
        NonfiniteReferenceMarginError,
    )

    if stress_selection.get("schema") != "inferswarm.issue86.v3-selected-stress-eighth/1":
        raise MethodologyError("v3 selected-eight schema mismatch")
    if stress_selection.get("state") != "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE":
        raise MethodologyError("v3 selected-eight is not frozen at the post-reference barrier")
    if stress_selection.get("stress_pool_sha256") != pool_sha:
        raise MethodologyError("v3 selected-eight does not bind the exact frozen pool")
    if stress_selection.get("selection_commitment_sha256") != commitment_sha:
        raise MethodologyError("v3 selected-eight does not bind the exact frozen commitment")
    if stress_selection.get("selection_inputs") != "MATCHED_REFERENCE_MARGINS_ONLY":
        raise MethodologyError("v3 selected-eight is not reference-only")
    selected = stress_selection.get("selected")
    if not isinstance(selected, list) or len(selected) != V3_SELECTED_STRESS_CASES:
        raise MethodologyError("v3 selected-eight must contain exactly eight cases")
    pool_cases = {row["case_id"]: row for row in stress_pool["cases"]}
    selected_ids: set[str] = set()
    group_counts = {"four-smallest-including-zero": 0, "four-largest": 0}
    for row in selected:
        if not isinstance(row, dict) or row.get("selection_group") not in group_counts:
            raise MethodologyError("v3 selected-eight contains an invalid selection group")
        case = row.get("case")
        case_id = case.get("case_id") if isinstance(case, dict) else None
        if case_id in selected_ids or case_id not in pool_cases or case != pool_cases.get(case_id):
            raise MethodologyError("v3 selected-eight contains a duplicate or non-pool case")
        try:
            margin = float.fromhex(row["reference_top1_margin_hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MethodologyError("v3 selected-eight contains an invalid reference margin") from exc
        if not math.isfinite(margin) or margin < 0.0:
            raise MethodologyError(
                "v3 selected-eight requires finite nonnegative reference margins "
                "(zero-margin exact ties are eligible)"
            )
        if row.get("exact_zero_margin") is not (margin == 0.0):
            raise MethodologyError("v3 selected-eight zero-margin flag contradicts the margin value")
        selected_ids.add(str(case_id))
        group_counts[row["selection_group"]] += 1
    if set(group_counts.values()) != {4}:
        raise MethodologyError("v3 selected-eight must contain four cases in each selection group")
    stress_identities = _identity_rows(
        sorted((r["case"] for r in selected), key=lambda c: c["case_id"]),
        expected_count=V3_SELECTED_STRESS_CASES,
        prefix="p86-",
    )

    # --- validate the reference decision-domain manifest -------------------
    domain_manifest_sha = sha256_bytes(canonical_json_bytes(decision_domain_manifest))
    if decision_domain_manifest.get("schema") != "inferswarm.issue86.v3-decision-domain-manifest/1":
        raise MethodologyError("v3 decision-domain manifest schema mismatch")
    if decision_domain_manifest.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v3 decision-domain manifest contract mismatch")
    if decision_domain_manifest.get("construction") != decision_domain_construction_identity():
        raise MethodologyError("v3 decision-domain construction identity mismatch")
    if decision_domain_manifest.get("k") != 1024:
        raise MethodologyError("v3 decision-domain K mismatch")
    if decision_domain_manifest.get("reference_derived_only") is not True:
        raise MethodologyError("v3 decision domain must be reference-derived only")
    if decision_domain_manifest.get("candidate_membership_influence") != "PROHIBITED":
        raise MethodologyError("v3 decision domain must prohibit candidate influence")

    def _domain_identities(rows: Any, count: int, prefix: str) -> None:
        identities = _identity_rows(rows, expected_count=count, prefix=prefix)
        for row in rows:
            decisions = row.get("decisions")
            if not isinstance(decisions, list) or len(decisions) != 8:
                raise MethodologyError(f"{row.get('case_id')} needs 8 domain rows")
            indices = [d.get("decision_index") for d in decisions]
            if sorted(indices) != list(range(8)):
                raise MethodologyError(f"{row.get('case_id')} domain decision indices incomplete")
            for d in decisions:
                if not is_sha256(d.get("domain_membership_sha256")):
                    raise MethodologyError(f"{row.get('case_id')} domain row lacks membership hash")

    _domain_identities(decision_domain_manifest.get("statistical_cases"), V3_STATISTICAL_CASES, "c86-")
    _domain_identities(decision_domain_manifest.get("stress_cases"), V3_SELECTED_STRESS_CASES, "p86-")

    # --- validate the calibration summary ---------------------------------
    if calibration_summary.get("schema") != "inferswarm.issue86.v3-calibration-summary/1":
        raise MethodologyError("v3 calibration summary schema mismatch")
    if set(calibration_summary) != _CALIBRATION_SUMMARY_FIELDS:
        raise MethodologyError("v3 calibration summary fields do not match the schema")
    if calibration_summary.get("contract_id") != CONTRACT_ID:
        raise MethodologyError("v3 calibration summary contract mismatch")
    if calibration_summary.get("tooling_version") != V3_TOOLING_VERSION:
        raise MethodologyError("v3 calibration summary tooling version mismatch")
    if calibration_summary.get("calibration_corpus_sha256") != corpus_sha:
        raise MethodologyError("v3 calibration summary does not bind the exact corpus")
    if calibration_summary.get("stress_pool_sha256") != pool_sha:
        raise MethodologyError("v3 calibration summary does not bind the exact pool")
    if calibration_summary.get("stress_selection_commitment_sha256") != commitment_sha:
        raise MethodologyError("v3 calibration summary does not bind the exact commitment")
    if calibration_summary.get("stress_selection_sha256") != sha256_bytes(
        canonical_json_bytes(stress_selection)
    ):
        raise MethodologyError("v3 calibration summary does not bind the exact selected-eight")
    if calibration_summary.get("decision_domain_manifest_sha256") != domain_manifest_sha:
        raise MethodologyError("v3 calibration summary does not bind the exact domain manifest")
    statistical = _validate_summary_arm(
        calibration_summary.get("statistical_cases"), calibration_identities,
        V3_STATISTICAL_CASES, "c86-",
    )
    stress = _validate_summary_arm(
        calibration_summary.get("stress_cases"), stress_identities,
        V3_SELECTED_STRESS_CASES, "p86-",
    )

    # --- every decision's domain membership must match the domain manifest -
    domain_index = {}
    for row in decision_domain_manifest["statistical_cases"] + decision_domain_manifest["stress_cases"]:
        domain_index[row["case_id"]] = {d["decision_index"]: d for d in row["decisions"]}
    for row in statistical + stress:
        for decision in row["decisions"]:
            ref = domain_index.get(row["case_id"], {}).get(decision["decision_index"])
            if ref is None:
                raise MethodologyError(f"{row['case_id']} decision {decision['decision_index']} absent from the domain manifest")
            if decision["domain_membership_sha256"] != ref["domain_membership_sha256"]:
                raise MethodologyError(
                    f"{row['case_id']} decision {decision['decision_index']} domain membership "
                    "does not match the reference decision-domain manifest"
                )
            if decision["domain_size"] != ref["domain_size"]:
                raise MethodologyError(
                    f"{row['case_id']} decision {decision['decision_index']} domain size mismatch"
                )

    evidence_hashes = calibration_summary.get("evidence_sha256")
    if not isinstance(evidence_hashes, list) or not evidence_hashes:
        raise MethodologyError("at least one retained calibration evidence hash is required")
    if len(set(evidence_hashes)) != len(evidence_hashes):
        raise MethodologyError("calibration evidence hashes must be unique")
    for value in evidence_hashes + [program_sha256]:
        if not is_sha256(value):
            raise MethodologyError("evidence hashes must be SHA-256 hex digests")

    # --- derive the 15 numerical limits (unchanged v1 semantics) -----------
    limits: dict[str, Any] = {}
    for envelope in ENVELOPES:
        statistical_max = max(_parse_metric(row["envelopes"][envelope]) for row in statistical)
        stress_max = max(_parse_metric(row["envelopes"][envelope]) for row in stress)
        limit = max(statistical_max, stress_max)
        limits[envelope] = {
            "statistical_max_hex": statistical_max.hex(),
            "stress_max_hex": stress_max.hex(),
            "limit_hex": limit.hex(),
            "rule": "max(statistical_max,stress_max)",
            "comparison": "observed<=limit",
        }

    # --- derive E_D (supplemental, conjunctive) ----------------------------
    statistical_e_d = derive_e_d(
        [float.fromhex(row["case_e_d_hex"]) for row in statistical],
        [float.fromhex(row["case_e_d_hex"]) for row in stress],
    )
    statistical_arm = max(float.fromhex(row["case_e_d_hex"]) for row in statistical)
    stress_arm = max(float.fromhex(row["case_e_d_hex"]) for row in stress)
    e_d = max(statistical_arm, stress_arm)
    if e_d != statistical_e_d:
        raise MethodologyError("internal E_D derivation disagreement")

    return {
        "schema": "inferswarm.issue86.v3-threshold-manifest/1",
        "contract_id": CONTRACT_ID,
        "tooling_version": V3_TOOLING_VERSION,
        "calibration_corpus_sha256": corpus_sha,
        "calibration_case_ids_sha256": V3_CALIBRATION_CASE_IDS_SHA256,
        "calibration_case_identities_sha256": V3_CALIBRATION_CASE_IDENTITIES_SHA256,
        "calibration_summary_sha256": sha256_bytes(canonical_json_bytes(calibration_summary)),
        "calibration_evidence_sha256": sorted(evidence_hashes),
        "stress_pool_sha256": pool_sha,
        "stress_selection_commitment_sha256": commitment_sha,
        "stress_selection_sha256": sha256_bytes(canonical_json_bytes(stress_selection)),
        "decision_domain_manifest_sha256": domain_manifest_sha,
        "derivation_program_sha256": program_sha256,
        "metric_reducer": METRIC_REDUCER,
        "e_d_reducer": e_d_reducer_identity(),
        "decision_domain_construction": decision_domain_construction_identity(),
        "e_d_hex": e_d.hex(),
        "statistical_e_d_hex": statistical_arm.hex(),
        "stress_e_d_hex": stress_arm.hex(),
        "argmax_tie_break": argmax_tie_break_identity(),
        "limits": limits,
        "holdout_state": "SEALED_NOT_CONSUMED",
        "manual_editing_or_rounding": "PROHIBITED",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    design = subparsers.add_parser("statistical-design")
    design.add_argument("--json", action="store_true")
    derive = subparsers.add_parser("derive-thresholds")
    for name in ("--calibration-corpus", "--stress-pool", "--selection-commitment",
                 "--stress-selection", "--decision-domain-manifest",
                 "--calibration-summary", "--out"):
        derive.add_argument(name, required=True, type=Path)
    args = parser.parse_args(argv)

    if args.command == "statistical-design":
        from issue86_v3_methodology import statistical_design_v3

        doc = statistical_design_v3()
        print(json.dumps(doc, sort_keys=True, indent=2) if args.json else doc["minimum_n"])
        return 0

    manifest = derive_v3_threshold_manifest(
        calibration_corpus=json.loads(args.calibration_corpus.read_text()),
        stress_pool=json.loads(args.stress_pool.read_text()),
        selection_commitment=json.loads(args.selection_commitment.read_text()),
        stress_selection=json.loads(args.stress_selection.read_text()),
        decision_domain_manifest=json.loads(args.decision_domain_manifest.read_text()),
        calibration_summary=json.loads(args.calibration_summary.read_text()),
        program_sha256=sha256_file(Path(__file__)),
    )
    args.out.write_bytes(canonical_json_bytes(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
