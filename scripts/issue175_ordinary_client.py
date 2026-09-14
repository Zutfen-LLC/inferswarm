#!/usr/bin/env python3
"""Issue #175 — Arm-D ordinary client (orchestration host, stdlib).

Drives the frozen corpora through the ordinary external-Coordinator
path exactly like the accepted #172 issue172_ordinary_client.py
(same request shape, same session order, same fencing-arm trailing
control), but against the Arm-D phase endpoints and with Arm-D
schemas/attempt ids. Retains per-case HTTP records independently.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

SENTINEL_IDS = (
    "c109-04-02-047", "c109-04-06-074", "c109-03-04-003",
    "g170-01", "g170-05", "g170-09", "g170-13",
)


def post_chat(origin: str, body: dict, *, timeout: int = 3600) -> dict:
    payload = json.dumps(body).encode()
    request = urllib.request.Request(
        origin.rstrip("/") + "/v1/chat/completions",
        data=payload, headers={"Content-Type": "application/json"},
        method="POST")
    started = time.time_ns()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()
    return {"http_status": status, "response_bytes": raw,
            "wall_ns": time.time_ns() - started}


def case_body(case: dict, extra: dict | None = None) -> dict:
    body = {
        "model": "gemma-4-12B-it",
        "messages": [{"role": "user", "content": case["prompt_text"]}],
        "temperature": 0.0,
        "max_tokens": 8,
    }
    if extra:
        body.update(extra)
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://10.0.0.206:18080")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--mode", choices=["canonical", "sentinels",
                                           "screen"],
                        default="canonical")
    args = parser.parse_args()

    corpus = json.loads(Path(args.corpus).read_text())
    cases = sorted(corpus["cases"], key=lambda c: c["session_index"])
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    records = []
    fencing = None
    if args.mode in ("canonical", "screen"):
        for case in cases:
            outcome = post_chat(args.origin, case_body(case))
            record = {
                "schema": "inferswarm.issue175.arm-d.ordinary-case/1",
                "case_id": case["case_id"],
                "arm": case.get("arm"),
                "request_session_index": case["session_index"],
                "http_status": outcome["http_status"],
                "request_body": case_body(case),
                "response": json.loads(outcome["response_bytes"])
                if outcome["http_status"] == 200 else
                outcome["response_bytes"].decode("utf-8", "replace"),
                "wall_ns": outcome["wall_ns"],
            }
            records.append(record)
            (out / f"ordinary-{case['case_id']}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"case": case["case_id"],
                              "status": outcome["http_status"],
                              "wall_ms": outcome["wall_ns"] / 1e6}),
                  flush=True)
        if args.mode == "canonical":
            fencing_case = cases[0]
            outcome = post_chat(args.origin, case_body(
                fencing_case,
                extra={"inferswarm_fencing_arm_after_step": 3}))
            fencing = {
                "schema": "inferswarm.issue175.arm-d.fencing-arm/1",
                "case_id": fencing_case["case_id"],
                "http_status": outcome["http_status"],
                "request_body": case_body(
                    fencing_case,
                    extra={"inferswarm_fencing_arm_after_step": 3}),
                "response": json.loads(outcome["response_bytes"])
                if outcome["http_status"] == 200 else
                outcome["response_bytes"].decode("utf-8", "replace"),
                "wall_ns": outcome["wall_ns"],
            }
            (out / "fencing-arm.json").write_text(json.dumps(
                fencing, indent=2, sort_keys=True) + "\n")
    else:
        sentinels = [c for c in cases if c["case_id"] in SENTINEL_IDS]
        if len(sentinels) != 7:
            raise SystemExit("sentinel identities missing from corpus")
        for repeat in range(1, 7):
            for case in sentinels:
                outcome = post_chat(args.origin, case_body(case))
                record = {
                    "schema":
                        "inferswarm.issue175.arm-d.ordinary-sentinel/1",
                    "case_id": case["case_id"],
                    "repeat": repeat,
                    "http_status": outcome["http_status"],
                    "request_body": case_body(case),
                    "response": json.loads(outcome["response_bytes"])
                    if outcome["http_status"] == 200 else
                    outcome["response_bytes"].decode("utf-8", "replace"),
                    "wall_ns": outcome["wall_ns"],
                }
                records.append(record)
                print(json.dumps({"case": case["case_id"],
                                  "repeat": repeat,
                                  "status": outcome["http_status"],
                                  "wall_ms": outcome["wall_ns"] / 1e6}),
                      flush=True)

    ok_count = sum(1 for r in records if r["http_status"] == 200)
    campaign = {
        "schema": "inferswarm.issue175.arm-d.ordinary-campaign/1",
        "attempt_id": args.attempt_id,
        "mode": args.mode,
        "origin": args.origin,
        "case_count": len(records),
        "ok_count": ok_count,
        "records": records,
        "fencing_arm": fencing,
        "completed_at_ns": time.time_ns(),
    }
    (out / "ordinary-campaign.json").write_text(json.dumps(
        campaign, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ordinary_campaign": str(out / "ordinary-campaign.json"),
                      "ok": f"{ok_count}/{len(records)}", "mode": args.mode}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
