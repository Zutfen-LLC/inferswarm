#!/usr/bin/env python3
"""Build Issue #187's bounded, metadata-only DeepSeek V4.1 Flash census.

The tool deliberately uses HTTP metadata and safetensors *headers* only.  It
never asks for a checkpoint body, imports a model runtime, or opens a GPU.
Run it once to create the retained input records; use issue187_r7a_reducer.py
thereafter for an offline, fail-closed check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/deepseek-v41-flash-r7-a"
REPOSITORY = "deepseek-ai/DeepSeek-V4.1-Flash"
REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"
INFERSWARM_STARTING_HEAD = "f142a0d9b693f999685960c641b2a8fe362c4e1e"
ISSUE117_CLOSURE = "f349cbdfbb20ac933447c483f855b1f501aa7a1c"
SMALL_FILES = ("README.md", "LICENSE", "config.json", "tokenizer_config.json",
               "inference/config.json", "inference/model.py",
               "model.safetensors.index.json")


def get(url: str, byte_range: str | None = None) -> bytes:
    headers = {"Range": byte_range} if byte_range else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def file_url(path: str) -> str:
    return f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{path}"


def classify(name: str) -> str:
    if name.startswith(("vision.", "aligner.")):
        return "vision"
    if name.startswith("mtp."):
        return "draft_mtp"
    if ".ffn.experts." in name:
        return "routed_expert"
    if ".ffn.shared_experts." in name:
        return "shared_expert"
    if ".ffn.gate." in name:
        return "router"
    if ".engram." in name:
        return "engram"
    if name.startswith(("embed.", "head.")):
        return "embedding_or_head"
    if ".attn." in name:
        return "attention"
    return "backbone_or_other"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.write:
        parser.error("--write is required; this producer performs bounded network retrieval")

    api = json.loads(get(f"https://huggingface.co/api/models/{REPOSITORY}?blobs=true"))
    if api.get("sha") != REVISION:
        raise ValueError("ISSUE187_FAIL: mutable repository no longer resolves to pinned revision")
    siblings = api.get("siblings")
    if not isinstance(siblings, list) or not siblings:
        raise ValueError("ISSUE187_FAIL: repository inventory missing")
    objects = []
    by_name = {}
    for row in siblings:
        name = row.get("rfilename")
        size = row.get("size", 0)
        if not isinstance(name, str) or not isinstance(size, int):
            raise ValueError("ISSUE187_FAIL: malformed repository object")
        identity = {"path": name, "bytes": size, "blob_id": row.get("blobId")}
        if row.get("lfs"):
            identity["lfs_sha256"] = row["lfs"].get("sha256")
        objects.append(identity)
        by_name[name] = identity
    objects.sort(key=lambda row: row["path"])

    external = AREA / "external"
    hashes = {}
    for name in SMALL_FILES:
        payload = get(file_url(name))
        target = external / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        hashes[name] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    shards = [row for row in objects if row["path"].endswith(".safetensors")]
    if len(shards) != 48 or any(not row.get("lfs_sha256") for row in shards):
        raise ValueError("ISSUE187_FAIL: incomplete checkpoint-shard inventory")
    tensors = []
    header_bytes = 0
    for shard in sorted(shards, key=lambda row: row["path"]):
        prefix = get(file_url(shard["path"]), "bytes=0-7")
        if len(prefix) != 8:
            raise ValueError("ISSUE187_FAIL: safetensors header length unavailable")
        length = struct.unpack("<Q", prefix)[0]
        header = get(file_url(shard["path"]), f"bytes=8-{7 + length}")
        if len(header) != length:
            raise ValueError("ISSUE187_FAIL: incomplete safetensors header range")
        header_bytes += 8 + length
        decoded = json.loads(header)
        for name, value in decoded.items():
            if name == "__metadata__":
                continue
            offsets = value.get("data_offsets")
            if not isinstance(offsets, list) or len(offsets) != 2:
                raise ValueError("ISSUE187_FAIL: tensor offsets missing")
            extent = offsets[1] - offsets[0]
            if extent < 0:
                raise ValueError("ISSUE187_FAIL: negative tensor extent")
            tensors.append({"name": name, "shard": shard["path"],
                            "dtype": value.get("dtype"), "shape": value.get("shape"),
                            "encoded_bytes": extent, "state_class": classify(name)})
    names = [row["name"] for row in tensors]
    if len(names) != len(set(names)):
        raise ValueError("ISSUE187_FAIL: duplicate tensor identity across shards")
    index = json.loads((external / "model.safetensors.index.json").read_text())
    indexed = index.get("weight_map", {})
    if set(indexed) != set(names):
        raise ValueError("ISSUE187_FAIL: index/header tensor population disagreement")
    if any(indexed[name] != row["shard"] for name, row in ((r["name"], r) for r in tensors)):
        raise ValueError("ISSUE187_FAIL: index/header shard mapping disagreement")
    if sum(row["encoded_bytes"] for row in tensors) != index.get("metadata", {}).get("total_size"):
        raise ValueError("ISSUE187_FAIL: tensor byte total does not reconcile to index")

    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"tensors": 0, "encoded_bytes": 0})
    for row in tensors:
        totals[row["state_class"]]["tensors"] += 1
        totals[row["state_class"]]["encoded_bytes"] += row["encoded_bytes"]
    # The Hub config identifies the Transformers wrapper; the supplied
    # inference config is the pinned source authority for execution geometry.
    config = json.loads((external / "inference/config.json").read_text())
    inventory = {"schema": "inferswarm.issue187.repository-inventory/1", "repository": REPOSITORY,
                 "revision": REVISION, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                 "inferswarm_starting_head": INFERSWARM_STARTING_HEAD,
                 "issue117_closure_ancestor": ISSUE117_CLOSURE,
                 "objects": objects, "small_file_hashes": hashes,
                 "checkpoint_shards": len(shards),
                 "checkpoint_object_bytes": sum(row["bytes"] for row in shards),
                 "no_checkpoint_body_bytes_downloaded": True, "safetensors_header_bytes_downloaded": header_bytes}
    census = {"schema": "inferswarm.issue187.tensor-census/1", "repository": REPOSITORY,
              "revision": REVISION, "index_sha256": hashes["model.safetensors.index.json"]["sha256"],
              "tensor_count": len(tensors), "tensor_encoded_bytes": sum(r["encoded_bytes"] for r in tensors),
              "state_class_totals": dict(sorted(totals.items())), "tensors": tensors}
    state = {"schema": "inferswarm.issue187.state-inputs/1", "repository": REPOSITORY,
             "revision": REVISION, "text_first": True,
             "config": {key: config[key] for key in ("dim", "n_layers", "n_mtp_layers", "n_routed_experts",
                 "n_shared_experts", "n_activated_experts", "window_size", "kv_source_layers",
                 "index_source_layers", "engram_layer_ids", "engram_num_embeddings", "vision_n_layers")},
             "expert_unit_encoded_bytes": 18800640,
             "source_notes": {"model_implementation": "external/inference/model.py",
                 "prefill_decode_branch": "get_window_topk_idxs and Attention.forward",
                 "no_model_execution": True}}
    write_json(AREA / "repository-inventory.json", inventory)
    write_json(AREA / "tensor-census.json", census)
    write_json(AREA / "state-inputs.json", state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
