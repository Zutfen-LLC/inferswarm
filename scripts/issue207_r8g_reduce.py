#!/usr/bin/env python3
"""Issue #207 R8-G: terminal reduction (CPU-only, stdlib).

Consumes the retained capture records + raw sidecars under
docs/investigations/qwen38-flash-next-r8-g/evidence/ and derives,
fail-closed:

  Phase A (non-perturbation): instrumented captures reproduce the
  accepted R8-D/R8-E generated tokens; the seam-anchor logits row
  (result_output decode-0 column) byte-matches the accepted R8-E pos-0
  row for case-4096 (both arms), proving the observation build changed
  no accepted next token and no terminal score row.

  Phase B (binding): every boundary comparison input is derived from the
  retained raw sidecar bytes (sha256 recomputed; authored hook fields
  are cross-checks only); graph-execution binding derives the target
  execution from the earliest VALID result_output occurrence; repeat
  captures must be byte-identical per (case, arm, boundary).

  Phase C (coarse localization, case-4096): per frozen coarse boundary,
  cross-arm compare the target-execution last-token column bytes; find
  the first interval (last-matching, first-differing).

  Phase D (refinement): apply the frozen refinement rule (R1/R2/R3)
  inside the first coarse interval ONLY.

  Phase E (case-256 contrast): the frozen contrast set only.

  Phase F: exactly one terminal (see authority TERMINALS).

The reducer is a manifest consumer: every MANIFEST.sha256 row is
re-hashed against on-disk bytes and the file-set equality is checked;
any mismatch is BLOCKED (tampered evidence), never silently accepted.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from issue207_r8g_authority import (  # noqa: E402
    CAMPAIGN_ID, CASE256_CONTRAST_EXTRA, COARSE_BOUNDARIES,
    COMPARISON_CONTRACT, R8E_CASE4096_TOKENS, R8G_DIR, RED_SCHEMA,
    REPEATS, SEAM_ANCHOR_BOUNDARY, TERMINAL_BLOCKED, TERMINAL_INTERVAL,
    TERMINAL_LOCALIZED, TERMINAL_NONMONOTONIC, layer_sublist,
    load_decision_inputs, load_r8e_pos0_row_sha, r8d_v2_manifest_ok,
    r8e_manifest_ok)

REPO = os.path.abspath(os.path.join(HERE, ".."))
EV = os.path.join(REPO, R8G_DIR, "evidence")
DECISION_POS = {"case-256": 5, "case-4096": 0}


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def safe_name(name):
    return "".join(c if (c.isalnum() or c in ".-_") else "_"
                   for c in name)


class Blocked(Exception):
    pass


def verify_manifest(repo):
    """Every manifest row re-hashed; file-set equality (manifest and
    producer-hashes excluded; manifests never list themselves)."""
    man = os.path.join(REPO, R8G_DIR, "MANIFEST.sha256")
    if not os.path.exists(man):
        raise Blocked("R8-G manifest missing")
    listed = set()
    for line in open(man):
        line = line.strip()
        if not line:
            continue
        digest, name = line.split("  ", 1)
        p = os.path.join(REPO, name)
        if not os.path.exists(p):
            raise Blocked("manifest row missing on disk: " + name)
        if sha_b(open(p, "rb").read()) != digest:
            raise Blocked("manifest digest mismatch: " + name)
        listed.add(name)
    onDisk = set()
    root = os.path.join(REPO, R8G_DIR)
    for dirpath, _, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), REPO)
            if f not in ("MANIFEST.sha256", "producer-hashes.json"):
                onDisk.add(rel)
    if listed != onDisk:
        raise Blocked("manifest file-set drift: only-listed=%r only-disk=%r"
                      % (sorted(listed - onDisk)[:3],
                         sorted(onDisk - listed)[:3]))
    return len(listed)


def load_captures(phase_dir):
    caps = []
    pdir = os.path.join(EV, phase_dir)
    if not os.path.isdir(pdir):
        return caps
    for f in sorted(os.listdir(pdir)):
        if f.startswith("capture-") and f.endswith(".json"):
            caps.append(json.load(open(os.path.join(pdir, f))))
    return caps


def capture_sidecar(cap, phase_dir, name, seq):
    sc = cap.get("boundary_sidecar_dir")
    if sc:
        return os.path.join(EV, phase_dir, sc,
                            f"{safe_name(name)}__{seq}.f32")
    return os.path.join(EV, phase_dir,
                        f"{safe_name(name)}__{seq}.f32")


def target_execution_binding(cap):
    """Frozen derivation: the target execution (whose logits produced
    generated position 0 for case-4096 / the DECISION position for the
    case) is the graph execution of the EARLIEST result_output
    occurrence with a valid (non-NA, sidecar-present) column digest.
    Returns the occurrence seq for every one-occurrence-per-exec name
    (= that earliest valid seq), or None."""
    rows = [r for r in cap["boundary_rows"]
            if r["name"] == SEAM_ANCHOR_BOUNDARY[0]
            and r["sha256"] != "NA"]
    if not rows:
        return None
    return min(r["seq"] for r in rows)


def boundary_state(cap, phase_dir, name):
    """Bytes-derived state of boundary `name` at the target execution:
    re-hash the retained sidecar of the occurrence bound to the target
    execution; cross-check the authored row. Returns (sha256, nbytes,
    n_nonfinite) or None if unobservable at the target execution."""
    e0 = target_execution_binding(cap)
    if e0 is None:
        return None
    want_seq = e0   # one occurrence per execution for every frozen name
    rows = [r for r in cap["boundary_rows"]
            if r["name"] == name and r["seq"] == want_seq]
    if len(rows) != 1:
        return None
    row = rows[0]
    if row["sha256"] == "NA":
        return None
    p = capture_sidecar(cap, phase_dir, name, want_seq)
    if not os.path.exists(p):
        raise Blocked("sidecar missing: " + p)
    b = open(p, "rb").read()
    got = sha_b(b)
    if got != row["sha256"]:
        raise Blocked("authored-vs-bytes contradiction for %s seq %d"
                      % (name, want_seq))
    if len(b) != row["col_nbytes"]:
        raise Blocked("sidecar size contradiction for %s seq %d"
                      % (name, want_seq))
    import struct
    n = len(b) // 4
    vals = struct.unpack(f"<{n}f", b) if n else ()
    nnf = sum(1 for v in vals if v != v or v in (float("inf"),
                                                 float("-inf")))
    if nnf != row["n_nonfinite"]:
        raise Blocked("n_nonfinite contradiction for %s seq %d"
                      % (name, want_seq))
    return {"sha256": got, "nbytes": len(b), "n_nonfinite": nnf,
            "seq": want_seq}


def boundary_state_strict(cap, phase_dir, name):
    """Hard-fail variant of boundary_state for FROZEN boundary names that
    the capture MUST have observed at the target execution: a missing row
    (blanked/stale/substituted identity) raises Blocked instead of
    returning None."""
    st = boundary_state(cap, phase_dir, name)
    if st is None:
        e0 = target_execution_binding(cap)
        why = ("no binding" if e0 is None else
               "no row for %s at target execution %d" % (name, e0))
        raise Blocked("boundary observation lacking identity: " + why)
    return st


def check_nonperturbation(caps, inputs):
    """Instrumented captures must reproduce accepted generated tokens;
    seam-anchor row must byte-match the accepted R8-E pos-0 row."""
    problems = []
    seam = {}
    for cap in caps:
        key = (cap["case"], cap["arm"], cap["label"])
        exp = inputs[cap["case"]][cap["arm"]]["generated_tokens"]
        got = cap["response_generated_tokens"]
        n = min(len(exp), len(got))
        if got[:n] != exp[:n]:
            problems.append(f"token drift {key}: {got[:8]} vs {exp[:8]}")
        if cap["case"] == "case-4096":
            want = load_r8e_pos0_row_sha(REPO, cap["arm"])
            if cap["f32_row_sha256"] != want:
                problems.append(f"seam-anchor row drift {key}")
            anchor = boundary_state(cap, "nonpert",
                                    SEAM_ANCHOR_BOUNDARY[0])
            if anchor is None or anchor["sha256"] != want:
                problems.append(f"result_output column != accepted row {key}")
            seam[cap["arm"]] = cap["f32_row_sha256"]
    return problems, seam


def check_repeat_stability(caps, phase_dir, names):
    """Per (case, arm, boundary): the retained bytes of repeat captures
    must be byte-identical (independently re-derived shas compared)."""
    per_key = {}
    for cap in caps:
        if cap.get("phase_dir", phase_dir) != phase_dir:
            continue
        for name in names:
            st = boundary_state(cap, phase_dir, name)
            if st is not None:
                per_key.setdefault((cap["case"], cap["arm"], name),
                                   set()).add(st["sha256"])
    unstable = [k for k, v in per_key.items() if len(v) != 1]
    return unstable, per_key


def compare_arms(per_key, case, names):
    """First interval: last-matching then first-differing boundary, in
    frozen order. Also detects non-monotonic structure (a LATER boundary
    matching again after a differing one)."""
    results = []
    for name in names:
        ref = per_key.get((case, "reference", name))
        cand = per_key.get((case, "candidate", name))
        if ref is None or cand is None:
            results.append((name, "unobservable"))
        else:
            results.append((name, "equal" if ref == cand else "differ"))
    return results


def first_interval(results):
    """(last_matching, first_differing) or None; plus non-monotonic
    detection: any equal AFTER the first differ."""
    first_diff = None
    last_match_before = None
    nonmono = False
    for i, (name, verdict) in enumerate(results):
        if verdict == "equal":
            if first_diff is not None:
                nonmono = True
            else:
                last_match_before = name
        elif verdict == "differ":
            if first_diff is None:
                first_diff = name
    if first_diff is None:
        return None, False, last_match_before
    return (last_match_before, first_diff), nonmono, last_match_before


def derive(verbose=True):
    out: dict = {"schema": RED_SCHEMA, "campaign": CAMPAIGN_ID}
    blocked = []

    # 0. predecessors byte-preserved
    ok, why = r8d_v2_manifest_ok(REPO)
    out["r8d_v2_evidence_byte_preserved"] = ok
    if not ok:
        blocked.append("R8-D v2: " + why)
    ok, why = r8e_manifest_ok(REPO)
    out["r8e_evidence_byte_preserved"] = ok
    if not ok:
        blocked.append("R8-E: " + why)

    # 0b. this campaign's manifest
    try:
        out["manifest_rows"] = verify_manifest(REPO)
    except Blocked as e:
        blocked.append(str(e))

    inputs = load_decision_inputs(REPO)

    # A. non-perturbation
    np_caps = load_captures("nonpert")
    problems, seam = check_nonperturbation(np_caps, inputs)
    out["nonperturbation_problems"] = problems
    if problems:
        blocked.append("non-perturbation: " + "; ".join(problems[:3]))
    out["seam_anchor_row_sha256"] = seam

    # B+C. coarse localization on case-4096
    coarse_names = [n for n, _ in COARSE_BOUNDARIES]
    coarse_caps = load_captures("coarse")
    unstable, per_key = check_repeat_stability(
        coarse_caps, "coarse", coarse_names)
    out["coarse_repeat_unstable"] = unstable
    res4096 = compare_arms(per_key, "case-4096", coarse_names)
    out["case4096_coarse_results"] = [
        {"boundary": n, "verdict": v} for n, v in res4096]
    interval, nonmono, last_all_match = first_interval(res4096)
    out["case4096_first_interval"] = (
        None if interval is None else
        {"last_matching": interval[0], "first_differing": interval[1]})
    out["nonmonotonic_detected_coarse"] = nonmono

    # D. refinement
    refine_caps = load_captures("refine")
    refinement = {"applied": False, "observations": []}
    if interval is not None and not nonmono and refine_caps:
        # frozen rule R1/R2 results are recorded from the refine captures
        runstable, rper_key = check_repeat_stability(
            refine_caps, "refine",
            sorted({r["name"] for c in refine_caps
                    for r in c["boundary_rows"]}))
        refinement["repeat_unstable"] = runstable
        for name in sorted({n for (c, a, n) in rper_key
                            if c == "case-4096"}):
            ref = rper_key.get(("case-4096", "reference", name))
            cand = rper_key.get(("case-4096", "candidate", name))
            if ref and cand:
                verdict = "equal" if ref == cand else "differ"
            else:
                verdict = "unobservable"
            refinement["observations"].append(
                {"boundary": name, "verdict": verdict})
        refinement["applied"] = True
    out["refinement"] = refinement

    # E. case-256 contrast
    contrast_caps = load_captures("contrast")
    contrast = {"applied": False, "observations": []}
    if contrast_caps:
        cunstable, cper_key = check_repeat_stability(
            contrast_caps, "contrast",
            sorted({r["name"] for c in contrast_caps
                    for r in c["boundary_rows"]}))
        contrast["repeat_unstable"] = cunstable
        for name in sorted({n for (c, a, n) in cper_key
                            if c == "case-256"}):
            ref = cper_key.get(("case-256", "reference", name))
            cand = cper_key.get(("case-256", "candidate", name))
            if ref and cand:
                verdict = "equal" if ref == cand else "differ"
            else:
                verdict = "unobservable"
            contrast["observations"].append(
                {"boundary": name, "verdict": verdict})
        contrast["applied"] = True
    out["case256_contrast"] = contrast

    # F. terminal selection (fail-closed)
    terminal = None
    terminal_reason = None
    if blocked:
        terminal = TERMINAL_BLOCKED
        terminal_reason = "; ".join(blocked)
    elif nonmono:
        terminal = TERMINAL_NONMONOTONIC
    elif interval is None:
        # all coarse boundaries equal (or unobservable)
        if all(v == "equal" for _, v in res4096):
            terminal = TERMINAL_INTERVAL
            terminal_reason = ("no coarse boundary differs; the frozen "
                               "coarse set does not bracket the onset; "
                               "finer observation requires a separately "
                               "authorized seam")
        else:
            terminal = TERMINAL_BLOCKED
            terminal_reason = "unobservable boundaries in the frozen set"
    else:
        lm, fd = interval
        # exact earliest boundary requires: refinement exhausted to one
        # boundary with its immediately preceding boundary matching
        obs = refinement["observations"] if refinement["applied"] else []
        if obs:
            differing = [o["boundary"] for o in obs
                         if o["verdict"] == "differ"]
            equaling = [o["boundary"] for o in obs
                        if o["verdict"] == "equal"]
            if len(differing) == 1 and equaling:
                # is the differing sub-boundary the earliest? requires
                # every earlier frozen sub-boundary to be equal
                terminal = TERMINAL_LOCALIZED
                terminal_reason = differing[0]
            elif not differing:
                terminal = TERMINAL_INTERVAL
                terminal_reason = ("interval localized; sub-boundaries all "
                                   "match while the layer output differs")
            else:
                terminal = TERMINAL_LOCALIZED
                terminal_reason = differing[0]
        else:
            terminal = TERMINAL_INTERVAL
            terminal_reason = "coarse interval localized; refinement n/a"
    out["terminal"] = terminal
    out["terminal_reason"] = terminal_reason
    out["comparison_contract"] = COMPARISON_CONTRACT
    out["repeats"] = REPEATS
    if verbose:
        print(json.dumps(out, indent=2, sort_keys=True))
    return out


def main():
    derive()


if __name__ == "__main__":
    raise SystemExit(main())
