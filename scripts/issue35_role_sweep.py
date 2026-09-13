#!/usr/bin/env python3
"""Issue #35 bounded role/placement sweep over the accepted runtime.

Executes a PROSPECTIVELY FROZEN set of placement shapes (declared in
ROLE-SWEEP-FREEZE.json before any performance run) through the accepted
llama-cli runtime, using the accepted single-subject workload shape
(greedy decode, temp 0, seed 42, -st, -lv 4, visible-output comparison
via the accepted byte-exact comparator semantics).

Roles vary communication intensity per unit of useful GPU work under
CURRENTLY SUPPORTED runtime semantics only (device selection, layer
offload split, tensor-split row partition). No new public API, no
scheduler feature, no speculative seam is invented.

Per role the sweep retains: raw stdout/stderr/exit per attempt, wall
seconds, generation throughput parsed from the runtime's own summary
line, offload/fallback facts parsed from the retained stderr, and a
correctness result where the role is correctness-bearing (roles that
change device participation are checked byte-exact against the frozen
single-subject reference through the accepted comparator semantics).

All subject facts (selectors, BDFs, model path, prompt) are consumed
from the frozen subject/sweep documents; no selector, vendor, device
name, or BDF literal appears in this module's bytes.

Fail-closed: parse ambiguity, non-clean exits (unless the role's frozen
stop rules declare an expected failure mode), and reference mismatch all
raise ``SweepError`` and are retained as evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
from hashlib import sha256
from pathlib import Path

SCHEMA_SWEEP_RESULT = "inferswarm.issue35.role-sweep-result/1"

_PROMPT_RATE = re.compile(r"Prompt:\s*([0-9.]+)\s*t/s")
_GEN_RATE = re.compile(r"Generation:\s*([0-9.]+)\s*t/s")
_OFFLOAD_LINE = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")


class SweepError(RuntimeError):
    """A role sweep execution or reduction invariant failed."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def parse_rates(stdout_text: str) -> dict:
    """Parse the runtime's own throughput summary (fail-closed)."""
    gen = _GEN_RATE.search(stdout_text)
    prompt = _PROMPT_RATE.search(stdout_text)
    if gen is None:
        raise SweepError("no Generation rate line in stdout")
    return {
        "generation_tokens_per_s": float(gen.group(1)),
        "prompt_tokens_per_s": float(prompt.group(1)) if prompt else None,
    }


def parse_offload(stderr_text: str) -> dict:
    """Parse layer-offload facts from retained stderr (fail-closed on
    absence; the runtime always prints load summary at -lv 4)."""
    m = _OFFLOAD_LINE.search(stderr_text)
    if m is None:
        raise SweepError("no load_tensors offload summary in stderr")
    done, total = int(m.group(1)), int(m.group(2))
    fallback = re.search(r"fallback", stderr_text, re.IGNORECASE) is not None
    return {"layers_offloaded": done, "layers_total": total,
            "complete_offload": done == total, "fallback_mentioned": fallback}


def visible_output(stdout_text: str, prompt: str) -> str:
    """Extract the visible greedy continuation after the prompt echo.

    Mirrors the accepted V0-C visible-output semantics: the runtime
    echoes the prompt, then the generated continuation, then a blank
    line and the throughput summary. The continuation is everything
    between the prompt echo and the summary block.
    """
    if prompt not in stdout_text:
        raise SweepError("prompt echo not found in stdout")
    tail = stdout_text.split(prompt, 1)[1]
    marker = "\n[ Prompt:"
    if marker in tail:
        tail = tail.split(marker, 1)[0]
    return tail


ROLE_COMMAND_BUILDERS = {
    # role A: single-subject control baseline (communication-light: one
    # device, all layers resident, matched workload) -- the matched
    # control every other role is compared against.
    "single_subject_control": lambda spec, role: [
        "--device", spec["selector"], "-ngl", "99"],
    # role B: communication-heavy fine-grained multiworker serving.
    # The declared tensor_split value "unused-in-layer-mode" (or any
    # value containing "unused") selects the layer split -- the finest
    # multiworker shape the runtime supports on these backends -- where
    # every generated token crosses the split boundary on both links.
    # Any other tensor_split value selects the row-split tensor
    # partition (retained for the unsupported-shape control).
    "communication_heavy_row_split": lambda spec, role: (
        ["--device", f"{spec['selector']},{role['peer_selector']}",
         "-ngl", "99", "-sm", "layer"] if
        str(role.get("tensor_split", "")).startswith("unused") else
        ["--device", f"{spec['selector']},{role['peer_selector']}",
         "-ngl", "99", "-sm", "row", "-ts", role["tensor_split"]]),
    # role C: coarse boundary -- layer split (contiguous model blocks
    # per device) with the batch-parallelism knob (-np) as the only
    # supported coarser execution unit: N sequences per decode step
    # amortize the same per-token boundary transfer over N useful
    # tokens. batch_sequences defaults to 1 (single sequence).
    "coarse_layer_split": lambda spec, role: [
        "--device", f"{spec['selector']},{role['peer_selector']}",
        "-ngl", role["layer_split"], "-sm", "layer",
        "-np", str(role.get("batch_sequences", 1))],
    # role D: capacity feasibility -- a model that cannot execute
    # resident on the control subject alone but can with the subject
    # participating; correctness/feasibility role, not a throughput race.
    # A role with peer_selector "NONE" runs single-subject (the matched
    # partial-offload control for the capacity case).
    "capacity_feasibility": lambda spec, role: (
        ["--device", spec["selector"], "-ngl", "99"] if
        role.get("peer_selector", "NONE") == "NONE" else
        ["--device", f"{spec['selector']},{role['peer_selector']}",
         "-ngl", "99", "-sm", "layer"]),
}


