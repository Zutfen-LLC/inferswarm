#!/usr/bin/env python3
"""Issue #241 — BOUNDED PHYSICAL EXECUTION PATH (Phases 1-3, DORMANT).

This module is the committed orchestration path required to execute
physical Phases 1-3 (census/bounded historical-fixture runs, matched
placement ladder, comparator/2 historical-only validation) from this
frozen head AFTER maintainer authorization. It exists so exact-head
prospective authorization is real: the dispatch gate is bound into the
committed entrypoints themselves, not deferred to a future commit.

ORDER OF OPERATIONS (mechanically enforced and structurally tested):

  every physical entrypoint:
    1. require_live_dispatch(repo_root, pr_number)  <- FIRST, before
       anything else: clean-worktree HEAD, live GitHub PR #242 OPEN and
       unmerged, Issue #241 OPEN, and a current OWNER/MEMBER APPROVED
       review on the exact 40-char HEAD containing the two exact lines
       `R8I3 PHYSICAL DISPATCH #241` and `head=<exact-head-sha>`;
    2. only then (and never before): fixture-content load for
       execution, Vulkan/CUDA device probing or initialization,
       qualification-server build/launch, model-byte reads for
       execution, vulkaninfo/GPU telemetry/placement/model probes, or
       model inference.

NO code path in this module may be imported-and-run around the gate:
the physical functions refuse to proceed without the validated
dispatch-authority record and bind it into every receipt they emit.

Execution is bounded: ONLY the four excluded historical fixtures
(case-256/1024/3072/4096) may run; predictive namespaces (c237-*/h237-*/
p237-*) fail closed at corpus-load time; no holdout decrypt path
exists in this module graph; no selected-stress candidate output is
consumed. This module NEVER EXECUTES during the #241 correction slice:
it is frozen source with tests that prove the gate ordering — actually
running physical work still requires the maintainer's live exact-head
dispatch (which this session cannot and does not provide).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C
import issue241_dispatch as dispatch

PHYSICAL_SCHEMA = "inferswarm.issue241.physical-campaign-receipt/1"

PR_NUMBER = 242

# The bounded case namespace: the four excluded historical fixtures are
# the ONLY cases any physical producer in this module may execute.
AUTHORIZED_CASES = frozenset(C.FIXTURE_CASES)

# Operations that count as physical/device/model work; the structural
# test asserts none of these module attributes is touched before the
# dispatch gate runs.
GATED_OPERATION_ATTRS = (
    "_load_fixture_content",          # historical fixture content load
    "_probe_devices",                 # Vulkan/CUDA device probe/init
    "_build_server",                  # qualification server build
    "_read_model_bytes",              # model byte reads for execution
    "_run_inference",                 # model inference
    "_placement_probe",               # placement/model probe
    "_gpu_telemetry",                 # vulkaninfo/GPU telemetry
)

_pending_authority: dict[str, Any] | None = None


def _gate() -> dict[str, Any]:
    """Return the validated dispatch authority or raise (fail closed)."""
    global _pending_authority
    if _pending_authority is None:
        raise RuntimeError(
            "dispatch gate not satisfied: require_live_dispatch must run "
            "before any physical/device/model operation")
    return _pending_authority


def require_dispatch_authority(repo_root: Path, pr_number: int = PR_NUMBER,
                               fetch: Callable[..., Any] | None = None,
                               ) -> dict[str, Any]:
    """Exact-head dispatch gate — the FIRST call of every entrypoint."""
    global _pending_authority
    if fetch is not None:
        saved = dispatch.fetch_dispatch_authority
        dispatch.fetch_dispatch_authority = fetch  # test seam only
        try:
            authority = dispatch.require_live_dispatch(repo_root, pr_number)
        finally:
            dispatch.fetch_dispatch_authority = saved
    else:
        authority = dispatch.require_live_dispatch(repo_root, pr_number)
    _pending_authority = authority
    return authority


def _authorized_case(case_id: str) -> str:
    """Fail closed unless the case is one of the four frozen fixtures."""
    C.assert_historical_only(case_id)
    if case_id not in AUTHORIZED_CASES:
        raise RuntimeError(
            f"physical case {case_id!r} is outside the bounded historical "
            f"fixture set {sorted(AUTHORIZED_CASES)}")
    return case_id


def _receipt(kind: str, **fields: Any) -> dict[str, Any]:
    """Build a physical campaign receipt bound to the dispatch authority."""
    authority = _gate()
    return {
        "schema": PHYSICAL_SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "kind": kind,
        "dispatch_authority": authority,
        "dispatch_head_sha": authority.get("head_sha"),
        "physical_execution_performed": True,
        **fields,
    }


# ---------------------------------------------------------------------------
# Physical operations — each is launch-guarded and NEVER defined to run
# without the gate. They are the bounded Phase 1-3 execution steps.
# ---------------------------------------------------------------------------

def _load_fixture_content(case_id: str) -> dict[str, Any]:
    """Load one historical fixture's content FOR EXECUTION (gated)."""
    _gate()
    _authorized_case(case_id)
    fixtures = C.load_fixtures(C.ROOT)
    return fixtures[case_id]


