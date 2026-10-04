#!/usr/bin/env python3
"""Issue #273 (R8-I6A) — corrective dispatch law and terminal reducer.

New namespace, new dispatch phrase, new terminal vocabulary. No #270
terminal may be reused; no c270-* namespace may be dispatched; the
corrective tooling must be MERGED (this module refuses to authorize
execution from an unmerged head — the caller passes the exact merged
main head and the reducer cross-checks the frozen tooling head).

Terminal vocabulary (exactly one per execution; #273 issue text):

  R8I6A_V340_COMPARATOR2_CORRECTIVE_PHYSICAL_AUTHORITY_PASS
  R8I6A_REFERENCE_NONDETERMINISTIC_BLOCKED
  R8I6A_V340_COMPARATOR2_RUNTIME_BLOCKED
  R8I6A_V340_COMPARATOR2_INFRASTRUCTURE_BLOCKED
  R8I6A_V340_COMPARATOR2_AUTHORITY_BLOCKED

The mandatory execution order is enforced STRUCTURALLY by the reducer:
reference primary/repeat determinism is consumed before any candidate
pair comparison; a reference determinism failure on ANY authorized
fixture yields REFERENCE_NONDETERMINISTIC_BLOCKED (never a candidate
comparison verdict).
"""
from __future__ import annotations

import re
from typing import Any

import issue270_authority as C
import issue270_comparator as comparator
import issue273_admission as admission

SCHEMA = "inferswarm.issue273.corrective-terminal/1"
DISPATCH_SCHEMA = "inferswarm.issue273.dispatch-authority/1"

ISSUE_273 = 273
DISPATCH_PHRASE_273 = "R8I6A CORRECTIVE PHYSICAL DISPATCH"
NAMESPACE_273 = "c273-v340-comparator2-corrective"

# Namespace law: the corrective campaign namespace family. The old
# c270-* family is refused outright (a fresh execution may never reuse
# the invalidated campaign's namespace).
NAMESPACE_RE_273 = re.compile(r"^c273-[a-z0-9][a-z0-9-]*[a-z0-9]$")
FORBIDDEN_NAMESPACE_SUBSTRINGS_273 = (
    "c237-", "h237-", "p237-",      # predictive / holdout namespaces
    "c270-",                          # the invalidated #270 namespace
    "threshold", "calibration", "holdout",
)

TERMINAL_PASS_273 = (
    "R8I6A_V340_COMPARATOR2_CORRECTIVE_PHYSICAL_AUTHORITY_PASS")
TERMINAL_REFERENCE_NONDETERMINISTIC_273 = (
    "R8I6A_REFERENCE_NONDETERMINISTIC_BLOCKED")
TERMINAL_RUNTIME_BLOCKED_273 = (
    "R8I6A_V340_COMPARATOR2_RUNTIME_BLOCKED")
TERMINAL_INFRASTRUCTURE_BLOCKED_273 = (
    "R8I6A_V340_COMPARATOR2_INFRASTRUCTURE_BLOCKED")
TERMINAL_AUTHORITY_BLOCKED_273 = (
    "R8I6A_V340_COMPARATOR2_AUTHORITY_BLOCKED")
TERMINALS_273 = (
    TERMINAL_PASS_273,
    TERMINAL_REFERENCE_NONDETERMINISTIC_273,
    TERMINAL_RUNTIME_BLOCKED_273,
    TERMINAL_INFRASTRUCTURE_BLOCKED_273,
    TERMINAL_AUTHORITY_BLOCKED_273,
)

# A #270 terminal appearing anywhere in a #273 record is invalid.
LEGACY_TERMINALS = C.TERMINALS


class ReducerError(RuntimeError):
    pass


def validate_namespace_273(namespace: str) -> str:
    if not isinstance(namespace, str) \
            or NAMESPACE_RE_273.fullmatch(namespace) is None:
        raise ReducerError(f"invalid #273 namespace: {namespace!r}")
    for bad in FORBIDDEN_NAMESPACE_SUBSTRINGS_273:
        if bad in namespace:
            raise ReducerError(
                f"forbidden #273 namespace substring {bad!r} in "
                f"{namespace!r}")
    return namespace


