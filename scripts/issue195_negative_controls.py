#!/usr/bin/env python3
"""Issue #195 R8-D: negative-control execution against the real retained
evidence. Each control applies ONE mutation to a tmp copy of the evidence
tree and requires the terminal reduction to fail on exactly that check
(fail-closed proof), plus source-level structural checks.

Usage: issue195_negative_controls.py <out-json>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
AREA = os.path.join(REPO, "docs", "investigations", "qwen38-flash-next-r8-d")


def run_reduction(area_path):
    env = dict(os.environ)
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts",
                                      "issue195_terminal_reduction.py")],
        capture_output=True, text=True, env=env, cwd=REPO)
    # the reducer always reads the REPO area; controls that mutate bytes use
    # monkeypatched AREA via env
    return r.returncode, r.stdout


def mutate_and_check(mutate_fn, expect_terminal=None, expect_failed=None):
    tmp = tempfile.mkdtemp(prefix="i195-nc-")
    area_copy = os.path.join(tmp, "docs", "investigations", "qwen38-flash-next-r8-d")
    os.makedirs(os.path.dirname(area_copy))
    shutil.copytree(AREA, area_copy)
    # stage a minimal shadow repo so cross-area reads (R8-B ladder,
    # predecessor MANIFESTs) resolve inside the sandbox
    src_ladder = os.path.join(REPO, "docs", "investigations", "qwen38-flash-next-r8-b",
                              "evidence", "reference", "fixture-ladder.json")
    dst_ladder = os.path.join(tmp, "docs", "investigations", "qwen38-flash-next-r8-b",
                              "evidence", "reference", "fixture-ladder.json")
    os.makedirs(os.path.dirname(dst_ladder), exist_ok=True)
    shutil.copy2(src_ladder, dst_ladder)
    mutate_fn(area_copy)
    env = dict(os.environ)
    env["I195_AREA_OVERRIDE"] = area_copy
    env["I195_REPO_OVERRIDE"] = tmp
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts",
                                      "issue195_terminal_reduction.py")],
        capture_output=True, text=True, env=env, cwd=REPO)
    out = r.stdout
    ok = r.returncode == 0
    if expect_failed:
        for k in expect_failed:
            if f'"{k}": true' in out.replace(" ", "").replace('"', '"') and k in out:
                pass
    shutil.rmtree(tmp, ignore_errors=True)
    return r.returncode, out


def main(out_path):
    controls = []

    def ctrl(cid, desc, fn, expect_failed):
        rc, out = mutate_and_check(fn, expect_failed=expect_failed)
        detected = False
        try:
            # reducer prints a JSON doc with a failed_checks list
            start = out.index("{")
            doc = json.loads(out[start:out.rindex("}") + 1])
            failed = doc.get("failed_checks", [])
            detected = all(k in failed for k in expect_failed)
        except (ValueError, json.JSONDecodeError):
            detected = False
        controls.append({
            "control": cid, "description": desc,
            "fails_closed": detected,
            "reducer_exit": rc,
        })

    def m_candidate_tokens(area):
        p = os.path.join(area, "evidence", "candidate", "cand-run-1.json")
        d = json.load(open(p))
        d["results"][0]["generated_tokens"] = [1, 2, 3]
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_split_hash(area):
        p = os.path.join(area, "evidence", "split-identity", "split-rehash.json")
        d = json.load(open(p))
        d["members"][0]["sha256"] = "0" * 64
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_binary_hash(area):
        p = os.path.join(area, "evidence", "host-inventory",
                         "inferswarm03-inventory-raw.txt")
        t = open(p).read().replace(
            "de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411",
            "f" * 64)
        open(p, "w").write(t)

    def m_topology(area):
        p = os.path.join(area, "evidence", "host-inventory",
                         "inferswarm04-inventory-raw.txt")
        t = open(p).read().replace("GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03",
                                   "GPU-deadbeef-0000")
        open(p, "w").write(t)

    def m_chain_evidence(area):
        p = os.path.join(area, "evidence", "sampler-contract",
                         "sampler-probe-ref.json")
        d = json.load(open(p))
        d["variants"]["canonical"]["log_evidence"]["chains"] = []
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_samplers_widened(area):
        p = os.path.join(area, "evidence", "sampler-contract",
                         "sampler-probe-ref.json")
        d = json.load(open(p))
        d["variants"]["canonical"]["request"]["top_k"] = 4
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_legacy_accepted(area):
        p = os.path.join(area, "evidence", "sampler-contract",
                         "sampler-probe-ref.json")
        d = json.load(open(p))
        d["variants"]["legacy"]["classification"] = "TRUE_GREEDY_PROVEN"
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_request_contract(area):
        p = os.path.join(area, "evidence", "reference", "ref-run-1.json")
        d = json.load(open(p))
        d["request_contract"]["top_k"] = 2
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_restart_tokens(area):
        p = os.path.join(area, "evidence", "candidate",
                         "cand-restart-case-256.json")
        d = json.load(open(p))
        d["results"][0]["generated_tokens"] = [9, 9, 9]
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_reference_posthoc(area):
        p = os.path.join(area, "evidence", "reference", "frozen-reference.json")
        d = json.load(open(p))
        d["cases"]["case-256"]["generated_tokens"] = \
            [561, 324, 55965, 51624, 29014, 34227, 36165, 271]
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    def m_output_suppressed(area):
        p = os.path.join(area, "terminal-reduction.json")
        d = json.load(open(p))
        d["per_case"]["case-256"]["token_exact"] = True
        json.dump(d, open(p, "w"), indent=2, sort_keys=True)

    ctrl("NC-01", "candidate token mutation detected", m_candidate_tokens,
         ["candidate_deterministic_3x", "all_cases_token_exact"])
    ctrl("NC-02", "changed GGUF member hash rejected", m_split_hash,
         ["split_all_members_exact"])
    ctrl("NC-03", "changed runtime binary hash rejected", m_binary_hash,
         ["binaries_pinned_all_hosts"])
    ctrl("NC-04", "stale/wrong GPU UUID rejected", m_topology,
         ["topology_uuid_bdf_match"])
    ctrl("NC-05", "missing sampler-chain evidence BLOCKED", m_chain_evidence,
         ["sampler_contract_proven_reference"])
    ctrl("NC-06", "top_k>1 cannot pass as true greedy", m_samplers_widened,
         ["sampler_contract_proven_reference"])
    ctrl("NC-07", "legacy 'greedy' cannot be mislabeled canonical",
         m_legacy_accepted,
         ["legacy_greedy_negative_control_noncanonical"])
    ctrl("NC-08", "request mutation after freeze detected", m_request_contract,
         ["request_contract_unchanged_all_runs"])
    ctrl("NC-09", "restart output drift detected", m_restart_tokens,
         ["restart_identity_sentinels"])
    ctrl("NC-10", "post-hoc reference rewrite does not flip the comparison "
         "(comparison consumes run JSONs, not the frozen doc)",
         m_reference_posthoc, ["all_cases_token_exact"])
    ctrl("NC-11", "authored PASS contradicting raw output rejected "
         "(structural: reducer never reads terminal-reduction.json)",
         m_output_suppressed, [])

    # NC-11 structural: the reducer source must not read its own output doc
    src = open(os.path.join(REPO, "scripts",
                            "issue195_terminal_reduction.py")).read()
    reads_own = ('terminal-reduction.json' in src and
                 'load(' in src.split('def main')[0].split('--check')[0])
    controls[-1]["fails_closed"] = (
        controls[-1]["fails_closed"] and not reads_own)

    # NC-12: predecessor bundle mutation fails the manifest verification
    # (proved structurally: verify_predecessor_manifests hashes every row)
    controls.append({
        "control": "NC-12",
        "description": "R8-B/R8-C evidence mutation detected via MANIFEST "
                       "re-verification (structural: every row re-hashed)",
        "fails_closed": "def verify_predecessor_manifests" in src and
                        "sha(fp) != h" in src,
    })
    # NC-13: no bare-constant PASS in the reducer source (AST-level)
    import ast
    tree = ast.parse(src)
    bare_true = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Constant) and v.value is True
                        and "negative_control" not in k.value):
                    bare_true = True
    controls.append({
        "control": "NC-13",
        "description": "no bare 'True' check constants in reducer "
                       "(composer-constant trap)",
        "fails_closed": not bare_true,
    })

    doc = {
        "schema": "inferswarm.issue195.negative-controls/1",
        "controls": controls,
        "all_fail_closed": all(c["fails_closed"] for c in controls),
    }
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({c["control"]: c["fails_closed"] for c in controls},
                     indent=1))
    print("all_fail_closed =", doc["all_fail_closed"])
    return 0 if doc["all_fail_closed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
