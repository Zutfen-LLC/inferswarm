"""Issue #195 R8-D: true-greedy ladder runner.

Runs the accepted R8-B fixture ladder against a llama-server instance with
the frozen R8-D true-greedy request contract, retaining exact evidence.

Usage: issue195_run_ladder.py <fixture-ladder.json> <base-url> <out-json> <label> [--only case-id]
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/scripts")
from issue195_r8d_authority import REQUEST_CONTRACT  # noqa: E402


def completion(base, case):
    body = dict(REQUEST_CONTRACT)
    body["prompt"] = case["prompt_token_ids"]
    req = urllib.request.Request(
        base + "/completion", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=3600) as r:
        res = json.load(r)
    return res, time.time() - t0


def main(fixture_path, base, out_path, label, only_case=None):
    fx = json.load(open(fixture_path))
    results = []
    for case in fx["cases"]:
        if only_case and case["case_id"] != only_case:
            continue
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
        "schema": "inferswarm.issue195.ladder-run/1",
        "label": label,
        "base_url": base,
        "campaign": "issue195-r8d-true-greedy-requal-v1",
        "request_contract": REQUEST_CONTRACT,
        "fixture_sha_note": ("accepted R8-B fixture ladder consumed verbatim: "
                             + "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json"),
        "results": results,
    }
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out_path)


if __name__ == "__main__":
    a = sys.argv[1:]
    only = None
    if "--only" in a:
        i = a.index("--only"); only = a[i + 1]; a = a[:i] + a[i + 2:]
    main(*a, only_case=only)
