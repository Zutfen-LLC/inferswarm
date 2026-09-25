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
  * No physical entrypoint runs without a MAINTAINER DISPATCH
    AUTHORITY revalidated LIVE immediately before every unit: an
    OWNER/MEMBER top-level comment on PR #(this PR) carrying the
    dispatch phrase + ``head=<sha>`` + ``diagnostic-namespace=<d250-…>``
    as exact stripped lines, plus live OPEN/unmerged PR state and
    OPEN issue state. There is no production path that accepts a
    cached authority (the runner takes no authority parameter).
  * Every discriminator arm runs at the EXACT accepted subject
    semantics except the ONE declared factor: same accepted binaries,
    same three-member model set (all digests verified before any
    launch), same fixture ladder (sha-verified), same BYTE-EXACT
    accepted request contract (extras rejected), same identity
    discipline (fresh raw observations pre AND post; single-factor
    DIAGNOSTIC_ONLY interventions only).
  * Arm A2 CPU-only control uses ``-dev none`` — the PROVEN true
    CPU-only control of the pinned build (issue250_phase0 PINNED_
    CONTROLS) — NOT ``-ngl 0`` (which keeps the Vulkan backend in
    the scheduler with op_offload/KV-offload possible).
  * case-4096 never executes (out of scope for #250; refused
    outright, no preauthorization path exists in this module).
  * Determinism is judged ONLY on independently computed digests of
    rows/tokens; timing is metadata.
  * Retained bytes are append-only with ``-quarantined`` siblings.
  * The terminal is derived MECHANICALLY by the offline reducer from
    retained unit bytes against the frozen arm plan; missing or
    ambiguous evidence fails closed to
    R8I3B_REDUCER_BLOCKED_INCOMPLETE, never a hand-selected terminal.
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
DIAGNOSTIC_PR_NUMBER = 0  # bound after PR creation; tests verify binding
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

# Frozen discriminator geometry (Issue #250 §A–§D).
CASE = "case-3072"
ACCEPTED_MATCHED_NGL = 8
MIN_REPEATS = 3
DETERM_MIN_REPEATS = 5   # deterministic claim requires 5 identical
ARM_A2_DEV_NONE_ARGV_DELTA = ("-dev", "none")
ARM_C_THREADS = ("1",)
ARM_D_LADDER_LENGTHS = (1024, 1536, 2048, 2304, 2560, 3072)

# Same-process (Arm B) request-contract extension: id_slot pinning is
# required to make repeated requests land on the SAME slot. The
# accepted contract has no id_slot key; the frozen diagnostic contract
# for Arm B is the accepted contract + id_slot:3, and this extension
# is DECLARED in METHODOLOGY (maintainer-reviewed) rather than silent.
ARM_B_CONTRACT = dict(REQUEST_CONTRACT)
ARM_B_CONTRACT["id_slot"] = 3
ARM_B_EXTRA_KEYS = frozenset({"id_slot"})


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
    # Any arm other than the frozen arm vocabulary is refused.
    arms = [ln.split("=", 1)[1] for ln in lines
            if ln.startswith("arm=")]
    if len(arms) != 1 or arms[0] not in ARM_PLANS:
        raise DiagnosticError(
            f"exactly one frozen arm required (one of {sorted(ARM_PLANS)}), "
            f"found {arms}")
    return dict(authority, namespace=namespace, arm=arms[0])


# ---------------------------------------------------------------------------
# Frozen discriminator arm plans (Issue #250 §A–§D, minimum geometry)
# ---------------------------------------------------------------------------

