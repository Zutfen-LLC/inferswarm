#!/usr/bin/env python3
"""Issue #199 R8-E: decision-point observation capture producer (on-host,
inferswarm01; CPU-pure stdlib).

Per arm (reference/candidate) and case (case-256/case-4096), with a FRESH
server process per request (session-contamination-free):

  1. teacher-forced state = exact accepted R8-D prompt token IDs (+ the
     exact accepted common generated prefix positions 0..4 for case-256;
     no prefix for case-4096), mechanically loaded from the accepted
     retained run bytes (authority.load_decision_inputs);
  2. canonical request = the accepted R8-D request contract byte-for-byte
     (same serialization rules), prompt = the teacher-forced state;
  3. the diagnostic server (LLAMA_OBSERVE_* env bound to this capture's
     output path + target generated position + focus tokens) serves the
     request; the hook appends one JSONL line per sampled token and
     writes the exact float32 logits row at the target position;
  4. the producer retains: complete request/response bytes (base64 +
     sha256), the hook JSONL rows, the float32 row bytes (retained in the
     evidence dir; sha256 + derived stats computed from the bytes), and
     full identity (case, arm, generated position, prompt sha, campaign,
     producer sha, git head/clean, UTC stamps).

Evidence records embed `binding` = {case, arm, generated_position,
prompt_token_count, prompt_sha256, request_sha256, observation_path} so
score capture lacking token-position binding fails closed downstream.

The same --arm accepted mode runs the UNINSTRUMENTED accepted binary for
the non-perturbation controls (no LLAMA_OBSERVE_* env set; hook inert).
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
from issue199_r8e_authority import (  # noqa: E402
    CAMPAIGN_ID, CASE256_PREFIX, CASES, FOCUS_TOKENS, OBS_SCHEMA,
    R8E_DIR, REQUEST_CONTRACT, serialize_request)

REPO = os.path.abspath(os.path.join(HERE, ".."))
EV = os.path.join(REPO, R8E_DIR, "evidence")

# decision-point spec: (case, teacher-forcing prefix, target gen position)
DECISION_POINTS = {
    "case-256":  {"prefix": CASE256_PREFIX, "pos": 5},
    "case-4096": {"prefix": [],            "pos": 0},
}

PORTS = {"reference": 8331, "candidate": 8333}


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


def send_capture(arm, case, inputs, out_dir, label, binary_env=None):
    """One request against a running server; capture + retain evidence."""
    dp = DECISION_POINTS[case]
    prompt = list(inputs[case][arm]["prompt_token_ids"]) + list(dp["prefix"])
    body = serialize_request(prompt)
    url = f"http://127.0.0.1:{PORTS[arm]}/completion"
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    obs_path = os.path.join(out_dir, f"obs-{label}.jsonl")
    if os.path.exists(obs_path):
        os.remove(obs_path)
    env = dict(binary_env or {})
    started = utcnow()
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        raw = r.read()
    elapsed = round(time.time() - t0, 3)
    res = json.loads(raw)
    # read hook output
    rows = []
    if os.path.exists(obs_path):
        for line in open(obs_path):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    # float32 row at target position
    f32_path = obs_path + f".pos{dp['pos']}.f32"
    row_b = open(f32_path, "rb").read() if os.path.exists(f32_path) else b""
    # derived stats from retained bytes (never from C++)
    import struct
    n = len(row_b) // 4
    vals = struct.unpack(f"<{n}f", row_b) if n else ()
    top16_from_bytes = []
    if vals:
        order = sorted(range(n), key=lambda i: (-vals[i], i))[:16]
        top16_from_bytes = [[i, vals[i]] for i in order]
        row_sha = sha_b(row_b)
        n_nonfinite = sum(1 for v in vals if v != v or v in
                          (float("inf"), float("-inf")))
        fsum = sum(vals)  # plain sum; math.fsum for the record too
        import math
        fsumx = math.fsum(vals)
        sumsq = math.fsum(v * v for v in vals)
    else:
        row_sha, n_nonfinite, fsum, fsumx, sumsq = None, None, None, None, None
    rec = {
        "schema": OBS_SCHEMA,
        "campaign": CAMPAIGN_ID,
        "arm": arm,
        "case": case,
        "label": label,
        "generated_position_observed": dp["pos"],
        "teacher_forced_prefix": list(dp["prefix"]),
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
        "hook_rows": rows,
        "f32_row_sha256": row_sha,
        "f32_row_floats": n,
        "f32_row_stats": {
            "n_nonfinite": n_nonfinite, "fsum": fsum, "fsum_math": fsumx,
            "sumsq": sumsq,
        } if row_sha else None,
        "top16_from_f32_bytes": top16_from_bytes,
        "binding": {
            "case": case, "arm": arm, "generated_position": dp["pos"],
            "prompt_token_count": len(prompt),
            "prompt_sha256": sha_b(json.dumps(prompt).encode()),
            "request_sha256": sha_b(body),
            "observation_path": os.path.basename(obs_path),
        },
        "started_utc": started,
        "ended_utc": utcnow(),
        "elapsed_s": elapsed,
        "producer": os.path.basename(__file__),
        "producer_sha256": producer_sha(),
        "git_head": None,  # filled by caller (single git_state per run)
    }
    # retain the float32 bytes themselves under evidence/
    if row_b:
        with open(os.path.join(out_dir, f"row-{label}.pos{dp['pos']}.f32"),
                  "wb") as fh:
            fh.write(row_b)
    return rec


def verify_capture(rec, inputs):
    """Fail-closed checks on one capture record (used live and by the
    reducer/tests). Returns list of problems."""
    probs = []
    case, arm = rec["case"], rec["arm"]
    dp = DECISION_POINTS[case]
    # 1. teacher-forced identity against accepted bytes
    exp_prompt = list(inputs[case][arm]["prompt_token_ids"]) + list(dp["prefix"])
    got_prompt = json.loads(base64.b64decode(rec["request_body_b64"]))["prompt"]
    if got_prompt != exp_prompt:
        probs.append("request prompt != teacher-forced accepted state")
    # 2. token-position binding
    tgt = [r for r in rec["hook_rows"] if r["pos"] == dp["pos"]]
    if not tgt:
        probs.append(f"no hook row at generated position {dp['pos']}")
    else:
        r0 = tgt[0]
        if r0["n_vocab"] != rec["f32_row_floats"]:
            probs.append("hook n_vocab != f32 row floats")
        if r0["tok"] != (rec["response_generated_tokens"] or [None])[dp["pos"]
                                                                    if dp["pos"] < len(rec["response_generated_tokens"] or []) else 0]:
            # sampled token at the observed position must equal the
            # response token at the same position
            gt = rec["response_generated_tokens"]
            if dp["pos"] >= len(gt) or r0["tok"] != gt[dp["pos"]]:
                probs.append("hook tok != response token at observed position")
    # 3. row stats consistency
    if rec["f32_row_stats"] is None:
        probs.append("no f32 row retained at target position")
    elif rec["f32_row_stats"]["n_nonfinite"] != \
            (tgt[0]["n_nonfinite"] if tgt else None):
        probs.append("n_nonfinite mismatch hook vs derived bytes")
    # 4. top16 agreement hook vs bytes
    if tgt and rec["top16_from_f32_bytes"]:
        h = [[t, round(v, 6)] for t, v in tgt[0]["top"]]
        b = [[t, round(v, 6)] for t, v in rec["top16_from_f32_bytes"]]
        if h != b:
            probs.append("top16 mismatch hook vs derived bytes")
    # 5. no forbidden request keys
    req = json.loads(base64.b64decode(rec["request_body_b64"]))
    for k in ("n_probs", "probs", "min_p", "top_p", "typical_p"):
        if k in req:
            probs.append("forbidden request key " + k)
    return probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True,
                    choices=["reference", "candidate"])
    ap.add_argument("--case", required=True, choices=CASES)
    ap.add_argument("--mode", default="obs", choices=["obs", "accepted"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    from issue199_r8e_authority import load_decision_inputs
    inputs = load_decision_inputs(REPO)
    dp = DECISION_POINTS[a.case]
    env = {}
    if a.mode == "obs":
        env = {
            "LLAMA_OBSERVE_LOGITS": os.path.join(
                a.out_dir, f"obs-{a.label}.jsonl"),
            "LLAMA_OBSERVE_POS": str(dp["pos"]),
            "LLAMA_OBSERVE_FOCUS": ",".join(
                str(t) for t in FOCUS_TOKENS[a.case]),
        }
        # NOTE: env vars must be set in the SERVER process; the caller
        # launches the server with these. Here we only record the
        # intended observation path for the record.
    rec = send_capture(a.arm, a.case, inputs, a.out_dir, a.label, env)
    head, clean = git_state()
    rec["git_head"] = head
    rec["git_clean"] = clean
    rec["mode"] = a.mode
    probs = verify_capture(rec, inputs)
    rec["capture_problems"] = probs
    out = os.path.join(a.out_dir, f"capture-{a.label}.json")
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"label": a.label, "problems": probs,
                      "tokens": rec["response_generated_tokens"],
                      "out": out}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
