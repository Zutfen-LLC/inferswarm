#!/usr/bin/env python3
"""Issue #277: CPU-recordable, reference-first retained-byte gate.

This is not a physical dispatch entry point. The executor is an injected
callback (invoked once per required case, only after the complete reference
preflight); its return value is NOT evidence. Both arms' primary/repeat rows
are independently admitted from #276's staged + collector-custody bytes.
Neither callback nor caller can supply a determinism verdict. Success marks
only a fixture candidate gate, never #273 physical authority/PASS.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import issue270_authority as C
import issue273_reducer as R
from issue276_reader import ReaderError, admit_pair_276, admit_staged_276

SCHEMA = "inferswarm.issue277.reference-first/1"
_EVIDENCE_ERRORS = (ReaderError, OSError, ValueError, TypeError, KeyError, IndexError)
_ROWS = {str(d) for d in range(C.DECISIONS)}


def _unit(staged_root: Path, custody_root: Path, case: str,
          arm: str, repeat: bool) -> dict[str, Any]:
    """No authored per-unit admission inputs: read the real #276 byte path."""
    try:
        return admit_staged_276(staged_root, case, arm, repeat,
                                custody_root=custody_root)
    except _EVIDENCE_ERRORS as exc:
        return {"admitted": False, "derived": {}, "problems": [str(exc)]}


def _arm(staged_root: Path, custody_root: Path, case: str, arm: str
         ) -> tuple[dict[str, Any], list[str], bool]:
    primary = _unit(staged_root, custody_root, case, arm, False)
    repeat = _unit(staged_root, custody_root, case, arm, True)
    problems = [f"{case} {arm}{'+repeat' if is_repeat else ''}: {problem}"
                for is_repeat, unit in ((False, primary), (True, repeat))
                for problem in unit.get("problems", [])]
    admitted = all(unit.get("admitted") is True and not unit.get("problems")
                   for unit in (primary, repeat))
    maps = []
    for unit in (primary, repeat):
        derived = unit.get("derived")
        row_map = derived.get("row_sha256") if isinstance(derived, dict) else None
        if (not isinstance(row_map, dict) or set(row_map) != _ROWS
                or any(not isinstance(digest, str) or len(digest) != 64
                       for digest in row_map.values())):
            row_map = {}
            if unit.get("admitted") is True:
                problems.append(f"{case} {arm}: admitted unit lacks complete byte-derived row digests")
            admitted = False
        maps.append(dict(row_map))
    # A repeat must be another process/capture, not the primary reused under
    # a new tag. #276 pair admission enforces this again after candidate phase.
    if admitted:
        a, b = (unit["derived"] for unit in (primary, repeat))
        incarnation = lambda item: tuple(item.get(k) for k in ("pid", "boot_id", "start_ticks"))
        if incarnation(a) == incarnation(b):
            problems.append(f"{case} {arm} repeat shares primary process incarnation/source capture")
            admitted = False
    deterministic = admitted and maps[0] == maps[1]
    if admitted and not deterministic:
        problems.append(f"{case} {arm} primary/repeat row digest mismatch")
    return ({"primary_admitted": primary.get("admitted") is True,
             "repeat_admitted": repeat.get("admitted") is True,
             "primary_row_sha256": maps[0], "repeat_row_sha256": maps[1],
             "deterministic": deterministic}, problems, admitted)


def orchestrate_277(staged_root: Path, custody_root: Path,
                    executor: Callable[[str], Any],
                    pair_comparison: Callable[[str, dict, dict], Any] | None = None
                    ) -> dict[str, Any]:
    """Gate all required cases in two phases: ALL references, THEN candidates.

    The executor is called once per case, in C.FIXTURE_CASES order. Its result
    is discarded: only independently admitted #276 row bytes can determine
    the result. Pair comparison (optional, once per case) is reached only
    after *all* candidate admissions/determinism and #276 pair law pass.
    No callback receives a caller-authored verdict or physical authority.
    """
    staged_root, custody_root = Path(staged_root), Path(custody_root)
    record = {"schema": SCHEMA, "status": "blocked", "terminal": None,
              "problems": [], "candidate_launches": 0, "cases": {}}
    cases = tuple(C.FIXTURE_CASES)
    for case in cases:
        record["cases"][case] = {}
        item, issues, valid = _arm(staged_root, custody_root, case, "reference")
        record["cases"][case]["reference"] = item
        record["problems"].extend(issues)
        # Admission defects are NOT observed determinism mismatches: reserve
        # the reference-specific #273 terminal for two valid captures.
        if not valid:
            record["terminal"] = R.TERMINAL_RUNTIME_BLOCKED_273
    if record["terminal"] is not None:
        return record
    if any(not record["cases"][case]["reference"]["deterministic"] for case in cases):
        record["terminal"] = R.TERMINAL_REFERENCE_NONDETERMINISTIC_273
        return record

    # STRUCTURAL boundary: execution is unreachable until the loop above
    # has admitted/digest-compared every required reference primary+repeat.
    for case in cases:
        record["candidate_launches"] += 1
        try:
            executor(case)  # never use a callback result as evidence
        except Exception as exc:
            record["problems"].append(f"{case} candidate executor failed: {exc}")
            record["terminal"] = R.TERMINAL_RUNTIME_BLOCKED_273
            return record

    for case in cases:
        item, issues, valid = _arm(staged_root, custody_root, case, "candidate")
        record["cases"][case]["candidate"] = item
        record["problems"].extend(issues)
        if not valid or not item["deterministic"]:
            record["terminal"] = R.TERMINAL_RUNTIME_BLOCKED_273
    if record["terminal"] is not None:
        return record

    # Pair admission adds cross-arm row/ICD/incarnation/source anti-aliasing
    # and repeats the per-arm law. It cannot replace independent unit checks.
    for case in cases:
        try:
            pair = admit_pair_276(staged_root, case, custody_root=custody_root)
        except _EVIDENCE_ERRORS as exc:
            record["problems"].append(f"{case} pair admission failed: {exc}")
            record["terminal"] = R.TERMINAL_RUNTIME_BLOCKED_273
            return record
        if (pair.get("admitted") is not True or pair.get("problems")
                or pair.get("units") != {"reference": True, "reference+repeat": True,
                                         "candidate": True, "candidate+repeat": True}):
            record["problems"].extend(f"{case} pair: {p}" for p in pair.get("problems", []))
            if not pair.get("problems"):
                record["problems"].append(f"{case} pair admission incomplete")
            record["terminal"] = R.TERMINAL_RUNTIME_BLOCKED_273
            return record

    # This is a fixture gate only, not a physical terminal. Comparison return
    # values cannot supply a verdict; they are ignored just like executor data.
    for case in cases:
        if pair_comparison is not None:
            try:
                pair_comparison(case, record["cases"][case]["reference"]["primary_row_sha256"],
                                record["cases"][case]["candidate"]["primary_row_sha256"])
            except Exception as exc:
                record["problems"].append(f"{case} pair comparison failed: {exc}")
                record["terminal"] = R.TERMINAL_RUNTIME_BLOCKED_273
                return record
    record["status"] = "candidate gate reached"
    return record
