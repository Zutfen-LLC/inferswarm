# Phase-0 P0-C hardware profile procedure

This note refines the P0-C hardware-profile execution in
`docs/implementation/phase0-baseline.md` after the first real RTX 3060 runs
exposed two tooling gaps. It does not change a benchmark threshold or select a
performance baseline.

## Required runtime

Use the FreeToken `inferswarm` branch at the exact intended commit and its
project virtual environment. Do not run the profile under Debian's system
Python: the profile's `ft bench bw`, device-bandwidth, and NVFP4 expert
microbenchmark must execute in the same installed FreeToken environment used
for later serving.

Before measuring:

- the FreeToken checkout must be clean;
- the selected card must be the physical RTX 3060 12 GB identified by a stable
  GPU UUID;
- the exact InferSwarm commit containing the frozen Phase-0 methodology must be
  supplied with `--inferswarm-commit`;
- `ft bench bw` must run for `nvfp4`;
- device-memory bandwidth and the single-expert NVFP4 microbenchmark must both
  be requested.

Canonical invocation shape:

```bash
PYTHONPATH=python:. .venv/bin/python benchmarks/phase0_baseline.py profile \
    --gpu GPU-<UUID> \
    --inferswarm-commit <exact-40-hex-inferswarm-commit> \
    --dtype nvfp4 \
    --device-bandwidth \
    --expert-microbench \
    --out phase0-runs/hardware-profile.json
```

FreeToken validates the InferSwarm commit before starting a hardware
measurement. The profile must retain the exact FreeToken commit, exact
InferSwarm commit, interpreter/runtime provenance, selected GPU identity, and
all measured blocks below.

## Required P0-C evidence

A publishable P0-C profile must contain all of the following without an
`unavailable` result:

- selected NVIDIA GeForce RTX 3060 in the 12-GB VRAM class, with stable UUID;
- CPU/RAM/OS, driver, CUDA-facing runtime, compute capability, PCIe current/max
  link, and topology provenance;
- successful `ft bench bw` host-DRAM and PCIe measurements;
- usable NVFP4 calibration from that profile, including the resolved backend
  recommendation and hybrid fetch fraction when applicable;
- measured device/VRAM D2D bandwidth with per-repetition observations;
- measured true `top_k=1` single-expert NVFP4 latency;
- the grouped top-k diagnostic kept separately labelled from single-expert
  latency.

The microbenchmarks are diagnostic-only. They may explain a later end-to-end
result but cannot establish a Phase-1 speedup themselves.

## Hardware-discovered fixes

The first real P0-C attempts were intentionally not promoted to canonical
evidence. They exposed two harness defects before any candidate result existed:

1. sequential device-bandwidth and expert diagnostics republished the same GPU
   UUID after the first bind; FreeToken incorrectly treated the derived visible
   CUDA ordinal as a conflicting second assignment;
2. the profile command had no way to record the exact InferSwarm methodology
   commit.

FreeToken PR #2 fixes both: same-physical-GPU rebinding is idempotent while a
different GPU remains an error, and `profile --inferswarm-commit` is now a
pre-measurement provenance gate.

The next successful full profile replaces the exploratory attempts as the
P0-C evidence artifact.

## Accepted P0-C evidence — 2026-08-27

P0-C is **complete**. The accepted measured profile is published under
[`docs/benchmarks/results/phase0/`](results/phase0/p0c-hardware-profile.md):

- human-readable result and verdict: [`p0c-hardware-profile.md`](results/phase0/p0c-hardware-profile.md);
- complete normalized JSON data: [`p0c-hardware-profile.json`](results/phase0/p0c-hardware-profile.json).

The measurement was made from clean FreeToken commit
`715476811acdf281341d0f5f704bcc063bb18630` against InferSwarm methodology
commit `530bbc796039d7d3975439d0fbc2641b4ed0e5b9`, on the selected RTX 3060
UUID `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`.

Two SHA-256 values are retained deliberately:

- original host-produced artifact bytes:
  `fef830fea83f45b6b4b47e7aef30d4104c01c299307d587ef263dcf2403ca499`;
- repository JSON after whitespace-only normalization:
  `806421cf5753cad7e2b52748ecb0bed54e8803eba20191a4829d141b7aea33fd`.

The repository normalization changes formatting only; all JSON values and raw
per-repetition observations are preserved. The result passes every evidence
requirement above. This closes only P0-C: it does not select a performance
baseline or make an end-to-end speedup claim. P0-D, the explicitly
non-canonical real-serving smoke, is the next execution step.
