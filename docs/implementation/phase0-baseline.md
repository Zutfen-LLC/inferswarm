# Phase 0 baseline and instrumentation execution plan

```
Status: Active implementation / experiment plan
Canonical issues: #2 — Establish reproducible RTX 3060 FreeToken baseline
                  #3 — Instrument Qwen3.6 MoE routing and residency behavior
Implementation repository: Zutfen-LLC/FreeToken, branch: inferswarm
Evidence repository: Zutfen-LLC/inferswarm
```

This document turns ROADMAP Phase 0 into an ordered execution plan and records
what has already been built versus what still has to be measured. It does not
change the benchmark protocol or Phase-1 decision thresholds. If this plan
conflicts with [BENCHMARKING.md](../../BENCHMARKING.md),
[the Phase-1 POC success criteria](../phase1-poc-success-criteria.md), an
accepted ADR, or issues #2/#3, those sources win.

Phase 0 is **not complete when the harness exists**. It is complete only when
the canonical single-RTX-3060 baseline, correctness reference, hardware
profile, and routing/residency evidence exist with reproducible provenance.

## 1. Current status

| Work item | Status | Evidence / next action |
|---|---|---|
| Reproducible Phase-0 harness and runtime instrumentation | **DONE** | FreeToken PR #1, `bench: add reproducible InferSwarm Phase 0 baseline harness`, merged into FreeToken `inferswarm` |
| Real RTX 3060 development host provisioned | **DONE for execution readiness** | Debian host has RTX 3060 12 GB, current NVIDIA driver/CUDA toolkit, FreeToken editable install, and real CUDA tests exercised. This is setup evidence, not a Phase-0 benchmark result. |
| Full-suite regression check on the real 3060 | **DONE for harness validation** | PR-induced failures were fixed before merge. The remaining pageable-pointer test failure exists on the FreeToken base and can poison the immediately following CUDA test; isolated production pinned-memory/NVFP4/Triton paths pass. This does not count as a Phase-0 performance result. |
| Exact Qwen checkpoint revision pin | **TODO — blocks canonical measurement** | Pin exact 40-hex upstream revision of `nvidia/Qwen3.6-35B-A3B-NVFP4`; record it in every artifact. |
| Frozen canonical W1–W4 workload manifest | **TODO — blocks canonical measurement** | Finish/freeze issue #3 fixtures and hashes; the committed FreeToken example manifest is smoke-only and must not be used canonically. |
| RTX 3060 hardware profile | **TODO** | Run the Phase-0 `profile` subcommand on the selected physical GPU UUID. |
| Non-canonical real-serving smoke | **TODO** | Exercise the pinned model and representative B2/B3 paths with `--dev-smoke` before spending time on the canonical campaign. |
| Canonical B1–B5 performance sweep | **TODO** | Two complete sessions, second in reverse order; no early stopping or discarded measured repetitions. |
| Select `CANONICAL_PERFORMANCE_BASELINE` | **TODO** | Select the measured winner only after both valid sessions exist; selection is human review of precommitted metrics, not a harness-side optimization. |
| `CORRECTNESS_REFERENCE` | **TODO** | Two independent greedy reference runs; require self-consistent output hashes before Phase 1 can use the reference. |
| Routing/residency traces and miss-rate curves | **TODO** | Complete issue #3 on the frozen workload set. Add only the minimum extra FreeToken instrumentation if the merged harness/runtime counters are insufficient. |
| Commit Phase-0 evidence to InferSwarm | **TODO** | Publish raw/summary artifacts under `docs/benchmarks/results/` and routing analysis under `docs/investigations/`; then close #2/#3 only when their acceptance criteria are actually met. |

The distinction above is deliberate: **FreeToken PR #1 completed the tooling
work needed to run Phase 0; it did not complete Phase 0 itself.**

## 2. Repository and branch state before measurement

Canonical Phase-0 measurement uses the long-lived FreeToken `inferswarm`
branch, not the old `poc/phase0-baseline-harness` branch. Before each canonical
session:

1. update the local `inferswarm` checkout to the exact intended commit;
2. require `git status --short` to be empty — the harness refuses a dirty
   checkout for canonical runs;
3. record the full FreeToken commit SHA;
4. record the full InferSwarm commit SHA containing the frozen methodology and
   workload manifest;
5. record the selected physical RTX 3060 by stable `GPU-...` UUID, not merely
   by CUDA index.

A FreeToken/runtime/model/driver change that materially changes the measured
system requires the baseline and dependent candidate to be treated according
to BENCHMARKING.md and the success criteria; do not splice measurements from
incompatible environments.

## 3. P0-A — pin the model revision

Before the first canonical measurement, pin the exact upstream revision of:

```
nvidia/Qwen3.6-35B-A3B-NVFP4
```

Requirements:

