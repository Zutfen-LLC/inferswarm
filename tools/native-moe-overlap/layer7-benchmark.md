# Matched layer-7 CPU / H5 benchmark

This is a routing-boundary microbenchmark, **not full-model inference, activation
replay, numerical qualification, or execution authorization**. It asks whether
H5's existing five-hot RPC / five-cold CPU path adds or saves layer execution
time relative to the ordinary all-ten CPU graph under identical inputs.

## Executed computation

`layer7_bench.cpp` calls the actual composed llama.cpp
`llm_graph_context::build_qwen4exp_ffn_native` for A and
`build_qwen4exp_ffn` / `build_qwen4exp_ffn_hot` for B. The latter still constructs
its router/shared/expert/reduction branches from native source graphs, uses the
existing RPC-v7 dispatcher and immutable encoded-slice identity guard, and joins
with the existing response-bearing `GET_TENSOR`. No parallel FFN implementation,
protocol, placement, cache, quantizer, or accepted runtime identity is introduced.

Default geometry is embedding **2560**, expert/shared hidden **640**, **512**
global experts, **10** selected slots, **one token**, zero-based layer **7**.
Gate/up are `[2560,640,512,1]`, down `[640,2560,512,1]`. Shared gate/up/down use
the same embedding/hidden geometry and Q8_0; the shared sigmoid-gate vector is
F32. `--small-test` explicitly changes embedding/hidden to 32/32, **not global
IDs or expert count**. Portable fixture builds are barred from production-size
runs by the supervisor. Default seed is 314159, CPU threads 8; hardware recipe
uses the retained CPU05 setting of 14 threads.

Weights are dense signed seeded xorshift32 synthetic values, row-scaled by
`0.35/sqrt(row_width)` and encoded with the pinned `ggml_quantize_chunk(Q8_0)`.
Shared work and all ten weighted expert slots must be nonzero. Activations are
seeded, signed, nondegenerate F32 and change each pair. `weights.json` records the observed immutable bytes once at setup: explicit
names, GGML type, four-dimensional shape, byte length and SHA-256 for expert
gate/up/down, shared gate/up/down, the F32 shared sigmoid gate, and the router
weight (also inventoried although primary routing cuts it out). `spec.json`
and `assigned.txt` retain compact-bank/slice identities; expert source hashes
reuse the complete inventory observations. Setup hashes `weights.json` and
`spec.json`; the supervisor verifies/read-binds both and recursively hashes all
native artifacts, including `assigned.txt`. No per-pair weight hashing occurs;
weights are generated/allocated/uploaded once before timing.
There is one RPC connection and one H5 owner across both cases and all pairs.

Both arms bind identical IDs and original F32 routing-weight **bits** at the
native top-k/normalized-weight cut, preserving global IDs, slot association,
native SwiGLU, shared sigmoid gate, weighting and reduction/add order. The tiny
constructor-only `benchmark_routing` hook defaults to null: no serving CLI or
environment enables it. The regression control `--small-test --control
native-routing` leaves both native routers intact and exercises default-null H5
behavior against the ordinary source CPU graph. Other small-test-only controls
zero a B-only shared down projection (omitting its contribution without a
constructor-only failure), omit one B slot's contribution, or duplicate a routing ID;
all must refuse comparison.

**Router matmul/top-k/normalization cost is excluded from both primary arms.**
In the primary bound-routing arms both graphs are cut at the same boundary and
the executor reads it directly, so neither arm performs router computation;
H5 retains its input snapshot, partition and dispatch/bookkeeping work at this
cut. The `native-routing` control keeps both native routers intact and is the
regression for unchanged router behavior. This does not answer
full-FFN including router latency or end-to-end model throughput.

## Protocol and validity

