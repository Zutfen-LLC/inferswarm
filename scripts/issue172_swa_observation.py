#!/usr/bin/env python3
"""Issue #172 — SWA ownership pristine-state observation (inferswarm01).

Observes the accepted #166 ownership seam on the REAL deployed stage
runtime (read-only; no #157 deep capture; no execution-bearing change):

- builds stage 1 exactly as the serving path does (same chain-plan
  block, model view, GPU 0);
- pristine observation after reset_session_state(): allocated == 0,
  live_mapped_slots == 0, full free-list;
- a scripted 65-row two-chunk prefill session (64 + 1, the smallest
  long-remainder unit) through the SAME public methods the chain uses
  (prefill/decode), observing after each chunk that the ownership
  frontier covers exactly the executed range and NO mapping slot
  resolves to the reserved sentinel 0;
- reset again: wholesale release (allocated 0, live 0, free-list
  conserved) — no stale ownership survives reset/reuse;
- a second fresh session (fresh qualified session state) after the
  reset proves reuse validity (frontier starts at 0 again).

Runs under the deployed producer at 6202eee; every observation is a
pure read of swa_session_ownership_report()/pool state.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PRODUCER = "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469"


def main() -> int:
    repo = Path("/home/zutfen/FreeToken")
    chain_plan_path = Path(
        "/srv/inferswarm/state/arm-c-requal-172/chain-plan.json")
    running = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "rev-parse", "HEAD"], text=True).strip()
    if running != PRODUCER:
        raise SystemExit(f"producer drift {running}")

    sys.path.insert(0, str(repo))
    sys.path.insert(0, str(repo / "python"))
    sys.path.insert(0, str(repo / "benchmarks"))

    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = (
        "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099")
    import torch  # noqa: F401
    from freetoken.distributed import set_tp_info, try_get_tp_info
    from freetoken.layers.rotary import set_rope_device
    if try_get_tp_info() is None:
        set_tp_info(rank=0, size=1)
    set_rope_device(torch.device("cuda:0"))
    from benchmarks.inferswarm_r6.stage_runtime import GemmaDenseStage

    plan = json.loads(chain_plan_path.read_text())
    block = plan["blocks"][0]
    shared = plan.get("declared_shared_state")
    observations = {}

    stage = GemmaDenseStage(
        role="first",
        adapter_data={**block,
                      "declared_shared_state": shared,
                      "runtime_capacity_tokens":
                          plan["runtime_capacity_tokens"]},
        model_path="/srv/inferswarm/state/arm-c/model-view",
    )

    def snap(label):
        report = stage.swa_session_ownership_report()
        pool = stage._swa_pool()
        mapping = pool.full_to_swa_index_mapping
        allocated = report["allocated"]
        # the invariant concerns LIVE positions: every mapped position in
        # the owned range [0, allocated) must resolve to a real slot
        # (never the reserved sentinel 0); positions beyond the frontier
        # are legitimately sentinel by construction.
        live_range_sentinel = int((mapping[:allocated] == 0).sum()) if (
            allocated and mapping.shape[0] >= allocated) else 0
        observations[label] = {
            **report,
            "live_positions_resolving_to_sentinel_slot0":
                live_range_sentinel,
        }
        return observations[label]

    # pristine session state
    stage.reset_session_state()
    snap("pristine_after_reset_1")

    # two-chunk prefill session: 64 + 1 rows (g170-01 geometry), then a
    # decode step at position 65
    tokens_1 = [2] + [100] * 63
    tokens_2 = [101]
    stage.prefill(tokens_1, None, 0)
    snap("after_chunk_1_64_rows")
    stage.prefill(tokens_2, None, 64)
    snap("after_chunk_2_1_row")
    stage.decode(int(101), 65)
    snap("after_decode_position_65")

    # wholesale release
    stage.reset_session_state()
    snap("after_reset_following_session")

    # fresh reuse session: 53-row single-chunk
    stage.reset_session_state()
    stage.prefill([2] + [100] * 51, None, 0)
    snap("reuse_session_after_reset")

    verdicts = {
        "pristine_is_zeroed": (
            observations["pristine_after_reset_1"]["allocated"] == 0
            and observations["pristine_after_reset_1"]["live_mapped_slots"]
            == 0),
        "chunk1_frontier": (
            observations["after_chunk_1_64_rows"]["allocated"] == 64),
        "chunk2_frontier": (
            observations["after_chunk_2_1_row"]["allocated"] == 65),
        "decode_extends_by_one": (
            observations["after_decode_position_65"]["allocated"] == 66),
        "no_sentinel_resolution_while_live": all(
            obs["live_positions_resolving_to_sentinel_slot0"] == 0
            for k, obs in observations.items()
            if k in ("after_chunk_1_64_rows", "after_chunk_2_1_row",
                     "after_decode_position_65")),
        "reset_releases_wholesale": (
            observations["after_reset_following_session"]["allocated"] == 0
            and
            observations["after_reset_following_session"]
            ["live_mapped_slots"] == 0),
        "reuse_starts_fresh": (
            observations["reuse_session_after_reset"]["allocated"] == 52),
        "ownership_conserved": all(
            obs["live_mapped_slots"] + obs["available"]
            == observations["pristine_after_reset_1"]["available"]
            for obs in observations.values()),
    }
    record = {
        "schema": ("inferswarm.issue172.arm-c-requal."
                   "swa-ownership-observation/1"),
        "producer": running,
        "seam": "swa_session_ownership_report (accepted #166 pure-read)",
        "session_geometry": "64+1 two-chunk then decode at 65; reuse 52",
        "observations": observations,
        "verdicts": verdicts,
        "passed": all(verdicts.values()),
    }
    out = Path(
        "/srv/inferswarm/state/arm-c-requal-172/swa-ownership.json")
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": record["passed"],
                      "verdicts": verdicts}))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
