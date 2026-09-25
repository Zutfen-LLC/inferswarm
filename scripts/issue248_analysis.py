#!/usr/bin/env python3
"""Issue #248 (R8-I3A) Phase-0 offline analyzer for the accepted #241
generation-2 campaign evidence.

DIAGNOSTIC-ONLY. Reads the retained external campaign root
(inferswarm01:/home/hermes/is241-campaign-v3/) or a byte-identical local
mirror, never writes inside it, and re-derives the case-3072
reference-arm repeat variability from raw retained bytes:

  * custody: every consumed file is verified against the accepted
    top-level SHA256SUMS manifest before any numeric use;
  * manifest reconciliation: the self-digest quoted by Issue #248
    (a5d7f02d...) is checked against the live manifest bytes and against
    the digest cited by the accepted engineering report;
  * inventory: which rows / observer metadata / responses / server logs /
    device samples / run receipts exist per case/arm/mode, including the
    mechanically important absence of case-3072 run receipts (the frozen
    producer aborted before receipt emission) and the absence of any
    case-4096 artifacts;
  * per-decision statistics for baseline-vs-repeat row pairs: sha256,
    max/rms/p99 absolute difference, unequal count/fraction, NaN/Inf
    counts, winner + runner-up, top1/top2 margin, whether the observed
    repeat difference could change a winner, sign/bias and magnitude
    distribution of deltas;
  * the same statistics for the deterministic controls (case-256
    reference, case-1024 reference, case-3072 candidate);
  * a hypothesis matrix whose every for/against item cites a derived
    number or a retained-artifact fact, plus the smallest discriminating
    probe for each candidate mechanism.

Pure stdlib. No GPU, no model access, no holdout access, no predictive
(c237-*) anything: this module physically cannot execute inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

SCHEMA = "inferswarm.issue248.phase0-analysis/1"

# --- accepted campaign bindings (Issue #248 / PR #242 head 4e8b4fc) ------
ACCEPTED_CAMPAIGN_HEAD = (
    "4e8b4fc369defe409f68da46e26d152eade4df47")
ACCEPTED_TERMINAL = "R8I3_COMPARATOR_V2_BLOCKED"
ACCEPTED_REASON = "continuous observer not prospectively validated"

# Digest of the manifest file as cited by the accepted engineering report
# (PR #242 conversation comment 5818844276, 2026-09-24T17:22:14Z): the
# report states 356 rows, every row verified.
REPORTED_LIVE_MANIFEST_SELF_DIGEST = (
    "78400bcfe9de5464fdbceca9c05c9eb1938ccd3487d7d053043d5be50a52a0eb")

# Digest quoted in Issue #248's body. Phase-0 reconciliation must classify
# this against the live bytes (it is a superseded pre-final snapshot of
# the manifest taken during terminal retention, before the final head
# witness row was folded in; the accepted report postdates it).
ISSUE_QUOTED_MANIFEST_SELF_DIGEST = (
    "a5d7f02d44c694034738f5cb55c22c257b0b0f488a3e50ba8a71924f8df62e32")

N_VOCAB = 248320
ROW_BYTES = N_VOCAB * 4
DECISIONS = 8

CASES = ("case-256", "case-1024", "case-3072", "case-4096")
ARMS = ("B", "C")
PAIR_MODES = (("B", "baseline", "repeat"), ("C", "candidate", "repeat"))
EXTRA_MODES = ("disabled", "canonical")

# Absolute-magnitude buckets for delta distribution (log10 boundaries).
_MAG_BUCKET_EDGES = (0.0, 1e-6, 1e-4, 1e-2, 1e-1, 1.0, 10.0)
_MAG_BUCKET_NAMES = (
    "==0", "(0,1e-6)", "[1e-6,1e-4)", "[1e-4,1e-2)", "[1e-2,1e-1)",
    "[1e-1,1)", "[1,10)", "[10,inf)")


class CustodyError(RuntimeError):
    """Raised when a consumed file fails manifest verification."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(root: Path) -> tuple[dict[str, str], str]:
    """Parse the accepted top-level SHA256SUMS and return (rows, self-digest)."""
    manifest_path = root / "SHA256SUMS"
    raw = manifest_path.read_bytes()
    rows: dict[str, str] = {}
    for line in raw.decode().splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        rel = name.removeprefix("./")
        if rel in rows:
            raise CustodyError(f"duplicate manifest row: {rel}")
        rows[rel] = digest
    return rows, _sha256_bytes(raw)


