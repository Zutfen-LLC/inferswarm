#!/usr/bin/env python3
"""Issue #191 R8-B Phase 4: derive and freeze the fixture ladder.

Uses the pinned reference llama-server /tokenize endpoint (exact same
tokenizer as both arms) to derive exact prompt token IDs for four cases
(~256 / ~1024 / ~3072 / ~4096 rendered tokens), then freezes them to
evidence/reference/fixture-ladder.json BEFORE any candidate output.

Prompt construction is deterministic: fixed literal header per case plus a
repeating numeral sentence, truncated by TOKENIZER feedback (not guessed):
we tokenize, measure, and extend until the rendered length lands within
the target band, then record exact IDs.
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8301"
TARGETS = {"case-256": (250, 264), "case-1024": (1018, 1032),
           "case-3072": (3066, 3080), "case-4096": (4090, 4104)}
SENTENCE = "The lighthouse keeper counted forty-one waves before the foghorn answered twice. "
HEADERS = {
    "case-256": "You are recording a tide log. ",
    "case-1024": "You are summarizing a harbor survey. ",
    "case-3072": "You are compiling the annual coastal report. ",
    "case-4096": "You are drafting the final navigation notice. ",
}
# Continuation cue: forces multi-token decode instead of immediate EOS on
# otherwise "complete-looking" text. Same cue for every case.
CUE = "The next log entry begins as follows:"


def tokenize(content):
    body = json.dumps({"content": content, "add_special": True}).encode()
    req = urllib.request.Request(BASE + "/tokenize", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["tokens"]


def build(case):
    lo, hi = TARGETS[case]
    head = HEADERS[case]
    n = 1
    while True:
        content = head + SENTENCE * n + " " + CUE
        ids = tokenize(content)
        if len(ids) > hi:
            raise SystemExit(f"{case}: overshot target band (n={n}, len={len(ids)})")
        if len(ids) >= lo:
            return content, ids, n
        n += 1


def main(out_path):
    cases = []
    for case in ("case-256", "case-1024", "case-3072", "case-4096"):
        content, ids, n = build(case)
        cases.append({
            "case_id": case,
            "prompt_text": content,
            "prompt_token_ids": ids,
            "rendered_length": len(ids),
            "sentence_repeats": n,
            "target_band": list(TARGETS[case]),
        })
        print(f"{case}: {len(ids)} tokens ({n} repeats)", file=sys.stderr)
    doc = {
        "schema": "inferswarm.issue191.fixture-ladder/1",
        "derivation": "llama-server /tokenize on the frozen reference instance (pinned build b29c606e, exact accepted GGUF tokenizer metadata), add_special=true",
        "committed_tokens_per_case": 8,
        "sampling": {"temperature": 0.0, "greedy": True, "seed": 0},
        "cases": cases,
    }
    with open(out_path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out_path)


if __name__ == "__main__":
    main(sys.argv[1])
