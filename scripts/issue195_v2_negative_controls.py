#!/usr/bin/env python3
"""Issue #195 R8-D v2: TRUE differential negative controls.

v1 defect corrected: every mutation control now
  (1) runs an unmodified BASELINE reduction first (or a purpose-built
      synthetic green baseline where the real campaign is red);
  (2) asserts the target check(s) have the expected pre-mutation state;
  (3) applies exactly ONE mutation;
  (4) requires the intended check/terminal to move in the intended
      direction;
  (5) rejects a control whose named failure already existed at baseline
      (unless a synthetic green baseline is used).

Controls run the REAL v2 reducer derive() with
I195_AREA_OVERRIDE/I195_REPO_OVERRIDE sandboxing.

Usage: issue195_v2_negative_controls.py <out-json>
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from issue195_v2_authority import CAMPAIGN_ID, FIXTURE_CASES  # noqa: E402
from issue195_v2_authority import (  # noqa: E402
    TERMINAL_BLOCKED, TERMINAL_FAIL, TERMINAL_PASS)

V2_AREA_REL = "docs/investigations/qwen38-flash-next-r8-d-v2"
V1_AREA_REL = "docs/investigations/qwen38-flash-next-r8-d"
RESULTS = []


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def run_reducer(area):
    """Run the real v2 reducer derive() against a sandboxed area/repo.
    Returns (terminal, checks, err)."""
    env = dict(os.environ)
    env["I195_AREA_OVERRIDE"] = os.path.join(area, V2_AREA_REL)
    env["I195_REPO_OVERRIDE"] = area
    # git history checks (prospective freeze) always use the real repo:
    # the sandbox has no .git, and the refreeze ancestry proof must
    # exercise real history, not sandbox files.
    env["I195_GIT_OVERRIDE"] = REPO
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys, json; sys.path.insert(0, %r); "
         "import issue195_v2_terminal_reduction as R; "
         "r = R.derive(); "
         "print(json.dumps({'terminal': r['terminal'], 'checks': r['checks']}))"
         % os.path.join(REPO, "scripts")],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return None, None, r.stderr[-400:]
    d = json.loads(r.stdout.strip().splitlines()[-1])
    return d["terminal"], d["checks"], None


def sandbox():
    tmp = tempfile.mkdtemp(prefix="i195v2-nc-")
    shutil.copytree(os.path.join(REPO, V2_AREA_REL),
                    os.path.join(tmp, V2_AREA_REL))
    shutil.copytree(os.path.join(REPO, V1_AREA_REL),
                    os.path.join(tmp, V1_AREA_REL))
    for sub in ("qwen38-flash-next-r8-a", "qwen38-flash-next-r8-b",
                "qwen38-flash-next-r8-c"):
        shutil.copytree(os.path.join(REPO, "docs/investigations", sub),
                        os.path.join(tmp, "docs/investigations", sub))
    # predecessor manifests (and the superseded v1 manifest) may pin repo
    # files outside the investigation areas (scripts/, tests/); copy every
    # referenced path so predecessor and v1 manifest verification exercise
    # real bytes in the sandbox
    for area in ("qwen38-flash-next-r8-a", "qwen38-flash-next-r8-b",
                 "qwen38-flash-next-r8-c", "qwen38-flash-next-r8-d"):
        m = os.path.join(tmp, "docs/investigations", area, "MANIFEST.sha256")
        for line in open(m):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            _h, rel = line.split(None, 1)
            rel = rel.lstrip("*")
            src = os.path.join(REPO, rel)
            dst = os.path.join(tmp, rel)
            if os.path.isfile(src) and not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
    return tmp


def ev(area, *parts):
    return os.path.join(area, V2_AREA_REL, "evidence", *parts)


def edit_json(path, fn):
    with open(path) as fh:
        d = json.load(fh)
    fn(d)
    with open(path, "w") as fh:
        json.dump(d, fh, indent=2, sort_keys=True)
        fh.write("\n")


def rewrite_response_tokens(rec, new_tokens, stop_type=None, word=None):
    """Re-encode a run record's response so the parsed fields match the
    retained bytes (keeps records internally integral while changing
    model output)."""
    resp = json.loads(base64.b64decode(rec["response_bytes_b64"]))
    resp["tokens"] = new_tokens
    if stop_type is not None:
        resp["stop_type"] = stop_type
    if word is not None:
        resp["stopping_word"] = word
    rb = json.dumps(resp, sort_keys=True, separators=(",", ":")).encode()
    rec["response_bytes_b64"] = base64.b64encode(rb).decode()
    rec["response_sha256"] = sha_b(rb)
    rec["parsed_from_retained_bytes"]["generated_tokens"] = new_tokens
    if stop_type is not None:
        rec["parsed_from_retained_bytes"]["stop_type"] = stop_type
    if word is not None:
        rec["parsed_from_retained_bytes"]["stopping_word"] = word


def synth_green_campaign():
    """Purpose-built synthetic baseline: identical to the real evidence
    except candidate outputs equal the frozen reference (a PASS-shaped
    campaign) — used by controls whose target check is red in the real
    FAIL campaign."""
    base = sandbox()
    fr = json.load(open(ev(base, "reference", "frozen-reference.json")))
    for i in (1, 2, 3):
        p = ev(base, "candidate", f"cand-run-{i}.json")
        d = json.load(open(p))
        for r in d["results"]:
            fc = fr["cases"][r["case_id"]]
            rewrite_response_tokens(r, fc["generated_tokens"],
                                    fc["stop_type"], fc["stopping_word"])
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
            fh.write("\n")
    for c in ("case-256", "case-4096"):
        p = ev(base, "candidate", f"cand-restart-{c}.json")
        d = json.load(open(p))
        for r in d["results"]:
            fc = fr["cases"][r["case_id"]]
            rewrite_response_tokens(r, fc["generated_tokens"],
                                    fc["stop_type"], fc["stopping_word"])
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return base


def control(name, description, check_names, direction, mutate,
            expect_terminal=None, baseline=sandbox,
            baseline_must_be_green=False):
    """Run one differential control.

    baseline_must_be_green marks controls whose baseline is a
    purpose-built synthetic green campaign: before any mutation is
    applied, the unmodified baseline reduction MUST derive
    TERMINAL_PASS with every check green. If that precondition is
    false the control is INVALID (and the suite fails) — a synthetic
    "green" baseline that is not actually reducer-PASS must never be
    used before any mutation is applied. The precondition is enforced
    automatically for every control whose baseline is
    synth_green_campaign.
    """
    base = baseline()
    if baseline is synth_green_campaign:
        baseline_must_be_green = True
    bt, bc, err = run_reducer(base)
    if bt is None:
        RESULTS.append({"control": name, "valid": False,
                        "reason": "baseline reducer error: " + str(err)})
        shutil.rmtree(base, ignore_errors=True)
        return
    if baseline_must_be_green:
        not_green = ([] if bt == TERMINAL_PASS else ["terminal"]) + \
            sorted(k for k, v in (bc or {}).items() if v is not True)
        if not_green:
            RESULTS.append({
                "control": name, "valid": False,
                "reason": "synthetic green baseline precondition false "
                "(not reducer-PASS): " + ", ".join(not_green),
                "baseline_terminal": bt,
                "baseline_checks": {c: (bc or {}).get(c)
                                    for c in check_names}})
            shutil.rmtree(base, ignore_errors=True)
            return
    pre_ok = True
    if direction == "flip_false":
        for c in check_names:
            if bc.get(c) is not True:
                RESULTS.append({
                    "control": name, "valid": False,
                    "reason": f"baseline check {c} already false — "
                    "rejected by the v2 differential rule",
                    "baseline_terminal": bt,
                    "baseline_checks": {c: bc.get(c) for c in check_names}})
                pre_ok = False
    if not pre_ok:
        shutil.rmtree(base, ignore_errors=True)
        return
    mutate(base)
    mt, mc, err = run_reducer(base)
    if mt is None:
        RESULTS.append({"control": name, "valid": False,
                        "reason": "mutated reducer error: " + str(err)})
        shutil.rmtree(base, ignore_errors=True)
        return
    if direction == "flip_false":
        moved = all(mc.get(c) is False for c in check_names)
    else:  # stay_true
        moved = all(mc.get(c) is True for c in check_names)
    term_ok = expect_terminal is None or mt == expect_terminal
    valid = moved and term_ok
    RESULTS.append({
        "control": name, "description": description, "valid": bool(valid),
        "differential": True,
        "baseline_terminal": bt, "mutated_terminal": mt,
        "baseline_checks": {c: bc.get(c) for c in check_names},
        "mutated_checks": {c: mc.get(c) for c in check_names},
        **({"expected_terminal": expect_terminal} if expect_terminal else {}),
    })
    shutil.rmtree(base, ignore_errors=True)


def main():
    # NC-1 wrong accepted predecessor identity
    def nc1(a):
        p = os.path.join(a, "docs/investigations/qwen38-flash-next-r8-c",
                         "MANIFEST.sha256")
        t = open(p).read()
        lines = t.splitlines(True)
        lines[0] = "0" * 64 + "  " + lines[0].split("  ", 1)[1]
        open(p, "w").write("".join(lines))
    control("NC-1", "wrong accepted predecessor identity (R8-C manifest)",
            ["predecessor_bundles_byte_preserved"], "flip_false", nc1)

    # NC-2 changed GGUF member hash
    def nc2(a):
        edit_json(ev(a, "split-identity", "split-rehash.json"),
                  lambda d: d["members"][0].update(sha256="0" * 64))
    control("NC-2", "changed GGUF member hash", ["split_all_members_exact"],
            "flip_false", nc2)

    # NC-3 changed runtime/binary hash
    def nc3(a):
        p = ev(a, "host-inventory", "inferswarm01-inventory-raw.txt")
        open(p, "w").write(open(p).read().replace(
            BINARY_SHA256_SENTINEL[0], "f" * 64))
    control("NC-3", "changed llama-server binary hash (inferswarm01)",
            ["binaries_pinned_all_hosts"], "flip_false", nc3)

    # NC-4 stale/wrong GPU UUID/BDF/topology
    def nc4(a):
        p = ev(a, "host-inventory", "inferswarm03-inventory-raw.txt")
        open(p, "w").write(open(p).read().replace(
            "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176", "GPU-deadbeef"))
    control("NC-4", "stale/wrong GPU UUID in inventory",
            ["topology_uuid_bdf_match"], "flip_false", nc4)

    # NC-5 unresolved legacy greedy falsely accepted
    def nc5(a):
        edit_json(ev(a, "sampler-contract", "sampler-probe-ref.json"),
                  lambda d: d["variants"]["legacy"].update(
                      classification="TRUE_GREEDY_PROVEN"))
    control("NC-5", "legacy greedy variant falsely accepted as canonical",
            ["legacy_greedy_negative_control_noncanonical"], "flip_false", nc5)

    # NC-6 top_k>1 falsely accepted as true greedy
    def nc6(a):
        edit_json(ev(a, "sampler-contract", "sampler-probe-ref.json"),
                  lambda d: d["variants"]["wide"].update(
                      classification="TRUE_GREEDY_PROVEN"))
    control("NC-6", "top_k>1 falsely classified true-greedy",
            ["topk_gt1_negative_control_not_true_greedy"], "flip_false", nc6)

    # NC-7 missing sampler-chain evidence => BLOCKED (pre-candidate)
    def nc7(a):
        edit_json(ev(a, "sampler-contract", "sampler-probe-ref.json"),
                  lambda d: d["variants"]["canonical"].update(
                      classification="BLOCKED_NO_CHAIN_EVIDENCE"))
    control("NC-7", "missing sampler-chain evidence on reference probe",
            ["sampler_contract_proven_reference"], "flip_false", nc7,
            expect_terminal=TERMINAL_BLOCKED)

    # NC-8 request mutation after reference freeze
    def nc8(a):
        # mutate an actual request body byte-stream: change top_k in the
        # retained request bytes (re-serialized + digest fixed) of one
        # candidate case — exactly the "request mutation after freeze"
        # class; detected by identity check (contract drift).
        p = ev(a, "candidate", "cand-run-1.json")
        d = json.load(open(p))
        r = d["results"][0]
        body = json.loads(base64.b64decode(r["request_bytes_b64"]))
        body["top_k"] = 4
        rb = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        r["request_bytes_b64"] = base64.b64encode(rb).decode()
        r["request_sha256"] = sha_b(rb)
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
    control("NC-8", "request mutation after reference freeze (top_k->4)",
            ["candidate_identity_exact"], "flip_false", nc8)

    # NC-9 wrong prompt/token IDs actually sent
    def nc9(a):
        p = ev(a, "candidate", "cand-run-1.json")
        d = json.load(open(p))
        r = d["results"][0]
        ids = list(r["prompt_token_ids"])
        ids[5] = 999999
        body = json.loads(base64.b64decode(r["request_bytes_b64"]))
        body["prompt"] = ids
        rb = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        r["request_bytes_b64"] = base64.b64encode(rb).decode()
        r["request_sha256"] = sha_b(rb)
        r["prompt_token_ids"] = ids
        r["prompt_token_ids_sha256"] = sha_b(
            json.dumps(ids, separators=(",", ":")).encode())
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
    control("NC-9", "wrong prompt token IDs actually sent",
            ["candidate_identity_exact"], "flip_false", nc9)

    # NC-10 candidate topology differing from frozen authority
    def nc10(a):
        open(ev(a, "candidate", "launch-candidate.sh"), "w").write(
            "#!/usr/bin/env bash\nexec llama-server --rpc 10.0.0.219:50052\n")
    control("NC-10", "candidate topology differs from frozen authority",
            ["candidate_topology_matches_frozen_authority"], "flip_false",
            nc10, baseline=synth_green_campaign)

    # NC-11 stale process/session contamination after restart
    def nc11(a):
        edit_json(ev(a, "candidate", "restart-pid-proof.json"),
                  lambda d: d["terminated_pids"][0].update(
                      confirmed_gone_before_relaunch=False))
    control("NC-11", "stale process contamination after restart (PID alive)",
            ["restart_pids_proven_gone"], "flip_false", nc11)

    # NC-12 output mismatch suppressed/rewritten: post-hoc frozen-ref
    # token mutation must flip frozen_reference_integrity false
    def nc12(a):
        edit_json(ev(a, "reference", "frozen-reference.json"),
                  lambda d: d["cases"]["case-1024"]["generated_tokens"].__setitem__(
                      -1, d["cases"]["case-1024"]["generated_tokens"][-1] + 1))
    control("NC-12", "post-hoc frozen-reference token mutation detected",
            ["frozen_reference_integrity"], "flip_false", nc12,
            baseline=synth_green_campaign)

    # NC-13 authored PASS contradicting retained raw output is ignored
    def nc13(a):
        p = os.path.join(a, V2_AREA_REL, "terminal-reduction.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump({"terminal": TERMINAL_PASS, "authored": True}, fh)
    control("NC-13", "authored PASS contradicting retained raw output",
            ["all_cases_token_exact"], "stay_true", nc13,
            baseline=synth_green_campaign)

    # NC-14 n_probs in a correctness-bearing request must be rejected
    def nc14(a):
        p = ev(a, "candidate", "cand-run-1.json")
        d = json.load(open(p))
        r = d["results"][0]
        body = json.loads(base64.b64decode(r["request_bytes_b64"]))
        body["n_probs"] = 5
        rb = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        r["request_bytes_b64"] = base64.b64encode(rb).decode()
        r["request_sha256"] = sha_b(rb)
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
    control("NC-14", "n_probs present in correctness-bearing request",
            ["candidate_identity_exact"], "flip_false", nc14)

    # NC-15 accepted R8-B/R8-C evidence mutation
    def nc15(a):
        p = os.path.join(a, "docs/investigations/qwen38-flash-next-r8-b",
                         "MANIFEST.sha256")
        lines = open(p).read().splitlines(True)
        lines[2] = "0" * 64 + "  " + lines[2].split("  ", 1)[1]
        open(p, "w").write("".join(lines))
    control("NC-15", "accepted R8-B evidence manifest mutation",
            ["predecessor_bundles_byte_preserved"], "flip_false", nc15)

    # NC-16 v1 evidence mutation (superseded v1 bytes must be preserved)
    def nc16b(a):
        p = os.path.join(a, V1_AREA_REL, "evidence", "candidate",
                         "cand-run-2.json")
        d = json.load(open(p))
        d["results"][0]["generated_tokens"] = [4242]
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
    control("NC-16", "actual v1 evidence byte mutation detected",
            ["v1_evidence_byte_preserved"], "flip_false", nc16b)

    # NC-17 token mismatch on an otherwise-valid campaign => FAIL (the
    # NC-10-v1-defect class): synthetic PASS baseline, one token mutated
    def nc17(a):
        p = ev(a, "candidate", "cand-run-1.json")
        d = json.load(open(p))
        r = d["results"][0]
        toks = list(r["parsed_from_retained_bytes"]["generated_tokens"])
        toks[-1] = toks[-1] + 1
        rewrite_response_tokens(r, toks)
        with open(p, "w") as fh:
            json.dump(d, fh, indent=2, sort_keys=True)
    control("NC-17", "token mismatch on valid campaign => FAIL (not BLOCKED)",
            ["all_cases_token_exact"], "flip_false", nc17,
            expect_terminal=TERMINAL_FAIL, baseline=synth_green_campaign)

    # NC-18 post-output restart failure => FAIL not BLOCKED
    def nc18(a):
        edit_json(ev(a, "candidate", "restart-pid-proof.json"),
                  lambda d: d["terminated_pids"][0].update(
                      confirmed_gone_before_relaunch=False))
    control("NC-18", "post-output restart failure => FAIL",
            ["restart_pids_proven_gone"], "flip_false", nc18,
            expect_terminal=TERMINAL_FAIL, baseline=synth_green_campaign)

    # NC-19 post-output sampler-reproof failure => FAIL
    def nc19(a):
        edit_json(ev(a, "candidate", "sampler-probe-cand-restart.json"),
                  lambda d: d["variants"]["canonical"].update(
                      classification="BLOCKED_NO_CHAIN_EVIDENCE"))
    control("NC-19", "post-output sampler reproof failure => FAIL",
            ["sampler_contract_reproven_after_restart"], "flip_false", nc19,
            expect_terminal=TERMINAL_FAIL, baseline=synth_green_campaign)

    # NC-20 post-output placement failure => FAIL
    def nc20(a):
        p = ev(a, "candidate", "cand-server.log")
        t = open(p).read()
        open(p, "w").write(t.replace("per_layer_token_embd", "PLE_REMOVED"))
    control("NC-20", "post-output placement failure => FAIL",
            ["ple_host_resident_both_arms"], "flip_false", nc20,
            expect_terminal=TERMINAL_FAIL, baseline=synth_green_campaign)

    # Structural traps (retained from v1)
    src = open(os.path.join(REPO, "scripts",
                            "issue195_v2_terminal_reduction.py")).read()
    RESULTS.append({
        "control": "NC-S1", "description": "no bare-True composer trap in "
        "reducer (structural AST/regex scan)", "valid": not re.findall(
            r"return True  # (?:always|stub)", src),
        "structural": True})
    # derive() must never read an authored verdict file
    der_src = src.split("def derive")[1].split("def main")[0] if "def derive" in src else src
    RESULTS.append({
        "control": "NC-S2", "description": "derive() never reads any "
        "authored verdict file (structural)", "valid": (
            "terminal-reduction.json" not in der_src),
        "structural": True})

    out = (sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        REPO, V2_AREA_REL, "evidence", "negative-controls",
        "negative-controls.json"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc = {
        "schema": "inferswarm.issue195.negative-controls/2",
        "campaign": CAMPAIGN_ID,
        "method": ("differential: unmodified baseline first; assert "
                   "expected pre-mutation state; exactly one mutation; "
                   "intended check/terminal must move in the intended "
                   "direction; baseline-red invariants rejected unless a "
                   "purpose-built synthetic green baseline is used"),
        "controls": RESULTS,
        "all_valid": all(c["valid"] for c in RESULTS),
    }
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"controls": len(RESULTS),
                      "all_valid": doc["all_valid"],
                      "invalid": [c["control"] for c in RESULTS
                                  if not c["valid"]]}, indent=1))
    return 0 if doc["all_valid"] else 1


BINARY_SHA256_SENTINEL = ["de3a8a545e2f5995f80ff23f60776fedc30edca67f"
                          "0e09f3bc47c845156e3411"]

if __name__ == "__main__":
    sys.exit(main())
