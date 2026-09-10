#!/usr/bin/env python3
"""Issue #133 — direct-vs-ordinary equality reducer (independent derivation).

Compares, per case, deriving everything from retained raw evidence:
  1. committed token IDs at every position (ordinary: serving-report
     runtime_sessions step-0 ids under the frozen allocator; direct:
     per-case generated_token_ids);
  2. committed token count (8) and per-call generated count (2);
  3. stop semantics (finish_reason == length);
  4. decoded output bytes: sha256(tok.decode(prompt+committed)) for BOTH
     arms compared to each other AND to the ordinary HTTP content bytes
     (the ordinary coordinator's response content IS the decode of
     prompt+committed — the accepted #117 comparator contract);
  5. session/runtime identities (allocator sequence, plan digests).

No stored `equal` field is consumed.
"""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

DIRECT_DIR = Path(sys.argv[1])
ORDINARY_CAMPAIGN = Path(sys.argv[2])
SERVING_REPORT = Path(sys.argv[3])
TOKENIZER = sys.argv[4]  # /srv/inferswarm/tokenizers/gemma-r6-frozen or local copy

from transformers import AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(
    TOKENIZER, trust_remote_code=False, local_files_only=True)

direct_cases = {}
for p in sorted(DIRECT_DIR.glob("direct-c109-*.json")):
    d = json.loads(p.read_text())
    direct_cases[d["case_id"]] = d

campaign = json.loads(ORDINARY_CAMPAIGN.read_text())
serving = json.loads(SERVING_REPORT.read_text())
sessions = serving["epochs"][0]["runtime_sessions"]

by_logical = defaultdict(list)
for s in sessions:
    by_logical[s["session_id"] // 1_000_000].append(s)

problems = []
rows = []
records = campaign["records"]
if len(records) != 24:
    problems.append(f"ordinary records: {len(records)} != 24")
if len(direct_cases) != 24:
    problems.append(f"direct cases: {len(direct_cases)} != 24")

serving_plan = serving["epochs"][0]["plan_digest"]

for i, rec in enumerate(records):
    case_id = rec["case_id"]
    logical = i + 1
    d = direct_cases.get(case_id)
    if d is None:
        problems.append(f"{case_id}: no direct case")
        continue
    body = rec.get("response_body") or rec["response"]
    choices = body["choices"][0]
    finish = choices["finish_reason"]
    content = choices["message"]["content"]

    case_sessions = sorted(by_logical.get(logical, []),
                           key=lambda s: s["session_id"])
    if len(case_sessions) != 8:
        problems.append(f"{case_id}: {len(case_sessions)} sessions != 8")
        continue
    ids = [s["session_id"] for s in case_sessions]
    if len(set(ids)) != 8:
        problems.append(f"{case_id}: allocator sequence drift {ids}")
    for s in case_sessions:
        if len(s["generated_token_ids"]) != 2:
            problems.append(
                f"{case_id}: session {s['session_id']} generated "
                f"{len(s['generated_token_ids'])} != 2")
        if s["plan_digest"] != serving_plan:
            problems.append(
                f"{case_id}: session plan digest drift")
    ord_ids = [s["generated_token_ids"][0] for s in case_sessions]
    dir_ids = list(d["generated_token_ids"])
    prompt_ids = list(d["prompt_token_ids"])

    if list(ord_ids) != dir_ids:
        problems.append(
            f"{case_id}: committed ids differ: ordinary={ord_ids} "
            f"direct={dir_ids}")
    if len(dir_ids) != 8:
        problems.append(f"{case_id}: direct committed {len(dir_ids)} != 8")
    if finish != "length":
        problems.append(f"{case_id}: finish {finish} != length")

    ord_decode = tok.decode(prompt_ids + ord_ids)
    dir_decode = tok.decode(prompt_ids + dir_ids)
    if ord_decode != dir_decode:
        problems.append(f"{case_id}: decoded(prompt+committed) differ")
    if content != ord_decode:
        problems.append(
            f"{case_id}: HTTP content != decode(prompt+ordinary_committed)")
    rows.append({
        "case_id": case_id,
        "logical_session": logical,
        "runtime_session_ids": ids,
        "committed_ids_equal": list(ord_ids) == dir_ids,
        "decoded_equal": ord_decode == dir_decode,
        "http_content_bind": content == ord_decode,
        "finish_reason": finish,
        "committed_count": len(dir_ids),
        "committed_token_ids": dir_ids,
        "decoded_sha256": hashlib.sha256(
            dir_decode.encode(errors="surrogatepass")).hexdigest(),
    })

equal_count = sum(
    1 for r in rows
    if r["committed_ids_equal"] and r["decoded_equal"] and r["http_content_bind"])
result = {
    "schema": "inferswarm.issue133.arm-c-retry.equality-reduction/1",
    "case_count": len(rows),
    "equal_count": equal_count,
    "serving_plan_digest": serving_plan,
    "rows": rows,
    "problems": problems,
    "passed": not problems and equal_count == 24,
}
print(json.dumps(result, indent=2, sort_keys=True))
sys.exit(0 if result["passed"] else 1)
