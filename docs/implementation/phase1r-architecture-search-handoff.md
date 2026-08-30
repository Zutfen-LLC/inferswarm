# Phase1R architecture-search handoff

**Status:** Living implementation/research handoff  
**Last updated:** 2026-08-30  
**Resume instruction:** Continue InferSwarm from this document; verify any open PR/issue state before mutating it.

## 1. Purpose

This document is the single resume point for post-Phase-1 InferSwarm architecture research. It intentionally separates the immutable canonical Phase-1 result from later architecture-search experiments that explore materially different execution shapes.

The immediate research question is no longer whether the original Phase-1 candidate can be tuned into success. That candidate is permanently NO-GO. The current question is whether a graph-compatible, resident-worker design can add useful GPU memory/compute with a bounded marginal throughput tax as workers are added.

A long-running certification campaign is not the architecture-search inner loop. Physical experiments should use short, staged fail-fast screens and reserve multi-hour campaigns for later certification only.

---

## 2. Canonical Phase-1 result — immutable

Canonical publication was merged by InferSwarm PR #30.

- InferSwarm merge commit: `3e06e5e44b260af4e234d876a9325da77754f9fe`
- Canonical FreeToken runtime: `f29013fda7f1dcda94c6e44957d8b503795928dd`
- InferSwarm methodology commit used by the campaign: `14d0190eb76f39e11fcfd2e39d386ae05df78792`
- Model: `nvidia/Qwen3.6-35B-A3B-NVFP4`
- Model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`
- Placement SHA-256: `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`
- Campaign identity: `1a1dda536059c8d71f9179597c46d17c65a7763d9a8875414d7ce823b1c2ec13`

The campaign was COMPLETE / VALID in two independent counterbalanced sessions and produced `NO-GO` in both.

Canonical warm decode ratios were approximately `R_agg = 0.072` in both sessions. The candidate ran around 4 tok/s while B1 ran roughly 52–57 tok/s. F1–F6 and C1–C4 passed; the failure was performance, not correctness or mechanism validity.

The canonical report and disposition are:

- `docs/benchmarks/results/phase1/phase1-go-no-go-report.md`
- `docs/benchmarks/results/phase1/phase1-go-no-go-disposition.md`
- `docs/benchmarks/results/phase1/p6-complete-layer-breakdown.md`

The disposition is **STOP / RECONSIDER** for the tested mechanism. No later optimization or experiment may rewrite that campaign's verdict. Any materially different implementation is a new experiment.

The original canonical candidate used graph-disabled, per-layer host-orchestrated remote execution. It must not be confused with the later D2 architecture.

---

## 3. D1 — graph-loss attribution

### Goal

Determine how much of the Phase-1 slowdown came from disabling CUDA graph replay versus the incremental distributed path itself.

### External evidence

Host-local evidence directory used for the experiment:

`~/inferswarm-evidence/architecture-search/d1-graph-attribution/`

Important artifacts reported by the run:

- `d1-plan.json`
- `d1-arm-a.json`
- `d1-arm-b.json`
- `d1-arm-c.json`
- `d1-analysis.json`
- `d1-report.md`

### Measured result

D1 completed in 670.475 s (11m 10.475s).

| Arm | Meaning | Median decode |
|---|---|---:|
| A | graph-enabled matched local | 54.6057 tok/s |
| B | graph-disabled matched local | 6.2161 tok/s |
| C | graph-disabled distributed Phase-1 shape | 3.9124 tok/s |

Measured factors:

- `GRAPH_FACTOR = B / A = 0.113835`
- `DISTRIBUTED_FACTOR = C / B = 0.629402`
- `TOTAL_FACTOR = C / A = 0.071648`

Median measured MoE-only token wall:

- A: 9.0522 ms
- B: 44.3515 ms
- C: 137.6717 ms

Calculated additions from those measured per-step complete-layer walls:

- graph-added MoE wall: 35.299328 ms
- distributed-added MoE wall: 93.320192 ms

### Interpretation

D1 classified the end-to-end result as `GRAPH_LOSS_DOMINANT`: the throughput collapse from 54.6 to 6.2 tok/s existed before any remote execution was enabled.

Important nuance: graph loss dominates whole-token throughput because leaving the captured path slows the entire model, while the distributed path contributed the larger measured addition specifically inside the MoE critical path. A successor architecture therefore had to solve both problems.

Do **not** assume the eager-regime `DISTRIBUTED_FACTOR = 0.629402` predicts graph-compatible worker retention. D2 measured the combined graph-compatible system directly.

---

## 4. D2 — graph-compatible resident remote execution

### FreeToken implementation

Open FreeToken PR at the time of this handoff:

- PR: `Zutfen-LLC/FreeToken#14`
- title: `InferSwarm D2: prototype graph-compatible remote decode`
- branch: `poc/phase1r-graph-compatible-remote`
- reviewed head: `2f0ad1b678820c51a52b44821119395ee384e60e`
- base: `f29013fda7f1dcda94c6e44957d8b503795928dd`

