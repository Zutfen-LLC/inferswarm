# Phase 1 two-GPU POC implementation plan

```
Status: Implementation plan
Canonical issue: #4 — Prototype resident remote expert execution on a second RTX 3060
Implementation repository: Zutfen-LLC/FreeToken, branch family inferswarm / poc/*
```

This document turns ROADMAP Phase 1 into an ordered engineering plan. It does
not change the experiment, its thresholds, or its architecture. If this plan
conflicts with [the Phase-1 success criteria](../phase1-poc-success-criteria.md),
[BENCHMARKING.md](../../BENCHMARKING.md), an accepted ADR, or issue #4, those
sources win.

The question remains deliberately narrow:

> Can a subset of Qwen3.6 routed experts stay resident on a second RTX 3060,
> execute there, and improve end-to-end inference relative to the best
> existing single-RTX-3060 FreeToken path?

Phase 1 is a proof of mechanism, not the point where InferSwarm becomes a
fully generalized fabric.

## 1. Entry gates

Canonical Phase-1 measurement must not begin until Phase 0 has produced all
of the evidence the candidate depends on:

1. issue #2 has produced a valid `CANONICAL_PERFORMANCE_BASELINE` on GPU 0;
2. the exact `nvidia/Qwen3.6-35B-A3B-NVFP4` revision is pinned;
3. `CORRECTNESS_REFERENCE` exists and passes its self-consistency check.
   Since the pre-re-evaluation v2 amendment, the Phase-1 comparator is the
   matched-state `PHASE1_CORRECTNESS_REFERENCE_V2` — the candidate's GPU0
   serving configuration with the InferSwarm treatment removed — defined in
   [`phase1-correctness-reference-methodology-correction-v2.md`](phase1-correctness-reference-methodology-correction-v2.md).
   The P0-H R512 configuration remains historical Phase-0 evidence and is no
   longer the Phase-1 numerical reference;
4. issue #3 has produced real routing/cache traces for the frozen workload
   set, including enough hit/miss information to choose a placement without
   guessing;
5. two physical RTX 3060 12 GB devices are available in the same host, with
   UUIDs and PCIe topology recorded;
6. the FreeToken commit used for the candidate is recorded, and any change
   that would require the Phase-0 baseline to be re-run is handled before the
   candidate campaign.

Implementation may start before every Phase-0 result exists, but no canonical
candidate result may be collected before these gates are satisfied.

## 2. Scope: build only the mechanism Phase 1 needs

The Phase-1 implementation is an **in-process, same-host, two-CUDA-device
prototype** inside the FreeToken fork.

It is intentionally *not*:

- a network worker;
- an RPC protocol;
- a generic `FabricWorker` implementation;
- a generalized planner/scheduler;
- multi-secondary-GPU fan-out;
- dynamic promotion/demotion or expert replication;
- a new model loader or Qwen port;
- a multi-precision experiment.

Those belong to later roadmap phases. In particular, the conceptual
`FabricWorker` / capability contract remains unimplemented until Phase 5 has
evidence telling us what it actually needs.

### Decode first; keep prefill on the existing path

The minimum valid Phase-1 mechanism distributes **decode-time routed-expert
execution**. Prefill may remain on FreeToken's existing GPU-0 path for the
first candidate. This is deliberate:

- the Phase-1 mechanism gates measure remote participation at decode time;
- the experiment still measures TTFT and prefill end-to-end, so leaving
  prefill local is not hidden or free;
- remote prefill would add a second large workstream before we know whether
  resident remote decode is useful at all.

If later evidence identifies remote prefill as the bounded next experiment,
it can be added in a subsequent POC PR. It is not required to establish the
first valid resident-remote-execution candidate.

## 3. Reuse the narrow seams FreeToken already has

The current FreeToken `inferswarm` branch already separates routing/data
movement from expert kernel dispatch well enough for the POC:

- `python/freetoken/engine/engine.py::_init_offload_moe_cache` owns expert-bank
  loading, cache construction, resolved backend state, and attachment of the
  cache to MoE layers.
- `python/freetoken/layers/moe.py::_decode_routed` is the decode seam after
  top-k routing and before expert execution.
- the existing hybrid path already demonstrates the right semantic pattern:
  partition routes, execute each route exactly once on one destination,
  compute partial outputs, and add the partials.
- `python/freetoken/layers/moe.py::_expert_gemm` already dispatches the real
  production kernels from bank views + row indices. The remote executor should
  call the same kernel family rather than inventing a second numerical path.
- `python/freetoken/moe/offload_cache.py` already defines the bank schemas,
  bytes-per-expert arithmetic, GPU cache views, and device-side routing/cache
  counters the Phase-1 instrumentation can mirror.
