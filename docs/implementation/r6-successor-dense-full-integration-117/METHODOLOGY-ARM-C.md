# Issue #117 Arm C — ordinary external-Coordinator serving — frozen methodology

Status: FROZEN BEFORE ANY ARM-C CORRECTNESS-BEARING EXECUTION.

Arm C proves the accepted integrated dense-Gemma substrate behaves correctly
through the ordinary InferSwarm serving/control path. This document freezes
every methodology choice before execution. Nothing here may be tuned after a
correctness-bearing observation.

## 0. Authority and identities

- Accepted InferSwarm main (Arm-B merge): `fed87d1b71a0794374dd58c921e31606a56a242f`.
- Arm-C branch: `issue-117-arm-c-ordinary-serving` (accepted main + the
  status-sync commit `docs: authorize issue 117 arm C after arm B acceptance`,
  classified execution-substrate-neutral).
- Frozen FreeToken integration producer on EVERY participant and on the
  Coordinator checkout: `924cd22ea081f6d4ed471016faf01d427fc5b0d2` (clean
  trees; no FreeToken commits are permitted in Arm C —
  `benchmarks/inferswarm_r6/` and the model/execution surfaces are bound to
  non-admissible surfaces by the #117 applicability audit; any FreeToken
  delta would require a new producer-delta/applicability review).
- Checkpoint authority: `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`.
- Accepted qualification subject:
  `sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`.
- Candidate: `dense.6171f32b4413`; geometry `01/gpu-0 [0,16)`, `01/gpu-1
  [16,32)`, `03/gpu-0 [32,48)`; Coordinator `inferswarm00` (CPU-only).
- Accepted Arm-B execution-plan digest (historical authority):
  `sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad`.
- Accepted participant plan on hosts:
  `/srv/inferswarm/state/arm-b/accepted-participant-plan.json`
  (digest `sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1`,
  producer `44d6c94e…`).
- Fixture: exactly 24 public `c109-*` cases, digest
  `sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2`.
  No `h109-*` material may be used.

## 1. Arm-C participant plan (same semantics, producer-bound)

