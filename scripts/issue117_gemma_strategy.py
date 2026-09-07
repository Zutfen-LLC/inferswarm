#!/usr/bin/env python3
"""Issue #117 Gemma dense Model Execution Strategy (CPU-side seam).

This module is the ONLY place where model-family and accepted-campaign nouns
for the #117 integration live (the strategy/constrains side of the accepted
"strategy constrains; planner chooses" rule). It provides:

1. **Frozen subject identity** carried over unchanged from the accepted V5
   physical subject (model, revision, checkpoint, representation, backend,
   execution semantics).
2. **Frozen resource identity** for the Compute Units retained by the
   accepted V5 evidence (inferswarm01 GPU-0/GPU-1, inferswarm03 GPU-0 as the
   serving chain; inferswarm04 GPU-0 as the reference-reserved RTX 3090 path;
   inferswarm00 as the CPU-only Coordinator).
3. **Legal dense candidate enumeration**: contiguous balanced dense pipeline
   stage structures over the frozen Compute Unit chain, for declared legal
   stage counts. Capacity data comes from an operator-supplied capacity
   model; this module never invents hardware capacities.
4. **Checkpoint catalog mapping**: exact tensor -> logical-state -> byte-range
   artifact records derived from the real checkpoint layout (config.json +
   safetensors headers), including the tied-output-head shared-state rule.
5. **Qualification subjects**: the canonical opaque descriptor of what would
   have to match accepted qualification evidence for a candidate to inherit
   it; the accepted V5 evidence is bound as a deterministic record.

The generic planner (``issue117_planner``) must never import this module.

Pure stdlib; reads at most safetensors headers and config JSON — never
initializes a model runtime.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import (
    digest_of_bytes,
    freeze_artifact_record,
    self_digest,
)

STRATEGY_SCHEMA = "inferswarm.issue117.gemma-dense-strategy/1"
CATALOG_SCHEMA = "inferswarm.issue117.checkpoint-catalog/1"
PLAN_SCHEMA = "inferswarm.issue117.execution-plan/1"
QUALIFICATION_RECORD_SCHEMA = "inferswarm.issue117.qualification-record/1"

#: Layer count of the frozen physical subject, exactly as qualified by the
#: accepted V5 three-stage geometry [0,16) / [16,32) / [32,48).
LAYER_COUNT = 48

#: Dense pipeline structures this strategy declares legal (semantic
#: boundaries are strategy-owned). Balanced-stage dense chains only.
ALLOWED_STAGE_COUNTS = (1, 2, 3)

CONFIG_OBJECT = "config.json"
TOKENIZER_META_OBJECT = "tokenizer-metadata.json"

MODEL_SUBJECT: dict[str, Any] = {
    "model_id": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_sha256": "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
    "representation": "checkpoint-safetensors",
    "execution": "native BF16 text execution; Triton attention; one <=64-row replay chunk",
    "backend": {
        "torch": "2.11.0+cu130",
        "cuda_runtime": "13.0",
        "nvidia_driver": "610.57.04",
        "triton": "3.6.0",
        "flashinfer": "0.6.17",
    },
}

#: Compute Unit identities retained by the accepted V5 evidence, in canonical
#: dense-chain order. ``vram_bytes`` are public specification capacities; the
#: usable execution capacity is an operator-supplied capacity model, never a
#: constant invented here.
RESOURCE_SNAPSHOT: dict[str, Any] = {
    "snapshot_id": "issue117-frozen-resource-identity-v1",
    "coordinator": {"node": "inferswarm00", "cpu_only": True},
    "chain_order": [
        "inferswarm01/gpu-0",
        "inferswarm01/gpu-1",
        "inferswarm03/gpu-0",
        "inferswarm04/gpu-0",
    ],
    "compute_units": [
        {"cu_id": "inferswarm01/gpu-0", "node": "inferswarm01", "gpu_index": 0,
         "product": "NVIDIA GeForce RTX 3060", "vram_bytes": 12 * 1024**3,
         "role": "serving-candidate"},
        {"cu_id": "inferswarm01/gpu-1", "node": "inferswarm01", "gpu_index": 1,
         "product": "NVIDIA GeForce RTX 3060", "vram_bytes": 12 * 1024**3,
         "role": "serving-candidate"},
        {"cu_id": "inferswarm03/gpu-0", "node": "inferswarm03", "gpu_index": 0,
         "product": "NVIDIA GeForce RTX 3060", "vram_bytes": 12 * 1024**3,
         "role": "serving-candidate"},
        {"cu_id": "inferswarm04/gpu-0", "node": "inferswarm04", "gpu_index": 0,
         "product": "NVIDIA GeForce RTX 3090", "vram_bytes": 24 * 1024**3,
         "role": "reference-reserved"},
    ],
}

#: Operator hard policy for the canonical correctness-bearing serving arm:
#: the reference-reserved path is not a serving candidate.
SERVING_POLICY = {
    "policy_id": "issue117-canonical-serving-policy-v1",
    "serving_eligible_roles": ("serving-candidate",),
}

#: The exact accepted V5 candidate geometry (retained accepted evidence; a
#: historical constant, not a planner input).
ACCEPTED_V5_GEOMETRY: tuple[dict[str, Any], ...] = (
    {"cu_id": "inferswarm01/gpu-0", "layer_start": 0, "layer_end": 16},
    {"cu_id": "inferswarm01/gpu-1", "layer_start": 16, "layer_end": 32},
    {"cu_id": "inferswarm03/gpu-0", "layer_start": 32, "layer_end": 48},
)


class StrategyError(RuntimeError):
    """Fail-closed strategy construction/mapping error."""


# ---------------------------------------------------------------------------
# Checkpoint catalog (source-side knowledge; exact byte layout, no weights)
# ---------------------------------------------------------------------------


def read_safetensors_header(path: Path) -> tuple[dict[str, Any], int, int]:
    """Read only the safetensors header of a file (never the weight bytes).

    Returns ``(header, data_start, file_length)`` with header data offsets
    relative to ``data_start``.
    """
    with path.open("rb") as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise StrategyError(f"{path.name}: truncated safetensors prefix")
        (header_len,) = struct.unpack("<Q", prefix)
        header_bytes = stream.read(header_len)
    if len(header_bytes) != header_len:
        raise StrategyError(f"{path.name}: truncated safetensors header")
    return json.loads(header_bytes), 8 + header_len, path.stat().st_size


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def catalog_from_repository(root: Path, *, config: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact checkpoint catalog from a real/synthetic repository.

    Reads config JSON, every ``*.safetensors`` file's header (never weight
    bytes), and hashes every object byte-exactly. Tensor byte ranges are
    absolute file offsets, which is what exact Range acquisition consumes.
    """
    objects: dict[str, dict[str, Any]] = {}
    tensors: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.safetensors")):
        header, data_start, file_length = read_safetensors_header(path)
        objects[path.name] = {"length": file_length, "digest": digest_file(path)}
        for key in sorted(header):
            spec = header[key]
            start, end = spec["data_offsets"]
            tensors[key] = {
                "object": path.name,
                "dtype": spec["dtype"],
                "shape": list(spec["shape"]),
                "byte_start": data_start + start,
                "byte_end": data_start + end,
                "byte_count": end - start,
            }
    for extra in sorted(root.glob("*.json")):
        objects[extra.name] = {"length": extra.stat().st_size}
    if CONFIG_OBJECT not in objects:
        raise StrategyError("checkpoint repository has no config.json")
    catalog = {
        "schema": CATALOG_SCHEMA,
        "model": {
            "model_id": config["model_id"],
            "revision": config["revision"],
            "representation": config["representation"],
        },
        "config": {
            "num_hidden_layers": int(config["num_hidden_layers"]),
            "tie_word_embeddings": bool(config["tie_word_embeddings"]),
        },
        "objects": objects,
        "tensors": tensors,
    }
    catalog["catalog_digest"] = self_digest(catalog, identity_field="catalog_digest")
    return catalog


