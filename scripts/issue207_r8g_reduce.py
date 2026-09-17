#!/usr/bin/env python3
"""Issue #207 R8-G: terminal reduction (CPU-only, stdlib).

Correction round 2026-09-17 (maintainer review of PR #208 head
dfb1ef6): the reduction was rebuilt around four fixes —
(1) manifest/terminal closure split: the reducer now verifies an
EVIDENCE INPUT manifest (evidence/input-manifest.json) that covers only
immutable reduction inputs; reduction outputs (terminal-reduction.json,
README) are pinned by a separate final closure (CLOSURE.sha256) which
is NEVER an input to the terminal it contains (no digest cycle);
(2) refinement non-monotonic detection under the frozen R3 rule is
applied across the COMPLETE ordered refinement interval in frozen
SOURCE order — any differ at position k followed by an equal boundary
at k' > k makes the interval NON-MONOTONIC;
(3) terminal predicates are mechanically strict (see TERMINAL
DERIVATION below);
(4) boundary sets are executable authority: coarse consumes exactly
COARSE_BOUNDARIES; refinement consumes exactly the mechanically derived
frozen sub-boundaries of the first coarse interval plus the authorized
PLE bracket; case-256 consumes exactly the mechanically derived
authorized contrast set.

TERMINAL DERIVATION (exactly one terminal, fail-closed):

  R8G_EARLIEST_RUNTIME_BOUNDARY_LOCALIZED requires ALL of:
    - one frozen ordered refinement interval (mechanically derived);
    - every acceptance-required earlier boundary OBSERVABLE (a missing
      earlier frozen boundary blocks the exact-earliest claim);
    - every earlier boundary equal;
    - the candidate boundary different;
    - the immediately preceding boundary equal;
    - NO later reconvergence anywhere in the frozen interval (an equal
      boundary after the first differ makes the earliest-boundary
      interpretation misleading under R3).

  R8G_NONMONOTONIC_RUNTIME_DIVERGENCE_CHARACTERIZED requires:
    - at least one differ followed by a LATER equal boundary inside the
      frozen bounded interval; and
    - the COMPLETE retained map of the prospectively frozen interval
      (every frozen sub-boundary observable in both arms) — R3 needs
      the whole ordered map, otherwise the structure is not honestly
      characterized.

  R8G_RUNTIME_DIVERGENCE_INTERVAL_LOCALIZED when finer observation is
  honestly unavailable (frozen interval brackets the onset but some
  required sub-boundary is unobservable with no reconvergence).

  R8G_LOCALIZATION_EVIDENCE_BLOCKED for any missing/invalid authority
  (input-manifest drift, authored-vs-bytes contradiction, tampered
  sidecar, predecessor manifest mismatch, ...).

Graph-execution binding and byte-derivation are unchanged from the
accepted observation campaign: every boundary verdict is derived from
the retained raw sidecar bytes at the target execution (earliest valid
result_output occurrence + decision position); authored hook rows are
cross-checks only.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from issue207_r8g_authority import (  # noqa: E402
    CAMPAIGN_ID, CASE256_CONTRAST_EXTRA, COARSE_BOUNDARIES,
    COMPARISON_CONTRACT, PLE_BRACKET_AUTHORIZED, R8E_CASE4096_TOKENS,
    R8G_DIR, RED_SCHEMA, REPEATS, SEAM_ANCHOR_BOUNDARY, TERMINAL_BLOCKED,
    TERMINAL_INTERVAL, TERMINAL_LOCALIZED, TERMINAL_NONMONOTONIC,
    case256_authorized_set, load_decision_inputs, load_r8e_pos0_row_sha,
    r8d_v2_manifest_ok, r8e_manifest_ok, refinement_ordered_map)

REPO = os.path.abspath(os.path.join(HERE, ".."))
EV = os.path.join(REPO, R8G_DIR, "evidence")
DECISION_POS = {"case-256": 5, "case-4096": 0}


def set_repo(repo):
    """Point the module's evidence root at a sandbox repo root (used by
    --repo and the negative-control harness; production default is the
    repository the script lives in)."""
    global REPO, EV
    REPO = repo
    EV = os.path.join(REPO, R8G_DIR, "evidence")
INPUT_MANIFEST_SCHEMA = "inferswarm.issue207.input-manifest/1"


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def safe_name(name):
    return "".join(c if (c.isalnum() or c in ".-_") else "_"
                   for c in name)


class Blocked(Exception):
    pass


def verify_input_manifest(repo):
    """Every input-manifest row re-hashed against on-disk bytes; file-set
    equality against the evidence tree (input-manifest.json and nothing
    derived excluded). A listed reducer OUTPUT row fails closed (digest
    cycle prevention)."""
    p = os.path.join(repo, R8G_DIR, "evidence", "input-manifest.json")
    if not os.path.exists(p):
        raise Blocked("evidence input manifest missing")
    doc = json.load(open(p))
    if doc.get("schema") != INPUT_MANIFEST_SCHEMA:
        raise Blocked("input manifest schema drift")
    rows = doc.get("rows", {})
    derived_names = {
        R8G_DIR + "/README.md",
        R8G_DIR + "/terminal-reduction.json",
        R8G_DIR + "/producer-hashes.json",
        R8G_DIR + "/CLOSURE.sha256",
        R8G_DIR + "/evidence/input-manifest.json",
        R8G_DIR + "/MANIFEST.sha256",
    }
    for rel, want in rows.items():
        fp = os.path.join(repo, rel)
        if rel in derived_names:
            raise Blocked("derived artifact listed as input row: " + rel)
        if not os.path.exists(fp):
            raise Blocked("input row missing on disk: " + rel)
        if sha_b(open(fp, "rb").read()) != want:
            raise Blocked("input digest mismatch: " + rel)
    on_disk = set()
    for dirpath, _, files in os.walk(os.path.join(repo, R8G_DIR,
                                                  "evidence")):
        for f in files:
            if f == "input-manifest.json":
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), repo)
            on_disk.add(rel)
    if set(rows) != on_disk:
        raise Blocked(
            "input manifest file-set drift: only-listed=%r only-disk=%r"
            % (sorted(set(rows) - on_disk)[:3],
               sorted(on_disk - set(rows))[:3]))
    return len(rows)


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


def open_retained_sidecar(cap, phase_dir, name, seq):
    """Path-authority-hardened sidecar open (correction item 14):
    lstat the retained artifact; require a REGULAR file; reject
    symlinks; require canonical-path containment inside the correct
    evidence/<phase>/<capture-sidecar-dir> directory; defeat
    path/inode aliasing of one acceptance identity onto another
    capture's retained bytes."""
    p = capture_sidecar(cap, phase_dir, name, seq)
    want_dir = os.path.realpath(
        os.path.join(EV, phase_dir, cap.get("boundary_sidecar_dir", "")))
    st = os.lstat(p)                     # lstat: never follow the link
    import stat as _stat
    if _stat.S_ISLNK(st.st_mode):
        raise Blocked("sidecar is a symlink: " + p)
    if not _stat.S_ISREG(st.st_mode):
        raise Blocked("sidecar is not a regular file: " + p)
    real = os.path.realpath(p)
    if os.path.commonpath([real, want_dir]) != want_dir:
        raise Blocked("sidecar outside its capture directory: " + p)
    if real != os.path.abspath(p):
        raise Blocked("sidecar path is not canonical: " + p)
    with open(p, "rb") as fh:
        return fh.read(), p


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


