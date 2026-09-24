R8-I3A — RTX 3060 Vulkan long-context comparator/2 reference-row
nondeterminism diagnosis (Issue #248)
=======================================================================

DIAGNOSTIC-ONLY follow-up to the ACCEPTED Issue #241 generation-2
terminal `R8I3_COMPARATOR_V2_BLOCKED` (campaign head
`4e8b4fc369defe409f68da46e26d152eade4df47`, evidence root
`inferswarm01:/home/hermes/is241-campaign-v3/`, manifest self-digest
`78400bcfe9de5464fdbceca9c05c9eb1938ccd3487d7d053043d5be50a52a0eb`).
The blocked terminal is NOT reopened, reinterpreted, or relaxed here.

Phase-0 status: COMPLETE (retained-byte analysis committed under
`evidence/phase0/`; see METHODOLOGY.md for the frozen diagnostic plan
awaiting maintainer dispatch).

Key Phase-0 findings (all mechanically derived from retained bytes)
-------------------------------------------------------------------
1. Manifest reconciliation: the digest quoted by Issue #248's body
   (`a5d7f02d…`) is a SUPERSEDED pre-final snapshot of the accepted
   evidence root's SHA256SUMS (taken 2026-09-24 ~17:16Z, before the
   final head-witness row was folded in during terminal retention).
   The live manifest (356 rows, every row verifying) hashes to exactly
   the digest the accepted engineering report cited (`78400bcf…`).
   No retained campaign byte changed.
2. Custody: 192 locally mirrored phase-3 files (96 rows, 24 meta, 24
   responses, plus logs/samples) verify byte-exact against the accepted
   manifest; the retained case-3072 run receipts do not exist (the
   frozen producer aborted before receipt emission — fail-closed), so
   Phase 0 re-derives from raw bytes only.
3. Case-3072 reference-arm (RTX 3060) baseline-vs-repeat rows differ at
   ALL 8 decisions, and the difference is BROAD, not localized:
   effectively all 248,320 float32 entries per row differ
   (RMS 0.21–0.34, p99 |Δ| 0.57–0.91, max |Δ| 1.45–1.88 across
   decisions; magnitude mass concentrated in [0.1, 1.0)).
4. Winners and tokens are identical in both units at all decisions
   (argmax stable); at decision 0 the baseline top1/top2 margin (0.112)
   was SMALLER than the row max delta (1.45) — a winner flip was
   arithmetically possible and simply did not occur (the repeat's margin
   was 0.521).
5. Controls are byte-deterministic under the same observer, binaries,
   host, and process semantics: case-256 reference, case-1024 reference,
   and case-3072 candidate (RX 580). The variability is specific to the
   reference arm at the 3072-token regime.
6. Retained server logs show identical launch shape, slot selection
   (id 3, LRU), 512-token chunked prompt processing, and graph reuse
   count (7) in both units — no structural execution difference; only
   timings differ (metadata).

Hypothesis matrix and the smallest discriminating probe per mechanism
are in `evidence/phase0/phase0-analysis.json` (schema
`inferswarm.issue248.phase0-analysis/1`), produced by
`scripts/issue248_analysis.py` (stdlib-only; deterministic; re-run
byte-identical).

Diagnostic plan (frozen in METHODOLOGY.md BEFORE any physical work)
-------------------------------------------------------------------
Phase 1 — minimum repeatability probe: >=5 fresh-process diagnostic
repeats of case-3072 arm B at ngl=8, comparator binary, observer on
(namespace `d248-ref-repeats`).

Phase 2A — placement dependence: the frozen rung ladder 1/2/4/6/8 at
case-3072 arm B (namespace `d248-placement-rungs`).
Phase 2B — regime dependence: case-256/1024/3072 controls; case-4096
only under explicit dispatch preauthorization (namespace
`d248-regime-sweep`).

Phase 3 — observer vs backend localization (namespace
`d248-observer-ladder`), by increasing invasiveness:
  1. comparator observer enabled (accepted patched binary);
  2. DUAL capture in one process: comparator observer + R8-E
     observation hook capture (both hooks coexist in the patched
     binary; two independently coded capture paths reading the same
     row) — if the two captures agree within every process while rows
     still vary across processes, the capture is faithful and the
     variation is upstream of capture;
  3. R8-E-only observation binary (`dcee5bcf…`): rows captured by a
     different binary with no comparator hook;
  4. canonical no-hook binary (`21707f25…`): token-level custody only;
     plus patched-binary-observer-off runs (inert patched path).

Phase 4 — bounded one-variable interventions only when earlier phases
narrow the cause, each predeclared against a hypothesis.

Terminals: exactly the Issue #248 vocabulary (see
scripts/issue248_diagnostic.py TERMINALS). No qualification, no
comparator/2 change, no threshold work, no holdout access, no c237
execution — enforced by the tooling's namespace/authority gates and
tested by mutation in tests/test_issue248_diagnostic.py.

Authority model
---------------
Physical diagnostic execution requires a maintainer dispatch comment on
the diagnostic PR carrying the dispatch phrase, `head=<exact sha>`, and
`diagnostic-namespace=<d248-…>` as exact stripped lines from a current
OWNER/MEMBER. Verified LIVE immediately before every unit against the
exact clean HEAD and the live GitHub state: PR #249 OPEN/unmerged with
base `main` and head exactly the authorized sha, and Issue #248 OPEN —
any later HEAD movement, PR merge/close, or issue close invalidates the
authority before launch. No cached authority dict is accepted (the
runner has no authority parameter). case-4096 additionally requires an
exact stripped `case-4096:<reason>` line in the same live comment;
the authorization is comment-bound and cannot be supplied by any other
means.

Subject identity model
----------------------
The accepted #241 generation-2 runtime/device subject is held FIXED for
both arms (scripts/issue248_identity.py): every frozen field — PCI
sysfs identity, nvidia-smi identity, NVIDIA ICD, Vulkan device/UUID/
API/driver, kernel driver, negotiated link width, and max link/speed
capability — is derived from FRESH RAW OBSERVATIONS (sysfs, per-ICD
vulkaninfo, ICD inventory; read-only, no GPU compute) and compared
against the frozen constants before AND after every unit. Driver,
ICD, Vulkan, subsystem, revision, or link-identity drift fails the
unit closed. Exactly one factor may be deliberately changed under a
declared DIAGNOSTIC_ONLY intervention (single-factor, receipt-labeled,
baseline preserved); simultaneous multi-factor changes are rejected.
