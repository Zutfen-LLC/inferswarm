# Issue #284 correction — runner STOP law, observer retention, semantic gate

Parent: #280 (first completed physical campaign), #284 (this correction).
Status: repository implementation + CPU-only validation. **No GPU/model
execution is authorized or performed by this correction.** The prospective
minimal physical rerun (2 launches / 4 requests maximum) requires separate
maintainer authorization after this PR is reviewed and merged.

## Mechanically established root causes

All three were established from retained bytes (staged binaries, retained
server logs, and the pinned public llama.cpp source at `b29c606e`), not from
hypothesis.

### 1. Runner STOP enforcement was acceptance-blind

The recovered #280 runner (session-built `/tmp/i280-campaign.py`, never a
repository artifact) recorded `OK` per request on HTTP completion only. It
never evaluated the frozen task rubric or observer-evidence requirements
between requests, so the campaign ran all 8 launches / 16 requests after the
first baseline response already failed correctness.

### 2. Observer retention: library-TU I280 events were dropped by log-level routing

The staged binaries DO contain every hook (verified: event-name literals
present in the `.o` files, split across MOV immediates; `weight_inventory`,
`graph_begin`, `copy_manifest`, `kv_inventory` all compiled in). The hooks
fired. Their output was silently discarded:

- `common_init()` (common/common.cpp at the pin) installs
  `common_log_default_callback` for BOTH llama and ggml logging
  (`llama_log_set` forwards to `ggml_log_set`).
- That callback maps library `INFO` → `LOG_LEVEL_TRACE` (4)
  (common/log.cpp) and displays only when
  `verbosity <= common_log_verbosity_thold`, default
  `LOG_DEFAULT_LLAMA = LOG_LEVEL_INFO` (3). 4 ≤ 3 is false: dropped.
- The five library producer TUs routed `I280_LOG` through
  `LLAMA_LOG_INFO`/`GGML_LOG_INFO` → all their events were dropped.
- The server TU used `LOG_INF`, which calls `common_log_add` directly at
  INFO — bypassing the callback — so request/batch/sample/response survived.
  This exactly matches the retained logs (only those six event types).

Correction: library TUs now emit at log level NONE
(`LLAMA_LOG`/`GGML_LOG`), which the pinned callback maps to
`LOG_LEVEL_OUTPUT` (0) — always displayed. The server TU is unchanged.
No hooks, synchronization, or semantics were altered; only the five
`#define I280_LOG` sink lines changed.

### 3. Task rubric was formatting-sensitive

The frozen rubric demanded exact JSON-only output. The model returned correct
semantic content wrapped in introductory prose and Markdown fences (and, for
P2, the wrong `service` value). The rubric conflated formatting with content.

## Corrections

1. `scripts/issue280_runner.py` — pure gate engine over an injected executor.
   Every frozen per-request acceptance/STOP condition is evaluated BEFORE any
   subsequent launch/request: semantic task correctness, required observer
   evidence (per arm), peak-RSS retention, available health/resource stop
   inputs. Aborted/failed requests consume their slot; no automatic
   replacement. The matrix is the minimal-rerun contract (R1 baseline A,
   R2 candidate B; cold+warm each; 2 launches / 4 requests).
2. `scripts/issue280_task_check.py` — frozen deterministic semantic checker:
   exactly one three-field JSON object, exactly the frozen expected values
   per prompt (P1 payments/high/resolved, P2 search/low/open); accepts
   fences/prose; rejects wrong values (including P2 `service=search`),
   missing/extra fields, multiple objects, non-string values. Tolerance was
   frozen before any rerun; never tuned from candidate observations.
3. `scripts/issue280_source.py` + `instrumentation/` — the five library-TU
   `I280_LOG` sinks switched from filtered INFO to level-NONE logging.
   Identities re-pinned (patch SHA256, per-TU transformed hashes, full
   transformed Git tree) in `instrumentation/source-identity.json`.
