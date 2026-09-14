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
CENSUS = f"{AREA}/gguf-census.json"
OUTPUT = f"{AREA}/terminal-reduction.json"

OFFICIAL_REVISION = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
GGUF_REVISION = "38bb39ee97821de2c9009abb7e93950eec396e66"
SMALLEST_COMPLETE_GGUF_BYTES = 72_546_461_344
SMALLEST_COMPLETE_GGUF_FILES = 3
VERIFIED_NVIDIA_WEIGHT_BYTES = 72 * 1024**3
RUNTIME_AUDIT_REVISION = "1bc7a5af0d14b1fb72f266abbd1237b394187115"
RPC_REPRODUCER_REVISION = "17252c769a63c1cb650ce98ae309cf4de0da7778"
RPC_REPORTER_REBUILD_REVISION = "cc231cb0da565440cf6a3e5b55dfeba477972cb6"
RPC_FIX_REVISION = "a273d22e142b9ad253a09d7b76d4d24ba64eb9bc"
UD_IQ1_S_MEMBERS = (
    ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf", 10_946_624),
    ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf", 49_990_818_368),
    ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf", 22_544_696_352),
)


def canonical_bytes(document: dict) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_census(root: Path) -> dict:
    path = root / CENSUS
    if not path.is_file():
        raise ValueError("ISSUE189_FAIL: object-level GGUF census is missing")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schema") != "inferswarm.issue189.gguf-census/1"
            or document.get("revision") != GGUF_REVISION):
        raise ValueError("ISSUE189_FAIL: GGUF census authority drift")
    files = document.get("files")
    if not isinstance(files, list) or len(files) != 56:
        raise ValueError("ISSUE189_FAIL: incomplete GGUF object inventory")
    indexed = {row[0]: row for row in files
               if isinstance(row, list) and len(row) == 3
               and isinstance(row[0], str) and isinstance(row[1], int)
               and isinstance(row[2], str) and len(row[2]) == 64}
    if len(indexed) != 56:
        raise ValueError("ISSUE189_FAIL: malformed GGUF object identity")
    members = [indexed.get(name) for name, _ in UD_IQ1_S_MEMBERS]
    if any(member is None for member in members):
        raise ValueError("ISSUE189_FAIL: UD-IQ1_S split member missing")
    if [member[1] for member in members] != [size for _, size in UD_IQ1_S_MEMBERS]:
        raise ValueError("ISSUE189_FAIL: UD-IQ1_S split size drift")
    if sum(member[1] for member in members) != SMALLEST_COMPLETE_GGUF_BYTES:
        raise ValueError("ISSUE189_FAIL: UD-IQ1_S split sum drift")
    return document


def reduction_document(root: Path = ROOT) -> dict:
    """Derive the R8-A terminal only from retained, static inputs."""
    source = root / SOURCE
    if not source.is_file():
        raise ValueError("ISSUE189_FAIL: source-authority record is missing")
    text = source.read_text(encoding="utf-8")
    for expected in (OFFICIAL_REVISION, GGUF_REVISION, RUNTIME_AUDIT_REVISION,
                     RPC_REPRODUCER_REVISION, RPC_FIX_REVISION, "R8-A"):
        if expected not in text:
            raise ValueError(f"ISSUE189_FAIL: source-authority fact missing: {expected}")

    census = load_census(root)
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
            "gguf_census_sha256": sha256_file(root / CENSUS),
        },
        "representation": {
            "id": "unsloth-UD-IQ1_S",
            "complete_split_files": SMALLEST_COMPLETE_GGUF_FILES,
            "complete_split_bytes": SMALLEST_COMPLETE_GGUF_BYTES,
            "complete_split_gib": round(SMALLEST_COMPLETE_GGUF_BYTES / 1024**3, 2),
            "object_identities": [row[2] for row in
                                  [next(row for row in census["files"] if row[0] == name)
                                   for name, _ in UD_IQ1_S_MEMBERS]],
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
                "affected_runtime_revision": RPC_REPRODUCER_REVISION,
                "reported_mode": "Metal layer-split cross-host RPC, UD-IQ4_XS, long prefill/decode beyond about 2K prompt tokens",
                "reported_rebuild_revision": RPC_REPORTER_REBUILD_REVISION,
                "reported_fix_revision": RPC_FIX_REVISION,
                "reason": "The reported fix does not qualify NVIDIA, UD-IQ1_S, this fleet, or the required exact layer/RPC shape.",
            },
            {
                "id": "ngram-materialization-control",
                "classification": "PERFORMANCE_ONLY_RISK",
                "source": "https://github.com/ggml-org/llama.cpp/issues/28256",
                "reason": "The NFS/FS-cache small-read report is performance-only; separately, no retained conversion control proves independently addressable N-gram materialization.",
            },
        ],
        "terminal": "R8A_QWEN38_RUNTIME_PREREQUISITE",
        "runtime_audit_revision": RUNTIME_AUDIT_REVISION,
        "terminal_reason": "The target remains architecturally informative, but no selected and qualified llama.cpp build plus bounded, text-only, single-slot, NVIDIA/cross-host layer-RPC correctness and residency protocol exists for the only current-fleet-sized representation.",
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
