# R6 successor dense full integration — issue #117

## Current state

**Observed terminal:** `ISSUE117_ARM_B_COLD_REALIZATION_PASS`

Arm B — canonical cold acquisition + realization — was executed on the
fabric on 2026-09-08 from accepted InferSwarm main
`5179c41232051e7455b778ddb8876a6539f4cb04` with the frozen integration
producer `924cd22ea081f6d4ed471016faf01d427fc5b0d2`.

The Arm-B observation is retained in PR #127 and is pending maintainer
acceptance. **Arm C is blocked until that acceptance.** Arms C/D/E have not
been executed. No holdout material was used.

Accepted predecessor gates remain historical authority:

- physical preflight: `ISSUE117_PHYSICAL_PREFLIGHT_PASS`;
- Arm A: `ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS`, accepted at merge
  `6774474941d7ce2a0252c8c1e148f8bce61a8d6d`;
- accepted #118 blocked/static record remains preserved byte-for-byte as the
  correct historical record for its point in time.

## Frozen subject and execution identity

Model: `google/gemma-4-12B-it`

Revision: `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`

Checkpoint authority SHA-256:

`5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`

Accepted qualification subject:

`sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd`

Canonical candidate geometry:

```text
inferswarm01/gpu-0  [0,16)
inferswarm01/gpu-1  [16,32)
inferswarm03/gpu-0  [32,48)
```

Candidate ID: `dense.6171f32b4413`

## Arm A — accepted execution-equivalence bridge

Arm A proved the frozen integrated producer remained execution-equivalent to
the accepted V5 authority on the public Issue #117 fixture:

- 24 public cases × 8 decisions = **192/192 exact FP32 consumer-row
  identities**;
- exact prefix/trajectory/token/rule-proof identity;
- 72/72 stage-boundary comparisons;
- exact accepted checkpoint and qualification-subject continuity;
- exact Compute Unit bindings;
- zero NaN/Inf observations;
- no holdout use;
- no Arm-B acquisition/materialization claim.

Arm-A evidence is retained under [`evidence/arm-a/`](evidence/arm-a/) and is
bounded by [`evidence/MANIFEST.sha256`](evidence/MANIFEST.sha256).

## Arm B — observed canonical cold acquisition + realization PASS

Arm B proves the artifact/data-path half of the successor architecture
physically.

The retained physical flow establishes:

1. canonical Issue #117 participant roots were cold and non-aliased before
   acquisition;
2. exact participant requirements were derived from the real checkpoint and
   frozen selected plan;
3. the CPU-only external Coordinator issued exact acquisition authority while
   carrying no bulk model bytes;
4. model-state acquisition used the accepted plan-driven artifact path only;
5. every object was verified before cache publication;
6. only participant-planned state was materialized;
7. realization loaded the participant shards onto the exact planned GPUs with
   no persistent host model mirror or CPU-owned decoder layers;
8. runtime-read evidence established no hidden Source-repository dependency;
9. all mandatory Arm-B zero invariants reduce to zero from retained evidence.

Participant realization totals:

| Participant | Fetched bytes | Resident device bytes |
|---|---:|---:|
| stage-1 / inferswarm01 gpu-0 | 9,256,814,624 | 9,264,678,944 |
| stage-2 / inferswarm01 gpu-1 | 7,278,939,168 | 7,290,735,648 |
| stage-3 / inferswarm03 gpu-0 | 9,292,212,768 | 9,304,009,248 |

The realization substrate retained zero persistent host model bytes on every
stage.

## Arm-B attempt lineage

The authoritative retained lineage is
[`evidence/arm-b/attempt-lineage.json`](evidence/arm-b/attempt-lineage.json),
schema `/2`.

Six invalid launches are retained before completion of the valid encompassing
campaign:

- launches 1–3 were pre-acquisition-validity failures and transferred no
  model bytes;
- launches 4–6 were nested campaign phase attempts;
- launch 6 physically reached full device residency, but its report failed
  during serialization and therefore retained **zero correctness-bearing
  realization records**.

Physical execution and correctness-bearing retention are intentionally
separate dimensions. Do not reinterpret launch 6 as "no realization
occurred."

The valid record is `campaign-1`, an encompassing campaign interval, not a
chronologically-started "launch #7". Nested attempts are explicitly bound
through `parent_campaign_id` / `subattempt_of`.

No invalid attempt produced a correctness-bearing observation or destroyed or
reset the canonical cold roots.

## Raw evidence and finalization-boundary movement proof

Round 3 retained the previously host-only raw evidence:

- `evidence/arm-b/raw/source-server-access.log`;
- `evidence/arm-b/raw/realize-strace.stage-{1,2,3}.log`;
- byte-pinned historical producer sources under `evidence/arm-b/raw/producer/`;
- read-only machine observations under `evidence/arm-b/observations/`.

The historical realization trace was:

`strace -f -qq -e trace=file`

It is therefore **path-level support, not byte-traffic measurement**.

`unplanned_steady_state_model_state_movement_bytes == 0` is established at
the runtime finalization boundary using the pinned producer semantics plus the
retained realization counters:

- every planned model-state mapping is scoped through
  `BoundedSafetensorsReader`;
- mapping open count equals mapping close count on every stage;
- `host_staging_current_bytes == 0`;
- staging bytes processed equal fetched bytes;
- persistent host model bytes are zero;
- the raw traces show no cache/Source opens and no model-state path opens
  after the final shard-open boundary.

The trace corroborates the finalized-state invariant; no byte count is
invented from `openat` events.

