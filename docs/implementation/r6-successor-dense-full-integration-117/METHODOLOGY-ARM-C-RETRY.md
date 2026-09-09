# Issue #129 — Arm-C retry methodology remediation — frozen methodology

Status: FROZEN BEFORE ANY FUTURE ARM-C PHYSICAL RETRY.

This document freezes the corrected Arm-C retry methodology required by
issue #129 after the accepted #128 blocker
(`ISSUE117_ARM_C_EVIDENCE_BLOCKER`, merge
`718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22`). It authorizes and proves
CPU-only methodology readiness. It does NOT authorize any physical
execution, and it produces no ordinary-serving PASS or FAIL.

## 0. Authority and identities

- Accepted InferSwarm main after PR #128: `718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22`.
- Accepted Arm-B result: `ISSUE117_ARM_B_COLD_REALIZATION_PASS`, merge
  `fed87d1b71a0794374dd58c921e31606a56a242f`.
- Accepted Arm-C blocker: `ISSUE117_ARM_C_EVIDENCE_BLOCKER` (PR #128).
- Frozen FreeToken producer (every control-plane byte this methodology
  imports): `924cd22ea081f6d4ed471016faf01d427fc5b0d2`.
- Checkpoint authority:
  `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`.
- Accepted qualification subject:
  `sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`.
- Candidate `dense.6171f32b4413`; geometry `01/gpu-0 [0,16)`,
  `01/gpu-1 [16,32)`, `03/gpu-0 [32,48)`; Coordinator `inferswarm00`.
- Public fixture: exactly 24 `c109-*` cases, digest
  `sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2`.
  No `h109-*` material exists or may be created.

## 1. Why: the accepted frozen defect

The accepted #128 blocker established that the frozen Arm-C campaign did
not isolate the control plane:

- frozen direct comparator: one single-shot
  `generate(..., max_new_tokens=8)` per case;
- frozen ordinary path: `EpochServingController.serve_tokens`
  replay-prefix loop — one runtime call per committed position with
  `max_new_tokens=2`, commit step zero only, speculative second token
  discarded.

The arms therefore differed in runtime invocation semantics in addition
to control-plane routing. The retained 18/24 comparison and six
regime-4 divergences remain diagnostic evidence only; nothing in this
methodology is tuned against them.

## 2. Corrected comparator invocation contract (frozen)

The retry direct comparator must mechanically reproduce the ordinary
controller's runtime invocation contract. For each committed position:

1. derive replay input as `prompt_token_ids + committed_generated_token_ids`;
2. invoke the same integrated runtime with `max_new_tokens=2` (and the
   same `on_token` commit-capture contract);
3. commit only generated step/token zero;
4. treat the second generated token as speculative/uncommitted and
   discard it;
5. repeat until 8 tokens are committed.

A single-shot `max_new_tokens=8` direct comparator is prohibited (frozen
negative control `single_shot_8`).

## 3. CPU-only transcript-equivalence proof (the gate this issue runs)

Both arms run on a recording/fake runtime over all 24 frozen cases, on
CPU, with no model bytes and no GPU:

- ORDINARY arm: the REAL frozen control-plane bytes retained verbatim
  under `evidence/arm-c/frozen-freetoken/924cd22e/` —
  `freetoken.research.r3_planner` (generic planner),
  `freetoken.research.r5a_serving` (plan freeze + realization
  reconciliation), `freetoken.research.r5b_epochs`
  (`EpochServingController.serve_tokens`), and the R6 dense strategy
  adapters (`benchmarks/inferswarm_r6.{strategy,xc_strategy}`). The
  controller plans automatically (`AUTOMATIC_PLANNER_SELECTION` over the
  accepted campaign's single context-exact MEASURED ranking record,
  reconstructed verbatim from the retained accepted coordinator-report
  evidence audit), freezes a real execution plan, realizes it through a
  realizer whose observation is reconciled by the REAL frozen
  reconciliation machinery, and serves every case through the real
  `serve_tokens` loop.
- DIRECT arm: an independently coded comparator implementing §2 against
  the same frozen rendered prompt ids.

Both arms share one deterministic fake model response function seeded
from the frozen fixture bytes, so equivalence is a property of the two
control-plane paths, not of model outputs.

The recorded per-call transcript (the exact generate() argument set and
values) must be exactly equal across arms for every case: case identity;
logical session mapping; call count and position; prompt/replay token
ids; `max_new_tokens`; `on_token` presence (the commit-capture
contract); response commit token; speculative discarded token; stopping
semantics (length-only at 8); sampling inputs (greedy
temperature 0.0 / top_k −1 / top_p 1.0); candidate/plan semantics
(same candidate id, same mapping, both plans compiled by the real frozen
machinery).

Control-plane-only fields — `runtime_session_id`, `epoch_id`,
`generation`, `realization_id`, `plan_digest` value, `logical_session_id`
numbering, wall-clock stamps — may differ by construction and are
enumerated explicitly; the recording runtime captures the exact
generate() keyword set per call and the reducer requires it to equal the
frozen contract on both arms, proving those fields sit outside the
model-execution input transcript.

PASS only if all 24 cases have exact runtime-call transcript
equivalence. The reducer never consults stored `equal` flags or terminal
strings (frozen negative control).

## 4. Tokenizer / Source seam (frozen, non-ambiguous)

The blocked campaign observed four tokenizer-metadata reads under
`/srv/models/`. The retry methodology freezes the preferred approach:

- the exact rendered prompt token ids for all 24 public cases are a
  frozen methodology artifact (`evidence/arm-c-retry/prompt-fixture.json`),
  cross-derived from BOTH retained accepted sides (the direct-run
  results and the ordinary coordinator per-request records) with
  equality mechanically re-derived;
- the direct comparator consumes the frozen ids; it performs no
  tokenizer/Source read during the observation window;
- decoded-output reconstruction, if a future retry needs it, is a
  separate pinned CPU evidence step outside the observation window.

The methodology run mechanically proves `transformers` was never
imported in the observation process (a simulated import downgrades the
terminal to BLOCKED — frozen negative control).

## 5. Exact deployed-script identity contract (frozen)

No correctness-bearing execution from mutable/unpinned staged scripts.
Every correctness-bearing harness/driver on every host requires a
retained identity record with: repository SHA; file sha256; expected
path; read-only (or otherwise immutable) deployment identity;
pre-launch verification; post-run verification. Any correctness-bearing
script change after freeze (post-run sha256 differing from the frozen
file sha256) invalidates execution authority and requires a new
reviewed freeze. Mutable deployments, missing pins, and post-freeze
changes are rejected fail-closed (`verify_deployment_identity`).

## 6. Attempt/STOP state machine (frozen, executable)

Attempt classes are decided mechanically from observed facts — never
from an authored validity label:

- `PRE_OBSERVATION_INFRASTRUCTURE` — no correctness-bearing result or
  commit occurred;
- `CORRECTNESS_BEARING_VALID` — correctness-bearing result/commit with
  verified frozen identity (pre-launch AND post-run) and no prior STOP;
- `CORRECTNESS_BEARING_INVALID` — correctness-bearing result/commit
  without verified frozen identity (mandatory STOP:
  `invalid_correctness_bearing_observation`);
- `DIAGNOSTIC_ONLY_AFTER_STOP` — correctness-bearing observation
  explicitly after a STOP (retained as diagnostic, never as verdict
  authority);
- `TERMINAL_CAMPAIGN_ATTEMPT` — the classified terminal attempt.

A correctness-bearing attempt following a mandatory STOP without an
intervening terminal attempt fails closed
(`post_stop_continuation_without_terminal`) — including attempts that
label themselves diagnostic: after-stop classification derives from the
reducer's own stop-event history, never from an authored
``stop_occurred`` label. Post-stop diagnostics without any terminal
attempt may be retained, but they are never verdict authority and a
terminal attempt is mandatory before any new authorization.

## 7. Preserved Arm-C trust boundaries (future retry requirements)

A future physical retry must still preserve: CPU-only external
Coordinator; zero Coordinator model-weight receipt/materialization; zero
Coordinator CUDA initialization; accepted Arm-B participant state; no
model reacquisition/rematerialization; no silent plan substitution; full
fencing/session/plan/epoch/position attribution; no consumed holdout
material. This issue proves only that the methodology is sufficient to
test those claims correctly; it does not re-observe them physically.

## 8. Mandatory negative controls (all fail closed; retained in CI)

1. direct side uses `max_new_tokens=8` single-shot;
2. either side uses a different replay prefix;
3. either side changes call count;
4. either side commits the speculative second token;
5. sampling inputs differ;
6. prompt token ids differ;
7. stopping policy differs;
8. a control-plane-only field leaks into model execution inputs;
9. mutable/unpinned deployed driver identity is permitted;
10. a correctness-bearing script changes after freeze;
11. tokenizer Source access violates the frozen §4 rule;
12. an invalid correctness-bearing attempt continues without the frozen
    state machine authorizing it;
13. stored `equal: true` or stored terminal strings substitute for
    derivation.

## 9. Terminal / acceptance

Successful terminal: `ISSUE117_ARM_C_RETRY_METHODOLOGY_READY` — CPU-only
methodology readiness, NOT physical serving success.

Retained evidence: `evidence/arm-c-retry/prompt-fixture.json` (frozen
rendered ids + derivation provenance) and
`evidence/arm-c-retry/methodology-run.json` (full reduction, frozen
control-plane digests, per-case equality rows, CPU-only attestations),
both covered by the retained MANIFEST. The accepted `evidence/arm-c/`
blocker bytes are read-only input and are never edited.

After maintainer acceptance, Issue #117 may be updated to authorize a
new, separate Arm-C physical retry. That retry is NOT authorized by
this issue and was not executed.

## 10. Explicit non-claims

This methodology does not establish: Arm-C ordinary-serving PASS or
semantic FAIL; whether the six regime-4 divergences are a real runtime
defect; Arm-D restart/cache reuse; Arm-E locality mutation; any broader
model/vendor result. The accepted #128 blocker remains historical
truth.
