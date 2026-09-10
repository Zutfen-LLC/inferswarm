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

AUTHORIZATION FENCE (before realize_dense_chain and before any
model/runtime generation can occur): the locally built execution plan
must equal the issue #133 authorized Arm-B execution-plan digest

    sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad

and every external input capable of changing the physical plan/substrate
is mechanically bound to accepted evidence BEFORE realization:

- `--environment` must equal the accepted Arm-C environment freeze
  (canonical-JSON equality against the identity retained in the accepted
  run record);
- `--plan` (the chain plan) must equal, byte-for-byte in canonical JSON,
  the accepted Arm-C chain plan re-frozen from the accepted Arm-B
  participant plan (its digest is pinned, and its provenance must carry
  the accepted participant identity sha256:ee845188…);
- the pinned r5b_epochs.py bytes are sha256-pinned;
- the producer worktree must be clean at exactly 924cd22e…;
- the fixture/corpus digests are pinned.

authorized frozen digest == locally built plan digest ==
runtime-returned digest: the runtime-substitution fence
(`result["plan_digest"]`) remains AND the authorization fence is added
before realization.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import re
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

#: ---------------------------------------------------------------------------
#: Authorized plan/participant identities (issue #133; the participant
#: identity sha256:ee845188… is the ACCEPTED Arm-B participant-plan
#: digest — proven from the accepted retained Arm-C plan-verification
#: record and the retained chain plan's provenance, which bind
#: accepted_plan_digest == sha256:ee845188… and arm_c_plan_digest ==
#: sha256:a71a3129… as the exact relationship between the accepted
#: participant plan and the supplied chain plan).
AUTHORIZED_EXECUTION_PLAN_DIGEST = (
    "sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad")
AUTHORIZED_CHAIN_PLAN_DIGEST = (
    "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd6806b6ee53b9bc51f")
AUTHORIZED_PARTICIPANT_IDENTITY = (
    "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1")

#: The accepted environment is derived by the Issue #129 methodology from
#: ``evidence/physical-preflight.json``. Phase A retains its canonical digest
#: here. The direct driver does not load or execute a mutable methodology
#: module to decide which environment is authorized.
AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256 = (
    "182b950e844c078fd0a9d91c321cd67097c81d3d4fd704a86618407b6399b274")

#: Every realization-affecting location and endpoint is fixed before the
#: authorization fence. The source records are retained accepted evidence.
AUTHORIZED_MODEL_VIEW_PATH = "/srv/inferswarm/state/arm-c/model-view"
AUTHORIZED_LAST_STAGE_HOST = "10.0.0.219"
AUTHORIZED_LAST_STAGE_PORT = 18485
AUTHORIZED_TOKENIZER_PATH = "/srv/inferswarm/tokenizers/gemma-r6-frozen"
AUTHORIZED_INPUT_PATHS = {
    "plan": "/srv/inferswarm/state/arm-c/chain-plan.json",
    "environment": "/srv/inferswarm/state/arm-c/environment.json",
    "fixture": "/srv/inferswarm/state/arm-c-retry/prompt-fixture.json",
    "corpus": "/srv/inferswarm/state/arm-c-retry/integration-fixture.json",
    "pinned_r5b_epochs": (
        "/srv/inferswarm/state/arm-c-retry/scripts/r5b_epochs.py"),
}
AUTHORIZED_INPUT_FILE_SHA256 = {
    "plan": "6d9a4859af5b686a321458fe50c86189244b7d0d41e2cbb0df28147552f709ab",
    "fixture": "e68dfaafe661f2f6cc5f5be3a51128c7e7abf0b5c81978cbdb45e9788fd88cd0",
    "corpus": "b9c2bb7f7416b10dcee284aaf9b6c591644292550e1dced70a315c08eba120a3",
    "pinned_r5b_epochs": R5B_EPOCHS_SHA256,
}
AUTHORIZED_OUTPUT_ROOT = "/srv/inferswarm/state/arm-c-retry/attempts"
TOKENIZER_ASSET_PINS = {
    "chat_template.jinja": (
        "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4"),
    "config.json": (
        "478c46e8d2c52d5c2d85bf67e3b3e8c90e7c9d91086cee27e3c267907e936bd9"),
    "generation_config.json": (
        "a8349d9bd64cc5841297fcb5002f0fdc4749c473c8f1b10ea337f9ce4ee7014e"),
    "tokenizer.json": (
        "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"),
    "tokenizer_config.json": (
        "a62f4e85a47c0c136edaaa3a4f591fd6783717299a9def47e5ad03a49f6a5eb9"),
}
TOKENIZER_SOFTWARE_IDENTITY = {
    "transformers": "5.17.0",
    "tokenizers": "0.23.2",
    "Jinja2": "3.1.6",
    "MarkupSafe": "3.0.3",
}
TOKENIZER_PYTHON = "3.12"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


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
            f"ARM_C_RETRY_DIRECT_FAIL: expected one legal shape. got "
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