- the Phase-0 instrumentation endpoint/runtime report should be extended,
  not replaced, for secondary-GPU provenance and mechanism counters.

The first implementation should preserve these seams rather than refactor
FreeToken around an imagined final architecture.

## 4. Candidate execution shape

For each MoE decode layer:

```
router on GPU 0
      |
      +--> GPU-0 / existing FreeToken routes ----+
      |                                           |
      +--> GPU-1-resident routes                  |
             |                                    |
             +-- one activation/routing dispatch |
             +-- selected experts execute GPU 1  |
             +-- one combined partial returns ---+
                                                  |
                                              add partials
                                                  |
                                              layer output
```

The binding rules are:

1. **One destination dispatch per layer/step.** All GPU-1-selected experts for
   the layer are represented in one fixed-shape activation/routing dispatch,
   not one call or copy per expert.
2. **Weights stay resident.** GPU 1 receives its expert banks at startup or
   placement initialization. Decode never copies a remote expert's weights
   from host RAM or GPU 0 as part of servicing that expert.
3. **Each route executes exactly once.** A route assigned to GPU 1 is excluded
   from GPU-0/CPU computation. A route not assigned to GPU 1 follows the
   existing FreeToken path unchanged.
4. **No silent fallback.** A GPU-1-assigned route that cannot execute is an
   explicit recorded failure. It is never quietly served on GPU 0 or CPU.
5. **The returned object is a partial MoE output**, already accumulated across
   all GPU-1-selected experts for that destination. GPU 0 combines that
   partial with its local partial once.

### Suggested POC-only runtime controls

Use downstream-only controls rather than pretending this is already a stable
FreeToken interface. Exact spelling may change in implementation, but the
candidate needs the equivalent of:

```
--inferswarm-secondary-gpu <GPU UUID>
--inferswarm-placement <frozen placement artifact>
```

The secondary UUID is mandatory for a candidate run and must differ from GPU
0. Canonical runs must never use an implicit `cuda:1` assumption.

A diagnostic overlap-disable knob is acceptable for decomposition work, but
its state must be recorded and the canonical candidate configuration frozen
before measurement.

## 5. Resident secondary expert bank

Add a small POC-specific secondary-GPU bank/executor under `freetoken.moe`
(or an equivalently narrow location). Do **not** introduce the final
`FabricWorker` abstraction yet.

The resident bank should:

- allocate only on the explicitly selected GPU-1 device;
- use the same resolved NVFP4 bank layout/kernel family required by the
  candidate and `CORRECTNESS_REFERENCE`;
- copy the frozen expert subset from the existing host expert banks during
  startup/initialization;
- retain a deterministic `(layer_id, expert_id) -> remote_slot` mapping;
- expose immutable bank views for the production `_expert_gemm` path;
- record exact resident slots and bytes per layer/device;
- count startup weight bytes separately from steady-state traffic;
- perform **zero remote-expert weight loads during steady-state decode**.

Do not teach the ordinary GPU-0 `OffloadMoeCache` to become a multi-device
planner. A small secondary-resident bank is the narrower experiment and is
much easier to remove or extract later.

## 6. Placement: static, evidence-derived, and frozen

Phase 1 does not need a dynamic placement scheduler.

The canonical pre-performance candidate is
`phase1-qwen36-placement-v2` / `coverage_constrained_complement_5442`,
SHA-256
`2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`.
It supersedes v1 for the candidate while retaining v1 replay and historical
evidence. See the
[`v2 methodology correction`](phase1-placement-methodology-correction-v2.md).
The correction changes only the static GPU-1 identity set; route ownership,
dispatch, combine, transport, cache, prefill, and all gates remain unchanged.

Use Phase-0 routing/cache evidence to generate one deterministic placement
artifact before the first candidate benchmark. Prefer experts whose Phase-0
service was non-local on GPU 0 rather than merely the most frequently selected
experts; the hypothesis is that L1 resident execution can replace L2
host/CPU/offload service, not that L1 should displace cheap L0 cache hits.

The placement artifact must contain enough provenance to reproduce the
selection, including at least:

- schema/version;
- model repository and exact revision;
- expert quantization / resolved remote kernel layout;
- source Phase-0 result/trace identity;
- placement algorithm/version and deterministic tie-break rule;
- target remote resident byte/slot budget;
- exact remote expert IDs per layer;
- artifact SHA-256.

Freeze and hash-pin this artifact **before** the candidate performance
campaign. Do not change placement after seeing candidate throughput and call
the new run the same experiment.

The pre-measurement placement should be checked against the frozen Phase-0
traces for the mechanism-gate geometry only: enough GPU-1 resident bytes to
make F1 possible and enough selected touches to make F2 plausible. This is a
mechanism-validity check, not a predicted performance claim.

## 7. Decode partition and combine