Cases: primary `mixed` (hot globals `[54,74,136,290,394]`, five cold slots), then
`all-cold` (the same slot weight bits; hot IDs replaced deterministically by
unused nonhot globals). Synthetic routing starts in noncontiguous/interleaved
slot order with nonuniform weights; slot order rotates across changed inputs.
The all-cold control uses the same H5 setup/owner, with zero RPC graph dispatches.

Each case warms **5 pairs**, then measures **20 pairs** by default (bounded CLI
limits: at most 20 warm, 100 measured, supervisor deadline at most 600 seconds).
Pair index alternates AB/BA. Both graphs persist; no reconnect, reallocation or
weight upload occurs per pair. Input/routing writes are outside both timers.
The total timer covers compute through backend/scheduler synchronization for
both arms; output retrieval and correctness diagnostics are outside both.
Production H5 telemetry emission remains inside B's outer total, as in the real
path. Reference-only nonzero diagnostics retain A's weighted/shared tensors;
this may affect arena liveness, not arithmetic or an extra timed branch.

B additionally records the existing production intervals from
`overlay/src/llama-hot-experts.cpp::execute` (no new fence or interval sum):

| Field | Exact existing boundaries / included work |
|---|---|
| `dispatch_ms` | `dispatch_start` through `dispatched`: async input, compact-ID and routing-weight setters plus `graph_compute_async` return; not remote compute completion. Zero-hot steps report 0 (no dispatch). |
| `cold_ms` | `dispatched` through `cold_done`: cold IDs/weights setters and synchronous CPU cold-branch compute. Zero-hot steps report 0. |
| `shared_ms` | `cold_done` through `shared_done`: synchronous CPU shared-branch graph. Zero-hot steps report 0. |
| `join_ms` | `shared_done` through `joined`: response-bearing remote output `GET_TENSOR` plus RPC synchronization, after shared compute. Residual remote wait/result transfer/client work, **not pure GPU or network time**. Zero-hot steps report 0. |
| `fast_ms` | Zero-hot steps only: the single synchronous CPU compute of the reusable ordinary source FFN graph (see below). Mixed steps report 0. |
| `h5_layer_ms` | Inner `start` through stats capture: input snapshot, routing-boundary copy (empty router execution when routing is native-computed; a direct boundary read in bound mode), partition, dispatch/cold/shared/join or the single fast compute, slot restoration and native reduction/shared add where applicable, and output copy. Ends **before** production `IS314_STEP` telemetry emission. |
| B `total_layer_ms` | Outer compute call plus scheduler synchronization/completion; includes production telemetry/logging overhead and graph scheduling around the inner layer. A has the same outer compute-through-synchronization boundary. Both exclude output readback/diagnostics. |

**Zero-hot fast path.** When a step's routing selects no hot expert, the
executor runs one prebuilt ordinary CPU source FFN graph — cloned once at
setup with only the routing boundary (ten IDs and weight bits) and the layer
input as private leaves — instead of splitting cold/shared/reduce across
three private computes with slot restoration. It is the same builder,
weights, slot association, weighting, shared contribution and view/add
reduction order as the ordinary CPU arm, so an all-cold step performs the
ordinary CPU work plus only the input snapshot and boundary read. The
`cold[10]` split branch is no longer built. There is no per-step allocation,
weight upload or RPC frame; transitions between mixed and all-cold steps
reuse both paths within one graph lifetime. Mixed steps are unchanged:
hot-RPC/cold-CPU overlap, join and reduction stay exactly as before.

**Do not add stages to infer total.** Overlap is intentional; join need not equal
remote execution time. Existing input/routing/result hooks report logical
payload bytes; actual wire bytes are `null` (unavailable), not inferred.

The pre-hardware frozen comparison is **`legacy-cpu-unsplit/1`**, reusing the
unchanged empirical formula at `tools/moe-overlap/moe_overlap_harness.cpp:590-620`.
For each output coordinate, `L1 = sum_slot(abs(A_weighted_slot))` over all ten
already-retained A slots, and:

