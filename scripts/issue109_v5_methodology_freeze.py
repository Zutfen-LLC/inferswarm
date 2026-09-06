#!/usr/bin/env python3
"""Validate and assemble the issue #109 Gemma v5 methodology freeze.

This is pure-stdlib, CPU-only static tooling. It reads the versioned v5
methodology area, verifies every manifest against the accepted issue #108
post-v4 statistical/metric doctrine (via
``issue108_post_v4_statistical_metric_doctrine.validate_prospective_methodology``),
verifies internal hash bindings and mechanical disjointness, and emits the
terminal methodology-freeze record. It never reads node-local data, executes
a model, or decrypts holdout material.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes, sha256_bytes, sha256_file
from issue109_v5_contract import comparator_tier_contract, predictive_design
from issue109_v5_methodology import (
    ASSUMPTION_PROFILE,
    CONSTRUCTION,
    CONTRACT_ID,
    METHODOLOGY_ID,
    QUALIFICATION_CLAIM,
    mixture_population_declaration,
)
from commit_issue109_holdout import custody_is_satisfied

import issue108_post_v4_statistical_metric_doctrine as doctrine

ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / "docs/qualification/gemma4-12b-it-v5"
MANIFESTS = V5 / "manifests"

TERMINAL_DISPOSITION = "GEMMA_V5_CORRECTED_QUALIFICATION_METHODOLOGY_FROZEN"


class MethodologyFreezeError(ValueError):
    """A v5 methodology-freeze artifact is incomplete or inconsistent."""


def _load(name: str) -> dict[str, Any]:
    with (MANIFESTS / name).open(encoding="utf-8") as source:
        return json.load(source)


def _hash_file(name: str) -> str:
    return sha256_file(MANIFESTS / name)


def prospective_methodology() -> dict[str, Any]:
    """The v5 selection instantiating the accepted #108 doctrine (Q1-Q3)."""
    return {
        "assumption_profile": ASSUMPTION_PROFILE,
        "construction": CONSTRUCTION,
        "qualification_claim": QUALIFICATION_CLAIM,
        "declared_iid_mixture_target": True,
        "declared_named_strata": False,
        "claims_per_stratum_coverage": False,
    }


