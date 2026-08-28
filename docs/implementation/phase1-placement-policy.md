# Phase-1 placement policy — frozen from P0-I evidence

```
Status: PREDECLARED / FROZEN BEFORE PHASE-1 PERFORMANCE
Source issue: #3 — P0-I routing/residency evidence
Target issue: #4 — resident remote expert execution on a second RTX 3060
Policy id: phase1-qwen36-placement-v1
```

This document fixes how the first two-GPU Phase-1 expert placement is derived. It exists so
placement cannot be tuned after candidate throughput is visible.

It is subordinate to [`phase1-poc-success-criteria.md`](../phase1-poc-success-criteria.md),
[`BENCHMARKING.md`](../../BENCHMARKING.md), and issue #4. Changing this policy after the first
Phase-1 candidate performance observation requires an explicit methodology-change PR that
retains the previous placement/verdict path.

## 1. Immutable source evidence

The placement is derived only from the valid canonical P0-I trace:

- model: `nvidia/Qwen3.6-35B-A3B-NVFP4`;
- model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`;
- FreeToken source commit: `a42c03ce0233451df699cfd6c4e09573751c067f`;
- InferSwarm methodology commit: `0807842ce4cfd587ec77c5605cb61ed955dc3a11`;
- frozen workload manifest SHA-256:
  `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a`;
- canonical `exact-routing.jsonl` SHA-256:
  `4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f`;
- canonical `cache-pressure.jsonl` SHA-256:
  `f02d96a079a6af94b3fec9d2c571322a1274cd408a3a9ff2ef162f538babab3a`;
- canonical `run.json` SHA-256:
  `1ecd14c8c157eb6cde62f8514b8f2af82a36dfe69e3a7241f5be6c9908e539dc`.

No Phase-1 candidate output or throughput is an input to placement.

## 2. Geometry fixed by Phase 0

P0-I measured:

- 40 MoE layers;
- 256 routed experts/layer;
- 10,240 `(layer, expert)` slots total;
- GPU-0 auto cache `A = 3,774` slots on the Phase-0 RTX 3060;
- 3,774 slots = 36.86% raw expert-slot coverage;
- weighted measured miss rate at that capacity = 14.71%.

The accepted P0-H reference reported 512 NVFP4 expert slots occupying 909,115,392 bytes, or
**1,775,616 bytes/slot** for this checkpoint/layout. That byte figure is used only to convert
the predeclared remote byte cap into a slot count.

## 3. Remote resident budget

The first Phase-1 candidate has a fixed **maximum GPU-1 expert-bank budget of 9 GiB**:

```
remote_budget_bytes = 9 * 1024^3 = 9,663,676,416 bytes
bytes_per_slot       = 1,775,616 bytes
remote_slots         = floor(remote_budget_bytes / bytes_per_slot)
                     = 5,442 slots
resident_bytes       = 5,442 * 1,775,616
                     = 9,662,902,272 bytes
```

So the canonical placement contains **exactly 5,442 GPU-1 expert slots**, consuming
9,662,902,272 expert-bank bytes (8.9993 GiB), if the Phase-1 secondary-device substrate can
allocate that bank.

This leaves approximately 3 GiB of a nominal 12-GB RTX 3060 outside the expert-bank budget
for CUDA context, execution workspace, activation/partial buffers, and implementation
headroom. The P1 hardware probe must prove the allocation on the actual secondary card
before decode work proceeds.

**No silent size fallback.** If 5,442 slots cannot be allocated, the canonical Phase-1
candidate is blocked. Do not reduce the budget until it fits and then call that the same
experiment. A smaller placement requires a pre-performance methodology update recording the
new byte/slot budget and why the original predeclared geometry was infeasible.

## 4. Workload-balanced route score

Raw route counts would overweight W1/W2 simply because their frozen completions are longer.
The Phase-1 benchmark treats W1-W4 as distinct workload classes, so placement uses an
equal-class normalized score.

For every `(layer, expert)` slot `s` and class `c`:

```
p_c(s) = measured selections of s in class c
         ------------------------------------
         total measured selections in class c