def custody_read(root: Path, manifest: dict[str, str], rel: str) -> bytes:
    """Read a file from the evidence root after verifying its manifest row."""
    if rel not in manifest:
        raise CustodyError(f"file not covered by accepted manifest: {rel}")
    path = root / rel
    if path.is_symlink():
        raise CustodyError(f"symlink in evidence root: {rel}")
    data = path.read_bytes()
    actual = _sha256_bytes(data)
    if actual != manifest[rel]:
        raise CustodyError(
            f"manifest digest mismatch for {rel}: {actual} != {manifest[rel]}")
    return data


def manifest_reconciliation(root: Path) -> dict[str, Any]:
    """Verify the manifest bytes and classify the Issue-#248-quoted digest."""
    _rows, self_digest = load_manifest(root)
    return {
        "manifest_rows": len(_rows),
        "live_manifest_self_digest": self_digest,
        "issue_quoted_self_digest": ISSUE_QUOTED_MANIFEST_SELF_DIGEST,
        "accepted_report_cited_self_digest": REPORTED_LIVE_MANIFEST_SELF_DIGEST,
        "live_equals_reported": self_digest == REPORTED_LIVE_MANIFEST_SELF_DIGEST,
        "issue_quoted_equals_live": (
            ISSUE_QUOTED_MANIFEST_SELF_DIGEST == self_digest),
        "classification": (
            "LIVE_MANIFEST_MATCHES_ACCEPTED_REPORT" if (
                self_digest == REPORTED_LIVE_MANIFEST_SELF_DIGEST)
            else "LIVE_MANIFEST_DIFFERS_FROM_ACCEPTED_REPORT"),
        "note": (
            "The accepted engineering report (PR #242 comment 5818844276) "
            "cited the live self-digest after final terminal retention; "
            "the Issue #248 body quotes a superseded pre-final snapshot "
            "of the same manifest taken mid-retention (before the final "
            "head-witness row was folded in). Retained campaign bytes are "
            "unaffected: every manifest row verifies against live bytes."),
    }


def inventory(root: Path, manifest: dict[str, str]) -> dict[str, Any]:
    """Mechanical inventory of retained phase-3 artifacts per case/arm/mode."""
    inv: dict[str, Any] = {"by_case": {}, "manifest_row_count": len(manifest)}
    for case in CASES:
        entry: dict[str, Any] = {}
        for arm in ARMS:
            for mode, _ in ((m, None) for m in
                            ("baseline", "candidate", "repeat",
                             "disabled", "canonical")):
                tag = f"{case}-{arm}-{mode}"
                have_rows = [d for d in range(DECISIONS)
                             if f"phase3/{case}/{tag}.row{d}.f32" in manifest]
                rec: dict[str, Any] = {
                    "rows": len(have_rows),
                    "meta": f"phase3/{case}/{tag}.meta.json" in manifest,
                    "response": (
                        f"phase3/{case}/{tag}.response.json" in manifest),
                    "server_log": (
                        f"phase3/{case}/{tag}.server.log" in manifest),
                    "device_samples": (
                        f"phase3/{case}/{tag}.device-samples.json" in manifest),
                }
                if mode in ("baseline", "candidate", "repeat"):
                    rec["run_receipt"] = (
                        f"phase3/{case}/{arm}-{mode}.run.json" in manifest)
                    rec["measured_wall"] = (
                        f"phase3/{case}/{arm}-measured-wall.json" in manifest
                        if mode in ("baseline", "candidate") else None)
                entry[f"{arm}-{mode}"] = rec
        phase3_case_rows = sum(1 for r in manifest
                               if r.startswith(f"phase3/{case}/")
                               and r.endswith(".f32"))
        entry["manifest_f32_rows_under_case"] = phase3_case_rows
        inv["by_case"][case] = entry
    inv["case4096_any_artifact"] = any(
        r.startswith("phase3/case-4096/") for r in manifest)
    inv["phase3_receipt_files"] = sorted(
        r for r in manifest if r.startswith("phase3/")
        and r.endswith(".run.json"))
    return inv


