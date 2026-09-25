#!/usr/bin/env python3
"""Issue #248 (R8-I3A) — DIAGNOSTIC-ONLY tooling spine.

Diagnostic follow-up to the accepted Issue #241 generation-2 terminal
R8I3_COMPARATOR_V2_BLOCKED (head 4e8b4fc369defe409f68da46e26d152eade4df47).
Nothing in this module requalifies comparator/2, retries the blocked
qualification, relaxes determinism, or touches the accepted evidence.

Machine-enforced boundaries (tested in test_issue248_diagnostic.py):

  * The diagnostic namespace is exactly ``d248-<label>``; every physical
    helper refuses any other namespace, and refuses the qualification
    namespace outright.
  * No physical entrypoint runs without a MAINTAINER DISPATCH AUTHORITY
    revalidated LIVE immediately before every unit: the top-level PR
    conversation comment with dispatch phrase + head=sha +
    diagnostic-namespace scope as exact stripped lines from a current
    OWNER/MEMBER, fetched together with the live PR state (OPEN,
    unmerged, base main, head == authorized head) and the live Issue
    #248 state (OPEN). There is no production path that accepts a
    cached/prevalidated authority dict (the runner has no authority
    parameter); a closed/merged PR or a closed issue fails before any
    launch; any later HEAD movement invalidates the authorization.
  * case-4096 executes ONLY when the SAME live comment carries an exact
    stripped ``case-4096:<reason>`` line (exactly one, nonempty
    reason); the authorization is bound to that comment id in the
    authority snapshot. No caller-supplied field can manufacture it.
  * Every diagnostic execution unit binds, before launch: exact binary
    identity (one of the three accepted llama.cpp pin builds), the
    COMPLETE accepted three-member model set (every member hashed
    independently and compared against the accepted #241 digests; the
    launched path is the derived member 1), exact case fixture from the
    accepted historical ladder (sha-verified), the frozen request
    contract (caller overrides must equal it exactly; extra semantic
    keys rejected), and the EXACT accepted runtime/device subject
    identity (every frozen field derived from fresh raw observations
    pre AND post execution; single-factor DIAGNOSTIC_ONLY interventions
    only).
  * Determinism is judged ONLY on independently computed digests of the
    derived acceptance-bearing output (the fixed 8-token list canonically
    packed) plus the full row bytes when the observer captured them; raw
    responses are custody-only.
  * Timing is diagnostic metadata; never a gate.
  * Retained bytes are append-only: a failed or superseded diagnostic
    unit directory must be moved aside to a ``-quarantined`` sibling
    before any re-run at the same label (no overwrite in place).
  * The diagnostic terminal is derived MECHANICALLY by the offline
    reducer from retained unit bytes against the frozen plan; missing
    or ambiguous evidence fails closed to the machine-readable
    R8I3_REDUCER_BLOCKED_INCOMPLETE state, never to a hand-selected
    terminal.

The physical runner is deliberately structured as a thin orchestrator
around the SAME seams the accepted campaign used, so the diagnostic runs
share execution semantics (one fresh process per request, ngl from the
frozen placement, exact request contract) with the blocked campaign.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable

# --- accepted campaign bindings (read-only constants) --------------------
ACCEPTED_CAMPAIGN_HEAD = (
    "4e8b4fc369defe409f68da46e26d152eade4df47")
ACCEPTED_TERMINAL = "R8I3_COMPARATOR_V2_BLOCKED"
ACCEPTED_EVIDENCE_ROOT = "inferswarm01:/home/hermes/is241-campaign-v3"
ACCEPTED_MANIFEST_SELF_DIGEST = (
    "78400bcfe9de5464fdbceca9c05c9eb1938ccd3487d7d053043d5be50a52a0eb")
DIAGNOSTIC_ISSUE = 248
DIAGNOSTIC_PR_NUMBER = 249
DIAGNOSTIC_KIND = "R8-I3A"
# The dispatch phrase is intentionally NOT spelled out in any committed
# report prose (accepted #241 lesson): it must appear as an exact stripped
# line only in the authorizing comment. The verifier matches the line
# against a comment-body line that starts with the frozen prefix.
DIAGNOSTIC_DISPATCH_PHRASE_PREFIX = "R8I3A PHYSICAL DISPATCH"
DIAGNOSTIC_DISPATCH_PHRASE = f"{DIAGNOSTIC_DISPATCH_PHRASE_PREFIX} #{DIAGNOSTIC_ISSUE}"

# Diagnostic terminals permitted by Issue #248 (exact vocabulary).
TERMINALS = (
    "R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED",
    "R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED",
    "R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED",
    "R8I3_REF_NONDETERMINISM_UNRESOLVED",
    "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED",
)

# The three accepted llama.cpp b29c606e builds available as diagnostic
# binaries. OBSERVER-LADDER semantics (Phase 3):
#   canonical  — no observation hook at all (accepted R8-H binary);
#   r8e-obs    — R8-E observation-only hook (captures rows, no forcing);
#   comparator — R8-E + R8-I3 comparator/2 hooks (accepted patched build).
# Correction 1: exact model authority — the accepted #241 split GGUF set
# (PR #242 head 4e8b4fc, scripts/issue241_constants.py MODEL_*). The
# complete set verifies before ANY launch; the server launch points at
# member 1 (the accepted loader seam) only after all three digests
# verify against these accepted values.
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
SERVER_BINARIES = {
    "canonical": "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e",
    "r8e-obs": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
    "comparator": "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad",
}

# Diagnostic namespace shape. d248-<label> only; the qualification
# campaign namespace and every predictive/holdout namespace are refused.
NAMESPACE_RE = re.compile(r"^d248-[a-z0-9][a-z0-9-]*[a-z0-9]$")
FORBIDDEN_NAMESPACE_SUBSTRINGS = (
    "c237-",       # predictive calibration namespace (hard prohibition)
    "issue241",    # qualification campaign namespace
    "qualification",
    "campaign",    # never shadow campaign namespaces
    "phase",       # never shadow campaign phase namespaces
)

# The accepted historical fixture ladder binding (Issue #241 frozen
# constants, PR #242 head 4e8b4fc): path relative to repo root and the
# sha256 of the ladder document. Re-declared here because the #241
# producer modules live on the unmerged qualification branch; the ladder
# BYTES are identical (same frozen evidence file on main).
FIXTURE_LADDER_REL = (
    "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/"
    "fixture-ladder.json")
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db")
N_VOCAB = 248320
ROW_BYTES = N_VOCAB * 4
DECISIONS = 8
CANONICAL_PACK = struct.Struct("<8I")

# Frozen request contract — BYTE-EXACT copy of the accepted #241
# campaign contract (PR #242 head 4e8b4fc, issue241_constants.py).
# samplers=["top_k"] + top_k=1 is TRUE GREEDY (the R8-C lesson: the
# sampler-chain field determines what actually runs; never alter it).
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
# Keys whose presence could alter llama.cpp completion semantics; any
# extra key in a request contract is rejected (correction 2).
REQUEST_CONTRACT_KEYS = frozenset(REQUEST_CONTRACT)


def canonical_request_digest(contract: dict[str, Any]) -> str:
    """Digest of the canonical (sorted-keys JSON) request contract."""
    return sha256_bytes(
        json.dumps(contract, sort_keys=True, separators=(",", ":")
                   ).encode())


def validate_request_contract(contract: Any) -> dict[str, Any]:
    """Require byte/semantic equality with the frozen request contract.

    Correction 2: production diagnostic execution derives the request
    from immutable frozen authority; any override must be EXACTLY equal
    (same keys, same values, no extras) or it is rejected. Unknown keys
    are rejected outright — they could alter completion semantics.
    """
    if not isinstance(contract, dict):
        raise DiagnosticError("request contract must be a dict")
    keys = set(contract)
    extra = keys - REQUEST_CONTRACT_KEYS
    if extra:
        raise DiagnosticError(
            f"request contract carries extra semantic keys: {sorted(extra)}")
    missing = REQUEST_CONTRACT_KEYS - keys
    if missing:
        raise DiagnosticError(
            f"request contract is missing frozen keys: {sorted(missing)}")
    if contract != REQUEST_CONTRACT:
        differing = {k: (contract.get(k), REQUEST_CONTRACT[k])
                     for k in sorted(REQUEST_CONTRACT_KEYS)
                     if contract.get(k) != REQUEST_CONTRACT[k]}
        raise DiagnosticError(
            f"request contract is not the frozen accepted contract; "
            f"differences: {differing}")
    return dict(contract)


# Frozen diagnostic case ladder (accepted historical excluded fixtures,
# diagnostics-only reuse; case-4096 requires explicit preauthorization
# because the accepted campaign never executed it).
DIAGNOSTIC_CASES = ("case-256", "case-1024", "case-3072")
CASE_4096 = "case-4096"

# Frozen reference-arm placement rungs (from the accepted placement
# ladder 1/2/4/6/8; ngl=8 is the accepted matched placement).
PLACEMENT_RUNGS = (1, 2, 4, 6, 8)
ACCEPTED_MATCHED_NGL = 8


class DiagnosticError(RuntimeError):
    """Raised when a diagnostic boundary is violated."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Namespace and authority boundaries
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Dispatch-authority identity (round 3): every terminal-bearing unit binds
# to the EXACT authorizing comment. The canonical digest covers the comment
# identity fields AND the full comment body bytes, so a receipt stamped
# under one comment can never be re-bound to another.
# ---------------------------------------------------------------------------

