R8-I3A diagnostic methodology amendment 002 — correction round 3
=================================================================

Dated 2026-09-25. Repository-only correction; no physical diagnostic unit,
model workload, predictive case, or case-4096 has been executed by this
correction. The accepted #241 evidence, comparator/2 methodology, blocked
terminal, and #248 Phase-0 analysis are unchanged.

Defect (maintainer NO-GO comment 5825967767 on PR #249 at head
9b848455f3b68f479fab3d451cde144e9d861bd5)
-----------------------------------------------------------------
The offline terminal reducer accepted caller-supplied "live" authority
objects. derive_terminal(..., dispatch_authority=...) took a
namespace-keyed dictionary from its caller and structurally validated it
with D.validate_authority_payload(); a separate case4096_authority=
payload path existed with the same shape. That is not live authority: the
structural validator necessarily trusts caller-provided open_pr=True,
issue_open=True, comment ID, author association, issue/PR URL, created-at,
head SHA, and the full dispatch comment body. The round-3 unit fixture
dispatch_map() synthesized complete authority payloads with
make_authority(), labeled the result the LIVE dispatch authority map, and
derive_terminal() accepted it. Because the per-unit dispatch_sha256
digest is derived from the same caller-supplied payload, a fabricated
unit-receipt tree plus a matching fabricated authority map could satisfy
terminal provenance without any of it ever having come from GitHub.

Correction
----------
The production terminal-reduction path no longer accepts a ready-made
authority object or map as sufficient authority, in any form:

1. The dispatch_authority= and case4096_authority= parameters are
   structurally removed from derive_terminal (both the
   issue248_terminal reduction and the issue248_physical wrapper). The
   production API is derive_terminal(evidence_root, namespace, plan,
   expected_head, repo_root=None, *, health_verifier=None,
   authority_fetcher=None).

2. At terminal-reduction time the reducer mechanically derives the
   required diagnostic namespaces from the frozen plan (the unique
   values of the frozen probe map: d248-ref-repeats,
   d248-placement-rungs, d248-regime-sweep, d248-observer-ladder; the
   canonical probe shares the observer namespace and is fetched once)
   and invokes the canonical live authority fetch path
   D.require_live_dispatch — the SAME seam physical execution gates on
   (default D.fetch_dispatch_authority). There is no second, reduced
   authority implementation in the reduction. Each namespace fetch
   requires, live: local repository HEAD == exact expected head and a
   clean worktree; PR #249 OPEN, unmerged, base main, GitHub PR head ==
   the exact expected head; Issue #248 OPEN; a current OWNER/MEMBER
   top-level PR conversation comment carrying the exact stripped
   dispatch-phrase line, the exact stripped head=<sha> line, and exactly
   one diagnostic-namespace=<namespace> line.

3. Production callers pass authority_fetcher=None, which resolves to the
   real live GitHub fetcher. Omission never falls back to trusting
   caller-supplied authority: with no fetcher the real fetch runs, and
   any fetch loss (deleted or edited comment, moved head, closed
   PR/issue, GitHub failure) fails closed to
   R8I3_REDUCER_BLOCKED_INCOMPLETE with terminal null.

4. Tests inject a fetch FUNCTION (fetch_seam) whose contract mirrors the
   real fetcher's ((repo_root, expected_head, namespace, github_api) ->
   validated payload); the reducer invokes it itself once per namespace
   and asserts the fetch order. A prevalidated payload map is never an
   input; merely constructing a valid-looking dictionary never
   authorizes reduction.

5. All previously accepted cross-binding is preserved: each retained
   unit receipt's authority block must exactly equal
   D.unit_authority_block() re-derived from its namespace's LIVE-fetched
   authority (comment ID, head, namespace, created-at, association,
   PR/issue identity, dispatch body digest); all namespace authorities
   must bind one exact-head generation; case-4096 permission derives
   ONLY from the live-fetched regime-namespace comment body's single
   exact case-4096:<reason> line, cross-bound to every retained
   case-4096 unit.

Old-head defect reproduction (9b848455f3b68f479fab3d451cde144e9d861bd5)
-----------------------------------------------------------------------
At the old head, the completely synthetic namespace-keyed dispatch_map()
plus matching retained unit authority blocks derived a terminal with NO
GitHub fetch and NO test injection seam: derive_terminal accepted the
caller-supplied map directly. On the corrected head the same synthetic
map cannot even be passed (the parameters are removed — TypeError), and
a fully self-consistent fabricated receipt tree blocks when the live
fetch seam returns nothing. The same synthetic payloads authorize only
when explicitly returned through the injected test fetch function, which
models the live-fetch seam. Mutation controls (18 required classes) are
retained in tests/test_issue248_diagnostic.py::ReducerLiveFetchMatrix and
the inherited DispatchProvenanceMatrix / Case4096FullAuthorityMatrix.