score(s) = mean(p_W1(s), p_W2(s), p_W3(s), p_W4(s))
```

All ten measured exact-trace repetitions per class contribute. Discarded warmups do not.

Deterministic ordering:

1. `score(s)` descending;
2. total raw measured selections across W1-W4 descending;
3. flat expert id `layer * 256 + expert` ascending.

There is no random tie break and no manual expert substitution.

## 5. Two derived placements

The publication extractor emits both placements from the same score ordering.

### A. Global-hot diagnostic placement

`global_hot_5442` = the first 5,442 slots in workload-balanced score order.

Purpose: describe what a pure frequency-optimal remote bank would contain and measure its
trace coverage. It is a **diagnostic placement only** for Phase 1 v1. It is not the canonical
performance candidate because it intentionally overlaps the experts most likely to be cheap
GPU-0-local service.

### B. Canonical complementary placement

The canonical Phase-1 v1 placement is `complement_5442`:

1. define `gpu0_primary_proxy` as the first **3,774** slots in the same workload-balanced
   score order — matching GPU 0's measured Phase-0 expert-slot capacity;
2. remove those 3,774 slots from the ranked list;
3. take the next **5,442** unique slots for GPU 1.

This produces a static 9,216-slot primary-proxy + secondary complement, exactly **90.00% of
all 10,240 expert identities by capacity**, leaving 1,024 identities to the existing host-backed
path in this static geometry.

The 3,774-slot primary set is explicitly a **placement proxy**, not a claim that FreeToken's
runtime LRU literally holds those exact experts. P0-I measured temporal locality strong enough
for LRU hit rate to differ from static frequency coverage. The complement rule is chosen
because Phase 1's hypothesis is to add useful resident capacity without deliberately
replicating the hottest primary-capacity proxy on both GPUs.

GPU 0 itself remains on the existing FreeToken path. Phase 1 v1 does not replace GPU 0's LRU
with this static proxy; the proxy exists only to derive a non-overlapping GPU-1 set before
candidate performance is known.

## 6. Required placement artifact

The canonical generated artifact must contain at least:

- schema `inferswarm.phase1.placement/1`;
- policy id `phase1-qwen36-placement-v1`;
- model repository/revision;
- source P0-I artifact SHA-256s;
- source workload manifest SHA-256;
- score definition and tie-break rule;
- `bytes_per_slot = 1775616`;
- `remote_budget_bytes = 9663676416`;
- `remote_slots = 5442`;
- `remote_resident_bytes = 9662902272`;
- `gpu0_primary_proxy_slots = 3774`;
- exact `gpu0_primary_proxy` expert IDs per layer;
- exact `global_hot_5442` expert IDs per layer;
- exact canonical `complement_5442` expert IDs per layer;
- measured/calculated trace-coverage summaries for all three sets, globally and per W1-W4;
- deterministic artifact SHA-256 recorded beside the artifact.

The Phase-1 runtime consumes only the canonical `complement_5442` set unless a separate
predeclared diagnostic explicitly requests the global-hot set.

## 7. Publication / validation rules

The derivation script must first verify the canonical raw-source hashes above. It then emits:

1. a sanitized full P0-I routing histogram containing counts only — no prompt/output text or
   host-local paths;
2. the deterministic Phase-1 placement artifact;
3. SHA-256 values for both generated files.

Before merge/publication, mechanically verify:

- 40 layers and 256 experts/layer;
- all W1-W4 measured repetitions are present;
- no duplicate expert IDs within a placement;
- `gpu0_primary_proxy` count = 3,774;
- `global_hot_5442` count = 5,442;
- canonical `complement_5442` count = 5,442;
- canonical complement intersection with primary proxy = 0;
- all identities are within layer `[0,39]`, expert `[0,255]`;
- resident-byte arithmetic matches this document;
- source hashes match the canonical P0-I run.

## 8. What this policy does and does not claim

**[MEASURED]** P0-I proves substantial routing/temporal locality and a non-zero miss burden at
GPU 0's maximum measured cache.

**[CALCULATED]** The workload-balanced placements are deterministic transformations of those
measured exact-route counts.

**[SPEC]** The complementary 5,442-slot bank will improve end-to-end inference. That is the
Phase-1 hypothesis, not a conclusion of this document. GPU0→GPU1 activation cost, remote
expert execution latency, return/combine cost, synchronization, peer-access topology, and
possible loss of cheap GPU-0 hits remain to be measured.

No placement may be changed in response to Phase-1 throughput without creating a new,
explicitly versioned experiment.