4. Early mechanism-admission gates (issue §4) are enforced by the runner:
   the first baseline request must carry all baseline evidence or the run
   STOPs; the first candidate request must additionally carry the boundary
   transfer records or the remaining matrix is never launched.

## CPU validation performed

- New suites: `test_issue280_runner` (10 tests: immediate STOP after first
  failing baseline; no subsequent launch/request; missing inventory/compute/
  boundary rejection; peak-RSS fail-closed; health stop before next launch;
  aborted-slot consumption; minimal matrix shape),
  `test_issue280_task_check` (14 positive/negative/determinism fixtures,
  including the two verbatim retained physical responses),
  `test_issue280_retention_fix` (pins the corrected sink law AND proves the
  dropped-INFO mechanism from the pinned source bytes).
- Existing `test_issue280_observer` (503-line collector suite) and
  `test_issue280_source` remain green on the corrected transform.
- All six corrected TUs passed `-fsyntax-only` against the pinned source
  (the Vulkan TU against the generated shader header on inferswarm01,
  read-only; the server TU likewise). A syntax check is not a build:
  Vulkan build identity remains NOT_BUILT until the separately authorized
  rerun rebuilds.
- Retained historical evidence untouched byte-for-byte.

## Review round 2 (PR #285 comment 6035951310, P1)

The runner's mechanism admission was presence-only: `observer_events`
name-subset membership decided candidate acceptance. A stream carrying every
expected event name could still be causally or physically wrong (wrong BDF,
request/graph mismatch, no per-die completed compute, invalid boundary
attribution).

Correction (additive, no second validator):

- `scripts/issue280_observer.py` gains a `PHYSICAL_280` contract kind and
  `physical_280_contracts()` (frozen two-die candidate / single-die baseline
  identities from the run plan) plus `validate_admission()`, a structured
  PASS/FAIL verdict wrapper over the SAME `collect()` substantive laws:
  two distinct bound BDFs, request/graph correlation, declared layer/weight
  ownership (R3-2 cross-check), completed nonempty compute on both dies,
  boundary pre-execution manifest identity, shape/stride logical-byte law,
  occurrence multiplicity, cross-die src/dst binding, and host-staging leg
  reconciliation. CPU fixture behavior and tests are unchanged.
- `scripts/issue280_runner.py` admission now consumes that verdict from the
  retained raw request bytes (`observer_raw`); missing bytes fail closed.
  Event-name presence is diagnostic metadata only. Candidate cold must PASS
  observer admission before candidate warm executes; any failure is terminal
  STOP with candidate warm `not_attempted`, no replacement, no rerun.
- `tests/test_issue280_admission.py` (focused adversarial cases):
  A presence-only false positive (wrong BDF; also request-identity mismatch),
  B missing per-die completed compute, C invalid boundary proof (non-cross-die
  src/dst, wrong logical bytes, absent boundary chain) — all STOP before
  candidate warm — and D a valid two-die stream that passes and permits
  candidate warm. `tests/test_issue280_runner.py` fixtures now drive real
  retained-byte streams instead of name sets.

No already-accepted surface was reopened: fail-fast ordering, semantic
checker, retention fix, source identities, aborted-slot consumption,
2-launch/4-request matrix, peak-RSS gate, and health handling are unchanged.
No GPU/model execution occurred; the physical rerun remains separately
authorized. Health/resource gating was NOT broadened (round-2 scope was the
observer admission defect only).

## Review round 3 (PR #285: PHYSICAL_280 placement contract incomplete)

The round-2 placement contract admitted silently reduced placements.
`physical_280_contracts()["A"]` assigned only blocks 0–18 to baseline die A,
and no arm required the frozen output-layer ownership: a baseline stream
carrying only blocks 0–18 (missing 19–35 and the output tensor) PASSED
observer admission, and a candidate stream with blocks 0–35 but no proven
output ownership also PASSED. Both false positives were reproduced RED at
reviewed head `4de6581` before any production edit.

Correction (additive, same single validator):