def decision_position(case):
    try:
        return {"case-256": 5, "case-4096": 0}[case]
    except KeyError:
        raise Blocked("unknown case: %r" % case)


def boundary_state(cap, phase_dir, name):
    """Bytes-derived state of boundary `name` at the DECISION-position
    execution of the capture's case. Re-hashes the retained sidecar
    through the path-authority-hardened open; cross-checks the authored
    row. Returns the state dict or None if unobservable."""
    e0 = target_execution_binding(cap)
    if e0 is None:
        return None
    want_seq = e0 + decision_position(cap["case"])
    rows = [r for r in cap["boundary_rows"]
            if r["name"] == name and r["seq"] == want_seq]
    if len(rows) != 1:
        return None
    row = rows[0]
    if row["sha256"] == "NA":
        return None
    b, p = open_retained_sidecar(cap, phase_dir, name, want_seq)
    got = sha_b(b)
    if got != row["sha256"]:
        raise Blocked("authored-vs-bytes contradiction for %s seq %d (%s)"
                      % (name, want_seq, p))
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
    """Hard-fail variant for FROZEN boundary names the capture MUST have
    observed at the target execution: a missing row raises Blocked."""
    st = boundary_state(cap, phase_dir, name)
    if st is None:
        e0 = target_execution_binding(cap)
        why = ("no binding" if e0 is None else
               "no row for %s at target execution %d" % (name, e0))
        raise Blocked("boundary observation lacking identity: " + why)
    return st