def verify_environment_authorization(environment: dict) -> None:
    """Bind the environment to its Phase-A canonical identity.

    Issue #129 derived this identity from retained accepted physical-preflight
    evidence. The direct driver compares the canonical bytes to that frozen
    identity. It does not import another Python module to decide the expected
    environment at run time.
    """
    actual = sha256_bytes(canonical_bytes(environment))
    if actual != AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256:
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: --environment is not the accepted "
            "Arm-C environment freeze (canonical sha256 "
            f"{actual} != {AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256}); "
            "substituted environment inputs are rejected before realization")


def verify_realization_input_authorization(args: argparse.Namespace) -> None:
    """Reject every mutable realization input before realization."""
    observed = {
        "view-dir": args.view_dir,
        "last-stage-host": args.last_stage_host,
        "last-stage-port": args.last_stage_port,
        "tokenizer": args.tokenizer,
    }
    expected = {
        "view-dir": AUTHORIZED_MODEL_VIEW_PATH,
        "last-stage-host": AUTHORIZED_LAST_STAGE_HOST,
        "last-stage-port": AUTHORIZED_LAST_STAGE_PORT,
        "tokenizer": AUTHORIZED_TOKENIZER_PATH,
    }
    for name in expected:
        if observed[name] != expected[name]:
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: --{name} {observed[name]!r} is "
                f"not the authorized value {expected[name]!r}; rejected "
                "before realization")
    for name, authorized_path in AUTHORIZED_INPUT_PATHS.items():
        supplied = getattr(args, name)
        if supplied != authorized_path:
            option = name.replace("_", "-")
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: --{option} {supplied!r} is not "
                f"the authorized deployment path {authorized_path!r}; "
                "rejected before realization")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.attempt_id):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: --attempt-id has an unauthorized shape")
    expected_out = str(
        Path(AUTHORIZED_OUTPUT_ROOT) / args.attempt_id / "direct")
    if args.out_dir != expected_out:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: --out-dir {args.out_dir!r} is not "
            f"the attempt-bound path {expected_out!r}; rejected before "
            "realization")


def verify_pinned_file(path: str, expected_sha256: str, label: str) -> bytes:
    """Load one separately deployed input by exact byte identity."""
    raw = Path(path).read_bytes()
    actual = sha256_bytes(raw)
    if actual != expected_sha256:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: {label} sha256 drift: {actual} != "
            f"{expected_sha256}")
    return raw


def verify_tokenizer_authorization(path: str) -> None:
    """Verify the fixed tokenizer directory, exact assets, and software."""
    asset_dir = Path(path)
    try:
        entries = {entry.name: entry for entry in asset_dir.iterdir()}
    except OSError as error:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: cannot inspect tokenizer directory: "
            f"{error}") from error
    if set(entries) != set(TOKENIZER_ASSET_PINS):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: tokenizer directory is not exhaustive; "
            f"entries={sorted(entries)}")
    for name, expected in TOKENIZER_ASSET_PINS.items():
        entry = entries[name]
        if entry.is_symlink() or not entry.is_file():
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: tokenizer asset {name} is not an "
                "immutable regular-file deployment")
        verify_pinned_file(str(entry), expected, f"tokenizer asset {name}")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if python_version != TOKENIZER_PYTHON:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: tokenizer Python {python_version} != "
            f"{TOKENIZER_PYTHON}")
    for package, expected in TOKENIZER_SOFTWARE_IDENTITY.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as error:
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: tokenizer package {package} is "
                "not installed") from error
        if actual != expected:
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: tokenizer package {package} "
                f"version {actual} != {expected}")


