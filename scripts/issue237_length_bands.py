#!/usr/bin/env python3
"""R8-derived predictive length-band authority (issue #237 correction).

The Qwen Vulkan v1 predictive length regimes are NOT free design constants:
they are mechanically derived from the accepted R8-B fixture-ladder
``target_band`` fields (the context regimes where R8 already demonstrated
Qwen's length-sensitive numerical behavior). This module is the single
derivation authority:

- fails closed if the fixture ladder is missing, byte-drifted, malformed,
  or does not carry exactly the four accepted cases;
- derives the four frozen bands in ladder case order;
- exposes ``validate_frozen_bands`` so the freeze tooling, the corpus
  validator, and the focused tests all cross-check any candidate band set
  against the same authority bytes.

A regression back to the copied Gemma qualification bands (4-8 / 24-28 /
36-40 / 52-56) fails ``validate_frozen_bands`` by construction.

Pure stdlib, CPU-only, repository-static.
"""
from __future__ import annotations

import json
from pathlib import Path

from issue237_build_exclusion_inventory import (  # noqa: F401 (authority reuse)
    FIXTURE_LADDER as _FIXTURE_LADDER_PATH,
    FIXTURE_LADDER_SHA256 as FIXTURE_LADDER_SHA256,
)
from issue74_methodology import sha256_bytes

REPO = Path(__file__).resolve().parents[1]

EXPECTED_LADDER_CASE_IDS = (
    "case-256",
    "case-1024",
    "case-3072",
    "case-4096",
)
EXPECTED_BAND_COUNT = 4
MAX_BAND_WIDTH = 16  # each accepted R8 band spans <= 16 tokens


class BandAuthorityError(RuntimeError):
    pass


def derive_length_regimes(repo_root: Path | None = None) -> tuple[tuple[int, int], ...]:
    """Derive the four frozen (low, high) target-length bands from the
    accepted R8-B fixture-ladder ``target_band`` fields, in ladder order.

    Fail closed on: missing file, sha256 drift, wrong case set, malformed
    bands, band wider than the frozen maximum, or a rendered length that
    falls outside its own band (the band must contain the realized fixture).
    """
    root = repo_root if repo_root is not None else REPO
    path = root / _FIXTURE_LADDER_PATH
    if not path.is_file():
        raise BandAuthorityError(f"R8-B fixture ladder missing: {path}")
    raw = path.read_bytes()
    if sha256_bytes(raw) != FIXTURE_LADDER_SHA256:
        raise BandAuthorityError(
            "R8-B fixture ladder bytes drifted from the accepted authority"
        )
    ladder = json.loads(raw)
    cases = ladder.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_BAND_COUNT:
        raise BandAuthorityError("fixture ladder must carry exactly four cases")
    if [c.get("case_id") for c in cases] != list(EXPECTED_LADDER_CASE_IDS):
        raise BandAuthorityError("fixture ladder case set/order drift")
    bands: list[tuple[int, int]] = []
    for case in cases:
        band = case.get("target_band")
        if (
            not isinstance(band, list)
            or len(band) != 2
            or not all(isinstance(v, int) for v in band)
        ):
            raise BandAuthorityError(f"malformed target_band: {case.get('case_id')}")
        low, high = band
        if not 0 < low <= high:
            raise BandAuthorityError(f"non-positive band: {case.get('case_id')}")
        if high - low + 1 > MAX_BAND_WIDTH:
            raise BandAuthorityError(f"band wider than frozen maximum: {case['case_id']}")
        rendered = case.get("rendered_length")
        if not isinstance(rendered, int) or not low <= rendered <= high:
            raise BandAuthorityError(
                f"rendered length outside its own target band: {case['case_id']}"
            )
        bands.append((low, high))
    return tuple(bands)


def length_regimes_provenance(repo_root: Path | None = None) -> dict:
    """Public provenance block for the derived bands (no band hand-copy)."""
    root = repo_root if repo_root is not None else REPO
    path = root / _FIXTURE_LADDER_PATH
    ladder = json.loads(path.read_text())
    per_case = [
        {
            "case_id": case["case_id"],
            "rendered_length": case["rendered_length"],
            "target_band": list(case["target_band"]),
        }
        for case in ladder["cases"]
    ]
    relative = (
        path.relative_to(root)
        if path.is_absolute()
        else path
    )
    return {
        "authority": relative.as_posix(),
        "authority_sha256": FIXTURE_LADDER_SHA256,
        "derivation": (
            "the four predictive length regimes are the target_band fields "
            "of the accepted R8-B fixture ladder, derived mechanically by "
            "scripts/issue237_length_bands.py (fail-closed on drift); they "
            "replace the Gemma-qualification 4-56 bands this issue found "
            "copied into the first freeze"
        ),
        "cases": per_case,
    }


def validate_frozen_bands(bands) -> tuple[tuple[int, int], ...]:
    """Cross-check a candidate band set against the derived authority."""
    if not isinstance(bands, (tuple, list)) or len(bands) != EXPECTED_BAND_COUNT:
        raise BandAuthorityError("candidate band set must carry exactly four bands")
    normalized = []
    for band in bands:
        if not isinstance(band, (tuple, list)) or len(band) != 2:
            raise BandAuthorityError(f"malformed candidate band: {band!r}")
        low, high = band
        if not isinstance(low, int) or not isinstance(high, int):
            raise BandAuthorityError(f"non-integer candidate band: {band!r}")
        normalized.append((low, high))
    candidate = tuple(normalized)
    derived = derive_length_regimes()
    if candidate != derived:
        raise BandAuthorityError(
            "frozen length bands do not match the R8-B fixture authority: "
            f"candidate {candidate} != derived {derived}"
        )
    return derived


# The frozen band set, derived once at import from the accepted bytes.
LENGTH_REGIMES: tuple[tuple[int, int], ...] = derive_length_regimes()


__all__ = [
    "BandAuthorityError",
    "EXPECTED_BAND_COUNT",
    "EXPECTED_LADDER_CASE_IDS",
    "FIXTURE_LADDER_SHA256",
    "LENGTH_REGIMES",
    "derive_length_regimes",
    "length_regimes_provenance",
    "validate_frozen_bands",
]