The experiment is gated by:

`--inferswarm-experimental-d2-graph-remote`

The existing canonical `--inferswarm-remote-decode` implementation remains unchanged. D2 is intentionally separate post-NO-GO research machinery.

Before merging PR #14, run broader FreeToken regression suites in addition to the already reported targeted tests. At review time there was no GitHub CI workflow run on the D2 head, although 61 targeted tests, compile, and diff checks had passed.

### D2 architecture

D2 captures the remote worker fork/join into FreeToken's existing batch-1 whole-forward CUDA graph.

Captured topology:

1. GPU0 pinned D2H activation / slot IDs / route weights
2. internal cross-device ready event
3. GPU1 pinned H2D
4. GPU1 resident native-NVFP4 Triton route-contribution kernel
5. GPU1 pinned D2H ordered route contributions
6. internal cross-device done event
7. GPU0 pinned H2D
8. same-route reconstruction
9. one canonical route-order sum reduction

Properties demonstrated in Part 1:

- stock CUDA 13.0 cross-device dependency works despite peer access being unavailable;
- dynamic activation, route IDs, and route weights are consumed without recapture;
- real resident 5,442-slot GPU1 expert bank executes;
- zero steady-state expert-weight movement;
- zero steady-state host synchronization;
- no per-token/layer recapture;
- exact mixed, remote-only, and local-only correctness;
- no dropped or duplicated routes.

Unified internal-event capture succeeded. One whole-model replay owns the embedded GPU1 work; there are no per-layer Python graph launches in steady-state serving.

Replay submission microdiagnostic after warmup:

- current eager remote submit median: 747.137 µs
- captured graph replay submit median: 144.682 µs

### D2 direct serving result

Short W4 screen, 1 discarded warmup + 3 retained repetitions per arm.

G0 graph-local matched control:

- 54.287187
- 54.554496
- 54.576292 tok/s
- median: **54.554496 tok/s**

G1 D2 graph-compatible distributed:

- 67.905430
- 68.125518
- 68.027639 tok/s
- median: **68.027639 tok/s**

Direct architecture-search metric:

`NODE2_RETENTION = 68.027639 / 54.554496 = 1.2469667`

Therefore adding the second resident GPU increased measured throughput by about 24.7% in this short screen.

Lower-level timing agreed with the direction:

| Metric | G0 | G1 |
|---|---:|---:|
| complete-layer median | 0.233472 ms | 0.150528 ms |
| MoE-only token wall median | 9.055232 ms | 6.011904 ms |

G0/G1 completion output hashes were identical. G1 reported 26,211 GPU1 selections and 95,709 GPU0 selections across 15,240 layer calls, zero fallback/failure, and zero steady expert-weight H2D.

D2 conclusion: `GRAPH_DISTRIBUTED_STRONG`.

### What D2 does and does not prove

D2 is strong evidence that resident expert execution can be beneficial when remote participation remains inside the fast captured serving path.

