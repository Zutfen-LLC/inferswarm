# Fixed Q8 runtime/source contract (#299)

This is an offline, bounded backend contract for `qwen38-q8-fixed/1`, not a
launch authorization or a physical qualification result. It leaves the accepted
IQ1_S `/2` plan, normalized digest and `-cmoe` lowering unchanged. The two explicit
selections are `one-gpu` and `cpu-only`; a failed GPU candidate never selects the
CPU alternative, changes ownership or changes its copy route.

## Authenticated identities and evidence scope

- Unmodified llama.cpp commit: `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`.
- Complete source tree: `950999fe62b7fe55f44ab5b7394e3c8542f37f12`.
- Conversion: `unsloth/Qwen3.8-Flash-Next-GGUF`, revision
  `38bb39ee97821de2c9009abb7e93950eec396e66`, representation `Q8_0`.
- Public descriptor fixture: `tests/fixtures/issue299/q8-metadata.json`, file
  SHA-256 `d4ff414c3d796abd6afb94329de633c39ad5ba4723fc17baa41bdc4c72dce485`.
- Normalized metadata digest:
  `194c818cb0bbb6016f0a282596131040c7afbdb294f9962e7f9e262d7128239e`.

The six member full-object identities, exact authenticated header identities and
all 1,224 tensor descriptors are bound into the candidate. Header authentication
is **not weight verification**, a range SHA, an FNV observation, or evidence that
any full object was downloaded. No tensor-range hashes or native FNV keys are
invented. Source semantics and descriptor-derived amounts are **CALCULATED**.
Test resource profiles, bound values and capability receipts are explicitly
**SYNTHETIC**. A synthetic replay admission is never execution-ready. No build,
binary, device, listener, model, kernel, output or performance was tested here.

Every source citation below refers to the exact commit above. Source snapshots
were compared with `git show <pin>:<path>` and their complete-file SHA-256 values;
no patch, overlay or successor runtime is included.

## Complete fixed ownership

| Selection/owner | Tensors | Encoded bytes |
|---|---:|---:|
| Both: A CPU, input + lazy PLE + layers 0–13 | 361 | 93,736,272,512 |
| One-GPU: B physical CPU, layers 14–44 | 783 | 85,520,377,984 |
| One-GPU: B physical CUDA0, layers 45–47 + outputs | 80 | 8,957,357,824 |
| CPU-only: B physical CPU, layers 14–47 + outputs | 863 | 94,477,735,808 |
| Entire conversion | 1,224 | 188,214,008,320 |

The routed inventory is exactly three full 512-expert banks in **each** of 48
layers: `ffn_down_exps.weight`, `ffn_gate_exps.weight`, `ffn_up_exps.weight`, each
891,289,600 bytes. Layer 1 also owns all six PLE support tensors. Blocks 17 and 35
cross storage members but remain single complete compute-layer assignments.
The output inventory is exactly `output.weight`, `output_hc_down.weight`,
`output_hc_norm.weight`, `output_hc_up.weight`; there is no `output_norm` tensor.

Validation checks named-set equality, unique names/assignments, exact type,
shape, encoded length and authenticated member/offset extents, full layer
co-location, all outputs, input/PLE and disjoint ranges. Totals alone are not the
predicate. Q8_0 is 34 bytes per 32 elements, F32 four bytes and BF16 two bytes.
The complete six-object backing is 188,225,033,248 bytes **per host**; header and
alignment overhead is distinct from encoded payload.

## Native requested map, not observed placement

The server device order is explicit `CPU,CUDA0` for one-GPU, or `CPU` for
CPU-only (`tools/rpc/rpc-server.cpp:248–285`). One fresh client process registers
one endpoint; its client-visible handles are respectively `RPC0,RPC1` or
`RPC0` (`ggml/src/ggml-rpc/ggml-rpc.cpp:2308–2347`). RPC labels are ordinal
registration names, **not stable physical IDs or backend types**. The profiles
must bind each handle to the native selector, host/boot/topology epoch, physical
Compute Unit and RAM/VRAM domain.

