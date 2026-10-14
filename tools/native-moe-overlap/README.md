# One native qwen4exp layer (#309)

Default-off experimental integration against llama.cpp
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. This is the actual model's
`graph::build_layer_ffn` seam, compiled into the native llama library/server.
It is separate from `inferswarm.operator.qwen_q8` whole-layer ownership.
The earlier `tools/moe-overlap` harnesses and numerical failures are unchanged.

`IS309_MOE=<zero-based-layer>:serial` or `:overlap` selects exactly one layer.
The configuration is captured when the native qwen4exp model loads, so changing
the environment does not change a reused graph. Absence leaves ordinary native
execution; other layers call the original FFN builder. Invalid layer/mode,
non-qwen4exp model, missing shared branch, LoRA, intermediate eval callbacks,
noncontiguous/non-F32 activations, or incompatible weight placement are refused.

Use the existing native loader's `--override-tensor` to place all selected routed
banks (including any scales) on **one existing context RPC backend**, and its
router and gated shared weights on local CPU. Loading/materializing weights
remains native; the experiment borrows model tensor/buffer leaves and the
context RPC backend. There is no second loader, protocol, connection, per-step
weight copy, production Q8 plan lowering, or placement search.

The native router runs on CPU, then routed work is queued through the pinned
RPC dispatcher. Serial reads routed output before computing shared work;
overlap computes shared work first. Both join with response-bearing
`GET_TENSOR` before the same F32 combination. Client synchronize alone does not
wait for remote compute. Both arms use identical weights, selected experts,
normalization, scales, SwiGLU, shared sigmoid gate, placement and arithmetic.

Each reusable graph shape owns separate router, shared and routed `ggml_gallocr`
arenas and metadata through `llm_graph_result`. The activation snapshot has
INPUT **and OUTPUT** flags: INPUT alone permits router allocation reuse after
its last local read. Packed top-k IDs and normalized routing weights remain
live through the join; native top-k is a strided argsort view and must be packed
at this boundary. No outer scheduler synchronization is removed. Successful
calls join before returning, so repeated changed inputs, graph reset, shape
changes and context destruction can release arenas safely. The separate CPU
executor avoids recursive use of the outer CPU pool and uses its configured
decode/batch thread counts. Model buffers and the RPC connection outlive these
graph owners.

The pinned RPC dispatcher aborts on transport errors and has no socket deadline.
This experiment therefore requires external process supervision with a wall
deadline and client/worker cleanup; it does not offer in-process recovery or
reuse after failure. Tests inject disconnect and stalled-join controls and
verify bounded cleanup. This is the existing fail-stop RPC behavior, not a new
persistent-service design.

CPU development (uses an existing authenticated archive when supplied):

```bash
export MOE_OVERLAP_TARBALL=/absolute/path/to/verified/pin.tar.gz
python3 tools/native-moe-overlap/build.py --jobs 2 --server
python3 -m unittest tests.test_native_moe_overlap -v
```

The additive `native.patch` changes six pinned files; new native sources are in
`overlay/src`. The build verifies the archive SHA-256 and selected #299 source
digests, derives a fresh separate overlay, checks every cached input, and stamps
objects with source, header, flags and compiler identities. The direct build
uses the existing authenticated native target closure; `--server` also links
the full llama-server and original multi-device ggml-rpc-server. Nothing is
installed. `.cache/native-moe-overlap/build/build-identity.json` records the
archive, pin, patch, all overlay inputs, exact compile/link commands, compilers
and binary hashes. `--cuda` reuses #307's CUDA translation-unit closure and
driver-link recipe; it is **untested by the CPU checks** and does not execute a
model or device. Never identify this derived artifact as a historical binary.

`IS309_SETUP` reports graph shape/backend and separate arena sizes.
`IS309_MOE` reports selected-layer dispatch (including routing), shared and join
durations, and activation/routing/result bytes. Weight uploads belong to native
load/setup. The loopback wire test independently observes one connection, setup
bank uploads, exactly three small writes per step, graph reuse, and matching
allocation/free counts. Neither those byte counts nor fixture timings establish
real hardware residency or performance.

Optional `IS309_CAPTURE=/fresh/path.bin` appends I309/1 records: little-endian
`uint32 magic=0x39303349, layer, embedding, tokens; uint64 shape-local step`,
then contiguous F32 input and combined output arrays. Bound capture size and
duration in the supervising process. Compare two same-placement arms with:

```bash
python3 tools/native-moe-overlap/compare.py serial.bin overlap.bin > comparison.json
```

The comparison requires exact finite input/output equality, preserves max-abs
and RMS diagnostics, and refuses truncated/empty/over-budget captures. It
establishes scheduling equality only. Native fixtures use F32, merged gate/up
and Q8_0 banks, 18 changed-input steps across 1/7/1-token shapes, outer scheduler
intermediates, default-off/non-selected controls, missing shared work, wire
accounting, and process failure/cleanup. Full-model compatibility, CUDA
compilation, GPU fit, GPU execution overlap and speed remain separately untested.

See [hardware-recipe.md](hardware-recipe.md) for the bounded, separately
dispatched Hermes handoff. #300 remains open.
