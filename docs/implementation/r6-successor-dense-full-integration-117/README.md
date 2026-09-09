# R6 successor dense full integration — issue #117

## Current state

**Observed terminals (latest first):**

- Issue #129 (2026-09-09, review-corrected, pending maintainer review):
  `ISSUE117_ARM_C_RETRY_METHODOLOGY_READY` — CPU-only Arm-C retry
  methodology remediation. The corrected comparator contract (per
  committed position: replay prefix, `max_new_tokens=2`, commit step
  zero, discard the speculative second token; runtime-session
  allocation mechanically extracted from the pinned controller bytes),
  and the frozen 24-case rendered prompt-token fixture are frozen. Five
  exact tokenizer assets and the tokenizer software identity are
  retained outside the accepted Arm-C namespace. The real local-only
  tokenizer renders the exact request bodies through the AST-extracted
  Coordinator function to the frozen fixture IDs, 24/24. The CPU
  recording-runtime comparator gives 24/24 exact equivalence. It
  compares all `generate()` argument values, including runtime session
  IDs, between the real frozen `EpochServingController` path and the
  corrected direct comparator. The tokenizer Source contract requires
  pinned non-Source assets and zero forbidden-root opens. The accepted
  #128 preservation regression proves all `evidence/arm-c/`
  paths are byte-exact from merge `718efbf…` and no new path exists in
  that namespace. The campaign reducer makes a correctness-bearing STOP
  permanent within one campaign. A new campaign requires a fresh
  post-review authorization and lineage root. A separate accepted authority
  record binds every campaign. A campaign passes only after an authoritative
  terminal attempt. Diagnostics remain non-authoritative. All mandatory negative
  controls and the exact deployed-script identity contract are frozen in
  [METHODOLOGY-ARM-C-RETRY.md](METHODOLOGY-ARM-C-RETRY.md) with evidence
  under `evidence/arm-c-retry/` (`methodology-run.json`,
  `prompt-fixture.json`, `authority.json`, `integrity.json`). No
  physical execution; the physical Arm-C retry itself is NOT yet
  authorized.
- Arm C (2026-09-09, corrected 2026-09-09): physical observations
  exist, but the campaign is **methodology/evidence-blocked** —
  `ISSUE117_ARM_C_EVIDENCE_BLOCKER` (post-correctness-bearing
  methodology / evidence-admissibility failure); no accepted
  ordinary-serving semantic PASS or FAIL exists from this campaign
  (see the Arm C section below).
