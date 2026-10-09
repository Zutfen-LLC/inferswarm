# #299 production observer scope amendment

Status: implementation authorized by the maintainer on October 9, 2026; implementation incomplete. This authorizes the bounded coding/local-fixture work below, not deployment, physical execution, issue acceptance or merge.

## Authorized closure

- Include an observation-only native telemetry patch, real collector and independent identity reader, wired into normal Q8 `run_config`.
- Keep runtime base revision `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` and base tree `950999fe62b7fe55f44ab5b7394e3c8542f37f12`. Record base, patch/transformed-file identity and resulting compiler/build/artifact identity separately. Patched builds are derived builds, not the unmodified pin.
- No changes to inference mathematics, kernels, placement or scheduling to obtain a pass. Preserve the explicit B CPU → A staging → B CUDA copy route. CPU-only is a separately selected alternative, never fallback.
- Version the observation contract. Before dispatch: identity, source integrity, resource admission and available static ownership checks. During the same request: capture native task/graph/ubatch/state/copy evidence. Before accepting output: require complete fresh noncontradictory dynamic evidence joined to that request. Missing/stale/contradictory evidence fails with exact-owned cleanup. Planned placement never substitutes for observed execution.
- Complete the plan-only CLI, examples, receipts, documentation, independent reviews and verified draft PR.

The phase amendment replaces the earlier unrealizable requirement for completed computation copies before the first POST under `--no-warmup`. Historical `owned-observation/1` semantics/evidence remain unchanged; the new contract is an explicit successor, not silent weakening. Startup graph reservation is not request execution. Dynamic refusal means the request executed but its output was not accepted, not that dispatch never occurred.

## Bounded native development verification

Only CPU-only native builds and tiny synthetic buffer/graph/loopback tests in the existing development environment are allowed. No model downloads, real-model inference, GPU qualification, new dependencies, inference-host changes, deployment or merge. Physical preparation/qualification remain in #300. No extra model warmup/probe requests, observation eval callbacks or new synchronization to manufacture evidence.

Limits recorded before starting any native build:

| Resource | Limit |
| --- | --- |
| Build concurrency | One native build, one compiler job at a time |
| Process virtual memory | 3 GiB address-space limit per compiler/link/test process |
| Owned process-tree memory | Abort at 4 GiB summed RSS; not a unique-residency measurement |
| Core / individual output file | No core dumps / 256 MiB maximum file |
| Time | 30 minutes per build phase; 90 minutes cumulative native-build wall time; 60 seconds per tiny fixture |
| Generated source/objects/binaries | 4 GiB maximum, checked around each compile |
| Disk floor | Abort below 16 GiB free |
| Tiny native buffers | At most 1 MiB each, 16 MiB total |

A standard-library supervisor must enforce time/process/file limits and check actual memory/disk. Build artifacts and logs stay in task scratch, never in the read-only native base checkout. Limit breaches retain failure evidence and stop the owned process tree. Bounds may be reduced; expansion needs a new decision. No long-lived fixture listener survives its test.

Preflight found GCC 14.2 and GNU Make 4.4.1 installed; CMake/Ninja were absent from PATH and common candidate paths. Existing-toolchain build discovery is underway. No installation is authorized. A real direct compiler recipe may be used only if derived from authenticated native target definitions; helper-only compilation must not be described as a full native target build. CPU verification does not establish CUDA translation-unit compilation or physical GPU correctness.

## Completion and review boundaries

Each dependency-complete slice follows RED-first implementation, parent verification, independent SPEC then QUALITY review. Final original-acceptance integration review must include this amendment. Scope approval is not implementation approval. A usable implementation requires actual native producer artifacts, real collector/identity code and automatic normal wiring—not just an injectable interface or synthetic JSON generator.

Cheap repository-consistency checks and draft PR precede maintainer exact-head review and separately gated final full/hosted validation. No deployment or merge. Physical qualification, Q8 numerical/kernel correctness, real memory/traffic/fit and performance remain unperformed until separately authorized #300 work.