Implement the remote branch at the post-router `_decode_routed` seam.

For each layer/step:

1. keep the raw routed expert IDs;
2. look up the frozen remote-slot mapping;
3. produce a remote mask and remote slot IDs on device;
4. ensure the existing GPU-0 path sees only the routes it owns (remote routes
   must not trigger GPU-0 expert fetches merely to be zero-weighted later);
5. construct one fixed-shape remote routing payload containing the activation,
   remote slot IDs, and routing weights/mask;
6. execute the remote subset on GPU 1 with the same production expert kernel
   family;
7. return one partial `[tokens, hidden]` result to GPU 0;
8. add local and remote partials.

The existing hybrid CPU/GPU split is the semantic precedent: masked routes,
one owner per route, independent partials, one final add. Reuse that logic
where practical rather than creating parallel routing semantics.

### Correctness-first implementation

The first working version may serialize local and remote work. Its purpose is
to pass C1/C2/C4 and prove route ownership/placement. Do not optimize a path
whose output and accounting have not yet been proven correct.

Once the serialized path is correct, move remote work to a dedicated GPU-1
CUDA stream and overlap it with GPU-0 expert service where the transport and
CUDA synchronization primitives permit it:

```
GPU 0 router
  -> dispatch activation/routing to GPU 1
  -> GPU 0 local expert service       || GPU 1 remote expert service
  -> return remote partial
  -> synchronization boundary
  -> combine
```

Record whether direct peer access is available and the actual transfer path.
Do not assume P2P from SKU names. A startup probe should record GPU UUIDs,
`can_device_access_peer`/equivalent capability, PCIe topology, and the
transport path the candidate actually uses.

## 8. CUDA graphs

Cross-device work inside FreeToken's captured decode graphs has no established
precedent. The first valid candidate may therefore disable CUDA graph capture
for the affected path.

Rules:

- graph state is explicit provenance;
- any performance cost from disabling capture remains inside the candidate's
  end-to-end result;
- do not disable graphs on the baseline merely to make the comparison look
  cleaner;
- only invest in cross-device graph capture before the first verdict if it is
  required for correctness/mechanism validity;
- otherwise, graph capture is a bounded follow-up optimization only if the
  measured decomposition supports an ITERATE case.

## 9. Instrument the mechanism before benchmarking performance

The candidate is not valid evidence unless the Phase-1 mechanism gates can be
computed directly from runtime records.

Extend FreeToken instrumentation with at least:

### Placement / residency

- GPU-0 and GPU-1 UUID/name/VRAM identity;
- remote resident slots and bytes, total and per layer;
- placement artifact SHA;
- resolved remote quant/kernel backend;
- cross-checkable GPU memory observations.

### Route ownership (per workload class/session)

The four F6 counters must remain distinct:

```
selected_for_gpu1
executed_on_gpu1
explicit_failure
fallback_elsewhere
```

Also record per-device executed-expert totals so C2 and F2 are mechanical.
Counters should accumulate device-side where practical; do not add a host sync
per decode step just for telemetry.

### Dispatch / transport

- remote dispatches per layer/step;
- activation/routing bytes GPU0 -> GPU1;
- partial-result bytes GPU1 -> GPU0;
- startup expert-weight bytes host -> GPU1;
- steady-state expert-weight bytes host -> GPU1;
- peer-access/transport mode;
- explicit remote execution failures.

Steady-state expert-weight traffic must be distinguishable from activation
traffic so F5 cannot be satisfied by ambiguous byte accounting.

### Complete MoE-layer timing (issue #5)

Instrument both candidate and baseline at the same conceptual boundaries:

```
dispatch / non-local service
per-device selected-expert execution
return / combine
complete MoE-layer wall clock
```

The candidate should additionally expose removable prototype costs (for
example disabled-graph or synchronization costs) where they can be measured
without changing semantics. These diagnostics never replace the end-to-end
result.

## 10. PR-sized implementation sequence

Implementation PRs land in `Zutfen-LLC/FreeToken`, link issue #4 (and issue #5
where relevant), branch from `inferswarm`, and merge back to `inferswarm` only
after their own acceptance checks.

### P1 — secondary-device substrate and probe

Deliver:

- explicit secondary GPU UUID resolution/validation;
- two-device topology and peer-access/transport report;
- POC-only configuration plumbing;
- no model-output changes yet.

Gate: one- and two-GPU hosts behave deterministically; wrong/same/missing GPU
selection fails explicitly.

### P2 — resident secondary expert bank + frozen placement loader

Deliver:

- placement-artifact parser/validation;
- secondary resident bank allocation/load at startup;
- exact placement table/byte accounting;
- no decode dispatch yet.

Gate: selected expert banks on GPU 1 reproduce the source bytes/layout; no
steady-state load path exists.