Typed `NativeQ8Options` fixes layer split, 35 offloaded slots, `31,4` or `1`, fit
OFF, lazy ON, load NONE, KV offload ON, operation offload OFF, F16 K/V caches,
flash attention OFF and non-unified KV. No tensor override, global CPU-MoE,
adaptive fit or guessed flag is allowed. Definitions are at
`common/arg.cpp:1636–1680,2411–2417,2541–2566,2676–2717,2733–2876,2943–2948`;
flash-attention and KV-unified options are at `1751–1767,1720–1729`.
Effective argv/config/environment must be qualified; supplied argv alone does
not exclude inherited presets, visibility masks or overrides.

`src/llama-model.cpp:1464–1521` includes the output as slot 48: the offload start
is `49 - 35 = 14`. Cumulative float32 split points and native `upper_bound`
map slots 14–44 to the first RPC device and 45–48 to the second. The strategy
emulates that exact arithmetic; the ratios alone are not a layer-map proof.
Input stays on client CPU (`1510–1512`). Four OUTPUT-class tensors are created at
`src/models/qwen4exp.cpp:159–167` and classified in `src/llama-arch.cpp`.

Lazy PLE is created before override selection and takes the actual local CPU
buffer before regex overrides (`src/models/qwen4exp.cpp:169–188`;
`src/llama-model-loader.cpp:1073–1106,1204–1206,1227–1252,1335–1337`). It requires
mmap support. Its whole-file virtual mapping is not zero-RAM residence, and
ON without platform support must not silently become a whole-table RAM plan.
Native unsupported weight-operation CPU fallback exists
(`src/llama-model.cpp:1449–1455`; `src/llama-model-loader.cpp:1255–1259`): requested
ownership is therefore not an observation. Complete reconciliation is required.

## State and actual boundaries

The authenticated Q8 hparams, rather than conditional IQ1_S assumptions, drive
state formulas. State follows native `model.dev_layer` with KV offload enabled
(`src/llama-kv-cache.cpp:208–249`; `src/llama-memory-recurrent.cpp:73–114`).

- Recurrent layers: local F32 R convolution history, 122,880 bytes per row;
  F32 S delta-net state, 3,145,728 bytes per row.
- Layer 1: additional F32 PLE history, 368,640 bytes per row.
- Attention layers 3,7,…,47: F16 K/V, 2,048 bytes per allocated cell per
  stream, plus raw indexer K, 256 bytes per cell per stream. Indexer shares
  attention-cell layout, not independently authoritative cache state
  (`src/llama-memory-hybrid-idx.cpp:49–68,122–129`).
- Recurrent rows include `1 + n_rs_seq`; attention cells include native
  padding/stream count. This bounded variant is text-only, one slot/sequence,
  no speculative rollback, one stream and F16 caches. Context, batch,
  microbatch and all cache settings are digest-bearing.
- Client control state includes positions, output selectors, masks, KV row
  indices, recurrent source/rollback indices, QSA maps/bias and token
  predecessor/sequence lineage. Final HC/logit state stays on the final owner.
  Their upper bounds and allocator/workspace overhead remain UNKNOWN unless
  scoped evidence supplies a bound. Serialization is not invented recovery
  or arbitrary layer migration.

Cuts before layers 14 and (one-GPU) 45 carry the completed F32 HC residual
`[2560,4,microbatch]`, with strides, alias rule, ordering and side-input/state
dependencies (`src/models/qwen4exp.cpp:264–440`). Logical demand is 40,960 bytes
per token, **not measured wire bytes**. Native scheduler inputs remain on the
client CPU (`ggml/src/ggml-backend.cpp:944–948`); actual split inputs, repeated
copies and alias/layout behavior need observation. It is not a universal
2,560-element hidden-vector RPC contract.

