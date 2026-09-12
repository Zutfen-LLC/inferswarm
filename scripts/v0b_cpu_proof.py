#!/usr/bin/env python3
"""V0-B supplemental CPU arm — layers-executed-on-host-CPU proof (shared).

Single authoritative implementation of the correction-3 proof rule
(METHODOLOGY-CORRECTION-3.md), used at collection time by
`v0b_cpu_supplement_run.py` and at reduction time by
`v0b_cpu_supplement_derive.py` and `v0b_economics.py`.

What this rule proves, precisely: the model's layers executed on the
host CPU. It does NOT prove "no GPU participated", "no GPU device was
used", or "no GPU memory was touched": with a Vulkan ICD present the
runtime enumerates devices and reserves nonzero GPU scratch buffers even
at `-ngl 0` (retained lines in the accepted runs' stderr, e.g.
`sched_reserve: Vulkan0 compute buffer size = 565.81 MiB`). Enumeration
and scratch reservation are recorded as declared context, never as proof
either way.

A retained run's stderr satisfies the proof if and only if ALL of:

  1. exactly one `offloaded N/M layers to GPU` line, with N == 0 and M ==
     the expected layer count (0/<n> — exact zero GPU-layer offload);
  2. every `load_tensors: layer <i> assigned to device <D>` line present
     (one per model layer) assigns D == CPU — no layer assigned to a GPU;
  3. `CPU_Mapped model buffer` present (weights mapped on CPU);
  4. `CPU KV buffer` present (KV cache on CPU);
  5. `CPU output buffer` present (output state on CPU);
  6. process exit code is 0 (checked by the caller, which owns exit).

GPU execution-binding lines (`...: using device <GPU> ...`) are matched
and REPORTED with the disposition
`icd_device_enumeration_context_not_prohibitive`: they bind which device
the runtime prepared (scratch/ICD context), not where model layers
executed; condition (2) is what binds execution.
"""
from __future__ import annotations

import re

PROOF_SPEC = (
    "layers-executed-on-host-CPU (correction-3 rule): exactly one "
    "'offloaded 0/<n> layers to GPU' line; every 'layer <i> assigned to "
    "device CPU' line present and none assigned to a GPU; CPU_Mapped "
    "model buffer; CPU KV buffer; CPU output buffer; clean exit. Proves "
    "CPU layer execution only — NOT 'no GPU memory touched' and NOT 'no "
    "GPU device was used' (Vulkan enumeration and scratch reservation "
    "are declared context)."
)

OFFLOAD_RE = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")
LAYER_ASSIGN_RE = re.compile(
    r"layer\s+(\d+)\s+assigned to device\s+([A-Za-z_][\w ]*?)(?:,|$)")
GPU_BIND_RE = re.compile(r"using device\s+(\S+)")
BIND_DISPOSITION = "icd_device_enumeration_context_not_prohibitive"


def proof_from_stderr(stderr: str, expected_layers: int = 37) -> dict:
    """Re-derive the CPU-execution proof from raw retained stderr bytes."""
    lines = stderr.splitlines()

    offload_lines = [ln for ln in lines if OFFLOAD_RE.search(ln)]
    offload_ok = False
    if len(offload_lines) == 1:
        m = OFFLOAD_RE.search(offload_lines[0])
        if m is not None:
            offload_ok = m.groups() == ("0", str(expected_layers))

    assignments = LAYER_ASSIGN_RE.findall(stderr)
    assigned = {int(idx): dev.strip() for idx, dev in assignments}
    gpu_layers = sorted(i for i, dev in assigned.items() if dev.upper() != "CPU")
    layers_all_cpu = (
        len(assignments) == expected_layers
        and sorted(assigned) == list(range(expected_layers))
        and not gpu_layers
    )

    cpu_mapped = "CPU_Mapped model buffer" in stderr
    cpu_kv = re.search(r"CPU\s+KV buffer", stderr) is not None
    cpu_output = re.search(r"CPU\s+output buffer", stderr) is not None

    gpu_bind = [
        {"line": ln.strip(), "device": m.group(1), "disposition": BIND_DISPOSITION}
        for ln in lines
        for m in [GPU_BIND_RE.search(ln)]
        if m is not None and "assigned to device" not in ln
        and m.group(1).upper() != "CPU"
    ]

    return {
        "spec": PROOF_SPEC,
        "offload_zero_proven": offload_ok,
        "offload_lines_found": len(offload_lines),
        "expected_layers": expected_layers,
        "layer_assignment_lines_found": len(assignments),
        "layers_assigned_gpu": gpu_layers,
        "layers_all_cpu": layers_all_cpu,
        "cpu_mapped_model_buffer": cpu_mapped,
        "cpu_kv_buffer": cpu_kv,
        "cpu_output_buffer": cpu_output,
        "gpu_device_binding_lines": gpu_bind,
        "proved": bool(offload_ok and layers_all_cpu and cpu_mapped
                       and cpu_kv and cpu_output),
    }


def recheck_run(run_dir, rec: dict, expected_layers: int = 37) -> dict:
    """Re-derive the proof for one retained run from its raw bytes.

    `run_dir` is a Path to the run directory holding stderr.txt; `rec` is
    the parsed run.json. The returned dict carries the re-derived proof
    plus whether it agrees with the collected-time verdict recorded in
    run.json.
    """
    stderr = (run_dir / "stderr.txt").read_text()
    proof = proof_from_stderr(stderr, expected_layers=expected_layers)
    proof["exit_code"] = rec.get("exit_code")
    proof["proved"] = bool(proof["proved"] and rec.get("exit_code") == 0)
    proof["matches_collected_verdict"] = (
        bool(proof["proved"]) == bool(rec.get("backend_selection_proven")))
    return proof
