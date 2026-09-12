#!/usr/bin/env python3
"""Issue #154 V1-A physical campaign runner (local proving node only).

This is the narrowest correctness-bearing orchestration path for the V1-A
reusable internal participant: preflight, qualification, capability
creation, resource snapshot, generic planning, plan freeze, canonical
execution, accounting, correctness, adapter-sealed canonical proof,
generic canonical observation, and execution receipt.

The accounting reducer and the byte-exact correctness comparator are the
ACCEPTED, BYTE-UNCHANGED V0-C reducers (scripts/v0c_canonical_run.py
parse_accounting and scripts/v0c_correctness.py reduce). No V0-C evidence
is modified; the accepted comparator fixture/reference is consumed
unchanged. This runner never SSHes: it must run directly on the proving
node.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_execution_participant as participant  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402
import v0c_canonical_run as v0c_runner  # noqa: E402
import v0c_correctness as v0c_correctness  # noqa: E402


class RunnerError(RuntimeError):
    """A V1-A campaign invariant was not satisfied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def command(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


# ---------------------------------------------------------------------------
# Stage 1: mechanical preflight. Nothing is trusted from the caller: the
# hostname, runtime source identity, executable hash, model hash/size, BDF
# visibility, and V1-A source hashes are all measured locally.
# ---------------------------------------------------------------------------

V1A_SOURCES = (
    "scripts/v1a_execution_participant.py",
    "scripts/v1a_vulkan_adapter.py",
    "scripts/v1a_runner.py",
    "scripts/v0c_canonical_run.py",
    "scripts/v0c_correctness.py",
)


def preflight(authority: Mapping[str, Any]) -> dict[str, Any]:
    frozen = authority["frozen"]
    measured: dict[str, Any] = {}
    hostname = os.uname().nodename
    measured["hostname"] = hostname
    if hostname != frozen["hostname"]:
        raise RunnerError(f"proving hostname mismatch: {hostname}")
    source = Path(frozen["runtime_source"])
    actual_commit = command(["git", "-c", f"safe.directory={source}", "-C", str(source), "rev-parse", "HEAD"])
    if actual_commit != frozen["runtime_source_commit"]:
        raise RunnerError("runtime source commit mismatch")
    if command(["git", "-c", f"safe.directory={source}", "-C", str(source), "status", "--porcelain"]):
        raise RunnerError("runtime source is dirty")
    executable, model = Path(frozen["executable"]), Path(frozen["model"])
    measured.update({
        "runtime_source_commit": actual_commit,
        "executable": str(executable), "executable_sha256": sha256_file(executable),
        "model": str(model), "model_sha256": sha256_file(model), "model_bytes": model.stat().st_size,
        "v1a_sources": {path: sha256_file(ROOT / path) for path in V1A_SOURCES},
        "repository_head": command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
    })
    expected = {**{k: frozen[k] for k in ("executable_sha256", "model_sha256", "model_bytes")},
                "v1a_sources": {p: frozen["v1a_sources"][p] for p in V1A_SOURCES}}
    if any(measured[k] != v for k, v in expected.items()):
        raise RunnerError("measured frozen identity mismatch")
    # Physical BDF visibility is measured from the host, never asserted.
    bdf = frozen["physical_device_bdf"]
    lspci = command(["lspci", "-s", bdf])
    if not lspci.startswith(bdf):
        raise RunnerError(f"physical device {bdf} is not visible")
    measured["lspci_bdf_line"] = lspci
    if command(["git", "-C", str(ROOT), "status", "--porcelain"]):
        raise RunnerError("correctness-bearing working tree is dirty")
    return measured


# ---------------------------------------------------------------------------
# Stages 2-3: fresh qualification through the generalized seam, capability
# minted only from the adapter-sealed observation.
# ---------------------------------------------------------------------------

def _runtime_argv(frozen: Mapping[str, Any]) -> list[str]:
    return [frozen["executable"], "-m", frozen["model"], "--temp", "0", "--seed", "42",
            "-n", "48", "-ngl", "99", "--device", frozen["selector"], "-lv", "4",
            "-p", frozen["prompt"], "-st"]


def _execute(frozen: Mapping[str, Any], out: Path) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=False)
    runtime_argv = _runtime_argv(frozen)
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    process = subprocess.run(runtime_argv, capture_output=True, text=False, timeout=1800)
    wall_seconds = round(time.monotonic() - t0, 3)
    (out / "stdout.txt").write_bytes(process.stdout)
    (out / "stderr.txt").write_bytes(process.stderr)
    (out / "exit-code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")
    return {"started_utc": started, "wall_seconds": wall_seconds, "argv": runtime_argv,
            "exit_code": process.returncode, "stdout_sha256": digest_bytes(process.stdout),
            "stderr_sha256": digest_bytes(process.stderr), "stdout": process.stdout,
            "stderr": process.stderr.decode("utf-8", errors="strict")}


