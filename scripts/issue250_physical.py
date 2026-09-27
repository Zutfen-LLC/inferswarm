#!/usr/bin/env python3
"""Issue #250 (R8-I3B) bounded physical diagnostic producer.

DIAGNOSTIC-ONLY. Correction pass 2 (maintainer NO-GO comment
5840630050, blocker 1): this module is the physical execution path
PR #251 previously lacked. It reuses the accepted Issue #248
producer architecture (scripts/issue248_physical.py) — same
authority/custody model, same raw identity/health helpers
(issue248_identity / issue248_health, the accepted implementations) —
adapted to Issue #250's frozen discriminator geometry
(scripts/issue250_diagnostic.py): four arms, namespace<->arm exact
binding, CPU-only inheritance for B and C, retained-byte terminal
reduction with the sequential A->B->C->D reachability law.

Every entrypoint gates FIRST and only then performs any work:
no qualification path exists here, comparator/2 methodology is
untouched, no threshold exists, no holdout access is possible, and
the diagnostic terminal is derived by the offline reducer from
retained bytes only.

Production path per unit (fresh-process units):

  live exact-head dispatch authority (early)
  -> namespace/arm exact binding
  -> frozen arm/unit plan membership
  -> exact clean local head
  -> fixture authority (ladder sha)
  -> campaign opening model attestation + per-unit stat witness
  -> accepted binary authority (sha256)
  -> frozen request contract
  -> fresh raw subject identity (pre)
  -> live exact-head dispatch authority (final; two-pass binding)
  -> physical launch (one fresh llama-server per unit)
  -> identity postcheck
  -> append-only raw custody (rows, response, log, health)
  -> unit receipt

Same-process Arm-B lifecycle (correction pass 2: five nominal unit
records launched as five separate processes do NOT satisfy Arm B):

  per-request authority revalidation + all fresh-unit gates
  -> ONE server launch (CPU-only `-dev none`)
  -> slot 3 pinned via id_slot request field
  -> 5 sequential requests to that SAME PID/runtime, each with
     cache_prompt=false full-recompute proof retained from the server
     log (slot-selected-by-id line, prompt-eval 3077-token line,
     graphs-reused count)
  -> per-request rows/responses/log slices retained
  -> ONE shared process identity (single PID bound to every request)
  -> teardown after the arm population

There is NO authority parameter anywhere: dispatch authority always
comes from a mandatory live fetch (tests inject
``revalidate_authority``; production resolves the real fetcher in
issue250_diagnostic-validated form below).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import base64
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import issue250_diagnostic as D
import issue248_health as H
import issue248_identity as I

UNIT_SCHEMA = "inferswarm.issue250.diagnostic-unit/1"
LIFECYCLE_SCHEMA = "inferswarm.issue250.same-process-lifecycle/1"
REDUCTION_SCHEMA = "inferswarm.issue250.diagnostic-reduction/2"
TERMINAL_SCHEMA = "inferswarm.issue250.terminal/1"
MODEL_ATTESTATION_OPEN_SCHEMA = (
    "inferswarm.issue250.model-attestation-open/1")
MODEL_ATTESTATION_CLOSE_SCHEMA = (
    "inferswarm.issue250.model-attestation-close/1")
MODEL_ATTESTATION_OPEN_NAME = "model-attestation-open.json"
MODEL_ATTESTATION_CLOSE_NAME = "model-attestation-close.json"
WITNESS_STAT_KEYS = ("bytes", "device", "inode", "mtime_ns", "ctime_ns")

PORT = 19000  # accepted arm-B reference port (unchanged)
ARM = "B"     # every #250 unit executes on the accepted reference arm
SERVER_CTX_SIZE = 8192
SERVER_BATCH_SIZE = 512
SERVER_READY_TIMEOUT_S = 1800
HTTP_TIMEOUT_S = 1200

# Same-process reset-evidence grammar. CORRECTION PASS 3: the old
# unanchored SLOT_BY_ID_RE / PROMPT_EVAL_RE (any slot-3 line + any
# 3077-token prompt-eval line anywhere in the slice) admitted delayed
# prior-task evidence; superseded by the task-bound state machine at
# SELECTION_BY_ID_RE / LAUNCH_TASK_RE / PROMPT_EVAL_TASK_RE below.
# Kept (unused by proofs) only for documentation continuity.
SLOT_BY_ID_RE = re.compile(
    r"slot get_availabl[^\n]*\bid\s+3\b[^\n]*selected slot by id")
PROMPT_EVAL_RE = re.compile(
    r"prompt eval time\s*=\s*[0-9.]+ ms\s*/\s*(\d+) tokens")


class PhysicalDiagnosticError(RuntimeError):
    pass


def _write_json(path: Path, doc: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Live dispatch authority (no cached authority can bypass live fetch)
# ---------------------------------------------------------------------------

def fetch_dispatch_authority(repo_root: Path, expected_head: str,
                             namespace: str,
                             github_api: str = "https://api.github.com",
                             ) -> dict[str, Any]:
    """Fetch and verify the live #250 dispatch comment (fail-closed).

    Mirrors the accepted #248 fetcher: GET-only, paginated, clean
    exact-head worktree, live PR state (OPEN, unmerged, base main,
    head == expected_head), live Issue #250 state (OPEN), OWNER/MEMBER
    top-level PR-conversation comment carrying the exact dispatch
    phrase / ``head=<sha>`` / one ``diagnostic-namespace=`` / one
    ``arm=`` stripped lines with the namespace<->arm pair exactly
    bound (issue250_diagnostic.NAMESPACE_ARM_BINDING).
    """
    D.validate_namespace(namespace)
    D._require_clean_head(Path(repo_root), expected_head)
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue250-diagnostic"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _get_json(path: str) -> Any:
        url = f"{github_api}/repos/Zutfen-LLC/inferswarm/{path}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())

    pr = _get_json(f"pulls/{D.DIAGNOSTIC_PR_NUMBER}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise D.DiagnosticError(
            f"PR #{D.DIAGNOSTIC_PR_NUMBER} is not open/unmerged "
            f"(state={pr.get('state')!r}, merged={pr.get('merged')!r})")
    if pr.get("base", {}).get("ref") != "main":
        raise D.DiagnosticError(
            f"PR #{D.DIAGNOSTIC_PR_NUMBER} base is not main: "
            f"{pr.get('base', {}).get('ref')!r}")
    if pr.get("head", {}).get("sha") != expected_head:
        raise D.DiagnosticError(
            f"GitHub PR head {pr.get('head', {}).get('sha')} != expected "
            f"{expected_head}")
    issue = _get_json(f"issues/{D.DIAGNOSTIC_ISSUE}")
    if issue.get("state") != "open":
        raise D.DiagnosticError(
            f"Issue #{D.DIAGNOSTIC_ISSUE} is not open "
            f"(state={issue.get('state')!r})")
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _get_json(
            f"issues/{D.DIAGNOSTIC_PR_NUMBER}/comments"
            f"?page={page}&per_page=100")
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 50:
            raise D.DiagnosticError("unbounded comment pagination")
    for comment in comments:
        if D.DIAGNOSTIC_DISPATCH_PHRASE not in str(comment.get("body")):
            continue
        # The arm line is parsed from the comment body; the exact
        # namespace<->arm pair is enforced by validate_authority_payload.
        body_lines = [ln.strip()
                      for ln in str(comment.get("body")).splitlines()]
        arms = [ln.split("=", 1)[1] for ln in body_lines
                if ln.startswith("arm=")]
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
            "arm": arms[0] if len(arms) == 1 else None,
        }
        try:
            return D.validate_authority_payload(authority, expected_head)
        except D.DiagnosticError:
            continue
    raise D.DiagnosticError(
        f"no valid dispatch authority for head {expected_head} "
        f"namespace {namespace}")


def require_live_dispatch(repo_root: Path, expected_head: str,
                          namespace: str,
                          revalidate_authority: Any = None,
                          github_api: str = "https://api.github.com",
                          ) -> dict[str, Any]:
    """MANDATORY live revalidation; omission never disables it."""
    if revalidate_authority is None:
        revalidate_authority = fetch_dispatch_authority
    authority = revalidate_authority(repo_root, expected_head, namespace,
                                     github_api)
    return D.validate_authority_payload(authority, expected_head)


# ---------------------------------------------------------------------------
# Fixtures, binaries, campaign model attestation (#248 architecture)
# ---------------------------------------------------------------------------

def verify_fixtures(repo_root: Path) -> dict[str, Any]:
    """Load and sha-verify the accepted historical fixture ladder."""
    path = Path(repo_root) / D.FIXTURE_LADDER_REL
    raw = path.read_bytes()
    digest = D.sha256_bytes(raw)
    if digest != D.FIXTURE_LADDER_SHA256:
        raise PhysicalDiagnosticError(
            f"fixture ladder sha drift: {digest} != {D.FIXTURE_LADDER_SHA256}")
    doc = json.loads(raw)
    cases = doc.get("cases")
    if not isinstance(cases, list):
        raise PhysicalDiagnosticError("fixture ladder is not a case list")
    fixtures: dict[str, Any] = {}
    for entry in cases:
        case = entry.get("case_id")
        ids = entry.get("prompt_token_ids")
        if (not isinstance(case, str) or case in fixtures
                or not isinstance(ids, list) or len(ids) < 8
                or any(type(t) is not int for t in ids)
                or not isinstance(entry.get("prompt_text"), str)
                or not entry["prompt_text"]):
            raise PhysicalDiagnosticError(f"fixture entry malformed: {case}")
        fixtures[case] = entry
    for case in ("case-256", "case-1024", "case-3072"):
        if case not in fixtures:
            raise PhysicalDiagnosticError(f"fixture case missing: {case}")
    return fixtures


def verify_binary(path: Path, binary_id: str) -> str:
    """Verify an executing binary is one of the accepted builds."""
    if binary_id not in D.SERVER_BINARIES:
        raise PhysicalDiagnosticError(f"unknown binary id: {binary_id}")
    digest = D.file_sha256(path)
    if digest != D.SERVER_BINARIES[binary_id]:
        raise PhysicalDiagnosticError(
            f"binary sha mismatch for {binary_id}: {digest}")
    return digest


def attestation_canonical_digest(doc: dict[str, Any]) -> str:
    payload = {key: value for key, value in doc.items()
               if key not in ("attestation_sha256", "closing_sha256")}
    return D.sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def observe_model_stats(model_dir: Path,
                        stat_fn: Callable[[Path], Any] | None = None,
                        ) -> dict[str, dict[str, Any]]:
    """Live per-member file-identity observation (lstat; no byte reads)."""
    import stat as stat_module
    stat_fn = stat_fn or os.lstat
    model_dir = Path(model_dir)
    if not model_dir.is_dir():
        raise D.DiagnosticError(
            f"model dir is not a directory: {model_dir}")
    present = sorted(p.name for p in model_dir.iterdir()
                     if p.suffix == ".gguf")
    if present != sorted(D.MODEL_MEMBERS):
        raise D.DiagnosticError(
            f"unexpected split topology in {model_dir}: {present}")
    out: dict[str, dict[str, Any]] = {}
    for member in D.MODEL_MEMBERS:
        path = model_dir / member
        info = stat_fn(path)
        mode = info.st_mode
        if stat_module.S_ISLNK(mode):
            raise D.DiagnosticError(f"model member is a symlink: {path}")
        if not stat_module.S_ISREG(mode):
            raise D.DiagnosticError(
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

    The single full ~72.5 GiB verification against the accepted #241
    digests, performed ONCE per campaign (Issue #250 efficiency rule).
    """
    hasher = hasher or D.file_sha256
    stats = (stat_observer or observe_model_stats)(model_dir)
    members = []
    for member in D.MODEL_MEMBERS:
        path = Path(model_dir) / member
        digest = hasher(path)
        if digest != D.MODEL_MEMBER_SHA256[member]:
            raise D.DiagnosticError(
                f"model member sha mismatch for {member}: {digest} != "
                f"{D.MODEL_MEMBER_SHA256[member]}")
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
    if (not isinstance(members, list) or len(members) != len(D.MODEL_MEMBERS)
            or any(not isinstance(m, dict) for m in members)):
        raise D.DiagnosticError("attestation member population malformed")
    names = sorted(m["name"] for m in members)
    if names != sorted(D.MODEL_MEMBERS) or len(set(names)) != len(names):
        raise D.DiagnosticError(
            "attestation member names do not match the accepted set")
    for member in members:
        name = member["name"]
        if member.get("path") != str(Path(doc["model_dir"]) / name):
            raise D.DiagnosticError(f"attestation path mismatch: {name}")
        if member.get("sha256") != D.MODEL_MEMBER_SHA256[name]:
            raise D.DiagnosticError(
                f"attestation digest is not the accepted value: {name}")
        if member.get("symlink") is not False or (
                member.get("regular_file") is not True):
            raise D.DiagnosticError(
                f"attestation file status malformed: {name}")
        for key in WITNESS_STAT_KEYS:
            if type(member.get(key)) is not int or member[key] < 0:
                raise D.DiagnosticError(
                    f"attestation witness field {key} malformed: {name}")


