#!/usr/bin/env python3
"""R8-C ladder runner: run the case-256 sentinel (and optionally the full
accepted ladder) against a llama-server arm with exact evidence retention.
Same request protocol as accepted R8-B (issue191_run_ladder.py), extended
with optional n_probs capture for teacher-forced logprob evidence.
"""
import json, sys, time, urllib.request

def completion(base, case, n_probs=0):
    body = {
        "prompt": case["prompt_token_ids"],
        "n_predict": 8,
        "temperature": 0.0,
        "seed": 0,
        "cache_prompt": False,
        "return_tokens": True,
        "stream": False,
        "samplers": ["greedy"],
    }
    if n_probs:
        body["n_probs"] = n_probs
    req = urllib.request.Request(base + "/completion",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as r:
        res = json.load(r)
    return res, time.time() - t0

def main(fixture_path, base, out_path, label, n_probs=0, only_case=None):
    fx = json.load(open(fixture_path))
    results = []
    for case in fx["cases"]:
        if only_case and case["case_id"] != only_case:
            continue
        res, dur = completion(base, case, n_probs)
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
        if n_probs:
            rec["probs"] = [
                {"tok": p.get("id"), "logprob": p.get("logprob"),
                 "top": [{"tok": t.get("id"), "logprob": t.get("logprob")}
                          for t in (p.get("top_logprobs") or [])]}
                for p in (res.get("completion_probabilities") or [])
            ]
        print(json.dumps({k: rec[k] for k in ("case_id", "generated_tokens")}))
        results.append(rec)
    doc = {
        "schema": "inferswarm.issue193.arm-run/1",
        "label": label,
        "base_url": base,
        "n_probs": n_probs,
        "fixture_sha_note": "accepted R8-B fixture ladder (docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json)",
        "sampling": fx["sampling"],
        "results": results,
    }
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out_path)

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--nprobs" in a:
        i = a.index("--nprobs"); np_ = int(a[i+1]); a = a[:i] + a[i+2:]
    else:
        np_ = 0
    only = None
    if "--only" in a:
        i = a.index("--only"); only = a[i+1]; a = a[:i] + a[i+2:]
    main(*a, n_probs=np_, only_case=only)
