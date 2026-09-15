#!/usr/bin/env python3
"""Issue #191 R8-B: run the frozen fixture ladder against a llama-server
instance (reference or candidate) and retain exact evidence.

Usage: issue191_run_ladder.py <fixture-ladder.json> <base-url> <out-json> <label>
"""
import json
import sys
import time
import urllib.request


def completion(base, case):
    body = json.dumps({
        "prompt": case["prompt_token_ids"],
        "n_predict": 8,
        "temperature": 0.0,
        "seed": 0,
        "cache_prompt": False,
        "return_tokens": True,
        "stream": False,
        "samplers": ["greedy"],
    }).encode()
    req = urllib.request.Request(base + "/completion", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as r:
        res = json.load(r)
    return res, time.time() - t0


def main(fixture_path, base, out_path, label):
    fx = json.load(open(fixture_path))
    results = []
    for case in fx["cases"]:
        res, dur = completion(base, case)
        rec = {
            "case_id": case["case_id"],
            "prompt_len": case["rendered_length"],
            "generated_tokens": res.get("tokens"),
            "generated_text": res.get("content"),
            "stop_type": res.get("stop_type"),
            "stopping_word": res.get("stopping_word"),
            "timings": res.get("timings"),
            "wall_s": round(dur, 3),
        }
        print(json.dumps({k: rec[k] for k in ("case_id", "prompt_len",
                                              "generated_tokens", "wall_s")}))
        results.append(rec)
    doc = {
        "schema": "inferswarm.issue191.ladder-run/1",
        "label": label,
        "base_url": base,
        "fixture_sha_note": "fixture ladder as frozen in evidence/reference/fixture-ladder.json",
        "sampling": fx["sampling"],
        "results": results,
    }
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out_path)


if __name__ == "__main__":
    main(*sys.argv[1:5])
