# Warmed conditional MMVQ sweep preparation

Experimental continuation of `7373914779ddb1aa319bca8bab549a35588510a9`.
The [conditional numerical profile](layer7-conditional-profile.md) is unchanged:
vendor division/exp accuracy is an explicit assumption, T=16/MMQ is unsupported,
and `numerical_qualification=false`. Historical INVALID results remain INVALID.
Main was separately recorded as `5a28198f7f514b22e01e8204dc5499a173b0f569`;
this candidate does not rebase the experiment onto a newer main.

## Frozen work and acceptance

Opt-in `--warmed-operand-sweep` requires seed 314159, widths 1,2,4,8, five
warmup and twenty measured pairs per case. Cases are T=1 mixed, and T=2/4/8
mixed varied/shared sets: 35 warmup and 140 measured pairs. Every measured
case has ten AB and ten BA orders, alternating by pair index. Warmups do not
enter the performance report or require replay captures.

After **all** timed work, replay all 140 measured pairs into
`native/replays/t<T>-<CASE>-p<PAIR>`. Retained graphs are rebuilt once per width
and safely reused within that width; timed graphs retain no stages. Each replay
must match both corresponding timed output hashes exactly. The checker requires
the exact ordered timed and replay grids, full pair-record equality at the
expected directory, external stdout binding, consumed inputs/routing, slot
mapping, weight identities and the existing full arithmetic/control conjunction.
No sampling, tolerance change or changed quantization byte exception is used.

Only finite legacy numerical disagreement can continue in the explicit operand
mode. Nonfinite output, bad partition/token count, zero expert planes, capture
failure and consumed identity/replay mismatches stop or invalidate. All per-token
expert/shared omission controls remain mandatory; zero mass, rounding-insensitive
controls and bounds too broad to reject missing work produce inconclusive.
Cold/shared arithmetic remains relative to the trusted same-input CPU arm.
Same-request worker/device attribution remains an external prerequisite.

The native warmed summary withholds case statistics. After every measured replay
passes arithmetic, identity, binding and sensitivity checks, the offline report
adds `conditional_performance`: A/B median, min/max and nearest-rank p95; paired
B-A distribution; latency/token, tokens/second; B-faster count and AB/BA counts.
Only measured `total_layer_ms` wall times enter these statistics. Setup, warmup,
replay and checking are excluded; overlapping stage timers are never summed.
These are assumption-dependent experimental observations, not numerical or
performance qualification. `performance_claim=false` and all legacy verdicts
remain separately visible. The old one-pair/no-warmup mode remains available.

## Local preparation evidence and budgets

Geekom local CPU fixtures only; no model, CUDA, SSH or hardware dispatch:

- Fresh optimized CPU build from the authenticated native archive completed in
  approximately 94 seconds (configure-log completion to receipt: 93.44 seconds).
- The full small-geometry grid completed 35 warmups, 140 measurements and 140
  replays; all 140 offline reports matched with sensitive controls and exact
  binding, in 5.62 seconds.
- Separate production-geometry single-pair fixtures covered all seven cases;
  seven conditional matches, sensitive controls and exact binding in 13.73
  seconds. Payload was exactly 203,058,480 bytes. Synthetic setup took 32.58 s
  with two CPU threads. These CPU timings are not CPU05/GPU03 performance data.
- Extrapolating that representative checker workload twenty times gives about
  275 seconds for 140 analyses on geekom. Token-local omission evaluation avoids
  recomputing unrelated tokens: 356,352,000 instead of 1,933,312,000 composition
  additions across the grid, preserving every control and F32 operation order.
- Each physical bank file is still hashed. Verified content identities allow
  reuse of immutable bank bytes and finite-scale checks across analyses. No
  bank readback or identity check is removed from the captures.

Allow 900 s for fresh CPU build preparation, **before** starting the remote worker.
Synthetic weight/graph setup remains inside the benchmark's 300 s budget.
Keep the existing native/supervisor 300 s and worker 360 s caps; this is a
bounded attempt, not a claim that the new physical run fits. Offline analysis
has a separate 900 s cap after acknowledged cleanup, with flushed progress for
each checked pair. Timeout, mismatch, unknown or inconclusive is terminal;
preserve partial evidence and do not retry or expand budgets automatically.

