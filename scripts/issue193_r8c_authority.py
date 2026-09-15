#!/usr/bin/env python3
"""Issue #193 (R8-C): diagnosis authority constants and freeze verification.

R8-C localizes the accepted R8-B exact-token divergence (reference single-host
non-RPC vs candidate cross-host RPC, llama.cpp b29c606e, Qwen3.8-Flash-Next
UD-IQ1_S). This module is the single source of frozen identities for the
diagnosis: predecessor merge, runtime binaries, model split, host inventory,
and the prospectively frozen experiment matrix. Nothing here may be edited
after the first new diagnostic model output (see EXPERIMENT-MATRIX freeze).
"""

from __future__ import annotations

import hashlib
import json
import os

# ---------------------------------------------------------------------------
# Accepted predecessor (immutable R8-B authority — consumed, never rewritten)
# ---------------------------------------------------------------------------

R8B_MERGE_SHA = "3448cc7d63853079fff2520952c2b65d586ae3e4"
R8B_ISSUE = 191
R8B_PR = 192
R8B_TERMINAL = "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL"
R8B_EVIDENCE_DIR = "docs/investigations/qwen38-flash-next-r8-b"
R8A_MERGE_SHA = "938af774878f562314e920007846f9f2bb611ec2"

# Exact accepted R8-B case-256 outputs (from evidence/reference/reference-run-1.json
# and evidence/candidate/candidate-run-1.json; byte-anchored by the R8-B MANIFEST).
R8B_CASE256_REFERENCE_TOKENS = [561, 40554, 32039, 28056, 3486, 271, 248068, 198]
R8B_CASE256_CANDIDATE_TOKENS = [561, 40554, 32039, 25082, 271, 248068, 271, 248069]
R8B_CASE256_FIRST_DIVERGENCE_POSITION = 3  # 0-based generated-token index

# ---------------------------------------------------------------------------
# Frozen runtime + model authority (identical bytes to accepted R8-B)
# ---------------------------------------------------------------------------

LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
LLAMA_CPP_TAG = "v0.4.1"
BINARIES_SHA256 = {
    "llama-cli": "3f6b0ed46f42e5c614e4fb4d36b91c56061dfff96096bbb1e4bc0044bd95e77f",
    "llama-server": "de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411",
    "ggml-rpc-server": "a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9",
}
BINARY_PATH = "/home/hermes/llama.cpp/build-v041/bin"

MODEL_DIR = "/srv/models/qwen38-ud-iq1-s"
SPLIT_MEMBERS_SHA256 = {
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf":
        "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf":
        "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf":
        "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
}

# Hosts and exact GPU identities (fresh raw inventory 2026-09-15, retained
# under evidence/host-inventory/).
HOSTS = {
    "inferswarm01": {
        "lan": "10.0.0.141",
        "gpus": [
            {"bdf": "00000000:02:00.0", "uuid": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
             "name": "NVIDIA GeForce RTX 3060", "vram_mib": 12288},
            {"bdf": "00000000:03:00.0", "uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
             "name": "NVIDIA GeForce RTX 3060", "vram_mib": 12288},
        ],
        "driver": "610.57.04",
    },
    "inferswarm03": {
        "lan": "10.0.0.219",
        "gpus": [
            {"bdf": "00000000:01:00.0", "uuid": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
             "name": "NVIDIA GeForce RTX 3060", "vram_mib": 12288},
            {"bdf": "00000000:03:00.0", "uuid": "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0",
             "name": "NVIDIA GeForce RTX 3060", "vram_mib": 12288},
        ],
        "driver": "610.57.04",
    },
    "inferswarm04": {
        "lan": "10.0.0.204",
        "gpus": [
            {"bdf": "00000000:01:00.0", "uuid": "GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03",
             "name": "NVIDIA GeForce RTX 3090", "vram_mib": 24576},
        ],
        "driver": "610.57.04",
    },
}

# ---------------------------------------------------------------------------
# Prospectively frozen diagnostic experiment matrix (Phase 0 freeze — BEFORE
# any new diagnostic model output). Single-factor wedges on the case-256
# sentinel. Arms differ ONLY in the named execution factor.
# ---------------------------------------------------------------------------

SENTINEL_CASE = "case-256"

