#!/usr/bin/env python3
"""InferSwarm issue #237 Qwen3.8 Vulkan v1 qualification methodology (CPU-only).

Instantiates ADR 0010/0011/0012 and the accepted issue #108 statistical
doctrine for the FIRST heterogeneous-Vulkan Qwen3.8-Flash-Next UD-IQ1_S
qualification subject:

- assumption profile:   MIXTURE_POPULATION_EXCHANGEABILITY
- construction:         POOLED_ORDER_STATISTIC_PREDICTION
- qualification claim:  ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE
- semantic profile:     decision-stability (ADR 0010 §1.3), full-vocabulary
                        decision domain D (issue #237 preferred v1
                        simplification), ordered NVIDIA/Vulkan reference.

Pure stdlib: never imports an execution runtime, never queries accelerators,
never loads model weights (the pinned tokenizer JSON is metadata only).

All statistical identities are derived, never transcribed: the calibration
count N is solved mechanically from the frozen M/H/alpha so that
``M * H / (N + H) <= alpha``.
"""
from __future__ import annotations

import hashlib
import random
from fractions import Fraction
from typing import Any, Iterator

# Semantic machinery: ADR 0010 §1.3 decision-stability gate is instantiated
# here for the Qwen subject with the FULL VOCABULARY as D. The frozen
# argmax/tie-break rule identity and the E_D derivation law reuse the accepted
# Gemma v4/v5 helper SEMANTICS (same functions, new subject constants) — the
# Qwen comparator is a NEW comparator identity, not a Gemma evidence transfer.
from issue95_v4_methodology import (  # noqa: F401 (re-exported identity)
    DECISION_DOMAIN_ESCAPE,
    DECISION_LOCAL_BOUND_EXCEEDED,
    SEMANTIC_PASS,
    ambiguity_set,
    argmax_tie_break_identity,
    case_e_d as gemma_case_e_d,
    decision_local_error,
    decision_local_error_identity,
    domain_membership_sha256,
    e_d_reducer_identity,
    frozen_argmax,
    is_sha256,
    margin_on_domain,
)
from issue237_length_bands import (  # noqa: F401 (authority re-export)
    derive_length_regimes,
    length_regimes_provenance,
    validate_frozen_bands,
)
from issue74_methodology import (
    MethodologyError,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)

CONTRACT_ID = "inferswarm.qwen38-vulkan-heterogeneous-qualification/1"
METHODOLOGY_ID = "inferswarm.issue237.vulkan-v1-methodology/1"

# --- immutable doctrine/prerequisite identities -----------------------------

ADR0010_PATH = "docs/adr/0010-heterogeneous-numerical-equivalence.md"
ADR0011_PATH = "docs/adr/0011-two-tier-numerical-core-and-telemetry.md"
ADR0012_PATH = "docs/adr/0012-statistical-qualification-and-consumer-metric-doctrine.md"
NUMERICAL_CONTRACT_PATH = "docs/architecture/numerical-equivalence-contract.md"
STATISTICAL_CONTRACT_PATH = (
    "docs/qualification/post-v4-statistical-metric-doctrine/statistical-contract.json"
)
V5_PRECEDENT_PATH = "docs/qualification/gemma4-12b-it-v5/METHODOLOGY.md"
R8H_EVIDENCE_DIR = "docs/investigations/qwen38-flash-next-r8-h-vulkan"
R8H_MERGE_SHA = "dda4e8f83db967ebac7936f21b1732dcd5fc53a6"
R8H_REVIEWED_HEAD = "8438d88f4372a7af7f867bbeb9cb137cc84d3e86"
R8H_TERMINAL = "R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED"
R8G_ACCEPTED_RESULT = "R8G_QWEN38_NON_MONOTONIC_DIAGNOSTIC_ACCEPTED"  # historical diagnostic context only

# --- frozen Qwen/Vulkan physical subject (R8-H authority, bound not copied) --

QWEN_MODEL = "Qwen/Qwen3.8-Flash-Next"
QWEN_OFFICIAL_REVISION = "de4b8e4d43b917e7706784d8bb445c9af86a3540"
UNSLOTH_REPO = "unsloth/Qwen3.8-Flash-Next-GGUF"
UNSLOTH_REVISION = "38bb39ee97821de2c9009abb7e93950eec396e66"
REPRESENTATION = "UD-IQ1_S"
GGUF_MEMBERS: tuple[dict[str, Any], ...] = (
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
        "bytes": 10946624,
        "sha256": "88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd",
    },
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf",
        "bytes": 49990818368,
        "sha256": "3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6",
    },
    {
        "member": "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf",
        "bytes": 22544696352,
        "sha256": "0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a",
    },
)
GGUF_TOTAL_BYTES = 72546461344

