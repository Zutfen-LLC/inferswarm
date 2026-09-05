#!/usr/bin/env python3
"""InferSwarm issue #99 compact proving model + strategy adapter (CPU-only).

This module is the MODEL-SPECIFIC side of the issue #99 seam. Everything the
generic acquisition core must never learn lives here:

- the frozen compact fixture model ("issue99/mini-lm-8l") written in real
  safetensors-format bytes with a pure-stdlib codec (8-byte little-endian
  header length + JSON header + raw tensor data, 8-byte-aligned header);
- the Model Execution Strategy resolver mapping Logical State Unit
  requirements to immutable byte-range/whole-object artifacts inside the
  upstream repository objects. One LSU may resolve to SEVERAL artifacts
  (``model.shared.final`` spans two non-contiguous tensor groups), proving
  that upstream file, artifact, and Logical State Unit boundaries stay
  distinct (ADR 0009 rule 3);
- the participant runtime that turns VERIFIED cached artifacts into bounded
  staged Materializations (allow-list enforced, unplanned fetch refused) and
  executes the chained two-partition workload purely from materialized
  tensors.

The fixture deliberately contains unrelated model state (vision adapter, MTP
head, six unassigned layers): a correct participant must never acquire any of
it merely because it exists upstream.

The oracle execution digest is computed source-side by operator scaffolding
reading the complete repository (legal research scaffolding under ADR 0009
rule 11); canonical participants never possess that repository.

Pure stdlib. Deterministic: every value derives from frozen seeds.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import (
    AcquisitionError,
    digest_of_bytes,
    fail,
    freeze_artifact_record,
    self_digest,
)

MINI_MODEL_ID = "issue99/mini-lm-8l"
MINI_MODEL_REVISION = "99f1" * 10
MINI_MODEL_REPRESENTATION = "native-f32"
MINI_MODEL_SEED = "inferswarm-issue-99-mini-lm-v1"
WIDTH = 32
VOCAB = 128
NUM_LAYERS = 8
LAYER_A, LAYER_B = 2, 5
INPUT_TOKEN_IDS = (1, 42, 7, 13)
TRANSFORM_ID = "pack.f32-row-major"
TRANSFORM_VERSION = 1
BOUNDARY_DTYPE = "float32"
BOUNDARY_LAYOUT = "plane-major-contiguous"

SHARD_1 = "model-00001-of-00002.safetensors"
SHARD_2 = "model-00002-of-00002.safetensors"
VISION_OBJECT = "vision-adapter.safetensors"
MTP_OBJECT = "mtp-head.safetensors"
CONFIG_OBJECT = "runtime-config.json"
CATALOG_OBJECT = "source-catalog.json"

PLAN_SCHEMA = "inferswarm.issue99.frozen-plan/1"
CATALOG_SCHEMA = "inferswarm.issue99.source-catalog/1"


# ---------------------------------------------------------------------------
# Pure-stdlib safetensors-format codec (fixture layout only)
# ---------------------------------------------------------------------------


def _deterministic_f32_values(key: str, count: int) -> list[float]:
    """Deterministic small floats in [-1, 1) derived from frozen seeds."""
    values = []
    counter = 0
    while len(values) < count:
        material = hashlib.sha256(
            f"{MINI_MODEL_SEED}:{key}:{counter}".encode()).digest()
        for index in range(0, 32, 2):
            raw = int.from_bytes(material[index:index + 2], "big")
            values.append((raw % 20001 - 10000) / 10000.0)
            if len(values) == count:
                break
        counter += 1
    return values


def write_safetensors(
        path: Path, tensors: Mapping[str, tuple[Sequence[int], list[float]]]) -> bytes:
    """Write tensors in sorted-key order; returns the exact file bytes.

    Layout follows the safetensors format: u64 little-endian header length,
    JSON header (padded to 8 bytes), then packed little-endian f32 data in
    header order. Data offsets in the header are relative to the data start.
    """
    layout = {}
    offset = 0
    body = bytearray()
    for key in sorted(tensors):
        shape, values = tensors[key]
        count = 1
        for dim in shape:
            count *= dim
        if count != len(values):
            raise ValueError(f"{key}: {len(values)} values for shape {shape}")
        packed = struct.pack(f"<{count}f", *values)
        layout[key] = {
            "dtype": "F32",
            "shape": list(shape),
            "data_offsets": [offset, offset + len(packed)],
        }
        body.extend(packed)
        offset += len(packed)
    header_bytes = json.dumps(layout, sort_keys=True,
                              separators=(",", ":")).encode()
    header_bytes += b" " * ((-len(header_bytes)) % 8)
    data = struct.pack("<Q", len(header_bytes)) + header_bytes + bytes(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def safetensors_header(data: bytes) -> dict[str, Any]:
    (header_len,) = struct.unpack("<Q", data[:8])
    return json.loads(data[8:8 + header_len])


def safetensors_data_start(data: bytes) -> int:
    (header_len,) = struct.unpack("<Q", data[:8])
    return 8 + header_len


def tensor_abs_range(data: bytes, key: str) -> tuple[int, int]:
    """Absolute byte range [start, end) of one tensor inside the object."""
    header = safetensors_header(data)
    start, end = header[key]["data_offsets"]
    base = safetensors_data_start(data)
    return base + start, base + end


# ---------------------------------------------------------------------------
# Fixture repository + source catalog
# ---------------------------------------------------------------------------


def layer_tensor_keys(layer: int) -> list[str]:
    return [f"layers.{layer}.attn_in.weight", f"layers.{layer}.mlp_out.weight"]


def _shard_one_tensors() -> dict[str, tuple[Sequence[int], list[float]]]:
    tensors: dict[str, tuple[Sequence[int], list[float]]] = {
        "embed_tokens.weight": ([VOCAB, WIDTH],
                                _deterministic_f32_values("embed", VOCAB * WIDTH)),
        "rope.freqs": ([WIDTH], _deterministic_f32_values("rope", WIDTH)),
    }
    for layer in range(0, 4):
        for key in layer_tensor_keys(layer):
            tensors[key] = ([WIDTH, WIDTH],
                            _deterministic_f32_values(key, WIDTH * WIDTH))
    return tensors


def _shard_two_tensors() -> dict[str, tuple[Sequence[int], list[float]]]:
    tensors: dict[str, tuple[Sequence[int], list[float]]] = {}
    for layer in range(4, NUM_LAYERS):
        for key in layer_tensor_keys(layer):
            tensors[key] = ([WIDTH, WIDTH],
                            _deterministic_f32_values(key, WIDTH * WIDTH))
    tensors["final_norm.weight"] = ([WIDTH],
                                    _deterministic_f32_values("final_norm", WIDTH))
    tensors["lm_head.weight"] = ([VOCAB, WIDTH],
                                 _deterministic_f32_values("lm_head", VOCAB * WIDTH))
    return tensors


def build_mini_model_repository(root: Path) -> dict[str, Any]:
    """Build the frozen fixture repository and its operator source catalog.

    Returns the catalog document (per-object identity, per-tensor absolute
    byte ranges, workload oracle). The catalog is operator/source-side
    knowledge; participants never receive it.
    """
    root = Path(root)
    objects: dict[str, bytes] = {}
    objects[SHARD_1] = write_safetensors(root / SHARD_1, _shard_one_tensors())
    objects[SHARD_2] = write_safetensors(root / SHARD_2, _shard_two_tensors())
    objects[VISION_OBJECT] = write_safetensors(
        root / VISION_OBJECT,
        {"vision.proj.weight": ([WIDTH, WIDTH],
                                _deterministic_f32_values("vision", WIDTH * WIDTH))})
    objects[MTP_OBJECT] = write_safetensors(
        root / MTP_OBJECT,
        {"mtp.head.weight": ([WIDTH, WIDTH],
                             _deterministic_f32_values("mtp", WIDTH * WIDTH))})
    config = {
        "model_id": MINI_MODEL_ID,
        "revision": MINI_MODEL_REVISION,
        "representation": MINI_MODEL_REPRESENTATION,
        "num_layers": NUM_LAYERS,
        "width": WIDTH,
        "vocab": VOCAB,
        "layer_partition": {"exec.a": LAYER_A, "exec.b": LAYER_B},
    }
    objects[CONFIG_OBJECT] = canonical_json_bytes(config)
    (root / CONFIG_OBJECT).write_bytes(objects[CONFIG_OBJECT])

    tensors = {}
    for name in (SHARD_1, SHARD_2, VISION_OBJECT, MTP_OBJECT):
        data = objects[name]
        for key, spec in safetensors_header(data).items():
            start, end = tensor_abs_range(data, key)
            tensors[key] = {
                "object": name,
                "dtype": "F32",
                "shape": spec["shape"],
                "byte_start": start,
                "byte_end": end,
                "byte_count": end - start,
            }
    oracle = oracle_execution(root)
    catalog = {
        "schema": CATALOG_SCHEMA,
        "model": {
            "model_id": MINI_MODEL_ID,
            "revision": MINI_MODEL_REVISION,
            "representation": MINI_MODEL_REPRESENTATION,
        },
        "objects": {
            name: {"digest": digest_of_bytes(data), "length": len(data)}
            for name, data in objects.items()
        },
        "tensors": tensors,
        "required_text_state_keys": sorted(
            key for key in tensors
            if not key.startswith("vision.") and not key.startswith("mtp.")),
        "unrelated_state_keys": sorted(
            key for key in tensors
            if key.startswith("vision.") or key.startswith("mtp.")),
        "oracle": oracle,
    }
    catalog["catalog_digest"] = self_digest(catalog)
    (root / CATALOG_OBJECT).write_bytes(canonical_json_bytes(catalog))
    return catalog


# ---------------------------------------------------------------------------
# Deterministic execution (identical code path for oracle and participants)
# ---------------------------------------------------------------------------


def _matmul_rows(vector: list[float], matrix: list[list[float]]) -> list[float]:
    width = len(matrix[0])
    out = [0.0] * width
    for row, factor in zip(matrix, vector):
        for column in range(width):
            out[column] += factor * row[column]
    return out


def forward_layer(hidden: list[list[float]], weights: Mapping[str, list[list[float]]],
                  rope: list[float]) -> list[list[float]]:
    """One fixture layer: h = (h + h@W_in) * rope, then h @ W_out."""
    attn_in = weights["attn_in"]
    mlp_out = weights["mlp_out"]
    out = []
    for row in hidden:
        combined = [a + b for a, b in zip(row, _matmul_rows(row, attn_in))]
        scaled = [value * rope[index] for index, value in enumerate(combined)]
        out.append(_matmul_rows(scaled, mlp_out))
    return out


def boundary_pack(hidden: list[list[float]]) -> bytes:
    return struct.pack(f"<{len(hidden) * WIDTH}f",
                       *[value for row in hidden for value in row])


def stage_one(embed_rows: list[list[float]],
              layer_weights: Mapping[str, list[list[float]]],
              rope: list[float]) -> list[list[float]]:
    hidden = [list(row) for row in embed_rows]
    return forward_layer(hidden, layer_weights, rope)


def stage_two(hidden: list[list[float]], layer_weights: Mapping[str, list[list[float]]],
              rope: list[float], final_norm: list[float],
              lm_head: list[list[float]]) -> dict[str, Any]:
    hidden = forward_layer([list(row) for row in hidden], layer_weights, rope)
    normed = [[value * final_norm[index] for index, value in enumerate(row)]
              for row in hidden]
    logits = []
    decisions = []
    for row in normed:
        scores = [sum(value * head_value for value, head_value in zip(row, head_row))
                  for head_row in lm_head]
        best = max(range(len(scores)), key=lambda i: (scores[i], -i))
        logits.append(scores)
        decisions.append(best)
    packed = struct.pack(f"<{len(logits) * VOCAB}f",
                         *[value for row in logits for value in row])
    return {
        "decisions": decisions,
        "logits_digest": digest_of_bytes(packed),
        "final_hidden_digest": digest_of_bytes(boundary_pack(normed)),
    }


def unpack_f32_rows(data: bytes, rows: int, columns: int) -> list[list[float]]:
    """Unpack packed little-endian f32 payload bytes into rows."""
    flat = struct.unpack(f"<{rows * columns}f", data)
    return [list(flat[i * columns:(i + 1) * columns]) for i in range(rows)]


_unpack_rows = unpack_f32_rows


def _read_tensor_2d(data: bytes, key: str) -> list[list[float]]:
    header = safetensors_header(data)
    shape = header[key]["shape"]
    start, end = tensor_abs_range(data, key)
    columns = shape[1] if len(shape) > 1 else 1
    return _unpack_rows(data[start:end], shape[0], columns)


def oracle_execution(root: Path) -> dict[str, Any]:
    """Operator-scaffolding execution reading the COMPLETE local repository.

    Legal research scaffolding (ADR 0009 rule 11): it exists only to
    precompute the workload's expected identity. Canonical participants must
    reproduce these digests without ever possessing the repository.
    """
    shard1 = (root / SHARD_1).read_bytes()
    shard2 = (root / SHARD_2).read_bytes()

    def tensor(key: str) -> list[list[float]]:
        data = shard1 if key in safetensors_header(shard1) else shard2
        return _read_tensor_2d(data, key)

    embed = tensor("embed_tokens.weight")
    rope = [row[0] for row in tensor("rope.freqs")]
    final_norm = [row[0] for row in tensor("final_norm.weight")]

    def layer_weights(layer: int) -> dict[str, list[list[float]]]:
        return {"attn_in": tensor(f"layers.{layer}.attn_in.weight"),
                "mlp_out": tensor(f"layers.{layer}.mlp_out.weight")}

    embed_rows = [list(embed[token_id]) for token_id in INPUT_TOKEN_IDS]
    hidden = stage_one(embed_rows, layer_weights(LAYER_A), rope)
    boundary = boundary_pack(hidden)
    # The boundary contract is exact f32 bytes: the consumer consumes the
    # packed payload, not the producer's live doubles. The oracle round-trips
    # the same bytes so both arms execute on identical values.
    hidden = _unpack_rows(boundary, len(INPUT_TOKEN_IDS), WIDTH)
    result = stage_two(hidden, layer_weights(LAYER_B), rope, final_norm,
                       tensor("lm_head.weight"))
    workload = {
        "input_token_ids": list(INPUT_TOKEN_IDS),
        "tokens": len(INPUT_TOKEN_IDS),
        "boundary": {
            "dtype": BOUNDARY_DTYPE,
            "layout": BOUNDARY_LAYOUT,
            "token_count": len(INPUT_TOKEN_IDS),
            "width": WIDTH,
            "element_bytes": 4,
            "payload_bytes": len(boundary),
        },
        "expected_boundary_digest": digest_of_bytes(boundary),
        "expected_decisions": result["decisions"],
        "expected_logits_digest": result["logits_digest"],
        "expected_final_hidden_digest": result["final_hidden_digest"],
    }
    workload["workload_digest"] = self_digest(workload)
    return workload


# ---------------------------------------------------------------------------
# Model Execution Strategy resolver (LSU -> artifacts) + plan construction
# ---------------------------------------------------------------------------

ASSIGNED_STATES = {
    "exec.a": ["model.shared.embed", "model.block.2"],
    "exec.b": ["model.block.5", "model.shared.final"],
    "exec.c": ["model.shared.embed", "model.block.2"],
}
SHARED_STATES = ["model.shared.rope"]
METADATA_STATES = ["runtime.graph-config"]

_STATE_TENSOR_KEYS = {
    "model.shared.embed": ["embed_tokens.weight"],
    "model.block.2": layer_tensor_keys(LAYER_A),
    "model.block.5": layer_tensor_keys(LAYER_B),
    "model.shared.final": ["final_norm.weight", "lm_head.weight"],
    "model.shared.rope": ["rope.freqs"],
}


def _contiguous_groups(catalog: Mapping[str, Any],
                       tensor_keys: Sequence[str]) -> list[list[str]]:
    """Group a state's tensors into contiguous byte ranges in one object.

    Each group becomes one artifact; a state whose tensors are not adjacent
    upstream resolves to several artifacts (LSU != upstream file != artifact).
    """
    specs = [(catalog["tensors"][key]["byte_start"],
              catalog["tensors"][key]["byte_end"], key) for key in tensor_keys]
    specs.sort()
    groups: list[list[str]] = []
    for start, end, key in specs:
        if groups and _group_bounds(catalog, groups[-1])[1] == start:
            groups[-1].append(key)
        else:
            groups.append([key])
    return groups


def _group_bounds(catalog: Mapping[str, Any], group: Sequence[str]) -> tuple[int, int]:
    specs = [catalog["tensors"][key] for key in group]
    return (min(spec["byte_start"] for spec in specs),
            max(spec["byte_end"] for spec in specs))


def state_artifact_ranges(catalog: Mapping[str, Any],
                          state_id: str) -> list[dict[str, Any]]:
    """Strategy view: the exact covering ranges per state (no gaps allowed)."""
    ranges = []
    for group in _contiguous_groups(catalog, _STATE_TENSOR_KEYS[state_id]):
        start, end = _group_bounds(catalog, group)
        name = catalog["tensors"][group[0]]["object"]
        ranges.append({
            "source_object": name,
            "tensor_keys": sorted(group),
            "byte_start": start,
            "byte_end": end,
        })
    return ranges


class MiniLmStrategyResolver:
    """Strategy adapter: the only component mapping LSUs to concrete objects.

    Holds the operator-side catalog view (source root) and produces frozen
    artifact records. The generic core treats its output as opaque.
    """

    def __init__(self, *, catalog: Mapping[str, Any], source_root: Path,
                 revision: str = MINI_MODEL_REVISION,
                 representation: str = MINI_MODEL_REPRESENTATION) -> None:
        self.catalog = catalog
        self.source_root = Path(source_root)
        self.revision = revision
        self.representation = representation

    def _object_bytes(self, name: str) -> bytes:
        return (self.source_root / name).read_bytes()

    def __call__(self, requirement_class: str, requirement_id: str) -> list[dict[str, Any]]:
        if requirement_id == "runtime.graph-config":
            data = self._object_bytes(CONFIG_OBJECT)
            return [freeze_artifact_record(
                kind="whole_object",
                content=data,
                model_id=self.catalog["model"]["model_id"],
                revision=self.revision,
                representation=self.representation,
                satisfies_logical_state_ids=[requirement_id],
                requirement_class="required_metadata",
                origin={
                    "source_object": CONFIG_OBJECT,
                    "source_object_digest": self.catalog["objects"][CONFIG_OBJECT]["digest"],
                    "source_object_length": len(data),
                },
            )]
        if requirement_id not in _STATE_TENSOR_KEYS:
            return []
        records = []
        for artifact_range in state_artifact_ranges(self.catalog, requirement_id):
            name = artifact_range["source_object"]
            start, end = artifact_range["byte_start"], artifact_range["byte_end"]
            data = self._object_bytes(name)[start:end]
            records.append(freeze_artifact_record(
                kind="byte_range",
                content=data,
                model_id=self.catalog["model"]["model_id"],
                revision=self.revision,
                representation=self.representation,
                satisfies_logical_state_ids=[requirement_id],
                requirement_class=requirement_class,
                origin={
                    "source_object": name,
                    "source_object_digest": self.catalog["objects"][name]["digest"],
                    "source_object_length": self.catalog["objects"][name]["length"],
                    "byte_start": start,
                    "byte_end": end,
                },
            ))
        return records


def materialization_adapter_data(catalog: Mapping[str, Any],
                                 participant: Mapping[str, Any]) -> dict[str, Any]:
    """Per-LSU tensor placement (strategy view) carried inside the frozen plan.

    R2-style ``adapter_data``: absolute tensor ranges so the participant
    runtime can stage tensors out of verified artifact bytes without ever
    seeing the upstream repository or its layout.
    """
    states = (participant["required_state"]["assigned_logical_state"]
              + participant["required_state"]["declared_shared_state"])
    materializations = {}
    for state_id in states:
        specs = []
        for key in _STATE_TENSOR_KEYS[state_id]:
            tensor = catalog["tensors"][key]
            specs.append({
                "tensor_key": key,
                "source_object": tensor["object"],
                "byte_start": tensor["byte_start"],
                "byte_end": tensor["byte_end"],
                "shape": tensor["shape"],
                "byte_count": tensor["byte_count"],
            })
        materializations[state_id] = {
            "tensors": specs,
            "expected_bytes": sum(spec["byte_count"] for spec in specs),
        }
    config_length = catalog["objects"][CONFIG_OBJECT]["length"]
    return {
        "materializations": materializations,
        "metadata_expected_bytes": {"runtime.graph-config": config_length},
        "transform": {"transform_id": TRANSFORM_ID, "transform_version": TRANSFORM_VERSION},
    }


def build_frozen_plan(catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the legal two-partition Execution Plan (R1-shaped, internal)."""
    participants = []
    for exec_id, node_id in (("exec.a", "node-alpha"), ("exec.b", "node-alpha"),
                             ("exec.c", "node-beta")):
        participant = {
            "participant_id": exec_id,
            "node_id": node_id,
            "execution_unit_id": exec_id,
            "required_state": {
                "assigned_logical_state": list(ASSIGNED_STATES[exec_id]),
                "declared_shared_state": list(SHARED_STATES),
                "required_metadata": list(METADATA_STATES),
            },
        }
        participant["adapter_data"] = materialization_adapter_data(catalog, participant)
        participants.append(participant)
    plan = {
        "schema": PLAN_SCHEMA,
        "model": {
            "model_id": catalog["model"]["model_id"],
            "revision": catalog["model"]["revision"],
            "representation": catalog["model"]["representation"],
        },
        "strategy": {
            "strategy_id": "mini-lm-two-partition-v1",
            "resolver": "issue99_mini_model.MiniLmStrategyResolver",
            "selected_before_execution": True,
        },
        "logical_state_units": [
            {"id": "model.shared.embed", "semantic_class": "immutable_source",
             "sharing": "owned", "owners": ["exec.a", "exec.c"]},
            {"id": "model.block.2", "semantic_class": "immutable_source",
             "sharing": "owned", "owners": ["exec.a", "exec.c"]},
            {"id": "model.block.5", "semantic_class": "immutable_source",
             "sharing": "owned", "owners": ["exec.b"]},
            {"id": "model.shared.final", "semantic_class": "immutable_source",
             "sharing": "owned", "owners": ["exec.b"]},
            {"id": "model.shared.rope", "semantic_class": "immutable_source",
             "sharing": "explicitly_duplicated_immutable", "owners": ["exec.a", "exec.b", "exec.c"]},
            {"id": "runtime.graph-config", "semantic_class": "derived_reconstructible",
             "sharing": "explicitly_duplicated_immutable",
             "owners": ["exec.a", "exec.b", "exec.c"]},
        ],
        "participants": participants,
        "execution": {
            "chain": ["exec.a", "exec.b"],
            "recovery_replicas": {"exec.a": ["exec.c"]},
            "boundary": catalog["oracle"]["boundary"],
        },
        "workload": {
            "workload_digest": catalog["oracle"]["workload_digest"],
            "input_token_ids": catalog["oracle"]["input_token_ids"],
            "expected_boundary_digest": catalog["oracle"]["expected_boundary_digest"],
            "expected_decisions": catalog["oracle"]["expected_decisions"],
            "expected_logits_digest": catalog["oracle"]["expected_logits_digest"],
            "expected_final_hidden_digest": catalog["oracle"]["expected_final_hidden_digest"],
        },
    }
    plan["plan_digest"] = self_digest(plan)
    return plan