AUTHORITY_DIGEST_FIELDS = (
    "comment_id", "issue_url", "author_association", "created_at",
    "head_sha", "namespace", "body",
)


def authority_digest(authority: dict[str, Any]) -> str:
    """Canonical digest of the authorizing comment's binding identity."""
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


def unit_authority_block(final_authority: dict[str, Any]) -> dict[str, Any]:
    """The canonical per-unit dispatch-authority block for unit receipts.

    One implementation builds the block the producer stamps into every
    retained unit receipt; the offline reducer re-derives the SAME block
    from the live dispatch payload and requires exact equality, so a
    fabricated or transplanted receipt cannot satisfy the terminal
    reduction without the real authorizing comment bytes.
    """
    if not isinstance(final_authority, dict):
        raise DiagnosticError("final authority must be a dict")
    return {
        "comment_id": final_authority["comment_id"],
        "head_sha": final_authority["head_sha"],
        "namespace": final_authority["namespace"],
        "created_at": final_authority["created_at"],
        "author_association": final_authority["author_association"],
        "pr_number": DIAGNOSTIC_PR_NUMBER,
        "issue_number": DIAGNOSTIC_ISSUE,
        "dispatch_sha256": authority_digest(final_authority),
        "case4096": (dict(final_authority["case4096"])
                     if isinstance(final_authority.get("case4096"), dict)
                     else None),
    }


