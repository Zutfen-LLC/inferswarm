# Issue #268 Task 2 — internal configuration and strategy seam

This stage provides CPU-pure configuration parsing, immutable plan construction and llama.cpp argument binding only. It performs no filesystem backing verification, executable hashing, process launch, network request, or physical execution.

## Exported API

`inferswarm.operator.config` exports `OperatorConfig`, `ModelIdentity`, `Participant`, `Placement`, `parse_config(mapping)`, and `load_config(path)`. JSON schema is `operator-config/1`, with exact top-level keys: `schema`, `plan_id`, `model`, `participants`, `strategy_id`, `placement`, `request`. Model keys: `source_id`, `revision`, `representation`, `members` (nonempty `{name,sha256}` array). Participant keys: `node_id`, `compute_id`, `transport`, `address`, `device`, `source_id`, `source_revision`, and `source_representation` (which must match the model identity), `source_path`, `runtime_executable`, `runtime_sha256`, `cache_path`, `port`, `lifecycle_dir`. Placement rows have `unit_id`, `compute_id`, `native_args`; request keys are `prompt`, `max_tokens`, `temperature`. IDs and values are operator-supplied opaque strings; malformed digest/port/type, duplicate identities, unknown compute references and unknown/missing keys fail closed. Source/cache paths and expected digests are descriptors; parsing does not establish presence or verified bytes. `backing_verified` is always false at this seam.

`inferswarm.operator.plan` exports `OperatorPlan` and `build_plan(config)`. Its `digest` is SHA-256 of compact, key-sorted canonical JSON for the validated operator-authorized plan. Nested collections are tuples/frozen records.

`inferswarm.operator.strategy` exports `LaunchSpec` and `llama_cpp_spec(plan)`. The adapter accepts only the explicit `llama.cpp` strategy with two participants, both CUs explicitly represented in placement, and one `rpc` transport. It returns the selected local executable and expected digest, remote endpoint, device string, operator-provided native placement args, and exact expected placement; it launches nothing. Runtime-specific legality and actual placement observation remain for the next task.

No model-name/vendor/hostname policy, automatic fallback, placement synthesis, source verification claim, or runtime side effect is implemented here.
