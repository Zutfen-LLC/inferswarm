#!/usr/bin/env python3
"""Issue #207 R8-G: boundary-observation capture producer (on-host,
inferswarm01; CPU-pure stdlib).

Per arm (reference/candidate) and case (case-4096/case-256), with a FRESH
diagnostic server process per capture (--no-warmup so no graph executes
before the request; the capture additionally proves the boundary JSONL is
empty at request time):

  1. prompt = the exact accepted R8-D case prompt token ids (mechanically
     loaded via authority.load_decision_inputs);
  2. canonical request = the accepted contract byte-for-byte
     (serialize_request), n_predict=8, NO forbidden keys;
  3. the diagnostic server (LLAMA_OBSERVE_* env bound to this capture)
     serves the request:
       - the sampling-seam hook (R8-E semantics) appends one JSONL row per
         sampled token and writes the exact f32 logits row at the frozen
         target position (non-perturbation + seam-anchor bytes);
       - the boundary observer (native eval callback) appends one JSONL row
         per wanted-node occurrence and writes the raw last-token-column
         f32 sidecar per occurrence;
  4. the producer retains: request/response bytes (b64+sha256), both hook
     JSONLs, every sidecar named by its rows, and a capture record binding
     {case, arm, phase, boundary spec, prompt identity, producer identity,
     git head}.

Graph-execution binding (frozen derivation, implemented in
issue207_r8g_reduce.py, verified here at capture time):
  - the server runs --no-warmup; the producer proves the boundary JSONL
    was empty before the request, so occurrence 0 of every name is the
    first graph execution of the request;
  - result_output occurrences with a VALID column digest are exactly the
    output-bearing executions (final prefill exec + one per subsequent
    generated position); the EARLIEST such occurrence is the execution
    whose logits produced generated position 0 (the R8-E-observed row);
  - for one-occurrence-per-exec names (every frozen boundary name), the
    generated-position-p occurrence is seq(e0 + p) where e0 is that
    earliest valid result_output seq.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from issue207_r8g_authority import (  # noqa: E402
    CAMPAIGN_ID, FORBIDDEN_REQUEST_KEYS, OBS_SCHEMA, REQUEST_CONTRACT,
    R8G_DIR, serialize_request)

REPO = os.path.abspath(os.path.join(HERE, ".."))
EV = os.path.join(REPO, R8G_DIR, "evidence")

DECISION_POS = {"case-256": 5, "case-4096": 0}   # generated position observed
PORTS = {"reference": 8341, "candidate": 8343}


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def git_state():
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    return head, dirty == ""


def producer_sha():
    return sha_b(open(os.path.abspath(__file__), "rb").read())


def send_capture(arm, case, inputs, out_dir, label, phase, spec,
                 server_env_hint):
    pos = DECISION_POS[case]
    prompt = list(inputs[case][arm]["prompt_token_ids"])
    body = serialize_request(prompt)
    url = f"http://127.0.0.1:{PORTS[arm]}/completion"
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})

    b_jsonl = os.path.join(out_dir, f"bounds-{label}.jsonl")
    l_jsonl = os.path.join(out_dir, f"logits-{label}.jsonl")
    # producer-side proof that no boundary rows predate the request
    pre_rows = 0
    if os.path.exists(b_jsonl):
        with open(b_jsonl) as fh:
            pre_rows = sum(1 for _ in fh)

    started = utcnow()
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        raw = r.read()
    elapsed = round(time.time() - t0, 3)
    res = json.loads(raw)

    lrows = []
    if os.path.exists(l_jsonl):
        for line in open(l_jsonl):
            line = line.strip()
            if line:
                lrows.append(json.loads(line))
    brows = []
    if os.path.exists(b_jsonl):
        for line in open(b_jsonl):
            line = line.strip()
            if line:
                brows.append(json.loads(line))

    # f32 logits row at the target position (seam anchor)
    f32_path = l_jsonl + f".pos{pos}.f32"
    row_b = open(f32_path, "rb").read() if os.path.exists(f32_path) else b""
    import struct
    n = len(row_b) // 4
    vals = struct.unpack(f"<{n}f", row_b) if n else ()
    row_sha = sha_b(row_b) if row_b else None
    n_nonfinite = sum(1 for v in vals if v != v or v in
                      (float("inf"), float("-inf"))) if vals else None

    # boundary sidecar set named by the retained rows (presence check)
    sidecars = {}
    for r_ in brows:
        safe = "".join(c if (c.isalnum() or c in ".-_") else "_"
                       for c in r_["name"])
        p = os.path.join(out_dir, f"{safe}__{r_['seq']}.f32")
        sidecars[p] = os.path.getsize(p) if os.path.exists(p) else -1

    rec = {
        "schema": OBS_SCHEMA,
        "campaign": CAMPAIGN_ID,
        "arm": arm,
        "case": case,
        "phase": phase,
        "label": label,
        "boundary_spec": spec,
        "server_env_hint": server_env_hint,
        "generated_position_target": pos,
        "prompt_token_count": len(prompt),
        "prompt_sha256": sha_b(json.dumps(prompt).encode()),
        "request_body_b64": base64.b64encode(body).decode(),
        "request_body_sha256": sha_b(body),
        "response_body_b64": base64.b64encode(raw).decode(),
        "response_body_sha256": sha_b(raw),
        "response_generated_tokens": res.get("tokens") or
            res.get("generated_tokens") or [],
        "response_stop_type": res.get("stop_type"),
        "response_timings": res.get("timings"),
        "preexisting_boundary_rows": pre_rows,
        "boundary_rows": brows,
        "boundary_row_count": len(brows),
        "boundary_sidecar_sizes": {
            os.path.basename(k): v for k, v in sidecars.items()},
        "logits_hook_rows": lrows,
        "f32_row_sha256": row_sha,
        "f32_row_floats": n,
        "f32_row_nonfinite": n_nonfinite,
        "started_utc": started,
        "ended_utc": utcnow(),
        "elapsed_s": elapsed,
        "producer": os.path.basename(__file__),
        "producer_sha256": producer_sha(),
        "git_head": None,   # filled by caller
    }
    return rec


def verify_capture(rec, inputs):
    probs = []
    case, arm = rec["case"], rec["arm"]
    pos = DECISION_POS[case]
    exp_prompt = list(inputs[case][arm]["prompt_token_ids"])
    req = json.loads(base64.b64decode(rec["request_body_b64"]))
    if req.get("prompt") != exp_prompt:
        probs.append("request prompt != accepted case prompt")
    for k in FORBIDDEN_REQUEST_KEYS:
        if k in req:
            probs.append("forbidden request key " + k)
    if req.get("n_predict") != REQUEST_CONTRACT["n_predict"]:
        probs.append("n_predict drift")
    if rec["preexisting_boundary_rows"] != 0:
        probs.append("boundary rows existed before the request "
                     "(warmup not disabled?)")
    # sampling-seam row at target position must match the response token
    tgt = [r for r in rec["logits_hook_rows"] if r["pos"] == pos]
    if not tgt:
        probs.append(f"no logits hook row at generated position {pos}")
    else:
        gt = rec["response_generated_tokens"] or []
        if pos >= len(gt) or tgt[0]["tok"] != gt[pos]:
            probs.append("hook tok != response token at target position")
    # every boundary row's sidecar must exist with the recorded size
    for r_ in rec["boundary_rows"]:
        safe = "".join(c if (c.isalnum() or c in ".-_") else "_"
                       for c in r_["name"])
        key = f"{safe}__{r_['seq']}.f32"
        sz = rec["boundary_sidecar_sizes"].get(key)
        if sz is None:
            probs.append("sidecar missing for row " + key)
        elif r_["sha256"] != "NA":
            if sz != r_["col_nbytes"]:
                probs.append("sidecar size mismatch " + key)
    return probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True,
                    choices=["reference", "candidate"])
    ap.add_argument("--case", required=True, choices=["case-256",
                                                      "case-4096"])
    ap.add_argument("--phase", required=True,
                    choices=["nonpert", "coarse", "refine", "contrast"])
    ap.add_argument("--spec", required=True,
                    help="exact LLAMA_OBSERVE_BOUNDARIES string")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    sys.path.insert(0, HERE)
    from issue207_r8g_authority import load_decision_inputs
    inputs = load_decision_inputs(REPO)
    rec = send_capture(a.arm, a.case, inputs, a.out_dir, a.label,
                       a.phase, a.spec,
                       "LLAMA_OBSERVE_BOUNDARIES=%s" % a.spec)
    head, clean = git_state()
    rec["git_head"] = head
    rec["git_clean"] = clean
    probs = verify_capture(rec, inputs)
    rec["capture_problems"] = probs
    out = os.path.join(a.out_dir, f"capture-{a.label}.json")
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"label": a.label, "problems": probs,
                      "boundary_rows": rec["boundary_row_count"],
                      "tokens": rec["response_generated_tokens"][:8]}))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