def bind_authority_observations(early: Any, late: Any) -> dict[str, Any]:
    """Require two independently fetched authorities to be the SAME one.

    The live GitHub authority can move during the potentially long
    interval between the early fail-fast check and physical launch
    (complete three-member model hashing alone reads ~72.5 GB). Both
    observations must bind to the identical comment ID, exact head,
    namespace, author association, created-at timestamp, PR binding and
    comment body (via the canonical digest); any difference fails closed
    BEFORE any unit custody exists or any process launches.
    """
    if not isinstance(early, dict) or not isinstance(late, dict):
        raise DiagnosticError(
            "authority observations must be objects")
    for key in (*AUTHORITY_DIGEST_FIELDS,):
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
    """Structurally validate a fetched dispatch authority payload.

    The accepted #241 authority model (top-level PR conversation comment
    whose body carries the dispatch phrase and ``head=<sha>`` as EXACT
    STRIPPED LINES, from a current OWNER/MEMBER, bound via issue_url) is
    mirrored here for the diagnostic issue, with one addition: the
    comment body must also carry a diagnostic scope line
    ``diagnostic-namespace=<d248-...>`` so a #241 qualification dispatch
    can never authorize diagnostic execution and vice versa. The live
    fetch path is :func:`fetch_dispatch_authority`.

    Corrections 3+4 (maintainer NO-GO): the payload must also carry the
    live PR/issue STATE (open_pr / issue_open, fetched in the same live
    pass — a closed or merged PR, or a closed Issue #248, fails here,
    before any launch); and any case-4096 authorization is parsed ONLY
    from the comment body's exact stripped ``case-4096:<reason>`` line
    (``preauthorized_case4096`` dict fields are ignored; the derived
    authorization is returned as ``case4096``).
    """
    if not isinstance(authority, dict):
        raise DiagnosticError("authority must be a dict")
    for key in ("comment_id", "issue_url", "author_association",
                "created_at", "body", "head_sha"):
        if not authority.get(key):
            raise DiagnosticError(f"authority field missing: {key}")
    for key in ("open_pr", "issue_open"):
        if key not in authority:
            raise DiagnosticError(
                f"live authority state missing: {key} (the dispatch must "
                f"be revalidated live; a cached payload without PR/issue "
                f"state cannot authorize)")
    if not authority["open_pr"]:
        raise DiagnosticError(
            f"PR #{DIAGNOSTIC_PR_NUMBER} is closed or merged")
    if not authority["issue_open"]:
        raise DiagnosticError(f"Issue #{DIAGNOSTIC_ISSUE} is closed")
    if authority["author_association"] not in ("OWNER", "MEMBER"):
        raise DiagnosticError(
            f"dispatch author is not OWNER/MEMBER: "
            f"{authority['author_association']!r}")
    if not str(authority["created_at"]):
        raise DiagnosticError("review-shaped payload (no created_at)")
    issue_url = str(authority["issue_url"])
    if not issue_url.rstrip("/").endswith(f"/issues/{DIAGNOSTIC_PR_NUMBER}"):
        raise DiagnosticError(
            f"authority comment is not bound to PR #{DIAGNOSTIC_PR_NUMBER}: "
            f"{issue_url}")
    if str(authority["head_sha"]) != expected_head:
        raise DiagnosticError(
            f"dispatch head {authority['head_sha']} != expected {expected_head}")
    lines = [ln.strip() for ln in str(authority["body"]).splitlines()]
    if DIAGNOSTIC_DISPATCH_PHRASE not in lines:
        raise DiagnosticError("dispatch phrase line absent")
    head_line = f"head={expected_head}"
    if head_line not in lines:
        raise DiagnosticError(f"exact head line absent: {head_line}")
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
    # case-4096 authorization derives ONLY from the comment bytes
    # (correction 4): an exact stripped ``case-4096:<reason>`` line,
    # exactly one, nonempty reason. Prose mentions and malformed
    # prefixes are not authorization.
    c4096 = [ln for ln in lines if ln.startswith("case-4096:")]
    if len(c4096) > 1:
        raise DiagnosticError(
            f"multiple conflicting case-4096 authorization lines "
            f"({len(c4096)})")
    case4096: dict[str, Any] | None = None
    if len(c4096) == 1:
        reason = c4096[0][len("case-4096:"):].strip()
        if not reason:
            raise DiagnosticError("case-4096 authorization line has an "
                                  "empty reason")
        case4096 = {"comment_id": authority["comment_id"],
                    "line": c4096[0], "reason": reason}
    return dict(authority, namespace=namespace, case4096=case4096)


