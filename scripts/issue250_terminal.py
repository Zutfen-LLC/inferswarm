#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — fail-closed retained-byte terminal reduction.

Correction pass 2 (maintainer NO-GO comment 5840630050, blocker 4):
the previous ``derive_terminal(reduction)`` trusted a caller-constructed
dictionary of booleans. That is not retained-byte authority. This
module derives the Issue #250 terminal DIRECTLY from the retained
evidence tree: every conclusion is reconstructed from retained unit
receipts, raw responses, observer rows/metadata, server logs,
identity pre/post observations, platform-health receipts, campaign
model attestations, and the live dispatch-authority binding.

Caller-supplied ``deterministic=true``, localized factors, terminal
labels, or condition summaries are not authorities of any kind — the
function takes none of them.

Sequential terminal law (Issue #250 §A–§D; frozen):

  A. Arm A (namespace d250-arm-a) — required always.
     * CPU-only (-dev none) deterministic WITH a valid deterministic
       repeat count (>=5 identical) AND the accepted nonzero-Vulkan
       contrast (#248 retained ngl=1) nondeterministic
       => R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED,
          factor = backend-participation boundary.
     * CPU-only deterministic AND the contrast ALSO deterministic in a
       way that destroys the planned comparison (retained #248 bytes
       no longer vary / were consumed invalid)
       => R8I3B_REDUCER_BLOCKED_INCOMPLETE or honest UNRESOLVED per
          the frozen rule below — never localization.
     * CPU-only varies => Arm B becomes REQUIRED (no terminal yet).
  B. Arm B (d250-arm-b) — required only when A's CPU-only varies.
     * fresh-process CPU-only varies AND same-process CPU-only
       deterministic => LOCALIZED, factor = fresh-process/runtime-
       initialization boundary.
     * both vary => Arm C becomes required.
     * missing B evidence when required => REDUCER_BLOCKED.
  C. Arm C (d250-arm-c) — required only when B leaves CPU-only
     variation unlocalized.
     * default-threading CPU-only varies AND serial (-t 1 -tb 1)
       CPU-only deterministic => LOCALIZED, factor = CPU parallel
       execution/order boundary.
     * serial also varies => Arm D becomes required.
     * missing C evidence when required => REDUCER_BLOCKED.
  D. Arm D (d250-arm-d) — required only when A–C do not localize.
     * Derives each predeclared length's exact row repeatability.
     * LOCALIZED only if retained source/runtime evidence
       mechanically identifies the corresponding execution transition
       and a FROZEN predicate binds it to the observed
       deterministic->variable boundary (see TRANSITION_PREDICATES).
     * Otherwise => R8I3B_REFERENCE_RUNTIME_UNRESOLVED.

UNRESOLVED may be emitted only after every reachable arm is complete.
Unreachable later-arm evidence can never override an earlier
localization (later namespaces are simply not consumed once a
terminal is derived at an earlier arm).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

import issue250_diagnostic as D
import issue250_physical as P
import issue248_health as H
import issue248_identity as I

SCHEMA = TERMINAL_SCHEMA = "inferswarm.issue250.terminal/1"
LOCALIZED = "R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED"
UNRESOLVED = "R8I3B_REFERENCE_RUNTIME_UNRESOLVED"
BLOCKED = D.REDUCER_BLOCKED

TERMINALS = (LOCALIZED, UNRESOLVED)

# Sequential arm ladder (namespace, arm) in reachability order.
ARM_LADDER = (
    ("d250-arm-a", "A-vulkan-necessity"),
    ("d250-arm-b", "B-process-init"),
    ("d250-arm-c", "C-cpu-threads"),
    ("d250-arm-d", "D-context-transition"),
)

LOCALIZED_FACTORS = {
    "A-vulkan-necessity": "backend-participation boundary "
                          "(zero vs nonzero Vulkan participation)",
    "B-process-init": "fresh-process/runtime-initialization boundary",
    "C-cpu-threads": "CPU parallel execution/order boundary",
    "D-context-transition": "long-context execution-path transition "
                            "(bound by frozen transition predicate)",
}

# Frozen Arm-D transition predicates (predeclared BEFORE any Arm-D
# execution). A length transition alone never establishes causality:
# LOCALIZED at D requires retained evidence matching one of these
# mechanical predicates — a concrete execution transition identified
# from retained source/runtime evidence, bound to the observed
# deterministic->variable length boundary. Each predicate names the
# retained evidence it consumes; none is derivable from length alone.
TRANSITION_PREDICATES = {
    "ubatch_geometry_split": {
        "requires": "server-log prompt-processing progress lines "
                    "showing a ubatch split shape present at every "
                    "variable length and absent at every deterministic "
                    "length (retained per-unit server.log)",
        "binds": "the earliest variable ladder length must carry the "
                 "split shape and the latest deterministic length "
                 "must not",
    },
    "indexer_top_k_boundary": {
        "requires": "model-architecture fact "
                    "qwen4exp.attention.indexer.top_k = 2048 crossed "
                    "between the last deterministic and first variable "
                    "rendered length (phase0 MODEL_ARCH_FACTS + ladder "
                    "rendered lengths)",
        "binds": "the deterministic->variable boundary must equal the "
                 "top_k crossing length, not merely fall below it",
    },
    "checkpoint_resegmentation": {
        "requires": "server-log prompt-processing progress lines "
                    "showing hybrid-memory checkpoint resegmentation "
                    "(non-uniform split geometry) beginning exactly at "
                    "the boundary length",
        "binds": "resegmentation evidence present at the first "
                 "variable length and absent at the last deterministic "
                 "length, with no other logged execution change",
    },
}


def _blocked(problems: list[str], reduction: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    return {"schema": SCHEMA, "terminal": None, "terminal_vocabulary":
            list(D.TERMINALS), "blocked": BLOCKED, "complete": False,
            "problems": problems, "arms": (reduction or {}).get("arms", {}),
            "contrast": (reduction or {}).get("contrast")}


def _ok(terminal: str, reduction: dict[str, Any], basis: dict[str, Any]
        ) -> dict[str, Any]:
    return {"schema": SCHEMA, "terminal": terminal,
            "terminal_vocabulary": list(D.TERMINALS), "blocked": None,
            "complete": True, "problems": [], "arms": reduction["arms"],
            "contrast": reduction.get("contrast"), "basis": basis}


# ---------------------------------------------------------------------------
# Arm-D transition predicate evaluation (frozen, mechanical)
# ---------------------------------------------------------------------------

def _non_uniform_progress(counts: list[int]) -> bool:
    """True when the cumulative prompt-progress steps are unequal.

    The pinned server logs cumulative ``prompt processing, n_tokens``
    progress lines; unequal steps (e.g. 512*5 then 5 then 508 for a
    3077-token prompt) are the retained signature of hybrid
    memory-driven ubatch split geometry.
    """
    if len(counts) < 2:
        return False
    steps = [b - a for a, b in zip(counts, counts[1:])]
    return len(set(steps)) > 1


def _evaluate_transition_predicates(
        ladder_facts: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    """Evaluate the frozen Arm-D predicates from retained ladder facts.

    ``ladder_facts`` maps rendered length -> {"row_deterministic": bool,
    "prompt_progress_counts": [...]} derived from retained bytes. A
    predicate FIRES only on the mechanical shape it names; a length
    threshold alone fires nothing. Returns the fired predicate
    description or None.
    """
    lengths = sorted(ladder_facts)
    if not lengths:
        return None
    det = [n for n in lengths if ladder_facts[n]["row_deterministic"]]
    var = [n for n in lengths if not ladder_facts[n]["row_deterministic"]
           and ladder_facts[n]["unit_count"] >= 2]
    if not det or not var:
        return None
    # The observed boundary: last deterministic length, first variable.
    if max(det) >= min(var):
        return None  # interleaved — no monotone boundary exists
    boundary = (max(det), min(var))

    # ubatch_geometry_split / checkpoint_resegmentation: non-uniform
    # final-step geometry present at EVERY variable length and absent
    # at EVERY deterministic length.
    shapes = {n: _non_uniform_progress(
        ladder_facts[n]["prompt_progress_counts"]) for n in lengths}
    if all(shapes[n] for n in var) and not any(shapes[n] for n in det):
        return {
            "predicate": "ubatch_geometry_split",
            "boundary": boundary,
            "mechanism": TRANSITION_PREDICATES["ubatch_geometry_split"],
        }
    if any(shapes[n] for n in var) and not any(shapes[n] for n in det):
        return {
            "predicate": "checkpoint_resegmentation",
            "boundary": boundary,
            "mechanism": TRANSITION_PREDICATES["checkpoint_resegmentation"],
        }
    # indexer_top_k_boundary: boundary == top_k crossing (2048).
    if boundary[0] < 2048 <= boundary[1] and all(
            n < 2048 for n in det) and all(n >= 2048 for n in var):
        return {
            "predicate": "indexer_top_k_boundary",
            "boundary": boundary,
            "mechanism": TRANSITION_PREDICATES["indexer_top_k_boundary"],
        }
    return None


def _ladder_split_shapes(text: str) -> list[int]:
    """Parse cumulative prompt-progress counts from a retained server
    log slice. The pinned server emits cumulative
    ``prompt processing, n_tokens = <n>`` lines; these counts are the
    retained-byte basis for the Arm-D geometry predicates.
    """
    counts: list[int] = []
    for match in re.finditer(
            r"prompt processing, n_tokens = (\d+)", text):
        n = int(match.group(1))
        if n not in counts:
            counts.append(n)
    return counts


# ---------------------------------------------------------------------------
# Per-unit retained-byte verification (fail-closed)
# ---------------------------------------------------------------------------

UNIT_SAFE_TAG = re.compile(
    r"case-\d+-B-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{3}")


def _verify_unit_receipt(unit_dir: Path, namespace: str, arm: str,
                         tag: str, expected_head: str,
                         expected_authority: dict[str, Any],
                         attestation: dict[str, Any],
                         expected_request_kind: str,
                         ) -> dict[str, Any]:
    """Independently verify ONE retained unit from its bytes.

    Checks (each from retained bytes, fail-closed): unit receipt
    schema/tag/namespace/arm binding; dispatch-authority block equality
    with the live-validated payload; exact branch/head; binary SHA;
    model-member attestation binding + stat witness; request contract;
    process argv/env; raw response digest; token digest; complete row
    bytes and row SHA-256; observer metadata; identity pre/post raw
    observations; platform-health receipt.
    """
    if unit_dir.is_symlink() or not unit_dir.is_dir():
        raise ValueError(f"unit directory missing or symlink: {tag}")
    receipt = json.loads((unit_dir / "unit.json").read_bytes())
    if not isinstance(receipt, dict) or receipt.get("schema") != (
            P.UNIT_SCHEMA):
        raise ValueError("unit receipt schema mismatch")
    if (receipt.get("tag") != tag or receipt.get("namespace") != namespace
            or receipt.get("arm_id") != arm or receipt.get("arm") != P.ARM):
        raise ValueError("receipt tag/namespace/arm binding mismatch")
    # planned-unit geometry consistency (frozen plan membership)
    plan = D.probe_list_for(arm)
    spec = next((u for u in plan if u["tag"] == tag), None)
    if spec is None:
        raise ValueError(f"unit {tag} is not in the frozen arm plan")
    if receipt.get("unit", {}).get("argv_delta") != list(
            spec.get("argv_delta", ())):
        raise ValueError("receipt argv delta differs from frozen plan")
    # dispatch authority binding (exact block equality with live payload)
    authority = receipt.get("authority")
    if not isinstance(authority, dict):
        raise ValueError("unit receipt carries no dispatch authority block")
    expected_block = P.unit_authority_block(expected_authority)
    for key, value in expected_block.items():
        if authority.get(key) != value:
            raise ValueError(
                f"unit dispatch authority binding mismatch: {key}")
    if authority.get("head_sha") != expected_head:
        raise ValueError("unit authority head mismatch")
    # binary authority
    if (receipt.get("binary_sha256")
            != D.SERVER_BINARIES.get(receipt.get("binary_id"))):
        raise ValueError("unit binary identity mismatch")
    # model authority
    if receipt.get("model_attestation_sha256") != attestation[
            "attestation_sha256"]:
        raise ValueError(
            "unit model attestation digest differs from campaign opening")
    witness = receipt.get("model_stat_witness")
    if not isinstance(witness, dict) or sorted(witness) != sorted(
            D.MODEL_MEMBERS):
        raise ValueError("unit model stat witness population malformed")
    attested = {m["name"]: m for m in attestation["members"]}
    for member, fields in witness.items():
        if (not isinstance(fields, dict)
                or sorted(fields) != sorted(P.WITNESS_STAT_KEYS)
                or any(type(fields[k]) is not int for k in
                       P.WITNESS_STAT_KEYS)):
            raise ValueError(f"unit stat witness malformed: {member}")
        if any(fields[k] != attested[member][k]
               for k in P.WITNESS_STAT_KEYS):
            raise ValueError(
                f"unit stat witness differs from attestation: {member}")
    if (receipt.get("model_dir") != D.MODEL_DIR
            or receipt.get("model_launch_member")
            != str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)):
        raise ValueError("unit model launch member mismatch")
    # request contract
    if expected_request_kind == "arm-b":
        expected_contract = D.ARM_B_CONTRACT
    else:
        expected_contract = D.REQUEST_CONTRACT
    contract = receipt.get("request_contract")
    if (not isinstance(contract, dict) or contract != expected_contract
            or D.canonical_request_digest(contract)
            != receipt.get("request_contract_sha256")):
        raise ValueError("unit request contract mismatch")
    # argv/env (exact frozen geometry, one declared factor)
    argv = receipt.get("server_argv")
    if not isinstance(argv, list) or not argv or not argv[0]:
        raise ValueError("server argv missing")
    if argv != P.server_argv(Path(argv[0]),
                             Path(receipt["model_launch_member"]), spec):
        raise ValueError("server argv differs from frozen geometry")
    env = receipt.get("server_env")
    if not isinstance(env, dict):
        raise ValueError("server env missing")
    expected_env_visible = {
        k: v for k, v in P.launch_env(Path("x") / "obs").items()
        if k.startswith(("LLAMA_", "VK_", "CUDA_"))}
    # LLAMA_OBSERVE_OUT differs per unit dir; compare the rest
    for key in expected_env_visible:
        if key == "LLAMA_OBSERVE_OUT":
            continue
        if env.get(key) != expected_env_visible[key]:
            raise ValueError(
                f"server env differs from frozen probe: {key}")
    # process attribution
    actual = receipt.get("process_attribution")
    if (not isinstance(actual, dict)
            or type(actual.get("server_pid")) is not int
            or actual["server_pid"] <= 0
            or actual.get("server_exe_sha256") != receipt["binary_sha256"]
            or actual.get("server_argv") != argv):
        raise ValueError("process attribution mismatch")
    # raw response + token digests
    raw = (unit_dir / "response.json.raw").read_bytes()
    if receipt.get("response_raw_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("raw response digest binding mismatch")
    response = json.loads(raw)
    tokens = (response.get("tokens", response.get("tokens_predicted"))
              if isinstance(response, dict) else None)
    if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
            or any(type(t) is not int for t in tokens)
            or tokens != receipt.get("tokens")):
        raise ValueError("raw and receipt tokens disagree")
    token_sha = hashlib.sha256(
        D.CANONICAL_PACK.pack(*tokens)).hexdigest()
    if receipt.get("deterministic_output_sha256") != token_sha:
        raise ValueError("receipt token digest mismatch")
    # complete row bytes + digests
    meta_raw = (unit_dir / "obs.meta.json").read_bytes()
    if receipt.get("observer_meta_sha256") != hashlib.sha256(
            meta_raw).hexdigest():
        raise ValueError("observer metadata digest binding mismatch")
    lines = [ln for ln in meta_raw.decode("utf-8").splitlines()
             if ln.strip()]
    if len(lines) != D.DECISIONS:
        raise ValueError("observer metadata must cover all decisions")
    row_sha: list[str] = []
    for i, ln in enumerate(lines):
        meta = json.loads(ln)
        if not isinstance(meta, dict) or meta.get("pos") != i:
            raise ValueError("observer metadata position order mismatch")
        row = (unit_dir / f"obs.row{i}.f32").read_bytes()
        if len(row) != D.ROW_BYTES:
            raise ValueError("observer row wrong vocabulary width")
        row_sha.append(hashlib.sha256(row).hexdigest())
    if receipt.get("observer_rows") != row_sha:
        raise ValueError("observer row digest binding mismatch")
    # identity pre/post (raw observations, re-derived). Same-process
    # request units share the lifecycle identity observations.
    identity_dir = unit_dir
    if receipt.get("kind") == "same-process-request":
        sp_dir = receipt.get("same_process", {}).get("lifecycle_dir")
        if not isinstance(sp_dir, str) or "/" in sp_dir:
            raise ValueError("lifecycle dir binding malformed")
        identity_dir = unit_dir.parent / sp_dir
    pre = json.loads((identity_dir / "identity-pre.json").read_bytes())
    post = json.loads((identity_dir / "identity-post.json").read_bytes())
    if not isinstance(pre, dict) or not isinstance(post, dict):
        raise ValueError("identity observations malformed")
    raw_problems = (I.identity_problems(P.ARM, pre)
                    + I.identity_problems(P.ARM, post))
    if raw_problems:
        raise ValueError(f"identity drift: {raw_problems[0]}")
    # platform-health custody
    binding = receipt.get("platform_health_receipt")
    health_receipt = receipt.get("platform_health")
    health_dir = unit_dir
    if isinstance(binding, dict) and ".." in Path(
            binding.get("path", "")).parts:
        # same-process receipts bind the shared lifecycle receipt
        # (../<lifecycle>/platform-health-receipt.json)
        parts = [p for p in Path(binding["path"]).parts if p != ".."]
        if len(parts) != 2:
            raise ValueError("platform-health receipt binding malformed")
        health_dir = unit_dir.parent / parts[0]
        binding_path = health_dir / parts[1]
    else:
        binding_path = unit_dir / (
            binding.get("path") if isinstance(binding, dict)
            else "platform-health-receipt.json")
    raw_health = binding_path.read_bytes()
    if (not isinstance(binding, dict)
            or type(binding.get("bytes")) is not int
            or binding["bytes"] != len(raw_health)
            or binding.get("sha256") != hashlib.sha256(raw_health).hexdigest()
            or binding.get("window") != health_receipt.get("window")):
        raise ValueError("platform-health receipt binding mismatch")
    checked = H.verify_platform_health(
        health_dir, health_receipt,
        expected_gpu_uuid=I.REFERENCE_IDENTITY["gpu_uuid"],
        expected_bdf=I.frozen_identity(P.ARM)["bdf"],
        expected_arm=P.ARM)
    if not checked["valid"]:
        raise ValueError("platform-health custody invalid")
    return {"tag": tag, "token_sha256": token_sha, "row_sha256": row_sha,
            "receipt": receipt, "rows_meta_lines": lines,
            "fatal_findings": checked["fatal_findings"]}


def _verify_namespace_population(
        root: Path, namespace: str, arm: str, expected_head: str,
        authority: dict[str, Any], attestation: dict[str, Any],
        tags: list[str], request_kind_for_tag: Callable[[str], str],
        extra_expected: set[str] | None = None,
        ) -> tuple[dict[str, Any], list[str]]:
    """Verify the complete frozen unit population of one arm namespace.

    Fails closed on: missing units, quarantined-only units, unplanned
    current units, any per-unit verification failure. ``extra_expected``
    covers planned population verified by a different verifier (the
    Arm-B same-process units): those dirs are expected to exist but
    are not re-verified here.
    """
    base = D.namespace_dir(root, namespace)
    problems: list[str] = []
    facts: list[dict[str, Any]] = []
    if base.is_symlink() or not base.is_dir():
        return {}, [f"{arm}: namespace {namespace} missing"]
    current: set[str] = set()
    for candidate in sorted(base.iterdir()):
        name = candidate.name
        if name.endswith("-quarantined") or name.endswith("lifecycle"):
            continue
        if candidate.is_dir() and not candidate.is_symlink() and (
                UNIT_SAFE_TAG.fullmatch(name)):
            current.add(name)
    expected_all = set(tags) | (extra_expected or set())
    unplanned = current - expected_all
    if unplanned:
        problems.append(
            f"{arm}: unplanned current units present: {sorted(unplanned)}")
    for tag in tags:
        if tag not in current:
            problems.append(f"{arm}: planned unit missing from evidence: "
                            f"{tag}")
            continue
        try:
            facts.append(_verify_unit_receipt(
                base / tag, namespace, arm, tag, expected_head,
                authority, attestation, request_kind_for_tag(tag)))
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as exc:
            problems.append(f"{arm}: malformed retained unit {tag}: {exc}")
    return {"units": facts}, problems


# ---------------------------------------------------------------------------
# Accepted #248 contrast verification (read-only historical authority)
# ---------------------------------------------------------------------------

def _verify_contrast_manifest(manifest_path: Path) -> dict[str, Any]:
    """Verify the accepted #248 SHA256SUMS manifest self-digest."""
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != D.ACCEPTED_248_MANIFEST_SELF_DIGEST:
        raise ValueError(
            f"accepted #248 manifest self-digest drift: {digest}")
    rows: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError("malformed manifest row")
        rows[parts[1].strip()] = parts[0].strip()
    return {"rows": rows, "self_digest": digest}


# The accepted #248 retained units bind the exact head of the #248
# DISPATCH generation (the reviewed tooling head the campaign ran
# under), not the later result-adjudication head; both are frozen
# accepted authority constants.
CONTRAST_AUTHORITY_HEAD = "3f36ef1a518065bdc848cb66f6f26d94b34319f4"


def verify_historical_contrast(contrast_root: Path) -> dict[str, Any]:
    """Consume the accepted #248 retained ngl=1 result as the Arm-A
    nonzero-Vulkan contrast (READ-ONLY; never fresh #250 execution).

    Verifies: manifest self-digest; every consumed file's digest
    against a manifest row; unit receipts bind the accepted #248
    result head + placement namespace; ngl/case exact; row
    nondeterminism DERIVED from the retained row bytes themselves.
    """
    contrast_root = Path(contrast_root)
    manifest = _verify_contrast_manifest(contrast_root / "SHA256SUMS")
    rows = manifest["rows"]
    units = []
    for tag in D.CONTRAST_UNITS:
        unit_dir = contrast_root / D.CONTRAST_NAMESPACE / tag
        if unit_dir.is_symlink() or not unit_dir.is_dir():
            raise ValueError(f"contrast unit missing: {tag}")
        receipt_raw = (unit_dir / "unit.json").read_bytes()
        _require_manifest_row(rows, f"{D.CONTRAST_NAMESPACE}/{tag}/unit.json",
                              receipt_raw)
        receipt = json.loads(receipt_raw)
        if (receipt.get("namespace") != D.CONTRAST_NAMESPACE
                or receipt.get("case_id") != D.CONTRAST_CASE
                or receipt.get("ngl") != D.CONTRAST_NGL):
            raise ValueError(f"contrast unit binding mismatch: {tag}")
        authority = receipt.get("authority", {})
        if (authority.get("head_sha") != CONTRAST_AUTHORITY_HEAD
                or authority.get("namespace") != D.CONTRAST_NAMESPACE
                or authority.get("pr_number") != 249
                or authority.get("issue_number") != 248):
            raise ValueError(
                f"contrast unit not bound to the accepted #248 dispatch "
                f"head/PR/issue: {tag}")
        row_sha = []
        for i in range(D.DECISIONS):
            rel = f"{D.CONTRAST_NAMESPACE}/{tag}/obs.row{i}.f32"
            row = (contrast_root / rel).read_bytes()
            _require_manifest_row(rows, rel, row)
            if len(row) != D.ROW_BYTES:
                raise ValueError(f"contrast row width mismatch: {rel}")
            row_sha.append(hashlib.sha256(row).hexdigest())
        if receipt.get("observer_rows") != row_sha:
            raise ValueError(f"contrast receipt row digests mismatch: {tag}")
        units.append({"tag": tag, "row_sha256": row_sha,
                      "token_sha256": receipt["deterministic_output_sha256"]})
    if len(units) < D.CONTRAST_MIN_UNITS:
        raise ValueError("contrast population incomplete")
    row_digests = [tuple(u["row_sha256"]) for u in units]
    row_deterministic = len(set(row_digests)) == 1
    if row_deterministic != D.CONTRAST_EXPECTED_ROW_DETERMINISTIC:
        raise ValueError(
            "retained #248 contrast rows contradict the accepted "
            "nondeterminism — the planned Arm-A comparison is destroyed")
    return {
        "provenance": D.CONTRAST_PROVENANCE,
        "namespace": D.CONTRAST_NAMESPACE,
        "units": units,
        "manifest_self_digest": manifest["self_digest"],
        "row_deterministic": row_deterministic,
        "note": "accepted #248 retained evidence consumed read-only; "
                "never represented as fresh #250 execution",
    }


def _require_manifest_row(rows: dict[str, str], rel: str, raw: bytes
                          ) -> None:
    expected = rows.get(rel)
    if expected is None:
        raise ValueError(f"consumed contrast file absent from manifest: {rel}")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"contrast file digest mismatch: {rel}")


# ---------------------------------------------------------------------------
# Same-process lifecycle verification (Arm B condition 2)
# ---------------------------------------------------------------------------

def _verify_same_process_units(
        root: Path, namespace: str, arm: str, expected_head: str,
        authority: dict[str, Any], attestation: dict[str, Any],
        ) -> tuple[dict[str, Any], list[str]]:
    """Verify the Arm-B same-process population from retained bytes.

    Requires: one shared lifecycle record binding ONE PID to all five
    requests; per-request reset proofs (slot-by-id + full recompute)
    re-derived from the retained log slices; request-history
    invariance (same frozen Arm-B contract, same shared PID).
    """
    base = D.namespace_dir(root, namespace)
    problems: list[str] = []
    plan = D.probe_list_for(arm)
    same_specs = [u for u in plan if u.get("same_process")]
    tags = [u["tag"] for u in same_specs]
    lifecycle_dir = base / (tags[0].rsplit("-", 1)[0] + "-lifecycle")
    if lifecycle_dir.is_symlink() or not lifecycle_dir.is_dir():
        return {}, [f"{arm}: same-process lifecycle record missing"]
    lifecycle_raw = (lifecycle_dir / "lifecycle.json").read_bytes()
    lifecycle = json.loads(lifecycle_raw)
    if lifecycle.get("schema") != P.LIFECYCLE_SCHEMA:
        return {}, [f"{arm}: lifecycle schema mismatch"]
    shared_pid = lifecycle.get("shared_server_pid")
    if type(shared_pid) is not int or shared_pid <= 0:
        return {}, [f"{arm}: lifecycle binds no shared PID"]
    if lifecycle.get("request_count") != len(tags):
        return {}, [f"{arm}: lifecycle request count != planned "
                    f"{len(tags)}"]
    authority_block = lifecycle.get("authority")
    expected_block = P.unit_authority_block(authority)
    for key, value in expected_block.items():
        if not isinstance(authority_block, dict) or (
                authority_block.get(key) != value):
            return {}, [f"{arm}: lifecycle authority binding mismatch "
                        f"({key})"]
    units = []
    for spec in same_specs:
        tag = spec["tag"]
        try:
            fact = _verify_unit_receipt(
                base / tag, namespace, arm, tag, expected_head,
                authority, attestation, "arm-b")
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as exc:
            problems.append(f"{arm}: malformed same-process unit {tag}: "
                            f"{exc}")
            continue
        receipt = fact["receipt"]
        sp = receipt.get("same_process")
        if (not isinstance(sp, dict)
                or sp.get("shared_server_pid") != shared_pid
                or type(sp.get("request_index")) is not int
                or not isinstance(sp.get("reset_proof"), dict)):
            problems.append(
                f"{arm}: unit {tag} not bound to the shared lifecycle "
                "PID/requests")
            continue
        proof = sp["reset_proof"]
        if (not proof.get("slot_selected_by_id")
                or not proof.get("full_recompute_proven")):
            problems.append(
                f"{arm}: unit {tag} reset proof lacks slot-by-id or full "
                "recompute evidence")
            continue
        # Re-derive the reset proof from the retained log slice bytes.
        log_raw = (base / tag / "server.log").read_bytes()
        rederived = P._parse_slot_log(
            log_raw.decode("utf-8", errors="replace"),
            proof["request_index"], 3077)
        if (not rederived["slot_selected_by_id"]
                or not rederived["full_recompute_proven"]):
            problems.append(
                f"{arm}: unit {tag} retained log slice does not prove "
                "reset semantics")
            continue
        units.append(fact)
    if problems:
        return {"units": units, "shared_pid": shared_pid}, problems
    indexes = sorted(u["receipt"]["same_process"]["request_index"]
                     for u in units)
    if indexes != list(range(len(tags))):
        problems.append(
            f"{arm}: lifecycle request indexes are not a complete "
            f"sequence: {indexes}")
    return {"units": units, "shared_pid": shared_pid,
            "lifecycle": lifecycle}, problems


# ---------------------------------------------------------------------------
# Condition determinism derivation
# ---------------------------------------------------------------------------

def _condition_determinism(units: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a condition's determinism from unit row/token digests."""
    if not units:
        return {"deterministic": None, "n": 0}
    row_digests = [tuple(u["row_sha256"]) for u in units]
    token_digests = [u["token_sha256"] for u in units]
    rows_identical = len(set(row_digests)) == 1
    row_judgement = D.judge_repeat_determinism(
        [hashlib.sha256(json.dumps(list(rd)).encode()).hexdigest()
         for rd in row_digests])
    token_judgement = D.judge_repeat_determinism(token_digests)
    return {
        "deterministic": row_judgement["deterministic_claim_valid"],
        "rows_strictly_identical": rows_identical,
        "row_deterministic_claim_valid":
            row_judgement["deterministic_claim_valid"],
        "token_deterministic_claim_valid":
            token_judgement["deterministic_claim_valid"],
        "n": len(units),
        "row_unique_tuples": len(set(row_digests)),
        "token_unique": len(set(token_digests)),
    }


def _arm_a_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any], contrast_root: Path,
                 ) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    pop, pop_problems = _verify_namespace_population(
        root, "d250-arm-a", "A-vulkan-necessity", expected_head,
        authority, attestation,
        [u["tag"] for u in D.probe_list_for("A-vulkan-necessity")],
        lambda tag: "accepted")
    problems.extend(pop_problems)
    try:
        contrast = verify_historical_contrast(contrast_root)
    except (OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError) as exc:
        return pop, problems + [f"contrast verification failed: {exc}"]
    return {**pop, "contrast": contrast}, problems


def _arm_b_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any],
                 ) -> tuple[dict[str, Any], list[str]]:
    problems: list[str] = []
    fresh_tags = [u["tag"] for u in D.probe_list_for("B-process-init")
                  if not u.get("same_process")]
    same_tags = [u["tag"] for u in D.probe_list_for("B-process-init")
                 if u.get("same_process")]
    pop, pop_problems = _verify_namespace_population(
        root, "d250-arm-b", "B-process-init", expected_head,
        authority, attestation, fresh_tags, lambda tag: "accepted",
        extra_expected=set(same_tags))
    problems.extend(pop_problems)
    same, same_problems = _verify_same_process_units(
        root, "d250-arm-b", "B-process-init", expected_head,
        authority, attestation)
    problems.extend(same_problems)
    return {"fresh": pop, "same_process": same}, problems


