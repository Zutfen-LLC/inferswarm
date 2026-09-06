#!/usr/bin/env python3
"""Build the fixed issue #109 historical prompt and token exclusion inventory."""
from __future__ import annotations

import json
from pathlib import Path

from issue74_methodology import canonical_json_bytes, sha256_bytes, sha256_file

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/qualification/gemma4-12b-it-v5/manifests/historical-exclusion-inventory.json"

SOURCES = (
    ("c74", "docs/qualification/gemma4-12b-it-v1/manifests/calibration-corpus.json", "cases"),
    ("p74", "docs/qualification/gemma4-12b-it-v1/manifests/margin-stress-pool.json", "cases"),
    ("h74", "docs/qualification/gemma4-12b-it-v1/manifests/sealed-holdout-commitment.json", "cells"),
    ("p76", "docs/qualification/gemma4-12b-it-v2/manifests/margin-stress-pool.json", "cases"),
    ("c86", "docs/qualification/gemma4-12b-it-v3/manifests/calibration-corpus.json", "cases"),
    ("p86", "docs/qualification/gemma4-12b-it-v3/manifests/stress-pool.json", "cases"),
    ("h86", "docs/qualification/gemma4-12b-it-v3/manifests/sealed-holdout-commitment.json", "cells"),
    ("c95", "docs/qualification/gemma4-12b-it-v4/manifests/calibration-corpus.json", "cases"),
    ("p95", "docs/qualification/gemma4-12b-it-v4/manifests/stress-pool.json", "cases"),
    ("h95", "docs/qualification/gemma4-12b-it-v4/manifests/sealed-holdout-commitment.json", "cells"),
)


def build() -> dict:
    identities, sources = set(), []
    for name, relative, key in SOURCES:
        path = ROOT / relative
        rows = json.loads(path.read_text(encoding="utf-8"))[key]
        sources.append({"artifact": name, "path": relative, "sha256": sha256_file(path)})
        identities.update((row["prompt_sha256"], row["token_ids_sha256"]) for row in rows)
    frozen = [{"prompt_sha256": prompt, "token_ids_sha256": tokens}
              for prompt, tokens in sorted(identities)]
    return {
        "schema": "inferswarm.issue109.v5-historical-exclusion-inventory/1",
        "rule": "reject a v5 predictive candidate if either identity occurs in this fixed inventory",
        "sources": sources,
        "identity_count": len(frozen),
        "identities": frozen,
        "identity_set_sha256": sha256_bytes(canonical_json_bytes(frozen)),
    }


if __name__ == "__main__":
    OUT.write_bytes(canonical_json_bytes(build()))