def fetch_dispatch_authority(repo_root: Path, expected_head: str,
                             namespace: str,
                             github_api: str = "https://api.github.com"
                             ) -> dict[str, Any]:
    """Fetch and verify the live dispatch comment from the PR conversation.

    GET-only, paginated, fail-closed on unbounded pages; honors the
    authenticated GET-only proxy environment variables the accepted
    campaign used on the compute node (https_proxy/SSL_CERT_FILE).

    In the SAME live pass it fetches the PR state (must be OPEN,
    unmerged, base main, head exactly ``expected_head``) and the Issue
    #248 state (must be OPEN) — correction 3: a closed/merged PR or a
    closed issue fails before any launch, and HEAD movement
    automatically invalidates the authorization.
    """
    _require_clean_head(Path(repo_root), expected_head)
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue248-diagnostic"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _get_json(path: str) -> Any:
        url = f"{github_api}/repos/Zutfen-LLC/inferswarm/{path}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())

    # Live PR state: OPEN, unmerged, base main, head == expected_head.
    pr = _get_json(f"pulls/{DIAGNOSTIC_PR_NUMBER}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise DiagnosticError(
            f"PR #{DIAGNOSTIC_PR_NUMBER} is not open/unmerged "
            f"(state={pr.get('state')!r}, merged={pr.get('merged')!r})")
    if pr.get("base", {}).get("ref") != "main":
        raise DiagnosticError(
            f"PR #{DIAGNOSTIC_PR_NUMBER} base is not main: "
            f"{pr.get('base', {}).get('ref')!r}")
    if pr.get("head", {}).get("sha") != expected_head:
        raise DiagnosticError(
            f"GitHub PR head {pr.get('head', {}).get('sha')} != expected "
            f"{expected_head}")
    # Live issue state: OPEN.
    issue = _get_json(f"issues/{DIAGNOSTIC_ISSUE}")
    if issue.get("state") != "open":
        raise DiagnosticError(
            f"Issue #{DIAGNOSTIC_ISSUE} is not open "
            f"(state={issue.get('state')!r})")
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _get_json(f"issues/{DIAGNOSTIC_PR_NUMBER}/comments"
                          f"?page={page}&per_page=100")
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 50:
            raise DiagnosticError("unbounded comment pagination")
    for comment in comments:
        if DIAGNOSTIC_DISPATCH_PHRASE not in str(comment.get("body")):
            continue
        authority = {
            "comment_id": comment.get("id"),
            "issue_url": comment.get("issue_url"),
            "author_association": comment.get("author_association"),
            "created_at": comment.get("created_at"),
            "body": comment.get("body"),
            "head_sha": expected_head,
            "namespace": namespace,
            "open_pr": True,
            "issue_open": True,
        }
        try:
            return validate_authority_payload(authority, expected_head)
        except DiagnosticError:
            continue
    raise DiagnosticError(
        f"no valid dispatch authority for head {expected_head} "
        f"namespace {namespace}")


def require_live_dispatch(repo_root: Path, expected_head: str,
                          namespace: str, revalidate_authority: Any = None,
                          github_api: str = "https://api.github.com",
                          ) -> dict[str, Any]:
    """MANDATORY live revalidation immediately before a physical unit.

    There is no production path where omitting ``revalidate_authority``
    silently disables live verification (correction 3): the default
    fetcher is always executed. Tests inject a fake through
    ``revalidate_authority`` (a callable receiving
    ``(repo_root, expected_head, namespace, github_api)`` and returning
    the validated authority payload); production callers pass nothing.
    A cached/prevalidated dict passed here is NEVER trusted as
    authority.
    """
    if revalidate_authority is None:
        revalidate_authority = fetch_dispatch_authority
    authority = revalidate_authority(repo_root, expected_head, namespace,
                                     github_api)
    return validate_authority_payload(authority, expected_head)


# ---------------------------------------------------------------------------
# Diagnostic execution-unit custody
# ---------------------------------------------------------------------------