def check_capture_identity(cap, inputs, r8e_row_sha, phase_dir):
    """Per-capture identity gates (fail-closed list): accepted prompt,
    canonical request bytes, token-position binding, accepted-token
    reproduction, seam-anchor row identity (arm-anchored — defeats
    placement swap), and arm placement consistency with the retained
    R8-E rows.

    Seam anchor derivation: the hook's f32_row_sha256 when retained
    (nonpert/coarse/refine phases), else the boundary observer's
    result_output column at the decision execution (contrast phases ran
    LLAMA_OBSERVE_POS=0 so no hook row bytes exist there; the observer
    column IS the full logits row at that execution and must byte-match
    the accepted R8-E row)."""
    import base64
    case, arm = cap["case"], cap["arm"]
    probs = []
    exp_prompt = list(inputs[case][arm]["prompt_token_ids"])
    req = json.loads(base64.b64decode(cap["request_body_b64"]))
    if req.get("prompt") != exp_prompt:
        probs.append("request prompt != accepted case prompt")
    anchor_sha = cap["f32_row_sha256"]
    if anchor_sha is None:
        st = boundary_state(cap, phase_dir, SEAM_ANCHOR_BOUNDARY[0])
        anchor_sha = st["sha256"] if st else None
    if anchor_sha != r8e_row_sha[(case, arm)]:
        probs.append("seam-anchor row sha != accepted R8-E row for "
                     "(%s, %s)" % (case, arm))
    # token-position binding
    pos = decision_position(case)
    tgt = [r for r in cap["logits_hook_rows"] if r["pos"] == pos]
    if not tgt:
        probs.append("no logits hook row at decision position %d" % pos)
    else:
        gt = cap["response_generated_tokens"] or []
        if pos >= len(gt) or tgt[0]["tok"] != gt[pos]:
            probs.append("hook tok != response token at decision pos")
    exp_tok = inputs[case][arm]["generated_tokens"]
    got = cap["response_generated_tokens"]
    n = min(len(exp_tok), len(got))
    if got[:n] != exp_tok[:n]:
        probs.append("token drift (%s,%s): %r vs %r"
                     % (case, arm, got[:4], exp_tok[:4]))
    return probs


def load_r8e_rows(repo):
    """Accepted R8-E retained row shas for BOTH cases (case-4096 pos 0,
    case-256 pos 5), per arm, loaded mechanically from the accepted R8-E
    capture records."""
    out = {}
    for case, arm in (("case-4096", "reference"), ("case-4096", "candidate"),
                      ("case-256", "reference"), ("case-256", "candidate")):
        p = os.path.join(
            repo, "docs/investigations/qwen38-flash-next-r8-e",
            "evidence", "observations",
            f"capture-{case}-{arm}-obs1.json")
        d = json.load(open(p))
        assert d["case"] == case and d["arm"] == arm
        out[(case, arm)] = d["f32_row_sha256"]
    return out


def check_repeat_stability(caps, phase_dir, names):
    """Per (case, arm, boundary): retained bytes of repeat captures must
    be byte-identical (independently re-derived shas compared)."""
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
    detection: any equal AFTER the first differ (frozen R3 rule)."""
    first_diff = None
    last_match_before = None
    nonmono = False
    for name, verdict in results:
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


def refinements_nonmonotonic(ordered_results):
    """R3 across the COMPLETE ordered refinement interval: any differ at
    ordered position k followed by an equal boundary at k' > k."""
    seen_differ = False
    for name, verdict in ordered_results:
        if verdict == "differ":
            seen_differ = True
        elif verdict == "equal" and seen_differ:
            return True
    return False