LLAMA_CPP_PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
LLAMA_VULKAN_BINARY_SHA256 = (
    "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e"
)
LLAMA_VULKAN_BUILD = {
    "GGML_CUDA": "OFF",
    "GGML_VULKAN": "ON",
    "GGML_NATIVE": "OFF",
    "GGML_AVX": "OFF",
    "GGML_AVX2": "OFF",
    "GGML_FMA": "OFF",
    "GGML_F16C": "OFF",
    "GGML_BMI2": "OFF",
    "note": (
        "single Vulkan build produced once on inferswarm01 at the pinned "
        "source and deployed byte-identically to both execution hosts "
        "(R8-H binaries.vulkan_01 == binaries.vulkan_02)"
    ),
}

REFERENCE_ARM = {
    "role": "reference",
    "implementation": "NVIDIA/Vulkan local execution",
    "host": "inferswarm01",
    "gpu_uuid": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
    "bdf": "00000000:02:00.0",
    "device": "NVIDIA GeForce RTX 3060 12GiB",
    "vulkan_device_uuid": "1fc28f83-1d45-926e-54d0-ba1e835ef099",
    "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "selector": "GGML_VK_VISIBLE_DEVICES=0 (NVIDIA ICD)",
    "driver": "610.57.04",
    "non_oracle_statement": (
        "The NVIDIA/Vulkan arm is an ORDERED COMPARISON REFERENCE only. It is "
        "not an assertion of mathematical, vendor, or implementation "
        "correctness. Absolute-error numerical metrics are symmetric facts; "
        "semantic stability is evaluated under this frozen ordered "
        "relationship per the ADR-0010 strategy contract."
    ),
}
CANDIDATE_ARM = {
    "role": "candidate",
    "implementation": "AMD/Vulkan local execution",
    "host": "inferswarm02",
    "gpu_bdf": "00000000:06:00.0",
    "device": "AMD V340L selected die (RADV)",
    "vulkan_device_uuid": "00000000-0600-0000-0000-000000000000",
    "icd": "/usr/share/vulkan/icd.d/radeon_icd.json",
    "selector": "GGML_VK_VISIBLE_DEVICES=0 (radeon ICD)",
    "driver": "RADV 25.0.7",
    "single_die_authority": {
        "selected_die_bdf": "00000000:06:00.0",
        "excluded_die_bdf": "00000000:09:00.0",
        "rule": (
            "No second V340L die may participate in the candidate arm: the "
            "excluded die must show no residency delta beyond frozen noise "
            "budget counters in every retained placement record."
        ),
    },
    "no_cuda_participation": (
        "The candidate binary is the CUDA-OFF Vulkan build; CUDA must not be "
        "initialized in the qualification process tree (zero CUDA devices "
        "visible via env fencing where applicable)."
    ),
}

MATCHED_GEOMETRY = {
    "ngl": 1,
    "ctx_size": 8192,
    "batch_size": 512,
    "rpc": "none",
    "cross_die_external_memory": "none",
    "mixed_vendor_within_request": "forbidden",
    "vulkan_layers": "frozen at campaign freeze; VK_LOADER_DEBUG/disable-env exclusions recorded",
    "request_contract": {
        "cache_prompt": False,
        "n_predict": 8,
        "return_tokens": True,
        "samplers": ["top_k"],
        "seed": 0,
        "stream": False,
        "temperature": 0.0,
        "top_k": 1,
    },
    "canonical_prefix_replay": {
        "decisions_per_case": 8,
        "capture": "full-vocabulary FP32 consumer logits at every decision",
        "candidate_input_rule": (
            "every acceptance-bearing decision is evaluated on the REFERENCE "
            "canonical prefix (teacher-forced replay); a candidate's earlier "
            "divergent token never alters a later acceptance-bearing input"
        ),
        "free_running": "diagnostic only after the first allowed unstable divergence",
    },
}

# --- Layer 2 comparator families (ADR 0011 tier classification) -------------

COMPARATOR_ID = "inferswarm.qwen38-vulkan-comparator/1"