def verify_chain_plan_authorization(chain_plan: dict) -> None:
    """Bind the chain-plan/participant input to the accepted Arm-B evidence:

    - the chain plan's digest must be SELF-CONSISTENT (recomputed from
      the canonical bytes over the document minus `digest`) AND equal the
      accepted Arm-C chain-plan digest sha256:a71a3129… (the re-freeze of
      the accepted Arm-B participant plan under the frozen producer,
      retained byte-exact in accepted evidence) — so ANY content
      mutation (geometry, blocks, shared state, capacity) fails closed;
    - the chain plan's provenance must carry the ACCEPTED participant
      identity sha256:ee845188… as `accepted_plan_digest` — the exact
      relationship retained accepted evidence establishes between the
      supplied chain plan and the accepted Arm-B participant plan
      (plan-verification.json: arm_c_plan_digest == a71a3129… derived
      from accepted_plan_digest == ee845188…);
    - the producer binding must be the frozen producer 924cd22e….

    Any substituted chain plan/participant materialization fails closed
    BEFORE realization."""
    digest = chain_plan.get("digest")
    body = {k: v for k, v in chain_plan.items() if k != "digest"}
    recomputed = "sha256:" + sha256_bytes(
        (json.dumps(body, sort_keys=True,
                    separators=(",", ":")) + "\n").encode())
    if digest != recomputed:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: chain plan digest {digest} is not "
            f"self-consistent (recomputed {recomputed}); mutated plan "
            "content is rejected before realization")
    provenance = chain_plan.get("provenance", {})
    arm_c = provenance.get("issue117_arm_c", {})
    accepted_plan_digest = arm_c.get("accepted_plan_digest")
    if accepted_plan_digest != AUTHORIZED_PARTICIPANT_IDENTITY:
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: chain plan does not derive from the "
            f"accepted Arm-B participant identity {AUTHORIZED_PARTICIPANT_IDENTITY} "
            f"(provenance accepted_plan_digest={accepted_plan_digest!r}); "
            "the supplied plan/materialization is not the accepted "
            "participant state")
    if digest != AUTHORIZED_CHAIN_PLAN_DIGEST:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: chain plan digest {digest} is not "
            f"the authorized Arm-C chain plan {AUTHORIZED_CHAIN_PLAN_DIGEST} "
            "(the accepted re-freeze of the accepted Arm-B participant "
            "plan); substituted plan inputs are rejected before "
            "realization")
    producer_sha = provenance.get("r6", {}).get("producer_sha")
    if producer_sha != FREETOKEN_PRODUCER:
        raise SystemExit(
            f"ARM_C_RETRY_DIRECT_FAIL: chain plan producer {producer_sha!r} "
            f"is not the frozen producer {FREETOKEN_PRODUCER}")


