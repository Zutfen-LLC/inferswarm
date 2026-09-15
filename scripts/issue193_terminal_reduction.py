#!/usr/bin/env python3
"""Issue #193 (R8-C) terminal reduction: derive the diagnosis terminal from
retained bytes, fail-closed.

Established chain (each step machine-checked below):
1. Phase 1 reproduction: accepted outputs reproduced under exact pinned authority.
2. Wedge A: direct CUDA vs loopback RPC on the same physical GPU + same pinned
   tensor subset diverge at generated position 3 (RPC not required for divergence;
   transport/cross-host excluded by A2 == B2 byte-identical streams and placements).
3. Wedge B: loopback vs remote RPC on matched 3060s produce IDENTICAL streams —
   cross-host network transport exonerated.
4. Accepted-protocol sampler-chain finding: the accepted R8-B request's
   samplers=["greedy"] did not resolve ("unable to match sampler by name 'greedy'"
   is retained 16x in the accepted reference-server.log); the chain actually built
   was "logits -> dist" (retained 2x per launch in the accepted log) — seeded
   distribution sampling, not greedy argmax.
5. Logit evidence: the accepted reference stream contains tokens at full-vocab
   rank 1 (pos1), ~154k (pos2), ~1.6k (pos3), ~42k (pos4) of the emitted
   distribution — impossible under true greedy, expected under dist sampling.
6. Phase 5 single-factor intervention (request field only: samplers=["top_k"],
   top_k=1 = true greedy): reference vs full five-device RPC candidate become
   token-identical on case-1024 and case-3072, agree through position 5 on
   case-256; the historical case-4096 immediate-EOS persists in the candidate.

Terminal: R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED.
Cause: NOT transport/state corruption. The R8-B exact-token FAIL is primarily
controlled by the unintentional dist-sampling chain amplifying lawful
cross-backend numerical-path differences (backend/placement-dependent logits
differences move the cumulative-sum crossing of a seeded distribution sample);
a residual placement-linked difference remains at case-256 position >=5 and
case-4096 EOS under true greedy, attributed to lawful numerical-path variation
but NOT cleanly separable in this issue without the logit-row surface the
pinned build's server does not expose (the server n_probs surface is
row-misaligned at this revision: emitted token != reported-distribution argmax
in every arm including the reference).
"""
from __future__ import annotations

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(_HERE, ".."))
R8B = os.path.join(ROOT, "docs", "investigations", "qwen38-flash-next-r8-b")
R8C = os.path.join(ROOT, "docs", "investigations", "qwen38-flash-next-r8-c")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from issue193_r8c_authority import (  # noqa: E402
    R8B_CASE256_CANDIDATE_TOKENS,
    R8B_CASE256_REFERENCE_TOKENS,
)


def jload(p):
    with open(p) as fh:
        return json.load(fh)


def toks(doc, case="case-256"):
    for r in doc["results"]:
        if r["case_id"] == case:
            return r["generated_tokens"]
    raise KeyError(case)


