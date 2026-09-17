#!/usr/bin/env python3
"""CPU-only, fail-closed Issue #209 runtime-substrate reduction.

This lane performs static source/accounting work only: it imports no model
runtime and does not download, convert, or execute a checkpoint. It fails
closed on predecessor, retained-source, producer, or evidence-manifest drift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = "docs/investigations/deepseek-v41-flash-r7-b"
R7A_TERMINAL = "docs/investigations/deepseek-v41-flash-r7-a/terminal-reduction.json"
R7A_MANIFEST = "docs/investigations/deepseek-v41-flash-r7-a/MANIFEST.sha256"
RUNTIME_AUTHORITY = f"{AREA}/runtime-authority.json"
EXTERNAL_SOURCE_EVIDENCE = f"{AREA}/external-source-evidence.json"
OUTPUT = f"{AREA}/terminal-reduction.json"
R7A_RETAINED_FILES = {
    "docs/investigations/deepseek-v41-flash-r7-a/external/LICENSE":
        "f2c6c602815669d292889e5be8c802f2ed950653b77999b1584e8e6aed25d040",
    "docs/investigations/deepseek-v41-flash-r7-a/external/inference/config.json":
        "2e84f45cf1dac8c7fcbb200e96667d4b913275690668ed496f24c7747207a809",
    "docs/investigations/deepseek-v41-flash-r7-a/external/inference/model.py":
        "4e9ae23620edc8028ccc5d5fef552ab7fdc7dcd6f79608754fe9f67644056f65",
}
INPUTS = (R7A_TERMINAL, R7A_MANIFEST, RUNTIME_AUTHORITY,
          EXTERNAL_SOURCE_EVIDENCE, *R7A_RETAINED_FILES)
R7A_REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"
R7A_TERMINAL_NAME = "R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE"
R7A_MANIFEST_SHA256 = "6730826a7c00b92cc88bda814583ccc6955370cde37d685261f764b5146e640c"
R7A_TERMINAL_SHA256 = "aee287f59199622b97bdf9862624f990416ee838eebea397e6a64d99526806dc"
TERMINAL = "R7B_RUNTIME_SUBSTRATE_PREREQUISITE"
OFFICIAL_GENERATE_SHA256 = "8668d67f7d108e32b90d50cb0d8606889ceb2219bfe95741d84e22f70768e9f0"
OFFICIAL_CONVERT_SHA256 = "035028340479145594a81d6084a8424e57363adf83c0d5983914783d95614d76"
VLLM_REVISION = "0eae9acd4d01574e12d4ecf6a0229813f7fdb799"
SGLANG_REVISION = "7ccbf5fd04f7ee23095fc38e49e749d58dc18282"
VLLM_SOURCE_SHA256 = "51e40463b6ce3a76ad64a09b6bbdf4688cae468d316f426d9d394fcff08b146e"
SGLANG_SOURCE_SHA256 = "b47a8f8b1c3e27a009d1c06648c0c8d1173b09fbb85530febcd06a5337ac6b43"


def _load(root: Path, relative: str) -> dict:
    try:
        return json.loads((root / relative).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"ISSUE209_FAIL: missing or malformed {relative}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reduction_document(root: Path = ROOT) -> dict:
    predecessor = _load(root, R7A_TERMINAL)
    authority = _load(root, RUNTIME_AUTHORITY)
    source_evidence = _load(root, EXTERNAL_SOURCE_EVIDENCE)
    if predecessor.get("terminal") != R7A_TERMINAL_NAME:
        raise ValueError("ISSUE209_FAIL: R7-A terminal drift")
    if predecessor.get("source_authority", {}).get("revision") != R7A_REVISION:
        raise ValueError("ISSUE209_FAIL: R7-A model revision drift")
    if _sha256(root / R7A_TERMINAL) != R7A_TERMINAL_SHA256:
        raise ValueError("ISSUE209_FAIL: R7-A terminal content drift")
    if _sha256(root / R7A_MANIFEST) != R7A_MANIFEST_SHA256:
        raise ValueError("ISSUE209_FAIL: R7-A manifest drift")
    for relative, expected in R7A_RETAINED_FILES.items():
        if _sha256(root / relative) != expected:
            raise ValueError("ISSUE209_FAIL: R7-A retained source drift")
    official_sources = source_evidence.get("official_reference", {})
    if official_sources.get("revision") != R7A_REVISION \
            or official_sources.get("parent_retained_files") != R7A_RETAINED_FILES:
        raise ValueError("ISSUE209_FAIL: official source authority drift")
    for field, expected, required in (
        ("generate_py", OFFICIAL_GENERATE_SHA256, "model{rank}-mp{world_size}.safetensors"),
        ("convert_py", OFFICIAL_CONVERT_SHA256, "model.safetensors.index.json"),
    ):
        record = official_sources.get(field, {})
        if record.get("sha256") != expected or required not in record.get("excerpt", ""):
            raise ValueError("ISSUE209_FAIL: official source evidence drift")
    predicates = authority.get("mandatory_predicates")
    if not isinstance(predicates, list) or len(predicates) != 10:
        raise ValueError("ISSUE209_FAIL: incomplete selection rubric")
    candidates = authority.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise ValueError("ISSUE209_FAIL: candidate disposition inventory drift")
    official = candidates[0]
    if official.get("revision") != R7A_REVISION:
        raise ValueError("ISSUE209_FAIL: runtime revision drift")
    evidence = official.get("source_evidence", {})
    if evidence.get("generate_py", {}).get("sha256") != OFFICIAL_GENERATE_SHA256 \
            or evidence.get("convert_py", {}).get("sha256") != OFFICIAL_CONVERT_SHA256:
        raise ValueError("ISSUE209_FAIL: runtime source identity drift")
    loader = official.get("loader_contract")
    if loader == "official-sharded-safetensors-index":
        raise ValueError("ISSUE209_FAIL: candidate disposition contradicts loader contract")
    if loader != "converted-model{rank}-mp{world_size}-safetensors":
        raise ValueError("ISSUE209_FAIL: unrecognized loader contract")
    if official.get("disposition") != "REJECTED" \
            or "p4_native_official_sharded_safetensors" not in official.get("failed_predicates", []):
        raise ValueError("ISSUE209_FAIL: official runtime rejection is not fail-closed")
    third_party = source_evidence.get("third_party_candidates", {})
    vllm_source = third_party.get("vllm", {})
    sglang_source = third_party.get("sglang", {})
    if vllm_source.get("revision") != VLLM_REVISION \
            or vllm_source.get("sha256") != VLLM_SOURCE_SHA256 \
            or "for name, loaded_weight in weights:" not in vllm_source.get("excerpt", "") \
            or sglang_source.get("revision") != SGLANG_REVISION \
            or sglang_source.get("sha256") != SGLANG_SOURCE_SHA256 \
            or "not shipped in an SGLang release" not in sglang_source.get("excerpt", ""):
        raise ValueError("ISSUE209_FAIL: candidate source revision drift")
    expected_candidates = {
        "official-reference-runtime": R7A_REVISION,
        "vllm-current-source": VLLM_REVISION,
        "sglang-current-source": SGLANG_REVISION,
    }
    if {candidate.get("id"): candidate.get("revision") for candidate in candidates} != expected_candidates:
        raise ValueError("ISSUE209_FAIL: candidate authority inventory drift")
    if any(candidate.get("disposition") != "REJECTED" for candidate in candidates):
        raise ValueError("ISSUE209_FAIL: unreviewed runtime candidate")
    return {
        "schema": "inferswarm.issue209.terminal-reduction/1",
        "terminal": TERMINAL,
        "predecessor": {
            "merge": "7417c2f58a63d4da854ff399ba6fea5bd722da83",
            "terminal": R7A_TERMINAL_NAME,
            "terminal_commit_path": "7417c2f58a63d4da854ff399ba6fea5bd722da83:" + R7A_TERMINAL,
            "terminal_sha256": R7A_TERMINAL_SHA256,
            "manifest_commit_path": "7417c2f58a63d4da854ff399ba6fea5bd722da83:" + R7A_MANIFEST,
            "manifest_sha256": R7A_MANIFEST_SHA256,
        },
        "model": {"repository": "deepseek-ai/DeepSeek-V4.1-Flash",
                  "revision": R7A_REVISION, "scope": "text-only"},
        "selection_rule": authority["candidate_disposition_rule"],
        "candidate_dispositions": [
            {"id": candidate["id"], "disposition": candidate["disposition"],
             "failed_predicates": candidate["failed_predicates"]}
            for candidate in candidates
        ],
        "blocking_seam": {
            "kind": "runtime/backend",
            "required": "A pinned runtime must natively load the official sharded safetensors index and shards, selectively materialize the selected state, expose source-faithful text prefill/decode cache authority, and execute one declared legal shape.",
            "observed": "The official reference requires converted model{rank}-mp{world_size}.safetensors. Pinned current vLLM and SGLang sources offer model-serving implementations, but the audited surfaces load model-owned parameters/cache internally and retain no explicit InferSwarm-selected-state, cache-authority, or declared heterogeneous-shape contract.",
            "smallest_successor": "Add a bounded, source-audited backend boundary for one pinned candidate that maps official shards to selected state, makes prefill/decode cache ownership observable, and declares one legal heterogeneous shape; do not convert the R7 subject in InferSwarm.",
        },
        "non_claims": [
            "No full checkpoint download, model execution, GPU qualification, serving, conversion, strategy adapter, or compact execution-contract fixture occurred.",
            "This prerequisite does not reject DeepSeek V4.1 Flash; it rejects an unproven runtime substrate.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    encoded = json.dumps(reduction_document(), sort_keys=True, separators=(",", ":")) + "\n"
    path = ROOT / OUTPUT
    if args.write:
        path.write_text(encoded)
    elif not path.is_file() or path.read_text() != encoded:
        raise SystemExit("ISSUE209_FAIL: terminal reduction drift; run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