- exact 40-hex commit SHA;
- same repository and revision for every B1–B5 arm and the correctness
  reference;
- canonical live arms must report resolved `expert_quant = nvfp4`;
- if using a Hugging Face snapshot path, the local snapshot SHA/repository
  must agree with the declared repository/revision or the harness must refuse
  the run.

Deliverable: the exact model pin appears in the frozen workload/campaign
instructions and subsequently in every result artifact. No benchmark number
may precede this pin.

## 4. P0-B — freeze the canonical workload manifest

Issue #3 supplies the representative workload material used both for the
baseline and the routing analysis. Freeze the W1–W4 fixtures **before** the
candidate is benchmarked.

For each workload class, the manifest must pin at least:

- fixture contents or version-controlled fixture path;
- SHA-256;
- requested output-token count;
- sampling parameters;
- `ignore_eos`;
- chat-template settings;
- the workload-shape rule enforced by the harness.

Use the FreeToken harness validator and hashing helper. The example smoke
manifest under `benchmarks/inferswarm_phase0/examples/` is explicitly
non-canonical and must not be promoted into the real campaign.

Deliverable: one version-controlled canonical workload manifest in InferSwarm
(or a path arrangement referenced from InferSwarm) whose hashes do not change
between Phase 0 and Phase 1.

## 5. P0-C — capture the hardware profile

On the selected RTX 3060, from the FreeToken repo root:

```bash
nvidia-smi -L

PYTHONPATH=python:. python benchmarks/phase0_baseline.py profile \
    --gpu GPU-<UUID> \
    --dtype nvfp4 \
    --device-bandwidth \
    --expert-microbench \
    --out phase0-runs/hardware-profile.json
```

Review the artifact before continuing. It must identify the expected RTX 3060
12 GB and selected UUID and should contain usable measurements for:

- CPU/system-memory bandwidth and CPU-MoE calibration from `ft bench bw`;
- PCIe transfer/gather behavior from `ft bench bw`;
- device/VRAM D2D bandwidth;
- true `top_k=1` single-expert NVFP4 decode latency;
- grouped top-k diagnostic, kept distinct from single-expert latency;
- driver, CUDA-facing environment, compute capability, PCIe current/max link,
  topology, CPU/RAM/OS provenance.

All microbenchmarks are diagnostic only. They cannot select the baseline or
establish a Phase-1 performance claim.

## 6. P0-D — run one non-canonical serving smoke

Before the canonical two-session campaign, use `--dev-smoke` to prove the
whole serving path works with the pinned checkpoint, workload container, and
selected GPU.

The smoke should be deliberately small and must remain visibly
`NON_CANONICAL`. Its purpose is to catch operational failures cheaply:

- checkpoint/load failure;
- invalid manifest wiring;
- `ft bench bw` profile creation/consumption failure;
- server startup or instrumentation failure;
- GPU UUID mismatch;
- B2 hybrid-fraction resolution failure;
- B3 `auto` resolution behaving outside the allowed B1/B2 family;
- prefill record attribution failures.

Do not quote smoke throughput as a Phase-0 result and do not tune the
canonical protocol in response to attractive or unattractive smoke numbers.

## 7. P0-E — canonical B1–B5 session 1

Use the merged FreeToken harness. Canonical invocation shape:

```bash
PYTHONPATH=python:. python benchmarks/phase0_baseline.py sweep \
    --model /path/to/pinned/Qwen3.6-35B-A3B-NVFP4 \
    --model-repository nvidia/Qwen3.6-35B-A3B-NVFP4 \
    --model-revision <exact-40-hex-model-revision> \
    --gpu GPU-<UUID> \
    --manifest /path/to/frozen-workloads.json \
    --inferswarm-commit <exact-40-hex-inferswarm-commit> \
    --session-id session-1 \
    --out-root phase0-runs
```

The harness supplies the predeclared B1–B5 configuration matrix, refreshes the
NVFP4 `ft bench bw` profile before the sweep, runs two discarded warmups plus
10 measured generations per arm/workload class, preserves every repetition,
and records resolved runtime configuration.

After completion, require both:

- `execution_status = COMPLETE`;
- `validity = VALID`.

A complete but invalid campaign is not a baseline.

## 8. P0-F — canonical B1–B5 session 2, reversed

Run a second independent canonical session with a new session id and reversed
traversal:

```bash
PYTHONPATH=python:. python benchmarks/phase0_baseline.py sweep \
    ...same pinned model/GPU/manifest/provenance... \
    --session-id session-2 \
    --reverse-order \
    --out-root phase0-runs
```

Do not drop repetitions or stop early. Both sessions remain independently
reviewable; where the success criteria say the worse verdict stands, apply
that rule rather than pooling away a problem.

## 9. P0-G — select `CANONICAL_PERFORMANCE_BASELINE`

