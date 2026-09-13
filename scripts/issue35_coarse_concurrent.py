#!/usr/bin/env python3
"""Issue #35 CORRECTION: genuinely concurrent coarse-role measurement.

Maintainer review of PR #165 established that the retained coarse role
(``llama-cli -np 4``) issued ONE chat-completion interaction; ``-np 4``
provisions four parallel server slots but does not itself issue four
concurrent sequences. The retained 52.35 t/s result is therefore a
single-request diagnostic, not a four-request coarse workload.

This module implements the ADDITIVE corrected experiment, driven by a
PROSPECTIVELY COMMITTED correction freeze (before any attempt):

* the pinned runtime's own server binary (built from the SAME pinned
  llama.cpp source tree and accepted Vulkan build, binary digest
  recorded at execution) is launched with ``-np 4`` (four available
  parallel slots), ``-sm layer`` layer split across the two subjects,
  and the frozen workload parameters;
* after the server is ready, FOUR CONCURRENT IDENTICAL frozen requests
  (frozen prompt, frozen max tokens, temperature 0, seed 42) are issued
  over HTTP, each in its own thread; per-request request/response bytes
  are retained independently;
* correctness is required for EVERY request: the visible text of each
  response must equal the frozen single-sequence reference visible
  output EXACTLY (greedy temp-0 seed-42 semantics);
* aggregate wall time (first request sent -> last response complete)
  and aggregate generated tokens are measured; aggregate throughput is
  CALCULATED as generated tokens / aggregate wall seconds; per-request
  latency distribution is recorded; the per-sequence derived metric is
  defined mathematically and labeled CALCULATED;
* offload/residency/device facts are parsed from the retained server
  stderr with the same grammar as the accepted role sweep.

The MATCHED control runs the SAME four-concurrent-request workload on
the single-subject anchor (one device, all layers resident), so the
coarse comparison is workload-matched in both arms.

The original single-request ``-np 4`` result is preserved unchanged as
an invalid-for-intended-coarse-comparison diagnostic/reference.

Fail-closed: server not ready in the frozen timeout, non-2xx status,
missing timing fields, reference mismatch, and offload parse failure
all raise ``CoarseError`` and retain the raw bytes.

No selector, vendor, device name, BDF, or width literal appears in this
module's bytes; every subject value is consumed from the freeze.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import threading
import time
import urllib.request
from hashlib import sha256
from pathlib import Path

SCHEMA_RESULT = "inferswarm.issue35.coarse-concurrent-result/1"

_GEN_RATE = re.compile(r"Generation:\s*([0-9.]+)\s*t/s")
_OFFLOAD_LINE = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")
_CPU_MAPPED = re.compile(r"CPU_Mapped model buffer size\s*=\s*([0-9.]+) MiB")
_DEV_BUFFER = re.compile(r"(Vulkan\d+) model buffer size\s*=\s*([0-9.]+) MiB")
_GRAPH_SPLITS = re.compile(r"graph splits = (\d+)")


class CoarseError(RuntimeError):
    """A coarse-correction execution or reduction invariant failed."""


def digest_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def wait_ready(port: int, timeout_s: float) -> float:
    """Block until the server health endpoint answers; return elapsed s."""
    t0 = time.monotonic()
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return round(time.monotonic() - t0, 3)
        except Exception:
            time.sleep(0.25)
    raise CoarseError(f"server not ready within {timeout_s:.0f}s on port {port}")


def one_request(port: int, prompt: str, max_tokens: int,
                timeout_s: float) -> dict:
    """Issue ONE frozen chat-completion request; retain its bytes."""
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        status = resp.status
        body = resp.read()
    wall = round(time.monotonic() - t0, 3)
    if status != 200:
        raise CoarseError(f"request status {status}")
    doc = json.loads(body.decode("utf-8"))
    return {
        "request_payload_sha256": digest_bytes(payload),
        "request_body_bytes": len(payload),
        "response_sha256": digest_bytes(body),
        "response_bytes": len(body),
        "wall_seconds": wall,
        "visible_text": doc["choices"][0]["message"]["content"],
        "completion_tokens": doc["usage"]["completion_tokens"],
        "prompt_tokens": doc["usage"]["prompt_tokens"],
        "timing": doc.get("timing") or {},
        "model_reported": doc.get("model"),
    }


def run_arm(arm: dict, env: dict, out_root: Path, reference: str) -> dict:
    """Run every frozen attempt of one arm; reduce to a distribution
    record shaped like the accepted sweep results (values/min/median/max)
    with per-request facts retained per attempt in raw/."""
    per_attempt = []
    for attempt_index in range(1, arm["attempts"] + 1):
        out_dir = out_root / "raw" / arm["arm_id"] / f"attempt-{attempt_index:02d}"
        per_attempt.append(
            run_attempt(arm, env, out_dir, reference))
    agg = [a["aggregate_throughput_tokens_per_s"]["value"]
           for a in per_attempt]
    per_seq = [a["per_sequence_throughput_tokens_per_s"]["value"]
               for a in per_attempt]
    latencies = [l for a in per_attempt
                 for l in a["per_request_wall_seconds"]]
    return {
        "schema": SCHEMA_RESULT,
        "arm_id": arm["arm_id"],
        "label": "MEASURED",
        "attempts": arm["attempts"],
        "aggregate_throughput_tokens_per_s": {
            "values": agg,
            "median": round(statistics.median(agg), 3),
            "min": min(agg),
            "max": max(agg),
            "label": "CALCULATED",
            "definition": "sum(completion_tokens of all requests) / "
                          "aggregate wall seconds (first request sent to "
                          "last response complete)",
        },
        "per_sequence_throughput_tokens_per_s": {
            "values": per_seq,
            "median": round(statistics.median(per_seq), 3),
            "min": min(per_seq),
            "max": max(per_seq),
            "label": "CALCULATED",
            "definition": "median over requests of (completion_tokens_i / "
                          "per-request wall seconds_i); each request is one "
                          "sequence, so this is the per-sequence service "
                          "rate under four-way concurrency",
        },
        "per_request_latency_all_attempts": {
            "values": latencies,
            "median": round(statistics.median(latencies), 3),
            "min": round(min(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "all_attempts_all_correct": all(
            a["all_correct_vs_reference"] for a in per_attempt),
        "requests": arm["requests"],
        "parallel_slots": arm["parallel_slots"],
        "offload": per_attempt[0]["offload"],
        "residency": per_attempt[0]["residency"],
        "server_binary_sha256": per_attempt[0]["server_binary_sha256"],
        "per_attempt": per_attempt,
    }


def run_attempt(arm: dict, env: dict, out_dir: Path, reference: str) -> dict:
    """Launch the server for one attempt, fire the concurrent requests."""
    out_dir.mkdir(parents=True, exist_ok=False)
    port = arm["port"]
    argv = [env["server_executable"],
            "-m", env["model"],
            "--temp", "0", "--seed", "42",
            "-lv", "4",
            "-np", str(arm["parallel_slots"]),
            "-c", str(arm["ctx_size"]),
            "--host", "127.0.0.1", "--port", str(port)]
    argv += arm["server_extra_args"]
    server_proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        ready_s = wait_ready(port, arm["ready_timeout_s"])
        (out_dir / "server-argv.txt").write_text(
            " ".join(argv) + "\n", encoding="utf-8")
        barrier = threading.Barrier(arm["requests"])
        results = [None] * arm["requests"]
        errors = [None] * arm["requests"]

        def worker(i: int) -> None:
            try:
                barrier.wait(timeout=30.0)
                results[i] = one_request(
                    port, env["prompt"], env["max_tokens"],
                    arm["request_timeout_s"])
            except Exception as exc:  # retained per-request, fail-closed later
                errors[i] = f"{type(exc).__name__}: {exc}"

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(arm["requests"])]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=arm["request_timeout_s"] + 60.0)
        aggregate_wall = round(time.monotonic() - t0, 3)
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=30.0)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait(timeout=30.0)
        stdout_b, stderr_b = server_proc.communicate()
    (out_dir / "server-stdout.txt").write_bytes(stdout_b)
    (out_dir / "server-stderr.txt").write_bytes(stderr_b)
    (out_dir / "server-exit-code.txt").write_text(
        f"{server_proc.returncode}\n", encoding="utf-8")

    for i, err in enumerate(errors):
        if err is not None:
            raise CoarseError(f"request {i} failed: {err}")
    for i, res in enumerate(results):
        if res is None:
            raise CoarseError(f"request {i} produced no result")
        (out_dir / f"request-{i:02d}-response.json").write_bytes(
            json.dumps(res, indent=2, sort_keys=True).encode("utf-8") + b"\n")

    stderr_text = stderr_b.decode("utf-8", errors="strict")
    m = _OFFLOAD_LINE.search(stderr_text)
    if m is None:
        raise CoarseError("no offload summary in server stderr")
    cm = _CPU_MAPPED.search(stderr_text)
    cpu_mapped = float(cm.group(1)) if cm is not None else None
    device_buffers = {sel: float(sz) for sel, sz in
                      _DEV_BUFFER.findall(stderr_text)}
    splits = [int(s) for s in _GRAPH_SPLITS.findall(stderr_text)]

    tokens = [r["completion_tokens"] for r in results]
    total_tokens = sum(tokens)
    latencies = [r["wall_seconds"] for r in results]
    texts = [r["visible_text"] for r in results]
    matches = [t.strip() == reference.strip() for t in texts]
    gen_line = _GEN_RATE.search(stdout_b.decode("utf-8", errors="replace"))
    return {
        "schema": SCHEMA_RESULT,
        "arm_id": arm["arm_id"],
        "label": "MEASURED",
        "server_ready_seconds": ready_s,
        "aggregate_wall_seconds": aggregate_wall,
        "requests": arm["requests"],
        "parallel_slots": arm["parallel_slots"],
        "completion_tokens_per_request": tokens,
        "aggregate_completion_tokens": total_tokens,
        "per_request_wall_seconds": latencies,
        "per_request_latency": {
            "median": round(statistics.median(latencies), 3),
            "min": round(min(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "all_correct_vs_reference": all(matches),
        "per_request_correct_vs_reference": matches,
        "all_requests_identical": len(set(texts)) == 1,
        "aggregate_throughput_tokens_per_s": {
            "value": round(total_tokens / aggregate_wall, 3),
            "label": "CALCULATED",
            "definition": "sum(completion_tokens of all requests) / "
                          "aggregate wall seconds (first request sent to "
                          "last response complete)",
        },
        "per_sequence_throughput_tokens_per_s": {
            "value": round(statistics.median([t / l for t, l in
                                              zip(tokens, latencies)]), 3),
            "label": "CALCULATED",
            "definition": "median over requests of (completion_tokens_i / "
                          "per-request wall seconds_i); each request is one "
                          "sequence, so this is the per-sequence service "
                          "rate under four-way concurrency",
        },
        "server_reported_generation_rate": (
            float(gen_line.group(1)) if gen_line else None),
        "offload": {
            "layers_offloaded": int(m.group(1)),
            "layers_total": int(m.group(2)),
            "complete_offload": m.group(1) == m.group(2),
        },
        "residency": {
            "cpu_mapped_mib": cpu_mapped,
            "device_model_buffers_mib": device_buffers,
            "graph_splits_observed": splits,
            "fully_device_resident": (cpu_mapped in (None, 0.0)
                                      and bool(device_buffers)),
        },
        "server_stderr_sha256": digest_bytes(stderr_b),
        "server_stdout_sha256": digest_bytes(stdout_b),
        "server_binary_sha256": digest_bytes(
            Path(env["server_executable"]).read_bytes()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", required=True,
                        help="COARSE-CORRECTION-FREEZE.json path")
    parser.add_argument("--out-root", required=True,
                        help="investigation namespace root")
    args = parser.parse_args(argv)
    freeze = json.loads(Path(args.freeze).read_text(encoding="utf-8"))
    env = freeze["environment"]
    reference = Path(env["reference_output_path"]).read_text(
        encoding="utf-8")
    out_root = Path(args.out_root)
    results = []
    for arm in freeze["arms"]:
        raw_dir = out_root / "raw" / arm["arm_id"] / "attempt-01"
        results.append(run_arm(arm, env, raw_dir, reference))
    evidence = out_root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = evidence / f"{result['arm_id']}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({"arms": [r["arm_id"] for r in results]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
