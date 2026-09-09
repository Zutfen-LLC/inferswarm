#!/usr/bin/env python3
"""Issue #117 Arm C — ordinary-client campaign driver.

Pure-stdlib HTTP client: drives the 24 frozen fixture cases through the
ordinary path ONLY (HTTP POST /v1/chat/completions to the external
CPU-only Coordinator on inferswarm00), in deterministic ascending case_id
order, plus one trailing fencing-arm request. Retains per-case HTTP
records independently of the coordinator's own serving report.

Runs on the orchestration host (zutfen/hermes control host). The client is
an ordinary client: no coordinator-internal imports, no direct node
access, no model nouns.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def post_chat(origin: str, body: dict, *, timeout: int = 3600) -> dict:
    payload = json.dumps(body).encode()
    request = urllib.request.Request(
        origin.rstrip("/") + "/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time_ns()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()
    return {
        "http_status": status,
        "response_body": json.loads(raw) if raw else None,
        "wall_ns": time.time_ns() - started,
    }


def get_health(origin: str, *, timeout: int = 30) -> dict:
    with urllib.request.urlopen(origin.rstrip("/") + "/health",
                                timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True,
                        help="coordinator base URL, e.g. http://10.0.0.206:18080")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--fencing-after-cases", action="store_true",
                        default=True)
    args = parser.parse_args()

    fixture = json.loads(Path(args.fixture).read_text())
    cases = sorted(fixture["cases"], key=lambda c: c["case"]["case_id"])
    if len(cases) != 24:
        raise SystemExit(f"ARM_C_CLIENT_FAIL: expected 24 cases")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    health = get_health(args.origin)
    records = []
    fencing_record = None
    for index, case in enumerate(cases, 1):
        case_id = case["case"]["case_id"]
        body = {
            "model": "gemma-4-12B-it",
            "messages": [
                {"role": "user", "content": case["case"]["prompt_text"]}
            ],
            "max_tokens": 8,
            "temperature": 0.0,
        }
        outcome = post_chat(args.origin, body)
        record = {
            "schema": "inferswarm.issue117.arm-c.ordinary-case/1",
            "case_id": case_id,
            "request_session_index": index,
            "request_body": body,
            "http_status": outcome["http_status"],
            "response": outcome["response_body"],
            "wall_ns": outcome["wall_ns"],
        }
        records.append(record)
        (out / f"ordinary-{case_id}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n")

    if args.fencing_after_cases:
        # Real serving-path fencing arm on a distinct session (lowest case).
        body = {
            "model": "gemma-4-12B-it",
            "messages": [
                {"role": "user",
                 "content": cases[0]["case"]["prompt_text"]},
            ],
            "max_tokens": 8,
            "temperature": 0.0,
            "inferswarm_fencing_arm_after_step": 3,
        }
        outcome = post_chat(args.origin, body)
        fencing_record = {
            "schema": "inferswarm.issue117.arm-c.fencing-arm/1",
            "case_id": cases[0]["case"]["case_id"],
            "request_session_index": 25,
            "request_body": body,
            "http_status": outcome["http_status"],
            "response": outcome["response_body"],
            "wall_ns": outcome["wall_ns"],
        }
        (out / "fencing-arm.json").write_text(
            json.dumps(fencing_record, indent=2, sort_keys=True) + "\n")

    summary = {
        "schema": "inferswarm.issue117.arm-c.ordinary-campaign/1",
        "attempt_id": args.attempt_id,
        "origin": args.origin,
        "health": health,
        "case_count": len(records),
        "ok_count": sum(1 for r in records if r["http_status"] == 200),
        "records": records,
        "fencing_arm": fencing_record,
        "completed_at_ns": time.time_ns(),
    }
    (out / "ordinary-campaign.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "cases": len(records),
        "ok": summary["ok_count"],
        "fencing_status": fencing_record["http_status"]
        if fencing_record else None,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