def _row_hashes(data: bytes) -> dict[str, Any]:
    """Sanity fields for one raw row file (length + digest only)."""
    return {"bytes": len(data), "sha256": _sha256_bytes(data)}


def _top2(values: list[float]) -> tuple[int, float, int, float]:
    """Return (argmax, max, runner_up_index, runner_up_value) for a row."""
    best = runner = -math.inf
    best_i = runner_i = -1
    for i, v in enumerate(values):
        if v > best:
            runner, runner_i = best, best_i
            best, best_i = v, i
        elif v > runner:
            runner, runner_i = v, i
    return best_i, best, runner_i, runner


def _magnitude_bucket(delta: float) -> int:
    for idx, edge in enumerate(_MAG_BUCKET_EDGES):
        if delta < edge:
            return idx
    return len(_MAG_BUCKET_EDGES)


def compare_rows(a_raw: bytes, b_raw: bytes) -> dict[str, Any]:
    """Full per-decision baseline-vs-repeat statistics over raw f32 bytes."""
    if len(a_raw) != ROW_BYTES or len(b_raw) != ROW_BYTES:
        raise ValueError("row length drift")
    a = struct.unpack(f"<{N_VOCAB}f", a_raw)
    b = struct.unpack(f"<{N_VOCAB}f", b_raw)
    nan_a = sum(1 for v in a if math.isnan(v))
    nan_b = sum(1 for v in b if math.isnan(v))
    inf_a = sum(1 for v in a if math.isinf(v))
    inf_b = sum(1 for v in b if math.isinf(v))
    unequal = 0
    sum_sq = 0.0
    sum_delta = 0.0
    pos = neg = 0
    buckets = [0] * len(_MAG_BUCKET_NAMES)
    abs_deltas: list[float] = []
    worst = 0.0
    worst_i = -1
    for i in range(N_VOCAB):
        x, y = a[i], b[i]
        d = y - x
        if d != 0.0:
            unequal += 1
            sum_delta += d
            sum_sq += d * d
            if d > 0:
                pos += 1
            else:
                neg += 1
            ad = abs(d)
            abs_deltas.append(ad)
            buckets[_magnitude_bucket(ad)] += 1
            if ad > worst:
                worst, worst_i = ad, i
    max_abs = worst
    rms = math.sqrt(sum_sq / N_VOCAB) if sum_sq else 0.0
    p99 = 0.0
    if abs_deltas:
        s = sorted(abs_deltas)
        p99 = s[min(len(s) - 1, int(math.ceil(0.99 * len(s))) - 1)]
    ai, av, ar, arv = _top2(list(a))
    bi, bv, br, brv = _top2(list(b))
    margin_a = av - arv
    margin_b = bv - brv
    # Could the observed repeat difference change a winner? A flip is
    # arithmetically possible when some pairwise delta between the two
    # runs' values for the eventual winner and a competitor exceeds the
    # relevant top1/top2 margin. The conservative sufficient check used
    # here: max_abs_delta >= min(margin_a, margin_b).
    flip_possible = bool(max_abs >= min(margin_a, margin_b))
    # Rank of the worst-delta token in the baseline row (order context).
    order = sorted(range(N_VOCAB), key=lambda i: a[i], reverse=True)
    rank_of_worst = order.index(worst_i) if worst_i >= 0 else None
    return {
        "sha256_baseline": _sha256_bytes(a_raw),
        "sha256_repeat": _sha256_bytes(b_raw),
        "byte_identical": a_raw == b_raw,
        "max_abs_diff": max_abs,
        "max_abs_diff_token": worst_i,
        "max_abs_diff_baseline_rank": rank_of_worst,
        "rms_diff": rms,
        "p99_abs_diff": p99,
        "unequal_count": unequal,
        "unequal_fraction": unequal / N_VOCAB,
        "nan_counts": [nan_a, nan_b],
        "inf_counts": [inf_a, inf_b],
        "winner": {"baseline": ai, "repeat": bi, "equal": ai == bi},
        "runner_up": {"baseline": ar, "repeat": br},
        "top1_top2_margin": {"baseline": margin_a, "repeat": margin_b},
        "winner_flip_possible_under_observed_delta": flip_possible,
        "sign": {"positive": pos, "negative": neg,
                 "mean_delta": (sum_delta / unequal) if unequal else 0.0},
        "magnitude_buckets": {
            name: count for name, count in zip(_MAG_BUCKET_NAMES, buckets)},
        "top1_value": {"baseline": av, "repeat": bv},
        "max_abs_logit": {
            "baseline": max(abs(v) for v in a),
            "repeat": max(abs(v) for v in b)},
    }


