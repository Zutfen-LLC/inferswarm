# Gemma v4 prediction-aligned two-tier methodology (issue #95)

Status: prospective CPU/static methodology freeze. No CUDA/Triton/model execution, physical calibration, threshold derivation from physical evidence, or holdout decryption occurred.

Terminal disposition on maintainer acceptance:

`GEMMA_V4_PREDICTION_ALIGNED_METHODOLOGY_FROZEN`

## Subject and preservation

The physical subject is unchanged: `google/gemma-4-12B-it` revision `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`, checkpoint `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`, native BF16, Triton attention, deterministic eight-decision greedy replay-prefill, one <=64-row replay chunk, later RTX 3090 reference and accepted three-stage RTX 3060 candidate chain. A static dependency change stops the successor campaign for adjudication.

Historical #65, #76, #81, #88, #90 and #93 records are immutable. Consumed `h86-*` observations are permanently diagnostic-only and cannot become v4 inputs. Strict exact-token/bit-exact profiles remain stronger, separate profiles.

## Two tiers

`manifests/comparator-tier-contract.json` is mechanically derived from accepted #93 classification. It binds exactly three FP32 consumer-logit numerical pairs as acceptance-bearing and all twelve internal pairs as mandatory telemetry. `E_D` is the fourth acceptance-bearing statistical scalar family: a case value is the maximum of all eight canonical-prefix decision-local errors.

Core limits and telemetry reference bands are distinct schema concepts even though both future reducers are `max(statistical_max, selected_stress_max)`. Any valid core exceedance fails. A finite telemetry band exceedance is retained as `TELEMETRY_ALERT`, not a qualification failure. NaN/Inf at a finite-required core or telemetry identity fails unconditionally.

## Prediction-aligned statistical contract

The frozen public calibration corpus has 24 balanced cells × 79 independent cases = 1896 cases. A future sealed holdout has one independent case in each of the same 24 cells. For each core scalar family, the global calibration maximum is the inclusive limit (`observed <= limit`). Under within-cell exchangeability, a strict new record among holdout cells is at most `1/(79+1)=1/80`. Four core families yield the Bonferroni bound `4/80=5%`; therefore the same zero-of-24 core-exceedance rule has at least 95% prospective probability.

The fresh 48-case stress pool is selection-biased: after reference-only margins, select four smallest finite nonnegative margins and four largest, tie-breaking by case ID. It contributes zero observations to predictive sample size. Its maxima only make limits more conservative.

## Canonical-prefix semantic gate

Reference produces the canonical trajectory. Candidate is teacher-forced on each reference prefix. The decision domain is `reference-top-1024-with-cutoff-ties/1`; argmax is `ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima`. Evaluate `decision_local_error <= E_D`, then actual-winner containment, then stable exact-winner or unstable ambiguity-set membership. `DECISION_LOCAL_BOUND_EXCEEDED` and `DECISION_DOMAIN_ESCAPE` fail closed. Post-branch free-running tensors are diagnostic only.

## Future gates

A later separately authorized physical campaign may derive the core threshold manifest and telemetry-band manifest only from complete calibration and selected-stress evidence, commit/push/refetch them, then run the non-decrypting unseal preflight. It may unseal only by explicit maintainer action. No post-holdout tuning is permitted.