```text
tol = 8 * 2^-23 * L1 + (cross_backend ? 2^-7 * L1 : 0)
if tol <= 0: tol = 8 * 2^-23
pass iff all outputs, A weighted planes and A shared plane are finite
         and every abs(B-A) <= tol
```

Native and Python `--comparison-mode cpu-loopback|cpu-cuda` select the existing
backend contract **before execution**, never infer it from observed output.
Default `cpu-loopback` sets `cross_backend=false`; the CUDA recipe explicitly
sets `cpu-cuda`. Setup freezes identity/mode/constants/plane source; Python
requires exact equality to the requested contract and validates finite metrics,
not only the native pass boolean. `max_abs`, `max_ratio = max(abs(B-A)/tol)`, RMS,
relative-L2, and `exact_equal` are retained. Exact finite F32 equality remains a
useful loopback diagnostic/regression, **not a CUDA timing requirement**. Adjacent
F32, excessive-error, nonfinite-plane/output probes and actual shared/expert
omission/bad-partition controls exercise this exact gate, including cpu-cuda.

No thresholds are fitted or widened after hardware failure. This legacy screen
is empirical, **not independent operand/backend qualification**; the independent
`moe-operand-reference/2` contract is not claimed (its backend-specific operands
and plane-mass prerequisites are absent). A refusal is terminal INVALID: raw
timing rows are diagnostics, not speedup evidence. Preserve later failures.

Duplicate/missing partitions, incorrect hot/cold counts, missing/zero shared or
expert work, nonfinite/wrong output, failed transport, abnormal native exit,
missing results or deadline invalidate the entire timing comparison. Raw rows
are retained even on failure; only a complete successful final summary is
comparable. Fail-stop RPC has no socket deadline: always use the supervisor.

