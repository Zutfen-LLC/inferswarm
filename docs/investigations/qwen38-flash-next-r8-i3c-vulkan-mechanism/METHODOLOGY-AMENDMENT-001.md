# METHODOLOGY AMENDMENT 001 — 2026-09-30 (PR #253 correction round 2)

Scope of authority: correction round ordered by the maintainer NO-GO review of
PR #253 at reviewed head `875515d112af4843aa75ff94ff1c05117c1e9fd4`. Additive
only; the frozen METHODOLOGY.md text above is unchanged.

## A. Retained dispatch authority is retrieval-bound (new section 4a law)

Original text (section 4) remains authoritative for WHEN a dispatch exists.
This amendment adds WHAT retained authority must be, mechanically:

1. Every original arm dispatch and every future fix dispatch must be captured
   at authorization time by the LIVE gate (`issue252_physical.emit_capture`)
   into a retained, canonical, digest-bound capture
   (`inferswarm.issue252.dispatch-capture/2`) pinning: repository
   (`Zutfen-LLC/inferswarm`), campaign PR number, exact comment ID, exact PR
   number, commenter login and OWNER/MEMBER association, the exact immutable
   three-line body, the exact comment creation timestamp, the arm-to-namespace
   mapping, the execution-time PR state (open/unmerged/non-draft, targeting
   `main`, exact PR head equal to the authorized execution head), issue #252
   open, and the SHA-256 of the canonical raw comment bytes.
2. The reducer (`issue252_terminal`) admits retained authority ONLY by
   independently re-fetching the immutable GitHub comment by exact ID and
   requiring byte equality with the retained capture (plus the immutable
   comment law). A locally fabricated, merely self-consistent authority
   object — including one with recomputed internal digests — can never
   satisfy admission.
3. Terminal derivation does not depend on mutable current GitHub state after
   execution: PR/issue state is authenticated against the retained
   execution-time snapshot only.
4. The legacy self-consistent dispatch dict (`authority.json {"dispatch":
   {...body_sha256...}}`) is refused outright; it is retained in the corpus
   only as an adversarial rejection case.

## B. Prospective mechanism-localization contracts per arm (new section 5a law)

Five identical rows establish deterministic behavior under an arm; they never
localize a mechanism alone. Each arm's bounded mechanism/discriminator claim
additionally requires retained, digest-bound RAW observations proving the
named intervention actually changed the intended Vulkan-side runtime path
(seams verified at pinned llama.cpp `b29c606e`):

- **A1** `GGML_VK_SERIALIZE_SUBMISSIONS`: NON-TERMINAL-CAPABLE at this pin.
  The flag sets `device->serialize_submissions`
  (ggml-vulkan.cpp:7435) and the serialized path waits on the device fence
  (:18105), but no retained observable distinguishes a serialized submission
  from an unfenced batch. Deterministic contrast under A1 alone can never
  reach a localized terminal; a complete retained arm set under which no
  capable arm localizes resolves UNRESOLVED.
- **A2** `GGML_VK_DISABLE_COOPMAT`: gates only the KHR cooperative-matrix
  feature (:6600). Retained per-unit server logs must show the device
  enumeration line (:7695) with a non-KHR_coopmat matrix-core family in
  every unit. Dead-control honesty: the accepted capability line for this
  RTX 3060 subject records `NV_coopmat2`, which this control does NOT gate;
  on that subject the retained observation must show `none` (or a
  non-NV/non-KHR family) or the arm refuses localization as a dead control.
- **A3** `GGML_VK_DISABLE_ASYNC`: every retained unit's server log must
  contain the exact stderr marker the pin emits when async is disabled
  (:6727).
- **A4** `GGML_VK_PREFER_HOST_MEMORY`: retained memory-logger allocation
  lines (:7789/:2757) must include at least one HOST-typed allocation (the
  preference materially selected host-visible memory, :3812) AND at least one
  DEVICE-typed allocation (Vulkan compute placement remained active).
- **A5** `GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM`: every retained unit must
  show the sync-staging allocation line (:8603) — weight uploads routed
  through staged copies because buffers are not host-visible — and ZERO
  host-typed allocation lines.

Terminal semantics (section 5 amendment): `...FIX_NOT_VALIDATED` requires a
capable arm's mechanism observations PLUS five-repeat determinism.
`...FIX_VALIDATED` additionally requires separately authenticated fix
dispatch (same capture law), a changed Vulkan implementation/runtime commit,
five-repeat corrected determinism, and retained proof that intended Vulkan
participation remained active in the corrected run (device enumeration line
in every fixed unit's log). Narrative labels, booleans, and env-var presence
are rejected. Mechanism proof is kept strictly separate from the determinism
contrast.

## C. Observability requirement on launch geometry

The per-unit retained `server.log` (already digest-bound in every receipt)
is the mechanism-observation carrier. Runs intended to localize must launch
with the backend's device-enum/info logging enabled (`--verbose`) and, for
A4/A5, `GGML_VK_MEMORY_LOGGER` in the environment, so the contract lines are
present in retained bytes. The frozen argv/env law in `issue252_physical`
governs; any geometry change needed for these flags is a prospective,
pre-dispatch decision — never retrofitted after seeing physical outputs.
