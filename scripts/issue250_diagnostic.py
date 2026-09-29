#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — DIAGNOSTIC-ONLY runtime-boundary tooling spine.

Option-1 follow-up to the accepted Issue #248 terminal
R8I3_REF_NONDETERMINISM_UNRESOLVED. Goal (Issue #250 §Investigation):
localize the smallest mechanically demonstrated runtime/execution
factor required for the case-3072 fresh-process first-row
nondeterminism, WITHOUT changing model bytes, prompt/request
semantics, or the comparator acceptance law.

Nothing here reopens #241/#248 terminals, retries qualification,
implements a tolerance/noise model, or executes anything physical.

Machine-enforced boundaries (mirroring the accepted #248 authority
model, adapted to #250; tested in test_issue250_diagnostic.py):

  * Diagnostic namespaces are exactly ``d250-<label>``; campaign,
    phase, qualification, and predictive (c237-) namespaces are
    refused lexically — including the #248 diagnostic namespaces, so
    an #248 dispatch can never authorize #250 execution.
  * Every namespace is EXACTLY BOUND to its discriminator arm
    (correction pass 2, blocker 5): ``d250-arm-a`` <-> Arm A
    ``A-vulkan-necessity``, ``d250-arm-b`` <-> ``B-process-init``,
    ``d250-arm-c`` <-> ``C-cpu-threads``, ``d250-arm-d`` <->
    ``D-context-transition``. A dispatch comment pairing a valid
    namespace with any other (or unknown) arm is a protocol error.
  * No physical entrypoint runs without a MAINTAINER DISPATCH
    AUTHORITY revalidated LIVE immediately before every unit: an
    OWNER/MEMBER top-level comment on PR #(this PR) carrying the
    dispatch phrase + ``head=<sha>`` + ``diagnostic-namespace=<d250-…>``
    + ``arm=<frozen arm>`` as exact stripped lines, plus live
    OPEN/unmerged PR state and OPEN issue state. There is no
    production path that accepts a cached authority (the runner takes
    no authority parameter).
  * Every discriminator arm runs at the EXACT accepted subject
    semantics except the ONE declared factor: same accepted binaries,
    same three-member model set (campaign attestation + per-unit
    stat witness), same fixture ladder (sha-verified), same
    BYTE-EXACT accepted request contract (extras rejected), same
    identity discipline (fresh raw observations pre AND post).
  * CPU-only causal geometry (correction pass 2, blocker 2): Arm A
    establishes whether Vulkan participation is necessary. If the
    true CPU-only ``-dev none`` condition still varies, Arms B and C
    CONTINUE from that same CPU-only condition (B: fresh CPU-only
    processes vs equivalent same-process CPU-only repeats; C: default
    CPU threading vs ``-t 1 -tb 1`` serial CPU regime). No Vulkan
    device backend is reintroduced in B or C. Arm D (only reached
    when A-C do not localize) runs at the ACCEPTED placement because
    its factor is the prompt length, not the backend.
  * Arm-A nonzero-Vulkan contrast (correction pass 2, blocker 3) is
    the ACCEPTED #248 retained ``ngl=1`` case-3072 result, consumed
    as READ-ONLY contrast authority with digest/provenance
    verification (CONTRAST_* constants). It is never represented as
    fresh #250 execution, and no fresh ngl-based comparator units
    are planned. No ``ngl=8`` accepted-condition reproduction exists
    anywhere in Issue #250.
  * case-4096 never executes (out of scope for #250; refused
    outright, no preauthorization path exists in this module).
  * Determinism is judged ONLY on independently computed digests of
    rows/tokens; timing is metadata.
  * Retained bytes are append-only with ``-quarantined`` siblings.
  * The terminal is derived MECHANICALLY by the offline
    retained-byte reducer (scripts/issue250_physical.py
    ``derive_terminal``) directly from the retained evidence tree;
    this module exports NO caller-supplied-boolean terminal path and
    no terminal may be selected by hand. Missing or ambiguous
    evidence fails closed to R8I3B_REDUCER_BLOCKED_INCOMPLETE.

Correction pass 3 (maintainer NO-GO comment 5847890177) freezes:

  * the FROZEN PREFIX POPULATION LAW (``prefix_population_facts``):
    a nondeterministic verdict needs only the contiguous retained
    prefix that contains the first independently verified row-digest
    mismatch (execution must have STOPPED at that mismatch); the
    unexecuted planned tail is not missing evidence. A deterministic
    claim needs the full predeclared deterministic population (5
    identical where the arm freezes 5). Populations with gaps,
    cherry-picked subsets, or execution past the declared stop point
    are invalid and fail closed.
  * the Arm-D screening/confirmation geometry: 2 screening repeats
    per predeclared length establish only ``pair_identical``
    observations; a D LOCALIZED claim additionally requires the
    frozen deterministic-confirmation count (5 identical repeats)
    for the exact boundary-adjacent deterministic length, obtained
    under the predeclared adaptive extension rule (extend ONLY that
    condition; first mismatch at any point establishes variability
    immediately).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any

# --- accepted authority bindings (read-only) ------------------------------
ACCEPTED_MAIN_HEAD = "bc71774dc68e7d7fddaf97bd794bbbc297e66ca5"
ACCEPTED_248_RESULT_HEAD = (
    "a2cf9f33d1a056f2eef062b4186c078262e66f63")
ACCEPTED_248_TERMINAL = "R8I3_REF_NONDETERMINISM_UNRESOLVED"
ACCEPTED_241_TERMINAL = "R8I3_COMPARATOR_V2_BLOCKED"
ACCEPTED_248_EVIDENCE_ROOT = "inferswarm01:/home/hermes/is248-campaign/evidence/"
ACCEPTED_248_MANIFEST_SELF_DIGEST = (
    "af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc")

DIAGNOSTIC_ISSUE = 250
DIAGNOSTIC_PR_NUMBER = 251  # bound post-creation; verified live 2026-09-25
DIAGNOSTIC_KIND = "R8-I3B"

# Dispatch phrase prefix — the exact phrase is matched as an exact
# stripped comment line; never spelled in report prose.
DIAGNOSTIC_DISPATCH_PHRASE_PREFIX = "R8I3B PHYSICAL DISPATCH"
DIAGNOSTIC_DISPATCH_PHRASE = (
    f"{DIAGNOSTIC_DISPATCH_PHRASE_PREFIX} #{DIAGNOSTIC_ISSUE}")

# Issue #250 terminal vocabulary (exact, frozen).
TERMINALS = (
    "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED",
    "R8I3B_REFERENCE_RUNTIME_UNRESOLVED",
)
REDUCER_BLOCKED = "R8I3B_REDUCER_BLOCKED_INCOMPLETE"

# llama.cpp pin + accepted binaries (phase-0 verified).
LLAMA_PIN = "b29c606e28a01b1bc8c1351026a0fae616bf6c4"
SERVER_BINARIES = {
    "canonical": "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e",
    "r8e-obs": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
    "comparator": "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad",
}

# Model authority — accepted #241 three-member set.
MODEL_DIR = "/srv/models/qwen38-ud-iq1-s"
MODEL_MEMBERS = (
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf",
)
MODEL_MEMBER_SHA256 = {
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf":
        "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf":
        "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf":
        "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
}
MODEL_MEMBER_1 = MODEL_MEMBERS[0]

# Fixture ladder (accepted historical excluded fixtures).
FIXTURE_LADDER_REL = (
    "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/"
    "fixture-ladder.json")
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db")
N_VOCAB = 248320
ROW_BYTES = N_VOCAB * 4
DECISIONS = 8
CANONICAL_PACK = struct.Struct("<8I")

# BYTE-EXACT accepted #241 request contract.
REQUEST_CONTRACT = {
    "cache_prompt": False,
    "n_predict": 8,
    "return_tokens": True,
    "samplers": ["top_k"],
    "seed": 0,
    "stream": False,
    "temperature": 0.0,
    "top_k": 1,
}
REQUEST_CONTRACT_KEYS = frozenset(REQUEST_CONTRACT)

# ---------------------------------------------------------------------------
# Arm-A nonzero-Vulkan contrast authority (correction pass 2, blocker 3).
#
# FROZEN RULE (the preferred option; no fresh ngl reproduction is
# planned anywhere in Issue #250): the nonzero-Vulkan side of the
# Arm-A contrast is the ACCEPTED #248 retained ngl=1 case-3072
# placement result, consumed as READ-ONLY contrast authority. Its
# two retained fresh-process units carry byte-distinct full rows at
# every decision (row nondeterminism), while sharing identical
# tokens. Verification is mechanical (see issue250_physical.
# verify_historical_contrast): every consumed file digest must match
# a row of the accepted #248 SHA256SUMS manifest whose own bytes
# hash to the accepted self-digest, the unit receipts must bind the
# accepted #248 result head + placement namespace + the dispatch
# comment that authorized them, and row digests are recomputed from
# the retained row bytes — the contrast is DERIVED, never asserted.
# The historical fact this frozen rule consumes: at ngl=1 (minimal
# nonzero Vulkan participation; the output layer alone offloaded),
# the retained case-3072 rows VARY across fresh processes.
# ---------------------------------------------------------------------------
CONTRAST_PROVENANCE = "accepted_248_retained_ngl1_readonly"
CONTRAST_NAMESPACE = "d248-placement-rungs"
CONTRAST_CASE = "case-3072"
CONTRAST_UNITS = (
    "case-3072-B-ngl1-001",
    "case-3072-B-ngl1-002",
)
CONTRAST_NGL = 1
CONTRAST_EXPECTED_ROW_DETERMINISTIC = False
CONTRAST_MIN_UNITS = 2

# Issue #250 V0 is a diagnostic reachability gate, never a terminal.
# The input contract is deliberately exact: records bind all frozen
# workload/placement identity and retain the complete decision-0 row.
V0_SCHEMA = "inferswarm.issue250.v0-screen/1"
V0_NAMESPACE = "d250-arm-v0-amd"  # shared with physical producer
V0_ARM = "V0-amd-vulkan-concordance"
V0_UNIT_TAGS = tuple(f"case-3072-V0-amd-vulkan-{i:03d}" for i in range(1, 4))
V0_NVIDIA_ROW0_SHA256 = (
    "dff2499b64045f68d1349a363ee5bc888f3f9640c658252778d106fe80715499",
    "e369c8cb4ec5145f5ff855c0e29a1566795549126a4e135aaff5e94e8ce78ee6",
)
V0_STATE_AMD_VARIABLE = "AMD_VARIABLE_A_ELIGIBLE_DISPATCH_REQUIRED"
V0_STATE_IDENTICAL_PAIR_NEEDS_THIRD = "AMD_IDENTICAL_PAIR_THIRD_REQUIRED"
V0_STATE_CONCORDANCE_STOP = "CROSS_VENDOR_CONCORDANCE_STOP_BLOCKED"
V0_STATE_DISAGREEMENT_STOP = "CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED"
V0_STATE_INVALID = "V0_INVALID_BLOCKED"
V0_ROW_SLOT = 0

# ---------------------------------------------------------------------------
# Issue #250 V0n — prospective current-window NVIDIA RTX 3060 Vulkan
# screen (METHODOLOGY-AMENDMENT-007). Follows the COMPLETED V0 AMD screen
# (CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED under dispatch 5868617068 at
# head c5cc132..., evidence root evidence-v0-c5cc132): three fresh-process
# AMD/RADV repeats were byte-identical yet differed from BOTH retained
# #248 NVIDIA Vulkan ngl=1 rows. V0n answers, before any CPU Arm A
# spend, whether a CURRENT freshly dispatched NVIDIA Vulkan condition
# is (a) still fresh-process variable, (b) repeat-stable and different
# from the AMD current-window row, (c) repeat-stable and byte-equal to
# the AMD current-window row, or (d) reproduces retained #248 rows.
# It decides NO vendor's numerical authority, emits NO Issue #250
# terminal, and grants NO Arm A eligibility.
# ---------------------------------------------------------------------------
V0N_SCHEMA = "inferswarm.issue250.v0n-screen/1"
V0N_NAMESPACE = "d250-arm-v0n-nvidia"  # shared with physical producer
V0N_ARM = "V0n-nvidia-vulkan-current"
V0N_UNIT_TAGS = tuple(f"case-3072-V0n-nvidia-vulkan-{i:03d}"
                      for i in range(1, 4))
# The AMD current-window comparison row: the decision-0 row digest shared
# by all three retained fresh-process repeats of the completed V0 screen
# (read-only comparison input; the physical bytes remain retained under
# the completed AMD evidence root, which no V0n execution may touch).
V0N_AMD_CURRENT_ROW0_SHA256 = (
    "2187ab8f444e726b9a34d9874499603446a23efdd7943e8330286e223938fb41")
V0N_STATE_NVIDIA_VARIABLE_STOP = "CURRENT_NVIDIA_VARIABLE_STOP"
V0N_STATE_IDENTICAL_PAIR_NEEDS_THIRD = "V0N_IDENTICAL_PAIR_THIRD_REQUIRED"
V0N_STATE_CONCORDANCE_STOP = "CURRENT_CROSS_VENDOR_CONCORDANCE_STOP"
V0N_STATE_STABLE_DISAGREEMENT_STOP = (
    "CURRENT_CROSS_VENDOR_STABLE_DISAGREEMENT_STOP")
V0N_STATE_INVALID = "CURRENT_NVIDIA_INVALID_BLOCKED"

# ---------------------------------------------------------------------------
# METHODOLOGY-AMENDMENT-008: post-V0n maintainer-adjudicated Arm-A
# reachability bridge. V0/V0n semantics are FROZEN (no state, digest,
# `terminal` or `a_eligible` field changes): the accepted V0 result is
# the stable cross-vendor disagreement stop, V0n returned
# CURRENT_NVIDIA_VARIABLE_STOP with a_eligible=False, so the historical
# `_require_v0_fallback` gate (`a_eligible=True` required) can never
# open Arm A again and the combination leaves no mechanically defined
# path to the already-frozen CPU discriminator. This record is the ONE
# prospective exception: a maintainer-adjudicated, cryptographically
# self-authenticating bridge between the append-only physical evidence
# roots that a future Arm-A producer must authenticate from bytes —
# never from caller assertions or GitHub prose. Eligibility is NOT
# execution authority: the exact `d250-arm-a` / `A-vulkan-necessity`
# namespace/arm plus a NEW exact-head dispatch remain mandatory, and
# B/C/C1/C2/D stay unreachable from this record.
# ---------------------------------------------------------------------------
ARM_A_BRIDGE_SCHEMA = "inferswarm.issue250.arm-a-bridge/1"
ARM_A_BRIDGE_NAME = "arm-a-reachability-bridge.json"
# The accepted V0 AMD V0 dispatch (comment 5868617068, head c5cc132…)
# is COMPLETED and its comment ID is hard-refused by the V0n and Arm-A
# dispatch validators — the bridge binds its digests as evidence
# identity, never as authority.
ARM_A_BRIDGE_STALE_DISPATCH_COMMENT_IDS = frozenset({5868617068})
# The exact accepted result identities this bridge consumes. The
# bridge is mechanically invalid for any other combination.
ARM_A_BRIDGE_V0_DISPATCH_DIGEST_SHA256 = (
    "99cb573c473d677ffa76adbc8486f494f10a51091e0257e33c84f2eadd2da2fa")
ARM_A_BRIDGE_V0_STABLE_ROW_SHA256 = (
    "2187ab8f444e726b9a34d9874499603446a23efdd7943e8330286e223938fb41")
ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256 = (
    "4aa0aa0b216105d0c611652b100d53f4a5aed46be8f4013a6c15d1acd43dd776")
ARM_A_BRIDGE_V0N_FREEZE_SHA256 = (
    "3fe9e74dece02e4e892daec2f6510df6a670905d6ee5a83fea61bc1f2a7e9207")
ARM_A_BRIDGE_V0N_ROW_SHA256 = (
    "6c295c671a794ebd2d6b5d644900fd87eb3430c69226954db0870146822aae53",
    "3d6b599d15004d7ad0b4402784b64eec369434724c9dc13e16f23531de975d6b")
# The exact accepted physical execution heads the bridge consumes.
ACCEPTED_V0_EXECUTED_HEAD = "c5cc132762c51a3352014f36553eff6d0d26b112"


def _v0n_row_class(digest: str, amd_sha: str,
                   retained: tuple[str, ...]) -> dict[str, Any]:
    """Per-row novel/equality facts; never a validity or authority fact."""
    return {"row_sha256": digest,
            "equals_amd_current": digest == amd_sha,
            "equals_retained_nvidia_index": (
                retained.index(digest) if digest in retained else None),
            "novel": digest != amd_sha and digest not in retained}


def reduce_v0n_screen(nvidia_rows: list[bytes],
                      amd_current_sha: str,
                      retained_nvidia_shas: tuple[str, ...]
                      ) -> dict[str, Any]:
    """Pure full-byte current-window NVIDIA comparison (AMENDMENT-007).

    Predeclared interpretation law (never a terminal, never A-eligibility):

    * first two full rows differ -> CURRENT_NVIDIA_VARIABLE_STOP (the
      screen STOPS; per-row equality with the AMD current row and the
      retained #248 rows is REPORTED, never interpreted as cause);
    * first two identical, only two retained -> third required;
    * three identical and equal to the AMD current-window row ->
      CURRENT_CROSS_VENDOR_CONCORDANCE_STOP (stronger current-window
      concordance; #248 remains historical evidence of prior NVIDIA
      variability; maintainer reconciliation of changed runtime state);
    * three identical and different from the AMD row ->
      CURRENT_CROSS_VENDOR_STABLE_DISAGREEMENT_STOP (no vendor judged);
    * a third row executed after a mismatched first pair, or any
      unverified/incomplete population -> V0N_INVALID_BLOCKED.

    A variable population stays VARIABLE_STOP even when one of its rows
    happens to equal the AMD row or a retained #248 row.
    """
    invalid = {"state": V0N_STATE_INVALID, "valid": False,
               "terminal": None, "a_eligible": False}
    if (type(nvidia_rows) is not list or len(nvidia_rows) not in (2, 3)
            or any(type(row) is not bytes or len(row) != ROW_BYTES
                   for row in nvidia_rows)
            or amd_current_sha != V0N_AMD_CURRENT_ROW0_SHA256
            or retained_nvidia_shas != V0_NVIDIA_ROW0_SHA256):
        return dict(invalid, reason="unverified or incomplete full-row population")
    rows = [row_digest(row) for row in nvidia_rows]
    if rows[0] != rows[1]:
        if len(rows) != 2:
            return dict(invalid, reason="third row executed after first mismatch")
        return {"state": V0N_STATE_NVIDIA_VARIABLE_STOP, "valid": True,
                "terminal": None, "a_eligible": False,
                "maintainer_stop": True, "nvidia_rows": rows,
                "row_classes": [_v0n_row_class(r, amd_current_sha,
                                               retained_nvidia_shas)
                                for r in rows]}
    if len(rows) == 2:
        return {"state": V0N_STATE_IDENTICAL_PAIR_NEEDS_THIRD,
                "valid": True, "terminal": None, "a_eligible": False,
                "third_required": True, "nvidia_rows": rows}
    if rows[2] != rows[0]:
        return {"state": V0N_STATE_NVIDIA_VARIABLE_STOP, "valid": True,
                "terminal": None, "a_eligible": False,
                "maintainer_stop": True, "nvidia_rows": rows,
                "row_classes": [_v0n_row_class(r, amd_current_sha,
                                               retained_nvidia_shas)
                                for r in rows]}
    matched_amd = rows[0] == amd_current_sha
    matched_retained = rows[0] in retained_nvidia_shas
    return {"state": (V0N_STATE_CONCORDANCE_STOP if matched_amd else
                      V0N_STATE_STABLE_DISAGREEMENT_STOP),
            "valid": True, "terminal": None, "a_eligible": False,
            "maintainer_stop": True, "nvidia_rows": rows,
            "matched_amd_current": matched_amd,
            "matched_retained_nvidia": matched_retained}


def reduce_v0_screen(amd_rows: list[bytes],
                     nvidia_rows: tuple[str, str]) -> dict[str, Any]:
    """Pure full-byte comparison AFTER terminal's custody/provenance checks.

    This function is not an evidence verifier and cannot authorize A. The
    terminal reducer alone reads retained files and grants reachability.
    """
    invalid = {"state": V0_STATE_INVALID, "valid": False,
               "terminal": None, "a_eligible": False}
    if (type(amd_rows) is not list or len(amd_rows) not in (2, 3)
            or any(type(row) is not bytes or len(row) != ROW_BYTES
                   for row in amd_rows)
            or nvidia_rows != V0_NVIDIA_ROW0_SHA256):
        return dict(invalid, reason="unverified or incomplete full-row population")
    rows = [row_digest(row) for row in amd_rows]
    if rows[0] != rows[1]:
        if len(rows) != 2:
            return dict(invalid, reason="third row executed after first mismatch")
        return {"state": V0_STATE_AMD_VARIABLE, "valid": True,
                "terminal": None, "a_eligible": True,
                "dispatch_required": True, "amd_rows": rows}
    if len(rows) == 2:
        return {"state": V0_STATE_IDENTICAL_PAIR_NEEDS_THIRD,
                "valid": True, "terminal": None, "a_eligible": False,
                "third_required": True, "amd_rows": rows}
    if rows[2] != rows[0]:
        return {"state": V0_STATE_AMD_VARIABLE, "valid": True,
                "terminal": None, "a_eligible": True,
                "dispatch_required": True, "amd_rows": rows}
    matched = rows[0] in nvidia_rows
    return {"state": (V0_STATE_CONCORDANCE_STOP if matched else
                      V0_STATE_DISAGREEMENT_STOP), "valid": True,
            "terminal": None, "a_eligible": False, "maintainer_stop": True,
            "amd_rows": rows, "matched_retained_nvidia": matched}

# Frozen discriminator geometry (Issue #250 §A–§D; correction pass 2
# blockers 2+3: B and C continue from Arm A's CPU-only condition).
CASE = "case-3072"
ACCEPTED_MATCHED_NGL = 8      # Arm D ladder placement only (length factor)
MIN_REPEATS = 3
DETERM_MIN_REPEATS = 5        # deterministic claim requires 5 identical
ARM_A2_DEV_NONE_ARGV_DELTA = ("-dev", "none")
ARM_B_DEV_NONE_ARGV_DELTA = ("-dev", "none")
ARM_C_DEV_NONE_ARGV_DELTA = ("-dev", "none")
ARM_C_SERIAL_ARGV_DELTA = ("-t", "1", "-tb", "1")
ARM_D_LADDER_LENGTHS = (1024, 1536, 2048, 2304, 2560, 3072)
ARM_D_SCREEN_REPEATS = 2    # screening pair per length (correction pass 3)
ARM_D_CONFIRM_REPEATS = 5   # deterministic-confirmation count (5 identical)

# Arm D ladder derivation rule (predeclared; Issue #250 §D: same
# accepted fixture derivation rule — repeated sentence block with the
# identical prologue/suffix). CORRECTION PASS 3 (NO-GO 5847890177,
# blocker 4A): the ladder labels are TEXT GENERATION PARAMETERS
# (sentence-repeat counts), NOT assumed token lengths. The actual
# token count of every predeclared prompt is derived before physical
# Arm-D execution through the pinned-server tokenizer authority
# (POST /tokenize, add_special=true — the exact tokenize call the
# pinned /completion path itself makes at server-context.cpp:4579)
# and retained per unit; the reducer uses the ACTUAL count for any
# token-count mechanism (e.g. indexer top_k), never the nominal
# label. Accepted fixtures already demonstrate label!=count
# (case-1024 => 1022 tokens; case-3072 => 3077 tokens).
ARM_D_LADDER_SENTENCE_REPEATS = {
    1024: 68, 1536: 102, 2048: 136, 2304: 153, 2560: 171, 3072: 204,
}

# Model-architecture token-count mechanism boundary (phase0
# MODEL_ARCH_FACTS "qwen4exp.attention.indexer.top_k"). CORRECTION
# PASS 4 (NO-GO 5851078451, blocker 3): the pinned-source audit
# (950999fe src/models/qwen4exp.cpp build_qsa_top_k) proves the
# actual execution-path transition is NOT at the bare metadata
# constant — it is at the top-k SELECTION WIDTH:
#   width = std::min<int64_t>(n_kv, indexer_top_k + r - 1)
# where r is the per-layer compress ratio (4 for every QSA layer of
# this model: GGUF qwen4exp.attention.compress_ratios).
# CORRECTION PASS 5 (NO-GO 5852014883): the sides of that law are
# EXACT AT EQUALITY. width = min(n_kv, 2051) equals n_kv for every
# population THROUGH 2051 cells, so the top-k selection still
# covers EVERY KV cell there (ggml_top_k with k == n_kv: the
# selected-cell mask unmasks everything — dense attention,
# numerics identical to no selection): that is the ALL-CELLS side,
# n_kv <= 2051. Only from 2052 cells on is the capped width
# smaller than the population (min(2052, 2051) = 2051 < 2052), so
# the top-k tensor actively shapes the KQ mask via ggml_set_rows
# (unmasking only the selected cells) in the 12 QSA layers: that
# is the SELECTIVE side, n_kv >= 2052. The selective transition is
# never encoded as ">= 2051" anywhere. For the single-sequence
# frozen launch shape the KV-cell count at the decision-0 row
# equals the retained actual prompt token count.
INDEXER_TOP_K = 2048
INDEXER_COMPRESS_RATIO = 4
# Source-law selection-width cap: width = min(n_kv, 2051).
INDEXER_TOPK_WIDTH = INDEXER_TOP_K + INDEXER_COMPRESS_RATIO - 1  # 2051
# Explicit execution-boundary pair derived from the source law.
# All-cells / dense-equivalent side: n_kv <= 2051.
INDEXER_ALL_CELLS_MAX = INDEXER_TOPK_WIDTH  # 2051
# First population where the selection can exclude a cell.
INDEXER_SELECTIVE_MIN = INDEXER_ALL_CELLS_MAX + 1  # 2052

# Same-process (Arm B) request-contract extension: id_slot pinning is
# required to make repeated requests land on the SAME slot. The
# accepted contract has no id_slot key; the frozen diagnostic contract
# for Arm B same-process requests is the accepted contract + id_slot:3,
# and this extension is DECLARED in METHODOLOGY (maintainer-reviewed)
# rather than silent.
ARM_B_CONTRACT = dict(REQUEST_CONTRACT)
ARM_B_CONTRACT["id_slot"] = 3
ARM_B_EXTRA_KEYS = frozenset({"id_slot"})
ARM_B_ID_SLOT = 3

# ---------------------------------------------------------------------------
# Namespace <-> arm exact binding (correction pass 2, blocker 5)
#
# METHODOLOGY-AMENDMENT-003 (correction pass 6): Arm C is split.
# ``d250-arm-c`` now authorizes ONLY the default-thread reproduction
# pair + the bounded C1 reduced-parallelism probe (`-t 4 -tb 4`).
# The serial `-t 1 -tb 1` regime (C2) is NOT auto-reachable: its
# dedicated namespace ``d250-arm-c2`` is NOT part of
# NAMESPACE_ARM_BINDING, so no generic Arm-C dispatch (and no C1
# dispatch) can ever authorize serial execution — a C2 run requires
# its own exact-head ``d250-arm-c2`` maintainer dispatch comment,
# validated separately by validate_c2_dispatch_payload.
# ---------------------------------------------------------------------------
NAMESPACE_ARM_BINDING = {
    "d250-arm-a": "A-vulkan-necessity",
    "d250-arm-b": "B-process-init",
    "d250-arm-c": "C-cpu-threads",
    "d250-arm-c1": "C1-reduced-parallelism",
    "d250-arm-d": "D-context-transition",
}
ARM_NAMESPACE_BINDING = {arm: ns for ns, arm in NAMESPACE_ARM_BINDING.items()}

# C1: the ONE predeclared bounded reduced-parallelism regime
# (AMENDMENT-003): substantially below the default 14 threads, frozen
# before any execution, everything else identical to the CPU-only
# condition (same -dev none base, same case-3072 prompt, same binary,
# same batch/ubatch, no affinity/NUMA/polling/priority changes).
ARM_C1_ARGV_DELTA = ("-t", "4", "-tb", "4")
# C2: the serial deep discriminator — frozen, but reachable ONLY
# through the dedicated d250-arm-c2 maintainer gate.
ARM_C2_ARGV_DELTA = ("-t", "1", "-tb", "1")
ARM_C2_NAME = "C2-serial"
C2_SERIAL_NAMESPACE = "d250-arm-c2"
# The legacy Arm-C namespace must never reach the serial regime: its
# frozen plan simply contains no serial units (see _arm_units), and
# validate_authority_payload refuses any arm= pairing outside
# NAMESPACE_ARM_BINDING — so an `arm=C2-serial` line can never be a
# valid d250-arm-c or d250-arm-c1 dispatch.

# Stale-dispatch discipline (AMENDMENT-003): the retained v1 failed
# run's dispatch comment binds the PRE-correction head. Once the
# correction commit moves PR HEAD, that dispatch MUST be stale — the
# producer enforces this mechanically (dispatch head == live PR head
# == local HEAD), and bind_stale_dispatch_record is the retained
# record used by the regression test.
STALE_DISPATCH_COMMENT_ID = 5852485456
STALE_DISPATCH_HEAD = "1c86e97da42401ff7cfa98e3dc48a33517c65def"


def bind_stale_dispatch_record(current_head: str) -> dict[str, Any]:
    """Fail-closed stale-dispatch binding record for the regression.

    Proves mechanically that dispatch comment 5852485456 binds head
    1c86e97... and CANNOT authorize any unit at a moved HEAD: the
    record's head differs from current_head, so the producer's
    exact-head authority law (dispatch head == PR head == local HEAD)
    rejects it. Same head returns stale=False (still valid there).
    """
    if not isinstance(current_head, str) or not re.fullmatch(
            r"[0-9a-f]{40}", current_head):
        raise DiagnosticError("current head is not a 40-hex sha")
    return {
        "comment_id": STALE_DISPATCH_COMMENT_ID,
        "bound_head": STALE_DISPATCH_HEAD,
        "current_head": current_head,
        "stale": current_head != STALE_DISPATCH_HEAD,
        "namespace": "d250-arm-a",
        "arm": "A-vulkan-necessity",
    }


class DiagnosticError(RuntimeError):
    """Raised when a diagnostic boundary is violated."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_request_digest(contract: dict[str, Any]) -> str:
    return sha256_bytes(
        json.dumps(contract, sort_keys=True, separators=(",", ":"))
        .encode())


# ---------------------------------------------------------------------------
# Namespace discipline
# ---------------------------------------------------------------------------

NAMESPACE_RE = re.compile(r"^d250-[a-z0-9][a-z0-9-]*[a-z0-9]$")
FORBIDDEN_NAMESPACE_SUBSTRINGS = (
    "c237-",        # predictive namespace (hard prohibition)
    "issue241",     # qualification campaign
    "issue248",     # sibling diagnostic (distinct authority line)
    "qualification",
    "campaign",
    "phase",
)


def validate_namespace(namespace: str) -> str:
    if not isinstance(namespace, str) or not NAMESPACE_RE.fullmatch(namespace):
        raise DiagnosticError(f"invalid diagnostic namespace: {namespace!r}")
    for bad in FORBIDDEN_NAMESPACE_SUBSTRINGS:
        if bad in namespace:
            raise DiagnosticError(
                f"forbidden namespace substring {bad!r} in {namespace!r}")
    return namespace


def namespace_dir(root: Path, namespace: str) -> Path:
    validate_namespace(namespace)
    return Path(root) / namespace


def _require_clean_head(repo_root: Path, expected_head: str) -> None:
    """HEAD must be exactly the authorized head with an empty worktree."""
    import subprocess
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True,
        text=True, check=True).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True,
        text=True, check=True).stdout
    if head != expected_head:
        raise DiagnosticError(
            f"HEAD drift: {head} != authorized {expected_head}")
    if status.strip():
        raise DiagnosticError("worktree is dirty; diagnostic requires clean")


def validate_namespace_arm_binding(namespace: str, arm: str) -> str:
    """Require the EXACT frozen namespace<->arm pair (fail-closed).

    Correction pass 2, blocker 5: a syntactically valid namespace
    paired with any arm other than its frozen partner is a protocol
    error, as is any unknown namespace or arm.
    """
    validate_namespace(namespace)
    if arm not in ARM_NAMESPACE_BINDING:
        raise DiagnosticError(f"unknown arm: {arm!r}")
    if namespace not in NAMESPACE_ARM_BINDING:
        raise DiagnosticError(
            f"namespace is not one of the four frozen arm namespaces: "
            f"{namespace!r}")
    expected = NAMESPACE_ARM_BINDING[namespace]
    if arm != expected:
        raise DiagnosticError(
            f"namespace/arm binding violation: {namespace!r} must pair "
            f"with arm {expected!r}, got {arm!r}")
    return arm


# ---------------------------------------------------------------------------
# Request-contract discipline
# ---------------------------------------------------------------------------

def validate_request_contract(contract: Any,
                              extra_keys: frozenset[str] = frozenset(),
                              ) -> dict[str, Any]:
    """Require exact equality with the frozen accepted contract.

    Arm B (same-process) permits exactly the declared ``id_slot``
    extension (METHODOLOGY-declared); any other extra key is rejected.
    """
    if not isinstance(contract, dict):
        raise DiagnosticError("request contract must be a dict")
    if not extra_keys <= ARM_B_EXTRA_KEYS:
        raise DiagnosticError(
            f"undisclosed contract extension keys: "
            f"{sorted(extra_keys - ARM_B_EXTRA_KEYS)}")
    keys = set(contract)
    extras = keys - REQUEST_CONTRACT_KEYS - extra_keys
    if extras:
        raise DiagnosticError(
            f"request contract carries extra semantic keys: {sorted(extras)}")
    missing = REQUEST_CONTRACT_KEYS - keys
    if missing:
        raise DiagnosticError(
            f"request contract is missing frozen keys: {sorted(missing)}")
    base = {k: contract[k] for k in REQUEST_CONTRACT_KEYS}
    if base != REQUEST_CONTRACT:
        differing = {k: (contract.get(k), REQUEST_CONTRACT[k])
                     for k in sorted(REQUEST_CONTRACT_KEYS)
                     if contract.get(k) != REQUEST_CONTRACT[k]}
        raise DiagnosticError(
            f"request contract differs from frozen accepted contract; "
            f"differences: {differing}")
    for k in extra_keys:
        if contract.get(k) != ARM_B_CONTRACT.get(k):
            raise DiagnosticError(
                f"declared extension key {k} carries a non-frozen value")
    return dict(contract)


# ---------------------------------------------------------------------------
# Dispatch-authority model (exact stripped-line OWNER/MEMBER comment)
# ---------------------------------------------------------------------------

AUTHORITY_DIGEST_FIELDS = (
    "comment_id", "issue_url", "author_association", "created_at",
    "head_sha", "namespace", "body",
)


def authority_digest(authority: dict[str, Any]) -> str:
    if not isinstance(authority, dict):
        raise DiagnosticError("authority must be a dict")
    doc: dict[str, Any] = {}
    for key in AUTHORITY_DIGEST_FIELDS:
        value = authority.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise DiagnosticError(
                f"authority digest field missing or malformed: {key}")
        doc[key] = value
    return sha256_bytes(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())


def bind_authority_observations(early: Any, late: Any) -> dict[str, Any]:
    """Two live fetches must bind to the identical dispatch comment."""
    if not isinstance(early, dict) or not isinstance(late, dict):
        raise DiagnosticError("authority observations must be objects")
    for key in AUTHORITY_DIGEST_FIELDS:
        if early.get(key) != late.get(key):
            raise DiagnosticError(
                f"live dispatch authority changed between observations: "
                f"{key}")
    if authority_digest(early) != authority_digest(late):
        raise DiagnosticError(
            "live dispatch authority digest changed between observations")
    return dict(late)


def validate_authority_payload(authority: dict[str, Any],
                               expected_head: str) -> dict[str, Any]:
    """Validate a fetched #250 dispatch authority (fail-closed)."""
    if not isinstance(authority, dict):
        raise DiagnosticError("authority must be a dict")
    for key in ("comment_id", "issue_url", "author_association",
                "created_at", "body", "head_sha"):
        if not authority.get(key):
            raise DiagnosticError(f"authority field missing: {key}")
    for key in ("open_pr", "issue_open"):
        if key not in authority:
            raise DiagnosticError(
                f"live authority state missing: {key}")
    if not authority["open_pr"]:
        raise DiagnosticError(
            f"PR #{DIAGNOSTIC_PR_NUMBER} is closed or merged")
    if not authority["issue_open"]:
        raise DiagnosticError(f"Issue #{DIAGNOSTIC_ISSUE} is closed")
    if authority["author_association"] not in ("OWNER", "MEMBER"):
        raise DiagnosticError(
            f"dispatch author is not OWNER/MEMBER: "
            f"{authority['author_association']!r}")
    issue_url = str(authority["issue_url"])
    if not issue_url.rstrip("/").endswith(
            f"/issues/{DIAGNOSTIC_PR_NUMBER}"):
        raise DiagnosticError(
            f"authority comment is not bound to PR "
            f"#{DIAGNOSTIC_PR_NUMBER}: {issue_url}")
    if str(authority["head_sha"]) != expected_head:
        raise DiagnosticError(
            f"dispatch head {authority['head_sha']} != expected "
            f"{expected_head}")
    lines = [ln.strip() for ln in str(authority["body"]).splitlines()]
    if DIAGNOSTIC_DISPATCH_PHRASE not in lines:
        raise DiagnosticError("dispatch phrase line absent")
    if f"head={expected_head}" not in lines:
        raise DiagnosticError(f"exact head line absent: head={expected_head}")
    namespaces = [ln.split("=", 1)[1] for ln in lines
                  if ln.startswith("diagnostic-namespace=")]
    if len(namespaces) != 1:
        raise DiagnosticError(
            f"exactly one diagnostic-namespace line required, found "
            f"{len(namespaces)}")
    namespace = namespaces[0]
    validate_namespace(namespace)
    if namespace != authority.get("namespace"):
        raise DiagnosticError("scope namespace mismatch inside authority")
    # #250 has NO case-4096 preauthorization path: any case-4096 line in
    # a #250 dispatch comment is a protocol error, not an authorization.
    case4096 = [ln for ln in lines if ln.startswith("case-4096:")]
    if case4096:
        raise DiagnosticError(
            "case-4096 is out of scope for Issue #250; a case-4096 line "
            "in a #250 dispatch is a protocol error")
    # Any arm other than the frozen arm vocabulary is refused, and the
    # arm must be EXACTLY the namespace's frozen partner (correction
    # pass 2, blocker 5).
    arms = [ln.split("=", 1)[1] for ln in lines
            if ln.startswith("arm=")]
    if len(arms) != 1 or arms[0] not in ARM_PLANS:
        raise DiagnosticError(
            f"exactly one frozen arm required (one of {sorted(ARM_PLANS)}), "
            f"found {arms}")
    if namespace != C2_SERIAL_NAMESPACE:
        # AMENDMENT-003 authority separation: a non-C2 namespace may
        # pair ONLY with an arm whose frozen namespace is exactly this
        # namespace (d250-arm-c cannot smuggle a C1-arm line; C1
        # cannot smuggle a default-C arm line; serial is not even in
        # the binding map). C2 is handled fully separately below.
        expected_ns = ARM_NAMESPACE_BINDING.get(arms[0])
        if expected_ns != namespace:
            raise DiagnosticError(
                f"namespace/arm binding violation: {namespace!r} cannot "
                f"pair with arm {arms[0]!r}")
    if namespace == C2_SERIAL_NAMESPACE:
        # SEPARATE MAINTAINER GATE (AMENDMENT-003): a d250-arm-c2
        # dispatch is valid ONLY for the serial arm, ONLY with the
        # explicit `c2-serial-gate:` subscope line, and ONLY after C1
        # has actually completed (deterministic OR variable; C1 gate
        # precondition). The four-frozen-arms pairing below would
        # reject this namespace, so C2 validation is fully separate.
        if arms[0] != ARM_C2_NAME:
            raise DiagnosticError(
                f"{C2_SERIAL_NAMESPACE} dispatch must bind arm "
                f"{ARM_C2_NAME!r}, got {arms[0]!r}")
        c2_gates = [ln for ln in lines
                    if ln.startswith("c2-serial-gate:")]
        if len(c2_gates) != 1 or c2_gates[0] != C2_GATE_REQUIRED_LINE:
            raise DiagnosticError(
                f"{C2_SERIAL_NAMESPACE} dispatch lacks the explicit "
                f"serial gate line {C2_GATE_REQUIRED_LINE!r}")
        # NOTE: the C1-completed gate RECORD precondition is verified
        # where the evidence root is known (c2_launch_allowed in the
        # producer); a dispatch comment alone cannot prove it.
        return dict(authority, namespace=namespace, arm=arms[0])
    validate_namespace_arm_binding(namespace, arms[0])
    return dict(authority, namespace=namespace, arm=arms[0])


# ---------------------------------------------------------------------------
# C2 SERIAL GATE (AMENDMENT-004 supersedes 003's C1-varied restriction).
# The serial `-t 1 -tb 1` deep
# discriminator is reachable ONLY through a dedicated d250-arm-c2
# exact-head maintainer dispatch, which is valid ONLY when:
#   (a) the comment carries the explicit subscope line
#       `c2-serial-gate: authorized-for-serial-deep-probe`; AND
#   (b) a frozen C1 gate record is retained at the evidence root
#       proving C1 COMPLETED (either deterministic or variable), signed by
#       BOTH the C1 dispatch authority digest and the C2 dispatch
#       authority digest, at the same head.
# The record format is frozen here; the reducer verifies it (a C2
# terminal contribution is consumed only when this gate closed).
# ---------------------------------------------------------------------------
C2_GATE_REQUIRED_LINE = "c2-serial-gate: authorized-for-serial-deep-probe"
C2_GATE_RECORD_NAME = "c1-completed-c2-gate.json"
C2_GATE_RECORD_SCHEMA = "inferswarm.issue250.c1-completed-c2-gate/1"


def c1_dispatch_c2_unlocked(evidence_root: str | Path | None = None,
                            expected_head: str | None = None,
                            c2_authority: dict[str, Any] | None = None,
                            c1_authority: dict[str, Any] | None = None,
                            c1_verdict: str | None = None,
                            ) -> bool:
    """Whether the frozen C1->C2 gate is mechanically unlocked.

    Fail-closed: with no gate record present (the default state after
    this correction), returns False — C2 stays unreachable, which is
    the post-correction default. When a record exists, every frozen
    record syntax, head and supplied authority digests are re-checked.
    Callers MUST independently derive C1 completion from retained rows and
    pass the resulting verdict and live C1 authority: this helper cannot
    infer either from a caller-written gate record alone.
    """
    if evidence_root is None:
        return False
    root = Path(evidence_root)
    path = root / C2_GATE_RECORD_NAME
    if path.is_symlink() or not path.is_file():
        return False
    try:
        record = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict) or record.get(
            "schema") != C2_GATE_RECORD_SCHEMA:
        return False
    if record.get("c1_authority_sha256") is None \
            or record.get("c2_authority_sha256") is None:
        return False
    if expected_head is not None and record.get("head_sha") != \
            expected_head:
        return False
    # A live C2 comment and a self-asserted gate file cannot prove C1.
    # Physical callers must derive the verdict from retained C1 rows and
    # fetch that namespace's live authority independently.
    if c2_authority is not None and (
            c1_authority is None or c1_verdict is None):
        return False
    if c2_authority is not None:
        try:
            if record.get("c2_authority_sha256") != authority_digest(
                    c2_authority):
                return False
        except DiagnosticError:
            return False
    if c1_authority is not None:
        try:
            if record.get("c1_authority_sha256") != authority_digest(
                    c1_authority):
                return False
        except DiagnosticError:
            return False
    if c1_verdict is not None and record.get("c1_verdict") != c1_verdict:
        return False
    return (record.get("c1_completed") is True
            and record.get("c1_verdict") in
            ("deterministic", "variable"))


# ---------------------------------------------------------------------------
# Frozen discriminator arm plans (Issue #250 §A–§D; correction pass 2:
# one-factor causal geometry, CPU-only inheritance for B and C)
# ---------------------------------------------------------------------------

def _arm_units(arm: str) -> list[dict[str, Any]]:
    """Predeclared unit geometry per arm (fresh process per unit unless
    the arm is same-process by definition)."""
    if arm == "A-vulkan-necessity":
        # Condition "cpu-only-devnone" only: the exact accepted
        # case-3072 workload with `-dev none` appended (the PROVEN true
        # CPU-only control). 3 repeats minimum; extend to 5 before a
        # deterministic claim. The nonzero-Vulkan side of the contrast
        # is the ACCEPTED #248 retained ngl=1 result (CONTRAST_*),
        # consumed read-only — no fresh comparator units are planned.
        return [{"tag": f"{CASE}-B-devnone-00{i}", "argv_delta":
                 ARM_A2_DEV_NONE_ARGV_DELTA, "ngl": 0,
                 "request": "accepted"}
                for i in (1, 2, 3, 4, 5)]
    if arm == "B-process-init":
        # Only reached when Arm A's CPU-only condition VARIES. Both
        # conditions inherit that same CPU-only `-dev none` condition;
        # the only conceptual factor changed is process/runtime
        # lifetime (correction pass 2, blocker 2).
        # Arm 1: independent fresh CPU-only processes (5 units).
        # Arm 2: ONE controlled CPU-only process, 5 sequential
        # equivalent requests (id_slot=3 pinned, cache_prompt=false
        # proven full reset), retained as one shared-process lifecycle
        # record — NOT five separate process units.
        return [
            {"tag": f"{CASE}-B-cpu-fresh-00{i}",
             "argv_delta": ARM_B_DEV_NONE_ARGV_DELTA, "ngl": 0,
             "request": "accepted"}
            for i in (1, 2, 3, 4, 5)
        ] + [
            {"tag": f"{CASE}-B-cpu-sameproc-00{i}",
             "argv_delta": ARM_B_DEV_NONE_ARGV_DELTA, "ngl": 0,
             "request": "arm-b", "same_process": True}
            for i in (1, 2, 3, 4, 5)
        ]
    if arm == "C-cpu-threads":
        # AMENDMENT-003 (correction pass 6): the d250-arm-c namespace
        # now authorizes ONLY the default-thread CPU-only reproduction
        # pair (the VARIATION side is already established by arms A/B
        # fresh CPU-only units at the same geometry). The OLD one-shot
        # serial design (`-t 1 -tb 1`, ~19,150 s prefill per unit —
        # ~5.3 h) is RETIRED from this namespace: it is not an
        # automatically executed discriminator anymore. The bounded
        # probe lives in the separate d250-arm-c1 namespace
        # (C1-reduced-parallelism); the serial regime in the gated
        # d250-arm-c2 namespace (C2-serial).
        return [
            {"tag": f"{CASE}-B-cpu-thr-default-00{i}",
             "argv_delta": ARM_C_DEV_NONE_ARGV_DELTA, "ngl": 0,
             "request": "accepted"}
            for i in (1, 2)
        ]
    if arm == "C1-reduced-parallelism":
        # AMENDMENT-003: the bounded C1 reduced-parallelism probe —
        # ONE predeclared intermediate regime (`-t 4 -tb 4`,
        # substantially below the default 14 threads, frozen BEFORE
        # any execution), everything else identical to the CPU-only
        # condition (-dev none, same case-3072 prompt, same binary,
        # same batch/ubatch, no affinity/NUMA/polling/priority
        # changes). Normal prefix early-stop law: first full-row
        # mismatch establishes variation; a deterministic claim
        # requires DETERM_MIN_REPEATS identical units.
        return [
            {"tag": f"{CASE}-B-cpu-thr4-00{i}",
             "argv_delta": (ARM_C_DEV_NONE_ARGV_DELTA
                            + ARM_C1_ARGV_DELTA),
             "ngl": 0, "request": "accepted"}
            for i in (1, 2, 3, 4, 5)
        ]
    if arm == ARM_C2_NAME:
        # AMENDMENT-003: the serial deep discriminator. NOT part of
        # automatically reachable execution: no dispatch through
        # NAMESPACE_ARM_BINDING can authorize this arm — only a
        # dedicated d250-arm-c2 exact-head maintainer dispatch with
        # the explicit c2-serial-gate line AND a retained C1-varied
        # gate record (validate_authority_payload /
        # c1_dispatch_c2_unlocked). Preserves the legacy serial
        # geometry verbatim (-t 1 -tb 1; early stop; 5 identical for
        # a deterministic claim) so a maintainer-gated C2 run would
        # answer the ORIGINAL question without redesign.
        return [
            {"tag": f"{CASE}-B-cpu-thr1-00{i}",
             "argv_delta": ARM_C_DEV_NONE_ARGV_DELTA
             + ARM_C2_ARGV_DELTA,
             "ngl": 0, "request": "accepted"}
            for i in (1, 2, 3, 4, 5)
        ]
    if arm == "D-context-transition":
        # Only reached when A-C do not localize. Predeclared length
        # ladder between 1022 (deterministic) and 3077 (variable)
        # tokens, same accepted fixture derivation rule, at the
        # ACCEPTED placement (the factor here is prompt length, not
        # the backend). Ladder frozen BEFORE any execution.
        # CORRECTION PASS 3 (NO-GO 5847890177, blocker 4C): the
        # prospective deterministic-confirmation rule. Units 001/002
        # per length are the SCREENING pair (2 repeats — establishes
        # only a pair-identical observation, never a deterministic
        # claim). Units 003-005 per length are the PREDECLARED
        # ADAPTIVE CONFIRMATION extension: executed ONLY for the
        # exact boundary-adjacent deterministic length when a
        # LOCALIZED claim would depend on it (never for unrelated
        # ladder points); a first mismatch at ANY point establishes
        # variability immediately (screening or confirmation).
        out = []
        for length in ARM_D_LADDER_LENGTHS:
            for i in (1, 2):
                out.append({
                    "tag": f"case-{length}-B-ladder-{length}-00{i}",
                    "argv_delta": (), "ngl": ACCEPTED_MATCHED_NGL,
                    "request": "accepted", "ladder_length": length})
            for i in (3, 4, 5):
                out.append({
                    "tag": (f"case-{length}-B-ladder-{length}-"
                            f"00{i}-confirm"),
                    "argv_delta": (), "ngl": ACCEPTED_MATCHED_NGL,
                    "request": "accepted", "ladder_length": length,
                    "confirm_extension": True})
        return out
    raise DiagnosticError(f"unknown arm: {arm}")


ARM_PLANS = {arm: _arm_units(arm) for arm in (
    "A-vulkan-necessity", "B-process-init", "C-cpu-threads",
    "C1-reduced-parallelism", ARM_C2_NAME, "D-context-transition")}


def probe_list_for(arm: str) -> list[dict[str, Any]]:
    """The ordered unit list an arm is authorized to execute."""
    if arm not in ARM_PLANS:
        raise DiagnosticError(f"unknown arm: {arm}")
    return [dict(u) for u in ARM_PLANS[arm]]


# ---------------------------------------------------------------------------
# Determinism judgement (digest-only)
# ---------------------------------------------------------------------------

def canonical_token_digest(tokens: list[int]) -> str:
    if (not isinstance(tokens, list) or len(tokens) != DECISIONS
            or not all(isinstance(t, int) for t in tokens)):
        raise DiagnosticError(
            f"tokens must be a list of {DECISIONS} ints")
    return sha256_bytes(CANONICAL_PACK.pack(*tokens))


def row_digest(row: bytes) -> str:
    if not isinstance(row, bytes) or len(row) != ROW_BYTES:
        raise DiagnosticError(
            f"row must be exactly {ROW_BYTES} bytes")
    return sha256_bytes(row)


def judge_repeat_determinism(digests: list[str]) -> dict[str, Any]:
    """Digest equality judgement with the frozen repeat rules.

    A nondeterministic verdict requires only the observed mismatches
    (first mismatch suffices); a DETERMINISTIC verdict requires the
    predeclared repeat count (>= DETERM_MIN_REPEATS).
    """
    if not digests:
        raise DiagnosticError("no digests to judge")
    unique = sorted(set(digests))
    deterministic = len(unique) == 1
    return {
        "deterministic": deterministic if not deterministic else
        len(digests) >= DETERM_MIN_REPEATS,
        "strictly_identical": deterministic,
        "n": len(digests),
        "unique": unique,
        "deterministic_claim_valid": deterministic and
        len(digests) >= DETERM_MIN_REPEATS,
    }


# ---------------------------------------------------------------------------
# FROZEN PREFIX POPULATION LAW (correction pass 3, NO-GO 5847890177
# blocker 2). Machine-enforced; the reducer derives the stop reason
# mechanically from the retained rows/custody, never from a
# caller-supplied ``stopped_early`` boolean.
# ---------------------------------------------------------------------------
PREFIX_LAW_MIN_MISMATCH_UNITS = 2


def prefix_population_facts(
        planned_tags: list[str],
        retained_tags: list[str],
        row_digests: dict[str, Any],
        deterministic_required: int = DETERM_MIN_REPEATS,
        allow_inflight_tail: bool = False,
        ) -> dict[str, Any]:
    """Judge one condition's retained population under the frozen law.

    ``planned_tags``: the frozen ordered unit plan (index order ==
    execution order). ``retained_tags``: the VALID retained units
    actually present (already per-unit verified). ``row_digests``:
    per-tag digest tuple (or any hashable equality subject; row
    digests in practice). A condition is:

    * ``deterministic`` ONLY when every planned unit is retained and
      ALL digests are identical (>= deterministic_required).
    * ``nondeterministic`` (mismatch-triggered early stop) when the
      retained units form a CONTIGUOUS PREFIX of the plan starting at
      index 0, at least two units exist, the first digest mismatch
      occurs WITHIN the retained prefix, and execution stopped at the
      first mismatch (no later planned unit retained) — except units
      already unavoidably in flight under the frozen in-flight rule
      (``allow_inflight_tail`` marks conditions whose producer
      executes fixed batches; the in-flight units immediately after
      the mismatch unit are retained-but-excused, NEVER units past
      the first mismatch+batch boundary).
    * otherwise ``invalid`` (fail closed): gaps inside the retained
      prefix, retained units past the declared stop point, duplicates,
      unordered indexes, or an all-identical population below the
      deterministic threshold.
    """
    planned = list(planned_tags)
    retained = list(retained_tags)
    if len(set(retained)) != len(retained):
        return _pp_invalid("duplicate retained tags", retained, planned)
    index_of = {tag: i for i, tag in enumerate(planned)}
    unknown = [t for t in retained if t not in index_of]
    if unknown:
        return _pp_invalid(f"retained units not in the frozen plan: "
                           f"{sorted(unknown)}", retained, planned)
    indexes = sorted(index_of[t] for t in retained)
    if not indexes:
        return _pp_invalid("no retained units", retained, planned)
    if indexes != list(range(len(indexes))):
        return _pp_invalid(
            f"retained units are not a contiguous prefix from unit 001 "
            f"(indexes {indexes})", retained, planned)
    n = len(indexes)
    digests = [row_digests[t] for t in
               sorted(retained, key=lambda t: index_of[t])]
    unique = []
    for d in digests:
        if d not in unique:
            unique.append(d)
    first_mismatch_at = None if len(unique) == 1 else next(
        i for i in range(1, n) if digests[i] != digests[0])
    planned_tail = planned[n:]
    if first_mismatch_at is None:
        # all identical: deterministic ONLY at the full frozen count
        if n < deterministic_required or planned_tail:
            return {
                "population": "incomplete",
                "deterministic": False,
                "nondeterministic": False,
                "n": n,
                "first_mismatch_index": None,
                "stop_reason": (
                    "identical rows below the deterministic claim count"
                    if n < deterministic_required else
                    "identical rows but the planned population is "
                    "incomplete"),
                "planned": planned, "retained": retained,
                "invalid": None,
            }
        return {
            "population": "complete_deterministic",
            "deterministic": True,
            "nondeterministic": False,
            "n": n,
            "first_mismatch_index": None,
            "stop_reason": None,
            "planned": planned, "retained": retained,
            "invalid": None,
        }
    # A verified mismatch exists inside the retained prefix.
    # Stop law: no execution past the mismatch unit, except the
    # explicitly frozen in-flight allowance (units at indexes
    # first_mismatch_at+1 .. first_mismatch_at+inflight bound when the
    # arm freezes batch execution). Without the allowance, the prefix
    # must END exactly at the first-mismatch unit.
    allowed_end = first_mismatch_at + 1
    if allow_inflight_tail:
        # frozen rule: at most the immediately following unit may be
        # already in flight (batch-of-2 producers); any unit beyond
        # that, or any retained unit after a NON-mismatch unit when a
        # mismatch already answered, is execution past the stop point.
        allowed_end = first_mismatch_at + 2
    if n > allowed_end:
        return _pp_invalid(
            f"execution continued past the first mismatch (mismatch at "
            f"unit {first_mismatch_at + 1}, retained {n} units) without "
            f"a predeclared reason", retained, planned)
    if n < PREFIX_LAW_MIN_MISMATCH_UNITS:
        return _pp_invalid(
            "fewer than two retained units cannot establish a mismatch",
            retained, planned)
    return {
        "population": "complete_nondeterministic_prefix",
        "deterministic": False,
        "nondeterministic": True,
        "n": n,
        "first_mismatch_index": first_mismatch_at,
        "stop_reason": "mismatch_triggered_stop",
        "planned": planned, "retained": retained,
        "invalid": None,
    }


def _pp_invalid(reason: str, retained: list[str],
                planned: list[str]) -> dict[str, Any]:
    return {
        "population": "invalid",
        "deterministic": False,
        "nondeterministic": False,
        "n": len(retained),
        "first_mismatch_index": None,
        "stop_reason": None,
        "planned": planned,
        "retained": retained,
        "invalid": reason,
    }


def terminal_vocabulary() -> tuple[str, ...]:
    return TERMINALS + (REDUCER_BLOCKED,)