QSA scores all cache cells; dense masked attention remains in use
(`src/models/qwen4exp.cpp:581–750`). Capability requirements include Q8, BF16
indexer, GDN/SSM-conv, workload-sized top-k and dense attention, native state/map,
exact unmodified tree, effective argv and complete physical observation. CUDA
TOP_K without CUB is limited to widths at most 1024 at this pin
(`ggml/src/ggml-cuda/ggml-cuda.cu:5459–5469`; `common.cuh:114–116`;
`top-k.cu:225–274`). A short-context success cannot qualify a larger context.

## Source-level route limitation

**One endpoint does not provide server-local native CPU↔CUDA copying at this
unmodified pin.** The scheduler copy reaches the RPC destination copy hook,
then server `COPY_TENSOR` calls the narrow buffer-copy helper
(`ggml/src/ggml-rpc/ggml-rpc.cpp:734–753,1584–1622`;
`ggml/src/ggml-backend.cpp:216–221`). CUDA's hook rejects native CPU sources
(`ggml/src/ggml-cuda/ggml-cuda.cu:820–843`); the reverse CPU hook rejects native
CUDA sources (`ggml/src/ggml-backend.cpp:2390–2399`). The client then GETs into A
staging and SETs back to B (`ggml/src/ggml-backend.cpp:488–508`).

A one-GPU selection explicitly requiring `server-local` receives
`UNSUPPORTED_PLACEMENT`, even when synthetic profiles claim that capability.
`client-mediated` is a separately selected route with B→A→B, two link legs,
A bounce lower bound and UNKNOWN additional overlap/wire demand. It must not
inherit server-local evidence or silently change the source pin. A source
correction would require separately reviewed/authorized work; none is supplied.

## Budget and immutable admission contract

Generic admission consumes opaque immutable `LegalCandidate`,
`ResourceCharge` and `CapabilityRequirement` values. Qwen names, cache formulas,
ownership, native lowering and option normalization stay in `qwen_q8.py`.

For each unique physical memory domain it sums simultaneous allocations in
verification/load/serve/cleanup, taking the largest phase rather than adding
disjoint lifetimes. Per-phase reserve/headroom is checked with the same phase;
existing load, virtual mapping, role breakdown, known lower-bound peak and
UNKNOWN allocations are separately reported. Policy peak, preflight available
minimum, projected available reserve and physical capacity are independent.
Equal shared aliases deduplicate only with equal domain, bytes, phase, role and
provenance. Inconsistent aliases reject; distinct named mirrors charge separately.

Declared charges include encoded weights (PLE active residence separate),
state lower bounds, repacking/backend allocation, allocator, graph/workspace,
observer, verification/source page residence and read buffers, complete SSD
backing on both hosts, full-tensor loader and serialized RPC staging/receive
buffers, and route overlap. Three load-side staging terms each carry the
891,289,600-byte largest-bank lower bound
(`src/llama-model-loader.cpp:1553–1557,1605–1615,1730–1738`;
`ggml/src/ggml-rpc/ggml-rpc.cpp:700–722,1400–1449`). They are conservatively
simultaneous; tighter alias/overlap claims need evidence, not automatic subtraction.

RPC cache defaults to disabled. Enabling it requires exact assigned descriptors,
separate disk footprint, a full cached-tensor hit vector and UNKNOWN overlap.
The stock FNV cache is not cryptographic source authentication
(`ggml/src/ggml-rpc/ggml-rpc.cpp:1452–1511`). An explicit host mirror is optional,
named and budgeted; absence must not mean an unobserved mirror is permitted.
The no-unplanned-host-mirror capability is required. Whole-source mmap is
virtual, not a RAM-fit verdict. No generic full-model-possession eligibility rule
or automatic 8 GiB auxiliary allowance is introduced.

UNKNOWN required amounts, missing allocations/evidence, stale profiles or
unqualified capabilities produce named BLOCKED deficits. Bound evidence must
match allocation/phase/domain/role/amount/metadata token, runtime host and
physical-memory dependency; it cannot shrink a known source lower bound.
Runtime qualification requires measured capability evidence, not an estimated
claim. Receipt evidence classes retain assumptions without promoting them.
Structural validity, technical feasibility, policy eligibility and execution
readiness are separate fields. Default source-backed candidates are structurally
valid but BLOCKED by real evidence gaps; nominal 12 GiB VRAM is not a fit verdict.

