#!/usr/bin/env python3
"""Offline, fail-closed terminal reduction for Issue #187's static census."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = "docs/investigations/deepseek-v41-flash-r7-a"
INVENTORY = f"{AREA}/repository-inventory.json"
CENSUS = f"{AREA}/tensor-census.json"
STATE = f"{AREA}/state-inputs.json"
INDEX = f"{AREA}/external/model.safetensors.index.json"
OUTPUT = f"{AREA}/terminal-reduction.json"
REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"
ISSUE117_CLOSURE = "f349cbdfbb20ac933447c483f855b1f501aa7a1c"
TERMINAL = "R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE"

# This is deliberately a bounded substrate contract, not a runtime design or
# a physical-campaign authorization.  Keep the missing capability structured
# so a successor can satisfy it mechanically without reinterpreting prose.
SUBSTRATE_PREREQUISITE = {
    "model": {
        "repository": "deepseek-ai/DeepSeek-V4.1-Flash",
        "revision": REVISION,
        "scope": "text-only",
    },
    "representation": {
        "required": "selective materialization from the pinned official sharded safetensors representation",
        "not_established": "a runtime/backend can selectively load the required official tensors without first materializing the complete checkpoint on one Memory Resource",
    },
    "runtime": {
        "required": [
            "execute source-faithful text-only prefill and decode",
            "declare cache authority, lifetime, and reconstruction across the prefill/decode boundary",
            "execute one strategy-certified multi-resource decomposition with explicit boundary dependencies",
        ],
        "not_established": "a pinned runtime/backend path satisfying all three requirements",
    },
    "successor_scope": [
        "pin one runtime/backend revision and its supported official representation path",
        "implement one text-only Model Execution Strategy adapter with cache-authority semantics",
        "demonstrate one strategy-certified contiguous-stage or expert-local multi-resource shape before any physical R7-B qualification",
    ],
    "not_required": [
        "a checkpoint-body download for R7-A",
        "a model-wide third-party conversion survey",
        "a complete distributed capacity or economics plan",
        "vision/aligner support",
        "a generic planner concept named expert, router, or KV cache",
    ],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(root: Path, relative: str) -> dict:
    try:
        return json.loads((root / relative).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"ISSUE187_FAIL: missing or malformed {relative}") from error


def reduction_document(root: Path = ROOT) -> dict:
    inventory, census, state, index = (load(root, path)
                                       for path in (INVENTORY, CENSUS, STATE, INDEX))
    if any(doc.get("revision") != REVISION for doc in (inventory, census, state)):
        raise ValueError("ISSUE187_FAIL: stale external revision")
    if inventory.get("issue117_closure_ancestor") != ISSUE117_CLOSURE:
        raise ValueError("ISSUE187_FAIL: accepted #117 closure ancestry not recorded")
    objects = inventory.get("objects", [])
    shards = [row for row in objects if row.get("path", "").endswith(".safetensors")]
    if len(shards) != 48 or len({row["path"] for row in shards}) != 48:
        raise ValueError("ISSUE187_FAIL: incomplete or duplicate shard inventory")
    shard_bytes = sum(row.get("bytes", -1) for row in shards)
    if shard_bytes != inventory.get("checkpoint_object_bytes"):
        raise ValueError("ISSUE187_FAIL: checkpoint object sum disagreement")
    tensors = census.get("tensors", [])
    if len(tensors) != census.get("tensor_count") or not tensors:
        raise ValueError("ISSUE187_FAIL: tensor census count disagreement")
    names = [row.get("name") for row in tensors]
    if len(names) != len(set(names)):
        raise ValueError("ISSUE187_FAIL: tensor duplication")
    if any(row.get("shard") not in {s["path"] for s in shards} for row in tensors):
        raise ValueError("ISSUE187_FAIL: tensor references absent shard")
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not all(
            isinstance(name, str) and isinstance(shard, str)
            for name, shard in weight_map.items()):
        raise ValueError("ISSUE187_FAIL: malformed official tensor index")
    if set(weight_map) != set(names):
        raise ValueError("ISSUE187_FAIL: index/header tensor population disagreement")
    if any(weight_map[row["name"]] != row["shard"] for row in tensors):
        raise ValueError("ISSUE187_FAIL: index/header shard mapping disagreement")
    if census.get("index_sha256") != sha256(root / INDEX):
        raise ValueError("ISSUE187_FAIL: stale or ambiguous official tensor index")
    tensor_bytes = sum(row.get("encoded_bytes", -1) for row in tensors)
    if tensor_bytes != census.get("tensor_encoded_bytes"):
        raise ValueError("ISSUE187_FAIL: tensor byte sum disagreement")
    if index.get("metadata", {}).get("total_size") != tensor_bytes:
        raise ValueError("ISSUE187_FAIL: index tensor byte sum disagreement")
    totals = census.get("state_class_totals", {})
    if sum(row.get("encoded_bytes", -1) for row in totals.values()) != tensor_bytes:
        raise ValueError("ISSUE187_FAIL: state-class byte sum disagreement")
    config = state.get("config", {})
    required = {"dim": 5120, "n_layers": 40, "n_routed_experts": 384,
                "n_activated_experts": 6, "n_shared_experts": 1, "window_size": 128}
    if any(config.get(key) != value for key, value in required.items()):
        raise ValueError("ISSUE187_FAIL: unsupported inference assumption")
    expert_bytes = state.get("expert_unit_encoded_bytes")
    routed = totals.get("routed_expert", {}).get("encoded_bytes", 0)
    expected_routed = config["n_layers"] * config["n_routed_experts"] * expert_bytes
    if routed != expected_routed:
        raise ValueError("ISSUE187_FAIL: expert-unit census disagreement")
    # The largest accepted deployed Memory Resource is 24 GiB (R8-A's read-only
    # fleet census).  This is only a per-unit capacity filter, never an E2E claim.
    largest_resource = 24 * 1024**3
    return {"schema": "inferswarm.issue187.terminal-reduction/2", "terminal": TERMINAL,
            "source_authority": {"repository": "deepseek-ai/DeepSeek-V4.1-Flash", "revision": REVISION,
                "repository_inventory_sha256": sha256(root / INVENTORY), "tensor_census_sha256": sha256(root / CENSUS)},
            "census": {"repository_objects": len(objects), "checkpoint_shards": len(shards),
                "checkpoint_object_bytes": shard_bytes, "tensor_count": len(tensors), "tensor_encoded_bytes": tensor_bytes,
                "state_class_totals": totals},
            "semantics": {"text_first": True, "routed_experts_per_backbone_layer": 384,
                "activated_routed_experts_per_token": 6, "shared_experts_per_layer": 1,
                "sliding_window_tokens": 128, "kv_source_layers": config["kv_source_layers"],
                "index_source_layers": config["index_source_layers"], "engram_layers": config["engram_layer_ids"],
                "prefill_decode": "same backbone weights; source implementation has explicit start_pos==0 prefill and decode cache branches"},
            "decomposition": {"contiguous_stage": "LEGAL_GENERIC_EXTENSION_REQUIRED",
                "expert_local": "MODEL_ADAPTER_EXTENSION_REQUIRED", "hybrid_stage_expert": "RUNTIME_BACKEND_PREREQUISITE",
                "evidence_supported_candidates": ["contiguous_stage", "expert_local"],
                "current_seams": {"generic_planner": [
                    "strategy-defined opaque execution units, dependencies, memory requirements, and normalized costs",
                    "selection among strategy-certified legal alternatives on the Swarm resource graph",
                ], "model_execution_strategy": [
                    "model/revision-specific split and grouping legality",
                    "representation/backend predicates, cache authority, boundary semantics, and correctness rules",
                    "conditional routed-demand observations without teaching generic planning model-family nouns",
                ]}},
            "pressure": {"expert_unit_encoded_bytes": expert_bytes,
                "routed_expert_weight_bytes_selected_per_backbone_token": config["n_layers"] * config["n_activated_experts"] * expert_bytes,
                "boundary_hidden_bf16_bytes_per_token": config["dim"] * 2,
                "qualification_note": "structural bytes only; no bandwidth division or throughput claim"},
            "fleet_fit": {"largest_accepted_memory_resource_bytes": largest_resource,
                "official_checkpoint_fits_one_resource": shard_bytes <= largest_resource,
                "capacity_feasible": "NOT_ESTABLISHED", "runtime_supported": "NOT_ESTABLISHED",
                "correctness_qualified": "NOT_ESTABLISHED", "economically_useful": "NOT_ESTABLISHED"},
            "substrate_prerequisite": SUBSTRATE_PREREQUISITE,
            "prerequisite": "A pinned runtime must demonstrate selective official-representation loading, text-only prefill/decode, cache authority, and one legal multi-resource shape before physical qualification.",
            "non_claims": ["No checkpoint body download, model execution, GPU execution, serving, throughput, correctness, or execution authorization occurred.", "Aggregate VRAM is not a feasibility proof."]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    document = reduction_document()
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    if args.write:
        (ROOT / OUTPUT).write_text(encoded)
    elif not (ROOT / OUTPUT).is_file() or (ROOT / OUTPUT).read_text() != encoded:
        raise SystemExit("ISSUE187_FAIL: terminal reduction drift; run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
