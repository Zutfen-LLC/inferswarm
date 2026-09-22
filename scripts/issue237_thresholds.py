#!/usr/bin/env python3
"""Threshold + telemetry-band derivation tooling for the future physical
R8-I successor campaign (issue #237, CPU-only, deterministic, fail-closed).

Correction-pass contract (repository-only): the derivation authority is
MECHANICAL END TO END. There is no caller-supplied semantic ``e_d_hex`` (or
any other hand-authored limit) anywhere in this module — the manifest
builder that accepted an arbitrary ``e_d_hex`` argument was DELETED. Every
emitted value derives from a complete retained observation bundle:

    core limits   = max over ALL N=1416 complete retained calibration
                    observations, per acceptance-bearing family;
    telemetry     = max over the complete retained calibration
                    observations, per mandatory-telemetry family;
    semantic E_D  = max( max over exactly N=1416 statistical case E_D
                    values, max over exactly 8 frozen selected-stress
                    case E_D values )   [frozen reducer identity]

Every artifact records the exact sha256 input digests it was derived from,
and those digests are COMPUTED from the passed document bytes — never
asserted by the caller. ``verify_threshold_artifacts`` re-derives both
artifacts from the same bundle and proves the committed frozen artifacts
are byte-identical to the fresh derivation; any hand-edited threshold,
forged digest, missing/extra case, wrong family, wrong stress selection,
NaN/Inf value, or incomplete evidence fails closed.

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
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402
from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

CORE_THRESHOLD_SCHEMA = "inferswarm.issue237.core-threshold-manifest/1"
TELEMETRY_BANDS_SCHEMA = "inferswarm.issue237.telemetry-reference-bands/1"
OBSERVATION_MANIFEST_SCHEMA = "inferswarm.issue237.observation-manifest/1"
SELECTED_STRESS_SCHEMA = "inferswarm.issue237.selected-stress/1"


class DerivationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DerivationError(message)


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _hex_float(value: Any, label: str) -> float:
    if not isinstance(value, str):
        raise DerivationError(f"{label} must be a hex-float string")
    try:
        f = float.fromhex(value)
    except ValueError:
        raise DerivationError(f"{label} is not a parseable hex float") from None
    if not math.isfinite(f) or f < 0.0:
        raise DerivationError(f"{label} must be finite and nonnegative")
    return f


def _finite_nonnegative(values: Sequence[float], label: str) -> list[float]:
    out = []
    for v in values:
        f = float(v)
        if not math.isfinite(f) or f < 0.0:
            raise DerivationError(f"{label} contains non-finite or negative values")
        out.append(f)
    return out


def _hex_float(value: Any, label: str) -> float:
    if not isinstance(value, str):
        raise DerivationError(f"{label} must be a hex-float string")
    try:
        f = float.fromhex(value)
    except ValueError:
        raise DerivationError(f"{label} is not a parseable hex float") from None
    if not math.isfinite(f) or f < 0.0:
        raise DerivationError(f"{label} must be finite and nonnegative")
    return f


# ---------------------------------------------------------------------------
# input-document validation (complete retained evidence, exact identities)


def validate_selected_stress(
    doc: dict[str, Any], *, stress_pool: dict[str, Any],
) -> list[str]:
    """Exactly the 8 frozen selected-stress cases, all members of the pool."""
    _require(
        doc.get("schema") == SELECTED_STRESS_SCHEMA,
        "selected-stress document schema drift",
    )
    selected = doc.get("selected")
    _require(
        isinstance(selected, list) and len(selected) == m.STRESS_SELECTED_CASES,
        f"selected stress requires exactly {m.STRESS_SELECTED_CASES} cases",
    )
    pool_ids = _pool_case_ids(stress_pool)
    ids: list[str] = []
    for row in selected:
        _require(isinstance(row, dict), "selected-stress rows must be objects")
        case_id = row.get("case_id")
        _require(
            isinstance(case_id, str) and case_id.startswith("p237-"),
            "selected-stress case id drift",
        )
        ids.append(case_id)
    _require(len(set(ids)) == m.STRESS_SELECTED_CASES, "duplicate selected-stress ids")
    _require(set(ids) <= pool_ids, "selected stress contains non-pool cases")
    return ids


def _pool_case_ids(stress_pool: dict[str, Any]) -> set[str]:
    _require(
        stress_pool.get("schema") == m.STRESS_POOL_SCHEMA,
        "stress pool schema drift",
    )
    cases = stress_pool.get("cases")
    _require(
        isinstance(cases, list) and len(cases) == m.STRESS_POOL_CASES,
        f"stress pool requires exactly {m.STRESS_POOL_CASES} cases",
    )
    ids = [c.get("case_id") for c in cases]
    _require(all(isinstance(i, str) and i.startswith("p237-") for i in ids),
             "stress pool case id drift")
    _require(len(set(ids)) == m.STRESS_POOL_CASES, "duplicate stress pool ids")
    return set(ids)


def _corpus_case_ids(calibration_corpus: dict[str, Any]) -> list[str]:
    _require(
        calibration_corpus.get("schema") == m.CALIBRATION_SCHEMA,
        "calibration corpus schema drift",
    )
    cases = calibration_corpus.get("cases")
    _require(
        isinstance(cases, list) and len(cases) == m.CALIBRATION_CASES,
        f"calibration corpus requires exactly {m.CALIBRATION_CASES} cases",
    )
    ids = [c.get("case_id") for c in cases]
    _require(
        all(isinstance(i, str) and i.startswith("c237-") for i in ids),
        "calibration case id drift",
    )
    _require(len(set(ids)) == m.CALIBRATION_CASES, "duplicate calibration ids")
    return ids


def validate_calibration_summary(
    doc: dict[str, Any], *, calibration_corpus: dict[str, Any],
) -> dict[str, list[float]]:
    """Complete per-case family values for EXACTLY the corpus population.

    Requires the exact family identities (3 acceptance-bearing + the frozen
    telemetry family), exactly N values per family, exactly N case E_D
    values, and case ids that equal the corpus population in corpus order —
    so a dropped, extra, reordered, or foreign case fails closed.
    """
    _require(
        doc.get("schema") == "inferswarm.issue237.calibration-summary/1",
        "calibration summary schema drift",
    )
    families = doc.get("per_case_family_values")
    _require(isinstance(families, dict), "per_case_family_values must be an object")
    expected = [f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES] + [
        f["family"] for f in m.TELEMETRY_FAMILIES
    ]
    _require(sorted(families) == sorted(expected), "family set drift")
    n = m.CALIBRATION_CASES
    for family, values in families.items():
        _require(
            isinstance(values, list) and len(values) == n,
            f"family {family} requires exactly {n} values",
        )
        for i, v in enumerate(values):
            _hex_float(v, f"{family}[{i}]")
    case_ids = doc.get("case_ids")
    _require(
        isinstance(case_ids, list) and case_ids == _corpus_case_ids(calibration_corpus),
        "calibration summary case ids must equal the corpus population in order",
    )
    case_e_d = doc.get("case_e_d_hex")
    _require(
        isinstance(case_e_d, list) and len(case_e_d) == n,
        f"calibration summary requires exactly {n} statistical case E_D values",
    )
    for i, v in enumerate(case_e_d):
        _hex_float(v, f"case_e_d_hex[{i}]")
    return {
        family: [_hex_float(v, f"{family}[{i}]") for i, v in enumerate(values)]
        for family, values in families.items()
    }


def validate_observation_manifest(
    doc: dict[str, Any],
    *,
    calibration_corpus: dict[str, Any],
    stress_pool: dict[str, Any],
    selected_stress: dict[str, Any],
) -> None:
    """The campaign's per-case observation evidence manifest.

    Binds every calibration case to BOTH arm observation digests and its
    statistical case E_D, and every selected stress case to both arm
    observation digests and its stress case E_D. Identities must match the
    corpus population in order and the frozen selected-stress selection.
    """
    _require(
        doc.get("schema") == OBSERVATION_MANIFEST_SCHEMA,
        "observation manifest schema drift",
    )
    _require(doc.get("contract_id") == m.CONTRACT_ID, "observation contract drift")
    _require(doc.get("comparator_id") == m.COMPARATOR_ID, "observation comparator drift")
    _require(
        _is_sha256_hex(doc.get("calibration_corpus_sha256")),
        "observation manifest corpus digest missing",
    )
    cal_rows = doc.get("calibration_cases")
    n = m.CALIBRATION_CASES
    _require(
        isinstance(cal_rows, list) and len(cal_rows) == n,
        f"observation manifest requires exactly {n} calibration rows",
    )
    corpus_ids = _corpus_case_ids(calibration_corpus)
    for i, row in enumerate(cal_rows):
        _require(isinstance(row, dict), "calibration observation rows must be objects")
        _require(
            row.get("case_id") == corpus_ids[i],
            f"observation row {i} does not bind the corpus case in order",
        )
        for key in ("reference_sha256", "candidate_sha256"):
            _require(_is_sha256_hex(row.get(key)), f"observation row {i} {key} missing")
        _hex_float(row.get("case_e_d_hex"), f"observation row {i} case E_D")
    stress_rows = doc.get("selected_stress_cases")
    _require(
        isinstance(stress_rows, list)
        and len(stress_rows) == m.STRESS_SELECTED_CASES,
        f"observation manifest requires exactly {m.STRESS_SELECTED_CASES} stress rows",
    )
    selected_ids = validate_selected_stress(selected_stress, stress_pool=stress_pool)
    for i, row in enumerate(stress_rows):
        _require(isinstance(row, dict), "stress observation rows must be objects")
        _require(
            row.get("case_id") == selected_ids[i],
            f"stress observation row {i} does not bind the selected stress in order",
        )
        for key in ("reference_sha256", "candidate_sha256"):
            _require(_is_sha256_hex(row.get(key)), f"stress row {i} {key} missing")
        _hex_float(row.get("case_e_d_hex"), f"stress row {i} case E_D")


# ---------------------------------------------------------------------------
# derivation (no caller-supplied semantic values of any kind)


def derive_core_limits(
    per_case_family_values: dict[str, list[float]],
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
    per_case_family_values: dict[str, list[float]],
) -> dict[str, dict[str, str]]:
    if sorted(per_case_family_values) != sorted(
        f["family"] for f in m.TELEMETRY_FAMILIES
    ):
        raise DerivationError(
            "telemetry family set does not match the frozen comparator"
        )
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


def derive_e_d(
    statistical_case_e_ds: Sequence[float],
    stress_case_e_ds: Sequence[float],
) -> str:
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


def derive_threshold_artifacts(
    *,
    calibration_summary: dict[str, Any],
    calibration_corpus: dict[str, Any],
    stress_pool: dict[str, Any],
    selected_stress: dict[str, Any],
    observation_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive BOTH canonical threshold artifacts from complete evidence.

    This is the ONLY production entry point that builds threshold artifacts.
    It takes raw observation documents (not digests, not semantic values):
    every identity is validated and every digest is computed here.
    """
    # 1. validate the complete input bundle mechanically
    family_values = validate_calibration_summary(
        calibration_summary, calibration_corpus=calibration_corpus,
    )
    _pool_case_ids(stress_pool)
    validate_selected_stress(selected_stress, stress_pool=stress_pool)
    validate_observation_manifest(
        observation_manifest,
        calibration_corpus=calibration_corpus,
        stress_pool=stress_pool,
        selected_stress=selected_stress,
    )
    # cross-binding: the observation manifest names the corpus it observed
    _require(
        observation_manifest["calibration_corpus_sha256"]
        == sha256_bytes(canonical_json_bytes(calibration_corpus)),
        "observation manifest does not bind this calibration corpus",
    )
    _require(
        calibration_corpus.get("schema") == m.CALIBRATION_SCHEMA
        and stress_pool.get("schema") == m.STRESS_POOL_SCHEMA,
        "corpus/pool identity drift",
    )
    # 2. case E_D values come from the OBSERVATION manifest (the retained
    #    evidence), and must equal the summary's statistical arm exactly
    summary_e_d = [
        _hex_float(v, f"case_e_d_hex[{i}]")
        for i, v in enumerate(calibration_summary["case_e_d_hex"])
    ]
    observed_cal_e_d = [
        _hex_float(r["case_e_d_hex"], f"observation row {i} case E_D")
        for i, r in enumerate(observation_manifest["calibration_cases"])
    ]
    _require(
        summary_e_d == observed_cal_e_d,
        "calibration summary case E_D does not equal the observation manifest",
    )
    stress_e_d = [
        _hex_float(r["case_e_d_hex"], f"stress row {i} case E_D")
        for i, r in enumerate(observation_manifest["selected_stress_cases"])
    ]
    # 3. compute every emitted value
    acceptance_values = {
        f["family"]: family_values[f["family"]]
        for f in m.ACCEPTANCE_BEARING_FAMILIES
    }
    telemetry_values = {
        f["family"]: family_values[f["family"]]
        for f in m.TELEMETRY_FAMILIES
    }
    e_d_hex = derive_e_d(summary_e_d, stress_e_d)
    digests = {
        "calibration_corpus_sha256": sha256_bytes(
            canonical_json_bytes(calibration_corpus)
        ),
        "stress_pool_sha256": sha256_bytes(canonical_json_bytes(stress_pool)),
        "selected_stress_sha256": sha256_bytes(
            canonical_json_bytes(selected_stress)
        ),
        "calibration_summary_sha256": sha256_bytes(
            canonical_json_bytes(calibration_summary)
        ),
        "observation_manifest_sha256": sha256_bytes(
            canonical_json_bytes(observation_manifest)
        ),
    }
    threshold_manifest = {
        "schema": CORE_THRESHOLD_SCHEMA,
        "comparator_id": m.COMPARATOR_ID,
        "limits": derive_core_limits(acceptance_values),
        "e_d_hex": e_d_hex,
        "e_d_derivation": {
            "rule": (
                "max(statistical_E_D over N=1416 calibration cases, "
                "stress_E_D over the 8 frozen selected-stress cases)"
            ),
            "statistical_case_count": m.CALIBRATION_CASES,
            "stress_case_count": m.STRESS_SELECTED_CASES,
        },
        "derived_from": digests,
        "derivation_rule": (
            "mechanical max over complete calibration evidence; no manual "
            "editing, rounding, or post-hoc adjustment is representable"
        ),
        "familywise_statement": m.statistical_design()["probability_statement"],
    }
    bands_manifest = {
        "schema": TELEMETRY_BANDS_SCHEMA,
        "comparator_id": m.COMPARATOR_ID,
        "bands": derive_telemetry_bands(telemetry_values),
        "derived_from": {
            k: digests[k]
            for k in (
                "calibration_corpus_sha256",
                "calibration_summary_sha256",
                "observation_manifest_sha256",
            )
        },
    }
    return threshold_manifest, bands_manifest


