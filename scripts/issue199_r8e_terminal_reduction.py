#!/usr/bin/env python3
"""Issue #199 R8-E: machine terminal reduction (CPU-only, stdlib).

Derives the R8-E terminal from the retained observation evidence under
docs/investigations/qwen38-flash-next-r8-e/. Fails closed on every
identity/binding check; emits terminal-reduction.json.

Terminals (exactly one):
  R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED
  R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED
  R8E_EVIDENCE_BLOCKED

Per-case characterization (from RAW rank/logit/margin evidence, no
post-hoc numeric threshold; the classes and the boundary between them
come from Issue #199's required structure, not from magnitudes observed
in this campaign):

- "narrow-winner-inversion": the two focal winner tokens (each arm's
  accepted winner at this decision point) are the immediate decision
  competitors in BOTH arms — each occupies rank 1 or 2 in both arms,
  their ordering is inverted, both are finite, and the top-16 overlap
  is coherent (>= 12/16).
- "broader-focal-shift": a focal winner token is NOT the other arm's
  runner-up (some focal token sits at rank >= 3 in some arm, or the
  focal ordering is not inverted) while the broader top-K set remains
  mostly shared — a score/rank re-arrangement beyond a pure winner
  swap, even though overlap alone would look coherent.
- "materially-different-score-structure": the broader top-K structure
  itself is broken (overlap < 12/16), a focal winner falls outside the
  other arm's retained top-16 entirely, or non-finite logits appear.

Terminal: LOCALIZATION_JUSTIFIED iff ANY case is NOT a
narrow-winner-inversion (broader focal shift or materially different
structure both qualify — Issue #199's terminal text asks whether the
evidence "cannot reasonably be explained by only a winner inversion").

BLOCKED iff no non-perturbing token-aligned observation path was
established (non-perturbation proofs failed / observation records
absent or binding-broken).
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from issue199_r8e_authority import (  # noqa: E402
    ACCEPTED_BINARY_SHA256, CAMPAIGN_ID, CASE256_CAND_TOKEN,
    CASE256_REF_TOKEN, CASES, CASE4096_CAND_TOKEN, CASE4096_REF_TOKEN,
    FOCUS_TOKENS, LLAMA_CPP_COMMIT, R8D_V2_TERMINAL, R8E_DIR,
    load_decision_inputs, r8d_v2_manifest_ok)

REPO = os.path.abspath(os.path.join(HERE, ".."))
AREA_OVERRIDE_MODE = False
EV = os.path.join(REPO, R8E_DIR, "evidence")

# accepted R8-D next-token at each decision point (from accepted bytes)
ACCEPTED_NEXT = {
    ("case-256", "reference"): CASE256_REF_TOKEN,
    ("case-256", "candidate"): CASE256_CAND_TOKEN,
    ("case-4096", "reference"): CASE4096_REF_TOKEN,
    ("case-4096", "candidate"): CASE4096_CAND_TOKEN,
}
DECISION_POS = {"case-256": 5, "case-4096": 0}


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def load(rel):
    with open(os.path.join(REPO, rel)) as fh:
        return json.load(fh)


def hook_row(rec, pos):
    for r in rec["hook_rows"]:
        if r["pos"] == pos:
            return r
    return None


def rank_of(row, tok):
    for t, rank, _v in row.get("focus", []):
        if t == tok:
            return rank
    return None


def expected_repeat_identity(case, arm, repeat):
    """The loop authority, rather than capture-controlled metadata,
    selects every artifact for one incremental observation repeat."""
    pos = DECISION_POS[case]
    label = f"{case}-{arm}-obs{repeat}"
    obsdir = os.path.join(R8E_DIR, "evidence", "observations")
    observation = f"obs-{label}.jsonl"
    return {
        "case": case, "arm": arm, "repeat": repeat, "label": label,
        "generated_position": pos,
        "capture_rel": os.path.join(obsdir, f"capture-{label}.json"),
        "observation_path": observation,
        "observation_rel": os.path.join(obsdir, observation),
        # This is the hook producer's output path: the capture producer
        # opens it before copying the identical retained row-* sidecar.
        "raw_f32_rel": os.path.join(obsdir, f"{observation}.pos{pos}.f32"),
        "row_copy_rel": os.path.join(obsdir, f"row-{label}.pos{pos}.f32"),
    }


def _float_equal(a, b):
    import math
    return (a == b or (isinstance(a, (int, float)) and
            isinstance(b, (int, float)) and math.isclose(
                a, b, rel_tol=1e-6, abs_tol=1e-7)))


def _view_from_row_bytes(row_b, case):
    """Decode a retained float32 row and derive every score fact used by
    characterization or capture-field cross-checks."""
    import struct
    import math
    vals = list(struct.unpack("<%df" % (len(row_b) // 4), row_b))
    finite = [i for i, v in enumerate(vals) if v == v and v not in
              (float("inf"), float("-inf"))]
    order = sorted(finite, key=lambda i: (-vals[i], i))
    top = [[i, vals[i]] for i in order[:16]]
    focus = {}
    for tok in FOCUS_TOKENS[case]:
        focus[tok] = {"rank": (order.index(tok) + 1 if tok in order else None),
                      "logit": vals[tok] if tok < len(vals) else None}
    winner, winner_logit = (top[0] if top else (None, None))
    runner, runner_logit = (top[1] if len(top) > 1 else (None, None))
    return {"top16_ids": [t for t, _v in top], "top16": top,
            "winner": winner, "winner_logit": winner_logit,
            "runner_up": runner, "runner_up_logit": runner_logit,
            "top1_top2_margin": (winner_logit - runner_logit
                                   if runner_logit is not None else None),
            "focus_tokens": focus,
            "n_nonfinite": len(vals) - len(finite),
            "float_count": len(vals), "actual_sha256": sha_b(row_b),
            "fsum_math": math.fsum(vals),
            "sumsq": math.fsum(v * v for v in vals)}


def bind_repeat_to_bytes(rec, repo, case, arm, repeat):
    """Bind *one* repeat to its exact raw hook output and copied row.

    The generated loop tuple is the only artifact selector.  In
    particular, a capture's mutable label never chooses a path.  The raw
    hook sidecar is canonical; row-* is a retained copy and is therefore
    separately required and byte-identical.
    """
    ident = expected_repeat_identity(case, arm, repeat)
    p = []
    if rec.get("label") != ident["label"]:
        p.append("capture label != loop-derived label")
    b = rec.get("binding") or {}
    for key in ("case", "arm", "generated_position"):
        if b.get(key) != ident[key]:
            p.append("binding.%s != loop-derived identity" % key)
    if b.get("observation_path") != ident["observation_path"]:
        p.append("binding.observation_path != loop-derived raw JSONL path")
    if rec.get("generated_position_observed") != ident["generated_position"]:
        p.append("capture generated position != loop-derived position")
    # The raw JSONL itself is contract-bearing, not just a filename in a
    # record.  It must be the fixed repeat's output and equal the retained
    # hook rows copied into its capture record.
    for rel, role in ((ident["observation_rel"], "raw observation JSONL"),
                      (ident["raw_f32_rel"], "raw hook f32 sidecar"),
                      (ident["row_copy_rel"], "retained row-copy f32 sidecar")):
        if os.path.islink(os.path.join(repo, rel)):
            p.append("loop-derived %s must not alias another repeat" % role)
    try:
        with open(os.path.join(repo, ident["observation_rel"])) as fh:
            raw_rows = [json.loads(line) for line in fh if line.strip()]
        if raw_rows != rec.get("hook_rows"):
            p.append("raw observation JSONL rows != capture hook_rows")
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        p.append("loop-derived raw observation JSONL unusable: %s" % exc)
    try:
        raw_b = read_bytes(os.path.join(repo, ident["raw_f32_rel"]))
    except FileNotFoundError:
        raw_b = None
        p.append("loop-derived raw hook f32 sidecar missing")
    try:
        copy_b = read_bytes(os.path.join(repo, ident["row_copy_rel"]))
    except FileNotFoundError:
        copy_b = None
        p.append("loop-derived retained row-copy f32 sidecar missing")
    if raw_b is None or copy_b is None:
        return None, ident, p
    if raw_b != copy_b:
        p.append("raw hook f32 sidecar != retained row-copy f32 sidecar")
    if len(raw_b) % 4:
        p.append("raw hook f32 row byte length not a multiple of 4")
        return None, ident, p
    view = _view_from_row_bytes(raw_b, case)
    if rec.get("f32_row_floats") != view["float_count"]:
        p.append("f32_row_floats disagrees with actual raw hook row bytes")
    if rec.get("f32_row_sha256") != view["actual_sha256"]:
        p.append("f32_row_sha256 disagrees with actual raw hook row bytes")
    row = hook_row(rec, ident["generated_position"])
    if row is None:
        p.append("no hook row at loop-derived generated position")
    else:
        if row.get("n_vocab") != view["float_count"]:
            p.append("hook n_vocab disagrees with actual raw hook row bytes")
        if row.get("n_nonfinite") != view["n_nonfinite"]:
            p.append("hook n_nonfinite disagrees with actual raw hook row bytes")
        top = row.get("top") or []
        if len(top) != len(view["top16"]) or any(
                ht != bt or not _float_equal(hv, bv)
                for (ht, hv), (bt, bv) in zip(top, view["top16"])):
            p.append("hook top-16 disagrees with actual raw hook row bytes")
        if row.get("tok") != view["winner"]:
            p.append("hook top1 token disagrees with actual raw hook row bytes")
        for tok in FOCUS_TOKENS[case]:
            authored = next((x for x in row.get("focus", []) if x[0] == tok), None)
            derived = view["focus_tokens"][tok]
            if (authored is None or authored[1] != derived["rank"] or
                    not _float_equal(authored[2], derived["logit"])):
                p.append("hook focal %s disagrees with actual raw hook row bytes" % tok)
    authored_top = rec.get("top16_from_f32_bytes") or []
    if authored_top and (len(authored_top) != len(view["top16"]) or any(
            at != bt or not _float_equal(av, bv)
            for (at, av), (bt, bv) in zip(authored_top, view["top16"]))):
        p.append("record top16_from_f32_bytes disagrees with actual raw hook row bytes")
    stats = rec.get("f32_row_stats") or {}
    if stats.get("n_nonfinite") != view["n_nonfinite"]:
        p.append("record f32_row_stats.n_nonfinite disagrees with actual raw hook row bytes")
    for key in ("fsum", "fsum_math", "sumsq"):
        if not _float_equal(stats.get(key), view["fsum_math"] if key in
                            ("fsum", "fsum_math") else view["sumsq"]):
            p.append("record f32_row_stats.%s disagrees with actual raw hook row bytes" % key)
    return view, ident, p


def bytes_derived_view(rec, repo, case, arm, repeat=1):
    """Re-derive argmax/top-16/focal ranks directly from the retained
    float32 row bytes (correction-round P2: authored hook 'focus'
    ranks must never be the sole authority for the characterization).

    Returns (view, problems): view is an arm_view-shaped dict built
    ONLY from the bytes, or None when the row bytes are unavailable
    (the caller then fails closed for the incremental state class).
    """
    view, _ident, p = bind_repeat_to_bytes(rec, repo, case, arm, repeat)
    return view, p


def logit_of(row, tok):
    for t, _rank, v in row.get("focus", []):
        if t == tok:
            return v
    for t, v in row.get("top", []):
        if t == tok:
            return v
    return None


def check_capture(rec, case, arm, inputs, tf=False):
    """Fail-closed identity/binding checks on one capture record.
    tf=True: teacher-forced state class (pos 0 observed, tf prefix in
    the request); the accepted-next-token equality is NOT required for
    tf rows (physically they legitimately differ — recorded, and that
    difference is itself retained evidence), but all binding checks
    still apply."""
    p = []
    if rec.get("schema") != "inferswarm.issue199.observation/1":
        p.append("wrong schema")
    if rec.get("campaign") != CAMPAIGN_ID:
        p.append("wrong campaign")
    if rec.get("case") != case or rec.get("arm") != arm:
        p.append("case/arm mismatch")
    if tf:
        if rec.get("state_class") != "tf":
            p.append("tf capture not labeled state_class=tf")
        pos = 0
    else:
        if rec.get("state_class") not in (None, "incremental"):
            p.append("capture state_class is not incremental")
        pos = DECISION_POS[case]
    row = hook_row(rec, pos)
    if row is None:
        p.append(f"no hook row at generated position {pos} "
                 "(score capture lacking token-position binding)")
        return p, None
    if rec.get("generated_position_observed") != pos:
        p.append("record generated_position != decision position")
    b = rec.get("binding") or {}
    if b.get("generated_position") != pos or b.get("case") != case or \
            b.get("arm") != arm:
        p.append("binding block missing/misaligned")
    # prompt identity (accepted bytes)
    dp_prefix = rec.get("teacher_forced_prefix") or []
    if tf:
        exp_prompt = list(inputs[case][arm]["prompt_token_ids"]) + \
            list(dp_prefix)
    else:
        exp_prompt = list(inputs[case][arm]["prompt_token_ids"])
    req = json.loads(__import__("base64").b64decode(
        rec["request_body_b64"]))
    if req.get("prompt") != exp_prompt:
        p.append("request prompt != accepted state (wrong case prompt "
                 "or teacher-forced prefix)")
    # Worktree state at capture: full cleanliness is the simple green
    # path. A dirty flag is admissible ONLY when mechanically provable
    # as the campaign's own not-yet-committed evidence: the capture head
    # must be the frozen producer head (or an ancestor of HEAD whose
    # descendant delta is confined to the additive campaign namespace +
    # registration files). This mirrors the accepted R8-D v2
    # CORRECTNESS_PREFIXES descendant rule.
    if not rec.get("git_clean"):
        cap_head = rec.get("git_head")
        if cap_head is None:
            p.append("dirty worktree with no recorded git head")
        else:
            import subprocess as _sp
            repo = os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))) if not AREA_OVERRIDE_MODE                 else REPO
            anc = _sp.run(["git", "merge-base", "--is-ancestor",
                           cap_head, "HEAD"], cwd=repo,
                          capture_output=True)
            if anc.returncode != 0:
                p.append("capture head is not an ancestor of HEAD")
            else:
                # Fail-closed INVERSION (accepted R8-D v2
                # CORRECTNESS_PREFIXES pattern): a descendant HEAD may
                # advance freely (CI merge commits, registration,
                # unrelated mainline work) BUT any change INSIDE a
                # correctness-bearing prefix (the campaign's frozen
                # producers, its accepted predecessors' authority/evidence,
                # or the pinned run-driver bytes) invalidates captures
                # bound to the earlier head.
                diff = _sp.run(
                    ["git", "diff", "--name-only", cap_head, "HEAD"],
                    cwd=repo, capture_output=True,
                    text=True).stdout.split()
                correctness_pre = (
                    "scripts/issue199_r8e_authority.py",
                    "scripts/issue199_r8e_launch.py",
                    "scripts/issue199_r8e_capture.py",
                    os.path.join(R8E_DIR, "evidence/run/run-driver.sh"),
                    os.path.join(R8E_DIR, "evidence/run/wait_backends.sh"),
                    os.path.join(R8E_DIR, "evidence/run/"
                                 "stop_rpc_backends.sh"),
                    "docs/investigations/qwen38-flash-next-r8-a/",
                    "docs/investigations/qwen38-flash-next-r8-b/",
                    "docs/investigations/qwen38-flash-next-r8-c/",
                    "docs/investigations/qwen38-flash-next-r8-d/",
                    "docs/investigations/qwen38-flash-next-r8-d-v2/")
                bad = [x for x in diff
                       if x.startswith(correctness_pre)]
                if bad:
                    p.append("correctness-bearing changes after the "
                             "capture head: " + ", ".join(bad[:3]))
                # fall through: dirt provably confined to non-
                # correctness-bearing additions (e.g. this campaign's
                # own not-yet-committed evidence output)
    # non-perturbation: sampled token must equal the accepted R8-D
    # token (incremental state class only; tf rows record their own
    # tokens as retained evidence of the state-class difference)
    exp_tok = ACCEPTED_NEXT[(case, arm)]
    gt = rec.get("response_generated_tokens") or []
    if not tf:
        if pos >= len(gt) or gt[pos] != exp_tok:
            p.append(f"response token at pos {pos} != accepted R8-D "
                     f"token {exp_tok} (perturbing observation path)")
        if row["tok"] != exp_tok:
            p.append("hook tok != accepted R8-D token")
        # authored-vs-derived consistency: hook n_nonfinite must equal
        # the n_nonfinite derived from the retained f32 bytes
        st = rec.get("f32_row_stats") or {}
        if "n_nonfinite" in st and st["n_nonfinite"] != row.get(
                "n_nonfinite"):
            p.append("n_nonfinite mismatch hook vs derived bytes "
                     "(authored characterization contradicting raw "
                     "score evidence)")
        # hook top-16 vs top16 re-derived from the retained f32 bytes
        # (hook prints 9 significant digits; compare at that precision)
        b16 = rec.get("top16_from_f32_bytes") or []
        if b16:
            h16 = row.get("top") or []
            bad16 = any(ht != bt or abs(hv - bv) > abs(hv) * 1e-6
                        for (ht, hv), (bt, bv) in zip(h16, b16))
            if bad16 or len(h16) != len(b16):
                p.append("top16 mismatch hook vs derived bytes")
    else:
        rec["_tf_note"] = ("tf state class: token equality to R8-D not "
                           "required; difference retained as evidence")
    return p, row


def arm_view(row, focus_tokens):
    """Per-arm decision-point view from the retained hook row + bytes."""
    top = row["top"]
    ids = [t for t, _v in top]
    winner, winner_logit = top[0]
    runner, runner_logit = top[1] if len(top) > 1 else (None, None)
    margin = (winner_logit - runner_logit) if runner is not None else None
    focus = {t: {"rank": rank_of(row, t), "logit": logit_of(row, t)}
             for t in focus_tokens}
    return {"top16_ids": ids, "top16": top, "winner": winner,
            "winner_logit": winner_logit, "runner_up": runner,
            "runner_up_logit": runner_logit, "top1_top2_margin": margin,
            "focus_tokens": focus, "n_nonfinite": row["n_nonfinite"]}


def characterize(case, ref_view, cand_view, focus_tokens):
    """Structural characterization from raw rank facts only.

    Three mutually-exclusive classes, derived from Issue #199's own
    decision structure (no numeric tolerance on logit magnitudes):

    - narrow-winner-inversion: both focal winner tokens hold ranks 1
      and 2 in BOTH arms with inverted ordering (the immediate
      decision competitors simply trade places) and the top-16 set
      remains coherent;
    - broader-focal-shift: a focal token is not the other winner's
      immediate runner-up somewhere (rank >= 3, absent from a top-16,
      or ordering not inverted) while top-K overlap alone would still
      look coherent;
    - materially-different-score-structure: broader top-K structure
      broken (overlap < 12/16) or non-finite logits.
    """
    raw = {
        "top16_set_equal":
            set(ref_view["top16_ids"]) == set(cand_view["top16_ids"]),
        "top16_order_equal":
            ref_view["top16_ids"] == cand_view["top16_ids"],
        "ref_top1_top2_margin": ref_view["top1_top2_margin"],
        "cand_top1_top2_margin": cand_view["top1_top2_margin"],
        "ref_top16": ref_view["top16"],
        "cand_top16": cand_view["top16"],
        "focus": {arm: ref_view["focus_tokens"] if arm == "reference"
                  else cand_view["focus_tokens"] for arm in
                  ("reference", "candidate")},
    }
    inter = set(ref_view["top16_ids"]) & set(cand_view["top16_ids"])
    raw["top16_overlap_count"] = len(inter)
    raw["cross_arm_logit_deltas"] = {
        str(tok): (None if (ref_view["focus_tokens"][tok]["logit"] is None
                            or cand_view["focus_tokens"][tok]["logit"]
                            is None)
                   else cand_view["focus_tokens"][tok]["logit"]
                   - ref_view["focus_tokens"][tok]["logit"])
        for tok in focus_tokens}
    for tok in focus_tokens:
        raw[f"ref_focus_{tok}"] = ref_view["focus_tokens"][tok]
        raw[f"cand_focus_{tok}"] = cand_view["focus_tokens"][tok]

    nonfinite = bool(ref_view["n_nonfinite"] or cand_view["n_nonfinite"])
    overlap = len(inter)
    # rank facts per focal token (rank None = outside that arm's
    # retained top-16 / unranked in the focus rows)
    fr = {tok: ref_view["focus_tokens"][tok]["rank"]
          for tok in focus_tokens}
    cr = {tok: cand_view["focus_tokens"][tok]["rank"]
          for tok in focus_tokens}
    ranks = {("reference", tok): fr[tok] for tok in focus_tokens}
    ranks.update({("candidate", tok): cr[tok] for tok in focus_tokens})
    raw["focal_ranks"] = {f"{arm}|{tok}": r for (arm, tok), r
                          in ranks.items()}
    raw["focal_rank_facts"] = {
        "both_focal_rank_1_or_2_in_both_arms": all(
            r in (1, 2) for r in ranks.values()),
        "focal_ordering_inverted": (
            fr[focus_tokens[0]] == 1 and cr[focus_tokens[1]] == 1),
        "any_focal_rank_missing": any(r is None for r in ranks.values()),
    }
    if nonfinite:
        clazz = "materially-different-score-structure"
        reason = ("non-finite logits present (%d ref / %d cand)"
                  % (ref_view["n_nonfinite"], cand_view["n_nonfinite"]))
    elif overlap < 12 or raw["focal_rank_facts"]["any_focal_rank_missing"]:
        clazz = "materially-different-score-structure"
        reason = ("top-16 overlap only %d/16 across arms"
                  % overlap) if overlap < 12 else (
            "focal winner token absent from an arm's retained top-16")
    elif (raw["focal_rank_facts"]["both_focal_rank_1_or_2_in_both_arms"]
            and raw["focal_rank_facts"]["focal_ordering_inverted"]):
        clazz = "narrow-winner-inversion"
        reason = ("focal winner tokens occupy ranks 1 and 2 in both arms "
                  "with inverted ordering (top-16 overlap %d/16)"
                  % overlap)
    else:
        clazz = "broader-focal-shift"
        detail = []
        for (arm, tok), r in sorted(ranks.items()):
            if r is None:
                continue
            if r >= 3:
                detail.append(f"{tok} is rank {r} in the {arm} arm "
                              "(not the immediate runner-up)")
        if not raw["focal_rank_facts"]["focal_ordering_inverted"]:
            detail.append("focal ordering not inverted across arms")
        reason = ("; ".join(detail) if detail else
                  "focal rank structure is not a clean 1<->2 inversion") + \
            f" (top-16 overlap {overlap}/16 retained as context)"
    raw["shifted_reasons"] = [reason]
    raw["characterization"] = clazz
    return raw


def _manifest_ok(repo):
    """Verify every MANIFEST.sha256 row against the on-disk bytes AND
    the on-disk file set against the listed set (the reducer is itself
    a manifest consumer: doctored evidence bytes must fail closed at
    reduction time, not only in the CI test layer). Review lane-1 P2,
    PR #205."""
    import hashlib
    p = os.path.join(repo, R8E_DIR, "MANIFEST.sha256")
    if not os.path.exists(p):
        return False, "manifest missing"
    listed = set()
    for line in open(p):
        line = line.strip()
        if not line:
            continue
        digest, name = line.split("  ", 1)
        fp = os.path.join(repo, name)
        if not os.path.exists(fp):
            return False, name + " missing"
        got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        if got != digest:
            return False, name + " digest mismatch (tampered evidence)"
        listed.add(name)
    ondisk = set()
    for dirpath, _dirs, files in os.walk(os.path.join(repo, R8E_DIR)):
        for f in files:
            if f in ("MANIFEST.sha256", "producer-hashes.json"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f),
                                  repo).replace(os.sep, "/")
            ondisk.add(rel)
    if listed != ondisk:
        return False, "manifest/on-disk file-set drift: %s" %             sorted(listed ^ ondisk)[:3]
    return True, "ok (%d rows)" % len(listed)


