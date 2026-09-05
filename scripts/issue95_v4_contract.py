#!/usr/bin/env python3
"""Pure CPU/static contract checks for issue #95's Gemma v4 freeze.

This module never imports torch/transformers/Triton or initializes a model.
It validates the accepted #93 tier classification and derives the predictive
zero-exceedance statement from the frozen balanced design.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from issue74_methodology import MethodologyError, canonical_json_bytes, sha256_bytes
from issue95_v4_methodology import (
    V4_CASES_PER_CELL, V4_CORE_FAMILY_COUNT, V4_STATISTICAL_CASES,
    V4_TELEMETRY_FAMILY_COUNT,
)

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION_PATH = ROOT / 'docs/qualification/post-v3-numerical-core-doctrine/first-contract-classification.json'
COMPARATOR_SCHEMA = 'inferswarm.issue95.v4-comparator-tier-contract/1'


def predictive_design() -> dict[str, Any]:
    cells = 24
    if V4_STATISTICAL_CASES != cells * V4_CASES_PER_CELL:
        raise MethodologyError('v4 calibration count is not the frozen balanced design')
    if V4_CASES_PER_CELL != 79 or V4_CORE_FAMILY_COUNT != 4:
        raise MethodologyError('v4 predictive theorem constants changed')
    per_family = 1.0 / (V4_CASES_PER_CELL + 1)
    familywise = V4_CORE_FAMILY_COUNT * per_family
    return {
        'cells': cells,
        'cases_per_cell': V4_CASES_PER_CELL,
        'statistical_cases': V4_STATISTICAL_CASES,
        'holdout_cases': cells,
        'per_core_family_strict_exceedance_bound': f'1/{V4_CASES_PER_CELL + 1}',
        'familywise_bonferroni_bound': f'{V4_CORE_FAMILY_COUNT}/{V4_CASES_PER_CELL + 1}',
        'familywise_failure_probability': familywise,
        'zero_exceedance_probability_at_least': 1.0 - familywise,
        'inclusive_holdout_comparison': 'observed<=limit',
        'stress_cases_contribute_predictive_sample_size': 0,
        'theorem': 'within-cell exchangeability; global maximum lies in one cell; a strict future record in that cell has probability <=1/80',
    }


def comparator_tier_contract(classification: dict[str, Any] | None = None) -> dict[str, Any]:
    source = classification or json.loads(CLASSIFICATION_PATH.read_text())
    families = source.get('families')
    if not isinstance(families, list) or len(families) != 15:
        raise MethodologyError('accepted classification must enumerate exactly 15 identities')
    pairs = {(r.get('family'), r.get('metric')): r.get('tier') for r in families}
    if len(pairs) != 15:
        raise MethodologyError('accepted classification contains duplicate identities')
    core = sorted(k for k, tier in pairs.items() if tier == 'ACCEPTANCE_BEARING')
    telemetry = sorted(k for k, tier in pairs.items() if tier == 'MANDATORY_TELEMETRY')
    expected_core = [('fp32-consumer-logits', m) for m in ('max-absolute-difference', 'p99-absolute-error', 'rms-difference')]
    if core != expected_core or len(telemetry) != V4_TELEMETRY_FAMILY_COUNT:
        raise MethodologyError('v4 tiers do not exactly bind accepted #93 classification')
    source_sha = sha256_bytes(canonical_json_bytes(source))
    return {
        'schema': COMPARATOR_SCHEMA,
        'contract_id': 'inferswarm.gemma4-prediction-aligned-qualification/1',
        'classification_source': str(CLASSIFICATION_PATH.relative_to(ROOT)),
        'classification_sha256': source_sha,
        'classification_terminal_disposition': source.get('terminal_disposition'),
        'core_numerical_pairs': [{'family': f, 'metric': m} for f, m in core],
        'semantic_core': {'identity': 'decision_local_E_D', 'tier': 'ACCEPTANCE_BEARING', 'case_reducer': 'max over all 8 canonical-prefix decision-local errors'},
        'mandatory_telemetry_pairs': [{'family': f, 'metric': m} for f, m in telemetry],
        'finite_policy': 'finite_required identities fail unconditionally on NaN/Inf; finite telemetry band exceedance records TELEMETRY_ALERT only',
        'tier_change_rule': 'new comparator version and prospective justification required',
        'core_limit_schema': 'core-threshold-manifest.schema.json',
        'telemetry_band_schema': 'telemetry-reference-bands.schema.json',
    }


def derive_separate_bands(statistical: dict[str, float], stress: dict[str, float], contract: dict[str, Any]) -> dict[str, Any]:
    core_keys = {f"{r['family']}:{r['metric']}" for r in contract['core_numerical_pairs']} | {'decision_local_E_D'}
    telemetry_keys = {f"{r['family']}:{r['metric']}" for r in contract['mandatory_telemetry_pairs']}
    if set(statistical) != set(stress) or set(statistical) != core_keys | telemetry_keys:
        raise MethodologyError('complete exact core and telemetry identities are required')
    return {
        'core_limits': {k: max(statistical[k], stress[k]) for k in sorted(core_keys)},
        'telemetry_reference_bands': {k: max(statistical[k], stress[k]) for k in sorted(telemetry_keys)},
        'telemetry_exceedance_verdict': 'TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE',
    }
