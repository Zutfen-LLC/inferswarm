#!/usr/bin/env python3
"""Emit the versioned issue #109 v5 JSON Schemas deterministically.

CPU-only, pure stdlib. Running this script always produces byte-identical
schema files (canonical JSON), so the committed schemas are reproducible.
"""
from __future__ import annotations

from pathlib import Path

from issue74_methodology import ENVELOPES, canonical_json_bytes
from issue109_v5_methodology import (
    V5_CALIBRATION_CASES,
    V5_HOLDOUT_CASES,
    V5_MIXTURE_COMPONENTS,
    V5_SELECTED_STRESS_CASES,
    V5_STATISTICAL_CASES,
    V5_STRESS_POOL_CASES,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs/qualification/gemma4-12b-it-v5/schemas"
BASE = "https://inferswarm.dev/schema/issue109/"
CONTRACT = "inferswarm.gemma4-mixture-population-qualification/1"
DOMAIN_ID = "reference-top-1024-with-cutoff-ties/1"
TIE_BREAK = "ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima"

SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
HEX = {"type": "string", "pattern": "^0x[0-9a-f.]+p[+-][0-9]+$"}


def schema(schema_id: str, title: str, required: list[str], properties: dict) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + schema_id,
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def case_ref() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["case_id", "content_class", "length_regime", "token_count",
                     "prompt_text", "token_ids", "prompt_sha256", "token_ids_sha256",
                     "case_sha256"],
        "properties": {
            "case_id": {"type": "string"},
            "content_class": {"type": "string"},
            "length_regime": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
            "token_count": {"type": "integer"},
            "prompt_text": {"type": "string"},
            "token_ids": {"type": "array", "items": {"type": "integer"}},
            "prompt_sha256": SHA,
            "token_ids_sha256": SHA,
            "case_sha256": SHA,
        },
    }


def tokenizer_block() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["model", "revision", "tokenizer_json_sha256", "profile"],
        "properties": {
            "model": {"const": "google/gemma-4-12B-it"},
            "revision": {"const": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7"},
            "tokenizer_json_sha256": {"const": "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"},
            "profile": {"const": "raw-text encode(add_special_tokens=False); no chat template"},
        },
    }


def mixture_population_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "contract_id", "assumption_profile", "components",
                     "component_count", "component_weights", "component_selection_rule",
                     "draws_are_iid", "calibration_and_holdout_share_generator",
                     "calibration_namespace", "holdout_namespace", "generator", "note"],
        "properties": {
            "schema": {"const": "inferswarm.issue109.v5-mixture-population/1"},
            "contract_id": {"const": CONTRACT},
            "assumption_profile": {"const": "MIXTURE_POPULATION_EXCHANGEABILITY"},
            "components": {
                "type": "array", "minItems": V5_MIXTURE_COMPONENTS, "maxItems": V5_MIXTURE_COMPONENTS,
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["content_class", "length_regime"],
                    "properties": {
                        "content_class": {"type": "string"},
                        "length_regime": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                    },
                },
            },
            "component_count": {"const": V5_MIXTURE_COMPONENTS},
            "component_weights": {"type": "string"},
            "component_selection_rule": {"type": "string"},
            "draws_are_iid": {"const": True},
            "calibration_and_holdout_share_generator": {"const": True},
            "calibration_namespace": {"const": "calibration"},
            "holdout_namespace": {"const": "v5-sealed-holdout"},
            "generator": {"const": "scripts/generate_issue109_corpora.py"},
            "note": {"type": "string"},
        },
    }


