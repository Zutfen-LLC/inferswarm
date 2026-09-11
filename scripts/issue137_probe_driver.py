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
      history.  NOTE (correction): the after_divergent_history arm is
      cumulative after the stable-history arm in the same realization;
      the reducer treats it as an informational observation only —
      it can show history is NOT causal-fORBIDDING but never that
      history has no influence (see conclusions reducer v2).
  C2  corrected chunk-partition intervention (replaces the retired C
      design as the causal evidence; the retained C record stays as
      an informational cumulative observation).  ONE-VARIABLE design:
      for each trial t, realize TWO fresh equivalent substrates and
      execute the target call FIRST in each:
        arm "single": canonical single-chunk prefill (chunk=64);
        arm "two":    identical total input, synthetic chunk boundary
                      at 32 (two wire-legal sub-64 chunks).
      Arm launch order is COUNTERBALANCED across trials (alternating
      by trial parity); within a trial the two arms run on separate
      fresh substrates, so neither arm's execution can condition the
      other through process-lifetime state.  Each arm's substrate is
      bound (stage pids, remote last-stage launch identity) and the
      driver verifies the accepted authority (issue137_binding)
      before any GPU work.
  C   chunk-partition intervention.  A historically STABLE short case
      driven with the SAME total input but a synthetic chunk boundary
      at 32 (two chunks: 32 + remainder, both <= 64 wire-legal) vs the
      canonical single chunk, on fresh realizations.  RETIRED as
      causal evidence (correction): both arms ran cumulatively in one
      realization in a fixed order — retained bytes-only as an
      informational observation; superseded by probe C2.
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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue137_binding  # noqa: E402  (accepted-authority pins/verifier)

DIAG_SCHEMA = "inferswarm.issue137.diagnostic-probe/2"
PRODUCER = issue137_binding.PRODUCER
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


def build_chain(repo: Path, plan_path: str, model_path: str,
                host: str, port: int, *, arm_capture: bool = False,
                capture_out_dir: str | None = None,
                capture_after_layers=(), capture_run_id: str | None = None):
    """Compose GemmaStageChainRuntime exactly as chain_runtime does.

    Returns (chain, realization_identity) where realization_identity
    binds the stage process pids and the remote last-stage launch
    identity for this substrate.
    """
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
    realization_identity = {
        "stage_pids": [
            int(stage.process.pid) for stage in chain.stages[:-1]
        ],
        "stage_pids_distinct_within": (
            len({int(s.process.pid) for s in chain.stages[:-1]})
            == len(chain.stages[:-1])
        ),
        "stage_ready_pids": [
            int(r["runtime_report"]["pid"]) for r in chain.ready[:-1]
        ],
        "remote_last_stage": getattr(chain.stages[-1], "launch_identity", None),
        "build_chain_pid": os.getpid(),
    }
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
                "diagnostic_run_binding": {
                    "run_id": capture_run_id,
                    "capture_dir": capture_out_dir,
                    "classification": DIAGNOSTIC_ONLY,
                },
            })
    return chain, realization_identity


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


