#!/usr/bin/env python3
"""Issue #195 R8-D v2: byte-exact true-greedy ladder runner (correctness
producer). Supersedes the v1 producer defect: every request/response is
retained byte-exactly with digests, plus prompt identity, fixture-ladder
identity observed at execution, producer identity, campaign, and git state.

Per case and repeat the record retains:
  case_id; complete prompt token ID array sent; prompt token count;
  sha256 of the canonical prompt-token representation;
  sha256 of the fixture ladder observed by the producer at execution;
  exact serialized HTTP request body bytes (base64) and their sha256;
  exact raw HTTP response body bytes (base64) and their sha256;
  parsed comparator fields (generated_tokens/content/stop_type/
  stopping_word/timings) parsed FROM the retained raw bytes;
  UTC start/end timestamps; campaign; producer sha256; git HEAD and
  clean/dirty state at execution.

The response is parsed from the retained raw response bytes only (no
second stream). Requests are serialized deterministically (sorted keys,
compact separators, ASCII) so the retained envelope reproduces/verifies
exactly.

Fail-closed gate: --arm candidate requires the v2 reference freeze to be
established (REFREEZE.json present, expected refreeze commit permitted,
frozen-reference digest pinned, producer pins green, worktree clean),
and records the refreeze commit + frozen-reference sha256 into every
execution record.

Usage:
  issue195_v2_run_ladder.py ref    <base-url> <out-json> <label> [--only CASE]
  issue195_v2_run_ladder.py cand   <base-url> <out-json> <label> [--only CASE]
    [--refreeze-commit SHA] [--frozen-ref-sha256 SHA]
"""
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from issue195_v2_authority import (  # noqa: E402
    CAMPAIGN_ID, FIXTURE_CASES, FIXTURE_LADDER_PATH, FIXTURE_LADDER_SHA256,
    FORBIDDEN_REQUEST_KEYS, REQUEST_CONTRACT, RUN_SCHEMA, V2_PRODUCERS)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha_b(b):
    return hashlib.sha256(b).hexdigest()


def serialize_request(prompt_ids):
    """Deterministic exact request body bytes for a case."""
    body = dict(REQUEST_CONTRACT)
    body["prompt"] = list(prompt_ids)
    for k in FORBIDDEN_REQUEST_KEYS:
        body.pop(k, None)
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def git_state():
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    return head, dirty == ""


def producer_sha():
    return sha_b(open(os.path.abspath(__file__), "rb").read())


def load_fixture(repo):
    with open(os.path.join(repo, FIXTURE_LADDER_PATH), "rb") as fh:
        raw = fh.read()
    return json.loads(raw), sha_b(raw)


def refreeze_state(repo):
    """Load v2 REFREEZE.json if present."""
    p = os.path.join(repo, "docs/investigations/qwen38-flash-next-r8-d-v2",
                     "evidence", "reference", "REFREEZE.json")
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def producer_pins_ok(repo):
    import importlib
    mod = importlib.import_module("issue195_v2_authority")
    return mod.producer_pins_ok(repo)


def fail_closed_gate(repo):
    """Candidate gate: fail closed unless the v2 prospective reference
    freeze is mechanically established."""
    problems = []
    # 1. worktree clean
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        problems.append("worktree dirty: " + dirty.splitlines()[0])
    # 2. REFREEZE.json present with pinned expectations
    rf = refreeze_state(repo)
    if rf is None:
        problems.append("v2 REFREEZE.json missing (reference not frozen)")
    else:
        # 3. expected refreeze commit is HEAD or a permitted descendant
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
        exp = rf["refreeze_commit"]
        if head == exp:
            pass  # exactly at the freeze commit
        else:
            anc = subprocess.run(
                ["git", "merge-base", "--is-ancestor", exp, head],
                cwd=repo, capture_output=True)
            if anc.returncode != 0:
                problems.append(f"HEAD {head[:12]} is not a descendant of "
                                f"reference-freeze commit {exp[:12]}")
            else:
                # descendant: no correctness-bearing changes allowed
                # after the refreeze commit EXCEPT the REFREEZE.json pin
                # file itself (which by contract is authored in the
                # commit immediately after the pushed reference freeze
                # and pins that commit's identity + digest)
                diff = subprocess.run(
                    ["git", "diff", "--name-only", exp, head], cwd=repo,
                    capture_output=True, text=True).stdout.split()
                from issue195_v2_authority import CORRECTNESS_PREFIXES
                PIN_FILE = ("docs/investigations/qwen38-flash-next-r8-d-v2"
                            "/evidence/reference/REFREEZE.json")
                bad = [p for p in diff if p != PIN_FILE and any(
                    p.startswith(pre) for pre in CORRECTNESS_PREFIXES)]
                if bad:
                    problems.append(
                        "correctness-bearing changes after refreeze: "
                        + ", ".join(bad[:3]))
    # 4. frozen-reference artifact digest matches the pin
    if rf is not None:
        frp = os.path.join(repo, "docs/investigations/qwen38-flash-next-r8-d-v2",
                           "evidence", "reference",
                           "frozen-reference.json")
        if not os.path.exists(frp):
            problems.append("frozen-reference.json missing")
        elif sha_b(open(frp, "rb").read()) != rf["frozen_reference_sha256"]:
            problems.append("frozen-reference.json digest != REFREEZE pin")
    # 5. producer pins green
    ok, why = producer_pins_ok(repo)
    if not ok:
        problems.append("producer pin failure: " + why)
    return (len(problems) == 0), problems, (rf or {})


