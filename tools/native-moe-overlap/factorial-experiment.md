# Bounded RPC waits × selected-expert placement experiment

This is an **unmerged diagnostic candidate**, based on reviewed warmed candidate
`4a703fdcedf5f15bb76d6ea00a12ca524eb7da37`. Creating and testing it does not
authorize hardware dispatch. No model, CI, Final Validation, PR or merge is part
of this task. The accepted worker and historical evidence stay unchanged.

The controlled single-layer fixture selects **ten useful experts per token**.
The placement factor computes either five or all ten of those same experts
remotely; it never adds work. Five-remote owns five resident experts. Ten-remote
needs **26 resident experts**, the union `0..20,54,74,136,290,394`, because T4
varied routing selects different expert sets across tokens and fixture blocks.
Selected count and resident count are different quantities.

CALCULATED: Q8_0 stores 34 bytes per 32 values. Three matrices per resident
expert at `d=2560,f=640` require
`3 × 2560 × 640 ÷ 32 × 34 × 26 = 135,782,400 bytes = 129.4921875 MiB`.
This is the encoded bank payload, excluding CUDA context, native arenas,
allocator overhead, other owners and transient staging. It is **not a
recommendation to use only 129.5 MiB of a multi-GiB GPU**. The broader goal is
useful profiled expert residency across layers and whole-model latency; this
experiment only distinguishes two factors at a fixed layer boundary.

## Frozen cells and measurement

Run T1 mixed, then T4 varied, each with ordinary CPU plus:

| Cell | Mutable input transport | Selected remote / CPU cold | Resident experts |
|---|---|---:|---:|
| current5 | Three serial SET/ACK waits in the bounded instrumented engine | 5 / 5 | 5 |
| pipeline5 | Exclusive ordered group, three existing SETs and ACKs | 5 / 5 | 5 |
| current10 | Three serial SET/ACK waits in the bounded instrumented engine | 10 / 0 | 26 |
| pipeline10 | Exclusive ordered group, three existing SETs and ACKs | 10 / 0 | 26 |

All arms use the same fixture bytes, ten selected IDs, routing/slot order,
weight bits, Q8_0 representation, CPU shared branch and final CPU reduction.
The zero-cold case explicitly has no cold tensors or cold work. Separate
resident owners prevent bank replacement between arms. Upload, readback,
graph construction and rebuild costs are recorded outside layer timing.

Per width: five warmup and twenty measured fixture blocks. Each block contains
all five arms. The prespecified order is five Latin rotations, their reversed
orders, repeated twice; every measured arm pair has ten forward and ten reverse
orders. All arms are primed exactly once with their own same fixture immediately
before their timed invocation, including CPU. Timed remote invocations must
report `GRAPH_RECOMPUTE`; the worker caches only its last graph. This creates a
new contemporaneous baseline and is not pooled with the previous warmed run.

Counts: 50 total fixture blocks, 250 timed arm invocations (200 measured/50
warmup), another 250 excluded immediate primes, and 160 measured remote-pair
replays. Every replay must reproduce the corresponding timed CPU and remote
output hashes exactly. All timed work precedes retained replay work; no timed
graph retains stages. Immutable encoded banks are read back, checked and
exported once per owner during setup, then referenced by hash from each replay.
The 16 MiB base/32 MiB stage per-capture caps remain unchanged.

CALCULATED: all immutable bank payloads total 161,894,400 B and replay tensor
payloads total 307,808,000 B, together 469,702,400 B (about 448 MiB), excluding
JSON/logs/receipts. The largest base capture is 1,106,880 B and largest stage
capture is 2,252,800 B. Do not duplicate full banks per replay. These size
calculations are not measured execution or checker timings.

## Admission and instrumentation contract

Pipelining is bounded, opt-in and client-only. It uses one exclusive dispatcher
group after prior responses are drained, preserves existing RPC-v7 frame order,
SHA-bound staging restrictions and all three admission ACKs, and admits GRAPH
only after every ACK succeeds. A concurrent drain inside the exclusive group
prevents mutual send/receive backpressure from depending on available socket
buffer space. The dispatcher is the sole reader; responses correspond by
ordered position because v7 has no per-message sequence identifier. Buffers and
headers stay immutable/alive through completion. Error, malformed/refused ACK,
EOF, timeout or SHA failure closes/aborts the connection; partially admitted
state is never reused. Assigned immutable weight uploads are unchanged; dispatch
still overlaps CPU cold/shared work and is joined before GET. There is no new
opcode and no accepted-worker rebuild.

Both transport cells hash all three mutable payloads before the exclusive queue
item is submitted and use the same bounded wire engine/counters. The current
cell retains three serial admission waits; it is a controlled contemporaneous
reference, not a byte-for-byte reproduction of the historical setter schedule.
No absolute timing difference from the old run is attributed solely to pipelining.

Record actual client command/ACK counts and bytes; monotonic submission, hash,
write, ACK, graph, join, GET and total spans; graph UID/recompute; selected,
remote, cold and resident counts; setup/rebuild/readback costs; client staging
peak and native device-memory before/after setup. Instrumentation is equivalent
across arms. Client waits do not measure server execution or GPU kernel time.
Do not add overlapping spans or subtract three full RTTs from layer latency.
Removing the observed join tail under fixed other local work bounds only that
fixed-work scenario; it does **not** upper-bound changes in transport-induced
CPU contention, scheduling or host costs.

