#!/usr/bin/env python3
"""Issue #243 (R8-I4) — campaign constants, frozen prospectively.

Authority consumed (immutable):
  - #237 / PR #238 / merge 3aa59aed74df7f00302a6a2eb84640623b7cc14b
  - R8-H PHYSICAL-AUTHORITY.json model members + fixture ladder
  - llama.cpp pin b29c606e28a01b1bc8c1351026a0fa6e616bf6c4
  - Vulkan bin dir as built for R8-H arm B/C (llama-server sha256
    21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e)
  - R8-B fixture ladder JSON (historical-excluded fixtures ONLY)

Prohibitions encoded: no c237-* predictive execution, no holdout access,
no selected-stress candidate execution, no threshold derivation.
"""
from __future__ import annotations

CAMPAIGN_ID = "issue243-r8i4-v340l-z440-characterization"
HOST = "inferswarm05"
STARTING_MAIN = "3aa59aed74df7f00302a6a2eb84640623b7cc14b"

LLAMA_CPP_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
LLAMA_SERVER_SHA256 = (
    "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e")

MODEL_MEMBERS = (
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
        "bytes": 10_946_624,
        "sha256": "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    },
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf",
        "bytes": 49_990_818_368,
        "sha256": "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    },
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf",
        "bytes": 22_544_696_352,
        "sha256": "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
    },
)
MODEL_DIR = "/srv/models/qwen38-ud-iq1-s"
BIN_DIR = "/home/hermes/is243/r8h-vk-bin"

# Historical-excluded fixtures (R8-B ladder, re-anchored by R8-H
# PHYSICAL-AUTHORITY). These are the ONLY prompts this campaign may
# execute. sha256 of fixture-ladder.json:
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db")
FIXTURE_CASES = ("case-256", "case-1024", "case-3072", "case-4096")

# Request contract: identical to R8-H arm-C true-greedy contract.
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

CONTEXT_SETTINGS = {
    "ctx-size": 8192,
    "batch-size": 512,
}

# Historical baseline rung (accepted R8-H/R8-I inherited geometry).
BASELINE_NGL = 1

# Prospectively frozen HBM reserve for Vulkan/runtime buffers on the
# selected die, BEFORE observing comparative performance.
# Die HBM total = 8,573,157,376 B (7.984 GiB). Reserve = 1,073,741,824 B
# (1.0 GiB) for Vulkan instance/device buffers, KV/scratch already
# counted by llama.cpp "offloaded buffers" reporting, plus safety for
# BAR-visible mappings. Derived from R8-H measured ~1.05 GiB residency
# at ngl=1 (runtime floor) and #240's observed ~7.3 GiB ceiling at
# ngl=8 — 1 GiB reserve keeps max rung below both.
HBM_RESERVE_BYTES = 1_073_741_824

# ngl ladder: frozen before comparative performance observation.
# Model = 49 layers total (n_layer=48 decoder + output?). Actual tensor
# metadata read from the model header at runtime; ladder derived as
# monotone rungs from ngl=1 toward (HBM_total - reserve) budget using
# per-layer bytes measured at load. Rungs frozen in phase3-freeze.json
# BEFORE any retained performance output (see issue243_phase3.py).
REQUIRED_REPEATS_WARM = 3
REQUIRED_REPEATS_COLD = 1

# Selector space (freshly re-derived per boot on 05; never assumed):
#   VK_ICD_FILENAMES=radeon_icd.x86_64.json (exclude llvmpipe+nouveau)
#   GGML_VK_VISIBLE_DEVICES=<idx> selects die by loader order; die-level
#   proof is the per-BDF sysfs mem_info_vram_used delta.
ICD_FILE = "/usr/share/vulkan/icd.d/radeon_icd.json"

# Excluded-die noise bound: Vulkan instance init touches sibling die at
# MiB scale; material model residency at IQ1_S is >= hundreds of MiB.
EXCLUDED_DIE_NOISE_BYTES = 64 * 1024 * 1024

# Ports (one per concurrently running server)
PORT_DIE0 = 18491
PORT_DIE1 = 18492

# Terminal vocabulary (see issue text): one of
#   R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE
#   R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_ONLY
#   R8I4_V340_Z440_INFRASTRUCTURE_BLOCKED
#   R8I4_V340_Z440_RUNTIME_BLOCKED
#   R8I4_V340_Z440_NOT_PRACTICAL
