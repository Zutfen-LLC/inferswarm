#!/usr/bin/env python3
"""Issue #133 Arm-C retry — corrected direct-control comparator driver.

Drives the SAME integrated candidate substrate the node agent serves, with
the Coordinator/control plane fully bypassed, under the corrected #129/#133
comparator contract:

- per committed position: replay input = frozen rendered prompt ids +
  already committed generated ids;
- runtime session_id allocated through the FROZEN controller allocation
  (verbatim AST extraction of EpochServingController._runtime_session_id
  from the sha256-pinned r5b_epochs.py bytes — never a hand-copied formula);
- generate(max_new_tokens=2) with the on_token commit-capture callback
  present (the exact frozen generate() argument set);
- commit generated step zero; discard the speculative step-1 token;
- repeat until 8 committed tokens (the frozen stopping contract).

Single-shot max_new_tokens=8 is FORBIDDEN and not used.

Runs on inferswarm01 inside the frozen FreeToken worktree at 924cd22e…
(clean), under strace -f -e trace=file. The driver records the complete
per-call invocation transcript so the terminal reducer can compare the
direct arm against the ordinary arm's retained coordinator records
without trusting any authored equality label.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

FREETOKEN_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
#: the pinned r5b_epochs.py bytes retain their accepted #128/#129 pin
R5B_EPOCHS_SHA256 = (
    "388678971eb608741bd7dd4ad31a34e2e63c45fd2d0807e01065d077d9202805")
GENERATE_ARGUMENT_NAMES = (
    "max_new_tokens", "on_token", "prompt_token_ids", "session_id")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_runtime_session_allocation(pinned_source: str) -> dict:
    """Structurally extract _runtime_session_id from the pinned
    r5b_epochs.py bytes (same verification as the accepted #129 proof):
    one sequence increment; return logical_session_id * <int> + sequence;
    sequence zeroed in __init__. Returns the allocator facts; never a
    hand-copied formula."""
    tree = ast.parse(pinned_source)
    cls = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef)
         and node.name == "EpochServingController"), None)
    if cls is None:
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: pinned r5b_epochs.py carries no "
            "EpochServingController")
    init = next(
        (node for node in cls.body
         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
         and node.name == "__init__"), None)
    if init is None or "self._runtime_session_sequence = 0" not in (
            ast.get_source_segment(pinned_source, init) or ""):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: pinned __init__ does not zero the "
            "runtime-session sequence")
    fn = next(
        (node for node in cls.body
         if isinstance(node, ast.FunctionDef)
         and node.name == "_runtime_session_id"), None)
    if fn is None:
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: no _runtime_session_id to derive")
    segment = ast.get_source_segment(pinned_source, fn)
    body = fn.body
    ret = body[1].value if len(body) == 2 else None
    if (len(body) != 2 or not isinstance(body[0], ast.AugAssign)
            or not isinstance(body[1], ast.Return) or segment is None
            or not (isinstance(ret, ast.BinOp) and isinstance(ret.op, ast.Add)
                    and isinstance(ret.left, ast.BinOp)
                    and isinstance(ret.left.op, ast.Mult)
                    and isinstance(ret.left.left, ast.Name)
                    and ret.left.left.id == "logical_session_id"
                    and isinstance(ret.left.right, ast.Constant)
                    and isinstance(ret.left.right.value, int))):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: extracted _runtime_session_id does "
            "not have the frozen increment+return structure")
    return {
        "multiplier": ret.left.right.value,
        "method_sha256": sha256_bytes(segment.encode()),
        "method_line": fn.lineno,
    }


class FrozenRuntimeSessionAllocator:
    """Executes the verbatim extracted method (sequence starts at zero)."""

    def __init__(self, pinned_source: str) -> None:
        facts = extract_runtime_session_allocation(pinned_source)
        self.facts = facts
        namespace: dict = {}
        fn = None
        tree = ast.parse(pinned_source)
        cls = next(
            n for n in tree.body
            if isinstance(n, ast.ClassDef)
            and n.name == "EpochServingController")
        fn = next(
            n for n in cls.body
            if isinstance(n, ast.FunctionDef)
            and n.name == "_runtime_session_id")
        segment = ast.get_source_segment(pinned_source, fn)
        text = (
            "class _Alloc:\n"
            "    _runtime_session_sequence = 0\n"
            + "\n".join("    " + line for line in segment.splitlines())
            + "\n")
        exec(compile(text, "<frozen-runtime-session-allocation>", "exec"),
             namespace)
        self._impl = namespace["_Alloc"]()

    def allocate(self, logical_session_id: int) -> int:
        return int(self._impl._runtime_session_id(int(logical_session_id)))


def build_execution_plan(env: dict, chain_plan: dict) -> dict:
    """Compile the frozen execution plan via the producer's own machinery
    (identical to the accepted historical Arm-C construction)."""
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
            f"ARM_C_RETRY_DIRECT_FAIL: expected one legal shape, got "
            f"{evaluations}")
    evaluation = next(iter(evaluations.values()))
    if evaluation["state"] != "FEASIBLE_UNRANKED":
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: unexpected state "
            f"{evaluation['state']}")
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
    parser.add_argument("--fixture", required=True,
                        help="the #129 frozen rendered prompt-token fixture")
    parser.add_argument("--corpus", required=True,
                        help="the accepted integration fixture (c109 case "
                             "texts + raw ids; digest-pinned)")
    parser.add_argument("--pinned-r5b-epochs", required=True,
                        help="path to the sha256-pinned frozen r5b_epochs.py")
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
        raise SystemExit("ARM_C_RETRY_DIRECT_FAIL: dirty producer tree")
    if running != FREETOKEN_PRODUCER:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: producer {running} != "
            f"{FREETOKEN_PRODUCER}")

    # the frozen allocator derivation (fail-closed on byte drift)
    pinned_source = Path(args.pinned_r5b_epochs).read_text()
    if sha256_bytes(pinned_source.encode()) != R5B_EPOCHS_SHA256:
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: pinned r5b_epochs.py sha256 drift")
    allocator = FrozenRuntimeSessionAllocator(pinned_source)

    fixture = json.loads(Path(args.fixture).read_text())
    if fixture.get("fixture_digest") != (
            "sha256:6046d4796a5d9cc888030c6b3f07304c20ce117d93905c3"
            "00d7aae7c0ae01c7"):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: fixture digest drift against the "
            "#129 frozen rendered fixture")
    rows = sorted(fixture["cases"], key=lambda c: c["case_id"])
    if len(rows) != 24:
        raise SystemExit("ARM_C_RETRY_DIRECT_FAIL: expected 24 cases")

    corpus = json.loads(Path(args.corpus).read_text())
    if corpus.get("fixture_digest") != (
            "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a"
            "64f4508b2ba36f2"):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: corpus digest drift against the "
            "accepted integration fixture")
    prompt_texts = {
        row["case"]["case_id"]: row["case"]["prompt_text"]
        for row in corpus["cases"]}

    # render equality with the REAL tokenizer (24/24 mechanical check)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=False)
    for row in rows:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": prompt_texts[row["case_id"]]}],
            tokenize=False, add_generation_prompt=True)
        rendered = tok.encode(prompt, add_special_tokens=False)
        if rendered != row["rendered_prompt_token_ids"]:
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: real-tokenizer render mismatch "
                f"for {row['case_id']}")

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
    transcript = []
    # CORRECTED per-token replay-prefill invocation under the #133 contract
    for row in rows:
        case_id = row["case_id"]
        logical_session = int(row["session_index"])
        prompt_ids = list(row["rendered_prompt_token_ids"])
        committed: list[int] = []
        case_calls = []
        t0 = time.time_ns()
        while len(committed) < 8:
            replay_input = list(prompt_ids) + committed
            runtime_session_id = allocator.allocate(logical_session)
            token_holder: list[int] = []

            def capture(step: int, token: int, boundary) -> None:
                if step == 0:
                    token_holder.append(int(token))

            result = runtime.generate(
                session_id=runtime_session_id,
                prompt_token_ids=replay_input,
                max_new_tokens=2,
                on_token=capture,
            )
            if result.get("plan_digest") != execution_plan["digest"]:
                raise SystemExit(
                    "ARM_C_RETRY_DIRECT_FAIL: runtime silently substituted "
                    "a plan")
            tokens = [int(t) for t in result["generated_token_ids"]]
            if not tokens:
                raise SystemExit(
                    f"ARM_C_RETRY_DIRECT_FAIL: replay produced no token "
                    f"({case_id} step {len(committed)})")
            # commit step zero (captured via the on_token boundary when
            # present, matching the controller's capture contract); the
            # speculative step-1 token is discarded before replay
            committed_token = (
                token_holder[-1] if token_holder else tokens[0])
            committed.append(committed_token)
            case_calls.append({
                "runtime_session_id": runtime_session_id,
                "prompt_token_ids": replay_input,
                "max_new_tokens": 2,
                "argument_names": sorted(GENERATE_ARGUMENT_NAMES),
                "response_token_ids": tokens,
                "committed_token": committed_token,
                "speculative_discarded": tokens[1:],
                "on_token_present": True,
            })
        decoded = tok.decode(committed)
        results.append({
            "schema": "inferswarm.issue133.arm-c-retry.direct-case/1",
            "case_id": case_id,
            "logical_session_id": logical_session,
            "prompt_token_ids": prompt_ids,
            "generated_token_ids": committed,
            "invocation": "per-token-replay-prefill/frozen-allocator/1",
            "decoded_output": decoded,
            "decoded_output_sha256": hashlib.sha256(
                decoded.encode("utf-8", errors="surrogatepass")).hexdigest(),
            "plan_digest": execution_plan["digest"],
            "wall_ns": time.time_ns() - t0,
        })
        transcript.append({
            "case_id": case_id,
            "logical_session_id": logical_session,
            "calls": case_calls,
        })
        (out / f"direct-{case_id}.json").write_text(json.dumps(
            results[-1], indent=2, sort_keys=True) + "\n")

    report = dict(runtime.report())
    runtime.close()
    record = {
        "schema": "inferswarm.issue133.arm-c-retry.direct-run/1",
        "attempt_id": args.attempt_id,
        "producer": running,
        "plan_digest": execution_plan["digest"],
        "chain_plan_digest": chain_plan["digest"],
        "runtime_session_allocation": allocator.facts,
        "comparator_contract": {
            "max_new_tokens": 2,
            "commit": "step zero only",
            "speculative": "step one discarded",
            "single_shot_max_new_tokens_8_used": False,
        },
        "realization_wall_ns": realized_ns - started_ns,
        "case_count": len(results),
        "results": results,
        "invocation_transcript": transcript,
        "runtime_report": report,
        "completed_at_ns": time.time_ns(),
    }
    (out / "direct-run.json").write_text(json.dumps(
        record, indent=2, sort_keys=True) + "\n")
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
