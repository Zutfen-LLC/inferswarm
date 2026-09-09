#!/usr/bin/env python3
"""Issue #117 Arm C — decoded-bytes derivation (CPU-only).

Independently derives the committed decoded output bytes for BOTH retained
sides from their raw token ids plus the frozen tokenizer files. Writes
decoded-bytes.json next to the retained arm-c evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-c-dir", required=True)
    parser.add_argument("--tokenizer", required=True)
    args = parser.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=False)
    base = Path(args.arm_c_dir)
    direct = json.loads((base / "direct-run.json").read_text())
    ordinary = json.loads((base / "ordinary-campaign.json").read_text())
    coordinator = json.loads((base / "coordinator-report.json").read_text())
    by_session = {r["session_id"]: r
                  for r in coordinator["coordinator_scope"]["requests"]}

    def sha(text):
        return hashlib.sha256(text.encode(
            "utf-8", errors="surrogatepass")).hexdigest()

    rows = []
    for record in ordinary["records"]:
        case_id = record["case_id"]
        index = record["request_session_index"]
        creq = by_session[index]
        dcase = next(r for r in direct["results"] if r["case_id"] == case_id)
        ordinary_ids = list(creq["prompt_token_ids"]) + list(
            creq["generated_token_ids"])
        direct_ids = list(dcase["prompt_token_ids"]) + list(
            dcase["generated_token_ids"])
        content = record["response"]["choices"][0]["message"]["content"]
        rows.append({
            "case_id": case_id,
            "session_id": index,
            "ordinary_decode_sha256": sha(tok.decode(ordinary_ids)),
            "direct_decode_sha256": sha(tok.decode(direct_ids)),
            "ordinary_http_content_sha256": sha(content),
            "ordinary_http_content_len": len(content.encode(
                "utf-8", errors="surrogatepass")),
        })
    out = {
        "schema": "inferswarm.issue117.arm-c.decoded-bytes/1",
        "tokenizer": str(args.tokenizer),
        "case_count": len(rows),
        "rows": rows,
    }
    (base / "decoded-bytes.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    both = sum(1 for r in rows
               if r["ordinary_decode_sha256"] == r["direct_decode_sha256"])
    http = sum(1 for r in rows if r["ordinary_decode_sha256"]
               == r["ordinary_http_content_sha256"])
    print(json.dumps({"cases": len(rows),
                      "ordinary_vs_direct_decodes_equal": both,
                      "ordinary_decode_vs_http_equal": http}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
