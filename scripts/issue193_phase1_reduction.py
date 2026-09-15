#!/usr/bin/env python3
"""Issue #193 Phase 1 reducer: accepted-failure sentinel reproduction check.

Fail-closed derivation from retained arm-run bytes:
- every R arm must equal the accepted R8-B reference case-256 tokens;
- every C arm must equal the accepted R8-B candidate case-256 tokens;
- the restart arm must equal the C tokens;
- placements (from retained server logs) must match the accepted R8-B
  buffer-size vectors before a C arm is counted as a reproduction.

Emits phase1-reproduction.json. Exits nonzero on any failure.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts"))
from issue193_r8c_authority import (  # noqa: E402
    R8B_CASE256_CANDIDATE_TOKENS,
    R8B_CASE256_REFERENCE_TOKENS,
    SENTINEL_CASE,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
EV = os.path.join(_HERE, "..", "docs", "investigations", "qwen38-flash-next-r8-c", "evidence", "phase1-reproduction")

# Accepted R8-B placement vectors (MiB, from accepted candidate-server.log /
# reference-server.log load_tensors "model buffer size" lines, sorted).
R8B_REF_PLACEMENT = sorted([19821.96, 21460.90, 9620.55, 9808.56, 27465.95])
R8B_CAND_PLACEMENT = sorted([341.02, 6796.90, 6518.70, 13493.79, 7761.99, 6796.90, 27465.95])


def placement_from_log(path: str):
    sizes = []
    with open(path, errors="replace") as fh:
        for line in fh:
            m = re.search(r"model buffer size =\s*([0-9.]+) MiB", line)
            if m:
                sizes.append(float(m.group(1)))
    return sorted(sizes)


def tokens_of(path: str):
    doc = json.load(open(path))
    for r in doc["results"]:
        if r["case_id"] == SENTINEL_CASE:
            return r["generated_tokens"]
    raise SystemExit(f"{path}: sentinel {SENTINEL_CASE} missing")


def main():
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    ref_tokens = tokens_of(os.path.join(EV, "r8c-R-run1.json"))
    check("R-run1 == accepted R8-B reference tokens",
          ref_tokens == R8B_CASE256_REFERENCE_TOKENS, str(ref_tokens))
    for f in ("r8c-R-run2.json", "r8c-R-run3.json"):
        check(f"{f} == accepted reference tokens",
              tokens_of(os.path.join(EV, f)) == R8B_CASE256_REFERENCE_TOKENS, "")

    # placements
    ref_place = placement_from_log(os.path.join(EV, "r8c-R-server.log"))
    check("R placement == accepted R8-B reference placement",
          ref_place == R8B_REF_PLACEMENT, str(ref_place))

    c_tokens = tokens_of(os.path.join(EV, "r8c-C-run2.json"))
    check("C-run2 == accepted R8-B candidate tokens",
          c_tokens == R8B_CASE256_CANDIDATE_TOKENS, str(c_tokens))
    check("C-run3 == accepted R8-B candidate tokens",
          tokens_of(os.path.join(EV, "r8c-C-run3.json")) == R8B_CASE256_CANDIDATE_TOKENS, "")
    check("C-restart == accepted R8-B candidate tokens",
          tokens_of(os.path.join(EV, "r8c-C-restart.json")) == R8B_CASE256_CANDIDATE_TOKENS, "")

    c_place = placement_from_log(os.path.join(EV, "r8c-C-server.log"))
    check("C placement == accepted R8-B candidate placement",
          c_place == R8B_CAND_PLACEMENT, str(c_place))

    # the invalid first C attempt is retained but explicitly NOT a reproduction:
    inv = json.load(open(os.path.join(EV, "r8c-C-run1-invalid-topology.json")))
    check("invalid-topology C attempt retained and excluded",
          inv["results"][0]["case_id"] == SENTINEL_CASE
          and inv.get("label") == "arm-R8C-C-run1", "")

    ok = all(c["ok"] for c in checks)
    doc = {
        "schema": "inferswarm.issue193.phase1-reproduction/1",
        "sentinel": SENTINEL_CASE,
        "checks": checks,
        "reproduced": ok,
        "note": (
            "All reproduction arms executed under the exact pinned authority "
            "(binaries/model/split re-hashed at freeze). The first C launch "
            "ran while the reference server still held inferswarm01's GPUs, "
            "producing a different placement; retained as "
            "r8c-C-run1-invalid-topology.json and excluded from reproduction."
        ),
    }
    out = os.path.join(_HERE, "..", "docs", "investigations", "qwen38-flash-next-r8-c", "phase1-reproduction.json")
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({"reproduced": ok, "failed": [c["check"] for c in checks if not c["ok"]]}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
