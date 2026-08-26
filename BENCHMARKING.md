# InferSwarm Benchmarking Contract

This document is the project's benchmark contract. It exists because
distributed inference invites a specific failure mode: quoting
order-of-magnitude byte arithmetic or a favorable microbenchmark as if it
were an end-to-end result. The project must never publish fabricated or
estimated performance as measured results.

## Evidence labels

Every performance number published by this project — in issues, PRs, docs,
or benchmarks directories — must carry one of:

```
MEASURED    directly observed on real hardware, with the protocol below
CALCULATED  arithmetic derived from recorded MEASURED inputs
ESTIMATED   order-of-magnitude reasoning, not observed on target hardware
SPECULATIVE a hypothesis; no supporting measurement
```

When in doubt, label down. A number that is not MEASURED must never be
presented, formatted, or discussed as though it were.

## Required provenance

Every benchmark result must record, at minimum:

```
InferSwarm commit
FreeToken commit
model repository
model revision
quantization / weight format

CPU
system RAM
GPU(s)
driver
CUDA/ROCm/XPU version where applicable

PCIe topology
network topology
configured network rate

VRAM allocation policy
RAM allocation policy
expert placement

prompt/workload
batch size
context length
output length

TTFT
prefill throughput
decode tokens/sec
per-token latency if available
```

If a field cannot be filled, record why. A benchmark with silent holes in its
provenance is not a benchmark.

## A/B comparisons

Performance *changes* require an A/B comparison against the relevant baseline
under identical conditions: same model revision, same workload, same
measurement protocol, same hardware, differing only in the configuration
under test. "Same conditions" means the baseline numbers must be re-run (or
provably carried over from a recorded run) whenever hardware, driver, or
model revision changes.

## Microbenchmarks vs end-to-end

For distributed execution, both are required, and they answer different
questions:

- **Microbenchmarks** (single transfer, single expert, single hop) isolate
  where time goes. They diagnose; they do not conclude.
- **End-to-end inference** (TTFT, prefill, decode tokens/sec on a real
  workload) is the only acceptable evidence that inference performance
  improved.

A faster microbenchmark is **not** evidence that end-to-end inference
improved. Synchronization, overlap, and scheduling effects can fully consume
a microbenchmark win. Phases in [ROADMAP.md](ROADMAP.md) are complete only on
end-to-end evidence.

## Correctness checks

Every distributed result must include a correctness check against a
non-distributed reference configuration (e.g. single-GPU or host-RAM offload
on the same model revision). Record:

- the reference configuration and its commit;
- how outputs were compared (metric and tolerance);
- the observed deviation.

A distributed run that is fast but wrong is a bug report, not a result.

## Storing results

Result conventions and the machine-readable layout live in
[docs/benchmarks/](docs/benchmarks/README.md). Results are committed with
exact provenance; hardware benchmarks run on trusted hardware, not public CI
(see [SECURITY.md](SECURITY.md) for why arbitrary PRs cannot trigger
GPU-hungry workflows).

## What this means in practice

- Never present [ESTIMATED] or [SPECULATIVE] numbers with the formatting or
  confidence of [MEASURED] ones.
- Never extrapolate a per-expert win to tokens/sec.
- Never compare against a baseline you did not record.
- If the honest result is "no improvement" or "slower", publish that. That is
  the experiment working.
