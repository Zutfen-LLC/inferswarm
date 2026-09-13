#!/usr/bin/env python3
"""Issue #157 probe driver — chunk-2 extend-path diagnosis (DIAGNOSTIC_ONLY).

Physical authorization: InferSwarm issue #157 (fresh diagnostic GPU/model
execution against the required multi-chunk extend-prefill path; NO Arm-C
requalification, NO h109 access, NO contract change).

Phases (issue #157):
  BASE  baseline reproduction — Anchor A (in-session variable),
        Anchor B (session-stable/cross-session-different), stable C2
        control; fresh realizations + within-realization repeats.
  REPLAY exact-state chunk-2 replay — capture post-chunk-1 stage-1
        state, rebuild fresh replay state per trial, execute the exact
        chunk-2 operation repeatedly, compare earliest checkpoints;
        prove no mutated-state reuse across trials.
  IV-SYNC    one-variable intervention: explicit torch.cuda.synchronize
        + stream dependency before the earliest unstable op (vs the
        unchanged path from identical diagnostic state).
  IV-SCRATCH one-variable intervention: deterministic zero-init of the
        decode-route scratch (attn_logits/attn_lse) vs torch.empty.
  IV-ROUTE   kernel-route observation/mechanical verification + legal
        alternate-route paired comparison where semantics allow.
  IV-BISECT  (only if needed) op-level bisection within layer 0/1.

Every launch: fresh run/attempt ID, labeled DIAGNOSTIC_ONLY, fails
closed through scripts/issue157_binding.py BEFORE any GPU work.
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

import issue157_binding  # noqa: E402  (accepted-authority pins/verifier)

DIAG_SCHEMA = "inferswarm.issue157.probe/1"
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"

MODEL_PATH = "/srv/models/gemma-r6"
ENVIRONMENT_PATH = "/srv/inferswarm/state/arm-c/environment.json"
FIXTURE_PATH = "/srv/inferswarm/state/arm-c-retry/prompt-fixture.json"
CHAIN_PLAN_PATH = "/srv/inferswarm/state/arm-c/chain-plan.json"
ATTEMPT_DIRECT_RUN = (
    "/srv/inferswarm/state/arm-c-retry/attempts/armc-retry-physical-1/"
    "direct/direct-run.json"
)
SCRIPTS_DIR = str(Path(__file__).resolve().parent)

# Frozen anchors (bound in issue157_binding from accepted #137 evidence)
ANCHOR_A = issue157_binding.ANCHOR_A          # c109-04-02-047 (67 = 64+3)
ANCHOR_B = issue157_binding.ANCHOR_B          # c109-04-06-074 (66 = 64+2)
STABLE_CONTROL = issue157_binding.STABLE_CONTROL  # c109-03-04-003 (53)

ACCEPTED_FIRST_DIVERGENT = {
    k: v for k, v in issue157_binding.ACCEPTED_FIRST_DIVERGENT.items()
    if not k.endswith("-047") or k == "c109-04-02-047"
}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":")).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def software_snapshot() -> dict:
    import torch

    return {
        "executable": sys.executable,
        "python": ".".join(map(str, sys.version_info[:3])),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "driver": torch.cuda.get_device_name(0) and subprocess.check_output(
            ["nvidia-smi", "--query-gpu=driver_version",
             "--format=csv,noheader", "-i", "0"], text=True
        ).strip(),
        "cudnn_deterministic": bool(torch.backends.cudnn.deterministic),
        "cudnn_benchmark": bool(torch.backends.cudnn.benchmark),
        "deterministic_algorithms": bool(
            torch.are_deterministic_algorithms_enabled()
        ),
        "deterministic_algorithms_warn_only": bool(
            torch.is_deterministic_algorithms_warn_only_enabled()
        ),
        "tf32_matmul": bool(torch.backends.cuda.matmul.allow_tf32),
        "tf32_cudnn": bool(torch.backends.cudnn.allow_tf32),
        "mp_start_method": torch.multiprocessing.get_all_start_methods()[0]
        if hasattr(torch.multiprocessing, "get_all_start_methods") else None,
    }


# ---------------------------------------------------------------------------
# Chain construction (mirrors chain_runtime.realize_dense_chain exactly,
# with the #157 instrumentation env injected into the stage processes).
# ---------------------------------------------------------------------------

def build_chain(
    repo: Path,
    plan_path: str,
    model_path: str,
    host: str,
    port: int,
    *,
    instrument: bool = False,
    instrument_dir: str | None = None,
    run_id: str | None = None,
    attempt: int = 0,
):
    import multiprocessing

    from benchmarks.inferswarm_r6.stage_chain import (
        GemmaStageChainRuntime,
        StageClient,
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
                    env_extra = {}
                    if instrument:
                        env_extra = {
                            "ISSUE157_STAGE_INSTRUMENT": "1",
                            "ISSUE157_OUT_DIR": instrument_dir,
                            "ISSUE157_RUN_ID": run_id,
                            "ISSUE157_ATTEMPT": str(attempt),
                            "ISSUE157_SCRIPTS_DIR": SCRIPTS_DIR,
                            "ISSUE157_STAGE_ROLE": (
                                f"stage{index + 1}-{block['spec']['role']}"
                            ),
                        }
                    self.stages.append(
                        _InstrumentedStageClient(
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
                            env_extra=env_extra,
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
        "remote_last_stage": getattr(chain.stages[-1], "launch_identity",
                                     None),
        "build_chain_pid": os.getpid(),
    }
    return chain, realization_identity


class _InstrumentedStageClient:
    """StageClient variant that injects the #157 instrumentation env into
    the spawned stage process (PYTHONPATH covers the shim dir; the shim
    itself is activated by ISSUE157_STAGE_INSTRUMENT)."""

    def __init__(self, context, *, role, adapter_data, model_path,
                 gpu_index: int, env_extra: dict):
        import multiprocessing.connection as mp_conn  # noqa: F401

        from benchmarks.inferswarm_r6.stage_chain import StageClient

        self._inner = None
        self._env_extra = env_extra
        self.role = role
        # Build the pipe + process ourselves so we control the env.
        parent, child = context.Pipe()
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu_index)}
        env.update(env_extra)
        if env_extra.get("ISSUE157_STAGE_INSTRUMENT") == "1":
            # sitecustomize discovery: prepend the scripts dir holding the
            # shim + instrumentation module
            env["PYTHONPATH"] = (
                f"{SCRIPTS_DIR}:{env.get('PYTHONPATH', '')}"
            )
        import multiprocessing

        self.parent = parent
        self.process = context.Process(
            target=_env_stage_entry,
            args=(env,),
            kwargs={
                "role": role,
                "adapter_data": adapter_data,
                "model_path": model_path,
                "connection": child,
            },
        )
        self.process.start()
        self._inner = None  # unified interface below

    def recv(self):
        return self.parent.recv()

    def send(self, message):
        self.parent.send(message)

    def request(self, message):
        self.send(message)
        response = self.recv()
        if isinstance(response, dict) and response.get("op") == "ERROR":
            raise RuntimeError(f"stage {self.role} error: {response}")
        return response

    def shutdown(self):
        try:
            self.send({"op": "SHUTDOWN"})
            self.parent.recv()
        except (BrokenPipeError, EOFError, OSError):
            pass
        self.process.join(timeout=30)
        if self.process.is_alive():
            self.process.terminate()


def _env_stage_entry(env: dict, *, role, adapter_data, model_path,
                     connection):
    os.environ.update({k: v for k, v in env.items()
                       if k != "CUDA_VISIBLE_DEVICES"})
    os.environ["CUDA_VISIBLE_DEVICES"] = env["CUDA_VISIBLE_DEVICES"]
    if env.get("ISSUE157_STAGE_INSTRUMENT") == "1":
        sys.path.insert(0, env["ISSUE157_SCRIPTS_DIR"])
        import issue157_instrumentation

        issue157_instrumentation.install(
            env["ISSUE157_OUT_DIR"],
            env.get("ISSUE157_STAGE_ROLE", role),
        )
    from benchmarks.inferswarm_r6.stage_chain import _stage_entry

    _stage_entry(role=role, adapter_data=adapter_data,
                 model_path=model_path, connection=connection)


# ---------------------------------------------------------------------------
# Replay invocation (RESET discipline identical to generate())
# ---------------------------------------------------------------------------

def replay_call(chain, replay_input, chunk=64, capture_step=None):
    import torch

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
                    "token_ids": replay_input[position:position + count],
                    "position": position,
                })
            else:
                response = stage.request({
                    "op": "PREFILL",
                    "hidden": hidden,
                    "position": position,
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


def chunk1_boundary_digest(chain):
    """Digest of the stable 64-row first-chunk stage-1 boundary."""
    pass  # boundary digests come from replay_call's collection


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="/srv/inferswarm/repos/FreeToken")
    parser.add_argument("--probe", required=True,
                        choices=["BASE", "REPLAY", "IV-SYNC",
                                 "IV-SCRATCH", "IV-ROUTE"])
    parser.add_argument("--realizations", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--replay-trials", type=int, default=6)
    parser.add_argument("--last-stage-host", default="10.0.0.219")
    parser.add_argument("--last-stage-port", type=int, default=18485)
    parser.add_argument("--last-stage-ledger",
                        default="/srv/inferswarm/state/issue157/ready")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--instrument-dir", default=None)
    parser.add_argument("--keep-tensors", action="store_true")
    args = parser.parse_args(argv)

    global torch
    import torch  # noqa: F401

    repo = Path(args.repo).resolve()

    # -- PRE-EXECUTION accepted-authority binding (fails closed) ----------
    producer_modules = issue157_binding.verify_producer_checkout(repo)
    baseline_inputs = issue157_binding.verify_baseline_inputs({
        "prompt-fixture.json": Path(FIXTURE_PATH),
        "environment.json": Path(ENVIRONMENT_PATH),
        "chain-plan.json": Path(CHAIN_PLAN_PATH),
        "direct-run.json": Path(ATTEMPT_DIRECT_RUN),
    })
    issue157_binding.verify_checkpoint(
        Path(MODEL_PATH) / "model.safetensors")
    software = software_snapshot()
    issue157_binding.verify_software(software,
                                     interpreter_path=software["executable"])
    gpu_uuids_01 = [
        u.strip() for u in subprocess.check_output(
            ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            text=True).splitlines()
    ]
    issue157_binding.verify_geometry({"inferswarm01": gpu_uuids_01})
    driver_sha = sha256_bytes(Path(__file__).read_bytes())
    instrumentation_sha = sha256_bytes(
        (Path(__file__).parent / "issue157_instrumentation.py").read_bytes()
    )
    shim_sha = sha256_bytes(
        (Path(__file__).parent / "issue157_sitecustomize.py").read_bytes()
    )
    binding_sha = sha256_bytes(Path(issue157_binding.__file__).read_bytes())

    fixture = json.loads(Path(FIXTURE_PATH).read_text())
    rows = {r["case_id"]: r for r in fixture["cases"]}
    accepted = json.loads(Path(ATTEMPT_DIRECT_RUN).read_text())
    accepted_ids = {
        e["case_id"]: [c["committed_token"] for c in e["calls"]]
        for e in accepted["invocation_transcript"]
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = f"i157-{args.probe}-{int(time.time())}"
    record = {
        "schema": DIAG_SCHEMA,
        "classification": DIAGNOSTIC_ONLY,
        "run_id": run_id,
        "probe": args.probe,
        "issue_authorization": 157,
        "producer": producer_modules["producer"],
        "hostname": os.uname().nodename,
        "started_at_ns": time.time_ns(),
        "driver": {
            "sha256": driver_sha,
            "invocation": ["issue157_probe_driver.py", *sys.argv[1:]],
            "instrumentation_sha256": instrumentation_sha,
            "sitecustomize_sha256": shim_sha,
            "binding_module_sha256": binding_sha,
        },
        "authority": {
            "baseline_inputs": baseline_inputs,
            "producer_modules": producer_modules["modules"],
            "software": software,
            "geometry": {
                "inferswarm01": gpu_uuids_01,
            },
            "subject": issue157_binding.SUBJECT,
            "anchors": {
                "anchor_a": ANCHOR_A,
                "anchor_b": ANCHOR_B,
                "stable_control": STABLE_CONTROL,
            },
        },
    }

    def target_replay(case_id):
        k = ACCEPTED_FIRST_DIVERGENT.get(case_id, 0)
        prompt = list(rows[case_id]["rendered_prompt_token_ids"])
        return prompt + accepted_ids[case_id][:k], k

    instrument_dir = args.instrument_dir or str(out / "instrumentation")
    observations = []
    recon = None

    def reconcile_last_stage() -> list[dict]:
        ledger_dir = Path(args.last_stage_ledger)
        launches = []
        if not ledger_dir.is_dir():
            record.setdefault("unavailable_facts", {})[
                "remote_last_stage_ledger"] = "not_retained: dir absent"
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
                    <= record.get("completed_at_ns", time.time_ns() + 10**18):
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

    def run_baseline_case(chain_rip, case_id, repeats):
        """Within-realization repeats for one case (fresh RESET each)."""
        replay, k = target_replay(case_id)
        per = []
        for m in range(repeats):
            committed, spec, digests = replay_call(chain_rip, replay)
            per.append({"repeat": m, "committed_step0": committed,
                        "speculative_step1": spec,
                        "boundary_digests": digests})
        return per

    if args.probe == "BASE":
        # Anchor A, Anchor B, stable control: fresh realizations x
        # within-realization repeats (issue #157 Phase 2).  #137 showed
        # BOTH dimensions matter (per-execution + per-session variance).
        for r in range(args.realizations):
            chain, rid = build_chain(
                repo, CHAIN_PLAN_PATH, MODEL_PATH,
                args.last_stage_host, args.last_stage_port,
                instrument=True, instrument_dir=instrument_dir,
                run_id=run_id, attempt=r,
            )
            try:
                row = {"realization": r, "realization_identity": rid}
                for case in (ANCHOR_A, ANCHOR_B, STABLE_CONTROL):
                    row[case] = run_baseline_case(chain, case, args.repeats)
                observations.append(row)
            finally:
                chain.close()
            time.sleep(2)  # launcher restart window for the last stage
        recon = reconcile_last_stage()

    elif args.probe == "REPLAY":
        # Exact-state chunk-2 replay harness (issue #157 Phase 3) for
        # Anchor A: run in the FIRST stage's own process space via a
        # dedicated diagnostic subprocess (see issue157_replay_harness).
        from importlib import import_module

        harness = import_module("issue157_replay_harness")
        result = harness.run(
            repo=repo,
            case_id=ANCHOR_A,
            fixture_rows=rows,
            accepted_ids=accepted_ids,
            first_divergent=ACCEPTED_FIRST_DIVERGENT[ANCHOR_A],
            trials=args.replay_trials,
            out_dir=str(out),
            run_id=run_id,
            model_path=MODEL_PATH,
            chain_plan_path=CHAIN_PLAN_PATH,
        )
        observations.append(result)
        recon = []

    elif args.probe in ("IV-SYNC", "IV-SCRATCH", "IV-ROUTE"):
        from importlib import import_module

        harness = import_module("issue157_replay_harness")
        mode = {
            "IV-SYNC": "sync",
            "IV-SCRATCH": "scratch",
            "IV-ROUTE": "route",
        }[args.probe]
        result = harness.run(
            repo=repo,
            case_id=ANCHOR_A,
            fixture_rows=rows,
            accepted_ids=accepted_ids,
            first_divergent=ACCEPTED_FIRST_DIVERGENT[ANCHOR_A],
            trials=args.replay_trials,
            out_dir=str(out),
            run_id=run_id,
            model_path=MODEL_PATH,
            chain_plan_path=CHAIN_PLAN_PATH,
            intervention=mode,
        )
        observations.append(result)
        recon = []

    record["observations"] = observations
    if recon is not None:
        record["remote_last_stage_launches"] = recon
    record["completed_at_ns"] = time.time_ns()
    record["instrumentation_dir"] = instrument_dir
    out_file = out / f"{run_id}.json"
    out_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"[issue157] {args.probe} complete -> {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
