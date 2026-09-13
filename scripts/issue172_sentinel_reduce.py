#!/usr/bin/env python3
"""Issue #172 — Phase 5 sentinel repeatability reducer (CPU-only, stdlib).

Re-derives from raw retained bytes, for each of the seven sentinel
identities x six repeats x two arms:

- within-direct determinism: all six direct repeats' committed token
  ids identical;
- within-ordinary determinism: all six ordinary repeats' committed ids
  (from the serving-report session ledgers' token_events) identical;
- exact cross-arm equality per repeat;
- full distributions retained; no selection of a preferred run.

Any valid within-arm variation or cross-arm mismatch is FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402

SENTINELS = list(P.SENTINEL_HISTORICAL) + [s[0] for s in P.SENTINEL_170]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-run", required=True)
    parser.add_argument("--serving-report", required=True,
                        help="the sentinels-phase coordinator report")
    parser.add_argument("--ordinary-campaign", required=True,
                        help="ordinary sentinels client records")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    direct = json.loads(Path(args.direct_run).read_text())
    report = json.loads(Path(args.serving_report).read_text())
    ordinary = json.loads(Path(args.ordinary_campaign).read_text())
    corpus = json.loads(Path(args.corpus).read_text())
    session_of = {c["case_id"]: c["session_index"] for c in corpus["cases"]}

    problems: list[str] = []
    if direct.get("mode") != "sentinels" or direct["case_count"] != 42:
        problems.append("direct sentinels run shape drift")
    if ordinary["ok_count"] != 42:
        problems.append("ordinary sentinels ok count drift")

    # direct: {case_id: {repeat: committed}}
    direct_dist = {}
    for record in direct["results"]:
        direct_dist.setdefault(record["case_id"], {})[
            int(record["repeat"])] = list(record["generated_token_ids"])

    # ordinary: requests in serving report are in arrival order; the
    # client records carry (case_id, repeat); map session_id -> ids
    ordinary_requests = [
        r for r in report["coordinator_scope"]["requests"]
        if not r.get("fencing_arm_injections")]
    if len(ordinary_requests) != 42:
        problems.append(
            f"serving report carries {len(ordinary_requests)} sentinel "
            "requests")
    ordinary_dist = {}
    ordinary_records = [
        (r["case_id"], int(r.get("repeat", 0)))
        for r in ordinary["records"]]
    if len(ordinary_records) != len(ordinary_requests):
        problems.append("ordinary record/request count mismatch")
    for (case_id, repeat), request in zip(ordinary_records,
                                          ordinary_requests):
        events = request.get("token_events") or []
        ids = [int(e["token_id"]) for e in events]
        ordinary_dist.setdefault(case_id, {})[repeat] = ids

    rows = []
    deterministic = True
    cross_equal = True
    for case_id in SENTINELS:
        row = {"case_id": case_id, "problems": []}
        d_dist = direct_dist.get(case_id, {})
        o_dist = ordinary_dist.get(case_id, {})
        if sorted(d_dist) != list(range(1, 7)):
            row["problems"].append(
                f"direct repeats present: {sorted(d_dist)}")
        if sorted(o_dist) != list(range(1, 7)):
            row["problems"].append(
                f"ordinary repeats present: {sorted(o_dist)}")
        d_values = [d_dist[r] for r in sorted(d_dist)]
        o_values = [o_dist[r] for r in sorted(o_dist)]
        if len(d_values) == 6 and len({tuple(v) for v in d_values}) != 1:
            row["problems"].append(
                f"direct within-arm variation: {d_values}")
            deterministic = False
        if len(o_values) == 6 and len({tuple(v) for v in o_values}) != 1:
            row["problems"].append(
                f"ordinary within-arm variation: {o_values}")
            deterministic = False
        if d_values and o_values:
            for repeat in sorted(set(d_dist) & set(o_dist)):
                if d_dist[repeat] != o_dist[repeat]:
                    row["problems"].append(
                        f"repeat {repeat} cross-arm mismatch: direct="
                        f"{d_dist[repeat]} ordinary={o_dist[repeat]}")
                    cross_equal = False
        row["direct_distribution"] = {str(k): v for k, v in
                                      sorted(d_dist.items())}
        row["ordinary_distribution"] = {str(k): v for k, v in
                                        sorted(o_dist.items())}
        rows.append(row)

    global_problems = problems + [
        f"{r['case_id']}: " + "; ".join(r["problems"])
        for r in rows if r["problems"]]
    passed = (deterministic and cross_equal and not problems
              and len(rows) == 7)
    record = {
        "schema": "inferswarm.issue172.arm-c-requal.sentinel-reduction/1",
        "campaign_id": P.CAMPAIGN_ID,
        "sentinels": SENTINELS,
        "repeats_per_identity_per_arm": P.SENTINEL_REPEATS,
        "within_direct_deterministic": deterministic,
        "within_ordinary_deterministic": deterministic and all(
            not ("ordinary within-arm variation" in p)
            for r in rows for p in r["problems"]),
        "cross_arm_exact": cross_equal,
        "rows": rows,
        "global_problems": global_problems,
        "terminal": P.PASS_TERMINAL if passed else P.FAIL_TERMINAL,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True)
                              + "\n")
    print(json.dumps({
        "sentinels": len(rows),
        "within_direct_deterministic": record["within_direct_deterministic"],
        "within_ordinary_deterministic":
            record["within_ordinary_deterministic"],
        "cross_arm_exact": cross_equal,
        "terminal": record["terminal"],
        "problems": global_problems[:6],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
