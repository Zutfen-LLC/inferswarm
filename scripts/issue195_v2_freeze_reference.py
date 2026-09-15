#!/usr/bin/env python3
"""Issue #195 R8-D v2: prospective reference freeze.

Consumes the v2 reference run records (ref-run-{1,2,3}.json produced by
issue195_v2_run_ladder.py --arm ref), requires the exact 4-case x3
deterministic contract, verifies each run's internal identity (request
bytes == deterministic serialization of contract+prompt; response parsed
from retained bytes; fixture/prompt digests), and emits:

  v2/evidence/reference/frozen-reference.json  — per-case frozen outputs
    (tokens/stop/stopping_word), request+response digests per repeat,
    reference run-file digests, determinism proof, campaign identity,
    producer identity.

It does NOT author REFREEZE.json. REFREEZE.json (the commit-side pin:
refreeze_commit + frozen_reference_sha256) is written in a second step
by --pin mode after the reference-freeze commit exists. Order of
operations at the reference-freeze commit:

  1. run reference arm (3x) with the v2 producer
  2. python3 scripts/issue195_v2_freeze_reference.py freeze
       -> validates + writes frozen-reference.json
  3. git add frozen-reference.json + evidence; commit "v2 reference
     freeze"; PUSH (this is the immutable reference-freeze commit)
  4. python3 scripts/issue195_v2_freeze_reference.py --pin <sha>
          [--frozen-ref-sha256 <sha>]
       -> writes REFREEZE.json recording the pushed commit + digest
  5. git add REFREEZE.json; commit; push  (REFREEZE.json records the
     reference-freeze commit SHA; candidate gate verifies ancestry)

The candidate fail-closed gate in issue195_v2_run_ladder.py verifies:
REFREEZE.json exists; HEAD == refreeze commit or descendant with no
correctness-bearing diffs; frozen-reference.json digest == pin; producer
pins green; worktree clean.

Mechanical pre-freeze-before-candidate proof (reducer): every candidate
run record contains refreeze_commit + frozen_reference_sha256 sampled
from REFREEZE.json at execution; git history proves refreeze commit is
an ancestor of each candidate run's git_head; refreeze commit's tree
contains the exact frozen-reference.json bytes matching the pin.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from issue195_v2_authority import (  # noqa: E402
    CAMPAIGN_ID, FIXTURE_CASES, FIXTURE_LADDER_SHA256, REFERENCE_REPEATS,
    REQUEST_CONTRACT)
from issue195_v2_run_ladder import (  # noqa: E402
    serialize_request, sha_b, utcnow)

V2 = os.path.join(REPO, "docs/investigations/qwen38-flash-next-r8-d-v2")
REF = os.path.join(V2, "evidence", "reference")


def load(p):
    with open(p) as fh:
        return json.load(fh)


def case_from_run(run, cid):
    for r in run["results"]:
        if r["case_id"] == cid:
            return r
    raise KeyError(cid)


def verify_run(run_path, problems, strict_prompt=True):
    """Verify one reference run record end-to-end."""
    d = load(run_path)
    if d.get("schema") != "inferswarm.issue195.ladder-run-v2/2":
        problems.append(f"{run_path}: wrong schema")
    if d.get("campaign") != CAMPAIGN_ID:
        problems.append(f"{run_path}: wrong campaign")
    if d.get("arm") != "reference":
        problems.append(f"{run_path}: wrong arm")
    if d.get("fixture_ladder_sha256") != FIXTURE_LADDER_SHA256:
        problems.append(f"{run_path}: fixture ladder digest mismatch")
    if d.get("request_contract") != REQUEST_CONTRACT:
        problems.append(f"{run_path}: request contract drift")
    for r in d["results"]:
        cid = r["case_id"]
        import base64
        reqb = base64.b64decode(r["request_bytes_b64"])
        if sha_b(reqb) != r["request_sha256"]:
            problems.append(f"{run_path}/{cid}: request digest mismatch")
        respb = base64.b64decode(r["response_bytes_b64"])
        if sha_b(respb) != r["response_sha256"]:
            problems.append(f"{run_path}/{cid}: response digest mismatch")
        # request body must be the deterministic serialization of
        # contract + the retained prompt IDs
        want = serialize_request(r["prompt_token_ids"])
        if reqb != want:
            problems.append(
                f"{run_path}/{cid}: request bytes != deterministic "
                "serialization of contract+prompt")
        # response fields parsed from retained bytes
        parsed = json.loads(respb)
        p = r["parsed_from_retained_bytes"]
        for k in ("generated_tokens", "generated_text", "stop_type",
                  "stopping_word"):
            if p.get(k) != parsed.get("tokens" if k == "generated_tokens"
                                      else k if k != "generated_text"
                                      else "content"):
                problems.append(f"{run_path}/{cid}: parsed field {k} "
                                "not from retained bytes")
        if strict_prompt:
            if sha_b(json.dumps(r["prompt_token_ids"],
                                separators=(",", ":")).encode()) != \
                    r["prompt_token_ids_sha256"]:
                problems.append(f"{run_path}/{cid}: prompt digest mismatch")
    return d


def cmd_freeze(problems):
    runs = []
    for i in range(1, REFERENCE_REPEATS + 1):
        rp = os.path.join(REF, f"ref-run-{i}.json")
        if not os.path.exists(rp):
            problems.append(f"missing {rp}")
            return None
        runs.append(verify_run(rp, problems))
    if problems:
        return None
    # determinism: tokens+stop byte-identical across repeats
    for cid in FIXTURE_CASES:
        vals = []
        for d in runs:
            r = case_from_run(d, cid)
            vals.append((r["parsed_from_retained_bytes"]["generated_tokens"],
                         r["parsed_from_retained_bytes"]["stop_type"],
                         r["parsed_from_retained_bytes"]["stopping_word"]))
        if len(set(map(json.dumps, vals))) != 1:
            problems.append(f"{cid}: non-deterministic across repeats")
    if problems:
        return None
    frozen = {
        "schema": "inferswarm.issue195.frozen-reference/2",
        "campaign": CAMPAIGN_ID,
        "created_utc": utcnow(),
        "fixture_ladder_sha256": FIXTURE_LADDER_SHA256,
        "request_contract": REQUEST_CONTRACT,
        "cases": {},
        "reference_run_file_sha256": {
            f"ref-run-{i}.json": sha_b(open(
                os.path.join(REF, f"ref-run-{i}.json"), "rb").read())
            for i in range(1, REFERENCE_REPEATS + 1)},
        "determinism": "verified across 3 clean repeats per case",
    }
    for cid in FIXTURE_CASES:
        r0 = case_from_run(runs[0], cid)
        p0 = r0["parsed_from_retained_bytes"]
        frozen["cases"][cid] = {
            "prompt_token_count": r0["prompt_token_count"],
            "prompt_token_ids_sha256": r0["prompt_token_ids_sha256"],
            "generated_tokens": p0["generated_tokens"],
            "generated_text": p0["generated_text"],
            "stop_type": p0["stop_type"],
            "stopping_word": p0["stopping_word"],
            "request_sha256_per_repeat": [
                case_from_run(d, cid)["request_sha256"] for d in runs],
            "response_sha256_per_repeat": [
                case_from_run(d, cid)["response_sha256"] for d in runs],
        }
    out = os.path.join(REF, "frozen-reference.json")
    with open(out, "w") as fh:
        json.dump(frozen, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out)
    print("frozen-reference sha256:", sha_b(open(out, "rb").read()))
    return out


def cmd_pin(args, problems):
    rf_path = os.path.join(REF, "REFREEZE.json")
    fr_path = os.path.join(REF, "frozen-reference.json")
    if not os.path.exists(fr_path):
        problems.append("frozen-reference.json missing")
        return None
    fr_sha = sha_b(open(fr_path, "rb").read())
    if args.frozen_ref_sha256 and args.frozen_ref_sha256 != fr_sha:
        problems.append("--frozen-ref-sha256 does not match on-disk bytes")
    # verify the refreeze commit exists and contains the exact bytes
    show = subprocess.run(
        ["git", "show", f"{args.refreeze_commit}:"
         + "docs/investigations/qwen38-flash-next-r8-d-v2/evidence/"
         "reference/frozen-reference.json"],
        cwd=REPO, capture_output=True, text=True)
    if show.returncode != 0:
        problems.append("refreeze commit does not contain "
                        "frozen-reference.json")
    elif sha_b(show.stdout.encode()) != fr_sha:
        problems.append("refreeze-commit frozen-reference bytes != local")
    doc = {
        "schema": "inferswarm.issue195.refreeze-pin/1",
        "campaign": CAMPAIGN_ID,
        "created_utc": utcnow(),
        "refreeze_commit": args.refreeze_commit,
        "frozen_reference_sha256": fr_sha,
    }
    with open(rf_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", rf_path, "pinning commit", args.refreeze_commit[:12],
          "frozen-reference", fr_sha[:16])
    return rf_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="freeze",
                    choices=["freeze", "pin"])
    ap.add_argument("--pin", dest="pin_commit", default=None,
                    help="legacy alias: write REFREEZE.json for commit")
    ap.add_argument("--refreeze-commit")
    ap.add_argument("--frozen-ref-sha256")
    args = ap.parse_args()
    if args.pin_commit:
        args.refreeze_commit = args.pin_commit
        args.mode = "pin"
    problems = []
    if args.mode == "freeze":
        out = cmd_freeze(problems)
    else:
        if not args.refreeze_commit:
            print("FATAL: pin mode requires --refreeze-commit")
            return 2
        out = cmd_pin(args, problems)
    if problems:
        print("FATAL: reference freeze problems:")
        for p in problems:
            print("  -", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
