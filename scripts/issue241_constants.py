#!/usr/bin/env python3
"""Issue #241 (R8-I3) — frozen constants: first practical AMD/Vulkan
comparator pivoted to a consumer Polaris RX 580 8GB on the SAME
high-RAM host (inferswarm01) as the NVIDIA reference, plus the
prospective continuous canonical-reference-prefix observer
(comparator/2).

HISTORICAL-EXCLUDED FIXTURES ONLY. This module is authority-bearing: it
names the accepted predecessor identities that must remain
byte-preserved and the prospective identities this issue freezes BEFORE
any retained physical measurement.

Prohibited in this campaign (mechanically enforced by the runner/gates
and tested in tests/test_issue241_r8i3_rx580.py):
  * any c237-*/h237-*/p237-* predictive case execution;
  * any holdout decrypt/read (public ciphertext/certificate/commitment
    bytes may be read and hashed normally);
  * any selected-stress candidate output use;
  * any candidate-output agreement criterion influencing rung selection;
  * any CUDA participation or silent CPU/wrong-device fallback;
  * any change to model/conversion/member bytes, source pin, statistical
    design, comparator/1 families, or sealed-holdout authority.

Superseded #240 exploration: retained as diagnostic history only; no
file, hash, or output from the #240 tree is consumed here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ISSUE = 241
CAMPAIGN_ID = "issue241-r8i3-rx580-comparator-v2"

# --- accepted predecessor authority (byte-preserved; verified in Phase 0) ---
ACCEPTED_MAIN = "3aa59aed74df7f00302a6a2eb84640623b7cc14b"  # merge of PR #238 (#237)
R8I_AREA_REL = "docs/qualification/qwen38-vulkan-v1"
R8I_MANIFEST_REL = f"{R8I_AREA_REL}/MANIFEST.sha256"
R8I_HOLDOUT_REL = f"{R8I_AREA_REL}/sealed/holdout.cms"
R8I_TERMINAL = "R8I_QWEN38_HETEROGENEOUS_VULKAN_METHODOLOGY_FROZEN"
R8I_COMPARATOR_ID = "inferswarm.qwen38-vulkan-comparator/1"
SUPERSEDED_EXPLORATION_ISSUE = 240  # diagnostic history only; do not continue

# --- prospective v2 area (additive; accepted v1 area never edited) ---
AREA_REL = "docs/qualification/qwen38-vulkan-v2-rx580"
EVIDENCE_REL = f"{AREA_REL}/evidence"

# --- frozen subject: model bytes (unchanged v1 authority) ---
LLAMA_CPP_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
OBSERVER_BUILD_FLAGS = [
    "-DGGML_VULKAN=ON", "-DGGML_CUDA=OFF",
    "-DCMAKE_BUILD_TYPE=Release", "-DGGML_NATIVE=OFF",
    "-DGGML_AVX=OFF", "-DGGML_AVX2=OFF",
    "-DGGML_F16C=OFF", "-DGGML_FMA=OFF",
]
# Accepted observation binary (R8-E hook) — observer-equivalence BASELINE
# identity only, never a placement authority for this campaign.
ACCEPTED_OBS_SERVER_SHA256 = (
    "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0")
ACCEPTED_CANONICAL_VK_SERVER_SHA256 = (
    "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e")

MODEL_DIR = Path("/srv/models/qwen38-ud-iq1-s")  # inferswarm01 (single host)
MODEL_MEMBERS = (
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf",
)
MODEL_TOTAL_BYTES = 72546461344
MODEL_MEMBER_SHA256 = {
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf":
        "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf":
        "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf":
        "0e25ceaeb89b8a80aa9736b0c7448943622f7408c2855b2ebd016b7643a861a",
}

# --- frozen request contract (unchanged v1 §2 / R8-H authority) ---
REQUEST_CONTRACT = {
    "cache_prompt": False,
    "n_predict": 8,
    "return_tokens": True,
    "samplers": ["top_k"],
    "seed": 0,
    "stream": False,
    "temperature": 0.0,
    "top_k": 1,
}

# --- frozen matched geometry context settings (unchanged) ---
CONTEXT_SETTINGS = {"ctx-size": 8192, "batch-size": 512}
MATCHED_NGL_V1 = 1  # superseded placement; ladder starts here

N_VOCAB = 248320
ROW_BYTES = N_VOCAB * 4
DECISIONS = 8

# --- arms: SAME HOST (inferswarm01), sequential execution only ----------
# Identities below are the PROSPECTIVE frozen subject, derived from the
# post-swap fresh census (2026-09-23). Physical Phase 1 must re-observe
# every field read-only and fail closed on drift.
REFERENCE_ARM = {
    "arm": "B",
    "role": "reference",
    "host": "inferswarm01",
    "device": "NVIDIA GeForce RTX 3060 12GiB",
    "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    "bdf": "00000000:03:00.0",  # 16-char domain-prefixed form
    "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "vulkan_driver": "NVIDIA proprietary 610.57.04",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0", "CUDA_VISIBLE_DEVICES": "-1"},
    "non_oracle": (
        "Ordered comparison reference only; not an assertion of "
        "mathematical, vendor, or implementation correctness."),
}
CANDIDATE_ARM = {
    "arm": "C",
    "role": "candidate",
    "host": "inferswarm01",  # SAME host — the matched-host pivot
    "device": "AMD Radeon RX 580 Series (RADV POLARIS10), Ellesmere "
              "[1002:67df] rev e7, Sapphire Radeon RX 570 Pulse 4GB "
              "subsystem (8192 MiB VRAM per amdgpu census)",
    "gpu_uuid": None,  # RADV Polaris exposes no stable UUID; bound by BDF+PCIID
    "bdf": "00000000:02:00.0",
    "pci_id": "1002:67df",
    "icd": "/usr/share/vulkan/icd.d/radeon_icd.json",
    "vulkan_driver": "RADV (Mesa 25.0.7-2+deb13u1), apiVersion 1.4.305",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0", "CUDA_VISIBLE_DEVICES": "-1"},
}
# The excluded device set on this host: the non-participating GPU of each
# arm. Sequential single-GPU execution: during arm B only 03:00.0 may hold
# model residency; during arm C only 02:00.0 may.
EXCLUDED_BY_ARM = {
    "B": {"00000000:02:00.0"},  # RX 580 must stay at idle during reference
    "C": {"00000000:03:00.0"},  # RTX 3060 must stay at idle during candidate
}
EXCLUDED_RESIDENCY_NOISE_MIB = 8

# --- historical excluded fixtures (R8-B ladder; diagnostics ONLY) -------
FIXTURE_LADDER_REL = (
    "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json")
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db")
FIXTURE_CASES = ("case-256", "case-1024", "case-3072", "case-4096")

# --- accepted R8-H arm-B outputs (ngl=1 inertness/correctness sentinels) --
# Reference arm identity is CONTINUOUS with R8-H arm B ONLY IF the same
# physical card (GPU-1fc28f83 @ 02:00.0 then) is the card now at 03:00.0
# (GPU-d5c05739). The fresh census shows the REMAINING 3060 is
# GPU-d5c05739 — a DIFFERENT physical card from R8-H's reference
# (GPU-1fc28f83). Therefore R8-H arm-B sentinels are NOT byte-authority
# for this campaign's reference arm; comparator/2 reference rows are
# re-established prospectively. Retained for drift diagnostics only.
R8H_SENTINELS_AUTHORITY = "diagnostic-only: NOT byte-authority for the #241 reference arm"
R8H_ARM_B_SENTINELS_DIAGNOSTIC = {
    "case-256":  [561, 324, 55965, 51624, 29014, 271, 248068, 271],
    "case-1024": [561, 324, 55965, 51624, 29014, 34227, 18030, 16382],
    "case-3072": [328, 760, 324, 55965, 51624, 29014, 34227, 18030],
    "case-4096": [328, 760, 324, 55965, 51624, 29014, 34227, 18030],
}

# --- prospective VRAM reserve policy (RX 580 8GB) -----------------------
# Fresh census: 8192 MiB VRAM (amdgpu "VRAM: 8192M"). Frozen reserve for
# runtime/Vulkan buffers: 1536 MiB (unchanged policy constant). Budget =
# 8192 - 1536 = 6656 MiB model-tensor ceiling. This is a PROSPECTIVE
# policy bound, not a measured capacity or headroom claim.
CANDIDATE_VRAM_CENSUS_MIB = 8192
HBM_RESERVE_MIB = 1536
CANDIDATE_MODEL_BUDGET_MIB = CANDIDATE_VRAM_CENSUS_MIB - HBM_RESERVE_MIB
assert CANDIDATE_MODEL_BUDGET_MIB == 6656

# Prospective per-layer/output-head placement-law inputs (metadata-derived,
# same measurement family as the #240 pre-freeze probes; the campaign
# re-derives them from live -lv 5 placement at each rung and fail-closes
# on drift). Used ONLY to construct the ladder arithmetically.
PER_LAYER_MIB = 875.04
OUTPUT_HEAD_MIB = 393.43
MAX_RUNG_NGL = 8  # floor((6656 - 393.43)/875.04) + 1 = 8
LADDER_NGLS = (1, 2, 4, 6, 8)


def model_buffer_mib(ngl: int) -> float:
    """Prospective model-tensor estimate, not measured runtime residency."""
    if ngl < 1:
        raise ValueError("ngl must be >= 1")
    return (ngl - 1) * PER_LAYER_MIB + OUTPUT_HEAD_MIB


def derive_ladder() -> tuple[int, ...]:
    """Monotone ladder under the prospective budget; pure arithmetic."""
    rungs = [n for n in LADDER_NGLS if model_buffer_mib(n) <= CANDIDATE_MODEL_BUDGET_MIB]
    if not rungs or rungs[0] != MATCHED_NGL_V1:
        raise RuntimeError("ladder must start at the accepted ngl=1 geometry")
    return tuple(rungs)


# --- comparator/2 (prospective; this issue) ------------------------------
COMPARATOR_V2_ID = "inferswarm.qwen38-vulkan-comparator/2"
V2_OBSERVER = {
    "requests_per_case": 1,  # one continuous request per arm/case
    "decisions": DECISIONS,
    "reference_arm": (
        "one continuous request: consume frozen prompt; capture untouched "
        "full-vocab FP32 row at decision d; choose frozen greedy reference "
        "winner; append it to live state; repeat through 8 decisions"),
    "candidate_arm": (
        "one continuous request: consume identical prompt; capture "
        "untouched full-vocab FP32 row at decision d; record candidate "
        "winner; AFTER row capture force/append the REFERENCE token for "
        "decision d; continue live state to d+1; repeat through 8 decisions"),
    "capture_before_force": (
        "source-order proof required: row capture occurs before "
        "reference-token forcing at every decision"),
    "supersedes": (
        "v1 independent-prefill physical observation semantics for future "
        "R8-J predictive execution IF the maintainer accepts comparator/2"),
    "v1_relation": (
        "v1 vs v2 row differences are retained as diagnostic evidence "
        "only; byte equality between comparator versions is NOT required "
        "and NOT claimed"),
}

# --- practicality gate disposition vocabulary ---------------------------
DISPOSITION_PRACTICAL = "R8I3_RX580_COMPARATOR_V2_PRACTICAL"
DISPOSITION_INFRA = "R8I3_RX580_INFRASTRUCTURE_BLOCKED"
DISPOSITION_RUNTIME = "R8I3_RX580_RUNTIME_BLOCKED"
DISPOSITION_V2_BLOCKED = "R8I3_COMPARATOR_V2_BLOCKED"
DISPOSITIONS = (
    DISPOSITION_PRACTICAL, DISPOSITION_INFRA,
    DISPOSITION_RUNTIME, DISPOSITION_V2_BLOCKED,
)
PRACTICAL_CANDIDATE_PHASE_A_BOUND_S = 24 * 3600  # "~24 hours central"

# --- R8-J frozen realized calibration regime counts (projection input) --
# Issue #241 text: ~256:338, ~1024:366, ~3072:363, ~4096:349 (1416 total).
R8J_REALIZED_REGIME_COUNTS = {
    "250-264": 338, "1018-1032": 366, "3066-3080": 363, "4090-4104": 349,
}
R8J_SELECTED_STRESS_COUNT = 8
assert sum(R8J_REALIZED_REGIME_COUNTS.values()) == 1416

REGIME_OF_CASE = {
    "case-256": "250-264", "case-1024": "1018-1032",
    "case-3072": "3066-3080", "case-4096": "4090-4104",
}

PROHIBITED_CASE_PREFIXES = ("c237-", "h237-", "p237-")


def assert_historical_only(prompt_token_ids_name: str) -> None:
    """Fail closed if any case id carries a predictive namespace."""
    name = prompt_token_ids_name or ""
    for pref in PROHIBITED_CASE_PREFIXES:
        if name.startswith(pref):
            raise RuntimeError(
                f"predictive case {name!r} is prohibited in this campaign")


def fixture_ladder_path(root: Path | None = None) -> Path:
    root = root or ROOT
    return root / FIXTURE_LADDER_REL


def load_fixtures(root: Path | None = None) -> dict:
    """Load and hash-verify the historical excluded fixture ladder."""
    p = fixture_ladder_path(root)
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FIXTURE_LADDER_SHA256:
        raise RuntimeError(
            f"fixture ladder sha256 drift: {digest} != {FIXTURE_LADDER_SHA256}")
    doc = json.loads(data)
    cases = {c["case_id"]: c for c in doc["cases"]}
    missing = [c for c in FIXTURE_CASES if c not in cases]
    if missing:
        raise RuntimeError(f"fixture cases missing: {missing}")
    return cases


def accepted_r8i_file_digest(root: Path | None = None) -> dict[str, str]:
    """Recompute every accepted R8-I MANIFEST row digest from live bytes."""
    root = root or ROOT
    out: dict[str, str] = {}
    for line in (root / R8I_MANIFEST_REL).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        digest, rel = line.split(None, 1)
        out[rel.strip()] = digest
    return out


def verify_r8i_preservation(root: Path | None = None) -> dict[str, str]:
    """Fail closed if any accepted R8-I evidence byte drifted."""
    root = root or ROOT
    drifted: dict[str, str] = {}
    for rel, expected in accepted_r8i_file_digest(root).items():
        data = (root / rel).read_bytes()
        got = hashlib.sha256(data).hexdigest()
        if got != expected:
            drifted[rel] = f"{got} != {expected}"
    if drifted:
        raise RuntimeError(f"accepted R8-I evidence drift: {drifted}")
    return accepted_r8i_file_digest(root)
