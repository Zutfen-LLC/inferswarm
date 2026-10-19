# Bounded weighted remote-output reduction

Unmerged, default-off diagnostic successor of published
`diag/layer7-transport-placement-2x2` at exact
`3bbecbfdb4950d18f1e2da4e7ca02751f3df3ae4`. Main was recorded separately as
`5a28198f7f514b22e01e8204dc5499a173b0f569` on 2026-10-19; do not rebase.
The original factorial and layer7 producer files and historical evidence are
unchanged. This candidate does not authorize hardware execution, CI, PR or merge.

The supplied prior CPU05/GPU03 result had T1 CPU/current5/pipeline5/current10/
pipeline10 medians 1.804/4.036/3.554/4.485/3.540 ms; T4 medians
3.924/7.244/7.156/8.904/7.964 ms. No remote cell beat CPU. The supplied report
had 160 conditional matches and twenty finite legacy disagreements, with
`numerical_qualification=false`. These numbers are supplied context, not a
locally verified hardware bundle. They motivate this hypothesis, not a latency
prediction. The goal remains capability- and demand-profiled placement using
available VRAM, not a permanent small-VRAM policy.

## Feasibility and semantics

`reduction-overlay/src/llama-hot-experts.cpp` is a separate experiment overlay.
The owner uploads the same three compact Q8_0 banks once in `setup()`, checks
identity, and retains the device buffers across width/graph rebuilds. Those
resident weights are separate from the worker's last-graph cache. Every arm
receives its own excluded immediate prime because v7 remembers only its most
recent graph. Timed calls must use `GRAPH_RECOMPUTE`.

The branch does gate/up projections, per-expert SwiGLU, down projection, and
routing-weight multiplication before reduction. In each reduced graph, views
select `[d,T]` planes from `[d,selected,T]` in branch slot order, followed by
explicit left-to-right F32 ADD nodes and CONT. Existing RPC-v7 serializes these
operations; no opcode, worker, kernel, or accepted identity changes. The pinned
CUDA backend supports them. A CONT between MUL and VIEW prevents its weighted
MoE fusion matcher from spanning weighting and summation; view nodes separate
successive ADDs. No weights are pushed per step.

Both graph families share each placement's compact banks, and both are
preallocated outside timing. The reduced family adds graph/arena memory, which
is included in setup memory and the unchanged 512 MiB allocation-delta cap.
The bounded client workspace remains allocated for ten planes; this is a
return-traffic experiment, not a host-memory saving claim.

With `IS_REDUCED_OUTPUT` absent or `0`, the original per-plane result is
returned, restored to original slot order, and fed through the cloned source
reduction. Value `1` selects a prebuilt reduced graph and returns only its
`d*T*4` bytes. Any other value fails. Both use the same pipelined three SET/ACK
admissions, routing/selection/weights/input bytes, CPU cold branch, CPU shared
branch, and five total RPC commands. The experimental harness sets this flag
explicitly per arm; inherited flags are refused.

For five remote experts, final arithmetic changes from the original interleaved
left fold to `remote-left-fold + each CPU cold slot in original order + shared`.
The CPU adds execute one F32 addition per step. For ten remote experts the slot
fold order is unchanged. Bitwise equivalence with ordinary CPU is not promised
for mixed placement. The old legacy comparator and its tolerance remain
unchanged, are reported, and do not decide the new exact composition check.

## Numerical check and retention

`reduction_check.py` retains the original operand-driven conditional MMVQ
projection/SwiGLU profile and CPU reference path. Vendor division/exp accuracy
limits remain conditional; numerical qualification is always false. The new
assumption is finite F32 RN ADD with normal operands/intermediates (exact zero
allowed), without FTZ/underflow/overflow. Unsupported values are inconclusive.

Reduced replay captures retain every selected weighted plane and the actual
remote sum, consumed inputs/IDs/weight bits, CPU cold planes and shared output.
Only the untimed diagnostic graphs mark the extra nodes as OUTPUT, preventing
arena reuse before readback. Timed graphs do not retain those planes and issue
one GET for the selected output only. Every untimed final A/B output must hash
exactly to its own timed invocation; any retention/fusion-induced discrepancy
is a terminal STOP. All timed work precedes replay/readback/checking.

The checker reconstructs the ordered remote sum and complete grouped final
output from retained weighted planes with **zero-ULP exact F32 byte comparison**.
It rejects each omitted expert/shared contribution, wrong-token output, routing
or compact-map defect and stale replay binding; insensitive controls stop
acceptance. Original per-plane captures are still checked in source slot order.

Rounding telemetry compares two folds of the *same B weighted planes*: the
original interleaved fold and grouped fold. Each has ten additions over eleven
terms including shared. With `u=2^-24`, the standard forward-error bound for
either order is `gamma_10*sum(abs(terms))`, where `gamma_10=10*u/(1-10*u)`.
Their difference is therefore bounded by `2*gamma_10*sum(abs(terms))` coordinate
by coordinate. The checker enforces that bound and reports observed maximum
regrouping error. It is telemetry, not extra tolerance on the final output,
not a bound on heterogeneous projection differences, and not a replacement
for the vendor-profile limitations or legacy outcomes.

