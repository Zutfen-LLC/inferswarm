#!/usr/bin/env python3
"""Threshold + telemetry-band derivation tooling for the future physical
R8-I successor campaign (issue #237, CPU-only, deterministic, fail-closed).

The DERIVATION ALGORITHM is frozen here, prospectively; the future campaign
runs it over complete calibration evidence and commits the output artifacts.
Nothing in this module derives limits from anything but complete retained
calibration bytes, and no manual threshold editing/rounding exists anywhere
in the pipeline (values serialize via float.hex).

Frozen algorithm (ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE / POOLED calibration max):

  core limits:
    limit(family) = max over ALL N calibration cases of case_value(family)
    (inclusive holdout comparison: observed <= limit; no safety factor, no
    rounding, no post-hoc adjustment)

  telemetry bands:
    band(family) = max over calibration cases (report-only; exceedance marks
    evidence health DEGRADED, never qualification failure)

  semantic E_D:
    E_D = max(statistical_E_D over N calibration cases, stress_E_D over the
    8 selected stress cases)  [frozen reducer identity]

Every artifact records the exact input digests it was derived from.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402
from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

CORE_THRESHOLD_SCHEMA = "inferswarm.issue237.core-threshold-manifest/1"
TELEMETRY_BANDS_SCHEMA = "inferswarm.issue237.telemetry-reference-bands/1"


class DerivationError(RuntimeError):
    pass


def _finite_nonnegative(values: Sequence[float], label: str) -> list[float]:
    out = []
    for v in values:
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")) or f < 0.0:
            raise DerivationError(f"{label} contains non-finite or negative values")
        out.append(f)
    return out


def derive_core_limits(
    per_case_family_values: dict[str, Sequence[float]],
) -> dict[str, dict[str, str]]:
    """Max over all N calibration cases per acceptance-bearing family."""
    if sorted(per_case_family_values) != sorted(
        f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES
    ):
        raise DerivationError("family set does not match the frozen comparator")
    n = m.CALIBRATION_CASES
    limits = {}
    for family, values in per_case_family_values.items():
        if len(values) != n:
            raise DerivationError(
                f"family {family} requires exactly {n} calibration values"
            )
        finite = _finite_nonnegative(values, family)
        limits[family] = {
            "limit_hex": max(finite).hex(),
            "algorithm": "max over N calibration cases (pooled order statistic)",
            "inclusive_comparison": "observed<=limit",
        }
    return limits


def derive_telemetry_bands(
    per_case_family_values: dict[str, Sequence[float]],
) -> dict[str, dict[str, str]]:
    n = m.CALIBRATION_CASES
    bands = {}
    for family, values in per_case_family_values.items():
        if len(values) != n:
            raise DerivationError(
                f"family {family} requires exactly {n} calibration values"
            )
        finite = _finite_nonnegative(values, family)
        bands[family] = {
            "band_max_hex": max(finite).hex(),
            "role": "report-only; exceedance degrades evidence health, not qualification",
        }
    return bands


def derive_e_d(statistical_case_e_ds: Sequence[float],
               stress_case_e_ds: Sequence[float]) -> str:
    if len(statistical_case_e_ds) != m.CALIBRATION_CASES:
        raise DerivationError(
            f"statistical E_D arm requires exactly {m.CALIBRATION_CASES} cases"
        )
    if len(stress_case_e_ds) != m.STRESS_SELECTED_CASES:
        raise DerivationError(
            f"stress E_D arm requires exactly {m.STRESS_SELECTED_CASES} cases"
        )
    statistical = _finite_nonnegative(statistical_case_e_ds, "statistical E_D")
    stress = _finite_nonnegative(stress_case_e_ds, "stress E_D")
    return max(max(statistical), max(stress)).hex()


def build_threshold_manifest(
    per_case_family_values: dict[str, Sequence[float]],
    *,
    calibration_corpus_sha256: str,
    observation_manifest_sha256: str,
    e_d_hex: str,
) -> dict[str, Any]:
    if len(calibration_corpus_sha256) != 64 or len(observation_manifest_sha256) != 64:
        raise DerivationError("input digests must be sha256 hex")
    return {
        "schema": CORE_THRESHOLD_SCHEMA,
        "comparator_id": m.COMPARATOR_ID,
        "limits": derive_core_limits(per_case_family_values),
        "e_d_hex": e_d_hex,
        "derived_from": {
            "calibration_corpus_sha256": calibration_corpus_sha256,
            "observation_manifest_sha256": observation_manifest_sha256,
        },
        "derivation_rule": (
            "mechanical max over complete calibration evidence; no manual "
            "editing, rounding, or post-hoc adjustment is representable"
        ),
        "familywise_statement": m.statistical_design()["probability_statement"],
    }


def build_telemetry_bands_manifest(
    per_case_family_values: dict[str, Sequence[float]],
    *,
    calibration_corpus_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": TELEMETRY_BANDS_SCHEMA,
        "comparator_id": m.COMPARATOR_ID,
        "bands": derive_telemetry_bands(per_case_family_values),
        "derived_from": {"calibration_corpus_sha256": calibration_corpus_sha256},
    }
