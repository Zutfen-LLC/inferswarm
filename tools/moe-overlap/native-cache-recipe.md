# Assigned complete-bank RPC integration (#321)

This is a future separately dispatched 05→03 T=1 recipe. It grants no hardware
execution authority. #311, #313 and #315 remain open. Step B was reported as
transfer/cache/load and exact readback only; it did not qualify arithmetic.
The compatibility inspection is reproduced from repository source, without
retrieving the controller's external report.

## Supported boundary and provenance

`build.py --native-cache` reuses `tools/native-cache/operator-build.py:compose`
and its unchanged patch/observer/assignment guard. It builds a **derived CPU
harness**, not the reviewed operator client. The reviewed CUDA worker, build-pair
selector and identity table are unchanged. Stock builds/defaults remain v6.
Do not relabel a new harness manifest as `step-a-cpu05-cuda03` client identity.
Composed sources are authenticated on reuse, have separate object directories,
and stamp every object with composition identity and compile flags. Absolute
paths in the existing composer can change its composition digest.

Use a new owned build prefix on 05, the original authenticated archive, and
bounded compilation parallelism (no CUDA compiler/device needed on 05):

```bash
MOE_OVERLAP_TARBALL=/absolute/pin.tar.gz \
  python3 tools/moe-overlap/build.py --native-cache --cache /absolute/owned/moe321 --jobs 2
```

The harness is `/absolute/owned/moe321/build-cpu-native-cache/moe_overlap_harness_native_cache`.
Retain its adjacent `.build-manifest.json`, executable SHA-256, exact repository
head, build log, compiler paths/versions, original archive hash and composed
source identity. The runtime JSON independently records composed source and
upload boundary. Record worker executable/dependency hashes, complete reviewed
CUDA03 manifest, masked UUID/PCI/native-selector discovery and owned PID as in
[the CUDA prerequisite recipe](../native-cache/cuda-prerequisite-recipe.md).
Protocol mismatch stops with the pin's `RPC server version mismatch` diagnostic;
never retry using a stock v6 client or by dropping the assignment guard.

## Assignment and resource preflight

Only `--gguf SHARD --layer N --secondary rpc --split 0 --assigned-banks GUARD`
is supported. The selected shard must contain the original eight block tensors.
The guard is the existing `source.assigned_guard_bytes` /
`source.publish_assigned_guard` output, from the existing validated assignment
and prepared metadata; no second manifest format is introduced. It must contain
**exactly** these three complete tensors for that block, with original Q8_0
bytes, type, all dimensions, lengths and SHA-256:

- `blk.N.ffn_up_exps.weight` `[2560,640,512]`;
- `blk.N.ffn_gate_exps.weight` `[2560,640,512]`;
- `blk.N.ffn_down_exps.weight` `[640,2560,512]`.

Each is 891,289,600 bytes (CALCULATED from authenticated Q8_0 geometry).
Freeze the exact original model revision, member/header identities and range
hashes through the existing #311 assignment validation/preparation route.
Prepare the three assigned ranges on 03 using `prepare_q8_participant` and the
existing disk admission/delta inventory, with the worker stopped. If Step B
backing contains only two tensors, the third bank is an explicit missing delta;
it is required before this complete-block test. Keep routers and shared tensors
local on 05. Extra/missing/duplicate/partial tensors, altered bytes, types,
shapes, lengths, nonzero split and synthetic mode refuse. Uploads are owned
whole tensors, offset zero, with weight-buffer usage; graph expert IDs/views
and scheduling mathematics stay unchanged. The composed client checks the
actual loaded-byte digest again at each upload before sending weight payload.

Retain Step B's bounds: <=10 GiB owned worker host peak, >=4 GiB free host
headroom, measured available VRAM minus >=512 MiB reserve, GPU0 x16 only, no
second GPU or service interruption. Count the full three-bank destination,
backend graph/workspace overhead, <=1 MiB native cache scratch, any verification
GET buffers and simultaneous allocations. Coordinator retains its full local
bank store for the CPU reference, plus router/shared state and loader/hash reads;
this test does not remove that source/reference dependency. Admit only if the
whole block fits these declared bounds before dispatch; otherwise STOP and
report the concrete fit gap. Do not shrink/slice banks after a failed run.
Freeze one cold run and one restart run, warmup=0/reps=1, a 10-minute total
execution budget, and owned-process cleanup. Any integrity/identity/placement
drift, OOM/swap growth, budget/headroom breach or missing attribution stops.