def validate_model_attestation(doc: Any,
                               expected_head: str | None = None,
                               ) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get(
            "schema") != MODEL_ATTESTATION_OPEN_SCHEMA:
        raise D.DiagnosticError("opening attestation schema mismatch")
    head = doc.get("head_sha")
    if (not isinstance(head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", head)):
        raise D.DiagnosticError("opening attestation head is not a 40-hex sha")
    if expected_head is not None and head != expected_head:
        raise D.DiagnosticError(
            f"opening attestation binds head {head} != expected "
            f"{expected_head}")
    if doc.get("model_dir") != D.MODEL_DIR:
        raise D.DiagnosticError(
            f"opening attestation model dir mismatch: "
            f"{doc.get('model_dir')!r}")
    _validate_member_entries(doc)
    if doc.get("attestation_sha256") != attestation_canonical_digest(doc):
        raise D.DiagnosticError("opening attestation canonical digest mismatch")
    return doc


def validate_closing_attestation(doc: Any,
                                 opening: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get(
            "schema") != MODEL_ATTESTATION_CLOSE_SCHEMA:
        raise D.DiagnosticError("closing attestation schema mismatch")
    if doc.get("opening_attestation_sha256") != opening.get(
            "attestation_sha256"):
        raise D.DiagnosticError(
            "closing attestation is not bound to the opening attestation")
    for key in ("head_sha", "model_dir"):
        if doc.get(key) != opening.get(key):
            raise D.DiagnosticError(
                f"closing attestation {key} differs from the opening")
    _validate_member_entries(doc)
    if doc.get("members") != opening.get("members"):
        raise D.DiagnosticError(
            "closing attestation members differ from the opening "
            "(digest or stat drift between open and close)")
    if doc.get("closing_sha256") != attestation_canonical_digest(doc):
        raise D.DiagnosticError("closing attestation canonical digest mismatch")
    return doc


def attestation_witness(model_dir: Path, attestation: dict[str, Any], *,
                        stat_observer=None
                        ) -> tuple[list[str], dict[str, Any] | None]:
    """Cheap fail-closed pre-unit identity check (no member byte reads)."""
    validate_model_attestation(attestation)
    try:
        observed = (stat_observer or observe_model_stats)(model_dir)
    except D.DiagnosticError as exc:
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


def open_campaign_attestation(evidence_root: Path, model_dir: Path,
                              expected_head: str,
                              hasher: Callable[[Path], str] | None = None,
                              ) -> dict[str, Any]:
    """Build and durably retain the campaign OPENING model attestation."""
    evidence_root = Path(evidence_root)
    doc = build_model_attestation(model_dir, expected_head,
                                  hasher=hasher or D.file_sha256)
    target = evidence_root / MODEL_ATTESTATION_OPEN_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"opening attestation already retained (append-only): {target}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    _write_json(target, doc)
    return doc


def close_campaign_attestation(evidence_root: Path, model_dir: Path,
                               expected_head: str,
                               hasher: Callable[[Path], str] | None = None,
                               ) -> dict[str, Any]:
    """Campaign closing full re-hash bound to the retained opening."""
    evidence_root = Path(evidence_root)
    opening_path = evidence_root / MODEL_ATTESTATION_OPEN_NAME
    if opening_path.is_symlink() or not opening_path.is_file():
        raise PhysicalDiagnosticError(
            "closing requires a retained opening attestation")
    opening = json.loads(opening_path.read_bytes())
    validate_model_attestation(opening, expected_head)
    fresh = build_model_attestation(model_dir, expected_head,
                                    hasher=hasher or D.file_sha256)
    doc = {key: value for key, value in fresh.items()
           if key != "attestation_sha256"}
    doc["schema"] = MODEL_ATTESTATION_CLOSE_SCHEMA
    doc["opening_attestation_sha256"] = opening["attestation_sha256"]
    doc["closing_sha256"] = attestation_canonical_digest(doc)
    validate_closing_attestation(doc, opening)
    target = evidence_root / MODEL_ATTESTATION_CLOSE_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"closing attestation already retained (append-only): {target}")
    _write_json(target, doc)
    return doc


# ---------------------------------------------------------------------------
# Arm-D ladder fixture derivation (frozen, predeclared)
# ---------------------------------------------------------------------------

def derive_ladder_prompt(base_prompt: str, length: int,
                         base_repeats: int) -> str:
    """Derive a ladder-length prompt by the accepted derivation rule.

    The accepted ladder fixtures are a frozen prologue + N repeats of
    one sentence block + a frozen suffix. A ladder prompt at length L
    uses the SAME prologue/suffix with the sentence repeat count from
    the frozen ARM_D_LADDER_SENTENCE_REPEATS table (predeclared in
    scripts/issue250_diagnostic.py before any execution; never picked
    after seeing outputs).

    CORRECTION PASS 3 (NO-GO 5847890177, blocker 4A): the old
    signature carried ``base_tokens`` but never used it, implying the
    nominal ladder label was a token length. It is not: the label is
    a TEXT GENERATION PARAMETER. The actual token count is derived
    separately through the pinned-server tokenizer authority
    (``tokenize_prompt`` / tokenizer receipts) and retained per unit.
    """
    if length not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError(
            f"length {length} is not in the predeclared ladder")
    if base_repeats <= 0:
        raise PhysicalDiagnosticError("malformed base fixture")
    return _scale_sentence_block(base_prompt, base_repeats,
                                 D.ARM_D_LADDER_SENTENCE_REPEATS[length])


def _scale_sentence_block(prompt: str, base_repeats: int,
                          target_repeats: int) -> str:
    if target_repeats == base_repeats:
        return prompt
    # The accepted sentence block (from the frozen ladder document):
    # "The lighthouse keeper counted forty-one waves before the foghorn
    #  answered twice. " repeated; prologue and suffix fixed.
    block = ("The lighthouse keeper counted forty-one waves before the "
             "foghorn answered twice. ")
    head = prompt[:prompt.index(block)]
    tail = prompt[prompt.rindex(block) + len(block):]
    if head + block * base_repeats + tail != prompt:
        raise PhysicalDiagnosticError(
            "base fixture is not a prologue+N-blocks+suffix shape")
    return head + block * target_repeats + tail


def ladder_token_authority_receipt(nominal_length: int,
                                   sentence_repeats: int,
                                   prompt_text: str,
                                   prompt_sha256: str,
                                   token_count: int,
                                   token_ids: list[int] | None = None,
                                   ) -> dict[str, Any]:
    """Build the per-ladder-length tokenizer-authority receipt.

    Binds: nominal ladder label (TEXT PARAMETER, not a token count),
    sentence-repeat count, prompt text digest, and the ACTUAL token
    count derived through the pinned tokenizer authority (server
    /tokenize receipt or authoritative fixture token ids). Retained
    append-only per unit; the reducer recomputes the digest binding.
    """
    if nominal_length not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError(
            f"nominal length {nominal_length} not in the frozen ladder")
    if sentence_repeats != D.ARM_D_LADDER_SENTENCE_REPEATS[
            nominal_length]:
        raise PhysicalDiagnosticError(
            f"sentence repeats {sentence_repeats} do not match the "
            f"frozen ladder entry for {nominal_length}")
    if (not isinstance(prompt_text, str) or not prompt_text
            or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256)
            or type(token_count) is not int or token_count <= 0):
        raise PhysicalDiagnosticError("malformed token authority inputs")
    if token_ids is not None and (not isinstance(token_ids, list)
                                  or len(token_ids) != token_count
                                  or any(type(t) is not int
                                         for t in token_ids)):
        raise PhysicalDiagnosticError(
            "token id population does not match the token count")
    return {
        "nominal_length": nominal_length,
        "sentence_repeats": sentence_repeats,
        "prompt_sha256": prompt_sha256,
        "actual_token_count": token_count,
        "token_ids_sha256": (
            D.sha256_bytes(
                json.dumps(token_ids, separators=(",", ":")).encode())
            if token_ids is not None else None),
        "token_ids": token_ids,
    }


def validate_ladder_token_authority(receipt: Any,
                                    prompt_text: str | None = None,
                                    ) -> dict[str, Any]:
    """Fail-closed validation of a retained token-authority receipt,
    recomputing the prompt-text digest when the prompt is supplied."""
    if not isinstance(receipt, dict):
        raise PhysicalDiagnosticError(
            "ladder token authority receipt is not an object")
    nominal = receipt.get("nominal_length")
    repeats = receipt.get("sentence_repeats")
    if nominal not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError("unknown nominal ladder length")
    if repeats != D.ARM_D_LADDER_SENTENCE_REPEATS[nominal]:
        raise PhysicalDiagnosticError(
            "token authority receipt does not match the frozen ladder")
    count = receipt.get("actual_token_count")
    if type(count) is not int or count <= 0:
        raise PhysicalDiagnosticError("actual token count malformed")
    sha = receipt.get("prompt_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise PhysicalDiagnosticError("prompt digest malformed")
    if prompt_text is not None and D.sha256_bytes(
            prompt_text.encode()) != sha:
        raise PhysicalDiagnosticError(
            "token authority receipt binds a different prompt text")
    ids = receipt.get("token_ids")
    if ids is not None:
        if (not isinstance(ids, list) or len(ids) != count
                or any(type(t) is not int for t in ids)):
            raise PhysicalDiagnosticError("token id population malformed")
        if receipt.get("token_ids_sha256") != D.sha256_bytes(
                json.dumps(ids, separators=(",", ":")).encode()):
            raise PhysicalDiagnosticError(
                "token id digest binding mismatch")
    elif receipt.get("token_ids_sha256") is not None:
        raise PhysicalDiagnosticError(
            "token id digest present without token ids")
    return dict(receipt)


LADDER_TOKEN_AUTHORITY_NAME = "ladder-token-authority.json"
LADDER_TOKEN_AUTHORITY_SCHEMA = (
    "inferswarm.issue250.ladder-token-authority/1")


def tokenize_prompt(port: int, prompt: str,
                    http_post: Callable[[str, bytes], Any] | None = None,
                    ) -> tuple[int, list[int]]:
    """Tokenize one prompt through a server's /tokenize endpoint.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 2): this helper is
    NO LONGER production token authority by itself — it blindly
    POSTs to ``http://127.0.0.1:<port>/tokenize`` with no proof that
    the listener is the accepted binary launched with the accepted
    model. Production tokenization goes through
    ``launch_tokenizer_server`` + ``_tokenize_via_attributed_server``
    which launch, attribute, and verify ONE dedicated pinned process
    (add_special defaults true server-side; parse_special true —
    mirroring the pinned /completion tokenize call at
    server-context.cpp:4579). Returns (token_count, token_ids).
    """
    if http_post is None:
        http_post = _http_json_post
    body = json.dumps({"content": prompt}).encode()
    doc = http_post(f"http://127.0.0.1:{port}/tokenize", body)
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if (not isinstance(tokens, list) or not tokens
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(
            f"malformed tokenize response: {str(doc)[:200]}")
    return len(tokens), list(tokens)


def _http_json_post(url: str, body: bytes) -> Any:
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"tokenize HTTP status {response.status}")
        return json.loads(response.read(16 * 1024 * 1024))


def _port_occupied(port: int) -> bool:
    """True when something is already listening on the loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


# Frozen tokenization-server launch geometry (correction pass 4,
# blocker 2): the dedicated tokenize-only process uses the EXACT
# accepted server geometry (same ctx/batch/host/port contract as the
# campaign launch shape) with NO observer hook — tokenization must
# not perturb or be perturbed by the observation seam, and it serves
# ONLY /tokenize requests (never /completion).
TOKENIZER_SERVER_CTX_SIZE = SERVER_CTX_SIZE
TOKENIZER_SERVER_BATCH_SIZE = SERVER_BATCH_SIZE
TOKENIZER_SERVER_PORT = PORT
TOKENIZER_SCHEMA = "inferswarm.issue250.token-authority-process/1"


def tokenizer_server_argv(binary: Path, model_member: Path,
                          port: int = TOKENIZER_SERVER_PORT,
                          ) -> list[str]:
    """FROZEN argv for the dedicated tokenize-only server process.

    Byte-identical geometry to the accepted campaign launch shape
    (--ctx-size 8192 --batch-size 512, host/port) with NO argv delta:
    no observer env, no thread regime, no placement change — the
    tokenizer authority must come from the accepted binary+model
    under the accepted launch shape.
    """
    return [str(binary), "--model", str(model_member),
            "-ngl", str(D.ACCEPTED_MATCHED_NGL),
            "--ctx-size", str(TOKENIZER_SERVER_CTX_SIZE),
            "--batch-size", str(TOKENIZER_SERVER_BATCH_SIZE),
            "--host", "127.0.0.1", "--port", str(port)]


def launch_tokenizer_server(
        binary: Path, binary_sha: str, model_dir: Path,
        model_member: Path, *, port: int = TOKENIZER_SERVER_PORT,
        spawn=None, wait_healthy: Callable[..., None] | None = None,
        port_occupied: Callable[[int], bool] | None = None,
        attribution_fn=None, log_dir: Path | None = None,
        ) -> dict[str, Any]:
    """Launch and MECHANICALLY ATTRIBUTE the tokenize-only server.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 2) — the production
    ladder-token authority producer. Steps (fail-closed at each):

    1. refuse a pre-existing unknown listener on the target port
       (fail closed; never silently reuse, never kill unrelated
       processes to obtain the port);
    2. launch ONE accepted llama-server process under the frozen
       tokenization geometry above (no observer hook env);
    3. wait for /health;
    4. capture PID + process attribution and verify
       ``/proc/<pid>/exe`` byte SHA == the accepted binary SHA (the
       listener is PROVEN to be the verified binary);
    5. bind argv to the exact accepted model member / model dir.

    Returns the process handle: ``{"proc", "attribution", "argv"}``.
    The caller MUST ``_stop_tokenizer_server`` the process in a
    finally block. ``spawn``/``wait_healthy``/``port_occupied``/
    ``attribution_fn`` are test seams; production omission resolves
    the real implementations.
    """
    if port_occupied is None:
        port_occupied = _port_occupied
    if spawn is None:
        spawn = _spawn_server
    if wait_healthy is None:
        wait_healthy = _wait_healthy
    if attribution_fn is None:
        attribution_fn = _proc_attribution
    # PRE-EXISTING PORT RULE: an unknown listener fails closed.
    if port_occupied(port):
        raise PhysicalDiagnosticError(
            f"port {port} is already occupied by an unknown process — "
            f"refusing to attribute token authority to an unverified "
            f"listener (no unrelated process is killed to obtain the "
            f"port)")
    argv = tokenizer_server_argv(Path(binary), Path(model_member),
                                 port=port)
    if log_dir is None:
        log_dir = Path(model_dir).parent / "tokenizer-authority"
    log_dir.mkdir(parents=True, exist_ok=True)
    proc = spawn(argv, log_dir / "tokenizer-server.log")
    try:
        wait_healthy(proc, port)
        attribution = attribution_fn(proc, argv, {})
        exe_sha = attribution.get("server_exe_sha256")
        if exe_sha != binary_sha:
            raise PhysicalDiagnosticError(
                f"tokenizer server executable SHA mismatch: {exe_sha} "
                f"!= accepted binary {binary_sha}")
        attribution["model_dir"] = str(Path(model_dir))
        attribution["model_launch_member"] = str(Path(model_member))
        attribution["argv"] = list(argv)
        return {"proc": proc, "attribution": attribution,
                "argv": argv}
    except BaseException:
        if proc.poll() is None:
            _terminate_process_group(proc)
        raise


def _spawn_server(argv: list[str], log_path: Path
                  ) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        argv, env=dict(os.environ), stdout=log_file,
        stderr=subprocess.STDOUT, start_new_session=True)
    return proc


def _terminate_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            proc.wait(timeout=5)


def _stop_tokenizer_server(handle: dict[str, Any]) -> None:
    """Teardown the dedicated tokenizer server process (always runs)."""
    proc = handle.get("proc")
    if proc is not None:
        _terminate_process_group(proc)


def _verify_tokenizer_process_still_attributed(
        handle: dict[str, Any], binary_sha: str) -> None:
    """Re-verify the live PID + executable mid-authority generation.

    The process answering the tokenize requests must STILL be the
    attributed process: PID alive, /proc/<pid>/exe SHA unchanged. A
    process replacement mid-generation fails closed (control 8).
    """
    proc = handle["proc"]
    attribution = handle["attribution"]
    if proc.poll() is not None:
        raise PhysicalDiagnosticError(
            f"tokenizer server exited mid-authority (rc="
            f"{proc.returncode})")
    try:
        exe = os.path.realpath(f"/proc/{proc.pid}/exe")
    except OSError as exc:
        raise PhysicalDiagnosticError(
            f"tokenizer server process vanished mid-authority "
            f"(pid {proc.pid}): {exc}") from exc
    if not Path(exe).exists():
        raise PhysicalDiagnosticError(
            f"tokenizer server process vanished mid-authority "
            f"(pid {proc.pid}): no /proc/{proc.pid}/exe")
    live_sha = D.file_sha256(Path(exe))
    if live_sha != binary_sha or live_sha != attribution[
            "server_exe_sha256"]:
        raise PhysicalDiagnosticError(
            f"tokenizer server process changed mid-authority: live "
            f"executable SHA {live_sha} != attributed "
            f"{attribution['server_exe_sha256']}")


def _tokenize_via_attributed_server(
        port: int, prompt: str, handle: dict[str, Any],
        binary_sha: str,
        http_post: Callable[[str, bytes], Any] | None = None,
        verify_alive: Callable[[dict[str, Any], str], None]
        | None = None,
        ) -> tuple[int, list[int], bytes, str]:
    """Tokenize ONE prompt through the attributed server process.

    Verifies the process attribution immediately before the request,
    issues ONLY a /tokenize POST, retains the RAW response bytes and
    their digest alongside the parsed token ids. Returns
    (count, ids, raw_bytes, raw_sha256).
    """
    if verify_alive is None:
        verify_alive = _verify_tokenizer_process_still_attributed
    verify_alive(handle, binary_sha)
    if http_post is None:
        http_post = _raw_json_post
    body = json.dumps({"content": prompt}).encode()
    raw, doc = http_post(f"http://127.0.0.1:{port}/tokenize", body)
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if (not isinstance(tokens, list) or not tokens
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(
            f"malformed tokenize response: {str(doc)[:200]}")
    return len(tokens), list(tokens), raw, D.sha256_bytes(raw)


def _raw_json_post(url: str, body: bytes) -> tuple[bytes, Any]:
    """POST returning (raw_bytes, decoded_json) — custody-grade."""
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"tokenize HTTP status {response.status}")
        raw = response.read(16 * 1024 * 1024)
    return raw, json.loads(raw)


def derive_ladder_token_authority(
        repo_root: Path, evidence_root: Path, expected_head: str,
        *, binary: Path, binary_id: str, model_dir: Path,
        attestation: dict[str, Any] | None = None,
        launch_server: Callable[..., dict[str, Any]] | None = None,
        stop_server: Callable[[dict[str, Any]], None] | None = None,
        verify_alive: Callable[[dict[str, Any], str], None]
        | None = None,
        tokenize: Callable[[str], tuple[int, list[int]]] | None = None,
        http_post: Callable[[str, bytes], Any] | None = None,
        ) -> dict[str, Any]:
    """Derive and retain the campaign ladder-token-authority document.

    CORRECTION PASS 3 (NO-GO 5847890177, blocker 4A): BEFORE any
    physical Arm-D execution, every predeclared ladder prompt is
    tokenized through the pinned tokenizer authority — the accepted
    comparator binary itself serving /tokenize (the same tokenizer the
    pinned /completion path uses). The document retains, per nominal
    ladder length: nominal label (TEXT PARAMETER), sentence-repeat
    count, prompt text digest, actual token ids (full population), and
    the actual token count. Append-only; regeneration is refused.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 2): the production
    path now LAUNCHES AND ATTRIBUTES the pinned server. The tokens
    are proven to come from ONE accepted llama-server process:
    exact clean head -> binary file verification -> accepted campaign
    model attestation binding -> model stat witness -> port free of
    unknown listeners -> ONE process launched under the frozen
    tokenization geometry -> healthy -> PID + /proc/<pid>/exe SHA ==
    accepted binary SHA -> argv bound to the accepted model member ->
    per-prompt re-attribution + /tokenize ONLY -> raw response bytes
    + digests retained -> teardown. ``tokenize`` is the TEST-ONLY
    injection seam (a bare callback returning ids produces
    NON-production authority — the retained document then names
    ``test_seam`` and the reducer rejects it for production use);
    production callers pass nothing.
    """
    repo_root = Path(repo_root)
    D._require_clean_head(repo_root, expected_head)
    fixtures = verify_fixtures(repo_root)
    binary_sha = verify_binary(Path(binary), binary_id)
    # Campaign model attestation binding: the tokenizer authority
    # must use the SAME accepted model bytes as the physical
    # campaign (accepted member digests + opening attestation digest
    # + live stat witness).
    if attestation is None:
        attestation = validate_model_attestation(
            _load_retained_attestation(evidence_root), expected_head)
    else:
        attestation = validate_model_attestation(attestation,
                                                 expected_head)
    witness_problems, stat_witness = attestation_witness(
        Path(model_dir), attestation)
    if witness_problems:
        raise PhysicalDiagnosticError(
            f"tokenizer-authority model stat witness drift: "
            f"{witness_problems}")
    if attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError(
            "attested model dir differs from the tokenizer model dir")
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1
    base = fixtures[D.CASE]
    lengths: dict[str, Any] = {}
    process_block: dict[str, Any] | None = None
    if tokenize is not None:
        # TEST SEAM ONLY — never production authority.
        for length in D.ARM_D_LADDER_LENGTHS:
            prompt = derive_ladder_prompt(
                base["prompt_text"], length, base["sentence_repeats"])
            count, ids = tokenize(prompt)
            lengths[str(length)] = ladder_token_authority_receipt(
                length, D.ARM_D_LADDER_SENTENCE_REPEATS[length], prompt,
                D.sha256_bytes(prompt.encode()), count, token_ids=ids)
        process_block = None
    else:
        launcher = launch_server or launch_tokenizer_server
        stopper = stop_server or _stop_tokenizer_server
        verifier = (verify_alive
                    or _verify_tokenizer_process_still_attributed)
        handle = launcher(Path(binary), binary_sha, Path(model_dir),
                          launch_member)
        try:
            for length in D.ARM_D_LADDER_LENGTHS:
                prompt = derive_ladder_prompt(
                    base["prompt_text"], length,
                    base["sentence_repeats"])
                count, ids, raw, raw_sha = _tokenize_via_attributed_server(
                    TOKENIZER_SERVER_PORT, prompt, handle, binary_sha,
                    http_post=http_post, verify_alive=verifier)
                receipt = ladder_token_authority_receipt(
                    length, D.ARM_D_LADDER_SENTENCE_REPEATS[length],
                    prompt, D.sha256_bytes(prompt.encode()), count,
                    token_ids=ids)
                receipt["tokenize_response_raw_sha256"] = raw_sha
                receipt["tokenize_response_bytes"] = len(raw)
                # retain the RAW response bytes themselves so the
                # reducer can re-verify the digest against content
                # (raw mutation control 9)
                receipt["tokenize_response_raw_b64"] = base64.b64encode(
                    raw).decode("ascii")
                lengths[str(length)] = receipt
            process_block = dict(handle["attribution"])
            process_block["schema"] = TOKENIZER_SCHEMA
            process_block["head_sha"] = expected_head
            process_block["binary_id"] = binary_id
            process_block["binary_sha256"] = binary_sha
            process_block["model_attestation_sha256"] = attestation[
                "attestation_sha256"]
            process_block["model_stat_witness"] = stat_witness
            process_block["tokenizer_semantics"] = {
                "same_accepted_model_bytes": True,
                "add_special": "server-default-true",
                "parse_special": True,
                "reference": ("pinned /completion tokenize call "
                              "(server-context.cpp:4579)"),
            }
        finally:
            stopper(handle)
    doc = {
        "schema": LADDER_TOKEN_AUTHORITY_SCHEMA,
        "head_sha": expected_head,
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "authority": ("attributed_pinned_server_tokenize_endpoint"
                      if process_block is not None else "test_seam"),
        "method": ("dedicated accepted-binary llama-server launched "
                   "under the frozen tokenization geometry, attributed "
                   "by PID + /proc/<pid>/exe SHA == accepted binary "
                   "SHA, serving ONLY /tokenize; add_special "
                   "server-default (true) + parse_special true — the "
                   "same tokenize call the pinned /completion path "
                   "makes (server-context.cpp:4579)"),
        "model_attestation_sha256": attestation[
            "attestation_sha256"],
        "process_attribution": process_block,
        "lengths": lengths,
    }
    root = Path(evidence_root)
    target = root / LADDER_TOKEN_AUTHORITY_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"ladder token authority already retained (append-only): "
            f"{target}")
    root.mkdir(parents=True, exist_ok=True)
    _write_json(target, doc)
    return doc


def _load_retained_attestation(evidence_root: Path) -> dict[str, Any]:
    """Load the retained campaign OPENING attestation (fail-closed)."""
    path = Path(evidence_root) / MODEL_ATTESTATION_OPEN_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError(
            f"campaign opening model attestation is not retained: "
            f"{path}")
    return json.loads(path.read_bytes())


def validate_token_authority_process_block(block: Any,
                                           expected_head: str,
                                           ) -> dict[str, Any]:
    """Fail-closed validation of the retained token-authority PROCESS
    ATTRIBUTION (correction pass 4, NO-GO 5851078451, blocker 2).

    Production token authority must be bound to the attributed
    pinned-server process: schema, exact head, binary id + SHA (the
    accepted digest), live server PID, executable SHA == the accepted
    binary SHA, the exact frozen argv (bound to the accepted model
    member + model dir), the opening model-attestation digest, the
    per-member stat witness, and the tokenizer-semantics declaration
    (same accepted model bytes; add_special/parse_special behavior).
    A document without this block is NOT production authority.
    """
    if not isinstance(block, dict):
        raise PhysicalDiagnosticError(
            "ladder token authority lacks process attribution — a "
            "synthetic/unattributed endpoint cannot produce "
            "production token authority")
    if block.get("schema") != TOKENIZER_SCHEMA:
        raise PhysicalDiagnosticError(
            "token-authority process attribution schema mismatch")
    if block.get("head_sha") != expected_head:
        raise PhysicalDiagnosticError(
            "token-authority process attribution binds a different head")
    pid = block.get("server_pid")
    if type(pid) is not int or pid <= 0:
        raise PhysicalDiagnosticError(
            "token-authority process attribution lacks a server PID")
    binary_id = block.get("binary_id")
    accepted = (D.SERVER_BINARIES.get(binary_id)
                if isinstance(binary_id, str) else None)
    if (not isinstance(binary_id, str) or accepted is None
            or block.get("binary_sha256") != accepted
            or block.get("server_exe_sha256") != accepted):
        raise PhysicalDiagnosticError(
            "token-authority process executable/binary binding "
            "mismatch (wrong binary id, binary SHA, or /proc/<pid>/exe "
            "SHA)")
    argv = block.get("argv")
    if (not isinstance(argv, list)
            or argv != tokenizer_server_argv(
                Path(argv[0]) if argv else Path(""),
                Path(str(block.get("model_launch_member"))))):
        raise PhysicalDiagnosticError(
            "token-authority process argv is not the frozen "
            "tokenization geometry bound to the accepted model member")
    if (block.get("model_launch_member")
            != str(Path(str(block.get("model_dir")))
                   / D.MODEL_MEMBER_1)):
        raise PhysicalDiagnosticError(
            "token-authority process model launch member mismatch")
    attestation_sha = block.get("model_attestation_sha256")
    if (not isinstance(attestation_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", attestation_sha)):
        raise PhysicalDiagnosticError(
            "token-authority process lacks the opening "
            "model-attestation digest")
    # (the doc-level digest binding to the retained campaign opening
    # is enforced by load_ladder_token_authority, which knows the
    # evidence root)
    witness = block.get("model_stat_witness")
    if (not isinstance(witness, dict)
            or sorted(witness) != sorted(D.MODEL_MEMBERS)):
        raise PhysicalDiagnosticError(
            "token-authority process stat witness population malformed")
    for member, fields in witness.items():
        if (not isinstance(fields, dict)
                or sorted(fields) != sorted(WITNESS_STAT_KEYS)
                or any(type(fields[k]) is not int for k in
                       WITNESS_STAT_KEYS)):
            raise PhysicalDiagnosticError(
                f"token-authority stat witness malformed: {member}")
    semantics = block.get("tokenizer_semantics")
    if (not isinstance(semantics, dict)
            or semantics.get("same_accepted_model_bytes") is not True
            or semantics.get("add_special") != "server-default-true"
            or semantics.get("parse_special") is not True):
        raise PhysicalDiagnosticError(
            "token-authority tokenizer semantics declaration malformed")
    return block


def load_ladder_token_authority(evidence_root: Path,
                                expected_head: str) -> dict[str, Any]:
    """Load and fail-closed validate the retained token authority."""
    path = Path(evidence_root) / LADDER_TOKEN_AUTHORITY_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError(
            f"retained ladder token authority missing: {path}")
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict) or doc.get(
            "schema") != LADDER_TOKEN_AUTHORITY_SCHEMA:
        raise PhysicalDiagnosticError(
            "ladder token authority schema mismatch")
    if doc.get("head_sha") != expected_head:
        raise PhysicalDiagnosticError(
            "ladder token authority binds a different head")
    binary_id = doc.get("binary_id")
    if not isinstance(binary_id, str) or doc.get(
            "binary_sha256") != D.SERVER_BINARIES.get(binary_id):
        raise PhysicalDiagnosticError(
            "ladder token authority binary binding mismatch")
    # CORRECTION PASS 4 (blocker 2): production authority REQUIRES the
    # attributed pinned-server process block (a synthetic HTTP
    # endpoint alone — or a test-seam document — is rejected).
    if doc.get("authority") != (
            "attributed_pinned_server_tokenize_endpoint"):
        raise PhysicalDiagnosticError(
            "ladder token authority is not bound to an attributed "
            "pinned-server tokenize process")
    block = doc.get("process_attribution")
    validate_token_authority_process_block(block, expected_head)
    doc_sha = doc.get("model_attestation_sha256")
    if (not isinstance(doc_sha, str)
            or block.get("model_attestation_sha256") != doc_sha):
        raise PhysicalDiagnosticError(
            "token-authority doc/process-block attestation digest "
            "binding mismatch")
    opening_path = Path(evidence_root) / MODEL_ATTESTATION_OPEN_NAME
    if opening_path.is_file():
        opening = json.loads(opening_path.read_bytes())
        if (opening.get("attestation_sha256") != doc_sha
                or opening.get("schema") != MODEL_ATTESTATION_OPEN_SCHEMA
                or opening.get("head_sha") != expected_head):
            raise PhysicalDiagnosticError(
                "token-authority attestation digest does not match "
                "the retained campaign opening")
    lengths = doc.get("lengths")
    if (not isinstance(lengths, dict)
            or sorted(lengths) != sorted(
                str(n) for n in D.ARM_D_LADDER_LENGTHS)):
        raise PhysicalDiagnosticError(
            "ladder token authority does not cover exactly the frozen "
            "ladder lengths")
    for key, entry in lengths.items():
        validate_ladder_token_authority(entry)
        if entry["nominal_length"] != int(key):
            raise PhysicalDiagnosticError(
                "ladder token authority key/entry mismatch")
        raw_sha = entry.get("tokenize_response_raw_sha256")
        if (not isinstance(raw_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", raw_sha)
                or type(entry.get("tokenize_response_bytes")) is not int
                or entry["tokenize_response_bytes"] <= 0):
            raise PhysicalDiagnosticError(
                "ladder token authority entry lacks the raw tokenize "
                "response digest/size binding")
        raw_b64 = entry.get("tokenize_response_raw_b64")
        if not isinstance(raw_b64, str):
            raise PhysicalDiagnosticError(
                "ladder token authority entry lacks the retained raw "
                "tokenize response bytes")
        try:
            raw_bytes = base64.b64decode(raw_b64, validate=True)
        except Exception:
            raise PhysicalDiagnosticError(
                "ladder token authority raw response bytes are not "
                "valid base64") from None
        if (len(raw_bytes) != entry["tokenize_response_bytes"]
                or D.sha256_bytes(raw_bytes) != raw_sha):
            raise PhysicalDiagnosticError(
                "ladder token authority raw response bytes do not "
                "match the retained digest/size (mutation detected)")
        ids = entry.get("token_ids")
        if (not isinstance(ids, list) or len(ids) == 0
                or any(type(t) is not int for t in ids)
                or json.loads(raw_bytes).get("tokens") != ids):
            raise PhysicalDiagnosticError(
                "ladder token authority token ids do not match the "
                "retained raw tokenize response (mutation detected)")
        if entry.get("actual_token_count") != len(ids):
            raise PhysicalDiagnosticError(
                "ladder token authority count does not match the "
                "retained token id population (mutation detected)")
    return doc


def validate_ladder_token_authority_entry(entry: Any,
                                          prompt_text: str) -> dict[str, Any]:
    """Validate one retained entry against the exact prompt text the
    unit will send (digest recompute — prompt mutation is fatal)."""
    return validate_ladder_token_authority(entry, prompt_text)


# ---------------------------------------------------------------------------
# Server launch geometry (exact accepted shape + the one arm factor)
# ---------------------------------------------------------------------------

def server_argv(binary: Path, model_member: Path, unit: dict[str, Any],
                port: int = PORT) -> list[str]:
    """Exact accepted launch shape with the unit's declared argv delta.

    Base shape is byte-identical to the accepted #248 producer
    (--ctx-size 8192 --batch-size 512, -ngl placement, host/port); the
    unit's frozen ``argv_delta`` appends exactly the one declared
    factor tokens (e.g. ``-dev none``, ``-t 1 -tb 1``). Arm D ladder
    units run at the accepted placement (length is the factor).
    """
    delta = tuple(unit.get("argv_delta", ()))
    if unit.get("ladder_length"):
        if delta:
            raise PhysicalDiagnosticError(
                "ladder units cannot carry an argv delta")
        ngl = D.ACCEPTED_MATCHED_NGL
    else:
        ngl = int(unit["ngl"])
        if ngl != 0:
            raise PhysicalDiagnosticError(
                f"#250 non-ladder units are CPU-only (-dev none); "
                f"ngl={ngl} is not a #250 current-unit condition")
    argv = [str(binary), "--model", str(model_member), "-ngl", str(ngl),
            "--ctx-size", str(SERVER_CTX_SIZE),
            "--batch-size", str(SERVER_BATCH_SIZE),
            "--host", "127.0.0.1", "--port", str(port)]
    argv.extend(delta)
    return argv


def launch_env(out_prefix: Path) -> dict[str, str]:
    """Environment for one #250 server launch (accepted observer env)."""
    identity = I.frozen_identity(ARM)
    env = {**identity["selector"], "VK_ICD_FILENAMES": identity["icd"],
           "CUDA_VISIBLE_DEVICES": "-1",
           "LLAMA_OBSERVE_CAPTURE": "8",
           "LLAMA_OBSERVE_OUT": str(out_prefix),
           "LLAMA_OBSERVE_FORCE": ""}
    return env