### P3 — correctness-first remote decode path

Deliver:

- post-router route partition;
- exactly-once local/remote ownership;
- one destination-batched remote call per layer/step;
- production NVFP4 kernel execution on GPU 1;
- one partial result returned and combined;
- explicit failure rather than fallback.

Initially serialization is acceptable.

Gate: C1/C2/C4 fixtures pass before performance work proceeds.

### P4 — overlap + mechanism/full-layer instrumentation

Deliver:

- dedicated GPU-1 execution stream and safe synchronization;
- overlap with GPU-0 service where supported;
- F1/F2/F3/F5/F6 counters;
- issue-#5 dispatch/execute/combine timing for candidate and baseline;
- runtime/instrumentation report extensions.

Gate: a non-canonical two-GPU smoke passes every invalidating mechanism gate
and correctness gate. F3 should pass for the intended final shape; if it does
not, the run may only support the criteria's bounded ITERATE path.

### P5 — Phase-1 campaign runner

Reuse the Phase-0 harness's provenance, workload, repetition, statistics, and
artifact machinery rather than creating a second benchmark philosophy.

Deliver:

- candidate arm with all held constants enforced;
- same frozen W1-W4 fixtures and output lengths;
- two-session protocol and no early stopping;
- automatic mechanism/correctness evaluation before performance verdicts;
- complete raw observations plus summary artifacts;
- no code that silently selects a GO/NO-GO rule different from the canonical
  criteria.

Gate: dry-run/provenance validation can prove the candidate and baseline are
comparable before any expensive campaign starts.

### P6 — canonical evidence and report

After P1-P5 are merged and Phase-0 entry gates are satisfied:

1. generate/freeze the placement artifact from Phase-0 evidence;
2. run non-canonical hardware smoke;
3. run C1-C4 correctness gates;
4. run the complete canonical two-session candidate campaign;
5. commit measured evidence/results to InferSwarm under the benchmark-results
   structure;
6. apply the existing GO / ITERATE / NO-GO / INVALID criteria without
   changing them;
7. complete issue #5's full-layer evidence and issue #10's Phase-1 report.

## 11. Test strategy

Every POC PR should add ordinary unit/regression tests that run without two
physical GPUs where possible, plus narrowly gated real multi-GPU tests.

Minimum coverage:

- placement schema, hashing, model/revision/backend mismatch refusal;
- deterministic remote-slot mapping;
- route partition: local-only, remote-only, mixed, no-remote-selected;
- each route executes exactly once;
- remote-assigned failure never falls back silently;
- one dispatch for multiple remote selected experts in the same layer;
- resident bank byte/layout equality against source banks;
- startup-vs-steady-state weight-byte accounting;
- mechanism-counter arithmetic and F1-F6 evaluation;
- combined output vs. a same-kernel single-device fixture;
- two-device integration test gated on `torch.cuda.device_count() >= 2`;
- current one-GPU FreeToken behavior unchanged when no InferSwarm POC flags
  are supplied.

The actual RTX-3060 pair remains the authority for the hardware-dependent
path; mocked CUDA tests cannot certify Phase 1.

## 12. Stop / change rules

- If an invalidating F gate fails, fix the mechanism before interpreting any
  performance number.
- If C1-C4 fail, discard performance data from that build and re-run after the
  correctness fix as required by the criteria.
- Do not add multi-GPU scaling, networking, dynamic placement, remote prefill,
  or generic worker abstractions merely because the code is nearby.
- Do not optimize after seeing a canonical result and reuse the same campaign
  identity. A changed candidate is a new measured build.
- If the valid Phase-1 result is NO-GO, later distributed phases are
  reconsidered rather than executed on momentum.
- If the result is ITERATE, the next PR must target the single named,
  measured, bounded bottleneck required by the success criteria.
- Only a Phase-1 verdict plus later roadmap evidence authorizes extraction of
  a generalized runtime into the InferSwarm repository.

## 13. Definition of implementation-complete

Implementation is ready for the canonical Phase-1 campaign when all of the
following are true:

- two RTX 3060 UUIDs are explicitly bound and recorded;
- the placement artifact is frozen and hash-pinned;
- GPU 1 contains a verified resident expert subset and no steady-state weight
  streaming services those routes;
- route ownership is exact and silent fallback is impossible;
- one destination-batched dispatch serves all GPU-1-selected experts for a
  layer/step;
- local + remote combine passes the predeclared correctness gates;
- F1-F6 and issue-#5 timing evidence are directly observable from runtime
  records;
- candidate graph/transport/overlap state is explicit provenance;
- the benchmark runner enforces the same workload/repetition/held-constant
  contract as Phase 0;
- one-GPU FreeToken behavior remains unchanged when the POC is disabled.

At that point the next step is measurement, not more architecture.
