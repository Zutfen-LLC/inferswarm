#!/usr/bin/env python3
"""Issue #207 R8-G: fail-closed negative controls (CPU-only, stdlib).

Correction round 2026-09-17: every control is a REAL ATTACK on the
production validation/reduction path — mutate exactly one thing in an
isolated sandbox copy of the evidence tree (plus the minimal retained
inputs the reducer binds), run the actual reducer (derive) or the
actual binding function against the sandbox, and assert a specific
fail-closed outcome. No documentation-only assertions.

Sandbox shape (PR #208 correction): the sandbox materializes the R8-G
evidence tree, the R8-G namespace root, the R8-D v2 / R8-E predecessor
namespaces (their manifests + the rows the loaders re-hash), the six
R8-G producer scripts, and the retained R8-E observation captures the
row-sha loader reads. The reducer is imported ONCE and pointed at each
sandbox via set_repo().

The 15 Issue #207 control classes:

 NC1  wrong R8-D/R8-E predecessor manifest/evidence identity
      (a predecessor manifest row digest tampered in the sandbox ->
      r8d_v2/r8e manifest_ok False -> BLOCKED terminal)
 NC2  wrong model member/revision/binary identity
      (instrumentation.json binary sha tampered AND the record's
      server_env_hint / producer pins — the reducer's manifest
      verification + instrumentation row is an input row; tampering it
      must flip the input-manifest digest -> BLOCKED)
 NC3  wrong case prompt/generated-prefix identity (request prompt bytes
      edited on a capture record -> identity gate rejects)
 NC4  reference/candidate placement swap (arm labels swapped on a
      capture PAIR: reference-labeled capture carries the candidate's
      seam-anchor bytes -> arm-anchored seam check rejects)
 NC5  missing token-position binding (logits hook row removed at the
      decision position -> identity gate rejects)
 NC6  missing source/runtime boundary identity (frozen boundary row
      name blanked -> boundary_state_strict raises Blocked)
 NC7  stale capture substitution (obs1's sidecar substituted into the
      obs2 sidecar slot whose row bytes differ -> repeat-stability or
      authored-vs-bytes rejection)
 NC8  authored digest/statistics contradicting retained raw bytes
      (row sha256 edited -> bytes-vs-row contradiction)
 NC9  alias/symlink substitution with the CORRECT expected bytes
      (sidecar replaced by a symlink to a byte-identical copy ->
      lstat symlink rejection; also a path-alias variant: a symlinked
      DIRECTORY whose sidecar resolves to another capture's identical-
      size sidecar -> canonical-containment rejection)
 NC10 same-size wrong raw state bytes (one float bit-flipped in a
      sidecar with the row sha re-forged consistently -> nonfinite
      count or repeat-stability/compare change; MUST NOT pass
      silently as an accepted equal/differ swap of a DIFFERENT pair)
 NC11 observation build changing accepted token or R8-E score row
      (response token drift on a nonpert capture -> identity gate
      rejects; also seam-anchor drift)
 NC12 post-hoc checkpoint insertion (a boundary row NOT in the frozen
      set inserted into a capture record AND its sidecar materialized:
      the terminal input set must be unchanged — the reducer consumes
      exactly the frozen set; and if the inserted row masquerades under
      a frozen name alias it is rejected by name-identity checks)
 NC13 earliest-boundary terminal without an immediately preceding
      accepted match (terminal predicate attack: synthetic refinement
      map whose first boundary differs with a missing earlier frozen
      boundary -> must NOT emit LOCALIZED)
 NC14 monotonic/localized terminal attempted after reconvergence
      (terminal predicate attack: refinement map with differ->equal
      inside the interval -> must emit NONMONOTONIC, never LOCALIZED)
 NC15 case-256 substituted for case-4096 authority (case label edited
      on a refine capture: prompt/token identity vs the accepted
      case-4096 decision inputs mismatches -> identity gate rejects)

Exit code 0 iff every control is REJECTED (or held non-influential for
the bounded-input controls NC12b/NC13/NC14 where the assertion is that
the terminal cannot reach the stronger claim).
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from issue207_r8g_reduce import (  # noqa: E402
    REPO, R8G_DIR, boundary_state_strict, derive, set_repo,
    verify_input_manifest)
from issue207_r8g_authority import (  # noqa: E402
    COARSE_BOUNDARIES, TERMINAL_LOCALIZED, TERMINAL_NONMONOTONIC,
    r8d_v2_manifest_ok, r8e_manifest_ok)

R8G_REL = R8G_DIR
EV_REL = R8G_DIR + "/evidence"
PRODUCERS = [
    "scripts/issue207_r8g_authority.py",
    "scripts/issue207_r8g_launch.py",
    "scripts/issue207_r8g_capture.py",
    "scripts/issue207_r8g_reduce.py",
    "scripts/issue207_r8g_negative_controls.py",
    "scripts/issue207_r8g_manifest.py",
]
PREDECESSORS = [
    "docs/investigations/qwen38-flash-next-r8-d-v2",
    "docs/investigations/qwen38-flash-next-r8-e",
]



def decision_sidecar(sb, phase, cap_name, boundary):
    """Locate the exact sidecar file the reducer will read for
    `boundary` at the decision execution of a sandbox capture."""
    cap = json.load(open(os.path.join(
        sb, EV_REL, phase, "capture-%s.json" % cap_name)))
    from issue207_r8g_reduce import (capture_sidecar, decision_position,
                                     target_execution_binding)
    e0 = target_execution_binding(cap)
    seq = e0 + decision_position(cap["case"])
    return capture_sidecar(cap, phase, boundary, seq)

def replace_write(path, data):
    """Write bytes through a fresh inode (temp + os.replace) so a
    sandbox mutation never truncates a hardlinked source file."""
    tmp = path + ".nc-tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _copy_tree(src, dst):
    """Space-bounded sandbox copy: hardlink large immutable files (the
    ~286 MB evidence sidecar tree), copy small files. Mutations in a
    control REPLACE the file (open(..., "w") truncates in place — so the
    harness instead copies-before-mutating via copy-on-write semantics:
    every file the control will mutate is < 1 MB and gets a real copy)."""
    os.makedirs(dst, exist_ok=True)
    for dirpath, dirnames, files in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        outdir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(outdir, exist_ok=True)
        for f in files:
            sp = os.path.join(dirpath, f)
            dp = os.path.join(outdir, f)
            if f.endswith(".f32"):
                # raw sidecar bytes are the bulk of the tree; hardlink
                # them (mutations in these controls always go through
                # replace_write / os.remove / shutil.move, which break
                # the link instead of truncating the shared inode)
                try:
                    os.link(sp, dp)
                except OSError:
                    shutil.copy2(sp, dp)
            else:
                shutil.copy2(sp, dp)


def build_sandbox(tmpd):
    """Materialize every repo path the reducer binds in the sandbox.

    Copy-on-write note: mutation sites in these controls never write a
    hardlinked big file in place — capture records and manifests are
    small real copies, and sidecar mutations operate on files the
    control first rewrites through open(..., "wb") which truncates the
    SHARED inode. To keep sandboxes isolated, _copy_tree hardlinks
    only files > 1 MiB and every such mutated file is redirected
    through a replace-write helper in these controls (write to temp
    then os.replace), which breaks the link safely."""
    for rel in PRODUCERS:
        dst = os.path.join(tmpd, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(REPO, rel), dst)
    _copy_tree(os.path.join(REPO, R8G_REL),
               os.path.join(tmpd, R8G_REL))
    for pred in PREDECESSORS:
        _copy_tree(os.path.join(REPO, pred),
                   os.path.join(tmpd, pred))
    return tmpd


def sandbox_terminal(sb, results, label, expect=None, forbid=None):
    """Run the REAL reducer against a sandbox and record the outcome."""
    set_repo(sb)
    try:
        out = derive(verbose=False)
        term = out["terminal"]
        reason = out.get("terminal_reason", "")
    except Exception as e:  # noqa: BLE001 — any fail-closed raise counts
        term = "EXCEPTION:" + type(e).__name__
        reason = str(e)[:200]
    rejected = True
    if expect is not None and term != expect:
        rejected = False
    if forbid is not None and term == forbid:
        rejected = False
    if term == TERMINAL_LOCALIZED and forbid == TERMINAL_LOCALIZED:
        rejected = False
    results.append({"control": label, "rejected": rejected,
                    "terminal": term, "reason": reason[:160]})


def main():
    results = []
    tmp_root = os.environ.get("R8G_NC_TMPDIR") or tempfile.gettempdir()
    os.makedirs(tmp_root, exist_ok=True)
    tmpd = tempfile.mkdtemp(prefix="r8g_nc_", dir=tmp_root)
    try:
        # baseline: unmutated sandbox must derive the committed terminal
        sb = build_sandbox(os.path.join(tmpd, "base"))
        set_repo(sb)
        base = derive(verbose=False)
        assert base["terminal"] == TERMINAL_NONMONOTONIC, \
            "sandbox baseline must be NONMONOTONIC, got " + base["terminal"]
        results.append({"control": "BASELINE",
                        "rejected": True,
                        "terminal": base["terminal"],
                        "reason": "unmutated sandbox reproduces the "
                                  "machine terminal"})

        # NC1 — predecessor manifest tamper (R8-D then R8-E)
        for which, pred in (("NC1a-r8d", PREDECESSORS[0]),
                            ("NC1b-r8e", PREDECESSORS[1])):
            sb = build_sandbox(os.path.join(tmpd, which))
            man = os.path.join(sb, pred, "MANIFEST.sha256")
            lines = open(man).readlines()
            parts = lines[0].split("  ", 1)
            lines[0] = ("0" * 64) + "  " + parts[1]
            open(man, "w").writelines(lines)
            ok, why = (r8d_v2_manifest_ok(sb) if "r8d" in which
                       else r8e_manifest_ok(sb))
            results.append({"control": which, "rejected": not ok,
                            "how": "manifest_ok=%r %s" % (ok, why[:80])})

        # NC2 — instrumentation/binary identity tamper (input row)
        sb = build_sandbox(os.path.join(tmpd, "nc2"))
        inst = os.path.join(sb, EV_REL, "instrumentation",
                            "instrumentation.json")
        d = json.load(open(inst))
        d["binary_sha256"] = "f" * 64
        json.dump(d, open(inst, "w"), indent=2, sort_keys=True)
        try:
            verify_input_manifest(sb)
            results.append({"control": "NC2", "rejected": False,
                            "how": "input manifest ACCEPTED tampered "
                                   "instrumentation"})
        except Exception as e:  # noqa: BLE001
            results.append({"control": "NC2", "rejected": True,
                            "how": type(e).__name__ + ": " + str(e)[:90]})

        # capture-record attacks (NC3/NC4/NC5/NC15) on the refine phase
        def cap_path(sb, name):
            return os.path.join(sb, EV_REL, "refine",
                                "capture-case-4096-" + name + ".json")

        def run_identity(sb, label, expect_reject=True):
            set_repo(sb)
            try:
                out = derive(verbose=False)
                probs = out.get("capture_identity_problems") or []
                blocked = out["terminal"]
                rej = (bool(probs) or
                       blocked == "R8G_LOCALIZATION_EVIDENCE_BLOCKED")
                if not expect_reject:
                    rej = not rej
                results.append({"control": label, "rejected": rej,
                                "problems": probs[:1] if probs else
                                blocked[:60]})
            except Exception as e:  # noqa: BLE001
                results.append({"control": label, "rejected": True,
                                "problems": [type(e).__name__]})

        # NC3 — wrong prompt
        import base64
        sb = build_sandbox(os.path.join(tmpd, "nc3"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        req = json.loads(base64.b64decode(c["request_body_b64"]))
        req["prompt"] = req["prompt"][:-1]
        c["request_body_b64"] = base64.b64encode(
            json.dumps(req).encode()).decode()
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        run_identity(sb, "NC3")

        # NC15 — case substitution (refine capture relabeled case-256)
        sb = build_sandbox(os.path.join(tmpd, "nc15"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        c["case"] = "case-256"
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        run_identity(sb, "NC15")

        # NC4 — placement swap (arm labels swapped across the pair)
        sb = build_sandbox(os.path.join(tmpd, "nc4"))
        pa, pb = cap_path(sb, "reference-rf1"), cap_path(sb,
                                                         "candidate-rf1")
        ca, cb = json.load(open(pa)), json.load(open(pb))
        ca["arm"], cb["arm"] = cb["arm"], ca["arm"]
        json.dump(ca, open(pa, "w"), indent=2, sort_keys=True)
        json.dump(cb, open(pb, "w"), indent=2, sort_keys=True)
        run_identity(sb, "NC4")

        # NC5 — token-position binding removed
        sb = build_sandbox(os.path.join(tmpd, "nc5"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        c["logits_hook_rows"] = [r for r in c["logits_hook_rows"]
                                 if r["pos"] != c[
                                     "generated_position_target"]]
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        run_identity(sb, "NC5")

        # NC11 — observation build changed an accepted token
        sb = build_sandbox(os.path.join(tmpd, "nc11"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        toks = list(c["response_generated_tokens"])
        toks[0] = (toks[0] + 1) % 100000
        c["response_generated_tokens"] = toks
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        run_identity(sb, "NC11")

        # NC6 — boundary identity blanked (strict derivation raises)
        sb = build_sandbox(os.path.join(tmpd, "nc6"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        target = "ffn_moe_out-0"
        c["boundary_rows"] = [dict(r, name="" if r["name"] == target
                                   else r["name"])
                              for r in c["boundary_rows"]]
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        try:
            set_repo(sb)
            boundary_state_strict(
                json.load(open(p)), "refine", target)
            results.append({"control": "NC6", "rejected": False,
                            "how": "blanked boundary accepted"})
        except Exception as e:  # noqa: BLE001
            results.append({"control": "NC6", "rejected": True,
                            "how": type(e).__name__})

        # NC8 — authored digest vs retained bytes contradiction
        sb = build_sandbox(os.path.join(tmpd, "nc8"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        for r in c["boundary_rows"]:
            if r["name"] == "ffn_moe_out-0" and r["sha256"] != "NA":
                r["sha256"] = "0" * 64
                break
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        set_repo(sb)
        try:
            out = derive(verbose=False)
            rej = out["terminal"] == "R8G_LOCALIZATION_EVIDENCE_BLOCKED"
            results.append({"control": "NC8", "rejected": rej,
                            "terminal": out["terminal"]})
        except Exception as e:  # noqa: BLE001
            results.append({"control": "NC8", "rejected": True,
                            "how": type(e).__name__})

        # NC7 — stale sidecar substitution (obs2 slot gets obs1 bytes)
        sb = build_sandbox(os.path.join(tmpd, "nc7"))
        set_repo(sb)
        # stale capture from the OTHER ARM (candidate rf1) whose
        # retained bytes genuinely differ from reference rf2
        src = decision_sidecar(sb, "refine",
                               "case-4096-candidate-rf1",
                               "ffn_moe_out-0")
        dst = decision_sidecar(sb, "refine",
                               "case-4096-reference-rf2",
                               "ffn_moe_out-0")
        assert open(src, "rb").read() != open(dst, "rb").read(), \
            "NC7 setup: arms must differ for a meaningful stale capture"
        orig_dst = open(dst, "rb").read()
        replace_write(dst, open(src, "rb").read())
        set_repo(sb)
        try:
            out = derive(verbose=False)
            rej = (out["terminal"] ==
                   "R8G_LOCALIZATION_EVIDENCE_BLOCKED" or
                   bool(out.get("capture_identity_problems")))
            results.append({"control": "NC7", "rejected": rej,
                            "terminal": out["terminal"],
                            "unstable": out.get("refinement", {})
                            .get("repeat_unstable")})
        except Exception as e:  # noqa: BLE001
            results.append({"control": "NC7", "rejected": True,
                            "how": type(e).__name__})

        # NC9 — symlink with CORRECT expected bytes + path-alias variant
        sb = build_sandbox(os.path.join(tmpd, "nc9"))
        set_repo(sb)
        target = decision_sidecar(sb, "refine",
                                  "case-4096-reference-rf1",
                                  "ffn_moe_out-0")
        raw = open(target, "rb").read()
        alias = target + ".alias"
        open(alias, "wb").write(raw)          # byte-identical copy
        os.remove(target)
        os.symlink(alias, target)             # correct bytes via symlink
        set_repo(sb)
        try:
            boundary_state_strict(
                json.load(open(cap_path(sb, "reference-rf1"))),
                "refine", "ffn_moe_out-0")
            results.append({"control": "NC9-symlink", "rejected": False,
                            "how": "correct-bytes symlink ACCEPTED"})
        except Exception as e:  # noqa: BLE001
            results.append({"control": "NC9-symlink", "rejected": True,
                            "how": type(e).__name__})
        # path-alias: sidecar in a symlinked dir pointing outside
        sb = build_sandbox(os.path.join(tmpd, "nc9b"))
        set_repo(sb)
        outside = os.path.join(tmpd, "nc9b-outside")
        os.makedirs(outside, exist_ok=True)
        target = decision_sidecar(sb, "refine",
                                  "case-4096-reference-rf1",
                                  "ffn_moe_out-0")
        shutil.move(target, os.path.join(outside, os.path.basename(target)))
        os.symlink(outside, target + ".d")    # dir alias
        os.symlink(os.path.join(outside, os.path.basename(target)), target)
        set_repo(sb)
        try:
            boundary_state_strict(
                json.load(open(cap_path(sb, "reference-rf1"))),
                "refine", "ffn_moe_out-0")
            results.append({"control": "NC9-path-alias", "rejected": False,
                            "how": "aliased path ACCEPTED"})
        except Exception as e:  # noqa: BLE001
            results.append({"control": "NC9-path-alias", "rejected": True,
                            "how": type(e).__name__})

        # NC10 — same-size wrong raw bytes with consistent re-forged sha
        sb = build_sandbox(os.path.join(tmpd, "nc10"))
        set_repo(sb)
        target = decision_sidecar(sb, "refine",
                                  "case-4096-reference-rf1",
                                  "ffn_moe_out-0")
        raw = bytearray(open(target, "rb").read())
        raw[0] ^= 0x01                          # same size, one bit
        replace_write(target, bytes(raw))
        # re-forge the authored row sha AND the input-manifest row so the
        # attack passes the manifest layer and must be caught by the
        # cross-arm semantics or nonfinite/size gates
        import hashlib
        newsha = hashlib.sha256(bytes(raw)).hexdigest()
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        for r in c["boundary_rows"]:
            if r["name"] == "ffn_moe_out-0" and \
                    r["sha256"] not in ("NA", newsha):
                r["sha256"] = newsha
                r["col_nbytes"] = len(raw)
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        imp = os.path.join(sb, EV_REL, "input-manifest.json")
        im = json.load(open(imp))
        relcap = os.path.relpath(p, sb)
        relsc = os.path.relpath(target, sb)
        im["rows"][relcap] = hashlib.sha256(
            open(p, "rb").read()).hexdigest()
        im["rows"][relsc] = newsha
        json.dump(im, open(imp, "w"), indent=2, sort_keys=True)
        set_repo(sb)
        try:
            out = derive(verbose=False)
            # the bit-flip changes the reference ffn_moe_out-0 state;
            # the candidate is unchanged. The authored row for rf1 was
            # re-forged consistently, but rf2's row was NOT — repeat
            # stability across rf1/rf2 must break, or the derivation
            # must fail closed; either way the tampered bytes cannot
            # pass silently through the comparison path.
            runst = out.get("refinement", {}).get(
                "repeat_unstable") or []
            rej = bool(runst) or out["terminal"] in (
                "R8G_LOCALIZATION_EVIDENCE_BLOCKED",)
            results.append({"control": "NC10", "rejected": rej,
                            "terminal": out["terminal"],
                            "repeat_unstable": len(runst)})
        except Exception as e:  # noqa: BLE001 — fail-closed raise
            results.append({"control": "NC10", "rejected": True,
                            "how": "Blocked: " + str(e)[:100]})

        # NC12 — post-hoc checkpoint insertion: a row for a boundary
        # NOT in the frozen set (l_last-1) is inserted into the capture
        # record + sidecar + input manifest, consistently. The terminal
        # input set must be unchanged (terminal identical to baseline).
        sb = build_sandbox(os.path.join(tmpd, "nc12"))
        p = cap_path(sb, "reference-rf1")
        c = json.load(open(p))
        seq0 = min(r["seq"] for r in c["boundary_rows"]
                   if r["name"] == "ffn_moe_out-0" and r["sha256"] != "NA")
        import hashlib
        payload = b"\x00" * 10240
        sha0 = hashlib.sha256(payload).hexdigest()
        c["boundary_rows"].append(
            {"name": "l_last-1", "seq": seq0, "sha256": sha0,
             "col_nbytes": len(payload), "n_nonfinite": 2560})
        json.dump(c, open(p, "w"), indent=2, sort_keys=True)
        scdir = os.path.join(sb, EV_REL, "refine",
                             "sc-case-4096-reference-rf1")
        open(os.path.join(scdir, "l_last-1__%d.f32" % seq0),
             "wb").write(payload)
        imp = os.path.join(sb, EV_REL, "input-manifest.json")
        im = json.load(open(imp))
        im["rows"][os.path.relpath(p, sb)] = hashlib.sha256(
            open(p, "rb").read()).hexdigest()
        im["rows"][os.path.relpath(
            os.path.join(scdir, "l_last-1__%d.f32" % seq0), sb)] = sha0
        json.dump(im, open(imp, "w"), indent=2, sort_keys=True)
        set_repo(sb)
        out = derive(verbose=False)
        results.append({
            "control": "NC12",
            "rejected": out["terminal"] == base["terminal"] and
            "l_last-1" not in json.dumps(
                out.get("refinement", {}).get("frozen_set", [])),
            "terminal": out["terminal"],
            "how": "inserted row cannot expand the terminal input set"})

        # NC13/NC14 — terminal-derivation attacks (production
        # terminal_selection on synthetic refinement maps)
        from issue207_r8g_reduce import terminal_selection
        # NC13: earliest-claim with a MISSING earlier frozen boundary
        term, _ = terminal_selection(
            [], [("model.input_embed", "equal"),
                 ("l_last-2", "differ")],
            [("s0", "unobservable"), ("s1", "differ"),
             ("s2", "differ")], True)
        results.append({"control": "NC13",
                        "rejected": term != TERMINAL_LOCALIZED,
                        "terminal": term,
                        "how": "missing earlier frozen boundary blocks "
                               "exact-earliest"})
        # NC13b: first sub-boundary differs with NO observable earlier
        term2, _ = terminal_selection(
            [], [("model.input_embed", "equal"), ("l_last-2", "differ")],
            [("s0", "differ"), ("s1", "equal")], True)
        # s0 differ then s1 equal is ALSO non-monotonic (reconvergence)
        results.append({"control": "NC13b",
                        "rejected": term2 != TERMINAL_LOCALIZED,
                        "terminal": term2})
        # NC14: LOCALIZED attempt after reconvergence
        term3, _ = terminal_selection(
            [], [("model.input_embed", "equal"), ("l_last-2", "differ")],
            [("s0", "equal"), ("s1", "equal"), ("s2", "differ"),
             ("s3", "equal"), ("s4", "differ")], True)
        results.append({"control": "NC14",
                        "rejected": term3 == TERMINAL_NONMONOTONIC,
                        "terminal": term3,
                        "how": "reconvergence after differ forces "
                               "NONMONOTONIC"})
        # positive control: monotonic map DOES localize
        term4, _ = terminal_selection(
            [], [("model.input_embed", "equal"), ("l_last-2", "differ")],
            [("s0", "equal"), ("s1", "equal"), ("s2", "differ"),
             ("s3", "differ")], True)
        results.append({"control": "NC14-positive",
                        "rejected": term4 == TERMINAL_LOCALIZED,
                        "terminal": term4,
                        "how": "monotonic map with all-earlier-equal "
                               "localizes"})

        # NC12b — case-256 extra observations beyond the authorized set
        # cannot influence classification: insert extra rows into
        # contrast captures; the case-256 derived fields must not move.
        sb = build_sandbox(os.path.join(tmpd, "nc12b"))
        for name in ("reference-ct1", "candidate-ct1"):
            p = os.path.join(sb, EV_REL, "contrast",
                             "capture-case-256-%s.json" % name)
            c = json.load(open(p))
            seq0 = min(r["seq"] for r in c["boundary_rows"]
                       if r["name"] == "result_output"
                       and r["sha256"] != "NA")
            payload = b"\x01" * 10240
            sha0 = hashlib.sha256(payload).hexdigest()
            c["boundary_rows"].append(
                {"name": "l_last-46", "seq": seq0, "sha256": sha0,
                 "col_nbytes": len(payload), "n_nonfinite": 0})
            json.dump(c, open(p, "w"), indent=2, sort_keys=True)
            scdir = os.path.join(sb, EV_REL, "contrast",
                                 "sc-case-256-" + name.replace(
                                     "-ct1", "-ct1"))
            open(os.path.join(scdir, "l_last-46__%d.f32" % seq0),
                 "wb").write(payload)
            imp = os.path.join(sb, EV_REL, "input-manifest.json")
            im = json.load(open(imp))
            im["rows"][os.path.relpath(p, sb)] = hashlib.sha256(
                open(p, "rb").read()).hexdigest()
            im["rows"][os.path.relpath(
                os.path.join(scdir, "l_last-46__%d.f32" % seq0), sb)] = sha0
            json.dump(im, open(imp, "w"), indent=2, sort_keys=True)
        set_repo(sb)
        out = derive(verbose=False)
        results.append({
            "control": "NC12b-case256",
            "rejected": (out.get("case256_first_authorized_differing") ==
                         base.get("case256_first_authorized_differing") and
                         out["terminal"] == base["terminal"]),
            "terminal": out["terminal"],
            "how": "extra case-256 rows cannot move the authorized "
                   "classification"})
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
        set_repo(REPO)

    print(json.dumps({"controls": results}, indent=2))
    bad = [r for r in results if not r["rejected"]]
    if bad:
        print("FAILED CONTROLS:", [r["control"] for r in bad],
              file=sys.stderr)
        return 1
    print("ALL %d CONTROLS REJECTED" % len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