def derive(area_override=None):
    """Full reduction. Returns dict with terminal + checks."""
    global REPO, EV
    if area_override:
        # sandbox mode: the override dir plays the role of the repo root
        global AREA_OVERRIDE_MODE
        AREA_OVERRIDE_MODE = True
        REPO = area_override
        EV = os.path.join(REPO, R8E_DIR, "evidence")
    problems = []
    checks = {}

    # 0a. evidence manifest: the reducer re-hashes the retained bytes
    # itself (never trusts record-embedded digests alone)
    mok, mmsg = _manifest_ok(REPO)
    checks["evidence_manifest_verified"] = mok
    if not mok:
        problems.append("evidence manifest verification failed: " + mmsg)

    # 0. accepted predecessor identity + byte preservation
    ok, msg = r8d_v2_manifest_ok(REPO)
    checks["r8d_v2_evidence_byte_preserved"] = ok
    if not ok:
        problems.append("R8-D v2 evidence not byte-preserved: " + msg)

    inputs = load_decision_inputs(REPO)

    # 1. instrumentation record
    try:
        instr = load(os.path.join(R8E_DIR,
                                  "evidence/instrumentation/"
                                  "instrumentation.json"))
        checks["instrumentation_record_present"] = True
        for k in ("patch_sha256", "applied_source_sha256",
                  "binary_sha256", "build_host", "base_commit"):
            if not instr.get(k):
                problems.append("instrumentation record missing " + k)
        import re as _re
        if instr.get("base_commit") != LLAMA_CPP_COMMIT:
            problems.append("instrumentation base commit != authority")
        for k in ("patch_sha256", "applied_source_sha256",
                  "binary_sha256"):
            v = instr.get(k) or ""
            if not _re.fullmatch(r"[0-9a-f]{64}", v):
                problems.append("instrumentation " + k +
                                " is not a sha256 hex digest")
        if instr.get("binary_sha256") == ACCEPTED_BINARY_SHA256.get(
                "llama-server"):
            problems.append("instrumentation binary sha equals the "
                            "accepted uninstrumented llama-server")
    except FileNotFoundError:
        instr = None
        checks["instrumentation_record_present"] = False
        problems.append("instrumentation record missing")

    # 2. captures: 2 cases x 2 arms x >=2 repeats, obs mode.
    # Decision-faithful evidence = incremental state class (original
    # accepted prompt; hook observes the target position during the
    # byte-identical-to-R8-D decode). tf (teacher-forced) captures are
    # retained as a SEPARATE state class: the physical pre-freeze smoke
    # proved the case-256 tf construction does NOT reproduce the R8-D
    # decision computation (reference emits 34227, not 271, under tf
    # prefill), so tf rows can never substitute for incremental rows.
    views = {}
    stability = {}
    repeat_byte_details = {}
    tf_views = {}
    for case in CASES:
        for arm in ("reference", "candidate"):
            recs = []
            for i in (1, 2):
                rel = os.path.join(
                    R8E_DIR, "evidence", "observations",
                    f"capture-{case}-{arm}-obs{i}.json")
                try:
                    rec = load(rel)
                except FileNotFoundError:
                    problems.append("missing capture " + rel)
                    continue
                if rec.get("state_class") != "incremental":
                    problems.append(
                        f"{case}/{arm}/obs{i}: decision-faithful capture "
                        "is not incremental state class")
                    continue
                p, row = check_capture(rec, case, arm, inputs)
                if p:
                    problems.append(f"{case}/{arm}/obs{i}: " + "; ".join(p))
                    continue
                # Every repeat independently opens its fixed raw hook
                # sidecar and fixed retained row copy.  Do this before
                # repeat comparison; a matching pair of authored digests
                # can never establish stability.
                bview, ident, bprob = bind_repeat_to_bytes(
                    rec, REPO, case, arm, i)
                detail_key = f"{case}/{arm}/obs{i}"
                repeat_byte_details[detail_key] = {
                    "identity": ident,
                    "actual_raw_hook_sha256": (bview or {}).get(
                        "actual_sha256"),
                    "actual_row_copy_sha256": (sha_b(read_bytes(
                        os.path.join(REPO, ident["row_copy_rel"])))
                        if os.path.exists(os.path.join(
                            REPO, ident["row_copy_rel"])) else None),
                    "raw_hook_equals_row_copy": not any(
                        "raw hook f32 sidecar != retained row-copy" in x
                        for x in bprob),
                    "problems": bprob,
                }
                if bprob or bview is None:
                    problems.append(f"{case}/{arm}/obs{i}: " + "; ".join(
                        bprob or ["actual retained bytes unusable"]))
                    continue
                recs.append((rec, row, bview))
            if len(recs) < 2:
                problems.append(f"{case}/{arm}: fewer than 2 valid repeats")
                continue
            (r1, row1, view1), (r2, row2, view2) = recs
            stable_tok = r1["response_generated_tokens"] == \
                r2["response_generated_tokens"]
            stable_row = view1["actual_sha256"] == view2["actual_sha256"]
            stability[f"{case}/{arm}"] = {
                "repeat_token_equality": stable_tok,
                "repeat_f32_row_sha256_equality": stable_row,
                "actual_obs1_raw_hook_sha256": view1["actual_sha256"],
                "actual_obs2_raw_hook_sha256": view2["actual_sha256"],
            }
            if not stable_tok:
                problems.append(f"{case}/{arm}: repeat token instability")
            if not stable_row:
                problems.append(
                    f"{case}/{arm}: repeat logits-row instability")
            # Characterization uses the independently decoded obs1 raw
            # hook bytes.  obs2 was decoded with identical authority above
            # and gates repeat stability, rather than being a mere digest.
            bview = view1
            hview = arm_view(row1, FOCUS_TOKENS[case])
            xb = []
            if bview["winner"] != hview["winner"]:
                xb.append("argmax differs hook vs bytes")
            if bview["top16_ids"] != hview["top16_ids"]:
                xb.append("top-16 order differs hook vs bytes")
            for tok in FOCUS_TOKENS[case]:
                br = bview["focus_tokens"][tok]["rank"]
                hr = hview["focus_tokens"][tok]["rank"]
                if br != hr:
                    xb.append(f"focal {tok} rank hook {hr} vs bytes {br}")
            if xb:
                problems.append(f"{case}/{arm}/obs1 authored-vs-bytes "
                                "contradiction: " + "; ".join(xb))
                continue
            views[(case, arm)] = bview

    # 2b. teacher-forced captures (separate state class; informational,
    # must be internally valid + stable but never gates the terminal)
    for case in CASES:
        for arm in ("reference", "candidate"):
            recs = []
            for i in (1, 2):
                rel = os.path.join(
                    R8E_DIR, "evidence", "observations-tf",
                    f"capture-{case}-{arm}-tf{i}.json")
                try:
                    rec = load(rel)
                except FileNotFoundError:
                    continue
                # tf class: the hook JSONL row (top16/focus/ranks) is
                # the retained observation; a missing pos-0 f32 sidecar
                # is tolerated for tf only (the tf construction is
                # informational and never gates the terminal — the
                # driver's LLAMA_OBSERVE_POS targets the incremental
                # decision position).
                p, row = check_capture(rec, case, arm, inputs,
                                       tf=True)
                p = [x for x in p
                     if x not in ("hook n_vocab != f32 row floats",
                                  "no f32 row retained at target position")]
                if p:
                    problems.append(f"tf {case}/{arm}/tf{i}: " +
                                    "; ".join(p))
                    continue
                recs.append((rec, row))
            if len(recs) == 2:
                tf_views[(case, arm)] = arm_view(recs[0][1],
                                                 FOCUS_TOKENS[case])

    # 3. non-perturbation controls (accepted binary, both arms, both cases)
    for case in CASES:
        for arm in ("reference", "candidate"):
            for i in (1, 2):
                rel = os.path.join(
                    R8E_DIR, "evidence", "nonperturbation",
                    f"capture-{case}-{arm}-accepted{i}.json")
                try:
                    rec = load(rel)
                except FileNotFoundError:
                    problems.append("missing non-perturbation " + rel)
                    continue
                exp_tok = ACCEPTED_NEXT[(case, arm)]
                pos = DECISION_POS[case]
                gt = rec.get("response_generated_tokens") or []
                if pos >= len(gt) or gt[pos] != exp_tok:
                    problems.append(
                        f"non-perturbation {case}/{arm}/accepted{i}: "
                        f"token at pos {pos} != accepted {exp_tok}")

    # 4. per-case characterization
    per_case = {}
    any_shifted = False
    for case in CASES:
        if (case, "reference") in views and (case, "candidate") in views:
            c = characterize(case, views[(case, "reference")],
                             views[(case, "candidate")],
                             FOCUS_TOKENS[case])
            per_case[case] = c
            if c["characterization"] != "narrow-winner-inversion":
                # Issue #199: deeper localization is justified when the
                # decision-point evidence "cannot reasonably be
                # explained by only a winner inversion" — a broader
                # focal score/rank shift qualifies exactly as much as a
                # materially reordered distribution.
                any_shifted = True
        else:
            per_case[case] = {"error": "missing valid arm view"}

    # 5. terminal
    if problems:
        # BLOCKED only for observation-path failures; identity problems
        # after valid captures are hard failures (also BLOCKED here —
        # no valid terminal exists)
        terminal = "R8E_EVIDENCE_BLOCKED"
    elif any_shifted:
        terminal = "R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED"
    else:
        terminal = "R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED"

    return {
        "campaign": CAMPAIGN_ID,
        "terminal": terminal,
        "checks": checks,
        "problems": problems,
        "stability": stability,
        "repeat_byte_details": repeat_byte_details,
        "per_case": per_case,
        "tf_views": {f"{c}/{a}": v for (c, a), v in tf_views.items()},
        "accepted_predecessor_terminal": R8D_V2_TERMINAL,
    }


def main():
    r = derive()
    out = os.path.join(EV and os.path.join(REPO, R8E_DIR) or R8E_DIR,
                       "terminal-reduction.json")
    with open(out, "w") as fh:
        json.dump(r, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"terminal": r["terminal"],
                      "problems": r["problems"][:10]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