It does **not** prove N-worker scaling. The current implementation has one secondary GPU and currently reports `FANOUT_SHAPE = CONCURRENT_BOUNDED`; D3 must physically prove that additional workers can actually fan out concurrently without a serial or host-linear penalty.

D2 also remains NVIDIA/NVFP4-specific implementation scaffolding. It must not redefine InferSwarm itself around CUDA Graphs or NVFP4.

External evidence path reported for D2:

`~/inferswarm-evidence/architecture-search/d2-graph-compatible-remote/`

---

## 5. Backend-independence architectural guardrail

InferSwarm ADR 0006 was accepted and committed at:

`fae92f152f7bae620a3ef971fe9f4f45351c0dda`

Document:

`docs/adr/0006-backend-independent-worker-and-representation-boundary.md`

Key invariants:

- CUDA Graphs are an NVIDIA/backend-native optimization, not an InferSwarm semantic requirement.
- The actual requirement is to avoid host-orchestrated eager execution in the hot inference path where a backend offers captured/compiled/queued/persistent execution.
- NVFP4/Triton is the first NVIDIA expert representation, not the canonical InferSwarm representation.
- InferSwarm owns logical expert identity; workers may use backend-native internal representations.
- Routed work and route contributions are the cross-worker semantic boundary, not packed expert bytes.
- Transport is orthogonal to execution.
- Same-host CUDA fusion is allowed as an optimized backend while the conceptual worker boundary remains backend-independent.
- Heterogeneous backends may require bounded numerical equivalence instead of impossible bitwise equivalence.

Do not freeze concrete Worker/Transport/Representation APIs until architecture-search evidence is sufficient.

---

## 6. `inferswarm02` — current D3 host

### OS/runtime

Fresh host provisioning completed and reported `ENVIRONMENT READY`.

- Debian 13.6
- NVIDIA driver: `610.57.04`
- system nvcc: `13.1.115` / CUDA toolkit 13.1.x
- Python: 3.13.5
- FreeToken venv Torch: `2.11.0+cu130`
- `torch.version.cuda`: 13.0
- Triton: 3.6.0
- uv: 0.12.7
- FreeToken checkout during setup: detached at D2 head `2f0ad1b678820c51a52b44821119395ee384e60e`, clean
- InferSwarm checkout during setup: `main` at `fae92f152f7bae620a3ef971fe9f4f45351c0dda`, clean
- 630 setup/unit tests passed in the environment bring-up

Setup evidence lives under:

`~/inferswarm02-setup/`

including `environment-readiness.json` and `.md`.

### GPUs

GPU0 — coordinator candidate:

- RTX 3090 24 GB
- UUID: `GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03`
- BDF: `01:00.0`
- motherboard-local slot
- measured PCIe endpoint: Gen2 x16

GPU1 — worker A:

- RTX 3060 12 GB
- UUID: `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`
- BDF: `04:00.0`
- x1 mining riser

GPU2 — worker B:

- RTX 3060 12 GB
- UUID: `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`
- BDF: `05:00.0`
- x1 mining riser

All are sm_86. `nvidia-smi topo -m` reports PHB relationships. Peer access is false on all pairs. No NVLink.

### RAM/swap

- physical RAM: about 15 GiB usable
- configured SSD swap: about 44 GiB
- `vm.swappiness=10`

The current FreeToken resident-bank architecture retains a complete CPU-side expert bank as source authority even when most experts are copied to GPU residency. For this Qwen NVFP4 geometry the packed full CPU expert bank is roughly 16.93 GiB by itself (`40 × 256 × 1,775,616 bytes`). Therefore swap may be required simply to park cold redundant CPU backing pages.

For architecture-search serving, swap is acceptable as cold capacity but **not** as a hot inference tier. Every D3 serving arm must record decode-window swap/page-fault behavior. Significant `pswpin`, `pswpout`, or major faults during measured decode contaminate the arm.

A future loader refactor should decouple GPU residency from mandatory full CPU expert-bank residency so a GPU-rich worker does not need host RAM >= model expert size.

