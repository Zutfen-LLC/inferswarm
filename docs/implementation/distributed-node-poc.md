# Distributed-node POC implementation plan

Status: **Active planning record**

Architecture decision: [ADR 0007](../adr/0007-coarse-model-block-partitioning-as-first-network-strategy.md)

Canonical issues: #31, #32, #33, #34.

This plan begins after the completed Phase1R D1-D7 local architecture search.
It does **not** reopen canonical Phase 1 or reinterpret the D-series results.

## Objective

Determine whether multiple ordinary machines can cooperate on one model by
owning **coarse contiguous model blocks**, while:

- requiring only ordinary 1 Gigabit Ethernet as the network baseline;
- preserving backend-native fast execution inside each node;
- keeping block-local weights and KV/recurrent state resident;
- loading only the model state assigned to each node;
- measuring correctness and performance end to end.

The first POC remains deliberately Qwen3.6/NVIDIA/FreeToken-specific so the
network/block architecture is not confounded with model-port or vendor work.

## Fixed starting model

Use the established controlled checkpoint unless an issue explicitly records a
new pre-performance reason to change it:

`nvidia/Qwen3.6-35B-A3B-NVFP4`

revision:

`491c2f1ea524c639598bf8fa787a93fed5a6fbce`

Reuse the established W1-W4 benchmark/correctness provenance where the new work
unit permits it.

## Architectural firewall

The N-series must not silently become fine-grained network expert RPC.

The first network topology is:

```text
node A model block
    |
    | hidden-state boundary
    v
node B model block
```

Networking occurs only at block boundaries. Local implementation inside either
node may use the existing FreeToken GPU/offload machinery as appropriate, but
N0-N3 do not require multi-GPU composition inside a node.

Similarly, do not freeze a generalized InferSwarm public API during these
experiments. The implementation may use explicit POC-only block descriptors,
messages, and process roles.

## N0 — selective model-block loading — issue #31

### Question

Can a node load only a contiguous model block without materializing the entire
model/full CPU expert bank?

### Work

1. Census Qwen3.6 state by layer/block and identify non-layer state that belongs
   at the model entrance/exit.
2. Define an experimental contiguous block descriptor.
3. Modify/add a selective loader path that reads/materializes only assigned
   state.
4. Preserve compact checkpoint/runtime representations where supported.
5. Measure model bytes read, peak RSS, transient staging, GPU bytes, and
   unrelated state that remains absent.
6. Execute at least two complementary block ranges against the corresponding
   slice of a normal full-model reference.

### Hard gates

- unrelated layers never materialize;
- no transient full CPU expert bank;
- block output/state correctness passes;
- RAM accounting is measured, not inferred from file size.

N1 is blocked until N0 passes.

## N1 — local split-block equivalence — issue #32

### Question

Can the complete model execute as two persistent blocks separated by an
explicit boundary without changing model semantics?

### Work

1. Freeze one two-block split before retained correctness/performance work.
2. Give each block explicit ownership of its weights and KV/recurrent state.
3. Define the minimum experimental boundary payload:
   - hidden state;
   - sequence/request position metadata;
   - any model-specific state proven necessary.
4. Run the blocks through separate persistent process/execution contexts on one
   host first.
5. Preserve backend-native fast execution within each block where viable.
6. Exercise decode and prefill separately.
7. Prove deterministic full-generation equivalence to the unsplit model.

### Hard gates

- no hidden shared globals that would disappear across machines;
- state ownership documented;
- full output correctness passes;
- split execution does not devolve into host-orchestrated eager execution on
  every layer.

N2 is blocked until N1 passes.

## N2 — two-machine block primitive over 1 GbE — issue #33

### Question

Can the N1 execution boundary cross an ordinary Ethernet link correctly and
with bounded overhead?

### Baseline network

Ordinary wired **1 Gigabit Ethernet** is mandatory for the baseline per ADR
0003. Faster NICs are optional comparison hardware only.

### Work

1. Keep two persistent node processes alive; no per-token process or connection
   creation.
2. Load only each node's assigned block using N0.
3. Reuse the N1 semantic boundary over a compact binary transport.
4. Keep remote block weights/state and backend execution warm/resident.
5. Measure exact message sizes and network wall for decode and prefill shapes.
6. Verify output/state equivalence against N1.
7. If working 10 GbE hardware is readily available, repeat the same frozen
   geometry as a secondary comparison after the 1 GbE result is preserved.

### Hard gates

- exact two-machine correctness;
- no full-model host RAM on either node;
- persistent network session;
- node-local fast execution remains active;
- full provenance includes NIC/link state and actual payload sizes.

N3 is blocked until N2 passes.

## N3 — end-to-end two-node serving — issue #34

### Question

Does the coarse two-node architecture provide useful end-to-end inference over
ordinary 1 GbE?

### Precommit before measurement

Freeze:

- block split;
- node roles;
- model revision;
- runtime geometry;
- workload population;
- warmup/repetition rules;
- correctness comparator;
- decision thresholds.

Do not retune the split after seeing retained serving results.

### Measure

- decode tok/s;
- TTFT;
- prefill throughput;
- boundary network wall/bytes;
- per-node compute time where non-perturbing instrumentation permits;
- RAM/VRAM utilization;
- paging;
- exact output correctness;
- NIC/link provenance.

The canonical verdict must be based on the 1 GbE arm. An optional 10 GbE arm
answers "how much faster does better networking make it?", not "can we rescue
1 GbE by changing the requirement?"

### Exit

N3 must end with an explicit decision:

- proceed to a bounded three-node N4 experiment;
- iterate on one measured removable bottleneck;
- or stop this network strategy.

Do not create/implement N4 during N3.

## Hardware capability evidence

Continue collecting descriptive capability data that will eventually inform
issue #8, including where available:

- GPU/CPU identity and memory capacity;
- PCIe link generation/width/topology;
- backend/representation support;
- measured local execution latency;
- host RAM capacity;
- network negotiated rate, RTT, and payload throughput.

Do **not** convert these fields into a generic worker score during N0-N3.

## Relationship to local Phase1R work

The D-series remains useful in two ways:

1. local node composition may later reuse graph-compatible expert residency on
   healthy links;
2. the experiments established a general lesson: keep stable hot execution
   local/backend-native and choose a distribution granularity whose boundary
   overhead is small relative to the work behind it.

The Gen2 x1 third-GPU result is not a blocker for coarse nodes. A separate
Gen3 x8 retest is tracked in #35.

## Deferred work

Do not combine into N0-N3:

- AMD/ROCm or Intel/XPU bring-up;
- GLM-5.3 model port;
- generalized worker/node API;
- mixed GPU+RAM acceptance issue #6;
- three-plus-node scheduler;
- dynamic/elastic node membership;
- RDMA/GPUDirect requirements;
- commercial control plane.

## Evidence discipline

Host-specific raw evidence stays external unless a canonical artifact is
explicitly selected for the repository. Every retained result records exact:

- FreeToken/InferSwarm commits;
- model revision;
- block split;
- hardware/node identities;
- network link state;
- commands/runtime geometry;
- workload identity;
- correctness result;
- paging/resource validity.

Conclusions must distinguish `MEASURED`, `CALCULATED`, `ESTIMATED`, and
`SPECULATIVE` per `BENCHMARKING.md`.
