"""Issue #195 R8-D: frozen authority constants for the true-greedy
cross-host RPC requalification campaign.

Every correctness-bearing producer in this campaign binds to the constants
frozen here. The freeze predates all Phase 2+ model output (see
AUTHORITY-FREEZE.md in this directory).
"""

# Starting point
START_MAIN = "f65b70970a9a10bf57bd58a902fe6e08b588c619"  # accepted R8-C merge
BRANCH = "issue-195-r8d-true-greedy-requal"

# Accepted predecessor terminals (immutable, never rewritten)
R8B_TERMINAL = "R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL"
R8C_TERMINAL = "R8C_QWEN38_RPC_DIVERGENCE_CAUSE_LOCALIZED"

# Evidence namespaces (additive; predecessors byte-preserved)
R8B_DIR = "docs/investigations/qwen38-flash-next-r8-b"
R8C_DIR = "docs/investigations/qwen38-flash-next-r8-c"
R8D_DIR = "docs/investigations/qwen38-flash-next-r8-d"

# Runtime authority (identical to accepted R8-B/R8-C pins; re-hashed fresh
# on every participating host at R8-D freeze — see evidence/host-inventory/)
LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
BINARY_SHA256 = {
    "llama-cli": "3f6b0ed46f42e5c614e4fb4d36b91c56061dfff96096bbb1e4bc0044bd95e77f",
    "llama-server": "de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411",
    "ggml-rpc-server": "a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9",
}

# Model authority (accepted R8-A pins, re-verified at R8-D freeze)
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

# Frozen topology (re-observed 2026-09-15; GPU UUID/BDF set identical to
# accepted R8-B; driver drift on inferswarm03 recorded in host inventory)
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
DRIVER_AT_FREEZE = {
    "inferswarm01": "610.57.04",
    "inferswarm03": "615.71.09",  # advanced from 610.57.04 since R8-B; applicability-audited
    "inferswarm04": "610.57.04",
}

# Canonical R8-D request contract (frozen; see issue Phase 1)
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

# Accepted R8-B fixture ladder — exact prompt token IDs consumed verbatim
FIXTURE_LADDER_PATH = (
    R8B_DIR + "/evidence/reference/fixture-ladder.json")
FIXTURE_CASES = ["case-256", "case-1024", "case-3072", "case-4096"]
FIXTURE_LENGTHS = {"case-256": 256, "case-1024": 1022,
                   "case-3072": 3077, "case-4096": 4097}

# Repeat / restart contract
REFERENCE_REPEATS = 3
CANDIDATE_REPEATS = 3
SENTINELS = ["case-256", "case-4096"]

# Terminals (exactly one)
TERMINAL_PASS = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_PASS"
TERMINAL_FAIL = "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL"
TERMINAL_BLOCKED = "R8D_EVIDENCE_BLOCKED"

# Campaign identity
CAMPAIGN_ID = "issue195-r8d-true-greedy-requal-v1"