def software_snapshot() -> dict:
    """Executing-interpreter numerical-mode snapshot (torch required)."""
    import multiprocessing

    import torch

    return {
        "executable": sys.executable,
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "driver": subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version",
             "--format=csv,noheader"], text=True).strip().splitlines()[0],
        "deterministic_algorithms": bool(
            torch.are_deterministic_algorithms_enabled()),
        "deterministic_algorithms_warn_only": bool(
            torch.is_deterministic_algorithms_warn_only_enabled()),
        "tf32_matmul": bool(torch.backends.cuda.matmul.allow_tf32),
        "tf32_cudnn": bool(torch.backends.cudnn.allow_tf32),
        "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
        "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
        "mp_start_method": multiprocessing.get_start_method(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="/srv/inferswarm/repos/FreeToken")
    parser.add_argument("--probe", required=True,
                        choices=["A", "A2", "B", "C", "C2", "D", "D2"])
    parser.add_argument("--case", default="c109-04-02-047")
    parser.add_argument("--stable-case", default="c109-03-04-003",
                        help="probe C/C2 target (historically stable)")
    parser.add_argument("--history-case", default="c109-01-01-045",
                        help="probe B prior-history case (stable regime 1)")
    parser.add_argument("--realizations", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--trials", type=int, default=6,
                        help="C2: paired-trial count (>=4 recommended)")
    parser.add_argument("--last-stage-host", default="10.0.0.219")
    parser.add_argument("--last-stage-port", type=int, default=18485)
    parser.add_argument("--last-stage-ledger",
                        default="/srv/inferswarm/state/issue137/ready")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    global torch
    import torch  # noqa: F401  (boundary digest path)

    repo = Path(args.repo).resolve()

    # -- PRE-EXECUTION accepted-authority binding (correction C5) -----
    # Fails closed BEFORE any GPU work on: producer commit/tree/module
    # drift, baseline input drift, interpreter/flag drift, GPU drift.
    producer_modules = issue137_binding.verify_producer_checkout(repo)
    baseline_inputs = issue137_binding.verify_baseline_inputs({
        "prompt-fixture.json": Path(FIXTURE_PATH),
        "environment.json": Path(ENVIRONMENT_PATH),
        "chain-plan.json": Path(CHAIN_PLAN_PATH),
        "direct-run.json": Path(ATTEMPT_DIRECT_RUN),
    })
    software = software_snapshot()
    issue137_binding.verify_software(software,
                                     interpreter_path=software["executable"])
    gpu_uuids_01 = [
        u.strip() for u in subprocess.check_output(
            ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            text=True).splitlines()
    ]
    issue137_binding.verify_geometry({"inferswarm01": gpu_uuids_01})
    driver_sha = sha256_bytes(Path(__file__).read_bytes())
    invocation = ["issue137_probe_driver.py", *sys.argv[1:]]

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
        "producer": producer_modules["producer"],
        "hostname": os.uname().nodename,
        "started_at_ns": time.time_ns(),
        "driver": {
            "sha256": driver_sha,
            "invocation": invocation,
            "binding_module_sha256": sha256_bytes(
                Path(issue137_binding.__file__).read_bytes()),
        },
        "authority": {
            "baseline_inputs": baseline_inputs,
            "producer_modules": producer_modules["modules"],
            "software": software,
            "venv_python": software["executable"],
            "geometry": {"inferswarm01": gpu_uuids_01},
        },
        "inputs": {
            "fixture_sha256": baseline_inputs["prompt-fixture.json"],
            "chain_plan_sha256": baseline_inputs["chain-plan.json"],
            "environment_sha256": baseline_inputs["environment.json"],
            "accepted_direct_run_sha256": baseline_inputs["direct-run.json"],
        },
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

    def reconcile_last_stage() -> list[dict]:
        """Reconcile the remote last-stage launch ledger (ready-N.json
        written by the launcher loop on inferswarm03) against this
        run's wall-clock window; returns the launches that served this
        run, binding pid/launch-counter/gpu-uuid/producer."""
        ledger_dir = Path(args.last_stage_ledger)
        launches = []
        if not ledger_dir.is_dir():
            record.setdefault("unavailable_facts", {})[
                "remote_last_stage_ledger"] = (
                    "not_retained: launcher ledger dir absent")
            return launches
        for rf in sorted(ledger_dir.glob("ready-*.json")):
            try:
                entry = json.loads(rf.read_text())
            except (OSError, ValueError):
                continue
            ts = None
            for key in ("ready_at_unix_ns", "started_at_unix_ns"):
                if isinstance(entry.get(key), int):
                    ts = entry[key]
                    break
            if ts is None:
                try:
                    ts = int(rf.stat().st_mtime_ns)
                except OSError:
                    continue
            if record["started_at_ns"] - 60_000_000_000 <= ts \
                    <= record["completed_at_ns"]:
                num = rf.stem.split("-")[1]
                launches.append({
                    "ledger_file": rf.name,
                    "pid": entry.get("pid"),
                    "launch_counter": int(num) if num.isdigit() else None,
                    "gpu_uuid": entry.get("gpu_uuid"),
                    "host": "inferswarm03",
                    "producer_freetoken_sha": entry.get(
                        "producer_freetoken_sha"),
                    "ready_at_unix_ns": ts,
                })
        launches.sort(key=lambda x: x["ready_at_unix_ns"])
        return launches

    def save_and_bind_captures(chain, capture_dir: str, suffix: str,
                               run_id_: str) -> list[str]:
        """SAVE_CAPTURE then post-bind each on-disk manifest to the
        exact diagnostic run + capture dir (correction C5)."""
        bound = []
        for stage in chain.stages[:-1]:
            resp = stage.request({"op": "SAVE_CAPTURE",
                                  "suffix": suffix})
            role = (resp.get("manifest") or {}).get("role")
            if not role:
                continue
            for target in sorted(
                    Path(capture_dir).glob(f"manifest-{role}-*{suffix}*.json")):
                doc = json.loads(target.read_text())
                doc["diagnostic_run_binding"] = {
                    "run_id": run_id_,
                    "capture_dir": capture_dir,
                    "classification": DIAGNOSTIC_ONLY,
                }
                target.write_text(json.dumps(
                    doc, indent=2, sort_keys=True) + "\n")
                bound.append(str(target))
        return bound

    if args.probe == "A":
        for r in range(args.realizations):
            chain, rid = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                     args.last_stage_host,
                                     args.last_stage_port)
            try:
                committed, spec, _ = replay_call(chain, replay)
                observations.append({
                    "realization": r,
                    "committed_step0": committed,
                    "speculative_step1": spec,
                    "realization_identity": rid,
                })
            finally:
                chain.close()
            time.sleep(2)  # allow the launcher to restart the last stage

    elif args.probe == "A2":
        chain, rid = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                 args.last_stage_host,
                                 args.last_stage_port)
        try:
            per = []
            for m in range(args.repeats):
                committed, spec, _ = replay_call(chain, replay)
                per.append({"repeat": m,
                            "committed_step0": committed,
                            "speculative_step1": spec})
            observations.append({"realization": 0, "repeats": per,
                                 "realization_identity": rid})
        finally:
            chain.close()

    elif args.probe == "B":
        for r in range(args.realizations):
            chain, rid = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                     args.last_stage_host,
                                     args.last_stage_port)
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
                # calls (full 8, positions 0..7).  CUMULATIVE on top
                # of (b) in the same realization — informational only.
                dv_prompt = list(
                    rows[args.case]["rendered_prompt_token_ids"])
                dv_ids = accepted_ids[args.case]
                for step in range(8):
                    replay_call(chain, dv_prompt + dv_ids[:step])
                committed, spec, _ = replay_call(chain, replay)
                per["after_divergent_history"] = {
                    "committed_step0": committed,
                    "speculative_step1": spec}
                observations.append({"realization": r, "variants": per,
                                     "realization_identity": rid})
            finally:
                chain.close()
            time.sleep(2)

    elif args.probe == "C":
        # RETIRED design (both arms cumulative in one realization,
        # fixed order): the retained record is informational only;
        # probe C2 is the corrected one-variable intervention.
        prompt = list(
            rows[args.stable_case]["rendered_prompt_token_ids"])
        record["target_call"] = {
            "case_id": args.stable_case,
            "prompt_len": len(prompt),
            "replay_sha256": sha256_bytes(canonical(prompt)),
        }
        record["design_status"] = (
            "retired_cumulative_fixed_order: informational only; "
            "superseded by probe C2 (fresh paired substrates, "
            "counterbalanced order)")
        for r in range(args.realizations):
            chain, rid = build_chain(repo, CHAIN_PLAN_PATH, MODEL_PATH,
                                     args.last_stage_host,
                                     args.last_stage_port)
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
                    "realization_identity": rid,
                })
            finally:
                chain.close()
            time.sleep(2)

    elif args.probe == "C2":
        # CORRECTED one-variable chunk-partition intervention.
        # Per trial: TWO fresh equivalent substrates; the target call
        # is the FIRST correctness-bearing call on each; arm order
        # counterbalanced across trials (even trial: single first;
        # odd trial: two first) so launch order cannot systematically
        # favor either arm.
        prompt = list(
            rows[args.stable_case]["rendered_prompt_token_ids"])
        record["target_call"] = {
            "case_id": args.stable_case,
            "prompt_len": len(prompt),
            "replay_sha256": sha256_bytes(canonical(prompt)),
        }
        record["design"] = {
            "arms": ["single_chunk_64", "two_chunk_32_21"],
            "substrate": ("fresh per arm per trial (stage processes "
                          "spawned new; remote last stage relaunched "
                          "between arms by the launcher loop)"),
            "target_call_position": ("first correctness-bearing call "
                                     "on each substrate"),
            "order": ("counterbalanced by trial parity (even: "
                      "single-first, odd: two-first)"),
            "one_variable": ("chunk partition of an identical total "
                             "input (single 53-row chunk vs 32+21)"),
            "trials": args.trials,
        }
        for t in range(args.trials):
            order = (["single", "two"] if t % 2 == 0
                     else ["two", "single"])
            trial_obs = {"trial": t, "launch_order": order, "arms": {}}
            for arm in order:
                chunk = 64 if arm == "single" else 32
                chain, rid = build_chain(
                    repo, CHAIN_PLAN_PATH, MODEL_PATH,
                    args.last_stage_host, args.last_stage_port)
                try:
                    committed, spec, _ = replay_call(chain, prompt,
                                                     chunk=chunk)
                    trial_obs["arms"][arm] = {
                        "committed_step0": committed,
                        "speculative_step1": spec,
                        "realization_identity": rid,
                    }
                finally:
                    chain.close()
                time.sleep(2)  # launcher restarts the last stage
            observations.append(trial_obs)

    elif args.probe == "D2":
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
        chain, rid = build_chain(
            repo, CHAIN_PLAN_PATH, MODEL_PATH,
            args.last_stage_host, args.last_stage_port,
            arm_capture=True, capture_out_dir=capture_dir,
            capture_after_layers=bisect_layers,
            capture_run_id=run_id,
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
            observations.append({"realization": 0, "repeats": per,
                                 "realization_identity": rid})
        finally:
            record["capture_manifests"] = save_and_bind_captures(
                chain, capture_dir, "d2", run_id)
            chain.close()

    elif args.probe == "D":
        capture_dir = str(out / f"{run_id}-captures")
        Path(capture_dir).mkdir(parents=True, exist_ok=True)
        for r in range(max(2, args.realizations)):
            chain, rid = build_chain(
                repo, CHAIN_PLAN_PATH, MODEL_PATH,
                args.last_stage_host, args.last_stage_port,
                arm_capture=True, capture_out_dir=capture_dir,
                capture_after_layers=(),
                capture_run_id=run_id,
            )
            try:
                committed, spec, digests = replay_call(
                    chain, replay, capture_step=r)
                observations.append({
                    "realization": r,
                    "committed_step0": committed,
                    "speculative_step1": spec,
                    "boundary_digests": digests,
                    "realization_identity": rid,
                })
            finally:
                record.setdefault("capture_manifests", []).extend(
                    save_and_bind_captures(
                        chain, capture_dir, f"r{r}", run_id))
                chain.close()
            time.sleep(2)

    record["observations"] = observations
    record["completed_at_ns"] = time.time_ns()
    record["remote_last_stage_launches"] = reconcile_last_stage()
    (out / f"{run_id}.json").write_text(json.dumps(
        record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "probe_record": str(out / f"{run_id}.json"),
        "probe": args.probe,
        "case": (args.stable_case if args.probe in ("C", "C2")
                 else args.case),
        "observations": len(observations),
        "classification": DIAGNOSTIC_ONLY,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