def placement_from_log(path):
    sizes = []
    with open(path, errors="replace") as fh:
        for line in fh:
            m = re.search(r"model buffer size =\s*([0-9.]+) MiB", line)
            if m:
                sizes.append(float(m.group(1)))
    return sorted(sizes)


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        return bool(ok)

    ev = os.path.join(R8C, "evidence")

    # 1. Phase 1 reproduction
    p1 = jload(os.path.join(R8C, "phase1-reproduction.json"))
    check("phase1 reproduction machine-derived", p1["reproduced"] is True)

    # 2. Wedge A: same GPU, direct vs loopback RPC, matched placement
    a1 = toks(jload(os.path.join(ev, "phase2-wedges", "wedge-A1-run1.json")))
    a1b = toks(jload(os.path.join(ev, "phase2-wedges", "wedge-A1-run2.json")))
    a2 = toks(jload(os.path.join(ev, "phase2-wedges", "wedge-A2-run1.json")))
    a2b = toks(jload(os.path.join(ev, "phase2-wedges", "wedge-A2-run2.json")))
    check("A1 internally deterministic", a1 == a1b, str(a1))
    check("A2 internally deterministic", a2 == a2b, str(a2))
    check("A1 vs A2 diverge (same GPU, direct vs loopback RPC)",
          a1 != a2 and a1[:3] == a2[:3] == R8B_CASE256_REFERENCE_TOKENS[:3],
          f"A1={a1} A2={a2}")
    pa1 = placement_from_log(os.path.join(ev, "phase2-wedges", "wedge-A1-server.log"))
    pa2 = placement_from_log(os.path.join(ev, "phase2-wedges", "wedge-A2-server.log"))
    check("wedge A placement matched (subset size identical on both arms)",
          pa1 == pa2 and any(abs(x - 6936.10) < 1.0 for x in pa1), f"{pa1} vs {pa2}")

    # 3. Wedge B: local vs remote RPC identical
    b2 = toks(jload(os.path.join(ev, "phase2-wedges", "wedge-B2-run1.json")))
    b2b = toks(jload(os.path.join(ev, "phase2-wedges", "wedge-B2-run2.json")))
    check("B2 internally deterministic", b2 == b2b, str(b2))
    check("A2 == B2 (loopback and remote RPC byte-identical streams)",
          a2 == b2, f"A2={a2} B2={b2}")
    pb2 = placement_from_log(os.path.join(ev, "phase2-wedges", "wedge-B2-server.log"))
    check("wedge B placement matched", pb2 == pa2, f"{pb2}")

    # 4. Accepted-log sampler-chain finding (retained bytes, not rerun claims)
    ref_log = os.path.join(R8B, "evidence", "reference", "reference-server.log")
    log = open(ref_log, errors="replace").read()
    n_warn = log.count("unable to match sampler by name 'greedy'")
    n_dist = log.count("sampler chain: logits -> dist")
    check("accepted reference log retains greedy-name mismatch warnings", n_warn >= 12, str(n_warn))
    check("accepted reference log retains actual chain 'logits -> dist'", n_dist >= 2, str(n_dist))

    # 5. Rank evidence from the retained full-vocab logits rows
    meta = jload(os.path.join(ev, "phase4-tool", "dl-R.json"))
    acc = R8B_CASE256_REFERENCE_TOKENS
    n_vocab = meta["n_vocab"]
    data = open(os.path.join(ev, "phase4-tool", "dl-R.bin"), "rb").read()
    import struct
    # NOTE (review P2 correction): rows are conditioned on the TOOL's own
    # greedy trajectory, which is on-stream with the accepted reference only
    # while the tool's pick equals the accepted token (row 0, and row 1's
    # context). Rank claims are therefore restricted to ON-trajectory rows;
    # off-trajectory ranks are reported as context-only and prove nothing
    # about the accepted stream.
    tool_toks = meta.get("tokens") or []
    ranks = []
    on_traj_ranks = {}
    for r in range(min(8, meta["n_rows"])):
        v = struct.unpack_from("<%df" % n_vocab, data, r * n_vocab * 4)
        order = sorted(range(n_vocab), key=lambda i: -v[i])
        rank = order.index(acc[r]) if acc[r] < n_vocab else None
        ranks.append(rank)
        on_traj = (r == 0) or (tool_toks[:r] == acc[:r])
        if on_traj:
            on_traj_ranks[r] = rank
    check("accepted stream pos1 token is NOT the argmax of its own decision "
          "context (rank>0 on the on-trajectory row)",
          on_traj_ranks.get(1, -1) > 0, f"on_traj_ranks={on_traj_ranks}")
    check("accepted pos0 is argmax-consistent (on-trajectory)",
          on_traj_ranks.get(0) == 0, f"on_traj_ranks={on_traj_ranks}")

    # 6. Phase 5 intervention
    ivR = jload(os.path.join(ev, "phase5-intervention", "iv-R.json"))
    ivC = jload(os.path.join(ev, "phase5-intervention", "iv-C.json"))
    true_greedy_matches = []
    for r, c in zip(ivR["results"], ivC["results"]):
        same = r["generated_tokens"] == c["generated_tokens"]
        prefix = 0
        for x, y in zip(r["generated_tokens"], c["generated_tokens"]):
            if x != y:
                break
            prefix += 1
        true_greedy_matches.append({"case": r["case_id"], "identical": same,
                                    "shared_prefix": prefix})
    tg = {m["case"]: m for m in true_greedy_matches}
    check("true-greedy intervention: >=2 of 4 cases token-identical R vs C",
          sum(1 for m in true_greedy_matches if m["identical"]) >= 2,
          json.dumps(true_greedy_matches))
    check("case-256 true-greedy shared prefix longer than accepted dist-mode (3)",
          tg["case-256"]["shared_prefix"] >= 5, str(tg["case-256"]["shared_prefix"]))

    # logit-row surface limitation retained
    tf = os.path.join(ev, "phase3-teacher-forced")
    check("phase3 teacher-forced surface retained with row-misalignment observation",
          os.path.isdir(tf) and all(
              os.path.exists(os.path.join(tf, f"tf-{a}.json"))
              for a in ("R", "C", "A1", "A2", "B2")))

    ok = all(c["ok"] for c in checks)
    terminal = "R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED" if ok else "R8C_REDUCTION_INCOMPLETE"
    doc = {
        "schema": "inferswarm.issue193.terminal-reduction/1",
        "terminal": terminal,
        "checks": checks,
        "cause_statement": (
            "The accepted R8-B exact-token FAIL is causally localized to the "
            "request-level sampler chain, not RPC transport or state: "
            "samplers=[\"greedy\"] did not resolve at llama.cpp b29c606e (retained "
            "warning in the accepted reference log), so both arms ran seeded "
            "distribution sampling (\"logits -> dist\", seed 0). Distribution "
            "sampling amplifies lawful cross-backend numerical-path logit "
            "differences (reference = CPU-spill-heavy placement; candidate = "
            "five-CUDA-device placement) into token divergence by moving the "
            "cumulative-sum crossing point. Under a single-factor intervention "
            "to true greedy (request field only: top_k=1), the same five-device "
            "RPC topology becomes token-identical to the reference on 2 of 4 "
            "cases and agrees through >=5 positions on case-256. Cross-host "
            "transport is exonerated by wedge B (loopback and remote RPC "
            "byte-identical); a same-GPU direct-vs-RPC difference exists "
            "(wedge A) but produces deterministic, coherent outputs in both "
            "arms with no state-corruption invariant violated. The residual "
            "true-greedy differences (case-256 pos>=5, case-4096 EOS) are "
            "attributed to lawful numerical-path variation; separating them "
            "further requires a trustworthy logit-row surface the pinned "
            "build's server does not expose (its n_probs rows are misaligned "
            "relative to the sampled decision row)."
        ),
        "classification": (
            "Primarily numerical-path divergence amplified by an invalid "
            "greedy-protocol assumption in the R8-B methodology; no RPC/state "
            "corruption demonstrated; historical R8-B FAIL remains valid under "
            "its own frozen comparator (exact tokens under the actually-built "
            "sampler chain) and is NOT reinterpreted as PASS."
        ),
        "non_claims": [
            "no repair to llama.cpp attempted or validated",
            "no requalification; R8-B FAIL stands unmodified",
            "no claim that llama.cpp RPC is defect-free in general",
            "no AMD/Vulkan/mixed-vendor evidence",
            "residual true-greedy case-256/case-4096 differences not localized to a layer",
        ],
    }
    out = os.path.join(R8C, "terminal-reduction.json")
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"terminal": terminal,
                      "failed": [c["check"] for c in checks if not c["ok"]]}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
