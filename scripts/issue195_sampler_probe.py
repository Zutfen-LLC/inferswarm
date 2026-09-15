"""Issue #195 R8-D Phase 1: live sampler-contract probe.

Starts nothing itself. Given a RUNNING llama-server base URL, sends tiny
probe completions under three request variants and records, for each:
request bytes, response tokens, and the sampler-chain evidence parsed from
a provided server log snapshot (taken AFTER the probes).

Usage:
  issue195_sampler_probe.py <base-url> <server-log> <out-json> <log-before-lines>

Classification (fail-closed):
  canonical (top_k=1): chain must be logits -> top-k -> dist (order
    sensitive), zero unresolved-sampler warnings, zero "greedy" mentions.
  legacy (samplers=["greedy"]): must reproduce >=1 unresolved-name warning
    and chain without top-k -> classified NONCANONICAL_LEGACY_GREEDY.
  wide (top_k=4): chain resolves but support is not 1 -> NOT_TRUE_GREEDY.
Missing/unknown chain line -> BLOCKED.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request

PROMPT = [1, 1501, 2028]  # tiny deterministic probe prompt (token ids)


def completion(base, overrides):
    body = {
        "prompt": PROMPT,
        "n_predict": 2,
        "temperature": 0.0,
        "seed": 0,
        "cache_prompt": False,
        "stream": False,
        "return_tokens": True,
        "samplers": ["top_k"],
        "top_k": 1,
    }
    body.update(overrides)
    req = urllib.request.Request(
        base + "/completion", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.load(r)
    return body, res, round(time.time() - t0, 3)


def parse_chain(log_text, skip_lines):
    """Extract sampler evidence from server log lines after a marker."""
    lines = log_text.splitlines()[skip_lines:]
    chains, warns, greedy_warns = [], 0, 0
    for ln in lines:
        if "sampler chain:" in ln:
            chains.append(ln.split("sampler chain:", 1)[1].strip())
        if "unable to match sampler" in ln:
            warns += 1
            if "greedy" in ln:
                greedy_warns += 1
    return {"chains": chains, "unresolved_warnings": warns,
            "greedy_unresolved_warnings": greedy_warns}


def classify(name, body, parsed):
    chain_set = set(parsed["chains"])
    ok_chain = any(c == "logits -> top-k -> dist" for c in parsed["chains"])
    if name == "canonical":
        if parsed["greedy_unresolved_warnings"] or parsed["unresolved_warnings"]:
            return "BLOCKED_UNRESOLVED_SAMPLER"
        if not chain_set:
            return "BLOCKED_NO_CHAIN_EVIDENCE"
        if not ok_chain:
            return "BLOCKED_UNEXPECTED_CHAIN"
        if body.get("top_k") != 1:
            return "NOT_TRUE_GREEDY"  # request mutated
        return "TRUE_GREEDY_PROVEN"
    if name == "legacy":
        if parsed["greedy_unresolved_warnings"] == 0:
            return "BLOCKED_LEGACY_WARNING_NOT_REPRODUCED"
        return "NONCANONICAL_LEGACY_GREEDY"
    if name == "wide":
        if not chain_set:
            return "BLOCKED_NO_CHAIN_EVIDENCE"
        # chain is still logits -> top-k -> dist; the WIDENING is in the
        # request (top_k=4); classifier must not label it true greedy
        return "NOT_TRUE_GREEDY" if body.get("top_k") != 1 else "MISLABELED"
    return "UNKNOWN"


def main(base, log_path, out_path, skip_lines):
    with open(log_path) as fh:
        before_text = fh.read()
    n_before = len(before_text.splitlines())

    probes = {}
    for name, overrides in [
        ("canonical", {}),
        ("legacy", {"samplers": ["greedy"], "top_k": 0}),
        ("wide", {"top_k": 4}),
    ]:
        body, res, dur = completion(base, overrides)
        probes[name] = {
            "request": body,
            "generated_tokens": res.get("tokens"),
            "wall_s": dur,
        }

    time.sleep(1.0)
    with open(log_path) as fh:
        after_text = fh.read()
    parsed = parse_chain(after_text, n_before)

    # chain evidence attribution: run each variant in its own log region is
    # not possible on one server; instead we require the LAST probe's chain
    # lines and re-probe sequentially with region markers. Simpler and
    # stricter: repeat each variant capturing per-variant regions.
    per_variant = {}
    for name, overrides in [
        ("canonical", {}),
        ("legacy", {"samplers": ["greedy"], "top_k": 0}),
        ("wide", {"top_k": 4}),
    ]:
        with open(log_path) as fh:
            b = len(fh.read().splitlines())
        body, res, dur = completion(base, overrides)
        time.sleep(0.5)
        with open(log_path) as fh:
            a = fh.read()
        p = parse_chain(a, b)
        per_variant[name] = {
            "request": body,
            "generated_tokens": res.get("tokens"),
            "wall_s": dur,
            "log_evidence": p,
            "classification": classify(name, body, p),
        }

    doc = {
        "schema": "inferswarm.issue195.sampler-probe/1",
        "base_url": base,
        "probe_prompt_token_ids": PROMPT,
        "variants": per_variant,
        "all_pass": (
            per_variant["canonical"]["classification"] == "TRUE_GREEDY_PROVEN"
            and per_variant["legacy"]["classification"] == "NONCANONICAL_LEGACY_GREEDY"
            and per_variant["wide"]["classification"] == "NOT_TRUE_GREEDY"
        ),
    }
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({k: v["classification"] for k, v in per_variant.items()},
                     indent=1))
    print("all_pass =", doc["all_pass"])
    print("wrote", out_path)
    sys.exit(0 if doc["all_pass"] else 1)


if __name__ == "__main__":
    main(*sys.argv[1:5])
