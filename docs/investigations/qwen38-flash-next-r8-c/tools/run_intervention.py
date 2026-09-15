#!/usr/bin/env python3
"""R8-C Phase 5 causal intervention arm-runner: identical to run_arm.py except
the sampler REQUEST FIELD resolves to a true greedy chain at this revision:
samplers=["top_k"] + top_k=1 (canonical name exists; k=1 => deterministic argmax).
Single factor changed vs the accepted R8-B protocol: sampler-chain construction."""
import json, sys, time, urllib.request

def completion(base, case):
    body = json.dumps({
        "prompt": case["prompt_token_ids"],
        "n_predict": 8,
        "temperature": 0.0,
        "seed": 0,
        "cache_prompt": False,
        "return_tokens": True,
        "stream": False,
        "samplers": ["top_k"],
        "top_k": 1,
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
            "case_id": case["case_id"], "prompt_len": case["rendered_length"],
            "generated_tokens": res.get("tokens"), "generated_text": res.get("content"),
            "stop_type": res.get("stop_type"), "stopping_word": res.get("stopping_word"),
            "timings": res.get("timings"), "wall_s": round(dur, 3),
        }
        print(json.dumps({"case_id": rec["case_id"], "tokens": rec["generated_tokens"]}))
        results.append(rec)
    doc = {"schema": "inferswarm.issue193.intervention-run/1", "label": label,
           "base_url": base, "samplers": ["top_k"], "top_k": 1,
           "fixture_sha_note": "accepted R8-B fixture ladder",
           "sampling": fx["sampling"], "results": results}
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True); fh.write("\n")
    print("wrote", out_path)

if __name__ == "__main__":
    main(*sys.argv[1:5])