def completion(base_url, prompt_ids):
    body_bytes = serialize_request(prompt_ids)
    req = urllib.request.Request(
        base_url + "/completion", data=body_bytes,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    started = utcnow()
    with urllib.request.urlopen(req, timeout=7200) as r:
        raw = r.read()          # the single response stream, retained
        status = r.status
    ended = utcnow()
    wall = time.time() - t0
    parsed = json.loads(raw)    # parsed FROM the retained raw bytes
    return {
        "request_bytes_b64": base64.b64encode(body_bytes).decode(),
        "request_sha256": sha_b(body_bytes),
        "response_bytes_b64": base64.b64encode(raw).decode(),
        "response_sha256": sha_b(raw),
        "http_status": status,
        "parsed_from_retained_bytes": {
            "generated_tokens": parsed.get("tokens"),
            "generated_text": parsed.get("content"),
            "stop_type": parsed.get("stop_type"),
            "stopping_word": parsed.get("stopping_word"),
            "timings": parsed.get("timings"),
        },
        "started_utc": started,
        "ended_utc": ended,
        "wall_s": round(wall, 3),
    }


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("ref", "cand"):
        print(__doc__)
        return 2
    arm, base, out_path, label = a[0], a[1], a[2], a[3]
    only = None
    if "--only" in a:
        i = a.index("--only")
        only = a[i + 1]
        a = a[:i] + a[i + 2:]

    fx, fx_sha = load_fixture(REPO)
    if fx_sha != FIXTURE_LADDER_SHA256:
        print("FATAL: fixture ladder sha mismatch", fx_sha)
        return 3

    gate = None
    if arm == "cand":
        ok, problems, rf = fail_closed_gate(REPO)
        if not ok:
            print("FATAL: candidate fail-closed gate FAILED:")
            for p in problems:
                print("  -", p)
            return 4
        gate = {
            "gate_passed": True,
            "refreeze_commit": rf.get("refreeze_commit"),
            "frozen_reference_sha256": rf.get("frozen_reference_sha256"),
            "producer_pins_ok": True,
        }

    head, clean = git_state()
    psha = producer_sha()
    results = []
    for case in fx["cases"]:
        cid = case["case_id"]
        if only and cid != only:
            continue
        if cid not in FIXTURE_CASES:
            continue
        ids = list(case["prompt_token_ids"])
        rec = completion(base, ids)
        rec.update({
            "case_id": cid,
            "prompt_token_ids": ids,
            "prompt_token_count": len(ids),
            "prompt_token_ids_sha256": sha_b(
                json.dumps(ids, separators=(",", ":")).encode()),
            "fixture_ladder_sha256_at_execution": fx_sha,
        })
        results.append(rec)
        p = rec["parsed_from_retained_bytes"]
        print(json.dumps({
            "case_id": cid, "prompt_len": rec["prompt_token_count"],
            "generated_tokens": p["generated_tokens"],
            "stop_type": p["stop_type"],
            "request_sha256": rec["request_sha256"][:16],
            "response_sha256": rec["response_sha256"][:16],
            "wall_s": rec["wall_s"]}))

    doc = {
        "schema": RUN_SCHEMA,
        "campaign": CAMPAIGN_ID,
        "arm": "reference" if arm == "ref" else "candidate",
        "label": label,
        "base_url": base,
        "started_utc": results[0]["started_utc"] if results else utcnow(),
        "ended_utc": results[-1]["ended_utc"] if results else utcnow(),
        "git_head": head,
        "git_clean": clean,
        "producer_sha256": psha,
        "producer_path": "scripts/issue195_v2_run_ladder.py",
        "request_contract": REQUEST_CONTRACT,
        "fixture_ladder_sha256": fx_sha,
        "sampler_gate": gate,
        "results": results,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out_path)


if __name__ == "__main__":
    sys.exit(main())
