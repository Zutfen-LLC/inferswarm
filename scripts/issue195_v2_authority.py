"""Issue #195 R8-D v2: frozen authority constants for the corrected
true-greedy cross-host RPC requalification campaign (v2).

v1 (campaign issue195-r8d-true-greedy-requal-v1) was superseded: its
producer did not retain per-case request/response bytes and could not
mechanically prove the reference was frozen before candidate execution.
v1 evidence bytes are preserved byte-for-byte and never rewritten; this
module is the fresh additive v2 authority required before any new
correctness-bearing model output.

Every v2 correctness-bearing producer binds to the constants frozen
here. The v2 authority freeze (producer bytes + this module + fresh
identity evidence) is committed and pushed BEFORE any v2 Phase-2+
model output (see AUTHORITY-FREEZE-V2.md).
"""

# Starting point (unchanged from v1 freeze; re-verified at v2 freeze)
START_MAIN = "f65b70970a9a10bf57bd58a902fe6e08b588c619"  # accepted R8-C merge
BRANCH = "issue-195-r8d-true-greedy-requal"
SUPERSEDED_V1_CAMPAIGN = "issue195-r8d-true-greedy-requal-v1"
SUPERSEDED_V1_TERMINAL = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL"

# Accepted predecessor terminals (immutable, never rewritten)
R8B_TERMINAL = "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL"
R8C_TERMINAL = "R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED"

# Evidence namespaces (additive; v1 and predecessors byte-preserved)
R8B_DIR = "docs/investigations/qwen38-flash-next-r8-b"
R8C_DIR = "docs/investigations/qwen38-flash-next-r8-c"
R8D_DIR = "docs/investigations/qwen38-flash-next-r8-d"
R8D_V2_DIR = "docs/investigations/qwen38-flash-next-r8-d-v2"
R8D_V2_EV = R8D_V2_DIR + "/evidence"

# Runtime authority (identical to accepted R8-B/R8-C/v1 pins; re-hashed
# fresh on every participating host at v2 freeze — v2/evidence/host-inventory/)
LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
BINARY_SHA256 = {
    "llama-cli": "3f6b0ed46f42e5c614e4fb4d36b91c56061dfff96096bbb1e4bc0044bd95e77f",
    "llama-server": "de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411",
    "ggml-rpc-server": "a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9",
}

# Model authority (accepted R8-A pins, re-verified at v2 freeze)
MODEL_DIR_01 = "/srv/models/qwen38-ud-iq1-s"
SPLIT_SHA256 = {
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf":
        "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf":
        "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf":
        "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
}
SPLIT_TOTAL_BYTES = 72546461344