def qualify(authority: Mapping[str, Any], measured: Mapping[str, Any], out: Path) -> dict[str, Any]:
    frozen = authority["frozen"]
    run = _execute(frozen, out)
    if run["exit_code"] != 0:
        raise RunnerError(f"qualification exit was not clean: {run['exit_code']}")
    observation = adapter.parse_backend_observation(
        stderr=run["stderr"], selector=frozen["selector"], expected_bdf=frozen["physical_device_bdf"],
        node_id=frozen["node_id"], compute_unit_id=frozen["compute_unit_id"],
        memory_resource_id=frozen["memory_resource_id"], execution_unit_id=frozen["execution_unit_id"],
        execution_contract_id=frozen["execution_contract_id"],
        implementation_id=frozen["implementation_id"], evidence_id=frozen["qualification_evidence_id"],
        runtime_identity=frozen["runtime_identity"])
    capability = adapter.capability_record(
        node_id=frozen["node_id"], compute_unit_id=frozen["compute_unit_id"],
        memory_resource_id=frozen["memory_resource_id"], execution_unit_id=frozen["execution_unit_id"],
        execution_contract_id=frozen["execution_contract_id"],
        implementation_id=frozen["implementation_id"], evidence_id=frozen["qualification_evidence_id"],
        bdf=frozen["physical_device_bdf"], runtime_identity=frozen["runtime_identity"],
        observation=observation)
    # Eligibility-completion facts (representation/features/integrity/freshness)
    # come from the frozen authority; the economics objective value is the
    # measured qualification wall time, never a caller assertion.
    completion = authority["capability_completion"]
    capability.update({
        "representations": list(completion["representations"]),
        "required_features": list(completion["required_features"]),
        "integrity_status": completion["integrity_status"],
        "evidence_fresh": True,
        "economics": {"objective_value": run["wall_seconds"]},
    })
    record = {"schema": "inferswarm.v1a.qualification/1",
              "qualification_evidence_id": frozen["qualification_evidence_id"],
              "preflight": measured, "attempt": {k: v for k, v in run.items() if k not in ("stdout", "stderr")},
              "offloaded_layers": list(observation.offloaded_layers),
              "qualification_digest": observation.proof_digest,
              "capability_record": capability, "result": "PASS"}
    return {"record": record, "observation": observation, "capability": capability, "run": run}


# ---------------------------------------------------------------------------
# Stages 4-6: resource snapshot, generic planning, frozen-plan persistence.
# ---------------------------------------------------------------------------

def build_snapshot(authority: Mapping[str, Any], capability: Mapping[str, Any]) -> dict[str, Any]:
    frozen = authority["frozen"]
    amd = {"node_id": frozen["node_id"], "compute_unit_id": frozen["compute_unit_id"],
           "physical_device_bdf": frozen["physical_device_bdf"],
           "memory_resource": {"memory_resource_id": frozen["memory_resource_id"], "bytes": frozen["memory_bytes"]},
           "capabilities": [capability]}
    pressure = authority["ontology_pressure_resource"]
    return {"schema": "inferswarm.v1a.resource-snapshot/1", "node_id": frozen["node_id"],
            "compute_units": [amd, pressure]}