Without deduplication, the 140 captures have 4,061,169,600 raw payload bytes
(3.783 GiB), plus metadata/logs/build. Reserve at least 8 GiB free storage before
preparation. No warmup captures or per-case model files are needed. All bank
readbacks remain in the bounded native run, so tunnel throughput can determine
whether the 300-second cap is sufficient. No private geekom evidence transfer
is required for synthetic production geometry.

Focused local tests:

```bash
python3 -m unittest tests.test_layer7_warmed_sweep \
  tests.test_layer7_arithmetic tests.test_layer7_operand_check \
  tests.test_layer7_mmvq_check \
  tests.test_native_moe_overlap.Layer7BenchContracts \
  tests.test_native_moe_overlap.Layer7BatchSweepContracts
```

## Future Hermes execution recipe

Use only when separately dispatched. Fetch the published exact candidate SHA
from `diag/layer7-warmed-sweep` in `Zutfen-LLC/inferswarm`; verify HEAD, preserve
prior tasks and use fresh checkout/build/result paths on CPU05. Record current
main separately without changing the experiment base. Read AGENTS.md. Use the
existing long-lived controller's agent-forwarded CPU05 session
(`hermes@100.107.250.44`, hostname `inferswarm05`). Preserve the existing
single-`-L` topology and 14 threads. GPU03 is `hermes@100.77.187.38`; GPU1 stays
untouched. Do not run models, PR/CI/Final Validation or merge work.

Existing remote prerequisites:

- CPU05 source archive `/home/hermes/is319-stepa/pin.tar.gz`, SHA256
  `03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`.
- Accepted GPU03 worker `/home/hermes/is327-owned/ggml-rpc-server.cuda03`, SHA256
  `46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`;
  GPU0 UUID `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`.
- Existing compiler/CMake/Ninja/Python tools; no downloads/install required.

The launcher performs a fresh optimized CPU candidate build before worker start,
then reuses the accepted CUDA worker through the established owned process-group
and cleanup protocol. It has one tunnel, bounded worker/native lifetimes and
acknowledged cleanup; every failure is terminal. Fresh build receipts bind the
new executable to its exact source inputs and compiler/library bytes.

```bash
# In the fresh exact-SHA checkout on CPU05; use fresh absolute paths:
repo=$PWD
base=/home/hermes/is-layer7-warmed-<EXACT_SHORT_SHA>
mkdir "$base"
sha256sum /home/hermes/is319-stepa/pin.tar.gz
bash "$repo/tools/native-moe-overlap/layer7-cpu05.sh" "$repo" \
  /home/hermes/is319-stepa/pin.tar.gz "$base/cpu-build" "$base/result" \
  --warmed-operand-sweep >"$base/launcher.log" 2>&1
# STOP on nonzero launcher status, absent/failed cleanup or identity drift.
# After verified owned-worker/listener absence:
c++ -O3 -std=c++17 -shared -fPIC -mf16c -ffp-contract=off \
  "$repo/tools/native-moe-overlap/layer7_arithmetic.cpp" -o "$base/helper.so"
timeout --signal=TERM --kill-after=5 900 python3 \
  "$repo/tools/native-moe-overlap/layer7_operand_check.py" \
  --replays "$base/result/benchmark" --helper "$base/helper.so" \
  --output "$base/check.json" >"$base/analysis.log" 2>&1
```

Use `set -euo pipefail` in the execution shell. Require analyzer exit 0 and all
140 reports conditional-match before reporting conditional timing observations.
Archive the complete result tree, source HEAD, candidate receipt, compiler
identity, helper hash, checker report/progress, launcher log and cleanup proof.
Report every failure/timeout honestly, including last completed pair and legacy
disagreements. Do not relabel historical INVALID, claim numerical qualification,
change the frozen profile, sample the replay set or rerun until success.
