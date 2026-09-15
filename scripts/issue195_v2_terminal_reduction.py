#!/usr/bin/env python3
"""Issue #195 R8-D v2: machine terminal reduction with corrected
BLOCKED-vs-FAIL semantics.

Derives every check from retained v2 evidence bytes and computes the
single terminal. Never trusts authored verdicts (an authored
terminal-reduction.json is never read).

Check groups (Issue #195 semantics):

  A. PROSPECTIVE / PRE-CANDIDATE PREREQUISITES
     predecessor preservation (R8-A/B/C + superseded v1), split/binaries/
     topology/fixture identity, sampler contract proven on the
     reference, reference run-record integrity, reference == frozen
     artifact, reference determinism, legacy/top_k negative controls,
     frozen-reference digest == REFREEZE pin, reference frozen
     prospectively (git ancestry + candidate gate fields).

  B. VALID-CANDIDATE-EXECUTION QUALIFICATION INVARIANTS
     sampler contract proven on candidate, candidate determinism,
     restart PID-death proof + sentinel equality, sampler re-proof
     after restart, candidate topology == frozen authority, candidate
     prompt/request/fixture identity at execution (vs the frozen
     reference's per-case prompt digests and the deterministic request
     serialization), placement/residency/fallback, accounting present.

  C. TOKEN/STOP CORRECTNESS (vs the FROZEN reference artifact)
     all-cases exact tokens, equal stop semantics, no pathological
     output.

VALID CANDIDATE CORRECTNESS OUTPUT (the BLOCKED/FAIL pivot) exists iff
the three candidate run records are internally integral (all 12
case-records retained with matching request/response digests, parsed
fields equal to the retained response bytes, sampler-gate + git fields
present), the reference arm is internally integral, the sampler
contract was proven on the reference, and the reference was
deterministic 3x. If that holds, a failure in ANY group (A post-hoc
anomaly, B, or C) is a qualification FAIL — a generated candidate
mismatch can never be relabeled BLOCKED, and post-hoc evidence
tampering after valid output is FAIL, not BLOCKED. If it does not hold,
any failed prerequisite is R8D_EVIDENCE_BLOCKED (no valid distributed
correctness execution was established).

Usage: issue195_v2_terminal_reduction.py [--check]
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("I195_REPO_OVERRIDE") or os.path.abspath(
    os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from issue195_v2_authority import (  # noqa: E402
    BINARY_SHA256, CAMPAIGN_ID, CANDIDATE_RPC_ENDPOINTS, FIXTURE_CASES,
    FIXTURE_LADDER_PATH, FIXTURE_LADDER_SHA256, FORBIDDEN_REQUEST_KEYS,
    R8D_V2_DIR, REQUEST_CONTRACT, SPLIT_SHA256, SPLIT_TOTAL_BYTES,
    START_MAIN, TERMINAL_BLOCKED, TERMINAL_FAIL, TERMINAL_PASS, TOPOLOGY)

RUN_SCHEMA = "inferswarm.issue195.ladder-run-v2/2"
CORRECTNESS_PREFIXES = ("scripts/issue195", "tests/test_issue195",
                        R8D_V2_DIR + "/evidence",
                        "docs/investigations/qwen38-flash-next-r8-d/"
                        "AUTHORITY-FREEZE")

if os.environ.get("I195_AREA_OVERRIDE"):
    AREA = os.environ["I195_AREA_OVERRIDE"]
else:
    AREA = os.path.join(REPO, "docs/investigations/qwen38-flash-next-r8-d-v2")
EV = os.path.join(AREA, "evidence")


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def load(path):
    with open(path) as fh:
        return json.load(fh)


def serialize_request(prompt_ids):
    body = dict(REQUEST_CONTRACT)
    body["prompt"] = list(prompt_ids)
    for k in FORBIDDEN_REQUEST_KEYS:
        body.pop(k, None)
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


GIT_REPO = os.environ.get("I195_GIT_OVERRIDE") or REPO


def git(*args):
    return subprocess.run(["git", "-C", GIT_REPO, *args],
                          capture_output=True, text=True)


ALL_CHECK_NAMES = (
    "predecessor_bundles_byte_preserved",
    "v1_evidence_byte_preserved",
    "split_all_members_exact",
    "binaries_pinned_all_hosts",
    "topology_uuid_bdf_match",
    "fixture_identity_exact",
    "sampler_contract_proven_reference",
    "reference_run_records_internal",
    "reference_identity_exact",
    "reference_deterministic_3x",
    "legacy_greedy_negative_control_noncanonical",
    "topk_gt1_negative_control_not_true_greedy",
    "frozen_reference_integrity",
    "reference_frozen_before_candidate",
    "sampler_contract_proven_candidate",
    "candidate_run_records_internal",
    "candidate_identity_exact",
    "candidate_deterministic_3x",
    "restart_pids_proven_gone",
    "restart_identity_sentinels",
    "sampler_contract_reproven_after_restart",
    "candidate_topology_matches_frozen_authority",
    "ple_host_resident_both_arms",
    "backbone_on_intended_devices",
    "no_fallback_wrong_device",
    "accounting_evidence_present",
    "all_cases_token_exact",
    "stop_semantics_equal_all_cases",
    "no_pathological_output",
)


# ---------------------------------------------------------------------------
# run-record verification (shared by reducer and freeze producer)
# ---------------------------------------------------------------------------

def producer_pin_for(rel_path):
    pf = os.path.join(REPO, R8D_V2_DIR, "producer-hashes.json")
    if not os.path.exists(pf):
        return None
    return load(pf).get(rel_path)


def verify_run_record(d, where, problems):
    """Internal + authority identity verification of one run record.
    Returns (internally_integral, identity_exact).

    internally_integral: retained bytes match their digests; parsed
      comparator fields equal the retained response bytes; schema/
      campaign/arm/placement fields present. (Authority-independent.)
    identity_exact: prompt/token IDs are the frozen ladder's; request
      bytes are the deterministic contract+prompt serialization with no
      forbidden keys; fixture digest at execution matches.
    """
    internal_ok = True
    identity_ok = True
    if d.get("schema") != RUN_SCHEMA:
        problems.append(f"{where}: wrong schema")
        internal_ok = False
    if d.get("campaign") != CAMPAIGN_ID:
        problems.append(f"{where}: wrong campaign")
        internal_ok = False
    if d.get("git_head") is None or "git_clean" not in d:
        problems.append(f"{where}: missing git state")
        internal_ok = False
    if d.get("producer_sha256") is None:
        problems.append(f"{where}: missing producer identity")
        internal_ok = False
    else:
        pin = producer_pin_for(d.get("producer_path") or
                               "scripts/issue195_v2_run_ladder.py")
        if pin is not None and pin != d["producer_sha256"]:
            problems.append(f"{where}: producer sha != repo pin "
                            "(executing producer differs from pinned bytes)")
            internal_ok = False
    if d.get("fixture_ladder_sha256") != FIXTURE_LADDER_SHA256:
        problems.append(f"{where}: fixture ladder digest mismatch")
        identity_ok = False
    if d.get("request_contract") != REQUEST_CONTRACT:
        problems.append(f"{where}: request contract drift")
        identity_ok = False
    if not d.get("results"):
        problems.append(f"{where}: no results")
        internal_ok = False
        return internal_ok, identity_ok
    ladder = json.load(open(os.path.join(REPO, FIXTURE_LADDER_PATH)))
    ladder_ids = {c["case_id"]: c["prompt_token_ids"] for c in ladder["cases"]}
    for r in d["results"]:
        cid = r.get("case_id", "?")
        try:
            reqb = base64.b64decode(r["request_bytes_b64"], validate=True)
        except Exception:
            problems.append(f"{where}/{cid}: request bytes undecodable")
            internal_ok = False
            continue
        if sha_b(reqb) != r.get("request_sha256"):
            problems.append(f"{where}/{cid}: request digest mismatch")
            internal_ok = False
        try:
            respb = base64.b64decode(r["response_bytes_b64"], validate=True)
        except Exception:
            problems.append(f"{where}/{cid}: response bytes undecodable")
            internal_ok = False
            continue
        if sha_b(respb) != r.get("response_sha256"):
            problems.append(f"{where}/{cid}: response digest mismatch")
            internal_ok = False
            continue
        try:
            parsed = json.loads(respb)
        except Exception:
            problems.append(f"{where}/{cid}: response bytes not JSON")
            internal_ok = False
            continue
        p = r.get("parsed_from_retained_bytes") or {}
        if p.get("generated_tokens") != parsed.get("tokens"):
            problems.append(f"{where}/{cid}: tokens not from retained bytes")
            internal_ok = False
        if p.get("stop_type") != parsed.get("stop_type"):
            problems.append(f"{where}/{cid}: stop_type not from retained bytes")
            internal_ok = False
        if p.get("stopping_word") != parsed.get("stopping_word"):
            problems.append(f"{where}/{cid}: stopping_word not from bytes")
            internal_ok = False
        # identity vs authority
        try:
            body = json.loads(reqb)
        except Exception:
            body = None
        if body is None:
            identity_ok = False
            continue
        for k in FORBIDDEN_REQUEST_KEYS:
            if k in body:
                problems.append(f"{where}/{cid}: forbidden key {k} in request")
                identity_ok = False
        ids = r.get("prompt_token_ids")
        if body.get("prompt") != ids:
            problems.append(f"{where}/{cid}: prompt ids != request bytes")
            identity_ok = False
        if ids is None or ladder_ids.get(cid) != ids:
            problems.append(f"{where}/{cid}: prompt ids != frozen ladder")
            identity_ok = False
        if sha_b(json.dumps(ids, separators=(",", ":")).encode()) != \
                r.get("prompt_token_ids_sha256"):
            problems.append(f"{where}/{cid}: prompt digest mismatch")
            identity_ok = False
        if reqb != serialize_request(ids):
            problems.append(f"{where}/{cid}: request bytes != deterministic "
                            "serialization")
            identity_ok = False
        if r.get("fixture_ladder_sha256_at_execution") != FIXTURE_LADDER_SHA256:
            problems.append(f"{where}/{cid}: ladder digest at execution drift")
            identity_ok = False
    return internal_ok, identity_ok


def tokens_of(run, cid):
    for r in run["results"]:
        if r["case_id"] == cid:
            p = r["parsed_from_retained_bytes"]
            return (p["generated_tokens"], p["stop_type"],
                    p["stopping_word"])
    raise KeyError(cid)


# ---------------------------------------------------------------------------
# Group A checks
# ---------------------------------------------------------------------------

def check_predecessor_manifests():
    for area in ("qwen38-flash-next-r8-a", "qwen38-flash-next-r8-b",
                 "qwen38-flash-next-r8-c"):
        m = os.path.join(REPO, "docs/investigations", area, "MANIFEST.sha256")
        for line in open(m):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            h, p = line.split(None, 1)
            fp = os.path.join(REPO, p.lstrip("*"))
            if not os.path.exists(fp) or sha(fp) != h:
                return False
    return True


def check_v1_evidence_preserved():
    """Superseded v1 evidence bytes remain byte-identical to the v1
    MANIFEST (never rewritten)."""
    m = os.path.join(REPO, "docs/investigations/qwen38-flash-next-r8-d",
                     "MANIFEST.sha256")
    for line in open(m):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, p = line.split(None, 1)
        fp = os.path.join(REPO, p.lstrip("*"))
        if not os.path.exists(fp) or sha(fp) != h:
            return False
    return True


def check_split():
    d = load(os.path.join(EV, "split-identity", "split-rehash.json"))
    if not d["all_members_match_r8a_pins"]:
        return False
    for m in d["members"]:
        if SPLIT_SHA256[m["file"]] != m["sha256"]:
            return False
    return d["total_bytes"] == SPLIT_TOTAL_BYTES


def check_binaries():
    pat = re.compile(
        r"^([0-9a-f]{64})\s+/home/hermes/llama.cpp/build-v041/bin/"
        r"(llama-cli|llama-server|ggml-rpc-server)$")
    for host in ("inferswarm01", "inferswarm03", "inferswarm04"):
        found = {}
        for line in open(os.path.join(
                EV, "host-inventory", f"{host}-inventory-raw.txt")):
            m = pat.match(line.strip())
            if m:
                found[m.group(2)] = m.group(1)
        for b, h in BINARY_SHA256.items():
            if found.get(b) != h:
                return False
    return True


def check_topology():
    for host, spec in (("inferswarm01", TOPOLOGY["client"]),
                       ("inferswarm03", TOPOLOGY["rpc1"]),
                       ("inferswarm04", TOPOLOGY["rpc2"])):
        txt = open(os.path.join(
            EV, "host-inventory", f"{host}-inventory-raw.txt")).read()
        for g in spec["gpus"]:
            if g["uuid"] not in txt or g["bdf"] not in txt:
                return False
    return True


def check_fixture_identity():
    return sha(os.path.join(REPO, FIXTURE_LADDER_PATH)) == FIXTURE_LADDER_SHA256


def check_probe_canonical(probe):
    v = probe["variants"]["canonical"]
    return (v["classification"] == "TRUE_GREEDY_PROVEN"
            and v["log_evidence"]["chains"].count("logits -> top-k -> dist") >= 1
            and v["log_evidence"]["unresolved_warnings"] == 0
            and v["request"].get("top_k") == 1)


def check_probe_legacy(probe):
    v = probe["variants"]["legacy"]
    return (v["classification"] == "NONCANONICAL_LEGACY_GREEDY"
            and v["log_evidence"]["greedy_unresolved_warnings"] >= 1
            and "top-k" not in " ".join(v["log_evidence"]["chains"]))


def check_probe_wide(probe):
    v = probe["variants"]["wide"]
    return (v["classification"] == "NOT_TRUE_GREEDY"
            and v["request"].get("top_k", 0) != 1)


def verify_frozen_reference(fr, problems):
    """Every frozen case equals the underlying retained raw reference
    execution records; ref-run file digests equal the frozen pins."""
    ok = True
    for i in (1, 2, 3):
        rp = os.path.join(EV, "reference", f"ref-run-{i}.json")
        want = fr["reference_run_file_sha256"].get(f"ref-run-{i}.json")
        if want != sha(rp):
            problems.append(f"ref-run-{i}.json digest != frozen pin")
            ok = False
        d = load(rp)
        for cid in FIXTURE_CASES:
            r = next(x for x in d["results"] if x["case_id"] == cid)
            p = r["parsed_from_retained_bytes"]
            fc = fr["cases"][cid]
            if (p["generated_tokens"] != fc["generated_tokens"]
                    or p["stop_type"] != fc["stop_type"]
                    or p["stopping_word"] != fc["stopping_word"]):
                problems.append(f"frozen case {cid} != ref-run-{i} bytes")
                ok = False
            if r["prompt_token_ids_sha256"] != fc["prompt_token_ids_sha256"]:
                problems.append(f"frozen case {cid} prompt digest != run")
                ok = False
    return ok


def check_reference_frozen_prospectively(cand_runs, rf, problems):
    """Mechanical prospective-freeze proof from retained git history and
    candidate execution metadata (never an authored boolean):

    1. REFREEZE.json pins refreeze_commit + frozen-reference sha256;
    2. that commit's git tree contains frozen-reference.json bytes
       exactly equal to the pinned digest;
    3. the refreeze commit is HEAD-or-ancestor of every candidate run's
       recorded git_head, with no correctness-bearing diffs between;
    4. every candidate run record embeds refreeze_commit +
       frozen_reference_sha256 (sampled at execution by the producer's
       fail-closed gate) equal to the pin;
    5. every candidate run executed on a clean worktree.
    """
    exp_commit = rf["refreeze_commit"]
    ok = True
    rel = R8D_V2_DIR + "/evidence/reference/frozen-reference.json"
    show = git("show", f"{exp_commit}:{rel}")
    if show.returncode != 0:
        problems.append("refreeze commit lacks frozen-reference.json")
        ok = False
    elif sha_b(show.stdout.encode()) != rf["frozen_reference_sha256"]:
        problems.append("refreeze-commit tree bytes != pinned digest")
        ok = False
    for d in cand_runs:
        head = d.get("git_head")
        if not head:
            problems.append("candidate run missing git_head")
            ok = False
            continue
        if head != exp_commit:
            anc = git("merge-base", "--is-ancestor", exp_commit, head)
            if anc.returncode != 0:
                problems.append(f"refreeze commit {exp_commit[:12]} not "
                                f"ancestor of candidate head {head[:12]}")
                ok = False
                continue
            diff = git("diff", "--name-only", exp_commit, head)
            pin_file = (R8D_V2_DIR + "/evidence/reference/REFREEZE.json")
            changed = [p for p in diff.stdout.split()
                       if p != pin_file and any(
                           p.startswith(pre) for pre in
                           CORRECTNESS_PREFIXES)]
            if changed:
                problems.append("correctness-bearing change after refreeze: "
                                + changed[0])
                ok = False
        g = d.get("sampler_gate") or {}
        if g.get("gate_passed") is not True:
            problems.append("candidate run gate not passed at execution")
            ok = False
        if g.get("refreeze_commit") != exp_commit:
            problems.append("candidate run gate refreeze_commit mismatch")
            ok = False
        if g.get("frozen_reference_sha256") != rf["frozen_reference_sha256"]:
            problems.append("candidate run gate frozen sha mismatch")
            ok = False
        if not d.get("git_clean"):
            problems.append("candidate run executed with dirty worktree")
            ok = False
    return ok


# ---------------------------------------------------------------------------
# Group B checks
# ---------------------------------------------------------------------------

def check_candidate_topology():
    lp = os.path.join(EV, "candidate", "launch-candidate.sh")
    if not os.path.exists(lp):
        return False
    m = re.search(r"--rpc\s+(\S+)", open(lp).read())
    if not m:
        return False
    return sorted(m.group(1).split(",")) == sorted(CANDIDATE_RPC_ENDPOINTS)


def check_placement(ref_log, cand_log):
    ref = open(ref_log).read()
    cand = open(cand_log).read()
    ple_ref = "lazy read enabled" in ref and "per_layer_token_embd" in ref
    ple_cand = "lazy read enabled" in cand and "per_layer_token_embd" in cand
    rpc_bufs = re.findall(
        r"RPC\d+\[[^\]]+\] model buffer size =\s+([0-9.]+) MiB", cand)
    cuda_bufs = re.findall(
        r"CUDA[01] model buffer size =\s+([0-9.]+) MiB", cand)
    backbone = sum(float(x) for x in rpc_bufs) + sum(float(x) for x in cuda_bufs)
    five_devices = len(rpc_bufs) == 3 and len(cuda_bufs) == 2
    cpu_only_fallback = ("CPU_Mapped model buffer size" in cand
                         and backbone < 30000)
    return {
        "ple_host_resident_both_arms": ple_ref and ple_cand,
        "backbone_on_intended_devices": five_devices and backbone > 40000,
        "no_fallback_wrong_device": not cpu_only_fallback,
        "backbone_mib": round(backbone, 2),
    }


def check_restart_pids():
    pidf = os.path.join(EV, "candidate", "restart-pid-proof.json")
    if not os.path.exists(pidf):
        return False
    pp = load(pidf)
    for p in pp.get("terminated_pids", []):
        if p.get("kill_confirmed") is not True or \
                p.get("confirmed_gone_before_relaunch") is not True:
            return False
    return bool(pp.get("terminated_pids"))


def check_restart_reproof():
    rp = os.path.join(EV, "candidate", "sampler-probe-cand-restart.json")
    if not os.path.exists(rp):
        return False
    return check_probe_canonical(load(rp))


def check_restart_sentinels(cand_runs):
    for c in ("case-256", "case-4096"):
        rr = load(os.path.join(EV, "candidate", f"cand-restart-{c}.json"))
        rt, rs, rw = tokens_of(rr, c)
        pt, ps, pw = tokens_of(cand_runs[0], c)
        if not (rt == pt and rs == ps and rw == pw):
            return False
    return True


def check_no_pathological(ref_runs, cand_runs):
    for run in ref_runs + cand_runs[:1]:
        for r in run["results"]:
            toks = r["parsed_from_retained_bytes"]["generated_tokens"]
            if not toks:
                return False
            if len(set(toks)) == 1 and len(toks) > 2:
                return False
    toks, stype, _ = tokens_of(cand_runs[0], "case-4096")
    if len(toks) == 1 and stype != "eos":
        return False
    return True


def check_accounting_present():
    for f in ("client-01-during.txt", "rpc-inferswarm03-during.txt",
              "rpc-inferswarm04-during.txt"):
        if not os.path.exists(os.path.join(EV, "accounting", f)):
            return False
    return True


# ---------------------------------------------------------------------------
# derive
# ---------------------------------------------------------------------------

def derive():
    problems = []
    ref_paths = [os.path.join(EV, "reference", f"ref-run-{i}.json")
                 for i in (1, 2, 3)]
    cand_paths = [os.path.join(EV, "candidate", f"cand-run-{i}.json")
                  for i in (1, 2, 3)]
    missing = [p for p in ref_paths + cand_paths
               + [os.path.join(EV, "sampler-contract",
                               "sampler-probe-ref.json"),
                  os.path.join(EV, "candidate", "sampler-probe-cand.json")]
               if not os.path.exists(p)]
    if missing:
        # fail-closed: no evidence => no valid execution => BLOCKED
        for p in missing:
            problems.append("missing evidence: " + os.path.basename(p))
        checks = dict.fromkeys(ALL_CHECK_NAMES, False)
        return {
            "checks": checks,
            "groups": {"A": {}, "B": {}, "C": {}},
            "has_valid_candidate_output": False,
            "terminal": TERMINAL_BLOCKED,
            "terminal_basis": ("no valid distributed correctness execution "
                               "established; missing evidence: "
                               + ", ".join(os.path.basename(p)
                                           for p in missing[:5])),
            "problems": problems,
            "placement": {"ple_host_resident_both_arms": False,
                          "backbone_on_intended_devices": False,
                          "no_fallback_wrong_device": False,
                          "backbone_mib": None},
            "frozen": None,
        }
    ref_runs = [load(p) for p in ref_paths]
    cand_runs = [load(p) for p in cand_paths]

    ref_internal = ref_identity = True
    for i, d in enumerate(ref_runs, 1):
        a, b = verify_run_record(d, f"ref-run-{i}", problems)
        ref_internal = ref_internal and a
        ref_identity = ref_identity and b

    cand_internal = cand_identity = True
    for i, d in enumerate(cand_runs, 1):
        if d.get("arm") != "candidate":
            problems.append(f"cand-run-{i}: wrong arm")
            cand_internal = False
        a, b = verify_run_record(d, f"cand-run-{i}", problems)
        cand_internal = cand_internal and a
        cand_identity = cand_identity and b
        if [r["case_id"] for r in d["results"]] != FIXTURE_CASES:
            problems.append(f"cand-run-{i}: case set/order drift")
            cand_internal = False
        if not (d.get("sampler_gate") or {}).get("gate_passed"):
            problems.append(f"cand-run-{i}: gate fields missing")
            cand_internal = False

    ref_probe = load(os.path.join(EV, "sampler-contract",
                                  "sampler-probe-ref.json"))
    cand_probe = load(os.path.join(EV, "candidate",
                                   "sampler-probe-cand.json"))

    placement = check_placement(
        os.path.join(EV, "reference", "ref-server.log"),
        os.path.join(EV, "candidate", "cand-server.log"))

    sampler_ref_ok = check_probe_canonical(ref_probe)
    ref_det = all(tokens_of(ref_runs[0], c) == tokens_of(ref_runs[i], c)
                  for c in FIXTURE_CASES for i in (1, 2))

    # frozen reference
    rfp = os.path.join(EV, "reference", "REFREEZE.json")
    rf = load(rfp) if os.path.exists(rfp) else None
    frozen = None
    frozen_integrity = False
    frozen_prospective = False
    if rf is not None:
        frp = os.path.join(EV, "reference", "frozen-reference.json")
        if os.path.exists(frp):
            frozen = load(frp)
            if sha(frp) == rf["frozen_reference_sha256"]:
                frozen_integrity = verify_frozen_reference(frozen, problems)
            else:
                problems.append("frozen-reference.json digest != REFREEZE "
                                "pin (post-hoc mutation)")
        else:
            problems.append("frozen-reference.json missing")
        frozen_prospective = check_reference_frozen_prospectively(
            cand_runs, rf, problems)
    else:
        problems.append("REFREEZE.json missing")

    groupA = {
        "predecessor_bundles_byte_preserved": check_predecessor_manifests(),
        "v1_evidence_byte_preserved": check_v1_evidence_preserved(),
        "split_all_members_exact": check_split(),
        "binaries_pinned_all_hosts": check_binaries(),
        "topology_uuid_bdf_match": check_topology(),
        "fixture_identity_exact": check_fixture_identity(),
        "sampler_contract_proven_reference": sampler_ref_ok,
        "reference_run_records_internal": ref_internal,
        "reference_identity_exact": ref_identity,
        "reference_deterministic_3x": ref_det,
        "legacy_greedy_negative_control_noncanonical": (
            check_probe_legacy(ref_probe) and check_probe_legacy(cand_probe)),
        "topk_gt1_negative_control_not_true_greedy": (
            check_probe_wide(ref_probe) and check_probe_wide(cand_probe)),
        "frozen_reference_integrity": frozen_integrity,
        "reference_frozen_before_candidate": frozen_prospective,
    }

    # the BLOCKED/FAIL pivot
    has_valid_cand = (cand_internal and ref_internal and sampler_ref_ok
                      and ref_det)

    groupB = {
        "sampler_contract_proven_candidate": check_probe_canonical(cand_probe),
        "candidate_run_records_internal": cand_internal,
        "candidate_identity_exact": cand_identity,
        "candidate_deterministic_3x": all(
            tokens_of(cand_runs[0], c) == tokens_of(cand_runs[i], c)
            for c in FIXTURE_CASES for i in (1, 2)),
        "restart_pids_proven_gone": check_restart_pids(),
        "restart_identity_sentinels": check_restart_sentinels(cand_runs),
        "sampler_contract_reproven_after_restart": check_restart_reproof(),
        "candidate_topology_matches_frozen_authority": check_candidate_topology(),
        "ple_host_resident_both_arms": placement["ple_host_resident_both_arms"],
        "backbone_on_intended_devices":
            placement["backbone_on_intended_devices"],
        "no_fallback_wrong_device": placement["no_fallback_wrong_device"],
        "accounting_evidence_present": check_accounting_present(),
    }

    # Group C — vs the FROZEN reference artifact (never a mutable ref-run)
    all_exact = stop_equal = False
    if frozen is not None:
        all_exact = stop_equal = True
        for cid in FIXTURE_CASES:
            ct, cs, csw = tokens_of(cand_runs[0], cid)
            fc = frozen["cases"][cid]
            if ct != fc["generated_tokens"]:
                all_exact = False
            if not (cs == fc["stop_type"] and csw == fc["stopping_word"]):
                stop_equal = False
    groupC = {
        "all_cases_token_exact": all_exact,
        "stop_semantics_equal_all_cases": stop_equal,
        "no_pathological_output": check_no_pathological(ref_runs, cand_runs),
    }

    a_fail = [k for k, v in groupA.items() if not v]
    b_fail = [k for k, v in groupB.items() if not v]
    c_fail = [k for k, v in groupC.items() if not v]

    if has_valid_cand:
        if not (a_fail or b_fail or c_fail):
            terminal, basis = TERMINAL_PASS, "all checks green"
        else:
            terminal = TERMINAL_FAIL
            basis = ("valid candidate correctness output reached; failed "
                     "invariants: " + ", ".join(a_fail + b_fail + c_fail))
    else:
        terminal = TERMINAL_BLOCKED
        failed = a_fail + b_fail
        basis = ("no valid distributed correctness execution established; "
                 "failed prerequisites: " + (", ".join(failed) if failed
                                             else "candidate records invalid"))
    return {
        "checks": {**groupA, **groupB, **groupC},
        "groups": {"A": groupA, "B": groupB, "C": groupC},
        "has_valid_candidate_output": has_valid_cand,
        "terminal": terminal,
        "terminal_basis": basis,
        "problems": problems,
        "placement": placement,
        "frozen": frozen,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    r = derive()
    per_case = {}
    if r["frozen"] is not None:
        cand0 = load(os.path.join(EV, "candidate", "cand-run-1.json"))
        for cid in FIXTURE_CASES:
            ct, cs, _ = tokens_of(cand0, cid)
            fc = r["frozen"]["cases"][cid]
            rt = fc["generated_tokens"]
            fd = next((j for j, (x, y) in enumerate(zip(ct, rt)) if x != y),
                      None if ct == rt else min(len(ct), len(rt)))
            per_case[cid] = {
                "reference_tokens": rt, "candidate_tokens": ct,
                "token_exact": ct == rt, "stop_equal": cs == fc["stop_type"],
                "first_divergence_position": fd,
            }
    doc = {
        "schema": "inferswarm.issue195.terminal-reduction/2",
        "campaign": CAMPAIGN_ID,
        "start_main": START_MAIN,
        "checks": r["checks"],
        "check_groups": {g: {k: r["checks"][k] for k in grp}
                         for g, grp in r["groups"].items()},
        "has_valid_candidate_output": r["has_valid_candidate_output"],
        "per_case": per_case,
        "placement_detail": r["placement"],
        "terminal": r["terminal"],
        "terminal_basis": r["terminal_basis"],
        "problems": r["problems"][:20],
    }
    out = os.path.join(AREA, "terminal-reduction.json")
    if args.check:
        cur = load(out) if os.path.exists(out) else None
        same = cur is not None and cur["terminal"] == doc["terminal"] and \
            cur["checks"] == doc["checks"]
        print("CHECK", "OK" if same else "DRIFT")
        return 0 if same else 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    failed = [k for k, v in r["checks"].items() if not v]
    print(json.dumps({
        "terminal": r["terminal"],
        "failed_checks": failed,
        "per_case_token_exact": {c: v["token_exact"]
                                 for c, v in per_case.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
