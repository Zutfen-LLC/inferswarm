#!/usr/bin/env python3
"""Issue #170 — Arm-C long-remainder public corpus methodology (stdlib).

This module is the CPU-ONLY, PURE-STDLIB authority for the prospective
16-case Arm-C long-remainder generalization corpus mandated by issue
#170 (successor to the accepted #168 blocker
ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED).

Everything frozen BEFORE generation lives here as a named constant:

- the public corpus seed / salt / case-id namespace;
- the exact 16 target rendered lengths and the derived second-chunk
  remainders (frozen 64-row boundary) and the four #168 buckets;
- the deterministic content-class assignment rule (all six accepted
  public CONTENT_CLASSES, each appearing at least twice);
- the deterministic per-target raw-token search order and the fixed
  finite search ceiling;
- the exclusion namespaces (public historical identities only; the
  h109 holdout is FORBIDDEN INPUT and is never enumerated here).

The producer that loads the frozen tokenizer (scripts/
issue170_corpus_producer.py) imports the CONTENT_CLASSES table from the
accepted #74 lineage (scripts/issue74_methodology.py) at run time —
never restated here — and this module never imports transformers.

The terminal reducer (scripts/issue170_terminal_reduction.py) consumes
only these constants and the retained corpus bytes to re-derive
completeness, buckets, digests, and the terminal — never authored
booleans.

No GPU, no model execution, no FreeToken candidate runtime, no
h109-* material. Nothing in this issue derives Arm-C PASS/FAIL.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ------------------------------------------------------------------
#: Public identity (frozen before generation; issue #170)
#: ------------------------------------------------------------------
SEED = "issue170-arm-c-long-remainder-corpus-v1"
CORPUS_ID = "issue170-arm-c-long-remainder-corpus-v1"
CASE_PREFIX = "g170-"
NAMESPACE = "arm-c-long-remainder"

#: frozen 64-row prefill boundary (accepted #129/#133 contract;
#: consumed identity — the boundary itself is NOT redefined here, only
#: referenced for remainder arithmetic)
ROW_BOUNDARY = 64

#: ------------------------------------------------------------------
#: Exact target rendered lengths and derived remainders
#: (frozen; must not change after observing generation difficulty)
#: ------------------------------------------------------------------
TARGET_RENDERED_LENGTHS = (
    65, 67, 69, 72,
    73, 78, 83, 88,
    89, 96, 104, 112,
    113, 118, 123, 128,
)
TARGET_REMAINDERS = tuple(
    length - ROW_BOUNDARY for length in TARGET_RENDERED_LENGTHS)
assert TARGET_REMAINDERS == (
    1, 3, 5, 8,
    9, 14, 19, 24,
    25, 32, 40, 48,
    49, 54, 59, 64,
)

#: the four original #168 buckets, unchanged
BUCKETS = ((("1-8"), 1, 8), (("9-24"), 9, 24),
           (("25-48"), 25, 48), (("49-64"), 49, 64))
REQUIRED_PER_BUCKET = 4
CASE_COUNT = 16

#: ------------------------------------------------------------------
#: Deterministic content-class assignment (frozen before generation)
#:
#: Rule: case ordinal i (0-based, ascending in the frozen target-length
#: sequence) is assigned CONTENT_CLASSES[(2 + 5 * i) % 6].
#:
#: This is a fixed, source-frozen bijection-free rotation over the six
#: accepted public content classes (consumed from the #74 methodology
#: at run time; never restated). With 16 cases and stride 5 (coprime
#: to 6) the orbit covers every class; the realized counts are
#: 3,3,3,3,2,2 — every class appears at least twice. The counts are
#: re-derived mechanically by the reducer; this comment is not
#: authority.
#: ------------------------------------------------------------------
CLASS_ASSIGNMENT_STRIDE = 5
CLASS_ASSIGNMENT_OFFSET = 2


def assigned_content_class(ordinal: int, content_classes) -> str:
    """The frozen deterministic assignment for case ordinal i (0-based)."""
    return content_classes[
        (CLASS_ASSIGNMENT_OFFSET + CLASS_ASSIGNMENT_STRIDE * ordinal) % 6]


#: ------------------------------------------------------------------
#: Deterministic raw-token target search order (frozen)
#:
#: For target rendered length L with wrapper delta w (rendered length
#: minus raw token count — MEASURED per candidate by the producer, not
#: assumed), the raw token target is r = L - w. Because w is usually
#: 13 but can be 12 at a tokenizer boundary merge, the frozen search
#: order enumerates, per attempt nonce n (monotonically increasing
#: from 0):
#:
#:   raw target r = L - w_n, where the wrapper-delta hypothesis order
#:   is frozen as (13, 12): candidate material is generated for raw
#:   target L-13 first, then L-12, each under attempt nonce n, and the
#:   FIRST candidate whose MEASURED rendered length equals L exactly
#:   (and which passes the disjointness rules) is accepted.
#:
#: The nonce strictly increases across retries of the same target and
#: never resets; the (13, 12) delta order is fixed and never adapted.
#: ------------------------------------------------------------------
WRAPPER_DELTA_ORDER = (13, 12)
SEARCH_CEILING = 4096  # attempts per target; frozen before generation

#: ------------------------------------------------------------------
#: Exclusion namespaces (public historical identities only)
#: ------------------------------------------------------------------
EXCLUSION_SOURCES = (
    {
        "kind": "public-calibration",
        "file": ("docs/qualification/gemma4-12b-it-v5/manifests/"
                 "calibration-corpus.json"),
        "prefix": "c109-",
    },
    {
        "kind": "public-stress-pool",
        "file": ("docs/qualification/gemma4-12b-it-v5/manifests/"
                 "stress-pool.json"),
        "prefix": "p109-",
    },
    {
        "kind": "accepted-regression-fixture",
        "file": ("docs/implementation/r6-successor-dense-full-integration"
                 "-117/evidence/arm-c-retry/prompt-fixture.json"),
        "prefix": "c109-",
        "identity": "24-case accepted #133 fixture, consumed by digest",
    },
    {
        "kind": "accepted-157-anchor-control",
        "file": ("docs/implementation/r6-successor-dense-full-integration"
                 "-117/evidence/arm-c-chunk2-diagnosis-157/"
                 "physical-diagnostic-authority.json"),
        "prefix": "c109-",
        "identity": ("anchor_a, anchor_b, stable_control case ids "
                     "(frozen_corpus block); public c109 identities "
                     "where separately represented"),
    },
)
#: The h109 holdout is FORBIDDEN INPUT — never enumerated, never read,
#: never hashed into any exclusion or generation input. The producer
#: and reducer mechanically assert no h109 path/name/content appears
#: in their own sources and in the retained corpus bytes.
FORBIDDEN_NAMESPACE = "h109-"

#: consumed (never restated) accepted authority identities
sys_path_note = ("scripts/issue129_arm_c_retry_core.FIXTURE_DIGEST_24 "
                 "is imported by the producer and reducer; the "
                 "historical literal appears only in the record tests "
                 "as an independent cross-check pin")

#: terminal classifications mandated by issue #170
FROZEN_TERMINAL = "ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_FROZEN"
BLOCKED_TERMINAL = "ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_BLOCKED"

CORPUS_SCHEMA = "inferswarm.issue170.arm-c-long-remainder-corpus/1"
AUTHORITY_SCHEMA = "inferswarm.issue170.arm-c-long-remainder-authority/1"
TERMINAL_SCHEMA = "inferswarm.issue170.arm-c-long-remainder-terminal/1"

EVIDENCE_DIR = ROOT / (
    "docs/implementation/r6-successor-arm-c-long-remainder-corpus-170/"
    "evidence")

#: accepted #168 blocker identity (consumed, not reinterpreted)
ACCEPTED_BLOCKER_TERMINAL = (
    "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED")
ACCEPTED_BLOCKER_ISSUE = (
    "https://github.com/Zutfen-LLC/inferswarm/issues/168")

#: starting heads named by issue #170 (the accepted PR #169 merge and
#: the accepted #166 FreeToken research merge)
INFERSWARM_MAIN_170 = "941d0fe52ecedff1c5294a5582af3fedecb1018e"
FREETOKEN_RESEARCH_170 = (
    "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")


def bucket_of(remainder: int) -> str | None:
    for name, low, high in BUCKETS:
        if low <= remainder <= high:
            return name
    return None


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha(value) -> str:
    return sha_bytes(canonical_json_bytes(value))