def terminal_selection(blocked, coarse_results, refinement_results,
                       refinement_applied):
    """Mechanically strict terminal predicates (correction item 7)."""
    if blocked:
        return TERMINAL_BLOCKED, "; ".join(blocked)
    interval, nonmono_coarse, _ = first_interval(coarse_results)

    # unobservable coarse boundaries block honest derivation
    unobs = [n for n, v in coarse_results if v == "unobservable"]
    if unobs:
        return TERMINAL_BLOCKED, ("unobservable frozen coarse "
                                  "boundaries: %s" % ", ".join(unobs[:4]))
    if interval is None:
        if all(v == "equal" for _, v in coarse_results):
            return TERMINAL_INTERVAL, ("no coarse boundary differs; the "
                                       "frozen coarse set does not "
                                       "bracket the onset; finer "
                                       "observation requires a "
                                       "separately authorized seam")
        return TERMINAL_BLOCKED, "coarse derivation inconsistency"

    if not refinement_applied:
        return TERMINAL_INTERVAL, ("coarse interval localized; "
                                   "refinement evidence unavailable")

    ordered = refinement_results          # already in frozen source order
    # every frozen refinement boundary must be observable (complete map)
    unobs_r = [n for n, v in ordered if v == "unobservable"]
    if unobs_r:
        return TERMINAL_BLOCKED, ("frozen refinement boundary "
                                  "unobservable: %s"
                                  % ", ".join(unobs_r[:4]))

    if refinements_nonmonotonic(ordered):
        first_diff = next(n for n, v in ordered if v == "differ")
        reconverged = [n for n, v in ordered
                       if v == "equal"
                       and ordered.index((n, v)) >
                       next(i for i, (nm, _) in enumerate(ordered)
                            if nm == first_diff)]
        return TERMINAL_NONMONOTONIC, (
            "R3: boundary %s differs and later boundaries (%s) match "
            "again inside the frozen ordered refinement interval — "
            "divergence structure is non-monotonic; earliest-boundary "
            "interpretation prohibited"
            % (first_diff, ", ".join(reconverged[:3])))

    # monotonic: earliest differing boundary with ALL earlier equal
    first_diff = next((n for n, v in ordered if v == "differ"), None)
    if first_diff is None:
        return TERMINAL_INTERVAL, ("frozen refinement interval fully "
                                   "observed and all boundaries equal "
                                   "while the coarse boundary differs")
    idx = [n for n, _ in ordered].index(first_diff)
    if idx == 0:
        return TERMINAL_INTERVAL, ("earliest frozen sub-boundary already "
                                   "differs; no observable earlier "
                                   "boundary in the frozen set")
    return TERMINAL_LOCALIZED, first_diff


