#!/usr/bin/env python3
"""Issue #241 Phase 3: comparator/2 historical-only validation reducer.

Validates the prospective continuous canonical-reference-prefix observer
against the frozen comparator/2 semantics USING EXCLUDED HISTORICAL
FIXTURES ONLY. Proves, from retained receipt/row evidence:

  - exactly 8 reference rows and 8 candidate rows per case;
  - exact reference prefix identity at every decision (candidate
    forced-token sequence == reference winners);
  - no candidate token can enter a later acceptance-bearing token
    prefix (the forced prefix is reference-authored at every decision);
  - RAW-ROW CUSTODY IS BYTE-BOUND: for every row the retained bytes are
    read through a custody-checked reader, required to be exactly
    ROW_BYTES long, independently SHA-256-hashed, and the computed
    digest must EQUAL the receipt's claimed digest before FP32
    finiteness is even evaluated — a claimed digest alone proves
    nothing (correction: the reducer previously format-checked the
    claimed digest and never hashed the bytes);
  - row paths are custody-hardened: absolute paths, `..` traversal,
    escape from the evidence/run root, symlinks/aliases, and
    non-regular/missing/unreadable files all fail closed;
  - determinism compares INDEPENDENTLY COMPUTED row-byte digests, never
    two untrusted receipt digest strings;
  - the run receipts cross-bind the pair to the EXACT case, subject
    prompt, matched ngl, host, arm/device/BDF/GPU identity, ICD, CUDA
    exclusion, excluded-device residency, the three frozen model-member
    hashes, the llama.cpp pin, the comparator/2 patched-source sha256,
    the executed server sha256, frozen build flags, the frozen request
    contract, process/argv/env attribution, the dispatch-authority
    receipt, and the comparator/2 implementation identity;
  - metadata rows are validated mechanically: exactly positions 0..7,
    `sampled_winner` agrees with `sampled_winners[d]`, reference
    `forced_token == -1`, candidate `forced_token == forced_tokens[d]`,
    and every candidate meta forced token equals the REFERENCE winner
    at that decision;
  - observer inert when disabled (disabled-hook run tokens equal the
    canonical no-hook run tokens);
  - no CUDA/fallback/wrong-device participation.

v1-vs-v2 row differences are recorded as DIAGNOSTIC ONLY. Byte equality
between comparator versions is NOT required and NOT checked as a gate.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C
import issue241_dispatch as dispatch

SCHEMA = "inferswarm.issue241.phase3-comparator-v2-validation/1"
RUN_SCHEMA = "inferswarm.issue241.comparator-v2-run/2"

Digest64_RE = re.compile(r"^[0-9a-f]{64}$")

# Every field a comparator/2 arm receipt must mechanically bind. The
# reducer validates each one; the cross-binding set (equal across both
# arms) is CROSS_BOUND_FIELDS.
RUN_RECEIPT_BOUND_FIELDS = (
    "campaign", "comparator_id", "case_id", "host", "arm",
    "bdf", "icd", "selector", "cuda_visible_devices", "ngl",
    "fixture_ladder_sha256", "prompt_token_ids", "prompt_len",
    "prompt_text_sha256", "model_members", "llama_cpp_pin",
    "patched_source_sha256", "server_sha256", "build_flags",
    "request_contract", "excluded_device_residency_mib",
    "process_attribution", "dispatch_authority",
)
CROSS_BOUND_FIELDS = (
    "case_id", "prompt_token_ids", "fixture_ladder_sha256", "ngl",
    "host", "model_members", "llama_cpp_pin", "patched_source_sha256",
    "server_sha256", "build_flags", "request_contract",
    "comparator_id", "dispatch_authority",
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
    """Build a fail-closed row reader bound beneath one run root.

    Rejects absolute paths, `..` traversal, escape from the resolved
    run root, symlinks/aliases anywhere on the path, non-regular
    files, and missing/unreadable files. This is the reader main()
    uses; validate_arm_receipt re-checks path shape itself so even a
    custom reader cannot be fed a path outside the run root.
    """
    root = Path(root).resolve()

    def read(rel: str) -> bytes:
        reason = _reject_row_path(rel)
        if reason:
            raise ValueError(reason)
        # containment beneath the run root (lexical join, NO resolve so
        # symlink components are still visible to the probe below)
        parts = PurePosixPath(rel).parts
        candidate = root.joinpath(*parts)
        # no symlinks/aliases: the leaf AND every intermediate component
        # are checked as raw path components BEFORE any resolution
        probe = root
        for part in parts:
            probe = probe / part
            if probe.is_symlink():
                raise ValueError(
                    f"symlink/alias row rejected at {probe}")
        try:
            inside = probe.relative_to(root)
        except ValueError:
            raise ValueError(
                f"row path escapes the evidence/run root: {rel!r}") from None
        if not probe.exists():
            raise ValueError(f"row file missing: {rel!r}")
        if not probe.is_file():
            raise ValueError(
                f"row is not a regular file: {rel!r}")
        try:
            return probe.read_bytes()
        except OSError as exc:
            raise ValueError(f"row file unreadable: {rel!r} ({exc})") from exc

    return read


def validate_rows_finite(row_bytes: bytes) -> list[int]:
    """Decode FP32 rows and return indices of non-finite values."""
    if len(row_bytes) % 4:
        raise ValueError("row bytes not a whole number of floats")
    values = struct.unpack(f"<{len(row_bytes)//4}f", row_bytes)
    return [i for i, v in enumerate(values) if v != v or v in (
        float("inf"), float("-inf"))]


# ---------------------------------------------------------------------------
# Per-arm validation
# ---------------------------------------------------------------------------

def _fixture_authority() -> dict[str, Any]:
    """Independently derive the accepted prompt identity from the repo."""
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
            problems.append(
                f"server env {key}={env.get(key)!r} != {expected!r}")
    if env.get("VK_ICD_FILENAMES") != arm_const["icd"]:
        problems.append("server env VK_ICD_FILENAMES != arm ICD")
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
            problems.append(
                f"server argv -ngl != matched ngl {ngl}")
    else:
        problems.append("server argv lacks -ngl")
    return problems


def _dispatch_authority_problems(receipt: dict[str, Any]) -> list[str]:
    da = receipt.get("dispatch_authority")
    if not isinstance(da, dict):
        return ["dispatch-authority receipt missing from run receipt"]
    problems: list[str] = []
    if da.get("schema") != dispatch.AUTHORITY_SCHEMA:
        problems.append("dispatch-authority receipt schema mismatch")
    head = da.get("head_sha")
    if not isinstance(head, str) or dispatch.SHA40.fullmatch(head) is None:
        problems.append("dispatch-authority head_sha malformed")
    if da.get("dispatch_phrase") != dispatch.DISPATCH_PHRASE:
        problems.append("dispatch-authority phrase mismatch")
    if not isinstance(da.get("review_id"), int) or isinstance(
            da.get("review_id"), bool):
        problems.append("dispatch-authority review_id malformed")
    if not isinstance(da.get("reviewer"), str) or not da.get("reviewer"):
        problems.append("dispatch-authority reviewer missing")
    return problems


def validate_arm_receipt(receipt: dict[str, Any], arm: str,
                         row_reader: Any) -> dict[str, Any]:
    """Validate one arm's comparator/2 run receipt + raw rows.

    Every claimed row digest is re-derived from the retained bytes; the
    computed digest must equal the claim BEFORE finiteness is checked.
    """
    problems: list[str] = []
    if receipt.get("arm") != arm:
        problems.append(f"arm mismatch: {receipt.get('arm')!r} != {arm!r}")
    if receipt.get("campaign") != C.CAMPAIGN_ID:
        problems.append("campaign mismatch (not the issue241 R8-I3 campaign)")
    if receipt.get("comparator_id") != C.COMPARATOR_V2_ID:
        problems.append(
            f"comparator id mismatch: {receipt.get('comparator_id')!r}")
    if receipt.get("host") != "inferswarm01":
        problems.append("both arms must run on the same host (inferswarm01)")
    selector = receipt.get("selector") or {}
    arm_const = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    if selector != arm_const["selector"]:
        problems.append(f"selector drift: {selector!r}")
    if receipt.get("icd") != arm_const["icd"]:
        problems.append("ICD drift")
    if receipt.get("cuda_visible_devices") != "-1":
        problems.append("CUDA not fenced off")
    if receipt.get("bdf") != arm_const["bdf"]:
        problems.append(
            f"bdf mismatch: {receipt.get('bdf')!r} != {arm_const['bdf']!r}")
    # arm device identity: reference = exact RTX 3060 UUID; candidate =
    # AMD PCI vendor/device identity + frozen RADV physical-device name.
    if arm == "B":
        if receipt.get("gpu_uuid") != arm_const["gpu_uuid"]:
            problems.append(
                f"reference GPU uuid mismatch: {receipt.get('gpu_uuid')!r}")
        if receipt.get("vulkan_device_name") != "NVIDIA GeForce RTX 3060":
            problems.append("reference Vulkan device name mismatch")
    else:
        if receipt.get("pci_id") != arm_const["pci_id"]:
            problems.append(
                f"candidate AMD PCI identity mismatch: "
                f"{receipt.get('pci_id')!r}")
        name = receipt.get("vulkan_device_name")
        if not isinstance(name, str) or "RADV POLARIS10" not in name:
            problems.append(
                f"candidate Vulkan device identity mismatch: {name!r}")
    ngl = receipt.get("ngl")
    if not isinstance(ngl, int) or isinstance(ngl, bool) or \
            ngl not in C.LADDER_NGLS:
        problems.append(f"ngl {ngl!r} missing or off the frozen ladder")

    case_id = receipt.get("case_id")
    if case_id not in C.FIXTURE_CASES:
        problems.append(f"non-historical case {case_id!r}")
    C.assert_historical_only(case_id or "")

    # fixture-ladder identity + exact prompt/input identity, derived
    # independently from the accepted fixture authority (repo bytes)
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
            problems.append(
                "prompt length mismatch vs fixture authority")
        want_text = hashlib.sha256(
            fx["prompt_text"].encode()).hexdigest()
        if receipt.get("prompt_text_sha256") != want_text:
            problems.append(
                "prompt text digest mismatch vs fixture authority")

    # model representation: the exact three frozen member hashes
    if receipt.get("model_members") != C.MODEL_MEMBER_SHA256:
        problems.append(
            "model member hashes do not match the frozen three-member set")
    if receipt.get("llama_cpp_pin") != C.LLAMA_CPP_PIN:
        problems.append("llama.cpp pin mismatch")
    if receipt.get("patched_source_sha256") != C.OBSERVER_PATCHED_SOURCE_SHA256:
        problems.append("comparator/2 patched-source sha mismatch")
    server_sha = receipt.get("server_sha256")
    if not isinstance(server_sha, str) or \
            Digest64_RE.fullmatch(server_sha) is None:
        problems.append("executed server/binary sha256 malformed")
    if receipt.get("build_flags") != C.OBSERVER_BUILD_FLAGS:
        problems.append("build flags drift")
    if receipt.get("request_contract") != C.REQUEST_CONTRACT:
        problems.append("request contract drift")

    # non-participating GPU residency evidence
    excluded = receipt.get("excluded_device_residency_mib")
    want_excluded = C.EXCLUDED_BY_ARM.get(arm, set())
    if not isinstance(excluded, dict) or \
            set(excluded) != set(want_excluded):
        problems.append(
            f"excluded-device residency evidence must cover exactly "
            f"{sorted(want_excluded)}")
    elif any(v > C.EXCLUDED_RESIDENCY_NOISE_MIB for v in excluded.values()):
        problems.append("excluded device over the residency noise floor")

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
    if arm == "B":
        if len(winners) != C.DECISIONS:
            problems.append("reference sampled winners != 8")
        if forced:
            problems.append("reference arm must not force tokens")
    else:
        if len(winners) != C.DECISIONS:
            problems.append("candidate sampled winners != 8")
        if len(forced) != C.DECISIONS:
            problems.append("candidate forced tokens != 8")

    for d, entry in sorted(rows.items()):
        digest = entry.get("sha256")
        nbytes = entry.get("bytes")
        if not isinstance(digest, str) or not Digest64_RE.fullmatch(digest):
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
    # claimed digest. Only then evaluate FP32 finiteness. The computed
    # digests are exposed in the result as the independent verification.
    row_digests: dict[str, str] = {}
    for d, entry in sorted(rows.items()):
        try:
            raw = row_reader(entry["path"])
        except Exception as exc:  # unreadable/rejected custody path
            problems.append(f"row {d} custody read failed: {exc}")
            continue
        if len(raw) != C.ROW_BYTES:
            problems.append(
                f"row {d} raw bytes {len(raw)} != {C.ROW_BYTES}")
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
    # the named high-signal mismatches get their own stable strings so
    # negative controls can assert exactly what fired
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
        problems.append(
            f"{arm} meta rows are not exactly positions 0..7")
        return problems
    winners = receipt.get("sampled_winners") or []
    forced = receipt.get("forced_tokens") or []
    for d, m in enumerate(meta):
        if m.get("sampled_winner") != (winners[d] if d < len(winners)
                                       else None):
            problems.append(
                f"{arm} meta row {d} sampled_winner disagrees with "
                f"sampled_winners[{d}]")
        want_forced = (-1 if arm == "B" else
                       (forced[d] if d < len(forced) else None))
        if m.get("forced_token") != want_forced:
            problems.append(
                f"{arm} meta row {d} forced_token disagrees with the "
                f"receipt forced-token array")
        if arm == "C" and reference_winners is not None and \
                d < len(reference_winners) and \
                m.get("forced_token") != reference_winners[d]:
            problems.append(
                f"candidate meta row {d} forced_token != reference "
                f"winner at {d} — a candidate token may enter a later "
                f"acceptance-bearing prefix")
    return problems


def validate_pair(reference: dict[str, Any], candidate: dict[str, Any],
                  row_reader: Any,
                  expected_ngl: int | None = None) -> dict[str, Any]:
    """Cross-arm validation: same-case binding + reference prefix authority."""
    problems: list[str] = []
    ref_winners = reference.get("sampled_winners") or []
    cand_winners = candidate.get("sampled_winners") or []

    problems.extend(_cross_binding_problems(reference, candidate))
    problems.extend(_meta_row_problems(reference, "B", None))
    problems.extend(_meta_row_problems(candidate, "C", ref_winners))

    if expected_ngl is not None:
        for label, r in (("reference", reference), ("candidate", candidate)):
            if r.get("ngl") != expected_ngl:
                problems.append(
                    f"{label} ngl {r.get('ngl')!r} != phase-2 matched "
                    f"ngl {expected_ngl}")

    diag = {
        "first_divergent_decision": next(
            (d for d, (a, b) in enumerate(zip(cand_winners, ref_winners))
             if a != b), None),
        "winner_agreement": sum(
            1 for a, b in zip(cand_winners, ref_winners) if a == b),
        "v1_relation": C.V2_OBSERVER["v1_relation"],
    }
    ref_v = validate_arm_receipt(reference, "B", row_reader)
    cand_v = validate_arm_receipt(candidate, "C", row_reader)
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
                         row_reader: Any) -> dict[str, Any]:
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
    for label, rows, receipt in (("a", ra, repeat_a), ("b", rb, repeat_b)):
        per: dict[str, str] = {}
        for d in sorted(rows):
            try:
                raw = row_reader(rows[d]["path"])
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
        "schema": "inferswarm.issue241.phase3-determinism/2",
        "case_id": repeat_a.get("case_id"),
        "deterministic": not problems, "problems": problems,
        "row_digests_independent": computed,
    }


def validate_inertness(disabled_run_tokens: list[int],
                       canonical_run_tokens: list[int]) -> dict[str, Any]:
    """Observer disabled => tokens identical to the no-hook canonical run."""
    ok = (list(disabled_run_tokens or []) ==
          list(canonical_run_tokens or []))
    return {
        "schema": "inferswarm.issue241.phase3-inertness/1",
        "inert": ok,
        "problems": [] if ok else ["disabled-observer tokens differ"],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--expected-ngl", type=int, default=None,
                    help="phase-2 matched ngl both arms must have run at")
    args = ap.parse_args(argv)
    ref = load_run_receipt(args.reference)
    cand = load_run_receipt(args.candidate)
    reader = custody_row_reader(args.reference.parent)
    print(json.dumps(validate_pair(ref, cand, reader,
                                   expected_ngl=args.expected_ngl),
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