## Checking and frozen decisions

Offline checking retains exact integrity, full output composition, supported
MMVQ conditional arithmetic, per-token expert/shared omission controls, exact
timed-to-untimed binding and the historical legacy comparator. The vendor
division/exp accuracy assumption is explicit; `numerical_qualification=false`.
Legacy finite disagreements remain visible. An unsupported arithmetic path,
nonfinite output, insensitive control, identity/replay mismatch or inconclusive
check stops acceptance; do not redesign the comparator during this run.

After all 160 reports match, report raw per-cell times and paired contrasts:
transport at five/ten; placement under current/pipelined waits; average factor
effects; and interaction `(pipeline10−current10)−(pipeline5−current5)`.
The frozen estimator takes medians of paired fixture-block contrasts, then
10,000 deterministic bootstrap resamples of whole fixture blocks. The reported
95% percentile interval uses sorted positions 249/9749 (zero based), seed
`314159 + 100×tokens + contrast_index`. These are within-session intervals,
not independent-run or population uncertainty; report that limitation.

Assess T1 and T4 independently. The conservative adoption screen is at least
10% median paired gain over CPU and upper paired median-difference 95% interval
below zero, with all checks passing. Smaller measured gains still count as
observations and must be reported honestly. A decode benefit need not win T4,
or vice versa. If only the combined cell passes at a width, recommend both
factors there. If ten/current passes and pipelining adds less than 5% at that
width without decisive interaction, defer transport complexity. Otherwise
report the measured effects and uncertainty; no post-hoc workload extension,
tuning or retry until success.

## Bounded execution and feasibility

| Phase | Hard bound | Conditions |
|---|---:|---|
| Preparation | 900 s | Build client/CPU fixtures and arithmetic helper before worker start |
| Native | 300 s | Setup, primes, measured work and every replay; no offline analysis |
| Accepted worker | 360 s | External timeout, explicit token-owned process-group cleanup |
| Offline analysis | 900 s | Only after verified worker/listener absence |
| Complete retained result | 8 GiB | Supervisor monitors native output; launcher checks result tree |

Preflight requires CPU05 `MemAvailable ≥8 GiB`, result filesystem free space
`≥9 GiB`, idle accepted GPU0 and `≥2048 MiB` device free before worker start.
These conservative floors reserve room for whole CPU synthetic weights, native
arenas, CUDA context and staging. They do not claim measured fit. The suggested
**512 MiB additional GPU allocation envelope is an estimate**: native preflight
also checks at least 1 GiB free after worker/context initialization, records
before/after setup free memory, stops if setup delta exceeds 512 MiB and retains
at least 512 MiB free afterward. A failed floor or exceeded envelope is terminal;
document a justified adjustment separately before any future dispatch.

The supervisor's `valid=true` means structural execution complete only.
`timing_comparison_valid=false` remains until independent full replay analysis;
physical device attribution also requires the external worker/UUID evidence.
Preparation, native and checker timings measured locally are fixture-tool
costs, not CPU05/GPU03 performance predictions. Use fresh paths and preserve
partial receipts/logs on every outcome. No automatic cap increase is permitted.

Local CPU-only diagnostic costs measured during candidate preparation:

| Work | MEASURED local result | Interpretation |
|---|---:|---|
| Fresh final CPU candidate build | 86.1526 s | Includes source composition/configure/build and source-bound receipt; excludes helper compilation |
| Final source-bound supervisor native CPU loopback | 48.3150 s; peak native RSS 3,570,708,480 B | Full geometry/grid with local CPU worker and verified child reaping; no GPU fit claim |
| Full production-geometry native CPU loopback, development snapshot | 47.7505 s total, including 41.5158 s setup | All 50 fixture blocks, 160 measured pairs/replays; no CUDA/tunnel prediction |
| Final source-bound full offline CPU checker | 133.8622 s | 160/160 CPU-loopback matches; six unique banks read, 161,894,400 B cached |
| Final source-bound retained native tree | 479,816,162 B | Includes tensor payload plus native JSON metadata |
| T1 five/ten native RPC arenas | 386,880 / 1,564,928 B | Backend requested arenas, not actual GPU memory consumption |
| Five/ten compact encoded bank payloads | 26,112,000 / 135,782,400 B | Separate persistent resident owners |
| Five/ten client upload staging peaks | 8,704,000 / 45,260,800 B | Largest one-bank staging, separate from resident payload |

All 200 local timed remote-pair records matched the original warmed evidence's
fixture input/routing hashes, selected IDs and weight bits; the source
`weights.json` was byte-identical. These establish controlled fixture reuse,
not physical GPU correctness or performance. The full offline checker cost and
verdict are local CPU evidence. Its zero legacy disagreements do not remove or
relabel the eleven historical warmed CPU/CUDA legacy disagreements.

Focused local commands (no SSH/GPU/models):