def verify_plan_authorization_fence(built_plan: dict) -> None:
    """THE authorization fence: the locally built execution plan must
    equal the issue #133 authorized Arm-B execution-plan digest. This is
    independent of (and prior to) the runtime-substitution fence on
    `result["plan_digest"]`: an unintended chain-plan/environment input
    producing a different locally built plan is rejected here, before
    realize_dense_chain() and before any model/runtime generation."""
    digest = built_plan.get("digest")
    if digest != AUTHORIZED_EXECUTION_PLAN_DIGEST:
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: locally built execution plan digest "
            f"{digest} != authorized issue #133 Arm-B execution-plan "
            f"digest {AUTHORIZED_EXECUTION_PLAN_DIGEST}; refusing to "
            "realize an unauthorized plan")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="FreeToken worktree root (default: inferred)")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--view-dir",
                        default=AUTHORIZED_MODEL_VIEW_PATH)
    parser.add_argument("--last-stage-host",
                        default=AUTHORIZED_LAST_STAGE_HOST)
    parser.add_argument("--last-stage-port", type=int,
                        default=AUTHORIZED_LAST_STAGE_PORT)
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
    args = parser.parse_args(argv)

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

    # Reject every caller-controlled realization and deployed-input path
    # before loading tokenizer or plan code and before physical realization.
    verify_realization_input_authorization(args)

    # The frozen allocator derivation fails closed on path or byte drift.
    pinned_raw = verify_pinned_file(
        args.pinned_r5b_epochs,
        AUTHORIZED_INPUT_FILE_SHA256["pinned_r5b_epochs"],
        "pinned r5b_epochs.py")
    pinned_source = pinned_raw.decode("utf-8")
    allocator = FrozenRuntimeSessionAllocator(pinned_source)

    fixture = json.loads(verify_pinned_file(
        args.fixture, AUTHORIZED_INPUT_FILE_SHA256["fixture"],
        "prompt fixture"))
    if fixture.get("fixture_digest") != (
            "sha256:6046d4796a5d9cc888030c6b3f07304c20ce117d93905c30"
            "00d7aae7c0ae01c7"):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: fixture digest drift against the "
            "#129 frozen rendered fixture")
    rows = sorted(fixture["cases"], key=lambda c: c["case_id"])
    if len(rows) != 24:
        raise SystemExit("ARM_C_RETRY_DIRECT_FAIL: expected 24 cases")

    corpus = json.loads(verify_pinned_file(
        args.corpus, AUTHORIZED_INPUT_FILE_SHA256["corpus"],
        "integration fixture"))
    if corpus.get("fixture_digest") != (
            "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a"
            "64f4508b2ba36f2"):
        raise SystemExit(
            "ARM_C_RETRY_DIRECT_FAIL: corpus digest drift against the "
            "accepted integration fixture")
    prompt_texts = {
        row["case"]["case_id"]: row["case"]["prompt_text"]
        for row in corpus["cases"]}

    # Verify and load the exact non-Source tokenizer deployment. No network
    # acquisition or remote-code path is available.
    verify_tokenizer_authorization(args.tokenizer)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(
        args.tokenizer, trust_remote_code=False, local_files_only=True)
    for row in rows:
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": prompt_texts[row["case_id"]]}],
            tokenize=False, add_generation_prompt=True)
        rendered = tok.encode(prompt, add_special_tokens=False)
        if rendered != row["rendered_prompt_token_ids"]:
            raise SystemExit(
                f"ARM_C_RETRY_DIRECT_FAIL: real-tokenizer render mismatch "
                f"for {row['case_id']}")

    chain_plan = json.loads(verify_pinned_file(
        args.plan, AUTHORIZED_INPUT_FILE_SHA256["plan"], "chain plan"))
    environment = json.loads(Path(args.environment).read_text())

    # ---- AUTHORIZATION FENCE: bind external plan/substrate inputs and ---
    # ---- require the built plan to equal the authorized digest, all  ---
    # ---- BEFORE realize_dense_chain()/any model execution.             ---
    verify_chain_plan_authorization(chain_plan)
    verify_environment_authorization(environment)
    execution_plan = build_execution_plan(environment, chain_plan)
    verify_plan_authorization_fence(execution_plan)

    from benchmarks.inferswarm_r6.chain_runtime import realize_dense_chain
    started_ns = time.time_ns()
    runtime = realize_dense_chain(
        dict(execution_plan),
        chain_plan_path=args.plan,
        model_path=AUTHORIZED_MODEL_VIEW_PATH,
        last_stage_host=AUTHORIZED_LAST_STAGE_HOST,
        last_stage_port=AUTHORIZED_LAST_STAGE_PORT,
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
