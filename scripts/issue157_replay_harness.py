#!/usr/bin/env python3
"""Issue #157 exact-state chunk-2 replay harness (DIAGNOSTIC_ONLY).

Phase 3 + Phase 4 one-variable interventions.  Runs INSIDE a dedicated
stage-1-role process (spawned with CUDA_VISIBLE_DEVICES=gpu-0) so the
real layer/kernels execute on the real substrate, but the full serving
lifecycle (chain spawn, wire, allocator history across stages) is
removed.  Method (issue #157 Phase 3, for at least Anchor A):

  1. materialize the frozen stage-1 runtime (selective load from the
     pinned checkpoint — the same constructor path the chain uses);
  2. execute chunk 1 (64 rows) fresh and capture/freeze the stable
     post-chunk-1 state needed for chunk 2 (KV pool bytes for owned
     layers + any runtime state);
  3. per trial: construct fresh replay state from the frozen capture
     (clone KV bytes into the live pool; zero elsewhere), then execute
     the EXACT chunk-2 logical operation (same tokens, same positions,
     same phase) repeatedly;
  4. compare earliest declared checkpoints bytewise (via the #157
     instrumentation installed in this process);
  5. prove no mutated-state reuse: after each trial, assert the live
     KV state was re-derived from the frozen capture (trial uses fresh
     bytes; a control byte planted in an unused slot must vanish).

Interventions (Phase 4; one variable at a time, paired against the
unchanged control from identical state, counterbalanced order):
  sync    explicit torch.cuda.synchronize() immediately before the
          layer-0 attention op of the chunk-2 call (A).
  scratch deterministic zero-init of the decode-route scratch buffers
          (attn_logits/attn_lse/num_kv_splits) before the chunk-2 call
          (B; only concrete buffers proven to participate).
  route   mechanical route verification + legal alternate-route paired
          comparison: same captured pre-chunk state, same rows/
          positions/KV authority, current route vs the alternate
          semantically valid extend route (decode->extend for 1-row
          chunks via a phase-label-only difference is NOT taken — the
          alternate route here is generic paged_attention, reachable
          without contract change only when is_decode stays False; if
          forcing is required, records INTERVENTION_NOT_LEGAL).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DIAG_SCHEMA = "inferswarm.issue157.replay-harness/1"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"


def run(*, repo, case_id, fixture_rows, accepted_ids, first_divergent,
        trials: int, out_dir: str, run_id: str, model_path: str,
        chain_plan_path: str, intervention: str | None = None) -> dict:
    """Spawn the in-process harness on gpu-0 and collect its result."""
    import subprocess

    scripts_dir = Path(__file__).resolve().parent
    harness_script = scripts_dir / "issue157_replay_worker.py"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / f"{run_id}-replay-result.json"
    cmd = [
        "/srv/inferswarm/repos/FreeToken/.venv/bin/python",
        str(harness_script),
        "--case-id", case_id,
        "--trials", str(trials),
        "--out", str(result_path),
        "--model", model_path,
        "--chain-plan", chain_plan_path,
        "--intervention", intervention or "none",
    ]
    env = {
        **os.environ,
        "CUDA_VISIBLE_DEVICES": "0",
        "PYTHONPATH": f"{repo}/python:{repo}/benchmarks:{repo}",
        "TMPDIR": "/var/tmp",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ISSUE157_RUN_ID": run_id,
    }
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                          timeout=3600)
    if proc.returncode != 0:
        return {
            "schema": DIAG_SCHEMA,
            "classification": DIAGNOSTIC_ONLY,
            "run_id": run_id,
            "case": case_id,
            "status": "HARNESS_FAILED",
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    return json.loads(result_path.read_text())


if __name__ == "__main__":
    print("use issue157_probe_driver.py --probe REPLAY", file=sys.stderr)
    raise SystemExit(2)
