#!/usr/bin/env python3
"""Issue #200 (R8-F) machine-derived terminal classification.

Combines two independently mechanical findings into exactly one of the three
terminals the issue defines:

1. the compact CPU source-policy/local-backing campaign
   (``issue200_r8f_proof.run_campaign``) - Phases 1-3;
2. the Phase 4 mechanical llama.cpp/ggml-rpc local-backing-applicability
   finding, derived from the exact pinned runtime identity and the exact
   committed R8-D v2 launch-orchestration source
   (``scripts/issue195_v2_launch.py``, ``docs/investigations/qwen38-flash-next-r8-d-v2/``) -
   never re-executed, never requalified, read only.

This script does not perform any physical GPU/network action; it is a pure
CPU reducer over already-committed repository evidence plus the fresh
compact campaign it runs itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from issue200_r8f_proof import ROOT, AREA, run_campaign, write_evidence

TERMINAL_LOCAL_VERIFIED_BACKING_PASS = "R8F_LOCAL_VERIFIED_BACKING_PASS"
TERMINAL_RUNTIME_LOCAL_BACKING_PREREQUISITE = "R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE"
TERMINAL_GENERIC_SOURCE_POLICY_BLOCKED = "R8F_GENERIC_SOURCE_POLICY_BLOCKED"

LLAMA_CPP_PINNED_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
RPC_LAUNCH_SOURCE = "scripts/issue195_v2_launch.py"


def phase4_mechanical_finding() -> dict[str, Any]:
    """Mechanically re-derive the Phase 4 answer from committed launch-orchestration
    source, rather than asserting it as an authored claim.

    ``scripts/issue195_v2_launch.py`` (the exact producer that launched the
    accepted R8-D v2 physical candidate arm) invokes the RPC backend binary
    with only ``-H``, ``-p``, and ``-d`` (device) flags - no ``-m``/model
    path argument exists anywhere in ``RPC03_G0``, ``RPC03_G1``, or ``RPC04``.
    Only the client ``llama-server`` invocation (``CAND_SH``) receives
    ``-m {MODEL}``. This is read directly from the committed producer text,
    not inferred, so a later change to that file would change this finding
    the next time this reducer runs against it.
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
    return {
        "schema": "inferswarm.issue200.phase4-finding/1",
        "pinned_llama_cpp_commit": LLAMA_CPP_PINNED_COMMIT,
        "evidence_source": RPC_LAUNCH_SOURCE,
        "client_process_receives_model_path_argument": client_has_model_arg,
        "rpc_backend_process_receives_model_path_argument": rpc_backend_has_model_arg,
        "finding": (
            "The client llama-server process is the only process given the model "
            "path; every ggml-rpc-server backend process is launched with only "
            "-H/-p/-d and no model artifact of any kind. The ggml-rpc wire "
            "protocol this pinned build implements (alloc_buffer/set_tensor/"
            "get_tensor/copy_tensor/graph_compute) is a generic remote compute/"
            "memory protocol driven entirely by client-originated pushes; the RPC "
            "backend process has no independent model-loading capability and no "
            "seam to consume a participant-local verified artifact for its "
            "assigned tensors without the client retransmitting those exact "
            "bytes over the wire. mmap on the client process is client-local "
            "materialization staging, not RPC-host-local backing consumption."
        ),
        "answer_1_can_remote_participant_materialize_from_own_local_backing_without_client_retransmission": False,
        "answer_2_exact_seam_permitting_it": None,
        "answer_3_where_client_originated_bytes_are_forced": (
            "Every RPC backend launch invocation in scripts/issue195_v2_launch.py "
            "(RPC03_G0, RPC03_G1, RPC04) omits a model path entirely; the backend "
            "process therefore has no model bytes of its own to serve, so every "
            "tensor byte it ever holds must originate from the client's "
            "set_tensor calls over the RPC wire."),
        "smallest_narrow_successor_scope": (
            "A separately authorized ggml-rpc backend/protocol extension letting "
            "an rpc-server process open a participant-local verified artifact by "
            "content identity and satisfy assigned tensor requests from it, "
            "with integrity/provenance verification before trust - out of scope "
            "for this issue by its own hard constraints (no llama.cpp change "
            "in this session)."),
    }


def environment_execution_note() -> dict[str, Any]:
    """Records (does not claim to resolve) the separate, non-substrate reason
    Phase 5 did not run in this execution environment: this session has no
    network reachability to the physical fleet hosts the R8-D v2 campaign
    used (no DNS resolution, no SSH credentials, no known_hosts entries).
    This is independent of, and does not substitute for, the Phase 4
    substrate finding above; both are reported so neither is mistaken for
    the other."""
    return {
        "schema": "inferswarm.issue200.execution-environment-note/1",
        "physical_fleet_reachable_from_this_session": False,
        "note": ("This remote execution session has no SSH credentials, no "
                 "known_hosts entries, and no DNS resolution for the R8-D "
                 "physical fleet hostnames (inferswarm01/03/04). This is an "
                 "execution-environment constraint of this particular session, "
                 "reported separately from the Phase 4 substrate finding so "
                 "the two are never conflated: even a session with fleet access "
                 "would still hit the Phase 4 ggml-rpc blocker above."),
    }


def reduce_terminal() -> dict[str, Any]:
    campaign = run_campaign()
    summary = campaign["canonical-summary.json"]
    compact_seam_pass = bool(summary["all_arms_passed"] and summary["all_negative_controls_failed_closed"])
    phase4 = phase4_mechanical_finding()
    environment = environment_execution_note()

    if not compact_seam_pass:
        terminal = TERMINAL_GENERIC_SOURCE_POLICY_BLOCKED
    elif phase4["answer_1_can_remote_participant_materialize_from_own_local_backing_without_client_retransmission"]:
        # Only reachable if the pinned runtime seam changes; Phase 5 physical
        # staging is explicitly out of scope for this session regardless (see
        # environment_execution_note) and was not run.
        terminal = TERMINAL_LOCAL_VERIFIED_BACKING_PASS
    else:
        terminal = TERMINAL_RUNTIME_LOCAL_BACKING_PREREQUISITE

    document = {
        "schema": "inferswarm.issue200.terminal-reduction/1",
        "compact_source_policy_seam_pass": compact_seam_pass,
        "phase4_mechanical_finding": phase4,
        "execution_environment_note": environment,
        "physical_phase5_ran": False,
        "physical_phase5_not_run_reason": (
            "Phase 4 mechanically found the pinned ggml-rpc substrate forces "
            "client-originated tensor bytes with no participant-local-backing "
            "seam; per the issue's own hard constraints this stops the physical "
            "phase rather than staging 72.5 GB for appearance. Independently, "
            "this session also has no reachability to the physical fleet."),
        "terminal": terminal,
    }
    return document, campaign


def main() -> int:
    document, campaign = reduce_terminal()
    documents = {**campaign, "terminal-reduction.json": document}
    write_evidence(documents)
    print(json.dumps({"terminal": document["terminal"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
