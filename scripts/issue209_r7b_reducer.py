#!/usr/bin/env python3
"""Fail-closed Issue #209 R7-B reduction over retained static evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AREA = "docs/investigations/deepseek-v41-flash-r7-b"
R7A_TERMINAL = "docs/investigations/deepseek-v41-flash-r7-a/terminal-reduction.json"
R7A_MANIFEST = "docs/investigations/deepseek-v41-flash-r7-a/MANIFEST.sha256"
RUNTIME_AUTHORITY = f"{AREA}/runtime-authority.json"
EXTERNAL_SOURCE_EVIDENCE = f"{AREA}/external-source-evidence.json"
OUTPUT = f"{AREA}/terminal-reduction.json"
R7A_RETAINED_FILES = {
    "docs/investigations/deepseek-v41-flash-r7-a/external/LICENSE": "f2c6c602815669d292889e5be8c802f2ed950653b77999b1584e8e6aed25d040",
    "docs/investigations/deepseek-v41-flash-r7-a/external/inference/config.json": "2e84f45cf1dac8c7fcbb200e96667d4b913275690668ed496f24c7747207a809",
    "docs/investigations/deepseek-v41-flash-r7-a/external/inference/model.py": "4e9ae23620edc8028ccc5d5fef552ab7fdc7dcd6f79608754fe9f67644056f65",
}
R7A_REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"
R7A_TERMINAL_NAME = "R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE"
R7A_MANIFEST_SHA256 = "6730826a7c00b92cc88bda814583ccc6955370cde37d685261f764b5146e640c"
R7A_TERMINAL_SHA256 = "aee287f59199622b97bdf9862624f990416ee838eebea397e6a64d99526806dc"
VLLM_REVISION = "0eae9acd4d01574e12d4ecf6a0229813f7fdb799"
EVIDENCE_BLOCKED = "R7B_EVIDENCE_BLOCKED"
RUNTIME_PREREQUISITE = "R7B_RUNTIME_SUBSTRATE_PREREQUISITE"
PREDICATES = (
    "p1_exact_immutable_runtime_revision", "p2_license_provenance",
    "p3_source_faithful_model_path", "p4_native_official_sharded_safetensors",
    "p5_no_mandatory_representation_conversion", "p6_text_prefill_decode_path",
    "p7_selective_materialization_control", "p8_observable_cache_authority",
    "p9_one_legal_multi_resource_shape", "p10_deterministic_build_identity",
)
EXPECTED_STATUS = {predicate: "PASS" for predicate in PREDICATES}
EXPECTED_STATUS["p8_observable_cache_authority"] = "UNPROVEN"
REQUIRED_SOURCE_HASHES = {
    "model": "51e40463b6ce3a76ad64a09b6bbdf4688cae468d316f426d9d394fcff08b146e",
    "utils": "98b8358dd37f1148b6d29d1969ba4064343a316153ebad6e3bb82cdf3d528bf9",
    "default_loader": "9c9d54b1b650bf5affc924ebb8b8c73711e187ae7486cadd9f737bb1279cc7b8",
    "attention": "88c47493149406249a195bf9e316ab3c63154ce82001f90dcde5b0e8be137069",
}
INPUTS = (R7A_TERMINAL, R7A_MANIFEST, RUNTIME_AUTHORITY,
          EXTERNAL_SOURCE_EVIDENCE, *R7A_RETAINED_FILES)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(root: Path, relative: str) -> dict[str, Any]:
    try:
        return json.loads((root / relative).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"ISSUE209_FAIL: missing or malformed {relative}") from error


def _preserve_r7a(root: Path) -> None:
    predecessor = _load(root, R7A_TERMINAL)
    if (predecessor.get("terminal") != R7A_TERMINAL_NAME
            or predecessor.get("source_authority", {}).get("revision") != R7A_REVISION):
        raise ValueError("ISSUE209_FAIL: R7-A terminal drift")
    if _sha256(root / R7A_TERMINAL) != R7A_TERMINAL_SHA256:
        raise ValueError("ISSUE209_FAIL: R7-A terminal content drift")
    if _sha256(root / R7A_MANIFEST) != R7A_MANIFEST_SHA256:
        raise ValueError("ISSUE209_FAIL: R7-A manifest drift")
    for relative, expected in R7A_RETAINED_FILES.items():
        if _sha256(root / relative) != expected:
            raise ValueError("ISSUE209_FAIL: R7-A retained source drift")


def _terminal_for_p8(p8: dict[str, Any], sources: dict[str, Any]) -> str:
    """Derive the terminal solely from the cache predicate and retained proof.

    An unresolved source question is evidence-blocked, not a claim about the
    runtime.  A runtime prerequisite needs a distinct retained proof that the
    missing capability requires an external runtime/backend change.  A PASS
    cannot terminate this Phase-1-only reduction: the selected shape, frozen
    cuts, adapter, and compact fixture must then be completed by later phases.
    """
    status = p8.get("status")
    if status == "UNPROVEN":
        return EVIDENCE_BLOCKED
    if status == "FAIL":
        proof = sources.get("third_party_candidates", {}).get("vllm", {}).get(
            "p8_failure_proof")
        if not isinstance(proof, dict) or proof.get("requires_external_runtime_backend_change") is not True:
            raise ValueError("ISSUE209_FAIL: p8 FAIL lacks retained external runtime/backend-change proof")
        source_file = proof.get("source_file")
        source = sources["third_party_candidates"]["vllm"].get("files", {}).get(source_file, {})
        if not source_file or proof.get("sha256") != source.get("sha256") or not proof.get("excerpt"):
            raise ValueError("ISSUE209_FAIL: p8 FAIL proof is not bound to retained pinned source")
        return RUNTIME_PREREQUISITE
    if status == "PASS":
        raise ValueError("ISSUE209_FAIL: p8 PASS requires Phase 2-5 shape, cut, adapter, and fixture evidence")
    raise ValueError("ISSUE209_FAIL: invalid p8 cache-authority disposition")


def _vllm_authority(authority: dict[str, Any], sources: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if authority.get("mandatory_predicates") != list(PREDICATES):
        raise ValueError("ISSUE209_FAIL: incomplete selection rubric")
    candidates = authority.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("ISSUE209_FAIL: malformed candidate authority")
    vllm_rows = [row for row in candidates if row.get("id") == "vllm-current-source"]
    if len(vllm_rows) != 1:
        raise ValueError("ISSUE209_FAIL: vLLM candidate identity drift")
    vllm = vllm_rows[0]
    if (vllm.get("revision") != VLLM_REVISION
            or vllm.get("failed_predicates") != ["p8_observable_cache_authority"]):
        raise ValueError("ISSUE209_FAIL: unsupported runtime disposition")
    adjudications = {row.get("id"): row for row in vllm.get("predicate_adjudications", [])}
    if set(adjudications) != set(PREDICATES):
        raise ValueError("ISSUE209_FAIL: incomplete predicate adjudication")
    for predicate, expected in EXPECTED_STATUS.items():
        row = adjudications[predicate]
        if not row.get("evidence"):
            raise ValueError("ISSUE209_FAIL: predicate disposition lacks retained evidence")
        if predicate != "p8_observable_cache_authority" and row.get("status") != expected:
            raise ValueError("ISSUE209_FAIL: predicate disposition contradicts pinned source")

    source = sources.get("third_party_candidates", {}).get("vllm", {})
    files = source.get("files", {})
    observed_hashes = {key: files.get(key, {}).get("sha256") for key in REQUIRED_SOURCE_HASHES}
    if source.get("revision") != VLLM_REVISION or observed_hashes != REQUIRED_SOURCE_HASHES:
        raise ValueError("ISSUE209_FAIL: pinned vLLM source drift")
    if any(not files[key].get("path") or not files[key].get("excerpts")
           for key in REQUIRED_SOURCE_HASHES):
        raise ValueError("ISSUE209_FAIL: pinned vLLM excerpt drift")
    if (source.get("build", {}).get("sha256")
            != "953aefa02a4a18194946711b76f6a4854fd096f09b3d07ac4403e339cb4dd518"
            or source.get("license", {}).get("sha256")
            != "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"):
        raise ValueError("ISSUE209_FAIL: vLLM provenance/build drift")
    p8 = adjudications["p8_observable_cache_authority"]
    p8_evidence = " ".join(p8["evidence"])
    required_gap = ("request/session lifetime", "invalidation", "reconstruction")
    if p8.get("status") == "UNPROVEN" and not all(term in p8_evidence for term in required_gap):
        raise ValueError("ISSUE209_FAIL: cache lifecycle seam is not explicit")
    if "terminal" in authority or "terminal" in vllm:
        raise ValueError("ISSUE209_FAIL: authored terminal is not an input to reduction")
    terminal = _terminal_for_p8(p8, sources)
    expected_disposition = {
        EVIDENCE_BLOCKED: "EVIDENCE_BLOCKED",
        RUNTIME_PREREQUISITE: "REJECTED",
    }[terminal]
    if vllm.get("disposition") != expected_disposition:
        raise ValueError("ISSUE209_FAIL: runtime disposition contradicts predicate-derived terminal")
    return vllm, terminal


def reduction_document(root: Path = ROOT) -> dict[str, Any]:
    _preserve_r7a(root)
    vllm, terminal = _vllm_authority(_load(root, RUNTIME_AUTHORITY),
                                     _load(root, EXTERNAL_SOURCE_EVIDENCE))
    return {
        "schema": "inferswarm.issue209.terminal-reduction/3",
        "terminal": terminal,
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
        "runtime": {"id": vllm["id"], "revision": vllm["revision"],
                    "predicate_adjudications": vllm["predicate_adjudications"]},
        "blocking_seam": {
            "predicate": "p8_observable_cache_authority",
            "classification": "evidence_gap",
            "observed": "Pinned attention source establishes KV-source ownership, shared-cache dependencies, prefill/decode token accounting, and rejection of PP cuts inside a sharing group; the retained source set does not bind request/session lifetime, invalidation, or legal reconstruction to this model's selected boundary.",
            "smallest_successor_evidence": "Retain exact pinned vLLM request/session KV-cache lifecycle and invalidation/reconstruction source, bind it to this model's cache-source mapping, then re-adjudicate p8 without downloading a checkpoint or executing a model.",
        },
        "non_claims": [
            "No strategy adapter, compact execution fixture, full checkpoint download, model execution, GPU/CUDA/Vulkan qualification, serving, or representation conversion occurred.",
            "This evidence blocker records no execution authorization or runtime/backend deficiency.",
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
