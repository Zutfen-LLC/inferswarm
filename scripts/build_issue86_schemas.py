#!/usr/bin/env python3
"""Emit the versioned v3 JSON Schemas (issue #86) deterministically.

CPU-only, pure stdlib. Running this script always produces byte-identical
schema files (canonical JSON), so the committed schemas are reproducible.
"""
from __future__ import annotations

from pathlib import Path

from issue74_methodology import ENVELOPES, canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs/qualification/gemma4-12b-it-v3/schemas"
BASE = "https://inferswarm.dev/schema/issue86/"
CONTRACT = "inferswarm.gemma4-heterogeneous-numerical-equivalence/1"
DOMAIN_ID = "reference-top-1024-with-cutoff-ties/1"
TIE_BREAK = "ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima"
REDUCER = "host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1"
E_D_REDUCER = (
    "case_E_D=max over 8 decisions of decision_local_error; "
    "statistical_E_D=max over 576 statistical cases; "
    "stress_E_D=max over 8 selected stress cases; E_D=max(statistical_E_D,stress_E_D)"
)

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


def build() -> dict[str, dict]:
    schemas: dict[str, dict] = {}

    schemas["calibration-corpus.schema.json"] = schema(
        "calibration-corpus-1.json",
        "InferSwarm issue #86 v3 576-case statistical calibration corpus",
        ["schema", "contract_id", "generator", "generator_sha256", "tokenizer",
         "seed", "cases_per_cell", "cases", "disjointness"],
        {
            "schema": {"const": "inferswarm.issue86.v3-calibration-corpus/1"},
            "contract_id": {"const": CONTRACT},
            "generator": {"const": "scripts/generate_issue86_corpora.py"},
            "generator_sha256": SHA,
            "tokenizer": tokenizer_block(),
            "seed": {"const": "inferswarm-issue-86-calibration-v3"},
            "cases_per_cell": {"const": 24},
            "cases": {"type": "array", "minItems": 576, "maxItems": 576, "items": case_ref()},
            "disjointness": {"type": "string"},
        },
    )

    schemas["stress-pool.schema.json"] = schema(
        "stress-pool-1.json",
        "InferSwarm issue #86 v3 48-case reference-only stress pool",
        ["schema", "contract_id", "generator", "generator_sha256", "tokenizer",
         "seed", "selection_input_only", "cases_per_cell", "cases", "disjointness"],
        {
            "schema": {"const": "inferswarm.issue86.v3-stress-pool/1"},
            "contract_id": {"const": CONTRACT},
            "generator": {"const": "scripts/generate_issue86_corpora.py"},
            "generator_sha256": SHA,
            "tokenizer": tokenizer_block(),
            "seed": {"const": "inferswarm-issue-86-stress-pool-v3"},
            "selection_input_only": {"const": "matched-reference-top1-margin"},
            "cases_per_cell": {"const": 2},
            "cases": {"type": "array", "minItems": 48, "maxItems": 48, "items": case_ref()},
            "disjointness": {"type": "string"},
        },
    )

    schemas["reference-margin-summary.schema.json"] = schema(
        "reference-margin-summary-1.json",
        "InferSwarm issue #86 v3 reference-only margin summary over the p86 pool",
        ["schema", "contract_id", "margin_definition", "stress_pool_sha256", "cases"],
        {
            "schema": {"const": "inferswarm.issue86.v3-reference-margin-summary/1"},
            "contract_id": {"const": CONTRACT},
            "margin_definition": {"const": "min over all 8 greedy decisions of fp32(top1_logit - top2_logit)"},
            "stress_pool_sha256": SHA,
            "cases": {
                "type": "array", "minItems": 48, "maxItems": 48,
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
        "InferSwarm issue #86 v3 selected-eight stress manifest (future physical artifact)",
        ["schema", "contract_id", "margin_definition", "margin_definition_unchanged_from",
         "stress_pool_sha256", "selection_commitment_sha256",
         "reference_margin_summary_sha256", "selection_inputs", "eligibility_rule",
         "selection_rule", "minimum_eligible_cases", "eligible_case_count",
         "ineligible_case_count", "ineligible_cases", "selected_count", "selected", "state"],
        {
            "schema": {"const": "inferswarm.issue86.v3-selected-stress-eighth/1"},
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
            "selected_count": {"const": 8},
            "selected": {
                "type": "array", "minItems": 8, "maxItems": 8,
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
        "InferSwarm issue #86 v3 reference-only decision-domain manifest (D(r) memberships)",
        ["schema", "contract_id", "construction", "k", "reference_derived_only",
         "candidate_membership_influence", "statistical_cases", "stress_cases"],
        {
            "schema": {"const": "inferswarm.issue86.v3-decision-domain-manifest/1"},
            "contract_id": {"const": CONTRACT},
            "construction": {"const": DOMAIN_ID},
            "k": {"const": 1024},
            "reference_derived_only": {"const": True},
            "candidate_membership_influence": {"const": "PROHIBITED"},
            "statistical_cases": {
                "type": "array", "minItems": 576, "maxItems": 576,
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
                "type": "array", "minItems": 8, "maxItems": 8,
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
        "InferSwarm issue #86 v3 calibration summary (15 envelopes + per-decision decision-local evidence)",
        ["schema", "contract_id", "tooling_version", "calibration_corpus_sha256",
         "stress_pool_sha256", "stress_selection_commitment_sha256",
         "reference_margin_summary_sha256",
         "stress_selection_sha256", "decision_domain_manifest_sha256",
         "evidence_sha256", "statistical_cases", "stress_cases"],
        {
            "schema": {"const": "inferswarm.issue86.v3-calibration-summary/1"},
            "contract_id": {"const": CONTRACT},
            "tooling_version": {"const": "inferswarm.issue86.v3-threshold-tooling/1"},
            "calibration_corpus_sha256": SHA,
            "stress_pool_sha256": SHA,
            "stress_selection_commitment_sha256": SHA,
            "reference_margin_summary_sha256": SHA,
            "stress_selection_sha256": SHA,
            "decision_domain_manifest_sha256": SHA,
            "evidence_sha256": {"type": "array", "minItems": 1, "uniqueItems": True, "items": SHA},
            "statistical_cases": {"type": "array", "minItems": 576, "maxItems": 576, "items": summary_case_row},
            "stress_cases": {"type": "array", "minItems": 8, "maxItems": 8, "items": summary_case_row},
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
    schemas["threshold-manifest.schema.json"] = schema(
        "threshold-manifest-1.json",
        "InferSwarm issue #86 v3 threshold manifest (15 numerical limits + E_D + frozen semantic provenance)",
        ["schema", "contract_id", "tooling_version", "calibration_corpus_sha256",
         "calibration_case_ids_sha256", "calibration_case_identities_sha256",
         "calibration_summary_sha256", "calibration_evidence_sha256",
         "stress_pool_sha256", "stress_selection_commitment_sha256",
         "reference_margin_summary_sha256",
         "stress_selection_sha256", "decision_domain_manifest_sha256",
         "derivation_program_sha256", "metric_reducer", "e_d_reducer",
         "decision_domain_construction", "e_d_hex", "statistical_e_d_hex",
         "stress_e_d_hex", "argmax_tie_break", "limits", "holdout_state",
         "manual_editing_or_rounding"],
        {
            "schema": {"const": "inferswarm.issue86.v3-threshold-manifest/1"},
            "contract_id": {"const": CONTRACT},
            "tooling_version": {"const": "inferswarm.issue86.v3-threshold-tooling/1"},
            "calibration_corpus_sha256": SHA,
            "calibration_case_ids_sha256": SHA,
            "calibration_case_identities_sha256": SHA,
            "calibration_summary_sha256": SHA,
            "calibration_evidence_sha256": {"type": "array", "minItems": 1, "uniqueItems": True, "items": SHA},
            "stress_pool_sha256": SHA,
            "stress_selection_commitment_sha256": SHA,
            "reference_margin_summary_sha256": SHA,
            "stress_selection_sha256": SHA,
            "decision_domain_manifest_sha256": SHA,
            "derivation_program_sha256": SHA,
            "metric_reducer": {"const": REDUCER},
            "e_d_reducer": {"const": E_D_REDUCER},
            "decision_domain_construction": {"const": DOMAIN_ID},
            "e_d_hex": HEX,
            "statistical_e_d_hex": HEX,
            "stress_e_d_hex": HEX,
            "argmax_tie_break": {"const": TIE_BREAK},
            "limits": {
                "type": "object",
                "minProperties": 15,
                "maxProperties": 15,
                "propertyNames": {"enum": list(ENVELOPES)},
                "additionalProperties": limit,
            },
            "holdout_state": {"const": "SEALED_NOT_CONSUMED"},
            "manual_editing_or_rounding": {"const": "PROHIBITED"},
        },
    )

    schemas["sealed-holdout-commitment.schema.json"] = schema(
        "sealed-holdout-commitment-1.json",
        "InferSwarm issue #86 v3 public sealed-holdout commitment",
        ["schema", "contract_id", "state", "case_count", "cells", "secret_seed_sha256",
         "generator", "generator_sha256", "tokenizer_json_sha256", "cipher",
         "ciphertext_sha256", "recipient_certificate_sha256", "unseal_rule",
         "plaintext_retention", "historical_h74_holdout_reuse",
         "historical_h74_ciphertext_sha256"],
        {
            "schema": {"const": "inferswarm.issue86.v3-holdout-commitment/1"},
            "contract_id": {"const": CONTRACT},
            "state": {"const": "SEALED_NOT_CONSUMED"},
            "case_count": {"const": 24},
            "cells": {
                "type": "array", "minItems": 24, "maxItems": 24,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "content_class", "length_regime", "token_count",
                                 "prompt_sha256", "token_ids_sha256", "case_sha256"],
                    "properties": {
                        "case_id": {"type": "string", "pattern": "^h86-"},
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
            "historical_h74_holdout_reuse": {"const": "PROHIBITED_PERMANENTLY"},
            "historical_h74_ciphertext_sha256": {"const": "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59"},
        },
    )

    schemas["holdout-custody-record.schema.json"] = schema(
        "holdout-custody-record-1.json",
        "InferSwarm issue #86 v3 non-secret holdout custody record",
        ["schema", "contract_id", "custodians", "holdout_ciphertext_sha256",
         "recipient_certificate_sha256", "recipient_public_key_der_sha256",
         "holdout_state", "private_material_in_repository", "fail_closed_rule",
         "unseal_authorized", "custody_history", "verification_method"],
        {
            "schema": {"const": "inferswarm.issue86.v3-holdout-custody-record/1"},
            "contract_id": {"const": CONTRACT},
            "custodians": {
                "type": "array", "minItems": 2,
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
            "holdout_state": {"const": "SEALED_NOT_CONSUMED"},
            "private_material_in_repository": {"const": "PROHIBITED"},
            "fail_closed_rule": {"type": "string"},
            "unseal_authorized": {"const": False},
            "custody_history": {"type": "string"},
            "verification_method": {"type": "string"},
        },
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
