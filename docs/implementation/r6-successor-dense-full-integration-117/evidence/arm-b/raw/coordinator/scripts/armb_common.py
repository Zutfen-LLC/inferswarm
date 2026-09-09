"""Arm-B shared role configuration (physical campaign constants).

Physical decomposition of the accepted #99/#101 in-process trusted boundary:
  SOURCE role    : inferswarm01 (owns /srv/models/gemma-r6, byte-reading side)
  COORDINATOR    : inferswarm00 (external CPU-only; metadata only)
  PARTICIPANTS   : inferswarm01 (stage-1 gpu-0, stage-2 gpu-1), inferswarm03 (stage-3 gpu-0)
Transport        : operator-local-http Range GET (accepted #99 source contract),
                   endpoint on inferswarm01 LAN interface; every byte moves only
                   through acquire_artifact() under a Coordinator ticket,
                   verify-then-publish into the canonical cold roots.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

# ---- accepted authorities (Issue #117, Arm-B prompt) ------------------------
ACCEPTED_MAIN = "5179c41232051e7455b778ddb8876a6539f4cb04"
ARM_A_MERGE = "6774474941d7ce2a0252c8c1e148f8bce61a8d6d"
FROZEN_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"   # FreeToken
CHECKPOINT_SHA256 = "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"
MODEL_ID = "google/gemma-4-12B-it"
MODEL_REVISION = "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7"
REPRESENTATION = "checkpoint-safetensors"
ACCEPTED_SUBJECT_DIGEST = "sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd"
ACCEPTED_R6_PLAN_SHA256 = "a91e3f71353905d4af3722408327a9f9bda0f2655061ae9e44f51d9a3edf28fc"
ACCEPTED_R6_PLAN_DIGEST = "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1"

# ---- fabric -----------------------------------------------------------------
SOURCE_HOST = "inferswarm01"
SOURCE_MODEL_ROOT = Path("/srv/models/gemma-r6")
SOURCE_ENDPOINT_HOST = "10.0.0.141"     # inferswarm01 LAN
SOURCE_ENDPOINT_PORT = 18486
SOURCE_ID = "issue117-origin"
SOURCE_KIND = "operator-local-http"
COORDINATOR_HOST = "inferswarm00"
PARTICIPANT_NODES = ("inferswarm01", "inferswarm03")

# accepted CU identities (Issue #117 / physical preflight)
STAGES = [
    {"participant_id": "dense.6171f32b4413.stage-1", "node": "inferswarm01",
     "cu_id": "inferswarm01/gpu-0", "gpu_uuid": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
     "role": "first",  "start_layer": 0,  "end_layer": 16,
     "owns_embeddings": True,  "owns_final_norm_head": False},
    {"participant_id": "dense.6171f32b4413.stage-2", "node": "inferswarm01",
     "cu_id": "inferswarm01/gpu-1", "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
     "role": "middle", "start_layer": 16, "end_layer": 32,
     "owns_embeddings": False, "owns_final_norm_head": False},
    {"participant_id": "dense.6171f32b4413.stage-3", "node": "inferswarm03",
     "cu_id": "inferswarm03/gpu-0", "gpu_uuid": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
     "role": "last",   "start_layer": 32, "end_layer": 48,
     "owns_embeddings": False, "owns_final_norm_head": True},
]

TEXT_PREFIX = "model.language_model"
EMBED_KEY = TEXT_PREFIX + ".embed_tokens.weight"
NORM_KEY = TEXT_PREFIX + ".norm.weight"

CACHE_ROOT = "/srv/inferswarm/cache/issue117"
MATERIALIZED_ROOT = "/srv/inferswarm/materialized/issue117"

CHUNK_BYTES = 32 * 1024 * 1024

CANDIDATE_ID = "dense.6171f32b4413"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(8 * 1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(document) -> bytes:
    return json.dumps(document, sort_keys=True, indent=2,
                      ensure_ascii=False, separators=(",", ": ")).encode()


def digest_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def self_digest(document: dict, *, identity_field: str) -> str:
    payload = {k: v for k, v in document.items() if k != identity_field}
    return digest_of_bytes(canonical_json_bytes(payload))