EXPERIMENT_MATRIX = {
    "schema": "inferswarm.issue193.experiment-matrix/1",
    "sentinel": SENTINEL_CASE,
    "design_rule": (
        "Each wedge is a pair of arms differing in exactly one execution "
        "factor. Client host is inferswarm01 for every arm; model bytes, "
        "binaries, prompt token IDs, sampling (greedy, temp 0, seed 0), "
        "context size, and the PLE lazy host-side default are identical "
        "across all arms. Tensor placement is pinned per-arm and retained "
        "from load logs; auto-placement drift between arms of a wedge is a "
        "match failure, not a result."
    ),
    "phase1_reproduction": {
        "arm-R8C-R": (
            "Unmodified accepted R8-B reference: llama-server on "
            "inferswarm01, no --rpc, default fit (CUDA0+CUDA1 + CPU spill, "
            "PLE lazy host). Must reproduce R8B reference case-256 tokens "
            "exactly."
        ),
        "arm-R8C-C": (
            "Unmodified accepted R8-B candidate: llama-server on "
            "inferswarm01 with --rpc 10.0.0.219:50052,10.0.0.219:50053,"
            "10.0.0.204:50052 (rpc-servers on 03 g0/g1 and 04 g0). Must "
            "reproduce R8B candidate case-256 tokens exactly."
        ),
    },
    "wedge_A_direct_vs_loopback_rpc": {
        "purpose": "Isolate the RPC process/serialization path from GPU identity and network.",
        "arm-A1": (
            "Direct CUDA: llama-server on inferswarm01, no --rpc, "
            "-ngl 99 --override-tensor 'blk\\.(3[3-9]|[45][0-9])\\..*=CUDA0' "
            "style pinned small offload subset (frozen below), remainder CPU. "
            "Exact frozen subset recorded from load logs before arm A2 runs."
        ),
        "arm-A2": (
            "Same physical GPU (inferswarm01 CUDA0), same exact tensor "
            "subset, exposed via local ggml-rpc-server on 127.0.0.1 loopback; "
            "client uses --rpc 127.0.0.1:50052 only for that subset, "
            "remainder CPU identical to A1."
        ),
        "single_factor": "execution path of one exact tensor subset: in-process direct vs through ggml-rpc serialization over loopback TCP",
    },
    "wedge_B_local_vs_remote_rpc": {
        "purpose": "Pressure cross-host transport while minimizing device/kernel differences.",
        "arm-B1": (
            "ggml-rpc-server on inferswarm01 CUDA0 (127.0.0.1 or LAN IP), "
            "client pinned to the same exact tensor subset as wedge A."
        ),
        "arm-B2": (
            "ggml-rpc-server on inferswarm03 GPU0 (matched RTX 3060, same "
            "driver 610.57.04, same binary hash, same CUDA arch 8.6), same "
            "exact tensor subset as B1."
        ),
        "single_factor": "RPC endpoint locality: same-device loopback/LAN vs cross-host LAN, matched 3060-class GPU",
    },
    "wedge_C_full_topology": {
        "purpose": "Establish whether the localized wedge finding scales to the accepted five-device R8-B topology.",
        "arm-C1": "arm-R8C-C reproduction (already required by Phase 1).",
        "single_factor": "relation-only wedge; no new single-factor claim",
    },
    "phase3_teacher_forced_logprob_capture": {
        "method": (
            "llama-server /completion with n_probs=20 (greedy samplers, "
            "identical token-ID prompt) on each arm at the case-256 shared "
            "prefix (positions 0..3); retain selected token, top-K ids, "
            "top-K logprobs, logit margin winner-vs-runner-up for reference "
            "winner and candidate values at the same ids. Frozen reporting "
            "buckets (pre-observation): near-tie margin < 0.10 logit; "
            "moderate 0.10-1.0; large > 1.0. Buckets are descriptive only; "
            "no threshold converts R8-B to PASS."
        ),
        "frozen_buckets": {"near_tie_lt": 0.10, "moderate_le": 1.0},
    },
    "interpretation_rules": {
        "numerical_path": (
            "Placement/device changes flip the token with coherent "
            "next-token distributions and a retained logit-margin "
            "explanation; no transport/state invariant violated."
        ),
        "rpc_state_defect": (
            "Requires a matched control demonstrating divergence "
            "introduced at a specific RPC/state boundary while the same "
            "computation without that boundary does not diverge."
        ),
    },
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_r8b_bundle_unchanged(repo_root: str) -> dict:
    """Re-verify the accepted R8-B evidence bundle byte-preservation via its
    own MANIFEST (fail-closed)."""
    man = os.path.join(repo_root, R8B_EVIDENCE_DIR, "MANIFEST.sha256")
    problems = []
    checked = 0
    with open(man) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, rel = line.split(None, 1)
            rel = rel.strip()
            if rel == "MANIFEST.sha256":
                continue
            p = os.path.join(repo_root, rel)
            if not os.path.exists(p):
                problems.append(f"missing {rel}")
                continue
            if sha256_file(p) != digest:
                problems.append(f"digest mismatch {rel}")
            checked += 1
    return {"checked": checked, "problems": problems,
            "ok": not problems}


def load_json(path: str):
    with open(path) as fh:
        return json.load(fh)


TERMINALS = (
    "R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED",
    "R8C_QWEN38_NUMERICAL_PATH_DIVERGENCE_LOCALIZED",
    "R8C_QWEN38_DIAGNOSIS_PARTIAL",
    "R8C_EVIDENCE_BLOCKED",
)
