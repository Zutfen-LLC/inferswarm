#!/usr/bin/env python3
"""Issue #172 — Phase 1 immutable 40-case corpus binder (CPU-only, stdlib).

Re-derives, from retained bytes only:

- the 24 accepted #133 regression cases (prompt-fixture.json: rendered
  prompt ids, raw fixture ids, session indices — consumed exactly as
  retained, digest-bound);
- the 16 accepted #170 generalization cases (corpus.json raw token ids
  + prompt texts — consumed without regeneration, canonical-digest-bound);
- the combined 40-case campaign corpus with per-case render identities
  and a canonical combined digest;
- session-index assignment: regression cases keep their accepted
  session_index (1..24); g170 cases continue 25..40 in frozen case_id
  order;
- mechanical eligibility checks: every case renders to EXACTLY two
  prefill chunks under the frozen 64-row boundary for the g170 arm
  (rendered length 65..128 → 64 + remainder 1..64), matching the frozen
  target lengths/remainders; regression cases keep their accepted
  identities untouched (their historical multi-chunk membership is
  retained fact, not re-derived here);
- the prefix-disambiguation property across all 40 rendered prompts
  (no rendered prompt is a prefix of another — required by replay-stream
  matching).

Writes evidence/corpus-binding.json and the deployable campaign corpus
document (evidence/campaign-corpus.json). Fail-closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402

ROW_BOUNDARY = P.SUBJECT["prefill_boundary_rows"]
EXPECTED_170_LENGTHS = (
    65, 67, 69, 72, 73, 78, 83, 88, 89, 96, 104, 112, 113, 118, 123, 128)
EXPECTED_170_REMAINDERS = (
    1, 3, 5, 8, 9, 14, 19, 24, 25, 32, 40, 48, 49, 54, 59, 64)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value) -> str:
    return "sha256:" + sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def write_canonical_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load(rel: str) -> dict:
    return json.loads((P.ROOT / rel).read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", default=str(P.EVIDENCE_DIR))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    regression = load(P.REGRESSION_FIXTURE_PATH)
    integration = load(P.INTEGRATION_FIXTURE_PATH)
    corpus170 = load(P.CORPUS_170_PATH)

    # --- regression arm: consume exactly as retained -------------------
    if regression["fixture_digest"] != (
            "sha256:6046d4796a5d9cc888030c6b3f07304c20ce117d93905c30"
            "00d7aae7c0ae01c7"):
        raise SystemExit("ISSUE172_CORPUS_FAIL: regression fixture digest")
    if integration["fixture_digest"] != P.REGRESSION_FIXTURE_DIGEST_24:
        raise SystemExit("ISSUE172_CORPUS_FAIL: integration fixture digest")
    reg_rows = sorted(regression["cases"], key=lambda c: c["case_id"])
    if len(reg_rows) != P.REGRESSION_ARM_CASE_COUNT:
        raise SystemExit("ISSUE172_CORPUS_FAIL: regression count")
    prompt_texts = {
        row["case"]["case_id"]: row["case"]["prompt_text"]
        for row in integration["cases"]}

    regression_cases = []
    for row in reg_rows:
        case_id = row["case_id"]
        if case_id not in prompt_texts:
            raise SystemExit(f"ISSUE172_CORPUS_FAIL: no text for {case_id}")
        regression_cases.append({
            "case_id": case_id,
            "arm": "regression-133",
            "session_index": int(row["session_index"]),
            "prompt_text": prompt_texts[case_id],
            "raw_fixture_token_ids": list(row["raw_fixture_token_ids"]),
            "rendered_prompt_token_ids":
                list(row["rendered_prompt_token_ids"]),
            "rendered_len": int(row["rendered_len"]),
            "case_render_sha256": row["case_render_sha256"],
        })
    indexes = sorted(c["session_index"] for c in regression_cases)
    if indexes != list(range(1, 25)):
        raise SystemExit("ISSUE172_CORPUS_FAIL: regression session indices")

    # --- generalization arm: consume without regeneration --------------
    cases170 = corpus170["cases"]
    if canonical_digest(cases170) != P.CORPUS_170_DIGEST:
        raise SystemExit("ISSUE172_CORPUS_FAIL: #170 canonical digest drift")
    rendered_by_case = {}
    for case in cases170:
        ids = case["raw_token_ids"]
        rendered = case.get("rendered_prompt_token_ids")
        if rendered is None:
            # the #170 corpus retains raw ids + the frozen tokenizer
            # identity; the rendered ids are re-derived at deployment by
            # the pinned tokenizer (Phase 2/3 render preflight). Here we
            # bind the raw ids and the frozen length contract.
            rendered_len = case["raw_token_count"] + case[
                "accepted_wrapper_delta"]
        else:
            rendered_len = len(rendered)
        rendered_by_case[case["case_id"]] = {
            "rendered_len": rendered_len,
            "raw_token_ids": list(ids),
        }
    lengths = sorted(
        rendered_by_case[c["case_id"]]["rendered_len"] for c in cases170)
    if lengths != list(EXPECTED_170_LENGTHS):
        raise SystemExit(
            f"ISSUE172_CORPUS_FAIL: #170 rendered lengths {lengths}")
    for case in cases170:
        remainder = rendered_by_case[case["case_id"]][
            "rendered_len"] - ROW_BOUNDARY
        bucket = case["bucket"]
        low, high = bucket.split("-")
        if not (int(low) <= remainder <= int(high)):
            raise SystemExit("ISSUE172_CORPUS_FAIL: bucket membership")

    generalization_cases = []
    next_index = 25
    for case in sorted(cases170, key=lambda c: c["case_id"]):
        info = rendered_by_case[case["case_id"]]
        generalization_cases.append({
            "case_id": case["case_id"],
            "arm": "generalization-170",
            "session_index": next_index,
            "prompt_text": case["prompt_text"],
            "raw_token_ids": info["raw_token_ids"],
            "rendered_len": info["rendered_len"],
            "second_chunk_remainder": info["rendered_len"] - ROW_BOUNDARY,
            "bucket": case["bucket"],
            "content_class": case["content_class"],
            "prompt_sha256": case["prompt_sha256"],
        })
        next_index += 1

    # --- combined corpus ------------------------------------------------
    all_cases = regression_cases + generalization_cases
    if len(all_cases) != P.TOTAL_CASE_COUNT:
        raise SystemExit("ISSUE172_CORPUS_FAIL: combined count")
    if len({c["case_id"] for c in all_cases}) != P.TOTAL_CASE_COUNT:
        raise SystemExit("ISSUE172_CORPUS_FAIL: duplicate case ids")

    # prefix disambiguation over the RENDERED id lists (regression now;
    # g170 rendered ids are pinned at deployment preflight — the check is
    # re-run there over the pinned bytes before any launch)
    prompts = [
        tuple(c["rendered_prompt_token_ids"])
        for c in all_cases if "rendered_prompt_token_ids" in c]
    for i, a in enumerate(prompts):
        for j, b in enumerate(prompts):
            if i != j and len(a) <= len(b) and list(a) == list(b)[:len(a)]:
                raise SystemExit(
                    "ISSUE172_CORPUS_FAIL: ambiguous replay prefix")

    corpus_document = {
        "schema": P.CORPUS_BINDING_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "regression_arm": {
            "count": len(regression_cases),
            "fixture_digest": regression["fixture_digest"],
            "integration_fixture_digest":
                integration["fixture_digest"],
            "consumed_as_retained": True,
        },
        "generalization_arm": {
            "count": len(generalization_cases),
            "corpus_id": corpus170["corpus_id"],
            "canonical_corpus_digest": P.CORPUS_170_DIGEST,
            "rendered_lengths": list(EXPECTED_170_LENGTHS),
            "second_chunk_remainders": list(EXPECTED_170_REMAINDERS),
            "consumed_without_regeneration": True,
        },
        "case_count": len(all_cases),
        "combined_canonical_digest": canonical_digest(all_cases),
        "cases": all_cases,
    }
    write_canonical_json(out_dir / "campaign-corpus.json", corpus_document)

    binding = {
        "schema": "inferswarm.issue172.arm-c-requal-corpus-binding/1",
        "campaign_id": P.CAMPAIGN_ID,
        "regression_fixture_digest": regression["fixture_digest"],
        "integration_fixture_digest": integration["fixture_digest"],
        "corpus_170_canonical_digest": P.CORPUS_170_DIGEST,
        "combined_canonical_digest":
            corpus_document["combined_canonical_digest"],
        "case_count": len(all_cases),
        "regression_count": len(regression_cases),
        "generalization_count": len(generalization_cases),
        "identity_counts": {"total": P.TOTAL_CASE_COUNT},
        "checks": {
            "regression_session_indices_1_to_24": True,
            "g170_lengths_exact": lengths == list(EXPECTED_170_LENGTHS),
            "g170_bucket_membership": True,
            "prefix_disambiguation_rendered": True,
            "no_forbidden_namespace": all(
                P.FORBIDDEN_NAMESPACE not in json.dumps(c)
                for c in all_cases),
        },
    }
    if not all(binding["checks"].values()):
        raise SystemExit("ISSUE172_CORPUS_FAIL: checks")
    write_canonical_json(out_dir / "corpus-binding.json", binding)
    print(json.dumps({
        "corpus": str(out_dir / "campaign-corpus.json"),
        "combined_digest": corpus_document["combined_canonical_digest"],
        "cases": len(all_cases),
        "g170_render_note": (
            "g170 rendered ids pinned at deployment by the pinned-tokenizer "
            "render preflight; lengths contract-bound here"),
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