def unit_tag(case: str, arm: str, variant: str, index: int) -> str:
    """Canonical name of one diagnostic execution unit.

    variant encodes the one factor that differs from the accepted
    baseline execution (e.g. ``baseline``, ``ngl4``, ``no-observer``,
    ``r8e-only``, ``canonical``, ``case4096``).
    """
    if case not in DIAGNOSTIC_CASES + (CASE_4096,):
        raise DiagnosticError(f"case outside diagnostic ladder: {case}")
    if case == CASE_4096 and variant != "case4096":
        raise DiagnosticError(
            "case-4096 must be explicitly labeled in its variant")
    if arm not in ("B", "C"):
        raise DiagnosticError(f"arm must be B or C: {arm}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", variant):
        raise DiagnosticError(f"invalid variant: {variant}")
    return f"{case}-{arm}-{variant}-{index:03d}"


def prepare_unit_dir(root: Path, namespace: str, tag: str) -> Path:
    """Create (or quarantine) the append-only directory for a unit."""
    base = namespace_dir(root, namespace)
    base.mkdir(parents=True, exist_ok=True)
    unit = base / tag
    if unit.exists() or unit.is_symlink():
        raise DiagnosticError(
            f"existing diagnostic unit cannot be replaced: {unit}. "
            f"Move it to a -quarantined sibling first (append-only custody).")
    unit.mkdir()
    return unit


def quarantine_unit(root: Path, namespace: str, tag: str) -> Path:
    """Move a failed/superseded unit aside; never overwrite in place."""
    base = namespace_dir(root, namespace)
    unit = base / tag
    if not unit.is_dir():
        raise DiagnosticError(f"unit to quarantine does not exist: {unit}")
    target = base / f"{tag}-quarantined"
    if target.exists():
        raise DiagnosticError(f"quarantine target already exists: {target}")
    unit.rename(target)
    return target


def verify_binary(path: Path, binary_id: str) -> str:
    """Verify an executing binary is one of the three accepted builds."""
    if binary_id not in SERVER_BINARIES:
        raise DiagnosticError(f"unknown diagnostic binary id: {binary_id}")
    digest = file_sha256(path)
    if digest != SERVER_BINARIES[binary_id]:
        raise DiagnosticError(
            f"binary sha mismatch for {binary_id}: {digest}")
    return digest


# ---------------------------------------------------------------------------
# Campaign-level model attestation (maintainer correction 2026-09-25)
# ---------------------------------------------------------------------------
# Per-unit full SHA-256 of all three ~72.5 GiB members added a complete
# model read to every unit without materially improving the model-identity
# guarantee. The corrected design: ONE cryptographic opening attestation
# (full three-member hash against the accepted #241 values + per-member
# stat witness), cheap fail-closed file/topology/stat identity checks
# immediately before every unit, and ONE closing full re-hash bound to
# the opening. No unit re-hashes the model on the unchanged path.
MODEL_ATTESTATION_OPEN_SCHEMA = (
    "inferswarm.issue248.model-attestation-open/1")
MODEL_ATTESTATION_CLOSE_SCHEMA = (
    "inferswarm.issue248.model-attestation-close/1")
MODEL_ATTESTATION_OPEN_NAME = "model-attestation-open.json"
MODEL_ATTESTATION_CLOSE_NAME = "model-attestation-close.json"
# The stat fields a witness carries (observed via lstat; atime is
# deliberately NOT witnessed because reads legitimately update it).
WITNESS_STAT_KEYS = ("bytes", "device", "inode", "mtime_ns", "ctime_ns")


def attestation_canonical_digest(doc: dict[str, Any]) -> str:
    """Canonical digest of an attestation minus its own digest field."""
    payload = {key: value for key, value in doc.items()
               if key not in ("attestation_sha256", "closing_sha256")}
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def observe_model_stats(model_dir: Path,
                        stat_fn: Callable[[Path], Any] | None = None,
                        ) -> dict[str, dict[str, Any]]:
    """Live per-member file-identity observation (lstat; no byte reads).

    Enforces the exact split topology (no extra/missing member) and
    rejects symlinked or non-regular members. Returns
    ``{member name: {bytes, device, inode, mtime_ns, ctime_ns,
    symlink, regular_file}}``.
    """
    import stat as stat_module
    stat_fn = stat_fn or os.lstat
    model_dir = Path(model_dir)
    if not model_dir.is_dir():
        raise DiagnosticError(
            f"model dir is not a directory: {model_dir}")
    present = sorted(p.name for p in model_dir.iterdir()
                     if p.suffix == ".gguf")
    if present != sorted(MODEL_MEMBERS):
        raise DiagnosticError(
            f"unexpected split topology in {model_dir}: {present}")
    out: dict[str, dict[str, Any]] = {}
    for member in MODEL_MEMBERS:
        path = model_dir / member
        info = stat_fn(path)
        mode = info.st_mode
        if stat_module.S_ISLNK(mode):
            raise DiagnosticError(f"model member is a symlink: {path}")
        if not stat_module.S_ISREG(mode):
            raise DiagnosticError(
                f"model member is not a regular file: {path}")
        out[member] = {
            "bytes": info.st_size, "device": info.st_dev,
            "inode": info.st_ino, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
            "symlink": False, "regular_file": True}
    return out


