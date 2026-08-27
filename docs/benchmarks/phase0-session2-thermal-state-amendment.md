# Phase-0 Session-2 thermal-state amendment

```
Status: Binding Phase-0 methodology amendment
Recorded after P0-E Session 1 completed and before P0-F Session 2 began.
```

## What changes

The Phase-1 success-criteria document currently says that Phase-0 Session 2 runs on a
"different day and thermal state" with the order reversed. For P0-F, the calendar-day
requirement is replaced by the causally relevant requirement: **Session 2 must begin from an
independently cooled, thermally reset host/GPU state, and the B1-B5 traversal must be
reversed.**

A 24-hour separation is not required. The second session may begin on the same calendar day
once GPU, GPU-memory, CPU, and host temperatures have returned to their normal idle range and
are no longer carrying material heat soak from Session 1.

The operator records that thermal reset was observed before starting Session 2. The normal
run artifact continues to record the hardware/software provenance available to the harness.

## What does not change

This amendment changes **no performance decision rule and no measured-workload parameter**.
P0-F still uses:

- the same physical RTX 3060;
- the same FreeToken runtime commit used for the canonical campaign;
- the same pinned Qwen3.6-35B-A3B-NVFP4 model revision;
- the same frozen W1-W4 manifest;
- `--memory-ratio 0.85`;
- `--kv-reserve-tokens 17075`;
- a fresh session-level NVFP4 `ft bench bw` profile;
- all five B1-B5 configurations;
- 2 warmups + 10 measured generations per arm/workload block;
- no selective deletion or early stopping;
- the reversed Session-2 traversal, B5 -> B4 -> B3 -> B2 -> B1;
- the same primary statistics, variance treatment, validity rules, and
  `CANONICAL_PERFORMANCE_BASELINE` selection rule.

## Why this amendment is made

The original "different day" wording used calendar separation as a proxy for an independent
thermal condition. After P0-E completed, the measurement host returned to its normal idle
GPU, GPU-memory, and CPU temperatures well before 24 hours had elapsed. Calendar time itself
has no causal effect on the benchmark once the machine has thermally reset.

Keeping an arbitrary 24-hour delay would add no experimental control beyond the actual
thermal-state requirement. This amendment therefore replaces the proxy with the condition it
was intended to enforce.

## Anti-goalpost statement

P0-E Session 1 already exists at the time of this amendment. This change cannot alter any
Session-1 observation, does not add or remove an arm, does not alter any threshold or statistic,
and does not select or favor a baseline candidate. Under the previous rule, P0-F would simply
have been delayed until the next calendar day; its configuration, reversed order, measurements,
and eventual interpretation would otherwise be identical.

No P0-F measurement may begin until this amendment is merged.
