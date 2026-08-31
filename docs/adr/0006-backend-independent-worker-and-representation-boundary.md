# 0006. Backend-independent worker and representation boundary

Date: 2026-08-30
Status: Superseded by 0008

> **Current doctrine clarification (2026-08-31):** ADR 0008 supersedes the
> universal physical `Worker` abstraction used here. The durable decisions
> remain canonical through the Fabric Doctrine: backend-native fast execution,
> backend-native state representations, strategy-specific semantic execution
> boundaries, transport orthogonality, bounded heterogeneous correctness
> contracts, and rebuilding stable fast paths at execution-plan epochs.

## Context

InferSwarm's first working path is deliberately NVIDIA-focused. Phase 1 used
CUDA, CUDA Graphs, Triton, and Qwen3.6 NVFP4 expert banks to answer the first
mechanism questions quickly on available RTX 3060 hardware. Post-Phase-1 D1
then showed that falling out of FreeToken's captured batch-1 execution path is
catastrophically expensive on that stack: the matched graph-enabled local
control ran at 54.6057 tok/s while the matched graph-disabled local control ran
at 6.2161 tok/s. The current graph-disabled distributed path then fell further
to 3.9124 tok/s.

Those results make backend-native captured/compiled execution important, but
they do not justify defining InferSwarm in terms of CUDA Graphs. The same
problem exists for expert representation: NVFP4/Triton is a useful first
backend, but a future AMD, Intel, CPU, or remote worker may require a different
weight representation and execution substrate. If NVIDIA implementation
choices leak into the fabric contract, heterogeneous hardware becomes an
architectural rewrite rather than another backend.

This refines, but does not replace, ADR 0004's decision that MoE/NVIDIA is the
first execution strategy while the platform abstraction remains model- and
vendor-independent.

## Decision

InferSwarm's core worker, placement, and execution semantics are independent
of accelerator vendor, graph/capture API, expert-weight quantization/packing,
and transport.

The following are architectural invariants:

1. **Backend-native fast execution, not CUDA Graphs specifically, is the
   requirement.** A hot inference path must avoid per-layer host-orchestrated
   eager execution when a backend provides a captured, compiled, queued, or
   persistent execution mechanism. NVIDIA workers may use CUDA Graphs; another
   backend may use a different mechanism.

2. **CUDA-specific fusion is an optimization beneath the worker boundary.**
   Same-host NVIDIA workers may be folded into a unified or segmented
   multi-device CUDA graph when that is the fastest correct implementation.
   Doing so must not redefine an InferSwarm worker as "a participant in a CUDA
   graph." The conceptual worker remains an asynchronously executable resource
   that can have another backend implementation.

3. **InferSwarm owns logical expert identity, not one global packed weight
   format.** Placement assigns logical experts to workers. A worker may hold
   those experts in a backend-native representation appropriate to its
   hardware. NVFP4/native ModelOpt/Triton is the first NVIDIA representation,
   not the canonical InferSwarm representation.

4. **Worker capabilities must eventually describe representation and execution
   support.** A placement/execution plan must be able to determine whether a
   worker can legally and efficiently host a logical expert without assuming
   one vendor or quantization. The exact capability schema is intentionally not
   frozen by this ADR.

5. **The cross-worker semantic boundary is routed work and route
   contributions, not packed expert bytes.** Workers consume routed activation
   state plus the routing information required by the selected execution
   strategy and return semantically correct contributions for deterministic
   reconstruction/reduction. The exact interchange dtype/layout is not frozen
   here.

6. **Different internal representations may require numerical, rather than
   bitwise, equivalence.** Identical backend/kernel/representation paths should
   retain exactness tests where available. Heterogeneous backends or
   quantizations may use a predeclared bounded numerical-equivalence contract,
   including finite outputs and model-level correctness checks, rather than an
   impossible requirement for bit-identical arithmetic.

7. **Transport is orthogonal to execution.** Same-host staging, device-to-device
   transport, shared-memory/RDMA-style mechanisms, and network transport are
   implementation substrates beneath the logical worker contract. A transport
   optimization must not become a requirement for every worker class.

8. **A stable fast-path topology may be rebuilt at topology epochs.** InferSwarm
   does not require workers to join or leave a captured/compiled execution plan
   on every token. Worker discovery, placement, buffer construction, and
   capture/compilation may establish an execution-plan epoch that is reused for
   many tokens and rebuilt when membership or another material topology input
   changes.

9. **The architecture must admit heterogeneous coordinators as well as
   heterogeneous workers.** GPU0/coordinator is not permanently an NVIDIA
   device. Core routing, placement, worker capability, and correctness semantics
   must remain expressible if the coordinator is AMD, Intel, CPU-backed, or
   another supported accelerator.

The intended layering is therefore conceptually:

```text
InferSwarm routing / placement / execution plan
                    |
          backend-independent worker boundary
             /             |             \
      NVIDIA worker     AMD worker     other worker
      CUDA/NVFP4/...     native fast     native fast
      implementation     implementation  implementation
             \             |             /
              semantic route contributions
                    |
        deterministic reconstruction/reduction
```

The concrete type names, method signatures, buffer descriptors, capability
schema, interchange dtype, plugin mechanism, and coordinator/worker API are not
part of this decision. They will be designed from measured post-Phase-1
experiments rather than invented in advance.

## Consequences

- D2 and other near-term experiments may be aggressively NVIDIA-specific when
  that is the fastest way to prove a performance mechanism, including unified
  multi-device CUDA graphs and NVFP4/Triton resident banks.
- Review of those experiments must distinguish a reusable worker/execution
  concept from an NVIDIA-only optimized implementation.
- A successful CUDA fast path does not by itself establish the final worker
  abstraction; it becomes one backend implementation beneath that abstraction.
- Future AMD/Intel/backend work is allowed to repack the same logical experts
  into different physical representations, subject to an explicit numerical
  contract.
- The core scheduler cannot assume that all workers share one quantization,
  kernel implementation, device API, or transport.
- Backend abstraction must not be introduced prematurely at the cost of the
  current experiments: concrete interfaces should be extracted only after the
  execution boundaries are supported by evidence.
- Performance remains a first-class constraint. "Portable" does not authorize
  falling back to a host-orchestrated eager hot path that makes inference
  impractical.

## Hypotheses distinguished from decisions

- **Decided:** CUDA Graphs and NVFP4/Triton are backend-specific implementation
  choices, not InferSwarm semantic requirements; logical expert identity and
  the worker boundary must admit other vendors, representations, execution
  substrates, transports, and coordinator devices.
- **Decided:** same-backend fusion is allowed as an optimization so long as it
  remains beneath the backend-independent worker semantics.
- **Not yet decided:** the exact `Worker`, `WorkerCapability`, transport,
  representation, buffer/queue, or plugin interfaces; the interchange
  dtype/layout; or whether local fused CUDA workers are exposed internally as
  distinct runtime objects.
- **Not yet proven:** that an AMD, Intel, CPU, or network worker can meet an
  acceptable performance or numerical-equivalence envelope.
- **Not yet proven:** that D2's current CUDA graph findings translate to a
  production architecture or to acceptable 1->2->3->N worker scaling.
- **Not claimed:** that heterogeneous quantization is free of model-quality
  impact. Any such representation requires its own predeclared correctness and
  quality evidence.