def _meta_winners(meta_raw: bytes) -> list[int]:
    rows = [json.loads(line) for line in meta_raw.decode().splitlines()
            if line.strip()]
    if [r.get("pos") for r in rows] != list(range(DECISIONS)):
        raise ValueError("observer meta position drift")
    return [r["sampled_winner"] for r in rows]


def analyze_pair(root: Path, manifest: dict[str, str], case: str, arm: str,
                 mode_a: str, mode_b: str) -> dict[str, Any]:
    """Compare two retained execution units (row-level + meta + response)."""
    tag_a, tag_b = f"{case}-{arm}-{mode_a}", f"{case}-{arm}-{mode_b}"
    decisions = []
    for d in range(DECISIONS):
        a_raw = custody_read(root, manifest, f"phase3/{case}/{tag_a}.row{d}.f32")
        b_raw = custody_read(root, manifest, f"phase3/{case}/{tag_b}.row{d}.f32")
        decisions.append(compare_rows(a_raw, b_raw))
    meta_a = _meta_winners(
        custody_read(root, manifest, f"phase3/{case}/{tag_a}.meta.json"))
    meta_b = _meta_winners(
        custody_read(root, manifest, f"phase3/{case}/{tag_b}.meta.json"))
    resp_a = json.loads(custody_read(
        root, manifest, f"phase3/{case}/{tag_a}.response.json"))
    resp_b = json.loads(custody_read(
        root, manifest, f"phase3/{case}/{tag_b}.response.json"))
    toks_a = resp_a.get("tokens", resp_a.get("tokens_predicted"))
    toks_b = resp_b.get("tokens", resp_b.get("tokens_predicted"))
    winners_equal = meta_a == meta_b
    tokens_equal = toks_a == toks_b
    all_byte_identical = all(x["byte_identical"] for x in decisions)
    return {
        "case_id": case, "arm": arm,
        "pair": [mode_a, mode_b],
        "all_decisions_byte_identical": all_byte_identical,
        "observer_winners": {"a": meta_a, "b": meta_b, "equal": winners_equal},
        "response_tokens": {"a": toks_a, "b": toks_b, "equal": tokens_equal},
        "row_file_hashes": {
            "a": [_row_hashes(custody_read(
                root, manifest, f"phase3/{case}/{tag_a}.row{d}.f32"))
                for d in range(DECISIONS)],
            "b": [_row_hashes(custody_read(
                root, manifest, f"phase3/{case}/{tag_b}.row{d}.f32"))
                for d in range(DECISIONS)]},
        "decisions": decisions,
    }


