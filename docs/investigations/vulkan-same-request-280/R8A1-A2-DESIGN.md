# Round-9 design note: R8-A1 (partial logical identity) and R8-A2 (producer occurrence identity)

Scope: exactly the two advisory findings from round-8 comment 6024739045. Smallest
implementation that fixes them; no general redesign, no new authority.

## R8-A1 — collector rejects partial logical keys

Defect: `scripts/issue280_observer.py` host_leg law enters the tensor-scoped
branch only when BOTH `input` and `copy` are present. A row carrying exactly one
of them falls into the buffer-scope branch, which ignores the supplied field:
an explicitly alien (or wrong) partial identity binds the open boundary.

Fix (collector only, one law): a host_leg row that contains `input` or `copy`
MUST contain both, and is then tensor-scoped: full `(input, copy, occ)` must
match the open boundary. Buffer-scope remains reachable ONLY by rows carrying
NEITHER field. Existing behavior preserved: valid buffer-only rows, complete
tensor identity matching, explicit-`occ` disagreement on buffer-scope rows.

## R8-A2 — producer occurrence identity

Defect: four process-lifetime static counters keyed only by the input pointer
(`observed_copy_occurrences`, `observed_boundary_occurrences`,
`observed_boundary_end_occurrences` in ggml-backend.cpp; `observed_copy_paths`
in ggml-vulkan.cpp) disagree with the collector's graph-local, (input, copy)-
keyed occurrence derivation. Valid source-shaped streams are rejected (false
negatives) the moment an input recurs in a later graph or has two distinct
copies.

Target contract (unchanged, `issue280_observer.py` copy_manifest law):
occurrence = number of prior `copy_manifest` rows with the same
`(input, copy)` key **within the current graph**, starting at 0, reset per
`graph_begin`.

### Production graph-reset boundary

`ggml_backend_sched_graph_compute_async` (pinned ggml-backend.cpp:2014,
anchor `enum ggml_status ggml_backend_sched_graph_compute_async(...) {`,
unique in the TU). At the pin, `llama_context::graph_compute`
(src/llama-context.cpp:2513) executes exactly ONE async sched call per
`graph_begin`/`graph_end` pair the observer emits from
`src/llama-context.cpp:1396`, so entry into this function is 1:1 with the
collector's graph scope. Resetting the occurrence state here gives the
collector's per-graph reset with no new synchronization: the reset runs on the
host thread before `ggml_backend_sched_compute_splits` emits any manifest.

### Copy-selection point

Unchanged from the pin: manifests are emitted in
`ggml_backend_sched_compute_splits` (anchor
`struct ggml_backend_sched_split * splits = sched->splits;`, pin line 1645)
over `planned->inputs[pi]` and `tensor_id_copy(hid, planned->backend_id,
sched->cur_copy)`. The copy selection itself (`sched->cur_copy` rotation in
`ggml_backend_sched_alloc_graph`) is production code and is NOT modified.

### Sharing occurrence identity across the scheduler/Vulkan TU boundary

The emitter header `issue280_observer.h` is deliberately translation-unit
local (anonymous namespace; each producer logs through its own `I280_LOG`
macro) — see `test_logging_sinks_are_translation_unit_local`. The scheduler
counters (ggml-backend.cpp) and the Vulkan `copy_path` counter
(ggml-vulkan.cpp) therefore CANNOT share a static map without breaking that
design, and a shared global would introduce cross-TU state in an
observation-only overlay.

Mechanism: a shared production helper header
`instrumentation/issue280_occurrence.h` defining an ODR-shared, graph-local
occurrence registry: a named namespace (`issue280_occurrence`) whose access
functions are C++17 `inline` functions with function-local `static` state.
Inline-function statics are unified across translation units by the standard,
so the scheduler TU (ggml-backend.cpp) and the Vulkan TU (ggml-vulkan.cpp)
see ONE registry with no exported symbols and no change to the emitter's
TU-local logging design (`test_logging_sinks_are_translation_unit_local`
continues to hold). At the pin, every counter site runs on the scheduler's
host thread, so the shared state adds no synchronization.

- scope: per graph — `reset()` at the `ggml_backend_sched_graph_compute_async`
  entry hook (the design note section above);
