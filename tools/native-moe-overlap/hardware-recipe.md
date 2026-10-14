# Hermes handoff: one real native MoE layer

**Recipe only; execution requires a separate maintainer dispatch.** #309
authorized CPU development on Valinor. It authorized no InferSwarm host access,
install, model acquisition, GPU build/campaign, or full-model inference. CPU
fixtures establish none of CUDA compatibility, real-model compatibility, VRAM
fit, GPU overlap or performance. #300 is not closed by this handoff.

The separately dispatched experiment must freeze: reviewed InferSwarm head;
this patch/overlay/build identities; authenticated, already-staged model objects;
the actual baseline argv, environment, placement and device identities; selected
layer and tensor overrides; request JSON; build/run budgets; VRAM/RAM/health caps;
and STOP/cleanup rules. A frozen baseline or resource mismatch is a STOP, not
permission to move other layers or increase caps. Do not use the Q8 production
plan validator to claim this intra-layer experiment is an unchanged whole-layer
plan. Leave those production plans and historical binaries/evidence untouched.

## Layer selection and admission

The proposed selection is **layer 6**, against the fixed Q8 baseline documented
in [the #299 runtime contract](../../docs/implementation/profiled-q8-299/runtime-contract.md):
layers 0–13 are local client CPU, remote CPU owns 14–44, and remote CUDA owns
45–47 plus output. Confirm this is the actual frozen baseline before adopting
the proposal. Layer 6 keeps its router, gated shared branch, hyper-connections,
attention/recurrent state and all surrounding layers in their baseline locations.
Only its routed banks move from client CPU to the admitted remote CUDA device.
If the actual baseline differs, freeze a new explicit selection before execution.

For that authenticated Q8 conversion each of its three full routed banks is
**CALCULATED** 891,289,600 encoded bytes; the addition is 2,673,868,800 bytes
(about 2.49 GiB). Include native buffer padding, the reported routed arena for
the largest admitted graph shape, CUDA scratch/capture/allocation overhead,
existing model/state allocations and the frozen headroom. The baseline's
8,957,357,824 encoded CUDA bytes become 11,631,226,624 encoded bytes before
those overheads. Encoded arithmetic alone is not VRAM admission; a 12 GiB
device may fail this experiment's envelope. No silent cap increase or other
layer movement is allowed.

Before request dispatch, require the selected bank names, shapes, types and
encoded extents to match the authenticated descriptor and backing; all three
must occupy the admitted single RPC CUDA device. Verify local CPU router/shared
weights, native loader buffer logs, stable device/boot/topology identity, baseline
placement of every other layer/output, measured post-setup VRAM/RAM, and the
actual `IS309_SETUP` arena sizes. Reserve the worst admitted batch/warmup shape;
the native warmup may select every expert and is part of peak accounting.
Any unexpected native fallback, missing branch, over-budget allocation or
unexplained weight mirror is a STOP. Static placement flags alone are insufficient.

## Separate experimental build

Use a **new** scratch/cache directory under the authorized supervisor. Reuse
the authenticated source archive; no model or source acquisition is implicit.
Build deadline: at most 90 minutes, at most two compile jobs, within separately
frozen RAM/disk/host limits; failure is retained with no retry-until-PASS.

```bash
export MOE_OVERLAP_TARBALL=/frozen/source/pin.tar.gz
EXPERIMENT_CACHE=/authorized/new/native-moe-309
timeout --signal=TERM --kill-after=15s 90m \
  python3 tools/native-moe-overlap/build.py \
    --cache "$EXPERIMENT_CACHE" --server --cuda --jobs 2
```

Record `build/build-identity.json` and its hash, all binary hashes, version
output, compiler/nvcc/driver/link identities, logs and source pin/archive/overlay
digests. The version includes `is309`; the manifest is authoritative for the
complete derived build identity. Compile and device discovery are separate
gates; stop on any build/device/health failure. The script's CUDA recipe reuses
the #307 closure/extended-lambda/VMM-driver flags but **has not been CUDA-tested**
by this coding dispatch. No historical binaries or caches are overwritten.

Use the newly built **original multi-device** `ggml-rpc-server` to preserve the
baseline's device order (for the documented baseline, `CPU,CUDA0`). The tiny
single-device fixture `rpc-worker` is not the whole-model baseline worker.
Bind only on the separately admitted homelab endpoint. Supervise and stop the
worker by the owned PID/unit; never kill unrelated services.

```bash
"$EXPERIMENT_CACHE/build/ggml-rpc-server" \
  -H "$FROZEN_BIND_ADDRESS" -p "$FROZEN_RPC_PORT" \
  -d CPU,CUDA0 -t "$FROZEN_REMOTE_CPU_THREADS"
```

Record the fresh listener, PID/start identity, actual CUDA device and request
GPU attribution. In one fresh coordinator process the documented device order
registers CPU as `RPC0` and CUDA as `RPC1`; confirm the actual registration and
full buffer-type name `RPC1[host:port]`. Ordinals alone are not physical identity.

## Exactly two arms, same work

Maximum runtime: two model-server launches, each at most 45 minutes including
load/setup; two deterministic requests per launch (first plus one repeated warm
request), at most 128 input tokens and 32 generated tokens each, one slot, no
parallel requests or speculative decoding. Freeze exact prompts/tokenization,
greedy parameters, seeds and all context/cache/batch/thread settings before
dispatch. Use already-verified staged model backing. Preserve baseline warmup
policy identically in both arms. No third arm, hidden retry, autotuning or fallback.

Freeze `baseline-argv.json` as the actual baseline native-server argument array,
including model, RPC endpoint, split/device order, fit OFF, lazy/load/cache,
operation-offload and other frozen settings. It must not contain `-ot`, `-cmoe`
or other competing expert overrides. Layer 6's sole delta is this separate
experiment's explicit native tensor override (buffer name resolved above):

```text
blk\.6\.ffn_(gate|up|down)_exps\..*=RPC1[host:port],blk\.6\.ffn_(gate|up|down)_shexp\..*=CPU,blk\.6\.ffn_gate_inp(_shexp)?\..*=CPU
```

For each arm, use the *same* newly built binary and the *same* frozen argv plus
that identical override; only `IS309_MOE=6:serial` versus `6:overlap` differs.
Capture paths are fresh per arm. Example command assembly (inside the authorized
supervisor, after admission, never via the production Q8 plan lowering):

```python
import json, os, subprocess
from pathlib import Path

mode = os.environ["FROZEN_ARM"]  # exactly serial or overlap, once each
assert mode in ("serial", "overlap")
argv = json.loads(Path("baseline-argv.json").read_text())
assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
assert not any(a in ("-ot", "--override-tensor", "-cmoe", "--cpu-moe", "-ncmoe") for a in argv)
capture = Path(mode + ".bin")
assert not capture.exists()
env = dict(os.environ, IS309_MOE="6:" + mode, IS309_CAPTURE=str(capture.resolve()))
binary = str(Path(os.environ["EXPERIMENT_CACHE"]) / "build/llama-server")
# The supervisor also owns the worker and request controller, caps files at
# 64 MiB, enforces the 45-minute deadline, and always terminates its own PIDs.
subprocess.run([binary, *argv, "-ot", os.environ["FROZEN_EXPERIMENT_OVERRIDES"]],
               env=env, check=True, timeout=45 * 60)
```

Use the frozen bounded request controller to submit the same two requests to
each owned server, save exact response JSON including timings/token IDs/logprobs,
and terminate that server after the second response. This code block's timeout
is a backstop, not a replacement for process-group/unit cleanup. Never let a
server timeout initiate an automatic new launch.

## Compare and preserve

```bash
python3 tools/native-moe-overlap/compare.py serial.bin overlap.bin \
  > native-layer-comparison.json
```

Require identical input record order/shapes and finite exact selected-layer
outputs; retain max-abs/RMS diagnostics even on failure. Compare exact greedy
token IDs and response/logprob diagnostics too. These are same-placement
scheduling checks, not acceptance of the historical heterogeneous numerical
qualification. Do not widen tolerances or erase prior failures.

Bracket setup and requests separately. Preserve native loader/setup uploads,
`IS309_SETUP` allocation sizes, per-step activation/routing/result transfer
counts, connection identities, native dispatch/shared/join timings, request
timings and GPU execution attribution. Weight-sized transfers during a request,
reconnection, or unexpected allocation/placement changes invalidate steady-state
attribution. `dispatch + shared + join` describes the layer's critical path;
native queue submission timestamps alone do not establish physical GPU overlap.
Report first and repeated request effects separately, layer latency and end-to-end
effect; one-layer improvement may be below the resolution of total tokens/second.

STOP and preserve on the first correctness/identity/attribution mismatch,
nonfinite result, health/thermal/fault alarm, deadline, resource cap, transport
failure or incomplete capture. Do not rerun until a new decision. The pinned
RPC transport has no native timeout; supervisor expiry must kill the owned
client group, close its connection (releasing server buffers), then terminate
the owned worker group and confirm listeners/allocations are gone. Retain the
failed/STOP evidence and keep #300 open; hardware acceptance is a separate decision.