# ---------------------------------------------------------------------------
# Unit directories (append-only; quarantine-before-rerun)
# ---------------------------------------------------------------------------

def prepare_unit_dir(root: Path, namespace: str, tag: str) -> Path:
    """Create (or refuse to replace) the append-only unit directory."""
    base = D.namespace_dir(root, namespace)
    base.mkdir(parents=True, exist_ok=True)
    unit = base / tag
    if unit.exists() or unit.is_symlink():
        raise D.DiagnosticError(
            f"existing diagnostic unit cannot be replaced: {unit}. "
            f"Move it to a -quarantined sibling first (append-only custody).")
    unit.mkdir()
    return unit


def quarantine_unit(root: Path, namespace: str, tag: str) -> Path:
    """Move a failed/superseded unit aside; never overwrite in place."""
    base = D.namespace_dir(root, namespace)
    unit = base / tag
    if not unit.is_dir():
        raise D.DiagnosticError(f"unit to quarantine does not exist: {unit}")
    target = base / f"{tag}-quarantined"
    if target.exists():
        raise D.DiagnosticError(f"quarantine target already exists: {target}")
    unit.rename(target)
    return target


# ---------------------------------------------------------------------------
# Raw observation helpers (device samples; injectable runner seams)
# ---------------------------------------------------------------------------

