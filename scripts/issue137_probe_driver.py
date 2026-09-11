#!/usr/bin/env python3
"""Issue #137 Phase 3 — DIAGNOSTIC_ONLY probe driver (runs on inferswarm01).

Fresh diagnostic run identity ``i137-diag-*``; every artifact is marked
DIAGNOSTIC_ONLY.  Uses ONLY the frozen producer 924cd22e… read-only via
its public runtime API — zero producer modification, zero new serving
semantics.  All probes drive the accepted direct-arm invocation contract
(per-call full replay prefill in <=64-row chunks, ``max_new_tokens=2``,
commit step-0, discard step-1).

Probe families (one factor changed per probe):

  A   fresh-realization repeatability.  For a target case's exact
      first-divergent call (replay prefix = prompt + accepted committed
      ids before the position): realize the chain R times (fresh stage
      processes AND fresh last-stage service per realization), execute
      the call FIRST in each realization.  Distribution of committed
      step-0 tokens across realizations discriminates per-realization
      variance (kernel/numerical family) vs a stable per-realization
      answer that differs across arms (lifecycle family).
  A2  within-realization repeat.  Same realized substrate; the same
      call M times with the accepted inter-call RESET discipline.
      Discriminates per-execution nondeterminism.
  B   history sensitivity.  Fresh realization; target call executed (a)
      first, (b) after replaying the accepted case-1..k-1 request
      history (one full stable case's 8 calls), (c) after an
      intervening regime-4 case's accepted calls.  One factor: prior
      history.
  C   chunk-partition intervention.  A historically STABLE short case
      driven with the SAME total input but a synthetic chunk boundary
      at 32 (two chunks: 32 + remainder, both <= 64 wire-legal) vs the
      canonical single chunk, on fresh realizations.  If two-chunking a
      stable input flips its token, the two-chunk prefill path is
      causal independent of prompt length.
  D   boundary localization.  For the target call, arm the frozen #71
      capture (stage-1 after_layer_15, stage-2 after_layer_31, last
      stage final-row fp32 via wire capture_step + LogitCapture) on two
      fresh realizations; compare boundary digests.  Earliest differing
      boundary localizes the divergence stage.

The last-stage service is single-connection: the LAUNCHER (not this
driver) restarts it between realizations; this driver connects per
realization and treats connection-refused as a launcher bug.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

DIAG_SCHEMA = "inferswarm.issue137.diagnostic-probe/1"
PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
ENVIRONMENT_PATH = "/srv/inferswarm/state/arm-c/environment.json"
FIXTURE_PATH = "/srv/inferswarm/state/arm-c-retry/prompt-fixture.json"
CHAIN_PLAN_PATH = "/srv/inferswarm/state/arm-c/chain-plan.json"
MODEL_PATH = "/srv/models/gemma-r6"
ATTEMPT_DIRECT_RUN = (
    "/srv/inferswarm/state/arm-c-retry/attempts/armc-retry-physical-1/"
    "direct/direct-run.json"
)
ACCEPTED_FIRST_DIVERGENT = {
    "c109-04-01-026": 4,
    "c109-04-02-047": 0,
    "c109-04-03-040": 2,
    "c109-04-04-024": 3,
    "c109-04-05-043": 0,
    "c109-04-06-074": 0,
}
# Stable-case controls default to position 0 (first call of the case).
STABLE_POSITION_0 = 0


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":")).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_frozen_producer(repo: Path) -> str:
    running = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "status", "--porcelain"], text=True)
    if status:
        raise SystemExit("DIAG_FAIL: producer tree dirty")
    if running != PRODUCER:
        raise SystemExit(f"DIAG_FAIL: producer {running} != {PRODUCER}")
    return running


def build_chain(repo: Path, plan_path: str, model_path: str,
                host: str, port: int, *, arm_capture: bool = False,
                capture_out_dir: str | None = None,
                capture_after_layers=()):
    """Compose GemmaStageChainRuntime exactly as chain_runtime does."""
    import multiprocessing

    from benchmarks.inferswarm_r6.stage_chain import (
        GemmaStageChainRuntime, StageClient,
    )
    from benchmarks.inferswarm_r6.wire_client import RemoteLastStageClient

    plan = json.loads(Path(plan_path).read_text())
    shared = plan.get("declared_shared_state")
    context = multiprocessing.get_context("spawn")

    class _Chain(GemmaStageChainRuntime):
        def __init__(self):
            self.stages = []
            try:
                for index, block in enumerate(plan["blocks"][:-1]):
                    self.stages.append(
                        StageClient(
                            context,
                            role="first" if index == 0 else "middle",
                            adapter_data={
                                **block,
                                "declared_shared_state": (
                                    shared if index == 0 else None),
                                "runtime_capacity_tokens":
                                    plan["runtime_capacity_tokens"],
                            },
                            model_path=model_path,
                            gpu_index=index,
                        ))
                last = None
                for _attempt in range(120):
                    try:
                        last = RemoteLastStageClient(
                            host=host, port=port,
                            experiment_id=plan["digest"],
                            connect_timeout=600.0,
                        )
                        break
                    except ConnectionRefusedError:
                        time.sleep(5)
                if last is None:
                    raise RuntimeError(
                        "last-stage service never became reachable")
                self.stages.append(last)
                self.ready = []
                for stage in self.stages[:-1]:
                    ready = stage.recv()
                    if ready.get("op") == "ERROR":
                        raise RuntimeError(f"stage failed: {ready}")
                    self.ready.append(ready)
                self.ready.append(
                    {"op": "READY", "role": "last", "remote": True})
            except BaseException:
                for stage in self.stages:
                    stage.shutdown()
                raise
            self._sessions = []
            self._closed = False
            self.reclamation_report = {}

    chain = _Chain()
    if arm_capture:
        gpu_uuids = [
            subprocess.check_output(
                ["nvidia-smi", "-i", str(i), "--query-gpu=uuid",
                 "--format=csv,noheader"], text=True).strip()
            for i in (0, 1)
        ]
        for stage_index, (stage, uuid) in enumerate(
                zip(chain.stages[:-1], gpu_uuids)):
            coarse = 15 if stage_index == 0 else 31
            stage.request({
                "op": "ARM_CAPTURE",
                "out_dir": capture_out_dir,
                "tag": f"i137-stage{stage_index + 1}",
                "gpu_uuid": uuid,
                "after_layers": sorted({coarse} | set(capture_after_layers)),
            })
    return chain


def replay_call(chain, replay_input, chunk=64, capture_step=None):
    """Accepted replay-prefill invocation; returns (committed, spec,
    boundary_digests)."""
    # RESET discipline identical to GemmaStageChainRuntime.generate
    for stage in chain.stages:
        if hasattr(stage, "request"):
            stage.request({"op": "RESET"})
        else:
            stage.send({"op": "RESET"})
            stage.recv()
    position = 0
    total = len(replay_input)
    token_id = None
    boundary_digests = []
    while position < total:
        count = min(chunk, total - position)
        hidden = None
        for index, stage in enumerate(chain.stages):
            last_chunk = position + count >= total
            if index == 0:
                response = stage.request({
                    "op": "PREFILL",
                    "token_ids":
                        replay_input[position:position + count],
                    "position": position,
                    **({"capture_step": capture_step}
                       if capture_step is not None and last_chunk else {}),
                })
            else:
                response = stage.request({
                    "op": "PREFILL",
                    "hidden": hidden,
                    "position": position,
                    **({"capture_step": capture_step}
                       if capture_step is not None and last_chunk else {}),
                })
            if response.get("op") == "TOKEN_RESULT":
                token_id = response["token_id"]
                break
            hidden = response["hidden"]
            boundary_digests.append({
                "stage_out": index,
                "position": position,
                "sha256": sha256_bytes(
                    hidden.detach().contiguous().view(torch.uint8)
                    .numpy().tobytes()),
                "rows": int(hidden.shape[0]),
            })
        position += count
    if token_id is None:
        raise RuntimeError("chain ended without a token result")
    committed = int(token_id)
    # speculative step-1 (decode) exactly as generate() does
    spec = None
    if total >= 1:
        hidden = None
        for index, stage in enumerate(chain.stages):
            if index == 0:
                response = stage.request({
                    "op": "DECODE",
                    "token_id": committed,
                    "position": total,
                })
            else:
                response = stage.request({
                    "op": "DECODE",
                    "hidden": hidden,
                    "position": total,
                })
            if response.get("op") == "TOKEN_RESULT":
                spec = int(response["token_id"])
                break
            hidden = response["hidden"]
    return committed, spec, boundary_digests


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="/srv/inferswarm/repos/FreeToken")
    parser.add_argument("--probe", required=True,
                        choices=["A", "A2", "B", "C", "D", "D2"])
    parser.add_argument("--case", default="c109-04-02-047")
    parser.add_argument("--stable-case", default="c109-03-04-003",
                        help="probe C target (historically stable)")
    parser.add_argument("--history-case", default="c109-01-01-045",
                        help="probe B prior-history case (stable regime 1)")
    parser.add_argument("--realizations", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--last-stage-host", default="10.0.0.219")
    parser.add_argument("--last-stage-port", type=int, default=18485)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    global torch
    import torch  # noqa: F401  (boundary digest path)

    repo = Path(args.repo).resolve()
    producer = require_frozen_producer(repo)
    fixture = json.loads(Path(FIXTURE_PATH).read_text())
    rows = {r["case_id"]: r for r in fixture["cases"]}
    accepted = json.loads(Path(ATTEMPT_DIRECT_RUN).read_text())
    accepted_ids = {
        e["case_id"]: [c["committed_token"] for c in e["calls"]]
        for e in accepted["invocation_transcript"]
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = f"i137-diag-{args.probe}-{int(time.time())}"
    record = {
        "schema": DIAG_SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "run_id": run_id,
        "probe": args.probe,
        "producer": producer,
        "hostname": os.uname().nodename,
        "started_at_ns": time.time_ns(),
        "inputs": {
            "fixture_sha256": sha256_bytes(
                Path(FIXTURE_PATH).read_bytes()),
            "chain_plan_sha256": sha256_bytes(
                Path(CHAIN_PLAN_PATH).read_bytes()),
            "environment_sha256": sha256_bytes(
                Path(ENVIRONMENT_PATH).read_bytes()),
            "accepted_direct_run_sha256": sha256_bytes(
                Path(ATTEMPT_DIRECT_RUN).read_bytes()),
        },
        "software": json.loads(subprocess.check_output(
            [str(Path(repo) / ".venv/bin/python"), "-c",
             "import json,torch,sys;"
             "print(json.dumps({'python':sys.version,"
             "'torch':torch.__version__,"
             "'cuda':torch.version.cuda}))"],
            text=True)),
    }

    def target_replay(case_id):
        k = ACCEPTED_FIRST_DIVERGENT.get(case_id, STABLE_POSITION_0)
        prompt = list(rows[case_id]["rendered_prompt_token_ids"])
        return prompt + accepted_ids[case_id][:k], k

    observations = []
    replay = None
    if args.probe in ("A", "A2", "B", "D", "D2"):
        replay, k = target_replay(args.case)
        record["target_call"] = {
            "case_id": args.case,
            "first_divergent_position": k,
            "replay_len": len(replay),
            "replay_sha256": sha256_bytes(canonical(replay)),
        }

    if args.probe == "A":
        for r in range(args.realizations):
            chain = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                args.last_stage_host,
                                args.last_stage_port)
            try:
                committed, spec, _ = replay_call(chain, replay)
                observations.append({
                    "realization": r,
                    "committed_step0": committed,
                    "speculative_step1": spec,
                })
            finally:
                chain.close()
            time.sleep(2)  # allow the launcher to restart the last stage

    elif args.probe == "A2":
        chain = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                            args.last_stage_host, args.last_stage_port)
        try:
            per = []
            for m in range(args.repeats):
                committed, spec, _ = replay_call(chain, replay)
                per.append({"repeat": m,
                            "committed_step0": committed,
                            "speculative_step1": spec})
            observations.append({"realization": 0, "repeats": per})
        finally:
            chain.close()

    elif args.probe == "B":
        variants = ["fresh", "after_stable_history",
                    "after_divergent_history"]
        for r in range(args.realizations):
            chain = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                args.last_stage_host, args.last_stage_port)
            try:
                per = {}
                # (a) fresh
                committed, spec, _ = replay_call(chain, replay)
                per["fresh"] = {"committed_step0": committed,
                                "speculative_step1": spec}
                # (b) after one stable case's accepted 8-call history
                hist_prompt = list(
                    rows[args.history_case]["rendered_prompt_token_ids"])
                hist_ids = accepted_ids[args.history_case]
                for step in range(8):
                    replay_call(chain, hist_prompt + hist_ids[:step])
                committed, spec, _ = replay_call(chain, replay)
                per["after_stable_history"] = {
                    "committed_step0": committed,
                    "speculative_step1": spec}
                # (c) after an intervening divergent case's accepted
                # calls (full 8, positions 0..7)
                dv_prompt = list(
                    rows[args.case]["rendered_prompt_token_ids"])
                dv_ids = accepted_ids[args.case]
                for step in range(8):
                    replay_call(chain, dv_prompt + dv_ids[:step])
                committed, spec, _ = replay_call(chain, replay)
                per["after_divergent_history"] = {
                    "committed_step0": committed,
                    "speculative_step1": spec}
                observations.append({"realization": r, "variants": per})
            finally:
                chain.close()
            time.sleep(2)

    elif args.probe == "C":
        prompt = list(
            rows[args.stable_case]["rendered_prompt_token_ids"])
        record["target_call"] = {
            "case_id": args.stable_case,
            "prompt_len": len(prompt),
            "replay_sha256": sha256_bytes(canonical(prompt)),
        }
        for r in range(args.realizations):
            chain = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                args.last_stage_host, args.last_stage_port)
            try:
                single, spec_s, _ = replay_call(chain, prompt, chunk=64)
                two, spec_2, _ = replay_call(chain, prompt, chunk=32)
                observations.append({
                    "realization": r,
                    "single_chunk_64": {
                        "committed_step0": single,
                        "speculative_step1": spec_s},
                    "two_chunk_32": {
                        "committed_step0": two,
                        "speculative_step1": spec_2},
                })
            finally:
                chain.close()
            time.sleep(2)

    elif args.probe == "D2":
        replay, k = target_replay(args.case)
        capture_dir = str(out / f"{run_id}-captures")
        Path(capture_dir).mkdir(parents=True, exist_ok=True)
        bisect_layers = [0, 1, 2, 4, 8, 12]
        record["target_call"] = {
            "case_id": args.case,
            "first_divergent_position": k,
            "replay_len": len(replay),
            "replay_sha256": sha256_bytes(canonical(replay)),
            "bisect_after_layers": bisect_layers,
        }
        chain = build_chain(
            repo, CHAIN_PLAN_PATH, MODEL_PATH,
            args.last_stage_host, args.last_stage_port,
            arm_capture=True, capture_out_dir=capture_dir,
            capture_after_layers=bisect_layers,
        )
        try:
            per = []
            for m in range(max(2, args.repeats)):
                committed, spec, digests = replay_call(
                    chain, replay, capture_step=m)
                per.append({
                    "repeat": m,
                    "committed_step0": committed,
                    "speculative_step1": spec,
                    "boundary_digests": digests,
                })
            observations.append({"realization": 0, "repeats": per})
        finally:
            for stage in chain.stages[:-1]:
                stage.request({"op": "SAVE_CAPTURE",
                               "suffix": "d2"})
            chain.close()

    elif args.probe == "D":
        replay, k = target_replay(args.case)
        capture_dir = str(out / f"{run_id}-captures")
        Path(capture_dir).mkdir(parents=True, exist_ok=True)
        for r in range(max(2, args.realizations)):
            chain = build_chain(
                repo, CHAIN_PLAN_PATH, MODEL_PATH,
                args.last_stage_host, args.last_stage_port,
                arm_capture=True, capture_out_dir=capture_dir,
                capture_after_layers=(),
            )
            try:
                committed, spec, digests = replay_call(
                    chain, replay, capture_step=r)
                observations.append({
                    "realization": r,
                    "committed_step0": committed,
                    "speculative_step1": spec,
                    "boundary_digests": digests,
                })
            finally:
                # SAVE_CAPTURE persists stage captures
                for stage_index, stage in enumerate(chain.stages[:-1]):
                    stage.request({
                        "op": "SAVE_CAPTURE",
                        "suffix": f"r{r}",
                    })
                chain.close()
            time.sleep(2)

    record["observations"] = observations
    record["completed_at_ns"] = time.time_ns()
    (out / f"{run_id}.json").write_text(json.dumps(
        record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "probe_record": str(out / f"{run_id}.json"),
        "probe": args.probe,
        "case": args.case if args.probe != "C" else args.stable_case,
        "observations": len(observations),
        "classification": DIAGNOSTIC_ONLY,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
