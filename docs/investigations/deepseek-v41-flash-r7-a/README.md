# R7-A — DeepSeek V4.1 Flash static census and strategy fit

Status: CPU/static, metadata-only investigation for [issue #187](https://github.com/Zutfen-LLC/inferswarm/issues/187). This is not a model execution, acceptance record, architecture decision, or authorization for a successor physical campaign.

## Frozen authority and method

The official authority is `deepseek-ai/DeepSeek-V4.1-Flash` at immutable revision `dba1be0a40aa45a94ad051997016db3960a90277`. The accepted #117 closure commit `f349cbdfbb20ac933447c483f855b1f501aa7a1c` is in this checkout's ancestry. `repository-inventory.json` records all 88 repository objects, LFS identities where supplied, object sizes, retrieval time, and hashes of every retained small source input. The retained inputs are the official card/license/config/tokenizer, supplied inference config/model source, and safetensors index.

`scripts/issue187_r7a_census.py` performed 48 safetensors HTTP range-header reads (and zero checkpoint-body reads). It generated `tensor-census.json`: all 96,085 tensor identities, shapes, stored dtypes, byte extents, and index-to-shard mappings. It rejects duplicate identities, index/header disagreement, malformed extents, and a non-pinned repository revision. `scripts/issue187_r7a_reducer.py` is the offline reduction and fails closed on revision drift, shard/tensor omission or duplication, inconsistent byte sums, unsupported geometry assumptions, or a false per-expert census.

The repository finalizer owns the derived terminal, producer-hash ledger, and bundle manifest; it reuses the metadata outputs offline and never invokes the census producer.

## Census

The official checkpoint has 48 safetensors shards totaling 510,296,708,312 object bytes. Header-derived tensor extents reconcile exactly to the official index's 510,286,023,000 bytes; the difference is file/header/container overhead, not unaccounted state. The complete machine-readable class totals are in the terminal reduction.

The source config establishes 40 backbone layers, dimension 5,120, 384 routed experts plus one shared expert per backbone layer, six routed expert selections per token, a 128-token sliding window, KV source layers 2/8/14/20, index source layers 2/8/14/20/24/28/32/36, two Engram layers (1 and 14), three MTP/draft layers, and a 32-layer vision path. Text-only is the first prospective scope; vision/aligner tensors are separately inventoried and excluded from it.

| logical state | authority / lifetime | header-derived stored bytes |
| --- | --- | ---: |
| Routed expert banks | immutable; conditionally selected by model-owned router | 288,777,830,400 |
| Engram tables and projections | immutable lookup state at layers 1 and 14 | 203,073,076,240 |
| Attention | immutable weights; source-owned window/compressed/index cache is session-mutable | 5,151,556,608 |
| Shared experts and router | immutable, active/shared model-owned computation | 1,416,960,000 / 157,409,280 |
| Embedding/output head | immutable input/output state | 2,647,654,400 |
| Draft/MTP | immutable optional draft state plus runtime/session state | 7,932,874,632 |
| Vision + aligner | immutable multimodal-only state, excluded from text-first | 970,506,240 |

Source `Attention.forward` has distinct `start_pos == 0` prefill and decode branches: prefill seeds the ring cache while decode inserts one token and reads the complete window. That proves phase asymmetry and mutable cache ownership needs; it does not establish a transferable cache protocol. The model source routes top-six experts and runs the shared expert; it establishes conditional demand, not a generic planner expert concept. A future strategy can emit opaque demand observations without retaining prompt/response content, but no workload demand profile is measured here.

## Legal-shape and pressure findings

| shape | classification | static finding |
| --- | --- | --- |
| Contiguous backbone stages | `LEGAL_GENERIC_EXTENSION_REQUIRED` | A strategy can expose model-legal stage boundaries; each BF16 hidden-state crossing is structurally 10,240 bytes/token. Cache/source dependencies must be made explicit. |
| Expert-local | `MODEL_ADAPTER_EXTENSION_REQUIRED` | Tensor identity makes a per-layer/expert bank census possible (18,800,640 stored bytes per backbone expert), but router/shared-state locality and dispatch correctness remain adapter semantics. |
| Hybrid stage + expert bank | `RUNTIME_BACKEND_PREREQUISITE` | Semantically plausible only after a runtime exposes selective materialization and cross-resource dispatch/correctness controls. |

The six selected routed experts across 40 backbone layers represent 4,512,153,600 stored expert-weight bytes of structural selection per token if every selected unit is cold; that is a residency/traffic pressure bound, not transfer volume, latency, or throughput. The reducer intentionally does not divide bytes by link bandwidth.

The read-only current-fleet ceiling is one 24-GiB accepted Memory Resource. The official checkpoint does not fit one such resource. This rules out neither a legal distributed plan nor a future compact representation, but it means aggregate capacity is not a plan. Current classifications are `NOT_ESTABLISHED` for capacity-feasible, runtime-supported, correctness-qualified, and economically useful.

## Reduction and next gate

`terminal-reduction.json` records exactly one terminal:

`R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE`

The terminal's `substrate_prerequisite` object is the mechanical contract. The missing capability is one pinned runtime/backend path which can selectively materialize the pinned official **sharded safetensors** representation, execute source-faithful text-only prefill and decode, declare cache authority/lifetime/reconstruction at that phase boundary, and execute one strategy-certified multi-resource shape with explicit boundary dependencies. It is absent today; a 510-GiB official checkpoint and a 24-GiB largest accepted Memory Resource cannot establish selective materialization, cross-resource dispatch, cache correctness, or numerical equivalence by aggregate capacity alone. A physical R7-B campaign without that substrate would therefore test an unpinned representation/runtime substitute rather than the stated subject.

The static evidence supports two candidate legal InferSwarm decomposition families, subject to their named extension: contiguous backbone stages (`LEGAL_GENERIC_EXTENSION_REQUIRED`) and expert-local units (`MODEL_ADAPTER_EXTENSION_REQUIRED`). Hybrid stage-plus-expert placement remains `RUNTIME_BACKEND_PREREQUISITE`; it is not an established execution shape. The current generic seam can already select strategy-defined opaque execution units, dependencies, memory requirements, and normalized costs on the Swarm resource graph. The Model Execution Strategy seam can already carry DeepSeek-specific legal cuts/groupings, representation/backend predicates, cache and boundary semantics, correctness rules, and conditional demand observations. Neither seam needs a generic `expert`, `router`, or `KV cache` concept.

The smallest bounded successor is: pin one runtime/backend revision and its official-representation path; implement one text-only strategy adapter with cache-authority semantics; then demonstrate one certified contiguous-stage or expert-local multi-resource shape before any physical R7-B qualification. It does **not** require another R7-A checkpoint-body download, a model-wide third-party conversion survey, a complete distributed capacity/economics plan, vision/aligner support, or execution authorization. No runtime/parser/backend support claim, correctness result, performance result, capacity plan, or execution authorization is made here.

## Repository reconciliation and acceptance gate

`mainline-reconciliation.json` records the acceptance reconciliation. The retained R7-A commit is `5f28f2685288d21298aee6ec3be0d2e7d318ea32`, its branch base is `f142a0d9b693f999685960c641b2a8fe362c4e1e`, and reconciled `origin/main` is `6ff184166a3ee969829329d43814314bfca01501`. The intervening #202 test-infrastructure repair is the only drift: it affects validation machinery by repairing host-optional checkout probing and worker interpreter inheritance. It changes neither census authority, architecture/decomposition interpretation, nor the fleet-capacity study, so no external R7-A input or census output was regenerated. `acceptance-validation.json` retains the clean-baseline comparison for the four former suite errors and their separate baseline repair. This conclusion is scoped to those exact mainline identities; it does not turn the static evidence into a physical authorization.
