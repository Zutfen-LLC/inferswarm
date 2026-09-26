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
import signal
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

# Same-process reset-evidence proof shapes, derived from the PINNED
# server's actual log lines (server-context.cpp:1831 + retained #248
# evidence shape):
#   "slot get_availabl: id  3 | task 0 | selected slot by id (3)"
#     -> an id_slot request selects slot 3 BY ID (not LRU/LCP)
#   "prompt eval time = ... /  3077 tokens"
#     -> the FULL prompt was re-processed (no cache reuse) per request
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
                         base_repeats: int, base_tokens: int) -> str:
    """Derive a ladder-length prompt by the accepted derivation rule.

    The accepted ladder fixtures are a frozen prologue + N repeats of
    one sentence block + a frozen suffix. A ladder prompt at length L
    uses the SAME prologue/suffix with the sentence repeat count from
    the frozen ARM_D_LADDER_SENTENCE_REPEATS table (predeclared in
    scripts/issue250_diagnostic.py before any execution; never picked
    after seeing outputs).
    """
    if length not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError(
            f"length {length} is not in the predeclared ladder")
    if base_repeats <= 0 or base_tokens <= 0:
        raise PhysicalDiagnosticError("malformed base fixture")
    # The repeated sentence block is derived from the accepted
    # case-3072 fixture itself: total chars minus prologue/suffix
    # split proportionally to the repeat count.
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
            base["prompt_text"], length,
            base["sentence_repeats"], len(base["prompt_token_ids"]))
        prompt_token_ids = None  # ladder token count recorded at runtime
    else:
        prompt = fixtures[D.CASE]["prompt_text"]
        prompt_token_ids = fixtures[D.CASE]["prompt_token_ids"]

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
        wall=wall, health_runner=health_runner)


def _finalize_unit_receipt(*, unit_dir, tag, namespace, arm, unit, result,
                           request, argv, env, binary_id, binary_sha,
                           attestation, stat_witness, model_dir,
                           launch_member, prompt, prompt_token_ids,
                           identity_pre, identity_observer, problems_pre,
                           final_authority, unit_started_at, unit_ended_at,
                           wall, health_runner,
                           same_process_block=None) -> dict[str, Any]:
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
# equivalent requests, reset semantics proven per request)
# ---------------------------------------------------------------------------

def _parse_slot_log(text: str, request_index: int,
                    expected_prompt_tokens: int) -> dict[str, Any]:
    """Prove reset semantics for one same-process request from the
    retained server-log slice: slot 3 selected BY ID, full prompt
    re-evaluated (no cache reuse)."""
    slot_by_id = bool(SLOT_BY_ID_RE.search(text))
    prompt_evals = [int(m.group(1))
                    for m in PROMPT_EVAL_RE.finditer(text)]
    full_recompute = [n for n in prompt_evals
                      if n == expected_prompt_tokens]
    return {
        "request_index": request_index,
        "slot_selected_by_id": slot_by_id,
        "prompt_eval_token_counts": prompt_evals,
        "full_recompute_proven": bool(full_recompute),
        "full_recompute_count": len(full_recompute),
    }


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
                    expected_prompt_tokens=expected_prompt_tokens)
    wall = time.monotonic() - started
    ended_at = _utcnow()

    # ---- custody + fail-closed lifecycle verification ----
    shared_pid = result.get("server_pid")
    if type(shared_pid) is not int or shared_pid <= 0:
        raise PhysicalDiagnosticError("lifecycle carried no server PID")
    per_request = result.get("requests")
    if (not isinstance(per_request, list)
            or len(per_request) != D.DETERM_MIN_REPEATS):
        raise PhysicalDiagnosticError(
            "same-process lifecycle must retain exactly "
            f"{D.DETERM_MIN_REPEATS} per-request records")
    request_records = []
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
        proof = record["reset_proof"]
        if (not isinstance(proof, dict)
                or not proof.get("slot_selected_by_id")
                or not proof.get("full_recompute_proven")):
            raise PhysicalDiagnosticError(
                f"same-process request {index} lacks reset-equivalence "
                "proof (slot-by-id + full prompt recompute)")
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
            "authority": unit_authority_block(final_authority),
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
        "reset_proofs": [r["reset_proof"] for r in request_records],
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
        expected_prompt_tokens: int) -> dict[str, Any]:
    """ONE server launch; ``repeats`` sequential requests; teardown."""
    samples = [_device_sample() | {"stage": "before"}]
    full_env = {**os.environ, **env}
    log_path = unit_dir / "server.log.full"
    log_offsets: list[int] = []
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
            try:
                for index in range(repeats):
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
                        index, expected_prompt_tokens)
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
                    "device_samples": samples}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