---

## 7. D3A — `inferswarm02` substrate qualification

### External evidence

`~/inferswarm-evidence/architecture-search/d3a-substrate/`

D3A runtime was 66.46 seconds. No repo/model changes occurred.

Classification: **`D3_SUBSTRATE_GOOD`**.

### PCIe topology

Important correction preserved by D3A: 5 GT/s is PCIe Gen2, not Gen1.

- GPU0 endpoint: Gen2 x16 under load
- GPU1 endpoint: Gen2 x1 under load
- GPU2 endpoint: Gen2 x1 under load

GPU1 and GPU2 use distinct root ports (`00:1c.3` and `00:1c.4`) and distinct IOMMU groups. Both are NUMA node 0. They do not share one immediate bridge. A possible common chipset/host aggregate bottleneck above those ports is not directly exposed by the captured topology and must not be invented.

The raw evidence preserves a register discrepancy: each 3060 endpoint reported 5 GT/s x1 under load while its parent bridge LnkSta remained 2.5 GT/s x1. Measured transfer behavior, not silent normalization of that register discrepancy, controls substrate interpretation.

### Measured pinned-host transfer ceiling

Large-payload worker throughput was approximately:

- GPU1 H2D: 0.363 GiB/s
- GPU1 D2H: 0.398 GiB/s
- GPU2 H2D: 0.363 GiB/s
- GPU2 D2H: 0.398 GiB/s

The local 3090 measured about 6 GiB/s in the same large-payload test.

### D2-shaped transfer-only latency

Pattern per remote layer approximation:

- GPU0 -> pinned host: ~4 KiB
- pinned host -> worker: ~4 KiB
- worker -> pinned host: ~32 KiB
- pinned host -> GPU0: ~32 KiB

Independent medians:

- GPU1: 54.7 µs
- GPU2: 55.4 µs

Concurrent two-worker medians:

- GPU1: 105.0 µs
- GPU2: 105.1 µs

So concurrent small-message roundtrip latency is about 1.9x each independent worker, but absolute latency remains about 105 µs.

### Contention result

There was **no bandwidth collapse** when both x1 workers transferred concurrently.

Large-transfer concurrent retention was approximately 0.998 for each worker in both H2D and D2H directions. Small 32 KiB throughput was also stable; >1.0 apparent retention was classified as variance/startup behavior, not extra physical capacity.

This is why D3A is `D3_SUBSTRATE_GOOD`: the risers are narrow and measured, but they do not halve each other's bandwidth under concurrent traffic.

No swap activity occurred during D3A (`pswpin=0`, `pswpout=0`).

---

## 8. D3 — next experiment to design/run

### Goal

Test the property that now matters most:

> Does adding a second resident worker increase capacity without precipitous or compounding throughput falloff?

D3 should be a **captured concurrent 1 -> 2 -> 3 GPU fan-out/fan-in experiment**, not a new canonical campaign.

Use `inferswarm02`:

- coordinator: RTX 3090 GPU0
- worker A: RTX 3060 GPU1
- worker B: RTX 3060 GPU2

The D3 implementation should build from the D2 graph-compatible execution machinery, not from the old eager Phase-1 remote path.

### Coordinator must be intentionally constrained

The Qwen model can fit comfortably enough on the RTX 3090 that an unconstrained coordinator could make the workers unnecessary and invalidate the research question.

Therefore constrain GPU0's expert cache/residency intentionally.

Current preferred starting geometry for D3 design:

- GPU0 coordinator: **3,774** local expert slots
- worker A: approximately **3,000 unique** expert identities
- worker B: approximately **3,000 additional unique** expert identities

The exact worker counts should be finalized by a joint placement calculation before measurement, not tuned after seeing serving performance.

Qwen geometry relevant to placement:

- 40 MoE layers
- 256 experts/layer
- 10,240 logical expert identities total
- native NVFP4 bytes per expert identity: 1,775,616

~3,000 resident identities correspond to roughly 5 GiB of expert payload per 3060, leaving comfortable VRAM for D2/D3 workspaces.