def _arm_c_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any],
                 ) -> tuple[dict[str, Any], list[str]]:
    plan = D.probe_list_for("C-cpu-threads")
    default_tags = [u["tag"] for u in plan if "thr-default" in u["tag"]]
    serial_tags = [u["tag"] for u in plan if "thr1" in u["tag"]]
    problems: list[str] = []
    default_pop, default_problems = _verify_namespace_population(
        root, "d250-arm-c", "C-cpu-threads", expected_head,
        authority, attestation, default_tags, lambda tag: "accepted",
        extra_expected=set(serial_tags))
    serial_pop, serial_problems = _verify_namespace_population(
        root, "d250-arm-c", "C-cpu-threads", expected_head,
        authority, attestation, serial_tags, lambda tag: "accepted",
        extra_expected=set(default_tags))
    problems.extend(default_problems)
    problems.extend(serial_problems)
    return {"default": default_pop, "serial": serial_pop}, problems


def _arm_d_facts(root: Path, expected_head: str, authority: dict[str, Any],
                 attestation: dict[str, Any],
                 ) -> tuple[dict[str, Any], list[str]]:
    plan = D.probe_list_for("D-context-transition")
    problems: list[str] = []
    by_length: dict[int, list[dict[str, Any]]] = {}
    for spec in plan:
        length = spec["ladder_length"]
        tag = spec["tag"]
        base = D.namespace_dir(root, "d250-arm-d")
        try:
            fact = _verify_unit_receipt(
                base / tag, "d250-arm-d", "D-context-transition", tag,
                expected_head, authority, attestation, "accepted")
        except (OSError, ValueError, TypeError, KeyError,
                json.JSONDecodeError) as exc:
            problems.append(f"D: malformed retained unit {tag}: {exc}")
            continue
        log_raw = (base / tag / "server.log").read_bytes()
        by_length.setdefault(length, []).append({
            **fact, "prompt_progress_counts": _ladder_split_shapes(
                log_raw.decode("utf-8", errors="replace"))})
    unplanned = _unplanned_arm_d_units(root)
    if unplanned:
        problems.append(f"D: unplanned current units: {unplanned}")
    return {"by_length": by_length}, problems


