# R7-B — DeepSeek V4.1 Flash runtime substrate

Status: CPU/static source audit + compact substrate-contract fixtures for [issue #209](https://github.com/Zutfen-LLC/inferswarm/issues/209). This additive correction preserves the accepted R7-A bundle byte-for-byte. Correction history retained additively: the insufficient one-file vLLM disposition at `69e07e5`, the expanded-source `EVIDENCE_BLOCKED` terminal at `9feb7e74`, and the pre-lifecycle-retention `EVIDENCE_BLOCKED` head at `253d19b` live on unchanged in `superseded-69e07e5.json`, `superseded-9feb7e74.json`, and `superseded-253d19b.json`.

## Runtime decision

`runtime-authority.json` records vLLM `0eae9acd4d01574e12d4ecf6a0229813f7fdb799` as `SELECTED`: p1–p10 all `PASS`. `external-source-evidence.json` pins its Apache-2.0 license, build configuration, full-file SHA-256 identities, paths, and decisive verbatim excerpts (with exact line spans) for the DeepSeek V4.1 model, PP utilities, standard safetensors loader, attention/cache implementation, and — the correction this round — the full v1 KV-cache lifecycle surface:

- `vllm/v1/core/kv_cache_manager.py` — request→block ownership (`req_to_blocks[request_id]`), `free()`, `reset_prefix_cache()`
- `vllm/v1/core/single_type_kv_cache_manager.py` — `pop_blocks_for_free`, reverse-order free semantics
- `vllm/v1/core/kv_cache_coordinator.py` — `SpecGroup` uniform-spec cache grouping
- `vllm/v1/core/sched/scheduler.py` — `_free_request` on completion, `deferred_frees` for in-flight/PP execution with `_drain_deferred_frees` fencing, `_preempt_request` (frees blocks, resets `num_computed_tokens = 0`, requeues to the waiting queue for recomputation), `is_prefill_chunk` prefill/decode transition
- `vllm/v1/kv_cache_interface.py` — `KVCacheSpec`/`MLAAttentionSpec` DeepseekV4 cache specs with uniform-group merge assertions
- `vllm/models/deepseek_v41/attention.py` — `is_kv_source` cache ownership, `_replace_layer_index` compressed-KV/index-K mapping to the owning source layer, and rejection of PP cuts inside a v4.1 kv-sharing group

Full bytes of every cited file are retained under `external/vllm/`; excerpts are verbatim line spans of those hash-pinned bytes.

## p8 adjudication (mechanical)

`scripts/issue209_r7b_reducer.py` derives p8 from 13 verbatim markers across the retained lifecycle sources — request/block ownership, free-on-completion, deferred free + drain, prefix-cache reset, preemption (block free + computed-token reset + requeue), prefill/decode transition, V4.1 cache-spec ownership, KV/index source mapping, PP-cut-in-group prohibition, and uniform group-spec merge. Authored p8 fields are never an input; deleting or tampering with any retained lifecycle file fails closed on the hash pin rather than downgrading to UNPROVEN. All 13 markers verify: **p8 PASS**.

## Selected shape and frozen cut

`strategy-authority.json` freezes `contiguous_stage` with cut at layer 20 over interval [20, 40). Legal cut boundaries {2, 8, 14, 20, 40} follow mechanically from the pinned config topology (kv sources {2,8,14,20}, nearest-source-at-or-below group resolution, attention-source PP-cut prohibition). `expert_local` is not honestly supported: the pinned runtime executes routed experts inside whole-layer MoE forward and exposes no independent expert-bank seam; selecting it would hide full-layer materialization. No generic fabric extension was required.

The cache contract at the boundary: layer 20 owns its own compressed-KV cache (it is a kv source and the candidate source layer); consumers at layers ≥ 21 resolve their source to layer 20 within the same stage; no cross-stage cache dependency exists at the cut. Lifetime/invalidation/reconstruction semantics are the pinned vLLM v1 scheduler semantics, consumed as substrate contract (see `strategy-authority.json`).

## Compact execution-contract fixture

`execution-contract-fixture.json` (produced by `scripts/issue209_r7b_fixture.py`) records a deterministic two-resource, two-unit run (stage-a → stage-b dependency), prefill→decode transition, preemption/recompute determinism, and 11 fail-closed negative controls, including: fabricated FAIL-proof prose rejected, authored boolean cannot flip the terminal, wrong source hash fails, excerpt absent from source fails, deleting lifecycle evidence cannot unprove p8, p8 PASS cannot stop at Phase 1, authored terminal rejected, R7-A byte-identity, and superseded-evidence quarantine. Unit official-tensor membership is derived mechanically from the accepted R7-A census counts. This is a substrate-contract proof over synthetic geometry — not DeepSeek inference evidence.

## Terminal

`terminal-reduction.json` derives `R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY` fail-closed from the retained bytes. Non-claims: no full checkpoint download, no model execution, no GPU/CUDA/Vulkan qualification, no serving, no representation conversion; the terminal authorizes nothing physically — a separately authorized issue is required for any R7-C physical qualification.