def _arm_units(arm: str) -> list[dict[str, Any]]:
    """Predeclared unit geometry per arm (fresh process per unit unless
    the arm is same-process by definition)."""
    if arm == "A-vulkan-necessity":
        # CPU-only (-dev none) at the exact accepted workload, 3 repeats
        # minimum; extend to 5 before a deterministic claim.
        return [{"tag": f"{CASE}-B-devnone-00{i}", "argv_delta":
                 ARM_A2_DEV_NONE_ARGV_DELTA, "ngl": 0,
                 "request": "accepted"}
                for i in (1, 2, 3, 4, 5)]
    if arm == "B-process-init":
        # Arm 1: 5 fresh-process units at accepted placement (reproduce);
        # Arm 2: ONE process, 5 same-process repeats (id_slot pinned,
        # cache_prompt=false proven full reset).
        return [
            {"tag": f"{CASE}-B-fresh-00{i}", "argv_delta": (),
             "ngl": ACCEPTED_MATCHED_NGL, "request": "accepted"}
            for i in (1, 2, 3, 4, 5)
        ] + [
            {"tag": f"{CASE}-B-sameproc-00{i}", "argv_delta": (),
             "ngl": ACCEPTED_MATCHED_NGL, "request": "arm-b",
             "same_process": True}
            for i in (1, 2, 3, 4, 5)
        ]
    if arm == "C-cpu-threads":
        # Default 14-thread regime (2 units reproduce) vs serial regime
        # -t 1 -tb 1 (5 units).
        return [
            {"tag": f"{CASE}-B-thr14-00{i}", "argv_delta": (),
             "ngl": ACCEPTED_MATCHED_NGL, "request": "accepted"}
            for i in (1, 2)
        ] + [
            {"tag": f"{CASE}-B-thr1-00{i}",
             "argv_delta": ("-t", "1", "-tb", "1"),
             "ngl": ACCEPTED_MATCHED_NGL, "request": "accepted"}
            for i in (1, 2, 3, 4, 5)
        ]
    if arm == "D-context-transition":
        # Predeclared length ladder between 1022 (deterministic) and
        # 3077 (variable), same fixture derivation rule, 2 repeats per
        # length at the accepted placement. Ladder frozen BEFORE any
        # execution; never picked after seeing outputs.
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

CANONICAL_TOKENS = None  # set by reduce from retained bytes


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
# Terminal derivation (offline, fail-closed)
# ---------------------------------------------------------------------------

REQUIRED_ARMS = ("A-vulkan-necessity",)


def derive_terminal(reduction: dict[str, Any]) -> str:
    """Mechanically derive the #250 terminal from a COMPLETE reduction.

    Decision tree (frozen):
      * reducer incomplete -> R8I3B_REDUCER_BLOCKED_INCOMPLETE
      * localized: exactly one smallest boundary factor demonstrated
        by a one-factor control pair (deterministic condition vs
        nondeterministic condition), with the weaker interpretations
        excluded by the retained evidence;
      * else unresolved.
    """
    if not isinstance(reduction, dict):
        raise DiagnosticError("reduction must be a dict")
    if not reduction.get("complete"):
        return REDUCER_BLOCKED
    arms = reduction.get("arms", {})
    for arm in reduction.get("required_arms", REQUIRED_ARMS):
        if arm not in arms:
            return REDUCER_BLOCKED
    a = arms.get("A-vulkan-necessity", {})
    det_map = a.get("condition_determinism", {})
    cpu = det_map.get("cpu_only_devnone")
    accepted = det_map.get("accepted_ngl8")
    if cpu is None or accepted is None:
        return REDUCER_BLOCKED
    if cpu["deterministic"] and not accepted["deterministic"]:
        return "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED"
    if cpu["deterministic"] and accepted["deterministic"]:
        # CPU-only deterministic AND accepted condition now also
        # deterministic: reproduction failed -> unresolved (honest).
        return "R8I3B_REFERENCE_RUNTIME_UNRESOLVED"
    if not cpu["deterministic"]:
        # CPU-only varies: Vulkan participation NOT necessary; single
        # localized boundary not yet demonstrated by arm A alone.
        return "R8I3B_REFERENCE_RUNTIME_UNRESOLVED"
    return "R8I3B_REFERENCE_RUNTIME_UNRESOLVED"


def terminal_vocabulary() -> tuple[str, ...]:
    return TERMINALS + (REDUCER_BLOCKED,)