def _device_sample() -> dict[str, Any]:
    """One residency/telemetry sample (same seam as accepted #248)."""
    sample: dict[str, Any] = {
        "stage": None, "captured_at": _utcnow(), "residency_mib": {}}
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15).stdout
    for line in smi.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) == 2:
            sample["residency_mib"]["00000000:03:00.0"] = int(fields[1])
    telemetry = subprocess.run(
        ["nvidia-smi", f"--query-gpu={H.NVIDIA_QUERY}",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15)
    if telemetry.returncode != 0 or not telemetry.stdout:
        raise PhysicalDiagnosticError(
            "in-window NVIDIA telemetry unavailable")
    sample["nvidia_smi_raw"] = telemetry.stdout
    return sample


def _http_completion(port: int, request: dict[str, Any],
                     prompt: str) -> tuple[bytes, dict[str, Any]]:
    payload = json.dumps({**request, "prompt": prompt}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/completion", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"completion HTTP status {response.status}")
        raw = response.read(1024 * 1024)
    return raw, json.loads(raw)


def _wait_healthy(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + SERVER_READY_TIMEOUT_S
    ready = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise PhysicalDiagnosticError(
                f"server exited early rc={proc.returncode}")
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    if not ready:
        raise PhysicalDiagnosticError("server never became healthy")


def _proc_attribution(proc: subprocess.Popen, argv: list[str],
                      env: dict[str, str]) -> dict[str, Any]:
    exe = os.path.realpath(f"/proc/{proc.pid}/exe")
    return {
        "server_pid": proc.pid,
        "server_exe_sha256": D.file_sha256(Path(exe)),
        "server_argv": list(argv),
        "server_env": dict(env),
    }


def _observe_arm_identity() -> dict[str, Any]:
    """Raw device identity observation (accepted #248 seam)."""
    return I.observe_arm_identity(ARM)


# ---------------------------------------------------------------------------
# Physical execution (one fresh process per unit)
# ---------------------------------------------------------------------------

def _real_execute(argv: list[str], env: dict[str, str],
                  request: dict[str, Any], prompt: str, port: int,
                  unit_dir: Path) -> dict[str, Any]:
    """Launch one fresh server process; issue one completion; tear down."""
    samples = [_device_sample() | {"stage": "before"}]
    full_env = {**os.environ, **env}
    log_path = unit_dir / "server.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            argv, env=full_env, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True)
        attribution: dict[str, Any] = {}
        try:
            _wait_healthy(proc, port)
            attribution = _proc_attribution(proc, argv, env)
            stop = threading.Event()
            errors: list[Exception] = []

            def sample_loop() -> None:
                while not stop.is_set():
                    try:
                        samples.append(_device_sample() | {"stage": "during"})
                    except Exception as exc:  # pragma: no cover
                        errors.append(exc)
                        return
                    time.sleep(2.0)

            samples.append(_device_sample() | {"stage": "during"})
            thread = threading.Thread(target=sample_loop, daemon=True)
            thread.start()
            try:
                raw, response = _http_completion(port, request, prompt)
            finally:
                stop.set()
                thread.join(timeout=2)
            if errors:
                raise PhysicalDiagnosticError(
                    "device sampling failed") from errors[0]
            samples.append(_device_sample() | {"stage": "after"})
            tokens = response.get("tokens", response.get("tokens_predicted"))
            return {"returncode": proc.poll(),
                    "tokens": tokens, "response_raw": raw,
                    "process_attribution": attribution,
                    "device_samples": samples}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)


def _collect_rows(unit_dir: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Collect r8i3 observer rows + meta from a unit directory."""
    rows: dict[str, bytes] = {}
    meta_raw = (unit_dir / "obs.meta.json").read_bytes()
    meta = [json.loads(line) for line in meta_raw.decode().splitlines()
            if line.strip()]
    for d in range(D.DECISIONS):
        rows[str(d)] = (unit_dir / f"obs.row{d}.f32").read_bytes()
    return rows, meta


def run_diagnostic_unit(
    repo_root: Path, evidence_root: Path, namespace: str, arm: str,
    tag: str, *, binary: Path, binary_id: str,
    model_dir: Path, expected_head: str,
    model_attestation: dict[str, Any],
    execute: Callable[..., dict[str, Any]] | None = None,
    identity_observer: Callable[[], dict[str, Any]] | None = None,
    revalidate_authority: Callable[..., dict[str, Any]] | None = None,
    request_contract: dict[str, Any] | None = None,
    health_runner: Callable[..., Any] = H._run_readonly,
    github_api: str = "https://api.github.com",
) -> dict[str, Any]:
    """Execute ONE fresh-process diagnostic unit under full gating.

    GATE ORDER (fail fast, all before any launch):
      namespace<->arm exact binding -> EARLY live dispatch authority ->
      frozen plan membership (arm + tag) -> exact clean local head ->
      fixture authority -> campaign model attestation + stat witness ->
      binary identity -> request contract -> subject identity (pre) ->
      prelaunch custody -> FINAL live dispatch authority (two-pass
      binding + clean head re-check) -> physical launch.

    ``execute``/``identity_observer``/``revalidate_authority``/
    ``health_runner`` are injectable test seams; production resolves
    the real implementations. There is NO authority parameter.
    """
    repo_root = Path(repo_root).resolve(strict=True)
    # Namespace<->arm exact binding (blocker 5) FIRST.
    D.validate_namespace_arm_binding(namespace, arm)
    plan = D.probe_list_for(arm)
    tags = [u["tag"] for u in plan]
    if tag not in tags:
        raise PhysicalDiagnosticError(
            f"unit {tag!r} is not in the frozen plan for arm {arm}")
    unit = next(u for u in plan if u["tag"] == tag)
    if unit.get("same_process"):
        raise PhysicalDiagnosticError(
            "same-process units run through run_same_process_lifecycle; "
            "the fresh-process unit path cannot satisfy Arm B arm-2")
    authority_early = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    if authority_early.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "live dispatch arm does not match the executing arm")
    D._require_clean_head(repo_root, expected_head)
    fixtures = verify_fixtures(repo_root)
    binary_sha = verify_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation,
                                             expected_head)
    retained_opening_path = (Path(evidence_root)
                             / MODEL_ATTESTATION_OPEN_NAME)
    if (retained_opening_path.is_symlink()
            or not retained_opening_path.is_file()):
        raise PhysicalDiagnosticError(
            "campaign opening model attestation is not retained in the "
            f"evidence root: {retained_opening_path}")
    retained_opening = json.loads(retained_opening_path.read_bytes())
    if attestation != retained_opening:
        raise PhysicalDiagnosticError(
            "unit attestation differs from the retained campaign opening")
    witness_problems, stat_witness = attestation_witness(
        Path(model_dir), attestation)
    if witness_problems:
        raise PhysicalDiagnosticError(
            "model stat witness drift — full re-hash required before "
            f"further execution: {witness_problems}")
    if attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError(
            "attested model dir differs from the launched model dir")
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1

    if unit.get("ladder_length"):
        length = unit["ladder_length"]
        base = fixtures[D.CASE]
        prompt = derive_ladder_prompt(
            base["prompt_text"], length, base["sentence_repeats"])
        prompt_token_ids = None  # ladder token ids live in the authority
        # CORRECTION PASS 3 (blocker 4A): the ACTUAL token count comes
        # from the retained campaign ladder-token-authority document,
        # derived BEFORE physical Arm-D execution through the pinned
        # tokenizer (see derive_ladder_token_authority). No ladder unit
        # can execute without it — a nominal label is never a token
        # count.
        authority_doc = load_ladder_token_authority(
            evidence_root, expected_head)
        entry = authority_doc["lengths"].get(str(length))
        if entry is None:
            raise PhysicalDiagnosticError(
                f"retained ladder token authority does not cover "
                f"nominal length {length}")
        validate_ladder_token_authority_entry(entry, prompt)
        token_authority = entry
    else:
        prompt = fixtures[D.CASE]["prompt_text"]
        prompt_token_ids = fixtures[D.CASE]["prompt_token_ids"]
        token_authority = None

    unit_dir = prepare_unit_dir(evidence_root, namespace, tag)

    identity_pre = (identity_observer or _observe_arm_identity)()
    problems_pre = I.identity_problems(ARM, identity_pre)
    if problems_pre:
        _write_json(unit_dir / "identity-pre.json", identity_pre)
        raise PhysicalDiagnosticError(
            f"pre-launch identity drift: {problems_pre}")

    if unit.get("request") == "arm-b":
        raise PhysicalDiagnosticError(
            "arm-b contract extension is same-process only")
    request = D.validate_request_contract(
        request_contract if request_contract is not None
        else D.REQUEST_CONTRACT)

    out_prefix = unit_dir / "obs"
    env = launch_env(out_prefix)
    argv = server_argv(Path(binary), launch_member, unit)

    # FINAL GOVERNANCE GATE: second live fetch bound to the first;
    # remote drift between preflight and launch => zero runner calls.
    authority_late = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    final_authority = D.bind_authority_observations(
        authority_early, authority_late)
    if final_authority.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "final live dispatch arm does not match the executing arm")
    D._require_clean_head(repo_root, expected_head)

    unit_started_at = _utcnow()
    started = time.monotonic()
    runner = execute or _real_execute
    result = runner(argv=argv, env=env, request=request,
                    prompt=prompt, port=PORT, unit_dir=unit_dir)
    wall = time.monotonic() - started
    unit_ended_at = _utcnow()

    return _finalize_unit_receipt(
        unit_dir=unit_dir, tag=tag, namespace=namespace, arm=arm,
        unit=unit, result=result, request=request, argv=argv, env=env,
        binary_id=binary_id, binary_sha=binary_sha,
        attestation=attestation, stat_witness=stat_witness,
        model_dir=model_dir, launch_member=launch_member,
        prompt=prompt, prompt_token_ids=prompt_token_ids,
        identity_pre=identity_pre, identity_observer=identity_observer,
        problems_pre=problems_pre, final_authority=final_authority,
        unit_started_at=unit_started_at, unit_ended_at=unit_ended_at,
        wall=wall, health_runner=health_runner,
        token_authority=token_authority)


def _finalize_unit_receipt(*, unit_dir, tag, namespace, arm, unit, result,
                           request, argv, env, binary_id, binary_sha,
                           attestation, stat_witness, model_dir,
                           launch_member, prompt, prompt_token_ids,
                           identity_pre, identity_observer, problems_pre,
                           final_authority, unit_started_at, unit_ended_at,
                           wall, health_runner,
                           same_process_block=None,
                           token_authority=None) -> dict[str, Any]:
    """Post-execution custody: identity postcheck, rows, health, receipt."""
    identity_post = (identity_observer or _observe_arm_identity)()
    problems_post = I.identity_problems(ARM, identity_post)
    _write_json(unit_dir / "identity-pre.json", identity_pre)
    _write_json(unit_dir / "identity-post.json", identity_post)
    if problems_post:
        raise PhysicalDiagnosticError(
            f"post-execution identity drift: {problems_post}")

    tokens = result.get("tokens")
    if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(f"{tag}: malformed token output")
    (unit_dir / "response.json.raw").write_bytes(result["response_raw"])

    device_samples = result.get("device_samples")
    if not isinstance(device_samples, list):
        raise PhysicalDiagnosticError("execution returned no device samples")
    health_receipt = H.capture_platform_health(
        unit_dir, unit_started_at, unit_ended_at,
        samples=device_samples, runner=health_runner)
    verified_health = H.verify_platform_health(
        unit_dir, health_receipt,
        expected_gpu_uuid=I.REFERENCE_IDENTITY["gpu_uuid"],
        expected_bdf=I.frozen_identity(ARM)["bdf"],
        expected_arm=ARM)
    if not verified_health["valid"]:
        raise PhysicalDiagnosticError(
            f"retained platform health invalid: "
            f"{verified_health['problems']}")

    receipt: dict[str, Any] = {
        "schema": UNIT_SCHEMA,
        "kind": "diagnostic-unit",
        "namespace": namespace,
        "arm_id": arm,
        "tag": tag,
        "case_id": D.CASE,
        "arm": ARM,
        "unit": {k: (list(v) if isinstance(v, tuple) else v)
                 for k, v in unit.items()},
        "ngl": unit["ngl"],
        "argv_delta": list(unit.get("argv_delta", ())),
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "model_dir": str(model_dir),
        "model_attestation_sha256": attestation["attestation_sha256"],
        "model_stat_witness": stat_witness,
        "model_launch_member": str(launch_member),
        "request_contract": request,
        "request_contract_sha256": D.canonical_request_digest(request),
        "prompt_len": len(prompt),
        "prompt_token_ids": prompt_token_ids,
        "prompt_sha256": D.sha256_bytes(prompt.encode()),
        "ladder_token_authority": token_authority,
        "server_argv": argv,
        "server_env": {k: env[k] for k in sorted(env)
                       if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
        "process_attribution": result.get("process_attribution"),
        "platform_health": health_receipt,
        "platform_health_receipt": {
            "path": "platform-health-receipt.json",
            "bytes": len((unit_dir / "platform-health-receipt.json")
                         .read_bytes()),
            "sha256": D.file_sha256(
                unit_dir / "platform-health-receipt.json"),
            "window": {"start": unit_started_at, "end": unit_ended_at},
        },
        "tokens": tokens,
        "response_raw_sha256": D.sha256_bytes(result["response_raw"]),
        "deterministic_output_sha256": D.canonical_token_digest(tokens),
        "identity_problems_pre": problems_pre,
        "identity_problems_post": problems_post,
        "subject_identity_schema": I.IDENTITY_SCHEMA,
        "authority": unit_authority_block(final_authority),
        "wall_time_s": wall,
    }
    meta_path = unit_dir / "obs.meta.json"
    if meta_path.is_file():
        rows, metadata = _collect_rows(unit_dir)
        if (len(metadata) != D.DECISIONS
                or any(not isinstance(m, dict) or m.get("pos") != i
                       for i, m in enumerate(metadata))):
            raise PhysicalDiagnosticError("observer meta population malformed")
        receipt["observer_rows"] = [D.row_digest(rows[str(i)])
                                    for i in range(D.DECISIONS)]
        receipt["observer_meta_sha256"] = D.file_sha256(meta_path)
    else:
        raise PhysicalDiagnosticError(
            "required full-row capture missing (observer seam)")
    if same_process_block is not None:
        receipt["same_process"] = same_process_block
    _write_json(unit_dir / "unit.json", receipt)
    return receipt


def unit_authority_block(final_authority: dict[str, Any]) -> dict[str, Any]:
    """Canonical per-unit dispatch-authority block (receipt binding)."""
    if not isinstance(final_authority, dict):
        raise D.DiagnosticError("final authority must be a dict")
    return {
        "comment_id": final_authority["comment_id"],
        "head_sha": final_authority["head_sha"],
        "namespace": final_authority["namespace"],
        "arm": final_authority["arm"],
        "created_at": final_authority["created_at"],
        "author_association": final_authority["author_association"],
        "pr_number": D.DIAGNOSTIC_PR_NUMBER,
        "issue_number": D.DIAGNOSTIC_ISSUE,
        "dispatch_sha256": D.authority_digest(final_authority),
    }


# ---------------------------------------------------------------------------
# Same-process Arm-B lifecycle (correction pass 2: one process, five
# equivalent requests, reset semantics proven per request).
#
# CORRECTION PASS 3 (NO-GO 5847890177, blockers 1+3):
#   * authority is revalidated LIVE before EACH completion request
#     (not only before the launch) and cross-bound to the original
#     dispatch generation;
#   * the reset proof is bound to the CURRENT request's task identity
#     through the pinned server's ACTUAL log grammar.
#
# Pinned grammar (llama.cpp b29c606e, server-common.h SLT_INF prefix
# ``slot %12s: id %2d | task %d |``; verified against the retained
# #248 evidence logs):
#   selection : "slot get_availabl: id  3 | task -1 | selected slot
#                by id (3)"          (slot.task is unset during
#               get_available_slot -> the task field is STRUCTURALLY
#               -1 here; task identity therefore comes from the
#               launch line, not the selection line)
#   launch    : "slot launch_slot_: id  3 | task 7 | processing task,
#                is_child = 0"
#   timing    : "slot print_timing: id  3 | task 7 | prompt eval time
#                =  48215.02 ms /  3077 tokens (...)"
# Every request consumes a fresh task id from the server's monotonic
# counter (server-queue.cpp get_new_id: ``id++``; /health consumes no
# task id, but NEXT_RESPONSE/control tasks may — task ids are NOT
# assumed equal to request indexes). The proof is therefore a
# REQUEST-DELIMITED LOG STATE MACHINE: selection-by-id(slot 3) ->
# launch(slot 3, task N, processing task) -> prompt-eval(slot 3,
# task N, EXACTLY the expected token count), with N fresh w.r.t. all
# task ids consumed by earlier requests of the SAME lifecycle.
# ---------------------------------------------------------------------------

_SLOT_LINE = r"slot\s+[^\s:]+:\s*id\s+{id}\s*\|\s*task\s*(-?\d+)\s*\|"


def _slot_line_re(slot_id: int) -> re.Pattern[str]:
    return re.compile(_SLOT_LINE.format(id=slot_id))


SELECTION_BY_ID_RE = re.compile(
    r"slot\s+get_availabl:[^\n]*\bid\s+3\b[^\n]*task\s+-1\b[^\n]*"
    r"selected slot by id\s*\(3\)")
# a non-by-id selection (LRU/LCP) mentioning slot 3 must NOT satisfy
# the selected-by-id requirement
SELECTION_NOT_BY_ID_RE = re.compile(
    r"slot\s+get_availabl:[^\n]*\bid\s+3\b[^\n]*"
    r"selected slot by (?!id)")
LAUNCH_TASK_RE = re.compile(
    _SLOT_LINE.format(id=3).replace("(-?\\d+)", "(-?\\d+)") +
    r"[^\n]*processing task")
PROMPT_EVAL_TASK_RE = re.compile(
    r"slot\s+[^\s:]+:\s*id\s+3\s*\|\s*task\s+(\d+)\s*\|[^\n]*"
    r"prompt eval time\s*=\s*[0-9.]+ ms\s*/\s*(\d+)\s*tokens")


def _parse_slot_log(text: str, request_index: int,
                    expected_prompt_tokens: int,
                    consumed_task_ids: frozenset[int] | set[int] = frozenset(),
                    ) -> dict[str, Any]:
    """Prove reset semantics for one same-process request from the
    retained server-log slice, BOUND to the current request's task.

    Fail-closed requirements (all must hold):
      1. the LAST selection line for slot 3 in the slice selects BY
         ID (an LRU/LCP selection is fatal);
      2. after that selection, slot 3 launches EXACTLY ONE task N
         ("processing task");
      3. a prompt-eval line for slot 3 | task N covers EXACTLY
         ``expected_prompt_tokens`` (full recompute; a smaller count
         is cache reuse and is fatal);
      4. task N is FRESH: not among ``consumed_task_ids`` (the task
         ids proven by earlier requests of this lifecycle) — delayed
         evidence from request N-1 carries request N-1's task id and
         CANNOT certify request N;
      5. exactly one fresh task boundary exists (two unseen task ids
         is ambiguous -> fail closed).

    Returns the mechanically parsed task id and evidence; raises
    nothing (callers check ``proven``).
    """
    consumed = set(consumed_task_ids)
    selection_matches = list(SELECTION_BY_ID_RE.finditer(text))
    lru_matches = list(SELECTION_NOT_BY_ID_RE.finditer(text))
    last_selection_end = (
        selection_matches[-1].end() if selection_matches else -1)
    # a non-by-id selection AFTER the last by-id selection means the
    # slot was re-selected without id pinning (fatal); before it, an
    # earlier request's LRU line is historical noise only if a later
    # by-id selection exists for the fresh task
    late_lru = [m for m in lru_matches if m.start() > last_selection_end]
    launches = [(m.start(), int(m.group(1)))
                for m in LAUNCH_TASK_RE.finditer(text)
                if m.start() > last_selection_end]
    evals = [(m.start(), int(m.group(1)), int(m.group(2)))
             for m in PROMPT_EVAL_TASK_RE.finditer(text)]
    fresh_launches = [(pos, tid) for pos, tid in launches
                      if tid not in consumed]
    problems: list[str] = []
    if not selection_matches:
        problems.append("no slot-3 selected-by-id line in slice")
    if late_lru:
        problems.append("slot 3 selected by LRU/LCP after the by-id "
                        "selection")
    if not fresh_launches:
        problems.append(
            "no launch of a FRESH task on slot 3 after the by-id "
            "selection (delayed prior-task evidence cannot certify "
            "this request)")
    if len({tid for _, tid in fresh_launches}) > 1:
        problems.append("multiple conflicting fresh task boundaries")
    task_id: int | None = None
    prompt_eval_tokens: int | None = None
    if fresh_launches:
        task_id = fresh_launches[-1][1]
        task_evals = [n for _, tid, n in evals if tid == task_id]
        if not task_evals:
            problems.append(
                f"no prompt-eval line for the current task {task_id}")
        else:
            prompt_eval_tokens = task_evals[-1]
            if prompt_eval_tokens != expected_prompt_tokens:
                problems.append(
                    f"prompt eval covers {prompt_eval_tokens} tokens != "
                    f"expected {expected_prompt_tokens} (cache reuse or "
                    f"wrong-task evidence)")
        prior_evals = sorted({tid for _, tid, _ in evals
                              if tid in consumed})
        if prior_evals:
            problems.append(
                f"slice carries delayed prompt-eval evidence of prior "
                f"tasks {prior_evals}")
    proven = not problems
    return {
        "request_index": request_index,
        "task_id": task_id,
        "slot_selected_by_id": bool(selection_matches) and not late_lru,
        "launch_proven": bool(fresh_launches),
        "prompt_eval_tokens": prompt_eval_tokens,
        "full_recompute_proven": (
            proven and prompt_eval_tokens == expected_prompt_tokens),
        "consumed_prior_task_ids": sorted(consumed),
        "problems": problems,
        "proven": proven,
    }


def _validate_reset_proof(proof: dict[str, Any], index: int) -> int:
    """Fail-closed check of one parsed reset proof; returns task id."""
    if (not isinstance(proof, dict) or not proof.get("proven")
            or proof.get("request_index") != index
            or type(proof.get("task_id")) is not int
            or not proof.get("slot_selected_by_id")
            or not proof.get("launch_proven")
            or not proof.get("full_recompute_proven")):
        detail = (proof.get("problems") if isinstance(proof, dict)
                  else "malformed proof")
        raise PhysicalDiagnosticError(
            f"same-process request {index} lacks a task-bound reset "
            f"proof (slot-by-id + fresh-task launch + full prompt "
            f"recompute): {detail}")
    return proof["task_id"]


def run_same_process_lifecycle(
    repo_root: Path, evidence_root: Path, namespace: str, arm: str,
    tag_prefix: str, *, binary: Path, binary_id: str,
    model_dir: Path, expected_head: str,
    model_attestation: dict[str, Any],
    execute: Callable[..., dict[str, Any]] | None = None,
    identity_observer: Callable[[], dict[str, Any]] | None = None,
    revalidate_authority: Callable[..., dict[str, Any]] | None = None,
    health_runner: Callable[..., Any] = H._run_readonly,
    github_api: str = "https://api.github.com",
) -> dict[str, Any]:
    """Execute the Arm-B same-process population under full gating.

    ONE server launch (CPU-only `-dev none`), slot 3 pinned via the
    frozen ``id_slot: 3`` request extension, five sequential equivalent
    requests to the SAME PID/runtime, each with reset semantics proven
    from the retained log slice, per-request rows/responses retained,
    one shared process identity bound to every request, teardown after
    the arm population. Five separate processes would NOT satisfy
    Arm B and are structurally impossible here.

    CORRECTION PASS 3 (NO-GO 5847890177, blocker 1): authority is
    revalidated LIVE immediately before EACH completion request —
    not only before the launch — through the canonical fetch path,
    and every per-request observation must cross-bind to the SAME
    original dispatch generation (same comment id/head/namespace/arm/
    author association/created-at/body digest). A drift at request N
    stops the lifecycle BEFORE request N issues: already-completed
    request evidence stays retained (append-only), the lifecycle is
    marked incomplete (fail-closed), and no later request executes.
    The ``preflight_request`` callback is the ONLY mechanism by which
    the runner may request a gate check; the runner itself never
    fetches authority and cannot bypass the gate.
    """
    repo_root = Path(repo_root).resolve(strict=True)
    D.validate_namespace_arm_binding(namespace, arm)
    if arm != "B-process-init":
        raise PhysicalDiagnosticError(
            "same-process lifecycle is an Arm-B population only")
    plan = D.probe_list_for(arm)
    same_units = [u for u in plan if u.get("same_process")
                  and u["tag"].startswith(tag_prefix)]
    if len(same_units) != D.DETERM_MIN_REPEATS:
        raise PhysicalDiagnosticError(
            f"same-process population is frozen at "
            f"{D.DETERM_MIN_REPEATS} requests, plan lists {len(same_units)}")

    # Per-request live authority revalidation (blocker 1): every
    # completion request begins under CURRENT authority, cross-bound
    # to the original dispatch generation. CORRECTION PASS 4 (NO-GO
    # 5851078451, blocker 1) mechanically separates four concepts that
    # pass 3 conflated: gate ATTEMPTS (every gate call, including the
    # one that fails), SUCCESSFUL authority observations, COMPLETED
    # requests, and the FAILED gate index. A failed gate attempt never
    # corresponds to a completed request; the accounting below must
    # hold for BOTH shapes so an authority-drift prefix is retained
    # durably instead of raising before custody is written.
    request_authorities: list[dict[str, Any]] = []
    request_gate_attempts: list[int] = []
    request_gate_failed_index: int | None = None
    generation_anchor: dict[str, Any] | None = None

    def _request_gate(index: int) -> None:
        request_gate_attempts.append(index)
        try:
            payload = require_live_dispatch(
                repo_root, expected_head, namespace,
                revalidate_authority=revalidate_authority,
                github_api=github_api)
            if payload.get("arm") != arm:
                raise PhysicalDiagnosticError(
                    f"per-request authority at request {index} binds arm "
                    f"{payload.get('arm')!r} != {arm!r}")
            D._require_clean_head(repo_root, expected_head)
            nonlocal generation_anchor, request_gate_failed_index
            if generation_anchor is None:
                generation_anchor = payload
            else:
                # cross-bind EVERY observation to the original generation
                D.bind_authority_observations(generation_anchor, payload)
            request_authorities.append(dict(payload))
        except BaseException:
            if request_gate_failed_index is None:
                request_gate_failed_index = index
            raise

    authority_early = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    if authority_early.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "live dispatch arm does not match the executing arm")
    generation_anchor = dict(authority_early)
    D._require_clean_head(repo_root, expected_head)
    fixtures = verify_fixtures(repo_root)
    binary_sha = verify_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation,
                                             expected_head)
    retained_opening_path = (Path(evidence_root)
                             / MODEL_ATTESTATION_OPEN_NAME)
    if (retained_opening_path.is_symlink()
            or not retained_opening_path.is_file()):
        raise PhysicalDiagnosticError(
            "campaign opening model attestation is not retained")
    retained_opening = json.loads(retained_opening_path.read_bytes())
    if attestation != retained_opening:
        raise PhysicalDiagnosticError(
            "lifecycle attestation differs from the retained campaign "
            "opening")
    witness_problems, stat_witness = attestation_witness(
        Path(model_dir), attestation)
    if witness_problems:
        raise PhysicalDiagnosticError(
            f"model stat witness drift: {witness_problems}")
    if attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError(
            "attested model dir differs from the launched model dir")
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1
    prompt = fixtures[D.CASE]["prompt_text"]
    expected_prompt_tokens = len(fixtures[D.CASE]["prompt_token_ids"])
    request = D.validate_request_contract(
        dict(D.ARM_B_CONTRACT), extra_keys=frozenset({"id_slot"}))

    lifecycle_dir = D.namespace_dir(evidence_root, namespace) / (
        tag_prefix + "-lifecycle")
    if lifecycle_dir.exists() or lifecycle_dir.is_symlink():
        raise D.DiagnosticError(
            f"existing lifecycle directory cannot be replaced: "
            f"{lifecycle_dir}")
    lifecycle_dir.mkdir(parents=True)

    identity_pre = (identity_observer or _observe_arm_identity)()
    problems_pre = I.identity_problems(ARM, identity_pre)
    if problems_pre:
        _write_json(lifecycle_dir / "identity-pre.json", identity_pre)
        raise PhysicalDiagnosticError(
            f"pre-launch identity drift: {problems_pre}")

    out_prefix = lifecycle_dir / "obs"
    env = launch_env(out_prefix)
    unit = same_units[0]
    argv = server_argv(Path(binary), launch_member, unit)

    # FINAL live governance gate before the single launch.
    authority_late = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    final_authority = D.bind_authority_observations(
        authority_early, authority_late)
    if final_authority.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "final live dispatch arm does not match the executing arm")
    D._require_clean_head(repo_root, expected_head)

    started_at = _utcnow()
    started = time.monotonic()
    runner = execute or _real_same_process_execute
    result = runner(argv=argv, env=env, request=request, prompt=prompt,
                    port=PORT, unit_dir=lifecycle_dir,
                    repeats=D.DETERM_MIN_REPEATS,
                    expected_prompt_tokens=expected_prompt_tokens,
                    preflight_request=_request_gate)
    wall = time.monotonic() - started
    ended_at = _utcnow()

    # ---- custody + fail-closed lifecycle verification ----
    shared_pid = result.get("server_pid")
    if type(shared_pid) is not int or shared_pid <= 0:
        raise PhysicalDiagnosticError("lifecycle carried no server PID")
    per_request = result.get("requests")
    if not isinstance(per_request, list):
        raise PhysicalDiagnosticError(
            "same-process lifecycle returned no request records")
    stop_kind = result.get("stop_kind", "completed_all")
    stop_reason = result.get("stop_reason")
    if stop_kind not in ("completed_all", "truncated", "mismatch_stop"):
        raise PhysicalDiagnosticError(
            f"lifecycle stop kind malformed: {stop_kind!r}")
    truncated = stop_kind == "truncated"
    mismatch_stop = stop_kind == "mismatch_stop"
    # CORRECTION PASS 4 (NO-GO 5851078451, blocker 1): a drift/proof
    # failure truncates the lifecycle — the COMPLETED PREFIX IS
    # RETAINED AND FINALIZED append-only (per-request unit
    # directories, receipts, shared identity/health custody, and the
    # lifecycle record), and the lifecycle is marked INCOMPLETE
    # (fail-closed; the reducer never treats an authority-truncated
    # prefix as a terminal-complete population). A MISMATCH STOP is
    # the frozen early-stop law firing: the retained prefix is a
    # COMPLETE nondeterministic population. Authority gate
    # accounting: ATTEMPTS are every gate invocation (a failed
    # attempt corresponds to NO completed request), successful
    # OBSERVATIONS correspond 1:1 with completed requests. The
    # runner's preflight hook is the only gate mechanism; the
    # recorded attempts prove no request was issued without a gate
    # call, and the failed index is the attempt that fired last.
    if request_gate_attempts:
        # monotone, no duplicates, contiguous from 0
        if (request_gate_attempts
                != list(range(len(request_gate_attempts)))):
            raise PhysicalDiagnosticError(
                f"per-request authority gate attempts are not a "
                f"contiguous request sequence (attempts: "
                f"{request_gate_attempts})")
        last_attempt = request_gate_attempts[-1]
        if len(per_request) not in (last_attempt, last_attempt + 1):
            raise PhysicalDiagnosticError(
                f"per-request authority gate accounting mismatch: "
                f"{len(per_request)} completed requests vs last gate "
                f"attempt {last_attempt} — no request may complete "
                f"without a preceding gate call, and at most the "
                f"gate-failing request may be absent")
        if len(request_authorities) != len(per_request):
            raise PhysicalDiagnosticError(
                "per-request authority observation count mismatch")
        if truncated and request_gate_failed_index is not None:
            if len(per_request) != request_gate_failed_index:
                raise PhysicalDiagnosticError(
                    f"truncated lifecycle retained {len(per_request)} "
                    f"requests but the authority gate failed at index "
                    f"{request_gate_failed_index} — the failed gate "
                    f"must correspond to the first unexecuted request")
        elif truncated and request_gate_failed_index is None:
            # truncation without a gate failure: the runner reported a
            # reset-proof/process truncation. No failed gate index is
            # recorded; the stop_reason carries the cause.
            pass
    else:
        # zero gate attempts: the runner never invoked the preflight
        # hook — no request may exist (an unfenced request path is
        # a producer defect, not a lifecycle shape).
        if per_request:
            raise PhysicalDiagnosticError(
                "same-process runner issued requests without any "
                "authority gate attempt (preflight hook bypassed)")
        if len(request_authorities) != 0:
            raise PhysicalDiagnosticError(
                "per-request authority observation count mismatch")
    request_records = []
    consumed_task_ids: set[int] = set()
    for index, record in enumerate(per_request):
        for field in ("tokens", "response_raw", "log_slice",
                      "row_files", "meta_file", "reset_proof"):
            if field not in record:
                raise PhysicalDiagnosticError(
                    f"same-process request {index} missing {field}")
        if record.get("server_pid") != shared_pid:
            raise PhysicalDiagnosticError(
                f"same-process request {index} executed on a different "
                f"PID ({record.get('server_pid')!r} != {shared_pid}); "
                "PID changes mid-arm are fatal")
        # task-bound reset proof (blocker 3): re-derive from the
        # retained log slice with the consumed-task set; the runner's
        # own proof must agree exactly.
        rederived = _parse_slot_log(
            record["log_slice"].decode("utf-8", errors="replace"),
            index, expected_prompt_tokens,
            consumed_task_ids=frozenset(consumed_task_ids))
        proof = record["reset_proof"]
        if (not isinstance(proof, dict)
                or proof.get("task_id") != rederived["task_id"]
                or not rederived["proven"]):
            raise PhysicalDiagnosticError(
                f"same-process request {index} lacks a task-bound reset "
                f"proof (slot-by-id + fresh-task launch + full prompt "
                f"recompute): {rederived['problems']}")
        task_id = _validate_reset_proof(rederived, index)
        consumed_task_ids.add(task_id)
        tokens = record["tokens"]
        if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
                or any(type(t) is not int for t in tokens)):
            raise PhysicalDiagnosticError(
                f"same-process request {index} malformed tokens")
        # request-history drift: every request's contract must be the
        # frozen Arm-B contract (no drift across the sequence)
        contract = record.get("request_contract")
        if contract != D.ARM_B_CONTRACT:
            raise PhysicalDiagnosticError(
                f"same-process request {index} contract drift")
        # per-request authority receipt binding (blocker 1): the
        # observation CURRENT at this request, with its digest.
        authority_receipt = unit_authority_block(request_authorities[index])
        if authority_receipt["dispatch_sha256"] != D.authority_digest(
                request_authorities[index]):
            raise PhysicalDiagnosticError(
                f"same-process request {index} authority receipt digest "
                "mismatch")
        record["_authority"] = authority_receipt
        record["_reset_proof_verified"] = rederived
        request_records.append(record)

    # Retain per-request custody under each planned tag.
    for record, unit_spec in zip(request_records, same_units):
        tag = unit_spec["tag"]
        unit_dir = prepare_unit_dir(evidence_root, namespace, tag)
        for name, data in record["row_files"].items():
            (unit_dir / name).write_bytes(data)
        (unit_dir / "obs.meta.json").write_bytes(record["meta_file"])
        (unit_dir / "response.json.raw").write_bytes(record["response_raw"])
        (unit_dir / "server.log").write_bytes(record["log_slice"])
        _write_json(unit_dir / "identity-pre.json", identity_pre)

    identity_post = (identity_observer or _observe_arm_identity)()
    problems_post = I.identity_problems(ARM, identity_post)
    _write_json(lifecycle_dir / "identity-pre.json", identity_pre)
    _write_json(lifecycle_dir / "identity-post.json", identity_post)
    if problems_post:
        raise PhysicalDiagnosticError(
            f"post-execution identity drift: {problems_post}")

    samples = result.get("device_samples")
    if not isinstance(samples, list):
        raise PhysicalDiagnosticError("lifecycle returned no samples")
    health_receipt = H.capture_platform_health(
        lifecycle_dir, started_at, ended_at,
        samples=samples, runner=health_runner)
    verified_health = H.verify_platform_health(
        lifecycle_dir, health_receipt,
        expected_gpu_uuid=I.REFERENCE_IDENTITY["gpu_uuid"],
        expected_bdf=I.frozen_identity(ARM)["bdf"],
        expected_arm=ARM)
    if not verified_health["valid"]:
        raise PhysicalDiagnosticError(
            f"retained platform health invalid: "
            f"{verified_health['problems']}")

    # Per-tag receipts bind the shared lifecycle identity.
    receipts = []
    for record, unit_spec in zip(request_records, same_units):
        tag = unit_spec["tag"]
        unit_dir = D.namespace_dir(evidence_root, namespace) / tag
        tokens = record["tokens"]
        rows, metadata = _collect_rows(unit_dir)
        if (len(metadata) != D.DECISIONS
                or any(not isinstance(m, dict) or m.get("pos") != i
                       for i, m in enumerate(metadata))):
            raise PhysicalDiagnosticError(
                "same-process observer meta population malformed")
        receipt = {
            "schema": UNIT_SCHEMA,
            "kind": "same-process-request",
            "namespace": namespace,
            "arm_id": arm,
            "tag": tag,
            "case_id": D.CASE,
            "arm": ARM,
            "unit": {k: (list(v) if isinstance(v, tuple) else v)
                     for k, v in unit_spec.items()},
            "ngl": unit_spec["ngl"],
            "argv_delta": list(unit_spec.get("argv_delta", ())),
            "binary_id": binary_id,
            "binary_sha256": binary_sha,
            "model_dir": str(model_dir),
            "model_attestation_sha256": attestation["attestation_sha256"],
            "model_stat_witness": stat_witness,
            "model_launch_member": str(launch_member),
            "request_contract": D.ARM_B_CONTRACT,
            "request_contract_sha256": D.canonical_request_digest(
                D.ARM_B_CONTRACT),
            "prompt_len": len(prompt),
            "prompt_token_ids": fixtures[D.CASE]["prompt_token_ids"],
            "server_argv": argv,
            "server_env": {k: env[k] for k in sorted(env)
                           if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
            "process_attribution": result.get("process_attribution"),
            "platform_health": health_receipt,
            "platform_health_receipt": {
                "path": "../" + tag_prefix + "-lifecycle/"
                        "platform-health-receipt.json",
                "bytes": len((lifecycle_dir /
                              "platform-health-receipt.json").read_bytes()),
                "sha256": D.file_sha256(
                    lifecycle_dir / "platform-health-receipt.json"),
                "window": {"start": started_at, "end": ended_at},
            },
            "tokens": tokens,
            "response_raw_sha256": D.sha256_bytes(record["response_raw"]),
            "deterministic_output_sha256": D.canonical_token_digest(tokens),
            "identity_problems_pre": problems_pre,
            "identity_problems_post": problems_post,
            "subject_identity_schema": I.IDENTITY_SCHEMA,
            "authority": record["_authority"],
            "wall_time_s": wall,
            "same_process": {
                "lifecycle_schema": LIFECYCLE_SCHEMA,
                "shared_server_pid": shared_pid,
                "request_index": record["reset_proof"]["request_index"],
                "reset_proof": record["reset_proof"],
                "lifecycle_dir": lifecycle_dir.name,
            },
        }
        receipt["observer_rows"] = [D.row_digest(rows[str(i)])
                                    for i in range(D.DECISIONS)]
        receipt["observer_meta_sha256"] = D.file_sha256(
            unit_dir / "obs.meta.json")
        _write_json(unit_dir / "unit.json", receipt)
        receipts.append(receipt)

    lifecycle_doc = {
        "schema": LIFECYCLE_SCHEMA,
        "namespace": namespace,
        "arm_id": arm,
        "tag_prefix": tag_prefix,
        "shared_server_pid": shared_pid,
        "process_attribution": result.get("process_attribution"),
        "request_count": len(request_records),
        "planned_request_count": D.DETERM_MIN_REPEATS,
        # complete == the lifecycle answered its question: either
        # all planned requests executed (completed_all) or the frozen
        # early-stop law fired on a mechanically derived mismatch
        # (mismatch_stop). An authority/process truncation is an
        # INCOMPLETE population (blocker 1).
        "complete": stop_kind in ("completed_all", "mismatch_stop"),
        "stop_kind": stop_kind,
        "stop_reason": stop_reason,
        # CORRECTION PASS 4 (NO-GO 5851078451, blocker 1): the
        # truncated-lifecycle schema mechanically states the authority
        # accounting — attempted gate calls, successful observations,
        # and (for authority drift) the FAILED gate index, which has
        # no corresponding completed request by construction.
        "gate_attempt_count": len(request_gate_attempts),
        "successful_gate_count": len(request_authorities),
        "failed_gate_index": request_gate_failed_index if truncated
        else None,
        "reset_proofs": [r["reset_proof"] for r in request_records],
        "verified_reset_proofs": [r["_reset_proof_verified"]
                                  for r in request_records],
        "per_request_authorities": [r["_authority"]
                                    for r in request_records],
        "platform_health": health_receipt,
        "identity_problems_pre": problems_pre,
        "identity_problems_post": problems_post,
        "authority": unit_authority_block(final_authority),
        "wall_time_s": wall,
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "model_attestation_sha256": attestation["attestation_sha256"],
        "model_stat_witness": stat_witness,
        "server_argv": argv,
        "server_env": {k: env[k] for k in sorted(env)
                       if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
        "request_contract": D.ARM_B_CONTRACT,
        "request_contract_sha256": D.canonical_request_digest(
            D.ARM_B_CONTRACT),
    }
    _write_json(lifecycle_dir / "lifecycle.json", lifecycle_doc)
    return {"lifecycle": lifecycle_doc, "receipts": receipts}


def _real_same_process_execute(
        argv: list[str], env: dict[str, str], request: dict[str, Any],
        prompt: str, port: int, unit_dir: Path, repeats: int,
        expected_prompt_tokens: int,
        preflight_request: Callable[[int], None] | None = None,
        ) -> dict[str, Any]:
    """ONE server launch; ``repeats`` sequential requests; teardown.

    CORRECTION PASS 3 (blocker 1): before EVERY completion request the
    producer calls ``preflight_request(index)`` — the lifecycle's live
    authority revalidation seam. A gate failure raises before the HTTP
    completion is issued; the server is torn down and no later request
    executes (fail-closed mid-lifecycle stop).
    """
    samples = [_device_sample() | {"stage": "before"}]
    full_env = {**os.environ, **env}
    log_path = unit_dir / "server.log.full"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            argv, env=full_env, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True)
        try:
            _wait_healthy(proc, port)
            attribution = _proc_attribution(proc, argv, env)
            stop = threading.Event()
            errors: list[Exception] = []

            def sample_loop() -> None:
                while not stop.is_set():
                    try:
                        samples.append(
                            _device_sample() | {"stage": "during"})
                    except Exception as exc:  # pragma: no cover
                        errors.append(exc)
                        return
                    time.sleep(2.0)

            samples.append(_device_sample() | {"stage": "during"})
            thread = threading.Thread(target=sample_loop, daemon=True)
            thread.start()
            records = []
            consumed_task_ids: set[int] = set()
            stop_kind = "completed_all"
            stop_reason: str | None = None
            baseline_rows: list[str] | None = None
            try:
                for index in range(repeats):
                    # LIVE authority gate BEFORE the HTTP completion
                    # (blocker 1); a drift retains the completed prefix
                    # and stops here (fail-closed truncation).
                    if preflight_request is not None:
                        try:
                            preflight_request(index)
                        except Exception as exc:
                            stop_kind = "truncated"
                            stop_reason = (
                                f"authority-revalidation failure before "
                                f"request {index}: {exc}")
                            break
                    offset_before = log_path.stat().st_size
                    raw, response = _http_completion(port, request, prompt)
                    time.sleep(0.2)  # let the slot log flush
                    with log_path.open("rb") as stream:
                        stream.seek(offset_before)
                        log_slice = stream.read()
                    tokens = response.get(
                        "tokens", response.get("tokens_predicted"))
                    proof = _parse_slot_log(
                        log_slice.decode("utf-8", errors="replace"),
                        index, expected_prompt_tokens,
                        consumed_task_ids=frozenset(consumed_task_ids))
                    if not proof["proven"]:
                        stop_kind = "truncated"
                        stop_reason = (
                            f"reset-proof failure at request {index}: "
                            f"{proof['problems']}")
                        break
                    consumed_task_ids.add(proof["task_id"])
                    row_files = {}
                    for d in range(D.DECISIONS):
                        name = f"obs.row{d}.f32"
                        row_files[name] = (unit_dir / name).read_bytes()
                    meta_file = (unit_dir / "obs.meta.json").read_bytes()
                    records.append({
                        "server_pid": proc.pid,
                        "tokens": tokens,
                        "response_raw": raw,
                        "log_slice": log_slice,
                        "row_files": row_files,
                        "meta_file": meta_file,
                        "reset_proof": proof,
                        "request_contract": dict(request),
                    })
                    # roll observer outputs aside so the next request's
                    # hook writes fresh files (retained per-request)
                    for d in range(D.DECISIONS):
                        src = unit_dir / f"obs.row{d}.f32"
                        dst = (unit_dir /
                               f"req{index + 1}.obs.row{d}.f32")
                        if src.exists():
                            src.replace(dst)
                    meta_src = unit_dir / "obs.meta.json"
                    meta_dst = unit_dir / f"req{index + 1}.obs.meta.json"
                    if meta_src.exists():
                        meta_src.replace(meta_dst)
                    # FROZEN EARLY-STOP LAW (correction pass 3, blocker
                    # 2): the first row-digest mismatch answers the
                    # discriminator — never burn further repeats. A
                    # mismatch stop is a VALID completion cause,
                    # distinct from truncation.
                    row_digests = [D.row_digest(row_files[
                        f"obs.row{d}.f32"]) for d in range(D.DECISIONS)]
                    if baseline_rows is None:
                        baseline_rows = row_digests
                    elif row_digests != baseline_rows:
                        stop_kind = "mismatch_stop"
                        stop_reason = (
                            f"first row-digest mismatch at request "
                            f"{index}")
                        break
            finally:
                stop.set()
                thread.join(timeout=2)
            if errors:
                raise PhysicalDiagnosticError(
                    "device sampling failed") from errors[0]
            samples.append(_device_sample() | {"stage": "after"})
            return {"server_pid": proc.pid,
                    "process_attribution": attribution,
                    "requests": records,
                    "device_samples": samples,
                    "stop_kind": stop_kind,
                    "stop_reason": stop_reason}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
