"""Arm-B shared helpers: plan/requirements/artifact construction (stdlib only).

Bridges the accepted R6 census/block-plan machinery (FreeToken producer
924cd22e, text prefix model.language_model) into the accepted #99 artifact
record / participant-requirements contracts, deriving everything
mechanically from the real checkpoint header. No torch import.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

PLAN_SCHEMA = "inferswarm.issue117.execution-plan/2"
REQUIREMENTS_SCHEMA = "inferswarm.issue99.participant-requirements/1"
AUTHORIZATION_SCHEMA = "inferswarm.issue99.realization-authorization/1"
ARTIFACT_RECORD_SCHEMA = "inferswarm.issue99.artifact-record/1"

REQUIREMENT_CLASSES = ("assigned_logical_state", "declared_shared_state",
                       "required_metadata")


def canonical_json_bytes(document) -> bytes:
    # exact accepted methodology serialization (issue74_methodology):
    # compact separators, sorted keys, ensure_ascii=False, trailing newline
    return (json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n").encode()


def digest_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def self_digest(document: dict, *, identity_field: str) -> str:
    payload = {k: v for k, v in document.items() if k != identity_field}
    return digest_of_bytes(canonical_json_bytes(payload))


def validate_self_identity(document: dict, *, identity_field: str) -> None:
    if document.get(identity_field) != self_digest(document, identity_field=identity_field):
        raise ValueError(f"{identity_field} self-identity mismatch")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(8 * 1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_range(path, byte_start: int, byte_end: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(byte_start)
        remaining = byte_end - byte_start
        while remaining > 0:
            block = f.read(min(8 * 1024 * 1024, remaining))
            if not block:
                raise IOError(f"short read hashing {path}[{byte_start}:{byte_end}]")
            h.update(block)
            remaining -= len(block)
    return h.hexdigest()


def safetensors_layout(path) -> dict:
    """Header + absolute byte offsets for every tensor in one shard."""
    with open(path, "rb") as f:
        (header_len,) = struct.unpack("<Q", f.read(8))
        header = json.loads(f.read(header_len))
    data_start = 8 + header_len
    out = {}
    for key, spec in header.items():
        if key == "__metadata__":
            continue
        start, end = spec["data_offsets"]
        out[key] = {
            "object": os.path.basename(path),
            "dtype": spec["dtype"],
            "shape": list(spec["shape"]),
            "byte_start": data_start + start,
            "byte_end": data_start + end,
            "byte_count": end - start,
        }
    return out


def freeze_artifact_record(*, kind, content_digest, length, model_id, revision,
                           representation, satisfies_logical_state_ids,
                           requirement_class, origin):
    record = {
        "schema": ARTIFACT_RECORD_SCHEMA,
        "kind": kind,
        "content_digest": content_digest,
        "length": length,
        "provenance": {"model_id": model_id, "revision": revision,
                       "representation": representation},
        "satisfies_logical_state_ids": sorted(satisfies_logical_state_ids),
        "requirement_class": requirement_class,
        "origin": dict(origin),
    }
    record["artifact_id"] = self_digest(record, identity_field="artifact_id")
    return record


def build_arm_b_plan(*, census_tensors, layers, tied, participants_spec,
                     model_id, revision, representation, checkpoint_authority,
                     execution, backend, epoch=1):
    """Construct the #99-shaped execution plan from census-derived ownership.

    participants_spec: list of dicts with participant_id, node_id,
    execution_unit_id, assigned (list), shared (list), metadata (list).
    """
    units = set()
    for layer in range(layers):
        units.add(f"state.layer.{layer}")
    units.update({"state.embedding", "state.final_norm", "state.output_head",
                  "metadata.config.json"})
    plan = {
        "schema": PLAN_SCHEMA,
        "epoch": epoch,
        "candidate_id": "dense.6171f32b4413",
        "model": {
            "model_id": model_id,
            "revision": revision,
            "representation": representation,
            "checkpoint_authority_sha256": checkpoint_authority,
            "layer_count": layers,
            "tie_word_embeddings": tied,
            "execution": execution,
            "backend": dict(backend),
        },
        "logical_state_units": [{"id": u} for u in sorted(units)],
        "participants": [
            {"participant_id": p["participant_id"], "node_id": p["node_id"],
             "execution_unit_id": p["execution_unit_id"],
             "required_state": {
                 "assigned_logical_state": sorted(p["assigned"]),
                 "declared_shared_state": sorted(p["shared"]),
                 "required_metadata": sorted(p["metadata"]),
             }}
            for p in participants_spec
        ],
    }
    plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
    return plan


class ManifestResolver:
    """Resolver over the SOURCE-built manifest: (class, id) -> artifact records.

    Serves frozen descriptors only; no byte access. Content digests were
    computed by the SOURCE-side builder over the exact checkpoint ranges.
    """

    def __init__(self, manifest_records: dict):
        # manifest_records: {"class|id": [record, ...]}
        self._records = manifest_records

    def __call__(self, requirement_class, requirement_id):
        key = f"{requirement_class}|{requirement_id}"
        records = self._records.get(key)
        if records is None:
            raise ValueError(f"manifest has no records for {key}")
        return [dict(r) for r in records]


def derive_participant_requirements(plan, resolver):
    """Faithful re-implementation of the accepted #99 derivation (issue99
    semantics preserved: coverage, class agreement, provenance triple match,
    per-participant digest, document digest). Kept structurally identical to
    scripts/issue99_artifact_core.derive_participant_requirements.
    """
    validate_self_identity(plan, identity_field="plan_digest")
    model = plan["model"]
    declared_unit_ids = {unit["id"] for unit in plan["logical_state_units"]}
    participants_out = []
    for participant in plan["participants"]:
        required_state = participant["required_state"]
        declared: dict[str, str] = {}
        for requirement_class in REQUIREMENT_CLASSES:
            for requirement_id in required_state[requirement_class]:
                if requirement_id not in declared_unit_ids:
                    raise ValueError(f"UNDECLARED_REQUIREMENT_ARTIFACT {requirement_id}")
                if requirement_id in declared:
                    raise ValueError("REQUIRED_STATE_COVERAGE_INCOMPLETE duplicate")
                declared[requirement_id] = requirement_class
        records = {}
        satisfied_by = {rid: [] for rid in declared}
        for requirement_class in REQUIREMENT_CLASSES:
            for requirement_id in required_state[requirement_class]:
                produced = resolver(requirement_class, requirement_id)
                if not produced:
                    raise ValueError(f"REQUIRED_STATE_COVERAGE_INCOMPLETE {requirement_id}")
                for raw in produced:
                    provenance = raw["provenance"]
                    if (provenance["model_id"], provenance["revision"],
                            provenance["representation"]) != (
                            model["model_id"], model["revision"],
                            model["representation"]):
                        raise ValueError("PROVENANCE_IDENTITY_MISMATCH")
                    for state_id in raw["satisfies_logical_state_ids"]:
                        if state_id not in declared:
                            raise ValueError(f"UNDECLARED_REQUIREMENT_ARTIFACT {state_id}")
                        if declared[state_id] != raw["requirement_class"]:
                            raise ValueError(
                                f"UNDECLARED_REQUIREMENT_ARTIFACT class mismatch {state_id}")
                        satisfied_by[state_id].append(raw["artifact_id"])
                    records[raw["artifact_id"]] = raw
        missing = sorted(rid for rid, ids in satisfied_by.items() if not ids)
        if missing:
            raise ValueError(f"REQUIRED_STATE_COVERAGE_INCOMPLETE uncovered {missing}")
        participant_doc = {
            "plan_digest": plan["plan_digest"],
            "participant_id": participant["participant_id"],
            "node_id": participant["node_id"],
            "execution_unit_id": participant["execution_unit_id"],
            "required_logical_state": {
                "assigned": sorted(required_state["assigned_logical_state"]),
                "declared_shared": sorted(required_state["declared_shared_state"]),
                "required_metadata": sorted(required_state["required_metadata"]),
            },
            "required_artifacts": [records[aid] for aid in sorted(records)],
            "required_artifact_bytes": sum(r["length"] for r in records.values()),
        }
        participant_doc["participant_requirements_digest"] = self_digest(
            participant_doc, identity_field="participant_requirements_digest")
        participants_out.append(participant_doc)
    document = {
        "schema": REQUIREMENTS_SCHEMA,
        "plan_digest": plan["plan_digest"],
        "model": dict(model),
        "participants": participants_out,
    }
    document["requirements_digest"] = self_digest(document,
                                                  identity_field="requirements_digest")
    return document