ACCEPTANCE_BEARING_FAMILIES: tuple[dict[str, str], ...] = (
    {
        "family": "fp32-consumer-logits:max-absolute-difference",
        "tier": "acceptance-bearing",
        "domain": "full vocabulary (248320) FP32 consumer-logit row per decision",
        "reducer": "max over all decisions of max_i |candidate_i - reference_i|",
        "basis": "strategy-consumed semantic-boundary output; ADR 0012 keeps it core",
    },
    {
        "family": "fp32-consumer-logits:rms-difference",
        "tier": "acceptance-bearing",
        "domain": "full vocabulary FP32 consumer-logit row per decision",
        "reducer": "max over all decisions of RMS_i(candidate - reference)",
        "basis": "strategy-consumed semantic-boundary output; ADR 0012 keeps it core",
    },
    {
        "family": "decision_local_E_D",
        "tier": "acceptance-bearing",
        "domain": "full-vocabulary decision domain D per decision (v1: D = full vocab)",
        "reducer": "E_D reducer identity (issue95 law, Qwen case constants)",
        "basis": "theorem premise of the decision-stability semantic layer",
    },
)
TELEMETRY_FAMILIES: tuple[dict[str, str], ...] = (
    {
        "family": "fp32-consumer-logits:p99-absolute-error",
        "tier": "mandatory-telemetry",
        "domain": "full vocabulary FP32 consumer-logit row per decision",
        "reducer": "nearest-rank p99 of |candidate - reference| per decision; max over decisions reported",
        "basis": "ADR 0012: p99 is retained finite-checked telemetry, not core",
    },
)

QWEN_FUTURE_USE_STATE_AUDIT: dict[str, Any] = {
    "question": (
        "Does any retained future-use/recurrent state of this exact "
        "qualification subject require an acceptance-bearing family beyond "
        "the consumer-logit rows?"
    ),
    "mechanical_answer": "NO",
    "reasoning": (
        "The qualification observation surface is the llama.cpp greedy "
        "consumer logit row at each canonical-prefix decision. The subject "
        "architecture (qwen4exp: recurrent/GDN/QSA-style blocks) carries "
        "recurrent state INSIDE execution, but the frozen observation seam "
        "(llama-server request/response with cache_prompt=false) exposes NO "
        "retained future-use state across decisions to the comparator: each "
        "canonical-prefix replay re-executes from the exact frozen prompt "
        "prefix with KV/prefix caching disabled, so no state persists between "
        "acceptance-bearing decisions that the strategy consumes later. "
        "Downstream subsumption (ADR 0011): the full-vocabulary consumer-row "
        "core families completely exercise every state-dependent numerical "
        "path on each identical canonical input, and no authoritative mutable "
        "or future-use state crosses the observation boundary. A future "
        "methodology that retains intermediate recurrent state tensors must "
        "re-audit and create a NEW comparator version."
    ),
    "audit_scope": "exact subject Qwen/Qwen3.8-Flash-Next UD-IQ1_S, llama.cpp b29c606e llama-server greedy seam",
}

# --- Layer 3 semantic profile -----------------------------------------------

SEMANTIC_PROFILE = "DECISION_STABILITY/1"
DECISION_COUNT = 8
DECISION_DOMAIN_RULE = "full-vocabulary/1"
MARGIN_RULE = "m_D = r[a] - r[b_D] under the frozen argmax/tie-break rule"
TIE_RULE = argmax_tie_break_identity()
STABILITY_RULE = (
    "m_D > 2E_D => STABLE: candidate winner must equal reference winner "
    "(exact token identity at every stable decision); "
    "m_D <= 2E_D => UNSTABLE: candidate winner may differ only within "
    "A_ED(r) = {k in D | r[a] - r[k] <= 2E_D}; after the first ALLOWED "
    "unstable free-running divergence, later free-running steps are "
    "diagnostic-only and same-input qualification continues only by "
    "canonical-prefix replay"
)
EVALUATION_ORDER = (
    "1 exact-integrity applicability (Layer 1; stops evaluation); "
    "2 decision-local numerical row bound max_{i in D}|candidate_i - "
    "reference_i| <= E_D (DECISION_LOCAL_BOUND_EXCEEDED); "
    "3 candidate winner containment in D (DECISION_DOMAIN_ESCAPE); "
    "4 stable exact-winner requirement or unstable ambiguity-set "
    "adjudication (STABLE_DECISION_MISMATCH / "
    "UNSTABLE_DECISION_INADMISSIBLE)"
)
REASON_CODES = (
    "DECISION_LOCAL_BOUND_EXCEEDED",
    "DECISION_DOMAIN_ESCAPE",
    "STABLE_DECISION_MISMATCH",
    "UNSTABLE_DECISION_INADMISSIBLE",
    "SEMANTIC_PASS",
)
NO_SUBSET_DODGE = (
    "D is the FULL VOCABULARY: the domain-escape reason is structurally "
    "available only against non-finite rows; no subset was introduced to "
    "make observed R8-H divergence pass"
)


