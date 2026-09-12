#!/usr/bin/env python3
"""V0-B Phase 2 — matched same-device economics reduction.

Mechanically derives, with distributions retained (never collapsed to a
single number):

  - NV-A Vulkan/CUDA: prefill, decode, startup-to-ready, VRAM at ready,
    host RSS at ready (ratios/deltas from retained V0-A medians + raw
    process observations);
  - AMD-A Vulkan: characterization (no native comparator exists);
  - AMD-A Vulkan vs host (CPU): the supplemental matched CPU baseline
    (same host, probe, model, workload; -ngl 0), with the declared
    difference that the physical execution substrate differs.

Prefill and decode are kept separate throughout. The CPU arm is NOT a
backend ratio.

Writes docs/investigations/vulkan-v0-b/results/economics.json.
Fail-closed: refuses to emit a ratio not grounded in the retained rows.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v0b_cpu_proof import recheck_run  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
V0A = REPO / "docs/investigations/vulkan-v0-a"
CPU_DIR = REPO / "docs/investigations/vulkan-v0-b/results/cpu-supplemental"
OUT = REPO / "docs/investigations/vulkan-v0-b/results/economics.json"

failures: list[str] = []


def load_bench(name: str) -> dict:
    """Return {'pp512': [tps...], 'tg128': [tps...]} from a bench CSV."""
    out = {"pp512": [], "tg128": []}
    lines = (V0A / "results" / name).read_text().splitlines()
    header = None
    for line in lines:
        if line.startswith("build_commit,"):
            header = line
            continue
        row = next(csv.DictReader([header, line]))
        ts = float(row["avg_ts"])
        if row["n_prompt"] == "512" and row["n_gen"] == "0":
            out["pp512"].append(ts)
        elif row["n_gen"] == "128" and row["n_prompt"] == "0":
            out["tg128"].append(ts)
    return out


def reduce_cpu_arm() -> dict | None:
    run_dirs = sorted(CPU_DIR.glob("v0b-cpu-*"))
    runs = []
    for rd in run_dirs:
        rec_path = rd / "run.json"
        if not rec_path.exists():
            continue
        rec = json.loads(rec_path.read_text())
        rid = rec.get("run_id", rd.name)
        proof = recheck_run(rd, rec, expected_layers=37)
        if rec.get("exit_code") != 0:
            failures.append(f"{rid}: nonzero exit")
            continue
        if not proof.get("proved"):
            failures.append(f"{rid}: raw stderr does not prove layers-executed-on-host-CPU")
            continue
        stdout = (rd / "stdout.txt").read_text()
        vals = {"pp512": [], "tg128": []}
        # canonical llama-bench output table: | model | size | params | backend |
        # threads | gpu layers | test | t/s ± ...
        for line in stdout.splitlines():
            if not line.startswith("| qwen2"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            # find the test name and value robustly
            test = None
            for c in cells:
                if c.startswith("pp") or c.startswith("tg"):
                    test = c.split()[0]
            ts_cell = cells[-1]
            ts = float(ts_cell.split("±")[0].strip())
            if test and test.startswith("pp"):
                vals["pp512"].append(ts)
            elif test and test.startswith("tg"):
                vals["tg128"].append(ts)
        if len(vals["pp512"]) != 1 or len(vals["tg128"]) != 1:
            failures.append(
                f"{rec['run_id']}: expected 1 pp512 + 1 tg128 aggregate row, "
                f"got {len(vals['pp512'])}/{len(vals['tg128'])}")
            continue
        runs.append({"run_id": rec["run_id"], "raw_proof": {
            "proved": proof["proved"],
            "offload_zero_proven": proof["offload_zero_proven"],
            "layers_all_cpu": proof["layers_all_cpu"],
            "cpu_mapped_model_buffer": proof["cpu_mapped_model_buffer"],
            "cpu_kv_buffer": proof["cpu_kv_buffer"],
            "cpu_output_buffer": proof["cpu_output_buffer"],
        }, **{k: v[0] for k, v in vals.items()}})
    if not runs:
        return None
    return {
        "runs": runs,
        "n_runs": len(runs),
        "pp512_median_tps": statistics.median(r["pp512"] for r in runs),
        "tg128_median_tps": statistics.median(r["tg128"] for r in runs),
        "arm_identity": "inferswarm02 host CPU (Celeron G3900, 2 threads), "
                        "same probe build-vulkan binary, same model bytes, "
                        "same pp512/tg128 workload, -ngl 0",
        "governance": {
            "physical_factual_finding": "layers-executed-on-host-CPU",
            "final_proof_timing": "retrospective_after_collection",
            "prospectively_frozen_decision_grade": False,
            "evidence_use": "retrospective_descriptive_only",
        },
    }


def main() -> int:
    nv_vk = load_bench("bench-nvidia-vk.csv")
    nv_cu = load_bench("bench-nvidia-cuda.csv")
    amd_vk = load_bench("bench-amd-vk.csv")
    for name, d in (("nv-vk", nv_vk), ("nv-cuda", nv_cu), ("amd-vk", amd_vk)):
        if len(d["pp512"]) != 3 or len(d["tg128"]) != 3:
            failures.append(f"{name}: expected 3+3 process rows, got "
                            f"{len(d['pp512'])}+{len(d['tg128'])}")

    matcor = json.loads(
        (V0A / "results-correction/materialization-correction.json").read_text())

    def med(xs):
        return statistics.median(xs)

    def ratio(a, b):
        return round(a / b, 4)

    nv = {
        "pair": "NV-A (04:00.0) Vulkan vs CUDA",
        "classification": "MATCHED_WITH_DECLARED_DIFFERENCE (same physical GPU, model, workload, link state; backend codegen differs by construction)",
        "prefill": {
            "vulkan_pp512_process_tps": nv_vk["pp512"],
            "cuda_pp512_process_tps": nv_cu["pp512"],
            "vulkan_median": med(nv_vk["pp512"]),
            "cuda_median": med(nv_cu["pp512"]),
            "ratio_vk_over_cuda": ratio(med(nv_vk["pp512"]), med(nv_cu["pp512"])),
            "label": "CALCULATED from retained MEASURED process aggregates",
        },
        "decode": {
            "vulkan_tg128_process_tps": nv_vk["tg128"],
            "cuda_tg128_process_tps": nv_cu["tg128"],
            "vulkan_median": med(nv_vk["tg128"]),
            "cuda_median": med(nv_cu["tg128"]),
            "ratio_vk_over_cuda": ratio(med(nv_vk["tg128"]), med(nv_cu["tg128"])),
            "label": "CALCULATED from retained MEASURED process aggregates",
        },
        "startup_to_ready": {
            "vulkan_median_s": matcor["arms"]["nvidia-vulkan"]["startup_to_ready_s_median"],
            "cuda_median_s": matcor["arms"]["nvidia-cuda"]["startup_to_ready_s_median"],
            "vulkan_minus_cuda_s": matcor["nvidia_vulkan_minus_cuda_deltas"]["startup_to_ready_s_median"]["vulkan_minus_cuda"],
            "ratio_cuda_over_vk": ratio(
                matcor["arms"]["nvidia-cuda"]["startup_to_ready_s_median"],
                matcor["arms"]["nvidia-vulkan"]["startup_to_ready_s_median"]),
            "label": "MEASURED (corrected zero-inference harness) + CALCULATED ratio",
        },
        "vram_at_ready": {
            "vulkan_bytes": matcor["arms"]["nvidia-vulkan"]["gpu_vram_ready_bytes_median"],
            "cuda_bytes": matcor["arms"]["nvidia-cuda"]["gpu_vram_ready_bytes_median"],
            "vulkan_minus_cuda_bytes": matcor["nvidia_vulkan_minus_cuda_deltas"]["gpu_vram_ready_bytes_median"]["vulkan_minus_cuda"],
        },
        "host_rss_at_ready": {
            "vulkan_kB": matcor["arms"]["nvidia-vulkan"]["host_rss_ready_kB_median"],
            "cuda_kB": matcor["arms"]["nvidia-cuda"]["host_rss_ready_kB_median"],
            "vulkan_minus_cuda_kB": matcor["nvidia_vulkan_minus_cuda_deltas"]["host_rss_ready_kB_median"]["vulkan_minus_cuda"],
        },
    }

    amd = {
        "arm": "AMD-A (02:00.0) Vulkan characterization",
        "native_comparator": "NONE — HIP/ROCm NATIVE_BACKEND_UNAVAILABLE (mechanically demonstrated); no Vulkan/native ratio exists",
        "prefill": {
            "pp512_process_tps": amd_vk["pp512"],
            "median": med(amd_vk["pp512"]),
        },
        "decode": {
            "tg128_process_tps": amd_vk["tg128"],
            "median": med(amd_vk["tg128"]),
        },
        "startup_to_ready_s_median": matcor["arms"]["amd-a-vulkan"]["startup_to_ready_s_median"],
        "vram_at_ready_bytes": matcor["arms"]["amd-a-vulkan"]["gpu_vram_ready_bytes_median"],
        "host_rss_at_ready_kB": matcor["arms"]["amd-a-vulkan"]["host_rss_ready_kB_median"],
    }

    cpu = reduce_cpu_arm()

    host_comparison = None
    if cpu:
        if len(cpu["runs"]) < 3:
            failures.append(f"CPU arm: expected 3 proven runs, got {len(cpu['runs'])}")
        host_comparison = {
            "pair": "AMD-A (02:00.0) Vulkan vs host CPU execution on the same host",
            "classification": "MATCHED_WITH_DECLARED_DIFFERENCE (same host/probe/model/workload; execution substrate differs: device-local VRAM+GPU vs host RAM+CPU — that difference is the question)",
            "method_authority": ("retrospective correction-3 factual proof; not a "
                                 "prospectively frozen decision-grade CPU baseline"),
            "cpu_arm": cpu,
            "prefill": {
                "amd_vulkan_median_tps": med(amd_vk["pp512"]),
                "cpu_median_tps": cpu["pp512_median_tps"],
                "ratio_amd_vk_over_cpu": ratio(med(amd_vk["pp512"]), cpu["pp512_median_tps"]),
                "label": "CALCULATED",
            },
            "decode": {
                "amd_vulkan_median_tps": med(amd_vk["tg128"]),
                "cpu_median_tps": cpu["tg128_median_tps"],
                "ratio_amd_vk_over_cpu": ratio(med(amd_vk["tg128"]), cpu["tg128_median_tps"]),
                "label": "CALCULATED",
            },
            "interpretation_guard": "this is a substrate-usefulness comparison, NOT a backend ratio; prefill and decode kept separate",
        }

    if failures:
        print(json.dumps({"failures": failures}, indent=1))
        return 1

    out = {
        "schema": "inferswarm.vulkan-v0-b.economics/1",
        "issue": 142,
        "nvidia_same_device": nv,
        "amd_characterization": amd,
        "host_execution_comparison": host_comparison,
        "prefill_decode_separation": "enforced — no combined average is computed anywhere in this reduction",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({
        "written": str(OUT.relative_to(REPO)),
        "nv_pp_ratio": nv["prefill"]["ratio_vk_over_cuda"],
        "nv_tg_ratio": nv["decode"]["ratio_vk_over_cuda"],
        "cpu_runs": len(cpu["runs"]) if cpu else 0,
        "amd_vk_over_cpu_pp": (host_comparison or {}).get("prefill", {}).get("ratio_amd_vk_over_cpu"),
        "amd_vk_over_cpu_tg": (host_comparison or {}).get("decode", {}).get("ratio_amd_vk_over_cpu"),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