def build_model_attestation(model_dir: Path, expected_head: str, *,
                            hasher: Callable[[Path], str] | None = None,
                            stat_observer=None) -> dict[str, Any]:
    """Opening attestation: full three-member hash + stat witnesses.

    Hashes every accepted member against the frozen #241 digests exactly
    once and records the complete per-member file identity. The doc is
    self-digesting via :func:`attestation_canonical_digest`.
    """
    hasher = hasher or file_sha256
    stats = (stat_observer or observe_model_stats)(model_dir)
    members = []
    for member in MODEL_MEMBERS:
        path = Path(model_dir) / member
        digest = hasher(path)
        if digest != MODEL_MEMBER_SHA256[member]:
            raise DiagnosticError(
                f"model member sha mismatch for {member}: {digest} != "
                f"{MODEL_MEMBER_SHA256[member]}")
        members.append({"name": member, "path": str(path),
                        "sha256": digest, **stats[member]})
    doc: dict[str, Any] = {
        "schema": MODEL_ATTESTATION_OPEN_SCHEMA,
        "head_sha": expected_head,
        "model_dir": str(Path(model_dir)),
        "members": sorted(members, key=lambda m: m["name"]),
    }
    doc["attestation_sha256"] = attestation_canonical_digest(doc)
    return doc


def _validate_member_entries(doc: dict[str, Any]) -> None:
    members = doc.get("members")
    if (not isinstance(members, list) or len(members) != len(MODEL_MEMBERS)
            or any(not isinstance(m, dict) for m in members)):
        raise DiagnosticError("attestation member population malformed")
    names = sorted(m["name"] for m in members)
    if names != sorted(MODEL_MEMBERS) or len(set(names)) != len(names):
        raise DiagnosticError(
            "attestation member names do not match the accepted set")
    for member in members:
        name = member["name"]
        if member.get("path") != str(Path(doc["model_dir"]) / name):
            raise DiagnosticError(f"attestation path mismatch: {name}")
        if member.get("sha256") != MODEL_MEMBER_SHA256[name]:
            raise DiagnosticError(
                f"attestation digest is not the accepted value: {name}")
        if member.get("symlink") is not False or (
                member.get("regular_file") is not True):
            raise DiagnosticError(
                f"attestation file status malformed: {name}")
        for key in WITNESS_STAT_KEYS:
            if type(member.get(key)) is not int or member[key] < 0:
                raise DiagnosticError(
                    f"attestation witness field {key} malformed: {name}")


