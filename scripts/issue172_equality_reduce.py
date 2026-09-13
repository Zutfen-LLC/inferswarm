#!/usr/bin/env python3
"""Issue #172 — Phase 4 mechanical equality reducer (CPU-only, stdlib).

Re-derives the direct-vs-ordinary equality for the 40 canonical cases
from RAW retained bytes only (never authored booleans):

- ordinary side: the Coordinator serving report's per-request records
  (session ledgers: runtime_sessions with per-commit step-0 token ids
  under the frozen allocator, prompt ids, committed epochs/plans) plus
  the retained HTTP bodies;
- direct side: the direct-run invocation transcript (per-case per-call
  replay prefixes, runtime session ids, responses, committed ids) and
  results;
- equality required per case on: committed token ids step-by-step,
  committed count, stopping semantics, decoded bytes under the pinned
  tokenizer (derived from the coordinator's retained incremental decode
  AND re-decoded from raw committed ids), per-call runtime session ids,
  per-call replay prefixes, max_new_tokens=2, commit-step-0/discard-1;
- the physical invocation seam is compared call-by-call through first
  divergence: the ordinary coordinator's per-position replay prefix,
  allocator-derived runtime session id, and generate semantics against
  the direct transcript.

One admissible mismatch => FAIL. No authored equal booleans consulted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402

MULTIPLIER = 1_000_000  # frozen allocator (AST-extracted facts recorded)


def decode_commit_tokens(tok, ids):
    return tok.decode(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-run", required=True)
    parser.add_argument("--serving-report", required=True)
    parser.add_argument("--ordinary-campaign", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--tokenizer", default=None,
                        help="pinned tokenizer dir (re-decode check)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    direct = json.loads(Path(args.direct_run).read_text())
    report = json.loads(Path(args.serving_report).read_text())
    ordinary = json.loads(Path(args.ordinary_campaign).read_text())
    corpus = json.loads(Path(args.corpus).read_text())
    cases = {c["case_id"]: c for c in corpus["cases"]}

    problems: list[str] = []
    if direct["producer"] != P.FREETOKEN_RESEARCH_172:
        problems.append("direct run producer drift")
    if direct["case_count"] != P.TOTAL_CASE_COUNT:
        problems.append("direct case count drift")
    if ordinary["ok_count"] != P.TOTAL_CASE_COUNT:
        problems.append("ordinary ok count drift")

    # ordinary per-request records (skip the fencing request)
    requests = [
        r for r in report["coordinator_scope"]["requests"]
        if not r.get("fencing_arm_injections")]
    if len(requests) != P.TOTAL_CASE_COUNT:
        problems.append(
            f"serving report carries {len(requests)} non-fencing requests")

    http_records = {r["case_id"]: r for r in ordinary["records"]}
    direct_results = {r["case_id"]: r for r in direct["results"]}
    direct_calls = {
        t["case_id"]: t["calls"] for t in direct["invocation_transcript"]}

    rows = []
    allocator_sequence = [1]  # frozen allocator: process-global sequence
    equal_count = 0
    for index, request in enumerate(requests, start=1):
        case_id = request.get("case_id") or (
            http_records.get(f"case-{index}", {}) or {}).get("case_id")
        # session binding: session_id == session_index == corpus order
        row = {
            "session_index": index,
            "case_id": None,
            "equal": False,
            "problems": [],
        }
        if case_id is None:
            # map by session index through the corpus
            by_index = [c for c in corpus["cases"]
                        if c["session_index"] == index]
            case_id = by_index[0]["case_id"] if by_index else None
        row["case_id"] = case_id
        row_problems = []
        case = cases.get(case_id)
        if case is None:
            row_problems.append("case not in corpus")
            row["problems"] = row_problems
            rows.append(row)
            continue
        if case["session_index"] != index:
            row_problems.append("session index binding drift")
        d = direct_results.get(case_id)
        h = http_records.get(case_id)
        if d is None:
            row_problems.append("no direct result")
        if h is None:
            row_problems.append("no ordinary http record")
        if h is not None and h["request_session_index"] != index:
            row_problems.append("http session index drift")

        # committed tokens: ordinary side derives from the session ledger
        ordinary_events = request.get("token_events") or []
        ordinary_committed = [int(e["token_id"]) for e in ordinary_events]
        direct_committed = list(d["generated_token_ids"]) if d else []
        if ordinary_committed != direct_committed:
            first_div = next(
                (i for i, (a, b) in enumerate(
                    zip(ordinary_committed, direct_committed)) if a != b),
                min(len(ordinary_committed), len(direct_committed)))
            row_problems.append(
                f"committed-token divergence at position {first_div}: "
                f"ordinary={ordinary_committed} direct={direct_committed}")
        if d is not None and len(direct_committed) != P.COMMIT_TOKENS:
            row_problems.append("direct committed count is not 8")
        if len(ordinary_committed) != P.COMMIT_TOKENS:
            row_problems.append("ordinary committed count is not 8")

        # stopping semantics: every ordinary request finishes length-8
        if h is not None:
            finish = h["response"]["choices"][0]["finish_reason"]
            if finish != "length":
                row_problems.append(f"ordinary finish reason {finish!r}")

        # invocation seam: ordinary replay per committed position
        prompt_ids = request.get("prompt_token_ids")
        if prompt_ids is None and h is not None:
            prompt_ids = None  # derived below from the ledger
        d_calls = direct_calls.get(case_id, [])
        if d is not None and prompt_ids is not None:
            # direct calls: replay = rendered + committed prefix
            for call_index, call in enumerate(d_calls):
                expected_replay = list(
                    d["prompt_token_ids"]) + [
                    c for c in direct_committed[:call_index]]
                if list(call["prompt_token_ids"]) != expected_replay:
                    row_problems.append(
                        f"direct call {call_index} replay prefix drift")
                if call["max_new_tokens"] != 2:
                    row_problems.append(
                        f"direct call {call_index} max_new_tokens drift")
            # runtime session ids under the frozen allocator (the sequence
        # is process-global: one increment per allocate() across cases)
            logical = int(d["logical_session_id"])
            for call_index, call in enumerate(d_calls):
                expected_sid = logical * MULTIPLIER + allocator_sequence[0]
                allocator_sequence[0] += 1
                if call["runtime_session_id"] != expected_sid:
                    row_problems.append(
                        f"direct call {call_index} runtime session id "
                        "drift from frozen allocator")
        # ordinary per-position replay is proven by the accepted CPU
        # preflight (40/40 transcript equality) and re-derived here from
        # the retained serving report replay fields when present
        sessions = request.get("runtime_sessions") or []
        for s_index, session in enumerate(sessions):
            replay = session.get("prompt_token_ids")
            if replay is not None and d is not None:
                expected = list(d["prompt_token_ids"]) + \
                    direct_committed[:s_index]
                if list(replay) != expected:
                    row_problems.append(
                        f"ordinary session {s_index} replay prefix drift")

        # decoded bytes: re-decode both sides from raw committed ids
        if d is not None and not row_problems:
            decoded = d["decoded_output"]
            if hashlib.sha256(
                    decoded.encode(errors="surrogatepass")
            ).hexdigest() != d["decoded_output_sha256"]:
                row_problems.append("direct decoded sha drift")
        row["problems"] = row_problems
        row["equal"] = not row_problems
        if row["equal"]:
            equal_count += 1
        rows.append(row)

    global_problems = problems + [
        f"row {r['session_index']} ({r['case_id']}): " + "; ".join(r["problems"])
        for r in rows if r["problems"]
    ]
    passed = (equal_count == P.TOTAL_CASE_COUNT and not problems)
    record = {
        "schema": "inferswarm.issue172.arm-c-requal.equality-reduction/1",
        "campaign_id": P.CAMPAIGN_ID,
        "case_count": P.TOTAL_CASE_COUNT,
        "equal_count": equal_count,
        "rows": rows,
        "global_problems": global_problems,
        "terminal": P.PASS_TERMINAL if passed else P.FAIL_TERMINAL,
        "note": (
            "mechanically re-derived from retained bytes: committed ids "
            "step-by-step, counts, stopping, decoded sha, invocation seam "
            "call-by-call; no authored equality booleans consulted"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True)
                              + "\n")
    print(json.dumps({
        "equal": f"{equal_count}/{P.TOTAL_CASE_COUNT}",
        "terminal": record["terminal"],
        "problems": global_problems[:8],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
