#!/usr/bin/env python3
"""Fail-closed Issue #209 R7-B reduction over retained static evidence.

Reduction v4 changes versus v3:

* p8 (observable cache authority) is adjudicated MECHANICALLY from
  retained, hash-verified vLLM lifecycle source bytes.  Authored p8
  fields are never an input; they may only agree with the derivation.
* The forged-FAIL seam is closed: a ``p8_failure_proof`` now requires
  (a) the named source file to be retained with a matching SHA-256,
  (b) the proof's excerpt to appear verbatim in those exact bytes, and
  (c) the proof's ``source_condition`` marker to appear verbatim in the
  same bytes.  An authored ``requires_external_runtime_backend_change``
  boolean alone can no longer produce ``R7B_RUNTIME_SUBSTRATE_PREREQUISITE``.
* p8 PASS no longer terminates at Phase 1: the reduction consumes the
  retained Phase 2-5 strategy-authority and compact execution-contract
  fixture records and derives the Phase-6 terminal fail-closed.
"""
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
R7A_CENSUS = "docs/investigations/deepseek-v41-flash-r7-a/tensor-census.json"
RUNTIME_AUTHORITY = f"{AREA}/runtime-authority.json"
EXTERNAL_SOURCE_EVIDENCE = f"{AREA}/external-source-evidence.json"
STRATEGY_AUTHORITY = f"{AREA}/strategy-authority.json"
EXECUTION_CONTRACT = f"{AREA}/execution-contract-fixture.json"
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
STRATEGY_SEAM_PREREQUISITE = "R7B_STRATEGY_SEAM_PREREQUISITE"
GATE_READY = "R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY"
PREDICATES = (
    "p1_exact_immutable_runtime_revision", "p2_license_provenance",
    "p3_source_faithful_model_path", "p4_native_official_sharded_safetensors",
    "p5_no_mandatory_representation_conversion", "p6_text_prefill_decode_path",
    "p7_selective_materialization_control", "p8_observable_cache_authority",
    "p9_one_legal_multi_resource_shape", "p10_deterministic_build_identity",
)
EXPECTED_STATUS = {predicate: "PASS" for predicate in PREDICATES}
REQUIRED_SOURCE_HASHES = {
    "attention": "88c47493149406249a195bf9e316ab3c63154ce82001f90dcde5b0e8be137069",
    "default_loader": "9c9d54b1b650bf5affc924ebb8b8c73711e187ae7486cadd9f737bb1279cc7b8",
    "kv_cache_coordinator": "7fa4065d19021e77b3424d24e1b088c530ed70b90c5ed9bc52cf4b7581d5fc48",
    "kv_cache_interface": "a187dd20b9404bcdcd9f9e64bd1ccef821084bfb88330f16f6798e0672b74316",
    "kv_cache_manager": "b5a0bb144934cc3c0e6b6dc63b69e1919e7a36c4221fba949b07e89c08e1f11c",
    "model": "51e40463b6ce3a76ad64a09b6bbdf4688cae468d316f426d9d394fcff08b146e",
    "scheduler": "ea45be71111aa81a423b4e77dc82b769cda530f0117a3af3214202d8feda06a4",
    "single_type_kv_cache_manager": "15360abf039513fab8f0fe99d7bc36283e63251d83e1c13f99368ae89bf13135",
    "utils": "98b8358dd37f1148b6d29d1969ba4064343a316153ebad6e3bb82cdf3d528bf9",
}
#: p8 fact table: each required lifecycle fact is a verbatim marker that
#: must appear in the named retained lifecycle source file's exact bytes.
P8_FACTS = {
    "request_block_ownership": ("kv_cache_manager", "req_to_blocks[request_id]"),
    "free_on_completion": ("scheduler", "def _free_request("),
    "deferred_free_inflight": ("scheduler", "self.deferred_frees.append("),
    "deferred_free_drain": ("scheduler", "def _drain_deferred_frees("),
    "prefix_cache_reset": ("kv_cache_manager", "def reset_prefix_cache("),
    "preemption_frees_blocks": ("scheduler", "def _preempt_request("),
    "preemption_resets_computed": ("scheduler", "request.num_computed_tokens = 0"),
    "preempted_requeue": ("scheduler", "self.waiting.prepend_request(request)"),
    "prefill_decode_transition": ("scheduler", "request.is_prefill_chunk = request.num_computed_tokens < ("),
    "v41_cache_spec_ownership": ("attention", "if not self.is_kv_source:"),
    "v41_kv_index_mapping": ("attention", "def _replace_layer_index("),
    "pp_cut_in_group_prohibited": ("attention", "PP splits inside a v4.1 kv-sharing group"),
    "cache_group_spec_merge": ("kv_cache_interface", "class MLAAttentionSpec("),
}
#: Derived legal cut boundaries: kv-sharing groups are [source, next
#: source) with group membership defined by nearest-source-at-or-below
#: resolution (attention.py:331-336); a PP cut may not fall inside a
#: group (attention.py:439-444,550-558).  Sources are {2,8,14,20} and
#: layer 40 is the backbone end, so legal cuts are exactly these.
LEGAL_CUTS = (2, 8, 14, 20, 40)
N_LAYERS = 40
STRATEGY_SCHEMA = "inferswarm.issue209.strategy-authority/1"
EXEC_SCHEMA = "inferswarm.issue209.execution-contract-fixture/1"
INPUTS = (R7A_TERMINAL, R7A_MANIFEST, R7A_CENSUS, RUNTIME_AUTHORITY,
          EXTERNAL_SOURCE_EVIDENCE, STRATEGY_AUTHORITY, EXECUTION_CONTRACT,
          *R7A_RETAINED_FILES)


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


