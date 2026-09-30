METHODOLOGY AMENDMENT 002 — R8-I3B (Issue #250, PR #251)

CORRECTION PASS 5 — NO-GO comment 5852014883 (single blocker:
`indexer_top_k_boundary` off-by-one at the selection-width
equality). Implemented at the correction-pass-5 head on branch
issue-250-r8i3b-ref-runtime-boundary; base main unchanged at
bc71774dc68e7d7fddaf97bd794bbbc297e66ca5. Repository-only; zero
physical execution; the frozen METHODOLOGY.md text remains
preserved verbatim (dated-amendment discipline).

A. INDEXER TOP-K BOUNDARY — EXACT SIDES AT EQUALITY

AMENDMENT-001 §B established the pinned runtime law

  width = std::min<int64_t>(n_kv, indexer_top_k + r - 1)
        = min(n_kv, 2048 + 4 - 1) = min(n_kv, 2051)

but then described the execution transition as "below the width /
at/above the width" and encoded the reducer rule as: deterministic
side `< 2051`, variable side `>= 2051`.

Defect: that split is wrong at equality. At exactly n_kv = 2051
the computed width is min(2051, 2051) = 2051, which equals the
ENTIRE KV-cell population — the top-k selection still contains
every cell (dense attention, numerics identical to no selection).
The first population where the selection can exclude a cell is
n_kv = 2052, because min(2052, 2051) = 2051 < 2052. The old rule
therefore (a) accepted a variable-side actual count of exactly
2051 as "selective" and (b) denied a legal deterministic-side
count of exactly 2051 (proven by old-defect proof at 63c28a6).

Amended execution-boundary semantics (frozen):

  - ALL-CELLS / DENSE-EQUIVALENT SIDE: n_kv <= 2051
    (INDEXER_ALL_CELLS_MAX = INDEXER_TOP_K +
    INDEXER_COMPRESS_RATIO - 1 = INDEXER_TOPK_WIDTH = 2051)
  - SELECTIVE SIDE: n_kv >= 2052
    (INDEXER_SELECTIVE_MIN = INDEXER_ALL_CELLS_MAX + 1 = 2052)

The selective transition is never encoded as `>= 2051` anywhere.

Amended reducer predicate (`indexer_top_k_boundary` may fire only
if ALL hold; measured in ACTUAL retained token counts, never
nominal ladder labels):

  1. every deterministic-side actual token/KV count <= 2051;
  2. every variable-side actual token/KV count >= 2052;
  3. the monotone deterministic->variable ladder boundary actually
     straddles the transition: max(det_actual_counts) <= 2051 AND
     min(var_actual_counts) >= 2052;
  4. all other frozen D gates remain satisfied (prior arms did not
     localize; the deterministic boundary side is confirmed at the
     frozen five-repeat count; the variable side contains a
     mechanically demonstrated mismatch; tokenizer authority and
     runtime prompt-eval counts agree; actual counts, never nominal
     labels; no retired progress/ubatch predicate participates).

Localization claim (unchanged in scope, exact at the boundary):
when the predicate fires, the localized factor is the QSA
all-cells -> selective-mask execution boundary — the smallest
demonstrated runtime/execution boundary permitted by Issue #250.
The predicate does NOT establish that top-k is the ultimate
numerical root cause, that the indexer implementation is
defective, or that crossing 2051/2052 alone explains the
numerics; it binds only the observed deterministic->variable
transition to the source-proven execution boundary.

Equality controls (frozen test obligations): 2050 is all-cells
and can never be considered selective; 2051 is STILL all-cells
and must NOT satisfy the selective-side predicate; 2052 is the
first selective-side count; a variable side of exactly 2051 with
a deterministic side below 2051 must NOT fire; real prospective
ladders such as 1534 -> 2053 continue to fire when all
confirmation/gating conditions hold.

B. DOCUMENTATION CORRECTIONS

METHODOLOGY-AMENDMENT-001.md §B (current authority) was corrected
in place to the exact law — through 2051 cells the selection
covers the full population; starting at 2052 cells the capped
width is smaller than the population and selection becomes
genuinely selective — with a pointer to this amendment. Code
comments/constants (scripts/issue250_diagnostic.py,
scripts/issue250_terminal.py) and the test-retention audit
invariant text were updated to the boundary pair. The frozen
METHODOLOGY.md text is untouched (its predicate (a) names the
top_k crossing in qualitative terms and predicate (b) was already
retired by AMENDMENT-001).

C. NO OTHER CHANGE

Everything else from correction passes 2-4 stands unchanged:
Arm-B durable truncated-prefix custody; per-request Arm-B live
authority revalidation; prefix-population law; task-bound reset
proofs; attributed tokenizer-server authority; unknown-listener
refusal; raw tokenize-response custody; actual token-count
authority; runtime prompt-eval equality gate; retirement of
midstream_ubatch_split; wall-clock progress as diagnostic
metadata only; D two-repeat screening / five-repeat
deterministic confirmation; accepted #248 ngl=1 contrast;
true CPU-only A/B/C geometry; campaign model attestation; live
reducer authority fetch; exact namespace<->arm binding;
append-only/quarantine semantics.
