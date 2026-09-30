METHODOLOGY — R8-I3C Vulkan mechanism diagnostic (Issue #252)
============================================================

FROZEN 2026-09-30, before any Issue #252 physical execution. This is a prospective, repository-only method freeze. It neither accepts a result nor authorizes execution. The accepted #250 boundary is read-only context: zero↔nonzero Vulkan participation was localized as a necessary boundary for the observed case-3072 fresh-process variability; it did not establish a lower-level cause.

0. Subject, authority, and inputs (exact, read-only)
----------------------------------------------------
- Issue: #252, R8-I3C. Accepted base/main authority `850429973a2061ff82dc46dc06481ad13ebd24d9`; accepted #250 terminalization head `3e4e8790ed0225741642fecd7dc5ff707cd9b050`; accepted #250 physical execution head `5d015b5bc437bb82d5e966d0da8b90ff44b079a1`.
- llama.cpp source authority: commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, tree `950999fe62b7fe55f44ab5b7394e3c8542f37f12`.
- Accepted comparator: SHA-256 `6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad`; unchanged and read-only.
- Model: Qwen3.8-Flash-Next-UD-IQ1_S; the immutable members are: `Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf` SHA-256 `88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd`; `Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf` SHA-256 `3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6`; `Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf` SHA-256 `0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a`. These are fixed in `scripts/issue252_constants.py` (`MODEL_MEMBERS`) and the reconciliation evidence; do not substitute a member or model.
- Host/subject facts from the accepted predecessor authority: inferswarm01, reference arm B, NVIDIA GeForce RTX 3060, BDF `00000000:03:00.0`, UUID `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, driver `610.57.04`, ICD `nvidia`, Vulkan `1.4.341`. These identify the accepted comparison subject; they do not prove any #252 run.
- The predecessor's reported source-pin literal `b29c606e28a01b1bc8c1351026a0fae616bf6c4` (39 characters) is preserved exactly as historical text and is not repaired or normalized. The independently verified 40-character pin above is the actual source authority; the mismatch is recorded in Phase 0.
- `scripts/issue252_constants.py`, `issue252_phase0.py`, `issue252_vulkanpath.py`, and `issue252_arms.py` define and derive authority. Issue #248/#250 retained populations and terminalization are read-only inputs; never rerun or rewrite them.

1. Phase-0 reconstruction (offline)
-----------------------------------
Phase 0 is source/evidence reconstruction only; it is not physical execution or a causal finding. Its committed machine-readable outputs are:
- `evidence/phase0/reconciliation.json`: pinned base/predecessor verification, accepted comparator/model/host facts, and llama.cpp commit/tree identity.
- `evidence/phase0/vulkan-path.json`: pinned-source Vulkan path/control analysis, candidate mechanisms, limitations, and preserved predecessor literal discrepancy.
- `evidence/phase0/hypothesis-matrix.json`: six ranked candidate classes, their source basis, discriminator mapping, arm definitions, repeat law, and terminal vocabulary.

Source alone establishes neither a runtime-selected shader/allocator path nor a race, uninitialized read, numerical root cause, or driver defect. All Phase-0 outputs are offline derivations and make no claim of new physical observations.

2. Hypothesis matrix (six classes; all unproven)
------------------------------------------------
Rank order is fixed in `scripts/issue252_arms.py:HYPOTHESES` and `hypothesis-matrix.json`:
1. H1 — GPU input/scratch content or padding read before initialization; `discriminator_arm=None` because no proven one-factor control establishes/forces initialization.
2. H2 — cross-queue synchronization or buffer-aliasing gap; A1 screens submission-order sensitivity only, not alias correctness.
3. H3 — driver-reported memory type/capability or allocation fallback varies; A4 is a prospective memory-preference discriminator, not a forced fallback.
4. H4 — driver compilation or implicit driver shader cache; `discriminator_arm=None`; absence of an application-cache control does not control driver-internal cache behavior.
5. H5 — shape-sensitive reduction/MMVQ/cooperative-matrix/split-K path selection; A2 disables only coopmat feature detection and does not jointly change MMVQ or split-K.
6. H6 — ASLR/pointer-keyed reuse and submission timeline values; `discriminator_arm=None`; no direct control fixes pointer-keyed reuse, and A1 is not double-counted for this class.

Every class remains unproven before and after any arm. A change in repeat outcome is evidence of a discriminator association under the frozen conditions, not by itself a source-level root-cause proof. Do not promote a rank, source observation, or arm outcome into a causal claim the evidence does not establish.

3. Frozen discriminator arms, population, and custody
----------------------------------------------------
Every arm holds fixed the accepted model, binary/comparator, request contract, case-3072 geometry, `ngl=1`, host/subject, launch shape, and observation seam. Each arm changes exactly one factor, its named environment control; no arm bundles interventions. The five controls, exactly as frozen in code, are:
- A1 `GGML_VK_SERIALIZE_SUBMISSIONS` — enable submission serialization; namespace `d252-arm-serialize`.
- A2 `GGML_VK_DISABLE_COOPMAT` — disable KHR cooperative-matrix feature detection; namespace `d252-arm-no-coopmat`.
- A3 `GGML_VK_DISABLE_ASYNC` — disable backend asynchronous interface support; namespace `d252-arm-no-async`.
- A4 `GGML_VK_PREFER_HOST_MEMORY` — prefer coherent host-visible allocation; namespace `d252-arm-host-memory`.
- A5 `GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM` — prefer device-local-only allocation; namespace `d252-arm-device-local`.

Population/repeat law (`REPEAT_LAW`): each arm has at least 2 units; a variable condition stops on the first mismatch, with a maximum of 5 units (`variable_stop: 5`). Three stable units are screening stability only, not a deterministic claim. Deterministic requires five identical units. Never select favorable repeats; retain all attempted outcomes and stop at the first mismatch. Each unit is a fresh process. Execute only an arm expressly authorized by its own current dispatch; do not infer permission or ordering from this list.

Custody is append-only. Retain raw outputs, logs, request/response bytes, process/argv/environment attribution, identity/health observations, dispatch authority, and digests under that arm's namespace. Never overwrite, prune, rewrite, or cherry-pick evidence. A failed/retried unit is retained and quarantined as a distinct sibling before any new attempt. Preserve historical #248/#250 evidence byte-for-byte and consume it only as a read-only contrast.

4. Dispatch law (fail closed)
-----------------------------
No physical work without a current maintainer exact-head dispatch whose body contains the exact format `R8I3C PHYSICAL DISPATCH #252`, binds `head=<exact execution head>`, the named owner/member and exactly one frozen arm/namespace, and passes all repository producer, clean-head, subject, model, comparator, cost, request, and custody checks. A dispatch authorizes only its named arm and exact head; it does not authorize another arm, a moved head, or later repeats after authority becomes stale. Revalidate authority before each unit as required by the producer. Missing, ambiguous, malformed, stale, mismatched, unavailable, or failed checks block before launch. CI, this methodology, a green test, or an accepted predecessor is not dispatch authority.

5. Terminal derivation
----------------------
Only the retained-byte reducer in `scripts/issue252_terminal.py` may derive a terminal from authenticated retained receipts and populations. Its terminal vocabulary is exactly:
- `R8I3C_VULKAN_MECHANISM_LOCALIZED_FIX_VALIDATED`
- `R8I3C_VULKAN_MECHANISM_LOCALIZED_FIX_NOT_VALIDATED`
- `R8I3C_VULKAN_MECHANISM_UNRESOLVED`

Insufficient, absent, malformed, inconsistent, unauthenticated, or otherwise inadmissible evidence resolves to `BLOCKED` (no terminal), not a favorable interpretation. The reducer—not narrative, a runner summary, or caller-supplied status—owns population validity and terminal derivation. A localized discriminator is not automatically a validated implementation fix.

6. Hard prohibitions (Issue #252)
---------------------------------
- No comparator/2 change.
- No noise model.
- No threshold derivation.
- No c237 predictive work.
- No selected stress.
- No holdout.
- No R8-J.
- No #239 binding.
- No evidence rewrite.
- No CUDA substitution.
- No settings-search.
- No multi-factor causality claim.
- No dispatchless physical work.
- No auto-merge.

These prohibitions are not relaxed by a test result, source inference, or dispatch for a different arm. STOP for maintainer review before any physical execution.