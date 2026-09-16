#!/usr/bin/env python3
"""Issue #199 R8-E: differential negative controls (CPU-only, stdlib).

Method (identical to accepted R8-D v2): unmodified baseline first; assert
expected pre-mutation state; exactly one mutation; the intended check or
terminal must move; baseline-red invariants rejected.

The controls run on a SANDBOX copy of the R8-E evidence area (plus the
accepted predecessor manifests needed for byte-preservation checks) and
mutate the retained records — synthetic reducer-level controls, since
physically destructive injection adds no information for these seams.

Issue #199 required controls -> control ids:
  1. wrong R8-D predecessor identity rejected ........ NC1
  2. wrong model/binary identity rejected ............ NC2
  3. wrong case prompt / teacher-forced prefix ....... NC3
  4. placement identity swap rejected ................ NC4
  5. capture lacking token-position binding .......... NC5
  6. diagnostic build changing accepted next token ... NC6
  7. stale/session-contaminated capture .............. NC7
  8. HTTP n_probs cannot substitute .................. NC8
  9. authored characterization contradicting raw ..... NC9
 10. semantic characterization (rank structure vs
     authored prose) ................................ NC10 (correction)
 11. stale obs2 digest / every alias and one-sided-copy seam .... NC11-16
 17. internally consistent but byte-different obs2 ............ NC17
"""
import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import issue199_r8e_terminal_reduction as R  # noqa: E402
from issue199_r8e_authority import (  # noqa: E402
    CAMPAIGN_ID, R8D_V2_DIR, R8E_DIR)

REPO = os.path.abspath(os.path.join(HERE, ".."))


def sandbox(tmp):
    """Copy the evidence namespaces the reducer reads into a sandbox
    repo-root layout, then build a git repo whose history preserves the
    capture-head -> HEAD ancestry the dirty-worktree rule proves (the
    sandbox commits mimic the real campaign: capture head first, later
    namespace-confined commits on top)."""
    root = os.path.join(tmp, "repo")
    for rel in (R8E_DIR, R8D_V2_DIR,
                "docs/investigations/qwen38-flash-next-r8-a",
                "docs/investigations/qwen38-flash-next-r8-b",
                "docs/investigations/qwen38-flash-next-r8-c",
                "docs/investigations/qwen38-flash-next-r8-d"):
        src = os.path.join(REPO, rel)
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copytree(src, dst)
    import subprocess as sp
    def git(*a):
        sp.run(["git", "-C", root] + list(a), check=True,
               capture_output=True)
    git("init", "-q")
    git("config", "user.email", "sandbox@invalid")
    git("config", "user.name", "sandbox")
    # capture head commit = the evidence as captured (pre-terminal);
    # the terminal artifact is excluded so commit 2 is non-empty
    term = os.path.join(root, R8E_DIR, "terminal-reduction.json")
    term_saved = None
    if os.path.exists(term):
        term_saved = open(term, "rb").read()
        os.remove(term)
    git("add", "-A")
    git("commit", "-q", "-m", "capture head")
    cap_head = sp.run(["git", "-C", root, "rev-parse", "HEAD"],
                      capture_output=True, text=True).stdout.strip()
    # later namespace-confined commit (terminal + controls)
    if term_saved is not None:
        open(term, "wb").write(term_saved)
    git("add", "-A")
    git("commit", "-q", "-m", "terminal + controls")
    open(os.path.join(tmp, "cap_head"), "w").write(cap_head)
    return root


def read_cap(root, rel):
    with open(os.path.join(root, rel)) as fh:
        return json.load(fh)


def write_cap(root, rel, d):
    with open(os.path.join(root, rel), "w") as fh:
        json.dump(d, fh, indent=2, sort_keys=True)
        fh.write("\n")


def base_state(root):
    r = R.derive(area_override=root)
    return r


