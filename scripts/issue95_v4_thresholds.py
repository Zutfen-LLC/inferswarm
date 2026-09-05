#!/usr/bin/env python3
"""Issue #95 future-only threshold derivation; CPU/static and fail-closed."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from issue74_methodology import MethodologyError, canonical_json_bytes, sha256_bytes
from issue95_v4_contract import comparator_tier_contract, derive_separate_bands, predictive_design


def derive_threshold_artifacts(statistical: dict[str, float], stress: dict[str, float], *, calibration_case_count: int, selected_stress_count: int, provenance: dict[str, str]) -> dict[str, Any]:
    if calibration_case_count != predictive_design()['statistical_cases']:
        raise MethodologyError('v4 requires exactly 1896 statistical calibration cases')
    if selected_stress_count != 8:
        raise MethodologyError('v4 requires exactly eight selected stress cases')
    contract = comparator_tier_contract()
    bands = derive_separate_bands(statistical, stress, contract)
    common = {'contract_id': contract['contract_id'], 'comparator_tier_contract_sha256': sha256_bytes(canonical_json_bytes(contract)), 'provenance': provenance, 'holdout_state': 'SEALED_NOT_CONSUMED', 'manual_editing_or_rounding': 'PROHIBITED'}
    return {
        'core_threshold_manifest': common | {'schema':'inferswarm.issue95.v4-core-threshold-manifest/1', 'limits':bands['core_limits'], 'acceptance':'all four core values observed<=limit'},
        'telemetry_reference_bands': common | {'schema':'inferswarm.issue95.v4-telemetry-reference-bands/1', 'bands':bands['telemetry_reference_bands'], 'finite_exceedance':'TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE'},
    }


def main() -> int:
    raise SystemExit('future physical calibration only; invoke derive_threshold_artifacts from a validated campaign assembler')

if __name__ == '__main__':
    main()