def decision_domain_full_vocab(vocab_size: int) -> tuple[int, ...]:
    """v1 decision domain D = {0..V-1} (issue #237 preferred simplification)."""
    if vocab_size <= 0:
        raise MethodologyError("vocabulary size must be positive")
    return tuple(range(vocab_size))


def case_e_d(decision_errors: list[float]) -> float:
    """case E_D over exactly 8 Qwen canonical-prefix decisions."""
    values = [float(v) for v in decision_errors]
    if len(values) != DECISION_COUNT:
        raise MethodologyError(
            f"each case must report exactly {DECISION_COUNT} decisions"
        )
    if not all(v >= 0.0 and v == v and v != float("inf") for v in values):
        raise MethodologyError("decision-local errors must be finite and nonnegative")
    return max(values)


# --- statistical design (mechanically derived) ------------------------------

VOCAB_SIZE = 248320
ALPHA = Fraction(1, 20)          # familywise numerical failure budget 0.05
HOLDOUT_CASES = 24               # finite sealed holdout campaign size H
M = len(ACCEPTANCE_BEARING_FAMILIES)   # acceptance-bearing statistical families

ASSUMPTION_PROFILE = "MIXTURE_POPULATION_EXCHANGEABILITY"
CONSTRUCTION = "POOLED_ORDER_STATISTIC_PREDICTION"
QUALIFICATION_CLAIM = "ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE"


def derive_minimum_calibration_n(
    *, m: int = M, h: int = HOLDOUT_CASES, alpha: Fraction = ALPHA,
) -> int:
    """Solve M*H/(N+H) <= alpha for the minimum integer N mechanically."""
    if m <= 0 or h <= 0 or not (0 < alpha < 1):
        raise MethodologyError("invalid statistical design inputs")
    n = 0
    while Fraction(m * h, n + h) > alpha:
        n += 1
    return n


CALIBRATION_CASES = derive_minimum_calibration_n()
STRESS_POOL_CASES = 48           # 2 per mixture component, non-predictive
STRESS_SELECTED_CASES = 8
MIXTURE_COMPONENTS = 24          # 6 content classes x 4 length regimes


def statistical_design() -> dict[str, Any]:
    n = CALIBRATION_CASES
    per_family = Fraction(HOLDOUT_CASES, n + HOLDOUT_CASES)
    familywise = Fraction(M, 1) * per_family
    if familywise > ALPHA:
        raise MethodologyError("derived design violates the familywise budget")
    return {
        "assumption_profile": ASSUMPTION_PROFILE,
        "construction": CONSTRUCTION,
        "qualification_claim": QUALIFICATION_CLAIM,
        "probability_statement": (
            "For one frozen IID mixture-population generator, the "
            "unconditional probability that the future sealed-holdout "
            f"campaign (H={HOLDOUT_CASES} cases) observes ZERO strict "
            "exceedances across all acceptance-bearing numerical families is "
            f"at least {float(1 - familywise):.4f} (familywise budget "
            f"alpha={float(ALPHA)})"
        ),
        "mixture_components": MIXTURE_COMPONENTS,
        "calibration_cases": n,
        "holdout_cases": HOLDOUT_CASES,
        "acceptance_family_count": M,
        "alpha": float(ALPHA),
        "derivation": (
            "N >= H * (M/alpha - 1) solved mechanically from "
            "M*H/(N+H) <= alpha with M=3, H=24, alpha=1/20"
        ),
        "per_family_strict_exceedance_bound": f"{HOLDOUT_CASES}/{n + HOLDOUT_CASES}",
        "familywise_bonferroni_bound": f"{M * HOLDOUT_CASES}/{n + HOLDOUT_CASES}",
        "familywise_failure_probability": float(familywise),
        "zero_exceedance_probability_at_least": float(1 - familywise),
        "inclusive_holdout_comparison": "observed<=limit",
        "stress_cases": STRESS_POOL_CASES,
        "stress_selected_cases": STRESS_SELECTED_CASES,
        "stress_cases_contribute_predictive_sample_size": 0,
        "no_independence_assumption_between_families": (
            "Bonferroni union bound only; no cross-family independence assumed"
        ),
        "theorem": (
            "IID frozen mixture-population exchangeability; a calibration "
            "maximum over N draws has strict-exceedance probability at most "
            "H/(N+H) for H future exchangeable draws from the same mixture"
        ),
    }


