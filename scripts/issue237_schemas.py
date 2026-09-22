#!/usr/bin/env python3
"""Schemas for the future physical R8-I campaign observations (issue #237).

Deterministic, versioned, fail-closed pure-stdlib validators + JSON schema
documents for:

- reference-observation  (NVIDIA/Vulkan arm, canonical-prefix replay)
- candidate-observation  (AMD/Vulkan arm, canonical-prefix replay)
- calibration-summary    (per-case family values for threshold derivation)
- semantic-row           (adjudication output rows)
- core-threshold-manifest
- telemetry-reference-bands
- holdout-result         (future unsealed campaign result)

The validators are the machine contract: the future campaign's retained
artifacts must satisfy them exactly, and the negative-control tests prove
they reject the mandatory control classes.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import issue237_methodology as m  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs/qualification/qwen38-vulkan-v1"

REFERENCE_OBSERVATION_SCHEMA = "inferswarm.issue237.reference-observation/1"
CANDIDATE_OBSERVATION_SCHEMA = "inferswarm.issue237.candidate-observation/1"
CALIBRATION_SUMMARY_SCHEMA = "inferswarm.issue237.calibration-summary/1"
SEMANTIC_ROW_SCHEMA = "inferswarm.issue237.semantic-row/1"
HOLDOUT_RESULT_SCHEMA = "inferswarm.issue237.holdout-result/1"


class SchemaError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


def _is_hex_float(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        float.fromhex(value)
        return True
    except ValueError:
        return False


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def validate_layer1_identity(doc: dict[str, Any]) -> None:
    """The Layer-1 exact-integrity block every physical artifact must carry."""
    layer1 = doc.get("layer1")
    if not isinstance(layer1, dict):
        raise SchemaError("layer1 identity block missing")
    subject = m.physical_subject_contract()
    _require(
        layer1.get("llama_cpp_pin") == m.LLAMA_CPP_PIN,
        "runtime pin mismatch",
    )
    _require(
        layer1.get("vulkan_binary_sha256") == m.LLAMA_VULKAN_BINARY_SHA256,
        "vulkan binary mismatch",
    )
    members = layer1.get("gguf_member_sha256")
    _require(
        isinstance(members, list) and len(members) == 3
        and members == [x["sha256"] for x in m.GGUF_MEMBERS],
        "gguf member hashes mismatch",
    )
    _require(
        layer1.get("no_cuda_participation") is True,
        "CUDA participation not excluded",
    )
    arm = layer1.get("arm")
    if arm == "reference":
        _require(
            layer1.get("gpu_uuid") == subject["reference_arm"]["gpu_uuid"]
            and layer1.get("bdf") == subject["reference_arm"]["bdf"],
            "reference device identity mismatch",
        )
    elif arm == "candidate":
        _require(
            layer1.get("bdf") == subject["candidate_arm"]["gpu_bdf"],
            "candidate device identity mismatch",
        )
        _require(
            layer1.get("excluded_die_bdf")
            == subject["candidate_arm"]["single_die_authority"]["excluded_die_bdf"],
            "excluded die identity mismatch",
        )
    else:
        raise SchemaError("layer1 arm must be reference or candidate")


def validate_observation(doc: dict[str, Any], *, arm: str) -> None:
    expected_schema = (
        REFERENCE_OBSERVATION_SCHEMA if arm == "reference"
        else CANDIDATE_OBSERVATION_SCHEMA
    )
    _require(doc.get("schema") == expected_schema, "observation schema drift")
    _require(doc.get("arm") == arm, "arm mismatch")
    validate_layer1_identity(doc)
    geometry = doc.get("geometry", {})
    subject_geometry = m.physical_subject_contract()["geometry"]
    _require(geometry.get("ngl") == 1, "ngl drift")
    _require(
        geometry.get("request") == subject_geometry["request_contract"],
        "request contract drift",
    )
    decisions = doc.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != m.DECISION_COUNT:
        raise SchemaError(f"exactly {m.DECISION_COUNT} decisions required")
    for i, row in enumerate(decisions):
        _require(_is_sha256(row.get("prefix_sha256")), f"decision {i} prefix hash missing")
        _require(_is_hex_float(row.get("top1_hex")), f"decision {i} top1 missing")
        _require(_is_hex_float(row.get("top2_hex")), f"decision {i} top2 missing")
        _require(_is_sha256(row.get("logits_row_sha256")), f"decision {i} logits row hash missing")
        _require(
            isinstance(row.get("emitted_token"), int),
            f"decision {i} emitted token missing",
        )
        # reference/candidate prefix identity is the SAME frozen prefix
        if arm == "candidate":
            _require(
                row.get("input_prefix_source") == "reference-canonical-prefix",
                f"decision {i} not teacher-forced on the reference prefix",
            )


def validate_calibration_summary(doc: dict[str, Any]) -> None:
    _require(doc.get("schema") == CALIBRATION_SUMMARY_SCHEMA, "summary schema drift")
    families = doc.get("per_case_family_values")
    if not isinstance(families, dict):
        raise SchemaError("per_case_family_values must be an object")
    expected = [f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES] + [
        f["family"] for f in m.TELEMETRY_FAMILIES
    ]
    _require(sorted(families) == sorted(expected), "family set drift")
    for family, values in families.items():
        _require(
            isinstance(values, list) and len(values) == m.CALIBRATION_CASES,
            f"{family} requires exactly {m.CALIBRATION_CASES} values",
        )
        for v in values:
            _require(_is_hex_float(v), f"{family} values must be hex floats")
    # correction-pass binding: the summary names its complete case
    # population and carries the statistical case-E_D arm
    case_ids = doc.get("case_ids")
    _require(
        isinstance(case_ids, list) and len(case_ids) == m.CALIBRATION_CASES,
        "calibration summary case_ids must list the complete population",
    )
    for case_id in case_ids:
        _require(
            isinstance(case_id, str) and case_id.startswith("c237-"),
            "calibration summary case id drift",
        )
    case_e_d = doc.get("case_e_d_hex")
    _require(
        isinstance(case_e_d, list) and len(case_e_d) == m.CALIBRATION_CASES,
        "calibration summary requires exactly "
        f"{m.CALIBRATION_CASES} statistical case E_D values",
    )
    for v in case_e_d:
        _require(_is_hex_float(v), "case E_D values must be hex floats")


THRESHOLD_INPUT_DIGEST_KEYS = (
    "calibration_corpus_sha256",
    "stress_pool_sha256",
    "selected_stress_sha256",
    "calibration_summary_sha256",
    "observation_manifest_sha256",
)


def validate_threshold_manifest(doc: dict[str, Any]) -> None:
    from issue237_thresholds import CORE_THRESHOLD_SCHEMA
    _require(doc.get("schema") == CORE_THRESHOLD_SCHEMA, "threshold schema drift")
    _require(doc.get("comparator_id") == m.COMPARATOR_ID, "comparator drift")
    limits = doc.get("limits")
    if not isinstance(limits, dict):
        raise SchemaError("limits must be an object")
    _require(
        sorted(limits) == sorted(f["family"] for f in m.ACCEPTANCE_BEARING_FAMILIES),
        "limit family drift",
    )
    for family, block in limits.items():
        _require(_is_hex_float(block.get("limit_hex")), f"{family} limit not hex float")
    _require(_is_hex_float(doc.get("e_d_hex")), "E_D not hex float")
    derived = doc.get("derived_from")
    if not isinstance(derived, dict):
        raise SchemaError("derived_from must be an object")
    for key in THRESHOLD_INPUT_DIGEST_KEYS:
        _require(
            _is_sha256(derived.get(key)),
            f"threshold manifest input digest missing: {key}",
        )


def schema_documents() -> dict[str, Any]:
    """Emit the JSON-schema documents for the future campaign artifacts."""
    def family_enum(tier: str) -> list[str]:
        src = (
            m.ACCEPTANCE_BEARING_FAMILIES if tier == "acceptance"
            else m.TELEMETRY_FAMILIES
        )
        return [f["family"] for f in src]

    layer1_block = {
        "type": "object",
        "required": ["arm", "llama_cpp_pin", "vulkan_binary_sha256",
                     "gguf_member_sha256", "no_cuda_participation", "bdf"],
        "properties": {
            "arm": {"enum": ["reference", "candidate"]},
            "llama_cpp_pin": {"const": m.LLAMA_CPP_PIN},
            "vulkan_binary_sha256": {"const": m.LLAMA_VULKAN_BINARY_SHA256},
            "gguf_member_sha256": {
                "const": [x["sha256"] for x in m.GGUF_MEMBERS],
            },
            "no_cuda_participation": {"const": True},
            "bdf": {"type": "string"},
            "gpu_uuid": {"type": "string"},
            "excluded_die_bdf": {"type": "string"},
        },
    }
    decision_row = {
        "type": "object",
        "required": ["prefix_sha256", "top1_hex", "top2_hex",
                     "logits_row_sha256", "emitted_token"],
        "properties": {
            "prefix_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "top1_hex": {"type": "string"},
            "top2_hex": {"type": "string"},
            "logits_row_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "emitted_token": {"type": "integer", "minimum": 0},
            "input_prefix_source": {"type": "string"},
        },
    }
    observation = {
        "type": "object",
        "required": ["schema", "arm", "layer1", "geometry", "case_id", "decisions"],
        "properties": {
            "schema": {"type": "string"},
            "arm": {"enum": ["reference", "candidate"]},
            "case_id": {"type": "string"},
            "layer1": layer1_block,
            "geometry": {
                "type": "object",
                "required": ["ngl", "request"],
                "properties": {
                    "ngl": {"const": 1},
                    "request": {"type": "object"},
                },
            },
            "decisions": {
                "type": "array",
                "minItems": m.DECISION_COUNT,
                "maxItems": m.DECISION_COUNT,
                "items": decision_row,
            },
        },
    }
    return {
        "reference-observation.schema.json": observation,
        "candidate-observation.schema.json": observation,
        "calibration-summary.schema.json": {
            "type": "object",
            "required": ["schema", "per_case_family_values"],
            "properties": {
                "schema": {"const": CALIBRATION_SUMMARY_SCHEMA},
                "per_case_family_values": {
                    "type": "object",
                    "required": family_enum("acceptance")
                    + family_enum("telemetry"),
                    "additionalProperties": False,
                    "patternProperties": {
                        "^.+$": {
                            "type": "array",
                            "minItems": m.CALIBRATION_CASES,
                            "maxItems": m.CALIBRATION_CASES,
                            "items": {"type": "string"},
                        },
                    },
                },
            },
        },
        "semantic-row.schema.json": {
            "type": "object",
            "required": ["schema", "decision_local_error_hex",
                         "reference_winner_token", "verdict"],
            "properties": {
                "schema": {"const": SEMANTIC_ROW_SCHEMA},
                "decision_local_error_hex": {"type": "string"},
                "reference_winner_token": {"type": "integer"},
                "candidate_winner_token": {"type": "integer"},
                "m_d_hex": {"type": "string"},
                "stability": {"enum": ["STABLE", "UNSTABLE"]},
                "verdict": {
                    "enum": list(m.REASON_CODES),
                },
            },
        },
        "core-threshold-manifest.schema.json": {
            "type": "object",
            "required": ["schema", "comparator_id", "limits", "e_d_hex",
                         "e_d_derivation", "derived_from"],
            "properties": {
                "schema": {"const": "inferswarm.issue237.core-threshold-manifest/1"},
                "comparator_id": {"const": m.COMPARATOR_ID},
                "limits": {"type": "object"},
                "e_d_hex": {"type": "string"},
                "e_d_derivation": {
                    "type": "object",
                    "required": ["rule", "statistical_case_count",
                                 "stress_case_count"],
                    "properties": {
                        "rule": {"type": "string"},
                        "statistical_case_count": {"const": m.CALIBRATION_CASES},
                        "stress_case_count": {"const": m.STRESS_SELECTED_CASES},
                    },
                },
                "derived_from": {
                    "type": "object",
                    "required": list(THRESHOLD_INPUT_DIGEST_KEYS),
                },
            },
        },
        "telemetry-reference-bands.schema.json": {
            "type": "object",
            "required": ["schema", "comparator_id", "bands", "derived_from"],
            "properties": {
                "schema": {
                    "const": "inferswarm.issue237.telemetry-reference-bands/1",
                },
                "comparator_id": {"const": m.COMPARATOR_ID},
                "bands": {"type": "object"},
                "derived_from": {
                    "type": "object",
                    "required": ["calibration_corpus_sha256",
                                 "calibration_summary_sha256",
                                 "observation_manifest_sha256"],
                },
            },
        },
        "selected-stress.schema.json": {
            "type": "object",
            "required": ["schema", "selected"],
            "properties": {
                "schema": {
                    "const": "inferswarm.issue237.selected-stress/1",
                },
                "selected": {
                    "type": "array",
                    "minItems": m.STRESS_SELECTED_CASES,
                    "maxItems": m.STRESS_SELECTED_CASES,
                    "items": {
                        "type": "object",
                        "required": ["case_id"],
                        "properties": {
                            "case_id": {"type": "string"},
                        },
                    },
                },
            },
        },
        "observation-manifest.schema.json": {
            "type": "object",
            "required": ["schema", "contract_id", "comparator_id",
                         "calibration_corpus_sha256", "calibration_cases",
                         "selected_stress_cases"],
            "properties": {
                "schema": {
                    "const": "inferswarm.issue237.observation-manifest/1",
                },
                "contract_id": {"const": m.CONTRACT_ID},
                "comparator_id": {"const": m.COMPARATOR_ID},
                "calibration_corpus_sha256": {
                    "type": "string", "pattern": "^[0-9a-f]{64}$",
                },
                "calibration_cases": {
                    "type": "array",
                    "minItems": m.CALIBRATION_CASES,
                    "maxItems": m.CALIBRATION_CASES,
                    "items": {
                        "type": "object",
                        "required": ["case_id", "reference_sha256",
                                     "candidate_sha256", "case_e_d_hex"],
                    },
                },
                "selected_stress_cases": {
                    "type": "array",
                    "minItems": m.STRESS_SELECTED_CASES,
                    "maxItems": m.STRESS_SELECTED_CASES,
                    "items": {
                        "type": "object",
                        "required": ["case_id", "reference_sha256",
                                     "candidate_sha256", "case_e_d_hex"],
                    },
                },
            },
        },
        "maintainer-unseal-authorization.schema.json": {
            "type": "object",
            "required": ["schema", "authorized", "authorized_by",
                         "campaign_head", "holdout_ciphertext_sha256",
                         "core_threshold_manifest_sha256",
                         "comparator_id", "contract_id"],
            "properties": {
                "schema": {
                    "const": (
                        "inferswarm.issue237.maintainer-unseal-authorization/1"
                    ),
                },
                "authorized": {"const": True},
                "authorized_by": {"type": "string", "minLength": 1},
                "campaign_head": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "holdout_ciphertext_sha256": {
                    "type": "string", "pattern": "^[0-9a-f]{64}$",
                },
                "core_threshold_manifest_sha256": {
                    "type": "string", "pattern": "^[0-9a-f]{64}$",
                },
                "comparator_id": {"const": m.COMPARATOR_ID},
                "contract_id": {"const": m.CONTRACT_ID},
            },
        },
        "holdout-result.schema.json": {
            "type": "object",
            "required": ["schema", "campaign", "case_results", "terminal"],
            "properties": {
                "schema": {"const": HOLDOUT_RESULT_SCHEMA},
                "campaign": {"type": "string"},
                "case_results": {"type": "array"},
                "terminal": {"type": "string"},
            },
        },
    }


def write_schema_documents() -> dict[str, str]:
    written = {}
    DOCS.joinpath("schemas").mkdir(parents=True, exist_ok=True)
    for name, document in schema_documents().items():
        path = DOCS / "schemas" / name
        path.write_bytes(canonical_json_bytes(document))
        written[name] = f"docs/qualification/qwen38-vulkan-v1/schemas/{name}"
    return written


if __name__ == "__main__":
    print(json.dumps(write_schema_documents(), indent=1))
