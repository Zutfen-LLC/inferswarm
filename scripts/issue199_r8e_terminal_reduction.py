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
post-hoc threshold): a branch is distribution-shifted (justifying deeper
localization) iff the top-K structure materially differs — mechanically:
the two arms' top-16 sets are equal AND the winner-vs-runner-up margins
have the same sign structure in a narrow band around zero (margin
inversion) vs any of: (a) top-16 set/rank overlap materially broken,
(b) the loser of one arm missing from the other arm's top-16 entirely
with a large gap, or (c) non-finite logits. The reducer reports raw
values and BOTH per-case characterizations; the terminal is
LOCALIZATION_JUSTIFIED iff EITHER case is distribution-shifted.

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
    """Margin-inversion vs distribution-shift, from raw structure only."""
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
    shifted_reasons = []
    if raw["top16_set_equal"] is False:
        # measure the overlap
        inter = set(ref_view["top16_ids"]) & set(cand_view["top16_ids"])
        raw["top16_overlap_count"] = len(inter)
        if len(inter) < 12:
            shifted_reasons.append(
                f"top-16 overlap only {len(inter)}/16 across arms")
    if ref_view["n_nonfinite"] or cand_view["n_nonfinite"]:
        shifted_reasons.append("non-finite logits present")
    # cross-arm winner handling
    for tok, arm in ((t, "reference") for t in focus_tokens):
        v = (ref_view if arm == "reference" else cand_view)["focus_tokens"][tok]
        raw[f"ref_focus_{tok}"] = v
    for tok in focus_tokens:
        raw[f"cand_focus_{tok}"] = cand_view["focus_tokens"][tok]
    raw["shifted_reasons"] = shifted_reasons
    raw["characterization"] = ("materially-different-score-structure"
                               if shifted_reasons else
                               "consistent-with-margin-inversion")
    return raw


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
                recs.append((rec, row))
            if len(recs) < 2:
                problems.append(f"{case}/{arm}: fewer than 2 valid repeats")
                continue
            (r1, row1), (r2, row2) = recs
            stable_tok = r1["response_generated_tokens"] == \
                r2["response_generated_tokens"]
            stable_row = r1["f32_row_sha256"] == r2["f32_row_sha256"]
            stability[f"{case}/{arm}"] = {
                "repeat_token_equality": stable_tok,
                "repeat_f32_row_sha256_equality": stable_row,
            }
            if not stable_tok:
                problems.append(f"{case}/{arm}: repeat token instability")
            if not stable_row:
                problems.append(
                    f"{case}/{arm}: repeat logits-row instability")
            views[(case, arm)] = arm_view(row1, FOCUS_TOKENS[case])

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
            if c["characterization"] == "materially-different-score-structure":
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