def verify_doctrine_compliance() -> dict[str, Any]:
    """Validate the v5 selection against the accepted #108 statistical contract.

    This is the mechanism ADR 0012 requires: #108 froze the permitted
    construction classes and their compatibility constraints but selected
    none of them (NO_V5_PARAMETER_SELECTION); #109 makes exactly that
    prospective selection and must validate against the unchanged #108
    contract, not a locally redefined copy of it.
    """
    contract_path = (
        doctrine.AREA / "statistical-contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    doctrine.validate_prospective_methodology(prospective_methodology(), contract)
    return contract


def verify_disjointness(proof: dict[str, Any] | None = None) -> dict[str, Any]:
    proof = proof if proof is not None else _load("disjointness-proof.json")
    if proof.get("schema") != "inferswarm.issue109.v5-disjointness-proof/1":
        raise MethodologyFreezeError("v5 disjointness proof schema mismatch")
    if proof.get("verdict") != "MECHANICALLY_DISJOINT":
        raise MethodologyFreezeError("v5 corpora are not mechanically disjoint")
    comparisons = proof.get("comparisons")
    if not isinstance(comparisons, list) or not comparisons:
        raise MethodologyFreezeError("v5 disjointness proof has no comparisons")
    for row in comparisons:
        if row.get("prompt_sha256_overlap") or row.get("token_ids_sha256_overlap"):
            raise MethodologyFreezeError("v5 disjointness proof records a nonzero overlap")
    return proof


def verify_mixture_population(committed: dict[str, Any] | None = None) -> dict[str, Any]:
    declared = mixture_population_declaration()
    committed = committed if committed is not None else _load("mixture-population.json")
    if canonical_json_bytes(declared) != canonical_json_bytes(committed):
        raise MethodologyFreezeError("committed mixture-population.json does not match the frozen declaration")
    calibration = _load("calibration-corpus.json")
    if canonical_json_bytes(calibration.get("mixture_population")) != canonical_json_bytes(declared):
        raise MethodologyFreezeError("calibration corpus does not bind the frozen mixture declaration")
    return committed


def verify_corpora() -> dict[str, Any]:
    calibration = _load("calibration-corpus.json")
    stress = _load("stress-pool.json")
    if calibration.get("schema") != "inferswarm.issue109.v5-calibration-corpus/1":
        raise MethodologyFreezeError("v5 calibration corpus schema mismatch")
    if len(calibration.get("cases", [])) != 1416:
        raise MethodologyFreezeError("v5 calibration corpus must contain exactly 1416 cases")
    case_ids = {case["case_id"] for case in calibration["cases"]}
    prompt_hashes = {case["prompt_sha256"] for case in calibration["cases"]}
    if len(case_ids) != 1416 or len(prompt_hashes) != 1416:
        raise MethodologyFreezeError("v5 calibration corpus contains non-unique cases")
    if stress.get("schema") != "inferswarm.issue109.v5-stress-pool/1":
        raise MethodologyFreezeError("v5 stress pool schema mismatch")
    if len(stress.get("cases", [])) != 48:
        raise MethodologyFreezeError("v5 stress pool must contain exactly 48 cases")
    return {"calibration": calibration, "stress_pool": stress}


def verify_comparator_contract(committed: dict[str, Any] | None = None) -> dict[str, Any]:
    computed = comparator_tier_contract()
    committed = committed if committed is not None else _load("comparator-tier-contract.json")
    if canonical_json_bytes(computed) != canonical_json_bytes(committed):
        raise MethodologyFreezeError("committed comparator-tier-contract.json is not mechanically derived")
    if len(committed["core_numerical_pairs"]) != 2:
        raise MethodologyFreezeError("v5 comparator must have exactly 2 core numerical pairs")
    if len(committed["mandatory_telemetry_pairs"]) != 13:
        raise MethodologyFreezeError("v5 comparator must have exactly 13 telemetry pairs")
    return committed


def verify_statistical_derivation(committed: dict[str, Any] | None = None) -> dict[str, Any]:
    computed = predictive_design()
    committed = committed if committed is not None else _load("statistical-derivation.json")
    if canonical_json_bytes(computed) != canonical_json_bytes(committed):
        raise MethodologyFreezeError("committed statistical-derivation.json is not mechanically derived")
    if committed["familywise_failure_probability"] > 0.05:
        raise MethodologyFreezeError("v5 familywise failure probability exceeds the declared alpha")
    return committed


def verify_holdout_and_custody(
    commitment: dict[str, Any] | None = None, custody: dict[str, Any] | None = None,
) -> dict[str, Any]:
    commitment = commitment if commitment is not None else _load("sealed-holdout-commitment.json")
    custody = custody if custody is not None else _load("holdout-custody-record.json")
    if commitment.get("schema") != "inferswarm.issue109.v5-holdout-commitment/1":
        raise MethodologyFreezeError("v5 holdout commitment schema mismatch")
    if commitment.get("state") != "SEALED_NOT_CONSUMED":
        raise MethodologyFreezeError("v5 holdout is not sealed")
    if custody.get("holdout_ciphertext_sha256") != commitment.get("ciphertext_sha256"):
        raise MethodologyFreezeError("v5 custody record does not bind the committed ciphertext")
    if custody.get("unseal_authorized") is not False:
        raise MethodologyFreezeError("v5 custody record must not authorize unseal at freeze time")
    return {
        "commitment": commitment,
        "custody": custody,
        "custody_satisfied": custody_is_satisfied(custody),
    }


def build_record() -> dict[str, Any]:
    contract = verify_doctrine_compliance()
    disjointness = verify_disjointness()
    mixture = verify_mixture_population()
    corpora = verify_corpora()
    comparator = verify_comparator_contract()
    derivation = verify_statistical_derivation()
    holdout = verify_holdout_and_custody()

    manifest_hashes = {
        name: _hash_file(name)
        for name in (
            "calibration-corpus.json", "stress-pool.json", "mixture-population.json",
            "disjointness-proof.json", "comparator-tier-contract.json",
            "statistical-derivation.json", "sealed-holdout-commitment.json",
            "holdout-custody-record.json", "stress-selection-commitment.json",
        )
    }

    return {
        "schema": "inferswarm.issue109.v5-methodology-freeze-record/1",
        "methodology_id": METHODOLOGY_ID,
        "contract_id": CONTRACT_ID,
        "terminal_classification": TERMINAL_DISPOSITION,
        "issue108_statistical_contract_sha256": sha256_bytes(canonical_json_bytes(contract)),
        "prospective_methodology": prospective_methodology(),
        "predictive_design": derivation,
        "comparator_tier_contract": comparator,
        "mixture_population": mixture,
        "disjointness_proof": disjointness,
        "corpora_summary": {
            "calibration_cases": len(corpora["calibration"]["cases"]),
            "stress_pool_cases": len(corpora["stress_pool"]["cases"]),
        },
        "holdout": {
            "state": holdout["commitment"]["state"],
            "custody_state": holdout["custody"]["holdout_state"],
            "custody_satisfied": holdout["custody_satisfied"],
        },
        "manifest_sha256": manifest_hashes,
        "physical_execution": "PROHIBITED_AND_NOT_PERFORMED",
        "holdout_decryption": "PROHIBITED_AND_NOT_PERFORMED",
        "physical_campaign_authorized": False,
        "non_claims": [
            "This freeze sets no v5 numerical limit; limits are derived only from "
            "future complete physical calibration evidence (issue #110).",
            "It does not establish a qualified model, backend, device, or deployment.",
            "It does not reinterpret #88, #97, #105, or #108, or admit consumed "
            "h74/h86/h95 observations as v5 input.",
            "It does not authorize holdout decryption; that requires custody "
            "completion (>=2 verified independent custodians) and the non-decrypting "
            "unseal preflight, then explicit maintainer action.",
        ],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None,
                        help="write the deterministic record to this path")
    args = parser.parse_args()
    rendered = json.dumps(build_record(), indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(rendered, end="")
    else:
        args.out.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
