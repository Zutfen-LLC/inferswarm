#!/usr/bin/env python3
"""Issue #189 R8-A terminal reduction (CPU-only, offline, stdlib only).

This reducer does not download a model, inspect a GPU, or execute a model.  It
turns the retained source-authority facts and the bounded fleet/runtime audit
into the one terminal permitted by Issue #189.  It fails closed if either
separate model authority drifts, if the smallest recorded representation is
not the complete split set, or if the conclusion is changed from the runtime
prerequisite without a separately recorded runtime qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AREA = "docs/investigations/qwen38-flash-next-r8-a"
SOURCE = f"{AREA}/source-findings.md"
OUTPUT = f"{AREA}/terminal-reduction.json"

OFFICIAL_REVISION = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
GGUF_REVISION = "38bb39ee97821de2c9009abb7e93950eec396e66"
SMALLEST_COMPLETE_GGUF_BYTES = 72_546_461_344
SMALLEST_COMPLETE_GGUF_FILES = 3
VERIFIED_NVIDIA_WEIGHT_BYTES = 72 * 1024**3


def canonical_bytes(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reduction_document(root: Path = ROOT) -> dict:
    """Derive the R8-A terminal only from retained, static inputs."""
    source = root / SOURCE
    if not source.is_file():
        raise ValueError("ISSUE189_FAIL: source-authority record is missing")
    text = source.read_text(encoding="utf-8")
    for expected in (OFFICIAL_REVISION, GGUF_REVISION,
                     "UD-IQ1_S", "72,546,461,344", "R8-A"):
        if expected not in text:
            raise ValueError(f"ISSUE189_FAIL: source-authority fact missing: {expected}")

    # The full set is required: a single first split is not a representation.
    if SMALLEST_COMPLETE_GGUF_FILES != 3:
        raise ValueError("ISSUE189_FAIL: split inventory is not complete")
    headroom = VERIFIED_NVIDIA_WEIGHT_BYTES - SMALLEST_COMPLETE_GGUF_BYTES
    if headroom <= 0:
        raise ValueError("ISSUE189_FAIL: no verified aggregate weight headroom")

    document = {
        "schema": "inferswarm.issue189.r8a-terminal/1",
        "issue": 189,
        "source_authority": {
            "official_revision": OFFICIAL_REVISION,
            "third_party_gguf_revision": GGUF_REVISION,
            "source_findings_sha256": sha256_file(source),
        },
        "representation": {
            "id": "unsloth-UD-IQ1_S",
            "complete_split_files": SMALLEST_COMPLETE_GGUF_FILES,
            "complete_split_bytes": SMALLEST_COMPLETE_GGUF_BYTES,
            "complete_split_gib": round(SMALLEST_COMPLETE_GGUF_BYTES / 1024**3, 2),
        },
        "fleet_fit": {
            "verified_nvidia_weight_bytes": VERIFIED_NVIDIA_WEIGHT_BYTES,
            "aggregate_weight_headroom_bytes": headroom,
            "capacity_feasible": "NOT_ESTABLISHED",
            "runtime_supported": "NOT_ESTABLISHED",
            "correctness_qualified": "NOT_ESTABLISHED",
            "economically_useful": "NOT_ESTABLISHED",
            "reason": "Aggregate VRAM is not a per-resource fit proof; the required compute, KV, recurrent, and staging allocations and a lawful cross-host execution path are unmeasured.",
        },
        "runtime_blockers": [
            {
                "id": "rpc-cross-host-correctness",
                "classification": "CORRECTNESS_BLOCKER",
                "source": "https://github.com/ggml-org/llama.cpp/issues/27993",
                "reason": "The required multi-resource shape needs cross-host RPC, while the recorded Qwen3.8 GGUF defect was deterministic long-prompt degeneration. The issue closure alone does not name a prospectively qualified commit or prove this fleet/mode safe.",
            },
            {
                "id": "ngram-materialization-control",
                "classification": "RUNTIME_BACKEND_PREREQUISITE",
                "source": "https://github.com/ggml-org/llama.cpp/issues/28256",
                "reason": "The retained conversion inventory does not establish an independently addressable N-gram GGUF materialization or an honest host-memory placement contract; small-read behavior is a separate performance risk.",
            },
        ],
        "terminal": "R8A_QWEN38_RUNTIME_PREREQUISITE",
        "terminal_reason": "The target remains architecturally informative, but no pinned llama.cpp commit plus bounded, single-slot, text-only, multi-resource correctness/residency protocol has been established for the only current-fleet-sized representation.",
        "non_claims": [
            "No Qwen3.8 inference, model download, GPU execution, serving run, or R8-B execution occurred.",
            "This reduction is not acceptance or execution authorization for R8-B.",
            "It does not infer per-tensor quantization, N-gram tensor bytes, or host/SSD suitability from aggregate GGUF bytes.",
        ],
    }
    document["record_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(document)).hexdigest()
    return document


def render(root: Path = ROOT) -> bytes:
    return json.dumps(reduction_document(root), indent=2, sort_keys=True).encode() + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / OUTPUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(render(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
