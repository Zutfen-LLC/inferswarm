#!/usr/bin/env python3
"""V0-B Phase 3 — portable-capability assessment.

Consumes the accepted V0-A backend-capability records and the corrected
correctness/evidence, and assesses — as evidence about physical Compute
Units, never as vendor ontology — whether the observed Vulkan path
supplies the properties InferSwarm needs from an accelerator backend
capability (issue #142 Phase 3 checklist).

Every finding cites its evidence. A capability with no retained
evidence is recorded `no-evidence`, never guessed.

Writes docs/investigations/vulkan-v0-b/results/capability-assessment.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V0A = REPO / "docs/investigations/vulkan-v0-a"
OUT = REPO / "docs/investigations/vulkan-v0-b/results/capability-assessment.json"


def main() -> int:
    caps = json.loads(
        (V0A / "capabilities/backend-capability-records.json").read_text())
    mat = json.loads(
        (V0A / "results-correction/materialization-correction.json").read_text())

    by_backend = {}
    for r in caps["records"]:
        key = (r["physical_gpu"]["label"], r["backend"]["kind"])
        by_backend.setdefault(key, []).append(r)

    amd_vk = by_backend[("AMD-A", "Vulkan")][0]
    nv_vk = by_backend[("NV-A", "Vulkan")][0]

    # NV-A ready-state host RSS vs device-local model footprint: does GPU
    # residency inherently keep a persistent host copy? Evidence: AMD-A
    # RSS-at-ready 469,720 kB vs NV-A 1,003,172 kB vs NV-A/CUDA 789,488 kB;
    # model file 1.92 GB. The Vulkan arms hold MORE host RSS than CUDA at
    # the same residency — consistent with a host-side shadow of tensor
    # state — but RSS alone cannot prove persistence semantics, so this
    # stays an evidence-bounded observation, not a verdict.
    model_gb = 1_929_903_264 / 1e9
    amd_rss_gb = mat["arms"]["amd-a-vulkan"]["host_rss_ready_kB_median"] / 1e6
    nvvk_rss_gb = mat["arms"]["nvidia-vulkan"]["host_rss_ready_kB_median"] / 1e6
    nvcu_rss_gb = mat["arms"]["nvidia-cuda"]["host_rss_ready_kB_median"] / 1e6

    assessment = {
        "schema": "inferswarm.vulkan-v0-b.capability-assessment/1",
        "issue": 142,
        "framing": ("Findings are backend capabilities / evidence associated with "
                    "physical Compute Units (fabric-doctrine 2.4/2.5, ADR 0006 "
                    "backend-independent boundaries). Nothing here becomes a "
                    "resource-ontology noun."),
        "per_backend": {
            "amd_a_polaris_vulkan": {
                "compute_unit": "AMD-A (02:00.0, 1002:67df rev e7, 8 GiB VRAM, x16-capable slot via x1 riser)",
                "findings": {
                    "deterministic_physical_device_discovery_selection": {
                        "status": "evidence-supported",
                        "evidence": "loader enumerates multiple devices; every corrected run pinned --device Vulkan1 and proved BDF 0000:02:00.0 in its own stderr; llvmpipe/iGPU/other-card fallbacks excluded per-run"},
                    "device_local_memory_capacity_explicit": {
                        "status": "evidence-supported",
                        "evidence": f"vulkaninfo JSON dump: 8589934592 B device-local; corrected runs record ~{mat['arms']['amd-a-vulkan']['gpu_vram_ready_bytes_median']/1e9:.2f} GB VRAM at ready with the 1.92 GB model fully resident + KV"},
                    "model_state_materialization_on_accelerator": {
                        "status": "demonstrated for this model class",
                        "evidence": "37/37 layers offloaded, zero-inference harness proves VRAM residency at ready; Qwen2.5-3B Q4_K_M only — no claim for larger/multi-GPU models"},
                    "representative_ops_without_silent_host_fallback": {
                        "status": "demonstrated at fixture scale",
                        "evidence": "clean exits, stable greedy generation, no fallback markers in retained stderr across 4 Vulkan runs; logits-level op coverage NOT observable via CLI"},
                    "stable_sync_execution_semantics": {
                        "status": "evidence-supported (bounded)",
                        "evidence": "backend-local repeatability stable (3/3 identical AMD-A generations); crash/hang/device-loss rate unobserved beyond campaign length"},
                    "representation_quantization_support": {
                        "status": "partial",
                        "evidence": "Q4_K_M executed correctly; Polaris/RADV advertises no fp16 compute storage->compute fast path, no int-dot, and no matrix cores (subgroup 64); retained ggml evidence records the tested f32 compute path — representation breadth is partial/untested. These advertised capabilities and the tested representation path do not demonstrate a cause of the observed AMD throughput; compute vs memory vs link remains open"},
                    "useful_error_reporting": {
                        "status": "adequate",
                        "evidence": "device/offload banners, exit codes, and RADV driver messages retained and sufficient to attribute runs"},
                    "workload_relevant_prefill_performance": {
                        "status": "measured — materially limited",
                        "evidence": "pp512 median 498.0 t/s (vs NV-A Vulkan 3579.0) — DESCRIPTIVE cross-vendor only; absolute level ~26x below the same-class CUDA control is not available (no AMD native arm)"},
                    "workload_relevant_decode_performance": {
                        "status": "measured — descriptive host context only",
                        "evidence": "AMD Vulkan decode tg128 median 43.7 t/s is measured; a retained host comparison exists in results/economics.json. Vulkan/host ratios are descriptive context only: the CPU proof was established retrospectively after collection, is not prospectively frozen decision-grade authority, and does not gate or promote the V0-B terminal"},
                    "evidence_bindable_backend_runtime_identity": {
                        "status": "evidence-supported",
                        "evidence": "RADV 25.0.7-2+deb13u1, Vulkan API 1.4.305, loader 1.4.309.0 recorded in capability records with build/library SHA-256s"},
                    "capability_property_discovery_for_planning": {
                        "status": "evidence-supported",
                        "evidence": "vulkaninfo JSON dumps + llama.cpp advertised-capability banner retained (fp16/int-dot/matrix-cores/subgroup) — machine-readable per-device capability facts"},
                    "persistent_host_copy_requirement": {
                        "status": "no-evidence (bounded observation)",
                        "evidence": f"AMD-A host RSS at ready {amd_rss_gb:.2f} GB vs NV-A/Vulkan {nvvk_rss_gb:.2f} GB vs NV-A/CUDA {nvcu_rss_gb:.2f} GB for a {model_gb:.2f} GB model: the Vulkan arms hold more host RSS than CUDA at identical residency, consistent with a host-side shadow of state; RSS cannot establish persistence semantics — needs a runtime-level experiment"},
                    "backend_fast_path_coexistence_under_generic_semantics": {
                        "status": "conceptually supported, unproven",
                        "evidence": "fabric-doctrine 6.6/10.2 permits backend-native executors under backend-neutral planning; no InferSwarm-integrated Vulkan executor exists yet to demonstrate it"},
                },
            },
            "nv_a_ga104_vulkan": {
                "compute_unit": "NV-A (04:00.0, GA104 RTX 3060 Ti, 8 GiB, endpoint LnkCap 2.5GT/s x16 / LnkSta x1)",
                "findings": {
                    "deterministic_physical_device_discovery_selection": {
                        "status": "evidence-supported",
                        "evidence": "pinned --device Vulkan3 proved as 0000:04:00.0 in run stderr; CUDA0 control likewise"},
                    "device_local_memory_capacity_explicit": {
                        "status": "evidence-supported",
                        "evidence": "vulkaninfo + corrected materialization (~3.28 GB VRAM at ready)"},
                    "model_state_materialization_on_accelerator": {
                        "status": "demonstrated for this model class",
                        "evidence": "37/37 layers, zero-inference proof, flat VRAM through idle hold"},
                    "representative_ops_without_silent_host_fallback": {
                        "status": "evidence-supported (one corrected run)",
                        "evidence": "corrected run exited cleanly; intended NV-A physical device was proven; no silent host fallback markers were observed; zero-inference/materialization observations were clean where applicable. The one corrected generated-output observation is insufficiently observed; it is neither stable nor repeatable"},
                    "stable_sync_execution_semantics": {
                        "status": "evidence-supported (bounded)",
                        "evidence": "single corrected run + 3 zero-inference process runs clean; campaign length bounds the claim"},
                    "representation_quantization_support": {
                        "status": "strong for this stack",
                        "evidence": "fp16, int-dot, NV_coopmat2 (subgroup 32) advertised; Q4_K_M executed correctly at 0.949/0.884 of CUDA"},
                    "workload_relevant_performance": {
                        "status": "measured — near native",
                        "evidence": "pp512 ratio 0.949, tg128 ratio 0.884 vs CUDA (same device); startup-to-ready +1.66 s vs CUDA; VRAM at ready 143.7 MB LOWER than CUDA; host RSS 213.7 MB higher"},
                    "evidence_bindable_backend_runtime_identity": {
                        "status": "evidence-supported",
                        "evidence": "NVIDIA Vulkan ICD 615.71.09 + build SHA-256s retained"},
                    "persistent_host_copy_requirement": {
                        "status": "no-evidence (bounded observation)",
                        "evidence": "same RSS-shadow observation as AMD-A; runtime-level experiment required"},
                },
            },
        },
        "capability_discovery_useful_to_planning": {
            "status": "evidence-supported as a shape",
            "evidence": "the V0-A backend-capability record schema (physical GPU identity + backend identity + advertised capabilities + measured economics, bound to evidence) matches the doctrine's 'capabilities/evidence associated with a resource' requirement (fabric-doctrine 2.4, 6.6, ADR 0006); it is research evidence shape, NOT a production schema"},
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(assessment, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"written": str(OUT.relative_to(REPO)),
                      "per_backend": list(assessment["per_backend"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
