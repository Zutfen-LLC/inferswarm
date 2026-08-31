# InferSwarm Benchmarking Contract

This document is the project's benchmark contract. It exists because
heterogeneous/distributed inference invites a specific failure mode: quoting
order-of-magnitude byte arithmetic or a favorable microbenchmark as if it were
an end-to-end result. The project must never publish fabricated or estimated
performance as measured results.

The [Fabric Doctrine](docs/architecture/fabric-doctrine.md) separates generic
resource/path evidence from strategy/model-specific execution evidence. This
contract applies to both.

## Evidence labels

Every performance number published by this project — in issues, PRs, docs, or
benchmark directories — must carry one of:

```text
MEASURED    directly observed on real hardware, with the protocol below
CALCULATED  arithmetic derived from recorded MEASURED inputs
ESTIMATED   order-of-magnitude reasoning, not observed on target hardware
SPECULATIVE a hypothesis; no supporting measurement
```

When in doubt, label down. A number that is not MEASURED must never be
presented, formatted, or discussed as though it were.

## Required provenance

Every benchmark result must record, at minimum, the applicable fields from:

```text
InferSwarm commit
host/runtime integration commit (e.g. FreeToken)
model repository
model revision
quantization / weight representation
Model Execution Strategy / experimental strategy identity

CPU
system RAM
GPU(s) / other Compute Units
Memory Resources relevant to the result
driver
CUDA/ROCm/XPU/other runtime version where applicable

PCIe / NUMA / local topology
network topology where applicable
configured / negotiated network rate where applicable

Execution Plan / frozen placement description
state residency/materialization policy relevant to the result
memory accounting policy
strategy boundary / distribution granularity where applicable
operator constraints relevant to the plan

prompt/workload identity or reproducible workload fixture
batch/concurrency
context/input length
output length

TTFT where applicable
prefill throughput/latency where applicable
decode tokens/sec or latency where applicable
aggregate throughput/concurrency where applicable
```

For resource/path microbenchmarks, record the measurement protocol and enough
resource/topology/runtime context to determine when the result remains valid.
For strategy-specific measurements, also record the applicable
representation/strategy/model context.

If a field is not applicable or cannot be filled, record why. A benchmark with
silent holes in material provenance is not a benchmark.

## A/B comparisons

Performance *changes* require an A/B comparison against the relevant baseline
under equivalent conditions: same model revision, workload, measurement
protocol, and hardware/topology unless the hardware/topology change is itself
the tested variable.

The comparison should differ only in the configuration under test, with every
other material difference identified explicitly.

Baseline numbers must be rerun—or provably carried over from a context-valid
record—when hardware, topology, driver/runtime, representation, model revision,
or another dependency materially affecting the metric changes.

## Microbenchmarks vs end-to-end

Both are valuable and answer different questions:

- **Microbenchmarks** (for example one transfer/path, one strategy execution
  unit, one boundary, or one backend primitive) isolate where time goes. They
  diagnose; they do not conclude end-to-end performance.
- **End-to-end inference** (TTFT, prefill, decode, throughput/concurrency on a
  real/reproducible workload) is the evidence required to claim that inference
  service actually improved.

A faster microbenchmark is **not** evidence that end-to-end inference improved.
Synchronization, overlap, batching, contention, state placement, and scheduling
effects can fully consume a microbenchmark win. Evidence gates in
[ROADMAP.md](ROADMAP.md) are satisfied only by the measurements their frozen
methodology requires.

## Correctness checks

Every execution-path result that changes model computation, representation,
placement, boundary semantics, or distributed execution must include the
correctness check required by the applicable strategy contract against a
trusted reference.

Record:

- the reference configuration/plan and commits;
- model/revision/representation;
- how outputs/state were compared (metric and tolerance);
- the observed deviation;
- NaN/Inf or other validity checks where relevant.

The reference may be a single-resource/non-distributed path for early POCs, but
that is not a universal architecture requirement; it is the trusted comparator
for the specific experiment.

A run that is fast but wrong is a bug report, not a result.

## Demand evidence is not performance evidence

Adaptive Demand Profile observations may predict that one placement should be
better than another. That prediction is not itself a measured performance
result.

Keep separate:

- **demand evidence** — what opaque strategy units/boundaries the workload tends
  to require, including frequency/correlation where relevant;
- **performance evidence** — what it actually costs to satisfy that demand on a
  particular resource/representation/plan.

A learned placement earns a performance claim only after runtime/end-to-end
measurement confirms the outcome.

## Baselines, degradation, and trust

An accepted reference baseline is versioned and must not silently rolling-
average into a degraded new normal. Recent observations may update a Planner
Estimate while the accepted baseline remains available for comparison.

Performance degradation and integrity trust are separate. A resource/path may
be slow but correct. Evidence of untrustworthy computation/state/transport is a
correctness problem governed by quarantine semantics, not a performance-score
penalty.

## Storing results

Result conventions and the machine-readable layout live in
[docs/benchmarks/](docs/benchmarks/README.md). Results are committed with exact
provenance; hardware benchmarks run on trusted hardware, not public CI (see
[SECURITY.md](SECURITY.md) for why arbitrary PRs cannot trigger GPU-hungry
workflows).

Historical result files retain the terminology used by their original frozen
methodology. Do not rewrite measured artifacts merely to replace terms such as
`worker`, `primary`, or `expert` with current doctrine language.

## What this means in practice

- Never present ESTIMATED or SPECULATIVE numbers with the formatting/confidence
  of MEASURED ones.
- Never extrapolate a single transfer/strategy-unit win to end-to-end tokens/sec
  without measuring the end-to-end path.
- Never compare against a baseline whose context is materially different unless
  that difference is the explicit experimental variable.
- Record measured bytes and transient/persistent memory when making residency or
  capacity claims; RSS alone may not prove materialization ownership.
- Keep nominal specifications, discovered configuration, measurements, runtime
  observations, accepted baselines, and planner estimates conceptually
  distinct.
- If the honest result is "no improvement" or "slower", publish that. That is
  the experiment working.
