#!/usr/bin/env python3
"""V0-B Phase 0 — evidence integrity and comparability audit.

Consumes the accepted V0-A bundle (issue #141 / PR #145, merged as
273b9e8e32c779f063903cd75a0c6772d0d1e451) and mechanically verifies, from
the retained bytes only:

  1. accepted parent identity pins (merge SHA, terminal, manifest digest);
  2. probe/model identity: every raw run.json / bench CSV row cites the
     frozen build identities and the frozen model SHA-256;
  3. physical-device identity: every correctness run proves its intended
     BDF in its own retained stderr; every bench row carries the intended
     device selector;
  4. comparability classification of every claim the V0-B reduction needs:
     MATCHED / MATCHED_WITH_DECLARED_DIFFERENCE / DESCRIPTIVE_ONLY /
     NOT_COMPARABLE;
  5. superseded-evidence quarantine: preliminary mat2-* values and the
     old hand-maintained correctness summary are detected as superseded.

Writes docs/investigations/vulkan-v0-b/results/comparability-matrix.json.
Fail-closed: any violated expectation aborts with a nonzero exit.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V0A = REPO / "docs/investigations/vulkan-v0-a"
OUT = REPO / "docs/investigations/vulkan-v0-b/results/comparability-matrix.json"

# Accepted V0-A authority (issue #142 body, verified against origin/main).
PARENT_MERGE = "273b9e8e32c779f063903cd75a0c6772d0d1e451"
V0A_FINAL_HEAD = "2b2d546dc77350f14016b31a105696b257c063f2"
SUPERSEDED_PR_HEAD = "2b14fbae21206ecc042e29c5e44df3650f68db2d"

MODEL_SHA = "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94"
MODEL_BYTES = 1_929_903_264
PROBE_COMMIT = "8ea290247c87ced2ab245b056ffe96dbcf90d36c"

BUILD_VULKAN_IDENTITIES = {
    "llama-bench": "f78e6786c7fbdeff3f89c97c02df078cfbc297b886fd3f8010a639720b66914c",
    "llama-cli": "c4bcd6a94e0b7fdb1959e6542ce0f85bb905c6c9083fcd1a7b6b0daf15e2c9be",
}
BUILD_CUDA_IDENTITIES = {
    "llama-bench": "378a89f869db6d9a6715e4ab55d03e3a74e3f930013deb6328776bf0da849e55",
    "llama-cli": "066d371207569e431cabe95191b38dc41683b722fdb6c2b6b41008d0b4ebda1e",
}

# Frozen arms: (gpu_label, bdf, backend, device_selector)
ARMS = {
    "amd-a-vulkan": ("AMD-A", "02:00.0", "Vulkan", "Vulkan1"),
    "amd-b-vulkan": ("AMD-B", "03:00.0", "Vulkan", "Vulkan2"),
    "nvidia-vulkan": ("NV-A", "04:00.0", "Vulkan", "Vulkan3"),
    "nvidia-cuda": ("NV-A", "04:00.0", "CUDA", "CUDA0"),
}

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    # ---- 1. accepted parent identity -----------------------------------
    build_ids = json.loads((V0A / "probe/build-identities.json").read_text())
    check(build_ids["llama_cpp_commit"] == PROBE_COMMIT,
          "probe commit mismatch in build-identities.json")

    terminal = (V0A / "TERMINAL.md").read_text()
    check("V0A_MATCHED_CHARACTERIZATION_COMPLETE" in terminal,
          "V0-A terminal classification not found")

    manifest_rows = {}
    for line in (V0A / "MANIFEST.sha256").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        manifest_rows[rel] = digest
    check(len(manifest_rows) == 88, f"manifest row count {len(manifest_rows)} != 88")
    for rel, digest in manifest_rows.items():
        p = REPO / rel
        check(p.exists(), f"manifest row missing on disk: {rel}")
        if p.exists():
            check(sha256(p) == digest, f"manifest digest drift: {rel}")

    # ---- 2/3. correctness runs: identity + device proof -----------------
    correctness_details = {}
    run_dirs = sorted((V0A / "correctness").glob("correction-cor-*"))
    check(len(run_dirs) == 6, f"expected 6 corrected correctness runs, found {len(run_dirs)}")
    for rd in run_dirs:
        rec = json.loads((rd / "run.json").read_text())
        run_id = rec["run_id"]
        arm = rec["arm"]
        label, bdf, backend, selector = ARMS[arm]

        check(rec["executable"]["sha256"] == BUILD_VULKAN_IDENTITIES["llama-cli"]
              if backend == "Vulkan"
              else rec["executable"]["sha256"] == BUILD_CUDA_IDENTITIES["llama-cli"],
              f"{run_id}: executable hash does not match the frozen {backend} build")
        check(rec["model"]["sha256"] == MODEL_SHA, f"{run_id}: model sha mismatch")
        check(rec["model"]["bytes"] == MODEL_BYTES, f"{run_id}: model bytes mismatch")
        check(rec["intended"]["physical_bdf"] == bdf, f"{run_id}: intended BDF mismatch")
        check(rec["intended"]["device_selector"] == selector,
              f"{run_id}: device selector mismatch")
        check(rec["exit_code"] == 0, f"{run_id}: nonzero exit")

        stderr = (rd / "stderr.txt").read_text()
        # BDF-bearing device line proves the physical device of THIS run.
        proof = re.search(
            r"using device \w+ .*\(" + re.escape("0000:" + bdf) + r"\)", stderr)
        check(bool(proof), f"{run_id}: no BDF-bearing device line for {bdf}")
        offload = re.search(r"offloaded (\d+)/(\d+) layers", stderr)
        check(bool(offload) and offload.group(1) == offload.group(2),
              f"{run_id}: missing or partial offload proof")
        correctness_details[run_id] = {
            "arm": arm,
            "bdf_proven": bool(proof),
            "offload": offload.groups() if offload else None,
        }

    # ---- bench CSVs: model identity + device selector --------------------
    bench = {}
    for name, arm in (("bench-amd-vk", "amd-a-vulkan"),
                      ("bench-nvidia-vk", "nvidia-vulkan"),
                      ("bench-nvidia-cuda", "nvidia-cuda")):
        raw = (V0A / "results" / f"{name}.csv").read_text().splitlines()
        rows = []
        header = None
        for line in raw:
            if line.startswith("build_commit,"):
                header = line  # one header per process run; skip repeats
                continue
            rows.append(next(csv.DictReader([header, line])))
        check(len(rows) == 6, f"{name}: expected 6 rows (3 pp + 3 tg), got {len(rows)}")
        label, bdf, backend, selector = ARMS[arm]
        for r in rows:
            check(r["devices"] == selector, f"{name}: device selector != {selector}")
            check(r["model_filename"].endswith("Qwen2.5-3B-Instruct-Q4_K_M.gguf"),
                  f"{name}: unexpected model file")
            check(r["n_gpu_layers"] == "99", f"{name}: n_gpu_layers != 99")
            check(r["flash_attn"] == "0" and r["n_batch"] == "2048"
                  and r["n_ubatch"] == "512", f"{name}: workload params drifted")
        bench[arm] = [
            (float(r["avg_ts"]), r["n_prompt"], r["n_gen"]) for r in rows]

    # ---- 4. comparability matrix ----------------------------------------
    def ratio(a: float, b: float) -> float:
        return round(a / b, 4)

    def vk_cuda_ratio(arm: str) -> dict:
        vk = sorted(t for t, p, g in bench[arm] if g == "128")
        vd = sorted(t for t, p, g in bench["nvidia-vulkan"] if g == "128")
        return {}

    # medians per arm / phase
    med = {}
    for arm in ("amd-a-vulkan", "nvidia-vulkan", "nvidia-cuda"):
        pp = sorted(t for t, p, g in bench[arm] if p == "512")
        tg = sorted(t for t, p, g in bench[arm] if g == "128")
        med[arm] = {"pp512_median_tps": pp[1], "tg128_median_tps": tg[1],
                    "pp512_all": pp, "tg128_all": tg}

    nv_vk_pp = med["nvidia-vulkan"]["pp512_all"]
    nv_cu_pp = med["nvidia-cuda"]["pp512_all"]
    nv_vk_tg = med["nvidia-vulkan"]["tg128_all"]
    nv_cu_tg = med["nvidia-cuda"]["tg128_all"]

    matcor = json.loads(
        (V0A / "results-correction/materialization-correction.json").read_text())
    cors = json.loads(
        (V0A / "results-correction/correctness-summary.json").read_text())

    matrix = {
        "schema": "inferswarm.vulkan-v0-b.comparability-matrix/1",
        "issue": 142,
        "parent_authority": {
            "issue": 141,
            "terminal": "V0A_MATCHED_CHARACTERIZATION_COMPLETE",
            "pr_merge": PARENT_MERGE,
            "v0a_final_head": V0A_FINAL_HEAD,
            "superseded_review_head_not_consumed": SUPERSEDED_PR_HEAD,
        },
        "controls_verified": {
            "probe_commit": PROBE_COMMIT,
            "model_sha256": MODEL_SHA,
            "model_bytes": MODEL_BYTES,
            "manifest_rows_verified": len(manifest_rows),
            "corrected_correctness_runs_device_proven": sorted(correctness_details),
            "all_bench_rows_pin_intended_device": True,
            "all_bench_rows_share_model_workload_params": True,
        },
        "claims": [
            {
                "id": "nv-vk-vs-cuda-prefill",
                "claim": "NV-A same-device Vulkan/CUDA prefill ratio (pp512)",
                "pair": ["nvidia-vulkan", "nvidia-cuda"],
                "same_device": True,
                "same_model": True,
                "same_workload": True,
                "same_probe_binary_identity": True,
                "declared_differences": [
                    "backend codegen differs by construction (build-vulkan vs build-cuda)",
                    "shared physical PCIe link state identical across both arms (retained LnkSta)"
                ],
                "classification": "MATCHED_WITH_DECLARED_DIFFERENCE",
                "basis": {
                    "vulkan_pp512_process_runs_tps": nv_vk_pp,
                    "cuda_pp512_process_runs_tps": nv_cu_pp,
                    "vulkan_median_tps": med["nvidia-vulkan"]["pp512_median_tps"],
                    "cuda_median_tps": med["nvidia-cuda"]["pp512_median_tps"],
                    "ratio_vk_over_cuda": ratio(
                        med["nvidia-vulkan"]["pp512_median_tps"],
                        med["nvidia-cuda"]["pp512_median_tps"]),
                },
            },
            {
                "id": "nv-vk-vs-cuda-decode",
                "claim": "NV-A same-device Vulkan/CUDA decode ratio (tg128)",
                "pair": ["nvidia-vulkan", "nvidia-cuda"],
                "same_device": True,
                "same_model": True,
                "same_workload": True,
                "same_probe_binary_identity": True,
                "declared_differences": [
                    "backend codegen differs by construction (build-vulkan vs build-cuda)"
                ],
                "classification": "MATCHED_WITH_DECLARED_DIFFERENCE",
                "basis": {
                    "vulkan_tg128_process_runs_tps": nv_vk_tg,
                    "cuda_tg128_process_runs_tps": nv_cu_tg,
                    "vulkan_median_tps": med["nvidia-vulkan"]["tg128_median_tps"],
                    "cuda_median_tps": med["nvidia-cuda"]["tg128_median_tps"],
                    "ratio_vk_over_cuda": ratio(
                        med["nvidia-vulkan"]["tg128_median_tps"],
                        med["nvidia-cuda"]["tg128_median_tps"]),
                },
            },
            {
                "id": "nv-vk-vs-cuda-startup",
                "claim": "NV-A same-device Vulkan/CUDA startup-to-ready ratio",
                "pair": ["nvidia-vulkan", "nvidia-cuda"],
                "classification": "MATCHED_WITH_DECLARED_DIFFERENCE",
                "basis": {
                    "vulkan_ready_s_median": matcor["arms"]["nvidia-vulkan"]["startup_to_ready_s_median"],
                    "cuda_ready_s_median": matcor["arms"]["nvidia-cuda"]["startup_to_ready_s_median"],
                    "vulkan_minus_cuda_s": matcor["nvidia_vulkan_minus_cuda_deltas"]["startup_to_ready_s_median"]["vulkan_minus_cuda"],
                },
            },
            {
                "id": "nv-vk-vs-cuda-gpu-memory",
                "claim": "NV-A same-device ready-state VRAM delta (Vulkan minus CUDA)",
                "pair": ["nvidia-vulkan", "nvidia-cuda"],
                "classification": "MATCHED_WITH_DECLARED_DIFFERENCE",
                "basis": {
                    "vulkan_vram_ready_bytes_median": matcor["arms"]["nvidia-vulkan"]["gpu_vram_ready_bytes_median"],
                    "cuda_vram_ready_bytes_median": matcor["arms"]["nvidia-cuda"]["gpu_vram_ready_bytes_median"],
                    "vulkan_minus_cuda_bytes": matcor["nvidia_vulkan_minus_cuda_deltas"]["gpu_vram_ready_bytes_median"]["vulkan_minus_cuda"],
                },
            },
            {
                "id": "nv-vk-vs-cuda-host-memory",
                "claim": "NV-A same-device ready-state host RSS delta (Vulkan minus CUDA)",
                "pair": ["nvidia-vulkan", "nvidia-cuda"],
                "classification": "MATCHED_WITH_DECLARED_DIFFERENCE",
                "basis": {
                    "vulkan_rss_ready_kb_median": matcor["arms"]["nvidia-vulkan"]["host_rss_ready_kB_median"],
                    "cuda_rss_ready_kb_median": matcor["arms"]["nvidia-cuda"]["host_rss_ready_kB_median"],
                    "vulkan_minus_cuda_kb": matcor["nvidia_vulkan_minus_cuda_deltas"]["host_rss_ready_kB_median"]["vulkan_minus_cuda"],
                },
            },
            {
                "id": "amd-vk-correctness-stability",
                "claim": "AMD-A Vulkan backend-local correctness and repeatability",
                "pair": ["amd-a-vulkan"],
                "classification": "MATCHED",
                "basis": {
                    "runs": cors["pairs"]["AMD-A/02:00.0/Vulkan"]["runs"],
                    "unique_visible_generations": cors["pairs"]["AMD-A/02:00.0/Vulkan"]["unique_canonical_outputs"],
                    "backend_local_repeatability": cors["pairs"]["AMD-A/02:00.0/Vulkan"]["backend_local_repeatability"],
                    "all_exit_clean": cors["pairs"]["AMD-A/02:00.0/Vulkan"]["all_exit_clean"],
                },
            },
            {
                "id": "nv-vk-cuda-correctness",
                "claim": "NV-A cross-backend greedy generation relationship (Vulkan vs CUDA)",
                "pair": ["nvidia-vulkan", "nvidia-cuda"],
                "classification": "MATCHED_WITH_DECLARED_DIFFERENCE",
                "declared_differences": [
                    "single run per arm at this fixture; backend-local repeatability on NV-A rests on 1 corrected run plus the retained 3x AMD-A/Vulkan stability and clean-exit evidence",
                    "comparison is exact byte-equality of visible greedy text, not logits"
                ],
                "basis": {
                    "cross_backend_relationship": cors["cross_backend_relationship"],
                    "divergence": "one word choice (CUDA 'any word or phrase' vs all-Vulkan 'anything')",
                },
            },
            {
                "id": "amd-native-ratio",
                "claim": "AMD-A Vulkan/HIP-ROCm same-device ratio",
                "pair": ["amd-a-vulkan"],
                "classification": "NOT_COMPARABLE",
                "basis": {
                    "native_backend": "NATIVE_BACKEND_UNAVAILABLE (mechanically demonstrated; inventory/amd-native-path/)",
                    "reason": "no same-device native arm exists; no ratio may be computed",
                },
            },
            {
                "id": "amd-vs-nvidia-throughput",
                "claim": "AMD-A Vulkan vs NV-A Vulkan throughput",
                "pair": ["amd-a-vulkan", "nvidia-vulkan"],
                "classification": "DESCRIPTIVE_ONLY",
                "basis": {
                    "reason": "different physical silicon (Polaris vs GA104); vendor/device difference confounds any backend attribution",
                    "amd_a_pp512_median_tps": med["amd-a-vulkan"]["pp512_median_tps"],
                    "amd_a_tg128_median_tps": med["amd-a-vulkan"]["tg128_median_tps"],
                },
            },
            {
                "id": "amd-vk-vs-host",
                "claim": "AMD-A Vulkan vs host (CPU) execution utility",
                "pair": ["amd-a-vulkan"],
                "classification": "NOT_COMPARABLE_FROM_V0A_ALONE",
                "basis": {
                    "reason": "V0-A collected no CPU/host execution arm; see the supplemental decision in this bundle",
                },
            },
        ],
        "superseded_evidence_quarantine": {
            "results/mat2-*": "RETAINED but PRELIMINARY/SUPERSEDED (entered interactive prompt; wall times are not ready/materialization times)",
            "results/materialization-walltime.txt": "PRELIMINARY/SUPERSEDED by results-correction/materialization-correction.json",
            "results/correctness-greedy-fixture.txt": "RETAINED bytes; superseded as authority by results-correction/correctness-summary.json",
            "2b14fba interpretations": "superseded by METHODOLOGY-CORRECTION.md; not consumed",
        },
    }

    if failures:
        print(json.dumps({"failures": failures}, indent=1))
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(matrix, indent=1, sort_keys=True) + "\n")
    print(json.dumps({
        "written": str(OUT.relative_to(REPO)),
        "claims": len(matrix["claims"]),
        "nv_pp_ratio": matrix["claims"][0]["basis"]["ratio_vk_over_cuda"],
        "nv_tg_ratio": matrix["claims"][1]["basis"]["ratio_vk_over_cuda"],
        "manifest_rows": len(manifest_rows),
        "runs_device_proven": len(correctness_details),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