## Frozen compact comparison

Use `reduction-build.py`, `reduction_run.py`, `reduction_check.py` and
`reduction-cpu05.sh`. Existing ownership and cleanup helper
`factorial_remote.py` and bounded wire engine are reused unchanged.

Five arms per fixture block: ordinary CPU, pipeline5, reduced5, pipeline10,
reduced10. Five/ten selected remote remain distinct; all select the same useful
ten experts per token. Five/26 resident experts remain distinct from selected
counts. Keep production d=2560, m=640, 512 experts, top-k=10, Q8_0; T1 mixed and
T4 varied; fixed seed314159; five warmup/twenty measured blocks per width; five
Latin rotations and reversed rotations repeated twice. Every measured arm pair
has ten forward and ten reverse orders. One same-fixture prime immediately
precedes every timed arm, including CPU. No serial transport cells are rerun.

Totals: 50 blocks, 250 timed invocations, 250 excluded primes, 160 measured
remote/CPU replay checks. Banks export once per placement. Existing 16 MiB
base/32 MiB stage capture caps and 8 GiB result cap remain; extra remote-sum
captures add a CALCULATED 2,048,000 B over the original full-grid payload.

Expected actual received bytes, including three ACK frames and GET framing:

| T | pipeline5 | reduced5 | pipeline10 | reduced10 |
|---|---:|---:|---:|---:|
| 1 | 51,235 | 10,275 | 102,435 | 10,275 |
| 4 | 204,835 | 40,995 | 409,635 | 40,995 |

These are CALCULATED expectations until measured by client counters. The checker
requires exact RX values, unchanged SET/ACK/GRAPH/GET counts, pipeline=true and
equal transmitted payload/wire bytes within each selected-count comparison.
Setup, rebuild, arenas, staging and persistent bank payloads remain reported.
Client spans cannot distinguish RTT, server overhead and GPU execution.
The output-mode contrast measures GPU reduction plus reduced return traffic
and the changed CPU tail together; it does not isolate network bytes alone.

Report T1/T4 separately with raw per-arm observations and paired reduced-minus-
planes effects at five/ten, placement effects under each output mode and their
interaction. Keep the previous deterministic 10,000 whole-block bootstrap,
seed314159+100*T+contrast_index, endpoints249/9749, and explicitly within-session
uncertainty. The >=10% median paired gain over CPU with upper95% paired median-
difference below zero screen is unchanged; report smaller gains honestly.

## Bounds and future hardware handoff

One separately authorized invocation only, <=45 minutes and $0. Preparation900s,
native300s, worker360s external timeout and explicit token-owned process-group
cleanup, offline analysis900s after acknowledged cleanup. Preserve partial
results on every failure; no retry-until-PASS or cap increases. CPU MemAvailable
>=8GiB, result free>=9GiB; idle accepted GPU0 free>=2048MiB, native post-context
free>=1GiB, setup delta<=512MiB and post-setup free>=512MiB. Leave GPU1 untouched.

CPU05: hermes@100.107.250.44 (`inferswarm05`). GPU03: hermes@100.77.187.38.
GPU0 UUID `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`, bus01:00.0 x16.
Accepted worker `/home/hermes/is327-owned/ggml-rpc-server.cuda03`, SHA256
`46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`.
Native archive `/home/hermes/is319-stepa/pin.tar.gz`, SHA256
`03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`,
native pin `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`.
Known Ninja `/home/hermes/is-layer7-warmed-4a703fdc/helpers/ninja` is prepended
by the launcher. Fresh candidate client/CPU build allowed; accepted CUDA worker
unchanged. No install/download/model rehash/acquisition/full-model run.

Use the established long-lived agent-forwarded SSH-A controller on CPU05 and
keep its single local forward and SSH master alive through acknowledged
cleanup. The script owns only its token-tagged worker group; never kill by name
or replace accepted files. Read the complete prior `factorial-experiment.md`
for the inherited instrumentation and cleanup contracts. Source dispatch
commands and exact published SHA accompany this candidate outside this file.

Local diagnostic preparation may use `reduction-build.py --retained-receipt`
with an authenticated retained factorial receipt; it checks every input and
copies the old composed source into a fresh directory. This does not edit the
prior worktree/build. Hermes uses the authenticated archive route, not a
geekom-only path. A local CPU smoke proves neither GPU behavior nor latency.

Documentation impact: this opt-in candidate changes no demonstrated capability,
acceptance, integration branch or hardware execution authority. Living project
status remains unchanged. New tests are declared in the existing MoE group;
full suites, hosted validation and PR workflow are explicitly deferred.