# --- fresh Qwen target generator (frozen IID mixture law) -------------------

# Qwen-specific content classes: same six CLASS SEMANTICS as the accepted v5
# construction (they name input regimes, not Gemma authority), with a FRESH
# Qwen lexeme pool drawn from ordinary English + code + math + multilingual +
# repetitive + punctuation/whitespace regimes.
CONTENT_CLASSES: tuple[str, ...] = (
    "ordinary-prose",
    "source-code-structured-syntax",
    "mathematics-numerals",
    "multilingual-text",
    "repetitive-low-entropy",
    "punctuation-whitespace-rare-high-entropy",
)

# Context/input regimes relevant to the intended Qwen heterogeneous-Vulkan
# strategy (R8-H matched geometry, ctx 8192): four length regimes DERIVED
# from the accepted R8-B fixture-ladder target_band fields (250-264 /
# 1018-1032 / 3066-3080 / 4090-4104) — the context regimes where R8
# demonstrated Qwen's length-sensitive numerical behavior. The Gemma
# qualification bands (4-8/24-28/36-40/52-56) found in the first freeze did
# not exercise those regimes and are superseded.
LENGTH_REGIMES: tuple[tuple[int, int], ...] = derive_length_regimes()
validate_frozen_bands(LENGTH_REGIMES)

LEXEMES: dict[str, tuple[str, ...]] = {
    "ordinary-prose": (
        "harbor", "lantern", "quiet", "drifts", "north", "meadow", "gentle",
        "ridge", "atoll", "answers", "kind", "beacon", "evening", "near",
        "open", "trail", "still", "current", "granite", "wanders", "under",
        "basin", "breeze", "younger", "cedar", "marsh", "signal", "tide",
    ),
    "source-code-structured-syntax": (
        "async", "await", "match", "guard", "enum", "struct", "impl", "trait",
        "value", "item", "queue", "true", "false", "none", "(", ")", "[", "]",
        "{", "}", ":", ";", ",", "=", "->", "=>", "+", "-", "*", "_buf",
        "yield", "break", "loop", "where", "self", "pub", "use", "mod",
    ),
    "mathematics-numerals": (
        "1", "1", "2", "3", "5", "7", "11", "18", "29", "47", "u", "v", "w",
        "+", "-", "*", "=", "<", ">", "(", ")", "sum", "mean", "ratio",
        "squared", "half", "third", "prime", "vector", "matrix", "epsilon",
    ),
    "multilingual-text": (
        "guten", "Morgen", "Welt", "bonjour", "monde", "merci", "hola",
        "mundo", "gracias", "ciao", "mondo", "grazie", "olá", "obrigado",
        "hej", "värld", "tack", "namaste", "duniya", "shukriya", "こんにちは",
        "世界", "ありがとう", "안녕", "세계", "감사", "مرحبا", "العالم", "شكرا",
        "привет", "мир", "спасибо",
    ),
    "repetitive-low-entropy": (
        "da", "da", "da", "la", "la", "na", "na", "hum", "hum", "again",
        "again", "tick", "tock", "null", "null", "same", "same", "loop",
        "loop", "echo",
    ),
    "punctuation-whitespace-rare-high-entropy": (
        "!", "?", "#", "$", "%", "&", "*", "+", "-", "/", ":", ";", "<", "=",
        ">", "@", "[", "]", "^", "_", "{", "|", "}", "~", "§", "¶", "※", "◇",
        "Ж", "λ", "猫", "Ω", "f0", "c7", "0b", "::", "//", "\\n",
    ),
}

CALIBRATION_SEED = "inferswarm-issue-237-qwen38-vulkan-calibration-v2-r8bands"
STRESS_POOL_SEED = "inferswarm-issue-237-qwen38-vulkan-stress-v2-r8bands"
HOLDOUT_NAMESPACE = "qwen38-vulkan-v1-sealed-holdout"

