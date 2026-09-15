#!/usr/bin/env python3
"""R8-C Phase 3 teacher-forced capture: for each arm, evaluate the exact
next-token distribution at the case-256 divergence boundary by submitting
prompt + shared generated prefix (positions 0..2) with n_predict=1 and
n_probs=20. Also captures position 0 and position 2 boundaries for
alignment checking. One request per (arm, boundary); no generation loop.
"""
import json, sys, time, urllib.request

CASE = json.load(open("/tmp/i193/fixture-ladder.json"))["cases"][0]  # case-256
P = CASE["prompt_token_ids"]
SHARED = [561, 40554, 32039]  # accepted shared prefix, positions 0-2

def tf(base, ids, n_probs=20):
    body = {"prompt": ids, "n_predict": 1, "temperature": 0.0, "seed": 0,
            "cache_prompt": False, "return_tokens": True, "stream": False,
            "samplers": ["greedy"], "n_probs": n_probs}
    req = urllib.request.Request(base + "/completion", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1200) as r:
        return json.load(r), time.time() - t0

def main(base, out, arm):
    boundaries = {
        "b0_prompt_end": P,
        "b2_after_shared2": P + SHARED[:2],
        "b3_divergence": P + SHARED,
    }
    recs = {}
    for name, ids in boundaries.items():
        res, dur = tf(base, ids)
        probs = res.get("completion_probabilities") or []
        # teacher-forced: the single returned position describes P(next | ids)
        row = probs[-1] if probs else {}
        top = [{"tok": t.get("id"), "logprob": t.get("logprob")}
               for t in (row.get("top_logprobs") or [])]
        recs[name] = {
            "input_len": len(ids),
            "sampled_token": res.get("tokens", [None])[0],
            "row_tok": row.get("id"),
            "row_logprob": row.get("logprob"),
            "top20": top,
            "wall_s": round(dur, 3),
        }
        print(arm, name, "argmax_sampled=", recs[name]["sampled_token"],
              "top5=", [(t["tok"], round(t["logprob"], 4)) for t in top[:5]])
    doc = {"schema": "inferswarm.issue193.teacher-forced/1", "arm": arm,
           "base_url": base, "boundaries": recs}
    json.dump(doc, open(out, "w"), indent=2, sort_keys=True)
    print("wrote", out)

if __name__ == "__main__":
    main(*sys.argv[1:4])
