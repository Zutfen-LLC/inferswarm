# Issue #280 CPU-only observer implementation

**NO-GO: independent CPU review found unresolved correctness gaps.**
See [the stop report](../README.md); passing fixtures below are incomplete and
source-log readiness has NOT been established.

**Tooling/fixture validation only. Physical runner: HELD_UNAVAILABLE.**
This directory grants no physical execution authorization. There is no GPU
launcher, model reader, device discovery, pooling framework, or acceptance gate.
The parent owns prospective plan, workload, model-source, and status documents.

## Components and bounded contract

- `scripts/issue280_source.py`: source-pin/hash-checked, insertions-only overlay
  for llama.cpp `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. The upstream checkout
  is never edited. The overlay emits metadata through original loggers; original
  scheduler decisions, computation, transfers, dispatches and waits are unchanged.
- `issue280_observer.h`: opt-in `ISSUE280_OBSERVE=1` raw JSON emitter. The logging
  implementation is translation-unit-local because server/llama/ggml sinks differ.
  Disabled hooks do not evaluate metadata or logging expressions.
- `scripts/issue280_observer.py`: strict raw-log parser and bounded collector.
  One sequential request, no speculative decoding, cache reuse, interleaving,
  or parallel copies. It consumes an explicitly bracketed single-request stream,
  not an entire server launch/warmup log or multiple requests. A CPU fixture
  contract is the only admitted contract; source-labelled replay also remains
  explicitly not physical proof.
- `../fixtures/recording.cpp`: synthetic CPU recording producer using the same
  emitter/schema. No fixture identifiers or byte counts describe a real model.

Correlation retains graph/sequence/token identities, cached BDFs, named node and
weight-allocation ranges, command-buffer/use-counter identities, actual nonzero
compute dispatches, queue submissions and successful **existing** fence/timeline
waits. Empty/copy-only submissions cannot establish compute. Preexecution
scheduler copy manifests bind tensor shape/strides/view offsets and logical
ranges before boundary copies. Source/destination staging-buffer IDs correlate
the nested host legs; only the outer synchronized boundary interval is summed.
Logical bytes are not PCIe wire traffic. Sampling counts reconcile prefill
microbatches, the first sample produced by prefill, final EOS, and non-EOS limits.
Partial/abort recordings retain pending work and fail closed.

## Verification performed

- `.venv/bin/python -m unittest tests.test_issue280_observer tests.test_issue280_source -v`
  — 25 tests, PASS. CPU emitter fixtures exercise the real parser/collector;
  negative recordings cover incomplete/empty submissions, missing waits/staging,
  wrong requests/bytes/output lengths, stale timeline values and malformed fields.
  RED/GREEN also caught and corrected cross-translation-unit logging sink merging.
- CPU fixture compiled with `c++ -std=c++17 -Wall -Wextra -Werror`.
  Real collector CLI replay passed positive, native-shaped staging/timeline,
  and microbatch recordings; missing-completion and abort exited 1 as required.
  Host-local raw logs and CLI outputs are under
  `/home/zutfen/.hermes/cache/scratch/issue280-cpu-replay-final/`.
- CPU syntax-only checks passed for transformed `ggml-backend.cpp`,
  `llama-context.cpp` and `server-context.cpp` (using pinned-source include paths).
- **Vulkan translation-unit compile remains unverified:** the local compile
  stopped at `fatal error: vulkan/vulkan_core.h: No such file or directory`.
  No SDK installation, runtime build, physical inference, or GPU probe was done.
  This is a compile-verification gap, not evidence of physical correlation.
- Environment doctor, CI planner self-check and test-retention verifier passed.
  Child pre-staging run had one tracked-tree-census failure. Parent reran the
  affected planner/retention suites after staging: 164 tests, PASS. These
  registration/preservation tests do not resolve observer correctness gaps.
- Full CPU and hosted validation remain deferred to maintainer exact-head review.
  No parent finalizer or status writer was run.

## Exact source identities

`source-identity.json` records original/transformed source SHA-256 values, emitter
and patch identities, reconstructed base/full transformed Git trees, and an
explicit NOT_BUILT Vulkan build identity. `applied-source.patch` is reproducible
from the pinned public source and current emitter; both recorded hashes were
checked against the retained bytes. Removing the exact inserted logging bytes
recovers every original source byte in the focused tests.

The transform can be regenerated **without any build or launch**:

```sh
.venv/bin/python scripts/issue280_source.py /home/zutfen/llama.cpp-252 <new-source-overlay-directory>
```

The source observer is not represented as physically validated or generally
admitted. A future authorized campaign would still need a verified Vulkan build,
a real model/placement contract, a bounded request-log capture, and authentic
same-request records before any physical claim. Never promote fixture success or
source feasibility to acceptance or execution authority.
