# Layer-7 local implementation validation

Base: `adb2172015757c99c8b04c49f295ce0e0aee7da4`.
This record concerns local synthetic CPU-loopback development only. It does not
change the completed H5 experiment, historical answer-check failures, accepted
native identities, project status, or hardware authorization.

## Built and exercised

Only `native-layer7-bench` and the CPU-loopback `rpc-worker` were built. Initial
composition used `hot-build-composed.py --benchmark-only --portable-fixtures`.
The final benchmark/worker were freshly compiled and linked by CMake/Ninja to
reauthenticated, unchanged composed CPU/RPC-v7 native libraries; no full server
build was needed. This is a portable development build, not the future CPU05
optimized candidate. The future recipe produces its own actual candidate receipt.

Final local benchmark SHA-256:
`60635cffb0091574019c1eaf024d159b2aeb44d4eff557df519d37b1437f230a`.
Build receipt SHA-256:
`c407cf35ee4b5a83d61af80ae263d5efa55f3d3c642d7355459b7222b36754f6`.

Parent/controller verification on final executable source:

- 14 focused tests plus 3 cross-cutting smoke tests: **17 passed**, zero skips,
  via canonical venv `python -E -m unittest -v`; 15.215 seconds. The focused
  population is `Layer7BenchContracts`, the six `NativeHotExperts.test_matched_*`
  methods and `test_hot_candidate_builder_is_additive` in
  `tests/test_native_moe_overlap.py`.
- Self-contained synthetic routing: 5 warm + 20 measured pairs per case;
  mixed and all-cold both valid, **40 measured pairs**, finite exact outputs,
  maximum absolute difference **0**, loopback worker reaped.
- Authenticated captured routing with synthetic activations/weights: same pair
  counts and checks, maximum absolute difference **0**, worker reaped. The
  archive's 62 routing rows were extracted; default measurements sample across
  both retained windows. These are not captured activation replays.
- Final run receipts' recursive artifact hashes verified independently.
- Actual omission controls under the frozen `cpu-cuda` numerical gate refused
  missing expert, missing shared contribution, and duplicate partition. The
  missing-shared control executes a valid graph with a B-only zero shared down
  projection, rather than relying on constructor rejection. These CPU-loopback
  controls do not constitute CUDA validation.
- Shell/remote cleanup tested with mocked external SSH orchestration and real
  local process groups, including success, numerical refusal, startup failure,
  signals, cleanup failure/unknown and preserving unrelated processes. The graph
  and native identity conversion were not mocked.

## Single scoped review and corrections

The independent scoped review returned **NO-GO** for the initial candidate:
wrong same-backend exact-equality comparator, missing shared-weight identities,
and unacknowledged remote cleanup. That original verdict is preserved, not
rewritten or relabeled GO. Accepted corrections:

1. Freeze the existing unchanged `legacy-cpu-unsplit/1` empirical plane-mass
   comparison with explicit mode before execution; keep exact equality as a
   diagnostic. Native adjacent-F32/excess-error/nonfinite probes, Python contract
   binding and real omission controls verify the correction. No hardware result
   preceded this contract selection; no tolerances were fitted or widened.
2. Inventory all eight immutable expert/shared/router tensors at setup, bind
   actual type/shape/length/hash, and recursively retain native manifest hashes.
3. Explicitly terminate the exact owned remote group, verify group/listener
   absence and acknowledge cleanup; preserve failure/unknown and nonzero exit.

No additional independent review lane was launched. Final corrections were
verified by the controller's source inspection and focused executions above.

## Retained artifacts and limits

Local durable evidence: `/home/zutfen/data/h5-layer7-local-validation/`.
It contains the original review, correction disposition/RED logs, parent test
log, final synthetic/captured runs, omission controls, actual build receipts,
benchmark executable and `SHA256.json`. Build receipts preserve original build
paths as provenance; rebuilding elsewhere uses the checked-in composed builder,
not a claim that those absolute paths are relocatable. Scratch build:
`/home/zutfen/.hermes/cache/scratch/h5-layer7-candidate6/`.

Cheap CI planner/status/retention/frozen-workload checks were exercised during
development. Native/build changes correctly classify as **full-risk for merge**.
No full suite, hosted CI or merge qualification is claimed. An earlier
`finalize_repository.py --check` timed out after 180 seconds without a verdict;
its process was stopped. It was not repeatedly relaunched.

This establishes executable production-graph integration, matched byte inputs,
source-order reduction, nondegenerate fixtures, failure sensitivity, reusable
weights/graphs and comparable timer collection on CPU loopback. It establishes
**no CPU-versus-GPU speedup**. The ready recipe in `layer7-cpu05.sh` still requires
separate hardware execution. Production-size optimized runtime, CUDA numerical
screening and remote cleanup remain unexecuted. Router cost is excluded
symmetrically. Real model weights/activations are needed to establish latency
and numerical representativeness for the real model; end-to-end impact requires
separate matched full-model evidence.
