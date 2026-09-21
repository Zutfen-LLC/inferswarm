# Qwen3.8-Flash-Next heterogeneous-Vulkan numerical qualification methodology v1 (issue #237)

Status: **prospective CPU/static methodology freeze — NO PHYSICAL EXECUTION.**

No SSH to execution nodes, no CUDA/Vulkan device initialization, no model
checkpoint execution, no physical calibration observations, no numerical
limits derived from R8-H observations, no holdout decrypt, no mixed-vendor
inference, and no physical successor created in this issue.

Terminal disposition on maintainer acceptance:

`R8I_QWEN38_HETEROGENEOUS_VULKAN_METHODOLOGY_FROZEN`

## 1. Why this freeze exists

R8-H (#234 / PR #235, merged `dda4e8f...`, reviewed head `8438d88f...`,
terminal `R8H_QWEN38_MULTI_AXIS_DIVERGENCE_CHARACTERIZED`) proved that the
exact same RTX 3060 under CUDA vs Vulkan — and NVIDIA/Vulkan vs AMD/Vulkan —
can produce different deterministic token/logit results while every
execution identity remains trustworthy. That is not a new correctness
doctrine: ADR 0010 already rejects universal cross-device/backend bit
identity while preserving exact state/transport/authority invariants.

The R8 question this methodology answers is:

> What prospectively frozen ADR-0010 numerical + semantic qualification
> contract must Qwen3.8 UD-IQ1_S satisfy before NVIDIA/Vulkan and AMD/Vulkan
> may both be treated as correctness-qualified execution resources for a
> backend-coherent heterogeneous Vulkan plan?

R8-H is design/diagnostic evidence only, permanently ineligible as
calibration or holdout evidence for this contract. R8-G's accepted
non-monotonic diagnostic result is historical diagnostic context only.

## 2. Frozen subject

Model: `Qwen/Qwen3.8-Flash-Next` @ `de4b8e4d43b917e7706784d8bb445c9af86a3540`,
converted by `unsloth/Qwen3.8-Flash-Next-GGUF` @
`38bb39ee97821de2c9009abb7e93950eec396e66`, representation UD-IQ1_S, exactly
the three accepted R8-A/R8-H members (72,546,461,344 bytes, per-member
sha256 in the manifest). No conversion, requantization, split merge, or
alternate representation.

