# R7-B — DeepSeek V4.1 Flash runtime-substrate audit

Status: CPU/static source audit for [issue #209](https://github.com/Zutfen-LLC/inferswarm/issues/209). It consumes R7-A as accepted predecessor authority. It is neither model execution nor physical qualification.

## Authority, reconciliation, and selection rule

The starting and final `origin/main` is `267b983de1249cad9c516e5c5c3cf86ed4a5a252`; accepted R7-A merge `7417c2f58a63d4da854ff399ba6fea5bd722da83`, terminal `R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE`, and manifest `6730826a7c00b92cc88bda814583ccc6955370cde37d685261f764b5146e640c` are bound by immutable `commit:path` plus expected hashes in `terminal-reduction.json`. `mainline-reconciliation.json` records the explicit post-R7-A applicability audit, including #200's reusable model-independent Source-policy seam; it is not imported as R7 representation, runtime, cache-correctness, or acceptance authority.

Before candidate inspection, `runtime-authority.json` froze the ten mandatory predicates from the issue. A candidate is rejected if any predicate is false or cannot be pinned from retained source; performance, output behavior, and vendor preference are not selection inputs.

## Candidate disposition and terminal

The official reference inference implementation at the R7-A revision has suitable MIT provenance and source-faithful text prefill/decode model code, but it cannot consume the official subject natively: `generate.py` loads `model{rank}-mp{world_size}.safetensors`; `convert.py` reads the official index and shard set, renames/repartitions tensors, and writes that new runtime representation. The exact URLs, full-file hashes, decisive excerpts, and R7-A's retained license/config/model source bindings are in `external-source-evidence.json`.

Two credible current sources were also pinned and audited: vLLM `0eae9ac` contains the DeepSeek V4.1 model loader, while SGLang `7ccbf5f` documents V4.1 Flash only through its mutable preview image. Neither retained source exposes the required InferSwarm-selected-state materialization, source-faithful cache-authority, and declared heterogeneous-shape boundary. They are therefore explicit rejected candidates, not discarded model-card leads.

The machine-derived terminal is:

`R7B_RUNTIME_SUBSTRATE_PREREQUISITE`

The smallest successor is to pin and audit a runtime that natively consumes the official sharded safetensors index/shards, selectively materializes the chosen state, exposes source-faithful text prefill/decode cache authority, and executes exactly one legal strategy shape. It must not convert the R7 subject in InferSwarm.

## Scope result

No DeepSeek strategy adapter, generic extension, compact execution-contract fixture, cache contract, or physical qualification was implemented: without a truthful pinned runtime substrate, claiming any of those would evade the gate rather than satisfy it. No complete checkpoint was downloaded, no model code executed, and no GPU/CUDA/Vulkan/serving/conversion activity occurred.

The generic Fabric remains untouched. No generic planner/model vocabulary or policy for DeepSeek, experts, routing, caches, backends, vendors, or host topology was added. The terminal makes no claim about full-model correctness, performance, production support, or model suitability.

## Status impact

No `project-status.json` update is appropriate. This is unaccepted static evidence of a prerequisite; it changes neither an accepted capability nor the active R8 frontier or execution authorization. The status generators were nevertheless run in check mode, and the explanatory status prose has no dependent DeepSeek claim to revise.

## Reproduction

```bash
python3 scripts/issue209_r7b_reducer.py
python3 scripts/issue209_r7b_manifest.py --check
python3 -m unittest tests.test_issue209_r7b -v
```
