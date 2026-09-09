#!/usr/bin/env python3
"""Issue #117 Arm C — direct-control comparator driver (inferswarm01).

Drives the SAME integrated candidate substrate the node agent serves, with
the Coordinator/control plane fully bypassed: constructs
ChainEpochRuntime exactly as the node agent's build_runtime does (same
chain plan, same model view dir, same remote last-stage service) and calls
generate() directly per fixture case.

Also renders each case's prompt with the same tokenizer files the
coordinator uses (independent render; equality is verified by the reducer,
not here) and retains per-case token results.

Runs inside the frozen FreeToken worktree at 924cd22e… (clean) under
strace -f -e trace=file. No torch import before producer verification.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

FREETOKEN_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True,
                        default="/srv/inferswarm/state/arm-c/chain-plan.json")
    parser.add_argument("--view-dir",
                        default="/srv/inferswarm/state/arm-c/model-view")
    parser.add_argument("--last-stage-host", default="10.0.0.219")
    parser.add_argument("--last-stage-port", type=int, default=18485)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--attempt-id", required=True)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    running = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "status", "--porcelain"], text=True)
    if status:
        raise SystemExit(f"ARM_C_DIRECT_FAIL: dirty producer tree")
    if running != FREETOKEN_PRODUCER:
        raise SystemExit(
            f"ARM_C_DIRECT_FAIL: producer {running} != {FREETOKEN_PRODUCER}")

    fixture = json.loads(Path(args.fixture).read_text())
    cases = sorted(fixture["cases"], key=lambda c: c["case"]["case_id"])
    if len(cases) != 24:
        raise SystemExit(f"ARM_C_DIRECT_FAIL: expected 24 cases")

    # Independent render with the same tokenizer files (transformers is
    # available in the producer venv on the compute node).
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=False)
    rendered = {}
    for case in cases:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": case["case"]["prompt_text"]}],
            tokenize=False, add_generation_prompt=True)
        rendered[case["case"]["case_id"]] = tok.encode(
            prompt, add_special_tokens=False)

    # Same substrate as the node agent.
    from benchmarks.inferswarm_r6.chain_runtime import realize_dense_chain
    plan = json.loads(Path(args.plan).read_text())
    started_ns = time.time_ns()
    runtime = realize_dense_chain(
        {"digest": plan["digest"]},
        chain_plan_path=args.plan,
        model_path=args.view_dir,
        last_stage_host=args.last_stage_host,
        last_stage_port=args.last_stage_port,
    )
    realized_ns = time.time_ns()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for index, case in enumerate(cases, 1):
        case_id = case["case"]["case_id"]
        t0 = time.time_ns()
        result = runtime.generate(
            session_id=index,
            prompt_token_ids=rendered[case_id],
            max_new_tokens=8,
        )
        results.append({
            "schema": "inferswarm.issue117.arm-c.direct-case/1",
            "case_id": case_id,
            "session_id": index,
            "prompt_token_ids": rendered[case_id],
            "generated_token_ids": list(result["generated_token_ids"]),
            "plan_digest": result.get("plan_digest"),
            "wall_ns": time.time_ns() - t0,
        })
        (out / f"direct-{case_id}.json").write_text(json.dumps(
            results[-1], indent=2, sort_keys=True) + "\n")

    report = dict(runtime.report())
    runtime.close()
    record = {
        "schema": "inferswarm.issue117.arm-c.direct-run/1",
        "attempt_id": args.attempt_id,
        "producer": running,
        "plan_digest": plan["digest"],
        "realization_wall_ns": realized_ns - started_ns,
        "case_count": len(results),
        "results": results,
        "runtime_report": report,
        "completed_at_ns": time.time_ns(),
    }
    (out / "direct-run.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "direct_run": str(out / "direct-run.json"),
        "cases": len(results),
        "first_case_tokens": results[0]["generated_token_ids"],
        "last_case_tokens": results[-1]["generated_token_ids"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
