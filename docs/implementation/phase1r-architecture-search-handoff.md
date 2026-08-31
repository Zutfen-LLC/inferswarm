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

---

## 12. D3 serving screen — valid completion

The frozen short W4 serving screen ran on `inferswarm01` in the mandated fresh-process order `S1`, `S2A`, `S2B`, `S3`, with one discarded warmup and exactly three retained greedy 128-token generations per arm. It used FreeToken `9aa113e3` (a measurement-only harness commit on top of accepted runtime/correctness SHA `b472a29e941f5435df12b4441960d952eee3d992`), handoff `1118320ce17c702c6dc1c16cd36825e412dc05db`, and frozen placement SHA `6677fe1c506376a55aa8dcabb8d5761dc0373ced9d9b053209991059556d5887`. Common geometry was GPU0 `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, TP1, offload, zero CPU MoE layers, Triton NVFP4, 3,774 GPU0 cache slots, 17,075 KV/runtime tokens, one running request, and graph BS `[1]`.

| Arm | Retained decode tok/s | Median decode tok/s |
|---|---:|---:|
| S1 | 52.8961, 53.2212, 53.2395 | 53.2212 |
| S2A | 54.2339, 54.4818, 54.4867 | 54.4818 |
| S2B | 66.7866, 67.8157, 67.8542 | 67.8157 |
| S3 | 51.1066, 51.2780, 51.2377 | 51.2377 |

Thus `E2A = 1.023686`, `E2B = 1.274224`, and `E3 = 0.755544`, with `S3/S1 = 0.962732`, `S3/S2A = 0.940457`, and `S3/S2B = 0.755544`. The first resident worker is approximately neutral on the Gen2 x1 A path, while B's Gen3 x16 path improves W4 decode throughput by 27.4% versus S1. S3 does not exceed B-only throughput but retains 75.554% of it while adding another 3,000 resident identities.

| Arm | A selections/share | B selections/share | GPU0 local selections/share |
|---|---:|---:|---:|
| S2A | 77,900 / 47.920768% | 0 / 0% | 84,660 / 52.079232% |
| S2B | 0 / 0% | 77,518 / 47.685778% | 85,042 / 52.314222% |
| S3 | 77,900 / 47.920768% | 77,518 / 47.685778% | 7,142 / 4.393455% |

All D3 ownership arithmetic was exact with no dropped or duplicated routes. Every D3 arm retained zero fallback, failure, graph recapture, steady host synchronization, and steady expert-weight H2D; every retained generation completed at 128 tokens with zero process major faults, `pswpin`, and `pswpout`. Total generation wall including warmups was 71.626 s; fresh-process startup/ready time was 559.802 s. The bounded generic MoE timing surface produced an S1 complete-layer median of 0.233 ms (p95 0.777 ms); D3 component intervals were unavailable/not-applicable, so they are not combined into a critical-path claim.

Final classification is `D3_SCALING_PROMISING`; `COMPOUNDING_MARGINAL_PENALTY = false`. The result justifies one further bounded architecture question: whether this marginal retention persists with a fourth worker and/or a deliberately heterogeneous low-cost resident worker. No follow-on experiment was started. Host-local raw evidence remains under `~/inferswarm-evidence/architecture-search/d3-three-gpu-fanout/` and is not committed here. Canonical Phase-1 NO-GO remains unchanged.

---

## 13. D4 capability-weighted heterogeneous placement

D4 tested whether D3's equal route-pressure placement made the faster worker wait for the slower worker. It changed placement only: the D3 GPU0-local plus independent A/B fan-out, wait, reconstruction, and canonical sum topology remained unchanged. No fourth GPU, network worker, or D5 work was introduced.

### Startup reuse

An unchanged D3 S3 baseline startup was profiled at 200.149 s. Approximate phase walls were 14.002 s GPU/runtime initialization, 10.076 s non-expert model loading, 48.967 s normalized expert-bank materialization, 121.068 s resident-worker loading, 5.117 s graph capture, and 0.919 s other. Process-group checkpoint-window reads were approximately 26.211 GB; disk reads overlap parsing/materialization, so those phase estimates are not additive.

FreeToken added a benchmark-only, CUDA-free parent that stages the exact immutable model snapshot read-only in tmpfs and launches every arm as a new subprocess. Only snapshot files are reused. Engine, CUDA allocator/runtime state, GPU0 cache, resident banks, KV state, streams/events, graphs, counters, pointers, and request state remain fresh. Three fresh-engine startups were 163.537, 164.520, and 163.509 s: median 163.537 s, 1.224x versus baseline, saving 36.613 s per arm. Remaining phase medians were about 5 s non-expert loading, 17 s expert-bank materialization, 121 s resident loading, and 5 s capture. The one-time full-copy plus byte verification cost 239.258 s and amortizes after approximately seven arms; D4 used more than seven fresh model starts across reuse measurement, calibration, correctness, and serving, so no broader loader redesign was pursued.

### Frozen calibration and placement

FreeToken `c74e3c94105e23398a39f707e5d63a03f820116f` measured the already-proven captured D3 one-layer physical path for 200 repetitions per isolated worker:

| Worker | Median | p95 | max |
|---|---:|---:|---:|
| A, Gen2 x1 | 279.9410 us | 287.5119 us | 292.5740 us |
| B, Gen3 x16 | 177.9415 us | 191.6544 us | 204.6130 us |

Both calibration arms had zero major faults, paging, fallback, failure, recapture, steady host sync, and steady expert-weight movement. Frozen inverse-service targets were A 38.861826% and B 61.138174%. Calibration evidence SHA-256 was `a7b0a0fa2e32ed25109985f64e26bcba54b0d3afe50494c4646a4d079558cc79`.

InferSwarm commit `c7e0dc0` froze placement SHA-256 `283595b7559bb3aa46a08c7d00cfef1e0a77eb62967d6392c618a63f35d34cdf` before D4 execution/performance. It preserves the exact D3 top-6000 remote union, 3,000 identities per worker, 3,774 GPU0 dynamic-cache slots, and the 4,240-identity local remainder. Exact-rational deterministic derivation predicts W4 remote shares A 38.857414% / B 61.142586% and normalized service walls 104.269068 / 104.288431 us, an absolute difference of 0.019363 us.

### Correctness and serving result

FreeToken `1935ca0c80bc2163e5541d89f8430d3c15580769` passed the D4 SHA-pinned parser, exact banks/ownership, whole-model BS1 capture, real mixed A+B+local oracle, changed payload without recapture, and graph-local versus weighted deterministic W4 equality. Final gate: `D4_PLACEMENT_PRIMITIVE_PASS`. D3's concurrency proof remains applicable because execution code/topology did not change.

The matched screen ran D3 equal control then D4 weighted, each with one discarded warmup and exactly three retained 128-token W4 generations:

| Arm | Retained decode tok/s | Median |
|---|---:|---:|
| D4-CONTROL | 51.061229, 51.237563, 51.255660 | 51.237563 |
| D4-WEIGHTED | 51.089438, 51.252748, 51.267758 | 51.252748 |

Weighted measured total route shares were A 37.294537%, B 58.312008%, and GPU0 4.393455%; the remote-only split was A 39.008352% / B 60.991648%, close to the frozen capacity target. Control remote split was A 50.122894% / B 49.877106%. Despite that large physical routing change, median inter-token wall was effectively unchanged (19.372838 ms control, 19.365014 ms weighted).

- `WEIGHTED_GAIN = 1.000296362`
- `WEIGHTED_VS_S2B = 0.755765223`
- `WEIGHTED_VS_S1 = 0.963013754`
- final classification: `D4_WEIGHTING_NEUTRAL`

Both arms had exact ownership, identical GPU0-local counts, zero fallback/failure/recapture/steady host synchronization/steady expert-weight movement, and zero retained major faults, `pswpin`, or `pswpout`.

The leading slow-worker critical-path hypothesis is not supported: capability weighting moved remote pressure from roughly 50/50 to 39/61 without moving throughput. Do not add another worker yet. The next bounded experiment should add non-perturbing worker-completion and join/fan-in timing under equal and weighted placement, then isolate fixed two-worker graph/host-staged transport tax from GPU0 reconstruction/local work and PCIe contention. Canonical Phase-1 NO-GO, D2, and D3 remain unchanged.

---

## 14. D5 resident loading and compact physical route execution

D5 was a new post-NO-GO architecture-search experiment with two independent tracks. D5-L changed startup residency only; D5-C changed the experimental decode executor. Canonical Phase-1, D2, D3, and D4 results remain frozen.

### D5-L startup-only result

The opt-in legacy microprofile reproduced the resident bottleneck: worker A loaded in 73.220 s, worker B in 47.924 s, and serial A+B in 120.988 s. Each worker transferred and verified 5,326,848,000 bytes in each direction. A used 714 chunks averaging 7.461 MB; B used 684 averaging 7.788 MB. In the matched serial AB run, A spent 14.453 s in H2D, 13.031 s in D2H verification, and 43.845 s in CPU equality/SHA work; B spent 0.849 s, 1.448 s, and 43.989 s respectively. This measurement shows that exact CPU verification/hash work, plus A's Gen2 x1 round trip, dominated rather than source gathering or GPU scatter.

The frozen D5 loader uses one exactly sized pinned staging tensor per bank in final remote-slot order, six large H2D transfers per worker directly into final resident tensors, no GPU `index_copy_`, one large D2H verification per bank, exact byte comparison, deterministic SHA-256, prompt staging release, explicit devices, and concurrent A/B materialization. A bounded 1/2/4/8 CPU-worker sweep produced concurrent AB walls of 65.018, 63.569, 64.404, and 61.822 s. Eight workers were frozen before D5-C because they were fastest and stable.

Final isolated bulk walls were A 61.190 s and B 35.135 s; concurrent AB was 61.822 s, close to `max(A,B)` rather than their sum. Resident-wall speedup was 1.957x versus the freshly profiled 120.988 s legacy serial wall. Matched full startup fell from 201.673 s to 145.547 s (1.386x, 56.126 s saved). The useful 2x target was narrowly missed, but the safe improvement should be retained for future architecture-search work.

Legacy and bulk paths retained exact slot mapping, tensor shape/dtype/layout, auxiliary tensors, native raw bytes without conversion, accounting, and fail-closed restoration. Per-tensor source/resident exact comparison and SHA verification passed on both A and B. Real one-layer output was exact, and graph-local versus bulk compact AB produced identical 32-token W4 output with SHA-256 `c2b34b307eb0e57ac09e27b1cdc444a9e2184a245cc6bd91fe5d4fdf25a967dc`. D5-L is not a decode-scalability result.

### D5-C mechanism and correctness

The fixed-width diagnostic used captured real resident NVFP4 worker execution and same-device CUDA events. Median duration in milliseconds for useful counts `0/1/2/4/6/8` was:

| Worker | 0 | 1 | 2 | 4 | 6 | 8 |
|---|---:|---:|---:|---:|---:|---:|
| fixed A | 0.089088 | 0.089088 | 0.089088 | 0.089088 | 0.089088 | 0.089088 |
| fixed B | 0.088960 | 0.088864 | 0.088864 | 0.088896 | 0.088960 | 0.088752 |

This directly confirms that zero-weight non-owned routes left physical fixed-width work essentially unchanged.

The separate D5 executor performs stable device-only compaction into fixed-capacity K buffers, transfers fixed-capacity metadata, carries device-resident active counts, exits inactive Triton programs before expert-weight access, deterministically zeroes inactive tails, scatters compact route contributions back to exclusive original positions, and performs exactly one canonical route-order reduction. GPU0 expert compute is count-aware. The experimental cache planner still sees valid fixed-capacity tail IDs; dummy cache planning remains and is reported, but dummy expert compute is eliminated.

Compact duration and `duration(count)/duration(8)` were:

| Worker | 0 | 1 | 2 | 4 | 6 | 8 |
|---|---:|---:|---:|---:|---:|---:|
| compact A ms | 0.015360 | 0.040960 | 0.055296 | 0.061440 | 0.074752 | 0.089088 |
| compact A ratio | 0.172 | 0.460 | 0.621 | 0.690 | 0.839 | 1.000 |
| compact B ms | 0.016384 | 0.040752 | 0.054992 | 0.061264 | 0.073728 | 0.089088 |
| compact B ratio | 0.184 | 0.457 | 0.617 | 0.688 | 0.828 | 1.000 |

All-local, all-A, all-B, mixed A+B+local, stable positions, 0..K counts, dynamic consecutive count changes, inactive-tail zeroing, one-layer local-oracle equality, graph BS1, and whole-model short equality passed. The targeted loader/compaction/D3/D4 regression run reported 131 passed and 6 skipped. Final primitive classification: `D5_COMPACT_PRIMITIVE_PASS`.

### D5-C serving result

FreeToken `b7c857a7fe7afe716a7f6b6ae4bda2ae72060a92` ran the frozen serving order F0, C1, C2, C3. Every arm used a fresh Engine/GPU state, the frozen eight-worker bulk loader, one discarded warmup, and exactly three retained greedy 128-token W4 generations.

| Arm | Retained decode tok/s | Median |
|---|---:|---:|
| F0 fixed equal S3 | 51.021228, 51.188824, 51.185105 | 51.185105 |
| C1 compact B | 73.171028, 74.438260, 74.477759 | 74.438260 |
| C2 compact equal S3 | 57.152054, 57.273206, 57.293662 | 57.273206 |
| C3 compact weighted S3 | 57.824755, 57.952018, 57.932780 | 57.932780 |

- `COMPACT_EQUAL_GAIN = 1.118942832`
- `COMPACT_E3_EQUAL = 0.769405492`
- `COMPACT_WEIGHTING_GAIN = 1.011516277`
- `COMPACT_E3_WEIGHTED = 0.778266178`
- `C2 / historical D3 S3 = 1.117794239`
- `C3 / historical D3 S3 = 1.130667067`
- `C3 / historical D3 S2B = 0.854267964`

F0 equal ownership was A 77,900, B 77,518, local 7,142; its remote split was A 50.122894% / B 49.877106%. C2 had the same logical ownership, but physically executed exactly 77,900 A, 77,518 B, and 7,142 local expert invocations, skipping 169,702 remote dummy invocations and 155,418 local-tail invocations across the observed calls. C3 moved ownership to A 60,626, B 94,792, local 7,142; its remote split was A 39.008352% / B 60.991648%, and physical invocations exactly matched those owned routes. C1 executed 77,518 B and 85,042 local routes, with no A branch.

Every arm had exact ownership with no drop/duplication, zero fallback/failure/recapture/steady host synchronization, zero steady expert-weight movement, zero retained major faults, and zero `pswpin`/`pswpout`. Direct throughput is authoritative; overlapping timing components are not summed.

Formal classification is `D5_DUMMY_TAX_CONFIRMED`: eliminating dummy physical route compute improved matched equal S3 by 11.894%. Capability weighting remained neutral after compaction (`1.0115x`, within 0.97–1.05). Compact equal and weighted marginal retention are both promising, not strong (`0.7694` and `0.7783`, below 0.90).

The next bounded experiment should isolate the remaining fixed-capacity host-staged activation/metadata/return transfers, GPU0 return H2D, fan-in event/wait behavior, reconstruction, PCIe contention, and graph-node overhead. A fourth/heterogeneous worker is not yet recommended because compact retention did not reach the predeclared strong 0.90 region. No D6 or fourth worker was started. Host-specific evidence remains under `~/inferswarm-evidence/architecture-search/d5-compact/` and is not committed.
