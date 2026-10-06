# Issue #280 bounded observer — NO-GO / physical HOLD

This is an additive DRAFT implementation and stop report, not a completed
same-request observer or physical proof. One bounded CPU-only pass was attempted.
The independent review exposed missing authentic observations and false-positive
collector acceptance. Implementation stopped; no follow-on correction campaign,
new framework, synchronization, transfer, model acquisition or GPU execution
is authorized by this artifact.

## What was exercised

The parent reran 25 focused CPU tests, all passing, and 164 affected CI planner /
retention tests, all passing after staging the registered paths. The CPU test
environment doctor, planner self-check and retained-lineage verifier passed.
Synthetic positive, native-shaped staging/timeline and microbatch recordings
passed the real compiled emitter -> raw log -> collector CLI; missing-completion
and abort recordings exited 1. Those results test tooling only and are NOT
physical evidence. Passing these tests does not make this observer correct:
review negatives below expose holes in those tests and in the implementation.

Parent CPU fixture compiler: c++ (Debian 14.2.0-19) 14.2.0, command
c++ -std=c++17 -Wall -Wextra -Werror -I<instrumentation> <fixtures/recording.cpp> -o <scratch>/recording.
Fixture binary SHA256:
2745fc8dffbe3d41d3f73f1056d6edc940c80cc11a9985c8ebb4d8730d213ddb.
This hash identifies a synthetic recording executable, not llama-server.
Parent raw replay output: /home/zutfen/.hermes/cache/scratch/issue280-parent-replay/.

llama.cpp pin: b29c606e28a01b1bc8c1351026a0fa6e616bf6c4.
Observer patch SHA256:
3931525cf073771954da1427f4b073a75ec5dcc381b8453b92cf57ffe2d4bd0f.
Full transformed source Git tree: eb46e8dd1c0d0a6b7192ff4b587477abeb1801eb.
Complete byte identities: instrumentation/source-identity.json. The additions-only
transform preserves original computations, scheduler decisions, submissions,
transfers and waits; removing inserted bytes recovers original source bytes.
Vulkan build identity is NOT_BUILT. CPU syntax checks of backend, llama context
and server context passed, but the Vulkan translation unit stopped at missing
vulkan/vulkan_core.h. Neither a Vulkan integration build nor device execution
was verified. No SDK installation or host configuration change was attempted.

## Independent bounded review and specific STOP gaps

One read-only advisory review returned NO-GO for CPU-only draft correctness.
It examined the owned uncommitted overlay at base e518fd3a5b884fa69b74a082836e8bcad0989170,
bound by the patch/tree identities above; it was not a maintainer exact-head
approval. The parent independently reproduced four of the review probes:

| CPU probe | Actual current collector outcome | Required interpretation |
|---|---|---|
| Native first-use command counter 0 | rejects: node: invalid use | Wrong rejection; upstream counters start at 0 |
| Repeated successful wait on same timeline value | rejects identity mismatch | Wrong rejection; repeat waits need idempotent treatment |
| Shape ne0=1048576 with unchanged payload bytes | ok=true | False positive; range/shape reconciliation incomplete |
| Extra recorded node/weight/dispatch never submitted | ok=true | False positive; compute attribution coverage incomplete |

Further review findings remain unresolved, not silently waived:

1. Sampling/graph reconciliation is aggregate-only. Actual decode input token
   IDs and absolute positions are not emitted; same-count but wrong-order
   sample/decode streams can pass. One previous-sample -> next-decode causal
   check is missing.
2. Expected boundaries use a fixture bytes-per-token rule, not independently
   validated native graph-specific ranges. Shape/type/strides/view offsets are
   recorded but not reconciled; actual source/destination copy offsets and
   repeated-copy occurrence/split identities are missing.
3. The collector admits only CPU_FIXTURE, exactly two dies and nonempty
   boundaries. It cannot authenticate the planned single-die A baseline.
   Source identity emits once per process, while collection ends at first
   response; the second warm request has no authentic independent framing.
   Source-labelled synthetic logs are not a real source observation contract.
4. Aborted-stream reconciliation loses completed-copy aggregate totals and
   does not return sampled token IDs/timestamps or unsubmitted recorded work.
   Request acceptance, stop reason and returned-token reconciliation are absent.
5. Weight operands on dispatched nodes are partial placement evidence, not a
   complete named weight/KV/mutable-state inventory, byte reconciliation or
   explained-versus-unexplained CPU placement accounting.
6. Vulkan translation-unit compilation remains unverified as stated above.

These are concrete missing observation/reconciliation seams. The bounded pass
has NOT demonstrated the required end-to-end same-request source-log contract.
Some defects may admit small fixes, but the complete remedy's scope is not
established. Stop for maintainer review rather than expand this pass into a new
source/harness campaign or present synthetic success as physical readiness.
No current collector ok=true result may be used as a physical PASS.

## Prospective next review

RUN-PLAN.md and workload.json preserve eight launches / sixteen requests /
twenty-minute physical cap / $0 incremental cash. The thresholds remain
proposals. The exact model member/revision/LFS SHA256/size and proposed staging
source are metadata-resolved in model-source.json; no model member was read,
downloaded or staged. Acquisition and staging are not authorized.

Before any physical run, review must resolve the observation gaps, verify a
native build, approve the exact source/criteria/run plan and staging, obtain
fresh cooling confirmation and approve temperature AND health-stop policy.
No tuning until PASS; no GPU enumeration/exercise, transfers, host changes,
hardware purchases, holdout access, #239 activation or automatic successor.

Mandatory validation order remains repository policy: focused checks and
ordinary exact-head CI, maintainer exact-head review, then the single hosted
Final CPU Validation at the approved reviewed head (REQUIRED/DEFERRED until GO).
An advisory review cannot supply that GO; a draft CI success cannot authorize
physical execution. The review found NO-GO, so final full CPU validation is not
self-dispatched. This PR remains OPEN/DRAFT/UNMERGED for maintainer review.

## Correction round addendum (post-NO-GO, same PR)

The accepted NO-GO findings above were corrected in this same PR as bounded
additive commits (295a8d2 RED controls → efa2872). The NO-GO report above is
preserved as historical evidence and its probes now resolve as designed: the four
false-positive probes reject, the two wrong-rejection probes are admitted.
Observation law now covers submission/completion classification, per-occurrence
copy-range reconciliation with endpoint-offset bounds, decode token/position
causality at the pinned `pos_next` semantics, per-request framing with
not_attempted accounting, placement inventory with layer-ownership and
buffer-category laws and an explicit denominator relation, and structured abort
accounting. The additions-only transform covers six source files; removing the
inserted bytes restores the pinned sources exactly; disabled mode emits nothing.

Independent exact-head adversarial reviews ran per round (NO_GO ×5, then GO at
efa2872: 76 probes, 0 false positives; receipts under the campaign record). All
six transformed units pass `c++ -std=c++17 -fsyntax-only`; the Vulkan TU was
syntax-verified on an isolated header-equipped host (vulkan_core.h v309 + shader
header generated by the pin's own vulkan-shaders-gen; no device contact). A
syntax check is not a build: build identity remains NOT_BUILT and
VULKAN_BUILD_NOT_VERIFIED remains a prerequisite.

Physical validation stays HELD. Final CPU Validation is
DEFERRED_PENDING_MAINTAINER_GO; ordinary CI success is not that authorization.
No model bytes were read or staged; no GPU activity, transfers, or host changes;
#239 and holdout material untouched. Thresholds, cooling, staging, and the frozen
physical budget remain maintainer decisions.