```bash
python3 -m unittest tests.test_factorial_run tests.test_factorial_check \
  tests.test_factorial_rpc_transport
python3 tools/native-moe-overlap/factorial_run.py \
  --build-receipt /ABS/FRESH-BUILD/factorial-candidate-receipt.json \
  --output /ABS/FRESH-LOCAL-RESULT --loopback --small-test --quick \
  --threads 2 --timeout 300 --comparison-mode cpu-loopback
python3 tools/native-moe-overlap/factorial_check.py \
  --replays /ABS/FRESH-LOCAL-RESULT --helper /ABS/HELPER.so \
  --output /ABS/FRESH-LOCAL-CHECK.json --small-test-grid
```

`--quick` is restricted to small local CPU geometry: one warmup/two measured
blocks per width, no adoption screen. Full default geometry/grid must be used
for the proposed hardware attempt. There is no general token/pair/seed tuning
surface in this supervisor.

## Self-contained future Hermes prompt

Execute only after a separate explicit hardware dispatch. Use the exact
published remote SHA supplied with this handoff, in a fresh checkout on CPU05,
preserving previous tasks/results. Source repository is
`Zutfen-LLC/inferswarm`; base is warmed candidate
`4a703fdcedf5f15bb76d6ea00a12ca524eb7da37`, native pin
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. Record current main separately;
do not rebase the candidate. Read `AGENTS.md` and this entire recipe.

Use the established long-lived controller's agent-forwarded SSH-A CPU05 session
(`hermes@100.107.250.44`, hostname `inferswarm05`) for the entire start/run/cleanup
lifetime. GPU03 is `hermes@100.77.187.38`; GPU0 is UUID
`GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`; leave GPU1 untouched. Preserve the
single local forward and its SSH master through acknowledged cleanup. No model
loading, hardware/configuration changes, CI, PR, Final Validation or merge.

Use only these existing artifacts, with no download/install:

- CPU05 native archive `/home/hermes/is319-stepa/pin.tar.gz`, SHA-256
  `03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`.
- GPU03 accepted worker `/home/hermes/is327-owned/ggml-rpc-server.cuda03`, SHA-256
  `46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`.
- Existing CPU05 C++ compiler, CMake, Ninja and Python. No geekom-only file is
  required. Do not rebuild/replace the accepted CUDA worker.

In the fresh clean exact-SHA CPU05 checkout, replace the SHA below with the
published handoff SHA. Fresh absolute paths are mandatory:

```bash
set -euo pipefail
expected_sha=EXACT_PUBLISHED_CANDIDATE_SHA
repo=$PWD
test "$(git rev-parse HEAD)" = "$expected_sha"
base=/home/hermes/is-layer7-factorial-${expected_sha:0:12}
mkdir "$base"
printf '%s  %s\n' \
  03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723 \
  /home/hermes/is319-stepa/pin.tar.gz | sha256sum --check
bash "$repo/tools/native-moe-overlap/factorial-cpu05.sh" "$repo" \
  /home/hermes/is319-stepa/pin.tar.gz "$base/cpu-build" "$base/result" \
  >"$base/launcher.log" 2>&1
# Nonzero launcher is terminal. On any outcome retain cleanup proof/logs;
# do not run analysis until owned-worker/listener absence is verified.
python3 - "$base/result/cleanup.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['cleanup']=='verified' and r['owned_worker_absent'] and r['owned_listener_absent']
PY
timeout --signal=TERM --kill-after=5 900 python3 \
  "$repo/tools/native-moe-overlap/factorial_check.py" \
  --replays "$base/result/benchmark" --helper "$base/cpu-build/helper.so" \
  --output "$base/check.json" >"$base/analysis.log" 2>&1
```

Require checker exit 0 and all 160 conditional-profile matches, sensitive full
expert/shared controls, exact per-arm replay binding, and same-request accepted
worker/device attribution before reporting conditional timing observations.
Report all raw per-cell times and paired effects per width, selected versus
resident counts, setup/allocation evidence, legacy disagreements, achieved
budgets and cleanup proof. Preserve exact source HEAD, build receipt/compiler
identities, build/preparation logs, helper/checker hashes, complete result tree,
checker progress and launcher logs in the evidence bundle. Recheck complete
retained size against 8 GiB before archiving. A failure/timeout/inconclusive is
the result of this one attempt: preserve it and stop, without a second run.

## Validation scope

The final candidate passed 31 focused local CPU/loopback tests. One independent
correctness/transport/fairness review found no material blocker to unmerged
diagnostic publication, including separate real-dispatcher compatibility with
the unchanged CPU-v7 helper. No hardware or numerical qualification follows.
Local tests used the available Python 3.14; the canonical Python 3.12 full suite
and hosted CI were not run. Publication uses a skip-CI commit as requested.

Documentation impact: this opt-in diagnostic changes no demonstrated hardware
capability, acceptance, integration branch or execution authority; living
project-status records remain unchanged. New test modules are declared in the
existing MoE group and retention registry. The complete retention audit still
reports four inherited warmed-base layer7 test modules without audit entries;
those base records and producer files were preserved. The targeted group
workflow/registry identity check passes; this is not full CI qualification.