def _retained_source_text(root: Path, sources: dict[str, Any], key: str) -> str:
    """Exact retained bytes for a cited source file, hash-verified."""
    entry = (sources.get("third_party_candidates", {}).get("vllm", {})
             .get("files", {}).get(key))
    if not isinstance(entry, dict):
        raise ValueError(f"ISSUE209_FAIL: retained source '{key}' missing")
    relative = entry.get("path") or ""
    expected = entry.get("sha256") or ""
    if not relative.startswith("vllm/"):
        raise ValueError(f"ISSUE209_FAIL: retained source '{key}' path malformed")
    absolute = root / AREA / "external" / relative
    try:
        actual = _sha256(absolute)
    except OSError as error:
        raise ValueError(f"ISSUE209_FAIL: retained source '{key}' bytes absent") from error
    if actual != expected:
        raise ValueError(f"ISSUE209_FAIL: retained source '{key}' hash mismatch")
    return absolute.read_text()


def _adjudicate_p8(root: Path, sources: dict[str, Any]) -> dict[str, Any]:
    """Derive every p8 lifecycle fact from retained, hash-verified bytes."""
    texts: dict[str, str] = {}
    verified: dict[str, str] = {}
    missing: list[str] = []
    for fact, (source_key, marker) in sorted(P8_FACTS.items()):
        if source_key not in texts:
            texts[source_key] = _retained_source_text(root, sources, source_key)
        if marker in texts[source_key]:
            verified[fact] = f"{source_key}: verbatim marker present"
        else:
            missing.append(fact)
    if missing:
        return {"status": "UNPROVEN",
                "missing_facts": missing,
                "question": ("retained pinned lifecycle source does not "
                             "establish: " + ", ".join(missing))}
    return {"status": "PASS", "verified": verified}


def _verify_fail_proof(root: Path, sources: dict[str, Any]) -> str:
    """Mechanically verify a retained p8 FAIL proof against exact bytes.

    Requires the proof to name a retained source file whose SHA-256
    matches, an excerpt present verbatim in those bytes, and a
    ``source_condition`` marker also present verbatim in the same bytes.
    Returns the verified source path; raises fail-closed otherwise.
    """
    proof = (sources.get("third_party_candidates", {}).get("vllm", {})
             .get("p8_failure_proof"))
    if not isinstance(proof, dict):
        raise ValueError("ISSUE209_FAIL: p8 FAIL lacks retained proof")
    if proof.get("requires_external_runtime_backend_change") is not True:
        raise ValueError("ISSUE209_FAIL: p8 FAIL proof lacks external-change derivation")
    key = proof.get("source_file") or ""
    entry = (sources.get("third_party_candidates", {}).get("vllm", {})
             .get("files", {}).get(key))
    if not isinstance(entry, dict):
        raise ValueError("ISSUE209_FAIL: p8 FAIL proof names an unretained source")
    text = _retained_source_text(root, sources, key)
    excerpt = proof.get("excerpt") or ""
    condition = proof.get("source_condition") or ""
    if not excerpt or excerpt not in text:
        raise ValueError("ISSUE209_FAIL: p8 FAIL proof excerpt not in retained bytes")
    if not condition or condition not in text:
        raise ValueError("ISSUE209_FAIL: p8 FAIL source condition not in retained bytes")
    return entry.get("path") or key