# Frozen topology (re-observed fresh at v2 freeze; GPU UUID/BDF set
# identical to accepted R8-B/v1; driver drift on inferswarm03 recorded
# in v2/evidence/host-inventory/)
TOPOLOGY = {
    "client": {"host": "inferswarm01", "ip": "10.0.0.141", "gpus": [
        {"bdf": "0000:02:00.0", "uuid": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"},
        {"bdf": "0000:03:00.0", "uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55"},
    ]},
    "rpc1": {"host": "inferswarm03", "ip": "10.0.0.219", "gpus": [
        {"bdf": "0000:01:00.0", "uuid": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176"},
        {"bdf": "0000:03:00.0", "uuid": "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0"},
    ]},
    "rpc2": {"host": "inferswarm04", "ip": "10.0.0.204", "gpus": [
        {"bdf": "0000:01:00.0", "uuid": "GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03"},
    ]},
}
# Frozen candidate RPC endpoint set (candidate launch must match exactly)
CANDIDATE_RPC_ENDPOINTS = ["10.0.0.219:50052", "10.0.0.219:50053",
                           "10.0.0.204:50052"]
REFERENCE_PORT = 8321   # single-host non-RPC arm, inferswarm01 loopback
CANDIDATE_PORT = 8323   # 5-device RPC arm client, inferswarm01 loopback
DRIVER_AT_FREEZE = {
    "inferswarm01": "610.57.04",
    "inferswarm03": "615.71.09",  # applicability-audited at v1 and v2 freeze
    "inferswarm04": "610.57.04",
}

# Canonical request contract (frozen; identical semantics to v1/Phase 1 —
# deterministically serialized by the v2 producer; n_probs is FORBIDDEN)
REQUEST_CONTRACT = {
    "samplers": ["top_k"],
    "top_k": 1,
    "temperature": 0.0,
    "seed": 0,
    "cache_prompt": False,
    "stream": False,
    "return_tokens": True,
    "n_predict": 8,
}
FORBIDDEN_REQUEST_KEYS = ("n_probs", "probs", "min_p", "top_p", "typical_p")

# Accepted R8-B fixture ladder — exact prompt token IDs consumed verbatim
FIXTURE_LADDER_PATH = (
    R8B_DIR + "/evidence/reference/fixture-ladder.json")
FIXTURE_LADDER_SHA256 = "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db"
FIXTURE_CASES = ["case-256", "case-1024", "case-3072", "case-4096"]
FIXTURE_LENGTHS = {"case-256": 256, "case-1024": 1022,
                   "case-3072": 3077, "case-4096": 4097}

# Repeat / restart contract
REFERENCE_REPEATS = 3
CANDIDATE_REPEATS = 3
SENTINELS = ["case-256", "case-4096"]

# Terminals (exactly one; identical strings to v1)
TERMINAL_PASS = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_PASS"
TERMINAL_FAIL = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL"
TERMINAL_BLOCKED = "R8D_EVIDENCE_BLOCKED"

# Campaign identity (v2)
CAMPAIGN_ID = "issue195-r8d-true-greedy-requal-v2"

# Evidence record schema
RUN_SCHEMA = "inferswarm.issue195.ladder-run-v2/2"

# ---------------------------------------------------------------------------
# v2 freeze pins. Producer SHA-256 pins are the authority-freeze commit
# content; the reference-freeze pin (FROZEN_REFERENCE_SHA256 and
# REFREEZE_COMMIT) is authored by scripts/issue195_v2_freeze_reference.py
# into v2/evidence/reference/REFREEZE.json at the dedicated immutable
# reference-freeze commit. Candidate execution fails closed unless every
# pin below matches the executing bytes/history.
# ---------------------------------------------------------------------------
PRODUCER_SHA256 = {}  # filled by scripts/issue195_v2_freeze_reference? no —
# filled at authority freeze; see producer-hashes.json in R8D_V2_DIR.

# Producers whose bytes are pinned at the v2 authority freeze (paths
# relative to repo root). The v1 sampler probe is pinned UNCHANGED from
# the accepted v1 producer set and reused byte-identical for v2 probes.
V2_PRODUCERS = (
    "scripts/issue195_v2_authority.py",
    "scripts/issue195_v2_run_ladder.py",
    "scripts/issue195_v2_freeze_reference.py",
    "scripts/issue195_v2_terminal_reduction.py",
    "scripts/issue195_v2_negative_controls.py",
    "scripts/issue195_v2_manifest.py",
    "scripts/issue195_sampler_probe.py",
    "scripts/issue195_v2_launch.py",
)

# Correctness-bearing path prefixes: a post-refreeze HEAD may advance only
# with changes outside ALL of these (fail closed otherwise).
CORRECTNESS_PREFIXES = ("scripts/issue195", "tests/test_issue195",
                        R8D_V2_DIR + "/evidence",
                        R8D_DIR + "/AUTHORITY-FREEZE")


def producer_pins_ok(repo_root):
    """Every V2 producer file matches its pinned digest (dict source:
    v2/producer-hashes.json, itself pinned by the freeze commits)."""
    import hashlib
    import json
    import os
    pins = json.load(open(os.path.join(repo_root, R8D_V2_DIR,
                                       "producer-hashes.json")))
    for rel, want in pins.items():
        p = os.path.join(repo_root, rel)
        if not os.path.exists(p):
            return False, rel + " missing"
        got = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if got != want:
            return False, rel + " digest mismatch"
    return True, "ok"