- `physical_280_contracts()` now encodes the exact frozen #280 arm
  placements from the run plan: **Baseline A** = die `0000:07:00.0` owning
  ALL model block layers 0–35 plus the required output tensor (`output.
  weight`) — the full intended single-die block/output offload, no split;
  **Candidate B** = die `0000:07:00.0` owning blocks 0–18, die
  `0000:0b:00.0` owning blocks 19–35 plus the required output tensor.
- `collect()` (the same substantive law, not a second validator) now
  requires every frozen block-layer ownership element and every
  `required_tensors` element to be represented by admissible named weight
  inventory on exactly its contract die, evaluated after deferred
  backend-name resolution. Missing elements ("silent placement reduction")
  and elements bound to the wrong contract die, CPU, or an alien backend all
  fail closed. CPU_FIXTURE semantics are unchanged (the law is keyed on
  contract-declared required placement; the synthetic fixture contract
  declares none beyond its layers, which its two-die fixtures already
  carry).
- The synthetic fixtures model the real frozen placement: the baseline
  fixture emits blocks 0–35 plus the output tensor on die A; the candidate
  fixture emits 0–18 on A and 19–35 plus output on B. The contract was NOT
  reduced to the old fixtures.
- Adversarial additions: baseline missing any upper block (0–k, k < 35)
  rejected; baseline output missing / on an alien backend (`0000:0c:00.0`,
  `CPU`) rejected; candidate output missing / owned by die A rejected;
  correct full baseline and complete candidate split (with candidate warm
  still permitted) PASS; all round-2 wrong-BDF, request-mismatch,
  missing-die-compute, wrong-boundary-src/dst, wrong-byte-law,
  missing-boundary and no-retained-bytes cases remain fail-closed.

Blocks 0–18 on die A alone is the CANDIDATE half-split, never the baseline
placement; no statement to that effect remains in this correction's law or
status text.


## Review round 4 (PR #285: KV/mutable-state ownership not mechanically required)

Issue #284 requires admitted real-run evidence to include KV/mutable-state
inventory/ownership where applicable, and frozen #280 authority requires each
candidate die to own its declared layers/KV. The collector already supported
this law — per-die `placement[die]["kv_bytes"]` under
`contract["placement"]["required_categories"]` with the existing
`required category kv_cache is not declared on every die` fail-closed check —
but `physical_280_contracts()` declared no placement requirement, so
PHYSICAL_280 admission never activated it.

Reproduced RED at reviewed head `8365965` before any production edit:

- a candidate B stream with valid full block/output placement, valid both-die
  compute and boundary proof, but `kv_inventory` bound to die A only
  (per-die KV bytes: A=128, B=0) PASSED with the `kv_inventory` event name
  still present — no proven candidate-die-B KV ownership was required;
- a candidate with no KV inventory at all PASSED;
- a baseline A stream with no KV inventory also PASSED (pinned separately).

Correction (additive, smallest, same single validator):

- `physical_280_contracts()` now declares
  `placement.required_categories = ["kv_cache"]` on both arms. This activates
  the collector's existing per-die placement law for the physical contracts:
  **Candidate B** requires nonzero admissible KV inventory on BOTH frozen
  V340L dies; **Baseline A** requires it on its sole die.
- No second validator was added; the declaration reuses the exact existing
  `required_categories` mechanism (`collect()`, unchanged).
- CPU_FIXTURE behavior is unchanged: the synthetic fixture contract declares
  no required placement categories, exactly as before.

Adversarial additions (`tests/test_issue280_admission.py::KVOwnershipTests`):
candidate KV only on die A fails; only on die B fails; absent entirely fails;
correct KV ownership on both candidate dies passes; baseline without KV
fails; correct baseline KV on die A passes; `kv_inventory` event-name
completeness cannot override missing per-die KV ownership (the name stays
present while ownership is absent and the verdict still fails); candidate
warm remains unreachable after a KV-admission failure (runner STOPs with
`observer admission failure` naming `kv_cache`, candidate warm
`not_attempted`). All round-2 and round-3 adversarial cases remain
fail-closed and unchanged.
