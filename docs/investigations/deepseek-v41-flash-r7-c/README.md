# R7-C — DeepSeek V4.1 Flash current-fleet physical feasibility

Status: COMPLETE — bounded capacity prerequisite. This additive R7-C bundle
consumes R7-A/R7-B byte-for-byte and stops before model-state acquisition.

## Authority

- Starting reconciled main: `fe690249873a9bf7ca19d788a2fab5e580473394`.
- Frozen producer head before physical collection: `e35217553385a56ef3864c6391a3002457049c95`.
- R7-A: merge `7417c2f58a63d4da854ff399ba6fea5bd722da83`, terminal
  `R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE`.
- R7-B: merge `54d36cb9d8a4c0603abeb18968a8ffb7b52ca10e`, terminal
  `R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY`.
- Official subject: `deepseek-ai/DeepSeek-V4.1-Flash` at
  `dba1be0a40aa45a94ad051997016db3960a90277`; 48 official sharded
  safetensors, with no conversion authority.
- Runtime: vLLM `0eae9acd4d01574e12d4ecf6a0229813f7fdb799`.
- Strategy: the accepted `contiguous_stage` subject with fixed cut 20:
  stage A `[0,20)`, stage B `[20,40)`, no cross-stage cache dependency.

The authority's mechanical post-R7-B audit covers 2,370 changed paths from the
R7-B merge through reconciled main: 4 campaign-gate/CI paths, 2,357 separate
V340L Vulkan/hardware paths, and 9 other documentation/test paths. It finds no
change to R7-A census authority, R7-B vLLM authority, or the selected R7-B
strategy.

## Derived text-only stage contract

| Stage | Tensor count | Shards touched | Logical-required parameter lower bound |
| --- | ---: | ---: | ---: |
| A `[0,20)` plus embeddings | 46,717 | 23 | 352,235,502,576 bytes |
| B `[20,40)` plus norm/head | 46,701 | 21 | 149,147,108,832 bytes |

These are exact official tensor byte sums derived from the retained R7-A header
census. They are lower bounds for device-resident immutable parameters under
the exact no-conversion/no-offload subject. They are not relabeled as host
staging, KV/cache, allocator/workspace, or boundary-transfer measurements.
Those runtime terms remain unknown or prospectively measurable because Phase 2
stopped the campaign.

## Fresh fleet census and legal placement

The frozen collector was run read-only against all current NVIDIA candidates.
`inferswarm01` was reachable and exposed two idle RTX 3060 resources with
12,485,394,432 and 12,487,491,584 bytes available. `inferswarm03` was reachable
and exposed two RTX 3060 resources with 12,341,739,520 bytes free each, but
both carried visible 184-MiB foreign compute processes and were excluded from
available placement. `inferswarm02` and `inferswarm04` each timed out during the
frozen SSH probe and are retained as unavailable, zero-capacity boundaries; they
were not silently omitted or counted from old inventory.

No individual compatible, currently available resource satisfies either stage
lower bound. The smallest per-resource deficits are 339,748,010,992 bytes for
stage A and 136,659,617,248 bytes for stage B. Aggregate VRAM was never used as
an alternative placement rule.

## Terminal

`R7C_CURRENT_FLEET_CAPACITY_PREREQUISITE`

Required successor prerequisite: a compatible single-resource capacity path for
each exact R7-B contiguous stage, without an alternate cut, tensor parallelism,
CPU/disk offload, representation conversion, or hybrid execution.

The reduction stopped at Phase 2. No official checkpoint body bytes were
acquired; no model runtime initialized; no tensor sentinel, full-model forward
pass, benchmark, serving run, AMD/Vulkan path, or alternate placement mechanism
was executed.

## Controls and scope

The committed reducer/tests fail closed on mutated R7-A/R7-B authority, altered
cut, incomplete candidate-host set, stale fleet census, missing foreign-process
receipts, foreign-process availability substitution, aggregate-VRAM placement,
and an authored terminal that differs from the deterministic reduction. The
fleet record retains the exact source hash, command receipts, raw GPU rows,
foreign-process rows, and SSH timeout receipts that the reduction consumes.

This result establishes no DeepSeek numerical correctness, full checkpoint
execution, performance, serving readiness, production support, conversion,
expert-local/hybrid support, tensor parallelism, CPU offload, AMD/Vulkan
support, or generic planner preference.
