# Q8 fixed two-CUDA topology (#313)

This is the smallest opt-in software slice for issue #313. It does not record
a physical result or authorize a hardware run.

## Fixed topology

`selection: two-gpu` keeps the complete Q8 source and layers 0--40 on the CPU
coordinator. One small-RAM worker owns two complete CUDA layer ranges:

| owner | native selector | coordinator selector | complete states | encoded weights |
|---|---|---|---|---:|
| coordinator CPU | `CPU` | `CPU` | embeddings and layers 0--40 | 168,221,585,536 B |
| worker GPU 0 | `CUDA0` | `RPC0` | layers 41--44 | 11,035,064,960 B |
| worker GPU 1 | `CUDA1` | `RPC3` | layers 45--47 and output | 8,957,357,824 B |

The byte census comes from the exact pinned Q8 metadata used by the operator.
It is a lower bound, not a fit verdict. Each VRAM domain is admitted separately
with its own weights, persistent state, backend allocation, graph, workspace,
observer and reserve. Worker RAM is charged separately for assigned metadata,
page residence, verification, transport and bounded receive/cache staging,
plus the logical cross-device RPC payload and unknown overlap/runtime heap.
The mode requires assigned-only backing; the worker has no full-source backing
and no permanent host weight mirror.

The worker runs one reviewed RPC server with `--device CUDA0,CUDA1`. The
coordinator registers its one owned listener through the FQDN and absolute
trailing-dot spelling of that same DNS name. Arbitrary second hosts refuse.
Native enumeration makes the selected client devices `RPC0` and
`RPC3`; `--gpu-layers 8 --tensor-split 4,4` places four complete layers on each.
The distinct registrations produce distinct RPC dispatchers. At the
GPU0-to-GPU1 boundary, pinned llama.cpp therefore declines its same-dispatcher
server copy and uses the existing generic coordinator-staged GET/SET path. No
P2P or server-local GPU copy is assumed. Duplicate endpoints, reversed primary
ownership and `server-local` routing refuse.

Existing `cpu-only` and `one-gpu` selections and their identity rows are
unchanged. Assigned-only v7 acquisition, immutable tensor identities,
whole-tensor guards and missing-only restart reuse are reused without a new
cache or protocol.

## Honest observation boundary

The reviewed CUDA build closure is eligible for static planning/lowering only.
The retained transfer observation ABI identifies RPC operations but not the
endpoint/device ordinal for each occurrence. It cannot prove the required
`RPC0 -> coordinator staging -> RPC3` transition, so dynamic reconciliation of
`two-gpu` explicitly refuses. A physical run needs a newly reviewed observer
receipt that adds that exact join; source inspection or a CPU fixture must not
mint a qualified CUDA identity.

The later bounded hardware recipe is
[`../../tools/native-cache/q8-two-cuda-recipe.md`](../../tools/native-cache/q8-two-cuda-recipe.md).
It requires real per-device and host budgets before launch; the roughly
20,018,422,784 B aggregate encoded GPU weight total is only a placement
hypothesis.

## Offline evidence

Focused regressions cover selector order and native argv, nonoverlapping
whole-layer/tensor ownership, final output ownership, independent VRAM refusal,
bounded worker-host charges, unsupported route refusal, assigned-only backing
projection and explicit dynamic-observer refusal. Existing CPU/loopback suites
continue to cover old modes, complete assigned-bank loading, restart reuse,
changed inputs and failure cleanup. Those fixtures do not prove CUDA execution,
residency, numerical correctness or capacity.