### Joint placement requirements

Do **not** simply duplicate the original 5,442-slot worker placement onto both 3060s.

Generate the multi-worker placement jointly so that:

- worker A and worker B add unique residency by default;
- GPU0, worker A, and worker B ownership is mechanically exact;
- placement uses the frozen routing evidence rather than arbitrary expert IDs;
- expected worker route load is reasonably balanced so one worker does not become a trivial/no-op participant or obvious straggler;
- duplicate residency, if ever introduced, must be intentional and justified rather than accidental.

### Serving shapes

Run four short matched shapes on the same D3 build:

- `S1`: constrained RTX 3090, no remote worker
- `S2A`: constrained RTX 3090 + worker A
- `S2B`: constrained RTX 3090 + worker B
- `S3`: constrained RTX 3090 + both workers concurrently

`S2A` and `S2B` provide a worker/riser consistency check before interpreting the two-worker result.

An optional unconstrained-3090 reference may be useful descriptively, but it must **not** become the denominator for marginal worker-retention arithmetic.

### Marginal-retention metrics

Report at least:

- `E2A = T_S2A / T_S1`
- `E2B = T_S2B / T_S1`
- `E3 = T_S3 / max(T_S2A, T_S2B)`

Also report absolute throughput and added resident capacity at each stage.

The long-term product requirement is bounded marginal worker cost, not necessarily matching the fastest monolithic single-GPU configuration.

Repeated ~0.5 retention per added worker would compound into a non-starter. A useful architecture should keep marginal retention comfortably above 0.5 and preferably in the 0.75–0.90+ region as worker count grows. These remain architecture-search heuristics, not frozen canonical success criteria.

D2 already measured `E2 ≈ 1.247` on the two-3060 workstation setup; D3 must not assume that favorable result survives a stronger coordinator, x1 risers, or a second concurrent worker.

### D3 instrumentation priorities

Add fine-grained evidence for:

- worker A execution time
- worker B execution time
- captured cross-device dependency stall / join wait at GPU0
- whether workers actually overlap
- fan-out launch topology
- fan-in/reduction topology
- each worker's routed selection share
- zero fallback/failure
- zero steady expert-weight movement
- graph active / no eager fallback
- graph replay/recapture count
- any serial host work proportional to worker count

The critical scaling question is whether the captured path behaves like:

`coordinator -> workers concurrently -> bounded fan-in`

rather than:

`worker A -> wait -> worker B -> wait`.

### RAM/swap validity

For every measured serving arm capture before/after decode-window:

- RSS / available memory
- swap used
- `/proc/vmstat` `pswpin` and `pswpout`
- major page faults

Swap usage after startup is not itself invalid. Measured decode actively paging expert/runtime state from SSD is.

### Runtime discipline

Keep architecture-search physical testing short.

Suggested D3 serving shape remains similar to D2:

- one short canonical workload (W4 is adequate initially)
- one discarded warmup
- three retained repetitions per arm
- bounded timing population
- no bootstrap/two-session certification yet

Target model-serving physical runtime: approximately 10–15 minutes. Hard stop: 30 minutes unless a new explicit diagnostic justifies otherwise.

Do not return to a six-hour canonical campaign until a candidate has already passed short architecture screens.

---

## 9. Immediate next action

At the time this handoff was written:

1. `inferswarm02` environment is ready.
2. D3A substrate qualification is complete and good.
3. The Qwen model had **not yet been downloaded/loaded on `inferswarm02`** during D3A.
4. D3 multi-worker code/placement had **not yet been created** during D3A.
5. FreeToken PR #14 contains the D2 substrate and is still an experimental branch pending broader regression review before merge.

The next work should therefore be:

1. verify current FreeToken PR #14 state/head before building on it;
2. download/cache the exact frozen Qwen model revision on `inferswarm02`;
3. design and generate a joint three-device placement with the constrained coordinator and two unique worker budgets;
4. extend D2's captured executor from one worker to two truly concurrent workers;
5. add fine-grained worker/dependency timing;
6. run the short `S1 / S2A / S2B / S3` D3 serving screen;
7. decide whether the measured `E3` justifies continuing to a backend-neutral asynchronous worker abstraction and, later, a second physical compute node.

