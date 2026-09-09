"""Arm-B realization child: GemmaDenseStage over the materialized repository.

Runs as the FreeToken producer 924cd22e seam. NO PREFILL / decode /
generate: construction of GemmaDenseStage performs the selective load,
context setup, and finalization; the report retains the full residency/
staging account. The whole-shard sentinel stays armed after load.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

FREETOKEN_ROOT = Path("/home/zutfen/FreeToken")
sys.path.insert(0, str(FREETOKEN_ROOT))            # package root: benchmarks.*
sys.path.insert(0, str(FREETOKEN_ROOT / "python"))  # freetoken.*
sys.path.insert(0, "/srv/inferswarm/state/arm-b/scripts")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True)
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--block-plan", required=True)
    ap.add_argument("--participant", required=True)
    ap.add_argument("--gpu-uuid", required=True)
    ap.add_argument("--runtime-capacity-tokens", type=int, default=256)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_uuid

    import torch  # noqa: E402  (producer runtime; CUDA initializes here)

    from freetoken.distributed import set_tp_info, try_get_tp_info  # noqa: E402
    from freetoken.layers.rotary import set_rope_device  # noqa: E402

    if try_get_tp_info() is None:
        set_tp_info(rank=0, size=1)
    set_rope_device(torch.device("cuda:0"))

    from benchmarks.inferswarm_r6.stage_runtime import GemmaDenseStage  # noqa: E402

    plan = json.loads(Path(args.block_plan).read_text())
    block = next(b for b in plan["blocks"]
                 if b["spec"]["start_layer"] == PLAN_SPEC[args.participant][0]
                 and b["spec"]["end_layer"] == PLAN_SPEC[args.participant][1])
    shared = plan.get("declared_shared_state")
    runtime = GemmaDenseStage(
        role=args.role,
        model_path=args.model_path,
        adapter_data={
            **block,
            "declared_shared_state": (
                shared if args.role in ("first", "last") else None),
            "runtime_capacity_tokens": args.runtime_capacity_tokens,
        },
    )

    # keep the sentinel armed AFTER realization: any further checkpoint
    # iteration would raise (whole-model dependence proof)
    import benchmarks.inferswarm_r6.stage_runtime as sr  # noqa: E402
    import freetoken.models.gemma4.weight as gemma_weight  # noqa: E402

    def armed(*a, **k):
        runtime.whole_shard_sentinel_calls += 1
        raise AssertionError(
            "whole-checkpoint iterator executed after realization")

    gemma_weight.iter_weights = armed

    torch.cuda.synchronize()
    report = {
        "schema": "inferswarm.issue117.arm-b.realization-report/1",
        "participant_id": args.participant,
        "role": args.role,
        "model_path": args.model_path,
        "gpu_uuid": args.gpu_uuid,
        "observed_gpu_uuid": OBSERVED_UUID(),
        "plan_digest": plan.get("digest") or plan.get("plan_digest"),
        "block_spec": block["spec"],
        "allowed_key_count": len(block["allowed_tensor_keys"]),
        "global_layer_ids": list(runtime.block.global_layer_ids),
        "fetched_keys": runtime.fetched_keys,
        "fetched_bytes": runtime.fetched_bytes,
        "checkpoint_bytes_selected": runtime.checkpoint_bytes_selected,
        "largest_raw_tensor_bytes": runtime.largest_raw_tensor_bytes,
        "host_staging_total_bytes_processed":
            runtime.host_staging_total_bytes_processed,
        "host_staging_peak_live_tensor_bytes":
            runtime.host_staging_peak_live_tensor_bytes,
        "host_staging_current_bytes": runtime.host_staging_current_bytes,
        "page_cache_advisory_calls": runtime.page_cache_advisory_calls,
        "safetensors_mapping_open_count": runtime.safetensors_mapping_open_count,
        "safetensors_mapping_close_count": runtime.safetensors_mapping_close_count,
        "resident_device_bytes": runtime.resident_device_bytes,
        "persistent_host_model_bytes": runtime.persistent_host_model_bytes,
        "host_resident_tensor_keys": runtime._host_resident_tensor_keys,
        "cpu_owned_decoder_layers": runtime.cpu_owned_decoder_layers,
        "unexplained_persistent_host_mirror_bytes":
            runtime.persistent_host_model_bytes,
        "whole_shard_sentinel_calls": runtime.whole_shard_sentinel_calls,
        "cuda_allocated_bytes":
            int(torch.cuda.memory_allocated(runtime.device)),
        "cuda_total_memory_bytes": runtime.cuda_total_memory_bytes,
        "tied_embedding_materializations":
            getattr(runtime.block, "tied_embedding_materializations", None),
        "state_ownership": runtime.state_ownership,
        "process_after_realization": runtime.process_after_realization,
        "non_claims": [
            "No PREFILL, decode, or generate was executed.",
            "No fixture inference; no serving claim (Arm C not executed).",
            "No holdout material touched.",
        ],
    }
    Path(args.report).write_bytes(json.dumps(report, indent=1).encode())
    print("REALIZE_OK", args.participant, runtime.fetched_bytes)
    return 0


PLAN_SPEC = {
    "dense.6171f32b4413.stage-1": (0, 16),
    "dense.6171f32b4413.stage-2": (16, 32),
    "dense.6171f32b4413.stage-3": (32, 48),
}


def OBSERVED_UUID():
    """Resolve the CUDA-visible device UUID mechanically.

    nvidia-smi -i 0 ignores CUDA_VISIBLE_DEVICES (physical index), so the
    selector must be the env-pinned UUID itself; nvidia-smi resolves a UUID
    selector and fails if it is not a present device. The returned value is
    the device torch cuda:0 is bound to.
    """
    import subprocess
    pinned = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not pinned.startswith("GPU-"):
        raise RuntimeError(f"CUDA_VISIBLE_DEVICES not UUID-pinned: {pinned!r}")
    resolved = subprocess.check_output(
        ["nvidia-smi", "-i", pinned, "--query-gpu=uuid",
         "--format=csv,noheader"], text=True).strip()
    if resolved != pinned:
        raise RuntimeError(
            f"CUDA device binding drift: pinned {pinned} resolved {resolved}")
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
