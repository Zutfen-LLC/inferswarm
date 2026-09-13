#!/usr/bin/env python3
"""Issue #172 — physical direct-control comparator driver (inferswarm01).

The accepted #133 corrected direct comparator, extended to the 40-case
campaign corpus and the Phase-5 sentinel repeats. Semantics UNCHANGED
from the accepted driver:

- per committed position: replay input = frozen rendered prompt ids +
  already committed generated ids;
- runtime session id through the frozen AST-extracted allocator
  (sha256-pinned r5b_epochs.py bytes);
- generate(max_new_tokens=2) with on_token commit capture;
- commit step zero; discard speculative step one; stop at 8;
- the r5a static-plan authorization fence (authorized == locally built
  == runtime-returned) before realization;
- all deployed inputs byte-pinned; tokenizer Source rule enforced on
  the resolved path.

Runs inside the verified producer worktree at 6202eee (clean) with
PYTHONPATH=python:benchmarks. Evidence lands in the fresh namespace
/srv/inferswarm/state/arm-c-requal-172/.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.metadata
import json
import subprocess
import sys
import time
from pathlib import Path

FREETOKEN_PRODUCER = "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469"
FREETOKEN_166_IMPLEMENTATION = "64a37a1f1a2797a190610c5adcdcb4157bce63b9"
R5B_EPOCHS_SHA256 = (
    "388678971eb608741bd7dd4ad31a34e2e63c45fd2d0807e01065d077d9202805")
GENERATE_ARGUMENT_NAMES = (
    "max_new_tokens", "on_token", "prompt_token_ids", "session_id")

ARM_B_PARTICIPANT_PLAN_DIGEST = (
    "sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad")
AUTHORIZED_R5A_STATIC_PLAN_DIGEST = (
    "sha256:208be7956474a559756355c85142eb6716585f4c0320a27fe73d2f4196972c3e")
AUTHORIZED_R5A_STATIC_PLAN_SCHEMA = (
    "inferswarm.r5a.static-execution-plan/1")
if ARM_B_PARTICIPANT_PLAN_DIGEST == AUTHORIZED_R5A_STATIC_PLAN_DIGEST:
    raise SystemExit("plan-family conflation")
#: the accepted #133 chain plan remains the authority invariant; the
#: campaign executes its content-identical re-freeze under 6202eee
ACCEPTED_CHAIN_PLAN_DIGEST = (
    "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd6806b6ee53b9bc51f")
AUTHORIZED_CHAIN_PLAN_172_DIGEST = (
    "sha256:b24c3ca06b3ea79b62fdea8058afe9f71e0c69187b5cd77740cc5855f9796529")
AUTHORIZED_ENVIRONMENT_172_CANONICAL_SHA256 = (
    "sha256:cd0909bb96fc637a921218c973aaa1640579af7093681714cd3216a0dfa5f279")
AUTHORIZED_PARTICIPANT_IDENTITY = (
    "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1")

AUTHORIZED_MODEL_VIEW_PATH = "/srv/inferswarm/state/arm-c/model-view"
AUTHORIZED_LAST_STAGE_HOST = "10.0.0.219"
AUTHORIZED_LAST_STAGE_PORT = 18485
AUTHORIZED_TOKENIZER_PATH = "/srv/inferswarm/tokenizers/gemma-r6-frozen"
FORBIDDEN_SOURCE_ROOT = "/srv/models/"
AUTHORIZED_INPUT_PATHS = {
    "plan": "/srv/inferswarm/state/arm-c-requal-172/chain-plan.json",
    "environment": "/srv/inferswarm/state/arm-c-requal-172/environment.json",
    "fixture": "/srv/inferswarm/state/arm-c-requal-172/campaign-corpus.json",
    "pinned_r5b_epochs":
        "/srv/inferswarm/state/arm-c-requal-172/scripts/r5b_epochs.py",
}
AUTHORIZED_INPUT_FILE_SHA256 = {
    "pinned_r5b_epochs": R5B_EPOCHS_SHA256,
}
CAMPAIGN_CORPUS_DIGEST = None  # bound at deploy time; set by deploy script
TOKENIZER_ASSET_PINS = {
    "chat_template.jinja":
        "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4",
    "config.json":
        "478c46e8d2c52d5c2d85bf67e3b3e8c90e7c9d91086cee27e3c267907e936bd9",
    "generation_config.json":
        "a8349d9bd64cc5841297fcb5002f0fdc4749c473c8f1b10ea337f9ce4ee7014e",
    "tokenizer.json":
        "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
    "tokenizer_config.json":
        "a62f4e85a47c0c136edaaa3a4f591fd6783717299a9def47e5ad03a49f6a5eb9",
}
TOKENIZER_PYTHON = "3.13"
OUTPUT_ROOT = "/srv/inferswarm/state/arm-c-requal-172/attempts"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


# --- frozen allocator extraction (accepted #129/#133, verbatim) --------
def extract_runtime_session_allocation(pinned_source: str) -> dict:
    tree = ast.parse(pinned_source)
    cls = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef)
         and node.name == "EpochServingController"), None)
    if cls is None:
        raise SystemExit("no EpochServingController in pinned bytes")
    init = next(
        (node for node in cls.body
         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
         and node.name == "__init__"), None)
    if init is None or "self._runtime_session_sequence = 0" not in (
            ast.get_source_segment(pinned_source, init) or ""):
        raise SystemExit("pinned __init__ does not zero the sequence")
    fn = next(
        (node for node in cls.body
         if isinstance(node, ast.FunctionDef)
         and node.name == "_runtime_session_id"), None)
    if fn is None:
        raise SystemExit("no _runtime_session_id to derive")
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
        raise SystemExit("extracted _runtime_session_id structure drift")
    return {
        "multiplier": ret.left.right.value,
        "method_sha256": sha256_bytes(segment.encode()),
        "method_line": fn.lineno,
    }


class FrozenRuntimeSessionAllocator:
    def __init__(self, pinned_source: str) -> None:
        self.facts = extract_runtime_session_allocation(pinned_source)
        namespace: dict = {}
        tree = ast.parse(pinned_source)
        cls = next(
            (n for n in tree.body
             if isinstance(n, ast.ClassDef)
             and n.name == "EpochServingController"))
        fn = next(
            (n for n in cls.body
             if isinstance(n, ast.FunctionDef)
             and n.name == "_runtime_session_id"))
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


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def activate_producer_worktree(repo: Path) -> None:
    for name, module in tuple(sys.modules.items()):
        if not any(name == prefix or name.startswith(prefix + ".")
                   for prefix in ("benchmarks", "freetoken")):
            continue
        origin = getattr(module, "__file__", None)
        if origin is not None and not _within(Path(origin).resolve(), repo):
            raise SystemExit(
                f"preloaded producer module {name} resolves outside the "
                f"verified worktree: {origin}")
    for root in reversed((repo, repo / "python", repo / "benchmarks")):
        if not root.is_dir():
            raise SystemExit(f"verified producer import root missing: {root}")
        value = str(root)
        sys.path[:] = [e for e in sys.path if e != value]
        sys.path.insert(0, value)


def require_producer_module(repo: Path, name: str, relative: str):
    module = importlib.import_module(name)
    origin = getattr(module, "__file__", None)
    expected = (repo / relative).resolve()
    if origin is None or Path(origin).resolve() != expected:
        raise SystemExit(
            f"producer module {name} resolved to {origin!r}, not {expected}")
    return module


def build_execution_plan(repo: Path, env: dict, chain_plan: dict) -> dict:
    strategy = require_producer_module(
        repo, "benchmarks.inferswarm_r6.xc_strategy",
        "benchmarks/inferswarm_r6/xc_strategy.py")
    coordinator = require_producer_module(
        repo, "benchmarks.inferswarm_r6.coordinator",
        "benchmarks/inferswarm_r6/coordinator.py")
    planner = require_producer_module(
        repo, "freetoken.research.r3_planner",
        "python/freetoken/research/r3_planner.py")
    serving = require_producer_module(
        repo, "freetoken.research.r5a_serving",
        "python/freetoken/research/r5a_serving.py")
    sha = env["implementation_commit"]
    decision = planner.plan(
        strategy.planning_problem(sha), coordinator._r6_snapshot(env),
        strategy.operator_policy(sha), coordinator._r6_objective(sha),
        planner.freeze({"schema": "inferswarm.r6.evidence-catalog/1",
                        "implementation_commit": sha, "records": []}),
    )
    evaluations = {item["id"]: item for item in decision["evaluations"]}
    if len(evaluations) != 1:
        raise SystemExit(f"expected one legal shape, got {evaluations}")
    evaluation = next(iter(evaluations.values()))
    if evaluation["state"] != "FEASIBLE_UNRANKED":
        raise SystemExit(f"unexpected state {evaluation['state']}")
    authorization = {
        "mode": "CONTROLLED_EVIDENCE_COLLECTION_OVERRIDE",
        "candidate_id": evaluation["id"],
        "planner_selected_candidate_id": decision.get("selected_candidate_id"),
        "automatic_selection_preserved": True,
        "reason": (
            "direct-control comparator compiles the only legal shape "
            "before any ranking evidence exists; the ordinary arm "
            "selects the same candidate automatically from measured "
            "evidence"),
    }
    plan = serving.freeze_execution_plan(
        decision=decision,
        evaluation=evaluation,
        authorization=authorization,
        compiled_body=strategy.compile_candidate(
            dict(evaluation), chain_plan=dict(chain_plan)),
        objective=coordinator._r6_objective(sha),
        policy=strategy.operator_policy(sha),
    )
    if plan.get("schema") != AUTHORIZED_R5A_STATIC_PLAN_SCHEMA:
        raise SystemExit(f"wrong plan family {plan.get('schema')!r}")
    return plan


def verify_chain_plan_authorization(chain_plan: dict) -> None:
    digest = chain_plan.get("digest")
    body = {k: v for k, v in chain_plan.items() if k != "digest"}
    recomputed = "sha256:" + sha256_bytes(
        (json.dumps(body, sort_keys=True,
                    separators=(",", ":")) + "\n").encode())
    if digest != recomputed:
        raise SystemExit("chain plan digest not self-consistent")
    if digest != AUTHORIZED_CHAIN_PLAN_172_DIGEST:
        raise SystemExit("chain plan digest is not the authorized #172 freeze")
    prov172 = chain_plan.get("provenance", {}).get("issue172_arm_c_requal", {})
    if prov172.get("producer_sha") != FREETOKEN_PRODUCER:
        raise SystemExit("chain plan not bound to the #172 producer")
    if prov172.get("accepted_arm_c_chain_plan") != ACCEPTED_CHAIN_PLAN_DIGEST:
        raise SystemExit("chain plan does not chain to the accepted #133 plan")
    if prov172.get("accepted_plan_digest") != AUTHORIZED_PARTICIPANT_IDENTITY:
        raise SystemExit("chain plan not derived from accepted participant")


def verify_environment_authorization(environment: dict) -> None:
    actual = sha256_bytes(canonical_bytes(environment))
    if actual != AUTHORIZED_ENVIRONMENT_172_CANONICAL_SHA256.removeprefix(
            "sha256:"):
        raise SystemExit(
            f"environment canonical sha256 {actual} != authorized "
            f"{AUTHORIZED_ENVIRONMENT_172_CANONICAL_SHA256}")
    if environment.get("implementation_commit") != FREETOKEN_PRODUCER:
        raise SystemExit("environment not bound to the #172 producer")


def verify_r5a_fence(built_plan: dict) -> None:
    if built_plan.get("schema") != AUTHORIZED_R5A_STATIC_PLAN_SCHEMA:
        raise SystemExit("wrong plan family at the fence")
    if built_plan.get("digest") != AUTHORIZED_R5A_STATIC_PLAN_DIGEST:
        raise SystemExit(
            f"locally built r5a digest {built_plan.get('digest')} != "
            f"authorized {AUTHORIZED_R5A_STATIC_PLAN_DIGEST}")


def verify_pinned_file(path: str, expected_sha256: str, label: str) -> bytes:
    raw = Path(path).read_bytes()
    actual = sha256_bytes(raw)
    if actual != expected_sha256:
        raise SystemExit(f"{label} sha256 drift: {actual} != {expected_sha256}")
    return raw


def verify_tokenizer(path: str) -> None:
    if path != AUTHORIZED_TOKENIZER_PATH:
        raise SystemExit("tokenizer path drift")
    asset_dir = Path(path)
    resolved = asset_dir.resolve()
    forbidden = Path(FORBIDDEN_SOURCE_ROOT).resolve()
    if resolved == forbidden or forbidden in resolved.parents:
        raise SystemExit("tokenizer resolves into the forbidden Source root")
    if asset_dir.is_symlink() or not asset_dir.is_dir():
        raise SystemExit("tokenizer deployment must be a real directory")
    entries = {e.name for e in asset_dir.iterdir()}
    if entries != set(TOKENIZER_ASSET_PINS):
        raise SystemExit(f"tokenizer entries {sorted(entries)}")
    for name, expected in TOKENIZER_ASSET_PINS.items():
        verify_pinned_file(str(asset_dir / name), expected,
                           f"tokenizer asset {name}")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if python_version != TOKENIZER_PYTHON:
        raise SystemExit(f"tokenizer python {python_version} != 3.13")


def run_case(runtime, allocator, execution_plan, tok, row, out_dir: Path,
             label: str) -> dict:
    """One case under the corrected comparator loop; per-call transcript
    retained. Identical inputs produce identical invocations for
    sentinel repeats (fresh runtime session ids per committed position
    from the frozen allocator, RESET-driven fresh session state in the
    substrate)."""
    case_id = row["case_id"]
    logical_session = int(row["session_index"])
    prompt_ids = list(row["rendered_prompt_token_ids"])
    committed: list[int] = []
    calls = []
    t0 = time.time_ns()
    while len(committed) < 8:
        replay_input = list(prompt_ids) + committed
        runtime_session_id = allocator.allocate(logical_session)
        holder: list[int] = []

        def capture(step: int, token: int, boundary) -> None:
            if step == 0:
                holder.append(int(token))

        result = runtime.generate(
            session_id=runtime_session_id,
            prompt_token_ids=replay_input,
            max_new_tokens=2,
            on_token=capture,
        )
        if result.get("plan_digest") != execution_plan["digest"]:
            raise SystemExit("runtime silently substituted a plan")
        tokens = [int(t) for t in result["generated_token_ids"]]
        if not tokens:
            raise SystemExit(
                f"replay produced no token ({case_id} step {len(committed)})")
        committed_token = holder[-1] if holder else tokens[0]
        committed.append(committed_token)
        calls.append({
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
    record = {
        "schema": "inferswarm.issue172.arm-c-requal.direct-case/1",
        "case_id": case_id,
        "label": label,
        "logical_session_id": logical_session,
        "prompt_token_ids": prompt_ids,
        "generated_token_ids": committed,
        "invocation": "per-token-replay-prefill/frozen-allocator/1",
        "decoded_output": decoded,
        "decoded_output_sha256": hashlib.sha256(
            decoded.encode("utf-8", errors="surrogatepass")).hexdigest(),
        "plan_digest": execution_plan["digest"],
        "wall_ns": time.time_ns() - t0,
    }
    (out_dir / f"direct-{label}-{case_id}.json").write_text(json.dumps(
        record, indent=2, sort_keys=True) + "\n")
    return {"record": record, "calls": calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="/home/zutfen/FreeToken")
    parser.add_argument("--plan", default=AUTHORIZED_INPUT_PATHS["plan"])
    parser.add_argument("--environment",
                        default=AUTHORIZED_INPUT_PATHS["environment"])
    parser.add_argument("--fixture", default=AUTHORIZED_INPUT_PATHS["fixture"])
    parser.add_argument("--fixture-digest", required=True,
                        help="canonical combined digest of campaign corpus")
    parser.add_argument("--pinned-r5b-epochs",
                        default=AUTHORIZED_INPUT_PATHS["pinned_r5b_epochs"])
    parser.add_argument("--tokenizer", default=AUTHORIZED_TOKENIZER_PATH)
    parser.add_argument("--view-dir", default=AUTHORIZED_MODEL_VIEW_PATH)
    parser.add_argument("--last-stage-host", default=AUTHORIZED_LAST_STAGE_HOST)
    parser.add_argument("--last-stage-port", type=int,
                        default=AUTHORIZED_LAST_STAGE_PORT)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--mode", choices=["canonical", "sentinels"],
                        default="canonical")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    running = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "status", "--porcelain"], text=True)
    if status:
        raise SystemExit("dirty producer tree")
    if running != FREETOKEN_PRODUCER:
        raise SystemExit(f"producer {running} != {FREETOKEN_PRODUCER}")
    activate_producer_worktree(repo)

    if args.out_dir != str(
            Path(OUTPUT_ROOT) / args.attempt_id / args.mode / "direct"):
        raise SystemExit("out-dir is not the attempt-bound path")

    pinned_raw = verify_pinned_file(
        args.pinned_r5b_epochs, R5B_EPOCHS_SHA256, "pinned r5b_epochs.py")
    allocator = FrozenRuntimeSessionAllocator(pinned_raw.decode())

    corpus = json.loads(verify_pinned_file(
        args.fixture, args.fixture_digest, "campaign corpus"))
    cases = corpus["cases"]
    if len(cases) != 40:
        raise SystemExit("campaign corpus must carry 40 cases")
    # double-bind: canonical combined digest over the 40 case rows
    combined = "sha256:" + sha256_bytes(json.dumps(
        cases, sort_keys=True, separators=(",", ":")).encode())
    if combined != corpus.get("combined_canonical_digest"):
        raise SystemExit("campaign corpus combined digest drift")

    verify_tokenizer(args.tokenizer)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(
        args.tokenizer, trust_remote_code=False, local_files_only=True)
    # pin every case render through the real tokenizer
    for row in cases:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": row["prompt_text"]}],
            tokenize=False, add_generation_prompt=True)
        rendered = tok.encode(prompt, add_special_tokens=False)
        if row["arm"] == "generalization-170":
            if len(rendered) != row["rendered_len"]:
                raise SystemExit(
                    f"{row['case_id']} render length drift")
        else:
            if rendered != row["rendered_prompt_token_ids"]:
                raise SystemExit(
                    f"{row['case_id']} real-tokenizer render mismatch")
        row["rendered_prompt_token_ids"] = rendered

    chain_plan = json.loads(Path(args.plan).read_text())
    environment = json.loads(Path(args.environment).read_text())

    verify_chain_plan_authorization(chain_plan)
    verify_environment_authorization(environment)
    execution_plan = build_execution_plan(repo, environment, chain_plan)
    verify_r5a_fence(execution_plan)

    chain_runtime = require_producer_module(
        repo, "benchmarks.inferswarm_r6.chain_runtime",
        "benchmarks/inferswarm_r6/chain_runtime.py")
    started_ns = time.time_ns()
    runtime = chain_runtime.realize_dense_chain(
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

    # SWA pristine-state observation seam: the accepted #166 report on the
    # LAST stage's final report; local stages report through report().
    results = []
    transcript = []
    try:
        if args.mode == "canonical":
            for row in cases:
                entry = run_case(runtime, allocator, execution_plan, tok,
                                 row, out, label="canonical")
                results.append(entry["record"])
                transcript.append({
                    "case_id": row["case_id"],
                    "logical_session_id": row["session_index"],
                    "calls": entry["calls"],
                })
        else:
            sentinels = [c for c in cases if c["case_id"] in (
                "c109-04-02-047", "c109-04-06-074", "c109-03-04-003",
                "g170-01", "g170-05", "g170-09", "g170-13")]
            if len(sentinels) != 7:
                raise SystemExit("sentinel identities missing from corpus")
            for repeat in range(1, 7):
                for row in sentinels:
                    label = f"r{repeat}"
                    entry = run_case(
                        runtime, allocator, execution_plan, tok, row, out,
                        label=label)
                    entry["record"]["repeat"] = repeat
                    results.append(entry["record"])
                    transcript.append({
                        "case_id": row["case_id"],
                        "repeat": repeat,
                        "logical_session_id": row["session_index"],
                        "calls": entry["calls"],
                    })
        report = dict(runtime.report())
    finally:
        runtime.close()

    record = {
        "schema": "inferswarm.issue172.arm-c-requal.direct-run/1",
        "attempt_id": args.attempt_id,
        "mode": args.mode,
        "producer": running,
        "producer_implementation": FREETOKEN_166_IMPLEMENTATION,
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
    print(json.dumps({
        "direct_run": str(out / "direct-run.json"),
        "execution_plan_digest": execution_plan["digest"],
        "cases": len(results),
        "mode": args.mode,
        "first_case_tokens": results[0]["generated_token_ids"] if results
        else None,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