`stdout.jsonl` has setup, compact pair records (case/index/warmup/order, each
arm's input/routing/output hashes, IDs/weight bits, counts, times and correctness),
then distributions (n/min/median/p95/max/mean) and paired **B-minus-A** differences.
`run.json` binds executable, all composed source inputs, compiler executables,
static and dynamic libraries, runner, flags, RPC major, host/CPU/RAM, exact argv,
recursive raw/native artifact hashes and child cleanup. It never substitutes an accepted binary
hash for the candidate. It deliberately does not claim physical GPU attribution.

## Local executable recipe

Use an already installed CMake/Ninja, existing canonical Python and authenticated
retained source archive; no package installation/download or full server build:

```bash
PY=/home/zutfen/code/inferswarm/.venv/bin/python
BUILD=/absolute/fresh/candidate
$PY -E tools/native-moe-overlap/hot-build-composed.py \
  --archive /absolute/authenticated/llama-source.tar.gz --output "$BUILD" \
  --benchmark-only --portable-fixtures
$PY -E tools/native-moe-overlap/layer7_bench.py \
  --build-receipt "$BUILD/hot-candidate-receipt.json" \
  --output /absolute/fresh/loopback --loopback --small-test --threads 2
```

`--loopback` launches only the candidate CPU worker, then terminates and reaps
that owned child even on native timeout. `--endpoint HOST:PORT` uses an external
worker without killing it. The normal supervisor default is 300 seconds; use
fresh result directories for every attempt, never overwrite a failed run.

Optional `--captured-routing /absolute/h5-run-20261018T1550Z-terminal.tar.gz`
authenticates SHA-256
`a79e3c2f9ffa9e3ffe7ede4d94d63c43976ba817aa022cd95407c7466ce9276b` and reads only
`evidence/arm-B/client/client.log` and `coordinator/immutable-prepared.json`.
Extraction retains exactly 62 routing rows: request2 steps8–38 and request5
steps84–114, original slot IDs and weight bits, member hashes and labels. No
activation tensor is extracted. For N measured pairs, native selection is
`floor(pair*62/N) mod 62`, spreading the default 20 across both windows. The
all-cold routing is explicitly derived from these rows, not historical routing.

Focused tests live in the already registered `tests.test_native_moe_overlap`:
`Layer7BenchContracts`, and `NativeHotExperts.test_matched_*` plus the existing
`test_hot_candidate_builder_is_additive`. Set `IS314_NATIVE_BUILD` to the new
`BUILD/build` to reuse the benchmark-only build. Tests exercise real CPU/RPC-v7
source graphs and identity uploads, changed-input graph reuse, AB/BA, both
partitions, source router default-null behavior, omission failures and bounded
stalled-transport cleanup. No external orchestration mock replaces arithmetic.

## Later CPU05 / GPU03 GPU0 Hermes dispatch — NOT executed here

The executable [layer7-cpu05.sh](layer7-cpu05.sh) is for a separately dispatched
hardware run. Start from the established long-lived **`ssh -A` CPU05 controller**
(`hermes@100.107.250.44`), with this reviewed worktree and retained source archive
already staged there. The script composes/builds **only** the optimized benchmark
and CPU fixture worker, launches one bounded owned copy of the unchanged accepted
GPU03 worker at `/home/hermes/is327-owned/ggml-rpc-server.cuda03`, independently
checks its SHA-256
`46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`, verifies GPU0
UUID `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`, idle compute and free port, and
uses exactly **one `-L 127.0.0.1:50060:127.0.0.1:50060`**, never `-R`, to
`hermes@100.77.187.38`. It records GPU/driver/memory/temperature before launch
and verifies the listener's executable path; no models or historical caches are
read/written. Retain existing campaign health/STOP supervision; this is not a
replacement for it.

```bash
bash /reviewed/repo/tools/native-moe-overlap/layer7-cpu05.sh \
  /reviewed/repo /authenticated/source.tar.gz /fresh/candidate /fresh/result
```

That script performs only the primary self-contained routing experiment, using
production dimensions, 5 warm + 20 measured pairs per case. No automatic retry,
rescue/comparator change, or optional captured-routing second experiment follows
failure. Worker has a 360-second external cap plus 5-second kill-after;
benchmark has a 300-second bound. `layer7_remote.py` is sent over the one SSH
master: a fresh token names `/home/hermes/is327-owned/h5-layer7-<token>/`, records
root PID/PGID, `/proc` start time/executable and verified worker identity, and tags
the whole private process group with `H5_LAYER7_OWNER_TOKEN`. No pre-existing
process or listener is terminated. The existing master carries an explicit
cleanup request on success, refusal, startup failure, INT and TERM **before**
closing local SSH children. The request verifies group identity, sends TERM
(up to 3 seconds), then KILL if needed (up to 2 seconds), and checks no owned
worker/group/listener remains. Startup and cleanup share a lock and a terminal
marker prevents a delayed launch after cleanup. Local cleanup has a 20-second
request bound plus 2-second kill-after; loss of connectivity/unknown ownership
is retained as UNKNOWN/FAILED and forces nonzero exit, never asserted success.
INT/TERM exit 130/143 and stop the local supervisor/native process group; they
do not resume the benchmark. Retain `owner-token.txt`, `worker03.log`,
`tunnel.log`, `cleanup.json`, `cleanup.log`, and remote identity/worker/cleanup
artifacts. External-command fake SSH tests exercise terminal paths without any
SSH, and local real-process tests exercise exact group termination while
preserving an unrelated same-executable process. Hardware cleanup is unexecuted
here, not certified by those tests. Existing accepted artifact
hashes are provenance facts, not authorization to execute. No SSH, GPU, optimized
production-size execution or hosted CI was performed as part of local development.
The [local validation record](layer7-local-validation.md) retains the focused
checks and disposition of the single scoped review; it grants no hardware or
merge authority.

Documentation impact is confined here: this adds an unaccepted developer
microbenchmark, not architecture/placement policy, a gate result, accepted
capability, promoted identity or physical authority; living project status is
unchanged.