def _verify_phase2_5(root: Path) -> dict[str, Any]:
    """Consume retained Phase 2-5 artifacts fail-closed (p8 PASS path)."""
    strategy = _load(root, STRATEGY_AUTHORITY)
    execution = _load(root, EXECUTION_CONTRACT)
    if strategy.get("schema") != STRATEGY_SCHEMA:
        raise ValueError("ISSUE209_FAIL: strategy authority schema drift")
    if execution.get("schema") != EXEC_SCHEMA:
        raise ValueError("ISSUE209_FAIL: execution-contract schema drift")
    if strategy.get("model_revision") != R7A_REVISION:
        raise ValueError("ISSUE209_FAIL: strategy authority revision drift")
    shape = strategy.get("shape")
    if shape not in ("contiguous_stage", "expert_local"):
        raise ValueError("ISSUE209_FAIL: no legal frozen shape")
    cut = strategy.get("cut_layer")
    if shape == "contiguous_stage":
        if cut not in LEGAL_CUTS:
            raise ValueError(f"ISSUE209_FAIL: cut {cut!r} is not a legal kv-sharing-group boundary")
        interval = strategy.get("layer_interval")
        if not isinstance(interval, list) or len(interval) != 2 or interval[0] != cut:
            raise ValueError("ISSUE209_FAIL: stage interval must start at the cut")
        if interval[1] is not None and not (cut < interval[1] <= N_LAYERS):
            raise ValueError("ISSUE209_FAIL: stage interval out of range")
    elif cut is not None:
        raise ValueError("ISSUE209_FAIL: expert_local carries no PP cut")
    if execution.get("shape") != shape or execution.get("strategy_digest") != strategy.get("digest"):
        raise ValueError("ISSUE209_FAIL: fixture/strategy identity drift")
    units = execution.get("units", [])
    if len(units) < 2:
        raise ValueError("ISSUE209_FAIL: compact proof requires >=2 units")
    if len({unit.get("resource") for unit in units}) < 2:
        raise ValueError("ISSUE209_FAIL: compact proof must be multi-resource")
    for unit in units:
        if not isinstance(unit.get("dependencies"), list):
            raise ValueError("ISSUE209_FAIL: unit missing dependency edges")
    controls = execution.get("negative_controls", [])
    required_controls = {
        "fabricated_fail_proof_rejected", "authored_boolean_cannot_flip_terminal",
        "wrong_source_hash_fails", "excerpt_absent_from_source_fails",
        "deleting_lifecycle_evidence_cannot_unprove_p8", "p8_pass_not_phase1",
        "authored_terminal_rejected", "r7a_byte_identical", "superseded_not_authority",
        "stale_cache_authority_rejected", "decode_before_prefill_fails",
    }
    if {c.get("id") for c in controls} != required_controls:
        raise ValueError("ISSUE209_FAIL: required negative-control set incomplete")
    if any(c.get("result") != "FAIL_CLOSED" for c in controls):
        raise ValueError("ISSUE209_FAIL: negative control did not fail closed")
    return {"shape": shape, "cut": cut,
            "units": len(units),
            "negative_controls": len(controls)}


