# V0-C methodology: S2 backend-adapter participant

Issue: Zutfen-LLC/inferswarm#143 (parent #140)

Status: frozen before any V0-C correctness-bearing physical execution.

## Authority and starting point

- InferSwarm starting `main`: `d9bcd539e2191056a9340cb69f378dfa018bb8de`.
- Accepted V0-B handoff: PR #146, accepted evidence head
  `c912891c669412d5206697bb537eb77f27f55824`, terminal
  `V0B_PROCEED_TO_INTEGRATION_SPIKE`.
- Selected seam: `S2-backend-adapter-participant`.
- This methodology is a narrow integration spike. It neither freezes a public
  API nor promotes any implementation as a default or preferred backend.

## Frozen subject and proving resource

The initial strategy-defined opaque execution unit is the complete
`Qwen2.5-3B-Instruct-Q4_K_M.gguf` model operation. V0-B selected whole-model
scope because that is the smallest honest unit the accepted V0-A substrate
actually proved end-to-end (37/37 layers on one device).

- Model size: 1,929,903,264 bytes.
- Model SHA-256: `9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`.
- Representation: `gguf-q4-k-m`.
- Initial physical Compute Unit: `cu-amd-a`, on `node-inferswarm02`, PCI BDF
  `02:00.0`, paired with `mr-amd-a-vram` (8,589,934,592 bytes).
- Backend-local adapter implementation identity: `impl-portable-amd-a`.
- Initial runtime/probe source: llama.cpp
  `8ea290247c87ced2ab245b056ffe96dbcf90d36c`, Release build with
  `-DGGML_VULKAN=ON`.
- Expected Vulkan runtime: loader 1.4.309.0 and RADV 25.0.7-2+deb13u1, as
  recorded in accepted V0-A evidence. A run records the newly observed identity
  and fails closed if it does not match this frozen target.

The same resource snapshot includes `cu-nv-a` / `mr-nv-a-vram` at BDF
`04:00.0` with a distinct opaque native implementation capability. It provides
ontology and planning pressure only; no mixed-device execution is claimed.

## Generic execution contract

The strategy exposes the unit's representation, `compute` feature requirement,
3,254,091,776 resident model-byte requirement, 536,870,912 bytes of headroom,
and `QUALIFIED` integrity requirement. The generic planner evaluates opaque
capability records by physical binding, representation, features, integrity,
evidence freshness, memory/headroom, and economics. It uses the deterministic
initial objective `MIN_STARTUP_SECONDS`; it never branches on backend, vendor,
or model-family names.

A candidate must be excluded with a retained generic explanation when any gate
fails. Canonical negative controls are wrong physical binding, stale evidence,
unsupported representation, missing feature, insufficient headroom, and missing
correctness trust. The planner freezes a self-digesting plan before realization.

## Materialization and execution contract

The adapter must retain backend stderr and prove all of the following before a
result is eligible for comparison:

1. the selected backend device is `Vulkan1` and reports BDF `02:00.0`;
2. all 37/37 model layers were offloaded;
3. the model, executable, adapter, and frozen-plan SHA-256 identities match;
4. the planned device-local materialization is present before execution;
5. no source fetch/rematerialization or unplanned state movement occurs after
   ready; and
6. `unexplained_persistent_host_mirror_bytes == 0` only if direct accounting,
   not process RSS alone, establishes it.

Backend initialization, selected-device mismatch, partial offload, unavailable
representation, and any attempt to substitute another execution resource are
hard failures. They must not fall back to CPU or another accelerator.

## Prospective correctness comparator

The canonical fixture is the V0-A frozen deterministic greedy operation:

```text
prompt: The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:
sampling: --temp 0 --seed 42 -n 48
```

The reference is AMD-A's accepted V0-A Vulkan visible generation. V0-C uses
byte-exact canonicalized visible output equality, zero NaN/Inf markers, clean
exit, exact model/runtime/device/plan attribution, and full layer-offload proof.
This deliberately narrow comparator is not a claim of ADR-0010 layer-2
numerical equivalence or layer-3 semantic qualification; those remain not
established by V0-B. A failing comparator produces `V0C_VULKAN_INTEGRATION_FAIL`
or `V0C_EVIDENCE_BLOCKED`, not tolerance tuning.

## Non-claims

This does not claim production support, a final plugin API, native-backend
parity, a performance victory, mixed-resource request execution, cross-backend
semantic equivalence, logits-level equivalence, or a new numerical threshold.