def layer_of_tensor(name: str) -> int | None:
    """Return the decoder layer index a tensor belongs to, else None."""
    prefix = "model.layers."
    if not name.startswith(prefix):
        return None
    rest = name[len(prefix):]
    head = rest.split(".", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


def logical_state_of_tensor(name: str, *, tie_word_embeddings: bool) -> str | None:
    """Map one checkpoint tensor to its Logical State Unit id."""
    if name == "model.embed_tokens.weight":
        return "state.embedding"
    if name == "model.norm.weight":
        return "state.final_norm"
    if name == "model.lm_head.weight":
        return "state.output_head"
    layer = layer_of_tensor(name)
    if layer is not None:
        return f"state.layer.{layer}"
    return None


def weight_unit_ids(catalog: Mapping[str, Any]) -> list[str]:
    """Every logical state unit carried by checkpoint weight bytes."""
    tied = bool(catalog["config"]["tie_word_embeddings"])
    units = set()
    for name in catalog["tensors"]:
        unit = logical_state_of_tensor(name, tie_word_embeddings=tied)
        if unit is not None:
            units.add(unit)
    if tied:
        # the output head is the shared embedding state
        units.add("state.output_head")
    return sorted(units)


def checkpoint_weight_bytes(catalog: Mapping[str, Any]) -> int:
    """Total checkpoint weight bytes (excluding non-weight objects)."""
    total = 0
    for name in catalog["tensors"]:
        if logical_state_of_tensor(
                name, tie_word_embeddings=bool(catalog["config"]["tie_word_embeddings"])):
            total += catalog["tensors"][name]["byte_count"]
    return total


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


def _balanced_stage_sizes(layers: int, stages: int) -> list[int]:
    base, remainder = divmod(layers, stages)
    return [base + (1 if index < remainder else 0) for index in range(stages)]


def _candidate_id(stages: Sequence[Mapping[str, Any]]) -> str:
    payload = canonical_json_bytes([dict(stage) for stage in stages])
    return "dense." + hashlib.sha256(payload).hexdigest()[:12]


class GemmaDenseStrategy:
    """Expose legal opaque dense candidates and exact requirement mappings."""

    def __init__(self, *, catalog: Mapping[str, Any],
                 snapshot: Mapping[str, Any] = RESOURCE_SNAPSHOT,
                 subject: Mapping[str, Any] = MODEL_SUBJECT,
                 source_bytes: Callable[[str], bytes] | None = None):
        if catalog["schema"] != CATALOG_SCHEMA:
            raise StrategyError("catalog schema mismatch")
        self.catalog = catalog
        self.snapshot = snapshot
        self.subject = subject
        self.layers = int(catalog["config"]["num_hidden_layers"])
        self.tied = bool(catalog["config"]["tie_word_embeddings"])
        if self.layers != LAYER_COUNT:
            raise StrategyError(
                f"catalog layer count {self.layers} != frozen subject {LAYER_COUNT}")
        self._cu_by_id = {cu["cu_id"]: cu for cu in snapshot["compute_units"]}
        self._chain = list(snapshot["chain_order"])
        self._source_bytes = source_bytes or (lambda name: _missing_source(name))
        self._plan_cache: dict[str, dict[str, Any]] = {}
        self._records: dict[tuple[str, str], list[dict[str, Any]]] = {}

    # -- candidate enumeration -------------------------------------------------

    def legal_candidates(self, *, capacity_model: Mapping[str, int] | None = None) -> list[dict[str, Any]]:
        """Enumerate the legal dense candidates over the frozen CU chain.

        ``capacity_model`` maps cu_id -> usable weight bytes (operator
        supplied). It influences only ``technical_feasibility`` inputs, never
        the legal set itself.
        """
        candidates: list[dict[str, Any]] = []
        for stage_count in ALLOWED_STAGE_COUNTS:
            if stage_count > len(self._chain):
                continue
            sizes = _balanced_stage_sizes(self.layers, stage_count)
            for start_index in range(0, len(self._chain) - stage_count + 1):
                cu_ids = self._chain[start_index:start_index + stage_count]
                stages = []
                cursor = 0
                for cu_id, size in zip(cu_ids, sizes):
                    stages.append({
                        "cu_id": cu_id,
                        "node": self._cu_by_id[cu_id]["node"],
                        "layer_start": cursor,
                        "layer_end": cursor + size,
                    })
                    cursor += size
                candidate = {
                    "candidate_id": _candidate_id(stages),
                    "stage_count": stage_count,
                    "stages": stages,
                }
                candidate["qualification_subject"] = self.qualification_subject(candidate)
                candidate["qualification_subject_digest"] = digest_of_bytes(
                    canonical_json_bytes(candidate["qualification_subject"]))
                capacity = None
                if capacity_model is not None:
                    capacity = {
                        "stage_weight_bytes": [
                            self.stage_weight_bytes(candidate, index)
                            for index in range(stage_count)
                        ],
                        "usable_weight_bytes": [int(capacity_model[cu_id])
                                                for cu_id in cu_ids],
                    }
                candidate["capacity"] = capacity
                candidates.append(candidate)
        candidates.sort(key=lambda candidate: candidate["candidate_id"])
        return candidates

    def stage_weight_bytes(self, candidate: Mapping[str, Any], stage_index: int) -> int:
        """Exact checkpoint weight bytes assigned to one candidate stage."""
        stage = candidate["stages"][stage_index]
        total = 0
        for name, tensor in self.catalog["tensors"].items():
            layer = layer_of_tensor(name)
            if layer is None or not (stage["layer_start"] <= layer < stage["layer_end"]):
                continue
            total += tensor["byte_count"]
        for name in ("model.norm.weight", "model.lm_head.weight"):
            tensor = self.catalog["tensors"].get(name)
            if tensor is not None and stage_index == len(candidate["stages"]) - 1:
                total += tensor["byte_count"]
        return total

    # -- strategy-owned feasibility and policy inputs --------------------------

    def feasibility(self, candidate: Mapping[str, Any], *,
                    capacity_model: Mapping[str, int] | None = None) -> dict[str, Any]:
        """Technical feasibility + hard operator policy + integrity inputs.

        Technical feasibility requires an operator capacity model; without one
        it is declared unknown and must fail closed in the planner.
        """
        if capacity_model is None:
            return {"technical_feasibility": False, "technical_feasibility_known": False,
                    "hard_policy_eligible": self._serving_policy_eligible(candidate),
                    "integrity_eligible": True}
        per_stage = [self.stage_weight_bytes(candidate, index)
                     for index in range(candidate["stage_count"])]
        usable = [int(capacity_model[stage["cu_id"]]) for stage in candidate["stages"]]
        fits = all(weight <= limit and limit > 0
                   for weight, limit in zip(per_stage, usable))
        return {"technical_feasibility": bool(fits), "technical_feasibility_known": True,
                "stage_weight_bytes": per_stage, "usable_weight_bytes": usable,
                "hard_policy_eligible": self._serving_policy_eligible(candidate),
                "integrity_eligible": True}

    def _serving_policy_eligible(self, candidate: Mapping[str, Any]) -> bool:
        return all(
            self._cu_by_id[stage["cu_id"]]["role"] in SERVING_POLICY["serving_eligible_roles"]
            for stage in candidate["stages"]
        )

    # -- qualification subjects ------------------------------------------------

    def qualification_subject(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        """Opaque descriptor of everything qualification evidence must bind."""
        return {
            "model_id": self.subject["model_id"],
            "revision": self.subject["revision"],
            "checkpoint_sha256": self.subject["checkpoint_sha256"],
            "representation": self.subject["representation"],
            "execution": self.subject["execution"],
            "backend": dict(self.subject["backend"]),
            "layer_count": self.layers,
            "stage_structure": [
                {
                    "cu_id": stage["cu_id"],
                    "node": stage.get("node") or self._cu_by_id[stage["cu_id"]]["node"],
                    "layer_start": stage["layer_start"],
                    "layer_end": stage["layer_end"],
                }
                for stage in candidate["stages"]
            ],
        }

    def accepted_v5_candidate(self, candidates: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Return the enumerated candidate whose geometry is the accepted V5
        geometry; fail closed if the enumeration did not produce it."""
        def geometry(candidate: Mapping[str, Any]) -> list[tuple[str, int, int]]:
            return [(stage["cu_id"], stage["layer_start"], stage["layer_end"])
                    for stage in candidate["stages"]]

        accepted = [(stage["cu_id"], stage["layer_start"], stage["layer_end"])
                    for stage in ACCEPTED_V5_GEOMETRY]
        for candidate in candidates:
            if geometry(candidate) == accepted:
                return candidate
        raise StrategyError("accepted V5 geometry missing from the legal candidate set")

    def accepted_v5_qualification_record(self) -> dict[str, Any]:
        """Deterministic qualification evidence record binding the accepted V5
        terminal result to the exact qualified subject."""
        from issue117_applicability import (
            ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER,
            ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER,
            ACCEPTED_V5_METHODOLOGY,
            ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
        )
        probe = {"candidate_id": "accepted-v5",
                 "stages": [dict(stage) for stage in ACCEPTED_V5_GEOMETRY],
                 "stage_count": len(ACCEPTED_V5_GEOMETRY)}
        subject = self.qualification_subject(probe)
        record = {
            "schema": QUALIFICATION_RECORD_SCHEMA,
            "qualification_record_id": "inferswarm.issue117.v5-qualification/1",
            "authority": {
                "terminal_disposition": "V5_QUALIFICATION_PASS",
                "terminal_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
                "accepted_v5_methodology": ACCEPTED_V5_METHODOLOGY,
                "accepted_freetoken_calibration_producer": ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER,
                "accepted_freetoken_holdout_producer": ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER,
            },
            "qualification_subject": subject,
        }
        record["qualification_subject_digest"] = digest_of_bytes(
            canonical_json_bytes(subject))
        record["record_digest"] = self_digest(record, identity_field="record_digest")
        return record

    # -- frozen plan + requirement resolver (strategy adapter boundary) --------

    def plan(self, candidate: Mapping[str, Any], *, epoch: int = 1) -> dict[str, Any]:
        key = f"{candidate['candidate_id']}#{epoch}"
        if key in self._plan_cache:
            return self._plan_cache[key]
        participants = []
        stage_count = candidate["stage_count"]
        for index, stage in enumerate(candidate["stages"]):
            assigned: list[str] = [
                f"state.layer.{layer}" for layer in range(stage["layer_start"], stage["layer_end"])
            ]
            shared: list[str] = []
            metadata = [f"metadata.{CONFIG_OBJECT}", f"metadata.{TOKENIZER_META_OBJECT}"]
            if index == 0:
                assigned.insert(0, "state.embedding")
            if index == stage_count - 1:
                assigned.append("state.final_norm")
                if self.tied:
                    shared.extend(["state.embedding", "state.output_head"])
                else:
                    assigned.append("state.output_head")
            participants.append({
                "participant_id": f"{candidate['candidate_id']}.stage-{index + 1}",
                "node_id": stage["node"],
                "execution_unit_id": stage["cu_id"],
                "required_state": {
                    "assigned_logical_state": assigned,
                    "declared_shared_state": shared,
                    "required_metadata": metadata,
                },
            })
        plan = {
            "schema": PLAN_SCHEMA,
            "epoch": epoch,
            "candidate_id": candidate["candidate_id"],
            "model": dict(self.catalog["model"]),
            "logical_state_units": [{"id": unit} for unit in self.logical_state_units()],
            "participants": participants,
        }
        plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
        self._plan_cache[key] = plan
        return plan

    def logical_state_units(self) -> list[str]:
        units = weight_unit_ids(self.catalog)
        units.extend([f"metadata.{CONFIG_OBJECT}", f"metadata.{TOKENIZER_META_OBJECT}"])
        return sorted(units)

    def resolve(self, requirement_class: str, requirement_id: str) -> list[dict[str, Any]]:
        """Strategy adapter: logical state requirement -> exact artifact records.

        The only place where checkpoint tensor names and byte ranges become
        plan-driven artifact identities.
        """
        key = (requirement_class, requirement_id)
        if key in self._records:
            return list(self._records[key])
        produced: list[dict[str, Any]] = []
        if requirement_id.startswith("metadata."):
            object_name = requirement_id[len("metadata."):]
            content = self._source_bytes(object_name)
            produced.append(freeze_artifact_record(
                kind="whole_object", content=content,
                model_id=self.catalog["model"]["model_id"],
                revision=self.catalog["model"]["revision"],
                representation=self.catalog["model"]["representation"],
                satisfies_logical_state_ids=[requirement_id],
                requirement_class="required_metadata",
                origin={"source_object": object_name,
                        "source_object_digest": digest_of_bytes(content),
                        "source_object_length": len(content)},
            ))
        elif requirement_id == "state.embedding":
            produced.extend(self._tensor_records(
                ["model.embed_tokens.weight"], requirement_class=requirement_class,
                extra_satisfies=(["state.output_head"]
                                 if requirement_class == "declared_shared_state" else [])))
        elif requirement_id == "state.final_norm":
            produced.extend(self._tensor_records(
                ["model.norm.weight"], requirement_class=requirement_class))
        elif requirement_id == "state.output_head":
            if self.tied:
                if requirement_class != "declared_shared_state":
                    raise StrategyError("tied output head is declared shared state only")
                produced.extend(self._tensor_records(
                    ["model.embed_tokens.weight"], requirement_class=requirement_class,
                    extra_satisfies=["state.output_head"]))
            else:
                produced.extend(self._tensor_records(
                    ["model.lm_head.weight"], requirement_class=requirement_class))
        elif requirement_id.startswith("state.layer."):
            layer = int(requirement_id[len("state.layer."):])
            names = sorted(
                name for name in self.catalog["tensors"]
                if layer_of_tensor(name) == layer
            )
            if not names:
                raise StrategyError(f"no checkpoint tensors for {requirement_id}")
            produced.extend(self._tensor_records(names, requirement_class=requirement_class))
        else:
            raise StrategyError(f"unknown logical state requirement {requirement_id!r}")
        self._records[key] = produced
        return list(produced)

    def _tensor_records(self, names: Sequence[str], *, requirement_class: str,
                        extra_satisfies: Sequence[str] = ()) -> list[dict[str, Any]]:
        records = []
        for name in names:
            tensor = self.catalog["tensors"][name]
            content = self._range_bytes(tensor)
            state_id = logical_state_of_tensor(name, tie_word_embeddings=self.tied)
            satisfies_set: set[str] = set(extra_satisfies)
            if state_id is not None:
                satisfies_set.add(state_id)
            satisfies = sorted(satisfies_set)
            records.append(freeze_artifact_record(
                kind="byte_range", content=content,
                model_id=self.catalog["model"]["model_id"],
                revision=self.catalog["model"]["revision"],
                representation=self.catalog["model"]["representation"],
                satisfies_logical_state_ids=satisfies,
                requirement_class=requirement_class,
                origin={
                    "source_object": tensor["object"],
                    "source_object_digest": self.catalog["objects"][tensor["object"]]["digest"],
                    "source_object_length": self.catalog["objects"][tensor["object"]]["length"],
                    "byte_start": tensor["byte_start"],
                    "byte_end": tensor["byte_end"],
                },
            ))
        return records

    def _range_bytes(self, tensor: Mapping[str, Any]) -> bytes:
        data = self._source_bytes(tensor["object"])
        return bytes(data[tensor["byte_start"]:tensor["byte_end"]])

    def frozen_document(self, candidates: Sequence[Mapping[str, Any]], *,
                        capacity_model: Mapping[str, int] | None = None) -> dict[str, Any]:
        """Strategy-side frozen document: legal set + feasibility + subjects."""
        document = {
            "schema": STRATEGY_SCHEMA,
            "subject": dict(self.subject),
            "resource_snapshot": dict(self.snapshot),
            "layer_count": self.layers,
            "tie_word_embeddings": self.tied,
            "allowed_stage_counts": list(ALLOWED_STAGE_COUNTS),
            "logical_state_units": self.logical_state_units(),
            "candidates": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "stage_count": candidate["stage_count"],
                    "stages": [dict(stage) for stage in candidate["stages"]],
                    "qualification_subject": candidate["qualification_subject"],
                    "qualification_subject_digest": candidate["qualification_subject_digest"],
                    "feasibility": self.feasibility(candidate, capacity_model=capacity_model),
                }
                for candidate in candidates
            ],
        }
        document["strategy_digest"] = self_digest(document, identity_field="strategy_digest")
        return document


def _missing_source(name: str) -> bytes:
    raise StrategyError(f"strategy has no source bytes for {name!r}")


def build_synthetic_gemma_repository(
        root: Path, *, layers: int = LAYER_COUNT, seed: str = "issue117-synthetic-gemma-v1",
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Build a Gemma-shaped synthetic checkpoint (tiny bytes, real layout).

    Two shards whose boundary crosses the accepted stage-1/stage-2 layer
    boundary, tied embeddings (no lm_head tensor), final norm, config.json
    and tokenizer metadata — the structure the exact-mapping derivation must
    handle, at fixture scale. Returns ``(config, objects)``.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    def values(key: str, count: int) -> list[float]:
        out: list[float] = []
        counter = 0
        while len(out) < count:
            material = hashlib.sha256(f"{seed}:{key}:{counter}".encode()).digest()
            for index in range(0, 32, 2):
                raw = int.from_bytes(material[index:index + 2], "big")
                out.append((raw % 20001 - 10000) / 10000.0)
                if len(out) == count:
                    break
            counter += 1
        return out

    vocab, width = 512, 16
    per_layer_tensors = (
        "self_attn.q_proj.weight", "self_attn.o_proj.weight",
        "mlp.gate_proj.weight", "mlp.down_proj.weight",
    )

    def tensor_key(layer: int, suffix: str) -> str:
        return f"model.layers.{layer}.{suffix}"

    # shard boundary at layer 24: stage 2 [16,32) spans both shard files
    shard_one_layers = range(0, 24)
    shard_two_layers = range(24, layers)

    objects: dict[str, bytes] = {}

    def write_object(name: str, tensors: Mapping[str, tuple[list[int], list[float]]]) -> None:
        layout = {}
        offset = 0
        body = bytearray()
        for key in sorted(tensors):
            shape, vals = tensors[key]
            packed = struct.pack(f"<{len(vals)}f", *vals)
            layout[key] = {"dtype": "F32", "shape": list(shape),
                           "data_offsets": [offset, offset + len(packed)]}
            body.extend(packed)
            offset += len(packed)
        header_bytes = json.dumps(layout, sort_keys=True, separators=(",", ":")).encode()
        header_bytes += b" " * ((-len(header_bytes)) % 8)
        data = struct.pack("<Q", len(header_bytes)) + header_bytes + bytes(body)
        (root / name).write_bytes(data)
        objects[name] = data

    shard_one = {
        "model.embed_tokens.weight": ([vocab, width],
                                      values("embed", vocab * width)),
    }
    for layer in shard_one_layers:
        for suffix in per_layer_tensors:
            key = tensor_key(layer, suffix)
            shard_one[key] = ([width, width], values(key, width * width))
    write_object("model-00001-of-00002.safetensors", shard_one)

    shard_two = {}
    for layer in shard_two_layers:
        for suffix in per_layer_tensors:
            key = tensor_key(layer, suffix)
            shard_two[key] = ([width, width], values(key, width * width))
    shard_two["model.norm.weight"] = ([width], values("norm", width))
    write_object("model-00002-of-00002.safetensors", shard_two)

    config = {
        "schema": "inferswarm.issue117.synthetic-checkpoint-config/1",
        "model_id": "synthetic/gemma-shaped-fixture",
        "revision": "issue117-fixture-v1",
        "representation": "checkpoint-safetensors",
        "num_hidden_layers": layers,
        "tie_word_embeddings": True,
        "vocab_size": vocab,
        "hidden_size": width,
    }
    objects[CONFIG_OBJECT] = canonical_json_bytes(config)
    (root / CONFIG_OBJECT).write_bytes(objects[CONFIG_OBJECT])
    tokenizer_meta = {
        "tokenizer_identity": "accepted-v5-tokenizer",
        "note": "metadata only; never weight bytes",
    }
    objects[TOKENIZER_META_OBJECT] = canonical_json_bytes(tokenizer_meta)
    (root / TOKENIZER_META_OBJECT).write_bytes(objects[TOKENIZER_META_OBJECT])
    return config, objects
