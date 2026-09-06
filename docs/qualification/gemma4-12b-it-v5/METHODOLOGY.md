# Gemma v5 mixture-population methodology (issue #109)

Status: prospective CPU/static methodology freeze. No CUDA/Triton/model execution, physical calibration, threshold derivation from physical evidence, or holdout decryption occurred.

Terminal disposition on maintainer acceptance:

`GEMMA_V5_CORRECTED_QUALIFICATION_METHODOLOGY_FROZEN`

## Subject and preservation

The physical subject is unchanged. It is `google/gemma-4-12B-it` at revision `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`. The checkpoint SHA-256 is `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`. It uses native BF16 text execution and Triton attention. It uses one <=64-row replay chunk. The reference path uses one RTX 3090. The candidate path uses the accepted three-stage RTX 3060 chain. `manifests/physical-subject.json` freezes this identity, the eight decisions, the evaluation order, and the fail-closed reason codes. Historical `#88`, `#90`, `#93`, `#97`, `#105`, and `#108` records are immutable. Consumed `h74-*`, `h86-*`, and `h95-*` observations are permanently diagnostic-only and cannot become v5 inputs.

## What this freeze instantiates

ADR 0012 and issue #108 accepted a doctrine (`docs/qualification/post-v4-statistical-metric-doctrine/`) that named permitted statistical construction classes and their compatibility constraints but explicitly selected none of them (`NO_V5_PARAMETER_SELECTION`). This issue makes that prospective selection:

- **Assumption profile:** `MIXTURE_POPULATION_EXCHANGEABILITY`.
- **Construction:** `POOLED_ORDER_STATISTIC_PREDICTION`.
- **Qualification claim:** `ZERO_EXCEEDANCE_CAMPAIGN_MIXTURE`.

`scripts/issue109_v5_methodology_freeze.py` validates this selection directly against the unchanged, accepted `docs/qualification/post-v4-statistical-metric-doctrine/statistical-contract.json` by calling `issue108_post_v4_statistical_metric_doctrine.validate_prospective_methodology`, rather than a locally redefined copy of the #108 doctrine.

## Mixture-population design

The v1/v3/v4 design used fixed balanced cells. Issue #105/#108 found that design does not support a pooled cross-cell probability statement. The v5 target is a frozen 24-component mixture. Each component is one `(content_class, length_regime)` pair. Each component has weight `1/24`. The component and target length use SHA-256-seeded case-local draws. The target length is uniform over the inclusive selected regime. Calibration uses a public seed. Holdout uses an independent secret seed. Both arms use the same generator and weights. This establishes joint exchangeability under issue #108 Q2. A shared fixed cell count does not establish it.

- Calibration: **1416** IID mixture draws (`c109-*`).
- Fresh sealed holdout: **24** IID mixture draws (`h109-*`), one future campaign.
- Reference-only stress pool: **48** cases (`p109-*`, 2 per component, unchanged deterministic construction — stress cases contribute zero predictive sample size).

For `N=1416` calibration cases and `H=24` future holdout cases, a calibration maximum has strict-exceedance probability at most `H/(N+H) = 24/1440 = 1/60` under mixture exchangeability (`statistical-derivation.json`). There are three acceptance-bearing scalar families under the accepted #108 metric-core doctrine (`fp32-consumer-logits:max-absolute-difference`, `fp32-consumer-logits:rms-difference`, `decision_local_E_D`); the Bonferroni familywise bound is `3 * 1/60 = 1/20 = 5%`, so the same zero-of-3-families core-exceedance rule has at least 95% prospective probability — the same confidence level as v4, achieved through a doctrine-compliant mixture claim instead of the invalid pooled-under-within-cell-only construction #105 diagnosed.

## Two tiers (accepted #108 metric-core doctrine)

`manifests/comparator-tier-contract.json` (`scripts/issue109_v5_contract.py`) mechanically merges the accepted #108 `fp32-consumer-logits`/`decision_local_E_D` reclassification with the twelve internal-family identities whose tier is unchanged since #93: `fp32-consumer-logits:max-absolute-difference` and `fp32-consumer-logits:rms-difference` remain acceptance-bearing; `fp32-consumer-logits:p99-absolute-error` moves to mandatory telemetry (13 telemetry identities total). `decision_local_E_D` remains the semantic acceptance-bearing family. All eight canonical-prefix decisions remain required for every acceptance-bearing metric (`capture_position_rule` unchanged from #108).

## Canonical-prefix semantic gate (unchanged from v4)

ADR 0012 revises only the statistical construction and metric tiers, not the semantic gate: `scripts/issue109_v5_methodology.py` re-exports the frozen v4 decision-domain construction (`reference-top-1024-with-cutoff-ties/1`), argmax/tie-break rule (`ARGMAX_FIRST_MAX/lowest-token-id-among-exactly-equal-fp32-maxima`), and `E_D` reducer unchanged and byte-identical from `issue95_v4_methodology.py`.

## Sealed holdout and custody

The fresh 24-case holdout was generated once from an independently random secret seed, immediately CMS-sealed (AES-256-CBC, RSA-3072 recipient, `-binary` byte-exact round-trip verified), and the plaintext was discarded; it is not and has never been a repository artifact (`manifests/sealed-holdout-commitment.json`).

**Custody is incomplete.** Only one verified local custodian copy of the recipient private key and secret seed currently exists (`manifests/holdout-custody-record.json`, `holdout_state: SEALED_CUSTODY_INCOMPLETE`, `unseal_authorized: false`). This is an honest, fail-closed state, not a placeholder: `scripts/issue109_v5_thresholds.py` and `scripts/verify_issue109_v5_unseal.py` both refuse to proceed unless `holdout_state == SEALED_NOT_CONSUMED` with at least two independently verified custodians (`commit_issue109_holdout.custody_is_satisfied`). Establishing and verifying a second independent custodian copy is an outstanding manual action before any physical v5 campaign (issue #110) may run its unseal preflight.

## Future gates

Issue #110 (physical execution, not authorized by this freeze) may run the reference/candidate campaign over the frozen calibration and stress corpora, derive the core threshold manifest and telemetry-band manifest only from complete evidence (`derive_v5_threshold_artifacts`), commit them, complete holdout custody, then run the non-decrypting unseal preflight. It may unseal only by explicit maintainer action. No post-holdout tuning is permitted.
