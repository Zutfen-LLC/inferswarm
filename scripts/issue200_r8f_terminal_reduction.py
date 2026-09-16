#!/usr/bin/env python3
"""Issue #200 (R8-F) machine-derived terminal classification.

Combines the compact policy proof, corrected Phase-4 cache finding, and (if
present) mechanically validated Phase-5 receipts into one of the three Issue
#200 terminals.  An unresolved Phase 5 is deliberately *not* a terminal.

1. the compact CPU source-policy/local-backing campaign
   (``issue200_r8f_proof.run_campaign``) - Phases 1-3;
2. the Phase 4 launch-configuration finding, derived from the exact
   committed R8-D v2 launch-orchestration source
   (``scripts/issue195_v2_launch.py``) - never re-executed, never
   requalified, read only. This finding is narrow: it establishes only
   that the accepted R8-D v2 launch never passed a model path (or ``-c``)
   to any RPC backend process. It does NOT by itself establish whether the
   pinned runtime has any participant-local-backing seam at all -- an
   earlier revision of this reducer drew that broader conclusion from this
   narrow fact alone, which was incorrect and is retracted below.
3. the corrected cache-mechanism finding
   (``issue200_r8f_rpc_cache_mechanism.mechanical_cache_finding``),
   mechanically re-derived from a retained, bounded, non-Qwen experiment
   that built and ran the actual pinned ``ggml-rpc-server`` binary and
   proved its ``-c``/``RPC_CMD_SET_TENSOR_HASH`` local-cache seam.

This script does not perform any physical GPU/network action; it is a pure
CPU reducer over already-committed repository evidence plus the fresh
compact campaign it runs itself. No llama.cpp source was modified to
produce any evidence this script reads.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from issue200_r8f_proof import ROOT, AREA, run_campaign, write_evidence
import issue200_r8f_rpc_cache_mechanism as cache_mechanism
import issue200_r8f_physical as physical

TERMINAL_LOCAL_VERIFIED_BACKING_PASS = "R8F_LOCAL_VERIFIED_BACKING_PASS"
TERMINAL_RUNTIME_LOCAL_BACKING_PREREQUISITE = "R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE"
TERMINAL_GENERIC_SOURCE_POLICY_BLOCKED = "R8F_GENERIC_SOURCE_POLICY_BLOCKED"

LLAMA_CPP_PINNED_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
RPC_LAUNCH_SOURCE = "scripts/issue195_v2_launch.py"

PHYSICAL_PHASE5_EVIDENCE_DEFAULT_PATH = ROOT / AREA / "evidence" / "physical-phase5.json"
PHYSICAL_PHASE5_SCHEMA = physical.SCHEMA


def phase4_mechanical_finding() -> dict[str, Any]:
    """Mechanically re-derive the narrow Phase 4 launch-configuration fact
    from committed launch-orchestration source, rather than asserting it as
    an authored claim.

    ``scripts/issue195_v2_launch.py`` (the exact producer that launched the
    accepted R8-D v2 physical candidate arm) invokes the RPC backend binary
    with only ``-H``, ``-p``, and ``-d`` (device) flags - no ``-m``/model
    path argument and no ``-c``/cache flag exists anywhere in ``RPC03_G0``,
    ``RPC03_G1``, or ``RPC04``. Only the client ``llama-server`` invocation
    (``CAND_SH``) receives ``-m {MODEL}``. This is read directly from the
    committed producer text, not inferred, so a later change to that file
    would change this finding the next time this reducer runs against it.

    CORRECTION (this revision): this fact establishes only that the R8-D v2
    launch, as configured, never exercised any RPC-backend-local
    materialization path. An earlier revision of this reducer treated that
    absence as proof that the pinned runtime has *no* such path at all -
    that broader inference was false and is retracted. The pinned build
    separately implements a local file cache for large tensors
    (``-c``/``--cache``, ``RPC_CMD_SET_TENSOR_HASH``) which this specific
    launch simply never enabled. See ``cache_mechanism_finding`` (below,
    also embedded in this document) for the corrected treatment.
    """
    launch_path = ROOT / RPC_LAUNCH_SOURCE
    source = launch_path.read_text()
    import re
    blocks = {}
    for name in ("CAND_SH", "RPC03_G0", "RPC03_G1", "RPC04"):
        match = re.search(rf'{name} = f"""(.*?)"""', source, re.DOTALL)
        if not match:
            raise AssertionError(f"phase4: could not locate {name} block in {RPC_LAUNCH_SOURCE}")
        blocks[name] = match.group(1)
    client_has_model_arg = "-m {MODEL}" in blocks["CAND_SH"] or "-m " in blocks["CAND_SH"]
    rpc_backend_has_model_arg = any("-m " in blocks[name] for name in ("RPC03_G0", "RPC03_G1", "RPC04"))
    rpc_backend_has_cache_flag = any(
        (" -c " in (" " + blocks[name] + " ")) or ("--cache" in blocks[name])
        for name in ("RPC03_G0", "RPC03_G1", "RPC04"))
    return {
        "schema": "inferswarm.issue200.phase4-finding/2",
        "pinned_llama_cpp_commit": LLAMA_CPP_PINNED_COMMIT,
        "evidence_source": RPC_LAUNCH_SOURCE,
        "client_process_receives_model_path_argument": client_has_model_arg,
        "rpc_backend_process_receives_model_path_argument": rpc_backend_has_model_arg,
        "rpc_backend_process_receives_cache_flag": rpc_backend_has_cache_flag,
        "finding": (
            "In the exact accepted R8-D v2 launch configuration, the client llama-server "
            "process is the only process given a model path; every ggml-rpc-server backend "
            "process is launched with only -H/-p/-d, no model path and no -c/--cache flag. "
            "This narrow fact is scoped to this one launch configuration. It does not, by "
            "itself, establish whether the pinned ggml-rpc runtime has any "
            "participant-local-backing seam -- that broader question is answered separately "
            "and correctly by cache_mechanism_finding, not by this fact."
        ),
        "retraction_note": (
            "An earlier revision of this reducer used this launch-configuration fact alone to "
            "conclude 'the RPC backend process has no independent model-loading capability and "
            "no seam to consume a participant-local verified artifact for its assigned tensors "
            "without the client retransmitting those exact bytes over the wire' and emitted "
            "R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE on that basis. That conclusion did not "
            "inspect the pinned ggml-rpc-server's local-cache implementation "
            "(tools/rpc/rpc-server.cpp, ggml/src/ggml-rpc/ggml-rpc.cpp) at all and is retracted. "
            "It is superseded by cache_mechanism_finding, which mechanically tested that seam "
            "directly against the pinned binary."
        ),
    }


def cache_mechanism_finding() -> dict[str, Any]:
    """The corrected Phase 4 answer: mechanically re-derived from a retained,
    bounded, non-Qwen experiment against the actual pinned ggml-rpc-server
    binary (see evidence/rpc-cache-experiment.json and
    evidence/rpc-cache-experiment-raw/). Raises if that retained evidence is
    absent -- this terminal reducer must never fall back to guessing a
    runtime-prerequisite terminal just because the cache seam was not
    exhaustively evaluated.
    """
    return cache_mechanism.mechanical_cache_finding()


def environment_execution_note() -> dict[str, Any]:
    """Records (does not claim to resolve) the separate, non-substrate reason
    Phase 5 did not run in this execution environment: this session has no
    usable authorized access to the physical fleet hosts the R8-D v2 campaign
    used. Hostname resolution alone is not authorization to operate the fleet.
    This is independent of the cache-mechanism finding above; both are
    reported so neither is mistaken for the other."""
    return {
        "schema": "inferswarm.issue200.execution-environment-note/1",
        "fleet_phase5_authorized_from_this_session": False,
        "note": ("The fleet hostnames resolve from this session, but an SSH "
                 "BatchMode probe to inferswarm01 was rejected for lack of a "
                 "usable credential. This is an execution-environment constraint "
                 "only; it is not evidence about the legal cache seam or a final "
                 "Issue #200 terminal."),
    }


def load_physical_phase5_evidence(path: Path | None = None) -> dict[str, Any]:
    """Load and strictly validate optional physical Phase 5 evidence.
    Fails closed: absent, unparseable, schema-mismatched, or
    predicate-incomplete evidence is never treated as a pass, and is always
    reported with an explicit reason rather than silently ignored."""
    target = path if path is not None else PHYSICAL_PHASE5_EVIDENCE_DEFAULT_PATH
    try:
        display_path = target.relative_to(ROOT)
    except ValueError:
        display_path = target
    if not target.is_file():
        return {"evidence_file_present": False, "valid": False,
                "reason": f"no physical Phase 5 evidence file at {display_path}"}
    try:
        doc = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as error:
        return {"evidence_file_present": True, "valid": False,
                "reason": f"physical Phase 5 evidence file is not valid JSON: {error}"}
    if not isinstance(doc, dict):
        return {"evidence_file_present": True, "valid": False,
                "reason": "physical Phase 5 evidence is not a JSON object"}
    validation = physical.validate_physical_evidence(doc, evidence_root=target.parent)
    return {"evidence_file_present": True, "valid": validation["valid"],
            "reason": validation.get("reason"), "document": doc,
            "derived": validation.get("derived")}


def reduce_terminal(physical_phase5_evidence_path: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = run_campaign()
    summary = campaign["canonical-summary.json"]
    compact_seam_pass = bool(summary["all_arms_passed"] and summary["all_negative_controls_failed_closed"])
    phase4 = phase4_mechanical_finding()
    cache_finding = cache_mechanism_finding()
    environment = environment_execution_note()
    physical = load_physical_phase5_evidence(physical_phase5_evidence_path)

    # Fail closed.  Phase 4 case C establishes a legal generic cache seam,
    # but does not settle the actual frozen Qwen payload boundaries.  Until
    # Phase 5 settles them, this campaign is explicitly incomplete outside
    # the terminal field.  It may never invent a fourth terminal.
    if not compact_seam_pass:
        terminal = TERMINAL_GENERIC_SOURCE_POLICY_BLOCKED
    elif physical["evidence_file_present"] and physical["valid"]:
        terminal = TERMINAL_LOCAL_VERIFIED_BACKING_PASS
    else:
        terminal = None

    physical_phase5_handoff = None
    if terminal is None:
        physical_phase5_handoff = {
            "required_release": "accepted Qwen3.8-Flash-Next UD-IQ1_S release (accepted hashes)",
            "seam_to_exercise": ("bounded external adapter that verifies InferSwarm provenance for "
                                 "each participant's assigned tensors, then materializes them into "
                                 "the pinned ggml-rpc-server's -c/--cache directory at the exact "
                                 "FNV-1a-named path the client will probe for, before the client "
                                 "connects"),
            "comparison_required": [
                "remote/cold arm: RPC backends launched without -c or with an empty cache "
                "(reproduces accepted R8-D v2 topology)",
                "local-verified arm: identical required state and placement, RPC backends "
                "launched with -c and pre-staged via the adapter above from InferSwarm-verified "
                "local backing, zero prior network SET_TENSOR pass for that content",
                "local-verified arm repeated once more for stability",
            ],
            "evidence_to_retain": ["exact network bytes per arm", "local/cache attribution",
                                   "initialization timing", "required-state identity",
                                   "materialization identity", "provenance verification records"],
            "not_yet_proven": cache_finding["boundary_condition_not_proven"],
            "why_not_run_here": environment["note"],
        }

    document = {
        "schema": "inferswarm.issue200.terminal-reduction/3",
        "compact_source_policy_seam_pass": compact_seam_pass,
        "phase4_launch_configuration_finding": phase4,
        "cache_mechanism_finding": cache_finding,
        "execution_environment_note": environment,
        "physical_phase5_ran": physical["evidence_file_present"] and physical["valid"],
        "physical_phase5_evidence_status": physical,
        "physical_phase5_handoff": physical_phase5_handoff,
        "status": "PHASE5_REQUIRED" if terminal is None else "TERMINAL_RESOLVED",
        "incomplete": terminal is None,
        "terminal": terminal,
    }
    return document, campaign


def main() -> int:
    document, campaign = reduce_terminal()
    cache_evidence = cache_mechanism.evidence_document()
    documents = {**campaign, "terminal-reduction.json": document, "rpc-cache-mechanism.json": cache_evidence}
    write_evidence(documents)
    print(json.dumps({"terminal": document["terminal"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
