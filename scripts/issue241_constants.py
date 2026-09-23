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
        "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
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

# comparator/2 observer source identity: sha256 of server-context.cpp at
# llama.cpp pin b29c606e AFTER the accepted R8-E patch (post-image blob
# 02a8e4b439c78224d1b9e4eaeb1d890718c00e68, verified byte-identical to
# the accepted applied-source.patch header) plus the comparator/2 seam.
# Derived CPU-only from accepted committed bytes; re-derivable via
# scripts/issue241_observer_patch.py against the pinned base blob.
OBSERVER_PATCHED_SOURCE_SHA256 = (
    "2f1f3d5461c39b94d4dc92c74e03da5fb0b1af069f1aeda1df587a25c3ffe89f")

# --- arms: SAME HOST (inferswarm01), sequential execution only ----------
# Identities below are the PROSPECTIVE frozen subject, derived from the
# post-swap fresh census (2026-09-23). Physical Phase 1 must re-observe
# every field read-only and fail closed on drift.
#
# Machine-readable frozen subject identity (R8-I3 correction pass): every
# identity field required by issue #241 is a constant here, never prose
# alone. Sources (already-authoritative pre-campaign observations only):
#   * the retained 2026-09-23 post-swap census observations (session
#     outputs: lspci -nn/-k, nvidia-smi UUID/bus-id, dmesg amdgpu VRAM,
#     ICD inventory, per-ICD vulkaninfo summaries incl. NVIDIA deviceUUID
#     and RADV POLARIS10 deviceName/apiVersion/Mesa version);
#   * the accepted fleet hardware census of 2026-09-15
#     (docs/investigations/qwen38-flash-next-r8-a/hardware-census.json +
#     raw-hardware/inv-inferswarm01.txt), which recorded the 03:00.0 slot
#     as 10de:2504 subsystem 1458:4074 rev a1, LnkCap x16;
#   * a read-only sysfs/lspci -vv/nvidia-smi/vulkaninfo observation of
#     inferswarm01 taken 2026-09-23 for the subsystem/link-width fields
#     the post-swap session had not retained (identity-observation raw
#     retained at docs/qualification/qwen38-vulkan-v2-rx580/
#     identity-observation-2026-09-23.txt; sha256 recorded in the area
#     MANIFEST). No GPU compute, model read, or dispatch machinery was
#     involved.
# LINK IDENTITY POLICY: negotiated link SPEED is downtrainable by normal
# PCIe power management (observed 2.5 GT/s at idle on the reference) and
# is therefore recorded, never frozen. The frozen link identity is the
# negotiated WIDTH plus the max-link WIDTH capability (and, for the
# candidate, the max-link speed capability that distinguishes a Gen3
# slot from slot/device drift). Measured current speeds are retained in
# census receipts as observations.
REFERENCE_ARM = {
    "arm": "B",
    "role": "reference",
    "host": "inferswarm01",
    "device": "NVIDIA GeForce RTX 3060 12GiB",
    "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    "bdf": "00000000:03:00.0",  # 16-char domain-prefixed form
    "pci_id": "10de:2504",
    "vendor_id": "10de",
    "device_id": "2504",
    "subsystem_vendor_id": "1458",   # Gigabyte
    "subsystem_device_id": "4074",
    "revision": "a1",
    "link_width": "x16",            # negotiated width (frozen identity)
    "max_link_width": "x16",        # slot/device capability (frozen)
    "max_link_speed": "16.0 GT/s",  # Gen4 capability (frozen; slot drift
    #                                   discriminator; observed speed may
    #                                   downtrain to 2.5 GT/s at idle)
    "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "kernel_driver": "nvidia",
    "nvidia_driver_version": "610.57.04",
    "vulkan_device_name": "NVIDIA GeForce RTX 3060",
    "vulkan_device_uuid": "d5c05739-96c1-7e49-89b6-bf54c2121c55",
    "vulkan_api_version": "1.4.341",
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
    "gpu_uuid": None,  # RADV Polaris exposes no per-card UUID; bound below
    "bdf": "00000000:02:00.0",
    "pci_id": "1002:67df",
    "vendor_id": "1002",
    "device_id": "67df",
    "subsystem_vendor_id": "1da2",   # Sapphire Technology Limited
    "subsystem_device_id": "e353",   # "Radeon RX 570 Pulse 4GB" label
    "revision": "e7",
    "link_width": "x8",              # negotiated width (frozen identity;
    #                                   observed downgraded from x16 LnkCap)
    "max_link_width": "x16",         # device capability (frozen)
    "max_link_speed": "8.0 GT/s",    # Gen3 capability (frozen; Gen3-vs-Gen1
    #                                   slot drift discriminator)
    "icd": "/usr/share/vulkan/icd.d/radeon_icd.json",
    "kernel_driver": "amdgpu",
    "vulkan_device_name": "AMD Radeon RX 580 Series (RADV POLARIS10)",
    "vulkan_device_uuid": "00000000-0200-0000-0000-000000000000",
    "vulkan_api_version": "1.4.305",
    "vulkan_driver": "RADV (Mesa 25.0.7-2+deb13u1), apiVersion 1.4.305",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0", "CUDA_VISIBLE_DEVICES": "-1"},
}
# RADV Polaris10 deviceUUID is bus-derived, not card-unique: it encodes
# the BDF (domain 0000, bus 02, slot 00), which is exactly why it is
# retained as a frozen identity field (a different physical card in the
# same slot shares it, but a card at a different BDF does not) and why
# subsystem vendor/device/revision are additionally frozen.

# Frozen subject-identity predicate keys per arm role. Any drift in these
# fields must fail every acceptance-bearing boundary closed (census,
# Phase-2 telemetry, Phase-3 device identity, comparator validation).
IDENTITY_FIELDS = (
    "bdf", "vendor_id", "device_id", "subsystem_vendor_id",
    "subsystem_device_id", "revision", "link_width", "max_link_width",
    "kernel_driver", "icd", "vulkan_device_name", "vulkan_device_uuid",
)


def frozen_identity(arm: str) -> dict[str, str]:
    """Machine-readable frozen identity subset for an arm ('B' or 'C')."""
    if arm not in ("B", "C"):
        raise ValueError(f"unknown arm {arm!r}")
    cfg = REFERENCE_ARM if arm == "B" else CANDIDATE_ARM
    identity = {field: cfg[field] for field in IDENTITY_FIELDS}
    if arm == "B":
        identity["gpu_uuid"] = cfg["gpu_uuid"]
    else:
        identity["pci_id"] = cfg["pci_id"]
        identity["max_link_speed"] = cfg["max_link_speed"]
    return identity
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