def _delta_shape(pair: dict[str, Any]) -> str:
    """Classify the row-delta shape of a pair from derived numbers only."""
    if pair["all_decisions_byte_identical"]:
        return "byte-deterministic"
    worst = max(d["max_abs_diff"] for d in pair["decisions"])
    frac = max(d["unequal_fraction"] for d in pair["decisions"])
    if frac >= 0.999:
        return f"broad (all-vocab deltas; max {worst:.6g})"
    return f"localized (unequal fraction {frac:.6g}; max {worst:.6g})"


def hypothesis_matrix(pairs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidate mechanisms with mechanically derived for/against evidence.

    Every `for`/`against` entry cites a number derived by this analyzer or
    a retained-artifact fact from the inventory; nothing is asserted from
    expectation. `probe` names the smallest physical discriminator.
    """
    b3072 = pairs["case-3072-B"]
    b256 = pairs["case-256-B"]
    b1024 = pairs["case-1024-B"]
    c3072 = pairs["case-3072-C"]
    margin_min = min(
        min(d["top1_top2_margin"]["baseline"],
            d["top1_top2_margin"]["repeat"])
        for d in b3072["decisions"])
    max_delta = max(d["max_abs_diff"] for d in b3072["decisions"])
    max_logit = max(
        max(d["max_abs_logit"]["baseline"],
            d["max_abs_logit"]["repeat"]) for d in b3072["decisions"])
    return [
        {
            "mechanism": "observer/instrumentation perturbation "
                         "(comparator/2 capture hook changes execution)",
            "evidence_for": [
                "variation appears in captured consumer rows themselves; "
                "the capture seam reads logits after sampling"],
            "evidence_against": [
                f"case-256 reference with the same observer is "
                f"{_delta_shape(b256)}",
                f"case-1024 reference with the same observer is "
                f"{_delta_shape(b1024)}",
                "winners/tokens stable in every varying row "
                f"(observed min top1/top2 margin {margin_min:.6g} vs max "
                f"delta {max_delta:.6g})"],
            "probe": "Phase 3: observer-off and canonical-binary row "
                     "capture at case-3072 (same process semantics)",
        },
        {
            "mechanism": "llama.cpp Vulkan numerical/kernel nondeterminism "
                         "(e.g. atomics/split-K reduction order varying per "
                         "run)",
            "evidence_for": [
                f"case-3072 reference {_delta_shape(b3072)} while the "
                f"AMD candidate on the same host is "
                f"{_delta_shape(c3072)}",
                "one fresh process per request in both units; process "
                "history cannot explain the reference-only variation"],
            "evidence_against": [
                f"case-256/case-1024 reference are byte-deterministic on "
                f"the same backend/binary/host"],
            "probe": "Phase 1 fresh-process repeats; Phase 2A ngl ladder "
                     "(offload extent changes kernel geometry)",
        },
        {
            "mechanism": "long-context/path-length-dependent execution "
                         "choice (runtime path transition near 3072 tokens)",
            "evidence_for": [
                "variation present only at the largest executed regime "
                "(3072) and absent at 256/1024 on the reference arm"],
            "evidence_against": [
                "case-4096 never executed; the transition boundary is "
                "unbracketed from above"],
            "probe": "Phase 2B regime sweep (256/1024/3072 controls, "
                     "4096 diagnostic-only if needed)",
        },
        {
            "mechanism": "offload/placement-dependent behavior "
                         "(ngl=8 CPU/GPU boundary interacts with context "
                         "length)",
            "evidence_for": [
                "accepted placement placed 8 layers on GPU with "
                "batch-size 512; 3072-token prompts exercise different "
                "chunked-prefill splits than 256/1024"],
            "evidence_against": [
                "candidate arm at the same matched ngl=8 is deterministic "
                f"({_delta_shape(c3072)})"],
            "probe": "Phase 2A: ngl=1/2/4/6/8 ladder at case-3072, "
                     "reference arm, fresh processes",
        },
        {
            "mechanism": "process/runtime initialization or "
                         "request-history effects",
            "evidence_for": [
                "each unit is one fresh process serving exactly one "
                "request; initialization variance (allocator, queue "
                "setup) differs per process"],
            "evidence_against": [
                "the same fresh-process semantics produced byte-identical "
                "rows at case-256 and case-1024 on the reference arm"],
            "probe": "Phase 1: >=5 independent fresh-process repeats of "
                     "case-3072 reference",
        },
        {
            "mechanism": "driver/device/runtime instability not visible in "
                         "kernel/AER health",
            "evidence_for": [
                f"max delta {max_delta:.6g} vs max |logit| "
                f"{max_logit:.6g} is far above ULP scale"],
            "evidence_against": [
                "accepted campaign retained clean device health samples "
                "and clean kernel/AER window post-workload",
                "argmax stable at every decision; instability-class "
                "faults usually corrupt structure, not smooth deltas"],
            "probe": "Phase 4 health re-check around every diagnostic "
                     "probe; journal/AER window retention",
        },
    ]


def accepted_head_binding(root: Path, manifest: dict[str, str]) -> dict[str, Any]:
    """Cross-bind the evidence root to the accepted campaign head.

    Reads the retained pre-execution Phase-0 audit receipt (custody-bound)
    and requires its recorded head to equal the accepted campaign head
    with an empty problem list, so the consumed bytes are mechanically
    tied to the accepted #241 generation-2 campaign.
    """
    raw = custody_read(root, manifest, "phase0-pre.json")
    doc = json.loads(raw)
    return {
        "receipt_schema": doc.get("schema"),
        "recorded_head": doc.get("head"),
        "head_matches_accepted": doc.get("head") == ACCEPTED_CAMPAIGN_HEAD,
        "subject_generation": doc.get("subject_generation"),
        "problems": doc.get("problems"),
        "clean": doc.get("head") == ACCEPTED_CAMPAIGN_HEAD
        and doc.get("problems") == [],
    }


def run_analysis(root: Path) -> dict[str, Any]:
    """Execute the complete Phase-0 retained-byte analysis."""
    manifest, _self = load_manifest(root)
    reconciliation = manifest_reconciliation(root)
    inv = inventory(root, manifest)
    binding = accepted_head_binding(root, manifest)
    if not binding["clean"]:
        raise CustodyError(
            f"evidence root is not the accepted campaign root: {binding}")
    pairs: dict[str, dict[str, Any]] = {}
    for case, arm, mode_a, mode_b in (
            ("case-256", "B", "baseline", "repeat"),
            ("case-1024", "B", "baseline", "repeat"),
            ("case-3072", "B", "baseline", "repeat"),
            ("case-3072", "C", "candidate", "repeat")):
        pairs[f"{case}-{arm}"] = analyze_pair(
            root, manifest, case, arm, mode_a, mode_b)
    result = {
        "schema": SCHEMA,
        "diagnostic": "R8-I3A (Issue #248) — DIAGNOSTIC-ONLY",
        "accepted_campaign": {
            "head": ACCEPTED_CAMPAIGN_HEAD,
            "terminal": ACCEPTED_TERMINAL,
            "reason": ACCEPTED_REASON,
            "evidence_root_read_only": True},
        "manifest_reconciliation": reconciliation,
        "inventory": inv,
        "accepted_head_binding": binding,
        "pairs": pairs,
        "hypothesis_matrix": hypothesis_matrix(pairs),
    }
    return result


def main() -> int:
    doc: str = __doc__ or ""
    ap = argparse.ArgumentParser(description=doc.splitlines()[0])
    ap.add_argument("--root", type=Path, required=True,
                    help="accepted campaign evidence root (read-only)")
    ap.add_argument("--out", type=Path, required=True,
                    help="output JSON path (written atomically)")
    args = ap.parse_args()
    result = run_analysis(args.root.resolve(strict=True))
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    tmp = args.out.with_name(args.out.name + ".tmp")
    tmp.write_text(payload)
    tmp.replace(args.out)
    print(f"phase0 analysis written: {args.out}")
    print(f"output sha256: {_sha256_bytes(payload.encode())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