Runtime: llama.cpp source pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`,
Vulkan build `21707f2568d80fb7...` (GGML_CUDA=OFF, baseline CPU intrinsics)
— the exact R8-H B/C binary bytes. Vulkan only for this qualification
relation; CUDA is NOT the numerical reference. Future methodology needing a
new diagnostic build must remain exact-source-pin-derived and
prospectively hash-frozen before physical calibration.

Reference/candidate relationship (ordered, non-oracle):

- reference: NVIDIA/Vulkan on inferswarm01 RTX 3060
  `GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099` @ `00000000:02:00.0` (NVIDIA ICD);
- candidate: AMD/Vulkan on inferswarm02 V340L selected die `00000000:06:00.0`
  (radeon ICD, RADV 25.0.7), second die `00000000:09:00.0` EXCLUDED by
  single-die authority.

The NVIDIA/Vulkan arm is an ordered comparison reference, not an assertion
of mathematical or vendor correctness. Absolute-error metrics are symmetric
facts; semantic stability is evaluated under the frozen ordered reference
relationship required by the ADR-0010 strategy contract.

Initial geometry: the accepted R8-H matched local Vulkan geometry — ngl=1,
ctx-size 8192, batch-size 512, greedy request contract (temperature 0,
top_k 1, seed 0, n_predict 8, cache_prompt false), no RPC, one V340L die,
no cross-die external memory, no mixed-vendor execution inside one request.

## 3. Backend-coherence posture (Model Execution Strategy constraint)

1. Homogeneous NVIDIA plans may use CUDA when the exact CUDA subject has
   applicable correctness qualification.
2. Mixed-vendor GPU plans use one common backend substrate by default;
   Vulkan is the current proving substrate.
3. CUDA+Vulkan inside one execution request is not a default plan shape;
   it requires a separately justified future use case and qualification.
4. This is a strategy/applicability constraint. The generic planner still
   consumes backend capabilities, strategy constraints, and applicable
   qualification evidence without hard-coded CUDA/Vulkan/NVIDIA/AMD or
   model-name policy; "prefer backend coherence" is not an ontology claim
   that a plan can never contain multiple backends.

## 4. Layer 1 — exact integrity

Never toleranced (full list in `manifests/` Layer-1 contract block):
model/revision/conversion/member hashes; runtime source/build/package
identity; reference/candidate device+backend identity; strategy/comparator
identity; prompt/token IDs; canonical-prefix identity;
request/sampler/seed/context/batch/geometry; shape and frozen semantic
dtype; execution-plan/role attribution; backend/device/path attribution;
process/session/position attribution; materialization/state ownership;
sender/receiver bytes for any transport boundary; no silent
fallback/substitution; no hidden CUDA participation; no second-V340L-die
participation. A Layer-1 failure stops evaluation before numerical or
semantic adjudication.

## 5. Layer 2 — qualified numerical execution equivalence

Comparator `inferswarm.qwen38-vulkan-comparator/1`:

Acceptance-bearing families (3):
1. `fp32-consumer-logits:max-absolute-difference` (full vocabulary FP32);
2. `fp32-consumer-logits:rms-difference` (full vocabulary FP32);
3. `decision_local_E_D` (the semantic-profile theorem premise).

Mandatory telemetry: `fp32-consumer-logits:p99-absolute-error`
(ADR 0012 classification; finite-checked, retained, report-only).

Future-use-state audit (mechanical, documented before corpus freeze): the
llama-server greedy observation seam with `cache_prompt=false` exposes NO
retained future-use state across decisions to the comparator — every
canonical-prefix replay re-executes from the exact frozen prompt prefix,
and the full-vocabulary consumer-row core families completely exercise all
state-dependent numerical paths on each identical canonical input
(ADR 0011 downstream subsumption). Answer: NO additional acceptance-bearing
state family for this exact subject. A future methodology that retains
intermediate recurrent state tensors must re-audit and create a NEW
comparator version.

No universal epsilon: every limit is derived prospectively by the frozen
threshold algorithm from complete calibration evidence; nothing is copied
from Gemma, R6, R8-H, or ad hoc judgment.

## 6. Layer 3 — decision-stability semantic contract

Profile `DECISION_STABILITY/1` (not strict universal exact-token):

- deterministic canonical-prefix replay; 8 consumer decisions per case;
- ordered reference; decision domain D = FULL VOCABULARY {0..248319}
  (v1 simplification — no subset introduced to make observed R8-H
  divergence pass, so zero-domain-escape is structurally provable);
- E_D derivation/application per the frozen reducer law;
- argmax/tie-break: `ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima`;
- evaluation order: exact-integrity → decision-local bound → containment →
  stability/ambiguity adjudication (fail-closed reason codes
  `DECISION_LOCAL_BOUND_EXCEEDED`, `DECISION_DOMAIN_ESCAPE`,
  `STABLE_DECISION_MISMATCH`, `UNSTABLE_DECISION_INADMISSIBLE`,
  `SEMANTIC_PASS`);
- if reference margin m_D > 2E_D the candidate winner must equal the
  reference winner: exact token equality remains required at every STABLE
  decision; if m_D <= 2E_D the candidate winner may differ only within the
  theorem-defined ambiguity set; after the first ALLOWED unstable
  free-running divergence, later free-running steps are diagnostic-only and
  same-input qualification continues only by canonical-prefix replay.
- every acceptance-bearing candidate decision is teacher-forced on the
  REFERENCE canonical prefix: a candidate's earlier divergent token never
  alters a later acceptance-bearing input.

## 7. Statistical design (ADR 0012)

- assumption profile: `MIXTURE_POPULATION_EXCHANGEABILITY`;
- construction: `POOLED_ORDER_STATISTIC_PREDICTION`;
- claim: `ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE`;
- alpha = 0.05 familywise; H = 24 finite sealed-holdout cases; zero strict
  exceedances across all M=3 acceptance-bearing families on the future
  holdout campaign;
- calibration N derived mechanically: `N >= H*(M/alpha - 1)` => N >= 24*59
  => **N = 1416** (per-family bound 24/1440; familywise Bonferroni bound
  72/1440 = 0.05; zero-exceedance probability >= 0.95). No
  cross-family independence assumed (union bound only).

## 8. Target generator (fresh, Qwen-specific)

Frozen 24-component IID mixture: six content classes (ordinary prose,
source-code syntax, mathematics/numerals, multilingual, repetitive
low-entropy, punctuation/whitespace rare/high-entropy) x four length
regimes (4–8, 24–28, 36–40, 52–56 tokens), uniform 1/24 weights,
SHA-256-seeded per-draw component + target-length selection frozen before
any content exists. Prompts are rendered from a fresh Qwen lexeme pool and
tokenized with the pinned Qwen tokenizer (reconstructed from the accepted
GGUF member-1 header bytes and validated against all four accepted R8-B
fixture-ladder tokenizations — `scripts/issue237_reconstruct_tokenizer.py`,
tokenizer sha256 `8de1d385...`). One frozen IID mixture law generates BOTH
calibration and holdout. Realized component counts are observations, not
quotas. R8's historical 256/1024/3072/4096 fixtures informed regime design
only; their identities (and every extractable R8-A..H + consumed Gemma
qualification identity — 2888 distinct sha256) are excluded by the
hash-bound inventory with the conditional-rejection law (regenerate only
the prompt realization; never redraw the component/length).

- Calibration: **1416** IID draws (`c237-*`), public seed.
- Fresh sealed holdout: **24** IID draws (`h237-*`), independent secret seed.
- Non-predictive stress pool: **48** cases (`p237-*`, 2 per component),
  reference-input-only selection (margin-based, frozen before any candidate
  output exists), zero predictive sample count.

## 9. Sealed holdout and custody

Single-use holdout CMS-sealed (AES-256-CBC to a fresh RSA-3072 recipient)
BEFORE physical calibration: ciphertext `sealed/holdout.cms`
(sha256 `f90806c5...`), public certificate, public per-draw identity
commitment (case id, component, token count, prompt/token-IDs hashes — no
plaintext), custody record with NO private material in Git. State:
`SEALED_CUSTODY_INCOMPLETE` (one verified local custodian; fail-closed
until a second independent custodian copy is established — the unseal
preflight refuses otherwise). No decrypt occurred in this issue
(structural CMS checks only). The future campaign may open it only after
complete valid calibration evidence, mechanically derived limits, frozen
threshold/contract artifacts, and maintainer authorization
(`scripts/issue237_unseal_preflight.py` stops at the decision boundary).

## 10. Corpus / semantic replay profile

Same fixed 8 consumer decisions per case throughout calibration and
holdout; exact reference prefix retained per decision; candidate
teacher-forced canonical replay on those exact prefixes; full-vocabulary
FP32 consumer-logit capture at every acceptance-bearing decision;
finite-output checks; reference top1/top2 margin retained; candidate
emitted winner retained; free-running continuation retained as diagnostic
only. Schemas and fail-closed validators for the future physical
reference/candidate observations: `schemas/` +
`scripts/issue237_schemas.py`.

## 11. Tooling (deterministic, fail-closed, CPU/static)

- `scripts/issue237_methodology.py` — the frozen methodology contract;
- `scripts/issue237_reconstruct_tokenizer.py` — GGUF-header→tokenizer.json
  reconstruction + fixture validation;
- `scripts/issue237_build_exclusion_inventory.py` — hash-bound historical
  exclusion inventory (derives every hash from accepted bytes);
- `scripts/issue237_generate_corpora.py` — IID mixture corpus generator;
- `scripts/issue237_seal_holdout.py` — CMS sealing + public commitment +
  custody (never commits plaintext/private key);
- `scripts/issue237_thresholds.py` — frozen threshold/band derivation
  algorithm (max over complete calibration evidence; hex-float; no manual
  editing representable);
- `scripts/issue237_semantic_adjudication.py` — frozen decision-stability
  gate application;
- `scripts/issue237_unseal_preflight.py` — stops before decrypt;
- `scripts/issue237_freeze_tooling.py` — prerequisite/methodology/corpus/
  holdout validation + freeze report.

## 12. Future gates (NOT authorized by this freeze)

The separately reviewed physical R8 successor campaign may: run the
NVIDIA/Vulkan vs AMD/Vulkan calibration under THIS exact methodology →
derive + freeze thresholds → complete custody → maintainer-authorized
unseal → holdout qualification. No post-holdout tuning. Completion of R8-I
does not authorize physical calibration until the maintainer accepts this
terminal.

## 13. Explicit non-claims

This freeze does not qualify NVIDIA/Vulkan or AMD/Vulkan; does not declare
existing R8-H token differences acceptable; does not establish a universal
Qwen or Vulkan epsilon; does not reinterpret R8-H; does not make CUDA
invalid; does not require Vulkan for homogeneous NVIDIA operation; does not
qualify Vulkan RPC, mixed-vendor execution inside one request, or dual-die
V340L execution; does not establish production Qwen support; does not
change generic planner ontology/policy; runs no performance benchmarks;
does not open the holdout.