- key: `(input pointer, copy pointer)` pair, not input pointer alone;
- value: `assign()` records the 0-based per-key count at the manifest;
  `begin()` advances a per-key event cursor (repeated pairs: 0, then 1);
  `current()` recalls the open event's occurrence (copy_path, boundary_end).

All four sites share the ONE ODR registry: the manifest is the authoritative
assignment (it fires first, per planned input, in the pre-compute manifest
loop); begin/end/copy_path walk it positionally, so manifest, begin,
copy_path and end emit ONE occurrence identity per pair per graph.

### Occurrence lifecycle (producer side, after this change)

1. `graph_begin` (llama-context.cpp) / entry of
   `ggml_backend_sched_graph_compute_async` (ggml-backend.cpp): all TU-local
   occurrence registries reset to empty (per-graph scope).
2. `copy_manifest` (compute_splits): occ = count of prior manifests with the
   same (input, copy) this graph; register (input, copy) → occ for the
   boundary hooks in the same TU.
3. `boundary_begin` / `boundary_end` (same TU): look up (input, copy);
   emit the SAME occ as the manifest (0 when unregistered, which cannot
   happen for well-formed producer order since the manifest hook precedes
   compute).
4. `copy_path` (ggml-vulkan.cpp): same registry, keyed by the (src, dst)
   pair — at the pin `src`/`dst` ARE the planned input and its selected
   copy (the scheduler copies cross-die inputs by calling
   `ggml_backend_tensor_copy` on exactly this pair), so the
   (input, copy)-keyed and (src, dst)-keyed views coincide and all four
   sites agree on one occurrence number per pair per graph.

Because all four sites share one registry, the manifest is the authoritative
assignment (it fires first, per planned input, in the pre-compute manifest
loop); begin/end/copy_path recall the assigned value by (input, copy) key.
No site derives its own independent counter anymore. Explicit cross-TU
coupling via exported symbols is rejected: it would couple independent
backends in an observation-only patch.

Known limitation (disclosed, pre-existing): the old counters were TU-local
function statics with process-lifetime scope — already shared across all
scheduler instances in that TU without synchronization. The ODR-shared
registry extends that same single-host-thread assumption across the two
TUs. At the pin, llama.cpp server graph execution is host-thread serialized
(one sched per context; input copies issued from the scheduler thread), so
no new race is introduced in the observed path; no mutex is added to keep
this the smallest change.

### Harness lifecycle correspondence

The regression cases execute a C++ harness (`fixtures/producer_occurrence.cpp`)
that calls the REAL shared production helper
`instrumentation/issue280_occurrence.h` with the exact expressions the
transform inserts into the production sources, in the pinned lifecycle order:
`sched entry (reset) → per planned input: assign (manifest) → begin
(boundary_begin) → current (copy_path, boundary_end)`. `tests/
test_issue280_source.py::test_harness_executes_production_counter_expressions`
asserts the harness's `issue280_occurrence::` call expressions equal the
transform's inserted expressions, and `test_harness_lifecycle_matches_
production_anchors` asserts the reset is anchored at
`ggml_backend_sched_graph_compute_async` entry, `assign` in the
compute_splits manifest loop, and `current(src, dst)` in the Vulkan TU
copy_path — so harness execution exercises the actual generated hook/counter
logic, not a hand-written re-enactment. The resulting rows are emitted through
the standard emitter header and fed into the REAL collector.

## Tests

R8-A1 (observer, fixture-driven): input-only and copy-only host_leg rows with
matching concrete buffers — matching and foreign partial values — must reject;
buffer-only rows, complete tensor identity rows, and wrong explicit occ still
behave as at 807759a.

R8-A2 (harness-driven, the four required cases):
1. same (input, copy) across two graph invocations in one process, graph
   object reused → occ 0, then 0;
2. one input, two distinct copies in one graph → occ 0 for each pair;
3. repeated occurrences of one pair within a graph → 0, then 1;
4. manifest/begin/copy_path/end agree on occ; deliberately wrong occ still
   rejects (collector unchanged in this respect).

## Identity refresh

`scripts/issue280_source.py` emits new applied-source.patch +
source-identity.json (ggml-backend.cpp and ggml-vulkan.cpp transformed hashes,
overlay, patch, full tree). Base pin and originals unchanged. NOT_BUILT /
VULKAN_BUILD_NOT_VERIFIED retained — CPU harness compilation is not a build.
