#!/usr/bin/env python3
"""Issue #234 — R8-H matched-campaign freeze builder (schema /2).

Writes evidence/freeze/campaign-freeze.json from the FRESH censuses +
runtime qualifications + per-host model rehash BEFORE any canonical
correctness output. The freeze pins:

  * the one frozen RTX 3060 (host, UUID, BDF, CUDA identity, Vulkan
    identity, selectors for both builds, driver, topology, VRAM,
    foreign-process baseline) — arms A and B MUST bind this identical
    GPU object (control 28);
  * the selected V340L die + excluded die (control 8/9);
  * both binaries' identities (CUDA build, Vulkan build — the Vulkan
    binary byte-identical on both hosts);
  * the matched geometry (ngl=1, ctx, batch, request, fixture, model
    member hashes) identical across A/B/C (control 30);
  * deployed physical-producer hashes at freeze time.

Structural verification lives in issue234_receipt.verify_freeze_binding.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc


def build(nvidia_census: dict, amd_census: dict,
          cuda_runtime: dict, vk_runtime_01: dict, vk_runtime_02: dict,
          backing: dict[str, dict], producer_hashes: dict[str, str],
          frozen_3060_index: int = 0) -> dict[str, Any]:
    r3060 = nvidia_census["rtx3060"]
    if len(r3060) != 2:
        raise rc.FreezeError(f"census must carry exactly 2 RTX 3060: "
                             f"{len(r3060)}")
    frozen = r3060[frozen_3060_index]
    other = r3060[1 - frozen_3060_index]
    dies = amd_census["v340l_dies"]
    if len(dies) != 2:
        raise rc.FreezeError(f"census must carry exactly 2 V340L dies")
    # deterministic selection: lowest BDF is the selected die (V2-G
    # remediated-path convention; output-blind)
    sel_bdf = sorted(dies)[0]
    exc_bdf = sorted(dies)[1]
    sel_die = dies[sel_bdf]
    exc_die = dies[exc_bdf]

    vk_sha = vk_runtime_01["binaries"]["llama-server"]["sha256"]
    if vk_runtime_02["binaries"]["llama-server"]["sha256"] != vk_sha:
        raise rc.FreezeError(
            "Vulkan binary differs between hosts — arms B/C would not "
            "share binary bytes")
    cuda_sha = cuda_runtime["binaries"]["llama-server"]["sha256"]

    # driver/vram join: census rtx3060 rows carry nvidia-smi bdf/uuid,
    # the driver + totals live in the nvidia.gpus section
    nv_by_uuid = {g["uuid"]: g for g in nvidia_census["nvidia"]["gpus"]}
    nv_frozen = nv_by_uuid[frozen["nvidia_uuid"]]

    gpu_obj = {
        "host": nvidia_census["host"]["hostname"],
        "uuid": frozen["nvidia_uuid"],
        "bdf": frozen["bdf_smi"],
        "cuda_identity": {
            "name": frozen["name"],
            "driver": nv_frozen["driver_version"],
            "smi_index": frozen["smi_index"],
            "selector": f"CUDA_VISIBLE_DEVICES={frozen['smi_index']}",
        },
        "vulkan_identity": {
            "deviceUUID": frozen["vulkan_deviceUUID"],
            "vulkan_key": frozen["vulkan_key"],
            "selector": (f"GGML_VK_VISIBLE_DEVICES="
                         f"{vk_runtime_01['selector']['value']}"),
            "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
        },
        "memory_total_mib": nv_frozen["memory_total_mib"],
        "topology": frozen.get("sysfs", {}).get("current_link_width"),
        "foreign_processes_at_freeze":
            nvidia_census["nvidia"]["compute_apps_raw"].strip(),
        "sibling_3060": {"uuid": other["nvidia_uuid"],
                         "bdf": other["bdf_smi"]},
    }
    arm_common = {
        "ngl": rc.MATCHED_NGL,
        "context": dict(rc.CONTEXT_SETTINGS),
        "request": dict(rc.REQUEST_CONTRACT),
        "fixture_sha256": rc.R8D_FIXTURE_SHA256,
        "model_sha256": [m["sha256"] for m in rc.MODEL_MEMBERS],
    }
    doc = {
        "schema": "inferswarm.r8h.freeze/2",
        "campaign": rc.CAMPAIGN_ID,
        "llama_cpp_pin": rc.LLAMA_CPP_PIN,
        "request_contract": rc.REQUEST_CONTRACT,
        "fixture_sha256": rc.R8D_FIXTURE_SHA256,
        "ngl": rc.MATCHED_NGL,
        "context": rc.CONTEXT_SETTINGS,
        "model_members": [dict(m) for m in rc.MODEL_MEMBERS],
        "rtx3060": gpu_obj,
        "binaries": {
            "cuda_01": {"sha256": cuda_sha},
            "vulkan_01": {"sha256": vk_sha},
            "vulkan_02": {"sha256": vk_runtime_02["binaries"]
                          ["llama-server"]["sha256"]},
        },
        "arms": {
            "A": {**arm_common, "gpu": gpu_obj,
                  "binary_sha256": cuda_sha,
                  "backend": "cuda"},
            "B": {**arm_common, "gpu": gpu_obj,
                  "binary_sha256": vk_sha,
                  "backend": "vulkan"},
            "C": {
                **arm_common,
                "gpu": {
                    "host": amd_census["host"]["hostname"],
                    "bdf": sel_bdf,
                    "deviceUUID": sel_die["deviceUUID"],
                    "vulkan_key": sel_die["vulkan_key"],
                    "driver": "RADV " + str(sel_die.get("driverVersion")),
                    "selector": (f"GGML_VK_VISIBLE_DEVICES="
                                 f"{vk_runtime_02['selector']['value']}"),
                },
                "excluded_die": {"bdf": exc_bdf,
                                 "deviceUUID": exc_die["deviceUUID"]},
                "binary_sha256": vk_runtime_02["binaries"]
                ["llama-server"]["sha256"],
                "backend": "vulkan",
            },
        },
        "backing": backing,
        "producer_hashes_at_freeze": producer_hashes,
        "census_boot_ids": {
            "nvidia_host": nvidia_census["host"]["boot_id"],
            "amd_host": amd_census["host"]["boot_id"],
        },
    }
    rc.verify_freeze_binding(doc)
    return doc


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="R8-H matched-campaign freeze builder")
    ap.add_argument("--nvidia-census", type=Path, required=True)
    ap.add_argument("--amd-census", type=Path, required=True)
    ap.add_argument("--cuda-runtime", type=Path, required=True)
    ap.add_argument("--vk-runtime-01", type=Path, required=True)
    ap.add_argument("--vk-runtime-02", type=Path, required=True)
    ap.add_argument("--backing", type=Path, required=True,
                    help="JSON {arm: backing-doc}")
    ap.add_argument("--producer-hashes", type=Path, required=True)
    ap.add_argument("--frozen-3060-index", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = build(
        json.loads(args.nvidia_census.read_text()),
        json.loads(args.amd_census.read_text()),
        json.loads(args.cuda_runtime.read_text()),
        json.loads(args.vk_runtime_01.read_text()),
        json.loads(args.vk_runtime_02.read_text()),
        json.loads(args.backing.read_text()),
        json.loads(args.producer_hashes.read_text()),
        args.frozen_3060_index)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "frozen_3060": doc["rtx3060"]["uuid"],
        "frozen_3060_bdf": doc["rtx3060"]["bdf"],
        "selected_die": doc["arms"]["C"]["gpu"]["bdf"],
        "excluded_die": doc["arms"]["C"]["excluded_die"]["bdf"],
        "cuda_sha": doc["binaries"]["cuda_01"]["sha256"][:16],
        "vulkan_sha": doc["binaries"]["vulkan_01"]["sha256"][:16],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