## Future physical commands (not executed by this PR)

On 03, use the already reviewed CUDA03 `ggml-rpc-server` and its existing
private listener/lifecycle, with only the admitted UUID visible. Exact option
syntax of the pinned server is shown below; substitute the frozen paths,
private address and unused owned port. `LLAMA_CACHE` is the parent of `rpc/`.
Both hosts' guard bytes must be identical. No new network/security setup:

```bash
CUDA_VISIBLE_DEVICES=GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176 \
IS311_ASSIGNED=/absolute/assigned.txt LLAMA_CACHE=/absolute/owned/backing \
  /absolute/reviewed/ggml-rpc-server -H PRIVATE_03_ADDRESS -p OWNED_PORT -c -d CUDA0 -t 2
```

On 05, using the derived harness and frozen captured block input:

```bash
IS311_ASSIGNED=/absolute/assigned.txt \
  /absolute/owned/moe321/build-cpu-native-cache/moe_overlap_harness_native_cache \
  --gguf /absolute/pinned/shard.gguf --layer 2 --assigned-banks /absolute/assigned.txt \
  --secondary rpc --rpc-endpoint PRIVATE_03_ADDRESS:OWNED_PORT --split 0 \
  --tokens 1 --threads 2 --warmup 0 --reps 1 --inputs-file /absolute/block-input.f32 \
  --self-check-negative --dump-reference-case /absolute/new/cold
python3 tools/moe-overlap/check_scheduling.py /absolute/new/cold
python3 tools/moe-overlap/check_reference.py /absolute/new/cold --gguf /absolute/pinned/shard.gguf
```

The numerical command is expected to refuse `rpc-remote-unverified`; retain
that refusal separately. Scheduling equality cannot certify GPU arithmetic,
and no tolerance, oracle, fallback or selected expert is changed here.
Retain complete serial/overlap outputs, input/routing/partial/shared exports,
negative-control verdict, run JSON and separate checker reports even on STOP.
Terminate/reap only the owned worker, revalidate durable assigned backing and
restart once. Repeat the identical harness command into a new `restart` case.
Compare both complete output files byte-for-byte across cold/restart and arms.

Account separately for (1) missing-range SSD acquisition, (2) attempted assigned
weight bytes, (3) actual cmd6 weight SET payload, (4) cmd7 hash-hit responses,
(5) graph/activation/routing/control/framing and (6) output/verification GET
traffic. A restart requires zero missing-weight acquisition and zero unchanged
weight SET payload plus actual graph execution/identical outputs; upload-attempt
observer facts or readback alone do not establish this. Local source reads and
hashing still occur on 05 and are not network acquisition. Freeze observer and
accounting methods before physical dispatch; the test relay is loopback-only
fixture instrumentation, not an additional deployed service.

## Reproducible CPU fixture

`python3 -m unittest tests.test_moe_native_cache -v` builds actual pinned
stock/composed closures and runs a 12-expert sparse Q8 GGUF fixture, with all
ten selected experts and the shared branch. Literal expert-dependent source
weights, deliberately reordered GGUF tensor storage and independently expected
router IDs are checked using the existing CPU operand reference. This is
CPU fixture engineering, not remote numerical qualification or a hardware
performance claim. Set `MOE_NATIVE_CACHE_RESULTS` to a new owned directory to
retain complete cold/restart exports, wire ledgers and derived build manifests.
The composed `--rpc-worker --cache-dir DIR` helper is for this CPU loopback
fixture; it is a separately identified derived worker and never replaces the
reviewed CUDA worker. It requires `IS311_ASSIGNED` when caching is enabled.

Smallest physical next action after maintainer review is to admit the full
three-bank assignment and derived harness provenance for one cold/restart
05→03 T=1 pair. Full physical validation belongs to a later Hermes dispatch.
No merge, Final CPU Validation dispatch or inference-host operation occurs here.