def _unplanned_arm_d_units(root: Path) -> list[str]:
    base = D.namespace_dir(root, "d250-arm-d")
    if base.is_symlink() or not base.is_dir():
        return []
    planned = {u["tag"] for u in D.probe_list_for("D-context-transition")}
    found = {c.name for c in base.iterdir()
             if c.is_dir() and not c.is_symlink() and not c.name.endswith(
                 "-quarantined")}
    unplanned = found - planned
    # ladder units' tag prefix case-<len> differs from the frozen
    # case vocabulary; validate the ladder shape lexically
    return sorted(t for t in unplanned
                  if UNIT_SAFE_TAG.fullmatch(t)) or sorted(unplanned)


# ---------------------------------------------------------------------------
# Terminal derivation (offline, retained-byte, fail-closed)
# ---------------------------------------------------------------------------

def derive_terminal(evidence_root: Path, expected_head: str, *,
                    repo_root: Path | None = None,
                    authority_fetcher: Any = None,
                    contrast_root: Path | None = None,
                    github_api: str = "https://api.github.com",
                    ) -> dict[str, Any]:
    """Derive the Issue #250 terminal from the retained evidence tree.

    No caller-supplied determinism/factor/terminal/summary values are
    accepted. Authority for each consumed namespace is LIVE-fetched
    through the canonical seam (production default
    ``issue250_physical.fetch_dispatch_authority``); the retained
    receipts must bind exactly the fetched payload. The campaign
    model attestations (opening + closing) are terminal preconditions.
    ``authority_fetcher`` is a TEST-ONLY injection seam; production
    callers pass nothing, which resolves to the REAL live fetcher.

    Sequential law: A always; B required iff A's CPU-only varies; C
    required iff B leaves variation; D required iff A-C do not
    localize. UNRESOLVED only after all REACHABLE arms are complete.
    """
    root = Path(evidence_root)
    if (not isinstance(expected_head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_head)):
        return _blocked(["expected head is not a 40-hex sha"])
    if repo_root is None:
        # production callers must pass the campaign repo root
        # explicitly (no silent cwd trust)
        return _blocked(["repo_root is required for terminal derivation"])

    # Campaign model attestation preconditions (opening + closing).
    attestation: dict[str, Any] | None = None
    try:
        opening_path = root / P.MODEL_ATTESTATION_OPEN_NAME
        if opening_path.is_symlink() or not opening_path.is_file():
            raise ValueError("opening attestation missing or symlink")
        opening = json.loads(opening_path.read_bytes())
        P.validate_model_attestation(opening, expected_head)
        closing_path = root / P.MODEL_ATTESTATION_CLOSE_NAME
        if closing_path.is_symlink() or not closing_path.is_file():
            raise ValueError("closing attestation missing or symlink")
        closing = json.loads(closing_path.read_bytes())
        P.validate_closing_attestation(closing, opening)
        attestation = opening
    except (OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError, D.DiagnosticError) as exc:
        return _blocked([f"campaign model attestation invalid: {exc}"])
    if attestation is None:  # defensive narrowing; unreachable
        return _blocked(["campaign model attestation invalid"])

    # Live authority for the FIRST reachable namespace decides the
    # ladder walk; every namespace consumed here is fetched live and
    # every retained receipt must bind it exactly.
    reduction: dict[str, Any] = {"arms": {}, "contrast": None}
    problems: list[str] = []

    def _fetch(namespace: str, arm: str) -> dict[str, Any] | None:
        try:
            payload = P.require_live_dispatch(
                repo_root, expected_head, namespace,
                revalidate_authority=authority_fetcher,
                github_api=github_api)
        except Exception as exc:  # network/OS/git loss fails closed
            problems.append(
                f"live dispatch authority for {namespace} rejected: {exc}")
            return None
        if payload.get("arm") != arm:
            problems.append(
                f"live dispatch for {namespace} binds arm "
                f"{payload.get('arm')!r} != {arm!r}")
            return None
        return payload

    # ---------------- Arm A (always required) ----------------
    authority_a = _fetch("d250-arm-a", "A-vulkan-necessity")
    if authority_a is None:
        return _blocked(problems, reduction)
    arm_a, a_problems = _arm_a_facts(
        root, expected_head, authority_a, attestation,
        contrast_root or root)
    problems.extend(a_problems)
    reduction["arms"]["A-vulkan-necessity"] = arm_a
    reduction["contrast"] = arm_a.get("contrast")
    if problems:
        return _blocked(problems, reduction)
    cpu_units = arm_a.get("units", [])
    cpu = _condition_determinism(cpu_units)
    arm_a["cpu_only_devnone"] = cpu
    contrast = arm_a.get("contrast") or {}
    contrast_varies = (contrast.get("row_deterministic") is False)

    if cpu["deterministic"] and contrast_varies:
        # A localizes: backend-participation boundary.
        return _ok(LOCALIZED, reduction, {
            "localized_factor":
                LOCALIZED_FACTORS["A-vulkan-necessity"],
            "arm": "A-vulkan-necessity",
            "deterministic_condition":
                "cpu-only -dev none (5/5 identical rows)",
            "nondeterministic_condition":
                "accepted #248 retained ngl=1 case-3072 (row-varying)",
            "contrast_provenance": D.CONTRAST_PROVENANCE,
        })
    if cpu["deterministic"] and not contrast_varies:
        # Contrast destroyed (e.g. retained bytes no longer vary): the
        # planned comparison is destroyed; honest UNRESOLVED per the
        # frozen rule (verify_historical_contrast already fails closed
        # on contradiction, so this branch is defensive only).
        return _ok(UNRESOLVED, reduction, {
            "reason": "CPU-only deterministic but the accepted contrast "
                      "did not establish nonzero-Vulkan variation",
        })
    if not cpu["deterministic"] and cpu["n"] and not cpu[
            "rows_strictly_identical"]:
        # CPU-only VARIES: Vulkan participation NOT necessary.
        # Arm B becomes REQUIRED; no terminal is emitted here.
        pass
    else:
        # cpu n==0 or ambiguous identical rows below claim threshold
        return _blocked(
            ["arm A CPU-only determinism incomplete/ambiguous"], reduction)

    # ---------------- Arm B (required: A CPU-only varies) ----------
    authority_b = _fetch("d250-arm-b", "B-process-init")
    if authority_b is None:
        return _blocked(problems, reduction)
    arm_b, b_problems = _arm_b_facts(
        root, expected_head, authority_b, attestation)
    problems.extend(b_problems)
    reduction["arms"]["B-process-init"] = arm_b
    if problems:
        return _blocked(problems, reduction)
    fresh = _condition_determinism(arm_b["fresh"].get("units", []))
    same = _condition_determinism(arm_b["same_process"].get("units", []))
    arm_b["cpu_fresh"] = fresh
    arm_b["cpu_same_process"] = same
    if fresh["deterministic"]:
        # A varied but B's fresh condition is deterministic —
        # contradictory across arms; fail closed per the frozen rule.
        return _blocked(
            ["arm B fresh-process CPU-only deterministic while arm A "
             "CPU-only varied (contradictory evidence)"], reduction)
    if same["deterministic"]:
        return _ok(LOCALIZED, reduction, {
            "localized_factor":
                LOCALIZED_FACTORS["B-process-init"],
            "arm": "B-process-init",
            "deterministic_condition":
                "same-process CPU-only repeats (one runtime, id_slot=3, "
                "proven full recompute)",
            "nondeterministic_condition":
                "fresh-process CPU-only repeats (-dev none)",
        })
    if not (fresh["n"] and same["n"] and not same["deterministic"]):
        return _blocked(["arm B evidence incomplete"], reduction)

    # ---------------- Arm C (required: B leaves variation) ---------
    authority_c = _fetch("d250-arm-c", "C-cpu-threads")
    if authority_c is None:
        return _blocked(problems, reduction)
    arm_c, c_problems = _arm_c_facts(
        root, expected_head, authority_c, attestation)
    problems.extend(c_problems)
    reduction["arms"]["C-cpu-threads"] = arm_c
    if problems:
        return _blocked(problems, reduction)
    default = _condition_determinism(arm_c["default"].get("units", []))
    serial = _condition_determinism(arm_c["serial"].get("units", []))
    arm_c["cpu_default_threads"] = default
    arm_c["cpu_serial"] = serial
    if serial["deterministic"]:
        # NOTE: default has only 2 reproduction units — a deterministic
        # CLAIM needs 5, but the default condition's VARIATION is
        # already established by Arms A/B fresh CPU-only units (same
        # condition geometry); variation is what C contrasts against.
        return _ok(LOCALIZED, reduction, {
            "localized_factor": LOCALIZED_FACTORS["C-cpu-threads"],
            "arm": "C-cpu-threads",
            "deterministic_condition":
                "serial CPU-only -t 1 -tb 1 (5/5 identical rows)",
            "nondeterministic_condition":
                "default-threading CPU-only (varies; established at "
                "arms A/B fresh CPU-only units)",
            "default_condition_units": default["n"],
        })
    if not (serial["n"] and not serial["deterministic"]):
        return _blocked(["arm C evidence incomplete"], reduction)

    # ---------------- Arm D (required: A-C did not localize) -------
    authority_d = _fetch("d250-arm-d", "D-context-transition")
    if authority_d is None:
        return _blocked(problems, reduction)
    arm_d, d_problems = _arm_d_facts(
        root, expected_head, authority_d, attestation)
    problems.extend(d_problems)
    reduction["arms"]["D-context-transition"] = arm_d
    if problems:
        return _blocked(problems, reduction)
    ladder_facts: dict[int, dict[str, Any]] = {}
    for length, units in sorted(arm_d["by_length"].items()):
        if len(units) < 2:
            problems.append(f"D: length {length} lacks repeat pairs")
            continue
        row_tuples = {tuple(u["row_sha256"]) for u in units}
        ladder_facts[length] = {
            "row_deterministic": len(row_tuples) == 1,
            "prompt_progress_counts": units[0]["prompt_progress_counts"],
            "unit_count": len(units),
        }
    if problems or len(ladder_facts) != len(D.ARM_D_LADDER_LENGTHS):
        return _blocked(problems or ["arm D ladder incomplete"], reduction)
    fired = _evaluate_transition_predicates(ladder_facts)
    arm_d["ladder"] = ladder_facts
    if fired is not None:
        return _ok(LOCALIZED, reduction, {
            "localized_factor": LOCALIZED_FACTORS["D-context-transition"],
            "arm": "D-context-transition",
            "transition_predicate": fired["predicate"],
            "boundary": fired["boundary"],
            "mechanism": fired["mechanism"],
        })
    # All reachable arms complete; no causal mechanism bound.
    return _ok(UNRESOLVED, reduction, {
        "reason": "bounded controls reproduce the instability but no "
                  "smallest runtime/execution boundary was mechanically "
                  "bound by the frozen transition predicates",
        "ladder": {str(k): v["row_deterministic"]
                   for k, v in ladder_facts.items()},
    })