- Arm B (2026-09-08, ACCEPTED at merge
  `fed87d1b71a0794374dd58c921e31606a56a242f`, PR #127):
  `ISSUE117_ARM_B_COLD_REALIZATION_PASS` — executed from historical
  accepted main `5179c41232051e7455b778ddb8876a6539f4cb04` with the frozen
  integration producer `924cd22ea081f6d4ed471016faf01d427fc5b0d2`. No
  holdout material was used.

Arm D has NOT been executed and remains blocked pending maintainer review
of the Arm-C observation.

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

## Arm C — methodology/evidence-blocked campaign (2026-09-09)

Arm C executed physically on the fabric from accepted main
`fed87d1b…` + status-sync, with the frozen integration producer
`924cd22e…` byte-identical and clean on inferswarm00/01/03. Physical
observations exist and are ALL retained unchanged; the campaign
terminal, however, is NOT an ordinary-serving PASS or FAIL. The
retention/derivation correction pass (2026-09-09, no rerun)
reclassified the campaign:

**Terminal: `ISSUE117_ARM_C_EVIDENCE_BLOCKER`** — qualified as a
**post-correctness-bearing methodology / evidence-admissibility
failure**, mechanically derived by
`scripts/issue117_arm_c_blocker_reducer.py` from
[`evidence/arm-c/blocker-reduction.json`](evidence/arm-c/blocker-reduction.json).
Correction /2 (2026-09-09, retention/derivation only) replaced the
earlier post-hoc "direct-6 used an invalid invocation" derivation
with the actual frozen-methodology defect: the frozen comparator's
two arms differed in runtime invocation semantics by design (see
finding 1).

What the frozen pre-execution authority actually establishes
(`pre_execution_inferwarm_sha` = `5e2c83a…`; bound by git blob SHA and
sha256 in
[`evidence/arm-c/pre-execution-authority-audit.json`](evidence/arm-c/pre-execution-authority-audit.json)):

1. **The frozen comparator failed its own comparator-isolation
   requirement (the actual defect, correction /2).** The frozen
   methodology §4 @ `5e2c83a` defines the direct comparator as one
   `generate(session_id=i, prompt_token_ids=<rendered ids>,
   max_new_tokens=8)` per case — a single-shot invocation with one
   prefill per case — while the frozen ordinary path (FreeToken
   producer `924cd22e…`, whose bytes are retained verbatim and
   sha256-pinned under
   [`evidence/arm-c/frozen-freetoken/924cd22e/`](evidence/arm-c/frozen-freetoken/924cd22e/))
   dispatches every `/v1/chat/completions` request through
   `EpochServingController.serve_tokens`: a per-committed-position
   loop that re-feeds the full replay prefix (prompt + committed
   tokens, per `GemmaTokenBoundaryStrategy.replay_input`), invokes the
   runtime with `max_new_tokens=2`, commits only step/token zero, and
   discards the speculative second token. The arms therefore differed
   in **runtime invocation semantics** in addition to differing in
   control-plane routing, violating the frozen "The ONLY intended
   difference is the control-plane path" requirement **by design**.
   The frozen campaign could not establish ordinary-vs-direct serving
   equivalence or semantic failure as designed. The direct arm's
   single-shot invocation is NOT itself the error — it is what the
   frozen methodology told the direct arm to use.
2. **The exact staged driver bytes used by direct-1..6 are
   `unknown / not retained`.** The staged copy on inferswarm01 was
   overwritten in place at 2026-09-09T10:43Z — mechanically placed
   AFTER direct-6 completed (10:28:36Z) and BEFORE direct-7 was
   observed (10:49:28Z) — and committed at `dd4154d` as per-token
   replay-prefill (`max_new_tokens=2`). The direct-6 rows are
   consistent with the single-shot invocation (no replay marker), but
   absence of a marker introduced later cannot alone prove exact
   producer-script identity; the unrecoverability independently
   strengthens the evidence blocker.
3. **The §10 stop-rule ambiguity is reported, not resolved — both
   histories converge on the blocker.** The exact moment at which the
   operator first regarded direct-6 as an invalid comparator is not
   independently retained. If direct-6 was still regarded as valid
   when ordinary-1 ran, the campaign followed the frozen methodology
   but the frozen comparator itself was defective (finding 1). If
   direct-6 had already been regarded as invalid, frozen §10 required
   STOP after its correctness-bearing output (retained timestamps:
   direct-6 10:28 UTC < ordinary-1 10:38 UTC) and ordinary-1
   improperly ran afterward. Both branches derive
   `ISSUE117_ARM_C_EVIDENCE_BLOCKER`; the reducer never needs the
   post-hoc validity judgment to obtain the terminal.
4. **Post-observation reducer weakening reverted; exact-head audit
   fail-closed.** The reducer was changed after physical execution
   (fail-closed invalid-attempt rule weakened to a review list;
   `/srv/models/` tokenizer-metadata exemption added). The blocker
   reducer is bound to the pre-execution methodology, and correction
   /2 closes the exact-head audit loophole: a frozen
   methodology/driver change after the audited head ALWAYS fails, and
   every other post-audit file change must be individually allowlisted
   with its exact sha256 (methodology+reducer, driver+reducer, and
   methodology+driver+reducer combinations all fail).
5. **Four Source-tree metadata reads under the frozen zero-Source
   rule.** The direct window shows four tokenizer-metadata file opens
   under `/srv/models/` (plus one directory stat; zero model-weight
   reads). The frozen §9 rule admits no exemption; the four reads are
   retained and counted, never zeroed. They independently bar PASS. A
   future methodology may pre-declare an immutable-tokenizer-metadata
   exception, but only frozen BEFORE a new correctness-bearing
   campaign — it cannot be backported to this one.

**Disposition of the physical observations (all 11 attempts
retained, none erased; authored validity flags retained verbatim as
historical/post-hoc classification):**

- `armc-direct-6`: correctness-bearing physical observation;
  invocation consistent with the frozen single-shot comparator; exact
  staged driver bytes unknown / not retained; part of the evidence
  that exposes the frozen comparator defect; NOT accepted terminal
  comparator evidence;
- `armc-ordinary-1`: correctness-bearing ordinary-path observation
  (24 cases + fencing, 10:38 UTC, after direct-6 and before the
  replay-prefill rewrite reached a completed direct run); part of the
  frozen-methodology campaign evidence; inadmissible to a semantic
  PASS/FAIL because the comparator methodology was defective;
- `armc-direct-7/8/9` (10:49/10:56/11:09 UTC): post-observation /
  post-methodology-revision diagnostics; inadmissible to the terminal
  campaign;
- the 18/24 ordinary-vs-direct comparison (replay-prefill comparator,
  post-revision) is retained as **diagnostic evidence only**; it does
  NOT establish the terminal Arm-C ordinary-serving result;
- the six regime-4 divergences (rendered prompt 65–67 ids) are
  retained as diagnostic evidence strongly suggesting a real
  multi-chunk/KV nondeterminism defect — a **follow-up hypothesis**,
  not the accepted result of this campaign;
- direct-6 single-shot trajectory, direct-9 replay-prefill trajectory,
  ordinary trajectory, fencing/coordinator/data-path zeros, straces,
  censuses, and the recovered attempt lineage
  ([`evidence/arm-c/attempt-lineage.json`](evidence/arm-c/attempt-lineage.json),
  schema /3: per-attempt timestamps recovered digest-bound from the
  retained execution-session transcript; physical chronology is
  derived only from retained timestamp evidence — direct-6 10:28:36Z
  < ordinary-1 10:38:52Z < direct-7 10:49:28Z < direct-8 10:56:57Z <
  direct-9 11:09:05Z — while the authored logical `order` field is
  retained separately and must not contradict it; unrecoverable
  fields carry explicit `unknown / not retained` markers — including
  the exact driver bytes used by direct-1..6, which were overwritten
  in place and are part of the evidence blocker).

Canonical reducers: `scripts/issue117_arm_c_blocker_reducer.py`
(frozen-evidence terminal derivation, correction /2; 31-control
mutation suite + frozen-source pin suite in
`tests/test_issue117_arm_c_blocker.py`; the ordinary-path invocation
semantics are derived from the sha256-pinned FreeToken bytes by
`scripts/issue117_arm_c_frozen_pins.py`) and
`scripts/issue117_arm_c_evidence.py` (retained-equality derivation;
34-control suite in `tests/test_issue117_arm_c_retention.py`).

Arm D has NOT been executed and remains blocked.

## Non-claims (Arm C)

- Arm C claims NO ordinary-serving semantic PASS or FAIL: the retained
  18/24 comparison used a post-stop, post-freeze replay-prefill
  comparator and is diagnostic only.
- The six regime-4 divergences are diagnostic evidence for a follow-up
  hypothesis (multi-chunk/KV nondeterminism), not an accepted result.
- No Arm-D warm-restart or Arm-E locality claim; Arm D remains blocked.
- No new Arm-C physical campaign is authorized by this record.
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