Only after both valid sessions exist:

1. compute/review the precommitted aggregate warm decode metric and its
   variance/uncertainty exactly as specified by the success criteria;
2. confirm every B1–B5 arm was a legitimate working FreeToken configuration;
3. select the measured winner as `CANONICAL_PERFORMANCE_BASELINE`;
4. preserve all five arm results, including equivalent B1/B4 observations if
   `auto` resolved to Triton;
5. record the selected arm and the reason mechanically from the frozen rule —
   do not choose the arm that makes InferSwarm easiest to beat.

This selected baseline is what Phase 1 must beat. Any later material change
that invalidates this comparison requires a baseline re-run under the project
benchmark contract.

## 10. P0-H — establish `CORRECTNESS_REFERENCE`

Run the separate reference subcommand using the same pinned model/workload and
the resolved NVFP4 backend that the Phase-1 GPU-resident expert path will use.
Invocation shape from the FreeToken harness documentation:

```bash
PYTHONPATH=python:. python benchmarks/phase0_baseline.py reference \
    --model /path/to/pinned/model \
    --model-repository nvidia/Qwen3.6-35B-A3B-NVFP4 \
    --model-revision <exact-40-hex-model-revision> \
    --gpu GPU-<UUID> \
    --manifest /path/to/frozen-workloads.json \
    --nvfp4-backend <resolved-reference-backend> \
    --moe-cache-size <fixed-valid-size>
```

Run it twice under distinct session ids. The reference must be greedy and
self-consistent: matching output hashes per fixture across the two independent
runs. If the reference is unstable, Phase 1 correctness comparison is blocked;
do not loosen the later tolerance to accommodate an unstable reference.

## 11. P0-I — capture routing/residency evidence for issue #3

Using the same frozen workload classes, capture the routing and cache behavior
needed to replace feasibility estimates with measured data.

Required issue #3 deliverables:

- routing traces for at least two workload classes;
- empirical miss-rate-vs-cache-fraction curve at several cache sizes;
- measured hit/miss/residency observations with evidence labels;
- anonymized trace/analysis committed under `docs/investigations/`.

Before writing more runtime code, first verify whether the instrumentation now
present on FreeToken `inferswarm` already exposes the required selection,
per-layer miss, and routing histogram data. If anything is missing, create one
focused FreeToken `poc/*` instrumentation PR linked to issue #3. Do not mix a
new distributed-execution implementation into that PR.

The output of this step is an input to Phase-1 placement. Coverage alone is
not a hit-rate claim; the Phase-1 placement must be derived from measured
routing evidence rather than guessed from expert count.

## 12. P0-J — publish and close Phase 0

Phase-0 completion requires repo evidence, not files stranded under the
ignored local `phase0-runs/` directory.

Publish to InferSwarm:

- canonical hardware-profile evidence;
- both complete/valid B1–B5 sessions and raw repetition data;
- the recorded `CANONICAL_PERFORMANCE_BASELINE` selection;
- both correctness-reference runs and self-consistency result;
- routing/residency traces and miss-rate analysis;
- exact provenance: model revision, FreeToken commit, InferSwarm commit, GPU
  UUID, driver/CUDA-facing environment, topology, host CPU/RAM, resolved
  runtime settings;
- concise human-readable summaries under `docs/benchmarks/results/` and
  `docs/investigations/`, with raw artifacts retained or referenced according
  to repository policy.

Then evaluate issues #2 and #3 against their acceptance criteria. Close them
only when every required artifact exists.

## 13. Phase-0 exit gate into Phase 1

[Phase 1](phase1-two-gpu-poc.md) may have implementation work in flight, but
**canonical Phase-1 measurement is blocked** until all of these are true:

- valid `CANONICAL_PERFORMANCE_BASELINE` selected from two canonical sessions;
- exact checkpoint revision pinned and unchanged;
- self-consistent `CORRECTNESS_REFERENCE` captured;
- frozen W1–W4 workload manifest exists;
- issue #3 routing/residency evidence exists and supports a predeclared
  placement rather than a guessed one;
- all Phase-0 evidence is committed with provenance.

At that point Phase 0 is complete. The next implementation step is Phase-1 P1
(the secondary-device substrate/probe), unless that work has already been
completed opportunistically without using Phase-1 performance results to
change the precommitted experiment.

## 14. Non-goals

Phase 0 does not:

- implement distributed execution;
- use GPU 1 for expert execution;
- choose or tune Phase-1 placement after seeing candidate performance;
- infer end-to-end gains from microbenchmarks;
- treat smoke runs as canonical evidence;
- change the success thresholds after measurements exist;
- generalize InferSwarm worker abstractions.

The phase exists to establish trustworthy ground truth. If Phase 0 is weak,
every later speedup ratio is weak with it.