def validate_model_attestation(doc: Any,
                               expected_head: str | None = None,
                               ) -> dict[str, Any]:
    """Fail-closed validation of an opening attestation document."""
    if not isinstance(doc, dict) or doc.get(
            "schema") != MODEL_ATTESTATION_OPEN_SCHEMA:
        raise DiagnosticError("opening attestation schema mismatch")
    head = doc.get("head_sha")
    if (not isinstance(head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", head)):
        raise DiagnosticError("opening attestation head is not a 40-hex sha")
    if expected_head is not None and head != expected_head:
        raise DiagnosticError(
            f"opening attestation binds head {head} != expected "
            f"{expected_head}")
    if doc.get("model_dir") != MODEL_DIR:
        raise DiagnosticError(
            f"opening attestation model dir mismatch: "
            f"{doc.get('model_dir')!r}")
    _validate_member_entries(doc)
    if doc.get("attestation_sha256") != attestation_canonical_digest(doc):
        raise DiagnosticError("opening attestation canonical digest mismatch")
    return doc


def validate_closing_attestation(doc: Any,
                                 opening: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed validation of the closing re-hash receipt."""
    if not isinstance(doc, dict) or doc.get(
            "schema") != MODEL_ATTESTATION_CLOSE_SCHEMA:
        raise DiagnosticError("closing attestation schema mismatch")
    if doc.get("opening_attestation_sha256") != opening.get(
            "attestation_sha256"):
        raise DiagnosticError(
            "closing attestation is not bound to the opening attestation")
    for key in ("head_sha", "model_dir"):
        if doc.get(key) != opening.get(key):
            raise DiagnosticError(
                f"closing attestation {key} differs from the opening")
    _validate_member_entries(doc)
    if doc.get("members") != opening.get("members"):
        raise DiagnosticError(
            "closing attestation members differ from the opening "
            "(digest or stat drift between open and close)")
    if doc.get("closing_sha256") != attestation_canonical_digest(doc):
        raise DiagnosticError("closing attestation canonical digest mismatch")
    return doc


def attestation_witness(model_dir: Path, attestation: dict[str, Any], *,
                        stat_observer=None
                        ) -> tuple[list[str], dict[str, Any] | None]:
    """Cheap fail-closed pre-unit identity check (no member byte reads).

    Re-observes the live topology/stats and compares every witnessed
    field against the opening attestation. Returns ``(problems,
    observed)``; non-empty problems mean STOP — a full re-hash (new
    campaign attestation) is required before any further execution.
    """
    validate_model_attestation(attestation)
    try:
        observed = (stat_observer or observe_model_stats)(model_dir)
    except DiagnosticError as exc:
        return [str(exc)], None
    problems: list[str] = []
    for member in attestation["members"]:
        name = member["name"]
        live = observed.get(name)
        if live is None:
            problems.append(f"{name}: missing from live model topology")
            continue
        for key in WITNESS_STAT_KEYS:
            if live.get(key) != member.get(key):
                problems.append(
                    f"{name}: {key} drift ({live.get(key)!r} != "
                    f"{member.get(key)!r})")
    witness = {m["name"]: {key: observed[m["name"]][key]
                           for key in WITNESS_STAT_KEYS}
               for m in attestation["members"]} if not problems else None
    return problems, witness


def verify_model_members(model_dir: Path,
                         hasher: Callable[[Path], str] = file_sha256
                         ) -> dict[str, str]:
    """Verify the COMPLETE accepted three-member GGUF set (correction 1).

    Requires all three expected member paths, rejects a missing member,
    rejects a wrong filename/path mapping, hashes every member
    independently, and compares every digest against the exact accepted
    #241 values. Returns the verified {member filename: sha256} map for
    binding into the unit receipt. No arbitrary caller-supplied model
    file can pass: the launched member-1 path is derived from
    ``model_dir`` + the frozen member filename, never accepted from the
    caller.
    """
    model_dir = Path(model_dir)
    if not model_dir.is_dir():
        raise DiagnosticError(
            f"model dir is not a directory: {model_dir}")
    present = sorted(p.name for p in model_dir.iterdir()
                     if p.suffix == ".gguf")
    expected = sorted(MODEL_MEMBERS)
    unexpected = sorted(set(present) - set(expected))
    if unexpected:
        raise DiagnosticError(
            f"unexpected split topology in {model_dir}: {unexpected}")
    verified: dict[str, str] = {}
    for member in MODEL_MEMBERS:
        path = model_dir / member
        if path.is_symlink() or not path.is_file():
            raise DiagnosticError(
                f"accepted model member missing: {path}")
        digest = hasher(path)
        if digest != MODEL_MEMBER_SHA256[member]:
            raise DiagnosticError(
                f"model member sha mismatch for {member}: {digest} != "
                f"{MODEL_MEMBER_SHA256[member]}")
        verified[member] = digest
    if set(verified) != set(MODEL_MEMBER_SHA256):
        raise DiagnosticError("model member map incomplete")
    return verified


def verify_fixtures(repo_root: Path) -> dict[str, Any]:
    """Load and sha-verify the accepted historical fixture ladder.

    Self-contained binding (same frozen ladder bytes as the #241
    campaign): the ladder document is read and hashed here; every
    diagnostic case entry must carry the expected shape.
    """
    path = Path(repo_root) / FIXTURE_LADDER_REL
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if digest != FIXTURE_LADDER_SHA256:
        raise DiagnosticError(
            f"fixture ladder sha drift: {digest} != {FIXTURE_LADDER_SHA256}")
    doc = json.loads(raw)
    cases = doc.get("cases")
    if not isinstance(cases, list):
        raise DiagnosticError("fixture ladder is not a case list")
    fixtures: dict[str, Any] = {}
    for entry in cases:
        case = entry.get("case_id")
        ids = entry.get("prompt_token_ids")
        if (not isinstance(case, str) or case in fixtures
                or not isinstance(ids, list) or len(ids) < 8
                or any(type(t) is not int for t in ids)
                or not isinstance(entry.get("prompt_text"), str)
                or not entry["prompt_text"]):
            raise DiagnosticError(f"fixture entry malformed: {case}")
        fixtures[case] = entry
    for case in DIAGNOSTIC_CASES + (CASE_4096,):
        if case not in fixtures:
            raise DiagnosticError(f"fixture case missing: {case}")
    return fixtures


def canonical_token_digest(tokens: list[int]) -> str:
    """Digest of the derived acceptance-bearing output (frozen form)."""
    if (not isinstance(tokens, list) or len(tokens) != DECISIONS
            or any(type(t) is not int or isinstance(t, bool) or t < 0
                   for t in tokens)):
        raise DiagnosticError(f"malformed token list: {tokens!r}")
    packed = CANONICAL_PACK.pack(*tokens)
    return sha256_bytes(packed)


def row_digest(row: bytes) -> str:
    if len(row) != ROW_BYTES:
        raise DiagnosticError(f"row length drift: {len(row)}")
    return sha256_bytes(row)


def judge_repeat_determinism(digests: list[str]) -> dict[str, Any]:
    """Determinism over independently computed digests only."""
    unique = sorted(set(digests))
    return {
        "repeat_count": len(digests),
        "deterministic": len(unique) == 1,
        "unique_digests": unique,
    }


def launch_env(arm: str, *, icd: str, selector: dict[str, str],
               observer: str, out_prefix: Path, force: list[int] | None,
               r8e_capture: bool = False) -> dict[str, str]:
    """Environment for one diagnostic server launch.

    observer modes:
      comparator — LLAMA_OBSERVE_CAPTURE=8 (r8i3 rows + forcing off for
                   arm B; forcing on for arm C when ``force`` given)
      r8e-only   — LLAMA_OBSERVE_LOGITS set with per-position capture,
                   comparator capture off (R8-E path only)
      off        — no observation env at all (inert patched binary)
    r8e_capture additionally enables the R8-E per-position row capture
    in the SAME process as the comparator observer (dual-capture
    discriminator: two independently coded capture paths, one process).
    """
    if observer not in ("comparator", "r8e-only", "off"):
        raise DiagnosticError(f"invalid observer mode: {observer}")
    env: dict[str, str] = {**selector, "VK_ICD_FILENAMES": icd,
                           "CUDA_VISIBLE_DEVICES": "-1"}
    if observer == "comparator":
        env["LLAMA_OBSERVE_CAPTURE"] = "8" if force is None else "8"
        env["LLAMA_OBSERVE_OUT"] = str(out_prefix)
        env["LLAMA_OBSERVE_FORCE"] = "" if force is None else ",".join(
            map(str, force))
    elif observer == "r8e-only":
        env["LLAMA_OBSERVE_LOGITS"] = str(out_prefix) + ".r8e.jsonl"
        env["LLAMA_OBSERVE_POS"] = "0"
    if r8e_capture and observer == "comparator":
        env["LLAMA_OBSERVE_LOGITS"] = str(out_prefix) + ".r8e.jsonl"
        env["LLAMA_OBSERVE_POS"] = "0"
    return env


def server_argv(binary: Path, model_member: Path, ngl: int, port: int,
                ctx_size: int = 8192, batch_size: int = 512) -> list[str]:
    """Exact accepted launch shape (one process per request unit)."""
    if ngl not in PLACEMENT_RUNGS:
        raise DiagnosticError(f"ngl outside frozen rungs: {ngl}")
    return [str(binary), "--model", str(model_member), "-ngl", str(ngl),
            "--ctx-size", str(ctx_size), "--batch-size", str(batch_size),
            "--host", "127.0.0.1", "--port", str(port)]


def validate_no_overlap_with_qualification(namespace: str) -> None:
    """The diagnostic namespace must not collide with qualification paths."""
    validate_namespace(namespace)
    if "phase3" in namespace or "campaign" in namespace:
        raise DiagnosticError(
            "diagnostic namespace must not shadow qualification namespaces")


# ---------------------------------------------------------------------------
# Phase-record helpers (offline reducers)
# ---------------------------------------------------------------------------

def collect_row_meta(unit_dir: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Collect r8i3 observer rows + meta from a unit directory."""
    rows: dict[str, bytes] = {}
    meta_raw = (unit_dir / "obs.meta.json").read_bytes()
    meta = [json.loads(line) for line in meta_raw.decode().splitlines()
            if line.strip()]
    for d in range(DECISIONS):
        rows[str(d)] = (unit_dir / f"obs.row{d}.f32").read_bytes()
    return rows, meta


def derive_unit_facts(unit_dir: Path) -> dict[str, Any]:
    """Derive the offline facts for one diagnostic unit from raw bytes."""
    rows, meta = collect_row_meta(unit_dir)
    facts = {
        "rows": {d: {"bytes": len(b), "sha256": row_digest(b)}
                 for d, b in rows.items()},
        "meta": meta,
        "winners": [m["sampled_winner"] for m in meta],
        "deterministic_output_sha256": canonical_token_digest(
            [m["sampled_winner"] for m in meta]),
    }
    resp_path = unit_dir / "response.json"
    if resp_path.is_file():
        resp = json.loads(resp_path.read_bytes())
        tokens = resp.get("tokens", resp.get("tokens_predicted"))
        facts["response_tokens"] = tokens
        facts["response_token_digest"] = canonical_token_digest(tokens)
    return facts


def r8e_captured_rows(unit_dir: Path) -> dict[int, bytes]:
    """Rows captured by the R8-E path (pos{N}.f32 files)."""
    out: dict[int, bytes] = {}
    for p in sorted(unit_dir.glob("*.pos*.f32")):
        if ".r8e" not in p.name:
            continue
        m = re.search(r"\.pos(\d+)\.f32$", p.name)
        if m:
            pos = int(m.group(1))
            # Keep duplicate handling aligned with issue248_terminal._population.
            if pos in out:
                raise DiagnosticError("duplicate r8e position")
            out[pos] = p.read_bytes()
    return out


def compare_units(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Offline comparison of two diagnostic units (row-level)."""
    problems: list[str] = []
    if a["winners"] != b["winners"]:
        problems.append("winner sequences differ")
    row_equal = {
        d: a["rows"][d]["sha256"] == b["rows"][d]["sha256"] for d in a["rows"]}
    return {
        "winners_equal": a["winners"] == b["winners"],
        "rows_byte_identical": all(row_equal.values()),
        "row_equal": row_equal,
        "problems": problems,
    }