def verify_threshold_artifacts(
    *,
    committed_threshold_bytes: bytes,
    committed_bands_bytes: bytes,
    calibration_summary: dict[str, Any],
    calibration_corpus: dict[str, Any],
    stress_pool: dict[str, Any],
    selected_stress: dict[str, Any],
    observation_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Prove committed frozen artifacts are byte-identical to a fresh
    derivation over the same complete evidence (fail-closed)."""
    fresh_threshold, fresh_bands = derive_threshold_artifacts(
        calibration_summary=calibration_summary,
        calibration_corpus=calibration_corpus,
        stress_pool=stress_pool,
        selected_stress=selected_stress,
        observation_manifest=observation_manifest,
    )
    threshold_ok = (
        committed_threshold_bytes == canonical_json_bytes(fresh_threshold)
    )
    bands_ok = committed_bands_bytes == canonical_json_bytes(fresh_bands)
    return {
        "schema": "inferswarm.issue237.threshold-verification/1",
        "threshold_byte_identical": threshold_ok,
        "bands_byte_identical": bands_ok,
        "committed_threshold_sha256": hashlib.sha256(
            committed_threshold_bytes
        ).hexdigest(),
        "fresh_threshold_sha256": sha256_bytes(
            canonical_json_bytes(fresh_threshold)
        ),
        "committed_bands_sha256": hashlib.sha256(committed_bands_bytes).hexdigest(),
        "fresh_bands_sha256": sha256_bytes(canonical_json_bytes(fresh_bands)),
        "derivation": "max over complete retained calibration observations",
    }
