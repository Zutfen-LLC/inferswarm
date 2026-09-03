#!/usr/bin/env python3
"""Build small frozen manifests from the issue #74 corpus artifacts."""
from __future__ import annotations

import json
from pathlib import Path

from issue74_methodology import (
    CONTENT_CLASSES,
    CONTRACT_ID,
    ENVELOPES,
    FAMILYWISE_CONFIDENCE,
    LENGTH_REGIMES,
    METHODOLOGY_SCHEMA,
    POPULATION_CONTENT,
    SELECTED_CALIBRATION_CASES,
    canonical_json_bytes,
    minimum_sample_size,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/qualification/gemma4-12b-it-v1"
MANIFESTS = BASE / "manifests"


def load(name: str) -> dict:
    return json.loads((MANIFESTS / name).read_text())


def write(name: str, value: dict) -> None:
    (MANIFESTS / name).write_bytes(canonical_json_bytes(value))


def main() -> int:
    calibration = load("calibration-corpus.json")
    stress = load("margin-stress-pool.json")
    holdout = load("sealed-holdout-commitment.json")

    by_cell = {(row["content_class"], tuple(row["length_regime"])): [] for row in calibration["cases"]}
    for row in calibration["cases"]:
        by_cell[(row["content_class"], tuple(row["length_regime"]))].append(row)
    sentinel_cases = []
    for class_index, class_name in enumerate(CONTENT_CLASSES):
        for offset, regime_index in enumerate((class_index % 4, (class_index + 2) % 4)):
            source = by_cell[(class_name, LENGTH_REGIMES[regime_index])][class_index + offset * 12]
            sentinel_cases.append({key: source[key] for key in (
                "case_id", "content_class", "length_regime", "token_count", "prompt_sha256",
                "token_ids_sha256", "case_sha256",
            )})
    write("sentinel-subset.json", {
        "schema": "inferswarm.issue74.sentinel-subset/1",
        "contract_id": CONTRACT_ID,
        "source_calibration_manifest_sha256": sha256_file(MANIFESTS / "calibration-corpus.json"),
        "selection_rule": "two cases per content class; three cases per length regime; fixed class-index selection",
        "case_count": 12,
        "cases": sentinel_cases,
        "arms": ["same-device-repeatability", "same-device-class-cross-card", "heterogeneous-same-input-stage"],
        "fresh_process_realizations_per_device_minimum": 3,
    })

    write("margin-stress-selection-commitment.json", {
        "schema": "inferswarm.issue74.margin-stress-selection-commitment/1",
        "contract_id": CONTRACT_ID,
        "state": "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION",
        "candidate_pool_sha256": sha256_file(MANIFESTS / "margin-stress-pool.json"),
        "candidate_pool_case_count": len(stress["cases"]),
        "selection_program": "scripts/select_issue74_margin_stress.py",
        "selection_program_sha256": sha256_file(ROOT / "scripts/select_issue74_margin_stress.py"),
        "selection_rule": "sort finite positive matched-reference top-1 margins by (margin,case_id); select four smallest and four largest",
        "selected_case_count": 8,
        "smallest_positive_count": 4,
        "largest_count": 4,
        "candidate_observations_forbidden": True,
        "freeze_barrier": "selected manifest must be committed before any heterogeneous candidate execution",
    })

    checkpoints = [
        ("embedding-output", "local-bf16-backend-operation-output", "complete token-row x hidden domain", "bfloat16", True),
        ("layer-0-o-proj-input", "local-bf16-backend-operation-output", "complete o_proj input tensor", "bfloat16", False),
        ("layer-0-o-proj-output", "local-bf16-backend-operation-output", "complete o_proj output tensor", "bfloat16", False),
        ("global-layer-15-attention-o-proj-output", "local-bf16-backend-operation-output", "complete projection output tensor", "bfloat16", False),
        ("post-global-layer-15-residual", "hidden-residual-stream", "complete residual tensor", "bfloat16", False),
        ("post-global-layer-31-residual", "hidden-residual-stream", "complete residual tensor", "bfloat16", False),
        ("post-global-layer-47-residual", "hidden-residual-stream", "complete residual tensor", "bfloat16", False),
        ("final-normalized-hidden-state", "final-normalized-hidden-state", "complete final-row hidden tensor", "bfloat16", False),
        ("full-final-row-bf16-logits", "bf16-logits", "full 262144-value vocabulary row", "bfloat16", False),
        ("full-final-row-fp32-consumer-logits", "fp32-consumer-logits", "full 262144-value greedy-consumer row", "float32", False),
    ]
    write("checkpoint-family-map.json", {
        "schema": "inferswarm.issue74.checkpoint-family-map/1",
        "contract_id": CONTRACT_ID,
        "replay_capture_positions": [0, 1, 3, 7],
        "checkpoints": [{
            "checkpoint_id": checkpoint_id,
            "family": family,
            "comparison_domain": domain,
            "semantic_dtype": dtype,
            "exact_reference_sanity_gate": sanity,
            "mandatory_metrics": ["max-absolute-difference", "rms-difference", "p99-absolute-error"],
        } for checkpoint_id, family, domain, dtype, sanity in checkpoints],
        "boundary_sender_receiver_bytes": "EXACT_OUTSIDE_NUMERICAL_ENVELOPES",
    })

    minimum = minimum_sample_size()
    write("sample-size-derivation.json", {
        "schema": "inferswarm.issue74.sample-size-derivation/1",
        "contract_id": CONTRACT_ID,
        "population_content_p": POPULATION_CONTENT,
        "familywise_confidence": FAMILYWISE_CONFIDENCE,
        "familywise_alpha": 1.0 - FAMILYWISE_CONFIDENCE,
        "mandatory_envelope_count": len(ENVELOPES),
        "bonferroni_per_envelope_alpha": (1.0 - FAMILYWISE_CONFIDENCE) / len(ENVELOPES),
        "probability_statement": "P(F(X_(n))>=p)=1-p^n>=1-alpha_i",
        "minimum_n": minimum,
        "selected_n": SELECTED_CALIBRATION_CASES,
        "selection_reason": "24 balanced cells times 24 independent cases",
        "interpretation_limit": "marginal 0.99 population coverage for each envelope with simultaneous 0.95 confidence; not joint request-pass probability",
    })

    write("qualification-draft.json", {
        "schema": "inferswarm.issue74.qualification-draft/1",
        "contract_id": CONTRACT_ID,
        "state": "NOT_QUALIFIED_METHODOLOGY_ONLY",
        "planner_eligibility": "EXCLUDED_PENDING_APPLICABLE_QUALIFICATION",
        "semantic_identity": {
            "model": "google/gemma-4-12B-it",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "checkpoint_sha256": "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
            "strategy": "freetoken.gemma4-dense-serving/1",
            "contract_version": 1,
            "representation": "native-bf16-text",
            "execution_mode": "deterministic-greedy-replay-prefill",
        },
        "applicability_fields": [
            "FreeToken source and build", "torch", "CUDA runtime", "driver", "Triton",
            "native extensions", "cuBLAS and observable math libraries", "GPU architecture",
            "GPU product class", "ordered stage-role mapping", "attention and math modes",
            "matrix, sequence, replay, and chunk geometry",
        ],
        "reference_scope": "inferswarm04 RTX 3090 instance-bound",
        "candidate_scope": "three-stage RTX 3060 chain; class claim requires two physical RTX 3060 cards",
        "required_evidence": ["Arm A", "Arm B", "Arm C", "Arm D", "derived threshold manifest", "sealed holdout zero-exceedance result"],
        "evidence_sha256": [],
        "limits": None,
        "physical_execution_authorized": False,
    })

    methodology = {
        "schema": METHODOLOGY_SCHEMA,
        "contract_id": CONTRACT_ID,
        "methodology_version": 1,
        "status": "FROZEN_METHODOLOGY_PHYSICAL_EXECUTION_NOT_AUTHORIZED",
        "authoritative_sources": {
            "architecture_commit": "9b514c3880189a068dcdd850c476043ebfa0f430",
            "adr": "docs/adr/0010-heterogeneous-numerical-equivalence.md",
            "normative_supplement": "docs/architecture/numerical-equivalence-contract.md",
            "freetoken_base": "d4d16089165917704a87f4e2f0c4a09969646f95",
        },
        "subject": {
            "model": "google/gemma-4-12B-it",
            "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
            "checkpoint_sha256": "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
            "representation": "native BF16 text execution",
            "attention_backend": "Triton",
            "execution": "deterministic greedy replay-prefill only",
            "replay_chunk_rows": 64,
            "reference": "matched single-GPU FreeToken on inferswarm04 RTX 3090",
            "candidate": "accepted three-stage RTX 3060 chain",
            "excluded": ["incremental KV extend", "multi-chunk", "Transformers-vs-FreeToken baseline gate"],
        },
        "correctness_layers": ["exact-integrity", "qualified-numerical-equivalence", "exact-deterministic-greedy-semantics"],
        "checkpoint_families": [envelope.split(":", 1)[0] for envelope in ENVELOPES[::3]],
        "metrics": ["max-absolute-difference", "rms-difference", "p99-absolute-error"],
        "mandatory_envelopes": list(ENVELOPES),
        "reducer": {
            "arithmetic": "host IEEE-754 binary64; math.fsum for sum of squared errors",
            "tail": "sort ascending; rank=ceil(0.99*N); use one-based rank (nearest-rank/higher)",
            "case_family": "maximum checkpoint value per metric across all declared checkpoints and replay positions",
            "comparison": "inclusive observed<=frozen_limit",
        },
        "statistical_design": {
            "population_content": 0.99,
            "familywise_confidence": 0.95,
            "bonferroni_envelopes": 15,
            "minimum_n": minimum,
            "selected_n": 576,
            "cell_count": 24,
            "cases_per_cell": 24,
            "independent_unit": "one deterministic prompt case",
        },
        "corpora": {
            "calibration_manifest_sha256": sha256_file(MANIFESTS / "calibration-corpus.json"),
            "calibration_case_count": 576,
            "stress_pool_manifest_sha256": sha256_file(MANIFESTS / "margin-stress-pool.json"),
            "stress_pool_case_count": 48,
            "stress_selected_case_count": 8,
            "holdout_commitment_sha256": sha256_file(MANIFESTS / "sealed-holdout-commitment.json"),
            "holdout_ciphertext_sha256": holdout["ciphertext_sha256"],
            "holdout_case_count": 24,
        },
        "generation": {
            "program": "scripts/generate_issue74_corpora.py",
            "program_sha256": calibration["generator_sha256"],
            "tokenizer_json_sha256": calibration["tokenizer"]["tokenizer_json_sha256"],
            "calibration_seed": calibration["seed"],
            "stress_pool_seed": stress["seed"],
            "holdout_seed": "WITHHELD; SHA-256 committed inside sealed-holdout-commitment.json",
        },
        "semantic_profile": {"generated_tokens": 8, "capture_positions": [0, 1, 3, 7], "exact_token_positions": list(range(8))},
        "threshold_rule": "max(576-case statistical maximum,8-case stress maximum) for each envelope",
        "threshold_input_policy": "calibration summaries and frozen methodology only; all holdout fields and case IDs are rejected",
        "holdout_acceptance": "zero exceedances; exact integrity, applicability, finite values, all envelopes, all token IDs, and required role coverage",
        "historical_r6": "R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL_UNTOUCHED",
        "authorization": "STOP_FOR_MAINTAINER_REVIEW_BEFORE_PHYSICAL_CALIBRATION",
    }
    write("methodology.json", methodology)
    write("methodology-build-audit.json", {
        "schema": "inferswarm.issue74.methodology-build-audit/1",
        "contract_id": CONTRACT_ID,
        "scope": "methodology artifact creation and CPU-only regression checks",
        "allowed_inputs": ["repository files", "pinned tokenizer.json", "holdout secret seed during initial generation", "OpenSSL recipient certificate"],
        "allowed_programs": ["Python standard library", "tokenizers.Tokenizer", "OpenSSL CMS"],
        "model_weights_read": False,
        "gemma_executed": False,
        "torch_imported": False,
        "cuda_initialized": False,
        "gpu_queried": False,
        "triton_imported": False,
        "calibration_executed": False,
        "holdout_unsealed": False,
        "historical_r6_evidence_modified": False,
        "holdout_initial_sealing": "COMPLETE; plaintext removed after commitment creation",
        "physical_execution_authorized": False,
        "next_action": "STOP_FOR_MAINTAINER_REVIEW",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
