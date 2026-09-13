# Issue #172 — Arm-C physical requalification methodology (frozen BEFORE physical results)

Authority: InferSwarm issue #172. Campaign
`issue172-arm-c-requalification-v1`, physical authorization
`physical-authorization-issue172-inferswarm-bce7fb3d-freetoken-6202eeeb`,
attempt `armc-requal172-physical-1`.

This methodology is frozen before any correctness-bearing GPU/model
execution. It changes nothing in the accepted methodology line: it is the
accepted #129/#133 comparator contract applied unchanged over the union
of the accepted 24-case regression fixture and the accepted #170
16-case long-remainder generalization corpus, on the #166-remediated
producer. Every semantic below is consumed from accepted authority;
none is redefined here.

## 1. Starting heads (verified mechanically, `evidence/authority.json`)

- InferSwarm `main@bce7fb3d8e54429972472933be66433b81ebcf8f` (PR #171
  merge accepting the #170 corpus freeze).
- FreeToken `inferswarm-research@6202eeebcdf63e7bc8bb3498dd3c364ae42ee469`
  (PR #34 merge containing the accepted #166 remediation;
  implementation head `64a37a1` in ancestry).
- Execution-delta audit re-derived: the only execution-bearing delta
  beyond the accepted Arm-C producer `924cd22e` is the accepted #153
  single-chunk policy + the accepted #166 SWA lifecycle;
  `benchmarks/inferswarm_r6/stage_runtime.py` at the head is
  sha256 `afe9ceb0…` — byte-identical to the accepted #166 remediation
  hash. No unreviewed model-math/tokenizer/geometry/planner/comparator
  change exists in the lineage.

## 2. Subject / topology (frozen; consumed from #133/#172)

Model `google/gemma-4-12B-it` @ `707f0a3b`, checkpoint sha256
`5a84cb31…`, qualification subject `sha256:c6b9fe72…`, candidate
`dense.6171f32b4413`, geometry `inferswarm01/gpu-0 [0,16)`,
`inferswarm01/gpu-1 [16,32)`, `inferswarm03/gpu-0 [32,48)`, prefill
boundary 64 rows. Mutable hardware/software identities (GPU UUID/BDF,
driver, CUDA, Python, torch, tokenizer software, network) are
re-observed live at Phase 3 and bound before correctness-bearing
output; historical identities are never assumed.

Plan digest families (never conflated): Arm-B participant plan
`8646e00c…` (issue117.execution-plan/2, authority invariant); frozen
chain plan `a71a3129…`; r5a static execution plan `a730405d…` (the
direct comparator authorization fence, re-proven by the real-builder
dry run); the ordinary serving plan is re-derived this campaign through
the frozen planner (the #133 value `d9c4e295…` is history, not a fence).

## 3. Immutable 40-case corpus (`evidence/corpus-binding.json`)

- Regression arm: the accepted #133 fixture exactly as retained
  (24 cases, rendered ids digest `6046d479…`; raw identities bound to
  the accepted integration fixture digest `180185cd…`). The six
  historical divergent cases (`c109-04-01-026`, `c109-04-02-047`,
  `c109-04-03-040`, `c109-04-04-024`, `c109-04-05-043`,
  `c109-04-06-074`) are regression identities, not tuning targets.
- Generalization arm: the accepted #170 corpus consumed without
  regeneration (canonical digest `8a382df1…`; lengths 65..128,
  remainders 1..64, four per bucket). Rendered ids are pinned at
  deployment by re-rendering each `g170-*` prompt under the pinned
  frozen tokenizer and requiring the rendered length to equal the
  frozen target exactly (the #170 producer's measured
  wrapper-delta contract).
- Session indices: regression 1..24 (as retained); g170 25..40 in
  frozen case_id order.
- Before GPU launch both fixture digests are mechanically re-derived
  and the exact 24 + 16 = 40 identities required.

## 4. Comparator contract (accepted #129/#133, unchanged)

Per committed position on BOTH arms:

1. replay input = frozen rendered prompt ids + already committed ids;
2. accepted session/runtime allocation semantics (runtime session id
   from the frozen AST-extracted allocator, pinned `r5b_epochs.py`
   sha256 `38867897…`);
3. `generate(max_new_tokens=2)` with the frozen argument set
   (`max_new_tokens, on_token, prompt_token_ids, session_id`);
4. commit generated token/step zero;
5. discard speculative token/step one;
6. repeat until 8 committed tokens (length-only stopping).

Single-shot `max_new_tokens=8` is forbidden. Sampling frozen greedy
(temperature 0.0, top_k -1, top_p 1.0). Tokenizer boundary preserved:
pinned public tokenizer/config materialization only; no participant or
Coordinator Source fallback during the observation window.

Direct arm: the corrected `issue133_arm_c_retry_direct.py` semantics,
driving the SAME integrated candidate substrate with the
Coordinator/control plane bypassed, authorization fenced by the r5a
static-plan digest (authorized == locally built == runtime-returned).

Ordinary arm: real stdlib HTTP client → external CPU-only Coordinator on
inferswarm00 → frozen Gemma strategy → generic planner (automatic
selection from this campaign's own measured EXACT_CONTEXT ranking
evidence) → frozen serving plan → node agent on inferswarm01 → 3-stage
chain → remote last stage on inferswarm03 → fenced result → Coordinator
commit, plus one controlled fencing-arm request after the 40 cases.

## 5. Phase 2 — CPU transcript preflight (before physical output)

Using the accepted recording-runtime mechanism (no GPU, no model):
prove exact model-execution transcript equivalence between direct and
ordinary invocations for all 40 cases — the per-position replay prefix,
runtime session id allocation, argument set, commit/discard semantics
must be call-by-call identical, with control-plane-only differences
outside the runtime-invocation argument set. Fail-closed: any
difference blocks launch.

## 6. Phase 3 — physical preflight (before the first canonical result)

- canonical geometry → intended physical devices (live GPU UUID/BDF
  re-observation; the frozen devices must be present at the frozen
  indices; extra hardware is recorded inventory, not geometry);
- FreeToken `6202eee` deployed clean on every execution-bearing node;
  `stage_runtime.py` sha256 `afe9ceb0…` verified on each host;
- participant plan/materialization/shard identities and accepted model
  bytes (model-view substrate reconciliation against the accepted
  censuses);
- #157 deep diagnostic instrumentation proven OFF (env gates absent,
  no injected sitecustomize on the serving path);
- pristine SWA lifecycle state per qualified session observed through
  the least-perturbative accepted #166 seam
  (`swa_session_ownership_report` over the accepted RESET/generate
  path; no #157-style deep capture re-enabled);
- required fencing/control-plane negative controls from the accepted
  Arm-C methodology (duplicate-position and stale-epoch late-result
  injection rejected without ledger mutation);
- Coordinator zero CUDA/model-weight/bulk-artifact participation
  (torch-free process proof + transport accounting);
- no participant model reads under `/srv/models/` during the serving
  observation window; no hidden Source fallback/reacquisition
  (audit-hook + strace retained as in #133);
- complete launch order bound before inspecting candidate outputs.

A real pre-observation authority/environment/tooling contradiction is
`ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED`. The subject is never
silently repaired/substituted inside the campaign.

## 7. Phase 4 — canonical 40-case physical campaign

All 40 frozen cases through independently retained direct and ordinary
observations. For each case, re-derived from retained bytes, exact
equality required of at least: ordered model/runtime-call transcript;
committed token ids step-by-step; committed token count; stopping
semantics; decoded bytes/text under the pinned tokenizer; session /
realization / plan / epoch / position attribution; candidate /
producer / geometry identity. Both sides retained independently; no
authored `equal`/`pass` boolean substitutes for reduction from raw
retained outputs. One admissible mismatch is FAIL. No selective rerun.

## 8. Phase 5 — repeatability sentinels (prospectively frozen)

Seven identities: `c109-04-02-047` (Anchor A), `c109-04-06-074`
(Anchor B), `c109-03-04-003` (stable control), `g170-01` (bucket 1-8,
remainder 1), `g170-05` (9-24, remainder 9), `g170-09` (25-48,
remainder 25), `g170-13` (49-64, remainder 49). Six repeats per
identity per arm, each from fresh qualified session state with
identical frozen inputs/state construction. Require 6/6 within-direct
determinism, 6/6 within-ordinary determinism, exact direct-vs-ordinary
equality for every corresponding repeat, no selection of a preferred
run. All repeat distributions retained. Any valid within-arm variation
or cross-arm mismatch is terminal FAIL.

## 9. Mandatory zero / fail-closed invariants

During correctness-bearing observation, all of (mechanically derived
from retained bytes, never authored):

```
stale_session_commits == 0          wrong_session_commits == 0
stale_plan_commits == 0             wrong_plan_commits == 0
stale_epoch_commits == 0            wrong_epoch_commits == 0
wrong_position_commits == 0
unattributed_correctness_bearing_commits == 0
coordinator_cuda_initialized == 0
coordinator_model_weight_bytes_received == 0
coordinator_model_weight_bytes_materialized == 0
coordinator_bulk_artifact_bytes_observed == 0
```

plus: zero hidden Source fallback/reacquisition; zero unexpected
rematerialization/new participant model files; zero unexplained
persistent host model mirrors; zero silent plan substitution; zero
unauthorized model-state movement; no live prefix/store position
resolves to SWA sentinel slot 0; no stale SWA ownership survives
session reset/reuse (both observed through the accepted #166
ownership-report seam — #157 deep capture is NOT re-enabled; if the
accepted runtime cannot expose sufficient evidence without changing
execution-bearing behavior, stop pre-observation EVIDENCE_BLOCKED).

## 10. Attempt lineage / mandatory STOP

Fail-closed semantics accepted by #129/#133: every launch/attempt
retained; a pre-observation infrastructure failure is correctable only
when mechanically proven to have emitted/committed zero
correctness-bearing results with the frozen substrate preserved; an
invalid attempt that emitted any correctness-bearing result is STOP (no
later run derives PASS/FAIL authority); after any valid admissible
mismatch, repeatability variation, or invariant failure the terminal is
FAIL and the campaign is never restarted to seek a passing sample.

## 11. Terminals

- `ISSUE117_ARM_C_ORDINARY_SERVING_PASS` — all 40 canonical cases exact;
  all seven sentinels 6/6 deterministic within each arm and exact across
  arms; all Coordinator/fencing/Source/deployment/SWA invariants pass;
  no mandatory STOP fired.
- `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` — any admissible
  direct/ordinary mismatch, within-arm repeatability failure, or
  correctness-bearing invariant failure under the frozen campaign.
  Evidence retained; no diagnosis/remediation here.
- `ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED` — only for a
  concrete pre-observation authority/substrate/tooling contradiction.
  Cannot relabel a valid observed correctness failure.

## 12. Non-claims

A PASS does not rewrite the historical #133 FAIL — it is a new
post-remediation physical result. Arm D and Arm E are not started in
this issue even on a local PASS; they require maintainer
acceptance/merge of this requalification first. No FreeToken runtime
PR is expected; if execution-bearing FreeToken changes become
necessary the terminal is EVIDENCE_BLOCKED, not an in-campaign repair.
No `h109-*` material is opened, generated, copied, inferred,
reconstructed, decrypted, or used.
