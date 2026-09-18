#!/usr/bin/env python3
"""Issue #216 — V2-D synchronized Vulkan participant collector.

Run only on inferswarm02 after this committed producer is copied unchanged to
the frozen checkout.  Two child wrappers wait on one same-host gate file, then
each runs the frozen full-offload V2 sentinel.  Each wrapper retains raw probe,
stdout, stderr, visible output, monotonic interval, hashes, and independently
reduced correctness/accounting fields.  Sequential shell launches alone are
not evidence of concurrency; the reducer requires interval overlap.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from issue216_campaign_plan import CAMPAIGN_ID, build_plan

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPO = SCRIPT_DIR.parent

PROMPT = "The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:"


def durable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(argv: list[str], timeout: int) -> tuple[int, bytes, bytes]:
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or b"", (exc.stderr or b"") + b"\nTIMEOUT\n"


def probe(plan: dict, selector: str) -> dict:
    rt = plan["runtime"]
    argv = [rt["executable"], "-m", rt["model"], "--temp", "0", "--seed", "42", "-n", "0",
            "-ngl", "0", "--device", selector, "-lv", "4", "-p", PROMPT, "-st"]
    rc, stdout, stderr = run(argv, 600)
    text = stderr.decode("utf-8", "replace")
    match = re.search(r"using device.*?([0-9a-f]{2}:[0-9a-f]{2}\.[0-9])", text, re.I)
    return {"argv": argv, "rc": rc, "bdf": match.group(1) if match else None,
            "identity_line": match.group(0) if match else None, "stdout": stdout, "stderr": stderr}


def participant(args: argparse.Namespace) -> int:
    plan = build_plan()
    resource = plan["physical_resources"][args.die]
    out = Path(args.out) / "participants" / args.die
    out.mkdir(parents=True, exist_ok=True)
    p = probe(plan, resource["selector"])
    durable(out / "probe.stdout", p["stdout"])
    durable(out / "probe.stderr", p["stderr"])
    durable(out / "probe.json", json.dumps({k: v for k, v in p.items() if k not in ("stdout", "stderr")},
                                             indent=1, sort_keys=True).encode() + b"\n")
    ready = Path(args.gate + "." + args.die + ".ready")
    durable(ready, b"ready\n")
    deadline = time.monotonic() + 120
    gate = Path(args.gate)
    while not gate.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not gate.exists():
        raise RuntimeError("same-host start gate did not open")
    rt = plan["runtime"]
    argv = [rt["executable"], "-m", rt["model"], "--temp", "0", "--seed", "42", "-n", "8",
            "-ngl", "99", "--device", resource["selector"], "-lv", "4", "-p", PROMPT, "-st"]
    started = time.monotonic_ns()
    rc, stdout, stderr = run(argv, 1800)
    ended = time.monotonic_ns()
    durable(out / "stdout.txt", stdout)
    durable(out / "stderr.txt", stderr)
    durable(out / "exit-code.txt", f"{rc}\n".encode())
    sys.path.insert(0, args.repo + "/scripts")
    import v0c_correctness
    import v1c_accounting
    try:
        visible = v0c_correctness.extract_visible_response(stdout, PROMPT.encode())
        reference = (Path(args.repo) / rt["reference"]).read_bytes()
        byte_exact = bool(visible) and reference.startswith(visible)
    except Exception:
        visible, byte_exact = b"", False
    durable(out / "visible-output.txt", visible)
    text = stderr.decode("utf-8", "replace")
    m = re.search(r"offloaded (\d+)/(\d+) layers", text)
    offload = [int(m.group(1)), int(m.group(2))] if m else None
    try:
        parsed = v1c_accounting.parse_accounting(text, selector=resource["selector"])
        accounting = {k: parsed[k] for k in ("unexplained_persistent_host_mirror_bytes",
                                               "source_fetches_after_ready", "unplanned_state_movements")}
    except Exception as exc:
        accounting = {"error": f"{type(exc).__name__}: {exc}"}
    clean = all(accounting.get(k) == 0 for k in ("unexplained_persistent_host_mirror_bytes",
                                                  "source_fetches_after_ready", "unplanned_state_movements"))
    finite = not re.search(r"\b(?:nan|inf)\b", stdout.decode("utf-8", "replace"), re.I)
    result = (rc == 0 and p["rc"] == 0 and p["bdf"] == resource["expected_bdf"] and byte_exact
              and offload is not None and offload[0] == offload[1] and clean and finite)
    rec = {"schema": "inferswarm.v2d.participant-receipt/1", "campaign_id": CAMPAIGN_ID,
           "attempt_id": args.attempt, "die": args.die, "selector": resource["selector"],
           "bdf": p["bdf"], "probe_identity_line": p["identity_line"], "interval_ns": [started, ended],
           "argv": argv, "exit_code": rc, "full_offload": bool(offload and offload[0] == offload[1]),
           "offloaded_layers": offload, "byte_exact": byte_exact, "finite_output": finite,
           "accounting": accounting, "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr),
           "visible_output_sha256": digest(visible), "result": "PASS" if result else "FAIL"}
    durable(out / "receipt.json", json.dumps(rec, indent=1, sort_keys=True).encode() + b"\n")
    return 0 if result else 1


def pair(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    gate = out / "start-gate"
    children = []
    for die in ("a", "b"):
        argv = [sys.executable, __file__, "participant", "--die", die, "--attempt", args.attempt,
                "--out", str(out), "--repo", args.repo, "--gate", str(gate)]
        children.append(subprocess.Popen(argv))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and not all((Path(str(gate) + f".{d}.ready")).is_file() for d in ("a", "b")):
        time.sleep(0.01)
    if not all((Path(str(gate) + f".{d}.ready")).is_file() for d in ("a", "b")):
        for child in children:
            child.terminate()
        raise RuntimeError("both participants did not become ready")
    durable(gate, b"open\n")
    rc = [child.wait(timeout=1900) for child in children]
    receipts = {d: json.loads((out / "participants" / d / "receipt.json").read_text()) for d in ("a", "b")}
    a0, a1 = receipts["a"]["interval_ns"]
    b0, b1 = receipts["b"]["interval_ns"]
    overlap = max(a0, b0) < min(a1, b1)
    summary = {"schema": "inferswarm.v2d.concurrent-receipt/1", "campaign_id": CAMPAIGN_ID,
               "attempt_id": args.attempt, "participant_exit_codes": dict(zip(("a", "b"), rc)),
               "participants": receipts, "actual_temporal_overlap": overlap,
               "result": "PASS" if overlap and rc == [0, 0] else "FAIL"}
    durable(out / "concurrent-receipt.json", json.dumps(summary, indent=1, sort_keys=True).encode() + b"\n")
    print(json.dumps({"attempt": args.attempt, "result": summary["result"], "overlap": overlap}))
    return 0 if summary["result"] == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("participant")
    p.add_argument("--die", choices=("a", "b"), required=True); p.add_argument("--attempt", required=True)
    p.add_argument("--out", required=True); p.add_argument("--repo", default=str(DEFAULT_REPO)); p.add_argument("--gate", required=True)
    q = sub.add_parser("pair")
    q.add_argument("--attempt", required=True); q.add_argument("--out", required=True); q.add_argument("--repo", default=str(DEFAULT_REPO))
    args = ap.parse_args()
    return participant(args) if args.cmd == "participant" else pair(args)


if __name__ == "__main__":
    raise SystemExit(main())
