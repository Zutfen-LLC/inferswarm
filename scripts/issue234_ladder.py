#!/usr/bin/env python3
"""Issue #234 — R8-H correctness ladder runner (inferswarm02).

Launches the frozen single-die Vulkan llama-server once, then walks the
frozen candidate ladder (case-256 -> 1024 -> 3072 -> 4096) with 3
repeats per case under the canonical true-greedy request contract,
comparing exact token IDs + stop semantics against the frozen accepted
R8-D reference (loaded from the repository fixture bytes, never
regenerated). Escalation only on exact-token/exact-stop PASS + clean
platform health; hard stop on any health stop-class between cases.

Execution-truth evidence is captured per case window: both dies' VRAM
counters, server log backend lines, and the process/drm association.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc
import issue234_health as health


class LadderError(RuntimeError):
    pass


def http_json(url: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait_server(port: int, deadline_s: int = 7200) -> None:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=10) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(5)
    raise LadderError("server did not become healthy before deadline")


def server_log_tail(proc) -> str:
    # server launched with stdout to a file; caller passes nothing here
    return ""


def run_case(port: int, prompt_token_ids: list[int]) -> dict[str, Any]:
    body = dict(rc.REQUEST_CONTRACT)
    body["prompt"] = prompt_token_ids
    t0 = time.time()
    resp = http_json(f"http://127.0.0.1:{port}/completion", body)
    dt = time.time() - t0
    tokens = resp.get("tokens")
    if tokens is None and resp.get("return_tokens"):
        tokens = resp.get("tokens")
    stop = resp.get("stop_type", resp.get("stop_type"))
    return {
        "wall_s": round(dt, 3),
        "generated_tokens": tokens if tokens is not None else
        resp.get("completion_tokens"),
        "stop_type": stop,
        "stop_word": resp.get("stopping_word", ""),
        "raw": resp,
    }


def compare(candidate: dict[str, Any], reference: dict[str, Any]) -> dict:
    tok_ok = candidate["generated_tokens"] == reference["generated_tokens"]
    stop_ok = candidate["stop_type"] == reference["stop_type"]
    first_div = None
    if not tok_ok:
        ct = candidate["generated_tokens"] or []
        rt = reference["generated_tokens"]
        for i, (c, r) in enumerate(zip(ct, rt)):
            if c != r:
                first_div = {"position": i, "candidate": c, "reference": r}
                break
        if first_div is None:
            first_div = {"position": min(len(ct), len(rt)),
                         "candidate": ct[len(rt):] if len(ct) > len(rt) else None,
                         "reference": rt[len(ct):] if len(rt) > len(ct) else None}
    return {"tokens_equal": tok_ok, "stop_equal": stop_ok,
            "exact": tok_ok and stop_ok, "first_divergence": first_div}


def launch_server(server: Path, model: Path, ngl: int, port: int,
                  log_path: Path) -> subprocess.Popen:
    import os
    env = dict(os.environ)
    env["GGML_VK_VISIBLE_DEVICES"] = "1"
    env["PATH"] = "/usr/bin:/bin:" + env.get("PATH", "")
    log = open(log_path, "w")
    return subprocess.Popen(
        [str(server), "--model", str(model),
         "--n-gpu-layers", str(ngl),
         "--ctx-size", str(rc.CONTEXT_SETTINGS["ctx-size"]),
         "--batch", str(rc.CONTEXT_SETTINGS["batch"]),
         "--port", str(port), "--host", "127.0.0.1"],
        stdout=log, stderr=subprocess.STDOUT, env=env)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--ngl", type=int, required=True)
    ap.add_argument("--fixture", type=Path, required=True,
                    help="accepted R8-B fixture-ladder.json copy")
    ap.add_argument("--reference", type=Path, required=True,
                    help="accepted R8-D frozen-reference.json copy")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--selected-sysfs", default="0000:06:00.0")
    ap.add_argument("--excluded-sysfs", default="0000:09:00.0")
    ap.add_argument("--port", type=int, default=18434)
    args = ap.parse_args()

    import hashlib
    fixture_bytes = args.fixture.read_bytes()
    if hashlib.sha256(fixture_bytes).hexdigest() != rc.R8D_FIXTURE_SHA256:
        raise LadderError("fixture ladder identity drift (control 18)")
    reference = json.loads(args.reference.read_text())
    fixture = json.loads(fixture_bytes)
    prompts = {c["case_id"]: c["prompt_token_ids"] for c in fixture["cases"]}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.out_dir / "ladder-server.log"
    health_before = health.snapshot(args.selected_sysfs, args.excluded_sysfs)
    t_start = time.strftime("%Y-%m-%d %H:%M:%S")

    proc = launch_server(args.server, args.model, args.ngl, args.port,
                         log_path)
    try:
        wait_server(args.port)
        results: dict[str, Any] = {}
        halted = None
        for case_id in rc.LADDER_CASES:
            if halted:
                results[case_id] = {"status": "NOT_EXECUTED",
                                    "reason": f"halted after {halted}"}
                continue
            case_repeats = []
            case_exact = None
            for rep in range(1, rc.REPEATS_PER_CASE + 1):
                obs = run_case(args.port, prompts[case_id])
                cmp = compare(obs, reference["cases"][case_id])
                case_repeats.append({"repeat": rep, "observation": obs,
                                     "comparison": cmp})
                case_exact = cmp["exact"]
                if not cmp["exact"]:
                    break  # deterministic mismatch: no further repeats
            results[case_id] = {
                "status": "PASS" if case_exact else "FAIL",
                "repeats": case_repeats,
                "reference": reference["cases"][case_id],
            }
            # health gate between cases
            jraw = health.journal_amdgpu(since=t_start)
            jwin = health.classify_journal(
                jraw, args.selected_sysfs, args.excluded_sysfs)
            results[case_id]["health_window"] = {
                "stop_classes": jwin["stop_classes"],
                "rxerr_lines": jwin["correctable_rxerr_lines"],
            }
            stops = health.stop_now({"journal": jwin})
            if stops:
                halted = f"{case_id}:{'+'.join(stops)}"
                results[case_id]["status"] = (
                    "FAIL" if case_exact is False else
                    "PASS_BUT_HALTED")
            elif not case_exact:
                halted = f"{case_id}:deterministic_mismatch"
        # final snapshot after all cases
        health_after = health.snapshot(args.selected_sysfs,
                                       args.excluded_sysfs)
        jfinal = health.classify_journal(
            health.journal_amdgpu(since=t_start),
            args.selected_sysfs, args.excluded_sysfs)
        doc = {
            "schema": "inferswarm.r8h.ladder/1",
            "campaign": rc.CAMPAIGN_ID,
            "server": {
                "binary": str(args.server),
                "model": str(args.model),
                "ngl": args.ngl,
                "ctx": rc.CONTEXT_SETTINGS,
                "port": args.port,
                "selector": "GGML_VK_VISIBLE_DEVICES=1",
            },
            "fixture_sha256": rc.R8D_FIXTURE_SHA256,
            "request_contract": rc.REQUEST_CONTRACT,
            "t_start": t_start,
            "results": results,
            "halted": halted,
            "health": {
                "before": health_before,
                "after": health_after,
                "delta": health.delta(health_before, health_after),
                "journal_final": jfinal,
            },
            "server_log_tail": log_path.read_text()[-20000:],
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        time.sleep(5)
        post = health.snapshot(args.selected_sysfs, args.excluded_sysfs)
        release_ok = all(
            v <= 8 * 1024 * 1024 for k, v in post["selected_mem"].items()
            if "vram" in k)
        doc_final = doc if 'doc' in dir() else {}
        doc_final.setdefault("health", {})["post_exit"] = {
            "snapshot": post,
            "vram_released": release_ok,
            "server_exit_code": proc.returncode,
        }
        out = args.out_dir / "ladder.json"
        out.write_text(json.dumps(doc_final, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(json.dumps({
            "cases": {k: v.get("status") for k, v in
                      doc_final.get("results", {}).items()},
            "halted": doc_final.get("halted"),
            "vram_released": release_ok,
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