# Holdout lifecycle and custody are TWO INDEPENDENT axes (issue #237
# correction): the lifecycle state never encodes custody completeness.
# - HOLDOUT_STATE_LIFECYCLE: sealed / not decrypted / not consumed / still
#   the single-use future holdout;
# - custody_status: whether the required independently verified custodian
#   copies of the recipient key + secret seed exist yet.
HOLDOUT_STATE_LIFECYCLE = "SEALED_NOT_CONSUMED"
CUSTODY_STATUS_INCOMPLETE = "INCOMPLETE"
CUSTODY_STATUS_COMPLETE = "COMPLETE"
REQUIRED_VERIFIED_CUSTODIANS = 2

CALIBRATION_SCHEMA = "inferswarm.issue237.calibration-corpus/1"
STRESS_POOL_SCHEMA = "inferswarm.issue237.stress-pool/1"
HOLDOUT_PLAINTEXT_SCHEMA = "inferswarm.issue237.holdout/1"
HOLDOUT_COMMITMENT_SCHEMA = "inferswarm.issue237.holdout-commitment/1"
HOLDOUT_CUSTODY_SCHEMA = "inferswarm.issue237.holdout-custody-record/1"
MIXTURE_SCHEMA = "inferswarm.issue237.mixture-population/1"
TOKENIZER_ASSET_PATH = "docs/qualification/qwen38-vulkan-v1/assets/tokenizer.json"
TOKENIZER_JSON_SHA256 = (
    "8de1d3858667c32441d4a7c5a8f89f43ae3210c5eb6d12d48c8a83569e3d9af7"
)


def mixture_components() -> tuple[tuple[str, int], ...]:
    """The frozen 24 (content_class, length_regime_index) components."""
    return tuple(
        (content_class, regime_index)
        for content_class in CONTENT_CLASSES
        for regime_index in range(len(LENGTH_REGIMES))
    )


def component_stream(
    seed: str, namespace: str, count: int,
    *, component_count: int = MIXTURE_COMPONENTS,
) -> Iterator[tuple[int, tuple[str, int]]]:
    """Yield ``count`` IID (draw_index, component) pairs.

    Precommitted SHA-256-seeded selection keyed ONLY on
    (seed, namespace, 'mixture-component', draw_index): frozen before any
    case content exists, independent of every other draw.
    """
    if count < 0:
        raise MethodologyError("mixture draw count must be nonnegative")
    components = mixture_components()
    if len(components) != component_count:
        raise MethodologyError("mixture component universe size mismatch")
    for index in range(count):
        material = "\0".join(
            (seed, namespace, "mixture-component", str(index))
        ).encode()
        rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
        yield index, components[rng.randrange(len(components))]


def target_length(seed: str, namespace: str, regime_index: int, draw_index: int) -> int:
    """One IID uniform target length for a frozen mixture draw."""
    if not 0 <= regime_index < len(LENGTH_REGIMES) or draw_index < 0:
        raise MethodologyError("invalid target-length draw inputs")
    low, high = LENGTH_REGIMES[regime_index]
    material = "\0".join(
        (seed, namespace, "target-length", str(regime_index), str(draw_index))
    ).encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))
    return rng.randint(low, high)


