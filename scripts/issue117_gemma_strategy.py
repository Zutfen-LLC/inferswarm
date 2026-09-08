#!/usr/bin/env python3
"""Issue #117 Gemma dense Model Execution Strategy (CPU-side seam).

This module is the ONLY place where model-family and accepted-campaign nouns
for the #117 integration live (the strategy/constrains side of the accepted
"strategy constrains; planner chooses" rule). It provides:

1. **Frozen accepted subject identity** carried over unchanged from the
   accepted V5 physical subject (model, revision, checkpoint authority,
   representation, backend, execution semantics).
2. **Frozen resource identity** for the Compute Units retained by the
   accepted V5 evidence (inferswarm01 GPU-0/GPU-1, inferswarm03 GPU-0 as the
   serving chain; inferswarm04 GPU-0 as the reference-reserved RTX 3090 path;
   inferswarm00 as the CPU-only Coordinator).
3. **Legal dense candidate enumeration**: contiguous balanced dense pipeline
   stage structures over the frozen Compute Unit chain, for declared legal
   stage counts. Capacity data comes from an operator-supplied capacity
   model; this module never invents hardware capacities.
4. **Checkpoint catalog mapping** (SOURCE side): exact tensor -> logical
   state -> byte-range artifact records derived from the real checkpoint
   layout. Reading and hashing model bytes happens only here and only in
   ``catalog_from_repository`` / ``build_source_manifest``; the planning
   waist (``GemmaDenseStrategy``) consumes the resulting small immutable
   descriptor manifest and has no byte-access path at all.
5. **Two explicitly separated checkpoint identities.** The catalog carries
   the retained repeated ``checkpoint_authority_sha256`` value and
   ``catalog_content_digest``, a mechanically derived digest over the exact
   repository/catalog content. Neither value is an independent
   byte-to-checkpoint derivation. Neither may masquerade as the other.
6. **Qualification subjects bound to catalog/plan identity**: a candidate's
   qualification subject is derived mechanically from the exact
   catalog/plan that would be executed — never from parallel constants.
   Constructing a strategy whose subject disagrees with its catalog fails
   closed. A synthetic fixture catalog cannot inherit physical qualification.
   The V5-shaped descriptor catalog is a candidate-construction diagnostic.
   It does not reconstruct an accepted V5 qualification subject.

The generic planner (``issue117_planner``) must never import this module.

Pure stdlib. Only the SOURCE-side builder touches model bytes; it never
initializes a model runtime.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from issue74_methodology import canonical_json_bytes, sha256_file
from issue99_artifact_core import (
    digest_of_bytes,
    freeze_artifact_record,
    self_digest,
    validate_artifact_record,
    validate_self_identity,
)
from issue117_subject_identity import execution_equality_subject, subject_digest

STRATEGY_SCHEMA = "inferswarm.issue117.gemma-dense-strategy/2"
CATALOG_SCHEMA = "inferswarm.issue117.checkpoint-catalog/3"
PLAN_SCHEMA = "inferswarm.issue117.execution-plan/2"
QUALIFICATION_RECORD_SCHEMA = "inferswarm.issue117.qualification-record/2"
SOURCE_MANIFEST_SCHEMA = "inferswarm.issue117.source-artifact-manifest/2"
CHECKPOINT_AUTHORITY_ATTESTATION_SCHEMA = (
    "inferswarm.issue117.checkpoint-authority-attestation/1")

#: The checkpoint repository document that attests the observed object set
#: to the accepted external checkpoint authority identity. Required by
#: ``catalog_from_repository``; byte-verified object-by-object.
AUTHORITY_ATTESTATION_OBJECT = "checkpoint-authority.json"

#: Layer count of the frozen physical subject, exactly as qualified by the
#: accepted V5 three-stage geometry [0,16) / [16,32) / [32,48).
LAYER_COUNT = 48

#: Dense pipeline structures this strategy declares legal (semantic
#: boundaries are strategy-owned). Balanced-stage dense chains only.
ALLOWED_STAGE_COUNTS = (1, 2, 3)

CONFIG_OBJECT = "config.json"
TOKENIZER_META_OBJECT = "tokenizer-metadata.json"

#: Backend fields every subject must declare (validated, never optional).
REQUIRED_SUBJECT_BACKEND_KEYS = (
    "torch", "cuda_runtime", "nvidia_driver", "triton", "flashinfer")

#: Retained V5-shaped identity values for fixture construction. The repeated
#: ``checkpoint_authority_sha256`` value is not an independent
#: byte-to-checkpoint derivation. A catalog can carry it only through the
#: retained evidence reader, never as an unchecked config field. This
#: prevents simple config injection. It does not establish qualification
#: authority for observed checkpoint bytes.
MODEL_SUBJECT: dict[str, Any] = {
    "model_id": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_authority_sha256": (
        "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"),
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

#: Execution/backend semantics for the synthetic fixture world. They are
#: fixture constants so the synthetic subject is internally truthful and can
#: never be confused with the accepted Gemma subject above.
SYNTHETIC_SUBJECT_EXECUTION = (
    "fixture analog of the accepted execution semantics; synthetic BF32 "
    "text execution; fixture attention; one <=64-row replay chunk")
SYNTHETIC_SUBJECT_BACKEND = {
    "torch": "fixture-torch-0.0",
    "cuda_runtime": "fixture-cuda-0.0",
    "nvidia_driver": "fixture-driver-0.0",
    "triton": "fixture-triton-0.0",
    "flashinfer": "fixture-flashinfer-0.0",
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

#: The retained V5 geometry. It is a historical fixture constant, not a
#: planner input or physical qualification authority.
ACCEPTED_V5_GEOMETRY: tuple[dict[str, Any], ...] = (
    {"cu_id": "inferswarm01/gpu-0", "layer_start": 0, "layer_end": 16},
    {"cu_id": "inferswarm01/gpu-1", "layer_start": 16, "layer_end": 32},
    {"cu_id": "inferswarm03/gpu-0", "layer_start": 32, "layer_end": 48},
)


class StrategyError(RuntimeError):
    """Fail-closed strategy construction/mapping error."""


class QualificationAuthorityUnavailable(StrategyError):
    """Retained evidence cannot reconstruct an accepted V5 subject.

    Raised when the byte-pinned historical evidence is missing, drifted,
    contradictory, or disagrees with the frozen #117 subject identity.
    """


# ---------------------------------------------------------------------------
# Checkpoint catalog (SOURCE side; the only component that reads model bytes
# to build descriptors)
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
    """SOURCE-side whole-object hashing (reads every byte of ``path``)."""
    return "sha256:" + sha256_file(path)


def catalog_from_repository(root: Path, *, config: Mapping[str, Any],
                            inferswarm_root: Path | None = None) -> dict[str, Any]:
    """SOURCE-side exact checkpoint catalog from a real/synthetic repository.

    This builder is the SOURCE role: it reads config JSON, every
    ``*.safetensors`` file's header, hashes every object byte-exactly, and
    derives the mechanical ``catalog_content_digest``. It also binds the
    catalog to its external checkpoint authority identity
    (``checkpoint_authority_sha256``) through the repository's
    ``checkpoint-authority.json`` attestation, which is validated
    object-by-object against the observed bytes; for repositories claiming
    the canonical Gemma identity the attested authority must equal the
    accepted authority loaded from the byte-pinned retained V5 evidence, and
    the observed structure must match the accepted representation. Everything
    the builder returns is a small immutable descriptor; the
    Coordinator/planning waist never runs this code. Tensor byte ranges are
    absolute file offsets, which is what exact Range acquisition consumes.
    ``source_bytes_hashed`` records the model bytes this SOURCE-side builder
    read, separately from any Coordinator/control-plane traffic.
    """
    root = Path(root)
    attestation = _load_authority_attestation(root)
    objects: dict[str, dict[str, Any]] = {}
    tensors: dict[str, Any] = {}
    source_bytes_hashed = 0
    for path in sorted(root.glob("*.safetensors")):
        header, data_start, file_length = read_safetensors_header(path)
        objects[path.name] = {"length": file_length, "digest": digest_file(path)}
        source_bytes_hashed += file_length
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
        if extra.name == AUTHORITY_ATTESTATION_OBJECT:
            continue
        objects[extra.name] = {"length": extra.stat().st_size,
                               "digest": digest_file(extra)}
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
        "source_bytes_hashed": source_bytes_hashed,
    }
    _validate_authority_attestation(
        root, attestation, catalog, inferswarm_root=inferswarm_root)
    catalog["checkpoint_authority_sha256"] = \
        attestation["checkpoint_authority_sha256"]
    catalog["authority_attestation_digest"] = digest_of_bytes(
        (root / AUTHORITY_ATTESTATION_OBJECT).read_bytes())
    catalog["catalog_content_digest"] = catalog_content_digest(catalog)
    return catalog


def _load_authority_attestation(root: Path) -> dict[str, Any]:
    """Read and structurally validate the checkpoint authority attestation."""
    path = root / AUTHORITY_ATTESTATION_OBJECT
    if not path.is_file():
        raise StrategyError(
            f"checkpoint repository carries no {AUTHORITY_ATTESTATION_OBJECT}; "
            "the checkpoint authority identity cannot be established")
    try:
        attestation = json.loads(path.read_text())
    except ValueError as error:
        raise StrategyError(f"unreadable checkpoint authority attestation: {error}")
    for field in ("schema", "model_id", "revision",
                  "checkpoint_authority_sha256", "authority_evidence", "objects"):
        if field not in attestation:
            raise StrategyError(
                f"checkpoint authority attestation missing {field!r}")
    if attestation["schema"] != CHECKPOINT_AUTHORITY_ATTESTATION_SCHEMA:
        raise StrategyError(
            f"unexpected attestation schema {attestation['schema']!r}")
    authority = attestation["checkpoint_authority_sha256"]
    if not (isinstance(authority, str) and len(authority) == 64
            and all(char in "0123456789abcdef" for char in authority)):
        raise StrategyError(
            "attested checkpoint_authority_sha256 is not a bare 64-hex SHA-256")
    if not isinstance(attestation["objects"], Mapping):
        raise StrategyError("attestation objects manifest is not a mapping")
    return attestation


def _validate_authority_attestation(root: Path, attestation: Mapping[str, Any],
                                    catalog: Mapping[str, Any], *,
                                    inferswarm_root: Path | None) -> None:
    """Validate attestation consistency with observed repository bytes.

    This check detects attestation drift. It does not independently bind the
    observed bytes to the retained checkpoint authority value.
    """
    if attestation["model_id"] != catalog["model"]["model_id"] \
            or attestation["revision"] != catalog["model"]["revision"]:
        raise StrategyError(
            "attestation model identity does not match the repository config")
    attested_objects = attestation["objects"]
    observed_objects = {
        name: {"length": spec["length"], "sha256": spec["digest"].split(":", 1)[1]}
        for name, spec in sorted(catalog["objects"].items())
    }
    if dict(attested_objects) != observed_objects:
        raise StrategyError(
            "checkpoint authority attestation does not match the observed "
            "object set; the repository bytes drifted from the attested "
            "checkpoint")
    claims_canonical = (
        catalog["model"]["model_id"] == MODEL_SUBJECT["model_id"]
        and catalog["model"]["revision"] == MODEL_SUBJECT["revision"])
    if not claims_canonical:
        return
    # A repository claiming the canonical Gemma identity is held to the
    # accepted authority and the accepted representation structure.
    from issue117_applicability import accepted_checkpoint_authority_from_evidence
    accepted_authority = accepted_checkpoint_authority_from_evidence(
        inferswarm_root or Path(__file__).resolve().parents[1])
    if attestation["checkpoint_authority_sha256"] != accepted_authority:
        raise StrategyError(
            "attested checkpoint authority is not the accepted authority "
            "retained by the V5 evidence for the canonical Gemma identity; "
            "refusing a forged or foreign authority claim")
    if catalog["config"]["num_hidden_layers"] != LAYER_COUNT \
            or not catalog["config"]["tie_word_embeddings"]:
        raise StrategyError(
            "canonical checkpoint structure drift: layer count/tied-embedding "
            "config does not match the accepted subject")
    dtypes = {tensor["dtype"] for tensor in catalog["tensors"].values()}
    if dtypes != {"BF16"}:
        raise StrategyError(
            "canonical checkpoint representation drift: observed dtypes "
            f"{sorted(dtypes)!r} are not the accepted native-BF16 representation")
    for required in ("model.embed_tokens.weight", "model.norm.weight"):
        if required not in catalog["tensors"]:
            raise StrategyError(
                f"canonical checkpoint structure drift: missing {required!r}")
    if "model.lm_head.weight" in catalog["tensors"]:
        raise StrategyError(
            "canonical checkpoint structure drift: untied output head tensor "
            "present in a tied-embedding checkpoint")


def build_checkpoint_authority_attestation(
        root: Path, *, model_id: str, revision: str,
        checkpoint_authority_sha256: str,
        authority_evidence: str) -> dict[str, Any]:
    """SOURCE-side tool: attest an observed checkpoint repository to an
    external checkpoint authority identity.

    The fabric operator runs this once per acquired checkpoint repository;
    the attested object manifest is what ``catalog_from_repository``
    re-verifies byte-exactly at every later construction.
    """
    root = Path(root)
    if not (isinstance(checkpoint_authority_sha256, str)
            and len(checkpoint_authority_sha256) == 64
            and all(char in "0123456789abcdef"
                    for char in checkpoint_authority_sha256)):
        raise StrategyError(
            "checkpoint_authority_sha256 must be a bare 64-hex SHA-256")
    objects: dict[str, Any] = {}
    for path in sorted(root.glob("*.safetensors")) + sorted(root.glob("*.json")):
        if path.name == AUTHORITY_ATTESTATION_OBJECT:
            continue
        objects[path.name] = {
            "length": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    if CONFIG_OBJECT not in objects:
        raise StrategyError("checkpoint repository has no config.json")
    return {
        "schema": CHECKPOINT_AUTHORITY_ATTESTATION_SCHEMA,
        "model_id": model_id,
        "revision": revision,
        "checkpoint_authority_sha256": checkpoint_authority_sha256,
        "authority_evidence": authority_evidence,
        "objects": objects,
    }


def catalog_content_digest(catalog: Mapping[str, Any]) -> str:
    """Mechanical content identity over the exact weight-bearing content.

    Binds model identity, every weight object's digest/length, and the
    complete tensor table (layout, dtype, ranges) into one digest. A
    materially different checkpoint cannot carry the same identity. This is
    the drift binding of the exact bytes this machinery observed; it is a
    different identity from the external ``checkpoint_authority_sha256`` and
    must never be presented as the accepted checkpoint authority.
    """
    weight_objects = {
        name: {"length": spec["length"], "digest": spec["digest"]}
        for name, spec in sorted(catalog["objects"].items())
        if name.endswith(".safetensors")
    }
    identity = {
        "model": dict(catalog["model"]),
        "config": dict(catalog["config"]),
        "objects": weight_objects,
        "tensors": {name: catalog["tensors"][name] for name in sorted(catalog["tensors"])},
    }
    return digest_of_bytes(canonical_json_bytes(identity))


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


def logical_state_of_tensor(name: str) -> str | None:
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
    units = set()
    for name in catalog["tensors"]:
        unit = logical_state_of_tensor(name)
        if unit is not None:
            units.add(unit)
    if bool(catalog["config"]["tie_word_embeddings"]):
        # the output head is the shared embedding state
        units.add("state.output_head")
    return sorted(units)


def checkpoint_weight_bytes(catalog: Mapping[str, Any]) -> int:
    """Total checkpoint weight bytes (excluding non-weight objects)."""
    total = 0
    for name in catalog["tensors"]:
        if logical_state_of_tensor(name):
            total += catalog["tensors"][name]["byte_count"]
    return total


# ---------------------------------------------------------------------------
# SOURCE-side artifact manifest builder (the only byte reader below the
# catalog)
# ---------------------------------------------------------------------------


class SourceManifestBuilder:
    """Build the frozen artifact-record manifest from source object bytes.

    SOURCE role only: this is the single place below the catalog where model
    bytes are read or hashed. Its output is a small immutable set of
    artifact descriptors (digests, lengths, byte ranges); the strategy
    planning waist consumes the manifest and has no byte-access path.
    """

    def __init__(self, catalog: Mapping[str, Any], *,
                 source_bytes: Callable[[str], bytes]):
        self.catalog = catalog
        self._source_bytes = source_bytes
        self.bytes_read = 0
        self._object_cache: dict[str, bytes] = {}
        self._records: dict[str, list[dict[str, Any]]] = {}

    def _object_bytes(self, name: str) -> bytes:
        if name not in self._object_cache:
            data = self._source_bytes(name)
            expected = self.catalog["objects"].get(name, {}).get("digest")
            if expected is not None and digest_of_bytes(data) != expected:
                raise StrategyError(f"source object {name!r} drifted from catalog digest")
            self._object_cache[name] = data
            self.bytes_read += len(data)
        return self._object_cache[name]

    def _range_bytes(self, tensor: Mapping[str, Any]) -> bytes:
        data = self._object_bytes(tensor["object"])
        return bytes(data[tensor["byte_start"]:tensor["byte_end"]])

    def _tensor_records(self, names: Sequence[str], *, requirement_class: str,
                        extra_satisfies: Sequence[str] = ()) -> list[dict[str, Any]]:
        records = []
        for name in names:
            tensor = self.catalog["tensors"][name]
            content = self._range_bytes(tensor)
            state_id = logical_state_of_tensor(name)
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

    def _metadata_record(self, object_name: str, requirement_id: str) -> dict[str, Any]:
        content = self._object_bytes(object_name)
        return freeze_artifact_record(
            kind="whole_object", content=content,
            model_id=self.catalog["model"]["model_id"],
            revision=self.catalog["model"]["revision"],
            representation=self.catalog["model"]["representation"],
            satisfies_logical_state_ids=[requirement_id],
            requirement_class="required_metadata",
            origin={"source_object": object_name,
                    "source_object_digest": digest_of_bytes(content),
                    "source_object_length": len(content)},
        )

    def build(self) -> dict[str, Any]:
        """Resolve every legal (requirement class, requirement id) pair."""
        catalog = self.catalog
        layers = int(catalog["config"]["num_hidden_layers"])
        tied = bool(catalog["config"]["tie_word_embeddings"])

        def put(requirement_class: str, requirement_id: str,
                records: list[dict[str, Any]]) -> None:
            if records:
                self._records[f"{requirement_class}|{requirement_id}"] = records

        for layer in range(layers):
            names = sorted(name for name in catalog["tensors"]
                           if layer_of_tensor(name) == layer)
            if not names:
                raise StrategyError(f"no checkpoint tensors for state.layer.{layer}")
            put("assigned_logical_state", f"state.layer.{layer}",
                self._tensor_records(names, requirement_class="assigned_logical_state"))
        if "model.embed_tokens.weight" in catalog["tensors"]:
            put("assigned_logical_state", "state.embedding", self._tensor_records(
                ["model.embed_tokens.weight"], requirement_class="assigned_logical_state"))
            put("declared_shared_state", "state.embedding", self._tensor_records(
                ["model.embed_tokens.weight"], requirement_class="declared_shared_state",
                extra_satisfies=["state.output_head"]))
        put("assigned_logical_state", "state.final_norm", self._tensor_records(
            ["model.norm.weight"], requirement_class="assigned_logical_state"))
        if tied:
            # a tied output head is only ever declared shared state; the
            # record content is the shared embedding state
            put("declared_shared_state", "state.output_head", self._tensor_records(
                ["model.embed_tokens.weight"], requirement_class="declared_shared_state",
                extra_satisfies=["state.output_head"]))
        else:
            put("assigned_logical_state", "state.output_head", self._tensor_records(
                ["model.lm_head.weight"], requirement_class="assigned_logical_state"))
        put("required_metadata", f"metadata.{CONFIG_OBJECT}",
            [self._metadata_record(CONFIG_OBJECT, f"metadata.{CONFIG_OBJECT}")])
        put("required_metadata", f"metadata.{TOKENIZER_META_OBJECT}",
            [self._metadata_record(TOKENIZER_META_OBJECT,
                                   f"metadata.{TOKENIZER_META_OBJECT}")])

        manifest = {
            "schema": SOURCE_MANIFEST_SCHEMA,
            "model": dict(catalog["model"]),
            "checkpoint_authority_sha256": catalog["checkpoint_authority_sha256"],
            "catalog_content_digest": catalog["catalog_content_digest"],
            "records": {key: self._records[key] for key in sorted(self._records)},
            "source_bytes_read": self.bytes_read,
        }
        manifest["manifest_digest"] = self_digest(
            manifest, identity_field="manifest_digest")
        return manifest


def build_source_manifest(catalog: Mapping[str, Any], *,
                          source_bytes: Callable[[str], bytes]) -> dict[str, Any]:
    """SOURCE-side entry point: build the frozen artifact-record manifest."""
    return SourceManifestBuilder(catalog, source_bytes=source_bytes).build()


# ---------------------------------------------------------------------------
# Qualification subjects and records
# ---------------------------------------------------------------------------


def _validate_subject_fields(subject: Mapping[str, Any]) -> None:
    for field in ("model_id", "revision", "checkpoint_authority_sha256",
                  "representation", "execution"):
        value = subject.get(field)
        if not (isinstance(value, str) and value.strip()):
            raise StrategyError(f"subject field {field!r} missing or empty")
    authority = subject["checkpoint_authority_sha256"]
    if not (len(authority) == 64
            and all(char in "0123456789abcdef" for char in authority)):
        raise StrategyError(
            "subject checkpoint_authority_sha256 is not a bare 64-hex SHA-256")
    content = subject.get("catalog_content_digest")
    if content is not None \
            and not (isinstance(content, str) and content.startswith("sha256:")):
        raise StrategyError(
            "subject catalog_content_digest must be a sha256:-prefixed digest")
    backend = subject.get("backend")
    if not isinstance(backend, Mapping):
        raise StrategyError("subject backend identity missing")
    for key in REQUIRED_SUBJECT_BACKEND_KEYS:
        if not str(backend.get(key, "")).strip():
            raise StrategyError(f"subject backend field {key!r} missing")


def subject_from_catalog(catalog: Mapping[str, Any], *, execution: str,
                         backend: Mapping[str, str]) -> dict[str, Any]:
    """Derive a strategy subject mechanically from the exact catalog.

    The subject's model/revision/representation, checkpoint authority
    identity, and catalog content identity are the catalog's own; execution
    and backend are the operator-declared semantics. A subject can therefore
    never disagree with the catalog it qualifies, and it binds BOTH the
    accepted external checkpoint authority identity and the mechanical
    catalog content identity explicitly and separately.
    """
    _validate_subject_fields({
        "model_id": catalog["model"]["model_id"],
        "revision": catalog["model"]["revision"],
        "checkpoint_authority_sha256": catalog["checkpoint_authority_sha256"],
        "catalog_content_digest": catalog["catalog_content_digest"],
        "representation": catalog["model"]["representation"],
        "execution": execution, "backend": backend})
    return {
        "model_id": catalog["model"]["model_id"],
        "revision": catalog["model"]["revision"],
        "checkpoint_authority_sha256": catalog["checkpoint_authority_sha256"],
        "catalog_content_digest": catalog["catalog_content_digest"],
        "representation": catalog["model"]["representation"],
        "execution": execution,
        "backend": dict(backend),
    }


def build_qualification_record(*, qualification_record_id: str,
                               terminal_disposition: str,
                               terminal_adjudication_sha256: str,
                               qualification_subject: Mapping[str, Any],
                               authority_extra: Mapping[str, Any] | None = None,
                               scope: str = "accepted-authority") -> dict[str, Any]:
    """Build one self-consistent qualification record for an exact subject.

    The record's subject digest follows the shared execution-equality
    convention (``issue117_subject_identity.subject_digest``): machinery-local
    content identities carried on the subject are bound by the machinery and
    projected out of the matched digest on both the record and candidate
    sides.
    """
    _validate_subject_fields(qualification_subject)
    record = {
        "schema": QUALIFICATION_RECORD_SCHEMA,
        "qualification_record_id": qualification_record_id,
        "scope": scope,
        "authority": {
            "terminal_disposition": terminal_disposition,
            "terminal_adjudication_sha256": terminal_adjudication_sha256,
            **(dict(authority_extra) if authority_extra else {}),
        },
        "qualification_subject": dict(qualification_subject),
    }
    record["qualification_subject_digest"] = subject_digest(
        record["qualification_subject"])
    record["record_digest"] = self_digest(record, identity_field="record_digest")
    return record


def canonical_authority_catalog(*, inferswarm_root: Path | None = None) -> dict[str, Any]:
    """Build a V5-shaped diagnostic descriptor catalog.

    The catalog carries retained model strings and a repeated
    ``checkpoint_authority_sha256`` value. It cannot establish checkpoint
    authority or an accepted qualification subject. It is descriptor-only and
    contains no tensor table. A strategy built from it refuses the byte-level
    planning surface. Physical construction requires
    ``catalog_from_repository`` over a real checkpoint repository and an
    independent authority derivation (recovered: PR #119 provenance record;
    see ``issue117_checkpoint_authority`` and
    ``issue117_accepted_subject``).
    """
    from issue117_applicability import accepted_checkpoint_authority_from_evidence
    root = Path(inferswarm_root or Path(__file__).resolve().parents[1])
    accepted_authority = accepted_checkpoint_authority_from_evidence(root)
    if accepted_authority != MODEL_SUBJECT["checkpoint_authority_sha256"]:
        raise StrategyError(
            "accepted checkpoint authority evidence does not agree with the "
            "frozen subject identity")
    catalog = {
        "schema": CATALOG_SCHEMA,
        "model": {
            "model_id": MODEL_SUBJECT["model_id"],
            "revision": MODEL_SUBJECT["revision"],
            "representation": MODEL_SUBJECT["representation"],
        },
        "config": {
            "num_hidden_layers": LAYER_COUNT,
            # tied output head: the accepted canonical serving layout the
            # exact-mapping derivation is frozen against
            "tie_word_embeddings": True,
        },
        "objects": {},
        "tensors": {},
        "descriptor_only": True,
        "checkpoint_authority_sha256": accepted_authority,
        "authority_basis": {
            "source": "retained accepted V5 checkpoint authority evidence",
            "authority_evidence_files": sorted(
                {"docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json",
                 "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json"}),
            "source_field": "checkpoint_sha256",
        },
        "source_bytes_hashed": 0,
    }
    catalog["catalog_content_digest"] = catalog_content_digest(catalog)
    return catalog


def canonical_v5_candidate(*, inferswarm_root: Path | None = None) -> Mapping[str, Any]:
    """Build a V5-shaped candidate-construction diagnostic.

    Builds the diagnostic descriptor catalog, derives its subject
    with ``subject_from_catalog``, enumerates the legal dense candidates with
    ``GemmaDenseStrategy``, and returns the candidate whose geometry matches
    the retained V5-shaped geometry. It does not establish an accepted V5
    qualification subject or checkpoint authority.
    """
    catalog = canonical_authority_catalog(inferswarm_root=inferswarm_root)
    subject = subject_from_catalog(
        catalog, execution=MODEL_SUBJECT["execution"],
        backend=MODEL_SUBJECT["backend"])
    instance = GemmaDenseStrategy(catalog=catalog, subject=subject,
                                  source_manifest=None)
    candidates = instance.legal_candidates()
    return instance.accepted_v5_candidate(candidates)


def retained_v5_qualification_authority(
        inferswarm_root: Path | None = None) -> dict[str, Any]:
    """Load the accepted V5 qualification record from retained evidence.

    Recovered 2026-09-07 (``V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED``):
    the accepted subject is reconstructed by
    ``issue117_accepted_subject.accepted_v5_qualification_record`` purely
    from byte-pinned accepted historical evidence (V5 physical subject, V4
    execution authority, V2/V4 preflights, #110 terminal adjudication, and
    the PR #119 checkpoint-authority provenance). That module imports no
    candidate-construction machinery; this loader adds only a consistency
    requirement that the record agree with the frozen model-subject strings
    this strategy already carries. It still raises
    ``QualificationAuthorityUnavailable`` when retained evidence is missing,
    drifted, contradictory, or tampered.
    """
    from issue117_accepted_subject import (
        SubjectReconstructionError,
        accepted_v5_qualification_record,
    )
    try:
        record = accepted_v5_qualification_record(inferswarm_root)
    except SubjectReconstructionError as error:
        raise QualificationAuthorityUnavailable(str(error)) from error
    subject = record["qualification_subject"]
    for field in ("model_id", "revision", "checkpoint_authority_sha256",
                  "representation", "execution"):
        if subject.get(field) != MODEL_SUBJECT[field]:
            raise QualificationAuthorityUnavailable(
                f"reconstructed accepted subject field {field!r} disagrees "
                "with the frozen #117 subject identity "
                f"({subject.get(field)!r} != {MODEL_SUBJECT[field]!r})")
    if subject.get("backend") != MODEL_SUBJECT["backend"]:
        raise QualificationAuthorityUnavailable(
            "reconstructed accepted subject backend disagrees with the "
            "frozen #117 subject identity")
    return record


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
    """Expose legal opaque dense candidates and exact requirement mappings.

    The strategy is a pure planning-waist consumer of descriptors: it holds
    a catalog, a subject, and a SOURCE-built artifact manifest, and never
    reads or hashes model bytes.
    """

    def __init__(self, *, catalog: Mapping[str, Any], subject: Mapping[str, Any],
                 source_manifest: Mapping[str, Any] | None,
                 snapshot: Mapping[str, Any] = RESOURCE_SNAPSHOT):
        if catalog["schema"] != CATALOG_SCHEMA:
            raise StrategyError("catalog schema mismatch")
        if subject is None:
            raise StrategyError(
                "a strategy subject is required; it must be derived from the "
                "exact catalog via subject_from_catalog")
        _validate_subject_fields(subject)
        self.catalog = catalog
        self.subject = dict(subject)
        self.snapshot = snapshot
        self.descriptor_only = bool(catalog.get("descriptor_only"))
        self.layers = int(catalog["config"]["num_hidden_layers"])
        self.tied = bool(catalog["config"]["tie_word_embeddings"])
        if self.layers != LAYER_COUNT:
            raise StrategyError(
                f"catalog layer count {self.layers} != frozen subject {LAYER_COUNT}")
        # subject/catalog inseparability: the qualification subject is only
        # constructible from the exact plan/catalog identity, on BOTH the
        # accepted checkpoint authority identity and the mechanical catalog
        # content identity
        for field, catalog_value in (
                ("model_id", catalog["model"]["model_id"]),
                ("revision", catalog["model"]["revision"]),
                ("representation", catalog["model"]["representation"]),
                ("checkpoint_authority_sha256",
                 catalog["checkpoint_authority_sha256"]),
                ("catalog_content_digest", catalog["catalog_content_digest"])):
            if self.subject.get(field) != catalog_value:
                raise StrategyError(
                    f"subject {field} {self.subject.get(field)!r} != catalog identity "
                    f"{catalog_value!r}; qualification is not constructible for a "
                    "foreign catalog")
        if source_manifest is None:
            if not self.descriptor_only:
                raise StrategyError(
                    "a SOURCE-built artifact manifest is required; the planning "
                    "waist has no byte-access path")
        else:
            if self.descriptor_only:
                raise StrategyError(
                    "a descriptor-only authority catalog takes no source manifest")
            self._validate_manifest(source_manifest)
        self.source_manifest = source_manifest
        self._cu_by_id = {cu["cu_id"]: cu for cu in snapshot["compute_units"]}
        self._chain = list(snapshot["chain_order"])
        self._plan_cache: dict[str, dict[str, Any]] = {}
        self._requirements_cache: dict[str, Any] = {}

    def _require_byte_catalog(self, operation: str) -> None:
        if self.descriptor_only:
            raise StrategyError(
                f"{operation} requires a byte-level checkpoint catalog; the "
                "canonical authority descriptor catalog carries identity only")

    def _validate_manifest(self, manifest: Mapping[str, Any]) -> None:
        from issue99_artifact_core import validate_self_identity
        if manifest.get("schema") != SOURCE_MANIFEST_SCHEMA:
            raise StrategyError("source manifest schema mismatch")
        try:
            validate_self_identity(dict(manifest), identity_field="manifest_digest")
        except Exception as error:
            raise StrategyError(f"source manifest self-identity mismatch: {error}")
        if manifest.get("model") != dict(self.catalog["model"]):
            raise StrategyError("source manifest model identity != catalog")
        if manifest.get("checkpoint_authority_sha256") \
                != self.catalog["checkpoint_authority_sha256"] \
                or manifest.get("catalog_content_digest") \
                != self.catalog["catalog_content_digest"]:
            raise StrategyError("source manifest checkpoint identity != catalog")

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
                candidate["qualification_subject_digest"] = subject_digest(
                    candidate["qualification_subject"])
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

    # -- exact participant requirements (the feasibility input) ----------------

    def stage_requirements(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        """The exact frozen participant requirements for one candidate."""
        self._require_byte_catalog("stage_requirements")
        key = candidate["candidate_id"]
        if key not in self._requirements_cache:
            from issue99_artifact_core import derive_participant_requirements
            self._requirements_cache[key] = derive_participant_requirements(
                self.plan(candidate), self.resolve)
        return self._requirements_cache[key]

    def stage_weight_bytes(self, candidate: Mapping[str, Any], stage_index: int) -> int:
        """Exact model-state bytes one candidate stage must materialize.

        Derived from the exact frozen participant requirements: assigned
        state plus declared shared state, excluding only declared metadata,
        deduplicated only by artifact identity within the participant (a
        shared state is one artifact on that participant).
        """
        self._require_byte_catalog("stage_weight_bytes")
        requirements = self.stage_requirements(candidate)
        participant_id = f"{candidate['candidate_id']}.stage-{stage_index + 1}"
        matches = [p for p in requirements["participants"]
                   if p["participant_id"] == participant_id]
        if len(matches) != 1:
            raise StrategyError(f"no frozen requirements for {participant_id}")
        return sum(record["length"] for record in matches[0]["required_artifacts"]
                   if record["requirement_class"] != "required_metadata")

    # -- strategy-owned feasibility and policy inputs --------------------------

    def feasibility(self, candidate: Mapping[str, Any], *,
                    capacity_model: Mapping[str, int] | None = None) -> dict[str, Any]:
        """Technical feasibility + hard operator policy + integrity inputs.

        Stage bytes come from the exact participant requirements. Technical
        feasibility requires an operator capacity model; without one it is
        declared unknown and must fail closed in the planner.
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
                "accounting_source": "exact_participant_requirements",
                "hard_policy_eligible": self._serving_policy_eligible(candidate),
                "integrity_eligible": True}

    def _serving_policy_eligible(self, candidate: Mapping[str, Any]) -> bool:
        return all(
            self._cu_by_id[stage["cu_id"]]["role"] in SERVING_POLICY["serving_eligible_roles"]
            for stage in candidate["stages"]
        )

    # -- qualification subjects ------------------------------------------------

    def qualification_subject(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        """Opaque descriptor of everything qualification evidence must bind.

        Derived mechanically from the exact catalog/plan identity (model,
        revision, checkpoint authority, catalog content, representation,
        layer count) plus the frozen execution/backend semantics and the
        candidate's stage geometry and device assignment. The subject binds
        BOTH checkpoint identities explicitly: the accepted external
        ``checkpoint_authority_sha256`` and the machinery-local
        ``catalog_content_digest``. The shared subject-identity convention
        (``issue117_subject_identity.subject_digest``) defines the matched
        qualification digest over the execution-equality projection.
        """
        return {
            "model_id": self.subject["model_id"],
            "revision": self.subject["revision"],
            "checkpoint_authority_sha256": self.subject["checkpoint_authority_sha256"],
            "catalog_content_digest": self.subject["catalog_content_digest"],
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

    # -- frozen plan + requirement resolver (strategy adapter boundary) --------

    def plan(self, candidate: Mapping[str, Any], *, epoch: int = 1) -> dict[str, Any]:
        embedded = candidate.get("qualification_subject")
        derived = self.qualification_subject(candidate)
        if embedded is not None and embedded != derived:
            raise StrategyError(
                "candidate qualification subject does not match the strategy's "
                "catalog/plan identity; refusing to plan a foreign subject")
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
                if self.tied and stage_count > 1:
                    # a tied head is shared across stages; a single-stage
                    # participant already owns the embedding state outright
                    shared.extend(["state.embedding", "state.output_head"])
                elif not self.tied:
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
            "model": {
                **dict(self.catalog["model"]),
                "checkpoint_authority_sha256": self.catalog["checkpoint_authority_sha256"],
                "catalog_content_digest": self.catalog["catalog_content_digest"],
                "layer_count": self.layers,
                "execution": self.subject["execution"],
                "backend": dict(self.subject["backend"]),
            },
            "qualification_subject": derived,
            "qualification_subject_digest": subject_digest(derived),
            "logical_state_units": [{"id": unit} for unit in self.logical_state_units()],
            "participants": participants,
        }
        plan["plan_digest"] = self_digest(plan, identity_field="plan_digest")
        self._plan_cache[key] = plan
        return plan

    def logical_state_units(self) -> list[str]:
        self._require_byte_catalog("logical_state_units")
        units = weight_unit_ids(self.catalog)
        units.extend([f"metadata.{CONFIG_OBJECT}", f"metadata.{TOKENIZER_META_OBJECT}"])
        return sorted(units)

    def resolve(self, requirement_class: str, requirement_id: str) -> list[dict[str, Any]]:
        """Strategy adapter: logical state requirement -> exact artifact records.

        Serves frozen descriptors from the SOURCE-built manifest; there is no
        byte-access path here.
        """
        self._require_byte_catalog("resolve")
        key = f"{requirement_class}|{requirement_id}"
        records = self.source_manifest["records"].get(key)
        if not records:
            raise StrategyError(
                f"no source artifact record for {requirement_id!r} as "
                f"{requirement_class!r}")
        return [validate_artifact_record(record) for record in records]

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


# ---------------------------------------------------------------------------
# Synthetic fixture checkpoint (SOURCE side)
# ---------------------------------------------------------------------------


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
        "tokenizer_identity": "fixture-analog-tokenizer",
        "note": "metadata only; synthetic fixture bytes",
    }
    objects[TOKENIZER_META_OBJECT] = canonical_json_bytes(tokenizer_meta)
    (root / TOKENIZER_META_OBJECT).write_bytes(objects[TOKENIZER_META_OBJECT])
    # the fixture world carries its own synthetic authority identity: it is
    # derived from the fixture seed, labeled fixture-only, and can never
    # equal — or be exchanged for — the accepted Gemma checkpoint authority
    synthetic_authority = hashlib.sha256(
        f"issue117-synthetic-checkpoint-authority:{seed}".encode()).hexdigest()
    attestation = build_checkpoint_authority_attestation(
        root, model_id=config["model_id"], revision=config["revision"],
        checkpoint_authority_sha256=synthetic_authority,
        authority_evidence=(
            "synthetic fixture world; no external checkpoint authority; "
            "never valid for the canonical Gemma identity"))
    attestation_bytes = canonical_json_bytes(attestation)
    (root / AUTHORITY_ATTESTATION_OBJECT).write_bytes(attestation_bytes)
    objects[AUTHORITY_ATTESTATION_OBJECT] = attestation_bytes
    return config, objects