## Exact Coordinator state proof

Round 4 removed prefix/extension-based admission.

The observed Coordinator Arm-B state must equal an exact frozen set of
**14 regular files / 35,445,075 bytes**:

- 6 campaign data files: **35,399,067 bytes**;
- 8 operational files: **46,008 bytes**.

Every file is pinned by exact relative path, size, and SHA-256. Byte-exact
copies of all eight operational files are retained under
[`evidence/arm-b/raw/coordinator/`](evidence/arm-b/raw/coordinator/).

Unknown, renamed, added, removed, or digest-changed files fail closed
regardless of filename or extension.

## Coordinator receipt and materialization semantics

`coordinator_model_weight_bytes_received == 0` is **not** derived from final
filesystem occupancy.

It is derived from absence of any permitted or observed receipt path:

- zero Coordinator requests in the raw Source-server log;
- frozen ledger topology: inferswarm01 used local-file transport and
  inferswarm03 used operator-local HTTP from the Source host;
- every `ACQUIRED` event is participant-bound;
- the digest-bound contemporaneous execution-session transport audit records
  zero Coordinator/model-byte co-targeting commands and zero destructive
  Coordinator/canonical-root operations;
- the exact observed Coordinator state contains no model payload;
- the pinned historical producer/coordinator semantics contain no Coordinator
  model-byte acquisition path.

The transport audit is retained at
[`evidence/arm-b/observations/coordinator-transport-audit.json`](evidence/arm-b/observations/coordinator-transport-audit.json).

A receive-then-delete history therefore cannot be converted into a zero merely
by observing empty roots afterward.

`coordinator_model_weight_bytes_materialized == 0` derives from received ==
zero, the accepted pre-campaign Coordinator state, the exact observed
post-campaign state, and the pinned execution semantics. Final occupancy is
only a cross-check.

## Mandatory Arm-B zero invariants

The retained reducer must derive all of these as exactly zero:

```text
unrelated_model_bytes_acquired_for_realization
unassigned_model_weight_bytes_acquired
unexplained_full_model_dependency
participant_requires_complete_model_repository
coordinator_bulk_artifact_bytes_observed
unverified_state_used_as_locality_evidence
unauthorized_source_used
unexplained_transition_bytes
unexplained_persistent_host_mirror_bytes
unplanned_steady_state_model_state_movement_bytes
runtime_fallback_events
silent_plan_substitution_events
coordinator_cuda_initialized
coordinator_model_weight_bytes_received
coordinator_model_weight_bytes_materialized
```

The canonical reducer is:

`scripts/issue117_arm_b_evidence.py`

Stored summary zeros are cross-checks, not authority.

## Current validation

At PR #127 round-4 head `dfaee1722f2407d843be940b84905d77d4b6a636`:

- Arm-B retention suite: **112 passed**;
- reducer terminal: `ISSUE117_ARM_B_COLD_REALIZATION_PASS`;
- all 15 mandatory zero invariants: `0`;
- proof / Arm-A / physical-retention focused suites: passed;
- manifest verification: passed;
- project-status synchronization/check: passed;
- Markdown links: passed;
- `py_compile`: passed;
- `git diff --check`: passed;
- hosted CI run `34309763106`: success.

Two independent exact-head reviews completed with zero P0/P1 findings.

## Non-claims

- Arm B does not claim ordinary external-Coordinator serving; that is Arm C.
- No PREFILL/decode/generate or fixture serving was executed as part of Arm B.
- Arms C/D/E have not been executed.
- No consumed `h109-*` holdout material is used as Arm-B evidence.
- No public planner, artifact, path, or wire schema is frozen by this record.
- Historical accepted failures/blockers remain historical truth; later
  recovery/pass evidence is additive.

## Next gate

Arm C — ordinary external-Coordinator serving — remains blocked until
maintainer acceptance/merge of the Arm-B observation.

Do not rerun accepted Arm A, the accepted physical preflight, or Arm B merely
to begin Arm C.

## Evidence index

Core Issue #117 records:

- [Frozen methodology](METHODOLOGY.md)
- [Canonical #118 historical summary](evidence/canonical-summary.json)
- [Physical preflight](evidence/physical-preflight.json)
- [Applicability audit](evidence/applicability-audit.json)
- [Planner decision](evidence/planner-decision.json)
- [Producer hashes](evidence/producer-hashes.json)
- [Integrity manifest](evidence/MANIFEST.sha256)

Arm A:

- [Arm-A evidence](evidence/arm-a/)
- [Arm-A run record](evidence/arm-a/run-record.json)
- [Arm-A attempt lineage](evidence/arm-a/attempt-lineage.json)

Arm B:

- [Arm-B evidence](evidence/arm-b/)
- [Attempt lineage](evidence/arm-b/attempt-lineage.json)
- [Execution plan](evidence/arm-b/execution-plan.json)
- [Requirements](evidence/arm-b/requirements.json)
- [Coordinator record](evidence/arm-b/coordinator-record.json)
- [Coordinator transport accounting](evidence/arm-b/coordinator-transport-accounting.json)
- [Coordinator transport audit](evidence/arm-b/observations/coordinator-transport-audit.json)
- [Steady-state movement](evidence/arm-b/steady-state-movement.json)
- [Runtime fallback accounting](evidence/arm-b/runtime-fallback-accounting.json)
- [Raw retained evidence](evidence/arm-b/raw/)

Internal record, digest, cache-layout, and descriptor choices remain unfrozen
implementation details unless another accepted doctrine explicitly freezes
them.