def _terminal_for_p8(p8_status: str, root: Path,
                     sources: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Derive the terminal solely from the mechanically derived p8 status."""
    if p8_status == "UNPROVEN":
        return EVIDENCE_BLOCKED, {"p8_status": "UNPROVEN"}
    if p8_status == "FAIL":
        source_path = _verify_fail_proof(root, sources)
        return RUNTIME_PREREQUISITE, {"p8_status": "FAIL",
                                      "proof_source": source_path}
    detail = _verify_phase2_5(root)
    detail["p8_status"] = "PASS"
    return GATE_READY, detail


def _vllm_authority(authority: dict[str, Any],
                    sources: dict[str, Any]) -> dict[str, Any]:
    if authority.get("mandatory_predicates") != list(PREDICATES):
        raise ValueError("ISSUE209_FAIL: incomplete selection rubric")
    candidates = authority.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("ISSUE209_FAIL: malformed candidate authority")
    vllm_rows = [row for row in candidates if row.get("id") == "vllm-current-source"]
    if len(vllm_rows) != 1:
        raise ValueError("ISSUE209_FAIL: vLLM candidate identity drift")
    vllm = vllm_rows[0]
    if vllm.get("revision") != VLLM_REVISION:
        raise ValueError("ISSUE209_FAIL: vLLM revision drift")
    adjudications = {row.get("id"): row for row in vllm.get("predicate_adjudications", [])}
    if set(adjudications) != set(PREDICATES):
        raise ValueError("ISSUE209_FAIL: incomplete predicate adjudication")
    for predicate in PREDICATES:
        if not adjudications[predicate].get("evidence"):
            raise ValueError("ISSUE209_FAIL: predicate disposition lacks retained evidence")
    source = sources.get("third_party_candidates", {}).get("vllm", {})
    files = source.get("files", {})
    observed = {key: files.get(key, {}).get("sha256") for key in REQUIRED_SOURCE_HASHES}
    if source.get("revision") != VLLM_REVISION or observed != REQUIRED_SOURCE_HASHES:
        raise ValueError("ISSUE209_FAIL: pinned vLLM source drift")
    if (source.get("build", {}).get("sha256")
            != "953aefa02a4a18194946711b76f6a4854fd096f09b3d07ac4403e339cb4dd518"
            or source.get("license", {}).get("sha256")
            != "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"):
        raise ValueError("ISSUE209_FAIL: vLLM provenance/build drift")
    if "terminal" in authority or "terminal" in vllm:
        raise ValueError("ISSUE209_FAIL: authored terminal is not an input to reduction")
    return vllm


def reduction_document(root: Path = ROOT) -> dict[str, Any]:
    _preserve_r7a(root)
    authority = _load(root, RUNTIME_AUTHORITY)
    sources = _load(root, EXTERNAL_SOURCE_EVIDENCE)
    vllm = _vllm_authority(authority, sources)
    p8 = _adjudicate_p8(root, sources)
    terminal, detail = _terminal_for_p8(p8["status"], root, sources)
    adjudications = {row["id"]: row for row in vllm.get("predicate_adjudications", [])}
    authored_p8 = adjudications.get("p8_observable_cache_authority", {})
    if "status" in authored_p8 and authored_p8["status"] != p8["status"]:
        raise ValueError("ISSUE209_FAIL: authored p8 disposition contradicts source-derived adjudication")
    expected_disposition = {EVIDENCE_BLOCKED: "EVIDENCE_BLOCKED",
                            RUNTIME_PREREQUISITE: "REJECTED",
                            STRATEGY_SEAM_PREREQUISITE: "REJECTED",
                            GATE_READY: "SELECTED"}[terminal]
    if vllm.get("disposition") != expected_disposition:
        raise ValueError("ISSUE209_FAIL: runtime disposition contradicts predicate-derived terminal")
    document = {
        "schema": "inferswarm.issue209.terminal-reduction/4",
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
        "p8_derivation": p8,
        "terminal_detail": detail,
        "non_claims": [
            "No full checkpoint download, full DeepSeek V4.1 Flash model execution, GPU/CUDA/Vulkan qualification, serving, or representation conversion occurred.",
            "The compact execution-contract fixture is a substrate-contract proof over synthetic geometry derived from the accepted R7-A census; it is not DeepSeek inference evidence.",
            "This terminal grants no execution authorization; physical qualification requires a separately authorized issue.",
        ],
    }
    return document


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
