#!/usr/bin/env python3
"""Pure CPU/static contract checks for issue #109's Gemma v5 freeze.

This module never imports torch/transformers/Triton or initializes a model.
It mechanically merges the accepted issue #108 fp32-consumer-logits/E_D tier
reclassification (metric-core-classification.json: p99 demoted to mandatory
telemetry) with the twelve internal-family identities whose tier is
unchanged since the accepted #93 classification, and derives the v5
mixture-population predictive design.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from issue74_methodology import ENVELOPES, MethodologyError, canonical_json_bytes, sha256_bytes
from issue109_v5_methodology import (
    CONTRACT_ID,
    V5_CORE_FAMILY_COUNT,
    V5_TELEMETRY_FAMILY_COUNT,
    derive_mixture_prediction_design,
)

ROOT = Path(__file__).resolve().parents[1]
V3_CLASSIFICATION_PATH = ROOT / "docs/qualification/post-v3-numerical-core-doctrine/first-contract-classification.json"
V4_METRIC_CLASSIFICATION_PATH = ROOT / "docs/qualification/post-v4-statistical-metric-doctrine/metric-core-classification.json"
COMPARATOR_SCHEMA = "inferswarm.issue109.v5-comparator-tier-contract/1"


def predictive_design() -> dict[str, Any]:
    """Return the canonical mechanically-derived issue #109 mixture design."""
    design = derive_mixture_prediction_design()
    if (
        design["core_family_count"] != V5_CORE_FAMILY_COUNT
        or design["calibration_cases"] != 1416
        or design["holdout_cases"] != 24
        or design["familywise_failure_probability"] > 0.05
    ):
        raise MethodologyError("v5 mixture predictive theorem constants changed")
    return design


def comparator_tier_contract(
    v3_classification: dict[str, Any] | None = None,
    v4_metric_classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    v3 = v3_classification or json.loads(V3_CLASSIFICATION_PATH.read_text())
    v4 = v4_metric_classification or json.loads(V4_METRIC_CLASSIFICATION_PATH.read_text())

    families = v3.get("families")
    if not isinstance(families, list) or len(families) != 15:
        raise MethodologyError("accepted v3 classification must enumerate exactly 15 identities")
    v3_pairs = {(row.get("family"), row.get("metric")): row.get("tier") for row in families}
    if len(v3_pairs) != 15:
        raise MethodologyError("accepted v3 classification contains duplicate identities")

    if v4.get("schema") != "inferswarm.issue108.metric-core-classification/1":
        raise MethodologyError("accepted #108 metric classification schema mismatch")
    v4_metrics = {row["identity"]: row["tier"] for row in v4.get("metrics", [])}
    required_v4_identities = {
        "fp32-consumer-logits:max-absolute-difference",
        "fp32-consumer-logits:rms-difference",
        "fp32-consumer-logits:p99-absolute-error",
        "decision_local_E_D",
    }
    if set(v4_metrics) != required_v4_identities:
        raise MethodologyError("accepted #108 metric classification identities mismatch")

    merged: dict[tuple[str, str], str] = {}
    for (family, metric), tier in v3_pairs.items():
        if family == "fp32-consumer-logits":
            tier = v4_metrics[f"{family}:{metric}"]
        merged[(family, metric)] = tier

    core = sorted(k for k, tier in merged.items() if tier == "ACCEPTANCE_BEARING")
    telemetry = sorted(k for k, tier in merged.items() if tier == "MANDATORY_TELEMETRY")
    expected_core = [
        ("fp32-consumer-logits", "max-absolute-difference"),
        ("fp32-consumer-logits", "rms-difference"),
    ]
    if (core != expected_core or len(telemetry) != V5_TELEMETRY_FAMILY_COUNT
            or core_telemetry_disjoint_and_complete(core, telemetry) is False):
        raise MethodologyError("v5 tiers do not exactly bind the accepted #93/#108 classifications")
    if v4_metrics["decision_local_E_D"] != "ACCEPTANCE_BEARING":
        raise MethodologyError("decision_local_E_D must remain acceptance-bearing")

    v3_source_sha = sha256_bytes(canonical_json_bytes(v3))
    v4_source_sha = sha256_bytes(canonical_json_bytes(v4))
    return {
        "schema": COMPARATOR_SCHEMA,
        "contract_id": CONTRACT_ID,
        "v3_classification_source": str(V3_CLASSIFICATION_PATH.relative_to(ROOT)),
        "v3_classification_sha256": v3_source_sha,
        "v4_metric_classification_source": str(V4_METRIC_CLASSIFICATION_PATH.relative_to(ROOT)),
        "v4_metric_classification_sha256": v4_source_sha,
        "classification_terminal_disposition": v4.get("terminal_disposition")
        or "POST_V4_STATISTICAL_METRIC_DOCTRINE_ACCEPTED",
        "core_numerical_pairs": [{"family": f, "metric": m} for f, m in core],
        "semantic_core": {
            "identity": "decision_local_E_D", "tier": "ACCEPTANCE_BEARING",
            "case_reducer": "max over all 8 canonical-prefix decision-local errors",
        },
        "mandatory_telemetry_pairs": [{"family": f, "metric": m} for f, m in telemetry],
        "finite_policy": (
            "finite_required identities fail unconditionally on NaN/Inf; finite "
            "telemetry band exceedance records TELEMETRY_ALERT only"
        ),
        "tier_change_rule": "new comparator version and prospective justification required",
        "core_limit_schema": "core-threshold-manifest.schema.json",
        "telemetry_band_schema": "telemetry-reference-bands.schema.json",
    }


def core_telemetry_disjoint_and_complete(core: list[tuple[str, str]], telemetry: list[tuple[str, str]]) -> bool:
    core_set, telemetry_set = set(core), set(telemetry)
    envelope_pairs = {tuple(identity.split(":", 1)) for identity in ENVELOPES}
    return bool(
        not (core_set & telemetry_set)
        and core_set | telemetry_set == envelope_pairs
    )


def derive_separate_bands(statistical: dict[str, float], stress: dict[str, float], contract: dict[str, Any]) -> dict[str, Any]:
    core_keys = {f"{r['family']}:{r['metric']}" for r in contract["core_numerical_pairs"]} | {"decision_local_E_D"}
    telemetry_keys = {f"{r['family']}:{r['metric']}" for r in contract["mandatory_telemetry_pairs"]}
    if set(statistical) != set(stress) or set(statistical) != core_keys | telemetry_keys:
        raise MethodologyError("complete exact core and telemetry identities are required")
    return {
        "core_limits": {k: max(statistical[k], stress[k]) for k in sorted(core_keys)},
        "telemetry_reference_bands": {k: max(statistical[k], stress[k]) for k in sorted(telemetry_keys)},
        "telemetry_exceedance_verdict": "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE",
    }