def build() -> dict[str, dict]:
    schemas: dict[str, dict] = {}

    schemas["calibration-corpus.schema.json"] = schema(
        "calibration-corpus-1.json",
        f"InferSwarm issue #109 v5 {V5_CALIBRATION_CASES}-case mixture-population calibration corpus",
        ["schema", "contract_id", "generator", "generator_sha256", "tokenizer",
         "seed", "mixture_population", "cases", "disjointness"],
        {
            "schema": {"const": "inferswarm.issue109.v5-calibration-corpus/1"},
            "contract_id": {"const": CONTRACT},
            "generator": {"const": "scripts/generate_issue109_corpora.py"},
            "generator_sha256": SHA,
            "tokenizer": tokenizer_block(),
            "seed": {"const": "inferswarm-issue-109-calibration-v5-2"},
            "mixture_population": mixture_population_schema(),
            "cases": {"type": "array", "minItems": V5_CALIBRATION_CASES,
                      "maxItems": V5_CALIBRATION_CASES, "items": case_ref()},
            "disjointness": {"type": "string"},
        },
    )

    schemas["stress-pool.schema.json"] = schema(
        "stress-pool-1.json",
        f"InferSwarm issue #109 v5 {V5_STRESS_POOL_CASES}-case reference-only stress pool",
        ["schema", "contract_id", "generator", "generator_sha256", "tokenizer",
         "seed", "selection_input_only", "cases_per_cell", "cases", "disjointness"],
        {
            "schema": {"const": "inferswarm.issue109.v5-stress-pool/1"},
            "contract_id": {"const": CONTRACT},
            "generator": {"const": "scripts/generate_issue109_corpora.py"},
            "generator_sha256": SHA,
            "tokenizer": tokenizer_block(),
            "seed": {"const": "inferswarm-issue-109-stress-pool-v5"},
            "selection_input_only": {"const": "matched-reference-top1-margin"},
            "cases_per_cell": {"const": 2},
            "cases": {"type": "array", "minItems": V5_STRESS_POOL_CASES,
                      "maxItems": V5_STRESS_POOL_CASES, "items": case_ref()},
            "disjointness": {"type": "string"},
        },
    )

    schemas["reference-margin-summary.schema.json"] = schema(
        "reference-margin-summary-1.json",
        "InferSwarm issue #109 v5 reference-only margin summary over the p109 pool",
        ["schema", "contract_id", "margin_definition", "stress_pool_sha256", "cases"],
        {
            "schema": {"const": "inferswarm.issue109.v5-reference-margin-summary/1"},
            "contract_id": {"const": CONTRACT},
            "margin_definition": {"const": "min over all 8 greedy decisions of fp32(top1_logit - top2_logit)"},
            "stress_pool_sha256": SHA,
            "cases": {
                "type": "array", "minItems": V5_STRESS_POOL_CASES, "maxItems": V5_STRESS_POOL_CASES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "case_sha256", "top1_margin_hex"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "case_sha256": SHA,
                        "top1_margin_hex": HEX,
                    },
                },
            },
        },
    )

    schemas["selected-stress-eighth.schema.json"] = schema(
        "selected-stress-eighth-1.json",
        "InferSwarm issue #109 v5 selected-eight stress manifest (future physical artifact)",
        ["schema", "contract_id", "margin_definition", "margin_definition_unchanged_from",
         "stress_pool_sha256", "selection_commitment_sha256",
         "reference_margin_summary_sha256", "selection_inputs", "eligibility_rule",
         "selection_rule", "minimum_eligible_cases", "eligible_case_count",
         "ineligible_case_count", "ineligible_cases", "selected_count", "selected", "state"],
        {
            "schema": {"const": "inferswarm.issue109.v5-selected-stress-eighth/1"},
            "contract_id": {"const": CONTRACT},
            "margin_definition": {"type": "string"},
            "margin_definition_unchanged_from": {"type": "string"},
            "stress_pool_sha256": SHA,
            "selection_commitment_sha256": SHA,
            "reference_margin_summary_sha256": SHA,
            "selection_inputs": {"const": "MATCHED_REFERENCE_MARGINS_ONLY"},
            "eligibility_rule": {"type": "string"},
            "selection_rule": {"type": "string"},
            "minimum_eligible_cases": {"const": 8},
            "eligible_case_count": {"type": "integer", "minimum": 8},
            "ineligible_case_count": {"type": "integer", "minimum": 0},
            "ineligible_cases": {"type": "array", "items": {"type": "object"}},
            "selected_count": {"const": V5_SELECTED_STRESS_CASES},
            "selected": {
                "type": "array", "minItems": V5_SELECTED_STRESS_CASES, "maxItems": V5_SELECTED_STRESS_CASES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["selection_group", "case", "reference_top1_margin_hex",
                                 "exact_zero_margin"],
                    "properties": {
                        "selection_group": {"enum": ["four-smallest-including-zero", "four-largest"]},
                        "case": case_ref(),
                        "reference_top1_margin_hex": HEX,
                        "exact_zero_margin": {"type": "boolean"},
                    },
                },
            },
            "state": {"const": "FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE"},
        },
    )

    decision_row = {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision_index", "domain_membership_sha256", "domain_size"],
        "properties": {
            "decision_index": {"type": "integer", "minimum": 0, "maximum": 7},
            "domain_membership_sha256": SHA,
            "domain_size": {"type": "integer", "minimum": 1},
        },
    }
    schemas["decision-domain-manifest.schema.json"] = schema(
        "decision-domain-manifest-1.json",
        "InferSwarm issue #109 v5 reference-only decision-domain manifest (D(r) memberships)",
        ["schema", "contract_id", "construction", "k", "reference_derived_only",
         "candidate_membership_influence", "statistical_cases", "stress_cases"],
        {
            "schema": {"const": "inferswarm.issue109.v5-decision-domain-manifest/1"},
            "contract_id": {"const": CONTRACT},
            "construction": {"const": DOMAIN_ID},
            "k": {"const": 1024},
            "reference_derived_only": {"const": True},
            "candidate_membership_influence": {"const": "PROHIBITED"},
            "statistical_cases": {
                "type": "array", "minItems": V5_STATISTICAL_CASES, "maxItems": V5_STATISTICAL_CASES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "case_sha256", "decisions"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "case_sha256": SHA,
                        "decisions": {"type": "array", "minItems": 8, "maxItems": 8, "items": decision_row},
                    },
                },
            },
            "stress_cases": {
                "type": "array", "minItems": V5_SELECTED_STRESS_CASES, "maxItems": V5_SELECTED_STRESS_CASES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "case_sha256", "decisions"],
                    "properties": {
                        "case_id": {"type": "string"},
                        "case_sha256": SHA,
                        "decisions": {"type": "array", "minItems": 8, "maxItems": 8, "items": decision_row},
                    },
                },
            },
        },
    )

    semantic_decision_row = {
        "type": "object",
        "additionalProperties": False,
        "required": ["decision_index", "domain_membership_sha256", "domain_size",
                     "decision_local_error_hex"],
        "properties": {
            "decision_index": {"type": "integer", "minimum": 0, "maximum": 7},
            "domain_membership_sha256": SHA,
            "domain_size": {"type": "integer", "minimum": 1},
            "decision_local_error_hex": HEX,
        },
    }
    summary_case_row = {
        "type": "object",
        "additionalProperties": False,
        "required": ["case_id", "case_sha256", "exact_integrity", "finite",
                     "evidence_complete", "envelopes", "case_e_d_hex", "decisions"],
        "properties": {
            "case_id": {"type": "string"},
            "case_sha256": SHA,
            "exact_integrity": {"const": "PASS"},
            "finite": {"const": True},
            "evidence_complete": {"const": True},
            "envelopes": {
                "type": "object",
                "minProperties": 15,
                "maxProperties": 15,
                "propertyNames": {"enum": list(ENVELOPES)},
                "additionalProperties": HEX,
            },
            "case_e_d_hex": HEX,
            "decisions": {"type": "array", "minItems": 8, "maxItems": 8, "items": semantic_decision_row},
        },
    }
    schemas["calibration-summary.schema.json"] = schema(
        "calibration-summary-1.json",
        "InferSwarm issue #109 v5 calibration summary (15 envelopes + per-decision decision-local evidence)",
        ["schema", "contract_id", "tooling_version", "calibration_corpus_sha256",
         "stress_pool_sha256", "stress_selection_commitment_sha256",
         "reference_margin_summary_sha256",
         "stress_selection_sha256", "decision_domain_manifest_sha256",
         "evidence_sha256", "statistical_cases", "stress_cases"],
        {
            "schema": {"const": "inferswarm.issue109.v5-calibration-summary/1"},
            "contract_id": {"const": CONTRACT},
            "tooling_version": {"const": "inferswarm.issue109.v5-threshold-tooling/1"},
            "calibration_corpus_sha256": SHA,
            "stress_pool_sha256": SHA,
            "stress_selection_commitment_sha256": SHA,
            "reference_margin_summary_sha256": SHA,
            "stress_selection_sha256": SHA,
            "decision_domain_manifest_sha256": SHA,
            "evidence_sha256": {"type": "array", "minItems": 1, "uniqueItems": True, "items": SHA},
            "statistical_cases": {"type": "array", "minItems": V5_STATISTICAL_CASES,
                                   "maxItems": V5_STATISTICAL_CASES, "items": summary_case_row},
            "stress_cases": {"type": "array", "minItems": V5_SELECTED_STRESS_CASES,
                              "maxItems": V5_SELECTED_STRESS_CASES, "items": summary_case_row},
        },
    )

    limit = {
        "type": "object",
        "additionalProperties": False,
        "required": ["statistical_max_hex", "stress_max_hex", "limit_hex", "rule", "comparison"],
        "properties": {
            "statistical_max_hex": HEX,
            "stress_max_hex": HEX,
            "limit_hex": HEX,
            "rule": {"const": "max(statistical_max,stress_max)"},
            "comparison": {"const": "observed<=limit"},
        },
    }
    core_ids = [
        "fp32-consumer-logits:max-absolute-difference",
        "fp32-consumer-logits:rms-difference",
        "decision_local_E_D",
    ]
    telemetry_ids = sorted(
        identity for identity in ENVELOPES
        if identity != "fp32-consumer-logits:max-absolute-difference"
        and identity != "fp32-consumer-logits:rms-difference"
    )
    provenance = {
        "type": "object", "additionalProperties": False,
        "required": ["calibration_corpus_sha256", "calibration_summary_sha256",
                     "calibration_evidence_sha256", "selected_stress_sha256",
                     "decision_domain_manifest_sha256", "derivation_program_sha256",
                     "holdout_commitment_sha256", "holdout_custody_record_sha256", "argmax_tie_break"],
        "properties": {
            "calibration_corpus_sha256": SHA, "calibration_summary_sha256": SHA,
            "calibration_evidence_sha256": {"type": "array", "minItems": 1, "uniqueItems": True, "items": SHA},
            "selected_stress_sha256": SHA, "decision_domain_manifest_sha256": SHA,
            "derivation_program_sha256": SHA, "holdout_commitment_sha256": SHA,
            "holdout_custody_record_sha256": SHA,
            "argmax_tie_break": {"const": TIE_BREAK},
        },
    }
    schemas["core-threshold-manifest.schema.json"] = schema(
        "core-threshold-manifest-1.json",
        "InferSwarm issue #109 v5 three-identity conjunctive core threshold manifest",
        ["schema", "contract_id", "comparator_tier_contract_sha256", "provenance",
         "limits", "holdout_state", "manual_editing_or_rounding"],
        {"schema": {"const": "inferswarm.issue109.v5-core-threshold-manifest/1"},
         "contract_id": {"const": CONTRACT}, "comparator_tier_contract_sha256": SHA,
         "provenance": provenance,
         "limits": {"type": "object", "additionalProperties": False,
                    "required": core_ids,
                    "properties": {identity: limit for identity in core_ids}},
         "holdout_state": {"const": "SEALED_NOT_CONSUMED"},
         "manual_editing_or_rounding": {"const": "PROHIBITED"}},
    )
    telemetry_band = {**limit, "required": ["statistical_max_hex", "stress_max_hex", "limit_hex", "rule", "comparison", "qualification_semantics"],
                      "properties": {**limit["properties"], "qualification_semantics": {"const": "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE"}}}
    schemas["telemetry-reference-bands.schema.json"] = schema(
        "telemetry-reference-bands-1.json",
        "InferSwarm issue #109 v5 thirteen-identity telemetry reference-band manifest",
        ["schema", "contract_id", "comparator_tier_contract_sha256", "provenance",
         "bands", "holdout_state", "manual_editing_or_rounding", "finite_exceedance"],
        {"schema": {"const": "inferswarm.issue109.v5-telemetry-reference-bands/1"},
         "contract_id": {"const": CONTRACT}, "comparator_tier_contract_sha256": SHA,
         "provenance": provenance,
         "bands": {"type": "object", "additionalProperties": False,
                   "required": telemetry_ids,
                   "properties": {identity: telemetry_band for identity in telemetry_ids}},
         "holdout_state": {"const": "SEALED_NOT_CONSUMED"},
         "manual_editing_or_rounding": {"const": "PROHIBITED"},
         "finite_exceedance": {"const": "TELEMETRY_ALERT_NOT_QUALIFICATION_FAILURE"}},
    )

    schemas["sealed-holdout-commitment.schema.json"] = schema(
        "sealed-holdout-commitment-1.json",
        "InferSwarm issue #109 v5 public sealed-holdout commitment",
        ["schema", "contract_id", "state", "case_count", "draws", "secret_seed_sha256",
         "generator", "generator_sha256", "tokenizer_json_sha256", "cipher",
         "ciphertext_sha256", "recipient_certificate_sha256", "unseal_rule",
         "plaintext_retention"],
        {
            "schema": {"const": "inferswarm.issue109.v5-holdout-commitment/1"},
            "contract_id": {"const": CONTRACT},
            "state": {"const": "SEALED_NOT_CONSUMED"},
            "case_count": {"const": V5_HOLDOUT_CASES},
            "draws": {
                "type": "array", "minItems": V5_HOLDOUT_CASES, "maxItems": V5_HOLDOUT_CASES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "content_class", "length_regime", "token_count",
                                 "prompt_sha256", "token_ids_sha256", "case_sha256"],
                    "properties": {
                        "case_id": {"type": "string", "pattern": "^h109-"},
                        "content_class": {"type": "string"},
                        "length_regime": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
                        "token_count": {"type": "integer"},
                        "prompt_sha256": SHA,
                        "token_ids_sha256": SHA,
                        "case_sha256": SHA,
                    },
                },
            },
            "secret_seed_sha256": SHA,
            "generator": {"type": "string"},
            "generator_sha256": SHA,
            "tokenizer_json_sha256": SHA,
            "cipher": {"const": "CMS EnvelopedData; AES-256-CBC; RSA-3072 recipient"},
            "ciphertext_sha256": SHA,
            "recipient_certificate_sha256": SHA,
            "unseal_rule": {"type": "string"},
            "plaintext_retention": {"const": "PROHIBITED_IN_REPOSITORY"},
        },
    )

    schemas["holdout-custody-record.schema.json"] = schema(
        "holdout-custody-record-1.json",
        "InferSwarm issue #109 v5 non-secret holdout custody record",
        ["schema", "contract_id", "custodians", "holdout_ciphertext_sha256",
         "recipient_certificate_sha256", "recipient_public_key_der_sha256",
         "holdout_state", "private_material_in_repository", "fail_closed_rule",
         "unseal_authorized", "custody_history", "verification_method"],
        {
            "schema": {"const": "inferswarm.issue109.v5-holdout-custody-record/1"},
            "contract_id": {"const": CONTRACT},
            "custodians": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["custodian_id", "files", "host", "location", "ownership",
                                 "permissions", "private_key_sha256", "public_key_match",
                                 "verified_date"],
                    "properties": {
                        "custodian_id": {"type": "string"},
                        "files": {"type": "string"},
                        "host": {"type": "string"},
                        "location": {"type": "string"},
                        "ownership": {"type": "string"},
                        "permissions": {"type": "string"},
                        "private_key_sha256": SHA,
                        "public_key_match": {"const": True},
                        "verified_date": {"type": "string"},
                    },
                },
            },
            "holdout_ciphertext_sha256": SHA,
            "recipient_certificate_sha256": SHA,
            "recipient_public_key_der_sha256": SHA,
            "holdout_state": {"enum": ["SEALED_NOT_CONSUMED", "SEALED_CUSTODY_INCOMPLETE"]},
            "private_material_in_repository": {"const": "PROHIBITED"},
            "fail_closed_rule": {"type": "string"},
            "unseal_authorized": {"const": False},
            "custody_history": {"type": "string"},
            "verification_method": {"type": "string"},
            "outstanding_action": {"type": "string"},
        },
    )

    schemas["mixture-population.schema.json"] = schema(
        "mixture-population-1.json",
        "InferSwarm issue #109 v5 frozen mixture-population generator declaration",
        list(mixture_population_schema()["required"]),
        mixture_population_schema()["properties"],
    )

    return schemas


def main() -> int:
    SCHEMAS.mkdir(parents=True, exist_ok=True)
    for name, doc in sorted(build().items()):
        (SCHEMAS / name).write_bytes(canonical_json_bytes(doc))
        print("wrote", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