The Arm-C chain plan is re-frozen from the accepted participant plan using
the frozen producer's own freeze code (`freetoken.research.r2_local_split.
freeze_plan`) with producer `924cd22e…`:

- block specs, `allowed_tensor_keys`, `declared_shared_state`,
  `boundary_geometry`, and `runtime_capacity_tokens` (256) are copied from
  the accepted participant plan UNCHANGED;
- every block's allowed key set is mechanically verified against the HEADERS
  of the accepted materialized participant shards (no Source-tree access of
  any kind during plan construction);
- provenance binds the running producer `924cd22e…`;
- the resulting digest differs from `ee845188…` only through the
  producer-bound provenance; the reducer proves key-set/spec equality with
  the accepted plan and per-shard header equality.

The last-stage service therefore starts in `PLAN_FROZEN` mode (no
`--allow-producer` override; that path is explicitly non-canonical).

## 2. Serving-time realization from accepted participant state

No acquisition, cache read, rematerialization, or Source access occurs.
Participants start from the accepted Arm-B materialized state only:

- inferswarm01: `/srv/inferswarm/state/arm-c/model-view/` — a ZERO-BYTE
  symlink view containing `config.json` and two shard symlinks pointing at
  the accepted materialized `stage-1`/`stage-2` shards. The unmodified
  multi-shard bounded loader resolves each stage's disjoint planned key set
  from these links. Symlink creation is the declared serving-time
  realization seam; zero model bytes are moved, copied, or written.
- inferswarm03: the last-stage service uses
  `/srv/inferswarm/materialized/issue117/dense.6171f32b4413.stage-3`
  directly.
- Startup realization is expected to load each stage's full planned shard to
  its planned GPU (accepted Arm-B residency semantics) and is mechanically
  accounted (open counts, staging release, persistent host mirror zero).

If serving cannot start from this state without new acquisition, STOP
(classify; do not rebuild Arm B).

## 3. Ordinary path definition (the only correctness-bearing distributed arm)

```
ordinary client (HTTP POST /v1/chat/completions, from the orchestration
  host over the network)
  → external CPU-only Coordinator on inferswarm00
     (benchmarks/inferswarm_r6/coordinator.py @ 924cd22e; #67 waist)
  → EpochServingController → strategy (GemmaTokenBoundaryStrategy)
  → generic planner (r3_planner.plan over the frozen resource snapshot,
     operator policy, objective, evidence catalog)
  → frozen execution plan (freeze_execution_plan)
  → xc-wire REALIZE → node agent on inferswarm01
  → 3-stage chain (stage-1/2 local GPUs, stage-3 via accepted R4 wire to
     inferswarm03) — realized remote Compute Nodes
  → fenced result (accept_result: epoch/plan/session/position)
  → Coordinator commit (committed ledger + on_token events)
```

Prohibited (each would invalidate the arm): invoking participant runtimes
directly and labeling it ordinary serving; injecting a plan without the
planner; calling internal Coordinator functions in place of HTTP ingress;
copying model bytes; bespoke substitutes for the serving path; weakening
fencing; hard-coded candidate selection.

Planner honesty requirement: the evidence catalog record is MEASURED at the
exact current context (producer `924cd22e…`, same topology/revision) by the
direct-control arm, which runs FIRST. The planner still evaluates every
legal shape and selects automatically (`AUTOMATIC_PLANNER_SELECTION`). The
historical `44d6c94e`-bound record is context-inapplicable and is not used.

## 4. Direct-control comparator definition

For each of the 24 cases, the SAME integrated candidate substrate
(`benchmarks/inferswarm_r6/chain_runtime.ChainEpochRuntime` constructed
exactly as the node agent constructs it: same producer, same chain plan,
same view-dir/state model sources, same R4 last-stage service binary and
checkpoint state) is invoked directly on inferswarm01 with the
Coordinator/control plane fully bypassed: one `generate(session_id=i,
prompt_token_ids=<rendered ids>, max_new_tokens=8)` per case.

Both arms use the same: FreeToken producer `924cd22e…`; checkpoint
authority; candidate geometry; materialized participant state; block/plan
semantics; input bytes (the coordinator's own chat render of the fixture
prompt — the direct arm renders independently with the same tokenizer
files and the retained prompt ids must be byte-equal, verified by the
reducer, not asserted); generation configuration and stopping policy
(§5); tokenizer/decoding semantics (same tokenizer files);
model/runtime implementation. The ONLY intended difference is the
control-plane path. The V5/RTX-3090 reference path is NOT the comparator.

## 5. Request construction, generation configuration, stopping policy

- Ordinary request: `POST /v1/chat/completions` with body
  `{"model":"gemma-4-12B-it","messages":[{"role":"user","content":<fixture
  prompt_text>}],"max_tokens":8,"temperature":0.0}`. No other fields.
- Generation configuration: greedy (temperature 0.0, top_k −1, top_p 1.0 —
  the coordinator's frozen defaults), derived from the accepted R6 serving
  authority (canonical request) and the V5 campaign's GENERATED_TOKENS = 8.
- Stopping policy: length-only at 8 committed tokens (the ordinary serving
  contract; finish reason `length`). No EOS/stop-string semantics exist on
  this path; both arms stop identically.
- Ordering: cases are served in ascending `case_id` order (deterministic);
  session ids are assigned by the ordinary path (1..24). One additional
  fencing-arm request (case with the lowest case_id, `max_tokens` 8,
  `inferswarm_fencing_arm_after_step`: 3) runs AFTER the 24 cases; its
  outputs are fencing evidence only and are not part of the equality set.
- Direct arm: same 24 prompts in the same order, `max_new_tokens=8`.

## 6. Mandatory exact per-case equivalence (derived, never asserted)

For every case, from both independently retained sides:

- generated token IDs at every committed step (8 positions);
- committed token count (8);
- stop reason / stop-length semantics (`length` at 8);
- committed decoded output bytes (UTF-8 decode of the committed ids; also
  cross-checked against the ordinary HTTP content stream);
- final request classification (success);
- deterministic request/result identities of the ordinary contract
  (session id, committed epoch ids, committed plan digests, positions).

A single valid mismatch on any dimension is a real Arm-C failure
(`ISSUE117_ARM_C_ORDINARY_SERVING_FAIL` class). No tolerance comparator.
No rerun/tuning after a correctness-bearing mismatch.

## 7. Attribution/fencing

The runtime uses the accepted #62/#67/#101 dimensions: session, epoch
(Coordinator-authorized generation), realization id, plan digest,
operation, position. The reducer mechanically derives, from the retained
coordinator report and per-request records:

```
stale_session_commits == 0        wrong_session_commits == 0
stale_plan_commits == 0           wrong_plan_commits == 0
stale_epoch_commits == 0          wrong_epoch_commits == 0
wrong_position_commits == 0       unattributed_correctness_bearing_commits == 0
```

retaining the stronger runtime names individually (epoch_id, generation,
realization_id, plan_digest, position, runtime_session_id). The real
serving-path fencing arm (duplicate committed position; retired/stale
epoch) is executed via the coordinator's controlled injection seam and its
rejections retained. CPU mutation controls poison each dimension and must
fail closed through the real derivation.

## 8. Coordinator invariants (Arm-C window)

```
coordinator_cuda_initialized == 0
coordinator_model_weight_bytes_received == 0
coordinator_model_weight_bytes_materialized == 0
coordinator_bulk_artifact_bytes_observed == 0
```

Derived from Arm-C-window observations: the Coordinator host has no NVIDIA
device nodes; its venv has no torch/triton (pip snapshot retained; any
torch import is categorically impossible); the coordinator state directory
equals an exact before/after census (no model payload); the xc wire frames
are bounded (24 MiB body budget) JSON; the HTTP ingress bodies are bounded
(4 MiB); the orchestration command audit (this session) shows zero
coordinator/model-byte co-targeting commands and zero destructive
coordinator/canonical-root operations. Arm-B zeros are historical and are
not used as Arm-C proof.

## 9. Participant data-path preservation (Arm-C window)

- Zero Source-tree reads: the complete ordinary-arm serving tree on 01 and
  03 runs under `strace -f -e trace=file`; the retained trace must show no
  open of any path under `/srv/models/` (Source) and none under
  `/srv/inferswarm/cache/` (no reacquisition) during the serving window.
- Zero rematerialization: materialized root inode/mtime census before and
  after the campaign is unchanged; no new files.
- Zero unexplained persistent host mirror: stage reports retain
  `persistent_host_model_bytes == 0`, `host_staging_current_bytes == 0`,
  mapping open==close counts.
- Zero unplanned model-state movement: symlink view creation is the only
  filesystem change under `/srv/inferswarm/state/arm-c/` setup; it is
  declared here and accounted in lineage.
- No complete model repository is required on any participant (each stage
  reads only its planned shard through the bounded reader).

## 10. Attempt lineage

Every physical launch/attempt is retained in
`evidence/arm-c/attempt-lineage.json` with: logical id; ordering; observed
timestamps; exact pre-execution InferSwarm SHA and FreeToken producer;
hosts; phase reached; exception/failure; whether a realization request
occurred; whether GPU execution/device residency occurred; whether any
correctness-bearing result was emitted; whether any result reached the
Coordinator; whether any Coordinator commit occurred; whether accepted
Arm-B participant state changed; cleanup/containment; evidence bindings.
Pre-observation infrastructure failures may be corrected only with
mechanical proof of zero correctness-bearing observations/commits,
preserved participant state, and no tuned-away result. An invalid attempt
with a correctness-bearing observation or commit is NOT harmless: STOP for
maintainer review.

## 11. Terminal classifications

- PASS only as `ISSUE117_ARM_C_ORDINARY_SERVING_PASS` (24/24 exact on all
  mandatory dimensions + all zero invariants + fencing proven).
- Valid ordinary-serving semantic mismatch:
  `ISSUE117_ARM_C_ORDINARY_SERVING_FAIL`.
- Fencing/attribution failure; Coordinator-boundary failure; participant
data-path failure: narrowest applicable failure class, never relabeled as
infrastructure.
- Pre-observation evidence/infrastructure blocker:
  `ISSUE117_ARM_C_EVIDENCE_BLOCKER` (narrowest).

## 12. Retained evidence set (manifest-covered)

`evidence/arm-c/`: run record + attempt lineage; pre-run reconciliation;
Arm-C plan + plan-equivalence derivation; environment freeze + coordinator
config + serving evidence record; direct-arm per-case results; ordinary
client per-case HTTP records; coordinator serving report (retained bytes);
last-stage final reports + ready files (both arms); strace logs (direct +
ordinary; gzip-compressed); host census observations (pre/post); fencing
records; per-case equality derivation; zero-invariant derivations;
orchestration audit. Both comparison sides are retained independently; the
reducer never consumes a stored `equal` summary as authority.

## 13. Explicit non-claims

Arm C claims nothing about warm restart (Arm D), locality mutation
(Arm E), statistical qualification, other models/vendors/backends, or any
path beyond the frozen subject/topology/producer. The physical preflight,
Arm A, and Arm B are accepted gates and are not rerun.
