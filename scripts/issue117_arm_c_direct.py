#!/usr/bin/env python3
"""Issue #117 Arm C — direct-control comparator driver (inferswarm01).

Drives the SAME integrated candidate substrate the node agent serves, with
the Coordinator/control plane fully bypassed: compiles the execution plan
with the frozen producer's own strategy/planner machinery (identical legal
candidate; authorization honestly recorded as a controlled
evidence-collection override because no ranking evidence exists before the
first physical measurement — the ordinary arm later selects the same
candidate AUTOMATICALLY from the measured record), constructs
ChainEpochRuntime exactly as the node agent's build_runtime does (same
chain plan, same model view dir, same remote last-stage service) and calls
generate() directly per fixture case.

Runs inside the frozen FreeToken worktree at 924cd22e… (clean) under
strace -f -e trace=file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

FREETOKEN_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"


def build_execution_plan(env: dict, chain_plan: dict) -> dict:
    """Compile the frozen execution plan via the producer's own machinery."""
    from benchmarks.inferswarm_r6.xc_strategy import (
        compile_candidate,
        operator_policy,
        planning_problem,
    )
    from benchmarks.inferswarm_r6.coordinator import (
        _r6_objective,
        _r6_snapshot,
    )
    from freetoken.research.r3_planner import freeze, plan as r3plan
    from freetoken.research.r5a_serving import freeze_execution_plan

    sha = env["implementation_commit"]
    decision = r3plan(
        planning_problem(sha), _r6_snapshot(env), operator_policy(sha),
        _r6_objective(sha),
        freeze({"schema": "inferswarm.r6.evidence-catalog/1",
                "implementation_commit": sha, "records": []}),
    )
    evaluations = {item["id"]: item for item in decision["evaluations"]}
    if len(evaluations) != 1:
        raise SystemExit(
            f"ARM_C_DIRECT_FAIL: expected one legal shape, got {evaluations}")
    evaluation = next(iter(evaluations.values()))
    if evaluation["state"] != "FEASIBLE_UNRANKED":
        raise SystemExit(
            f"ARM_C_DIRECT_FAIL: unexpected state {evaluation['state']}")
    authorization = {
        "mode": "CONTROLLED_EVIDENCE_COLLECTION_OVERRIDE",
        "candidate_id": evaluation["id"],
        "planner_selected_candidate_id": decision.get("selected_candidate_id"),
        "automatic_selection_preserved": True,
        "reason": "direct-control comparator compiles the only legal shape "
                  "before any ranking evidence exists; the ordinary arm "
                  "selects the same candidate automatically from measured "
                  "evidence",
    }
    return freeze_execution_plan(
        decision=decision,
        evaluation=evaluation,
        authorization=authorization,
        compiled_body=compile_candidate(dict(evaluation),
                                        chain_plan=dict(chain_plan)),
        objective=_r6_objective(sha),
        policy=operator_policy(sha),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="FreeToken worktree root (default: inferred)")
    parser.add_argument("--plan", required=True,
                        default="/srv/inferswarm/state/arm-c/chain-plan.json")
    parser.add_argument("--environment", required=True,
                        default="/srv/inferswarm/state/arm-c/environment.json")
    parser.add_argument("--view-dir",
                        default="/srv/inferswarm/state/arm-c/model-view")
    parser.add_argument("--last-stage-host", default="10.0.0.219")
    parser.add_argument("--last-stage-port", type=int, default=18485)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--attempt-id", required=True)
    args = parser.parse_args()

    repo = Path(args.repo).resolve() if args.repo else Path(
        __file__).resolve().parents[2]
    running = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "status", "--porcelain"], text=True)
    if status:
        raise SystemExit("ARM_C_DIRECT_FAIL: dirty producer tree")
    if running != FREETOKEN_PRODUCER:
        raise SystemExit(
            f"ARM_C_DIRECT_FAIL: producer {running} != {FREETOKEN_PRODUCER}")

    fixture = json.loads(Path(args.fixture).read_text())
    cases = sorted(fixture["cases"], key=lambda c: c["case"]["case_id"])
    if len(cases) != 24:
        raise SystemExit("ARM_C_DIRECT_FAIL: expected 24 cases")

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=False)
    rendered = {}
    for case in cases:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": case["case"]["prompt_text"]}],
            tokenize=False, add_generation_prompt=True)
        rendered[case["case"]["prompt_text"]] = tok.encode(
            prompt, add_special_tokens=False)

    chain_plan = json.loads(Path(args.plan).read_text())
    environment = json.loads(Path(args.environment).read_text())
    execution_plan = build_execution_plan(environment, chain_plan)

    from benchmarks.inferswarm_r6.chain_runtime import realize_dense_chain
    started_ns = time.time_ns()
    runtime = realize_dense_chain(
        dict(execution_plan),
        chain_plan_path=args.plan,
        model_path=args.view_dir,
        last_stage_host=args.last_stage_host,
        last_stage_port=args.last_stage_port,
    )
    realized_ns = time.time_ns()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "execution-plan.json").write_text(json.dumps(
        execution_plan, indent=2, sort_keys=True) + "\n")
    results = []
    # Canonical per-token replay-prefill invocation (the accepted #62/#67/V5
    # canonical-prefix contract; identical commit semantics to the ordinary
    # controller's serve_tokens loop: one committed token per generate over
    # the full replayed prefix, speculative step-1 discarded). A single-shot
    # max_new_tokens=8 incremental decode is NOT an accepted invocation of
    # this substrate (known anomalous KV-append path) and is not used.
    for index, case in enumerate(cases, 1):
        case_id = case["case"]["case_id"]
        prompt_ids = rendered[case["case"]["prompt_text"]]
        committed: list[int] = []
        t0 = time.time_ns()
        while len(committed) < 8:
            replay_input = list(prompt_ids) + committed
            result = runtime.generate(
                session_id=index,
                prompt_token_ids=replay_input,
                max_new_tokens=2,
            )
            tokens = [int(t) for t in result["generated_token_ids"]]
            if not tokens:
                raise SystemExit(
                    f"ARM_C_DIRECT_FAIL: replay produced no token "
                    f"({case_id} step {len(committed)})")
            committed.append(tokens[0])
        decoded = tok.decode(committed)
        results.append({
            "schema": "inferswarm.issue117.arm-c.direct-case/1",
            "case_id": case_id,
            "session_id": index,
            "prompt_token_ids": prompt_ids,
            "generated_token_ids": committed,
            "invocation": "per-token-replay-prefill/1",
            "decoded_output": decoded,
            "decoded_output_sha256": hashlib.sha256(
                decoded.encode("utf-8", errors="surrogatepass")).hexdigest(),
            "plan_digest": execution_plan["digest"],
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
        "plan_digest": execution_plan["digest"],
        "chain_plan_digest": chain_plan["digest"],
        "realization_wall_ns": realized_ns - started_ns,
        "case_count": len(results),
        "results": results,
        "runtime_report": report,
        "completed_at_ns": time.time_ns(),
    }
    (out / "direct-run.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    # measured ttft evidence for the ordinary arm's planner (EXACT_CONTEXT)
    ttfts = [r["wall_ns"] for r in results]
    print(json.dumps({
        "direct_run": str(out / "direct-run.json"),
        "execution_plan_digest": execution_plan["digest"],
        "cases": len(results),
        "first_case_tokens": results[0]["generated_token_ids"],
        "median_wall_ms": sorted(ttfts)[len(ttfts) // 2] / 1e6,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
