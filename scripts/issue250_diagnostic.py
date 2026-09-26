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

# Arm D ladder derivation rule (predeclared; Issue #250 §D: same
# accepted fixture derivation rule — repeated sentence block with the
# identical prologue/suffix, length set by sentence repeat count).
ARM_D_LADDER_SENTENCE_REPEATS = {
    1024: 68, 1536: 102, 2048: 136, 2304: 153, 2560: 171, 3072: 204,
}

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
# ---------------------------------------------------------------------------
NAMESPACE_ARM_BINDING = {
    "d250-arm-a": "A-vulkan-necessity",
    "d250-arm-b": "B-process-init",
    "d250-arm-c": "C-cpu-threads",
    "d250-arm-d": "D-context-transition",
}
ARM_NAMESPACE_BINDING = {arm: ns for ns, arm in NAMESPACE_ARM_BINDING.items()}


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
    validate_namespace_arm_binding(namespace, arms[0])
    return dict(authority, namespace=namespace, arm=arms[0])


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
        # Only reached when CPU-only variation survives Arm B. Remains
        # CPU-only `-dev none`. ONE conceptual threading-regime factor:
        # accepted/default CPU threading (2 reproduction units) vs the
        # serial CPU regime `-t 1 -tb 1` (5 units). Nothing else
        # changes (no batch/ubatch/NUMA/affinity/polling/warmup/Vulkan).
        return [
            {"tag": f"{CASE}-B-cpu-thr-default-00{i}",
             "argv_delta": ARM_C_DEV_NONE_ARGV_DELTA, "ngl": 0,
             "request": "accepted"}
            for i in (1, 2)
        ] + [
            {"tag": f"{CASE}-B-cpu-thr1-00{i}",
             "argv_delta": ARM_C_DEV_NONE_ARGV_DELTA + ARM_C_SERIAL_ARGV_DELTA,
             "ngl": 0, "request": "accepted"}
            for i in (1, 2, 3, 4, 5)
        ]
    if arm == "D-context-transition":
        # Only reached when A-C do not localize. Predeclared length
        # ladder between 1022 (deterministic) and 3077 (variable),
        # same accepted fixture derivation rule, 2 repeats per length
        # at the ACCEPTED placement (the factor here is prompt length,
        # not the backend). Ladder frozen BEFORE any execution.
        out = []
        for length in ARM_D_LADDER_LENGTHS:
            for i in (1, 2):
                out.append({
                    "tag": f"case-{length}-B-ladder-{length}-00{i}",
                    "argv_delta": (), "ngl": ACCEPTED_MATCHED_NGL,
                    "request": "accepted", "ladder_length": length})
        return out
    raise DiagnosticError(f"unknown arm: {arm}")


ARM_PLANS = {arm: _arm_units(arm) for arm in (
    "A-vulkan-necessity", "B-process-init", "C-cpu-threads",
    "D-context-transition")}


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


def terminal_vocabulary() -> tuple[str, ...]:
    return TERMINALS + (REDUCER_BLOCKED,)
