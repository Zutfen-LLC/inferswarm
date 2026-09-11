# Issue #133 Arm-C physical retry — physical-execution evidence

Status: `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` (re-derived under the
review-5173318161 fail-closed correction /3 from the unchanged retained
observations; pending maintainer re-review). Arm D remains blocked.

Campaign `armc-retry-afcdc4428f95d50c`, attempt `armc-retry-physical-1`,
execution freeze `88389598…` (schema /7), authority commit `c42a0ea3`
(merged to `origin/main` as `c4a8911`, PR #135).

## What ran

The first physical Arm-C retry under the corrected #129/#133 comparator
contract, on the authorized geometry (inferswarm01/gpu-0+gpu-1,
inferswarm03/gpu-0; BDFs re-observed live), frozen producer
`924cd22ea081f6d4ed471016faf01d427fc5b0d2` on every participant, the
accepted Arm-B materialized participant substrate (byte-reconciled
read-only against the accepted censuses, pre and post).

- Canonical Git-rooted prelaunch bootstrap (review 5169777338 launch
  contract, executed verbatim): PASS, `source_mode=
  accepted_git_materialization`, authority commit `c42a0ea3`, freeze
  binding `88389598…`, real-builder r5a digest `a730405d…` == frozen,
  environment `98c04387…`. Run twice: at Phase-B start and immediately
  before launch (both retained).
- Tokenizer deployment `/srv/inferswarm/tokenizers/gemma-r6-frozen`
  (exactly the five pinned assets, real dir, not under `/srv/models/`)
  on the coordinator and the direct driver host, under the frozen
  software identity (Python 3.12, transformers 5.17.0, tokenizers 0.23.2,
  Jinja2 3.1.6, MarkupSafe 3.0.3): 24/24 ordinary Coordinator rendering
  equality with the frozen prompt-token fixture, zero Source opens
  (audit hook).
- Direct arm: the corrected `issue133_arm_c_retry_direct.py`
  (file sha256 `02ec9cf7…`, deployed read-only at
  `/srv/inferswarm/state/arm-c-retry/scripts/`) driving the SAME
  integrated candidate substrate with the control plane bypassed:
  per-position replay prefill, frozen runtime-session allocator
  (AST-extracted from the pinned r5b_epochs.py), `max_new_tokens=2`,
  step-0 commit, step-1 discard; 24/24 cases, 192 invocations, plan
  digest `a730405d…` (authorized == locally built == runtime-returned).
- Ordinary arm: real client → external CPU-only Coordinator on
  inferswarm00 (frozen tok venv; no torch in maps, no CUDA env, no
  NVIDIA devices) → frozen strategy → generic planner (with the accepted
  `armc-direct-measured-chain-ttft` ranking evidence) → frozen serving
  plan `d9c4e295…` → node agent on inferswarm01 → 3-stage chain →
  remote last stage on inferswarm03 → fenced commits. 24/24 HTTP 200 +
  the controlled fencing-arm request; epoch RECLAIMED on SIGTERM.

## Result (independently re-derived, not authored)

`equality-reduction.json` (correction /2, maintainer review 5172615768)
re-derives committed tokens for BOTH arms from raw retained evidence
(serving-report runtime_sessions step-0 ids under the frozen allocator
vs direct per-case ids) and decoded bytes, and mechanically proves the
physical invocation seam through first divergence: for every case the
ordinary Coordinator's per-position replay prefix
(`coordinator_scope.requests[i].prompt_token_ids + committed ids before
the position`), the frozen-allocator runtime session id,
`max_new_tokens=2`, commit-step-zero and discard-step-one semantics are
compared against the direct invocation transcript call by call —
- 18/24 cases exact on committed token IDs at every position, committed
  count, stop semantics, and decoded output bytes, with all eight calls
  equivalent;
- 6 legitimate mismatches, all regime-4 (`c109-04-01-026`,
  `c109-04-02-047`, `c109-04-03-040`, `c109-04-04-024`,
  `c109-04-05-043`, `c109-04-06-074`) — committed-token divergence
  between the direct comparator and the ordinary path, on freshly
  executed arms in this campaign (the direct arm reproduces the 18
  regime-1/2/3 historical outputs byte-exactly; regime-4 divergences
  re-observe, not replay, the historical Arm-C blocker signature);
  mechanically derived first-divergence positions: 4, 0, 2, 3, 0, 0 —
  with complete model-input equivalence proven through the divergent
  call in every case (post-divergence prefixes differ by construction);
- HTTP content: all 24 contents (including the four regime-4 cases
  where a naive `decode(prompt+committed)` check fails) are
  byte-reproducible from the frozen Coordinator's incremental decoding
  (`cpu_only.printable_increment` holdback + `_decode_incremental`
  prefix diff); the four discrepancies are retained as non-prefix-stable
  incremental decoding, a distinct ordinary-serving semantic
  observation, not an evidence defect;
- One mismatch is a semantic FAIL under the frozen methodology. No
  rerun, no tuning, no relabeling.

Terminal reduction (`terminal-reduction.json`, correction /3 for review
5173318161): every mandatory zero is mechanically derived from retained
observations (fencing/attribution counters from
`coordinator_scope.requests[*].token_events` + session ledgers +
dual-retained injection rejection records). The Coordinator
receive/materialization/bulk zeros are derived from an exact transport
accounting (review 5173318161 P1): `coordinator-boundary-source-pins.json`
pins the twelve boundary/producer modules byte-bound to frozen producer
924cd22e (git blob == deployed participant trees == vendored bytes; host
preflights prove clean trees at that HEAD; the coordinator's own
constructor re-verified it via `_require_clean_exact_source`); AST over
the pinned bytes proves the receive surface is exactly one
`recv_frame` site over one node-agent socket plus the bounded HTTP
ingress (25 retained bodies), with every Coordinator-bound frame
constructed by `node_agent.py` at exactly two `send_exact` sites; the
200 GENERATE + 1 REPORT wire envelopes are re-encoded to exact canonical
wire bytes from retained payloads and every leaf classified
(control metadata / model payload / unknown — unknown must be 0);
REALIZE/CLOSE are budget-bound (203 frames x 24 MiB < the 9.26 GB
checkpoint — structural exclusion); census files are classified by
name/type with no size threshold (the invented 1-GiB threshold is
removed) and pre-census ⊆ post-census. Attempt attribution is fail-closed
(review 5173318161 P2): all 48 per-case files bind by full content
identity to their attempt-attributed aggregates; null/missing/wrong
attempt ids fail closed and no unexpected attempt ids exist anywhere in
the retained tree. Stale/wrong session/plan/epoch/position commits = 0,
unattributed = 0; two controlled fencing injections REJECTED pre-commit
(NON_NEXT_COMMIT_POSITION / RETIRED_OR_SUPERSEDED_EPOCH); coordinator
CUDA/model-weight/bulk-byte counters all 0; launch 1's
PRE_OBSERVATION_INFRASTRUCTURE classification is derived from the
retained launch-1 failure log + plan + the absence of launch-1 case
observations. The FAIL is classified semantic, not infrastructure.

## Data-path and identity invariants

- `strace-audit.json`: zero Source (`/srv/models/`) opens across all
  four traced processes (direct driver, node agent, both last-stage
  runs); zero writes under the accepted materialized participant state.
- `substrate-reconciliation-01/03.json`: the accepted Arm-B participant
  materializations are byte-identical (path set + sha256 per file) to
  the accepted Arm-C censuses, before AND after the campaign. No
  reacquisition, no rematerialization, no state movement.
- Deployment identities pre/post: driver `02ec9cf7…` unchanged,
  r5b_epochs `38867897…` unchanged, chain-plan `6d9a4859…` unchanged,
  last_stage_service `08825dcd…` == producer blob. All deployed
  correctness-bearing files read-only throughout.
- GPU identity: authorized UUID/BDF mapping observed live at preflight.

## Attempts (frozen state machine)

- Launch 1: `PRE_OBSERVATION_INFRASTRUCTURE` failure — stage startup
  died on a missing venv dependency (`tvm_ffi`) before ANY
  correctness-bearing observation (zero case files, zero commits;
  retained in `attempts/launch1-failure.log`). Fixed by completing the
  venv deployment; relaunch under the same attempt lineage.
- Launch 2 (direct arm) + ordinary campaign: `CORRECTNESS_BEARING_VALID`
  → `TERMINAL_CAMPAIGN_ATTEMPT` with terminal observation
  `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL`. No STOP fired; the campaign
  concluded with an authoritative terminal.

## Non-claims

- This FAIL does not diagnose the six regime-4 divergences; that
  analysis is for maintainers (the historical blocker-reduction remains
  diagnostic only).
- No Arm D execution, no holdout material, no rerun after the terminal.
- The four raw strace files (91 MB) are retained on
  inferswarm01/03 under `/srv/inferswarm/state/arm-c-retry/` with
  sha256 pins in `strace-raw-pins.json`; they are not committed to the
  repository by size.
