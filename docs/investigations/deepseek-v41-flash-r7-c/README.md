# R7-C — DeepSeek V4.1 Flash current-fleet physical feasibility

Status: COMPLETE — bounded capacity prerequisite. This additive R7-C bundle
consumes R7-A/R7-B byte-for-byte and stops before model-state acquisition.

## Authority

- Starting reconciled main: `fe690249873a9bf7ca19d788a2fab5e580473394`.
- Corrected producer/authority head: `31bec059a9016de61ebcdfc61b4b9e4766493441`
  (`authority.json.repo_head`). The retained authority is a pure function of the
  frozen R7-A/R7-B predecessor bytes at this head and is re-derived - never
  trusted as authored input - at reduction and finalization time.
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

The mechanical post-R7-B applicability audit classifies the 2,370 changed paths
from the R7-B merge through reconciled main: 4 campaign-gate/CI paths, 2,357
separate V340L Vulkan/hardware paths, and 9 other documentation/test paths. Its
verbatim changed-path census is retained as `mainline-changed-paths.txt` (the
output of the frozen read-only `git diff --name-only
54d36cb9d8a4c0603abeb18968a8ffb7b52ca10e..fe690249873a9bf7ca19d788a2fab5e580473394`
query, re-derived and byte-compared by a focused test), so the audit is a
function of retained bytes rather than a live query. It finds no change to R7-A
census authority, R7-B vLLM authority, or the selected R7-B strategy.

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

The frozen collector was run read-only on all four current NVIDIA candidates
under the re-frozen authority, after that authority was committed and pushed.
All four hosts were reachable and returned six GPU resources:

| Resource | Device | Available bytes | Foreign compute |
| --- | --- | ---: | --- |
| `inferswarm01/gpu-0` | RTX 3060 | 12,485,394,432 | none |
| `inferswarm01/gpu-1` | RTX 3060 | 12,487,491,584 | none |
| `inferswarm02/gpu-0` | RTX 3060 Ti | 8,276,410,368 | none |
| `inferswarm03/gpu-0` | RTX 3060 | 12,341,739,520 | PID 1218154 (184 MiB) |
| `inferswarm03/gpu-1` | RTX 3060 | 12,341,739,520 | PID 1218155 (184 MiB) |
| `inferswarm04/gpu-0` | RTX 3090 | 25,294,798,848 | none |

`unavailable_hosts` is empty: no host is retained as a zero-capacity boundary,
and `inferswarm02` and `inferswarm04` are present with full host records. The
two `inferswarm03` resources carry visible foreign compute processes and are
excluded from legal placement. Every resource row - including total, available
and used bytes, UUID, PCI BDF and driver version - is re-derived by the reducer
from the retained raw `nvidia-smi` receipt bytes, and the reducer rejects
forged, duplicated, substituted, stale or incomplete receipts.

No individual compatible, currently available resource satisfies either stage
lower bound. The largest single compatible usable resource is 25,294,798,848
bytes (`inferswarm04/gpu-0`, the RTX 3090), leaving per-resource deficits of
326,940,703,728 bytes for stage A and 123,852,309,984 bytes for stage B. The
compatible aggregate of 58,544,095,232 bytes is reported for transparency only
and is never used as a placement rule: each contiguous stage must fit one
resource, and aggregate-VRAM arithmetic can never substitute for that.

## Terminal

`R7C_CURRENT_FLEET_CAPACITY_PREREQUISITE`

Required successor prerequisite: a compatible single-resource capacity path for
each exact R7-B contiguous stage, without an alternate cut, tensor parallelism,
CPU/disk offload, representation conversion, or hybrid execution.

The reduction stopped at Phase 2. No official checkpoint body bytes were
acquired; no model runtime initialized; no tensor sentinel, full-model forward
pass, benchmark, serving run, AMD/Vulkan path, or alternate placement mechanism
was executed.

## Superseded observation

An earlier census/terminal pair (retained in git history at commit `1cd140e`)
was observed under a pre-hardening producer and described `inferswarm02` and
`inferswarm04` as unreachable zero-capacity boundaries. Hardening the producer
changed its bytes and therefore invalidated that census's collector-identity
binding, so it cannot carry acceptance and has been replaced by the fresh
observation above. It proved only that the four candidates were probed and that
two of them were unreachable at that time; it never carried the accepted
terminal, because the accepted terminal is re-derived under the final authority.

## Controls and scope

The committed reducer/tests fail closed on mutated R7-A/R7-B authority, altered
cut, a re-signed R7-C authority that is not the deterministic derivation from
the frozen predecessor bytes (alternate cut, authored stage bounds, substituted
model/runtime/producer identity), incomplete candidate-host set, stale fleet
census, missing foreign-process receipts, foreign-process availability
substitution, duplicate or unknown device rows, aggregate-VRAM placement, and an
authored terminal that differs from the deterministic reduction. The fleet
record retains the exact source hash, command receipts, raw GPU rows,
foreign-process rows, and any SSH timeout receipts that the reduction consumes.
Receipt digests establish the integrity of the retained raw bytes, not their
authenticity: the census carries no out-of-band signing anchor and is trusted
through maintainer review of this bundle.

This result establishes no DeepSeek numerical correctness, full checkpoint
execution, performance, serving readiness, production support, conversion,
expert-local/hybrid support, tensor parallelism, CPU offload, AMD/Vulkan
support, or generic planner preference.
