# Issue #168 — Arm-C post-SWA requalification: EVIDENCE_BLOCKED (corpus insufficiency)

Status: **pre-observation terminal `ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED`** — PR open, unmerged, for maintainer review.

Issue #168 authorized the first physical requalification of the
remediated ordinary Arm-C path after acceptance of #166
(`ISSUE117_ARM_C_SWA_REMEDIATION_READY`). During Phase 1 (qualification
corpus freeze, before ANY model/GPU execution), the mandated fresh
public multi-chunk generalization arm proved corpus-insufficient:

- the arm requires 16 additional public `c109-*` cases, four per
  second-chunk-remainder bucket (1-8, 9-24, 25-48, 49-64), each
  requiring exactly two prefill chunks under the frozen 64-row
  contract;
- the public #109 calibration corpus is capped by its frozen length
  regimes at 56 raw prompt tokens per case; under the accepted
  chat-template rendering (reproduced byte-exact for all 24 accepted
  #133 fixture cases with the pinned frozen tokenizer) the maximum
  rendered length in the entire 1416-case corpus is 69;
- therefore buckets 25-48 and 49-64 are EMPTY under every defensible
  reading of the two-chunk length requirement (including the most
  generous: final comparator replay = rendered + 7 committed tokens,
  max remainder 12). Bucket 9-24 is also empty under the strict
  prompt-length reading (344 eligible only in 1-8).

Issue #168 explicitly forbids adapting buckets or inspecting outputs
and mandates this terminal for corpus insufficiency. No GPU, model,
direct/ordinary observation, or h109-* material is involved; the
accepted #133 FAIL and #157/#166 records are untouched.

## What the maintainer must decide

Either (a) authorize a fresh public multi-chunk corpus with longer
length regimes (a methodology change requiring a new freeze), or (b)
re-scope the fresh-arm bucket design to the reach of the existing
public corpus. This record deliberately does not choose.

## Evidence

- `evidence/authority-record.json` — Phase 0 authority/freeze record:
  fresh `campaign_id`/`physical_authorization_id`, verified starting
  heads (InferSwarm `00140a14`, FreeToken research `6202eeeb`, #166
  implementation head `64a37a1` with ancestor proofs), subject /
  checkpoint / candidate / geometry identities, 24-case regression
  fixture binding, the mechanical execution-delta audit of the producer
  lineage (accepted Arm-C producer `924cd22e` → #110 merge → #153
  single-chunk policy → #166 SWA lifecycle; only
  `benchmarks/inferswarm_r6/stage_runtime.py` changed in the #166 step,
  hash-bound), and the pre-observation state.
- `evidence/corpus-census.json` — deterministic fresh-arm census over
  the public 1416-case `c109-*` corpus with the pinned frozen
  tokenizer: all-case rendered lengths, both eligibility readings,
  per-bucket members with canonical selection keys (salt
  `issue168-arm-c-post-swa-requal-v1`), supplementary stress-pool
  bound.
- `evidence/terminal-reduction.json` — stdlib fail-closed reducer
  output re-deriving the terminal from retained bytes.

## Producers

- `scripts/issue168_corpus_census.py` — CPU-only census producer
  (imports the frozen tokenizer; runs under the #129/#133 frozen
  software identity).
- `scripts/issue168_authority_record.py` — authority/freeze record
  builder (pure stdlib; consumes accepted constants from
  `issue133_arm_c_retry_campaign` and the accepted #166 record tests).
- `scripts/issue168_terminal_reduction.py` — terminal reducer (pure
  stdlib, never reads authored terminal fields).
- `tests/test_issue168_requal_blocked_record.py` — machine checks +
  negative controls (runs in CI, stdlib only).

## Non-claims

- The Arm-C requalification question (does #166 restore ordinary
  serving equivalence?) is **not answered** — it cannot be under this
  corpus.
- No PASS/FAIL for any case; the six historical divergent cases were
  used as regression identities only.
- Arm D / Arm E not started; no h109-* access.
