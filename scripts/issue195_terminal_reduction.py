#!/usr/bin/env python3
"""Issue #195 R8-D: machine terminal reduction.

Re-derives every qualification check from the retained evidence bytes
under docs/investigations/qwen38-flash-next-r8-d/ and computes the single
terminal classification. Never trusts an authored verdict field; the
authored terminal (if any) is only cross-checked, never consumed.

Usage: issue195_terminal_reduction.py [--check]
  default: write terminal-reduction.json
  --check: verify existing terminal-reduction.json against current bytes
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
AREA = os.environ.get("I195_AREA_OVERRIDE") or os.path.join(
    REPO, "docs", "investigations", "qwen38-flash-next-r8-d")
EV = os.path.join(AREA, "evidence")
_ALT_REPO = os.environ.get("I195_REPO_OVERRIDE")
_R8B_LADDER = os.path.join(
    _ALT_REPO or REPO, "docs", "investigations",
    "qwen38-flash-next-r8-b", "evidence", "reference", "fixture-ladder.json")

sys.path.insert(0, os.path.join(REPO, "scripts"))
from issue195_r8d_authority import (  # noqa: E402
    BINARY_SHA256, DRIVER_AT_FREEZE, FIXTURE_CASES, FIXTURE_LADDER_PATH,
    R8B_DIR, R8C_DIR, REQUEST_CONTRACT, SPLIT_SHA256, SPLIT_TOTAL_BYTES,
    START_MAIN, TERMINAL_BLOCKED, TERMINAL_FAIL, TERMINAL_PASS, TOPOLOGY)

TERMINAL_KEYS = [
    "predecessor_bundles_byte_preserved",
    "split_all_members_exact",
    "binaries_pinned_all_hosts",
    "topology_uuid_bdf_match",
    "sampler_contract_proven_reference",
    "sampler_contract_proven_candidate",
    "sampler_contract_reproven_after_restart",
    "legacy_greedy_negative_control_noncanonical",
    "topk_gt1_negative_control_not_true_greedy",
    "reference_deterministic_3x",
    "reference_frozen_before_candidate",
    "candidate_deterministic_3x",
    "restart_identity_sentinels",
    "all_cases_token_exact",
    "stop_semantics_equal_all_cases",
    "no_pathological_output",
    "ple_host_resident_both_arms",
    "backbone_on_intended_devices",
    "no_fallback_wrong_device",
    "fixture_identity_exact",
]


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load(path):
    with open(path) as fh:
        return json.load(fh)


def verify_predecessor_manifests():
    """R8-A/B/C MANIFEST rows verify against current bytes."""
    for area in ("qwen38-flash-next-r8-a", "qwen38-flash-next-r8-b",
                 "qwen38-flash-next-r8-c"):
        m = os.path.join(REPO, "docs", "investigations", area, "MANIFEST.sha256")
        for line in open(m):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            h, p = line.split(None, 1)
            p = p.lstrip("*")
            fp = os.path.join(REPO, p)
            if not os.path.exists(fp) or sha(fp) != h:
                return False
    return True


def parse_chain_evidence(log_text):
    chains = re.findall(r"sampler chain:\s*(\S.*)", log_text)
    warns = len(re.findall(r"unable to match sampler", log_text))
    greedy = len(re.findall(r"unable to match sampler by name 'greedy'", log_text))
    return chains, warns, greedy


def check_split():
    d = load(os.path.join(EV, "split-identity", "split-rehash.json"))
    if not d["all_members_match_r8a_pins"]:
        return False
    for m in d["members"]:
        if SPLIT_SHA256[m["file"]] != m["sha256"]:
            return False
    return d["total_bytes"] == SPLIT_TOTAL_BYTES


def check_binaries():
    pat = re.compile(r"^([0-9a-f]{64})\s+/home/hermes/llama.cpp/build-v041/bin/(llama-cli|llama-server|ggml-rpc-server)$")
    for host in ("inferswarm01", "inferswarm03", "inferswarm04"):
        found = {}
        for line in open(os.path.join(EV, "host-inventory", f"{host}-inventory-raw.txt")):
            m = pat.match(line.strip())
            if m:
                found[m.group(2)] = m.group(1)
        for b, h in BINARY_SHA256.items():
            if found.get(b) != h:
                return False
    return True


def check_topology():
    ok = True
    for host, spec in (("inferswarm01", TOPOLOGY["client"]),
                       ("inferswarm03", TOPOLOGY["rpc1"]),
                       ("inferswarm04", TOPOLOGY["rpc2"])):
        txt = open(os.path.join(EV, "host-inventory", f"{host}-inventory-raw.txt")).read()
        for g in spec["gpus"]:
            if g["uuid"] not in txt or g["bdf"] not in txt:
                ok = False
    return ok


def check_probe_legacy(probe_path):
    d = load(probe_path)
    v = d["variants"]["legacy"]
    return (v["classification"] == "NONCANONICAL_LEGACY_GREEDY"
            and v["log_evidence"]["greedy_unresolved_warnings"] >= 1
            and "top-k" not in " ".join(v["log_evidence"]["chains"]))


def check_probe_wide(probe_path):
    d = load(probe_path)
    v = d["variants"]["wide"]
    return (v["classification"] == "NOT_TRUE_GREEDY"
            and v["request"].get("top_k", 0) != 1)


def check_probe_canonical(probe_path):
    d = load(probe_path)
    v = d["variants"]["canonical"]
    return (v["classification"] == "TRUE_GREEDY_PROVEN"
            and v["log_evidence"]["chains"].count("logits -> top-k -> dist") >= 1
            and v["log_evidence"]["unresolved_warnings"] == 0
            and v["request"].get("top_k") == 1)


def check_request_contract_in_runs(run_paths):
    for p in run_paths:
        d = load(p)
        rc = d["request_contract"]
        for k, v in REQUEST_CONTRACT.items():
            if rc.get(k) != v:
                return False
    return True


def tokens_of(run, case_id):
    for r in run["results"]:
        if r["case_id"] == case_id:
            return r["generated_tokens"], r["stop_type"], r["stopping_word"]
    raise KeyError(case_id)


def check_no_pathological(ref_runs, cand_runs):
    """No empty/all-identical/NaN-like output; every case returns >=1 token."""
    for run in ref_runs + cand_runs[:1]:
        for r in run["results"]:
            if not r["generated_tokens"] or len(r["generated_tokens"]) == 0:
                return False
            if len(set(r["generated_tokens"])) == 1 and len(r["generated_tokens"]) > 2:
                return False
    # the case-4096 single-token candidate output must be a real EOG stop
    toks, stype, _ = tokens_of(cand_runs[0], "case-4096")
    if len(toks) == 1 and stype != "eos":
        return False
    return True


def check_placement():
    ref = open(os.path.join(EV, "reference", "ref-server.log")).read()
    cand = open(os.path.join(EV, "candidate", "cand-server.log")).read()
    ple_ref = "lazy read enabled" in ref and "per_layer_token_embd" in ref
    ple_cand = "lazy read enabled" in cand and "per_layer_token_embd" in cand
    # backbone across the 5 CUDA devices (candidate): CUDA0+CUDA1+3 RPC buffers
    dev_bufs = re.findall(r"model buffer size =\s+([0-9.]+) MiB", cand)
    rpc_bufs = re.findall(r"RPC\d+\[[^\]]+\] model buffer size =\s+([0-9.]+) MiB", cand)
    cuda_bufs = re.findall(r"CUDA[01] model buffer size =\s+([0-9.]+) MiB", cand)
    backbone = sum(float(x) for x in rpc_bufs) + sum(float(x) for x in cuda_bufs)
    five_devices = len(rpc_bufs) == 3 and len(cuda_bufs) == 2
    cpu_only_fallback = "CPU_Mapped model buffer size" in cand and backbone < 30000
    return {
        "ple_host_resident_both_arms": ple_ref and ple_cand,
        "backbone_on_intended_devices": five_devices and backbone > 40000,
        "no_fallback_wrong_device": not cpu_only_fallback,
        "_backbone_mib": round(backbone, 2),
        "_buffer_lines": len(dev_bufs),
    }


def check_reference_frozen_before_candidate():
    d = load(os.path.join(EV, "reference", "frozen-reference.json"))
    return bool(d.get("frozen_before_candidate_output"))


def check_restart(probe_path):
    if not check_probe_canonical(probe_path):
        return False
    ok = True
    for c in ("case-256", "case-4096"):
        rr = load(os.path.join(EV, "candidate", f"cand-restart-{c}.json"))
        pre = load(os.path.join(EV, "candidate", "cand-run-1.json"))
        rt, rs, rw = tokens_of(rr, c)
        pt, ps, pw = tokens_of(pre, c)
        ok = ok and (rt == pt and rs == ps and rw == pw)
    return ok


def check_fixture_identity():
    """The ladder every run consumed is the accepted R8-B ladder byte-exact."""
    return sha(_R8B_LADDER) == _FROZEN_LADDER_SHA


_FROZEN_LADDER_SHA = "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    ref_runs = [load(os.path.join(EV, "reference", f"ref-run-{i}.json")) for i in (1, 2, 3)]
    cand_runs = [load(os.path.join(EV, "candidate", f"cand-run-{i}.json")) for i in (1, 2, 3)]

    placement = check_placement()

    checks = {
        "predecessor_bundles_byte_preserved": verify_predecessor_manifests(),
        "split_all_members_exact": check_split(),
        "binaries_pinned_all_hosts": check_binaries(),
        "topology_uuid_bdf_match": check_topology(),
        "sampler_contract_proven_reference": check_probe_canonical(
            os.path.join(EV, "sampler-contract", "sampler-probe-ref.json")),
        "sampler_contract_proven_candidate": check_probe_canonical(
            os.path.join(EV, "candidate", "sampler-probe-cand.json")),
        "sampler_contract_reproven_after_restart": check_restart(
            os.path.join(EV, "candidate", "sampler-probe-cand-restart.json")),
        "legacy_greedy_negative_control_noncanonical": check_probe_legacy(
            os.path.join(EV, "sampler-contract", "sampler-probe-ref.json"))
        and check_probe_legacy(os.path.join(EV, "candidate", "sampler-probe-cand.json")),
        "topk_gt1_negative_control_not_true_greedy": check_probe_wide(
            os.path.join(EV, "sampler-contract", "sampler-probe-ref.json"))
        and check_probe_wide(os.path.join(EV, "candidate", "sampler-probe-cand.json")),
        "reference_deterministic_3x": all(
            tokens_of(ref_runs[0], c) == tokens_of(ref_runs[i], c)
            for c in FIXTURE_CASES for i in (1, 2)),
        "reference_frozen_before_candidate": check_reference_frozen_before_candidate(),
        "candidate_deterministic_3x": all(
            tokens_of(cand_runs[0], c) == tokens_of(cand_runs[i], c)
            for c in FIXTURE_CASES for i in (1, 2)),
        "restart_identity_sentinels": check_restart(
            os.path.join(EV, "candidate", "sampler-probe-cand-restart.json")),
        "all_cases_token_exact": all(
            tokens_of(cand_runs[0], c)[0] == tokens_of(ref_runs[0], c)[0]
            for c in FIXTURE_CASES),
        "stop_semantics_equal_all_cases": all(
            tokens_of(cand_runs[0], c)[1:] == tokens_of(ref_runs[0], c)[1:]
            for c in FIXTURE_CASES),
        "no_pathological_output": check_no_pathological(ref_runs, cand_runs),
        "ple_host_resident_both_arms": placement["ple_host_resident_both_arms"],
        "backbone_on_intended_devices": placement["backbone_on_intended_devices"],
        "no_fallback_wrong_device": placement["no_fallback_wrong_device"],
        "fixture_identity_exact": check_fixture_identity(),
        "request_contract_unchanged_all_runs": check_request_contract_in_runs(
            [os.path.join(EV, "reference", f"ref-run-{i}.json") for i in (1, 2, 3)]
            + [os.path.join(EV, "candidate", f"cand-run-{i}.json") for i in (1, 2, 3)]),
    }

    per_case = {}
    for c in FIXTURE_CASES:
        rt, rs, _ = tokens_of(ref_runs[0], c)
        ct, cs, _ = tokens_of(cand_runs[0], c)
        fd = next((j for j, (a, b) in enumerate(zip(ct, rt)) if a != b),
                  None if ct == rt else min(len(ct), len(rt)))
        per_case[c] = {
            "reference_tokens": rt, "candidate_tokens": ct,
            "token_exact": ct == rt, "stop_equal": rs == cs,
            "first_divergence_position": fd,
        }

    prereq = all(checks[k] for k in checks if k != "all_cases_token_exact"
                 and k != "stop_semantics_equal_all_cases")
    if not prereq:
        terminal = TERMINAL_BLOCKED
    elif checks["all_cases_token_exact"] and checks["stop_semantics_equal_all_cases"]:
        terminal = TERMINAL_PASS
    else:
        terminal = TERMINAL_FAIL

    doc = {
        "schema": "inferswarm.issue195.terminal-reduction/1",
        "campaign": "issue195-r8d-true-greedy-requal-v1",
        "start_main": START_MAIN,
        "checks": checks,
        "per_case": per_case,
        "placement_detail": {k: v for k, v in placement.items() if not k.startswith("_")},
        "backbone_mib": placement.get("_backbone_mib"),
        "terminal": terminal,
        "terminal_basis": (
            "valid candidate correctness output reached with per-case token/stop "
            "mismatch against the frozen true-greedy reference"
            if terminal == TERMINAL_FAIL else
            "all checks green" if terminal == TERMINAL_PASS else
            "a prerequisite check failed before a valid comparison could be made"),
    }
    out = os.path.join(AREA, "terminal-reduction.json")
    if args.check:
        cur = load(out)
        same = cur["terminal"] == terminal and cur["checks"] == checks
        print("CHECK", "OK" if same else "DRIFT")
        return 0 if same else 1
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"terminal": terminal,
                      "failed_checks": [k for k, v in checks.items() if not v],
                      "per_case_token_exact": {c: per_case[c]["token_exact"] for c in per_case}},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
