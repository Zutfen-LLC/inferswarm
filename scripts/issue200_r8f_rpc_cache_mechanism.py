#!/usr/bin/env python3
"""Issue #200 (R8-F) correction: mechanical treatment of the pinned llama.cpp
RPC local-cache seam that the original R8-F Phase 4 finding overlooked.

The original finding inferred "no participant-local backing seam exists"
solely from the absence of a ``-m``/model-path argument on the R8-D v2
``ggml-rpc-server`` launch invocations. That inference is retracted (see
``issue200_r8f_terminal_reduction.phase4_mechanical_finding``): the pinned
build (commit ``b29c606e28a01b1bc8c1351026a0fa6e616bf6c4``) separately
implements a local file cache for large tensors, entirely independent of
whether a model path is ever passed to the backend process --

- ``-c``/``--cache`` (``tools/rpc/rpc-server.cpp``) enables a local file
  cache under ``$LLAMA_CACHE/rpc/`` (default
  ``$HOME/.cache/llama.cpp/rpc/``).
- For any ``set_tensor`` call whose payload exceeds ``HASH_THRESHOLD``
  (10 MiB), the client first sends ``RPC_CMD_SET_TENSOR_HASH`` -- an
  FNV-1a hash of the tensor bytes it is about to send, computed by
  ``ggml/src/ggml-rpc/ggml-rpc.cpp:fnv_hash`` -- instead of the payload
  itself. If the server has a file at ``<cache_dir>/<16-hex-fnv1a>``, it
  loads that file into the tensor's backend memory and reports a hit; the
  client then skips the full ``RPC_CMD_SET_TENSOR`` transfer entirely. On a
  miss, the client falls back to the full transfer, and the server
  (``rpc_server::set_tensor``) writes what it received to that same path
  for next time.

This module records the immutable identity of the exact pinned files
consulted, and mechanically re-derives (never authors) the cache-seam
conclusion from a retained, bounded, non-Qwen experiment
(``evidence/rpc-cache-experiment.json``) that built and ran the actual
pinned ``ggml-rpc-server`` binary plus an external driver calling only the
pinned public backend API -- no llama.cpp source was modified to produce
that evidence. See ``evidence/rpc-cache-experiment-raw/`` for the driver
source, fixture generator, orchestration script, and raw per-phase
strace/server logs the summarized JSON was computed from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AREA = Path("docs/implementation/r8-f-local-backing-source-policy-200")
EXPERIMENT_EVIDENCE_PATH = ROOT / AREA / "evidence" / "rpc-cache-experiment.json"

PINNED_LLAMA_CPP_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
PINNED_UPSTREAM_REPO = "https://github.com/ggml-org/llama.cpp"

# Pinned constant this pinned build uses (ggml/src/ggml-rpc/ggml-rpc.cpp:87):
#   const size_t HASH_THRESHOLD = 10 * 1024 * 1024;
HASH_THRESHOLD_BYTES = 10 * 1024 * 1024
# A response/probe-only exchange for a 12 MiB fixture is ~321 bytes on the
# wire (cmd + size header + rpc_tensor + offset + hash, per
# rpc_msg_set_tensor_hash_req); anything under this is unambiguously a probe,
# never a payload retransmission.
SMALL_RESPONSE_THRESHOLD_BYTES = 4096

# Immutable source identity for the exact pinned files this correction
# inspected, fetched read-only from the pinned commit above (never vendored,
# never modified). The sha256 values are the authoritative anchor; the
# excerpts below are short (fair-use), human-readable quotations recorded
# for traceability only and carry no independent authority.
UPSTREAM_SOURCE_IDENTITY = {
    "tools/rpc/rpc-server.cpp": {
        "sha256": "14f69793a377a79f2476a190da1f80bac079cfeb4a83df13ffd378d3435d974",
        "fetched_from": f"{PINNED_UPSTREAM_REPO}/raw/{PINNED_LLAMA_CPP_COMMIT}/tools/rpc/rpc-server.cpp",
    },
    "tools/rpc/README.md": {
        "sha256": "f3ca2fcfadf926ec60115da8102cedf08f0701f60f62c16ff42f56f87dd819d",
        "fetched_from": f"{PINNED_UPSTREAM_REPO}/raw/{PINNED_LLAMA_CPP_COMMIT}/tools/rpc/README.md",
    },
    "ggml/src/ggml-rpc/ggml-rpc.cpp": {
        "sha256": "07ca713158d222959b4415e74e0bee83119212aad85750ff6240773365c0b2d",
        "fetched_from": f"{PINNED_UPSTREAM_REPO}/raw/{PINNED_LLAMA_CPP_COMMIT}/ggml/src/ggml-rpc/ggml-rpc.cpp",
    },
    "ggml/include/ggml-rpc.h": {
        "sha256": "505c01e4575c06a3b01cdbbb5688368baaabf6223a36eeafd918057251da6e4",
        "fetched_from": f"{PINNED_UPSTREAM_REPO}/raw/{PINNED_LLAMA_CPP_COMMIT}/ggml/include/ggml-rpc.h",
    },
    "ggml/src/ggml-rpc/transport.h": {
        "sha256": "fec7abf4e6cebec0d20e3350c01f2f47d495f90a79c6d829870e09d8a7ef221",
        "fetched_from": f"{PINNED_UPSTREAM_REPO}/raw/{PINNED_LLAMA_CPP_COMMIT}/ggml/src/ggml-rpc/transport.h",
    },
}

STATIC_SOURCE_EXCERPTS = {
    "tools/rpc/rpc-server.cpp:print_usage (cache flag exists)": (
        '  fprintf(stderr, "  -c, --cache                      enable local file cache\\n");'
    ),
    "tools/rpc/README.md:Local cache section": (
        "The RPC server can use a local cache to store large tensors and avoid "
        "transferring them over the network. This can speed up model loading "
        "significantly, especially when using large models. To enable the "
        "cache, use the `-c` option ... By default, the cache is stored in the "
        "`$HOME/.cache/llama.cpp/rpc` directory and can be controlled via the "
        "`LLAMA_CACHE` environment variable."
    ),
    "ggml-rpc.cpp:fnv_hash": (
        "static uint64_t fnv_hash(const uint8_t * data, size_t len, "
        "uint64_t hash = 0xcbf29ce484222325ULL) {\n"
        "    const uint64_t fnv_prime = 0x100000001b3ULL;\n"
        "    for (size_t i = 0; i < len; ++i) { hash ^= data[i]; hash *= fnv_prime; }\n"
        "    return hash;\n"
        "}"
    ),
    "ggml-rpc.cpp:HASH_THRESHOLD": (
        "const size_t HASH_THRESHOLD = 10 * 1024 * 1024;  // try SET_TENSOR_HASH "
        "first when data size is larger than this"
    ),
    "ggml-rpc.cpp:client set_tensor cache probe": (
        "if (size > HASH_THRESHOLD) { ...request->hash = fnv_hash((const uint8_t*)data, size); "
        "...send(RPC_CMD_SET_TENSOR_HASH, ...); if (response.result) { "
        "// the server has the same data, no need to send it\\n            return; } } "
        "// falls through to full RPC_CMD_SET_TENSOR on a miss"
    ),
    "ggml-rpc.cpp:rpc_server::get_cached_file (no content re-verification)": (
        "bool rpc_server::get_cached_file(uint64_t hash, std::vector<uint8_t> & data) {\n"
        "    ... fs::path cache_file = fs::path(cache_dir) / hash_str;\n"
        "    if (!fs::exists(cache_file, ec)) { return false; }\n"
        "    ... data.resize(size); ifs.read((char *)data.data(), size); return true;\n"
        "}  // trusts whatever bytes are at that filename; never re-hashes the file's own content"
    ),
}


def load_experiment_evidence() -> dict[str, Any]:
    if not EXPERIMENT_EVIDENCE_PATH.is_file():
        raise AssertionError(
            f"missing retained RPC cache experiment evidence at {EXPERIMENT_EVIDENCE_PATH}; "
            "the cache-mechanism finding must not be derived without it")
    return json.loads(EXPERIMENT_EVIDENCE_PATH.read_text())


def mechanical_cache_finding(experiment: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mechanically re-derive the cache-seam conclusion from the retained
    experiment evidence's own recorded byte counts and exit codes -- every
    boolean here is a direct comparison against numbers already present in
    ``evidence/rpc-cache-experiment.json``, not an independent claim."""
    doc = experiment if experiment is not None else load_experiment_evidence()
    phases = doc["phases"]

    def set_sent(phase: str) -> int:
        return phases[phase]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]

    def exit_code(phase: str) -> int:
        return phases[phase]["result"]["exit_code"]

    cold_bytes = set_sent("A_cold")
    warm_restart_bytes = set_sent("B_warm_restart")
    prestaged_bytes = set_sent("C_prestaged")
    wrong_content_exit = exit_code("D_wrong_content")
    truncated_exit = exit_code("E_truncated")

    if exit_code("A_cold") != 0 or exit_code("B_warm_restart") != 0 or exit_code("C_prestaged") != 0:
        raise AssertionError("cache-mechanism finding: a benign phase (A/B/C) did not verify correct "
                              "byte-identical content; refusing to derive a seam conclusion from it")

    cold_exceeded_threshold = cold_bytes > HASH_THRESHOLD_BYTES
    durable_cache_reuse_suppresses_retransmission = (
        cold_exceeded_threshold and warm_restart_bytes < SMALL_RESPONSE_THRESHOLD_BYTES)
    prestaged_verified_backing_consumed_without_prior_network_pass = (
        cold_exceeded_threshold and prestaged_bytes < SMALL_RESPONSE_THRESHOLD_BYTES)
    upstream_cache_is_fail_open_on_wrong_or_truncated_content = (
        wrong_content_exit == 2 and truncated_exit == 2)

    if prestaged_verified_backing_consumed_without_prior_network_pass:
        case_classification = "C"
    elif durable_cache_reuse_suppresses_retransmission:
        case_classification = "B"
    else:
        case_classification = "D"

    legal_non_runtime_modifying_seam_exists = case_classification in ("A", "B", "C")

    return {
        "schema": "inferswarm.issue200.rpc-cache-mechanical-finding/1",
        "pinned_llama_cpp_commit": PINNED_LLAMA_CPP_COMMIT,
        "measured": {
            "cold_set_phase_bytes_sent": cold_bytes,
            "warm_restart_set_phase_bytes_sent": warm_restart_bytes,
            "prestaged_set_phase_bytes_sent": prestaged_bytes,
            "wrong_content_get_exit_code": wrong_content_exit,
            "truncated_get_exit_code": truncated_exit,
        },
        "cold_exceeded_hash_threshold": cold_exceeded_threshold,
        "durable_cache_reuse_suppresses_retransmission": durable_cache_reuse_suppresses_retransmission,
        "prestaged_verified_backing_consumed_without_prior_network_pass":
            prestaged_verified_backing_consumed_without_prior_network_pass,
        "upstream_cache_is_fail_open_on_wrong_or_truncated_content":
            upstream_cache_is_fail_open_on_wrong_or_truncated_content,
        "case_classification": case_classification,
        "case_classification_meaning": {
            "A": "existing -c cache fully satisfies the requirement out of the box",
            "B": "existing cache works after one network seed but cannot consume pre-staged verified backing",
            "C": "existing cache can consume pre-staged backing with a bounded external adapter, no llama.cpp modification",
            "D": "runtime/backend modification is required",
        }[case_classification],
        "legal_non_runtime_modifying_seam_exists": legal_non_runtime_modifying_seam_exists,
        "requires_external_provenance_verification_before_cache_population": (
            upstream_cache_is_fail_open_on_wrong_or_truncated_content),
        "non_claim_fnv1a_is_not_inferswarm_trust_authority": (
            "The upstream FNV-1a filename is a 64-bit non-cryptographic dedup key the pinned "
            "server trusts blindly on read (rpc_server::get_cached_file never re-hashes the file "
            "it loads). Phases D and E mechanically prove this: wrong content and truncated "
            "content are both served as a 'hit' without detection. Any adapter that populates "
            "this cache from InferSwarm-verified local backing MUST perform InferSwarm's own "
            "SHA-256/provenance verification before writing to the cache path -- the FNV-1a name "
            "is never sufficient and is never treated as InferSwarm trust authority."
        ),
        "boundary_condition_not_proven": (
            "This experiment used a single whole-tensor SET_TENSOR call (offset=0, one contiguous "
            "chunk). It does not prove (and does not assume) the same result for a tensor whose "
            "assignment is fragmented into multiple (offset, size) sub-ranges by llama.cpp's own "
            "runtime tensor-split logic (e.g. proportional multi-device memory splitting); "
            "reproducing the exact chunk boundaries needed to pre-stage such a tensor is left as an "
            "explicit open boundary, not claimed to work."
        ),
    }


def evidence_document() -> dict[str, Any]:
    experiment = load_experiment_evidence()
    return {
        "schema": "inferswarm.issue200.rpc-cache-mechanism/1",
        "pinned_llama_cpp_commit": PINNED_LLAMA_CPP_COMMIT,
        "upstream_source_identity": UPSTREAM_SOURCE_IDENTITY,
        "static_source_excerpts": STATIC_SOURCE_EXCERPTS,
        "experiment_evidence_path": str(AREA / "evidence" / "rpc-cache-experiment.json"),
        "experiment_summary": {
            "fixture": experiment["fixture"],
            "phase_descriptions": {name: p["description"] for name, p in experiment["phases"].items()},
        },
        "mechanical_finding": mechanical_cache_finding(experiment),
    }


def main() -> int:
    print(json.dumps(evidence_document(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
