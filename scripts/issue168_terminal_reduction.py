#!/usr/bin/env python3
"""Issue #168 — Arm-C post-SWA requalification BLOCKED-terminal reducer.

Pure stdlib, CPU-only, fail-closed. Re-derives the terminal
classification from retained bytes only (corpus-census.json +
authority-record.json + the accepted fixture/corpus bytes), never from
authored `pass`/`equal`/terminal fields inside those records.

Classification logic (exactly the issue #168 Phase 1B rule):

- for EVERY eligibility reading recorded in the census, re-derive the
  per-bucket eligible counts from the census's own per-case rendered
  lengths (the census retains all 1416), recompute bucket membership,
  and require the recomputed counts to equal the recorded counts;
- if ANY reading shows any of the four mandated remainder buckets with
  fewer than four eligible public cases, and no physical execution was
  performed, the terminal is
  ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED (corpus insufficiency,
  pre-observation);
- the reducer fails closed on structural drift (schemas, fixture
  binding, missing members, count mismatch, any hint of physical
  execution or h109 access in the records).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: accepted digest of the 24-case #133 Arm-C regression fixture
#: (issue #168 Phase 1A) — consumed from the accepted #133 authority
#: module (import-don't-restate; cross-pinned by the record tests)
from issue129_arm_c_retry_core import FIXTURE_DIGEST_24  # noqa: E402

ACCEPTED_FIXTURE_DIGEST = FIXTURE_DIGEST_24
BUCKETS = (("1-8", 1, 8), ("9-24", 9, 24), ("25-48", 25, 48),
           ("49-64", 49, 64))
REQUIRED_PER_BUCKET = 4
CENSUS_SCHEMA = "inferswarm.issue168.arm-c-requal-corpus-census/1"
AUTHORITY_SCHEMA = "inferswarm.issue168.arm-c-requal-authority/1"
BLOCKED_TERMINAL = "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED"
EVIDENCE_DIR = ROOT / (
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence")
CENSUS_SALT = "issue168-arm-c-post-swa-requal-v1"


def bucket_of(remainder: int) -> str | None:
    for name, low, high in BUCKETS:
        if low <= remainder <= high:
            return name
    return None


def reduce_terminal(evidence_dir: Path = EVIDENCE_DIR) -> dict:
    census = json.loads((evidence_dir / "corpus-census.json").read_text())
    authority = json.loads(
        (evidence_dir / "authority-record.json").read_text())

    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    require(census["schema"] == CENSUS_SCHEMA,
            "census schema drift")
    require(authority["schema"] == AUTHORITY_SCHEMA,
            "authority schema drift")
    require(census["regression_fixture"]["accepted_fixture_digest"]
            == ACCEPTED_FIXTURE_DIGEST, "regression fixture digest drift")
    require(census["regression_fixture"]["renders_reproduced"] == 24,
            "regression fixture not reproduced under frozen tokenizer")
    require(not authority["preflight_state"]["physical_execution_performed"],
            "authority record claims physical execution")
    require(not authority["preflight_state"]["outputs_inspected"],
            "authority record claims output inspection")
    require(not authority["preflight_state"]["h109_material_accessed"],
            "authority record claims h109 access")

    # corpus file pin
    corpus_path = ROOT / census["corpus"]["file"]
    corpus_sha = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    require(census["corpus"]["file_sha256"] == "sha256:" + corpus_sha,
            "corpus file sha drift")

    # re-derive counts from per-case rendered lengths
    per_case = census["per_case_rendered_lengths"]
    require(len(per_case) == census["corpus"]["case_count"] == 1416,
            "corpus case-count drift")
    fixture_ids = set(census["regression_fixture"]["case_ids"])
    require(len(fixture_ids) == 24, "regression fixture case-count drift")
    # per-case fixture flags must agree with the recorded fixture ids
    # (an inconsistent flag would silently shift the eligible pool)
    flagged = {row["case_id"] for row in per_case
               if row["in_regression_fixture"]}
    require(flagged == fixture_ids,
            "per-case in_regression_fixture flags disagree with the "
            "recorded regression fixture case ids")

    readings = census["eligibility_readings"]
    require(set(readings) == {
        "prompt_two_chunk", "final_replay_crossing"},
        "eligibility readings changed")
    reading_lengths = {
        "prompt_two_chunk": lambda r: r["rendered_len"],
        "final_replay_crossing": lambda r: r["rendered_len"] + 7,
    }
    all_sufficient = True
    insufficient_detail = {}
    for name, reading in readings.items():
        length_of = reading_lengths[name]
        recomputed = {b: 0 for b, _, _ in BUCKETS}
        for row in per_case:
            if row["case_id"] in fixture_ids:
                continue
            length = length_of(row)
            if 65 <= length <= 128:
                bucket = bucket_of(length - 64)
                if bucket is not None:
                    recomputed[bucket] += 1
        require(recomputed == reading["eligible_counts"],
                f"{name}: recorded counts do not match recomputation")
        # member-level re-derivation: every recorded member must be
        # individually eligible with the right bucket/remainder
        members_by_bucket = {
            b: [m for m in reading["members"][b]] for b, _, _ in BUCKETS}
        recorded_total = sum(
            len(v) for v in members_by_bucket.values())
        require(recorded_total == sum(recomputed.values()),
                f"{name}: member rows do not match eligible counts")
        for b, members in members_by_bucket.items():
            for m in members:
                require(m["second_chunk_remainder"] == m["effective_len"] - 64,
                        f"{name}/{b}/{m['case_id']}: remainder arithmetic")
                require(bucket_of(m["second_chunk_remainder"]) == b,
                        f"{name}/{b}/{m['case_id']}: bucket membership")
                require(65 <= m["effective_len"] <= 128,
                        f"{name}/{b}/{m['case_id']}: length window")
                # recompute the canonical selection key from member
                # bytes (salt + case id + rendered ids) so a forged or
                # drifted key cannot ride along unverified
                expected_key = hashlib.sha256(json.dumps({
                    "salt": CENSUS_SALT,
                    "case_id": m["case_id"],
                    "rendered_prompt_token_ids":
                        m["rendered_prompt_token_ids"],
                }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                require(m["selection_key_sha256"] == expected_key,
                        f"{name}/{b}/{m['case_id']}: selection key does "
                        "not recompute from member bytes")
                require(m["rendered_len"] == len(
                    m["rendered_prompt_token_ids"]),
                    f"{name}/{b}/{m['case_id']}: rendered_len vs ids")
                require(m["effective_len"] == length_of(m),
                        f"{name}/{b}/{m['case_id']}: effective_len vs "
                        "reading definition")
        insufficient = sorted(
            b for b, _, _ in BUCKETS if recomputed[b] < REQUIRED_PER_BUCKET)
        require(insufficient == reading["insufficient_buckets"],
                f"{name}: insufficient-bucket list drift")
        if insufficient:
            all_sufficient = False
        insufficient_detail[name] = {
            "recomputed_counts": recomputed,
            "insufficient_buckets": insufficient,
        }

    # binding between census and authority record
    require(authority["fresh_corpus_census"]["insufficient_buckets"]
            == {name: r["insufficient_buckets"]
                for name, r in readings.items()},
            "authority/census insufficient-bucket drift")

    if failures:
        return {
            "schema": "inferswarm.issue168.arm-c-requal-terminal/1",
            "verdict": "REDUCTION_FAILED",
            "failures": failures,
        }

    if all_sufficient:
        # corpus sufficient — this reducer does not authorize execution;
        # the campaign would proceed under the issue's phase machinery
        return {
            "schema": "inferswarm.issue168.arm-c-requal-terminal/1",
            "verdict": "CORPUS_SUFFICIENT_CAMPAIGN_UNEXECUTED",
            "detail": insufficient_detail,
        }

    return {
        "schema": "inferswarm.issue168.arm-c-requal-terminal/1",
        "verdict": BLOCKED_TERMINAL,
        "classification_basis": "corpus_insufficiency_pre_observation",
        "detail": insufficient_detail,
        "required_per_bucket": REQUIRED_PER_BUCKET,
        "mandate": (
            "issue #168 Phase 1B: do not adapt the bucket or inspect "
            "outputs; report the corpus insufficiency for maintainer "
            "correction"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--write", action="store_true",
                        help="write terminal-reduction.json")
    args = parser.parse_args(argv)
    result = reduce_terminal(args.evidence_dir)
    text = json.dumps(result, sort_keys=True, indent=1) + "\n"
    if args.write:
        (args.evidence_dir / "terminal-reduction.json").write_text(text)
        print(f"wrote {args.evidence_dir / 'terminal-reduction.json'}")
    print(json.dumps({k: result[k] for k in
                      ("schema", "verdict")
                      if k in result}, indent=1))
    if "detail" in result:
        print(json.dumps(result["detail"], indent=1))
    return 0 if result["verdict"] not in ("REDUCTION_FAILED",) else 1


if __name__ == "__main__":
    sys.exit(main())
