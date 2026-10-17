# Native expert-demand inputs for #314 (#312 coding slice)

## Scope and starting point

Started from freshly fetched `origin/main`
`100eb138847feedec135e5e8ca86dadd3971eb12`, in an isolated worktree on
`issue-312-native-demand`. This matches the reported last-tested baseline;
other checkouts and their changes were preserved. Read issues #312, #314,
#313 and the Fabric Doctrine before implementation.

This adds structural profiling, not placement selection, arbitrary native
expert-subset execution, or a new qualification framework. Whole-layer
experiments remain prerequisite evidence, not completion of expert placement.
No historical failure or general-observer refusal is revised. No native
hardware build, current-model request, acquisition, model rehash, deployment,
GPU operation, or host change was performed for this coding slice.

## Capture boundary

The existing native overlap integration selects one qwen4exp layer. Its
private router already owns packed selected I32 IDs on CPU; capture uses
those IDs without changing expert work. All other layers use the native
scheduler callback on computed `ffn_moe_argsort-<layer>` nodes. The top-k
itself is a strided view, not an independently computed callback node.
Only the selected K IDs are retained, grouped by layer, explicit phase,
step, and token row. The dedicated single-request profiling CLI marks prefill
and decode explicitly: a one-token prompt is still prefill.

The profiling buffer has independent finite row/byte/step bounds. It does
not consume the general observer's 512-event budget or remove its refusal.
Drops remain visible and cannot yield a complete profile. Re-export does
not drain capture state. Raw prompts, token IDs, generated text, router
probabilities, activations, and results are not exported. `IS309_CAPTURE`
is refused by the profiling CLI because that older diagnostic records
input/result tensors.

The normal server does not enable this profiler. Routing, selected experts,
quantization, arithmetic, placement, and numerical tolerances are unchanged.
Profiling adds synchronization/readback and collection overhead; offline
fixtures do not measure its effect on real service.

## Identity, costs, and existing representations

Profiles bind model source/revision/digest/representation, native
source/build digest, workload identity/cohort, phase, and shape. Model and
build custody must come from the existing authenticated inputs, not a fresh
model hash. Operator-attested identities are not discovered physical facts.
The reducer requires independently supplied expected identities; Qwen3.6
records are not current Qwen3.8 demand. Profiling/training prompts must remain
separate from later evaluation prompts.

Reuse `inferswarm.operator.profiles` resource/capability/link evidence and
the existing strategy/planner metric/value/unit/statistic vocabulary. A
resource snapshot is not a new hardware ranking policy, and supplied
evidence must retain its provenance/freshness limits. Readback/collection
and existing overlap stage observations describe their actual CPU/client
boundaries. Dispatch, shared, and join stages overlap and are not additive
wall time. Client RPC wait is not GPU kernel time. Unavailable per-expert
execution and link costs remain unknown; frequency alone cannot rank a
placement.

## Smallest operations handoff (proposal, not execution authority)

1. Review this source and run the focused CPU capture/reducer fixtures. Batch
   ordinary hosted CI and final CPU validation only after the reviewed head
   may be pushed. This task explicitly stops before push/PR/merge, so no
   hosted result for an unpublished head is claimed.
2. Build only the CPU native profiling client through the existing builder,
   from the already authenticated pinned archive in a fresh cache. The
   additive `--demand` target avoids compiling the server/MTMD closure:

   ```text
   MOE_OVERLAP_TARBALL=<authenticated-existing-archive> \
     python3 tools/native-moe-overlap/build.py --demand \
     --cache <fresh-profile-build-root> --jobs 2
   ```

   This is a requested build, not a verified executable-ready dispatch. The
   underlying source pin is
   `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, tree
   `950999fe62b7fe55f44ab5b7394e3c8542f37f12`. Record the new binary and
   build manifest as a successor, never relabel an old accepted binary.
3. Under a separately approved finite load/request/memory/deadline envelope,
   use the existing current Qwen3.8 Q8 backing and a single private profiling
   prompt with a short explicit decode. An all-layer capture, even one
   request, is more useful than another fixed-input one-layer trace; it is
   still only a seed profile, not representative economics. The invocation
   and reducer flags are documented in
   `tools/native-moe-overlap/README.md`. Set row capacity to cover every
   expected layer/step and inspect all drop/completeness fields afterward.
4. Preserve current residency. The dedicated CLI is not integrated into the
   guarded two-CUDA operator runner and must not be substituted for its
   binary. Its optional single-RPC bank override supports the existing
   one-layer overlap mechanism, not the full two-listener 41/45 operator
   configuration. If that full configuration is required for the first
   capture, the missing seam is matching the existing native device/split
   arguments and supervision in this profiling entrypoint; do not improvise
   a new placement or launch a model merely to discover that gap.
5. Reduce the export against independently retained model/native/workload
   identities and, where available, current resource evidence. Retain raw
   structural export, summary, build identity and workload digest privately.
   A later small diverse profiling workload is needed before choosing a
   representative #314 candidate; evaluate on separate prompts.

Optimized 41/45 remains the working baseline for its larger memory margin.
The latest 40/44 attempt produced no request sample; its older decode sample
falls within the latest 41/45 range. No winner or measured speedup is claimed.

## Reliability slice remains separate

The independent `fix/native-participant-liveness` branch contains the
retained-evidence investigation at
`docs/investigations/native-participant-liveness.md`. The authenticated bundle
records both `client participant lost` and an rpc1 memory/swap monitor safety
stop. It lacks the individual failing PID/start observation and timestamped
stop ordering. An active systemd cleanup receipt does not establish which
identity predicate failed earlier. The /proc false-negative attribution is
not proven, and no liveness change or hardware rerun is justified. Existing
process identity checks, memory caps, deadlines, and terminal cleanup remain.
