# Issue #170 — Arm-C long-remainder public corpus freeze (CPU-only)

Successor to the accepted Issue #168 blocker
(`ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED`,
classification `corpus_insufficiency_pre_observation`): the maintainer
chose the stronger correction — freeze a fresh PUBLIC longer-regime
generalization corpus that honestly populates the original four
second-chunk-remainder buckets — instead of re-scoping buckets to the
bounded historical `c109` corpus.

This issue freezes the corpus only. It does **not** answer whether the
#166 SWA lifecycle correction fixes Arm C, derives no Arm-C PASS/FAIL,
starts no Arm D/E, and performs **no physical execution** (no GPU, no
CUDA, no Gemma model, no FreeToken candidate runtime, no
candidate-output inspection, no `h109-*` access).

## Authority

- InferSwarm `main@941d0fe52ecedff1c5294a5582af3fedecb1018e` (PR #169 merge)
- FreeToken `inferswarm-research@6202eeebcdf63e7bc8bb3498dd3c364ae42ee469` (accepted #166 remediation merge, unchanged)
- Tokenizer/render semantics: accepted #129/#133 frozen assets +
  software identity (`python 3.12`, `transformers 5.17.0`,
  `tokenizers 0.23.2`); all 24 accepted #133 fixture renders
  reproduced byte-exact before generation (24/24 preflight).

## Methodology (all frozen in source before generation)

- public seed `issue170-arm-c-long-remainder-corpus-v1`, namespace
  `arm-c-long-remainder`, case prefix `g170-`;
- exact 16 target rendered lengths 65,67,69,72,73,78,83,88,89,96,
  104,112,113,118,123,128 -> remainders 1,3,5,8,9,14,19,24,25,32,40,
  48,49,54,59,64 under the frozen 64-row boundary -> exactly four
  cases per original #168 bucket (1-8 / 9-24 / 25-48 / 49-64);
- content-class assignment rule: ordinal i (0-based ascending) ->
  `CONTENT_CLASSES[(2 + 5*i) % 6]` (the six accepted public classes;
  realized 3,3,3,3,2,2 — every class at least twice);
- deterministic search: per target, monotonically increasing attempt
  nonce from 0; raw-token target order L-13 then L-12 (frozen
  wrapper-delta hypothesis order); first exact-length realization that
  passes public-historical disjointness is accepted; search ceiling
  4096 nonces per target (frozen; BLOCKED if exceeded — never adapted);
- disjointness against all 1416 public `c109-*` calibration cases,
  the public `p109-*` stress pool, the 24-case accepted #133 fixture,
  and the accepted #157 anchor/control identities (prompt-text,
  raw-token, and rendered-token digests where represented);
  `h109-*` is forbidden input and never enumerated.

## Files

- `evidence/corpus.json` — complete frozen methodology + 16 public
  cases (prompt text, raw/rendered token ids and counts, remainders,
  buckets, attempt metadata, digests, exclusion inventory) + canonical
  corpus digest
- `evidence/authority-record.json` — starting heads/ancestry proofs,
  accepted authority chain consumed, execution non-claims
- `evidence/terminal-reduction.json` — fail-closed reducer output
  (`ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_FROZEN`, mechanically
  re-derived from retained bytes)
- `evidence/producer-hashes.json`, `evidence/MANIFEST.sha256`

## Producers / tests (CPU-only)

- `scripts/issue170_corpus_methodology.py` (pure stdlib, frozen
  constants), `scripts/issue170_corpus_producer.py` (tokenizer-bound
  producer), `scripts/issue170_authority_record.py`,
  `scripts/issue170_terminal_reduction.py` (fail-closed stdlib
  reducer), `scripts/issue170_manifest.py`
- `tests/test_issue170_long_remainder_corpus.py` — determinism,
  completeness, bucket/class coverage, disjointness, purity, and the
  mandated negative controls (mutations must fail)

The physical Arm-C requalification successor (40-case canonical
campaign = the accepted 24-case #133 regression fixture + this frozen
16-case corpus, plus repeatability sentinels) remains separately
blocked pending maintainer acceptance/merge of this freeze.
