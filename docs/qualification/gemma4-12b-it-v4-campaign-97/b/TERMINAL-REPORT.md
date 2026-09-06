# Issue #97 — Gemma v4 physical qualification — TERMINAL REPORT

## Terminal verdict

`V4_HOLDOUT_CORE_FAIL`

A valid acceptance-bearing holdout failure. Terminal per issue #97 doctrine:
no tuning, no threshold change, no rerun, no resealing, no replacement holdout.

## Execution identities

- InferSwarm pre-execution authority head: `77064804d38122efeb2e05a98156a8df2dabdda3` (PR #98)
- Phase A calibration producer: `57dfcb7289efac8f66de5b3abbe8de04f2580f75` (FreeToken PR #31)
- Phase B holdout producer: `c60a4b7080913eba90585de8e8602460a7f5b1a7` (FreeToken PR #31)
- All three node worktrees verified clean at `c60a4b7` before execution; 13-test
  Phase B suite green on every node; all frozen artifact SHAs re-verified;
  non-decrypting preflight re-run PASS immediately before decrypt.

## h95 unseal

- Single-use decrypt performed 2026-09-06 under explicit maintainer Phase B
  authorization, from the verified external custodian path (record: `b/h95-unseal-record.json`).
- Commitment verification before any model execution: ALL PASS — 24 cases,
  every per-case hash (prompt/token_ids/case sha256) recomputed and matching
  the frozen public commitment; seed/generator/tokenizer identities bound.
- h95 is now CONSUMED. Plaintext never entered either repository.

## Execution

- Reference (inferswarm04 RTX 3090): 24/24 h95 cases, 0 NaN/Inf, all 192
  decision rows sha-verified (`href95` run index).
- Candidate (3-stage 3060 chain: 01 GPU-0/GPU-1 + 03 last stage): 24/24 cases,
  0 NaN/Inf, teacher-forcing prefix identity proven on all 192 decisions,
  forced trajectories byte-equal to reference (`cand95h` run index).
- Invalid attempts: none. Both arms completed rc=0 first try.

## Adjudication (frozen limits/bands/domains/semantic contract only)

Core observed maxima vs frozen limits (inclusive `observed <= limit`):

| family | observed | limit | verdict |
|---|---|---|---|
| fp32-consumer-logits:max-absolute-difference | 23.296875 | 26.625 | PASS |
| fp32-consumer-logits:rms-difference | 8.920100 | 10.134608 | PASS |
| **fp32-consumer-logits:p99-absolute-error** | **16.765625** | **16.640625** | **FAIL (+0.75%)** |
| decision_local_E_D | 20.875 | 26.625 | PASS |

Semantic adjudication (192 decisions, frozen v4 gate order, global E_D = 26.625):
- SEMANTIC_PASS 192/192 (all UNSTABLE-ambiguous, ambiguity-set admissible)
- STABLE_DECISION_MISMATCH 0; UNSTABLE_DECISION_INADMISSIBLE 0
- DECISION_LOCAL_BOUND_EXCEEDED 0; DECISION_DOMAIN_ESCAPE 0

Telemetry (TELEMETRY_ALERT, not qualification-failure): 4 alerts, all on
`h95-01-01-01` — hidden-residual-stream:rms, final-normalized-hidden-state:rms
and :p99, bf16-logits:p99.

## Failure anatomy

A single case, `h95-01-01-01` (ordinary-prose, 4-8 token regime — the shortest
prompt cell), drives the entire failure surface: the p99 core exceedance
(16.765625 vs 16.640625), the observed max-abs (23.2969) and E_D (20.875)
maxima, and all four telemetry alerts. Every other holdout case sits at least
3x below the failing limit (next-highest p99: 5.25). This mirrors the #88/#90
finding of a smooth heavy tail dominated by rare extreme draws, here in the
minimal-context regime where per-token relative divergence is largest.

## Retained evidence

- `b/h95-unseal-record.json` — unseal + commitment verification
- `b/holdout-adjudication.json` — terminal adjudication (core/semantic/telemetry)
- `b/holdout-rows.json` — all 24 case rows: 15 envelopes, case E_D, 8 decision
  rows each (domain hashes, decision-local errors, semantic verdicts)
- Node-local full evidence (never committed, retained on hosts):
  - inferswarm04 `/srv/inferswarm/state/issue97/holdout-reference/` (2.0G incl. FP32 rows + captures)
  - inferswarm01 `/srv/models/issue97/holdout-candidate/` (416M) and `/srv/models/issue97/holdout-adjudication/`
  - inferswarm03 `/srv/models/issue97/holdout-candidate-laststage/` (3.6G incl. candidate FP32 rows)

## PR state

Both PRs remain OPEN and unmerged pending maintainer review, per instruction.