# ---------------------------------------------------------------------------
# Participant runtime: verified artifacts -> staged Materializations -> execute
# ---------------------------------------------------------------------------


class MiniLmParticipantRuntime:
    """Executes ONLY from verified cached artifacts and materialized tensors.

    Deliberately has no source-repository path and no source client: it can
    never bypass verified acquisition. Unplanned tensor fetches fail closed
    (the N0 selective-loader discipline, applied to cache objects).
    """

    def __init__(self, *, plan: Mapping[str, Any],
                 participant_requirements: Mapping[str, Any],
                 cache: Any) -> None:
        self.plan = plan
        self.requirements = participant_requirements
        self.cache = cache
        self.staging_bytes_read = 0
        self.fetched_tensor_keys: list[str] = []
        participant = next(
            p for p in plan["participants"]
            if p["participant_id"] == participant_requirements["participant_id"])
        self.adapter_data = participant["adapter_data"]
        self._records = {record["artifact_id"]: record
                         for record in participant_requirements["required_artifacts"]}
        self._by_state: dict[str, list[dict[str, Any]]] = {}
        for record in participant_requirements["required_artifacts"]:
            for state_id in record["satisfies_logical_state_ids"]:
                self._by_state.setdefault(state_id, []).append(record)

    def _artifact_bytes(self, record: Mapping[str, Any]) -> bytes:
        data = self.cache.open_verified(record)
        self.staging_bytes_read += len(data)
        return data

    def read_tensor(self, state_id: str, tensor_key: str) -> list[list[float]]:
        """Allow-list enforced selective fetch from a VERIFIED artifact."""
        state_specs = self.adapter_data["materializations"].get(state_id)
        if state_specs is None:
            raise fail("STAGING_UNPLANNED_KEY",
                       f"{state_id} not in this participant's plan")
        spec = next((s for s in state_specs["tensors"]
                     if s["tensor_key"] == tensor_key), None)
        if spec is None:
            raise fail("STAGING_UNPLANNED_KEY",
                       f"{tensor_key} not planned for {state_id}")
        for record in self._by_state.get(state_id, []):
            origin = record["origin"]
            if origin.get("source_object") != spec["source_object"]:
                continue
            if record["kind"] == "byte_range":
                if not (origin["byte_start"] <= spec["byte_start"]
                        and spec["byte_end"] <= origin["byte_end"]):
                    continue
                base = origin["byte_start"]
            else:
                base = 0
            artifact_bytes = self._artifact_bytes(record)
            data = artifact_bytes[spec["byte_start"] - base:spec["byte_end"] - base]
            if len(data) != spec["byte_count"]:
                raise fail("INTEGRITY_DIGEST_MISMATCH",
                           f"{tensor_key} staged {len(data)} bytes")
            self.fetched_tensor_keys.append(tensor_key)
            shape = spec["shape"]
            columns = shape[1] if len(shape) > 1 else 1
            return _unpack_rows(data, shape[0], columns)
        raise fail("STAGING_UNPLANNED_KEY",
                   f"no verified artifact covers {tensor_key}")

    def _materialize_state(self, state_id: str) -> dict[str, Any]:
        state_specs = self.adapter_data["materializations"][state_id]
        staged = [(spec, self.read_tensor(state_id, spec["tensor_key"]))
                  for spec in state_specs["tensors"]]
        packed = bytearray()
        for spec, rows in staged:
            count = 1
            for dim in spec["shape"]:
                count *= dim
            packed.extend(struct.pack(f"<{count}f",
                                      *[value for row in rows for value in row]))
        transform_record = freeze_artifact_record(
            kind="transform",
            content=bytes(packed),
            model_id=self.plan["model"]["model_id"],
            revision=self.plan["model"]["revision"],
            representation=self.plan["model"]["representation"],
            satisfies_logical_state_ids=[state_id],
            requirement_class="assigned_logical_state"
            if state_id in self.requirements["required_logical_state"]["assigned"]
            else "declared_shared_state",
            origin={"transform_inputs": sorted(
                record["artifact_id"] for record in self._by_state.get(state_id, []))},
            transform={
                "transform_id": self.adapter_data["transform"]["transform_id"],
                "transform_version": self.adapter_data["transform"]["transform_version"],
                "staged_tensor_keys": [spec["tensor_key"] for spec, _ in staged],
            })
        return {
            "logical_state_id": state_id,
            "memory_resource_id": "node.ram",
            "representation": (
                f"{self.plan['model']['representation']}:"
                f"{self.adapter_data['transform']['transform_id']}"),
            "role": "required_residency",
            "requirement": "required",
            "persistence": "transient",
            "verification": "VERIFIED_CACHE_SOURCE",
            "expected_bytes": state_specs["expected_bytes"],
            "observed_bytes": state_specs["expected_bytes"],
            "source_artifact_ids": sorted(
                record["artifact_id"] for record in self._by_state.get(state_id, [])),
            "transform_id": transform_record["transform"]["transform_id"],
            "transform_version": transform_record["transform"]["transform_version"],
            "transform_content_digest": transform_record["content_digest"],
        }

    def _materialize_metadata(self, state_id: str) -> dict[str, Any]:
        record = self._by_state[state_id][0]
        data = self._artifact_bytes(record)
        expected = self.adapter_data["metadata_expected_bytes"][state_id]
        if len(data) != expected:
            raise fail("INTEGRITY_DIGEST_MISMATCH",
                       f"{state_id} staged {len(data)} bytes")
        return {
            "logical_state_id": state_id,
            "memory_resource_id": "node.ram",
            "representation": "runtime-metadata:json",
            "role": "required_residency",
            "requirement": "required",
            "persistence": "transient",
            "verification": "VERIFIED_CACHE_SOURCE",
            "expected_bytes": expected,
            "observed_bytes": len(data),
            "source_artifact_ids": [record["artifact_id"]],
            "transform_id": "identity",
            "transform_version": 1,
            "transform_content_digest": record["content_digest"],
        }

    def materialize(self) -> list[dict[str, Any]]:
        """Stage every planned Logical State Unit into accounted Materializations."""
        tensor_states = set(self.adapter_data["materializations"])
        metadata_states = set(self.requirements["required_logical_state"]["required_metadata"])
        materializations = []
        for state_id in sorted(tensor_states | metadata_states):
            if state_id in tensor_states:
                materializations.append(self._materialize_state(state_id))
            else:
                materializations.append(self._materialize_metadata(state_id))
        return materializations

    def execute_stage_one(self) -> dict[str, Any]:
        embed = self.read_tensor("model.shared.embed", "embed_tokens.weight")
        weights = {
            "attn_in": self.read_tensor("model.block.2", "layers.2.attn_in.weight"),
            "mlp_out": self.read_tensor("model.block.2", "layers.2.mlp_out.weight"),
        }
        rope = [row[0] for row in self.read_tensor("model.shared.rope", "rope.freqs")]
        rows = [list(embed[token_id]) for token_id in self.plan["workload"]["input_token_ids"]]
        hidden = stage_one(rows, weights, rope)
        boundary = boundary_pack(hidden)
        return {
            "boundary_payload_bytes": len(boundary),
            "boundary_digest": digest_of_bytes(boundary),
            "hidden": hidden,
        }

    def execute_stage_two(self, hidden: list[list[float]]) -> dict[str, Any]:
        weights = {
            "attn_in": self.read_tensor("model.block.5", "layers.5.attn_in.weight"),
            "mlp_out": self.read_tensor("model.block.5", "layers.5.mlp_out.weight"),
        }
        rope = [row[0] for row in self.read_tensor("model.shared.rope", "rope.freqs")]
        final_norm = [row[0] for row in
                      self.read_tensor("model.shared.final", "final_norm.weight")]
        lm_head = self.read_tensor("model.shared.final", "lm_head.weight")
        result = stage_two(hidden, weights, rope, final_norm, lm_head)
        return result
