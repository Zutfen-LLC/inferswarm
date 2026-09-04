# Issue #79 — v2 executable evidence/threshold/unseal tooling

## Status

Methodology v2 accepted at InferSwarm `main@8905566031e0296694b3f1288d0f9d1ae15f8134`
(PR #78). Issue #79 freezes the executable v2 evidence/threshold/unseal
schemas and tooling. **No v2 model execution has yet occurred** — physical
execution remains unauthorized until #79 is reviewed/accepted.

Historical issue #76 v1 execution remains terminal
(`PHASE0_REFERENCE_COMPLETE` / `STRESS_SELECTION_BLOCKED`), and historical
R6 remains permanently `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`. Neither
is reopened or rewritten by this issue.

## What changed (provenance only, math unchanged)

The accepted v2 methodology uses the unchanged 576-case `c74-*` statistical
calibration corpus, the new `p76-*` v2 stress pool, v2 stress schemas and
the future selected-eight manifest, and the retained v1 sealed holdout. The
v1 executable path was hard-bound to `p74-*`, v1 pool/selection schemas and
the v1 unseal verifier. Issue #79 adds **versioned v2 executable tooling**
that accepts the exact v2 stress evidence while preserving all v1 behavior:

- `docs/qualification/gemma4-12b-it-v2/schemas/calibration-summary.schema.json`
  — `inferswarm.issue79.v2-calibration-summary/1`: exactly 576 `c74-*`
  statistical rows + exactly 8 `p76-*` stress rows, exact `case_sha256`
  bindings, exact-integrity/semantic PASS gates, `finite`/`evidence_complete`
  true, exactly 15 envelope keys, provenance fields (corpus, pool,
  commitment, selection, evidence SHAs). No holdout field is allowed.
- `docs/qualification/gemma4-12b-it-v2/schemas/threshold-manifest.schema.json`
  — `inferswarm.issue79.v2-threshold-manifest/1`: full provenance + the same
  15 envelope names, per-limit `statistical_max_hex`/`stress_max_hex`/
  `limit_hex` with `rule = max(statistical_max,stress_max)` and
  `comparison = observed<=limit`, `holdout_state = SEALED_NOT_CONSUMED`,
  `manual_editing_or_rounding = PROHIBITED`.
- `scripts/issue79_v2_thresholds.py` — deterministic CPU-only derivation.
  Fail-closed validation order: contract/tooling identity → exact frozen
  `c74-*` corpus (SHA + 576-ID mapping) → exact frozen `p76-*` pool →
  exact accepted v2 commitment (pre-reference state, selector path+hash,
  unchanged margin definition, finite-positive eligibility, candidate
  observations forbidden) → future selected-eight manifest (v2 schema,
  `FROZEN_AFTER_MATCHED_REFERENCE_BEFORE_HETEROGENEOUS_CANDIDATE` state,
  pool/commitment SHA binding, `MATCHED_REFERENCE_MARGINS_ONLY`, exactly 8
  unique pool-identical cases, 4+4 grouping, no `p74-*`) → v2 calibration
  summary (all gates) → holdout-exclusion scan on every input. It does NOT
  recompute the ranking and does not need the holdout.
- `scripts/verify_issue79_v2_unseal.py` — v2 unseal preflight/verifier.
  `validate_unseal_preconditions(...)` refuses permission unless the
  threshold manifest validates against the v2 schema, matches the
  externally committed SHA, says `SEALED_NOT_CONSUMED`, is bound to the
  accepted v2 tooling version, and every artifact SHA (corpus, pool,
  commitment, selected-eight, ciphertext `23311c55…`, certificate
  `9edb50e8…`) is exact, custody is not blocked, and any future private-key
  path is external to the repo scope. It never decrypts and never invokes
  OpenSSL. The v1 unseal script remains byte-identical.

**Threshold math is unchanged from v1**: for each of exactly 15 envelopes,
`limit = max(statistical_max over 576, stress_max over 8)`, comparison
`observed <= limit`, reducer identity
`host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1`,
exact hexadecimal binary64 serialization, no interpolation, no rounding, no
universal epsilon. Only artifact versioning/provenance changed to support
`p76-*`.

## Test-only synthetic evidence

`tests/test_issue79_v2_threshold_tooling.py` builds a clearly-labeled
TEST-ONLY SYNTHETIC end-to-end fixture: real frozen 576 `c74-*` identities,
real frozen v2 48-case pool, accepted real selector + commitment,
deterministic synthetic reference margins, selector-generated synthetic
selected-eight manifest (generated in test memory, never committed into the
qualification evidence directory), synthetic finite envelope summaries and
evidence SHAs. A structural test asserts no selected-eight manifest exists
anywhere under the v2 evidence directory. Positive path proves: manifest
validates → summary validates → derivation succeeds → threshold manifest
validates → byte-for-byte determinism → unseal preflight passes up to but
not including decrypt. Negative controls cover statistical-corpus
substitution/duplication/count drift, stress-provenance forgery (v1 rows,
non-selected rows, wrong SHAs, v1 schema, wrong state/inputs, margin
drift), correctness gates, holdout poisoning, and every unseal-preflight
precondition.

## Frozen inputs (unchanged, verified by tests)

| Artifact | SHA-256 |
|---|---|
| calibration corpus (`c74-*`, 576) | `e147ce0a672fe7f8616f9e000fea770bfeab6e0a1aca637ffe6bc07cd64c3175` |
| v2 stress pool (`p76-*`, 48) | `533b32857721b3f99243e5695bc18b24960cbd3c80692d626154907d6ecbd7c9` |
| v2 selector | `e32e8672671c3b3ec6b47e3b119c66fd54e2c5a62ba72fb2ec2288764508beab` |
| v2 selection commitment | `04421a6f19f6338a340dfea296214509eae3adc5ca32067dfd76880ab1cacba0` |
| holdout ciphertext | `23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59` |
| recipient certificate | `9edb50e82a070bc666b43ac7d0fac158caa906a34510efda3241b1d160be2b46` |

The living v1 `MANIFEST.sha256` pins `.github/workflows/ci.yml`; its entry
was regenerated mechanically (new hash `fc55c62e…`) after adding the #79
CPU-only CI step. No frozen v1 experiment content was altered.

## Not yet authorized

- the v2 Phase-0 reference-only run over the frozen v2 pool;
- any heterogeneous candidate execution;
- derivation against real (non-synthetic) evidence;
- holdout consumption/unseal.

Physical execution remains unauthorized until #79 is reviewed and accepted.
