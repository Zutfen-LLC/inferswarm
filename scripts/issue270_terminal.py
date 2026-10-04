#!/usr/bin/env python3
"""Issue #270 (R8-I6) — Phase 1/2/4 producers and terminal reducer.

Completes the producer set begun in issue270_physical.py (Phase 0
reconciliation, fresh host observation, dispatch authority, binary/model
authentication). This module adds:

  Phase 1  write_subject_freeze — durable append-only freeze record
           binding subject, runtime, binaries, fixtures, and the
           frozen candidate-die selection derived by the accepted
           two-index rule.
  Phase 2  validate_selector_binding — the #250-style two-index,
          two-die load-only binding (each Vulkan index probed once;
          selected/excluded residency proven; selection derived by
          the FROZEN rule, never by enumeration order).
  Phase 4  derive_terminal — the single mechanical terminal
           derivation from retained Phase-3 evidence. Numerical
           agreement is retained as diagnostics only; NO threshold,
           NO calibration, NO placement guidance is produced.

Physical execution (server launch, HTTP requests, row capture) is
NOT in this repository pass: the thin executor that drives the live
arms is follow-on work gated on maintainer dispatch at the merged
head. Everything here is unit-testable offline via injectable seams.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any, Callable

import issue270_authority as C
import issue270_comparator as comparator
import issue270_physical as P

BDF_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")


class ReducerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Phase 1 — subject freeze
# ---------------------------------------------------------------------------

def derive_frozen_selection(binding_record: dict[str, Any]) -> dict[str, Any]:
    """Apply the accepted two-index rule to a validated binding record.

    Rule (C.TWO_INDEX_RULE): among the selector->BDF entries of the
    validated preflight mapping, freeze the entry whose SELECTED BDF
    sorts lowest. Derived from validated record content only.
    """
    mapping = binding_record.get("mapping")
    if not isinstance(mapping, dict) or set(mapping) != {"0", "1"}:
        raise ReducerError("binding mapping malformed")
    entries = []
    for key, entry in mapping.items():
        if not isinstance(entry, dict):
            raise ReducerError("binding mapping entry malformed")
        selected, excluded = entry.get("selected_bdf"), entry.get(
            "excluded_bdf")
        if (not isinstance(selected, str) or not isinstance(excluded, str)
                or BDF_RE.fullmatch(selected) is None
                or BDF_RE.fullmatch(excluded) is None
                or selected == excluded
                or selected not in C.DIE_BDFS or excluded not in C.DIE_BDFS):
            raise ReducerError(f"binding entry {key} malformed")
        entries.append((selected, excluded))
    if len({e[0] for e in entries}) != 2:
        raise ReducerError("duplicate selector-to-BDF mapping")
    entries.sort()
    selected_bdf, excluded_bdf = entries[0]
    return {"rule": C.TWO_INDEX_RULE, "selected_bdf": selected_bdf,
            "excluded_bdfs": (excluded_bdf,),
            "selected_index": next(
                k for k, v in mapping.items()
                if v.get("selected_bdf") == selected_bdf)}


def write_subject_freeze(evidence_root: Path, repo_root: Path,
                         host_observation: dict[str, Any],
                         binding_record: dict[str, Any],
                         dispatch: dict[str, Any]) -> dict[str, Any]:
    """Durable Phase-1 freeze: bind every identity BEFORE observation."""
    derived = P.derive_v340_identity(host_observation["raw"])
    drift = P.identity_problems_vs_frozen(derived)
    if drift:
        raise P.PhysicalError(
            "fresh host identity drift at freeze: " + "; ".join(drift))
    selection = derive_frozen_selection(binding_record)
    fixtures = C.load_fixtures(repo_root)
    freeze = {
        "schema": P.FREEZE_SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "host_observation": {
            "host": host_observation["host"],
            "derived": derived,
            "observed_at": host_observation["observed_at"],
            "observation_digest": C.authority_digest(
                host_observation["raw"]),
        },
        "frozen_selection": selection,
        "subject": {
            "llama_source_pin": C.LLAMA_SOURCE_PIN,
            "llama_source_tree": C.ACCEPTED_LLAMA_SOURCE_TREE,
            "comparator_sha256": C.COMPARATOR_SHA256,
            "canonical_sha256": C.CANONICAL_SHA256,
            "observer_libs": dict(C.OBSERVER_LIBS),
            "model_dir": C.MODEL_DIR,
            "model_members": dict(C.MODEL_MEMBER_SHA256),
            "request_contract": C.REQUEST_CONTRACT,
            "context_settings": C.CONTEXT_SETTINGS,
            "fixture_ladder_sha256": C.FIXTURE_LADDER_SHA256,
            "fixture_cases": list(C.FIXTURE_CASES),
            "ngl": C.SELECTED_PLACEMENT_NGL,
        },
        "reference": C.reference_identity(),
        "dispatch": {
            "comment_id": dispatch["comment_id"],
            "head_sha": dispatch["head_sha"],
            "namespace": dispatch["namespace"],
            "digest": C.authority_digest(dispatch),
        },
        "binding_digest": C.authority_digest(binding_record),
        "frozen_at": P._utcnow(),
    }
    freeze["self_digest_sha256"] = C.authority_digest(
        {k: v for k, v in freeze.items() if k != "self_digest_sha256"})
    path = Path(evidence_root) / P.FREEZE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    P._write_json(path, freeze)
    return freeze


def load_subject_freeze(evidence_root: Path) -> dict[str, Any]:
    path = Path(evidence_root) / P.FREEZE_NAME
    if path.is_symlink() or not path.is_file():
        raise ReducerError(f"subject freeze missing: {path}")
    freeze = json.loads(path.read_bytes())
    expected = freeze.get("self_digest_sha256")
    actual = C.authority_digest(
        {k: v for k, v in freeze.items() if k != "self_digest_sha256"})
    if expected != actual:
        raise ReducerError("subject freeze self-digest mismatch")
    # JSON round-trip turns the frozen selection tuple into a list;
    # restore declared tuples so downstream comparisons are type-stable.
    selection = freeze.get("frozen_selection") or {}
    if isinstance(selection.get("excluded_bdfs"), list):
        selection["excluded_bdfs"] = tuple(selection["excluded_bdfs"])
    return freeze


# ---------------------------------------------------------------------------
# Phase 2 — two-index selector binding validation (#243/#250 law)
# ---------------------------------------------------------------------------

def validate_selector_binding(record: dict[str, Any], expected_head: str,
                              binary_sha: str, *, host: str = C.CANDIDATE_HOST
                              ) -> dict[str, Any]:
    """Authenticate a fresh two-index, two-die load-only binding.

    Shape follows the accepted #250 V0 binding: one probe per Vulkan
    index, each proving selected-die residency >= the noise bound and
    excluded-die residency < the noise bound. The selected index for
    the campaign is then derived by the frozen rule.
    """
    if not isinstance(record, dict) or record.get("schema") != C.BINDING_SCHEMA:
        raise P.PhysicalError("#270 selector binding record missing")
    if (record.get("expected_pr_head") != expected_head
            or record.get("host") != host
            or record.get("binary_sha256") != binary_sha
            or binary_sha != C.COMPARATOR_SHA256
            or record.get("icd") != C.RADV_ICD
            or record.get("cuda_visible_devices") != "-1"):
        raise P.PhysicalError(
            "#270 selector binding head/binary/ICD mismatch")
    mapping = record.get("mapping")
    if (not isinstance(mapping, dict) or set(mapping) != {"0", "1"}):
        raise P.PhysicalError("#270 binding mapping malformed")
    for key, entry in mapping.items():
        if not isinstance(entry, dict):
            raise P.PhysicalError("#270 binding entry malformed")
        a, b = entry.get("selected_bdf"), entry.get("excluded_bdf")
        if (a not in C.DIE_BDFS or b not in C.DIE_BDFS or a == b
                or set(entry.get("vram_before", {})) != set(C.DIE_BDFS)
                or set(entry.get("vram_after", {})) != set(C.DIE_BDFS)):
            raise P.PhysicalError(f"#270 binding {key} BDF/residency shape")
        before, after = entry["vram_before"], entry["vram_after"]
        if any(type(v) is not int or v < 0
               for v in list(before.values()) + list(after.values())):
            raise P.PhysicalError("#270 residency counters malformed")
        if (after[a] - before[a] < C.EXCLUDED_NOISE_BYTES
                or after[b] - before[b] >= C.EXCLUDED_NOISE_BYTES):
            raise P.PhysicalError(
                f"#270 index {key}: selected/excluded residency unproven")
    return derive_frozen_selection(record)


# ---------------------------------------------------------------------------
# Phase 4 — mechanical terminal derivation
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ReducerError(f"evidence file missing: {path}")
    return json.loads(path.read_bytes())


def derive_terminal(evidence_root: Path, repo_root: Path,
                    expected_head: str,
                    row_reader: Callable[[str], bytes] | None = None,
                    ) -> dict[str, Any]:
    """Derive the SINGLE terminal from retained Phase-3 bytes.

    Mechanical and total: any missing/invalid evidence yields a BLOCKED
    terminal — never a partial PASS. Numerical deltas are copied into
    the diagnostics verbatim; the reducer derives no threshold.
    """
    evidence_root = Path(evidence_root)
    row_reader = row_reader or comparator.custody_row_reader(evidence_root)
    problems: list[str] = []
    diagnostics: dict[str, Any] = {}

    # 0. Freeze custody binds the run to this exact evidence root.
    try:
        freeze = load_subject_freeze(evidence_root)
    except (ReducerError, ValueError) as exc:
        return _terminal(C.TERMINAL_AUTHORITY_BLOCKED,
                         [f"subject freeze unusable: {exc}"], {})
    if freeze["dispatch"]["head_sha"] != expected_head:
        return _terminal(C.TERMINAL_AUTHORITY_BLOCKED,
                         ["freeze head != authorized head"], {})
    selection = freeze["frozen_selection"]
    frozen_ref = freeze["reference"]

    # 1. Phase-2 preflight record.
    try:
        preflight = _load_json(evidence_root / P.PREFLIGHT_NAME)
    except (ReducerError, ValueError) as exc:
        return _terminal(C.TERMINAL_INFRASTRUCTURE_BLOCKED,
                         [f"phase-2 preflight missing: {exc}"], {})
    try:
        binding_sel = validate_selector_binding(
            preflight.get("selector_binding", {}),
            expected_head, C.COMPARATOR_SHA256)
    except P.PhysicalError as exc:
        return _terminal(C.TERMINAL_INFRASTRUCTURE_BLOCKED,
                         [f"selector binding invalid: {exc}"], {})
    if binding_sel["selected_bdf"] != selection["selected_bdf"]:
        return _terminal(C.TERMINAL_INFRASTRUCTURE_BLOCKED,
                         ["preflight selection != frozen selection"], {})

    # 2. Per-case comparator/2 units (reference+candidate, repeat, inertness).
    units: dict[str, Any] = {}
    for case in C.FIXTURE_CASES:
        try:
            C.validate_case(case)
        except C.AuthorityError as exc:
            return _terminal(C.TERMINAL_AUTHORITY_BLOCKED, [str(exc)], {})
        unit_dir = evidence_root / "units" / case
        arm_files = {
            "reference": unit_dir / "reference.json",
            "candidate": unit_dir / "candidate.json",
            "reference_repeat": unit_dir / "reference-repeat.json",
            "candidate_repeat": unit_dir / "candidate-repeat.json",
        }
        missing = [n for n, p in arm_files.items()
                   if p.is_symlink() or not p.is_file()]
        if missing:
            problems.append(f"{case}: arm receipts missing: {missing}")
            continue
        try:
            receipts = {name: comparator.load_run_receipt(path)
                        for name, path in arm_files.items()}
        except (ValueError, OSError) as exc:
            problems.append(f"{case}: receipts unreadable: {exc}")
            continue
        # Repeat receipts must declare the repeat tag.
        for tag in ("reference_repeat", "candidate_repeat"):
            if receipts[tag].get("repeat_of") != tag.removesuffix(
                    "_repeat"):
                problems.append(f"{case}: {tag} repeat_of malformed")
        pair = comparator.validate_pair(
            receipts["reference"], receipts["candidate"], row_reader,
            frozen_ref)
        ref_det = comparator.validate_determinism(
            receipts["reference"], receipts["reference_repeat"],
            row_reader)
        cand_det = comparator.validate_determinism(
            receipts["candidate"], receipts["candidate_repeat"],
            row_reader)
        inert = comparator.validate_inertness(
            receipts["reference"].get("disabled_observer_tokens") or [],
            receipts["reference"].get("canonical_tokens") or [],
            bool(receipts["reference"].get("disabled_observer_emitted",
                                           True)),
            bool(receipts["reference"].get("canonical_emitted", True)))
        diagnostics[case] = {
            "pair": pair["diagnostic"],
            "reference_deterministic": ref_det["deterministic"],
            "candidate_deterministic": cand_det["deterministic"],
            "observer_inert": inert["inert"],
        }
        for sub, res in (("pair", pair), ("ref_det", ref_det),
                         ("cand_det", cand_det), ("inert", inert)):
            key = {"pair": "validated", "ref_det": "deterministic",
                   "cand_det": "deterministic", "inert": "inert"}[sub]
            if not res[key]:
                problems.extend(
                    f"{case} {sub}: {p}" for p in res["problems"])
        units[case] = True

    if set(units) != set(C.FIXTURE_CASES):
        return _terminal(C.TERMINAL_RUNTIME_BLOCKED, problems, diagnostics)

    # 3. Prohibition tripwires on the retained corpus: every row path
    #    consumed must live under units/<authorized-case>/; every case
    #    must be an authorized fixture. (Custody reader already refuses
    #    traversal; the case set was validated above.)
    record = {
        "schema": P.TERMINAL_SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "head_sha": expected_head,
        "frozen_selection": selection,
        "units": sorted(units),
        "diagnostics": diagnostics,
        "problems": problems,
    }
    record["terminal"] = (C.TERMINAL_PASS if not problems
                          else C.TERMINAL_RUNTIME_BLOCKED)
    record["derived_at"] = P._utcnow()
    return record


def _terminal(terminal: str, problems: list[str],
              diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": P.TERMINAL_SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "terminal": terminal,
        "problems": problems,
        "diagnostics": diagnostics,
        "derived_at": P._utcnow(),
    }