The `/3` digest binds metadata/member/header identities, normalized profiles,
physical bindings, selection, policy, workload, ownership, state/boundaries,
source contract, budgets, capability/evidence identities and request. Semantically
unordered inventories are normalized by their owner. Metadata paths, validation
clock and time-dependent receipt verdict are not plan identities. Frozen payloads
reject mutable/nonfinite content. `revalidate_admission` checks plan integrity
and revalidates profiles at injected `now`; omission uses real UTC time and live
scope, never replay freshness as execution authority. `Q8LaunchSpec` is a pure
requested lowering with expected inventory, deficits and readiness, not a process
launcher. Runtime reconciliation/lifecycle integration belongs to the next slice.

## Physical evidence still required

Stock RPC client devices advertise GPU and unconditional operation support;
native physical type/PCI identity is not transmitted
(`ggml/src/ggml-rpc/ggml-rpc.cpp:2149–2199`). Startup summaries/debug assignment
logs do not establish every weight/state allocation, hidden mirrors, actual
copy success or owned-process physical GPU attribution. A trusted observer must
join the exact plan/runtime/argv/model to owned PID/start/host epoch, native and
visible selectors, stable physical IDs, all tensors/state/base allocations,
copy routes and shape-sized kernels, and measured peaks/headroom. Missing
telemetry remains UNKNOWN. Mock tests establish refusal/contract plumbing only.
No claim of correctness, live memory fit, server-local traffic, inference,
performance, weight access or #300 execution authorization follows from this work.

## Complete-file source digests for cited authorities

| Path | SHA-256 |
|---|---|
| `src/models/qwen4exp.cpp` | `e08619e298fdc0b66ae3c0a3ca5d692e23d7261121c4f481689b59655870ba33` |
| `src/llama-model.cpp` | `dc852c79709927631135ff9482e7fa7597d9b975a1867eb49003c14f93594ad3` |
| `src/llama-model-loader.cpp` | `5ef07476310d4678df18a61a6ec0a1ebcbb58c7534ac3c624b9fe0f315a4ab01` |
| `src/llama-arch.cpp` | `1a480fc4899ba76a4e24119d65fbca67905cdd641953ec0eaae878b3c0af560c` |
| `src/llama-kv-cache.cpp` | `16b40ff274e5aed3827f0d1c13a04f4f44c4d800c4eecbb5294b04127ab213c3` |
| `src/llama-memory-recurrent.cpp` | `35903c832ba321aad3fca8b2adf2d481f6ba41196478c6c8f248ffe2bd7d9d51` |
| `src/llama-memory-hybrid-idx.cpp` | `84a57c465729006c28edbca6bc04d121a2afda1495afb206f956dfc3d17096a1` |
| `common/arg.cpp` | `6e71ad4f63c79fee81fe218ab6755ed97813ba84d179e38ae02924be1556d46e` |
| `tools/rpc/rpc-server.cpp` | `14f69793a377a79f2476a190da1f80bac079cfeb4a83df13ffd378d3435d974a` |
| `ggml/src/ggml-rpc/ggml-rpc.cpp` | `07ca713158d222959b4415e74e0bee83119212aad85750ff6240773365c0b2d9` |
| `ggml/src/ggml-backend.cpp` | `a39c4fe81b043c7e8616ebe57afb75d727c692fe3b26c3e9bc2ddde3c6991041` |
| `ggml/src/ggml-cuda/ggml-cuda.cu` | `523470d6604755b82d0208414ce40f1378941b10bc1349763bbdf02edaab9634` |
| `ggml/src/ggml-cuda/common.cuh` | `a210a71f965419ab55cce071b900df118c2520c1566ea5e068d8be07805644a2` |
| `ggml/src/ggml-cuda/top-k.cu` | `e8fd64d90d021e5d0549e6c529619a782a050df3e309ac088151d6b5490a5c89` |