Do not build network-worker plumbing before local N-worker fan-out has shown bounded scaling.

---

## 10. Key research interpretation

The current evidence progression is:

1. **Phase 1:** original eager host-orchestrated remote design is decisively nonviable (`NO-GO`).
2. **D1:** most whole-token collapse occurred because remote participation forced FreeToken out of its captured fast path; the eager distributed path added another large MoE-specific penalty.
3. **D2:** embedding resident remote work into the captured graph eliminated that catastrophe and, in the short two-GPU screen, actually improved throughput from ~54.6 to ~68.0 tok/s.
4. **D3A:** two extremely cheap Gen2 x1 worker links on a mining board maintain essentially independent large-transfer bandwidth when used concurrently; the board is a valid substrate for the first three-GPU scaling proof.
5. **D3:** must now determine whether the favorable architecture has a bounded marginal worker tax as another worker is added.

The project should continue only while new workers add meaningful capacity without a precipitous, compounding throughput falloff.

---

## 11. D3 on `inferswarm01` — primitive completion

`inferswarm02` was abandoned for D3 model execution after a substrate OOM abort. D3 migrated to `inferswarm01`; this is a host change for the architecture-search experiment, not a change to canonical Phase-1.

Physical D3 roles on `inferswarm01` are frozen:

- GPU0/coordinator: `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, BDF `03:00.0`, healthy x16.
- worker A: `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`, BDF `05:00.0`, Gen2 x1 riser.
- worker B: `GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099`, BDF `02:00.0`, Gen3 x16.

`D3B_INFERSWARM01_GOOD` established the physical topology. The captured primitive then passed real one-layer exact correctness, dynamic payload replay, whole-model capture for `a`, `b`, and `ab`, and an explicit captured concurrency control: A 17.033 ms, B 17.026 ms, AB 17.044 ms (`AB/max = 1.001`, `AB/(A+B) = 0.500`). This is physical concurrent A/B scheduling evidence, not a serving screen.

The initially attempted whole-model completion is preserved as `D3_PRIMITIVE_INVALID`: its local request completed, but an instrumentation payload-wrapper parsing defect prevented scheduler token-ID retention. The defect was repaired in FreeToken `b472a29e941f5435df12b4441960d952eee3d992`, with no production D3 runtime change.

A new clean four-arm correctness session then ran one fresh graph-enabled W4 greedy request (32-token cap) per clean server process, in order `local`, `a`, `b`, `ab`. All four exact token-ID sequences had 32 tokens and SHA-256 `c2b34b307eb0e57ac09e27b1cdc444a9e2184a245cc6bd91fe5d4fdf25a967dc`, using compact JSON token-ID encoding. The retained D3 ownership counts were:

| Shape | A | B | GPU0 local | Total |
|---|---:|---:|---:|---:|
| a | 4,718 | 0 | 5,202 | 9,920 |
| b | 0 | 4,721 | 5,199 | 9,920 |
| ab | 4,718 | 4,721 | 481 | 9,920 |

All D3 shape contracts reported BS1 graph active, exact corrected placement SHA, zero fallback/failure/recapture/steady host synchronization/steady expert-weight movement, and no dropped or duplicated routes. The generation windows had zero major faults, `pswpin`, and `pswpout`. Evidence is:

`~/inferswarm-evidence/architecture-search/d3-three-gpu-fanout/d3-whole-model-correctness-session2.json`

The fresh session supersedes the earlier incomplete INVALID for the overall D3 primitive verdict. Final primitive classification is:

`D3_PRIMITIVE_PASS_OVERLAP_CONFIRMED`

Authorization: D3 may proceed to the short `S1/S2A/S2B/S3` serving screen. That screen, and E2A/E2B/E3 calculations, have not been run here.
