#!/usr/bin/env python3
"""Issue #172 — Phase 2 CPU transcript preflight (recording runtime).

Proves, before any physical output, exact model-execution transcript
equivalence between direct and ordinary invocations for ALL 40 campaign
cases (24 accepted #133 regression + 16 accepted #170 generalization),
reusing the accepted #129 recording-runtime machinery unchanged:

- the ordinary arm runs the REAL EpochServingController.serve_tokens
  loop (frozen producer bytes, sha256-verified) against the
  RecordingRuntime, with prompt ids derived through the frozen
  Coordinator ingress seam (chat template + encode, pinned tokenizer);
- the direct arm runs the corrected comparator loop with the frozen
  AST-extracted runtime-session allocator;
- both arms' complete generate() transcripts are compared call-by-call
  by the accepted reducer semantics (argument names, session ids,
  replay prefixes, max_new_tokens, responses, commit/discard).

g170 case rendered ids are PINNED here: each g170 prompt is rendered
under the pinned frozen tokenizer through the extracted ingress seam
and the rendered length must equal the frozen target exactly.

Fail-closed: any difference blocks launch (BLOCKED), never silently
passes. CPU-only: no GPU, no model bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import issue172_campaign_pins as P  # noqa: E402

ROOT = P.ROOT
sys.path.insert(0, str(ROOT / "scripts"))
import issue129_arm_c_retry_core as core  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_canonical_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def build_40_case_fixture(corpus_doc: dict, ingress: dict) -> dict:
    """Extend the accepted 24-case fixture semantics to 40 cases for the
    recording preflight: rendered prompt ids for all 40 (regression as
    retained; g170 pinned through the ingress seam), case-render
    digests, deterministic responses from the same seeding rule."""
    rows = []
    for case in corpus_doc["cases"]:
        if case["arm"] == "regression-133":
            rendered = case["rendered_prompt_token_ids"]
        else:
            rendered = ingress["derived_ids"][case["case_id"]]
            if len(rendered) != case["rendered_len"]:
                raise SystemExit(
                    f"ISSUE172_PREFLIGHT_FAIL: {case['case_id']} rendered "
                    f"length {len(rendered)} != frozen target "
                    f"{case['rendered_len']}")
        body = {
            "case_id": case["case_id"],
            "session_index": case["session_index"],
            "rendered_prompt_token_ids": list(rendered),
            "raw_fixture_token_ids": list(case.get(
                "raw_fixture_token_ids", case.get("raw_token_ids", []))),
            "rendered_len": len(rendered),
        }
        rows.append({
            **body,
            "case_render_sha256": "sha256:" + sha256_bytes(
                json.dumps(body, sort_keys=True).encode()),
        })
    rows.sort(key=lambda r: (r["session_index"], r["case_id"]))
    prompts = [tuple(r["rendered_prompt_token_ids"]) for r in rows]
    for i, a in enumerate(prompts):
        for j, b in enumerate(prompts):
            if i != j and len(a) <= len(b) and list(a) == list(b)[:len(a)]:
                raise SystemExit(
                    "ISSUE172_PREFLIGHT_FAIL: ambiguous replay prefix "
                    f"{rows[i]['case_id']}/{rows[j]['case_id']}")
    return {
        "schema": "inferswarm.issue129.prompt-fixture/1",
        "case_count": len(rows),
        "cases": rows,
        "fixture_digest": "sha256:" + sha256_bytes(json.dumps(
            [{k: v for k, v in r.items() if k != "case_render_sha256"}
             for r in rows], sort_keys=True).encode()),
    }


def render_g170_through_ingress(corpus_doc: dict) -> dict:
    """Pin the g170 rendered ids through the frozen Coordinator ingress
    seam with the real pinned tokenizer (the exact ordinary path)."""
    extracted = core.extract_coordinator_ingress(ROOT)
    core.verify_retained_tokenizer_assets(ROOT)
    core.verify_tokenizer_software_identity(ROOT)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        str(core.TOKENIZER_ASSET_DIR), local_files_only=True,
        trust_remote_code=False)
    ingress = extracted["seam_class"](tokenizer)
    derived = {}
    lengths = {}
    for case in corpus_doc["cases"]:
        if case["arm"] != "generalization-170":
            continue
        body = {
            "messages": [{"role": "user", "content": case["prompt_text"]}],
            "model": "gemma-4-12B-it",
            "temperature": 0.0,
            "max_tokens": 8,
        }
        ids = list(ingress._render_and_tokenize(body))
        derived[case["case_id"]] = ids
        lengths[case["case_id"]] = len(ids)
    return {"derived_ids": derived, "lengths": lengths}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus",
                        default=str(P.EVIDENCE_DIR / "campaign-corpus.json"))
    parser.add_argument("--out",
                        default=str(P.EVIDENCE_DIR / "cpu-transcript-preflight.json"))
    args = parser.parse_args()

    corpus_doc = json.loads(Path(args.corpus).read_text())
    started = time.time()

    # frozen-byte verification of the whole accepted control plane
    frozen_digests = core.verify_frozen_bytes(ROOT)

    # pin g170 rendered ids through the frozen ingress + pinned tokenizer
    ingress = render_g170_through_ingress(corpus_doc)
    fixture40 = build_40_case_fixture(corpus_doc, ingress)

    planner, serving, epochs, _strategy, xc_strategy = \
        core.load_frozen_control_plane(ROOT)

    # --- direct arm (corrected comparator loop, recording runtime) -----
    transcript: list[dict] = []
    direct_runtime = core.RecordingRuntime(
        core.deterministic_case_responses(fixture40), transcript, arm="direct")
    direct_runtime._reject_unknown_stream = True
    core._bind_runtime(direct_runtime, fixture40)
    allocator = core.extract_runtime_session_allocator(ROOT)
    from issue172_direct_loop import run_direct_loop  # local module
    direct_cases = run_direct_loop(
        allocator=allocator, runtime=direct_runtime, fixture=fixture40)

    # --- ordinary arm (real serve_tokens, recording runtime) -----------
    ordinary_transcript: list[dict] = []
    ordinary_runtime = core.RecordingRuntime(
        core.deterministic_case_responses(fixture40), ordinary_transcript,
        arm="ordinary")
    core._bind_runtime(ordinary_runtime, fixture40)
    from issue172_ordinary_loop import run_ordinary_loop  # local module
    ordinary_cases = run_ordinary_loop(
        planner=planner, serving=serving, epochs=epochs,
        xc_strategy=xc_strategy, runtime=ordinary_runtime,
        fixture=fixture40, repo_root=ROOT)

    # --- reduction (accepted reducer semantics over 40 cases) ----------
    direct_arm_doc = {
        "arm": "direct", "variant": "corrected",
        "generate_argument_names": sorted(P.GENERATE_ARGUMENT_NAMES),
        "sampling_inputs": dict(P.SAMPLING_INPUTS),
        "stopping_policy": dict(P.STOPPING_POLICY),
        "per_case": direct_cases,
    }
    ordinary_arm_doc = {
        "arm": "ordinary", "variant": "ingress-derived",
        "generate_argument_names": sorted(P.GENERATE_ARGUMENT_NAMES),
        "sampling_inputs": dict(P.SAMPLING_INPUTS),
        "stopping_policy": dict(P.STOPPING_POLICY),
        "per_case": ordinary_cases,
        "selection_authorization": ordinary_cases.get(
            "__selection_authorization__"),
    }
    ordinary_cases.pop("__selection_authorization__", None)
    reduction = core.reduce_transcripts(ordinary_arm_doc, direct_arm_doc)

    equal_count = sum(
        1 for row in reduction.get("rows", [])
        if row.get("equal") and not row.get("problems"))
    # the accepted reducer bakes the #129 24-case count into its own
    # `passed`; this campaign requires 40 — re-derive over the rows and
    # require zero global problems from the reducer itself.
    passed = (equal_count == P.TOTAL_CASE_COUNT
              and not reduction.get("global_problems")
              and len(reduction.get("rows", [])) == P.TOTAL_CASE_COUNT)

    record = {
        "schema": "inferswarm.issue172.arm-c-requal.cpu-transcript-preflight/1",
        "campaign_id": P.CAMPAIGN_ID,
        "case_count": P.TOTAL_CASE_COUNT,
        "regression_count": P.REGRESSION_ARM_CASE_COUNT,
        "generalization_count": P.GENERALIZATION_ARM_CASE_COUNT,
        "fixture40_digest": fixture40["fixture_digest"],
        "g170_rendered_lengths": ingress["lengths"],
        "frozen_control_plane_digests": frozen_digests,
        "runtime_session_allocation": allocator.facts,
        "per_case_equal_count": equal_count,
        "reduction_passed": bool(reduction.get("passed")),
        "global_problems": reduction.get("global_problems", []),
        "cpu_only": {
            "gpu_execution_occurred": False,
            "model_execution_occurred": False,
            "recording_fake_runtime": True,
        },
        "terminal": "PREFLIGHT_PASS" if passed else "PREFLIGHT_BLOCKED",
        "built_at_unix": int(started),
    }
    write_canonical_json(Path(args.out), record)
    # retain the full transcripts for the evidence bundle
    write_canonical_json(
        Path(args.out).with_name("cpu-transcript-preflight-transcripts.json"),
        {"direct": transcript, "ordinary": ordinary_transcript,
         "reduction_rows": reduction.get("rows", [])})
    print(json.dumps({
        "out": args.out,
        "equal": f"{equal_count}/{P.TOTAL_CASE_COUNT}",
        "terminal": record["terminal"],
        "problems": record["global_problems"][:5],
    }, indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