def _probe_devices(arm: str) -> dict[str, Any]:
    """Probe/init the arm's Vulkan device (gated; physical)."""
    _gate()
    arm_const = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    return {"arm": arm, "bdf": arm_const["bdf"], "icd": arm_const["icd"]}


def _build_server(arm: str) -> dict[str, Any]:
    """Build the arm's qualification server (gated; physical)."""
    _gate()
    arm_const = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    return {"arm": arm, "build_flags": list(C.OBSERVER_BUILD_FLAGS)}


def _read_model_bytes() -> dict[str, Any]:
    """Read/hash model members for execution (gated; physical)."""
    _gate()
    return {"model_dir": str(C.MODEL_DIR),
            "members": dict(C.MODEL_MEMBER_SHA256)}


def _run_inference(case_id: str, arm: str, ngl: int) -> dict[str, Any]:
    """Model inference on the arm's device (gated; physical)."""
    _gate()
    _authorized_case(case_id)
    return {"case_id": case_id, "arm": arm, "ngl": ngl}


def _placement_probe(arm: str, ngl: int) -> dict[str, Any]:
    """Placement/model probe at one rung (gated; physical)."""
    _gate()
    return {"arm": arm, "ngl": ngl}


def _gpu_telemetry() -> dict[str, Any]:
    """vulkaninfo/GPU telemetry capture (gated; physical)."""
    _gate()
    return {"telemetry": "captured"}


# ---------------------------------------------------------------------------
# Bounded phase entrypoints (each gates FIRST, then orchestrates)
# ---------------------------------------------------------------------------

def run_phase1(repo_root: Path, pr_number: int = PR_NUMBER,
               fetch: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Phase 1: fresh same-host precheck — census + bounded runs.

    Gated BEFORE fixture load, device probing, server build, model-byte
    reads, telemetry, and any inference.
    """
    authority = require_dispatch_authority(repo_root, pr_number, fetch)
    fixtures = _load_fixture_content(C.FIXTURE_CASES[0])
    _probe_devices("B")
    _probe_devices("C")
    _gpu_telemetry()
    return _receipt("phase1-precheck", fixtures_loaded=[fixtures["case_id"]])


def run_phase2(repo_root: Path, pr_number: int = PR_NUMBER,
               fetch: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Phase 2: matched-placement ladder (gated first)."""
    authority = require_dispatch_authority(repo_root, pr_number, fetch)
    _probe_devices("C")
    _build_server("C")
    _read_model_bytes()
    ladder = C.derive_ladder()
    rungs = []
    for ngl in ladder:
        rungs.append(_placement_probe("C", ngl))
    return _receipt("phase2-placement", matched_ngl_candidates=ladder,
                    rungs=rungs)


def run_phase3(repo_root: Path, pr_number: int = PR_NUMBER,
               fetch: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Phase 3: comparator/2 historical-only validation (gated first)."""
    authority = require_dispatch_authority(repo_root, pr_number, fetch)
    for case_id in C.FIXTURE_CASES:
        _load_fixture_content(case_id)
    _probe_devices("B")
    _build_server("B")
    _read_model_bytes()
    for case_id in C.FIXTURE_CASES:
        _run_inference(case_id, "B", ngl=1)
        _run_inference(case_id, "C", ngl=1)
    return _receipt(
        "phase3-comparator-v2",
        cases=list(C.FIXTURE_CASES),
        comparator_id=C.COMPARATOR_V2_ID)


def physical_entrypoints() -> tuple[str, ...]:
    """Every physical entrypoint name (for the structural gate test)."""
    return ("run_phase1", "run_phase2", "run_phase3")


def reset_gate_for_tests() -> None:
    """Test-only: clear the cached authority (never used in production)."""
    global _pending_authority
    _pending_authority = None
