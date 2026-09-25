## R8-I3A physical diagnostic terminal — Issue #248 final report

Physical campaign executed 2026-09-25 under the four live exact-head
dispatch comments at PR #249 head `3f36ef1a518065bdc848cb66f6f26d94b34319f4`.
Terminal (machine-derived): `R8I3_REF_NONDETERMINISM_UNRESOLVED`.

1. **Heads**: starting main `d8803570ace24174754aab4ee33cec4003ab3bcc`
   (unchanged, final identical); diagnostic branch head `3f36ef1a…`
   throughout (no post-dispatch movement; campaign + reduction executed
   at the exact dispatched head).
2. **Accepted #241 authority consumed**: campaign head
   `4e8b4fc369defe409f68da46e26d152eade4df47`; external evidence root
   `inferswarm01:/home/hermes/is241-campaign-v3/`, 356-row SHA256SUMS
   self-digest `78400bcfe9de5464fdbceca9c05c9eb1938ccd3487d7d053043d5be50a52a0eb`
   (verified live before launch, Phase-0 committed analysis).
3. **Retained-byte verification**: external campaign evidence root
   `inferswarm01:/home/hermes/is248-campaign/evidence/` — 534-row
   SHA256SUMS, self-digest
   `af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc`,
   every row verified (`sha256sum -c` 534/534 OK); opening attestation
   `fc76fa30…` / closing `9b6f9150…` bound to every unit; pre-correction
   unit retained quarantined and non-terminal-bearing.
4. **Per-decision case-3072 stats** (5 fresh repeats, 10 pairs): d0
   max |Δ| 1.43–1.88 / RMS 0.255–0.281 / ~248,320 of 248,320 entries
   unequal, zero NaN/Inf, in EVERY pair; d1–d7 among the four
   winner-stable repeats max |Δ| 0.87–2.6 / RMS 0.16–0.40. The
   baseline-001 winner-flip pair shows cascaded d1–d7 max |Δ| ~14–18
   (committed-context divergence, not per-decision noise). Full matrix
   in `evidence/physical/physical-verification.txt`.
5. **Controls**: case-256 and case-1024 reference arm byte-deterministic
   across fresh processes (rows identical); case-3072 RX580 candidate
   control from accepted #241 evidence (byte-deterministic there) — not
   re-executed here (diagnostic scope is the reference arm).
6. **Repeat reproducibility**: phenomenon REPRODUCED — 5/5 fresh
   processes pairwise row-distinct at case-3072; winner sequence stable
   in 4/5 (the accepted sequence `[328, 760, 324, 55965, 51624, 29014,
   34227, 18030]`), flipped in one fresh process (`[561, 324, 55965,
   51624, 29014, 34227, 18030, 16382]` — d0/d1/d7 differ; exact lists
   retained in unit receipts).
7. **Placement localization**: rows distinct at EVERY rung
   ngl∈{1,2,4,6,8} (2/2 per rung); placement does not remove the
   variation — including ngl=1 (near-all-CPU).
8. **Regime localization**: 256/1024 deterministic, 3072 variable —
   variation is regime-specific (long-context), reproduced across all
   probe families.
9. **Observer comparison**: dual-capture byte-equal in-process (both
   dual units: comparator row0 == R8-E pos0 row0, 993,280 bytes) while
   rows vary across processes — observer/capture excluded as cause.
   Canonical (hook-free) binary tokens DIFFERED across its two fresh
   processes; obs-off tokens stable in-pair but rows unavailable by
   design (no hooks). The unobserved path itself varies.
9b. **Within canonical caveat**: canonical pair divergence is token-
   level only (no rows by design); it corroborates but rows-level
   canonical comparison is not available.
10. **One-variable interventions**: none executed — Phase 4 requires
    earlier-phase narrowing to justify an intervention; the honest
    result is that narrowing did not localize (see 14), so no
    intervention was justified. No "settings until deterministic".
11. **Identities**: every probe on inferswarm01, RTX 3060 reference
    arm B (BDF `00000000:03:00.0`, GPU-UUID
    `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, driver 610.57.04,
    NVIDIA ICD, Vulkan 1.4.341, canonical `21707f25…` / r8e-obs
    `dcee5bcf…` / comparator `6f8b56bd…` binaries); frozen subject
    identity verified pre/post on all 31 units — zero drift.
12. **Health**: all 31 units clean — no fatal platform findings, no
    identity problems, no kernel/AER device-fault evidence in retained
    journal windows.
13. **Earliest divergence boundary**: the decision-0 full-vocabulary
    row of the FIRST generation step already differs broadly across
    fresh processes in every pair — divergence arises at or before the
    first generation row computation, upstream of committed-token
    cascades.
14. **Terminal**: `R8I3_REF_NONDETERMINISM_UNRESOLVED` (reduction
    record `evidence/physical/terminal-reduction.json`, complete,
    problems=[]).
15. **Prohibitions proof**: zero predictive `c237-*` execution
    (namespace-refused structurally), zero holdout plaintext/decrypt/
    secret access, zero threshold derivation (no numeric tolerance
    exists; determinism judged by digest equality), zero case-4096
    execution (not authorized by dispatch; never attempted).
16. **#241 terminal**: `R8I3_COMPARATOR_V2_BLOCKED` remains accepted
    historical evidence — untouched, unmodified, uninterpreted. This
    issue's terminal qualifies nothing.
17. **Future work**: evidence supports a methodology-versioning
    proposal (reference-repeat/noise model per maintainer option 2)
    and/or reference-implementation investigation upstream (option 1);
    it does NOT support a backend substitution (option 3) — the same
    subject is deterministic at 256/1024 — nor comparator retirement
    (option 4). The choice belongs to the maintainer per the issue's
    decision section.