def mixture_population_declaration() -> dict[str, Any]:
    return {
        "schema": MIXTURE_SCHEMA,
        "contract_id": CONTRACT_ID,
        "assumption_profile": ASSUMPTION_PROFILE,
        "components": [
            {
                "content_class": content_class,
                "length_regime": list(LENGTH_REGIMES[regime_index]),
            }
            for content_class, regime_index in mixture_components()
        ],
        "component_count": MIXTURE_COMPONENTS,
        "component_weights": f"uniform 1/{MIXTURE_COMPONENTS} per component",
        "component_selection_rule": (
            "for draw index i, component = components[SHA256(seed \\0 namespace "
            "\\0 'mixture-component' \\0 i)-seeded Random.randrange(24)]; frozen "
            "before any case content is generated"
        ),
        "target_length_selection_rule": (
            "for draw index i and selected regime r, length = SHA256(seed \\0 "
            "namespace \\0 'target-length' \\0 r \\0 i)-seeded "
            "Random.randint(low, high); uniform inclusive"
        ),
        "historical_exclusion_conditional_law": (
            "For each draw index, select one component uniformly (1/24) and "
            "one target length uniformly in its regime; freeze both values. "
            "Generate a prompt realization. If its prompt/token identity is "
            "in the fixed historical exclusion inventory, increment a "
            "case-local attempt nonce and regenerate ONLY the prompt "
            "realization. Never redraw the component or target length. "
            "Retain the accepted realization at the original draw index. "
            "No quota balancing. Realized component counts are observations."
        ),
        "draws_are_iid": True,
        "calibration_and_holdout_share_generator": True,
        "calibration_namespace": "calibration",
        "holdout_namespace": HOLDOUT_NAMESPACE,
        "tokenizer": {
            "path": TOKENIZER_ASSET_PATH,
            "sha256": TOKENIZER_JSON_SHA256,
            "provenance": (
                "reconstructed from the accepted GGUF member-1 header bytes "
                "(scripts/issue237_reconstruct_tokenizer.py); validated "
                "against all four accepted R8-B fixture-ladder tokenizations"
            ),
        },
        "length_regime_authority": length_regimes_provenance(),
        "note": (
            "Calibration uses the public seed; the holdout uses an "
            "independent secret seed. Both arms use THIS identical generator "
            "law, so calibration and holdout cases are IID draws from one "
            "frozen mixture population (issue #108 Q2). The four predictive "
            "length regimes are mechanically derived from the accepted R8-B "
            "fixture-ladder target_band fields (the context regimes where "
            "R8 demonstrated Qwen's length-sensitive numerical behavior); "
            "historical R8 256/1024/3072/4096 prompt/token identities "
            "informed regime design only and are excluded from fresh "
            "predictive material by the hash-bound inventory."
        ),
    }