def plan_and_freeze(authority: Mapping[str, Any], snapshot: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = authority["frozen"]
    unit = {"execution_unit_id": frozen["execution_unit_id"],
            "execution_contract_id": frozen["execution_contract_id"],
            "logical_state_id": frozen["logical_state_id"],
            "required_representation": frozen["required_representation"],
            "required_features": frozen["required_features"],
            "required_memory_bytes": frozen["required_memory_bytes"],
            "required_headroom_bytes": frozen["required_headroom_bytes"],
            "required_integrity_status": frozen["required_integrity_status"],
            "correctness_policy": frozen["correctness_policy"]}
    decision = participant.plan_execution_unit(execution_unit=unit, compute_units=snapshot["compute_units"],
                                               objective=frozen["objective"])
    if decision.get("selected_candidate") is None:
        raise RunnerError("generic planner selected no candidate")
    plan = participant.freeze_plan(decision=decision, execution_unit=unit)
    return decision, plan


# ---------------------------------------------------------------------------
# Stages 7-12: canonical execution, accounting, correctness, sealed proof,
# canonical observation, execution receipt.
# ---------------------------------------------------------------------------

def execute_canonical(authority: Mapping[str, Any], plan: Mapping[str, Any], measured: Mapping[str, Any],
                      out: Path) -> dict[str, Any]:
    frozen = authority["frozen"]
    participant.validate_frozen_plan(plan)
    if plan["plan_digest"] != frozen["plan_digest"]:
        raise RunnerError("frozen plan digest differs from authority")
    candidate = plan["candidate"]
    for field in ("node_id", "compute_unit_id", "memory_resource_id", "execution_unit_id",
                  "execution_contract_id", "implementation_id", "candidate_id", "physical_device_bdf"):
        if candidate.get(field) != frozen[field]:
            raise RunnerError(f"frozen candidate {field} mismatch")
    run = _execute(frozen, out)
    if run["exit_code"] != 0:
        raise RunnerError(f"canonical exit was not clean: {run['exit_code']}")
    observation = adapter.parse_backend_observation(
        stderr=run["stderr"], selector=frozen["selector"], expected_bdf=frozen["physical_device_bdf"],
        node_id=candidate["node_id"], compute_unit_id=candidate["compute_unit_id"],
        memory_resource_id=candidate["memory_resource_id"], execution_unit_id=candidate["execution_unit_id"],
        execution_contract_id=candidate["execution_contract_id"],
        implementation_id=candidate["implementation_id"], evidence_id=candidate["evidence_id"],
        runtime_identity=candidate["runtime_identity"])
    # Accepted V0-C accounting reducer, byte-unchanged.
    accounting = v0c_runner.parse_accounting(run["stderr"])
    for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready", "unplanned_state_movements"):
        if accounting[key] != 0:
            raise RunnerError(f"accounting disposition not clean: {key}")
    # Accepted V0-C byte-exact correctness comparator, byte-unchanged.
    correctness = v0c_correctness.reduce(run["stdout"], frozen["prompt"].encode(), Path(frozen["reference_output"]).read_bytes())
    if not correctness["byte_exact_visible_output"]:
        raise RunnerError("byte-exact correctness comparison failed")
    proof = adapter.seal_canonical_execution_proof(
        observation=observation, plan_digest=plan["plan_digest"], candidate_id=candidate["candidate_id"],
        execution_contract_id=candidate["execution_contract_id"],
        execution_evidence_id=frozen["canonical_execution_evidence_id"], stdout=run["stdout"],
        stderr=run["stderr"], exit_code=run["exit_code"])
    observation_record = participant.canonical_observation(plan=plan, canonical_proof=proof)
    receipt = participant.execution_receipt(plan=plan, output=run["stdout"], canonical_proof=proof)
    return {"run": run, "accounting": accounting, "correctness": correctness, "proof": proof,
            "canonical_observation": observation_record, "receipt": receipt}


REDUCED_RUN_KEYS = ("started_utc", "wall_seconds", "argv", "exit_code", "stdout_sha256", "stderr_sha256")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("preflight", "qualify", "plan", "canonical"), required=True)
    parser.add_argument("--capability")
    parser.add_argument("--plan")
    args = parser.parse_args(argv)
    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    out = Path(args.out)
    frozen = authority["frozen"]

    if args.mode == "preflight":
        measured = preflight(authority)
        print(canonical({"result": "PASS", "measured": measured}).decode())
        return 0

    if args.mode == "qualify":
        measured = preflight(authority)
        result = qualify(authority, measured, out)
        record = result["record"]
        record["raw"] = {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt"}
        record.pop("attempt", None)
        record["attempt"] = {k: v for k, v in result["run"].items() if k in REDUCED_RUN_KEYS}
        record["record_digest"] = digest_bytes(canonical(record))
        (out / "qualification.json").write_bytes(canonical(record) + b"\n")
        print(record["record_digest"])
        return 0

    if args.mode == "plan":
        capability = json.loads(Path(args.capability).read_text(encoding="utf-8"))
        snapshot = build_snapshot(authority, capability)
        decision, plan = plan_and_freeze(authority, snapshot)
        out.mkdir(parents=True, exist_ok=False)
        (out / "resource-snapshot.json").write_bytes(canonical(snapshot) + b"\n")
        (out / "candidate-set.json").write_bytes(canonical(decision) + b"\n")
        (out / "frozen-plan.json").write_bytes(canonical(plan) + b"\n")
        print(plan["plan_digest"])
        return 0

    # canonical
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    measured = preflight(authority)
    result = execute_canonical(authority, plan, measured, out)
    record = {"schema": "inferswarm.v1a.canonical-execution/1",
              "canonical_execution_evidence_id": frozen["canonical_execution_evidence_id"],
              "preflight": measured,
              "attempt": {k: v for k, v in result["run"].items() if k in REDUCED_RUN_KEYS},
              "plan_digest": plan["plan_digest"], "candidate_id": plan["candidate"]["candidate_id"],
              "accounting": result["accounting"],
              "correctness": {k: (v.decode("utf-8") if isinstance(v, bytes) else v)
                              for k, v in result["correctness"].items()},
              "canonical_proof_digest": result["proof"].proof_digest,
              "canonical_observation": result["canonical_observation"],
              "execution_receipt": result["receipt"], "result": "PASS",
              "raw": {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt"}}
    record["record_digest"] = digest_bytes(canonical(record))
    (out / "canonical-execution.json").write_bytes(canonical(record) + b"\n")
    print(record["record_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
