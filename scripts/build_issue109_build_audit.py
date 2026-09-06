#!/usr/bin/env python3
"""Build the CPU/static Issue #109 v5 provenance audit."""
from __future__ import annotations

from pathlib import Path

from issue74_methodology import canonical_json_bytes, sha256_file

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/qualification/gemma4-12b-it-v5/manifests/build-audit.json"
TOKENIZER_SHA256 = "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"


def build() -> dict:
    names = (
        "build_issue109_build_audit.py", "build_issue109_disjointness.py",
        "build_issue109_historical_exclusion.py", "build_issue109_schemas.py",
        "commit_issue109_holdout.py", "commit_issue109_stress_selection.py",
        "generate_issue109_corpora.py", "issue109_v5_contract.py",
        "issue109_v5_methodology.py", "issue109_v5_methodology_freeze.py",
        "issue109_v5_thresholds.py", "select_issue109_margin_stress_v5.py",
        "validate_issue109_prerequisites.py", "verify_issue109_v5_unseal.py",
    )
    return {
        "schema": "inferswarm.issue109.v5-build-audit/2",
        "status": "CPU_STATIC_ONLY",
        "physical_execution": "PROHIBITED_AND_NOT_PERFORMED",
        "holdout_decryption": "PROHIBITED_AND_NOT_PERFORMED",
        "tokenizer_acquisition": {
            "repository": "google/gemma-4-12B-it",
            "provider": "Hugging Face official Google model repository",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "filename": "tokenizer.json",
            "sha256": TOKENIZER_SHA256,
            "verification": "SHA256_EXACT_MATCH",
        },
        "files": {f"scripts/{name}": sha256_file(ROOT / "scripts" / name) for name in names},
    }


if __name__ == "__main__":
    OUT.write_bytes(canonical_json_bytes(build()))