def validate_dispatch_273(doc: Any, expected_head: str,
                          namespace: str = NAMESPACE_273) -> dict[str, Any]:
    """Authenticate a #273 corrective dispatch record.

    Required exact shape (issue #273 Phase 3):

        R8I6A CORRECTIVE PHYSICAL DISPATCH
        head=<exact 40-hex merged main>
        namespace=c273-v340-comparator2-corrective

    Stale head, old namespace, non-maintainer (non-OWNER/MEMBER)
    authorization, or the legacy #270 phrase all fail closed.
    """
    if not isinstance(doc, dict) or doc.get("schema") != DISPATCH_SCHEMA:
        raise ReducerError("#273 dispatch authority schema mismatch")
    if doc.get("issue") != ISSUE_273:
        raise ReducerError("#273 dispatch authority issue mismatch")
    if doc.get("dispatch_phrase") != DISPATCH_PHRASE_273:
        raise ReducerError(
            "#273 dispatch phrase mismatch (legacy #270 phrases are "
            "refused)")
    if doc.get("head_sha") != expected_head:
        raise ReducerError("#273 dispatch head mismatch (stale head)")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head or ""):
        raise ReducerError("#273 dispatch head malformed")
    if doc.get("namespace") != validate_namespace_273(namespace):
        raise ReducerError("#273 dispatch namespace mismatch")
    if doc.get("commenter_association") not in ("OWNER", "MEMBER"):
        raise ReducerError("#273 dispatch commenter not OWNER/MEMBER")
    if (not isinstance(doc.get("comment_id"), int)
            or isinstance(doc.get("comment_id"), bool)
            or doc.get("comment_id", 0) <= 0):
        raise ReducerError("#273 dispatch comment_id malformed")
    # The dispatch must carry the MERGED tooling head marker: the
    # corrective tooling PR must be merged before any acceptance-bearing
    # fresh execution (no local-only patch may define run authority).
    if doc.get("tooling_merged") is not True:
        raise ReducerError(
            "#273 dispatch must assert the corrective tooling is merged")
    return doc


# ---------------------------------------------------------------------------
# Corrected terminal derivation
# ---------------------------------------------------------------------------

def derive_terminal_273(admissions: dict[str, dict[str, Any]],
                        determinism: dict[str, dict[str, Any]],
                        pair_results: dict[str, dict[str, Any]] | None = None,
                        ) -> dict[str, Any]:
    """Derive the single #273 terminal from per-case corrected evidence.

    Inputs (all previously derived from retained bytes):

      admissions[case]  — issue273_admission.admit_pair verdicts
                          (already reference-determinism-gated);
      determinism[case] — {"reference": bool, "candidate": bool}
                          per-case per-arm deterministic-repeat verdicts
                          (independently computed row digests);
      pair_results      — optional cross-vendor comparator diagnostics
                          (never gates the terminal on numerical
                          agreement; recorded verbatim).

    Mandatory order enforced structurally: if ANY case's reference
    determinism is False, the terminal is REFERENCE_NONDETERMINISTIC_
    BLOCKED regardless of candidate state — a candidate comparison can
    never redeem a nondeterministic reference.
    """
    problems: list[str] = []
    if set(admissions) != set(C.FIXTURE_CASES):
        return _blocked(TERMINAL_RUNTIME_BLOCKED_273,
                        [f"admissions must cover exactly "
                         f"{sorted(C.FIXTURE_CASES)}; got "
                         f"{sorted(admissions)}"])
    if set(determinism) != set(C.FIXTURE_CASES):
        return _blocked(TERMINAL_RUNTIME_BLOCKED_273,
                        [f"determinism must cover exactly "
                         f"{sorted(C.FIXTURE_CASES)}; got "
                         f"{sorted(determinism)}"])
    # 1. Reference determinism first, per case (mandatory order).
    for case in C.FIXTURE_CASES:
        ref_det = (determinism.get(case) or {}).get("reference")
        if ref_det is not True:
            return _blocked(
                TERMINAL_REFERENCE_NONDETERMINISTIC_273,
                [f"{case}: reference primary/repeat not deterministic "
                 f"(verdict {ref_det!r}) — physical qualification "
                 f"stops before candidate comparison"])
    # 2. Admission verdicts per case (includes per-arm determinism
    #    consumption, provenance, anti-aliasing). The verdict records
    #    are SCHEMA-VALIDATED, not trusted: a bare {"admitted": true}
    #    dict with no admission schema/case binding cannot pass.
    for case in C.FIXTURE_CASES:
        verdict = admissions.get(case)
        if not isinstance(verdict, dict):
            problems.append(f"{case}: admission verdict not a record")
            continue
        if verdict.get("schema") != admission.SCHEMA:
            problems.append(
                f"{case}: admission verdict schema mismatch — only "
                f"records derived by issue273_admission.admit_pair are "
                f"consumable")
            continue
        if verdict.get("case_id") != case:
            problems.append(
                f"{case}: admission verdict case_id {verdict.get('case_id')!r} "
                f"does not bind this case")
            continue
        if verdict.get("admitted") is not True:
            problems.extend(
                f"{case}: {p}" for p in verdict.get("problems") or
                ["admission verdict missing"])
    # 3. Candidate determinism.
    for case in C.FIXTURE_CASES:
        cand_det = (determinism.get(case) or {}).get("candidate")
        if cand_det is not True:
            problems.append(
                f"{case}: candidate primary/repeat not deterministic")
    if problems:
        return _blocked(TERMINAL_RUNTIME_BLOCKED_273, problems)
    record = {
        "schema": SCHEMA,
        "namespace": NAMESPACE_273,
        "terminal": TERMINAL_PASS_273,
        "cases": sorted(admissions),
        "pair_diagnostics": pair_results or {},
        "problems": [],
    }
    return record


def _blocked(terminal: str, problems: list[str]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "namespace": NAMESPACE_273,
        "terminal": terminal,
        "problems": problems,
        "pair_diagnostics": {},
    }


def legacy_terminal_present(doc: Any) -> bool:
    """Any #270 terminal in a #273 record invalidates it."""
    text = str(doc)
    return any(t in text for t in LEGACY_TERMINALS)
