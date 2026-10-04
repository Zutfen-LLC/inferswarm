#!/usr/bin/env python3
"""Issue #270 (R8-I6) — accepted comparator/2 semantics, re-declared.

PR #242 (the #241 qualification branch carrying
scripts/issue241_comparator.py) was CLOSED UNMERGED, so the
self-containment law forbids importing it: this module re-declares the
accepted continuous comparator/2 validation semantics LOCALLY, byte-for-
byte in meaning, and tests/test_issue270_authority.py cross-verifies the
frozen identity constants against the accepted main-resident authority.

Accepted semantics (unchanged from comparator/2; DO NOT redefine):

  Reference arm — one continuous request per case:
    capture the untouched full-vocabulary FP32 consumer row at decision
    d; the greedy winner IS the reference winner and enters the live
    state naturally; repeat through 8 decisions.

  Candidate arm — one continuous request per case:
    capture the untouched full-vocabulary FP32 row for the same decision
    and same canonical reference prefix; record the candidate winner
    (diagnostic only); AFTER row capture force/append the REFERENCE
    token; continue live state to d+1; repeat through 8 decisions.

Invariants validated here (mechanically, from retained bytes):

  * exactly 8 reference rows and 8 candidate rows per case;
  * candidate forced-token sequence == reference winners at every
    decision (no candidate token may enter a later acceptance-bearing
    prefix);
  * reference arm never forces a token;
  * RAW-ROW CUSTODY IS BYTE-BOUND: retained bytes are read through a
    custody-checked reader, required to be exactly ROW_BYTES long,
    independently SHA-256-hashed, and the computed digest must EQUAL the
    receipt claim before FP32 finiteness is evaluated;
  * determinism compares INDEPENDENTLY COMPUTED row-byte digests, never
    two claimed digest strings;
  * metadata rows: exactly positions 0..7, sampled_winner agreement,
    reference forced_token == -1, candidate forced_token == winners[d];
  * observer inert when disabled (disabled-hook tokens equal canonical
    no-hook tokens; disabled/canonical runs emit NO observer output);
  * run receipts cross-bind case/subject/runtime/authority identities.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import issue270_authority as C

SCHEMA = "inferswarm.issue270.phase3-comparator-v2-validation/1"
RUN_SCHEMA = "inferswarm.issue270.comparator-v2-run/1"

Digest64_RE = re.compile(r"^[0-9a-f]{64}$")

# Every field a comparator/2 arm receipt must mechanically bind. The
# reducer validates each one; the cross-binding set (equal across both
# arms) is CROSS_BOUND_FIELDS.
RUN_RECEIPT_BOUND_FIELDS = (
    "campaign", "comparator_id", "case_id", "host", "arm",
    "bdf", "icd", "selector", "cuda_visible_devices", "ngl",
    "fixture_ladder_sha256", "prompt_token_ids", "prompt_len",
    "prompt_text_sha256", "model_members", "llama_source_pin",
    "server_sha256", "build_flags", "request_contract",
    "excluded_device_residency_bytes", "process_attribution",
    "dispatch_authority",
)
CROSS_BOUND_FIELDS = (
    "case_id", "prompt_token_ids", "fixture_ladder_sha256", "ngl",
    "model_members", "llama_source_pin", "server_sha256", "build_flags",
    "request_contract", "comparator_id", "dispatch_authority",
)


def load_run_receipt(path: Path) -> dict[str, Any]:
    receipt = json.loads(Path(path).read_text())
    if not isinstance(receipt, dict):
        raise ValueError("run receipt must be a JSON object")
    if receipt.get("schema") != RUN_SCHEMA:
        raise ValueError("run receipt schema mismatch")
    return receipt


# ---------------------------------------------------------------------------
# Row-file custody
# ---------------------------------------------------------------------------

def _reject_row_path(rel: Any) -> str | None:
    """Return a rejection reason for a structurally invalid row path."""
    if not isinstance(rel, str) or not rel:
        return "row path must be a non-empty relative string"
    if rel.startswith("/") or PurePosixPath(rel).is_absolute():
        return f"absolute row path rejected: {rel!r}"
    parts = PurePosixPath(rel).parts
    if ".." in parts:
        return f"row path traversal rejected: {rel!r}"
    return None


def custody_row_reader(root: Path) -> Callable[[str], bytes]:
    """Build a fail-closed row reader bound beneath one evidence root.

    Rejects absolute paths, ``..`` traversal, escape from the resolved
    root, symlinks/aliases anywhere on the path, non-regular files, and
    missing/unreadable files.
    """
    root = Path(root).resolve()

    def read(rel: str) -> bytes:
        reason = _reject_row_path(rel)
        if reason:
            raise ValueError(reason)
        parts = PurePosixPath(rel).parts
        candidate = root.joinpath(*parts)
        probe = root
        for part in parts:
            probe = probe / part
            if probe.is_symlink():
                raise ValueError(f"symlink/alias row rejected at {probe}")
        try:
            inside = probe.relative_to(root)
        except ValueError:
            raise ValueError(
                f"row path escapes the evidence root: {rel!r}") from None
        del inside
        if not probe.exists():
            raise ValueError(f"row file missing: {rel!r}")
        if not probe.is_file():
            raise ValueError(f"row is not a regular file: {rel!r}")
        try:
            return probe.read_bytes()
        except OSError as exc:
            raise ValueError(f"row file unreadable: {rel!r} ({exc})") from exc

    return read


def validate_rows_finite(row_bytes: bytes) -> list[int]:
    """Decode FP32 rows and return indices of non-finite values."""
    if len(row_bytes) % 4:
        raise ValueError("row bytes not a whole number of floats")
    values = struct.unpack(f"<{len(row_bytes) // 4}f", row_bytes)
    return [i for i, v in enumerate(values)
            if v != v or v in (float("inf"), float("-inf"))]


# ---------------------------------------------------------------------------
# Per-arm validation
# ---------------------------------------------------------------------------

def _fixture_authority() -> dict[str, Any]:
    return C.load_fixtures(C.ROOT)


def _process_attribution_problems(receipt: dict[str, Any],
                                  arm_const: dict[str, Any],
                                  ngl: Any) -> list[str]:
    problems: list[str] = []
    pa = receipt.get("process_attribution")
    if not isinstance(pa, dict):
        return ["process attribution missing (pid/argv/env)"]
    pid = pa.get("server_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        problems.append("process attribution lacks a live server pid")
    env = pa.get("server_env") or {}
    selector = arm_const["selector"]
    for key, expected in selector.items():
        if env.get(key) != expected:
            problems.append(f"server env {key}={env.get(key)!r} != {expected!r}")
    if env.get("VK_ICD_FILENAMES") != arm_const["icd"]:
        problems.append("server env VK_ICD_FILENAMES != arm ICD")
    if env.get("LLAMA_OBSERVE_CAPTURE") not in ("8", 8, None):
        if str(env.get("LLAMA_OBSERVE_CAPTURE")) != "8":
            problems.append("observer capture count != 8")
    argv = pa.get("server_argv")
    if not isinstance(argv, list) or not argv:
        problems.append("server argv missing")
        return problems
    argv_s = [str(a) for a in argv]
    if not any(str(C.MODEL_DIR) in a for a in argv_s):
        problems.append("server argv does not bind the frozen model subject")
    if "-ngl" in argv_s:
        i = argv_s.index("-ngl")
        if i + 1 >= len(argv_s) or argv_s[i + 1] != str(ngl):
            problems.append(f"server argv -ngl != frozen ngl {ngl}")
    else:
        problems.append("server argv lacks -ngl")
    return problems


def _dispatch_authority_problems(receipt: dict[str, Any]) -> list[str]:
    da = receipt.get("dispatch_authority")
    if not isinstance(da, dict):
        return ["dispatch-authority receipt missing from run receipt"]
    problems: list[str] = []
    head = da.get("head_sha")
    if not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        problems.append("dispatch-authority head_sha malformed")
    if da.get("issue") != C.ISSUE:
        problems.append("dispatch-authority issue mismatch")
    if da.get("dispatch_phrase") != C.DISPATCH_PHRASE:
        problems.append("dispatch-authority phrase mismatch")
    if (not isinstance(da.get("comment_id"), int)
            or isinstance(da.get("comment_id"), bool)
            or da.get("comment_id", 0) <= 0):
        problems.append("dispatch-authority comment_id malformed")
    if not isinstance(da.get("commenter"), str) or not da.get("commenter"):
        problems.append("dispatch-authority commenter missing")
    if da.get("commenter_association") not in ("OWNER", "MEMBER"):
        problems.append("dispatch-authority commenter association not OWNER/MEMBER")
    return problems


def validate_arm_receipt(receipt: dict[str, Any], arm: str,
                         row_reader: Any,
                         frozen_reference: dict[str, Any]) -> dict[str, Any]:
    """Validate one comparator/2 arm run receipt + raw rows.

    arm is "reference" (RTX 3060) or "candidate" (one V340L die). Every
    claimed row digest is re-derived from the retained bytes; the
    computed digest must equal the claim BEFORE finiteness is checked.
    """
    problems: list[str] = []
    if receipt.get("arm") != arm:
        problems.append(f"arm mismatch: {receipt.get('arm')!r} != {arm!r}")
    if receipt.get("campaign") != C.CAMPAIGN_ID:
        problems.append("campaign mismatch (not the issue270 R8-I6 campaign)")
    if receipt.get("comparator_id") != C.COMPARATOR_V2_ID:
        problems.append(
            f"comparator id mismatch: {receipt.get('comparator_id')!r}")
    expected_host = (C.REFERENCE_HOST if arm == "reference"
                     else C.CANDIDATE_HOST)
    if receipt.get("host") != expected_host:
        problems.append(f"arm host must be {expected_host}")
    selector = receipt.get("selector") or {}
    arm_const = receipt.get("_arm_const") or {}
    if selector != arm_const.get("selector"):
        problems.append(f"selector drift: {selector!r}")
    if receipt.get("icd") != arm_const.get("icd"):
        problems.append("ICD drift")
    if receipt.get("cuda_visible_devices") != "-1":
        problems.append("CUDA not fenced off")
    if receipt.get("bdf") != arm_const.get("bdf"):
        problems.append(
            f"bdf mismatch: {receipt.get('bdf')!r} != "
            f"{arm_const.get('bdf')!r}")
    subject = receipt.get("subject_identity")
    if not isinstance(subject, dict):
        problems.append("run receipt lacks the frozen subject-identity block")
    elif arm == "reference":
        # The reference arm is bound to the ACCEPTED #248 identity.
        for field, want in frozen_reference.items():
            got = subject.get(field)
            if got != want:
                problems.append(
                    f"{arm} frozen subject-identity drift {field}: "
                    f"{got!r} != {want!r}")
    else:
        # The candidate arm is bound to the Phase-1 frozen candidate
        # subject carried on the receipt itself (the freeze record is
        # authenticated separately by the producer/reducer; here the
        # requirement is presence + internal consistency: host/BDF/
        # CUDA exclusion must agree with the receipt top level).
        for field in ("host", "bdf"):
            got = subject.get(field)
            if got != receipt.get(field):
                problems.append(
                    f"{arm} subject-identity inconsistent {field}: "
                    f"{got!r} != {receipt.get(field)!r}")
    ngl = receipt.get("ngl")
    if not isinstance(ngl, int) or isinstance(ngl, bool) or ngl != C.SELECTED_PLACEMENT_NGL:
        problems.append(f"ngl {ngl!r} != frozen placement {C.SELECTED_PLACEMENT_NGL}")

    case_id = receipt.get("case_id")
    try:
        C.validate_case(case_id or "")
    except C.AuthorityError as exc:
        problems.append(f"case discipline: {exc}")
    try:
        fixtures = _fixture_authority()
        fx = fixtures.get(case_id) if case_id else None
    except Exception as exc:  # fixture authority failure = fail closed
        fx = None
        problems.append(f"fixture authority unreadable: {exc}")
    if fx is None:
        problems.append(f"case {case_id!r} absent from the fixture authority")
    else:
        if receipt.get("fixture_ladder_sha256") != C.FIXTURE_LADDER_SHA256:
            problems.append("fixture ladder digest mismatch")
        if receipt.get("prompt_token_ids") != fx["prompt_token_ids"]:
            problems.append(
                "prompt token ids do not match the frozen fixture authority")
        if receipt.get("prompt_len") != fx["rendered_length"]:
            problems.append("prompt length mismatch vs fixture authority")
        want_text = hashlib.sha256(
            fx["prompt_text"].encode()).hexdigest()
        if receipt.get("prompt_text_sha256") != want_text:
            problems.append("prompt text digest mismatch vs fixture authority")

    if receipt.get("model_members") != C.MODEL_MEMBER_SHA256:
        problems.append("model member hashes do not match the frozen set")
    if receipt.get("llama_source_pin") != C.LLAMA_SOURCE_PIN:
        problems.append("llama.cpp source pin mismatch")
    server_sha = receipt.get("server_sha256")
    if not isinstance(server_sha, str) or Digest64_RE.fullmatch(server_sha) is None:
        problems.append("executed server/binary sha256 malformed")
    elif server_sha != C.COMPARATOR_SHA256:
        problems.append("executed server != accepted comparator binary")
    if receipt.get("build_flags") != arm_const.get("build_flags"):
        problems.append("build flags drift")
    if receipt.get("request_contract") != C.REQUEST_CONTRACT:
        problems.append("request contract drift")

    # Non-participating second-die / sibling-device residency evidence.
    excluded = receipt.get("excluded_device_residency_bytes")
    want_excluded = tuple(arm_const.get("excluded_bdfs", ()))
    if not isinstance(excluded, dict) or set(excluded) != set(want_excluded):
        problems.append(
            f"excluded-device residency evidence must cover exactly "
            f"{sorted(want_excluded)}")
    else:
        for bdf, noise in sorted(excluded.items()):
            if not isinstance(noise, int) or isinstance(noise, bool) \
                    or noise < 0 or noise > C.EXCLUDED_NOISE_BYTES:
                problems.append(
                    f"excluded device {bdf} over the residency noise "
                    f"bound ({noise!r} > {C.EXCLUDED_NOISE_BYTES})")

    problems.extend(_process_attribution_problems(receipt, arm_const, ngl))
    problems.extend(_dispatch_authority_problems(receipt))

    rows = receipt.get("rows") or {}
    if set(rows) != {str(d) for d in range(C.DECISIONS)}:
        problems.append(f"row decisions != 8: {sorted(rows)}")
    meta = receipt.get("meta_rows") or []
    if len(meta) != C.DECISIONS:
        problems.append(f"meta rows != 8: {len(meta)}")

    # Reference-prefix identity / forcing contract
    winners = receipt.get("sampled_winners") or []
    forced = receipt.get("forced_tokens") or []
    if arm == "reference":
        if len(winners) != C.DECISIONS:
            problems.append("reference sampled winners != 8")
        real_forced = [t for t in forced if t not in (-1, None)]
        if real_forced:
            problems.append("reference arm must not force tokens")
    else:
        if len(winners) != C.DECISIONS:
            problems.append("candidate sampled winners != 8")
        if len(forced) != C.DECISIONS:
            problems.append("candidate forced tokens != 8")

    for d, entry in sorted(rows.items()):
        digest = entry.get("sha256")
        nbytes = entry.get("bytes")
        if not isinstance(digest, str) or Digest64_RE.fullmatch(digest) is None:
            problems.append(f"row {d} digest malformed")
        if nbytes != C.ROW_BYTES:
            problems.append(f"row {d} bytes {nbytes} != {C.ROW_BYTES}")
        path = entry.get("path")
        reason = _reject_row_path(path)
        if reason:
            problems.append(f"row {d} {reason}")
    if problems:
        return {"arm": arm, "valid": False, "problems": problems}

    # RAW-ROW CUSTODY: read the retained bytes, require the exact row
    # size, compute SHA-256 FROM THOSE BYTES, and require computed ==
    # claimed digest. Only then evaluate FP32 finiteness.
    row_digests: dict[str, str] = {}
    for d, entry in sorted(rows.items()):
        try:
            raw = row_reader(entry["path"])
        except Exception as exc:
            problems.append(f"row {d} custody read failed: {exc}")
            continue
        if len(raw) != C.ROW_BYTES:
            problems.append(f"row {d} raw bytes {len(raw)} != {C.ROW_BYTES}")
            continue
        computed = hashlib.sha256(raw).hexdigest()
        if computed != entry["sha256"]:
            problems.append(
                f"row {d} digest mismatch: independently computed "
                f"{computed} != claimed {entry['sha256']}")
            continue
        row_digests[str(d)] = computed
        nonfinite = validate_rows_finite(raw)
        if nonfinite:
            problems.append(f"row {d} has {len(nonfinite)} non-finite values")
    return {
        "arm": arm, "valid": not problems, "problems": problems,
        "row_digests_independent": row_digests,
    }


# ---------------------------------------------------------------------------
# Cross-arm validation
# ---------------------------------------------------------------------------

def _cross_binding_problems(reference: dict[str, Any],
                            candidate: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for field in CROSS_BOUND_FIELDS:
        if reference.get(field) != candidate.get(field):
            problems.append(
                f"reference/candidate {field} mismatch — the pair must "
                f"cross-bind to the same historical case/subject/runtime")
    if reference.get("case_id") != candidate.get("case_id"):
        problems.append(
            f"reference/candidate case mismatch: "
            f"{reference.get('case_id')!r} != {candidate.get('case_id')!r}")
    if reference.get("ngl") != candidate.get("ngl"):
        problems.append(
            f"reference/candidate ngl mismatch: "
            f"{reference.get('ngl')!r} != {candidate.get('ngl')!r}")
    ref_winners = reference.get("sampled_winners") or []
    cand_forced = candidate.get("forced_tokens") or []
    if len(ref_winners) == C.DECISIONS and len(cand_forced) == C.DECISIONS:
        if cand_forced != ref_winners:
            problems.append(
                "candidate forced prefix != reference winners — a candidate "
                "token may enter a later acceptance-bearing prefix")
    return problems


def _meta_row_problems(receipt: dict[str, Any], arm: str,
                       reference_winners: list[int] | None) -> list[str]:
    problems: list[str] = []
    meta = receipt.get("meta_rows") or []
    if [m.get("pos") for m in meta] != list(range(C.DECISIONS)):
        problems.append(f"{arm} meta rows are not exactly positions 0..7")
        return problems
    winners = receipt.get("sampled_winners") or []
    forced = receipt.get("forced_tokens") or []
    for d, m in enumerate(meta):
        if m.get("sampled_winner") != (winners[d] if d < len(winners)
                                       else None):
            problems.append(
                f"{arm} meta row {d} sampled_winner disagrees with "
                f"sampled_winners[{d}]")
        want_forced = (-1 if arm == "reference"
                       else (forced[d] if d < len(forced) else None))
        if m.get("forced_token") != want_forced:
            problems.append(
                f"{arm} meta row {d} forced_token disagrees with the "
                f"receipt forced-token array")
        if arm == "candidate" and reference_winners is not None and \
                d < len(reference_winners) and \
                m.get("forced_token") != reference_winners[d]:
            problems.append(
                f"candidate meta row {d} forced_token != reference "
                f"winner at {d} — a candidate token may enter a later "
                f"acceptance-bearing prefix")
    return problems


def validate_pair(reference: dict[str, Any], candidate: dict[str, Any],
                  row_reader: Any,
                  frozen_reference_identity: dict[str, Any]) -> dict[str, Any]:
    """Cross-arm validation: same-case binding + reference prefix authority."""
    problems: list[str] = []
    ref_winners = reference.get("sampled_winners") or []
    cand_winners = candidate.get("sampled_winners") or []

    problems.extend(_cross_binding_problems(reference, candidate))
    problems.extend(_meta_row_problems(reference, "reference", None))
    problems.extend(_meta_row_problems(candidate, "candidate", ref_winners))

    diag = {
        "first_divergent_decision": next(
            (d for d, (a, b) in enumerate(zip(cand_winners, ref_winners))
             if a != b), None),
        "winner_agreement": sum(
            1 for a, b in zip(cand_winners, ref_winners) if a == b),
        "semantics": "comparator/2 continuous (unchanged)",
    }
    ref_v = validate_arm_receipt(reference, "reference", row_reader,
                                 frozen_reference_identity)
    cand_v = validate_arm_receipt(candidate, "candidate", row_reader,
                                  frozen_reference_identity)
    problems.extend(ref_v["problems"])
    problems.extend(cand_v["problems"])
    return {
        "schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
        "comparator_id": C.COMPARATOR_V2_ID,
        "case_id": reference.get("case_id"),
        "matched_ngl": reference.get("ngl"),
        "reference": ref_v, "candidate": cand_v,
        "problems": problems,
        "validated": not problems,
        "diagnostic": diag,
    }


def validate_determinism(repeat_a: dict[str, Any], repeat_b: dict[str, Any],
                         row_reader: Any,
                         row_reader_b: Any | None = None) -> dict[str, Any]:
    """Repeat requests under each arm must be byte-identical per decision.

    Compares INDEPENDENTLY COMPUTED SHA-256 digests of the retained raw
    bytes — never two claimed receipt digest strings — and additionally
    requires each computed digest to equal that receipt's own claim.
    """
    problems = []
    ra, rb = repeat_a.get("rows") or {}, repeat_b.get("rows") or {}
    if set(ra) != set(rb):
        problems.append("repeat run row sets differ")
    computed: dict[str, dict[str, str]] = {}
    for label, rows, receipt, reader in (
            ("a", ra, repeat_a, row_reader),
            ("b", rb, repeat_b, row_reader_b or row_reader)):
        per: dict[str, str] = {}
        for d in sorted(rows):
            try:
                raw = reader(rows[d]["path"])
            except Exception as exc:
                problems.append(
                    f"repeat {label} decision {d} custody read failed: {exc}")
                continue
            digest = hashlib.sha256(raw).hexdigest()
            if digest != rows[d].get("sha256"):
                problems.append(
                    f"repeat {label} decision {d} claimed digest != "
                    f"independently computed bytes digest")
            per[d] = digest
        computed[label] = per
    for d in sorted(set(computed["a"]) & set(computed["b"])):
        if computed["a"][d] != computed["b"][d]:
            problems.append(
                f"decision {d} repeat rows differ (independently "
                f"computed digests mismatch)")
    return {
        "schema": "inferswarm.issue270.phase3-determinism/1",
        "case_id": repeat_a.get("case_id"),
        "deterministic": not problems, "problems": problems,
        "row_digests_independent": computed,
    }


def validate_inertness(disabled_run_tokens: list[int],
                       canonical_run_tokens: list[int],
                       disabled_emitted_observer_output: bool = False,
                       canonical_emitted_observer_output: bool = False,
                       ) -> dict[str, Any]:
    """Observer disabled => tokens equal the no-hook canonical run AND
    neither run emitted any observer artifact (inertness is behavioral,
    not token-only)."""
    problems: list[str] = []
    if list(disabled_run_tokens or []) != list(canonical_run_tokens or []):
        problems.append("disabled-observer tokens differ from canonical")
    if disabled_emitted_observer_output:
        problems.append("observer-disabled run emitted observer output")
    if canonical_emitted_observer_output:
        problems.append("canonical no-hook run emitted observer output")
    return {
        "schema": "inferswarm.issue270.phase3-inertness/1",
        "inert": not problems, "problems": problems,
    }