def control(root, cap_rel, mutate, expect_substr, note):
    """One mutation on one PRISTINE capture record; the reducer must
    BLOCK with the intended check. Exactly one mutation per control:
    the record is snapshotted before mutation and restored after, so
    controls never chain."""
    fp = os.path.join(root, cap_rel)
    pristine = open(fp, "rb").read()
    d = json.loads(pristine)
    mutate(d)
    write_cap(root, cap_rel, d)
    r = base_state(root)
    moved = (r["terminal"] == "R8E_EVIDENCE_BLOCKED" and
             any(expect_substr in p for p in r["problems"]))
    out = {"control": note, "moved": moved,
           "terminal": r["terminal"],
           "matched_problem": next(
               (p for p in r["problems"] if expect_substr in p), None)}
    open(fp, "wb").write(pristine)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    results = []

    with tempfile.TemporaryDirectory() as tmp:
        root = sandbox(tmp)
        cap_head = open(os.path.join(tmp, "cap_head")).read().strip()
        # bind every sandboxed capture record's git head to the sandbox
        # capture-head commit (and dirty) BEFORE the baseline reduction,
        # so the ancestry proof is exercisable from the first derive
        for sub in ("observations", "observations-tf", "nonperturbation"):
            dpath = os.path.join(root, R8E_DIR, "evidence", sub)
            if not os.path.isdir(dpath):
                continue
            for fn in os.listdir(dpath):
                if not (fn.startswith("capture-") and
                        fn.endswith(".json")):
                    continue
                fp = os.path.join(dpath, fn)
                d = json.load(open(fp))
                d["git_head"] = cap_head
                d["git_clean"] = False  # exercise the confined-dirty rule
                json.dump(d, open(fp, "w"), indent=2, sort_keys=True)
        # the repoint rewrote evidence bytes: regenerate the SANDBOX
        # manifest so the baseline reflects the repointed records (the
        # real campaign's manifest covers its own committed records).
        # The manifest builder also pins producers, so stage the
        # producer scripts into the sandbox first.
        import pathlib
        import shutil as _sh
        sdir = pathlib.Path(root) / "scripts"
        sdir.mkdir(exist_ok=True)
        for rel in ("issue199_r8e_authority.py",
                    "issue199_r8e_launch.py",
                    "issue199_r8e_capture.py",
                    "issue199_r8e_terminal_reduction.py",
                    "issue199_r8e_negative_controls.py",
                    "issue199_r8e_manifest.py"):
            _sh.copy(os.path.join(REPO, "scripts", rel),
                     sdir / rel)
        import issue199_r8e_manifest as MB
        MB.AREA = pathlib.Path(root) / R8E_DIR
        MB.ROOT = pathlib.Path(root)
        MB.main()
        base = base_state(root)
        base_terminal = base["terminal"]
        base_problems = list(base["problems"])
        baseline_green = base_terminal in (
            "R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED",
            "R8E_DEEPER_RUNTIME_LOCALIZATION_JUSTIFIED") and \
            not base_problems
        results.append({"control": "baseline",
                        "terminal": base_terminal,
                        "problems": base_problems[:3],
                        "baseline_green": baseline_green})

        def must_be_green():
            if not baseline_green:
                raise SystemExit(
                    "synthetic-green precondition violated: baseline "
                    f"terminal {base_terminal} with problems "
                    f"{base_problems[:3]}")

        must_be_green()
        C256 = "reference"
        cap = lambda arm, i: os.path.join(  # noqa: E731
            R8E_DIR, "evidence/observations",
            f"capture-case-256-{arm}-obs{i}.json")  # incremental state

        # These controls deliberately regenerate the sandbox manifest.  A
        # green generic manifest must never conceal a broken per-repeat
        # identity or actual-byte binding.
        import pathlib as _pathlib
        import issue199_r8e_manifest as _MB0

        def refresh_manifest():
            _MB0.AREA = _pathlib.Path(root) / R8E_DIR
            _MB0.ROOT = _pathlib.Path(root)
            _MB0.main()

        def byte_control(note, mutate, expect_substr):
            snaps = {}

            def snap(rel):
                fp = os.path.join(root, rel)
                snaps[rel] = (os.path.islink(fp),
                              os.readlink(fp) if os.path.islink(fp) else
                              open(fp, "rb").read())

            mutate(snap)
            refresh_manifest()
            r = base_state(root)
            for rel, (was_link, content) in snaps.items():
                fp = os.path.join(root, rel)
                if os.path.lexists(fp):
                    os.unlink(fp)
                if was_link:
                    os.symlink(content, fp)
                else:
                    open(fp, "wb").write(content)
            refresh_manifest()
            return {"control": note,
                    "moved": r["terminal"] == "R8E_EVIDENCE_BLOCKED" and
                    any(expect_substr in x for x in r["problems"]),
                    "terminal": r["terminal"],
                    "matched_problem": next((x for x in r["problems"]
                                             if expect_substr in x), None)}

        def ident(case, arm, i):
            return R.expected_repeat_identity(case, arm, i)

        # NC11: mutate only obs2's canonical raw sidecar; leave its
        # capture-authored digest stale while making the generic manifest
        # green.  The exact obs2 byte/digest binding must stop reduction.
        def nc11(snap):
            x = ident("case-256", "reference", 2)
            snap(x["raw_f32_rel"])
            fp = os.path.join(root, x["raw_f32_rel"])
            b = bytearray(open(fp, "rb").read())
            b[0] ^= 1
            open(fp, "wb").write(b)
        results.append(byte_control(
            "NC11 stale obs2 authored digest after raw-byte mutation",
            nc11, "f32_row_sha256 disagrees with actual raw hook row bytes"))

        def mutate_cap(case, arm, i, fn, snap):
            x = ident(case, arm, i)
            snap(x["capture_rel"])
            fp = os.path.join(root, x["capture_rel"])
            d = json.load(open(fp))
            fn(d)
            write_cap(root, x["capture_rel"], d)

        results.append(byte_control(
            "NC12 obs2 label aliases obs1 label",
            lambda snap: mutate_cap("case-256", "reference", 2,
                lambda d: d.__setitem__("label", "case-256-reference-obs1"), snap),
            "capture label != loop-derived label"))
        results.append(byte_control(
            "NC13 obs2 observation-path aliases obs1 JSONL",
            lambda snap: mutate_cap("case-256", "reference", 2,
                lambda d: d["binding"].__setitem__(
                    "observation_path", "obs-case-256-reference-obs1.jsonl"), snap),
            "binding.observation_path != loop-derived raw JSONL path"))

        # A symlink is a concrete raw-sidecar redirection.  Exact fixed
        # names alone are insufficient if their inode may alias obs1.
        def nc14(snap):
            one = ident("case-256", "reference", 1)
            two = ident("case-256", "reference", 2)
            snap(two["raw_f32_rel"])
            fp = os.path.join(root, two["raw_f32_rel"])
            os.unlink(fp)
            os.symlink(os.path.basename(os.path.join(root, one["raw_f32_rel"])), fp)
        results.append(byte_control("NC14 obs2 raw-sidecar aliases obs1",
                                    nc14, "must not alias another repeat"))

        def flip_only(rel):
            def mutate(snap):
                snap(rel)
                fp = os.path.join(root, rel)
                b = bytearray(open(fp, "rb").read())
                b[0] ^= 1
                open(fp, "wb").write(b)
            return mutate
        x2 = ident("case-256", "reference", 2)
        results.append(byte_control("NC15 obs2 raw-hook sidecar mutation only",
                                    flip_only(x2["raw_f32_rel"]),
                                    "raw hook f32 sidecar != retained row-copy"))
        results.append(byte_control("NC16 obs2 retained row-copy mutation only",
                                    flip_only(x2["row_copy_rel"]),
                                    "raw hook f32 sidecar != retained row-copy"))

        # NC17 is the hard negative: every obs2 authored field and both
        # duplicate sidecars are made self-consistent with a different,
        # valid float32 row.  Only independently derived repeat bytes may
        # reject it.
        def nc17(snap):
            import struct
            x = ident("case-256", "reference", 2)
            for rel in (x["capture_rel"], x["observation_rel"],
                        x["raw_f32_rel"], x["row_copy_rel"]):
                snap(rel)
            rawp = os.path.join(root, x["raw_f32_rel"])
            vals = list(struct.unpack("<%df" % (os.path.getsize(rawp) // 4),
                                      open(rawp, "rb").read()))
            # Preserve argmax/token identity but alter a non-focal score.
            vals[100] = vals[100] - 0.125
            b = struct.pack("<%df" % len(vals), *vals)
            for rel in (x["raw_f32_rel"], x["row_copy_rel"]):
                open(os.path.join(root, rel), "wb").write(b)
            fp = os.path.join(root, x["capture_rel"])
            d = json.load(open(fp))
            view = R._view_from_row_bytes(b, "case-256")
            d["f32_row_sha256"] = hashlib.sha256(b).hexdigest()
            d["f32_row_floats"] = len(vals)
            d["f32_row_stats"]["n_nonfinite"] = view["n_nonfinite"]
            d["f32_row_stats"]["fsum"] = view["fsum_math"]
            d["f32_row_stats"]["fsum_math"] = view["fsum_math"]
            d["f32_row_stats"]["sumsq"] = view["sumsq"]
            d["top16_from_f32_bytes"] = view["top16"]
            for row in d["hook_rows"]:
                if row["pos"] == x["generated_position"]:
                    row["top"] = view["top16"]
                    row["tok"] = view["winner"]
                    row["n_nonfinite"] = view["n_nonfinite"]
                    row["focus"] = [[tok, view["focus_tokens"][tok]["rank"],
                                     view["focus_tokens"][tok]["logit"]]
                                    for tok in (271, 34227)]
            write_cap(root, x["capture_rel"], d)
            with open(os.path.join(root, x["observation_rel"]), "w") as fh:
                for row in d["hook_rows"]:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
        results.append(byte_control("NC17 internally consistent but byte-different obs2",
                                    nc17, "repeat logits-row instability"))

        # NC1 wrong predecessor identity: corrupt an R8-D v2 evidence
        # byte covered by its manifest
        p = os.path.join(root, R8D_V2_DIR, "terminal-reduction.json")
        orig = open(p, "rb").read()
        open(p, "wb").write(orig.replace(b'"terminal"', b'"terminak"', 1))
        r = base_state(root)
        results.append({
            "control": "NC1 wrong R8-D predecessor identity",
            "moved": r["terminal"] == "R8E_EVIDENCE_BLOCKED" and
            any("byte-preserved" in p for p in r["problems"]),
            "terminal": r["terminal"]})
        open(p, "wb").write(orig)

        # NC2 wrong model/binary identity: instrumentation record binary
        ip = os.path.join(root, R8E_DIR,
                          "evidence/instrumentation/instrumentation.json")
        ip_pristine = open(ip, "rb").read()
        d = json.load(open(ip))
        d["binary_sha256"] = "deadbeef"  # not a sha256 hex digest
        json.dump(d, open(ip, "w"), indent=2, sort_keys=True)
        r = base_state(root)
        results.append({
            "control": "NC2 wrong binary identity",
            "moved": r["terminal"] == "R8E_EVIDENCE_BLOCKED" and
            any("binary" in p for p in r["problems"]),
            "terminal": r["terminal"]})
        # byte-exact restore (round-tripping through json.dump would
        # drop the trailing newline and drift the sandbox manifest)
        open(ip, "wb").write(ip_pristine)

        # NC3 wrong teacher-forced prefix: mutate request prompt bytes
        def nc3(d):
            import base64
            req = json.loads(base64.b64decode(d["request_body_b64"]))
            req["prompt"][-1] = req["prompt"][-1] + 1
            d["request_body_b64"] = base64.b64encode(json.dumps(
                req, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True).encode()).decode()
        results.append(control(root, cap(C256, 1), nc3,
                               "teacher-forced", "NC3 wrong prefix"))

        # NC4 placement swap: relabel a reference capture as candidate
        def nc4(d):
            d["arm"] = "candidate"
            d["binding"]["arm"] = "candidate"
        results.append(control(root, cap(C256, 1), nc4,
                               "mismatch", "NC4 placement swap"))

        # NC5 missing token-position binding: drop the pos-5 hook row
        def nc5(d):
            d["hook_rows"] = [r for r in d["hook_rows"]
                              if r["pos"] != d[
                                  "generated_position_observed"]]
        results.append(control(root, cap(C256, 1), nc5,
                               "token-position binding",
                               "NC5 no position binding"))

        # NC6 diagnostic changing accepted token: hook tok mutated AND
        # response token mutated consistently (a fully forged capture
        # must still fail the accepted-next-token check)
        def nc6(d):
            pos = d["generated_position_observed"]
            for hr in d["hook_rows"]:
                if hr["pos"] == pos:
                    hr["tok"] = hr["tok"] + 1
            d["response_generated_tokens"][pos] = \
                d["response_generated_tokens"][pos] + 1
        results.append(control(root, cap(C256, 1), nc6,
                               "accepted R8-D token",
                               "NC6 changed accepted token"))

        # NC7 stale capture: wrong campaign + stale git head + dirty tree
        def nc7(d):
            d["campaign"] = "issue195-r8d-true-greedy-requal-v2"
            d["git_head"] = "0" * 40
            d["git_clean"] = False
        results.append(control(root, cap(C256, 1), nc7,
                               "campaign", "NC7 stale capture"))

        # NC8 n_probs substitution: request carries n_probs and no
        # hook rows at all (HTTP-substitution attempt)
        def nc8(d):
            import base64
            req = json.loads(base64.b64decode(d["request_body_b64"]))
            req["n_probs"] = 16
            d["request_body_b64"] = base64.b64encode(json.dumps(
                req, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True).encode()).decode()
            d["hook_rows"] = []
        results.append(control(root, cap(C256, 1), nc8,
                               "token-position binding",
                               "NC8 n_probs substitution"))

        # NC9 authored characterization contradicting raw: reducer
        # derives from raw rows; inject a contradiction by making the
        # retained f32 row stats disagree with the hook row (n_nonfinite)
        def nc9(d):
            d["f32_row_stats"]["n_nonfinite"] = \
                d["f32_row_stats"]["n_nonfinite"] + 3
        results.append(control(root, cap(C256, 1), nc9,
                               "n_nonfinite mismatch",
                               "NC9 authored contradiction"))

        # NC10 semantic-characterization negative control (correction
        # round for the NO-GO review): prove the characterization (and
        # through it the terminal) is derived from the retained RAW
        # rank/logit structure and never from authored prose/summaries.
        # Two independent single forgeries, each restored afterwards:
        #
        #   (a) NON-NARROW FORGERY: in the case-256 candidate row,
        #       demote focal token 271 from rank 2 to rank 5 (argmax and
        #       all binding/token facts untouched) while planting an
        #       authored characterization field that still claims a
        #       narrow winner inversion. The reducer must flip the
        #       derived characterization to broader-focal-shift.
        #
        #   (b) NARROW FORGERY: in the case-4096 reference row, promote
        #       EOS 248046 from rank 5 to rank 2 (328 stays argmax, all
        #       binding facts untouched). Case-4096 then structurally
        #       mirrors case-256's clean 1<->2 inversion, and with both
        #       cases narrow the TERMINAL itself must flip off
        #       LOCALIZATION_JUSTIFIED to RESIDUAL_DIVERGENCE_
        #       CHARACTERIZED — the terminal follows bytes, not prose.
        #
        # The sandbox manifest is regenerated after each forgery so the
        # integrity layer cannot mask the semantic path under BLOCKED.
        def reforge_row(d, forge):
            pos = d["generated_position_observed"]
            for hr in d["hook_rows"]:
                if hr["pos"] != pos:
                    continue
                forge(hr)
                # keep the stored hook-vs-bytes cross-check consistent
                # with the forged hook row (the attacker updates every
                # authored derived field; only RAW structure differs)
                if d.get("top16_from_f32_bytes"):
                    d["top16_from_f32_bytes"] = [list(x) for x in
                                                hr["top"]]
                # authored prose claims narrow inversion regardless
                d["authored_characterization"] = \
                    "narrow-winner-inversion"

        def demote_271_to_rank5(hr, vals):
            # swap focal 271 (rank 2) with the rank-5 entry IN THE
            # BYTES, then mirror the new ordering into the hook row
            order = sorted(range(len(vals)), key=lambda i: -vals[i])
            i271, i5 = order[1], order[4]
            vals[i271], vals[i5] = vals[i5], vals[i271]
            order2 = sorted(range(len(vals)), key=lambda i: -vals[i])
            top16 = [[i, vals[i]] for i in order2[:16]]
            hr["top"] = top16
            hr["focus"] = [[t, next(idx + 1 for idx, (tt, _v) in
                                    enumerate(top16) if tt == t),
                            vals[t]] for t in (271, 34227)]

        def promote_eos_to_rank2(hr, vals):
            # move EOS 248046 (rank 5) to rank 2 IN THE BYTES (logit
            # strictly between the new top-2), mirror into hook row
            order = sorted(range(len(vals)), key=lambda i: -vals[i])
            ieos = order[4]
            vals[ieos] = (vals[order[0]] + vals[order[1]]) / 2.0
            order2 = sorted(range(len(vals)), key=lambda i: -vals[i])
            top16 = [[i, vals[i]] for i in order2[:16]]
            hr["top"] = top16
            hr["focus"] = [[t, next(idx + 1 for idx, (tt, _v) in
                                    enumerate(top16) if tt == t),
                            vals[t]] for t in (328, 248046)]

        import issue199_r8e_manifest as _MB
        import pathlib as _pl

        def regen_manifest(root_):
            _MB.AREA = _pl.Path(root_) / R8E_DIR
            _MB.ROOT = _pl.Path(root_)
            _MB.main()

        def semantic_control(cap_rel, forge, case, expect_pre,
                             expect_post, forge_only_arm):
            """Forge the rank structure CONSISTENTLY across the full
            retained evidence stack for one arm of one case: both
            repeats' hook rows, the float32 row sidecars (values
            rewritten so the forged ordering IS the bytes' ordering),
            the records' digests/stats of those bytes, and the manifest
            — leaving binding/token identity facts and any authored
            characterization prose untouched. What remains impossible
            to forge by construction: the accepted R8-D token pins
            (still equal to each arm's forged argmax) and the
            repeat-stability equality (both repeats forged
            identically). The derived characterization must follow the
            (forged) raw bytes, not the authored prose."""
            import struct

            def forge_arm(arm):
                for i in (1, 2):
                    crel = os.path.join(
                        R8E_DIR, "evidence/observations",
                        f"capture-{case}-{arm}-obs{i}.json")
                    fp_ = os.path.join(root, crel)
                    pristine_ = open(fp_, "rb").read()
                    d_ = json.loads(pristine_)
                    pos = d_["generated_position_observed"]
                    label = d_["label"]
                    rrel = os.path.join(
                        R8E_DIR, "evidence/observations",
                        f"row-{label}.pos{pos}.f32")
                    orel0 = os.path.join(
                        R8E_DIR, "evidence/observations",
                        f"obs-{label}.jsonl.pos{pos}.f32")
                    jrel = os.path.join(
                        R8E_DIR, "evidence/observations",
                        f"obs-{label}.jsonl")
                    snap(crel)
                    snap(jrel)
                    snap(rrel)
                    if os.path.exists(os.path.join(root, orel0)):
                        snap(orel0)
                    rfp = os.path.join(root, rrel)
                    row_bytes = open(rfp, "rb").read()
                    vals = list(struct.unpack(
                        "<%df" % (len(row_bytes) // 4), row_bytes))
                    for hr in d_["hook_rows"]:
                        if hr["pos"] != pos:
                            continue
                        forge(hr, vals)
                        if d_.get("top16_from_f32_bytes"):
                            d_["top16_from_f32_bytes"] = [
                                list(x) for x in hr["top"]]
                    # write the forged float values back into the
                    # sidecar bytes, then re-pin every digest/stat the
                    # records carry about those bytes
                    import hashlib as _hl
                    nb = struct.pack("<%df" % len(vals), *vals)
                    open(rfp, "wb").write(nb)
                    d_["f32_row_sha256"] = _hl.sha256(nb).hexdigest()
                    d_["f32_row_stats"] = {
                        "fsum": math.fsum(vals),
                        "fsum_math": math.fsum(vals),
                        "n_nonfinite": sum(
                            1 for v in vals if v != v or v in
                            (float("inf"), float("-inf"))),
                        "sumsq": math.fsum(v * v for v in vals),
                    }
                    # authored prose claims narrow inversion
                    d_["authored_characterization"] = \
                        "narrow-winner-inversion"
                    write_cap(root, crel, d_)
                    # The capture producer copied the raw hook JSONL into
                    # hook_rows.  A complete self-consistent negative must
                    # update that contract-bearing source as well.
                    with open(os.path.join(root, jrel), "w") as jfh:
                        for hook in d_["hook_rows"]:
                            jfh.write(json.dumps(hook, sort_keys=True) + "\n")
                    # also mirror the forgery into the raw obs jsonl
                    # sidecar the manifest covers
                    orel = os.path.join(
                        R8E_DIR, "evidence/observations",
                        f"obs-{label}.jsonl.pos{pos}.f32")
                    ofp = os.path.join(root, orel)
                    if os.path.exists(ofp):
                        open(ofp, "wb").write(nb)
            import math
            import subprocess as _sp2
            # snapshot every file we will touch (both arms, both
            # repeats: capture json + row sidecar + obs sidecar)
            snaps = {}

            def snap(rel):
                fp__ = os.path.join(root, rel)
                snaps[rel] = open(fp__, "rb").read()

            def restore(rel):
                open(os.path.join(root, rel), "wb").write(snaps[rel])
            forge_arm(forge_only_arm)
            regen_manifest(root)
            rr = base_state(root)
            for rel in snaps:
                restore(rel)
            regen_manifest(root)
            # sanity: pristine bytes fully restored (a later derive
            # must see the un-forged evidence)
            rr2 = base_state(root)
            assert rr2["terminal"] == base_r["terminal"], \
                "NC10 restore incomplete: %r" % rr2["problems"][:3]
            return {
                "derived_characterization":
                    rr["per_case"][case].get("characterization"),
                "derived_terminal": rr["terminal"],
                "derived_problems": rr["problems"][:3],
                "moved": (rr["per_case"][case].get(
                    "characterization") == expect_post
                    and expect_post != expect_pre)}

        base_r = base_state(root)
        assert base_r["per_case"]["case-256"][
            "characterization"] == "narrow-winner-inversion"
        assert base_r["per_case"]["case-4096"][
            "characterization"] == "broader-focal-shift"
        nc10a = semantic_control(
            os.path.join(R8E_DIR, "evidence/observations",
                         "capture-case-256-candidate-obs1.json"),
            demote_271_to_rank5, "case-256",
            "narrow-winner-inversion", "broader-focal-shift",
            forge_only_arm="candidate")
        nc10b = semantic_control(
            os.path.join(R8E_DIR, "evidence/observations",
                         "capture-case-4096-reference-obs1.json"),
            promote_eos_to_rank2, "case-4096",
            "broader-focal-shift", "narrow-winner-inversion",
            forge_only_arm="reference")
        results.append({
            "control": "NC10 semantic characterization (raw rank "
                       "structure mutated; authored characterization "
                       "still says narrow winner inversion)",
            "moved": nc10a["moved"] and nc10b["moved"] and
            nc10b["derived_terminal"] ==
            "R8E_RESIDUAL_DIVERGENCE_CHARACTERIZED",
            "nc10a_nonnarrow_forge": nc10a,
            "nc10b_narrow_forge": nc10b})

    ok = all(c["moved"] for c in results[1:])
    doc = {"campaign": CAMPAIGN_ID, "controls": results,
           "all_moved": ok, "baseline_green": baseline_green}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"all_moved": ok, "n": len(results) - 1}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
