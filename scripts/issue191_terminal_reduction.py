#!/usr/bin/env python3
"""Issue #191 R8-B terminal reduction.

Re-derives the terminal classification from the retained evidence bytes:
  - split verification (all 3 members sha256-pinned);
  - reference determinism (3 runs identical);
  - candidate determinism (3 runs identical) + restart equality;
  - reference/candidate exact token comparison;
  - placement/accounting invariants;
  - negative controls all fail closed.

Terminal (exactly one):
  R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_PASS
  R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
EV = HERE / "docs" / "investigations" / "qwen38-flash-next-r8-b" / "evidence"

PASS = "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_PASS"
FAIL = "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL"


def load(rel):
    return json.loads((EV / rel).read_text())


def main():
    checks = {}

    split = load("split-identity/split-verification.json")
    checks["split_all_members_exact"] = split["all_ok"] and all(
        m["sha256_ok"] and m["bytes_ok"] and m["header_bytes_ok"]
        for m in split["members"])

    ref_runs = [load(f"reference/reference-run-{i}.json") for i in (1, 2, 3)]
    cand_runs = [load(f"candidate/candidate-run-{i}.json") for i in (1, 2, 3)]
    restart = load("candidate/candidate-restart.json")

    def tokens(run):
        return {c["case_id"]: c["generated_tokens"] for c in run["results"]}

    checks["reference_deterministic_3x"] = all(
        tokens(r) == tokens(ref_runs[0]) for r in ref_runs[1:])
    checks["candidate_deterministic_3x"] = all(
        tokens(c) == tokens(cand_runs[0]) for c in cand_runs[1:])
    checks["restart_equality"] = tokens(restart) == tokens(cand_runs[0])

    r, k = tokens(ref_runs[0]), tokens(cand_runs[0])
    per_case = {cid: (r[cid] == k[cid]) for cid in r}
    checks["all_cases_token_exact"] = all(per_case.values())
    checks["prefix_divergence_pattern"] = {
        cid: next((i for i, (a, b) in enumerate(zip(r[cid], k[cid])) if a != b),
                  min(len(r[cid]), len(k[cid])))
        for cid in r}

    acct = load("accounting/residency-accounting.json")
    checks["ple_host_resident_both_arms"] = (
        "CPU lazy read" in acct["reference_arm_inferswarm01"]["placement_from_load_log"]["PLE_per_layer_token_embd_weight"]
        and "CPU lazy read" in acct["candidate_arm_client_inferswarm01"]["placement_from_load_log"]["PLE_per_layer_token_embd_weight"])
    checks["backbone_on_intended_devices"] = (
        acct["totals_check"]["backbone_bytes_on_devices_MiB"] == 41368)

    nc = load("negative-controls/negative-controls.json")
    checks["negative_controls_fail_closed"] = nc["all_fail_closed"]

    # Stop semantics + non-pathology
    checks["long_cases_nonempty"] = all(
        len(k[cid]) >= 1 for cid in ("case-3072", "case-4096"))

    passed = all(v for kk, v in checks.items() if isinstance(v, bool)) and checks["all_cases_token_exact"]
    terminal = PASS if passed else FAIL

    doc = {
        "schema": "inferswarm.issue191.terminal-reduction/1",
        "checks": checks,
        "per_case_token_exact": per_case,
        "terminal": terminal,
        "fail_basis": None if passed else (
            "Distributed candidate (cross-host RPC, 5 CUDA devices over 3 hosts) "
            "produces generated token IDs that differ from the frozen same-build "
            "single-host non-RPC reference on all four fixture cases, with a "
            "consistent shared-prefix divergence pattern. The candidate is "
            "internally deterministic (3/3 identical) and restart-stable, so the "
            "divergence is reproducible, not noise. Per the issue contract this "
            "is retained as FAIL: no comparator weakening, no topology/runtime "
            "change after the observation."),
    }
    out = HERE / "docs" / "investigations" / "qwen38-flash-next-r8-b" / "terminal-reduction.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(json.dumps(doc, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
