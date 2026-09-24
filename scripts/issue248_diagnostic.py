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
  * No physical entrypoint runs without a maintainer dispatch authority
    bound to the exact current HEAD (accepted #241 authority model:
    top-level PR conversation comment with dispatch phrase + head=sha +
    diagnostic-namespace scope as exact stripped lines) — a #241
    qualification dispatch can never authorize diagnostic execution.
  * Every diagnostic execution unit binds, before launch: exact binary
    identity (one of the three accepted llama.cpp pin builds), exact
    model member hashes, exact case fixture from the accepted historical
    ladder (sha-verified), exact arm identity via the frozen #241
    generation-2 constants, and the frozen request contract.
  * Determinism is judged ONLY on independently computed digests of the
    derived acceptance-bearing output (the fixed 8-token list canonically
    packed) plus the full row bytes when the observer captured them; raw
    responses are custody-only.
  * Timing is diagnostic metadata; never a gate.
  * Retained bytes are append-only: a failed or superseded diagnostic
    unit directory must be moved aside to a ``-quarantined`` sibling
    before any re-run at the same label (no overwrite in place).

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
    """
    if not isinstance(authority, dict):
        raise DiagnosticError("authority must be a dict")
    for key in ("comment_id", "issue_url", "author_association",
                "created_at", "body", "head_sha"):
        if not authority.get(key):
            raise DiagnosticError(f"authority field missing: {key}")
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
    namespace = None
    for ln in lines:
        if ln.startswith("diagnostic-namespace="):
            namespace = ln.split("=", 1)[1]
    validate_namespace(namespace or "")
    if namespace != authority.get("namespace"):
        raise DiagnosticError("scope namespace mismatch inside authority")
    return dict(authority, namespace=namespace)


def fetch_dispatch_authority(repo_root: Path, expected_head: str,
                             namespace: str,
                             github_api: str = "https://api.github.com"
                             ) -> dict[str, Any]:
    """Fetch and verify the live dispatch comment from the PR conversation.

    GET-only, paginated, fail-closed on unbounded pages; honors the
    authenticated GET-only proxy environment variables the accepted
    campaign used on the compute node (https_proxy/SSL_CERT_FILE).
    """
    import urllib.request

    _require_clean_head(Path(repo_root), expected_head)
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue248-diagnostic"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (f"{github_api}/repos/Zutfen-LLC/inferswarm/"
               f"issues/{DIAGNOSTIC_PR_NUMBER}/comments?page={page}&per_page=100")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            batch = json.loads(response.read())
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
        }
        try:
            return validate_authority_payload(authority, expected_head)
        except DiagnosticError:
            continue
    raise DiagnosticError(
        f"no valid dispatch authority for head {expected_head} "
        f"namespace {namespace}")


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
    for p in sorted(unit_dir.glob("*.r8e.pos*.f32")):
        m = re.search(r"\.pos(\d+)\.f32$", p.name)
        if m:
            out[int(m.group(1))] = p.read_bytes()
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
