#!/usr/bin/env python3
"""Issue #234 — R8-H matched-arm ladder runner (schema /2).

Runs ONE (arm, case) rung: 3 repeats of the canonical true-greedy
request against the arm's frozen server, sampling execution truth
DURING generation. Invoked per rung by the controller in frozen order
(case-256 first; arm A, then B, then C). The reducer — never this
runner — adjudicates rung equality and ladder escalation (control 35).

Execution-truth binding per repeat (issue #11):
  * request/response raw bytes retained verbatim (tokens from
    response["tokens"] only);
  * per-repeat device residency samples taken DURING generation
    (selected device must carry model-scale residency; excluded
    devices must stay under the frozen noise bound);
  * process identity (pid, start time), server log window, backend
    lines from the server log;
  * platform health window per repeat and post-exit cleanup.

Emits raw observation receipts only; no authored status is trusted by
the reducer (issue #9).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc
import issue234_health as health
import issue234_placement as placement


class LadderError(RuntimeError):
    pass


def http_json(url: str, payload: dict, timeout: int = 3600) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait_server(port: int, deadline_s: int = 14400) -> None:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=10) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(10)
    raise LadderError("server did not become healthy before deadline")


def _mem_sampler(arm: str):
    if arm in ("A", "B"):
        return placement.gpu_mem_nvidia
    return placement.gpu_mem_amd


def run_arm_case(arm: str, server: Path, model_dir: Path, out_dir: Path,
                 case_id: str, prompt_token_ids: list[int],
                 cuda_selector: str | None = None,
                 vk_selector: str | None = None, icd: Path | None = None,
                 selected_key: str | None = None,
                 excluded_keys: list[str] | None = None,
                 port: int = 18491) -> dict[str, Any]:
    import os
    if selected_key is None or excluded_keys is None:
        raise LadderError("selected/excluded device keys required")
    model_files = sorted(model_dir.glob("*.gguf"))
    if len(model_files) != len(rc.MODEL_MEMBERS):
        raise LadderError(f"model dir member count {len(model_files)}")
    model_arg = model_files[0]

    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin:" + env.get("PATH", "")
    if arm == "A":
        env["CUDA_VISIBLE_DEVICES"] = cuda_selector or ""
        env.pop("GGML_VK_VISIBLE_DEVICES", None)
    else:
        env["GGML_VK_VISIBLE_DEVICES"] = vk_selector or ""
        env["CUDA_VISIBLE_DEVICES"] = "-1"
        if icd is not None:
            env["VK_ICD_FILENAMES"] = str(icd)

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"ladder-{arm}-{case_id}-server.log"
    sampler = _mem_sampler(arm)
    body = dict(rc.REQUEST_CONTRACT)
    body["prompt"] = prompt_token_ids

    mem_before = sampler()
    j_before = health.journal_kernel()
    j_before_classes = health.classify_journal(j_before)
    t_start = time.strftime("%Y-%m-%d %H:%M:%S")

    log = open(log_path, "w")
    proc = subprocess.Popen(
        [str(server), "--model", str(model_arg),
         "--n-gpu-layers", str(rc.MATCHED_NGL),
         "--ctx-size", str(rc.CONTEXT_SETTINGS["ctx-size"]),
         "--batch-size", str(rc.CONTEXT_SETTINGS["batch-size"]),
         "--port", str(port), "--host", "127.0.0.1"],
        stdout=log, stderr=subprocess.STDOUT, env=env)
    doc: dict[str, Any] = {
        "schema": "inferswarm.r8h.ladder-arm-case/2",
        "campaign": rc.CAMPAIGN_ID,
        "arm": arm,
        "case_id": case_id,
        "geometry": {"ngl": rc.MATCHED_NGL,
                     "ctx": dict(rc.CONTEXT_SETTINGS),
                     "request": dict(rc.REQUEST_CONTRACT)},
        "fixture_sha256": rc.R8D_FIXTURE_SHA256,
        "prompt_len": len(prompt_token_ids),
        "model_members": [m.name for m in model_files],
        "selector": {"cuda": cuda_selector, "vk": vk_selector,
                     "icd": str(icd) if icd else None},
        "pid": proc.pid,
        "t_start": t_start,
        "mem_before": mem_before,
        "journal_before_classes": j_before_classes["stop_classes"],
        "repeats": [],
    }
    repeats = []
    try:
        wait_server(port)
        time.sleep(5)
        for rep in rc.REQUIRED_REPEAT_IDS:
            mem_pre = sampler()
            t0 = time.time()
            resp = http_json(f"http://127.0.0.1:{port}/completion", body)
            dt = time.time() - t0
            mem_post = sampler()
            tokens = resp.get("tokens")
            if not isinstance(tokens, list):
                raise LadderError(
                    f"repeat {rep}: response carries no token array")
            sel_pre = mem_pre.get(selected_key, {})
            sel_post = mem_post.get(selected_key, {})
            exc = {}
            for ex in excluded_keys:
                exc[ex] = {"pre": mem_pre.get(ex, {}),
                           "post": mem_post.get(ex, {})}
            jraw = health.journal_kernel(since=t_start)
            jwin = health.classify_journal(jraw)
            repeats.append({
                "repeat": rep,
                "wall_s": round(dt, 3),
                "generated_tokens": tokens,
                "stop_type": resp.get("stop_type"),
                "stop_word": resp.get("stopping_word", ""),
                "raw_response": resp,
                "selected_residency": {"pre": sel_pre, "post": sel_post},
                "excluded_residency": exc,
                "health_window": {
                    "stop_classes": jwin["stop_classes"],
                    "correctable_rxerr_lines":
                        jwin["correctable_rxerr_lines"],
                },
            })
            stops = jwin["stop_classes"]
            if stops:
                doc["halted"] = f"repeat{rep}:{'+'.join(stops)}"
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        time.sleep(10)
        mem_after = sampler()
        jraw = health.journal_kernel(since=t_start)
        jfinal = health.classify_journal(jraw)
        log_text = log_path.read_text(errors="replace") or ""
        doc["post_exit"] = {
            "memory_after": mem_after,
            "exit_code": proc.returncode,
            "journal_final_stop_classes": jfinal["stop_classes"],
            "correctable_rxerr_lines": jfinal["correctable_rxerr_lines"],
        }
        doc["server_log_tail"] = log_text[-20000:]
        doc["backend_lines"] = [l for l in log_text.splitlines()
                                if "vulkan" in l.lower()
                                or "cuda" in l.lower()][:80]
    doc["repeats"] = repeats
    out = out_dir / f"ladder-{arm}-{case_id}.json"
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "arm": arm, "case_id": case_id,
        "repeats": len(repeats),
        "halted": doc.get("halted"),
        "exit_code": doc["post_exit"]["exit_code"],
    }))
    return doc


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=("A", "B", "C"), required=True)
    ap.add_argument("--server", type=Path, required=True)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--prompt-token-ids", required=True,
                    help="path to JSON list of prompt token ids")
    ap.add_argument("--cuda-selector")
    ap.add_argument("--vk-selector")
    ap.add_argument("--icd", type=Path)
    ap.add_argument("--selected-key", required=True)
    ap.add_argument("--excluded-keys", nargs="+", required=True)
    ap.add_argument("--port", type=int, default=18491)
    args = ap.parse_args()
    prompt = json.loads(Path(args.prompt_token_ids).read_text())
    run_arm_case(args.arm, args.server, args.model_dir, args.out_dir,
                 args.case, prompt, args.cuda_selector, args.vk_selector,
                 args.icd, args.selected_key, args.excluded_keys, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