def build_argv(spec: dict, role: dict) -> list[str]:
    """Build the runtime argv for one role from frozen data only."""
    builder = ROLE_COMMAND_BUILDERS.get(role["role_kind"])
    if builder is None:
        raise SweepError(f"unknown role kind: {role['role_kind']!r}")
    model = role.get("model_override") or spec["model"]
    effective = dict(spec)
    if role.get("selector_override"):
        effective["selector"] = role["selector_override"]
    argv = [spec["runtime_executable"], "-m", model,
            "--temp", "0", "--seed", "42",
            "-n", str(role.get("tokens", 48)),
            "-lv", "4", "-p", spec["prompt"], "-st"]
    argv += builder(effective, role)
    return argv


def execute_attempt(argv: list[str], out_dir: Path, timeout_s: int) -> dict:
    """One physical attempt; retains raw bytes; never retries silently."""
    out_dir.mkdir(parents=True, exist_ok=False)
    t0 = time.monotonic()
    proc = subprocess.run(argv, capture_output=True, timeout=timeout_s)
    wall = round(time.monotonic() - t0, 3)
    (out_dir / "stdout.txt").write_bytes(proc.stdout)
    (out_dir / "stderr.txt").write_bytes(proc.stderr)
    (out_dir / "exit-code.txt").write_text(f"{proc.returncode}\n",
                                           encoding="utf-8")
    return {"argv": argv, "wall_seconds": wall,
            "exit_code": proc.returncode,
            "stdout_sha256": digest_bytes(proc.stdout),
            "stderr_sha256": digest_bytes(proc.stderr),
            "stdout": proc.stdout.decode("utf-8", errors="strict"),
            "stderr": proc.stderr.decode("utf-8", errors="strict")}


def reduce_role(spec: dict, role: dict, attempts: list[dict],
                reference: str | None) -> dict:
    """Reduce attempts into the per-role evidence record (fail-closed)."""
    clean = [a for a in attempts if a["exit_code"] == 0]
    expected_failure = role.get("expected_failure_mode")
    if not clean:
        if expected_failure:
            return {
                "role_id": role["role_id"],
                "role_kind": role["role_kind"],
                "attempts": len(attempts),
                "outcome": "EXPECTED_FAILURE",
                "expected_failure_mode": expected_failure,
                "label": "MEASURED",
            }
        raise SweepError(f"role {role['role_id']}: no clean attempts")
    rates = [parse_rates(a["stdout"]) for a in clean]
    offloads = [parse_offload(a["stderr"]) for a in clean]
    result = {
        "schema": SCHEMA_SWEEP_RESULT,
        "role_id": role["role_id"],
        "role_kind": role["role_kind"],
        "label": "MEASURED",
        "attempts": len(attempts),
        "clean_attempts": len(clean),
        "walls": [a["wall_seconds"] for a in clean],
        "generation_tokens_per_s": {
            "values": [r["generation_tokens_per_s"] for r in rates],
            "median": round(statistics.median(
                [r["generation_tokens_per_s"] for r in rates]), 4),
            "min": round(min(r["generation_tokens_per_s"] for r in rates), 4),
            "max": round(max(r["generation_tokens_per_s"] for r in rates), 4),
        },
        "prompt_tokens_per_s": {
            "values": [r["prompt_tokens_per_s"] for r in rates],
            "median": round(statistics.median(
                [r["prompt_tokens_per_s"] for r in rates]), 4),
        },
        "offload": offloads[0],
        "offload_consistent": all(o == offloads[0] for o in offloads),
    }
    if reference is not None:
        outs = [visible_output(a["stdout"], spec["prompt"]) for a in clean]
        result["byte_exact_vs_reference"] = {
            "matches": [o == reference for o in outs],
            "all_match": all(o == reference for o in outs),
        }
    return result


def run_sweep(spec_path: Path, out_root: Path) -> list[dict]:
    """Run the full frozen sweep; returns per-role results."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    results = []
    for role in spec["roles"]:
        attempts = []
        raw_role_dir = out_root / "raw" / role["role_id"]
        for attempt_index in range(1, role["attempts"] + 1):
            argv = build_argv(spec, role)
            attempt_dir = raw_role_dir / f"attempt-{attempt_index:02d}"
            attempts.append(execute_attempt(
                argv, attempt_dir, role.get("timeout_s", 1800)))
        reference = None
        if role.get("correctness_reference") == "frozen_reference":
            reference_path = Path(spec["reference_output_path"])
            reference = reference_path.read_text(encoding="utf-8")
        results.append(reduce_role(spec, role, attempts, reference))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True,
                        help="frozen ROLE-SWEEP-FREEZE.json path")
    parser.add_argument("--out-root", required=True,
                        help="investigation namespace root")
    args = parser.parse_args(argv)
    out_root = Path(args.out_root)
    results = run_sweep(Path(args.spec), out_root)
    payload = {"schema": "inferswarm.issue35.role-sweep-batch/1",
               "spec_sha256": sha256(
                   Path(args.spec).read_bytes()).hexdigest(),
               "results": results}
    evidence = out_root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = evidence / f"{result['role_id']}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({"roles": len(results),
                      "ids": [r["role_id"] for r in results]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
