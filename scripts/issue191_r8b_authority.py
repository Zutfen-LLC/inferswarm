"""Issue #191 (R8-B) campaign authority constants and loading.

Binds the campaign to the accepted R8-A authorities and the frozen R8-B
selections.  Every correctness-bearing script in this campaign imports its
identity constants from here; none of them are re-typed elsewhere.
"""
import hashlib
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Accepted predecessor (Issue #189 / PR #190, merged as below).  Consume the
# retained R8-A evidence; never restate its derivations.
# ---------------------------------------------------------------------------
R8A_TERMINAL = "R8A_QWEN38_RUNTIME_PREREQUISITE"
R8A_MERGE = "938af774878f562314e920007846f9f2bb611ec2"
R8A_DIR = REPO_ROOT / "docs" / "investigations" / "qwen38-flash-next-r8-a"

# Official model authority (R8-A source-findings.md)
QWEN_OFFICIAL_REPO = "Qwen/Qwen3.8-Flash-Next"
QWEN_OFFICIAL_REV = "de4b8e4d43b917e7706784d8bb445c9af86a3540"

# GGUF conversion authority
UNSLOTH_REPO = "unsloth/Qwen3.8-Flash-Next-GGUF"
UNSLOTH_REV = "38bb39ee97821de2c9009abb7e93950eec396e66"

REPRESENTATION = "UD-IQ1_S"
TOTAL_ENCODED_BYTES = 72_546_461_344  # 67.56 GiB

# Exact split members, loaded verbatim from the accepted R8-A header census.
def _load_r8a_header_census() -> dict:
    return json.loads((R8A_DIR / "gguf-header-census.json").read_text())

def split_members() -> list:
    """Exact accepted split set as (path, bytes, hf_lfs_sha256) rows."""
    census = _load_r8a_header_census()
    return [
        {
            "path": f["path"],
            "object_bytes": f["object_bytes"],
            "hf_lfs_sha256": f["hf_lfs_sha256"],
            "url": f["url"],
        }
        for f in census["files"]
    ]

# Exact PLE / n-gram tensor identity (R8-A header census).
PLE_TENSOR = "per_layer_token_embd.weight"
PLE_SHAPE = [160, 320001536]
PLE_TYPE = "GGML_TYPE_IQ4_NL"
PLE_ENCODED_BYTES = 28_800_138_240  # 26.82 GiB

# ---------------------------------------------------------------------------
# Frozen llama.cpp runtime selection (Phase 1 freeze, this campaign).
# ---------------------------------------------------------------------------
LLAMA_CPP_REPO = "ggml-org/llama.cpp"
LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"  # tag v0.4.1
LLAMA_CPP_TAG = "v0.4.1"

# #27993 repair ancestry (PR #27960 merge commit, verified ancestor of the
# selection by GitHub compare on 2026-09-15).
REPAIR_27960_MERGE = "73f56d105bb6b5aeb37d0c7dcc6a7d58c2f7974a"
REPAIR_27960_COMMIT = "a273d22e142b9ad253a09d7b76d4d24ba64eb9bc"

# qwen4exp support commits proven ancestral to the selection.
QWEN4EXP_SUPPORT_COMMITS = [
    "6c84c7d5d8833c6e0df69628f75a0f599797934e",  # model: add Qwen3.8-Flash-Next (#27742)
    "36b10154383b60eb15baac2c7a40d2a5f784faa7",  # qwen4exp: fix seq_cp, position keying, tests (#27941)
    "09412af38a9fe328da2ed452a40f310eea350290",  # qwen4exp: sum indexer heads by slices (#28023)
    "0eadefebd3f8f92a86d634a0e5b8fffc9dc792c0",  # qwen4exp: recurrent state rollback (#28123)
    "6fe74980162af0ed5e559870d5deccafaa034e7c",  # qwen4exp: reduce graph splits (#27880)
]

# ---------------------------------------------------------------------------
# Frozen physical topology (Phase 3 freeze; host names only here — the full
# device/BDF/UUID/nic identities live in the topology freeze record).
# ---------------------------------------------------------------------------
CLIENT_HOST = "inferswarm01"      # llama-cli client + reference arm host
RPC_HOSTS = ["inferswarm03", "inferswarm04"]
CAMPAIGN_HOSTS = [CLIENT_HOST] + RPC_HOSTS

# Predeclared capacity-only topology ladder (Phase 3).  A load failure with
# ZERO generated candidate tokens may advance rungs ONLY for demonstrated
# static memory insufficiency.
TOPOLOGY_LADDER = [
    "rung-0: client=inferswarm01 (2x RTX 3060 12GiB, PLE host/CPU), rpc1=inferswarm03 (2x RTX 3060 12GiB), rpc2=inferswarm04 (RTX 3090 24GiB)",
    "rung-1: adds inferswarm01 GPU1 fully into client pool if 01 weight capacity is insufficient (no host change)",
    "rung-2: adds inferswarm03 GPU1 as separate rpc endpoint if 03 single-GPU capacity is insufficient",
]

# Fixture ladder (Phase 4 freeze): approximate rendered token targets; exact
# frozen token IDs derived with the pinned tokenizer before execution and
# retained in the fixture record.
FIXTURE_TARGET_TOKENS = [256, 1024, 3072, 4096]
COMMITTED_TOKENS_PER_CASE = 8  # greedy/deterministic

# Sentinel cases for repeatability (Phase 6): one short + one >2K.
SENTINEL_CASES = ["case-256", "case-4096"]
REPEATS_PER_SENTINEL_PER_ARM = 3


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
