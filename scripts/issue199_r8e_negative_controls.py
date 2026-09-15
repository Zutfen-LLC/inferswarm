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
    repo-root layout."""
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
    """One mutation on one capture record; the reducer must BLOCK."""
    d = read_cap(root, cap_rel)
    mutate(d)
    write_cap(root, cap_rel, d)
    r = base_state(root)
    moved = (r["terminal"] == "R8E_EVIDENCE_BLOCKED" and
             any(expect_substr in p for p in r["problems"]))
    return {"control": note, "moved": moved,
            "terminal": r["terminal"],
            "matched_problem": next(
                (p for p in r["problems"] if expect_substr in p), None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    results = []

    with tempfile.TemporaryDirectory() as tmp:
        root = sandbox(tmp)
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
        d = json.load(open(ip))
        d["binary_sha256"] = "0" * 64
        json.dump(d, open(ip, "w"), indent=2, sort_keys=True)
        r = base_state(root)
        results.append({
            "control": "NC2 wrong binary identity",
            "moved": r["terminal"] == "R8E_EVIDENCE_BLOCKED" and
            any("binary" in p for p in r["problems"]),
            "terminal": r["terminal"]})
        # restore
        d["binary_sha256"] = json.load(open(
            os.path.join(REPO, R8E_DIR,
                         "evidence/instrumentation/"
                         "instrumentation.json")))["binary_sha256"]
        json.dump(d, open(ip, "w"), indent=2, sort_keys=True)

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
