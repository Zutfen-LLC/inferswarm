# Issue #254 Round-7 A3 Result and A5 Dispatch-Authority Record

Date: 2026-10-02  
PR: #256  
Predecessor reviewed head: `9c187ed4500a7f8fd5440888175e3a32554cdd05`

## Purpose

This is an additive custody/authority record only. It does **not** change methodology, producer behavior, reducer behavior, frozen arm definitions, acceptance law, or retained physical evidence.

Its purpose is to record the accepted Round-7 A3 physical result and the subsequent A5 preflight authority collision so that the PR head can advance without rewriting or deleting any dispatch comment that is already part of accepted evidence provenance.

## Accepted Round-7 A3 physical result

Dispatch comment:
- id: `5944397004`
- head: `9c187ed4500a7f8fd5440888175e3a32554cdd05`
- arm: `A3`

Fresh evidence root:
- `/home/hermes/is254-a3-round7/evidence`

The production producer completed two legal A3 units under the frozen case-3072 geometry.

Full-row SHA-256:
- unit 001: `9bb6e8e66f09282a98d6bb67ceabeb1119f287ae9363e1e3b3ba21567869d17e`
- unit 002: `2e5e8768da27c82495b809dad236a9490d0139aa314d2251c5ad9bfac625573d`

Unit 002 mismatched unit 001, triggering the accepted first-mismatch stop law. The A3 population is therefore variable. The mechanically derived A3-only reducer status is:

`R8I3C_REDUCER_BLOCKED_INCOMPLETE`

This is an accepted physical result, not a producer/custody failure. The retained evidence mechanically establishes that the frozen A3 factor `GGML_VK_DISABLE_ASYNC=1` did not restore deterministic fresh-process full-row behavior under the accepted case-3072 geometry.

The Round-7 physical path also exercised the corrected canonical identity normalization boundary using the real #248-shaped production observation. Receipt, producer-attestation, retained identity JSON, request/prompt, process, placement, observer, and cleanup bindings validated for both retained units.

The A3 evidence root and all predecessor Issue #254 roots remain immutable custody.

## A5 same-head dispatch preflight stop

A subsequent A5 dispatch was posted as comment:
- id: `5944607021`
- head: `9c187ed4500a7f8fd5440888175e3a32554cdd05`
- arm: `A5`

No A5 physical execution occurred.

The unmodified production `fetch_live_dispatch` authority gate correctly refused before evidence-root creation because two otherwise-valid dispatch comments targeted the same live PR head:

- `5944397004` — A3
- `5944607021` — A5

The frozen authority law requires exactly one valid live dispatch comment at the current head. The gate therefore failed closed with two valid same-head candidates.

This stop created no A5 physical evidence, no scratch/quarantine state, and no model/GPU execution.

## Provenance-preserving resolution

Do **not** delete or edit dispatch comment `5944397004`. The accepted Round-7 A3 evidence re-fetches that exact comment by ID as part of live provenance verification.

Do **not** delete or edit `5944607021` either; retain it as the historical record of the correctly refused same-head A5 authorization attempt.

Do **not** change the producer dispatch-selection law solely to bypass this collision.

This additive documentation commit intentionally advances PR #256 to a new head. Under the existing exact-head authority law, both prior comments become stale for future execution while remaining available to verify historical custody.

After exact-head maintainer review and required CI on the new head, the next legal physical action is a **fresh A5 dispatch** binding that new exact head. A5 must use a fresh evidence root and the existing frozen A5 definition unchanged.

## Scope statement

This record:
- changes no executable code;
- changes no methodology amendment;
- changes no frozen arm geometry;
- changes no reducer or terminal law;
- changes no accepted evidence;
- grants no physical execution authority by itself.

A new exact-head maintainer dispatch is still required before A5 execution.