def derive(verbose=True, repo=None):
    if repo:
        set_repo(repo)
        repo_root = repo
    else:
        repo_root = REPO
    out: dict = {"schema": RED_SCHEMA, "campaign": CAMPAIGN_ID}
    blocked = []

    # 0. predecessors byte-preserved
    ok, why = r8d_v2_manifest_ok(repo_root)
    out["r8d_v2_evidence_byte_preserved"] = ok
    if not ok:
        blocked.append("R8-D v2: " + why)
    ok, why = r8e_manifest_ok(repo_root)
    out["r8e_evidence_byte_preserved"] = ok
    if not ok:
        blocked.append("R8-E: " + why)

    # 0b. evidence INPUT manifest (reduction inputs only; the final
    # closure is NOT read here — no digest cycle)
    try:
        out["input_manifest_rows"] = verify_input_manifest(repo_root)
    except Blocked as e:
        blocked.append(str(e))

    inputs = load_decision_inputs(repo_root)
    r8e_rows = load_r8e_rows(repo_root)

    # A. capture identity + non-perturbation across ALL retained phases
    problems = []
    seam = {}
    for phase in ("nonpert", "coarse", "refine", "refine-ple",
                  "contrast", "contrast-ple"):
        for cap in load_captures(phase):
            probs = check_capture_identity(cap, inputs,
                                           r8e_rows, phase)
            if probs:
                problems.append("%s/%s/%s: %s" % (
                    phase, cap["case"], cap["arm"], "; ".join(probs)))
            seam[cap["case"] + ":" + cap["arm"]] = cap["f32_row_sha256"]
    out["capture_identity_problems"] = problems
    out["seam_anchor_row_sha256"] = seam
    if problems:
        blocked.append("capture identity: " + "; ".join(problems[:3]))

    # B+C. coarse localization on case-4096 — consume EXACTLY the
    # frozen COARSE_BOUNDARIES (nothing else, in frozen order)
    coarse_names = [n for n, _ in COARSE_BOUNDARIES]
    coarse_caps = load_captures("coarse")
    unstable, per_key = check_repeat_stability(
        coarse_caps, "coarse", coarse_names)
    out["coarse_repeat_unstable"] = unstable
    if unstable:
        blocked.append("coarse repeat instability: %r" % unstable[:3])
    res4096 = compare_arms(per_key, "case-4096", coarse_names)
    out["case4096_coarse_results"] = [
        {"boundary": n, "verdict": v} for n, v in res4096]
    interval, nonmono_coarse, _ = first_interval(res4096)
    out["case4096_first_interval"] = (
        None if interval is None else
        {"last_matching": interval[0], "first_differing": interval[1]})
    out["nonmonotonic_detected_coarse"] = nonmono_coarse

    # D. refinement: consume EXACTLY the mechanically derived frozen
    # sub-boundaries of the first coarse interval plus the authorized
    # PLE bracket, in frozen SOURCE order. Rows beyond that set are
    # retained incidental evidence and never enter the terminal.
    refinement = {"applied": False, "observations": [],
                  "frozen_set_source": "authority.refinement_ordered_map("
                  "model.input_embed, l_last-2)"}
    refine_caps = load_captures("refine") + load_captures("refine-ple")
    if interval is not None and refine_caps:
        frozen_ordered = refinement_ordered_map(*interval)
        refinement["frozen_set"] = [n for n, _ in frozen_ordered]
        runstable, rper_key = check_repeat_stability(
            refine_caps, "refine", [n for n, _ in frozen_ordered])
        refinement["repeat_unstable"] = runstable
        if runstable:
            blocked.append("refine repeat instability: %r" % runstable[:3])
        for name in [n for n, _ in frozen_ordered]:
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

    # E. case-256 contrast: consume EXACTLY the mechanically derived
    # authorized set (correction item 10)
    contrast = {"applied": False, "observations": [],
                "authorized_set_source":
                    "authority.case256_authorized_set() = case-4096 "
                    "terminal boundary set + adjacent coarse anchors + "
                    "one frozen checkpoint (" + CASE256_CONTRAST_EXTRA +
                    ")"}
    contrast_caps = (load_captures("contrast") +
                     load_captures("contrast-ple"))
    if contrast_caps:
        authorized = case256_authorized_set()
        contrast["authorized_set"] = list(authorized)
        cunstable, cper_key = check_repeat_stability(
            contrast_caps, "contrast", list(authorized))
        contrast["repeat_unstable"] = cunstable
        if cunstable:
            blocked.append("contrast repeat instability: %r"
                           % cunstable[:3])
        for name in authorized:
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

    # descriptive first-observed-differing sub-boundary (NOT a terminal
    # claim; retained for README reconciliation)
    if refinement["applied"]:
        fd = next((o["boundary"] for o in refinement["observations"]
                   if o["verdict"] == "differ"), None)
        out["first_observed_differing_sub_boundary"] = fd
    # case-256 classification derived ONLY from the authorized set
    if contrast["applied"]:
        fd256 = next((o["boundary"] for o in contrast["observations"]
                      if o["verdict"] == "differ"), None)
        out["case256_first_authorized_differing"] = fd256
        vals = [o["verdict"] for o in contrast["observations"]]
        out["case256_authorized_all_equal"] = all(
            v == "equal" for v in vals)

    # F. terminal selection (fail-closed, mechanically strict)
    terminal, terminal_reason = terminal_selection(
        blocked,
        [(o["boundary"], o["verdict"])
         for o in out["case4096_coarse_results"]],
        [(o["boundary"], o["verdict"])
         for o in refinement["observations"]],
        refinement["applied"])
    out["terminal"] = terminal
    out["terminal_reason"] = terminal_reason
    out["comparison_contract"] = COMPARISON_CONTRACT
    out["repeats"] = REPEATS
    if verbose:
        print(json.dumps(out, indent=2, sort_keys=True))
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write terminal-reduction.json (canonical JSON)")
    ap.add_argument("--repo", default=None,
                    help="repo root override (sandbox controls)")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo) if a.repo else None
    out = derive(verbose=not a.write, repo=repo)
    if a.write:
        p = os.path.join(REPO, R8G_DIR,
                         "terminal-reduction.json")
        with open(p, "w") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("wrote", p, "terminal:", out["terminal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