def realized_component_counts(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Observational component counts from realized draws (never quotas)."""
    counts: dict[tuple[str, int], int] = {}
    for case in cases:
        key = (case["content_class"], case["length_regime_index"])
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "content_class": content_class,
            "length_regime_index": regime_index,
            "observed": counts.get((content_class, regime_index), 0),
        }
        for content_class, regime_index in mixture_components()
    ]


def physical_subject_contract() -> dict[str, Any]:
    return {
        "schema": "inferswarm.issue237.subject/1",
        "model": QWEN_MODEL,
        "official_revision": QWEN_OFFICIAL_REVISION,
        "unsloth_conversion": {
            "repo": UNSLOTH_REPO,
            "revision": UNSLOTH_REVISION,
            "representation": REPRESENTATION,
            "members": [dict(m) for m in GGUF_MEMBERS],
            "total_bytes": GGUF_TOTAL_BYTES,
            "forbidden": (
                "no conversion, requantization, split merge, or alternate "
                "representation"
            ),
        },
        "runtime": {
            "llama_cpp_source_pin": LLAMA_CPP_PIN,
            "vulkan_binary_sha256": LLAMA_VULKAN_BINARY_SHA256,
            "build": dict(LLAMA_VULKAN_BUILD),
            "backend": "vulkan only for this qualification relation",
            "cuda_reference_forbidden": (
                "CUDA is not the numerical reference for this first "
                "heterogeneous-Vulkan contract"
            ),
        },
        "reference_arm": dict(REFERENCE_ARM),
        "candidate_arm": dict(CANDIDATE_ARM),
        "geometry": dict(MATCHED_GEOMETRY),
        "decision_count": DECISION_COUNT,
        "evaluation_order": EVALUATION_ORDER,
        "reason_codes": list(REASON_CODES),
        "predecessor": {
            "r8h_merge": R8H_MERGE_SHA,
            "r8h_reviewed_head": R8H_REVIEWED_HEAD,
            "r8h_terminal": R8H_TERMINAL,
            "r8h_eligibility": (
                "R8-H is design/diagnostic evidence ONLY, permanently "
                "ineligible as calibration or holdout evidence for this "
                "contract; R8-G accepted non-monotonic diagnostic is "
                "historical context only"
            ),
        },
    }


def layer1_integrity_contract() -> dict[str, Any]:
    return {
        "schema": "inferswarm.issue237.layer1-integrity/1",
        "contract_id": CONTRACT_ID,
        "never_toleranced": [
            "model/revision/conversion/member hashes (3 GGUF sha256)",
            "runtime source/build/package identity (pin + binary sha256)",
            "reference/candidate device and backend identity (UUID/BDF/ICD/driver)",
            "strategy/comparator identity",
            "prompt/token IDs (exact)",
            "canonical-prefix identity",
            "request/sampler/seed/context/batch/geometry",
            "shape and frozen semantic dtype (FP32 consumer rows)",
            "execution-plan/role attribution where applicable",
            "backend/device/path attribution",
            "process/session/position attribution",
            "materialization/state ownership",
            "sender/receiver bytes for any transport boundary",
            "no silent fallback/substitution",
            "no hidden CUDA participation in the Vulkan subject",
            "no second-V340L-die participation where single-die authority applies",
        ],
        "failure_semantics": (
            "A Layer-1 mismatch stops evaluation BEFORE numerical/semantic "
            "adjudication; no floating-point tolerance can excuse it"
        ),
        "fail_closed_reason": "LAYER1_EXACT_INTEGRITY_FAILURE",
    }


def comparator_contract() -> dict[str, Any]:
    return {
        "schema": "inferswarm.issue237.comparator/1",
        "comparator_id": COMPARATOR_ID,
        "acceptance_bearing": [dict(f) for f in ACCEPTANCE_BEARING_FAMILIES],
        "mandatory_telemetry": [dict(f) for f in TELEMETRY_FAMILIES],
        "future_use_state_audit": dict(QWEN_FUTURE_USE_STATE_AUDIT),
        "no_universal_epsilon": (
            "every numerical limit is derived prospectively by the frozen "
            "threshold algorithm from complete calibration evidence; none is "
            "copied from Gemma, R6, R8-H, or ad hoc judgment"
        ),
        "semantic_profile": {
            "profile": SEMANTIC_PROFILE,
            "decision_domain_rule": DECISION_DOMAIN_RULE,
            "domain_construction": (
                "D = full vocabulary {0..248319}; decision_domain_full_vocab()"
            ),
            "tie_rule": TIE_RULE,
            "stability_rule": STABILITY_RULE,
            "margin_rule": MARGIN_RULE,
            "evaluation_order": EVALUATION_ORDER,
            "reason_codes": list(REASON_CODES),
            "exact_tokens_still_required": (
                "exact token equality remains required at every STABLE "
                "decision under the theorem; divergence is never globally "
                "reinterpreted as harmless"
            ),
            "no_subset_dodge": NO_SUBSET_DODGE,
        },
        "e_d_reducer": e_d_reducer_identity().replace("1896", "N-calibration").replace("8 selected", "selected"),
        "decision_local_error_identity": decision_local_error_identity(),
    }


__all__ = [
    "ACCEPTANCE_BEARING_FAMILIES",
    "ALPHA",
    "ASSUMPTION_PROFILE",
    "CALIBRATION_CASES",
    "CALIBRATION_SCHEMA",
    "CALIBRATION_SEED",
    "COMPARATOR_ID",
    "CONTRACT_ID",
    "CONTENT_CLASSES",
    "CONSTRUCTION",
    "CUSTODY_STATUS_COMPLETE",
    "CUSTODY_STATUS_INCOMPLETE",
    "HOLDOUT_STATE_LIFECYCLE",
    "REQUIRED_VERIFIED_CUSTODIANS",
    "DECISION_COUNT",
    "HOLDOUT_CASES",
    "HOLDOUT_COMMITMENT_SCHEMA",
    "HOLDOUT_CUSTODY_SCHEMA",
    "HOLDOUT_NAMESPACE",
    "HOLDOUT_PLAINTEXT_SCHEMA",
    "LENGTH_REGIMES",
    "derive_length_regimes",
    "length_regimes_provenance",
    "validate_frozen_bands",
    "LEXEMES",
    "M",
    "MIXTURE_COMPONENTS",
    "MIXTURE_SCHEMA",
    "QWEN_FUTURE_USE_STATE_AUDIT",
    "QUALIFICATION_CLAIM",
    "STRESS_POOL_CASES",
    "STRESS_POOL_SCHEMA",
    "STRESS_POOL_SEED",
    "STRESS_SELECTED_CASES",
    "TELEMETRY_FAMILIES",
    "TOKENIZER_ASSET_PATH",
    "TOKENIZER_JSON_SHA256",
    "VOCAB_SIZE",
    "ambiguity_set",
    "argmax_tie_break_identity",
    "case_e_d",
    "comparator_contract",
    "component_stream",
    "decision_domain_full_vocab",
    "decision_local_error",
    "frozen_argmax",
    "layer1_integrity_contract",
    "mixture_components",
    "mixture_population_declaration",
    "physical_subject_contract",
    "realized_component_counts",
    "statistical_design",
    "target_length",
]
