#!/usr/bin/env python3
"""Run an authority-pinned V0-C qualification or canonical attempt locally.

Qualification is deliberately pre-plan and cannot mint a canonical execution
observation. Canonical realization consumes an already persisted frozen plan.
Both modes retain raw runtime streams before any reduction fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


class AccountingError(RuntimeError):
    """Direct runtime accounting is absent, malformed, or contradictory."""


def sha256(path: Path) -> str:
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


def _line_values(stderr: str, label: str) -> tuple[int, list[str]]:
    pattern = re.compile(re.escape(label) + r"\s*=\s*([0-9]+(?:\.[0-9]+)?)\s+MiB")
    matches = [(round(float(match.group(1)) * MIB), line) for line in stderr.splitlines()
               if (match := pattern.search(line))]
    if len(matches) != 1:
        raise AccountingError(f"missing or ambiguous direct accounting line: {label}")
    return matches[0][0], [matches[0][1]]


def _breakdowns(stderr: str) -> tuple[list[dict[str, int | str]], list[str]]:
    # This is llama.cpp's printed accounting grammar, not a process/RSS estimate.
    expression = re.compile(
        r"\|\s+-\s+(?P<resource>Vulkan\d+|Host).*?\|\s*"
        r"(?:(?P<total>\d+)\s*=\s*)?(?P<free>\d+)\s*\+\s*"
        r"\(?(?P<self>\d+)\s*=\s*(?P<model>\d+)\s*\+\s*"
        r"(?P<context>\d+)\s*\+\s*(?P<compute>\d+)\)?"
    )
    rows, lines = [], []
    for line_index, line in enumerate(stderr.splitlines()):
        match = expression.search(line)
        if match:
            row = {key: (int(value) if value is not None else -1)
                   for key, value in match.groupdict().items() if key != "resource"}
            row["resource"] = match.group("resource")
            row["line_index"] = line_index
            rows.append(row)
            lines.append(line)
    return rows, lines


def parse_accounting(stderr: str) -> dict[str, Any]:
    """Reduce direct llama.cpp buffer/breakdown diagnostics without RSS inference."""
    if not isinstance(stderr, str) or not stderr:
        raise AccountingError("runtime stderr is required for accounting")
    model, model_lines = _line_values(stderr, "Vulkan1 model buffer size")
    context, context_lines = _line_values(stderr, "Vulkan1 KV buffer size")
    compute, compute_lines = _line_values(stderr, "Vulkan1 compute buffer size")
    mapped, mapped_lines = _line_values(stderr, "CPU_Mapped model buffer size")
    output, output_lines = _line_values(stderr, "Vulkan_Host  output buffer size")
    host_compute, host_compute_lines = _line_values(stderr, "Vulkan_Host compute buffer size")
    all_lines = stderr.splitlines()
    ready_indices = [index for index, line in enumerate(all_lines)
                   if "cached n_tokens = 0" in line and "memory_seq_rm" in line]
    if len(ready_indices) != 1:
        raise AccountingError("missing or ambiguous ready-state accounting")
    ready_index = ready_indices[0]
    ready_lines = [all_lines[ready_index]]
    rows, breakdown_lines = _breakdowns(stderr)
    indexed_rows = list(zip(rows, breakdown_lines, strict=True))
    device_events = [(row, line, int(row["line_index"])) for row, line in indexed_rows
                     if row["resource"] == "Vulkan1"]
    host_pattern = re.compile(r"\|\s+-\s+Host\s+\|\s*(\d+)\s*=\s*(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)")
    host_events = [(tuple(map(int, match.groups())), line, index)
                   for index, line in enumerate(all_lines)
                   if (match := host_pattern.search(line))]
    pre_device = [(row, line, index) for row, line, index in device_events if index < ready_index]
    post_device = [(row, line, index) for row, line, index in device_events if index > ready_index]
    pre_host = [(row, line, index) for row, line, index in host_events if index < ready_index]
    post_host = [(row, line, index) for row, line, index in host_events if index > ready_index]
    if not pre_device:
        raise AccountingError("missing pre-ready direct device memory breakdown")
    if not post_device:
        raise AccountingError("missing final direct device memory breakdown")
    if not post_host:
        raise AccountingError("missing final direct host memory breakdown")
    if len(post_device) != 1:
        raise AccountingError("ambiguous final direct device memory breakdown")
    if len(post_host) != 1:
        raise AccountingError("ambiguous final direct host memory breakdown")
    before, before_line, _ = pre_device[-1]
    after, after_line, _ = post_device[0]
    (host_total, host_model, host_context, host_compute_mib), host_line, _ = post_host[0]
    for row, name in ((before, "before device"), (after, "after device")):
        # The displayed total/free/self columns include the runtime's explicit
        # unaccounted field, so only the directly decomposed self total is exact.
        if abs(row["self"] - (row["model"] + row["context"] + row["compute"])) > 1:
            raise AccountingError(f"contradictory {name} breakdown components")
    if host_total != host_model + host_context + host_compute_mib:
        raise AccountingError("contradictory host breakdown total")
    if (abs(after["model"] * MIB - model) > 2 * MIB
            or abs(after["context"] * MIB - context) > 2 * MIB
            or abs(after["compute"] * MIB - compute) > 2 * MIB):
        raise AccountingError("contradictory final device buffers and breakdown")
    if host_model * MIB + 2 * MIB < mapped or abs(host_compute_mib * MIB - host_compute) > 2 * MIB:
        raise AccountingError("contradictory host buffers and breakdown")
    # A direct Host model component not labelled CPU_Mapped is not silently zeroed.
    unexplained = max(0, (host_model * MIB) - mapped)
    after_ready = all_lines[ready_index + 1:]
    source_fetch_lines = [line for line in after_ready if re.search(r"\b(fetch|download|remote source)\b", line, re.I)]
    movement_lines = [line for line in after_ready if re.search(r"\b(rematerializ|state movement|migration|copying state)\b", line, re.I)]
    return {
        "schema": "inferswarm.v0c.materialization-accounting/1",
        "device_resident_model_bytes": model,
        "device_context_bytes": context,
        "device_compute_bytes": compute,
        "required_persistent_host_bytes": 0,
        "intentional_host_mapping_or_cache_bytes": mapped,
        "host_context_kv_output_compute_bytes": output + host_compute,
        "released_staging_bytes": 0,
        "representation_conversion_bytes": 0,
        "unexplained_persistent_host_mirror_bytes": unexplained,
        "source_fetches_after_ready": len(source_fetch_lines),
        "unplanned_state_movements": len(movement_lines),
        "raw_lines": {
            "device_model": model_lines, "device_context": context_lines,
            "device_compute": compute_lines, "host_mapping": mapped_lines,
            "host_output": output_lines, "host_compute": host_compute_lines,
            "ready_state": ready_lines, "device_memory_before_after": [before_line, after_line],
            "host_memory_pre_realization": [line for _, line, _ in pre_host],
            "host_memory_final": [host_line],
            "source_fetches_after_ready": source_fetch_lines,
            "unplanned_state_movements": movement_lines,
        },
        "basis": "direct llama.cpp named buffers plus before/after memory-breakdown rows; never process RSS",
    }


def validate_stage_inputs(mode: str, authority: Mapping[str, Any], plan: Mapping[str, Any] | None) -> None:
    if mode == "qualification":
        if plan is not None:
            raise RuntimeError("qualification must not accept a frozen plan")
        return
    if mode != "canonical":
        raise RuntimeError("unknown stage")
    if not isinstance(plan, Mapping):
        raise RuntimeError("canonical execution requires a persisted frozen plan")
    required = {"plan_digest", "candidate", "execution_unit", "objective", "schema"}
    if set(plan) != required or not plan.get("plan_digest"):
        raise RuntimeError("canonical execution requires an exact frozen plan")


def preflight(authority: Mapping[str, Any], mode: str, plan: Mapping[str, Any] | None) -> dict[str, Any]:
    validate_stage_inputs(mode, authority, plan)
    frozen = authority["frozen"]
    if os.uname().nodename != frozen["hostname"]:
        raise RuntimeError("proving hostname mismatch")
    source = Path(frozen["runtime_source"])
    actual_commit = command(["git", "-c", f"safe.directory={source}", "-C", str(source), "rev-parse", "HEAD"])
    if actual_commit != frozen["runtime_source_commit"]:
        raise RuntimeError("runtime source commit mismatch")
    if command(["git", "-c", f"safe.directory={source}", "-C", str(source), "status", "--porcelain"]):
        raise RuntimeError("runtime source is dirty")
    executable, model = Path(frozen["executable"]), Path(frozen["model"])
    measured = {
        "hostname": os.uname().nodename, "runtime_source_commit": actual_commit,
        "executable": str(executable), "executable_sha256": sha256(executable),
        "executable_bytes": executable.stat().st_size, "model": str(model),
        "model_sha256": sha256(model), "model_bytes": model.stat().st_size,
        "control_plane_sources": {path: sha256(ROOT / path) for path in frozen["control_plane_sources"]},
        "repository_head": command(["git", "rev-parse", "HEAD"]),
    }
    expected = {key: frozen[key] for key in ("executable_sha256", "model_sha256", "model_bytes", "control_plane_sources")}
    if any(measured[key] != value for key, value in expected.items()):
        raise RuntimeError("measured frozen identity mismatch")
    if command(["git", "status", "--porcelain"]):
        raise RuntimeError("correctness-bearing working tree is dirty")
    if mode == "canonical":
        candidate = plan["candidate"]
        for field in ("candidate_id", "compute_unit_id", "memory_resource_id", "execution_unit_id", "execution_contract_id", "implementation_id", "physical_device_bdf"):
            if candidate.get(field) != frozen[field]:
                raise RuntimeError(f"frozen candidate {field} mismatch")
        if plan["plan_digest"] != frozen["plan_digest"]:
            raise RuntimeError("frozen plan digest mismatch")
        if candidate.get("evidence_id") != frozen["qualification_evidence_id"]:
            raise RuntimeError("qualification observation identity mismatch")
    return measured


def _runtime_argv(frozen: Mapping[str, Any]) -> list[str]:
    return [frozen["executable"], "-m", frozen["model"], "--temp", "0", "--seed", "42", "-n", "48", "-ngl", "99", "--device", frozen["selector"], "-lv", "4", "-p", frozen["prompt"], "-st"]


def _proof(stderr: str, frozen: Mapping[str, Any]) -> dict[str, Any]:
    selected = [line for line in stderr.splitlines() if "using device" in line]
    offload = [line for line in stderr.splitlines() if re.search(r"offloaded\s+37\s*/\s*37\s+layers\s+to\s+GPU", line)]
    fallback = [line for line in stderr.splitlines() if re.search(r"\b(falling back|cpu fallback|fallback execution)\b", line, re.I)]
    target = f"using device {frozen['selector']}"
    bdf = f"0000:{frozen['physical_device_bdf']}"
    if len(selected) != 1 or target not in selected[0] or bdf not in selected[0] or len(offload) != 1 or fallback:
        raise RuntimeError("execution did not prove exact selected device/full offload/no fallback")
    return {"selected_device_lines": selected, "offload_lines": offload, "fallback_lines": fallback,
            "offloaded_layers": [37, 37], "fallback_free": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("qualification", "canonical"), required=True)
    parser.add_argument("--plan")
    args = parser.parse_args(argv)
    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8")) if args.plan else None
    measured = preflight(authority, args.mode, plan)
    frozen = authority["frozen"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    runtime_argv = _runtime_argv(frozen)
    environment = {key: os.environ[key] for key in sorted(os.environ) if key.startswith(("GGML_", "VK_", "LD_LIBRARY_PATH")) and os.environ[key]}
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    process = subprocess.run(runtime_argv, capture_output=True, text=False, timeout=1200, env=dict(os.environ))
    wall_seconds = round(time.monotonic() - t0, 3)
    (out / "stdout.txt").write_bytes(process.stdout)
    (out / "stderr.txt").write_bytes(process.stderr)
    (out / "exit-code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")
    record: dict[str, Any] = {"schema": f"inferswarm.v0c.{args.mode}-attempt/1", "mode": args.mode,
        "started_utc": started, "wall_seconds": wall_seconds, "argv": runtime_argv, "environment": environment,
        "preflight": measured, "exit_code": process.returncode, "stdout_sha256": sha256(out / "stdout.txt"),
        "stderr_sha256": sha256(out / "stderr.txt"), "raw": {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt"}}
    try:
        if process.returncode != 0:
            raise RuntimeError("runtime exit was not clean")
        stderr = process.stderr.decode("utf-8")
        proof = _proof(stderr, frozen)
        record["execution_proof"] = proof
        if args.mode == "qualification":
            observation = {"schema": "inferswarm.v0c.qualification-observation/1", "qualification_evidence_id": frozen["qualification_evidence_id"],
                "preflight": measured, "execution_contract_id": frozen["execution_contract_id"], "implementation_id": frozen["implementation_id"],
                "compute_unit_id": frozen["compute_unit_id"], "memory_resource_id": frozen["memory_resource_id"], "execution_unit_id": frozen["execution_unit_id"],
                "selector": frozen["selector"], "physical_device_bdf": frozen["physical_device_bdf"], "exit_code": 0,
                "stdout_sha256": record["stdout_sha256"], "stderr_sha256": record["stderr_sha256"], **proof}
            observation["observation_digest"] = digest_bytes(canonical(observation))
            record["qualification_observation"] = observation
        else:
            accounting = parse_accounting(stderr)
            record["materialization_accounting"] = accounting
            if any(accounting[key] != 0 for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready", "unplanned_state_movements")):
                raise AccountingError("accounting disposition is not clean")
            record["canonical_execution_inputs"] = {"plan_digest": plan["plan_digest"], "candidate_id": plan["candidate"]["candidate_id"],
                "canonical_execution_evidence_id": frozen["canonical_execution_evidence_id"], "qualification_evidence_id": frozen["qualification_evidence_id"]}
        record["result"] = "PASS"
    except (RuntimeError, AccountingError) as error:
        record["result"] = "V0C_EVIDENCE_BLOCKED" if isinstance(error, AccountingError) else "V0C_VULKAN_INTEGRATION_FAIL"
        record["error"] = str(error)
    record["record_digest"] = digest_bytes(canonical(record))
    (out / "attempt.json").write_bytes(canonical(record) + b"\n")
    print(record["record_digest"])
    return 0 if record["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
